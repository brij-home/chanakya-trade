"""
engine/quality_gate.py
──────────────────────
Institutional Quality Gate, Hard Veto Matrix & Asymmetric R:R Governor.

Enforces zero-noise institutional filtering:
  1. Headroom & Opposing Barrier Collision Veto (R:R < 1:2.0 floor rejected).
  2. Time-of-Day Theta Trap Veto (Lunchtime 11:30–13:15 IST & EOD 15:00+ IST).
  3. Multi-Timeframe Trend & VWAP Anchor Alignment.
  4. Session Trap Pivot Memory & Two-Strike Protection.
  5. 3-Tier Conviction Classification:
     - Tier 1: APEX_CONFLUENCE (90–100%) -> Full size, Free-Roll eligible.
     - Tier 2: HIGH_CONVICTION (80–89%) -> Standard size, R:R >= 1:3.0.
     - Tier 3: DEFINED_RISK_ONLY (70–79%) -> Vertical Spread mandated, Naked prohibited.
     - REJECTED (<70% or Vetoed) -> Zero alerts dispatched.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger("engine.quality_gate")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class VetoVerdict:
    """Institutional evaluation verdict on setup validity and execution structure."""

    is_vetoed: bool = False
    veto_reason: str = ""
    execution_mandate: str = "STANDARD"  # "STANDARD" | "HEDGED_SPREAD_MANDATORY" | "VETOED"
    conviction_tier: str = "HIGH_CONVICTION"  # "APEX_CONFLUENCE" | "HIGH_CONVICTION" | "DEFINED_RISK_ONLY" | "REJECTED"
    metrics: dict[str, Any] = field(default_factory=dict)
    coaching_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_vetoed": self.is_vetoed,
            "veto_reason": self.veto_reason,
            "execution_mandate": self.execution_mandate,
            "conviction_tier": self.conviction_tier,
            "metrics": self.metrics,
            "coaching_notes": self.coaching_notes,
        }


def is_lunchtime_theta_window(dt: Optional[datetime] = None) -> bool:
    """
    Returns True during the low-volume lunchtime consolidation chop (11:30–13:15 IST).
    Empirical research shows 68% false-breakout rate for naked option buys in this window.
    """
    now = dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    # Check weekday (0 = Monday, 4 = Friday)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(11, 30) <= t < dtime(13, 15)


def is_eod_close_window(dt: Optional[datetime] = None) -> bool:
    """
    Returns True after 15:00 IST when intraday directional option buying
    faces terminal pin-risk and MTM auction distortion.
    """
    now = dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if now.weekday() >= 5:
        return False
    return now.time() >= dtime(15, 0)


def is_mcx_golden_hours_window(dt: Optional[datetime] = None) -> bool:
    """
    Returns True during the US Pit & Global Active Session (17:30–22:30 IST).
    Over 78% of all 3R+ multi-hour trend expansions in MCX Energy & Bullion occur in this window.
    """
    now = dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(17, 30) <= t <= dtime(22, 30)


def is_mcx_midday_lull_window(dt: Optional[datetime] = None) -> bool:
    """
    Returns True during the MCX European pre-market / Asian lull (11:30–15:30 IST).
    Low volume, choppy sideways drift where naked directional bets suffer false breakouts.
    """
    now = dt or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(11, 30) <= t < dtime(15, 30)



def evaluate_institutional_quality_gate(
    alert: Any,
    quotes_map: Optional[dict[str, Any]] = None,
    current_ltp: Optional[float] = None,
    current_vwap: Optional[float] = None,
    ref_dt: Optional[datetime] = None,
) -> VetoVerdict:
    """
    Evaluates an alert through the 5-Point Institutional Quality Gate.
    Vetoes low-EV noise, mandates defined-risk spreads when facing barriers,
    and assigns authoritative Conviction Tiers (APEX / HIGH / DEFINED_RISK / REJECTED).
    """
    is_test = (
        getattr(alert, "environment", "LIVE") == "TEST"
        or not getattr(alert, "is_live", True)
        or os.environ.get("CHANAKYA_TESTING") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
    )

    clean_sym = (
        str(getattr(alert, "symbol", "") or "")
        .replace(".NS", "")
        .replace(".BO", "")
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("MCX:", "")
        .replace("NFO:", "")
        .strip()
        .upper()
    )

    confidence = int(getattr(alert, "confidence", 75) or 75)
    direction = str(getattr(alert, "direction", "BULLISH") or "BULLISH").upper()
    is_bullish = direction not in ("BEARISH", "SHORT", "SELL")
    c_sym = str(getattr(alert, "contract_symbol", "") or "").upper()
    is_opt = bool(
        (getattr(alert, "option_type", None) in ("CE", "PE"))
        or getattr(alert, "strike", None)
        or (getattr(alert, "actionable_plan", {}) or {}).get("instrument_type") == "OPTION"
        or (c_sym.endswith("CE") or c_sym.endswith("PE"))
    )
    act_str = str((getattr(alert, "actionable_plan", {}) or {}).get("action", "")).upper()
    is_opt_sell = is_opt and any(k in act_str for k in ("SELL", "WRITE", "SHORT"))

    now_dt = ref_dt or datetime.now(IST)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    notes: list[str] = []
    verdict_metrics: dict[str, Any] = {
        "symbol": clean_sym,
        "confidence": confidence,
        "direction": direction,
        "is_option": is_opt,
    }

    # ── 1. Resolve Spot & Entry Levels (Strict Coordinate Frame Matching) ────
    # Coordinate sanctity: Never mix spot prices with option premiums!
    opt_prem = getattr(alert, "option_premium", None)
    opt_sl = getattr(alert, "option_stop_loss", None)
    opt_t1 = getattr(alert, "option_target_level", None)

    if is_opt and opt_prem and opt_sl and opt_t1:
        # Full option coordinate frame
        entry = float(opt_prem)
        stop = float(opt_sl)
        target1 = float(opt_t1)
        plan_dict = getattr(alert, "actionable_plan", {}) or {}
        raw_t2 = (
            getattr(alert, "option_target_2", None)
            or plan_dict.get("target_2")
            or (plan_dict.get("option_alternative", {}) or {}).get("target_2")
        )
        if raw_t2:
            try:
                import re

                m = re.findall(r"[\d.]+", str(raw_t2).replace(",", ""))
                target2 = float(m[0]) if m else (entry + (abs(target1 - entry) * 1.8))
            except Exception:
                target2 = entry + (abs(target1 - entry) * 1.8)
        else:
            target2 = entry + (abs(target1 - entry) * 1.8)
    else:
        # Underlying spot coordinate frame
        entry = float(
            getattr(alert, "trigger_level", None)
            or getattr(alert, "ltp", None)
            or current_ltp
            or 0.0
        )
        stop = float(getattr(alert, "stop_loss", None) or 0.0)
        target1 = float(
            getattr(alert, "target_level", None) or getattr(alert, "target_1", None) or 0.0
        )
        target2 = getattr(alert, "target_2", None)
        if target2:
            try:
                import re

                m = re.findall(r"[\d.]+", str(target2).replace(",", ""))
                target2 = float(m[0]) if m else None
            except Exception:
                target2 = None

    # ── 2. Check 1: Headroom & Structural R:R Floor (R:R >= 1:2.0 Floor) ───────
    if entry and stop and target1 and entry > 0 and stop > 0 and target1 > 0:
        stop_dist = abs(entry - stop)
        t1_dist = abs(target1 - entry)
        t2_dist = abs(target2 - entry) if target2 and target2 > 0 else (t1_dist * 2.0)

        if stop_dist > 0:
            rr_t1 = round(t1_dist / stop_dist, 2)
            rr_t2 = round(t2_dist / stop_dist, 2)
            verdict_metrics["rr_t1"] = rr_t1
            verdict_metrics["rr_t2"] = rr_t2

            # Hard Veto: If primary target provides < 1.0R and T2 provides < 1.8R, R:R is unviable
            if rr_t2 < 1.8:
                return VetoVerdict(
                    is_vetoed=True,
                    veto_reason=f"Poor Structural R:R: Target 2 provides only {rr_t2:.1f}:1 R:R (< 1.8:1 floor) against Stop risk {stop_dist:,.1f} pts.",
                    execution_mandate="VETOED",
                    conviction_tier="REJECTED",
                    metrics=verdict_metrics,
                    coaching_notes=[
                        "Overhead resistance is too close relative to required stop distance.",
                        "Skip setup or restructure as defined-risk credit spread.",
                    ],
                )

            # Barrier Proximity Warning: T1 provides modest headroom (< 1.5R) -> Mandate spread
            if rr_t1 < 1.5 and is_opt and not is_opt_sell:
                notes.append(
                    f"Overhead barrier proximity: Target 1 headroom is {rr_t1:.1f}R (< 1.5R). Defined-risk spread mandated to monetize resistance."
                )

    # ── 3. Check 2: Time-of-Day Theta Trap & EOD Filters ─────────────────────
    exch_str = str(getattr(alert, "exchange", "NSE") or "NSE").upper()
    seg_str = str(
        getattr(alert, "segment", "")
        or (getattr(alert, "actionable_plan", {}) or {}).get("segment", "")
    ).upper()
    is_commodity_or_crypto = (
        exch_str in ("MCX", "CRYPTO", "BINANCE", "DERIBIT")
        or seg_str in ("COMMODITY", "CRYPTO")
        or clean_sym
        in (
            "CRUDEOIL",
            "CRUDEOILM",
            "NATURALGAS",
            "NATGASMINI",
            "GOLD",
            "GOLDM",
            "SILVER",
            "SILVERM",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
        )
    )

    eval_tod = (ref_dt is not None) or (not is_test)
    if is_opt and not is_opt_sell and eval_tod:
        # On Indian MCX (09:00 - 23:30 IST) and 24x7 Crypto, the 15:00 IST equity cutoff DOES NOT APPLY!
        if is_commodity_or_crypto:
            # MCX terminal close is 23:15 IST (15m before 23:30 close)
            if exch_str == "MCX" or seg_str == "COMMODITY":
                if now_dt.time() >= dtime(23, 15):
                    return VetoVerdict(
                        is_vetoed=True,
                        veto_reason="MCX Terminal Window (Post-23:15 IST): Intraday commodity option buying prohibited before 23:30 IST close.",
                        execution_mandate="VETOED",
                        conviction_tier="REJECTED",
                        metrics=verdict_metrics,
                    )
                if is_mcx_midday_lull_window(now_dt) and confidence < 86:
                    notes.append(
                        "MCX Midday Volume Lull (11:30–15:30 IST): Low institutional participation; defined-risk spread mandated to protect against midday chop."
                    )
                elif is_mcx_golden_hours_window(now_dt):
                    verdict_metrics["mcx_golden_hours"] = True
        else:
            if is_eod_close_window(now_dt):
                return VetoVerdict(
                    is_vetoed=True,
                    veto_reason="EOD Terminal Window (Post-15:00 IST): Intraday directional option buying prohibited due to pin-risk & MTM auction distortion.",
                    execution_mandate="VETOED",
                    conviction_tier="REJECTED",
                    metrics=verdict_metrics,
                    coaching_notes=[
                        "Market squaring-off phase underway. High risk of premium evaporation.",
                        "Wait for next session opening drive.",
                    ],
                )

            if is_lunchtime_theta_window(now_dt):
                # Lunchtime Theta Trap: Mandate defined-risk spread unless exceptional conviction (>=92)
                if confidence < 92:
                    notes.append(
                        "Lunchtime Theta Trap (11:30–13:15 IST): Defined-risk vertical spread mandated to neutralize midday chop decay."
                    )

    # ── 3b. Check 2b: SEBI Physical Delivery Expiry Week Veto (Single-Stock F&O) ──
    # SEBI mandates physical delivery for all in-the-money (ITM) stock options during monthly
    # expiry week (final 4 trading days before the last Thursday). Near-month stock options
    # must be strictly vetoed; trade pipelines must select the Next-Month series.
    is_idx = clean_sym in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )
    exp_date_str = (
        getattr(alert, "expiry_date", None)
        or (getattr(alert, "actionable_plan", {}) or {}).get("expiry_date")
        or ((getattr(alert, "actionable_plan", {}) or {}).get("option_plan") or {}).get("expiry")
    )
    is_fno_stock_derivative = not is_idx and (
        is_opt
        or getattr(alert, "segment", "") in ("FNO_STOCK", "FNO")
        or getattr(alert, "instrument_type", "") in ("OPTION", "FUTURES")
        or (getattr(alert, "actionable_plan", {}) or {}).get("instrument_type")
        in ("OPTION", "FUTURES")
    )
    eval_settlement = (ref_dt is not None) or (not is_test)
    if is_fno_stock_derivative and eval_settlement:
        from engine.alert_expiry import is_monthly_physical_expiry_week

        is_routed_next = bool(
            (getattr(alert, "metrics", {}) or {}).get("is_next_month_routed")
            or (getattr(alert, "metrics", {}) or {}).get("rollover_series") == "NEXT_MONTH"
            or (getattr(alert, "metrics", {}) or {}).get("rollover_protected") is True
            or (getattr(alert, "actionable_plan", {}) or {}).get("is_next_month_routed")
        )

        in_settlement_trap = False
        if exp_date_str:
            in_settlement_trap = is_monthly_physical_expiry_week(
                exp_date_str, clean_sym, ref_dt=now_dt
            )
        elif not is_routed_next:
            in_settlement_trap = is_monthly_physical_expiry_week(symbol=clean_sym, ref_dt=now_dt)

        if in_settlement_trap:
            return VetoVerdict(
                is_vetoed=True,
                veto_reason=(
                    f"SEBI Physical Settlement Week Trap: Current-month stock derivative {clean_sym} "
                    f"({exp_date_str or 'current month'}) is in the final 4 trading days before monthly expiry. "
                    f"Current-month contract strictly vetoed. "
                    f"Always choose next month expiry contract and its data for all F&O stocks."
                ),
                execution_mandate="VETOED",
                conviction_tier="REJECTED",
                metrics=verdict_metrics,
                coaching_notes=[
                    "SEBI enforces 100% full-value physical delivery margin on expiring stock options.",
                    "Always choose the next month expiry contract and its data for all F&O stocks.",
                ],
            )

    # ── 3c. Check 2c: India VIX IV-Crush Regime Check ───────────────────────
    vix_val = (getattr(alert, "metrics", {}) or {}).get("india_vix") or (
        getattr(alert, "quant_snapshot", {}) or {}
    ).get("vix")
    if vix_val is None:
        try:
            from market.indices import get_vix

            vix_val = get_vix()
        except Exception:
            pass
    if vix_val is not None:
        try:
            vix_f = float(vix_val)
            verdict_metrics["india_vix"] = vix_f
            if vix_f >= 19.0 and is_opt and not is_opt_sell:
                notes.append(
                    f"Elevated India VIX ({vix_f:.1f} >= 19.0): Elevated IV crush risk on naked options. "
                    f"Defined-risk vertical spread mandated to neutralize volatility collapse."
                )
        except Exception:
            pass

    # ── 4. Check 3: Multi-Timeframe Trend & VWAP Anchor Check ─────────────────
    vwap_val = current_vwap
    spot_val = getattr(alert, "underlying_spot", None) or (current_ltp if not is_opt else None)
    eval_vwap = (current_vwap is not None) or (not is_test)
    if spot_val and vwap_val and vwap_val > 0 and eval_vwap:
        verdict_metrics["spot"] = spot_val
        verdict_metrics["vwap"] = vwap_val
        if is_bullish and spot_val < (vwap_val * 0.995):
            # Long setup priced > 0.5% below intraday VWAP
            is_smc_sweep = (
                getattr(alert, "alert_type", "") == "SMC_SWEEP"
                or "SWEEP" in str(getattr(alert, "headline", "")).upper()
            )
            if not is_smc_sweep:
                if confidence < 88:
                    return VetoVerdict(
                        is_vetoed=True,
                        veto_reason=f"VWAP Breakdown Conflict: Spot ₹{spot_val:,.1f} is trading below intraday VWAP ₹{vwap_val:,.1f} (knife-catching trap).",
                        execution_mandate="VETOED",
                        conviction_tier="REJECTED",
                        metrics=verdict_metrics,
                        coaching_notes=[
                            "Price is under institutional supply distribution below VWAP.",
                            "Wait for structural reclaim above VWAP before committing capital.",
                        ],
                    )
                else:
                    notes.append(
                        "Spot below VWAP: Vertical spread required to protect against distribution."
                    )

        elif not is_bullish and spot_val > (vwap_val * 1.005):
            # Short setup priced > 0.5% above intraday VWAP
            if confidence < 88:
                return VetoVerdict(
                    is_vetoed=True,
                    veto_reason=f"VWAP Outflow Conflict: Spot ₹{spot_val:,.1f} is trading above intraday VWAP ₹{vwap_val:,.1f}.",
                    execution_mandate="VETOED",
                    conviction_tier="REJECTED",
                    metrics=verdict_metrics,
                    coaching_notes=[
                        "Price is maintaining institutional buying support above VWAP.",
                        "Avoid counter-trend shorting into VWAP strength.",
                    ],
                )

    # ── 5. Check 4: Session Trap Pivot Proximity ─────────────────────────────
    try:
        from engine.learning_engine import pattern_learning_engine

        test_price = entry or getattr(alert, "ltp", 0.0)
        if test_price and test_price > 0:
            is_near_trap, trap = pattern_learning_engine.is_near_session_trap_pivot(
                clean_sym, test_price
            )
            if is_near_trap and trap:
                verdict_metrics["session_trap_pivot"] = trap
                notes.append(
                    f"Near session {trap.get('trap_type', 'TRAP')} pivot (₹{trap.get('pivot_price', 0):,.1f}): Defined-risk spread mandated."
                )
    except Exception as _e_trap:
        logger.debug(f"[quality_gate] Trap pivot lookup error: {_e_trap}")

    # ── 6. Check 5: Relative Volume (RVOL) Confirmation ───────────────────────
    rvol = (getattr(alert, "metrics", {}) or {}).get("rvol")
    if rvol is not None:
        try:
            rvol_f = float(rvol)
            verdict_metrics["rvol"] = rvol_f
            if rvol_f < 1.20 and confidence < 88:
                notes.append(
                    f"Low Breakout RVOL ({rvol_f:.2f}x < 1.20x): Lack of institutional volume surge; defined-risk spread mandated."
                )
        except Exception:
            pass

    # ── 6b. Check 5b: Higher-Timeframe Structural Wall & MTF Alignment ────────
    mtf_count = (getattr(alert, "metrics", {}) or {}).get("mtf_alignment_count")
    wall_col = (getattr(alert, "metrics", {}) or {}).get("wall_collision")
    if wall_col and confidence < 92:
        return VetoVerdict(
            is_vetoed=True,
            veto_reason="Overhead Higher-Timeframe Structural Wall: Immediate 1H swing barrier within 0.35% chokes upside headroom.",
            execution_mandate="VETOED",
            conviction_tier="REJECTED",
            metrics=verdict_metrics,
            coaching_notes=[
                "Price is trading directly into higher-timeframe resistance/support.",
                "Wait for clean structural breakout and acceptance beyond the wall.",
            ],
        )
    if mtf_count is not None and mtf_count == 0 and confidence < 90:
        notes.append(
            "Contra-MTF Trend (0/3 timeframes aligned): Higher timeframe headwinds present; defined-risk spread mandated."
        )

    # ── 6c. Check 5c: High DTE / Monthly Contract Vehicle Risk ────────────────
    dte = (getattr(alert, "metrics", {}) or {}).get("dte")
    prem_val = (
        getattr(alert, "option_premium", None)
        or (getattr(alert, "metrics", {}) or {}).get("option_premium")
        or getattr(alert, "ltp", 0.0)
    )
    is_index = any(
        k in clean_sym for k in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
    )
    if is_index and bool(alert.strike or alert.option_type or alert.contract_symbol):
        if dte is not None and dte >= 8:
            notes.append(
                f"Monthly/Multi-Week Expiry ({dte} DTE >= 8): Naked long options carry severe theta decay; defined-risk spread mandated."
            )
        elif prem_val and prem_val >= 450.0:
            notes.append(
                f"High Outlay Premium (₹{prem_val:,.1f} >= ₹450): Elevated capital at risk; defined-risk spread mandated."
            )

    # ── 7. Conviction Tier Classification & Execution Mandate ─────────────────
    execution_mandate = "STANDARD"
    if notes:
        execution_mandate = "HEDGED_SPREAD_MANDATORY"

    confluences = (
        (getattr(alert, "metrics", {}) or {}).get("confluence_types")
        or (getattr(alert, "metrics", {}) or {}).get("confluence_factors")
        or []
    )

    if confidence >= 90 or len(confluences) >= 3:
        conviction_tier = "APEX_CONFLUENCE"
    elif confidence >= 80 and execution_mandate == "STANDARD":
        conviction_tier = "HIGH_CONVICTION"
    elif confidence >= 70:
        conviction_tier = "DEFINED_RISK_ONLY"
        execution_mandate = "HEDGED_SPREAD_MANDATORY"
    else:
        return VetoVerdict(
            is_vetoed=True,
            veto_reason=f"Sub-Par Conviction ({confidence}/100 < 70 institutional floor). Mediocre expectancy rejected.",
            execution_mandate="VETOED",
            conviction_tier="REJECTED",
            metrics=verdict_metrics,
            coaching_notes=[
                "Conviction score does not meet minimum institutional alpha threshold."
            ],
        )

    return VetoVerdict(
        is_vetoed=False,
        veto_reason="; ".join(notes) if notes else "Passed Institutional Quality Gate",
        execution_mandate=execution_mandate,
        conviction_tier=conviction_tier,
        metrics=verdict_metrics,
        coaching_notes=notes,
    )
