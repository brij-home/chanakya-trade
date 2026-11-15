# -*- coding: utf-8 -*-
"""
engine/fractal_entry_coordinator.py
───────────────────────────────────
Dual-Timeframe Fractal Inception & Precision Timing Coordinator.

Bridges Higher-Timeframe (HTF: Daily / 1H / 15m) Zones of Interest (Order Blocks,
FVGs, Confluence Clusters, Liquidity Pools) to Lower-Timeframe (LTF: 1m / 3m / 5m)
Precision Execution.

Core Institutional Execution Principles:
  1. HTF provides the Context & Target (Where to participate, where liquidity rests).
  2. LTF provides the Invalidation & Timing (When to execute, shrinking initial risk R).
  3. Replaces late momentum market orders with:
     - Micro-CHoCH (Change of Character) & Displacement verification.
     - Micro Liquidity Sweep (SFP / Turtle Soup purge).
     - Dynamic Hybrid Limit Placement:
       * Fast Impulse: 50% Fair Value Gap Consequent Encroachment (when RVOL >= 2.0x).
       * Retest OTE: 61.8%–78.6% Optimal Trade Entry (when market is rotational).
  4. 3-Tier Asymmetric Scale-Out Engine:
     * Target 1 (+2.0R): Scale out 50% -> Move Stop-Loss to Breakeven.
     * Target 2 (+4.0R): Scale out 30%.
     * Target Runner: Trail remaining 20% to HTF Liquidity Target (+6.0R to +12.0R).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from analysis.technical import atr

logger = logging.getLogger("chanakya.engine.fractal_entry_coordinator")


@dataclass
class FractalExecutionBlueprint:
    """Actionable precision execution blueprint resulting from Fractal Inception."""

    symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    is_confirmed: bool
    entry_type: str  # "LIMIT_OTE" | "LIMIT_FVG_50" | "STOP_LIMIT_PIVOT" | "UNCONFIRMED_STALK"

    entry_price: float
    stop_loss: float
    target_1: float  # +2.0R
    target_2: float  # +4.0R
    target_runner: float  # HTF Liquidity Target

    risk_reward_ratio: float  # Macro Reward / Micro Risk
    micro_risk_pts: float
    macro_reward_pts: float

    has_micro_sweep: bool
    has_micro_choch: bool
    micro_sweep_level: Optional[float] = None
    displacement_bar_range: float = 0.0

    scale_out_plan: Dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "is_confirmed": self.is_confirmed,
            "entry_type": self.entry_type,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target_1": round(self.target_1, 2),
            "target_2": round(self.target_2, 2),
            "target_runner": round(self.target_runner, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "micro_risk_pts": round(self.micro_risk_pts, 2),
            "macro_reward_pts": round(self.macro_reward_pts, 2),
            "has_micro_sweep": self.has_micro_sweep,
            "has_micro_choch": self.has_micro_choch,
            "micro_sweep_level": round(self.micro_sweep_level, 2)
            if self.micro_sweep_level
            else None,
            "scale_out_plan": self.scale_out_plan,
            "summary": self.summary,
        }


def coordinate_fractal_entry(
    symbol: str,
    direction: str,
    htf_zone: Tuple[float, float],
    htf_target: float,
    df_ltf: Optional[pd.DataFrame],
    ltp: float,
    market_regime: str = "NORMAL",
    atr_ltf: Optional[float] = None,
) -> FractalExecutionBlueprint:
    """
    Coordinates Higher-Timeframe Zone of Interest with Lower-Timeframe Micro-Execution.

    Args:
        symbol: Canonical symbol
        direction: "BULLISH" | "BEARISH"
        htf_zone: (zone_top, zone_bottom)
        htf_target: Target price derived from HTF liquidity
        df_ltf: Lower-timeframe OHLCV DataFrame (1m, 3m, or 5m)
        ltp: Current last traded price
        market_regime: Active macro market regime
        atr_ltf: Pre-computed LTF ATR (optional)
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()
    is_bullish = direction.upper() in ("BULLISH", "LONG", "BUY")
    zone_top, zone_bottom = max(htf_zone), min(htf_zone)
    zone_mid = (zone_top + zone_bottom) / 2.0

    if df_ltf is None or len(df_ltf) < 5:
        # Fallback to HTF Zone midpoint if LTF data is unavailable
        initial_risk = max(0.5, abs(zone_top - zone_bottom))
        sl = (zone_bottom - 0.2 * initial_risk) if is_bullish else (zone_top + 0.2 * initial_risk)
        rr = abs(htf_target - zone_mid) / max(0.5, abs(zone_mid - sl))
        return FractalExecutionBlueprint(
            symbol=clean_sym,
            direction=direction.upper(),
            is_confirmed=False,
            entry_type="UNCONFIRMED_STALK",
            entry_price=zone_mid,
            stop_loss=sl,
            target_1=zone_mid + 2.0 * abs(zone_mid - sl)
            if is_bullish
            else zone_mid - 2.0 * abs(zone_mid - sl),
            target_2=zone_mid + 4.0 * abs(zone_mid - sl)
            if is_bullish
            else zone_mid - 4.0 * abs(zone_mid - sl),
            target_runner=htf_target,
            risk_reward_ratio=rr,
            micro_risk_pts=abs(zone_mid - sl),
            macro_reward_pts=abs(htf_target - zone_mid),
            has_micro_sweep=False,
            has_micro_choch=False,
            summary="LTF data unavailable; fallback to HTF Zone boundary stalk.",
        )

    cols = {c.lower(): c for c in df_ltf.columns}
    h_col = cols.get("high", "high")
    l_col = cols.get("low", "low")
    c_col = cols.get("close", "close")
    o_col = cols.get("open", "open")
    v_col = cols.get("volume", "volume")

    # Compute LTF ATR
    if atr_ltf is None or atr_ltf <= 0:
        try:
            atr_s = atr(df_ltf, period=14)
            atr_ltf = float(atr_s.dropna().iloc[-1])
        except Exception:
            atr_ltf = max(0.5, ltp * 0.003)  # 0.3% fallback
    atr_ltf = max(0.5, atr_ltf)

    # 1. Evaluate Recent Bars (Last 5 bars) for Micro-Sweep and Micro-CHoCH
    recent_bars = df_ltf.tail(5)
    has_micro_sweep = False
    micro_sweep_level: Optional[float] = None
    has_micro_choch = False
    displacement_bar_range = 0.0
    impulse_high = ltp
    impulse_low = ltp

    # Micro Sweep Detection (SFP Wick) across recent bars
    for i in range(len(recent_bars) - 1):
        bar = recent_bars.iloc[i]
        b_h = float(bar[h_col])
        b_l = float(bar[l_col])
        b_c = float(bar[c_col])
        b_o = float(bar[o_col]) if o_col in bar else b_c
        b_range = max(0.001, b_h - b_l)
        lower_wick = min(b_o, b_c) - b_l
        upper_wick = b_h - max(b_o, b_c)

        if is_bullish:
            # Swept below zone_bottom (or within 0.1% buffer) and closed back above with rejection wick
            if b_l <= zone_bottom * 1.001 and lower_wick >= 0.28 * b_range:
                has_micro_sweep = True
                if micro_sweep_level is None or b_l < micro_sweep_level:
                    micro_sweep_level = b_l
        else:
            # Swept above zone_top (or within 0.1% buffer) and closed back below with rejection wick
            if b_h >= zone_top * 0.999 and upper_wick >= 0.28 * b_range:
                has_micro_sweep = True
                if micro_sweep_level is None or b_h > micro_sweep_level:
                    micro_sweep_level = b_h

    # Micro-CHoCH Detection on last 2 bars
    last_bar = recent_bars.iloc[-1]
    prev_bar = recent_bars.iloc[-2]

    last_c = float(last_bar[c_col])
    last_o = float(last_bar[o_col]) if o_col in last_bar else last_c
    last_h = float(last_bar[h_col])
    last_l = float(last_bar[l_col])
    last_body = abs(last_c - last_o)
    last_range = max(0.001, last_h - last_l)

    prev_h = float(prev_bar[h_col])
    prev_l = float(prev_bar[l_col])

    # Volume check on last bar (compared to prior baseline excluding current bar)
    v_series = (
        df_ltf[v_col].astype(float)
        if v_col in df_ltf.columns
        else pd.Series(1000.0, index=df_ltf.index)
    )
    prior_v = v_series.iloc[:-1] if len(v_series) > 1 else v_series
    avg_vol = (
        float(prior_v.rolling(20, min_periods=2).mean().iloc[-1])
        if len(prior_v) >= 2
        else float(prior_v.mean())
    )
    last_vol = float(v_series.iloc[-1])
    rvol = last_vol / max(1.0, avg_vol)

    if is_bullish:
        # Bullish displacement: Bull bar closing above prior bar high with strong body
        if last_c > last_o and (last_body / last_range) >= 0.50 and last_c >= prev_h:
            has_micro_choch = True
            displacement_bar_range = last_range
            impulse_low = min(last_l, prev_l)
            impulse_high = last_h
    else:
        # Bearish displacement: Bear bar closing below prior bar low with strong body
        if last_c < last_o and (last_body / last_range) >= 0.50 and last_c <= prev_l:
            has_micro_choch = True
            displacement_bar_range = last_range
            impulse_high = max(last_h, prev_h)
            impulse_low = last_l

    # If micro sweep was not explicitly found in prior 5 bars, use lowest low / highest high of recent cluster
    if micro_sweep_level is None:
        micro_sweep_level = (
            float(recent_bars[l_col].min()) if is_bullish else float(recent_bars[h_col].max())
        )

    # 2. Formulate Entry Type & Execution Levels
    # Stop Loss calculation: 1 tick + buffer beyond the micro-sweep extreme
    sl_buffer = 0.15 * atr_ltf
    if is_bullish:
        stop_loss = micro_sweep_level - sl_buffer
    else:
        stop_loss = micro_sweep_level + sl_buffer

    # Dynamic Hybrid Entry Formulation
    is_confirmed = has_micro_choch or has_micro_sweep
    if is_bullish:
        if rvol >= 2.0 and (last_body / last_range) >= 0.65:
            # Fast Impulse Mode: Consequent Encroachment (50% of displacement bar)
            entry_type = "LIMIT_FVG_50"
            entry_price = last_l + 0.50 * last_range
        else:
            # Retest OTE Mode: 61.8% Retracement of micro-impulse leg
            entry_type = "LIMIT_OTE"
            impulse_span = max(0.5, impulse_high - impulse_low)
            entry_price = impulse_high - (0.618 * impulse_span)
    else:
        if rvol >= 2.0 and (last_body / last_range) >= 0.65:
            entry_type = "LIMIT_FVG_50"
            entry_price = last_h - 0.50 * last_range
        else:
            entry_type = "LIMIT_OTE"
            impulse_span = max(0.5, impulse_high - impulse_low)
            entry_price = impulse_low + (0.618 * impulse_span)

    # Sanity bounds: entry must be between stop_loss and current ltp / target
    if is_bullish and entry_price <= stop_loss:
        entry_price = stop_loss + (0.5 * atr_ltf)
    elif not is_bullish and entry_price >= stop_loss:
        entry_price = stop_loss - (0.5 * atr_ltf)

    micro_risk_pts = max(0.5, abs(entry_price - stop_loss))
    macro_reward_pts = max(1.0, abs(htf_target - entry_price))
    rr = macro_reward_pts / micro_risk_pts

    # 3-Tier Multi-Horizon Scale Blueprint
    if is_bullish:
        target_1 = entry_price + (2.0 * micro_risk_pts)
        target_2 = entry_price + (4.0 * micro_risk_pts)
    else:
        target_1 = entry_price - (2.0 * micro_risk_pts)
        target_2 = entry_price - (4.0 * micro_risk_pts)

    scale_out_plan = {
        "Target_1 (+2.0R)": f"₹{target_1:.2f} (Scale 50% & Move Stop-Loss to Breakeven ₹{entry_price:.2f})",
        "Target_2 (+4.0R)": f"₹{target_2:.2f} (Scale 30% & Trail SL behind 15m structural pivot)",
        "Target_Runner": f"₹{htf_target:.2f} (Trail remaining 20% to HTF liquidity target)",
    }

    summary = (
        f"Fractal Inception {direction.upper()} [{entry_type}]: Entry ₹{entry_price:.2f}, "
        f"SL ₹{stop_loss:.2f} (Risk: {micro_risk_pts:.1f} pts), Target ₹{htf_target:.2f} "
        f"(Reward: {macro_reward_pts:.1f} pts, R:R = {rr:.2f}:1). "
        f"Sweep: {has_micro_sweep}, mCHoCH: {has_micro_choch}."
    )

    return FractalExecutionBlueprint(
        symbol=clean_sym,
        direction=direction.upper(),
        is_confirmed=is_confirmed,
        entry_type=entry_type,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        target_runner=htf_target,
        risk_reward_ratio=rr,
        micro_risk_pts=micro_risk_pts,
        macro_reward_pts=macro_reward_pts,
        has_micro_sweep=has_micro_sweep,
        has_micro_choch=has_micro_choch,
        micro_sweep_level=micro_sweep_level,
        displacement_bar_range=displacement_bar_range,
        scale_out_plan=scale_out_plan,
        summary=summary,
    )
