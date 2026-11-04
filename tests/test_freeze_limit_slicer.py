"""
tests/test_freeze_limit_slicer.py
──────────────────────────────────
Institutional test suite for Exchange Order Quantity Freeze Limits & Smart Iceberg Slicer.
"""

from __future__ import annotations

import pytest

from engine.order_lifecycle import (
    confirm_order_intent,
    execute_order_intent,
    preview_order_intent,
)
from engine.smart_order_router import (
    build_smart_execution_plan,
    get_exchange_freeze_limit,
    slice_quantity_by_freeze_limit,
)


@pytest.fixture
def published_freeze_fixture(monkeypatch):
    """Use explicit published-master-shaped fixtures; never encode current limits in logic tests."""
    quantities = {
        "NIFTY": 1777,
        "BANKNIFTY": 890,
        "FINNIFTY": 1823,
        "MIDCPNIFTY": 2791,
        "SENSEX": 511,
        "BANKEX": 617,
        "RELIANCE": 6137,
    }

    def resolve(symbol, *, segment=None):
        clean = str(symbol).upper().split(":")[-1]
        underlying = next(
            (name for name in quantities if clean == name or clean.startswith(name)), None
        )
        if underlying is None:
            raise RuntimeError(f"No fixture quantity freeze for {symbol}")
        return {"quantity": quantities[underlying], "source": "TEST_FIXTURE"}

    monkeypatch.setattr("market.symbol_master.get_quantity_freeze_info", resolve)
    return quantities


def test_exchange_freeze_limit_resolution(published_freeze_fixture):
    """Planner consumes provider-published limits rather than local constants or lot heuristics."""
    assert get_exchange_freeze_limit("NIFTY") == published_freeze_fixture["NIFTY"]
    assert get_exchange_freeze_limit("NSE:NIFTY26NOV25000CE") == published_freeze_fixture["NIFTY"]
    assert get_exchange_freeze_limit("BANKNIFTY") == published_freeze_fixture["BANKNIFTY"]
    assert (
        get_exchange_freeze_limit("NFO:BANKNIFTY26NOV53000PE")
        == published_freeze_fixture["BANKNIFTY"]
    )
    assert get_exchange_freeze_limit("FINNIFTY") == published_freeze_fixture["FINNIFTY"]
    assert get_exchange_freeze_limit("MIDCPNIFTY") == published_freeze_fixture["MIDCPNIFTY"]
    assert get_exchange_freeze_limit("SENSEX") == published_freeze_fixture["SENSEX"]
    assert get_exchange_freeze_limit("BANKEX") == published_freeze_fixture["BANKEX"]
    assert (
        get_exchange_freeze_limit("NSE:RELIANCE26NOV1200CE", lot_size=250)
        == published_freeze_fixture["RELIANCE"]
    )


def test_slice_quantity_by_freeze_limit(published_freeze_fixture):
    """Verify order quantity slicing respects freeze limits and exact lot size multiples."""
    # 1. NIFTY: the fixture limit is 1,777. Slice to the largest full-lot size below it.
    slices_nifty = slice_quantity_by_freeze_limit("NIFTY", total_quantity=4030, lot_size=65)
    assert sum(slices_nifty) == 4030
    assert all(s <= published_freeze_fixture["NIFTY"] for s in slices_nifty)
    assert slices_nifty == [1755, 1755, 520]
    # Check lot size integrity:
    assert slices_nifty[0] % 65 == 0
    assert slices_nifty[1] % 65 == 0

    # 2. BANKNIFTY: each slice is the largest complete lot count under its fixture limit.
    slices_bn = slice_quantity_by_freeze_limit("BANKNIFTY", total_quantity=2700, lot_size=30)
    assert slices_bn == [870, 870, 870, 90]
    assert sum(slices_bn) == 2700

    # 3. Small order: 65 contracts on NIFTY
    slices_small = slice_quantity_by_freeze_limit("NIFTY", total_quantity=65, lot_size=65)
    assert slices_small == [65]


def test_smart_execution_plan_forces_iceberg_on_freeze_exceedance(published_freeze_fixture):
    """Verify build_smart_execution_plan forces ICEBERG mode when order exceeds freeze limit."""
    plan = build_smart_execution_plan(
        symbol="NIFTY",
        side="BUY",
        total_quantity=3640,
        ltp=25000.0,
        lot_size=65,
    )

    assert plan.routing_mode == "ICEBERG"
    assert "Exchange Freeze Slicer Active" in plan.notes
    assert plan.total_quantity == 3640
    assert all(t.quantity <= published_freeze_fixture["NIFTY"] for t in plan.tranches)


def test_smart_execution_plan_rejects_non_lot_and_non_integer_quantities(published_freeze_fixture):
    with pytest.raises(ValueError, match="exact multiple"):
        build_smart_execution_plan(
            symbol="NIFTY", side="BUY", total_quantity=66, ltp=25000.0, lot_size=65
        )
    with pytest.raises(ValueError, match="positive integer"):
        build_smart_execution_plan(
            symbol="NIFTY", side="BUY", total_quantity=65.5, ltp=25000.0, lot_size=65
        )


def test_vwap_rejects_freeze_below_one_lot(monkeypatch):
    from engine.smart_order_router import build_vwap_pov_execution_plan

    monkeypatch.setattr(
        "market.symbol_master.get_quantity_freeze_info",
        lambda symbol, *, segment=None: {"quantity": 64, "source": "TEST_FIXTURE"},
    )
    with pytest.raises(ValueError, match="below one canonical lot"):
        build_vwap_pov_execution_plan(
            symbol="NIFTY", side="BUY", total_quantity=65, ltp=25000.0, lot_size=65
        )


def test_order_lifecycle_freeze_slicing_flow(tmp_path, monkeypatch, published_freeze_fixture):
    """Verify end-to-end preview and execution with automatic freeze slicing in Paper mode."""
    test_paper_file = tmp_path / "paper_portfolio.json"
    monkeypatch.setattr("engine.paper.get_paper_file", lambda: test_paper_file)
    monkeypatch.setenv("TOTAL_CAPITAL", "50000000")

    # Preview 56 valid NIFTY lots; the fixture limit requires three suggested child orders.
    preview = preview_order_intent(
        symbol="NIFTY",
        side="BUY",
        quantity=3640,
        price=25000.0,
        order_type="LIMIT",
        product="MIS",
    )

    # Check freeze warning and metadata in charges
    assert preview.charges.get("freeze_limit") == published_freeze_fixture["NIFTY"]
    assert preview.charges.get("sliced_execution_required") is True
    assert preview.charges.get("suggested_tranches") == 3
    assert "Exchange Freeze Slicer" in preview.charges.get("freeze_warning", "")

    # Confirm order
    confirmed = confirm_order_intent(preview.order_id, preview.preview_hash)
    assert confirmed.status == "CONFIRMED"

    # Execute order
    executed = execute_order_intent(confirmed.order_id)
    assert executed.status == "FILLED_PAPER"
    assert "PAPER-EXEC-SLICED" in str(executed.broker_order_id)
