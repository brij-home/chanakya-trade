"""
analysis/volume_profile.py
──────────────────────────
Institutional Volume Price Analysis (VPA), Relative Volume (RVOL) & Volume Profile Engine.

Computes:
  1. Relative Volume (RVOL): Current bar volume vs 20-day and 50-day SMA volume.
  2. Volume Spread Analysis (VSA):
     - Absorption / Stopping Volume (Institutions absorbing supply near support)
     - Effort vs Result (High volume with minimal price progress — distribution/accumulation)
     - Volume Dry-Up (Pullback absorption / seller exhaustion)
     - No Demand / No Supply Tests
  3. Volume Profile & Value Area:
     - Point of Control (POC - price level with maximum traded volume)
     - Value Area High (VAH - upper boundary of 70% volume)
     - Value Area Low (VAL - lower boundary of 70% volume)
  4. Institutional Footprint Summary: ACCUMULATION, DISTRIBUTION, NEUTRAL, ABSORPTION

Pure numpy/pandas with zero external dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class VSASignal:
    name: str
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    bar_index: int
    date: str
    description: str
    confidence: int = 70


@dataclass
class VolumeProfileBucket:
    price_low: float
    price_high: float
    price_mid: float
    volume: float
    volume_pct: float
    is_poc: bool = False


@dataclass
class VolumeProfileReport:
    symbol: str
    ltp: float
    rvol_20d: float  # Relative Volume vs 20D SMA (e.g. 2.4x)
    rvol_50d: float
    volume_tier: str  # "ULTRA_HIGH" | "HIGH" | "NORMAL" | "DRY_UP"
    
    # Institutional Footprint
    footprint_bias: str  # "ACCUMULATION" | "DISTRIBUTION" | "ABSORPTION" | "NEUTRAL"
    footprint_score: int  # -100 to +100
    
    # Volume Profile Value Area
    poc_price: float  # Point of Control
    vah_price: float  # Value Area High (70%)
    val_price: float  # Value Area Low (70%)
    price_vs_value_area: str  # "ABOVE_VAH" | "INSIDE_VALUE_AREA" | "BELOW_VAL"
    
    # Signals
    vsa_signals: list[VSASignal] = field(default_factory=list)
    profile_buckets: list[VolumeProfileBucket] = field(default_factory=list)
    
    summary: str = ""
    takeaway: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Volume Profile & POC Calculator ───────────────────────────


def compute_volume_profile(df: pd.DataFrame, num_bins: int = 12) -> tuple[float, float, float, list[VolumeProfileBucket]]:
    """
    Computes approximate price-volume distribution (Volume Profile).
    Returns (poc_price, vah_price, val_price, buckets).
    """
    if df is None or len(df) < 5:
        return 0.0, 0.0, 0.0, []

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    vols = df["volume"].values if "volume" in df.columns else np.ones(len(df))

    if len(df) == 0:
        return 0.0, 0.0, 0.0, []

    min_p = float(np.nanmin(lows)) if np.any(~np.isnan(lows)) else 0.0
    max_p = float(np.nanmax(highs)) if np.any(~np.isnan(highs)) else 0.0

    if max_p <= min_p or np.isnan(min_p) or np.isnan(max_p):
        last_close = float(closes[-1]) if len(closes) > 0 and not np.isnan(closes[-1]) else 0.0
        return last_close, last_close, last_close, []

    bin_size = (max_p - min_p) / num_bins
    if bin_size <= 0 or np.isnan(bin_size):
        last_close = float(closes[-1]) if len(closes) > 0 and not np.isnan(closes[-1]) else 0.0
        return last_close, last_close, last_close, []

    bins_vol = np.zeros(num_bins)

    # Distribute volume across candle range
    for i in range(len(df)):
        c_low = lows[i]
        c_high = highs[i]
        c_vol = vols[i]
        
        if np.isnan(c_low) or np.isnan(c_high) or np.isnan(c_vol) or c_vol <= 0:
            continue

        # Approximate which bins this candle intersects
        low_ratio = (c_low - min_p) / bin_size
        high_ratio = (c_high - min_p) / bin_size
        if np.isnan(low_ratio) or np.isnan(high_ratio):
            continue

        start_bin = int(np.clip(low_ratio, 0, num_bins - 1))
        end_bin = int(np.clip(high_ratio, 0, num_bins - 1))
        
        count_bins = max(1, end_bin - start_bin + 1)
        vol_per_bin = c_vol / count_bins
        for b in range(start_bin, end_bin + 1):
            bins_vol[b] += vol_per_bin

    total_vol = np.sum(bins_vol)
    if total_vol <= 0:
        total_vol = 1.0

    poc_idx = int(np.argmax(bins_vol))
    poc_price = min_p + (poc_idx + 0.5) * bin_size

    # Value area: 70% of total volume radiating outward from POC
    target_va_vol = total_vol * 0.70
    accumulated_vol = bins_vol[poc_idx]
    lower_idx = poc_idx
    upper_idx = poc_idx

    while accumulated_vol < target_va_vol and (lower_idx > 0 or upper_idx < num_bins - 1):
        next_low_vol = bins_vol[lower_idx - 1] if lower_idx > 0 else 0
        next_high_vol = bins_vol[upper_idx + 1] if upper_idx < num_bins - 1 else 0

        if next_high_vol >= next_low_vol and upper_idx < num_bins - 1:
            upper_idx += 1
            accumulated_vol += bins_vol[upper_idx]
        elif lower_idx > 0:
            lower_idx -= 1
            accumulated_vol += bins_vol[lower_idx]
        else:
            break

    val_price = min_p + lower_idx * bin_size
    vah_price = min_p + (upper_idx + 1) * bin_size

    # Form buckets
    buckets: list[VolumeProfileBucket] = []
    for b in range(num_bins):
        b_low = min_p + b * bin_size
        b_high = b_low + bin_size
        buckets.append(
            VolumeProfileBucket(
                price_low=round(b_low, 2),
                price_high=round(b_high, 2),
                price_mid=round((b_low + b_high) / 2.0, 2),
                volume=round(float(bins_vol[b]), 0),
                volume_pct=round(float((bins_vol[b] / total_vol) * 100), 1),
                is_poc=(b == poc_idx),
            )
        )

    return round(poc_price, 2), round(vah_price, 2), round(val_price, 2), buckets


# ── Volume Spread Analysis (VSA) Engine ─────────────────────────


def analyze_vsa(df: pd.DataFrame) -> list[VSASignal]:
    """
    Computes Volume Spread Analysis signals on recent bars.
    """
    if df is None or len(df) < 10:
        return []

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    vols = df["volume"].values if "volume" in df.columns else np.ones(len(df))
    dates = df["date"].astype(str).values if "date" in df.columns else [str(i) for i in df.index]

    spreads = highs - lows
    bodies = np.abs(closes - opens)
    avg_vol_20 = np.mean(vols[-20:]) if len(vols) >= 20 else np.mean(vols)
    avg_spread_20 = np.mean(spreads[-20:]) if len(spreads) >= 20 else np.mean(spreads)

    signals: list[VSASignal] = []
    n = len(df)
    check_window = min(10, n)

    for i in range(n - check_window, n):
        c_vol = vols[i]
        c_spread = spreads[i]
        c_body = bodies[i]
        c_close = closes[i]
        c_open = opens[i]
        c_low = lows[i]
        c_high = highs[i]

        vol_ratio = c_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
        spread_ratio = c_spread / avg_spread_20 if avg_spread_20 > 0 else 1.0

        # Close position in bar: 0.0 (at low) to 1.0 (at high)
        close_pos = (c_close - c_low) / c_spread if c_spread > 0 else 0.5

        # 1. Stopping Volume / Absorption (High Volume, Wide Spread, Close off lows near bottom)
        if vol_ratio > 1.8 and close_pos > 0.45 and c_close <= c_open and i > 5:
            # Check if prior bars were declining
            if closes[i - 1] < closes[i - 4]:
                signals.append(
                    VSASignal(
                        name="Absorption / Stopping Volume",
                        bias="BULLISH",
                        bar_index=i,
                        date=str(dates[i]),
                        description=f"Institutions stepped in to absorb heavy selling (RVOL {vol_ratio:.1f}x with close off low).",
                        confidence=85,
                    )
                )

        # 2. Effort vs Result (Very High Volume, Narrow Spread near Highs -> Distribution)
        if vol_ratio > 2.0 and spread_ratio < 0.75:
            if close_pos < 0.6:
                signals.append(
                    VSASignal(
                        name="Effort vs Result (Distribution)",
                        bias="BEARISH",
                        bar_index=i,
                        date=str(dates[i]),
                        description=f"Massive volume ({vol_ratio:.1f}x) failed to push price higher — institutional supply capping.",
                        confidence=80,
                    )
                )

        # 3. Volume Dry-Up on Pullback (Low Volume Test)
        if vol_ratio < 0.55 and spread_ratio < 0.7:
            # Check if overall trend is up
            if closes[i] > closes[max(0, i - 15)]:
                signals.append(
                    VSASignal(
                        name="Volume Dry-Up (Supply Exhaustion)",
                        bias="BULLISH",
                        bar_index=i,
                        date=str(dates[i]),
                        description=f"Low volume ({vol_ratio:.2f}x) pullback confirms lack of aggressive selling pressure.",
                        confidence=75,
                    )
                )

        # 4. Institutional Climax Breakout (High Volume, Wide Spread, Close near High)
        if vol_ratio > 2.2 and spread_ratio > 1.4 and close_pos > 0.8:
            signals.append(
                VSASignal(
                    name="Institutional Expansion Bar",
                    bias="BULLISH",
                    bar_index=i,
                    date=str(dates[i]),
                    description=f"Dominant institutional demand expansion bar (RVOL {vol_ratio:.1f}x closing at highs).",
                    confidence=90,
                )
            )

    return signals


# ── Full Volume Profile & VPA Analyzer ──────────────────────────


def analyze_volume_profile(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
    timeframe: str = "day",
) -> VolumeProfileReport:
    """
    Analyzes Volume Profile, RVOL, and Volume Spread Analysis (VSA).
    """
    if df is None or len(df) == 0:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(symbol, exchange=exchange, interval=timeframe, days=250)
        except Exception:
            df = None

    if df is None or len(df) < 10:
        return VolumeProfileReport(
            symbol=symbol,
            ltp=0.0,
            rvol_20d=1.0,
            rvol_50d=1.0,
            volume_tier="NORMAL",
            footprint_bias="NEUTRAL",
            footprint_score=0,
            poc_price=0.0,
            vah_price=0.0,
            val_price=0.0,
            price_vs_value_area="INSIDE_VALUE_AREA",
            summary="Insufficient volume data.",
            takeaway="Awaiting active volume history.",
        )

    ltp = float(df["close"].iloc[-1])
    vols = df["volume"].values if "volume" in df.columns else np.ones(len(df))

    # 1. RVOL
    current_vol = float(vols[-1])
    avg_20 = float(np.mean(vols[-21:-1])) if len(vols) >= 21 else float(np.mean(vols))
    avg_50 = float(np.mean(vols[-51:-1])) if len(vols) >= 51 else float(np.mean(vols))

    rvol_20 = current_vol / avg_20 if avg_20 > 0 else 1.0
    rvol_50 = current_vol / avg_50 if avg_50 > 0 else 1.0

    if rvol_20 >= 3.0:
        vol_tier = "ULTRA_HIGH"
    elif rvol_20 >= 1.8:
        vol_tier = "HIGH"
    elif rvol_20 < 0.6:
        vol_tier = "DRY_UP"
    else:
        vol_tier = "NORMAL"

    # 2. Volume Profile
    poc_price, vah_price, val_price, buckets = compute_volume_profile(df, num_bins=10)

    if ltp > vah_price:
        va_status = "ABOVE_VAH"
    elif ltp < val_price:
        va_status = "BELOW_VAL"
    else:
        va_status = "INSIDE_VALUE_AREA"

    # 3. VSA Signals
    vsa_signals = analyze_vsa(df)

    # 4. Footprint Bias & Score
    bull_signals = sum(1 for s in vsa_signals if s.bias == "BULLISH")
    bear_signals = sum(1 for s in vsa_signals if s.bias == "BEARISH")

    footprint_score = 0
    if va_status == "ABOVE_VAH":
        footprint_score += 25
    elif va_status == "BELOW_VAL":
        footprint_score -= 25

    if rvol_20 > 1.8 and df["close"].iloc[-1] > df["open"].iloc[-1]:
        footprint_score += 30
    elif rvol_20 > 1.8 and df["close"].iloc[-1] < df["open"].iloc[-1]:
        footprint_score -= 30

    footprint_score += (bull_signals - bear_signals) * 20
    footprint_score = max(-100, min(100, footprint_score))

    if footprint_score >= 35:
        footprint_bias = "ACCUMULATION"
    elif footprint_score <= -35:
        footprint_bias = "DISTRIBUTION"
    elif any(s.name == "Absorption / Stopping Volume" for s in vsa_signals):
        footprint_bias = "ABSORPTION"
    else:
        footprint_bias = "NEUTRAL"

    # Summary
    summary = f"Volume is {vol_tier} (RVOL 20D: {rvol_20:.2f}x). POC at ₹{poc_price:.2f} (VAH: ₹{vah_price:.2f}, VAL: ₹{val_price:.2f}). Footprint: {footprint_bias} (Score: {footprint_score:+d}/100)."
    if va_status == "ABOVE_VAH":
        takeaway = f"Trading above Value Area High (₹{vah_price:.2f}) indicates aggressive institutional buying acceptance."
    elif va_status == "BELOW_VAL":
        takeaway = f"Trading below Value Area Low (₹{val_price:.2f}) reflects institutional rejection / breakdown."
    else:
        takeaway = f"Consolidating inside Value Area (₹{val_price:.2f} – ₹{vah_price:.2f}) around Point of Control ₹{poc_price:.2f}."

    return VolumeProfileReport(
        symbol=symbol,
        ltp=round(ltp, 2),
        rvol_20d=round(rvol_20, 2),
        rvol_50d=round(rvol_50, 2),
        volume_tier=vol_tier,
        footprint_bias=footprint_bias,
        footprint_score=footprint_score,
        poc_price=poc_price,
        vah_price=vah_price,
        val_price=val_price,
        price_vs_value_area=va_status,
        vsa_signals=vsa_signals[-5:],
        profile_buckets=buckets,
        summary=summary,
        takeaway=takeaway,
    )
