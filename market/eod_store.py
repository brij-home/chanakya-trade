"""Versioned local EOD snapshots for reproducible research and backtests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.paths import app_data_path


def _db_path() -> Path:
    path = app_data_path("market_data.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _init_db() -> None:
    with sqlite3.connect(_db_path(), timeout=30.0) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eod_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                canonical_instrument_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_symbol TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                source_version TEXT NOT NULL,
                data_quality TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                checksum TEXT NOT NULL,
                UNIQUE(canonical_instrument_id, provider, as_of_date, checksum)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eod_snapshot_lookup "
            "ON eod_snapshots(canonical_instrument_id, as_of_date, retrieved_at DESC)"
        )
        conn.commit()


def _canonical_payload(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)


def save_eod_snapshot(
    *,
    canonical_instrument_id: str,
    provider: str,
    provider_symbol: str,
    as_of_date: str,
    rows: list[dict[str, Any]],
    data_quality: str = "VERIFIED",
    source_version: str = "v1",
) -> str:
    """Persist immutable normalized EOD rows and return their content ID."""
    _init_db()
    payload = _canonical_payload(rows)
    checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    snapshot_id = hashlib.sha256(
        f"{canonical_instrument_id}|{provider}|{as_of_date}|{checksum}".encode("utf-8")
    ).hexdigest()[:32]
    with sqlite3.connect(_db_path(), timeout=30.0) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO eod_snapshots (
                snapshot_id, canonical_instrument_id, provider, provider_symbol,
                as_of_date, retrieved_at, source_version, data_quality, payload_json, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                canonical_instrument_id,
                provider,
                provider_symbol,
                as_of_date,
                datetime.now(timezone.utc).isoformat(),
                source_version,
                data_quality,
                payload,
                checksum,
            ),
        )
        conn.commit()
    return snapshot_id


def load_eod_snapshot(
    canonical_instrument_id: str, *, as_of_date: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Load the latest matching snapshot without contacting any provider."""
    _init_db()
    sql = "SELECT * FROM eod_snapshots WHERE canonical_instrument_id = ?"
    params: list[str] = [canonical_instrument_id]
    if as_of_date:
        sql += " AND as_of_date = ?"
        params.append(as_of_date)
    sql += " ORDER BY retrieved_at DESC LIMIT 1"
    with sqlite3.connect(_db_path(), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    result = dict(row)
    result["rows"] = json.loads(result.pop("payload_json"))
    return result
