"""
tests/test_payoff_coordinates.py
─────────────────────────────────
Unit tests for institutional position sizing payoff coordinates (E01) and capital controls (E03).
Verifies:
  1. Bought Call and Bought Put mirror tests preserve long premium coordinates (stop < entry < target).
  2. Sold Call and Sold Put mirror tests preserve short premium coordinates (target < entry < stop).
  3. Short options require verified margin evidence, otherwise fail-closed as BLOCKED_UNBOUNDED_RISK.
  4. Invalid anchors in actionable mode fail-closed as BLOCKED_INVALID_ANCHORS without percentage fallback.
  5. Missing capital in actionable mode returns BLOCKED_MISSING_CAPITAL with zero executable lots.
  6. Explicit research mode returns RESEARCH_ONLY status with HYPOTHETICAL_RESEARCH capital basis.
  7. Non-positive/non-finite entry price returns BLOCKED_INVALID_PRICE.
  8. Unsupported currencies in account snapshots are rejected with BLOCKED_INVALID_CURRENCY.
"""

from __future__ import annotations

from unittest.mock import patch

from engine.position_sizer import (
    calculate_position_size,
    resolve_payoff_orientation,
)


class TestPayoffOrientation:
    def test_bought_put_orientation_is_long_premium(self):
        # A bought put on a bearish underlying is LONG premium coordinate
        assert (
            resolve_payoff_orientation("LONG_OPTION", "BEARISH", "NSE:NIFTY26NOV24500PE") == "LONG"
        )
        assert resolve_payoff_orientation(None, "BEARISH", "NSE:NIFTY26NOV24500PE") == "LONG"

    def test_bought_call_orientation_is_long_premium(self):
        # A bought call on a bullish underlying is LONG premium coordinate
        assert (
            resolve_payoff_orientation("LONG_OPTION", "BULLISH", "NSE:NIFTY26NOV25000CE") == "LONG"
        )
        assert resolve_payoff_orientation(None, "BULLISH", "NSE:NIFTY26NOV25000CE") == "LONG"

    def test_sold_option_orientation_is_short_premium(self):
        # Sold options are SHORT premium coordinate
        assert (
            resolve_payoff_orientation("SHORT_OPTION", "BEARISH", "NSE:NIFTY26NOV25000CE")
            == "SHORT"
        )
        assert (
            resolve_payoff_orientation("OPTION_SELLER", "BULLISH", "NSE:NIFTY26NOV24500PE")
            == "SHORT"
        )

    def test_cash_asset_follows_direction(self):
        assert resolve_payoff_orientation("LONG_ASSET", "BULLISH", "RELIANCE") == "LONG"
        assert resolve_payoff_orientation("LONG_ASSET", "BEARISH", "RELIANCE") == "SHORT"
        assert resolve_payoff_orientation("SHORT_ASSET", "BEARISH", "RELIANCE") == "SHORT"


class TestE01BoughtPutPremiumRisk:
    @patch("engine.position_sizer.get_lot_size", return_value=65)
    def test_bought_put_preserves_premium_coordinates(self, _mock_lot):
        """Bought Put with entry 150, stop 120, target 240 must NEVER invert to stop 153 and target 144."""
        res = calculate_position_size(
            symbol="NSE:NIFTY26NOV24500PE",
            entry_price=150.0,
            stop_loss=120.0,
            target_price=240.0,
            capital=200000.0,  # 1.5% risk = 3,000 INR; 1 lot risk = 65 * 30 = 1,950 INR
            direction="BEARISH",
            payoff_type="LONG_OPTION",
            vix=15.0,
            is_research=False,
        )
        assert res.entry_price == 150.0
        assert res.stop_loss == 120.0
        assert res.target_price == 240.0
        assert res.r_multiple == 3.0  # (240 - 150) / (150 - 120) = 90 / 30 = 3.0
        assert res.lots == 1
        assert res.shares == 65
        assert res.status == "CALCULATED"
        assert res.capital_basis == "EXPLICIT_BUDGET"

    @patch("engine.position_sizer.get_lot_size", return_value=65)
    def test_bought_call_mirror_preserves_premium_coordinates(self, _mock_lot):
        """Bought Call with entry 150, stop 120, target 240 mirrors bought put."""
        res = calculate_position_size(
            symbol="NSE:NIFTY26NOV25000CE",
            entry_price=150.0,
            stop_loss=120.0,
            target_price=240.0,
            capital=200000.0,
            direction="BULLISH",
            payoff_type="LONG_OPTION",
            vix=15.0,
            is_research=False,
        )
        assert res.entry_price == 150.0
        assert res.stop_loss == 120.0
        assert res.target_price == 240.0
        assert res.r_multiple == 3.0
        assert res.lots == 1
        assert res.shares == 65
        assert res.status == "CALCULATED"


class TestE01SoldOptionPayoff:
    @patch("engine.position_sizer.get_lot_size", return_value=65)
    def test_sold_option_requires_margin_evidence(self, _mock_lot):
        """Short option sizing without verified margin is blocked fail-closed."""
        res = calculate_position_size(
            symbol="NSE:NIFTY26NOV25000CE",
            entry_price=150.0,
            stop_loss=180.0,
            target_price=90.0,
            capital=500000.0,
            direction="BEARISH",
            payoff_type="SHORT_OPTION",
            margin_required_per_lot=None,  # Missing margin
            is_research=False,
        )
        assert res.lots == 0
        assert res.shares == 0
        assert res.status == "BLOCKED_UNBOUNDED_RISK"
        assert "margin and bounded-risk evidence" in res.reason

    @patch("engine.position_sizer.get_lot_size", return_value=65)
    def test_sold_option_with_margin_preserves_short_coordinates(self, _mock_lot):
        """Short option sizing with margin preserves short premium coordinates (target < entry < stop)."""
        res = calculate_position_size(
            symbol="NSE:NIFTY26NOV25000CE",
            entry_price=150.0,
            stop_loss=180.0,
            target_price=90.0,
            capital=1000000.0,
            direction="BEARISH",
            payoff_type="SHORT_OPTION",
            margin_required_per_lot=150000.0,
            is_research=False,
        )
        assert res.entry_price == 150.0
        assert res.stop_loss == 180.0
        assert res.target_price == 90.0
        assert res.r_multiple == 2.0  # (150 - 90) / (180 - 150) = 60 / 30 = 2.0
        assert res.lots >= 1
        assert res.status == "CALCULATED"


class TestE03CapitalAndAnchorGuards:
    def test_actionable_mode_rejects_missing_capital(self):
        """In actionable mode (is_research=False), missing capital is blocked, never defaulted to 100k."""
        res = calculate_position_size(
            symbol="INFY",
            entry_price=1500.0,
            stop_loss=1470.0,
            capital=None,
            is_research=False,
        )
        assert res.lots == 0
        assert res.shares == 0
        assert res.status == "BLOCKED_MISSING_CAPITAL"
        assert res.capital_basis == "UNAVAILABLE"
        assert "Mandatory trading capital budget missing" in res.reason

    def test_research_mode_allows_hypothetical_capital_with_typed_status(self):
        """In research mode (is_research=True), 100k capital is explicitly labeled RESEARCH_ONLY."""
        res = calculate_position_size(
            symbol="INFY",
            entry_price=1500.0,
            stop_loss=1470.0,
            capital=None,
            is_research=True,
        )
        assert res.shares > 0
        assert res.status == "RESEARCH_ONLY"
        assert res.capital_basis == "HYPOTHETICAL_RESEARCH"

    def test_actionable_mode_rejects_invalid_long_anchors(self):
        """Actionable mode blocks invalid long stops (stop >= entry) without synthetic percentage repairs."""
        res = calculate_position_size(
            symbol="TCS",
            entry_price=3500.0,
            stop_loss=3600.0,  # Invalid: stop above entry for long
            capital=200000.0,
            is_research=False,
        )
        assert res.shares == 0
        assert res.status == "BLOCKED_INVALID_ANCHORS"
        assert "must be strictly below entry" in res.reason

    def test_actionable_mode_rejects_invalid_short_anchors(self):
        """Actionable mode blocks invalid short stops (stop <= entry) without synthetic percentage repairs."""
        res = calculate_position_size(
            symbol="TCS",
            entry_price=3500.0,
            stop_loss=3400.0,  # Invalid: stop below entry for short
            capital=200000.0,
            direction="BEARISH",
            payoff_type="SHORT_ASSET",
            is_research=False,
        )
        assert res.shares == 0
        assert res.status == "BLOCKED_INVALID_ANCHORS"
        assert "must be strictly above entry" in res.reason

    def test_non_positive_entry_price_is_blocked(self):
        res = calculate_position_size(
            symbol="INFY",
            entry_price=0.0,
            stop_loss=1470.0,
            capital=100000.0,
            is_research=False,
        )
        assert res.shares == 0
        assert res.status == "BLOCKED_INVALID_PRICE"

    def test_unsupported_currency_in_account_snapshot_is_blocked(self):
        snapshot = {"available_balance": 500000.0, "currency": "USD"}
        res = calculate_position_size(
            symbol="INFY",
            entry_price=1500.0,
            stop_loss=1470.0,
            account_snapshot=snapshot,
            is_research=False,
        )
        assert res.shares == 0
        assert res.status == "BLOCKED_INVALID_CURRENCY"
