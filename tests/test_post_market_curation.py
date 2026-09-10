"""
tests/test_post_market_curation.py
──────────────────────────────────
Unit tests validating Option B: Curated Post-Market Watchlist Discipline.
Ensures:
  1. Intraday fast-derivatives / scalps (Gamma Blasts, Options Momentum, Intraday Sparks, Circuits)
     are silenced from Telegram outside active market hours.
  2. Sub-90% confidence swing alerts are silenced from Telegram outside active market hours.
  3. High-conviction swing alerts (>= 90%) like Precursor Radar and Asymmetric Opportunities
     dispatch with [POST-MARKET EOD WATCHLIST] header and clear gameplan disclaimers.
  4. Active market sessions (e.g. MCX Commodities at 19:30 IST) dispatch normally.
  5. Position lifecycle milestones (Invalidations, Targets, Trailing stops) remain permitted.
  6. scan_post_market_digest() executes only swing detectors, avoiding closed options chains.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from bot.alert_templates import render_auto_alert, render_precursor_alert, render_asymmetric_alert

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def clean_engine(tmp_path, monkeypatch):
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    # Clear test env vars so unit tests can specifically evaluate _dispatch Telegram logic
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    engine = AutoAlertEngine(max_buffer=50)
    engine._alerts = []
    engine._cooldowns = {}
    engine._dispatched_milestones = set()
    engine._dispatch_cooldowns = {}
    return engine


def test_post_market_intraday_derivative_silenced_from_telegram(clean_engine, monkeypatch):
    """Gamma Blast or Options Momentum outside market hours must not buzz Telegram."""
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": False)

    alert = AutoAlert(
        alert_id="opt-gamma-dixon-13500",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="DIXON",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ PUT GAMMA BLAST IGNITED: DIXON 13500 PE",
        summary="Put writers shedding OI.",
        ltp=468.45,
        trigger_level=468.45,
        target_level=593.8,
        stop_loss=396.8,
        confidence=96,
        is_live=True,
        environment="LIVE",
    )

    with patch("engine.alerts._telegram_notify") as mock_tg:
        clean_engine._dispatch(alert)
        mock_tg.assert_not_called()


def test_post_market_low_confidence_swing_silenced_from_telegram(clean_engine, monkeypatch):
    """Precursor radar with confidence < 90% outside market hours must not buzz Telegram."""
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": False)

    alert = AutoAlert(
        alert_id="prec-infy-82conf",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ PRECURSOR RADAR: INFY Coiling",
        summary="VCP contraction.",
        ltp=1850.0,
        trigger_level=1855.0,
        target_level=1920.0,
        stop_loss=1820.0,
        confidence=82,  # < 90% threshold
        is_live=True,
        environment="LIVE",
    )

    with patch("engine.alerts._telegram_notify") as mock_tg:
        clean_engine._dispatch(alert)
        mock_tg.assert_not_called()


def test_post_market_high_conviction_swing_dispatches_to_telegram(clean_engine, monkeypatch):
    """Precursor radar with confidence >= 90% outside market hours dispatches with watchlist header."""
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": False)

    alert = AutoAlert(
        alert_id="prec-trent-92conf",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="🔥 PRECURSOR RADAR: TRENT Stage 2 Breakout Ready",
        summary="Tight VCP 3T contraction with 2.8x institutional volume dry-up.",
        ltp=7150.0,
        trigger_level=7150.0,
        target_level=7550.0,
        stop_loss=6980.0,
        confidence=92,  # >= 90% threshold
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "entry_range": "₹7,140.0 – ₹7,160.0",
            "stop_loss": 6980.0,
            "target_1": 7550.0,
            "target_2": 7800.0,
            "risk_reward": "1:2.4",
            "when_to_wait": "DO NOT CHASE above ₹7,180.0",
        },
    )

    with patch("engine.alerts._telegram_notify") as mock_tg:
        clean_engine._dispatch(alert)
        mock_tg.assert_called_once()
        dispatched_msg = mock_tg.call_args[0][0]
        assert "POST-MARKET EOD WATCHLIST" in dispatched_msg
        assert "Market is closed. Setup calibrated for tomorrow's opening gameplan" in dispatched_msg


def test_post_market_asymmetric_opportunity_dispatches_high_conviction(clean_engine, monkeypatch):
    """Asymmetric Opportunity (1:3+ R:R) with score >= 90 dispatches as EOD watchlist."""
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": False)

    alert = AutoAlert(
        alert_id="asym-reliance-94conf",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="READY",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="🎯 ASYMMETRIC OPPORTUNITY: RELIANCE 1:3.4 R:R",
        summary="Weekly Demand Order Block retest.",
        ltp=2950.0,
        trigger_level=2950.0,
        target_level=3180.0,
        stop_loss=2880.0,
        confidence=94,  # >= 90%
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "conviction_score": 94,
            "entry_range": "₹2,940.0 – ₹2,960.0",
            "stop_loss": 2880.0,
            "target_1": 3100.0,
            "target_2": 3180.0,
            "risk_reward": "3.4",
        },
    )

    with patch("engine.alerts._telegram_notify") as mock_tg:
        clean_engine._dispatch(alert)
        mock_tg.assert_called_once()
        dispatched_msg = mock_tg.call_args[0][0]
        assert "POST-MARKET EOD WATCHLIST" in dispatched_msg
        assert "Market is closed" in dispatched_msg


def test_live_mcx_commodity_dispatches_normally_in_evening(clean_engine, monkeypatch):
    """MCX Commodity alerts during evening session (in_market=True for MCX) must dispatch normally."""
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="MCX": True)

    alert = AutoAlert(
        alert_id="comm-gold-1930",
        alert_type="COMMODITY_MOMENTUM",
        stage="IGNITED",
        symbol="GOLD",
        exchange="MCX",
        direction="BULLISH",
        headline="🛢️ [REAL/LIVE] MCX MOMENTUM: GOLD +0.8% Reclaiming VWAP",
        summary="US Session open momentum.",
        ltp=73500.0,
        trigger_level=73500.0,
        target_level=74200.0,
        stop_loss=73150.0,
        confidence=86,
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "action": "BUY_FUTURES",
            "contract": "MCX:GOLD",
            "entry_range": "₹73,450 – ₹73,550",
            "target": "₹74,200",
            "stop_loss": "₹73,150",
            "risk_reward": "1:2.0",
            "lot_size": 100,
            "profit_rule": "Scale 50% at T1",
        },
    )

    with patch("engine.alerts._telegram_notify") as mock_tg:
        clean_engine._dispatch(alert)
        mock_tg.assert_called_once()
        dispatched_msg = mock_tg.call_args[0][0]
        assert "[REAL / LIVE MCX COMMODITY SIGNAL]" in dispatched_msg


def test_settlement_invalidation_permitted_post_market(clean_engine, monkeypatch):
    """Position invalidation from EOD settlement auction price must dispatch to Telegram."""
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange="NSE": False)

    alert = AutoAlert(
        alert_id="inv-eod-sbin",
        alert_type="SQUEEZE_BREAKOUT",
        stage="INVALIDATED",
        symbol="SBIN",
        exchange="NSE",
        direction="BULLISH",
        headline="⚠️ VIEW INVALIDATED: SBIN",
        summary="Closing price breached stop-loss floor ₹810.0.",
        ltp=808.5,
        trigger_level=810.0,
        target_level=860.0,
        stop_loss=810.0,
        confidence=95,
        is_invalidated=True,
        invalidation_reason="Settlement price ₹808.5 breached stop-loss floor ₹810.0.",
        is_live=True,
        environment="LIVE",
    )

    with patch("engine.alerts._telegram_notify") as mock_tg:
        clean_engine._dispatch(alert)
        mock_tg.assert_called_once()
        dispatched_msg = mock_tg.call_args[0][0]
        assert "VIEW INVALIDATED" in dispatched_msg
        assert "SBIN" in dispatched_msg


def test_scan_post_market_digest_runs_only_swing_detectors(clean_engine):
    """scan_post_market_digest() runs precursors, asymmetric opportunities, and squeezes; skips options & circuits."""
    with patch.object(clean_engine, "scan_precursor_radars", return_value=[]) as m_prec:
        with patch.object(clean_engine, "scan_asymmetric_opportunities", return_value=[]) as m_asym:
            with patch.object(clean_engine, "scan_squeeze_breakouts", return_value=[]) as m_sqz:
                with patch.object(clean_engine, "scan_gamma_blasts", return_value=[]) as m_gamma:
                    with patch.object(clean_engine, "scan_circuits", return_value=[]) as m_circ:
                        clean_engine.scan_post_market_digest()
                        m_prec.assert_called_once()
                        m_asym.assert_called_once()
                        m_sqz.assert_called_once()
                        m_gamma.assert_not_called()
                        m_circ.assert_not_called()
