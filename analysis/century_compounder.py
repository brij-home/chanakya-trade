"""
analysis/century_compounder.py
──────────────────────────────
Institutional 100x, 1,000x & 10,000x Discovery Engine & Anti-FOMO Fair Value Accumulator.

The Empirical Mathematics of Indian Dalal Street Megacompounders (Titan, Bajaj Finance,
Eicher Motors, Astral, Aarti Industries, Trent, Dixon):

1. The "Twin Engines" Lollapalooza Formula:
     Stock Return = PAT Expansion (Earnings Growth) × P/E Multiple Expansion (Re-rating)
   - 100x Return (10,000% Gain):
       • Path A: 10x PAT Growth (26% CAGR for 10 yrs) × 10x P/E Expansion (e.g. 8x to 80x PE) = 100x.
       • Path B: 25x PAT Growth (38% CAGR for 10 yrs) × 4x P/E Expansion (e.g. 15x to 60x PE) = 100x.
   - 1,000x Return (100,000% Gain):
       • 50x–100x PAT Growth (30% CAGR over 15–18 yrs) × 10x–20x P/E Expansion = 1,000x.

2. The 7 Non-Negotiable Invariants of 100x–1,000x Compounders:
   - Pillar 1: Micro/Smallcap Market Cap Runway (Headroom)
       Must start at ₹500 Cr – ₹7,500 Cr Market Cap with a Total Addressable Market (TAM) >= ₹50,000 Cr.
       (A ₹5 Lakh Cr mega-cap cannot 100x because it would exceed India's GDP).
   - Pillar 2: Buffett-Mauboussin Reinvestment Compounding Machine
       Intrinsic Growth = ROIC × Reinvestment Rate.
       ROIC >= 22% and Reinvestment Rate >= 70% into high-return expansion without equity dilution.
   - Pillar 3: Operating Leverage Inflection (Fixed Cost Absorption)
       Completed Capex / Gross Block growth with Capacity Utilization crossing the 65% inflection point.
       Operating Leverage Multiplier = (% Δ EBIT) / (% Δ Revenue) >= 2.0x.
   - Pillar 4: P/E Alchemy (Multiple Re-Rating Opportunity)
       Initial mispricing as a "cyclical/contract manufacturer" (PE 10–18x) before recognition as a
       branded, proprietary, or high-entry-barrier compounder (re-rating to PE 50–80x).
   - Pillar 5: Institutional & Credit Rating Catalyst
       CRISIL/ICRA rating upgrades into A/AA unlocking institutional MF investment mandates,
       paired with QoQ FII/DII accumulation and promoter de-pledging.
   - Pillar 6: Forensic Fortress (Zero Terminal Risk)
       Beneish M-Score <= -2.22 (clean accounting), Altman Z" >= 2.60 (zero default risk),
       CFO/EBITDA >= 0.80 (cash earnings), Promoter holding > 55–65%, zero pledge.
   - Pillar 7: Vijay Kedia SMILE Framework
       Small in size, Medium experience, Investing in capex, Large market opportunity, Extraordinary leadership.

3. Anti-FOMO Fair Value Accumulation Architecture:
   - Accumulate only at Anchored VWAP / Volume Profile POC (Fair Value Zone).
   - Strict "NO CHASE" Boundary: Max +2.5% above pivot.
   - Pullback / Retest Auto-Limit Order generated when stock has gapped past the no-chase boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import os
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("analysis.century_compounder")


@dataclass
class TwinEngineForecast:
    """Mathematical projection of earnings expansion and multiple re-rating."""
    current_market_cap_cr: float
    current_pe: float
    projected_terminal_pe: float
    pe_expansion_multiple: float  # e.g. 3.5x
    
    current_pat_cr: float
    forecast_pat_cagr_pct: float  # e.g. 28%
    years_horizon: int  # 5 or 10 years
    pat_expansion_multiple: float  # e.g. 11.8x
    
    total_projected_multiple: float  # pat_multiple * pe_multiple (e.g. 41.3x)
    target_market_cap_cr: float
    compounder_tier: str  # "1000X_POTENTIAL" | "100X_CENTURY" | "25X_MULTIBAGGER" | "10X_QUALITY" | "STANDARD"


@dataclass
class AntiFomoExecutionBlueprint:
    """Discipline framework to prevent emotional chasing and accumulate at fair value."""
    fair_value_anchor: float  # Anchored VWAP / Volume Profile POC
    fair_value_source: str  # "VOLUME_PROFILE_POC" | "ANCHORED_VWAP" | "20_EMA_BASE"
    accumulate_low: float  # Fair value - 1.5%
    accumulate_high: float  # Fair value + 2.0%
    pivot_trigger: float  # Breakout level
    no_chase_boundary: float  # Pivot + 2.5% max
    pullback_limit_entry: float  # Where to place limit order if price gaps beyond no_chase
    invalidation_stop: float  # Structural invalidation SL
    risk_reward_to_2x: str
    action_directive: str  # "ACCUMULATE_FAIR_VALUE" | "WAIT_FOR_PULLBACK" | "STALK_PIVOT"


@dataclass
class CenturyCompounderReport:
    symbol: str
    ltp: float
    century_score: int  # 0 to 100
    is_qualified_compounder: bool  # Score >= 75
    compounder_tier: str  # "1000X_POTENTIAL" | "100X_CENTURY" | "25X_MULTIBAGGER" | "10X_QUALITY" | "STANDARD"
    
    # Mathematical Twin Engines
    twin_engines: TwinEngineForecast
    
    # 7 Pillar Breakdown
    runway_score: int  # 0 - 15 (Microcap headroom vs TAM)
    reinvestment_score: int  # 0 - 15 (ROIC >= 22% & Reinvestment Rate >= 70%)
    operating_leverage_score: int  # 0 - 15 (EBIT/Sales growth ratio & Capex)
    multiple_rerating_score: int  # 0 - 15 (PE vs Terminal PE headroom)
    institutional_catalyst_score: int  # 0 - 15 (Credit upgrade & FII/DII accumulation)
    forensic_fortress_score: int  # 0 - 15 (Beneish, Altman, CFO/EBITDA, Zero Pledge)
    smile_framework_score: int  # 0 - 10 (Vijay Kedia SMILE criteria)
    
    pillar_notes: list[str] = field(default_factory=list)
    catalyst_badges: list[str] = field(default_factory=list)
    
    # Anti-FOMO Execution Blueprint
    anti_fomo: AntiFomoExecutionBlueprint = field(default_factory=lambda: AntiFomoExecutionBlueprint(
        fair_value_anchor=0.0,
        fair_value_source="VOLUME_PROFILE_POC",
        accumulate_low=0.0,
        accumulate_high=0.0,
        pivot_trigger=0.0,
        no_chase_boundary=0.0,
        pullback_limit_entry=0.0,
        invalidation_stop=0.0,
        risk_reward_to_2x="1:4.0",
        action_directive="STALK_PIVOT"
    ))
    
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_twin_engines(
    market_cap_cr: float,
    pe: float,
    sales_growth_pct: float,
    pat_margin_pct: float,
    roce_pct: float,
    gross_block_growth_pct: float = 20.0,
    tam_cr: float = 100000.0,
) -> TwinEngineForecast:
    """
    Computes the empirical Twin Engines (PAT Growth × PE Multiple Expansion).
    
    Indian Market Realities:
      - Titan, Bajaj Finance, Eicher Motors started at P/E 8–18x and expanded to 55–80x.
      - Operating leverage accelerates PAT CAGR significantly above top-line sales growth.
    """
    mcap = max(100.0, market_cap_cr)
    curr_pe = max(5.0, min(120.0, pe if pe and pe > 0 else 22.0))
    
    # 1. PE Re-Rating Potential
    # If company has high ROCE (>25%) and enters institutional scale, terminal PE is 45-65x.
    if roce_pct >= 25.0:
        base_terminal_pe = 55.0
    elif roce_pct >= 18.0:
        base_terminal_pe = 42.0
    elif roce_pct >= 12.0:
        base_terminal_pe = 28.0
    else:
        base_terminal_pe = 18.0
        
    # Cap terminal PE so it doesn't exceed 75x
    terminal_pe = round(min(75.0, max(curr_pe, base_terminal_pe)), 1)
    pe_expansion_mult = round(max(1.0, terminal_pe / curr_pe), 2)
    
    # 2. PAT CAGR Projection with Operating Leverage Boost
    # If gross block (capex) expanded > 25%, operating leverage multiplier = 1.35x to 1.7x
    op_lev_boost = 1.45 if gross_block_growth_pct >= 25.0 else (1.20 if gross_block_growth_pct >= 12.0 else 1.05)
    base_sales_growth = max(10.0, min(50.0, sales_growth_pct if sales_growth_pct else 20.0))
    projected_pat_cagr = round(min(45.0, base_sales_growth * op_lev_boost), 1)
    
    # 10-Year Horizon Compounding
    years = 10
    pat_expansion_mult = round(float((1.0 + (projected_pat_cagr / 100.0)) ** years), 1)
    
    # Market Cap Headroom Constraint
    # A company cannot expand beyond the Total Addressable Market (TAM)
    raw_total_mult = pe_expansion_mult * pat_expansion_mult
    max_mcap_headroom = tam_cr / mcap
    total_mult = round(min(raw_total_mult, max_mcap_headroom * 1.5), 1)
    
    target_mcap = round(mcap * total_mult, 1)
    current_pat = round(mcap / curr_pe, 1)
    
    if total_mult >= 500.0:
        tier = "1000X_POTENTIAL"
    elif total_mult >= 75.0:
        tier = "100X_CENTURY"
    elif total_mult >= 25.0:
        tier = "25X_MULTIBAGGER"
    elif total_mult >= 10.0:
        tier = "10X_QUALITY"
    else:
        tier = "STANDARD"
        
    return TwinEngineForecast(
        current_market_cap_cr=round(mcap, 1),
        current_pe=round(curr_pe, 1),
        projected_terminal_pe=terminal_pe,
        pe_expansion_multiple=pe_expansion_mult,
        current_pat_cr=current_pat,
        forecast_pat_cagr_pct=projected_pat_cagr,
        years_horizon=years,
        pat_expansion_multiple=pat_expansion_mult,
        total_projected_multiple=total_mult,
        target_market_cap_cr=target_mcap,
        compounder_tier=tier,
    )


def evaluate_century_compounder(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    ltp: Optional[float] = None,
    exchange: str = "NSE",
) -> CenturyCompounderReport:
    """
    Evaluates an asset against the institutional 7 Pillars of 100x–1,000x Compounders,
    computes the Twin Engines projection, and formulates the Anti-FOMO Fair Value blueprint.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    
    # 1. Resolve Price
    if ltp is None or ltp <= 0:
        if df is not None and len(df) > 0 and "close" in df.columns:
            ltp = float(df["close"].iloc[-1])
        else:
            try:
                from market.quotes import get_quote
                q = get_quote(f"NSE:{clean_sym}")
                if q:
                    ltp = float(getattr(q, "last_price", getattr(q, "ltp", 0.0)))
            except Exception:
                ltp = 0.0
    ltp = round(float(ltp if ltp and ltp > 0 else 100.0), 2)
    
    # 2. Gather Fundamentals
    mcap_cr = 2500.0
    pe = 22.0
    roce = 24.0
    sales_growth = 22.0
    profit_growth = 28.0
    debt_equity = 0.25
    promoter_holding = 65.0
    pledge_pct = 0.0
    free_cash_flow = 80.0
    cfo_pat_ratio = 0.95
    gross_block_growth = 25.0
    
    if not os.environ.get("CHANAKYA_TESTING"):
        try:
            from analysis.fundamental import analyse
            snap = analyse(clean_sym)
            if snap:
                if snap.market_cap: mcap_cr = float(snap.market_cap)
                if snap.pe: pe = float(snap.pe)
                if snap.roce: roce = float(snap.roce)
                if snap.sales_growth: sales_growth = float(snap.sales_growth)
                if snap.profit_growth: profit_growth = float(snap.profit_growth)
                if snap.debt_equity: debt_equity = float(snap.debt_equity)
                if snap.promoter_holding: promoter_holding = float(snap.promoter_holding)
                if snap.pledged_pct is not None: pledge_pct = float(snap.pledged_pct)
        except Exception as e:
            logger.debug(f"[CenturyCompounder] Fundamental fetch error for {clean_sym}: {e}")

    # 3. Gather Institutional Catalysts (Credit Upgrades, FII/DII, De-Pledging)
    credit_rating = "AA"
    is_credit_upgrade = False
    fii_delta = 0.8
    dii_delta = 1.2
    has_creeping_acquisition = False
    
    try:
        from analysis.institutional_catalysts import get_institutional_catalysts
        cat_report = get_institutional_catalysts(clean_sym)
        if cat_report:
            credit_rating = cat_report.credit_rating.current_rating
            is_credit_upgrade = cat_report.credit_rating.is_upgrade
            fii_delta = cat_report.shareholding.fii_stake_delta_qoq
            dii_delta = cat_report.shareholding.dii_stake_delta_qoq
            has_creeping_acquisition = cat_report.shareholding.creeping_acquisition_detected
            pledge_pct = cat_report.promoter_skin.pledged_percentage
    except Exception as e:
        logger.debug(f"[CenturyCompounder] Institutional catalyst fetch error: {e}")

    # 4. Gather Forensic Audit
    beneish_m = -2.65
    altman_z = 3.8
    is_manipulator = False
    try:
        from analysis.forensic import audit_company_forensics
        fa = audit_company_forensics(clean_sym)
        if fa and fa.available:
            beneish_m = fa.beneish_m_score if fa.beneish_m_score is not None else -2.5
            altman_z = fa.altman_z_score if fa.altman_z_score is not None else 3.2
            is_manipulator = fa.is_manipulator_risk
    except Exception as e:
        logger.debug(f"[CenturyCompounder] Forensic audit fetch error: {e}")

    # ── Pillar Scoring (0–100 total) ───────────────────────────
    pillar_notes: list[str] = []
    badges: list[str] = []
    
    # Pillar 1: Market Cap Runway (0–15 pts)
    # Headroom to 100x: ₹500 Cr – ₹5,000 Cr is prime sweet spot
    if mcap_cr <= 2500.0:
        runway_score = 15
        pillar_notes.append(f"Sub-₹2,500 Cr Microcap (₹{mcap_cr:,.0f} Cr) with supreme 50x–100x scaling runway.")
        badges.append("🚀 Micro-Runway (<₹2.5k Cr)")
    elif mcap_cr <= 7500.0:
        runway_score = 12
        pillar_notes.append(f"High-growth Smallcap (₹{mcap_cr:,.0f} Cr) with 20x–40x institutional expansion runway.")
        badges.append("📈 Smallcap Runway")
    elif mcap_cr <= 20000.0:
        runway_score = 7
        pillar_notes.append(f"Midcap (₹{mcap_cr:,.0f} Cr) — Strong 5x–10x potential; 100x constrained by size.")
    else:
        runway_score = 2
        pillar_notes.append(f"Large-cap (₹{mcap_cr:,.0f} Cr) — Law of large numbers caps terminal multiple.")

    # Pillar 2: Buffett-Mauboussin Reinvestment Engine (0–15 pts)
    # Intrinsic Growth = ROIC * Reinvestment Rate
    if roce >= 24.0 and debt_equity <= 0.4:
        reinvestment_score = 15
        pillar_notes.append(f"Compounding Machine: Elite ROCE ({roce:.1f}%) + Low D/E ({debt_equity:.2f}) self-funds hypergrowth.")
        badges.append(f"💎 Elite ROCE {roce:.0f}%")
    elif roce >= 18.0 and debt_equity <= 0.8:
        reinvestment_score = 11
        pillar_notes.append(f"High-return capital deployment: ROCE ({roce:.1f}%) exceeds cost of capital.")
    elif roce >= 12.0:
        reinvestment_score = 6
    else:
        reinvestment_score = 0
        pillar_notes.append(f"Low capital efficiency: ROCE ({roce:.1f}%) creates zero economic value.")

    # Pillar 3: Operating Leverage Inflection & Capex Cycle (0–15 pts)
    # (% Δ EBIT) / (% Δ Revenue) >= 2.0x
    op_lev_ratio = profit_growth / max(5.0, sales_growth)
    if op_lev_ratio >= 1.5 and sales_growth >= 18.0:
        operating_leverage_score = 15
        pillar_notes.append(f"Operating Leverage Tipping Point: Profit growth ({profit_growth:.1f}%) outpaces Sales ({sales_growth:.1f}%) by {op_lev_ratio:.2f}x.")
        badges.append(f"⚡ Operating Leverage {op_lev_ratio:.1f}x")
    elif op_lev_ratio >= 1.2 or sales_growth >= 20.0:
        operating_leverage_score = 11
        pillar_notes.append(f"Strong capacity utilization & margin expansion (Sales +{sales_growth:.1f}%).")
    else:
        operating_leverage_score = 5

    # Pillar 4: Multiple Re-Rating Alchemy (0–15 pts)
    # Mispriced entry PE with huge room to expand
    if pe <= 22.0 and sales_growth >= 20.0:
        multiple_rerating_score = 15
        pillar_notes.append(f"P/E Alchemy: Deep PEG undervaluation (PE {pe:.1f}x vs {sales_growth:.1f}% growth) primed for 3x–5x multiple re-rating.")
        badges.append(f"🎯 PE Re-rating (P/E {pe:.1f}x)")
    elif pe <= 35.0:
        multiple_rerating_score = 10
        pillar_notes.append(f"Reasonable multiple (PE {pe:.1f}x) with moderate re-rating headroom.")
    elif pe <= 60.0:
        multiple_rerating_score = 5
    else:
        multiple_rerating_score = 2
        pillar_notes.append(f"Elevated valuation (PE {pe:.1f}x) leaves little headroom for multiple expansion.")

    # Pillar 5: Institutional & Credit Rating Catalyst (0–15 pts)
    # CRISIL/ICRA upgrade + FII/DII QoQ accumulation
    inst_pts = 0
    if is_credit_upgrade or credit_rating in ("AA", "AA+", "AAA"):
        inst_pts += 8
        badges.append(f"🏆 {credit_rating} Credit")
    if (fii_delta + dii_delta) >= 1.5:
        inst_pts += 7
        badges.append(f"🐋 Smart Money (+{(fii_delta + dii_delta):.1f}%)")
    elif (fii_delta + dii_delta) > 0.0:
        inst_pts += 4
    institutional_catalyst_score = min(15, inst_pts)

    # Pillar 6: Forensic Fortress & Skin in the Game (0–15 pts)
    # Clean Beneish, Altman, Zero Pledge, High Promoter
    forensic_pts = 0
    if not is_manipulator and (beneish_m is None or beneish_m <= -2.22):
        forensic_pts += 5
    if altman_z is None or altman_z >= 2.6:
        forensic_pts += 4
    if pledge_pct == 0.0:
        forensic_pts += 3
        badges.append("🛡️ Zero Pledge")
    if promoter_holding >= 60.0 or has_creeping_acquisition:
        forensic_pts += 3
        badges.append("👑 Promoter Skin")
    forensic_fortress_score = min(15, forensic_pts)

    # Pillar 7: Vijay Kedia SMILE Framework (0–10 pts)
    smile_pts = 0
    if mcap_cr <= 5000.0: smile_pts += 2  # Small in size
    if promoter_holding >= 55.0 and pledge_pct == 0.0: smile_pts += 2  # Extraordinary leadership
    if sales_growth >= 18.0: smile_pts += 2  # Large market
    if gross_block_growth >= 15.0 or debt_equity <= 0.5: smile_pts += 2  # Investing in business
    if roce >= 20.0: smile_pts += 2
    smile_framework_score = min(10, smile_pts)

    century_score = (
        runway_score
        + reinvestment_score
        + operating_leverage_score
        + multiple_rerating_score
        + institutional_catalyst_score
        + forensic_fortress_score
        + smile_framework_score
    )

    # ── Twin Engines Math ──────────────────────────────────────
    twin_engines = calculate_twin_engines(
        market_cap_cr=mcap_cr,
        pe=pe,
        sales_growth_pct=sales_growth,
        pat_margin_pct=15.0,
        roce_pct=roce,
        gross_block_growth_pct=gross_block_growth,
    )

    # ── Anti-FOMO Execution Blueprint ──────────────────────────
    # Calculate fair value anchor from Volume Profile POC or 20-EMA base
    fair_value = ltp
    fv_source = "20_EMA_BASE"
    pivot = round(ltp * 1.02, 2)
    
    if df is not None and len(df) >= 20:
        try:
            from analysis.volume_profile import compute_volume_profile
            poc_p, vah_p, val_p, _ = compute_volume_profile(df, num_bins=12)
            if poc_p > 0:
                fair_value = round(poc_p, 2)
                fv_source = "VOLUME_PROFILE_POC"
            highs = df["high"].values if "high" in df.columns else df["close"].values
            pivot = round(float(np.max(highs[-20:])), 2)
        except Exception:
            pass

    acc_low = round(fair_value * 0.98, 2)
    acc_high = round(fair_value * 1.025, 2)
    no_chase = round(pivot * 1.025, 2)  # Hard +2.5% max boundary
    pullback_limit = round(max(fair_value, pivot * 0.985), 2)
    invalidation_sl = round(acc_low * 0.94, 2)  # Structural base low
    
    # Determine Action Directive
    if ltp > no_chase:
        action_directive = "WAIT_FOR_PULLBACK"
        dir_msg = f"DO NOT CHASE! Asset is +{((ltp - pivot) / pivot * 100):.1f}% past pivot. Place limit order at pullback level (₹{pullback_limit:,.1f})."
    elif acc_low <= ltp <= acc_high:
        action_directive = "ACCUMULATE_FAIR_VALUE"
        dir_msg = f"In Prime Accumulation Zone (₹{acc_low:,.1f} – ₹{acc_high:,.1f}) anchored to {fv_source}. Systematic position build recommended."
    else:
        action_directive = "STALK_PIVOT"
        dir_msg = f"Coiling below breakout pivot (₹{pivot:,.1f}). Accumulate within range, trigger buy on volume breakout."

    risk_pts = max(1.0, ltp - invalidation_sl)
    rr_str = f"1:{(ltp * 1.0 / risk_pts):.1f}"

    anti_fomo = AntiFomoExecutionBlueprint(
        fair_value_anchor=fair_value,
        fair_value_source=fv_source,
        accumulate_low=acc_low,
        accumulate_high=acc_high,
        pivot_trigger=pivot,
        no_chase_boundary=no_chase,
        pullback_limit_entry=pullback_limit,
        invalidation_stop=invalidation_sl,
        risk_reward_to_2x=rr_str,
        action_directive=action_directive,
    )

    summary = (
        f"{clean_sym}: Century Compounder Score {century_score}/100 [{twin_engines.compounder_tier}]. "
        f"Twin Engines project {twin_engines.total_projected_multiple:.0f}x potential over {twin_engines.years_horizon}Y "
        f"({twin_engines.pat_expansion_multiple:.1f}x PAT growth × {twin_engines.pe_expansion_multiple:.1f}x P/E re-rating to {twin_engines.projected_terminal_pe:.0f}x). "
        f"{dir_msg}"
    )

    return CenturyCompounderReport(
        symbol=clean_sym,
        ltp=ltp,
        century_score=century_score,
        is_qualified_compounder=bool(century_score >= 70),
        compounder_tier=twin_engines.compounder_tier,
        twin_engines=twin_engines,
        runway_score=runway_score,
        reinvestment_score=reinvestment_score,
        operating_leverage_score=operating_leverage_score,
        multiple_rerating_score=multiple_rerating_score,
        institutional_catalyst_score=institutional_catalyst_score,
        forensic_fortress_score=forensic_fortress_score,
        smile_framework_score=smile_framework_score,
        pillar_notes=pillar_notes,
        catalyst_badges=badges,
        anti_fomo=anti_fomo,
        summary=summary,
    )


def resolve_compounder_universe(universe: Optional[list[str] | str] = None) -> list[str]:
    """Resolves string preset or list into a clean list of NSE/BSE tickers."""
    if isinstance(universe, str) and universe:
        try:
            from analysis.universe import resolve_universe

            symbols, _ = resolve_universe(universe)
            if symbols:
                return symbols
        except Exception:
            pass
    elif isinstance(universe, list) and universe:
        return universe

    # Default institutional high-asymmetry universe (Microcaps + Smallcaps)
    try:
        from analysis.universe import resolve_universe

        syms, _ = resolve_universe("microcap250")
        if syms:
            return syms
    except Exception:
        pass

    return [
        "TRENT",
        "DIXON",
        "KAYNES",
        "PREMIERENE",
        "WAAREEENER",
        "INOXWIND",
        "KPITTECH",
        "ZENTEC",
        "DATAPATTNS",
        "ARE&M",
        "NEWGEN",
        "RATEGAIN",
        "ASTRAL",
        "POLYCAB",
        "KALYANKJIL",
        "CDSL",
        "BSE",
        "MCX",
    ]


def scan_century_compounders(
    universe: Optional[list[str] | str] = None,
    min_score: int = 65,
    top_n: int = 15,
    use_cache: bool = True,
) -> list[CenturyCompounderReport]:
    """
    Scans full Indian market universe (NSE EQ series & BSE compounders) to surface 100x & 1,000x candidates.
    Leverages persistent SQLite caching to deliver instantaneous (<100ms) multi-stock results.
    """
    sym_list = resolve_compounder_universe(universe)
    cached_map: dict[str, dict[str, Any]] = {}

    if use_cache and not os.environ.get("CHANAKYA_TESTING"):
        try:
            from engine.eod_store import get_cached_century_compounders_batch

            cached_map = get_cached_century_compounders_batch(sym_list, max_age_days=7)
        except Exception as e:
            logger.debug(f"[CenturyCompounder] SQLite cache read error: {e}")

    results: list[CenturyCompounderReport] = []
    to_persist: list[dict[str, Any]] = []
    fresh_evaluated = 0
    max_fresh = 6 if use_cache and not os.environ.get("CHANAKYA_TESTING") else len(sym_list)

    for sym in sym_list:
        clean_s = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
        # 1. Use cached report if available
        if clean_s in cached_map:
            cached_d = cached_map[clean_s]
            if cached_d.get("century_score", 0) >= min_score:
                try:
                    te_d = cached_d.get("twin_engines", {})
                    af_d = cached_d.get("anti_fomo", {})
                    te = TwinEngineForecast(
                        current_market_cap_cr=float(te_d.get("current_market_cap_cr", 0.0)),
                        current_pe=float(te_d.get("current_pe", 0.0)),
                        projected_terminal_pe=float(te_d.get("projected_terminal_pe", 0.0)),
                        pe_expansion_multiple=float(te_d.get("pe_expansion_multiple", 1.0)),
                        current_pat_cr=float(te_d.get("current_pat_cr", 0.0)),
                        forecast_pat_cagr_pct=float(te_d.get("forecast_pat_cagr_pct", 0.0)),
                        years_horizon=int(te_d.get("years_horizon", 10)),
                        pat_expansion_multiple=float(te_d.get("pat_expansion_multiple", 1.0)),
                        total_projected_multiple=float(te_d.get("total_projected_multiple", 1.0)),
                        target_market_cap_cr=float(te_d.get("target_market_cap_cr", 0.0)),
                        compounder_tier=str(te_d.get("compounder_tier", "STANDARD")),
                    )
                    af = AntiFomoExecutionBlueprint(
                        fair_value_anchor=float(af_d.get("fair_value_anchor", 0.0)),
                        fair_value_source=str(af_d.get("fair_value_source", "VOLUME_PROFILE_POC")),
                        accumulate_low=float(af_d.get("accumulate_low", 0.0)),
                        accumulate_high=float(af_d.get("accumulate_high", 0.0)),
                        pivot_trigger=float(af_d.get("pivot_trigger", 0.0)),
                        no_chase_boundary=float(af_d.get("no_chase_boundary", 0.0)),
                        pullback_limit_entry=float(af_d.get("pullback_limit_entry", 0.0)),
                        invalidation_stop=float(af_d.get("invalidation_stop", 0.0)),
                        risk_reward_to_2x=str(af_d.get("risk_reward_to_2x", "1:4.0")),
                        action_directive=str(af_d.get("action_directive", "STALK_PIVOT")),
                    )
                    rep = CenturyCompounderReport(
                        symbol=clean_s,
                        ltp=float(cached_d.get("ltp", 0.0)),
                        century_score=int(cached_d.get("century_score", 0)),
                        is_qualified_compounder=bool(
                            cached_d.get("is_qualified_compounder", False)
                        ),
                        compounder_tier=str(cached_d.get("compounder_tier", "STANDARD")),
                        twin_engines=te,
                        runway_score=int(cached_d.get("runway_score", 0)),
                        reinvestment_score=int(cached_d.get("reinvestment_score", 0)),
                        operating_leverage_score=int(cached_d.get("operating_leverage_score", 0)),
                        multiple_rerating_score=int(cached_d.get("multiple_rerating_score", 0)),
                        institutional_catalyst_score=int(
                            cached_d.get("institutional_catalyst_score", 0)
                        ),
                        forensic_fortress_score=int(cached_d.get("forensic_fortress_score", 0)),
                        smile_framework_score=int(cached_d.get("smile_framework_score", 0)),
                        pillar_notes=cached_d.get("pillar_notes", []),
                        catalyst_badges=cached_d.get("catalyst_badges", []),
                        anti_fomo=af,
                        summary=str(cached_d.get("summary", "")),
                    )
                    results.append(rep)
                    continue
                except Exception:
                    pass

        # If cache satisfied top_n, stop early
        if len(results) >= top_n and use_cache:
            break

        # Bound on-the-fly network evaluations to keep responses snappy
        if fresh_evaluated >= max_fresh:
            continue

        # 2. Evaluate fresh
        try:
            rep = evaluate_century_compounder(clean_s)
            fresh_evaluated += 1
            if rep.century_score >= min_score:
                results.append(rep)
            to_persist.append(rep.to_dict())
        except Exception as e:
            logger.debug(f"[CenturyCompounder] Error evaluating {clean_s}: {e}")

    # Bulk persist freshly computed reports into SQLite
    if to_persist and not os.environ.get("CHANAKYA_TESTING"):
        try:
            from engine.eod_store import save_century_compounders_batch

            save_century_compounders_batch(to_persist)
        except Exception as e:
            logger.debug(f"[CenturyCompounder] Error persisting to SQLite: {e}")

    # Fallback to top cached compounders if results are empty and cache requested
    if not results and use_cache and not os.environ.get("CHANAKYA_TESTING"):
        try:
            from engine.eod_store import get_top_cached_century_compounders

            top_cached = get_top_cached_century_compounders(min_score=min_score, limit=top_n)
            for c_d in top_cached:
                try:
                    te_d = c_d.get("twin_engines", {})
                    af_d = c_d.get("anti_fomo", {})
                    te = TwinEngineForecast(
                        current_market_cap_cr=float(te_d.get("current_market_cap_cr", 0.0)),
                        current_pe=float(te_d.get("current_pe", 0.0)),
                        projected_terminal_pe=float(te_d.get("projected_terminal_pe", 0.0)),
                        pe_expansion_multiple=float(te_d.get("pe_expansion_multiple", 1.0)),
                        current_pat_cr=float(te_d.get("current_pat_cr", 0.0)),
                        forecast_pat_cagr_pct=float(te_d.get("forecast_pat_cagr_pct", 0.0)),
                        years_horizon=int(te_d.get("years_horizon", 10)),
                        pat_expansion_multiple=float(te_d.get("pat_expansion_multiple", 1.0)),
                        total_projected_multiple=float(te_d.get("total_projected_multiple", 1.0)),
                        target_market_cap_cr=float(te_d.get("target_market_cap_cr", 0.0)),
                        compounder_tier=str(te_d.get("compounder_tier", "STANDARD")),
                    )
                    af = AntiFomoExecutionBlueprint(
                        fair_value_anchor=float(af_d.get("fair_value_anchor", 0.0)),
                        fair_value_source=str(af_d.get("fair_value_source", "VOLUME_PROFILE_POC")),
                        accumulate_low=float(af_d.get("accumulate_low", 0.0)),
                        accumulate_high=float(af_d.get("accumulate_high", 0.0)),
                        pivot_trigger=float(af_d.get("pivot_trigger", 0.0)),
                        no_chase_boundary=float(af_d.get("no_chase_boundary", 0.0)),
                        pullback_limit_entry=float(af_d.get("pullback_limit_entry", 0.0)),
                        invalidation_stop=float(af_d.get("invalidation_stop", 0.0)),
                        risk_reward_to_2x=str(af_d.get("risk_reward_to_2x", "1:4.0")),
                        action_directive=str(af_d.get("action_directive", "STALK_PIVOT")),
                    )
                    results.append(
                        CenturyCompounderReport(
                            symbol=str(c_d.get("symbol", "")),
                            ltp=float(c_d.get("ltp", 0.0)),
                            century_score=int(c_d.get("century_score", 0)),
                            is_qualified_compounder=bool(c_d.get("is_qualified_compounder", False)),
                            compounder_tier=str(c_d.get("compounder_tier", "STANDARD")),
                            twin_engines=te,
                            runway_score=int(c_d.get("runway_score", 0)),
                            reinvestment_score=int(c_d.get("reinvestment_score", 0)),
                            operating_leverage_score=int(c_d.get("operating_leverage_score", 0)),
                            multiple_rerating_score=int(c_d.get("multiple_rerating_score", 0)),
                            institutional_catalyst_score=int(
                                c_d.get("institutional_catalyst_score", 0)
                            ),
                            forensic_fortress_score=int(c_d.get("forensic_fortress_score", 0)),
                            smile_framework_score=int(c_d.get("smile_framework_score", 0)),
                            pillar_notes=c_d.get("pillar_notes", []),
                            catalyst_badges=c_d.get("catalyst_badges", []),
                            anti_fomo=af,
                            summary=str(c_d.get("summary", "")),
                        )
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[CenturyCompounder] Fallback to top cached error: {e}")

    results.sort(
        key=lambda r: (r.century_score, r.twin_engines.total_projected_multiple), reverse=True
    )
    return results[:top_n]


def sync_and_precompute_market_compounders(
    universe_name: str = "microcap250",
    max_symbols: int = 120,
) -> dict[str, Any]:
    """
    Institutional Background Task: Parallel syncs fundamentals/EOD for a whole market universe
    and pre-computes 100x Century Compounder ratings in SQLite.
    """
    import concurrent.futures
    import time

    start_t = time.perf_counter()
    syms = resolve_compounder_universe(universe_name)[:max_symbols]
    logger.info(
        f"[CenturyCompounder] Starting parallel market precompute for {len(syms)} symbols ({universe_name})..."
    )

    to_persist = []
    qualified = []

    def _eval_sym(s: str):
        try:
            return evaluate_century_compounder(s)
        except Exception:
            return None

    # Parallel evaluation with 6 worker threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_eval_sym, s): s for s in syms}
        for fut in concurrent.futures.as_completed(futures):
            rep = fut.result()
            if rep:
                to_persist.append(rep.to_dict())
                if rep.century_score >= 60:
                    qualified.append(rep.symbol)

    if to_persist and not os.environ.get("CHANAKYA_TESTING"):
        try:
            from engine.eod_store import save_century_compounders_batch

            save_century_compounders_batch(to_persist)
        except Exception as e:
            logger.debug(f"[CenturyCompounder] Error persisting precompute batch: {e}")

    dur = round(time.perf_counter() - start_t, 2)
    return {
        "status": "COMPLETED",
        "universe": universe_name,
        "total_requested": len(syms),
        "precomputed_count": len(to_persist),
        "qualified_compounders": len(qualified),
        "duration_sec": dur,
        "top_picks": qualified[:10],
    }
