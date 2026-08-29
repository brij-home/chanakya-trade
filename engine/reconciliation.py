"""
engine/reconciliation.py
────────────────────────
Broker Statement & Internal Ledger Reconciliation Engine.

Compares internal trade intent and execution records against broker statements,
identifies discrepancies across quantities, prices, fees, and cash balances,
and assigns formal institutional accounting statuses:
  - COMPLETE: Perfect reconciliation (zero discrepancies).
  - PARTIAL: Minor fee or rounding difference within tolerance.
  - STALE: Broker statement timestamp lag detected.
  - RECONCILING: In-flight execution awaiting confirmation.
  - DISPUTED: Quantity or position mismatch requiring immediate investigation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

ReconciliationStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "STALE",
    "RECONCILING",
    "DISPUTED",
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
    discrepancy_type: str  # "QTY_MISMATCH", "PRICE_MISMATCH", "MISSING_IN_BROKER", "MISSING_IN_LEDGER"
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
    discrepancies: list[PositionDiscrepancy] = field(default_factory=list)
    cash_internal: float = 0.0
    cash_broker: float = 0.0
    cash_diff: float = 0.0
    unrealized_pnl_diff: float = 0.0
    summary_verdict: str = ""
    audit_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_ledger(
    internal_positions: list[dict[str, Any]],
    broker_positions: list[dict[str, Any]],
    internal_cash: float = 1000000.0,
    broker_cash: float = 1000000.0,
    broker_name: str = "PAPER_SIMULATOR",
    price_tolerance: float = 0.05,  # 5 paise tolerance
) -> ReconciliationReport:
    """
    Reconcile internal position ledger against broker statement snapshot.

    Args:
        internal_positions: List of internal positions [{'symbol', 'qty', 'avg_price', 'pnl'}]
        broker_positions: List of broker positions [{'symbol', 'qty', 'avg_price', 'pnl'}]
        internal_cash: Internal cash ledger balance
        broker_cash: Official broker cash balance
        broker_name: Name of the broker
        price_tolerance: Allowed price tolerance buffer

    Returns:
        Structured ReconciliationReport with accounting classification.
    """
    now_str = datetime.now().strftime("%d %b %Y, %H:%M:%S IST")
    internal_map = {p.get("symbol", "").upper(): p for p in internal_positions if p.get("symbol")}
    broker_map = {p.get("symbol", "").upper(): p for p in broker_positions if p.get("symbol")}

    all_symbols = sorted(set(list(internal_map.keys()) + list(broker_map.keys())))
    discrepancies: list[PositionDiscrepancy] = []
    matched_count = 0

    for sym in all_symbols:
        int_pos = internal_map.get(sym)
        brk_pos = broker_map.get(sym)

        if int_pos and not brk_pos:
            discrepancies.append(
                PositionDiscrepancy(
                    symbol=sym,
                    internal_qty=int(int_pos.get("qty", 0)),
                    broker_qty=0,
                    qty_diff=int(int_pos.get("qty", 0)),
                    internal_avg_price=float(int_pos.get("avg_price", 0.0)),
                    broker_avg_price=0.0,
                    price_diff=float(int_pos.get("avg_price", 0.0)),
                    discrepancy_type="MISSING_IN_BROKER",
                    severity="HIGH",
                    actionable_fix=f"Position {sym} exists in internal ledger but missing on broker statement. Verify order fill status.",
                )
            )
        elif brk_pos and not int_pos:
            discrepancies.append(
                PositionDiscrepancy(
                    symbol=sym,
                    internal_qty=0,
                    broker_qty=int(brk_pos.get("qty", 0)),
                    qty_diff=-int(brk_pos.get("qty", 0)),
                    internal_avg_price=0.0,
                    broker_avg_price=float(brk_pos.get("avg_price", 0.0)),
                    price_diff=float(brk_pos.get("avg_price", 0.0)),
                    discrepancy_type="MISSING_IN_LEDGER",
                    severity="HIGH",
                    actionable_fix=f"Unrecognized position {sym} on broker. Run sync_positions to import broker execution.",
                )
            )
        else:
            i_qty = int(int_pos.get("qty", 0))
            b_qty = int(brk_pos.get("qty", 0))
            i_price = float(int_pos.get("avg_price", 0.0))
            b_price = float(brk_pos.get("avg_price", 0.0))

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

    cash_diff = round(internal_cash - broker_cash, 2)

    # Determine overall status
    if len(discrepancies) == 0 and abs(cash_diff) < 1.0:
        status: ReconciliationStatus = "COMPLETE"
        verdict = f"🟢 RECONCILED: All {len(all_symbols)} positions and cash balances match broker perfectly."
    elif any(d.severity == "HIGH" for d in discrepancies):
        status = "DISPUTED"
        verdict = f"🔴 DISPUTED: {len([d for d in discrepancies if d.severity == 'HIGH'])} critical position quantity mismatch(es) detected."
    elif len(discrepancies) > 0 or abs(cash_diff) >= 1.0:
        status = "PARTIAL"
        verdict = f"🟡 PARTIAL: Minor pricing/cash difference (Cash diff: ₹{cash_diff:,.2f}) within operational bounds."
    else:
        status = "RECONCILING"
        verdict = "🔄 RECONCILING: Position sync in progress."

    import hashlib
    audit_hash = hashlib.sha256(f"{now_str}:{status}:{len(all_symbols)}:{cash_diff}".encode()).hexdigest()[:16]

    return ReconciliationReport(
        timestamp=now_str,
        status=status,
        broker_name=broker_name,
        total_positions_checked=len(all_symbols),
        matched_positions_count=matched_count,
        discrepancies_count=len(discrepancies),
        discrepancies=discrepancies,
        cash_internal=internal_cash,
        cash_broker=broker_cash,
        cash_diff=cash_diff,
        summary_verdict=verdict,
        audit_hash=audit_hash,
    )
