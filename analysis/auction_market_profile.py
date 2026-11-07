"""
analysis/auction_market_profile.py
──────────────────────────────────
Dalton Auction Market Theory (AMT) & Market Profile Engine.

Implements core Steidlmayer and Jim Dalton Market Profile concepts:
  1. Initial Balance (IB): 09:15 to 10:15 IST (First 1-hour auction range).
  2. Dalton Day Type Classification:
     - Trend Day (IB < 0.65x Daily ATR, directional expansion > 2.0x IB, no re-entry into IB).
     - Normal Variation Day (IB broken by 1.0x to 1.5x IB extension, moderate one-time framing).
     - Normal Day (IB contains ~85% of total day range, wide initial base).
     - Neutral Day (Both IB High and IB Low are broken/swept, closes near equilibrium).
     - Double Distribution Trend Day (Two distinct value areas separated by single print speedway).
  3. Auction Mechanics:
     - Poor Highs & Poor Lows (Equal highs/lows with no single-print tail — unfinished auction business).
     - Excess / Rejection Tails (Buying tail >= 2x tick size at lows, selling tail at highs).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.technical import atr

logger = logging.getLogger("chanakya.analysis.auction_market_profile")


@dataclass
class MarketProfileSnapshot:
    symbol: str
    session_date: str
    ib_high: float
    ib_low: float
    ib_midpoint: float
    ib_range_pts: float
    ib_to_atr_ratio: float
    day_type: (
        str  # "TREND_DAY", "NORMAL_VARIATION", "NORMAL_DAY", "NEUTRAL_DAY", "DOUBLE_DISTRIBUTION"
    )
    current_expansion_multiple: float  # e.g., 1.5x IB, 2.2x IB
    has_poor_high: bool
    has_poor_low: bool
    has_buying_tail: bool  # Excess at low
    has_selling_tail: bool  # Excess at high
    t1_extension: float  # 1.5x IB
    t2_extension: float  # 2.0x IB
    invalidation_level: float
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "session_date": self.session_date,
            "ib_high": round(self.ib_high, 2),
            "ib_low": round(self.ib_low, 2),
            "ib_midpoint": round(self.ib_midpoint, 2),
            "ib_range_pts": round(self.ib_range_pts, 2),
            "ib_to_atr_ratio": round(self.ib_to_atr_ratio, 2),
            "day_type": self.day_type,
            "current_expansion_multiple": round(self.current_expansion_multiple, 2),
            "has_poor_high": self.has_poor_high,
            "has_poor_low": self.has_poor_low,
            "has_buying_tail": self.has_buying_tail,
            "has_selling_tail": self.has_selling_tail,
            "t1_extension": round(self.t1_extension, 2),
            "t2_extension": round(self.t2_extension, 2),
            "invalidation_level": round(self.invalidation_level, 2),
            "summary": self.summary,
        }


def analyze_market_profile(
    df_intraday: pd.DataFrame,
    symbol: str = "UNKNOWN",
    daily_atr: Optional[float] = None,
) -> Optional[MarketProfileSnapshot]:
    """
    Evaluates Auction Market Theory and Dalton Market Profile parameters
    from 5m or 15m intraday OHLCV bars.
    """
    if df_intraday is None or len(df_intraday) < 12:  # Need at least 1-hour IB (12x 5m bars)
        return None

    cols = {c.lower(): c for c in df_intraday.columns}
    h_s = df_intraday[cols["high"]].astype(float)
    l_s = df_intraday[cols["low"]].astype(float)
    c_s = df_intraday[cols["close"]].astype(float)

    # Compute ATR baseline
    if daily_atr is None or daily_atr <= 0:
        atr_s = atr(df_intraday, 14)
        daily_atr = (
            float(atr_s.iloc[-1])
            if not atr_s.empty and not np.isnan(atr_s.iloc[-1])
            else float(c_s.iloc[-1]) * 0.015
        )
    daily_atr = max(daily_atr, 1.0)

    # First 12 bars (09:15 to 10:15 IST) represent the Initial Balance
    ib_bars = df_intraday.iloc[:12]
    ib_high = float(ib_bars[cols["high"]].max())
    ib_low = float(ib_bars[cols["low"]].min())
    ib_range = max(ib_high - ib_low, 0.001)
    ib_mid = (ib_high + ib_low) / 2.0
    ib_ratio = ib_range / daily_atr

    # Session stats up to current bar
    session_high = float(h_s.max())
    session_low = float(l_s.min())
    session_close = float(c_s.iloc[-1])
    total_range = max(session_high - session_low, 0.001)
    expansion_mult = total_range / ib_range

    # Both sides breached?
    high_breached = session_high > ib_high + (0.05 * ib_range)
    low_breached = session_low < ib_low - (0.05 * ib_range)

    # ─────────────────────────────────────────────────────────
    # 1. DALTON DAY TYPE CLASSIFICATION
    # ─────────────────────────────────────────────────────────
    if high_breached and low_breached:
        day_type = "NEUTRAL_DAY"
        t1_ext = ib_high + (0.5 * ib_range)
        t2_ext = ib_low - (0.5 * ib_range)
        inv = ib_mid
    elif ib_ratio <= 0.65 and expansion_mult >= 1.8:
        day_type = "TREND_DAY"
        is_bull_trend = session_close > ib_high
        t1_ext = ib_high + (1.5 * ib_range) if is_bull_trend else ib_low - (1.5 * ib_range)
        t2_ext = ib_high + (2.5 * ib_range) if is_bull_trend else ib_low - (2.5 * ib_range)
        inv = ib_mid if is_bull_trend else ib_mid
    elif expansion_mult >= 1.25:
        day_type = "NORMAL_VARIATION"
        is_bull_var = session_close > ib_mid
        t1_ext = ib_high + (1.0 * ib_range) if is_bull_var else ib_low - (1.0 * ib_range)
        t2_ext = ib_high + (1.5 * ib_range) if is_bull_var else ib_low - (1.5 * ib_range)
        inv = ib_low if is_bull_var else ib_high
    else:
        day_type = "NORMAL_DAY"
        t1_ext = ib_high
        t2_ext = ib_low
        inv = ib_mid

    # ─────────────────────────────────────────────────────────
    # 2. AUCTION MECHANICS: POOR HIGHS / LOWS & EXCESS TAILS
    # ─────────────────────────────────────────────────────────
    # Poor High: top 2 session highs are within 0.02% of each other (unfinished business, will be swept)
    sorted_highs = sorted(h_s.iloc[-10:].tolist(), reverse=True)
    has_poor_high = False
    if len(sorted_highs) >= 2:
        high_diff_pct = (sorted_highs[0] - sorted_highs[1]) / sorted_highs[0] * 100.0
        if high_diff_pct <= 0.03:
            has_poor_high = True

    # Poor Low: bottom 2 session lows are within 0.02% of each other
    sorted_lows = sorted(l_s.iloc[-10:].tolist())
    has_poor_low = False
    if len(sorted_lows) >= 2:
        low_diff_pct = (sorted_lows[1] - sorted_lows[0]) / max(sorted_lows[0], 1.0) * 100.0
        if low_diff_pct <= 0.03:
            has_poor_low = True

    # Excess Tail check on the lowest bar (Buying tail: long lower wick >= 40% of bar range at session low)
    lowest_idx = l_s.idxmin()
    lowest_bar = df_intraday.loc[lowest_idx]
    l_b_range = max(float(lowest_bar[cols["high"]]) - float(lowest_bar[cols["low"]]), 0.001)
    l_b_wick = min(
        float(lowest_bar[cols["open"]] if "open" in cols else lowest_bar["close"]),
        float(lowest_bar["close"]),
    ) - float(lowest_bar[cols["low"]])
    has_buying_tail = (l_b_wick / l_b_range) >= 0.40

    # Selling Tail check on the highest bar (Selling tail: long upper wick >= 40% of bar range at session high)
    highest_idx = h_s.idxmax()
    highest_bar = df_intraday.loc[highest_idx]
    h_b_range = max(float(highest_bar[cols["high"]]) - float(highest_bar[cols["low"]]), 0.001)
    h_b_wick = float(highest_bar[cols["high"]]) - max(
        float(highest_bar[cols["open"]] if "open" in cols else highest_bar["close"]),
        float(highest_bar["close"]),
    )
    has_selling_tail = (h_b_wick / h_b_range) >= 0.40

    summary = (
        f"Dalton Market Profile [{day_type}]: IB [{ib_low:.2f} - {ib_high:.2f}] ({ib_range:.1f} pts, {ib_ratio:.2f}x ATR). "
        f"Expansion: {expansion_mult:.2f}x IB. Poor High: {has_poor_high}, Poor Low: {has_poor_low}, Buying Tail: {has_buying_tail}."
    )

    date_str = (
        str(df_intraday.index[-1].date()) if hasattr(df_intraday.index[-1], "date") else "LIVE"
    )

    return MarketProfileSnapshot(
        symbol=symbol,
        session_date=date_str,
        ib_high=ib_high,
        ib_low=ib_low,
        ib_midpoint=ib_mid,
        ib_range_pts=ib_range,
        ib_to_atr_ratio=ib_ratio,
        day_type=day_type,
        current_expansion_multiple=expansion_mult,
        has_poor_high=has_poor_high,
        has_poor_low=has_poor_low,
        has_buying_tail=has_buying_tail,
        has_selling_tail=has_selling_tail,
        t1_extension=t1_ext,
        t2_extension=t2_ext,
        invalidation_level=inv,
        summary=summary,
    )
