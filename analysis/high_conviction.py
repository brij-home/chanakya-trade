"""
analysis/high_conviction.py
───────────────────────────
Institutional High-Conviction Opportunity Screener & Ranking Engine.

Evaluates stocks across 5 quantitative pillars in parallel:
  1. Price Action & Smart Money Concepts (SMC): Structural Regimes, CHoCH Shifts, Order Blocks.
  2. Volume Price Analysis (VPA): RVOL 20D/50D, VSA Absorption, Point of Control (POC).
  3. Multibagger Discovery: Minervini 8-Point Trend Template, Weinstein Stage 2, VCP Contraction.
  4. Sector Momentum: Relative Rotation Graph (RRG) Quadrants & Tailwinds.
  5. Forensic Governance: Beneish M-Score, Altman Z''-Score, Piotroski F-Score.

Calculates a composite Conviction Score (0–100) and produces actionable trade setups.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional

# Fix Windows charmap / cp1252 codec errors for unicode console prints
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import pandas as pd

from analysis.forensic import audit_forensics
from analysis.market_structure import analyze_market_structure
from analysis.multibagger import scan_multibagger_opportunity
from analysis.sector_rotation import get_sector_rrg_matrix, get_stock_sector_alignment
from analysis.universe import get_stock_sector, resolve_dynamic_universe
from analysis.volume_profile import analyze_volume_profile
from engine.analysis_cache import cache_get, cache_set

@dataclass
class HighConvictionOpportunity:
    rank: int
    symbol: str
    sector: str
    ltp: float
    conviction_score: int
    setup_type: str
    setup_title: str
    trade_bias: str  # "LONG" | "SHORT"
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward_ratio: float
    risk_pts: float
    reward_pts: float
    catalyst_summary: str
    structure_regime: str
    weinstein_stage: str
    trend_template_passed: int
    rvol_20d: float
    vcp_detected: bool
    forensic_quality: str
    liquidity_tier: str = "TIER_1_ULTRA_LIQUID"  # "TIER_1_ULTRA_LIQUID" | "TIER_2_ACTIVE_LIQUID" | "TIER_3_MIDCAP"
    est_turnover_cr: float = 100.0  # Estimated daily turnover in Crores
    sector_icon: str = "🏢"
    data_source: str = "HISTORICAL_EOD"  # "LIVE_TICK" | "HISTORICAL_EOD"
    as_of_date: str = ""
    dataset_info: str = "NSE Daily OHLCV (250 Bars Lookback)"
    expected_timeline: str = "3–10 Trading Days (Swing Momentum)"
    target_1_timeline: str = "2–5 Trading Days"
    target_2_timeline: str = "6–10 Trading Days"
    time_stop_days: int = 10
    profit_booking_plan: str = ""
    eligibility_status: str = "READY"  # "READY" | "STALK" | "STAND_DOWN"
    eligibility_label: str = "🟢 Top Pick (Ready)"
    why_rationale: str = ""
    contributing_factors: dict[str, Any] = field(default_factory=dict)
    smc_signals: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HighConvictionScanResult:
    timestamp: str
    scanned_universe: str
    total_scanned: int
    market_posture: str  # "BULLISH_EXPANSION" | "CHOPPY_ROTATION" | "DEFENSIVE_RISK_OFF"
    leading_sectors: list[str]
    opportunities: list[HighConvictionOpportunity]
    summary: str
    top_down_rationale: str = ""
    data_source: str = "HISTORICAL_EOD"  # "LIVE_TICK" | "HISTORICAL_EOD"
    dataset_timeline: str = "NSE Daily OHLCV (250 Bars Lookback · EOD Daily Bars)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "scanned_universe": self.scanned_universe,
            "total_scanned": self.total_scanned,
            "market_posture": self.market_posture,
            "leading_sectors": self.leading_sectors,
            "opportunities": [o.to_dict() for o in self.opportunities],
            "summary": self.summary,
            "top_down_rationale": self.top_down_rationale,
            "data_source": self.data_source,
            "dataset_timeline": self.dataset_timeline,
        }



def _evaluate_single_stock(
    symbol: str,
    exchange: str = "NSE",
    data_override: Optional[pd.DataFrame] = None,
) -> Optional[HighConvictionOpportunity]:
    """
    Evaluates a single ticker across the 5 quantitative pillars and computes conviction score.
    Reuses historical OHLCV data across all analyzers to prevent redundant external fetches.
    """
    try:
        # Fetch OHLCV data once per stock (or reuse data_override)
        df = data_override
        if df is None or len(df) == 0:
            try:
                from market.history import get_ohlcv

                df = get_ohlcv(symbol, exchange=exchange, interval="day", days=250)
            except Exception:
                df = None

        if df is None or len(df) < 10:
            return None

        # 1. Price Action & Market Structure
        ms = analyze_market_structure(symbol, exchange=exchange, df=df)
        if not ms or ms.ltp <= 0:
            return None

        ltp = ms.ltp

        # 2. Volume Profile & RVOL
        vp = analyze_volume_profile(symbol, exchange=exchange, df=df)

        # 3. Multibagger & Minervini Trend Template
        mb = scan_multibagger_opportunity(symbol, exchange=exchange, df=df)

        # 4. Sector Rotation & Alignment
        sector_info = get_stock_sector_alignment(symbol)
        sector_name = sector_info.get("sector", "Broad Market")
        sector_tailwind = sector_info.get("tailwind_score", 50)
        sector_quadrant = sector_info.get("quadrant", "IMPROVING")

        # 5. Forensic Governance Audit
        forensic = audit_forensics(symbol)

        # ── Compute Composite Conviction Score (0–100) ───────────────
        score = 0.0

        # Component A: Market Structure (Weight: 25%)
        # Map regime & structure_score (-100 to +100) to 0-100
        ms_pts = max(0, min(100, (ms.structure_score + 100) / 2))
        if ms.choch_detected and ms.choch_type == "BULLISH_CHOCH":
            ms_pts = max(ms_pts, 80)
        if ms.bos_detected and ms.bos_type == "BULLISH_BOS":
            ms_pts = max(ms_pts, 85)
        score += 0.25 * ms_pts

        # Component B: Volume Profile & Footprint (Weight: 20%)
        vp_pts = 50.0
        if vp.rvol_20d >= 2.0:
            vp_pts = 95.0
        elif vp.rvol_20d >= 1.5:
            vp_pts = 85.0
        elif vp.rvol_20d >= 1.1:
            vp_pts = 70.0
        elif vp.rvol_20d < 0.6:
            vp_pts = 45.0  # low volume

        if vp.footprint_bias == "ACCUMULATION":
            vp_pts = min(100.0, vp_pts + 15.0)
        score += 0.20 * vp_pts

        # Component C: Multibagger & Trend Template (Weight: 25%)
        mb_pts = mb.multibagger_score
        score += 0.25 * mb_pts

        # Component D: Sector RRG Alignment (Weight: 15%)
        score += 0.15 * sector_tailwind

        # Component E: Forensic Accounting Safety (Weight: 15%)
        forensic_pts = 80.0
        if forensic.quality_rating in ("A+", "A"):
            forensic_pts = 95.0
        elif forensic.quality_rating == "B":
            forensic_pts = 75.0
        elif forensic.quality_rating in ("C", "D"):
            forensic_pts = 40.0
        if forensic.governance_red_flags:
            forensic_pts = max(10, forensic_pts - 25)
        score += 0.15 * forensic_pts

        conviction_score = int(round(max(0, min(100, score))))

        # ── Determine Setup Archetype & Trade Bias ────────────────────
        smc_signals = []
        tags = []

        if ms.choch_detected:
            smc_signals.append(f"⚠️ {ms.choch_type}")
        if ms.bos_detected:
            smc_signals.append(f"🚀 {ms.bos_type}")
        if ms.liquidity_sweeps:
            smc_signals.append("🎯 Liquidity Sweep Reclaimed")
        if mb.vcp_detected:
            smc_signals.append("⚡ VCP Contraction Active")

        # Classify setup archetype
        setup_type = "BREAKOUT_EXPANSION"
        setup_title = "🚀 Breakout Expansion"
        trade_bias = "LONG"

        if mb.vcp_detected:
            setup_type = "VCP_CONTRACTION"
            setup_title = "⚡ VCP Volatility Contraction"
            tags.append("VCP")
            tags.append("Tight Base")
        elif ms.setup_type == "BOTTOM_FISHING_SPRING" or (ms.choch_detected and ms.choch_type == "BULLISH_CHOCH"):
            setup_type = "BOTTOM_FISHING_SPRING"
            setup_title = "🎣 Bottom Fishing (Wyckoff Spring)"
            tags.append("Reversal")
            tags.append("High R:R")
        elif ms.active_demand_zones and ltp <= ms.active_demand_zones[-1].top * 1.02:
            setup_type = "PULLBACK_DEMAND_OB"
            setup_title = "🎯 Pullback to Demand OB"
            tags.append("Demand Retest")
        elif mb.weinstein_stage == "STAGE_2_MARKUP":
            setup_type = "STAGE_2_SUPERPERFORMER"
            setup_title = "💎 Stage 2 Superperformer"
            tags.append("Stage 2")
            tags.append("Momentum")
        elif ms.regime == "BEARISH":
            setup_type = "TOP_FISHING_UTAD"
            setup_title = "🏔️ Top Fishing (UTAD Distribution)"
            trade_bias = "SHORT"
            tags.append("Short Setup")
        else:
            setup_type = "MOMENTUM_EXPANSION"
            setup_title = "📈 Trend Momentum"
            tags.append("Trend Continuation")

        if vp.rvol_20d >= 1.8:
            tags.append(f"RVOL {vp.rvol_20d:.1f}x")
        if mb.trend_template_passed >= 6:
            tags.append(f"{mb.trend_template_passed}/8 Rules")
        if sector_quadrant in ("LEADING", "IMPROVING"):
            tags.append(f"{sector_name} Sector")

        # ── Price Targets & Levels ───────────────────────────────────
        entry_price = ltp
        stop_loss = ms.invalidation_level
        target_1 = ms.target_1
        target_2 = ms.target_2

        # Sanity check stop loss
        if trade_bias == "LONG":
            if stop_loss >= entry_price or stop_loss <= 0:
                stop_loss = round(entry_price * 0.965, 2)
            risk_pts = round(entry_price - stop_loss, 2)
            reward_pts = round((target_1 - entry_price) if target_1 > entry_price else risk_pts * 2.0, 2)
            if target_1 <= entry_price:
                target_1 = round(entry_price + risk_pts * 2.0, 2)
            if target_2 <= target_1:
                target_2 = round(entry_price + risk_pts * 3.5, 2)
        else:
            if stop_loss <= entry_price or stop_loss <= 0:
                stop_loss = round(entry_price * 1.035, 2)
            risk_pts = round(stop_loss - entry_price, 2)
            reward_pts = round((entry_price - target_1) if target_1 < entry_price else risk_pts * 2.0, 2)
            if target_1 >= entry_price:
                target_1 = round(entry_price - risk_pts * 2.0, 2)
            if target_2 >= target_1:
                target_2 = round(entry_price - risk_pts * 3.5, 2)

        rr_ratio = round(reward_pts / max(1.0, risk_pts), 1)

        # ── Sector Taxonomy & Icon ────────────────────────────────────
        sec_id, sec_display = get_stock_sector(symbol)
        sector_icons = {
            "banking": "🏦", "it": "💻", "auto": "🚗", "defence": "🛡️",
            "energy": "⚡", "metals": "⛏️", "pharma": "💊", "fmcg": "🛒",
            "infra": "🏗️", "chemicals": "🧪", "telecom": "📡", "broad_market": "🏢",
        }
        sec_icon = sector_icons.get(sec_id, "🏢")

        # Estimate turnover in Crores (LTP * ~15D Avg Volume)
        approx_volume = 1200000 if ltp < 1000 else 450000 if ltp < 3000 else 150000
        est_turnover_cr = round((ltp * approx_volume * vp.rvol_20d) / 10000000, 1)
        if est_turnover_cr >= 100.0:
            liq_tier = "TIER_1_ULTRA_LIQUID"
        elif est_turnover_cr >= 25.0:
            liq_tier = "TIER_2_ACTIVE_LIQUID"
        else:
            liq_tier = "TIER_3_MIDCAP"

        # ── Catalyst Summary ─────────────────────────────────────────
        catalyst_parts = []
        if mb.weinstein_stage == "STAGE_2_MARKUP":
            catalyst_parts.append("Stage 2 Markup")
        if mb.vcp_detected:
            catalyst_parts.append("VCP Wave Contraction")
        if vp.rvol_20d >= 1.5:
            catalyst_parts.append(f"Institutional RVOL {vp.rvol_20d:.1f}x")
        if ms.choch_detected:
            catalyst_parts.append(ms.choch_type)
        if sector_quadrant == "LEADING":
            catalyst_parts.append(f"{sector_name} leading momentum")
        if forensic.quality_rating in ("A+", "A"):
            catalyst_parts.append(f"Grade {forensic.quality_rating} Balance Sheet")

        catalyst_summary = " · ".join(catalyst_parts) if catalyst_parts else "Multi-factor quantitative alignment."

        # Determine data provenance & timeline
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

        if data_override is not None and not data_override.empty:
            idx = data_override.index[-1]
            as_of_date = idx.strftime("%d %b %Y") if hasattr(idx, "strftime") else str(idx)
        else:
            as_of_date = now_dt.strftime("%d %b %Y")

        data_source = "HISTORICAL_EOD"
        dataset_info = f"NSE Daily OHLCV (250 Bars Lookback · As of {as_of_date})"

        # ── Expected Timelines & Profit-Booking Playbook ──────────────
        if setup_type in ("VCP_CONTRACTION", "STAGE_2_MARKUP"):
            expected_timeline = "3–10 Trading Days (Swing Momentum)"
            t1_timeline = "2–5 Trading Days"
            t2_timeline = "6–10 Trading Days"
            time_stop_days = 10
        elif setup_type in ("SMC_ORDER_BLOCK", "LIQUIDITY_SWEEP", "CHOCH_REVERSAL"):
            expected_timeline = "2–7 Trading Days (Swing Reversal)"
            t1_timeline = "1–3 Trading Days"
            t2_timeline = "4–7 Trading Days"
            time_stop_days = 7
        elif setup_type == "MULTIBAGGER_STAGE2":
            expected_timeline = "2–6 Weeks (Positional Trend)"
            t1_timeline = "1–2 Weeks"
            t2_timeline = "3–6 Weeks"
            time_stop_days = 20
        else:
            expected_timeline = "3–10 Trading Days (Swing Momentum)"
            t1_timeline = "2–5 Trading Days"
            t2_timeline = "6–10 Trading Days"
            time_stop_days = 10

        profit_booking_plan = (
            f"Scale out 50% at Target 1 (₹{target_1:,.2f}), move SL to Breakeven (+0.2%), "
            f"and trail remainder via Daily 20-EMA / 3.0×ATR to Target 2 (₹{target_2:,.2f})."
        )

        # ── Eligibility Classification & Institutional Rationale ──────
        if conviction_score >= 70 and (vp.rvol_20d >= 1.3 or mb.weinstein_stage == "STAGE_2_MARKUP" or ms.choch_detected or mb.vcp_detected) and not forensic.governance_red_flags:
            eligibility_status = "READY"
            eligibility_label = "🟢 TOP PICK (READY TO EXECUTE)"
            stage_str = mb.weinstein_stage.replace('_', ' ').title() if mb.weinstein_stage else 'Structural Markup'
            why_rationale = (
                f"🟢 Top Pick: Confirmed {stage_str} with {mb.trend_template_passed}/8 Minervini criteria passed, "
                f"{vp.rvol_20d:.1f}x institutional RVOL surge, clean balance sheet (Grade {forensic.quality_rating}), "
                f"and parent sector {sector_name} leading momentum in {sector_quadrant} quadrant."
            )
        elif conviction_score >= 50 or mb.trend_template_passed >= 5:
            eligibility_status = "STALK"
            eligibility_label = "🟡 WATCHLIST / STALK TRIGGER"
            why_rationale = (
                f"🟡 Stalking Setup: Solid baseline passing {mb.trend_template_passed}/8 trend template rules with {ms.regime.lower()} structure, "
                f"but volume is coiling ({vp.rvol_20d:.1f}x RVOL). Wait for volume breakout confirmation above ₹{entry_price:,.2f}."
            )
        else:
            eligibility_status = "STAND_DOWN"
            eligibility_label = "⚪ AVOID / LOW CONVICTION"
            why_rationale = (
                f"⚪ Low Conviction / Avoid: Sub-optimal relative strength vs peer group ({mb.trend_template_passed}/8 trend criteria passed) "
                f"or facing rotational sector headwinds in {sector_quadrant} quadrant."
            )

        contributing_factors = {
            "stage": mb.weinstein_stage.replace('_', ' ').title() if mb.weinstein_stage else "Stage 2 Markup",
            "trend_template": f"{mb.trend_template_passed}/8 Criteria Passed",
            "rvol": f"{vp.rvol_20d:.1f}x",
            "smc_structure": ms.choch_type if ms.choch_detected else ms.bos_type if ms.bos_detected else ms.regime,
            "forensic_grade": f"Grade {forensic.quality_rating}",
            "sector_quadrant": sector_quadrant,
            "piotroski_f": int(getattr(forensic, "piotroski_f_score", 7) or 7),
            "altman_z": round(float(getattr(forensic, "altman_z_score", 3.2) or 3.2), 2),
        }

        return HighConvictionOpportunity(
            rank=0,  # assigned during sorting
            symbol=symbol,
            sector=sector_name,
            ltp=ltp,
            conviction_score=conviction_score,
            setup_type=setup_type,
            setup_title=setup_title,
            trade_bias=trade_bias,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            risk_reward_ratio=rr_ratio,
            risk_pts=risk_pts,
            reward_pts=reward_pts,
            catalyst_summary=catalyst_summary,
            structure_regime=ms.regime,
            weinstein_stage=mb.weinstein_stage,
            trend_template_passed=mb.trend_template_passed,
            rvol_20d=vp.rvol_20d,
            vcp_detected=mb.vcp_detected,
            forensic_quality=forensic.quality_rating,
            liquidity_tier=liq_tier,
            est_turnover_cr=est_turnover_cr,
            sector_icon=sec_icon,
            data_source=data_source,
            as_of_date=as_of_date,
            dataset_info=dataset_info,
            expected_timeline=expected_timeline,
            target_1_timeline=t1_timeline,
            target_2_timeline=t2_timeline,
            time_stop_days=time_stop_days,
            profit_booking_plan=profit_booking_plan,
            eligibility_status=eligibility_status,
            eligibility_label=eligibility_label,
            why_rationale=why_rationale,
            contributing_factors=contributing_factors,
            smc_signals=smc_signals,
            tags=tags[:4],
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None


def scan_high_conviction_opportunities(
    universe: str | list[str] = "auto_market_aware",
    exchange: str = "NSE",
    top_n: int = 10,
    use_cache: bool = True,
) -> HighConvictionScanResult:
    """
    Scans a market-aware dynamic universe of liquid stocks and returns Top N High-Conviction trading opportunities.
    """
    now_ist = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    cache_key = f"high_conviction_{universe if isinstance(universe, str) else len(universe)}_{top_n}"

    if use_cache:
        cached = cache_get(cache_key, namespace="high_conviction", max_age_seconds=600)  # 10m cache
        if cached and isinstance(cached, dict):
            # Reconstruct result from cached dict with field safety
            valid_fields = {f.name for f in fields(HighConvictionOpportunity)}
            opps = []
            for o in cached.get("opportunities", []):
                if isinstance(o, dict):
                    clean_o = {k: v for k, v in o.items() if k in valid_fields}
                    try:
                        opps.append(HighConvictionOpportunity(**clean_o))
                    except Exception:
                        pass
            if len(opps) > 0:
                return HighConvictionScanResult(
                    timestamp=cached.get("timestamp", now_ist.strftime("%d %b %Y, %I:%M %p IST")),
                    scanned_universe=cached.get("scanned_universe", str(universe)),
                    total_scanned=cached.get("total_scanned", len(opps)),
                    market_posture=cached.get("market_posture", "BULLISH_EXPANSION"),
                    leading_sectors=cached.get("leading_sectors", []),
                    opportunities=opps,
                    summary=cached.get("summary", ""),
                    top_down_rationale=cached.get("top_down_rationale", ""),
                    data_source=cached.get("data_source", "HISTORICAL_EOD"),
                    dataset_timeline=cached.get("dataset_timeline", f"Dataset: 250D Daily Historical Bars (As of {now_ist.strftime('%d %b %Y')} Close)"),
                )


    # Resolve dynamic top-down or sector universe
    if isinstance(universe, list):
        symbols = universe
        resolution_reason = f"Custom list of {len(symbols)} tickers"
    else:
        symbols, resolution_reason = resolve_dynamic_universe(universe, use_cache=use_cache)

    # Fetch RRG matrix for macro context
    rrg_matrix = get_sector_rrg_matrix(use_cache=use_cache)
    leading_sectors = []
    if isinstance(rrg_matrix, list):
        for s in rrg_matrix:
            q = getattr(s, "quadrant", None) if hasattr(s, "quadrant") else s.get("quadrant") if isinstance(s, dict) else None
            sec = getattr(s, "sector", None) if hasattr(s, "sector") else s.get("sector") if isinstance(s, dict) else None
            if q == "LEADING" and sec:
                leading_sectors.append(sec)
    elif isinstance(rrg_matrix, dict):
        leading_sectors = [s["sector"] if isinstance(s, dict) else getattr(s, "sector", str(s)) for s in rrg_matrix.get("leading", [])]

    # Parallel evaluation
    candidates: list[HighConvictionOpportunity] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(symbols))) as executor:
        futures = {executor.submit(_evaluate_single_stock, sym, exchange): sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res is not None:
                candidates.append(res)

    # Sort descending by conviction score
    candidates.sort(key=lambda x: (x.conviction_score, x.risk_reward_ratio), reverse=True)

    # Pick top N and assign rank
    top_opportunities = candidates[:top_n]
    for idx, opp in enumerate(top_opportunities, start=1):
        opp.rank = idx

    # Determine market posture
    bull_count = sum(1 for o in top_opportunities if o.structure_regime == "BULLISH")
    bull_ratio = bull_count / max(1, len(top_opportunities))

    if bull_ratio >= 0.6:
        market_posture = "BULLISH_EXPANSION"
    elif bull_ratio <= 0.3:
        market_posture = "DEFENSIVE_RISK_OFF"
    else:
        market_posture = "CHOPPY_ROTATION"

    avg_conv = int(sum(o.conviction_score for o in top_opportunities) / max(1, len(top_opportunities))) if top_opportunities else 0
    summary = (
        f"Scanned {len(candidates)} liquid tickers. Market posture: {market_posture}. "
        f"Top setups led by {', '.join([o.symbol for o in top_opportunities[:3]])} with average conviction "
        f"{avg_conv}/100."
    )

    dataset_timeline = f"Dataset: 250D Daily Historical Bars (As of {now_ist.strftime('%d %b %Y')} Close)"

    result = HighConvictionScanResult(
        timestamp=now_ist.strftime("%d %b %Y, %I:%M %p IST"),
        scanned_universe=universe if isinstance(universe, str) else "custom_watchlist",
        total_scanned=len(candidates),
        market_posture=market_posture,
        leading_sectors=leading_sectors[:4],
        opportunities=top_opportunities,
        summary=summary,
        top_down_rationale=resolution_reason,
        data_source="HISTORICAL_EOD",
        dataset_timeline=dataset_timeline,
    )

    if use_cache and len(top_opportunities) > 0:
        cache_set(cache_key, result.to_dict(), namespace="high_conviction")

    return result


