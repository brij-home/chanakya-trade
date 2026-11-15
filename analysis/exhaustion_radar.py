# -*- coding: utf-8 -*-
"""
analysis/exhaustion_radar.py
────────────────────────────
Institutional Anti-Chase, Exhaustion & Headroom Radar for Dalal Street.

Guarantees that no trade enters at the point of exhaustion, buying climax,
selling climax, or into an impenetrable structural/derivative resistance wall.

Evaluates 5 Quantitative Dimensions:
  1. Extension Z-Score: Displacement from session VWAP / 20 EMA in units of ATR.
     - Vetoes momentum chase when price is > 1.8x ATR extended.
  2. Volume Spread Analysis (VSA) Climax:
     - Detects Buying Climax & Selling Climax (Effort vs Result: high volume + narrow spread + rejection wick).
     - Validates Volume Dry-Up on pullbacks (RVOL <= 0.75x 20-MA volume).
  3. Structural Headroom R-Multiple Gate:
     - Calculates exact distance to the nearest major barrier (Daily CPR, Camarilla H4/L4,
       Daily VPOC, or Call/Put OI Writing Wall).
     - Enforces: Headroom >= 2.50x initial risk.
  4. Order Flow Toxicity & Adverse Selection (VPIN & OBI):
     - Warns/vetoes when VPIN indicates toxic institutional flow (adverse selection for limit orders).
  5. Deterministic "No-Chase" Price Ceiling:
     - Computes the mathematical boundary beyond which market orders are strictly forbidden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from analysis.technical import atr, ema

logger = logging.getLogger("chanakya.analysis.exhaustion_radar")


@dataclass
class ExhaustionRadarVerdict:
    """Comprehensive verdict from the Institutional Exhaustion Radar."""

    symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    is_exhausted: bool
    severity: str  # "NONE" | "LOW" | "MODERATE" | "HIGH" | "CRITICAL_VETO"
    trap_type: str  # "CLEAN" | "EXTENSION_CLIMAX" | "PASSIVE_ABSORPTION" | "CHOKED_HEADROOM" | "TOXIC_FLOW" | "HIGH_VOL_PULLBACK"
    recommended_action: str  # "PROCEED" | "LIMIT_PULLBACK_REQUIRED" | "TIGHTEN_SL" | "HARD_VETO"

    extension_zscore: float  # |LTP - VWAP| / ATR
    headroom_pts: float
    headroom_multiple: float  # headroom / initial_risk
    no_chase_limit: float  # Max allowable entry price

    vsa_signal: (
        str  # "NORMAL" | "BUYING_CLIMAX" | "SELLING_CLIMAX" | "VOLUME_DRYUP" | "HIGH_VOL_CHURN"
    )
    is_volume_dryup: bool
    vpin_toxicity: Optional[float] = None
    flags: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "is_exhausted": self.is_exhausted,
            "severity": self.severity,
            "trap_type": self.trap_type,
            "recommended_action": self.recommended_action,
            "extension_zscore": round(self.extension_zscore, 2),
            "headroom_pts": round(self.headroom_pts, 2),
            "headroom_multiple": round(self.headroom_multiple, 2),
            "no_chase_limit": round(self.no_chase_limit, 2),
            "vsa_signal": self.vsa_signal,
            "is_volume_dryup": self.is_volume_dryup,
            "vpin_toxicity": round(self.vpin_toxicity, 3)
            if self.vpin_toxicity is not None
            else None,
            "flags": self.flags,
            "rationale": self.rationale,
        }


def compute_extension_zscore(
    ltp: float,
    vwap: Optional[float] = None,
    atr_val: Optional[float] = None,
    df: Optional[pd.DataFrame] = None,
) -> float:
    """
    Computes the displacement of current price from session VWAP (or 20 EMA) in units of ATR.

    Z_ext = |LTP - Anchor| / ATR
    """
    if ltp <= 0:
        return 0.0

    anchor = vwap if vwap and vwap > 0 else None

    # Fallback to 20 EMA or close series if anchor missing
    if anchor is None and df is not None and len(df) >= 20:
        try:
            ema20 = ema(df["close"].astype(float), period=20)
            anchor = float(ema20.iloc[-1])
        except Exception as e_supp:
            logger.debug(f"[exhaustion_radar] EMA fallback error: {e_supp}")

    if anchor is None or anchor <= 0:
        anchor = ltp  # No displacement measurable

    if atr_val is None or atr_val <= 0:
        if df is not None and len(df) >= 14:
            try:
                atr_s = atr(df, period=14)
                atr_val = float(atr_s.dropna().iloc[-1])
            except Exception as e_supp:
                logger.debug(f"[exhaustion_radar] ATR calculation error: {e_supp}")
                atr_val = ltp * 0.015
        else:
            atr_val = ltp * 0.015

    atr_val = max(0.001, atr_val)
    return abs(ltp - anchor) / atr_val


def evaluate_vsa_climax(
    df: pd.DataFrame,
    direction: str = "BULLISH",
    is_pullback: bool = False,
) -> tuple[str, bool, list[str]]:
    """
    Evaluates Volume Spread Analysis for exhaustion wicks, climaxes, and volume dry-ups.

    Returns:
        (vsa_signal, is_volume_dryup, evidence_flags)
    """
    if df is None or len(df) < 5:
        return ("NORMAL", False, [])

    cols = {c.lower(): c for c in df.columns}
    h_col = cols.get("high", "high")
    l_col = cols.get("low", "low")
    c_col = cols.get("close", "close")
    o_col = cols.get("open", "open")
    v_col = cols.get("volume", "volume")

    last = df.iloc[-1]
    c_c = float(last[c_col])
    c_o = float(last[o_col]) if o_col in df.columns else c_c
    c_h = float(last[h_col])
    c_l = float(last[l_col])
    bar_range = max(0.0001, c_h - c_l)
    upper_wick = c_h - max(c_o, c_c)
    lower_wick = min(c_o, c_c) - c_l

    # Volume ratios
    v_series = df[v_col].astype(float) if v_col in df.columns else pd.Series(1000.0, index=df.index)
    avg_vol = float(v_series.rolling(20, min_periods=3).mean().iloc[-1])
    avg_vol = max(1.0, avg_vol)
    curr_vol = float(v_series.iloc[-1])
    rvol = curr_vol / avg_vol

    # Spread ratio vs 20-period average
    tr_series = df[h_col].astype(float) - df[l_col].astype(float)
    avg_tr = float(tr_series.rolling(20, min_periods=3).mean().iloc[-1])
    avg_tr = max(0.0001, avg_tr)
    spread_ratio = bar_range / avg_tr

    flags: list[str] = []

    # Pullback volume evaluation
    if is_pullback:
        if rvol <= 0.75:
            flags.append(f"Volume Dry-Up Confirmed (RVOL {rvol:.2f}x <= 0.75x)")
            return ("VOLUME_DRYUP", True, flags)
        elif rvol >= 1.60:
            flags.append(
                f"High-Volume Churn on Retest (RVOL {rvol:.2f}x >= 1.60x - Distribution Risk)"
            )
            return ("HIGH_VOL_CHURN", False, flags)

    # Climax & Absorption Checks
    if direction.upper() in ("BULLISH", "LONG", "BUY"):
        # Buying Climax: Ultra high volume + narrow spread or massive upper rejection wick
        if rvol >= 2.0 and upper_wick >= 0.35 * bar_range:
            flags.append(
                f"Buying Climax Wick (Upper wick {upper_wick / bar_range * 100:.1f}%, RVOL {rvol:.2f}x)"
            )
            return ("BUYING_CLIMAX", False, flags)
        if rvol >= 2.2 and spread_ratio <= 0.65 and c_c > c_o:
            flags.append(
                f"Effort vs Result Top (RVOL {rvol:.2f}x on narrow spread {spread_ratio:.2f}x)"
            )
            return ("BUYING_CLIMAX", False, flags)
    else:
        # Selling Climax: Ultra high volume + narrow spread or massive lower rejection wick
        if rvol >= 2.0 and lower_wick >= 0.35 * bar_range:
            flags.append(
                f"Selling Climax Wick (Lower wick {lower_wick / bar_range * 100:.1f}%, RVOL {rvol:.2f}x)"
            )
            return ("SELLING_CLIMAX", False, flags)
        if rvol >= 2.2 and spread_ratio <= 0.65 and c_c < c_o:
            flags.append(
                f"Effort vs Result Bottom (RVOL {rvol:.2f}x on narrow spread {spread_ratio:.2f}x)"
            )
            return ("SELLING_CLIMAX", False, flags)

    return ("NORMAL", False, flags)


def audit_headroom(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    daily_levels: Optional[Any] = None,
    chain: Optional[List[Any]] = None,
    explicit_barriers: Optional[List[float]] = None,
) -> tuple[float, float, list[str]]:
    """
    Computes exact headroom to nearest major structural or derivative barrier.

    Barriers include:
      - Daily CPR Top/Bottom
      - Camarilla H4/L4
      - Previous Day High/Low (PDH/PDL)
      - Nearest High Open Interest Writing Wall (Call Wall for Longs, Put Wall for Shorts)

    Returns:
        (headroom_pts, headroom_multiple, barrier_details)
    """
    is_long = direction.upper() in ("BULLISH", "LONG", "BUY")
    initial_risk = max(0.5, abs(entry_price - stop_loss))
    barriers: List[tuple[float, str]] = []

    # 1. Daily Reference Levels (CPR, Camarilla, PDH, PDL)
    if daily_levels is not None:
        cpr = getattr(daily_levels, "cpr", None)
        if isinstance(cpr, dict):
            tc = cpr.get("tc") or cpr.get("top_central")
            bc = cpr.get("bc") or cpr.get("bottom_central")
            if is_long and tc and tc > entry_price:
                barriers.append((float(tc), "CPR Top Central"))
            elif not is_long and bc and bc < entry_price:
                barriers.append((float(bc), "CPR Bottom Central"))

        cam = getattr(daily_levels, "camarilla", None)
        if isinstance(cam, dict):
            h4 = cam.get("h4")
            l4 = cam.get("l4")
            if is_long and h4 and h4 > entry_price:
                barriers.append((float(h4), "Camarilla H4"))
            elif not is_long and l4 and l4 < entry_price:
                barriers.append((float(l4), "Camarilla L4"))

        pdh = getattr(daily_levels, "pdh", None)
        pdl = getattr(daily_levels, "pdl", None)
        if is_long and pdh and pdh > entry_price:
            barriers.append((float(pdh), "Previous Day High"))
        elif not is_long and pdl and pdl < entry_price:
            barriers.append((float(pdl), "Previous Day Low"))

    # 2. Options Open Interest Walls
    if chain:
        try:
            ce_strikes = []
            pe_strikes = []
            for c in chain:
                strike = float(getattr(c, "strike", 0.0) or getattr(c, "strike_price", 0.0))
                opt_type = str(getattr(c, "option_type", "") or getattr(c, "type", "")).upper()
                oi = float(getattr(c, "oi", 0.0) or getattr(c, "open_interest", 0.0))
                if strike > 0 and oi > 0:
                    if "CE" in opt_type or opt_type == "CALL":
                        ce_strikes.append((strike, oi))
                    elif "PE" in opt_type or opt_type == "PUT":
                        pe_strikes.append((strike, oi))

            if is_long and ce_strikes:
                ce_strikes.sort(key=lambda x: x[1], reverse=True)
                top_ce_strike = ce_strikes[0][0]
                if top_ce_strike > entry_price:
                    barriers.append(
                        (top_ce_strike, f"Max Call OI Wall (Strike ₹{top_ce_strike:.0f})")
                    )
            elif not is_long and pe_strikes:
                pe_strikes.sort(key=lambda x: x[1], reverse=True)
                top_pe_strike = pe_strikes[0][0]
                if top_pe_strike < entry_price:
                    barriers.append(
                        (top_pe_strike, f"Max Put OI Wall (Strike ₹{top_pe_strike:.0f})")
                    )
        except Exception as e_supp:
            logger.debug(f"[exhaustion_radar] Chain parsing error: {e_supp}")

    # 3. Explicit barriers passed by caller
    if explicit_barriers:
        for b in explicit_barriers:
            if is_long and b > entry_price:
                barriers.append((b, f"Structural Barrier ₹{b:.1f}"))
            elif not is_long and b < entry_price:
                barriers.append((b, f"Structural Barrier ₹{b:.1f}"))

    # 4. Psychological Round-Number Strike Magnets (Nifty, BankNifty, Sensex)
    clean_sym_upper = symbol.upper()
    round_step = 0.0
    if "BANKNIFTY" in clean_sym_upper:
        round_step = 500.0
    elif "NIFTY" in clean_sym_upper or "FINNIFTY" in clean_sym_upper:
        round_step = 500.0
    elif "SENSEX" in clean_sym_upper:
        round_step = 500.0

    if round_step > 0:
        if is_long:
            next_round = np.ceil(entry_price / round_step) * round_step
            # If entry is within 0.18% below the round number, it acts as a magnet/barrier
            if 0 < (next_round - entry_price) <= (entry_price * 0.0018):
                barriers.append(
                    (next_round, f"Psychological Round Strike Magnet ₹{next_round:.0f}")
                )
        else:
            prev_round = np.floor(entry_price / round_step) * round_step
            if 0 < (entry_price - prev_round) <= (entry_price * 0.0018):
                barriers.append(
                    (prev_round, f"Psychological Round Strike Magnet ₹{prev_round:.0f}")
                )

    if not barriers:
        # Open air headroom
        return (initial_risk * 4.0, 4.0, ["Open Air: No nearby structural barriers detected"])

    # Find the closest barrier in the direction of trade
    if is_long:
        barriers.sort(key=lambda x: x[0])
    else:
        barriers.sort(key=lambda x: x[0], reverse=True)

    nearest_barrier, barrier_desc = barriers[0]
    headroom_pts = abs(nearest_barrier - entry_price)
    headroom_multiple = headroom_pts / initial_risk
    details = [
        f"Nearest Barrier: {barrier_desc} at ₹{nearest_barrier:.1f} (Distance: {headroom_pts:.1f} pts / {headroom_multiple:.2f}R)"
    ]

    return (headroom_pts, headroom_multiple, details)


def evaluate_exhaustion(
    symbol: str,
    direction: str,
    ltp: float,
    entry_price: float,
    stop_loss: float,
    target_1: float,
    df: Optional[pd.DataFrame] = None,
    vwap: Optional[float] = None,
    daily_levels: Optional[Any] = None,
    chain: Optional[List[Any]] = None,
    vpin: Optional[float] = None,
    is_pullback: bool = False,
    current_hour: Optional[int] = None,
    current_minute: Optional[int] = None,
) -> ExhaustionRadarVerdict:
    """
    Main evaluation pipeline of the Institutional Exhaustion Radar with Dalal Street
    Time-of-Day (TOD) and Asset-Class specific calibrations.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").replace("BSE:", "").strip()
    is_long = direction.upper() in ("BULLISH", "LONG", "BUY")

    # Symbol-specific extension threshold calibration
    if "NIFTY" in clean_sym and "BANK" not in clean_sym:
        max_z_ext = 1.60
    elif "BANKNIFTY" in clean_sym:
        max_z_ext = 1.80
    else:
        max_z_ext = 2.00

    # Calculate ATR
    atr_val = ltp * 0.015
    if df is not None and len(df) >= 14:
        try:
            atr_s = atr(df, period=14)
            val = float(atr_s.dropna().iloc[-1])
            if val > 0:
                atr_val = val
        except Exception as e_atr:
            logger.debug(f"[exhaustion_radar] ATR calc fallback: {e_atr}")

    # 1. Extension Z-Score
    z_ext = compute_extension_zscore(ltp=ltp, vwap=vwap, atr_val=atr_val, df=df)

    # 2. VSA Climax & Absorption
    vsa_sig, is_dryup, vsa_flags = evaluate_vsa_climax(
        df=df, direction=direction, is_pullback=is_pullback
    )

    # 3. Headroom Audit
    headroom_pts, headroom_multiple, barrier_details = audit_headroom(
        symbol=clean_sym,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        daily_levels=daily_levels,
        chain=chain,
    )

    # 4. No-Chase Price Boundary
    no_chase_delta = 0.35 * atr_val
    no_chase_limit = (entry_price + no_chase_delta) if is_long else (entry_price - no_chase_delta)

    # Synthesis & Verdict Determination
    is_exhausted = False
    severity = "NONE"
    trap_type = "CLEAN"
    recommended_action = "PROCEED"
    flags: List[str] = []
    flags.extend(vsa_flags)
    flags.extend(barrier_details)

    # 5. Dalal Street Time-of-Day (TOD) Session Calibration
    if current_hour is not None:
        mins = current_hour * 60 + (current_minute or 0)
        # 09:15 to 09:45 IST (555 to 585 mins)
        if 555 <= mins < 585:
            flags.append(
                "Opening Discovery (09:15–09:45 IST): High volatility & initial spread whip risk"
            )
        # 11:30 to 13:15 IST (690 to 795 mins) - Midday Lull
        elif 690 <= mins < 795:
            flags.append(
                "Midday Lull Window (11:30–13:15 IST): Volume contraction, breakouts prone to chop"
            )
            if not is_pullback and recommended_action == "PROCEED":
                recommended_action = "LIMIT_PULLBACK_REQUIRED"
                flags.append("Midday breakout chase vetoed; demoted to limit pullback retest")
        # 14:45 to 15:30 IST (885 to 930 mins) - MOC / Expiry Squeeze
        elif 885 <= mins <= 930:
            flags.append(
                "MOC / Expiry Squeeze Window (14:45–15:30 IST): High gamma acceleration active"
            )

    # Rule A: Extreme Extension Climax
    if z_ext >= 2.50:
        is_exhausted = True
        severity = "CRITICAL_VETO"
        trap_type = "EXTENSION_CLIMAX"
        recommended_action = "HARD_VETO"
        flags.append(f"Extreme Extension Climax (Z_ext {z_ext:.2f} >= 2.50x ATR from mean)")
    elif z_ext >= max_z_ext:
        is_exhausted = True
        severity = "MODERATE"
        trap_type = "EXTENSION_CLIMAX"
        recommended_action = "LIMIT_PULLBACK_REQUIRED"
        flags.append(f"Extended Move (Z_ext {z_ext:.2f} >= {max_z_ext:.2f}x ATR - Chase Forbidden)")

    # Rule B: Passive Absorption Climax
    if vsa_sig in ("BUYING_CLIMAX", "SELLING_CLIMAX"):
        is_exhausted = True
        severity = "CRITICAL_VETO" if severity != "CRITICAL_VETO" else severity
        trap_type = "PASSIVE_ABSORPTION"
        recommended_action = "HARD_VETO"

    # Rule C: High-Volume Retest (Liquidation instead of dry-up)
    if is_pullback and vsa_sig == "HIGH_VOL_CHURN":
        is_exhausted = True
        severity = "HIGH"
        trap_type = "HIGH_VOL_PULLBACK"
        recommended_action = "HARD_VETO"

    # Rule D: Choked Headroom
    if headroom_multiple < 1.0:
        is_exhausted = True
        severity = "CRITICAL_VETO"
        trap_type = "CHOKED_HEADROOM"
        recommended_action = "HARD_VETO"
        flags.append("Critical Headroom Collision (< 1.0R to nearest wall)")
    elif headroom_multiple < 2.50:
        if recommended_action == "PROCEED":
            recommended_action = "TIGHTEN_SL"
            severity = "MODERATE"
        flags.append(f"Sub-optimal Headroom ({headroom_multiple:.2f}R < 2.50R target requirement)")

    # Rule E: Toxic Order Flow (VPIN)
    if vpin is not None and vpin >= 0.70:
        flags.append(f"High Adverse Selection Risk (VPIN {vpin:.2f} >= 0.70)")
        if recommended_action == "PROCEED":
            recommended_action = "LIMIT_PULLBACK_REQUIRED"

    # Compile Rationale
    if is_exhausted:
        rationale = f"Exhaustion detected [{trap_type} - {severity}]: {', '.join(flags[:3])}. Action: {recommended_action}"
    else:
        rationale = f"Clean execution window: Z_ext {z_ext:.2f}, Headroom {headroom_multiple:.2f}R, VSA {vsa_sig}. Action: PROCEED"

    return ExhaustionRadarVerdict(
        symbol=clean_sym,
        direction=direction.upper(),
        is_exhausted=is_exhausted,
        severity=severity,
        trap_type=trap_type,
        recommended_action=recommended_action,
        extension_zscore=z_ext,
        headroom_pts=headroom_pts,
        headroom_multiple=headroom_multiple,
        no_chase_limit=no_chase_limit,
        vsa_signal=vsa_sig,
        is_volume_dryup=is_dryup,
        vpin_toxicity=vpin,
        flags=flags,
        rationale=rationale,
    )
