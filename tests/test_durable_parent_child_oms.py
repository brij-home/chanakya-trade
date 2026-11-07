"""
tests/test_durable_parent_child_oms.py
──────────────────────────────────────
Comprehensive verification of Phase 2 Durable Parent-Child Order Tracking & Recovery:
1. Paper mode freeze-slicing pre-persists child orders in orders_ledger with parent_order_id, slice_index, total_slices.
2. Complete execution across all child slices rolls up parent status (FILLED_PAPER), filled_quantity, and average_fill_price.
3. Partial fill behavior: child 1 fills, child 2 rejects -> parent transitions to PARTIALLY_FILLED with verified metrics.
4. Live qualification gate: LIVE_EXECUTION_QUALIFIED=0 blocks live slicing; LIVE_EXECUTION_QUALIFIED=1 allows durable child tracking.
5. Fail-closed UNKNOWN_FREEZE: Network exception on child tranche freezes child order and rolls parent to UNKNOWN_FREEZE.
6. Recovery worker cycle reconciles ambiguous child tranches from broker orders and automatically rolls up parent order.
7. REST API endpoints GET /api/orders/{order_id} and GET /api/orders/{order_id}/children return verified schemas.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from brokers.base import Quote, Funds, OrderResponse
from engine.order_lifecycle import (
    preview_order_intent,
    confirm_order_intent,
    execute_order_intent,
    get_order_intent,
    get_child_orders,
)
from engine.recovery_worker import run_recovery_cycle
from web.api import app


@pytest.fixture(autouse=True)
def clean_orders_db(tmp_path, monkeypatch):
    """Hermetic SQLite database isolation for each test."""
    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    monkeypatch.delenv("LIVE_EXECUTION_QUALIFIED", raising=False)


def test_paper_sliced_order_persists_child_ledger_records(monkeypatch):
    """Paper mode freeze slicing creates durable child orders with parent-child linkage."""
    monkeypatch.setattr(
        "engine.smart_order_router.slice_quantity_by_freeze_limit",
        lambda symbol, quantity, lot_size, **kwargs: [100, 100, 50],
    )

    class MockPB:
        def place_order(self, req):
            return OrderResponse(
                order_id=f"PB-{req.quantity}",
                status="COMPLETE",
                average_price=800.0,
                filled_quantity=req.quantity,
            )

    monkeypatch.setattr("engine.paper.PaperBroker", MockPB)

    intent = preview_order_intent(
        symbol="SBIN",
        side="BUY",
        quantity=250,
        price=800.0,
        idempotency_key="TEST-PAPER-SLICE-1",
        auto_gtt_oco=False,
    )
    confirmed = confirm_order_intent(intent.order_id, intent.preview_hash or "")
    executed = execute_order_intent(confirmed.order_id)

    assert executed.status == "FILLED_PAPER"
    assert executed.filled_quantity == 250
    assert executed.average_fill_price == 800.0
    assert "PAPER-EXEC-SLICED-" in str(executed.broker_order_id)

    # Verify parent retrieval
    parent = get_order_intent(executed.order_id)
    assert parent is not None
    assert parent.order_id == executed.order_id
    assert parent.filled_quantity == 250
    assert parent.parent_order_id is None

    # Verify children retrieval
    children = get_child_orders(executed.order_id)
    assert len(children) == 3
    assert [c.slice_index for c in children] == [1, 2, 3]
    assert [c.total_slices for c in children] == [3, 3, 3]
    assert [c.quantity for c in children] == [100, 100, 50]
    assert [c.filled_quantity for c in children] == [100, 100, 50]
    assert all(c.parent_order_id == executed.order_id for c in children)
    assert all(c.status == "FILLED_PAPER" for c in children)


def test_paper_sliced_order_partial_rejection(monkeypatch):
    """When child slice 2 rejects, parent transitions to PARTIALLY_FILLED and slice 3 is skipped."""
    monkeypatch.setattr(
        "engine.smart_order_router.slice_quantity_by_freeze_limit",
        lambda symbol, quantity, lot_size, **kwargs: [100, 100, 100],
    )

    call_count = 0

    class MockPaperBroker:
        def place_order(self, req):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(
                    status="COMPLETE", order_id="PB-101", message="", average_price=800.0
                )
            elif call_count == 2:
                return MagicMock(
                    status="REJECTED",
                    order_id="PB-102",
                    message="Margin ceiling hit",
                    average_price=0.0,
                )
            return MagicMock(status="COMPLETE", order_id="PB-103", message="", average_price=800.0)

    monkeypatch.setattr("engine.paper.PaperBroker", MockPaperBroker)

    intent = preview_order_intent(
        symbol="SBIN",
        side="BUY",
        quantity=300,
        price=800.0,
        idempotency_key="TEST-PAPER-PARTIAL-1",
        auto_gtt_oco=False,
    )
    confirm_order_intent(intent.order_id, intent.preview_hash or "")
    executed = execute_order_intent(intent.order_id)

    assert executed.status == "PARTIALLY_FILLED"
    assert executed.filled_quantity == 100
    assert "Margin ceiling hit" in str(executed.rejection_reason)
    assert call_count == 2  # Tranche 3 never dispatched

    children = get_child_orders(intent.order_id)
    assert len(children) == 3
    assert children[0].status == "FILLED_PAPER"
    assert children[0].filled_quantity == 100
    assert children[1].status == "REJECTED"
    assert children[1].filled_quantity == 0
    # Tranche 3 stayed in pre-persisted CONFIRMED state
    assert children[2].status == "CONFIRMED"


def _setup_live_environment(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("PILOT_ALLOW_LIVE_EXECUTION", "1")
    monkeypatch.setenv("PILOT_ALLOWED_SEGMENTS", "EQUITY_INTRADAY")
    monkeypatch.setenv("PILOT_ALLOWED_PRODUCTS", "MIS")
    monkeypatch.setenv("PILOT_MAX_ORDER_NOTIONAL", "10000000")
    monkeypatch.setattr("engine.modes.assert_live_execution_allowed", lambda: None)
    monkeypatch.setattr(
        "engine.pretrade.validate_pretrade",
        lambda *args, **kwargs: MagicMock(passed=True, errors=[]),
    )
    monkeypatch.setattr(
        "engine.recovery_worker.has_active_unknown_freeze", lambda *args, **kwargs: False
    )

    from datetime import datetime, timezone

    mock_q = Quote(
        symbol="NSE:TCS",
        last_price=3500.0,
        data_state="LIVE",
        received_at=datetime.now(timezone.utc).isoformat(),
        provider="mock",
    )
    monkeypatch.setattr(
        "market.quotes.get_quote", lambda *args, **kwargs: {"NSE:TCS": mock_q, "TCS": mock_q}
    )


def test_live_sliced_qualification_gate(monkeypatch):
    """LIVE_EXECUTION_QUALIFIED=0 blocks live slicing; LIVE_EXECUTION_QUALIFIED=1 executes child tracking."""
    _setup_live_environment(monkeypatch)
    monkeypatch.setattr(
        "engine.smart_order_router.slice_quantity_by_freeze_limit",
        lambda symbol, quantity, lot_size, **kwargs: [10, 10],
    )

    intent = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=20,
        price=3500.0,
        idempotency_key="TEST-LIVE-QUAL-GATE-1",
        auto_gtt_oco=False,
    )
    confirm_order_intent(intent.order_id, intent.preview_hash or "")

    # 1. Unqualified -> PermissionError and stays CONFIRMED
    monkeypatch.delenv("LIVE_EXECUTION_QUALIFIED", raising=False)
    with pytest.raises(PermissionError, match="Live freeze-limit sliced orders are disabled"):
        execute_order_intent(intent.order_id)

    parent_unqual = get_order_intent(intent.order_id)
    assert parent_unqual is not None
    assert parent_unqual.status == "CONFIRMED"

    # 2. Qualified -> Executes durable slicing
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")
    mock_broker = MagicMock()
    mock_broker.account_id = "TEST_LIVE_ACC"
    mock_broker.get_funds.return_value = Funds(
        available_cash=500_000.0, used_margin=0.0, total_balance=500_000.0
    )
    mock_broker.place_order.side_effect = [
        MagicMock(
            status="COMPLETE", order_id="BROKER-TR-1", filled_quantity=10, average_price=3500.0
        ),
        MagicMock(
            status="COMPLETE", order_id="BROKER-TR-2", filled_quantity=10, average_price=3500.0
        ),
    ]
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_broker)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mockbroker")

    executed = execute_order_intent(intent.order_id)
    assert executed.status == "FILLED"
    assert executed.filled_quantity == 20
    assert executed.average_fill_price == 3500.0
    assert executed.broker_order_id == "SLICED:BROKER-TR-1,BROKER-TR-2"

    children = get_child_orders(intent.order_id)
    assert len(children) == 2
    assert children[0].status == "FILLED"
    assert children[0].broker_order_id == "BROKER-TR-1"
    assert children[1].status == "FILLED"
    assert children[1].broker_order_id == "BROKER-TR-2"


def test_live_sliced_tranche_network_exception_freezes_child_and_parent(monkeypatch):
    """If broker call throws network exception on slice 2, slice 2 & parent transition to UNKNOWN_FREEZE."""
    _setup_live_environment(monkeypatch)
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")
    monkeypatch.setattr(
        "engine.smart_order_router.slice_quantity_by_freeze_limit",
        lambda symbol, quantity, lot_size, **kwargs: [10, 10],
    )

    intent = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=20,
        price=3500.0,
        idempotency_key="TEST-LIVE-FREEZE-1",
        auto_gtt_oco=False,
    )
    confirm_order_intent(intent.order_id, intent.preview_hash or "")

    mock_broker = MagicMock()
    mock_broker.account_id = "TEST_LIVE_ACC"
    mock_broker.get_funds.return_value = Funds(
        available_cash=500_000.0, used_margin=0.0, total_balance=500_000.0
    )
    mock_broker.place_order.side_effect = [
        MagicMock(
            status="COMPLETE", order_id="BROKER-TR-1", filled_quantity=10, average_price=3500.0
        ),
        ConnectionResetError("Socket reset by peer during tranche 2"),
    ]
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_broker)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mockbroker")

    executed = execute_order_intent(intent.order_id)
    assert executed.status == "UNKNOWN_FREEZE"
    assert "Socket reset by peer" in str(executed.rejection_reason)
    assert executed.filled_quantity == 10

    children = get_child_orders(intent.order_id)
    assert len(children) == 2
    assert children[0].status == "FILLED"
    assert children[0].broker_order_id == "BROKER-TR-1"
    assert children[1].status == "UNKNOWN_FREEZE"
    assert children[1].broker_order_id is None


def test_recovery_worker_reconciles_stuck_child_and_rolls_up_parent(monkeypatch):
    """Recovery worker queries broker order book, recovers stuck child tranche, and rolls up parent order."""
    _setup_live_environment(monkeypatch)
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")
    monkeypatch.setattr(
        "engine.smart_order_router.slice_quantity_by_freeze_limit",
        lambda symbol, quantity, lot_size, **kwargs: [10, 10],
    )

    intent = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=20,
        price=3500.0,
        idempotency_key="TEST-RECOVERY-ROLLUP-1",
        auto_gtt_oco=False,
    )
    confirm_order_intent(intent.order_id, intent.preview_hash or "")

    mock_broker = MagicMock()
    mock_broker.account_id = "TEST_LIVE_ACC"
    mock_broker.get_funds.return_value = Funds(
        available_cash=500_000.0, used_margin=0.0, total_balance=500_000.0
    )
    # First slice succeeds, second slice raises timeout
    mock_broker.place_order.side_effect = [
        MagicMock(
            status="COMPLETE", order_id="BRK-REC-1", filled_quantity=10, average_price=3500.0
        ),
        TimeoutError("Broker gateway timeout"),
    ]
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: mock_broker)
    monkeypatch.setattr("brokers.session.get_execution_broker_key", lambda: "mockbroker")

    execute_order_intent(intent.order_id)

    # Initial state: parent & child 2 are UNKNOWN_FREEZE
    parent_frozen = get_order_intent(intent.order_id)
    assert parent_frozen.status == "UNKNOWN_FREEZE"

    children = get_child_orders(intent.order_id)
    child_2_id = children[1].order_id
    assert children[1].status == "UNKNOWN_FREEZE"

    # Now broker confirms child 2 actually filled on exchange with tag=child_2_id
    mock_broker.get_orders.return_value = [
        MagicMock(
            order_id="BRK-REC-1",
            tag=children[0].order_id,
            status="COMPLETE",
            filled_quantity=10,
            average_price=3500.0,
        ),
        MagicMock(
            order_id="BRK-REC-2",
            tag=child_2_id,
            status="COMPLETE",
            filled_quantity=10,
            average_price=3500.0,
        ),
    ]

    # Run recovery cycle
    report = run_recovery_cycle()
    assert report["recovered_count"] >= 1

    # Verify child 2 recovered
    child_2_rec = get_order_intent(child_2_id)
    assert child_2_rec is not None
    assert child_2_rec.status == "FILLED"
    assert child_2_rec.broker_order_id == "BRK-REC-2"
    assert child_2_rec.filled_quantity == 10

    # Verify parent order automatically rolled up to FILLED with 20 qty!
    parent_rec = get_order_intent(intent.order_id)
    assert parent_rec is not None
    assert parent_rec.status == "FILLED"
    assert parent_rec.filled_quantity == 20
    assert parent_rec.average_fill_price == 3500.0


def test_order_endpoints_via_fastapi(monkeypatch):
    """GET /api/orders/{order_id} and /api/orders/{order_id}/children return verified JSON payloads."""
    monkeypatch.setattr(
        "engine.smart_order_router.slice_quantity_by_freeze_limit",
        lambda symbol, quantity, lot_size, **kwargs: [50, 50],
    )

    class MockPB:
        def place_order(self, req):
            return OrderResponse(
                order_id=f"PB-{req.quantity}",
                status="COMPLETE",
                average_price=1800.0,
                filled_quantity=req.quantity,
            )

    monkeypatch.setattr("engine.paper.PaperBroker", MockPB)

    intent = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=100,
        price=1800.0,
        idempotency_key="TEST-API-ROUTER-1",
        auto_gtt_oco=False,
    )
    confirm_order_intent(intent.order_id, intent.preview_hash or "")
    execute_order_intent(intent.order_id)

    client = TestClient(app)

    # 1. GET /api/orders/{order_id}
    resp = client.get(f"/api/orders/{intent.order_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_id"] == intent.order_id
    assert data["status"] == "FILLED_PAPER"
    assert data["filled_quantity"] == 100

    # 2. GET /api/orders/{order_id}/children
    resp_ch = client.get(f"/api/orders/{intent.order_id}/children")
    assert resp_ch.status_code == 200
    ch_data = resp_ch.json()
    assert len(ch_data) == 2
    assert [c["slice_index"] for c in ch_data] == [1, 2]
    assert [c["quantity"] for c in ch_data] == [50, 50]
    assert all(c["parent_order_id"] == intent.order_id for c in ch_data)

    # 3. 404 for unknown order
    resp_404 = client.get("/api/orders/UNKNOWN-ID-999")
    assert resp_404.status_code == 404
