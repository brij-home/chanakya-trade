"""
tests/test_flattrade_rate_gate.py
─────────────────────────────────
Unit tests for the UnifiedFlattradeRateGate (sliding window, priority tiers, pacing).
"""

import time
from market.flattrade_rate_gate import (
    FlattradeCallCategory,
    UnifiedFlattradeRateGate,
    get_flattrade_rate_gate,
)


def test_flattrade_rate_gate_singleton():
    gate1 = get_flattrade_rate_gate()
    gate2 = get_flattrade_rate_gate()
    assert gate1 is gate2


def test_flattrade_rate_gate_acquire_and_diagnostics():
    gate = UnifiedFlattradeRateGate(max_per_sec=5.0, max_per_min=50.0, max_hist_per_sec=2.0)

    # Immediate acquisition
    acquired = gate.acquire(category=FlattradeCallCategory.ORDER, timeout=1.0)
    assert acquired is True

    diag = gate.get_diagnostics()
    assert diag["plan"] == "PI_CONNECT"
    assert diag["status"] == "NOMINAL"
    assert diag["max_per_sec"] == 5.0
    assert diag["requests_last_sec"] >= 1
    assert diag["total_requests"] >= 1


def test_flattrade_rate_gate_priority_ordering():
    gate = UnifiedFlattradeRateGate(max_per_sec=2.0, max_per_min=10.0, max_hist_per_sec=1.0)

    # Fill capacity
    assert gate.acquire(category=FlattradeCallCategory.SCANNER_QUOTE, timeout=0.1) is True
    assert gate.acquire(category=FlattradeCallCategory.SCANNER_QUOTE, timeout=0.1) is True

    # Next call should wait or pace
    t0 = time.time()
    acquired = gate.acquire(category=FlattradeCallCategory.ORDER, timeout=2.0)
    elapsed = time.time() - t0

    assert acquired is True
    assert elapsed >= 0.3  # Paced through sliding window


def test_flattrade_rate_gate_timeout_wakes_next_waiter_and_fails_closed():
    import threading
    from unittest.mock import MagicMock
    import pytest
    from brokers import flattrade
    from brokers.flattrade import FlattradeAPI
    from market.flattrade_rate_gate import get_flattrade_rate_gate

    gate = get_flattrade_rate_gate()
    gate.reset_state()

    local_gate = UnifiedFlattradeRateGate(max_per_sec=1.0, max_per_min=10.0, max_hist_per_sec=1.0)
    assert local_gate.acquire(FlattradeCallCategory.SCANNER_QUOTE, timeout=0.5) is True

    results: dict[str, bool] = {}

    def _short_waiter():
        results["short"] = local_gate.acquire(FlattradeCallCategory.SCANNER_QUOTE, timeout=0.05)

    def _normal_waiter():
        results["normal"] = local_gate.acquire(FlattradeCallCategory.ORDER, timeout=1.8)

    t1 = threading.Thread(target=_short_waiter, daemon=True)
    t2 = threading.Thread(target=_normal_waiter, daemon=True)
    t1.start()
    time.sleep(0.01)
    t2.start()
    t1.join(timeout=1.0)
    t2.join(timeout=2.0)

    assert results["short"] is False
    assert results["normal"] is True

    # Verify FlattradeAPI._post fails closed on rate-gate timeout rather than bypassing via HTTP POST.
    broker = FlattradeAPI(user_id="FT100", api_key="AK", api_secret="AS")
    broker._token = "tok"
    broker._token_date = flattrade._today_ist()
    broker._client = MagicMock()
    old_acquire = gate.acquire
    gate.acquire = lambda *a, **kw: False
    try:
        with pytest.raises(TimeoutError, match="Rate gate wait timed out"):
            broker._post("GetQuotes", {"exch": "NSE", "token": "26000"})
        broker._client.post.assert_not_called()
    finally:
        gate.acquire = old_acquire
        gate.reset_state()
