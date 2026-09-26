"""
tests/test_detector_circuit_breaker.py
───────────────────────────────────────
Unit tests for DetectorCircuitBreaker.
Verifies expectancy calculation, Kelly fraction, degradation state transitions, and halts.
"""

from __future__ import annotations

from pathlib import Path
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
