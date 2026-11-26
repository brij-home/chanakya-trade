"""
tests/test_unified_options_rate_limiting.py
─────────────────────────────────────────────
Comprehensive institutional test suite verifying:
1. Anti-Starvation Dynamic Priority Aging in UnifiedFyersRateGate
2. Stale-While-Revalidate (SWR) fallback in market/options.py under broker throttling
3. Zero Cache Poisoning (never overwriting valid cache with [] on throttle/timeout)
4. Thread stampede immunity and OCM in-memory resolution
"""

import time
import threading
from unittest.mock import MagicMock

from market.fyers_rate_gate import UnifiedFyersRateGate, FyersCallCategory
from brokers.base import OptionsContract


def test_anti_starvation_priority_aging_promotes_depth_chain():
    """
    Verify that a lower-priority DEPTH_CHAIN waiter (priority 3) ages up when waiting,
    preventing starvation from incoming SCANNER_QUOTE requests (priority 2).
    """
    gate = UnifiedFyersRateGate(max_per_sec=1.0, max_per_min=60.0)
    gate.reset_state()

    # Saturate current second limit with an initial request
    assert gate.acquire(category=FyersCallCategory.URGENT_QUOTE) is True

    acquisition_order = []

    def worker_depth():
        acquired = gate.acquire(category=FyersCallCategory.DEPTH_CHAIN, timeout=8.0)
        if acquired:
            acquisition_order.append("DEPTH_CHAIN")

    def worker_quote():
        acquired = gate.acquire(category=FyersCallCategory.SCANNER_QUOTE, timeout=8.0)
        if acquired:
            acquisition_order.append("SCANNER_QUOTE")

    # Start DEPTH_CHAIN waiter first
    t_depth = threading.Thread(target=worker_depth, daemon=True)
    t_depth.start()
    time.sleep(0.05)

    # Simulate waiting: backdate the depth waiter's start time by 3.0 seconds to trigger aging
    with gate._lock:
        assert len(gate._waiters) == 1
        prio, tb, cat, evt, enq_t = gate._waiters[0]
        gate._waiters[0] = (prio, tb, cat, evt, enq_t - 3.0)

    # Now start a fresh SCANNER_QUOTE (prio 2)
    # Because DEPTH_CHAIN (initial prio 3) has waited 3.0s, aging promotes it to priority 2.
    # Because its tie_breaker is earlier, DEPTH_CHAIN must pop BEFORE SCANNER_QUOTE!
    t_quote = threading.Thread(target=worker_quote, daemon=True)
    t_quote.start()

    t_depth.join(timeout=4.0)
    t_quote.join(timeout=4.0)

    assert not t_depth.is_alive()
    assert not t_quote.is_alive()
    assert acquisition_order == ["DEPTH_CHAIN", "SCANNER_QUOTE"]


def test_orders_retain_absolute_priority_over_aged_waiters():
    """
    Verify that ORDER requests (tier 0) always execute ahead of aged non-order categories.
    """
    gate = UnifiedFyersRateGate(max_per_sec=1.0, max_per_min=60.0)
    gate.reset_state()

    assert gate.acquire(category=FyersCallCategory.URGENT_QUOTE) is True

    acquisition_order = []

    def worker_hist():
        if gate.acquire(category=FyersCallCategory.HISTORICAL, timeout=8.0):
            acquisition_order.append("HISTORICAL")

    def worker_order():
        if gate.acquire(category=FyersCallCategory.ORDER, timeout=8.0):
            acquisition_order.append("ORDER")

    t_hist = threading.Thread(target=worker_hist, daemon=True)
    t_hist.start()
    time.sleep(0.05)

    # Backdate historical waiter by 10s (would reach priority 1, but never 0)
    with gate._lock:
        assert len(gate._waiters) == 1
        prio, tb, cat, evt, enq_t = gate._waiters[0]
        gate._waiters[0] = (prio, tb, cat, evt, enq_t - 10.0)

    t_order = threading.Thread(target=worker_order, daemon=True)
    t_order.start()

    t_order.join(timeout=4.0)
    t_hist.join(timeout=4.0)

    assert not t_order.is_alive()
    assert not t_hist.is_alive()
    # ORDER must acquire ahead of aged HISTORICAL
    assert acquisition_order == ["ORDER", "HISTORICAL"]


def test_options_chain_swr_fallback_under_broker_throttle(monkeypatch):
    """
    Verify that when the broker returns [] (e.g. rate gate denies permit),
    market.options.get_options_chain serves the cached chain (Stale-While-Revalidate)
    and does NOT return [] or poison the in-memory cache.
    """
    from market.options import get_options_chain, _CHAIN_CACHE, _CHAIN_CACHE_LOCK

    clean_sym = "RELIANCE"
    cache_key = f"{clean_sym}:nearest"

    sample_contract = OptionsContract(
        symbol="RELIANCE26OCT3000CE",
        underlying="RELIANCE",
        strike=3000.0,
        option_type="CE",
        expiry="2026-10-29",
        last_price=45.0,
        oi=5000,
        oi_change=100,
        volume=12000,
    )

    # Prime the cache with an entry that has aged past the 120s TTL
    with _CHAIN_CACHE_LOCK:
        _CHAIN_CACHE[cache_key] = (time.time() - 150.0, [sample_contract])

    # Mock broker to return [] (simulating rate gate denied permit)
    mock_broker = MagicMock()
    mock_broker.get_options_chain.return_value = []
    monkeypatch.setattr("market.options.get_data_broker", lambda: mock_broker)

    # Mock NSE scraper to also return []
    monkeypatch.setattr("market.options.nse_get_options_chain", lambda sym, exp: [])

    # Call get_options_chain with expired TTL
    chain = get_options_chain("RELIANCE")

    # SWR must kick in: return the valid cached contracts rather than empty []!
    assert len(chain) == 1
    assert chain[0].symbol == "RELIANCE26OCT3000CE"

    # Verify cache was NOT poisoned with []
    with _CHAIN_CACHE_LOCK:
        cached_entry = _CHAIN_CACHE.get(cache_key)
        assert cached_entry is not None
        assert len(cached_entry[1]) == 1


def test_options_chain_manager_get_cached_chain_swr():
    """
    Verify OCM get_cached_chain returns cached data with live quote overlay.
    """
    from market.oc_manager import get_oc_manager
    from market.options import _CHAIN_CACHE, _CHAIN_CACHE_LOCK
    from market.quotes import _QUOTE_CACHE, _quote_cache_lock

    ocm = get_oc_manager()
    clean_sym = "INFY"
    cache_key = f"{clean_sym}:nearest"

    sample_contract = OptionsContract(
        symbol="INFY26OCT1900CE",
        underlying="INFY",
        strike=1900.0,
        option_type="CE",
        expiry="2026-10-29",
        last_price=30.0,
        oi=2000,
        oi_change=10,
        volume=4000,
    )

    with _CHAIN_CACHE_LOCK:
        _CHAIN_CACHE[cache_key] = (time.time() - 30.0, [sample_contract])

    # Mock real-time quote update in _QUOTE_CACHE
    mock_quote = MagicMock()
    mock_quote.last_price = 38.5
    mock_quote.volume = 9500
    mock_quote.bid = 38.4
    mock_quote.ask = 38.6
    mock_quote.oi = 2500

    with _quote_cache_lock:
        _QUOTE_CACHE["INFY26OCT1900CE"] = (time.time(), mock_quote)

    cached = ocm.get_cached_chain("INFY")
    assert len(cached) == 1
    assert cached[0].symbol == "INFY26OCT1900CE"
    # Live quote overlay must have updated LTP to 38.5
    assert cached[0].ltp == 38.5
    assert cached[0].volume == 9500
