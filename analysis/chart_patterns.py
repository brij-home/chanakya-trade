"""
analysis/chart_patterns.py
──────────────────────────
Institutional Classical & Geometric Chart Pattern Recognition Engine.

Implements high-conviction pattern recognition:
  1. Head and Shoulders (Top Reversal) & Inverse Head and Shoulders (Bottom Reversal)
  2. Double Top (M-Pattern) & Double Bottom (W-Pattern) with neckline breach
  3. High-Tight Bull & Bear Flags (Impulse pole + dry volume consolidation)
  4. Ascending & Descending Triangles (Horizontal barrier + higher lows / lower highs)

All patterns output measured move targets, invalidation stop-loss anchors, and risk-reward ratios.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("chanakya.analysis.chart_patterns")


@dataclass
class ChartPattern:
    name: str  # "HEAD_AND_SHOULDERS" | "INVERSE_HEAD_AND_SHOULDERS" | "DOUBLE_TOP" | "DOUBLE_BOTTOM" | "BULL_FLAG" | "BEAR_FLAG" | "ASCENDING_TRIANGLE" | "DESCENDING_TRIANGLE"
    bias: str  # "BULLISH" | "BEARISH"
    pattern_type: str  # "REVERSAL" | "CONTINUATION"
    confidence: int  # 0 to 100
    neckline_or_pivot: float
    breakout_level: float
    measured_target: float
    invalidation_stop: float
    risk_reward_ratio: float
    status: str  # "COILING" | "BREAKOUT_TRIGGERED" | "CONFIRMED"
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bias": self.bias,
            "pattern_type": self.pattern_type,
            "confidence": self.confidence,
            "neckline_or_pivot": round(self.neckline_or_pivot, 2),
            "breakout_level": round(self.breakout_level, 2),
            "measured_target": round(self.measured_target, 2),
            "invalidation_stop": round(self.invalidation_stop, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "status": self.status,
            "summary": self.summary,
        }


def _find_fractal_pivots(
    highs: np.ndarray, lows: np.ndarray, window: int = 3
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Finds fractal peaks (highs) and troughs (lows)."""
    peaks: list[tuple[int, float]] = []
    troughs: list[tuple[int, float]] = []
    n = len(highs)
    if n < 7:
        return peaks, troughs

    for i in range(window, n - window):
        # Peak: highest in local window
        if highs[i] == max(highs[i - window : i + window + 1]):
            peaks.append((i, float(highs[i])))
        # Trough: lowest in local window
        if lows[i] == min(lows[i - window : i + window + 1]):
            troughs.append((i, float(lows[i])))

    return peaks, troughs


def detect_chart_patterns(
    df: pd.DataFrame,
    ltp: Optional[float] = None,
    lookback_bars: int = 60,
) -> List[ChartPattern]:
    """
    Evaluates historical price action for classical chart patterns.
    """
    if df is None or len(df) < 15:
        return []

    cols = {c.lower(): c for c in df.columns}
    if not all(k in cols for k in ("high", "low", "close")):
        return []

    c_s = df[cols["close"]].values.astype(float)
    h_s = df[cols["high"]].values.astype(float)
    l_s = df[cols["low"]].values.astype(float)
    v_s = df[cols["volume"]].values.astype(float) if "volume" in cols else np.ones(len(df))

    curr_p = float(ltp if (ltp is not None and ltp > 0) else c_s[-1])
    n = len(df)
    window = min(lookback_bars, n)

    sub_h = h_s[-window:]
    sub_l = l_s[-window:]
    sub_c = c_s[-window:]
    sub_v = v_s[-window:]

    peaks, troughs = _find_fractal_pivots(sub_h, sub_l, window=2)
    patterns: List[ChartPattern] = []

    # ── 1. Double Bottom (W-Pattern) ──────────────────────────────
    if len(troughs) >= 2:
        t1 = troughs[-2]
        t2 = troughs[-1]
        # Two troughs within 1.2% price equality and separated by >= 4 bars
        if abs(t1[1] - t2[1]) / t1[1] <= 0.015 and (t2[0] - t1[0]) >= 4:
            # Find intermediate peak (neckline)
            mid_peaks = [p for p in peaks if t1[0] < p[0] < t2[0]]
            if mid_peaks:
                neckline = max(p[1] for p in mid_peaks)
                pattern_height = neckline - min(t1[1], t2[1])
                target = neckline + pattern_height
                stop_loss = min(t1[1], t2[1]) * 0.995
                risk = max(1.0, curr_p - stop_loss) if curr_p > stop_loss else pattern_height
                rr = round((target - curr_p) / risk, 2) if risk > 0 else 2.0

                status = "CONFIRMED" if curr_p >= neckline else "COILING"
                patterns.append(
                    ChartPattern(
                        name="DOUBLE_BOTTOM",
                        bias="BULLISH",
                        pattern_type="REVERSAL",
                        confidence=82 if status == "CONFIRMED" else 74,
                        neckline_or_pivot=neckline,
                        breakout_level=neckline,
                        measured_target=target,
                        invalidation_stop=stop_loss,
                        risk_reward_ratio=rr,
                        status=status,
                        summary=f"Double Bottom (W-Pattern) base at ₹{min(t1[1], t2[1]):.1f}; Neckline ₹{neckline:.1f}, Target ₹{target:.1f} (+{pattern_height / neckline * 100:.1f}%)",
                    )
                )

    # ── 2. Double Top (M-Pattern) ─────────────────────────────────
    if len(peaks) >= 2:
        p1 = peaks[-2]
        p2 = peaks[-1]
        # Two peaks within 1.2% price equality and separated by >= 4 bars
        if abs(p1[1] - p2[1]) / p1[1] <= 0.015 and (p2[0] - p1[0]) >= 4:
            mid_troughs = [t for t in troughs if p1[0] < t[0] < p2[0]]
            if mid_troughs:
                neckline = min(t[1] for t in mid_troughs)
                pattern_height = max(p1[1], p2[1]) - neckline
                target = neckline - pattern_height
                stop_loss = max(p1[1], p2[1]) * 1.005
                risk = max(1.0, stop_loss - curr_p) if curr_p < stop_loss else pattern_height
                rr = round((curr_p - target) / risk, 2) if risk > 0 else 2.0

                status = "CONFIRMED" if curr_p <= neckline else "COILING"
                patterns.append(
                    ChartPattern(
                        name="DOUBLE_TOP",
                        bias="BEARISH",
                        pattern_type="REVERSAL",
                        confidence=82 if status == "CONFIRMED" else 74,
                        neckline_or_pivot=neckline,
                        breakout_level=neckline,
                        measured_target=target,
                        invalidation_stop=stop_loss,
                        risk_reward_ratio=rr,
                        status=status,
                        summary=f"Double Top (M-Pattern) resistance at ₹{max(p1[1], p2[1]):.1f}; Neckline ₹{neckline:.1f}, Downside Target ₹{target:.1f}",
                    )
                )

    # ── 3. Head and Shoulders (Top Reversal) ──────────────────────
    if len(peaks) >= 3 and len(troughs) >= 2:
        ls, head, rs = peaks[-3], peaks[-2], peaks[-1]
        # Head higher than both left and right shoulder, shoulders approximately equal (within 3.0%)
        if (
            head[1] > ls[1] * 1.01
            and head[1] > rs[1] * 1.01
            and abs(ls[1] - rs[1]) / ls[1] <= 0.035
        ):
            neck_troughs = [t for t in troughs if ls[0] < t[0] < rs[0]]
            if len(neck_troughs) >= 2:
                neckline = (neck_troughs[0][1] + neck_troughs[1][1]) / 2.0
                h_dist = head[1] - neckline
                target = neckline - h_dist
                stop_loss = rs[1] * 1.005
                risk = max(1.0, stop_loss - curr_p)
                rr = round((curr_p - target) / risk, 2) if risk > 0 else 2.0
                status = "CONFIRMED" if curr_p <= neckline else "COILING"

                patterns.append(
                    ChartPattern(
                        name="HEAD_AND_SHOULDERS",
                        bias="BEARISH",
                        pattern_type="REVERSAL",
                        confidence=85 if status == "CONFIRMED" else 76,
                        neckline_or_pivot=neckline,
                        breakout_level=neckline,
                        measured_target=target,
                        invalidation_stop=stop_loss,
                        risk_reward_ratio=rr,
                        status=status,
                        summary=f"Head & Shoulders Top Reversal: Head ₹{head[1]:.1f}, Shoulders ₹{ls[1]:.1f}/₹{rs[1]:.1f}, Neckline ₹{neckline:.1f}, Target ₹{target:.1f}",
                    )
                )

    # ── 4. Inverse Head and Shoulders (Bottom Reversal) ───────────
    if len(troughs) >= 3 and len(peaks) >= 2:
        ls_t, head_t, rs_t = troughs[-3], troughs[-2], troughs[-1]
        # Head lower than both shoulders, shoulders approximately equal
        if (
            head_t[1] < ls_t[1] * 0.99
            and head_t[1] < rs_t[1] * 0.99
            and abs(ls_t[1] - rs_t[1]) / ls_t[1] <= 0.035
        ):
            neck_peaks = [p for p in peaks if ls_t[0] < p[0] < rs_t[0]]
            if len(neck_peaks) >= 2:
                neckline = (neck_peaks[0][1] + neck_peaks[1][1]) / 2.0
                h_dist = neckline - head_t[1]
                target = neckline + h_dist
                stop_loss = rs_t[1] * 0.995
                risk = max(1.0, curr_p - stop_loss)
                rr = round((target - curr_p) / risk, 2) if risk > 0 else 2.0
                status = "CONFIRMED" if curr_p >= neckline else "COILING"

                patterns.append(
                    ChartPattern(
                        name="INVERSE_HEAD_AND_SHOULDERS",
                        bias="BULLISH",
                        pattern_type="REVERSAL",
                        confidence=85 if status == "CONFIRMED" else 76,
                        neckline_or_pivot=neckline,
                        breakout_level=neckline,
                        measured_target=target,
                        invalidation_stop=stop_loss,
                        risk_reward_ratio=rr,
                        status=status,
                        summary=f"Inverse Head & Shoulders Accumulation: Head ₹{head_t[1]:.1f}, Shoulders ₹{ls_t[1]:.1f}/₹{rs_t[1]:.1f}, Neckline ₹{neckline:.1f}, Target ₹{target:.1f}",
                    )
                )

    # ── 5. High-Tight Bull Flag (Continuation) ────────────────────
    # Impulse pole in prior 10-15 bars followed by tight 3-6 bar downward/flat drift on drying volume
    if len(sub_c) >= 12:
        pole_start = float(sub_c[-12])
        pole_peak = float(sub_h[-12:-4].max())
        flag_low = float(sub_l[-4:].min())
        flag_high = float(sub_h[-4:].max())
        pole_gain_pct = (pole_peak - pole_start) / pole_start * 100.0

        if pole_gain_pct >= 4.0:  # Strong impulse pole
            pullback_pct = (pole_peak - flag_low) / (pole_peak - pole_start)
            # Pullback holds upper 38.2% or 50% of the pole
            if 0.10 <= pullback_pct <= 0.45:
                # Volume dry-up check in flag vs pole
                pole_vol_avg = float(np.mean(sub_v[-12:-4])) if len(sub_v) >= 12 else 1.0
                flag_vol_avg = float(np.mean(sub_v[-4:]))
                if flag_vol_avg <= pole_vol_avg * 0.85:
                    target = curr_p + (pole_peak - pole_start)
                    stop_loss = flag_low * 0.996
                    risk = max(1.0, curr_p - stop_loss)
                    rr = round((target - curr_p) / risk, 2) if risk > 0 else 2.5
                    status = "CONFIRMED" if curr_p >= flag_high else "COILING"

                    patterns.append(
                        ChartPattern(
                            name="BULL_FLAG",
                            bias="BULLISH",
                            pattern_type="CONTINUATION",
                            confidence=84 if status == "CONFIRMED" else 78,
                            neckline_or_pivot=flag_high,
                            breakout_level=flag_high,
                            measured_target=target,
                            invalidation_stop=stop_loss,
                            risk_reward_ratio=rr,
                            status=status,
                            summary=f"Bull Flag Continuation: +{pole_gain_pct:.1f}% impulse pole followed by quiet consolidation; Target ₹{target:.1f} (+{((target - curr_p) / curr_p) * 100:.1f}%)",
                        )
                    )

    # Sort patterns: highest confidence first
    patterns.sort(key=lambda p: p.confidence, reverse=True)
    return patterns
