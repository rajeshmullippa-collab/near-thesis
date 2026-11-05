"""Turn raw snapshots into one tidy daily table plus point-in-time facts.

Conventions
-----------
* All dates are UTC calendar days.
* NEAR amounts in yoctoNEAR (1e-24) are converted to NEAR.
* Nothing is interpolated or invented: a day a source does not cover is NaN,
  and any metric that cannot be computed is reported as ``None`` with a reason.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import sources

YOCTO = 1e24


def _day(value) -> pd.Timestamp:
    """Parse an ISO string, a unix timestamp (s), or a string holding YYYY-MM-DD."""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return pd.Timestamp(int(value), unit="s").normalize()
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    if not m:
        raise ValueError(f"unparseable date {value!r}")
    return pd.Timestamp(m.group(0))


def _series_from_pairs(pairs, name: str) -> pd.Series:
    if not pairs:
        return pd.Series(dtype=float, name=name)
    s = pd.Series({_day(t): float(v) for t, v in pairs}, name=name).sort_index()
    return s[~s.index.duplicated(keep="last")]


def nearblocks_daily() -> pd.DataFrame:
    rows = sources.load("nearblocks_charts")["charts"]
    df = pd.DataFrame(rows)
    df.index = [_day(d) for d in df.pop("date")]
    df = df.apply(pd.to_numeric, errors="coerce")
    out = pd.DataFrame(index=df.index)
    out["txns"] = df["txns"]
    out["active_accounts"] = df["active_accounts"]
    out["new_accounts"] = df["new_accounts"]
    out["deleted_accounts"] = df["deleted_accounts"]
    out["active_contracts"] = df["active_contracts"]
    out["new_contracts"] = df["new_contracts"]
    out["gas_used_tgas"] = df["gas_used"] / 1e12
    out["fee_near"] = df["txn_fee"] / YOCTO
    out["fee_usd"] = df["txn_fee_usd"]
    out["transfer_volume_usd"] = df["txn_volume_usd"]
    out["total_supply_near"] = df["total_supply"] / YOCTO
    out["price_usd_nb"] = df["near_price"].replace(0, np.nan)
    out["market_cap_usd_nb"] = df["market_cap"].replace(0, np.nan)
    return out.sort_index()


def llama_daily() -> pd.DataFrame:
    parts = []
    tvl = sources.load("llama_chain_tvl") or []
    parts.append(_series_from_pairs([(r["date"], r["tvl"]) for r in tvl], "defi_tvl_usd"))
    for name, col in [
        ("llama_intents_volume", "intents_volume_usd"),
        ("llama_intents_fees", "intents_fees_usd"),
        ("llama_intents_revenue", "intents_revenue_usd"),
        ("llama_chain_fees", "chain_fees_usd_llama"),
        ("llama_chain_dex", "dex_volume_usd"),
    ]:
        d = sources.load(name)
        parts.append(_series_from_pairs((d or {}).get("totalDataChart", []), col))
    st = sources.load("llama_stablecoins") or []
    parts.append(
        _series_from_pairs(
            [(r["date"], (r.get("totalCirculatingUSD") or {}).get("peggedUSD", np.nan)) for r in st],
            "stablecoins_usd",
        )
    )
    return pd.concat(parts, axis=1).sort_index()


def coingecko_daily() -> pd.DataFrame:
    d = sources.load("coingecko_market_chart")
    if not d or "prices" not in d:
        return pd.DataFrame(columns=["price_usd_cg", "market_cap_usd_cg", "volume_usd_cg"])
    cols = {"prices": "price_usd_cg", "market_caps": "market_cap_usd_cg", "total_volumes": "volume_usd_cg"}
    parts = []
    for k, c in cols.items():
        s = pd.Series({pd.Timestamp(int(t), unit="ms").normalize(): v for t, v in d[k]}, name=c)
        parts.append(s[~s.index.duplicated(keep="last")])
    return pd.concat(parts, axis=1)


def daily() -> pd.DataFrame:
    """One row per UTC day, all sources joined, plus derived columns."""
    df = nearblocks_daily().join(llama_daily(), how="outer").join(coingecko_daily(), how="left")
    # Price: CoinGecko where available (it is the market reference), else NearBlocks.
    df["price_usd"] = df["price_usd_cg"].combine_first(df["price_usd_nb"]) if "price_usd_cg" in df else df["price_usd_nb"]
    df["net_supply_change_near"] = df["total_supply_near"].diff()
    df["supply_growth_365d"] = df["total_supply_near"].pct_change(365, fill_method=None)
    df["fee_per_txn_usd"] = df["fee_usd"] / df["txns"]
    df["txns_per_active_account"] = df["txns"] / df["active_accounts"]
    df["intents_volume_per_active_account"] = df["intents_volume_usd"] / df["active_accounts"]
    df = df[df.index >= pd.Timestamp("2020-07-21")]
    # Drop today's partial row if a source has not closed the day yet.
    return df.sort_index()


@dataclass
class Facts:
    as_of: str
    values: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)


def _ttm(s: pd.Series, end: pd.Timestamp, days: int = 365) -> float | None:
    w = s[(s.index > end - pd.Timedelta(days=days)) & (s.index <= end)].dropna()
    if len(w) < days * 0.9:
        return None
    return float(w.sum())


def _mean(s: pd.Series, end: pd.Timestamp, days: int) -> float | None:
    w = s[(s.index > end - pd.Timedelta(days=days)) & (s.index <= end)].dropna()
    return float(w.mean()) if len(w) else None


def _yoy(s: pd.Series, end: pd.Timestamp, days: int = 30) -> float | None:
    now = _mean(s, end, days)
    then = _mean(s, end - pd.Timedelta(days=365), days)
    if not now or not then:
        return None
    return now / then - 1


def staking_facts() -> dict:
    v = sources.load("rpc_validators")
    blk = sources.load("rpc_block")
    stakes = sorted((int(x["stake"]) / YOCTO for x in v["current_validators"]), reverse=True)
    total = sum(stakes)
    supply = int(blk["total_supply"]) / YOCTO
    cum, nak = 0.0, None
    for i, s in enumerate(stakes, 1):
        cum += s
        if nak is None and cum > total / 3:
            nak = i
    top10 = sum(stakes[:10]) / total
    return {
        "validators": len(stakes),
        "total_stake_near": total,
        "staked_share_of_supply": total / supply,
        "nakamoto_coefficient": nak,
        "top10_stake_share": top10,
        "stake_distribution": stakes,
        "epoch_height": v.get("epoch_height"),
    }


def protocol_facts() -> dict:
    pc = sources.load("rpc_protocol_config")
    blk = sources.load("rpc_block")
    num, den = pc["max_inflation_rate"]
    pr_num, pr_den = pc["protocol_reward_rate"]
    bgr = pc.get("burnt_gas_reward") or [3, 10]
    return {
        "protocol_version": pc["protocol_version"],
        "max_inflation_rate": num / den,
        "protocol_treasury_rate": pr_num / pr_den if pr_den else 0.0,
        "contract_reward_share_of_gas": bgr[0] / bgr[1],
        "min_burn_share_of_fees": 1 - bgr[0] / bgr[1],
        "total_supply_near": int(blk["total_supply"]) / YOCTO,
        "block_height": blk["height"],
        "gas_price_yocto": int(blk["gas_price"]),
    }


def dev_activity() -> pd.DataFrame:
    d = sources.load("github_commit_activity") or {}
    cols = {}
    for repo, weeks in d.items():
        if isinstance(weeks, list) and weeks:
            cols[repo] = pd.Series({pd.Timestamp(w["week"], unit="s"): w["total"] for w in weeks})
    return pd.DataFrame(cols).sort_index().fillna(0) if cols else pd.DataFrame()


def lead_lag(df: pd.DataFrame, leader: str, targets: list[str], max_lag_weeks: int = 8, since: str | None = None) -> dict:
    """Correlation of weekly log-changes: corr(leader change at t, target change at t+lag).

    A positive best lag means the leader moves first. This is a descriptive
    statistic on a short sample, not a causal test, and the thesis treats it so.
    """
    w = df[[leader] + targets].copy()
    if since:
        w = w[w.index >= pd.Timestamp(since)]
    w = w.resample("W-SUN").mean()
    w = np.log(w.where(w > 0)).diff()
    out = {}
    for t in targets:
        lags = {}
        for lag in range(-max_lag_weeks, max_lag_weeks + 1):
            pair = pd.concat([w[leader], w[t].shift(-lag)], axis=1).dropna()
            if len(pair) >= 20:
                lags[lag] = float(pair.corr().iloc[0, 1])
        if lags:
            best = max(lags, key=lambda k: abs(lags[k]))
            out[t] = {"significance_threshold_95": 2 / math.sqrt(max(len(w[leader].dropna()), 1)), "by_lag": lags, "best_lag_weeks": best, "best_corr": lags[best], "corr_lag0": lags.get(0), "n_weeks": int(w[leader].notna().sum())}
    return out


def facts(df: pd.DataFrame | None = None) -> Facts:
    df = daily() if df is None else df
    # "as of" = last day NearBlocks has closed (its final row can be partial).
    nb_last = df["txns"].dropna().index.max()
    end = nb_last - pd.Timedelta(days=1)
    il = df["intents_volume_usd"].dropna()
    intents_end = il.index.max() - pd.Timedelta(days=1) if len(il) else None
    v: dict = {}
    n: dict = {}
    stats = sources.load("nearblocks_stats")["stats"][0]
    v["price_usd"] = float(stats["near_price"])
    v["market_cap_usd"] = float(stats["market_cap"])
    v["circulating_supply_near"] = int(float(stats["circulating_supply"])) / YOCTO
    v["total_supply_near"] = int(float(stats["total_supply"])) / YOCTO
    v["fdv_usd"] = v["price_usd"] * v["total_supply_near"]
    v["ath_price_usd"] = float(stats["high_all"])
    v["lifetime_txns"] = int(stats["total_txns"])
    for col, label in [("txns", "txns"), ("active_accounts", "active_accounts"), ("new_accounts", "new_accounts"), ("fee_usd", "l1_fees_usd"), ("fee_near", "l1_fees_near")]:
        v[f"{label}_30d_avg"] = _mean(df[col], end, 30)
        v[f"{label}_yoy"] = _yoy(df[col], end)
        peak_day = df[col].rolling(30).mean().idxmax()
        v[f"{label}_30d_avg_peak"] = float(df[col].rolling(30).mean().max())
        v[f"{label}_30d_avg_peak_date"] = peak_day.strftime("%Y-%m-%d")
    v["l1_fees_usd_ttm"] = _ttm(df["fee_usd"], end)
    v["l1_fees_near_ttm"] = _ttm(df["fee_near"], end)
    v["defi_tvl_usd"] = float(df["defi_tvl_usd"].dropna().iloc[-1]) if df["defi_tvl_usd"].notna().any() else None
    v["defi_tvl_usd_yoy"] = _yoy(df["defi_tvl_usd"], df["defi_tvl_usd"].dropna().index.max(), 7)
    if df["stablecoins_usd"].notna().any():
        v["stablecoins_usd"] = float(df["stablecoins_usd"].dropna().iloc[-1])
        v["stablecoins_usd_yoy"] = _yoy(df["stablecoins_usd"], df["stablecoins_usd"].dropna().index.max(), 7)
    if intents_end is not None:
        v["intents_as_of"] = intents_end.strftime("%Y-%m-%d")
        v["intents_volume_30d_avg"] = _mean(df["intents_volume_usd"], intents_end, 30)
        v["intents_volume_ttm"] = _ttm(df["intents_volume_usd"], intents_end)
        v["intents_volume_yoy"] = _yoy(df["intents_volume_usd"], intents_end)
        v["intents_volume_alltime"] = float(il.sum())
        v["intents_first_day"] = il.index.min().strftime("%Y-%m-%d")
        v["intents_fees_ttm"] = _ttm(df["intents_fees_usd"], intents_end)
        v["intents_revenue_ttm"] = _ttm(df["intents_revenue_usd"], intents_end)
        v["intents_revenue_30d_annualized"] = (_mean(df["intents_revenue_usd"], intents_end, 30) or 0) * 365
        v["intents_volume_30d_annualized"] = (v["intents_volume_30d_avg"] or 0) * 365
        if v["intents_volume_ttm"] and v["intents_revenue_ttm"]:
            v["intents_take_rate_bps_ttm"] = v["intents_revenue_ttm"] / v["intents_volume_ttm"] * 1e4
        if v.get("intents_revenue_30d_annualized") and v.get("intents_volume_30d_annualized"):
            v["intents_take_rate_bps_30d"] = v["intents_revenue_30d_annualized"] / v["intents_volume_30d_annualized"] * 1e4
        for mcol in ["intents_fees_ttm", "intents_revenue_ttm"]:
            if v.get(mcol) is None:
                n[mcol] = "fewer than 330 days of DefiLlama fee data; see the 30-day annualized figure"
    # Supply and inflation.
    ts = df["total_supply_near"].dropna()
    ts = ts[ts.index <= end]
    v["supply_growth_365d"] = float(ts.iloc[-1] / ts[ts.index <= end - pd.Timedelta(days=365)].iloc[-1] - 1)
    last90 = ts[ts.index > end - pd.Timedelta(days=90)]
    v["supply_growth_90d_annualized"] = float((last90.iloc[-1] / last90.iloc[0]) ** (365 / (len(last90) - 1)) - 1)
    v["net_issuance_near_per_day_90d"] = float(last90.diff().mean())
    pf = protocol_facts()
    v.update({f"protocol_{k}": val for k, val in pf.items()})
    v["burn_near_ttm_min"] = (v["l1_fees_near_ttm"] or 0) * pf["min_burn_share_of_fees"]
    year_ago = ts[ts.index <= end - pd.Timedelta(days=365)].iloc[-1]
    v["net_supply_change_near_ttm"] = float(ts.iloc[-1] - year_ago)
    v["gross_issuance_near_ttm_est"] = v["net_supply_change_near_ttm"] + v["burn_near_ttm_min"]
    if v["gross_issuance_near_ttm_est"]:
        v["burn_offset_share_of_issuance"] = v["burn_near_ttm_min"] / v["gross_issuance_near_ttm_est"]
    rw = sources.load("rpc_revenue_wallets") or {}
    bal = {a: int(x["amount"]) / YOCTO for a, x in rw.items() if x.get("amount")}
    if bal:
        v["revenue_wallet_balances_near"] = bal
        v["buyback_wallet_balance_near"] = bal.get("buybacks.multisignature.near")
    # Revenue vs emissions (USD, at today's price): how far is NEAR from being a net sink?
    if v.get("gross_issuance_near_ttm_est"):
        v["emissions_usd_annual_at_price"] = v["gross_issuance_near_ttm_est"] * v["price_usd"]
        sink = (v.get("intents_revenue_30d_annualized") or 0) + (v.get("l1_fees_usd_ttm") or 0)
        v["revenue_plus_burn_usd_annual"] = sink
        v["revenue_plus_burn_to_emissions"] = sink / v["emissions_usd_annual_at_price"]
    if v.get("intents_volume_30d_annualized"):
        v["intents_annualized_volume_to_market_cap"] = v["intents_volume_30d_annualized"] / v["market_cap_usd"]
    sf = staking_facts()
    v.update({f"staking_{k}": val for k, val in sf.items() if k != "stake_distribution"})
    # Real staking yield ~ nominal inflation / staked share (all issuance goes to validators/delegators).
    v["staking_nominal_yield_est"] = v["supply_growth_90d_annualized"] / sf["staked_share_of_supply"]
    v["staking_real_yield_est"] = (1 + v["staking_nominal_yield_est"]) / (1 + v["supply_growth_90d_annualized"]) - 1
    n["staking_nominal_yield_est"] = "Estimate: annualized net supply growth divided by the staked share. Validator commissions (typically 1-10%) come out of it."
    # Valuation ratios.
    v["market_cap_to_l1_fees_ttm"] = v["market_cap_usd"] / v["l1_fees_usd_ttm"] if v["l1_fees_usd_ttm"] else None
    if v.get("intents_revenue_30d_annualized"):
        v["market_cap_to_intents_revenue_ann"] = v["market_cap_usd"] / v["intents_revenue_30d_annualized"]
    # Developer activity.
    dev = dev_activity()
    if not dev.empty:
        tot = dev.sum(axis=1)
        v["dev_commits_last_12w"] = float(tot.iloc[-12:].sum())
        v["dev_commits_prior_12w"] = float(tot.iloc[-24:-12].sum())
        v["dev_commits_last_52w"] = float(tot.iloc[-52:].sum())
        v["dev_repos_tracked"] = int(dev.shape[1])
    else:
        n["dev_commits"] = "GitHub commit statistics were not available in this snapshot."
    # Hypothesis test: does Intents volume lead usage or price?
    v["lead_lag"] = lead_lag(df, "intents_volume_usd", ["price_usd", "txns", "active_accounts", "defi_tvl_usd"], since="2025-01-01")
    v["lead_lag_price_leader"] = lead_lag(df, "price_usd", ["txns", "active_accounts", "intents_volume_usd"], since="2025-01-01")
    return Facts(as_of=end.strftime("%Y-%m-%d"), values=v, notes=n)


def clean(obj):
    """Make values JSON-safe (NaN -> None, numpy -> python)."""
    if isinstance(obj, dict):
        return {str(k): clean(x) for k, x in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(x) for x in obj]
    if isinstance(obj, (np.floating, float)):
        return None if math.isnan(float(obj)) or math.isinf(float(obj)) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj
