"""Static PNG charts for THESIS.md and the dashboard (rebuilt on every run)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "charts"

INK = "#1b1f24"
NEAR_GREEN = "#00a37a"
BLUE = "#3b6fd8"
ORANGE = "#e07b2a"
GREY = "#8a94a3"
RED = "#c8453b"

plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": 110,
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.edgecolor": "#c9ced6",
        "text.color": INK,
        "axes.labelcolor": INK,
    }
)


def _usd(x, _pos=None):
    a = abs(x)
    for d, s in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= d:
            return f"${x / d:.0f}{s}" if a / d >= 10 else f"${x / d:.1f}{s}"
    return f"${x:.2f}" if a < 10 else f"${x:.0f}"


def _num(x, _pos=None):
    a = abs(x)
    for d, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= d:
            return f"{x / d:.1f}{s}".replace(".0", "")
    return f"{x:.0f}"


def _date_axis(ax):
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))


def _save(fig, name, source):
    fig.text(0.01, 0.01, f"Source: {source}  ·  near-thesis", fontsize=7.5, color=GREY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png")
    plt.close(fig)
    return f"charts/{name}.png"


def usage(df):
    d = df[df.index >= "2023-01-01"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(d.index, d["txns"].rolling(30).mean(), color=BLUE, lw=2, label="Transactions / day (30d avg)")
    ax.plot(d.index, d["active_accounts"].rolling(30).mean(), color=NEAR_GREEN, lw=2, label="Active accounts / day (30d avg)")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(_num))
    ax.set_title("L1 activity: transactions and active accounts")
    ax.legend(loc="lower left", frameon=False)
    _date_axis(ax)
    return _save(fig, "usage", "NearBlocks /v1/charts")


def intents_vs_price(df):
    d = df[df.index >= "2024-12-01"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.bar(d.index, d["intents_volume_usd"], color=NEAR_GREEN, alpha=0.35, width=1.0, label="NEAR Intents volume / day")
    ax.plot(d.index, d["intents_volume_usd"].rolling(30).mean(), color=NEAR_GREEN, lw=2, label="30d avg")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(_usd))
    ax.set_title("NEAR Intents daily volume vs NEAR price")
    ax2 = ax.twinx()
    ax2.plot(d.index, d["price_usd"], color=INK, lw=1.4, label="NEAR price (right)")
    ax2.yaxis.set_major_formatter(mtick.FuncFormatter(_usd))
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", frameon=False, ncol=3)
    ax.set_ylim(0, d["intents_volume_usd"].max() * 1.15)
    _date_axis(ax)
    return _save(fig, "intents_vs_price", "DefiLlama (near-intents), CoinGecko")


def fees(df):
    d = df[df.index >= "2025-01-01"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(d.index, d["fee_usd"].rolling(30).mean(), color=BLUE, lw=2, label="L1 gas fees (all burned)")
    ax.plot(d.index, d["intents_fees_usd"].rolling(30).mean(), color=ORANGE, lw=2, label="Intents gross fees")
    rev = d["intents_revenue_usd"].rolling(30).mean()
    ax.plot(d.index, rev.where(rev > 100), color=NEAR_GREEN, lw=2.4, label="Intents revenue captured by NEAR (lumpy sweeps before 2026)")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(_usd))
    ax.set_title("Where the money is: daily fees, 30-day average (USD)")
    ax.legend(loc="lower left", frameon=False)
    _date_axis(ax)
    return _save(fig, "fees", "NearBlocks /v1/charts, DefiLlama (near-intents fees & revenue)")


def supply(df, facts):
    d = df[df.index >= "2021-01-01"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(d.index, d["total_supply_near"] / 1e9, color=INK, lw=2, label="Total supply (B NEAR)")
    ax.set_ylabel("B NEAR")
    ax.set_title("Supply and realized inflation")
    ax2 = ax.twinx()
    ax2.plot(d.index, d["supply_growth_365d"] * 100, color=RED, lw=1.6, label="Supply growth, trailing 365d (right)")
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=1))
    ax2.set_ylim(0, 6)
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False)
    _date_axis(ax)
    return _save(fig, "supply", "NearBlocks /v1/charts; protocol max inflation from RPC")


def tvl(df):
    d = df[df.index >= "2023-01-01"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(d.index, d["defi_tvl_usd"], color=NEAR_GREEN, lw=2, label="DeFi TVL on NEAR")
    ax.plot(d.index, d["stablecoins_usd"], color=BLUE, lw=2, label="Stablecoins on NEAR")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(_usd))
    ax.set_title("Capital on NEAR: DeFi TVL and stablecoin supply")
    ax.legend(loc="upper left", frameon=False)
    _date_axis(ax)
    return _save(fig, "tvl", "DefiLlama chain TVL & stablecoins")


def staking(facts_values, stakes):
    s = np.array(stakes)
    cum = np.cumsum(s) / s.sum()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(np.arange(1, len(s) + 1), cum * 100, color=NEAR_GREEN, lw=2)
    ax.axhline(100 / 3, color=RED, lw=1, ls="--")
    nak = facts_values.get("staking_nakamoto_coefficient")
    ax.annotate(
        f"{nak} validators control > 1/3 of stake",
        xy=(nak, 100 / 3),
        xytext=(nak + 25, 18),
        arrowprops={"arrowstyle": "->", "color": INK},
    )
    ax.set_xscale("log")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.set_xlabel("Validators, largest first (log scale)")
    ax.set_title("Stake concentration (current epoch)")
    return _save(fig, "staking", "NEAR RPC `validators`")


def devs(dev: pd.DataFrame):
    if dev.empty:
        return None
    fig, ax = plt.subplots(figsize=(9, 4.2))
    tot = dev.sum(axis=1)
    ax.bar(tot.index, tot.values, width=5, color=BLUE, alpha=0.55, label="Commits / week, tracked core repos")
    ax.plot(tot.index, tot.rolling(4).mean(), color=INK, lw=2, label="4-week avg")
    ax.set_title(f"Developer activity: {dev.shape[1]} core NEAR repositories")
    ax.legend(loc="upper left", frameon=False)
    _date_axis(ax)
    return _save(fig, "devs", "GitHub REST API stats/commit_activity")


def lead_lag(ll: dict):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    colors = {"price_usd": INK, "txns": BLUE, "active_accounts": NEAR_GREEN, "defi_tvl_usd": ORANGE}
    labels = {"price_usd": "NEAR price", "txns": "Transactions", "active_accounts": "Active accounts", "defi_tvl_usd": "DeFi TVL"}
    thr = None
    for t, r in ll.items():
        lags = sorted(int(k) for k in r["by_lag"])
        ax.plot(lags, [r["by_lag"][k] if k in r["by_lag"] else r["by_lag"][str(k)] for k in lags], marker="o", ms=3, lw=1.6, color=colors.get(t, GREY), label=labels.get(t, t))
        thr = r.get("significance_threshold_95", thr)
    if thr:
        ax.axhspan(-thr, thr, color=GREY, alpha=0.15, label=f"|r| < {thr:.2f}: indistinguishable from noise")
    ax.axvline(0, color=GREY, lw=0.8)
    ax.set_xlabel("Lag in weeks (positive = Intents volume moves first)")
    ax.set_ylabel("Correlation of weekly % changes")
    ax.set_title("Does Intents volume lead price or usage? (since Jan 2025)")
    ax.set_ylim(-0.5, 0.5)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), frameon=False, fontsize=8, ncol=5)
    return _save(fig, "lead_lag", "near-thesis computation on DefiLlama, NearBlocks, CoinGecko data")


def scenarios(model: dict):
    names = ["bear", "base", "bull"]
    pv = [model["scenarios"][n]["present_value_per_token_usd"] for n in names]
    price = model["start"]["price_usd"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars = ax.bar([n.title() for n in names], pv, color=[RED, BLUE, NEAR_GREEN], alpha=0.85)
    ax.axhline(price, color=INK, ls="--", lw=1.2)
    ax.text(-0.45, price, f"price today ${price:.2f}", va="bottom", ha="left", fontsize=9)
    for b, v in zip(bars, pv):
        ax.text(b.get_x() + b.get_width() / 2, v, f"${v:.2f}", ha="center", va="bottom", fontweight="bold")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(_usd))
    ax.set_title(f"Fundamentals-only value per NEAR today ({model['horizon_years']}-year model, discounted)")
    return _save(fig, "scenarios", "near-thesis model, config/assumptions.yaml")


def build_all(df, facts, model, dev, stakes) -> dict:
    v = facts.values
    out = {
        "usage": usage(df),
        "intents_vs_price": intents_vs_price(df),
        "fees": fees(df),
        "supply": supply(df, v),
        "tvl": tvl(df),
        "staking": staking(v, stakes),
        "lead_lag": lead_lag(v["lead_lag"]),
        "scenarios": scenarios(model),
    }
    d = devs(dev)
    if d:
        out["devs"] = d
    return out
