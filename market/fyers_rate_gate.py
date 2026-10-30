"""
market/fyers_rate_gate.py
─────────────────────────
Unified prioritized sliding-window rate gate and budget governor for Fyers API v3.

Fyers API Hard Constraints:
  - Fyers Prime Plan:
      * 10 requests / second (Safe operating cap: 8.0 - 9.0 req/s)
      * 500 requests / minute (Safe operating cap: 400.0 - 450.0 req/min)
      * 500,000 requests / day (Safe operating cap: 480,000 req/day)
      * Up to 1,000 symbols per quotes request (clamped to 300 to avoid HTTP 414 URI Length)
      * Up to 5,000 symbols on real-time Data WebSocket
  - Fyers Standard Plan:
      * 5 requests / second (Safe operating cap: 4.0 req/s)
      * 50 requests / minute (Safe operating cap: 40.0 req/min)
      * 5,000 requests / day (Safe operating cap: 4,500 req/day)

Priority Tiers (Lower value = Higher priority):
  - Tier 0: ORDER           (Execution, cancel, modify; never starved by queries)
  - Tier 1: URGENT_QUOTE    (In-flight position stop-loss/take-profit guardian)
  - Tier 2: SCANNER_QUOTE   (Batch quotes for market scanners & radar)
  - Tier 3: DEPTH_CHAIN     (Market depth L2, options chains)
  - Tier 4: HISTORICAL      (Candle historical backfill, pre-market/post-market prefetch)
"""

from __future__ import annotations

import heapq
import atexit
import itertools
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional

from config.constants import IST_ZONE as IST

logger = logging.getLogger(__name__)

_ENABLE_CALLER_TRACKING = os.environ.get("FYERS_CALLER_TRACKING", "0") == "1"


def _get_quota_file() -> Path:
    base = os.environ.get("TRADING_PLATFORM_HOME")
    if base:
        return Path(base) / "fyers_daily_quota.json"
    return Path.home() / ".trading_platform" / "fyers_daily_quota.json"


_QUOTA_FILE = _get_quota_file()

# Institutional presets for Fyers API tiers
FYERS_PLAN_PRESETS: dict[str, dict[str, Any]] = {
    "PRIME": {
        "max_per_sec": 8.0,  # Official limit: 10 req/s (20% institutional cushion to prevent micro-burst trips)
        "max_per_min": 360.0,  # Official limit: 500 req/min (140 req/min headroom to prevent rolling window trips)
        "max_per_day": 480_000.0,  # Official limit: 500,000 req/day (20k emergency buffer)
        "order_emergency_cap": 498_000.0,
        "quotes_chunk_size": 1000,  # Official limit: 1,000 symbols/request
        "data_socket_symbols": 5000,
        "tbt_socket_symbols": 15,
    },
    "STANDARD": {
        "max_per_sec": 4.0,  # Official limit: 5 req/s (20% cushion)
        "max_per_min": 40.0,  # Official limit: 50 req/min (20% cushion)
        "max_per_day": 4500.0,  # Official limit: 5,000 req/day
        "order_emergency_cap": 4950.0,
        "quotes_chunk_size": 50,  # Official limit: 50 symbols/request
        "data_socket_symbols": 50,
        "tbt_socket_symbols": 1,
    },
}


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
    Supports dynamic tier calibration for Fyers Prime (500k req/day, 500 req/min, 10 req/s, 1000 symbols/req)
    and Fyers Standard (5k req/day, 50 req/min, 5 req/s, 50 symbols/req).
    """

    _last_instance: Optional["UnifiedFyersRateGate"] = None

    def __init__(
        self,
        plan: Optional[str] = None,
        max_per_sec: Optional[float] = None,
        max_per_min: Optional[float] = None,
        max_per_day: Optional[float] = None,
    ) -> None:
        self._quota_file = _QUOTA_FILE
        if (
            UnifiedFyersRateGate._last_instance is not None
            and UnifiedFyersRateGate._last_instance is not self
        ):
            try:
                if (
                    getattr(UnifiedFyersRateGate._last_instance, "_quota_file", None)
                    == self._quota_file
                ):
                    UnifiedFyersRateGate._last_instance.flush_quota()
            except Exception as e:
                logger.warning(f"Error flushing previous rate gate instance quota: {e}")
        UnifiedFyersRateGate._last_instance = self

        selected_plan = (plan or os.environ.get("FYERS_PLAN", "PRIME")).upper()
        if selected_plan not in FYERS_PLAN_PRESETS:
            selected_plan = "PRIME"
        self._plan = selected_plan
        preset = FYERS_PLAN_PRESETS[selected_plan]

        env_sec = os.environ.get("FYERS_MAX_PER_SEC")
        env_min = os.environ.get("FYERS_MAX_PER_MIN")
        env_day = os.environ.get("FYERS_MAX_PER_DAY")

        self._max_per_sec = float(
            max_per_sec
            if max_per_sec is not None
            else (float(env_sec) if env_sec else preset["max_per_sec"])
        )
        self._max_per_min = float(
            max_per_min
            if max_per_min is not None
            else (float(env_min) if env_min else preset["max_per_min"])
        )
        self._max_per_day = float(
            max_per_day
            if max_per_day is not None
            else (float(env_day) if env_day else preset["max_per_day"])
        )
        self._order_emergency_cap = float(preset["order_emergency_cap"])
        self._quotes_chunk_size = int(preset["quotes_chunk_size"])
        self._data_socket_symbols = int(preset["data_socket_symbols"])
        self._tbt_socket_symbols = int(preset["tbt_socket_symbols"])

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

        # Daily cumulative quota tracking (resets at 00:00:00 IST)
        self._today_str: str = datetime.now(IST).strftime("%Y-%m-%d")
        self._daily_requests: int = 0
        self._daily_by_category: dict[FyersCallCategory, int] = {c: 0 for c in FyersCallCategory}
        self._last_warn_time: float = 0.0
        self._last_dispatch_ts: float = 0.0
        self._last_depth_dispatch_ts: float = 0.0
        self._last_hist_dispatch_ts: float = 0.0
        self._caller_counts: dict[str, int] = {}
        self._quota_dirty: bool = False
        self._load_daily_quota()
        self._start_quota_persistence_loop()
        atexit.register(self.flush_quota)

    @property
    def plan(self) -> str:
        return self._plan

    @property
    def quotes_chunk_size(self) -> int:
        return self._quotes_chunk_size

    @property
    def data_socket_symbols(self) -> int:
        return self._data_socket_symbols

    @property
    def tbt_socket_symbols(self) -> int:
        return self._tbt_socket_symbols

    def recalibrate(self, plan: str = "PRIME") -> None:
        """Dynamically switch between PRIME and STANDARD operational limits."""
        plan_upper = plan.upper()
        if plan_upper not in FYERS_PLAN_PRESETS:
            raise ValueError(
                f"Unknown Fyers plan: {plan}. Supported: {list(FYERS_PLAN_PRESETS.keys())}"
            )
        preset = FYERS_PLAN_PRESETS[plan_upper]
        with self._lock:
            self._plan = plan_upper
            self._max_per_sec = preset["max_per_sec"]
            self._max_per_min = preset["max_per_min"]
            self._max_per_day = preset["max_per_day"]
            self._order_emergency_cap = preset["order_emergency_cap"]
            self._quotes_chunk_size = preset["quotes_chunk_size"]
            self._data_socket_symbols = preset["data_socket_symbols"]
            self._tbt_socket_symbols = preset["tbt_socket_symbols"]
            logger.info(
                f"[FyersRateGate] Recalibrated to {plan_upper}: {self._max_per_sec} req/s, "
                f"{self._max_per_min} req/min, {self._max_per_day:,.0f} req/day, "
                f"{self._quotes_chunk_size} symbols/batch"
            )

    def reset_state(self) -> None:
        """Reset all in-memory sliding windows, waiters, and timestamps (e.g. for test isolation)."""
        with self._lock:
            self._sliding_window.clear()
            for _, _, _, event in self._waiters:
                event.set()
            self._waiters.clear()
            self._last_dispatch_ts = 0.0
            self._last_depth_dispatch_ts = 0.0
            self._last_hist_dispatch_ts = 0.0
            self._counter = itertools.count()

    def reset_daily_quota(self, requests: int = 0) -> None:
        """Reset the persisted daily quota counter (e.g. after purchasing Prime)."""
        with self._lock:
            self._daily_requests = requests
            self._quota_dirty = False
            self._save_daily_quota()
            logger.info(
                f"[FyersRateGate] Daily request counter set to {requests} / {int(self._max_per_day):,}"
            )

    def _start_quota_persistence_loop(self) -> None:
        """Persist daily quota to disk every 30s in background to eliminate ~1M sync disk writes per session."""

        def _loop():
            while True:
                time.sleep(30.0)
                try:
                    with self._lock:
                        if self._quota_dirty:
                            self._save_daily_quota()
                            self._quota_dirty = False
                except Exception as exc:
                    logger.debug(f"[FyersRateGate] Quota persistence background error: {exc}")

        t = threading.Thread(target=_loop, daemon=True, name="FyersRateGate-QuotaPersist")
        t.start()

    def flush_quota(self) -> None:
        """Synchronously persist quota to disk if dirty."""
        with self._lock:
            if self._quota_dirty:
                self._save_daily_quota()
                self._quota_dirty = False

    def _load_daily_quota(self) -> None:
        """Load persisted daily request count to survive service restarts."""
        try:
            q_file = getattr(self, "_quota_file", _QUOTA_FILE)
            if q_file.exists():
                data = json.loads(q_file.read_text(encoding="utf-8"))
                if data.get("date") == self._today_str:
                    self._daily_requests = int(data.get("requests", 0))
                else:
                    self._daily_requests = 0
                    self._save_daily_quota()
        except Exception as exc:
            logger.debug("[FyersRateGate] Daily quota load error: %s", exc)
            self._daily_requests = 0

    def _save_daily_quota(self) -> None:
        """Atomically persist daily counter to disk."""
        try:
            q_file = getattr(self, "_quota_file", _QUOTA_FILE)
            q_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "date": self._today_str,
                "requests": self._daily_requests,
                "last_updated": datetime.now(IST).isoformat(),
            }
            tmp_path = q_file.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(q_file)
        except Exception as e_suppressed:
            logger.debug(f"[market.fyers_rate_gate] Non-fatal exception suppressed: {e_suppressed}")

    def record_external_exhaustion(self) -> None:
        """Explicitly record that Fyers returned 429 daily limit reached."""
        with self._lock:
            self._daily_requests = max(self._daily_requests, int(self._max_per_day) + 500)
            self._quota_dirty = False
            self._save_daily_quota()

    def _check_and_rollover_day(self) -> None:
        """Rollover daily counter if calendar day in IST has changed."""
        now_day = datetime.now(IST).strftime("%Y-%m-%d")
        if now_day != self._today_str:
            self._today_str = now_day
            self._daily_requests = 0
            self._daily_by_category = {c: 0 for c in FyersCallCategory}
            self._quota_dirty = False
            self._save_daily_quota()
            logger.info(
                "[FyersRateGate] Daily request counter reset for new calendar session: %s", now_day
            )

    def _purge_stale_timestamps(self, now: float) -> None:
        """Evict records older than 60.0 seconds from the sliding window."""
        cutoff = now - 60.0
        while self._sliding_window and self._sliding_window[0][0] < cutoff:
            self._sliding_window.popleft()

    def _calculate_sleep_needed(
        self, now: float, category: Optional[FyersCallCategory] = None
    ) -> float:
        """Calculate minimum sleep needed to satisfy 1-sec, 60-sec caps, and leaky bucket inter-request spacing."""
        # 1. Orders bypass leaky bucket inter-request spacing for immediate execution
        if category == FyersCallCategory.ORDER:
            min_interval = 0.02
        else:
            min_interval = 1.0 / max(self._max_per_sec, 1.0)

        # Guard against backwards clock skew or future mocked timestamps
        if self._last_dispatch_ts > now:
            self._last_dispatch_ts = now
        time_since_last = max(0.0, now - self._last_dispatch_ts)
        sleep_sec = max(0.0, min_interval - time_since_last)

        # 1b. Dedicated rate pacing for DEPTH_CHAIN calls to eliminate Fyers /depth burst throttling (-360/429)
        if category == FyersCallCategory.DEPTH_CHAIN:
            depth_spacing = (
                0.40  # Max ~2.5 depth requests/sec (strictly protects Fyers /depth limit)
            )
            last_depth = getattr(self, "_last_depth_dispatch_ts", 0.0)
            if last_depth > now:
                self._last_depth_dispatch_ts = now
                last_depth = now
            time_since_depth = max(0.0, now - last_depth)
            sleep_sec = max(sleep_sec, depth_spacing - time_since_depth)

            # Dedicated 1-second rolling cap for DEPTH_CHAIN (max 2 per second)
            depth_sec_cutoff = now - 1.0
            recent_depth = [
                t
                for t, c in self._sliding_window
                if c == FyersCallCategory.DEPTH_CHAIN and t >= depth_sec_cutoff
            ]
            if len(recent_depth) >= 2:
                oldest_depth = min(now, recent_depth[0])
                sleep_sec = max(sleep_sec, 1.0 - (now - oldest_depth) + 0.01)

        # 1c. Dedicated rate pacing for HISTORICAL calls to pace multi-bar history fetches
        if category == FyersCallCategory.HISTORICAL:
            hist_spacing = (
                0.35  # Max ~2.85 historical requests/sec (strictly protects Fyers /history limit)
            )
            last_hist = getattr(self, "_last_hist_dispatch_ts", 0.0)
            if last_hist > now:
                self._last_hist_dispatch_ts = now
                last_hist = now
            time_since_hist = max(0.0, now - last_hist)
            sleep_sec = max(sleep_sec, hist_spacing - time_since_hist)

            # Dedicated 1-second rolling cap for HISTORICAL (max 3 per second)
            hist_sec_cutoff = now - 1.0
            recent_hist = [
                t
                for t, c in self._sliding_window
                if c == FyersCallCategory.HISTORICAL and t >= hist_sec_cutoff
            ]
            if len(recent_hist) >= 3:
                oldest_hist = min(now, recent_hist[0])
                sleep_sec = max(sleep_sec, 1.0 - (now - oldest_hist) + 0.01)

        # 2. Check 1-second rolling window
        sec_cutoff = now - 1.0
        recent_sec = [t for t, _ in self._sliding_window if t >= sec_cutoff]
        if len(recent_sec) >= self._max_per_sec:
            # Must wait until oldest entry in current 1s window ages out
            oldest_in_sec = min(now, recent_sec[0])
            sleep_sec = max(sleep_sec, 1.0 - (now - oldest_in_sec) + 0.005)

        # 3. Check 60-second rolling window including pending waiter load
        effective_min_load = len(self._sliding_window) + len(self._waiters)
        if effective_min_load >= self._max_per_min:
            oldest_in_min = min(now, self._sliding_window[0][0]) if self._sliding_window else now
            sleep_sec = max(sleep_sec, 60.0 - (now - oldest_in_min) + 0.02)

        # Rate gate operates on 1-sec and 60-sec rolling windows; sleep can never legitimately exceed 60s.
        # Clamping sleep_sec protects against clock skew and Windows DWORD/TIMEOUT_MAX overflow errors.
        sleep_sec = max(0.0, min(sleep_sec, 60.0))

        # Apply slight micro-jitter (2-6ms) when sleep is needed to desynchronize thread releases
        if sleep_sec > 0.0:
            import random

            sleep_sec += random.uniform(0.002, 0.006)

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
        Returns True if acquired, False if timed out or rejected due to daily quota.
        """
        # Track caller attribution for institutional rate observability (debug only)
        if _ENABLE_CALLER_TRACKING:
            import traceback

            try:
                frames = traceback.extract_stack(limit=12)[:-1]
                relevant = [
                    f"{Path(fr.filename).name}:{fr.lineno} ({fr.name})"
                    for fr in frames
                    if "fyers_rate_gate" not in fr.filename and "threading" not in fr.filename
                ]
                if relevant:
                    c_key = " <- ".join(reversed(relevant[-3:]))
                    with self._lock:
                        self._caller_counts[c_key] = self._caller_counts.get(c_key, 0) + 1
            except Exception as e_suppressed:
                logger.debug(f"[market.fyers_rate_gate] Caller tracking error: {e_suppressed}")
        event = threading.Event()
        start_wait = time.time()
        tie_breaker = next(self._counter)
        waiter_entry = (int(category), tie_breaker, category, event)

        with self._lock:
            self._check_and_rollover_day()

            # Enforce daily cumulative budget limits
            if category != FyersCallCategory.ORDER and self._daily_requests >= self._max_per_day:
                now_w = time.time()
                if now_w - self._last_warn_time > 60.0:
                    self._last_warn_time = now_w
                    logger.warning(
                        "[FyersRateGate] Daily soft quota reached (%d/%d reqs). Rejecting %s "
                        "to preserve remaining budget for ORDER execution.",
                        self._daily_requests,
                        int(self._max_per_day),
                        category.name,
                    )
                return False

            if (
                category == FyersCallCategory.ORDER
                and self._daily_requests >= self._order_emergency_cap
            ):
                logger.critical(
                    "[FyersRateGate] Fyers daily emergency order budget reached (%d/%d reqs). "
                    "Halting order dispatch to avoid broker freeze.",
                    self._daily_requests,
                    int(self._order_emergency_cap),
                )
                return False

            # If no one is waiting and there is immediate capacity, grant immediately
            now = time.time()
            self._purge_stale_timestamps(now)
            sleep_needed = self._calculate_sleep_needed(now, category=category)

            if not self._waiters and sleep_needed <= 0.0:
                self._sliding_window.append((now, category))
                self._last_dispatch_ts = now
                if category == FyersCallCategory.DEPTH_CHAIN:
                    self._last_depth_dispatch_ts = now
                elif category == FyersCallCategory.HISTORICAL:
                    self._last_hist_dispatch_ts = now
                self._total_requests[category] += 1
                self._daily_requests += 1
                self._daily_by_category[category] += 1
                self._quota_dirty = True
                if self._daily_requests % 50 == 0:
                    self._save_daily_quota()
                    self._quota_dirty = False
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
                    waiter_cat = self._waiters[0][2]
                    sleep_needed = self._calculate_sleep_needed(now, category=waiter_cat)
                    if sleep_needed <= 0.0:
                        # Success: pop ourselves and record consumption
                        heapq.heappop(self._waiters)
                        self._sliding_window.append((now, category))
                        self._last_dispatch_ts = now
                        if category == FyersCallCategory.DEPTH_CHAIN:
                            self._last_depth_dispatch_ts = now
                        elif category == FyersCallCategory.HISTORICAL:
                            self._last_hist_dispatch_ts = now
                        self._total_requests[category] += 1
                        self._daily_requests += 1
                        self._daily_by_category[category] += 1
                        self._quota_dirty = True
                        if self._daily_requests % 50 == 0:
                            self._save_daily_quota()
                            self._quota_dirty = False
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
            event.clear()
            safe_sleep = max(0.0, min(sleep_to_use, 60.0))
            event.wait(timeout=safe_sleep)

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

            daily_by_cat: dict[str, int] = {
                cat.name: cnt for cat, cnt in self._daily_by_category.items()
            }
            daily_remaining = max(0, int(self._max_per_day - self._daily_requests))
            is_daily_exhausted = bool(self._daily_requests >= self._max_per_day)

            return {
                "plan": self._plan,
                "quotes_chunk_size": self._quotes_chunk_size,
                "data_socket_symbols": self._data_socket_symbols,
                "tbt_socket_symbols": self._tbt_socket_symbols,
                "max_per_sec": self._max_per_sec,
                "max_per_min": self._max_per_min,
                "max_per_day": self._max_per_day,
                "daily_requests": self._daily_requests,
                "daily_budget_remaining": daily_remaining,
                "daily_quota_exhausted": is_daily_exhausted,
                "daily_requests_by_tier": daily_by_cat,
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
                "top_callers": dict(
                    sorted(self._caller_counts.items(), key=lambda x: x[1], reverse=True)[:15]
                ),
                "uptime_seconds": round(now - self._started_at, 1),
                "status": "EXHAUSTED"
                if is_daily_exhausted
                else (
                    "HEALTHY"
                    if utilization_pct < 85.0
                    else ("WARNING" if utilization_pct < 95.0 else "SATURATED")
                ),
            }


# Global singleton instance
fyers_rate_gate = UnifiedFyersRateGate()


def get_fyers_rate_gate() -> UnifiedFyersRateGate:
    """Return the global unified rate gate singleton."""
    return fyers_rate_gate
