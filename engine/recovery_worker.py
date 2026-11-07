"""
engine/recovery_worker.py
─────────────────────────
Institutional Recovery Worker for In-Flight and Ambiguous Orders:
  - Resolves orders stranded in SUBMITTING, UNKNOWN_FREEZE, or PENDING_FACTS.
  - Matches orders against live broker order book via broker_order_id or client tag.
  - Ingests authentic fills upon discovery and transitions orders to canonical states.
  - Fail-closed: Flags orders that remain unconfirmed after grace period.
  - Safety barrier: Blocks new live executions while an unresolved UNKNOWN_FREEZE exists.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from engine.order_lifecycle import (
    _get_orders_db,
    _record_order_event,
    ingest_broker_executions,
)
from engine.security_audit import record_audit_event
from brokers.order_types import normalize_order_status

logger = logging.getLogger(__name__)

_worker_task: Optional[asyncio.Task] = None
_worker_stop_event = threading.Event()


def has_active_unknown_freeze(account_id: Optional[str] = None) -> bool:
    """Return True if any UNKNOWN_FREEZE order exists for the given account (or globally)."""
    with _get_orders_db() as conn:
        if account_id and account_id.strip():
            row = conn.execute(
                "SELECT 1 FROM orders_ledger WHERE status = 'UNKNOWN_FREEZE' AND account_id = ? LIMIT 1",
                (account_id.strip(),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM orders_ledger WHERE status = 'UNKNOWN_FREEZE' LIMIT 1"
            ).fetchone()
        return row is not None


def run_recovery_cycle() -> dict[str, Any]:
    """
    Execute a single synchronous reconciliation cycle across stuck or ambiguous orders.

    Scans for:
      - status == 'SUBMITTING'
      - status == 'UNKNOWN_FREEZE'
      - ledger_status in ('PENDING_FACTS', 'INGESTION_FAILED')
    """
    from brokers.session import get_execution_broker, get_execution_broker_key

    broker = get_execution_broker()
    provider = get_execution_broker_key() or (
        broker.__class__.__name__.lower() if broker else "UNKNOWN"
    )

    with _get_orders_db() as conn:
        conn.row_factory = sqlite3.Row
        stuck_orders = conn.execute(
            """
            SELECT * FROM orders_ledger
            WHERE status IN ('SUBMITTING', 'UNKNOWN_FREEZE')
               OR ledger_status IN ('PENDING_FACTS', 'INGESTION_FAILED')
            """
        ).fetchall()

    if not stuck_orders:
        return {
            "status": "CLEAN",
            "stuck_count": 0,
            "recovered_count": 0,
            "active_freeze_count": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    if broker is None or not hasattr(broker, "get_orders"):
        logger.warning(
            "[RecoveryWorker] %d stuck/ambiguous orders detected, but execution broker is unavailable.",
            len(stuck_orders),
        )
        return {
            "status": "BROKER_UNAVAILABLE",
            "stuck_count": len(stuck_orders),
            "recovered_count": 0,
            "active_freeze_count": sum(1 for o in stuck_orders if o["status"] == "UNKNOWN_FREEZE"),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        broker_orders = broker.get_orders() or []
    except Exception as exc:
        logger.error("[RecoveryWorker] Failed to query broker orders: %s", exc)
        return {
            "status": "BROKER_QUERY_FAILED",
            "error": str(exc),
            "stuck_count": len(stuck_orders),
            "recovered_count": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    by_broker_id: dict[str, Any] = {}
    by_tag: dict[str, Any] = {}

    for bo in broker_orders:
        oid = getattr(bo, "order_id", None) or (
            bo.get("order_id") if isinstance(bo, dict) else None
        )
        tag = getattr(bo, "tag", None) or (bo.get("tag") if isinstance(bo, dict) else None)
        if oid:
            by_broker_id[str(oid)] = bo
        if tag:
            by_tag[str(tag)] = bo

    recovered = 0
    affected_parents: set[str] = set()
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    for row in stuck_orders:
        if row["parent_order_id"]:
            affected_parents.add(str(row["parent_order_id"]))
        order_id = str(row["order_id"])
        broker_oid = str(row["broker_order_id"]) if row["broker_order_id"] else None
        curr_status = row["status"]

        matched_order = None
        if broker_oid and broker_oid in by_broker_id:
            matched_order = by_broker_id[broker_oid]
        elif order_id in by_tag:
            matched_order = by_tag[order_id]

        if matched_order:
            raw_st = getattr(matched_order, "status", None) or (
                matched_order.get("status") if isinstance(matched_order, dict) else None
            )
            norm_st = normalize_order_status(raw_st)
            target_status = "FILLED" if norm_st == "COMPLETE" else norm_st

            real_broker_id = (
                getattr(matched_order, "order_id", None)
                or (matched_order.get("order_id") if isinstance(matched_order, dict) else None)
                or broker_oid
            )

            filled_qty = int(
                getattr(matched_order, "filled_quantity", 0)
                or (
                    matched_order.get("filled_quantity", 0)
                    if isinstance(matched_order, dict)
                    else 0
                )
                or 0
            )
            avg_px = float(
                getattr(matched_order, "average_price", 0.0)
                or (
                    matched_order.get("average_price", 0.0)
                    if isinstance(matched_order, dict)
                    else 0.0
                )
                or 0.0
            )

            # Ingest execution fills if available
            try:
                ingest_broker_executions(
                    order_id=order_id,
                    broker_order_id=str(real_broker_id),
                    live_broker=broker,
                    broker_res=matched_order,
                    order_details=dict(row),
                )
            except Exception as e_ingest:
                logger.error("[RecoveryWorker] Fill ingestion error for %s: %s", order_id, e_ingest)

            with _get_orders_db() as conn:
                conn.execute(
                    """
                    UPDATE orders_ledger
                    SET status = ?, broker_order_id = ?, filled_quantity = ?, average_fill_price = ?,
                        last_sync_at = ?, updated_at = ?
                    WHERE order_id = ?
                    """,
                    (
                        target_status,
                        str(real_broker_id) if real_broker_id else None,
                        filled_qty,
                        avg_px if avg_px > 0 else None,
                        now_iso,
                        now_iso,
                        order_id,
                    ),
                )
                conn.commit()

            record_audit_event(
                event_type="ORDER_RECOVERED",
                mode=str(row["mode"]),
                details={
                    "order_id": order_id,
                    "previous_status": curr_status,
                    "recovered_status": target_status,
                    "broker_order_id": real_broker_id,
                },
            )
            _record_order_event(
                order_id,
                "RECOVERY_RESOLVED",
                broker_name=provider,
                broker_order_id=str(real_broker_id),
                payload={"recovered_status": target_status, "filled_quantity": filled_qty},
            )
            recovered += 1
        else:
            # Not found on broker
            if curr_status == "SUBMITTING":
                created_str = row["created_at"]
                try:
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    age_seconds = (now_dt - created_dt).total_seconds()
                except Exception:
                    age_seconds = 999.0

                if age_seconds > 60.0:
                    # Transition timed-out SUBMITTING to UNKNOWN_FREEZE for operator review
                    msg = f"Submission timed out ({age_seconds:.0f}s elapsed) and not found on broker order book."
                    with _get_orders_db() as conn:
                        conn.execute(
                            """
                            UPDATE orders_ledger
                            SET status = 'UNKNOWN_FREEZE', rejection_reason = ?, updated_at = ?
                            WHERE order_id = ? AND status = 'SUBMITTING'
                            """,
                            (msg, now_iso, order_id),
                        )
                        conn.commit()

                    record_audit_event(
                        event_type="ORDER_UNKNOWN_FREEZE",
                        mode=str(row["mode"]),
                        details={"order_id": order_id, "reason": msg},
                    )
                    _record_order_event(
                        order_id,
                        "SUBMITTING_TIMEOUT_FREEZE",
                        broker_name=provider,
                        payload={"reason": msg},
                    )

    if affected_parents:
        from engine.order_lifecycle import _reconcile_parent_order_in_conn

        with _get_orders_db() as conn:
            for pid in affected_parents:
                _reconcile_parent_order_in_conn(conn, pid, now_iso)
            conn.commit()

    return {
        "status": "OK",
        "stuck_count": len(stuck_orders),
        "recovered_count": recovered,
        "active_freeze_count": sum(1 for o in stuck_orders if o["status"] == "UNKNOWN_FREEZE")
        - recovered,
        "checked_at": now_iso,
    }


async def _recovery_worker_loop(interval_seconds: float = 30.0):
    """Background async polling task for FastAPI lifespan."""
    logger.info(
        "[RecoveryWorker] Background recovery worker started (interval: %.1fs)", interval_seconds
    )
    while not _worker_stop_event.is_set():
        try:
            await asyncio.to_thread(run_recovery_cycle)
        except Exception as e:
            logger.error("[RecoveryWorker] Error during recovery cycle: %s", e)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
    logger.info("[RecoveryWorker] Background recovery worker stopped.")


def start_recovery_worker(interval_seconds: float = 30.0) -> Optional[asyncio.Task]:
    """Start background recovery worker task."""
    global _worker_task
    _worker_stop_event.clear()
    try:
        loop = asyncio.get_running_loop()
        _worker_task = loop.create_task(_recovery_worker_loop(interval_seconds))
        return _worker_task
    except RuntimeError:
        logger.debug("[RecoveryWorker] No running event loop to start background task.")
        return None


def stop_recovery_worker():
    """Signal background recovery worker to stop."""
    global _worker_task
    _worker_stop_event.set()
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None
