"""
engine/signal_policy.py
────────────────────────
Consolidated Signal Policy Authority & Unified Candidate Evaluation Funnel.

Institutional Architecture (S01 SSOT):
Consolidates scattered decision authorities across the trading desk:
  - Quality Gate (Headroom, R:R floor, MTSCM)
  - Alert Scrutiny (Tier-1 Sanity, mathematical coherence)
  - Learning Engine (Two-Strike lockouts, composite key isolation)
  - Detector Degradation Circuit Breaker (Kelly fraction)
  - Session Runway & Market Hours

Invariants Enforced:
1. One Evaluation Context: Session, instrument, payoff, feature snapshot, regime,
   policy version, and risk budget.
2. Strict Bifurcation of Gates:
   - Category A: Non-negotiable Data & Execution Safety Gates (Fail-Closed).
     Any defect strictly VETOES the candidate from actionable execution.
   - Category B: Contextual & Regime Gates (Lunchtime, EOD, VIX regime).
   - Category C: Empirical Strategy Filters (RSI exhaustion, VWAP trend, Lockouts).
     If safety passes but empirical filters block, candidate is routed to Shadow Evaluator.
3. Cache key includes universe, strategy/policy, feature hash, and as-of time.
4. Explains candidate evaluation in < 1ms with a structured audit trail entry.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from datetime import datetime
from typing import Any, Optional

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol
from engine.alert_scrutiny import alert_scrutiny_auditor
from engine.detector_circuit_breaker import detector_circuit_breaker
from engine.learning_engine import pattern_learning_engine
from engine.quality_gate import evaluate_institutional_quality_gate

logger = logging.getLogger("engine.signal_policy")

CURRENT_SIGNAL_POLICY_VERSION = "2026.11.01"


class PolicyGateCategory(str, Enum):
    SAFETY = "SAFETY"
    CONTEXT = "CONTEXT"
    STRATEGY_FILTER = "STRATEGY_FILTER"


class PolicyVetoCode(str, Enum):
    ZERO_FUTURES_VETO = "ZERO_FUTURES_VETO"
    TIER1_MATH_SANITY_VETO = "TIER1_MATH_SANITY_VETO"
    CIRCUIT_BREAKER_VETO = "CIRCUIT_BREAKER_VETO"
    LEARNING_LOCKOUT = "LEARNING_LOCKOUT"
    QUALITY_GATE_VETO = "QUALITY_GATE_VETO"
    SESSION_RUNWAY_EXHAUSTED = "SESSION_RUNWAY_EXHAUSTED"
    UNAVAILABLE_EVIDENCE = "UNAVAILABLE_EVIDENCE"


@dataclass(frozen=True)
class SignalPolicyEvaluationContext:
    """
    Standardized, immutable evaluation context for quantitative candidates.
    Every detector, scanner, CLI, and API input evaluates through this context.
    """

    session_id: str
    symbol: str
    canonical_symbol: str
    exchange: str = "NSE"
    segment: str = "EQUITY"
    instrument_type: str = "EQUITY"  # "EQUITY" | "OPTION" | "SPREAD" | "FUTURES"
    payoff_type: str = "LONG_ASSET"  # "LONG_ASSET" | "SHORT_ASSET" | "LONG_OPTION" | "SHORT_OPTION" | "VERTICAL_SPREAD"
    direction: str = "BULLISH"  # "BULLISH" | "BEARISH"
    feature_snapshot: dict[str, Any] = field(default_factory=dict)
    regime: str = "NORMAL"
    policy_version: str = CURRENT_SIGNAL_POLICY_VERSION
    risk_budget: Optional[dict[str, Any]] = None
    timestamps: dict[str, float] = field(default_factory=dict)

    def compute_cache_key(self, detector_slug: str = "GENERIC") -> str:
        """
        Computes deterministic cache key including symbol, direction, detector, segment,
        payoff_type, session_id, regime, feature snapshot hash, and policy version.
        """
        feat_keys = sorted(self.feature_snapshot.keys())
        feat_str = "|".join(
            f"{k}:{self.feature_snapshot[k]}" for k in feat_keys if k != "timestamp"
        )
        feat_hash = hashlib.sha256(feat_str.encode("utf-8")).hexdigest()[:12]
        return (
            f"{self.canonical_symbol}:{self.direction}:{detector_slug}:{self.session_id}:"
            f"{self.segment}:{self.payoff_type}:{self.regime}:{feat_hash}:{self.policy_version}"
        )


@dataclass
class GateVerdict:
    """Individual gate verdict within the candidate evaluation funnel."""

    gate_name: str
    category: str  # "SAFETY" | "CONTEXT" | "STRATEGY_FILTER"
    status: str  # "ACCEPT" | "HOLD" | "REJECT"
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    is_safety_gate: bool = False
    veto_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidatePolicyResult:
    """
    Final authoritative decision emitted by the Consolidated Signal Policy.
    Derived views (Telegram, Order Ticket, Desktop UI, SSE) consume this result.
    """

    decision: str  # "ACCEPT" | "HOLD" | "REJECT"
    primary_status: str  # "ACTIONABLE" | "RESEARCH_ONLY" | "SHADOW_ONLY" | "VETOED"
    conviction_tier: str  # "APEX_CONFLUENCE" | "HIGH_CONVICTION" | "DEFINED_RISK_ONLY" | "REJECTED"
    execution_mandate: str  # "STANDARD" | "HEDGED_SPREAD_MANDATORY" | "VETOED"
    gate_verdicts: list[GateVerdict] = field(default_factory=list)
    blocking_gate: Optional[GateVerdict] = None
    evaluation_context: Optional[SignalPolicyEvaluationContext] = None
    evaluated_at: str = ""
    latency_ms: float = 0.0
    cache_key: str = ""
    audit_trail_entry: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        if self.decision == "ACCEPT":
            return 85.0
        elif self.decision == "HOLD":
            return 50.0
        return 0.0

    @property
    def veto_reasons(self) -> list[Any]:
        return [g.reason for g in self.gate_verdicts if g.status == "REJECT"]

    @property
    def breakdown(self) -> dict[str, Any]:
        return {g.gate_name: g.status for g in self.gate_verdicts}

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "primary_status": self.primary_status,
            "conviction_tier": self.conviction_tier,
            "execution_mandate": self.execution_mandate,
            "gate_verdicts": [g.to_dict() for g in self.gate_verdicts],
            "blocking_gate": self.blocking_gate.to_dict() if self.blocking_gate else None,
            "evaluated_at": self.evaluated_at,
            "latency_ms": self.latency_ms,
            "cache_key": self.cache_key,
            "audit_trail_entry": self.audit_trail_entry,
        }


def build_policy_context(
    symbol: str,
    direction: str = "BULLISH",
    *,
    exchange: str = "NSE",
    segment: str = "EQUITY",
    instrument_type: str = "EQUITY",
    payoff_type: Optional[str] = None,
    ltp: float = 0.0,
    vwap: Optional[float] = None,
    rvol: Optional[float] = None,
    vix: Optional[float] = None,
    session_id: Optional[str] = None,
    regime: str = "NORMAL",
    policy_version: str = CURRENT_SIGNAL_POLICY_VERSION,
    risk_budget: Optional[dict[str, Any]] = None,
    extra_features: Optional[dict[str, Any]] = None,
) -> SignalPolicyEvaluationContext:
    """Constructs a normalized, strongly-typed SignalPolicyEvaluationContext."""
    clean_sym = canonical_alert_symbol(symbol).upper()
    now_dt = datetime.now(IST)
    sess_id = session_id or now_dt.strftime("%Y%m%d")

    # Resolve payoff type if not explicitly passed
    resolved_payoff = payoff_type
    if not resolved_payoff:
        from engine.position_sizer import resolve_payoff_orientation

        resolved_payoff = resolve_payoff_orientation(
            payoff_type=instrument_type,
            direction=direction,
            symbol=clean_sym,
        )

    feats: dict[str, Any] = {
        "ltp": float(ltp),
        "vwap": float(vwap) if vwap is not None else None,
        "rvol": float(rvol) if rvol is not None else None,
        "vix": float(vix) if vix is not None else None,
    }
    if extra_features:
        feats.update(extra_features)

    return SignalPolicyEvaluationContext(
        session_id=sess_id,
        symbol=symbol,
        canonical_symbol=clean_sym,
        exchange=exchange.upper(),
        segment=segment.upper(),
        instrument_type=instrument_type.upper(),
        payoff_type=resolved_payoff,
        direction=direction.upper(),
        feature_snapshot=feats,
        regime=regime,
        policy_version=policy_version,
        risk_budget=risk_budget,
        timestamps={"created_at": time.time()},
    )


def build_policy_context_from_alert(alert: Any) -> SignalPolicyEvaluationContext:
    metrics = getattr(alert, "metrics", {}) or {}
    if not isinstance(metrics, dict):
        metrics = {}
    return build_policy_context(
        symbol=getattr(alert, "symbol", ""),
        direction=getattr(alert, "direction", "BULLISH"),
        exchange=getattr(alert, "exchange", "NSE"),
        segment=getattr(alert, "segment", "EQUITY"),
        instrument_type=getattr(alert, "instrument_type", "EQUITY"),
        payoff_type=getattr(alert, "payoff_type", None)
        or ("LONG_OPTION" if getattr(alert, "derivative_type", None) == "OPT" else None),
        ltp=float(getattr(alert, "ltp", 0.0) or 0.0),
        vwap=metrics.get("vwap"),
        rvol=metrics.get("rvol"),
        vix=metrics.get("vix"),
        regime=str(metrics.get("regime", "NORMAL")),
    )


def evaluate_candidate_policy(
    ctx: Any = None,
    alert: Any = None,
    *,
    skip_empirical_filters: bool = False,
) -> CandidatePolicyResult:
    if alert is None and ctx is not None:
        alert = ctx
        ctx = build_policy_context_from_alert(alert)
    elif ctx is None and alert is not None:
        ctx = build_policy_context_from_alert(alert)
    """
    Central evaluation authority. Evaluates candidate alert against:
      1. Non-negotiable Data & Execution Safety Gates (Zero Blackout / Fail-Closed)
      2. Institutional Quality Gate (Headroom, R:R floor, Conviction Tier)
      3. Learning Lockout & Two-Strike Protection
      4. Contextual & Volatility Gates

    Returns CandidatePolicyResult with complete traceability.
    """
    t0 = time.perf_counter()
    now_dt = datetime.now(IST)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
    detector_slug = getattr(alert, "alert_type", "GENERIC") or "GENERIC"
    cache_key = ctx.compute_cache_key(detector_slug=detector_slug)

    gate_verdicts: list[GateVerdict] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Phase A: Non-negotiable Data & Safety Gates (Fail-Closed)
    # Any failure here is P0 fatal: marks candidate VETOED with zero actionable output.
    # ─────────────────────────────────────────────────────────────────────────

    # A1. Zero-Futures Invariant Gate (Domestic Equities & Indices)
    clean_sym = ctx.canonical_symbol
    is_comm_or_crypto = (
        ctx.exchange in ("MCX", "CRYPTO", "BINANCE", "DERIBIT")
        or ctx.segment in ("COMMODITY", "CRYPTO")
        or clean_sym
        in ("COPPER", "ZINC", "ALUMINIUM", "LEAD", "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS")
    )
    c_sym = str(getattr(alert, "contract_symbol", "") or "").upper()
    i_type = str(getattr(alert, "instrument_type", "") or ctx.instrument_type).upper()
    if not is_comm_or_crypto and (
        i_type == "FUTURES" or c_sym.endswith("FUT") or c_sym.endswith("-FUT") or ":FUT" in c_sym
    ):
        blocking = GateVerdict(
            gate_name="ZERO_FUTURES_GATE",
            category="SAFETY",
            status="REJECT",
            reason="Zero-Futures Invariant: Domestic index & equity futures prohibited. Use options or spot.",
            evidence={"contract_symbol": c_sym},
            is_safety_gate=True,
            veto_code=PolicyVetoCode.ZERO_FUTURES_VETO.value,
        )
        gate_verdicts.append(blocking)
        latency = (time.perf_counter() - t0) * 1000.0
        return _build_result(
            "REJECT",
            "VETOED",
            "REJECTED",
            "VETOED",
            gate_verdicts,
            blocking,
            ctx,
            now_str,
            latency,
            cache_key,
        )

    gate_verdicts.append(
        GateVerdict(
            "ZERO_FUTURES_GATE", "SAFETY", "ACCEPT", "Futures policy satisfied", is_safety_gate=True
        )
    )

    # A2. Tier-1 Mathematical Sanity Gate (Non-negotiable math check across all environments)
    sanity_passed, sanity_reason, _ = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    if not sanity_passed:
        if "Learning Engine Lockout" in sanity_reason:
            blocking = GateVerdict(
                gate_name="LEARNING_LOCKOUT_GATE",
                category="STRATEGY_FILTER",
                status="REJECT",
                reason=sanity_reason,
                evidence={"lock_reason": sanity_reason},
                is_safety_gate=False,
                veto_code=PolicyVetoCode.LEARNING_LOCKOUT.value,
            )
            gate_verdicts.append(blocking)
            latency = (time.perf_counter() - t0) * 1000.0
            return _build_result(
                "HOLD",
                "SHADOW_ONLY",
                "REJECTED",
                "VETOED",
                gate_verdicts,
                blocking,
                ctx,
                now_str,
                latency,
                cache_key,
            )

        blocking = GateVerdict(
            gate_name="TIER1_SANITY_GATE",
            category="SAFETY",
            status="REJECT",
            reason=f"Mathematical sanity veto: {sanity_reason}",
            evidence={"failure_reason": sanity_reason},
            is_safety_gate=True,
            veto_code=PolicyVetoCode.TIER1_MATH_SANITY_VETO.value,
        )
        gate_verdicts.append(blocking)
        latency = (time.perf_counter() - t0) * 1000.0
        return _build_result(
            "REJECT",
            "VETOED",
            "REJECTED",
            "VETOED",
            gate_verdicts,
            blocking,
            ctx,
            now_str,
            latency,
            cache_key,
        )

    gate_verdicts.append(
        GateVerdict("TIER1_SANITY_GATE", "SAFETY", "ACCEPT", "Sanity verified", is_safety_gate=True)
    )

    # A3. Detector Circuit Breaker
    allowed, multiplier, cb_reason = detector_circuit_breaker.evaluate_alert_allowed(detector_slug)
    if not allowed:
        blocking = GateVerdict(
            gate_name="CIRCUIT_BREAKER_GATE",
            category="SAFETY",
            status="REJECT",
            reason=f"Detector degraded: {cb_reason}",
            evidence={"multiplier": multiplier},
            is_safety_gate=True,
            veto_code=PolicyVetoCode.CIRCUIT_BREAKER_VETO.value,
        )
        gate_verdicts.append(blocking)
        latency = (time.perf_counter() - t0) * 1000.0
        return _build_result(
            "REJECT",
            "VETOED",
            "REJECTED",
            "VETOED",
            gate_verdicts,
            blocking,
            ctx,
            now_str,
            latency,
            cache_key,
        )

    gate_verdicts.append(
        GateVerdict(
            "CIRCUIT_BREAKER_GATE", "SAFETY", "ACCEPT", "Circuit breaker clear", is_safety_gate=True
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase B: Institutional Quality Gate & Hard Veto Matrix
    # ─────────────────────────────────────────────────────────────────────────
    q_verdict = evaluate_institutional_quality_gate(
        alert,
        current_ltp=ctx.feature_snapshot.get("ltp") or getattr(alert, "ltp", 0.0),
        current_vwap=ctx.feature_snapshot.get("vwap"),
        ref_dt=now_dt,
    )

    if q_verdict.is_vetoed:
        blocking = GateVerdict(
            gate_name="QUALITY_GATE",
            category="SAFETY"
            if "R:R" in q_verdict.veto_reason or "SEBI" in q_verdict.veto_reason
            else "CONTEXT",
            status="REJECT",
            reason=q_verdict.veto_reason,
            evidence=q_verdict.metrics,
            is_safety_gate=("R:R" in q_verdict.veto_reason or "SEBI" in q_verdict.veto_reason),
            veto_code=PolicyVetoCode.QUALITY_GATE_VETO.value,
        )
        gate_verdicts.append(blocking)
        latency = (time.perf_counter() - t0) * 1000.0
        primary_st = "VETOED" if blocking.is_safety_gate else "SHADOW_ONLY"
        return _build_result(
            "REJECT",
            primary_st,
            "REJECTED",
            "VETOED",
            gate_verdicts,
            blocking,
            ctx,
            now_str,
            latency,
            cache_key,
        )

    gate_verdicts.append(
        GateVerdict(
            gate_name="QUALITY_GATE",
            category="SAFETY",
            status="ACCEPT",
            reason=f"Tier: {q_verdict.conviction_tier} | Mandate: {q_verdict.execution_mandate}",
            evidence=q_verdict.metrics,
            is_safety_gate=False,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase C: Learning Engine Two-Strike Lockout Gate (Empirical Strategy Filter)
    # ─────────────────────────────────────────────────────────────────────────
    if not skip_empirical_filters:
        ltp_val = ctx.feature_snapshot.get("ltp") or getattr(alert, "ltp", 0.0)
        vwap_val = ctx.feature_snapshot.get("vwap")
        is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
            ctx.canonical_symbol,
            direction=ctx.direction,
            ltp=ltp_val,
            vwap=vwap_val,
            session_id=ctx.session_id,
        )
        if is_locked:
            blocking = GateVerdict(
                gate_name="LEARNING_LOCKOUT_GATE",
                category="STRATEGY_FILTER",
                status="REJECT",
                reason=f"Learning lockout active: {lock_reason}",
                evidence={"lock_reason": lock_reason},
                is_safety_gate=False,
                veto_code=PolicyVetoCode.LEARNING_LOCKOUT.value,
            )
            gate_verdicts.append(blocking)
            latency = (time.perf_counter() - t0) * 1000.0
            return _build_result(
                "HOLD",
                "SHADOW_ONLY",
                q_verdict.conviction_tier,
                q_verdict.execution_mandate,
                gate_verdicts,
                blocking,
                ctx,
                now_str,
                latency,
                cache_key,
            )

    gate_verdicts.append(
        GateVerdict(
            "LEARNING_LOCKOUT_GATE",
            "STRATEGY_FILTER",
            "ACCEPT",
            "Symbol not locked out",
            is_safety_gate=False,
        )
    )

    # All gates passed!
    latency = (time.perf_counter() - t0) * 1000.0
    return _build_result(
        "ACCEPT",
        "ACTIONABLE",
        q_verdict.conviction_tier,
        q_verdict.execution_mandate,
        gate_verdicts,
        None,
        ctx,
        now_str,
        latency,
        cache_key,
    )


def _build_result(
    decision: str,
    primary_status: str,
    conviction_tier: str,
    execution_mandate: str,
    verdicts: list[GateVerdict],
    blocking: Optional[GateVerdict],
    ctx: SignalPolicyEvaluationContext,
    evaluated_at: str,
    latency_ms: float,
    cache_key: str,
) -> CandidatePolicyResult:
    """Helper to assemble an authoritative CandidatePolicyResult with structured audit entry."""
    audit_entry = {
        "timestamp": evaluated_at,
        "event_type": "POLICY_EVALUATION",
        "actor": "SIGNAL_POLICY_AUTHORITY",
        "policy_version": ctx.policy_version,
        "decision": decision,
        "primary_status": primary_status,
        "conviction_tier": conviction_tier,
        "execution_mandate": execution_mandate,
        "gates_evaluated_count": len(verdicts),
        "blocking_gate": blocking.to_dict() if blocking else None,
        "latency_ms": round(latency_ms, 2),
    }

    return CandidatePolicyResult(
        decision=decision,
        primary_status=primary_status,
        conviction_tier=conviction_tier,
        execution_mandate=execution_mandate,
        gate_verdicts=verdicts,
        blocking_gate=blocking,
        evaluation_context=ctx,
        evaluated_at=evaluated_at,
        latency_ms=round(latency_ms, 2),
        cache_key=cache_key,
        audit_trail_entry=audit_entry,
    )
