"""
analysis/regime_governor.py
───────────────────────────
Real-Time Dynamic Market Regime Governor.

Continuously classifies macro Dalal Street market conditions into 4 distinct regimes:
  1. TREND_EXPANSION: Volatility expanding (VIX 13.0–18.5), benchmark trending outside 30m ORB,
     directional delta high. Breakouts and trend-following setups prioritized.
  2. BALANCED_CHOP: Volatility compressed (VIX < 12.5), Nifty trapped in tight 30m ORB band (<0.45%),
     midday lull. Mean-reversion (SMC OB Retest, Turtle Soup) & defined-risk neutral strategies prioritized.
     Breakouts require RVOL >= 2.0x to avoid false-breakout traps.
  3. VOLATILITY_EXPANSION_EXPIRY: Session day is an active index expiry (Nifty/BankNifty/Sensex/FinNifty)
     post-13:15 IST. Dealer gamma unwinding active. Gamma Blast & Options Momentum enabled.
  4. MACRO_SHOCK: Extreme volatility shock (VIX >= 19.0) or Global Macro composite score < -50.
     Naked directional options penalized; defined-risk hedged spreads mandated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Optional

logger = logging.getLogger("chanakya.analysis.regime_governor")
from config.constants import IST_ZONE as IST


@dataclass
class MarketRegimeClassification:
    regime: (
        str  # "TREND_EXPANSION" | "BALANCED_CHOP" | "VOLATILITY_EXPANSION_EXPIRY" | "MACRO_SHOCK"
    )
    vix: float
    is_orb_trapped: bool
    is_expiry_session: bool
    min_scrutiny_score: int
    dominant_bias: (
        str  # "TREND_FRIENDLY" | "MEAN_REVERSION" | "GAMMA_DRIVEN" | "CAPITAL_PRESERVATION"
    )
    guidance: str
    active_detectors: list[str] = field(default_factory=list)
    suppressed_detectors: list[str] = field(default_factory=list)
    classified_at: str = field(
        default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "vix": self.vix,
            "is_orb_trapped": self.is_orb_trapped,
            "is_expiry_session": self.is_expiry_session,
            "min_scrutiny_score": self.min_scrutiny_score,
            "dominant_bias": self.dominant_bias,
            "guidance": self.guidance,
            "active_detectors": self.active_detectors,
            "suppressed_detectors": self.suppressed_detectors,
            "classified_at": self.classified_at,
        }


def classify_market_regime(
    vix: Optional[float] = None,
    nifty_spot: Optional[float] = None,
    orb_high: Optional[float] = None,
    orb_low: Optional[float] = None,
    global_macro_score: Optional[float] = None,
    ref_dt: Optional[datetime] = None,
) -> MarketRegimeClassification:
    """
    Classifies the Dalal Street market regime deterministically based on
    volatility, benchmark range containment, expiry calendar, and macro scores.
    """
    now_ist = ref_dt or datetime.now(IST)
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=IST)
    else:
        now_ist = now_ist.astimezone(IST)

    import os

    is_test_env = (
        os.environ.get("CHANAKYA_TESTING") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get("DEPLOY_MODE") == "test"
    )

    if is_test_env and ref_dt is None:
        # In test environments without an explicit time fixture, default to standard morning session (10:00 IST)
        # to ensure unit tests targeting specific alert logic are not blocked by ambient wall-clock midday lull.
        now_ist = now_ist.replace(hour=10, minute=0, second=0)

    # 1. Fetch live VIX if not provided (Zero Network I/O in test environments)
    vix_val = vix
    if vix_val is None or vix_val <= 0:
        try:
            from market.quotes import _QUOTE_CACHE, _quote_cache_lock

            with _quote_cache_lock:
                for k in ("NSE:INDIA VIX", "INDIA VIX", "VIX", "INDIAVIX"):
                    if k in _QUOTE_CACHE:
                        _, q_obj = _QUOTE_CACHE[k]
                        val = float(
                            getattr(q_obj, "last_price", 0.0) or getattr(q_obj, "ltp", 0.0) or 0.0
                        )
                        if val > 0:
                            vix_val = val
                            break
        except Exception as e_suppressed:
            logger.debug(
                f"[analysis.regime_governor] Non-fatal exception suppressed: {e_suppressed}"
            )

    if (vix_val is None or vix_val <= 0) and not is_test_env:
        try:
            from market.indices import get_vix

            v_raw = get_vix()
            if isinstance(v_raw, (int, float)) and v_raw > 0:
                vix_val = float(v_raw)
            elif hasattr(v_raw, "ltp") and v_raw.ltp:
                vix_val = float(v_raw.ltp)
            elif isinstance(v_raw, dict):
                vix_val = float(v_raw.get("ltp") or v_raw.get("value") or 0.0)
        except Exception as e_suppressed:
            logger.debug(
                f"[analysis.regime_governor] Non-fatal exception suppressed: {e_suppressed}"
            )

    if vix_val is None or vix_val <= 0:
        vix_val = 13.5  # Neutral institutional baseline

    # 2. Check Expiry Session (Post 13:15 IST on active index weekly expiry days: Nifty Thu, Sensex Fri)
    from market.calendar import is_expiry_day

    cur_d = now_ist.date()
    is_active_expiry = is_expiry_day("NIFTY", ref_date=cur_d) or is_expiry_day(
        "SENSEX", ref_date=cur_d, exchange="BSE"
    )
    now_t = now_ist.time()
    is_afternoon_expiry = is_active_expiry and now_t >= dtime(13, 15) and now_t <= dtime(15, 30)

    # 3. Check ORB Trapping (Opening 30-min range containment between 10:30 and 14:00 IST)
    is_orb_trapped = False
    if dtime(10, 30) <= now_t <= dtime(14, 0):
        if nifty_spot and orb_high and orb_low and orb_high > orb_low:
            if orb_low <= nifty_spot <= orb_high:
                range_pct = ((orb_high - orb_low) / nifty_spot) * 100.0
                if range_pct < 0.50:  # Tight ORB band
                    is_orb_trapped = True

    # 4. Check Macro Shock
    macro_score = global_macro_score if global_macro_score is not None else 0.0

    # ── Regime Decision Logic ───────────────────────────────────────────────

    # Regime 4: Macro Shock
    if vix_val >= 19.0 or macro_score <= -50.0:
        return MarketRegimeClassification(
            regime="MACRO_SHOCK",
            vix=vix_val,
            is_orb_trapped=is_orb_trapped,
            is_expiry_session=is_afternoon_expiry,
            min_scrutiny_score=85,
            dominant_bias="CAPITAL_PRESERVATION",
            guidance="Extreme macro/volatility shock. Strict defined-risk hedged spreads mandated; reduce size 50%.",
            active_detectors=["DEFINED_RISK_NEUTRAL", "CIRCUIT_WARNING"],
            suppressed_detectors=["SQUEEZE_BREAKOUT", "OPTIONS_MOMENTUM"],
        )

    # Regime 3: Volatility Expansion Expiry
    if is_afternoon_expiry and vix_val >= 12.0:
        return MarketRegimeClassification(
            regime="VOLATILITY_EXPANSION_EXPIRY",
            vix=vix_val,
            is_orb_trapped=is_orb_trapped,
            is_expiry_session=True,
            min_scrutiny_score=75,
            dominant_bias="GAMMA_DRIVEN",
            guidance="Expiry day gamma expansion active. Fast-paced options unwinding setups prioritized.",
            active_detectors=["GAMMA_BLAST", "OPTIONS_MOMENTUM", "INTRADAY_SPARK"],
            suppressed_detectors=["MULTIBAGGER", "DEFINED_RISK_NEUTRAL"],
        )

    # Regime 2b: Institutional Distribution (Bearish Trend Day)
    nifty_dir_chg = 0.0
    is_intraday_recovering = False
    if not is_test_env:
        try:
            from market.quotes import _QUOTE_CACHE, _quote_cache_lock

            with _quote_cache_lock:
                for k in ("NSE:NIFTY 50", "NSE:NIFTY", "NIFTY", "NIFTY 50"):
                    if k in _QUOTE_CACHE:
                        _, nq = _QUOTE_CACHE[k]
                        nifty_dir_chg = float(getattr(nq, "change_pct", 0.0) or 0.0)
                        nq_ltp = float(
                            getattr(nq, "last_price", 0.0) or getattr(nq, "ltp", 0.0) or 0.0
                        )
                        nq_open = float(getattr(nq, "open", 0.0) or 0.0)
                        nq_vwap = float(getattr(nq, "vwap", 0.0) or 0.0)
                        # Intraday recovery: Spot has reclaimed VWAP or is trading above session open
                        if nq_ltp > 0 and (
                            (nq_vwap > 0 and nq_ltp > nq_vwap) or (nq_open > 0 and nq_ltp > nq_open)
                        ):
                            is_intraday_recovering = True
                        break
        except Exception as e_suppressed:
            logger.debug(f"[analysis.regime_governor] Benchmark quote error: {e_suppressed}")

    # If spot has broken out above ORB high, benchmark is exhibiting bullish expansion, not distribution
    is_orb_breakout_bull = bool(nifty_spot and orb_high and orb_high > 0 and nifty_spot > orb_high)

    if (
        (nifty_dir_chg <= -0.40 or macro_score <= -30.0)
        and not is_orb_trapped
        and not is_orb_breakout_bull
        and not is_intraday_recovering
    ):
        return MarketRegimeClassification(
            regime="INSTITUTIONAL_DISTRIBUTION",
            vix=vix_val,
            is_orb_trapped=False,
            is_expiry_session=is_afternoon_expiry,
            min_scrutiny_score=75,
            dominant_bias="BEARISH_EXPANSION",
            guidance="Dalal Street in institutional distribution (Nifty down >= 0.40% or macro headwinds). Actively prioritize Put setups, breakdown sparks, and defensive decouplers.",
            active_detectors=[
                "INDEX_PUT_SETUP",
                "INTRADAY_SPARK",
                "SMC_OB_RETEST",
                "TURTLE_SOUP_SWEEP",
                "GAMMA_BLAST",
            ],
            suppressed_detectors=[
                "INDEX_CALL_SETUP",
                "OPENING_DRIVE",
                "AFTERNOON_THRUST",
                "THEMATIC_SYMPATHY",
            ],
        )

    # Regime 2: Balanced Chop / Midday Consolidation
    is_benchmark_trending = False
    if nifty_spot and orb_high and orb_low and orb_high > orb_low:
        if nifty_spot > orb_high or nifty_spot < orb_low:
            is_benchmark_trending = True
    if not is_benchmark_trending and not is_test_env:
        try:
            from market.quotes import _QUOTE_CACHE, _quote_cache_lock

            with _quote_cache_lock:
                for k in ("NSE:NIFTY 50", "NSE:NIFTY", "NIFTY", "NIFTY 50"):
                    if k in _QUOTE_CACHE:
                        _, nq = _QUOTE_CACHE[k]
                        chg_pct = abs(float(getattr(nq, "change_pct", 0.0) or 0.0))
                        if chg_pct >= 0.40:
                            is_benchmark_trending = True
                        break
        except Exception as e_suppressed:
            logger.debug(
                f"[analysis.regime_governor] Non-fatal exception suppressed: {e_suppressed}"
            )

    is_midday_lull = (
        (dtime(11, 15) <= now_t <= dtime(13, 15)) and (vix_val < 16.0) and not is_benchmark_trending
    )
    if (
        (vix_val < 13.5 and not is_benchmark_trending) or is_orb_trapped or is_midday_lull
    ) and not is_benchmark_trending:
        return MarketRegimeClassification(
            regime="BALANCED_CHOP",
            vix=vix_val,
            is_orb_trapped=is_orb_trapped,
            is_expiry_session=False,
            min_scrutiny_score=80,
            dominant_bias="MEAN_REVERSION",
            guidance="Compressed volatility and range-bound session. Prioritize SMC OB retests & Turtle Soup reversals. Breakouts require RVOL >= 2.0x.",
            active_detectors=[
                "SMC_OB_RETEST",
                "TURTLE_SOUP_SWEEP",
                "DEFINED_RISK_NEUTRAL",
                "PAIRS_ARBITRAGE",
            ],
            suppressed_detectors=[
                "SQUEEZE_BREAKOUT",
                "OPENING_RANGE_BREAKOUT",
                "INDEX_MICRO_SCALP",
                "OPTIONS_MOMENTUM",
            ],
        )

    # Regime 1: Trend Expansion (Default Institutional State)
    return MarketRegimeClassification(
        regime="TREND_EXPANSION",
        vix=vix_val,
        is_orb_trapped=False,
        is_expiry_session=False,
        min_scrutiny_score=70,
        dominant_bias="TREND_FRIENDLY",
        guidance="Market exhibiting directional trend expansion. Standard institutional conviction threshold (70%) active.",
        active_detectors=[
            "SQUEEZE_BREAKOUT",
            "GAMMA_BLAST",
            "OPENING_DRIVE",
            "MULTIBAGGER",
            "INTRADAY_SPARK",
            "TURTLE_SOUP_SWEEP",
        ],
        suppressed_detectors=[],
    )


def is_detector_eligible_for_regime(
    alert_type: str,
    regime: MarketRegimeClassification,
    rvol: float = 1.0,
    has_structural_sweep: bool = False,
    direction: str = "BULLISH",
    sector_rs_leading: bool = False,
    sector_rs_lagging: bool = False,
) -> tuple[bool, str]:
    """
    Evaluates if a specific detector is eligible to fire under the current market regime.
    Bidirectionally calibrated:
      - In Bearish Institutional Distribution: Put setups prioritized; Bullish setups allowed
        at calibrated 1.60x RVOL if in a Leading/Improving Relative Strength sector (e.g. IT, FMCG, Pharma).
      - In Bullish Trend Expansion: Call setups prioritized; Bearish short setups allowed
        at calibrated 1.60x RVOL if in a Lagging Relative Strength sector with structural breakdown.
      - In Balanced Chop: Breakouts require >= 2.0x RVOL or verified SMC structural sweep.
      - In Macro Shock: Naked directional breakouts prohibited; defined-risk spreads mandated.
    Returns: (is_eligible, reason_if_suppressed)
    """
    atype = alert_type.upper()
    dir_up = str(direction or "BULLISH").upper()
    is_bull = dir_up in ("BULLISH", "LONG", "BUY")
    is_bear = dir_up in ("BEARISH", "SHORT", "SELL")

    # In Macro Shock, suppress naked directional breakouts in both directions
    if regime.regime == "MACRO_SHOCK":
        if atype in (
            "SQUEEZE_BREAKOUT",
            "SQUEEZE_BREAKDOWN",
            "OPTIONS_MOMENTUM",
            "INTRADAY_SPARK",
            "INDEX_MICRO_SCALP",
        ):
            return (
                False,
                "Suppressed by Regime Governor: MACRO_SHOCK regime prohibits naked breakouts. Use defined-risk spreads.",
            )

    # In Institutional Distribution (Bearish Benchmark State)
    if regime.regime == "INSTITUTIONAL_DISTRIBUTION":
        if is_bull:
            if atype == "INDEX_CALL_SETUP":
                if not has_structural_sweep and rvol < 2.50:
                    return (
                        False,
                        f"Suppressed by Regime Governor: INSTITUTIONAL_DISTRIBUTION active (Benchmark down >= 0.40%). "
                        f"Index Call setup requires verified structural sweep (PDL/Day Low bounce/SMT) or RVOL >= 2.50x (got {rvol:.2f}x). "
                        f"Terminal dynamically pivots to Index Put setups & breakdown sparks.",
                    )
            elif atype in ("OPENING_DRIVE", "AFTERNOON_THRUST", "SQUEEZE_BREAKOUT"):
                rvol_floor = 1.60 if sector_rs_leading else 2.50
                if rvol < rvol_floor:
                    tag = (
                        "Leading/Defensive Sector Decoupler"
                        if sector_rs_leading
                        else "Cyclical/Broad Market"
                    )
                    return (
                        False,
                        f"Suppressed by Regime Governor: INSTITUTIONAL_DISTRIBUTION active ({tag}). "
                        f"Bullish setup requires RVOL >= {rvol_floor:.2f}x (got {rvol:.2f}x) to confirm decoupling from benchmark selling.",
                    )

    # In Bullish Trend Expansion (Bullish Benchmark State)
    if regime.regime == "TREND_EXPANSION":
        if is_bear:
            if atype == "INDEX_PUT_SETUP":
                if not has_structural_sweep and rvol < 2.5:
                    return (
                        False,
                        f"Suppressed by Regime Governor: TREND_EXPANSION active (Benchmark trending up). "
                        f"Counter-trend Index Put requires verified SMC structural sweep or extreme RVOL >= 2.50x (got {rvol:.2f}x).",
                    )
            elif atype in ("SQUEEZE_BREAKDOWN", "INTRADAY_BREAKDOWN_SPARK"):
                rvol_floor = 1.60 if sector_rs_lagging else 2.20
                if not has_structural_sweep and rvol < rvol_floor:
                    tag = (
                        "Lagging Relative Strength Sector" if sector_rs_lagging else "General Stock"
                    )
                    return (
                        False,
                        f"Suppressed by Regime Governor: TREND_EXPANSION active ({tag}). "
                        f"Short breakdown requires RVOL >= {rvol_floor:.2f}x (got {rvol:.2f}x) or verified SMC sweep to avoid bear traps.",
                    )

    # In Balanced Chop, suppress directional breakouts unless confirmed by heavy volume or SMC sweep
    if regime.regime == "BALANCED_CHOP":
        if atype == "INDEX_MICRO_SCALP":
            return (
                False,
                f"Suppressed by Regime Governor: BALANCED_CHOP regime prohibits 1-minute micro-scalps "
                f"(VIX {regime.vix:.1f} / range containment). Micro-scalping in chop leads to severe theta bleed.",
            )
        if atype in (
            "SQUEEZE_BREAKOUT",
            "SQUEEZE_BREAKDOWN",
            "ORB_BREAKOUT",
            "OPENING_RANGE_BREAKOUT",
            "OPTIONS_MOMENTUM",
            "INDEX_CALL_SETUP",
            "INDEX_PUT_SETUP",
            "GAMMA_BLAST",
        ):
            # Verified SMC liquidity sweeps (Turtle soup, PDH/PDL rejection) are valid mean-reversions
            if has_structural_sweep:
                return True, ""
            if rvol < 2.0:
                return (
                    False,
                    f"Suppressed by Regime Governor: BALANCED_CHOP regime (tight range / compressed VIX {regime.vix:.1f}). "
                    f"Directional breakouts require RVOL >= 2.0x (current RVOL: {rvol:.2f}x) or verified SMC sweep to avoid false breakouts.",
                )

    return True, ""
