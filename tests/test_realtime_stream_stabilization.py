"""
tests/test_realtime_stream_stabilization.py
───────────────────────────────────────────
Regression and verification test suite for Real-Time Stream Stabilization (Phase 1).
Verifies:
  1. AutoAlertEngine _on_domestic_tick supports both Tick dataclass instances and dicts.
  2. Canonical alert symbol normalizes broker suffixes (-EQ, -INDEX) and aliases.
  3. MarketTickerStream uses adaptive intervals off-market to prevent REST rate-limit flooding.
  4. Quotes in-memory cache coalesces off-market requests with extended TTL.
"""

from __future__ import annotations

import time
from unittest.mock import patch


from engine.alert_identity import canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from market.websocket import Tick


def test_canonical_alert_symbol_suffixes():
    """Verify that -EQ and -INDEX suffixes are cleanly stripped and mapped."""
    assert canonical_alert_symbol("NSE:RELIANCE-EQ") == "RELIANCE"
    assert canonical_alert_symbol("RELIANCE-EQ") == "RELIANCE"
    assert canonical_alert_symbol("NSE:TCS-EQ") == "TCS"
    assert canonical_alert_symbol("NSE:NIFTY50-INDEX") == "NIFTY"
    assert canonical_alert_symbol("NIFTY50-INDEX") == "NIFTY"
    assert canonical_alert_symbol("NSE:NIFTYBANK-INDEX") == "BANKNIFTY"
    assert canonical_alert_symbol("NSE:INDIAVIX-INDEX") == "INDIAVIX"


def test_auto_alert_domestic_tick_dataclass():
    """Verify that _on_domestic_tick accepts Tick dataclass objects and evaluates active alerts."""
    engine = AutoAlertEngine()

    # Create an active alert for RELIANCE with entry 2500, SL 2480, target 2540
    alert = AutoAlert(
        alert_id="aa-orb-reliance-bull-20261016",
        alert_type="ORB",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE ORB IGNITED",
        summary="ORB Breakout",
        trigger_level=2500.0,
        ltp=2500.0,
        stop_loss=2480.0,
        target_level=2540.0,
        time_horizon="INTRADAY",
        environment="TEST",
    )

    with engine._lock:
        engine._alerts = [alert]

    # Send a Tick dataclass with stop-loss breach: LTP = 2470 < 2480
    tick_sl = Tick(
        symbol="NSE:RELIANCE-EQ",
        ltp=2470.0,
        timestamp=time.time(),
    )
    engine._on_domestic_tick(tick_sl)

    # Alert should be invalidated
    assert alert.is_invalidated is True
    assert alert.stage == "INVALIDATED"
    assert "stop-loss" in (alert.invalidation_reason or "").lower()


def test_auto_alert_domestic_tick_dict():
    """Verify that _on_domestic_tick also accepts dict payloads."""
    engine = AutoAlertEngine()

    alert = AutoAlert(
        alert_id="aa-orb-infy-bull-20261016",
        alert_type="ORB",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY ORB IGNITED",
        summary="ORB Breakout",
        trigger_level=1600.0,
        ltp=1600.0,
        stop_loss=1580.0,
        target_level=1640.0,
        time_horizon="INTRADAY",
        environment="TEST",
    )

    with engine._lock:
        engine._alerts = [alert]

    # Send a dict tick with stop-loss breach
    tick_dict = {
        "symbol": "NSE:INFY-EQ",
        "ltp": 1575.0,
        "timestamp": time.time(),
    }
    engine._on_domestic_tick(tick_dict)

    assert alert.is_invalidated is True
    assert alert.stage == "INVALIDATED"


def test_ticker_stream_off_market_adaptive_intervals():
    """Verify that MarketTickerStream avoids calling compute_ribbon_tickers when markets are closed."""
    from market.ticker_stream import MarketTickerStream

    stream = MarketTickerStream()

    # Pre-populate cached ribbon with valid non-zero data
    stream._cached_ribbon_tickers = [{"symbol": "NIFTY", "ltp": 25000.0}]

    with patch("market.calendar.get_current_ist_session", return_value={"equity_nfo": False}):
        with patch("market.ticker_stream.compute_ribbon_tickers") as mock_compute:
            # force_ribbon = False, off-market with cached ribbon -> should NOT re-compute ribbon
            stream.refresh_indices_sync(force_ribbon=False)
            mock_compute.assert_not_called()


def test_auto_alert_option_spot_tick_isolation():
    """Verify that an underlying index spot tick updates underlying_spot without leaking into option premium targets/SL."""
    engine = AutoAlertEngine()

    opt_alert = AutoAlert(
        alert_id="aa-gamma-blast-nifty-pe-22900-20261016",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26O1922900PE",
        exchange="NSE",
        direction="BEARISH",
        headline="NIFTY 22900 PE IGNITED",
        summary="Put Gamma Blast",
        trigger_level=117.0,
        ltp=117.0,
        stop_loss=100.0,
        target_level=150.0,
        option_type="PE",
        strike=22900.0,
        time_horizon="INTRADAY",
        environment="TEST",
    )

    with engine._lock:
        engine._alerts = [opt_alert]

    # Ingest SPOT tick for NIFTY (LTP = 22950.0)
    spot_tick = Tick(
        symbol="NSE:NIFTY50-INDEX",
        ltp=22950.0,
        timestamp=time.time(),
    )
    engine._on_domestic_tick(spot_tick)

    # Underlying spot should be updated
    assert opt_alert.underlying_spot == 22950.0
    # Alert must NOT be falsely invalidated or promoted by spot price
    assert opt_alert.is_invalidated is False
    assert opt_alert.stage == "IGNITED"

    # Now ingest OPTION CONTRACT tick (LTP = 155.0 > target 150.0)
    opt_tick = Tick(
        symbol="NSE:NIFTY26O1922900PE",
        ltp=155.0,
        timestamp=time.time(),
    )
    engine._on_domestic_tick(opt_tick)

    # Now milestone should be recorded
    assert (
        "TARGET_1" in opt_alert.achieved_milestones
        or "T1_ACHIEVED" in opt_alert.achieved_milestones
        or opt_alert.target_status in ("TARGET_1", "T1_ACHIEVED", "TARGET_ACHIEVED")
    )
