"""
tests/test_risk_compression.py
──────────────────────────────
Institutional Test Suite for Dynamic Risk Compression (DRC) & Logical Stop-Loss Optimization.

Verifies:
  1. Pre-T1 Step-Ladder Trailing (+0.5R de-risking from -1.0R to -0.35R, +0.8R locking breakeven)
  2. SMC Post-Sweep Structural Trailing (tightening SL to post-sweep floor upon liquidity probe)
  3. Midday Theta Stall & Bleed Guard (tightening SL during 12:00-14:15 IST midday lull)
  4. Monotonic Invariant (Stop loss can NEVER loosen or move away from profit)
  5. Option Execution Plan DRC ladder metadata
  6. AutoAlert Engine propagation (updating alert.stop_loss and actionable_plan)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.trade_plan import calculate_option_execution_plan, TradePlan

IST = timezone(timedelta(hours=5, minutes=30))


def test_drc_pillar_1_pre_t1_step_ladder_half_r():
    """Verify that at +0.5R, stop-loss is compressed from -1.0R to -0.35R, slashing downside risk by 65%."""
    # Entry = 100.0, Initial SL = 80.0 (Risk = 20.0 pts)
    # T1 = 140.0 (+2.0R)
    alert = AutoAlert(
        alert_id="test-drc-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout Ignited",
        summary="Test alert",
        ltp=100.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=80.0,
        option_premium=100.0,
        contract_symbol="NIFTY26SEP23500PE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹100.0",
            "stop_loss": "₹80.0",
            "target": "₹140.0",
        },
    )

    # At LTP = 111.0: PnL = +11.0 pts. R-multiple = 11 / 20 = +0.55R (> 0.5R, < 0.8R)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=111.0)
    assert res is not None
    assert res.new_milestone == "DE_RISK_0_5R"
    assert res.should_trail is True
    assert res.is_risk_compression is True
    assert res.trailing_ratcheted is True

    # Initial risk = 20. Compressed stop = 100 - (20 * 0.35) = 93.0
    assert res.recommended_stop == 93.0
    # Risk saved = 93 - 80 = 13 pts. 13 / 20 = 65% reduction
    assert res.risk_reduction_pct == 65.0
    assert "DE-RISK TRADE EARLY" in res.trailing_rationale


def test_drc_pillar_1_pre_t1_breakeven_lock():
    """Verify that at +0.8R, stop-loss is ratcheted to Breakeven (+0.2% buffer), eliminating 100% downside."""
    # Entry = 100.0, SL = 85.0 (Risk = 15.0 pts, 0.8R = +12.0 pts at 112.0, below T0.5 default 116.0)
    alert = AutoAlert(
        alert_id="test-drc-002",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout Ignited",
        summary="Test alert",
        ltp=100.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=85.0,
        option_premium=100.0,
        contract_symbol="NIFTY26SEP23500PE",
        achieved_milestones=["DE_RISK_0_5R"],  # Already completed 0.5R de-risk
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹100.0",
            "initial_sl": "₹85.0",
            "stop_loss": "₹94.75",
            "target": "₹140.0",
        },
    )

    # At LTP = 113.0: PnL = +13.0 pts. R-multiple = 13 / 15 = +0.867R (>= 0.8R, < 1.5R)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=113.0)
    assert res is not None
    assert res.new_milestone == "BREAKEVEN_LOCKED"
    assert res.should_trail is True
    assert res.is_risk_compression is True
    # Breakeven stop = Entry * 1.002 = 100.20
    assert res.recommended_stop == 100.20
    assert res.risk_reduction_pct == 100.0
    assert "LOCK BREAKEVEN" in res.trailing_rationale


def test_drc_pillar_1_t0_5_scale_hit_also_compresses_risk():
    """Verify that when structural T0.5 target is reached, it also acts as a 100% risk compression event."""
    alert = AutoAlert(
        alert_id="test-drc-002b",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout Ignited",
        summary="Test alert",
        ltp=100.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=80.0,
        option_premium=100.0,
        contract_symbol="NIFTY26SEP23500PE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹100.0",
            "stop_loss": "₹80.0",
            "target": "₹140.0",
        },
    )

    # At LTP = 117.0: Crosses T0.5 default level (116.0)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=117.0)
    assert res is not None
    assert res.new_milestone == "T0_5_ACHIEVED"
    assert res.should_trail is True
    assert res.is_risk_compression is True
    assert res.risk_reduction_pct == 100.0
    assert res.recommended_stop == 100.20


def test_drc_pillar_2_smc_post_sweep_trailing():
    """Verify that when an SMC liquidity sweep is detected on the underlying, SL tightens to post-sweep floor."""
    alert = AutoAlert(
        alert_id="test-drc-003",
        alert_type="SMC_SWEEP",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="SMC Sweep Ignited",
        summary="Test alert",
        ltp=280.0,
        trigger_level=280.0,
        target_level=360.0,
        stop_loss=220.0,  # Initial risk = 60.0 pts
        option_premium=280.0,
        contract_symbol="BANKNIFTY26SEP56600PE",
        metrics={
            "post_sweep_sl": 255.0,  # Higher structural floor established after liquidity probe
        },
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹280.0",
            "stop_loss": "₹220.0",
            "target": "₹360.0",
        },
    )

    # LTP is 290 (+0.16R, below 0.5R step-ladder trigger)
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=290.0)
    assert res is not None
    assert res.new_milestone == "TRAIL_POST_SWEEP"
    assert res.should_trail is True
    assert res.recommended_stop == 255.0
    # Risk saved = 255 - 220 = 35 pts out of 60 initial risk = 58.3%
    assert res.risk_reduction_pct > 50.0
    assert "POST-SWEEP FLOOR" in res.trailing_rationale


def test_drc_pillar_3_midday_stall_and_bleed_guard():
    """Verify that during midday lull (12:00-14:15 IST), an option trade stagnant for >= 35m tightens SL by 35%."""
    created_time = (
        datetime.now(IST).replace(hour=12, minute=5, second=0).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    alert = AutoAlert(
        alert_id="test-drc-004",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout Ignited",
        summary="Test alert",
        ltp=100.0,
        trigger_level=100.0,
        target_level=150.0,
        stop_loss=70.0,  # Initial risk = 30 pts
        option_premium=100.0,
        created_at=created_time,
        contract_symbol="NIFTY26SEP23500CE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹100.0",
            "stop_loss": "₹70.0",
            "target": "₹150.0",
        },
    )

    # LTP is 101.0 (flat/choppy: +1% PnL, R-multiple = +0.03R)
    # Mocking now as 12:45 IST (40 minutes elapsed)
    import unittest.mock as mock

    fake_now = datetime.now(IST).replace(hour=12, minute=45, second=0)
    with mock.patch("engine.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.strptime = datetime.strptime
        mock_dt.fromisoformat = datetime.fromisoformat

        res = evaluate_alert_targets_and_trailing(alert, current_ltp=101.0)

    assert res is not None
    assert res.new_milestone == "COMPRESS_STALL_RISK"
    assert res.should_trail is True
    # Initial risk = 30. Compressed stop = 100 - (30 * 0.65) = 80.50
    assert res.recommended_stop == 80.50
    assert res.risk_reduction_pct == 35.0
    assert "COMPRESS RISK AGAINST THETA BLEED" in res.trailing_rationale


def test_drc_monotonic_invariant_never_loosens_stop():
    """Verify that DRC will NEVER recommend a looser stop loss than an existing higher trailing stop."""
    alert = AutoAlert(
        alert_id="test-drc-005",
        alert_type="OPTIONS_MOMENTUM",
        stage="TRAILING_UPDATE",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Trailing Active",
        summary="Test alert",
        ltp=112.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=80.0,
        trailing_stop=96.0,  # Already ratcheted higher
        option_premium=100.0,
        contract_symbol="NIFTY26SEP23500PE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹100.0",
            "stop_loss": "₹96.0",
            "target": "₹140.0",
        },
    )

    # At +0.55R, default DRC recommends 93.0. But alert already has trailing_stop = 96.0.
    # It must NOT loosen from 96.0 to 93.0!
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=111.0)
    # Because 93.0 is looser than 96.0, DRC does not trigger a downgrade.
    # It falls through to hold stop.
    assert res is not None
    assert res.new_milestone != "DE_RISK_0_5R"


def test_calculate_option_execution_plan_drc_ladder():
    """Verify that calculate_option_execution_plan includes the DRC ladder with explicit trigger and stop levels."""
    dummy_tp = TradePlan(
        symbol="NIFTY",
        direction="LONG",
        timeframe="INTRADAY",
        entry_price=23400.0,
        invalidation_stop=23300.0,
        stop_distance_pts=100.0,
        stop_distance_pct=0.43,
        sl_rationale="OB",
        target_1=23550.0,
        t1_distance_pts=150.0,
        t1_distance_pct=0.64,
        rr_t1=1.5,
        t1_rationale="Supply",
        target_2=23700.0,
        t2_distance_pts=300.0,
        t2_distance_pct=1.28,
        rr_t2=3.0,
        t2_rationale="Sweep",
        is_asymmetry_viable=True,
        asymmetry_verdict="EXCELLENT",
        asymmetry_note="",
        atr_points=120.0,
        velocity_pts_per_bar=15.0,
        expected_bars_t1=10,
        expected_bars_t2=20,
        eta_t1_minutes=50,
        eta_t2_minutes=100,
        eta_t1_str="~50m",
        eta_t2_str="~100m",
        session_overrun_risk=False,
        session_clock_note="",
        options_recommended_structure="NAKED_OPTION",
        estimated_theta_drag_pts=2.5,
        theta_drag_pct_of_gain=5.0,
        structure_advice="",
    )

    opt_plan = calculate_option_execution_plan(
        trade_plan=dummy_tp,
        option_type="CE",
        strike=23400.0,
        expiry="2026-09-30",
        option_ltp=150.0,
        lot_size=65,
    )

    assert "risk_compression_ladder" in opt_plan
    ladder = opt_plan["risk_compression_ladder"]
    assert "de_risk_trigger_prem" in ladder
    assert "de_risk_new_stop" in ladder
    assert "breakeven_trigger_prem" in ladder
    assert "breakeven_stop" in ladder
    assert ladder["de_risk_trigger_prem"] > 150.0
    assert ladder["de_risk_new_stop"] > opt_plan["sl_premium"]
    assert ladder["breakeven_stop"] >= 150.0


def test_auto_alert_engine_drc_lifecycle_integration():
    """Verify that auto_alert_engine._evaluate_alert_lifecycle updates alert fields upon DRC milestones."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    alert = AutoAlert(
        alert_id="test-drc-lifecycle-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Initial Signal",
        summary="Initial Signal Summary",
        ltp=100.0,
        trigger_level=100.0,
        target_level=140.0,
        stop_loss=80.0,
        option_premium=100.0,
        contract_symbol="NIFTY26SEP23500PE",
        is_live=True,
        environment="LIVE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹100.0",
            "stop_loss": "₹80.0",
            "target": "₹140.0",
            "option_plan": {"sl_premium": 80.0},
        },
    )

    with engine._lock:
        engine._alerts = [alert]

    # Mock batch refresh to return 111.0 (+0.55R)
    import unittest.mock as mock

    with mock.patch.object(
        engine, "_batch_refresh_quotes", return_value={"NIFTY26SEP23500PE": 111.0}
    ):
        with mock.patch.object(engine, "_dispatch"):
            with mock.patch.object(engine, "check_and_ignite_early_warnings"):
                with mock.patch.object(engine, "resolve_session_end_alerts"):
                    updated = engine.check_and_alert_targets_and_trailing()

    assert len(updated) == 1
    u_alert = updated[0]
    assert u_alert.stage == "DE_RISK_0_5R"
    assert "DE_RISK_0_5R" in u_alert.achieved_milestones
    assert "RISK COMPRESSED (+0.5R DE-RISK)" in u_alert.headline
    assert u_alert.stop_loss == 93.0
    assert u_alert.trailing_stop == 93.0
    assert u_alert.actionable_plan["invalidation_stop"] == 93.0
    assert u_alert.actionable_plan["option_plan"]["sl_premium"] == 93.0
