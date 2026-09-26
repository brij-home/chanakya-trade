"""
Options Gamma Blast detector (Early Warning & Ignited triggers on call/put writer capitulation).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_expiry import classify_expiry_type
from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert

import time

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Short-term strike snapshot cache: contract_key -> (timestamp, oi, volume)
_STRIKE_OI_SNAPSHOTS: dict[str, tuple[float, int, int]] = {}


def compute_gamma_conviction(
    *,
    is_index: bool,
    vol_oi_ratio: float,
    oi_change: int,
    oi_chg_pct: float,
    pchange: float,
    volume: int,
    c_vol: float,
    stage: str,
    strike_diff_pct: float,
    sweep_active: bool,
    tp: Any = None,
    spread_pct: Optional[float] = None,
    is_wall_breakout: bool = False,
    is_physical_week: bool = False,
) -> int:
    """
    Computes institutional conviction score (60 - 98) for Gamma Blast setups.

    Quality Pillars:
      1. Base foundation: 62 pts
      2. True Writer Capitulation (ΔOI < 0): up to +18 pts based on % OI shedding
         - When ΔOI >= 0 (writers adding resistance): capped at max +6 pts only if pchange > 0
      3. Turnover Intensity (vol_oi_ratio): up to +15 pts
      4. Absolute Volume & Liquidity depth: up to +8 pts (filters illiquid contracts)
      5. Stage verification: +6 pts for IGNITED vs preliminary early warning
      6. Moneyness / Gamma Convexity sweet spot (ATM <= 0.35%): +5 pts, (Near-ATM <= 0.70%): +2 pts
      7. SMC Structural Anchor (PDL/PDH sweep + wick rejection): +6 pts
      8. Trade Plan Structural Asymmetry (R:R >= 1:2.0 viable): +5 pts
      9. Major OI Wall Breakout (+6 pts for breaking through max OI wall with negative ΔOI)
      10. Order Book Spread Audit (+3 pts for tight spread <= 1.0%, -4 pts for wide > 2.5%)
      11. SEBI Physical Settlement Week Friction (-4 pts for single stock near-month unless explosive)
    """
    score = 62.0

    # 1. Writer capitulation vs supply resistance
    if oi_change < 0:
        # True writer panic/covering
        score += min(18.0, abs(oi_chg_pct) * 0.8)
    else:
        # Writers adding supply: only award if buyers are aggressively absorbing
        score += min(6.0, max(0.0, pchange * 0.5))

    # 2. Turnover intensity (vol / OI ratio)
    score += min(15.0, max(0.0, (vol_oi_ratio - 0.5) * 6.0))

    # 3. Absolute volume depth (institutional footprint)
    if is_index:
        score += min(8.0, volume / 10000.0)
    else:
        score += min(8.0, c_vol / 80.0)

    # 4. Stage verification
    if stage == "IGNITED":
        score += 6.0

    # 5. Moneyness (ATM gamma sweet spot has maximum gamma sensitivity)
    abs_diff = abs(strike_diff_pct)
    if abs_diff <= 0.35:
        score += 5.0
    elif abs_diff <= 0.70:
        score += 2.0

    # 6. SMC structural sweep
    if sweep_active:
        score += 6.0

    # 7. Trade plan asymmetry viability
    if tp and getattr(tp, "is_asymmetry_viable", False):
        score += 5.0

    # 8. Major OI Wall Breakout
    if is_wall_breakout:
        score += 6.0

    # 9. Bid-ask spread audit
    if spread_pct is not None and spread_pct > 0:
        if spread_pct <= 1.0:
            score += 3.0
        elif spread_pct > 2.5:
            score -= 4.0

    # 10. Physical settlement week penalty (single stock near-month)
    if is_physical_week and vol_oi_ratio < 2.0:
        score -= 4.0

    return min(98, max(60, int(round(score))))


def detect_gamma_blast(
    underlying: str,
    spot: float,
    chain: list[Any],
    vwap: Optional[float] = None,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    prev_day_high: Optional[float] = None,
    prev_day_low: Optional[float] = None,
) -> list[AutoAlert]:
    """
    Evaluates options chain for explosive Gamma Blast early-warning and ignite triggers.

    Leading Indicators:
      - Negative Change in OI (Call/Put writers closing positions in panic).
      - Volume / OI Ratio >= 1.8x (massive intraday turnover vs accumulated open interest).
      - Spot price reclaiming or breaking away from intraday VWAP.
      - ATM & near-OTM strike proximity (within ±1.5% of spot).
      - PDH/PDL Liquidity Sweep + Wick Rejection (institutional supply/demand OB reversal).

    VWAP Gate Policy:
      - CE: spot must be >= vwap * 0.998 (spot holding or above VWAP = bullish).
      - PE: spot must be <= vwap * 1.008 (0.8% buffer — experts buy PEs at supply/OB rejection
            BEFORE spot actually breaks down; hard reject was causing systematic PE misses).
      - PDH Sweep bypass: if spot tagged day_high and rejected with a wick, the VWAP gate
            is lifted for PE — structural reversal signal supersedes VWAP position.
    """
    if not chain or spot <= 0:
        return []

    alerts: list[AutoAlert] = []
    now_dt = datetime.now(IST)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    is_opening_drive = now_dt.hour == 9 and now_dt.minute <= 45
    clean_sym = (
        underlying.upper().replace(".NS", "").replace("NSE:", "").replace("NFO:", "").strip()
    )

    # Institutional Liquidity & Significance Filters (SEBI / F&O standard):
    is_index = underlying.upper() in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "BANKEX",
    )
    from engine.position_sizer import get_lot_size

    lot_sz = get_lot_size(underlying) or 1
    is_bse = underlying.upper() in ("SENSEX", "BANKEX")
    opt_exchange = "BFO" if is_bse else "NFO"

    ce_contracts = [c for c in chain if getattr(c, "option_type", "") == "CE"]
    pe_contracts = [c for c in chain if getattr(c, "option_type", "") == "PE"]

    effective_vwap = vwap if (vwap and vwap > 0) else spot

    # ── PDH / PDL Liquidity Sweep Detection (Fix 3) ────────────────────────────
    # Detects when spot has swept previous session or intraday extreme and rejected/bounced
    # — the highest-conviction SMC reversal signal.
    # An active sweep REQUIRES:
    #   1. Extreme was tested (within 0.15% or pierced)
    #   2. Spot has actively bounced/pulled back >= 0.10% (cannot be resting at the extreme tick)
    #   3. Spot is holding on the safe side of the key reference level
    _spot_bounce_from_low = ((spot - day_low) / max(1.0, spot) * 100) if (day_low and spot >= day_low) else 0.0
    _spot_pullback_from_high = ((day_high - spot) / max(1.0, spot) * 100) if (day_high and spot <= day_high) else 0.0

    _pdl_tested = bool(
        prev_day_low and prev_day_low > 0
        and day_low and day_low <= (prev_day_low * 1.002)
        and (prev_day_low - day_low) / prev_day_low * 100 <= 0.40
    ) or bool(
        day_low and day_low > 0 and (spot - day_low) / max(1.0, spot) * 100 >= 0.15
    )

    _pdl_sweep_active = bool(
        _pdl_tested
        and _spot_bounce_from_low >= 0.10  # Requires verified bounce off session low!
        and (not prev_day_low or spot >= prev_day_low * 0.999)  # Reclaiming back above PDL
    )

    _pdh_tested = bool(
        prev_day_high and prev_day_high > 0
        and day_high and day_high >= (prev_day_high * 0.998)
        and (day_high - prev_day_high) / prev_day_high * 100 <= 0.40
    ) or bool(
        day_high and day_high > 0 and (day_high - spot) / max(1.0, spot) * 100 >= 0.15
    )

    _pdh_sweep_active = bool(
        _pdh_tested
        and _spot_pullback_from_high >= 0.10  # Requires verified rejection off session high!
        and (not prev_day_high or spot <= prev_day_high * 1.001)  # Holding back below PDH
    )

    # ── PDL / PDH Proximity Gates (Previous Session Levels) ─────────────────────
    # When current spot is very close to yesterday's key levels, the dynamics change:
    #
    # Near PDL (Previous Day Low):
    #   → Buying PE risks hitting a major demand wall right below → suppress PE (opposing demand)
    #   → CE bounce off PDL is a high-probability structural reversal → boost CE conviction
    #
    # Near PDH (Previous Day High):
    #   → Buying CE risks hitting a major supply wall right above → suppress CE (opposing supply)
    #   → PE rejection at PDH is a high-probability structural reversal → boost PE conviction
    #
    # Bypass: If a sweep is already confirmed (_pdl_sweep_active / _pdh_sweep_active),
    # these gates are skipped — the sweep itself confirms directional intent.
    _PDL_PROXIMITY_THRESHOLD = 0.0025  # 0.25% of spot = "at PDL"
    _PDH_PROXIMITY_THRESHOLD = 0.0025  # 0.25% of spot = "at PDH"

    _near_pdl = bool(
        prev_day_low
        and prev_day_low > 0
        and spot >= prev_day_low  # spot is above PDL (not broken yet)
        and (spot - prev_day_low) / spot <= _PDL_PROXIMITY_THRESHOLD
    )
    _near_pdh = bool(
        prev_day_high
        and prev_day_high > 0
        and spot <= prev_day_high  # spot is below PDH (not broken yet)
        and (prev_day_high - spot) / spot <= _PDH_PROXIMITY_THRESHOLD
    )

    # For PE: being at PDL means the demand wall is right below — extra headroom risk
    # Bypass when _pdl_sweep_active (spot has already swept and bounced: that IS the CE setup)
    _pe_near_pdl_suppressed = _near_pdl and not _pdl_sweep_active

    # For CE: being at PDH means the supply wall is right above — extra headroom risk
    # Bypass when _pdh_sweep_active (spot has already swept and wicked: that IS the PE setup)
    _ce_near_pdh_suppressed = _near_pdh and not _pdh_sweep_active

    if _near_pdl and is_index:
        logger.debug(
            f"[GammaBlast] {underlying}: Near PDL ₹{prev_day_low:,.1f} "  # type: ignore[str-format]
            f"(spot ₹{spot:,.1f}, gap {((spot - prev_day_low) / spot * 100):.3f}%). "
            f"PE suppressed={'Yes' if _pe_near_pdl_suppressed else 'No (sweep active)'}. "
            f"CE conviction boosted +6."
        )
    if _near_pdh and is_index:
        logger.debug(
            f"[GammaBlast] {underlying}: Near PDH ₹{prev_day_high:,.1f} "  # type: ignore[str-format]
            f"(spot ₹{spot:,.1f}, gap {((prev_day_high - spot) / spot * 100):.3f}%). "
            f"CE suppressed={'Yes' if _ce_near_pdh_suppressed else 'No (sweep active)'}. "
            f"PE conviction boosted +6."
        )

    # ── Major Open Interest Concentration Walls ─────────────────────────────────
    # The strike with maximum Call OI acts as an institutional resistance ceiling.
    # The strike with maximum Put OI acts as an institutional support floor.
    max_ce_oi_strike = 0.0
    max_ce_oi_val = 0
    max_ce_oi_chg = 0
    for c_obj in ce_contracts:
        c_oi_val = int(getattr(c_obj, "oi", 0) or 0)
        if c_oi_val > max_ce_oi_val:
            max_ce_oi_val = c_oi_val
            max_ce_oi_strike = float(getattr(c_obj, "strike", 0.0) or 0.0)
            max_ce_oi_chg = int(getattr(c_obj, "oi_change", 0) or 0)

    max_pe_oi_strike = 0.0
    max_pe_oi_val = 0
    max_pe_oi_chg = 0
    for p_obj in pe_contracts:
        p_oi_val = int(getattr(p_obj, "oi", 0) or 0)
        if p_oi_val > max_pe_oi_val:
            max_pe_oi_val = p_oi_val
            max_pe_oi_strike = float(getattr(p_obj, "strike", 0.0) or 0.0)
            max_pe_oi_chg = int(getattr(p_obj, "oi_change", 0) or 0)

    # ── Analyze CALL Gamma Blast (Bullish Upside Explosion) ───
    for c in ce_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        # Delta-Gated Sweet-Spot Filter: Indices demand ATM/Near-ATM (<= 0.6%), equities allow up to 1.2%
        max_call_otm = 0.6 if is_index else 1.2
        max_call_itm = 0.4 if is_index else 0.8
        if not (-max_call_itm <= strike_diff_pct <= max_call_otm):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}CE")

        if not is_index and lot_sz > 1:
            c_oi = (oi / lot_sz) if oi > lot_sz * 2.5 else oi
            c_vol = (volume / lot_sz) if volume > lot_sz * 2.5 else volume
            c_oi_chg = (
                (abs(oi_change) / lot_sz) if abs(oi_change) > lot_sz * 2.5 else abs(oi_change)
            )
            min_strike_oi = 150 if is_opening_drive else 100
            min_abs_oi_change = 30 if is_opening_drive else 20
            min_volume = 120 if is_opening_drive else 50
            min_exp_oi_chg = 80 * lot_sz
            min_turnover_vol = 150 * lot_sz
        else:
            c_oi = oi
            c_vol = volume
            c_oi_chg = abs(oi_change)
            if clean_sym in ("SENSEX", "BANKEX"):
                min_strike_oi = 500 if is_opening_drive else 800
                min_abs_oi_change = 60 if is_opening_drive else 100
                min_volume = 400 if is_opening_drive else 1000
                min_exp_oi_chg = 300
                min_turnover_vol = 1200
            elif clean_sym == "MIDCPNIFTY":
                min_strike_oi = 1000 if is_opening_drive else 2000
                min_abs_oi_change = 60 if is_opening_drive else 120
                min_volume = 600 if is_opening_drive else 1500
                min_exp_oi_chg = 400
                min_turnover_vol = 2500
            elif clean_sym == "FINNIFTY":
                min_strike_oi = 3000 if is_opening_drive else 5000
                min_abs_oi_change = 300 if is_opening_drive else 600
                min_volume = 1200 if is_opening_drive else 3000
                min_exp_oi_chg = 2000
                min_turnover_vol = 5000
            else:
                # NIFTY & BANKNIFTY
                min_strike_oi = 8000 if is_opening_drive else 12000
                min_abs_oi_change = 1200 if is_opening_drive else 2500
                min_volume = 2500 if is_opening_drive else 8000
                min_exp_oi_chg = 8000
                min_turnover_vol = 12000

        if c_oi < min_strike_oi or c_vol < min_volume:
            continue

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = (
            round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0
        )
        pchange = float(getattr(c, "pchange", 0.0) or 0.0)

        exp_date = getattr(c, "expiry", "") or None
        is_phys_week = False
        if exp_date:
            try:
                exp_str = str(exp_date).split("T")[0].strip()
                exp_dt = None
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if exp_dt:
                    today_ist = datetime.now(IST).date()
                    dte_days = (exp_dt - today_ist).days
                    max_gamma_dte = (
                        8 if (is_index and clean_sym == "NIFTY") else (16 if is_index else 35)
                    )
                    if dte_days > max_gamma_dte:
                        continue
                    # 0DTE Afternoon Theta Decay Guard (Post 13:00 IST):
                    # On expiry day (dte_days == 0), OTM options decay rapidly due to hyper-accelerated theta.
                    # Ban naked OTM options after 13:00 IST; strictly require ATM or ITM contracts!
                    # Big Opportunity Bypass: allow near-OTM (up to 0.35%) ONLY if massive writer panic unwind
                    if dte_days == 0 and now_dt.hour >= 13:
                        is_hero_unwind = (
                            oi_change < 0 and abs(oi_chg_pct) >= 15.0 and vol_oi_ratio >= 2.0
                        )
                        if strike_diff_pct > 0.05 and not (
                            is_hero_unwind and strike_diff_pct <= 0.35
                        ):
                            continue
            except Exception:
                pass

            # SEBI Physical Delivery Expiry Week Guard for Single-Stock Options:
            if not is_index:
                try:
                    from engine.alert_expiry import is_monthly_physical_expiry_week

                    is_phys_week = is_monthly_physical_expiry_week(
                        str(exp_date), symbol=clean_sym, ref_dt=now_dt
                    )
                except Exception:
                    is_phys_week = False

        if is_phys_week and not is_index:
            # During physical expiry week, near-month single stock options have huge margin spikes (25%->100%).
            # Suppress sluggish early warnings: require vol_oi_ratio >= 1.4 or ignited momentum to prevent capital traps.
            if vol_oi_ratio < 1.4 and (volume < 300 * lot_sz) and pchange < 10.0:
                logger.debug(
                    f"[GammaBlast CE] Suppressed {contract_sym}: Low turnover during SEBI physical delivery week"
                )
                continue

        now_ts = time.time()
        c_key = f"{underlying}_{int(strike)}_CE"
        prior_snap = _STRIKE_OI_SNAPSHOTS.get(c_key)
        _STRIKE_OI_SNAPSHOTS[c_key] = (now_ts, oi, volume)

        short_term_unwind = False
        if prior_snap:
            p_ts, p_oi, _ = prior_snap
            dt_sec = max(1.0, now_ts - p_ts)
            if dt_sec <= 300.0:  # Within 5 minutes
                unwind_rate = ((oi - p_oi) / dt_sec) * 60.0  # contracts / min
                if (is_index and unwind_rate <= -1000) or (not is_index and unwind_rate <= -50):
                    short_term_unwind = True

        has_gamma_pchange = pchange >= 12.0 and volume >= (4000 if is_index else 200)
        is_high_volume_expansion = (
            vol_oi_ratio >= 1.8 and volume >= (8000 if is_index else 500) and pchange >= 4.5
        )
        if (
            c_oi_chg > 0
            and c_oi_chg < min_abs_oi_change
            and not has_gamma_pchange
            and not is_high_volume_expansion
            and not short_term_unwind
        ):
            continue
        if (
            c_oi_chg == 0
            and not short_term_unwind
            and not has_gamma_pchange
            and not is_high_volume_expansion
        ):
            continue

        is_oi_shedding = (
            oi_change < 0
            and (oi_chg_pct <= -6.0 or abs(oi_change) >= (8000 if is_opening_drive else 15000))
        ) or short_term_unwind
        is_gamma_expansion = (
            (
                oi_change > 0
                and abs(oi_change) >= min_exp_oi_chg
                and vol_oi_ratio >= (0.75 if is_opening_drive else 0.90)
                and (pchange >= 4.0 or is_high_volume_expansion)
            )
            or (pchange >= 12.0 and volume >= (min_volume if is_index else (60 * lot_sz)))
            or is_high_volume_expansion
        )
        is_high_turnover = (
            vol_oi_ratio >= (0.80 if is_opening_drive else 1.4) or volume >= min_turnover_vol
        )
        spot_above_vwap = spot >= (effective_vwap * (1.0 if is_index else 0.998))
        # PDL sweep bypass: if spot tagged day_low and bounced, it's a structural CE trigger
        # regardless of VWAP position (covers gap-fill bounce + demand OB scenarios)
        if _pdl_sweep_active and not spot_above_vwap:
            spot_above_vwap = True
            logger.debug(
                f"[GammaBlast CE] PDL sweep bypass activated for {underlying}: "
                f"spot={spot:.1f} within 0.3% of day_low={day_low:.1f}"
            )

        # Opposing Day High collision & VWAP overextension filter for CE:
        if effective_vwap > 0 and (spot - effective_vwap) / effective_vwap * 100 > 0.65:
            continue  # Extended > 0.65% above VWAP: Climax exhaustion risk

        # PDH Proximity Suppression for CE:
        # If spot is within 0.25% of PDH and no confirmed PDH sweep, CE is colliding into
        # a major previous-session supply wall — high probability of rejection.
        if _ce_near_pdh_suppressed:
            logger.debug(
                f"[GammaBlast CE] Suppressed {contract_sym}: Spot ₹{spot:,.1f} within "
                f"0.25% of PDH ₹{prev_day_high:,.1f} (Opposing Supply Collision — prior session wall)"
            )
            continue
        if (
            day_high
            and spot < day_high
            and day_low
            and ((day_high - day_low) / max(1.0, spot)) >= 0.003
        ):
            if (day_high - spot) / spot * 100 < 0.15:
                # If spot is pressing right up against day high, allow it if high volume expansion or strong momentum
                if not (is_high_volume_expansion or pchange >= 8.0 or vol_oi_ratio >= 1.5):
                    continue  # Spot is colliding into day high resistance (< 0.15% headroom without breakout momentum)

        # Major Call OI Wall interaction:
        is_ce_wall_breakout = False
        if max_ce_oi_strike > 0 and max_ce_oi_val > 0:
            dist_to_ce_wall_pct = ((max_ce_oi_strike - spot) / spot) * 100.0
            if -0.10 <= dist_to_ce_wall_pct <= 0.35:
                # Approaching or colliding into major call wall
                if max_ce_oi_chg >= 0 and vol_oi_ratio < 2.0 and not _pdl_sweep_active:
                    # Call writers are defending the wall; buying CE into this is a high-risk trap
                    logger.debug(
                        f"[GammaBlast CE] Rejected {contract_sym}: Colliding into unbroken Call OI wall "
                        f"at {max_ce_oi_strike} (ΔOI: +{max_ce_oi_chg:,}, dist: {dist_to_ce_wall_pct:.2f}%)"
                    )
                    continue
                elif max_ce_oi_chg < 0:
                    # Writers at the biggest wall are PANICKING and unwinding! Major short-covering blast!
                    is_ce_wall_breakout = True

        # Bid-Ask Spread & Slippage Quality Gate:
        from market.options import audit_option_liquidity

        liq_audit = audit_option_liquidity(c, underlying=underlying, lot_size=lot_sz)
        spread_pct = liq_audit.get("bid_ask_spread_pct")

        # Veto wide spreads (>1.8% index, >3.0% stock) to prevent severe slippage.
        max_allowed_spread = 1.8 if is_index else 3.0
        if spread_pct is not None and spread_pct > max_allowed_spread:
            # Institutional Momentum Bypass (Preserve Big Opportunities):
            is_explosive_turnover = vol_oi_ratio >= 2.5 and volume >= (
                20000 if is_index else (300 * lot_sz)
            )
            is_ignited_unwind = vol_oi_ratio >= 1.8 and oi_change < 0 and abs(oi_chg_pct) >= 15.0
            if not (is_explosive_turnover or is_ignited_unwind or _pdl_sweep_active):
                logger.debug(
                    f"[GammaBlast CE] Rejected {contract_sym}: Wide bid-ask spread ({spread_pct}% > {max_allowed_spread}%)"
                )
                continue

        if (is_oi_shedding or is_gamma_expansion) and is_high_turnover and spot_above_vwap:
            is_ignited = (
                (vol_oi_ratio >= 2.0 and oi_chg_pct <= -15.0)
                or (
                    is_opening_drive
                    and (
                        (vol_oi_ratio >= 1.2 and oi_change < 0)
                        or (vol_oi_ratio >= 1.5 and pchange >= 8.0)
                        or volume >= (25000 if is_index else (300 * lot_sz))
                    )
                )
                or (pchange >= 18.0 and volume >= (12000 if is_index else (200 * lot_sz)))
            )
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            exp_type = classify_expiry_type(exp_date, underlying)

            try:
                from engine.trade_plan import (
                    calculate_trade_plan,
                    calculate_option_execution_plan,
                    get_market_status,
                )
                from engine.position_sizer import get_lot_size

                tp = calculate_trade_plan(
                    symbol=underlying,
                    direction="BUY",
                    spot=spot,
                    timeframe="INTRADAY",
                    exchange=opt_exchange,
                    has_active_blast=True,
                )

                # Fix 2: SMC Structural Bypass for is_asymmetry_viable (CE side)
                _ce_smc_bypass = _pdl_sweep_active and is_index and vol_oi_ratio >= 1.5
                if tp and not tp.is_asymmetry_viable and not _ce_smc_bypass:
                    logger.debug(
                        f"[GammaBlast] Rejected {contract_sym}: Poor structural asymmetry ({tp.asymmetry_verdict})"
                    )
                    continue
                elif tp and not tp.is_asymmetry_viable and _ce_smc_bypass:
                    logger.debug(
                        f"[GammaBlast CE] SMC PDL-sweep bypass: overriding asymmetry rejection for {contract_sym} "
                        f"(spot={spot:.1f} near day_low={day_low})"
                    )

                # Optimized Institutional Conviction Scoring:
                confidence = compute_gamma_conviction(
                    is_index=is_index,
                    vol_oi_ratio=vol_oi_ratio,
                    oi_change=oi_change,
                    oi_chg_pct=oi_chg_pct,
                    pchange=pchange,
                    volume=volume,
                    c_vol=c_vol,
                    stage=stage,
                    strike_diff_pct=strike_diff_pct,
                    sweep_active=_pdl_sweep_active,
                    tp=tp,
                    spread_pct=spread_pct,
                    is_wall_breakout=is_ce_wall_breakout,
                    is_physical_week=is_phys_week,
                )

                # PDL Proximity Boost: CE at PDL is a structural demand bounce — extra conviction
                if _near_pdl and is_index:
                    confidence = min(98, confidence + 6)
                    logger.debug(
                        f"[GammaBlast CE] +6 conviction boost for {contract_sym}: "
                        f"Spot near PDL ₹{prev_day_low:,.1f} (demand bounce setup)"
                    )

                mkt_status = get_market_status(opt_exchange)
                lot_sz = get_lot_size(underlying)
                opt_plan = (
                    calculate_option_execution_plan(
                        trade_plan=tp,
                        option_type="CE",
                        strike=strike,
                        expiry=exp_date or "",
                        option_ltp=opt_ltp,
                        lot_size=lot_sz,
                    )
                    if opt_ltp > 0 and exp_date
                    else None
                )
                target_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.25, 1)
                t2_premium = opt_plan.get("t2_premium") if opt_plan else round(opt_ltp * 1.45, 1)
                t3_premium = opt_plan.get("t3_premium") if opt_plan else round(opt_ltp * 1.75, 1)
                sl_premium = (
                    opt_plan["sl_premium"] if opt_plan else round(max(0.05, opt_ltp * 0.85), 1)
                )
                if opt_plan and opt_plan.get("option_rr"):
                    rr_str = opt_plan["option_rr"]
                elif opt_plan and opt_plan.get("t1_premium") and opt_plan.get("sl_premium"):
                    risk_prem = max(0.5, opt_ltp - opt_plan["sl_premium"])
                    reward_prem = max(0.5, opt_plan["t1_premium"] - opt_ltp)
                    rr_str = f"1:{round(reward_prem / risk_prem, 2)}"
                elif tp:
                    rr_str = f"1:{tp.rr_t1}"
                else:
                    rr_str = "1:1.7"
                t1_pct_str = (
                    f"+{opt_plan['t1_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("t1_pct"))
                    else "+25%"
                )
                tp_dict = tp.as_dict()
            except Exception as e_tp:
                logger.debug(
                    "[GammaBlast CE] Dynamic trade plan failed, using conservative fallback: %s",
                    e_tp,
                )
                tp_dict = None
                opt_plan = None
                mkt_status = {"status": "SESSION_CLOSED", "label": "🌙 SESSION CLOSED"}
                target_premium = (
                    round(opt_ltp * 1.25, 1) if opt_ltp > 0 else round(strike * 0.012, 1)
                )
                t2_premium = round(opt_ltp * 1.45, 1) if opt_ltp > 0 else round(strike * 0.020, 1)
                t3_premium = round(opt_ltp * 1.75, 1) if opt_ltp > 0 else round(strike * 0.035, 1)
                sl_premium = round(max(0.05, opt_ltp * 0.72), 1) if opt_ltp > 0 else 1.0
                rr_str = "1:1.7"
                t1_pct_str = "+25%"

            headline = (
                f"⚡ CALL GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} CE"
                + (" [SEBI PHYSICAL SETTLEMENT WEEK]" if is_phys_week else "")
            )
            if oi_change < 0 and abs(oi_chg_pct) > 0.05:
                oi_desc = f"Call writers shedding {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
            elif oi_change > 0 and abs(oi_chg_pct) > 0.05:
                oi_desc = f"Call volume surging with fresh accumulation (ΔOI: +{oi_change:,}). "
            else:
                oi_desc = f"Institutional Call turnover surge ({volume:,} contracts traded). "

            summary = (
                f"{oi_desc}Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} holding VWAP. "
                f"{'Explosive short-covering underway!' if is_ignited else 'Early-warning coiling before gamma surge!'}"
            )

            if not opt_ltp or opt_ltp <= 0.0:
                try:
                    from market.quotes import get_ltp

                    fetched = get_ltp(contract_sym)
                    if fetched and fetched > 0:
                        opt_ltp = float(fetched)
                except Exception:
                    pass

            is_authentic_opt = bool(opt_ltp and opt_ltp > 0.0)
            alert_env = "LIVE" if is_authentic_opt else "TEST"

            # Determine optional High-Beta Runner strike (1 strike further OTM with verified liquidity)
            runner_strike_info = None
            higher_ce_candidates = [
                c_cand for c_cand in ce_contracts if getattr(c_cand, "strike", 0.0) > strike
            ]
            if higher_ce_candidates:
                higher_ce_candidates.sort(key=lambda x: getattr(x, "strike", 0.0))
                runner_c = higher_ce_candidates[0]
                r_strike = getattr(runner_c, "strike", 0.0)
                r_ltp = getattr(runner_c, "last_price", 0.0)
                r_sym = getattr(runner_c, "symbol", f"{underlying}{int(r_strike)}CE")
                runner_strike_info = {
                    "strike": r_strike,
                    "option_type": "CE",
                    "ltp": r_ltp,
                    "symbol": r_sym,
                }

            entry_min_ce = round(max(0.5, opt_ltp * 0.94), 1) if opt_ltp > 0 else spot
            entry_max_ce = round(opt_ltp * 1.02, 1) if opt_ltp > 0 else spot
            entry_range_ce = f"₹{entry_min_ce:,.1f} – ₹{entry_max_ce:,.1f}"
            no_chase_ce = (
                round(opt_ltp * 1.04, 1) if (opt_ltp and opt_ltp > 0) else round(spot * 1.004, 1)
            )

            profit_rule_base = (
                f"Book 50% at T1 (₹{target_premium:,.2f}), move SL to Cost, let remainder ride to T2 (₹{t2_premium:,.2f})."
                if t2_premium
                else f"Book 50% at T1 (₹{target_premium:,.2f}), move SL to Cost."
            )

            alerts.append(
                AutoAlert(
                    alert_id=generate_alert_id(
                        underlying,
                        "GAMMA_BLAST",
                        variant=f"ce-{int(strike)}",
                    ),
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange=opt_exchange,
                    direction="BULLISH",
                    headline=headline,
                    summary=f"{summary} | OTE Entry: {entry_range_ce} | No Chase > ₹{no_chase_ce}",
                    ltp=opt_ltp or spot,
                    trigger_level=opt_ltp if (opt_ltp and opt_ltp > 0) else strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    no_chase_boundary=no_chase_ce,
                    strike=strike,
                    option_type="CE",
                    contract_symbol=contract_sym,
                    expiry_date=exp_date,
                    expiry_type=exp_type,
                    underlying_spot=spot,
                    option_premium=opt_ltp or None,
                    market_status=mkt_status["status"],
                    is_live=is_authentic_opt,
                    environment=alert_env,
                    liquidity_status=liq_audit["liquidity_status"],
                    bid_ask_spread_pct=liq_audit["bid_ask_spread_pct"],
                    segment="FNO_INDEX"
                    if underlying
                    in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
                    else "FNO_STOCK",
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "liquidity": liq_audit,
                        "is_volume_expansion": is_high_volume_expansion,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(
                            ((spot - effective_vwap) / effective_vwap) * 100, 2
                        ),
                        "lot_size": lot_sz,
                        "runner_strike": runner_strike_info["strike"]
                        if runner_strike_info
                        else None,
                        "runner_symbol": runner_strike_info["symbol"]
                        if runner_strike_info
                        else None,
                        "runner_ltp": runner_strike_info["ltp"] if runner_strike_info else None,
                        "runner_strike_info": runner_strike_info,
                        "pdl_sweep": _pdl_sweep_active,
                        "day_low": day_low,
                        "day_high": day_high,
                        "prev_day_low": prev_day_low,
                        "prev_day_high": prev_day_high,
                        "near_pdl": _near_pdl,
                        "near_pdh": _near_pdh,
                        "wall_breakout": is_ce_wall_breakout,
                        "physical_settlement_week": is_phys_week,
                        "physical_settlement_warning": (
                            "⚠️ SEBI Physical Delivery Expiry Week: STAGGERED MARGIN SURGE (25%->100% full lot cash value). INTRADAY SCALP ONLY — MANDATORY EXIT BY 15:00 IST."
                            if is_phys_week
                            else None
                        ),
                    },
                    actionable_plan={
                        "action": "BUY CE",
                        "contract": contract_sym,
                        "instrument": contract_sym,
                        "instrument_type": "OPTION",
                        "strike": strike,
                        "option_type": "CE",
                        "expiry_date": exp_date,
                        "expiry_type": exp_type,
                        "underlying_spot": f"₹{spot:,.1f}",
                        "recommended_entry": f"₹{opt_ltp:,.2f} (OTE Pullback: {entry_range_ce})"
                        if opt_ltp
                        else "Market",
                        "entry_range": entry_range_ce,
                        "no_chase": f"DO NOT CHASE above ₹{no_chase_ce}",
                        "target_1": f"₹{target_premium:,.2f}",
                        "target": f"₹{target_premium:,.2f} ({t1_pct_str})",
                        "target_2": f"₹{t2_premium:,.2f}"
                        if t2_premium
                        else f"₹{round(target_premium * 1.6, 2):,.2f}",
                        "target_moonshot": f"₹{t3_premium:,.2f}"
                        if t3_premium
                        else f"₹{round(target_premium * 2.5, 2):,.2f}",
                        "stop_loss": f"₹{sl_premium:,.2f}",
                        "risk_reward": rr_str,
                        "profit_rule": (
                            f"⚠️ INTRADAY SCALP ONLY (SEBI Physical Settlement Week - Mandatory square-off before 15:00 IST). {profit_rule_base}"
                            if is_phys_week
                            else profit_rule_base
                        ),
                        "trade_plan": tp_dict,
                        "option_plan": opt_plan,
                        "runner_strike": runner_strike_info,
                        "market_status": mkt_status,
                        "lot_size": lot_sz,
                    },
                    lot_size=lot_sz,
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    # ── Analyze PUT Gamma Blast (Bearish Downside Panic) ───────
    for c in pe_contracts:
        strike = getattr(c, "strike", 0.0)
        strike_diff_pct = ((strike - spot) / spot) * 100.0
        # Delta-Gated Sweet-Spot Filter: Indices demand ATM/Near-ATM (<= 0.6%), equities allow up to 1.2%
        max_put_otm = 0.6 if is_index else 1.2
        max_put_itm = 0.4 if is_index else 0.8
        if not (-max_put_otm <= strike_diff_pct <= max_put_itm):
            continue

        oi = getattr(c, "oi", 0)
        oi_change = getattr(c, "oi_change", 0)
        volume = getattr(c, "volume", 0)
        opt_ltp = getattr(c, "last_price", 0.0)
        contract_sym = getattr(c, "symbol", f"{underlying}{int(strike)}PE")

        if not is_index and lot_sz > 1:
            c_oi = (oi / lot_sz) if oi > lot_sz * 2.5 else oi
            c_vol = (volume / lot_sz) if volume > lot_sz * 2.5 else volume
            c_oi_chg = (
                (abs(oi_change) / lot_sz) if abs(oi_change) > lot_sz * 2.5 else abs(oi_change)
            )
            min_strike_oi = 150 if is_opening_drive else 100
            min_abs_oi_change = 30 if is_opening_drive else 20
            min_volume = 120 if is_opening_drive else 50
            min_exp_oi_chg = 80 * lot_sz
            min_turnover_vol = 150 * lot_sz
        else:
            c_oi = oi
            c_vol = volume
            c_oi_chg = abs(oi_change)
            if clean_sym in ("SENSEX", "BANKEX"):
                min_strike_oi = 500 if is_opening_drive else 800
                min_abs_oi_change = 60 if is_opening_drive else 100
                min_volume = 400 if is_opening_drive else 1000
                min_exp_oi_chg = 300
                min_turnover_vol = 1200
            elif clean_sym == "MIDCPNIFTY":
                min_strike_oi = 1000 if is_opening_drive else 2000
                min_abs_oi_change = 60 if is_opening_drive else 120
                min_volume = 600 if is_opening_drive else 1500
                min_exp_oi_chg = 400
                min_turnover_vol = 2500
            elif clean_sym == "FINNIFTY":
                min_strike_oi = 3000 if is_opening_drive else 5000
                min_abs_oi_change = 300 if is_opening_drive else 600
                min_volume = 1200 if is_opening_drive else 3000
                min_exp_oi_chg = 2000
                min_turnover_vol = 5000
            else:
                # NIFTY & BANKNIFTY
                min_strike_oi = 8000 if is_opening_drive else 12000
                min_abs_oi_change = 1200 if is_opening_drive else 2500
                min_volume = 2500 if is_opening_drive else 8000
                min_exp_oi_chg = 8000
                min_turnover_vol = 12000

        if c_oi < min_strike_oi or c_vol < min_volume:
            continue

        vol_oi_ratio = round(volume / max(1, oi), 2)
        oi_chg_pct = (
            round((oi_change / max(1, oi - oi_change)) * 100.0, 1) if (oi - oi_change) > 0 else 0.0
        )
        pchange = float(getattr(c, "pchange", 0.0) or 0.0)

        exp_date = getattr(c, "expiry", "") or None
        is_phys_week = False
        if exp_date:
            try:
                exp_str = str(exp_date).split("T")[0].strip()
                exp_dt = None
                for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        exp_dt = datetime.strptime(exp_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if exp_dt:
                    today_ist = datetime.now(IST).date()
                    dte_days = (exp_dt - today_ist).days
                    max_gamma_dte = (
                        8 if (is_index and clean_sym == "NIFTY") else (16 if is_index else 35)
                    )
                    if dte_days > max_gamma_dte:
                        continue
                    # 0DTE Afternoon Theta Decay Guard (Post 13:00 IST):
                    # On expiry day (dte_days == 0), OTM options decay rapidly due to hyper-accelerated theta.
                    # Ban naked OTM options after 13:00 IST; strictly require ATM or ITM contracts!
                    # Big Opportunity Bypass: allow near-OTM (up to 0.35%) ONLY if massive writer panic unwind
                    if dte_days == 0 and now_dt.hour >= 13:
                        is_hero_unwind = (
                            oi_change < 0 and abs(oi_chg_pct) >= 15.0 and vol_oi_ratio >= 2.0
                        )
                        if strike_diff_pct < -0.05 and not (
                            is_hero_unwind and strike_diff_pct >= -0.35
                        ):
                            continue
            except Exception:
                pass

            # SEBI Physical Delivery Expiry Week Guard for Single-Stock Options:
            if not is_index:
                try:
                    from engine.alert_expiry import is_monthly_physical_expiry_week

                    is_phys_week = is_monthly_physical_expiry_week(
                        str(exp_date), symbol=clean_sym, ref_dt=now_dt
                    )
                except Exception:
                    is_phys_week = False

        if is_phys_week and not is_index:
            # During physical expiry week, near-month single stock options have huge margin spikes (25%->100%).
            # Suppress sluggish early warnings: require vol_oi_ratio >= 1.4 or ignited momentum to prevent capital traps.
            if vol_oi_ratio < 1.4 and (volume < 300 * lot_sz) and pchange < 10.0:
                logger.debug(
                    f"[GammaBlast PE] Suppressed {contract_sym}: Low turnover during SEBI physical delivery week"
                )
                continue

        now_ts = time.time()
        c_key = f"{underlying}_{int(strike)}_PE"
        prior_snap = _STRIKE_OI_SNAPSHOTS.get(c_key)
        _STRIKE_OI_SNAPSHOTS[c_key] = (now_ts, oi, volume)

        short_term_unwind = False
        if prior_snap:
            p_ts, p_oi, _ = prior_snap
            dt_sec = max(1.0, now_ts - p_ts)
            if dt_sec <= 300.0:  # Within 5 minutes
                unwind_rate = ((oi - p_oi) / dt_sec) * 60.0  # contracts / min
                if (is_index and unwind_rate <= -1000) or (not is_index and unwind_rate <= -50):
                    short_term_unwind = True

        has_gamma_pchange = pchange >= 12.0 and volume >= (4000 if is_index else 200)
        is_high_volume_expansion = (
            vol_oi_ratio >= 1.8 and volume >= (8000 if is_index else 500) and pchange >= 4.5
        )
        if (
            c_oi_chg > 0
            and c_oi_chg < min_abs_oi_change
            and not has_gamma_pchange
            and not is_high_volume_expansion
            and not short_term_unwind
        ):
            continue
        if (
            c_oi_chg == 0
            and not short_term_unwind
            and not has_gamma_pchange
            and not is_high_volume_expansion
        ):
            continue

        is_oi_shedding = (
            oi_change < 0
            and (oi_chg_pct <= -6.0 or abs(oi_change) >= (8000 if is_opening_drive else 15000))
        ) or short_term_unwind
        is_gamma_expansion = (
            (
                oi_change > 0
                and abs(oi_change) >= min_exp_oi_chg
                and vol_oi_ratio >= (0.75 if is_opening_drive else 0.90)
                and (pchange >= 4.0 or is_high_volume_expansion)
            )
            or (pchange >= 12.0 and volume >= (min_volume if is_index else (60 * lot_sz)))
            or is_high_volume_expansion
        )
        is_high_turnover = (
            vol_oi_ratio >= (0.80 if is_opening_drive else 1.4) or volume >= min_turnover_vol
        )
        # Relaxed VWAP gate for PE (1.002 → 1.008)
        _pe_vwap_multiplier = 1.008 if is_index else 1.004
        spot_below_vwap = spot <= (effective_vwap * _pe_vwap_multiplier)
        # PDH sweep bypass: if spot swept the day_high and wicked back, lift the VWAP gate
        if _pdh_sweep_active and not spot_below_vwap:
            spot_below_vwap = True
            logger.debug(
                f"[GammaBlast PE] PDH sweep bypass activated for {underlying}: "
                f"spot={spot:.1f} within 0.3% of day_high={day_high:.1f} — VWAP gate lifted"
            )

        # Opposing Day Low collision & VWAP overextension filter for PE:
        if effective_vwap > 0 and (effective_vwap - spot) / effective_vwap * 100 > 0.65:
            continue  # Extended > 0.65% below VWAP: Capitulation exhaustion risk

        # PDL Proximity Suppression for PE:
        # If spot is within 0.25% above PDL and no confirmed PDL bounce, PE is colliding into
        # a major previous-session demand wall right below — high probability of support hold.
        if _pe_near_pdl_suppressed:
            logger.debug(
                f"[GammaBlast PE] Suppressed {contract_sym}: Spot ₹{spot:,.1f} within "
                f"0.25% of PDL ₹{prev_day_low:,.1f} (Opposing Demand Collision — prior session floor)"
            )
            continue
        if (
            day_low
            and spot > day_low
            and day_high
            and ((day_high - day_low) / max(1.0, spot)) >= 0.003
        ):
            if (spot - day_low) / spot * 100 < 0.15:
                # If spot is pressing right down against day low, allow it if high volume expansion or strong momentum
                if not (is_high_volume_expansion or pchange >= 8.0 or vol_oi_ratio >= 1.5):
                    continue  # Spot is colliding into day low support (< 0.15% headroom without breakdown momentum)

        # Major Put OI Wall interaction:
        is_pe_wall_breakout = False
        if max_pe_oi_strike > 0 and max_pe_oi_val > 0:
            dist_to_pe_wall_pct = ((spot - max_pe_oi_strike) / spot) * 100.0
            if -0.10 <= dist_to_pe_wall_pct <= 0.35:
                # Approaching or colliding into major put wall
                if max_pe_oi_chg >= 0 and vol_oi_ratio < 2.0 and not _pdh_sweep_active:
                    # Put writers are defending support; buying PE into this is a high-risk trap
                    logger.debug(
                        f"[GammaBlast PE] Rejected {contract_sym}: Colliding into unbroken Put OI wall "
                        f"at {max_pe_oi_strike} (ΔOI: +{max_pe_oi_chg:,}, dist: {dist_to_pe_wall_pct:.2f}%)"
                    )
                    continue
                elif max_pe_oi_chg < 0:
                    # Writers at the biggest wall are PANICKING and unwinding! Major liquidation blast!
                    is_pe_wall_breakout = True

        # Bid-Ask Spread & Slippage Quality Gate:
        from market.options import audit_option_liquidity

        liq_audit = audit_option_liquidity(c, underlying=underlying, lot_size=lot_sz)
        spread_pct = liq_audit.get("bid_ask_spread_pct")

        # Veto wide spreads (>1.8% index, >3.0% stock) to prevent severe slippage.
        max_allowed_spread = 1.8 if is_index else 3.0
        if spread_pct is not None and spread_pct > max_allowed_spread:
            # Institutional Momentum Bypass (Preserve Big Opportunities):
            is_explosive_turnover = vol_oi_ratio >= 2.5 and volume >= (
                20000 if is_index else (300 * lot_sz)
            )
            is_ignited_unwind = vol_oi_ratio >= 1.8 and oi_change < 0 and abs(oi_chg_pct) >= 15.0
            if not (is_explosive_turnover or is_ignited_unwind or _pdh_sweep_active):
                logger.debug(
                    f"[GammaBlast PE] Rejected {contract_sym}: Wide bid-ask spread ({spread_pct}% > {max_allowed_spread}%)"
                )
                continue

        if (is_oi_shedding or is_gamma_expansion) and is_high_turnover and spot_below_vwap:
            is_ignited = (
                (vol_oi_ratio >= 2.0 and oi_chg_pct <= -15.0)
                or (
                    is_opening_drive
                    and (
                        (vol_oi_ratio >= 1.2 and oi_change < 0)
                        or (vol_oi_ratio >= 1.5 and pchange >= 8.0)
                        or volume >= (25000 if is_index else (300 * lot_sz))
                    )
                )
                or (pchange >= 18.0 and volume >= (12000 if is_index else (200 * lot_sz)))
            )
            stage = "IGNITED" if is_ignited else "EARLY_WARNING"
            exp_type = classify_expiry_type(exp_date, underlying)

            try:
                from engine.trade_plan import (
                    calculate_trade_plan,
                    calculate_option_execution_plan,
                    get_market_status,
                )
                from engine.position_sizer import get_lot_size

                tp = calculate_trade_plan(
                    symbol=underlying,
                    direction="SELL",
                    spot=spot,
                    timeframe="INTRADAY",
                    exchange=opt_exchange,
                    has_active_blast=True,
                )

                # Fix 2: SMC Structural Bypass for is_asymmetry_viable (PE side)
                _pe_smc_bypass = is_index and ((vol_oi_ratio >= 2.0) or _pdh_sweep_active)
                if tp and not tp.is_asymmetry_viable and not _pe_smc_bypass:
                    logger.debug(
                        f"[GammaBlast] Rejected {contract_sym}: Poor structural asymmetry ({tp.asymmetry_verdict})"
                    )
                    continue
                elif tp and not tp.is_asymmetry_viable and _pe_smc_bypass:
                    logger.debug(
                        f"[GammaBlast PE] SMC bypass: overriding asymmetry rejection for {contract_sym} "
                        f"(vol_oi={vol_oi_ratio:.2f}, pdh_sweep={_pdh_sweep_active})"
                    )

                # Optimized Institutional Conviction Scoring:
                confidence = compute_gamma_conviction(
                    is_index=is_index,
                    vol_oi_ratio=vol_oi_ratio,
                    oi_change=oi_change,
                    oi_chg_pct=oi_chg_pct,
                    pchange=pchange,
                    volume=volume,
                    c_vol=c_vol,
                    stage=stage,
                    strike_diff_pct=strike_diff_pct,
                    sweep_active=_pdh_sweep_active,
                    tp=tp,
                    spread_pct=spread_pct,
                    is_wall_breakout=is_pe_wall_breakout,
                    is_physical_week=is_phys_week,
                )

                # PDH Proximity Boost: PE at PDH is a structural supply rejection — extra conviction
                if _near_pdh and is_index:
                    confidence = min(98, confidence + 6)
                    logger.debug(
                        f"[GammaBlast PE] +6 conviction boost for {contract_sym}: "
                        f"Spot near PDH ₹{prev_day_high:,.1f} (supply rejection setup)"
                    )

                mkt_status = get_market_status(opt_exchange)
                lot_sz = get_lot_size(underlying)
                opt_plan = (
                    calculate_option_execution_plan(
                        trade_plan=tp,
                        option_type="PE",
                        strike=strike,
                        expiry=exp_date or "",
                        option_ltp=opt_ltp,
                        lot_size=lot_sz,
                    )
                    if opt_ltp > 0 and exp_date
                    else None
                )
                target_premium = opt_plan["t1_premium"] if opt_plan else round(opt_ltp * 1.25, 1)
                t2_premium = opt_plan.get("t2_premium") if opt_plan else round(opt_ltp * 1.45, 1)
                t3_premium = opt_plan.get("t3_premium") if opt_plan else round(opt_ltp * 1.75, 1)
                sl_premium = (
                    opt_plan["sl_premium"] if opt_plan else round(max(0.05, opt_ltp * 0.85), 1)
                )
                if opt_plan and opt_plan.get("option_rr"):
                    rr_str = opt_plan["option_rr"]
                elif opt_plan and opt_plan.get("t1_premium") and opt_plan.get("sl_premium"):
                    risk_prem = max(0.5, opt_ltp - opt_plan["sl_premium"])
                    reward_prem = max(0.5, opt_plan["t1_premium"] - opt_ltp)
                    rr_str = f"1:{round(reward_prem / risk_prem, 2)}"
                elif tp:
                    rr_str = f"1:{tp.rr_t1}"
                else:
                    rr_str = "1:1.7"
                t1_pct_str = (
                    f"+{opt_plan['t1_pct']:.1f}%"
                    if (opt_plan and opt_plan.get("t1_pct"))
                    else "+25%"
                )
                tp_dict = tp.as_dict()
            except Exception as e_tp:
                logger.debug(
                    "[GammaBlast PE] Dynamic trade plan failed, using conservative fallback: %s",
                    e_tp,
                )
                tp_dict = None
                opt_plan = None
                mkt_status = {"status": "SESSION_CLOSED", "label": "🌙 SESSION CLOSED"}
                target_premium = (
                    round(opt_ltp * 1.25, 1) if opt_ltp > 0 else round(strike * 0.012, 1)
                )
                t2_premium = round(opt_ltp * 1.45, 1) if opt_ltp > 0 else round(strike * 0.020, 1)
                t3_premium = round(opt_ltp * 1.75, 1) if opt_ltp > 0 else round(strike * 0.035, 1)
                sl_premium = round(max(0.05, opt_ltp * 0.72), 1) if opt_ltp > 0 else 1.0
                rr_str = "1:1.7"
                t1_pct_str = "+25%"

            headline = (
                f"⚡ PUT GAMMA BLAST {stage.replace('_', ' ')}: {underlying} {int(strike)} PE"
                + (" [SEBI PHYSICAL SETTLEMENT WEEK]" if is_phys_week else "")
            )
            if oi_change < 0 and abs(oi_chg_pct) > 0.05:
                oi_desc = (
                    f"Put writers capitulating {abs(oi_chg_pct):.1f}% OI (ΔOI: {oi_change:,}). "
                )
            elif oi_change > 0 and abs(oi_chg_pct) > 0.05:
                oi_desc = f"Put volume surging with fresh accumulation (ΔOI: +{oi_change:,}). "
            else:
                oi_desc = f"Institutional Put turnover surge ({volume:,} contracts traded). "

            summary = (
                f"{oi_desc}Vol/OI turnover {vol_oi_ratio}x. Spot ₹{spot:,.1f} below VWAP. "
                f"{'Aggressive long put / short spot momentum!' if is_ignited else 'Early-warning coiling before put gamma surge!'}"
            )

            if not opt_ltp or opt_ltp <= 0.0:
                try:
                    from market.quotes import get_ltp

                    fetched = get_ltp(contract_sym)
                    if fetched and fetched > 0:
                        opt_ltp = float(fetched)
                except Exception:
                    pass

            is_authentic_opt = bool(opt_ltp and opt_ltp > 0.0)
            alert_env = "LIVE" if is_authentic_opt else "TEST"

            # Determine optional High-Beta Runner strike (1 strike further OTM with verified liquidity)
            runner_strike_info = None
            lower_pe_candidates = [
                c_cand for c_cand in pe_contracts if getattr(c_cand, "strike", 0.0) < strike
            ]
            if lower_pe_candidates:
                lower_pe_candidates.sort(key=lambda x: getattr(x, "strike", 0.0), reverse=True)
                runner_c = lower_pe_candidates[0]
                r_strike = getattr(runner_c, "strike", 0.0)
                r_ltp = getattr(runner_c, "last_price", 0.0)
                r_sym = getattr(runner_c, "symbol", f"{underlying}{int(r_strike)}PE")
                runner_strike_info = {
                    "strike": r_strike,
                    "option_type": "PE",
                    "ltp": r_ltp,
                    "symbol": r_sym,
                }

            entry_min_pe = round(max(0.5, opt_ltp * 0.94), 1) if opt_ltp > 0 else spot
            entry_max_pe = round(opt_ltp * 1.02, 1) if opt_ltp > 0 else spot
            entry_range_pe = f"₹{entry_min_pe:,.1f} – ₹{entry_max_pe:,.1f}"
            no_chase_pe = (
                round(opt_ltp * 1.04, 1) if (opt_ltp and opt_ltp > 0) else round(spot * 0.996, 1)
            )

            profit_rule_base = (
                f"Book 50% at T1 (₹{target_premium:,.2f}), move SL to Cost, let remainder ride to T2 (₹{t2_premium:,.2f})."
                if t2_premium
                else f"Book 50% at T1 (₹{target_premium:,.2f}), move SL to Cost."
            )

            alerts.append(
                AutoAlert(
                    alert_id=generate_alert_id(
                        underlying,
                        "GAMMA_BLAST",
                        variant=f"pe-{int(strike)}",
                    ),
                    alert_type="GAMMA_BLAST",
                    stage=stage,
                    symbol=underlying,
                    exchange=opt_exchange,
                    direction="BEARISH",
                    headline=headline,
                    summary=f"{summary} | OTE Entry: {entry_range_pe} | No Chase > ₹{no_chase_pe}",
                    ltp=opt_ltp or spot,
                    trigger_level=opt_ltp if (opt_ltp and opt_ltp > 0) else strike,
                    target_level=target_premium,
                    stop_loss=sl_premium,
                    no_chase_boundary=no_chase_pe,
                    strike=strike,
                    option_type="PE",
                    contract_symbol=contract_sym,
                    expiry_date=exp_date,
                    expiry_type=exp_type,
                    underlying_spot=spot,
                    option_premium=opt_ltp or None,
                    market_status=mkt_status["status"],
                    is_live=is_authentic_opt,
                    environment=alert_env,
                    liquidity_status=liq_audit["liquidity_status"],
                    bid_ask_spread_pct=liq_audit["bid_ask_spread_pct"],
                    segment="FNO_INDEX"
                    if underlying
                    in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
                    else "FNO_STOCK",
                    metrics={
                        "strike": strike,
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_change_pct": oi_chg_pct,
                        "volume": volume,
                        "vol_oi_ratio": vol_oi_ratio,
                        "liquidity": liq_audit,
                        "is_volume_expansion": is_high_volume_expansion,
                        "spot": spot,
                        "vwap": effective_vwap,
                        "spot_to_vwap_pct": round(
                            ((spot - effective_vwap) / effective_vwap) * 100, 2
                        ),
                        "lot_size": lot_sz,
                        "runner_strike": runner_strike_info["strike"]
                        if runner_strike_info
                        else None,
                        "runner_symbol": runner_strike_info["symbol"]
                        if runner_strike_info
                        else None,
                        "runner_ltp": runner_strike_info["ltp"] if runner_strike_info else None,
                        "runner_strike_info": runner_strike_info,
                        "pdh_sweep": _pdh_sweep_active,
                        "pdl_sweep": _pdl_sweep_active,
                        "day_high": day_high,
                        "day_low": day_low,
                        "prev_day_low": prev_day_low,
                        "prev_day_high": prev_day_high,
                        "near_pdl": _near_pdl,
                        "near_pdh": _near_pdh,
                        "choch": _pdh_sweep_active,
                        "wall_breakout": is_pe_wall_breakout,
                        "physical_settlement_week": is_phys_week,
                        "physical_settlement_warning": (
                            "⚠️ SEBI Physical Delivery Expiry Week: STAGGERED MARGIN SURGE (25%->100% full lot cash value). INTRADAY SCALP ONLY — MANDATORY EXIT BY 15:00 IST."
                            if is_phys_week
                            else None
                        ),
                    },
                    actionable_plan={
                        "action": "BUY PE",
                        "contract": contract_sym,
                        "instrument": contract_sym,
                        "instrument_type": "OPTION",
                        "strike": strike,
                        "option_type": "PE",
                        "expiry_date": exp_date,
                        "expiry_type": exp_type,
                        "underlying_spot": f"₹{spot:,.1f}",
                        "recommended_entry": f"₹{opt_ltp:,.2f} (OTE Pullback: {entry_range_pe})"
                        if opt_ltp
                        else "Market",
                        "entry_range": entry_range_pe,
                        "no_chase": f"DO NOT CHASE above ₹{no_chase_pe}",
                        "target_1": f"₹{target_premium:,.2f}",
                        "target": f"₹{target_premium:,.2f} ({t1_pct_str})",
                        "target_2": f"₹{t2_premium:,.2f}"
                        if t2_premium
                        else f"₹{round(target_premium * 1.6, 2):,.2f}",
                        "target_moonshot": f"₹{t3_premium:,.2f}"
                        if t3_premium
                        else f"₹{round(target_premium * 2.5, 2):,.2f}",
                        "stop_loss": f"₹{sl_premium:,.2f}",
                        "risk_reward": rr_str,
                        "profit_rule": (
                            f"⚠️ INTRADAY SCALP ONLY (SEBI Physical Settlement Week - Mandatory square-off before 15:00 IST). {profit_rule_base}"
                            if is_phys_week
                            else profit_rule_base
                        ),
                        "trade_plan": tp_dict,
                        "option_plan": opt_plan,
                        "runner_strike": runner_strike_info,
                        "market_status": mkt_status,
                        "lot_size": lot_sz,
                    },
                    lot_size=lot_sz,
                    confidence=confidence,
                    created_at=now_iso,
                )
            )

    return alerts
