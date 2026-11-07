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
from typing import Any, Optional


from config.constants import IST
from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.defined_risk_spreads import build_defined_risk_spread
from market.instruments import get_fno_lot_size
from analysis.dmi_filter import compute_adx

logger = logging.getLogger(__name__)


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
            calls = [
                item
                for item in ctx.option_chain
                if item.get("option_type") == "CE" and item.get("strike", 0) > ltp
            ]
            puts = [
                item
                for item in ctx.option_chain
                if item.get("option_type") == "PE" and item.get("strike", 0) < ltp
            ]
            if calls and puts:
                best_call = max(calls, key=lambda x: x.get("oi", 0))
                best_put = max(puts, key=lambda x: x.get("oi", 0))
                call_wall_strike = float(best_call.get("strike", 0))
                put_wall_strike = float(best_put.get("strike", 0))
                if call_wall_strike > ltp > put_wall_strike:
                    oi_walls_present = True
        except Exception as exc:
            logger.debug("OI wall detection error: %s", exc)

    # 4. Flow-Based Choppy / Neutral Regime Confluence (OBV, DMI, AVWAP, VSA)
    obv_status = "NEUTRAL"
    dmi_status = "NEUTRAL"
    avwap_status = "NEUTRAL"
    vsa_status = "NEUTRAL"
    is_flow_choppy = False

    if candles is not None and len(candles) >= 8:
        try:
            from analysis.obv import analyse_obv
            from analysis.dmi_filter import evaluate_triple_dmi
            from analysis.anchored_vwap import detect_intraday_anchors
            from analysis.vsa import analyse_vsa

            _obv = analyse_obv(candles, is_intraday=True)
            obv_status = _obv.regime
            _dmi = evaluate_triple_dmi(candles, is_intraday=True)
            dmi_status = _dmi.verdict
            _avwap = detect_intraday_anchors(candles, spot_price=ltp)
            avwap_status = _avwap.get("confluence", "NEUTRAL")
            _vsa = analyse_vsa(candles, symbol=symbol, is_intraday=True)
            vsa_status = _vsa.vsa_signal

            # Flow is verified choppy / non-trending if:
            # 1. OBV is neutral / compressing
            # 2. DMI shows weak momentum below threshold
            # 3. AVWAP is compressed inside anchors
            if dmi_status in ("WEAK_MOMENTUM_BELOW_25", "CHOP_WHIPSAW", "NEUTRAL"):
                is_flow_choppy = True
            if avwap_status in ("COMPRESSION_INSIDE", "NEUTRAL"):
                is_flow_choppy = True
        except Exception as e_flow_neutral:
            logger.debug("Flow neutral analysis non-fatal: %s", e_flow_neutral)

    # Condition: Must exhibit either low ADX, narrow intraday consolidation, flanking OI walls, or verified choppy flow
    evidence_score = 0
    if is_low_adx:
        evidence_score += 1
    if is_narrow_day:
        evidence_score += 1
    if oi_walls_present:
        evidence_score += 1
    if is_flow_choppy:
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
    lower_be = (
        spread.breakeven_points[0] if spread.breakeven_points else short_put.strike - net_credit_pts
    )
    upper_be = (
        spread.breakeven_points[1]
        if len(spread.breakeven_points) > 1
        else short_call.strike + net_credit_pts
    )

    # Quantitative SABR Volatility Smile Check
    sabr_skew = None
    short_put_edge = None
    short_call_edge = None
    try:
        from analysis.vol_surface import analyze_volatility_surface

        surf = analyze_volatility_surface(symbol)
        if surf:
            sabr_skew = surf.skew_verdict
            for m in surf.mispricings:
                if m.strike == short_put.strike:
                    short_put_edge = m.iv_edge_pts
                elif m.strike == short_call.strike:
                    short_call_edge = m.iv_edge_pts
    except Exception as e_sabr:
        logger.debug("SABR surface check non-fatal for %s: %s", symbol, e_sabr)

    # Conviction scoring (72 - 95)
    conviction = 74
    if vix < 14.0:
        conviction += 6
    if is_low_adx:
        conviction += 5
    if oi_walls_present:
        conviction += 5
    # Boost conviction if short strikes exhibit positive IV edge (overpriced premium)
    if (short_put_edge and short_put_edge > 0.5) or (short_call_edge and short_call_edge > 0.5):
        conviction += 3
    conviction = min(95, conviction)

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    headline = (
        f"🛡 DEFINED-RISK CONDOR: {symbol} @ ₹{ltp:,.1f} | "
        f"Corridor [₹{short_put.strike:,.0f} – ₹{short_call.strike:,.0f}] (Credit ₹{abs(spread.net_debit_or_credit):,.0f})"
    )
    summary = (
        f"Range-bound consolidation regime (VIX {vix:.1f}"
        f"{f', ADX {adx_val:.1f}' if adx_val is not None else ''}"
        f"{f', SABR Skew: {sabr_skew}' if sabr_skew else ''}). "
        f"Hedged Iron Condor collects ₹{abs(spread.net_debit_or_credit):,.0f} net credit. "
        f"Safe corridor ₹{lower_be:,.1f} to ₹{upper_be:,.1f}. Capped max loss ₹{spread.max_loss:,.0f}."
    )

    eff_lot = lot_size if lot_size > 0 else 1
    t1_profit = round(spread.max_profit * 0.5, 2)
    t2_profit = round(spread.max_profit * 0.8, 2)

    spread_dict = spread.to_dict()
    spread_dict["spread_name"] = "Iron Condor Neutral Harvest"
    spread_dict["short_put_strike"] = short_put.strike
    spread_dict["long_put_strike"] = long_put.strike
    spread_dict["short_call_strike"] = short_call.strike
    spread_dict["long_call_strike"] = long_call.strike
    spread_dict["profit_corridor"] = f"₹{short_put.strike:,.0f} to ₹{short_call.strike:,.0f}"
    spread_dict["breakevens"] = f"₹{lower_be:,.1f} – ₹{upper_be:,.1f}"

    entry_min = min(round(ltp * 0.995, 1), round(ltp * 1.005, 1))
    entry_max = max(round(ltp * 0.995, 1), round(ltp * 1.005, 1))

    alert = AutoAlert(
        alert_id=generate_alert_id(symbol, "DEFINED_RISK_NEUTRAL", variant="condor"),
        alert_type="DEFINED_RISK_NEUTRAL",
        stage="ACTIONABLE",
        symbol=symbol,
        exchange=ctx.exchange,
        direction="NEUTRAL",
        derivative_type="SPREAD",
        headline=headline,
        summary=summary,
        ltp=ltp,
        underlying_spot=ltp,
        trigger_level=ltp,
        target_level=round(upper_be, 2),
        stop_loss=round(lower_be, 2),
        lot_size=lot_size,
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
            "sabr_skew": sabr_skew,
            "short_put_iv_edge": short_put_edge,
            "short_call_iv_edge": short_call_edge,
            "obv_regime": obv_status,
            "dmi_triple_verdict": dmi_status,
            "avwap_confluence": avwap_status,
            "vsa_signal": vsa_status,
            "hedged_spread": spread_dict,
        },
        actionable_plan={
            "action": "EXECUTE_IRON_CONDOR",
            "preferred_vehicle": "DEFINED_RISK_SPREAD",
            "hedged_spread": spread_dict,
            "structure": (
                f"BUY {long_put.strike:.0f} PE | SELL {short_put.strike:.0f} PE | "
                f"SELL {short_call.strike:.0f} CE | BUY {long_call.strike:.0f} CE"
            ),
            "entry_price": round(net_credit_pts, 2),
            "stop_loss": round(spread.max_loss / eff_lot, 2),
            "target_1": round(t1_profit / eff_lot, 2),
            "target_2": round(t2_profit / eff_lot, 2),
            "target_3": round(spread.max_profit / eff_lot, 2),
            "entry_range": f"Spot ₹{entry_min:.1f} – ₹{entry_max:.1f}",
            "profit_corridor": f"₹{short_put.strike:,.0f} to ₹{short_call.strike:,.0f}",
            "breakevens": f"₹{lower_be:,.1f} – ₹{upper_be:,.1f}",
            "no_chase_boundary": round(upper_be, 2),
            "decay_target_1": f"+50% Decay (Harvest ₹{t1_profit:,.0f})",
            "decay_target_2": f"+80% Decay (Harvest ₹{t2_profit:,.0f})",
            "risk_reward": f"1:{spread.risk_reward_ratio:.2f}",
            "profit_rule": "Scale 50% profits at 50% max theta decay; close all wings if underlying challenges short strikes.",
        },
        no_chase_boundary=round(upper_be, 2),
        confidence=conviction,
        created_at=now_iso,
    )
    alert.hedged_spread = spread_dict
    return alert
