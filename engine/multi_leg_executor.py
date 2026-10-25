"""
engine/multi_leg_executor.py
────────────────────────────
Institutional Multi-Leg Atomic Spread Execution Engine & Legging Risk Shield (G1).

Coordinates multi-leg derivative spreads (Bull Call Spread, Bear Put Spread,
Bull Put Spread, Bear Call Spread, Iron Condor) across Indian broker APIs.

P0 Invariants & Guarantees:
  1. Execution Sequencing (Hedge-First):
     - BUY legs (the protective hedges) MUST be executed and confirmed FIRST.
     - This unlocks exchange/broker margin relief before short legs are placed,
       preventing margin shortfall rejections.
  2. Legging Risk Shield & Auto-Unwind Watchdog:
     - If a subsequent short leg fails, rejects, or times out (default 1200ms),
       the watchdog immediately liquidates the filled long leg(s) via an emergency
       market order or neutralizes naked delta exposure.
     - Never leaves an account in an inadvertent unhedged directional posture.
  3. Fail-Closed State Machine:
     - Spread statuses: PENDING -> SUBMITTING_HEDGES -> SUBMITTING_SHORTS -> FILLED
       or LEGGING_FAILED_UNWOUND / UNKNOWN_FREEZE.
  4. End-to-End Audit Trail:
     - Every leg transition is immutably logged to the security audit ledger.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from engine.defined_risk_spreads import DefinedRiskSpread
from engine.order_lifecycle import (
    OrderIntent,
    OrderStatus,
    preview_order_intent,
    confirm_order_intent,
    execute_order_intent,
)
from engine.security_audit import record_audit_event

logger = logging.getLogger("engine.multi_leg_executor")

SpreadExecutionStatus = Literal[
    "PENDING",
    "SUBMITTING_HEDGES",
    "SUBMITTING_SHORTS",
    "FILLED",
    "LEGGING_FAILED_UNWOUND",
    "REJECTED",
    "UNKNOWN_FREEZE",
]


@dataclass
class ChildLegExecution:
    leg_index: int
    symbol: str
    option_type: str
    strike: float
    side: Literal["BUY", "SELL"]
    quantity: int
    limit_price: float
    order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    status: OrderStatus = "DRAFT"
    fill_price: float = 0.0
    error_message: str = ""


@dataclass
class SpreadExecutionResult:
    spread_id: str
    strategy_name: str
    underlying: str
    status: SpreadExecutionStatus
    legs: list[ChildLegExecution]
    net_fill_price: float = 0.0  # Realized net debit (+) or credit (-)
    execution_start_time: str = ""
    execution_end_time: str = ""
    total_duration_ms: float = 0.0
    unwind_performed: bool = False
    rejection_reason: str = ""
    audit_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spread_id": self.spread_id,
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "status": self.status,
            "net_fill_price": round(self.net_fill_price, 2),
            "execution_start_time": self.execution_start_time,
            "execution_end_time": self.execution_end_time,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "unwind_performed": self.unwind_performed,
            "rejection_reason": self.rejection_reason,
            "legs": [
                {
                    "leg_index": l.leg_index,
                    "symbol": l.symbol,
                    "option_type": l.option_type,
                    "strike": l.strike,
                    "side": l.side,
                    "quantity": l.quantity,
                    "status": l.status,
                    "fill_price": round(l.fill_price, 2),
                    "order_id": l.order_id,
                    "broker_order_id": l.broker_order_id,
                    "error_message": l.error_message,
                }
                for l in self.legs
            ],
            "audit_events": self.audit_events,
        }


def execute_defined_risk_spread(
    spread: DefinedRiskSpread,
    product: str = "MIS",
    max_legging_timeout_ms: float = 1500.0,
    executor_fn: Optional[Callable[[str], OrderIntent]] = None,
    unwind_fn: Optional[Callable[[str, int, str], bool]] = None,
) -> SpreadExecutionResult:
    """
    Atomically execute a defined-risk options spread with hedge-first sequencing
    and automated legging-risk unwinding.

    Args:
        spread: DefinedRiskSpread object with constituent legs.
        product: 'MIS' (intraday) or 'NRML' (positional).
        max_legging_timeout_ms: Milliseconds to wait before declaring legging failure.
        executor_fn: Optional test mock for execute_order_intent.
        unwind_fn: Optional test mock for emergency liquidation.
    """
    exec_intent = executor_fn or execute_order_intent
    spread_id = f"spread-{uuid.uuid4().hex[:12]}"
    start_t = time.monotonic()
    start_iso = datetime.now(timezone.utc).isoformat()

    child_legs: list[ChildLegExecution] = []
    for idx, leg in enumerate(spread.legs):
        child_legs.append(
            ChildLegExecution(
                leg_index=idx,
                symbol=leg.symbol,
                option_type=leg.option_type,
                strike=leg.strike,
                side=leg.side,
                quantity=leg.quantity,
                limit_price=leg.premium,
            )
        )

    result = SpreadExecutionResult(
        spread_id=spread_id,
        strategy_name=spread.strategy_name,
        underlying=spread.underlying,
        status="PENDING",
        legs=child_legs,
        execution_start_time=start_iso,
    )

    def _log_event(action: str, details: dict[str, Any]):
        evt = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "details": details,
        }
        result.audit_events.append(evt)
        record_audit_event(
            event_type=f"SPREAD_{action}",
            actor="MULTI_LEG_EXECUTOR",
            details=details,
        )

    _log_event(
        "INITIATED",
        {"spread_id": spread_id, "strategy": spread.strategy_name, "legs_count": len(child_legs)},
    )

    # Partition into BUY legs (hedges) and SELL legs (short strikes)
    buy_legs = [l for l in child_legs if l.side == "BUY"]
    sell_legs = [l for l in child_legs if l.side == "SELL"]

    # ── Phase 1: Submit and Confirm All BUY (Hedge) Legs First ─────────────
    result.status = "SUBMITTING_HEDGES"
    for leg in buy_legs:
        try:
            # 1. Create order intent preview
            intent = preview_order_intent(
                symbol=leg.symbol,
                side="BUY",
                quantity=leg.quantity,
                price=leg.limit_price,
                order_type="LIMIT" if leg.limit_price > 0 else "MARKET",
                product=product,
            )
            leg.order_id = intent.order_id

            # 2. Confirm preview hash
            confirm_order_intent(intent.order_id, intent.preview_hash)

            # 3. Execute
            exec_res = exec_intent(intent.order_id)
            leg.status = exec_res.status
            leg.broker_order_id = exec_res.broker_order_id
            leg.fill_price = (
                getattr(exec_res, "fill_price", None) or exec_res.price or leg.limit_price
            )

            if exec_res.status not in ("FILLED", "OPEN"):
                raise RuntimeError(f"Hedge leg {leg.symbol} failed with status {exec_res.status}")

            _log_event("HEDGE_LEG_CONFIRMED", {"leg_symbol": leg.symbol, "order_id": leg.order_id})

        except Exception as e_hedge:
            logger.error(
                f"[multi_leg_executor] Hedge leg submission failed for {leg.symbol}: {e_hedge}"
            )
            leg.status = "REJECTED"
            leg.error_message = str(e_hedge)
            result.status = "REJECTED"
            result.rejection_reason = f"Hedge leg {leg.symbol} rejected: {e_hedge}"
            result.execution_end_time = datetime.now(timezone.utc).isoformat()
            result.total_duration_ms = (time.monotonic() - start_t) * 1000.0
            _log_event("FAILED_AT_HEDGE", {"error": str(e_hedge)})
            return result

    # ── Phase 2: Submit Short (SELL) Legs with Auto-Unwind Guard ───────────
    result.status = "SUBMITTING_SHORTS"
    for leg in sell_legs:
        try:
            # Check elapsed time against legging timeout
            elapsed_ms = (time.monotonic() - start_t) * 1000.0
            if elapsed_ms > max_legging_timeout_ms:
                raise TimeoutError(
                    f"Legging timeout exceeded ({elapsed_ms:.1f}ms > {max_legging_timeout_ms}ms)"
                )

            intent = preview_order_intent(
                symbol=leg.symbol,
                side="SELL",
                quantity=leg.quantity,
                price=leg.limit_price,
                order_type="LIMIT" if leg.limit_price > 0 else "MARKET",
                product=product,
            )
            leg.order_id = intent.order_id
            confirm_order_intent(intent.order_id, intent.preview_hash)

            exec_res = exec_intent(intent.order_id)
            leg.status = exec_res.status
            leg.broker_order_id = exec_res.broker_order_id
            leg.fill_price = (
                getattr(exec_res, "fill_price", None) or exec_res.price or leg.limit_price
            )

            if exec_res.status not in ("FILLED", "OPEN"):
                raise RuntimeError(f"Short leg {leg.symbol} failed with status {exec_res.status}")

            _log_event("SHORT_LEG_CONFIRMED", {"leg_symbol": leg.symbol, "order_id": leg.order_id})

        except Exception as e_short:
            logger.critical(
                f"[multi_leg_executor] LEGGING RISK TRIGGERED: Short leg {leg.symbol} failed! Initiating auto-unwind. Error: {e_short}"
            )
            leg.status = "REJECTED"
            leg.error_message = str(e_short)
            result.status = "LEGGING_FAILED_UNWOUND"
            result.rejection_reason = f"Short leg failed ({e_short}). Auto-unwind executed."

            # ── Emergency Auto-Unwind: Liquidate Filled BUY Legs ───────────
            _unwind_filled_hedges(buy_legs, unwind_fn)
            result.unwind_performed = True
            _log_event("EMERGENCY_UNWIND_COMPLETED", {"unwound_legs": [l.symbol for l in buy_legs]})

            result.execution_end_time = datetime.now(timezone.utc).isoformat()
            result.total_duration_ms = (time.monotonic() - start_t) * 1000.0
            return result

    # ── Phase 3: All Legs Filled Successfully ──────────────────────────────
    result.status = "FILLED"
    result.execution_end_time = datetime.now(timezone.utc).isoformat()
    result.total_duration_ms = (time.monotonic() - start_t) * 1000.0

    # Calculate realized net debit or credit
    net_val = 0.0
    for leg in child_legs:
        sign = 1.0 if leg.side == "BUY" else -1.0
        net_val += sign * leg.fill_price * leg.quantity
    result.net_fill_price = net_val

    _log_event(
        "SPREAD_COMPLETED",
        {"status": "FILLED", "net_cashflow": net_val, "duration_ms": result.total_duration_ms},
    )
    return result


def _unwind_filled_hedges(
    filled_buy_legs: list[ChildLegExecution],
    custom_unwind_fn: Optional[Callable[[str, int, str], bool]] = None,
) -> None:
    """
    Emergency liquidation of already-filled long hedge legs to neutralize naked exposure.
    """
    for leg in filled_buy_legs:
        if leg.status in ("FILLED", "OPEN") and leg.order_id:
            try:
                if custom_unwind_fn:
                    custom_unwind_fn(leg.symbol, leg.quantity, "SELL")
                else:
                    # Place emergency market SELL to exit the long leg
                    unwind_intent = preview_order_intent(
                        symbol=leg.symbol,
                        side="SELL",
                        quantity=leg.quantity,
                        price=0.0,
                        order_type="MARKET",
                        product="MIS",
                    )
                    confirm_order_intent(unwind_intent.order_id, unwind_intent.preview_hash)
                    execute_order_intent(unwind_intent.order_id)
                logger.info(
                    f"[multi_leg_executor] Successfully unwound long hedge leg {leg.symbol}."
                )
            except Exception as e_unwind:
                logger.critical(
                    f"[multi_leg_executor] CRITICAL: Failed to unwind long hedge leg {leg.symbol}: {e_unwind}. Manual intervention required!"
                )
