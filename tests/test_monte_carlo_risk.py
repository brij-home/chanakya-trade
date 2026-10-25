"""
tests/test_monte_carlo_risk.py
──────────────────────────────
Unit tests for engine/monte_carlo_risk.py (10,000-Path Monte Carlo Portfolio Risk Simulator).
"""

import numpy as np
from engine.monte_carlo_risk import run_portfolio_monte_carlo


def test_empty_portfolio_returns_zero_risk():
    res = run_portfolio_monte_carlo(holdings={}, daily_volatilities={})
    assert res.portfolio_value == 0.0
    assert res.var_95_inr == 0.0
    assert res.cvar_95_inr == 0.0


def test_single_asset_monte_carlo_bounds():
    # ₹1,000,000 portfolio in RELIANCE with 1.5% daily volatility over 21 trading days (~1 month)
    res = run_portfolio_monte_carlo(
        holdings={"RELIANCE": 1_000_000.0},
        daily_volatilities={"RELIANCE": 0.015},
        time_horizon_days=21,
        num_paths=5_000,
        seed=42,
    )

    assert res.portfolio_value == 1_000_000.0
    assert res.var_95_inr > 0.0
    assert res.var_99_inr > res.var_95_inr  # 99% VaR must be strictly greater than 95% VaR
    assert res.cvar_95_inr >= res.var_95_inr  # CVaR (Expected Shortfall) must exceed VaR
    assert res.cvar_99_inr >= res.var_99_inr
    assert 0.0 <= res.probability_of_loss_pct <= 100.0
    assert res.median_max_drawdown_pct > 0.0


def test_correlated_multi_asset_diversification():
    # Compare 2 highly correlated assets vs 2 negatively correlated assets
    holdings = {"ASSET_A": 500_000.0, "ASSET_B": 500_000.0}
    vols = {"ASSET_A": 0.02, "ASSET_B": 0.02}

    # Case 1: Perfect positive correlation (+0.95)
    corr_pos = np.array([[1.0, 0.95], [0.95, 1.0]])
    res_pos = run_portfolio_monte_carlo(
        holdings=holdings,
        daily_volatilities=vols,
        correlation_matrix=corr_pos,
        time_horizon_days=21,
        num_paths=5_000,
        seed=100,
    )

    # Case 2: Negative correlation / hedging (-0.60)
    corr_neg = np.array([[1.0, -0.60], [-0.60, 1.0]])
    res_neg = run_portfolio_monte_carlo(
        holdings=holdings,
        daily_volatilities=vols,
        correlation_matrix=corr_neg,
        time_horizon_days=21,
        num_paths=5_000,
        seed=100,
    )

    # Hedged/negatively correlated portfolio MUST have significantly lower VaR and Drawdown
    assert res_neg.var_95_inr < res_pos.var_95_inr
    assert res_neg.median_max_drawdown_pct < res_pos.median_max_drawdown_pct
