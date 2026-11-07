"""
tests/test_payoff_and_token_refresh.py
──────────────────────────────────────
Verification of Phase 4 Transformations:
1. Multi-leg Option Strategy Payoff Visualizer API (POST /api/options/payoff).
2. Theoretical T+0 curve calculation with Black-Scholes and simulated IV shift.
3. Accurate Indian statutory friction breakdown (STT, GST, brokerage).
4. Aggregated Portfolio Greeks (Delta, Gamma, Theta, Vega).
5. Constant-tenor IV surface API endpoint (GET /api/options/surface/{symbol}).
6. Autonomous daily morning broker token refresh scheduler (06:15 - 07:30 IST).
"""

from __future__ import annotations

import pytest

from analysis.options import PayoffLeg, payoff, black_scholes_price
from engine.data_sync_scheduler import DataSyncScheduler


def test_black_scholes_analytical_pricing():
    """Verify Black-Scholes analytical call and put pricing."""
    # Spot=100, Strike=100, T=1.0 year, r=0.065, vol=0.20
    c_price = black_scholes_price(
        spot=100.0, strike=100.0, t_years=1.0, rate=0.065, vol=0.20, option_type="CE"
    )
    p_price = black_scholes_price(
        spot=100.0, strike=100.0, t_years=1.0, rate=0.065, vol=0.20, option_type="PE"
    )

    # Put-Call Parity: C - P = S - K * exp(-r * T)
    # 100 - 100 * exp(-0.065) ~ 100 - 93.7067 = 6.293
    assert c_price > 0
    assert p_price > 0
    assert c_price > p_price
    diff = c_price - p_price
    expected_parity = 100.0 - 100.0 * 0.937067
    assert diff == pytest.approx(expected_parity, abs=0.1)


def test_payoff_t0_curve_and_friction_calculation():
    """Verify payoff computes both expiry and theoretical T+0 curves with statutory friction."""
    legs = [
        PayoffLeg("CE", "BUY", 24000.0, 150.0, lot_size=25, lots=1, iv=0.16, dte=7),
        PayoffLeg("CE", "SELL", 24200.0, 60.0, lot_size=25, lots=1, iv=0.15, dte=7),
    ]

    res = payoff(legs, spot_range=(23500.0, 24500.0), steps=21, iv_shift_pct=1.0)
    assert res.max_profit > 0
    assert res.max_loss < 0
    assert len(res.payoff) == 21
    assert len(res.t0_payoff) == 21

    # Check friction breakdown
    assert "total_statutory_friction" in res.friction_breakdown
    assert res.friction_breakdown["total_statutory_friction"] > 0
    assert res.net_max_profit < res.max_profit
    assert res.net_max_loss < res.max_loss

    # Check net greeks
    assert "portfolio_delta" in res.net_greeks
    assert "portfolio_theta" in res.net_greeks


@pytest.mark.anyio
async def test_payoff_api_endpoint():
    """Verify POST /api/options/payoff endpoint."""
    from web.routers.market_data import post_options_payoff_endpoint

    payload = {
        "underlying": "NIFTY",
        "spot": 24000.0,
        "legs": [
            {
                "option_type": "CE",
                "transaction": "BUY",
                "strike": 24000.0,
                "premium": 150.0,
                "lot_size": 25,
                "lots": 1,
                "iv": 0.16,
                "dte": 7,
            },
            {
                "option_type": "CE",
                "transaction": "SELL",
                "strike": 24300.0,
                "premium": 50.0,
                "lot_size": 25,
                "lots": 1,
                "iv": 0.15,
                "dte": 7,
            },
        ],
        "steps": 25,
        "iv_shift_pct": 0.0,
    }

    res = await post_options_payoff_endpoint(payload)
    assert res["status"] == "ok"
    assert res["underlying"] == "NIFTY"
    assert res["spot"] == 24000.0
    assert res["max_profit"] > 0
    assert res["max_loss"] < 0
    assert len(res["payoff"]) == 25
    assert len(res["breakevens"]) >= 1
    assert res["net_max_profit"] < res["max_profit"]


@pytest.mark.anyio
async def test_options_surface_api_endpoint():
    """Verify GET /api/options/surface/{symbol} endpoint returns authentic fail-closed structure."""
    from web.routers.market_data import get_options_surface_endpoint

    res = await get_options_surface_endpoint("NON_EXISTENT_TICKER")
    assert res["status"] == "ok"
    assert "data" in res
    assert res["data"]["status"] == "UNAVAILABLE"
    assert res["data"]["atm_iv_30d"] is None


def test_data_sync_scheduler_broker_token_refresh():
    """Verify DataSyncScheduler.sync_broker_tokens runs without crashing and tracks session date."""
    scheduler = DataSyncScheduler()
    status_before = scheduler.get_sync_status()
    assert "last_token_refresh_date" in status_before
    assert status_before["last_token_refresh_date"] is None

    # Run with force=True in hermetic test mode
    res = scheduler.sync_broker_tokens(force=True)
    assert res["status"] in ("SUCCESS", "PARTIAL")
    assert "session_date" in res

    status_after = scheduler.get_sync_status()
    assert status_after["last_token_refresh_date"] == res["session_date"]
