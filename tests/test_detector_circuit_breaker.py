"""
tests/test_detector_circuit_breaker.py
───────────────────────────────────────
Unit tests for DetectorCircuitBreaker.
Verifies expectancy calculation, Kelly fraction, degradation state transitions, and halts.
"""

from __future__ import annotations

import pytest

from engine.detector_circuit_breaker import DetectorCircuitBreaker


@pytest.fixture
def temp_breaker(tmp_path):
    """Provides isolated circuit breaker with temp file."""
    ledger_file = tmp_path / "test_detector_perf.json"
    return DetectorCircuitBreaker(ledger_file=ledger_file, rolling_window=10, min_samples=4)


def test_initial_fresh_detector(temp_breaker):
    """Fresh detector with zero samples defaults to NORMAL status."""
    metrics = temp_breaker.get_metrics("GAMMA_BLAST")
    assert metrics.status == "NORMAL"
    assert metrics.confidence_multiplier == 1.0
    allowed, mult, msg = temp_breaker.evaluate_alert_allowed("GAMMA_BLAST")
    assert allowed is True
    assert mult == 1.0


def test_healthy_winning_streak(temp_breaker):
    """Consistent winners elevate detector to HEALTHY with conviction bonus."""
    for i in range(5):
        temp_breaker.record_outcome(
            alert_id=f"alert-win-{i}",
            symbol="NIFTY",
            alert_type="GAMMA_BLAST",
            outcome="WIN",
            realized_r=2.5,
        )

    metrics = temp_breaker.get_metrics("GAMMA_BLAST")
    assert metrics.status == "HEALTHY"
    assert metrics.win_rate == 1.0
    assert metrics.expectancy > 0.50
    assert metrics.confidence_multiplier == 1.05

    allowed, mult, _ = temp_breaker.evaluate_alert_allowed("GAMMA_BLAST")
    assert allowed is True
    assert mult == 1.05


def test_probation_degradation(temp_breaker):
    """Negative expectancy degrades detector into PROBATION with 25% discount."""
    # 1 win, 3 losses
    temp_breaker.record_outcome("a1", "SBIN", "ORB", "WIN", 1.2)
    temp_breaker.record_outcome("a2", "SBIN", "ORB", "LOSS", -1.0)
    temp_breaker.record_outcome("a3", "SBIN", "ORB", "LOSS", -1.0)
    temp_breaker.record_outcome("a4", "SBIN", "ORB", "LOSS", -1.0)

    metrics = temp_breaker.get_metrics("ORB")
    assert metrics.status == "PROBATION"
    assert metrics.win_rate == 0.25
    assert metrics.expectancy < 0.0
    assert metrics.confidence_multiplier == 0.75

    allowed, mult, msg = temp_breaker.evaluate_alert_allowed("ORB")
    assert allowed is True
    assert mult == 0.75
    assert "probation" in msg.lower()


def test_severe_losses_trip_circuit_breaker(temp_breaker):
    """5 consecutive losses trigger circuit breaker HALT."""
    for i in range(5):
        temp_breaker.record_outcome(
            alert_id=f"alert-loss-{i}",
            symbol="INFY",
            alert_type="CIRCUIT_WARNING",
            outcome="LOSS",
            realized_r=-1.0,
        )

    metrics = temp_breaker.get_metrics("CIRCUIT_WARNING")
    assert metrics.status == "HALTED"
    assert metrics.consecutive_losses == 5
    assert metrics.confidence_multiplier == 0.0

    allowed, mult, msg = temp_breaker.evaluate_alert_allowed("CIRCUIT_WARNING")
    assert allowed is False
    assert mult == 0.0
    assert "halted" in msg.lower()


def test_reset_detector(temp_breaker):
    """Reset clears history and returns detector to default status."""
    for i in range(5):
        temp_breaker.record_outcome(f"l-{i}", "TCS", "SQUEEZE", "LOSS", -1.0)

    assert temp_breaker.get_metrics("SQUEEZE").status == "HALTED"

    temp_breaker.reset_detector("SQUEEZE")
    assert temp_breaker.get_metrics("SQUEEZE").status == "NORMAL"


def test_auto_alert_engine_circuit_breaker_halt(monkeypatch):
    """When a detector is HALTED, AutoAlertEngine.record_alert rejects it."""
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from engine.detector_circuit_breaker import detector_circuit_breaker

    engine = AutoAlertEngine()
    test_type = "TEST_CIRCUIT_TRIP"

    # Trip breaker
    for i in range(5):
        detector_circuit_breaker.record_outcome(f"halt-{i}", "RELIANCE", test_type, "LOSS", -1.0)

    try:
        alert = AutoAlert(
            alert_id="live-test-halt-001",
            alert_type=test_type,
            stage="IGNITED",
            symbol="RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="Breakout",
            summary="Testing halt",
            ltp=2500.0,
            trigger_level=2500.0,
            target_level=2550.0,
            stop_loss=2480.0,
            confidence=85,
            is_live=True,
            environment="LIVE",
        )
        res = engine.record_alert(alert)
        assert res is False, "Alert from HALTED detector must be rejected"
    finally:
        detector_circuit_breaker.reset_detector(test_type)


def test_auto_alert_engine_circuit_breaker_probation(monkeypatch):
    """When a detector is in PROBATION, AutoAlertEngine applies a 25% confidence discount."""
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from engine.detector_circuit_breaker import detector_circuit_breaker

    engine = AutoAlertEngine()
    test_type = "TEST_CIRCUIT_PROBATION"

    # Degrade to probation (5 samples >= min_samples: 1 win of 1.5R, 4 losses of -1.0R with win in middle)
    detector_circuit_breaker.record_outcome("p1", "RELIANCE", test_type, "LOSS", -1.0)
    detector_circuit_breaker.record_outcome("p2", "RELIANCE", test_type, "LOSS", -1.0)
    detector_circuit_breaker.record_outcome("p3", "RELIANCE", test_type, "WIN", 1.5)
    detector_circuit_breaker.record_outcome("p4", "RELIANCE", test_type, "LOSS", -1.0)
    detector_circuit_breaker.record_outcome("p5", "RELIANCE", test_type, "LOSS", -1.0)

    import uuid

    aid = f"live-test-prob-{uuid.uuid4().hex[:6]}"
    with engine._lock:
        engine._alerts = [
            a for a in engine._alerts if not (a.symbol == "RELIANCE" and a.alert_type == test_type)
        ]

    try:
        alert = AutoAlert(
            alert_id=aid,
            alert_type=test_type,
            stage="IGNITED",
            symbol="RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="Breakout",
            summary="Testing probation",
            ltp=2500.0,
            trigger_level=2500.0,
            target_level=2600.0,
            stop_loss=2460.0,
            confidence=80,
            is_live=True,
            environment="LIVE",
        )
        # Mock market hours to avoid off-market suppression during test
        monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange: True)
        from engine.quality_gate import VetoVerdict

        monkeypatch.setattr(
            "engine.quality_gate.evaluate_institutional_quality_gate",
            lambda *args, **kwargs: VetoVerdict(
                is_vetoed=False,
                execution_mandate="STANDARD",
                conviction_tier="HIGH_CONVICTION",
            ),
        )
        import unittest.mock

        with unittest.mock.patch.object(engine, "_async_enrich_scrutiny"):
            res = engine.record_alert(alert)
            assert res is True
            # Original 80 * 0.75 = 60
            assert alert.confidence == 60
    finally:
        detector_circuit_breaker.reset_detector(test_type)
        with engine._lock:
            engine._alerts = [a for a in engine._alerts if a.alert_id != aid]
