"""
engine/security_audit.py
────────────────────────
Immutable, Cryptographically Chained Security & Financial Audit Trail.

Maintains an append-only audit ledger in SQLite with SHA-256 block hash chaining
to guarantee tamper evidence across all order submissions, mode changes, risk trips,
and financial reconciliations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from config.paths import app_data_path

DB_PATH = app_data_path("audit.db")


@dataclass
class AuditRecord:
    event_id: str
    timestamp: str
    event_type: str
    mode: str
    actor: str
    payload_json: str
    prev_hash: str
    record_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _init_audit_db():
    """Ensure audit database schema exists."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS security_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                mode TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON security_audit_log(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_event_type ON security_audit_log(event_type)")
        conn.commit()


def record_audit_event(
    event_type: str,
    mode: str = "SIMULATE",
    actor: str = "SYSTEM",
    details: Optional[dict[str, Any]] = None,
) -> AuditRecord:
    """
    Append an immutable, hash-chained audit record.

    Args:
        event_type: Category (e.g. ORDER_SUBMITTED, MODE_CHANGE, RISK_TRIP, RECONCILIATION)
        mode: Active operating mode (OBSERVE, SIMULATE, EXECUTE)
        actor: User ID, client ID, or system agent
        details: Event payload dictionary

    Returns:
        Persisted AuditRecord with cryptographic hash.
    """
    _init_audit_db()
    details_str = json.dumps(details or {}, sort_keys=True)
    event_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT record_hash FROM security_audit_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        prev_hash = row[0] if row else "GENESIS_BLOCK_00000000000000000000000000000000"

        # Cryptographic record hash
        raw_to_hash = f"{prev_hash}:{now_iso}:{event_type}:{mode}:{actor}:{details_str}"
        record_hash = hashlib.sha256(raw_to_hash.encode()).hexdigest()

        conn.execute(
            """
            INSERT INTO security_audit_log (
                event_id, timestamp, event_type, mode, actor, payload_json, prev_hash, record_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, now_iso, event_type, mode, actor, details_str, prev_hash, record_hash),
        )
        conn.commit()

    return AuditRecord(
        event_id=event_id,
        timestamp=now_iso,
        event_type=event_type,
        mode=mode,
        actor=actor,
        payload_json=details_str,
        prev_hash=prev_hash,
        record_hash=record_hash,
    )


def get_audit_logs(limit: int = 50, event_type: Optional[str] = None) -> list[dict[str, Any]]:
    """Retrieve recent audit logs."""
    _init_audit_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if event_type:
            cursor = conn.execute(
                "SELECT * FROM security_audit_log WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            cursor = conn.execute("SELECT * FROM security_audit_log ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def verify_audit_integrity() -> dict[str, Any]:
    """Verify hash chain integrity across all audit records."""
    _init_audit_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM security_audit_log ORDER BY id ASC")
        rows = cursor.fetchall()

    if not rows:
        return {"valid": True, "total_records": 0, "message": "No audit records logged yet."}

    prev_hash = "GENESIS_BLOCK_00000000000000000000000000000000"
    for r in rows:
        if r["prev_hash"] != prev_hash:
            return {
                "valid": False,
                "broken_at_id": r["id"],
                "broken_event_id": r["event_id"],
                "message": f"Tamper detected: Previous hash mismatch at record {r['id']}",
            }
        # Verify content hash
        raw_to_hash = f"{prev_hash}:{r['timestamp']}:{r['event_type']}:{r['mode']}:{r['actor']}:{r['payload_json']}"
        expected_hash = hashlib.sha256(raw_to_hash.encode()).hexdigest()
        if r["record_hash"] != expected_hash:
            return {
                "valid": False,
                "broken_at_id": r["id"],
                "broken_event_id": r["event_id"],
                "message": f"Tamper detected: Content signature mismatch at record {r['id']}",
            }
        prev_hash = r["record_hash"]

    return {"valid": True, "total_records": len(rows), "latest_hash": prev_hash}
