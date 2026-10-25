"""
tests/test_market_impact.py
───────────────────────────
Unit tests for engine/market_impact.py (Almgren-Chriss Market Impact Model).
"""

import pytest
from engine.market_impact import calculate_almgren_chriss_impact


def test_small_order_impact_dominated_by_spread():
    # Buy 100 shares of RELIANCE @ 3000, ADV = 5,000,000 (0.002% of ADV)
    # Market impact should be minimal, mostly half-spread
    res = calculate_almgren_chriss_impact(
        symbol="RELIANCE",
        side="BUY",
        quantity=100,
        price=3000.0,
        adv=5_000_000,
        daily_volatility=0.015,
        half_spread_bps=2.0,  # 3000 * 0.0002 = 0.60
    )

    assert res.effective_fill_price > 3000.0
    assert res.half_spread_cost == pytest.approx(0.60, 0.01)
    # Total slippage on 100 shares should be very close to the half spread (sub-rupee)
    assert res.total_slippage_per_unit < 1.0


def test_large_block_order_exponential_impact():
    # Buy 500,000 shares of mid-cap stock @ 500, ADV = 1,000,000 (50% of ADV)
    # Substantial temporary and permanent impact expected
    res = calculate_almgren_chriss_impact(
        symbol="MIDCAP",
        side="BUY",
        quantity=500_000,
        price=500.0,
        adv=1_000_000,
        daily_volatility=0.025,
        half_spread_bps=5.0,
    )

    assert res.participation_of_adv_pct == 50.0
    assert res.permanent_impact > 1.0
    assert res.temporary_impact > 2.0
    assert res.effective_fill_price > 500.0 + res.half_spread_cost


def test_sell_order_impact_lowers_price():
    # Sell order pushes effective fill price DOWN
    res = calculate_almgren_chriss_impact(
        symbol="INFY",
        side="SELL",
        quantity=10_000,
        price=1800.0,
        adv=2_000_000,
    )

    assert res.effective_fill_price < 1800.0
    assert res.total_slippage_per_unit > 0.0
