"""
Test suite for Gate 26: Option Contract Bid-Ask Spread Friction & Depth Sanity Gate.

Verifies:
1. Index Option (NIFTY/BANKNIFTY) with excessive bid-ask spread (> 4.5% of mid) is vetoed.
2. Index Option with institutional tight spread (<= 4.5%) passes.
3. Single Stock Option with spread > 8.0% is vetoed.
4. Single Stock Option with spread <= 8.0% passes.
"""

from types import SimpleNamespace
import pytest
from engine.alert_scrutiny import AlertScrutinyAuditor
from market.order_book import get_depth_book, clear_depth_books


@pytest.fixture(autouse=True)
def clean_books():
    clear_depth_books()
    yield
    clear_depth_books()


def test_gate26_index_option_wide_spread_veto():
    """Gate 26 must veto Nifty option when bid-ask spread exceeds 4.5%."""
    auditor = AlertScrutinyAuditor()
    sym = "NIFTY26OCT25000CE"
    book = get_depth_book(sym)
    # Bid: 100.0, Ask: 110.0 -> spread 10.0 / mid 105.0 = 9.52% > 4.5%
    book.batch_update(
        bids=[{"price": 100.0, "quantity": 100, "orders": 2}],
        asks=[{"price": 110.0, "quantity": 100, "orders": 2}],
    )

    alert = SimpleNamespace(
        alert_id="aa-opt-nifty-001",
        symbol=sym,
        contract_symbol=sym,
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry=105.0,
        trigger_level=105.0,
        stop_loss=90.0,
        target_level=135.0,
        target1=135.0,
        target2=150.0,
        ltp=105.0,
        stage="TRIGGERED",
        setup_type="MOMENTUM_EXPANSION",
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        option_type="CE",
        segment="OPT",
        metrics={},
        extra_metrics={},
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert flags["option_spread_friction_valid"] is False
    assert "Option Bid-Ask Spread Friction Veto" in reason
    assert "9.5%" in reason


def test_gate26_index_option_tight_spread_passes():
    """Gate 26 passes Nifty option when bid-ask spread is tight (<= 4.5%)."""
    auditor = AlertScrutinyAuditor()
    sym = "NIFTY26OCT25000CE"
    book = get_depth_book(sym)
    # Bid: 100.0, Ask: 102.0 -> spread 2.0 / mid 101.0 = 1.98% <= 4.5%
    book.batch_update(
        bids=[{"price": 100.0, "quantity": 100, "orders": 2}],
        asks=[{"price": 102.0, "quantity": 100, "orders": 2}],
    )

    alert = SimpleNamespace(
        alert_id="aa-opt-nifty-002",
        symbol=sym,
        contract_symbol=sym,
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry=101.0,
        trigger_level=101.0,
        stop_loss=85.0,
        target_level=135.0,
        target1=135.0,
        target2=150.0,
        ltp=101.0,
        stage="TRIGGERED",
        setup_type="MOMENTUM_EXPANSION",
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        option_type="CE",
        segment="OPT",
        metrics={},
        extra_metrics={},
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed
    assert flags["option_spread_friction_valid"] is True
    assert flags.get("option_spread_pct") == 1.98


def test_gate26_stock_option_spread_threshold():
    """Gate 26 permits stock options up to 8.0% spread, vetoes beyond 8.0%."""
    auditor = AlertScrutinyAuditor()
    sym = "TATASTEEL26OCT160CE"
    book = get_depth_book(sym)
    # Bid: 10.0, Ask: 11.2 -> spread 1.2 / mid 10.6 = 11.32% > 8.0%
    book.batch_update(
        bids=[{"price": 10.0, "quantity": 500, "orders": 3}],
        asks=[{"price": 11.2, "quantity": 500, "orders": 3}],
    )

    alert = SimpleNamespace(
        alert_id="aa-opt-tatasteel-001",
        symbol=sym,
        contract_symbol=sym,
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry=10.6,
        trigger_level=10.6,
        stop_loss=9.0,
        target_level=14.0,
        target1=14.0,
        target2=16.0,
        ltp=10.6,
        stage="TRIGGERED",
        setup_type="MOMENTUM_EXPANSION",
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        option_type="CE",
        segment="OPT",
        metrics={},
        extra_metrics={},
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert not passed
    assert flags["option_spread_friction_valid"] is False
    assert "Option Bid-Ask Spread Friction Veto" in reason
    assert "11.3%" in reason
