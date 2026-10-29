"""
tests/test_fyers_rate_gate.py
─────────────────────────────
Comprehensive tests for UnifiedFyersRateGate and prioritized rate limiting.
"""

import time
import threading
from unittest.mock import MagicMock

from market.fyers_rate_gate import (
    FyersCallCategory,
    UnifiedFyersRateGate,
    get_fyers_rate_gate,
)
from brokers.fyers import FyersAPI


def test_rate_gate_singleton():
    gate1 = get_fyers_rate_gate()
    gate2 = get_fyers_rate_gate()
    assert gate1 is gate2


def test_rate_gate_diagnostics_structure():
    gate = UnifiedFyersRateGate(max_per_sec=8.0, max_per_min=160.0)
    gate.acquire(category=FyersCallCategory.ORDER)
    gate.acquire(category=FyersCallCategory.SCANNER_QUOTE)

    diag = gate.get_diagnostics()
    assert diag["max_per_sec"] == 8.0
    assert diag["max_per_min"] == 160.0
    assert diag["requests_last_sec"] == 2
    assert diag["requests_last_min"] == 2
    assert diag["remaining_min_budget"] == 158.0
    assert diag["total_requests_by_tier"]["ORDER"] >= 1
    assert diag["total_requests_by_tier"]["SCANNER_QUOTE"] >= 1
    assert diag["status"] == "HEALTHY"


def test_rate_gate_priority_ordering():
    """
    Verify that an ORDER request (Tier 0) jumps ahead of a HISTORICAL request (Tier 4)
    when both are queued.
    """
    gate = UnifiedFyersRateGate(max_per_sec=2.0, max_per_min=10.0)

    # Exhaust current 1-second limit (2 tokens)
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE) is True
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE) is True

    acquisition_order = []

    def worker_historical():
        # Will be queued behind saturated rate limit
        gate.acquire(category=FyersCallCategory.HISTORICAL)
        acquisition_order.append("HISTORICAL")

    def worker_order():
        # High priority: should jump ahead of historical in the queue
        gate.acquire(category=FyersCallCategory.ORDER)
        acquisition_order.append("ORDER")

    # Start historical first
    t_hist = threading.Thread(target=worker_historical, daemon=True)
    t_hist.start()
    time.sleep(0.05)  # Ensure historical enters wait queue first

    # Start order next
    t_order = threading.Thread(target=worker_order, daemon=True)
    t_order.start()

    t_order.join(timeout=3.0)
    t_hist.join(timeout=3.0)

    assert not t_order.is_alive()
    assert not t_hist.is_alive()

    # ORDER must have acquired BEFORE HISTORICAL despite starting later
    assert acquisition_order == ["ORDER", "HISTORICAL"]


def test_expiry_timestamp_and_dates_caching(monkeypatch):
    """
    Verify that optionchain is called once and subsequent calls hit the 12h in-memory cache.
    """
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    mock_client = MagicMock()
    mock_client.optionchain.return_value = {
        "s": "ok",
        "data": {
            "expiryData": [
                {"date": "15-10-2026", "expiry": "1756980000"},
                {"date": "22-10-2026", "expiry": "1757584800"},
            ]
        },
    }
    monkeypatch.setattr(api, "_get_fyers", lambda: mock_client)

    # First call: populates cache
    ts1 = api._resolve_expiry_timestamp("NSE:NIFTY50-INDEX", "2026-10-15")
    assert ts1 == "1756980000"
    assert mock_client.optionchain.call_count == 1

    # Second call for the other date: should be retrieved directly from cache!
    ts2 = api._resolve_expiry_timestamp("NSE:NIFTY50-INDEX", "2026-10-22")
    assert ts2 == "1757584800"
    assert mock_client.optionchain.call_count == 1  # Still 1 call, zero repeat!

    # get_expiries should also reuse the cache
    expiries = api.get_expiries("NSE:NIFTY50-INDEX")
    assert expiries == ["2026-10-15", "2026-10-22"]
    assert mock_client.optionchain.call_count == 1  # Zero additional API calls


def test_historical_dedicated_rate_cap():
    """
    Verify that HISTORICAL calls strictly enforce minimum inter-request spacing
    and do not exceed 3 requests per second under concurrent load.
    """
    gate = UnifiedFyersRateGate(max_per_sec=10.0, max_per_min=100.0)

    # First call grants immediately
    t0 = time.time()
    assert gate.acquire(category=FyersCallCategory.HISTORICAL) is True

    # Second call must wait at least 0.35s
    assert gate.acquire(category=FyersCallCategory.HISTORICAL) is True
    t1 = time.time()
    dt = t1 - t0
    assert dt >= 0.34, f"HISTORICAL inter-request spacing failed: dt={dt:.4f}s"


def test_in_flight_history_coalescing(monkeypatch):
    """
    Verify that multiple concurrent calls to get_ohlcv for the same symbol
    coalesce into a single broker historical fetch.
    """
    from market.history import get_ohlcv
    from datetime import datetime

    mock_broker = MagicMock()
    mock_broker._is_mock = False
    fake_candles = [
        {
            "date": "2026-10-27 09:15:00",
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 104.0,
            "volume": 1000,
        }
    ]
    call_count = 0
    call_lock = threading.Lock()

    def slow_historical(*args, **kwargs):
        nonlocal call_count
        with call_lock:
            call_count += 1
        time.sleep(0.15)  # Simulate network latency
        return fake_candles

    mock_broker.get_historical_data.side_effect = slow_historical

    monkeypatch.setattr("brokers.session.get_data_broker", lambda: mock_broker)
    monkeypatch.setattr("brokers.session.get_data_broker_key", lambda: "fyers")

    results = []
    res_lock = threading.Lock()

    def caller():
        df = get_ohlcv(
            symbol="COALESCE_TEST_SYM",
            exchange="NSE",
            interval="15m",
            days=1,
            from_date=datetime(2026, 10, 27, 9, 15),
            to_date=datetime(2026, 10, 27, 15, 30),
        )
        with res_lock:
            results.append(df)

    threads = [threading.Thread(target=caller) for _ in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    # All 5 callers must receive non-empty DataFrames
    assert len(results) == 5
    for df in results:
        assert not df.empty

    # But the live broker must have been called exactly ONCE (all 4 followers coalesced)
    assert call_count == 1


def test_quota_deferred_persistence(monkeypatch):
    """Verify rate gate marks quota dirty on acquire without synchronous disk writes."""
    gate = UnifiedFyersRateGate(max_per_sec=10.0, max_per_min=500.0)
    save_mock = MagicMock()
    monkeypatch.setattr(gate, "_save_daily_quota", save_mock)

    assert not gate._quota_dirty
    assert gate.acquire(category=FyersCallCategory.ORDER) is True

    # Quota is marked dirty, but _save_daily_quota was NOT called synchronously
    assert gate._quota_dirty is True
    assert save_mock.call_count == 0

    # flush_quota synchronously flushes and clears the dirty flag
    gate.flush_quota()
    assert gate._quota_dirty is False
    assert save_mock.call_count == 1


def test_waiter_aware_minute_budget():
    """Verify that _calculate_sleep_needed accounts for pending waiters in minute load."""
    gate = UnifiedFyersRateGate(max_per_sec=10.0, max_per_min=5.0)
    now = time.time()
    # Fill sliding window with 3 requests
    gate._sliding_window.append((now - 10.0, FyersCallCategory.ORDER))
    gate._sliding_window.append((now - 8.0, FyersCallCategory.ORDER))
    gate._sliding_window.append((now - 5.0, FyersCallCategory.ORDER))

    # Without waiters: 3 items < 5 max_per_min -> no minute-based sleep needed
    sleep_no_waiters = gate._calculate_sleep_needed(now, category=FyersCallCategory.ORDER)
    assert sleep_no_waiters <= 0.05

    # Simulate 3 queued waiters in self._waiters: 3 + 3 = 6 >= 5 max_per_min
    dummy_event = threading.Event()
    gate._waiters.append((0, 1, FyersCallCategory.ORDER, dummy_event))
    gate._waiters.append((0, 2, FyersCallCategory.ORDER, dummy_event))
    gate._waiters.append((0, 3, FyersCallCategory.ORDER, dummy_event))

    sleep_with_waiters = gate._calculate_sleep_needed(now, category=FyersCallCategory.ORDER)
    # Must enforce sleep because effective_min_load (6) >= max_per_min (5)
    assert sleep_with_waiters > 40.0
