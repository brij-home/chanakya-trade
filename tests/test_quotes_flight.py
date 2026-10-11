"""
tests/test_quotes_flight.py
───────────────────────────
Validates in-flight request coalescing (single-flight) in market/quotes.py.
Ensures that concurrent threads requesting the exact same missing instrument
only trigger a single external broker REST call, eliminating redundant network calls.
"""

from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch

from market.quotes import get_quote, clear_quote_cache, Quote


def test_in_flight_quotes_coalescing():
    clear_quote_cache()

    call_count = 0
    call_lock = threading.Lock()

    def slow_broker_get_quote(instruments):
        nonlocal call_count
        with call_lock:
            call_count += 1
        time.sleep(0.08)  # simulate network latency
        results = {}
        for inst in instruments:
            q = Quote(
                symbol=inst.split(":")[-1],
                last_price=1850.50,
                close=1840.00,
                open=1845.00,
                high=1860.00,
                low=1840.00,
                volume=500000,
                change=10.50,
                change_pct=0.57,
            )
            results[inst] = q
        return results

    mock_broker = MagicMock()
    mock_broker.get_quote.side_effect = slow_broker_get_quote

    results = []

    def worker():
        q_dict = get_quote("NSE:INFY")
        results.append(q_dict.get("NSE:INFY"))

    with (
        patch("market.quotes.get_data_broker", return_value=mock_broker),
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
    ):
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # Verify that broker was only called once despite 6 concurrent requests
    assert call_count == 1, f"Expected 1 broker call, got {call_count}"
    assert len(results) == 6
    for q in results:
        assert q is not None
        assert q.last_price == 1850.50
        assert q.symbol == "INFY"


def test_in_flight_quotes_leader_error_no_deadlock():
    clear_quote_cache()

    def failing_broker_get_quote(instruments):
        time.sleep(0.05)
        raise ConnectionResetError("Broker connection reset")

    mock_broker = MagicMock()
    mock_broker.get_quote.side_effect = failing_broker_get_quote

    results = []

    def worker():
        q_dict = get_quote("NSE:RELIANCE")
        results.append(q_dict.get("NSE:RELIANCE"))

    # When broker fails, fallback to yfinance may succeed or return empty, but must never hang/deadlock
    with (
        patch("market.quotes.get_data_broker", return_value=mock_broker),
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
        patch("market.yfinance_provider.yf_available", return_value=False),
    ):
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)
            assert not t.is_alive(), "Worker thread deadlocked during leader error!"

    assert len(results) == 4
