"""Write the static dashboard (docs/index.html) and the evidence table (EVIDENCE.md).

The dashboard is one self-contained HTML file: the data is embedded, Chart.js
is vendored in docs/vendor, so it works from GitHub Pages and from file://.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import metrics, sources

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TEMPLATE = Path(__file__).parent / "templates" / "index.html"


def _pct(x, d=0):
    return "n/a" if x is None else f"{x * 100:+.{d}f}%"


def _p(x, d=1):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def _usd(x):
    if x is None:
        return "n/a"
    a = abs(x)
    for div, s in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"${x / div:,.2f}{s}"
    return f"${x:,.2f}"


def _n(x):
    if x is None:
        return "n/a"
    a = abs(x)
    for div, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{x / div:,.2f}{s}"
    return f"{x:,.0f}"


def _weekly(df: pd.DataFrame, cols: list[str], since: str, how: str = "mean") -> dict:
    w = df.loc[df.index >= since, cols]
    w = w.resample("W-SUN").mean() if how == "mean" else w.resample("W-SUN").last()
    return {
        "labels": [d.strftime("%Y-%m-%d") for d in w.index],
        **{c: [None if pd.isna(x) else round(float(x), 6) for x in w[c]] for c in cols},
    }


def sentences(v: dict, model: dict) -> dict:
    """One plain sentence per chart, computed from the numbers (never hand-typed)."""
    ll = v["lead_lag"]
    thr = next(iter(ll.values())).get("significance_threshold_95", 0.2)
    strongest = max(ll.items(), key=lambda kv: abs(kv[1]["best_corr"]))
    base = model["scenarios"]["base"]
    return {
        "usage": (
            f"L1 activity is down sharply from its peak: transactions average {_n(v['txns_30d_avg'])}/day over the last 30 days "
            f"({_pct(v['txns_yoy'])} year on year, peak {_n(v['txns_30d_avg_peak'])}/day around {v['txns_30d_avg_peak_date']}), "
            f"and active accounts {_n(v['active_accounts_30d_avg'])}/day ({_pct(v['active_accounts_yoy'])} YoY)."
        ),
        "intents_vs_price": (
            f"NEAR Intents settled {_usd(v.get('intents_volume_30d_avg'))}/day over the last 30 days ({_pct(v.get('intents_volume_yoy'))} YoY) "
            f"and {_usd(v.get('intents_volume_ttm'))} in the last 365 days, while NEAR trades at {_usd(v['price_usd'])}."
        ),
        "fees": (
            ("Intents now out-earns the L1: " if (v.get("intents_revenue_30d_annualized") or 0) > (v["l1_fees_usd_ttm"] or 0) else "The L1 still out-earns Intents: ")
            + f"NEAR's captured Intents revenue runs at {_usd(v.get('intents_revenue_30d_annualized'))}/yr "
            f"(last 30 days annualized) against {_usd(v['l1_fees_usd_ttm'])} of L1 gas fees in the last 365 days."
        ),
        "supply": (
            f"Supply grew {_p(v['supply_growth_365d'], 2)} over the last 365 days, in line with the protocol's "
            f"{_p(v['protocol_max_inflation_rate'], 1)} max inflation; fee burn offset only {_p(v.get('burn_offset_share_of_issuance'), 1)} of issuance."
        ),
        "tvl": (
            f"DeFi TVL on NEAR is {_usd(v.get('defi_tvl_usd'))} ({_pct(v.get('defi_tvl_usd_yoy'))} YoY) and stablecoins "
            f"{_usd(v.get('stablecoins_usd'))} ({_pct(v.get('stablecoins_usd_yoy'))} YoY): capital parked on NEAR is small next to the volume flowing through Intents."
        ),
        "staking": (
            f"{_p(v['staking_staked_share_of_supply'])} of supply is staked across {v['staking_validators']} validators; "
            f"the largest {v['staking_nakamoto_coefficient']} hold more than one third of stake (top 10: {_p(v['staking_top10_stake_share'])})."
        ),
        "devs": (
            f"The {v.get('dev_repos_tracked', 0)} tracked core repositories logged {_n(v.get('dev_commits_last_12w'))} commits in the last 12 weeks "
            f"vs {_n(v.get('dev_commits_prior_12w'))} in the 12 before."
            if v.get("dev_commits_last_12w") is not None
            else "Developer-activity data was not available in this snapshot."
        ),
        "lead_lag": (
            f"The strongest weekly correlation between Intents volume changes and any target is r = {strongest[1]['best_corr']:+.2f} "
            f"({strongest[0]}, lag {strongest[1]['best_lag_weeks']} weeks) against a noise band of ±{thr:.2f}; for price the best is "
            f"r = {ll['price_usd']['best_corr']:+.2f} at lag {ll['price_usd']['best_lag_weeks']}, "
            + ("so Intents volume does not reliably lead price." if abs(ll["price_usd"]["best_corr"]) < thr or ll["price_usd"]["best_lag_weeks"] <= 0 else "a positive lead worth watching.")
        ),
        "scenarios": (
            f"On cash flows alone the base case is worth {_usd(base['present_value_per_token_usd'])} per NEAR today vs a {_usd(v['price_usd'])} price; "
            f"holding base assumptions, today's price implies Intents volume compounding {_p(base['implied_intents_volume_cagr_for_price'], 0)} a year for {model['horizon_years']} years."
        ),
    }


def build(df: pd.DataFrame, facts: metrics.Facts, model: dict, chart_paths: dict, offline: bool) -> None:
    v = facts.values
    sent = sentences(v, model)
    man = sources.manifest()
    dev = metrics.dev_activity()
    series = {
        "usage": _weekly(df, ["txns", "active_accounts"], "2023-01-01"),
        "intents_vs_price": _weekly(df, ["intents_volume_usd", "price_usd"], "2024-12-01"),
        "fees": _weekly(df, ["fee_usd", "intents_fees_usd", "intents_revenue_usd"], "2025-01-01"),
        "supply": _weekly(df, ["total_supply_near", "supply_growth_365d"], "2021-01-01", how="last"),
        "tvl": _weekly(df, ["defi_tvl_usd", "stablecoins_usd"], "2023-01-01"),
    }
    if not dev.empty:
        tot = dev.sum(axis=1)
        series["devs"] = {"labels": [d.strftime("%Y-%m-%d") for d in tot.index], "commits": [int(x) for x in tot.values]}
    stakes = metrics.staking_facts()["stake_distribution"]
    tot_stake = sum(stakes)
    cum, c = [], 0.0
    for s in stakes:
        c += s
        cum.append(round(c / tot_stake, 5))
    series["staking"] = {"cumulative_share": cum}
    series["lead_lag"] = v["lead_lag"]
    q = sources.PROVENANCE
    cards = [
        ("usage", "L1 activity", [q["nearblocks_charts"]], "Columns txns, active_accounts; weekly mean of daily values."),
        ("intents_vs_price", "NEAR Intents volume vs price", [q["llama_intents_volume"], q["coingecko_market_chart"]], "Daily volume (USD) as reported by DefiLlama's near-intents adapter."),
        ("fees", "Fees and captured revenue", [q["nearblocks_charts"], q["llama_intents_fees"], q["llama_intents_revenue"]], "L1: txn_fee_usd. Intents: gross fees vs NEAR's captured revenue (DefiLlama methodology: swept into revenue wallets, used for buybacks since 2026-02-23)."),
        ("supply", "Supply and inflation", [q["nearblocks_charts"], q["rpc_protocol_config"]], "Trailing-365-day % change of total_supply; protocol max_inflation_rate from RPC."),
        ("tvl", "DeFi TVL and stablecoins", [q["llama_chain_tvl"], q["llama_stablecoins"]], "DefiLlama chain-level series for NEAR."),
        ("staking", "Stake concentration", [q["rpc_validators"]], "Cumulative share of stake, validators sorted largest first."),
        ("devs", "Developer activity", [q["github_commit_activity"]], "Sum of weekly commits across tracked repositories (a sample of the ecosystem)."),
        ("lead_lag", "Hypothesis test: does Intents volume lead?", ["metrics.lead_lag() on the joined daily table"], "Pearson correlation of weekly log-changes at lags of -8..+8 weeks, Jan 2025 onward."),
        ("scenarios", "Valuation scenarios", ["config/assumptions.yaml", "near_thesis/model.py"], "Discounted fundamentals-only value per token; edit the YAML and re-run."),
    ]
    payload = {
        "as_of": facts.as_of,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "offline (committed snapshot)" if offline else "live fetch",
        "kpis": [
            {"label": "NEAR price", "value": _usd(v["price_usd"]), "sub": f"market cap {_usd(v['market_cap_usd'])}"},
            {"label": "Intents volume, 30d avg / day", "value": _usd(v.get("intents_volume_30d_avg")), "sub": f"{_pct(v.get('intents_volume_yoy'))} YoY"},
            {"label": "Intents revenue (annualized)", "value": _usd(v.get("intents_revenue_30d_annualized")), "sub": f"{v.get('intents_take_rate_bps_30d', 0):.1f} bps of volume"},
            {"label": "L1 transactions / day", "value": _n(v["txns_30d_avg"]), "sub": f"{_pct(v['txns_yoy'])} YoY"},
            {"label": "Active accounts / day", "value": _n(v["active_accounts_30d_avg"]), "sub": f"{_pct(v['active_accounts_yoy'])} YoY"},
            {"label": "Supply growth (365d)", "value": _p(v["supply_growth_365d"], 2), "sub": f"max inflation {_p(v['protocol_max_inflation_rate'], 1)}"},
            {"label": "Staked share", "value": _p(v["staking_staked_share_of_supply"]), "sub": f"Nakamoto coefficient {v['staking_nakamoto_coefficient']}"},
            {"label": "Revenue + burn vs emissions", "value": _p(v.get("revenue_plus_burn_to_emissions")), "sub": "at today's price"},
        ],
        "cards": [
            {"id": cid, "title": t, "sources": src, "method": m, "sentence": sent.get(cid, ""), "png": chart_paths.get(cid)}
            for cid, t, src, m in cards
            if chart_paths.get(cid)
        ],
        "series": series,
        "model": model,
        "manifest": man,
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data").mkdir(exist_ok=True)
    clean = metrics.clean(payload)
    (DOCS / "data" / "dashboard.json").write_text(json.dumps(clean, indent=1))
    (DOCS / "data" / "facts.json").write_text(json.dumps(metrics.clean({"as_of": facts.as_of, "values": v, "notes": facts.notes}), indent=1))
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(clean, separators=(",", ":")))
    (DOCS / "index.html").write_text(html)
    (DOCS / ".nojekyll").write_text("")
    write_evidence(facts, model, sent)


def write_evidence(facts: metrics.Facts, model: dict, sent: dict) -> None:
    v = facts.values
    rows = [
        ("NEAR price / market cap", f"{_usd(v['price_usd'])} / {_usd(v['market_cap_usd'])}", "NearBlocks /v1/stats"),
        ("Total supply / circulating", f"{_n(v['total_supply_near'])} / {_n(v['circulating_supply_near'])} NEAR", "NearBlocks /v1/stats"),
        ("L1 transactions, 30d avg/day (YoY)", f"{_n(v['txns_30d_avg'])} ({_pct(v['txns_yoy'])})", "NearBlocks /v1/charts"),
        ("L1 transactions, peak 30d avg/day", f"{_n(v['txns_30d_avg_peak'])} ({v['txns_30d_avg_peak_date']})", "NearBlocks /v1/charts"),
        ("Active accounts, 30d avg/day (YoY)", f"{_n(v['active_accounts_30d_avg'])} ({_pct(v['active_accounts_yoy'])})", "NearBlocks /v1/charts"),
        ("New accounts, 30d avg/day (YoY)", f"{_n(v['new_accounts_30d_avg'])} ({_pct(v['new_accounts_yoy'])})", "NearBlocks /v1/charts"),
        ("L1 gas fees, trailing 365d", f"{_usd(v['l1_fees_usd_ttm'])} ({_n(v['l1_fees_near_ttm'])} NEAR)", "NearBlocks /v1/charts"),
        ("Share of gas fees burned", _p(v["protocol_min_burn_share_of_fees"], 0), "RPC protocol config burnt_gas_reward"),
        ("NEAR Intents volume, 30d avg/day (YoY)", f"{_usd(v.get('intents_volume_30d_avg'))} ({_pct(v.get('intents_volume_yoy'))})", "DefiLlama near-intents"),
        ("NEAR Intents volume, trailing 365d", _usd(v.get("intents_volume_ttm")), "DefiLlama near-intents"),
        ("NEAR Intents volume, all-time (since " + str(v.get("intents_first_day")) + ")", _usd(v.get("intents_volume_alltime")), "DefiLlama near-intents"),
        ("Intents gross fees, trailing 365d", _usd(v.get("intents_fees_ttm")), "DefiLlama near-intents fees"),
        ("Intents revenue captured by NEAR, trailing 365d", _usd(v.get("intents_revenue_ttm")), "DefiLlama near-intents revenue"),
        ("Intents revenue, last 30d annualized", _usd(v.get("intents_revenue_30d_annualized")), "DefiLlama near-intents revenue"),
        ("Net take-rate, 30d / 365d", f"{v.get('intents_take_rate_bps_30d', 0):.2f} / {v.get('intents_take_rate_bps_ttm', 0):.2f} bps", "revenue / volume"),
        ("Buyback wallet balance", f"{_n(v.get('buyback_wallet_balance_near'))} NEAR", "RPC view_account buybacks.multisignature.near"),
        ("Supply growth, trailing 365d / 90d annualized", f"{_p(v['supply_growth_365d'], 2)} / {_p(v['supply_growth_90d_annualized'], 2)}", "NearBlocks total_supply"),
        ("Protocol max inflation", _p(v["protocol_max_inflation_rate"], 2), "RPC protocol config"),
        ("Fee burn as share of gross issuance", _p(v.get("burn_offset_share_of_issuance"), 2), "computed"),
        ("Revenue + burn vs emissions (USD, at today's price)", _p(v.get("revenue_plus_burn_to_emissions"), 1), "computed"),
        ("Staked share of supply", _p(v["staking_staked_share_of_supply"]), "RPC validators + block"),
        ("Validators / Nakamoto coefficient / top-10 share", f"{v['staking_validators']} / {v['staking_nakamoto_coefficient']} / {_p(v['staking_top10_stake_share'])}", "RPC validators"),
        ("Estimated staking yield, nominal / real", f"{_p(v['staking_nominal_yield_est'], 2)} / {_p(v['staking_real_yield_est'], 2)}", "computed (before validator commission)"),
        ("DeFi TVL (YoY)", f"{_usd(v.get('defi_tvl_usd'))} ({_pct(v.get('defi_tvl_usd_yoy'))})", "DefiLlama"),
        ("Stablecoins on NEAR (YoY)", f"{_usd(v.get('stablecoins_usd'))} ({_pct(v.get('stablecoins_usd_yoy'))})", "DefiLlama stablecoins"),
        ("Market cap / L1 fees (365d)", f"{v['market_cap_to_l1_fees_ttm']:,.0f}x" if v.get("market_cap_to_l1_fees_ttm") else "n/a", "computed"),
        ("Market cap / Intents revenue (annualized)", f"{v['market_cap_to_intents_revenue_ann']:,.0f}x" if v.get("market_cap_to_intents_revenue_ann") else "n/a", "computed"),
        ("Core-repo commits, last 12w vs prior 12w", f"{_n(v.get('dev_commits_last_12w'))} vs {_n(v.get('dev_commits_prior_12w'))}", "GitHub API"),
    ]
    lines = [
        "# EVIDENCE: every number, regenerated",
        "",
        f"_Generated by `python -m near_thesis run` from the data snapshot. Data as of **{facts.as_of}** (UTC day; NEAR Intents series to {v.get('intents_as_of')}). Do not edit by hand._",
        "",
        "| Metric | Value | Source |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    lines += ["", "## Hypothesis test (lead-lag of weekly changes, since 2025-01-01)", "", "| Leader → target | r at lag 0 | Best lag (weeks) | r at best lag | Noise band (±) |", "| --- | --- | --- | --- | --- |"]
    for t, r in v["lead_lag"].items():
        lines.append(f"| Intents volume → {t} | {r['corr_lag0']:+.2f} | {r['best_lag_weeks']} | {r['best_corr']:+.2f} | {r['significance_threshold_95']:.2f} |")
    for t, r in v["lead_lag_price_leader"].items():
        lines.append(f"| Price → {t} | {r['corr_lag0']:+.2f} | {r['best_lag_weeks']} | {r['best_corr']:+.2f} | {r['significance_threshold_95']:.2f} |")
    lines += ["", "## Valuation scenarios", "", f"Horizon {model['horizon_years']} years. Start: Intents volume {_usd(model['start']['intents_volume_start_usd'])}/yr, net take-rate {model['start']['intents_take_rate_bps']:.2f} bps, L1 fees {_usd(model['start']['l1_fees_start_usd'])}/yr, supply growth {_p(model['start']['supply_growth'], 1)}/yr.", "", "| | Bear | Base | Bull |", "| --- | --- | --- | --- |"]
    sc = model["scenarios"]
    def row(label, key, fmt):
        return f"| {label} | " + " | ".join(fmt(sc[n][key]) for n in ("bear", "base", "bull")) + " |"
    def irow(label, key, fmt):
        return f"| {label} | " + " | ".join(fmt(sc[n]["inputs"][key]) for n in ("bear", "base", "bull")) + " |"
    lines += [
        irow("Intents volume growth / yr", "intents_volume_cagr", lambda x: _p(x, 0)),
        irow("Take-rate change by horizon", "take_rate_change", lambda x: _pct(x, 0)),
        irow("Share of Intents revenue to holders", "value_accrual_share", lambda x: _p(x, 0)),
        irow("L1 fee growth / yr", "l1_fee_cagr", lambda x: _pct(x, 0)),
        irow("Exit multiple (x holder earnings)", "exit_multiple", lambda x: f"{x}x"),
        irow("Discount rate", "discount_rate", lambda x: _p(x, 0)),
        row("Intents volume in year T", "intents_volume_usd_T", _usd),
        row("Holder earnings in year T", "holder_earnings_usd_T", _usd),
        row("Network value in year T", "network_value_usd_T", _usd),
        row("Value per NEAR in year T", "value_per_token_usd_T", _usd),
        row("**Present value per NEAR**", "present_value_per_token_usd", lambda x: f"**{_usd(x)}**"),
        row("vs today's price", "pv_vs_price", lambda x: _pct(x, 0)),
        row("Intents growth / yr implied by today's price", "implied_intents_volume_cagr_for_price", lambda x: _p(x, 0)),
    ]
    lines += ["", "## One-line readings", ""] + [f"- **{k}**: {s}" for k, s in sent.items()]
    if facts.notes:
        lines += ["", "## Notes", ""] + [f"- `{k}`: {s}" for k, s in facts.notes.items()]
    (ROOT / "EVIDENCE.md").write_text("\n".join(lines) + "\n")
