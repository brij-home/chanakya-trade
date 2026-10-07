"""
Tests for Intraday Index Option Target Calibration & Trailed Breakeven Exit Integrity.
Verifies that:
1. Intraday Index Option targets (T1, T2, T3) are realistic and feasible within intraday market ATR.
2. Target 0.5 (Scale 1) is calibrated for intraday de-risking.
3. When a trailed breakeven stop is breached after T0.5 or T1, it is classified as a PROTECTED/BREAKEVEN exit,
   NEVER as a failed/losing 'SL HIT' or 'INVALIDATED' loss.
"""

import pytest
from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.trade_plan import calculate_trade_plan, calculate_option_execution_plan


def test_intraday_index_option_targets_are_feasible():
    """Verify Bank Nifty intraday option targets are calibrated to reachable intraday bounds."""
    # Bank Nifty spot at 55,229 with daily ATR ~650
    tp = calculate_trade_plan(
        symbol="NSE:BANKNIFTY",
        spot=55229.0,
        direction="BULLISH",
        timeframe="INTRADAY",
    )
    assert tp is not None
    # Intraday spot T1 must be within realistic single-wave ATR (max 0.25 * atr = ~162.5 pts)
    spot_move_t1 = tp.target_1 - 55229.0
    assert spot_move_t1 <= 200.0, f"Spot T1 move {spot_move_t1:.1f} is excessively large for intraday"

    # Now calculate option execution plan for a ₹972 option
    opt_plan = calculate_option_execution_plan(
        trade_plan=tp,
        option_type="CE",
        strike=54800.0,
        expiry="2026-10-29",
        option_ltp=972.2,
        lot_size=30,
        contract_symbol="NSE:BANKNIFTY26OCT54800CE",
    )
    assert opt_plan is not None

    t1_prem = opt_plan["t1_premium"]
    t2_prem = opt_plan["t2_premium"]
    t3_prem = opt_plan["t3_premium"]
    sl_prem = opt_plan["sl_premium"]
    t0_5_prem = opt_plan["t0_5_premium"]

    # Invariants:
    # 1. Monotonic ordering: SL < Entry < T0.5 <= T1 < T2 < T3
    assert sl_prem < 972.2 < t0_5_prem <= t1_prem < t2_prem < t3_prem

    # 2. Risk must be disciplined on expensive index options (max ~18% drawdown, not -28%)
    opt_drawdown = (972.2 - sl_prem) / 972.2
    assert opt_drawdown <= 0.18, f"Intraday index option drawdown {opt_drawdown:.1%} is excessively wide"

    # 3. T1 gain must be reachable in 1 intraday wave (+8% to +20%, NOT +30% or +50%)
    t1_gain_pct = (t1_prem - 972.2) / 972.2
    assert 0.08 <= t1_gain_pct <= 0.20, f"T1 gain {t1_gain_pct:.1%} must be feasible intraday (+8% to +20%)"

    # 4. T2 gain must be within session impulse (+18% to +35%)
    t2_gain_pct = (t2_prem - 972.2) / 972.2
    assert 0.15 <= t2_gain_pct <= 0.35, f"T2 gain {t2_gain_pct:.1%} must be feasible intraday (+15% to +35%)"

    # 5. T3 gain must not exceed realistic trend day ceiling (+55%)
    t3_gain_pct = (t3_prem - 972.2) / 972.2
    assert t3_gain_pct <= 0.55, f"T3 gain {t3_gain_pct:.1%} must be within trend-day ceiling (+55%)"


def test_trailed_breakeven_exit_is_not_sl_hit():
    """When stop loss is trailed to breakeven or slight profit, hitting it must return a protected trailing exit."""
    alert = AutoAlert(
        alert_id="aa-gamma-blast-banknifty-ce-54800-20261007",
        alert_type="GAMMA_BLAST",
        stage="T0_5_ACHIEVED",
        symbol="NSE:BANKNIFTY",
        exchange="NSE",
        contract_symbol="NSE:BANKNIFTY26OCT54800CE",
        direction="BULLISH",
        headline="🎯 [REAL/LIVE] TARGET 0.5 (SCALE 1) ACHIEVED",
        summary="Target 0.5 reached at ₹1,172.95 (+20.7%, +3.1R). DECISION: SCALE 35% PARTIAL PROFIT & TRAIL STOP-LOSS TO BREAKEVEN (₹974.10).",
        ltp=972.2,
        trigger_level=972.2,
        target_level=1120.0,
        stop_loss=974.1,  # Trailed to breakeven! (Above entry 972.2)
        initial_stop_loss=820.0,
        strike=54800.0,
        option_type="CE",
        underlying_spot=55229.0,
        option_premium=972.2,
        achieved_milestones=["T0_5_ACHIEVED"],
        target_status="T0_5_ACHIEVED",
        should_trail=True,
        trailing_stop=974.1,
    )

    # Current price drops to 972.0 (below trailed stop 974.1)
    reason = evaluate_alert_invalidation(alert, current_ltp=972.0)
    assert reason is not None
    # Crucial: Must be identified as a trailing runner stop / breakeven / profit secured, NOT a gamma thesis invalidation!
    assert "Trailing runner stop" in reason or "breakeven" in reason or "profit" in reason
    assert "thesis invalidated" not in reason
    assert "collapsed" not in reason


def test_auto_alert_engine_handles_breakeven_exit_as_runner_closed():
    """Verify AutoAlertEngine._handle_alert_exit marks trailed breakeven exits as RUNNER_EXIT, not INVALIDATED."""
    from engine.auto_alert_engine import auto_alert_engine

    alert = AutoAlert(
        alert_id="aa-gamma-blast-banknifty-ce-54800-test-be",
        alert_type="GAMMA_BLAST",
        stage="T0_5_ACHIEVED",
        symbol="NSE:BANKNIFTY",
        exchange="NSE",
        contract_symbol="NSE:BANKNIFTY26OCT54800CE",
        direction="BULLISH",
        headline="Target 0.5 hit",
        summary="Target 0.5 reached",
        ltp=972.2,
        trigger_level=972.2,
        target_level=1120.0,
        stop_loss=974.1,
        initial_stop_loss=820.0,
        strike=54800.0,
        option_type="CE",
        underlying_spot=55229.0,
        option_premium=972.2,
        achieved_milestones=["T0_5_ACHIEVED"],
        target_status="T0_5_ACHIEVED",
        should_trail=True,
        trailing_stop=974.1,
        environment="TEST",
        is_live=False,
    )

    reason = "Trailing runner stop triggered at ₹972.0 (breached ratcheted stop ₹974.1). Call Target profit secured; runner also closed in profit."
    is_inv = auto_alert_engine._handle_alert_exit(
        alert=alert,
        reason=reason,
        current_ltp=972.0,
        loop_context="Test",
    )

    # Invariants:
    # 1. Must return False (is_inv = False means it was NOT a loss invalidation)
    assert is_inv is False
    # 2. Stage must be RUNNER_EXIT
    assert alert.stage == "RUNNER_EXIT"
    # 3. is_invalidated must remain False
    assert alert.is_invalidated is False
    # 4. Headline must indicate profit secured / protected exit, not view invalidated!
    assert "VIEW INVALIDATED" not in alert.headline
    assert "PROFIT SECURED" in alert.headline or "BREAKEVEN" in alert.headline
