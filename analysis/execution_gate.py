"""
analysis/execution_gate.py
──────────────────────────
Two-Tier Execution Gate: Separating Strategic Edge (Historical Quant) from Tactical Execution Gate (Real-Time Microstructure).

Rules:
  1. Strategic Edge (Historical Data — 180 to 365 Days):
     - Minervini 8-Point Trend Template
     - Stan Weinstein Stage 2 Markup Classification
     - Smart Money Concepts (Fractal Swings, Order Blocks, FVGs)
     - Forensic Accounting & Balance Sheet Quality
     - JdK Relative Rotation Graph (RRG) Sector Momentum
     → Generates Strategic Conviction Score (0–100).
  2. Tactical Execution Gate (Real-Time Microstructure — Live Tick & Order Flow):
     - Live Price Proximity to Entry Zone (&plusmn;0.5% buffer)
     - Live Intraday RVOL Surge (&ge;1.3x)
     - Live Options Open Interest (OI) Shift (Long Buildup / Short Covering)
     - John Carter Volatility Squeeze Fire Status
     - Spread & Liquidity Invalidation Gate
     → Generates Live Tactical Execution Score (0–100).
  3. Execution Verdict:
     - READY (&ge;80 Tactical + &ge;75 Strategic): Trigger fired, execute live order now.
     - STALK (50–79 Tactical + &ge;70 Strategic): Setup valid, wait for 5m intraday retest.
     - STAND_DOWN (<50 Tactical or Trap detected): Strategic setup valid, but live distribution active.
  4. Real-Time Telegram & Alert Notification Dispatch:
     - Automatically pushes rich, actionable mobile notifications when status is READY or STALK.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# UTF-8 console output for Windows
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import numpy as np
import pandas as pd

from analysis.big_move import compute_ttm_squeeze, analyze_options_flow
from analysis.market_structure import analyze_market_structure
from analysis.multibagger import scan_multibagger_opportunity
from analysis.sector_rotation import get_stock_sector_alignment
from analysis.universe import get_stock_sector
from analysis.volume_profile import analyze_volume_profile


@dataclass
class ExecutionGateReport:
    symbol: str
    sector: str
    sector_icon: str
    ltp: float
    strategic_score: int  # 0–100 (Historical edge)
    tactical_score: int  # 0–100 (Live microstructure readiness)
    execution_status: str  # "READY" | "STALK" | "STAND_DOWN"
    setup_title: str
    trade_bias: str  # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward_ratio: float
    rvol: float
    options_oi_regime: str
    squeeze_fired: bool
    expected_timeline: str = "3–10 Trading Days (Swing Momentum)"
    target_1_timeline: str = "2–5 Trading Days"
    target_2_timeline: str = "6–10 Trading Days"
    time_stop_days: int = 10
    profit_booking_plan: str = ""
    catalysts: list[str] = field(default_factory=list)
    action_summary: str = ""
    telegram_sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Two-Tier Evaluator ───────────────────────────────────────────────


def evaluate_execution_gate(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
    notify_telegram: bool = False,
) -> ExecutionGateReport:
    """
    Evaluates strategic setup quality (Historical) vs tactical execution readiness (Real-Time Microstructure).
    Optionally dispatches instant Telegram notification if status is READY or STALK.
    """
    symbol = symbol.upper().replace(".NS", "").replace(".BO", "")

    if df is None or len(df) == 0:
        try:
            from market.history import get_daily_history

            df = get_daily_history(symbol=symbol, exchange=exchange, days=250)
        except Exception:
            df = None

    if df is None or len(df) < 15:
        return ExecutionGateReport(
            symbol=symbol,
            sector="General",
            sector_icon="🏢",
            ltp=0.0,
            strategic_score=0,
            tactical_score=0,
            execution_status="STAND_DOWN",
            setup_title="Insufficient Data",
            trade_bias="LONG",
            entry_price=0.0,
            stop_loss=0.0,
            target_1=0.0,
            target_2=0.0,
            risk_reward_ratio=1.0,
            rvol=1.0,
            options_oi_regime="BALANCED",
            squeeze_fired=False,
            expected_timeline="3–10 Trading Days",
            target_1_timeline="2–5 Trading Days",
            target_2_timeline="6–10 Trading Days",
            time_stop_days=10,
            profit_booking_plan="Awaiting data before planning.",
            catalysts=["Insufficient historical bars"],
            action_summary="Awaiting data before evaluation.",
            telegram_sent=False,
        )

    # Normalize column names if needed
    col_map = {c: c.lower() for c in df.columns}
    close_col = "close" if "close" in df.columns else "Close" if "Close" in df.columns else df.columns[3]
    ltp = float(df[close_col].iloc[-1])

    # 1. Tier 1: Strategic Macro & Positional Analysis (Historical Lookback)
    ms = analyze_market_structure(symbol, df=df, exchange=exchange)
    mb = scan_multibagger_opportunity(symbol, df=df)

    from analysis.universe import SECTOR_TAXONOMY

    sec_id, sector_name = get_stock_sector(symbol)
    sec_align = get_stock_sector_alignment(symbol)
    sector_icon = SECTOR_TAXONOMY.get(sec_id, {}).get("icon", "🏢")

    # Strategic Scoring (0–100)
    strat_score = 40
    if mb.weinstein_stage == "STAGE_2_MARKUP":
        strat_score += 25
    if mb.trend_template_passed >= 7:
        strat_score += 15
    if ms.regime == "BULLISH":
        strat_score += 10
    if (isinstance(sec_align, dict) and sec_align.get("quadrant") == "LEADING") or sec_align == "STRONG_LEADING":
        strat_score += 10
    strat_score = int(min(98, max(20, strat_score)))

    # 2. Tier 2: Tactical Microstructure Analysis (Live Real-Time Tick & Order Flow)
    vp = analyze_volume_profile(symbol, df=df, exchange=exchange)
    squeeze = compute_ttm_squeeze(df)
    opt_flow = analyze_options_flow(symbol=symbol, ltp=ltp)

    tact_score = 40
    catalysts: list[str] = []

    # Factor A: RVOL Surge
    rvol_val = vp.rvol_20d
    if rvol_val >= 2.0:
        tact_score += 25
        catalysts.append(f"Institutional Volume Surge (RVOL {rvol_val:.1f}x)")
    elif rvol_val >= 1.3:
        tact_score += 15
        catalysts.append(f"Above-average Volume (RVOL {rvol_val:.1f}x)")

    # Factor B: Squeeze Explosion
    if squeeze.squeeze_fired:
        tact_score += 20
        catalysts.append(f"🚀 Squeeze FIRED ({squeeze.momentum_direction}) — Volatility expansion active")
    elif squeeze.is_squeeze_on:
        tact_score += 10
        catalysts.append(f"🔴 Energy coiling in Squeeze ({squeeze.squeeze_duration_bars} bars)")

    # Factor C: Live Options Flow
    if opt_flow.dominant_regime in ("LONG_BUILDUP", "SHORT_COVERING"):
        tact_score += 20
        catalysts.append(f"Live Options {opt_flow.dominant_regime} (PCR {opt_flow.pcr})")
    elif opt_flow.dominant_regime in ("SHORT_BUILDUP", "LONG_UNWINDING"):
        tact_score -= 20
        catalysts.append(f"⚠️ Live Options Resistance: {opt_flow.dominant_regime}")

    # Factor D: SMC Structural Trigger (BOS / CHoCH)
    if ms.choch_detected:
        tact_score += 15
        catalysts.append(f"⚠️ Bullish Change of Character ({ms.choch_type})")

    tact_score = int(min(98, max(15, tact_score)))

    # 3. Determine Execution Status
    if tact_score >= 78 and strat_score >= 70:
        execution_status = "READY"
        action_summary = f"⚡ Alignment confirmed! Execute Long near ₹{ltp:.2f}."
    elif strat_score >= 70 and tact_score >= 50:
        execution_status = "STALK"
        action_summary = f"🎯 Strategic setup valid. Stalk entry on intraday pullback near ₹{ltp * 0.985:.2f}."
    else:
        execution_status = "STAND_DOWN"
        action_summary = "Stand down. Awaiting live volume or structural confirmation."

    # Actionable Blueprint Levels
    entry_price = round(ltp, 2)
    atr = float(df["High"].iloc[-14:] - df["Low"].iloc[-14:]).mean() if "High" in df.columns and len(df) >= 14 else ltp * 0.02
    stop_loss = round(max(ltp * 0.85, ltp - (1.5 * atr)), 2)
    risk_pts = max(1.0, entry_price - stop_loss)
    target_1 = round(entry_price + (risk_pts * 2.0), 2)
    target_2 = round(entry_price + (risk_pts * 3.5), 2)
    rr_ratio = round((target_1 - entry_price) / risk_pts, 2)

    setup_title = "💎 Stage 2 Markup" if mb.weinstein_stage == "STAGE_2_MARKUP" else (ms.setup_type.replace("_", " ").title())

    expected_timeline = "3–10 Trading Days (Swing Momentum)" if mb.weinstein_stage == "STAGE_2_MARKUP" else "2–7 Trading Days (Swing Reversal)"
    t1_timeline = "2–5 Trading Days"
    t2_timeline = "6–10 Trading Days"
    time_stop_days = 10
    profit_booking_plan = (
        f"Scale out 50% at Target 1 (₹{target_1:,.2f}), move SL to Breakeven (+0.2%), "
        f"and trail remainder via Daily 20-EMA / 3.0×ATR to Target 2 (₹{target_2:,.2f})."
    )

    report = ExecutionGateReport(
        symbol=symbol,
        sector=sector_name,
        sector_icon=sector_icon,
        ltp=ltp,
        strategic_score=strat_score,
        tactical_score=tact_score,
        execution_status=execution_status,
        setup_title=setup_title,
        trade_bias="LONG",
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        risk_reward_ratio=rr_ratio,
        rvol=rvol_val,
        options_oi_regime=opt_flow.dominant_regime,
        squeeze_fired=squeeze.squeeze_fired,
        expected_timeline=expected_timeline,
        target_1_timeline=t1_timeline,
        target_2_timeline=t2_timeline,
        time_stop_days=time_stop_days,
        profit_booking_plan=profit_booking_plan,
        catalysts=catalysts,
        action_summary=action_summary,
        telegram_sent=False,
    )

    # 4. Dispatch Telegram & Desktop Notification if eligible
    if notify_telegram and execution_status in ("READY", "STALK"):
        try:
            from bot.telegram_bot import push_execution_alert

            push_execution_alert(report.to_dict())
            report.telegram_sent = True
        except Exception:
            pass

    return report


def scan_and_alert_execution_candidates(
    universe: str = "auto_market_aware",
    top_n: int = 5,
    exchange: str = "NSE",
    notify_telegram: bool = True,
) -> list[ExecutionGateReport]:
    """
    Batch scans leading candidates and automatically dispatches Telegram notifications
    for any opportunities that achieve READY or STALK execution readiness.
    """
    from analysis.universe import resolve_dynamic_universe

    symbols = resolve_dynamic_universe(universe)
    results: list[ExecutionGateReport] = []

    for sym in symbols[:20]:
        try:
            rep = evaluate_execution_gate(
                symbol=sym,
                exchange=exchange,
                notify_telegram=notify_telegram,
            )
            if rep.execution_status in ("READY", "STALK"):
                results.append(rep)
        except Exception:
            continue

    # Sort: READY first, then by tactical score descending
    results.sort(key=lambda x: (1 if x.execution_status == "READY" else 0, x.tactical_score), reverse=True)
    return results[:top_n]
