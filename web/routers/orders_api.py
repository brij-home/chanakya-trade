"""
web/routers/orders_api.py
─────────────────────────
Modular router for order lifecycle (preview, confirm, execute, batch)
and honest ledger-broker reconciliation endpoints in ChanakyaTrade.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(tags=["Orders & Reconciliation"])


class OrderPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=64)
    side: str
    quantity: int = Field(ge=1)
    price: float = Field(gt=0)
    order_type: str = "LIMIT"
    product: str = "MIS"
    idempotency_key: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized

    @field_validator("side", "order_type", "product")
    @classmethod
    def normalize_order_choices(cls, value: str, info):
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string")
        normalized = value.strip().upper()
        allowed = {
            "side": {"BUY", "SELL"},
            "order_type": {"MARKET", "LIMIT", "SL_LIMIT", "SL_MARKET"},
            "product": {"CNC", "MIS", "NRML"},
        }[info.field_name]
        if normalized not in allowed:
            raise ValueError(f"Unsupported {info.field_name}: {value!r}")
        return normalized


class OrderExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str


class OrderConfirmRequest(OrderExecuteRequest):
    preview_hash: str


class OrderBatchExecuteRequest(BaseModel):
    order_ids: list[str]


class RiskPreflightRequest(BaseModel):
    symbol: str
    action: str = "BUY"
    quantity: int = 1
    price: float = 0.0
    current_position: Optional[dict] = None
    allow_override: bool = False


class ReconciliationBaselineRequest(BaseModel):
    """User-declared opening cash for the immutable local execution ledger."""

    opening_cash: float = Field(..., ge=0)


# ── Route Handlers ────────────────────────────────────────────────────────────


@router.post("/api/orders/preview")
async def api_order_preview(req: OrderPreviewRequest, request: Request):
    """Generate order preview with statutory Indian charges and idempotency key."""
    from engine.order_lifecycle import preview_order_intent
    from engine.security_audit import record_audit_event

    actor = "LOCAL"
    if hasattr(request.state, "user") and request.state.user:
        actor = request.state.user.get("username", request.state.user.get("user_id", "UNKNOWN"))

    try:
        order = await asyncio.to_thread(
            preview_order_intent,
            symbol=req.symbol,
            side=req.side,  # type: ignore
            quantity=req.quantity,
            price=req.price,
            order_type=req.order_type,  # type: ignore
            product=req.product,  # type: ignore
            idempotency_key=req.idempotency_key,
        )

        await asyncio.to_thread(
            record_audit_event,
            event_type="ORDER_PREVIEW_REQUESTED",
            mode=order.mode,
            actor=actor,
            details={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": order.quantity,
            },
        )
        return JSONResponse(order.to_dict())
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/orders/confirm")
async def api_order_confirm(req: OrderConfirmRequest, request: Request):
    """Record the user's final confirmation before an intent can execute."""
    from engine.order_lifecycle import confirm_order_intent
    from engine.security_audit import record_audit_event

    actor = "LOCAL"
    if hasattr(request.state, "user") and request.state.user:
        actor = request.state.user.get("username", request.state.user.get("user_id", "UNKNOWN"))

    try:
        order = await asyncio.to_thread(confirm_order_intent, req.order_id, req.preview_hash)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code, str(exc)) from exc

    await asyncio.to_thread(
        record_audit_event,
        event_type="ORDER_CONFIRMED_BY_USER",
        mode=order.mode,
        actor=actor,
        details={"order_id": order.order_id, "preview_hash": order.preview_hash},
    )
    return JSONResponse(order.to_dict())


@router.post("/api/orders/execute")
async def api_order_execute(req: OrderExecuteRequest, request: Request):
    """Execute order intent with mode gate and double-confirmation validation."""
    from engine.order_lifecycle import execute_order_intent
    from engine.security_audit import record_audit_event

    actor = "LOCAL"
    if hasattr(request.state, "user") and request.state.user:
        actor = request.state.user.get("username", request.state.user.get("user_id", "UNKNOWN"))

    try:
        order = await asyncio.to_thread(execute_order_intent, order_id=req.order_id)
        await asyncio.to_thread(
            record_audit_event,
            event_type="ORDER_EXECUTE_REQUESTED",
            mode=order.mode,
            actor=actor,
            details={
                "order_id": order.order_id,
                "status": order.status,
                "broker_order_id": order.broker_order_id,
            },
        )
        return JSONResponse(order.to_dict())
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code, str(exc)) from exc


@router.post("/api/orders/batch/execute")
async def api_order_batch_execute(req: OrderBatchExecuteRequest, request: Request):
    """Execute micro-batch of order intents atomically with mode gate and double-confirmation validation."""
    from engine.order_lifecycle import execute_order_batch
    from engine.security_audit import record_audit_event

    actor = "LOCAL"
    if hasattr(request.state, "user") and request.state.user:
        actor = request.state.user.get("username", request.state.user.get("user_id", "UNKNOWN"))

    try:
        orders = await asyncio.to_thread(execute_order_batch, order_ids=req.order_ids)
        for order in orders:
            await asyncio.to_thread(
                record_audit_event,
                event_type="ORDER_BATCH_EXECUTE_REQUESTED",
                mode=order.mode,
                actor=actor,
                details={
                    "order_id": order.order_id,
                    "status": order.status,
                    "broker_order_id": order.broker_order_id,
                },
            )
        return JSONResponse([o.to_dict() for o in orders])
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code, str(exc)) from exc


@router.post("/api/risk/preflight")
async def api_risk_preflight(req: RiskPreflightRequest):
    """Evaluate order against risk limits, returning structured behavioral guidance & double confirmation requirements."""
    from engine.risk_limits import risk_limits

    res = risk_limits.evaluate_preflight(
        symbol=req.symbol,
        action=req.action,
        quantity=max(1, req.quantity),
        price=max(0.0, req.price),
        current_position=req.current_position,
        allow_override=req.allow_override,
    )
    return JSONResponse(res.to_dict())


@router.get("/api/reconciliation")
async def api_reconciliation():
    """
    Ledger vs broker reconciliation.

    Requires a live, authenticated broker snapshot. If no broker session is
    available the endpoint returns status='UNAVAILABLE' — it does NOT compare
    the internal ledger against itself, which would always report a clean
    reconciliation and mask real discrepancies.
    """
    from engine.reconciliation import reconcile_ledger
    from engine.observability import new_correlation_id

    correlation_id = new_correlation_id("reconciliation")

    try:
        from brokers.session import get_execution_broker

        live_broker = get_execution_broker()
        if live_broker is None:
            raise RuntimeError("No authenticated broker session.")

        broker_positions_raw = await asyncio.to_thread(live_broker.get_positions)
        broker_funds_raw = await asyncio.to_thread(live_broker.get_funds)

        snapshot_at = datetime.now(timezone.utc).isoformat()
        broker_account_id = (
            getattr(live_broker, "account_id", None)
            or getattr(live_broker, "client_id", None)
            or "UNKNOWN"
        )

        def _pos_to_dict(p) -> dict:
            if isinstance(p, dict):
                return {
                    "symbol": p.get("symbol") or p.get("tradingsymbol", ""),
                    "qty": int(p.get("quantity", p.get("qty", 0))),
                    "avg_price": float(p.get("average_price", p.get("avg_price", 0.0))),
                }
            return {
                "symbol": getattr(p, "symbol", ""),
                "qty": int(getattr(p, "quantity", 0)),
                "avg_price": float(getattr(p, "avg_price", 0.0)),
            }

        def _funds_cash(f) -> float:
            if isinstance(f, dict):
                return float(f.get("available_cash", f.get("net", 0.0)))
            return float(getattr(f, "available_cash", 0.0))

        broker_positions = [_pos_to_dict(p) for p in (broker_positions_raw or [])]
        broker_cash = _funds_cash(broker_funds_raw)

    except Exception as broker_exc:
        return JSONResponse(
            {
                "status": "UNAVAILABLE",
                "reason": (
                    f"Reconciliation requires an authenticated broker snapshot. "
                    f"No broker session available: {broker_exc}"
                ),
                "broker_positions": None,
                "broker_cash": None,
                "internal_positions": None,
                "internal_cash": None,
                "broker_account_id": None,
                "broker_snapshot_at": None,
                "correlation_id": correlation_id,
            }
        )

    try:
        from engine.order_lifecycle import get_internal_ledger_snapshot, sync_execution_orders

        await asyncio.to_thread(sync_execution_orders)
        internal = await asyncio.to_thread(get_internal_ledger_snapshot, broker_account_id)
    except Exception as ledger_exc:
        internal = None
        ledger_reason = str(ledger_exc)
    else:
        ledger_reason = ""

    if internal is None:
        return JSONResponse(
            {
                "status": "UNAVAILABLE",
                "reason": (
                    "Reconciliation requires an explicit local opening-cash baseline and persisted "
                    f"execution ledger for account {broker_account_id}. {ledger_reason}"
                ).strip(),
                "broker_positions": broker_positions,
                "broker_cash": broker_cash,
                "internal_positions": None,
                "internal_cash": None,
                "broker_account_id": broker_account_id,
                "broker_snapshot_at": snapshot_at,
                "correlation_id": correlation_id,
            }
        )

    report = await asyncio.to_thread(
        reconcile_ledger,
        internal_positions=internal["positions"],
        broker_positions=broker_positions,
        internal_cash=float(internal["cash"]),
        broker_cash=broker_cash,
        broker_name=broker_account_id,
    )
    result = report.to_dict()
    result["broker_account_id"] = broker_account_id
    result["broker_snapshot_at"] = snapshot_at
    result["correlation_id"] = correlation_id
    return JSONResponse(result)


@router.post("/api/reconciliation/baseline")
async def api_reconciliation_baseline(req: ReconciliationBaselineRequest):
    """Establish or deliberately reset the local reconciliation baseline."""
    from brokers.session import get_execution_broker
    from engine.order_lifecycle import set_ledger_cash_baseline

    broker = get_execution_broker()
    account_id = getattr(broker, "account_id", None) or getattr(broker, "client_id", None)
    if not account_id:
        raise HTTPException(
            status_code=503, detail="An authenticated execution broker is required."
        )
    set_ledger_cash_baseline(str(account_id), req.opening_cash, actor="USER_API")
    return {
        "status": "ok",
        "account_id": str(account_id),
        "opening_cash": req.opening_cash,
        "message": "Independent ledger baseline saved. Run reconciliation to compare it with the broker.",
    }
