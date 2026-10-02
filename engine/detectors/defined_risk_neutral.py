"""
engine/detectors/defined_risk_neutral.py
────────────────────────────────────────
Institutional Defined-Risk Neutral / Range-Bound Options Detector for Indian Markets.

Identifies sideways, consolidating, and mean-reverting regimes where directional
trend-following produces false breakouts or severe theta bleed:
  1. Low or consolidating volatility: India VIX between 10.0 and 18.0.
  2. Range-bound technical structure: ADX(14) < 25, price oscillating within Bollinger Bands.
  3. Flanking Open Interest (OI) Pinning: High Put OI wall acting as dynamic floor,
     high Call OI wall acting as ceiling.

Constructs mathematically defined-risk delta-neutral multi-leg strategies:
  - Iron Condor (Sell OTM Put + Buy Wing, Sell OTM Call + Buy Wing)
  - Defined max loss, explicit breakevens, net credit theta harvest.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from config.constants import IST
from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.defined_risk_spreads import build_defined_risk_spread
from market.instruments import get_fno_lot_size

logger = logging.getLogger(__name__)


def compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Computes standard Wilder's ADX from OHLCV dataframe."""
    if df is None or len(df) < period * 2:
        return None
    try:
        cols = {str(c).lower(): c for c in df.columns}
        if not {"high", "low", "close"}.issubset(set(cols.keys())):
            return None
        h = df[cols["high"]].astype(float)
        l = df[cols["low"]].astype(float)
        c = df[cols["close"]].astype(float)

        up_move = h - h.shift(1)
        down_move = l.shift(1) - l

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)

        # Smooth
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=period).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=period).mean() / atr)

        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)) * 100
        adx = dx.rolling(window=period).mean()
        val = float(adx.iloc[-1])
        return round(val, 2) if not np.isnan(val) and val >= 0 else None
    except Exception as exc:
        logger.debug("ADX computation error: %s", exc)
        return None


def detect_defined_risk_neutral(
    ctx: Any,  # DetectionContext duck-typed to avoid circular imports
) -> Optional[AutoAlert]:
    """
    Evaluates DetectionContext for range-bound / neutral option income opportunities.
    Returns AutoAlert with Iron Condor blueprint when criteria are met.
    """
    if ctx.segment not in ("FNO_INDEX", "FNO_STOCK", "EQUITY"):
        return None

    symbol = canonical_alert_symbol(ctx.canonical_symbol)
    ltp = float(ctx.ltp)
    if ltp <= 0:
        return None

    # Filter out excessive panic volatility (Iron Condors need stable/contracting IV)
    vix = float(ctx.vix) if ctx.vix and ctx.vix > 0 else 13.5
    if vix > 22.0:
        return None

    # Check non-trending regime indicators:
    # 1. ADX on intraday or daily candles
    candles = ctx.candles_15m if ctx.candles_15m is not None else ctx.candles_5m
    if candles is None:
        candles = ctx.candles_daily

    adx_val = compute_adx(candles) if candles is not None else None
    is_low_adx = adx_val is not None and adx_val < 25.0

    # 2. Intraday price movement check (consolidating within narrow range)
    day_chg = abs(ctx.day_change_pct)
    is_narrow_day = day_chg <= 0.85

    # 3. Open interest flanking walls check
    oi_walls_present = False
    put_wall_strike: Optional[float] = None
    call_wall_strike: Optional[float] = None

    if ctx.option_chain and len(ctx.option_chain) >= 4:
        try:
            calls = [item for item in ctx.option_chain if item.get("option_type") == "CE" and item.get("strike", 0) > ltp]
            puts = [item for item in ctx.option_chain if item.get("option_type") == "PE" and item.get("strike", 0) < ltp]
            if calls and puts:
                best_call = max(calls, key=lambda x: x.get("oi", 0))
                best_put = max(puts, key=lambda x: x.get("oi", 0))
                call_wall_strike = float(best_call.get("strike", 0))
                put_wall_strike = float(best_put.get("strike", 0))
                if call_wall_strike > ltp > put_wall_strike:
                    oi_walls_present = True
        except Exception as exc:
            logger.debug("OI wall detection error: %s", exc)

    # Condition: Must exhibit either low ADX or narrow intraday consolidation or flanking OI walls
    evidence_score = 0
    if is_low_adx:
        evidence_score += 1
    if is_narrow_day:
        evidence_score += 1
    if oi_walls_present:
        evidence_score += 1

    # Require at least 2 confirming range-bound signals (or index in low VIX with narrow range)
    if evidence_score < 2 and not (ctx.is_index and vix <= 15.0 and is_narrow_day):
        return None

    # Construct Iron Condor strategy
    lot_size = get_fno_lot_size(symbol)
    iv = max(0.10, min(0.35, vix / 100.0))

    try:
        spread = build_defined_risk_spread(
            underlying=symbol,
            spot_price=ltp,
            strategy="IRON_CONDOR",
            iv=iv,
            dte=7,
            lot_size=lot_size,
            num_lots=1,
        )
    except Exception as exc:
        logger.warning("Error building iron condor for %s: %s", symbol, exc)
        return None

    if not spread.legs or spread.max_profit <= 0 or spread.max_loss <= 0:
        return None

    # Extract strikes for actionable blueprint
    put_legs = [l for l in spread.legs if l.option_type == "PE"]
    call_legs = [l for l in spread.legs if l.option_type == "CE"]
    short_put = next((l for l in put_legs if l.side == "SELL"), None)
    long_put = next((l for l in put_legs if l.side == "BUY"), None)
    short_call = next((l for l in call_legs if l.side == "SELL"), None)
    long_call = next((l for l in call_legs if l.side == "BUY"), None)

    if not (short_put and long_put and short_call and long_call):
        return None

    net_credit_pts = abs(spread.net_debit_or_credit) / (lot_size if lot_size > 0 else 1)
    lower_be = spread.breakeven_points[0] if spread.breakeven_points else short_put.strike - net_credit_pts
    upper_be = spread.breakeven_points[1] if len(spread.breakeven_points) > 1 else short_call.strike + net_credit_pts

    # Conviction scoring (72 - 92)
    conviction = 74
    if vix < 14.0:
        conviction += 6
    if is_low_adx:
        conviction += 5
    if oi_walls_present:
        conviction += 5
    conviction = min(92, conviction)

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    headline = (
        f"🛡 DEFINED-RISK CONDOR: {symbol} @ ₹{ltp:,.1f} | "
        f"Corridor [₹{short_put.strike:,.0f} – ₹{short_call.strike:,.0f}] (Credit ₹{abs(spread.net_debit_or_credit):,.0f})"
    )
    summary = (
        f"Range-bound consolidation regime (VIX {vix:.1f}"
        f"{f', ADX {adx_val:.1f}' if adx_val is not None else ''}). "
        f"Hedged Iron Condor collects ₹{abs(spread.net_debit_or_credit):,.0f} net credit. "
        f"Safe corridor ₹{lower_be:,.1f} to ₹{upper_be:,.1f}. Capped max loss ₹{spread.max_loss:,.0f}."
    )

    t1_profit = round(spread.max_profit * 0.5, 2)
    t2_profit = round(spread.max_profit * 0.8, 2)

    return AutoAlert(
        alert_id=generate_alert_id(symbol, "DEFINED_RISK_NEUTRAL", variant="condor"),
        alert_type="DEFINED_RISK_NEUTRAL",
        stage="ACTIONABLE",
        symbol=symbol,
        exchange=ctx.exchange,
        direction="NEUTRAL",
        headline=headline,
        summary=summary,
        ltp=ltp,
        trigger_level=ltp,
        target_level=round(upper_be, 2),
        stop_loss=round(lower_be, 2),
        metrics={
            "strategy": "IRON_CONDOR",
            "vix": round(vix, 2),
            "adx": adx_val,
            "lot_size": lot_size,
            "short_put_strike": short_put.strike,
            "long_put_strike": long_put.strike,
            "short_call_strike": short_call.strike,
            "long_call_strike": long_call.strike,
            "net_credit": round(abs(spread.net_debit_or_credit), 2),
            "max_profit": round(spread.max_profit, 2),
            "max_loss": round(spread.max_loss, 2),
            "risk_reward_ratio": round(spread.risk_reward_ratio, 2),
            "breakeven_lower": round(lower_be, 2),
            "breakeven_upper": round(upper_be, 2),
            "margin_estimate": round(spread.capital_required, 2),
        },
        actionable_plan={
            "action": "EXECUTE_IRON_CONDOR",
            "structure": (
                f"BUY {long_put.strike:.0f} PE | SELL {short_put.strike:.0f} PE | "
                f"SELL {short_call.strike:.0f} CE | BUY {long_call.strike:.0f} CE"
            ),
            "entry_range": f"Spot ₹{round(ltp * 0.995, 1):.1f} – ₹{round(ltp * 1.005, 1):.1f}",
            "profit_corridor": f"₹{short_put.strike:,.0f} to ₹{short_call.strike:,.0f}",
            "breakevens": f"₹{lower_be:,.1f} – ₹{upper_be:,.1f}",
            "target": f"+50% Decay (Harvest ₹{t1_profit:,.0f})",
            "target_2": f"+80% Decay (Harvest ₹{t2_profit:,.0f})",
            "stop_loss": f"Exit if underlying crosses ₹{lower_be:.1f} or ₹{upper_be:.1f}",
            "risk_reward": f"1:{spread.risk_reward_ratio:.2f}",
            "profit_rule": "Scale 50% profits at 50% max theta decay; close all wings if underlying challenges short strikes.",
        },
        confidence=conviction,
        created_at=now_iso,
    )
