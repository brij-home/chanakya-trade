"""
tests/test_event_volatility.py
──────────────────────────────
Institutional test suite for Defined-Risk Event Volatility & Hedged Earnings Intelligence.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from analysis.event_volatility import (
    detect_upcoming_earnings_window,
    evaluate_event_volatility_strategy,
)
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.trade_plan import calculate_option_execution_plan


def test_earnings_window_detection():
    """Verifies quarterly earnings window scheduling logic."""
    # RELIANCE typically reports in Jan (1), Apr (4), Jul (7), Oct (10)
    # Check date inside earnings reporting window (e.g., Oct 18)
    is_event, h_to_event, event_date = detect_upcoming_earnings_window(
        "RELIANCE", ref_date=date(2026, 10, 18)
    )
    assert is_event is True
    assert h_to_event <= 48.0
    assert event_date == "2026-10-18"

    # Off-season date (e.g., Feb 5)
    is_event_off, h_off, _ = detect_upcoming_earnings_window("RELIANCE", ref_date=date(2026, 2, 5))
    assert is_event_off is False
    assert h_off > 100.0


def test_high_iv_earnings_deploys_vertical_spread():
    """
    When IV Rank >= 50%, options are overpriced due to earnings uncertainty.
    Deploying Bull Call or Bear Put Spreads harvests IV crush as pure profit.
    """
    # 1. Bullish scenario on RELIANCE (Spot 3000, IV Rank 75)
    plan_bull = evaluate_event_volatility_strategy(
        symbol="RELIANCE",
        spot=3000.0,
        direction="BULLISH",
        hours_to_event=20.0,
        iv_rank_override=75.0,
    )

    assert plan_bull is not None
    assert plan_bull.volatility_regime == "OVERPRICED_IV"
    assert plan_bull.recommended_strategy == "BULL_CALL_SPREAD"
    assert plan_bull.iv_crush_neutralized is True
    assert len(plan_bull.legs) == 2
    assert plan_bull.legs[0].action == "BUY" and plan_bull.legs[0].option_type == "CE"
    assert plan_bull.legs[1].action == "SELL" and plan_bull.legs[1].option_type == "CE"
    assert plan_bull.legs[1].strike > plan_bull.legs[0].strike  # OTM short leg
    assert plan_bull.max_risk_pts > 0
    assert plan_bull.max_reward_pts > plan_bull.max_risk_pts
    assert "IV CRUSH HARVESTER" in plan_bull.rationale

    # 2. Bearish scenario on INFY (Spot 1800, IV Rank 65)
    plan_bear = evaluate_event_volatility_strategy(
        symbol="INFY",
        spot=1800.0,
        direction="BEARISH",
        hours_to_event=12.0,
        iv_rank_override=65.0,
    )

    assert plan_bear is not None
    assert plan_bear.recommended_strategy == "BEAR_PUT_SPREAD"
    assert plan_bear.legs[0].action == "BUY" and plan_bear.legs[0].option_type == "PE"
    assert plan_bear.legs[1].action == "SELL" and plan_bear.legs[1].option_type == "PE"
    assert plan_bear.legs[1].strike < plan_bear.legs[0].strike


def test_low_iv_earnings_deploys_long_straddle():
    """
    When IV Rank < 40%, options market is underpricing historical earnings move.
    Deploying Long Straddles captures explosive breakout with positive statistical edge.
    """
    plan = evaluate_event_volatility_strategy(
        symbol="TCS",
        spot=4000.0,
        direction="BULLISH",
        hours_to_event=18.0,
        iv_rank_override=28.0,
    )

    assert plan is not None
    assert plan.volatility_regime == "UNDERPRICED_IV"
    assert plan.recommended_strategy == "LONG_STRADDLE"
    assert len(plan.legs) == 2
    # Both legs are bought (ATM CE + ATM PE)
    assert plan.legs[0].action == "BUY" and plan.legs[0].option_type == "CE"
    assert plan.legs[1].action == "BUY" and plan.legs[1].option_type == "PE"
    assert plan.legs[0].strike == plan.legs[1].strike
    assert "UNDERPRICED VOLATILITY SQUEEZE" in plan.rationale


def test_trade_plan_integrates_event_hedge():
    """Verify calculate_option_execution_plan attaches event_hedge_plan."""
    opt_plan = calculate_option_execution_plan(
        option_type="CE",
        strike=3000.0,
        option_ltp=45.0,
        spot=3000.0,
        contract_symbol="RELIANCE",
    )

    assert "hedged_spread" in opt_plan
    assert "event_hedge_plan" in opt_plan
    # RELIANCE in active earnings window produces valid event_hedge_plan
    eh = opt_plan.get("event_hedge_plan")
    if eh:
        assert eh.get("symbol") == "RELIANCE"
        assert eh.get("recommended_strategy") in ("BULL_CALL_SPREAD", "LONG_STRADDLE")


def test_alert_scrutiny_event_hedge_bonus(monkeypatch):
    """Verify AlertScrutinyAuditor recognizes event hedge plan and approves with bonus."""
    auditor = AlertScrutinyAuditor(min_rr_ratio=1.5)
    monkeypatch.setattr(auditor, "_execute_fast_llm_scrutiny", lambda *args, **kwargs: None)

    # Pre-configure event hedge on alert
    event_plan = evaluate_event_volatility_strategy(
        symbol="RELIANCE",
        spot=3000.0,
        direction="BULLISH",
        hours_to_event=15.0,
        iv_rank_override=70.0,
    )

    alert = SimpleNamespace(
        symbol="RELIANCE",
        ltp=3000.0,
        trigger_level=3000.0,
        stop_loss=2960.0,
        target_level=3120.0,
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        rvol=2.2,
        environment="TEST",
        is_live=False,
        alert_id="test-ev-1",
        metrics={"event_hedge_plan": event_plan.to_dict() if event_plan else None},
    )

    res = auditor.scrutinize_alert(alert)
    assert res.status == "APPROVED"
    assert res.score >= 80
    assert alert.metrics.get("event_hedge_plan") is not None
    assert alert.metrics["predatory_pipeline"].get("event_hedge") is not None
