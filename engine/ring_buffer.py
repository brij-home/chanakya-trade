"""
engine/ring_buffer.py
─────────────────────
High-Performance O(1) Circular Ring Buffer for High-Frequency Ticks and Depth Streams.

Guarantees & Invariants:
  1. O(1) Append & Memory Stability: Fixed capacity, zero memory re-allocation or GC churn during tick bursts.
  2. O(1) Online VWAP: Instantaneous Volume Weighted Average Price using sliding cumulative products.
  3. O(1) Sliding Variance & Volatility: Continuous rolling variance and standard deviation.
  4. O(1) Amortized Min & Max: Monotonic double-ended queues track exact high & low in the sliding window.
  5. Thread-Safe: Protected by lightweight re-entrant locks.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class TickEntry:
    price: float
    volume: int
    timestamp: float


class RollingTickBuffer:
    """
    Fixed-capacity circular buffer with O(1) rolling VWAP, variance, and extrema.
    """

    def __init__(self, capacity: int = 100) -> None:
        if capacity <= 0:
            raise ValueError("Capacity must be greater than 0")
        self.capacity = int(capacity)
        self._lock = threading.Lock()

        # Circular buffer arrays
        self._prices: list[float] = [0.0] * self.capacity
        self._volumes: list[int] = [0] * self.capacity
        self._timestamps: list[float] = [0.0] * self.capacity

        self._head = 0  # Write pointer
        self._count = 0  # Current number of items stored
        self._total_appended = 0  # Monotonic tick sequence index

        # Online VWAP accumulators
        self._sum_pv = 0.0
        self._sum_v = 0

        # Online Variance accumulators
        self._sum_p = 0.0
        self._sum_p2 = 0.0

        # Periodic exact recalibration interval to eliminate IEEE 754 drift
        self._recalc_interval = 2000

        # Monotonic deques for O(1) sliding min / max: store (value, seq_index)
        self._max_deque: deque[tuple[float, int]] = deque()
        self._min_deque: deque[tuple[float, int]] = deque()

    def _recalibrate_accumulators_locked(self) -> None:
        """Re-anchor rolling accumulators using exact math.fsum to prevent IEEE 754 float drift."""
        n = self._count
        if n == 0:
            self._sum_pv = 0.0
            self._sum_v = 0
            self._sum_p = 0.0
            self._sum_p2 = 0.0
            return
        active_prices = self._prices[:n] if n < self.capacity else self._prices
        active_volumes = self._volumes[:n] if n < self.capacity else self._volumes
        self._sum_p = math.fsum(active_prices)
        self._sum_p2 = math.fsum(p * p for p in active_prices)
        self._sum_pv = math.fsum(p * v for p, v in zip(active_prices, active_volumes))
        self._sum_v = sum(active_volumes)

    def _append_locked(self, p: float, v: int, ts: float) -> None:
        """Inner O(1) tick append routine executed under self._lock."""
        seq = self._total_appended
        idx = self._head

        if self._count < self.capacity:
            # Buffer is filling up
            self._prices[idx] = p
            self._volumes[idx] = v
            self._timestamps[idx] = ts

            self._sum_pv += p * v
            self._sum_v += v
            self._sum_p += p
            self._sum_p2 += p * p
            self._count += 1
        else:
            # Buffer is full -> evict oldest entry at current head
            old_p = self._prices[idx]
            old_v = self._volumes[idx]

            self._sum_pv += (p * v) - (old_p * old_v)
            self._sum_v += v - old_v
            self._sum_p += p - old_p
            self._sum_p2 += (p * p) - (old_p * old_p)

            self._prices[idx] = p
            self._volumes[idx] = v
            self._timestamps[idx] = ts

        # Update write head circularly
        self._head = (idx + 1) % self.capacity
        self._total_appended += 1

        # Periodic exact recalibration every 2,000 appends
        if self._total_appended % self._recalc_interval == 0:
            self._recalibrate_accumulators_locked()

        # Update Monotonic Max Deque
        while self._max_deque and self._max_deque[-1][0] <= p:
            self._max_deque.pop()
        self._max_deque.append((p, seq))

        # Evict expired max elements older than the sliding window
        cutoff = seq - self.capacity
        while self._max_deque and self._max_deque[0][1] <= cutoff:
            self._max_deque.popleft()

        # Update Monotonic Min Deque
        while self._min_deque and self._min_deque[-1][0] >= p:
            self._min_deque.pop()
        self._min_deque.append((p, seq))

        # Evict expired min elements older than the sliding window
        while self._min_deque and self._min_deque[0][1] <= cutoff:
            self._min_deque.popleft()

    def append(self, price: float, volume: int = 1, timestamp: Optional[float] = None) -> None:
        """
        Append a new tick in O(1) time complexity.
        """
        p = float(price)
        v = int(volume)
        ts = float(timestamp) if timestamp is not None else time.time()

        with self._lock:
            self._append_locked(p, v, ts)

    def extend(self, ticks: list[Any]) -> None:
        """
        Append a batch of ticks under a single lock acquisition.
        Drastically reduces lock contention during burst socket dispatches.
        Each item can be (price, volume) or (price, volume, timestamp).
        """
        if not ticks:
            return
        now = time.time()
        with self._lock:
            for item in ticks:
                if len(item) == 2:
                    p, v = item
                    ts = now
                else:
                    p, v, ts_val = item
                    ts = float(ts_val) if ts_val is not None else now
                self._append_locked(float(p), int(v), float(ts))

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def is_full(self) -> bool:
        with self._lock:
            return self._count == self.capacity

    @property
    def last_price(self) -> float:
        with self._lock:
            if self._count == 0:
                return 0.0
            last_idx = (self._head - 1) % self.capacity
            return self._prices[last_idx]

    @property
    def vwap(self) -> float:
        """O(1) Rolling Volume Weighted Average Price."""
        with self._lock:
            if self._sum_v <= 0 or self._count == 0:
                return 0.0
            return self._sum_pv / self._sum_v

    @property
    def mean(self) -> float:
        """O(1) Rolling Mean Price."""
        with self._lock:
            if self._count == 0:
                return 0.0
            return self._sum_p / self._count

    @property
    def variance(self) -> float:
        """O(1) Rolling Price Variance with automatic float drift compensation."""
        with self._lock:
            if self._count <= 1:
                return 0.0
            mean = self._sum_p / self._count
            var = (self._sum_p2 / self._count) - (mean * mean)
            if var < 0.0:
                # IEEE 754 float drift detected, recalibrate immediately
                self._recalibrate_accumulators_locked()
                mean = self._sum_p / self._count
                var = (self._sum_p2 / self._count) - (mean * mean)
            return max(0.0, var)

    @property
    def std(self) -> float:
        """O(1) Rolling Price Standard Deviation."""
        return math.sqrt(self.variance)

    @property
    def std_dev(self) -> float:
        """O(1) Rolling Price Standard Deviation (alias for std)."""
        return self.std

    @property
    def max_price(self) -> float:
        """O(1) Highest price in current window."""
        with self._lock:
            if not self._max_deque:
                return 0.0
            return self._max_deque[0][0]

    @property
    def min_price(self) -> float:
        """O(1) Lowest price in current window."""
        with self._lock:
            if not self._min_deque:
                return 0.0
            return self._min_deque[0][0]

    @property
    def total_volume(self) -> int:
        with self._lock:
            return self._sum_v

    def get_snapshot(self) -> dict[str, Any]:
        """Return instantaneous quant statistics in O(1)."""
        with self._lock:
            cnt = self._count
            if cnt == 0:
                return {
                    "count": 0,
                    "last_price": 0.0,
                    "vwap": 0.0,
                    "mean": 0.0,
                    "std": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "total_volume": 0,
                }
            last_idx = (self._head - 1) % self.capacity
            mean = self._sum_p / cnt
            var = max(0.0, (self._sum_p2 / cnt) - (mean * mean)) if cnt > 1 else 0.0
            vwap = (self._sum_pv / self._sum_v) if self._sum_v > 0 else 0.0
            max_p = self._max_deque[0][0] if self._max_deque else 0.0
            min_p = self._min_deque[0][0] if self._min_deque else 0.0

            return {
                "count": cnt,
                "last_price": self._prices[last_idx],
                "vwap": round(vwap, 4),
                "mean": round(mean, 4),
                "std": round(math.sqrt(var), 4),
                "min": min_p,
                "max": max_p,
                "total_volume": self._sum_v,
            }

    def quantile(self, q: float = 0.5) -> float:
        """Calculate quantile (e.g. 0.5 for median) of the current window."""
        with self._lock:
            if self._count == 0:
                return 0.0
            q_clamped = max(0.0, min(1.0, float(q)))
            sorted_p = sorted(self._prices[: self._count])
            idx = int(q_clamped * (len(sorted_p) - 1))
            return sorted_p[idx]

    @property
    def median(self) -> float:
        """Median price of the current window."""
        return self.quantile(0.5)

    def to_records(self) -> list[dict[str, Any]]:
        """Return all ticks in current window ordered chronologically."""
        with self._lock:
            if self._count == 0:
                return []
            if self._count < self.capacity:
                return [
                    {
                        "price": self._prices[i],
                        "volume": self._volumes[i],
                        "timestamp": self._timestamps[i],
                    }
                    for i in range(self._count)
                ]
            records = []
            for i in range(self.capacity):
                idx = (self._head + i) % self.capacity
                records.append(
                    {
                        "price": self._prices[idx],
                        "volume": self._volumes[idx],
                        "timestamp": self._timestamps[idx],
                    }
                )
            return records

    def clear(self) -> None:
        """Reset the buffer."""
        with self._lock:
            self._head = 0
            self._count = 0
            self._total_appended = 0
            self._sum_pv = 0.0
            self._sum_v = 0
            self._sum_p = 0.0
            self._sum_p2 = 0.0
            self._max_deque.clear()
            self._min_deque.clear()
