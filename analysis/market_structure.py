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
from datetime import datetime
from typing import Any, Optional

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
    type: str  # "BULLISH_SWEEP" (Spring/Stop-hunt below low) | "BEARISH_SWEEP" (Upthrust above high)
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
    
    summary: str = ""
    actionable_trade_idea: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
            swings.append(SwingPoint(index=i, date=str(dates[i]), price=float(highs[i]), type="HIGH"))

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


def detect_order_blocks(df: pd.DataFrame, swings: list[SwingPoint]) -> tuple[list[OrderBlock], list[OrderBlock]]:
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
            
            # Check if mitigated later
            mitigated = False
            for j in range(i + 2, n):
                if lows[j] <= ob_top:
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

            mitigated = False
            for j in range(i + 2, n):
                if highs[j] >= ob_bottom:
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
                )
            )

    return demand_obs, supply_obs


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

    ltp = float(df["close"].iloc[-1])

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
    active_demand = [ob for ob in demand_obs if not ob.mitigated][-3:]
    active_supply = [ob for ob in supply_obs if not ob.mitigated][-3:]
    fvgs = [f for f in detect_fair_value_gaps(df) if not f.filled][-4:]
    sweeps = detect_liquidity_sweeps(df, swings)[-3:]

    # 3. Structural Regime Classification
    hh_count = sum(1 for s in recent_swings if s.classification == "HH")
    hl_count = sum(1 for s in recent_swings if s.classification == "HL")
    lh_count = sum(1 for s in recent_swings if s.classification == "LH")
    ll_count = sum(1 for s in recent_swings if s.classification == "LL")

    # Fast trend slope check
    closes = df["close"].values
    short_slope = (closes[-1] - closes[-min(10, len(closes))]) / closes[-min(10, len(closes))]

    structure_score = 0
    regime = "RANGING"

    if (hh_count + hl_count) >= (lh_count + ll_count) + 2 or (short_slope > 0.05 and ltp > last_swing_high * 0.98):
        regime = "BULLISH"
        structure_score = min(90, 40 + (hh_count + hl_count) * 12 + int(short_slope * 200))
    elif (lh_count + ll_count) >= (hh_count + hl_count) + 2 or (short_slope < -0.05 and ltp < last_swing_low * 1.02):
        regime = "BEARISH"
        structure_score = max(-90, -40 - (lh_count + ll_count) * 12 + int(short_slope * 200))
    else:
        regime = "RANGING"
        structure_score = int((hh_count + hl_count - lh_count - ll_count) * 10)

    # 4. CHoCH & BOS Detection
    choch_detected = False
    choch_type = None
    bos_detected = False
    bos_type = None

    # CHoCH Bullish: Downtrend prior / LHs present, now price broke above the last swing high
    if (lh_count >= 1 or regime == "BEARISH" or short_slope < 0) and high_swings and ltp > high_swings[-1].price:
        choch_detected = True
        choch_type = "BULLISH_CHOCH"
        structure_score = max(35, structure_score + 35)

    # CHoCH Bearish: Uptrend prior / HLs present, now price broke below the last swing low
    elif (hl_count >= 1 or regime == "BULLISH" or short_slope > 0) and low_swings and ltp < low_swings[-1].price:
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
    elif regime == "BULLISH" and active_demand and any(ob.bottom <= ltp <= ob.top * 1.02 for ob in active_demand):
        setup_type = "PULLBACK_RETEST"
        setup_confidence = 78
    elif bos_type == "BEARISH_BOS" or (regime == "BEARISH" and ltp <= last_swing_low * 1.01):
        setup_type = "BREAKDOWN_EXPANSION"
        setup_confidence = 78

    # 6. Key Levels, Invalidations & Payoff Targets
    supports = [ob.top for ob in active_demand if ob.top < ltp] + [s.price for s in low_swings if s.price < ltp]
    nearest_support = max(supports) if supports else last_swing_low

    resistances = [ob.bottom for ob in active_supply if ob.bottom > ltp] + [s.price for s in high_swings if s.price > ltp]
    nearest_resistance = min(resistances) if resistances else last_swing_high

    if nearest_resistance <= ltp:
        nearest_resistance = ltp * 1.06
    if nearest_support >= ltp:
        nearest_support = ltp * 0.94

    if structure_score >= 0:
        invalidation = nearest_support * 0.99
        risk = max(0.01, ltp - invalidation)
        target_1 = ltp + (risk * 2.0)
        target_2 = ltp + (risk * 3.5)
        rr = round((target_1 - ltp) / risk, 2)
    else:
        invalidation = nearest_resistance * 1.01
        risk = max(0.01, invalidation - ltp)
        target_1 = ltp - (risk * 2.0)
        target_2 = ltp - (risk * 3.5)
        rr = round((ltp - target_1) / risk, 2)

    # 7. Summary Synthesis
    summary_parts = [f"Structure is {regime} (Score: {structure_score:+d}/100)."]
    if choch_detected:
        summary_parts.append(f"⚠️ {choch_type} triggered — structural trend shift in progress.")
    elif bos_detected:
        summary_parts.append(f"🚀 {bos_type} active — momentum continuation confirmed.")
    if has_bull_sweep:
        summary_parts.append("🎯 Bullish Liquidity Sweep (Spring) detected below support.")
    if active_demand:
        summary_parts.append(f"🛡️ Key Demand Order Block at ₹{active_demand[-1].bottom:.1f}–₹{active_demand[-1].top:.1f}.")

    summary = " ".join(summary_parts)

    if structure_score > 20:
        action = f"Plan Long entry near ₹{ltp:.2f} (or on retest of ₹{nearest_support:.2f}). Invalidation Stop below ₹{invalidation:.2f}. Targets: ₹{target_1:.2f} (2R) and ₹{target_2:.2f} (3.5R)."
    elif structure_score < -20:
        action = f"Avoid fresh longs. For short/hedging: Enter near ₹{ltp:.2f}. Invalidation Stop above ₹{invalidation:.2f}. Targets: ₹{target_1:.2f} and ₹{target_2:.2f}."
    else:
        action = f"Consolidating inside range ₹{nearest_support:.2f} – ₹{nearest_resistance:.2f}. Await clear BOS or Liquidity Sweep before entering."

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
        summary=summary,
        actionable_trade_idea=action,
    )
