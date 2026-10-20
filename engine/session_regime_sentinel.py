"""
engine/session_regime_sentinel.py
─────────────────────────────────
Autonomous Intraday Regime Shift Sentinel.

Monitors daily Central Pivot Range (CPR) geometry and intraday Average Daily Range
(ADR) exhaustion to dynamically switch execution mandates between:
  1. TREND_EXPANSION_REGIME: Narrow CPR (<0.15% index / <0.35% equity) + low ADR exhaustion
     (<50%). Full clearance for ORB breakouts, momentum surges, and trend runners.
  2. CHOP_MEAN_REVERSION_REGIME: Wide CPR (>0.35% index / >0.65% equity) OR high ADR exhaustion
     (>=85% of 5-day ADR consumed post-11:30 IST). Breakout chasing at session extremes
     is mathematically vetoed due to >80% trap probability; mean-reversion fades to VWAP/CPR
     are actively favored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Optional

logger = logging.getLogger("engine.session_regime_sentinel")
from config.constants import IST_ZONE as IST


@dataclass
class CPRMetrics:
    pivot: float
    bottom_central: float
    top_central: float
    cpr_width_pts: float
    cpr_width_pct: float
    cpr_type: str  # "NARROW" | "AVERAGE" | "WIDE"


@dataclass
class SessionRegimeClassification:
    symbol: str
    regime: str  # "TREND_EXPANSION" | "CHOP_MEAN_REVERSION" | "NEUTRAL_BALANCED"
    cpr: CPRMetrics
    session_range_pts: float
    adr_5d_pts: float
    adr_exhaustion_pct: float
    veto_breakout_chase: bool
    favor_mean_reversion: bool
    rationale: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "regime": self.regime,
            "cpr": {
                "pivot": self.cpr.pivot,
                "bottom_central": self.cpr.bottom_central,
                "top_central": self.cpr.top_central,
                "cpr_width_pts": self.cpr.cpr_width_pts,
                "cpr_width_pct": self.cpr.cpr_width_pct,
                "cpr_type": self.cpr.cpr_type,
            },
            "session_range_pts": self.session_range_pts,
            "adr_5d_pts": self.adr_5d_pts,
            "adr_exhaustion_pct": self.adr_exhaustion_pct,
            "veto_breakout_chase": self.veto_breakout_chase,
            "favor_mean_reversion": self.favor_mean_reversion,
            "rationale": self.rationale,
            "evaluated_at": self.evaluated_at,
        }


def calculate_cpr(
    high: float,
    low: float,
    close: float,
    is_index: bool = False,
) -> CPRMetrics:
    """
    Computes Central Pivot Range (Pivot, Bottom Central, Top Central) and classifies width.
    """
    if high <= 0 or low <= 0 or close <= 0:
        return CPRMetrics(0.0, 0.0, 0.0, 0.0, 0.0, "AVERAGE")

    pivot = round((high + low + close) / 3.0, 2)
    bc = round((high + low) / 2.0, 2)
    tc = round((pivot - bc) + pivot, 2)

    width_pts = round(abs(tc - bc), 2)
    width_pct = round((width_pts / pivot) * 100.0, 3) if pivot > 0 else 0.0

    # Index vs Equity calibration
    narrow_threshold = 0.15 if is_index else 0.35
    wide_threshold = 0.35 if is_index else 0.65

    if width_pct <= narrow_threshold:
        cpr_type = "NARROW"
    elif width_pct >= wide_threshold:
        cpr_type = "WIDE"
    else:
        cpr_type = "AVERAGE"

    return CPRMetrics(
        pivot=pivot,
        bottom_central=bc,
        top_central=tc,
        cpr_width_pts=width_pts,
        cpr_width_pct=width_pct,
        cpr_type=cpr_type,
    )


def evaluate_symbol_session_regime(
    symbol: str,
    current_high: float,
    current_low: float,
    current_ltp: float,
    prev_high: float,
    prev_low: float,
    prev_close: float,
    adr_5d: Optional[float] = None,
    ref_time: Optional[datetime] = None,
) -> SessionRegimeClassification:
    """
    Evaluates intraday regime shift by comparing session range against ADR and CPR width.
    """
    clean_sym = symbol.upper()
    is_index = any(
        idx in clean_sym
        for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
    )

    cpr = calculate_cpr(prev_high, prev_low, prev_close, is_index=is_index)

    session_range = max(0.0, current_high - current_low)
    # Default ADR fallback: if not provided, approximate using prior day range
    adr_pts = float(adr_5d or max(1.0, prev_high - prev_low))
    adr_exhaustion_pct = round((session_range / adr_pts) * 100.0, 1) if adr_pts > 0 else 50.0

    now_dt = ref_time or datetime.now(IST)
    current_t = now_dt.time()
    is_post_1130 = current_t >= dtime(11, 30)

    # Decision Matrix:
    # 1. Exhaustion Veto: ADR >= 85% (or Wide CPR with ADR >= 75% post-11:30)
    if adr_exhaustion_pct >= 85.0 or (
        cpr.cpr_type == "WIDE" and adr_exhaustion_pct >= 75.0 and is_post_1130
    ):
        regime = "CHOP_MEAN_REVERSION"
        veto_chase = True
        favor_fade = True
        rationale = (
            f"ADR Exhaustion ({adr_exhaustion_pct:.1f}% consumed of {adr_pts:.1f} pts) "
            f"on {cpr.cpr_type} CPR ({cpr.cpr_width_pct:.2f}%). Breakout chasing at extremes vetoed; "
            f"mean-reversion fades favored."
        )
    # 2. Narrow CPR Trend Expansion: CPR is Narrow and ADR < 55%
    elif cpr.cpr_type == "NARROW" and adr_exhaustion_pct < 60.0:
        regime = "TREND_EXPANSION"
        veto_chase = False
        favor_fade = False
        rationale = (
            f"Narrow CPR Trend Expansion primed ({cpr.cpr_width_pct:.2f}% width) with "
            f"ample ADR runway remaining ({100.0 - adr_exhaustion_pct:.1f}% headroom). "
            f"Breakout acceleration permitted."
        )
    # 3. Wide CPR Chop Lull (Midday consolidation):
    elif cpr.cpr_type == "WIDE":
        regime = "CHOP_MEAN_REVERSION"
        veto_chase = is_post_1130
        favor_fade = True
        rationale = (
            f"Wide CPR Range-Bound Day ({cpr.cpr_width_pct:.2f}% width). "
            f"Sideways containment expected; avoid chasing edges."
        )
    else:
        regime = "NEUTRAL_BALANCED"
        veto_chase = False
        favor_fade = False
        rationale = (
            f"Balanced market session: Average CPR ({cpr.cpr_width_pct:.2f}%) and "
            f"moderate ADR consumption ({adr_exhaustion_pct:.1f}%)."
        )

    return SessionRegimeClassification(
        symbol=clean_sym,
        regime=regime,
        cpr=cpr,
        session_range_pts=session_range,
        adr_5d_pts=adr_pts,
        adr_exhaustion_pct=adr_exhaustion_pct,
        veto_breakout_chase=veto_chase,
        favor_mean_reversion=favor_fade,
        rationale=rationale,
    )


def check_alert_session_regime(
    alert: Any,
    ref_time: Optional[datetime] = None,
) -> Optional[SessionRegimeClassification]:
    """
    Extracts session parameters from alert metrics and evaluates regime shift.
    """
    if alert is None:
        return None

    metrics = getattr(alert, "metrics", {}) or {}
    if not isinstance(metrics, dict):
        metrics = alert.get("metrics", {}) if isinstance(alert, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}

    sym = str(
        getattr(alert, "symbol", "") or (alert.get("symbol", "") if isinstance(alert, dict) else "")
    ).upper()

    ltp = float(
        getattr(alert, "underlying_ltp", 0.0)
        or metrics.get("underlying_ltp")
        or metrics.get("spot")
        or getattr(alert, "ltp", 0.0)
        or (alert.get("ltp", 0.0) if isinstance(alert, dict) else 0.0)
        or 0.0
    )

    high = float(metrics.get("high") or metrics.get("day_high") or (ltp * 1.005))
    low = float(metrics.get("low") or metrics.get("day_low") or (ltp * 0.995))
    prev_h = float(metrics.get("prev_high") or metrics.get("pdh") or (ltp * 1.01))
    prev_l = float(metrics.get("prev_low") or metrics.get("pdl") or (ltp * 0.99))
    prev_c = float(metrics.get("prev_close") or metrics.get("pdc") or ltp)
    adr = float(metrics.get("adr") or metrics.get("adr_5d") or abs(prev_h - prev_l))

    return evaluate_symbol_session_regime(
        symbol=sym,
        current_high=high,
        current_low=low,
        current_ltp=ltp,
        prev_high=prev_h,
        prev_low=prev_l,
        prev_close=prev_c,
        adr_5d=adr,
        ref_time=ref_time,
    )
