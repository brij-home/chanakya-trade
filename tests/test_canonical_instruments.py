"""
tests/test_canonical_instruments.py
───────────────────────────────────
Unit tests for P1-A Canonical Instrument Master and Market Session State Engine.
"""

from datetime import datetime, timezone
from market.instruments import (
    resolve_canonical_instrument,
    get_market_session_state,
)


def test_resolve_equities():
    """Verify standard NSE/BSE equities resolve to canonical IDs."""
    rel = resolve_canonical_instrument("RELIANCE")
    assert rel.instrument_id == "NSE:RELIANCE:EQUITY"
    assert rel.symbol == "RELIANCE"
    assert rel.exchange == "NSE"
    assert rel.segment == "EQUITY"
    assert rel.lot_size == 1
    assert rel.tick_size == 0.05
    assert rel.is_tradable is True

    bse_tcs = resolve_canonical_instrument("BSE:TCS")
    assert bse_tcs.instrument_id == "BSE:TCS:EQUITY"
    assert bse_tcs.exchange == "BSE"


def test_resolve_indices():
    """Verify benchmark and sectoral indices resolve with lot sizes."""
    nifty = resolve_canonical_instrument("NIFTY")
    assert nifty.instrument_id == "NSE:NIFTY:INDEX"
    assert nifty.segment == "INDEX"
    assert nifty.lot_size == 25
    assert nifty.is_tradable is False  # Spot index is not directly tradable

    banknifty = resolve_canonical_instrument("BANKNIFTY")
    assert banknifty.instrument_id == "NSE:BANKNIFTY:INDEX"
    assert banknifty.lot_size == 15

    sensex = resolve_canonical_instrument("SENSEX")
    assert sensex.instrument_id == "BSE:SENSEX:INDEX"
    assert sensex.lot_size == 10


def test_resolve_mcx_commodities():
    """Verify MCX commodities resolve with standard contract multipliers."""
    gold = resolve_canonical_instrument("GOLD")
    assert gold.instrument_id == "MCX:GOLD:COMMODITY"
    assert gold.exchange == "MCX"
    assert gold.segment == "COMMODITY"
    assert gold.is_tradable is True

    crude = resolve_canonical_instrument("CRUDEOIL")
    assert crude.instrument_id == "MCX:CRUDEOIL:COMMODITY"
    assert crude.lot_size == 100


def test_resolve_currency_pairs():
    """Verify CDS currency pairs resolve with CDS venue and 0.0025 tick."""
    usdinr = resolve_canonical_instrument("USDINR")
    assert usdinr.instrument_id == "CDS:USDINR:CURRENCY"
    assert usdinr.exchange == "CDS"
    assert usdinr.segment == "CURRENCY"
    assert usdinr.lot_size == 1000
    assert usdinr.tick_size == 0.0025


def test_market_session_state_nse_open():
    """Verify market open state during NSE regular trading hours (e.g. Wednesday 11:00 AM IST = 05:30 UTC)."""
    # Wednesday 2026-09-02 05:30:00 UTC = 11:00:00 AM IST
    wed_11am_utc = datetime(2026, 9, 2, 5, 30, 0, tzinfo=timezone.utc)
    state = get_market_session_state(exchange="NSE", now_utc=wed_11am_utc)
    assert state.session_state == "OPEN"
    assert state.is_open is True
    assert "11:00:00 IST" in state.current_time_ist


def test_market_session_state_nse_pre_open():
    """Verify pre-open state at 09:05 AM IST (03:35 UTC)."""
    wed_0905am_utc = datetime(2026, 9, 2, 3, 35, 0, tzinfo=timezone.utc)
    state = get_market_session_state(exchange="NSE", now_utc=wed_0905am_utc)
    assert state.session_state == "PRE_OPEN"
    assert state.is_open is False


def test_market_session_state_nse_closed_evening():
    """Verify closed state after market hours at 18:00 PM IST (12:30 UTC)."""
    wed_18pm_utc = datetime(2026, 9, 2, 12, 30, 0, tzinfo=timezone.utc)
    state = get_market_session_state(exchange="NSE", now_utc=wed_18pm_utc)
    assert state.session_state == "CLOSED"
    assert state.is_open is False


def test_market_session_state_weekend():
    """Verify closed state on Saturday (2026-09-05)."""
    sat_utc = datetime(2026, 9, 5, 6, 0, 0, tzinfo=timezone.utc)
    state = get_market_session_state(exchange="NSE", now_utc=sat_utc)
    assert state.session_state == "CLOSED"
    assert state.is_open is False
    assert "weekend" in state.reason.lower()


def test_market_session_state_mcx_evening():
    """Verify MCX commodity market is OPEN at 20:00 PM IST (14:30 UTC) on weekdays."""
    wed_20pm_utc = datetime(2026, 9, 2, 14, 30, 0, tzinfo=timezone.utc)
    state = get_market_session_state(exchange="MCX", now_utc=wed_20pm_utc)
    assert state.session_state == "OPEN"
    assert state.is_open is True
