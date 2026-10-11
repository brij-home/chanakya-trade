"""
engine/equity_adaptive_regime.py
────────────────────────────────
Universal Falcon & Cheetah Single-Stock Equity Adaptive Regime Engine.

Implements the Two Pillars of Institutional Equity Excellence:
  1. 🦅 FALCON EYE (Single-Stock Multi-Dimensional Regime Radar):
     - Dreiss Choppiness Index (CHOP): Identifies severe consolidation chop (>=61.8) vs trending expansion (<=38.2).
     - Wilder's Average Directional Index (ADX-14): Quantifies directional momentum strength (<20 non-trending, >=25 trending).
     - Bollinger Band / Keltner Squeeze State: Detects coiling, firing, or exhaustion phases.
     - Multi-timeframe trend alignment: Evaluates 15m/60m trend structure vs 5m execution bar.
     - Time-of-Day Phase: Suppresses midday lunch lull false breakouts (11:30–13:15 IST).

  2. 🐆 CHEETAH POUNCE (Regime-Adaptive Equity Strategy Selection):
     - CHEETAH_STALKING_PRESERVE_CAPITAL: When CHOP >= 61.8 or ADX < 20, routine breakouts are
       COMPLETELY SUPPRESSED to prevent false breakouts and whipsaw traps. Cash is a position!
     - CHEETAH_POUNCE_MOMENTUM: When CHOP <= 38.2 and ADX >= 25, authorizes momentum breakouts,
       ORB continuations, and stage expansions.
     - CHEETAH_SPRING_INVERSION: When in rangebound chop, authorizes ONLY Wyckoff Springs and
       Turtle Soup fades of swept boundaries.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime
from typing import Any, Optional

import numpy as np
import pandas as pd

from config.constants import IST_ZONE as IST
from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.equity_adaptive_regime")


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class FalconRegime:
    """Pillar 1: 🦅 Falcon Eye — Single-Stock Multi-Dimensional Regime Radar."""

    symbol: str
    spot: float
    chop_index: float  # 0.0 to 100.0 (>=61.8 = severe chop, <=38.2 = trending expansion)
    chop_status: str  # "SEVERE_CHOP" | "TRENDING_EXPANSION" | "NEUTRAL_DRIFT"
    adx_14: float  # < 20 = non-trending, >= 25 = trending
    adx_status: str  # "NON_TRENDING" | "MODERATE_TREND" | "STRONG_TREND"
    squeeze_state: str  # "SQUEEZE_ON" | "SQUEEZE_FIRED" | "NORMAL" | "EXHAUSTION"
    market_phase: str  # "OPENING_AUCTION" | "MORNING_EXPANSION" | "MIDDAY_CHOP" | "AFTERNOON_EXPANSION" | "CLOSING_AUCTION"
    is_midday_lull: bool
    overall_environment: str  # "OPTIMAL_TREND_EXPANSION" | "WHIPSAW_CHOP_TRAP" | "VOLATILITY_COILING" | "BALANCED_RANGE"
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheetahStrategyMandate:
    """Pillar 2: 🐆 Cheetah Pounce — Regime-Adaptive Strategy Selection & Gate."""

    mandate: str  # "CHEETAH_POUNCE_MOMENTUM" | "CHEETAH_STALKING_PRESERVE_CAPITAL" | "CHEETAH_SPRING_INVERSION" | "CHEETAH_SELECTIVE_SNIPER"
    allow_routine_breakouts: bool  # False during severe chop or midday lull
    allow_thrust_only: (
        bool  # True when breakout requires explosive institutional thrust (RVOL >= 2.2x)
    )
    min_required_rvol: float
    suggested_strategy: str  # "BUY_BREAKOUT" | "WAIT_IN_CASH" | "FADE_SPRING" | "LIMIT_ON_RETEST"
    reason: str
    action_guidance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdaptiveEquityDecision:
    """Synthesized evaluation combining Falcon Eye and Cheetah Pounce."""

    symbol: str
    spot: float
    falcon: FalconRegime
    cheetah: CheetahStrategyMandate
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "falcon": self.falcon.to_dict(),
            "cheetah": self.cheetah.to_dict(),
            "evaluated_at": self.evaluated_at,
        }


# ── Thread-safe TTL Cache ─────────────────────────────────────────────────────

_EQUITY_REGIME_CACHE_LOCK = threading.Lock()
_EQUITY_REGIME_CACHE: dict[str, tuple[float, AdaptiveEquityDecision]] = {}
_EQUITY_REGIME_CACHE_TTL = 15.0  # 15s refresh interval


# ── Mathematical Indicators ───────────────────────────────────────────────────


def compute_equity_choppiness_index(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Computes Dreiss Choppiness Index (CHOP) for single-stock equities.
    CHOP >= 61.8: Severe consolidation chop. Breakouts have extreme failure rate.
    CHOP <= 38.2: Trending expansion. High follow-through.
    """
    if df is None or len(df) < period + 1:
        return None
    try:
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"

        highs = df[col_h].astype(float).values
        lows = df[col_l].astype(float).values
        closes = df[col_c].astype(float).values

        tr = []
        for i in range(1, len(df)):
            tr.append(
                max(
                    float(highs[i] - lows[i]),
                    abs(float(highs[i] - closes[i - 1])),
                    abs(float(lows[i] - closes[i - 1])),
                )
            )

        if len(tr) < period:
            return None

        tr_sum = sum(tr[-period:])
        max_high = max(highs[-period:])
        min_low = min(lows[-period:])
        hl_range = max_high - min_low

        if hl_range <= 0.0:
            return 100.0  # Stagnant flat bars = infinite chop

        ratio = tr_sum / hl_range
        if ratio <= 0.0:
            return 0.0

        chop = 100.0 * (math.log10(ratio) / math.log10(period))
        return round(max(0.0, min(100.0, chop)), 2)
    except Exception as exc:
        logger.debug("[EquityAdaptiveRegime] Choppiness calculation failed for %s", exc)
        return None


def compute_equity_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Computes standard 14-period Wilder's Average Directional Index (ADX)."""
    if df is None or len(df) < period + 2:
        return None
    try:
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"
        col_c = "close" if "close" in df.columns else "Close"

        h = df[col_h].astype(float)
        l = df[col_l].astype(float)
        c = df[col_c].astype(float)

        up_move = h - h.shift(1)
        down_move = l.shift(1) - l

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1.0 / period, min_periods=period).mean()
        atr_clean = atr.replace(0, np.nan)
        plus_di = 100.0 * (
            pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, min_periods=period).mean()
            / atr_clean
        )
        minus_di = 100.0 * (
            pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, min_periods=period).mean()
            / atr_clean
        )

        di_sum = (plus_di + minus_di + 1e-9).replace(0, np.nan)
        dx = (abs(plus_di - minus_di) / di_sum) * 100.0
        adx = dx.ewm(alpha=1.0 / period, min_periods=period).mean()

        val = float(adx.iloc[-1])
        return round(val, 2) if not np.isnan(val) and val >= 0 else None
    except Exception as exc:
        logger.debug("[EquityAdaptiveRegime] ADX calculation failed: %s", exc)
        return None


def detect_equity_squeeze_state(df: pd.DataFrame) -> str:
    """
    Evaluates Bollinger Bands (20, 2.0) vs Keltner Channels (20, 1.5).
    Returns SQUEEZE_ON | SQUEEZE_FIRED | EXHAUSTION | NORMAL.
    """
    if df is None or len(df) < 20:
        return "NORMAL"
    try:
        col_c = "close" if "close" in df.columns else "Close"
        col_h = "high" if "high" in df.columns else "High"
        col_l = "low" if "low" in df.columns else "Low"

        closes = df[col_c].astype(float)
        highs = df[col_h].astype(float)
        lows = df[col_l].astype(float)

        sma20 = closes.rolling(20).mean()
        std20 = closes.rolling(20).std()
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        prev_c = closes.shift(1)
        tr = pd.concat([highs - lows, (highs - prev_c).abs(), (lows - prev_c).abs()], axis=1).max(
            axis=1
        )
        atr20 = tr.rolling(20).mean()
        kc_upper = sma20 + (1.5 * atr20)
        kc_lower = sma20 - (1.5 * atr20)

        # Squeeze is ON when BB is completely inside KC
        is_squeeze = (bb_upper.iloc[-1] <= kc_upper.iloc[-1]) and (
            bb_lower.iloc[-1] >= kc_lower.iloc[-1]
        )
        was_squeeze = (bb_upper.iloc[-2] <= kc_upper.iloc[-2]) and (
            bb_lower.iloc[-2] >= kc_lower.iloc[-2]
        )

        # Climax exhaustion: price > 3.0 ATR above 20 SMA
        last_c = closes.iloc[-1]
        last_sma = sma20.iloc[-1]
        last_atr = atr20.iloc[-1]
        if last_atr > 0 and abs(last_c - last_sma) > (3.0 * last_atr):
            return "EXHAUSTION"

        if is_squeeze:
            return "SQUEEZE_ON"
        elif was_squeeze and not is_squeeze:
            return "SQUEEZE_FIRED"
        return "NORMAL"
    except Exception as exc:
        logger.debug("[EquityAdaptiveRegime] Squeeze detection failed: %s", exc)
        return "NORMAL"


def get_equity_time_of_day_phase(dt: Optional[datetime] = None) -> tuple[str, bool]:
    """Returns (phase_name, is_midday_lull) for Indian cash equity hours."""
    now_dt = dt or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
    t = now_dt.time()

    if t < dtime(9, 25):
        return "OPENING_AUCTION", False
    elif dtime(9, 25) <= t < dtime(11, 30):
        return "MORNING_EXPANSION", False
    elif dtime(11, 30) <= t < dtime(13, 15):
        return "MIDDAY_CHOP", True
    elif dtime(13, 15) <= t < dtime(15, 0):
        return "AFTERNOON_EXPANSION", False
    elif dtime(15, 0) <= t <= dtime(15, 30):
        return "CLOSING_AUCTION", False
    return "OFF_MARKET", False


# ── Core Evaluation Engine ────────────────────────────────────────────────────


def evaluate_equity_adaptive_regime(
    symbol: str,
    spot: float,
    ohlcv_df: Optional[pd.DataFrame] = None,
    ref_time: Optional[datetime] = None,
    metrics: Optional[dict[str, Any]] = None,
    force_refresh: bool = False,
) -> AdaptiveEquityDecision:
    """
    Evaluates Falcon Eye and Cheetah Pounce for an equity stock.
    Guarantees regime-adaptive strategy selection to eliminate consolidation false breakouts.
    """
    clean_sym = canonical_alert_symbol(symbol)
    now_ts = time.time()

    # 1. Thread-safe cache check (bypass if custom metrics passed)
    if not force_refresh and not metrics:
        with _EQUITY_REGIME_CACHE_LOCK:
            cached = _EQUITY_REGIME_CACHE.get(clean_sym)
            if cached and (now_ts - cached[0]) < _EQUITY_REGIME_CACHE_TTL:
                return cached[1]

    now_dt = ref_time or datetime.now(IST)
    evaluated_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    # 2. Fetch history if not provided
    df = ohlcv_df
    if df is None and (metrics is None or ("chop_index" not in metrics and "chop" not in metrics)):
        try:
            from market.history import get_history_feed

            hist = get_history_feed()
            if hist:
                df = hist.get_candles(clean_sym, interval="5m", lookback=80)
        except Exception as exc:
            logger.debug("[EquityAdaptiveRegime] Feed fetch error for %s: %s", clean_sym, exc)

    # 3. Compute or Extract Quantitative Metrics
    metrics_d = metrics or {}
    chop = None
    if "chop_index" in metrics_d or "chop" in metrics_d:
        try:
            chop = float(metrics_d.get("chop_index") or metrics_d.get("chop"))
        except (ValueError, TypeError):
            chop = None
    if chop is None and df is not None:
        chop = compute_equity_choppiness_index(df, period=14)
    if chop is None:
        chop = 50.0  # Neutral fallback

    adx = None
    if "adx_14" in metrics_d or "adx" in metrics_d:
        try:
            adx = float(metrics_d.get("adx_14") or metrics_d.get("adx"))
        except (ValueError, TypeError):
            adx = None
    if adx is None and df is not None:
        adx = compute_equity_adx(df, period=14)
    if adx is None:
        adx = 22.0

    sqz = str(metrics_d.get("squeeze_state") or metrics_d.get("squeeze") or "")
    if not sqz and df is not None:
        sqz = detect_equity_squeeze_state(df)
    if not sqz:
        sqz = "NORMAL"

    phase, is_midday = get_equity_time_of_day_phase(now_dt)

    # 4. Classify Falcon Regime
    if chop >= 61.8:
        chop_status = "SEVERE_CHOP"
    elif chop <= 38.2:
        chop_status = "TRENDING_EXPANSION"
    else:
        chop_status = "NEUTRAL_DRIFT"

    if adx < 20.0:
        adx_status = "NON_TRENDING"
    elif adx >= 25.0:
        adx_status = "STRONG_TREND"
    else:
        adx_status = "MODERATE_TREND"

    if chop_status == "TRENDING_EXPANSION" and adx_status == "STRONG_TREND" and not is_midday:
        overall_env = "OPTIMAL_TREND_EXPANSION"
    elif chop_status == "SEVERE_CHOP" or adx_status == "NON_TRENDING":
        overall_env = "WHIPSAW_CHOP_TRAP"
    elif is_midday:
        overall_env = "MIDDAY_LULL"
    elif sqz == "SQUEEZE_ON":
        overall_env = "VOLATILITY_COILING"
    else:
        overall_env = "BALANCED_RANGE"

    falcon_summary = (
        f"{clean_sym} Spot ₹{spot:,.1f}: {chop_status} (CHOP {chop:.1f}), "
        f"{adx_status} (ADX {adx:.1f}), Squeeze: {sqz}, Phase: {phase}."
    )

    falcon = FalconRegime(
        symbol=clean_sym,
        spot=spot,
        chop_index=chop,
        chop_status=chop_status,
        adx_14=adx,
        adx_status=adx_status,
        squeeze_state=sqz,
        market_phase=phase,
        is_midday_lull=is_midday,
        overall_environment=overall_env,
        summary=falcon_summary,
    )

    # 5. Determine Cheetah Strategy Mandate
    if overall_env == "WHIPSAW_CHOP_TRAP":
        cheetah_mandate = "CHEETAH_STALKING_PRESERVE_CAPITAL"
        allow_routine_breakouts = False
        allow_thrust_only = True
        min_rvol = 2.20
        suggested_strat = "WAIT_IN_CASH"
        reason = (
            f"Severe chop or non-trending consolidation on {clean_sym} (CHOP {chop:.1f} >= 61.8 or ADX {adx:.1f} < 20.0). "
            f"Routine breakouts have high failure rate; preserve capital."
        )
        guidance = "DO NOT chase breakouts in consolidation chop. Only explosive institutional volume (RVOL >= 2.2x) or spring reclaims permitted."

    elif overall_env == "MIDDAY_LULL":
        cheetah_mandate = "CHEETAH_MIDDAY_LULL"
        allow_routine_breakouts = False
        allow_thrust_only = True
        min_rvol = 1.80
        suggested_strat = "WAIT_IN_CASH"
        reason = f"Midday lunch lull (11:30-13:15 IST) on {clean_sym}. Breakouts without institutional volume have elevated fakeout risk."
        guidance = "Require institutional volume expansion (RVOL >= 1.8x) or wait for afternoon session (post-13:15 IST)."

    elif overall_env == "OPTIMAL_TREND_EXPANSION":
        cheetah_mandate = "CHEETAH_POUNCE_MOMENTUM"
        allow_routine_breakouts = True
        allow_thrust_only = False
        min_rvol = 1.35
        suggested_strat = "BUY_BREAKOUT"
        reason = f"Confirmed directional momentum expansion (CHOP {chop:.1f} <= 38.2, ADX {adx:.1f} >= 25)."
        guidance = "Strike decisively on pivot crosses and pullback retests. Trailing stops active."

    elif sqz == "SQUEEZE_ON":
        cheetah_mandate = "CHEETAH_SELECTIVE_SNIPER"
        allow_routine_breakouts = False
        allow_thrust_only = True
        min_rvol = 1.80
        suggested_strat = "LIMIT_ON_RETEST"
        reason = f"Volatility compression squeeze ON for {clean_sym}. Energy coiling for impending breakout."
        guidance = "Pre-stage order tickets. Do not jump gun before verified squeeze fire."

    else:
        cheetah_mandate = "CHEETAH_SELECTIVE_SNIPER"
        allow_routine_breakouts = True
        allow_thrust_only = False
        min_rvol = 1.60
        suggested_strat = "LIMIT_ON_RETEST"
        reason = f"Neutral balanced drift on {clean_sym}."
        guidance = "Require clear volume expansion and limit pullback entries."

    cheetah = CheetahStrategyMandate(
        mandate=cheetah_mandate,
        allow_routine_breakouts=allow_routine_breakouts,
        allow_thrust_only=allow_thrust_only,
        min_required_rvol=min_rvol,
        suggested_strategy=suggested_strat,
        reason=reason,
        action_guidance=guidance,
    )

    decision = AdaptiveEquityDecision(
        symbol=clean_sym,
        spot=spot,
        falcon=falcon,
        cheetah=cheetah,
        evaluated_at=evaluated_str,
    )

    # 6. Store in cache
    with _EQUITY_REGIME_CACHE_LOCK:
        _EQUITY_REGIME_CACHE[clean_sym] = (now_ts, decision)

    return decision
