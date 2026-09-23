"""
analysis/market_structure.py
────────────────────────────
Institutional Market Structure, Smart Money Concepts (SMC) & Price Action Engine.

Computes:
  1. Fractal Swing Highs & Swing Lows (Multi-bar pivot detection)
  2. Structural Regime: BULLISH (HH + HL), BEARISH (LH + LL), RANGING
  3. Structural Transitions:
     - MSS / CHoCH (Change of Character): Early trend reversal (Bottom/Top Fishing)
     - BOS (Break of Structure): Trend continuation breakouts
  4. Institutional Footprints:
     - Order Blocks (OB): Bullish Demand OB & Bearish Supply OB (with mitigation status)
     - Fair Value Gaps (FVG): 3-bar price imbalances with fill ratios
     - Liquidity Sweeps: False breakouts / stop hunts that reclaim the range
  5. Setup Pattern Classifier:
     - BREAKOUT_EXPANSION, PULLBACK_DEMAND_RETEST, BOTTOM_FISHING_SPRING,
       TOP_FISHING_UTAD, VCP_CONTRACTION

Accepts OHLCV DataFrame or fetches live/cached history via market.history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import math
import numpy as np
import pandas as pd


# ── Data Models ───────────────────────────────────────────────


@dataclass
class SwingPoint:
    index: int
    date: str
    price: float
    type: str  # "HIGH" | "LOW"
    classification: str = ""  # "HH" | "LH" | "HL" | "LL"


@dataclass
class OrderBlock:
    type: str  # "DEMAND" | "SUPPLY"
    top: float
    bottom: float
    midpoint: float
    formed_date: str
    mitigated: bool = False
    volume_ratio: float = 1.0
    confluence_count: int = 1  # Number of aggregated overlapping blocks
    ote_price: float = 0.0  # 50% Mean Threshold (MT) / Optimal Trade Entry sweet spot
    is_unmitigated: bool = True
    has_fvg_confluence: bool = False
    quality_tier: str = "TIER_1_PRIME"  # "TIER_1_PRIME" | "TIER_2_VALID" | "TIER_3_WEAK"


@dataclass
class FairValueGap:
    type: str  # "BULLISH" | "BEARISH"
    top: float
    bottom: float
    size: float
    formed_date: str
    filled: bool = False


@dataclass
class LiquiditySweep:
    type: (
        str  # "BULLISH_SWEEP" (Spring/Stop-hunt below low) | "BEARISH_SWEEP" (Upthrust above high)
    )
    swept_level: float
    reclaim_price: float
    date: str
    description: str


@dataclass
class MarketStructureReport:
    symbol: str
    ltp: float
    regime: str  # "BULLISH" | "BEARISH" | "RANGING"
    structure_score: int  # -100 (Extremely Bearish) to +100 (Extremely Bullish)
    setup_type: str  # "BREAKOUT_EXPANSION" | "PULLBACK_RETEST" | "BOTTOM_FISHING_SPRING" | "TOP_FISHING_UTAD" | "VCP_CONTRACTION" | "CONSOLIDATION"
    setup_confidence: int  # 0 - 100

    # Swings
    recent_swings: list[SwingPoint] = field(default_factory=list)
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None

    # SMC Elements
    active_demand_zones: list[OrderBlock] = field(default_factory=list)
    active_supply_zones: list[OrderBlock] = field(default_factory=list)
    fair_value_gaps: list[FairValueGap] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)

    # Signals & Key Levels
    choch_detected: bool = False
    choch_type: Optional[str] = None  # "BULLISH_CHOCH" | "BEARISH_CHOCH"
    bos_detected: bool = False
    bos_type: Optional[str] = None  # "BULLISH_BOS" | "BEARISH_BOS"

    nearest_support: float = 0.0
    nearest_resistance: float = 0.0
    invalidation_level: float = 0.0  # Stop-loss reference level
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward_ratio: float = 0.0

    # SMC 2.0 Dealing Range & Inducement Metrics
    dealing_range_equilibrium: float = 0.0
    discount_zone_low: float = 0.0
    discount_zone_high: float = 0.0
    in_discount_zone: bool = False
    inducement_level: Optional[float] = None
    inducement_swept: bool = False

    # Price Action Confirmation & Trap Filters
    confirmation_candle: Optional[str] = None  # e.g. "Hammer", "Bullish Engulfing", None
    confirmation_confirmed: bool = False  # True = a valid rejection candle is present
    divergence_type: Optional[str] = (
        None  # "BULLISH_REGULAR" | "BEARISH_REGULAR" | "BULLISH_HIDDEN" | "BEARISH_HIDDEN"
    )
    divergence_bias: Optional[str] = None  # "BULLISH" | "BEARISH"

    summary: str = ""
    actionable_trade_idea: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Candlestick Confirmation & Divergence Detectors ─────────


def detect_confirmation_candle(
    df: pd.DataFrame,
    direction: str = "BULLISH",
) -> dict[str, Any]:
    """
    Detects a confirming rejection candle on the last 1–3 bars.

    Bullish patterns: Hammer, Bullish Engulfing, Bullish Pin Bar, Morning Star.
    Bearish patterns: Shooting Star, Bearish Engulfing, Bearish Pin Bar, Evening Star.

    Returns dict with:
        confirmed (bool)   — True if a valid pattern found
        pattern   (str)    — pattern name or "NONE"
        strength  (int)    — 0-100 confidence in pattern quality
    """
    result: dict[str, Any] = {"confirmed": False, "pattern": "NONE", "strength": 0}
    if df is None or len(df) < 2:
        return result

    try:
        # Use last 3 bars for multi-bar patterns
        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3] if len(df) >= 3 else prev

        c_o = float(last.get("open", last["close"]))
        c_c = float(last["close"])
        c_h = float(last.get("high", c_c))
        c_l = float(last.get("low", c_c))
        b_range = max(c_h - c_l, 0.0001)
        body = abs(c_c - c_o)
        upper_wick = c_h - max(c_o, c_c)
        lower_wick = min(c_o, c_c) - c_l

        p_o = float(prev.get("open", prev["close"]))
        p_c = float(prev["close"])
        p_h = float(prev.get("high", p_c))
        p_l = float(prev.get("low", p_c))

        if direction == "BULLISH":
            # 1. Hammer: lower wick >= 2x body, small upper wick, close > open preferred
            if lower_wick >= 2.0 * max(body, 0.0001) and upper_wick <= 0.3 * b_range:
                strength = min(95, 65 + int((lower_wick / b_range) * 40))
                result = {"confirmed": True, "pattern": "Hammer", "strength": strength}

            # 2. Bullish Engulfing: current bull bar fully engulfs prior bear bar
            elif c_c > c_o and p_c < p_o and c_c >= p_o and c_o <= p_c:
                strength = min(95, 70 + int((body / max(p_h - p_l, 0.0001)) * 25))
                result = {"confirmed": True, "pattern": "Bullish Engulfing", "strength": strength}

            # 3. Bullish Pin Bar: long lower wick (≥55% of range), tiny body at top
            elif lower_wick >= 0.55 * b_range and body <= 0.25 * b_range:
                result = {"confirmed": True, "pattern": "Bullish Pin Bar", "strength": 80}

            # 4. Morning Star (3-bar): big bear → small doji/inside → big bull
            elif len(df) >= 3:
                p2_o = float(prev2.get("open", prev2["close"]))
                p2_c = float(prev2["close"])
                p2_range = max(abs(p2_o - p2_c), 0.0001)
                p_body = abs(p_o - p_c)
                if (
                    p2_c < p2_o
                    and p_body <= 0.35 * p2_range
                    and c_c > c_o
                    and body >= 0.5 * p2_range
                ):
                    result = {"confirmed": True, "pattern": "Morning Star", "strength": 88}

        else:  # BEARISH
            # 1. Shooting Star: upper wick >= 2x body, small lower wick
            if upper_wick >= 2.0 * max(body, 0.0001) and lower_wick <= 0.3 * b_range:
                strength = min(95, 65 + int((upper_wick / b_range) * 40))
                result = {"confirmed": True, "pattern": "Shooting Star", "strength": strength}

            # 2. Bearish Engulfing: current bear bar fully engulfs prior bull bar
            elif c_c < c_o and p_c > p_o and c_c <= p_o and c_o >= p_c:
                strength = min(95, 70 + int((body / max(p_h - p_l, 0.0001)) * 25))
                result = {"confirmed": True, "pattern": "Bearish Engulfing", "strength": strength}

            # 3. Bearish Pin Bar: long upper wick (≥55% of range), tiny body at bottom
            elif upper_wick >= 0.55 * b_range and body <= 0.25 * b_range:
                result = {"confirmed": True, "pattern": "Bearish Pin Bar", "strength": 80}

            # 4. Evening Star (3-bar): big bull → small doji → big bear
            elif len(df) >= 3:
                p2_o = float(prev2.get("open", prev2["close"]))
                p2_c = float(prev2["close"])
                p2_range = max(abs(p2_o - p2_c), 0.0001)
                p_body = abs(p_o - p_c)
                if (
                    p2_c > p2_o
                    and p_body <= 0.35 * p2_range
                    and c_c < c_o
                    and body >= 0.5 * p2_range
                ):
                    result = {"confirmed": True, "pattern": "Evening Star", "strength": 88}

    except Exception:
        pass

    return result


def detect_divergence(
    df: pd.DataFrame,
    rsi_period: int = 14,
    lookback: int = 20,
) -> dict[str, Any]:
    """
    Detects RSI divergence on the last `lookback` bars.

    Regular Bullish:  Price makes lower low, RSI makes higher low  → reversal up
    Regular Bearish:  Price makes higher high, RSI makes lower high → reversal down
    Hidden Bullish:   Price makes higher low, RSI makes lower low   → trend continuation up
    Hidden Bearish:   Price makes lower high, RSI makes higher high → trend continuation down

    Returns dict with:
        type  (str)  — "BULLISH_REGULAR" | "BEARISH_REGULAR" | "BULLISH_HIDDEN" | "BEARISH_HIDDEN" | "NONE"
        bias  (str)  — "BULLISH" | "BEARISH" | "NONE"
    """
    result: dict[str, Any] = {"type": "NONE", "bias": "NONE"}
    if df is None or len(df) < max(rsi_period + 5, lookback + 2):
        return result

    try:
        closes = df["close"].astype(float)
        highs = df["high"].astype(float) if "high" in df.columns else closes
        lows = df["low"].astype(float) if "low" in df.columns else closes

        # RSI(14)
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
        rsi = 100 - (100 / (1 + avg_gain / avg_loss.replace(0, float("nan"))))

        # Use last `lookback` bars for pivot comparison
        window = min(lookback, len(df))
        price_lows = lows.iloc[-window:]
        price_highs = highs.iloc[-window:]
        rsi_win = rsi.iloc[-window:]

        # Split into first half vs second half for simple pivot comparison
        mid = window // 2
        if mid < 3:
            return result

        price_low1 = float(price_lows.iloc[:mid].min())
        price_low2 = float(price_lows.iloc[mid:].min())
        price_high1 = float(price_highs.iloc[:mid].max())
        price_high2 = float(price_highs.iloc[mid:].max())

        rsi_low1 = float(rsi_win.iloc[:mid].min())
        rsi_low2 = float(rsi_win.iloc[mid:].min())
        rsi_high1 = float(rsi_win.iloc[:mid].max())
        rsi_high2 = float(rsi_win.iloc[mid:].max())

        # Tolerance: 0.3% for price, 2 pts for RSI
        def price_lower(a: float, b: float) -> bool:
            return b < a * 0.997

        def price_higher(a: float, b: float) -> bool:
            return b > a * 1.003

        def rsi_higher(a: float, b: float) -> bool:
            return b > a + 2.0

        def rsi_lower(a: float, b: float) -> bool:
            return b < a - 2.0

        # Regular Bullish: price LL, RSI HL
        if price_lower(price_low1, price_low2) and rsi_higher(rsi_low1, rsi_low2):
            return {"type": "BULLISH_REGULAR", "bias": "BULLISH"}

        # Regular Bearish: price HH, RSI LH
        if price_higher(price_high1, price_high2) and rsi_lower(rsi_high1, rsi_high2):
            return {"type": "BEARISH_REGULAR", "bias": "BEARISH"}

        # Hidden Bullish: price HL, RSI LL (trend continuation up)
        if price_higher(price_low1, price_low2) and rsi_lower(rsi_low1, rsi_low2):
            return {"type": "BULLISH_HIDDEN", "bias": "BULLISH"}

        # Hidden Bearish: price LH, RSI HH (trend continuation down)
        if price_lower(price_high1, price_high2) and rsi_higher(rsi_high1, rsi_high2):
            return {"type": "BEARISH_HIDDEN", "bias": "BEARISH"}

    except Exception:
        pass

    return result


# ── Core SMC Algorithms ───────────────────────────────────────


def find_swing_points(df: pd.DataFrame, window: int = 3) -> list[SwingPoint]:
    """
    Identifies fractal Swing Highs and Lows across an OHLCV DataFrame.
    window: Number of bars on either side that must be lower (for highs) or higher (for lows).
    """
    if df is None or len(df) < (window * 2 + 1):
        return []

    highs = df["high"].values
    lows = df["low"].values
    dates = df["date"].astype(str).values if "date" in df.columns else [str(i) for i in df.index]

    swings: list[SwingPoint] = []
    n = len(df)

    for i in range(window, n - window):
        # Swing High
        is_high = True
        for w in range(1, window + 1):
            if highs[i] <= highs[i - w] or highs[i] <= highs[i + w]:
                is_high = False
                break
        if is_high:
            swings.append(
                SwingPoint(index=i, date=str(dates[i]), price=float(highs[i]), type="HIGH")
            )

        # Swing Low
        is_low = True
        for w in range(1, window + 1):
            if lows[i] >= lows[i - w] or lows[i] >= lows[i + w]:
                is_low = False
                break
        if is_low:
            swings.append(SwingPoint(index=i, date=str(dates[i]), price=float(lows[i]), type="LOW"))

    # Sort chronologically by bar index
    swings.sort(key=lambda s: s.index)

    # Classify HH, LH, HL, LL
    last_high: Optional[float] = None
    last_low: Optional[float] = None

    for s in swings:
        if s.type == "HIGH":
            if last_high is None:
                s.classification = "HIGH"
            elif s.price > last_high:
                s.classification = "HH"
            else:
                s.classification = "LH"
            last_high = s.price
        elif s.type == "LOW":
            if last_low is None:
                s.classification = "LOW"
            elif s.price > last_low:
                s.classification = "HL"
            else:
                s.classification = "LL"
            last_low = s.price

    return swings


def detect_order_blocks(
    df: pd.DataFrame, swings: list[SwingPoint]
) -> tuple[list[OrderBlock], list[OrderBlock]]:
    """
    Identifies unmitigated Bullish Demand and Bearish Supply Order Blocks.
    Demand OB: The last down-close candle before a high-momentum upward displacement move that broke structure.
    Supply OB: The last up-close candle before an aggressive downward displacement move.
    """
    if df is None or len(df) < 5:
        return [], []

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    vols = df["volume"].values if "volume" in df.columns else np.ones(len(df))
    avg_vol = np.mean(vols[-20:]) if len(vols) >= 20 else np.mean(vols)
    dates = df["date"].astype(str).values if "date" in df.columns else [str(i) for i in df.index]

    demand_obs: list[OrderBlock] = []
    supply_obs: list[OrderBlock] = []

    # Detect displacement (momentum candle size > 1.3x average bar body)
    bodies = np.abs(closes - opens)
    avg_body = np.mean(bodies[-20:]) if len(bodies) >= 20 else np.mean(bodies)

    n = len(df)
    for i in range(2, n - 2):
        # Bullish Displacement: Next 1-2 bars move up aggressively with large body
        up_displacement = (closes[i + 1] > highs[i]) and (bodies[i + 1] > avg_body * 1.3)
        if up_displacement and closes[i] <= opens[i]:  # Last down candle
            ob_top = float(highs[i])
            ob_bottom = float(lows[i])
            ob_mid = (ob_top + ob_bottom) / 2.0

            # Check if broken later (close below bottom invalidates demand OB)
            mitigated = False
            for j in range(i + 2, n):
                if closes[j] < ob_bottom:
                    mitigated = True
                    break

            demand_obs.append(
                OrderBlock(
                    type="DEMAND",
                    top=ob_top,
                    bottom=ob_bottom,
                    midpoint=ob_mid,
                    formed_date=str(dates[i]),
                    mitigated=mitigated,
                    volume_ratio=float(vols[i] / avg_vol) if avg_vol > 0 else 1.0,
                )
            )

        # Bearish Displacement: Next 1-2 bars move down aggressively
        down_displacement = (closes[i + 1] < lows[i]) and (bodies[i + 1] > avg_body * 1.3)
        if down_displacement and closes[i] >= opens[i]:  # Last up candle
            ob_top = float(highs[i])
            ob_bottom = float(lows[i])
            ob_mid = (ob_top + ob_bottom) / 2.0

            # Check if broken later (close above top invalidates supply OB)
            mitigated = False
            for j in range(i + 2, n):
                if closes[j] > ob_top:
                    mitigated = True
                    break

            supply_obs.append(
                OrderBlock(
                    type="SUPPLY",
                    top=ob_top,
                    bottom=ob_bottom,
                    midpoint=ob_mid,
                    formed_date=str(dates[i]),
                    mitigated=mitigated,
                    volume_ratio=float(vols[i] / avg_vol) if avg_vol > 0 else 1.0,
                    confluence_count=1,
                    ote_price=round(ob_mid, 2),
                )
            )

    # Aggregate nearby and overlapping order blocks into unified confluence zones
    agg_demand = aggregate_overlapping_order_blocks(demand_obs)
    agg_supply = aggregate_overlapping_order_blocks(supply_obs)

    # Filter for strong, data-backed unmitigated blocks only (volume >= 1.1x or confluence >= 2x)
    # and retain the top 2 nearest institutional zones to prevent chart clutter
    valid_demand = [
        d
        for d in agg_demand
        if not d.mitigated
        and (
            d.volume_ratio >= 1.1
            or d.confluence_count >= 2
            or (d.top - d.bottom) / (d.bottom or 1) >= 0.003
        )
    ]
    # Sort demand: nearest below current price first, keep top 2
    valid_demand.sort(key=lambda x: x.top, reverse=True)
    top_demand = sorted(valid_demand[:2], key=lambda x: x.bottom)

    valid_supply = [
        s
        for s in agg_supply
        if not s.mitigated
        and (
            s.volume_ratio >= 1.1
            or s.confluence_count >= 2
            or (s.top - s.bottom) / (s.bottom or 1) >= 0.003
        )
    ]
    # Sort supply: nearest above current price first, keep top 2
    valid_supply.sort(key=lambda x: x.bottom)
    top_supply = valid_supply[:2]

    return top_demand, top_supply


def aggregate_overlapping_order_blocks(
    obs: list[OrderBlock], proximity_pct: float = 0.01
) -> list[OrderBlock]:
    """
    Combines nearby and overlapping unmitigated Order Blocks into unified institutional
    Confluence Zones (Clusters).

    Why:
    Multiple adjacent fractals or candles often produce separate overlapping blocks.
    Aggregating them creates a high-conviction decision zone with a 50% Mean Threshold
    (OTE sweet spot) for highest R:R entries and clean chart readability.
    """
    if not obs:
        return []

    # Sort from low to high for demand, high to low for supply
    sorted_obs = sorted(obs, key=lambda x: x.bottom)
    merged: list[OrderBlock] = []

    for ob in sorted_obs:
        if ob.mitigated:
            continue

        if not merged:
            merged_ob = OrderBlock(
                type=ob.type,
                top=ob.top,
                bottom=ob.bottom,
                midpoint=(ob.top + ob.bottom) / 2.0,
                formed_date=ob.formed_date,
                mitigated=False,
                volume_ratio=ob.volume_ratio,
                confluence_count=1,
                ote_price=round((ob.top + ob.bottom) / 2.0, 2),
            )
            merged.append(merged_ob)
            continue

        prev = merged[-1]

        # Check overlap or tight proximity (within proximity_pct)
        overlap = not (ob.bottom > prev.top and (ob.bottom - prev.top) / prev.top > proximity_pct)

        if overlap:
            # Merge into higher-conviction unified zone
            new_top = max(prev.top, ob.top)
            new_bottom = min(prev.bottom, ob.bottom)
            new_mid = (new_top + new_bottom) / 2.0
            new_vol = max(prev.volume_ratio, ob.volume_ratio)
            new_confluence = prev.confluence_count + 1

            merged[-1] = OrderBlock(
                type=prev.type,
                top=new_top,
                bottom=new_bottom,
                midpoint=new_mid,
                formed_date=prev.formed_date,
                mitigated=False,
                volume_ratio=round(new_vol, 2),
                confluence_count=new_confluence,
                ote_price=round(new_mid, 2),
            )
        else:
            merged.append(
                OrderBlock(
                    type=ob.type,
                    top=ob.top,
                    bottom=ob.bottom,
                    midpoint=(ob.top + ob.bottom) / 2.0,
                    formed_date=ob.formed_date,
                    mitigated=False,
                    volume_ratio=ob.volume_ratio,
                    confluence_count=1,
                    ote_price=round((ob.top + ob.bottom) / 2.0, 2),
                )
            )

    return merged


def detect_fair_value_gaps(df: pd.DataFrame) -> list[FairValueGap]:
    """
    Identifies 3-bar Fair Value Gaps (FVG) / Liquidity Imbalances.
    Bullish FVG: Bar 1 High < Bar 3 Low (Gap in between).
    Bearish FVG: Bar 1 Low > Bar 3 High.
    """
    if df is None or len(df) < 3:
        return []

    highs = df["high"].values
    lows = df["low"].values
    dates = df["date"].astype(str).values if "date" in df.columns else [str(i) for i in df.index]
    fvgs: list[FairValueGap] = []
    n = len(df)

    for i in range(len(df) - 2):
        # Bullish FVG
        if highs[i] < lows[i + 2]:
            gap_bottom = float(highs[i])
            gap_top = float(lows[i + 2])
            gap_size = gap_top - gap_bottom

            # Check if filled by subsequent candles
            filled = any(lows[j] <= gap_bottom for j in range(i + 3, n))

            fvgs.append(
                FairValueGap(
                    type="BULLISH",
                    top=gap_top,
                    bottom=gap_bottom,
                    size=gap_size,
                    formed_date=str(dates[i + 1]),
                    filled=filled,
                )
            )

        # Bearish FVG
        elif lows[i] > highs[i + 2]:
            gap_top = float(lows[i])
            gap_bottom = float(highs[i + 2])
            gap_size = gap_top - gap_bottom

            filled = any(highs[j] >= gap_top for j in range(i + 3, n))

            fvgs.append(
                FairValueGap(
                    type="BEARISH",
                    top=gap_top,
                    bottom=gap_bottom,
                    size=gap_size,
                    formed_date=str(dates[i + 1]),
                    filled=filled,
                )
            )

    return fvgs


def detect_liquidity_sweeps(df: pd.DataFrame, swings: list[SwingPoint]) -> list[LiquiditySweep]:
    """
    Identifies Liquidity Sweeps (Stop Hunts / Wyckoff Springs / UTADs).
    Price temporarily trades below a key swing low or above a swing high,
    triggering retail stop orders, but immediately reclaims the level and closes back inside.
    """
    if df is None or len(df) < 5 or not swings:
        return []

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dates = df["date"].astype(str).values if "date" in df.columns else [str(i) for i in df.index]
    sweeps: list[LiquiditySweep] = []

    # Check the last 15 bars against confirmed older swing points
    recent_window = min(15, len(df))
    start_idx = len(df) - recent_window

    for i in range(start_idx, len(df)):
        c_low = lows[i]
        c_high = highs[i]
        c_close = closes[i]

        # Check Bullish Sweep (Spring): dipped below an older swing low, closed back above it
        for s in swings:
            if s.type == "LOW" and s.index < i - 3:
                if c_low < s.price and c_close > s.price:
                    sweeps.append(
                        LiquiditySweep(
                            type="BULLISH_SWEEP",
                            swept_level=float(s.price),
                            reclaim_price=float(c_close),
                            date=str(dates[i]),
                            description=f"Liquidity Sweep / Spring below ₹{s.price:.2f} swing low; closed strong at ₹{c_close:.2f}.",
                        )
                    )

            # Check Bearish Sweep (Upthrust): poked above an older swing high, closed back below it
            elif s.type == "HIGH" and s.index < i - 3:
                if c_high > s.price and c_close < s.price:
                    sweeps.append(
                        LiquiditySweep(
                            type="BEARISH_SWEEP",
                            swept_level=float(s.price),
                            reclaim_price=float(c_close),
                            date=str(dates[i]),
                            description=f"Liquidity Sweep / Upthrust above ₹{s.price:.2f} swing high; rejected down to ₹{c_close:.2f}.",
                        )
                    )

    return sweeps


# ── Full Market Structure Analyzer ────────────────────────────


def analyze_market_structure(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
    timeframe: str = "day",
) -> MarketStructureReport:
    """
    Comprehensive Market Structure & Smart Money Concepts (SMC) analyzer.
    Accepts an explicit DataFrame or fetches live OHLCV data.
    """
    if df is None or len(df) == 0:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(symbol, exchange=exchange, interval=timeframe, days=250)
        except Exception:
            df = None

    if df is not None and not df.empty:
        df = df.dropna(subset=["close"]).copy()

    if df is None or len(df) < 10:
        # Fallback safe report
        return MarketStructureReport(
            symbol=symbol,
            ltp=0.0,
            regime="RANGING",
            structure_score=0,
            setup_type="CONSOLIDATION",
            setup_confidence=40,
            summary="Insufficient historical price bars to compute institutional market structure.",
            actionable_trade_idea="Wait for sufficient data before taking structural entries.",
        )

    ltp_raw = float(df["close"].iloc[-1])
    if math.isnan(ltp_raw) or ltp_raw <= 0:
        try:
            from market.quotes import get_ltp

            live_p = get_ltp(f"{exchange}:{symbol}")
            ltp = float(live_p) if (live_p and not math.isnan(live_p) and live_p > 0) else None
        except Exception:
            ltp = None
    else:
        ltp = ltp_raw

    if not ltp or ltp <= 0:
        return MarketStructureReport(
            symbol=symbol,
            ltp=0.0,
            regime="UNAVAILABLE",
            structure_score=0,
            summary=f"LTP unavailable for {symbol} to compute market structure.",
            actionable_trade_idea="Awaiting market feed data.",
        )

    # 1. Swings (adaptive window based on sample length)
    swing_win = 2 if len(df) <= 60 else 3
    swings = find_swing_points(df, window=swing_win)
    recent_swings = swings[-8:] if swings else []

    high_swings = [s for s in swings if s.type == "HIGH"]
    low_swings = [s for s in swings if s.type == "LOW"]

    last_swing_high = high_swings[-1].price if high_swings else float(df["high"].max())
    last_swing_low = low_swings[-1].price if low_swings else float(df["low"].min())

    # 2. SMC Elements
    demand_obs, supply_obs = detect_order_blocks(df, swings)
    fvgs = [f for f in detect_fair_value_gaps(df) if not f.filled][-4:]

    # Enrich Order Blocks with FVG confluence and unmitigated status
    for ob in demand_obs:
        ob.is_unmitigated = not ob.mitigated
        # Check if any bullish FVG sits directly above or inside this demand block
        ob.has_fvg_confluence = any(
            f.type == "BULLISH" and abs(f.bottom - ob.top) <= (ob.top * 0.008) for f in fvgs
        )
        ob.quality_tier = (
            "TIER_1_PRIME"
            if (ob.is_unmitigated and ob.has_fvg_confluence)
            else ("TIER_2_VALID" if ob.is_unmitigated else "TIER_3_WEAK")
        )

    for ob in supply_obs:
        ob.is_unmitigated = not ob.mitigated
        ob.has_fvg_confluence = any(
            f.type == "BEARISH" and abs(f.top - ob.bottom) <= (ob.bottom * 0.008) for f in fvgs
        )
        ob.quality_tier = (
            "TIER_1_PRIME"
            if (ob.is_unmitigated and ob.has_fvg_confluence)
            else ("TIER_2_VALID" if ob.is_unmitigated else "TIER_3_WEAK")
        )

    active_demand = [ob for ob in demand_obs if ob.is_unmitigated][-3:]
    active_supply = [ob for ob in supply_obs if ob.is_unmitigated][-3:]
    sweeps = detect_liquidity_sweeps(df, swings)[-3:]

    # 3. Structural Regime Classification
    hh_count = sum(1 for s in recent_swings if s.classification == "HH")
    hl_count = sum(1 for s in recent_swings if s.classification == "HL")
    lh_count = sum(1 for s in recent_swings if s.classification == "LH")
    ll_count = sum(1 for s in recent_swings if s.classification == "LL")

    # Fast trend slope check
    closes = df["close"].values
    short_denom = closes[-min(10, len(closes))]
    if short_denom and not math.isnan(short_denom) and short_denom > 0:
        short_slope = (closes[-1] - short_denom) / short_denom
        if math.isnan(short_slope) or not math.isfinite(short_slope):
            short_slope = 0.0
    else:
        short_slope = 0.0

    structure_score = 0
    regime = "RANGING"
    slope_int = (
        int(short_slope * 200)
        if (not math.isnan(short_slope) and math.isfinite(short_slope))
        else 0
    )

    if (hh_count + hl_count) >= (lh_count + ll_count) + 2 or (
        short_slope > 0.05 and ltp > last_swing_high * 0.98
    ):
        regime = "BULLISH"
        structure_score = min(90, 40 + (hh_count + hl_count) * 12 + slope_int)
    elif (lh_count + ll_count) >= (hh_count + hl_count) + 2 or (
        short_slope < -0.05 and ltp < last_swing_low * 1.02
    ):
        regime = "BEARISH"
        structure_score = max(-90, -40 - (lh_count + ll_count) * 12 + slope_int)
    else:
        regime = "RANGING"
        structure_score = int((hh_count + hl_count - lh_count - ll_count) * 10)

    # 4. CHoCH & BOS Detection
    choch_detected = False
    choch_type = None
    bos_detected = False
    bos_type = None

    # CHoCH Bullish: Downtrend prior / LHs present, now price broke above the last swing high
    if (
        (lh_count >= 1 or regime == "BEARISH" or short_slope < 0)
        and high_swings
        and ltp > high_swings[-1].price
    ):
        choch_detected = True
        choch_type = "BULLISH_CHOCH"
        structure_score = max(35, structure_score + 35)

    # CHoCH Bearish: Uptrend prior / HLs present, now price broke below the last swing low
    elif (
        (hl_count >= 1 or regime == "BULLISH" or short_slope > 0)
        and low_swings
        and ltp < low_swings[-1].price
    ):
        choch_detected = True
        choch_type = "BEARISH_CHOCH"
        structure_score = min(-35, structure_score - 35)

    # BOS Bullish: Break of most recent confirmed High in existing uptrend
    elif regime == "BULLISH" and high_swings and ltp >= high_swings[-1].price:
        bos_detected = True
        bos_type = "BULLISH_BOS"
        structure_score += 15

    # BOS Bearish: Break of most recent confirmed Low in existing downtrend
    elif regime == "BEARISH" and low_swings and ltp <= low_swings[-1].price:
        bos_detected = True
        bos_type = "BEARISH_BOS"
        structure_score -= 15

    structure_score = max(-100, min(100, structure_score))

    # 5. Setup Type Classification
    setup_type = "CONSOLIDATION"
    setup_confidence = 50

    has_bull_sweep = any(s.type == "BULLISH_SWEEP" for s in sweeps)
    has_bear_sweep = any(s.type == "BEARISH_SWEEP" for s in sweeps)

    if has_bull_sweep and (choch_detected or structure_score > 0):
        setup_type = "BOTTOM_FISHING_SPRING"
        setup_confidence = 85
    elif has_bear_sweep and (choch_type == "BEARISH_CHOCH" or structure_score < -20):
        setup_type = "TOP_FISHING_UTAD"
        setup_confidence = 82
    elif bos_type == "BULLISH_BOS" or (regime == "BULLISH" and ltp >= last_swing_high * 0.99):
        setup_type = "BREAKOUT_EXPANSION"
        setup_confidence = 80
    elif (
        regime == "BULLISH"
        and active_demand
        and any(ob.bottom <= ltp <= ob.top * 1.02 for ob in active_demand)
    ):
        setup_type = "PULLBACK_RETEST"
        setup_confidence = 78
    elif bos_type == "BEARISH_BOS" or (regime == "BEARISH" and ltp <= last_swing_low * 1.01):
        setup_type = "BREAKDOWN_EXPANSION"
        setup_confidence = 78

    # 6. Key Levels, Invalidations & Payoff Targets
    supports = [ob.top for ob in active_demand if ob.top < ltp] + [
        s.price for s in low_swings if s.price < ltp
    ]
    nearest_support = max(supports) if supports else last_swing_low

    resistances = [ob.bottom for ob in active_supply if ob.bottom > ltp] + [
        s.price for s in high_swings if s.price > ltp
    ]
    nearest_resistance = min(resistances) if resistances else last_swing_high

    if nearest_resistance <= ltp:
        nearest_resistance = ltp * 1.06
    if nearest_support >= ltp:
        nearest_support = ltp * 0.94

    if structure_score >= 0:
        invalidation = nearest_support * 0.99
        risk = (
            max(0.01, ltp - invalidation)
            if not math.isnan(ltp)
            else max(0.01, invalidation * 0.015)
        )
        target_1 = ltp + (risk * 2.0)
        target_2 = ltp + (risk * 3.5)
        rr = round((target_1 - ltp) / risk, 2) if risk > 0 else 2.0
    else:
        invalidation = nearest_resistance * 1.01
        risk = (
            max(0.01, invalidation - ltp)
            if not math.isnan(ltp)
            else max(0.01, invalidation * 0.015)
        )
        target_1 = ltp - (risk * 2.0)
        target_2 = ltp - (risk * 3.5)
        rr = round((ltp - target_1) / risk, 2) if risk > 0 else 2.0

    # 7. Summary Synthesis
    summary_parts = [f"Structure is {regime} (Score: {structure_score:+d}/100)."]
    if choch_detected:
        summary_parts.append(f"⚠️ {choch_type} triggered — structural trend shift in progress.")
    elif bos_detected:
        summary_parts.append(f"🚀 {bos_type} active — momentum continuation confirmed.")
    if has_bull_sweep:
        summary_parts.append("🎯 Bullish Liquidity Sweep (Spring) detected below support.")
    if active_demand:
        summary_parts.append(
            f"🛡️ Key Demand Order Block at ₹{active_demand[-1].bottom:.1f}–₹{active_demand[-1].top:.1f}."
        )

    summary = " ".join(summary_parts)

    if structure_score > 20:
        action = f"Plan Long entry near ₹{ltp:.2f} (or on retest of ₹{nearest_support:.2f}). Invalidation Stop below ₹{invalidation:.2f}. Targets: ₹{target_1:.2f} (2R) and ₹{target_2:.2f} (3.5R)."
    elif structure_score < -20:
        action = f"Avoid fresh longs. For short/hedging: Enter near ₹{ltp:.2f}. Invalidation Stop above ₹{invalidation:.2f}. Targets: ₹{target_1:.2f} and ₹{target_2:.2f}."
    else:
        action = f"Consolidating inside range ₹{nearest_support:.2f} – ₹{nearest_resistance:.2f}. Await clear BOS or Liquidity Sweep before entering."

    # SMC 2.0 Dealing Range Equilibrium and Inducement
    range_high = max(last_swing_high, ltp)
    range_low = min(last_swing_low, ltp)
    dealing_range = max(1.0, range_high - range_low)
    equilibrium = round(range_low + dealing_range * 0.5, 2)
    discount_high = round(range_high - dealing_range * 0.50, 2)
    discount_low = round(range_high - dealing_range * 0.786, 2)
    in_discount = ltp <= equilibrium

    inducement_lvl = low_swings[-1].price if len(low_swings) >= 2 else None
    inducement_swept = any(
        sw.type == "BULLISH_SWEEP"
        and inducement_lvl
        and abs(sw.swept_level - inducement_lvl) <= (dealing_range * 0.03)
        for sw in sweeps
    )

    return MarketStructureReport(
        symbol=symbol,
        ltp=round(ltp, 2),
        regime=regime,
        structure_score=structure_score,
        setup_type=setup_type,
        setup_confidence=setup_confidence,
        recent_swings=recent_swings,
        last_swing_high=round(last_swing_high, 2),
        last_swing_low=round(last_swing_low, 2),
        active_demand_zones=active_demand,
        active_supply_zones=active_supply,
        fair_value_gaps=fvgs,
        liquidity_sweeps=sweeps,
        choch_detected=choch_detected,
        choch_type=choch_type,
        bos_detected=bos_detected,
        bos_type=bos_type,
        nearest_support=round(nearest_support, 2),
        nearest_resistance=round(nearest_resistance, 2),
        invalidation_level=round(invalidation, 2),
        target_1=round(target_1, 2),
        target_2=round(target_2, 2),
        risk_reward_ratio=rr,
        dealing_range_equilibrium=equilibrium,
        discount_zone_low=discount_low,
        discount_zone_high=discount_high,
        in_discount_zone=in_discount,
        inducement_level=round(inducement_lvl, 2) if inducement_lvl else None,
        inducement_swept=inducement_swept,
        summary=summary,
        actionable_trade_idea=action,
        # Price Action Confirmation (candle rejection at key level)
        **_build_confirmation_fields(df, structure_score),
        # RSI Divergence (trap filter)
        **_build_divergence_fields(df, structure_score),
    )


def _build_confirmation_fields(df: pd.DataFrame, structure_score: int) -> dict[str, Any]:
    """Helper: compute confirmation candle fields for MarketStructureReport."""
    try:
        direction = "BULLISH" if structure_score >= 0 else "BEARISH"
        conf = detect_confirmation_candle(df, direction=direction)
        return {
            "confirmation_candle": conf["pattern"] if conf["confirmed"] else None,
            "confirmation_confirmed": conf["confirmed"],
        }
    except Exception:
        return {"confirmation_candle": None, "confirmation_confirmed": False}


def _build_divergence_fields(df: pd.DataFrame, structure_score: int) -> dict[str, Any]:
    """Helper: compute RSI divergence fields for MarketStructureReport."""
    try:
        div = detect_divergence(df)
        return {
            "divergence_type": div["type"] if div["type"] != "NONE" else None,
            "divergence_bias": div["bias"] if div["bias"] != "NONE" else None,
        }
    except Exception:
        return {"divergence_type": None, "divergence_bias": None}


# ── Multi-Timeframe (MTF) Alignment Matrix ────────────────────


def check_mtf_structural_alignment(
    symbol: str,
    exchange: str = "MCX",
    ltp: float = 0.0,
    direction: str = "BULLISH",
    df_5m: Optional[pd.DataFrame] = None,
    df_1h: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """
    3-Tier MTF Alignment Matrix: 5m → 15m → 1H cascade.

    Returns alignment_count (0–3): how many timeframes agree with `direction`.
    Callers should require alignment_count >= 2 for high-conviction trades.
    """
    df_hourly = df_1h
    if df_hourly is None or df_hourly.empty:
        if df_5m is not None and len(df_5m) >= 24:
            try:
                # Resample 5m to 1h
                resampled = (
                    df_5m.resample("1h")
                    .agg(
                        {
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                        }
                    )
                    .dropna()
                )
                if len(resampled) >= 5:
                    df_hourly = resampled
            except Exception:
                df_hourly = None

    if df_hourly is None or df_hourly.empty:
        try:
            from market.history import get_ohlcv

            df_hourly = get_ohlcv(symbol, exchange=exchange, interval="1h", days=10)
        except Exception:
            df_hourly = None

    if df_hourly is None or len(df_hourly) < 5:
        return {
            "is_aligned": True,
            "htf_trend": "NEUTRAL",
            "wall_collision": False,
            "nearest_wall": 0.0,
            "distance_pct": 99.0,
            "reason": "Insufficient 1H data; defaulting to neutral",
        }

    closes = df_hourly["close"] if "close" in df_hourly.columns else df_hourly["Close"]
    highs = df_hourly["high"] if "high" in df_hourly.columns else df_hourly["High"]
    lows = df_hourly["low"] if "low" in df_hourly.columns else df_hourly["Low"]

    # 2. 1-Hour Trend Bias via EMAs (EMA 20 & EMA 50)
    ema20 = float(closes.ewm(span=min(20, len(closes)), adjust=False).mean().iloc[-1])
    ema50 = float(closes.ewm(span=min(50, len(closes)), adjust=False).mean().iloc[-1])
    cur_p = ltp if ltp > 0 else float(closes.iloc[-1])

    is_htf_bull = cur_p >= ema20 and ema20 >= ema50 * 0.998
    is_htf_bear = cur_p <= ema20 and ema20 <= ema50 * 1.002
    htf_trend = "BULLISH" if is_htf_bull else ("BEARISH" if is_htf_bear else "NEUTRAL")

    is_aligned = (direction == "BULLISH" and htf_trend != "BEARISH") or (
        direction == "BEARISH" and htf_trend != "BULLISH"
    )

    # 3. Detect 1-Hour Resistance / Support Walls (Swing Highs / Lows in last 48 bars)
    recent_lookback = min(48, len(df_hourly))
    recent_highs = highs.iloc[-recent_lookback:]
    recent_lows = lows.iloc[-recent_lookback:]

    wall_collision = False
    nearest_wall = 0.0
    dist_pct = 99.0

    if direction == "BULLISH":
        upper_walls = [float(h) for h in recent_highs if float(h) > cur_p]
        if upper_walls:
            nearest_wall = min(upper_walls)
            dist_pct = round(((nearest_wall - cur_p) / cur_p) * 100, 2)
            if dist_pct <= 0.35:
                wall_collision = True
    else:
        lower_walls = [float(l) for l in recent_lows if float(l) < cur_p]
        if lower_walls:
            nearest_wall = max(lower_walls)
            dist_pct = round(((cur_p - nearest_wall) / cur_p) * 100, 2)
            if dist_pct <= 0.35:
                wall_collision = True

    # ── Tier 2: 15-minute alignment (resample 5m → 15m) ────────
    alignment_count = 1 if is_aligned else 0  # 1H is tier 3
    tf_15m_trend = "NEUTRAL"
    tf_5m_trend = "NEUTRAL"

    if df_5m is not None and len(df_5m) >= 15:
        try:
            # 15-min: resample from 5m
            df_15m: Optional[pd.DataFrame] = None
            try:
                if hasattr(df_5m.index, "freq") or isinstance(df_5m.index, pd.DatetimeIndex):
                    df_15m = (
                        df_5m.resample("15min")
                        .agg(
                            {
                                "open": "first",
                                "high": "max",
                                "low": "min",
                                "close": "last",
                                "volume": "sum",
                            }
                        )
                        .dropna()
                    )
            except Exception:
                df_15m = None

            if df_15m is not None and len(df_15m) >= 5:
                c15 = df_15m["close"] if "close" in df_15m.columns else df_15m["Close"]
                ema9_15 = float(c15.ewm(span=min(9, len(c15)), adjust=False).mean().iloc[-1])
                ema21_15 = float(c15.ewm(span=min(21, len(c15)), adjust=False).mean().iloc[-1])
                ltp_15 = float(c15.iloc[-1])
                if ltp_15 >= ema9_15 and ema9_15 >= ema21_15 * 0.998:
                    tf_15m_trend = "BULLISH"
                elif ltp_15 <= ema9_15 and ema9_15 <= ema21_15 * 1.002:
                    tf_15m_trend = "BEARISH"

                if (direction == "BULLISH" and tf_15m_trend == "BULLISH") or (
                    direction == "BEARISH" and tf_15m_trend == "BEARISH"
                ):
                    alignment_count += 1

            # ── Tier 1: 5-minute CHoCH / momentum check ─────────
            c5 = df_5m["close"] if "close" in df_5m.columns else df_5m["Close"]
            h5 = df_5m["high"] if "high" in df_5m.columns else df_5m["High"]
            l5 = df_5m["low"] if "low" in df_5m.columns else df_5m["Low"]

            # Simple 5m CHoCH: compare last 5 bars to prior 5 bars
            if len(c5) >= 10:
                recent5 = c5.iloc[-5:]
                prior5 = c5.iloc[-10:-5]
                recent_high = float(h5.iloc[-5:].max())
                recent_low = float(l5.iloc[-5:].min())
                prior_high = float(h5.iloc[-10:-5].max())
                prior_low = float(l5.iloc[-10:-5].min())

                # 5m Bullish: recent low > prior low AND recent close > prior close avg
                if recent_low > prior_low * 1.001 and float(recent5.mean()) > float(prior5.mean()):
                    tf_5m_trend = "BULLISH"
                # 5m Bearish: recent high < prior high AND recent close < prior close avg
                elif recent_high < prior_high * 0.999 and float(recent5.mean()) < float(
                    prior5.mean()
                ):
                    tf_5m_trend = "BEARISH"

                if (direction == "BULLISH" and tf_5m_trend == "BULLISH") or (
                    direction == "BEARISH" and tf_5m_trend == "BEARISH"
                ):
                    alignment_count += 1

        except Exception:
            pass

    # Composite alignment: require >= 2/3 timeframes aligned for strong conviction
    is_aligned_composite = alignment_count >= 2 or (
        is_aligned and not wall_collision  # 1H aligned + no wall = acceptable
    )

    return {
        "is_aligned": is_aligned_composite,
        "is_htf_aligned": is_aligned,
        "htf_trend": htf_trend,
        "tf_15m_trend": tf_15m_trend,
        "tf_5m_trend": tf_5m_trend,
        "alignment_count": alignment_count,  # 0–3
        "wall_collision": wall_collision,
        "nearest_wall": nearest_wall,
        "distance_pct": dist_pct,
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
    }
