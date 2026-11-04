"""
engine/sqlite_store.py
──────────────────────
Institutional SQLite Storage Engine with Write-Ahead Logging (WAL) Mode.

Replaces synchronous, lock-bound monolithic JSON file serialization with a high-concurrency,
crash-resilient ACID SQLite database while preserving lossless backward-compatibility
with legacy JSON schemas.

Architectural Guarantees:
1. High-Concurrency: WAL mode allows concurrent readers without blocking writers.
2. Crash Resilience: Atomic transactions eliminate half-written file corruption on sudden reboots.
3. Sub-Millisecond Latency: Indexed queries on session_date, symbol, and status.
4. Lossless Round-Trip: Stores full serialized AutoAlert JSON payload alongside indexed query columns.
5. Dual-Sync Support: Bidirectional sync with legacy auto_alerts.json.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("engine.sqlite_store")
from config.constants import IST


def get_default_db_path() -> Path:
    """Returns canonical path to Chanakya ledger SQLite database."""
    from config.paths import app_data_path

    p = app_data_path("chanakya_ledger.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class SQLiteAlertStore:
    """
    Thread-safe SQLite storage engine for ChanakyaTrade market alerts.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns SQLite connection with WAL pragmas."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode and high-performance RAM/SSD pragmas
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA cache_size = -65536;")  # 64 MB RAM cache (negative = KiB)
        conn.execute("PRAGMA mmap_size = 268435456;")  # 256 MB memory-mapped file I/O
        conn.execute("PRAGMA temp_store = MEMORY;")  # Intermediate tables and sorts in RAM
        return conn

    def _init_db(self) -> None:
        """Initializes database schema and indexes."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    segment TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    ltp REAL,
                    trigger_level REAL,
                    target_level REAL,
                    stop_loss REAL,
                    confidence REAL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_session_date ON alerts(session_date);"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_alert_type ON alerts(alert_type);")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    event_version INTEGER NOT NULL DEFAULT 1,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    last_error TEXT,
                    claimed_by TEXT,
                    claimed_at TEXT,
                    lease_expires_at TEXT,
                    dispatched_at TEXT,
                    acknowledged_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT,
                    UNIQUE(alert_id, event_version, channel)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_pending ON alert_outbox(status, lease_expires_at);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_alert ON alert_outbox(alert_id, event_version);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_channel ON alert_outbox(channel, status);"
            )
            conn.commit()

    def save_alert(self, alert_or_dict: Any) -> None:
        """
        Saves or updates an alert atomically (UPSERT).
        Accepts AutoAlert instance or dict.
        """
        if hasattr(alert_or_dict, "to_dict"):
            d = alert_or_dict.to_dict()
        elif hasattr(alert_or_dict, "as_dict"):
            d = alert_or_dict.as_dict()
        elif isinstance(alert_or_dict, dict):
            d = dict(alert_or_dict)
        else:
            raise TypeError(f"Expected AutoAlert or dict, got {type(alert_or_dict).__name__}")

        alert_id = d.get("alert_id") or ""
        if not alert_id:
            logger.warning("[SQLiteAlertStore] Skipped saving alert missing alert_id")
            return

        from engine.data_sanctity import assert_production_data_sanctity

        if not assert_production_data_sanctity(d, "SQLiteAlertStore"):
            return

        symbol = str(d.get("symbol") or "")
        exchange = str(d.get("exchange") or "NSE")
        segment = str(d.get("segment") or "EQUITY")
        alert_type = str(d.get("alert_type") or "UNKNOWN")
        stage = str(d.get("stage") or "EARLY_WARNING")
        direction = str(d.get("direction") or "BULLISH")

        # Extract session_date: from alert_id suffix or timestamp
        session_date = ""
        parts = alert_id.split("-")
        if parts and len(parts[-1]) == 8 and parts[-1].isdigit():
            session_date = parts[-1]
        if not session_date:
            session_date = datetime.now(IST).strftime("%Y%m%d")

        ltp = float(d.get("ltp") or 0.0)
        trigger_level = float(d.get("trigger_level") or 0.0)
        target_level = float(d.get("target_level") or 0.0)
        stop_loss = float(d.get("stop_loss") or 0.0)
        confidence = float(d.get("confidence") or 0.0)

        # Status
        status = "ACTIVE"
        if d.get("is_invalidated"):
            status = "INVALIDATED"
        elif d.get("is_target_hit"):
            status = "TARGET_HIT"
        elif d.get("is_archived"):
            status = "ARCHIVED"

        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        created_at = str(d.get("created_at") or d.get("timestamp") or now_str)
        updated_at = now_str
        payload_json = json.dumps(d)

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO alerts (
                    alert_id, symbol, exchange, segment, alert_type, stage, direction,
                    session_date, ltp, trigger_level, target_level, stop_loss, confidence,
                    status, created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    stage = excluded.stage,
                    ltp = excluded.ltp,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json;
                """,
                (
                    alert_id,
                    symbol,
                    exchange,
                    segment,
                    alert_type,
                    stage,
                    direction,
                    session_date,
                    ltp,
                    trigger_level,
                    target_level,
                    stop_loss,
                    confidence,
                    status,
                    created_at,
                    updated_at,
                    payload_json,
                ),
            )
            conn.commit()

    def save_alerts_batch(self, alerts: list[Any]) -> int:
        """
        Saves or updates a batch of alerts atomically within a single SQLite transaction.
        """
        if not alerts:
            return 0

        from engine.data_sanctity import assert_production_data_sanctity

        alerts = [a for a in alerts if assert_production_data_sanctity(a, "SQLiteAlertStore")]
        if not alerts:
            return 0

        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        rows_to_insert = []
        for alert_or_dict in alerts:
            if hasattr(alert_or_dict, "to_dict"):
                d = alert_or_dict.to_dict()
            elif hasattr(alert_or_dict, "as_dict"):
                d = alert_or_dict.as_dict()
            elif isinstance(alert_or_dict, dict):
                d = dict(alert_or_dict)
            else:
                continue

            alert_id = d.get("alert_id") or ""
            if not alert_id:
                continue

            symbol = str(d.get("symbol") or "")
            exchange = str(d.get("exchange") or "NSE")
            segment = str(d.get("segment") or "EQUITY")
            alert_type = str(d.get("alert_type") or "UNKNOWN")
            stage = str(d.get("stage") or "EARLY_WARNING")
            direction = str(d.get("direction") or "BULLISH")

            session_date = ""
            parts = alert_id.split("-")
            if parts and len(parts[-1]) == 8 and parts[-1].isdigit():
                session_date = parts[-1]
            if not session_date:
                session_date = datetime.now(IST).strftime("%Y%m%d")

            ltp = float(d.get("ltp") or 0.0)
            trigger_level = float(d.get("trigger_level") or 0.0)
            target_level = float(d.get("target_level") or 0.0)
            stop_loss = float(d.get("stop_loss") or 0.0)
            confidence = float(d.get("confidence") or 0.0)

            status = "ACTIVE"
            if d.get("is_invalidated"):
                status = "INVALIDATED"
            elif d.get("is_target_hit"):
                status = "TARGET_HIT"
            elif d.get("is_archived"):
                status = "ARCHIVED"

            created_at = str(d.get("created_at") or d.get("timestamp") or now_str)
            payload_json = json.dumps(d)
            rows_to_insert.append(
                (
                    alert_id,
                    symbol,
                    exchange,
                    segment,
                    alert_type,
                    stage,
                    direction,
                    session_date,
                    ltp,
                    trigger_level,
                    target_level,
                    stop_loss,
                    confidence,
                    status,
                    created_at,
                    now_str,
                    payload_json,
                )
            )

        if not rows_to_insert:
            return 0

        with self._lock, self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO alerts (
                    alert_id, symbol, exchange, segment, alert_type, stage, direction,
                    session_date, ltp, trigger_level, target_level, stop_loss, confidence,
                    status, created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    stage = excluded.stage,
                    ltp = excluded.ltp,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json;
                """,
                rows_to_insert,
            )
            conn.commit()
        return len(rows_to_insert)

    def save_alert_with_outbox(
        self,
        alert_or_dict: Any,
        outbox_entries: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        """
        Atomically saves or updates an alert AND stages outbox delivery intents
        within a single SQLite transaction.

        Guarantees:
        1. Atomic all-or-nothing persistence: alert state and outbox intents are committed together.
        2. Unique constraint enforcement on (alert_id, event_version, channel).
        3. Identical idempotent retry succeeds cleanly; conflicting payload raises ValueError.
        """
        if hasattr(alert_or_dict, "to_dict"):
            d = alert_or_dict.to_dict()
        elif hasattr(alert_or_dict, "as_dict"):
            d = alert_or_dict.as_dict()
        elif isinstance(alert_or_dict, dict):
            d = dict(alert_or_dict)
        else:
            raise TypeError(f"Expected AutoAlert or dict, got {type(alert_or_dict).__name__}")

        alert_id = d.get("alert_id") or ""
        if not alert_id:
            raise ValueError("Alert missing alert_id")

        from engine.data_sanctity import assert_production_data_sanctity

        if not assert_production_data_sanctity(d, "SQLiteAlertStore"):
            raise ValueError(f"Alert {alert_id} failed production data sanctity check")

        symbol = str(d.get("symbol") or "")
        exchange = str(d.get("exchange") or "NSE")
        segment = str(d.get("segment") or "EQUITY")
        alert_type = str(d.get("alert_type") or "UNKNOWN")
        stage = str(d.get("stage") or "EARLY_WARNING")
        direction = str(d.get("direction") or "BULLISH")

        session_date = ""
        parts = alert_id.split("-")
        if parts and len(parts[-1]) == 8 and parts[-1].isdigit():
            session_date = parts[-1]
        if not session_date:
            session_date = datetime.now(IST).strftime("%Y%m%d")

        ltp = float(d.get("ltp") or 0.0)
        trigger_level = float(d.get("trigger_level") or 0.0)
        target_level = float(d.get("target_level") or 0.0)
        stop_loss = float(d.get("stop_loss") or 0.0)
        confidence = float(d.get("confidence") or 0.0)

        status = "ACTIVE"
        if d.get("is_invalidated"):
            status = "INVALIDATED"
        elif d.get("is_target_hit"):
            status = "TARGET_HIT"
        elif d.get("is_archived"):
            status = "ARCHIVED"

        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        now_iso = datetime.now(timezone.utc).isoformat()
        created_at = str(d.get("created_at") or d.get("timestamp") or now_str)
        updated_at = now_str
        payload_json = json.dumps(d)
        alert_version = int(d.get("version") or d.get("event_version") or 1)

        staged_ids: list[str] = []

        with self._lock, self._get_connection() as conn:
            # 1. Upsert alert
            conn.execute(
                """
                INSERT INTO alerts (
                    alert_id, symbol, exchange, segment, alert_type, stage, direction,
                    session_date, ltp, trigger_level, target_level, stop_loss, confidence,
                    status, created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    stage = excluded.stage,
                    ltp = excluded.ltp,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json;
                """,
                (
                    alert_id,
                    symbol,
                    exchange,
                    segment,
                    alert_type,
                    stage,
                    direction,
                    session_date,
                    ltp,
                    trigger_level,
                    target_level,
                    stop_loss,
                    confidence,
                    status,
                    created_at,
                    updated_at,
                    payload_json,
                ),
            )

            # 2. Stage outbox entries atomically
            for item in outbox_entries:
                channel = str(item.get("channel") or "").upper().strip()
                if not channel:
                    raise ValueError(f"Outbox entry for alert {alert_id} missing channel")
                entry_version = int(item.get("event_version") or alert_version)
                item_payload = item.get("payload") if item.get("payload") is not None else d
                entry_payload_json = json.dumps(item_payload)
                max_attempts = int(item.get("max_attempts") or 3)
                outbox_id = str(
                    item.get("outbox_id") or f"outbox-{alert_id}-v{entry_version}-{channel.lower()}"
                )

                # Check if entry already exists
                existing = conn.execute(
                    "SELECT outbox_id, payload_json, status FROM alert_outbox WHERE alert_id = ? AND event_version = ? AND channel = ?;",
                    (alert_id, entry_version, channel),
                ).fetchone()

                if existing:
                    existing_payload = json.loads(existing["payload_json"])
                    if existing_payload == item_payload:
                        # Idempotent retry: payload is identical
                        staged_ids.append(existing["outbox_id"])
                        continue
                    # Conflicting payload
                    raise ValueError(
                        f"Conflicting outbox delivery intent for alert={alert_id} v{entry_version} channel={channel}"
                    )

                conn.execute(
                    """
                    INSERT INTO alert_outbox (
                        outbox_id, alert_id, event_version, channel, status, payload_json,
                        attempts, max_attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'PENDING', ?, 0, ?, ?, ?);
                    """,
                    (
                        outbox_id,
                        alert_id,
                        entry_version,
                        channel,
                        entry_payload_json,
                        max_attempts,
                        now_iso,
                        now_iso,
                    ),
                )
                staged_ids.append(outbox_id)

            conn.commit()

        return alert_id, staged_ids

    def get_latest_outbox_version(self, alert_id: str) -> int:
        """Returns the highest event_version currently recorded in the outbox for an alert_id (0 if none)."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT MAX(event_version) as max_v FROM alert_outbox WHERE alert_id = ?;",
                (alert_id,),
            ).fetchone()
            if row and row["max_v"] is not None:
                return int(row["max_v"])
            return 0

    def stage_outbox_entry(
        self,
        alert_id: str,
        channel: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        event_version: int = 1,
    ) -> str:
        """Stages single outbox entry with idempotency check."""
        channel_upper = channel.upper().strip()
        outbox_id = f"outbox-{alert_id}-v{event_version}-{channel_upper.lower()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)

        with self._lock, self._get_connection() as conn:
            existing = conn.execute(
                "SELECT outbox_id, payload_json, status FROM alert_outbox WHERE alert_id = ? AND event_version = ? AND channel = ?;",
                (alert_id, event_version, channel_upper),
            ).fetchone()
            if existing:
                existing_payload = json.loads(existing["payload_json"])
                if existing_payload == payload:
                    return str(existing["outbox_id"])
                raise ValueError(
                    f"Conflicting outbox delivery intent for alert={alert_id} v{event_version} channel={channel_upper}"
                )

            conn.execute(
                """
                INSERT INTO alert_outbox (
                    outbox_id, alert_id, event_version, channel, status, payload_json,
                    attempts, max_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PENDING', ?, 0, ?, ?, ?);
                """,
                (
                    outbox_id,
                    alert_id,
                    event_version,
                    channel_upper,
                    payload_json,
                    max_attempts,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
            return outbox_id

    def claim_pending_outbox_entries(
        self,
        worker_id: str,
        lease_seconds: float = 30.0,
        limit: int = 50,
        channel: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Atomically leases pending or retryable outbox entries to a single worker.
        Prevents concurrent workers from claiming the same entry.
        Reclaims expired CLAIMED leases automatically.
        """
        if not worker_id:
            raise ValueError("worker_id is required to claim outbox entries")

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        lease_expiry_iso = (now_dt + timedelta(seconds=lease_seconds)).isoformat()

        chan_upper = channel.upper().strip() if channel else None

        with self._lock, self._get_connection() as conn:
            query = """
                SELECT outbox_id, alert_id, event_version, channel, status, payload_json,
                       attempts, max_attempts, last_error, claimed_by, claimed_at,
                       lease_expires_at, dispatched_at, acknowledged_at, created_at, updated_at
                FROM alert_outbox
                WHERE archived = 0
                  AND (
                      status IN ('PENDING', 'FAILED_RETRY')
                      OR (status = 'CLAIMED' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                  )
            """
            params: list[Any] = [now_iso]
            if chan_upper:
                query += " AND channel = ?"
                params.append(chan_upper)
            query += " ORDER BY rowid ASC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, tuple(params)).fetchall()
            if not rows:
                return []

            candidate_ids = [r["outbox_id"] for r in rows]
            placeholders = ",".join("?" for _ in candidate_ids)

            conn.execute(
                f"""
                UPDATE alert_outbox
                SET status = 'CLAIMED',
                    claimed_by = ?,
                    claimed_at = ?,
                    lease_expires_at = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE outbox_id IN ({placeholders});
                """,
                (worker_id, now_iso, lease_expiry_iso, now_iso, *candidate_ids),
            )
            conn.commit()

            claimed_rows = []
            for r in rows:
                d = dict(r)
                d["status"] = "CLAIMED"
                d["claimed_by"] = worker_id
                d["claimed_at"] = now_iso
                d["lease_expires_at"] = lease_expiry_iso
                d["attempts"] = int(d.get("attempts", 0)) + 1
                d["updated_at"] = now_iso
                d["payload"] = json.loads(d["payload_json"])
                claimed_rows.append(d)

            return claimed_rows

    def mark_outbox_dispatched(
        self,
        outbox_id: str,
        worker_id: Optional[str] = None,
        lease_seconds: float = 60.0,
    ) -> bool:
        """
        Transitions entry to DISPATCHED state with lease expiration for ambiguous detection.
        Validates worker identity if worker_id is provided.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        lease_expiry_iso = (now_dt + timedelta(seconds=lease_seconds)).isoformat()

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT claimed_by, status, attempts FROM alert_outbox WHERE outbox_id = ?;",
                (outbox_id,),
            ).fetchone()
            if not row:
                return False

            if worker_id is not None and row["claimed_by"] and row["claimed_by"] != worker_id:
                raise PermissionError(
                    f"Worker {worker_id} cannot dispatch entry claimed by {row['claimed_by']}"
                )

            attempts_inc = 0 if row["status"] == "CLAIMED" else 1

            conn.execute(
                """
                UPDATE alert_outbox
                SET status = 'DISPATCHED',
                    dispatched_at = ?,
                    lease_expires_at = ?,
                    attempts = attempts + ?,
                    updated_at = ?
                WHERE outbox_id = ?;
                """,
                (now_iso, lease_expiry_iso, attempts_inc, now_iso, outbox_id),
            )
            conn.commit()
            return True

    def mark_outbox_acknowledged(
        self,
        outbox_id: str,
        worker_id: Optional[str] = None,
    ) -> bool:
        """
        Transitions entry to ACKNOWLEDGED state.
        Idempotent: if already ACKNOWLEDGED, returns True.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT claimed_by, status FROM alert_outbox WHERE outbox_id = ?;",
                (outbox_id,),
            ).fetchone()
            if not row:
                return False

            if row["status"] == "ACKNOWLEDGED":
                return True

            if worker_id is not None and row["claimed_by"] and row["claimed_by"] != worker_id:
                raise PermissionError(
                    f"Worker {worker_id} cannot acknowledge entry claimed by {row['claimed_by']}"
                )

            conn.execute(
                """
                UPDATE alert_outbox
                SET status = 'ACKNOWLEDGED',
                    acknowledged_at = ?,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE outbox_id = ?;
                """,
                (now_iso, now_iso, outbox_id),
            )
            conn.commit()
            return True

    def mark_outbox_failed(
        self,
        outbox_id: str,
        error: str,
        worker_id: Optional[str] = None,
    ) -> bool:
        """
        Transitions entry to FAILED_RETRY (if attempts < max_attempts) or terminal FAILED.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT claimed_by, status, attempts, max_attempts FROM alert_outbox WHERE outbox_id = ?;",
                (outbox_id,),
            ).fetchone()
            if not row:
                return False

            if worker_id is not None and row["claimed_by"] and row["claimed_by"] != worker_id:
                raise PermissionError(
                    f"Worker {worker_id} cannot fail entry claimed by {row['claimed_by']}"
                )

            current_attempts = int(row["attempts"])
            if row["status"] != "CLAIMED":
                current_attempts += 1

            max_att = int(row["max_attempts"])
            new_status = "FAILED_RETRY" if current_attempts < max_att else "FAILED"

            conn.execute(
                """
                UPDATE alert_outbox
                SET status = ?,
                    attempts = ?,
                    last_error = ?,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE outbox_id = ?;
                """,
                (new_status, current_attempts, str(error), now_iso, outbox_id),
            )
            conn.commit()
            return True

    def get_outbox_entry(self, outbox_id: str) -> Optional[dict[str, Any]]:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM alert_outbox WHERE outbox_id = ? LIMIT 1;",
                (outbox_id,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["payload"] = json.loads(d["payload_json"])
            return d

    def get_pending_outbox_entries(self, channel: Optional[str] = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM alert_outbox WHERE status IN ('PENDING', 'FAILED_RETRY') AND archived = 0"
        params: list[Any] = []
        if channel:
            query += " AND channel = ?"
            params.append(channel.upper().strip())
        query += " ORDER BY rowid ASC;"
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["payload"] = json.loads(d["payload_json"])
                results.append(d)
            return results

    def get_ambiguous_outbox_entries(
        self,
        older_than_seconds: float = 60.0,
    ) -> list[dict[str, Any]]:
        """
        Returns entries in DISPATCHED state whose lease has expired without ACK.
        These are ambiguous deliveries needing reconciliation.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM alert_outbox
                WHERE status IN ('CLAIMED', 'DISPATCHED')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                  AND archived = 0;
                """,
                (now_iso,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["payload"] = json.loads(d["payload_json"])
                results.append(d)
            return results

    def reclaim_ambiguous_entry(
        self,
        outbox_id: str,
        retry: bool = True,
        error: str = "Ambiguous dispatch timeout without broker/channel ack",
    ) -> bool:
        """
        Safely reconciles an ambiguous dispatch entry.
        If retry=True and attempts < max_attempts: transitions to FAILED_RETRY.
        Otherwise transitions to terminal FAILED.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT status, attempts, max_attempts FROM alert_outbox WHERE outbox_id = ?;",
                (outbox_id,),
            ).fetchone()
            if not row or row["status"] not in ("CLAIMED", "DISPATCHED"):
                return False

            att = int(row["attempts"])
            max_att = int(row["max_attempts"])
            new_status = "FAILED_RETRY" if (retry and att < max_att) else "FAILED"

            conn.execute(
                """
                UPDATE alert_outbox
                SET status = ?,
                    last_error = ?,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE outbox_id = ?;
                """,
                (new_status, str(error), now_iso, outbox_id),
            )
            conn.commit()
            return True

    def archive_completed_outbox(self, older_than_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE alert_outbox
                SET archived = 1, archived_at = ?
                WHERE status IN ('ACKNOWLEDGED', 'FAILED')
                  AND archived = 0
                  AND updated_at < ?;
                """,
                (now_iso, cutoff),
            )
            conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        """Clears all records from alerts and alert_outbox tables."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM alert_outbox;")
            conn.execute("DELETE FROM alerts;")
            conn.commit()

    def get_alert(self, alert_id: str) -> Optional[dict[str, Any]]:
        """Retrieves single alert payload by alert_id."""
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM alerts WHERE alert_id = ? LIMIT 1;",
                (alert_id,),
            ).fetchone()
            if row:
                return json.loads(row["payload_json"])
            return None

    def get_alerts(
        self,
        session_date: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        active_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Queries stored alert payloads with optional filters."""
        query = "SELECT payload_json FROM alerts WHERE 1=1"
        params: list[Any] = []

        if session_date:
            query += " AND session_date = ?"
            params.append(session_date)

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())

        if status:
            query += " AND status = ?"
            params.append(status.upper())
        elif active_only:
            query += " AND status = 'ACTIVE'"

        query += " ORDER BY rowid DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [json.loads(r["payload_json"]) for r in rows]

    def update_alert_status(
        self,
        alert_id: str,
        status: str,
        ltp: Optional[float] = None,
    ) -> bool:
        """Updates alert status and optionally latest LTP."""
        now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM alerts WHERE alert_id = ? LIMIT 1;",
                (alert_id,),
            ).fetchone()
            if not row:
                return False

            payload = json.loads(row["payload_json"])
            payload["status"] = status
            if ltp is not None:
                payload["ltp"] = ltp
            if status == "INVALIDATED":
                payload["is_invalidated"] = True
            elif status == "TARGET_HIT":
                payload["is_target_hit"] = True
            elif status == "ARCHIVED":
                payload["is_archived"] = True

            payload_json = json.dumps(payload)

            if ltp is not None:
                conn.execute(
                    """
                    UPDATE alerts
                    SET status = ?, ltp = ?, updated_at = ?, payload_json = ?
                    WHERE alert_id = ?;
                    """,
                    (status, ltp, now_str, payload_json, alert_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE alerts
                    SET status = ?, updated_at = ?, payload_json = ?
                    WHERE alert_id = ?;
                    """,
                    (status, now_str, payload_json, alert_id),
                )
            conn.commit()
            return True

    def sync_from_legacy_json(self, json_path: Path) -> int:
        """Ingests legacy JSON alerts into SQLite database."""
        p = Path(json_path)
        if not p.exists():
            return 0
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            records = data if isinstance(data, list) else data.get("alerts", [])
            count = 0
            for r in records:
                if isinstance(r, dict) and r.get("alert_id"):
                    self.save_alert(r)
                    count += 1
            logger.info(f"[SQLiteAlertStore] Ingested {count} records from {json_path}")
            return count
        except Exception as e:
            logger.error(f"[SQLiteAlertStore] Error ingesting from {json_path}: {e}")
            return 0

    def export_to_legacy_json(self, json_path: Path, session_date: Optional[str] = None) -> int:
        """Exports SQLite alerts to legacy JSON file for backward compatibility."""
        p = Path(json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        alerts = self.get_alerts(session_date=session_date, limit=500)
        # Reverse to chronological order (oldest first)
        alerts.reverse()
        with open(p, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)
        return len(alerts)


# Module-level singleton
alert_sqlite_store = SQLiteAlertStore()
