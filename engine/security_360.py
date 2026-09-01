"""
engine/security_360.py
──────────────────────
P2-B Security 360 Institutional Decision Dossier.

Synthesizes a comprehensive, multi-dimensional equity intelligence report:
1. Canonical instrument identity & exchange trading session state
2. Fundamental valuation & margin of safety (real forensic audit; DCF pending)
3. Forensic accounting flags (Beneish M-Score, Altman Z''-Score, Promoter Pledging)
4. Technical price action & SMC liquidity structure
5. Methodology lenses (Minervini SEPA, Buffett Moat, Taleb Convexity, Wyckoff VSA)
6. Defensible Decision Summary: Primary Thesis, Counter-Thesis, Invalidation Level,
   Planned Risk R-multiple, and Action Eligibility envelope.

Truthfulness guarantees
───────────────────────
- If the spot price cannot be determined from a live quote, the dossier is returned
  with _status='UNAVAILABLE', decision=None, and no trade levels.  The ₹2,500
  hardcoded fallback is permanently removed.
- fair_value and valuation_status are derived from real forensic data where
  possible; otherwise explicitly marked UNAVAILABLE.
- forensic_status is populated by a real call to analysis.forensic — never
  hardcoded to "CLEAN".
- Methodology lenses are left empty until real per-lens computation is wired.
  Returning an empty list is explicitly honest; returning four hardcoded BULLISH
  verdicts with fixed rationale strings is fabrication.
- Action eligibility is NOT_ELIGIBLE whenever lenses are empty.
- decision is None whenever lenses are empty or price is unavailable.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from market.instruments import (
    resolve_canonical_instrument,
    get_market_session_state,
    get_current_ist_time,
)
from engine.model_governance import ActionEligibility

# Top-level imports so tests can patch these via `engine.security_360.<name>`
try:
    from market.quotes import get_quote
except ImportError:  # pragma: no cover — market module unavailable in some test envs
    get_quote = None  # type: ignore[assignment]

try:
    from analysis.forensic import audit_company_forensics
except ImportError:  # pragma: no cover
    audit_company_forensics = None  # type: ignore[assignment]


@dataclass
class MethodologyLens:
    lens_id: str
    name: str
    verdict: str  # "BULLISH" | "NEUTRAL" | "BEARISH" | "UNAVAILABLE"
    confidence_pct: float
    rationale: str
    key_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionSummary:
    action_eligibility: ActionEligibility
    primary_thesis: str
    counter_thesis: str
    invalidation_level: float
    max_planned_loss: float
    target_1: float
    target_2: float
    risk_reward_ratio: float
    suggested_position_sizing_pct: float


@dataclass
class Security360Dossier:
    symbol: str
    canonical_symbol: str
    exchange: str
    segment: str
    lot_size: int
    tick_size: float
    session_state: str
    current_price: float
    valuation_fair_value: Optional[float]
    valuation_status: str  # "UNDERVALUED" | "FAIR_VALUE" | "OVERVALUED" | "UNAVAILABLE"
    forensic_status: str  # "CLEAN" | "CAUTION" | "FLAGGED" | "UNAVAILABLE"
    market_structure_trend: (
        str  # "BULLISH_EXPANSION" | "CONSOLIDATION" | "BEARISH_CONTRACTION" | "UNAVAILABLE"
    )
    methodology_lenses: list[MethodologyLens] = field(default_factory=list)
    decision: Optional[DecisionSummary] = None
    _status: str = "READY"
    _source_name: str = "CHANAKYA_SECURITY_360_ENGINE"
    _as_of: str = ""
    _unavailable_reason: Optional[str] = None  # Set when _status == "UNAVAILABLE"

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        if self.decision:
            elig = self.decision.action_eligibility
            res["decision"]["action_eligibility"] = (
                elig.value if hasattr(elig, "value") else str(elig)
            )
        return res


def _unavailable_dossier(
    symbol: str,
    canon: Any,
    session_state: str,
    as_of: str,
    reason: str,
) -> Security360Dossier:
    """
    Return an honest UNAVAILABLE dossier when required inputs are missing.

    No trade levels, no stop-loss, no targets, no recommendations.
    The caller should surface the reason to the user.
    """
    return Security360Dossier(
        symbol=canon.symbol,
        canonical_symbol=canon.instrument_id,
        exchange=canon.exchange,
        segment=canon.segment,
        lot_size=canon.lot_size,
        tick_size=canon.tick_size,
        session_state=session_state,
        current_price=0.0,
        valuation_fair_value=None,
        valuation_status="UNAVAILABLE",
        forensic_status="UNAVAILABLE",
        market_structure_trend="UNAVAILABLE",
        methodology_lenses=[],
        decision=None,
        _status="UNAVAILABLE",
        _source_name="CHANAKYA_SECURITY_360_ENGINE",
        _as_of=as_of,
        _unavailable_reason=reason,
    )


def build_security_360_dossier(
    symbol: str, current_price: Optional[float] = None
) -> Security360Dossier:
    """
    Builds a complete, institutional 360-degree security dossier with transparent provenance.

    Args:
        symbol: Ticker symbol or query (e.g. 'RELIANCE', 'NSE:INFY').
        current_price: Optional price override. If None, fetched from live quotes.
                       If the quote fetch also fails, returns an UNAVAILABLE dossier.

    Returns:
        Security360Dossier structured record.
        _status == "UNAVAILABLE" means required data was missing; decision is always
        None in that case and no trade levels are present.
    """
    canon = resolve_canonical_instrument(symbol)
    session = get_market_session_state(canon.exchange)
    as_of = get_current_ist_time().strftime("%Y-%m-%dT%H:%M:%S+05:30")

    # ── Path A: resolve spot price ─────────────────────────────────────────────
    # If current_price is not supplied, attempt a live quote fetch.
    # On failure (network error, symbol not found, zero price) → UNAVAILABLE.
    # The ₹2,500 hardcoded fallback is permanently removed.
    price = current_price
    if price is None or price <= 0:
        try:
            _get_quote = get_quote
            if _get_quote is None:
                raise ImportError("market.quotes.get_quote not available")
            q = _get_quote(canon.symbol)
            fetched = float(q.get("price", 0.0)) if isinstance(q, dict) else 0.0
            if fetched <= 0:
                raise ValueError(f"Quote returned non-positive price: {fetched}")
            price = fetched
        except Exception as quote_exc:
            return _unavailable_dossier(
                symbol=symbol,
                canon=canon,
                session_state=session.session_state,
                as_of=as_of,
                reason=(
                    f"Live quote unavailable for '{canon.symbol}': {quote_exc}. "
                    "Cannot produce investment intelligence without a real price."
                ),
            )

    # ── Path B: real data with honest UNAVAILABLE markers ─────────────────────

    # Valuation: DCF fair value computation is not yet wired.
    # Mark UNAVAILABLE rather than inventing price × 1.15.
    valuation_fair_value: Optional[float] = None
    valuation_status = "UNAVAILABLE"

    # Forensic status: call the real forensic audit module.
    # Do NOT hardcode "CLEAN".
    forensic_status = "UNAVAILABLE"
    try:
        _audit = audit_company_forensics
        if _audit is None:
            raise ImportError("analysis.forensic not available")
        forensic_result = _audit(canon.symbol)
        # audit_company_forensics returns a ForensicAuditResult with overall_flag
        flag = getattr(forensic_result, "overall_flag", None)
        if flag is not None:
            forensic_status = str(flag)
    except Exception:
        forensic_status = "UNAVAILABLE"

    # Methodology lenses: real per-lens computation is not yet wired into this
    # module.  Return an empty list rather than four hardcoded BULLISH verdicts.
    # When lenses are wired, populate this list with real MethodologyLens objects.
    lenses: list[MethodologyLens] = []

    # Decision summary: omit when lenses are empty — no defensible thesis exists.
    # Hardcoded stop-loss at 3.5% / fixed R-multiples are removed.
    decision = None

    return Security360Dossier(
        symbol=canon.symbol,
        canonical_symbol=canon.instrument_id,
        exchange=canon.exchange,
        segment=canon.segment,
        lot_size=canon.lot_size,
        tick_size=canon.tick_size,
        session_state=session.session_state,
        current_price=price,
        valuation_fair_value=valuation_fair_value,
        valuation_status=valuation_status,
        forensic_status=forensic_status,
        market_structure_trend="UNAVAILABLE",
        methodology_lenses=lenses,
        decision=decision,
        _status="PARTIAL",  # Price available but lenses not yet computed
        _source_name="CHANAKYA_SECURITY_360_ENGINE",
        _as_of=as_of,
        _unavailable_reason=(
            "Methodology lenses are pending real computation. "
            "Price and forensic status are available."
        )
        if not lenses
        else None,
    )
