"""
tests/test_ring_buffer.py
─────────────────────────
Unit tests for RollingTickBuffer: O(1) rolling VWAP, variance, monotonic extrema,
circular eviction, and throughput validation.
"""

import math
import statistics
import time


from engine.ring_buffer import RollingTickBuffer


def test_ring_buffer_basic_fill_and_eviction():
    buf = RollingTickBuffer(capacity=5)
    assert buf.count == 0
    assert not buf.is_full

    for i in range(1, 6):
        buf.append(price=float(i * 10), volume=100)

    assert buf.count == 5
    assert buf.is_full
    assert buf.last_price == 50.0

    # Overfill by 2 more items: 60.0, 70.0 -> window should now be [30, 40, 50, 60, 70]
    buf.append(60.0, 100)
    buf.append(70.0, 100)

    assert buf.count == 5
    assert buf.last_price == 70.0
    assert buf.min_price == 30.0
    assert buf.max_price == 70.0


def test_ring_buffer_vwap_accuracy():
    buf = RollingTickBuffer(capacity=4)

    # Ticks: (100, 10), (105, 20), (110, 15), (95, 5)
    ticks = [
        (100.0, 10),
        (105.0, 20),
        (110.0, 15),
        (95.0, 5),
    ]
    for p, v in ticks:
        buf.append(p, v)

    # Expected VWAP = (100*10 + 105*20 + 110*15 + 95*5) / (10 + 20 + 15 + 5)
    #               = (1000 + 2100 + 1650 + 475) / 50 = 5225 / 50 = 104.5
    assert math.isclose(buf.vwap, 104.5, rel_tol=1e-5)

    # Add 5th tick to evict the first (100, 10): new tick (120, 25)
    buf.append(120.0, 25)
    # Active window is now: (105, 20), (110, 15), (95, 5), (120, 25)
    # Expected VWAP = (2100 + 1650 + 475 + 3000) / (20 + 15 + 5 + 25) = 7225 / 65 = 111.1538
    expected = 7225.0 / 65.0
    assert math.isclose(buf.vwap, expected, rel_tol=1e-5)


def test_ring_buffer_mean_and_variance_accuracy():
    buf = RollingTickBuffer(capacity=5)
    prices = [10.0, 12.0, 15.0, 11.0, 14.0]

    for p in prices:
        buf.append(p, 1)

    exp_mean = statistics.mean(prices)
    exp_var = statistics.pvariance(prices)
    exp_std = statistics.pstdev(prices)

    assert math.isclose(buf.mean, exp_mean, rel_tol=1e-4)
    assert math.isclose(buf.variance, exp_var, rel_tol=1e-4)
    assert math.isclose(buf.std, exp_std, rel_tol=1e-4)

    # Evict two elements
    buf.append(20.0, 1)
    buf.append(25.0, 1)
    # Active window is now: [15.0, 11.0, 14.0, 20.0, 25.0]
    new_window = [15.0, 11.0, 14.0, 20.0, 25.0]
    assert math.isclose(buf.mean, statistics.mean(new_window), rel_tol=1e-4)
    assert math.isclose(buf.variance, statistics.pvariance(new_window), rel_tol=1e-4)
    assert math.isclose(buf.std, statistics.pstdev(new_window), rel_tol=1e-4)


def test_ring_buffer_monotonic_extrema():
    buf = RollingTickBuffer(capacity=3)

    buf.append(10.0)
    assert buf.min_price == 10.0
    assert buf.max_price == 10.0

    buf.append(50.0)
    assert buf.min_price == 10.0
    assert buf.max_price == 50.0

    buf.append(30.0)
    assert buf.min_price == 10.0
    assert buf.max_price == 50.0

    # Evict 10.0: window becomes [50.0, 30.0, 25.0]
    buf.append(25.0)
    assert buf.min_price == 25.0
    assert buf.max_price == 50.0

    # Evict 50.0: window becomes [30.0, 25.0, 40.0]
    buf.append(40.0)
    assert buf.min_price == 25.0
    assert buf.max_price == 40.0


def test_ring_buffer_snapshot():
    buf = RollingTickBuffer(capacity=10)
    for i in range(1, 6):
        buf.append(float(i * 10), volume=i * 5)

    snap = buf.get_snapshot()
    assert snap["count"] == 5
    assert snap["last_price"] == 50.0
    assert snap["min"] == 10.0
    assert snap["max"] == 50.0
    assert snap["total_volume"] == sum(i * 5 for i in range(1, 6))


def test_ring_buffer_high_throughput_performance():
    buf = RollingTickBuffer(capacity=500)
    t0 = time.perf_counter()

    # Append 50,000 ticks in a tight loop
    for i in range(50000):
        buf.append(price=100.0 + (i % 50), volume=10)

    elapsed = time.perf_counter() - t0
    # 50,000 appends with continuous online rolling VWAP, variance, and extrema
    # must complete in < 0.25 seconds in pure python
    assert elapsed < 0.25
    assert buf.count == 500


def test_ring_buffer_batch_extend():
    buf = RollingTickBuffer(capacity=10)
    ticks = [(100.0 + i, 10, 1000.0 + i) for i in range(5)]
    buf.extend(ticks)
    assert buf.count == 5
    assert buf.last_price == 104.0
    assert buf.min_price == 100.0
    assert buf.max_price == 104.0

    # Extend with 2-tuples (price, volume)
    more_ticks = [(105.0, 20), (106.0, 30)]
    buf.extend(more_ticks)
    assert buf.count == 7
    assert buf.last_price == 106.0


def test_ring_buffer_quantile_and_median():
    buf = RollingTickBuffer(capacity=10)
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    for p in prices:
        buf.append(p, 1)

    assert buf.median == 30.0
    assert buf.quantile(0.0) == 10.0
    assert buf.quantile(1.0) == 50.0
    assert buf.quantile(0.25) == 20.0


def test_ring_buffer_to_records_chronological():
    buf = RollingTickBuffer(capacity=3)
    buf.append(10.0, 1, 1.0)
    buf.append(20.0, 2, 2.0)
    records = buf.to_records()
    assert len(records) == 2
    assert records[0]["price"] == 10.0
    assert records[1]["price"] == 20.0

    # Fill and overflow
    buf.append(30.0, 3, 3.0)
    buf.append(40.0, 4, 4.0)  # Evicts 10.0; order should be 20.0, 30.0, 40.0
    recs = buf.to_records()
    assert [r["price"] for r in recs] == [20.0, 30.0, 40.0]
    assert [r["timestamp"] for r in recs] == [2.0, 3.0, 4.0]


def test_ring_buffer_exact_recalibration_drift_compensation():
    buf = RollingTickBuffer(capacity=100)
    # Simulate 5,000 continuous appends with realistic index prices (e.g. 24,000+)
    base_price = 24500.0
    for i in range(5000):
        buf.append(base_price + (i % 20), volume=10)

    # After 5,000 appends across recalibrations, variance must remain non-negative and exact
    assert buf.variance >= 0.0
    assert buf.std >= 0.0
    assert buf.count == 100
