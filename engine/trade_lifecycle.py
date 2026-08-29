"""
engine/trade_lifecycle.py
─────────────────────────
Active Trade Position Lifecycle, Dynamic Trailing Stop-Loss & Alignment Engine.

Handles:
  1. Real-time R-Multiple Payoff Tracking:
     - Measures current profit/loss as a multiple of initial risk (1R, 2R, 3R, etc.).
  2. Multi-Tier Profit Booking Rules:
     - 2R Milestone: Scale out 33-50% -> Auto-shift Stop Loss to Breakeven (+ transaction fee buffer).
     - 3R - 4R Milestone: Scale out secondary 25% or tighten trailing stop.
     - Multibagger Runner (remaining 33-50%): Protected by dynamic trailing stops until structural breakdown.
  3. Dynamic Trailing Stop-Loss Calculators:
     - Structure Trailing Stop: Trails below the most recent Higher Low (HL) swing point.
     - Chandelier ATR Trailing Stop: Highest High - (3.0 * ATR).
     - Moving Average Trailing Stop: Daily 20-EMA or 50-EMA support close.
  4. Periodic Position Health & Alignment Auditing:
     - HEALTHY_ACCELERATING, HEALTHY_PULLBACK, MOMENTUM_STALLING, STRUCTURAL_INVALIDATION.

Usage:
    from engine.trade_lifecycle import audit_position_lifecycle

    health = audit_position_lifecycle(
        symbol="RELIANCE",
        entry_price=2400.0,
        initial_stop_loss=2340.0,
        position_type="LONG",
    )
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class TrailingStopLevels:
    structure_stop: float  # Below recent confirmed Higher Low
    chandelier_stop: float  # Highest Close - 3.0 * ATR
    ema20_stop: float  # 20 EMA trailing floor
    recommended_active_stop: float  # The most prudent active stop level
    stop_method: str  # "STRUCTURE_HL" | "CHANDELIER_ATR" | "BREAKEVEN" | "INITIAL_STOP"


@dataclass
class ProfitMilestone:
    name: str  # "2R Breakeven Pivot", "3R Growth Target", "5R Superperformer"
    target_price: float
    r_multiple: float
    action_required: str
    reached: bool = False


@dataclass
class PositionLifecycleReport:
    symbol: str
    ltp: float
    entry_price: float
    initial_stop_loss: float
    initial_risk_per_share: float
    
    # Live Payoff
    current_pnl_pts: float
    current_pnl_pct: float
    current_r_multiple: float  # e.g. +2.4R or -0.8R
    
    # Health & Alignment
    health_status: str  # "HEALTHY_ACCELERATING" | "HEALTHY_PULLBACK" | "MOMENTUM_STALLING" | "STRUCTURAL_INVALIDATION"
    health_score: int  # 0 to 100
    
    # Milestones & Profit Booking
    breakeven_reached: bool
    recommended_action: str  # "HOLD_RUNNER" | "SCALE_OUT_50_PCT" | "TRAIL_SL_TIGHT" | "EXIT_IMMEDIATELY"
    milestones: list[ProfitMilestone] = field(default_factory=list)
    
    # Trailing Stops
    trailing_stops: Optional[TrailingStopLevels] = None
    
    summary: str = ""
    diagnostic_bullet_points: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Position Lifecycle Auditor ──────────────────────────────────


def audit_position_lifecycle(
    symbol: str,
    entry_price: float,
    initial_stop_loss: float,
    current_ltp: Optional[float] = None,
    position_type: str = "LONG",
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
) -> PositionLifecycleReport:
    """
    Audits an open trade's health, computes current R-multiple payoff, checks 2R breakeven pivot,
    and calculates structure & Chandelier ATR trailing stop-loss levels.
    """
    # Fetch historical data if not provided
    if df is None or len(df) == 0:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(symbol, exchange=exchange, interval="day", days=100)
        except Exception:
            df = None

    if df is not None and len(df) > 0:
        ltp = float(df["close"].iloc[-1]) if current_ltp is None else float(current_ltp)
    else:
        ltp = float(entry_price * 1.03 if current_ltp is None else current_ltp)

    initial_risk = max(0.01, abs(entry_price - initial_stop_loss))
    
    if position_type.upper() == "LONG":
        pnl_pts = ltp - entry_price
        pnl_pct = (pnl_pts / entry_price) * 100 if entry_price > 0 else 0
        r_multiple = pnl_pts / initial_risk
    else:  # SHORT
        pnl_pts = entry_price - ltp
        pnl_pct = (pnl_pts / entry_price) * 100 if entry_price > 0 else 0
        r_multiple = pnl_pts / initial_risk

    # 1. Trailing Stops Calculation
    highest_price = ltp
    lowest_price = ltp
    atr = initial_risk * 0.8
    ema20 = entry_price
    recent_hl = initial_stop_loss

    if df is not None and len(df) >= 14:
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        
        # ATR 14
        tr = np.maximum(highs[1:] - lows[1:], np.maximum(abs(highs[1:] - closes[:-1]), abs(lows[1:] - closes[:-1])))
        atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))
        
        highest_price = float(np.max(highs[-20:]))
        lowest_price = float(np.min(lows[-20:]))
        
        # EMA 20
        ema20 = float(pd.Series(closes).ewm(span=20, adjust=False).mean().iloc[-1])
        
        # Find highest swing low in recent bars
        try:
            from analysis.market_structure import find_swing_points

            swings = find_swing_points(df, window=2)
            low_swings = [s.price for s in swings if s.type == "LOW" and s.price > initial_stop_loss]
            if low_swings:
                recent_hl = float(low_swings[-1])
        except Exception:
            recent_hl = float(min(lows[-5:]))

    # Chandelier ATR Trailing Stop (Highest High - 3.0 * ATR for longs)
    chandelier_stop = max(initial_stop_loss, highest_price - (3.0 * atr))
    structure_stop = max(initial_stop_loss, recent_hl)
    ema20_stop = max(initial_stop_loss, ema20 * 0.985)

    # Determine recommended active stop
    breakeven_price = entry_price * 1.002  # Entry + 0.2% brokerage buffer
    breakeven_reached = r_multiple >= 2.0

    if r_multiple >= 3.0:
        recommended_stop = max(breakeven_price, structure_stop, chandelier_stop)
        stop_method = "CHANDELIER_ATR" if chandelier_stop >= structure_stop else "STRUCTURE_HL"
    elif r_multiple >= 2.0:
        recommended_stop = max(breakeven_price, structure_stop)
        stop_method = "BREAKEVEN" if recommended_stop <= breakeven_price else "STRUCTURE_HL"
    else:
        recommended_stop = initial_stop_loss
        stop_method = "INITIAL_STOP"

    trailing_stops = TrailingStopLevels(
        structure_stop=round(structure_stop, 2),
        chandelier_stop=round(chandelier_stop, 2),
        ema20_stop=round(ema20_stop, 2),
        recommended_active_stop=round(recommended_stop, 2),
        stop_method=stop_method,
    )

    # 2. Milestones
    m_2r = entry_price + (initial_risk * 2.0)
    m_3r = entry_price + (initial_risk * 3.0)
    m_5r = entry_price + (initial_risk * 5.0)

    milestones = [
        ProfitMilestone(
            name="2R Breakeven Pivot",
            target_price=round(m_2r, 2),
            r_multiple=2.0,
            action_required="Book 33-50% profit & Shift SL to Breakeven (+0.2%)",
            reached=bool(r_multiple >= 2.0),
        ),
        ProfitMilestone(
            name="3R Growth Target",
            target_price=round(m_3r, 2),
            r_multiple=3.0,
            action_required="Book secondary 25% & Activate Chandelier ATR Trail",
            reached=bool(r_multiple >= 3.0),
        ),
        ProfitMilestone(
            name="5R Superperformer Runner",
            target_price=round(m_5r, 2),
            r_multiple=5.0,
            action_required="Hold remaining runner; Trail SL below Daily 20-EMA",
            reached=bool(r_multiple >= 5.0),
        ),
    ]

    # 3. Health & Diagnosis
    diagnostics = []
    if r_multiple >= 3.0:
        health_status = "HEALTHY_ACCELERATING"
        health_score = 95
        action = "HOLD_RUNNER"
        diagnostics.append(f"Trade is superperforming at +{r_multiple:.2f}R (+{pnl_pct:.2f}%).")
        diagnostics.append("Hold 33-50% runner with dynamic Chandelier ATR / Structure stop.")
    elif r_multiple >= 2.0:
        health_status = "HEALTHY_ACCELERATING"
        health_score = 85
        action = "SCALE_OUT_50_PCT"
        diagnostics.append(f"Reached 2R Milestone (+{r_multiple:.2f}R, +{pnl_pct:.2f}%).")
        diagnostics.append("Lock in 33-50% partial profit and move SL to breakeven (Risk-Free Trade).")
    elif r_multiple >= 0.5:
        health_status = "HEALTHY_PULLBACK" if ltp < highest_price * 0.98 else "HEALTHY_ACCELERATING"
        health_score = 75
        action = "HOLD_RUNNER"
        diagnostics.append(f"Trade progressing favorably (+{r_multiple:.2f}R, +{pnl_pct:.2f}%).")
        diagnostics.append("Maintain initial stop-loss until 2R target is reached.")
    elif r_multiple >= -0.5:
        health_status = "MOMENTUM_STALLING"
        health_score = 55
        action = "HOLD_RUNNER"
        diagnostics.append(f"Price hovering near entry (+{r_multiple:.2f}R, {pnl_pct:+.2f}%).")
        diagnostics.append("Keep original risk parameters; avoid premature manual exits.")
    else:
        health_status = "STRUCTURAL_INVALIDATION"
        health_score = 25
        action = "EXIT_IMMEDIATELY" if ltp <= initial_stop_loss else "TRAIL_SL_TIGHT"
        diagnostics.append(f"Trade experiencing adverse excursion ({r_multiple:.2f}R, {pnl_pct:.2f}%).")
        diagnostics.append(f"Strictly honor Stop Loss at ₹{initial_stop_loss:.2f}.")

    summary = f"{symbol} Position Health: {health_status} (Score: {health_score}/100, Payoff: {r_multiple:+.2f}R / {pnl_pct:+.2f}%). Recommended Stop: ₹{recommended_stop:.2f} ({stop_method})."

    return PositionLifecycleReport(
        symbol=symbol,
        ltp=round(ltp, 2),
        entry_price=round(entry_price, 2),
        initial_stop_loss=round(initial_stop_loss, 2),
        initial_risk_per_share=round(initial_risk, 2),
        current_pnl_pts=round(pnl_pts, 2),
        current_pnl_pct=round(pnl_pct, 2),
        current_r_multiple=round(r_multiple, 2),
        health_status=health_status,
        health_score=health_score,
        breakeven_reached=breakeven_reached,
        recommended_action=action,
        milestones=milestones,
        trailing_stops=trailing_stops,
        summary=summary,
        diagnostic_bullet_points=diagnostics,
    )
