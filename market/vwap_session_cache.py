"""
market/vwap_session_cache.py
────────────────────────────
Persistent intraday VWAP session cache.

Addresses Fyers rate limit exhaustion caused by recursive OHLCV history queries
on every quote enrichment cycle.

Features:
  - Disk-backed persistence in ~/.trading_platform/cache/vwap_session_{YYYYMMDD}.json.
  - Instant warm restoration on server restart / service update.
  - Configurable TTL (default: 30 minutes during active market hours, permanent for closed sessions).
  - In-flight single-flight deduplication: concurrent requests for the same symbol
    share a single calculation rather than firing parallel history requests.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _get_cache_dir() -> Path:
    base = Path(os.environ.get("TRADING_PLATFORM_DATA") or (Path.home() / ".trading_platform"))
    cache_dir = base / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


class VwapSessionCache:
    """
    Session-level cache for computed VWAPs that survives service restarts.
    """

    def __init__(self, ttl_seconds: float = 1800.0) -> None:
        self._ttl_seconds = float(ttl_seconds)  # 30 minutes default
        self._lock = threading.Lock()
        self._in_flight_locks: dict[str, threading.Lock] = {}
        self._in_flight_master_lock = threading.Lock()
        self._disk_lock = threading.Lock()

        # In-memory store: clean_symbol -> (computed_ts, vwap_value)
        self._memory_cache: dict[str, tuple[float, float]] = {}
        self._current_date: str = datetime.now(IST).strftime("%Y%m%d")
        self._load_from_disk()

    def _get_cache_file(self, date_str: str) -> Path:
        return _get_cache_dir() / f"vwap_session_{date_str}.json"

    def _load_from_disk(self) -> None:
        """Restore cached session VWAPs from disk on startup/restart."""
        today = datetime.now(IST).strftime("%Y%m%d")
        self._current_date = today
        cache_file = self._get_cache_file(today)
        if not cache_file.exists():
            return

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            with self._lock:
                for sym, info in data.items():
                    val = float(info.get("vwap", 0.0) or 0.0)
                    ts = float(info.get("timestamp", now) or now)
                    if val > 0:
                        self._memory_cache[sym.upper()] = (ts, val)
            logger.info(
                f"[VwapCache] Restored {len(self._memory_cache)} session VWAPs from {cache_file.name}"
            )
        except Exception as exc:
            logger.warning(f"[VwapCache] Could not load disk cache {cache_file}: {exc}", exc_info=True)

    def _save_to_disk(self) -> None:
        """Persist in-memory cache to disk with thread-safe atomic write and Windows retry."""
        today = self._current_date
        cache_file = self._get_cache_file(today)
        with self._disk_lock:
            try:
                with self._lock:
                    payload = {
                        sym: {"vwap": val, "timestamp": ts}
                        for sym, (ts, val) in self._memory_cache.items()
                    }
                temp_file = cache_file.with_name(
                    f"{cache_file.name}.tmp.{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"
                )
                try:
                    with open(temp_file, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2)
                    for attempt in range(4):
                        try:
                            os.replace(temp_file, cache_file)
                            break
                        except PermissionError:
                            if attempt == 3:
                                with open(cache_file, "w", encoding="utf-8") as f:
                                    json.dump(payload, f, indent=2)
                            else:
                                time.sleep(0.04)
                finally:
                    if temp_file.exists():
                        try:
                            temp_file.unlink(missing_ok=True)
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning(f"[VwapCache] Failed to save disk cache {cache_file}: {exc}", exc_info=True)

    def _get_in_flight_lock(self, symbol: str) -> threading.Lock:
        with self._in_flight_master_lock:
            if symbol not in self._in_flight_locks:
                self._in_flight_locks[symbol] = threading.Lock()
            return self._in_flight_locks[symbol]

    def get(self, symbol: str) -> Optional[float]:
        """
        Get cached VWAP if fresh.
        Returns None if expired or not found.
        """
        clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
        now = time.time()
        with self._lock:
            entry = self._memory_cache.get(clean)
            if entry:
                computed_ts, val = entry
                # If market is closed (after 15:30 IST), today's VWAP is final and never expires
                now_ist = datetime.now(IST)
                market_closed = (now_ist.hour > 15) or (now_ist.hour == 15 and now_ist.minute >= 30)
                if market_closed or (now - computed_ts < self._ttl_seconds):
                    return val if val > 0 else None
        return None

    def put(self, symbol: str, vwap_val: float) -> None:
        """Store computed VWAP in memory and schedule disk persistence."""
        if vwap_val <= 0:
            return
        clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
        now = time.time()
        with self._lock:
            self._memory_cache[clean] = (now, float(vwap_val))
        self._save_to_disk()

    def get_or_compute(
        self,
        symbol: str,
        compute_fn,
        exchange: str = "NSE",
    ) -> Optional[float]:
        """
        Get cached VWAP or compute using single-flight deduplication.
        Prevents multiple threads from simultaneously computing VWAP for the same symbol.
        """
        cached = self.get(symbol)
        if cached is not None:
            return cached

        clean = symbol.upper().replace("NSE:", "").replace("BSE:", "").strip()
        lock = self._get_in_flight_lock(clean)

        # Single-flight gate
        with lock:
            # Re-check cache after acquiring lock
            cached = self.get(clean)
            if cached is not None:
                return cached

            # Compute via caller function
            try:
                computed_val = compute_fn(clean, exchange=exchange)
                if computed_val and computed_val > 0:
                    self.put(clean, computed_val)
                    return computed_val
            except Exception as exc:
                logger.warning(f"[VwapCache] Error computing VWAP for {clean}: {exc}", exc_info=True)

        return None

    def clear(self) -> None:
        """Purge memory cache and disk cache for testing and session reset."""
        with self._lock:
            self._memory_cache.clear()
        with self._disk_lock:
            today = self._current_date
            cache_file = self._get_cache_file(today)
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except Exception:
                    pass


# Global singleton
vwap_session_cache = VwapSessionCache(ttl_seconds=1800.0)


def get_vwap_session_cache() -> VwapSessionCache:
    return vwap_session_cache
