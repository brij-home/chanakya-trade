"""
tests/test_dual_horizon_sl_and_trailing.py
──────────────────────────────────────────
Verification suite for Dual-Horizon Invalidation Blueprint (Safe Trader 1m Close vs
Structural Spot Trader with -32% Disaster Floor) and Trailing Stop Loss mechanics.
"""

from __future__ import annotations

import pandas as pd
from datetime import datetime

from config.constants import IST_ZONE as IST
from engine.alert_model import ActionableBlueprint, AutoAlert
from engine.alert_evaluator import (
    evaluate_alert_targets_and_trailing,
)
from engine.lifecycle.trade_lifecycle_manager import TradeLifecycleManager
from bot.alert_templates import (
    FNOAlertData,
    MilestoneAlertData,
    render_fno_alert,
    render_auto_alert,
    render_milestone_alert,
)
from bot.free_index_templates import (
    render_free_index_alert,
    render_free_index_milestone,
)
from engine.detectors.opening_drive import detect_opening_drive


def test_actionable_blueprint_dual_invalidation():
    """Verify ActionableBlueprint supports dual invalidation fields and serializes cleanly."""
    bp = ActionableBlueprint(
        action="BUY_CALL",
        entry_range="₹140.0 – ₹145.0",
        trigger_level=142.0,
        invalidation_stop=110.0,
        target_1=200.0,
        target_2=260.0,
        runner_target=320.0,
        risk_reward="1:3.0",
        tactical_sl="₹110.00 (1m candle CLOSE)",
        structural_spot_sl="24,820.0 Spot breach",
        disaster_stop_floor="-32% Disaster Floor (₹96.50)",
    )
    d = bp.to_dict()
    assert d["tactical_sl"] == "₹110.00 (1m candle CLOSE)"
    assert d["structural_spot_sl"] == "24,820.0 Spot breach"
    assert d["disaster_stop_floor"] == "-32% Disaster Floor (₹96.50)"
    assert d["invalidation_stop"] == 110.0


def test_auto_alert_dual_invalidation_derivation():
    """Verify AutoAlert derives tactical_sl, structural_spot_sl, and -32% disaster floor."""
    alert = AutoAlert(
        alert_id="aa-test-nifty-ce-20261012",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24900 CE Ignition",
        summary="Opening drive impulse",
        ltp=150.0,
        trigger_level=150.0,
        target_level=230.0,
        stop_loss=115.0,
        strike=24900.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT24900CE",
        metrics={
            "spot_invalidation_anchor": 24820.0,
            "underlying_spot": 24880.0,
        },
        actionable_plan={
            "action": "BUY",
            "entry_range": "₹148.0 – ₹152.0",
            "recommended_entry": "₹150.00",
            "stop_loss": "₹115.0",
            "target_1": "₹230.0",
            "target_2": "₹310.0",
            "underlying_sl": "₹24,820.0",
            "option_plan": {
                "entry_premium": 150.0,
                "sl_premium": 115.0,
                "t1_premium": 230.0,
            },
        },
    )
    # Tactical SL is set to option stop loss
    assert alert.tactical_sl == 115.0
    # Structural Spot SL is extracted from spot_invalidation_anchor
    assert alert.structural_spot_sl == 24820.0
    # Disaster floor is automatically -32% from entry premium (150 * 0.68 = 102.0)
    assert alert.disaster_stop_floor == 102.0

    d = alert.to_dict()
    assert d["tactical_sl"] == 115.0
    assert d["structural_spot_sl"] == 24820.0
    assert d["disaster_stop_floor"] == 102.0


def test_render_fno_alert_dual_invalidation():
    """Verify render_fno_alert formats Safe SL (1m close) and Structural SL (Spot breach + Disaster Floor)."""
    data = FNOAlertData(
        contract="NIFTY 24900 CE",
        underlying="NIFTY",
        spot=24880.0,
        premium=150.0,
        stop_loss=115.0,
        target_1=230.0,
        target_2=310.0,
        entry_range="₹148.00 – ₹152.00",
        spot_invalidation_anchor=24820.0,
        disaster_stop_floor=102.0,
    )
    rendered = render_fno_alert(data)
    assert "Safe SL (Tactical):" in rendered
    assert "1m close — filters freak wicks" in rendered
    assert "₹115.00" in rendered
    assert "Structural SL (Spot):" in rendered
    assert "24,820.0 Spot breach" in rendered
    assert "Disaster Floor: -32% @ ₹102.00" in rendered


def test_render_auto_alert_dual_invalidation():
    """Verify render_auto_alert formats Dual Invalidation for option setups."""
    alert = AutoAlert(
        alert_id="aa-auto-test-opt-20261012",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24900 CE Blast",
        summary="Order flow surge",
        ltp=150.0,
        trigger_level=150.0,
        target_level=230.0,
        stop_loss=115.0,
        strike=24900.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT24900CE",
        metrics={
            "spot_invalidation_anchor": 24820.0,
        },
        actionable_plan={
            "action": "BUY",
            "entry_range": "₹150.00",
            "recommended_entry": "₹150.00",
            "stop_loss": "₹115.0",
            "target_1": "₹230.0",
            "spot_invalidation_anchor": 24820.0,
        },
    )
    rendered = render_auto_alert(alert)
    assert "Safe SL (Tactical):" in rendered
    assert "1m close — filters freak wicks" in rendered
    assert "Structural SL (Spot):" in rendered
    assert "24820.0" in rendered or "24,820.0" in rendered
    assert "Disaster Floor: -32%" in rendered


def test_evaluate_target_1_spot_trail_and_lifecycle():
    """Verify evaluate_alert_targets_and_trailing generates recommended_spot_stop on T1."""
    alert = AutoAlert(
        alert_id="aa-eval-t1-test-20261012",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24900 CE Call",
        summary="Breakout",
        ltp=150.0,
        trigger_level=150.0,
        target_level=230.0,
        stop_loss=115.0,
        strike=24900.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT24900CE",
        underlying_spot=24880.0,
        metrics={
            "spot_invalidation_anchor": 24820.0,
            "underlying_spot": 24880.0,
        },
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹150.00",
            "stop_loss": "₹115.0",
            "target_1": "₹230.0",
            "target_2": "₹310.0",
            "underlying_sl": "₹24,820.0",
            "spot_trigger": "24,880.0",
        },
    )
    # Price reaches Target 1 (230.0)
    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=230.0)
    assert eval_res is not None
    assert eval_res.new_milestone == "T1_ACHIEVED"
    assert eval_res.should_trail is True
    # Option Breakeven stop: 150 * 1.002 = 150.3
    assert eval_res.recommended_stop == 150.3
    # Recommended spot stop trailed to spot entry level (24880.0)
    assert eval_res.recommended_spot_stop == 24880.0
    assert "Spot Trail: 24,880.0" in eval_res.trailing_rationale

    # Apply via TradeLifecycleManager
    lifecycle = TradeLifecycleManager()
    lifecycle.apply_milestone_state(
        alert,
        eval_res,
        cur_quote_ltp=230.0,
        now_ts=1728700000.0,
        now_str="2026-10-12 10:15:00 IST",
    )
    assert alert.trailing_stop == 150.3
    assert alert.trailing_spot_sl == 24880.0
    assert alert.metrics["spot_invalidation_anchor"] == 24880.0
    assert alert.actionable_plan["underlying_sl"] == 24880.0


def test_render_milestone_alert_t1_and_ratchet_spot_trail():
    """Verify render_milestone_alert renders Spot Trail alongside Option Trail Stop."""
    m_data = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="NIFTY",
        contract="NIFTY 24900 CE",
        ltp=230.0,
        target_1=230.0,
        entry_price=150.0,
        initial_sl=115.0,
        trailing_stop=150.3,
        trailing_spot_sl=24880.0,
        pnl_pts=80.0,
        pnl_pct=53.3,
        r_multiple=2.3,
    )
    rendered = render_milestone_alert(m_data)
    assert "TARGET 1 HIT" in rendered
    assert "Trail Stop:" in rendered
    assert "₹150.30" in rendered
    assert "<b>Spot Trail:</b> <code>24880.0</code>" in rendered

    # Test TRAIL_RATCHET update
    m_ratchet = MilestoneAlertData(
        milestone_type="TRAIL_RATCHET",
        symbol="NIFTY",
        contract="NIFTY 24900 CE",
        ltp=270.0,
        entry_price=150.0,
        trailing_stop=210.0,
        trailing_spot_sl=24940.0,
        pnl_pts=120.0,
        pnl_pct=80.0,
        r_multiple=3.4,
    )
    ratchet_rendered = render_milestone_alert(m_ratchet)
    assert "New SL:" in rendered or "New SL:" in ratchet_rendered
    assert "₹210.00" in ratchet_rendered
    assert "<b>Spot Trail:</b> <code>24940.0</code>" in ratchet_rendered


def test_free_index_dual_invalidation_and_milestone():
    """Verify free index signal templates format dual invalidation and spot trail."""
    alert = AutoAlert(
        alert_id="aa-free-idx-20261012",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24900 CE Signal",
        summary="Index breakout setup",
        ltp=150.0,
        trigger_level=150.0,
        target_level=230.0,
        stop_loss=115.0,
        strike=24900.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT24900CE",
        metrics={
            "spot_invalidation_anchor": 24820.0,
        },
        actionable_plan={
            "action": "BUY",
            "entry_range": "₹150.00",
            "stop_loss": "₹115.0",
            "target_1": "₹230.0",
            "spot_invalidation_anchor": 24820.0,
        },
    )
    free_rendered = render_free_index_alert(alert)
    assert "Safe SL (Tactical):" in free_rendered
    assert "1m close — filters freak wicks" in free_rendered
    assert "Structural SL (Spot):" in free_rendered
    assert "24820.0 Spot breach" in free_rendered

    # Milestone test (LTP at 230 to validate T1 hit)
    m_data = MilestoneAlertData.from_alert(alert, "TARGET_1")
    m_data.ltp = 230.0
    m_data.trailing_spot_sl = 24880.0
    free_ms = render_free_index_milestone(m_data)
    assert "T1 HIT" in free_ms
    assert "Spot Trail: 24880.0" in free_ms


def test_opening_drive_detector_dual_invalidation(monkeypatch):
    """Verify opening drive detector generates dual invalidation coordinates."""
    eval_time = datetime(2026, 10, 12, 9, 20, 0, tzinfo=IST)
    df_bar = pd.DataFrame(
        [
            {
                "open": 24800.0,
                "high": 24925.0,
                "low": 24800.0,
                "close": 24920.0,
                "volume": 450000.0,
            }
        ],
        index=pd.to_datetime([eval_time]),
    )

    # Mock heavyweights posture to be bullish
    monkeypatch.setattr(
        "market.indices.get_heavyweights_posture",
        lambda *args, **kwargs: {
            "heavyweights": [{"symbol": "HDFCBANK", "change_pct": 1.2}],
            "bull_count": 4,
            "bear_count": 0,
            "all_bearish": False,
        },
    )

    alert = detect_opening_drive(
        symbol="NIFTY",
        df_5m=df_bar,
        ltp=24920.0,
        prev_close=24760.0,
        prev_high=24780.0,
        ref_time=eval_time,
        ignore_time_gate=True,
    )
    assert alert is not None
    assert alert.alert_type == "OPENING_DRIVE_IGNITION"
    assert alert.metrics.get("spot_invalidation_anchor") is not None
    assert alert.actionable_plan.get("spot_invalidation_anchor") is not None
    assert alert.structural_spot_sl is not None
    assert alert.structural_spot_sl > 0
    if alert.tactical_sl is not None:
        assert alert.tactical_sl > 0
    if alert.disaster_stop_floor is not None:
        assert alert.disaster_stop_floor > 0
