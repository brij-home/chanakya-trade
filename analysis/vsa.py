"""
analysis/vsa.py
───────────────
Institutional Volume Price Spread Analysis (VPA / VSA) Engine.
Implements Tom Williams & Richard Wyckoff Volume Spread Analysis to detect:
  1. Stopping Volume & Institutional Absorption
  2. No Demand & No Supply (Fake Breakout / Lack of Sponsorship warnings)
  3. Effort vs. Result Divergences (Climax topping and absorption bottoming)
  4. Wide-Spread Absorption Breakouts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd

logger = logging.getLogger("chanakya.analysis.vsa")


@dataclass
class VSASnapshot:
    """Quantitative snapshot of Volume Spread Analysis on the current/recent candle."""

    symbol: str
    timeframe: str  # "INTRADAY" | "DAILY"
    spread: float
    avg_spread_20: float
    spread_ratio: float  # spread / avg_spread
    volume_ratio: float  # volume / avg_volume
    close_in_range_pct: float  # (close - low) / (high - low) * 100
    vsa_signal: str  # "STOPPING_VOLUME" | "NO_DEMAND" | "NO_SUPPLY" | "EFFORT_NO_RESULT_BEARISH" | "EFFORT_NO_RESULT_BULLISH" | "ABSORPTION_BREAKOUT" | "NEUTRAL"
    bias: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    conviction_modifier: int  # -20 to +20 impact
    is_fake_breakout_risk: bool
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "spread": round(self.spread, 2),
            "spread_ratio": round(self.spread_ratio, 2),
            "volume_ratio": round(self.volume_ratio, 2),
            "close_in_range_pct": round(self.close_in_range_pct, 1),
            "vsa_signal": self.vsa_signal,
            "signal": self.vsa_signal,
            "bias": self.bias,
            "conviction_modifier": self.conviction_modifier,
            "is_fake_breakout_risk": self.is_fake_breakout_risk,
            "summary": self.summary,
        }

    @property
    def signal(self) -> str:
        return self.vsa_signal


def analyse_vsa(
    df: pd.DataFrame,
    symbol: str = "UNKNOWN",
    is_intraday: bool = False,
    period: int = 20,
) -> VSASnapshot:
    """
    Evaluates Volume Price Spread Analysis (VSA) on the latest bar of an OHLCV series.
    Tuned for Intraday (5m/15m) vs Daily/Swing bars.
    """
    timeframe = "INTRADAY" if is_intraday else "DAILY"

    if df is None or len(df) < max(period, 5):
        return VSASnapshot(
            symbol=symbol,
            timeframe=timeframe,
            spread=0.0,
            avg_spread_20=0.0,
            spread_ratio=1.0,
            volume_ratio=1.0,
            close_in_range_pct=50.0,
            vsa_signal="NEUTRAL",
            bias="NEUTRAL",
            conviction_modifier=0,
            is_fake_breakout_risk=False,
            summary="Insufficient history for VSA analysis.",
        )

    # Standardize column extraction
    high = df["high"] if "high" in df.columns else df["High"]
    low = df["low"] if "low" in df.columns else df["Low"]
    close = df["close"] if "close" in df.columns else df["Close"]
    volume = df["volume"] if "volume" in df.columns else df["Volume"]

    spreads = (high - low).astype(float)
    vols = volume.astype(float)

    curr_spread = float(spreads.iloc[-1])
    avg_spread = float(spreads.rolling(period, min_periods=min(10, len(spreads))).mean().iloc[-1])
    spread_ratio = curr_spread / max(1e-6, avg_spread)

    curr_vol = float(vols.iloc[-1])
    avg_vol = float(vols.rolling(period, min_periods=min(10, len(vols))).mean().iloc[-1])
    volume_ratio = curr_vol / max(1.0, avg_vol)

    c_curr = float(close.iloc[-1])
    h_curr = float(high.iloc[-1])
    l_curr = float(low.iloc[-1])
    c_prev = float(close.iloc[-2]) if len(close) >= 2 else c_curr

    # Closing position in candle range: 0.0 (at low) to 1.0 (at high)
    candle_span = max(1e-6, h_curr - l_curr)
    close_pos = (c_curr - l_curr) / candle_span
    close_pos_pct = close_pos * 100.0

    lower_wick_ratio = (
        min(c_curr, float(df["open"].iloc[-1] if "open" in df.columns else c_curr)) - l_curr
    ) / candle_span
    upper_wick_ratio = (
        h_curr - max(c_curr, float(df["open"].iloc[-1] if "open" in df.columns else c_curr))
    ) / candle_span

    is_up_bar = c_curr > c_prev
    is_down_bar = c_curr < c_prev

    vsa_signal = "NEUTRAL"
    bias = "NEUTRAL"
    conviction_mod = 0
    fake_breakout = False
    summary = ""

    # 1. Stopping Volume / Absorption Bottom
    # Down bar or gap down with high/ultra-high volume closing in middle or upper third (long lower wick)
    if is_down_bar and volume_ratio >= 1.6 and (close_pos >= 0.45 or lower_wick_ratio >= 0.40):
        vsa_signal = "STOPPING_VOLUME"
        bias = "BULLISH"
        conviction_mod = 15
        summary = (
            f"Stopping Volume / Demand Absorption: Down bar on {volume_ratio:.1f}x volume "
            f"closed at {close_pos_pct:.0f}% of range. Institutional limit orders absorbed selling."
        )

    # 2. Effort vs Result (Bearish Climax / Supply Entry)
    # Up bar with ultra-high volume but narrow spread or closing in bottom half (upper wick rejection)
    elif (
        is_up_bar
        and volume_ratio >= 1.8
        and (spread_ratio <= 0.85 or close_pos <= 0.40 or upper_wick_ratio >= 0.45)
    ):
        vsa_signal = "EFFORT_NO_RESULT_BEARISH"
        bias = "BEARISH"
        conviction_mod = -15
        fake_breakout = True
        summary = (
            f"Effort vs Result Bearish: Heavy volume ({volume_ratio:.1f}x) failed to achieve spread expansion "
            f"(closed at {close_pos_pct:.0f}% of range). Smart money distribution into retail buying."
        )

    # 3. No Demand Bar (Fake Breakout Warning)
    # Up bar breaking or testing high, but on low volume (<0.70x) and narrow spread
    elif is_up_bar and volume_ratio <= 0.65 and spread_ratio <= 0.85:
        vsa_signal = "NO_DEMAND"
        bias = "BEARISH"
        conviction_mod = -10
        fake_breakout = True
        summary = (
            f"No Demand Bar: Price moved up on drying volume ({volume_ratio:.2f}x avg). "
            "Lack of institutional buying sponsorship; high fake breakout risk."
        )

    # 4. No Supply Bar (Springboard Test)
    # Down bar pulling back into support/VWAP on low volume (<0.70x) with small spread
    elif is_down_bar and volume_ratio <= 0.65 and spread_ratio <= 0.80 and close_pos >= 0.35:
        vsa_signal = "NO_SUPPLY"
        bias = "BULLISH"
        conviction_mod = 10
        summary = (
            f"No Supply Test: Down bar on anemic volume ({volume_ratio:.2f}x avg). "
            "Sellers exhausted; springboard condition for continuation."
        )

    # 5. Absorption Breakout
    # Wide spread up bar with heavy volume closing near highs (>70% of range)
    elif is_up_bar and volume_ratio >= 1.5 and spread_ratio >= 1.25 and close_pos >= 0.70:
        vsa_signal = "ABSORPTION_BREAKOUT"
        bias = "BULLISH"
        conviction_mod = 15
        summary = (
            f"Absorption Breakout: Wide spread ({spread_ratio:.1f}x) on heavy volume ({volume_ratio:.1f}x) "
            f"closing near high ({close_pos_pct:.0f}%). Institutional thrust confirmed."
        )

    else:
        summary = f"Normal VSA profile: Spread {spread_ratio:.2f}x, Volume {volume_ratio:.2f}x, Close {close_pos_pct:.0f}%"

    return VSASnapshot(
        symbol=symbol,
        timeframe=timeframe,
        spread=curr_spread,
        avg_spread_20=avg_spread,
        spread_ratio=spread_ratio,
        volume_ratio=volume_ratio,
        close_in_range_pct=close_pos_pct,
        vsa_signal=vsa_signal,
        bias=bias,
        conviction_modifier=conviction_mod,
        is_fake_breakout_risk=fake_breakout,
        summary=summary,
    )
