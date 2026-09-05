"""Bounded asynchronous raw-tick archive for local pilot diagnostics."""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.paths import app_data_path
from market.data_events import MarketDataEvent


def _retention_days() -> int:
    try:
        return min(30, max(7, int(os.environ.get("RAW_TICK_RETENTION_DAYS", "14"))))
    except ValueError:
        return 14


def _db_path() -> Path:
    path = app_data_path("market_data.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class TickArchive:
    """A bounded producer queue so storage never delays broker stream callbacks."""

    def __init__(self, max_queue_size: int = 10_000) -> None:
        self._queue: queue.Queue[MarketDataEvent] = queue.Queue(maxsize=max_queue_size)
        self._started = False
        self._lock = threading.Lock()
        self.dropped_events = 0

    def record(self, event: MarketDataEvent) -> None:
        self._ensure_started()
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events += 1

    def _ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            threading.Thread(target=self._run, daemon=True, name="market-tick-archive").start()

    def _init_db(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA cache_size=-32000")
            conn.execute("PRAGMA mmap_size=134217728")
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_market_ticks (
                received_at TEXT NOT NULL,
                canonical_instrument_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                data_state TEXT NOT NULL,
                last_price REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_ticks_retention ON raw_market_ticks(received_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_ticks_lookup ON raw_market_ticks(canonical_instrument_id, received_at)"
        )
        conn.commit()

    def _run(self) -> None:
        try:
            with sqlite3.connect(_db_path(), timeout=30.0) as conn:
                self._init_db(conn)
                last_prune_time = time.time()
                while True:
                    first = self._queue.get()
                    batch = [first]
                    while len(batch) < 250:
                        try:
                            batch.append(self._queue.get_nowait())
                        except queue.Empty:
                            break
                    conn.executemany(
                        """
                        INSERT INTO raw_market_ticks(
                            received_at, canonical_instrument_id, provider, provider_symbol,
                            source, data_state, last_price, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                event.received_at,
                                event.canonical_instrument_id,
                                event.provider,
                                event.provider_symbol,
                                event.source,
                                event.data_state,
                                event.last_price,
                                json.dumps(asdict(event), sort_keys=True, default=str),
                            )
                            for event in batch
                        ],
                    )

                    # Decoupled periodic prune (runs at most once every 30 minutes, not every 250 ticks)
                    now_ts = time.time()
                    if now_ts - last_prune_time > 1800.0:
                        last_prune_time = now_ts
                        cutoff = (
                            datetime.now(timezone.utc) - timedelta(days=_retention_days())
                        ).isoformat()
                        conn.execute("DELETE FROM raw_market_ticks WHERE received_at < ?", (cutoff,))
                        try:
                            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                        except Exception:
                            pass
                    conn.commit()
        except Exception:
            # Archival is diagnostic; the live path remains available if disk is full or locked.
            with self._lock:
                self._started = False


def prune_tick_archive(retention_days: Optional[int] = None, max_rows: int = 500_000) -> int:
    """Explicitly prune tick archive to retain within storage budget."""
    days = retention_days or _retention_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    deleted = 0
    try:
        with sqlite3.connect(_db_path(), timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            cur = conn.execute("DELETE FROM raw_market_ticks WHERE received_at < ?", (cutoff,))
            deleted += cur.rowcount

            # Enforce max rows ceiling if needed
            count_row = conn.execute("SELECT COUNT(*) FROM raw_market_ticks").fetchone()
            total = count_row[0] if count_row else 0
            if total > max_rows:
                overflow = total - max_rows
                cur2 = conn.execute(
                    "DELETE FROM raw_market_ticks WHERE rowid IN (SELECT rowid FROM raw_market_ticks ORDER BY received_at ASC LIMIT ?)",
                    (overflow,),
                )
                deleted += cur2.rowcount

            conn.commit()
            if deleted > 0:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        pass
    return deleted


tick_archive = TickArchive()
