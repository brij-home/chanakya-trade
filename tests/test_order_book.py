"""
tests/test_order_book.py
────────────────────────
Unit tests for market.order_book OBI, iceberg detection, and depth metrics.
"""

from market.order_book import (
    compute_order_book_metrics,
    analyze_symbol_order_book,
    OrderBookSnapshot,
)


def test_compute_order_book_metrics_heavy_bid_imbalance():
    raw_depth = {
        "buy": [
            {"price": 1000.0, "quantity": 5000, "orders": 12},
            {"price": 999.5, "quantity": 4000, "orders": 10},
            {"price": 999.0, "quantity": 3500, "orders": 8},
            {"price": 998.5, "quantity": 2000, "orders": 5},
            {"price": 998.0, "quantity": 1500, "orders": 4},
        ],
        "sell": [
            {"price": 1000.5, "quantity": 1000, "orders": 3},
            {"price": 1001.0, "quantity": 1200, "orders": 4},
            {"price": 1001.5, "quantity": 800, "orders": 2},
            {"price": 1002.0, "quantity": 500, "orders": 1},
            {"price": 1002.5, "quantity": 600, "orders": 2},
        ],
    }

    snap = compute_order_book_metrics("RELIANCE", raw_depth, ltp=1000.25)
    assert snap.total_bid_qty == 16000
    assert snap.total_ask_qty == 4100
    assert snap.obi_5 > 0.50
    assert snap.obi_weighted > 0.50
    assert snap.bias in ("HEAVY_ACCUMULATION", "BUY_LEAN")
    assert snap.spread == 0.5
    assert snap.liquidity_status == "NORMAL"


def test_iceberg_order_detection_on_absorption():
    raw_depth = {
        "buy": [
            {"price": 500.0, "quantity": 1000, "orders": 2},
            {"price": 499.0, "quantity": 800, "orders": 2},
        ],
        "sell": [
            {"price": 500.5, "quantity": 1200, "orders": 3},
            {"price": 501.0, "quantity": 1500, "orders": 4},
        ],
    }

    # If recent trades at 500.0 was 6000 (>> average depth of 900)
    snap = compute_order_book_metrics("INFY", raw_depth, ltp=500.2, recent_trades_volume=6000.0)
    assert snap.iceberg_detected is True
    assert snap.iceberg_side == "BUY"
    assert snap.iceberg_price == 500.0
    assert snap.absorption_score > 60


def test_analyze_symbol_order_book_returns_snapshot():
    snap = analyze_symbol_order_book("TCS")
    assert isinstance(snap, OrderBookSnapshot)
    assert snap.symbol == "TCS"
    assert snap.to_dict()["bias"] in (
        "HEAVY_ACCUMULATION",
        "BUY_LEAN",
        "BALANCED",
        "SELL_LEAN",
        "HEAVY_DISTRIBUTION",
    )


def test_compute_order_book_metrics_fyers_volume_keys():
    """Verifies that Fyers L2 depth containing 'volume' and 'ord' computes OBI accurately."""
    fyers_raw_depth = {
        "buy": [
            {"price": 8652, "volume": 10, "ord": 4},
            {"price": 8651, "volume": 8, "ord": 2},
            {"price": 8650, "volume": 38, "ord": 9},
            {"price": 8649, "volume": 4, "ord": 3},
            {"price": 8648, "volume": 9, "ord": 7},
        ],
        "sell": [
            {"price": 8654, "volume": 4, "ord": 2},
            {"price": 8655, "volume": 4, "ord": 3},
            {"price": 8656, "volume": 10, "ord": 3},
            {"price": 8657, "volume": 17, "ord": 10},
            {"price": 8658, "volume": 11, "ord": 6},
        ],
    }
    snap = compute_order_book_metrics("CRUDEOIL", fyers_raw_depth, ltp=8653.0)
    assert snap.total_bid_qty == 69
    assert snap.total_ask_qty == 46
    assert snap.obi_5 > 0.0
    assert snap.total_bid_qty > snap.total_ask_qty
    assert snap.liquidity_status == "NORMAL"
    assert snap.bids[0]["quantity"] == 10
    assert snap.bids[0]["orders"] == 4

