"""
Test suite for multi-lot Depth-Sweep VWAP and Slippage No-Chase Enforcement.

Verifies:
1. Pretrade Gate 10 blocks when top-of-book LTP is compliant but Depth-Sweep VWAP
   sweeps through the order book past the no-chase boundary.
2. BisectDepthBook auto-resolution inside validate_pretrade accurately simulates
   market order sweeps based on requested quantity.
3. Order lifecycle preview flags FOMO Depth Sweep violations in charges dictionary.
4. Runaway MARKET orders are blocked when simulated depth-sweep fill price
   exceeds allowed chase percentage above trigger/baseline price.
"""

from engine.pretrade import validate_pretrade, _gate_no_chase
from market.order_book import get_depth_book


def test_gate_no_chase_explicit_depth_sweep_buy_violation():
    """Verify that a buy order is blocked when depth sweep VWAP breaches no-chase boundary."""
    res = _gate_no_chase(
        side="BUY",
        order_type="MARKET",
        ltp=100.0,  # Below boundary 102.0 (top-of-book passes)
        no_chase_boundary=102.0,
        depth_sweep_vwap=104.50,  # Multi-lot impact pushes average fill to 104.50
        segment="EQ",
    )
    assert not res.passed
    assert "FOMO Depth Sweep Violation" in res.reason
    assert "104.50" in res.reason
    assert "102.00" in res.reason
    assert res.details.get("depth_sweep_vwap") == 104.50


def test_gate_no_chase_explicit_depth_sweep_sell_violation():
    """Verify that a sell order is blocked when depth sweep VWAP drops below no-chase boundary."""
    res = _gate_no_chase(
        side="SELL",
        order_type="MARKET",
        ltp=100.0,  # Above boundary 98.0
        no_chase_boundary=98.0,
        depth_sweep_vwap=96.20,  # Sweeping bid depth drops fill to 96.20
        segment="EQ",
    )
    assert not res.passed
    assert "FOMO Depth Sweep Violation" in res.reason
    assert "96.20" in res.reason
    assert "98.00" in res.reason


def test_validate_pretrade_auto_resolves_bisect_depth_book():
    """Verify validate_pretrade queries BisectDepthBook and computes depth sweep VWAP automatically."""
    sym = "TEST_SWEEP_RELIANCE"
    book = get_depth_book(sym)
    # Configure asks: 10 units @ 100.0, 90 units @ 110.0
    book.batch_update(
        bids=[{"price": 99.5, "quantity": 50, "orders": 5}],
        asks=[
            {"price": 100.0, "quantity": 10, "orders": 1},
            {"price": 110.0, "quantity": 90, "orders": 3},
        ],
    )

    # 1. Order for 10 units: fills completely at 100.0 -> within boundary 103.0 -> PASS
    res_small = validate_pretrade(
        symbol=sym,
        side="BUY",
        quantity=10,
        order_type="MARKET",
        ltp=100.0,
        quote_age_seconds=1.0,
        no_chase_boundary=103.0,
        skip_session_check=True,
    )
    assert res_small.is_eligible
    no_chase_gate = res_small.gate_results.get("no_chase")
    assert no_chase_gate is not None
    assert no_chase_gate.passed

    # 2. Order for 100 units: 10@100 + 90@110 = 10900 / 100 = 109.0 VWAP -> breaches 103.0 -> BLOCK
    res_large = validate_pretrade(
        symbol=sym,
        side="BUY",
        quantity=100,
        order_type="MARKET",
        ltp=100.0,
        quote_age_seconds=1.0,
        no_chase_boundary=103.0,
        skip_session_check=True,
    )
    assert not res_large.is_eligible
    assert any("FOMO Depth Sweep Violation" in r for r in res_large.blocking_reasons)
    large_no_chase = res_large.gate_results.get("no_chase")
    assert large_no_chase is not None
    assert not large_no_chase.passed
    assert large_no_chase.details.get("depth_sweep_vwap") == 109.0


def test_validate_pretrade_runaway_market_order_with_sweep():
    """Verify that runaway market orders are blocked if depth sweep pushes price above max chase %."""
    res = validate_pretrade(
        symbol="NIFTY_OPT_TEST",
        side="BUY",
        quantity=50,
        order_type="MARKET",
        ltp=100.0,
        trigger_price=100.0,
        max_chase_pct=3.0,  # Max allowed fill: 103.0
        depth_sweep_vwap=106.0,  # Sweep impact pushes fill to 106.0
        segment="OPT",
        skip_session_check=True,
    )
    assert not res.is_eligible
    assert any("FOMO Market Order Violation" in r for r in res.blocking_reasons)
    assert any("106.00" in r for r in res.blocking_reasons)


def test_order_lifecycle_preview_depth_sweep_charges():
    """Verify preview_order_intent calculates depth_sweep_vwap and flags no_chase_violation."""
    from engine.order_lifecycle import preview_order_intent

    sym = "TEST_LIFECYCLE_TCS"
    book = get_depth_book(sym)
    book.batch_update(
        bids=[{"price": 99.0, "quantity": 50, "orders": 2}],
        asks=[
            {"price": 100.0, "quantity": 5, "orders": 1},
            {"price": 108.0, "quantity": 95, "orders": 4},
        ],
    )

    # Preview 100 shares with no_chase_boundary = 103.0
    intent = preview_order_intent(
        symbol=sym,
        side="BUY",
        quantity=100,
        price=100.0,
        order_type="MARKET",
        product="CNC",
        no_chase_boundary=103.0,
    )

    assert "depth_sweep_vwap" in intent.charges
    # VWAP = (5*100 + 95*108)/100 = (500 + 10260)/100 = 107.60
    assert intent.charges["depth_sweep_vwap"] == 107.6
    assert "no_chase_violation" in intent.charges
    assert "FOMO Depth Sweep Violation" in intent.charges["no_chase_violation"]
