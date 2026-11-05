"""Command line: `python -m near_thesis run [--offline]`.

  fetch            pull every public source live into data/snapshot/
  build            rebuild metrics, model, charts, dashboard and EVIDENCE.md from the snapshot
  model            print the bull/base/bear model only (fast; edit config/assumptions.yaml)
  run              fetch + build (default); with --offline, build from the committed snapshot only
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import charts, dashboard, metrics, model, sources


def _build(offline: bool, assumptions: str | None) -> dict:
    t = time.time()
    df = metrics.daily()
    facts = metrics.facts(df)
    cfg = model.load_assumptions(assumptions) if assumptions else model.load_assumptions()
    m = model.run(facts.values, cfg)
    paths = charts.build_all(df, facts, m, metrics.dev_activity(), metrics.staking_facts()["stake_distribution"])
    dashboard.build(df, facts, m, paths, offline=offline)
    print(f"Built {len(paths)} charts, docs/index.html and EVIDENCE.md from data as of {facts.as_of} in {time.time() - t:.1f}s")
    return {"facts": facts, "model": m}


def _print_model(m: dict) -> None:
    print(f"\nValuation (horizon {m['horizon_years']}y, price today ${m['start']['price_usd']:.2f}):")
    print(f"  {'scenario':8} {'PV/NEAR':>10} {'vs price':>9} {'implied Intents CAGR':>22}")
    for n, s in m["scenarios"].items():
        print(f"  {n:8} {s['present_value_per_token_usd']:>10.2f} {s['pv_vs_price'] * 100:>8.0f}% {s['implied_intents_volume_cagr_for_price'] * 100:>21.0f}%")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="near_thesis", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="run", choices=["fetch", "build", "model", "run"])
    p.add_argument("--offline", action="store_true", help="do not touch the network; use data/snapshot only")
    p.add_argument("--assumptions", help="path to an alternative assumptions YAML")
    a = p.parse_args(argv)
    if a.command in ("fetch", "run") and not a.offline:
        print("Fetching public data (NEAR RPC, NearBlocks, DefiLlama, CoinGecko, GitHub)...")
        sources.fetch_all()
    if a.command == "fetch":
        return 0
    if a.command == "model":
        facts = metrics.facts()
        cfg = model.load_assumptions(a.assumptions) if a.assumptions else model.load_assumptions()
        m = model.run(facts.values, cfg)
        _print_model(m)
        print(json.dumps(metrics.clean(m["sensitivity"]), indent=1))
        return 0
    out = _build(offline=a.offline or a.command == "build", assumptions=a.assumptions)
    _print_model(out["model"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
