"""
Unit tests for Institutional TWAP and VWAP / POV execution slicers in engine/smart_order_router.py.
"""

from engine.smart_order_router import (
    build_twap_execution_plan,
    build_vwap_pov_execution_plan,
    build_smart_execution_plan,
    get_exchange_freeze_limit,
    INDIAN_INTRADAY_VOLUME_PROFILE,
)


def test_twap_execution_plan_basic():
    """Verify TWAP slicer disperses lots across duration with pseudo-random jitter."""
    symbol = "NIFTY"
    lot_size = 75
    total_qty = 750  # 10 lots
    ltp = 25000.0

    plan = build_twap_execution_plan(
        symbol=symbol,
        side="BUY",
        total_quantity=total_qty,
        ltp=ltp,
        duration_minutes=30,
        lot_size=lot_size,
        randomize_jitter=True,
    )

    assert plan.routing_mode == "TWAP"
    assert plan.total_quantity == total_qty
    assert plan.total_lots == 10
    assert len(plan.tranches) > 1

    # Verify tranche quantity sum matches total
    sum_tranches = sum(t.quantity for t in plan.tranches)
    assert sum_tranches == total_qty

    # Verify each tranche is a multiple of lot size
    for t in plan.tranches:
        assert t.quantity % lot_size == 0
        assert t.lots == t.quantity // lot_size

    # Verify increasing delays and jitter
    delays = [t.delay_ms for t in plan.tranches]
    assert delays[0] == 0
    assert all(delays[i] < delays[i + 1] for i in range(len(delays) - 1))


def test_twap_execution_plan_no_jitter():
    """Verify TWAP without jitter yields predictable step spacing."""
    symbol = "RELIANCE"
    lot_size = 1
    total_qty = 500
    ltp = 2900.0
    duration_min = 20

    plan = build_twap_execution_plan(
        symbol=symbol,
        side="SELL",
        total_quantity=total_qty,
        ltp=ltp,
        duration_minutes=duration_min,
        lot_size=lot_size,
        num_slices=5,
        randomize_jitter=False,
    )

    assert plan.routing_mode == "TWAP"
    assert len(plan.tranches) == 5
    assert sum(t.quantity for t in plan.tranches) == total_qty

    # With 20 minutes (1,200,000 ms) and 5 slices, step is exactly 240,000 ms
    expected_step_ms = (20 * 60 * 1000) // 5
    for i, t in enumerate(plan.tranches):
        assert t.delay_ms == i * expected_step_ms


def test_twap_freeze_limit_enforcement():
    """Verify TWAP respects exchange RMS freeze limits for massive institutional orders."""
    symbol = "BANKNIFTY"
    lot_size = 30
    freeze_limit = get_exchange_freeze_limit(symbol, lot_size)  # 900
    huge_qty = freeze_limit * 4  # 3600 (120 lots)
    ltp = 52000.0

    plan = build_twap_execution_plan(
        symbol=symbol,
        side="BUY",
        total_quantity=huge_qty,
        ltp=ltp,
        duration_minutes=15,
        num_slices=2,  # Requested 2 slices, but 2 slices would exceed 900 freeze limit!
        lot_size=lot_size,
    )

    # Must automatically expand slice count so no slice exceeds freeze limit
    assert len(plan.tranches) >= 4
    for t in plan.tranches:
        assert t.quantity <= freeze_limit
    assert sum(t.quantity for t in plan.tranches) == huge_qty


def test_vwap_pov_execution_plan_volume_curve():
    """Verify VWAP / POV tranche sizing reflects Indian intraday volume distribution."""
    symbol = "TCS"
    lot_size = 1
    total_qty = 1000
    ltp = 4100.0

    plan = build_vwap_pov_execution_plan(
        symbol=symbol,
        side="BUY",
        total_quantity=total_qty,
        ltp=ltp,
        target_pov_pct=0.08,
        duration_minutes=60,
        lot_size=lot_size,
    )

    assert plan.routing_mode == "VWAP_POV"
    assert plan.total_quantity == total_qty
    assert sum(t.quantity for t in plan.tranches) == total_qty
    assert len(plan.tranches) >= 2

    # In Indian market, the opening bin (09:15-09:45) has significantly higher volume weight
    # than subsequent bins. Tranche 1 should be heavily weighted.
    weights = [bin_info[2] for bin_info in INDIAN_INTRADAY_VOLUME_PROFILE[: len(plan.tranches)]]
    if weights[0] > weights[1]:
        assert plan.tranches[0].quantity >= plan.tranches[1].quantity


def test_vwap_pov_freeze_limit_enforcement():
    """Verify VWAP tranche sizing clamps to freeze limit even in high volume peak bins."""
    symbol = "NIFTY"
    lot_size = 75
    freeze_limit = get_exchange_freeze_limit(symbol, lot_size)  # 1800
    huge_qty = freeze_limit * 3  # 5400
    ltp = 25000.0

    plan = build_vwap_pov_execution_plan(
        symbol=symbol,
        side="SELL",
        total_quantity=huge_qty,
        ltp=ltp,
        target_pov_pct=0.10,
        duration_minutes=60,
        lot_size=lot_size,
    )

    for t in plan.tranches:
        assert t.quantity <= freeze_limit
    assert sum(t.quantity for t in plan.tranches) == huge_qty


def test_smart_execution_plan_override():
    """Verify build_smart_execution_plan routes correctly when TWAP or VWAP_POV are requested."""
    symbol = "INFY"
    qty = 200
    ltp = 1900.0

    plan_twap = build_smart_execution_plan(
        symbol=symbol,
        side="BUY",
        total_quantity=qty,
        ltp=ltp,
        routing_mode_override="TWAP",
        duration_minutes=15,
    )
    assert plan_twap.routing_mode == "TWAP"

    plan_vwap = build_smart_execution_plan(
        symbol=symbol,
        side="BUY",
        total_quantity=qty,
        ltp=ltp,
        routing_mode_override="VWAP_POV",
        duration_minutes=30,
    )
    assert plan_vwap.routing_mode == "VWAP_POV"
