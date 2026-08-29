"""
tests/test_position_sizer.py
─────────────────────────────
Unit tests for institutional position sizing and risk-parity calculations.
"""

from __future__ import annotations

import pytest
from engine.position_sizer import (
    PositionSizeResult,
    calculate_position_size,
    get_lot_size,
)


class TestLotSizes:
    def test_nifty_lot_size(self):
        assert get_lot_size("NIFTY") == 25

    def test_banknifty_lot_size(self):
        assert get_lot_size("BANKNIFTY") == 15

    def test_equity_cash_defaults_to_one(self):
        assert get_lot_size("UNKNOWN_EQUITY") == 1


class TestPositionSizer:
    def test_atr_volatility_sizing(self):
        res = calculate_position_size(
            symbol="INFY",
            entry_price=1500.0,
            stop_loss=1470.0,  # 30 pts risk
            capital=100000.0,
            max_risk_pct=1.5,  # 1500 INR risk budget
            max_capital_pct=20.0,
            sizing_model="atr_volatility",
            atr=25.0,
        )
        assert isinstance(res, PositionSizeResult)
        assert res.shares > 0
        assert res.capital_allocated <= 100000.0 * 0.20 + 1.0  # Respects capital ceiling
        assert res.risk_amount > 0
        assert res.sizing_model == "atr_volatility"

    def test_fixed_fractional_sizing(self):
        # Capital 100,000, risk 1% = 1,000 INR
        # Entry 1000, Stop 950 -> stop distance 50 -> 1000 / 50 = 20 shares
        res = calculate_position_size(
            symbol="CASH_STOCK",
            entry_price=1000.0,
            stop_loss=950.0,
            capital=100000.0,
            max_risk_pct=1.0,
            max_capital_pct=25.0,
            sizing_model="fixed_fractional",
        )
        assert res.shares == 20
        assert res.risk_amount == 1000.0
        assert res.capital_allocated == 20000.0

    def test_half_kelly_sizing(self):
        res = calculate_position_size(
            symbol="TCS",
            entry_price=3500.0,
            stop_loss=3400.0,
            capital=200000.0,
            max_capital_pct=20.0,
            sizing_model="half_kelly",
            win_rate=0.60,
            profit_factor=2.0,
        )
        assert res.shares > 0
        assert res.capital_allocated <= 200000.0 * 0.20 + 1.0

    def test_derivatives_lot_rounding(self):
        # For NIFTY (lot size 25, price 24000 -> 1 lot = 600,000 INR)
        res = calculate_position_size(
            symbol="NIFTY",
            entry_price=24000.0,
            stop_loss=23800.0,
            capital=2000000.0,
            max_risk_pct=1.5,
            sizing_model="fixed_fractional",
            max_capital_pct=50.0,
            is_fno=True,
        )
        assert res.lot_size == 25
        assert res.shares % 25 == 0
        assert res.lots >= 1
