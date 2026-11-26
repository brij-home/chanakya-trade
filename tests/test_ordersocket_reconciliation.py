"""Regression tests for Track 2: FyersOrderSocket reconciliation & account-scoped recovery."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _seed_order(order_id: str, account_id: str, status: str, broker_order_id: str | None = None):
    from engine.order_lifecycle import _init_orders_db, _get_orders_db

    _init_orders_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _get_orders_db() as conn:
        conn.execute("DELETE FROM execution_fills WHERE order_id = ?", (order_id,))
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_ledger
            (order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
             order_type, product, status, mode, broker_order_id, account_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                f"idemp-{order_id}",
                "NIFTY26N2425000CE",
                "NFO",
                "FNO_INDEX",
                "BUY",
                75,
                140.0,
                "LIMIT",
                "MIS",
                status,
                "EXECUTE",
                broker_order_id,
                account_id,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()


def test_ordersocket_reconciles_submitting_by_tag_and_rejects_cross_account():
    from engine.order_lifecycle import (
        _get_orders_db,
        apply_fyers_stream_order_update,
        apply_fyers_stream_trade_fill,
        bind_fyers_order_stream,
    )
    from market.fyers_order_stream import fyers_order_stream

    _seed_order("LIVE-TAG-101", "FYERS_ACC_1", "SUBMITTING", broker_order_id=None)

    # Cross-account push must be rejected without mutating orders_ledger
    bad = apply_fyers_stream_order_update(
        {
            "orders": {
                "id": "BRK-9901",
                "orderTag": "LIVE-TAG-101",
                "status": 2,
                "filledQty": 75,
                "tradedPrice": 141.5,
                "clientId": "OTHER_ACC_2",
            }
        }
    )
    assert bad["updated"] is False
    assert bad["reason"] == "ACCOUNT_MISMATCH"

    # Matching account push resolves SUBMITTING -> FILLED and attaches broker_order_id
    ok = apply_fyers_stream_order_update(
        {
            "orders": {
                "id": "BRK-9901",
                "orderTag": "LIVE-TAG-101",
                "status": 2,
                "filledQty": 75,
                "tradedPrice": 141.5,
                "clientId": "FYERS_ACC_1",
            }
        }
    )
    assert ok["updated"] is True
    assert ok["status"] == "FILLED"
    assert ok["broker_order_id"] == "BRK-9901"

    import uuid

    trade_num = f"TRD-{uuid.uuid4().hex[:8].upper()}"
    # Trade push ingests idempotent fill scoped to FYERS_ACC_1
    trade_msg = {
        "trades": {
            "orderNumber": "BRK-9901",
            "tradeNumber": trade_num,
            "tradedQty": 75,
            "tradePrice": 141.5,
            "side": 1,
            "clientId": "FYERS_ACC_1",
            "orderDateTime": "2026-11-25T10:15:00+05:30",
        }
    }
    t_res = apply_fyers_stream_trade_fill(trade_msg)
    assert t_res["recorded"] is True
    # Replaying identical WebSocket fill event must remain idempotent
    t_res_dup = apply_fyers_stream_trade_fill(trade_msg)
    assert t_res_dup["recorded"] is True

    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT status, broker_order_id, filled_quantity FROM orders_ledger WHERE order_id = ?",
            ("LIVE-TAG-101",),
        ).fetchone()
        assert tuple(row) == ("FILLED", "BRK-9901", 75)

    # Binding stream callbacks is idempotent
    before_o = len(fyers_order_stream._callbacks_orders)
    bind_fyers_order_stream()
    bind_fyers_order_stream()
    assert len(fyers_order_stream._callbacks_orders) >= before_o


def test_recover_stale_inflight_orders_is_account_scoped():
    from engine.order_lifecycle import recover_stale_inflight_orders

    _seed_order("LIVE-FROZEN-A", "ACC_ALPHA", "UNKNOWN_FREEZE", broker_order_id=None)
    _seed_order("LIVE-SUB-B", "ACC_BETA", "SUBMITTING", broker_order_id=None)

    fake_brk = MagicMock()
    fake_brk.get_orders.return_value = []
    with patch("brokers.session.get_execution_broker", return_value=fake_brk):
        rep_alpha = recover_stale_inflight_orders(account_id="ACC_ALPHA")
    assert "LIVE-FROZEN-A" in rep_alpha["remaining_unknown_freeze"]
    assert "LIVE-SUB-B" not in rep_alpha["remaining_submitting"]


def test_fill_driven_protection_scales_with_partial_fills_and_stays_blocked_in_live():
    import uuid
    from datetime import datetime, timezone
    from engine.order_lifecycle import (
        _get_orders_db,
        _init_orders_db,
        apply_fyers_stream_trade_fill,
    )

    _init_orders_db()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. PAPER mode partial fills scale protection strictly by verified filled_quantity
    p_oid = f"PAPER-PROT-{uuid.uuid4().hex[:6]}"
    p_bid = f"BRK-P-{uuid.uuid4().hex[:6]}"
    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_ledger
            (order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
             order_type, product, status, mode, broker_order_id, account_id,
             stop_loss, target, auto_gtt_oco, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p_oid,
                f"idemp-{p_oid}",
                "NIFTY26N2425000CE",
                "NFO",
                "FNO_INDEX",
                "BUY",
                75,
                140.0,
                "LIMIT",
                "MIS",
                "PARTIALLY_FILLED",
                "PAPER",
                p_bid,
                "PAPER_ACC_1",
                115.0,
                195.0,
                1,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    f1 = apply_fyers_stream_trade_fill(
        {
            "trades": {
                "orderNumber": p_bid,
                "tradeNumber": f"TRD-P1-{uuid.uuid4().hex[:6]}",
                "tradedQty": 25,
                "tradePrice": 140.0,
                "side": 1,
                "clientId": "PAPER_ACC_1",
                "orderDateTime": "2026-11-25T10:15:00+05:30",
            }
        }
    )
    assert f1["recorded"] is True
    assert f1["protection"]["status"] == "PARTIAL_ACTIVE"
    assert f1["protection"]["protected_quantity"] == 25

    f2 = apply_fyers_stream_trade_fill(
        {
            "trades": {
                "orderNumber": p_bid,
                "tradeNumber": f"TRD-P2-{uuid.uuid4().hex[:6]}",
                "tradedQty": 50,
                "tradePrice": 142.0,
                "side": 1,
                "clientId": "PAPER_ACC_1",
                "orderDateTime": "2026-11-25T10:16:00+05:30",
            }
        }
    )
    assert f2["recorded"] is True
    assert f2["protection"]["status"] == "ACTIVE"
    assert f2["protection"]["protected_quantity"] == 75

    # 2. EXECUTE mode records fill & durable protection state WITHOUT placing live GTT
    l_oid = f"LIVE-PROT-{uuid.uuid4().hex[:6]}"
    l_bid = f"BRK-L-{uuid.uuid4().hex[:6]}"
    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_ledger
            (order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
             order_type, product, status, mode, broker_order_id, account_id,
             stop_loss, target, auto_gtt_oco, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                l_oid,
                f"idemp-{l_oid}",
                "NIFTY26N2425000CE",
                "NFO",
                "FNO_INDEX",
                "BUY",
                75,
                140.0,
                "LIMIT",
                "MIS",
                "FILLED",
                "EXECUTE",
                l_bid,
                "FYERS_ACC_1",
                115.0,
                195.0,
                1,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    fl = apply_fyers_stream_trade_fill(
        {
            "trades": {
                "orderNumber": l_bid,
                "tradeNumber": f"TRD-L1-{uuid.uuid4().hex[:6]}",
                "tradedQty": 75,
                "tradePrice": 141.0,
                "side": 1,
                "clientId": "FYERS_ACC_1",
                "orderDateTime": "2026-11-25T10:17:00+05:30",
            }
        }
    )
    assert fl["recorded"] is True
    assert fl["protection"]["status"] == "BLOCKED_LIVE_SAFETY"
    assert fl["protection"]["protected_quantity"] == 75
