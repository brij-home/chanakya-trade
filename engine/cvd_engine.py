"""
engine/cvd_engine.py
────────────────────
Cumulative Volume Delta (CVD) Footprint Microstructure Engine.

Institutional Capabilities:
  1. Aggressor Side Tick Classification:
     Classifies trades into Aggressive Buy (+Volume), Aggressive Sell (-Volume),
     or Neutral based on Best Bid/Ask boundaries and the Lee-Ready tick test.
  2. Cumulative Volume Delta (CVD) Accumulation:
     Maintains an online O(1) rolling session CVD, delta ratio, and rate-of-change slope.
  3. Microstructure Absorption & Trap Detection:
     - Bullish Absorption (Bear Trap): Price making lower lows or breaking support while
       CVD makes higher lows (passive institutional limit bids absorbing aggressive sellers).
     - Bearish Exhaustion (Bull Trap): Price pushing higher while CVD diverges negative
       (passive institutional limit asks absorbing aggressive buyers).
     - Aligned Delta Expansion: Confirmed institutional thrust where volume delta actively
       supports price direction.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Optional

from market.instruments import canonical_symbol

logger = logging.getLogger("engine.cvd_engine")


@dataclass
class CVDMetrics:
    """Institutional Order Flow Cumulative Volume Delta snapshot."""

    symbol: str
    current_cvd: float
    session_volume: float
    session_delta: float
    delta_ratio: float  # session_delta / session_volume ∈ [-1.0, 1.0]
    cvd_slope: float  # Rate of change over recent window
    cvd_bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    cvd_divergence: str  # "ALIGNED" | "BULLISH_ABSORPTION" | "BEARISH_EXHAUSTION" | "NEUTRAL"
    absorption_detected: bool
    absorption_note: str
    sample_count: int
    as_of: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SymbolCVDTracker:
    """Thread-safe, bounded circular tracker for a single symbol's CVD."""

    def __init__(self, symbol: str, window_size: int = 1000) -> None:
        self.symbol = canonical_symbol(symbol).upper()
        self.window_size = window_size
        self._lock = threading.Lock()

        # Cumulative counters
        self._cum_delta: float = 0.0
        self._total_volume: float = 0.0
        self._last_price: float = 0.0

        # Rolling history of (timestamp, price, delta, cum_delta)
        self._history: deque[tuple[float, float, float, float]] = deque(maxlen=window_size)

    def record_tick(
        self,
        price: float,
        volume: float,
        best_bid: float = 0.0,
        best_ask: float = 0.0,
        timestamp: Optional[float] = None,
    ) -> float:
        """
        Classifies incoming trade tick and updates running CVD.
        Returns the delta contribution of this tick.
        """
        if price <= 0 or volume <= 0:
            return 0.0

        ts = timestamp if timestamp is not None else time.time()

        with self._lock:
            # 1. Aggressor side classification (Lee-Ready with Depth Quote Boundaries)
            if best_ask > 0 and price >= best_ask:
                # Trade at or above ask -> Buyer initiated
                delta = float(volume)
            elif best_bid > 0 and price <= best_bid:
                # Trade at or below bid -> Seller initiated
                delta = -float(volume)
            else:
                # Inside the spread: use tick test vs last recorded price
                if self._last_price > 0:
                    if price > self._last_price:
                        delta = float(volume)
                    elif price < self._last_price:
                        delta = -float(volume)
                    else:
                        # Zero-tick: inherit prior tick sign if available, else 0
                        delta = self._history[-1][2] if self._history else 0.0
                else:
                    delta = 0.0

            self._cum_delta += delta
            self._total_volume += float(volume)
            self._last_price = price
            self._history.append((ts, price, delta, self._cum_delta))

            return delta

    def get_metrics(self) -> CVDMetrics:
        """Computes current CVD metrics and detects institutional absorption/divergence."""
        with self._lock:
            sample_count = len(self._history)
            now_iso = time.strftime("%Y-%m-%d %H:%M:%S IST", time.localtime())

            if sample_count < 2:
                return CVDMetrics(
                    symbol=self.symbol,
                    current_cvd=round(self._cum_delta, 2),
                    session_volume=round(self._total_volume, 2),
                    session_delta=round(self._cum_delta, 2),
                    delta_ratio=0.0,
                    cvd_slope=0.0,
                    cvd_bias="NEUTRAL",
                    cvd_divergence="NEUTRAL",
                    absorption_detected=False,
                    absorption_note="Insufficient tick samples for microstructure CVD profiling.",
                    sample_count=sample_count,
                    as_of=now_iso,
                )

            # Delta ratio
            delta_ratio = self._cum_delta / self._total_volume if self._total_volume > 0 else 0.0

            # Analyze recent window (last 20 to 50 samples)
            window_len = min(sample_count, 50)
            sub_history = list(self._history)[-window_len:]
            p_start, p_end = sub_history[0][1], sub_history[-1][1]
            cvd_start, cvd_end = sub_history[0][3], sub_history[-1][3]

            price_change = p_end - p_start
            price_change_pct = (price_change / p_start * 100.0) if p_start > 0 else 0.0
            cvd_change = cvd_end - cvd_start
            cvd_slope = cvd_change / window_len

            # Bias classification
            if cvd_slope > 0.05 or delta_ratio >= 0.12:
                cvd_bias = "BULLISH"
            elif cvd_slope < -0.05 or delta_ratio <= -0.12:
                cvd_bias = "BEARISH"
            else:
                cvd_bias = "NEUTRAL"

            # Divergence & Absorption Detection
            # Bullish Absorption (Bear Trap): Price making down move while CVD is rising / positive
            is_bull_absorb = price_change_pct <= -0.25 and (cvd_slope > 0 or delta_ratio > 0.08)

            # Bearish Exhaustion (Bull Trap): Price pushing up while CVD is falling / negative
            is_bear_exhaust = price_change_pct >= 0.25 and (cvd_slope < 0 or delta_ratio < -0.08)

            if is_bull_absorb:
                divergence = "BULLISH_ABSORPTION"
                absorption = True
                note = (
                    f"Passive Institutional Accumulation (Bear Trap): Price down {price_change_pct:.2f}% "
                    f"while CVD expands positively (+{cvd_change:.0f}). Aggressive sellers are being absorbed by limit bids."
                )
            elif is_bear_exhaust:
                divergence = "BEARISH_EXHAUSTION"
                absorption = True
                note = (
                    f"Passive Institutional Distribution (Bull Trap): Price up +{price_change_pct:.2f}% "
                    f"while CVD diverges negatively ({cvd_change:.0f}). Aggressive buyers are hitting passive limit asks."
                )
            elif (price_change_pct > 0 and cvd_slope > 0) or (
                price_change_pct < 0 and cvd_slope < 0
            ):
                divergence = "ALIGNED"
                absorption = False
                note = "Order Flow Delta confirms price momentum with aligned aggressor volume."
            else:
                divergence = "NEUTRAL"
                absorption = False
                note = "Balanced order flow delta."

            return CVDMetrics(
                symbol=self.symbol,
                current_cvd=round(self._cum_delta, 2),
                session_volume=round(self._total_volume, 2),
                session_delta=round(self._cum_delta, 2),
                delta_ratio=round(delta_ratio, 4),
                cvd_slope=round(cvd_slope, 4),
                cvd_bias=cvd_bias,
                cvd_divergence=divergence,
                absorption_detected=absorption,
                absorption_note=note,
                sample_count=sample_count,
                as_of=now_iso,
            )

    def reset(self) -> None:
        """Resets in-memory history for session initialization or test isolation."""
        with self._lock:
            self._cum_delta = 0.0
            self._total_volume = 0.0
            self._last_price = 0.0
            self._history.clear()


# ── Global CVD Registry ──

_CVD_TRACKERS: dict[str, SymbolCVDTracker] = {}
_CVD_LOCK = threading.Lock()


def get_cvd_tracker(symbol: str) -> SymbolCVDTracker:
    """Returns or creates the singleton SymbolCVDTracker for the canonical symbol."""
    clean = canonical_symbol(symbol).upper()
    with _CVD_LOCK:
        if clean not in _CVD_TRACKERS:
            _CVD_TRACKERS[clean] = SymbolCVDTracker(clean)
        return _CVD_TRACKERS[clean]


def record_market_trade(
    symbol: str,
    price: float,
    volume: float,
    best_bid: float = 0.0,
    best_ask: float = 0.0,
    timestamp: Optional[float] = None,
) -> float:
    """Ingests a live trade tick into the symbol's CVD engine."""
    tracker = get_cvd_tracker(symbol)
    return tracker.record_tick(price, volume, best_bid, best_ask, timestamp)


def get_cvd_metrics(symbol: str) -> CVDMetrics:
    """Returns current institutional CVD metrics for the symbol."""
    tracker = get_cvd_tracker(symbol)
    return tracker.get_metrics()


def clear_all_cvd_trackers() -> None:
    """Clears all registered CVD trackers (primarily for test isolation and session reset)."""
    with _CVD_LOCK:
        _CVD_TRACKERS.clear()
