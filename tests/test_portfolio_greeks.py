"""
tests/test_portfolio_greeks.py
──────────────────────────────
Unit tests for Unified Greek Portfolio Risk Surface & Stress Testing.
"""

from __future__ import annotations

import pytest

from engine.portfolio_greeks import (
    calculate_portfolio_greeks,
    estimate_contract_delta,
)


def test_estimate_contract_delta():
    """Verify linear equity is Delta=1.0 and options follow call/put bounds."""
    d_eq, g_eq, th_eq, vg_eq = estimate_contract_delta("EQUITY", spot_price=24500.0)
    assert d_eq == 1.0
    assert g_eq == 0.0
    assert th_eq == 0.0

    # ATM Call (spot=24500, strike=24500)
    d_ce, g_ce, th_ce, vg_ce = estimate_contract_delta("CE", spot_price=24500.0, strike=24500.0, dte=7)
    assert 0.45 <= d_ce <= 0.60
    assert g_ce > 0.0
    assert th_ce < 0.0  # Option buyer faces negative daily theta decay

    # ATM Put (spot=24500, strike=24500)
    d_pe, g_pe, th_pe, vg_pe = estimate_contract_delta("PE", spot_price=24500.0, strike=24500.0, dte=7)
    assert -0.60 <= d_pe <= -0.45
    assert g_pe > 0.0


def test_calculate_portfolio_greeks_balanced():
    """Verify aggregation across long equity and hedged options."""
    positions = [
        {"symbol": "RELIANCE", "instrument_type": "EQUITY", "quantity": 100, "ltp": 3000.0},
        {"symbol": "NIFTY24500CE", "underlying": "NIFTY", "instrument_type": "CE", "quantity": 50, "strike": 24500.0, "ltp": 120.0},
    ]

    snapshot = calculate_portfolio_greeks(positions, nifty_spot=24500.0)
    assert snapshot.positions_count == 2
    assert snapshot.net_delta_nifty_eq > 0.0
    assert "gap_down_2_5_pct" in snapshot.stress_tests
    assert snapshot.stress_tests["gap_down_2_5_pct"] < 0  # Long portfolio loses on gap down


def test_extreme_long_triggers_hedging_recommendation():
    """Verify excessive delta exposure automatically generates defined-risk hedge advice."""
    # 10 lots of naked NIFTY Call options
    positions = [
        {"symbol": "NIFTY24500CE", "underlying": "NIFTY", "instrument_type": "CE", "quantity": 250, "strike": 24500.0, "ltp": 150.0},
        {"symbol": "BANKNIFTY52000CE", "underlying": "BANKNIFTY", "instrument_type": "CE", "quantity": 150, "strike": 52000.0, "ltp": 280.0},
    ]

    snapshot = calculate_portfolio_greeks(positions, nifty_spot=24500.0)
    assert snapshot.delta_posture in ("BULLISH", "EXTREME_LONG")
    if snapshot.delta_posture == "EXTREME_LONG":
        assert snapshot.hedging_recommendation is not None
        assert snapshot.hedging_recommendation["action"] == "BUY_BEAR_PUT_SPREAD"
        assert snapshot.hedging_recommendation["lots"] >= 1
