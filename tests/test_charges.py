"""
tests/test_charges.py
─────────────────────
Unit tests for the Indian Market Transaction Cost Engine (engine/charges.py).
"""

from __future__ import annotations

from decimal import Decimal
from engine.charges import (
    calculate_transaction_charges,
)


class TestEquityDeliveryCharges:
    """Test delivery equity charges (STT 0.1% buy & sell, stamp duty on buy, zero brokerage default)."""

    def test_delivery_buy(self):
        # 100 shares @ ₹1,500 = ₹1,50,000 turnover
        breakdown = calculate_transaction_charges(
            price=1500.0,
            quantity=100,
            segment="EQUITY_DELIVERY",
            side="BUY",
        )
        assert breakdown.notional_turnover == Decimal("150000.00")
        assert breakdown.brokerage == Decimal("0.00")
        assert breakdown.stt == Decimal("150.00")  # 0.1% of 1,50,000
        assert breakdown.stamp_duty == Decimal("22.50")  # 0.015% of 1,50,000
        assert breakdown.sebi_charges == Decimal("0.15")  # ₹10/cr = 0.0001%
        assert breakdown.total_charges > Decimal("170.00")
        assert breakdown.effective_pct > Decimal("0.1")

    def test_delivery_sell(self):
        # 100 shares @ ₹1,500 = ₹1,50,000 turnover (Sell side: No Stamp Duty, STT applies)
        breakdown = calculate_transaction_charges(
            price=1500.0,
            quantity=100,
            segment="EQUITY_DELIVERY",
            side="SELL",
        )
        assert breakdown.stt == Decimal("150.00")
        assert breakdown.stamp_duty == Decimal("0.00")  # No stamp duty on sell


class TestEquityIntradayCharges:
    """Test intraday charges (STT 0.025% on sell only, brokerage capped at ₹20)."""

    def test_intraday_buy(self):
        # 500 shares @ ₹1,000 = ₹5,00,000 turnover
        breakdown = calculate_transaction_charges(
            price=1000.0,
            quantity=500,
            segment="EQUITY_INTRADAY",
            side="BUY",
        )
        assert breakdown.brokerage == Decimal("20.00")  # Capped at ₹20
        assert breakdown.stt == Decimal("0.00")  # No STT on intraday buy
        assert breakdown.stamp_duty == Decimal("15.00")  # 0.003% of 5,00,000

    def test_intraday_sell(self):
        # 500 shares @ ₹1,000 = ₹5,00,000 turnover
        breakdown = calculate_transaction_charges(
            price=1000.0,
            quantity=500,
            segment="EQUITY_INTRADAY",
            side="SELL",
        )
        assert breakdown.stt == Decimal("125.00")  # 0.025% of 5,00,000
        assert breakdown.stamp_duty == Decimal("0.00")


class TestOptionsCharges:
    """Test options charges (on premium turnover, STT 0.1% on sell, high exchange fee)."""

    def test_options_buy(self):
        # 100 lots of NIFTY (7,500 qty) @ ₹150 premium = ₹11,25,000 premium turnover
        breakdown = calculate_transaction_charges(
            price=150.0,
            quantity=7500,
            segment="OPTIONS",
            side="BUY",
        )
        assert breakdown.brokerage == Decimal("20.00")
        assert breakdown.stt == Decimal("0.00")  # No STT on option buy
        assert breakdown.stamp_duty == Decimal("33.75")  # 0.003% of 11,25,000

    def test_options_sell(self):
        # 100 lots of NIFTY @ ₹150 premium = ₹11,25,000 premium turnover
        breakdown = calculate_transaction_charges(
            price=150.0,
            quantity=7500,
            segment="OPTIONS",
            side="SELL",
        )
        assert breakdown.stt == Decimal("1125.00")  # 0.1% of premium turnover
        assert breakdown.stamp_duty == Decimal("0.00")


def test_zero_turnover():
    breakdown = calculate_transaction_charges(price=0.0, quantity=0)
    assert breakdown.notional_turnover == Decimal("0.00")
    assert breakdown.total_charges == Decimal("0.00")
