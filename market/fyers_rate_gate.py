"""
market/fyers_rate_gate.py
─────────────────────────
Unified prioritized sliding-window rate gate and budget governor for Fyers API v3.

Fyers API Hard Constraints:
  - Maximum 10 requests / second
  - Maximum 200 requests / minute (3 strikes in 1 day = account blocked for the entire day)

ChanakyaTrade Safe Operating Parameters:
  - Hard cap: 8.0 req/sec (20% safety margin)
  - Hard cap: 160.0 req/min (20% safety margin)

Priority Tiers (Lower value = Higher priority):
  - Tier 0: ORDER           (Execution, cancel, modify; never starved by queries)
  - Tier 1: URGENT_QUOTE    (In-flight position stop-loss/take-profit guardian)
  - Tier 2: SCANNER_QUOTE   (Batch quotes for market scanners & radar)
  - Tier 3: DEPTH_CHAIN     (Market depth L2, options chains)
  - Tier 4: HISTORICAL      (Candle historical backfill, pre-market/post-market prefetch)
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections import deque
from enum import IntEnum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FyersCallCategory(IntEnum):
    """Priority tiers for Fyers API calls. Lower numeric value = higher priority."""

    ORDER = 0
    URGENT_QUOTE = 1
    SCANNER_QUOTE = 2
    DEPTH_CHAIN = 3
    HISTORICAL = 4


class UnifiedFyersRateGate:
    """
    Thread-safe prioritized rate limiter and budget governor for Fyers API calls.
    Guarantees that order execution is never blocked behind high-volume quote or history fetches.
    """

    def __init__(
        self,
        max_per_sec: float = 8.0,
        max_per_min: float = 160.0,
    ) -> None:
        self._max_per_sec = float(max_per_sec)
        self._max_per_min = float(max_per_min)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        # Sliding window timestamp ring buffers: (timestamp, category)
        self._sliding_window: deque[tuple[float, FyersCallCategory]] = deque()

        # Priority queue for threads waiting on tokens:
        # Elements are: (priority, tie_breaker, category, threading.Event())
        self._waiters: list[tuple[int, int, FyersCallCategory, threading.Event]] = []
        self._counter = itertools.count()

        # Telemetry and diagnostics counters
        self._total_requests: dict[FyersCallCategory, int] = {c: 0 for c in FyersCallCategory}
        self._total_throttled: int = 0
        self._total_throttle_seconds: float = 0.0
        self._peak_minute_count: int = 0
        self._started_at: float = time.time()

    def _purge_stale_timestamps(self, now: float) -> None:
        """Evict records older than 60.0 seconds from the sliding window."""
        cutoff = now - 60.0
        while self._sliding_window and self._sliding_window[0][0] < cutoff:
            self._sliding_window.popleft()

    def _calculate_sleep_needed(self, now: float) -> float:
        """Calculate minimum sleep needed to satisfy 1-sec and 60-sec caps."""
        # Check 1-second window
        sec_cutoff = now - 1.0
        recent_sec = [t for t, _ in self._sliding_window if t >= sec_cutoff]
        sleep_sec = 0.0
        if len(recent_sec) >= self._max_per_sec:
            # Must wait until oldest entry in current 1s window ages out
            oldest_in_sec = recent_sec[0]
            sleep_sec = max(sleep_sec, 1.0 - (now - oldest_in_sec) + 0.005)

        # Check 60-second window
        if len(self._sliding_window) >= self._max_per_min:
            oldest_in_min = self._sliding_window[0][0]
            sleep_sec = max(sleep_sec, 60.0 - (now - oldest_in_min) + 0.02)

        return sleep_sec

    def acquire(
        self,
        category: FyersCallCategory = FyersCallCategory.ORDER,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Acquire permission to dispatch a Fyers API request.
        Blocks until capacity is available under sliding window constraints.
        Higher priority categories jump ahead in the wait queue.
        Returns True if acquired, False if timed out.
        """
        event = threading.Event()
        start_wait = time.time()
        tie_breaker = next(self._counter)
        waiter_entry = (int(category), tie_breaker, category, event)

        with self._lock:
            # If no one is waiting and there is immediate capacity, grant immediately
            now = time.time()
            self._purge_stale_timestamps(now)
            sleep_needed = self._calculate_sleep_needed(now)

            if not self._waiters and sleep_needed <= 0.0:
                self._sliding_window.append((now, category))
                self._total_requests[category] += 1
                if len(self._sliding_window) > self._peak_minute_count:
                    self._peak_minute_count = len(self._sliding_window)
                return True

            # Otherwise, register in the prioritized wait queue
            heapq.heappush(self._waiters, waiter_entry)
            self._total_throttled += 1

        # Wait loop until this thread is at the top of the queue and token is available
        deadline = (start_wait + timeout) if timeout is not None else None

        while True:
            with self._lock:
                now = time.time()
                self._purge_stale_timestamps(now)

                # Check if we are at the top of the priority queue
                if self._waiters and self._waiters[0][1] == tie_breaker:
                    sleep_needed = self._calculate_sleep_needed(now)
                    if sleep_needed <= 0.0:
                        # Success: pop ourselves and record consumption
                        heapq.heappop(self._waiters)
                        self._sliding_window.append((now, category))
                        self._total_requests[category] += 1
                        elapsed_wait = now - start_wait
                        self._total_throttle_seconds += elapsed_wait
                        if len(self._sliding_window) > self._peak_minute_count:
                            self._peak_minute_count = len(self._sliding_window)
                        # Wake the next waiter if queue not empty
                        if self._waiters:
                            self._waiters[0][3].set()
                        return True
                    else:
                        sleep_to_use = sleep_needed
                else:
                    # We are not at the head of the queue; wait for head to finish or next slot
                    sleep_to_use = 0.05

            # Handle timeout check
            now = time.time()
            if deadline is not None:
                remaining = deadline - now
                if remaining <= 0:
                    with self._lock:
                        # Remove ourselves from waiters if still present
                        self._waiters = [w for w in self._waiters if w[1] != tie_breaker]
                        heapq.heapify(self._waiters)
                        if self._waiters:
                            self._waiters[0][3].set()
                    return False
                sleep_to_use = min(sleep_to_use, remaining)

            # Wait on event or sleep
            event.wait(timeout=sleep_to_use)
            event.clear()

    def get_diagnostics(self) -> dict[str, Any]:
        """Return real-time usage telemetry, remaining capacity, and diagnostic stats."""
        with self._lock:
            now = time.time()
            self._purge_stale_timestamps(now)
            sec_cutoff = now - 1.0

            reqs_last_sec = sum(1 for t, _ in self._sliding_window if t >= sec_cutoff)
            reqs_last_min = len(self._sliding_window)

            by_category_last_min: dict[str, int] = {c.name: 0 for c in FyersCallCategory}
            for _, cat in self._sliding_window:
                by_category_last_min[cat.name] += 1

            by_category_total: dict[str, int] = {
                cat.name: cnt for cat, cnt in self._total_requests.items()
            }

            remaining_sec_tokens = max(0.0, self._max_per_sec - reqs_last_sec)
            remaining_min_tokens = max(0.0, self._max_per_min - reqs_last_min)
            utilization_pct = round((reqs_last_min / self._max_per_min) * 100.0, 1)

            waiting_by_tier: dict[str, int] = {c.name: 0 for c in FyersCallCategory}
            for _, _, cat, _ in self._waiters:
                waiting_by_tier[cat.name] += 1

            return {
                "max_per_sec": self._max_per_sec,
                "max_per_min": self._max_per_min,
                "requests_last_sec": reqs_last_sec,
                "requests_last_min": reqs_last_min,
                "remaining_min_budget": remaining_min_tokens,
                "remaining_sec_budget": remaining_sec_tokens,
                "utilization_pct": utilization_pct,
                "peak_minute_recorded": self._peak_minute_count,
                "total_throttled_calls": self._total_throttled,
                "total_throttle_seconds": round(self._total_throttle_seconds, 3),
                "active_waiters_count": len(self._waiters),
                "waiters_by_tier": waiting_by_tier,
                "requests_last_min_by_tier": by_category_last_min,
                "total_requests_by_tier": by_category_total,
                "uptime_seconds": round(now - self._started_at, 1),
                "status": "HEALTHY"
                if utilization_pct < 85.0
                else ("WARNING" if utilization_pct < 95.0 else "SATURATED"),
            }


# Global singleton instance
fyers_rate_gate = UnifiedFyersRateGate()


def get_fyers_rate_gate() -> UnifiedFyersRateGate:
    """Return the global unified rate gate singleton."""
    return fyers_rate_gate
