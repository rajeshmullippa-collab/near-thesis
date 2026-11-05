"""Offline tests: run against the committed snapshot in data/snapshot/."""
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from near_thesis import metrics, model

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def df():
    return metrics.daily()


@pytest.fixture(scope="module")
def facts(df):
    return metrics.facts(df)


def test_daily_table_is_complete(df):
    assert df.index.is_monotonic_increasing
    assert df.index.min() <= pd.Timestamp("2020-08-01")
    for col in ["txns", "active_accounts", "fee_usd", "total_supply_near", "intents_volume_usd", "defi_tvl_usd", "price_usd"]:
        assert df[col].notna().sum() > 100, col


def test_supply_is_sane(facts):
    v = facts.values
    assert 1.0e9 < v["total_supply_near"] < 2.0e9
    # Realized supply growth cannot exceed the protocol's max inflation by much.
    assert 0 <= v["supply_growth_365d"] <= v["protocol_max_inflation_rate"] + 0.01


def test_staking_facts(facts):
    v = facts.values
    assert 0 < v["staking_staked_share_of_supply"] < 1
    assert v["staking_nakamoto_coefficient"] >= 1
    assert v["staking_validators"] >= v["staking_nakamoto_coefficient"]


def test_intents_numbers_are_internally_consistent(facts):
    v = facts.values
    assert v["intents_volume_ttm"] <= v["intents_volume_alltime"]
    assert 0 < v["intents_take_rate_bps_30d"] < 100


def test_model_is_monotonic_in_growth(facts):
    cfg = model.load_assumptions()
    m = model.run(facts.values, cfg)
    sc = m["scenarios"]
    assert sc["bear"]["present_value_per_token_usd"] < sc["base"]["present_value_per_token_usd"] < sc["bull"]["present_value_per_token_usd"]
    grid = m["sensitivity"]["present_value_per_token_usd"]
    for col in range(len(grid[0])):
        column = [row[col] for row in grid]
        assert column == sorted(column)


def test_reverse_model_round_trips(facts):
    cfg = model.load_assumptions()
    start = model.resolve_start(cfg, facts.values)
    base = cfg["scenarios"]["base"]
    r = model.run_scenario(start, base, cfg["horizon_years"])
    implied = r["implied_intents_volume_cagr_for_price"]
    r2 = model.run_scenario(start, base | {"intents_volume_cagr": implied}, cfg["horizon_years"])
    assert math.isclose(r2["present_value_per_token_usd"], start["price_usd"], rel_tol=1e-6)


def test_built_outputs_exist():
    # `python -m near_thesis run --offline` must have produced these.
    d = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text())
    assert d["cards"] and d["kpis"]
    for c in d["cards"]:
        assert (ROOT / "docs" / c["png"]).exists(), c["png"]
    assert "EVIDENCE" in (ROOT / "EVIDENCE.md").read_text()
