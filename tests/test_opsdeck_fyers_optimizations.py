"""
tests/test_opsdeck_fyers_optimizations.py
─────────────────────────────────────────
Regression and invariant tests for the OpsDeck Fyers API optimizations and RCA fixes:
  - INC-001: Token-expiry circuit breaker suppression & instant auth recovery
  - INC-002: Options chain cache TTLs (60s index, 120s stock) & OptionsChainManager
  - INC-003: Rate gate deferred persistence and waiter-aware rolling budget
  - INC-004: Expired option contract extraction, detection, and alert invalidation
  - INC-005: mStock websocket reconnect debouncing
"""

import time
from datetime import date
from unittest.mock import MagicMock

import pytest

from market.fyers_circuit_breaker import (
    FyersCircuitBreaker,
    CircuitState,
    get_fyers_circuit_breaker,
)
from brokers.fyers import FyersAPI
from market.options import get_chain_cache_ttl
from market.fyers_rate_gate import UnifiedFyersRateGate, FyersCallCategory
from engine.alert_expiry import (
    extract_contract_expiry_date,
    is_contract_expired,
    purge_expired_option_contracts,
)
from market.oc_manager import get_oc_manager


# ── INC-001: Token-Expiry Circuit Breaker Trip & Recovery ──────────────────────


def test_token_expiry_circuit_breaker_trip_and_recovery():
    """Verify circuit breaker trips on code -16 with 300s cooldown and recovers on record_auth_success."""
    cb = FyersCircuitBreaker(cooldown_sec=60.0)
    assert cb.state == CircuitState.CLOSED

    # Record token expired failure
    cb.record_failure(status_code=-16, error_message="Token is Invalid or Expired")
    assert cb.state == CircuitState.OPEN
    assert cb.is_tripped() is True
    diag = cb.get_diagnostics()
    assert diag["cooldown_seconds"] == 300.0
    assert "Fyers Token Invalid or Expired" in diag["last_trip_reason"]

    # When fresh token is authenticated, record_auth_success immediately resets breaker
    cb.record_auth_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.is_tripped() is False


def test_fyers_api_profile_fails_closed_when_circuit_open(monkeypatch):
    """Verify FyersAPI.get_profile does not invoke underlying network when circuit is open."""
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"
    api._token_ts = time.time()

    mock_client = MagicMock()
    monkeypatch.setattr(api, "_get_fyers", lambda: mock_client)

    cb = get_fyers_circuit_breaker()
    cb.record_failure(status_code=-16, error_message="Token is Invalid or Expired")

    try:
        with pytest.raises(PermissionError, match="Fyers circuit breaker is OPEN"):
            api.get_profile()
        assert mock_client.get_profile.call_count == 0
    finally:
        cb.record_auth_success()


# ── INC-002: Options Chain Cache TTL & OCM ─────────────────────────────────────


def test_options_chain_cache_ttl_index_vs_stock(monkeypatch):
    """Verify 60s TTL for major index options and 120s TTL for stock options during live hours."""
    # Mock market as open
    monkeypatch.setattr("market.calendar.is_market_open", lambda exch: True)

    ttl_nifty = get_chain_cache_ttl(is_broker=True, is_empty=False, symbol="NIFTY")
    assert ttl_nifty == 60.0

    ttl_banknifty = get_chain_cache_ttl(is_broker=True, is_empty=False, symbol="BANKNIFTY")
    assert ttl_banknifty == 60.0

    ttl_stock = get_chain_cache_ttl(is_broker=True, is_empty=False, symbol="RELIANCE")
    assert ttl_stock == 120.0

    # Off market
    monkeypatch.setattr("market.calendar.is_market_open", lambda exch: False)
    ttl_closed = get_chain_cache_ttl(is_broker=True, is_empty=False, symbol="NIFTY")
    assert ttl_closed == 180.0


def test_options_chain_manager_singleton_and_subscriptions():
    """Verify OCM singleton tracks default index subscriptions and handles add/remove."""
    ocm = get_oc_manager()
    assert "NIFTY" in ocm.subscribed_symbols
    assert "BANKNIFTY" in ocm.subscribed_symbols

    ocm.subscribe("NSE:TCS-INDEX")
    assert "TCS" in ocm.subscribed_symbols

    ocm.unsubscribe("TCS")
    assert "TCS" not in ocm.subscribed_symbols


# ── INC-003: Rate Gate Deferred Persistence & Waiter-Aware Budget ──────────────


def test_rate_gate_deferred_persistence(monkeypatch):
    """Verify acquire() marks quota dirty without synchronous disk writes."""
    gate = UnifiedFyersRateGate(max_per_sec=10.0, max_per_min=500.0)
    save_mock = MagicMock()
    monkeypatch.setattr(gate, "_save_daily_quota", save_mock)

    assert not gate._quota_dirty
    assert gate.acquire(category=FyersCallCategory.ORDER) is True

    # Quota is dirty, but no sync disk write executed
    assert gate._quota_dirty is True
    assert save_mock.call_count == 0

    # Explicit flush flushes and clears dirty flag
    gate.flush_quota()
    assert gate._quota_dirty is False
    assert save_mock.call_count == 1


def test_rate_gate_waiter_aware_minute_budget():
    """Verify that _calculate_sleep_needed accounts for pending waiters in minute load."""
    gate = UnifiedFyersRateGate(max_per_sec=10.0, max_per_min=5.0)
    now = time.time()
    gate._sliding_window.append((now - 10.0, FyersCallCategory.ORDER))
    gate._sliding_window.append((now - 8.0, FyersCallCategory.ORDER))
    gate._sliding_window.append((now - 5.0, FyersCallCategory.ORDER))

    # Without waiters: 3 items < 5 max_per_min -> no sleep needed
    sleep_no_waiters = gate._calculate_sleep_needed(now, category=FyersCallCategory.ORDER)
    assert sleep_no_waiters <= 0.05

    # Simulate 3 queued waiters in self._waiters: 3 + 3 = 6 >= 5 max_per_min
    dummy_event = MagicMock()
    gate._waiters.append((0, 1, FyersCallCategory.ORDER, dummy_event))
    gate._waiters.append((0, 2, FyersCallCategory.ORDER, dummy_event))
    gate._waiters.append((0, 3, FyersCallCategory.ORDER, dummy_event))

    sleep_with_waiters = gate._calculate_sleep_needed(now, category=FyersCallCategory.ORDER)
    # Must enforce sleep because effective_min_load (6) >= max_per_min (5)
    assert sleep_with_waiters > 40.0


# ── INC-004: Expired Contract Extraction & Alert Purging ───────────────────────


def test_extract_contract_expiry_date():
    """Verify date extraction across broker YYYYMMDD and standard contract formats."""
    # Broker YYYYMMDD format
    d1 = extract_contract_expiry_date("M&M202609293050PE")
    assert d1 == date(2026, 9, 29)

    d2 = extract_contract_expiry_date("NSE:HAL202610274800PE")
    assert d2 == date(2026, 10, 27)

    # Weekly format (e.g. 26924 -> 2026-09-24)
    d3 = extract_contract_expiry_date("NIFTY2692425000CE")
    assert d3 == date(2026, 9, 24)


def test_is_contract_expired_and_purging():
    """Verify expired contract detection against current reference date."""
    ref_date = date(2026, 10, 27)

    # Expired in September 2026
    assert is_contract_expired("M&M202609293050PE", current_date=ref_date) is True
    # Expiring today (not expired yet)
    assert is_contract_expired("HAL202610274800PE", current_date=ref_date) is False
    # Non-derivative equity
    assert is_contract_expired("NSE:RELIANCE", current_date=ref_date) is False

    symbols = ["M&M202609293050PE", "NSE:RELIANCE", "HAL202610274800PE"]
    purged = purge_expired_option_contracts(symbols, current_date=ref_date)
    assert purged == ["NSE:RELIANCE", "HAL202610274800PE"]


def test_alert_manager_purges_expired_contracts(monkeypatch):
    """Verify AlertManager invalidates alerts for expired option contracts."""
    from engine.alerts import AlertManager, Alert

    am = AlertManager()
    am._alerts.clear()

    # Add expired alert (Sep 2026) and active equity alert
    expired_alert = Alert(
        id="test-exp-1",
        symbol="M&M202609293050PE",
        exchange="NSE",
        condition="ABOVE",
        threshold=100.0,
        alert_type="PRICE",
    )
    active_alert = Alert(
        id="test-act-1",
        symbol="RELIANCE",
        exchange="NSE",
        condition="ABOVE",
        threshold=2500.0,
        alert_type="PRICE",
    )

    am._alerts = [expired_alert, active_alert]

    purged_count = am.purge_expired_option_alerts()
    assert purged_count == 1
    assert expired_alert.is_invalidated is True
    assert "Option contract expired" in expired_alert.invalidation_reason
    assert active_alert.is_invalidated is False


def test_fyers_broker_all_endpoints_fail_closed_when_circuit_tripped(monkeypatch):
    """Verify all FyersAPI data and execution endpoints fail closed without network calls when circuit is open."""
    api = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    api._access_token = "mock_token"
    api._token_ts = time.time()

    mock_client = MagicMock()
    monkeypatch.setattr(api, "_get_fyers", lambda: mock_client)

    cb = get_fyers_circuit_breaker()
    cb.record_failure(status_code=-16, error_message="Token is Invalid or Expired")

    try:
        # Funds raises PermissionError
        with pytest.raises(PermissionError, match="Fyers circuit breaker is OPEN"):
            api.get_funds()

        # Holdings fails safe to empty list
        assert api.get_holdings() == []

        # Positions fails safe to empty list
        assert api.get_positions() == []

        # Orders fails safe to empty list
        assert api.get_orders() == []

        # Expiries fails safe to empty list
        assert api.get_expiries("NIFTY") == []

        # Place order fails closed with REJECTED status
        from brokers.base import OrderRequest

        req = OrderRequest(
            symbol="RELIANCE",
            exchange="NSE",
            transaction_type="BUY",
            quantity=1,
            order_type="MARKET",
            product="CNC",
        )
        resp = api.place_order(req)
        assert resp.status == "REJECTED"
        assert "circuit breaker is OPEN" in resp.message

        # Ensure zero underlying network calls were made across all above calls
        assert mock_client.funds.call_count == 0
        assert mock_client.holdings.call_count == 0
        assert mock_client.positions.call_count == 0
        assert mock_client.orderbook.call_count == 0
        assert mock_client.optionchain.call_count == 0
        assert mock_client.place_order.call_count == 0
    finally:
        cb.record_auth_success()


def test_options_chain_bypass_cache_and_get_cached_chain(monkeypatch):
    """Verify get_options_chain honors bypass_cache and OCM.get_cached_chain reads from memory."""
    from market.options import get_options_chain, _CHAIN_CACHE, _CHAIN_CACHE_LOCK
    from brokers.base import OptionsContract

    ocm = get_oc_manager()
    clean_sym = "NIFTY"
    cache_key = f"{clean_sym}:nearest"

    sample_contract = OptionsContract(
        symbol="NIFTY26OCT25000CE",
        underlying="NIFTY",
        strike=25000.0,
        option_type="CE",
        expiry="2026-10-29",
        last_price=120.0,
        oi=1000,
        oi_change=50,
        volume=5000,
    )

    with _CHAIN_CACHE_LOCK:
        _CHAIN_CACHE[cache_key] = (time.time(), [sample_contract])

    # 1. get_cached_chain returns cached contract instantly from memory
    cached = ocm.get_cached_chain("NIFTY")
    assert len(cached) == 1
    assert cached[0].symbol == "NIFTY26OCT25000CE"

    # 2. Standard call without bypass returns cached version without broker fetch
    mock_broker = MagicMock()
    monkeypatch.setattr("market.options.get_data_broker", lambda: mock_broker)
    res = get_options_chain("NIFTY", bypass_cache=False)
    assert len(res) == 1
    assert mock_broker.get_options_chain.call_count == 0
