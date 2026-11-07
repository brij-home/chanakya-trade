"""
tests/test_pullback_volume_calibration.py
─────────────────────────────────────────
Regression and invariant tests for the Archetype-Aware Volume Calibration:
Distinguishing Breakout Momentum Expansion (High RVOL required) from
Pullback / Retest Absorption (Volume Contraction / Dry-Up required).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert, is_pullback_or_absorption_setup
from engine.session_runway import evaluate_session_runway
from engine.quality_gate import evaluate_institutional_quality_gate
from engine.alert_scrutiny import alert_scrutiny_auditor

IST = ZoneInfo("Asia/Kolkata")


def _make_dummy_alert(
    alert_type: str = "TREND_DAY_PULLBACK",
    rvol: float = 1.0,
    confidence: int = 85,
    entry_type: str = "LIMIT_ON_PULLBACK",
    created_at: str = "2026-11-02 12:00:00 IST",
    metrics_extra: dict | None = None,
    stop_loss: float = 3440.0,
    target_level: float = 3620.0,
) -> AutoAlert:
    metrics = {
        "rvol": rvol,
        "atr_14": 40.0,
        "is_pullback": True if "PULLBACK" in alert_type or "RETEST" in alert_type else False,
    }
    if metrics_extra:
        metrics.update(metrics_extra)

    return AutoAlert(
        alert_id=f"aa-{alert_type.lower()[:10]}-tcs-20261102",
        alert_type=alert_type,
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="Test Headline",
        summary="Test Summary",
        ltp=3500.0,
        trigger_level=3500.0,
        stop_loss=stop_loss,
        target_level=target_level,
        confidence=confidence,
        time_horizon="INTRADAY",
        entry_type=entry_type,
        actionable_plan={
            "action": "BUY",
            "entry_type": entry_type,
            "invalidation_stop": stop_loss,
            "target_1": target_level,
        },
        metrics=metrics,
        created_at=created_at,
        is_live=True,
        environment="LIVE",
    )


class TestArchetypeClassification:
    """Verifies that setups are correctly classified into breakout vs pullback/absorption."""

    def test_pullback_setup_classification_strings(self):
        assert is_pullback_or_absorption_setup("TREND_DAY_PULLBACK") is True
        assert is_pullback_or_absorption_setup("SMC_OB_RETEST") is True
        assert is_pullback_or_absorption_setup("PRE_INFLECTION_DRYUP") is True
        assert is_pullback_or_absorption_setup("TURTLE_SOUP") is True
        assert is_pullback_or_absorption_setup("TURTLE_SOUP_SWEEP") is True
        assert is_pullback_or_absorption_setup("VWAP_BOUNCE") is True
        assert is_pullback_or_absorption_setup("PATTERN_COILING") is True

    def test_breakout_setup_classification_strings(self):
        assert is_pullback_or_absorption_setup("ORB_BREAKOUT") is False
        assert is_pullback_or_absorption_setup("OPENING_DRIVE") is False
        assert is_pullback_or_absorption_setup("SQUEEZE_BREAKOUT") is False
        assert is_pullback_or_absorption_setup("AFTERNOON_THRUST") is False
        assert is_pullback_or_absorption_setup("GAMMA_BLAST") is False

    def test_alert_object_property(self):
        pb_alert = _make_dummy_alert(alert_type="TREND_DAY_PULLBACK")
        assert pb_alert.is_pullback_or_absorption is True

        bo_alert = _make_dummy_alert(alert_type="ORB_BREAKOUT", entry_type="BREAKOUT_STOP")
        assert bo_alert.is_pullback_or_absorption is False


class TestSessionRunwayExemption:
    """Verifies that pullbacks are exempted from high-RVOL breakout runway blocks."""

    def test_pullback_permitted_in_midday_compression(self, monkeypatch):
        monkeypatch.setenv("FORCE_RUNWAY_CHECK", "1")
        # 12:00 IST is MIDDAY_COMPRESSION
        eval_time = datetime(2026, 11, 2, 12, 0, 0, tzinfo=IST)
        res = evaluate_session_runway(
            "TCS",
            alert_type="TREND_DAY_PULLBACK",
            time_horizon="INTRADAY",
            rvol=0.95,
            now_dt=eval_time,
        )
        assert res.is_allowed is True, f"Expected allowed, got: {res.veto_reason}"

    def test_breakout_vetoed_in_midday_compression_with_low_rvol(self, monkeypatch):
        monkeypatch.setenv("FORCE_RUNWAY_CHECK", "1")
        eval_time = datetime(2026, 11, 2, 12, 0, 0, tzinfo=IST)
        res = evaluate_session_runway(
            "TCS",
            alert_type="ORB_BREAKOUT",
            time_horizon="INTRADAY",
            rvol=0.95,
            now_dt=eval_time,
        )
        assert res.is_allowed is False
        assert "Midday Compression Lull" in (res.veto_reason or "")


class TestScrutinyMiddayGate:
    """Verifies alert scrutiny behavior during midday lull (11:30 - 13:15 IST)."""

    def test_breakout_vetoed_in_midday_lull(self):
        bo_alert = _make_dummy_alert(
            alert_type="SQUEEZE_BREAKOUT",
            rvol=1.2,
            entry_type="BREAKOUT_STOP",
            created_at="2026-11-02 12:15:00 IST",
        )
        passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(bo_alert)
        assert passed is False
        assert "Midday False Breakout Trap" in reason

    def test_pullback_allowed_in_midday_lull_with_quiet_volume(self):
        pb_alert = _make_dummy_alert(
            alert_type="SQUEEZE_BREAKOUT",
            rvol=1.05,
            entry_type="LIMIT_ON_PULLBACK",
            created_at="2026-11-02 12:15:00 IST",
            metrics_extra={
                "pullback_vol_ratio": 0.85,
                "is_volume_dryup": True,
                "is_pullback": True,
            },
        )
        passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(pb_alert)
        # Should NOT fail with Midday False Breakout Trap
        assert "Midday False Breakout Trap" not in reason

    def test_pullback_vetoed_if_heavy_dumping_volume(self):
        dump_alert = _make_dummy_alert(
            alert_type="SQUEEZE_BREAKOUT",
            rvol=2.45,  # heavy selling into support!
            entry_type="LIMIT_ON_PULLBACK",
            created_at="2026-11-02 12:15:00 IST",
            metrics_extra={"is_pullback": True},
        )
        passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(dump_alert)
        assert passed is False
        assert "Midday Distribution Hazard" in reason


class TestQualityGateCalibration:
    """Verifies that Quality Gate recognizes controlled retest absorption vs breakout volume."""

    def test_quality_gate_recognizes_retest_absorption(self):
        pb_alert = _make_dummy_alert(
            alert_type="TREND_DAY_PULLBACK",
            rvol=0.90,
            confidence=85,
            metrics_extra={"is_volume_dryup": True, "pullback_vol_ratio": 0.70},
        )
        verdict = evaluate_institutional_quality_gate(pb_alert)
        notes_str = " ".join(verdict.coaching_notes)
        assert "Controlled Retest Absorption" in notes_str
        assert "Low Breakout RVOL" not in notes_str

    def test_quality_gate_flags_low_breakout_rvol(self):
        bo_alert = _make_dummy_alert(
            alert_type="ORB_BREAKOUT",
            rvol=0.90,
            confidence=85,
            entry_type="BREAKOUT_STOP",
            metrics_extra={"is_pullback": False},
        )
        verdict = evaluate_institutional_quality_gate(bo_alert)
        notes_str = " ".join(verdict.coaching_notes)
        assert "Low Breakout RVOL" in notes_str


class TestAutoAlertEngineAfternoonGate:
    """Verifies that afternoon gate allows quiet pullbacks and rejects heavy dumps."""

    def test_afternoon_pullback_gate_logic(self, monkeypatch):
        monkeypatch.setenv("ENFORCE_AFTERNOON_STOCK_GATE", "1")
        from engine.auto_alert_engine import AutoAlertEngine

        engine = AutoAlertEngine()
        test_ts = datetime(2026, 11, 2, 13, 30, tzinfo=IST).timestamp()

        # Afternoon quiet pullback at 13:30 IST
        pb_alert = _make_dummy_alert(
            alert_type="TREND_DAY_PULLBACK",
            rvol=1.1,
            confidence=90,
            created_at="2026-11-02 13:30:00 IST",
            metrics_extra={"pullback_vol_ratio": 0.80, "is_volume_dryup": True},
        )
        # Pass through Telegram gate evaluator
        allowed, reason = engine._eval_telegram_apex_gate(pb_alert, now_ts=test_ts)
        # Should NOT fail with "Afternoon stock setup requires RVOL >= 2.5x"
        assert "requires RVOL >= 2.5x" not in reason

        # Afternoon pullback with heavy dumping (RVOL >= 2.5x)
        dump_alert = _make_dummy_alert(
            alert_type="TREND_DAY_PULLBACK",
            rvol=2.6,
            confidence=90,
            created_at="2026-11-02 13:30:00 IST",
        )
        allowed_dump, reason_dump = engine._eval_telegram_apex_gate(dump_alert, now_ts=test_ts)
        assert allowed_dump is False
        assert "Heavy distribution dumping" in reason_dump
