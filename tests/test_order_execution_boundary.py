"""
tests/test_order_execution_boundary.py
──────────────────────────────────────
Real-boundary regression tests for P0-1 and P1-4 acceptance:
1. Authentic execution ingestion via ingest_broker_executions and execute_order_intent.
2. Missing average price, trade ID, or account never fabricates fills into the ledger.
3. Partial fills recorded with independent trade IDs, authentic quantities, and monotonic sequences.
4. Idempotent retry on matching facts vs rejection on conflicting facts.
5. Fee adjustment semantics: identical execution facts with updated charges updates fee.
6. Actual filled quantity differs from intent quantity; only actual filled quantity enters ledger.
7. Statutory charges failure propagates to visible status (ledger_status == 'INGESTION_FAILED').
8. Concurrency test verifying serialized sequence numbers with BEGIN IMMEDIATE locks.
"""

from __future__ import annotations

import concurrent.futures
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.order_lifecycle import (
    record_execution_fill,
    set_ledger_cash_baseline,
    get_internal_ledger_snapshot,
    ingest_broker_executions,
    _get_orders_db,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def clean_test_env(tmp_path: Path, monkeypatch):
    """Use isolated orders.db and fresh environment per test."""
    db_file = tmp_path / "test_boundary_orders.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setenv("TRADING_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_file)
    yield


def test_missing_trade_facts_never_fabricates_fills():
    """Missing authentic trade ID or account never fabricates fallback IDs into ledger."""
    # 1. Reject missing or placeholder account_id
    with pytest.raises(ValueError, match="account_id is required"):
        record_execution_fill(
            account_id="",
            broker_name="FYERS",
            order_id="ORD-001",
            broker_order_id="BRK-001",
            broker_trade_id="TRD-001",
            symbol="RELIANCE",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=2500.0,
            charges=25.0,
        )

    with pytest.raises(ValueError, match="account_id cannot be generic placeholder"):
        record_execution_fill(
            account_id="LIVE_ACCOUNT",
            broker_name="FYERS",
            order_id="ORD-001",
            broker_order_id="BRK-001",
            broker_trade_id="TRD-001",
            symbol="RELIANCE",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=2500.0,
            charges=25.0,
        )

    # 2. Reject missing broker_trade_id
    with pytest.raises(ValueError, match="broker_trade_id is required"):
        record_execution_fill(
            account_id="ACC-REAL-001",
            broker_name="FYERS",
            order_id="ORD-001",
            broker_order_id="BRK-001",
            broker_trade_id="",
            symbol="RELIANCE",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=2500.0,
            charges=25.0,
        )

    # 3. Reject non-finite prices
    with pytest.raises(ValueError, match="fill_price must be a finite positive price"):
        record_execution_fill(
            account_id="ACC-REAL-001",
            broker_name="FYERS",
            order_id="ORD-001",
            broker_order_id="BRK-001",
            broker_trade_id="TRD-001",
            symbol="RELIANCE",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=0.0,
            charges=25.0,
        )


def test_naive_timestamp_rejected():
    """Naive timestamps must be rejected to enforce timezone awareness across audit boundaries."""
    with pytest.raises(ValueError, match="fill_time must be timezone-aware"):
        record_execution_fill(
            account_id="ACC-REAL-001",
            broker_name="FYERS",
            order_id="ORD-001",
            broker_order_id="BRK-001",
            broker_trade_id="TRD-001",
            symbol="RELIANCE",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=10,
            fill_price=2500.0,
            charges=25.0,
            fill_time="2026-11-02 09:30:00",  # Naive, no timezone offset
        )


def test_partial_fills_with_independent_trade_ids_and_sequence():
    """Two partial fills are recorded cleanly with independent trade IDs and monotonic sequence numbers."""
    account_id = "ACC-PARTIAL-001"
    set_ledger_cash_baseline(account_id, 100_000.0, actor="SYSTEM_TEST")

    now_iso = datetime.now(IST).isoformat()

    f1 = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ORD-PARTIAL-1",
        broker_order_id="BRK-ORD-1",
        broker_trade_id="TRD-101",
        symbol="NIFTY26NOV24500CE",
        exchange="NSE",
        segment="OPTIONS",
        side="BUY",
        quantity=50,  # Intent was 100, first partial fill is 50
        fill_price=120.0,
        charges=30.0,
        fill_time=now_iso,
    )
    assert f1["sequence_num"] == 1
    assert f1["is_idempotent_retry"] is False

    f2 = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ORD-PARTIAL-1",
        broker_order_id="BRK-ORD-1",
        broker_trade_id="TRD-102",
        symbol="NIFTY26NOV24500CE",
        exchange="NSE",
        segment="OPTIONS",
        side="BUY",
        quantity=50,  # Second partial fill
        fill_price=122.0,
        charges=30.5,
        fill_time=now_iso,
    )
    assert f2["sequence_num"] == 2
    assert f2["is_idempotent_retry"] is False

    snap = get_internal_ledger_snapshot(account_id)
    assert snap is not None
    assert snap["total_fills_count"] == 2
    assert len(snap["positions"]) == 1
    pos = snap["positions"][0]
    assert pos["quantity"] == 100
    assert pos["average_price"] == (50 * 120.0 + 50 * 122.0) / 100  # 121.0


def test_idempotent_retry_and_conflict_rejection():
    """Duplicate execution retry is idempotent when facts match, and fails visibly when facts conflict."""
    account_id = "ACC-IDEMPOTENT-001"
    set_ledger_cash_baseline(account_id, 50_000.0, actor="SYSTEM_TEST")
    now_iso = datetime.now(IST).isoformat()

    # Initial fill
    f1 = record_execution_fill(
        account_id=account_id,
        broker_name="ZERODHA",
        order_id="ORD-Z1",
        broker_order_id="BRK-Z1",
        broker_trade_id="TRD-Z100",
        symbol="INFY",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=25,
        fill_price=1500.0,
        charges=15.0,
        fill_time=now_iso,
    )
    assert f1["sequence_num"] == 1
    assert f1["is_idempotent_retry"] is False

    # Exact retry with identical facts
    f1_retry = record_execution_fill(
        account_id=account_id,
        broker_name="ZERODHA",
        order_id="ORD-Z1",
        broker_order_id="BRK-Z1",
        broker_trade_id="TRD-Z100",
        symbol="INFY",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=25,
        fill_price=1500.0,
        charges=15.0,
        fill_time=now_iso,
    )
    assert f1_retry["sequence_num"] == 1
    assert f1_retry["is_idempotent_retry"] is True
    assert f1_retry.get("is_fee_adjustment") is False

    # Conflicting retry with different price
    with pytest.raises(ValueError, match="Conflicting duplicate broker execution retry"):
        record_execution_fill(
            account_id=account_id,
            broker_name="ZERODHA",
            order_id="ORD-Z1",
            broker_order_id="BRK-Z1",
            broker_trade_id="TRD-Z100",
            symbol="INFY",
            exchange="NSE",
            segment="EQUITY_INTRADAY",
            side="BUY",
            quantity=25,
            fill_price=1505.0,  # Conflicting price!
            charges=15.0,
            fill_time=now_iso,
        )


def test_authorized_fee_adjustment_semantics():
    """Identical trade facts with updated charges updates fee and returns is_fee_adjustment=True."""
    account_id = "ACC-FEE-001"
    set_ledger_cash_baseline(account_id, 50_000.0, actor="SYSTEM_TEST")
    now_iso = datetime.now(IST).isoformat()

    f1 = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ORD-F1",
        broker_order_id="BRK-F1",
        broker_trade_id="TRD-F100",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=10,
        fill_price=3500.0,
        charges=35.0,
        fill_time=now_iso,
    )
    assert f1["charges"] == 35.0

    # Broker later reports finalized tax / exchange turnover charges update (e.g. from 35.0 to 38.5)
    f1_fee_adj = record_execution_fill(
        account_id=account_id,
        broker_name="FYERS",
        order_id="ORD-F1",
        broker_order_id="BRK-F1",
        broker_trade_id="TRD-F100",
        symbol="TCS",
        exchange="NSE",
        segment="EQUITY_INTRADAY",
        side="BUY",
        quantity=10,
        fill_price=3500.0,
        charges=38.5,  # Adjusted statutory fee
        fill_time=now_iso,
    )
    assert f1_fee_adj["is_idempotent_retry"] is True
    assert f1_fee_adj["is_fee_adjustment"] is True
    assert f1_fee_adj["charges"] == 38.5

    # Check database directly to confirm charges column was updated
    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT charges FROM execution_fills WHERE broker_trade_id = 'TRD-F100'"
        ).fetchone()
        assert row["charges"] == 38.5


def test_ingest_broker_executions_actual_vs_intent_quantity():
    """ingest_broker_executions records only actual filled quantities from authentic broker trade records."""
    account_id = "ACC-INGEST-001"
    set_ledger_cash_baseline(account_id, 100_000.0, actor="SYSTEM_TEST")

    # Intent was 100 shares, but broker executed only 75 shares
    raw_broker_trades = [
        {
            "trade_id": "TRADE-EX-001",
            "order_id": "BRK-ORD-99",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "EQUITY_INTRADAY",
            "side": "BUY",
            "quantity": 75,
            "price": 2400.0,
            "trade_time": datetime.now(IST).isoformat(),
        }
    ]

    broker_res = MagicMock()
    broker_res.raw = {"trades": raw_broker_trades}
    broker_res.order_id = "BRK-ORD-99"

    mock_broker = MagicMock()
    mock_broker.account_id = account_id
    mock_broker.__class__.__name__ = "FyersBroker"

    fills = ingest_broker_executions(
        order_id="ORD-OMS-99",
        broker_order_id="BRK-ORD-99",
        live_broker=mock_broker,
        broker_res=broker_res,
        order_details={
            "symbol": "RELIANCE",
            "side": "BUY",
            "segment": "EQUITY_INTRADAY",
            "exchange": "NSE",
        },
    )

    assert len(fills) == 1
    fill = fills[0]
    assert fill["broker_trade_id"] == "TRADE-EX-001"
    assert fill["quantity"] == 75  # Actual filled, not 100
    assert fill["fill_price"] == 2400.0
    assert fill["charges"] > 0

    snap = get_internal_ledger_snapshot(account_id)
    assert snap["positions"][0]["quantity"] == 75


def test_concurrent_fill_recording_serializes_sequence():
    """Concurrent fill recording uses BEGIN IMMEDIATE to serialize sequence numbers without collision."""
    account_id = "ACC-CONCUR-001"
    set_ledger_cash_baseline(account_id, 1_000_000.0, actor="SYSTEM_TEST")
    now_iso = datetime.now(IST).isoformat()

    def _worker(i: int):
        return record_execution_fill(
            account_id=account_id,
            broker_name="MOCK_BROKER",
            order_id=f"ORD-C-{i}",
            broker_order_id=f"BRK-C-{i}",
            broker_trade_id=f"TRD-CONCUR-{i}",
            symbol="NIFTY",
            exchange="NSE",
            segment="OPTIONS",
            side="BUY",
            quantity=50,
            fill_price=100.0 + i,
            charges=20.0,
            fill_time=now_iso,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_worker, i) for i in range(1, 21)]
        results = [f.result() for f in futures]

    sequences = sorted([r["sequence_num"] for r in results])
    assert sequences == list(range(1, 21))  # Monotonic 1 through 20 with zero duplicates or gaps


def test_charges_failure_propagates_to_ledger_status():
    """Failure in statutory charges calculation propagates to ledger_status == INGESTION_FAILED."""
    account_id = "ACC-CHG-FAIL"
    set_ledger_cash_baseline(account_id, 100_000.0, actor="SYSTEM_TEST")

    # Insert a dummy order in orders_ledger first so it can be updated
    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, preview_hash, idempotency_key, account_id, symbol,
                side, quantity, order_type, product, price, stop_loss, target,
                mode, status, ledger_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ORD-FAIL-1",
                "hash",
                "key-fail-1",
                account_id,
                "TCS",
                "BUY",
                10,
                "LIMIT",
                "MIS",
                3500.0,
                None,
                None,
                "EXECUTE",
                "SUBMITTING",
                "PENDING_FACTS",
                datetime.now(IST).isoformat(),
                datetime.now(IST).isoformat(),
            ),
        )
        conn.commit()

    raw_broker_trades = [
        {
            "trade_id": "EX-TRADE-99991",
            "quantity": 10,
            "price": 3500.0,
            "trade_time": datetime.now(IST).isoformat(),
        }
    ]
    broker_res = MagicMock()
    broker_res.raw = {"trades": raw_broker_trades}

    mock_broker = MagicMock()
    mock_broker.account_id = account_id
    mock_broker.__class__.__name__ = "FyersBroker"

    # Patch calculate_transaction_charges to raise an error
    with patch(
        "engine.order_lifecycle.calculate_transaction_charges",
        side_effect=RuntimeError("Statutory engine error"),
    ):
        with pytest.raises(RuntimeError, match="Statutory engine error"):
            ingest_broker_executions(
                order_id="ORD-FAIL-1",
                broker_order_id="BRK-FAIL-1",
                live_broker=mock_broker,
                broker_res=broker_res,
                order_details={
                    "symbol": "TCS",
                    "side": "BUY",
                    "segment": "EQUITY_INTRADAY",
                    "exchange": "NSE",
                    "account_id": account_id,
                },
            )

    # Verify ledger_status was updated to INGESTION_FAILED
    with _get_orders_db() as conn:
        row = conn.execute(
            "SELECT ledger_status, ledger_error FROM orders_ledger WHERE order_id = 'ORD-FAIL-1'"
        ).fetchone()
        assert row["ledger_status"] == "INGESTION_FAILED"
        assert "Statutory engine error" in row["ledger_error"]
