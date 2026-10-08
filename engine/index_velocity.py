"""
engine/index_velocity.py
────────────────────────
Cross-Index Real-Time Velocity Radar for Indian Markets.

Continuously computes Index Velocity Score (IVS) across:
    NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX

Distinguishes between:
    1. LEADER_EXPANSION — Fast directional impulse, high ATR expansion, priority scanning.
    2. NORMAL_TREND     — Steady trend with standard volatility.
    3. CHOP_PINNED      — Low volatility, range-bound mean reversion (<0.18% range over 30m).

Used by:
    - AutoAlertEngine to prioritize fast-moving indices over stagnant ones.
    - Index detectors to attach velocity badges and suppress low-conviction chop breakouts.
    - Trade planners to select fast-scalp targets and tight time-stops.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
import pandas as pd

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_WATCHED_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "SENSEX",
    "BANKEX",
]


@dataclass
class IndexVelocityMetric:
    """Quantitative velocity snapshot for an index."""

    symbol: str
    velocity_score: float  # 0 to 100
    regime: str  # "LEADER_EXPANSION" | "NORMAL_TREND" | "CHOP_PINNED"
    spot: float
    change_pct: float
    atr_5m: float
    range_pct_30m: float  # 30-min high-low range as % of spot
    rvol_15m: float  # 15-min relative volume vs session average
    directional_purity: float  # 0.0 to 1.0 (clean trend vs whipsaw)
    is_leader: bool
    is_choppy: bool
    updated_at: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "velocity_score": round(self.velocity_score, 1),
            "regime": self.regime,
            "spot": round(self.spot, 2),
            "change_pct": round(self.change_pct, 2),
            "atr_5m": round(self.atr_5m, 2),
            "range_pct_30m": round(self.range_pct_30m, 3),
            "rvol_15m": round(self.rvol_15m, 2),
            "directional_purity": round(self.directional_purity, 2),
            "is_leader": self.is_leader,
            "is_choppy": self.is_choppy,
            "updated_at": self.updated_at,
            "summary": self.summary,
        }


@dataclass
class RocMomentumMetric:
    """Quantitative Rate-of-Change (ROC) and acceleration metrics on 5m OHLCV."""

    symbol: str
    consecutive_up: bool  # c[-1] > c[-2] > c[-3]
    consecutive_down: bool  # c[-1] < c[-2] < c[-3]
    roc_1: float  # 1-bar ROC %: (c[-1] - c[-2]) / c[-2] * 100
    roc_2: float  # Previous 1-bar ROC %: (c[-2] - c[-3]) / c[-3] * 100
    roc_3bar: float  # 3-bar ROC %: (c[-1] - c[-4]) / c[-4] * 100
    is_accelerating_up: bool  # consecutive_up and roc_1 > roc_2 > 0
    is_accelerating_down: bool  # consecutive_down and roc_1 < roc_2 < 0 (faster drop)
    is_decelerating_up: bool  # Price rising, but momentum stalling: roc_1 < roc_2 and roc_1 <= 0.05
    is_decelerating_down: (
        bool  # Price falling, but momentum stalling: roc_1 > roc_2 and roc_1 >= -0.05
    )
    is_meaningful_up: bool  # Exceeds index-specific threshold for genuine impulse
    is_meaningful_down: bool  # Exceeds index-specific threshold for genuine breakdown
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "consecutive_up": self.consecutive_up,
            "consecutive_down": self.consecutive_down,
            "roc_1": round(self.roc_1, 3),
            "roc_2": round(self.roc_2, 3),
            "roc_3bar": round(self.roc_3bar, 3),
            "is_accelerating_up": self.is_accelerating_up,
            "is_accelerating_down": self.is_accelerating_down,
            "is_decelerating_up": self.is_decelerating_up,
            "is_decelerating_down": self.is_decelerating_down,
            "is_meaningful_up": self.is_meaningful_up,
            "is_meaningful_down": self.is_meaningful_down,
            "summary": self.summary,
        }


# ── Thread-safe TTL Cache for Velocity Metrics ─────────────────────────
_velocity_cache_lock = threading.Lock()
_velocity_cache: dict[str, tuple[float, IndexVelocityMetric]] = {}
_CACHE_TTL_SECONDS = 15.0  # 15s cache matching index polling loop


def _resolve_exchange(symbol: str) -> str:
    clean = symbol.replace("NSE:", "").replace("BSE:", "").strip().upper()
    if clean in ("SENSEX", "BANKEX"):
        return "BSE"
    return "NSE"


def calculate_index_velocity(
    symbol: str,
    ohlcv_5m: Optional[pd.DataFrame] = None,
    spot: Optional[float] = None,
    change_pct: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    force_refresh: bool = False,
) -> IndexVelocityMetric:
    """
    Computes real-time Index Velocity Score (IVS) for a single index.
    Returns cached metric if fresh (< 15s).
    """
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip().upper()
    now_ts = time.time()

    if not force_refresh:
        with _velocity_cache_lock:
            cached = _velocity_cache.get(clean_sym)
            if cached and (now_ts - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]

    # Resolve live quote data if not provided
    if spot is None or spot <= 0 or change_pct is None:
        try:
            from market.quotes import get_quote

            exch = _resolve_exchange(clean_sym)
            lookup = f"{exch}:{clean_sym}"
            raw = get_quote(lookup)
            q = raw.get(lookup) or raw.get(clean_sym)
            if q:
                spot = float(getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or 0.0)
                change_pct = float(getattr(q, "change_pct", 0.0) or 0.0)
                day_high = float(getattr(q, "high", 0.0) or getattr(q, "day_high", 0.0) or 0.0)
                day_low = float(getattr(q, "low", 0.0) or getattr(q, "day_low", 0.0) or 0.0)
        except Exception as e:
            logger.debug(f"[IndexVelocity] Quote fetch fallback for {clean_sym}: {e}")

    spot = spot or 1000.0
    change_pct = change_pct or 0.0

    # Fetch 5m OHLCV if not provided
    if ohlcv_5m is None:
        try:
            from market.history import get_ohlcv

            exch = _resolve_exchange(clean_sym)
            ohlcv_5m = get_ohlcv(clean_sym, exchange=exch, interval="5minute", days=2)
        except Exception as e:
            logger.debug(f"[IndexVelocity] OHLCV fetch error for {clean_sym}: {e}")

    # Fallback path if OHLCV is completely unavailable
    if ohlcv_5m is None or len(ohlcv_5m) < 4:
        # Approximate metrics using day range
        day_range = max(0.01, (day_high or spot) - (day_low or spot))
        range_pct_30m = round((day_range / max(1.0, spot)) * 100 * 0.4, 3)
        atr_5m = round(day_range * 0.08, 2)
        rvol_15m = 1.0
        directional_purity = 0.5

        # Heuristic score based on change magnitude
        base_score = min(75.0, abs(change_pct) * 35.0)
        regime = "NORMAL_TREND"
        if base_score >= 60 and range_pct_30m >= 0.25:
            regime = "LEADER_EXPANSION"
        elif base_score < 30 or range_pct_30m < 0.15:
            regime = "CHOP_PINNED"

        metric = IndexVelocityMetric(
            symbol=clean_sym,
            velocity_score=round(base_score, 1),
            regime=regime,
            spot=spot,
            change_pct=change_pct,
            atr_5m=atr_5m,
            range_pct_30m=range_pct_30m,
            rvol_15m=rvol_15m,
            directional_purity=directional_purity,
            is_leader=(regime == "LEADER_EXPANSION"),
            is_choppy=(regime == "CHOP_PINNED"),
            updated_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            summary=f"{clean_sym} {regime} (Est Score: {base_score:.0f}/100)",
        )
        with _velocity_cache_lock:
            _velocity_cache[clean_sym] = (now_ts, metric)
        return metric

    # ── Full Quantitative Metrics from 5m OHLCV ───────────────────────────
    col_h = "high" if "high" in ohlcv_5m.columns else "High"
    col_l = "low" if "low" in ohlcv_5m.columns else "Low"
    col_c = "close" if "close" in ohlcv_5m.columns else "Close"
    col_v = "volume" if "volume" in ohlcv_5m.columns else "Volume"

    df_tail = ohlcv_5m.tail(12)  # Last 60 minutes
    highs = df_tail[col_h].values
    lows = df_tail[col_l].values
    closes = df_tail[col_c].values
    volumes = df_tail[col_v].values

    # 1. 5-min ATR over last 6 bars
    bar_ranges = [max(0.01, highs[i] - lows[i]) for i in range(len(highs))]
    atr_5m = float(sum(bar_ranges[-6:]) / max(1, len(bar_ranges[-6:])))

    # 2. 15-min Price Expansion (last 3 bars) vs ATR
    recent_3_high = max(highs[-3:])
    recent_3_low = min(lows[-3:])
    range_15m = recent_3_high - recent_3_low
    atr_expansion_ratio = range_15m / max(0.01, atr_5m * 2.2)

    # 3. 30-min High-Low Range as % of Spot
    recent_6_high = max(highs[-6:])
    recent_6_low = min(lows[-6:])
    range_30m = recent_6_high - recent_6_low
    range_pct_30m = (range_30m / max(1.0, spot)) * 100.0

    # 4. Relative Volume (RVOL 15m)
    vol_recent_3 = sum(volumes[-3:])
    avg_vol_prior = (sum(volumes) - vol_recent_3) / max(1, len(volumes) - 3)
    rvol_15m = (vol_recent_3 / 3.0) / max(1.0, avg_vol_prior) if avg_vol_prior > 0 else 1.0

    # 5. Directional Purity (Net Move / Total Traveled Path over last 3 bars)
    net_move_15m = abs(closes[-1] - closes[-3]) if len(closes) >= 3 else 0.0
    traveled_path_15m = sum(bar_ranges[-3:])
    directional_purity = min(1.0, net_move_15m / max(0.01, traveled_path_15m))

    # ── Composite Velocity Score (0 to 100) ──────────────────────────────
    # A. Expansion component (0-40 pts): atr_expansion_ratio >= 1.5 gives max
    expansion_pts = min(40.0, atr_expansion_ratio * 26.6)

    # B. Volume Surge component (0-30 pts): RVOL >= 2.0x gives max
    rvol_pts = min(30.0, rvol_15m * 15.0)

    # C. Trend Purity component (0-30 pts): pure directional candle gives max
    purity_pts = directional_purity * 30.0

    velocity_score = round(expansion_pts + rvol_pts + purity_pts, 1)

    # ── Regime Classification ───────────────────────────────────────────
    # A. Leader: High Velocity (>= 60) AND 30m Range >= 0.22%
    # B. Chop Pinned: Low Velocity (< 38) OR 30m Range < 0.16%
    # C. Normal Trend: in between
    if velocity_score >= 60.0 and range_pct_30m >= 0.22:
        regime = "LEADER_EXPANSION"
    elif velocity_score < 38.0 or range_pct_30m < 0.16:
        regime = "CHOP_PINNED"
    else:
        regime = "NORMAL_TREND"

    summary = (
        f"{clean_sym} {regime} (IVS: {velocity_score:.0f}/100 | "
        f"RVOL: {rvol_15m:.1f}x | 30m Rng: {range_pct_30m:.2f}%)"
    )

    metric = IndexVelocityMetric(
        symbol=clean_sym,
        velocity_score=velocity_score,
        regime=regime,
        spot=round(spot, 2),
        change_pct=round(change_pct, 2),
        atr_5m=round(atr_5m, 2),
        range_pct_30m=round(range_pct_30m, 3),
        rvol_15m=round(rvol_15m, 2),
        directional_purity=round(directional_purity, 2),
        is_leader=(regime == "LEADER_EXPANSION"),
        is_choppy=(regime == "CHOP_PINNED"),
        updated_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        summary=summary,
    )

    with _velocity_cache_lock:
        _velocity_cache[clean_sym] = (now_ts, metric)

    return metric


def rank_indices_by_velocity(
    indices: Optional[list[str]] = None,
    force_refresh: bool = False,
) -> list[IndexVelocityMetric]:
    """
    Ranks all watched indices from highest velocity (Leader) to lowest (Chop).
    Returns sorted list of IndexVelocityMetric.
    """
    targets = indices or DEFAULT_WATCHED_INDICES
    metrics: list[IndexVelocityMetric] = []

    for sym in targets:
        try:
            m = calculate_index_velocity(sym, force_refresh=force_refresh)
            metrics.append(m)
        except Exception as e:
            logger.debug(f"[IndexVelocity] Error ranking {sym}: {e}")

    # Sort descending by velocity score
    metrics.sort(key=lambda m: (-m.velocity_score, -m.range_pct_30m))

    # Mark top 1 or 2 as leader if score is >= 50
    for i, m in enumerate(metrics):
        if i == 0 and m.velocity_score >= 50.0:
            m.is_leader = True
            if m.regime != "CHOP_PINNED":
                m.regime = "LEADER_EXPANSION"

    return metrics


def get_prioritized_index_symbols(indices: Optional[list[str]] = None) -> list[str]:
    """
    Returns index symbols sorted by Velocity: fastest moving index first!
    """
    ranked = rank_indices_by_velocity(indices)
    return [m.symbol for m in ranked]


# ── ROC Momentum & Acceleration Calculator ─────────────────────────────


def calculate_roc_momentum(
    ohlcv_5m: Optional[pd.DataFrame],
    symbol: str = "",
) -> RocMomentumMetric:
    """
    Computes 3-bar Rate of Change (ROC) and 2nd derivative acceleration on 5m OHLCV.
    Deterministic, zero-network, defensive against missing/empty DataFrames.

    Formulation:
      ROC_1 = (c[-1] - c[-2]) / c[-2] * 100
      ROC_2 = (c[-2] - c[-3]) / c[-3] * 100
      ROC_3bar = (c[-1] - c[-4]) / c[-4] * 100
      is_accelerating_up = consecutive_up and ROC_1 > ROC_2 > 0
      is_accelerating_down = consecutive_down and ROC_1 < ROC_2 < 0
      is_decelerating_up = ROC_2 > 0 and ROC_1 < ROC_2 and ROC_1 <= 0.05 (stalling near highs)
      is_decelerating_down = ROC_2 < 0 and ROC_1 > ROC_2 and ROC_1 >= -0.05 (stalling near lows)
    """
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip().upper()

    null_metric = RocMomentumMetric(
        symbol=clean_sym,
        consecutive_up=False,
        consecutive_down=False,
        roc_1=0.0,
        roc_2=0.0,
        roc_3bar=0.0,
        is_accelerating_up=False,
        is_accelerating_down=False,
        is_decelerating_up=False,
        is_decelerating_down=False,
        is_meaningful_up=False,
        is_meaningful_down=False,
        summary=f"{clean_sym} ROC: Insufficient data",
    )

    if ohlcv_5m is None or not hasattr(ohlcv_5m, "iloc") or len(ohlcv_5m) < 3:
        return null_metric

    try:
        col_c = "close" if "close" in ohlcv_5m.columns else "Close"
        closes = [float(x) for x in ohlcv_5m[col_c].values]
        if len(closes) < 3:
            return null_metric

        c1 = closes[-1]
        c2 = closes[-2]
        c3 = closes[-3]
        c4 = closes[-4] if len(closes) >= 4 else closes[-3]

        if c2 <= 0 or c3 <= 0 or c4 <= 0:
            return null_metric

        roc_1 = ((c1 - c2) / c2) * 100.0
        roc_2 = ((c2 - c3) / c3) * 100.0
        roc_3bar = ((c1 - c4) / c4) * 100.0

        consecutive_up = bool(c1 > c2 > c3)
        consecutive_down = bool(c1 < c2 < c3)

        is_accelerating_up = bool(consecutive_up and roc_1 > roc_2 > 0)
        is_accelerating_down = bool(consecutive_down and roc_1 < roc_2 < 0)

        # Deceleration / Stalling at high:
        # Prior bars were green (roc_2 > 0), but latest bar is smaller or stalled near zero (roc_1 <= 0.05)
        is_decelerating_up = bool(roc_2 > 0 and roc_1 < roc_2 and roc_1 <= 0.05)
        # Deceleration / Stalling at low:
        is_decelerating_down = bool(roc_2 < 0 and roc_1 > roc_2 and roc_1 >= -0.05)

        # Index-specific meaningful magnitude thresholds:
        # High-beta / larger point indices (BANKNIFTY, SENSEX, BANKEX) need slightly higher threshold
        is_high_beta = clean_sym in ("BANKNIFTY", "SENSEX", "BANKEX")
        up_thresh_1 = 0.15 if is_high_beta else 0.10
        up_thresh_3 = 0.30 if is_high_beta else 0.20
        is_meaningful_up = bool(roc_1 >= up_thresh_1 or roc_3bar >= up_thresh_3)

        down_thresh_1 = -0.15 if is_high_beta else -0.10
        down_thresh_3 = -0.30 if is_high_beta else -0.20
        is_meaningful_down = bool(roc_1 <= down_thresh_1 or roc_3bar <= down_thresh_3)

        if is_accelerating_up:
            state = f"ACCELERATING_UP (+{roc_1:.2f}% vs +{roc_2:.2f}%)"
        elif is_accelerating_down:
            state = f"ACCELERATING_DOWN ({roc_1:.2f}% vs {roc_2:.2f}%)"
        elif is_decelerating_up:
            state = f"STALLING_AT_TOP ({roc_1:+.2f}% vs +{roc_2:.2f}%)"
        elif is_decelerating_down:
            state = f"STALLING_AT_BOTTOM ({roc_1:+.2f}% vs {roc_2:.2f}%)"
        else:
            state = f"STEADY ({roc_1:+.2f}%)"

        summary = f"{clean_sym} 5m ROC: {state} | 3-bar: {roc_3bar:+.2f}%"

        return RocMomentumMetric(
            symbol=clean_sym,
            consecutive_up=consecutive_up,
            consecutive_down=consecutive_down,
            roc_1=round(roc_1, 3),
            roc_2=round(roc_2, 3),
            roc_3bar=round(roc_3bar, 3),
            is_accelerating_up=is_accelerating_up,
            is_accelerating_down=is_accelerating_down,
            is_decelerating_up=is_decelerating_up,
            is_decelerating_down=is_decelerating_down,
            is_meaningful_up=is_meaningful_up,
            is_meaningful_down=is_meaningful_down,
            summary=summary,
        )
    except Exception as e:
        logger.debug(f"[IndexVelocity] ROC calculation error for {clean_sym}: {e}")
        return null_metric


# ── Option Premium Velocity Tracker (₹/min) ───────────────────────────
_premium_velocity_lock = threading.Lock()
# contract_symbol -> (last_timestamp, last_ltp, smoothed_velocity_rs_per_min)
_PREMIUM_VELOCITY_CACHE: dict[str, tuple[float, float, float]] = {}


def calculate_premium_velocity(
    contract_symbol: str,
    ltp: float,
    now_ts: Optional[float] = None,
) -> float:
    """
    Computes real-time option premium velocity (₹ / minute rate of change).
    Thread-safe with bounded TTL eviction.
    Returns:
        Velocity in ₹ per minute (positive = expanding premium, negative = decaying/falling).
    """
    if not contract_symbol or ltp <= 0:
        return 0.0

    ts = now_ts if now_ts is not None else time.time()
    clean_sym = contract_symbol.strip().upper()

    with _premium_velocity_lock:
        # Periodic cleanup of entries older than 10 minutes
        if len(_PREMIUM_VELOCITY_CACHE) > 500:
            stale_keys = [k for k, v in _PREMIUM_VELOCITY_CACHE.items() if (ts - v[0]) > 600.0]
            for k in stale_keys:
                _PREMIUM_VELOCITY_CACHE.pop(k, None)

        cached = _PREMIUM_VELOCITY_CACHE.get(clean_sym)
        if cached is None:
            _PREMIUM_VELOCITY_CACHE[clean_sym] = (ts, ltp, 0.0)
            return 0.0

        last_ts, last_ltp, prev_vel = cached
        dt = ts - last_ts

        # Wait at least 3 seconds between updates to avoid tick-noise spikes
        if dt < 3.0:
            return prev_vel

        # Calculate instantaneous velocity: ₹ change per minute
        dl = ltp - last_ltp
        inst_vel = (dl / dt) * 60.0

        # Exponential moving average smoothing: 0.6 * inst + 0.4 * prev
        smoothed_vel = round(0.6 * inst_vel + 0.4 * prev_vel, 2)
        _PREMIUM_VELOCITY_CACHE[clean_sym] = (ts, ltp, smoothed_vel)
        return smoothed_vel
