"""Public data sources for the NEAR thesis.

Every source here is public and needs no API key. Each fetcher writes the raw
response, untouched, to ``data/snapshot/<name>.json`` so that every number in
the thesis can be traced back to a file you can open, and so that the whole
pipeline can be re-run offline (``--offline``) from the committed snapshot.

Sources
-------
* NEAR RPC (https://rpc.mainnet.near.org, fallback https://free.rpc.fastnear.com)
  - ``block``                       latest final block: total supply, gas price
  - ``validators``                  current validator set and stake
  - ``EXPERIMENTAL_protocol_config`` inflation rate, reward rate, gas burn share
* NearBlocks API (https://api.nearblocks.io/v1)
  - ``/charts``  daily series since genesis: txns, active/new accounts, fees,
                 supply, contracts, price
  - ``/stats``   current snapshot: supply, circulating supply, market cap
* DefiLlama (https://api.llama.fi, https://stablecoins.llama.fi)
  - NEAR chain TVL history, NEAR chain DEX volume, NEAR chain fees,
    NEAR Intents daily volume / fees / revenue, stablecoins on NEAR
* CoinGecko (https://api.coingecko.com) - 365 days of NEAR price, market cap
  and volume. Rate limited on the free tier; the pipeline retries and, if it
  still fails, falls back to the NearBlocks price series.
* GitHub REST API - weekly commit counts for core NEAR repositories (developer
  activity). Uses ``GITHUB_TOKEN`` if set, otherwise unauthenticated.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshot"

RPC_ENDPOINTS = ["https://rpc.mainnet.near.org", "https://free.rpc.fastnear.com"]
NEARBLOCKS = "https://api.nearblocks.io/v1"
LLAMA = "https://api.llama.fi"
LLAMA_STABLES = "https://stablecoins.llama.fi"
COINGECKO = "https://api.coingecko.com/api/v3"
GITHUB = "https://api.github.com"

# Core repositories used as a developer-activity proxy. This is a sample of
# the ecosystem, not all of it; the thesis says so.
DEV_REPOS = [
    "near/nearcore",
    "near/near-sdk-rs",
    "near/near-api-js",
    "near/near-cli-rs",
    "near/docs",
    "near/intents",
    "near/mpc",
    "nearai/nearai",
]

UA = {"User-Agent": "near-thesis/1.0 (+https://github.com/rajeshmullippa-collab/near-thesis)"}

# Human-readable provenance for every snapshot file; shown on the dashboard.
PROVENANCE: dict[str, str] = {
    "rpc_block": "NEAR RPC `block` (finality=final)",
    "rpc_validators": "NEAR RPC `validators` [null]",
    "rpc_protocol_config": "NEAR RPC `EXPERIMENTAL_protocol_config`",
    "nearblocks_charts": f"GET {NEARBLOCKS}/charts",
    "nearblocks_stats": f"GET {NEARBLOCKS}/stats",
    "llama_chain_tvl": f"GET {LLAMA}/v2/historicalChainTvl/Near",
    "llama_chain_dex": f"GET {LLAMA}/overview/dexs/near?dataType=dailyVolume",
    "llama_chain_fees": f"GET {LLAMA}/summary/fees/near?dataType=dailyFees",
    "llama_intents_volume": f"GET {LLAMA}/summary/dexs/near-intents?dataType=dailyVolume",
    "llama_intents_fees": f"GET {LLAMA}/summary/fees/near-intents?dataType=dailyFees",
    "llama_intents_revenue": f"GET {LLAMA}/summary/fees/near-intents?dataType=dailyRevenue",
    "llama_stablecoins": f"GET {LLAMA_STABLES}/stablecoincharts/Near",
    "coingecko_market_chart": f"GET {COINGECKO}/coins/near/market_chart?vs_currency=usd&days=365",
    "rpc_revenue_wallets": "NEAR RPC `query` view_account for " + ", ".join(["buybacks.multisignature.near", "fefundsadmin.sputnik-dao.near", "1csfundsadmin.sputnik-dao.near"]),
    "github_commit_activity": f"GET {GITHUB}/repos/<repo>/stats/commit_activity for {', '.join(DEV_REPOS)}",
}


class FetchError(RuntimeError):
    pass


def _get(url: str, *, retries: int = 4, headers: dict | None = None, ok_202: bool = False) -> Any:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={**UA, **(headers or {})}, timeout=60)
            if r.status_code == 202 and ok_202:
                # GitHub stats are computed lazily; ask again shortly.
                time.sleep(3 + attempt * 3)
                continue
            if r.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:  # network or JSON
            last = e
            time.sleep(2 * (attempt + 1))
    raise FetchError(f"{url}: {last or 'no data after retries'}")


def _rpc(method: str, params: Any) -> Any:
    last = None
    for ep in RPC_ENDPOINTS:
        try:
            r = requests.post(
                ep,
                json={"jsonrpc": "2.0", "id": "near-thesis", "method": method, "params": params},
                headers=UA,
                timeout=60,
            )
            r.raise_for_status()
            body = r.json()
            if "result" in body:
                return body["result"]
            last = body.get("error")
        except (requests.RequestException, ValueError) as e:
            last = e
    raise FetchError(f"RPC {method}: {last}")


def _slim_validators(res: dict) -> dict:
    keep = ("account_id", "stake", "num_produced_blocks", "num_expected_blocks")
    return {
        "epoch_height": res.get("epoch_height"),
        "epoch_start_height": res.get("epoch_start_height"),
        "current_validators": [{k: v.get(k) for k in keep} for v in res.get("current_validators", [])],
    }


def _slim_protocol_config(res: dict) -> dict:
    rc = res.get("runtime_config", {}).get("transaction_costs", {})
    return {
        k: res.get(k)
        for k in (
            "protocol_version",
            "genesis_time",
            "max_inflation_rate",
            "protocol_reward_rate",
            "num_blocks_per_year",
            "epoch_length",
            "min_gas_price",
            "max_gas_price",
        )
    } | {"burnt_gas_reward": rc.get("burnt_gas_reward")}


def _slim_block(res: dict) -> dict:
    h = res["header"]
    return {k: h.get(k) for k in ("height", "timestamp", "timestamp_nanosec", "total_supply", "gas_price", "epoch_id")}


def _slim_llama_summary(res: dict) -> dict:
    return {k: res.get(k) for k in ("name", "methodology", "total24h", "total7d", "total30d", "totalAllTime")} | {
        "totalDataChart": res.get("totalDataChart", [])
    }


def _github_activity() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    # GitHub computes these statistics lazily and answers 202 until ready:
    # trigger every repo first, wait, then collect (with retries).
    for repo in DEV_REPOS:
        try:
            requests.get(f"{GITHUB}/repos/{repo}/stats/commit_activity", headers={**UA, **headers}, timeout=30)
        except requests.RequestException:
            pass
    time.sleep(20)
    out = {}
    for repo in DEV_REPOS:
        try:
            out[repo] = _get(f"{GITHUB}/repos/{repo}/stats/commit_activity", headers=headers, ok_202=True, retries=8)
        except FetchError as e:
            out[repo] = {"error": str(e)}
    return out


# Wallets that receive NEAR's captured Intents revenue and run the buyback,
# as listed on https://revenue.near.org ("Wallet Breakdown").
REVENUE_WALLETS = [
    "buybacks.multisignature.near",
    "fefundsadmin.sputnik-dao.near",
    "1csfundsadmin.sputnik-dao.near",
]


def _revenue_wallets() -> dict:
    out = {}
    for acct in REVENUE_WALLETS:
        try:
            r = _rpc("query", {"request_type": "view_account", "finality": "final", "account_id": acct})
            out[acct] = {"amount": r.get("amount"), "locked": r.get("locked"), "block_height": r.get("block_height")}
        except FetchError as e:
            out[acct] = {"error": str(e)}
    return out


FETCHERS: dict[str, Callable[[], Any]] = {
    "rpc_block": lambda: _slim_block(_rpc("block", {"finality": "final"})),
    "rpc_validators": lambda: _slim_validators(_rpc("validators", [None])),
    "rpc_protocol_config": lambda: _slim_protocol_config(_rpc("EXPERIMENTAL_protocol_config", {"finality": "final"})),
    "nearblocks_charts": lambda: _get(f"{NEARBLOCKS}/charts"),
    "nearblocks_stats": lambda: _get(f"{NEARBLOCKS}/stats"),
    "llama_chain_tvl": lambda: _get(f"{LLAMA}/v2/historicalChainTvl/Near"),
    "llama_chain_dex": lambda: {
        "totalDataChart": _get(f"{LLAMA}/overview/dexs/near?excludeTotalDataChartBreakdown=true&dataType=dailyVolume").get(
            "totalDataChart", []
        )
    },
    "llama_chain_fees": lambda: _slim_llama_summary(_get(f"{LLAMA}/summary/fees/near?dataType=dailyFees")),
    "llama_intents_volume": lambda: _slim_llama_summary(_get(f"{LLAMA}/summary/dexs/near-intents?dataType=dailyVolume")),
    "llama_intents_fees": lambda: _slim_llama_summary(_get(f"{LLAMA}/summary/fees/near-intents?dataType=dailyFees")),
    "llama_intents_revenue": lambda: _slim_llama_summary(_get(f"{LLAMA}/summary/fees/near-intents?dataType=dailyRevenue")),
    "llama_stablecoins": lambda: [
        {"date": r["date"], "totalCirculatingUSD": r.get("totalCirculatingUSD")}
        for r in _get(f"{LLAMA_STABLES}/stablecoincharts/Near")
    ],
    "rpc_revenue_wallets": lambda: _revenue_wallets(),
    "coingecko_market_chart": lambda: _get(f"{COINGECKO}/coins/near/market_chart?vs_currency=usd&days=365", retries=5),
    "github_commit_activity": _github_activity,
}

# Sources the pipeline can live without (it degrades and says so).
OPTIONAL = {"rpc_revenue_wallets", "coingecko_market_chart", "github_commit_activity", "llama_chain_dex", "llama_stablecoins"}


def snapshot_path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def fetch_all(only: list[str] | None = None, verbose: bool = True) -> dict:
    """Fetch every source live and overwrite the snapshot. Returns a manifest."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = SNAPSHOT_DIR / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, fn in FETCHERS.items():
        if only and name not in only:
            continue
        try:
            data = fn()
            snapshot_path(name).write_text(json.dumps(data, separators=(",", ":")))
            manifest[name] = {
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": PROVENANCE[name],
                "status": "ok",
            }
            if verbose:
                print(f"  fetched {name}")
        except FetchError as e:
            prev = manifest.get(name, {})
            manifest[name] = prev | {"status": f"failed, kept previous snapshot: {e}"[:300]}
            if verbose:
                print(f"  ! {name} failed ({e}); keeping the previous snapshot")
            if name not in OPTIONAL and not snapshot_path(name).exists():
                raise
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def load(name: str) -> Any:
    p = snapshot_path(name)
    if not p.exists():
        if name in OPTIONAL:
            return None
        raise FileNotFoundError(f"missing snapshot {p}; run `python -m near_thesis fetch`")
    return json.loads(p.read_text())


def manifest() -> dict:
    p = SNAPSHOT_DIR / "_manifest.json"
    return json.loads(p.read_text()) if p.exists() else {}
