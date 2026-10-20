"""
Test suite for multi-broker Level 2 depth normalization.
Verifies Shoonya and Angel One market depth extraction and BisectDepthBook bridging.
"""

from unittest.mock import MagicMock
import pytest
from market.order_book import get_depth_book, clear_depth_books


@pytest.fixture(autouse=True)
def clean_books():
    clear_depth_books()
    yield
    clear_depth_books()


def test_shoonya_get_market_depth_normalization(monkeypatch):
    """Verify Shoonya GetQuotes response is parsed into 5-depth levels and bridges into BisectDepthBook."""
    from brokers.shoonya import ShoonyaAPI

    broker = ShoonyaAPI()
    broker._token = "test_token"
    broker.user_id = "test_user"

    # Stub instrument resolution
    monkeypatch.setattr(
        broker,
        "_resolve_instrument",
        lambda sym: {"exch": "NSE", "token": "2885", "tsym": "RELIANCE-EQ"},
    )

    # Stub GetQuotes response
    mock_quotes = {
        "lp": "2500.00",
        "bp1": "2499.50",
        "bq1": "100",
        "bno1": "5",
        "bp2": "2499.00",
        "bq2": "200",
        "bno2": "10",
        "bp3": "2498.50",
        "bq3": "300",
        "bno3": "15",
        "bp4": "2498.00",
        "bq4": "400",
        "bno4": "20",
        "bp5": "2497.50",
        "bq5": "500",
        "bno5": "25",
        "sp1": "2500.50",
        "sq1": "150",
        "sno1": "8",
        "sp2": "2501.00",
        "sq2": "250",
        "sno2": "12",
        "sp3": "2501.50",
        "sq3": "350",
        "sno3": "16",
        "sp4": "2502.00",
        "sq4": "450",
        "sno4": "22",
        "sp5": "2502.50",
        "sq5": "550",
        "sno5": "30",
    }
    monkeypatch.setattr(broker, "_post", lambda endpoint, payload: mock_quotes)

    depth = broker.get_market_depth("NSE:RELIANCE")

    assert depth["status"] == "LIVE_L2"
    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5
    assert depth["bids"][0]["price"] == 2499.50
    assert depth["bids"][0]["quantity"] == 100
    assert depth["asks"][0]["price"] == 2500.50
    assert depth["spread"] == 1.00
    assert depth["total_buy_qty"] == 1500
    assert depth["total_sell_qty"] == 1750

    # Verify central BisectDepthBook was bridged
    book = get_depth_book("RELIANCE")
    assert book.best_bid == 2499.50
    assert book.best_ask == 2500.50
    assert book.total_bid_qty == 1500
    assert book.total_ask_qty == 1750


def test_angelone_get_market_depth_normalization(monkeypatch):
    """Verify Angel One SmartAPI getMarketData is parsed into 5-depth levels and bridges into BisectDepthBook."""
    from brokers.angelone import AngelOneAPI

    broker = AngelOneAPI(api_key="test_key", client_code="test_client", password="test_password")
    mock_obj = MagicMock()
    broker._obj = mock_obj

    mock_market_data = {
        "status": True,
        "data": {
            "fetched": [
                {
                    "exchange": "NSE",
                    "tradingSymbol": "INFY-EQ",
                    "symbolToken": "1594",
                    "depth": {
                        "buy": [
                            {"price": 1800.0, "quantity": 50, "orders": 2},
                            {"price": 1799.5, "quantity": 100, "orders": 4},
                            {"price": 1799.0, "quantity": 150, "orders": 6},
                            {"price": 1798.5, "quantity": 200, "orders": 8},
                            {"price": 1798.0, "quantity": 250, "orders": 10},
                        ],
                        "sell": [
                            {"price": 1800.5, "quantity": 60, "orders": 3},
                            {"price": 1801.0, "quantity": 120, "orders": 5},
                            {"price": 1801.5, "quantity": 180, "orders": 7},
                            {"price": 1802.0, "quantity": 240, "orders": 9},
                            {"price": 1802.5, "quantity": 300, "orders": 11},
                        ],
                    },
                }
            ]
        },
    }
    mock_obj.getMarketData.return_value = mock_market_data

    depth = broker.get_market_depth("NSE:INFY")

    assert depth["status"] == "LIVE_L2"
    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5
    assert depth["bids"][0]["price"] == 1800.0
    assert depth["asks"][0]["price"] == 1800.5
    assert depth["spread"] == 0.50
    assert depth["total_buy_qty"] == 750
    assert depth["total_sell_qty"] == 900

    # Verify central BisectDepthBook was bridged
    book = get_depth_book("INFY")
    assert book.best_bid == 1800.0
    assert book.best_ask == 1800.5
    assert book.total_bid_qty == 750
    assert book.total_ask_qty == 900
