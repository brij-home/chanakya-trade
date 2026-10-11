"""
market/single_flight_cache.py
─────────────────────────────
High-Performance Single-Flight Mutex & Stale-While-Revalidate (SWR) Cache.

Key Features & Guarantees:
  1. Single-Flight Coalescing (Thundering Herd Protection):
     When multiple concurrent threads or async tasks request the same missing/expired key,
     only ONE caller executes the expensive external operation (broker API, scraping, heavy calculation).
     All other callers await the exact same in-flight result without duplicate requests.
  2. Stale-While-Revalidate (SWR):
     - Within soft_ttl: Returns instant cached data (<0.01ms).
     - Between soft_ttl and hard_ttl: Returns cached data immediately (zero latency),
       while launching a non-blocking background revalidation to refresh the cache.
     - Past hard_ttl: Blocks until a fresh value is fetched via single-flight mutex.
  3. Thread-Safe & Async-Compatible:
     Supports both synchronous call paths (`get_or_fetch_sync`) and async coroutines (`get_or_fetch_async`).
  4. Memory-Bounded:
     Maintains bounded LRU/TTL size to prevent memory leaks during long-running sessions.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    created_at: float


class SingleFlightCache(Generic[T]):
    """
    Thread-safe, async-friendly single-flight SWR cache.
    """

    def __init__(
        self,
        soft_ttl: float = 60.0,
        hard_ttl: float = 300.0,
        max_size: int = 1000,
        name: str = "cache",
    ) -> None:
        self.soft_ttl = float(soft_ttl)
        self.hard_ttl = float(hard_ttl)
        self.max_size = int(max_size)
        self.name = name

        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _CacheEntry[T]] = OrderedDict()

        # In-flight coalescing structures
        self._sync_flights: dict[str, tuple[threading.Event, list[Any]]] = {}
        self._async_flights: dict[str, asyncio.Future] = {}

        # Observability metrics
        self._hits = 0
        self._swr_hits = 0
        self._misses = 0
        self._coalesced_waits = 0

    def get_or_fetch_sync(
        self,
        key: str,
        fetcher: Callable[[], T],
        force_refresh: bool = False,
    ) -> T:
        """
        Synchronously get from cache or coalesce concurrent fetchers.
        """
        now = time.time()

        if not force_refresh:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    age = now - entry.created_at
                    if age <= self.soft_ttl:
                        self._hits += 1
                        self._entries.move_to_end(key)
                        return entry.value
                    elif age <= self.hard_ttl:
                        self._swr_hits += 1
                        self._entries.move_to_end(key)
                        # Trigger background revalidation if not already in flight
                        self._maybe_trigger_bg_revalidation_sync(key, fetcher)
                        return entry.value

        # Miss or hard expired -> Single flight coordination
        evt = None
        box: list[Any] = []
        is_leader = False

        with self._lock:
            if key in self._sync_flights:
                evt, box = self._sync_flights[key]
                self._coalesced_waits += 1
            else:
                evt = threading.Event()
                box = [None, None]  # [result, exception]
                self._sync_flights[key] = (evt, box)
                is_leader = True
                self._misses += 1

        if not is_leader:
            # Follower thread waits for leader to finish
            evt.wait()
            if box[1] is not None:
                raise box[1]
            return box[0]

        # Leader thread executes fetcher
        try:
            val = fetcher()
            box[0] = val
            with self._lock:
                self._put_locked(key, val)
            return val
        except Exception as exc:
            box[1] = exc
            logger.warning(f"[{self.name}] Fetch error for key '{key}': {exc}")
            raise
        finally:
            with self._lock:
                self._sync_flights.pop(key, None)
            evt.set()

    def _maybe_trigger_bg_revalidation_sync(
        self,
        key: str,
        fetcher: Callable[[], T],
    ) -> None:
        """Launch background worker to refresh stale SWR entry if not already in-flight."""
        if key in self._sync_flights:
            return

        def _bg_task():
            evt = threading.Event()
            box = [None, None]
            with self._lock:
                if key in self._sync_flights:
                    return
                self._sync_flights[key] = (evt, box)

            try:
                val = fetcher()
                box[0] = val
                with self._lock:
                    self._put_locked(key, val)
            except Exception as e:
                box[1] = e
                logger.debug(f"[{self.name}] SWR bg revalidation error for key '{key}': {e}")
            finally:
                with self._lock:
                    self._sync_flights.pop(key, None)
                evt.set()

        t = threading.Thread(
            target=_bg_task,
            daemon=True,
            name=f"SWR-{self.name}-{key[:16]}",
        )
        t.start()

    async def get_or_fetch_async(
        self,
        key: str,
        coro_fetcher: Callable[[], Coroutine[Any, Any, T]],
        force_refresh: bool = False,
    ) -> T:
        """
        Asynchronously get from cache or coalesce concurrent coroutines.
        """
        now = time.time()

        if not force_refresh:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    age = now - entry.created_at
                    if age <= self.soft_ttl:
                        self._hits += 1
                        self._entries.move_to_end(key)
                        return entry.value
                    elif age <= self.hard_ttl:
                        self._swr_hits += 1
                        self._entries.move_to_end(key)
                        self._maybe_trigger_bg_revalidation_async(key, coro_fetcher)
                        return entry.value

        loop = asyncio.get_running_loop()
        future: Optional[asyncio.Future] = None
        is_leader = False

        with self._lock:
            if key in self._async_flights:
                future = self._async_flights[key]
                self._coalesced_waits += 1
            else:
                future = loop.create_future()
                self._async_flights[key] = future
                is_leader = True
                self._misses += 1

        if not is_leader:
            return await future

        try:
            val = await coro_fetcher()
            with self._lock:
                self._put_locked(key, val)
            if not future.done():
                future.set_result(val)
            return val
        except Exception as exc:
            logger.warning(f"[{self.name}] Async fetch error for key '{key}': {exc}")
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._async_flights.pop(key, None)

    def _maybe_trigger_bg_revalidation_async(
        self,
        key: str,
        coro_fetcher: Callable[[], Coroutine[Any, Any, T]],
    ) -> None:
        """Launch asyncio background task to refresh stale SWR entry."""
        if key in self._async_flights:
            return

        async def _bg_coro():
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            with self._lock:
                if key in self._async_flights:
                    return
                self._async_flights[key] = future

            try:
                val = await coro_fetcher()
                with self._lock:
                    self._put_locked(key, val)
                if not future.done():
                    future.set_result(val)
            except Exception as e:
                logger.debug(f"[{self.name}] Async SWR bg revalidation error: {e}")
                if not future.done():
                    future.set_exception(e)
            finally:
                with self._lock:
                    self._async_flights.pop(key, None)

        try:
            asyncio.create_task(_bg_coro())
        except RuntimeError:
            pass

    def _put_locked(self, key: str, value: T) -> None:
        """Store value with LRU eviction under self._lock."""
        self._entries[key] = _CacheEntry(value=value, created_at=time.time())
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_size:
            self._entries.popitem(last=False)

    def get(self, key: str) -> Optional[T]:
        """Direct cache read without fetching or SWR."""
        with self._lock:
            entry = self._entries.get(key)
            if entry and (time.time() - entry.created_at <= self.hard_ttl):
                return entry.value
        return None

    def put(self, key: str, value: T) -> None:
        """Manually put into cache."""
        with self._lock:
            self._put_locked(key, value)

    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate specific key or entire cache."""
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)

    def stats(self) -> dict[str, Any]:
        """Return cache performance statistics."""
        with self._lock:
            return {
                "name": self.name,
                "size": len(self._entries),
                "max_size": self.max_size,
                "hits": self._hits,
                "swr_hits": self._swr_hits,
                "misses": self._misses,
                "coalesced_waits": self._coalesced_waits,
                "active_sync_flights": len(self._sync_flights),
                "active_async_flights": len(self._async_flights),
            }
