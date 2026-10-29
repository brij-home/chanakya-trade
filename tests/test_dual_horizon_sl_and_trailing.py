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
        expiry_date="2026-11-05",
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


def test_dual_stop_loss_rca_and_target_consistency():
    """
    RCA Regression Test: Verify option alerts never render dual contradictory stop losses
    or mismatched targets between the bullet lines, reason text, and playbook.
    """
    alert = AutoAlert(
        alert_id="aa-trend-pullback-jswsteel-1210pe-20261026",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="JSWSTEEL",
        exchange="NFO",
        direction="BEARISH",
        headline="🎯 [TREND PULLBACK] JSWSTEEL 1210 PE Buy: 20-EMA Resistance Reject (Spot ₹1,212.4)",
        summary=(
            "Institutional shallow bounce into falling 20-EMA/VWAP on JSWSTEEL. Low-volume retest rejected at resistance. "
            "Enter JSWSTEEL 1210 PE @ ₹32.15. Stop loss: ₹30.2. (R:R 2.0)"
        ),
        ltp=32.15,
        trigger_level=32.15,
        target_level=41.8,
        stop_loss=27.3,
        tactical_sl=27.3,
        strike=1210.0,
        option_type="PE",
        contract_symbol="JSWSTEEL26OCT1210PE",
        option_premium=32.15,
        underlying_spot=1212.4,
        structural_spot_sl=1216.3,
        metrics={
            "underlying_spot": 1212.4,
            "spot_invalidation_anchor": 1216.3,
            "target_1": 41.8,
            "target_2": 49.0,
            "tactical_sl": 27.3,
        },
        actionable_plan={
            "action": "BUY PE",
            "contract": "JSWSTEEL 1210 PE",
            "instrument": "JSWSTEEL 1210 PE",
            "recommended_entry": "₹32.15",
            "stop_loss": "₹27.3",
            "tactical_sl": "₹27.3",
            "spot_invalidation_anchor": "₹1,216.3",
            "underlying_sl": "₹1,216.3",
            "target_1": "₹41.8",
            "target_2": "₹49.0",
            "target_3": "₹58.7",
            "profit_rule": "Scale Blueprint: Book 50% at Target 1 (₹41.8) and trail SL to Cost/Breakeven. Book 25% at Target 2 (₹49.0). Hold 25% runner trailing on EMA.",
            "option_plan": {
                "contract_symbol": "JSWSTEEL26OCT1210PE",
                "strike": 1210.0,
                "option_type": "PE",
                "entry_premium": 32.15,
                "sl_premium": 27.3,
                "t1_premium": 41.8,
                "t2_premium": 49.0,
                "t3_premium": 58.7,
            },
        },
    )

    rendered = render_auto_alert(alert)

    # 1. Safe SL (Tactical) must display ₹27.3
    assert "Safe SL (Tactical):" in rendered
    assert "₹27.3" in rendered or "₹27.30" in rendered

    # 2. Contradictory "Stop loss: ₹30.2" MUST NOT appear anywhere in the rendered alert!
    assert "Stop loss: ₹30.2" not in rendered
    assert "₹30.2" not in rendered

    # 3. Reason must contain strictly the market/technical thesis
    assert (
        "Reason:</b> <i>Institutional shallow bounce into falling 20-EMA/VWAP on JSWSTEEL."
        in rendered
    )

    # 4. Target 1 & Target 2 in bullets and Playbook must match exactly
    assert "T1:</b> <code>₹41.8" in rendered or "T1:</b> <code>₹41.80" in rendered
    assert "Target 1 (₹41.8" in rendered


def test_auto_alert_engine_noise_floor_sl_synchronization(tmp_path, monkeypatch):
    """
    Verify AutoAlertEngine noise floor gate synchronizes alert.stop_loss,
    alert.tactical_sl, actionable_plan, option_plan, and metrics when adjusting tight stops.
    """
    from engine.auto_alert_engine import AutoAlertEngine

    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)
    engine = AutoAlertEngine()

    # Create an initial alert with sub-noise-floor SL (6% risk: 32.15 -> 30.2)
    alert = AutoAlert(
        alert_id="aa-trend-pullback-jswsteel-test",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="JSWSTEEL",
        exchange="NFO",
        direction="BEARISH",
        headline="🎯 [TREND PULLBACK] JSWSTEEL 1210 PE Buy",
        summary="Institutional shallow bounce into falling 20-EMA/VWAP on JSWSTEEL.",
        ltp=32.15,
        trigger_level=32.15,
        target_level=39.22,
        stop_loss=30.2,  # <10% risk -> triggers noise floor calibration to 15%
        tactical_sl=30.2,
        strike=1210.0,
        option_type="PE",
        contract_symbol="JSWSTEEL26OCT1210PE",
        option_premium=32.15,
        underlying_spot=1212.4,
        structural_spot_sl=1216.3,
        metrics={
            "underlying_spot": 1212.4,
            "spot_invalidation_anchor": 1216.3,
            "target_1": 39.22,
            "target_2": 41.80,
            "target_3": 44.37,
        },
        actionable_plan={
            "action": "BUY PE",
            "contract": "JSWSTEEL 1210 PE",
            "recommended_entry": "₹32.15",
            "stop_loss": "₹30.2",
            "tactical_sl": "₹30.2",
            "target_1": "₹39.22",
            "target_2": "₹41.80",
            "target_3": "₹44.37",
            "option_plan": {
                "contract_symbol": "JSWSTEEL26OCT1210PE",
                "strike": 1210.0,
                "option_type": "PE",
                "entry_premium": 32.15,
                "sl_premium": 30.2,
                "t1_premium": 39.22,
                "t2_premium": 41.80,
                "t3_premium": 44.37,
            },
        },
        environment="TEST",
        is_live=False,
    )

    engine.record_alert(alert)

    # Verify stop loss was updated to 15% breathing room (27.3)
    assert alert.stop_loss == 27.3
    assert alert.tactical_sl == 27.3

    # Verify actionable_plan and option_plan were synchronized
    assert alert.actionable_plan["stop_loss"] == "₹27.3"
    assert alert.actionable_plan["tactical_sl"] == "₹27.3"
    assert alert.actionable_plan["option_sl"] == "₹27.3"
    assert alert.actionable_plan["option_plan"]["sl_premium"] == 27.3

    # Verify targets were synchronized
    min_t1 = alert.target_level
    assert min_t1 > 39.22  # Recalibrated to 2R+ from the new 15% SL
    assert alert.actionable_plan["option_plan"]["t1_premium"] == min_t1
    assert alert.metrics["tactical_sl"] == 27.3
