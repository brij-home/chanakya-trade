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
    """Expiry day contracts must compute intraday fractional year using effective-dated session close."""
    import config.constants

    # 2026-11-03 (CAS Phase 1: derivative_close = 15:40 IST -> 385 mins total) at 14:30 IST -> 70 mins remaining
    sample_now_nov = datetime(2026, 11, 3, 14, 30, tzinfo=IST_ZONE)
    monkeypatch.setattr(config.constants, "now_ist", lambda: sample_now_nov)

    t_0dte_nov = _dte_years("2026-11-03")
    assert t_0dte_nov > 0.0
    expected_t_nov = (70.0 / 385.0) / 365.0
    assert pytest.approx(t_0dte_nov, rel=1e-3) == expected_t_nov

    # 2026-12-08 (Post-Dec 7 CAS: expiring index closes 15:30 IST -> 375 mins total) at 14:30 IST -> 60 mins remaining
    sample_now_dec = datetime(2026, 12, 8, 14, 30, tzinfo=IST_ZONE)
    monkeypatch.setattr(config.constants, "now_ist", lambda: sample_now_dec)

    t_0dte_dec = _dte_years("2026-12-08")
    assert t_0dte_dec > 0.0
    expected_t_dec = (60.0 / 375.0) / 365.0
    assert pytest.approx(t_0dte_dec, rel=1e-3) == expected_t_dec

    # Expired contract must return 0.0
    t_expired = _dte_years("2026-12-07")
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
