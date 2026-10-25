"""
tests/test_order_slicer.py
──────────────────────────
Unit tests for engine/order_slicer.py (TWAP and POV Order Slicing).
"""

from engine.order_slicer import build_twap_schedule, build_pov_schedule


def test_build_twap_schedule_conservation_of_quantity():
    # 1000 shares sliced into 5 slices over 15 minutes
    schedule = build_twap_schedule(
        symbol="RELIANCE",
        side="BUY",
        total_quantity=1000,
        base_limit_price=2900.0,
        duration_minutes=15.0,
        num_slices=5,
        seed=42,
    )

    assert schedule.algorithm == "TWAP"
    assert schedule.num_slices == 5
    assert schedule.total_sliced_quantity == 1000
    assert sum(s.quantity for s in schedule.slices) == 1000

    # First slice should have 0.0 delay (immediate execution)
    assert schedule.slices[0].delay_seconds == 0.0
    # Subsequent delays should be monotonically increasing
    delays = [s.delay_seconds for s in schedule.slices]
    assert delays == sorted(delays)


def test_build_twap_schedule_lot_size_quantization():
    # NIFTY 100 quantity (4 lots of 25) sliced into 3 slices
    schedule = build_twap_schedule(
        symbol="NIFTY",
        side="SELL",
        total_quantity=100,
        base_limit_price=24500.0,
        duration_minutes=10.0,
        num_slices=3,
        lot_size=25,
        seed=123,
    )

    assert schedule.total_sliced_quantity == 100
    for s in schedule.slices:
        assert s.quantity % 25 == 0  # Every slice must be a multiple of lot size 25


def test_build_pov_schedule():
    # 5000 shares, candle volume = 20,000 shares, 5% participation rate (max 1,000 per 5-min candle)
    # Expected slices = ceil(5000 / 1000) = 5 slices
    schedule = build_pov_schedule(
        symbol="TATASTEEL",
        side="BUY",
        total_quantity=5000,
        base_limit_price=150.0,
        estimated_candle_volume=20000,
        participation_rate=0.05,
        candle_interval_minutes=5.0,
    )

    assert schedule.total_sliced_quantity == 5000
    assert schedule.num_slices >= 5
    for s in schedule.slices:
        # Each slice should be around ~1000 shares (5% of 20000)
        assert s.quantity <= 1200
