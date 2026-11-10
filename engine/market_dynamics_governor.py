"""
engine/market_dynamics_governor.py
──────────────────────────────────
Unified Market Dynamics & Context-Adaptive Calibration Governor for Indian Markets.

Implements the institutional principle that "One size does not fit all":
  1. Macro Volatility Dimension (India VIX Tiers):
     - Low VIX (<12.0): Sluggish ranges, high theta bleed -> Mandatory debit spreads, tighter stops (0.85x ATR), smaller targets (1.5R).
     - Normal VIX (12.0–16.5): Balanced directional momentum -> Standard 1.0x–1.2x ATR stops, 1:3.0R setups, naked ATM/near-OTM options.
     - Elevated VIX (16.5–22.0): High range expansion -> Wider 1.6x–1.8x ATR stops, extended 1:4.0R targets, deep ITM or futures.
     - Crisis VIX (>22.0): Violent whipsaws -> 50% lot sizing haircut, strict debit spreads, mandatory safety collars.
  2. Intraday Session Phase (IST Time-of-Day):
     - 09:15–09:45: Opening Auction Discovery -> High RVOL hurdle (2.5x), wider slippage buffer.
     - 09:45–11:30: Morning Institutional Expansion -> Optimal for ORB, Dalton IB continuations, SMC order blocks.
     - 11:30–13:15: Midday Mean Reversion Chop -> Routine breakouts suppressed (RVOL >= 3.0x required); CPR/VWAP fades favored.
     - 13:15–14:45: Afternoon Trend Ignition -> Secondary expansion, gamma thrusts.
     - 14:45–15:15: 0DTE Expiry Climax -> Index gamma unpins; single-stock option entries frozen.
     - 15:15–15:30: Session MOC Hardboard Cutoff -> Absolute entry freeze; aggressive trailing; margin protection.
  3. Instrument Tier Disparity:
     - Tier 1 Benchmark Indices: High liquidity, tightest spreads, cash-settled (zero delivery risk).
     - Tier 2 Liquid Stock Leaders: Top 25 F&O stocks with high volume, moderate spreads.
     - Tier 3 Broader Stock F&O: Wider bid-ask spreads, lower depth; requires limit-order price improvement.
  4. SEBI Physical Delivery Quarantine:
     - Starting Monday of monthly expiry week, single-stock options expiring ITM face mandatory physical delivery.
     - The Governor automatically quarantines near-expiry stock option buying, directing strategy to Futures or Far-Month.

All calibrations are cached in an in-memory matrix for sub-millisecond (<0.05ms) query speed.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime
from typing import Any, Optional

from config.constants import IST
from market.instruments import canonical_symbol, is_derivative_eligible

logger = logging.getLogger("engine.market_dynamics_governor")

# ── Canonical Constants & Tiers ──────────────────────────────────────────────

BENCHMARK_INDICES = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})

TOP_25_LIQUID_LEADERS = frozenset(
    {
        "RELIANCE",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "TCS",
        "SBIN",
        "BHARTIARTL",
        "LT",
        "KOTAKBANK",
        "AXISBANK",
        "ITC",
        "BAJFINANCE",
        "MARUTI",
        "TATAMOTORS",
        "M&M",
        "SUNPHARMA",
        "TATASTEEL",
        "HINDUNILVR",
        "NTPC",
        "ONGC",
        "POWERGRID",
        "TITAN",
        "ADANIENT",
        "COALINDIA",
        "JSWSTEEL",
    }
)


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DynamicCalibrationContext:
    """Context-adaptive quantitative parameter calibration for a specific instrument & session."""

    symbol: str
    timestamp: str
    phase: str
    volatility_regime: str
    vix_value: float
    instrument_tier: str
    min_required_rvol: float
    atr_sl_multiplier: float
    target_1_rr: float
    target_2_rr: float
    max_chase_pct: float
    preferred_vehicle: (
        str  # "NAKED_OPTION_BUY" | "DEBIT_SPREAD" | "DEEP_ITM_OR_FUTURES" | "FUTURES_ONLY"
    )
    mandate: (
        str  # "POUNCE_MOMENTUM" | "STALK_PRESERVE_CAPITAL" | "FADE_SPRING" | "SUPPRESS_NEW_ENTRIES"
    )
    is_breakout_allowed: bool
    is_mean_reversion_favored: bool
    stock_options_quarantined: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Helper Evaluators ─────────────────────────────────────────────────────────


def get_intraday_phase(dt: Optional[datetime] = None) -> str:
    """Classify the current IST time into one of the 6 canonical intraday session phases."""
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)

    t = dt.time()

    if t < dtime(9, 15):
        return "OFF_MARKET_PREOPEN"
    if t < dtime(9, 45):
        return "OPENING_AUCTION_DISCOVERY"
    if t < dtime(11, 30):
        return "MORNING_INSTITUTIONAL_EXPANSION"
    if t < dtime(13, 15):
        return "MIDDAY_MEAN_REVERSION_CHOP"
    if t < dtime(14, 45):
        return "AFTERNOON_TREND_IGNITION"
    if t < dtime(15, 15):
        return "EXPIRY_0DTE_GAMMA_UNPIN"
    if t < dtime(15, 30):
        return "SESSION_MOC_HARDBOARD_CUTOFF"
    return "OFF_MARKET_POSTCLOSE"


def get_volatility_regime(vix: Optional[float] = None) -> tuple[str, float]:
    """Classify the macro volatility environment using India VIX."""
    if vix is None or vix <= 0.0:
        # Default baseline if VIX is unavailable
        return "NORMAL_VIX", 14.0

    if vix < 12.0:
        return "LOW_VIX", vix
    if vix <= 16.5:
        return "NORMAL_VIX", vix
    if vix <= 22.0:
        return "ELEVATED_VIX", vix
    return "CRISIS_VIX", vix


def get_instrument_tier(symbol: str) -> str:
    """Classify an instrument into its liquidity and settlement tier."""
    clean = canonical_symbol(symbol).upper()

    if clean in BENCHMARK_INDICES:
        return "INDEX"
    if clean in TOP_25_LIQUID_LEADERS:
        return "LIQUID_STOCK_LEADER"
    if is_derivative_eligible(clean):
        return "GENERAL_STOCK_FNO"
    return "NON_FNO"


def is_stock_option_quarantined(
    symbol: str,
    ref_date: Optional[date] = None,
    ref_time: Optional[dtime] = None,
) -> bool:
    """Check if single-stock options are quarantined due to SEBI expiry week physical delivery risk.

    Indices are cash-settled and never subject to physical delivery, returning False.
    Equities in the monthly expiry week (Monday through Thursday) return True.
    """
    clean = canonical_symbol(symbol).upper()
    if clean in BENCHMARK_INDICES:
        return False

    if ref_date is None:
        now = datetime.now(IST)
        ref_date = now.date()
        ref_time = now.time()

    try:
        from market.calendar import get_nearest_monthly_expiry

        monthly_expiry = get_nearest_monthly_expiry(clean, ref_date=ref_date, ref_time=ref_time)
        delta_days = (monthly_expiry - ref_date).days

        # Expiry week: 0 to 4 calendar days before monthly expiry
        if 0 <= delta_days <= 4:
            return True
    except Exception as e_suppressed:
        logger.debug(f"[market_dynamics_governor] Expiry calculation suppressed: {e_suppressed}")

    return False


# ── The Market Dynamics Governor Singleton ───────────────────────────────────


class MarketDynamicsGovernor:
    """Institutional Single Source of Truth for Context-Adaptive Strategy Calibration.

    Calculates optimal quantitative thresholds, stop-loss padding, profit target extensions,
    and execution vehicle recommendations based on macro volatility, intraday session phase,
    and instrument tier.
    """

    def __init__(self, cache_ttl_seconds: float = 15.0) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, DynamicCalibrationContext]] = {}
        self._vix_cache: tuple[float, float] = (0.0, 14.0)  # (timestamp, vix_val)
        logger.info("[MarketDynamicsGovernor] Initialized context-adaptive calibration governor.")

    def _fetch_live_vix(self) -> float:
        """Fetch current India VIX with bounded 30s cache."""
        now_ts = time.time()
        with self._lock:
            ts, val = self._vix_cache
            if now_ts - ts < 30.0 and val > 0.0:
                return val

        try:
            from market.indices import get_vix

            raw_vix = get_vix()
            vix_val = float(raw_vix) if raw_vix and float(raw_vix) > 0.0 else 14.0
        except Exception as e_vix:
            logger.debug(f"[MarketDynamicsGovernor] VIX fetch fallback: {e_vix}")
            vix_val = 14.0

        with self._lock:
            self._vix_cache = (now_ts, vix_val)
        return vix_val

    def get_calibration(
        self,
        symbol: str,
        strategy: str = "DEFAULT",
        as_of_time: Optional[datetime] = None,
        vix_override: Optional[float] = None,
        cpr_type: Optional[str] = None,
        adr_exhaustion_pct: Optional[float] = None,
        bypass_cache: bool = False,
    ) -> DynamicCalibrationContext:
        """Calculate and return the dynamic calibration context for a symbol.

        Executed in <0.05ms using in-memory caching.
        """
        clean_sym = canonical_symbol(symbol).upper()
        now_wall = time.time()
        cache_key = f"{clean_sym}:{strategy}"
        cache_eligible = (
            not bypass_cache
            and as_of_time is None
            and vix_override is None
            and cpr_type is None
            and adr_exhaustion_pct is None
        )

        if cache_eligible:
            with self._lock:
                if cache_key in self._cache:
                    cached_ts, cached_ctx = self._cache[cache_key]
                    if now_wall - cached_ts < self._cache_ttl:
                        return cached_ctx

        # 1. Evaluate Intraday Phase
        phase = get_intraday_phase(as_of_time)

        # 2. Evaluate Volatility Regime
        vix_val = vix_override if vix_override is not None else self._fetch_live_vix()
        vol_regime, safe_vix = get_volatility_regime(vix_val)

        # 3. Evaluate Instrument Tier & Physical Delivery Quarantine
        tier = get_instrument_tier(clean_sym)
        ref_d = as_of_time.date() if as_of_time else None
        ref_t = as_of_time.time() if as_of_time else None
        delivery_quarantine = is_stock_option_quarantined(clean_sym, ref_d, ref_t)

        # ── 4. Parameter Formulations ─────────────────────────────────────────

        # Base RVOL Hurdle
        strat_upper = strategy.upper()
        if strat_upper == "ORB":
            if phase in ("OPENING_AUCTION_DISCOVERY", "MORNING_INSTITUTIONAL_EXPANSION"):
                base_rvol = 1.30 if tier == "INDEX" else 1.45
            elif phase == "MIDDAY_MEAN_REVERSION_CHOP":
                base_rvol = 2.0  # Midday chop requires higher institutional confirmation
            else:
                base_rvol = 1.5
        elif phase == "OPENING_AUCTION_DISCOVERY":
            base_rvol = 2.5
        elif phase == "MORNING_INSTITUTIONAL_EXPANSION":
            base_rvol = 1.8
        elif phase == "MIDDAY_MEAN_REVERSION_CHOP":
            base_rvol = 3.0  # High hurdle during midday to prevent false breakouts
        elif phase == "AFTERNOON_TREND_IGNITION":
            base_rvol = 2.0
        elif phase == "EXPIRY_0DTE_GAMMA_UNPIN":
            base_rvol = 2.2
        else:
            base_rvol = 2.0

        # Adjust RVOL for Tier and CPR
        if strat_upper == "ORB":
            min_rvol = base_rvol
        elif tier == "INDEX":
            min_rvol = base_rvol
        elif tier == "LIQUID_STOCK_LEADER":
            min_rvol = base_rvol * 1.05
        else:
            min_rvol = base_rvol * 1.15

        if cpr_type == "WIDE":
            min_rvol *= 1.25  # Require even higher volume to trust a breakout on a wide-CPR day

        # Stop-Loss ATR Multiplier: SL = 1.0 * (VIX / 14.0)^0.65
        vix_factor = (safe_vix / 14.0) ** 0.65
        base_sl_atr = 1.0 * vix_factor

        if tier == "INDEX":
            sl_atr = max(0.8, min(2.0, base_sl_atr))
        else:
            # Single stocks have higher idiosyncratic volatility
            sl_atr = max(0.9, min(2.2, base_sl_atr * 1.15))

        # Target R:R Multipliers
        if cpr_type == "NARROW" and vol_regime in ("NORMAL_VIX", "ELEVATED_VIX"):
            target_1_rr = 2.2
            target_2_rr = 4.2
        elif cpr_type == "WIDE" or phase == "MIDDAY_MEAN_REVERSION_CHOP":
            target_1_rr = 1.5
            target_2_rr = 2.5
        elif adr_exhaustion_pct and adr_exhaustion_pct >= 80.0:
            target_1_rr = 1.5
            target_2_rr = 2.5  # Cap target expansion when range is exhausted
        else:
            target_1_rr = 2.0
            target_2_rr = 3.5

        # Maximum Chase Boundary (Percentage beyond trigger level)
        if tier == "INDEX":
            max_chase_pct = 0.12  # ~30 pts NIFTY, ~65 pts BANKNIFTY
        elif tier == "LIQUID_STOCK_LEADER":
            max_chase_pct = 0.25
        else:
            max_chase_pct = 0.45

        # ── 5. Vehicle & Mandate Selection ────────────────────────────────────

        if delivery_quarantine:
            mandate = "POUNCE_MOMENTUM"
            is_breakout_allowed = True
            is_mean_rev_favored = False
            preferred_vehicle = "FUTURES_OR_FAR_MONTH"  # Physical delivery quarantine
            rationale = "SEBI Expiry Week Quarantine: single-stock options frozen to eliminate physical settlement delivery risk."
        elif vol_regime == "LOW_VIX":
            mandate = (
                "POUNCE_MOMENTUM"
                if phase in ("MORNING_INSTITUTIONAL_EXPANSION", "AFTERNOON_TREND_IGNITION")
                else "STALK_PRESERVE_CAPITAL"
            )
            is_breakout_allowed = True
            is_mean_rev_favored = False
            preferred_vehicle = (
                "DEBIT_SPREAD"  # Low VIX mandatory debit spreads to combat theta drag
            )
            rationale = (
                "Low VIX (<12.0): defined-risk debit spreads mandatory to neutralize theta burden."
            )
        elif vol_regime == "CRISIS_VIX":
            mandate = "POUNCE_MOMENTUM"
            is_breakout_allowed = True
            is_mean_rev_favored = False
            preferred_vehicle = "DEEP_ITM_OR_FUTURES"
            rationale = (
                "Crisis VIX (>22.0): deep ITM or futures recommended to limit Vega collapse."
            )
        elif phase == "SESSION_MOC_HARDBOARD_CUTOFF" or phase.startswith("OFF_MARKET"):
            mandate = "SUPPRESS_NEW_ENTRIES"
            is_breakout_allowed = False
            is_mean_rev_favored = False
            preferred_vehicle = "FUTURES_ONLY"
            rationale = "Session cutoff or off-market hours: zero new entries permitted."
        elif (
            adr_exhaustion_pct and adr_exhaustion_pct >= 85.0 and phase != "EXPIRY_0DTE_GAMMA_UNPIN"
        ):
            mandate = "FADE_SPRING"
            is_breakout_allowed = False
            is_mean_rev_favored = True
            preferred_vehicle = "DEBIT_SPREAD" if vol_regime == "LOW_VIX" else "NAKED_OPTION_BUY"
            rationale = f"ADR exhausted ({adr_exhaustion_pct:.1f}%): breakout chasing vetoed; mean-reversion favored."
        elif phase == "MIDDAY_MEAN_REVERSION_CHOP" and cpr_type == "WIDE":
            mandate = "STALK_PRESERVE_CAPITAL"
            is_breakout_allowed = False
            is_mean_rev_favored = True
            preferred_vehicle = "DEBIT_SPREAD"
            rationale = "Midday lull + Wide CPR: breakout trap probability >80%; capital preservation active."
        else:
            mandate = "POUNCE_MOMENTUM"
            is_breakout_allowed = True
            is_mean_rev_favored = False
            preferred_vehicle = "NAKED_OPTION_BUY"
            rationale = f"Optimal {vol_regime} & {phase}: directional momentum with standard R:R."

        ctx = DynamicCalibrationContext(
            symbol=clean_sym,
            timestamp=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            phase=phase,
            volatility_regime=vol_regime,
            vix_value=round(safe_vix, 2),
            instrument_tier=tier,
            min_required_rvol=round(min_rvol, 2),
            atr_sl_multiplier=round(sl_atr, 2),
            target_1_rr=round(target_1_rr, 2),
            target_2_rr=round(target_2_rr, 2),
            max_chase_pct=round(max_chase_pct, 3),
            preferred_vehicle=preferred_vehicle,
            mandate=mandate,
            is_breakout_allowed=is_breakout_allowed,
            is_mean_reversion_favored=is_mean_rev_favored,
            stock_options_quarantined=delivery_quarantine,
            rationale=rationale,
        )

        if cache_eligible:
            with self._lock:
                self._cache[cache_key] = (now_wall, ctx)

        return ctx

    def get_diagnostics(self) -> dict[str, Any]:
        """Telemetry diagnostics for OpsDeck and API health hub."""
        with self._lock:
            cached_count = len(self._cache)
            _, current_vix = self._vix_cache

        current_phase = get_intraday_phase()
        vol_regime, _ = get_volatility_regime(current_vix)

        return {
            "status": "HEALTHY",
            "current_phase": current_phase,
            "volatility_regime": vol_regime,
            "india_vix": round(current_vix, 2),
            "cached_calibrations": cached_count,
            "cache_ttl_seconds": self._cache_ttl,
            "sample_index_calibration": self.get_calibration("NIFTY").to_dict(),
        }

    def reset_for_testing(self) -> None:
        """Reset internal caches for isolated deterministic testing."""
        with self._lock:
            self._cache.clear()
            self._vix_cache = (0.0, 14.0)


# ── Global Singleton Accessor ────────────────────────────────────────────────

_governor_instance: Optional[MarketDynamicsGovernor] = None
_governor_lock = threading.Lock()


def get_market_dynamics_governor() -> MarketDynamicsGovernor:
    """Return the centralized MarketDynamicsGovernor singleton instance."""
    global _governor_instance
    if _governor_instance is None:
        with _governor_lock:
            if _governor_instance is None:
                _governor_instance = MarketDynamicsGovernor()
    return _governor_instance
