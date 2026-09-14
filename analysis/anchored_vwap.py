"""
analysis/anchored_vwap.py
─────────────────────────
Institutional Event-Driven Anchored Volume-Weighted Average Price (AVWAP).

Calculates institutional cost-basis anchors and standard deviation volatility envelopes:
  1. Swing Low Anchor: The institutional accumulation baseline since the prior market trough.
  2. Swing High Anchor: The institutional distribution baseline since the prior market peak.
  3. Session Open Anchor: Intraday VWAP starting strictly from 09:15 IST.
  4. Earnings / High-Volume Catalyst Anchor: Sets the cost basis of the news shock.
  5. Multi-Period Volatility Envelopes:
     Band_1 = AVWAP +/- 1.0 * Volatility_Stdev
     Band_2 = AVWAP +/- 2.0 * Volatility_Stdev
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class AnchoredVWAPResult:
    anchor_type: str  # "SWING_LOW" | "SWING_HIGH" | "SESSION_OPEN" | "HIGH_VOLUME_CATALYST"
    anchor_date: str
    anchor_price: float
    current_avwap: float
    upper_band_1: float
    lower_band_1: float
    upper_band_2: float
    lower_band_2: float
    distance_pct: float  # (LTP - AVWAP) / AVWAP * 100
    confluence_status: (
        str  # "AT_SUPPORT_BOUNCE" | "AT_RESISTANCE_REJECTION" | "ABOVE_BULLISH" | "BELOW_BEARISH"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_anchored_vwap(
    df: pd.DataFrame,
    anchor_index: int = 0,
    anchor_type: str = "SWING_LOW",
) -> Optional[AnchoredVWAPResult]:
    """
    Computes Anchored VWAP from a specified integer row index to the end of the DataFrame.
    """
    if df is None or len(df) <= anchor_index or len(df) == 0:
        return None

    try:
        # Standardize column names
        cols = {c.lower(): c for c in df.columns}
        c_close = cols.get("close")
        c_high = cols.get("high")
        c_low = cols.get("low")
        c_vol = cols.get("volume")

        if not (c_close and c_vol):
            return None

        sub = df.iloc[anchor_index:].copy()
        if len(sub) == 0:
            return None

        # Typical price: (High + Low + Close) / 3 or Close
        if c_high and c_low:
            typical_price = (sub[c_high] + sub[c_low] + sub[c_close]) / 3.0
        else:
            typical_price = sub[c_close]

        vol = sub[c_vol].fillna(1.0)
        # Avoid division by zero if all volume is 0
        if vol.sum() == 0:
            vol = pd.Series(1.0, index=sub.index)

        pv = typical_price * vol
        cum_pv = pv.cumsum()
        cum_vol = vol.cumsum()
        avwap_series = cum_pv / cum_vol

        current_avwap = float(avwap_series.iloc[-1])
        ltp = float(sub[c_close].iloc[-1])

        # Variance and Standard Deviation Bands
        sq_diff = (typical_price - avwap_series) ** 2
        cum_sq_diff = (sq_diff * vol).cumsum()
        stdev_series = np.sqrt(cum_sq_diff / cum_vol).fillna(0.0)
        cur_stdev = (
            float(stdev_series.iloc[-1]) if len(stdev_series) > 0 else (current_avwap * 0.015)
        )

        upper_1 = round(current_avwap + cur_stdev, 2)
        lower_1 = round(max(0.01, current_avwap - cur_stdev), 2)
        upper_2 = round(current_avwap + 2.0 * cur_stdev, 2)
        lower_2 = round(max(0.01, current_avwap - 2.0 * cur_stdev), 2)

        dist_pct = (
            round(((ltp - current_avwap) / current_avwap) * 100, 2) if current_avwap > 0 else 0.0
        )

        # Confluence classification
        # Proximity threshold: within +/- 0.6% of AVWAP
        if abs(dist_pct) <= 0.6:
            status = "AT_SUPPORT_BOUNCE" if dist_pct >= 0 else "AT_RESISTANCE_REJECTION"
        elif dist_pct > 0:
            status = "ABOVE_BULLISH"
        else:
            status = "BELOW_BEARISH"

        # Anchor date resolution
        anchor_row = df.iloc[anchor_index]
        date_val = str(anchor_row.name if hasattr(anchor_row, "name") else "")
        if not date_val or date_val.isdigit():
            for d_col in ("date", "datetime", "timestamp", "Date", "Datetime"):
                if d_col in df.columns:
                    date_val = str(df[d_col].iloc[anchor_index])
                    break

        anchor_p = float(df[c_close].iloc[anchor_index])

        return AnchoredVWAPResult(
            anchor_type=anchor_type,
            anchor_date=str(date_val)[:19],
            anchor_price=round(anchor_p, 2),
            current_avwap=round(current_avwap, 2),
            upper_band_1=upper_1,
            lower_band_1=lower_1,
            upper_band_2=upper_2,
            lower_band_2=lower_2,
            distance_pct=dist_pct,
            confluence_status=status,
        )
    except Exception:
        return None


def detect_structural_anchors(df: pd.DataFrame) -> list[AnchoredVWAPResult]:
    """
    Automatically detects significant structural points (Major Swing Low, Swing High, and RVOL spike)
    and computes AVWAP from each anchor.
    """
    if df is None or len(df) < 15:
        return []

    results: list[AnchoredVWAPResult] = []
    cols = {c.lower(): c for c in df.columns}
    c_close = cols.get("close")
    c_low = cols.get("low", c_close)
    c_high = cols.get("high", c_close)
    c_vol = cols.get("volume")

    try:
        # 1. Major Swing Low in prior 60 bars (or full length)
        lookback = min(len(df), 60)
        sub_lows = df[c_low].iloc[-lookback:]
        min_idx_relative = int(sub_lows.values.argmin())
        abs_min_idx = len(df) - lookback + min_idx_relative
        if abs_min_idx < len(df) - 1:
            res_low = compute_anchored_vwap(df, abs_min_idx, "SWING_LOW")
            if res_low:
                results.append(res_low)

        # 2. Major Swing High in prior 60 bars
        sub_highs = df[c_high].iloc[-lookback:]
        max_idx_relative = int(sub_highs.values.argmax())
        abs_max_idx = len(df) - lookback + max_idx_relative
        if abs_max_idx < len(df) - 1 and abs_max_idx != abs_min_idx:
            res_high = compute_anchored_vwap(df, abs_max_idx, "SWING_HIGH")
            if res_high:
                results.append(res_high)

        # 3. High Volume Catalyst Bar (RVOL >= 2.5x)
        if c_vol:
            vols = df[c_vol].fillna(1.0)
            avg_vol = vols.rolling(20, min_periods=5).mean()
            rvol = vols / avg_vol.replace(0, 1)
            # Find the most recent bar with RVOL >= 2.2 in prior 30 bars
            recent_rvols = rvol.iloc[-min(len(df), 30) : -1]
            spike_indices = [idx for idx, val in enumerate(recent_rvols.values) if val >= 2.2]
            if spike_indices:
                last_spike_rel = spike_indices[-1]
                abs_spike_idx = len(df) - min(len(df), 30) + last_spike_rel
                if abs_spike_idx != abs_min_idx and abs_spike_idx != abs_max_idx:
                    res_catalyst = compute_anchored_vwap(df, abs_spike_idx, "HIGH_VOLUME_CATALYST")
                    if res_catalyst:
                        results.append(res_catalyst)
    except Exception:
        pass

    return results
