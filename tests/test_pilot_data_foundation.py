"""Tests for the truthful EOD, stream and pilot-safety foundations."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_eod_snapshot_is_content_addressed_and_replayable(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_PLATFORM_HOME", str(tmp_path))
    from market.eod_store import load_eod_snapshot, save_eod_snapshot

    rows = [
        {"date": "2026-09-01", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 123}
    ]
    snapshot_id = save_eod_snapshot(
        canonical_instrument_id="NSE:RELIANCE:EQUITY",
        provider="shoonya",
        provider_symbol="NSE:RELIANCE",
        as_of_date="2026-09-01",
        rows=rows,
    )
    replay = load_eod_snapshot("NSE:RELIANCE:EQUITY", as_of_date="2026-09-01")

    assert replay is not None
    assert replay["snapshot_id"] == snapshot_id
    assert replay["rows"] == rows
    assert replay["checksum"]


def test_market_event_never_infers_freshness_from_request_duration():
    from market.data_events import MarketDataEvent

    event = MarketDataEvent(
        canonical_instrument_id="NSE:RELIANCE:EQUITY",
        provider="shoonya",
        provider_symbol="RELIANCE-EQ",
        source="REST",
        data_state="LIVE",
        last_price=100.0,
        received_at=datetime.now(timezone.utc).isoformat(),
    )
    assert event.age_seconds is not None
    assert event.age_seconds < 1.0
    assert event.is_fresh_live


def test_shoonya_stream_normalizer_keeps_provider_and_token():
    from market.streaming import normalize_shoonya_tick

    event = normalize_shoonya_tick({"e": "NSE", "tk": "2885", "lp": "1420.25", "bp1": "1420.10"})
    assert event is not None
    assert event.provider == "shoonya"
    assert event.provider_symbol == "2885"
    assert event.source == "STREAM"
    assert event.data_state == "LIVE"


def test_stream_flags_unusual_move_without_silently_dropping_market_data(monkeypatch):
    from market.data_events import MarketDataEvent
    from market.streaming import MarketDataStreamRegistry

    monkeypatch.setenv("MARKET_DATA_JUMP_PCT", "5")
    registry = MarketDataStreamRegistry()
    seen = []
    registry.subscribe(seen.append)
    registry.publish(
        MarketDataEvent(
            canonical_instrument_id="NSE:RELIANCE:EQUITY",
            provider="shoonya",
            provider_symbol="RELIANCE-EQ",
            source="STREAM",
            data_state="LIVE",
            last_price=100.0,
        )
    )
    registry.publish(
        MarketDataEvent(
            canonical_instrument_id="NSE:RELIANCE:EQUITY",
            provider="shoonya",
            provider_symbol="RELIANCE-EQ",
            source="STREAM",
            data_state="LIVE",
            last_price=110.0,
        )
    )
    assert len(seen) == 2
    assert "UNUSUAL_PRICE_JUMP" in seen[-1].quality_flags
    assert seen[-1].data_state == "LIVE"


def test_pilot_profile_fails_closed_until_deliberately_enabled(monkeypatch):
    from engine.pilot_safety import assert_pilot_execution_allowed

    monkeypatch.delenv("PILOT_ALLOW_LIVE_EXECUTION", raising=False)
    with pytest.raises(PermissionError, match="disabled"):
        assert_pilot_execution_allowed(segment="EQUITY_DELIVERY", product="CNC", notional=1000)

    monkeypatch.setenv("PILOT_ALLOW_LIVE_EXECUTION", "1")
    monkeypatch.setenv("PILOT_MAX_ORDER_NOTIONAL", "1000")
    assert_pilot_execution_allowed(segment="EQUITY_DELIVERY", product="CNC", notional=1000)
    with pytest.raises(PermissionError, match="exceeds"):
        assert_pilot_execution_allowed(segment="EQUITY_DELIVERY", product="CNC", notional=1001)


def test_derivative_requires_verified_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_PLATFORM_HOME", str(tmp_path))
    from engine.order_lifecycle import _resolve_order_instrument
    from market.instrument_master import upsert_verified_contract

    with pytest.raises(ValueError, match="provider-verified"):
        _resolve_order_instrument("NFO:NIFTY26SEP25000CE", "NRML")

    upsert_verified_contract(
        lookup_symbol="NFO:NIFTY26SEP25000CE",
        provider="shoonya",
        provider_symbol="NIFTY26SEP25000CE",
        provider_token="12345",
        exchange="NFO",
        segment="FNO",
        lot_size=75,
        tick_size=0.05,
    )
    _, exchange, segment = _resolve_order_instrument("NFO:NIFTY26SEP25000CE", "NRML")
    assert exchange == "NFO"
    assert segment == "OPTIONS"


def test_cash_equity_suffix_is_not_misclassified_as_option():
    """CE in an equity name is not an option suffix without a numeric strike."""
    from market.instrument_master import is_derivative_query

    assert not is_derivative_query("RELIANCE")
    assert is_derivative_query("NIFTY26SEP25000CE")
