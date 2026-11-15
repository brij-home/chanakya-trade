"""
tests/test_intraday_to_swing_promotion.py
──────────────────────────────────────────
Unit tests for Intraday-to-Swing Promotion & Non-Directional EOD Preservation:
1. Profitable sector leaders (>= +1.5R) in LEADING RRG quadrants are promoted to SWING_SHORT at 15:10 IST,
   preserving multi-day runners instead of force-dumping at 15:15 IST.
2. Same-day expiry (0DTE) options are NOT promoted to swing (must square off at session end).
3. Non-directional theta-harvesting setups (DEFINED_RISK_NEUTRAL, IRON_CONDOR) are protected across sessions.
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_model import AutoAlert

IST = ZoneInfo("Asia/Kolkata")


def test_intraday_to_swing_promotion_at_1510_ist():
    """Verify that a qualified profitable intraday position is promoted to SWING_SHORT and survives EOD sweep."""
    engine = AutoAlertEngine()

    now_1510 = datetime(2026, 11, 14, 15, 12, tzinfo=IST)
    today_str = now_1510.strftime("%Y-%m-%d")

    # Profitable F&O stock leader with +2.0R gain and next-week expiry
    alert_winner = AutoAlert(
        alert_id="aa-options-powerindia-20261114",
        alert_type="OPTIONS_MOMENTUM",
        symbol="POWERINDIA",
        exchange="NFO",
        direction="BULLISH",
        stage="T1_ACHIEVED",
        headline="POWERINDIA Rally",
        summary="POWERINDIA option rally",
        time_horizon="INTRADAY",
        ltp=210.0,
        trigger_level=160.0,
        stop_loss=160.0,
        target_level=260.0,
        r_multiple=2.2,
        pnl_pct=31.2,
        expiry_date="2026-11-26",
        created_at=f"{today_str} 09:20:00 IST",
        triggered_at=f"{today_str} 09:20:00 IST",
        metrics={"dte": 12},
    )

    # Struggling trade with -0.5R loss
    alert_loser = AutoAlert(
        alert_id="aa-orb-losing-20261114",
        alert_type="ORB",
        symbol="LOSER",
        exchange="NSE",
        direction="BULLISH",
        stage="IGNITED",
        headline="LOSER breakdown",
        summary="LOSER setup",
        time_horizon="INTRADAY",
        ltp=95.0,
        trigger_level=100.0,
        stop_loss=90.0,
        target_level=120.0,
        r_multiple=-0.5,
        pnl_pct=-5.0,
        created_at=f"{today_str} 09:30:00 IST",
    )

    engine._alerts = [alert_winner, alert_loser]

    with (
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
    ):
        promoted = engine.evaluate_intraday_to_swing_promotions(now_dt=now_1510)

        assert len(promoted) == 1
        assert promoted[0].symbol == "POWERINDIA"
        assert alert_winner.time_horizon == "SWING_SHORT"
        assert alert_winner.setup_style == "SWING"
        assert any(
            a["event_type"] == "INTRADAY_PROMOTED_TO_SWING" for a in alert_winner.audit_trail
        )

        # Loser remains INTRADAY
        assert alert_loser.time_horizon == "INTRADAY"

    # Now simulate EOD sweep at 15:35 IST
    now_1535 = datetime(2026, 11, 14, 15, 35, tzinfo=IST)
    with (
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
        patch("engine.auto_alert_engine.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = now_1535
        closed = engine.sweep_intraday_eod_squareoffs()

        # Only the loser was squared off; the promoted swing position is preserved!
        assert len(closed) == 1
        assert closed[0].symbol == "LOSER"
        assert alert_winner.stage != "SESSION_CLOSE_EXIT"
        assert alert_winner.time_horizon == "SWING_SHORT"


def test_0dte_option_is_not_promoted_to_swing():
    """Verify that same-day expiry (0DTE) contracts cannot be promoted to multi-day swing."""
    engine = AutoAlertEngine()

    now_1510 = datetime(2026, 11, 14, 15, 12, tzinfo=IST)
    today_str = now_1510.strftime("%Y-%m-%d")

    alert_0dte = AutoAlert(
        alert_id="aa-gamma-nifty-20261114",
        alert_type="GAMMA_BLAST",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        stage="T1_ACHIEVED",
        headline="NIFTY 0DTE",
        summary="NIFTY setup",
        time_horizon="INTRADAY",
        ltp=150.0,
        trigger_level=100.0,
        stop_loss=100.0,
        target_level=200.0,
        r_multiple=2.5,
        pnl_pct=50.0,
        expiry_date=today_str,
        created_at=f"{today_str} 10:00:00 IST",
        metrics={"dte": 0, "is_0dte": True},
    )

    engine._alerts = [alert_0dte]

    with (
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
    ):
        promoted = engine.evaluate_intraday_to_swing_promotions(now_dt=now_1510)
        # 0DTE cannot be held overnight
        assert len(promoted) == 0
        assert alert_0dte.time_horizon == "INTRADAY"


def test_eod_sweep_exempts_non_directional_spreads():
    """Verify that defined-risk neutral spreads (e.g. Iron Condor) are never closed by intraday EOD sweep."""
    engine = AutoAlertEngine()

    alert_condor = AutoAlert(
        alert_id="aa-condor-banknifty-20261114",
        alert_type="DEFINED_RISK_NEUTRAL",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="NEUTRAL",
        stage="ACTIONABLE",
        headline="BANKNIFTY Condor",
        summary="BANKNIFTY neutral condor",
        time_horizon="SWING_SHORT",  # Multi-day neutral harvest
        ltp=52000.0,
        trigger_level=52000.0,
        stop_loss=51500.0,
        target_level=52500.0,
        metrics={"strategy": "IRON_CONDOR"},
        actionable_plan={"strategy_type": "IRON_CONDOR", "action": "EXECUTE_IRON_CONDOR"},
    )

    engine._alerts = [alert_condor]

    now_1535 = datetime(2026, 11, 14, 15, 35, tzinfo=IST)
    with (
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
        patch("engine.auto_alert_engine.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = now_1535
        closed = engine.sweep_intraday_eod_squareoffs()

        # Non-directional spread is NOT closed
        assert len(closed) == 0
        assert alert_condor.stage == "ACTIONABLE"


def test_bearish_intraday_to_swing_promotion_in_lagging_sector():
    """Verify that a bearish breakdown position (Put option / short) in a LAGGING sector is promoted to SWING_SHORT."""
    engine = AutoAlertEngine()

    now_1510 = datetime(2026, 11, 14, 15, 12, tzinfo=IST)
    today_str = now_1510.strftime("%Y-%m-%d")

    # Profitable bearish Put option on a stock breakdown (e.g. TATASTEEL breakdown) with +2.4R gain
    alert_bear_winner = AutoAlert(
        alert_id="aa-options-tatasteel-pe-20261114",
        alert_type="OPTIONS_MOMENTUM",
        symbol="TATASTEEL",
        exchange="NFO",
        direction="BEARISH",
        stage="T1_ACHIEVED",
        headline="TATASTEEL Breakdown PE",
        summary="TATASTEEL breakdown put momentum",
        time_horizon="INTRADAY",
        ltp=18.5,
        trigger_level=12.0,
        stop_loss=12.0,
        target_level=24.0,
        r_multiple=2.4,
        pnl_pct=54.2,
        expiry_date="2026-11-26",
        created_at=f"{today_str} 10:15:00 IST",
        triggered_at=f"{today_str} 10:15:00 IST",
        metrics={"dte": 12},
    )

    # Struggling bearish trade with -0.6R
    alert_bear_loser = AutoAlert(
        alert_id="aa-orb-bear-loser-20261114",
        alert_type="ORB",
        symbol="BEAR_LOSER",
        exchange="NSE",
        direction="BEARISH",
        stage="IGNITED",
        headline="BEAR_LOSER stalled",
        summary="BEAR_LOSER setup",
        time_horizon="INTRADAY",
        ltp=205.0,
        trigger_level=200.0,
        stop_loss=210.0,
        target_level=180.0,
        r_multiple=-0.6,
        pnl_pct=-2.5,
        created_at=f"{today_str} 11:00:00 IST",
    )

    engine._alerts = [alert_bear_winner, alert_bear_loser]

    mock_directional = {
        "BULLISH": {"POWERINDIA", "ABB"},
        "BEARISH": {"TATASTEEL", "INFY"},
    }

    with (
        patch(
            "analysis.sector_rotation.get_directional_sector_constituents",
            return_value=mock_directional,
        ),
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
    ):
        promoted = engine.evaluate_intraday_to_swing_promotions(now_dt=now_1510)

        assert len(promoted) == 1
        assert promoted[0].symbol == "TATASTEEL"
        assert alert_bear_winner.time_horizon == "SWING_SHORT"
        assert alert_bear_winner.setup_style == "SWING"

        # Verify bidirectional audit trail
        audit_events = [
            a
            for a in alert_bear_winner.audit_trail
            if a["event_type"] == "INTRADAY_PROMOTED_TO_SWING"
        ]
        assert len(audit_events) == 1
        assert "bearish breakdown laggard" in audit_events[0]["message"]
        assert audit_events[0]["details"]["direction"] == "BEARISH"

        # Loser remains INTRADAY
        assert alert_bear_loser.time_horizon == "INTRADAY"

    # Now simulate EOD sweep at 15:35 IST
    now_1535 = datetime(2026, 11, 14, 15, 35, tzinfo=IST)
    with (
        patch.object(engine, "_save", return_value=None),
        patch.object(engine, "_dispatch", return_value=None),
        patch("engine.auto_alert_engine.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = now_1535
        closed = engine.sweep_intraday_eod_squareoffs()

        # Bearish loser is squared off, but profitable bearish breakdown is preserved as swing!
        assert len(closed) == 1
        assert closed[0].symbol == "BEAR_LOSER"
        assert alert_bear_winner.stage != "SESSION_CLOSE_EXIT"
        assert alert_bear_winner.time_horizon == "SWING_SHORT"
