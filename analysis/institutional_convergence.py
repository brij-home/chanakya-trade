"""
analysis/institutional_convergence.py
──────────────────────────────────────
Master Institutional Edge Convergence Matrix.

Unifies all 6 institutional super-edge pillars into a single quantitative composite:
  1. Free-Float Absorption Index (CFAI & Delivery Accumulation Whales)
  2. SEBI Reg 30 Corporate Order-Inflows & Book-to-Bill Multiplier
  3. Capex & CWIP-to-Gross-Block Commercialization Inflection
  4. Institutional Block Deal Absorption vs Distribution Anchoring
  5. RRG Sector Momentum × Order-Book Backlog Convergence
  6. Promoter De-Pledging Trajectory & Open-Market Insider Buying (Skin-in-the-Game)

Generates institutional conviction ratings (0-100), edge count (0 to 6 active pillars),
and unified hedge-fund grade radar intelligence for Indian equities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Optional

import pandas as pd

from analysis.delivery_accumulation import compute_cfai
from analysis.order_book_catalyst import analyze_order_book_catalyst
from analysis.capex_inflection import analyze_capex_inflection
from analysis.block_deal_analyzer import analyze_block_deal_absorption
from analysis.rrg_orderbook_convergence import evaluate_rrg_orderbook_convergence
from analysis.insider_radar import analyze_insider_activity

logger = logging.getLogger("analysis.institutional_convergence")


@dataclass
class MasterConvergenceReport:
    """Consolidated institutional multi-factor edge analysis across all 6 pillars."""

    symbol: str
    company_name: str
    sector: str
    ltp: float

    # Pillar Scores (each 0 to 100)
    cfai_score: int
    order_book_score: int
    capex_inflection_score: int
    block_deal_score: int
    rrg_convergence_score: int
    insider_skin_score: int

    # Master Composite
    composite_institutional_score: int  # Weighted 0-100
    active_pillars_count: int  # How many pillars >= 75
    institutional_tier: str  # "APEX_INSTITUTIONAL_CONVERGENCE" | "HIGH_INSTITUTIONAL_CONVERGENCE" | "SELECTIVE_PILLAR_EDGE" | "NEUTRAL"
    actionable_verdict: str

    # Pillar Snapshot Highlights
    cfai_summary: str
    order_book_summary: str
    capex_summary: str
    block_deal_summary: str
    rrg_summary: str
    insider_summary: str

    institutional_support_floor: Optional[float] = None
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_master_institutional_convergence(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: Optional[float] = None,
    rrg_matrix: Optional[dict[str, Any]] = None,
) -> MasterConvergenceReport:
    """
    Evaluates all 6 institutional pillars for a given stock and computes the unified convergence score.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    # Determine current price
    price = ltp
    if price is None and df is not None and len(df) > 0:
        price = float(df["close"].iloc[-1])
    if price is None or price <= 0:
        price = 1000.0  # Safe default baseline if price is unavailable

    # 1. Pillar 1: CFAI & Delivery Accumulation
    cfai_rep = compute_cfai(clean_sym, df=df, ltp=price)
    p1_score = cfai_rep.accumulation_score
    p1_summary = f"CFAI: {cfai_rep.cfai_pct:.1f}% free-float absorbed (Delivery: {cfai_rep.current_delivery_pct:.1f}%, 20D Avg: {cfai_rep.avg_delivery_pct_20d:.1f}%)."

    # 2. Pillar 2: Order-Book & Book-to-Bill
    ob_rep = analyze_order_book_catalyst(clean_sym)
    b2b = ob_rep.book_to_bill_ratio
    if b2b >= 4.0:
        p2_score = 95
    elif b2b >= 2.5:
        p2_score = 85
    elif b2b >= 1.5:
        p2_score = 70
    elif b2b >= 1.0:
        p2_score = 55
    else:
        p2_score = 40
    p2_summary = f"Book-to-Bill: {b2b:.1f}x (₹{ob_rep.current_order_book_cr:,.0f} Cr order backlog)."

    # 3. Pillar 3: Capex & CWIP Inflection
    capex_rep = analyze_capex_inflection(clean_sym)
    p3_score = capex_rep.conviction_score
    p3_summary = f"Gross Block YoY: +{capex_rep.gross_block_growth_1y_pct:.1f}% (CWIP: {capex_rep.cwip_to_gross_block_pct:.1f}%)."

    # 4. Pillar 4: Institutional Block Deals
    block_rep = analyze_block_deal_absorption(clean_sym, current_price=price)
    if block_rep.status == "INSTITUTIONAL_ABSORPTION":
        p4_score = 90
        p4_summary = f"Institutional Absorption active above ₹{block_rep.support_anchor_price:.2f} floor."
    elif block_rep.status == "SUSPECTED_DISTRIBUTION":
        p4_score = 25
        p4_summary = f"Caution: Suspected Institutional Distribution below ₹{block_rep.support_anchor_price:.2f}."
    else:
        p4_score = 50
        p4_summary = "No major institutional bulk/block transactions detected in window."

    # 5. Pillar 5: RRG Sector Momentum Convergence
    rrg_rep = evaluate_rrg_orderbook_convergence(clean_sym, rrg_matrix=rrg_matrix)
    p5_score = rrg_rep.composite_conviction
    p5_summary = f"Sector '{rrg_rep.sector}' in {rrg_rep.rrg_quadrant} (RS-Momentum: {rrg_rep.rs_momentum:.1f})."

    # 6. Pillar 6: Promoter De-Pledging & Insider Skin-in-the-Game
    insider_rep = analyze_insider_activity(clean_sym)
    p6_score = insider_rep.skin_in_the_game_score
    p6_summary = f"Promoter Holding: {insider_rep.promoter_holding_pct:.1f}%, Pledged: {insider_rep.pledged_pct:.1f}%."

    # Weighted Master Composite Score
    # Weights:
    #   Pillar 1 (CFAI): 20%
    #   Pillar 2 (Order Book): 20%
    #   Pillar 3 (Capex): 15%
    #   Pillar 4 (Block Deals): 15%
    #   Pillar 5 (RRG Convergence): 15%
    #   Pillar 6 (Insider Skin): 15%
    composite = int(
        round(
            (p1_score * 0.20)
            + (p2_score * 0.20)
            + (p3_score * 0.15)
            + (p4_score * 0.15)
            + (p5_score * 0.15)
            + (p6_score * 0.15)
        )
    )
    composite = max(0, min(100, composite))

    # Count pillars with strong conviction (score >= 75)
    pillar_scores = [p1_score, p2_score, p3_score, p4_score, p5_score, p6_score]
    active_count = sum(1 for s in pillar_scores if s >= 75)

    if composite >= 85 and active_count >= 4:
        tier = "APEX_INSTITUTIONAL_CONVERGENCE"
        verdict = f"🔥 APEX CONVERGENCE ({active_count}/6 Pillars Firing): Institutional Multibagger Super-Setup"
    elif composite >= 70 and active_count >= 3:
        tier = "HIGH_INSTITUTIONAL_CONVERGENCE"
        verdict = f"🟢 HIGH CONVERGENCE ({active_count}/6 Pillars Firing): Strong Institutional Tailwinds"
    elif composite >= 55:
        tier = "SELECTIVE_PILLAR_EDGE"
        verdict = f"🟡 SELECTIVE EDGE ({active_count}/6 Pillars Active): Specific Catalyst Play"
    else:
        tier = "NEUTRAL"
        verdict = "⚪ NEUTRAL / ACCUMULATION PENDING: No institutional clustering detected"

    insights = [
        f"Active Institutional Pillars: {active_count} of 6 qualified with institutional confidence.",
        p1_summary,
        p2_summary,
        p3_summary,
        p4_summary,
        p5_summary,
        p6_summary,
    ]

    return MasterConvergenceReport(
        symbol=clean_sym,
        company_name=ob_rep.company_name if ob_rep.company_name != clean_sym else capex_rep.company_name,
        sector=rrg_rep.sector,
        ltp=round(price, 2),
        cfai_score=p1_score,
        order_book_score=p2_score,
        capex_inflection_score=p3_score,
        block_deal_score=p4_score,
        rrg_convergence_score=p5_score,
        insider_skin_score=p6_score,
        composite_institutional_score=composite,
        active_pillars_count=active_count,
        institutional_tier=tier,
        actionable_verdict=verdict,
        cfai_summary=p1_summary,
        order_book_summary=p2_summary,
        capex_summary=p3_summary,
        block_deal_summary=p4_summary,
        rrg_summary=p5_summary,
        insider_summary=p6_summary,
        institutional_support_floor=block_rep.support_anchor_price if block_rep.status == "INSTITUTIONAL_ABSORPTION" else None,
        insights=insights,
    )


def scan_master_institutional_radar() -> list[MasterConvergenceReport]:
    """
    Scans the cross-universe of institutional leaders across all 6 pillars and ranks them.
    """
    from analysis.order_book_catalyst import ORDER_BOOK_TITANS_LEDGER
    from analysis.capex_inflection import CANONICAL_CAPEX_TITANS
    from analysis.insider_radar import CANONICAL_INSIDER_LEDGER
    from analysis.sector_rotation import get_sector_rrg_matrix

    all_symbols = list(
        set(
            list(ORDER_BOOK_TITANS_LEDGER.keys())
            + list(CANONICAL_CAPEX_TITANS.keys())
            + list(CANONICAL_INSIDER_LEDGER.keys())
        )
    )

    try:
        rrg_matrix = {p.sector: p for p in get_sector_rrg_matrix()}
    except Exception:
        rrg_matrix = None

    reports = [
        evaluate_master_institutional_convergence(sym, rrg_matrix=rrg_matrix)
        for sym in all_symbols
    ]
    return sorted(reports, key=lambda r: (r.active_pillars_count, r.composite_institutional_score), reverse=True)
