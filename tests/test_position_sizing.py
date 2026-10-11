"""
Tests for percentage-based position sizing (#157).
"""

from __future__ import annotations

import pytest


class TestSizeByPct:
    def test_basic_pct_calculation(self):
        from engine.trade_executor import size_by_pct

        # 5% of ₹1,00,000 at ₹1,400 = ₹5,000 / ₹1,400 = 3.57 → floor to 3
        qty = size_by_pct("INFY", 5.0, 100_000, limit_price=1400.0)
        assert qty == 3

    def test_10pct_of_100k_at_500(self):
        from engine.trade_executor import size_by_pct

        # 10% of ₹1,00,000 at ₹500 = ₹10,000 / ₹500 = 20
        qty = size_by_pct("INFY", 10.0, 100_000, limit_price=500.0)
        assert qty == 20

    def test_returns_integer(self):
        from engine.trade_executor import size_by_pct

        qty = size_by_pct("INFY", 2.5, 100_000, limit_price=1000.0)
        assert isinstance(qty, int)

    def test_zero_quantity_raises(self):
        from engine.trade_executor import size_by_pct

        # 1% of ₹1,000 at ₹50,000 = ₹10 / ₹50,000 → 0 shares → error
        with pytest.raises(ValueError, match="too small"):
            size_by_pct("INFY", 1.0, 1_000, limit_price=50_000.0)

    def test_exceeds_max_position_pct_raises(self, monkeypatch):
        from engine.trade_executor import size_by_pct

        monkeypatch.setenv("MAX_POSITION_PCT", "20")
        with pytest.raises(ValueError, match="exceeds"):
            size_by_pct("INFY", 25.0, 100_000, limit_price=1000.0)

    def test_exactly_at_max_position_pct_ok(self, monkeypatch):
        from engine.trade_executor import size_by_pct

        monkeypatch.setenv("MAX_POSITION_PCT", "20")
        # 20% of ₹1,00,000 at ₹1,000 = 20 shares
        qty = size_by_pct("INFY", 20.0, 100_000, limit_price=1000.0)
        assert qty == 20

    def test_100pct_with_no_limit_cap(self, monkeypatch):
        from engine.trade_executor import size_by_pct

        monkeypatch.delenv("MAX_POSITION_PCT", raising=False)
        # Without MAX_POSITION_PCT env, default cap is 100%
        qty = size_by_pct("INFY", 50.0, 100_000, limit_price=1000.0)
        assert qty == 50


class TestGetTradingCapital:
    def test_default_is_100k(self, monkeypatch):
        from engine.trade_executor import get_trading_capital

        monkeypatch.delenv("TRADING_CAPITAL", raising=False)
        assert get_trading_capital() == 100_000

    def test_reads_from_env(self, monkeypatch):
        from engine.trade_executor import get_trading_capital

        monkeypatch.setenv("TRADING_CAPITAL", "500000")
        assert get_trading_capital() == 500_000

    def test_float_env_value(self, monkeypatch):
        from engine.trade_executor import get_trading_capital

        monkeypatch.setenv("TRADING_CAPITAL", "250000.50")
        assert get_trading_capital() == 250_000.50


class TestParsePctArg:
    def test_pct_string_detected(self):
        from engine.trade_executor import parse_qty_or_pct

        qty, is_pct = parse_qty_or_pct("5%")
        assert is_pct is True
        assert qty == 5.0

    def test_integer_string_not_pct(self):
        from engine.trade_executor import parse_qty_or_pct

        qty, is_pct = parse_qty_or_pct("100")
        assert is_pct is False
        assert qty == 100

    def test_float_pct(self):
        from engine.trade_executor import parse_qty_or_pct

        qty, is_pct = parse_qty_or_pct("2.5%")
        assert is_pct is True
        assert qty == 2.5

    def test_zero_pct_raises(self):
        from engine.trade_executor import parse_qty_or_pct

        with pytest.raises(ValueError):
            parse_qty_or_pct("0%")

    def test_negative_pct_raises(self):
        from engine.trade_executor import parse_qty_or_pct

        with pytest.raises(ValueError):
            parse_qty_or_pct("-5%")

    def test_zero_quantity_raises(self):
        from engine.trade_executor import parse_qty_or_pct

        with pytest.raises(ValueError, match="Quantity must be > 0"):
            parse_qty_or_pct("0")

    def test_negative_quantity_raises(self):
        from engine.trade_executor import parse_qty_or_pct

        with pytest.raises(ValueError, match="Quantity must be > 0"):
            parse_qty_or_pct("-10")

    def test_physical_expiry_week_discount(self):
        from engine.position_sizer import calculate_position_size_for_alert

        # Single-stock F&O: RELIANCE (lot size 500)
        res_normal = calculate_position_size_for_alert(
            alert_type="SQUEEZE_BREAKOUT",
            symbol="RELIANCE",
            entry_price=2500.0,
            stop_loss=2450.0,
            capital=5000000.0,
            is_fno=True,
            is_physical_expiry_week=False,
        )
        res_physical = calculate_position_size_for_alert(
            alert_type="SQUEEZE_BREAKOUT",
            symbol="RELIANCE",
            entry_price=2500.0,
            stop_loss=2450.0,
            capital=5000000.0,
            is_fno=True,
            is_physical_expiry_week=True,
        )
        assert res_physical.lots <= res_normal.lots
        assert "SEBI Physical Settlement" in res_physical.notes


class TestSebiPhysicalSettlementRiskGate:
    def test_single_stock_vs_index_classification(self):
        from engine.position_sizer import is_physical_delivery_fno

        # Single-stock derivatives are subject to physical delivery
        assert is_physical_delivery_fno("RELIANCE") is True
        assert is_physical_delivery_fno("INFY") is True
        assert is_physical_delivery_fno("HDFCBANK") is True
        assert is_physical_delivery_fno("NSE:TCS-EQ") is True
        assert is_physical_delivery_fno("RELIANCE26OCT3000CE") is True

        # Indices, MCX Commodities and CDS Currencies are cash settled
        assert is_physical_delivery_fno("NIFTY") is False
        assert is_physical_delivery_fno("BANKNIFTY") is False
        assert is_physical_delivery_fno("FINNIFTY") is False
        assert is_physical_delivery_fno("CRUDEOIL") is False
        assert is_physical_delivery_fno("USDINR") is False

    def test_risk_gate_blocks_underfunded_expiry_week_stock_derivative(self):
        from engine.position_sizer import check_sebi_physical_settlement_risk
        from engine.risk_gate import compute_allowed_actions

        # RELIANCE lot size = 500. At ₹2500, delivery value = 500 * 2500 = ₹12,50,000.
        # Account capital = ₹1,00,000 (< ₹12.5L required) and DTE = 2 days
        risk = check_sebi_physical_settlement_risk(
            "RELIANCE", dte=2, capital=100000.0, price=2500.0
        )
        assert risk["applicable"] is True
        assert risk["blocked"] is True
        assert risk["requires_full_margin"] is True
        assert "SEBI Physical Delivery Risk" in risk["warning"]

        # In compute_allowed_actions, it must fail-closed with SEBI_PHYSICAL_DELIVERY_RISK
        allowed = compute_allowed_actions(
            "RELIANCE",
            capital=100000.0,
            prices={"RELIANCE": 2500.0},
            dte=2,
        )
        assert allowed.allowed is False
        assert "SEBI_PHYSICAL_DELIVERY_RISK" in allowed.flags
        assert "SEBI Physical Delivery Risk" in allowed.block_reason

    def test_risk_gate_allows_cash_settled_index_derivative_in_expiry_week(self):
        from engine.position_sizer import check_sebi_physical_settlement_risk
        from engine.risk_gate import compute_allowed_actions

        # NIFTY is cash settled: not applicable to physical delivery block
        risk = check_sebi_physical_settlement_risk("NIFTY", dte=1, capital=100000.0, price=25000.0)
        assert risk["applicable"] is False
        assert risk["blocked"] is False

        allowed = compute_allowed_actions(
            "NIFTY",
            capital=500000.0,
            prices={"NIFTY": 25000.0},
            dte=1,
        )
        assert allowed.allowed is True
        assert "SEBI_PHYSICAL_DELIVERY_RISK" not in allowed.flags
