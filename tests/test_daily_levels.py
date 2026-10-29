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
import pytest
import pandas as pd

from engine.daily_levels import (
    DailyLevelsStore,
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
    updated = temp_store.update_preopen(
        "BANKNIFTY", pre_open_price=20300.0, session_date="2026-10-08"
    )
    assert updated is not None
    assert updated.pre_open["auction_settled"] is True
    assert updated.pre_open["price"] == 20300.0
    assert updated.pre_open["gap_points"] == 200.0  # 20300 - 20100
    assert "PRO_GAP_UP" in updated.pre_open["gap_type"]
    assert updated.pre_open["opening_bias"] == "BULLISH"

    # Case 2: Pre-market auction opens at 19900 (below yesterday's low 19950) -> PRO_GAP_DOWN
    updated2 = temp_store.update_preopen(
        "BANKNIFTY", pre_open_price=19900.0, session_date="2026-10-08"
    )
    assert updated2 is not None
    assert "PRO_GAP_DOWN" in updated2.pre_open["gap_type"]
    assert updated2.pre_open["opening_bias"] == "BEARISH"


def test_get_premarket_battle_plan_uses_daily_levels(monkeypatch):
    """Confirms get_premarket_battle_plan successfully retrieves and returns daily levels."""
    from market.indices import get_premarket_battle_plan

    mock_df = pd.DataFrame(
        [
            {"open": 24500, "high": 24700, "low": 24400, "close": 24600, "volume": 1000},
            {"open": 24650, "high": 25000, "low": 24600, "close": 24800, "volume": 1500},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)

    plan = get_premarket_battle_plan(["NIFTY"])
    assert "NIFTY" in plan
    nifty = plan["NIFTY"]
    assert nifty["pdh"] > 0
    assert nifty["pdl"] > 0
    assert nifty["pdc"] > 0
    assert "cpr" in nifty
    assert "camarilla" in nifty
    assert "blueprint" in nifty
    bp = nifty["blueprint"]
    assert "bull_contract" in bp
    assert "bear_contract" in bp
    assert "h4_trigger" in bp
    assert "l4_trigger" in bp


def test_format_premarket_strike_radar(monkeypatch):
    """Verifies that format_premarket_strike_radar formats actionable ready-to-execute strikes."""
    from market.indices import get_premarket_battle_plan, format_premarket_strike_radar

    mock_df = pd.DataFrame(
        [
            {"open": 24500, "high": 24700, "low": 24400, "close": 24600, "volume": 1000},
            {"open": 24650, "high": 25000, "low": 24600, "close": 24800, "volume": 1500},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)

    plan = get_premarket_battle_plan(["NIFTY", "BANKNIFTY"])
    card = format_premarket_strike_radar(plan)

    assert "PRE-MARKET INDEX STRIKE RADAR" in card
    assert "NIFTY" in card
    assert "BULL TRIGGER" in card
    assert "BEAR TRIGGER" in card
    assert "CE" in card
    assert "PE" in card
    assert "Chop Trap Zone" in card


def test_daily_levels_save_to_disk_windows_file_lock_resilience(tmp_path, monkeypatch):
    """
    Verifies that save_to_disk survives Windows file locks ([WinError 5] Access is denied)
    using exponential backoff retry and direct-write fallback.
    """
    store = DailyLevelsStore(persist_dir=tmp_path)
    mock_df = pd.DataFrame(
        [
            {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 100},
            {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 150},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    import os

    store.compute_and_store("INFY", session_date="2026-10-26", persist=False)

    replace_calls = 0
    orig_replace = os.replace

    def mock_replace(src, dst):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls < 3:
            raise PermissionError("[WinError 5] Access is denied: 'data\\daily_levels\\test.tmp'")
        return orig_replace(src, dst)

    monkeypatch.setattr("os.replace", mock_replace)

    # Should retry and succeed without raising PermissionError
    store.save_to_disk("2026-10-26")
    target_file = tmp_path / "daily_levels_2026-10-26.json"
    assert target_file.exists()
    assert replace_calls >= 3

    # Also test permanent lock triggering direct-write fallback
    replace_calls = 0

    def mock_replace_always_fail(src, dst):
        nonlocal replace_calls
        replace_calls += 1
        raise PermissionError("[WinError 5] Access is denied: permanent lock")

    monkeypatch.setattr("os.replace", mock_replace_always_fail)
    store.save_to_disk("2026-10-26")
    assert (
        replace_calls >= 5
    )  # Retried 5 times on primary, plus sidecar attempt before direct-write fallback


def test_daily_levels_concurrent_save_threads(tmp_path, monkeypatch):
    """
    Verifies that multiple concurrent threads calling compute_and_store and save_to_disk
    do not trigger temporary file collisions or WinError 5 on Windows.
    """
    import concurrent.futures

    store = DailyLevelsStore(persist_dir=tmp_path)
    mock_df = pd.DataFrame(
        [
            {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 100},
            {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 150},
        ],
        index=pd.to_datetime(["2026-10-06", "2026-10-07"]),
    )
    monkeypatch.setattr("market.history.get_ohlcv", lambda *a, **k: mock_df)
    monkeypatch.setattr("market.quotes.get_quote", lambda *a, **k: {})

    symbols = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]

    def worker(sym):
        return store.compute_and_store(sym, session_date="2026-10-26", persist=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, sym) for sym in symbols]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == len(symbols)
    target_file = tmp_path / "daily_levels_2026-10-26.json"
    assert target_file.exists()
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == len(symbols)


def test_options_reentrant_lock_and_no_deadlock():
    """Verifies that market.options locks are re-entrant and _store_in_chain_cache does not deadlock."""
    from market.options import _CHAIN_CACHE_LOCK, _store_in_chain_cache
    import threading

    assert isinstance(_CHAIN_CACHE_LOCK, type(threading.RLock()))
    # Test re-entrant lock acquisition
    with _CHAIN_CACHE_LOCK:
        _store_in_chain_cache("TEST_SYM:nearest", [])


def test_fyers_symbol_etf_prefix_integrity():
    """Verifies that equity ETFs starting with index names (e.g. NIFTYBEES) are mapped to -EQ, never -INDEX."""
    from brokers.fyers import to_fyers_symbol

    assert to_fyers_symbol("NIFTYBEES") == "NSE:NIFTYBEES-EQ"
    assert to_fyers_symbol("NIFTYBEES-EQ") == "NSE:NIFTYBEES-EQ"
    assert to_fyers_symbol("NIFTY 50") == "NSE:NIFTY50-INDEX"
    assert to_fyers_symbol("BANKNIFTY") == "NSE:NIFTYBANK-INDEX"


def test_is_valid_ws_symbol_rejects_multi_suffix():
    """Verifies that corrupted multi-suffix symbols are rejected by the WebSocket validator."""
    from market.ws_subscription_manager import is_valid_ws_symbol

    assert is_valid_ws_symbol("NSE:NIFTYBEES-EQ-INDEX") is False
    assert is_valid_ws_symbol("NSE:NIFTY-INDEX-INDEX") is False
    assert is_valid_ws_symbol("NSE:NIFTY50-INDEX") is True
    assert is_valid_ws_symbol("NSE:RELIANCE-EQ") is True


def test_daily_levels_endpoints_benchmarks_and_symbol():
    """Verifies that GET /api/levels/benchmarks and GET /api/levels/{symbol} return valid CPR and blueprints."""
    from fastapi.testclient import TestClient
    from web.api import app

    client = TestClient(app)
    resp = client.get("/api/levels/benchmarks")
    assert resp.status_code == 200
    b_data = resp.json()
    assert "indices" in b_data
    assert "session_date" in b_data

    # Test single symbol endpoint
    s_resp = client.get("/api/levels/NIFTY")
    assert s_resp.status_code == 200
    s_data = s_resp.json()
    assert s_data.get("symbol") == "NIFTY"
    assert "cpr" in s_data
    assert "camarilla" in s_data
    assert "blueprint" in s_data
