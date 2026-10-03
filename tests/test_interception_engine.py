"""
tests/test_interception_engine.py
──────────────────────────────────
Unit tests verifying the 3-stage predatory interception pipeline:
STALK (Radar Tracking) -> PRIMED (High-Priority Micro-Proximity) -> IGNITED (Sniper Execution).
"""

from __future__ import annotations

from datetime import datetime, date
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

import pytest

from engine.alert_identity import generate_alert_id
from engine.alert_model import (
    AutoAlert,
    STAGE_STALK,
    STAGE_PRIMED,
    STAGE_IGNITED,
    STAGE_EARLY_WARNING,
    STAGE_INVALIDATED,
)
from engine.auto_alert_engine import AutoAlertEngine

IST = ZoneInfo("Asia/Kolkata")


def test_auto_alert_interception_stage_properties():
    """Verify AutoAlert stage predicates and promote_stage method."""
    alert = AutoAlert(
        alert_id="aa-test-interception-20261003",
        alert_type="SQUEEZE_BREAKOUT",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        stage=STAGE_STALK,
        trigger_level=2500.0,
        ltp=2485.0,
        stop_loss=2460.0,
        target_level=2580.0,
        headline="Coiling Squeeze",
        summary="Test summary",
        environment="TEST",
    )

    assert alert.is_stalk is True
    assert alert.is_primed is False
    assert alert.is_ignited is False
    assert alert.is_active is True

    # Promote STALK -> PRIMED
    promoted = alert.promote_stage("PRIMED", reason="Within 0.35% proximity", ltp=2495.0)
    assert promoted is True
    assert alert.stage == STAGE_PRIMED
    assert alert.is_stalk is False
    assert alert.is_primed is True
    assert alert.is_ignited is False
    assert alert.ltp == 2495.0

    # Promote PRIMED -> IGNITED
    promoted_ignite = alert.promote_stage("IGNITED", reason="Trigger 2500 crossed", ltp=2502.0)
    assert promoted_ignite is True
    assert alert.stage == STAGE_IGNITED
    assert alert.is_primed is False
    assert alert.is_ignited is True
    assert alert.triggered_at is not None

    # Idempotent promotion returns False
    assert alert.promote_stage("IGNITED", reason="Duplicate") is False

    # Audit trail verification
    events = [e["event_type"] for e in alert.audit_trail]
    assert "STAGE_PROMOTION" in events


def test_proximity_promotion_stalk_to_primed():
    """
    Verify that check_and_ignite_early_warnings automatically promotes an alert
    from STALK to PRIMED when price enters within ±0.35% of trigger level.
    """
    engine = AutoAlertEngine()
    engine._alerts = []

    d = date(2026, 10, 3)
    aid = generate_alert_id("NSE:TCS", "SQUEEZE_BREAKOUT", session_date=d)

    alert = AutoAlert(
        alert_id=aid,
        alert_type="SQUEEZE_BREAKOUT",
        symbol="NSE:TCS",
        exchange="NSE",
        direction="BULLISH",
        stage=STAGE_STALK,
        trigger_level=3500.0,
        ltp=3470.0,
        stop_loss=3440.0,
        target_level=3620.0,
        headline="TCS Pre-Breakout Squeeze",
        summary="Coiling at pivot",
        environment="LIVE",
        is_live=True,
    )
    engine._alerts.append(alert)

    # 1. Price at 3470.0 (dist = 30 pts = 0.86% > 0.35%): stays STALK
    with patch.object(engine, "_batch_refresh_quotes", return_value={"NSE:TCS": 3470.0}):
        ignited = engine.check_and_ignite_early_warnings()
        assert len(ignited) == 0
        assert alert.stage == STAGE_STALK

    # 2. Price moves to 3492.0 (dist = 8 pts = 0.23% <= 0.35%): promoted to PRIMED
    with patch.object(engine, "_batch_refresh_quotes", return_value={"NSE:TCS": 3492.0}):
        ignited = engine.check_and_ignite_early_warnings()
        assert len(ignited) == 0  # Not yet ignited
        assert alert.stage == STAGE_PRIMED
        assert alert.is_primed is True
        assert alert.ltp == 3492.0

    # 3. Price crosses 3501.0: promoted to IGNITED
    with patch.object(engine, "_batch_refresh_quotes", return_value={"NSE:TCS": 3501.0}):
        with patch.object(engine, "_dispatch") as mock_dispatch:
            ignited = engine.check_and_ignite_early_warnings()
            assert len(ignited) == 1
            assert alert.stage == STAGE_IGNITED
            assert alert.is_ignited is True
            assert alert.ltp == 3501.0
            mock_dispatch.assert_called_once()


def test_calibrate_off_number_stop():
    """Verify off-number stop loss calibration buffers stops outside round number hunting pools."""
    from engine.position_sizer import calibrate_off_number_stop

    # Bullish (Long) trade with stop right on 2500.0 (major round level)
    # Stop should be buffered downward below 2500.0
    calibrated_bull = calibrate_off_number_stop(
        direction="BULLISH",
        raw_stop=2500.0,
        atr=25.0,
    )
    assert calibrated_bull < 2500.0
    assert calibrated_bull <= 2496.25  # Buffers by at least 0.15*ATR = 3.75 pts

    # Bearish (Short) trade with stop right on 2500.0
    # Stop should be buffered upward above 2500.0
    calibrated_bear = calibrate_off_number_stop(
        direction="BEARISH",
        raw_stop=2500.0,
        atr=25.0,
    )
    assert calibrated_bear > 2500.0
    assert calibrated_bear >= 2503.75

    # Non-round stop (e.g. 2487.35) remains unaffected (just rounded to tick)
    calibrated_clean = calibrate_off_number_stop(
        direction="BULLISH",
        raw_stop=2487.35,
        atr=25.0,
    )
    assert calibrated_clean == 2487.35

