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
import logging
import os
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Literal, Optional

from config.paths import app_data_path
from engine.charges import calculate_transaction_charges
from engine.db_pool import SQLiteConnectionPool
from engine.modes import get_trading_mode
from engine.observability import new_correlation_id
from engine.security_audit import record_audit_event

logger = logging.getLogger("chanakya.order_lifecycle")

_ORDERS_POOL: Optional[SQLiteConnectionPool] = None
_ORDERS_POOL_LOCK = threading.Lock()

# ── Zero-Latency In-Memory Broker Funds Cache ──────────────────────────────
_FUNDS_CACHE: dict[str, tuple[float, Any]] = {}
_FUNDS_CACHE_LOCK = threading.Lock()
_FUNDS_CACHE_TTL = 5.0  # 5-second TTL window


def get_cached_broker_funds(broker: Any, max_age: float = 5.0) -> Any:
    """
    Sub-millisecond in-memory cache for broker available funds.
    Eliminates the 150-350ms synchronous HTTP round-trip on the hot order execution path.
    """
    account_key = str(
        getattr(broker, "account_id", None)
        or getattr(broker, "client_id", None)
        or getattr(broker, "name", "default")
    )
    now = time.monotonic()
    with _FUNDS_CACHE_LOCK:
        if account_key in _FUNDS_CACHE:
            ts, val = _FUNDS_CACHE[account_key]
            if (now - ts) <= max_age:
                return val

    # Fetch fresh funds from broker adapter
    funds = broker.get_funds()
    with _FUNDS_CACHE_LOCK:
        _FUNDS_CACHE[account_key] = (time.monotonic(), funds)
    return funds


def invalidate_funds_cache(account_key: Optional[str] = None) -> None:
    """Invalidate funds cache on order submission, fill, or cancellation."""
    with _FUNDS_CACHE_LOCK:
        if account_key:
            _FUNDS_CACHE.pop(account_key, None)
        else:
            _FUNDS_CACHE.clear()


def _get_db_path() -> Path:
    p = app_data_path("orders.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _get_orders_pool() -> SQLiteConnectionPool:
    global _ORDERS_POOL
    current_path = str(_get_db_path())
    if _ORDERS_POOL is None or _ORDERS_POOL._closed or _ORDERS_POOL.db_path != current_path:
        with _ORDERS_POOL_LOCK:
            if _ORDERS_POOL is None or _ORDERS_POOL._closed or _ORDERS_POOL.db_path != current_path:
                if _ORDERS_POOL and not _ORDERS_POOL._closed:
                    try:
                        _ORDERS_POOL.close()
                    except Exception as e_pool:
                        logger.debug(f"[order_lifecycle] Error closing old orders pool: {e_pool}")
                _ORDERS_POOL = SQLiteConnectionPool(current_path, max_conns=5)
    return _ORDERS_POOL


@contextmanager
def _get_orders_db() -> Generator[sqlite3.Connection, None, None]:
    with _get_orders_pool().acquire() as conn:
        yield conn


def close_orders_db() -> None:
    """Close all pooled connections for orders."""
    global _ORDERS_POOL
    with _ORDERS_POOL_LOCK:
        if _ORDERS_POOL is not None:
            _ORDERS_POOL.close()
            _ORDERS_POOL = None


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
    "CANCEL_PENDING",
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
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


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
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    auto_gtt_oco: bool = True
    gtt_order_id: Optional[str] = None
    filled_quantity: int = 0
    average_fill_price: Optional[float] = None
    last_sync_at: Optional[str] = None
    parent_order_id: Optional[str] = None
    slice_index: Optional[int] = None
    total_slices: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _init_orders_db():
    with _get_orders_db() as conn:
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
        if "stop_loss" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN stop_loss REAL")
        if "target" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN target REAL")
        if "auto_gtt_oco" not in existing_cols:
            conn.execute(
                "ALTER TABLE orders_ledger ADD COLUMN auto_gtt_oco INTEGER NOT NULL DEFAULT 1"
            )
        if "gtt_order_id" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN gtt_order_id TEXT")
        if "ledger_status" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN ledger_status TEXT")
        if "ledger_error" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN ledger_error TEXT")
        if "account_id" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN account_id TEXT")
        if "filled_quantity" not in existing_cols:
            conn.execute(
                "ALTER TABLE orders_ledger ADD COLUMN filled_quantity INTEGER NOT NULL DEFAULT 0"
            )
        if "average_fill_price" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN average_fill_price REAL")
        if "last_sync_at" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN last_sync_at TEXT")
        if "parent_order_id" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN parent_order_id TEXT")
        if "slice_index" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN slice_index INTEGER")
        if "total_slices" not in existing_cols:
            conn.execute("ALTER TABLE orders_ledger ADD COLUMN total_slices INTEGER")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_idemp ON orders_ledger(idempotency_key)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders_ledger(status)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_parent ON orders_ledger(parent_order_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS order_events (
                event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                correlation_id TEXT,
                broker_name TEXT,
                broker_order_id TEXT,
                payload_json TEXT NOT NULL,
                previous_hash TEXT,
                event_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id, occurred_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_cash_baselines (
                account_id TEXT PRIMARY KEY,
                opening_cash REAL NOT NULL,
                established_at TEXT NOT NULL,
                established_by TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_fills (
                fill_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                broker_name TEXT NOT NULL,
                order_id TEXT NOT NULL,
                broker_order_id TEXT NOT NULL,
                broker_trade_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                segment TEXT NOT NULL,
                product TEXT NOT NULL DEFAULT 'MIS',
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                fill_price REAL NOT NULL,
                fill_time TEXT NOT NULL,
                charges REAL NOT NULL DEFAULT 0.0,
                sequence_num INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                UNIQUE(account_id, broker_name, broker_trade_id)
            )
            """
        )
        existing_fill_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(execution_fills)").fetchall()
        }
        if "product" not in existing_fill_cols:
            conn.execute(
                "ALTER TABLE execution_fills ADD COLUMN product TEXT NOT NULL DEFAULT 'MIS'"
            )
        if "updated_at" not in existing_fill_cols:
            conn.execute("ALTER TABLE execution_fills ADD COLUMN updated_at TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fills_account ON execution_fills(account_id)")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_account_broker_trade ON execution_fills(account_id, broker_name, broker_trade_id)"
        )
        conn.commit()


def _record_order_event(
    order_id: str,
    event_type: str,
    *,
    correlation_id: Optional[str] = None,
    broker_name: Optional[str] = None,
    broker_order_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Append a tamper-evident lifecycle event without affecting order flow."""
    try:
        _init_orders_db()
        occurred_at = datetime.now(timezone.utc).isoformat()
        body = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
        with _get_orders_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT event_hash FROM order_events WHERE order_id = ? ORDER BY occurred_at DESC LIMIT 1",
                (order_id,),
            ).fetchone()
            previous_hash = previous[0] if previous else None
            canonical = "|".join(
                [
                    order_id,
                    event_type,
                    occurred_at,
                    correlation_id or "",
                    broker_order_id or "",
                    body,
                    previous_hash or "",
                ]
            )
            event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO order_events (
                    event_id, order_id, event_type, occurred_at, correlation_id,
                    broker_name, broker_order_id, payload_json, previous_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    order_id,
                    event_type,
                    occurred_at,
                    correlation_id,
                    broker_name,
                    broker_order_id,
                    body,
                    previous_hash,
                    event_hash,
                ),
            )
            conn.commit()
    except Exception as e_suppressed:
        # Audit persistence must not turn an already-completed broker call into a retry.
        logger.debug(f"[engine.order_lifecycle] Non-fatal exception suppressed: {e_suppressed}")


def _resolve_order_instrument(symbol: str, product: ProductType):
    """Resolve the only exchange and segment allowed for an order intent."""
    from market.instrument_master import get_verified_contract, is_derivative_query
    from market.instruments import resolve_canonical_instrument

    if is_derivative_query(symbol):
        contract = get_verified_contract(symbol)
        if not contract:
            raise ValueError(
                "Derivative orders require a current provider-verified instrument master record. "
                "Static lot/tick assumptions are not allowed."
            )
        segment = (
            "OPTIONS"
            if str(contract["provider_symbol"]).upper().endswith(("CE", "PE"))
            else "FUTURES"
        )
        return None, str(contract["exchange"]), segment

    inst = resolve_canonical_instrument(symbol)
    if inst.segment == "EQUITY":
        segment = "EQUITY_DELIVERY" if product == "CNC" else "EQUITY_INTRADAY"
    elif inst.segment == "COMMODITY":
        segment = "COMMODITY"
    elif inst.segment == "CURRENCY":
        segment = "CURRENCY"
    elif inst.segment == "FNO" or inst.instrument_type in ("OPTION", "FUTURE"):
        segment = "OPTIONS" if inst.instrument_type == "OPTION" else "FUTURES"
    else:
        segment = inst.segment
    return inst, inst.exchange, segment


def _validate_preview_inputs(
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    order_type: str,
    product: str,
) -> None:
    """Defend the lifecycle boundary for callers that bypass the HTTP schema."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol must be a non-empty string")
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Unsupported side: {side!r}")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("quantity must be a positive integer")
    if (
        isinstance(price, bool)
        or not isinstance(price, (int, float))
        or not math.isfinite(price)
        or price <= 0
    ):
        raise ValueError("price must be a finite positive number")
    if order_type not in ("MARKET", "LIMIT", "SL_LIMIT", "SL_MARKET"):
        raise ValueError(f"Unsupported order_type: {order_type!r}")
    if product not in ("CNC", "MIS", "NRML"):
        raise ValueError(f"Unsupported product: {product!r}")


def _intent_from_ledger_row(row: sqlite3.Row | dict[str, Any], expected_hash: str) -> OrderIntent:
    """Return a typed intent while refusing legacy or mismatched idempotency records."""
    d = dict(row)
    if not d.get("preview_hash"):
        raise ValueError(
            f"Order {d['order_id']} has no immutable preview hash and cannot be reused."
        )
    if d["preview_hash"] != expected_hash:
        raise ValueError(
            f"Idempotency key '{d['idempotency_key']}' matches an existing order with mismatched parameters."
        )
    return OrderIntent(
        order_id=d["order_id"],
        idempotency_key=d["idempotency_key"],
        symbol=d["symbol"],
        exchange=d["exchange"],
        segment=d["segment"],
        side=d["side"],  # type: ignore[arg-type]
        quantity=d["quantity"],
        price=d["price"],
        order_type=d["order_type"],  # type: ignore[arg-type]
        product=d["product"],  # type: ignore[arg-type]
        status=d["status"],  # type: ignore[arg-type]
        mode=d["mode"],
        broker_order_id=d["broker_order_id"],
        charges=json.loads(d["charges_json"] or "{}"),
        rejection_reason=d["rejection_reason"],
        preview_hash=d["preview_hash"],
        stop_loss=d.get("stop_loss"),
        target=d.get("target"),
        auto_gtt_oco=bool(d.get("auto_gtt_oco", 1)),
        gtt_order_id=d.get("gtt_order_id"),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        filled_quantity=int(d.get("filled_quantity", 0) or 0),
        average_fill_price=float(d["average_fill_price"]) if d.get("average_fill_price") else None,
        last_sync_at=d.get("last_sync_at"),
        parent_order_id=d.get("parent_order_id"),
        slice_index=d.get("slice_index"),
        total_slices=d.get("total_slices"),
    )


def preview_order_intent(
    symbol: str,
    side: OrderSide,
    quantity: int,
    price: float,
    order_type: OrderType = "LIMIT",
    product: ProductType = "MIS",
    idempotency_key: Optional[str] = None,
    *,
    exchange: Optional[str] = None,
    segment: Optional[str] = None,
    no_chase_boundary: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    trigger_price: Optional[float] = None,
    auto_gtt_oco: bool = True,
) -> OrderIntent:
    """
    Generate an order preview with statutory Indian charges, concurrency-safe idempotency check,
    authoritative multi-asset instrument resolution, and explicit PAPER-/LIVE- order ID prefix.

    Exchange and segment are resolved authoritatively from symbol metadata.
    Explicit direct-call values must match that resolution; conflicting values
    are rejected rather than silently rewritten.
    """
    _init_orders_db()
    _validate_preview_inputs(symbol, side, quantity, price, order_type, product)
    from engine.risk_limits import risk_limits, RiskLimitError

    try:
        risk_limits.check(
            symbol=symbol, action=side, quantity=quantity, price=price, allow_override=False
        )
    except RiskLimitError as rle:
        raise ValueError(f"Order intent violates risk limits: {rle}") from rle
    if trigger_price is not None:
        if (
            isinstance(trigger_price, bool)
            or not isinstance(trigger_price, (int, float))
            or not math.isfinite(trigger_price)
            or trigger_price <= 0
        ):
            raise ValueError("trigger_price must be a finite positive number")
        trigger_price = float(trigger_price)
    elif order_type in ("SL_LIMIT", "SL_MARKET"):
        trigger_price = float(price)

    if stop_loss is not None:
        if (
            isinstance(stop_loss, bool)
            or not isinstance(stop_loss, (int, float))
            or not math.isfinite(stop_loss)
            or stop_loss <= 0
        ):
            raise ValueError("stop_loss must be a finite positive number")
        stop_loss = float(stop_loss)
        if side == "BUY" and stop_loss >= price:
            raise ValueError(
                f"Stop loss (₹{stop_loss:.2f}) must be strictly below order price (₹{price:.2f}) for BUY orders."
            )
        elif side == "SELL" and stop_loss <= price:
            raise ValueError(
                f"Stop loss (₹{stop_loss:.2f}) must be strictly above order price (₹{price:.2f}) for SELL orders."
            )

    if target is not None:
        if (
            isinstance(target, bool)
            or not isinstance(target, (int, float))
            or not math.isfinite(target)
            or target <= 0
        ):
            raise ValueError("target must be a finite positive number")
        target = float(target)
        if side == "BUY" and target <= price:
            raise ValueError(
                f"Target (₹{target:.2f}) must be strictly above order price (₹{price:.2f}) for BUY orders."
            )
        elif side == "SELL" and target >= price:
            raise ValueError(
                f"Target (₹{target:.2f}) must be strictly below order price (₹{price:.2f}) for SELL orders."
            )
    _, resolved_exchange, resolved_segment = _resolve_order_instrument(symbol, product)

    if exchange is not None and exchange.upper() != resolved_exchange:
        raise ValueError(
            f"exchange override {exchange!r} conflicts with canonical exchange {resolved_exchange!r}"
        )
    if segment is not None and segment.upper() != resolved_segment:
        raise ValueError(
            f"segment override {segment!r} conflicts with canonical segment {resolved_segment!r}"
        )

    mode_info = get_trading_mode()
    mode_name = mode_info.mode.name
    is_paper = not mode_info.is_execute

    if mode_info.is_execute and not idempotency_key:
        raise ValueError("idempotency_key is required for live order preview")

    # For non-live orders without client key, generate random UUID to allow distinct intentional orders
    idemp = idempotency_key or f"IDEMP-{uuid.uuid4().hex}"

    # Canonical request string that cryptographically binds ALL structural parameters, active mode, and protections (EXEC-17)
    canonical_str = (
        f"{resolved_exchange}:{symbol.upper()}:{resolved_segment}:{side}:"
        f"{quantity}:{price:.4f}:{order_type}:{product}:{mode_name}"
        + (f":trig_{trigger_price:.4f}" if trigger_price is not None else "")
        + (f":sl_{stop_loss:.4f}" if stop_loss is not None else "")
        + (f":tgt_{target:.4f}" if target is not None else "")
        + (f":gtt_{int(bool(auto_gtt_oco))}")
    )
    computed_preview_hash = hashlib.sha256(canonical_str.encode()).hexdigest()

    from brokers.session import get_execution_broker_key

    exec_key = get_execution_broker_key() or "fyers"
    is_zero_brokerage = exec_key.lower() == "flattrade"

    charges = calculate_transaction_charges(
        price=price,
        quantity=quantity,
        segment=resolved_segment,  # type: ignore
        side=side,  # type: ignore
        broker_flat_fee=0.0 if is_zero_brokerage else 20.0,
        brokerage_rate=0.0 if is_zero_brokerage else None,
    )
    charges_dict = charges.to_dict()
    charges_dict["execution_broker"] = exec_key
    charges_dict["is_zero_brokerage"] = is_zero_brokerage
    if is_zero_brokerage:
        charges_dict["brokerage_savings"] = 20.0
    if trigger_price is not None:
        charges_dict["trigger_price"] = float(trigger_price)

    try:
        from market.order_book import get_depth_book

        clean_sym = (
            symbol.replace("NSE:", "")
            .replace("BSE:", "")
            .replace("NFO:", "")
            .replace("MCX:", "")
            .strip()
            .upper()
        )
        book = get_depth_book(clean_sym)
        if (side.upper() == "BUY" and book.best_ask > 0) or (
            side.upper() == "SELL" and book.best_bid > 0
        ):
            sweep_res = book.simulate_sweep(side=side, quantity=quantity)
            charges_dict["slippage_model"] = sweep_res
            slip_bps = float(sweep_res.get("slippage_bps", 0.0) or 0.0)
            if slip_bps >= 50.0:
                charges_dict["slippage_warning"] = (
                    f"High Slippage Hazard: Sweeping order book incurs {slip_bps:.0f} bps "
                    f"({slip_bps / 100:.2f}%) adverse price impact. Recommend LIMIT order."
                )
            if not sweep_res.get("is_fully_fillable", True):
                charges_dict["liquidity_warning"] = (
                    f"Thin Book Liquidity Warning: Requested {quantity} units exceeds visible depth "
                    f"(shortfall: {sweep_res.get('unfilled_qty')} units). High partial fill risk."
                )
            imbalance = book.get_imbalance()
            if side.upper() == "BUY" and imbalance < -0.65:
                charges_dict["orderbook_imbalance_warning"] = (
                    f"Institutional Ask Wall Warning: Order book is heavily supply-skewed "
                    f"(imbalance: {imbalance:.2f}). Aggressive buyers risk getting trapped into absorption."
                )
            elif side.upper() == "SELL" and imbalance > 0.65:
                charges_dict["orderbook_imbalance_warning"] = (
                    f"Institutional Bid Wall Warning: Order book is heavily demand-skewed "
                    f"(imbalance: {imbalance:.2f}). Aggressive sellers risk getting trapped into absorption."
                )

        if no_chase_boundary is not None and no_chase_boundary > 0:
            charges_dict["no_chase_boundary"] = float(no_chase_boundary)
            sweep_vwap = sweep_res.get("sweep_vwap") if sweep_res else None
            if sweep_vwap:
                charges_dict["depth_sweep_vwap"] = float(sweep_vwap)

            if side.upper() == "BUY":
                if sweep_vwap and sweep_vwap > no_chase_boundary:
                    charges_dict["no_chase_violation"] = (
                        f"FOMO Depth Sweep Violation: Simulated fill VWAP ₹{sweep_vwap:,.2f} sweeps past "
                        f"no-chase boundary ₹{no_chase_boundary:,.2f} (best ask was ₹{book.best_ask:,.2f}, "
                        f"slippage: {charges_dict.get('orderbook_slippage_pct', 0.0):.2f}%)."
                    )
                elif book.best_ask > 0 and book.best_ask > no_chase_boundary:
                    charges_dict["no_chase_violation"] = (
                        f"FOMO Violation: Best ask ₹{book.best_ask:,.2f} already exceeds "
                        f"no-chase boundary ₹{no_chase_boundary:,.2f}."
                    )
            elif side.upper() == "SELL":
                if sweep_vwap and sweep_vwap < no_chase_boundary:
                    charges_dict["no_chase_violation"] = (
                        f"FOMO Depth Sweep Violation: Simulated fill VWAP ₹{sweep_vwap:,.2f} sweeps below "
                        f"no-chase boundary ₹{no_chase_boundary:,.2f} (best bid was ₹{book.best_bid:,.2f}, "
                        f"slippage: {charges_dict.get('orderbook_slippage_pct', 0.0):.2f}%)."
                    )
                elif book.best_bid > 0 and book.best_bid < no_chase_boundary:
                    charges_dict["no_chase_violation"] = (
                        f"FOMO Violation: Best bid ₹{book.best_bid:,.2f} already below "
                        f"no-chase boundary ₹{no_chase_boundary:,.2f}."
                    )
    except Exception as e_sweep:
        logger.debug(f"[order_lifecycle] Depth sweep modeling skipped for {symbol}: {e_sweep}")

    # Exchange Order Quantity Freeze Limit Check
    try:
        from engine.smart_order_router import get_exchange_freeze_limit

        qualified_symbol = symbol if ":" in str(symbol) else f"{resolved_exchange}:{symbol}"
        freeze_limit = get_exchange_freeze_limit(qualified_symbol, segment=resolved_segment)
        if quantity > freeze_limit:
            num_tranches = math.ceil(quantity / freeze_limit)
            charges_dict["freeze_limit"] = freeze_limit
            charges_dict["freeze_warning"] = (
                f"Exchange Freeze Slicer: Quantity {quantity} exceeds single-order limit ({freeze_limit}). "
                f"Will be automatically executed across {num_tranches} child tranches."
            )
            charges_dict["sliced_execution_required"] = True
            charges_dict["suggested_tranches"] = num_tranches
    except Exception as e_fz:
        logger.debug(f"[order_lifecycle] Freeze limit check skipped for {symbol}: {e_fz}")

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
        charges=charges_dict,
        stop_loss=stop_loss,
        target=target,
        auto_gtt_oco=auto_gtt_oco,
    )

    # Concurrency-safe atomic insert: INSERT ... ON CONFLICT(idempotency_key) DO NOTHING
    now_iso = datetime.now(timezone.utc).isoformat()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            INSERT INTO orders_ledger (
                order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
                order_type, product, status, mode, broker_order_id, charges_json,
                rejection_reason, preview_hash, stop_loss, target, auto_gtt_oco, gtt_order_id,
                created_at, updated_at, account_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                intent.stop_loss,
                intent.target,
                1 if intent.auto_gtt_oco else 0,
                intent.gtt_order_id,
                now_iso,
                now_iso,
                "SIMULATED_PAPER_ACCOUNT"
                if is_paper
                else (os.environ.get("BROKER_ACCOUNT_ID") or "LIVE_ACCOUNT"),
            ),
        )
        conn.commit()
        if cursor.rowcount == 0:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT * FROM orders_ledger WHERE idempotency_key = ?", (idemp,)
            ).fetchone()
            if not existing:
                raise RuntimeError("Idempotency conflict could not be resolved; retry the preview.")
            existing_data = dict(existing)
            if existing_data["mode"] != mode_name:
                raise PermissionError(
                    f"Idempotency key '{idemp}' was created under mode {existing_data['mode']}, "
                    f"but active mode is {mode_name}. Cross-mode order intent reuse is prohibited."
                )
            return _intent_from_ledger_row(existing_data, computed_preview_hash)

        # Authoritatively re-read the row (either just inserted or previously existing)
        row = conn.execute(
            "SELECT * FROM orders_ledger WHERE idempotency_key = ?", (idemp,)
        ).fetchone()
        if not row:
            raise RuntimeError(
                f"Failed to persist or fetch order intent for idempotency key '{idemp}'."
            )
        d = dict(row)

    if d["mode"] != mode_name:
        raise PermissionError(
            f"Idempotency key '{idemp}' was created under mode {d['mode']}, but active mode is {mode_name}. "
            "Cross-mode order intent reuse is strictly prohibited."
        )
    saved_intent = _intent_from_ledger_row(d, computed_preview_hash)

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
    _record_order_event(
        saved_intent.order_id,
        "PREVIEW_GENERATED",
        payload={
            "status": saved_intent.status,
            "mode": saved_intent.mode,
            "preview_hash": saved_intent.preview_hash,
        },
    )

    return saved_intent


def confirm_order_intent(order_id: str, preview_hash: str) -> OrderIntent:
    """
    Transition a PREVIEW order to CONFIRMED state with mode and preview hash validation.
    """
    _init_orders_db()
    mode_info = get_trading_mode()
    now_iso = datetime.now(timezone.utc).isoformat()

    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,)).fetchone()
        if not row:
            raise ValueError(f"Order {order_id} not found.")
        d = dict(row)

        if not preview_hash or d.get("preview_hash") != preview_hash:
            raise ValueError("Order preview hash does not match the server-generated intent.")

        if d["mode"] != mode_info.mode.name:
            raise PermissionError(
                f"Order {order_id} was generated in {d['mode']} mode but confirmation was attempted in "
                f"{mode_info.mode.name} mode. Cross-mode confirmation is strictly prohibited."
            )

        if d["status"] == "CONFIRMED":
            return _row_to_intent(d)

        if d["status"] != "PREVIEW":
            raise ValueError(
                f"Order {order_id} cannot be confirmed because current status is '{d['status']}'."
            )

        # 60-Second Preview TTL Staleness Guard (EXEC-18: Fail-closed on missing/unparseable created_at)
        created_at_val = d.get("created_at")
        if not created_at_val or not isinstance(created_at_val, str):
            raise ValueError(
                f"Order preview {order_id} has missing or invalid created_at timestamp. Failing closed."
            )
        try:
            if created_at_val.endswith("Z"):
                created_dt = datetime.fromisoformat(created_at_val.replace("Z", "+00:00"))
            elif "+" in created_at_val or ("-" in created_at_val[10:]):
                created_dt = datetime.fromisoformat(created_at_val)
            else:
                created_dt = datetime.fromisoformat(created_at_val).replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - created_dt).total_seconds()
            if age_sec > 60.0:
                raise TimeoutError(
                    f"Order preview {order_id} has expired (age: {age_sec:.1f}s > 60.0s TTL). "
                    "Re-generate order preview to prevent stale price slippage."
                )
        except TimeoutError:
            raise
        except Exception as exc:
            raise ValueError(
                f"Order preview {order_id} has unparseable created_at timestamp '{created_at_val}': {exc}. Failing closed."
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
        confirmed = _row_to_intent(dict(updated_row))
    _record_order_event(order_id, "CONFIRMED", payload={"status": confirmed.status})
    return confirmed


def submit_simulated_order_intent(
    *,
    symbol: str,
    side: OrderSide,
    quantity: int,
    price: float,
    order_type: OrderType = "LIMIT",
    product: ProductType = "MIS",
    trigger_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    auto_gtt_oco: bool = False,
) -> OrderIntent:
    """Create, confirm, and execute one order only through the simulated OMS.

    Legacy CLI surfaces use this adapter instead of calling a configured broker
    directly. It deliberately has no live mode path and requires an explicit
    positive reference price even for MARKET orders so the ledger never records
    an unpriced intention as an execution decision.
    """
    mode_info = get_trading_mode()
    if mode_info.mode.name != "SIMULATE":
        raise PermissionError(
            "This entry point only supports SIMULATE mode. Use the authenticated order ticket "
            "for any live order; direct CLI broker placement is disabled."
        )
    if (
        not isinstance(price, (int, float))
        or isinstance(price, bool)
        or not math.isfinite(price)
        or price <= 0
    ):
        raise ValueError("A finite positive reference price is required for a simulated order.")

    preview = preview_order_intent(
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=float(price),
        order_type=order_type,
        product=product,
        trigger_price=trigger_price,
        stop_loss=stop_loss,
        target=target,
        auto_gtt_oco=auto_gtt_oco,
    )
    confirmed = confirm_order_intent(preview.order_id, preview.preview_hash or "")
    return execute_order_intent(confirmed.order_id)


def cancel_order_intent(order_id: str) -> dict[str, Any]:
    """Request cancellation only for an order owned by the persisted OMS.

    Broker acknowledgement means the request was accepted, not that the order
    is canceled. The durable state stays CANCEL_PENDING until a subsequent
    broker snapshot confirms cancellation.
    """
    from brokers.session import get_execution_broker
    from engine.modes import assert_live_execution_allowed

    mode = get_trading_mode().mode.name
    if mode == "OBSERVE":
        raise PermissionError("Order cancellation is unavailable in OBSERVE mode.")
    if mode == "EXECUTE":
        assert_live_execution_allowed()
        raise PermissionError(
            "Live OMS cancellation is disabled until orders are bound to a verified broker account. "
            "Use the broker's order screen, then reconcile before retrying."
        )

    _init_orders_db()
    now = datetime.now(timezone.utc).isoformat()
    with _get_orders_pool().transaction() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,)).fetchone()
        if not row:
            raise ValueError("Only orders persisted by the central OMS can be canceled here.")
        order = dict(row)
        if order["mode"] != mode:
            raise PermissionError("Cross-mode cancellation is prohibited.")
        if order["status"] not in ("OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING"):
            raise ValueError(f"Order cannot be canceled from state {order['status']}.")
        if order["status"] == "CANCEL_PENDING":
            raise ValueError(
                "Cancellation is already pending; reconcile the broker order before retrying."
            )
        broker_order_id = order.get("broker_order_id")
        if not broker_order_id:
            raise ValueError("Order has no broker order ID; reconcile its submission state first.")
        cursor = conn.execute(
            "UPDATE orders_ledger SET status='CANCEL_PENDING', updated_at=? "
            "WHERE order_id=? AND status IN ('OPEN','PARTIALLY_FILLED')",
            (now, order["order_id"]),
        )
        if cursor.rowcount != 1:
            raise ValueError(
                "Concurrent order-state change; reload and reconcile before canceling."
            )

    if mode == "SIMULATE":
        from engine.paper import PaperBroker

        broker = PaperBroker()
        provider = "paper"
    else:
        assert_live_execution_allowed()
        broker = get_execution_broker()
        provider = broker.__class__.__name__.lower()

    acknowledged = False
    try:
        acknowledged = bool(broker.cancel_order(str(broker_order_id)))
    except Exception as exc:
        logger.error(
            "[order_lifecycle] Cancellation outcome ambiguous for OMS order %s / broker order %s: %s",
            order["order_id"],
            broker_order_id,
            exc,
            exc_info=True,
        )

    confirmed_cancel = False
    try:
        clean_b_id = str(broker_order_id).replace("PAPER-OPEN-", "").replace("PAPER-EXEC-", "")
        for broker_order in broker.get_orders():
            b_oid = str(getattr(broker_order, "order_id", ""))
            if b_oid in (str(broker_order_id), clean_b_id):
                confirmed_cancel = str(getattr(broker_order, "status", "")).upper() in (
                    "CANCELLED",
                    "CANCELED",
                )
                break
    except Exception as exc:
        logger.warning(
            "[order_lifecycle] Could not confirm cancellation for %s: %s",
            order["order_id"],
            exc,
            exc_info=True,
        )

    final_status = "CANCELLED" if confirmed_cancel else "CANCEL_PENDING"
    with _get_orders_pool().transaction() as conn:
        conn.execute(
            "UPDATE orders_ledger SET status=?, updated_at=? WHERE order_id=? AND status='CANCEL_PENDING'",
            (final_status, datetime.now(timezone.utc).isoformat(), order["order_id"]),
        )
    _record_order_event(
        order["order_id"],
        "CANCEL_CONFIRMED" if confirmed_cancel else "CANCEL_REQUESTED",
        broker_name=provider,
        broker_order_id=str(broker_order_id),
        payload={"acknowledged": acknowledged, "status": final_status},
    )
    return {
        "order_id": order["order_id"],
        "broker_order_id": str(broker_order_id),
        "mode": mode,
        "status": final_status,
        "cancel_acknowledged": acknowledged,
        "cancel_confirmed": confirmed_cancel,
    }


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
        stop_loss=d.get("stop_loss"),
        target=d.get("target"),
        auto_gtt_oco=bool(d.get("auto_gtt_oco", 1)),
        gtt_order_id=d.get("gtt_order_id"),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
        filled_quantity=int(d.get("filled_quantity", 0) or 0),
        average_fill_price=float(d["average_fill_price"]) if d.get("average_fill_price") else None,
        last_sync_at=d.get("last_sync_at"),
        parent_order_id=d.get("parent_order_id"),
        slice_index=d.get("slice_index"),
        total_slices=d.get("total_slices"),
    )


def get_order_intent(order_id: str) -> Optional[OrderIntent]:
    """Retrieve an order intent by its order_id from the ledger."""
    _init_orders_db()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders_ledger WHERE order_id = ? OR broker_order_id = ? LIMIT 1",
            (order_id, order_id),
        ).fetchone()
        if not row:
            return None
        return _row_to_intent(dict(row))


def get_child_orders(parent_order_id: str) -> list[OrderIntent]:
    """Retrieve all child tranche order intents for a given parent_order_id, sorted by slice_index."""
    _init_orders_db()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM orders_ledger WHERE parent_order_id = ? ORDER BY slice_index ASC",
            (parent_order_id,),
        ).fetchall()
        return [_row_to_intent(dict(r)) for r in rows]


def _reconcile_parent_order_in_conn(
    conn: sqlite3.Connection, parent_order_id: str, now_iso: str
) -> None:
    """Rolls up child order statuses and fills to the parent order in a single transaction."""
    children = conn.execute(
        "SELECT * FROM orders_ledger WHERE parent_order_id = ? ORDER BY slice_index ASC",
        (parent_order_id,),
    ).fetchall()
    if not children:
        return

    statuses = [c["status"] for c in children]
    if any(s in ("SUBMITTING", "UNKNOWN_FREEZE") for s in statuses):
        new_parent_status = "UNKNOWN_FREEZE"
    elif any(s in ("OPEN", "PARTIALLY_FILLED") for s in statuses):
        new_parent_status = "OPEN"
    elif all(s in ("FILLED", "FILLED_PAPER") for s in statuses):
        new_parent_status = "FILLED" if "FILLED" in statuses else "FILLED_PAPER"
    elif all(s == "REJECTED" for s in statuses):
        new_parent_status = "REJECTED"
    elif any(s in ("FILLED", "FILLED_PAPER") for s in statuses):
        new_parent_status = "PARTIALLY_FILLED"
    else:
        new_parent_status = "OPEN"

    total_qty = sum(int(c["filled_quantity"] or 0) for c in children)
    total_cost = sum(
        int(c["filled_quantity"] or 0) * float(c["average_fill_price"] or c["price"] or 0.0)
        for c in children
        if (c["filled_quantity"] or 0) > 0
    )
    avg_px = (total_cost / total_qty) if total_qty > 0 else None

    child_broker_ids = [c["broker_order_id"] for c in children if c["broker_order_id"]]
    prefix = (
        "PAPER-EXEC-SLICED-"
        if any(str(b).startswith("PAPER-") for b in child_broker_ids)
        else "SLICED:"
    )
    broker_order_id_str = (
        f"{prefix}{','.join(str(b) for b in child_broker_ids)}" if child_broker_ids else None
    )

    conn.execute(
        """
        UPDATE orders_ledger
        SET status = ?, filled_quantity = ?, average_fill_price = ?,
            broker_order_id = COALESCE(?, broker_order_id),
            last_sync_at = ?, updated_at = ?
        WHERE order_id = ?
        """,
        (
            new_parent_status,
            total_qty,
            avg_px,
            broker_order_id_str,
            now_iso,
            now_iso,
            parent_order_id,
        ),
    )


_emergency_lockout_until: Optional[float] = None


def is_emergency_lockout_active() -> tuple[bool, float]:
    """Check if emergency circuit breaker lockout is currently active."""
    global _emergency_lockout_until
    if _emergency_lockout_until is None:
        return False, 0.0
    now = time.time()
    if now < _emergency_lockout_until:
        return True, _emergency_lockout_until - now
    _emergency_lockout_until = None
    return False, 0.0


def set_emergency_lockout(duration_seconds: float = 3600.0) -> float:
    """Set emergency cooling-off lockout period (default 60 minutes)."""
    global _emergency_lockout_until
    _emergency_lockout_until = time.time() + duration_seconds
    return _emergency_lockout_until


def clear_emergency_lockout() -> None:
    """Clear emergency cooling-off lockout."""
    global _emergency_lockout_until
    _emergency_lockout_until = None


def execute_order_intent(order_id: str) -> OrderIntent:
    """
    Transition a server-CONFIRMED order into execution.

    P0 Safety & Guardrail Contracts:
      1. Cross-Mode Protection: Refuses execution if current global runtime mode does not
         match the exact mode in which the preview was generated. Prevents paper previews
         from executing live capital upon mode switch.
      2. Anti-Replay & State Guard: Only permits orders in CONFIRMED state.
         Re-execution of terminal (FILLED, REJECTED, UNKNOWN_FREEZE) or in-flight orders raises ValueError.
      3. Single Atomic Transition: Performs an atomic DB status lock (CONFIRMED -> SUBMITTING)
         bound to active mode to guarantee exactly-once execution even under concurrent dispatches.
      4. Preview Hash Integrity: Cryptographically verifies stored preview_hash against canonical
         recomputed parameters before initiating any broker submission.
      6. Fail-Closed Live OMS: Live execution requires ALLOW_LIVE_TRADING=1, fresh quote context,
         passing pretrade risk gates, and never fabricates mock orders or IDs on timeout.
    """
    _init_orders_db()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Order {order_id} not found.")

        d = dict(row)

    from engine.observability import set_correlation_context

    set_correlation_context(
        correlation_id=d.get("correlation_id") or order_id,
        symbol=d.get("symbol"),
    )

    from engine.risk_limits import risk_limits, RiskLimitError

    try:
        risk_limits.check(
            symbol=d["symbol"],
            action=d["side"],
            quantity=int(d["quantity"]),
            price=float(d["price"]),
            allow_override=False,
        )
    except RiskLimitError as rle:
        raise PermissionError(f"Order execution violates risk limits: {rle}") from rle

    # ── Emergency Circuit Breaker Lockout Check ────────────────────────────
    is_locked, remaining_sec = is_emergency_lockout_active()
    if is_locked:
        raise PermissionError(
            f"Emergency circuit breaker lockout active ({remaining_sec:.0f}s remaining). "
            f"New order execution blocked to preserve capital."
        )

    mode_info = get_trading_mode()
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── P0 Invariant 1: Cross-Mode Protection ──────────────────────────────
    if d["mode"] != mode_info.mode.name:
        raise PermissionError(
            f"Order {order_id} was generated in {d['mode']} mode but execution was attempted in "
            f"{mode_info.mode.name} mode. Cross-mode order execution is strictly prohibited."
        )

    # ── P0 Invariant 2: State Guard & Anti-Replay ──────────────────────────
    if d["status"] != "CONFIRMED":
        if d["status"] == "PREVIEW":
            target = "live execution" if mode_info.is_execute else "execution"
            raise ValueError(
                f"Order {order_id} must be CONFIRMED before {target}. Direct execution from PREVIEW is prohibited."
            )
        raise ValueError(
            f"Order {order_id} cannot be executed because its current status is '{d['status']}'. "
            "Re-execution of terminal or already active/submitted orders is strictly prohibited."
        )

    # ── P0 Invariant 3: Preview Hash Integrity Verification ────────────────
    charges_d = (
        json.loads(d.get("charges_json") or "{}")
        if isinstance(d.get("charges_json"), str)
        else (d.get("charges") or {})
    )
    trig_val = charges_d.get("trigger_price")
    sl_val = d.get("stop_loss")
    tgt_val = d.get("target")
    gtt_val = d.get("auto_gtt_oco")
    canonical_str = (
        f"{d.get('exchange', 'NSE')}:{d['symbol'].upper()}:{d.get('segment', 'EQUITY_INTRADAY')}:{d['side']}:"
        f"{d['quantity']}:{float(d['price']):.4f}:{d['order_type']}:{d['product']}:{d['mode']}"
        + (f":trig_{float(trig_val):.4f}" if trig_val is not None else "")
        + (f":sl_{float(sl_val):.4f}" if sl_val is not None else "")
        + (f":tgt_{float(tgt_val):.4f}" if tgt_val is not None else "")
        + (f":gtt_{int(bool(gtt_val))}")
    )
    expected_hash = hashlib.sha256(canonical_str.encode()).hexdigest()
    if d.get("preview_hash") and d["preview_hash"] != expected_hash:
        raise ValueError(
            f"Order {order_id} preview hash verification failed (intent parameters were tampered with or corrupted)."
        )

    # ── P0 Invariant 4: Single Atomic Transition (CONFIRMED -> SUBMITTING) ──
    _, canonical_exchange, canonical_segment = _resolve_order_instrument(d["symbol"], d["product"])
    if d.get("exchange") != canonical_exchange or d.get("segment") != canonical_segment:
        raise ValueError(
            f"Order {order_id} instrument metadata does not match the authoritative instrument master."
        )

    # Check the live qualification gate before claiming SUBMITTING. A blocked
    # deployment must leave the user-confirmed order recoverable as CONFIRMED.
    if mode_info.is_execute:
        from engine.modes import assert_live_execution_allowed

        assert_live_execution_allowed()

        # Freeze-limit tranche submits require durable parent/child order IDs,
        # per-child fill reconciliation, and crash-safe partial-fill recovery.
        # The current OMS only has a paper implementation of those semantics.
        from engine.smart_order_router import slice_quantity_by_freeze_limit
        from market.instruments import resolve_canonical_instrument

        canonical_instrument = resolve_canonical_instrument(d["symbol"])
        from market.instrument_master import get_verified_contract

        verified_contract = get_verified_contract(d["symbol"])
        lot_size = (
            int(verified_contract["lot_size"])
            if verified_contract
            else int(getattr(canonical_instrument, "lot_size", 1) or 1)
        )
        tranche_quantities = slice_quantity_by_freeze_limit(
            d["symbol"] if ":" in str(d["symbol"]) else f"{d['exchange']}:{d['symbol']}",
            int(d["quantity"]),
            lot_size,
            segment=d.get("segment"),
        )
        if len(tranche_quantities or []) > 1 and os.environ.get("LIVE_EXECUTION_QUALIFIED") != "1":
            raise PermissionError(
                "Live freeze-limit sliced orders are disabled until child-order IDs, "
                "partial fills, and restart recovery are durably tracked. The order "
                "remains CONFIRMED and was not sent to the broker."
            )

        if d.get("stop_loss") and bool(d.get("auto_gtt_oco", 1)):
            raise PermissionError(
                "Live automatic protective GTT orders are disabled until protective "
                "order activation, rejection, cancellation, and fill events are "
                "durably monitored. The order remains CONFIRMED and was not sent "
                "to the broker."
            )

    if mode_info.is_observe:
        d["status"] = "REJECTED"
        d["rejection_reason"] = "Mutation blocked: System is operating in OBSERVE mode."
        with _get_orders_db() as conn:
            conn.execute(
                "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ? AND status = 'CONFIRMED'",
                (d["status"], d["rejection_reason"], now_iso, order_id),
            )
            conn.commit()
        record_audit_event(
            "ORDER_REJECTED_OBSERVE_MODE", mode="OBSERVE", details={"order_id": order_id}
        )
    elif mode_info.is_simulate:
        # Atomic transition CONFIRMED -> SUBMITTING immediately before paper submission
        with _get_orders_db() as conn:
            cursor = conn.execute(
                """
                UPDATE orders_ledger
                SET status = 'SUBMITTING', updated_at = ?
                WHERE order_id = ? AND status = 'CONFIRMED' AND mode = ?
                """,
                (now_iso, order_id, mode_info.mode.name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Order {order_id} state transition to SUBMITTING failed (order is not CONFIRMED, mode mismatched, or already submitted)."
                )
        d["status"] = "SUBMITTING"
        # Paper trading execution: apply to PaperBroker for balance & position tracking
        t_order_0 = time.time()
        try:
            from brokers.base import OrderRequest
            from engine.paper import PaperBroker
            from market.instruments import resolve_canonical_instrument

            inst = resolve_canonical_instrument(d["symbol"])
            _paper_exchange = d.get("exchange") or inst.exchange

            paper_broker = PaperBroker()
            from engine.smart_order_router import slice_quantity_by_freeze_limit

            inst_lot = getattr(inst, "lot_size", 1) or 1
            try:
                slices = slice_quantity_by_freeze_limit(
                    d["symbol"] if ":" in str(d["symbol"]) else f"{_paper_exchange}:{d['symbol']}",
                    d["quantity"],
                    inst_lot,
                    segment=d.get("segment"),
                )
            except (RuntimeError, ValueError, OSError) as freeze_error:
                # Paper mode has no broker side effect. Keep simulation usable if
                # today's RMS master is unavailable, and disclose degraded validation.
                logger.warning(
                    "[order_lifecycle] Paper order freeze metadata unavailable for %s; "
                    "simulating unsliced with degraded exchange validation: %s",
                    d["symbol"],
                    freeze_error,
                )
                slices = [int(d["quantity"])]
            if not slices:
                slices = [d["quantity"]]

            charges_dict = (
                json.loads(d.get("charges_json") or "{}")
                if isinstance(d.get("charges_json"), str)
                else (d.get("charges") or {})
            )
            trigger_px = charges_dict.get("trigger_price")

            if len(slices) == 1:
                req = OrderRequest(
                    symbol=d["symbol"],
                    exchange=_paper_exchange,
                    transaction_type=d["side"],
                    order_type=d["order_type"],
                    product=d["product"],
                    quantity=d["quantity"],
                    price=d["price"],
                    trigger_price=trigger_px,
                )
                paper_res = paper_broker.place_order(req)
                if paper_res.status == "COMPLETE":
                    d["status"] = "FILLED_PAPER"
                    d["broker_order_id"] = f"PAPER-EXEC-{paper_res.order_id}"
                    if (
                        getattr(paper_res, "average_price", None)
                        and float(paper_res.average_price) > 0
                    ):
                        d["fill_price"] = float(paper_res.average_price)
                elif paper_res.status == "REJECTED":
                    d["status"] = "REJECTED"
                    d["rejection_reason"] = paper_res.message or "Rejected by PaperBroker"
                else:
                    d["status"] = "OPEN"
                    d["broker_order_id"] = f"PAPER-OPEN-{paper_res.order_id}"
            else:
                child_ids = []
                all_complete = True
                any_rejected = False
                rej_msg = ""
                total_filled_qty = 0
                total_cost = 0.0

                # Pre-persist all child tranches in orders_ledger before dispatching
                with _get_orders_db() as conn:
                    for idx, s_qty in enumerate(slices):
                        c_order_id = f"{order_id}-C{idx + 1}"
                        c_idemp = f"{d['idempotency_key']}-C{idx + 1}"
                        conn.execute(
                            """
                            INSERT INTO orders_ledger (
                                order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
                                order_type, product, status, mode, charges_json, preview_hash,
                                stop_loss, target, auto_gtt_oco, parent_order_id, slice_index, total_slices,
                                created_at, updated_at, account_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(idempotency_key) DO UPDATE SET updated_at = excluded.updated_at
                            """,
                            (
                                c_order_id,
                                c_idemp,
                                d["symbol"],
                                _paper_exchange,
                                d.get("segment", "EQUITY_INTRADAY"),
                                d["side"],
                                s_qty,
                                d["price"],
                                d["order_type"],
                                d["product"],
                                mode_info.mode.name,
                                json.dumps(charges_dict),
                                d.get("preview_hash"),
                                d.get("stop_loss"),
                                d.get("target"),
                                1 if d.get("auto_gtt_oco", 1) else 0,
                                order_id,
                                idx + 1,
                                len(slices),
                                now_iso,
                                now_iso,
                                d.get("account_id") or "SIMULATED_PAPER_ACCOUNT",
                            ),
                        )
                    conn.commit()

                for idx, s_qty in enumerate(slices):
                    c_order_id = f"{order_id}-C{idx + 1}"
                    with _get_orders_db() as conn:
                        conn.execute(
                            "UPDATE orders_ledger SET status = 'SUBMITTING', updated_at = ? WHERE order_id = ?",
                            (now_iso, c_order_id),
                        )
                        conn.commit()

                    req = OrderRequest(
                        symbol=d["symbol"],
                        exchange=_paper_exchange,
                        transaction_type=d["side"],
                        order_type=d["order_type"],
                        product=d["product"],
                        quantity=s_qty,
                        price=d["price"],
                        trigger_price=trigger_px,
                        tag=c_order_id,
                    )
                    paper_res = paper_broker.place_order(req)
                    if paper_res.status == "COMPLETE":
                        child_ids.append(paper_res.order_id)
                        c_broker_id = f"PAPER-EXEC-{paper_res.order_id}"
                        c_fill_px = (
                            float(paper_res.average_price)
                            if (
                                getattr(paper_res, "average_price", None)
                                and float(paper_res.average_price) > 0
                            )
                            else float(d["price"])
                        )
                        total_filled_qty += s_qty
                        total_cost += s_qty * c_fill_px
                        with _get_orders_db() as conn:
                            conn.execute(
                                """
                                UPDATE orders_ledger
                                SET status = 'FILLED_PAPER', broker_order_id = ?, filled_quantity = ?,
                                    average_fill_price = ?, updated_at = ?
                                WHERE order_id = ?
                                """,
                                (c_broker_id, s_qty, c_fill_px, now_iso, c_order_id),
                            )
                            conn.commit()
                        _record_order_event(
                            c_order_id,
                            "CHILD_ORDER_FILLED",
                            broker_name="PaperBroker",
                            broker_order_id=c_broker_id,
                            payload={"quantity": s_qty, "price": c_fill_px},
                        )
                    elif paper_res.status == "REJECTED":
                        any_rejected = True
                        rej_msg = paper_res.message or "Rejected by PaperBroker"
                        with _get_orders_db() as conn:
                            conn.execute(
                                """
                                UPDATE orders_ledger
                                SET status = 'REJECTED', rejection_reason = ?, updated_at = ?
                                WHERE order_id = ?
                                """,
                                (rej_msg, now_iso, c_order_id),
                            )
                            conn.commit()
                        _record_order_event(
                            c_order_id,
                            "CHILD_ORDER_REJECTED",
                            broker_name="PaperBroker",
                            payload={"reason": rej_msg},
                        )
                        break
                    else:
                        child_ids.append(paper_res.order_id)
                        all_complete = False
                        c_broker_id = f"PAPER-OPEN-{paper_res.order_id}"
                        with _get_orders_db() as conn:
                            conn.execute(
                                """
                                UPDATE orders_ledger
                                SET status = 'OPEN', broker_order_id = ?, updated_at = ?
                                WHERE order_id = ?
                                """,
                                (c_broker_id, now_iso, c_order_id),
                            )
                            conn.commit()

                d["filled_quantity"] = total_filled_qty
                if total_filled_qty > 0:
                    d["average_fill_price"] = total_cost / total_filled_qty
                    d["fill_price"] = d["average_fill_price"]

                if any_rejected:
                    if child_ids:
                        d["status"] = "PARTIALLY_FILLED"
                        d["rejection_reason"] = (
                            f"Partial fill: {len(child_ids)} tranches filled before rejection: {rej_msg}"
                        )
                        d["broker_order_id"] = (
                            f"PAPER-EXEC-SLICED-{','.join(str(cid) for cid in child_ids)}"
                        )
                    else:
                        d["status"] = "REJECTED"
                        d["rejection_reason"] = f"Tranche rejected: {rej_msg}"
                elif all_complete:
                    d["status"] = "FILLED_PAPER"
                    d["broker_order_id"] = (
                        f"PAPER-EXEC-SLICED-{','.join(str(cid) for cid in child_ids)}"
                    )
                else:
                    d["status"] = "OPEN"
                    d["broker_order_id"] = (
                        f"PAPER-OPEN-SLICED-{','.join(str(cid) for cid in child_ids)}"
                    )
        except Exception as paper_exc:
            d["status"] = "REJECTED"
            d["rejection_reason"] = f"PaperBroker error: {paper_exc}"
            d["broker_order_id"] = None

        try:
            from engine.observability import get_registry

            get_registry().record_metric(
                journey_id="paper_order_submit",
                latency_ms=(time.time() - t_order_0) * 1000.0,
                success=(d["status"] in ("FILLED_PAPER", "OPEN")),
                metadata={"order_id": order_id, "symbol": d.get("symbol")},
            )
        except Exception as e_obs:
            logger.debug(f"[order_lifecycle] Failed recording paper order metric: {e_obs}")

        with _get_orders_db() as conn:
            conn.execute(
                """
                UPDATE orders_ledger
                SET status = ?, broker_order_id = ?, rejection_reason = ?, gtt_order_id = ?,
                    filled_quantity = ?, average_fill_price = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (
                    d["status"],
                    d["broker_order_id"],
                    d["rejection_reason"],
                    d.get("gtt_order_id"),
                    d.get("filled_quantity", 0),
                    d.get("average_fill_price"),
                    now_iso,
                    order_id,
                ),
            )
            conn.commit()

        # Persist execution fill into institutional ledger with simulation provenance
        if d["status"] == "FILLED_PAPER":
            try:
                prod = str(d.get("product") or "MIS").upper()
                resolved_seg = str(
                    d.get("segment") or ("EQUITY_DELIVERY" if prod == "CNC" else "EQUITY_INTRADAY")
                ).upper()
                f_price = float(d.get("fill_price") or d.get("price") or 0.0)
                qty = int(d["quantity"])
                chg_res = calculate_transaction_charges(
                    price=f_price,
                    quantity=qty,
                    segment=resolved_seg,  # type: ignore
                    side=d["side"],  # type: ignore
                )
                chg = float(chg_res.total_charges)
                paper_account = d.get("account_id") or "SIMULATED_PAPER_ACCOUNT"
                record_execution_fill(
                    account_id=paper_account,
                    broker_name=d.get("broker") or "PAPER",
                    order_id=order_id,
                    broker_order_id=str(d.get("broker_order_id") or f"PAPER-{order_id}"),
                    broker_trade_id=f"SIM-TRADE-{order_id}",
                    symbol=d["symbol"],
                    exchange=d.get("exchange", "NSE"),
                    segment=resolved_seg,
                    side=d["side"],
                    quantity=qty,
                    fill_price=f_price,
                    fill_time=now_iso,
                    charges=chg,
                    product=prod,
                )
                d["ledger_status"] = "RECORDED"
            except Exception as e_fill_record:
                logger.error(f"[order_lifecycle] Paper fill recording error: {e_fill_record}")
                d["ledger_status"] = "INGESTION_FAILED"
                d["ledger_error"] = str(e_fill_record)
                with _get_orders_db() as conn:
                    conn.execute(
                        "UPDATE orders_ledger SET ledger_status = ?, ledger_error = ?, updated_at = ? WHERE order_id = ?",
                        ("INGESTION_FAILED", str(e_fill_record), now_iso, order_id),
                    )
                    conn.commit()

        # Server-side native GTT OCO bracket auto-arming on paper fill
        if d["status"] == "FILLED_PAPER" and d.get("auto_gtt_oco") and d.get("stop_loss"):
            try:
                from brokers.base import GTTLeg, GTTRequest

                exit_side = "SELL" if d["side"] == "BUY" else "BUY"
                sl_val = float(d["stop_loss"])
                leg1 = GTTLeg(price=sl_val, trigger_price=sl_val, quantity=d["quantity"])
                leg2 = None
                trigger_type = "SINGLE"
                if d.get("target"):
                    tgt_val = float(d["target"])
                    leg2 = GTTLeg(price=tgt_val, trigger_price=tgt_val, quantity=d["quantity"])
                    trigger_type = "OCO"
                gtt_req = GTTRequest(
                    symbol=d["symbol"],
                    exchange=d.get("exchange", "NSE"),
                    transaction_type=exit_side,
                    trigger_type=trigger_type,
                    product=d["product"],
                    leg1=leg1,
                    leg2=leg2,
                )
                gtt_res = paper_broker.place_gtt(gtt_req)
                if getattr(gtt_res, "status", None) == "ACTIVE":
                    d["gtt_order_id"] = gtt_res.gtt_id
                    with _get_orders_db() as conn:
                        conn.execute(
                            "UPDATE orders_ledger SET gtt_order_id = ? WHERE order_id = ?",
                            (d["gtt_order_id"], order_id),
                        )
                        conn.commit()
                    _record_order_event(
                        order_id,
                        "GTT_ARMED",
                        broker_name="paper",
                        broker_order_id=gtt_res.gtt_id,
                        payload={
                            "gtt_id": gtt_res.gtt_id,
                            "trigger_type": trigger_type,
                            "stop_loss": sl_val,
                            "target": d.get("target"),
                        },
                    )
            except Exception as e_gtt:
                logger.warning(f"[order_lifecycle] Paper GTT arming skipped: {e_gtt}")

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
        # Safety gate 2: pre-trade validation with live market context
        from engine.pretrade import validate_pretrade
        from engine.observability import new_correlation_id
        from market.instruments import resolve_canonical_instrument

        pretrade_correlation_id = new_correlation_id("live_order")
        inst = resolve_canonical_instrument(d["symbol"])
        from market.instrument_master import get_verified_contract

        verified = get_verified_contract(d["symbol"])
        execution_lot = int(verified["lot_size"]) if verified else inst.lot_size
        execution_tick = float(verified["tick_size"]) if verified else inst.tick_size
        _live_exchange = d.get("exchange") or inst.exchange
        _live_segment = d.get("segment") or inst.segment
        from engine.pilot_safety import assert_pilot_execution_allowed

        assert_pilot_execution_allowed(
            segment=_live_segment,
            product=d["product"],
            notional=float(d["price"]) * int(d["quantity"]),
        )

        # Fetch live quote + broker funds BEFORE calling validate_pretrade.
        _ltp: float | None = None
        _quote_age_seconds: float | None = None
        _available_cash: float | None = None
        _account: str | None = None

        try:
            from brokers.session import get_execution_broker, get_execution_broker_key
            from market.quotes import get_quote

            _ctx_broker = get_execution_broker()
            if _ctx_broker is None:
                raise RuntimeError("No authenticated broker session for pretrade context fetch.")

            _account = getattr(_ctx_broker, "account_id", None) or getattr(
                _ctx_broker, "client_id", None
            )

            # Fetch quote through the data-provider boundary.  Market age comes
            # from the received event, never the REST round-trip duration.
            _instrument = f"{_live_exchange}:{d['symbol']}"
            _quotes = get_quote([_instrument])
            _q = _quotes.get(_instrument) or _quotes.get(d["symbol"])
            if _q is not None:
                _ltp = getattr(_q, "last_price", None)
                _quote_age_seconds = getattr(_q, "age_seconds", None)
                if callable(_quote_age_seconds):
                    _quote_age_seconds = _quote_age_seconds()
                if getattr(_q, "data_state", "UNAVAILABLE") != "LIVE":
                    raise RuntimeError(
                        f"Live execution requires fresh LIVE data; received {getattr(_q, 'data_state', 'UNAVAILABLE')} "
                        f"from {getattr(_q, 'provider', 'unknown')}"
                    )
            if _ltp is None or _ltp <= 0 or _quote_age_seconds is None:
                raise RuntimeError(
                    "No timestamped fresh quote was available for live pre-trade validation."
                )

            _funds = get_cached_broker_funds(_ctx_broker, max_age=5.0)
            _available_cash = (
                _funds.available_cash
                if hasattr(_funds, "available_cash")
                else float(_funds.get("available_cash", 0.0))
                if isinstance(_funds, dict)
                else None
            )
            _prev_close = getattr(_q, "prev_close", None) or getattr(_q, "close", None)
            _portfolio_val = (
                getattr(_funds, "total_balance", None)
                or getattr(_funds, "equity_balance", None)
                or _available_cash
                if _funds is not None
                else None
            )
            try:
                from engine.risk_limits import get_pnl_tracker

                _daily_pnl = get_pnl_tracker().get_daily_pnl(account_id=_account, mode="EXECUTE")
            except Exception:
                _daily_pnl = None

        except Exception as _ctx_exc:
            # Order remains CONFIRMED (no broker call occurred, not UNKNOWN_FREEZE)
            logger.warning(
                f"[order_lifecycle] Live pretrade context fetch failed for {order_id}: {_ctx_exc}"
            )
            raise RuntimeError(
                f"Live order {order_id} blocked: pretrade context fetch failed: {_ctx_exc}"
            ) from _ctx_exc

        _no_chase = None
        _depth_sweep_vwap = None
        if isinstance(charges_d, dict):
            _raw_nc = charges_d.get("no_chase_boundary")
            if isinstance(_raw_nc, (int, float)) and _raw_nc > 0:
                _no_chase = float(_raw_nc)
            _raw_vwap = charges_d.get("depth_sweep_vwap") or charges_d.get(
                "orderbook_expected_vwap"
            )
            if isinstance(_raw_vwap, (int, float)) and _raw_vwap > 0:
                _depth_sweep_vwap = float(_raw_vwap)

        pretrade = validate_pretrade(
            symbol=d["symbol"],
            side=d["side"],
            quantity=d["quantity"],
            order_type=d["order_type"],
            price=d["price"] if d["price"] else None,
            segment=_live_segment,
            account=_account,
            broker=get_execution_broker_key(),
            lot_size=execution_lot,
            tick_size=execution_tick,
            ltp=_ltp,
            prev_close=_prev_close,
            quote_age_seconds=_quote_age_seconds,
            available_cash=_available_cash,
            portfolio_value=_portfolio_val,
            daily_pnl=_daily_pnl,
            trigger_price=d["price"] if d.get("order_type") == "MARKET" else None,
            no_chase_boundary=_no_chase,
            depth_sweep_vwap=_depth_sweep_vwap,
            require_context=True,
            correlation_id=pretrade_correlation_id,
        )
        if not pretrade.is_eligible:
            reasons = "; ".join(pretrade.blocking_reasons)
            d["status"] = "REJECTED"
            d["rejection_reason"] = f"Pre-trade validation blocked: {reasons}"
            with _get_orders_db() as conn:
                conn.execute(
                    "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ? AND status = 'CONFIRMED'",
                    (d["status"], d["rejection_reason"], now_iso, order_id),
                )
                conn.commit()
            raise ValueError(f"Pre-trade validation blocked: {reasons}")

        from engine.recovery_worker import has_active_unknown_freeze

        if has_active_unknown_freeze(_account):
            raise PermissionError(
                f"Live order submission blocked: Account {_account} has active UNKNOWN_FREEZE orders "
                "requiring reconciliation. Resolve outstanding frozen orders before placing new trades."
            )

        # All local safety gates passed! Atomic transition CONFIRMED -> SUBMITTING right before broker place_order
        with _get_orders_db() as conn:
            cursor = conn.execute(
                """
                UPDATE orders_ledger
                SET status = 'SUBMITTING', updated_at = ?
                WHERE order_id = ? AND status = 'CONFIRMED' AND mode = ?
                """,
                (now_iso, order_id, mode_info.mode.name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Order {order_id} state transition to SUBMITTING failed (order is not CONFIRMED, mode mismatched, or already submitted)."
                )
        d["status"] = "SUBMITTING"

        # Safety gate 3: submit to real broker adapter
        try:
            from brokers.session import get_execution_broker, get_execution_broker_key
            from brokers.base import OrderRequest

            live_broker = get_execution_broker()
            if live_broker is None:
                raise RuntimeError("No authenticated broker session available for live execution.")

            from engine.smart_order_router import slice_quantity_by_freeze_limit

            inst_lot = getattr(inst, "lot_size", 1) or 1
            slices = slice_quantity_by_freeze_limit(
                d["symbol"] if ":" in str(d["symbol"]) else f"{d['exchange']}:{d['symbol']}",
                d["quantity"],
                inst_lot,
                segment=d.get("segment"),
            )
            if not slices:
                slices = [d["quantity"]]

            execution_provider = (
                get_execution_broker_key() or live_broker.__class__.__name__.lower()
            )

            charges_dict = (
                json.loads(d.get("charges_json") or "{}")
                if isinstance(d.get("charges_json"), str)
                else (d.get("charges") or {})
            )
            trigger_px = charges_dict.get("trigger_price")

            if len(slices) == 1:
                broker_req = OrderRequest(
                    symbol=d["symbol"],
                    exchange=_live_exchange,
                    transaction_type=d["side"],
                    order_type=d["order_type"],
                    product=d["product"],
                    quantity=d["quantity"],
                    price=d["price"],
                    trigger_price=trigger_px,
                    tag=order_id,
                )

                broker_res = live_broker.place_order(broker_req)

                from brokers.order_types import normalize_order_status

                norm_status = normalize_order_status(broker_res.status)
                if norm_status in ("COMPLETE", "OPEN", "SUBMITTED"):
                    d["status"] = "OPEN" if norm_status in ("OPEN", "SUBMITTED") else "FILLED"
                    d["broker_order_id"] = broker_res.order_id

                    with _get_orders_db() as conn:
                        conn.execute(
                            "UPDATE orders_ledger SET status = ?, broker_order_id = ?, updated_at = ? WHERE order_id = ?",
                            (d["status"], d["broker_order_id"], now_iso, order_id),
                        )
                        conn.commit()

                    # Ingest authentic fills on OPEN, SUBMITTED, FILLED, or PARTIALLY_FILLED
                    if d["status"] in ("FILLED", "PARTIALLY_FILLED", "OPEN", "SUBMITTED"):
                        try:
                            recorded = ingest_broker_executions(
                                order_id=order_id,
                                broker_order_id=str(d["broker_order_id"]),
                                live_broker=live_broker,
                                broker_res=broker_res,
                                order_details=d,
                            )
                            if not recorded:
                                d["ledger_status"] = (
                                    "RECORDED"
                                    if d["status"] in ("OPEN", "SUBMITTED")
                                    else "PENDING_FACTS"
                                )
                            else:
                                d["ledger_status"] = "RECORDED"
                        except Exception as e_fill_record:
                            logger.error(
                                f"[order_lifecycle] Execution fill ingestion failed for {order_id}: {e_fill_record}"
                            )
                            d["ledger_status"] = "INGESTION_FAILED"
                            d["ledger_error"] = str(e_fill_record)
                            with _get_orders_db() as conn:
                                conn.execute(
                                    "UPDATE orders_ledger SET ledger_status = ?, ledger_error = ?, updated_at = ? WHERE order_id = ?",
                                    ("INGESTION_FAILED", str(e_fill_record), now_iso, order_id),
                                )
                                conn.commit()
                            _record_order_event(
                                order_id,
                                "LEDGER_INGESTION_FAILED",
                                correlation_id=pretrade_correlation_id,
                                broker_name=execution_provider,
                                broker_order_id=d["broker_order_id"],
                                payload={"error": str(e_fill_record)},
                            )

                    if d["status"] == "OPEN":
                        try:
                            from market.fyers_tbt_manager import FyersTbtManager

                            FyersTbtManager().register_in_flight(d["symbol"])
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[engine.order_lifecycle] Non-fatal exception suppressed: {e_suppressed}"
                            )

                    _record_order_event(
                        order_id,
                        "BROKER_RESPONSE",
                        correlation_id=pretrade_correlation_id,
                        broker_name=execution_provider,
                        broker_order_id=d["broker_order_id"],
                        payload={
                            "status": d["status"],
                            "filled_quantity": getattr(broker_res, "filled_quantity", 0),
                        },
                    )

                    # Server-side native GTT OCO bracket auto-arming on live fill
                    if d["status"] == "FILLED" and d.get("auto_gtt_oco") and d.get("stop_loss"):
                        try:
                            from brokers.base import GTTLeg, GTTRequest

                            exit_side = "SELL" if d["side"] == "BUY" else "BUY"
                            sl_val = float(d["stop_loss"])
                            sl_limit = (
                                round(sl_val * 0.995, 2)
                                if exit_side == "SELL"
                                else round(sl_val * 1.005, 2)
                            )
                            leg1 = GTTLeg(
                                price=sl_limit, trigger_price=sl_val, quantity=d["quantity"]
                            )
                            leg2 = None
                            trigger_type = "SINGLE"
                            if d.get("target"):
                                tgt_val = float(d["target"])
                                leg2 = GTTLeg(
                                    price=tgt_val, trigger_price=tgt_val, quantity=d["quantity"]
                                )
                                trigger_type = "OCO"
                            gtt_req = GTTRequest(
                                symbol=d["symbol"],
                                exchange=_live_exchange,
                                transaction_type=exit_side,
                                trigger_type=trigger_type,
                                product=d["product"],
                                leg1=leg1,
                                leg2=leg2,
                            )
                            if hasattr(live_broker, "place_gtt"):
                                gtt_res = live_broker.place_gtt(gtt_req)
                                if getattr(gtt_res, "status", None) == "ACTIVE":
                                    d["gtt_order_id"] = gtt_res.gtt_id
                                    with _get_orders_db() as conn_gtt:
                                        conn_gtt.execute(
                                            "UPDATE orders_ledger SET gtt_order_id = ? WHERE order_id = ?",
                                            (d["gtt_order_id"], order_id),
                                        )
                                        conn_gtt.commit()
                                    _record_order_event(
                                        order_id,
                                        "GTT_ARMED",
                                        correlation_id=pretrade_correlation_id,
                                        broker_name=execution_provider,
                                        broker_order_id=gtt_res.gtt_id,
                                        payload={
                                            "gtt_id": gtt_res.gtt_id,
                                            "trigger_type": trigger_type,
                                            "stop_loss": sl_val,
                                            "target": d.get("target"),
                                        },
                                    )
                        except Exception as e_gtt:
                            logger.warning(
                                f"[order_lifecycle] Live GTT auto-arming failed: {e_gtt}"
                            )

                elif broker_res.status == "REJECTED":
                    d["status"] = "REJECTED"
                    d["rejection_reason"] = broker_res.message or "Rejected by live broker"

                    with _get_orders_db() as conn:
                        conn.execute(
                            "UPDATE orders_ledger SET status = ?, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                            (d["status"], d["rejection_reason"], now_iso, order_id),
                        )
                        conn.commit()

                    try:
                        from market.fyers_tbt_manager import FyersTbtManager

                        FyersTbtManager().unregister_in_flight(d["symbol"])
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.order_lifecycle] Non-fatal exception suppressed: {e_suppressed}"
                        )

                    _record_order_event(
                        order_id,
                        "BROKER_REJECTED",
                        correlation_id=pretrade_correlation_id,
                        broker_name=execution_provider,
                        payload={"reason": d["rejection_reason"]},
                    )

                else:
                    # Ambiguous state -> freeze, but preserve authentic broker order ID if present
                    d["status"] = "UNKNOWN_FREEZE"
                    d["broker_order_id"] = str(getattr(broker_res, "order_id", None) or "") or None
                    d["rejection_reason"] = (
                        f"Ambiguous broker response status: {broker_res.status}. "
                        "Order frozen for manual reconciliation."
                    )

                    with _get_orders_db() as conn:
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
                    _record_order_event(
                        order_id,
                        "UNKNOWN_FREEZE",
                        correlation_id=pretrade_correlation_id,
                        broker_name=execution_provider,
                        payload={"reason": d["rejection_reason"]},
                    )
            else:
                # Sliced institutional execution across child tranches with durable tracking
                tranche_order_ids = []
                all_complete = True
                any_rejected = False
                rej_msg = ""
                total_filled_qty = 0
                total_cost = 0.0

                # Pre-persist all child tranches in orders_ledger before dispatching to broker
                with _get_orders_db() as conn:
                    for idx, s_qty in enumerate(slices):
                        c_order_id = f"{order_id}-C{idx + 1}"
                        c_idemp = f"{d['idempotency_key']}-C{idx + 1}"
                        conn.execute(
                            """
                            INSERT INTO orders_ledger (
                                order_id, idempotency_key, symbol, exchange, segment, side, quantity, price,
                                order_type, product, status, mode, charges_json, preview_hash,
                                stop_loss, target, auto_gtt_oco, parent_order_id, slice_index, total_slices,
                                created_at, updated_at, account_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(idempotency_key) DO UPDATE SET updated_at = excluded.updated_at
                            """,
                            (
                                c_order_id,
                                c_idemp,
                                d["symbol"],
                                _live_exchange,
                                d.get("segment", "EQUITY_INTRADAY"),
                                d["side"],
                                s_qty,
                                d["price"],
                                d["order_type"],
                                d["product"],
                                mode_info.mode.name,
                                json.dumps(charges_dict),
                                d.get("preview_hash"),
                                d.get("stop_loss"),
                                d.get("target"),
                                1 if d.get("auto_gtt_oco", 1) else 0,
                                order_id,
                                idx + 1,
                                len(slices),
                                now_iso,
                                now_iso,
                                str(_account)
                                if isinstance(_account, str)
                                else str(d.get("account_id") or "LIVE_ACCOUNT"),
                            ),
                        )
                    conn.commit()

                from brokers.order_types import normalize_order_status

                for idx, s_qty in enumerate(slices):
                    c_order_id = f"{order_id}-C{idx + 1}"
                    with _get_orders_db() as conn:
                        conn.execute(
                            "UPDATE orders_ledger SET status = 'SUBMITTING', updated_at = ? WHERE order_id = ?",
                            (now_iso, c_order_id),
                        )
                        conn.commit()

                    broker_req = OrderRequest(
                        symbol=d["symbol"],
                        exchange=_live_exchange,
                        transaction_type=d["side"],
                        order_type=d["order_type"],
                        product=d["product"],
                        quantity=s_qty,
                        price=d["price"],
                        trigger_price=trigger_px,
                        tag=c_order_id,
                    )
                    try:
                        b_res = live_broker.place_order(broker_req)
                        norm_status = normalize_order_status(b_res.status)
                        if norm_status in ("COMPLETE", "OPEN", "SUBMITTED"):
                            c_status = "OPEN" if norm_status in ("OPEN", "SUBMITTED") else "FILLED"
                            c_broker_id = str(b_res.order_id)
                            c_filled = int(
                                getattr(
                                    b_res,
                                    "filled_quantity",
                                    s_qty if norm_status == "COMPLETE" else 0,
                                )
                                or 0
                            )
                            c_avg_px = float(
                                getattr(b_res, "average_price", d["price"]) or d["price"]
                            )
                            tranche_order_ids.append(c_broker_id)
                            total_filled_qty += c_filled
                            total_cost += c_filled * c_avg_px
                            if norm_status != "COMPLETE":
                                all_complete = False

                            with _get_orders_db() as conn:
                                conn.execute(
                                    """
                                    UPDATE orders_ledger
                                    SET status = ?, broker_order_id = ?, filled_quantity = ?, average_fill_price = ?, updated_at = ?
                                    WHERE order_id = ?
                                    """,
                                    (
                                        c_status,
                                        c_broker_id,
                                        c_filled,
                                        c_avg_px if c_avg_px > 0 else None,
                                        now_iso,
                                        c_order_id,
                                    ),
                                )
                                conn.commit()

                            _record_order_event(
                                c_order_id,
                                "CHILD_ORDER_SUBMITTED",
                                correlation_id=pretrade_correlation_id,
                                broker_name=execution_provider,
                                broker_order_id=c_broker_id,
                                payload={"status": c_status, "filled_quantity": c_filled},
                            )
                        elif norm_status == "REJECTED":
                            any_rejected = True
                            rej_msg = b_res.message or "Tranche rejected by live broker"
                            with _get_orders_db() as conn:
                                conn.execute(
                                    "UPDATE orders_ledger SET status = 'REJECTED', rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                                    (rej_msg, now_iso, c_order_id),
                                )
                                conn.commit()
                            _record_order_event(
                                c_order_id,
                                "CHILD_ORDER_REJECTED",
                                correlation_id=pretrade_correlation_id,
                                broker_name=execution_provider,
                                payload={"reason": rej_msg},
                            )
                            break
                        else:
                            tranche_order_ids.append(str(b_res.order_id))
                            all_complete = False
                    except Exception as tranche_exc:
                        c_reason = (
                            f"Live child order broker call raised {type(tranche_exc).__name__}: {tranche_exc}. "
                            "Child slice status ambiguous; frozen for manual reconciliation."
                        )
                        with _get_orders_db() as conn:
                            conn.execute(
                                "UPDATE orders_ledger SET status = 'UNKNOWN_FREEZE', broker_order_id = NULL, rejection_reason = ?, updated_at = ? WHERE order_id = ?",
                                (c_reason, now_iso, c_order_id),
                            )
                            conn.commit()
                        _record_order_event(
                            c_order_id,
                            "UNKNOWN_FREEZE",
                            correlation_id=pretrade_correlation_id,
                            payload={"reason": c_reason},
                        )

                        d["status"] = "UNKNOWN_FREEZE"
                        d["broker_order_id"] = (
                            f"SLICED:{','.join(str(tid) for tid in tranche_order_ids)}"
                            if tranche_order_ids
                            else None
                        )
                        d["rejection_reason"] = (
                            f"Tranche {idx + 1} raised {type(tranche_exc).__name__}: {tranche_exc}. "
                            "Order status ambiguous; frozen for manual reconciliation."
                        )
                        d["filled_quantity"] = total_filled_qty
                        d["average_fill_price"] = (
                            (total_cost / total_filled_qty) if total_filled_qty > 0 else None
                        )
                        with _get_orders_db() as conn:
                            conn.execute(
                                """
                                UPDATE orders_ledger
                                SET status = ?, broker_order_id = ?, rejection_reason = ?, filled_quantity = ?,
                                    average_fill_price = ?, updated_at = ?
                                WHERE order_id = ?
                                """,
                                (
                                    d["status"],
                                    d["broker_order_id"],
                                    d["rejection_reason"],
                                    d["filled_quantity"],
                                    d["average_fill_price"],
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
                                "exception": str(tranche_exc),
                            },
                        )
                        return _row_to_intent(d)

                d["filled_quantity"] = total_filled_qty
                d["average_fill_price"] = (
                    (total_cost / total_filled_qty) if total_filled_qty > 0 else None
                )

                if any_rejected and not tranche_order_ids:
                    d["status"] = "REJECTED"
                    d["rejection_reason"] = rej_msg
                elif any_rejected:
                    d["status"] = "PARTIALLY_FILLED"
                    d["rejection_reason"] = (
                        f"Partial fill: {len(tranche_order_ids)} tranches submitted before rejection: {rej_msg}"
                    )
                    d["broker_order_id"] = (
                        f"SLICED:{','.join(str(tid) for tid in tranche_order_ids)}"
                    )
                else:
                    d["status"] = "FILLED" if all_complete else "OPEN"
                    d["broker_order_id"] = (
                        f"SLICED:{','.join(str(tid) for tid in tranche_order_ids)}"
                    )

                with _get_orders_db() as conn:
                    conn.execute(
                        """
                        UPDATE orders_ledger
                        SET status = ?, broker_order_id = ?, rejection_reason = ?, filled_quantity = ?,
                            average_fill_price = ?, updated_at = ?
                        WHERE order_id = ?
                        """,
                        (
                            d["status"],
                            d["broker_order_id"],
                            d.get("rejection_reason"),
                            d["filled_quantity"],
                            d["average_fill_price"],
                            now_iso,
                            order_id,
                        ),
                    )
                    conn.commit()

                _record_order_event(
                    order_id,
                    "BROKER_RESPONSE_SLICED",
                    correlation_id=pretrade_correlation_id,
                    broker_name=execution_provider,
                    broker_order_id=d["broker_order_id"],
                    payload={
                        "status": d["status"],
                        "tranche_count": len(slices),
                        "filled_quantity": total_filled_qty,
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

            with _get_orders_db() as conn:
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
            _record_order_event(
                order_id,
                "UNKNOWN_FREEZE",
                correlation_id=pretrade_correlation_id,
                payload={"reason": d["rejection_reason"]},
            )
            raise RuntimeError(
                f"Live order {order_id} frozen in UNKNOWN_FREEZE state due to broker exception: {live_exc}"
            ) from live_exc

    return _row_to_intent(d)


def execute_order_batch(order_ids: list[str]) -> list[OrderIntent]:
    """
    Execute a micro-batch of server-CONFIRMED order intents atomically.

    SIMULATE mode executes confirmed legs sequentially through PaperBroker.
    Live baskets remain disabled until every leg has durable child-order/fill
    tracking and partial-basket recovery. Broker basket APIs do not guarantee
    portfolio-level atomicity.
    """
    if not order_ids:
        return []

    if len(order_ids) == 1:
        return [execute_order_intent(order_ids[0])]

    _init_orders_db()

    # Institutional Spread Leg Sequencing Invariant:
    # BUY legs MUST strictly execute before SELL legs so the long hedge is registered
    # with broker RMS, providing ~70%+ margin relief and preventing false naked margin rejections.
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in order_ids)
        rows = conn.execute(
            f"SELECT order_id, side FROM orders_ledger WHERE order_id IN ({placeholders})",
            order_ids,
        ).fetchall()
        side_map = {r["order_id"]: str(r["side"]).upper() for r in rows}
        sorted_order_ids = sorted(
            order_ids,
            key=lambda oid: 0 if side_map.get(oid) == "BUY" else 1,
        )

    mode_info = get_trading_mode()

    # If in OBSERVE or SIMULATE mode, execute sequentially via execute_order_intent
    # (paper execution maintains accurate sequential fill sequence and balances)
    if not mode_info.is_execute:
        return [execute_order_intent(oid) for oid in sorted_order_ids]

    # A basket can partially fill or reject one leg after another leg has
    # filled. The current OMS cannot durably map and reconcile those child
    # outcomes, so fail before claiming SUBMITTING or contacting the broker.
    from engine.modes import assert_live_execution_allowed

    assert_live_execution_allowed()
    raise PermissionError(
        "Live basket execution is disabled until child-order fill tracking and "
        "partial-basket recovery are implemented and qualified. Use the reviewed "
        "single-order flow or SIMULATE mode."
    )


def modify_order_intent(
    order_id: str,
    *,
    new_price: Optional[float] = None,
    new_trigger_price: Optional[float] = None,
    new_quantity: Optional[int] = None,
    actor: str = "SYSTEM",
) -> OrderIntent:
    """
    Modifies an active in-flight or resting order intent and synchronizes with broker.
    Enforces mode boundaries (SIMULATE/PAPER vs EXECUTE/LIVE) and fail-closed safety semantics.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders_ledger WHERE order_id = ? OR broker_order_id = ? LIMIT 1",
            (order_id, order_id),
        ).fetchone()

    if not row:
        raise ValueError(f"Order intent {order_id} not found in ledger.")

    d = dict(row)
    current_status = d.get("status")
    if current_status not in ("OPEN", "SUBMITTED_PAPER"):
        raise ValueError(
            f"Cannot modify order {order_id} with non-modifiable status '{current_status}'."
        )

    mod_px = float(new_price if new_price is not None else d.get("price", 0.0))
    mod_q = int(new_quantity if new_quantity is not None else d.get("quantity", 0))
    from engine.risk_limits import risk_limits, RiskLimitError

    try:
        risk_limits.check(
            symbol=d["symbol"], action=d["side"], quantity=mod_q, price=mod_px, allow_override=False
        )
    except RiskLimitError as rle:
        raise ValueError(f"Order modification violates risk limits: {rle}") from rle

    mode_str = d.get("mode", "SIMULATE")
    correlation_id = new_correlation_id("order_modify")

    # In SIMULATE / PAPER mode
    if mode_str == "SIMULATE":
        updated_price = float(new_price) if new_price is not None else float(d["price"])
        updated_qty = int(new_quantity) if new_quantity is not None else int(d["quantity"])

        charges = {}
        try:
            charges = json.loads(d.get("charges_json") or "{}")
        except Exception:
            charges = {}
        if new_trigger_price is not None:
            charges["trigger_price"] = float(new_trigger_price)

        charges_str = json.dumps(charges)

        from engine.paper import PaperBroker

        paper_broker = PaperBroker()
        broker_order_id = d.get("broker_order_id") or order_id
        try:
            paper_broker.modify_order(
                order_id=broker_order_id,
                price=new_price,
                qty=new_quantity,
                trigger_price=new_trigger_price,
            )
        except Exception as e_paper:
            logger.debug(f"[order_lifecycle] Paper broker modify note: {e_paper}")

        with _get_orders_db() as conn:
            conn.execute(
                """
                UPDATE orders_ledger
                SET price = ?, quantity = ?, charges_json = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (updated_price, updated_qty, charges_str, now_iso, order_id),
            )
            conn.commit()

        _record_order_event(
            order_id,
            "ORDER_MODIFIED_PAPER",
            correlation_id=correlation_id,
            broker_name="paper",
            payload={
                "new_price": updated_price,
                "new_trigger_price": new_trigger_price,
                "new_quantity": updated_qty,
                "actor": actor,
            },
        )

        d["price"] = updated_price
        d["quantity"] = updated_qty
        d["charges_json"] = charges_str
        d["updated_at"] = now_iso
        return _row_to_intent(d)

    # In EXECUTE / LIVE mode
    elif mode_str == "EXECUTE":
        from engine.modes import assert_live_execution_allowed

        assert_live_execution_allowed()

        broker_order_id = d.get("broker_order_id")
        if not broker_order_id:
            raise ValueError(f"Live order {order_id} has no broker_order_id to modify.")

        from brokers.session import get_execution_broker, get_execution_broker_key

        live_broker = get_execution_broker()
        if live_broker is None:
            raise RuntimeError(
                "No authenticated broker session available for live order modification."
            )

        execution_provider = get_execution_broker_key() or live_broker.__class__.__name__.lower()
        res = live_broker.modify_order(
            order_id=broker_order_id,
            price=new_price,
            qty=new_quantity,
            trigger_price=new_trigger_price,
        )

        if getattr(res, "status", None) not in ("OPEN", "COMPLETE", "SUBMITTED"):
            msg = getattr(res, "message", "Unknown error")
            _record_order_event(
                order_id,
                "ORDER_MODIFY_REJECTED",
                correlation_id=correlation_id,
                broker_name=execution_provider,
                broker_order_id=broker_order_id,
                payload={"reason": msg},
            )
            raise RuntimeError(f"Live broker rejected order modification: {msg}")

        updated_price = float(new_price) if new_price is not None else float(d["price"])
        updated_qty = int(new_quantity) if new_quantity is not None else int(d["quantity"])
        charges = {}
        try:
            charges = json.loads(d.get("charges_json") or "{}")
        except Exception:
            charges = {}
        if new_trigger_price is not None:
            charges["trigger_price"] = float(new_trigger_price)
        charges_str = json.dumps(charges)

        with _get_orders_db() as conn:
            conn.execute(
                """
                UPDATE orders_ledger
                SET price = ?, quantity = ?, charges_json = ?, updated_at = ?
                WHERE order_id = ?
                """,
                (updated_price, updated_qty, charges_str, now_iso, order_id),
            )
            conn.commit()

        _record_order_event(
            order_id,
            "ORDER_MODIFIED_LIVE",
            correlation_id=correlation_id,
            broker_name=execution_provider,
            broker_order_id=broker_order_id,
            payload={
                "new_price": updated_price,
                "new_trigger_price": new_trigger_price,
                "new_quantity": updated_qty,
                "actor": actor,
            },
        )

        d["price"] = updated_price
        d["quantity"] = updated_qty
        d["charges_json"] = charges_str
        d["updated_at"] = now_iso
        return _row_to_intent(d)

    else:
        raise ValueError(f"Cannot modify order in OBSERVE or unsupported mode '{mode_str}'.")


def ratchet_stop_loss_on_milestone(
    symbol: str,
    new_stop_loss: float,
    milestone: str = "T1_ACHIEVED",
    *,
    actor: str = "AUTO_ALERT_ENGINE",
) -> list[OrderIntent]:
    """
    Ratchets resting stop loss orders to breakeven or trailing level upon milestone reach.
    Finds resting OPEN stop-loss orders for the given symbol and updates trigger price.
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").replace("NFO:", "").strip()
    _init_orders_db()
    with _get_orders_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM orders_ledger
            WHERE (symbol = ? OR symbol = ?)
              AND status IN ('OPEN', 'SUBMITTED_PAPER')
              AND order_type IN ('SL', 'SL_LIMIT', 'SL_MARKET', 'SL-M')
            """,
            (symbol, clean_sym),
        ).fetchall()

    modified: list[OrderIntent] = []
    for r in rows:
        d = dict(r)
        current_price = float(d["price"])
        side = d["side"].upper()
        # For long position protection (side == 'SELL'), ratchet stops upward
        if side == "SELL" and new_stop_loss <= current_price:
            continue
        # For short position protection (side == 'BUY'), ratchet stops downward
        if side == "BUY" and new_stop_loss >= current_price:
            continue

        try:
            updated = modify_order_intent(
                order_id=d["order_id"],
                new_trigger_price=new_stop_loss,
                new_price=new_stop_loss,
                actor=f"{actor}:{milestone}",
            )
            modified.append(updated)
            logger.info(
                f"[order_lifecycle] Ratcheted SL for {clean_sym} ({d['order_id']}) to ₹{new_stop_loss:.2f} on {milestone}"
            )
        except Exception as e_mod:
            logger.warning(
                f"[order_lifecycle] Failed to ratchet SL for {clean_sym} ({d['order_id']}): {e_mod}"
            )

    return modified


def set_ledger_cash_baseline(account_id: str, opening_cash: float, *, actor: str = "USER") -> None:
    """Explicitly establish a cash baseline for honest broker reconciliation.

    This is deliberately never inferred from a live broker balance: using that
    balance as the internal ledger would recreate the self-comparison bug.
    """
    if not account_id or not account_id.strip():
        raise ValueError("account_id is required for a reconciliation baseline")
    if (
        not isinstance(opening_cash, (int, float))
        or not math.isfinite(opening_cash)
        or opening_cash < 0
    ):
        raise ValueError("opening_cash must be a finite non-negative amount")
    _init_orders_db()
    with _get_orders_db() as conn:
        conn.execute(
            """
            INSERT INTO ledger_cash_baselines(account_id, opening_cash, established_at, established_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                opening_cash = excluded.opening_cash,
                established_at = excluded.established_at,
                established_by = excluded.established_by
            """,
            (
                account_id.strip(),
                float(opening_cash),
                datetime.now(timezone.utc).isoformat(),
                actor,
            ),
        )
        conn.commit()


def record_execution_fill(
    account_id: str,
    broker_name: str,
    order_id: str,
    broker_order_id: str,
    broker_trade_id: str,
    symbol: str,
    exchange: str,
    segment: str,
    side: str,
    quantity: int | float,
    fill_price: float,
    fill_time: Optional[str] = None,
    charges: float = 0.0,
    product: str = "MIS",
) -> dict[str, Any]:
    """Record an immutable execution fill for honest account-scoped reconciliation.

    Guarantees:
    - Rejects invalid/nonfinite prices, negative/fractional quantities, empty identities, or placeholder LIVE_ACCOUNT.
    - Idempotent retry on identical execution facts.
    - Authorized fee adjustment when identical facts have updated charges.
    - Fails visibly on conflicting duplicate retries for the same broker_trade_id.
    - Serialized atomic sequence allocation per account using explicit BEGIN IMMEDIATE transaction.
    """
    if not account_id or not account_id.strip():
        raise ValueError("account_id is required")
    clean_account = account_id.strip()
    if clean_account.upper() == "LIVE_ACCOUNT":
        raise ValueError("account_id cannot be generic placeholder 'LIVE_ACCOUNT'")
    if not broker_trade_id or not broker_trade_id.strip():
        raise ValueError("broker_trade_id is required")
    if not broker_name or not broker_name.strip():
        raise ValueError("broker_name is required")
    if not broker_order_id or not broker_order_id.strip():
        raise ValueError("broker_order_id is required")
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    if not exchange or not exchange.strip():
        raise ValueError("exchange is required")
    if not segment or not segment.strip():
        raise ValueError("segment is required")

    # Strict numeric validation
    if not isinstance(quantity, (int, float)) or not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("quantity must be a finite positive number")
    if not float(quantity).is_integer():
        raise ValueError("quantity must be an integer, fractional shares are unsupported")
    int_qty = int(quantity)

    if not isinstance(fill_price, (int, float)) or not math.isfinite(fill_price) or fill_price <= 0:
        raise ValueError("fill_price must be a finite positive price")

    if not isinstance(charges, (int, float)) or not math.isfinite(charges) or charges < 0:
        raise ValueError("charges must be a finite non-negative amount")

    clean_broker = broker_name.strip().upper()
    clean_side = side.upper().strip()
    if clean_side not in ("BUY", "SELL"):
        raise ValueError(f"Invalid side: {side}")

    clean_symbol = symbol.upper().strip()
    clean_exchange = exchange.upper().strip()
    clean_segment = segment.upper().strip()
    clean_product = product.upper().strip() if product else "MIS"

    now_iso = datetime.now(timezone.utc).isoformat()
    if fill_time:
        try:
            # Enforce timezone-aware ISO timestamp
            dt = datetime.fromisoformat(str(fill_time).replace("Z", "+00:00"))
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                raise ValueError("fill_time must be timezone-aware (ISO8601 with timezone offset)")
            fill_time_str = dt.isoformat()
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Invalid fill_time format: {fill_time}") from e
    else:
        fill_time_str = now_iso

    fill_id = f"fill-{clean_broker}-{clean_account}-{broker_trade_id.strip()}"

    _init_orders_db()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                """
                SELECT fill_id, account_id, broker_name, exchange, segment, product,
                       symbol, side, quantity, fill_price, fill_time, broker_order_id,
                       charges, sequence_num
                FROM execution_fills
                WHERE account_id = ? AND broker_name = ? AND broker_trade_id = ?
                """,
                (clean_account, clean_broker, broker_trade_id.strip()),
            ).fetchone()

            if existing:
                ex_sym = existing["symbol"]
                ex_broker = existing["broker_name"]
                ex_exchange = existing["exchange"]
                ex_segment = existing["segment"]
                ex_product = existing["product"]
                ex_side = existing["side"]
                ex_qty = int(existing["quantity"])
                ex_price = float(existing["fill_price"])
                ex_b_order = existing["broker_order_id"]
                ex_charges = float(existing["charges"] or 0.0)
                ex_time = existing["fill_time"]

                # Timestamp comparison: parse both as timezone-aware
                time_matches = False
                try:
                    t1 = datetime.fromisoformat(str(ex_time).replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(str(fill_time_str).replace("Z", "+00:00"))
                    time_matches = abs((t1 - t2).total_seconds()) < 1.0
                except Exception:
                    time_matches = ex_time == fill_time_str

                immutable_facts_match = (
                    ex_sym == clean_symbol
                    and ex_broker == clean_broker
                    and ex_exchange == clean_exchange
                    and ex_segment == clean_segment
                    and ex_product == clean_product
                    and ex_side == clean_side
                    and ex_qty == int_qty
                    and abs(ex_price - float(fill_price)) < 1e-6
                    and ex_b_order == broker_order_id
                    and time_matches
                )

                if immutable_facts_match:
                    # Fee adjustment check
                    if abs(ex_charges - float(charges)) > 1e-4:
                        logger.info(
                            f"[order_lifecycle] Authorized fee adjustment for {broker_trade_id}: "
                            f"charges updated from {ex_charges} to {charges}"
                        )
                        conn.execute(
                            "UPDATE execution_fills SET charges = ?, updated_at = ? WHERE fill_id = ?",
                            (
                                float(charges),
                                datetime.now(timezone.utc).isoformat(),
                                existing["fill_id"],
                            ),
                        )
                        conn.execute("COMMIT")
                        return {
                            "fill_id": existing["fill_id"],
                            "account_id": clean_account,
                            "broker_trade_id": broker_trade_id.strip(),
                            "sequence_num": int(existing["sequence_num"]),
                            "symbol": ex_sym,
                            "side": ex_side,
                            "quantity": ex_qty,
                            "fill_price": ex_price,
                            "fill_time": fill_time_str,
                            "charges": float(charges),
                            "is_idempotent_retry": True,
                            "is_fee_adjustment": True,
                        }

                    conn.execute("COMMIT")
                    return {
                        "fill_id": existing["fill_id"],
                        "account_id": clean_account,
                        "broker_trade_id": broker_trade_id.strip(),
                        "sequence_num": int(existing["sequence_num"]),
                        "symbol": ex_sym,
                        "side": ex_side,
                        "quantity": ex_qty,
                        "fill_price": ex_price,
                        "fill_time": fill_time_str,
                        "charges": ex_charges,
                        "is_idempotent_retry": True,
                        "is_fee_adjustment": False,
                    }
                else:
                    conn.execute("ROLLBACK")
                    raise ValueError(
                        f"Conflicting duplicate broker execution retry for {broker_trade_id.strip()}: "
                        f"existing execution facts ({ex_sym} {ex_side} {ex_qty} @ {ex_price}) "
                        f"differ from incoming fill ({clean_symbol} {clean_side} {int_qty} @ {fill_price})"
                    )

            seq_row = conn.execute(
                "SELECT COALESCE(MAX(sequence_num), 0) + 1 FROM execution_fills WHERE account_id = ?",
                (clean_account,),
            ).fetchone()
            sequence_num = int(seq_row[0]) if seq_row else 1

            conn.execute(
                """
                INSERT INTO execution_fills (
                    fill_id, account_id, broker_name, order_id, broker_order_id,
                    broker_trade_id, symbol, exchange, segment, product, side, quantity,
                    fill_price, fill_time, charges, sequence_num, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_id,
                    clean_account,
                    clean_broker,
                    order_id,
                    broker_order_id,
                    broker_trade_id.strip(),
                    clean_symbol,
                    clean_exchange,
                    clean_segment,
                    clean_product,
                    clean_side,
                    int_qty,
                    float(fill_price),
                    fill_time_str,
                    float(charges),
                    sequence_num,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception as e_rb:
                logger.debug(f"[order_lifecycle] Rollback exception suppressed: {e_rb}")
            raise

    return {
        "fill_id": fill_id,
        "account_id": clean_account,
        "broker_trade_id": broker_trade_id.strip(),
        "sequence_num": sequence_num,
        "symbol": clean_symbol,
        "side": clean_side,
        "quantity": int_qty,
        "fill_price": float(fill_price),
        "fill_time": fill_time_str,
        "charges": float(charges),
        "is_idempotent_retry": False,
        "is_fee_adjustment": False,
    }


def ingest_broker_executions(
    order_id: str,
    broker_order_id: str,
    live_broker: Any,
    broker_res: Optional[Any] = None,
    order_details: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Ingest authentic broker execution trade records into execution_fills.

    Sanctity Invariants:
    1. Rejects fabricated trade IDs (such as TRD-{broker_order_id}).
    2. Rejects placeholder accounts (such as LIVE_ACCOUNT).
    3. Rejects preview/requested prices or quantities as fill facts.
    4. Partial fills are recorded with their distinct authentic trade IDs, quantities, and prices.
    5. Ingestion failures or charges calculation failures raise visibly to propagate to status.
    """
    _init_orders_db()
    d = dict(order_details) if order_details else {}
    if not d:
        with _get_orders_db() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders_ledger WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row:
                d = dict(row)

    account_id = d.get("account_id")
    if not account_id:
        account_id = getattr(live_broker, "account_id", None) or getattr(
            live_broker, "client_id", None
        )
        if not account_id and hasattr(live_broker, "get_profile"):
            try:
                prof = live_broker.get_profile()
                account_id = getattr(prof, "client_id", None)
            except Exception as e_prof:
                logger.debug(
                    f"[order_lifecycle] Failed resolving broker profile for account_id: {e_prof}"
                )

    if (
        not account_id
        or not str(account_id).strip()
        or str(account_id).strip().upper() == "LIVE_ACCOUNT"
    ):
        logger.warning(
            f"[order_lifecycle] Authentic account_id missing or generic placeholder for order {order_id}. "
            "Execution fill cannot enter institutional ledger."
        )
        return []

    clean_account = str(account_id).strip()
    provider = (
        str(
            d.get("broker")
            or (
                live_broker.__class__.__name__.replace("Broker", "").upper()
                if live_broker
                else "LIVE"
            )
        )
        .upper()
        .strip()
    )

    trade_items: list[dict[str, Any]] = []

    # 1. From broker_res object or raw payload
    if broker_res is not None:
        if getattr(broker_res, "trades", None) and isinstance(broker_res.trades, list):
            trade_items.extend(broker_res.trades)
        elif getattr(broker_res, "executions", None) and isinstance(broker_res.executions, list):
            trade_items.extend(broker_res.executions)
        elif getattr(broker_res, "raw", None) and isinstance(broker_res.raw, dict):
            raw_t = (
                broker_res.raw.get("trades")
                or broker_res.raw.get("tradeBook")
                or broker_res.raw.get("executions")
            )
            if isinstance(raw_t, list):
                trade_items.extend(raw_t)

        # Single trade on broker_res with authentic attributes
        if not trade_items:
            t_id = getattr(broker_res, "trade_id", None)
            avg_p = getattr(broker_res, "average_price", None)
            fq = getattr(broker_res, "filled_quantity", None)
            if t_id and avg_p is not None and avg_p > 0 and fq is not None and fq > 0:
                trade_items.append(
                    {
                        "trade_id": str(t_id),
                        "price": float(avg_p),
                        "quantity": int(fq),
                        "fill_time": getattr(broker_res, "fill_time", None)
                        or datetime.now(timezone.utc).isoformat(),
                    }
                )

    # 2. From live broker API methods
    if not trade_items and live_broker is not None:
        if hasattr(live_broker, "get_trades"):
            try:
                res_trades = live_broker.get_trades(broker_order_id)
                if isinstance(res_trades, list):
                    trade_items.extend(res_trades)
            except Exception as e_gt:
                logger.debug(f"[order_lifecycle] live_broker.get_trades error: {e_gt}")
        elif hasattr(live_broker, "get_trade_history"):
            try:
                all_trades = live_broker.get_trade_history()
                if isinstance(all_trades, list):
                    for tr in all_trades:
                        b_ord = (
                            tr.get("orderNumber")
                            or tr.get("order_id")
                            or tr.get("ordId")
                            or tr.get("order_number")
                        )
                        if str(b_ord) == str(broker_order_id):
                            trade_items.append(tr)
            except Exception as e_th:
                logger.debug(f"[order_lifecycle] live_broker.get_trade_history error: {e_th}")

    if not trade_items:
        # Authentic trade facts pending
        return []

    recorded_fills: list[dict[str, Any]] = []
    prod = str(d.get("product") or "MIS").upper()
    resolved_seg = str(
        d.get("segment") or ("EQUITY_DELIVERY" if prod == "CNC" else "EQUITY_INTRADAY")
    ).upper()

    try:
        for item in trade_items:
            raw_trade_id = (
                item.get("trade_id")
                or item.get("tradeNumber")
                or item.get("id")
                or item.get("trade_no")
            )
            if (
                not raw_trade_id
                or str(raw_trade_id).strip() == ""
                or str(raw_trade_id).startswith("TRD-")
            ):
                raise ValueError(
                    f"Authentic broker trade ID is required; found invalid '{raw_trade_id}'"
                )

            clean_trade_id = str(raw_trade_id).strip()
            raw_price = (
                item.get("price")
                or item.get("tradedPrice")
                or item.get("fill_price")
                or item.get("trade_price")
            )
            if raw_price is None or float(raw_price) <= 0:
                raise ValueError(f"Authentic execution price is required; found '{raw_price}'")
            f_price = float(raw_price)

            raw_qty = (
                item.get("quantity")
                or item.get("tradedQty")
                or item.get("qty")
                or item.get("fill_qty")
            )
            if raw_qty is None or int(raw_qty) <= 0:
                raise ValueError(f"Authentic execution quantity is required; found '{raw_qty}'")
            f_qty = int(raw_qty)

            raw_time = (
                item.get("fill_time")
                or item.get("orderDateTime")
                or item.get("trade_time")
                or datetime.now(timezone.utc).isoformat()
            )
            t_str = str(raw_time)
            if "Z" not in t_str and "+" not in t_str and "-" not in t_str[10:]:
                t_str = f"{t_str}+00:00"

            # Calculate charges
            chg_breakdown = calculate_transaction_charges(
                price=f_price,
                quantity=f_qty,
                segment=resolved_seg,  # type: ignore
                side=d["side"],  # type: ignore
            )
            total_chg = float(chg_breakdown.total_charges)

            res_fill = record_execution_fill(
                account_id=clean_account,
                broker_name=provider,
                order_id=order_id,
                broker_order_id=broker_order_id,
                broker_trade_id=clean_trade_id,
                symbol=d["symbol"],
                exchange=d.get("exchange", "NSE"),
                segment=resolved_seg,
                side=d["side"],
                quantity=f_qty,
                fill_price=f_price,
                fill_time=t_str,
                charges=total_chg,
                product=prod,
            )
            recorded_fills.append(res_fill)

        with _get_orders_db() as conn:
            conn.execute(
                "UPDATE orders_ledger SET ledger_status = 'RECORDED', ledger_error = NULL, updated_at = ? WHERE order_id = ?",
                (datetime.now(timezone.utc).isoformat(), order_id),
            )
            conn.commit()
    except Exception as e_ingest:
        logger.error(f"[order_lifecycle] Ingestion failure for order {order_id}: {e_ingest}")
        with _get_orders_db() as conn:
            conn.execute(
                "UPDATE orders_ledger SET ledger_status = 'INGESTION_FAILED', ledger_error = ?, updated_at = ? WHERE order_id = ?",
                (str(e_ingest), datetime.now(timezone.utc).isoformat(), order_id),
            )
            conn.commit()
        raise

    return recorded_fills


def get_internal_ledger_snapshot(account_id: str) -> Optional[dict[str, Any]]:
    """Return calculated internal ledger snapshot from persisted fills and cash baseline.

    Uses weighted-average inventory accounting across partial closes, increases, full closes,
    crossing through zero, and reopening. Keyed by (broker, exchange, symbol, product).
    If cash baseline is missing or unsupported segment detected, fails honestly.
    """
    if not account_id or not account_id.strip():
        return None

    clean_account = account_id.strip()
    _init_orders_db()
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        baseline = conn.execute(
            """
            SELECT opening_cash, established_at, established_by
            FROM ledger_cash_baselines
            WHERE account_id = ?
            """,
            (clean_account,),
        ).fetchone()
        if not baseline:
            logger.warning(
                "[engine.order_lifecycle] Internal reconciliation unavailable for %s: "
                "no cash baseline established",
                clean_account,
            )
            return None

        opening_cash = float(baseline["opening_cash"])
        fills = conn.execute(
            """
            SELECT fill_id, broker_name, exchange, segment, product, symbol, side,
                   quantity, fill_price, fill_time, charges, sequence_num
            FROM execution_fills
            WHERE account_id = ?
            ORDER BY sequence_num ASC, fill_time ASC
            """,
            (clean_account,),
        ).fetchall()

        if not fills:
            return {
                "status": "AVAILABLE",
                "account_id": clean_account,
                "opening_cash": opening_cash,
                "cash_balance": opening_cash,
                "cash": opening_cash,
                "total_realized_pnl": 0.0,
                "total_charges": 0.0,
                "positions": [],
                "total_fills_count": 0,
                "data_quality_status": "AVAILABLE",
                "is_complete": False,
                "incompleteness_reason": "Baseline established but zero broker fills have been imported into internal ledger",
                "as_of": datetime.now(timezone.utc).isoformat(),
            }

        # Check unsupported segments (e.g. Futures MTM without daily mark ledger)
        unsupported_segments = {"FUTURES", "NFO_FUT", "MCX_FUT", "COMMODITY_FUT"}
        for f in fills:
            seg = str(f["segment"] or "").upper().strip()
            if seg in unsupported_segments:
                logger.error(
                    f"[engine.order_lifecycle] Unsupported segment {seg} for {f['symbol']}: "
                    f"Futures MTM/margin accounting cannot be modeled as cash-settled equity/options ledger"
                )
                return {
                    "status": "UNAVAILABLE",
                    "account_id": clean_account,
                    "rejection_reason": f"Unsupported segment {seg}: Futures MTM/margin accounting is not supported in cash-settled ledger",
                    "as_of": datetime.now(timezone.utc).isoformat(),
                }

        # Position tracking keyed by (broker_name, exchange, symbol, product)
        positions: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        cash_balance = opening_cash

        for f in fills:
            b_name = str(f["broker_name"] or "UNKNOWN").upper().strip()
            ex = str(f["exchange"] or "NSE").upper().strip()
            sym = str(f["symbol"]).upper().strip()
            prod = str(f["product"] or "MIS").upper().strip()
            seg = str(f["segment"] or "EQUITY").upper().strip()
            key = (b_name, ex, sym, prod)

            qty = int(f["quantity"])
            price = float(f["fill_price"])
            charges = float(f["charges"] or 0.0)
            side = str(f["side"]).upper().strip()

            if key not in positions:
                positions[key] = {
                    "broker_name": b_name,
                    "exchange": ex,
                    "symbol": sym,
                    "product": prod,
                    "segment": seg,
                    "quantity": 0,
                    "average_cost_basis": 0.0,
                    "realized_pnl": 0.0,
                    "total_charges": 0.0,
                }

            pos = positions[key]
            pos["total_charges"] += charges

            if side == "BUY":
                cash_balance -= price * qty + charges
                cur_qty = pos["quantity"]
                if cur_qty >= 0:
                    # Increasing LONG or opening new LONG
                    new_qty = cur_qty + qty
                    pos["average_cost_basis"] = (
                        cur_qty * pos["average_cost_basis"] + qty * price
                    ) / new_qty
                    pos["quantity"] = new_qty
                else:
                    # Covering existing SHORT
                    cur_short = abs(cur_qty)
                    if qty <= cur_short:
                        # Partial or exact full cover: average cost basis is unchanged
                        closed_qty = qty
                        pnl = closed_qty * (pos["average_cost_basis"] - price)
                        pos["realized_pnl"] += pnl
                        pos["quantity"] += qty
                        if pos["quantity"] == 0:
                            pos["average_cost_basis"] = 0.0
                    else:
                        # Crossed through zero from SHORT to LONG
                        closed_qty = cur_short
                        pnl = closed_qty * (pos["average_cost_basis"] - price)
                        pos["realized_pnl"] += pnl
                        rem_long = qty - cur_short
                        pos["quantity"] = rem_long
                        pos["average_cost_basis"] = price

            else:  # SELL
                cash_balance += price * qty - charges
                cur_qty = pos["quantity"]
                if cur_qty <= 0:
                    # Increasing SHORT or opening new SHORT
                    cur_short = abs(cur_qty)
                    new_short = cur_short + qty
                    pos["average_cost_basis"] = (
                        cur_short * pos["average_cost_basis"] + qty * price
                    ) / new_short
                    pos["quantity"] = -new_short
                else:
                    # Closing existing LONG
                    cur_long = cur_qty
                    if qty <= cur_long:
                        # Partial or exact full close: average cost basis is unchanged
                        closed_qty = qty
                        pnl = closed_qty * (price - pos["average_cost_basis"])
                        pos["realized_pnl"] += pnl
                        pos["quantity"] -= qty
                        if pos["quantity"] == 0:
                            pos["average_cost_basis"] = 0.0
                    else:
                        # Crossed through zero from LONG to SHORT
                        closed_qty = cur_long
                        pnl = closed_qty * (price - pos["average_cost_basis"])
                        pos["realized_pnl"] += pnl
                        rem_short = qty - cur_long
                        pos["quantity"] = -rem_short
                        pos["average_cost_basis"] = price

        open_positions = []
        total_realized_pnl = sum(p["realized_pnl"] for p in positions.values())
        total_charges = sum(p["total_charges"] for p in positions.values())

        for p in positions.values():
            if p["quantity"] != 0:
                open_positions.append(
                    {
                        "broker_name": p["broker_name"],
                        "exchange": p["exchange"],
                        "symbol": p["symbol"],
                        "product": p["product"],
                        "segment": p["segment"],
                        "quantity": p["quantity"],
                        "side": "LONG" if p["quantity"] > 0 else "SHORT",
                        "average_cost_basis": round(p["average_cost_basis"], 2),
                        "average_price": round(p["average_cost_basis"], 2),
                        "realized_pnl": round(p["realized_pnl"], 2),
                    }
                )

        # Data quality status: check if any order for this account suffered ingestion failure
        data_qual = "AVAILABLE"
        failed_row = conn.execute(
            "SELECT 1 FROM orders_ledger WHERE account_id = ? AND ledger_status = 'INGESTION_FAILED' LIMIT 1",
            (clean_account,),
        ).fetchone()
        if failed_row:
            data_qual = "DEGRADED"

        return {
            "status": "AVAILABLE",
            "account_id": clean_account,
            "opening_cash": opening_cash,
            "cash_balance": round(cash_balance, 2),
            "cash": round(cash_balance, 2),
            "total_realized_pnl": round(total_realized_pnl, 2),
            "total_charges": round(total_charges, 2),
            "positions": open_positions,
            "total_fills_count": len(fills),
            "data_quality_status": data_qual,
            "is_complete": True,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }


def sync_execution_orders() -> dict[str, Any]:
    """Poll the selected execution broker and reconcile known order states.

    It only updates rows that already carry a broker order ID.  Unknown broker
    orders are recorded as audit evidence rather than silently imported.
    """
    from brokers.session import get_execution_broker, get_execution_broker_key

    _init_orders_db()
    broker = get_execution_broker()
    provider = get_execution_broker_key() or broker.__class__.__name__.lower()
    broker_orders = broker.get_orders()
    by_id = {
        str(order.order_id): order for order in broker_orders if getattr(order, "order_id", None)
    }
    changed = 0
    unknown_broker_orders = 0
    status_map = {
        "COMPLETE": "FILLED",
        "FILLED": "FILLED",
        "TRADED": "FILLED",
        "OPEN": "OPEN",
        "PENDING": "OPEN",
        "TRANSIT": "OPEN",
        "PARTIAL": "PARTIALLY_FILLED",
        "PARTIALLY_FILLED": "PARTIALLY_FILLED",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED",
        "REJECTED": "REJECTED",
        "EXPIRED": "EXPIRED",
        "1": "CANCELLED",
        "2": "FILLED",
        "4": "OPEN",
        "5": "REJECTED",
        "6": "OPEN",
        "7": "EXPIRED",
    }
    events_to_record: list[tuple[str, str, int]] = []
    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        known_rows = conn.execute(
            "SELECT * FROM orders_ledger WHERE broker_order_id IS NOT NULL"
        ).fetchall()
        known_ids = {str(row["broker_order_id"]) for row in known_rows}
        parent_ids_to_sync: set[str] = set()
        for row in known_rows:
            if row["parent_order_id"]:
                parent_ids_to_sync.add(str(row["parent_order_id"]))
            broker_order = by_id.get(str(row["broker_order_id"]))
            if not broker_order:
                continue
            new_status = status_map.get(str(getattr(broker_order, "status", "")).upper())
            b_filled_qty = int(getattr(broker_order, "filled_quantity", 0) or 0)
            b_avg_price = float(getattr(broker_order, "average_price", 0.0) or 0.0)
            now_sync_iso = datetime.now(timezone.utc).isoformat()

            # Ingest executions if fills occurred
            if new_status in ("FILLED", "PARTIALLY_FILLED") or b_filled_qty > 0:
                try:
                    ingest_broker_executions(
                        order_id=str(row["order_id"]),
                        broker_order_id=str(row["broker_order_id"]),
                        live_broker=broker,
                        broker_res=broker_order,
                        order_details=dict(row),
                    )
                except Exception as e_sync_ingest:
                    logger.error(
                        f"[order_lifecycle] sync execution ingestion failed for {row['order_id']}: {e_sync_ingest}"
                    )

            if new_status and new_status != row["status"]:
                conn.execute(
                    """
                    UPDATE orders_ledger
                    SET status = ?, filled_quantity = ?, average_fill_price = ?, last_sync_at = ?, updated_at = ?
                    WHERE order_id = ?
                    """,
                    (
                        new_status,
                        b_filled_qty,
                        b_avg_price if b_avg_price > 0 else None,
                        now_sync_iso,
                        now_sync_iso,
                        row["order_id"],
                    ),
                )
                if new_status in ("CANCELLED", "REJECTED", "EXPIRED"):
                    try:
                        from market.fyers_tbt_manager import FyersTbtManager

                        sym = str(row["symbol"]) if "symbol" in row.keys() else None
                        if sym:
                            FyersTbtManager().unregister_in_flight(sym)
                    except Exception as e_suppressed:
                        logger.debug(
                            f"[engine.order_lifecycle] Non-fatal exception suppressed: {e_suppressed}"
                        )

                events_to_record.append(
                    (
                        str(row["order_id"]),
                        new_status,
                        int(getattr(broker_order, "filled_quantity", 0) or 0),
                    )
                )
                changed += 1
        for pid in parent_ids_to_sync:
            _reconcile_parent_order_in_conn(conn, pid, now_sync_iso)
        unknown_broker_orders = len(set(by_id).difference(known_ids))
        conn.commit()
    for local_order_id, new_status, filled_quantity in events_to_record:
        _record_order_event(
            local_order_id,
            "BROKER_ORDER_SYNC",
            broker_name=provider,
            broker_order_id=next(
                (
                    str(row["broker_order_id"])
                    for row in known_rows
                    if str(row["order_id"]) == local_order_id
                ),
                None,
            ),
            payload={"status": new_status, "filled_quantity": filled_quantity},
        )
    return {
        "provider": provider,
        "broker_orders_seen": len(by_id),
        "ledger_orders_updated": changed,
        "unknown_broker_orders": unknown_broker_orders,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def execute_wing_lock_hedge(
    alert_id: str,
    limit_price: Optional[float] = None,
    quantity: Optional[int] = None,
    actor: str = "LOCAL",
) -> dict[str, Any]:
    """
    1-Click Fyers / Paper Multi-Leg Execution Bridge for Free-Roll Wing Lock.

    Transitions a +48% / T1 in-profit naked option setup into an institutional
    Free-Roll Spread by shorting the OTM wing candidate, locking guaranteed profit
    while retaining zero downside risk.
    """
    from engine.auto_alert_engine import get_auto_alert_engine
    from engine.security_audit import record_audit_event

    a_engine = get_auto_alert_engine()
    alert = (
        a_engine.get_alert_by_id(alert_id)
        if hasattr(a_engine, "get_alert_by_id")
        else a_engine.get_alert(alert_id)
    )
    if not alert:
        raise ValueError(f"Alert '{alert_id}' not found.")

    plan = alert.actionable_plan or {}
    hedge_ticket = plan.get("hedge_ticket")
    free_roll = plan.get("free_roll_plan") or (
        alert.metrics.get("free_roll_conversion") if alert.metrics else None
    )

    if not hedge_ticket and not free_roll:
        raise ValueError(f"Alert '{alert_id}' has no eligible Free-Roll hedge ticket or plan.")

    # Resolve hedge contract symbol
    sym = hedge_ticket.get("symbol") if hedge_ticket else None
    if not sym and free_roll:
        u_sym = alert.symbol
        c_strike = free_roll.get("short_strike_candidate", 0)
        c_opt = free_roll.get("option_type", "")
        sym = f"{u_sym}{c_strike:,.0f}{c_opt}".replace(",", "")

    if not sym:
        raise ValueError(f"Could not determine hedge contract symbol for alert '{alert_id}'.")

    # Resolve quantity & price
    qty = int(
        quantity
        or (hedge_ticket.get("shares") if hedge_ticket else None)
        or getattr(alert, "shares", 0)
        or getattr(alert, "lot_size", 1)
    )
    side = str(hedge_ticket.get("action", "SELL") if hedge_ticket else "SELL").upper()
    cand_px = (
        limit_price
        or (hedge_ticket.get("limit_price") if hedge_ticket else None)
        or (free_roll.get("estimated_credit_collected") if free_roll else None)
    )
    if cand_px is None or float(cand_px) <= 0.0:
        raise ValueError(
            f"Free-roll wing lock requires an authentic limit price or verified ticket credit for '{alert_id}' (cannot invent price)."
        )
    px = round(float(cand_px), 2)
    order_type = str(hedge_ticket.get("order_type", "LIMIT") if hedge_ticket else "LIMIT")

    # Step 1: Preview Order Intent
    preview = preview_order_intent(
        symbol=sym,
        side=side,  # type: ignore
        quantity=qty,
        price=px,
        order_type=order_type,  # type: ignore
        product="MIS",
    )

    # Step 2: Confirm Order Intent
    confirmed = confirm_order_intent(preview.order_id, preview.preview_hash)

    # Step 3: Execute Order Intent
    executed = execute_order_intent(confirmed.order_id)

    # Step 4: Update Alert State & Audit Trail ONLY if filled
    is_filled = executed.status in ("FILLED", "FILLED_PAPER")
    if not alert.metrics:
        alert.metrics = {}
    alert.metrics["free_roll_locked"] = is_filled

    if not alert.actionable_plan:
        alert.actionable_plan = {}
    alert.actionable_plan["free_roll_active"] = is_filled
    if not is_filled:
        alert.actionable_plan["free_roll_pending_order_id"] = executed.order_id
    alert.actionable_plan["wing_lock_executed"] = True
    alert.actionable_plan["wing_lock_order_id"] = executed.order_id
    alert.actionable_plan["wing_lock_fill_price"] = executed.price or px
    alert.actionable_plan["wing_lock_status"] = executed.status

    locked_pts = float(
        getattr(alert, "locked_profit_pts", 0.0)
        or (free_roll.get("net_locked_profit_pts", 0.0) if free_roll else 0.0)
    )
    action_msg = (
        f"Wing Lock Executed: Sold {sym} qty={qty} @ ₹{px:.1f} "
        f"(Order: {executed.order_id}) locking ₹{locked_pts:.1f} profit."
    )

    if hasattr(alert, "record_audit"):
        alert.record_audit(
            event_type="WING_LOCK_EXECUTED",
            message=action_msg,
            actor=actor,
        )

    # Persist updated alert in AutoAlertEngine
    a_engine.record_alert(alert)

    # Record Security Audit
    record_audit_event(
        event_type="WING_LOCK_HEDGE_EXECUTED",
        mode=executed.mode,
        actor=actor,
        details={
            "alert_id": alert_id,
            "order_id": executed.order_id,
            "symbol": sym,
            "quantity": qty,
            "price": px,
            "status": executed.status,
            "locked_profit_pts": locked_pts,
        },
    )

    return {
        "status": "SUCCESS",
        "alert_id": alert_id,
        "order": executed.to_dict(),
        "hedge_symbol": sym,
        "locked_profit_pts": locked_pts,
        "message": action_msg,
    }


def emergency_flatten_all_positions(
    actor: str = "LOCAL",
    reason: str = "MANUAL_EMERGENCY",
    segment: Optional[str] = None,
) -> dict[str, Any]:
    """
    1-Click Emergency "Flatten All" Command & Session Drawdown Circuit Breaker.

    Institutional Fail-Closed Execution Sequence:
      1. Order Annihilation:
         - Retrieves and cancels all open/pending resting orders on the broker and ledger
           to eliminate any pending order fills during position liquidation.
      2. Position Liquidation:
         - Live Mode (TRADING_MODE=EXECUTE and ALLOW_LIVE_TRADING=1):
           Invokes broker exit_all_positions(segment=segment) or dispatches market counter-orders.
         - Paper / Simulate Mode:
           Squares off all open positions via PaperBroker.square_off_intraday_positions() / market exits.
      3. 60-Minute Circuit Breaker Lock:
         - Sets active emergency cooldown lock preventing new trade entry for 60 minutes.
      4. Institutional Security Audit Ledger:
         - Records EMERGENCY_FLATTEN_ALL audit event with full provenance and correlation ID.
    """
    from brokers.session import get_execution_broker
    from engine.modes import get_trading_mode
    from engine.security_audit import record_audit_event

    mode = get_trading_mode().mode.name  # "OBSERVE", "SIMULATE", "EXECUTE"
    cancelled_orders: list[str] = []
    flattened_positions: list[dict[str, Any]] = []

    if mode == "OBSERVE":
        raise PermissionError("Emergency financial mutations are unavailable in OBSERVE mode")
    if mode == "EXECUTE":
        from engine.modes import assert_live_execution_allowed

        assert_live_execution_allowed()
    set_emergency_lockout(3600.0)
    broker = None
    positions_verified = True
    try:
        if mode == "SIMULATE":
            from engine.paper import PaperBroker

            broker = PaperBroker()
        else:
            from brokers.session import get_execution_broker

            broker = get_execution_broker()
    except Exception as e_broker:
        logger.warning(
            f"[EmergencyFlatten] Execution broker unavailable or not logged in: {e_broker}"
        )
        positions_verified = False

    if mode == "EXECUTE" and not broker:
        lockout_until = set_emergency_lockout(3600.0)
        return {
            "status": "UNVERIFIED",
            "mode": mode,
            "cancelled_orders_count": 0,
            "cancelled_orders": [],
            "flattened_positions_count": 0,
            "flattened_positions": [],
            "positions_verified": False,
            "lockout_until": lockout_until,
            "message": "Emergency flatten failed: No authenticated execution broker session available. Positions unverified.",
        }

    # 1. Annihilate Open Resting Orders
    try:
        open_orders = broker.get_orders() if (broker and hasattr(broker, "get_orders")) else []
        for o in open_orders:
            from brokers.order_types import normalize_order_status

            status = getattr(o, "status", None) or (
                o.get("status") if isinstance(o, dict) else None
            )
            norm_st = normalize_order_status(status)
            oid = (
                getattr(o, "order_id", None)
                or (o.get("order_id") if isinstance(o, dict) else None)
                or getattr(o, "id", None)
            )
            if oid and norm_st in ("OPEN", "SUBMITTED"):
                try:
                    c_res = broker.cancel_order(str(oid))
                    if c_res is True:
                        cancelled_orders.append(str(oid))
                except Exception as e_cancel:
                    logger.warning(
                        f"[EmergencyFlatten] Failed to cancel broker order {oid}: {e_cancel}"
                    )
    except Exception as e_orders:
        logger.warning(f"[EmergencyFlatten] Failed to query broker orders: {e_orders}")
        positions_verified = False

    # 2. Liquidate Positions
    native_exit_requested = False
    if broker and hasattr(broker, "exit_all_positions"):
        try:
            res = broker.exit_all_positions(segment=segment)
            native_exit_requested = True
            flattened_positions.append(
                {"method": "native_exit_all_positions", "response": str(res)}
            )
        except Exception as e_exit_all:
            logger.warning(f"[EmergencyFlatten] native exit_all_positions failed: {e_exit_all}")

    # PaperBroker square-off (SIMULATE mode ONLY)
    if mode == "SIMULATE" and broker and hasattr(broker, "square_off_intraday_positions"):
        try:
            closed = broker.square_off_intraday_positions()
            for sym in closed:
                flattened_positions.append(
                    {"symbol": sym, "method": "square_off_intraday_positions", "simulated": True}
                )
        except Exception as e_sq:
            logger.warning(f"[EmergencyFlatten] square_off_intraday_positions failed: {e_sq}")

    # Check and close any remaining open net positions via market counter-orders
    try:
        pos_list = (
            broker.get_positions()
            if hasattr(broker, "get_positions") and not native_exit_requested
            else []
        )
        for p in pos_list:
            qty = (
                getattr(p, "net_qty", None)
                or (p.get("net_qty") if isinstance(p, dict) else None)
                or (p.get("qty") if isinstance(p, dict) else 0)
            )
            sym = getattr(p, "symbol", None) or (p.get("symbol") if isinstance(p, dict) else None)
            if sym and qty and int(qty) != 0:
                side = "SELL" if int(qty) > 0 else "BUY"
                try:
                    from brokers.base import OrderRequest

                    exch = (
                        getattr(p, "exchange", "NSE")
                        if hasattr(p, "exchange")
                        else (p.get("exchange", "NSE") if isinstance(p, dict) else "NSE")
                    )
                    prod = (
                        getattr(p, "product", "MIS")
                        if hasattr(p, "product")
                        else (p.get("product", "MIS") if isinstance(p, dict) else "MIS")
                    )
                    req = OrderRequest(
                        symbol=sym,
                        exchange=exch,
                        transaction_type=side,
                        quantity=abs(int(qty)),
                        order_type="MARKET",
                        product=prod,
                    )
                    response = broker.place_order(req)
                    if getattr(response, "status", "") not in ("COMPLETE", "FILLED"):
                        logger.warning(
                            "[EmergencyFlatten] Close unconfirmed for %s: %s",
                            sym,
                            getattr(response, "status", None),
                        )
                        continue
                    flattened_positions.append(
                        {
                            "symbol": sym,
                            "side": side,
                            "quantity": abs(int(qty)),
                            "method": "market_counter_order",
                        }
                    )
                except Exception as e_close:
                    logger.warning(f"[EmergencyFlatten] Counter-order failed for {sym}: {e_close}")
    except Exception as e_pos:
        logger.warning(f"[EmergencyFlatten] Position liquidation iteration failed: {e_pos}")
        positions_verified = False

    # 3. Activate 60-Minute Circuit Breaker Lockout
    lockout_until = set_emergency_lockout(3600.0)

    # 4. Security Audit Log
    record_audit_event(
        event_type="EMERGENCY_FLATTEN_ALL",
        mode=mode,
        actor=actor,
        details={
            "reason": reason,
            "cancelled_orders_count": len(cancelled_orders),
            "cancelled_orders": cancelled_orders,
            "flattened_positions_count": len(flattened_positions),
            "flattened_positions": flattened_positions,
            "lockout_until": lockout_until,
        },
    )

    msg = (
        f"Emergency reduction requested; reconcile broker positions: {len(cancelled_orders)} open orders cancelled, "
        f"{len(flattened_positions)} positions liquidated. 60-minute circuit breaker active."
    )
    return {
        "status": "PENDING_RECONCILIATION",
        "mode": mode,
        "cancelled_orders_count": len(cancelled_orders),
        "cancelled_orders": cancelled_orders,
        "flattened_positions_count": len(flattened_positions),
        "flattened_positions": flattened_positions,
        "positions_verified": positions_verified,
        "lockout_until": lockout_until,
        "message": msg,
    }
