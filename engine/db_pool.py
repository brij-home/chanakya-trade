"""
engine/db_pool.py
─────────────────
Thread-Safe Bounded SQLite Connection Pool for High-Frequency Read/Cache DBs.

Provides LIFO connection reuse to maximize CPU cache and SQLite page-cache warmness,
executes PRAGMAs once upon connection creation, and ensures deterministic teardown.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger("chanakya.db_pool")


class SQLiteConnectionPool:
    """
    Thread-safe bounded SQLite connection pool.
    
    Attributes:
        db_path: Filesystem path to the SQLite database.
        max_conns: Maximum number of persistent connections to create.
        timeout: Lock wait timeout in seconds.
    """

    def __init__(
        self,
        db_path: str,
        max_conns: int = 5,
        timeout: float = 30.0,
        page_cache_kb: int = 32000,
        mmap_size: int = 134217728,
    ) -> None:
        self.db_path = str(db_path)
        self.max_conns = max(1, max_conns)
        self.timeout = timeout
        self.page_cache_kb = page_cache_kb
        self.mmap_size = mmap_size

        self._pool: queue.LifoQueue[sqlite3.Connection] = queue.LifoQueue(maxsize=self.max_conns)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with tuned institutional PRAGMAs."""
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode by default; explicit transactions when needed
        )
        conn.row_factory = sqlite3.Row

        # Execute institutional performance PRAGMAs once upon connection creation
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
            conn.execute(f"PRAGMA cache_size=-{self.page_cache_kb}")
            conn.execute(f"PRAGMA mmap_size={self.mmap_size}")
        except Exception as exc:
            logger.debug("PRAGMA configuration note for %s: %s", self.db_path, exc)

        return conn

    @contextmanager
    def acquire(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Check out a connection from the pool, yielding it to the caller,
        and automatically returning it to the pool upon block exit.
        """
        if self._closed:
            raise RuntimeError(f"SQLiteConnectionPool for {self.db_path} is closed.")

        conn: sqlite3.Connection | None = None
        created_new = False

        # 1. Try to get an idle connection from the LIFO pool without blocking
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            # 2. If no idle connection, check if we can spawn a new one under max_conns
            with self._lock:
                if self._closed:
                    raise RuntimeError(f"SQLiteConnectionPool for {self.db_path} is closed.")
                if self._created < self.max_conns:
                    conn = self._create_connection()
                    self._created += 1
                    created_new = True

            # 3. If pool is saturated at max_conns, wait for an available connection
            if not created_new:
                try:
                    conn = self._pool.get(block=True, timeout=self.timeout)
                except queue.Empty:
                    raise TimeoutError(
                        f"SQLiteConnectionPool timed out after {self.timeout}s waiting for {self.db_path}"
                    )

        try:
            yield conn
        finally:
            if conn is not None:
                if self._closed:
                    try:
                        conn.close()
                    except Exception:
                        pass
                else:
                    try:
                        # Return to pool
                        self._pool.put_nowait(conn)
                    except queue.Full:
                        # Safety fallback if pool is full
                        try:
                            conn.close()
                        except Exception:
                            pass
                        with self._lock:
                            self._created = max(0, self._created - 1)

    def close(self) -> None:
        """Close all connections in the pool and mark the pool as closed."""
        with self._lock:
            self._closed = True
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._created = 0
