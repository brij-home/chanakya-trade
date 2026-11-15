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


# ─────────────────────────────────────────────────────────────
# 3. DALTON AUCTION MARKET OPENING TYPES & VALUE AREA MIGRATION
# ─────────────────────────────────────────────────────────────


def classify_opening_auction_type(
    df_opening: pd.DataFrame,
    pdh: float,
    pdl: float,
    pdc: float,
    vah: float = 0.0,
    val: float = 0.0,
) -> dict[str, Any]:
    """
    Evaluates Dalton's 4 Opening Auction Types from initial 3 to 6 intraday bars (15m–30m):
      1. OPEN_DRIVE: Price opens near/outside prior extremes and drives aggressively with zero overlap.
      2. OPEN_TEST_DRIVE: Price probes a reference level (PDH/PDL/VAH/VAL/PDC), fails to break, and drives away.
      3. OPEN_REJECTION_REVERSE: Price auctions one way, hits strong responsive rejection, and reverses across open.
      4. OPEN_AUCTION_IN_RANGE: Rotational balance around the opening price inside prior range.
    """
    if df_opening is None or len(df_opening) < 3:
        return {
            "opening_type": "OPEN_AUCTION_IN_RANGE",
            "conviction": "LOW",
            "direction": "NEUTRAL",
            "rationale": "Insufficient opening bars to classify auction type.",
        }

    cols = {c.lower(): c for c in df_opening.columns}
    o_s = df_opening[cols["open"]].astype(float)
    h_s = df_opening[cols["high"]].astype(float)
    l_s = df_opening[cols["low"]].astype(float)
    c_s = df_opening[cols["close"]].astype(float)

    open_price = float(o_s.iloc[0])
    session_high = float(h_s.max())
    session_low = float(l_s.min())
    curr_close = float(c_s.iloc[-1])

    first_bar_high = float(h_s.iloc[0])
    first_bar_low = float(l_s.iloc[0])
    first_bar_range = max(first_bar_high - first_bar_low, 0.001)

    # 1. Check for OPEN_DRIVE:
    # Pristine opening extreme: opening wick <= 10% of first bar range, and
    # aggressive unidirectional trend with no overlap back into the open.
    bullish_drive = (
        (open_price - first_bar_low) <= 0.10 * first_bar_range
        and l_s.min() >= first_bar_low - (0.05 * first_bar_range)
        and curr_close > first_bar_high + (0.5 * first_bar_range)
        and (c_s.diff().iloc[1:] >= -0.05 * first_bar_range).mean() >= 0.70
    )
    bearish_drive = (
        (first_bar_high - open_price) <= 0.10 * first_bar_range
        and h_s.max() <= first_bar_high + (0.05 * first_bar_range)
        and curr_close < first_bar_low - (0.5 * first_bar_range)
        and (c_s.diff().iloc[1:] <= 0.05 * first_bar_range).mean() >= 0.70
    )

    if bullish_drive or bearish_drive:
        return {
            "opening_type": "OPEN_DRIVE",
            "conviction": "HIGH",
            "direction": "BULLISH" if bullish_drive else "BEARISH",
            "rationale": (
                f"Aggressive Open-Drive detected. Price opened at ₹{open_price:,.2f} and expanded with zero overlap. "
                "Initiative buyers/sellers in full control — favor pullback/retest entries."
            ),
        }

    # 2. Check for OPEN_TEST_DRIVE:
    # Tested a key reference level in first 2 bars, rejected, then drove decisively
    tested_level = None
    test_rejection = False
    ref_levels = [("PDH", pdh), ("PDL", pdl), ("PDC", pdc)]
    if vah > 0:
        ref_levels.append(("VAH", vah))
    if val > 0:
        ref_levels.append(("VAL", val))

    for name, lvl in ref_levels:
        if lvl <= 0:
            continue
        # Probed near level within 0.10% (strict auction touch)
        probed_high = any(abs(h - lvl) / lvl <= 0.0010 for h in h_s.iloc[:2]) and lvl >= open_price
        probed_low = any(abs(l - lvl) / lvl <= 0.0010 for l in l_s.iloc[:2]) and lvl <= open_price

        if probed_high and curr_close < open_price - (0.35 * first_bar_range):
            tested_level = name
            test_rejection = True
            drive_dir = "BEARISH"
            break
        elif probed_low and curr_close > open_price + (0.35 * first_bar_range):
            tested_level = name
            test_rejection = True
            drive_dir = "BULLISH"
            break

    if test_rejection and tested_level:
        return {
            "opening_type": "OPEN_TEST_DRIVE",
            "conviction": "HIGH",
            "direction": drive_dir,
            "rationale": (
                f"Open-Test-Drive: Tested {tested_level} (₹{lvl:,.2f}), found strong opposing responsive rejection, "
                f"and drove {drive_dir.lower()} past open ₹{open_price:,.2f}."
            ),
        }

    # Check for OPEN_REJECTION_REVERSE:
    # First rallied one way by >= 0.25%, then rejected and sliced through open to new extreme
    initial_rally_pct = (session_high - open_price) / open_price * 100.0
    initial_drop_pct = (open_price - session_low) / open_price * 100.0

    if initial_rally_pct >= 0.25 and curr_close < open_price - (0.15 * first_bar_range):
        return {
            "opening_type": "OPEN_REJECTION_REVERSE",
            "conviction": "MEDIUM",
            "direction": "BEARISH",
            "rationale": (
                f"Open-Rejection-Reverse: Early probe above open to ₹{session_high:,.2f} rejected. "
                f"Price sliced back through open ₹{open_price:,.2f} showing responsive sellers."
            ),
        }
    elif initial_drop_pct >= 0.25 and curr_close > open_price + (0.15 * first_bar_range):
        return {
            "opening_type": "OPEN_REJECTION_REVERSE",
            "conviction": "MEDIUM",
            "direction": "BULLISH",
            "rationale": (
                f"Open-Rejection-Reverse: Early probe below open to ₹{session_low:,.2f} rejected. "
                f"Price sliced back through open ₹{open_price:,.2f} showing responsive buyers."
            ),
        }

    return {
        "opening_type": "OPEN_AUCTION_IN_RANGE",
        "conviction": "LOW",
        "direction": "NEUTRAL",
        "rationale": f"Price rotating quietly around open ₹{open_price:,.2f} within prior balance. Rotational day expected.",
    }


def evaluate_value_area_relationship(
    today_vah: float,
    today_val: float,
    prior_vah: float,
    prior_val: float,
) -> str:
    """
    Classifies Dalton's 6 Value Area 2-Day Relationships:
      - HIGHER_VALUE: Today's VAL > Prior VAH (Bullish Acceptance)
      - OVERLAPPING_HIGHER: Today's VAH > Prior VAH and Today's VAL >= Prior VAL (Bullish Continuation)
      - INSIDE_VALUE: Today's VAH <= Prior VAH and Today's VAL >= Prior VAL (Balance / Compression)
      - OUTSIDE_VALUE: Today's VAH > Prior VAH and Today's VAL < Prior VAL (Expansion / Volatility)
      - OVERLAPPING_LOWER: Today's VAH <= Prior VAH and Today's VAL < Prior VAL (Bearish Continuation)
      - LOWER_VALUE: Today's VAH < Prior VAL (Bearish Acceptance)
    """
    if prior_vah <= 0 or prior_val <= 0 or today_vah <= 0 or today_val <= 0:
        return "INSIDE_VALUE"

    if today_val > prior_vah:
        return "HIGHER_VALUE"
    elif today_vah < prior_val:
        return "LOWER_VALUE"
    elif today_vah > prior_vah and today_val < prior_val:
        return "OUTSIDE_VALUE"
    elif today_vah <= prior_vah and today_val >= prior_val:
        return "INSIDE_VALUE"
    elif today_vah >= prior_vah and today_val >= prior_val:
        return "OVERLAPPING_HIGHER"
    elif today_vah <= prior_vah and today_val <= prior_val:
        return "OVERLAPPING_LOWER"
    return "INSIDE_VALUE"


def evaluate_dalton_80_percent_rule(
    df_intraday: pd.DataFrame,
    prior_vah: float,
    prior_val: float,
    prior_poc: float = 0.0,
) -> Optional[dict[str, Any]]:
    """
    Evaluates Dalton's 80% Rule from Market Profile theory:
    If market opens outside the prior day's Value Area, then re-enters and prints
    >= 2 consecutive bars inside the Value Area (acceptance), there is an 80%
    probability that the auction will travel to the opposite extreme of the Value Area.

    Returns actionable trade setup dictionary or None if condition not met.
    """
    if df_intraday is None or len(df_intraday) < 4:
        return None
    if prior_vah <= 0 or prior_val <= 0 or prior_vah <= prior_val:
        return None

    cols = {c.lower(): c for c in df_intraday.columns}
    o_s = df_intraday[cols["open"]].astype(float)
    c_s = df_intraday[cols["close"]].astype(float)

    open_price = float(o_s.iloc[0])
    va_width = prior_vah - prior_val

    # Case 1: Opened Above Prior VAH and accepted downwards into VA
    if open_price > prior_vah:
        # Check if last 2 consecutive bars closed inside Value Area
        inside_mask = (c_s <= prior_vah) & (c_s >= prior_val)
        if inside_mask.iloc[-2:].all():
            curr_ltp = float(c_s.iloc[-1])
            sl = round(prior_vah + (0.25 * va_width), 2)
            risk = max(sl - curr_ltp, 0.005 * curr_ltp)
            t1 = round(prior_poc if prior_poc > prior_val else (prior_vah + prior_val) / 2.0, 2)
            t2 = round(prior_val, 2)
            rr = round(abs(curr_ltp - t2) / max(0.01, risk), 1)

            return {
                "rule": "DALTON_80_PERCENT_RULE",
                "direction": "BEARISH",
                "setup_type": "VALUE_AREA_ROTATION_DOWN",
                "probability": 0.80,
                "entry_level": round(curr_ltp, 2),
                "invalidation_sl": sl,
                "target_1": t1,
                "target_2": t2,
                "target_opposite_va": t2,
                "risk_reward": f"1:{rr}",
                "rationale": (
                    f"Market opened above Prior VAH (₹{prior_vah:,.2f}) at ₹{open_price:,.2f}, "
                    f"then accepted inside with 2 consecutive closes. Dalton's 80% Rule favors "
                    f"mean-reversion across Value Area to Prior VAL (₹{prior_val:,.2f})."
                ),
            }

    # Case 2: Opened Below Prior VAL and accepted upwards into VA
    elif open_price < prior_val:
        inside_mask = (c_s <= prior_vah) & (c_s >= prior_val)
        if inside_mask.iloc[-2:].all():
            curr_ltp = float(c_s.iloc[-1])
            sl = round(prior_val - (0.25 * va_width), 2)
            risk = max(curr_ltp - sl, 0.005 * curr_ltp)
            t1 = round(prior_poc if prior_poc < prior_vah else (prior_vah + prior_val) / 2.0, 2)
            t2 = round(prior_vah, 2)
            rr = round(abs(t2 - curr_ltp) / max(0.01, risk), 1)

            return {
                "rule": "DALTON_80_PERCENT_RULE",
                "direction": "BULLISH",
                "setup_type": "VALUE_AREA_ROTATION_UP",
                "probability": 0.80,
                "entry_level": round(curr_ltp, 2),
                "invalidation_sl": sl,
                "target_1": t1,
                "target_2": t2,
                "target_opposite_va": t2,
                "risk_reward": f"1:{rr}",
                "rationale": (
                    f"Market opened below Prior VAL (₹{prior_val:,.2f}) at ₹{open_price:,.2f}, "
                    f"then accepted inside with 2 consecutive closes. Dalton's 80% Rule favors "
                    f"mean-reversion across Value Area to Prior VAH (₹{prior_vah:,.2f})."
                ),
            }

    return None
