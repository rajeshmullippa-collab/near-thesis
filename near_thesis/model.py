"""Bull / base / bear valuation model with explicit, editable assumptions.

    holder_earnings(T) = intents_volume(T) * take_rate(T) * value_accrual_share
                       + l1_fees(T) * l1_fee_burn_share
    network_value(T)   = holder_earnings(T) * exit_multiple
    value_per_token(T) = network_value(T) / supply(T)
    present_value      = value_per_token(T) / (1 + discount_rate) ** T

and a reverse model: holding a scenario's other assumptions fixed, which
NEAR Intents volume growth rate would make present_value equal today's
price? That answer is usually more useful than the forward number, because
it turns "is NEAR cheap?" into "do you believe volume grows this fast?".
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "config" / "assumptions.yaml"


def load_assumptions(path: Path | str = ASSUMPTIONS) -> dict:
    return yaml.safe_load(Path(path).read_text())


def resolve_start(cfg: dict, facts: dict) -> dict:
    s = dict(cfg["start"])
    data_map = {
        "intents_volume_start_usd": facts.get("intents_volume_30d_annualized"),
        "intents_take_rate_bps": facts.get("intents_take_rate_bps_30d"),
        "l1_fees_start_usd": facts.get("l1_fees_usd_ttm"),
        "supply_growth": facts.get("protocol_max_inflation_rate"),
    }
    for k, v in s.items():
        if v == "from_data":
            if data_map.get(k) is None:
                raise ValueError(f"assumption {k} is from_data but the snapshot has no value for it")
            s[k] = float(data_map[k])
        else:
            s[k] = float(v)
    s["price_usd"] = float(facts["price_usd"])
    s["supply_near"] = float(facts["total_supply_near"])
    s["market_cap_usd"] = float(facts["market_cap_usd"])
    return s


def run_scenario(start: dict, sc: dict, horizon: int) -> dict:
    T = horizon
    vol = start["intents_volume_start_usd"] * (1 + sc["intents_volume_cagr"]) ** T
    take_bps = start["intents_take_rate_bps"] * (1 + sc["take_rate_change"])
    intents_rev = vol * take_bps / 1e4
    l1 = start["l1_fees_start_usd"] * (1 + sc["l1_fee_cagr"]) ** T
    earnings = intents_rev * sc["value_accrual_share"] + l1 * sc["l1_fee_burn_share"]
    value = earnings * sc["exit_multiple"]
    supply = start["supply_near"] * (1 + start["supply_growth"]) ** T
    per_token_T = value / supply
    pv = per_token_T / (1 + sc["discount_rate"]) ** T
    # Reverse: volume CAGR that makes pv == today's price.
    need_value = start["price_usd"] * (1 + sc["discount_rate"]) ** T * supply
    need_earnings = need_value / sc["exit_multiple"]
    need_intents_rev = (need_earnings - l1 * sc["l1_fee_burn_share"]) / max(sc["value_accrual_share"], 1e-12)
    need_vol = need_intents_rev / (take_bps / 1e4) if take_bps > 0 else float("inf")
    implied_cagr = (need_vol / start["intents_volume_start_usd"]) ** (1 / T) - 1 if need_vol > 0 else -1.0
    return {
        "inputs": sc,
        "intents_volume_usd_T": vol,
        "take_rate_bps_T": take_bps,
        "intents_revenue_usd_T": intents_rev,
        "l1_fees_usd_T": l1,
        "holder_earnings_usd_T": earnings,
        "network_value_usd_T": value,
        "supply_near_T": supply,
        "value_per_token_usd_T": per_token_T,
        "present_value_per_token_usd": pv,
        "pv_vs_price": pv / start["price_usd"] - 1,
        "implied_intents_volume_cagr_for_price": implied_cagr,
        "implied_intents_volume_usd_T_for_price": need_vol,
    }


def run(facts: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_assumptions()
    T = int(cfg["horizon_years"])
    start = resolve_start(cfg, facts)
    out = {"horizon_years": T, "start": start, "scenarios": {}}
    for name, sc in cfg["scenarios"].items():
        out["scenarios"][name] = run_scenario(start, sc, T)
    base = cfg["scenarios"]["base"]
    sens = cfg.get("sensitivity", {})
    grid = []
    for g in sens.get("intents_volume_cagr", []):
        row = []
        for m in sens.get("exit_multiple", []):
            row.append(run_scenario(start, base | {"intents_volume_cagr": g, "exit_multiple": m}, T)["present_value_per_token_usd"])
        grid.append(row)
    out["sensitivity"] = {
        "rows_intents_volume_cagr": sens.get("intents_volume_cagr", []),
        "cols_exit_multiple": sens.get("exit_multiple", []),
        "present_value_per_token_usd": grid,
    }
    return out
