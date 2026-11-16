"""
engine/pullback_level_resolver.py
─────────────────────────────────
Institutional Pullback-to-Value & Limit Entry Level Resolver.

Calculates mathematically grounded, asymmetric limit entry zones for trending
assets (Indices and F&O Equities) to eliminate FOMO market chasing at highs/lows.

Mathematical Foundations:
1. Session Intraday VWAP (Volume Weighted Average Price) - The Institutional Fair Value Anchor.
2. Fibonacci Optimal Trade Entry (OTE) Zone:
   - 38.2% Retracement: Shallow continuation / runaway momentum.
   - 50.0% Retracement: Equilibrium price.
   - 61.8% Retracement: Golden Pocket / Deep institutional discount.
3. Dynamic Invalidation Stop:
   - Below VWAP or Order Block Floor with dynamic noise buffer (1.2x 5m ATR).
4. Asymmetric Reward Escalation:
   - Target 1: +2.0R to +2.5R (Scale 50% & trail stop-loss to Breakeven).
   - Target 2: +4.0R to +4.5R (Expansion target).
   - Target 3: +6.0R+ (Moonshot runner).
5. Option Premium Limit Mapping:
   - Translates underlying Spot Limit Entry Zone into exact Option Contract Limit Buy price
     using Delta: Limit_Opt ≈ CMP_Opt - Delta * (Spot_CMP - Spot_Limit).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from engine.alert_identity import canonical_alert_symbol
from engine.option_resolver import resolve_option_contract, is_index_symbol

logger = logging.getLogger("chanakya.engine.pullback_level_resolver")


@dataclass
class PullbackLevelPlan:
    """Institutional limit entry and asymmetric risk plan anchored to fair value."""

    symbol: str
    direction: str  # "BULLISH" | "BEARISH"
    spot_cmp: float
    vwap: float
    entry_zone_min: float
    entry_zone_max: float
    entry_zone_mid: float
    stop_loss: float
    risk_pts: float
    target_1: float
    target_2: float
    target_3: float
    rr_t1: float
    rr_t2: float
    no_chase_price: float
    opt_symbol: Optional[str] = None
    opt_entry_limit: Optional[float] = None
    opt_sl: Optional[float] = None
    opt_t1: Optional[float] = None
    opt_t2: Optional[float] = None
    actionable_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def resolve_pullback_entry(
    symbol: str,
    direction: str,
    spot: float,
    vwap: float,
    day_high: Optional[float] = None,
    day_low: Optional[float] = None,
    atr_5m: Optional[float] = None,
    prefer_options: bool = True,
) -> PullbackLevelPlan:
    """
    Computes an institutional limit entry plan for a trending asset.
    Replaces CMP market chasing with precise VWAP / Fibonacci OTE limit entry levels.
    """
    clean_sym = canonical_alert_symbol(symbol)
    is_index = is_index_symbol(clean_sym)
    norm_dir = direction.upper().strip()
    is_bull = norm_dir in ("BULLISH", "BUY", "LONG")

    # Safe defaults
    effective_spot = max(0.05, float(spot))
    effective_vwap = (
        float(vwap)
        if (vwap and vwap > 0)
        else (effective_spot * 0.998 if is_bull else effective_spot * 1.002)
    )

    if is_bull:
        high = (
            float(day_high) if (day_high and day_high >= effective_spot) else effective_spot * 1.004
        )
        low = (
            float(day_low)
            if (day_low and 0 < day_low <= effective_spot)
            else (effective_vwap if effective_vwap > 0 else effective_spot * 0.994)
        )
        if low >= high:
            low = high * 0.994

        impulse_range = max(high - low, effective_spot * 0.004)

        # Fibonacci Optimal Trade Entry (OTE)
        # 38.2% retracement from high
        fib_382 = high - 0.382 * impulse_range
        # 61.8% golden pocket from high
        fib_618 = high - 0.618 * impulse_range

        # Confluence zone: between 38.2% and VWAP (or 61.8%)
        entry_zone_max = round(min(high * 0.999, max(fib_382, effective_vwap * 1.002)), 2)
        entry_zone_min = round(max(low, min(fib_618, effective_vwap * 0.999)), 2)

        if entry_zone_min >= entry_zone_max:
            entry_zone_min = round(effective_vwap * 0.999, 2)
            entry_zone_max = round(max(effective_vwap * 1.002, effective_spot * 0.999), 2)

        entry_zone_mid = round((entry_zone_min + entry_zone_max) / 2.0, 2)

        # Structural stop-loss below VWAP & entry zone floor
        min_risk_buffer = (
            (atr_5m * 1.20)
            if (atr_5m and atr_5m > 0)
            else max(effective_spot * 0.003, 1.5 if not is_index else 20.0)
        )
        raw_sl = min(entry_zone_min, effective_vwap) - min_risk_buffer * 0.40
        stop_loss = round(raw_sl, 2)
        risk_pts = max(round(entry_zone_mid - stop_loss, 2), round(min_risk_buffer, 2))

        target_1 = round(entry_zone_mid + 2.0 * risk_pts, 2)
        target_2 = round(entry_zone_mid + 4.0 * risk_pts, 2)
        target_3 = round(entry_zone_mid + 6.0 * risk_pts, 2)
        rr_t1 = round((target_1 - entry_zone_mid) / max(0.01, risk_pts), 1)
        rr_t2 = round((target_2 - entry_zone_mid) / max(0.01, risk_pts), 1)
        no_chase_price = round(high + 0.15 * risk_pts, 2)

    else:
        # BEARISH
        low = (
            float(day_low)
            if (day_low and 0 < day_low <= effective_spot)
            else effective_spot * 0.996
        )
        high = (
            float(day_high)
            if (day_high and day_high >= effective_spot)
            else (effective_vwap if effective_vwap > 0 else effective_spot * 1.006)
        )
        if high <= low:
            high = low * 1.006

        impulse_range = max(high - low, effective_spot * 0.004)

        # Fibonacci Optimal Trade Entry (OTE)
        # 38.2% bounce from low
        fib_382 = low + 0.382 * impulse_range
        # 61.8% bounce from low
        fib_618 = low + 0.618 * impulse_range

        entry_zone_min = round(max(low * 1.001, min(fib_382, effective_vwap * 0.998)), 2)
        entry_zone_max = round(min(high, max(fib_618, effective_vwap * 1.001)), 2)

        if entry_zone_min >= entry_zone_max:
            entry_zone_max = round(effective_vwap * 1.001, 2)
            entry_zone_min = round(min(effective_vwap * 0.998, effective_spot * 1.001), 2)

        entry_zone_mid = round((entry_zone_min + entry_zone_max) / 2.0, 2)

        min_risk_buffer = (
            (atr_5m * 1.20)
            if (atr_5m and atr_5m > 0)
            else max(effective_spot * 0.003, 1.5 if not is_index else 20.0)
        )
        raw_sl = max(entry_zone_max, effective_vwap) + min_risk_buffer * 0.40
        stop_loss = round(raw_sl, 2)
        risk_pts = max(round(stop_loss - entry_zone_mid, 2), round(min_risk_buffer, 2))

        target_1 = round(entry_zone_mid - 2.0 * risk_pts, 2)
        target_2 = round(entry_zone_mid - 4.0 * risk_pts, 2)
        target_3 = round(entry_zone_mid - 6.0 * risk_pts, 2)
        rr_t1 = round((entry_zone_mid - target_1) / max(0.01, risk_pts), 1)
        rr_t2 = round((entry_zone_mid - target_2) / max(0.01, risk_pts), 1)
        no_chase_price = round(low - 0.15 * risk_pts, 2)

    # ── Map to Derivative Option Contract ──────────────────────────
    opt_symbol = None
    opt_entry_limit = None
    opt_sl = None
    opt_t1 = None
    opt_t2 = None

    try:
        resolved_opt = resolve_option_contract(
            symbol=clean_sym,
            spot=entry_zone_mid,  # Price when the limit order fills!
            direction="BULLISH" if is_bull else "BEARISH",
            underlying_sl=stop_loss,
            underlying_target=target_1,
            prefer_options=prefer_options or is_index,
        )
        if resolved_opt and resolved_opt.entry_premium > 0:
            opt_symbol = resolved_opt.contract_symbol
            opt_entry_limit = resolved_opt.entry_premium
            opt_sl = resolved_opt.sl_premium
            opt_t1 = resolved_opt.t1_premium
            opt_t2 = resolved_opt.t2_premium
    except Exception as e_opt:
        logger.debug(
            f"[PullbackLevelResolver] Option resolution non-fatal for {clean_sym}: {e_opt}"
        )

    dir_label = "BUY (CALL)" if is_bull else "SELL (PUT)"
    actionable_summary = (
        f"🎯 [PULLBACK TO VALUE] {clean_sym} {dir_label}: "
        f"Do NOT chase CMP ₹{effective_spot:,.1f}. "
        f"Arm Limit Entry Zone ₹{entry_zone_min:,.1f} - ₹{entry_zone_max:,.1f} "
        f"(Mid: ₹{entry_zone_mid:,.1f}). "
        f"SL: ₹{stop_loss:,.1f} ({risk_pts:,.1f} pts risk). "
        f"T1: ₹{target_1:,.1f} (+{rr_t1}R), T2: ₹{target_2:,.1f} (+{rr_t2}R). "
        f"NO CHASE {'above' if is_bull else 'below'} ₹{no_chase_price:,.1f}."
    )

    return PullbackLevelPlan(
        symbol=clean_sym,
        direction="BULLISH" if is_bull else "BEARISH",
        spot_cmp=effective_spot,
        vwap=effective_vwap,
        entry_zone_min=entry_zone_min,
        entry_zone_max=entry_zone_max,
        entry_zone_mid=entry_zone_mid,
        stop_loss=stop_loss,
        risk_pts=risk_pts,
        target_1=target_1,
        target_2=target_2,
        target_3=target_3,
        rr_t1=rr_t1,
        rr_t2=rr_t2,
        no_chase_price=no_chase_price,
        opt_symbol=opt_symbol,
        opt_entry_limit=opt_entry_limit,
        opt_sl=opt_sl,
        opt_t1=opt_t1,
        opt_t2=opt_t2,
        actionable_summary=actionable_summary,
        metadata={
            "fib_382": fib_382,
            "fib_618": fib_618,
            "impulse_range": impulse_range,
        },
    )
