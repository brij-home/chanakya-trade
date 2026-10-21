"""
engine/strategic_horizon.py
───────────────────────────
Autonomous Strategic Horizon & Predictive Quantitative Synthesis Engine.

Synthesizes live market coordinates, breadth, options walls, SMT inter-market
alignment, and order book pressure to produce forward-looking strategic scenarios
and actionable battleground maps before lagging retail indicators catch on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.strategic_horizon")
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class StrategicHorizonReport:
    symbol: str
    spot: float
    vwap: float
    day_high: float
    day_low: float
    regime_verdict: str
    bias_direction: str  # "BEARISH" | "BULLISH" | "NEUTRAL"
    conviction_score: int  # 0 to 100
    battleground_zone: str
    immediate_resistance: float
    pivot_equilibrium: float
    immediate_support: float
    invalidation_level: float
    market_breadth: dict[str, Any] = field(default_factory=dict)
    options_posture: dict[str, Any] = field(default_factory=dict)
    smt_alignment: dict[str, Any] = field(default_factory=dict)
    tactical_scenarios: dict[str, str] = field(default_factory=dict)
    actionable_coaching: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "vwap": self.vwap,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "regime_verdict": self.regime_verdict,
            "bias_direction": self.bias_direction,
            "conviction_score": self.conviction_score,
            "battleground_zone": self.battleground_zone,
            "immediate_resistance": self.immediate_resistance,
            "pivot_equilibrium": self.pivot_equilibrium,
            "immediate_support": self.immediate_support,
            "invalidation_level": self.invalidation_level,
            "market_breadth": self.market_breadth,
            "options_posture": self.options_posture,
            "smt_alignment": self.smt_alignment,
            "tactical_scenarios": self.tactical_scenarios,
            "actionable_coaching": self.actionable_coaching,
            "timestamp": self.timestamp,
        }


def generate_strategic_horizon(symbol: str = "NIFTY") -> StrategicHorizonReport:
    """
    Generates a full-spectrum forward-looking strategic horizon for the given index.
    """
    clean_sym = canonical_alert_symbol(symbol).upper()
    now_dt = datetime.now(IST)
    ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    from market.quotes import get_quote, get_ltp, get_computed_vwap
    from market.sentiment import get_market_breadth
    from market.options import get_options_chain
    from engine.daily_levels import get_daily_levels
    from engine.market_regime_gate import evaluate_market_regime
    from engine.smt_divergence import evaluate_smt_divergence

    exch = "BSE" if clean_sym in ("SENSEX", "BANKEX") else "NSE"
    lookup = f"{exch}:{clean_sym}"
    q = get_quote(lookup).get(lookup) or get_quote(clean_sym).get(clean_sym)

    spot = float(
        getattr(q, "last_price", 0.0) or getattr(q, "ltp", 0.0) or get_ltp(clean_sym) or 0.0
    )
    day_high = float(getattr(q, "high", 0.0) or spot)
    day_low = float(getattr(q, "low", 0.0) or spot)
    vwap_val = float(
        getattr(q, "vwap", 0.0)
        or getattr(q, "average_price", 0.0)
        or get_computed_vwap(clean_sym, exchange=exch)
        or spot
    )

    # 1. Market Breadth & Sentiment
    mb_dict: dict[str, Any] = {}
    ad_ratio = 1.0
    try:
        mb = get_market_breadth()
        if mb and mb.verdict != "UNAVAILABLE":
            ad_ratio = float(getattr(mb, "ad_ratio", 1.0) or 1.0)
            mb_dict = {
                "verdict": mb.verdict,
                "ad_ratio": round(ad_ratio, 2),
                "advances": getattr(mb, "advances", 0),
                "declines": getattr(mb, "declines", 0),
            }
    except Exception as e_mb:
        logger.debug(f"[StrategicHorizon] Breadth error: {e_mb}")

    # 2. Daily Levels & Pivots
    dl = get_daily_levels(clean_sym)
    cam = dl.camarilla if dl else {}
    h4 = float(cam.get("h4", 0.0) or day_high)
    l4 = float(cam.get("l4", 0.0) or day_low)

    # 3. Market Regime & Locomotive Polarization
    reg_verdict = "NORMAL_SESSION"
    is_loco = False
    loco_detail = ""
    try:
        reg = evaluate_market_regime()
        if reg:
            is_loco = bool(getattr(reg, "is_locomotive_polarized", False))
            loco_detail = str(getattr(reg, "locomotive_detail", "") or "")
            if is_loco:
                reg_verdict = "LOCOMOTIVE_POLARIZATION_TRAP"
            elif reg.is_edgeless:
                reg_verdict = "EDGELESS_CHOP_CONSOLIDATION"
            elif ad_ratio <= 0.40:
                reg_verdict = "BROAD_MARKET_LIQUIDATION"
            elif ad_ratio >= 2.0:
                reg_verdict = "BROAD_MARKET_EXPANSION"
    except Exception as e_rg:
        logger.debug(f"[StrategicHorizon] Regime error: {e_rg}")

    # 4. SMT Inter-Market Alignment
    smt_info: dict[str, Any] = {}
    try:
        smt_res = evaluate_smt_divergence(
            clean_sym,
            "BULLISH" if spot < vwap_val else "BEARISH",
            spot,
            primary_day_high=day_high,
            primary_day_low=day_low,
            primary_vwap=vwap_val,
        )
        smt_info = {
            "has_divergence": smt_res.has_divergence,
            "divergence_type": smt_res.divergence_type,
            "sibling_symbol": smt_res.sibling_symbol,
            "sibling_spot": smt_res.sibling_spot,
            "sibling_vwap": smt_res.sibling_vwap,
            "is_trap": smt_res.is_trap,
            "rationale": smt_res.rationale,
        }
    except Exception as e_smt:
        logger.debug(f"[StrategicHorizon] SMT error: {e_smt}")

    # 5. Options Posture & Strike Walls
    opt_info: dict[str, Any] = {}
    call_wall = day_high
    put_wall = day_low
    chain_pcr = 1.0
    try:
        chain = get_options_chain(clean_sym)
        if chain:
            ce_cands = [
                c
                for c in chain
                if getattr(c, "option_type", "") == "CE" and int(getattr(c, "oi", 0) or 0) > 0
            ]
            pe_cands = [
                c
                for c in chain
                if getattr(c, "option_type", "") == "PE" and int(getattr(c, "oi", 0) or 0) > 0
            ]
            if ce_cands:
                max_ce = max(ce_cands, key=lambda c: int(getattr(c, "oi", 0) or 0))
                call_wall = float(getattr(max_ce, "strike", 0.0) or day_high)
            if pe_cands:
                max_pe = max(pe_cands, key=lambda c: int(getattr(c, "oi", 0) or 0))
                put_wall = float(getattr(max_pe, "strike", 0.0) or day_low)
            tot_ce_oi = sum(int(getattr(c, "oi", 0) or 0) for c in ce_cands)
            tot_pe_oi = sum(int(getattr(c, "oi", 0) or 0) for c in pe_cands)
            chain_pcr = round(tot_pe_oi / max(1, tot_ce_oi), 2)
            opt_info = {
                "call_wall": call_wall,
                "put_wall": put_wall,
                "pcr": chain_pcr,
                "total_contracts": len(chain),
            }
    except Exception as e_opt:
        logger.debug(f"[StrategicHorizon] Options error: {e_opt}")

    # 6. Directional Bias & Conviction Synthesis
    if spot < vwap_val and ad_ratio <= 0.45:
        bias = "BEARISH"
        conviction = 88 if is_loco or smt_info.get("has_divergence") else 80
        battleground = f"VWAP Ceiling (₹{vwap_val:,.1f}) & Put Floor (₹{day_low:,.1f})"
        inval = round(max(day_high, vwap_val * 1.003), 1)
        res_lvl = round(min(day_high, max(vwap_val, h4)), 1)
        sup_lvl = round(day_low, 1)

        bull_path = f"Bulls require sustained reclaim above VWAP ₹{vwap_val:,.1f} with A/D ratio expanding above 1.2."
        bear_path = f"Bears maintain control while below ₹{vwap_val:,.1f}. Clean break of Day Low ₹{day_low:,.1f} targets Camarilla L4 / Put Wall."
        coaching = (
            f"Markdown trend active. Avoid buying naked puts directly into session low ₹{day_low:,.1f} (support collision). "
            f"Optimal risk-reward: initiate short on relief pullback to 5m 20-EMA/VWAP (₹{vwap_val:,.1f}), "
            f"or enter on confirmed Stop-Limit breakdown below ₹{day_low:,.1f} with defined-risk Bear Put Spread."
        )
    elif spot > vwap_val and ad_ratio >= 1.5:
        bias = "BULLISH"
        conviction = 85
        battleground = f"VWAP Support (₹{vwap_val:,.1f}) & Day High (₹{day_high:,.1f})"
        inval = round(min(day_low, vwap_val * 0.997), 1)
        res_lvl = round(day_high, 1)
        sup_lvl = round(max(day_low, min(vwap_val, l4)), 1)

        bull_path = f"Bulls target breakout through Day High ₹{day_high:,.1f} towards Call Wall ₹{call_wall:,.1f}."
        bear_path = f"Bears need supply rejection at ₹{day_high:,.1f} and loss of VWAP ₹{vwap_val:,.1f} to flip bias."
        coaching = (
            f"Markup trend active. Do not chase at highs into Call Wall ₹{call_wall:,.1f}. "
            f"Enter on pullbacks to VWAP/5m 20-EMA (₹{vwap_val:,.1f}) with tight stop."
        )
    else:
        bias = "NEUTRAL"
        conviction = 65
        battleground = f"Range: ₹{day_low:,.1f} to ₹{day_high:,.1f} (Pivot ₹{vwap_val:,.1f})"
        inval = round(day_high, 1)
        res_lvl = round(day_high, 1)
        sup_lvl = round(day_low, 1)

        bull_path = f"Breakout above ₹{day_high:,.1f} needed for trend ignition."
        bear_path = f"Breakdown below ₹{day_low:,.1f} needed for liquidation continuation."
        coaching = (
            "Consolidation regime. Avoid naked option buying (theta bleed risk). "
            "Use defined-risk spreads or wait for breakout with institutional volume."
        )

    if is_loco and loco_detail:
        coaching = f"{coaching} [Locomotive Divergence: {loco_detail}]"

    return StrategicHorizonReport(
        symbol=clean_sym,
        spot=round(spot, 1),
        vwap=round(vwap_val, 1),
        day_high=round(day_high, 1),
        day_low=round(day_low, 1),
        regime_verdict=reg_verdict,
        bias_direction=bias,
        conviction_score=conviction,
        battleground_zone=battleground,
        immediate_resistance=res_lvl,
        pivot_equilibrium=round(vwap_val, 1),
        immediate_support=sup_lvl,
        invalidation_level=inval,
        market_breadth=mb_dict,
        options_posture=opt_info,
        smt_alignment=smt_info,
        tactical_scenarios={
            "bullish_pathway": bull_path,
            "bearish_pathway": bear_path,
        },
        actionable_coaching=coaching,
        timestamp=ts_str,
    )
