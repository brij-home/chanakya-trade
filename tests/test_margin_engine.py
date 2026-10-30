"""
tests/test_margin_engine.py
───────────────────────────
Unit tests for engine/margin_engine.py (SEBI 2026 Margin & Expiry ELM Engine).
"""

import pytest
from engine.margin_engine import (
    calculate_order_margin,
    validate_margin_solvency,
    SEBI_EXPIRY_ADDITIONAL_ELM_PCT,
)


def test_option_buyer_upfront_premium():
    # NIFTY 24500 CE, buy 1 lot (25 qty) @ ₹100
    req = calculate_order_margin(
        symbol="NIFTY24OCT24500CE",
        price=100.0,
        quantity=25,
        segment="OPTIONS",
        side="BUY",
        underlying_spot=24500.0,
    )
    # Option buyer requires 100% upfront premium (₹2500)
    assert req.upfront_premium == 2500.0
    assert req.total_margin_required == 2500.0
    assert req.expiry_additional_elm == 0.0
    assert not req.is_short_option


def test_option_seller_normal_day():
    # NIFTY 24500 CE, sell 1 lot (25 qty) @ ₹100, spot 24500 (Notional: 24500 * 25 = ₹612,500)
    req = calculate_order_margin(
        symbol="NIFTY24OCT24500CE",
        price=100.0,
        quantity=25,
        segment="OPTIONS",
        side="SELL",
        underlying_spot=24500.0,
        is_expiry_day=False,
    )
    assert req.is_short_option
    notional = 24500.0 * 25
    assert req.notional_value == notional
    # SPAN (10%) + Exposure (2%) = 12% of notional
    expected_margin = notional * 0.12
    assert req.total_margin_required == pytest.approx(expected_margin, 0.01)
    assert req.expiry_additional_elm == 0.0


def test_option_seller_expiry_day_additional_elm():
    # NIFTY 24500 CE, sell 1 lot (25 qty) on Expiry Day
    spot = 24500.0
    qty = 25
    notional = spot * qty
    req = calculate_order_margin(
        symbol="NIFTY24OCT24500CE",
        price=100.0,
        quantity=qty,
        segment="OPTIONS",
        side="SELL",
        underlying_spot=spot,
        is_expiry_day=True,
    )
    assert req.is_expiry_day
    assert req.is_short_option
    # SEBI 2% additional ELM
    expected_elm = notional * SEBI_EXPIRY_ADDITIONAL_ELM_PCT
    assert req.expiry_additional_elm == pytest.approx(expected_elm, 0.01)

    # Total = SPAN (10%) + Exposure (2%) + ELM (2%) = 14% of notional
    expected_total = notional * 0.14
    assert req.total_margin_required == pytest.approx(expected_total, 0.01)
    assert any("2.0% Extreme Loss Margin" in w for w in req.warnings)


def test_calendar_spread_trap_on_expiry_day():
    req = calculate_order_margin(
        symbol="NIFTY24OCT24500CE",
        price=50.0,
        quantity=25,
        segment="OPTIONS",
        side="SELL",
        underlying_spot=24500.0,
        is_expiry_day=True,
        is_calendar_spread=True,
    )
    assert req.is_calendar_spread_trap
    assert any("Calendar spread margin relief is REVOKED" in w for w in req.warnings)


def test_validate_margin_solvency():
    req = calculate_order_margin(
        symbol="NIFTY24OCT24500CE",
        price=100.0,
        quantity=25,
        segment="OPTIONS",
        side="BUY",
        underlying_spot=24500.0,
    )
    # Total required = 2500, with 5% buffer = 2625
    solvent, msg = validate_margin_solvency(req, available_cash=3000.0)
    assert solvent is True

    insolvent, fail_msg = validate_margin_solvency(req, available_cash=2000.0)
    assert insolvent is False
    assert "MARGIN SHORTFALL" in fail_msg
