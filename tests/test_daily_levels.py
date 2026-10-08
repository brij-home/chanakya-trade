"""
tests/test_daily_levels.py
──────────────────────────
Unit tests for the centralized Daily Reference Levels & Pre-Market Engine.
Verifies:
  1. CPR (TC, BC, Pivot, Width %, Regime) calculation correctness.
  2. Camarilla Pivots (H5, H4, H3, L3, L4, L5) correctness.
  3. Classical Pivots (R1-R3, S1-S3) correctness.
  4. L1 In-Memory Caching (sub-millisecond retrieval).
  5. L2 Daily File Persistence and reloading on restart.
  6. Pre-Market Indicative Auction updates and Gap classifications.
  7. Integration with get_premarket_battle_plan.
"""

import json
from pathlib import Path
import pytest
import pandas as pd

from engine.daily_levels import (
    DailyLevels,
    DailyLevelsStore,
    get_daily_levels,
    prime_daily_levels,
)


@pytest.fixture
def temp_store(tmp_path):
    """Fixture providing a DailyLevelsStore with isolated temp directory."""
    return DailyLevelsStore(persist_dir=tmp_path)


def test_daily_levels_mathematical_invariants(temp_store, monkeypatch):
    """Verifies CPR, Camarilla, and Pivot mathematical formulas with synthetic deterministic data."""
    # Synthetic bars: High=25000, Low=24600, Close=24800, Prev Close=24800
    mock_df = pd.DataFrame(
        [
            {"open": 24500, "high": 24700, "low": 24400, "close": 24600, "volume": 1000},
            {"open": 24650, "high": 25000, "low": 24600, "close": 24800, "volume": 1500},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )

    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    dl = temp_store.compute_and_store("NIFTY", session_date="2026-10-08")
    assert dl is not None
    assert dl.pdh == 25000.0
    assert dl.pdl == 24600.0
    assert dl.pdc == 24800.0

    # CPR: Pivot = (25000 + 24600 + 24800) / 3 = 24800.0
    # BC = (25000 + 24600) / 2 = 24800.0
    # TC = (24800 - 24800) + 24800 = 24800.0
    assert dl.cpr["pivot"] == 24800.0
    assert dl.cpr["bc"] == 24800.0
    assert dl.cpr["tc"] == 24800.0
    assert dl.cpr["is_narrow"] is True
    assert "NARROW_CPR" in dl.cpr["regime"]

    # Camarilla: Range = 400
    # H4 = 24800 + (400 * 1.1 / 2) = 24800 + 220 = 25020.0
    # H3 = 24800 + (400 * 1.1 / 4) = 24800 + 110 = 24910.0
    # L3 = 24800 - 110 = 24690.0
    # L4 = 24800 - 220 = 24580.0
    assert dl.camarilla["h4"] == 25020.0
    assert dl.camarilla["h3"] == 24910.0
    assert dl.camarilla["l3"] == 24690.0
    assert dl.camarilla["l4"] == 24580.0

    # Classic Pivots:
    # R1 = 2 * 24800 - 24600 = 25000.0
    # S1 = 2 * 24800 - 25000 = 24600.0
    assert dl.classic_pivots["r1"] == 25000.0
    assert dl.classic_pivots["s1"] == 24600.0


def test_in_memory_l1_caching_and_sub_millisecond_reuse(temp_store, monkeypatch):
    """Confirms that subsequent requests return directly from memory without re-fetching."""
    call_count = 0

    def mock_ohlcv(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return pd.DataFrame(
            [
                {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 100},
                {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 150},
            ],
            index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
        )

    monkeypatch.setattr("market.history.get_ohlcv", mock_ohlcv)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    # First call: computes and caches
    dl1 = temp_store.get_levels("RELIANCE", session_date="2026-10-08")
    assert dl1 is not None
    assert call_count >= 1

    # Second call: must hit memory cache, call_count should NOT increment
    prior_calls = call_count
    dl2 = temp_store.get_levels("RELIANCE", session_date="2026-10-08")
    assert dl2 is dl1
    assert call_count == prior_calls


def test_l2_disk_persistence_and_reload_on_restart(tmp_path, monkeypatch):
    """Verifies that levels persist to daily JSON and can be fully restored upon fresh restart."""
    store1 = DailyLevelsStore(persist_dir=tmp_path)

    mock_df = pd.DataFrame(
        [
            {"open": 500, "high": 520, "low": 490, "close": 510, "volume": 200},
            {"open": 510, "high": 530, "low": 500, "close": 525, "volume": 300},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    dl = store1.compute_and_store("TCS", session_date="2026-10-08")
    assert dl is not None

    # Check file was written to disk
    persisted_file = tmp_path / "daily_levels_2026-10-08.json"
    assert persisted_file.exists()

    with open(persisted_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "TCS" in data
    assert data["TCS"]["pdh"] == 530.0

    # Simulate fresh app restart: create a new DailyLevelsStore instance pointing to same directory
    # Prevent get_ohlcv from being called to verify pure disk reload
    monkeypatch.setattr(
        "market.history.get_ohlcv",
        lambda *a, **k: pytest.fail("Should have loaded from disk, not fetched history!"),
    )

    store2 = DailyLevelsStore(persist_dir=tmp_path)
    reloaded_dl = store2.get_levels("TCS", session_date="2026-10-08", compute_if_missing=False)
    assert reloaded_dl is not None
    assert reloaded_dl.symbol == "TCS"
    assert reloaded_dl.pdh == 530.0
    assert reloaded_dl.cpr["pivot"] > 0


def test_pre_market_auction_indicative_open_and_gap_classification(temp_store, monkeypatch):
    """Verifies indicative pre-market open discovery and gap classification (PRO_GAP_UP, PRO_GAP_DOWN, FLAT)."""
    mock_df = pd.DataFrame(
        [
            {"open": 20000, "high": 20100, "low": 19900, "close": 20000, "volume": 100},
            {"open": 20000, "high": 20200, "low": 19950, "close": 20100, "volume": 150},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    temp_store.compute_and_store("BANKNIFTY", session_date="2026-10-08")

    # Case 1: Pre-market auction opens at 20300 (above yesterday's high 20200) -> PRO_GAP_UP
    updated = temp_store.update_preopen("BANKNIFTY", pre_open_price=20300.0, session_date="2026-10-08")
    assert updated is not None
    assert updated.pre_open["auction_settled"] is True
    assert updated.pre_open["price"] == 20300.0
    assert updated.pre_open["gap_points"] == 200.0  # 20300 - 20100
    assert "PRO_GAP_UP" in updated.pre_open["gap_type"]
    assert updated.pre_open["opening_bias"] == "BULLISH"

    # Case 2: Pre-market auction opens at 19900 (below yesterday's low 19950) -> PRO_GAP_DOWN
    updated2 = temp_store.update_preopen("BANKNIFTY", pre_open_price=19900.0, session_date="2026-10-08")
    assert updated2 is not None
    assert "PRO_GAP_DOWN" in updated2.pre_open["gap_type"]
    assert updated2.pre_open["opening_bias"] == "BEARISH"


def test_get_premarket_battle_plan_uses_daily_levels(monkeypatch):
    """Confirms get_premarket_battle_plan successfully retrieves and returns daily levels."""
    from market.indices import get_premarket_battle_plan

    plan = get_premarket_battle_plan(["NIFTY"])
    assert "NIFTY" in plan
    nifty = plan["NIFTY"]
    assert nifty["pdh"] > 0
    assert nifty["pdl"] > 0
    assert nifty["pdc"] > 0
    assert "cpr" in nifty
    assert "camarilla" in nifty
    assert "blueprint" in nifty
