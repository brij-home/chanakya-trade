"""
engine/analysis_cache.py
────────────────────────
Persistent SQLite-backed cache for AI Multi-Agent analysis reports,
macro snapshots, and quant screening verdicts.

Eliminates redundant AI token consumption by caching syntheses and reusing them
intraday when stock price drift is within acceptable ATR/percentage boundaries.

Features:
- Configurable Time-To-Live (TTL, default 15 mins)
- Price-drift invalidation (invalidates if spot moved > 1.0%)
- Automatic size management (LRU pruning to stay within max storage limits)
- Token savings tracking
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB_PATH = Path.home() / ".trading_platform" / "analysis_cache.db"
DEFAULT_TTL_MINUTES = 15
DEFAULT_MAX_PRICE_DRIFT_PCT = 1.0
DEFAULT_MAX_RECORDS = 500


class AnalysisCache:
    """Persistent SQLite store for Multi-Agent AI analyses and market synthesis."""

    def __init__(self, db_path: Path | None = None, max_records: int = DEFAULT_MAX_RECORDS):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.max_records = max_records
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    spot_price REAL NOT NULL,
                    verdict TEXT,
                    confidence INTEGER,
                    report TEXT NOT NULL,
                    trade_plans TEXT,
                    analyst_signals TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    tokens_saved INTEGER DEFAULT 0,
                    hit_count INTEGER DEFAULT 0,
                    PRIMARY KEY (symbol, exchange, channel)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS macro_cache (
                    cache_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_expiry ON analysis_cache(expires_at)"
            )
            conn.commit()

    def get_analysis(
        self,
        symbol: str,
        exchange: str = "NSE",
        channel: str = "general",
        current_spot: float | None = None,
        max_price_drift_pct: float = DEFAULT_MAX_PRICE_DRIFT_PCT,
    ) -> dict[str, Any] | None:
        """
        Retrieve cached analysis if valid (not expired and price drift within threshold).
        """
        symbol = symbol.upper().strip()
        exchange = exchange.upper().strip()
        channel = channel.lower().strip()
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM analysis_cache 
                WHERE symbol = ? AND exchange = ? AND channel = ? AND expires_at > ?
                """,
                (symbol, exchange, channel, now),
            ).fetchone()

            if not row:
                return None

            cached_spot = float(row["spot_price"])

            # Check price drift if current_spot is provided
            if current_spot and current_spot > 0 and cached_spot > 0:
                drift_pct = abs(current_spot - cached_spot) / cached_spot * 100.0
                if drift_pct > max_price_drift_pct:
                    # Invalidate due to significant intraday price deviation
                    return None

            # Increment hit count & track estimated token savings (average ~4500 tokens per multi-agent run)
            conn.execute(
                """
                UPDATE analysis_cache 
                SET hit_count = hit_count + 1, tokens_saved = tokens_saved + 4500 
                WHERE symbol = ? AND exchange = ? AND channel = ?
                """,
                (symbol, exchange, channel),
            )
            conn.commit()

            created_dt = datetime.fromisoformat(row["created_at"])
            age_seconds = int((datetime.now() - created_dt).total_seconds())

            try:
                trade_plans = json.loads(row["trade_plans"]) if row["trade_plans"] else {}
            except Exception:
                trade_plans = {}

            try:
                analyst_signals = json.loads(row["analyst_signals"]) if row["analyst_signals"] else []
            except Exception:
                analyst_signals = []

            return {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "channel": row["channel"],
                "spot_price": cached_spot,
                "verdict": row["verdict"],
                "confidence": row["confidence"],
                "report": row["report"],
                "trade_plans": trade_plans,
                "analyst_signals": analyst_signals,
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "age_seconds": age_seconds,
                "hit_count": row["hit_count"] + 1,
                "is_cached": True,
            }

    def save_analysis(
        self,
        symbol: str,
        exchange: str = "NSE",
        channel: str = "general",
        spot_price: float = 0.0,
        verdict: str = "",
        confidence: int = 50,
        report: str = "",
        trade_plans: dict[str, Any] | None = None,
        analyst_signals: list[dict[str, Any]] | None = None,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> None:
        """Save completed multi-agent analysis to cache with TTL."""
        symbol = symbol.upper().strip()
        exchange = exchange.upper().strip()
        channel = channel.lower().strip()
        now = datetime.now()
        expires = now + timedelta(minutes=ttl_minutes)

        trade_plans_json = json.dumps(trade_plans or {}, default=str)
        analyst_signals_json = json.dumps(analyst_signals or [], default=str)

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_cache (
                    symbol, exchange, channel, spot_price, verdict, confidence,
                    report, trade_plans, analyst_signals, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    exchange,
                    channel,
                    spot_price,
                    verdict,
                    confidence,
                    report,
                    trade_plans_json,
                    analyst_signals_json,
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )
            conn.commit()

        # Enforce storage limits
        self.prune()

    def get_macro(self, key: str, max_age_seconds: int | None = None) -> Any | None:
        """Get cached macro or flow data if not expired and within max_age_seconds."""
        now_dt = datetime.now()
        now = now_dt.isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT data_json, created_at FROM macro_cache WHERE cache_key = ? AND expires_at > ?",
                (key, now),
            ).fetchone()
            if row:
                if max_age_seconds is not None and max_age_seconds > 0:
                    try:
                        created_dt = datetime.fromisoformat(row["created_at"])
                        if (now_dt - created_dt).total_seconds() > max_age_seconds:
                            return None
                    except Exception:
                        pass
                try:
                    return json.loads(row["data_json"])
                except Exception:
                    return None
        return None

    def save_macro(self, key: str, data: Any, ttl_minutes: int = 30) -> None:
        """Save macro or flow snapshot with TTL."""
        now = datetime.now()
        expires = now + timedelta(minutes=ttl_minutes)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO macro_cache (cache_key, data_json, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, json.dumps(data, default=str), now.isoformat(), expires.isoformat()),
            )
            conn.commit()

    def invalidate(self, symbol: str | None = None, exchange: str = "NSE") -> int:
        """Invalidate cache for a specific symbol or all entries."""
        with self._get_conn() as conn:
            if symbol:
                cur = conn.execute(
                    "DELETE FROM analysis_cache WHERE symbol = ? AND exchange = ?",
                    (symbol.upper().strip(), exchange.upper().strip()),
                )
            else:
                cur = conn.execute("DELETE FROM analysis_cache")
                conn.execute("DELETE FROM macro_cache")
            conn.commit()
            return cur.rowcount

    def prune(self) -> int:
        """
        Prune expired entries and enforce MAX_RECORDS limit.
        """
        now = datetime.now().isoformat()
        deleted = 0
        with self._get_conn() as conn:
            # 1. Delete expired
            cur = conn.execute("DELETE FROM analysis_cache WHERE expires_at <= ?", (now,))
            deleted += cur.rowcount
            conn.execute("DELETE FROM macro_cache WHERE expires_at <= ?", (now,))

            # 2. Enforce max records
            count_row = conn.execute("SELECT COUNT(*) as c FROM analysis_cache").fetchone()
            total = count_row["c"] if count_row else 0
            if total > self.max_records:
                overflow = total - self.max_records
                cur2 = conn.execute(
                    """
                    DELETE FROM analysis_cache 
                    WHERE rowid IN (
                        SELECT rowid FROM analysis_cache 
                        ORDER BY created_at ASC LIMIT ?
                    )
                    """,
                    (overflow,),
                )
                deleted += cur2.rowcount
            conn.commit()
        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Return cache health, storage size, and total estimated AI tokens saved."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT 
                    COUNT(*) as total_entries,
                    SUM(hit_count) as total_hits,
                    SUM(tokens_saved) as total_tokens_saved
                FROM analysis_cache
                """
            ).fetchone()

            db_size_kb = 0
            if self.db_path.exists():
                db_size_kb = round(self.db_path.stat().st_size / 1024, 2)

            return {
                "total_cached_analyses": row["total_entries"] or 0,
                "total_cache_hits": row["total_hits"] or 0,
                "total_tokens_saved": row["total_tokens_saved"] or 0,
                "db_size_kb": db_size_kb,
                "db_path": str(self.db_path),
            }


# Global singleton instance
analysis_cache = AnalysisCache()


def cache_get(key: str, namespace: str = "generic", max_age_seconds: int = 600) -> Any | None:
    """Retrieve cached JSON payload by key and namespace with max_age_seconds validation."""
    return analysis_cache.get_macro(f"{namespace}:{key}", max_age_seconds=max_age_seconds)


def cache_set(key: str, data: Any, namespace: str = "generic", ttl_minutes: int = 15) -> None:
    """Save JSON payload with namespace and TTL."""
    analysis_cache.save_macro(f"{namespace}:{key}", data, ttl_minutes=ttl_minutes)
