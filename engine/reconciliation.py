"""
engine/reconciliation.py
────────────────────────
Broker Statement & Internal Ledger Reconciliation Engine.

Compares internal trade intent and execution records against broker statements,
identifies discrepancies across quantities, prices, fees, and cash balances,
and assigns formal institutional accounting statuses:
  - COMPLETE: Perfect reconciliation (zero discrepancies).
  - PARTIAL: Minor fee or rounding difference within tolerance (cash diff <= 100).
  - STALE: Broker statement timestamp lag detected.
  - RECONCILING: In-flight execution awaiting confirmation.
  - DISPUTED: Quantity mismatch, large cash disparity, or missing positions.
  - UNAVAILABLE: Live broker statement or internal cash baseline unavailable.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

ReconciliationStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "STALE",
    "RECONCILING",
    "DISPUTED",
    "UNAVAILABLE",
]


@dataclass
class PositionDiscrepancy:
    symbol: str
    internal_qty: int
    broker_qty: int
    qty_diff: int
    internal_avg_price: float
    broker_avg_price: float
    price_diff: float
    discrepancy_type: (
        str  # "QTY_MISMATCH", "PRICE_MISMATCH", "MISSING_IN_BROKER", "MISSING_IN_LEDGER"
    )
    severity: str  # "HIGH", "MEDIUM", "LOW"
    actionable_fix: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationReport:
    timestamp: str
    status: ReconciliationStatus
    broker_name: str
    total_positions_checked: int
    matched_positions_count: int
    discrepancies_count: int
    is_reconciled: bool = True
    allow_trading: bool = True
    discrepancies: list[PositionDiscrepancy] = field(default_factory=list)
    cash_internal: float = 0.0
    cash_broker: float = 0.0
    cash_diff: float = 0.0
    unrealized_pnl_diff: float = 0.0
    summary_verdict: str = ""
    audit_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_qty(pos: dict[str, Any]) -> int:
    return int(pos.get("quantity", pos.get("qty", 0)))


def _extract_avg_price(pos: dict[str, Any]) -> float:
    return float(
        pos.get(
            "average_price",
            pos.get("avg_price", pos.get("average_cost_basis", 0.0)),
        )
    )


def _norm_sym(s: Any) -> str:
    sym = str(s or "").upper().strip()
    if ":" in sym:
        sym = sym.split(":")[-1]
    return sym


def reconcile_ledger(
    internal_positions: list[dict[str, Any]],
    broker_positions: list[dict[str, Any]],
    internal_cash: Optional[float] = None,
    broker_cash: Optional[float] = None,
    broker_name: str = "PAPER_SIMULATOR",
    price_tolerance: float = 0.05,  # 5 paise tolerance
) -> ReconciliationReport:
    """
    Reconcile internal position ledger against broker statement snapshot.

    Institutional Integrity Rules:
      1. Both internal_cash and broker_cash are strictly required; never fabricates 10 lakh.
      2. Missing cash returns status="UNAVAILABLE" and allow_trading=False.
      3. Robustly normalizes 'quantity'/'qty' and 'average_price'/'avg_price'.
      4. Disallows trading if cash divergence exceeds operational tolerance or position mismatch exists.
    """
    from market.instruments import get_current_ist_time

    now_str = get_current_ist_time().strftime("%d %b %Y, %H:%M:%S IST")

    if internal_cash is None or broker_cash is None:
        return ReconciliationReport(
            timestamp=now_str,
            status="UNAVAILABLE",
            broker_name=broker_name,
            total_positions_checked=0,
            matched_positions_count=0,
            discrepancies_count=0,
            is_reconciled=False,
            allow_trading=False,
            discrepancies=[],
            cash_internal=float(internal_cash or 0.0),
            cash_broker=float(broker_cash or 0.0),
            cash_diff=0.0,
            summary_verdict="UNAVAILABLE: Live broker statement or internal cash baseline unavailable.",
            audit_hash="",
        )

    def _pos_key(p: dict[str, Any]) -> str:
        s = _norm_sym(p.get("symbol"))
        prod = str(p.get("product") or "").upper().strip()
        return f"{s}:{prod}" if prod else s

    # Normalize mapping by canonical symbol & product
    internal_map: dict[str, dict[str, Any]] = {}
    for p in internal_positions:
        k = _pos_key(p)
        if k:
            internal_map[k] = p

    broker_map: dict[str, dict[str, Any]] = {}
    for p in broker_positions:
        k = _pos_key(p)
        if k:
            broker_map[k] = p

    all_symbols = sorted(set(list(internal_map.keys()) + list(broker_map.keys())))
    discrepancies: list[PositionDiscrepancy] = []
    matched_count = 0

    for sym in all_symbols:
        int_pos = internal_map.get(sym)
        brk_pos = broker_map.get(sym)

        if int_pos and not brk_pos:
            i_qty = _extract_qty(int_pos)
            i_price = _extract_avg_price(int_pos)
            if i_qty != 0:
                discrepancies.append(
                    PositionDiscrepancy(
                        symbol=sym,
                        internal_qty=i_qty,
                        broker_qty=0,
                        qty_diff=i_qty,
                        internal_avg_price=i_price,
                        broker_avg_price=0.0,
                        price_diff=i_price,
                        discrepancy_type="MISSING_IN_BROKER",
                        severity="HIGH",
                        actionable_fix=f"Position {sym} exists in internal ledger ({i_qty} shares) but missing on broker statement. Verify order fill status.",
                    )
                )
            else:
                matched_count += 1
        elif brk_pos and not int_pos:
            b_qty = _extract_qty(brk_pos)
            b_price = _extract_avg_price(brk_pos)
            if b_qty != 0:
                discrepancies.append(
                    PositionDiscrepancy(
                        symbol=sym,
                        internal_qty=0,
                        broker_qty=b_qty,
                        qty_diff=-b_qty,
                        internal_avg_price=0.0,
                        broker_avg_price=b_price,
                        price_diff=b_price,
                        discrepancy_type="MISSING_IN_LEDGER",
                        severity="HIGH",
                        actionable_fix=f"Unrecognized position {sym} on broker ({b_qty} shares). Run sync_execution_orders to import broker execution.",
                    )
                )
            else:
                matched_count += 1
        else:
            i_qty = _extract_qty(int_pos)
            b_qty = _extract_qty(brk_pos)
            i_price = _extract_avg_price(int_pos)
            b_price = _extract_avg_price(brk_pos)

            qty_diff = i_qty - b_qty
            price_diff = round(abs(i_price - b_price), 2)

            if qty_diff != 0:
                discrepancies.append(
                    PositionDiscrepancy(
                        symbol=sym,
                        internal_qty=i_qty,
                        broker_qty=b_qty,
                        qty_diff=qty_diff,
                        internal_avg_price=i_price,
                        broker_avg_price=b_price,
                        price_diff=price_diff,
                        discrepancy_type="QTY_MISMATCH",
                        severity="HIGH",
                        actionable_fix=f"Quantity mismatch ({i_qty} vs {b_qty}). Reconcile fill tickets.",
                    )
                )
            elif price_diff > price_tolerance:
                discrepancies.append(
                    PositionDiscrepancy(
                        symbol=sym,
                        internal_qty=i_qty,
                        broker_qty=b_qty,
                        qty_diff=0,
                        internal_avg_price=i_price,
                        broker_avg_price=b_price,
                        price_diff=price_diff,
                        discrepancy_type="PRICE_MISMATCH",
                        severity="MEDIUM",
                        actionable_fix=f"Execution average price deviation (₹{i_price} vs ₹{b_price}). Check broker slippage.",
                    )
                )
            else:
                matched_count += 1

    cash_diff = round(float(internal_cash) - float(broker_cash), 2)

    # Determine overall status
    if len(discrepancies) == 0 and abs(cash_diff) < 1.0:
        status: ReconciliationStatus = "COMPLETE"
        verdict = f"🟢 RECONCILED: All {len(all_symbols)} positions and cash balances match broker perfectly."
    elif any(d.severity == "HIGH" for d in discrepancies):
        status = "DISPUTED"
        verdict = f"🔴 DISPUTED: {len([d for d in discrepancies if d.severity == 'HIGH'])} critical position quantity mismatch(es) detected."
    elif abs(cash_diff) > 500.0:
        # Large cash disparity is DISPUTED, never allowed to trade
        status = "DISPUTED"
        verdict = (
            f"🔴 DISPUTED: Severe cash balance discrepancy detected (Cash diff: ₹{cash_diff:,.2f})."
        )
    elif len(discrepancies) > 0 or abs(cash_diff) >= 1.0:
        status = "PARTIAL"
        verdict = f"🟡 PARTIAL: Minor pricing/cash difference (Cash diff: ₹{cash_diff:,.2f}) within operational bounds."
    else:
        status = "RECONCILING"
        verdict = "🔄 RECONCILING: Position sync in progress."

    audit_hash = hashlib.sha256(
        f"{now_str}:{status}:{len(all_symbols)}:{cash_diff}".encode()
    ).hexdigest()[:16]

    is_reconciled = status == "COMPLETE"
    # allow_trading is ONLY allowed for COMPLETE or minor PARTIAL fee deviations (<= ₹100 cash diff and zero position discrepancies)
    allow_trading = (status == "COMPLETE") or (
        status == "PARTIAL" and abs(cash_diff) <= 100.0 and len(discrepancies) == 0
    )

    return ReconciliationReport(
        timestamp=now_str,
        status=status,
        broker_name=broker_name,
        total_positions_checked=len(all_symbols),
        matched_positions_count=matched_count,
        discrepancies_count=len(discrepancies),
        is_reconciled=is_reconciled,
        allow_trading=allow_trading,
        discrepancies=discrepancies,
        cash_internal=float(internal_cash),
        cash_broker=float(broker_cash),
        cash_diff=cash_diff,
        summary_verdict=verdict,
        audit_hash=audit_hash,
    )
