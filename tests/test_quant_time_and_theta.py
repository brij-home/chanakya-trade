"""
tests/test_quant_time_and_theta.py
==================================
Regression test suite for Task P3-A and Task P3-B:
1. 0-DTE time-to-close resolution in analysis/options.py.
2. Black-Scholes put theta analytical formula.
3. Half-Kelly sizing fail-closed on non-positive edge.
"""

from datetime import datetime
import pytest
from config.constants import IST_ZONE
from analysis.options import _dte_years, _bs_greeks_manual
from engine.position_sizer import calculate_position_size


def test_0dte_intraday_resolution(monkeypatch):
    """Expiry day contracts must compute intraday fractional year, not 0 or 1-day floor."""
    # 2026-11-03 at 14:30 IST -> 60 minutes remaining of 375 minutes in trading session
    sample_now = datetime(2026, 11, 3, 14, 30, tzinfo=IST_ZONE)

    import config.constants

    monkeypatch.setattr(config.constants, "now_ist", lambda: sample_now)

    t_0dte = _dte_years("2026-11-03")
    assert t_0dte > 0.0
    # Expected T = (60 / 375) / 365 = 0.16 / 365 ~ 0.000438
    expected_t = (60.0 / 375.0) / 365.0
    assert pytest.approx(t_0dte, rel=1e-3) == expected_t

    # Expired contract must return 0.0
    t_expired = _dte_years("2026-11-02")
    assert t_expired == 0.0


def test_bs_put_theta_formula():
    """Put theta must be mathematically consistent with Black-Scholes analytical formula."""
    # ATM Put: Spot=100, Strike=100, T=0.1, r=0.065, price=2.5, PE
    greeks_put = _bs_greeks_manual(
        S=100.0,
        K=100.0,
        T=0.1,
        r=0.065,
        price=2.5,
        option_type="PE",
    )
    # ATM Call: Spot=100, Strike=100, T=0.1, r=0.065, price=2.5, CE
    greeks_call = _bs_greeks_manual(
        S=100.0,
        K=100.0,
        T=0.1,
        r=0.065,
        price=2.5,
        option_type="CE",
    )
    # By put-call parity differentiation with respect to T:
    # Theta_put = Theta_call + r * K * exp(-rT)
    # Since r > 0, Theta_put is greater than (less negative than) Theta_call
    assert greeks_put.theta > greeks_call.theta
    assert greeks_put.delta < 0.0  # Long put delta must be negative


def test_half_kelly_allocates_zero_on_negative_edge():
    """Negative expectancy edge must allocate 0 shares under Half-Kelly sizing."""
    # Win rate 30% (0.30) and 1:1 payoff (profit_factor 1.0) -> edge is 0.3 * 1 - 0.7 = -0.4 (negative)
    res = calculate_position_size(
        symbol="RELIANCE",
        entry_price=2500.0,
        stop_loss=2450.0,
        capital=200_000.0,
        sizing_model="half_kelly",
        win_rate=0.30,
        profit_factor=1.0,
    )
    assert res.shares == 0
    assert res.lots == 0
    assert res.capital_allocated == 0.0
    assert "Non-positive edge" in res.notes or "zero capital" in res.notes.lower()
