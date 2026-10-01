"""
engine/detectors/smc_orderblock_retest.py
──────────────────────────────────────────
SMC (Smart Money Concepts) Order Block Re-Test Detector.

Detects when price returns to re-test an unmitigated institutional Order Block (OB)
with a low-risk, high-reward entry opportunity.

Signal Logic:
  1. Fetch daily candles (250 bars) to identify structural Order Blocks
     via analysis.market_structure.
  2. Filter for UNMITIGATED OBs with Tier-1 or Tier-2 quality rating.
  3. Check if current LTP is inside or touching the OB zone:
     - DEMAND OB (bullish): LTP within [OB.bottom - 0.35*ATR, OB.top + 0.35*ATR]
     - SUPPLY OB (bearish): LTP within [OB.bottom - 0.35*ATR, OB.top + 0.35*ATR]
  4. Confirm structural R:R:
     - SL = 0.20*ATR beyond the OB opposite edge (sub-ATR stop means tight risk)
     - T1 = next opposing OB or swing high/low (min 1.5R)
     - T2 = 4.0R extension
     - Reject if T1 R:R < 1.5 or T2 R:R < 3.0
  5. RVOL < 1.8 during re-test (quiet absorption, not panic selling/distribution into OB)
     — large volume on re-test can indicate mitigation/liquidation, not accumulation.

Output: AutoAlert with:
  - alert_type = "SMC_OB_RETEST"
  - stage = "EARLY_WARNING" (price at OB edge, awaiting reversal candle)
  - direction = "BULLISH" | "BEARISH"
  - trigger_level = OB midpoint (OTE price)
  - stop_loss = beyond OB with 0.20*ATR buffer
  - target_level = T1 structural resistance / demand
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_TIER_PRIORITY = {
    "TIER_1_PRIME": 1,
    "TIER_2_VALID": 2,
    "TIER_3_WEAK": 3,
}


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR(14) from OHLCV DataFrame."""
    if df is None or len(df) < period:
        return 0.0
    try:
        h = df["high"] if "high" in df.columns else df.get("High", df.iloc[:, 1])
        l = df["low"] if "low" in df.columns else df.get("Low", df.iloc[:, 2])
        c = df["close"] if "close" in df.columns else df.get("Close", df.iloc[:, 3])
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=period).mean().dropna()
        if len(atr_series) > 0:
            val = float(atr_series.iloc[-1])
            if val > 0:
                return round(val, 4)
    except Exception:
        pass
    return 0.0


def _find_next_structural_target(
    direction: str,
    entry: float,
    stop: float,
    supply_obs: list[Any],
    demand_obs: list[Any],
) -> tuple[float, float, float, str]:
    """
    Finds the nearest opposing structural target (T1), T2 (4R extension), and Runner (6R).
    Returns (t1_price, t2_price, runner_price, t1_rationale).
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0, 0.0, 0.0, ""

    is_bullish = direction.upper() in ("BULLISH", "BUY", "LONG")
    t1 = 0.0
    t1_rationale = ""

    if is_bullish:
        # Avoid immediate ceiling: filter supply OBs that are far enough to allow at least 1.5R
        candidates = [
            ob
            for ob in supply_obs
            if ob.midpoint > entry
            and not getattr(ob, "mitigated", False)
            and (ob.midpoint - entry) / risk >= 1.5
        ]
        if candidates:
            best = min(candidates, key=lambda ob: ob.midpoint)
            t1 = round(best.midpoint, 2)
            t1_rationale = f"Nearest Supply OB midpoint ₹{t1:,.2f} (formed {best.formed_date})"
        else:
            t1 = round(entry + 2.0 * risk, 2)
            t1_rationale = "2.0R structural expansion (no opposing OB within range)"
        t2 = round(entry + 4.0 * risk, 2)
        runner = round(entry + 6.0 * risk, 2)
    else:
        # Avoid immediate floor: filter demand OBs that are far enough to allow at least 1.5R
        candidates = [
            ob
            for ob in demand_obs
            if ob.midpoint < entry
            and not getattr(ob, "mitigated", False)
            and (entry - ob.midpoint) / risk >= 1.5
        ]
        if candidates:
            best = max(candidates, key=lambda ob: ob.midpoint)
            t1 = round(best.midpoint, 2)
            t1_rationale = f"Nearest Demand OB midpoint ₹{t1:,.2f} (formed {best.formed_date})"
        else:
            t1 = round(entry - 2.0 * risk, 2)
            t1_rationale = "2.0R structural expansion (no opposing OB within range)"
        t2 = round(entry - 4.0 * risk, 2)
        runner = round(entry - 6.0 * risk, 2)

    return t1, t2, runner, t1_rationale


def detect_smc_orderblock_retest(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: float = 0.0,
    exchange: str = "NSE",
    rvol: Optional[float] = None,
) -> list[AutoAlert]:
    """
    Scans for price retesting an unmitigated institutional Order Block.

    Args:
        symbol: Clean equity or index symbol (e.g. 'RELIANCE', 'NIFTY')
        df: Daily OHLCV DataFrame (at least 30 bars). Fetched if None.
        ltp: Current last traded price. Fetched if 0.
        exchange: Market exchange (NSE, BSE, NFO, MCX)
        rvol: Relative volume (current / expected avg). Fetched if None.

    Returns:
        List of AutoAlert objects (0–2 per symbol: one bullish, one bearish).
    """
    is_test = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or os.environ.get("DEPLOY_MODE") == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
    )

    clean_sym = canonical_alert_symbol(symbol)
    found: list[AutoAlert] = []

    # ── 1. Fetch OHLCV if not provided ────────────────────────────────────────
    if df is None or len(df) < 30:
        if is_test:
            return []
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, exchange=exchange, interval="day", days=250)
        except Exception as e:
            logger.debug(f"[SMC_OB] OHLCV fetch failed for {clean_sym}: {e}")
            return []

    if df is None or len(df) < 30:
        return []

    # ── 2. Fetch LTP if not provided ──────────────────────────────────────────
    if ltp <= 0:
        if is_test:
            return []
        try:
            from market.quotes import get_ltp

            fetched = get_ltp(f"{exchange}:{clean_sym}")
            if fetched and float(fetched) > 0:
                ltp = float(fetched)
        except Exception:
            return []

    if not ltp or ltp <= 0:
        return []

    # ── 3. Compute ATR (daily, 14-period) ─────────────────────────────────────
    atr = _compute_atr(df, period=14)
    if atr <= 0:
        atr = ltp * 0.015  # 1.5% daily range proxy

    # ── 4. Call SMC Market Structure Engine ───────────────────────────────────
    try:
        from analysis.market_structure import analyze_market_structure

        ms = analyze_market_structure(symbol=clean_sym, df=df, exchange=exchange)
    except Exception as e:
        logger.debug(f"[SMC_OB] Market structure analysis failed for {clean_sym}: {e}")
        return []

    if ms is None:
        return []

    demand_obs = [
        ob
        for ob in getattr(ms, "active_demand_zones", [])
        if ob.type == "DEMAND" and getattr(ob, "is_unmitigated", True)
    ]
    supply_obs = [
        ob
        for ob in getattr(ms, "active_supply_zones", [])
        if ob.type == "SUPPLY" and getattr(ob, "is_unmitigated", True)
    ]

    if not demand_obs and not supply_obs:
        return []

    # ── 5. OB Re-test proximity window ────────────────────────────────────────
    proximity_buffer = max(round(0.35 * atr, 4), ltp * 0.004)
    now_ist = datetime.now(IST)

    # ── 6. Check Demand OB (Bullish Re-test) ──────────────────────────────────
    sorted_demand = sorted(
        demand_obs,
        key=lambda o: _TIER_PRIORITY.get(getattr(o, "quality_tier", ""), 99),
    )
    for ob in sorted_demand:
        ob_zone_low = ob.bottom - proximity_buffer
        ob_zone_high = ob.top + proximity_buffer

        if not (ob_zone_low <= ltp <= ob_zone_high):
            continue

        # Quality gate: Tier-1 and Tier-2 only
        tier = getattr(ob, "quality_tier", "TIER_3_WEAK")
        if tier not in ("TIER_1_PRIME", "TIER_2_VALID"):
            continue

        # RVOL: quiet absorption, not capitulation selling into the block
        if rvol is not None and rvol > 1.8:
            logger.debug(
                f"[SMC_OB] {clean_sym} Demand OB suppressed: RVOL {rvol:.2f} > 1.8 "
                f"(distribution risk into OB)"
            )
            continue

        # Structural levels
        sl_buffer = max(0.20 * atr, ltp * 0.005)
        stop_loss = round(ob.bottom - sl_buffer, 2)
        risk = abs(ltp - stop_loss)
        if risk <= 0:
            continue

        ote_price = getattr(ob, "ote_price", 0.0)
        entry_price = ote_price if ote_price > 0 else round(ob.midpoint, 2)

        t1, t2, runner, t1_rationale = _find_next_structural_target(
            "BULLISH", entry_price, stop_loss, supply_obs, demand_obs
        )
        if t1 <= 0 or t2 <= 0:
            continue

        rr_t1 = round(abs(t1 - entry_price) / risk, 2)
        rr_t2 = round(abs(t2 - entry_price) / risk, 2)

        # Invariant 12: R:R must be institutional grade (T1 >= 1.5R, T2 >= 3.0R)
        if rr_t1 < 1.5 or rr_t2 < 3.0:
            logger.debug(
                f"[SMC_OB] {clean_sym} Demand OB R:R insufficient: T1={rr_t1:.1f}, T2={rr_t2:.1f}"
            )
            continue

        # Conviction scoring
        conviction = 82 if tier == "TIER_1_PRIME" else 75
        has_fvg = getattr(ob, "has_fvg_confluence", False)
        vol_ratio = getattr(ob, "volume_ratio", 1.0)
        ob_count = getattr(ob, "confluence_count", 1)
        if has_fvg:
            conviction = min(92, conviction + 6)
        if vol_ratio >= 2.0:
            conviction = min(92, conviction + 4)

        confluence_factors = [f"Demand OB ({tier}) formed {ob.formed_date}"]
        if has_fvg:
            confluence_factors.append("FVG Confluence: Bullish imbalance overlaps OB")
        if vol_ratio >= 2.0:
            confluence_factors.append(f"High Volume OB: {vol_ratio:.1f}x institutional absorption")
        if ob_count > 1:
            confluence_factors.append(f"Aggregated OB: {ob_count} overlapping blocks")

        alert_id = generate_alert_id(
            clean_sym,
            "SMC_OB_RETEST",
            variant="bull",
        )

        headline = (
            f"🧲 SMC Demand OB Re-Test: {clean_sym} at ₹{ob.bottom:,.2f}–₹{ob.top:,.2f} "
            f"({tier}) | SL ₹{stop_loss:,.2f} | R:R 1:{rr_t2}"
        )
        summary = (
            f"Price retesting unmitigated institutional Demand OB. "
            f"OTE Entry: ₹{entry_price:,.2f}. "
            f"SL: ₹{stop_loss:,.2f} (sub-ATR below OB bottom). "
            f"T1: ₹{t1:,.2f} (+{rr_t1:.1f}R · {t1_rationale}). "
            f"T2: ₹{t2:,.2f} (+{rr_t2:.1f}R extension). "
            f"NO CHASE above ₹{ob.top:,.2f} — OB mitigated if price closes above top."
        )

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type="SMC_OB_RETEST",
            stage="EARLY_WARNING",
            symbol=clean_sym,
            exchange=exchange.upper(),
            direction="BULLISH",
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=entry_price,
            stop_loss=stop_loss,
            target_level=t1,
            confidence=conviction,
            created_at=now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            is_live=not is_test,
            environment="TEST" if is_test else "LIVE",
            metrics={
                "ob_type": "DEMAND",
                "ob_top": ob.top,
                "ob_bottom": ob.bottom,
                "ob_midpoint": ob.midpoint,
                "ob_ote": ote_price,
                "ob_quality_tier": tier,
                "ob_formed_date": ob.formed_date,
                "ob_volume_ratio": vol_ratio,
                "ob_has_fvg": has_fvg,
                "atr_14d": atr,
                "target_1": t1,
                "target_2": t2,
                "runner_target": runner,
                "rr_t1": rr_t1,
                "rr_t2": rr_t2,
                "rvol": rvol,
                "confluence_types": confluence_factors,
                "confluence_factors": confluence_factors,
            },
            actionable_plan={
                "action": "BUY",
                "instrument_type": "EQUITY",
                "entry_range": f"₹{ob.bottom:,.2f} – ₹{ob.top:,.2f}",
                "stop_loss": f"₹{stop_loss:,.2f}",
                "target": f"₹{t1:,.2f}",
                "target_1": f"₹{t1:,.2f}",
                "target_2": f"₹{t2:,.2f}",
                "runner_target": f"₹{runner:,.2f}",
                "risk_reward": f"1:{rr_t2}",
                "no_chase_rule": (
                    f"DO NOT ENTER above ₹{ob.top:,.2f} — "
                    f"OB mitigated once price closes above its top."
                ),
                "trade_plan": {
                    "entry_price": entry_price,
                    "invalidation_stop": stop_loss,
                    "target_1": t1,
                    "target_2": t2,
                    "runner_target": runner,
                    "rr_t1": rr_t1,
                    "rr_t2": rr_t2,
                },
            },
        )
        found.append(alert)
        break  # One bullish OB alert per symbol per session

    # ── 7. Check Supply OB (Bearish Re-test) ──────────────────────────────────
    sorted_supply = sorted(
        supply_obs,
        key=lambda o: _TIER_PRIORITY.get(getattr(o, "quality_tier", ""), 99),
    )
    for ob in sorted_supply:
        ob_zone_low = ob.bottom - proximity_buffer
        ob_zone_high = ob.top + proximity_buffer

        if not (ob_zone_low <= ltp <= ob_zone_high):
            continue

        tier = getattr(ob, "quality_tier", "TIER_3_WEAK")
        if tier not in ("TIER_1_PRIME", "TIER_2_VALID"):
            continue

        if rvol is not None and rvol > 1.8:
            logger.debug(
                f"[SMC_OB] {clean_sym} Supply OB suppressed: RVOL {rvol:.2f} > 1.8 "
                f"(breakout squeeze risk)"
            )
            continue

        sl_buffer = max(0.20 * atr, ltp * 0.005)
        stop_loss = round(ob.top + sl_buffer, 2)
        risk = abs(stop_loss - ltp)
        if risk <= 0:
            continue

        ote_price = getattr(ob, "ote_price", 0.0)
        entry_price = ote_price if ote_price > 0 else round(ob.midpoint, 2)

        t1, t2, runner, t1_rationale = _find_next_structural_target(
            "BEARISH", entry_price, stop_loss, supply_obs, demand_obs
        )
        if t1 <= 0 or t2 <= 0:
            continue

        rr_t1 = round(abs(entry_price - t1) / risk, 2)
        rr_t2 = round(abs(entry_price - t2) / risk, 2)

        if rr_t1 < 1.5 or rr_t2 < 3.0:
            logger.debug(
                f"[SMC_OB] {clean_sym} Supply OB R:R insufficient: T1={rr_t1:.1f}, T2={rr_t2:.1f}"
            )
            continue

        conviction = 82 if tier == "TIER_1_PRIME" else 75
        has_fvg = getattr(ob, "has_fvg_confluence", False)
        vol_ratio = getattr(ob, "volume_ratio", 1.0)
        ob_count = getattr(ob, "confluence_count", 1)
        if has_fvg:
            conviction = min(92, conviction + 6)
        if vol_ratio >= 2.0:
            conviction = min(92, conviction + 4)

        confluence_factors = [f"Supply OB ({tier}) formed {ob.formed_date}"]
        if has_fvg:
            confluence_factors.append("FVG Confluence: Bearish imbalance overlaps OB")
        if vol_ratio >= 2.0:
            confluence_factors.append(
                f"High Volume OB: {vol_ratio:.1f}x institutional distribution"
            )

        alert_id = generate_alert_id(
            clean_sym,
            "SMC_OB_RETEST",
            variant="bear",
        )

        headline = (
            f"🔴 SMC Supply OB Re-Test: {clean_sym} at ₹{ob.bottom:,.2f}–₹{ob.top:,.2f} "
            f"({tier}) | SL ₹{stop_loss:,.2f} | R:R 1:{rr_t2}"
        )
        summary = (
            f"Price retesting unmitigated institutional Supply OB. "
            f"OTE Short Entry: ₹{entry_price:,.2f}. "
            f"SL: ₹{stop_loss:,.2f} (sub-ATR above OB top). "
            f"T1: ₹{t1:,.2f} (-{rr_t1:.1f}R · {t1_rationale}). "
            f"T2: ₹{t2:,.2f} (-{rr_t2:.1f}R extension). "
            f"NO CHASE below ₹{ob.bottom:,.2f} — OB mitigated if price closes below bottom."
        )

        alert = AutoAlert(
            alert_id=alert_id,
            alert_type="SMC_OB_RETEST",
            stage="EARLY_WARNING",
            symbol=clean_sym,
            exchange=exchange.upper(),
            direction="BEARISH",
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=entry_price,
            stop_loss=stop_loss,
            target_level=t1,
            confidence=conviction,
            created_at=now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            is_live=not is_test,
            environment="TEST" if is_test else "LIVE",
            metrics={
                "ob_type": "SUPPLY",
                "ob_top": ob.top,
                "ob_bottom": ob.bottom,
                "ob_midpoint": ob.midpoint,
                "ob_ote": ote_price,
                "ob_quality_tier": tier,
                "ob_formed_date": ob.formed_date,
                "ob_volume_ratio": vol_ratio,
                "ob_has_fvg": has_fvg,
                "atr_14d": atr,
                "target_1": t1,
                "target_2": t2,
                "runner_target": runner,
                "rr_t1": rr_t1,
                "rr_t2": rr_t2,
                "rvol": rvol,
                "confluence_types": confluence_factors,
                "confluence_factors": confluence_factors,
            },
            actionable_plan={
                "action": "SELL_SHORT",
                "instrument_type": "EQUITY",
                "entry_range": f"₹{ob.bottom:,.2f} – ₹{ob.top:,.2f}",
                "stop_loss": f"₹{stop_loss:,.2f}",
                "target": f"₹{t1:,.2f}",
                "target_1": f"₹{t1:,.2f}",
                "target_2": f"₹{t2:,.2f}",
                "runner_target": f"₹{runner:,.2f}",
                "risk_reward": f"1:{rr_t2}",
                "no_chase_rule": (
                    f"DO NOT ENTER below ₹{ob.bottom:,.2f} — "
                    f"OB mitigated once price closes below its bottom."
                ),
                "trade_plan": {
                    "entry_price": entry_price,
                    "invalidation_stop": stop_loss,
                    "target_1": t1,
                    "target_2": t2,
                    "runner_target": runner,
                    "rr_t1": rr_t1,
                    "rr_t2": rr_t2,
                },
            },
        )
        found.append(alert)
        break  # One bearish OB alert per symbol per session

    return found
