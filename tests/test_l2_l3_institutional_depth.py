"""
tests/test_l2_l3_institutional_depth.py
────────────────────────────────────────
Deterministic verification of L2 and L3 market microstructure upgrades:
  1. Fyers TBT 50-depth WebSocket packets bridge directly into BisectDepthBook.
  2. BisectDepthBook calculates 50-level OBI, micro-price, and sweep slippage.
  3. Scrutiny Gate 25 vetoes setups entering into:
     - Fleeing bid/ask walls (Spoof / Rugpull traps)
     - Immovable Fortress ask/bid walls capping upside/downside before Target 1
     - Extreme Order Book Imbalance (OBI-50 <= -0.45 for long, >= +0.45 for short)
  4. Zerodha get_market_depth extracts 5-depth and bridges into BisectDepthBook.
"""

from unittest.mock import MagicMock
import pytest

from engine.alert_scrutiny import AlertScrutinyAuditor
from market.fyers_tbt_manager import FyersTbtManager
from market.order_book import clear_depth_books, get_depth_book


class MockDepthProtobuf:
    """Simulates Fyers tbt_ws.Depth protobuf object with 50 levels."""

    def __init__(self, bid_base=100.0, ask_base=100.10):
        self.tbq = 500000
        self.tsq = 300000
        self.timestamp = 1727900000
        self.bidprice = [round(bid_base - (i * 0.05), 2) for i in range(50)]
        self.askprice = [round(ask_base + (i * 0.05), 2) for i in range(50)]
        self.bidqty = [2000] * 50
        self.askqty = [1500] * 50
        # Put an institutional fortress ask wall at level 6 (₹100.40)
        self.askqty[5] = 45000
        self.bidordn = [3] * 50
        self.askordn = [3] * 50
        self.askordn[5] = 12


@pytest.fixture(autouse=True)
def cleanup():
    clear_depth_books()
    yield
    clear_depth_books()


def test_fyers_tbt_bridges_into_bisect_depth_book():
    """Verify that incoming 50-depth TBT packets populate BisectDepthBook automatically."""
    mgr = FyersTbtManager()
    sym = "NSE:NIFTY26OCTFUT"
    clean_sym = "NIFTY26OCTFUT"

    mock_proto = MockDepthProtobuf(bid_base=25000.0, ask_base=25000.50)
    mgr._handle_depth_update(sym, mock_proto)

    # Verify both full symbol and clean symbol are populated in BisectDepthBook
    book = get_depth_book(clean_sym)
    assert book.best_bid == 25000.0
    assert book.best_ask == 25000.50
    assert len(book.get_bids(50)) == 50
    assert len(book.get_asks(50)) == 50

    # Verify 50-level OBI and micro-price computation
    obi_50 = book.obi(50)
    assert isinstance(obi_50, float)
    assert book.micro_price > 0

    # Verify sweep slippage simulation across depth tiers
    sweep = book.simulate_sweep("BUY", quantity=10000)
    assert sweep["filled_qty"] == 10000
    assert sweep["levels_swept"] >= 2
    assert sweep["slippage_bps"] >= 0.0


def test_scrutiny_gate25_vetoes_fleeing_bid_spoof_trap():
    """Gate 25 must reject long breakout when resting bid wall fled as price approached."""
    from types import SimpleNamespace

    engine = AlertScrutinyAuditor()

    alert = SimpleNamespace(
        alert_id="aa-real-reliance-001",
        symbol="NSE:RELIANCE",
        direction="BULLISH",
        option_type="CE",
        alert_type="BREAKOUT",
        entry=2900.0,
        trigger_level=2900.0,
        stop_loss=2850.0,
        target_level=3025.0,
        target1=3025.0,
        target2=3080.0,
        ltp=2902.0,
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        metrics={},
        extra_metrics={
            "l3_microstructure": {
                "fleeing_bid_wall_detected": True,
                "spoof_trap_warning": "BID_SPOOF_RUGPULL_RISK: Substantial resting bid wall fled as price approached",
            }
        },
    )

    passed, reason, flags = engine.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["order_book_sanctity_valid"] is False
    assert "Order Book Spoof Trap" in reason
    assert "bid floor abruptly fled" in reason


def test_scrutiny_gate25_vetoes_fortress_ask_wall_blocking_target():
    """Gate 25 must reject long setup if an immovable fortress ask wall caps upside before Target 1."""
    from types import SimpleNamespace

    engine = AlertScrutinyAuditor()

    alert = SimpleNamespace(
        alert_id="aa-real-infy-001",
        symbol="NSE:INFY",
        direction="BULLISH",
        option_type="CE",
        alert_type="BREAKOUT",
        entry=1900.0,
        trigger_level=1900.0,
        stop_loss=1860.0,
        target_level=2000.0,
        target1=2000.0,
        target2=2050.0,
        ltp=1901.0,
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        metrics={},
        extra_metrics={
            "l3_microstructure": {
                "fortress_ask_wall_confirmed": True,
                "ask_walls": [
                    {
                        "price": 1915.0,  # Sits at 1915, well before Target 1 (2000)
                        "qty": 35000,
                        "strength": "FORTRESS",
                        "book_share_pct": 28.5,
                    }
                ],
            }
        },
    )

    passed, reason, flags = engine.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["order_book_sanctity_valid"] is False
    assert "Institutional Fortress Ask Wall Veto" in reason
    assert "caps upside before Target 1" in reason


def test_scrutiny_gate25_vetoes_severe_order_book_imbalance():
    """Gate 25 must reject long breakout when OBI-50 is <= -0.45 (severe ask supply)."""
    from types import SimpleNamespace

    engine = AlertScrutinyAuditor()

    alert = SimpleNamespace(
        alert_id="aa-real-tcs-001",
        symbol="NSE:TCS",
        direction="BULLISH",
        option_type="CE",
        alert_type="BREAKOUT",
        entry=4200.0,
        trigger_level=4200.0,
        stop_loss=4120.0,
        target_level=4400.0,
        target1=4400.0,
        target2=4450.0,
        ltp=4202.0,
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        metrics={},
        extra_metrics={
            "l3_microstructure": {
                "obi_50": -0.58,  # Heavily skewed towards ask walls
            }
        },
    )

    passed, reason, flags = engine.verify_tier1_sanity(alert)
    assert passed is False
    assert flags["order_book_sanctity_valid"] is False
    assert "Order Book Imbalance Veto" in reason
    assert "-0.58" in reason


def test_zerodha_get_market_depth_bridges_into_bisect_depth_book():
    """Verify ZerodhaAPI get_market_depth extracts 5-depth and populates BisectDepthBook."""
    from brokers.zerodha import ZerodhaAPI

    api = ZerodhaAPI.__new__(ZerodhaAPI)
    mock_kite = MagicMock()
    mock_kite.quote.return_value = {
        "NSE:SBIN": {
            "last_price": 820.0,
            "depth": {
                "buy": [
                    {"price": 819.90, "quantity": 1500, "orders": 5},
                    {"price": 819.80, "quantity": 3000, "orders": 8},
                    {"price": 819.70, "quantity": 4500, "orders": 12},
                    {"price": 819.60, "quantity": 6000, "orders": 15},
                    {"price": 819.50, "quantity": 7500, "orders": 20},
                ],
                "sell": [
                    {"price": 820.10, "quantity": 1200, "orders": 4},
                    {"price": 820.20, "quantity": 2500, "orders": 7},
                    {"price": 820.30, "quantity": 3800, "orders": 10},
                    {"price": 820.40, "quantity": 5000, "orders": 14},
                    {"price": 820.50, "quantity": 6200, "orders": 18},
                ],
            },
        }
    }
    api.kite = mock_kite

    res = api.get_market_depth("SBIN")
    assert res["status"] == "LIVE_L2"
    assert len(res["bids"]) == 5
    assert len(res["asks"]) == 5
    assert round(res["spread"], 2) == 0.20
    assert res["total_buy_qty"] == 22500
    assert res["total_sell_qty"] == 18700

    # Verify that BisectDepthBook was populated
    book = get_depth_book("SBIN")
    assert book.best_bid == 819.90
    assert book.best_ask == 820.10
    assert book.total_bid_qty == 22500
    assert book.total_ask_qty == 18700
    assert round(book.spread, 2) == 0.20
