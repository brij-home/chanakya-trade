"""
analysis/bar_patterns.py
────────────────────────
Institutional Price Action & Structural Bar Pattern Engine.

Implements Rob Smith's 'The Strat' (1-Inside, 2-Directional, 3-Outside),
Toby Crabel's NR4 / NR7 volatility compression, The Strat 2-1-2 Continuation setups,
and Dan Chesler's Hikkake False-Breakout Reversal pattern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.analysis.bar_patterns")


@dataclass
class BarStratClassification:
    strat_type: int  # 1 (Inside), 2 (Directional), 3 (Outside)
    direction: str  # "UP", "DOWN", "INSIDE", "OUTSIDE"
    high: float
    low: float
    close: float
    open: float
    range_pts: float
    is_nr4: bool = False
    is_nr7: bool = False


@dataclass
class BarPatternSignal:
    symbol: str
    pattern_name: str  # e.g. "STRAT_2_1_2_BULLISH", "STRAT_2_1_2_BEARISH", "HIKKAKE_BULLISH", "HIKKAKE_BEARISH", "NR7_VOLATILITY_COIL", "OUTSIDE_BAR_ABSORPTION"
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: int  # 0 to 100
    strat_sequence: list[str] = field(default_factory=list)  # e.g. ["2U", "1", "2U"]
    is_coiled_compression: bool = False  # True for NR4/NR7/Inside Day
    mother_bar_high: float = 0.0
    mother_bar_low: float = 0.0
    entry_trigger: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward_ratio: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "pattern_name": self.pattern_name,
            "bias": self.bias,
            "confidence": self.confidence,
            "strat_sequence": self.strat_sequence,
            "is_coiled_compression": self.is_coiled_compression,
            "mother_bar_high": self.mother_bar_high,
            "mother_bar_low": self.mother_bar_low,
            "entry_trigger": self.entry_trigger,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "summary": self.summary,
        }


def classify_bar_strat(
    current_bar: pd.Series,
    prior_bar: pd.Series,
) -> BarStratClassification:
    """
    Classifies a candlestick into Rob Smith's 'The Strat' hierarchy:
      - 1: Inside Bar (High <= Prior High and Low >= Prior Low)
      - 2 Up: High > Prior High and Low >= Prior Low
      - 2 Down: High <= Prior High and Low < Prior Low
      - 3: Outside Bar (High > Prior High and Low < Prior Low)
    """
    c_h = float(current_bar.get("high", current_bar["close"]))
    c_l = float(current_bar.get("low", current_bar["close"]))
    c_c = float(current_bar["close"])
    c_o = float(current_bar.get("open", c_c))
    c_range = max(c_h - c_l, 0.001)

    p_h = float(prior_bar.get("high", prior_bar["close"]))
    p_l = float(prior_bar.get("low", prior_bar["close"]))

    # Type 1: Inside Bar
    if c_h <= p_h and c_l >= p_l:
        return BarStratClassification(
            strat_type=1,
            direction="INSIDE",
            high=c_h,
            low=c_l,
            close=c_c,
            open=c_o,
            range_pts=c_range,
        )

    # Type 3: Outside Bar
    elif c_h > p_h and c_l < p_l:
        return BarStratClassification(
            strat_type=3,
            direction="OUTSIDE",
            high=c_h,
            low=c_l,
            close=c_c,
            open=c_o,
            range_pts=c_range,
        )

    # Type 2: Directional
    elif c_h > p_h:
        return BarStratClassification(
            strat_type=2,
            direction="UP",
            high=c_h,
            low=c_l,
            close=c_c,
            open=c_o,
            range_pts=c_range,
        )
    else:
        return BarStratClassification(
            strat_type=2,
            direction="DOWN",
            high=c_h,
            low=c_l,
            close=c_c,
            open=c_o,
            range_pts=c_range,
        )


def detect_nr_compression(df: pd.DataFrame) -> tuple[bool, bool]:
    """
    Evaluates Toby Crabel's NR4 (Narrowest Range 4) and NR7 (Narrowest Range 7)
    volatility compression on the latest bar.
    """
    if len(df) < 4:
        return False, False

    cols = {c.lower(): c for c in df.columns}
    ranges = (df[cols["high"]] - df[cols["low"]]).astype(float)
    curr_range = float(ranges.iloc[-1])

    is_nr4 = curr_range < float(ranges.iloc[-4:-1].min())
    is_nr7 = False
    if len(df) >= 7:
        is_nr7 = curr_range < float(ranges.iloc[-7:-1].min())

    return is_nr4, is_nr7


def analyze_bar_patterns(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    atr_val: Optional[float] = None,
) -> Optional[BarPatternSignal]:
    """
    Evaluates candlestick sequences for institutional Strat, NR compression, and Hikkake patterns.
    Requires at least 5 bars of history.
    """
    if df is None or len(df) < 5:
        return None

    cols = {c.lower(): c for c in df.columns}
    h_series = df[cols["high"]].astype(float)
    l_series = df[cols["low"]].astype(float)
    c_series = df[cols["close"]].astype(float)

    curr = df.iloc[-1]
    prev1 = df.iloc[-2]
    prev2 = df.iloc[-3]
    prev3 = df.iloc[-4] if len(df) >= 4 else prev2

    c_c = float(curr["close"])
    c_h = float(curr[cols["high"]])
    c_l = float(curr[cols["low"]])
    curr_range = max(c_h - c_l, 0.001)

    p1_h = float(prev1[cols["high"]])
    p1_l = float(prev1[cols["low"]])

    p2_h = float(prev2[cols["high"]])
    p2_l = float(prev2[cols["low"]])

    # Calculate ATR buffer
    if atr_val is None or atr_val <= 0:
        tr = pd.concat(
            [
                h_series - l_series,
                (h_series - c_series.shift()).abs(),
                (l_series - c_series.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_val = float(tr.rolling(14, min_periods=5).mean().iloc[-1])
        if np.isnan(atr_val) or atr_val <= 0:
            atr_val = max(c_c * 0.01, 1.0)

    strat_curr = classify_bar_strat(curr, prev1)
    strat_prev1 = classify_bar_strat(prev1, prev2)
    strat_prev2 = classify_bar_strat(prev2, prev3)

    seq_str = [
        f"{strat_prev2.strat_type}{strat_prev2.direction[0]}",
        f"{strat_prev1.strat_type}{strat_prev1.direction[0]}",
        f"{strat_curr.strat_type}{strat_curr.direction[0]}",
    ]

    is_nr4, is_nr7 = detect_nr_compression(df)

    # ─────────────────────────────────────────────────────────
    # 1. HIKKAKE PATTERN (Dan Chesler False Breakout Reversal)
    # ─────────────────────────────────────────────────────────
    # Sequence: Mother Bar (prev3/prev2) -> Inside Bar (prev2) -> Trap Breakout (prev1) -> Violent Reversal (curr)
    # Bullish Hikkake:
    #   - prev2 was Inside Bar inside prev3
    #   - prev1 broke below Inside Bar low (false breakdown trap)
    #   - curr sharply reverses and closes back above Inside Bar high (or mother bar high)
    if strat_prev2.strat_type == 1 and p1_l < p2_l and c_c > p2_h:
        entry = round(p2_h + (0.05 * atr_val), 2)
        sl = round(min(p1_l, c_l) - (0.15 * atr_val), 2)
        risk = max(entry - sl, atr_val * 0.5)
        t1 = round(entry + (2.0 * risk), 2)
        t2 = round(entry + (3.5 * risk), 2)
        rr = round((t1 - entry) / risk, 2)
        return BarPatternSignal(
            symbol=symbol,
            pattern_name="HIKKAKE_BULLISH",
            bias="BULLISH",
            confidence=85,
            strat_sequence=seq_str,
            mother_bar_high=p2_h,
            mother_bar_low=p2_l,
            entry_trigger=entry,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward_ratio=rr,
            summary=f"Bullish Hikkake Trap Reversal: Trapped bears at {p1_l:.2f}. Immediate reclaim above mother bar {p2_h:.2f} confirms squeeze.",
        )

    # Bearish Hikkake:
    #   - prev2 was Inside Bar inside prev3
    #   - prev1 broke above Inside Bar high (false breakout trap)
    #   - curr sharply reverses and closes back below Inside Bar low
    elif strat_prev2.strat_type == 1 and p1_h > p2_h and c_c < p2_l:
        entry = round(p2_l - (0.05 * atr_val), 2)
        sl = round(max(p1_h, c_h) + (0.15 * atr_val), 2)
        risk = max(sl - entry, atr_val * 0.5)
        t1 = round(entry - (2.0 * risk), 2)
        t2 = round(entry - (3.5 * risk), 2)
        rr = round((entry - t1) / risk, 2)
        return BarPatternSignal(
            symbol=symbol,
            pattern_name="HIKKAKE_BEARISH",
            bias="BEARISH",
            confidence=85,
            strat_sequence=seq_str,
            mother_bar_high=p2_h,
            mother_bar_low=p2_l,
            entry_trigger=entry,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward_ratio=rr,
            summary=f"Bearish Hikkake Trap Reversal: Trapped bulls at {p1_h:.2f}. Immediate breakdown below mother bar {p2_l:.2f} confirms liquidation.",
        )

    # ─────────────────────────────────────────────────────────
    # 2. THE STRAT 2-1-2 CONTINUATION
    # ─────────────────────────────────────────────────────────
    # Bullish 2-1-2: Directional 2 Up -> Inside Bar (1) -> Directional 2 Up Breakout
    if (
        strat_prev2.strat_type == 2
        and strat_prev2.direction == "UP"
        and strat_prev1.strat_type == 1
        and strat_curr.strat_type == 2
        and strat_curr.direction == "UP"
    ):
        entry = round(p1_h + (0.05 * atr_val), 2)
        sl = round(p1_l - (0.15 * atr_val), 2)
        risk = max(entry - sl, atr_val * 0.4)
        t1 = round(entry + (2.0 * risk), 2)
        t2 = round(entry + (3.5 * risk), 2)
        rr = round((t1 - entry) / risk, 2)
        conf = 88 if is_nr4 or is_nr7 else 80
        return BarPatternSignal(
            symbol=symbol,
            pattern_name="STRAT_2_1_2_BULLISH",
            bias="BULLISH",
            confidence=conf,
            strat_sequence=seq_str,
            is_coiled_compression=(is_nr4 or is_nr7),
            mother_bar_high=p1_h,
            mother_bar_low=p1_l,
            entry_trigger=entry,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward_ratio=rr,
            summary=f"The Strat 2-1-2 Bullish Continuation: Breakout above Inside Bar {p1_h:.2f} continuing prior impulse.",
        )

    # Bearish 2-1-2: Directional 2 Down -> Inside Bar (1) -> Directional 2 Down Breakdown
    elif (
        strat_prev2.strat_type == 2
        and strat_prev2.direction == "DOWN"
        and strat_prev1.strat_type == 1
        and strat_curr.strat_type == 2
        and strat_curr.direction == "DOWN"
    ):
        entry = round(p1_l - (0.05 * atr_val), 2)
        sl = round(p1_h + (0.15 * atr_val), 2)
        risk = max(sl - entry, atr_val * 0.4)
        t1 = round(entry - (2.0 * risk), 2)
        t2 = round(entry - (3.5 * risk), 2)
        rr = round((entry - t1) / risk, 2)
        conf = 88 if is_nr4 or is_nr7 else 80
        return BarPatternSignal(
            symbol=symbol,
            pattern_name="STRAT_2_1_2_BEARISH",
            bias="BEARISH",
            confidence=conf,
            strat_sequence=seq_str,
            is_coiled_compression=(is_nr4 or is_nr7),
            mother_bar_high=p1_h,
            mother_bar_low=p1_l,
            entry_trigger=entry,
            stop_loss=sl,
            target_1=t1,
            target_2=t2,
            risk_reward_ratio=rr,
            summary=f"The Strat 2-1-2 Bearish Continuation: Breakdown below Inside Bar {p1_l:.2f} continuing prior markdown.",
        )

    # ─────────────────────────────────────────────────────────
    # 3. OUTSIDE BAR (STRAT 3) LIQUIDITY ABSORPTION / DISTRIBUTION
    # ─────────────────────────────────────────────────────────
    # Bar 3 sweeps both high and low of prior bar.
    if strat_curr.strat_type == 3:
        close_pos = (c_c - c_l) / curr_range  # 0.0 at low, 1.0 at high
        # Bullish Absorption Outside Bar: swept prior low, closed at top quartile (>75%)
        if close_pos >= 0.70:
            entry = round(c_h + (0.05 * atr_val), 2)
            sl = round(c_l - (0.15 * atr_val), 2)
            risk = max(entry - sl, atr_val * 0.5)
            t1 = round(entry + (2.0 * risk), 2)
            t2 = round(entry + (3.5 * risk), 2)
            rr = round((t1 - entry) / risk, 2)
            return BarPatternSignal(
                symbol=symbol,
                pattern_name="OUTSIDE_BAR_BULLISH_ABSORPTION",
                bias="BULLISH",
                confidence=82,
                strat_sequence=seq_str,
                entry_trigger=entry,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_reward_ratio=rr,
                summary=f"Outside Bar Bullish Absorption: Dual liquidity sweep closed at {close_pos * 100:.0f}% of range. Smart money absorbed supply.",
            )

        # Bearish Distribution Outside Bar: swept prior high, closed at bottom quartile (<30%)
        elif close_pos <= 0.30:
            entry = round(c_l - (0.05 * atr_val), 2)
            sl = round(c_h + (0.15 * atr_val), 2)
            risk = max(sl - entry, atr_val * 0.5)
            t1 = round(entry - (2.0 * risk), 2)
            t2 = round(entry - (3.5 * risk), 2)
            rr = round((entry - t1) / risk, 2)
            return BarPatternSignal(
                symbol=symbol,
                pattern_name="OUTSIDE_BAR_BEARISH_DISTRIBUTION",
                bias="BEARISH",
                confidence=82,
                strat_sequence=seq_str,
                entry_trigger=entry,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_reward_ratio=rr,
                summary=f"Outside Bar Bearish Distribution: Dual liquidity sweep closed at {close_pos * 100:.0f}% of range. Institutional distribution into retail breakout.",
            )

    # ─────────────────────────────────────────────────────────
    # 4. NR7 VOLATILITY COIL (EARLY WARNING)
    # ─────────────────────────────────────────────────────────
    if strat_curr.strat_type == 1 and (is_nr4 or is_nr7):
        pattern = "NR7_VOLATILITY_COIL" if is_nr7 else "NR4_INSIDE_COMPRESSION"
        return BarPatternSignal(
            symbol=symbol,
            pattern_name=pattern,
            bias="NEUTRAL",
            confidence=75,
            strat_sequence=seq_str,
            is_coiled_compression=True,
            mother_bar_high=p1_h,
            mother_bar_low=p1_l,
            entry_trigger=p1_h,
            stop_loss=p1_l,
            summary=f"Extreme Volatility Coiling ({pattern}): Narrowest range in session. Prepare straddle/bracket order on break of [{p1_l:.2f} - {p1_h:.2f}].",
        )

    return None
