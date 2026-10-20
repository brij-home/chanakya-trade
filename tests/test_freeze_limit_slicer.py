"""
tests/test_freeze_limit_slicer.py
──────────────────────────────────
Institutional test suite for Exchange Order Quantity Freeze Limits & Smart Iceberg Slicer.
"""

from __future__ import annotations


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


def test_exchange_freeze_limit_resolution():
    """Verify official Indian exchange freeze limits across index and equity F&O."""
    assert get_exchange_freeze_limit("NIFTY") == 1800
    assert get_exchange_freeze_limit("NSE:NIFTY26OCT25000CE") == 1800
    assert get_exchange_freeze_limit("BANKNIFTY") == 900
    assert get_exchange_freeze_limit("NFO:BANKNIFTY26OCT53000PE") == 900
    assert get_exchange_freeze_limit("FINNIFTY") == 1800
    assert get_exchange_freeze_limit("MIDCPNIFTY") == 4200
    assert get_exchange_freeze_limit("SENSEX") == 1000
    assert get_exchange_freeze_limit("BANKEX") == 1000

    # Stock F&O: e.g. RELIANCE lot size 250 -> 250 * 25 = 6,250
    rel_limit = get_exchange_freeze_limit("RELIANCE", lot_size=250)
    assert rel_limit == 6250


def test_slice_quantity_by_freeze_limit():
    """Verify order quantity slicing respects freeze limits and exact lot size multiples."""
    # 1. NIFTY: 4,000 contracts (lot size 65, freeze limit 1,800)
    # Max slice is (1800 // 65) * 65 = 27 * 65 = 1755
    slices_nifty = slice_quantity_by_freeze_limit("NIFTY", total_quantity=4000, lot_size=65)
    assert sum(slices_nifty) == 4000
    assert all(s <= 1800 for s in slices_nifty)
    assert slices_nifty == [1755, 1755, 490]
    # Check lot size integrity:
    assert slices_nifty[0] % 65 == 0
    assert slices_nifty[1] % 65 == 0

    # 2. BANKNIFTY: 2,700 contracts (lot size 30, freeze limit 900)
    # 2700 / 900 = exactly 3 tranches of 900
    slices_bn = slice_quantity_by_freeze_limit("BANKNIFTY", total_quantity=2700, lot_size=30)
    assert slices_bn == [900, 900, 900]
    assert sum(slices_bn) == 2700

    # 3. Small order: 65 contracts on NIFTY
    slices_small = slice_quantity_by_freeze_limit("NIFTY", total_quantity=65, lot_size=65)
    assert slices_small == [65]


def test_smart_execution_plan_forces_iceberg_on_freeze_exceedance():
    """Verify build_smart_execution_plan forces ICEBERG mode when order exceeds freeze limit."""
    plan = build_smart_execution_plan(
        symbol="NIFTY",
        side="BUY",
        total_quantity=3600,
        ltp=25000.0,
        lot_size=65,
    )

    assert plan.routing_mode == "ICEBERG"
    assert "Exchange Freeze Slicer Active" in plan.notes
    assert plan.total_quantity >= 3600
    assert all(t.quantity <= 1800 for t in plan.tranches)


def test_order_lifecycle_freeze_slicing_flow(tmp_path, monkeypatch):
    """Verify end-to-end preview and execution with automatic freeze slicing in Paper mode."""
    test_paper_file = tmp_path / "paper_portfolio.json"
    monkeypatch.setattr("engine.paper.get_paper_file", lambda: test_paper_file)
    monkeypatch.setenv("TOTAL_CAPITAL", "50000000")

    # Preview an institutional order of 3,600 NIFTY contracts (exceeds 1,800 freeze limit)
    preview = preview_order_intent(
        symbol="NIFTY",
        side="BUY",
        quantity=3600,
        price=25000.0,
        order_type="LIMIT",
        product="MIS",
    )

    # Check freeze warning and metadata in charges
    assert preview.charges.get("freeze_limit") == 1800
    assert preview.charges.get("sliced_execution_required") is True
    assert preview.charges.get("suggested_tranches") == 2
    assert "Exchange Freeze Slicer" in preview.charges.get("freeze_warning", "")

    # Confirm order
    confirmed = confirm_order_intent(preview.order_id, preview.preview_hash)
    assert confirmed.status == "CONFIRMED"

    # Execute order
    executed = execute_order_intent(confirmed.order_id)
    assert executed.status == "FILLED_PAPER"
    assert "PAPER-EXEC-SLICED" in str(executed.broker_order_id)
