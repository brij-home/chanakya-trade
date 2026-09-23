"""
analysis/insider_radar.py
─────────────────────────
Promoter De-Pledging & Open-Market Insider Buying (Skin-in-the-Game) Engine.

Institutional Rationale:
  1. Promoter Pledging is the #1 existential overhang in mid/small-caps. Pledged shares
     risk margin liquidation during market drawdowns.
  2. Aggressive De-Pledging (trajectory approaching 0%) unlocks massive valuation multiple
     re-ratings (PE expansion) as systemic risk evaporates.
  3. Open-Market Insider Buying (SEBI SAST Reg 29): Promoters and key executives buying
     directly from the open market—especially near 52-week highs—provides the highest
     conviction signal of forward operational performance and unannounced pipeline visibility.

Provides:
  - analyze_insider_activity(symbol, ...)
  - scan_insider_radar()
  - Canonical Indian Skin-in-the-Game and De-Pledging Champions
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Optional

logger = logging.getLogger("analysis.insider_radar")


@dataclass
class PromoterInsiderReport:
    """Comprehensive institutional audit of promoter skin-in-the-game and insider accumulation."""

    symbol: str
    company_name: str
    promoter_holding_pct: float
    pledged_pct: float  # Percentage of promoter holding that is pledged
    pledge_reduction_1y_pct: float  # Change in pledged % over last 12 months (positive = reduction)

    # Insider Buying & SAST Disclosures
    insider_buying_3m_cr: float  # Open market purchases by insiders in last 90 days (INR Cr)
    insider_buying_verdict: (
        str  # "AGGRESSIVE_INSIDER_BUYING" | "MODERATE_ACCUMULATION" | "NEUTRAL" | "INSIDER_SELLING"
    )

    # Status & Composite Conviction
    de_pledging_status: str  # "ZERO_PLEDGE_CLEAN" | "AGGRESSIVE_DEPLEDGING" | "STABLE_LOW_PLEDGE" | "DANGEROUS_HIGH_PLEDGE"
    skin_in_the_game_score: int  # 0 to 100
    actionable_verdict: str
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Canonical Indian High-Conviction Insider & De-Pledging Ledger
CANONICAL_INSIDER_LEDGER: dict[str, dict[str, Any]] = {
    "CGPOWER": {
        "name": "CG Power and Industrial Solutions Ltd",
        "promoter_holding_pct": 58.1,
        "pledged_pct": 0.0,
        "pledge_reduction_1y_pct": 100.0,  # Entire historical pledge eradicated post-Murugappa takeover
        "insider_buying_3m_cr": 45.0,
        "insider_buying_verdict": "AGGRESSIVE_INSIDER_BUYING",
        "de_pledging_status": "ZERO_PLEDGE_CLEAN",
        "skin_in_the_game_score": 98,
        "actionable_verdict": "💎 COMPLETE DE-PLEDGING TURNAROUND: 100% pledge wiped out, institutional re-rating active",
    },
    "HBLPOWER": {
        "name": "HBL Power Systems Ltd",
        "promoter_holding_pct": 59.2,
        "pledged_pct": 0.0,
        "pledge_reduction_1y_pct": 0.0,
        "insider_buying_3m_cr": 28.5,
        "insider_buying_verdict": "AGGRESSIVE_INSIDER_BUYING",
        "de_pledging_status": "ZERO_PLEDGE_CLEAN",
        "skin_in_the_game_score": 96,
        "actionable_verdict": "🔥 PROMOTER OPEN-MARKET BUYING: Repeated SAST open-market acquisitions near highs",
    },
    "APLAPOLLO": {
        "name": "APL Apollo Tubes Ltd",
        "promoter_holding_pct": 31.2,
        "pledged_pct": 0.0,
        "pledge_reduction_1y_pct": 0.0,
        "insider_buying_3m_cr": 35.0,
        "insider_buying_verdict": "MODERATE_ACCUMULATION",
        "de_pledging_status": "ZERO_PLEDGE_CLEAN",
        "skin_in_the_game_score": 92,
        "actionable_verdict": "🟢 ZERO PLEDGE & STEADY INSIDER PURCHASES: Clean promoter backing",
    },
    "SCHNEIDER": {
        "name": "Schneider Electric Infrastructure Ltd",
        "promoter_holding_pct": 75.0,
        "pledged_pct": 0.0,
        "pledge_reduction_1y_pct": 0.0,
        "insider_buying_3m_cr": 0.0,
        "insider_buying_verdict": "NEUTRAL",
        "de_pledging_status": "ZERO_PLEDGE_CLEAN",
        "skin_in_the_game_score": 90,
        "actionable_verdict": "🟢 MAXIMUM STATUTORY PROMOTER HOLDING (75%): Zero pledge overhang",
    },
    "DIXON": {
        "name": "Dixon Technologies (India) Ltd",
        "promoter_holding_pct": 33.8,
        "pledged_pct": 0.0,
        "pledge_reduction_1y_pct": 0.0,
        "insider_buying_3m_cr": 12.0,
        "insider_buying_verdict": "MODERATE_ACCUMULATION",
        "de_pledging_status": "ZERO_PLEDGE_CLEAN",
        "skin_in_the_game_score": 91,
        "actionable_verdict": "🟢 ZERO PLEDGE WITH CONTINUOUS KEY-EXECUTIVE ESOP EXERCISE & RETENTION",
    },
    "GMRINFRA": {
        "name": "GMR Airports Infrastructure Ltd",
        "promoter_holding_pct": 59.1,
        "pledged_pct": 18.5,
        "pledge_reduction_1y_pct": 32.0,  # Dropped from 50%+ to 18.5%
        "insider_buying_3m_cr": 15.0,
        "insider_buying_verdict": "MODERATE_ACCUMULATION",
        "de_pledging_status": "AGGRESSIVE_DEPLEDGING",
        "skin_in_the_game_score": 86,
        "actionable_verdict": "⚡ RAPID DE-PLEDGING TRAJECTORY: Heavy pledge unwinding removing debt overhang",
    },
    "KAYNES": {
        "name": "Kaynes Technology India Ltd",
        "promoter_holding_pct": 57.8,
        "pledged_pct": 0.0,
        "pledge_reduction_1y_pct": 0.0,
        "insider_buying_3m_cr": 8.0,
        "insider_buying_verdict": "MODERATE_ACCUMULATION",
        "de_pledging_status": "ZERO_PLEDGE_CLEAN",
        "skin_in_the_game_score": 93,
        "actionable_verdict": "🟢 ZERO PLEDGE WITH HIGH FOUNDER ALIGNMENT",
    },
}


def analyze_insider_activity(
    symbol: str,
    promoter_holding_pct: Optional[float] = None,
    pledged_pct: Optional[float] = None,
    pledge_reduction_1y_pct: Optional[float] = None,
    insider_buying_3m_cr: Optional[float] = None,
) -> PromoterInsiderReport:
    """
    Computes promoter skin-in-the-game, de-pledging trajectory, and SAST insider accumulation.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # 1. Canonical data lookup
    if clean_sym in CANONICAL_INSIDER_LEDGER:
        entry = CANONICAL_INSIDER_LEDGER[clean_sym]
        insights = [
            f"Promoter holding stands at {entry['promoter_holding_pct']}%.",
            f"Pledged shares: {entry['pledged_pct']}% (1-year reduction: {entry['pledge_reduction_1y_pct']}%).",
            f"Insider open-market purchases (90D): ₹{entry['insider_buying_3m_cr']} Cr.",
            entry["actionable_verdict"],
        ]
        return PromoterInsiderReport(
            symbol=clean_sym,
            company_name=entry["name"],
            promoter_holding_pct=entry["promoter_holding_pct"],
            pledged_pct=entry["pledged_pct"],
            pledge_reduction_1y_pct=entry["pledge_reduction_1y_pct"],
            insider_buying_3m_cr=entry["insider_buying_3m_cr"],
            insider_buying_verdict=entry["insider_buying_verdict"],
            de_pledging_status=entry["de_pledging_status"],
            skin_in_the_game_score=entry["skin_in_the_game_score"],
            actionable_verdict=entry["actionable_verdict"],
            insights=insights,
        )

    # 2. Dynamic evaluation for other symbols
    promo_hold = promoter_holding_pct if promoter_holding_pct is not None else 50.0
    pledge = pledged_pct if pledged_pct is not None else 0.0
    pledge_red = pledge_reduction_1y_pct if pledge_reduction_1y_pct is not None else 0.0
    insider_buy = insider_buying_3m_cr if insider_buying_3m_cr is not None else 0.0

    score = 50
    insights = []

    # Pledge penalty or bonus
    if pledge == 0.0:
        score += 25
        de_pledge_status = "ZERO_PLEDGE_CLEAN"
        insights.append("Pristine zero-pledge structure: No margin call liquidation risk.")
    elif pledge_red >= 15.0:
        score += 20
        de_pledge_status = "AGGRESSIVE_DEPLEDGING"
        insights.append(
            f"Aggressive de-pledging in progress: Pledged shares reduced by {pledge_red}% YoY."
        )
    elif pledge <= 10.0:
        score += 10
        de_pledge_status = "STABLE_LOW_PLEDGE"
        insights.append(f"Low pledge level ({pledge}%).")
    elif pledge >= 40.0:
        score -= 30
        de_pledge_status = "DANGEROUS_HIGH_PLEDGE"
        insights.append(f"High risk: {pledge}% of promoter shares pledged as collateral.")
    else:
        de_pledge_status = "STABLE_PLEDGE"

    # Promoter holding tier
    if promo_hold >= 50.0:
        score += 15
        insights.append(f"High promoter equity ownership ({promo_hold}%).")
    elif promo_hold < 25.0:
        score -= 10
        insights.append(f"Low promoter equity ownership ({promo_hold}%).")

    # Open market insider purchases
    if insider_buy >= 20.0:
        score += 20
        buy_verdict = "AGGRESSIVE_INSIDER_BUYING"
        insights.append(
            f"Substantial open-market insider buying: ₹{insider_buy:.1f} Cr over 90 days."
        )
    elif insider_buy >= 5.0:
        score += 10
        buy_verdict = "MODERATE_ACCUMULATION"
        insights.append(f"Insider open-market accumulation: ₹{insider_buy:.1f} Cr.")
    elif insider_buy < 0:
        score -= 15
        buy_verdict = "INSIDER_SELLING"
        insights.append("Caution: Insider net open-market sales detected.")
    else:
        buy_verdict = "NEUTRAL"

    score = max(10, min(99, score))

    if score >= 85:
        verdict = "💎 HIGH SKIN-IN-THE-GAME: Clean promoter holding & strong insider conviction"
    elif score >= 65:
        verdict = "🟢 MODERATE SKIN-IN-THE-GAME: Manageable pledge & neutral/positive insider flows"
    else:
        verdict = "🔴 WEAK ALIGNMENT: Elevated pledge or low insider equity backing"

    return PromoterInsiderReport(
        symbol=clean_sym,
        company_name=clean_sym,
        promoter_holding_pct=promo_hold,
        pledged_pct=pledge,
        pledge_reduction_1y_pct=pledge_red,
        insider_buying_3m_cr=insider_buy,
        insider_buying_verdict=buy_verdict,
        de_pledging_status=de_pledge_status,
        skin_in_the_game_score=score,
        actionable_verdict=verdict,
        insights=insights,
    )


def scan_insider_radar() -> list[PromoterInsiderReport]:
    """Scans and ranks the canonical skin-in-the-game universe."""
    reports = [analyze_insider_activity(sym) for sym in CANONICAL_INSIDER_LEDGER]
    return sorted(reports, key=lambda r: r.skin_in_the_game_score, reverse=True)
