"""
tests/test_position_sizer.py
─────────────────────────────
Unit tests for institutional position sizing and risk-parity calculations.
"""

from __future__ import annotations

from engine.position_sizer import (
    PositionSizeResult,
    calculate_position_size,
    get_lot_size,
)


class TestLotSizes:
    def test_nifty_lot_size(self):
        assert get_lot_size("NIFTY") == 65

    def test_banknifty_lot_size(self):
        assert get_lot_size("BANKNIFTY") == 30

    def test_equity_cash_defaults_to_one(self):
        assert get_lot_size("UNKNOWN_EQUITY") == 1

    def test_exact_contract_requires_current_master_lot(self, monkeypatch):
        monkeypatch.setattr(
            "market.symbol_master.get_symbol_info",
            lambda symbol, *, require_fresh=False: (
                {
                    "symTicker": "NSE:NIFTY26NOV25000CE",
                    "minLotSize": 65,
                    "tickSize": 0.05,
                    "tradeStatus": 1,
                    "fyToken": "1011126102925000",
                    "expiryDate": 1795700000,
                    "underSym": "NIFTY",
                    "optType": "CE",
                    "strikePrice": 25000,
                }
                if symbol in ("NFO:NIFTY26NOV25000CE", "NSE:NIFTY26NOV25000CE")
                else None
            ),
        )
        assert get_lot_size("NFO:NIFTY26NOV25000CE") == 65
        # An exact derivative without a current master row must never inherit the
        # underlying's legacy lot-size estimate.
        assert get_lot_size("NFO:NIFTY26OCT25000CE") == 0


class TestPositionSizer:
    def setup_method(self):
        from engine.market_regime_gate import clear_cached_regime

        clear_cached_regime()

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

    def test_unknown_exact_contract_has_zero_executable_size(self, monkeypatch):
        monkeypatch.setattr(
            "market.symbol_master.get_symbol_info",
            lambda symbol, *, require_fresh=False: None,
        )
        res = calculate_position_size(
            symbol="NFO:NIFTY26OCT25000CE",
            entry_price=100.0,
            stop_loss=80.0,
            capital=1_000_000.0,
            is_fno=True,
        )
        assert res.lot_size == 0
        assert res.lots == 0
        assert res.shares == 0
        assert "UNAVAILABLE_CONTRACT_MASTER" in res.notes

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
        # For NIFTY (lot size 65, price 24000 -> 1 lot = 1,560,000 INR)
        res = calculate_position_size(
            symbol="NIFTY",
            entry_price=24000.0,
            stop_loss=23800.0,
            capital=4000000.0,
            max_risk_pct=1.5,
            sizing_model="fixed_fractional",
            max_capital_pct=80.0,
            is_fno=True,
        )
        assert res.lot_size == 65
        assert res.shares % 65 == 0
        assert res.lots >= 1

    def test_fno_order_is_zero_when_one_lot_exceeds_risk_budget(self):
        # Exchange-valid quantity is not permission to exceed the user's risk budget.
        res = calculate_position_size(
            symbol="NIFTY",
            entry_price=250.0,
            stop_loss=200.0,
            capital=100000.0,
            max_risk_pct=1.5,
            sizing_model="fixed_fractional",
            is_fno=True,
        )
        assert res.lots == 0
        assert res.shares == 0
        assert "ZERO_LOT_RISK_BUDGET" in res.notes
        assert "No order size is authorized" in res.notes

    def test_vix_sub_12_compression_scaling(self):
        # When India VIX < 12.0, risk is scaled down 25% due to low-volatility compression
        res = calculate_position_size(
            symbol="RELIANCE",
            entry_price=2500.0,
            stop_loss=2450.0,
            capital=1000000.0,
            max_risk_pct=2.0,
            max_capital_pct=100.0,
            sizing_model="fixed_fractional",
            vix=11.2,
        )
        assert "COMPRESSION" in res.notes
        assert "Risk scaled down 25%" in res.notes
        # 2.0% * 0.75 = 1.5% effective risk -> risk budget = 15,000 / 50 pts = 300 shares
        assert res.shares == 300
        assert res.risk_pct <= 1.55

    def test_max_risk_rupees_cap_strict_enforcement(self):
        # NIFTY lot size 65. Entry 100, Stop 80 -> Stop distance 20 -> 1 lot risk = 1300 INR
        # With max_risk_rupees=5000: floor(5000 / 1300) = 3 lots = 195 shares. Risk = 3900 <= 5000
        res = calculate_position_size(
            symbol="NIFTY",
            entry_price=100.0,
            stop_loss=80.0,
            capital=1_000_000.0,
            max_risk_pct=5.0,  # 50,000 INR from capital pct, but max_risk_rupees caps it at 5,000!
            max_risk_rupees=5000.0,
            sizing_model="fixed_fractional",
            is_fno=True,
        )
        assert res.lots == 3
        assert res.shares == 195
        assert res.risk_amount == 3900.0
        assert res.risk_amount <= 5000.0

        # With max_risk_rupees=1000: 1 lot risk (1300) > 1000 -> 0 lots authorized
        res_zero = calculate_position_size(
            symbol="NIFTY",
            entry_price=100.0,
            stop_loss=80.0,
            capital=1_000_000.0,
            max_risk_rupees=1000.0,
            sizing_model="fixed_fractional",
            is_fno=True,
        )
        assert res_zero.lots == 0
        assert res_zero.shares == 0
        assert "ZERO_LOT_RISK_BUDGET" in res_zero.notes

    def test_max_risk_rupees_alert_sizing_combined_multiplier(self):
        from engine.position_sizer import calculate_position_size_for_alert

        # Base calculation sizes to 3 lots (3900 INR risk).
        # APEX_CONFLUENCE has 1.25x multiplier -> 3 * 1.25 = 3.75 -> 3 lots (not allowed to jump to 4 lots which would risk 5200 > 5000!)
        res = calculate_position_size_for_alert(
            alert_type="GAMMA_BLAST",
            symbol="NIFTY",
            entry_price=100.0,
            stop_loss=80.0,
            capital=1_000_000.0,
            max_risk_pct=5.0,
            max_risk_rupees=5000.0,
            conviction_tier="APEX_CONFLUENCE",
            sizing_model="fixed_fractional",
            is_fno=True,
        )
        assert res.lots <= 3
        assert res.risk_amount <= 5000.0
