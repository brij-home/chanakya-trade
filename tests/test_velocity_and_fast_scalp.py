"""
tests/test_velocity_and_fast_scalp.py
─────────────────────────────────────
Institutional test suite for Cross-Index Velocity Radar, 20-Minute Time-Stops,
Fast Scalp Execution, and Optimal Gamma-Torque Option Selection.
"""

from __future__ import annotations

import unittest.mock as mock
from datetime import datetime, timezone, timedelta
import pandas as pd

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.trade_plan import calculate_option_execution_plan, TradePlan
from engine.index_velocity import (
    calculate_index_velocity,
    rank_indices_by_velocity,
)
from engine.auto_alert_engine import AutoAlertEngine
from bot.alert_templates import render_auto_alert

IST = timezone(timedelta(hours=5, minutes=30))


def test_index_velocity_calculation_and_ranking():
    """Verify that high ATR expansion creates LEADER_EXPANSION while tight consolidation creates CHOP_PINNED."""
    # Synthetic 5m OHLCV for High-Velocity mover (Midcap-like)
    n_bars = 20
    base_price = 14500.0
    high_vol_data = {
        "open": [base_price + i * 15 for i in range(n_bars)],
        "high": [base_price + i * 15 + 25 for i in range(n_bars)],
        "low": [base_price + i * 15 - 5 for i in range(n_bars)],
        "close": [base_price + i * 15 + 20 for i in range(n_bars)],
        "volume": [1000 + i * 200 for i in range(n_bars)],
    }
    df_leader = pd.DataFrame(high_vol_data)

    m_leader = calculate_index_velocity(
        "MIDCPNIFTY",
        ohlcv_5m=df_leader,
        spot=14800.0,
        change_pct=1.8,
        force_refresh=True,
    )
    assert m_leader.velocity_score >= 50.0
    assert m_leader.regime in ("LEADER_EXPANSION", "NORMAL_TREND")

    # Synthetic 5m OHLCV for Choppy Pinned index (BankNifty-like chop)
    chop_data = {
        "open": [56500.0 + (i % 2) * 5 for i in range(n_bars)],
        "high": [56500.0 + (i % 2) * 5 + 10 for i in range(n_bars)],
        "low": [56500.0 + (i % 2) * 5 - 10 for i in range(n_bars)],
        "close": [56500.0 + ((i + 1) % 2) * 5 for i in range(n_bars)],
        "volume": [500 for _ in range(n_bars)],
    }
    df_chop = pd.DataFrame(chop_data)

    m_chop = calculate_index_velocity(
        "BANKNIFTY",
        ohlcv_5m=df_chop,
        spot=56500.0,
        change_pct=0.04,
        force_refresh=True,
    )
    assert m_chop.velocity_score < m_leader.velocity_score
    assert m_chop.regime == "CHOP_PINNED"

    # Test ranking: leader should rank before chop
    with mock.patch("engine.index_velocity.calculate_index_velocity") as mock_calc:

        def side_effect(sym, **kwargs):
            if sym == "MIDCPNIFTY":
                return m_leader
            return m_chop

        mock_calc.side_effect = side_effect
        ranked = rank_indices_by_velocity(["BANKNIFTY", "MIDCPNIFTY"], force_refresh=True)
        assert ranked[0].symbol == "MIDCPNIFTY"
        assert ranked[0].is_leader is True
        assert ranked[1].symbol == "BANKNIFTY"


def test_fast_scalp_trade_plan_generation():
    """Verify that calculate_option_execution_plan injects fast_scalp metadata with 20m time-stop."""
    tp = TradePlan(
        symbol="NIFTY",
        direction="BUY",
        timeframe="INTRADAY",
        entry_price=23400.0,
        invalidation_stop=23350.0,
        stop_distance_pts=50.0,
        stop_distance_pct=0.21,
        sl_rationale="OB Demand Floor",
        target_1=23500.0,
        t1_distance_pts=100.0,
        t1_distance_pct=0.42,
        rr_t1=2.0,
        t1_rationale="PDH Liquidity",
        target_2=23600.0,
        t2_distance_pts=200.0,
        t2_distance_pct=0.85,
        rr_t2=4.0,
        t2_rationale="Weekly High",
        is_asymmetry_viable=True,
        asymmetry_verdict="EXCELLENT_ASYMMETRY",
        asymmetry_note="Valid asymmetry",
        atr_points=120.0,
        velocity_pts_per_bar=25.0,
        expected_bars_t1=4,
        expected_bars_t2=8,
        eta_t1_minutes=20,
        eta_t2_minutes=40,
        eta_t1_str="20m",
        eta_t2_str="40m",
        session_overrun_risk=False,
        session_clock_note="Normal market hours",
        options_recommended_structure="NAKED_OPTION",
        estimated_theta_drag_pts=2.5,
        theta_drag_pct_of_gain=5.0,
        structure_advice="Buy CE",
        target_3=23700.0,
        t3_distance_pts=300.0,
        t3_distance_pct=1.28,
        rr_t3=6.0,
        t3_rationale="Runner",
        expected_bars_t3=12,
        eta_t3_minutes=60,
        eta_t3_str="60m",
    )

    opt_plan = calculate_option_execution_plan(
        trade_plan=tp,
        option_type="CE",
        strike=23400.0,
        expiry="2026-09-29",
        option_ltp=100.0,
        lot_size=65,
    )

    assert "fast_scalp" in opt_plan
    fs = opt_plan["fast_scalp"]
    assert fs["scalp_target_premium"] > 100.0
    assert fs["scalp_target_pct"] >= 15.0
    assert fs["time_stop_mins"] == 20
    assert "Book 70%" in fs["scalp_profit_rule"]
    assert "time_stop_rule" in fs


def test_20_minute_velocity_time_stop():
    """Verify that an option stagnating for >= 20 minutes triggers TIME_STOP_SCRATCH."""
    now_ist = datetime.now(IST)
    # Created 25 minutes ago
    created_time = (now_ist - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="test-time-stop-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Breakdown Active",
        summary="Test alert",
        ltp=283.50,
        trigger_level=283.50,
        target_level=368.0,
        stop_loss=226.80,
        option_premium=283.50,
        contract_symbol="BANKNIFTY26SEP56600PE",
        created_at=created_time,
        triggered_at=created_time,
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹283.50",
            "stop_loss": "₹226.80",
            "target": "₹368.0",
            "fast_scalp": {"time_stop_mins": 20},
        },
    )

    # Current LTP is 285.0 (PnL +1.5 pts / +0.5%, R-multiple +0.02R < 0.40R)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=285.0)
    assert res is not None
    assert res.new_milestone == "TIME_STOP_SCRATCH"
    assert res.target_status == "TIME_STOP_EXIT"
    assert res.trailing_decision == "TIME_STOP_SCRATCH"
    assert res.trailing_ratcheted is True
    assert "VELOCITY TIME-STOP" in res.trailing_rationale


def test_auto_alert_engine_dynamic_velocity_prioritization():
    """Verify AutoAlertEngine prioritizes leader index at position 0."""
    engine = AutoAlertEngine()

    with mock.patch("engine.index_velocity.get_prioritized_index_symbols") as mock_pri:
        mock_pri.return_value = ["MIDCPNIFTY", "FINNIFTY", "SENSEX", "BANKNIFTY", "NIFTY"]
        targets = engine._get_prioritized_targets()
        # Today's expiry logic may adjust position 0, but MIDCPNIFTY will be top or near top
        assert "MIDCPNIFTY" in targets[:2]


def test_auto_alert_engine_time_stop_lifecycle():
    """Verify that AutoAlertEngine invalidates and archives alert upon TIME_STOP_SCRATCH."""
    engine = AutoAlertEngine()
    now_ist = datetime.now(IST)
    created_time = (now_ist - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="test-time-stop-engine",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="Breakdown Active",
        summary="Test alert",
        ltp=283.50,
        trigger_level=283.50,
        target_level=368.0,
        stop_loss=226.80,
        option_premium=283.50,
        contract_symbol="BANKNIFTY26SEP56600PE",
        is_live=True,
        environment="LIVE",
        created_at=created_time,
        triggered_at=created_time,
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹283.50",
            "stop_loss": "₹226.80",
            "target": "₹368.0",
            "fast_scalp": {"time_stop_mins": 20},
        },
    )

    with engine._lock:
        engine._alerts = [alert]

    with mock.patch.object(
        engine, "_batch_refresh_quotes", return_value={"BANKNIFTY26SEP56600PE": 284.0}
    ):
        with mock.patch.object(engine, "_dispatch"):
            with mock.patch.object(engine, "check_and_ignite_early_warnings"):
                with mock.patch.object(engine, "resolve_session_end_alerts"):
                    updated = engine.check_and_alert_targets_and_trailing()

    assert len(updated) == 1
    u = updated[0]
    assert u.stage == "TIME_STOP_EXIT"
    assert u.is_invalidated is True
    assert "VELOCITY TIME-STOP EXIT" in u.headline
    assert "TIME_STOP_SCRATCH" in u.achieved_milestones


def test_bot_template_time_stop_exit_rendering():
    """Verify render_auto_alert produces VELOCITY TIME-STOP EXIT Telegram card."""
    alert = AutoAlert(
        alert_id="test-time-stop-render",
        alert_type="OPTIONS_MOMENTUM",
        stage="TIME_STOP_EXIT",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="⏱️ [REAL/LIVE] VELOCITY TIME-STOP EXIT: BANKNIFTY 56600 PE",
        summary="Trade stagnant for 22m. Exit at CMP to halt theta decay.",
        invalidation_reason="Trade stagnant for 22m without momentum expansion.",
        ltp=284.0,
        trigger_level=283.50,
        target_level=368.0,
        stop_loss=226.80,
        contract_symbol="BANKNIFTY26SEP56600PE",
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹283.50",
            "stop_loss": "₹226.80",
        },
    )

    msg = render_auto_alert(alert, in_market=True)
    assert "VELOCITY TIME-STOP EXIT" in msg
    assert "STAGNATION TIME-STOP" in msg
    assert "EXIT AT CMP / SCRATCH POSITION" in msg
