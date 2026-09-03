"""Dated, provider-verified contract metadata for executable derivatives."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.paths import app_data_path

# Option symbols conventionally end in a numeric strike followed by CE/PE.
# Requiring the strike avoids misclassifying cash equities such as RELIANCE.
_DERIVATIVE_PATTERN = re.compile(r"\d(?:CE|PE)$", re.IGNORECASE)


def is_derivative_query(symbol: str) -> bool:
    normalized = (symbol or "").upper()
    return normalized.startswith(("NFO:", "BFO:")) or bool(_DERIVATIVE_PATTERN.search(normalized))


def _db_path() -> Path:
    path = app_data_path("instrument_master.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _init_db() -> None:
    with sqlite3.connect(_db_path(), timeout=30.0) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS verified_contracts (
                lookup_symbol TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_symbol TEXT NOT NULL,
                provider_token TEXT NOT NULL,
                exchange TEXT NOT NULL,
                segment TEXT NOT NULL,
                lot_size INTEGER NOT NULL,
                tick_size REAL NOT NULL,
                expiry_date TEXT,
                verified_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def upsert_verified_contract(
    *,
    lookup_symbol: str,
    provider: str,
    provider_symbol: str,
    provider_token: str,
    exchange: str,
    segment: str,
    lot_size: int,
    tick_size: float,
    expiry_date: Optional[str] = None,
) -> None:
    """Store actual contract terms obtained from a broker instrument response."""
    if not lookup_symbol or not provider_token or lot_size <= 0 or tick_size <= 0:
        raise ValueError(
            "Verified contract requires symbol, token, positive lot size and tick size"
        )
    _init_db()
    with sqlite3.connect(_db_path(), timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO verified_contracts(
                lookup_symbol, provider, provider_symbol, provider_token, exchange,
                segment, lot_size, tick_size, expiry_date, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lookup_symbol) DO UPDATE SET
                provider=excluded.provider, provider_symbol=excluded.provider_symbol,
                provider_token=excluded.provider_token, exchange=excluded.exchange,
                segment=excluded.segment, lot_size=excluded.lot_size,
                tick_size=excluded.tick_size, expiry_date=excluded.expiry_date,
                verified_at=excluded.verified_at
            """,
            (
                lookup_symbol.upper(),
                provider.lower(),
                provider_symbol,
                provider_token,
                exchange.upper(),
                segment.upper(),
                int(lot_size),
                float(tick_size),
                expiry_date,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_verified_contract(symbol: str) -> Optional[dict[str, Any]]:
    """Return recently persisted contract metadata; never synthesize an F&O lot."""
    _init_db()
    with sqlite3.connect(_db_path(), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM verified_contracts WHERE lookup_symbol = ?", ((symbol or "").upper(),)
        ).fetchone()
    return dict(row) if row else None
