"""
market/flattrade_rate_gate.py
─────────────────────────────
Unified prioritized sliding-window rate gate and budget governor for Flattrade Pi Connect (Noren API).

Flattrade (Pi Connect) Constraints:
  - Non-order / Quotes API: Max 10 requests / second (Safe operating cap: 8.0 req/s)
  - Order API: Max 10 requests / second (Safe operating cap: 8.0 req/s)
  - Historical Data (TPS Series): Max 1 request / second (Strict pacing enforced)
  - WebSocket: Up to 30 symbols per subscription batch, with 40ms pacing

Priority Tiers (Lower value = Higher priority):
  - Tier 0: ORDER           (Execution, modify, cancel — never starved by scans)
  - Tier 1: URGENT_QUOTE    (In-flight position stop-loss / take-profit monitoring)
  - Tier 2: SCANNER_QUOTE   (Watchlist & scanner batch queries)
  - Tier 3: DEPTH           (5-level market depth)
  - Tier 4: HISTORICAL      (Historical candle chunking — strictly paced at 1.0 req/s)
"""

from __future__ import annotations

import heapq
import itertools
import logging
import os
import threading
import time
from collections import deque
from enum import IntEnum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FlattradeCallCategory(IntEnum):
    """Priority tiers for Flattrade API calls. Lower numeric value = higher priority."""

    ORDER = 0
    URGENT_QUOTE = 1
    SCANNER_QUOTE = 2
    DEPTH = 3
    HISTORICAL = 4


class UnifiedFlattradeRateGate:
    """
    Thread-safe prioritized rate limiter and budget governor for Flattrade Pi Connect API.
    Guarantees that high-frequency scans or depth requests never starve order execution
    or trigger HTTP 429 / broker session rate-limit drops.
    """

    _last_instance: Optional["UnifiedFlattradeRateGate"] = None

    def __init__(
        self,
        max_per_sec: Optional[float] = None,
        max_per_min: Optional[float] = None,
        max_hist_per_sec: Optional[float] = None,
    ) -> None:
        UnifiedFlattradeRateGate._last_instance = self

        env_sec = os.environ.get("FLATTRADE_MAX_PER_SEC")
        env_min = os.environ.get("FLATTRADE_MAX_PER_MIN")
        env_hist = os.environ.get("FLATTRADE_MAX_HIST_PER_SEC")

        # Official limit: 10 req/s. Safe cap: 8.0 req/s (20% institutional headroom)
        self._max_per_sec = float(
            max_per_sec if max_per_sec is not None else (float(env_sec) if env_sec else 8.0)
        )
        # 300 req/min provides a stable ceiling for non-burst streaming
        self._max_per_min = float(
            max_per_min if max_per_min is not None else (float(env_min) if env_min else 300.0)
        )
        # Strict 1 req/s for historical candle backfills
        self._max_hist_per_sec = float(
            max_hist_per_sec
            if max_hist_per_sec is not None
            else (float(env_hist) if env_hist else 1.0)
        )

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        # Sliding window timestamp ring buffer: (timestamp, category)
        self._sliding_window: deque[tuple[float, FlattradeCallCategory]] = deque()
        self._hist_window: deque[float] = deque()

        # Prioritized waiter queue: (category_priority, tie_breaker, category, threading.Event)
        self._waiters: list[tuple[int, int, FlattradeCallCategory, threading.Event]] = []
        self._counter = itertools.count()

        self._total_requests: dict[FlattradeCallCategory, int] = {
            c: 0 for c in FlattradeCallCategory
        }
        self._total_throttled: int = 0
        self._last_hist_dispatch_ts: float = 0.0

    def _purge_stale(self, now: float) -> None:
        cutoff_min = now - 60.0
        while self._sliding_window and self._sliding_window[0][0] < cutoff_min:
            self._sliding_window.popleft()

        cutoff_hist = now - 1.0
        while self._hist_window and self._hist_window[0] < cutoff_hist:
            self._hist_window.popleft()

    def _calculate_sleep_needed(self, now: float, category: FlattradeCallCategory) -> float:
        self._purge_stale(now)

        # 1. Historical candle pacing (max 1.0 req/s)
        if category == FlattradeCallCategory.HISTORICAL:
            if len(self._hist_window) >= self._max_hist_per_sec:
                oldest_hist = self._hist_window[0]
                hist_sleep = (oldest_hist + 1.0) - now
                if hist_sleep > 0.0:
                    return hist_sleep

        # 2. Per-second rolling ceiling
        sec_cutoff = now - 1.0
        reqs_last_sec = sum(1 for t, _ in self._sliding_window if t >= sec_cutoff)
        sleep_sec = 0.0
        if reqs_last_sec >= self._max_per_sec:
            # Find oldest in the 1s window
            for t, _ in self._sliding_window:
                if t >= sec_cutoff:
                    sleep_sec = max(sleep_sec, (t + 1.0) - now)
                    break

        # 3. Per-minute rolling ceiling
        sleep_min = 0.0
        if len(self._sliding_window) >= self._max_per_min:
            oldest_min = self._sliding_window[0][0]
            sleep_min = max(sleep_min, (oldest_min + 60.0) - now)

        return max(0.0, sleep_sec, sleep_min)

    def acquire(
        self,
        category: FlattradeCallCategory = FlattradeCallCategory.SCANNER_QUOTE,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Acquire rate-gate clearance for a Flattrade API call.
        Returns True if clearance granted; False if timed out.
        """
        if timeout is None:
            timeout = 5.0 if category == FlattradeCallCategory.ORDER else 15.0

        start = time.time()
        deadline = start + timeout

        event = threading.Event()
        tie_breaker = next(self._counter)
        waiter = (int(category), tie_breaker, category, event)

        with self._lock:
            now = time.time()
            sleep_needed = self._calculate_sleep_needed(now, category)

            if not self._waiters and sleep_needed <= 0.0:
                self._sliding_window.append((now, category))
                if category == FlattradeCallCategory.HISTORICAL:
                    self._hist_window.append(now)
                self._total_requests[category] += 1
                return True

            heapq.heappush(self._waiters, waiter)
            self._total_throttled += 1

        while True:
            now = time.time()
            if now >= deadline:
                with self._lock:
                    self._waiters = [w for w in self._waiters if w[1] != tie_breaker]
                    heapq.heapify(self._waiters)
                return False

            with self._lock:
                is_top = bool(self._waiters and self._waiters[0][1] == tie_breaker)
                if is_top:
                    sleep_needed = self._calculate_sleep_needed(now, category)
                    if sleep_needed <= 0.0:
                        heapq.heappop(self._waiters)
                        self._sliding_window.append((now, category))
                        if category == FlattradeCallCategory.HISTORICAL:
                            self._hist_window.append(now)
                        self._total_requests[category] += 1
                        if self._waiters:
                            self._waiters[0][3].set()
                        return True
                    sleep_to_use = min(sleep_needed, deadline - now)
                else:
                    sleep_to_use = deadline - now

            event.clear()
            event.wait(timeout=max(0.01, min(sleep_to_use, 1.0)))

    def get_diagnostics(self) -> dict[str, Any]:
        """Return real-time usage metrics and governor diagnostics."""
        with self._lock:
            now = time.time()
            self._purge_stale(now)

            sec_cutoff = now - 1.0
            reqs_last_sec = sum(1 for t, _ in self._sliding_window if t >= sec_cutoff)
            reqs_last_min = len(self._sliding_window)

            by_category_last_min = {c.name: 0 for c in FlattradeCallCategory}
            for _, cat in self._sliding_window:
                by_category_last_min[cat.name] += 1

            utilization_pct = round((reqs_last_min / self._max_per_min) * 100.0, 1)

            status = "NOMINAL"
            if utilization_pct >= 90.0:
                status = "SATURATED"
            elif self._total_throttled > 0 and len(self._waiters) > 0:
                status = "THROTTLED"

            return {
                "plan": "PI_CONNECT",
                "status": status,
                "max_per_sec": self._max_per_sec,
                "max_per_min": self._max_per_min,
                "max_hist_per_sec": self._max_hist_per_sec,
                "requests_last_sec": reqs_last_sec,
                "requests_last_min": reqs_last_min,
                "remaining_sec_tokens": max(0.0, self._max_per_sec - reqs_last_sec),
                "remaining_min_tokens": max(0.0, self._max_per_min - reqs_last_min),
                "utilization_pct": utilization_pct,
                "active_waiters": len(self._waiters),
                "total_requests": sum(self._total_requests.values()),
                "total_throttled": self._total_throttled,
                "requests_by_tier": {c.name: cnt for c, cnt in self._total_requests.items()},
                "requests_last_min_by_tier": by_category_last_min,
            }


_GLOBAL_FLATTRADE_RATE_GATE: Optional[UnifiedFlattradeRateGate] = None
_GATE_LOCK = threading.Lock()


def get_flattrade_rate_gate() -> UnifiedFlattradeRateGate:
    """Return the global Flattrade rate gate singleton."""
    global _GLOBAL_FLATTRADE_RATE_GATE
    if _GLOBAL_FLATTRADE_RATE_GATE is None:
        with _GATE_LOCK:
            if _GLOBAL_FLATTRADE_RATE_GATE is None:
                _GLOBAL_FLATTRADE_RATE_GATE = UnifiedFlattradeRateGate()
    return _GLOBAL_FLATTRADE_RATE_GATE
