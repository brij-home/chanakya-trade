"""
tests/test_supercharge.py
─────────────────────────
Deterministic unit tests for engine/supercharge.py.
"""

import pytest
from pathlib import Path

from engine.supercharge import (
    COUNCIL_ROSTER,
    StrategistSeat,
    StrategyVariant,
    EvolutionLog,
    evaluate_variant_vetoes,
    render_comparison_dashboard,
)


def test_council_roster_invariants():
    """Verify 12 seats exist and exactly 4 hold binding vetoes."""
    assert len(COUNCIL_ROSTER) == 12

    veto_seats = [s.name for s in COUNCIL_ROSTER if s.has_veto]
    assert set(veto_seats) == {"Risk", "Backtest Integrity", "Execution", "Simplicity & Robustness"}


def test_evaluate_variant_vetoes_risk_trigger():
    base_sc = {"max_drawdown": 10.0, "sharpe": 1.5, "robustness_score": 0.8}
    # Variant has 22% drawdown (more than 1.35x baseline and > 15%)
    var_sc = {"max_drawdown": 22.0, "sharpe": 1.7, "robustness_score": 0.75}

    passed, vetoes, reason = evaluate_variant_vetoes(base_sc, var_sc, params={})
    assert passed is False
    assert "ruin risk" in reason.lower()
    assert vetoes["Risk"].startswith("VETOED")


def test_evaluate_variant_vetoes_integrity_trigger():
    base_sc = {"max_drawdown": 10.0, "sharpe": 1.5, "robustness_score": 0.8}
    # Variant has poor out-of-sample robustness (curve fit)
    var_sc = {"max_drawdown": 10.0, "sharpe": 2.2, "robustness_score": 0.25}

    passed, vetoes, reason = evaluate_variant_vetoes(base_sc, var_sc, params={})
    assert passed is False
    assert "robustness score" in reason.lower()
    assert vetoes["Backtest Integrity"].startswith("VETOED")


def test_evaluate_variant_vetoes_cleared():
    base_sc = {"max_drawdown": 10.0, "sharpe": 1.5, "robustness_score": 0.8}
    # Improved variant with controlled risk and robust OOS score
    var_sc = {"max_drawdown": 8.5, "sharpe": 1.9, "robustness_score": 0.85, "trade_count": 80}

    passed, vetoes, reason = evaluate_variant_vetoes(base_sc, var_sc, params={})
    assert passed is True
    assert reason is None
    for seat, status in vetoes.items():
        assert status == "CLEARED"


def test_evolution_log_and_dashboard(tmp_path):
    log_file = tmp_path / "test_evolution.jsonl"
    logger = EvolutionLog(log_path=log_file)

    logger.log_entry("round_start", {"round_no": 1, "objective": "sharpe"})
    logger.log_entry("variant_tested", {"variant_id": "v1_atr_trailing", "accepted": True})

    history = logger.get_history()
    assert len(history) == 2
    assert history[0]["entry_type"] == "round_start"

    # Dashboard rendering
    base_sc = {"total_return_pct": 25.0, "cagr": 20.0, "sharpe": 1.4, "max_drawdown": 12.0, "robustness_score": 0.8}
    v1 = StrategyVariant(
        variant_id="v1_trail_stop",
        round_no=1,
        objective="sharpe",
        params={},
        scorecard={"total_return_pct": 32.0, "cagr": 26.0, "sharpe": 1.85, "max_drawdown": 9.5, "robustness_score": 0.88},
        rules_changed=["Added ATR 2.5x trailing stop"],
        is_accepted=True,
    )

    dashboard = render_comparison_dashboard("EMA_Crossover", base_sc, [v1], objective="sharpe")
    assert "Strategy Supercharge Comparison Dashboard" in dashboard
    assert "v1_trail_stop" in dashboard
    assert "EMA_Crossover (BASELINE)" in dashboard
