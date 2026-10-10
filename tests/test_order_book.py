"""
tests/test_order_book.py
────────────────────────
Unit tests for market.order_book OBI, iceberg detection, and depth metrics.
"""

from market.order_book import (
    BisectDepthBook,
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


def test_bisect_depth_book():
    from market.order_book import BisectDepthBook

    book = BisectDepthBook(max_depth=4)

    # 1. Insert bids in arbitrary/unsorted order
    book.update_level("BUY", price=100.0, quantity=10, orders=2)
    book.update_level("BUY", price=105.0, quantity=20, orders=3)
    book.update_level("BUY", price=95.0, quantity=30, orders=1)
    book.update_level("BUY", price=102.0, quantity=15, orders=2)

    # Bids must be sorted strictly descending by price
    bids = book.get_bids()
    assert [b["price"] for b in bids] == [105.0, 102.0, 100.0, 95.0]
    assert book.best_bid == 105.0
    assert book.total_bid_qty == 10 + 20 + 30 + 15

    # 2. Insert asks in arbitrary/unsorted order
    book.update_level("SELL", price=115.0, quantity=5, orders=1)
    book.update_level("SELL", price=108.0, quantity=25, orders=4)
    book.update_level("SELL", price=110.0, quantity=10, orders=2)

    # Asks must be sorted strictly ascending by price
    asks = book.get_asks()
    assert [a["price"] for a in asks] == [108.0, 110.0, 115.0]
    assert book.best_ask == 108.0
    assert book.spread == 3.0  # 108.0 - 105.0
    assert book.total_ask_qty == 5 + 25 + 10

    # 3. Update existing level in-place
    book.update_level("BUY", price=102.0, quantity=50, orders=5)
    assert book.total_bid_qty == (10 + 20 + 30 + 15) - 15 + 50
    assert book.get_bids()[1]["quantity"] == 50

    # 4. Delete level by setting quantity <= 0
    book.update_level("BUY", price=102.0, quantity=0)
    assert [b["price"] for b in book.get_bids()] == [105.0, 100.0, 95.0]
    assert book.total_bid_qty == 10 + 20 + 30

    # 5. Micro-price calculation
    # Best bid is 105.0 (qty 20), Best ask is 108.0 (qty 25)
    # micro_price = (105.0 * 25 + 108.0 * 20) / (20 + 25) = (2625 + 2160) / 45 = 4785 / 45 = 106.3333
    import math

    assert math.isclose(book.micro_price, 106.3333, rel_tol=1e-4)

    # 6. Max depth bounding: inserting 5th element into capacity 4 drops the lowest bid
    book.update_level("BUY", price=103.0, quantity=5)
    book.update_level("BUY", price=104.0, quantity=5)
    # Top 4 bids: 105, 104, 103, 100 (95 is dropped)
    assert len(book.get_bids()) == 4
    assert [b["price"] for b in book.get_bids()] == [105.0, 104.0, 103.0, 100.0]


def test_bisect_depth_book_rolling_tick_metrics():
    """Verify O(1) rolling VWAP and volatility tracking via internal RollingTickBuffer."""
    book = BisectDepthBook(max_depth=10, tick_buffer_capacity=10)
    assert book.rolling_tick_vwap == 0.0
    assert book.rolling_tick_volatility == 0.0

    # Record series of ticks: 100 @ 10, 102 @ 10, 104 @ 10
    book.record_tick(100.0, 10)
    assert book.rolling_tick_vwap == 100.0
    assert book.rolling_tick_volatility == 0.0

    book.record_tick(102.0, 10)
    assert book.rolling_tick_vwap == 101.0
    assert book.rolling_tick_volatility > 0.0

    book.record_tick(104.0, 10)
    # (100*10 + 102*10 + 104*10) / 30 = 3060 / 30 = 102.0
    assert book.rolling_tick_vwap == 102.0
    assert round(book.rolling_tick_volatility, 2) == 1.63

    book.clear()
    assert book.rolling_tick_vwap == 0.0
    assert book.rolling_tick_volatility == 0.0


def test_bisect_depth_book_simulate_sweep():
    """Verify market sweep slippage modeling across depth levels."""
    book = BisectDepthBook(max_depth=50)
    # Asks: 100.0 (qty 10), 101.0 (qty 20), 102.0 (qty 30)
    book.update_level("SELL", price=100.0, quantity=10)
    book.update_level("SELL", price=101.0, quantity=20)
    book.update_level("SELL", price=102.0, quantity=30)

    # 1. Sweep within inside spread: buy 5 units
    res1 = book.simulate_sweep(side="BUY", quantity=5)
    assert res1["filled_qty"] == 5
    assert res1["unfilled_qty"] == 0
    assert res1["sweep_vwap"] == 100.0
    assert res1["slippage_abs"] == 0.0
    assert res1["slippage_bps"] == 0.0
    assert res1["levels_swept"] == 1
    assert res1["is_fully_fillable"] is True

    # 2. Sweep across multiple levels: buy 25 units
    # Consumes all 10 @ 100.0 + 15 @ 101.0 -> (1000 + 1515) / 25 = 2515 / 25 = 100.60
    res2 = book.simulate_sweep(side="BUY", quantity=25)
    assert res2["filled_qty"] == 25
    assert res2["unfilled_qty"] == 0
    assert res2["sweep_vwap"] == 100.60
    assert res2["slippage_abs"] == 0.60
    # Slippage bps = (0.60 / 100.0) * 10000 = 60 bps
    assert res2["slippage_bps"] == 60.0
    assert res2["levels_swept"] == 2
    assert res2["price_impact"] == 1.0

    # 3. Sweep beyond available depth: buy 100 units (total depth is 60)
    res3 = book.simulate_sweep(side="BUY", quantity=100)
    assert res3["filled_qty"] == 60
    assert res3["unfilled_qty"] == 40
    assert res3["is_fully_fillable"] is False
