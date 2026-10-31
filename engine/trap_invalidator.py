# -*- coding: utf-8 -*-
"""
engine/trap_invalidator.py
──────────────────────────
Institutional Adversarial Red-Teaming & Trap Falsification Engine.

Acts as the dedicated "Devil's Advocate / Red-Teamer" in the trade lifecycle.
Every candidate setup is actively scrutinized against the 4 primary institutional
market traps in Indian indices and equities:

  1. Volume Exhaustion Breakout (Dry Breakout Fakeout):
     - Breakout attempted on sub-par volume (RVOL < 0.85x 20-MA volume).
     - Retail breakout buyers trapped without institutional sponsorship.

  2. Swing Failure Rejection Wick (SFP Trap):
     - Candle momentarily swept a swing pivot by <= 0.40% but closed back inside
       with an exhaustion wick >= 50% of candle range.

  3. Delta-Neutral OI Pinning Wall Trap:
     - On 0DTE / weekly expiry, massive Call + Put OI clusters at a nearby strike
       (within <= 0.35%), acting as a market-maker gamma peg that chokes delta velocity.

  4. Structural Resistance Collision:
     - Available headroom between entry and the nearest major barrier (CPR, PDH, PDL,
       or Camarilla H4/L4) is < 0.50x initial risk (< 0.5R headroom).

Returns:
  TrapAuditResult with deterministic falsification evidence, trap score (0–100),
  and recommended operational adjustment (PROCEED, DEMOTE_TO_LIMIT_RETEST, HARD_VETO).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger("chanakya.engine.trap_invalidator")


@dataclass
class TrapAuditResult:
    """Detailed audit verdict from Adversarial Trap Invalidator."""

    symbol: str
    is_trap: bool
    trap_score: int  # 0 to 100 (higher = greater probability of trap)
    trap_type: str  # "CLEAN" | "VOLUME_EXHAUSTION_BREAKOUT" | "SWING_FAILURE_WICK" | "OI_PINNING_WALL" | "RESISTANCE_COLLISION"
    severity: str  # "NONE" | "LOW" | "MODERATE" | "HIGH" | "CRITICAL_INVALIDATION"
    falsification_evidence: str
    recommended_action: str  # "PROCEED" | "DEMOTE_TO_LIMIT_RETEST" | "TIGHTEN_SL" | "HARD_VETO"
    headroom_pts: float
    headroom_r: float
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "is_trap": self.is_trap,
            "trap_score": self.trap_score,
            "trap_type": self.trap_type,
            "severity": self.severity,
            "falsification_evidence": self.falsification_evidence,
            "recommended_action": self.recommended_action,
            "headroom_pts": round(self.headroom_pts, 2),
            "headroom_r": round(self.headroom_r, 2),
            "flags": self.flags,
        }


def audit_trade_for_traps(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target_1: float,
    df_bars: Optional[pd.DataFrame] = None,
    chain: Optional[list[Any]] = None,
    daily_levels: Optional[Any] = None,
    current_hour: Optional[int] = None,
    is_0dte: bool = False,
) -> TrapAuditResult:
    """
    Performs adversarial multi-factor trap audit on a candidate trade setup.
    """
    clean_sym = symbol.upper().replace("NSE:", "").replace("BSE:", "").replace(".NS", "").strip()
    is_long = direction.upper() in ("LONG", "BULLISH", "BUY", "CE")
    initial_risk = max(0.5, abs(entry_price - stop_loss))

    trap_score = 0
    flags: list[str] = []
    evidence_points: list[str] = []
    primary_trap_type = "CLEAN"
    severity = "NONE"
    action = "PROCEED"

    # Default headroom is the distance to Target 1
    headroom_pts = abs(target_1 - entry_price) if target_1 > 0 else (initial_risk * 2.0)
    headroom_r = headroom_pts / initial_risk

    # ── 1. Check Volume Exhaustion Breakout (Dry Breakout Trap) ───────
    if df_bars is not None and len(df_bars) >= 20:
        col_v = "volume" if "volume" in df_bars.columns else "Volume"
        col_c = "close" if "close" in df_bars.columns else "Close"
        col_o = "open" if "open" in df_bars.columns else "Open"
        col_h = "high" if "high" in df_bars.columns else "High"
        col_l = "low" if "low" in df_bars.columns else "Low"

        vols = df_bars[col_v].astype(float).values
        avg_vol_20 = float(np.mean(vols[-20:-1])) if len(vols) > 20 else float(np.mean(vols))
        curr_vol = float(vols[-1])
        rvol = curr_vol / max(1.0, avg_vol_20)

        # If breakout setup attempted on dry volume (RVOL < 0.85x)
        if rvol < 0.85:
            trap_score += 35
            flags.append("DRY_VOLUME_BREAKOUT")
            evidence_points.append(
                f"Volume exhaustion: Breakout bar volume is {rvol:.2f}x 20-MA volume (< 0.85x required). "
                f"Lacks institutional accumulation sponsorship."
            )
            primary_trap_type = "VOLUME_EXHAUSTION_BREAKOUT"
            severity = "HIGH"
            action = "DEMOTE_TO_LIMIT_RETEST"

        # ── 2. Check Swing Failure Rejection Wick (SFP Trap) ──────────
        curr_h = float(df_bars[col_h].iloc[-1])
        curr_l = float(df_bars[col_l].iloc[-1])
        curr_c = float(df_bars[col_c].iloc[-1])
        curr_o = float(df_bars[col_o].iloc[-1])
        bar_range = max(0.1, curr_h - curr_l)

        if is_long:
            upper_wick = curr_h - max(curr_c, curr_o)
            wick_ratio = upper_wick / bar_range
            if wick_ratio >= 0.50 and curr_c < curr_h:
                trap_score += 45
                flags.append("LONG_EXHAUSTION_REJECTION_WICK")
                evidence_points.append(
                    f"Bearish SFP wick: {wick_ratio:.0%} upper rejection wick at ₹{curr_h:,.1f}. "
                    f"Aggressive buyers were absorbed into institutional limit asks."
                )
                primary_trap_type = "SWING_FAILURE_WICK"
                severity = "CRITICAL_INVALIDATION"
                action = "HARD_VETO"
        else:
            lower_wick = min(curr_c, curr_o) - curr_l
            wick_ratio = lower_wick / bar_range
            if wick_ratio >= 0.50 and curr_c > curr_l:
                trap_score += 45
                flags.append("SHORT_EXHAUSTION_REJECTION_WICK")
                evidence_points.append(
                    f"Bullish SFP wick: {wick_ratio:.0%} lower absorption wick at ₹{curr_l:,.1f}. "
                    f"Aggressive sellers were absorbed into institutional limit bids."
                )
                primary_trap_type = "SWING_FAILURE_WICK"
                severity = "CRITICAL_INVALIDATION"
                action = "HARD_VETO"

    # ── 3. Check Structural Resistance / CPR Collision ────────────────
    if daily_levels is not None:
        # Check proximity to key structural barriers in trade direction
        barriers: list[tuple[str, float]] = []

        # Previous Day High / Low
        pdh = getattr(daily_levels, "pdh", 0.0) or 0.0
        pdl = getattr(daily_levels, "pdl", 0.0) or 0.0
        if pdh > 0:
            barriers.append(("PDH", pdh))
        if pdl > 0:
            barriers.append(("PDL", pdl))

        # Central Pivot Range (CPR)
        cpr = getattr(daily_levels, "cpr", None)
        if isinstance(cpr, dict):
            tc = float(cpr.get("tc", 0.0) or 0.0)
            bc = float(cpr.get("bc", 0.0) or 0.0)
            pivot = float(cpr.get("pivot", 0.0) or 0.0)
            if tc > 0:
                barriers.append(("CPR_TC", tc))
            if bc > 0:
                barriers.append(("CPR_BC", bc))
            if pivot > 0:
                barriers.append(("CPR_PIVOT", pivot))

        # Camarilla Pivots (H4, L4, H3, L3)
        cam = getattr(daily_levels, "camarilla", None)
        if isinstance(cam, dict):
            h4 = float(cam.get("h4", 0.0) or 0.0)
            l4 = float(cam.get("l4", 0.0) or 0.0)
            if h4 > 0:
                barriers.append(("CAM_H4", h4))
            if l4 > 0:
                barriers.append(("CAM_L4", l4))

        # Find closest barrier ahead of entry in trade direction
        closest_barrier_name = None
        min_dist = float("inf")

        for b_name, b_price in barriers:
            if is_long and b_price > entry_price:
                dist = b_price - entry_price
                if dist < min_dist:
                    min_dist = dist
                    closest_barrier_name = b_name
            elif (not is_long) and b_price < entry_price:
                dist = entry_price - b_price
                if dist < min_dist:
                    min_dist = dist
                    closest_barrier_name = b_name

        if closest_barrier_name and min_dist < float("inf"):
            headroom_pts = min_dist
            headroom_r = round(headroom_pts / initial_risk, 2)

            # If headroom is less than 0.5R, trade collides directly into resistance
            if headroom_r < 0.50:
                trap_score += 50
                flags.append(f"STRUCTURAL_COLLISION_{closest_barrier_name}")
                evidence_points.append(
                    f"Structural wall collision: {closest_barrier_name} rests only {headroom_pts:.1f} pts away "
                    f"({headroom_r:.2f}R headroom vs 0.50R required). Insufficient runway before resistance."
                )
                primary_trap_type = "RESISTANCE_COLLISION"
                severity = "CRITICAL_INVALIDATION"
                action = "HARD_VETO"
            elif headroom_r < 1.0:
                trap_score += 25
                flags.append(f"TIGHT_HEADROOM_{closest_barrier_name}")
                evidence_points.append(
                    f"Tight headroom: {closest_barrier_name} is situated {headroom_pts:.1f} pts away ({headroom_r:.2f}R)."
                )
                if action == "PROCEED":
                    action = "TIGHTEN_SL"
                    severity = "MODERATE"

    # ── 4. Check Delta-Neutral OI Pinning Wall Trap ───────────────────
    if chain and is_0dte:
        try:
            # Locate strikes within 0.35% of entry
            nearby_strikes = []
            for item in chain:
                strike_px = getattr(item, "strike", None) or (
                    item.get("strike") if isinstance(item, dict) else 0.0
                )
                if strike_px and abs(strike_px - entry_price) / entry_price <= 0.0035:
                    call_oi = getattr(item, "call_oi", 0) or (
                        item.get("call_oi", 0) if isinstance(item, dict) else 0
                    )
                    put_oi = getattr(item, "put_oi", 0) or (
                        item.get("put_oi", 0) if isinstance(item, dict) else 0
                    )
                    total_oi = (call_oi or 0) + (put_oi or 0)
                    nearby_strikes.append((strike_px, total_oi, call_oi, put_oi))

            if nearby_strikes:
                nearby_strikes.sort(key=lambda x: x[1], reverse=True)
                top_strike, top_oi, c_oi, p_oi = nearby_strikes[0]
                # Heavy strike pinning if combined OI is high and balance between calls & puts is tight
                if top_oi > 500000 and c_oi and p_oi:
                    oi_balance = min(c_oi, p_oi) / max(1, max(c_oi, p_oi))
                    if oi_balance >= 0.70:  # Balanced strangle pinning
                        trap_score += 30
                        flags.append(f"OI_PINNING_STRANGLE_{int(top_strike)}")
                        evidence_points.append(
                            f"0DTE Gamma Pinning Wall at ₹{top_strike:,.0f} (Combined OI: {top_oi:,}, Balance: {oi_balance:.0%}). "
                            f"Market makers delta-hedging will damp directional momentum."
                        )
                        if severity not in ("HIGH", "CRITICAL_INVALIDATION"):
                            primary_trap_type = "OI_PINNING_WALL"
                            severity = "MODERATE"
                            action = "DEMOTE_TO_LIMIT_RETEST"
        except Exception as e_chain:
            logger.debug(f"[trap_invalidator] Non-fatal chain check error: {e_chain}")

    # Determine final verdict
    is_trap = (trap_score >= 40) or (severity in ("HIGH", "CRITICAL_INVALIDATION"))
    falsification_evidence = (
        " | ".join(evidence_points)
        if evidence_points
        else "No active institutional traps detected."
    )

    return TrapAuditResult(
        symbol=clean_sym,
        is_trap=is_trap,
        trap_score=min(100, trap_score),
        trap_type=primary_trap_type,
        severity=severity,
        falsification_evidence=falsification_evidence,
        recommended_action=action,
        headroom_pts=headroom_pts,
        headroom_r=headroom_r,
        flags=flags,
    )
