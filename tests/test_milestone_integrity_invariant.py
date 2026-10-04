"""
Tests for Milestone Integrity Invariant in ChanakyaTrade.
Verifies that no target milestone (T0.5, T1, T2, Final Target) can EVER be declared hit
unless the current market price (LTP) has physically crossed the target price level.
"""

import pytest
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from engine.alert_evaluator import (
    TargetTrailingEvaluation,
    evaluate_alert_targets_and_trailing,
)
from bot.alert_templates import render_milestone_alert, MilestoneAlertData


def test_target_trailing_evaluation_properties():
    """Verify TargetTrailingEvaluation boolean properties are orthogonal and strictly partitioned."""
    t0_5_eval = TargetTrailingEvaluation(new_milestone="T0_5_ACHIEVED")
    assert t0_5_eval.is_t0_5_hit is True
    assert t0_5_eval.is_t1_hit is False, "T0_5_ACHIEVED must NOT evaluate to is_t1_hit=True!"
    assert t0_5_eval.is_t2_hit is False
    assert t0_5_eval.is_target_hit is False

    t1_eval = TargetTrailingEvaluation(new_milestone="T1_ACHIEVED")
    assert t1_eval.is_t0_5_hit is False
    assert t1_eval.is_t1_hit is True
    assert t1_eval.is_t2_hit is False
    assert t1_eval.is_target_hit is False

    t2_eval = TargetTrailingEvaluation(new_milestone="T2_ACHIEVED")
    assert t2_eval.is_t0_5_hit is False
    assert t2_eval.is_t1_hit is False
    assert t2_eval.is_t2_hit is True
    assert t2_eval.is_target_hit is False, "T2_ACHIEVED must NOT evaluate to is_target_hit=True!"

    target_eval = TargetTrailingEvaluation(new_milestone="TARGET_ACHIEVED")
    assert target_eval.is_t1_hit is False
    assert target_eval.is_t2_hit is False
    assert target_eval.is_target_hit is True


def test_btcusdt_scenario_never_declares_t1_hit_at_1r():
    """
    Exact scenario from user complaint:
    BTCUSDT: Entry $84,656.39, SL $83,895.08, T1 $87,684.72, T2 $91,095.40.
    Spot CMP moves to $85,428.00 (+1.01R).
    Must declare T0.5 (Scale 1 / De-Risk), NEVER Target 1.
    """
    alert = AutoAlert(
        alert_id="aa-crypto-btcusdt-test",
        alert_type="CRYPTO_MOMENTUM",
        stage="IGNITED",
        symbol="BTCUSDT",
        exchange="BINANCE",
        direction="BULLISH",
        headline="Crypto momentum",
        summary="Test momentum",
        ltp=84656.39,
        trigger_level=84656.39,
        stop_loss=83895.08,
        target_level=91095.40,
        actionable_plan={
            "entry_price": 84656.39,
            "invalidation_stop": 83895.08,
            "target_1": 87684.72,
            "target_2": 91095.40,
            "final_target": 91095.40,
        },
        achieved_milestones=[],
    )

    # Price moves to $85,428.00 (R = +1.01R)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=85428.00)
    assert res is not None
    assert res.new_milestone == "T0_5_ACHIEVED"
    assert res.is_t0_5_hit is True
    assert res.is_t1_hit is False, "LTP 85428.00 is below T1 87684.72 — is_t1_hit MUST be False!"
    assert res.is_t2_hit is False
    assert res.is_target_hit is False
    assert "Target 0.5" in res.trailing_rationale
    assert "87,684.72" in res.trailing_rationale


def test_validate_milestone_integrity_long_and_short():
    """Verify AutoAlertEngine.validate_milestone_integrity fail-closed gate."""
    engine = AutoAlertEngine()

    long_alert = AutoAlert(
        alert_id="aa-test-long",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout",
        summary="Test",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2480.0,
        target_level=2580.0,
        actionable_plan={"target_1": 2540.0, "target_2": 2580.0, "final_target": 2580.0},
    )

    # Long: Below T1
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2520.0, milestone="T1_ACHIEVED")[0] is False
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2520.0, milestone="T2_ACHIEVED")[0] is False
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2520.0, milestone="TARGET_ACHIEVED")[0] is False
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2520.0, milestone="T0_5_ACHIEVED")[0] is True

    # Long: At or above T1
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2540.0, milestone="T1_ACHIEVED")[0] is True
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2541.0, milestone="T1_ACHIEVED")[0] is True
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2541.0, milestone="T2_ACHIEVED")[0] is False

    # Long: At or above T2
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2580.0, milestone="T2_ACHIEVED")[0] is True
    assert engine.validate_milestone_integrity(long_alert, cur_quote_ltp=2580.0, milestone="TARGET_ACHIEVED")[0] is True

    short_alert = AutoAlert(
        alert_id="aa-test-short",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BEARISH",
        headline="Breakdown",
        summary="Test",
        ltp=1500.0,
        trigger_level=1500.0,
        stop_loss=1520.0,
        target_level=1420.0,
        actionable_plan={"target_1": 1460.0, "target_2": 1420.0, "final_target": 1420.0},
    )

    # Short: Above T1
    assert engine.validate_milestone_integrity(short_alert, cur_quote_ltp=1480.0, milestone="T1_ACHIEVED")[0] is False
    # Short: At or below T1
    assert engine.validate_milestone_integrity(short_alert, cur_quote_ltp=1460.0, milestone="T1_ACHIEVED")[0] is True
    assert engine.validate_milestone_integrity(short_alert, cur_quote_ltp=1459.0, milestone="T1_ACHIEVED")[0] is True
    assert engine.validate_milestone_integrity(short_alert, cur_quote_ltp=1459.0, milestone="T2_ACHIEVED")[0] is False
    # Short: At or below T2
    assert engine.validate_milestone_integrity(short_alert, cur_quote_ltp=1420.0, milestone="T2_ACHIEVED")[0] is True


def test_template_rendering_demotes_false_t1():
    """Verify bot alert template defensively vetoes and demotes false T1."""
    d = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="BTCUSDT",
        alert_type="CRYPTO MOMENTUM",
        ltp=85428.00,
        target_level=91095.40,
        trailing_stop=84825.70,
        entry_price=84656.39,
        target_1=87684.72,
        target_2=91095.40,
        pnl_pct=0.91,
        r_multiple=1.01,
        decisive_action="SCALE_35_TRAIL_BREAKEVEN",
        direction="BULLISH",
    )
    rendered = render_milestone_alert(d)
    assert "TARGET 1 ACHIEVED" not in rendered, "Template rendered false TARGET 1 ACHIEVED!"
    assert "TARGET 0.5" in rendered or "SCALE 1" in rendered


def test_dispatch_gate_rectifies_corrupted_alert():
    """Verify AutoAlertEngine._dispatch rectifies stage if an alert claims T1 before price reach."""
    engine = AutoAlertEngine()
    corrupted_alert = AutoAlert(
        alert_id="aa-crypto-btcusdt-corrupted",
        alert_type="CRYPTO_MOMENTUM",
        stage="T1_ACHIEVED",
        symbol="BTCUSDT",
        exchange="BINANCE",
        direction="BULLISH",
        headline="Target 1 achieved",
        summary="Test",
        ltp=85428.00,
        trigger_level=84656.39,
        stop_loss=84825.70,
        target_level=91095.40,
        target_status="T1_HIT",
        achieved_milestones=["BREAKEVEN_LOCKED", "T1_ACHIEVED"],
        actionable_plan={"target_1": 87684.72, "target_2": 91095.40},
    )

    # Calling _dispatch should detect the false T1 and rectify it
    engine._dispatch(corrupted_alert)

    assert corrupted_alert.stage != "T1_ACHIEVED", "Corrupted stage was not rectified by _dispatch!"
    assert corrupted_alert.stage == "T0_5_ACHIEVED"
    assert "T1_ACHIEVED" not in corrupted_alert.achieved_milestones
