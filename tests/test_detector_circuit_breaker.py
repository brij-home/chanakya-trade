"""
tests/test_detector_circuit_breaker.py
───────────────────────────────────────
Unit tests for DetectorCircuitBreaker.
Verifies expectancy calculation, Kelly fraction, degradation state transitions, and halts.
"""

from __future__ import annotations

import pytest
import json

from engine.detector_circuit_breaker import DetectorCircuitBreaker


def _record_test_outcome(breaker, *args, **kwargs):
    """Mark synthetic unit-test observations explicitly so they cannot look live."""
    return breaker.record_outcome(*args, provenance="TEST", **kwargs)


@pytest.fixture
def temp_breaker(tmp_path):
    """Provides isolated circuit breaker with temp file."""
    ledger_file = tmp_path / "test_detector_perf.json"
    return DetectorCircuitBreaker(ledger_file=ledger_file, rolling_window=10, min_samples=4)


def test_initial_fresh_detector(temp_breaker):
    """Fresh detector has no empirical stats and no positive edge assumption."""
    metrics = temp_breaker.get_metrics("GAMMA_BLAST")
    assert metrics.status == "UNCALIBRATED"
    assert metrics.sample_count == 0
    assert metrics.win_rate == 0.0
    assert metrics.expectancy == 0.0
    assert metrics.kelly_fraction == 0.0
    assert metrics.confidence_multiplier == 1.0
    allowed, mult, msg = temp_breaker.evaluate_alert_allowed("GAMMA_BLAST")
    assert allowed is True
    assert mult == 1.0


def test_legacy_unqualified_outcomes_are_retained_but_not_calibrated(tmp_path):
    ledger_file = tmp_path / "legacy_detector_perf.json"
    legacy_records = [
        {
            "alert_id": f"legacy-{index}",
            "symbol": "NIFTY",
            "alert_type": "LEGACY",
            "outcome": "WIN" if index < 4 else "LOSS",
            "realized_r": 2.0 if index < 4 else -1.0,
            "timestamp": "2026-10-10 10:00:00 IST",
        }
        for index in range(5)
    ]
    ledger_file.write_text(json.dumps({"__schema_version__": 2, "LEGACY": legacy_records}))

    breaker = DetectorCircuitBreaker(ledger_file=ledger_file, min_samples=4)

    metrics = breaker.get_metrics("LEGACY")
    assert metrics.status == "UNCALIBRATED"
    assert metrics.sample_count == 0
    assert len(breaker._history["LEGACY"]) == 5
    assert all(row.provenance == "LEGACY_UNVERIFIED" for row in breaker._history["LEGACY"])

    _record_test_outcome(breaker, "new-test", "NIFTY", "LEGACY", "LOSS", -1.0)
    assert breaker.get_metrics("LEGACY").sample_count == 1


def test_healthy_winning_streak(temp_breaker):
    """A sufficiently sized mixed sample can qualify for HEALTHY status."""
    _record_test_outcome(
        temp_breaker,
        alert_id="alert-loss-calibration",
        symbol="NIFTY",
        alert_type="GAMMA_BLAST",
        outcome="LOSS",
        realized_r=-1.0,
    )
    for i in range(5):
        _record_test_outcome(
            temp_breaker,
            alert_id=f"alert-win-{i}",
            symbol="NIFTY",
            alert_type="GAMMA_BLAST",
            outcome="WIN",
            realized_r=2.5,
        )

    metrics = temp_breaker.get_metrics("GAMMA_BLAST")
    assert metrics.status == "HEALTHY"
    assert metrics.win_rate == 0.833
    assert metrics.expectancy > 0.50
    assert metrics.confidence_multiplier == 1.05

    allowed, mult, _ = temp_breaker.evaluate_alert_allowed("GAMMA_BLAST")
    assert allowed is True
    assert mult == 1.05


def test_forward_price_paths_cannot_claim_healthy_edge_or_kelly(temp_breaker):
    temp_breaker.record_outcome(
        "path-loss",
        "NIFTY",
        "PATH_ONLY",
        "LOSS",
        -1.0,
        provenance="ALERT_FORWARD_PATH_TERMINAL",
    )
    for index in range(5):
        temp_breaker.record_outcome(
            f"path-win-{index}",
            "NIFTY",
            "PATH_ONLY",
            "WIN",
            2.5,
            provenance="ALERT_FORWARD_PATH_TERMINAL",
        )

    metrics = temp_breaker.get_metrics("PATH_ONLY")

    assert metrics.expectancy > 0.0
    assert metrics.status == "NORMAL"
    assert metrics.confidence_multiplier == 1.0
    assert metrics.kelly_fraction == 0.0
    assert metrics.half_kelly == 0.0


def test_verified_fill_label_is_rejected_without_reconciled_fill_writer(temp_breaker):
    with pytest.raises(ValueError, match="account-scoped reconciled fill-ledger writer"):
        temp_breaker.record_outcome(
            "fill-label-is-not-evidence",
            "TCS",
            "ORB",
            "WIN",
            2.0,
            provenance="VERIFIED_BROKER_FILL",
        )


def test_test_provenance_is_rejected_outside_pytest_runtime(temp_breaker, monkeypatch):
    _record_test_outcome(temp_breaker, "existing-test-sample", "TCS", "ORB", "WIN", 2.0)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert temp_breaker.get_metrics("ORB").sample_count == 0
    with pytest.raises(ValueError, match="only accepted while running pytest"):
        temp_breaker.record_outcome(
            "synthetic-production-record",
            "TCS",
            "ORB",
            "WIN",
            2.0,
            provenance="TEST",
        )


def test_persisted_fill_label_does_not_establish_reconciliation(temp_breaker):
    rows = [
        {
            "alert_id": f"unverified-label-{index}",
            "symbol": "TCS",
            "alert_type": "ORB",
            "outcome": "WIN",
            "realized_r": 2.0,
            "provenance": "VERIFIED_BROKER_FILL",
        }
        for index in range(5)
    ]
    temp_breaker.ledger_file.write_text(json.dumps({"ORB": rows}), encoding="utf-8")
    reloaded = DetectorCircuitBreaker(ledger_file=temp_breaker.ledger_file, min_samples=4)
    metrics = reloaded.get_metrics("ORB")
    assert metrics.sample_count == 0
    assert metrics.status == "UNCALIBRATED"


def test_one_sided_winning_sample_does_not_claim_edge(temp_breaker):
    for i in range(5):
        _record_test_outcome(temp_breaker, f"one-side-{i}", "NIFTY", "ONE_SIDED", "WIN", 2.0)
    metrics = temp_breaker.get_metrics("ONE_SIDED")
    assert metrics.status == "UNCALIBRATED"
    assert metrics.win_rate == 0.0
    assert metrics.expectancy == 0.0
    assert metrics.kelly_fraction == 0.0


def test_flat_outcomes_remain_uncalibrated_without_division_errors(temp_breaker):
    for index in range(4):
        metrics = _record_test_outcome(
            temp_breaker, f"flat-{index}", "NIFTY", "FLAT_ONLY", "FLAT", 0.0
        )

    assert metrics.status == "UNCALIBRATED"
    assert metrics.sample_count == 4
    assert metrics.win_rate == 0.0
    assert metrics.expectancy == 0.0
    assert metrics.kelly_fraction == 0.0
    assert metrics.confidence_multiplier == 1.0


def test_outcome_replay_is_idempotent_and_conflicts_are_rejected(temp_breaker):
    original = _record_test_outcome(temp_breaker, "duplicate-id", "NIFTY", "DEDUP", "WIN", 1.5)
    replay = _record_test_outcome(temp_breaker, "duplicate-id", "NIFTY", "DEDUP", "WIN", 1.5)
    assert original.sample_count == replay.sample_count == 1
    with pytest.raises(ValueError, match="Conflicting outcome replay"):
        _record_test_outcome(temp_breaker, "duplicate-id", "NIFTY", "DEDUP", "WIN", 2.0)

    for index in range(12):
        _record_test_outcome(temp_breaker, f"dedup-window-{index}", "NIFTY", "DEDUP", "LOSS", -1.0)
    assert temp_breaker.get_metrics("DEDUP").sample_count == 10
    replay_after_rolloff = _record_test_outcome(
        temp_breaker, "duplicate-id", "NIFTY", "DEDUP", "WIN", 1.5
    )
    assert replay_after_rolloff.sample_count == 10

    reloaded = DetectorCircuitBreaker(
        ledger_file=temp_breaker.ledger_file, rolling_window=10, min_samples=4
    )
    assert (
        _record_test_outcome(reloaded, "duplicate-id", "NIFTY", "DEDUP", "WIN", 1.5).sample_count
        == 10
    )


def test_probation_degradation(temp_breaker):
    """Negative expectancy degrades detector into PROBATION with 25% discount."""
    # 1 win, 3 losses
    _record_test_outcome(temp_breaker, "a1", "SBIN", "ORB", "WIN", 1.2)
    _record_test_outcome(temp_breaker, "a2", "SBIN", "ORB", "LOSS", -1.0)
    _record_test_outcome(temp_breaker, "a3", "SBIN", "ORB", "LOSS", -1.0)
    _record_test_outcome(temp_breaker, "a4", "SBIN", "ORB", "LOSS", -1.0)

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
        _record_test_outcome(
            temp_breaker,
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
        _record_test_outcome(temp_breaker, f"l-{i}", "TCS", "SQUEEZE", "LOSS", -1.0)

    assert temp_breaker.get_metrics("SQUEEZE").status == "HALTED"

    temp_breaker.reset_detector("SQUEEZE")
    assert temp_breaker.get_metrics("SQUEEZE").status == "UNCALIBRATED"


def test_auto_alert_engine_circuit_breaker_halt(monkeypatch):
    """When a detector is HALTED, AutoAlertEngine.record_alert rejects it."""
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from engine.detector_circuit_breaker import detector_circuit_breaker

    test_type = "TEST_CIRCUIT_TRIP"
    detector_circuit_breaker.reset_detector(test_type)

    engine = AutoAlertEngine()
    with engine._lock:
        engine._alerts = []
        engine._cooldowns = {}

    # Trip breaker
    for i in range(5):
        _record_test_outcome(
            detector_circuit_breaker, f"halt-{i}", "RELIANCE", test_type, "LOSS", -1.0
        )

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
        with engine._lock:
            engine._alerts = []
            engine._cooldowns = {}


def test_auto_alert_engine_circuit_breaker_probation(monkeypatch):
    """When a detector is in PROBATION, AutoAlertEngine applies a 25% confidence discount."""
    from engine.auto_alert_engine import AutoAlertEngine
    from engine.alert_model import AutoAlert
    from engine.detector_circuit_breaker import detector_circuit_breaker
    from brokers.base import Quote
    from engine.quality_gate import VetoVerdict
    import unittest.mock
    import uuid

    test_type = "TEST_CIRCUIT_PROBATION"
    test_sym = "CIRCUIT_PROB_TEST"
    detector_circuit_breaker.reset_detector(test_type)

    # Environment isolation
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("DEPLOY_MODE", "test")
    monkeypatch.setattr("engine.alerts._is_market_hours", lambda exchange: True)
    monkeypatch.setattr(
        "engine.alert_scrutiny.alert_scrutiny_auditor.verify_tier1_sanity",
        lambda *args, **kwargs: (True, "", {}),
    )
    monkeypatch.setattr(
        "engine.quality_gate.evaluate_institutional_quality_gate",
        lambda *args, **kwargs: VetoVerdict(
            is_vetoed=False,
            execution_mandate="STANDARD",
            conviction_tier="HIGH_CONVICTION",
        ),
    )

    mock_q = Quote(
        symbol=test_sym,
        last_price=2500.0,
        open=2480.0,
        high=2520.0,
        low=2470.0,
        close=2490.0,
        volume=500000,
        provider="mock",
        source="STREAM",
        data_state="REALTIME",
    )
    monkeypatch.setattr(
        "market.quotes.get_quote",
        lambda syms, *args, **kwargs: {
            (s if isinstance(s, str) else test_sym): mock_q
            for s in (syms if isinstance(syms, list) else [syms])
        },
    )
    monkeypatch.setattr("market.quotes.get_ltp", lambda *args, **kwargs: 2500.0)

    engine = AutoAlertEngine()
    with engine._lock:
        engine._alerts = []
        engine._cooldowns = {}

    monkeypatch.setattr(engine, "_dispatch", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_save", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_auto_subscribe_stream", lambda *args, **kwargs: None)

    # Degrade to probation (5 samples >= min_samples: 1 win of 1.5R, 4 losses of -1.0R with win in middle)
    _record_test_outcome(detector_circuit_breaker, "p1", test_sym, test_type, "LOSS", -1.0)
    _record_test_outcome(detector_circuit_breaker, "p2", test_sym, test_type, "LOSS", -1.0)
    _record_test_outcome(detector_circuit_breaker, "p3", test_sym, test_type, "WIN", 1.5)
    _record_test_outcome(detector_circuit_breaker, "p4", test_sym, test_type, "LOSS", -1.0)
    _record_test_outcome(detector_circuit_breaker, "p5", test_sym, test_type, "LOSS", -1.0)

    aid = f"live-test-prob-{uuid.uuid4().hex[:6]}"

    try:
        alert = AutoAlert(
            alert_id=aid,
            alert_type=test_type,
            stage="IGNITED",
            symbol=test_sym,
            exchange="NSE",
            direction="BULLISH",
            headline="Probation Test Alert",
            summary="Testing probation",
            ltp=2500.0,
            trigger_level=2500.0,
            target_level=2600.0,
            stop_loss=2460.0,
            confidence=80,
            is_live=True,
            environment="LIVE",
        )

        with unittest.mock.patch.object(engine, "_async_enrich_scrutiny"):
            res = engine.record_alert(alert)
            assert res is True
            # Original 80 * 0.75 = 60
            assert alert.confidence == 60
    finally:
        detector_circuit_breaker.reset_detector(test_type)
        with engine._lock:
            engine._alerts = []
            engine._cooldowns = {}


def test_historical_losses_decay_to_probation_on_new_session(temp_breaker):
    """Losses from a previous calendar day do NOT halt the detector on day T; it enters PROBATION."""
    from engine.detector_circuit_breaker import TradeOutcome

    # Inject 5 losses with yesterday's timestamp
    for i in range(5):
        record = TradeOutcome(
            alert_id=f"yest-{i}",
            symbol="NIFTY",
            alert_type="OLD_LOSER",
            outcome="LOSS",
            realized_r=-1.0,
            provenance="TEST",
            timestamp="2026-10-10 10:00:00 IST",
        )
        temp_breaker._history.setdefault("OLD_LOSER", []).append(record)

    metrics = temp_breaker.get_metrics("OLD_LOSER")
    # Because today_consecutive_losses == 0, it does not HALT; enters PROBATION with 0.75x multiplier
    assert metrics.status == "PROBATION"
    assert metrics.confidence_multiplier == 0.75

    allowed, mult, msg = temp_breaker.evaluate_alert_allowed("OLD_LOSER")
    assert allowed is True
    assert mult == 0.75
    assert "probation" in msg.lower()


def test_get_all_metrics_and_reset_all(temp_breaker):
    """Verifies get_all_metrics dictionary and reset_all clearing."""
    _record_test_outcome(temp_breaker, "a1", "SBIN", "DET_A", "WIN", 1.5)
    _record_test_outcome(temp_breaker, "b1", "TCS", "DET_B", "LOSS", -1.0)

    all_m = temp_breaker.get_all_metrics()
    assert "DET_A" in all_m
    assert "DET_B" in all_m

    temp_breaker.reset_all()
    assert len(temp_breaker.get_all_metrics()) == 0
