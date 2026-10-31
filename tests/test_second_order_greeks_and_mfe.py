# -*- coding: utf-8 -*-
"""
tests/test_second_order_greeks_and_mfe.py
─────────────────────────────────────────
Test suite for Second-Order Options Cross Greeks (Gamma, Vega, Theta, Vanna, Charm),
Continuous In-Flight MAE / MFE excursion metrics, and 1-Click Emergency Flatten All
with session drawdown circuit breaker lockout.
"""

from __future__ import annotations


from engine.options_backtest import (
    bs_gamma,
    bs_vega,
    bs_theta,
    bs_vanna,
    bs_charm,
    bs_all_greeks,
)
from engine.greeks_manager import black_scholes_price_and_greeks
from engine.trade_lifecycle import compute_trade_excursion, audit_position_lifecycle
from engine.order_lifecycle import (
    emergency_flatten_all_positions,
    is_emergency_lockout_active,
    clear_emergency_lockout,
)


def test_second_order_greeks_mathematical_bounds():
    """Verify first- and second-order Greeks follow standard mathematical properties."""
    spot = 24500.0
    strike = 24500.0  # ATM
    dte = 3
    iv = 0.15

    # Gamma must be positive and non-zero
    gamma = bs_gamma(spot, strike, dte, iv)
    assert gamma > 0.0

    # Vega must be positive
    vega = bs_vega(spot, strike, dte, iv)
    assert vega > 0.0

    # Theta must be negative (time decay hurts long option)
    theta_ce = bs_theta(spot, strike, dte, iv, "CE")
    theta_pe = bs_theta(spot, strike, dte, iv, "PE")
    assert theta_ce < 0.0
    assert theta_pe < 0.0

    # Vanna and Charm
    vanna = bs_vanna(spot, strike, dte, iv)
    charm_ce = bs_charm(spot, strike, dte, iv, "CE")
    assert isinstance(vanna, float)
    assert isinstance(charm_ce, float)


def test_bs_all_greeks_and_greeks_manager_parity():
    """Verify closed-form parity between options_backtest and greeks_manager."""
    spot = 24500.0
    strike = 24650.0  # OTM Call
    dte = 2
    iv = 0.14

    all_g = bs_all_greeks(spot, strike, dte, iv, "CE")
    gm_g = black_scholes_price_and_greeks(
        spot=spot,
        strike=strike,
        time_to_expiry_years=dte / 365.0,
        volatility=iv,
        option_type="CE",
    )

    # Core Greeks must agree
    assert abs(all_g["delta"] - gm_g["delta"]) < 0.01
    assert abs(all_g["gamma"] - gm_g["gamma"]) < 0.0005
    assert abs(all_g["vega"] - gm_g["vega"]) < 0.2
    assert abs(all_g["theta"] - gm_g["theta"]) < 0.2
    assert abs(all_g["vanna"] - gm_g["vanna"]) < 0.001
    assert abs(all_g["charm"] - gm_g["charm"]) < 0.01


def test_compute_trade_excursion_long():
    """Verify MFE, MAE, and Execution Efficiency Ratio (EER) for long trade."""
    res = compute_trade_excursion(
        entry_price=100.0,
        initial_stop_loss=90.0,  # 10 pts risk
        high_watermark=130.0,  # Peak MFE +30 pts (+3.0R)
        low_watermark=95.0,  # Deepest MAE -5 pts (-0.5R)
        current_ltp=125.0,  # Current PnL +25 pts
        position_type="LONG",
    )

    assert res["mfe_pts"] == 30.0
    assert res["mfe_r"] == 3.0
    assert res["mae_pts"] == 5.0
    assert res["mae_r"] == 0.5
    # EER = 25 / 30 = 0.8333
    assert res["execution_efficiency_ratio"] == round(25.0 / 30.0, 4)


def test_compute_trade_excursion_short():
    """Verify MFE, MAE, and Execution Efficiency Ratio (EER) for short trade."""
    res = compute_trade_excursion(
        entry_price=200.0,
        initial_stop_loss=210.0,  # 10 pts risk
        high_watermark=205.0,  # Deepest MAE -5 pts (-0.5R)
        low_watermark=160.0,  # Peak MFE +40 pts (+4.0R)
        current_ltp=170.0,  # Current PnL +30 pts
        position_type="SHORT",
    )

    assert res["mfe_pts"] == 40.0
    assert res["mfe_r"] == 4.0
    assert res["mae_pts"] == 5.0
    assert res["mae_r"] == 0.5
    # EER = 30 / 40 = 0.75
    assert res["execution_efficiency_ratio"] == 0.75


def test_position_lifecycle_report_excursion_enrichment():
    """Audit position lifecycle should enrich PositionLifecycleReport with excursion analytics."""
    rep = audit_position_lifecycle(
        symbol="NIFTY",
        entry_price=24500.0,
        initial_stop_loss=24400.0,
        current_ltp=24750.0,
        high_watermark=24800.0,
        low_watermark=24450.0,
        position_type="LONG",
    )

    assert rep.peak_mfe_pts == 300.0  # 24800 - 24500
    assert rep.peak_mfe_r == 3.0  # 300 / 100
    assert rep.peak_mae_pts == 50.0  # 24500 - 24450
    assert rep.peak_mae_r == 0.5  # 50 / 100
    assert rep.execution_efficiency_ratio == round(250.0 / 300.0, 4)


def test_emergency_flatten_all_and_circuit_breaker():
    """Verify emergency flatten cancels orders, liquidates positions, and activates 60-min lockout."""
    clear_emergency_lockout()
    assert is_emergency_lockout_active()[0] is False

    res = emergency_flatten_all_positions(actor="TEST_RUNNER", reason="SAFETY_VERIFICATION")
    assert res["status"] == "SUCCESS"
    assert "cancelled_orders_count" in res
    assert "flattened_positions_count" in res

    # Lockout must now be active
    is_locked, remaining_seconds = is_emergency_lockout_active()
    assert is_locked is True
    assert remaining_seconds > 3500.0

    # Cleanup after test
    clear_emergency_lockout()
    assert is_emergency_lockout_active()[0] is False
