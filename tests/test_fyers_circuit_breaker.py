"""
tests/test_fyers_circuit_breaker.py
───────────────────────────────────
Tests for FyersCircuitBreaker trip logic, SSE/Telegram alerts, and fast-fail behavior.
"""

import time
from unittest.mock import MagicMock, patch

from market.fyers_circuit_breaker import FyersCircuitBreaker, CircuitState
from brokers.fyers import FyersAPI


def test_circuit_breaker_trip_on_429():
    cb = FyersCircuitBreaker(cooldown_sec=1.0)
    assert not cb.is_tripped()
    assert cb.state == CircuitState.CLOSED

    mock_sse = MagicMock()
    mock_tg = MagicMock()

    with (
        patch("web.sse.event_bus.publish_sync", mock_sse),
        patch("bot.telegram_bot.send_push", mock_tg),
    ):
        # Record HTTP 429 rate limit failure
        cb.record_failure(status_code=429, error_message="Rate limit 200 req/min exceeded")

        assert cb.is_tripped() is True
        assert cb.state == CircuitState.OPEN

        # Both SSE and Telegram alerts must have been dispatched
        assert mock_sse.call_count == 1
        assert mock_tg.call_count == 1
        sse_event = mock_sse.call_args[0][1]
        assert sse_event["type"] == "fyers_circuit_breaker_tripped"
        assert sse_event["service"] == "FYERS_API"


def test_circuit_breaker_cooldown_and_recovery():
    cb = FyersCircuitBreaker(cooldown_sec=0.2)
    cb.record_failure(status_code=429, error_message="Rate limited")
    assert cb.state == CircuitState.OPEN

    # Wait for cooldown to expire
    time.sleep(0.25)
    # Checking state should now show HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.is_tripped() is False  # Half open allows trial probe

    # Record successful probe
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.is_tripped() is False


def test_circuit_breaker_guards_fyers_api(monkeypatch):
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"

    mock_fyers_client = MagicMock()
    monkeypatch.setattr(api, "_get_fyers", lambda: mock_fyers_client)

    from market.fyers_circuit_breaker import get_fyers_circuit_breaker

    cb = get_fyers_circuit_breaker()
    # Trip circuit breaker
    cb.record_failure(status_code=429, error_message="Test trip")

    try:
        # Calls should fast-fail without calling underlying Fyers client
        quotes = api.get_quote(["NSE:RELIANCE-EQ"])
        assert quotes == {}
        assert mock_fyers_client.quotes.call_count == 0

        chain = api.get_options_chain("NSE:NIFTY50-INDEX")
        assert chain == []
        assert mock_fyers_client.optionchain.call_count == 0

        history = api.get_historical_data("RELIANCE")
        assert history == []
        assert mock_fyers_client.history.call_count == 0
    finally:
        # Reset circuit breaker
        cb.record_success()
