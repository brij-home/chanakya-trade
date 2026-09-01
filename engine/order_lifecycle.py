"""
engine/order_lifecycle.py
─────────────────────────
Typed Order Lifecycle State Machine & Idempotency Protection.

Transitions:
  DRAFT → PREVIEW → CONFIRMED → SUBMITTING → OPEN / FILLED / PARTIAL / REJECTED / UNKNOWN_FREEZE

Guarantees:
  1. Idempotency Key Validation: Prevents duplicate order placement across network retries.
  2. Fail-Closed Unknown State: If a broker response is ambiguous (timeout, 504), freezes order
     state as UNKNOWN_FREEZE to block re-triggering until reconciliation confirms status.
  3. Pre-Trade Risk & Statutory Cost Verification: Computes STT, GST, and SEBI charges before confirmation.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from config.paths import app_data_path
from engine.charges import calculate_transaction_charges
from engine.modes import get_trading_mode
from engine.security_audit import record_audit_event


def _get_db_path() -> Path:
    p = app_data_path("orders.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


OrderStatus = Literal[
    "DRAFT",
    "PREVIEW",
    "PREVIEWED",
    "CONFIRMED",
    "USER_CONFIRMED",
    "SUBMITTING",
    "SUBMITTED_PAPER",
    "OPEN",
    "PARTIALLY_FILLED",
    "FILLED",
    "FILLED_PAPER",
    "CANCELLED",
    "REJECTED",
    "UNKNOWN_FREEZE",
]

OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "SL_LIMIT", "SL_MARKET"]
ProductType = Literal["CNC", "MIS", "NRML"]


def _generate_order_id(is_paper: bool = True) -> str:
    """Generate explicit mode-prefixed order ID. Never use fake broker names."""
    prefix = "PAPER" if is_paper else "LIVE"
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


@dataclass
class OrderIntent:
    order_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    order_type: OrderType = "LIMIT"
    product: ProductType = "MIS"
    exchange: str = "NSE"
    segment: str = "EQUITY_INTRADAY"
    status: OrderStatus = "DRAFT"
    mode: str = "SIMULATE"
    preview_hash: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    broker_order_id: Optional[str] = None
    charges: dict[str, Any] = field(default_factory=dict)
    rejection_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _init_orders_db():
    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders_ledger (
                order_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT 'NSE',
                segment TEXT NOT NULL DEFAULT 'EQUITY_INTRADAY',
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                order_type TEXT NOT NULL,
                product TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                broker_order_id TEXT,
                charges_json TEXT,
                rejection_reason TEXT,
                preview_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(orders_ledger)").fetchall()
        }
        if "exchange" not in existing_cols:
            conn.execute(
                "ALTER TABLE orders_ledger ADD COLUMN exchange TEXT NOT NULL DEFAULT 'NSE'"
            )
        if "segment" not in existing_cols:
            conn.execute(
                "ALTER TABLE orders_ledger ADD COLUMN segment TEXT NOT NULL DEFAULT 'EQUITY_INTRADAY'"
            )
        if "preview_hash" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN preview_hash TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_idemp ON orders_ledger(idempotency_key)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders_ledger(status)")
        conn.commit()


def preview_order_intent(
    symbol: str,
    side: OrderSide,
    quantity: int,
    price: float,
    order_type: OrderType = "LIMIT",
    product: ProductType = "MIS",
    idempotency_key: Optional[str] = None,
    *args,
    **kwargs,
) -> OrderIntent:
    """
    Generate an order preview with statutory Indian charges, concurrency-safe idempotency check,
    authoritative multi-asset instrument resolution, and explicit PAPER-/LIVE- order ID prefix.

    Note: Any client-supplied exchange/segment overrides are strictly ignored;
    exchange and segment are resolved authoritatively from symbol metadata.
    """
    import uuid

    _init_orders_db()
    from market.instruments import resolve_canonical_instrument

    inst = resolve_canonical_instrument(symbol)
    resolved_exchange = inst.exchange

    if inst.segment == "COMMODITY":
        resolved_segment = "COMMODITY"
    elif inst.segment == "CURRENCY":
        resolved_segment = "CURRENCY"
    elif inst.segment in ("FNO", "OPTIONS", "FUTURES") or inst.instrument_type in (
        "OPTION",
        "FUTURE",
    ):
        resolved_segment = (
            "OPTIONS"
            if (
                inst.instrument_type == "OPTION" or "CE" in symbol.upper() or "PE" in symbol.upper()
            )
            else "FUTURES"
        )
    elif inst.segment == "EQUITY" or not inst.segment:
        resolved_segment = "EQUITY_DELIVERY" if product == "CNC" else "EQUITY_INTRADAY"
    else:
        resolved_segment = inst.segment

    mode_info = get_trading_mode()
    mode_name = mode_info.mode.name
    is_paper = not mode_info.is_execute

    if mode_info.is_execute and not idempotency_key:
        raise ValueError("idempotency_key is required for live order preview")

    # For non-live orders without client key, generate random UUID to allow distinct intentional orders
    idemp = idempotency_key or f"IDEMP-{uuid.uuid4().hex}"

    # Canonical request string that cryptographically binds ALL structural parameters and active mode
    canonical_str = (
        f"{resolved_exchange}:{symbol.upper()}:{resolved_segment}:{side}:"
        f"{quantity}:{price:.4f}:{order_type}:{product}:{mode_name}"
    )
    computed_preview_hash = hashlib.sha256(canonical_str.encode()).hexdigest()

    charges = calculate_transaction_charges(
        price=price,
        quantity=quantity,
        segment=resolved_segment,  # type: ignore
        side=side,  # type: ignore
    )

    intent = OrderIntent(
        order_id=_generate_order_id(is_paper=is_paper),
        symbol=symbol.upper(),
        exchange=resolved_exchange,
        segment=resolved_segment,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        product=product,
        idempotency_key=idemp,
        status="PREVIEW",
        mode=mode_name,
        preview_hash=computed_preview_hash,
        charges=charges.to_dict(),
    )

    # Concurrency-safe atomic insert: INSERT ... ON CONFLICT(idempotency_key) DO NOTHING
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
                order_type, product, status, mode, broker_order_id, charges_json,
                rejection_reason, preview_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (
                intent.order_id,
                intent.idempotency_key,
                intent.symbol,
                intent.exchange,
                intent.segment,
                intent.side,
                intent.quantity,
                intent.price,
                intent.order_type,
                intent.product,
                intent.status,
                intent.mode,
                intent.broker_order_id,
                json.dumps(intent.charges),
                intent.rejection_reason,
                intent.preview_hash,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

        # Authoritatively re-read the row (either just inserted or previously existing)
        row = conn.execute(
            "SELECT * FROM orders_ledger WHERE idempotency_key = ?", (idemp,)
        ).fetchone()
        if not row:
            raise RuntimeError(
                f"Failed to persist or fetch order intent for idempotency key '{idemp}'."
            )
        d = dict(row)

    # Refuse cross-mode idempotency reuse
    if d["mode"] != mode_name:
        raise PermissionError(
            f"Idempotency key '{idemp}' was created under mode {d['mode']}, but active mode is {mode_name}. "
            "Cross-mode order intent reuse is strictly prohibited."
        )

    # Verify parameter hash integrity
    if d.get("preview_hash") and d["preview_hash"] != computed_preview_hash:
        raise ValueError(
            f"Idempotency key '{idemp}' matches an existing order with mismatched parameters."
        )

    saved_intent = OrderIntent(
        order_id=d["order_id"],
        idempotency_key=d["idempotency_key"],
        symbol=d["symbol"],
        exchange=d.get("exchange", resolved_exchange),
        segment=d.get("segment", resolved_segment),
        side=d["side"],  # type: ignore
        quantity=d["quantity"],
        price=d["price"],
        order_type=d["order_type"],  # type: ignore
        product=d["product"],  # type: ignore
        status=d["status"],  # type: ignore
        mode=d["mode"],
        broker_order_id=d["broker_order_id"],
        charges=json.loads(d["charges_json"] or "{}"),
        rejection_reason=d["rejection_reason"],
        preview_hash=d.get("preview_hash", computed_preview_hash),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )

    record_audit_event(
        event_type="ORDER_PREVIEW_GENERATED",
        mode=saved_intent.mode,
        actor="SYSTEM",
        details={
            "order_id": saved_intent.order_id,
            "symbol": saved_intent.symbol,
            "exchange": saved_intent.exchange,
            "segment": saved_intent.segment,
            "side": saved_intent.side,
            "qty": saved_intent.quantity,
            "preview_hash": saved_intent.preview_hash,
        },
    )

    return saved_intent


def confirm_order_intent(order_id: str, preview_hash: Optional[str] = None) -> OrderIntent:
    """
    Transition a PREVIEW order to CONFIRMED state with mode and preview hash validation.
    """
    _init_orders_db()
    mode_info = get_trading_mode()
    now_iso = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,)).fetchone()
        if not row:
            raise ValueError(f"Order {order_id} not found.")
        d = dict(row)

        if d["mode"] != mode_info.mode.name:
            raise PermissionError(
                f"Order {order_id} was generated in {d['mode']} mode but confirmation was attempted in "
                f"{mode_info.mode.name} mode. Cross-mode confirmation is strictly prohibited."
            )

        if preview_hash and d.get("preview_hash") and d["preview_hash"] != preview_hash:
            raise ValueError("preview_hash mismatch: order parameters have changed since preview.")

        if d["status"] == "CONFIRMED":
            return _row_to_intent(d)

        if d["status"] != "PREVIEW":
            raise ValueError(
                f"Order {order_id} cannot be confirmed because current status is '{d['status']}'."
            )

        cursor = conn.execute(
            """
            UPDATE orders_ledger
            SET status = 'CONFIRMED', updated_at = ?
            WHERE order_id = ? AND status = 'PREVIEW' AND mode = ?
            """,
            (now_iso, order_id, mode_info.mode.name),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Concurrent state conflict confirming order {order_id}.")

        updated_row = conn.execute(
            "SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,)
        ).fetchone()
        return _row_to_intent(dict(updated_row))


def _row_to_intent(d: dict) -> OrderIntent:
    return OrderIntent(
        order_id=d["order_id"],
        idempotency_key=d["idempotency_key"],
        symbol=d["symbol"],
        exchange=d.get("exchange", "NSE"),
        segment=d.get("segment", "EQUITY_INTRADAY"),
        side=d["side"],  # type: ignore
        quantity=d["quantity"],
        price=d["price"],
        order_type=d["order_type"],  # type: ignore
        product=d["product"],  # type: ignore
        status=d["status"],  # type: ignore
        mode=d["mode"],
        broker_order_id=d.get("broker_order_id"),
        charges=json.loads(d.get("charges_json") or "{}"),
        rejection_reason=d.get("rejection_reason"),
        preview_hash=d.get("preview_hash"),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
    )


def execute_order_intent(order_id: str) -> OrderIntent:
    """
    Transition an order into execution.

    P0 Safety & Guardrail Contracts:
      1. Cross-Mode Protection: Refuses execution if current global runtime mode does not
         match the exact mode in which the preview was generated. Prevents paper previews
         from executing live capital upon mode switch.
      2. Double Confirmation Gate: Live execution (EXECUTE mode) strictly requires CONFIRMED status.
         Orders in PREVIEW status cannot be executed without prior explicit confirmation.
      3. Anti-Replay & State Guard: Re-execution of terminal (FILLED, REJECTED, UNKNOWN_FREEZE)
         or already in-flight orders raises ValueError / conflict.
      4. Single Atomic Transition: Performs an atomic DB status lock (CONFIRMED -> SUBMITTING in live,
         PREVIEW/CONFIRMED -> SUBMITTING in paper) bound to active mode.
      5. Preview Hash Integrity: Cryptographically verifies stored preview_hash against canonical
         recomputed parameters before initiating any broker submission.
      6. Fail-Closed Live OMS: Live execution requires ALLOW_LIVE_TRADING=1, fresh quote context,
         passing pretrade risk gates, and never fabricates mock orders or IDs on timeout.
    """
    _init_orders_db()
    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Order {order_id} not found.")

        d = dict(row)

    mode_info = get_trading_mode()
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── P0 Invariant 1: Cross-Mode Protection ──────────────────────────────
    if d["mode"] != mode_info.mode.name:
        raise PermissionError(
            f"Order {order_id} was generated in {d['mode']} mode but execution was attempted in "
            f"{mode_info.mode.name} mode. Cross-mode order execution is strictly prohibited."
        )

    # ── P0 Invariant 2: Double Confirmation Gate for Live Execution ───────
    if mode_info.is_execute:
        if d["status"] == "PREVIEW":
            raise ValueError(
                f"Order {order_id} must be CONFIRMED before live execution. Direct execution from PREVIEW is prohibited."
            )
        if d["status"] != "CONFIRMED":
            raise ValueError(
                f"Order {order_id} cannot be executed because its current status is '{d['status']}'."
            )
    else:
        if d["status"] not in ("PREVIEW", "CONFIRMED"):
            raise ValueError(
                f"Order {order_id} cannot be executed because its current status is '{d['status']}'. "
                "Re-execution of terminal or already active/submitted orders is strictly prohibited."
            )

    # ── P0 Invariant 3: Preview Hash Integrity Verification ────────────────
    canonical_str = (
        f"{d.get('exchange', 'NSE')}:{d['symbol'].upper()}:{d.get('segment', 'EQUITY_INTRADAY')}:{d['side']}:"
        f"{d['quantity']}:{float(d['price']):.4f}:{d['order_type']}:{d['product']}:{d['mode']}"
    )
    expected_hash = hashlib.sha256(canonical_str.encode()).hexdigest()
    if d.get("preview_hash") and d["preview_hash"] != expected_hash:
        raise ValueError(
            f"Order {order_id} preview hash verification failed (intent parameters were tampered with or corrupted)."
        )

    # ── P0 Invariant 4: Single Atomic Transition to SUBMITTING ───────────
    allowed_statuses = ("CONFIRMED",) if mode_info.is_execute else ("PREVIEW", "CONFIRMED")
    placeholders = ",".join("?" for _ in allowed_statuses)
    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        cursor = conn.execute(
            f"""
            UPDATE orders_ledger
            SET status = 'SUBMITTING', updated_at = ?
            WHERE order_id = ? AND status IN ({placeholders}) AND mode = ?
            """,
            (now_iso, order_id, *allowed_statuses, mode_info.mode.name),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(
                f"Order {order_id} state transition to SUBMITTING failed (order is not in required state {allowed_statuses}, mode mismatch, or already submitted)."
            )

    d["status"] = "SUBMITTING"

    if mode_info.is_observe:
        d["status"] = "REJECTED"
        d["rejection_reason"] = "Mutation blocked: System is operating in OBSERVE mode."
        with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
            conn.execute(
                "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                (d["status"], d["rejection_reason"], now_iso, order_id),
            )
            conn.commit()
        record_audit_event(
            "ORDER_REJECTED_OBSERVE_MODE", mode="OBSERVE", details={"order_id": order_id}
        )
    elif mode_info.is_simulate:
        # Paper trading execution: apply to PaperBroker for balance & position tracking
        try:
            from brokers.base import OrderRequest
            from engine.paper import PaperBroker
            from market.instruments import resolve_canonical_instrument

            inst = resolve_canonical_instrument(d["symbol"])
            _paper_exchange = d.get("exchange") or inst.exchange

            paper_broker = PaperBroker()
            req = OrderRequest(
                symbol=d["symbol"],
                exchange=_paper_exchange,
                transaction_type=d["side"],
                order_type=d["order_type"],
                product=d["product"],
                quantity=d["quantity"],
                price=d["price"],
            )
            paper_res = paper_broker.place_order(req)
            if paper_res.status == "COMPLETE":
                d["status"] = "FILLED_PAPER"
                d["broker_order_id"] = f"PAPER-EXEC-{paper_res.order_id}"
            elif paper_res.status == "REJECTED":
                d["status"] = "REJECTED"
                d["rejection_reason"] = paper_res.message or "Rejected by PaperBroker"
            else:
                d["status"] = "OPEN"
                d["broker_order_id"] = f"PAPER-OPEN-{paper_res.order_id}"
        except Exception as paper_exc:
            d["status"] = "REJECTED"
            d["rejection_reason"] = f"PaperBroker error: {paper_exc}"
            d["broker_order_id"] = None

        with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
            conn.execute(
                "UPDATE orders_ledger SET status = ?, broker_order_id = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                (d["status"], d["broker_order_id"], d["rejection_reason"], now_iso, order_id),
            )
            conn.commit()

        record_audit_event(
            event_type="ORDER_FILLED_PAPER" if d["status"] == "FILLED_PAPER" else "ORDER_REJECTED",
            mode=mode_info.mode.name,
            details={
                "order_id": order_id,
                "broker_order_id": d["broker_order_id"],
                "status": d["status"],
                "rejection_reason": d.get("rejection_reason"),
            },
        )
    else:
        # ── Live broker execution ───────────────────────────────────────────
        from engine.modes import assert_live_execution_allowed

        assert_live_execution_allowed()  # raises PermissionError if not EXECUTE + ALLOW_LIVE_TRADING=1

        # Safety gate 2: pre-trade validation with live market context
        from engine.pretrade import validate_pretrade
        from engine.observability import new_correlation_id
        from market.instruments import resolve_canonical_instrument

        pretrade_correlation_id = new_correlation_id("live_order")
        inst = resolve_canonical_instrument(d["symbol"])
        _live_exchange = d.get("exchange") or inst.exchange
        _live_segment = d.get("segment") or inst.segment

        # Fetch live quote + broker funds BEFORE calling validate_pretrade.
        _ltp: float | None = None
        _quote_age_seconds: float | None = None
        _available_cash: float | None = None
        _account: str | None = None

        try:
            from brokers.session import get_broker as _get_broker_inner

            _ctx_broker = _get_broker_inner()
            if _ctx_broker is None:
                raise RuntimeError("No authenticated broker session for pretrade context fetch.")

            _account = getattr(_ctx_broker, "account_id", None) or getattr(
                _ctx_broker, "client_id", None
            )

            # Fetch live quote using authoritative exchange prefix
            _instrument = f"{_live_exchange}:{d['symbol']}"
            _quote_fetched_at = datetime.now(timezone.utc)
            _quotes = _ctx_broker.get_quote([_instrument])
            _q = (
                _quotes.get(_instrument)
                if isinstance(_quotes, dict)
                else (
                    next(
                        (
                            q
                            for q in _quotes
                            if getattr(q, "symbol", None) in (_instrument, d["symbol"])
                        ),
                        None,
                    )
                    if _quotes
                    else None
                )
            )
            if _q is not None:
                _ltp = getattr(_q, "last_price", None)
            _quote_age_seconds = (datetime.now(timezone.utc) - _quote_fetched_at).total_seconds()

            _funds = _ctx_broker.get_funds()
            _available_cash = (
                _funds.available_cash
                if hasattr(_funds, "available_cash")
                else float(_funds.get("available_cash", 0.0))
                if isinstance(_funds, dict)
                else None
            )

        except Exception as _ctx_exc:
            d["status"] = "UNKNOWN_FREEZE"
            d["rejection_reason"] = f"Live pretrade context fetch failed: {_ctx_exc}."
            with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                    (d["status"], d["rejection_reason"], now_iso, order_id),
                )
                conn.commit()
            raise RuntimeError(
                f"Live order {order_id} frozen (pretrade context fetch failed): {_ctx_exc}"
            ) from _ctx_exc

        pretrade = validate_pretrade(
            symbol=d["symbol"],
            side=d["side"],
            quantity=d["quantity"],
            order_type=d["order_type"],
            price=d["price"] if d["price"] else None,
            segment=_live_segment,
            account=_account,
            ltp=_ltp,
            quote_age_seconds=_quote_age_seconds,
            available_cash=_available_cash,
            correlation_id=pretrade_correlation_id,
        )
        if not pretrade.is_eligible:
            reasons = "; ".join(pretrade.blocking_reasons)
            d["status"] = "REJECTED"
            d["rejection_reason"] = f"Pre-trade validation blocked: {reasons}"
            with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                    (d["status"], d["rejection_reason"], now_iso, order_id),
                )
                conn.commit()
            raise ValueError(f"Pre-trade validation blocked: {reasons}")

        # Safety gate 3: submit to real broker adapter
        try:
            from brokers.session import get_broker
            from brokers.base import OrderRequest

            live_broker = get_broker()
            if live_broker is None:
                raise RuntimeError("No authenticated broker session available for live execution.")

            broker_req = OrderRequest(
                symbol=d["symbol"],
                exchange=_live_exchange,
                transaction_type=d["side"],
                order_type=d["order_type"],
                product=d["product"],
                quantity=d["quantity"],
                price=d["price"],
            )

            broker_res = live_broker.place_order(broker_req)

            if broker_res.status == "COMPLETE" or broker_res.status == "OPEN":
                d["status"] = "OPEN" if broker_res.status == "OPEN" else "FILLED"
                d["broker_order_id"] = broker_res.order_id

                with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET status = ?, broker_order_id = ?, updated_at = ? WHERE order_id = ?",
                        (d["status"], d["broker_order_id"], now_iso, order_id),
                    )
                    conn.commit()

            elif broker_res.status == "REJECTED":
                d["status"] = "REJECTED"
                d["rejection_reason"] = broker_res.message or "Rejected by live broker"

                with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                        (d["status"], d["rejection_reason"], now_iso, order_id),
                    )
                    conn.commit()
            else:
                # Ambiguous state -> freeze
                d["status"] = "UNKNOWN_FREEZE"
                d["broker_order_id"] = None
                d["rejection_reason"] = (
                    f"Ambiguous broker response status: {broker_res.status}. "
                    "Order frozen for manual reconciliation."
                )

                with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET status = ?, broker_order_id = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                        (
                            d["status"],
                            d["broker_order_id"],
                            d["rejection_reason"],
                            now_iso,
                            order_id,
                        ),
                    )
                    conn.commit()

                record_audit_event(
                    event_type="ORDER_UNKNOWN_FREEZE",
                    mode=mode_info.mode.name,
                    details={
                        "order_id": order_id,
                        "correlation_id": pretrade_correlation_id,
                        "broker_response_status": broker_res.status,
                    },
                )

        except Exception as live_exc:
            # Ambiguous or timed-out broker call: MUST NOT fabricate order ID or set OPEN.
            d["status"] = "UNKNOWN_FREEZE"
            d["broker_order_id"] = None
            d["rejection_reason"] = (
                f"Live broker call raised {type(live_exc).__name__}: {live_exc}. "
                "Order status ambiguous; frozen for manual reconciliation."
            )

            with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = ?, broker_order_id = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                    (d["status"], d["broker_order_id"], d["rejection_reason"], now_iso, order_id),
                )
                conn.commit()

            record_audit_event(
                event_type="ORDER_UNKNOWN_FREEZE",
                mode=mode_info.mode.name,
                details={
                    "order_id": order_id,
                    "correlation_id": pretrade_correlation_id,
                    "exception": str(live_exc),
                },
            )
            raise RuntimeError(
                f"Live order {order_id} frozen in UNKNOWN_FREEZE state due to broker exception: {live_exc}"
            ) from live_exc

    return OrderIntent(
        order_id=d["order_id"],
        idempotency_key=d["idempotency_key"],
        symbol=d["symbol"],
        exchange=d.get("exchange", "NSE"),
        segment=d.get("segment", "EQUITY_INTRADAY"),
        side=d["side"],  # type: ignore
        quantity=d["quantity"],
        price=d["price"],
        order_type=d["order_type"],  # type: ignore
        product=d["product"],  # type: ignore
        status=d["status"],  # type: ignore
        mode=d["mode"],
        broker_order_id=d.get("broker_order_id"),
        charges=json.loads(d.get("charges_json") or "{}"),
        rejection_reason=d.get("rejection_reason"),
        preview_hash=d.get("preview_hash"),
        created_at=d.get("created_at", now_iso),
        updated_at=now_iso,
    )
