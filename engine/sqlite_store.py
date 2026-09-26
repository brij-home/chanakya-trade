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
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("engine.sqlite_store")

IST = timezone(timedelta(hours=5, minutes=30))


def get_default_db_path() -> Path:
    """Returns canonical path to Chanakya ledger SQLite database."""
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "chanakya_ledger.db"


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
        # Enable WAL mode and performance pragmas
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_session_date ON alerts(session_date);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_alert_type ON alerts(alert_type);"
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
