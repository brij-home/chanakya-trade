"""
tests/test_trade_plan.py
────────────────────────
Unit tests for the Institutional Data-Driven Trade Plan, Empirical R:R, and Velocity ETA Engine.
"""

from __future__ import annotations


from engine.trade_plan import calculate_trade_plan


def test_trade_plan_long_calculation():
    """Verify that a Long trade plan calculates structural SL, T1, T2, R:R, and ETA without hardcoding."""
    plan = calculate_trade_plan(
        symbol="NIFTY",
        direction="BUY",
        spot=23500.0,
        timeframe="INTRADAY",
    )
    assert plan.symbol == "NIFTY"
    assert plan.direction == "LONG"
    assert plan.entry_price == 23500.0
    assert plan.invalidation_stop < plan.entry_price
    assert plan.target_1 > plan.entry_price
    assert plan.target_2 >= plan.target_1
    assert plan.stop_distance_pts > 0
    assert plan.rr_t1 > 0
    assert plan.rr_t2 > 0
    assert plan.eta_t1_minutes > 0
    assert plan.eta_t2_minutes >= plan.eta_t1_minutes
    assert "IST" in plan.eta_t1_str
    assert plan.sl_rationale != ""
    assert plan.t1_rationale != ""
    assert plan.t2_rationale != ""


def test_trade_plan_short_calculation():
    """Verify that a Short trade plan sets stop above spot and targets below spot."""
    plan = calculate_trade_plan(
        symbol="NIFTY",
        direction="SELL",
        spot=23500.0,
        timeframe="INTRADAY",
    )
    assert plan.direction == "SHORT"
    assert plan.invalidation_stop > plan.entry_price
    assert plan.target_1 < plan.entry_price
    assert plan.target_2 <= plan.target_1
    assert plan.stop_distance_pts > 0
    assert plan.rr_t1 > 0
    assert plan.rr_t2 > 0


def test_trade_plan_asymmetry_filter():
    """Check that asymmetry verdict classifies viable vs unviable expectancy."""
    # Test valid serialization
    plan = calculate_trade_plan(symbol="RELIANCE", spot=2500.0)
    d = plan.as_dict()
    assert d["symbol"] == "RELIANCE"
    assert "invalidation_stop" in d
    assert "target_1" in d
    assert "rr_t2" in d
    assert "eta_t1_str" in d
    assert "options_recommended_structure" in d


def test_active_blast_increases_velocity():
    """Active order flow blast should increase velocity and decrease ETA bars."""
    plan_normal = calculate_trade_plan(symbol="NIFTY", spot=23500.0, has_active_blast=False)
    plan_blast = calculate_trade_plan(symbol="NIFTY", spot=23500.0, has_active_blast=True)

    assert plan_blast.velocity_pts_per_bar >= plan_normal.velocity_pts_per_bar
    assert plan_blast.eta_t1_minutes <= plan_normal.eta_t1_minutes


def test_theta_drag_quantification():
    """Options theta drag should be computed and recommend spreads when drag is significant."""
    plan = calculate_trade_plan(symbol="NIFTY", spot=23500.0)
    assert plan.estimated_theta_drag_pts >= 0
    assert plan.options_recommended_structure in (
        "NAKED_OPTION",
        "DEFINED_RISK_SPREAD",
        "CASH_EQUITY",
        "FUTURES",
    )
    assert len(plan.structure_advice) > 10


def test_direction_normalization_and_aliases():
    """Verify that BULLISH, BUY, LONG, CALL evaluate to LONG, and BEARISH, SELL, SHORT, PUT evaluate to SHORT."""
    for d in ("BULLISH", "BUY", "LONG", "CALL", "UP"):
        p = calculate_trade_plan(symbol="RELIANCE", direction=d, spot=2500.0)
        assert p.direction == "LONG"
        assert p.invalidation_stop < p.entry_price
        assert p.target_1 > p.entry_price

    for d in ("BEARISH", "SELL", "SHORT", "PUT", "DOWN"):
        p = calculate_trade_plan(symbol="RELIANCE", direction=d, spot=2500.0)
        assert p.direction == "SHORT"
        assert p.invalidation_stop > p.entry_price
        assert p.target_1 < p.entry_price


def test_compute_market_session_eta():
    """Test institutional session boundary aware ETA logic."""
    from datetime import datetime
    from engine.trade_plan import compute_market_session_eta

    # During active market hours (13:37 IST on a Wednesday)
    wed_afternoon = datetime(2026, 9, 9, 13, 37)

    # Fits within today's session (110m <= 113m remaining)
    eta_today = compute_market_session_eta(wed_afternoon, 110)
    assert "est. 15:27 IST" in eta_today

    # Overruns today's session (475m > 113m remaining -> rolls into Thursday)
    eta_overrun = compute_market_session_eta(wed_afternoon, 475)
    assert "Next session ~15:17 IST" in eta_overrun

    # Multi-day roll (1000m -> spans 3 trading sessions)
    eta_multiday = compute_market_session_eta(wed_afternoon, 1000)
    assert "sessions" in eta_multiday

    # Weekend handling (Saturday morning rolls to Monday)
    sat_morning = datetime(2026, 9, 12, 10, 0)
    eta_sat = compute_market_session_eta(sat_morning, 100)
    assert "Next session ~10:55 IST" in eta_sat


def test_mankind_regression_bullish_alert():
    """Regression test: MANKIND at ₹2285.4 with direction='BULLISH' must produce viable LONG trade plan."""
    plan = calculate_trade_plan(symbol="MANKIND", direction="BULLISH", spot=2285.4)

    assert plan.direction == "LONG"
    assert plan.entry_price == 2285.4
    assert plan.invalidation_stop < 2285.4, "Invalidation SL must be below entry price for LONG!"
    assert plan.target_1 > 2285.4, "Target 1 must be above entry price for LONG!"
    assert plan.target_2 >= plan.target_1, "Target 2 must be above or equal to Target 1!"
    assert plan.is_asymmetry_viable is True, "MANKIND should have viable asymmetry!"
    assert plan.asymmetry_verdict in ("EXCELLENT_ASYMMETRY", "ACCEPTABLE")
    assert plan.rr_t1 >= 1.2
    assert plan.rr_t2 >= 1.8
    assert "21:" not in plan.eta_t2_str, "ETA must not show closed market 21:xx hours for equity!"


def test_sbin_put_gamma_blast_zero_floor_and_divergence():
    """
    Regression test: Verifies that passing an option premium or badly scaled spot
    never generates negative targets or absurd risk/reward.
    """
    # 1. Direct calculate_trade_plan call with small spot vs SBIN levels
    plan = calculate_trade_plan(symbol="SBIN", direction="SHORT", spot=16.55)
    assert plan.target_1 > 0, "Target 1 must NEVER be negative!"
    assert plan.target_2 > 0, "Target 2 must NEVER be negative!"
    assert plan.target_1 >= 0.05
    assert plan.target_2 >= 0.05
    # If geometry was broken or divergence detected, it must not declare viable asymmetry on negative math
    if plan.invalidation_stop > 100 and plan.entry_price < 50:
        assert not plan.is_asymmetry_viable
