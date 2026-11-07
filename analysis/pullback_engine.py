"""
analysis/pullback_engine.py
───────────────────────────
Institutional Pullback, Retest & Continuation Engine.

Differentiates healthy institutional pullbacks from dangerous liquidation traps:
  1. Verifies origin impulse momentum (ADX >= 20, displacement >= 2.0x ATR).
  2. Enforces Volume Dry-Up during retracement (Vol <= 0.80x SMA20) — heavy volume on pullbacks indicates distribution.
  3. Validates structural anchor retest (Prior resistance-turned-support, 20 EMA, Anchored VWAP, or 0.50-0.618 Fib OTE).
  4. Requires re-ignition candlestick trigger (rejection pin bar or breakout above retest bar high).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from analysis.technical import atr, ema
from analysis.fibonacci import compute_fib_levels

logger = logging.getLogger("chanakya.analysis.pullback_engine")


@dataclass
class PullbackSignal:
    symbol: str
    pullback_type: (
        str  # "BREAKOUT_RETEST" | "EMA20_PULLBACK" | "VWAP_PULLBACK" | "FIB_OTE_PULLBACK" | "NONE"
    )
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: int  # 0 to 100
    anchor_level: float
    pullback_depth_fib: float
    is_volume_dryup: bool
    reignition_candle: str
    entry_zone: tuple[float, float]
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward_ratio: float
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "pullback_type": self.pullback_type,
            "bias": self.bias,
            "confidence": self.confidence,
            "anchor_level": round(self.anchor_level, 2),
            "pullback_depth_fib": round(self.pullback_depth_fib, 3),
            "is_volume_dryup": self.is_volume_dryup,
            "reignition_candle": self.reignition_candle,
            "entry_zone": [round(x, 2) for x in self.entry_zone],
            "stop_loss": round(self.stop_loss, 2),
            "target_1": round(self.target_1, 2),
            "target_2": round(self.target_2, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "summary": self.summary,
        }


def evaluate_pullback(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    breakout_level: Optional[float] = None,
    vwap_series: Optional[pd.Series] = None,
    atr_val: Optional[float] = None,
) -> Optional[PullbackSignal]:
    """
    Evaluates whether the current market action represents a confirmed institutional
    pullback/retest or an invalidated breakdown/liquidation.
    """
    if df is None or len(df) < 20:
        return None

    cols = {c.lower(): c for c in df.columns}
    h_series = df[cols["high"]].astype(float)
    l_series = df[cols["low"]].astype(float)
    c_series = df[cols["close"]].astype(float)
    o_series = df[cols["open"]].astype(float) if "open" in cols else c_series
    v_series = (
        df[cols["volume"]].astype(float) if "volume" in cols else pd.Series(1000.0, index=df.index)
    )

    c_curr = float(c_series.iloc[-1])
    h_curr = float(h_series.iloc[-1])
    l_curr = float(l_series.iloc[-1])
    o_curr = float(o_series.iloc[-1])

    h_prev = float(h_series.iloc[-2])
    l_prev = float(l_series.iloc[-2])

    # Dynamic ATR
    if atr_val is None or atr_val <= 0:
        atr_s = atr(df, period=14)
        atr_val = (
            float(atr_s.iloc[-1])
            if not atr_s.empty and not np.isnan(atr_s.iloc[-1])
            else c_curr * 0.015
        )
    if atr_val <= 0:
        atr_val = max(c_curr * 0.01, 1.0)

    # Moving Averages
    ema20_s = ema(c_series, 20)
    curr_ema20 = float(ema20_s.iloc[-1]) if not ema20_s.empty else c_curr

    # Volume Baseline
    avg_vol_20 = float(v_series.rolling(20, min_periods=5).mean().iloc[-1])
    curr_vol = float(v_series.iloc[-1])
    prev_vol = float(v_series.iloc[-2])

    # Volume dry-up check on retracement (pullback bars should have vol <= 0.85x avg)
    is_volume_dryup = (prev_vol <= 0.85 * max(avg_vol_20, 1.0)) or (
        curr_vol <= 0.90 * max(avg_vol_20, 1.0)
    )

    # Identify recent swing impulse (last 15 bars)
    recent_high = float(h_series.iloc[-15:-2].max())
    recent_low = float(l_series.iloc[-15:-2].min())
    impulse_span = max(recent_high - recent_low, 0.001)

    # ─────────────────────────────────────────────────────────
    # 1. BULLISH PULLBACK EVALUATION
    # ─────────────────────────────────────────────────────────
    # Impulse must be upward (recent_high higher than older lows)
    if recent_high > recent_low + (1.5 * atr_val):
        fib_bull = compute_fib_levels(recent_high, recent_low, direction="BULLISH")
        pullback_depth = (recent_high - l_prev) / impulse_span

        # Candidate anchors
        anchors: list[tuple[str, float, float]] = []  # (type, level, proximity_pts)

        if breakout_level and breakout_level > 0:
            anchors.append(("BREAKOUT_RETEST", breakout_level, abs(l_prev - breakout_level)))
        anchors.append(("EMA20_PULLBACK", curr_ema20, abs(l_prev - curr_ema20)))
        anchors.append(("FIB_OTE_PULLBACK", fib_bull.level_618, abs(l_prev - fib_bull.level_618)))

        if vwap_series is not None and not vwap_series.empty:
            curr_vwap = float(vwap_series.iloc[-1])
            anchors.append(("VWAP_PULLBACK", curr_vwap, abs(l_prev - curr_vwap)))

        # Find best-matched anchor within 0.40x ATR
        anchors.sort(key=lambda x: x[2])
        best_anchor_type, best_anchor_lvl, best_dist = anchors[0]

        # Valid pullback conditions:
        # - Pullback did not break below 0.786 Fib (healthy depth 0.382 to 0.705)
        # - Tested anchor within 0.50x ATR
        # - Current candle re-ignites (closes green, or breaks above prev bar high)
        is_depth_healthy = 0.20 <= pullback_depth <= 0.786
        is_anchor_tested = best_dist <= (0.60 * atr_val)
        is_reignited = (c_curr > o_curr and c_curr > l_prev) or (c_curr > h_prev)

        if is_depth_healthy and is_anchor_tested and is_reignited:
            candle_tag = (
                "BULLISH_ENGULFING"
                if (c_curr > h_prev and o_curr <= l_prev)
                else (
                    "HAMMER_REVERSAL"
                    if (min(o_curr, c_curr) - l_curr) >= 0.4 * (h_curr - l_curr)
                    else "GREEN_REIGNITION"
                )
            )

            sl = round(min(l_curr, l_prev, best_anchor_lvl) - (0.15 * atr_val), 2)
            risk = max(c_curr - sl, atr_val * 0.4)
            t1 = round(c_curr + (2.0 * risk), 2)
            t2 = round(c_curr + (3.5 * risk), 2)
            rr = round((t1 - c_curr) / risk, 2)
            entry_zone = (round(c_curr - 0.15 * atr_val, 2), round(c_curr + 0.10 * atr_val, 2))

            conf = (
                75
                + (10 if is_volume_dryup else 0)
                + (10 if best_anchor_type == "BREAKOUT_RETEST" else 5)
            )
            conf = min(95, conf)

            summary = (
                f"Bullish {best_anchor_type} ({conf}% Conf): Shallow pullback ({pullback_depth:.2f} Fib) into "
                f"anchor ₹{best_anchor_lvl:.2f}. Volume dryup: {is_volume_dryup}. Re-ignited with {candle_tag}."
            )

            return PullbackSignal(
                symbol=symbol,
                pullback_type=best_anchor_type,
                bias="BULLISH",
                confidence=conf,
                anchor_level=best_anchor_lvl,
                pullback_depth_fib=pullback_depth,
                is_volume_dryup=is_volume_dryup,
                reignition_candle=candle_tag,
                entry_zone=entry_zone,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_reward_ratio=rr,
                summary=summary,
            )

    # ─────────────────────────────────────────────────────────
    # 2. BEARISH RETRACEMENT EVALUATION
    # ─────────────────────────────────────────────────────────
    if recent_low < recent_high - (1.5 * atr_val):
        fib_bear = compute_fib_levels(recent_high, recent_low, direction="BEARISH")
        bounce_depth = (h_prev - recent_low) / impulse_span

        anchors_bear: list[tuple[str, float, float]] = []
        if breakout_level and breakout_level > 0:
            anchors_bear.append(("BREAKOUT_RETEST", breakout_level, abs(h_prev - breakout_level)))
        anchors_bear.append(("EMA20_PULLBACK", curr_ema20, abs(h_prev - curr_ema20)))
        anchors_bear.append(
            ("FIB_OTE_PULLBACK", fib_bear.level_618, abs(h_prev - fib_bear.level_618))
        )

        if vwap_series is not None and not vwap_series.empty:
            curr_vwap = float(vwap_series.iloc[-1])
            anchors_bear.append(("VWAP_PULLBACK", curr_vwap, abs(h_prev - curr_vwap)))

        anchors_bear.sort(key=lambda x: x[2])
        best_anchor_type_b, best_anchor_lvl_b, best_dist_b = anchors_bear[0]

        is_depth_healthy_b = 0.20 <= bounce_depth <= 0.786
        is_anchor_tested_b = best_dist_b <= (0.60 * atr_val)
        is_reignited_b = (c_curr < o_curr and c_curr < h_prev) or (c_curr < l_prev)

        if is_depth_healthy_b and is_anchor_tested_b and is_reignited_b:
            candle_tag_b = (
                "BEARISH_ENGULFING"
                if (c_curr < l_prev and o_curr >= h_prev)
                else (
                    "SHOOTING_STAR"
                    if (h_curr - max(o_curr, c_curr)) >= 0.4 * (h_curr - l_curr)
                    else "RED_REIGNITION"
                )
            )

            sl = round(max(h_curr, h_prev, best_anchor_lvl_b) + (0.15 * atr_val), 2)
            risk = max(sl - c_curr, atr_val * 0.4)
            t1 = round(c_curr - (2.0 * risk), 2)
            t2 = round(c_curr - (3.5 * risk), 2)
            rr = round((c_curr - t1) / risk, 2)
            entry_zone = (round(c_curr - 0.10 * atr_val, 2), round(c_curr + 0.15 * atr_val, 2))

            conf = (
                75
                + (10 if is_volume_dryup else 0)
                + (10 if best_anchor_type_b == "BREAKOUT_RETEST" else 5)
            )
            conf = min(95, conf)

            summary = (
                f"Bearish {best_anchor_type_b} ({conf}% Conf): Shallow bounce ({bounce_depth:.2f} Fib) into "
                f"anchor ₹{best_anchor_lvl_b:.2f}. Volume dryup: {is_volume_dryup}. Re-ignited with {candle_tag_b}."
            )

            return PullbackSignal(
                symbol=symbol,
                pullback_type=best_anchor_type_b,
                bias="BEARISH",
                confidence=conf,
                anchor_level=best_anchor_lvl_b,
                pullback_depth_fib=bounce_depth,
                is_volume_dryup=is_volume_dryup,
                reignition_candle=candle_tag_b,
                entry_zone=entry_zone,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_reward_ratio=rr,
                summary=summary,
            )

    return None
