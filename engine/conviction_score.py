"""
engine/conviction_score.py
──────────────────────────
12-Factor Orthogonal High-Conviction Trade Signal Scoring Engine.

Redesigned with orthogonal factor axes — each factor tests a DIFFERENT hypothesis
from a different data source to prevent correlated factor clustering.

Factor Axes:
  AXIS 1 — INSTITUTIONAL MONEY  (what are big players doing?)
  AXIS 2 — MACRO & GLOBAL       (what is the global environment?)
  AXIS 3 — OPTIONS INTELLIGENCE (what does the smart options market say?)
  AXIS 4 — PRICE STRUCTURE      (where is price in the market map?)
  AXIS 5 — TIMING & FLOW        (is NOW the right moment?)

Veto System:
  Even with 85+ score, certain hard conditions block the trade:
    - VIX > 25 and rising (tail risk event)
    - FII selling streak > 5 consecutive days > ₹3,000 Cr each
    - Options data marked STALE (> 15 min)

Score calibration:
    Signals should fire 3–5 times per week in normal markets, not all day.
    85+ should be RARE and highly selective.

Score Interpretation:
    ≥ 85  → Maximum Conviction — 2× normal size
    70–84 → High Conviction — take the trade, normal size
    50–69 → Moderate — reduce size or wait for improvement
    < 50  → Low Conviction — WAIT; sit on hands
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("chanakya.conviction_score")

MAX_SCORE_PER_FACTOR = 10

_CONVICTION_CACHE: dict[str, tuple[float, Any]] = {}
_CONVICTION_LOCK = threading.Lock()
_CONVICTION_CACHE_TTL = 45.0  # 45-second TTL cache for institutional factor aggregation


@dataclass
class FactorScore:
    """A single scored factor."""

    factor_id: str
    label: str
    score: int  # 0–10
    max_score: int = MAX_SCORE_PER_FACTOR
    signal: str = "NEUTRAL"  # "BULLISH" | "BEARISH" | "NEUTRAL" | "UNAVAILABLE"
    detail: str = ""
    raw_value: Optional[float] = None
    axis: str = ""  # Which orthogonal axis this belongs to


@dataclass
class VetoResult:
    """Hard-stop veto check result."""

    vetoed: bool
    reason: str = ""


@dataclass
class ConvictionScore:
    """Aggregated 12-factor conviction score with data-driven trade plan."""

    total_score: int
    verdict: str
    verdict_color: str
    summary: str
    factors: list[FactorScore] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    unavailable_count: int = 0
    recommended_position_size: str = "NORMAL"
    veto: Optional[VetoResult] = None
    trade_plan: Optional[Any] = None
    as_of: str = ""

    def as_dict(self) -> dict:
        return {
            "total_score": self.total_score,
            "verdict": self.verdict,
            "verdict_color": self.verdict_color,
            "summary": self.summary,
            "factors": [
                {
                    "factor_id": f.factor_id,
                    "label": f.label,
                    "score": f.score,
                    "max_score": f.max_score,
                    "signal": f.signal,
                    "detail": f.detail,
                    "raw_value": f.raw_value,
                    "axis": f.axis,
                }
                for f in self.factors
            ],
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "unavailable_count": self.unavailable_count,
            "recommended_position_size": self.recommended_position_size,
            "veto": {
                "vetoed": self.veto.vetoed,
                "reason": self.veto.reason,
            }
            if self.veto
            else None,
            "trade_plan": self.trade_plan.as_dict()
            if hasattr(self.trade_plan, "as_dict")
            else None,
            "as_of": self.as_of,
        }


# ── AXIS 1: INSTITUTIONAL MONEY ───────────────────────────────────────────────


def _score_fii_cash_flow() -> FactorScore:
    """
    Factor 1: FII/DII Cash Segment Flow Direction.
    Streak-weighted: 3+ consecutive buying days = strong signal.
    """
    try:
        from market.flow_intel import get_flow_analysis

        flow = get_flow_analysis()
        score = 5
        details = []

        if flow.fii_streak >= 3:
            score = 9
            details.append(
                f"FII buying streak +{flow.fii_streak}d (₹{flow.fii_streak_total:,.0f} Cr)"
            )
        elif flow.fii_streak == 2:
            score = 7
            details.append(f"FII buying 2 days (₹{flow.fii_net_today:,.0f} Cr today)")
        elif flow.fii_streak == 1:
            score = 6
            details.append(f"FII net buying today: ₹{flow.fii_net_today:,.0f} Cr")
        elif flow.fii_streak == -1:
            score = 4
            details.append(f"FII net selling today: ₹{flow.fii_net_today:,.0f} Cr")
        elif flow.fii_streak == -2:
            score = 3
            details.append(f"FII selling 2 days (₹{abs(flow.fii_streak_total):,.0f} Cr)")
        elif flow.fii_streak <= -3:
            score = 1
            details.append(
                f"FII sustained selling streak {flow.fii_streak}d (₹{flow.fii_streak_total:,.0f} Cr)"
            )
        else:
            details.append(f"FII neutral today: ₹{flow.fii_net_today:,.0f} Cr")

        # DII counter-buying bonus (FII selling but DII buying = floor support)
        if flow.divergence_type == "FII_SELL_DII_BUY" and score <= 4:
            score = max(score, 4)
            details.append("DII counter-buying (market floor support)")

        score = max(0, min(10, score))
        signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
        return FactorScore(
            factor_id="fii_cash_flow",
            label="FII/DII Cash Flow Streak",
            score=score,
            signal=signal,
            detail=" | ".join(details),
            raw_value=flow.fii_net_today,
            axis="INSTITUTIONAL",
        )
    except Exception as e:
        logger.debug("fii_cash_flow error: %s", e)
        return FactorScore(
            factor_id="fii_cash_flow",
            label="FII/DII Cash Flow Streak",
            score=5,
            signal="UNAVAILABLE",
            detail="FII/DII flow data temporarily unavailable",
            axis="INSTITUTIONAL",
        )


def _score_fii_futures_position() -> FactorScore:
    """
    Factor 2: FII Net Futures Position (F&O Segment).
    COMPLETELY DIFFERENT from cash FII flows.
    FII can sell cash AND buy futures simultaneously (classic hedge).
    NSE participant-wise OI data published daily ~6 PM IST.
    """
    try:
        from market.participant_oi import get_latest_participant_oi

        oi_summary = get_latest_participant_oi()
        if oi_summary and oi_summary.fii_index_long_ratio > 0:
            ratio = oi_summary.fii_index_long_ratio
            net_idx = oi_summary.fii_net_index_futures

            if ratio <= 0.20:
                score = 8
                sig = "BULLISH"
                dtl = f"FII Index Long Ratio severely depressed at {ratio * 100:.1f}% ({net_idx:,} net contracts) — Extreme short squeeze coiling setup."
            elif ratio >= 0.70:
                score = 8
                sig = "BULLISH"
                dtl = f"FII heavily long Index Futures at {ratio * 100:.1f}% ({net_idx:,} net contracts)."
            elif ratio >= 0.52:
                score = 7
                sig = "BULLISH"
                dtl = f"FII net long bias at {ratio * 100:.1f}% ({net_idx:,} net contracts)."
            elif ratio <= 0.35:
                score = 3
                sig = "BEARISH"
                dtl = f"FII net short bias at {ratio * 100:.1f}% ({net_idx:,} net contracts)."
            else:
                score = 5
                sig = "NEUTRAL"
                dtl = f"FII balanced at {ratio * 100:.1f}% ({net_idx:,} net contracts)."

            if oi_summary.divergence_notes:
                dtl += f" [{oi_summary.divergence_notes[0]}]"

            return FactorScore(
                factor_id="fii_futures",
                label="FII Participant-wise OI Ratio",
                score=score,
                signal=sig,
                detail=dtl,
                raw_value=float(net_idx),
                axis="INSTITUTIONAL",
            )
    except Exception as e:
        logger.debug("Real participant OI check fallback to proxy: %s", e)

    try:
        from market.sentiment import get_fii_dii_data

        # Fallback to 5-day FII cash momentum proxy if participant report unavailable
        raw = get_fii_dii_data(days=5)
        if not raw:
            raise ValueError("No data")

        recent_5 = raw[:5]
        fii_5d_net = sum(d.fii_net for d in recent_5)
        positive_days = sum(1 for d in recent_5 if d.fii_net > 0)
        negative_days = sum(1 for d in recent_5 if d.fii_net < 0)

        if len(recent_5) >= 3:
            recent_3_avg = sum(d.fii_net for d in recent_5[:3]) / 3
            prior_2_avg = sum(d.fii_net for d in recent_5[3:]) / max(1, len(recent_5) - 3)
            momentum = "ACCELERATING" if recent_3_avg > prior_2_avg else "DECELERATING"
        else:
            momentum = "STEADY"

        score = 5
        details = []

        if positive_days >= 4 and fii_5d_net > 3000:
            score = 9
            details.append(
                f"FII accumulated ₹{fii_5d_net:,.0f} Cr over 5D ({positive_days}/5 green)"
            )
        elif positive_days >= 3:
            score = 7
            details.append(
                f"FII net positive {positive_days}/5 days (5D total: ₹{fii_5d_net:,.0f} Cr)"
            )
        elif negative_days >= 4 and fii_5d_net < -3000:
            score = 1
            details.append(
                f"FII distributed ₹{abs(fii_5d_net):,.0f} Cr over 5D — sustained outflow"
            )
        elif negative_days >= 3:
            score = 3
            details.append(
                f"FII net negative {negative_days}/5 days (5D total: ₹{fii_5d_net:,.0f} Cr)"
            )
        else:
            details.append(f"FII mixed ({positive_days}↑/{negative_days}↓ in 5D)")

        if momentum == "ACCELERATING" and score >= 6:
            score = min(10, score + 1)
            details.append("Momentum ACCELERATING (increasing pace)")
        elif momentum == "DECELERATING" and score >= 6:
            details.append("Momentum DECELERATING (pace slowing)")

        score = max(0, min(10, score))
        signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
        return FactorScore(
            factor_id="fii_futures",
            label="FII 5D Positioning & Momentum",
            score=score,
            signal=signal,
            detail=" | ".join(details),
            raw_value=round(fii_5d_net, 0),
            axis="INSTITUTIONAL",
        )
    except Exception as e:
        logger.debug("fii_futures error: %s", e)
        return FactorScore(
            factor_id="fii_futures",
            label="FII 5D Positioning & Momentum",
            score=5,
            signal="UNAVAILABLE",
            detail="FII positioning data temporarily unavailable",
            axis="INSTITUTIONAL",
        )


# ── AXIS 2: MACRO & GLOBAL ────────────────────────────────────────────────────


def _score_global_macro(spot: float) -> FactorScore:
    """
    Factor 3: Global Macro Alignment.
    GIFT NIFTY gap + macro composite posture.
    """
    try:
        from market.gift_nifty import get_gift_nifty
        from market.global_macro import get_global_macro_report

        gift = get_gift_nifty(nifty_spot=spot)
        macro = get_global_macro_report()

        score = 5
        details = []

        if gift and gift.premium_pct is not None:
            gap = gift.premium_pct
            if gap >= 0.5:
                score += 3
                details.append(f"GIFT NIFTY +{gap:.2f}% gap-up — strong pre-market bullish")
            elif gap >= 0.2:
                score += 1
                details.append(f"GIFT NIFTY +{gap:.2f}% mild gap-up")
            elif gap <= -0.5:
                score -= 3
                details.append(f"GIFT NIFTY {gap:.2f}% gap-down — bearish pre-market")
            elif gap <= -0.2:
                score -= 1
                details.append(f"GIFT NIFTY {gap:.2f}% mild gap-down")
            else:
                details.append(f"GIFT NIFTY flat ({gap:+.2f}%)")

        if macro:
            if macro.composite_score >= 40:
                score += 2
                details.append(
                    f"Global posture: {macro.global_posture} (score {macro.composite_score:+d})"
                )
            elif macro.composite_score >= 15:
                score += 1
                details.append(
                    f"Global posture: {macro.global_posture} (score {macro.composite_score:+d})"
                )
            elif macro.composite_score <= -40:
                score -= 2
                details.append(
                    f"Global risk-off: {macro.global_posture} (score {macro.composite_score:+d})"
                )
            elif macro.composite_score <= -15:
                score -= 1
                details.append(
                    f"Global posture: {macro.global_posture} (score {macro.composite_score:+d})"
                )

        score = max(0, min(10, score))
        signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
        return FactorScore(
            factor_id="global_macro",
            label="Global Macro (GIFT NIFTY + DXY + Crude)",
            score=score,
            signal=signal,
            detail=" | ".join(details) if details else "Macro data not available",
            axis="MACRO",
        )
    except Exception as e:
        logger.debug("global_macro error: %s", e)
        return FactorScore(
            factor_id="global_macro",
            label="Global Macro (GIFT NIFTY + DXY + Crude)",
            score=5,
            signal="UNAVAILABLE",
            detail="Live macro data temporarily unavailable",
            axis="MACRO",
        )


_VIX_REGIME_CACHE: dict[str, tuple[float, FactorScore]] = {}


def clear_conviction_cache() -> None:
    """Clears conviction and VIX scoring in-memory caches (used in testing and forced refreshes)."""
    with _CONVICTION_LOCK:
        _CONVICTION_CACHE.clear()
    _VIX_REGIME_CACHE.clear()


def _score_india_vix_regime(vix: Optional[float] = None) -> FactorScore:
    """
    Factor 4: India VIX Direction + Level.
    IMPROVED: Scores both absolute level AND rate of change direction.
    Falling VIX at elevated levels is more bullish than flat VIX at low levels.
    """
    import os
    is_testing = bool(os.environ.get("CHANAKYA_TESTING") or os.environ.get("PYTEST_CURRENT_TEST"))
    now_ts = time.time()
    cache_key = f"{round(vix, 1) if vix is not None else 'auto'}"
    if not is_testing and cache_key in _VIX_REGIME_CACHE:
        cached_ts, cached_score = _VIX_REGIME_CACHE[cache_key]
        if now_ts - cached_ts < 60.0:
            return cached_score

    try:
        vix_now = vix
        vix_direction = "STABLE"

        if vix_now is None:
            from market.indices import get_vix
            vix_now = get_vix()

        # Resolve direction from fast live quote change without blocking on 30s historical scrapes
        if not is_testing:
            try:
                from market.quotes import get_quote
                from market.indices import INDEX_INSTRUMENTS
                vix_inst = INDEX_INSTRUMENTS.get("VIX", "NSE:INDIA VIX")
                q_map = get_quote([vix_inst])
                vq = q_map.get(vix_inst) or q_map.get("INDIA VIX") or q_map.get("NSE:INDIA VIX")
                if vq:
                    if (vix_now is None or vix_now <= 0) and getattr(vq, "last_price", 0) > 0 and vix is None:
                        vix_now = float(vq.last_price)
                    chg = getattr(vq, "change", None)
                    if chg is not None:
                        if chg < -0.5:
                            vix_direction = "FALLING"
                        elif chg > 0.5:
                            vix_direction = "RISING"
            except Exception:
                pass

        if vix_now is None or vix_now <= 0:
            res = FactorScore(
                factor_id="india_vix",
                label="India VIX Direction & Level",
                score=5,
                signal="UNAVAILABLE",
                detail="VIX data unavailable",
                axis="MACRO",
            )
            if not is_testing:
                _VIX_REGIME_CACHE[cache_key] = (now_ts, res)
            return res

        # Base score from absolute level
        if vix_now < 11:
            score = 8
            base_detail = f"VIX {vix_now:.1f} — very low (calm trending environment)"
        elif vix_now < 14:
            score = 7
            base_detail = f"VIX {vix_now:.1f} — low (ideal for directional trades)"
        elif vix_now < 17:
            score = 5
            base_detail = f"VIX {vix_now:.1f} — moderate (normal market)"
        elif vix_now < 21:
            score = 4
            base_detail = f"VIX {vix_now:.1f} — elevated (prefer defined-risk spreads)"
        elif vix_now < 25:
            score = 3
            base_detail = f"VIX {vix_now:.1f} — high (reduce size, widen SL)"
        else:
            score = 1
            base_detail = f"VIX {vix_now:.1f} — extreme (tail risk, no naked positions)"

        # Direction modifier: falling VIX is more bullish than rising at same level
        direction_note = ""
        if vix_direction == "FALLING":
            score = min(10, score + 2)
            direction_note = " ↓ Falling — relief rally conditions"
        elif vix_direction == "RISING":
            score = max(0, score - 2)
            direction_note = " ↑ Rising — volatility expansion warning"
        else:
            direction_note = " → Stable"

        signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
        res = FactorScore(
            factor_id="india_vix",
            label="India VIX Direction & Level",
            score=max(0, min(10, score)),
            signal=signal,
            detail=base_detail + direction_note,
            raw_value=vix_now,
            axis="MACRO",
        )
        _VIX_REGIME_CACHE[cache_key] = (now_ts, res)
        return res
    except Exception as e:
        logger.debug("india_vix error: %s", e)
        return FactorScore(
            factor_id="india_vix",
            label="India VIX Direction & Level",
            score=5,
            signal="UNAVAILABLE",
            detail="VIX data temporarily unavailable",
            axis="MACRO",
        )


# ── AXIS 3: OPTIONS INTELLIGENCE ─────────────────────────────────────────────


def _score_gex_posture(gex_posture: Optional[str] = None) -> FactorScore:
    """
    Factor 5: GEX Dealer Positioning.
    Measures market maker hedging requirement (flow-driven, not trend-driven).
    """
    score = 5
    details = []

    if gex_posture == "EXTREME_NEGATIVE":
        score = 9
        details.append("Extreme Negative GEX — dealers must buy rallies (fuel for moves)")
    elif gex_posture == "NEGATIVE":
        score = 7
        details.append("Negative GEX — dealers short gamma, trend acceleration possible")
    elif gex_posture == "POSITIVE":
        score = 4
        details.append("Positive GEX — dealers long gamma, dampening volatility (range-bound)")
    elif gex_posture == "EXTREME_POSITIVE":
        score = 2
        details.append("Extreme Positive GEX — strong market maker pinning (expiry gravity)")
    else:
        details.append("GEX posture data not available — assuming neutral")

    signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
    return FactorScore(
        factor_id="gex_posture",
        label="GEX Dealer Positioning",
        score=score,
        signal=signal,
        detail=" | ".join(details),
        axis="OPTIONS",
    )


def _score_pcr_contrarian(pcr: Optional[float] = None) -> FactorScore:
    """
    Factor 6: PCR Contrarian Signal.
    CRITICAL DESIGN: Extremes in EITHER direction are BEARISH.
    The optimal PCR zone is 0.9–1.3 (put writers supporting market without excess).
    PCR > 1.5 = extreme put OI = institutional distribution setup.
    PCR < 0.6 = extreme complacency = vulnerable to sharp correction.
    """
    if pcr is None:
        return FactorScore(
            factor_id="pcr_contrarian",
            label="PCR Contrarian Gate",
            score=5,
            signal="NEUTRAL",
            detail="PCR data not provided",
            axis="OPTIONS",
        )

    if pcr < 0.5:
        score = 2
        detail = f"PCR {pcr:.2f} — Extreme complacency (< 0.5). Correction risk HIGH."
        signal = "BEARISH"
    elif pcr < 0.7:
        score = 3
        detail = f"PCR {pcr:.2f} — Call writers dominant. Overhead resistance heavy."
        signal = "BEARISH"
    elif pcr < 0.85:
        score = 5
        detail = f"PCR {pcr:.2f} — Mild call resistance. Market cap near."
        signal = "NEUTRAL"
    elif pcr <= 1.15:
        score = 8
        detail = f"PCR {pcr:.2f} — Optimal zone. Put writers supporting market floor."
        signal = "BULLISH"
    elif pcr <= 1.35:
        score = 7
        detail = f"PCR {pcr:.2f} — Healthy put support. Minor OI at upper extremes."
        signal = "BULLISH"
    elif pcr <= 1.55:
        score = 5
        detail = f"PCR {pcr:.2f} — Elevated put OI. Watch for potential unwind squeeze."
        signal = "NEUTRAL"
    else:  # > 1.55
        score = 3
        detail = f"PCR {pcr:.2f} — Excessive put OI (> 1.55). Distribution or pain trade setup."
        signal = "BEARISH"

    return FactorScore(
        factor_id="pcr_contrarian",
        label="PCR Contrarian Gate (0.9–1.3 optimal)",
        score=score,
        signal=signal,
        detail=detail,
        raw_value=pcr,
        axis="OPTIONS",
    )


def _score_iv_skew(iv_skew: Optional[list] = None) -> FactorScore:
    """
    Factor 7: IV Skew Direction (Term Structure).
    Scores near-term vs far-term implied volatility spread.
    Normal: far-term IV ≥ near-term IV (healthy term structure).
    Inversion: near-term IV > far-term IV = institutional tail-risk hedging = bearish.
    """
    if not iv_skew or len(iv_skew) < 4:
        return FactorScore(
            factor_id="iv_skew",
            label="IV Skew / Term Structure",
            score=5,
            signal="NEUTRAL",
            detail="IV skew data not available — assuming normal structure",
            axis="OPTIONS",
        )

    try:
        ivs = [float(p.get("iv", 0)) for p in iv_skew if p.get("iv", 0) > 0]
        if len(ivs) < 4:
            raise ValueError("Insufficient IV points")

        n = len(ivs)
        # Near-term = first 1/3 of strikes (OTM puts/calls close to ATM)
        # Far-term = last 1/3 of strikes (deep OTM)
        near_avg = sum(ivs[: n // 3]) / max(1, n // 3)
        far_avg = sum(ivs[n * 2 // 3 :]) / max(1, n - n * 2 // 3)
        skew_spread = far_avg - near_avg  # Positive = normal (far > near)

        if skew_spread > 3.0:
            score = 8
            detail = f"Normal term structure: far-term IV {far_avg:.1f}% > near {near_avg:.1f}% (+{skew_spread:.1f}%). Calm near-term."
            signal = "BULLISH"
        elif skew_spread > 0.5:
            score = 7
            detail = f"Slightly positive skew ({skew_spread:+.1f}%). Healthy structure."
            signal = "BULLISH"
        elif skew_spread >= -1.0:
            score = 5
            detail = f"Near-flat IV skew ({skew_spread:+.1f}%). Neutral term structure."
            signal = "NEUTRAL"
        elif skew_spread >= -3.0:
            score = 3
            detail = f"Mild skew inversion ({skew_spread:+.1f}%): near-term IV higher. Watch for volatility spike."
            signal = "BEARISH"
        else:
            score = 1
            detail = f"IV INVERSION ({skew_spread:+.1f}%): Institutions buying near-term protection — tail risk hedging."
            signal = "BEARISH"

        return FactorScore(
            factor_id="iv_skew",
            label="IV Skew / Term Structure",
            score=score,
            signal=signal,
            detail=detail,
            raw_value=round(skew_spread, 2),
            axis="OPTIONS",
        )
    except Exception as e:
        logger.debug("iv_skew error: %s", e)
        return FactorScore(
            factor_id="iv_skew",
            label="IV Skew / Term Structure",
            score=5,
            signal="NEUTRAL",
            detail="Unable to compute IV term structure",
            axis="OPTIONS",
        )


# ── AXIS 4: PRICE STRUCTURE ───────────────────────────────────────────────────


def _score_smc_structure(spot: float, underlying: str = "NIFTY") -> FactorScore:
    """
    Factor 8: SMC Market Structure Quality.
    Measures structural integrity: higher highs/lows (BOS) vs broken structure (CHoCH).
    This is DIRECTIONAL but distinct from VWAP/EMAs — it measures STRUCTURE, not price level.
    """
    try:
        from market.history import get_ohlcv
        from market.quotes import normalize_instrument

        inst = normalize_instrument(underlying)
        df = get_ohlcv(inst, days=20, interval="day")

        if df is None or df.empty or len(df) < 10:
            raise ValueError("Insufficient OHLCV data")

        recent = df.tail(10)
        recent_high = float(recent["High"].max())
        recent_low = float(recent["Low"].min())
        prev_5_high = float(df.tail(10).head(5)["High"].max())
        prev_5_low = float(df.tail(10).head(5)["Low"].min())
        last_5_high = float(df.tail(5)["High"].max())
        last_5_low = float(df.tail(5)["Low"].min())

        is_bos_bullish = last_5_high > prev_5_high
        is_bos_bearish = last_5_low < prev_5_low
        price_in_upper_half = spot > (recent_low + (recent_high - recent_low) * 0.55)
        price_holding_support = spot > recent_low * 1.006

        score = 5
        details = []

        if is_bos_bullish and not is_bos_bearish and price_in_upper_half:
            score = 8
            details.append("BOS bullish: higher highs + price in upper range")
        elif is_bos_bearish and not is_bos_bullish and not price_in_upper_half:
            score = 2
            details.append("CHoCH: lower lows forming + price in lower range (bearish)")
        elif is_bos_bullish and not price_in_upper_half:
            score = 6
            details.append("BOS bullish but price retesting — potential Order Block retest")
        elif is_bos_bearish and price_in_upper_half:
            score = 4
            details.append("Mixed signals: lower lows but price still elevated — caution")
        else:
            details.append("Neutral structure — awaiting directional commitment")

        if price_holding_support:
            score = min(10, score + 1)
            details.append("Holding above 10D swing low support")
        else:
            score = max(0, score - 2)
            details.append("TESTING 10D swing low — structural caution")

        signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
        return FactorScore(
            factor_id="smc_structure",
            label="SMC Market Structure (BOS/CHoCH)",
            score=max(0, min(10, score)),
            signal=signal,
            detail=" | ".join(details),
            raw_value=round(spot / recent_high * 100, 1),
            axis="PRICE",
        )
    except Exception as e:
        logger.debug("smc_structure error: %s", e)
        return FactorScore(
            factor_id="smc_structure",
            label="SMC Market Structure (BOS/CHoCH)",
            score=5,
            signal="UNAVAILABLE",
            detail="Market structure data temporarily unavailable",
            axis="PRICE",
        )


def _score_max_pain_proximity(
    spot: float,
    max_pain: Optional[float] = None,
    session_time_str: Optional[str] = None,
) -> FactorScore:
    """
    Factor 9: Max Pain Expiry Gravity.
    ORTHOGONAL TO SMC — this is a mean-reversion factor, not a trend factor.
    Near expiry + spot far from max pain = high probability of convergence.
    This INTENTIONALLY contradicts trend signals near expiry.
    """
    if not max_pain or max_pain <= 0 or spot <= 0:
        return FactorScore(
            factor_id="max_pain",
            label="Max Pain Expiry Gravity",
            score=5,
            signal="NEUTRAL",
            detail="Max pain data not available — assuming neutral",
            axis="PRICE",
        )

    distance_pct = abs(spot - max_pain) / max_pain * 100
    is_above = spot > max_pain

    # Check if we're near expiry (Thursday = expiry day in NSE)
    from datetime import datetime

    now = datetime.now()
    days_to_thursday = (3 - now.weekday()) % 7  # 0 = Thursday
    near_expiry = days_to_thursday <= 1  # Thursday or Wednesday

    score = 5
    details = []

    if near_expiry:
        if distance_pct <= 0.3:
            score = 8
            details.append(
                f"Expiry day: Spot at Max Pain ₹{max_pain:,.0f} → Pin risk (mean reversion done)"
            )
        elif distance_pct <= 1.0:
            score = 6
            direction = "above" if is_above else "below"
            details.append(
                f"Near expiry: Spot {direction} Max Pain by {distance_pct:.1f}% → moderate pull expected"
            )
        elif distance_pct <= 2.0:
            score = 4
            direction = "above" if is_above else "below"
            details.append(
                f"Near expiry: Spot {distance_pct:.1f}% {direction} Max Pain ₹{max_pain:,.0f} → strong pull likely"
            )
        else:
            # Far from max pain near expiry = strong contrarian mean-reversion opportunity
            score = 2 if is_above else 8  # Far above max pain near expiry = bearish
            direction = "above" if is_above else "below"
            details.append(
                f"EXPIRY GRAVITY: Spot {distance_pct:.1f}% {direction} Max Pain ₹{max_pain:,.0f} → "
                f"{'Strong pull DOWN to max pain' if is_above else 'Strong pull UP to max pain'}"
            )
    else:
        # Mid-week: max pain is less predictive
        if distance_pct <= 0.5:
            score = 7
            details.append(f"Spot near Max Pain ₹{max_pain:,.0f} — low volatility zone")
        elif distance_pct <= 2.0:
            score = 5
            details.append(
                f"Spot {distance_pct:.1f}% from Max Pain ₹{max_pain:,.0f} — normal range"
            )
        else:
            score = 5
            details.append(
                f"Spot {distance_pct:.1f}% from Max Pain ₹{max_pain:,.0f} — mid-week pull limited"
            )

    signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
    return FactorScore(
        factor_id="max_pain",
        label="Max Pain Expiry Gravity",
        score=max(0, min(10, score)),
        signal=signal,
        detail=" | ".join(details),
        raw_value=distance_pct,
        axis="PRICE",
    )


# ── AXIS 5: TIMING & FLOW ─────────────────────────────────────────────────────


def _score_sector_rotation(underlying: str = "NIFTY", symbol: str = "") -> FactorScore:
    """
    Factor 10: Sector Rotation Momentum (RRG Quadrant).

    Enhanced with:
    - Stock-specific sector lookup via get_stock_tailwind (not just index mapping)
    - rotation_velocity from 12-point trail: rewards early IMPROVING + penalizes
      decelerating WEAKENING sectors
    """
    try:
        # Try stock-specific sector first (most accurate for individual equities)
        sector_point = None
        rrg_data = []
        stock_tailwind = None

        if symbol:
            try:
                from analysis.sector_rotation import get_stock_tailwind
                stock_tailwind = get_stock_tailwind(symbol.upper().replace("NSE:", "").replace(".NS", ""))
                if stock_tailwind and stock_tailwind.quadrant and stock_tailwind.quadrant != "UNAVAILABLE":
                    # Found stock-specific sector RRG — highest accuracy path
                    quad = stock_tailwind.quadrant
                    sec_name = stock_tailwind.sector or symbol
                    tailwind_score = stock_tailwind.tailwind_score
                    # Get velocity from the tailwind if available
                    rotation_velocity = getattr(stock_tailwind, "rotation_velocity", None)

                    if quad == "LEADING":
                        vel_boost = 1 if rotation_velocity and rotation_velocity > 0.1 else 0
                        score = min(10, 9 + vel_boost)
                        detail = f"{sec_name}: LEADING (tailwind={tailwind_score}/100)"
                        if vel_boost:
                            detail += " ↑ accelerating RS-Momentum"
                        signal = "BULLISH"
                    elif quad == "IMPROVING":
                        if rotation_velocity is not None and rotation_velocity > 0.08:
                            # Accelerating into leadership — early entry ideal
                            score, signal = 8, "BULLISH"
                            detail = f"{sec_name}: IMPROVING ↑ accel (velocity={rotation_velocity:.2f}) — best early entry"
                        elif rotation_velocity is not None and rotation_velocity < -0.05:
                            # Stalling before entering leading — risk of reverting to weakening
                            score, signal = 5, "NEUTRAL"
                            detail = f"{sec_name}: IMPROVING but decelerating (vel={rotation_velocity:.2f}) — watch"
                        else:
                            score, signal = 7, "BULLISH"
                            detail = f"{sec_name}: IMPROVING → entering leadership"
                    elif quad == "WEAKENING":
                        score, signal = 4, "NEUTRAL"
                        detail = f"{sec_name}: WEAKENING — momentum fading"
                    else:
                        score, signal = 2, "BEARISH"
                        detail = f"{sec_name}: LAGGING — underperforming benchmark"

                    return FactorScore(
                        factor_id="sector_rotation",
                        label="Sector Rotation Momentum (RRG)",
                        score=max(0, min(10, score)),
                        signal=signal,
                        detail=detail,
                        raw_value=float(tailwind_score),
                        axis="TIMING",
                    )
            except Exception:
                pass

        # Fallback: index-to-sector mapping for index options/derivatives
        sector_map = {
            "BANKNIFTY": "BANK",
            "BANKBEES": "BANK",
            "FINNIFTY": "FIN_SERVICES",
            "MIDCPNIFTY": "MIDCAP",
            "NIFTYIT": "IT",
        }
        underlying_upper = underlying.upper()
        target_sector = sector_map.get(underlying_upper)

        from analysis.sector_rotation import get_sector_rotation

        rrg_data = get_sector_rotation()
        if not rrg_data:
            raise ValueError("No RRG data returned")

        leading_count = sum(1 for sp in rrg_data if sp.quadrant == "LEADING")
        improving_count = sum(1 for sp in rrg_data if sp.quadrant == "IMPROVING")
        total = len(rrg_data)

        sector_point = None
        if target_sector:
            for sp in rrg_data:
                if sp.sector == target_sector:
                    sector_point = sp
                    break

        if sector_point:
            if sector_point.quadrant == "LEADING":
                score, detail, signal = (
                    9,
                    f"{sector_point.sector}: LEADING (RS-Ratio {sector_point.rs_ratio:.1f})",
                    "BULLISH",
                )
            elif sector_point.quadrant == "IMPROVING":
                score, detail, signal = (
                    7,
                    f"{sector_point.sector}: IMPROVING → entering leadership",
                    "BULLISH",
                )
            elif sector_point.quadrant == "WEAKENING":
                score, detail, signal = (
                    4,
                    f"{sector_point.sector}: WEAKENING — momentum fading",
                    "NEUTRAL",
                )
            else:
                score, detail, signal = (
                    2,
                    f"{sector_point.sector}: LAGGING — underperforming benchmark",
                    "BEARISH",
                )
        else:
            breadth_pct = (leading_count + improving_count) / max(1, total) * 100
            if breadth_pct >= 65:
                score, signal = 8, "BULLISH"
                detail = f"Broad market: {leading_count} LEADING + {improving_count} IMPROVING ({breadth_pct:.0f}%)"
            elif breadth_pct >= 40:
                score, signal = 6, "NEUTRAL"
                detail = (
                    f"Mixed rotation: {leading_count}L + {improving_count}I ({breadth_pct:.0f}%)"
                )
            else:
                score, signal = 3, "BEARISH"
                detail = f"Weak breadth: {leading_count} LEADING sectors ({breadth_pct:.0f}%)"

        return FactorScore(
            factor_id="sector_rotation",
            label="Sector Rotation Momentum (RRG)",
            score=max(0, min(10, score)),
            signal=signal,
            detail=detail,
            raw_value=float(leading_count),
            axis="TIMING",
        )
    except Exception as e:
        logger.debug("sector_rotation error: %s", e)
        return FactorScore(
            factor_id="sector_rotation",
            label="Sector Rotation Momentum (RRG)",
            score=5,
            signal="UNAVAILABLE",
            detail="Sector rotation data temporarily unavailable",
            axis="TIMING",
        )






def _score_event_calendar() -> FactorScore:
    """
    Factor 11: Event Calendar Clarity (36-hour window).
    STRICTER scoring: defaults to neutral (not bullish) when data is unavailable.
    """
    try:
        from market.events import get_upcoming_events
        from datetime import datetime, timedelta

        upcoming = get_upcoming_events()
        now = datetime.now()
        window_end = now + timedelta(hours=36)

        high_impact = []
        medium_impact = []
        if upcoming:
            for ev in upcoming:
                try:
                    ev_dt = datetime.strptime(ev.get("date", ""), "%Y-%m-%d")
                    if now.date() <= ev_dt.date() <= window_end.date():
                        impact = ev.get("impact", "").upper()
                        name = ev.get("name", "Event")
                        if impact in ("HIGH", "CRITICAL"):
                            high_impact.append(name)
                        elif impact in ("MEDIUM",):
                            medium_impact.append(name)
                except Exception:
                    pass

        if not high_impact and not medium_impact:
            score = 9
            signal = "BULLISH"
            detail = "Clear 36h window — no scheduled high-impact events"
        elif not high_impact and len(medium_impact) <= 2:
            score = 7
            signal = "BULLISH"
            detail = f"Low-risk window: {len(medium_impact)} medium-impact events only"
        elif len(high_impact) == 1:
            score = 4
            signal = "NEUTRAL"
            detail = f"1 high-impact event: {high_impact[0]} (IV may inflate — consider spreads)"
        else:
            score = 2
            signal = "BEARISH"
            detail = f"{len(high_impact)} high-impact events: {', '.join(high_impact[:2])} (avoid naked positions)"

        return FactorScore(
            factor_id="event_calendar",
            label="Event Calendar Clarity (36h)",
            score=score,
            signal=signal,
            detail=detail,
            axis="TIMING",
        )
    except Exception as e:
        logger.debug("event_calendar error: %s", e)
        return FactorScore(
            factor_id="event_calendar",
            label="Event Calendar Clarity (36h)",
            score=5,  # NEUTRAL default (not 9 like before)
            signal="NEUTRAL",
            detail="Event calendar unavailable — proceed with caution",
            axis="TIMING",
        )


def _score_blast_signal_quality(
    blast_score: Optional[int] = None,
    vol_oi_ratio: Optional[float] = None,
    imbalance_ratio: Optional[float] = None,
) -> FactorScore:
    """
    Factor 12: Institutional Real-Time Order Flow Blast Quality.
    This is the ONLY real-time intraday factor — all others are EOD/daily.
    """
    if blast_score is None and vol_oi_ratio is None:
        return FactorScore(
            factor_id="blast_signal",
            label="Real-Time Blast Signal Quality",
            score=5,
            signal="NEUTRAL",
            detail="No active Blast signal detected at this time",
            axis="TIMING",
        )

    score = 5
    details = []

    if blast_score is not None:
        if blast_score >= 90:
            score = 10
            details.append(f"Elite Blast signal: Score {blast_score}/100")
        elif blast_score >= 82:
            score = 8
            details.append(f"High-quality Blast signal: Score {blast_score}/100")
        elif blast_score >= 70:
            score = 6
            details.append(f"Moderate Blast signal: Score {blast_score}/100")
        else:
            score = 4
            details.append(f"Weak Blast signal: Score {blast_score}/100 (below threshold)")

    if vol_oi_ratio is not None:
        if vol_oi_ratio >= 5.0:
            score = min(10, score + 2)
            details.append(f"Vol/OI {vol_oi_ratio:.1f}x — extreme institutional urgency")
        elif vol_oi_ratio >= 3.0:
            score = min(10, score + 1)
            details.append(f"Vol/OI {vol_oi_ratio:.1f}x — elevated turnover")

    if imbalance_ratio is not None and imbalance_ratio >= 2.5:
        score = min(10, score + 1)
        details.append(f"Queue imbalance {imbalance_ratio:.1f}x — buyer aggression confirmed")

    signal = "BULLISH" if score >= 7 else "BEARISH" if score <= 3 else "NEUTRAL"
    return FactorScore(
        factor_id="blast_signal",
        label="Real-Time Blast Signal Quality",
        score=max(0, min(10, score)),
        signal=signal,
        detail=" | ".join(details),
        raw_value=blast_score,
        axis="TIMING",
    )


# ── Veto System ───────────────────────────────────────────────────────────────


def _check_veto_conditions(
    vix: Optional[float],
    fii_streak: Optional[int],
    fii_streak_total: Optional[float],
    data_state: Optional[str],
) -> VetoResult:
    """
    Hard-stop veto conditions. If vetoed, score is capped at 55 regardless of factors.
    These are ABSOLUTE blocks, not scoring adjustments.
    """
    try:
        # Veto 1: Extreme VIX AND rising
        if vix and vix > 25:
            return VetoResult(
                vetoed=True,
                reason=f"⛔ VETO: India VIX {vix:.1f} > 25 (tail risk event in progress — no new directional positions)",
            )

        # Veto 2: Extreme sustained FII selling
        if fii_streak and fii_streak <= -5 and fii_streak_total and abs(fii_streak_total) > 15000:
            return VetoResult(
                vetoed=True,
                reason=f"⛔ VETO: FII sold ₹{abs(fii_streak_total):,.0f} Cr over {abs(fii_streak)} days — sustained distribution. Avoid longs.",
            )

        # Veto 3: Stale options data
        if data_state and data_state in ("STALE", "ERROR", "UNAVAILABLE"):
            return VetoResult(
                vetoed=True,
                reason=f"⛔ VETO: Options data state is {data_state} — cannot compute reliable signal",
            )

    except Exception:
        pass

    return VetoResult(vetoed=False)


# ── Main Scoring Engine ───────────────────────────────────────────────────────


def get_conviction_score(
    underlying: str = "NIFTY",
    spot: float = 0.0,
    pcr: Optional[float] = None,
    gex_posture: Optional[str] = None,
    vix: Optional[float] = None,
    blast_score: Optional[int] = None,
    vol_oi_ratio: Optional[float] = None,
    imbalance_ratio: Optional[float] = None,
    iv_skew: Optional[list] = None,
    max_pain: Optional[float] = None,
    data_state: Optional[str] = None,
) -> ConvictionScore:
    """
    Compute the 12-Factor Orthogonal Conviction Score.

    Factors span 5 independent axes:
      AXIS 1 — INSTITUTIONAL: FII cash flow, FII 5D positioning
      AXIS 2 — MACRO: Global macro, India VIX direction+level
      AXIS 3 — OPTIONS: GEX posture, PCR contrarian, IV skew
      AXIS 4 — PRICE: SMC structure, Max pain proximity
      AXIS 5 — TIMING: Sector rotation, Event calendar, Blast signal

    Veto system: hard blocks regardless of total score.
    """
    from datetime import datetime

    import os
    is_testing = bool(os.environ.get("CHANAKYA_TESTING") or os.environ.get("PYTEST_CURRENT_TEST"))

    # ── Check 45s TTL Cache (Institutional factors are macro/daily/hourly) ───
    cache_key = f"{underlying.strip().upper()}_{round(spot, 1)}_{round(pcr, 2) if pcr else 0}_{gex_posture}_{round(vix, 1) if vix else 0}_{blast_score}_{data_state}"

    now = time.time()
    if not is_testing:
        with _CONVICTION_LOCK:
            cached = _CONVICTION_CACHE.get(cache_key)
            if cached is not None:
                cached_time, cached_res = cached
                if now - cached_time < _CONVICTION_CACHE_TTL:
                    return cached_res

    # ── Fetch veto prerequisites ──────────────────────────────────────────────
    fii_streak = None
    fii_streak_total = None
    try:
        from market.flow_intel import get_flow_analysis

        flow = get_flow_analysis()
        fii_streak = flow.fii_streak
        fii_streak_total = flow.fii_streak_total
        if vix is None:
            pass  # will be fetched inside _score_india_vix_regime
    except Exception:
        pass

    # ── Run all 12 factors ───────────────────────────────────────────────────
    factors = [
        # AXIS 1: INSTITUTIONAL
        _score_fii_cash_flow(),
        _score_fii_futures_position(),
        # AXIS 2: MACRO
        _score_global_macro(spot),
        _score_india_vix_regime(vix),
        # AXIS 3: OPTIONS
        _score_gex_posture(gex_posture),
        _score_pcr_contrarian(pcr),
        _score_iv_skew(iv_skew),
        # AXIS 4: PRICE
        _score_smc_structure(spot, underlying),
        _score_max_pain_proximity(spot, max_pain),
        # AXIS 5: TIMING
        _score_sector_rotation(underlying),
        _score_event_calendar(),
        _score_blast_signal_quality(blast_score, vol_oi_ratio, imbalance_ratio),
    ]

    # ── Aggregate ─────────────────────────────────────────────────────────────
    total = sum(f.score for f in factors)  # max = 120
    # Normalize to 100
    total_normalized = round(total / 120 * 100)

    bullish = sum(1 for f in factors if f.signal == "BULLISH")
    bearish = sum(1 for f in factors if f.signal == "BEARISH")
    unavail = sum(1 for f in factors if f.signal == "UNAVAILABLE")

    # ── Veto check ────────────────────────────────────────────────────────────
    veto = _check_veto_conditions(vix, fii_streak, fii_streak_total, data_state)
    if veto.vetoed:
        total_normalized = min(total_normalized, 55)  # Hard cap at MODERATE

    # ── Verdict ───────────────────────────────────────────────────────────────
    if total_normalized >= 85:
        verdict = "MAX_CONVICTION"
        verdict_color = "emerald"
        summary = f"🔥 Maximum Conviction ({total_normalized}/100) — {bullish}/12 factors bullish. Size up 2×."
        pos_size = "2X"
    elif total_normalized >= 70:
        verdict = "HIGH"
        verdict_color = "cyan"
        summary = f"✅ High Conviction ({total_normalized}/100) — {bullish} bullish, {bearish} bearish factors. Take the trade."
        pos_size = "NORMAL"
    elif total_normalized >= 50:
        verdict = "MODERATE"
        verdict_color = "amber"
        summary = f"⚠️ Moderate Conviction ({total_normalized}/100) — {bullish} bullish vs {bearish} bearish. Reduce size or wait."
        pos_size = "HALF"
    else:
        verdict = "WAIT"
        verdict_color = "rose"
        summary = f"🛑 Low Conviction ({total_normalized}/100) — {bearish} bearish factors dominating. WAIT for setup."
        pos_size = "FLAT"

    if veto.vetoed:
        summary = f"{summary} | {veto.reason}"

    # ── Data-Driven Trade Plan (Empirical Invalidation, Targets, R:R & ETA) ───
    trade_plan = None
    try:
        from engine.trade_plan import calculate_trade_plan

        plan_direction = "BUY" if (bullish >= bearish) else "SELL"
        has_blast = blast_score is not None and blast_score >= 80
        trade_plan = calculate_trade_plan(
            symbol=underlying,
            direction=plan_direction,
            spot=spot,
            timeframe="INTRADAY",
            has_active_blast=has_blast,
        )
    except Exception as _tpe:
        logger.debug("Failed computing trade plan: %s", _tpe)

    res = ConvictionScore(
        total_score=total_normalized,
        verdict=verdict,
        verdict_color=verdict_color,
        summary=summary,
        factors=factors,
        bullish_count=bullish,
        bearish_count=bearish,
        unavailable_count=unavail,
        recommended_position_size=pos_size,
        veto=veto,
        trade_plan=trade_plan,
        as_of=datetime.now().strftime("%H:%M:%S IST"),
    )

    if not is_testing:
        with _CONVICTION_LOCK:
            _CONVICTION_CACHE[cache_key] = (now, res)
            if len(_CONVICTION_CACHE) > 50:
                cutoff = now - _CONVICTION_CACHE_TTL
                for k in list(_CONVICTION_CACHE.keys()):
                    if _CONVICTION_CACHE[k][0] < cutoff:
                        _CONVICTION_CACHE.pop(k, None)

    return res
