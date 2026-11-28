"""
engine/stock_fno_catalysts.py
─────────────────────────────
Stock F&O Institutional Catalyst, PEAD/SEPA Funnel, 4-Quadrant Fut-OI x Delivery%,
and MWPL Squeeze / Ban Radar.

Zero-Hallucination & As-Of Guarantees:
  1. Earnings / Macro Event Shield filters strictly via `first_seen_at <= as_of`.
  2. Delivery % / Futures OI Matrix returns explicit `UNAVAILABLE` when delivery
     or OI change inputs are missing — never synthesizes delivery spikes.
  3. MWPL utilizes authoritative `market/fno_ban.py` (never invents utilization %),
     flagging `85%-94.9%` squeeze setups and gating `>=95%` ban or `>=92%` late-day entries.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any, Optional, Sequence

from config.constants import IST
from engine.alert_identity import canonical_alert_symbol
from engine.option_resolver import is_index_symbol

logger = logging.getLogger("engine.stock_fno_catalysts")


@dataclass(frozen=True)
class EventRiskShieldResult:
    symbol: str
    as_of: str
    event_iv_crush_risk: bool
    upcoming_events: list[dict[str, Any]] = field(default_factory=list)
    recommended_structure: str = "STANDARD"  # "STANDARD" | "VERTICAL_DEBIT_SPREAD"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_event_risk_shield(
    symbol: str,
    *,
    as_of: Optional[datetime] = None,
    earnings_entries: Optional[Sequence[Any]] = None,
    macro_events: Optional[Sequence[Any]] = None,
    horizon_days: int = 2,
) -> EventRiskShieldResult:
    """Assess whether upcoming company earnings or major macro releases sit within `horizon_days`."""
    from market.earnings import filter_earnings_as_of
    from market.events import filter_events_as_of

    clean = canonical_alert_symbol(symbol).upper()
    ref_dt = as_of or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)
    ref_date = ref_dt.date()

    upcoming: list[dict[str, Any]] = []
    if earnings_entries:
        known = filter_earnings_as_of(list(earnings_entries), ref_dt)
        for e in known:
            e_sym = canonical_alert_symbol(str(getattr(e, "symbol", "") or "")).upper()
            if e_sym and e_sym != clean:
                continue
            d_raw = str(getattr(e, "result_date", "") or "")[:10]
            if not d_raw or d_raw == "TBD":
                continue
            try:
                ev_date = datetime.strptime(d_raw, "%Y-%m-%d").date()
                days_away = (ev_date - ref_date).days
                if 0 <= days_away <= max(0, int(horizon_days)):
                    upcoming.append(
                        {
                            "kind": "EARNINGS",
                            "symbol": clean,
                            "date": ev_date.isoformat(),
                            "days_away": days_away,
                            "detail": str(getattr(e, "quarter", "") or "Quarterly Results"),
                        }
                    )
            except ValueError:
                continue

    if macro_events:
        known_m = filter_events_as_of(list(macro_events), ref_dt)
        for ev in known_m:
            d_raw = str(getattr(ev, "date", "") or getattr(ev, "ex_date", "") or "")[:10]
            if not d_raw:
                continue
            try:
                ev_date = datetime.strptime(d_raw, "%Y-%m-%d").date()
                days_away = (ev_date - ref_date).days
                if 0 <= days_away <= max(0, int(horizon_days)):
                    upcoming.append(
                        {
                            "kind": "MACRO_EVENT",
                            "symbol": str(getattr(ev, "symbol", "INDIA") or "INDIA"),
                            "date": ev_date.isoformat(),
                            "days_away": days_away,
                            "detail": str(getattr(ev, "event", "") or getattr(ev, "purpose", "")),
                        }
                    )
            except ValueError:
                continue

    risk = len(upcoming) > 0
    return EventRiskShieldResult(
        symbol=clean,
        as_of=ref_dt.isoformat(),
        event_iv_crush_risk=risk,
        upcoming_events=upcoming,
        recommended_structure="VERTICAL_DEBIT_SPREAD" if risk else "STANDARD",
        reason=(
            f"EVENT_IV_CRUSH_RISK: {len(upcoming)} known catalyst(s) within {horizon_days}d"
            if risk
            else "No known imminent catalyst inside crush window"
        ),
    )


@dataclass(frozen=True)
class FutOIDeliveryMatrixResult:
    symbol: str
    status: str  # "AVAILABLE" | "UNAVAILABLE"
    quadrant: str  # INSTITUTIONAL_ACCUMULATION | FRAGILE_SHORT_COVERING | INSTITUTIONAL_DISTRIBUTION | LONG_UNWINDING | NEUTRAL | UNAVAILABLE
    price_change_pct: Optional[float] = None
    fut_oi_change_pct: Optional[float] = None
    fut_basis_bps: Optional[float] = None
    delivery_pct: Optional[float] = None
    delivery_avg_20d: Optional[float] = None
    delivery_surge_ratio: Optional[float] = None
    conviction_delta: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_fut_oi_delivery_matrix(
    symbol: str,
    *,
    price_change_pct: Optional[float],
    fut_oi_change_pct: Optional[float],
    delivery_pct: Optional[float],
    delivery_avg_20d: Optional[float] = None,
    spot_price: Optional[float] = None,
    fut_price: Optional[float] = None,
) -> FutOIDeliveryMatrixResult:
    """4-Quadrant Stock F&O positioning classifier combining Futures dOI & Cash Delivery %."""
    clean = canonical_alert_symbol(symbol).upper()
    if price_change_pct is None or fut_oi_change_pct is None or delivery_pct is None:
        return FutOIDeliveryMatrixResult(
            symbol=clean,
            status="UNAVAILABLE",
            quadrant="UNAVAILABLE",
            price_change_pct=price_change_pct,
            fut_oi_change_pct=fut_oi_change_pct,
            delivery_pct=delivery_pct,
            reason="Missing price change, Futures OI change, or real cash delivery %.",
        )

    px_c = float(price_change_pct)
    oi_c = float(fut_oi_change_pct)
    deliv = float(delivery_pct)
    avg_d = float(delivery_avg_20d) if (delivery_avg_20d and delivery_avg_20d > 0) else None
    surge = round(deliv / avg_d, 2) if avg_d else None
    basis_bps = None
    if spot_price and fut_price and spot_price > 0 and fut_price > 0:
        basis_bps = round(((fut_price - spot_price) / spot_price) * 10000.0, 1)

    high_delivery = deliv >= 50.0 or (surge is not None and surge >= 1.25)
    low_delivery = deliv < 35.0 and (surge is None or surge < 0.95)

    if px_c >= 0.4 and oi_c >= 2.0 and high_delivery:
        quad = "INSTITUTIONAL_ACCUMULATION"
        delta = 12
        reason = f"Price {px_c:+.2f}%, Fut OI {oi_c:+.1f}%, Delivery {deliv:.1f}% confirms institutional buildup."
    elif px_c >= 0.4 and oi_c <= -2.0:
        quad = "FRAGILE_SHORT_COVERING"
        delta = -4 if low_delivery else 2
        reason = f"Price {px_c:+.2f}% on Fut OI unwind ({oi_c:+.1f}%), Delivery {deliv:.1f}%."
    elif px_c <= -0.4 and oi_c >= 2.0 and high_delivery:
        quad = "INSTITUTIONAL_DISTRIBUTION"
        delta = -10
        reason = (
            f"Price {px_c:+.2f}% on short buildup (OI {oi_c:+.1f}%) + high delivery ({deliv:.1f}%)."
        )
    elif px_c <= -0.4 and oi_c <= -2.0:
        quad = "LONG_UNWINDING"
        delta = -5
        reason = f"Price {px_c:+.2f}% with Futures long liquidation (OI {oi_c:+.1f}%)."
    else:
        quad = "NEUTRAL"
        delta = 0
        reason = f"Balanced positioning (dPx={px_c:+.2f}%, dOI={oi_c:+.1f}%, Deliv={deliv:.1f}%)."

    return FutOIDeliveryMatrixResult(
        symbol=clean,
        status="AVAILABLE",
        quadrant=quad,
        price_change_pct=round(px_c, 2),
        fut_oi_change_pct=round(oi_c, 2),
        fut_basis_bps=basis_bps,
        delivery_pct=round(deliv, 2),
        delivery_avg_20d=round(avg_d, 2) if avg_d is not None else None,
        delivery_surge_ratio=surge,
        conviction_delta=delta,
        reason=reason,
    )


@dataclass(frozen=True)
class MWPLSqueezeState:
    symbol: str
    status: str  # "AVAILABLE" | "UNAVAILABLE" | "NOT_APPLICABLE"
    mwpl_pct: Optional[float]
    in_ban: bool
    regime: str  # NORMAL | PRE_BAN_SHORT_SQUEEZE | LATE_BAN_LOCK_RISK | BANNED_NO_FRESH_EXPOSURE | INDEX_EXEMPT | UNAVAILABLE
    allow_fresh_directional: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_mwpl_squeeze_state(
    symbol: str,
    *,
    mwpl_pct_override: Optional[float] = None,
    price_change_pct: Optional[float] = None,
    breaking_resistance: bool = False,
    now_dt: Optional[datetime] = None,
) -> MWPLSqueezeState:
    """Evaluate single-stock F&O MWPL ban & pre-ban short-covering squeeze state."""
    from market.fno_ban import get_mwpl_utilization, is_in_fno_ban

    clean = canonical_alert_symbol(symbol).upper()
    if is_index_symbol(clean):
        return MWPLSqueezeState(
            symbol=clean,
            status="NOT_APPLICABLE",
            mwpl_pct=None,
            in_ban=False,
            regime="INDEX_EXEMPT",
            allow_fresh_directional=True,
            reason="Index derivatives are exempt from single-stock MWPL bans.",
        )

    in_ban = is_in_fno_ban(clean)
    mwpl = mwpl_pct_override if mwpl_pct_override is not None else get_mwpl_utilization(clean)
    if mwpl is None and not in_ban:
        return MWPLSqueezeState(
            symbol=clean,
            status="UNAVAILABLE",
            mwpl_pct=None,
            in_ban=False,
            regime="UNAVAILABLE",
            allow_fresh_directional=True,
            reason="Official MWPL utilization unavailable.",
        )

    ref_dt = now_dt or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)
    late_session = ref_dt.time() >= time(14, 30)

    mwpl_val = float(mwpl) if mwpl is not None else 95.0
    if in_ban or mwpl_val >= 95.0:
        return MWPLSqueezeState(
            symbol=clean,
            status="AVAILABLE",
            mwpl_pct=round(mwpl_val, 2),
            in_ban=True,
            regime="BANNED_NO_FRESH_EXPOSURE",
            allow_fresh_directional=False,
            reason=f"{clean} in F&O Ban (MWPL {mwpl_val:.1f}% >= 95%); fresh exposure blocked.",
        )

    if late_session and mwpl_val >= 92.0:
        return MWPLSqueezeState(
            symbol=clean,
            status="AVAILABLE",
            mwpl_pct=round(mwpl_val, 2),
            in_ban=False,
            regime="LATE_BAN_LOCK_RISK",
            allow_fresh_directional=False,
            reason=f"{clean} MWPL at {mwpl_val:.1f}% after 14:30 IST — imminent NSE ban lock risk.",
        )

    is_rising = (
        price_change_pct is not None and float(price_change_pct) >= 0.75
    ) or breaking_resistance
    if 85.0 <= mwpl_val < 95.0 and is_rising:
        return MWPLSqueezeState(
            symbol=clean,
            status="AVAILABLE",
            mwpl_pct=round(mwpl_val, 2),
            in_ban=False,
            regime="PRE_BAN_SHORT_SQUEEZE",
            allow_fresh_directional=True,
            reason=f"{clean} MWPL squeeze window ({mwpl_val:.1f}%) with upward breakout thrust.",
        )

    return MWPLSqueezeState(
        symbol=clean,
        status="AVAILABLE",
        mwpl_pct=round(mwpl_val, 2),
        in_ban=False,
        regime="NORMAL",
        allow_fresh_directional=True,
        reason=f"MWPL utilization healthy ({mwpl_val:.1f}%).",
    )


@dataclass(frozen=True)
class PEADSEPACandidateScore:
    symbol: str
    qualified: bool
    score: float
    sepa_qualified: bool
    forensic_verdict: str
    pead_active: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_pead_sepa_fno_candidate(
    symbol: str,
    *,
    fundamental: Any = None,
    forensic_verdict: Optional[str] = None,
    post_earnings_surprise: Optional[str] = None,
    tod_rvol: Optional[float] = None,
    above_avwap: Optional[bool] = None,
) -> PEADSEPACandidateScore:
    """Evaluate a Stock F&O candidate across Minervini SEPA growth, forensics & PEAD drift."""
    clean = canonical_alert_symbol(symbol).upper()
    reasons: list[str] = []
    score = 0.0

    sepa_ok = bool(getattr(fundamental, "sepa_qualified", False)) if fundamental else False
    eps_q1 = getattr(fundamental, "eps_q1_growth", None) if fundamental else None
    eps_acc = getattr(fundamental, "eps_acceleration", None) if fundamental else None
    rev_q1 = getattr(fundamental, "revenue_q1_growth", None) if fundamental else None

    if sepa_ok:
        score += 35.0
        reasons.append("SEPA qualified (YoY EPS acceleration + sales growth)")
    else:
        if eps_q1 is not None and float(eps_q1) >= 20.0:
            score += 15.0
            reasons.append(f"EPS YoY +{float(eps_q1):.1f}%")
        if eps_acc is not None and float(eps_acc) > 0:
            score += 10.0
            reasons.append(f"EPS accelerating +{float(eps_acc):.1f}%")
        if rev_q1 is not None and float(rev_q1) >= 15.0:
            score += 10.0
            reasons.append(f"Revenue YoY +{float(rev_q1):.1f}%")

    verdict = str(forensic_verdict or "UNKNOWN").upper()
    if verdict in ("HIGH_RISK", "MANIPULATION_RISK", "DISTRESS", "FAIL"):
        return PEADSEPACandidateScore(
            symbol=clean,
            qualified=False,
            score=0.0,
            sepa_qualified=sepa_ok,
            forensic_verdict=verdict,
            pead_active=False,
            reasons=[f"Disqualified by forensic audit ({verdict})"],
        )
    if verdict in ("CLEAN", "PASS", "LOW_RISK", "SAFE"):
        score += 15.0
        reasons.append(f"Forensic audit {verdict}")

    surprise_u = str(post_earnings_surprise or "").upper()
    rvol_ok = tod_rvol is not None and float(tod_rvol) >= 1.8
    pead_active = surprise_u == "BEAT" and rvol_ok and (above_avwap is not False)
    if pead_active:
        score += 30.0
        reasons.append(f"PEAD active (BEAT + RVOL {float(tod_rvol):.2f}x > AVWAP)")
    elif surprise_u == "BEAT":
        score += 12.0
        reasons.append("Earnings BEAT")

    if above_avwap is True:
        score += 10.0
        reasons.append("Holding above Anchored VWAP")

    return PEADSEPACandidateScore(
        symbol=clean,
        qualified=score >= 50.0,
        score=round(min(100.0, score), 1),
        sepa_qualified=sepa_ok,
        forensic_verdict=verdict,
        pead_active=pead_active,
        reasons=reasons,
    )


def build_fno_catalyst_watchlist(
    candidates: Sequence[dict[str, Any]],
    *,
    as_of: Optional[datetime] = None,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Rank Stock F&O candidates combining SEPA/PEAD, 4-Quadrant OI/Delivery, Events & MWPL."""
    from config.discovery_policy import allows_context_symbol, get_discovery_policy

    ref_dt = as_of or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)

    strict_fno = get_discovery_policy().fno_only
    ranked: list[dict[str, Any]] = []

    for item in candidates:
        sym = canonical_alert_symbol(str(item.get("symbol", "") or "")).upper()
        if not sym:
            continue
        if strict_fno and not allows_context_symbol(f"NSE:{sym}"):
            continue

        pead = score_pead_sepa_fno_candidate(
            sym,
            fundamental=item.get("fundamental"),
            forensic_verdict=item.get("forensic_verdict"),
            post_earnings_surprise=item.get("post_earnings_surprise"),
            tod_rvol=item.get("tod_rvol"),
            above_avwap=item.get("above_avwap"),
        )
        matrix = classify_fut_oi_delivery_matrix(
            sym,
            price_change_pct=item.get("price_change_pct"),
            fut_oi_change_pct=item.get("fut_oi_change_pct"),
            delivery_pct=item.get("delivery_pct"),
            delivery_avg_20d=item.get("delivery_avg_20d"),
            spot_price=item.get("spot_price"),
            fut_price=item.get("fut_price"),
        )
        mwpl = evaluate_mwpl_squeeze_state(
            sym,
            mwpl_pct_override=item.get("mwpl_pct"),
            price_change_pct=item.get("price_change_pct"),
            breaking_resistance=bool(item.get("breaking_resistance")),
            now_dt=ref_dt,
        )
        shield = assess_event_risk_shield(
            sym,
            as_of=ref_dt,
            earnings_entries=item.get("earnings_entries"),
            macro_events=item.get("macro_events"),
        )

        if not mwpl.allow_fresh_directional:
            continue

        composite = (
            pead.score
            + matrix.conviction_delta
            + (15.0 if mwpl.regime == "PRE_BAN_SHORT_SQUEEZE" else 0.0)
        )
        ranked.append(
            {
                "symbol": sym,
                "composite_score": round(max(0.0, min(100.0, composite)), 1),
                "pead_sepa": pead.to_dict(),
                "fut_oi_delivery": matrix.to_dict(),
                "mwpl_state": mwpl.to_dict(),
                "event_shield": shield.to_dict(),
                "recommended_structure": (
                    "VERTICAL_DEBIT_SPREAD" if shield.event_iv_crush_risk else "STANDARD"
                ),
            }
        )

    ranked.sort(key=lambda r: (-r["composite_score"], r["symbol"]))
    return ranked[: max(1, int(top_n))]
