"""
Tests for Milestone Integrity Invariant in ChanakyaTrade.
Verifies that no target milestone (T0.5, T1, T2, Final Target) can EVER be declared hit
unless the current market price (LTP) has physically crossed the target price level.
"""

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
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2520.0, milestone="T1_ACHIEVED"
        )[0]
        is False
    )
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2520.0, milestone="T2_ACHIEVED"
        )[0]
        is False
    )
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2520.0, milestone="TARGET_ACHIEVED"
        )[0]
        is False
    )
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2520.0, milestone="T0_5_ACHIEVED"
        )[0]
        is True
    )

    # Long: At or above T1
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2540.0, milestone="T1_ACHIEVED"
        )[0]
        is True
    )
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2541.0, milestone="T1_ACHIEVED"
        )[0]
        is True
    )
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2541.0, milestone="T2_ACHIEVED"
        )[0]
        is False
    )

    # Long: At or above T2
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2580.0, milestone="T2_ACHIEVED"
        )[0]
        is True
    )
    assert (
        engine.validate_milestone_integrity(
            long_alert, cur_quote_ltp=2580.0, milestone="TARGET_ACHIEVED"
        )[0]
        is True
    )

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
    assert (
        engine.validate_milestone_integrity(
            short_alert, cur_quote_ltp=1480.0, milestone="T1_ACHIEVED"
        )[0]
        is False
    )
    # Short: At or below T1
    assert (
        engine.validate_milestone_integrity(
            short_alert, cur_quote_ltp=1460.0, milestone="T1_ACHIEVED"
        )[0]
        is True
    )
    assert (
        engine.validate_milestone_integrity(
            short_alert, cur_quote_ltp=1459.0, milestone="T1_ACHIEVED"
        )[0]
        is True
    )
    assert (
        engine.validate_milestone_integrity(
            short_alert, cur_quote_ltp=1459.0, milestone="T2_ACHIEVED"
        )[0]
        is False
    )
    # Short: At or below T2
    assert (
        engine.validate_milestone_integrity(
            short_alert, cur_quote_ltp=1420.0, milestone="T2_ACHIEVED"
        )[0]
        is True
    )


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


def test_option_put_buyer_milestone_integrity_payoff_direction():
    """
    RCA Regression Test: Verify Put Option Buyer setup requires price expansion (upward payoff)
    to achieve T1, even though market direction is BEARISH.
    Prevents false T1 achievements when LTP is below T1.
    """
    engine = AutoAlertEngine()
    put_alert = AutoAlert(
        alert_id="aa-gamma-blast-nifty-pe-22250-20261008",
        alert_type="GAMMA_BLAST",
        stage="DE_RISK_0_5R",
        target_status="PENDING",
        symbol="NIFTY",
        contract_symbol="NSE:NIFTY26OCT22250PE",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 22250 PE Gamma Blast",
        summary="Put setup activated",
        ltp=96.55,
        trigger_level=90.45,
        stop_loss=79.76,
        target_level=121.50,
        confidence=98,
        segment="FNO_INDEX",
        strike=22250.0,
        option_type="PE",
        actionable_plan={
            "action": "BUY",
            "strike": 22250.0,
            "option_type": "PE",
            "recommended_entry": "₹90.45",
            "target_1": "₹106.94",
            "target_2": "₹121.50",
            "target_0_5": "₹99.50",
            "initial_invalidation_stop": "₹79.76",
        },
    )

    # 1. At CMP ₹96.55 (+0.57R, deficit ₹10.39 to T1), T1 MUST FAIL CLOSED!
    is_valid, veto_reason = engine.validate_milestone_integrity(
        put_alert, cur_quote_ltp=96.55, milestone="T1_ACHIEVED"
    )
    assert is_valid is False
    assert "below Target 1" in veto_reason

    is_t1_sat, _ = engine.validate_milestone_integrity_for_target(put_alert, "T1")
    assert is_t1_sat is False

    # 2. Template renderers MUST NOT render T1 HIT at ₹96.55
    from bot.free_index_templates import render_free_index_alert
    from bot.alert_templates import render_auto_alert

    free_msg = render_free_index_alert(put_alert, in_market=True)
    assert "T1 HIT" not in free_msg
    assert "hit T1" not in free_msg
    assert "96.55" in free_msg

    # Even if stage was falsely set to T1_ACHIEVED:
    put_alert.stage = "T1_ACHIEVED"
    put_alert.target_status = "T1"
    free_msg_vetoed = render_free_index_alert(put_alert, in_market=True)
    assert "T1 HIT" not in free_msg_vetoed
    assert "hit T1" not in free_msg_vetoed

    main_msg_vetoed = render_auto_alert(put_alert, in_market=True)
    assert "TARGET 1 ACHIEVED" not in main_msg_vetoed
    assert "TARGET 1 HIT" not in main_msg_vetoed

    # 3. When price physically reaches or crosses Target 1 (e.g. ₹107.00 >= ₹106.94), T1 MUST pass!
    put_alert.ltp = 107.00
    is_valid_t1, _ = engine.validate_milestone_integrity(
        put_alert, cur_quote_ltp=107.00, milestone="T1_ACHIEVED"
    )
    assert is_valid_t1 is True

    free_msg_passed = render_free_index_alert(put_alert, in_market=True)
    assert "T1 HIT" in free_msg_passed
    assert "hit T1" in free_msg_passed
