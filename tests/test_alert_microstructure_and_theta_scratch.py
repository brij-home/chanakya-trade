"""
tests/test_alert_microstructure_and_theta_scratch.py
────────────────────────────────────────────────────
Deterministic verification of:
  1. Microstructure Level-2 Depth Enrichment, Bid-Ask Spread Friction & Execution Drag Modeling.
  2. ActionableBlueprint & AutoAlert execution friction badge and depth synchronization.
  3. 0DTE Afternoon Theta-Stagnation Scratch Bailout detection (Post-13:30 IST).
"""

from datetime import datetime
from unittest.mock import patch
import pytest

from config.constants import IST_ZONE as IST
from engine.alert_model import ActionableBlueprint, AutoAlert
from engine.detection_context import DetectionContext
from engine.alert_evaluator import evaluate_alert_in_flight_decay
from engine.auto_alert_engine import AutoAlertEngine
from market.order_book import get_depth_book, clear_depth_books


@pytest.fixture(autouse=True)
def clean_books():
    clear_depth_books()
    yield
    clear_depth_books()


def test_detection_context_microstructure_and_friction_badge():
    """Verify DetectionContext computes depth imbalance, slippage bps, and friction badge."""
    # 1. Wide spread scenario (> 1.5%)
    ctx_wide = DetectionContext(
        symbol="NIFTY26OCT25000CE",
        canonical_symbol="NIFTY",
        ltp=100.0,
        extra_metrics={
            "bid": 97.0,
            "ask": 103.0,  # spread = 6.0, spread_pct = 6.0% > 1.5%
            "obi_5": -0.45,
        },
    )
    assert ctx_wide.bid_ask_spread_pct == 6.0
    assert ctx_wide.order_book_depth_imbalance == -0.45
    assert ctx_wide.estimated_slippage_bps() == 600.0
    assert ctx_wide.execution_friction_badge == "⚠️ WIDE SPREAD — USE STRICT LIMIT"
    assert "WIDE BID-ASK SPREAD" in ctx_wide.liquidity_warning

    # 2. Tight prime spread scenario (<= 0.5%)
    ctx_tight = DetectionContext(
        symbol="NIFTY26OCT25000CE",
        canonical_symbol="NIFTY",
        ltp=200.0,
        extra_metrics={
            "bid": 199.6,
            "ask": 200.2,  # spread = 0.6, spread_pct = 0.3% <= 0.5%
            "obi_5": 0.60,
        },
    )
    assert ctx_tight.bid_ask_spread_pct == 0.3
    assert ctx_tight.order_book_depth_imbalance == 0.60
    assert ctx_tight.estimated_slippage_bps() == 30.0
    assert ctx_tight.execution_friction_badge == "⚡ PRIME LIQUIDITY — TIGHT SPREAD"
    assert ctx_tight.liquidity_warning is None

    # 3. Moderate liquid spread scenario (0.5% - 1.5%)
    ctx_mod = DetectionContext(
        symbol="RELIANCE",
        canonical_symbol="RELIANCE",
        ltp=2500.0,
        extra_metrics={
            "bid": 2490.0,
            "ask": 2510.0,  # spread = 20.0, spread_pct = 0.8%
            "obi_5": 0.15,
        },
    )
    assert ctx_mod.bid_ask_spread_pct == 0.8
    assert ctx_mod.execution_friction_badge == "✓ LIQUID — NORMAL DEPTH"


def test_actionable_blueprint_and_auto_alert_friction_sync():
    """Verify ActionableBlueprint and AutoAlert synchronize friction badges and depth fields."""
    bp = ActionableBlueprint(
        action="BUY_CALL",
        entry_range="₹140.0 – ₹145.0",
        trigger_level=142.0,
        invalidation_stop=110.0,
        target_1=200.0,
        target_2=260.0,
        execution_friction_badge="⚠️ WIDE SPREAD — USE STRICT LIMIT",
        bid_ask_spread_pct=2.4,
        estimated_slippage_bps=240.0,
        order_book_depth_imbalance=0.35,
    )
    d = bp.to_dict()
    assert d["execution_friction_badge"] == "⚠️ WIDE SPREAD — USE STRICT LIMIT"
    assert d["bid_ask_spread_pct"] == 2.4
    assert d["estimated_slippage_bps"] == 240.0
    assert d["order_book_depth_imbalance"] == 0.35

    # AutoAlert initialization syncing from actionable_plan
    alert = AutoAlert(
        alert_id="aa-test-friction-001",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Friction Test",
        summary="Testing friction sync",
        ltp=142.0,
        trigger_level=142.0,
        target_level=200.0,
        stop_loss=110.0,
        strike=25000.0,
        option_type="CE",
        actionable_plan=d,
    )
    assert alert.execution_friction_badge == "⚠️ WIDE SPREAD — USE STRICT LIMIT"
    assert alert.bid_ask_spread_pct == 2.4
    assert alert.estimated_slippage_bps == 240.0
    assert alert.order_book_depth_imbalance == 0.35


def test_auto_alert_engine_enriches_with_live_l2_depth():
    """Verify record_alert enriches incoming alert with real-time BisectDepthBook depth."""
    engine = AutoAlertEngine()

    # Pre-populate L2 book in memory for NIFTY26OCT25000CE
    book = get_depth_book("NIFTY26OCT25000CE")
    book.batch_update(
        bids=[{"price": 148.0, "quantity": 1200}, {"price": 147.5, "quantity": 1800}],
        asks=[{"price": 152.0, "quantity": 1500}, {"price": 152.5, "quantity": 2200}],
    )  # spread = 4.0 on 150.0 ltp -> 2.67% spread > 1.5%

    alert = AutoAlert(
        alert_id="aa-test-l2-enrich-002",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY26OCT25000CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 25000 CE Live Book",
        summary="Testing L2 enrichment",
        ltp=150.0,
        trigger_level=150.0,
        target_level=220.0,
        stop_loss=115.0,
        strike=25000.0,
        option_type="CE",
        created_at="2026-10-18 10:00:00 IST",
        environment="TEST",
        is_live=False,
    )

    try:
        success = engine.record_alert(alert)
        assert success is True

        # Alert should now have enriched L2 spread, OBI, and friction badge
        assert alert.bid_ask_spread_pct is not None
        assert alert.bid_ask_spread_pct == pytest.approx(2.67, 0.05)
        assert alert.order_book_depth_imbalance is not None
        assert alert.execution_friction_badge == "⚠️ WIDE SPREAD — USE STRICT LIMIT"
        assert (
            alert.actionable_plan.get("execution_friction_badge")
            == "⚠️ WIDE SPREAD — USE STRICT LIMIT"
        )
    finally:
        with engine._lock:
            engine._alerts = [a for a in engine._alerts if a.alert_id != "aa-test-l2-enrich-002"]
            engine._save()


def test_0dte_afternoon_theta_stagnation_scratch_bailout_evaluator():
    """Verify evaluate_alert_in_flight_decay triggers THETA_STAGNATION_SCRATCH on >=15m stagnation."""
    thursday_afternoon = datetime(2026, 9, 10, 14, 0, 0, tzinfo=IST)
    with patch("engine.alert_evaluator.datetime") as mock_dt:
        mock_dt.now.return_value = thursday_afternoon
        mock_dt.strptime.side_effect = datetime.strptime

        # 1. 16 minutes elapsed (960s >= 900s) post-13:30 IST on Thursday -> THETA_STAGNATION_SCRATCH
        alert_16m = AutoAlert(
            alert_id="0dte-scratch-1",
            alert_type="OPTIONS_MOMENTUM_BREAKOUT",
            stage="IGNITED",
            symbol="NIFTY",  # Thursday expiry = 0DTE
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty 0DTE Call",
            summary="0DTE testing",
            trigger_level=100.0,
            target_level=160.0,
            ltp=93.5,  # -6.5% P&L
            option_premium=100.0,
            stop_loss=70.0,
            option_type="CE",
            strike=24200,
            created_at="2026-09-10 13:44:00",
            is_live=True,
        )
        eval_res = evaluate_alert_in_flight_decay(alert_16m, current_ltp=93.5)
        assert eval_res is not None
        assert eval_res.triggered is True
        assert eval_res.warning_type == "THETA_STAGNATION_SCRATCH"
        assert eval_res.coaching_decision == "THETA_STAGNATION_SCRATCH"
        assert "[THETA SCRATCH BAILOUT]" in eval_res.headline
        assert "Scratch trade immediately" in eval_res.summary

        # 2. 9 minutes elapsed (< 15m) post-13:30 IST -> EXIT_0DTE_OPTION_IMMEDIATELY (preserving backward compatibility)
        alert_9m = AutoAlert(
            alert_id="0dte-cliff-9m",
            alert_type="OPTIONS_MOMENTUM_BREAKOUT",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty 0DTE Call",
            summary="0DTE testing",
            trigger_level=100.0,
            target_level=160.0,
            ltp=95.0,
            option_premium=100.0,
            stop_loss=70.0,
            option_type="CE",
            strike=24200,
            created_at="2026-09-10 13:51:00",
            is_live=True,
        )
        eval_9m_res = evaluate_alert_in_flight_decay(alert_9m, current_ltp=95.0)
        assert eval_9m_res is not None
        assert eval_9m_res.triggered is True
        assert eval_9m_res.coaching_decision == "EXIT_0DTE_OPTION_IMMEDIATELY"


def test_auto_alert_engine_check_in_flight_theta_stagnation_bailout():
    """Verify check_and_alert_in_flight_decay marks theta_scratch_recommended and audits scratch event."""
    engine = AutoAlertEngine()
    thursday_afternoon = datetime(2026, 9, 10, 14, 15, 0, tzinfo=IST)

    alert = AutoAlert(
        alert_id="aa-0dte-scratch-003",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        contract_symbol="NIFTY26SEP24200CE",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24200 CE 0DTE Ignition",
        summary="Impulse breakout",
        ltp=100.0,
        trigger_level=100.0,
        target_level=170.0,
        stop_loss=70.0,
        strike=24200.0,
        option_type="CE",
        underlying_spot=24210.0,
        created_at="2026-09-10 13:45:00 IST",  # 30 minutes elapsed (> 15m)
        is_live=True,
        environment="LIVE",
    )
    alert.target_status = "PENDING"

    with engine._lock:
        prior_alerts = list(engine._alerts)
        engine._alerts = [alert]

    try:
        with (
            patch("engine.alert_evaluator.datetime") as mock_dt1,
            patch("engine.auto_alert_engine.datetime") as mock_dt2,
        ):
            mock_dt1.now.return_value = thursday_afternoon
            mock_dt1.strptime.side_effect = datetime.strptime
            mock_dt2.now.return_value = thursday_afternoon
            mock_dt2.strptime.side_effect = datetime.strptime

            # Current quote is flat / stagnant at 94.0 (-6.0%)
            quotes_map = {"NFO:NIFTY26SEP24200CE": 94.0, "NSE:NIFTY": 24215.0}
            warnings = engine.check_and_alert_in_flight_decay(quotes_map=quotes_map)

        assert len(warnings) == 1
        w_alert = warnings[0]
        assert w_alert.theta_scratch_recommended is True
        assert w_alert.trailing_decision == "THETA_STAGNATION_SCRATCH"
        assert "[THETA SCRATCH BAILOUT]" in w_alert.headline
        assert "Scratch trade immediately" in w_alert.stagnation_bailout_reason

        # Audit trail verification
        audit_events = [a["event_type"] for a in w_alert.audit_trail]
        assert "THETA_STAGNATION_SCRATCH" in audit_events
    finally:
        with engine._lock:
            engine._alerts = prior_alerts


def test_create_test_in_flight_warning_scratch():
    """Verify create_test_in_flight_warning_alert generates test scratch bailout alert."""
    engine = AutoAlertEngine()
    test_alert = engine.create_test_in_flight_warning_alert(
        warning_type="SCRATCH",
        symbol="NIFTY",
    )
    assert test_alert.theta_scratch_recommended is True
    assert test_alert.trailing_decision == "THETA_STAGNATION_SCRATCH"
    assert "[THETA SCRATCH BAILOUT]" in test_alert.headline
    assert "-6.5%" in test_alert.summary
