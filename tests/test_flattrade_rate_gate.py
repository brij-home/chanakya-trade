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
