"""
tests/test_direction_aware_reversal_pacing.py
─────────────────────────────────────────────
Deterministic unit tests for Direction-Aware Structural Reversal Bypass
in AutoAlertEngine._eval_telegram_apex_gate.
"""

from __future__ import annotations

import time

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def _make_index_alert(
    alert_id: str,
    symbol: str = "NIFTY",
    direction: str = "BULLISH",
    confidence: int = 90,
) -> AutoAlert:
    is_bear = direction in ("BEARISH", "SHORT", "SELL")
    stop_loss = 23100.0 if is_bear else 22900.0
    target_level = 22700.0 if is_bear else 23300.0
    vwap = 23050.0 if is_bear else 22950.0
    return AutoAlert(
        alert_id=alert_id,
        alert_type="INDEX_MOMENTUM",
        stage="IGNITED",
        symbol=symbol,
        exchange="NSE",
        direction=direction,
        headline=f"🚀 {symbol} Index Setup",
        summary="Test index summary",
        ltp=23000.0,
        trigger_level=23000.0,
        stop_loss=stop_loss,
        target_level=target_level,
        segment="FNO_INDEX",
        confidence=confidence,
        is_live=True,
        environment="LIVE",
        metrics={
            "spot": 23000.0,
            "vwap": vwap,
            "is_institutional_thrust": True,
            "signals": ["VWAP_BREAKDOWN", "DAY_LOW_BREAKDOWN"]
            if is_bear
            else ["VWAP_BREAKOUT", "DAY_HIGH_BREAKOUT"],
            "fii_aligned": True,
            "vwap_trend": True,
        },
        actionable_plan={
            "risk_reward": "1:3.0",
        },
    )


def test_direction_aware_reversal_bypass_granted(tmp_path, monkeypatch):
    """
    When the hourly index pacing limit is reached (e.g. 4 BEARISH dispatches with limit=4),
    a new high-conviction BULLISH alert (confidence >= 85) must be granted dispatch.
    """
    monkeypatch.setenv("TELEGRAM_MAX_INDEX_ALERTS_PER_DIR_HOUR", "4")
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    now_ts = time.time()

    # Simulate 4 BEARISH alerts already sent in the past 30 minutes
    engine._hourly_telegram_dispatches["INDEX"] = [
        now_ts - 1800,
        now_ts - 1200,
        now_ts - 600,
        now_ts - 300,
    ]
    engine._hourly_index_directional = [
        (now_ts - 1800, "BEARISH"),
        (now_ts - 1200, "BEARISH"),
        (now_ts - 600, "BEARISH"),
        (now_ts - 300, "BEARISH"),
    ]

    # Another BEARISH alert should be blocked by hourly pacing
    bearish_alert = _make_index_alert("aa-idx-bear-1", direction="BEARISH", confidence=90)
    allowed, reason = engine._eval_telegram_apex_gate(bearish_alert, in_market=True, now_ts=now_ts)
    assert not allowed
    assert "hourly pacing limit reached" in reason

    # A high-conviction BULLISH alert (reversal) MUST be granted dispatch
    bullish_alert = _make_index_alert("aa-idx-bull-rev", direction="BULLISH", confidence=90)
    allowed_rev, reason_rev = engine._eval_telegram_apex_gate(
        bullish_alert, in_market=True, now_ts=now_ts
    )
    assert allowed_rev
    assert reason_rev == "PASSED_APEX_GATE"


def test_reversal_bypass_not_granted_for_low_confidence(tmp_path, monkeypatch):
    """Low-confidence alert must be rejected by Telegram confidence floor."""
    monkeypatch.setenv("TELEGRAM_MAX_INDEX_ALERTS_PER_DIR_HOUR", "4")
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    now_ts = time.time()
    engine._hourly_telegram_dispatches["INDEX"] = [now_ts - 600] * 4
    engine._hourly_index_directional = [(now_ts - 600, "BEARISH")] * 4

    # Low-confidence BULLISH alert (70% < 85%)
    weak_alert = _make_index_alert("aa-idx-weak-rev", direction="BULLISH", confidence=70)
    allowed, reason = engine._eval_telegram_apex_gate(weak_alert, in_market=True, now_ts=now_ts)
    assert not allowed
    assert ("below" in reason) or ("hourly pacing limit reached" in reason)


def test_reversal_bypass_capped_at_two(tmp_path, monkeypatch):
    """Directional pacing ensures dispatches in the new direction cannot exceed directional limit."""
    monkeypatch.setenv("TELEGRAM_MAX_INDEX_ALERTS_PER_DIR_HOUR", "2")
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    now_ts = time.time()
    # 4 BEARISH + already 2 BULLISH reversals sent
    engine._hourly_telegram_dispatches["INDEX"] = [now_ts - 600] * 6
    engine._hourly_index_directional = [
        (now_ts - 600, "BEARISH"),
        (now_ts - 500, "BEARISH"),
        (now_ts - 400, "BEARISH"),
        (now_ts - 300, "BEARISH"),
        (now_ts - 200, "BULLISH"),
        (now_ts - 100, "BULLISH"),
    ]

    # 3rd BULLISH reversal alert must be paced (BULLISH count 2 >= limit 2)
    third_rev = _make_index_alert("aa-idx-third-rev", direction="BULLISH", confidence=92)
    allowed, reason = engine._eval_telegram_apex_gate(third_rev, in_market=True, now_ts=now_ts)
    assert not allowed
    assert "hourly pacing limit reached" in reason
