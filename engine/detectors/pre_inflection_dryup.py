"""
engine/detectors/pre_inflection_dryup.py
────────────────────────────────────────
Early-Warning Pre-Inflection Detector: Volume Dry-Up, Range Compression & Fair Value Accumulation.

Institutional Intent:
  Traders suffer from FOMO when alerted *after* a stock has already spiked 10-20% on high volume.
  This detector alerts ON OR BEFORE TIME — during the silent accumulation phase:
    1. Volume Dry-Up (Seller Exhaustion): Recent 3–5 bar volume contracts to <= 40% of 50-day SMA.
    2. Volatility Range Compression: High-Low daily spread drops to <= 1.5% of price (spring coiled).
    3. Anchored to Fair Value: Price is nestled right at the Volume Profile POC or Anchored VWAP.
    4. Anti-FOMO Execution Ticket: Strict entry range at fair value, clear invalidation stop,
       and an explicit "DO NOT CHASE" limit price (+2.0% max).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def detect_pre_inflection_dryup(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
) -> Optional[AutoAlert]:
    """
    Detects quiet, low-volume institutional accumulation bases before the breakout ignition.
    Generates an EARLY_WARNING alert with anti-FOMO fair-value entry brackets.
    """
    if df is None or len(df) < 25 or ltp <= 0:
        return None

    try:
        closes = df["close"].values if "close" in df.columns else df["Close"].values
        highs = df["high"].values if "high" in df.columns else df["High"].values
        lows = df["low"].values if "low" in df.columns else df["Low"].values
        volumes = df["volume"].values if "volume" in df.columns else np.ones(len(df))
        n = len(df)

        # 1. Volume Dry-Up Verification (Last 3-5 bars vs 50-day average)
        vol_50 = float(np.mean(volumes[-50:])) if n >= 50 else float(np.mean(volumes))
        vol_recent_3 = float(np.mean(volumes[-3:])) if n >= 3 else float(volumes[-1])
        vol_dryup_ratio = vol_recent_3 / vol_50 if vol_50 > 0 else 1.0

        # Dry-up condition: Volume <= 55% of average (ideal <= 40%)
        if vol_dryup_ratio > 0.55:
            return None

        # 2. Volatility Compression Check (Daily High-Low Spread)
        recent_ranges_pct = [
            ((highs[-i] - lows[-i]) / closes[-i]) * 100
            for i in range(1, min(4, n))
            if closes[-i] > 0
        ]
        avg_range_pct = float(np.mean(recent_ranges_pct)) if recent_ranges_pct else 2.5

        # Compression condition: Average range <= 1.8% of price
        if avg_range_pct > 1.8:
            return None

        # 3. Fair Value Anchor & Support Proximity
        # Compute 20-day Volume Profile POC or 20-SMA baseline
        try:
            from analysis.volume_profile import compute_volume_profile
            poc_price, vah_price, val_price, _ = compute_volume_profile(df, num_bins=10)
            if poc_price > 0:
                fair_value = poc_price
                fv_name = "Volume Profile POC"
            else:
                fair_value = float(np.mean(closes[-20:]))
                fv_name = "20-EMA Base"
        except Exception:
            fair_value = float(np.mean(closes[-20:])) if n >= 20 else ltp
            fv_name = "20-EMA Base"

        dist_from_fv_pct = abs(ltp - fair_value) / fair_value * 100 if fair_value > 0 else 0
        # Must be within 2.5% of fair value to avoid chasing extended prices
        if dist_from_fv_pct > 2.5:
            return None

        # 4. Conviction Scoring (0 to 100)
        score = 65
        # Stronger volume dry-up gives more points
        if vol_dryup_ratio <= 0.35:
            score += 15
        elif vol_dryup_ratio <= 0.45:
            score += 10

        # Tighter range gives more points
        if avg_range_pct <= 1.2:
            score += 15
        elif avg_range_pct <= 1.5:
            score += 8

        # 5. Anti-FOMO Execution Ticket Generation
        pivot_high = round(float(np.max(highs[-15:])), 2)
        accum_low = round(fair_value * 0.985, 2)
        accum_high = round(fair_value * 1.015, 2)
        no_chase_limit = round(pivot_high * 1.02, 2)  # Strict +2.0% rule
        pullback_limit = round(max(fair_value, pivot_high * 0.985), 2)

        # Invalidation Stop: Placed just below the tight consolidation base low
        base_low = round(float(np.min(lows[-15:])), 2)
        sl = round(min(ltp * 0.975, base_low * 0.995), 2)
        risk_pts = max(1.0, round(ltp - sl, 2))

        target_1 = round(ltp + 2.0 * risk_pts, 2)
        target_2 = round(ltp + 4.0 * risk_pts, 2)
        rr_str = f"1:{(4.0 * risk_pts / risk_pts):.1f}"

        now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

        headline = f"🤫 PRE-INFLECTION DRY-UP: {clean_sym} at ₹{ltp:,.1f} (Fair Value Zone)"
        summary = (
            f"Pre-ignition footprint detected: Volume dried up to {vol_dryup_ratio * 100:.0f}% of average "
            f"with tight {avg_range_pct:.1f}% daily range. Price is resting right at {fv_name} (₹{fair_value:,.1f}). "
            f"Enter within fair-value accumulation zone before the breakout candle detonates."
        )

        actionable_plan = {
            "action": "ACCUMULATE_FAIR_VALUE",
            "fair_value_anchor": f"₹{fair_value:,.1f} ({fv_name})",
            "entry_range": f"₹{accum_low:,.1f} – ₹{accum_high:,.1f}",
            "pivot_trigger": f"₹{pivot_high:,.1f}",
            "do_not_chase_above": f"₹{no_chase_limit:,.1f} (+2.0% ceiling)",
            "pullback_limit_order": f"₹{pullback_limit:,.1f}",
            "stop_loss": f"₹{sl:,.1f}",
            "target_1": f"₹{target_1:,.1f} (+2R)",
            "target_2": f"₹{target_2:,.1f} (+4R)",
            "risk_reward": rr_str,
            "anti_fomo_rule": (
                f"Accumulate between ₹{accum_low:,.1f} and ₹{accum_high:,.1f}. "
                f"If price gaps above ₹{no_chase_limit:,.1f}, DO NOT CHASE — place limit order at ₹{pullback_limit:,.1f}."
            ),
        }

        return AutoAlert(
            alert_id=generate_alert_id(clean_sym, "PRE_INFLECTION_DRYUP", variant="dryup"),
            alert_type="PRE_INFLECTION_DRYUP",
            stage="EARLY_WARNING",
            symbol=clean_sym,
            exchange=exchange,
            direction="BULLISH",
            headline=headline,
            summary=summary,
            ltp=ltp,
            trigger_level=fair_value,
            target_level=target_1,
            stop_loss=sl,
            metrics={
                "vol_dryup_ratio": round(vol_dryup_ratio, 2),
                "avg_range_pct": round(avg_range_pct, 2),
                "fair_value": fair_value,
                "fair_value_source": fv_name,
                "pivot_high": pivot_high,
                "no_chase_limit": no_chase_limit,
            },
            actionable_plan=actionable_plan,
            confidence=score,
            created_at=now_iso,
        )
    except Exception as e:
        logger.debug(f"[PreInflectionDryUp] Error evaluating {symbol}: {e}")
        return None
