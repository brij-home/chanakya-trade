"""
analysis/dmi_filter.py
──────────────────────
Institutional Triple-Filtered Directional Movement Index (DMI) Entry Engine.
Implements the 3-tier Swingscape DMI momentum filters to eliminate weak crossovers
and false trend breakouts in choppy or range-bound markets.

Core Quantitative Concepts:
  Why most DMI crossovers fail:
    - False crossovers in sideways chop (crossovers below 20-25 indicate no institutional momentum).
    - Weak trend follow-through without sustained buyer/seller control.

  The 3 Powerful Filters (#TripleDMIStrategy):
    1. Crossover Above Threshold (>=25 by default, >=22 for fast intraday):
       +DI must cross above -DI STRICTLY above the threshold level. Crossovers below are discarded as noise.
    2. +DI Must Stay Above Threshold:
       After crossover, +DI maintains its position above the threshold, verifying sustained buyer control.
    3. +DI Breaks Previous -DI Pivot:
       +DI must break above the peak swing high of -DI during the prior down move.
       This confirms momentum dominance: buying power exceeds peak selling panic!

  Symmetric Bearish Model (for Puts / Short Setups):
    1. -DI crosses above +DI above threshold.
    2. -DI stays above threshold.
    3. -DI breaks above the previous +DI swing high pivot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.analysis.dmi_filter")


@dataclass
class DMITripleFilterResult:
    """Quantitative result of the 3-tier DMI entry filter."""

    symbol: str
    timeframe: str  # "INTRADAY" | "DAILY" | "SWING"
    plus_di: float
    minus_di: float
    adx: float
    threshold: float
    crossover_type: str  # "BULLISH_CROSS" | "BEARISH_CROSS" | "NONE"
    crossover_above_threshold: bool
    plus_di_above_threshold: bool
    minus_di_above_threshold: bool
    prev_minus_di_pivot: float
    prev_plus_di_pivot: float
    breaks_opposite_pivot: bool
    verdict: str  # "TRIPLE_BULLISH_CONFIRMED" | "TRIPLE_BEARISH_CONFIRMED" | "WEAK_OR_CHOPPY" | "NEUTRAL"
    confidence_score: float  # 0.0 to 100.0
    summary: str
    adx_slope_3bar: float = 0.0  # Trend acceleration (d(ADX)/dt over 3 bars)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "plus_di": round(self.plus_di, 2),
            "minus_di": round(self.minus_di, 2),
            "adx": round(self.adx, 2),
            "adx_slope_3bar": round(self.adx_slope_3bar, 2),
            "threshold": self.threshold,
            "crossover_type": self.crossover_type,
            "crossover_above_threshold": self.crossover_above_threshold,
            "plus_di_above_threshold": self.plus_di_above_threshold,
            "minus_di_above_threshold": self.minus_di_above_threshold,
            "prev_minus_di_pivot": round(self.prev_minus_di_pivot, 2),
            "prev_plus_di_pivot": round(self.prev_plus_di_pivot, 2),
            "breaks_opposite_pivot": self.breaks_opposite_pivot,
            "verdict": self.verdict,
            "confidence_score": round(self.confidence_score, 1),
            "summary": self.summary,
        }


def compute_dmi_series(
    df: pd.DataFrame, period: int = 14
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Computes Wilder's +DI, -DI, and ADX series on an OHLCV DataFrame.
    """
    if df is None or len(df) < period:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    high = df["high"] if "high" in df.columns else df["High"]
    low = df["low"] if "low" in df.columns else df["Low"]
    close = df["close"] if "close" in df.columns else df["Close"]

    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement (+DM, -DM)
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    # Wilder smoothing (alpha = 1 / period)
    alpha = 1.0 / float(period)
    smooth_tr = tr.ewm(alpha=alpha, adjust=False).mean()
    smooth_plus = plus_dm_s.ewm(alpha=alpha, adjust=False).mean()
    smooth_minus = minus_dm_s.ewm(alpha=alpha, adjust=False).mean()

    # Directional Indices
    plus_di = 100.0 * (smooth_plus / smooth_tr.replace(0, np.nan)).fillna(0.0)
    minus_di = 100.0 * (smooth_minus / smooth_tr.replace(0, np.nan)).fillna(0.0)

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    dx = dx.fillna(0.0)

    adx_series = dx.ewm(alpha=alpha, adjust=False).mean()

    return plus_di, minus_di, adx_series


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Canonical Single Source of Truth (SSOT) computation for Wilder's ADX(14).
    Uses pure pandas/numpy with exact Wilder alpha = 1 / period smoothing.
    """
    if df is None or len(df) < period:
        return None
    try:
        _, _, adx_series = compute_dmi_series(df, period=period)
        if adx_series.empty or pd.isna(adx_series.iloc[-1]):
            return None
        val = float(adx_series.iloc[-1])
        return round(val, 2) if np.isfinite(val) and val >= 0 else None
    except Exception as exc:
        logger.debug("[analysis.dmi_filter] ADX computation error: %s", exc)
        return None


def evaluate_triple_dmi(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    is_intraday: bool = False,
    period: int = 14,
    threshold: Optional[float] = None,
    pivot_lookback: Optional[int] = None,
) -> DMITripleFilterResult:
    """
    Evaluates the 3-Tier DMI Entry Model for bullish or bearish setups.

    Calibration:
      - Daily / Swing: threshold = 25.0, pivot_lookback = 20 bars.
      - Intraday (1m, 3m, 5m, 15m): threshold = 22.0 or 25.0, pivot_lookback = 12-15 bars.
    """
    timeframe = "INTRADAY" if is_intraday else "DAILY"
    thresh = threshold if threshold is not None else (22.0 if is_intraday else 25.0)
    lookback = pivot_lookback if pivot_lookback is not None else (12 if is_intraday else 20)

    if df is None or len(df) < max(period + 2, 10):
        return DMITripleFilterResult(
            symbol=symbol,
            timeframe=timeframe,
            plus_di=0.0,
            minus_di=0.0,
            adx=0.0,
            threshold=thresh,
            crossover_type="NONE",
            crossover_above_threshold=False,
            plus_di_above_threshold=False,
            minus_di_above_threshold=False,
            prev_minus_di_pivot=0.0,
            prev_plus_di_pivot=0.0,
            breaks_opposite_pivot=False,
            verdict="NEUTRAL",
            confidence_score=0.0,
            summary="Insufficient data for DMI computation.",
        )

    plus_di_s, minus_di_s, adx_s = compute_dmi_series(df, period=period)
    if plus_di_s.empty or len(plus_di_s) < 2:
        return DMITripleFilterResult(
            symbol=symbol,
            timeframe=timeframe,
            plus_di=0.0,
            minus_di=0.0,
            adx=0.0,
            threshold=thresh,
            crossover_type="NONE",
            crossover_above_threshold=False,
            plus_di_above_threshold=False,
            minus_di_above_threshold=False,
            prev_minus_di_pivot=0.0,
            prev_plus_di_pivot=0.0,
            breaks_opposite_pivot=False,
            verdict="NEUTRAL",
            confidence_score=0.0,
            summary="Empty DMI calculation.",
        )

    curr_plus_di = float(plus_di_s.iloc[-1])
    curr_minus_di = float(minus_di_s.iloc[-1])
    curr_adx = float(adx_s.iloc[-1]) if not adx_s.empty else 0.0

    # Trend acceleration: slope of ADX over last 3 bars
    if len(adx_s) >= 4:
        adx_slope_3bar = float(adx_s.iloc[-1] - adx_s.iloc[-4]) / 3.0
    else:
        adx_slope_3bar = 0.0

    # Look back for recent crossovers (last 3-5 bars)
    check_bars = min(5, len(plus_di_s) - 1)
    crossover_type = "NONE"
    crossover_level = 0.0
    crossover_above_threshold = False

    for i in range(1, check_bars + 1):
        p_curr = float(plus_di_s.iloc[-i])
        m_curr = float(minus_di_s.iloc[-i])
        p_prev = float(plus_di_s.iloc[-i - 1])
        m_prev = float(minus_di_s.iloc[-i - 1])

        # Bullish cross: +DI crossed above -DI
        if p_prev <= m_prev and p_curr > m_curr:
            crossover_type = "BULLISH_CROSS"
            crossover_level = p_curr
            crossover_above_threshold = p_curr >= thresh
            break
        # Bearish cross: -DI crossed above +DI
        elif m_prev <= p_prev and m_curr > p_curr:
            crossover_type = "BEARISH_CROSS"
            crossover_level = m_curr
            crossover_above_threshold = m_curr >= thresh
            break

    # If no recent crossover within check_bars, inspect current relative positioning
    is_recent_crossover = crossover_type in ("BULLISH_CROSS", "BEARISH_CROSS")
    if not is_recent_crossover:
        if curr_plus_di > curr_minus_di:
            crossover_type = "BULLISH_ESTABLISHED"
            crossover_above_threshold = curr_plus_di >= thresh
        elif curr_minus_di > curr_plus_di:
            crossover_type = "BEARISH_ESTABLISHED"
            crossover_above_threshold = curr_minus_di >= thresh

    # Filter 2: DI Staying Above Threshold
    plus_di_above = curr_plus_di >= thresh
    minus_di_above = curr_minus_di >= thresh

    # Filter 3: DI Breaks Previous Opposite DI Pivot
    window_start = max(0, len(plus_di_s) - lookback - check_bars)
    window_end = max(1, len(plus_di_s) - 2)

    prior_minus_di_window = minus_di_s.iloc[window_start:window_end]
    prior_plus_di_window = plus_di_s.iloc[window_start:window_end]

    prev_minus_di_pivot = (
        float(prior_minus_di_window.max()) if not prior_minus_di_window.empty else 0.0
    )
    prev_plus_di_pivot = (
        float(prior_plus_di_window.max()) if not prior_plus_di_window.empty else 0.0
    )

    breaks_opposite_pivot = False
    verdict = "NEUTRAL"
    confidence = 50.0
    summary = ""

    # Bullish Evaluation
    if curr_plus_di > curr_minus_di:
        breaks_opposite_pivot = curr_plus_di > prev_minus_di_pivot

        # Triple Bullish Check
        if (
            (crossover_above_threshold or not is_recent_crossover)
            and plus_di_above
            and breaks_opposite_pivot
        ):
            verdict = "TRIPLE_BULLISH_CONFIRMED"
            confidence = min(
                98.0,
                80.0
                + (10.0 if curr_adx >= 20.0 else 5.0)
                + min(8.0, max(0.0, curr_plus_di - thresh) * 0.5),
            )
            summary = (
                f"Triple DMI Bullish Confirmed: +DI ({curr_plus_di:.1f}) >= {thresh}, "
                f"broke prior -DI pivot ({prev_minus_di_pivot:.1f}) with ADX={curr_adx:.1f}"
            )
        elif is_recent_crossover and not crossover_above_threshold:
            verdict = "WEAK_OR_CHOPPY"
            confidence = 30.0
            summary = (
                f"Weak DMI Cross / Chop: +DI crossover ({crossover_level:.1f}) occurred below {thresh} threshold. "
                "Crossovers below threshold lack institutional momentum."
            )
        elif curr_adx >= 20.0:
            verdict = "BULLISH_ESTABLISHED"
            confidence = 70.0
            summary = f"Established Bullish Trend: +DI ({curr_plus_di:.1f}) > -DI ({curr_minus_di:.1f}) with ADX={curr_adx:.1f}"
        else:
            verdict = "WEAK_OR_CHOPPY"
            confidence = 35.0
            summary = f"Weak Trend: ADX ({curr_adx:.1f}) <= 20.0 indicating consolidative chop"

    # Bearish Evaluation
    elif curr_minus_di > curr_plus_di:
        breaks_opposite_pivot = curr_minus_di > prev_plus_di_pivot

        # Triple Bearish Check
        if (
            (crossover_above_threshold or not is_recent_crossover)
            and minus_di_above
            and breaks_opposite_pivot
        ):
            verdict = "TRIPLE_BEARISH_CONFIRMED"
            confidence = min(
                98.0,
                80.0
                + (10.0 if curr_adx >= 20.0 else 5.0)
                + min(8.0, max(0.0, curr_minus_di - thresh) * 0.5),
            )
            summary = (
                f"Triple DMI Bearish Confirmed: -DI ({curr_minus_di:.1f}) >= {thresh}, "
                f"broke prior +DI pivot ({prev_plus_di_pivot:.1f}) with ADX={curr_adx:.1f}"
            )
        elif is_recent_crossover and not crossover_above_threshold:
            verdict = "WEAK_OR_CHOPPY"
            confidence = 30.0
            summary = f"Weak DMI Bearish Cross / Chop: -DI crossover ({crossover_level:.1f}) occurred below {thresh} threshold."
        elif curr_adx >= 20.0:
            verdict = "BEARISH_ESTABLISHED"
            confidence = 70.0
            summary = f"Established Bearish Trend: -DI ({curr_minus_di:.1f}) > +DI ({curr_plus_di:.1f}) with ADX={curr_adx:.1f}"
        else:
            verdict = "WEAK_OR_CHOPPY"
            confidence = 35.0
            summary = f"Weak Trend: ADX ({curr_adx:.1f}) <= 20.0 indicating consolidative chop"

    return DMITripleFilterResult(
        symbol=symbol,
        timeframe=timeframe,
        plus_di=curr_plus_di,
        minus_di=curr_minus_di,
        adx=curr_adx,
        threshold=thresh,
        crossover_type=crossover_type,
        crossover_above_threshold=crossover_above_threshold,
        plus_di_above_threshold=plus_di_above,
        minus_di_above_threshold=minus_di_above,
        prev_minus_di_pivot=prev_minus_di_pivot,
        prev_plus_di_pivot=prev_plus_di_pivot,
        breaks_opposite_pivot=breaks_opposite_pivot,
        verdict=verdict,
        confidence_score=confidence,
        summary=summary,
        adx_slope_3bar=round(adx_slope_3bar, 2),
    )
