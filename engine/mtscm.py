"""
engine/mtscm.py
───────────────
Universal Multi-Timeframe Structural Confluence Matrix (MTSCM 3-Tier Score) Engine.

Institutional Confluence Protocol:
Trades must NOT trigger on isolated single-timeframe spikes or unconfirmed indicators.
The MTSCM systematically evaluates structural confluence across three distinct analytical horizons:

1. 🏛️ TIER 1: HIGHER TIMEFRAME (HTF - Daily / 60m Structural Trend) [Weight: 40%]
   - Macro Trend & Moving Average Stack (Daily 200-EMA, 50-EMA) [15 pts]
   - Market Structure & Swing Architecture (BOS / Higher Highs & Lows) [15 pts]
   - Sector Rotation / RRG Alignment (Leading / Improving vs Lagging) [10 pts]

2. ⚖️ TIER 2: INTERMEDIATE TIMEFRAME (ITF - 15m Execution Structure) [Weight: 35%]
   - Smart Money Institutional Zones (Unmitigated Order Block / FVG Clearance) [12 pts]
   - Auction Market Theory (Value Area Acceptance above d-VAL/POC or below d-VAH/POC) [13 pts]
   - Volatility Regime & Squeeze Mechanics (VCP / Squeeze Expansion) [10 pts]

3. ⚡ TIER 3: LOWER TIMEFRAME (LTF - 5m / 1m Microstructure Trigger) [Weight: 25%]
   - Order Flow Cumulative Volume Delta (CVD Delta Aggression Ratio >= 2.0x) [10 pts]
   - Institutional VWAP Positioning & Slope [8 pts]
   - Level-2 Order Book Depth Imbalance (Bids absorbing Asks / Dominance >= 1.8x) [7 pts]

Composite Confluence Tiers:
  - 🏆 TIER 1: APEX_CONFLUENCE (Score 85–100%) -> Full Sizing (1.25x), Free-Roll Eligible.
  - 🎯 TIER 2: STRATEGIC_MOMENTUM (Score 70–84%) -> Baseline Sizing (1.0x).
  - 🛡️ TIER 3: DEFENSIVE_VETO (Score < 70%) -> Defined-Risk Spreads Only (0.65x) or VETO.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

from engine.alert_identity import canonical_alert_symbol

logger = logging.getLogger("chanakya.mtscm")


@dataclass
class MTSCMResult:
    """Quantitative result from Multi-Timeframe Structural Confluence Matrix."""

    symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    total_score: float  # 0.0 to 100.0
    tier: str  # "APEX_CONFLUENCE" | "STRATEGIC_MOMENTUM" | "DEFENSIVE_VETO"
    lot_multiplier: float  # 1.25 | 1.00 | 0.65

    htf_score: float  # 0 to 40
    itf_score: float  # 0 to 35
    ltf_score: float  # 0 to 25

    confluences: list[str] = field(default_factory=list)
    headwinds: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_mtscm(
    symbol: str,
    ltp: float,
    direction: str = "BULLISH",
    metrics: Optional[dict[str, Any]] = None,
    htf_df: Optional[pd.DataFrame] = None,
    itf_df: Optional[pd.DataFrame] = None,
    ltf_df: Optional[pd.DataFrame] = None,
) -> MTSCMResult:
    """
    Evaluates institutional multi-timeframe structural confluence score (0–100).
    Uses provided DataFrames if available; otherwise falls back gracefully to metrics payload.
    """
    clean_sym = canonical_alert_symbol(symbol)
    m = metrics or {}
    dir_upper = str(direction).upper()
    is_bull = dir_upper in ("BULLISH", "LONG", "BUY")

    htf_pts = 0.0
    itf_pts = 0.0
    ltf_pts = 0.0
    confluences: list[str] = []
    headwinds: list[str] = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. 🏛️ TIER 1: HTF Structural Trend (Max: 40 pts)
    # ─────────────────────────────────────────────────────────────────────────
    # 1a. Daily 200-EMA & 50-EMA Macro Trend (15 pts)
    d200 = float(m.get("daily_200_ema") or m.get("ema_200") or 0.0)
    d50 = float(m.get("daily_50_ema") or m.get("ema_50") or 0.0)
    if is_bull:
        if d200 > 0 and ltp > d200:
            htf_pts += 8.0
            confluences.append(f"Price > Daily 200-EMA (₹{d200:,.1f})")
        elif d200 > 0 and ltp < d200:
            headwinds.append(f"Trading below Daily 200-EMA (₹{d200:,.1f})")

        if d50 > 0 and ltp > d50:
            htf_pts += 7.0
            confluences.append(f"Price > Daily 50-EMA (₹{d50:,.1f})")
        elif d200 == 0 and d50 == 0:
            # Neutral baseline if moving averages unavailable
            htf_pts += 10.0
    else:
        if d200 > 0 and ltp < d200:
            htf_pts += 8.0
            confluences.append(f"Price < Daily 200-EMA (₹{d200:,.1f})")
        elif d200 > 0 and ltp > d200:
            headwinds.append(f"Trading above Daily 200-EMA (₹{d200:,.1f})")

        if d50 > 0 and ltp < d50:
            htf_pts += 7.0
            confluences.append(f"Price < Daily 50-EMA (₹{d50:,.1f})")
        elif d200 == 0 and d50 == 0:
            htf_pts += 10.0

    # 1b. HTF Market Structure & Break of Structure (BOS) (15 pts)
    htf_bos = bool(m.get("htf_bos") or m.get("daily_bos") or m.get("trend_aligned"))
    structure_phase = str(m.get("market_structure") or m.get("structure") or "").upper()
    if is_bull:
        if htf_bos or "BULLISH" in structure_phase or "EXPANSION" in structure_phase:
            htf_pts += 15.0
            confluences.append("HTF Bullish Market Structure (BOS/Higher Highs)")
        elif "BEARISH" in structure_phase:
            headwinds.append("HTF Bearish Market Structure Conflict")
        else:
            htf_pts += 8.0
    else:
        if htf_bos or "BEARISH" in structure_phase or "DISTRIBUTION" in structure_phase:
            htf_pts += 15.0
            confluences.append("HTF Bearish Market Structure (BOS/Lower Lows)")
        elif "BULLISH" in structure_phase:
            headwinds.append("HTF Bullish Market Structure Conflict")
        else:
            htf_pts += 8.0

    # 1c. Sector Rotation / RRG Phase (10 pts)
    rrg_phase = str(m.get("sector_rrg_phase") or m.get("rrg_quadrant") or "").upper()
    if is_bull:
        if rrg_phase in ("LEADING", "IMPROVING"):
            htf_pts += 10.0
            confluences.append(f"Sector RRG Tailwind ({rrg_phase})")
        elif rrg_phase == "LAGGING":
            headwinds.append("Sector RRG Lagging Headwind")
        else:
            htf_pts += 6.0
    else:
        if rrg_phase in ("LAGGING", "WEAKENING"):
            htf_pts += 10.0
            confluences.append(f"Sector RRG Distribution ({rrg_phase})")
        elif rrg_phase == "LEADING":
            headwinds.append("Sector RRG Leading Counter-Trend Headwind")
        else:
            htf_pts += 6.0

    # ─────────────────────────────────────────────────────────────────────────
    # 2. ⚖️ TIER 2: ITF 15m Execution Structure (Max: 35 pts)
    # ─────────────────────────────────────────────────────────────────────────
    # 2a. Smart Money Order Block / Fair Value Gap (12 pts)
    has_ob = bool(
        m.get("order_block")
        or m.get("bullish_ob" if is_bull else "bearish_ob")
        or "OB" in str(m.get("signals", []))
    )
    has_fvg = bool(m.get("fvg") or m.get("fair_value_gap") or "FVG" in str(m.get("signals", [])))
    if has_ob:
        itf_pts += 7.0
        confluences.append("Institutional Order Block Zone Reclaimed")
    if has_fvg:
        itf_pts += 5.0
        confluences.append("Fair Value Gap (FVG) Liquidity Vacuum Cleared")
    if not has_ob and not has_fvg:
        itf_pts += 5.0

    # 2b. Auction Market Theory Value Area Acceptance & POC Migration (13 pts)
    poc = float(m.get("d_poc") or m.get("poc") or 0.0)
    val = float(m.get("d_val") or m.get("val") or 0.0)
    vah = float(m.get("d_vah") or m.get("vah") or 0.0)
    poc_mig = str(m.get("poc_migration") or m.get("developing_poc_migration") or "").upper()

    if is_bull:
        if poc > 0 and ltp >= poc:
            itf_pts += 7.0
            confluences.append(f"Holding above Volume POC (₹{poc:,.1f})")
        if poc_mig in ("ASCENDING", "HIGHER"):
            itf_pts += 6.0
            confluences.append("Developing POC Migrating Higher (AMT Value Acceptance)")
        elif poc_mig in ("DESCENDING", "STAGNANT_LOW"):
            headwinds.append("Developing POC Stagnant / Non-Acceptance")
        elif val > 0 and ltp >= val:
            itf_pts += 4.0
    else:
        if poc > 0 and ltp <= poc:
            itf_pts += 7.0
            confluences.append(f"Holding below Volume POC (₹{poc:,.1f})")
        if poc_mig in ("DESCENDING", "LOWER"):
            itf_pts += 6.0
            confluences.append("Developing POC Migrating Lower (AMT Value Acceptance)")
        elif poc_mig in ("ASCENDING", "STAGNANT_HIGH"):
            headwinds.append("Developing POC Stagnant / Non-Acceptance Lower")
        elif vah > 0 and ltp <= vah:
            itf_pts += 4.0

    if poc == 0 and val == 0 and vah == 0:
        itf_pts += 8.0

    # 2c. Volatility Squeeze & Falcon Regime (10 pts)
    squeeze_state = str(m.get("squeeze_state") or "").upper()
    chop_idx = float(m.get("chop_index") or 45.0)
    if "FIRED" in squeeze_state or "RELEASE" in squeeze_state:
        itf_pts += 10.0
        confluences.append("Volatility Squeeze Fired into Momentum Expansion")
    elif chop_idx <= 38.2:
        itf_pts += 8.0
        confluences.append(f"Falcon Trending Expansion (CHOP {chop_idx:.1f} <= 38.2)")
    elif chop_idx >= 61.8:
        headwinds.append(f"Falcon Severe Consolidation Chop (CHOP {chop_idx:.1f} >= 61.8)")
    else:
        itf_pts += 6.0

    # ─────────────────────────────────────────────────────────────────────────
    # 3. ⚡ TIER 3: LTF 5m/1m Microstructure Trigger (Max: 25 pts)
    # ─────────────────────────────────────────────────────────────────────────
    # 3a. Order Flow Cumulative Volume Delta Aggression (10 pts)
    cvd_ratio = float(m.get("cvd_ratio") or m.get("cvd_divergence_ratio") or 1.0)
    cvd_div = str(m.get("cvd_divergence") or "").upper()
    if is_bull:
        if cvd_ratio >= 2.0:
            ltf_pts += 10.0
            confluences.append(f"Buyer CVD Delta Aggression ({cvd_ratio:.1f}x)")
        elif cvd_ratio >= 1.4 or "BULLISH" in cvd_div:
            ltf_pts += 7.0
            confluences.append("Positive Cumulative Volume Delta Flow")
        elif "BEARISH_EXHAUSTION" in cvd_div or cvd_ratio < 0.60:
            headwinds.append("Bearish CVD Limit Ask Absorption Overhang")
        else:
            ltf_pts += 5.0
    else:
        if cvd_ratio >= 2.0:
            ltf_pts += 10.0
            confluences.append(f"Seller CVD Delta Aggression ({cvd_ratio:.1f}x)")
        elif cvd_ratio >= 1.4 or "BEARISH" in cvd_div:
            ltf_pts += 7.0
            confluences.append("Negative Cumulative Volume Delta Flow")
        elif "BULLISH_ABSORPTION" in cvd_div or cvd_ratio < 0.60:
            headwinds.append("Bullish CVD Limit Bid Absorption Floor")
        else:
            ltf_pts += 5.0

    # 3b. Intraday VWAP Position & Reclaim (8 pts)
    vwap = float(m.get("vwap") or 0.0)
    if vwap > 0:
        if is_bull and ltp >= vwap:
            ltf_pts += 8.0
            confluences.append(f"Holding firmly above VWAP (₹{vwap:,.1f})")
        elif not is_bull and ltp <= vwap:
            ltf_pts += 8.0
            confluences.append(f"Holding firmly below VWAP (₹{vwap:,.1f})")
        else:
            headwinds.append("Trapped on wrong side of session VWAP")
    else:
        ltf_pts += 5.0

    # 3c. Level-2 Order Book Depth Imbalance (7 pts)
    b_qty = float(m.get("total_buy_qty") or m.get("total_buy_quantity") or 0.0)
    s_qty = float(m.get("total_sell_qty") or m.get("total_sell_quantity") or 0.0)
    if b_qty > 0 and s_qty > 0:
        if is_bull and b_qty >= (1.5 * s_qty):
            ltf_pts += 7.0
            confluences.append(f"Order Book Bid Dominance ({(b_qty / s_qty):.1f}x Buy Pressure)")
        elif not is_bull and s_qty >= (1.5 * b_qty):
            ltf_pts += 7.0
            confluences.append(f"Order Book Ask Dominance ({(s_qty / b_qty):.1f}x Sell Pressure)")
        elif is_bull and s_qty >= (2.0 * b_qty):
            headwinds.append("Heavy Order Book Sell Overhang (Asks outnumber Bids >2x)")
        elif not is_bull and b_qty >= (2.0 * s_qty):
            headwinds.append("Heavy Order Book Buy Floor (Bids outnumber Asks >2x)")
        else:
            ltf_pts += 4.0
    else:
        ltf_pts += 4.0

    # Total score calculation (clamped 0 to 100)
    total_score = round(min(100.0, max(0.0, htf_pts + itf_pts + ltf_pts)), 1)

    # Resolve Conviction Tier & Multiplier
    if total_score >= 85.0 and len(headwinds) == 0:
        tier = "APEX_CONFLUENCE"
        multiplier = 1.25
    elif (total_score >= 65.0 and len(headwinds) == 0) or (
        total_score >= 70.0 and len(headwinds) <= 1
    ):
        tier = "STRATEGIC_MOMENTUM"
        multiplier = 1.00
    elif len(headwinds) >= 2:
        tier = "DEFENSIVE_VETO"
        multiplier = 0.65
    elif len(confluences) == 0 and len(headwinds) == 0:
        tier = "NEUTRAL_BASELINE"
        multiplier = 1.00
    else:
        tier = "DEFENSIVE_CAUTION"
        multiplier = 0.85

    summary = (
        f"MTSCM Score: {total_score:.1f}/100 [{tier}] · HTF: {htf_pts:.1f}/40 | "
        f"ITF: {itf_pts:.1f}/35 | LTF: {ltf_pts:.1f}/25 · "
        f"Confluences: {len(confluences)} | Headwinds: {len(headwinds)}"
    )

    return MTSCMResult(
        symbol=clean_sym,
        direction=dir_upper,
        total_score=total_score,
        tier=tier,
        lot_multiplier=multiplier,
        htf_score=round(htf_pts, 1),
        itf_score=round(itf_pts, 1),
        ltf_score=round(ltf_pts, 1),
        confluences=confluences,
        headwinds=headwinds,
        summary=summary,
    )
