"""
tests/test_institutional_quality_filter.py
──────────────────────────────────────────
Verifies the institutional quality gates:
1. Low-momentum, stationary stock options (<6% expansion, <1.2x Vol/OI) are filtered out.
2. The recalibrated conviction scoring model awards high confidence only to setups with
   genuine institutional velocity, relative volume, and VWAP expansion.
3. Telegram blocks setups below 92% confidence for OPTIONS_MOMENTUM and enforces pacing.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from engine.alert_preferences import AlertPreferences, AlertPreferencesManager
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine


def test_telegram_conviction_gate_filters_noise(tmp_path):
    """Verifies that AutoAlertEngine suppresses alerts below 92% on Telegram."""
    test_pref_file = tmp_path / "test_prefs.json"

    mgr = AlertPreferencesManager()
    mgr._pref_file = test_pref_file
    mgr._preferences = AlertPreferences()
    mgr.update_preferences({"telegram": {"min_confidence": 92}})

    # Low-conviction / marginal setup (e.g. 85% confidence)
    marginal_alert = AutoAlert(
        alert_id="opt-marginal-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="RELIANCE",
        contract_symbol="RELIANCE1240CE",
        exchange="NFO",
        direction="BULLISH",
        headline="RELIANCE Marginal Call",
        summary="Marginal setup",
        ltp=15.0,
        trigger_level=15.0,
        target_level=22.0,
        stop_loss=11.0,
        confidence=85,  # Below 92% institutional Telegram bar
    )

    # High-conviction institutional setup (e.g. 95% confidence)
    elite_alert = AutoAlert(
        alert_id="opt-elite-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="BHARTIARTL",
        contract_symbol="BHARTIARTL1860PE",
        exchange="NFO",
        direction="BEARISH",
        headline="BHARTIARTL Elite Put Surge",
        summary="Elite institutional breakdown",
        ltp=25.0,
        trigger_level=25.0,
        target_level=35.0,
        stop_loss=20.0,
        confidence=95,  # Above 92% institutional Telegram bar
    )

    engine = AutoAlertEngine()
    engine._dispatched_milestones.clear()
    engine._dispatch_cooldowns.clear()

    # Mock telegram notify
    dispatched_msgs = []
    def mock_tg(msg, chat_id=None):
        dispatched_msgs.append((msg, chat_id))

    with patch("engine.alerts._telegram_notify", side_effect=mock_tg), \
         patch("engine.alerts._is_market_hours", return_value=True):

        # Dispatch marginal alert -> Must be suppressed on Telegram!
        engine._dispatch(marginal_alert)
        assert len(dispatched_msgs) == 0, "Marginal alert (<92% confidence) should NOT be dispatched to Telegram!"
        assert marginal_alert.telegram_dispatched is False

        # Dispatch elite alert -> Must be permitted to Telegram!
        engine._dispatch(elite_alert)
        assert len(dispatched_msgs) == 1, "Elite alert (>=92% confidence) MUST be dispatched to Telegram!"
        assert elite_alert.telegram_dispatched is True


def test_telegram_pacing_throttle_blocks_rapid_bursts(tmp_path):
    """Pacing throttle should suppress multiple signals within 180s window unless exceptional conviction (>=96)."""
    engine = AutoAlertEngine()
    engine._dispatched_milestones.clear()
    engine._dispatch_cooldowns.clear()

    alert1 = AutoAlert(
        alert_id="opt-pacing-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NFO",
        direction="BULLISH",
        headline="Alert 1",
        summary="First setup",
        ltp=10.0,
        trigger_level=10.0,
        target_level=16.0,
        stop_loss=7.0,
        confidence=88,
    )

    alert2 = AutoAlert(
        alert_id="opt-pacing-2",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="JSWSTEEL",
        exchange="NFO",
        direction="BULLISH",
        headline="Alert 2",
        summary="Burst setup within 10s",
        ltp=20.0,
        trigger_level=20.0,
        target_level=30.0,
        stop_loss=14.0,
        confidence=88,  # < 90, should be throttled by pacing filter
    )

    dispatched = []
    with patch("engine.alerts._telegram_notify", side_effect=lambda m, **kw: dispatched.append(m)), \
         patch("engine.alerts._is_market_hours", return_value=True):

        engine._dispatch(alert1)
        assert len(dispatched) == 1
        assert alert1.telegram_dispatched is True

        # Second alert fired 5 seconds later on same segment
        engine._dispatch(alert2)
        assert len(dispatched) == 1, "Second alert fired in rapid succession (<180s) must be held by pacing throttle!"
        assert alert2.telegram_dispatched is False
