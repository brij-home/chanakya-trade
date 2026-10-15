"""
tests/test_predatory_pipeline_and_circuit_breaker.py
────────────────────────────────────────────────────
Unit & regression tests for the 5 institutional enhancements:
  1. Autonomous Live Trailing-Stop Ratchet & Telegram Free-Roll Milestone Dispatch
  2. Quantized Capital Position Sizing in Actionable Blueprints
  3. Closed-Loop Post-Mortem Feedback (Detector Circuit Breaker Enforcement)
  4. Mathematical Expected Value (EV >= +0.85R) Calculation & Stamping
"""

from types import SimpleNamespace

from bot.alert_templates import render_milestone_alert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.detector_circuit_breaker import DetectorCircuitBreaker
from engine.lifecycle.trade_lifecycle_manager import TradeLifecycleManager
from engine.trade_plan import calculate_trade_plan


def test_t1_achieved_locks_cheetah_free_roll_in_lifecycle_and_telegram():
    """Verify that reaching T1 locks cheetah free-roll and renders free-roll banner."""
    mgr = TradeLifecycleManager()

    mock_alert = SimpleNamespace(
        alert_id="aa-orb-infy-20261012",
        symbol="INFY",
        contract_symbol=None,
        alert_type="ORB",
        direction="BULLISH",
        trigger_level=1500.0,
        stop_loss=1480.0,
        target_level=1540.0,
        ltp=1540.0,
        metrics={},
        actionable_plan={"invalidation_stop": 1480.0, "stop_loss": 1480.0},
        environment="TEST",
        is_live=False,
        achieved_milestones=[],
        stage="ACTIVE",
    )

    eval_res = SimpleNamespace(
        should_trail=True,
        trailing_decision="T1_TRAIL",
        recommended_stop=1503.0,
        trailing_rationale="Ratchet stop to breakeven +0.2% cost protection",
        locked_profit_pts=3.0,
        locked_profit_pct=0.2,
        target_status="T1_ACHIEVED",
        r_multiple=2.0,
        pnl_pct=2.67,
        strike_roll_recommendation=None,
        new_milestone="T1_ACHIEVED",
    )

    mgr.apply_milestone_state(
        alert=mock_alert,
        eval_res=eval_res,
        cur_quote_ltp=1540.0,
        now_ts=1728711300.0,
        now_str="2026-10-12 10:15:00 IST",
    )

    # 1. Verification of alert state & predatory pipeline Cheetah stamp
    assert mock_alert.metrics.get("free_roll_locked") is True
    assert mock_alert.actionable_plan.get("free_roll_active") is True
    assert mock_alert.stop_loss == 1503.0
    assert mock_alert.actionable_plan.get("stop_loss") == 1503.0
    assert (
        mock_alert.metrics.get("predatory_pipeline", {}).get("cheetah", {}).get("status")
        == "FREE_ROLL_ACTIVE"
    )

    # 2. Telegram Milestone Template Rendering
    d_dto = SimpleNamespace(
        contract="INFY",
        symbol="INFY",
        alert_type="ORB",
        direction="BULLISH",
        segment="EQUITY",
        ltp=1540.0,
        target_1=1540.0,
        target_2=1580.0,
        target_0_5=None,
        target_level=1540.0,
        trailing_stop=1503.0,
        locked_profit_pct=0.2,
        pnl_pts=40.0,
        pnl_pct=2.67,
        r_multiple=2.0,
        entry_price=1500.0,
        entry_range=None,
        initial_sl=1480.0,
        lot_size=None,
        milestone_type="TARGET_1",
        call_time="10:00 AM",
        timestamp="10:15 AM",
        is_t1_achieved=True,
        invalidation_reason=None,
        rationale=None,
        footer=None,
        environment="TEST",
        in_market=True,
    )

    msg = render_milestone_alert(d_dto)
    assert "TARGET 1 HIT" in msg
    assert "CHEETAH EXECUTION:" in msg
    assert "FREE-ROLL ACTIVE" in msg
    assert "ZERO DOWNSIDE RISK" in msg


def test_quantized_position_sizing_attached_to_trade_plan():
    """Verify that calculate_trade_plan includes quantized capital position sizing."""
    plan = calculate_trade_plan(
        symbol="TCS",
        direction="BUY",
        spot=3500.0,
        timeframe="INTRADAY",
    )

    assert plan.position_sizing is not None
    assert isinstance(plan.position_sizing, dict)
    assert "shares" in plan.position_sizing
    assert "capital_allocated" in plan.position_sizing
    assert "risk_amount" in plan.position_sizing
    assert plan.position_sizing["shares"] > 0
    assert plan.position_sizing["risk_amount"] > 0

    # Serialization test
    as_dict = plan.as_dict()
    assert "position_sizing" in as_dict
    assert as_dict["position_sizing"]["shares"] == plan.position_sizing["shares"]


def test_detector_circuit_breaker_halts_degraded_detector(tmp_path):
    """Verify that consecutive losses trigger HALTED and veto alerts in verify_tier1_sanity."""
    ledger = tmp_path / "cb_test.json"
    cb = DetectorCircuitBreaker(ledger_file=ledger, min_samples=3)

    # Record 5 consecutive losses
    for i in range(5):
        cb.record_outcome(
            alert_id=f"alert-{i}",
            symbol="NIFTY",
            alert_type="GAMMA_BLAST",
            outcome="LOSS",
            realized_r=-1.0,
        )

    metrics = cb.get_metrics("GAMMA_BLAST")
    assert metrics.status == "HALTED"
    assert metrics.consecutive_losses == 5
    allowed, mult, msg = cb.evaluate_alert_allowed("GAMMA_BLAST")
    assert allowed is False
    assert mult == 0.0
    assert "circuit tripped" in msg

    # Verify that AlertScrutinyAuditor vetoes an alert when detector is halted
    auditor = AlertScrutinyAuditor()
    mock_alert = SimpleNamespace(
        alert_id="aa-gamma-blast-nifty-20261012",
        symbol="NIFTY",
        alert_type="GAMMA_BLAST",
        direction="BULLISH",
        ltp=24500.0,
        stop_loss=24400.0,
        target_level=24750.0,
        trigger_level=24500.0,
        environment="REAL",
        is_live=True,
    )

    # Monkeypatch singleton circuit breaker in scrutiny
    import engine.detector_circuit_breaker

    orig_cb = engine.detector_circuit_breaker.detector_circuit_breaker
    engine.detector_circuit_breaker.detector_circuit_breaker = cb

    try:
        passed, reason, flags = auditor.verify_tier1_sanity(mock_alert)
        assert passed is False
        assert "Detector Circuit Breaker Tripped" in reason
        assert flags.get("circuit_breaker_valid") is False
    finally:
        engine.detector_circuit_breaker.detector_circuit_breaker = orig_cb


def test_mathematical_expected_value_and_sniper_stamping():
    """Verify that compile_predatory_pipeline_dossier computes EV and stamps expected_value_r."""
    auditor = AlertScrutinyAuditor()
    mock_alert = SimpleNamespace(
        alert_id="aa-squeeze-reliance-20261012",
        symbol="RELIANCE",
        alert_type="SQUEEZE_BREAKOUT",
        direction="BULLISH",
        ltp=2800.0,
        stop_loss=2760.0,
        target_level=2900.0,
        trigger_level=2800.0,
        environment="REAL",
        is_live=True,
        metrics={},
    )

    flags = {"no_chase": True, "staged_rr_scaleout": False}
    dossier = auditor.compile_predatory_pipeline_dossier(mock_alert, flags)

    assert "expected_value_r" in dossier
    assert "sniper" in dossier
    assert dossier["sniper"].get("expected_value_r") == dossier["expected_value_r"]
    # R:R is (2900 - 2800) / (2800 - 2760) = 100 / 40 = 2.50
    # EV = (0.60 * 2.50) - (0.40 * 1.0) - 0.08 = 1.50 - 0.40 - 0.08 = 1.02R
    assert dossier["expected_value_r"] >= 0.85
    assert dossier["sniper"]["status"] == "LASER_ENTRY"


def test_predatory_cross_desk_calibration_and_strike_clock():
    """Verify that compile_predatory_pipeline_dossier stamps Cross-Desk Calibration and Strike Clock."""
    auditor = AlertScrutinyAuditor()
    mock_alert = SimpleNamespace(
        alert_id="aa-orb-tata-20261014",
        symbol="TATASTEEL",
        alert_type="ORB_BREAKOUT",
        direction="BULLISH",
        ltp=160.0,
        stop_loss=156.0,
        target_level=170.0,
        trigger_level=160.0,
        environment="REAL",
        is_live=True,
        metrics={"nifty_change_pct": -0.65},
    )

    # 1. Non-decoupled equity setup under active Nifty liquidation -> THROTTLED
    flags_throttled = {"no_chase": True, "nifty_change_pct": -0.65, "decoupler_status": "NONE"}
    dossier = auditor.compile_predatory_pipeline_dossier(mock_alert, flags_throttled)

    assert "cross_desk" in dossier
    cd = dossier["cross_desk"]
    assert cd["seat"] == "🏛️ CROSS-DESK CALIBRATION"
    assert cd["nifty_posture"] == "LIQUIDATION_DUMP"
    assert cd["status"] == "INDEX_HEADWIND_THROTTLED"
    assert "strike_clock_zone" in cd
    assert cd["strike_clock_efficiency"] > 0

    # 2. Verified decoupler under Nifty liquidation -> PASS
    flags_decoupled = {
        "no_chase": True,
        "nifty_change_pct": -0.65,
        "decoupler_status": "VERIFIED_DECOUPLER",
    }
    dossier_dec = auditor.compile_predatory_pipeline_dossier(mock_alert, flags_decoupled)
    assert dossier_dec["cross_desk"]["status"] != "INDEX_HEADWIND_THROTTLED"


def test_predatory_position_sizing_timing_calibration():
    """Verify that predatory strike clock kill zones dynamically calibrate position sizing."""
    from engine.position_sizer import calculate_position_size_for_alert

    # Baseline position sizing
    base_res = calculate_position_size_for_alert(
        symbol="NIFTY",
        entry_price=25000.0,
        stop_loss=24900.0,
        alert_type="ORB_BREAKOUT",
        capital=500000.0,
        max_risk_pct=1.0,
        is_fno=True,
    )

    # Lunchtime chop zone sizing dampener (0.75x)
    chop_res = calculate_position_size_for_alert(
        symbol="NIFTY",
        entry_price=25000.0,
        stop_loss=24900.0,
        alert_type="ORB_BREAKOUT",
        capital=500000.0,
        max_risk_pct=1.0,
        is_fno=True,
        strike_clock_zone="LUNCHTIME_CHOP_ZONE",
    )

    # Power hour sizing boost (1.10x)
    power_res = calculate_position_size_for_alert(
        symbol="NIFTY",
        entry_price=25000.0,
        stop_loss=24900.0,
        alert_type="ORB_BREAKOUT",
        capital=500000.0,
        max_risk_pct=1.0,
        is_fno=True,
        strike_clock_zone="AFTERNOON_GAMMA_POWER_HOUR",
    )

    assert chop_res.lots <= base_res.lots
    assert power_res.lots >= base_res.lots


def test_trade_lifecycle_manager_records_target_milestones_as_wins_in_circuit_breaker(tmp_path):
    """Regression test: Milestone wins (T0_5, T1, T2, TARGET) MUST record as WIN in circuit breaker."""
    from engine.detector_circuit_breaker import DetectorCircuitBreaker
    import engine.detector_circuit_breaker
    from unittest.mock import patch

    ledger = tmp_path / "cb_milestone_test.json"
    cb = DetectorCircuitBreaker(ledger_file=ledger, min_samples=3)

    with patch.object(engine.detector_circuit_breaker, "detector_circuit_breaker", cb):
        mgr = TradeLifecycleManager()

        mock_alert = SimpleNamespace(
            alert_id="aa-orb-test-20261014",
            symbol="SENSEX",
            contract_symbol=None,
            alert_type="ORB_PRIMED",
            direction="BEARISH",
            trigger_level=300.0,
            stop_loss=250.0,
            target_level=450.0,
            ltp=380.0,
            metrics={},
            actionable_plan={"stop_loss": 250.0},
            environment="TEST",
            is_live=False,
            achieved_milestones=[],
            stage="ACTIVE",
        )

        eval_res = SimpleNamespace(
            should_trail=True,
            trailing_decision="SCALE_35_TRAIL_BREAKEVEN",
            recommended_stop=302.3,
            trailing_rationale="Target 0.5 reached",
            locked_profit_pts=2.3,
            locked_profit_pct=0.2,
            target_status="T0_5_ACHIEVED",
            r_multiple=1.0,
            pnl_pct=26.0,
            strike_roll_recommendation=None,
            new_milestone="T0_5_ACHIEVED",
        )

        mgr.apply_milestone_state(
            alert=mock_alert,
            eval_res=eval_res,
            cur_quote_ltp=380.0,
            now_ts=1728711300.0,
            now_str="2026-10-14 11:38:00 IST",
        )

        # Check circuit breaker history
        assert cb.get_metrics("ORB_PRIMED") is not None
        records = list(cb._history.get("ORB_PRIMED", []))
        assert len(records) == 1
        assert records[0].outcome == "WIN"
        assert records[0].realized_r == 1.0
