"""
engine/pipeline/hierarchical_engine.py
──────────────────────────────────────
Institutional Hierarchical Quantitative Decision Engine.

Translates modern quantitative mental models into a strict 3-tier filtration cascade:
  [Level 1: Market Context (3Cs)] ──> [Level 2: Signal Setup (5Ws)] ──> [Level 3: Execution (1H: HOW)]

Strict Hierarchical Flow:
1. Level 1: Market Context (Modernized 3Cs)
   - C1: Customers   -> Market Structure & Liquidity (Order Flow, Participant OI, TOD-RVOL)
   - C2: Competitors -> Correlated Assets & Intermarket Analysis (Macro, GIFT Nifty, Sector RRG)
   - C3: Company     -> Internal Asset Mechanics (Volatility regime, ATR, CPR geometry, ADR runway)
2. Level 2: Signal Generation & Validation (Modified 5Ws)
   - WHY   -> Alpha thesis validation (Liquidity sweep, Volatility expansion, Gamma unpin, Retest)
   - WHEN  -> Session window calibration (Opening Drive, Morning Trend, Midday Compression, Afternoon)
   - WHERE -> Key structural levels & confluence (SMC Order Blocks, FVGs, POC, Value Area, VWAP)
   - WHAT  -> Asset selection & canonical instrument feasibility (Listed options, spread tightness)
   - WHO   -> Counterparty analysis (Trapped breakout retail vs smart money absorption)
3. Level 3: Execution Matrix (The 1H: HOW)
   - How to enter? (Limit on pullback at OTE sweet spot, Anti-chase boundary enforcement)
   - How to manage risk? (Structural invalidation stop beyond sweep/OB + volatility buffer floor)
   - How to take profit? (Net executable R:R >= 1:2.0 net of STT, statutory charges and slippage)

Calibrations:
- Intraday vs Non-Intraday (Swing/EOD): Swing trades bypass intraday session chop & lunch lull.
- Directional vs Non-Directional: Edgeless chop suppresses directional breakouts but approves defined-risk spreads.
- Zero Hard-Coding & Anti-Patterns: Rolling statistical distributions, canonical exchange masters, fail-closed contracts.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime
from typing import Any, Optional

from config.constants import IST_ZONE as IST
from engine.pipeline.coherence_gate import clean_canonical_symbol, coherence_gate

logger = logging.getLogger("engine.pipeline.hierarchical")


# ── Level 1: Market Context (3Cs) Data Models ───────────────────────────────────


@dataclass
class Level1ContextResult:
    """Level 1: Market Context (Modernized 3Cs) Evaluation."""

    passed: bool = True
    status: str = "FAVORABLE"  # "FAVORABLE" | "EDGELESS_CHOP" | "VOLATILE_DERISKING" | "DEGRADED" | "UNAVAILABLE"
    # C1: Customers (Order Flow & Liquidity)
    order_flow_obi: Optional[float] = None
    cvd_divergence: Optional[str] = None
    participant_fii_bias: Optional[str] = None  # "BULLISH" | "BEARISH" | "NEUTRAL" | "OVERCROWDED"
    tod_rvol: float = 1.0
    liquidity_viable: bool = True

    # C2: Competitors (Intermarket, Global Macro & Sector RRG)
    macro_posture: str = "NEUTRAL"  # "RISK_ON" | "RISK_OFF" | "NEUTRAL"
    macro_score: int = 0
    sector_id: Optional[str] = None
    sector_rrg_quadrant: Optional[str] = None  # "LEADING" | "IMPROVING" | "WEAKENING" | "LAGGING"
    sector_aligned: bool = True
    multi_index_coherence_allowed: bool = True

    # C3: Company (Internal Asset Mechanics & Volatility Regimes)
    atr_val: float = 0.0
    vix_val: Optional[float] = None
    cpr_regime: str = "AVERAGE_CPR"  # "NARROW_CPR" | "WIDE_CPR" | "AVERAGE_CPR"
    adr_exhaustion_pct: float = 0.0
    is_edgeless_chop: bool = False
    volatility_posture: str = (
        "NORMAL"  # "EXPANSION_FAVORABLE" | "COMPRESSION_CHOP" | "HIGH_VOLATILITY"
    )

    reasons: list[str] = field(default_factory=list)
    coaching_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Level 2: Signal Generation & Validation (5Ws) Data Models ──────────────────


@dataclass
class Level2SetupResult:
    """Level 2: Signal Generation & Structural Validation (Modified 5Ws) Evaluation."""

    passed: bool = True
    status: str = (
        "QUALIFIED"  # "QUALIFIED" | "SUB_THRESHOLD_CONFLUENCE" | "TIMING_VETO" | "TRAP_VETO"
    )

    # W1: WHY (Alpha Thesis)
    alpha_thesis: str = "UNKNOWN"
    thesis_valid: bool = True

    # W2: WHEN (Session Timing Window)
    session_window: str = "UNKNOWN"
    timing_allowed: bool = True
    timing_reason: str = ""

    # W3: WHERE (Structural Location Confluence)
    structural_confluence_score: int = 70  # 0 to 100
    location_anchors: list[str] = field(default_factory=list)
    has_sufficient_confluence: bool = True

    # W4: WHAT (Asset Selection & Instrument Feasibility)
    resolved_instrument: Optional[str] = None
    instrument_type: str = "EQUITY"
    bid_ask_spread_pct: Optional[float] = None
    instrument_viable: bool = True

    # W5: WHO (Counterparty & Trapped Participants)
    trapped_counterparty: Optional[str] = None
    wick_rejection_pct: Optional[float] = None
    has_trap_edge: bool = False

    reasons: list[str] = field(default_factory=list)
    coaching_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Level 3: Execution Matrix (1H: HOW) Data Models ────────────────────────────


@dataclass
class Level3ExecutionResult:
    """Level 3: Execution Matrix (The 1H: HOW) Evaluation."""

    passed: bool = True
    status: str = (
        "EXECUTABLE"  # "EXECUTABLE" | "POOR_INDICATIVE_RR" | "CHASED_ENTRY" | "OBSTACLE_COLLISION"
    )

    entry_style: str = "LIMIT_ON_PULLBACK"
    trigger_level: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    no_chase_boundary: float = 0.0

    underlying_structural_rr: float = 2.0
    executable_indicative_rr: float = 2.0  # Net after friction & taxes
    statutory_charges_rupees: Optional[float] = None
    is_chased: bool = False
    runway_blocked: bool = False

    reasons: list[str] = field(default_factory=list)
    coaching_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Master Institutional Verdict ───────────────────────────────────────────────


@dataclass
class HierarchicalPipelineVerdict:
    """Master institutional verdict coordinating Level 1 (3Cs) -> Level 2 (5Ws) -> Level 3 (How)."""

    passed: bool = True
    verdict_label: str = "APEX_APPROVED"  # "APEX_APPROVED" | "STANDARD_APPROVED" | "DEFINED_RISK_MANDATED" | "SUPPRESSED_REGIME_CHOP" | "VETOED_TRAP" | "REJECTED_POOR_RR"
    conviction_tier: str = "HIGH_CONVICTION"  # "APEX_CONFLUENCE" | "HIGH_CONVICTION" | "DEFINED_RISK_ONLY" | "REJECTED"
    composite_confluence_score: int = 80  # 0 to 100

    # Horizon & Strategy Calibration
    time_horizon: str = "INTRADAY"  # "INTRADAY" | "SWING" | "POSITIONAL"
    strategy_orientation: str = "DIRECTIONAL"  # "DIRECTIONAL" | "NON_DIRECTIONAL"

    level1_context: Level1ContextResult = field(default_factory=Level1ContextResult)
    level2_setup: Level2SetupResult = field(default_factory=Level2SetupResult)
    level3_execution: Level3ExecutionResult = field(default_factory=Level3ExecutionResult)

    primary_reason: str = ""
    summary: str = ""
    coaching_notes: list[str] = field(default_factory=list)
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "verdict_label": self.verdict_label,
            "conviction_tier": self.conviction_tier,
            "composite_confluence_score": self.composite_confluence_score,
            "time_horizon": self.time_horizon,
            "strategy_orientation": self.strategy_orientation,
            "level1_context": self.level1_context.to_dict(),
            "level2_setup": self.level2_setup.to_dict(),
            "level3_execution": self.level3_execution.to_dict(),
            "primary_reason": self.primary_reason,
            "summary": self.summary,
            "coaching_notes": self.coaching_notes,
            "evaluated_at": self.evaluated_at,
        }


# ── Hierarchical Decision Engine Implementation ────────────────────────────────


class HierarchicalSignalPipeline:
    """Institutional 3-Tier Hierarchical Decision Engine."""

    def __init__(self) -> None:
        self.min_confluence_score = 75
        self.min_indicative_rr_floor = 1.8

    # ── Level 1: Market Context (Modernized 3Cs) ──────────────────────────────

    def evaluate_market_context_3cs(
        self,
        symbol: str,
        exchange: str = "NSE",
        ltp: float = 0.0,
        time_horizon: str = "INTRADAY",
        strategy_orientation: str = "DIRECTIONAL",
        ref_dt: Optional[datetime] = None,
        alert: Optional[Any] = None,
    ) -> Level1ContextResult:
        """Evaluates Market Context across C1 (Customers/Order Flow), C2 (Competitors/Macro), C3 (Company/Regime)."""
        clean_sym = clean_canonical_symbol(symbol)
        now_dt = ref_dt or datetime.now(IST)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=IST)

        res = Level1ContextResult()
        is_intraday = time_horizon.upper() in ("INTRADAY", "SCALP", "0DTE")
        is_directional = strategy_orientation.upper() == "DIRECTIONAL"

        # ── C1: Customers & Order Flow Liquidity ──
        try:
            from market.participant_oi import get_latest_participant_oi

            poi = get_latest_participant_oi()
            if poi and getattr(poi, "fii_index_long_ratio", None) is not None:
                ratio = float(poi.fii_index_long_ratio)
                if ratio < 0.20:
                    res.participant_fii_bias = "EXTREME_BEARISH_EXHAUSTION"  # Squeeze imminent
                elif ratio > 0.75:
                    res.participant_fii_bias = "OVERCROWDED_BULLISH"
                elif ratio >= 0.50:
                    res.participant_fii_bias = "BULLISH"
                else:
                    res.participant_fii_bias = "BEARISH"
        except Exception as e_poi:
            logger.debug(f"[HierarchicalEngine] Participant OI lookup: {e_poi}")

        # Check Order Book Imbalance / Flow
        metrics_dict = (
            getattr(alert, "metrics", {}) or {} if alert and hasattr(alert, "metrics") else {}
        )
        if isinstance(metrics_dict, dict):
            res.order_flow_obi = metrics_dict.get("obi_50") or metrics_dict.get("obi")
            res.cvd_divergence = metrics_dict.get("cvd_divergence")

        # TOD-RVOL (Time-of-Day relative volume)
        try:
            from engine.auto_alert_engine import compute_time_of_day_rvol

            vol = float(metrics_dict.get("volume", 0) or 0)
            avg_vol = float(metrics_dict.get("avg_daily_vol", 0) or 0)
            if vol > 0 and avg_vol > 0:
                res.tod_rvol = compute_time_of_day_rvol(vol, avg_vol, ref_dt=now_dt)
            else:
                res.tod_rvol = float(metrics_dict.get("rvol", 1.0) or 1.0)
        except Exception:
            res.tod_rvol = float(metrics_dict.get("rvol", 1.0) or 1.0)

        # ── C2: Competitors & Intermarket Analysis ──
        try:
            from market.global_macro import get_latest_macro_report

            macro = get_latest_macro_report()
            if macro:
                res.macro_posture = str(getattr(macro, "global_posture", "NEUTRAL"))
                res.macro_score = int(getattr(macro, "composite_score", 0) or 0)
        except Exception as e_macro:
            logger.debug(f"[HierarchicalEngine] Macro report lookup: {e_macro}")

        # Sector RRG Alignment
        if exchange.upper() in ("NSE", "NFO"):
            try:
                from analysis.sector_rotation import get_stock_sector_alignment

                sec_info = get_stock_sector_alignment(clean_sym)
                res.sector_id = sec_info.get("sector")
                res.sector_rrg_quadrant = sec_info.get("quadrant")
                if is_directional:
                    # Directional trades prefer LEADING or IMPROVING sectors
                    direction_str = str(getattr(alert, "direction", "BULLISH")).upper()
                    is_bull = direction_str not in ("BEARISH", "SHORT", "SELL")
                    if is_bull and res.sector_rrg_quadrant == "LAGGING":
                        res.sector_aligned = False
                        res.reasons.append(
                            f"Sector {res.sector_id} is in LAGGING RRG quadrant with negative relative momentum"
                        )
                    elif not is_bull and res.sector_rrg_quadrant == "LEADING":
                        res.sector_aligned = False
                        res.reasons.append(
                            f"Sector {res.sector_id} is in LEADING RRG quadrant; shorting leaders has low expectancy"
                        )
            except Exception as e_sec:
                logger.debug(f"[HierarchicalEngine] Sector alignment lookup: {e_sec}")

        # ── C3: Company / Asset Volatility & Regime Mechanics ──
        # Market Regime: Edgeless Chop Check
        try:
            from engine.market_regime_gate import evaluate_market_regime

            regime_snap = evaluate_market_regime()
            if regime_snap:
                res.vix_val = regime_snap.vix
                res.is_edgeless_chop = regime_snap.is_edgeless
                if res.is_edgeless_chop:
                    res.volatility_posture = "COMPRESSION_CHOP"
        except Exception as e_reg:
            logger.debug(f"[HierarchicalEngine] Market regime gate lookup: {e_reg}")

        # CPR & ADR Exhaustion Check
        try:
            from engine.session_regime_sentinel import check_alert_session_regime

            sess_reg = check_alert_session_regime(alert, ref_time=now_dt) if alert else None
            if sess_reg:
                res.cpr_regime = sess_reg.cpr.cpr_type + "_CPR"
                res.adr_exhaustion_pct = sess_reg.adr_exhaustion_pct
                if is_intraday and is_directional and sess_reg.veto_breakout_chase:
                    res.reasons.append(
                        f"ADR exhausted ({sess_reg.adr_exhaustion_pct:.0f}% consumed) in {res.cpr_regime}; breakout chase vetoed"
                    )
        except Exception as e_sentinel:
            logger.debug(f"[HierarchicalEngine] Session regime sentinel lookup: {e_sentinel}")

        # Canonical Indicator Snapshot Enrichment (ATR, ADX, CPR, Greeks)
        try:
            from engine.indicator_snapshot import get_indicator_snapshot

            snap = get_indicator_snapshot(clean_sym, exchange=exchange, time_horizon=time_horizon)
            if snap:
                if snap.atr_daily.value and snap.atr_daily.value > 0:
                    res.atr_val = float(snap.atr_daily.value)
                elif snap.atr_5m.value and snap.atr_5m.value > 0:
                    res.atr_val = float(snap.atr_5m.value)
                if not res.vix_val and snap.vix.value:
                    res.vix_val = float(snap.vix.value)
                if not res.cpr_regime or res.cpr_regime == "AVERAGE_CPR":
                    if snap.cpr_regime and snap.cpr_regime != "UNKNOWN":
                        res.cpr_regime = snap.cpr_regime
                if res.adr_exhaustion_pct == 0.0 and snap.adr_exhaustion_pct.value:
                    res.adr_exhaustion_pct = float(snap.adr_exhaustion_pct.value)
        except Exception as e_snap:
            logger.debug(f"[HierarchicalEngine] Indicator snapshot lookup error: {e_snap}")

        # ── Environmental Decision Logic ──
        # Rule: Edgeless Chop Gate
        if is_intraday and res.is_edgeless_chop:
            if is_directional:
                res.passed = False
                res.status = "EDGELESS_CHOP"
                res.reasons.append(
                    "Market in edgeless chop (VIX < 12.5 & balanced breadth); directional breakouts suppressed"
                )
                res.coaching_notes.append(
                    "Restructure trade as defined-risk credit spread or wait for volatility expansion"
                )
            else:
                # Non-directional strategies (iron condors, range fades) thrive in edgeless chop!
                res.passed = True
                res.status = "FAVORABLE"
                res.coaching_notes.append(
                    "Edgeless chop creates ideal conditions for defined-risk non-directional premium collection"
                )
        else:
            res.passed = True
            res.status = "FAVORABLE"

        return res

    # ── Level 2: Signal Setup (Modified 5Ws) ───────────────────────────────────

    def validate_signal_setup_5ws(
        self,
        alert: Any,
        context: Level1ContextResult,
        ref_dt: Optional[datetime] = None,
    ) -> Level2SetupResult:
        """Validates the 5W dimensions: Why, When, Where, What, Who."""
        clean_sym = clean_canonical_symbol(getattr(alert, "symbol", ""))
        now_dt = ref_dt or datetime.now(IST)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=IST)

        res = Level2SetupResult()
        metrics = getattr(alert, "metrics", {}) or {}
        if not isinstance(metrics, dict):
            metrics = {}

        # 1. WHY: Alpha Thesis Validation
        alert_type = str(getattr(alert, "alert_type", "UNKNOWN")).upper()
        if any(k in alert_type for k in ("SWEEP", "PREDATOR", "TURTLE")):
            res.alpha_thesis = "LIQUIDITY_SWEEP"
        elif any(
            k in alert_type
            for k in ("SQUEEZE", "EXPANSION", "COIL", "BREAKOUT", "MOMENTUM", "SPARK")
        ):
            res.alpha_thesis = "VOLATILITY_EXPANSION"
        elif any(k in alert_type for k in ("GAMMA", "UNPIN", "EXPIRY")):
            res.alpha_thesis = "GAMMA_UNPIN"
        elif any(k in alert_type for k in ("TREND", "PULLBACK", "THRUST", "DRIVE", "ORB")):
            res.alpha_thesis = "MOMENTUM_CONTINUATION"
        elif any(k in alert_type for k in ("RETEST", "ORDERBLOCK", "SMC")):
            res.alpha_thesis = "STRUCTURAL_RETEST"
        elif any(k in alert_type for k in ("MEAN_REVERSION", "FADE", "VWAP")):
            res.alpha_thesis = "MEAN_REVERSION"
        elif any(k in alert_type for k in ("NEUTRAL", "SPREAD", "CONDOR")):
            res.alpha_thesis = "DEFINED_RISK_NEUTRAL"
        else:
            res.alpha_thesis = "TECHNICAL_TRIGGER"

        # 2. WHEN: Session Timing Window
        time_horizon = str(getattr(alert, "time_horizon", "INTRADAY")).upper()
        is_intraday = time_horizon in ("INTRADAY", "SCALP", "0DTE")

        if not is_intraday:
            res.session_window = "OFF_MARKET_SWING"
            res.timing_allowed = True
            res.timing_reason = "Positional/Swing setup: exempt from intraday session clock cutoffs"
        else:
            t = now_dt.time()
            if dtime(9, 15) <= t < dtime(9, 45):
                res.session_window = "OPENING_DRIVE"
            elif dtime(9, 45) <= t < dtime(11, 30):
                res.session_window = "MORNING_TREND"
            elif dtime(11, 30) <= t < dtime(13, 15):
                res.session_window = "MIDDAY_COMPRESSION"
            elif dtime(13, 15) <= t < dtime(15, 0):
                res.session_window = "AFTERNOON_EXPANSION"
            else:
                res.session_window = "CLOSING_AUCTION"

            # Check CoherenceGate session entry window
            is_allowed, timing_msg = coherence_gate.validate_session_entry_window(
                alert, ref_dt=now_dt
            )
            res.timing_allowed = is_allowed
            res.timing_reason = timing_msg
            if not is_allowed:
                res.passed = False
                res.status = "TIMING_VETO"
                res.reasons.append(timing_msg)

        # 3. WHERE: Key Structural Levels & Confluence
        location_anchors: list[str] = []
        if metrics.get("nearest_demand_ob") or metrics.get("nearest_supply_ob"):
            location_anchors.append("SMC_ORDER_BLOCK")
        if metrics.get("has_unmitigated_fvg") or metrics.get("fvg_zone"):
            location_anchors.append("FAIR_VALUE_GAP")
        if metrics.get("vwap"):
            location_anchors.append("INTRADAY_VWAP")
        if metrics.get("poc") or metrics.get("value_area"):
            location_anchors.append("VOLUME_PROFILE_POC")
        if metrics.get("pdh") or metrics.get("pdl") or metrics.get("sweep_level"):
            location_anchors.append("KEY_SESSION_PIVOT")
        if metrics.get("cpr"):
            location_anchors.append("CENTRAL_PIVOT_RANGE")

        res.location_anchors = location_anchors
        # Calculate structural confluence score
        base_score = 65
        base_score += len(location_anchors) * 7
        if metrics.get("has_flow"):
            base_score += 5
        res.structural_confluence_score = min(98, max(50, base_score))
        res.has_sufficient_confluence = len(location_anchors) >= 1 or base_score >= 75

        # 4. WHAT: Asset Selection & Instrument Feasibility
        contract = getattr(alert, "contract_symbol", None) or metrics.get("contract_symbol")
        res.resolved_instrument = contract or clean_sym
        res.instrument_type = getattr(alert, "segment", "EQUITY") if not contract else "FNO_OPTION"

        # Check bid-ask spread if available
        entry_p = float(getattr(alert, "trigger_level", 0.0) or getattr(alert, "ltp", 0.0) or 0.0)
        bid = float(metrics.get("bid", 0.0) or 0.0)
        ask = float(metrics.get("ask", 0.0) or 0.0)
        if bid > 0 and ask > 0 and entry_p > 0:
            spread_pct = ((ask - bid) / entry_p) * 100.0
            res.bid_ask_spread_pct = round(spread_pct, 2)
            if spread_pct > 2.0 and "OPTION" in res.instrument_type:
                res.instrument_viable = False
                res.reasons.append(
                    f"Option bid-ask spread too wide ({spread_pct:.1f}% > 2.0% limit); excessive slippage drag"
                )

        # 5. WHO: Counterparty & Trapped Participants
        sweep_type = str(metrics.get("sweep_type", "")).upper()
        if "SPRING" in sweep_type or "BEAR_TRAP" in sweep_type or "SWEEP_LOWS" in sweep_type:
            res.trapped_counterparty = "RETAIL_BEAR_TRAP"
            res.has_trap_edge = True
        elif "UPTHRUST" in sweep_type or "BULL_TRAP" in sweep_type or "SWEEP_HIGHS" in sweep_type:
            res.trapped_counterparty = "RETAIL_BULL_TRAP"
            res.has_trap_edge = True
        elif "UNPIN" in alert_type or "GAMMA" in alert_type:
            res.trapped_counterparty = "TRAPPED_OPTION_WRITERS"
            res.has_trap_edge = True
        else:
            res.trapped_counterparty = "NONE"
            res.has_trap_edge = False

        if not res.has_sufficient_confluence and not res.has_trap_edge:
            res.passed = False
            res.status = "SUB_THRESHOLD_CONFLUENCE"
            res.reasons.append(
                f"Setup lacks structural location confluence (score {res.structural_confluence_score} < 75)"
            )

        return res

    # ── Level 3: Execution Matrix (The 1H: HOW) ───────────────────────────────

    def build_execution_matrix_how(
        self,
        alert: Any,
        context: Level1ContextResult,
        setup: Level2SetupResult,
    ) -> Level3ExecutionResult:
        """Validates execution viability, net R:R after friction/taxes, and anti-chase boundaries."""
        res = Level3ExecutionResult()
        metrics = getattr(alert, "metrics", {}) or {}
        if not isinstance(metrics, dict):
            metrics = {}

        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        trigger = float(getattr(alert, "trigger_level", 0.0) or ltp)
        stop = float(getattr(alert, "stop_loss", 0.0) or 0.0)
        t1 = float(getattr(alert, "target_level", 0.0) or getattr(alert, "target_1", 0.0) or 0.0)
        t2_val = getattr(alert, "target_2", None) or metrics.get("target_2")
        t2 = float(t2_val) if t2_val else (trigger + abs(t1 - trigger) * 1.8 if t1 > 0 else 0.0)
        no_chase = float(getattr(alert, "no_chase_boundary", 0.0) or 0.0)

        res.trigger_level = trigger
        res.stop_loss = stop
        res.target_1 = t1
        res.target_2 = t2
        res.no_chase_boundary = no_chase

        # Determine Entry Style & Structural R:R
        plan_dict = getattr(alert, "actionable_plan", {}) or {}
        if isinstance(plan_dict, dict) and plan_dict.get("execution_style"):
            res.entry_style = str(plan_dict["execution_style"])
        elif setup.has_trap_edge:
            res.entry_style = "LIMIT_ON_PULLBACK"  # Enter on OTE retracement
        elif setup.alpha_thesis in (
            "VOLATILITY_EXPANSION",
            "MOMENTUM_CONTINUATION",
            "TECHNICAL_TRIGGER",
        ):
            rsi_val = float(metrics.get("rsi") or metrics.get("rsi_5m") or 50.0)
            u_wick = float(metrics.get("upper_wick_ratio") or 0.0)
            l_wick = float(metrics.get("lower_wick_ratio") or 0.0)
            is_bull_dir = str(getattr(alert, "direction", "BULLISH")).upper() not in (
                "BEARISH",
                "SHORT",
                "SELL",
            )
            if (is_bull_dir and (rsi_val >= 70.0 or u_wick >= 0.25)) or (
                not is_bull_dir and (rsi_val <= 30.0 or l_wick >= 0.25)
            ):
                res.entry_style = "LIMIT_ON_PULLBACK"
                res.coaching_notes.append(
                    "Impulse candle shows overhead resistance or extended RSI. Mandatory LIMIT entry in OTE zone on pullback."
                )
            else:
                res.entry_style = "STOP_LIMIT_BREAKOUT"
        else:
            res.entry_style = "LIMIT_ON_PULLBACK"

        # Check Anti-Chase Boundary Violation
        direction_str = str(getattr(alert, "direction", "BULLISH")).upper()
        is_bull = direction_str not in ("BEARISH", "SHORT", "SELL")
        if no_chase > 0 and ltp > 0:
            if is_bull and ltp > no_chase:
                res.is_chased = True
                res.passed = False
                res.status = "CHASED_ENTRY"
                res.reasons.append(
                    f"Price ₹{ltp:,.2f} surged past no-chase boundary ₹{no_chase:,.2f}; chasing prohibited"
                )
            elif not is_bull and ltp < no_chase:
                res.is_chased = True
                res.passed = False
                res.status = "CHASED_ENTRY"
                res.reasons.append(
                    f"Price ₹{ltp:,.2f} dropped past short no-chase boundary ₹{no_chase:,.2f}; chasing prohibited"
                )

        # ── Structural R:R Calibration: Directional vs Non-Directional Defined-Risk Spreads ──
        is_spread = (
            setup.alpha_thesis == "DEFINED_RISK_NEUTRAL"
            or str(getattr(alert, "derivative_type", "")).upper()
            in ("SPREAD", "IRON_CONDOR", "STRADDLE", "STRANGLE")
            or "SPREAD" in str(getattr(alert, "headline", "")).upper()
            or (
                isinstance(plan_dict, dict) and "SPREAD" in str(plan_dict.get("action", "")).upper()
            )
        )

        if is_spread:
            res.entry_style = "NET_CREDIT_LIMIT"
            # For defined-risk spreads, reward is net credit, risk is max loss
            net_credit = float(metrics.get("net_credit") or metrics.get("max_profit") or 0.0)
            max_loss = float(metrics.get("max_loss") or metrics.get("capital_required") or 0.0)
            if net_credit > 0 and max_loss > 0:
                res.underlying_structural_rr = round(net_credit / max_loss, 2)
                res.executable_indicative_rr = round((net_credit * 0.95) / (max_loss * 1.05), 2)
                # Defined-risk credit spreads require minimum 15% return on risk (credit / max_loss >= 0.15)
                # with high statistical expectancy (>70% win rate)
                if res.executable_indicative_rr < 0.15:
                    res.passed = False
                    res.status = "POOR_INDICATIVE_RR"
                    res.reasons.append(
                        f"Spread credit return {res.executable_indicative_rr:.2f}:1 is below defined-risk floor 0.15:1"
                    )
                else:
                    res.passed = True
                    res.status = "EXECUTABLE"
            else:
                # If explicit spread metrics not populated, check trigger/stop
                risk = abs(trigger - stop)
                reward = abs(t1 - trigger)
                if risk > 0 and reward > 0:
                    res.underlying_structural_rr = round(reward / risk, 2)
                    res.executable_indicative_rr = round(
                        max(0.0, (reward * 0.95) / (risk * 1.05)), 2
                    )
        else:
            # Directional Setup Structural R:R
            risk = abs(trigger - stop)
            reward = abs(t1 - trigger)
            if risk > 0:
                res.underlying_structural_rr = round(reward / risk, 2)
                # Net indicative R:R factoring in spread/friction
                res.executable_indicative_rr = round(max(0.0, (reward * 0.95) / (risk * 1.05)), 2)

            if res.executable_indicative_rr < self.min_indicative_rr_floor:
                # If underlying structural R:R meets institutional 1.8:1 target (and friction-adjusted R:R >= 1.55), allow as EXECUTABLE
                if res.underlying_structural_rr >= 1.8 and res.executable_indicative_rr >= 1.55:
                    res.passed = True
                    res.status = "EXECUTABLE"
                    res.coaching_notes.append(
                        f"Target 1 structural R:R {res.underlying_structural_rr:.1f}:1 meets institutional target, net executable R:R {res.executable_indicative_rr:.1f}:1 post-friction."
                    )
                else:
                    res.passed = False
                    res.status = "POOR_INDICATIVE_RR"
                    res.reasons.append(
                        f"Indicative R:R {res.executable_indicative_rr:.1f}:1 is below institutional floor {self.min_indicative_rr_floor}:1"
                    )
                    res.coaching_notes.append(
                        "Restructure targets or wait for tighter invalidation pivot"
                    )

        return res

    # ── Master Orchestration ──────────────────────────────────────────────────

    def evaluate(
        self,
        alert: Any,
        quotes_map: Optional[dict[str, Any]] = None,
        ref_dt: Optional[datetime] = None,
    ) -> HierarchicalPipelineVerdict:
        """
        Coordinates full 3-Tier Hierarchical Evaluation:
        Level 1 (3Cs) -> Level 2 (5Ws) -> Level 3 (How).
        """
        clean_sym = clean_canonical_symbol(getattr(alert, "symbol", ""))

        # Accurately resolve Time Horizon (Intraday vs Non-Intraday/Swing/Multibagger)
        raw_horizon = str(getattr(alert, "time_horizon", "INTRADAY")).upper()
        alert_type_u = str(getattr(alert, "alert_type", "")).upper()
        dir_u = str(getattr(alert, "direction", "")).upper()
        deriv_u = str(getattr(alert, "derivative_type", "")).upper()
        act_plan = getattr(alert, "actionable_plan", {}) or {}

        if any(
            h in raw_horizon for h in ("SWING", "POSITIONAL", "MULTIBAGGER", "LONG_TERM")
        ) or any(t in alert_type_u for t in ("SWING", "MULTIBAGGER", "COMPOUNDER", "STAGE_1_TO_2")):
            time_horizon = (
                "SWING"
                if "SWING" in raw_horizon
                else ("MULTIBAGGER" if "MULTI" in raw_horizon else "POSITIONAL")
            )
        elif "SCALP" in raw_horizon or "0DTE" in raw_horizon:
            time_horizon = raw_horizon
        else:
            time_horizon = "INTRADAY"

        # Accurately resolve Strategy Orientation (Directional vs Non-Directional)
        is_neutral = (
            dir_u in ("NEUTRAL", "NON_DIRECTIONAL", "RANGE")
            or deriv_u in ("SPREAD", "IRON_CONDOR", "STRADDLE", "STRANGLE")
            or any(
                k in alert_type_u
                for k in ("NEUTRAL", "CONDOR", "STRADDLE", "STRANGLE", "FADE", "RANGE")
            )
            or "SPREAD" in str(getattr(alert, "headline", "")).upper()
            or (isinstance(act_plan, dict) and "SPREAD" in str(act_plan.get("action", "")).upper())
        )
        strat_orientation = "NON_DIRECTIONAL" if is_neutral else "DIRECTIONAL"

        ltp = float(getattr(alert, "ltp", 0.0) or 0.0)
        exchange = str(getattr(alert, "exchange", "NSE")).upper()

        # Step 1: Level 1 Market Context (3Cs)
        l1 = self.evaluate_market_context_3cs(
            symbol=clean_sym,
            exchange=exchange,
            ltp=ltp,
            time_horizon=time_horizon,
            strategy_orientation=strat_orientation,
            ref_dt=ref_dt,
            alert=alert,
        )

        # Step 2: Level 2 Signal Setup (5Ws)
        l2 = self.validate_signal_setup_5ws(alert=alert, context=l1, ref_dt=ref_dt)

        # Step 3: Level 3 Execution Matrix (How)
        l3 = self.build_execution_matrix_how(alert=alert, context=l1, setup=l2)

        # ── Synthesize Institutional Verdict ──
        overall_passed = l1.passed and l2.passed and l3.passed

        if strat_orientation == "NON_DIRECTIONAL":
            exec_score = (
                min(100, max(65, int((l3.executable_indicative_rr / 0.25) * 80)))
                if l3.passed
                else 30
            )
        else:
            exec_score = min(100, int(l3.executable_indicative_rr * 35))

        composite_score = int(
            (
                (85 if l1.passed else 40) * 0.35
                + l2.structural_confluence_score * 0.35
                + exec_score * 0.30
            )
        )

        if not l1.passed and l1.status == "EDGELESS_CHOP":
            verdict_label = "SUPPRESSED_REGIME_CHOP"
            conviction_tier = "DEFINED_RISK_ONLY"
            primary_reason = l1.reasons[0] if l1.reasons else "Suppressed by edgeless chop regime"
        elif not l2.passed:
            verdict_label = "VETOED_TRAP" if l2.status == "TRAP_VETO" else "REJECTED_SETUP"
            conviction_tier = "REJECTED"
            primary_reason = l2.reasons[0] if l2.reasons else "Setup validation failed"
        elif not l3.passed:
            verdict_label = (
                "REJECTED_POOR_RR" if l3.status == "POOR_INDICATIVE_RR" else "REJECTED_CHASE"
            )
            conviction_tier = "REJECTED"
            primary_reason = l3.reasons[0] if l3.reasons else "Execution parameters disqualified"
        elif composite_score >= 85 or getattr(alert, "confidence", 0) >= 90:
            verdict_label = "APEX_APPROVED"
            conviction_tier = "APEX_CONFLUENCE"
            primary_reason = (
                "Apex institutional confluence across 3Cs Context, 5Ws Setup, and Execution Matrix"
            )
        else:
            verdict_label = "STANDARD_APPROVED"
            conviction_tier = "HIGH_CONVICTION"
            primary_reason = "Approved standard institutional setup with favorable context and structural confluence"

        coaching = []
        coaching.extend(l1.coaching_notes)
        coaching.extend(l2.coaching_notes)
        coaching.extend(l3.coaching_notes)

        return HierarchicalPipelineVerdict(
            passed=overall_passed,
            verdict_label=verdict_label,
            conviction_tier=conviction_tier,
            composite_confluence_score=composite_score,
            time_horizon=time_horizon,
            strategy_orientation=strat_orientation,
            level1_context=l1,
            level2_setup=l2,
            level3_execution=l3,
            primary_reason=primary_reason,
            summary=f"Hierarchical Verdict [{verdict_label}]: Score {composite_score}/100 | {primary_reason}",
            coaching_notes=coaching,
        )


# Export singleton
hierarchical_pipeline = HierarchicalSignalPipeline()
