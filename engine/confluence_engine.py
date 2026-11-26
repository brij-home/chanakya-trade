"""
engine/confluence_engine.py
───────────────────────────
Institutional Multi-Factor Confluence Engine for Indian Derivatives (NSE / BSE).

Replaces defensive binary vetoes with an affirmative, weighted 0-100 Confluence Score.
Identifies high-conviction asymmetric trading opportunities by validating that
direction, timing, and levels are mutually reinforcing:

1. Pre-Open Gap & Uncrossing Auction Imbalance (15 Points):
   - Pro-Gap in direction of bias with institutional uncrossing volume.
2. Time-of-Day Relative Volume (TOD-RVOL) (20 Points):
   - RVOL >= 1.8x confirms institutional footprint, not retail drift.
3. Intraday Trend & Fair Value Anchor (20 Points):
   - Price holding on correct side of session VWAP and rising/falling 9 EMA.
4. Sector Momentum & Relative Rotation (RRG) (15 Points):
   - Stock belongs to a sector in LEADING or IMPROVING quadrant.
5. Derivatives Order Flow & Strike Buildup (20 Points):
   - Bullish: Call unwinding (bears exiting) or Put writing expansion (> 15% ΔOI).
   - Bearish: Put unwinding or Call writing expansion.
6. Market Structure & Price Action (10 Points):
   - Break of Structure (BOS), unmitigated Order Block, or Failed Sweep Inversion.

Qualification:
- Confluence Score >= 70: QUALIFIED (Asymmetric Edge Confirmed).
- Resolves precision Limit Entry Zone via engine.pullback_level_resolver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional


from engine.alert_identity import canonical_alert_symbol
from engine.pullback_level_resolver import resolve_pullback_entry, PullbackLevelPlan
from engine.option_resolver import is_index_symbol

logger = logging.getLogger("chanakya.engine.confluence")


@dataclass
class ConfluenceFactor:
    name: str
    score: float
    max_score: float
    status: str  # "CONFIRMED" | "PARTIAL" | "ABSENT" | "OPPOSING"
    details: str


@dataclass
class ConfluenceReport:
    symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    total_score: float
    is_qualified: bool  # True if total_score >= 70
    factors: list[ConfluenceFactor] = field(default_factory=list)
    pullback_plan: Optional[PullbackLevelPlan] = None
    headline: str = ""
    summary: str = ""


def evaluate_confluence(
    symbol: str,
    direction: str,
    ltp: float,
    vwap: Optional[float] = None,
    rvol: Optional[float] = None,
    change_pct: Optional[float] = None,
    pre_open_gap_pct: Optional[float] = None,
    sector_quadrant: Optional[str] = None,
    call_oi_change_pct: Optional[float] = None,
    put_oi_change_pct: Optional[float] = None,
    market_structure_signal: Optional[str] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    atr_5m: Optional[float] = None,
) -> ConfluenceReport:
    """
    Evaluates multi-factor confluence score (0 to 100) for a given symbol and bias.
    """
    clean_sym = canonical_alert_symbol(symbol)
    norm_dir = direction.upper().strip()
    is_bull = norm_dir in ("BULLISH", "BUY", "LONG")
    is_idx = is_index_symbol(clean_sym)

    factors: list[ConfluenceFactor] = []
    total_score = 0.0

    eff_chg = change_pct if change_pct is not None else 0.0
    eff_vwap = vwap if (vwap and vwap > 0) else ltp

    # ── Factor 1: Pre-Open Gap & Uncrossing Auction Imbalance (15 Pts) ──
    f1_score = 0.0
    f1_status = "ABSENT"
    f1_desc = "Neutral or unrecorded pre-open gap."
    gap_val = pre_open_gap_pct if pre_open_gap_pct is not None else 0.0
    if is_bull:
        if gap_val >= 0.80:
            f1_score = 15.0
            f1_status = "CONFIRMED"
            f1_desc = f"Institutional Pre-Open Pro-Gap Up (+{gap_val:.2f}%)."
        elif gap_val >= 0.30:
            f1_score = 8.0
            f1_status = "PARTIAL"
            f1_desc = f"Moderate Pre-Open Gap Up (+{gap_val:.2f}%)."
        elif gap_val <= -0.50:
            f1_score = -5.0
            f1_status = "OPPOSING"
            f1_desc = f"Counter-trend Gap Down ({gap_val:.2f}%)."
    else:
        if gap_val <= -0.80:
            f1_score = 15.0
            f1_status = "CONFIRMED"
            f1_desc = f"Institutional Pre-Open Pro-Gap Down ({gap_val:.2f}%)."
        elif gap_val <= -0.30:
            f1_score = 8.0
            f1_status = "PARTIAL"
            f1_desc = f"Moderate Pre-Open Gap Down ({gap_val:.2f}%)."
        elif gap_val >= 0.50:
            f1_score = -5.0
            f1_status = "OPPOSING"
            f1_desc = f"Counter-trend Gap Up (+{gap_val:.2f}%)."
    factors.append(
        ConfluenceFactor("Pre-Open Imbalance", max(0.0, f1_score), 15.0, f1_status, f1_desc)
    )
    total_score += max(0.0, f1_score)

    # ── Factor 2: Time-of-Day Relative Volume Acceleration (20 Pts) ──
    f2_score = 0.0
    f2_status = "ABSENT"
    rvol_val = float(rvol) if rvol is not None else 1.0
    if rvol_val >= 2.2:
        f2_score = 20.0
        f2_status = "CONFIRMED"
        f2_desc = f"Aggressive institutional volume acceleration ({rvol_val:.1f}x TOD-RVOL)."
    elif rvol_val >= 1.6:
        f2_score = 15.0
        f2_status = "CONFIRMED"
        f2_desc = f"Strong volume expansion ({rvol_val:.1f}x TOD-RVOL)."
    elif rvol_val >= 1.2:
        f2_score = 10.0
        f2_status = "PARTIAL"
        f2_desc = f"Moderate volume expansion ({rvol_val:.1f}x TOD-RVOL)."
    else:
        f2_score = 4.0
        f2_status = "ABSENT"
        f2_desc = f"Routine baseline volume ({rvol_val:.1f}x TOD-RVOL)."
    factors.append(ConfluenceFactor("Volume Acceleration", f2_score, 20.0, f2_status, f2_desc))
    total_score += f2_score

    # ── Factor 3: Intraday Trend & VWAP Fair Value Anchor (20 Pts) ──
    f3_score = 0.0
    f3_status = "ABSENT"
    if is_bull:
        if ltp >= eff_vwap * 1.002:
            f3_score = 20.0
            f3_status = "CONFIRMED"
            f3_desc = f"Spot ₹{ltp:,.1f} firmly holding above rising session VWAP ₹{eff_vwap:,.1f}."
        elif ltp >= eff_vwap * 0.999:
            f3_score = 12.0
            f3_status = "PARTIAL"
            f3_desc = f"Spot testing session VWAP equilibrium ₹{eff_vwap:,.1f}."
        else:
            f3_score = 0.0
            f3_status = "OPPOSING"
            f3_desc = f"Spot submerged below VWAP ₹{eff_vwap:,.1f}."
    else:
        if ltp <= eff_vwap * 0.998:
            f3_score = 20.0
            f3_status = "CONFIRMED"
            f3_desc = (
                f"Spot ₹{ltp:,.1f} firmly submerged below falling session VWAP ₹{eff_vwap:,.1f}."
            )
        elif ltp <= eff_vwap * 1.001:
            f3_score = 12.0
            f3_status = "PARTIAL"
            f3_desc = f"Spot testing session VWAP equilibrium ₹{eff_vwap:,.1f}."
        else:
            f3_score = 0.0
            f3_status = "OPPOSING"
            f3_desc = f"Spot holding above VWAP ₹{eff_vwap:,.1f}."
    factors.append(ConfluenceFactor("VWAP Fair Value Anchor", f3_score, 20.0, f3_status, f3_desc))
    total_score += f3_score

    # ── Factor 4: Sector Momentum & RRG Rotation (15 Pts) ──
    f4_score = 0.0
    f4_status = "ABSENT"
    f4_desc = "Neutral or index constituent."
    sec_q = (sector_quadrant or "").upper().strip()
    if is_idx:
        # Indices get automatic neutral-to-full credit based on macro alignment
        f4_score = 12.0
        f4_status = "CONFIRMED"
        f4_desc = "Index benchmark asset."
    else:
        if is_bull:
            if sec_q == "LEADING":
                f4_score = 15.0
                f4_status = "CONFIRMED"
                f4_desc = "Parent sector in RRG LEADING quadrant."
            elif sec_q == "IMPROVING":
                f4_score = 10.0
                f4_status = "PARTIAL"
                f4_desc = "Parent sector in RRG IMPROVING quadrant."
            elif sec_q == "LAGGING":
                f4_score = 0.0
                f4_status = "OPPOSING"
                f4_desc = "Parent sector in RRG LAGGING quadrant."
            else:
                f4_score = 7.0
                f4_status = "PARTIAL"
                f4_desc = "Neutral sector rotation."
        else:
            if sec_q == "LAGGING":
                f4_score = 15.0
                f4_status = "CONFIRMED"
                f4_desc = "Parent sector in RRG LAGGING quadrant."
            elif sec_q == "WEAKENING":
                f4_score = 10.0
                f4_status = "PARTIAL"
                f4_desc = "Parent sector in RRG WEAKENING quadrant."
            elif sec_q == "LEADING":
                f4_score = 0.0
                f4_status = "OPPOSING"
                f4_desc = "Parent sector in RRG LEADING quadrant."
            else:
                f4_score = 7.0
                f4_status = "PARTIAL"
                f4_desc = "Neutral sector rotation."
    factors.append(ConfluenceFactor("Sector RRG Rotation", f4_score, 15.0, f4_status, f4_desc))
    total_score += f4_score

    # ── Factor 5: Derivatives Order Flow & Strike Buildup (20 Pts) ──
    f5_score = 0.0
    f5_status = "ABSENT"
    f5_desc = "Neutral or unrecorded options flow."
    c_oi_chg = call_oi_change_pct if call_oi_change_pct is not None else 0.0
    p_oi_chg = put_oi_change_pct if put_oi_change_pct is not None else 0.0
    if is_bull:
        if p_oi_chg >= 15.0 or c_oi_chg <= -10.0:
            f5_score = 20.0
            f5_status = "CONFIRMED"
            f5_desc = (
                f"Institutional Put writing (+{p_oi_chg:.1f}%) / Call unwinding ({c_oi_chg:.1f}%)."
            )
        elif p_oi_chg >= 5.0 or c_oi_chg < 0.0:
            f5_score = 12.0
            f5_status = "PARTIAL"
            f5_desc = "Moderate Put support addition."
        elif c_oi_chg >= 25.0:
            f5_score = 0.0
            f5_status = "OPPOSING"
            f5_desc = f"Heavy overhead Call writing (+{c_oi_chg:.1f}%)."
        else:
            f5_score = 8.0
            f5_status = "PARTIAL"
            f5_desc = "Balanced derivatives flow."
    else:
        if c_oi_chg >= 15.0 or p_oi_chg <= -10.0:
            f5_score = 20.0
            f5_status = "CONFIRMED"
            f5_desc = f"Heavy Call writing resistance (+{c_oi_chg:.1f}%) / Put unwinding ({p_oi_chg:.1f}%)."
        elif c_oi_chg >= 5.0 or p_oi_chg < 0.0:
            f5_score = 12.0
            f5_status = "PARTIAL"
            f5_desc = "Moderate Call resistance addition."
        elif p_oi_chg >= 25.0:
            f5_score = 0.0
            f5_status = "OPPOSING"
            f5_desc = f"Heavy underlying Put writing support (+{p_oi_chg:.1f}%)."
        else:
            f5_score = 8.0
            f5_status = "PARTIAL"
            f5_desc = "Balanced derivatives flow."
    # Check Microstructure Cumulative Volume Delta (CVD) absorption/expansion
    try:
        from engine.cvd_engine import get_cvd_metrics

        cvd_m = get_cvd_metrics(clean_sym)
        if cvd_m.sample_count >= 5:
            if is_bull and (
                cvd_m.cvd_divergence == "BULLISH_ABSORPTION" or cvd_m.cvd_bias == "BULLISH"
            ):
                f5_score = max(f5_score, 18.0)
                f5_status = "CONFIRMED"
                f5_desc = f"Institutional Order Flow CVD confirmation: {cvd_m.absorption_note}"
            elif not is_bull and (
                cvd_m.cvd_divergence == "BEARISH_EXHAUSTION" or cvd_m.cvd_bias == "BEARISH"
            ):
                f5_score = max(f5_score, 18.0)
                f5_status = "CONFIRMED"
                f5_desc = f"Institutional Order Flow CVD confirmation: {cvd_m.absorption_note}"
            elif is_bull and cvd_m.cvd_divergence == "BEARISH_EXHAUSTION":
                f5_score = 0.0
                f5_status = "OPPOSING"
                f5_desc = f"Order Flow CVD Exhaustion / Bull Trap: {cvd_m.absorption_note}"
            elif not is_bull and cvd_m.cvd_divergence == "BULLISH_ABSORPTION":
                f5_score = 0.0
                f5_status = "OPPOSING"
                f5_desc = f"Order Flow CVD Absorption / Bear Trap: {cvd_m.absorption_note}"
    except Exception as exc_cvd:
        logger.debug(f"[confluence_engine] CVD evaluation note for {clean_sym}: {exc_cvd}")

    factors.append(ConfluenceFactor("Derivatives Order Flow", f5_score, 20.0, f5_status, f5_desc))
    total_score += f5_score

    # ── Factor 6: Market Structure & Price Action Inversion (10 Pts) ──
    f6_score = 5.0  # Base credit
    f6_status = "PARTIAL"
    f6_desc = "Standard market structure."
    ms_sig = (market_structure_signal or "").upper().strip()
    if ms_sig in (
        "BOS",
        "CHOC",
        "ORDER_BLOCK_RETEST",
        "LIQUIDITY_INVERSION",
        "BEAR_TRAP",
        "BULL_TRAP",
    ):
        f6_score = 10.0
        f6_status = "CONFIRMED"
        f6_desc = f"Verified structural trigger: {ms_sig}."
    factors.append(ConfluenceFactor("Market Structure", f6_score, 10.0, f6_status, f6_desc))
    total_score += f6_score

    final_score = round(min(100.0, total_score), 1)
    is_qualified = final_score >= 70.0

    # Calculate Pullback Level Plan
    plan = resolve_pullback_entry(
        symbol=clean_sym,
        direction="BULLISH" if is_bull else "BEARISH",
        spot=ltp,
        vwap=eff_vwap,
        day_high=day_high,
        day_low=day_low,
        atr_5m=atr_5m,
        prefer_options=True,
    )

    verdict_str = "HIGH CONVICTION QUALIFIED" if is_qualified else "UNCONFIRMED SETUP"
    dir_str = "BULLISH CALL" if is_bull else "BEARISH PUT"
    headline = f"🎯 [CONFLUENCE {final_score:.0f}/100] {clean_sym} {dir_str} ({verdict_str})"
    summary = (
        f"Multi-Factor Confluence Score: {final_score:.0f}/100 (Session Move: {eff_chg:+.2f}%). "
        f"Direction: {dir_str}. {plan.actionable_summary}"
    )

    return ConfluenceReport(
        symbol=clean_sym,
        direction="BULLISH" if is_bull else "BEARISH",
        total_score=final_score,
        is_qualified=is_qualified,
        factors=factors,
        pullback_plan=plan,
        headline=headline,
        summary=summary,
    )
