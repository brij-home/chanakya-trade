"""
Unit tests for Black-Scholes-Merton pricing and Greeks for cash/index options.
"""

from engine.greeks_manager import black_scholes_price_and_greeks


def test_black_scholes_atm_call_and_put():
    """Verify ATM Call and Put pricing, Delta symmetry, and positive Vega."""
    spot = 25000.0
    strike = 25000.0
    dte_years = 7.0 / 365.0
    iv = 0.15

    call = black_scholes_price_and_greeks(spot, strike, dte_years, volatility=iv, option_type="CE")
    put = black_scholes_price_and_greeks(spot, strike, dte_years, volatility=iv, option_type="PE")

    # Call delta ~ 0.50, Put delta ~ -0.50
    assert 0.45 < call["delta"] < 0.60
    assert -0.60 < put["delta"] < -0.40
    # Put-Call Delta parity: Call Delta - Put Delta = 1.0
    assert abs((call["delta"] - put["delta"]) - 1.0) < 0.01

    # Vega and Gamma must be identical for European Call and Put with same strike
    assert call["vega"] == put["vega"]
    assert call["gamma"] == put["gamma"]
    assert call["gamma"] > 0
    assert call["vega"] > 0

    # Theta must be negative (decaying with time)
    assert call["theta"] < 0
    assert put["theta"] < 0


def test_black_scholes_deep_itm_otm():
    """Verify deep ITM and deep OTM behavior."""
    spot = 25000.0
    # Deep ITM Call (strike 20000)
    deep_itm_call = black_scholes_price_and_greeks(spot, 20000.0, 7.0 / 365.0, option_type="CE")
    assert deep_itm_call["delta"] > 0.98
    assert deep_itm_call["price"] >= 5000.0  # Intrinsic value S - K

    # Deep OTM Call (strike 30000)
    deep_otm_call = black_scholes_price_and_greeks(spot, 30000.0, 7.0 / 365.0, option_type="CE")
    assert deep_otm_call["delta"] < 0.02
    assert deep_otm_call["price"] < 1.0
