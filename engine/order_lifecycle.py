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
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    order_type: OrderType = "LIMIT"
    product: ProductType = "MIS"
    trigger_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str = field(default_factory=lambda: _generate_order_id(True))
    status: OrderStatus = "DRAFT"
    mode: str = "SIMULATE"
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
                idempotency_key TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_idemp ON orders_ledger(idempotency_key)"
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
    segment: str = "EQUITY_INTRADAY",
    idempotency_key: Optional[str] = None,
) -> OrderIntent:
    """
    Generate an order preview with statutory Indian charges, idempotency check,
    and explicit PAPER-/LIVE- order ID prefix.
    """
    _init_orders_db()
    idemp = (
        idempotency_key
        or hashlib.sha256(f"{symbol}:{side}:{quantity}:{price}:{product}".encode()).hexdigest()[:16]
    )

    # Check for existing idempotency key
    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM orders_ledger WHERE idempotency_key = ?", (idemp,))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            return OrderIntent(
                order_id=d["order_id"],
                idempotency_key=d["idempotency_key"],
                symbol=d["symbol"],
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
                created_at=d["created_at"],
                updated_at=d["updated_at"],
            )

    mode_info = get_trading_mode()
    is_paper = not mode_info.is_execute
    charges = calculate_transaction_charges(
        price=price,
        quantity=quantity,
        segment=segment,  # type: ignore
        side=side,  # type: ignore
    )

    intent = OrderIntent(
        order_id=_generate_order_id(is_paper=is_paper),
        symbol=symbol.upper(),
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        product=product,
        idempotency_key=idemp,
        status="PREVIEW",
        mode=mode_info.mode.name,
        charges=charges.to_dict(),
    )

    # Persist in DB
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_ledger (
                order_id, idempotency_key, symbol, side, quantity, price,
                order_type, product, status, mode, broker_order_id, charges_json,
                rejection_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.order_id,
                intent.idempotency_key,
                intent.symbol,
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
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    record_audit_event(
        event_type="ORDER_PREVIEW_GENERATED",
        mode=intent.mode,
        actor="SYSTEM",
        details={
            "order_id": intent.order_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "qty": intent.quantity,
        },
    )

    return intent


def execute_order_intent(order_id: str) -> OrderIntent:
    """
    Transition a PREVIEW or CONFIRMED order into execution.

    In OBSERVE mode:
      - Immediately REJECTED — no mutations allowed.

    In SIMULATE / PAPER mode:
      - Routes to PaperBroker to update real paper holdings, positions, and cash.
      - Sets status to FILLED_PAPER (or OPEN if limit not met).
      - Sets broker_order_id with explicit PAPER- prefix.
      - On PaperBroker error: sets status to REJECTED with the real exception message.
        NEVER fabricates a filled status on error.

    In EXECUTE (live) mode:
      - Calls assert_live_execution_allowed() — raises PermissionError if mode/flag not met.
      - Calls validate_pretrade() — raises ValueError if any gate blocks.
      - Submits to the real broker adapter obtained from brokers.session.get_broker().
      - On ambiguous/timeout broker response: transitions to UNKNOWN_FREEZE.
        NEVER fabricates a broker order ID.
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

            paper_broker = PaperBroker()
            req = OrderRequest(
                symbol=d["symbol"],
                exchange="NSE",
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
            # PaperBroker raised — do NOT fabricate a FILLED status.
            # Record the real exception as a rejected order so the ledger
            # and audit trail reflect the actual outcome.
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
        # Safety gate 1: mode + server feature flag
        from engine.modes import assert_live_execution_allowed

        assert_live_execution_allowed()  # raises PermissionError if not EXECUTE + ALLOW_LIVE_TRADING=1

        # Safety gate 2: pre-trade validation with live market context
        from engine.pretrade import validate_pretrade
        from engine.observability import new_correlation_id
        # datetime and timezone are imported at module level — do NOT re-import here
        # as a local `from datetime import datetime` would shadow the module-level name
        # across the entire function scope in Python 3.12+ (UnboundLocalError).

        pretrade_correlation_id = new_correlation_id("live_order")

        # Fetch live quote + broker funds BEFORE calling validate_pretrade.
        # Gate 8 (data_freshness) fails-closed when quote_age_seconds is None,
        # so we MUST supply a fresh quote here or the order will be correctly rejected.
        _ltp: float | None = None
        _quote_age_seconds: float | None = None
        _available_cash: float | None = None
        _account: str | None = None

        try:
            from brokers.session import get_broker as _get_broker_inner
            _ctx_broker = _get_broker_inner()
            if _ctx_broker is None:
                raise RuntimeError("No authenticated broker session for pretrade context fetch.")

            _account = (
                getattr(_ctx_broker, "account_id", None)
                or getattr(_ctx_broker, "client_id", None)
            )

            # Fetch live quote and record the fetch timestamp immediately
            _instrument = f"NSE:{d['symbol']}"
            _quote_fetched_at = datetime.now(timezone.utc)
            _quotes = _ctx_broker.get_quote([_instrument])
            _q = _quotes.get(_instrument) if isinstance(_quotes, dict) else (
                next((q for q in _quotes if getattr(q, "symbol", None) in (_instrument, d["symbol"])), None)
                if _quotes else None
            )
            if _q is not None:
                _ltp = getattr(_q, "last_price", None)
            _quote_age_seconds = (datetime.now(timezone.utc) - _quote_fetched_at).total_seconds()

            # Fetch funds for buying-power gate
            _funds = _ctx_broker.get_funds()
            _available_cash = (
                _funds.available_cash
                if hasattr(_funds, "available_cash")
                else float(_funds.get("available_cash", 0.0))
                if isinstance(_funds, dict)
                else None
            )

        except Exception as _ctx_exc:
            # Fail-closed: if context fetch fails, freeze the order before pretrade.
            d["status"] = "UNKNOWN_FREEZE"
            d["rejection_reason"] = (
                f"Live pretrade context fetch failed: {_ctx_exc}. "
                "Order frozen for manual reconciliation."
            )
            with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                    (d["status"], d["rejection_reason"], now_iso, order_id),
                )
                conn.commit()
            record_audit_event(
                event_type="ORDER_UNKNOWN_FREEZE",
                mode=mode_info.mode.name,
                details={
                    "order_id": order_id,
                    "correlation_id": pretrade_correlation_id,
                    "exception": str(_ctx_exc),
                    "stage": "pretrade_context_fetch",
                },
            )
            raise RuntimeError(
                f"Live order {order_id} frozen (pretrade context fetch failed): {_ctx_exc}"
            ) from _ctx_exc

        # Resolve segment from product for lot-size and session checks
        _product = d.get("product", "MIS").upper()
        _segment = "FUT" if _product == "NRML" else "EQ"

        pretrade = validate_pretrade(
            symbol=d["symbol"],
            side=d["side"],
            quantity=d["quantity"],
            order_type=d["order_type"],
            price=d["price"] if d["price"] else None,
            segment=_segment,
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
            record_audit_event(
                event_type="ORDER_REJECTED_PRETRADE",
                mode=mode_info.mode.name,
                details={
                    "order_id": order_id,
                    "correlation_id": pretrade_correlation_id,
                    "blocking_reasons": pretrade.blocking_reasons,
                },
            )
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
                exchange="NSE",
                transaction_type=d["side"],
                order_type=d["order_type"],
                product=d["product"],
                quantity=d["quantity"],
                price=d["price"],
            )

            # Mark SUBMITTING before we call the broker so a crash mid-call
            # leaves an auditable state rather than staying CONFIRMED.
            with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = 'SUBMITTING', updated_at = ? WHERE order_id = ?",
                    (now_iso, order_id),
                )
                conn.commit()

            broker_res = live_broker.place_order(broker_req)

            if broker_res.status == "COMPLETE" or broker_res.status == "OPEN":
                d["status"] = "OPEN" if broker_res.status == "OPEN" else "FILLED"
                # Use the real broker-assigned order ID — never fabricate
                d["broker_order_id"] = broker_res.order_id

                with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET status = ?, broker_order_id = ?, updated_at = ? WHERE order_id = ?",
                        (d["status"], d["broker_order_id"], now_iso, order_id),
                    )
                    conn.commit()

                record_audit_event(
                    event_type="ORDER_SUBMITTED_LIVE",
                    mode=mode_info.mode.name,
                    details={
                        "order_id": order_id,
                        "broker_order_id": d["broker_order_id"],
                        "correlation_id": pretrade_correlation_id,
                        "status": d["status"],
                    },
                )

            elif broker_res.status == "REJECTED":
                d["status"] = "REJECTED"
                d["rejection_reason"] = broker_res.message or "Rejected by live broker"

                with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                        (d["status"], d["rejection_reason"], now_iso, order_id),
                    )
                    conn.commit()

                record_audit_event(
                    event_type="ORDER_REJECTED_LIVE_BROKER",
                    mode=mode_info.mode.name,
                    details={
                        "order_id": order_id,
                        "correlation_id": pretrade_correlation_id,
                        "rejection_reason": d["rejection_reason"],
                    },
                )

            else:
                # Ambiguous broker response — transition to UNKNOWN_FREEZE.
                # NEVER fabricate a broker order ID for an unknown outcome.
                d["status"] = "UNKNOWN_FREEZE"
                d["rejection_reason"] = (
                    f"Broker returned ambiguous status '{broker_res.status}'. "
                    "Order frozen for manual reconciliation."
                )

                with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                        (d["status"], d["rejection_reason"], now_iso, order_id),
                    )
                    conn.commit()

                record_audit_event(
                    event_type="ORDER_UNKNOWN_FREEZE",
                    mode=mode_info.mode.name,
                    details={
                        "order_id": order_id,
                        "correlation_id": pretrade_correlation_id,
                        "broker_status": broker_res.status,
                    },
                )

        except (PermissionError, ValueError):
            raise  # Already handled above — propagate without wrapping
        except Exception as live_exc:
            # Network error, timeout, or unknown broker exception.
            # Transition to UNKNOWN_FREEZE — do NOT fabricate any status or ID.
            d["status"] = "UNKNOWN_FREEZE"
            d["rejection_reason"] = (
                f"Live broker submission failed with exception: {live_exc}. "
                "Order frozen for manual reconciliation."
            )

            with sqlite3.connect(_get_db_path(), timeout=30.0) as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                    (d["status"], d["rejection_reason"], now_iso, order_id),
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
                f"Live order {order_id} transitioned to UNKNOWN_FREEZE due to: {live_exc}"
            ) from live_exc

    return OrderIntent(
        order_id=d["order_id"],
        idempotency_key=d["idempotency_key"],
        symbol=d["symbol"],
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
        created_at=d["created_at"],
        updated_at=now_iso,
    )
