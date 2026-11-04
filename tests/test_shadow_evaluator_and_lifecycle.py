"""
tests/test_shadow_evaluator_and_lifecycle.py
────────────────────────────────────────────
Unit tests for ShadowCandidateEvaluator & Candidate Funnel Lifecycle (S02 & S03).
Verifies:
  1. Shadow candidate recording and 15-minute episode deduplication.
  2. Forward price path evaluation (avoided adverse moves vs missed favorable moves).
  3. Suppressor ablation summary metrics and net R accounting.
  4. Latency telemetry tracking (p50/p95/p99) and entry validity budget compliance.
"""

from __future__ import annotations

from datetime import datetime
import pytest

from config.constants import IST
from engine.shadow_evaluator import (
    ShadowCandidateEvaluator,
)


@pytest.fixture
def temp_evaluator(tmp_path):
    storage = tmp_path / "shadow_candidates.json"
    return ShadowCandidateEvaluator(storage_path=storage)


def test_episode_deduplication(temp_evaluator):
    """Multiple option strikes/setups on the same underlying in a 15-minute window share one episode ID."""
    evaluator = temp_evaluator
    ref_dt = datetime(2026, 11, 1, 10, 10, tzinfo=IST)

    # Strike 1: NIFTY 25000 CE suppressed by RSI Extreme
    c1 = evaluator.record_shadow_candidate(
        symbol="NIFTY",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry_level=150.0,
        stop_loss=120.0,
        target_level=240.0,
        underlying_spot=25000.0,
        suppressed_by_gate="RSI_EXTREME_GATE",
        suppression_reason="RSI (79.0) > 78 overbought exhaustion",
        session_id="20261101",
        ref_dt=ref_dt,
    )

    # Strike 2: NIFTY 25050 CE suppressed 2 minutes later (10:12 IST)
    c2 = evaluator.record_shadow_candidate(
        symbol="NIFTY",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry_level=120.0,
        stop_loss=95.0,
        target_level=200.0,
        underlying_spot=25010.0,
        suppressed_by_gate="RSI_EXTREME_GATE",
        suppression_reason="RSI (79.5) > 78 overbought exhaustion",
        session_id="20261101",
        ref_dt=datetime(2026, 11, 1, 10, 12, tzinfo=IST),
    )

    # Different candidate IDs, but same underlying episode ID!
    assert c1.candidate_id != c2.candidate_id
    assert c1.episode_id == c2.episode_id
    assert "NIFTY:BULLISH:20261101:10_00" in c1.episode_id


def test_forward_price_path_evaluation(temp_evaluator):
    """Evaluate forward prices to distinguish successful gate vetoes from missed opportunities."""
    evaluator = temp_evaluator
    ref_dt = datetime(2026, 11, 1, 10, 5, tzinfo=IST)

    # Setup A: Avoided stop-loss liquidation
    c_avoided = evaluator.record_shadow_candidate(
        symbol="BANKNIFTY",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry_level=300.0,
        stop_loss=240.0,
        target_level=480.0,
        underlying_spot=54000.0,
        suppressed_by_gate="LEARNING_LOCKOUT_GATE",
        suppression_reason="Two-strike session lockout active",
        session_id="20261101",
        ref_dt=ref_dt,
    )

    # Setup B: Missed profitable move
    c_missed = evaluator.record_shadow_candidate(
        symbol="RELIANCE",
        direction="BULLISH",
        alert_type="INTRADAY_BREAKOUT",
        entry_level=2800.0,
        stop_loss=2760.0,  # 40 pts risk
        target_level=2920.0,  # 120 pts reward (+3.0R)
        underlying_spot=2800.0,
        suppressed_by_gate="VWAP_TREND_GATE",
        suppression_reason="Spot 0.6% below VWAP",
        session_id="20261101",
        ref_dt=ref_dt,
    )

    # Forward price bars (high, low)
    forward_paths = {
        # BANKNIFTY drops to 230.0 (breached SL 240.0) -> Veto saved capital!
        c_avoided.candidate_id: [(310.0, 290.0), (295.0, 230.0), (250.0, 220.0)],
        # RELIANCE rallies to 2930.0 without dropping below 2760.0 -> Missed +3.0R move!
        c_missed.candidate_id: [(2830.0, 2790.0), (2880.0, 2820.0), (2930.0, 2870.0)],
    }

    evaluated = evaluator.evaluate_shadow_outcomes(forward_paths)
    assert len(evaluated) == 2

    # Verify Setup A (Avoided Loss)
    assert c_avoided.evaluated is True
    assert c_avoided.avoided_adverse_move is True
    assert c_avoided.missed_favorable_move is False
    assert c_avoided.net_outcome_r == -1.0

    # Verify Setup B (Missed Opportunity)
    assert c_missed.evaluated is True
    assert c_missed.avoided_adverse_move is False
    assert c_missed.missed_favorable_move is True
    assert c_missed.net_outcome_r == 3.0


def test_suppressor_ablation_summary(temp_evaluator):
    """Verify suppressor ablation summary aggregates metrics and net R preserved."""
    evaluator = temp_evaluator
    ref_dt = datetime(2026, 11, 1, 11, 0, tzinfo=IST)

    # Record two candidates under LEARNING_LOCKOUT_GATE
    c1 = evaluator.record_shadow_candidate(
        symbol="TCS",
        direction="BULLISH",
        alert_type="BREAKOUT",
        entry_level=4000.0,
        stop_loss=3950.0,
        target_level=4150.0,
        underlying_spot=4000.0,
        suppressed_by_gate="LEARNING_LOCKOUT_GATE",
        suppression_reason="Lockout active",
        session_id="20261101",
        ref_dt=ref_dt,
    )

    c2 = evaluator.record_shadow_candidate(
        symbol="INFY",
        direction="BEARISH",
        alert_type="BREAKDOWN",
        entry_level=1800.0,
        stop_loss=1820.0,
        target_level=1740.0,
        underlying_spot=1800.0,
        suppressed_by_gate="LEARNING_LOCKOUT_GATE",
        suppression_reason="Lockout active",
        session_id="20261101",
        ref_dt=ref_dt,
    )

    # c1 hit SL (avoided loss: +1R preserved); c2 hit target (missed: -3R opportunity cost)
    evaluator.evaluate_shadow_outcomes(
        {
            c1.candidate_id: [(4020.0, 3940.0)],
            c2.candidate_id: [(1810.0, 1730.0)],
        }
    )

    summary = evaluator.get_suppressor_ablation_summary()
    assert "LEARNING_LOCKOUT_GATE" in summary
    gate_stats = summary["LEARNING_LOCKOUT_GATE"]
    assert gate_stats["total_suppressed"] == 2
    assert gate_stats["avoided_adverse_moves"] == 1
    assert gate_stats["missed_favorable_moves"] == 1
    assert gate_stats["gate_precision_pct"] == 50.0
    assert gate_stats["net_r_saved"] == -2.0  # +1.0R - 3.0R


def test_latency_telemetry_and_entry_validity_budget(temp_evaluator):
    """Pipeline latency percentiles and entry validity budget compliance."""
    evaluator = temp_evaluator

    # Candidate 1: Fast dispatch (within 60s budget)
    t0 = 1000.0
    s1 = evaluator.record_latency_telemetry(
        candidate_id="c-fast-1",
        first_evidence_ts=t0 - 2.0,
        trigger_ts=t0,
        eval_ts=t0 + 0.015,  # 15ms
        enrichment_ts=t0 + 0.045,  # 30ms
        dispatch_ts=t0 + 0.060,  # 15ms total: 60ms
        entry_validity_budget_seconds=60.0,
    )
    assert s1.detection_latency_ms == 15.0
    assert s1.enrichment_latency_ms == 30.0
    assert s1.dispatch_latency_ms == 15.0
    assert s1.total_pipeline_latency_ms == 60.0
    assert s1.is_within_entry_validity_budget is True

    # Candidate 2: Stale/late dispatch (85s > 60s budget)
    s2 = evaluator.record_latency_telemetry(
        candidate_id="c-slow-2",
        first_evidence_ts=t0,
        trigger_ts=t0 + 5.0,
        eval_ts=t0 + 10.0,
        enrichment_ts=t0 + 50.0,
        dispatch_ts=t0 + 90.0,  # 85s total
        entry_validity_budget_seconds=60.0,
    )
    assert s2.is_within_entry_validity_budget is False

    stats = evaluator.compute_pipeline_latency_stats()
    assert stats["sample_count"] == 2
    assert stats["on_time_ratio_pct"] == 50.0
    assert stats["p50_total_ms"] > 0
