"""
analysis/inflection_scanner.py
───────────────────────────────
Institutional High-Performance Inflection Point & Multibagger Screener.

Identifies the precise inflection point where high-growth, high-asymmetry moves are about
to ignite before they become obvious to retail participants.

Evaluates 5 Quantitative Inflection Archetypes:
  1. VCP_PIVOT_BREAKOUT: Minervini Volatility Contraction Pattern with tightest contraction (< 3.5%),
     volume drying up before volume explosion.
  2. TTM_SQUEEZE_EXPLOSION: Bollinger Bands (20, 2.0) compressed inside Keltner Channels (20, 1.5)
     for >= 5 bars with Linear Regression Momentum turning bullish.
  3. STAGE_1_TO_2_EXPANSION: Stan Weinstein Stage 1 accumulation base breakout, 50 SMA slope rising,
     150 & 200 SMA reclaimed, 52-week high proximity.
  4. SMC_SPRING_SWEEP: Wyckoff Spring / Liquidity Sweep below recent support base + Bullish CHoCH +
     retest of unmitigated Demand Order Block at 50% OTE (Optimal Trade Entry discount).
  5. RRG_SECTOR_ROTATION: Sector accelerating from Improving into Leading quadrant with stock
     exhibiting top-decile Relative Strength (RS-Ratio >= 100, RS-Momentum >= 100).

Timing Radar Classification:
  - "TRIGGER_NOW": Volume surge (RVOL >= 1.8x), breakout candle forming right at pivot.
  - "COILING_IMMINENT": Deep volatility compression (Squeeze ON, VCP tight, volume dry), stalk for 1–3 sessions.
  - "PULLBACK_RETEST": Breakout occurred, retesting breakout level / Order Block with declining volume.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import os
import sys
import time
from typing import Any, Optional

# UTF-8 console output for Windows
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

import numpy as np
import pandas as pd

from analysis.big_move import compute_ttm_squeeze
from analysis.forensic import audit_company_forensics
from analysis.market_structure import analyze_market_structure
from analysis.multibagger import (
    classify_weinstein_stage,
    detect_vcp,
    evaluate_trend_template,
)
from analysis.sector_rotation import get_stock_tailwind
from analysis.universe import (
    THEMATIC_PRESETS,
    get_stock_name,
    get_stock_sector,
    resolve_dynamic_universe,
)
from analysis.volume_profile import analyze_volume_profile


@dataclass
class InflectionSetup:
    symbol: str
    name: str
    sector: str
    sector_icon: str
    ltp: float
    day_change_pct: float
    inflection_score: int  # 0 to 100
    primary_archetype: str  # "VCP_PIVOT_BREAKOUT" | "TTM_SQUEEZE_EXPLOSION" | "STAGE_1_TO_2_EXPANSION" | "SMC_SPRING_SWEEP" | "RRG_SECTOR_ROTATION"
    archetype_label: str
    timing_state: str  # "TRIGGER_NOW" | "COILING_IMMINENT" | "PULLBACK_RETEST"
    timing_label: str
    weinstein_stage: str
    vcp_detected: bool
    vcp_tightness_pct: float
    vcp_pivot_price: float
    squeeze_state: str  # "COILING" | "FIRED" | "NORMAL"
    squeeze_duration: int
    rvol_20d: float
    trend_template_passed: int  # 0 to 8
    sector_tailwind_score: int  # 0 to 100
    rrg_quadrant: str
    forensic_safe: bool
    smc_regime: str
    smc_setup: str
    entry_price: float
    stop_loss: float
    target_1: float  # +2R Breakeven scale-out
    target_2: float  # +3.5R Swing Target
    target_moonshot: float  # +6R to +10R Generational Target
    risk_reward_ratio: float
    risk_pts: float
    reward_pts: float
    confluence_factors: list[str] = field(default_factory=list)
    catalyst_summary: str = ""
    suggested_action: str = ""
    execution_ticket: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InflectionScanResult:
    universe_id: str
    universe_name: str
    archetype_filter: str
    timing_filter: str
    total_scanned: int
    total_qualified: int
    candidates: list[InflectionSetup] = field(default_factory=list)
    archetype_counts: dict[str, int] = field(default_factory=dict)
    timing_counts: dict[str, int] = field(default_factory=dict)
    top_sectors: list[dict[str, Any]] = field(default_factory=list)
    scan_timestamp: str = ""
    execution_time_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe_id": self.universe_id,
            "universe_name": self.universe_name,
            "archetype_filter": self.archetype_filter,
            "timing_filter": self.timing_filter,
            "total_scanned": self.total_scanned,
            "total_qualified": self.total_qualified,
            "candidates": [c.to_dict() for c in self.candidates],
            "archetype_counts": self.archetype_counts,
            "timing_counts": self.timing_counts,
            "top_sectors": self.top_sectors,
            "scan_timestamp": self.scan_timestamp,
            "execution_time_seconds": self.execution_time_seconds,
        }


# ── Sector Icon Mapping ──────────────────────────────────────────────

SECTOR_ICONS: dict[str, str] = {
    "Banking & Financial Services": "🏦",
    "IT & Software Services": "💻",
    "Automotive & Ancillaries": "🚗",
    "Defence & Aerospace": "🛡️",
    "Energy & Utilities": "⚡",
    "Metals & Mining": "⛏️",
    "Pharma & Healthcare": "💊",
    "FMCG & Consumption": "🛒",
    "Infrastructure & Real Estate": "🏗️",
    "Chemicals & Fertilizers": "🧪",
    "Capital Goods & Industrial": "🏭",
    "Telecom & Media": "📡",
}


def _get_sector_icon(sector_name: str) -> str:
    for key, icon in SECTOR_ICONS.items():
        if key.lower() in sector_name.lower() or sector_name.lower() in key.lower():
            return icon
    return "🏢"


# ── Single Stock Inflection Evaluator ────────────────────────────────


def evaluate_single_stock_inflection(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
    sector_override: Optional[str] = None,
) -> Optional[InflectionSetup]:
    """
    Evaluates whether a single stock is at an inflection point ready for a big or multibagger move.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    if df is None or len(df) == 0:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(clean_sym, exchange=exchange, interval="day", days=300)
        except Exception:
            df = None

    if df is None or len(df) < 25:
        return None

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values
    ltp = float(closes[-1])
    if ltp <= 0:
        return None

    prev_close = float(closes[-2]) if len(closes) >= 2 else ltp
    day_change_pct = round(((ltp - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

    # 1. Minervini Trend Template & Weinstein Stage
    trend_passed, _ = evaluate_trend_template(df)
    weinstein_stage, stage_conf = classify_weinstein_stage(df)

    # 2. VCP Contraction Detection
    is_vcp, vcp_contractions, vcp_pivot = detect_vcp(df)
    vcp_tightness = (
        round(vcp_contractions[-1].depth_pct, 1)
        if (is_vcp and vcp_contractions)
        else 0.0
    )

    # 3. TTM Squeeze Detection
    squeeze = compute_ttm_squeeze(df)
    squeeze_status = "NORMAL"
    if squeeze.is_squeeze_on:
        squeeze_status = "COILING"
    elif squeeze.squeeze_fired and squeeze.momentum_value > 0:
        squeeze_status = "FIRED"

    # 4. Smart Money Concepts (SMC) Structure
    smc_rep = None
    try:
        smc_rep = analyze_market_structure(clean_sym, df=df)
    except Exception:
        pass

    smc_regime = smc_rep.regime if smc_rep else "CONSOLIDATION"
    smc_setup = smc_rep.setup_type if smc_rep else "RANGE_BOUND"
    has_choch = bool(smc_rep and smc_rep.choch_detected)
    has_spring = bool(smc_rep and "SPRING" in str(smc_setup).upper())

    # 5. Volume Profile & RVOL 20D
    rvol_20d = 1.0
    try:
        vpa_rep = analyze_volume_profile(clean_sym, df=df)
        rvol_20d = round(float(vpa_rep.rvol_20d), 2)
    except Exception:
        if len(volumes) >= 20:
            avg_vol = float(np.mean(volumes[-20:]))
            rvol_20d = round(float(volumes[-1]) / max(1.0, avg_vol), 2)

    # 6. Sector RRG Tailwind & Governance Forensics
    sec_info = get_stock_sector(clean_sym)
    sec_desc = sec_info[1] if isinstance(sec_info, tuple) else str(sec_info)
    sector_name = sector_override or sec_desc
    sector_tailwind = 60
    rrg_quadrant = "IMPROVING"
    forensic_safe = True

    if not os.environ.get("CHANAKYA_TESTING"):
        try:
            tailwind = get_stock_tailwind(clean_sym)
            if tailwind.quadrant and tailwind.quadrant != "UNAVAILABLE":
                rrg_quadrant = tailwind.quadrant
                sector_tailwind = tailwind.tailwind_score
            if sector_name in ("Broad Market", "BROAD_MARKET") and tailwind.sector:
                sector_name = tailwind.sector
        except Exception:
            pass

        try:
            f_audit = audit_company_forensics(clean_sym)
            forensic_safe = f_audit.overall_forensic_verdict in ("CLEAN_PASS", "MILD_WARNING")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────
    # 7. ARCHETYPE IDENTIFICATION & SCORING
    # ─────────────────────────────────────────────────────────────────
    confluence_factors: list[str] = []
    archetype_scores: dict[str, int] = {
        "VCP_PIVOT_BREAKOUT": 0,
        "TTM_SQUEEZE_EXPLOSION": 0,
        "STAGE_1_TO_2_EXPANSION": 0,
        "SMC_SPRING_SWEEP": 0,
        "RRG_SECTOR_ROTATION": 0,
    }

    # Archetype 1: VCP Pivot Breakout
    if is_vcp and vcp_pivot > 0:
        base_vcp = 60
        if vcp_tightness > 0 and vcp_tightness <= 4.0:
            base_vcp += 20
            confluence_factors.append(f"VCP Tight Contraction ({vcp_tightness}% pivot risk)")
        elif vcp_tightness <= 7.0:
            base_vcp += 10
            confluence_factors.append(f"VCP Contraction ({vcp_tightness}%)")

        pivot_dist_pct = abs(ltp - vcp_pivot) / vcp_pivot * 100.0
        if pivot_dist_pct <= 3.0:
            base_vcp += 15
            confluence_factors.append(f"At VCP Pivot ₹{vcp_pivot:.1f} (within {pivot_dist_pct:.1f}%)")

        archetype_scores["VCP_PIVOT_BREAKOUT"] = base_vcp

    # Archetype 2: TTM Squeeze Explosion
    if squeeze.is_squeeze_on or squeeze_status == "FIRED":
        base_sq = 55
        if squeeze.is_squeeze_on:
            base_sq += 15
            confluence_factors.append(f"TTM Squeeze Coiling ({squeeze.squeeze_duration_bars} bars)")
            if squeeze.momentum_value > 0:
                base_sq += 10
                confluence_factors.append("Squeeze Momentum Rising (+)")
        elif squeeze_status == "FIRED" and squeeze.momentum_value > 0:
            base_sq += 25
            confluence_factors.append("TTM Squeeze Volatility Explosion FIRED")

        archetype_scores["TTM_SQUEEZE_EXPLOSION"] = base_sq

    # Archetype 3: Stage 1 to 2 Expansion
    if weinstein_stage == "STAGE_2_MARKUP":
        base_s2 = 60 + int(trend_passed * 3.5)
        confluence_factors.append(f"Weinstein Stage 2 Markup ({trend_passed}/8 Minervini)")
        if trend_passed >= 6:
            base_s2 += 10
        archetype_scores["STAGE_1_TO_2_EXPANSION"] = base_s2
    elif weinstein_stage == "STAGE_1_BASE" and trend_passed >= 4:
        base_s1 = 50 + int(trend_passed * 3)
        confluence_factors.append(f"Stage 1 Accumulation Base Transition ({trend_passed}/8)")
        archetype_scores["STAGE_1_TO_2_EXPANSION"] = base_s1

    # Archetype 4: SMC Spring & Liquidity Sweep
    if has_choch or has_spring or smc_regime == "BULLISH":
        base_smc = 50
        if has_spring:
            base_smc += 25
            confluence_factors.append("Wyckoff Spring / Liquidity Sweep confirmed")
        if has_choch:
            base_smc += 15
            confluence_factors.append("Bullish Change of Character (CHoCH)")
        if smc_setup == "DEMAND_OTE_RETEST":
            base_smc += 10
            confluence_factors.append("Demand Order Block OTE 50% discount retest")
        archetype_scores["SMC_SPRING_SWEEP"] = base_smc

    # Archetype 5: RRG Sector Momentum Rotation
    if rrg_quadrant in ("LEADING", "IMPROVING"):
        base_rrg = 45 + int(sector_tailwind * 0.4)
        if rrg_quadrant == "LEADING":
            base_rrg += 10
            confluence_factors.append(f"Sector {sector_name} LEADING Benchmark ({sector_tailwind}/100)")
        else:
            base_rrg += 5
            confluence_factors.append(f"Sector {sector_name} IMPROVING into Leading")
        archetype_scores["RRG_SECTOR_ROTATION"] = base_rrg

    # Volume confluence
    if rvol_20d >= 1.8:
        confluence_factors.append(f"Institutional Volume Surge (RVOL {rvol_20d}x)")
    elif rvol_20d < 0.6 and (is_vcp or squeeze.is_squeeze_on):
        confluence_factors.append("Volume Dry-up / Supply Exhaustion before explosion")

    # Forensic check
    if not forensic_safe:
        confluence_factors.append("⚠️ Forensic Caution: Elevated governance / audit flags")

    # Determine Best Primary Archetype
    primary_archetype = max(archetype_scores, key=archetype_scores.get)
    max_archetype_score = archetype_scores[primary_archetype]

    # If no criteria hit at all, score is low
    if max_archetype_score < 40:
        return None

    # ─────────────────────────────────────────────────────────────────
    # 8. TIMING STATE CLASSIFICATION
    # ─────────────────────────────────────────────────────────────────
    if (rvol_20d >= 1.8 and day_change_pct >= 1.2) or squeeze_status == "FIRED":
        timing_state = "TRIGGER_NOW"
        timing_label = "🔥 Trigger Now"
    elif squeeze.is_squeeze_on or (is_vcp and vcp_tightness <= 5.0 and rvol_20d <= 1.1):
        timing_state = "COILING_IMMINENT"
        timing_label = "⏳ Coiling (1–3d)"
    else:
        timing_state = "PULLBACK_RETEST"
        timing_label = "🎯 Retest Zone"

    # ─────────────────────────────────────────────────────────────────
    # 9. COMPOSITE INFLECTION CONFLUENCE SCORE (0–100)
    # ─────────────────────────────────────────────────────────────────
    score = int(max_archetype_score * 0.50)

    # Volume contribution
    if rvol_20d >= 2.0:
        score += 15
    elif rvol_20d >= 1.4:
        score += 10
    elif rvol_20d < 0.6 and timing_state == "COILING_IMMINENT":
        score += 8  # Dry volume in contraction is bullish

    # Sector contribution
    if rrg_quadrant == "LEADING":
        score += 12
    elif rrg_quadrant == "IMPROVING":
        score += 8

    # Minervini / Stage contribution
    if trend_passed >= 7:
        score += 12
    elif trend_passed >= 5:
        score += 8

    # Forensic bonus / penalty
    if forensic_safe:
        score += 5
    else:
        score -= 20

    score = max(10, min(99, score))

    # ─────────────────────────────────────────────────────────────────
    # 10. DYNAMIC ATR RISK-BOUNDED TRADE TICKET
    # ─────────────────────────────────────────────────────────────────
    # 14-day ATR calculation
    atr = ltp * 0.025
    if len(df) >= 14:
        tr = np.maximum(
            highs[-14:] - lows[-14:],
            np.abs(highs[-14:] - closes[-15:-1]),
        )
        atr = float(np.mean(tr))

    if timing_state == "TRIGGER_NOW":
        entry_price = round(ltp, 2)
        stop_loss = round(max(0.1, ltp - (1.15 * atr)), 2)
    elif is_vcp and vcp_pivot > 0:
        entry_price = round(vcp_pivot, 2)
        stop_loss = round(max(0.1, vcp_pivot - (1.1 * atr)), 2)
    else:
        entry_price = round(ltp, 2)
        stop_loss = round(max(0.1, ltp - (1.25 * atr)), 2)

    risk_per_share = max(0.5, entry_price - stop_loss)
    target_1 = round(entry_price + (2.0 * risk_per_share), 2)
    target_2 = round(entry_price + (3.5 * risk_per_share), 2)
    target_moonshot = round(entry_price + (6.5 * risk_per_share), 2)
    risk_reward = round((target_1 - entry_price) / risk_per_share, 1)

    ticket = {
        "action": "LONG (BUY)",
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "target_moonshot": target_moonshot,
        "risk_reward_ratio": f"1:{risk_reward} (2R) / 1:3.5 (T2) / 1:6.5 (Moonshot)",
        "trailing_rule": "Scale 40-50% at Target 1 (+2R) -> Shift SL to Breakeven (+0.2% costs) -> Trail balance along 20-EMA / Swing Higher Lows.",
        "risk_pts": round(risk_per_share, 2),
        "reward_pts": round(target_2 - entry_price, 2),
    }

    # Labels and catalysts
    labels = {
        "VCP_PIVOT_BREAKOUT": "VCP Volatility Pivot Breakout",
        "TTM_SQUEEZE_EXPLOSION": "TTM Squeeze Volatility Explosion",
        "STAGE_1_TO_2_EXPANSION": "Weinstein Stage 1→2 Markup Expansion",
        "SMC_SPRING_SWEEP": "Smart Money Liquidity Sweep & CHoCH",
        "RRG_SECTOR_ROTATION": "RRG Sector Momentum Leading Rotation",
    }
    archetype_label = labels.get(primary_archetype, primary_archetype)

    catalyst_summary = (
        f"{clean_sym} at high-conviction inflection ({archetype_label} | Timing: {timing_label}). "
        f"Score: {score}/100. Sector {sector_name} ({rrg_quadrant}). "
        f"Confluences: {', '.join(confluence_factors[:3])}."
    )

    if timing_state == "TRIGGER_NOW":
        action = f"Immediate market/limit entry at ₹{entry_price:.2f}. Stop-loss ₹{stop_loss:.2f}. Scale 50% at Target 1 ₹{target_1:.2f}."
    elif timing_state == "COILING_IMMINENT":
        action = f"Stalk pivot ₹{entry_price:.2f}. Place GTT buy stop above pivot or enter early in compression base with tight SL at ₹{stop_loss:.2f}."
    else:
        action = f"Wait for minor pullback to ₹{entry_price:.2f} (Order Block / retest zone) before initiating long position. SL at ₹{stop_loss:.2f}."

    company_name = get_stock_name(clean_sym)
    sector_icon = _get_sector_icon(sector_name)

    return InflectionSetup(
        symbol=clean_sym,
        name=company_name,
        sector=sector_name,
        sector_icon=sector_icon,
        ltp=round(ltp, 2),
        day_change_pct=day_change_pct,
        inflection_score=score,
        primary_archetype=primary_archetype,
        archetype_label=archetype_label,
        timing_state=timing_state,
        timing_label=timing_label,
        weinstein_stage=weinstein_stage,
        vcp_detected=is_vcp,
        vcp_tightness_pct=vcp_tightness,
        vcp_pivot_price=round(vcp_pivot, 2),
        squeeze_state=squeeze_status,
        squeeze_duration=squeeze.squeeze_duration_bars,
        rvol_20d=rvol_20d,
        trend_template_passed=trend_passed,
        sector_tailwind_score=sector_tailwind,
        rrg_quadrant=rrg_quadrant,
        forensic_safe=forensic_safe,
        smc_regime=smc_regime,
        smc_setup=smc_setup,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        target_moonshot=target_moonshot,
        risk_reward_ratio=risk_reward,
        risk_pts=round(risk_per_share, 2),
        reward_pts=round(target_2 - entry_price, 2),
        confluence_factors=confluence_factors,
        catalyst_summary=catalyst_summary,
        suggested_action=action,
        execution_ticket=ticket,
    )


# ── Full Universe Batch Scanner ──────────────────────────────────────


def scan_inflections_universe(
    universe: str = "multibagger_hunters",
    archetype_filter: str = "ALL",
    timing_filter: str = "ALL",
    min_score: int = 50,
    max_results: int = 30,
    exchange: str = "NSE",
    parallel_workers: int = 8,
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
) -> InflectionScanResult:
    """
    Executes a parallel multi-threaded scan across the requested universe,
    identifying high-asymmetry inflection setups and ranking candidates.
    """
    t0 = time.perf_counter()
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1. Resolve Universe Symbols
    if df_cache:
        symbols = list(df_cache.keys())
        u_name = "In-Memory Cached Universe"
    else:
        symbols, universe_desc = resolve_dynamic_universe(universe, max_stocks=120)
        if not symbols:
            symbols = THEMATIC_PRESETS.get("multibagger_hunters", {}).get(
                "symbols", ["TRENT", "DIXON", "HAL", "BEL", "BSE", "COFORGE"]
            )
        u_name = THEMATIC_PRESETS.get(universe.lower(), {}).get("name", universe_desc)

    norm_archetype = archetype_filter.upper().strip()
    norm_timing = timing_filter.upper().strip()

    # 2. Parallel Evaluation
    candidates: list[InflectionSetup] = []

    def _worker(sym: str) -> Optional[InflectionSetup]:
        try:
            cached_df = df_cache.get(sym) if df_cache else None
            return evaluate_single_stock_inflection(sym, df=cached_df, exchange=exchange)
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        future_map = {executor.submit(_worker, s): s for s in symbols}
        for future in concurrent.futures.as_completed(future_map):
            setup = future.result()
            if setup and setup.inflection_score >= min_score:
                candidates.append(setup)

    # 3. Apply Filters
    filtered: list[InflectionSetup] = []
    archetype_counts: dict[str, int] = {}
    timing_counts: dict[str, int] = {}

    for c in candidates:
        # Tally counts
        archetype_counts[c.primary_archetype] = (
            archetype_counts.get(c.primary_archetype, 0) + 1
        )
        timing_counts[c.timing_state] = timing_counts.get(c.timing_state, 0) + 1

        # Check archetype filter
        if norm_archetype != "ALL" and c.primary_archetype != norm_archetype:
            continue

        # Check timing filter
        if norm_timing != "ALL" and c.timing_state != norm_timing:
            continue

        filtered.append(c)

    # 4. Sort descending by Inflection Score
    filtered.sort(key=lambda x: x.inflection_score, reverse=True)
    final_candidates = filtered[:max_results]

    # Sector summary
    sector_counts: dict[str, int] = {}
    for c in final_candidates:
        sector_counts[c.sector] = sector_counts.get(c.sector, 0) + 1

    top_sectors = [
        {"sector": sec, "count": count, "icon": _get_sector_icon(sec)}
        for sec, count in sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    t1 = time.perf_counter()

    return InflectionScanResult(
        universe_id=universe,
        universe_name=u_name,
        archetype_filter=norm_archetype,
        timing_filter=norm_timing,
        total_scanned=len(symbols),
        total_qualified=len(final_candidates),
        candidates=final_candidates,
        archetype_counts=archetype_counts,
        timing_counts=timing_counts,
        top_sectors=top_sectors,
        scan_timestamp=timestamp_str,
        execution_time_seconds=round(t1 - t0, 3),
    )


# ── Universes Preset Metadata ────────────────────────────────────────


def get_inflection_universes() -> list[dict[str, Any]]:
    """Returns available universe presets with metadata and counts."""
    return [
        {
            "id": "multibagger_hunters",
            "name": "🚀 Multibagger Hunters (High ROCE & Growth)",
            "description": "High-growth compounders, Minervini trend candidates, and Kedia/Jhunjhunwala multibaggers.",
            "category": "ALPHA",
            "count": 45,
        },
        {
            "id": "momentum_breakouts",
            "name": "⚡ Momentum & Squeeze Breakouts",
            "description": "Volatility contractions, TTM squeezes coiling, and high RVOL volume expansion candidates.",
            "category": "ALPHA",
            "count": 50,
        },
        {
            "id": "auto_market_aware",
            "name": "🌐 Market-Aware (Top RRG Sectors)",
            "description": "Dynamically selects leading & improving sectors relative to NIFTY 50.",
            "category": "ADAPTIVE",
            "count": 60,
        },
        {
            "id": "nifty50",
            "name": "🏛️ NIFTY 50 (Large Cap Core)",
            "description": "India's top 50 blue chips with institutional derivatives & options liquidity.",
            "category": "BENCHMARK",
            "count": 50,
        },
        {
            "id": "microcap_250",
            "name": "🌱 Microcap 250 (High Asymmetry)",
            "description": "Nifty Microcap 250 emerging leaders before institutional discovery.",
            "category": "HIGH_BETA",
            "count": 80,
        },
        {
            "id": "defence",
            "name": "🛡️ Defence & Aerospace",
            "description": "Indigenization compounders, HAL, BEL, Mazagon, Bharat Dynamics.",
            "category": "THEMATIC",
            "count": 12,
        },
        {
            "id": "it",
            "name": "💻 IT & Digital Engineering",
            "description": "Tier-1 & midcap IT services compounders tracking NASDAQ / global demand.",
            "category": "SECTOR",
            "count": 22,
        },
        {
            "id": "banking",
            "name": "🏦 Banking & Financial Services",
            "description": "Private Banks, PSU Banks, High-ROE NBFCs, and Capital Markets infrastructure.",
            "category": "SECTOR",
            "count": 25,
        },
        {
            "id": "energy",
            "name": "⚡ Energy & Power Transition",
            "description": "Power gen, transmission, renewable green energy, and PSU exploration.",
            "category": "SECTOR",
            "count": 18,
        },
        {
            "id": "pharma",
            "name": "💊 Pharma & Healthcare",
            "description": "CDMO, Active Pharmaceutical Ingredients (API), and domestic formulations.",
            "category": "SECTOR",
            "count": 20,
        },
    ]
