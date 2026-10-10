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
