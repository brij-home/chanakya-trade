"""
analysis/delivery_accumulation.py
─────────────────────────────────
Institutional Cumulative Free-Float Absorption Index (CFAI) & Stealth Delivery Accumulation Engine.

Identifies the "Whale Footprint" in Indian Equities:
Unlike intraday churn, Cash Delivery requires 100% upfront capital and transfer into Demat accounts
(paying 0.1% STT both ways). When institutions accumulate over multiple weeks:
  1. Delivery % expands significantly above baseline (often 55%–75%+).
  2. Price volatility tightens (Mark Minervini Volatility Contraction / Wyckoff Base).
  3. Cumulative Net Delivery absorbs a significant chunk of the tradable Free Float (4%–15%+).
  4. Floating Supply Exhaustion occurs: With free float locked in Demat accounts, any demand
     spark produces explosive, asymmetric Stage 2 breakouts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("analysis.delivery_accumulation")


@dataclass
class CFAIReport:
    """Institutional report on cumulative delivery absorption and floating supply exhaustion."""

    symbol: str
    ltp: float
    current_delivery_pct: float
    avg_delivery_pct_20d: float
    is_delivery_spike: bool

    # Free Float & Cumulative Absorption
    estimated_total_shares: int
    promoter_holding_pct: float
    estimated_free_float_shares: int
    net_excess_delivery_20d: int
    cfai_pct: float  # Cumulative Free-Float Absorption Index (0% - 100%)

    # Price Base & Supply Exhaustion
    base_tightness_pct: float  # 20-day high-low range as % of price
    float_exhaustion_detected: bool  # True when float is cornered in tight base
    accumulation_score: int  # 0 to 100 composite score
    verdict: str  # "HIGH_STEALTH_ACCUMULATION" | "MODERATE_ABSORPTION" | "NEUTRAL" | "DISTRIBUTION"
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_cfai(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    total_shares: Optional[int] = None,
    promoter_holding_pct: Optional[float] = None,
    ltp: Optional[float] = None,
) -> CFAIReport:
    """
    Computes the Cumulative Free-Float Absorption Index (CFAI) for a given stock.

    Args:
        symbol: NSE/BSE stock symbol (e.g. "MAZDOCK", "TRENT", "HAL").
        df: Daily OHLCV DataFrame with optional 'delivery_pct' or 'delivery_quantity' columns.
        total_shares: Total listed shares (optional, estimated from market cap if missing).
        promoter_holding_pct: Promoter + Govt shareholding percentage (default: 55.0%).
        ltp: Current market price (optional, fallback from df).
    """
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip().upper()

    # 1. Resolve Price & Historical Data
    if df is None or len(df) < 5:
        # Fallback minimal synthetic baseline if no history available
        current_ltp = float(ltp or 1000.0)
        tot_shares = int(total_shares or 100_000_000)
        prom_pct = float(promoter_holding_pct or 55.0)
        ff_shares = int(tot_shares * ((100.0 - prom_pct) / 100.0))
        return CFAIReport(
            symbol=clean_sym,
            ltp=round(current_ltp, 2),
            current_delivery_pct=35.0,
            avg_delivery_pct_20d=35.0,
            is_delivery_spike=False,
            estimated_total_shares=tot_shares,
            promoter_holding_pct=prom_pct,
            estimated_free_float_shares=ff_shares,
            net_excess_delivery_20d=0,
            cfai_pct=0.0,
            base_tightness_pct=8.0,
            float_exhaustion_detected=False,
            accumulation_score=50,
            verdict="NEUTRAL",
            insights=["Insufficient historical delivery bars for full CFAI matrix."],
        )

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    n = len(df)
    current_ltp = float(ltp or closes[-1])

    # 2. Extract or Synthesize Delivery Series
    if "delivery_pct" in df.columns:
        delivery_pct_series = df["delivery_pct"].astype(float).values
    elif "delivery_quantity" in df.columns:
        dq = df["delivery_quantity"].astype(float).values
        delivery_pct_series = np.clip((dq / np.maximum(volumes, 1.0)) * 100.0, 0.0, 100.0)
    else:
        # If delivery column absent, infer institutional absorption proxy from close-in-range & volume
        # High volume on up-days with close in upper 25% of bar implies strong delivery backing
        up_spread = (closes - lows) / np.maximum(highs - lows, 0.001)
        delivery_pct_series = np.clip(30.0 + (up_spread * 35.0), 10.0, 85.0)

    cur_deliv_pct = float(delivery_pct_series[-1])
    lookback_deliv = delivery_pct_series[-min(20, n) :]
    avg_deliv_20d = float(np.mean(lookback_deliv))

    # Baseline delivery represents normal non-institutional churn (typically ~35% or earlier 50D mean)
    baseline_deliv_pct = (
        float(np.mean(delivery_pct_series[-min(50, n) : -min(20, n)])) if n >= 35 else 35.0
    )
    baseline_deliv_pct = max(25.0, min(45.0, baseline_deliv_pct))

    is_deliv_spike = cur_deliv_pct >= max(55.0, avg_deliv_20d * 1.20) or (
        cur_deliv_pct >= 65.0 and avg_deliv_20d >= 48.0
    )

    # 3. Estimate Shares & Free Float
    # If not provided, estimate total shares based on realistic standard capital pool
    if total_shares is None or total_shares <= 0:
        # Default typical midcap/largecap total shares ~150 Million
        total_shares = 150_000_000

    if promoter_holding_pct is None or promoter_holding_pct <= 0:
        promoter_holding_pct = 54.0  # Median Indian promoter holding

    promoter_holding_pct = min(95.0, max(5.0, promoter_holding_pct))
    free_float_pct = max(5.0, 100.0 - promoter_holding_pct)
    free_float_shares = int(total_shares * (free_float_pct / 100.0))

    # 4. Calculate Net Excess Delivery Volume over 20 Sessions
    # Net excess delivery = Delivery volume above the normal non-institutional baseline (~35%)
    vol_lookback = volumes[-min(20, n) :]
    baseline_deliv_qty = np.mean(vol_lookback) * (baseline_deliv_pct / 100.0)

    actual_deliv_qty_20d = vol_lookback * (lookback_deliv / 100.0)
    excess_deliv_20d = np.maximum(0.0, actual_deliv_qty_20d - baseline_deliv_qty)
    net_excess_delivery_shares = int(np.sum(excess_deliv_20d))

    # 5. Compute CFAI Ratio (%)
    # Percentage of total free float pulled into Demat delivery above baseline
    cfai_pct = round((net_excess_delivery_shares / max(1.0, float(free_float_shares))) * 100.0, 2)

    # 6. Price Base Tightness (Minervini / Wyckoff Base)
    # Range of high to low over last 20 bars as % of current price
    h20 = float(np.max(highs[-min(20, n) :]))
    l20 = float(np.min(lows[-min(20, n) :]))
    base_tightness_pct = round(((h20 - l20) / max(1.0, current_ltp)) * 100.0, 2)

    # 7. Float Exhaustion Condition
    # High cumulative absorption (>= 3.5%) while price is coiling (base tightness <= 14.0%)
    # CRITICAL: Must NOT be in a downward distribution trend (20D return must be >= -2.0%)
    p_change_20d = float((closes[-1] - closes[-min(20, n)]) / max(1.0, closes[-min(20, n)]) * 100.0)
    is_downtrend = p_change_20d < -2.5

    float_exhaustion = (not is_downtrend) and (
        (cfai_pct >= 3.5 and base_tightness_pct <= 14.0)
        or (cfai_pct >= 5.0 and base_tightness_pct <= 18.0)
    )

    # 8. Composite Institutional Accumulation Score (0 to 100)
    score = 50

    # CFAI Absorption Points (up to +25)
    if not is_downtrend:
        if cfai_pct >= 6.0:
            score += 25
        elif cfai_pct >= 4.0:
            score += 18
        elif cfai_pct >= 2.0:
            score += 10
    else:
        # High delivery during a price breakdown = aggressive institutional selling / distribution
        score -= 25

    # Delivery Spike & Consistency Points (up to +20)
    if not is_downtrend:
        if is_deliv_spike:
            score += 12
        if avg_deliv_20d >= 50.0:
            score += 8
        elif avg_deliv_20d >= 40.0:
            score += 4
    else:
        if avg_deliv_20d >= 50.0:
            score -= 10

    # Volatility Tightness Points (Supply drying up inside base) (up to +15)
    if not is_downtrend:
        if base_tightness_pct <= 8.0:
            score += 15
        elif base_tightness_pct <= 12.0:
            score += 10

    # Closing Range Quality: Close near highs on high delivery bars (+10) vs close at lows (-20)
    if n >= 2:
        last_day_range = max(0.01, highs[-1] - lows[-1])
        close_pos = (closes[-1] - lows[-1]) / last_day_range
        if close_pos >= 0.70 and cur_deliv_pct >= 45.0:
            score += 10
        elif close_pos <= 0.30:
            # Closing in lower third on delivery = distribution pressure
            score -= 20

    score = int(np.clip(score, 10, 99))

    # 9. Categorize Verdict & Insights
    insights: list[str] = []

    if float_exhaustion and score >= 75:
        verdict = "HIGH_STEALTH_ACCUMULATION"
        insights.append(
            f"🎯 Floating Supply Exhaustion: {cfai_pct}% of entire tradable free float absorbed over 20 sessions."
        )
        insights.append(
            f"Consolidation tightness ({base_tightness_pct}%) indicates institutional supply absorption without runaway price expansion."
        )
    elif score >= 60 and not is_downtrend:
        verdict = "MODERATE_ABSORPTION"
        insights.append(
            f"Steady institutional accumulation: 20D delivery avg is {avg_deliv_20d:.1f}% (CFAI: {cfai_pct}%)."
        )
    elif is_downtrend or score <= 40:
        verdict = "DISTRIBUTION"
        insights.append(
            f"Distribution Warning: Heavy delivery accompanied by 20D downward drift ({p_change_20d:+.1f}%) signals institutional supply liquidation."
        )
    else:
        verdict = "NEUTRAL"
        insights.append(
            "Delivery activity aligned with historical normal baseline; no extreme float cornering detected."
        )

    if is_deliv_spike:
        insights.append(
            f"⚡ Delivery Spike: Today's delivery ({cur_deliv_pct:.1f}%) exceeds 20D baseline by {cur_deliv_pct - avg_deliv_20d:+.1f}%."
        )

    return CFAIReport(
        symbol=clean_sym,
        ltp=round(current_ltp, 2),
        current_delivery_pct=round(cur_deliv_pct, 1),
        avg_delivery_pct_20d=round(avg_deliv_20d, 1),
        is_delivery_spike=is_deliv_spike,
        estimated_total_shares=total_shares,
        promoter_holding_pct=round(promoter_holding_pct, 1),
        estimated_free_float_shares=free_float_shares,
        net_excess_delivery_20d=net_excess_delivery_shares,
        cfai_pct=cfai_pct,
        base_tightness_pct=base_tightness_pct,
        float_exhaustion_detected=float_exhaustion,
        accumulation_score=score,
        verdict=verdict,
        insights=insights,
    )
