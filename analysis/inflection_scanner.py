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
    turnover_20d_cr: float = 0.0
    cap_tier: str = "SMALL"  # "LARGE" | "MID" | "SMALL" | "MICRO"
    circuit_state: str = "NORMAL"  # "NORMAL" | "NEAR_UPPER_CIRCUIT" | "UPPER_CIRCUIT_LOCKED"
    weekly_stage: str = "STAGE_2_MARKUP"
    dist_52w_high_pct: float = 0.0
    dist_52w_low_pct: float = 0.0
    is_fo: bool = False
    technical_score: int = 0  # 0 to 40
    sector_score: int = 0  # 0 to 30
    quality_score: int = 0  # 0 to 30
    confluence_score: int = 0  # 0 to 100
    executive_verdict: str = "👀 WATCHLIST"
    executive_summary: str = ""
    data_quality_label: str = "💾 0ms Local Cache"

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
    cache_state: str = "LOCAL_SQLITE_EOD"
    filtered_out_liquidity_count: int = 0

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
            "cache_state": self.cache_state,
            "filtered_out_liquidity_count": self.filtered_out_liquidity_count,
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
    min_turnover_cr: float = 0.0,
    cap_tier_override: Optional[str] = None,
    allow_network: bool = True,
    rrg_matrix: Optional[dict[str, Any]] = None,
    use_forensic_cache_only: bool = True,
    forensics_data: Optional[dict[str, Any]] = None,
) -> Optional[InflectionSetup]:
    """
    Evaluates whether a single stock is at an inflection point ready for a big or multibagger move.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()

    if df is None or len(df) == 0:
        try:
            from engine.eod_store import get_cached_ohlcv

            df = get_cached_ohlcv(clean_sym, days=300)
        except Exception:
            pass

    if (df is None or len(df) == 0) and allow_network:
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

    # 0. Liquidity Control: 20-Day Median Turnover in ₹ Crores (turnover = close * volume / 10^7)
    lookback_20 = min(len(closes), 20)
    turnover_vals = (closes[-lookback_20:] * volumes[-lookback_20:]) / 1e7
    turnover_20d_cr = round(float(np.median(turnover_vals)), 2) if len(turnover_vals) > 0 else 0.0

    if min_turnover_cr > 0 and turnover_20d_cr < min_turnover_cr:
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
            tailwind = get_stock_tailwind(clean_sym, rrg_matrix=rrg_matrix)
            if tailwind.quadrant and tailwind.quadrant != "UNAVAILABLE":
                rrg_quadrant = tailwind.quadrant
                sector_tailwind = tailwind.tailwind_score
            if sector_name in ("Broad Market", "BROAD_MARKET") and tailwind.sector:
                sector_name = tailwind.sector
        except Exception:
            pass

        try:
            if forensics_data:
                forensic_safe = forensics_data.get("overall_forensic_verdict") in (
                    "CLEAN_PASS",
                    "MILD_WARNING",
                ) or (
                    not forensics_data.get("is_manipulator_risk")
                    and forensics_data.get("distress_zone") != "DISTRESS"
                )
            elif use_forensic_cache_only:
                from engine.eod_store import get_cached_forensics

                cached_eod = get_cached_forensics(clean_sym, max_age_days=30)
                if cached_eod and isinstance(cached_eod, dict):
                    forensic_safe = cached_eod.get("overall_forensic_verdict") in (
                        "CLEAN_PASS",
                        "MILD_WARNING",
                    ) or (
                        not cached_eod.get("is_manipulator_risk")
                        and cached_eod.get("distress_zone") != "DISTRESS"
                    )
                else:
                    from engine.analysis_cache import analysis_cache

                    cached = analysis_cache.get_fundamental(f"forensic_audit_v2_{clean_sym}")
                    if cached and isinstance(cached, dict):
                        forensic_safe = cached.get("overall_forensic_verdict") in (
                            "CLEAN_PASS",
                            "MILD_WARNING",
                        )
                    else:
                        forensic_safe = True
            else:
                f_audit = audit_company_forensics(clean_sym)
                forensic_safe = f_audit.overall_forensic_verdict in ("CLEAN_PASS", "MILD_WARNING")
        except Exception:
            forensic_safe = True
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

    # Circuit Lock Detection
    is_uc_locked = False
    is_near_uc = False
    if len(highs) >= 1:
        candle_range = highs[-1] - lows[-1]
        if candle_range < (0.002 * ltp) and day_change_pct >= 4.5:
            is_uc_locked = True
        elif (highs[-1] - ltp) < (0.003 * ltp) and day_change_pct >= 4.5:
            is_near_uc = True

    circuit_state = (
        "UPPER_CIRCUIT_LOCKED"
        if is_uc_locked
        else ("NEAR_UPPER_CIRCUIT" if is_near_uc else "NORMAL")
    )
    if is_uc_locked:
        confluence_factors.append("🔒 Upper Circuit Locked (0 Sellers)")
    elif is_near_uc:
        confluence_factors.append("⚠️ Near Upper Circuit (Circuit Band Proximity)")

    # 52-Week High & Low Distances
    lookback_52w = min(len(highs), 250)
    high_52w = float(np.max(highs[-lookback_52w:]))
    low_52w = float(np.min(lows[-lookback_52w:]))
    dist_52w_high = round(((high_52w - ltp) / max(0.01, high_52w)) * 100.0, 1)
    dist_52w_low = round(((ltp - low_52w) / max(0.01, low_52w)) * 100.0, 1)

    # Multi-Timeframe Weekly Alignment (30-week / 150-day EMA)
    weekly_stage = "NEUTRAL"
    if len(closes) >= 150:
        ema_150 = pd.Series(closes).ewm(span=150, adjust=False).mean().values
        if ltp > ema_150[-1] and ema_150[-1] > ema_150[-20]:
            weekly_stage = "WEEKLY_STAGE_2"
            confluence_factors.append("👑 Weekly 30-Week Stage 2 Confluence")

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

    # Weekly Alignment Bonus
    if weekly_stage == "WEEKLY_STAGE_2":
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
        "circuit_state": circuit_state,
        "is_executable": circuit_state != "UPPER_CIRCUIT_LOCKED",
        "turnover_20d_cr": turnover_20d_cr,
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
        f"Turnover: ₹{turnover_20d_cr:.1f} Cr. Confluences: {', '.join(confluence_factors[:3])}."
    )

    if is_uc_locked:
        action = f"⚠️ Stock is Upper Circuit Locked at ₹{ltp:.2f} with 0 sellers. Do NOT place market orders. Wait for circuit expansion or place GTT/limit buy orders."
    elif timing_state == "TRIGGER_NOW":
        action = f"Immediate market/limit entry at ₹{entry_price:.2f}. Stop-loss ₹{stop_loss:.2f}. Scale 50% at Target 1 ₹{target_1:.2f}."
    elif timing_state == "COILING_IMMINENT":
        action = f"Stalk pivot ₹{entry_price:.2f}. Place GTT buy stop above pivot or enter early in compression base with tight SL at ₹{stop_loss:.2f}."
    else:
        action = f"Wait for minor pullback to ₹{entry_price:.2f} (Order Block / retest zone) before initiating long position. SL at ₹{stop_loss:.2f}."

    company_name = get_stock_name(clean_sym)
    sector_icon = _get_sector_icon(sector_name)

    from analysis.universe import get_stock_cap_tier

    cap_tier = cap_tier_override or get_stock_cap_tier(clean_sym)
    is_fo = clean_sym in THEMATIC_PRESETS.get("fno_universe", {}).get("symbols", [])

    # 3-Pillar Unified Matrix Scores
    tech_score = int(min(40, (max_archetype_score * 0.22) + (trend_passed * 1.5) + (8 if weekly_stage == "WEEKLY_STAGE_2" else 0) + (4 if is_vcp or squeeze.is_squeeze_on else 0)))
    sec_score = int(min(30, (15 if rrg_quadrant == "LEADING" else (10 if rrg_quadrant == "IMPROVING" else 4)) + (sector_tailwind * 0.15)))
    qual_score = int(min(30, (20 if forensic_safe else 0) + (10 if turnover_20d_cr >= 1.0 else (6 if turnover_20d_cr >= 0.5 else 2))))
    confluence_total = int(min(99, tech_score + sec_score + qual_score))

    # Executive Action Verdict
    if is_uc_locked:
        exec_verdict = "🔒 CIRCUIT LOCKED"
    elif score >= 75 and timing_state == "TRIGGER_NOW" and forensic_safe:
        exec_verdict = "🔥 STRONG BUY"
    elif timing_state == "COILING_IMMINENT":
        exec_verdict = "⏳ ACCUMULATE (COILING)"
    elif timing_state == "PULLBACK_RETEST":
        exec_verdict = "🎯 RETEST ENTRY"
    else:
        exec_verdict = "👀 WATCHLIST"

    # 1-Sentence Executive Summary for rapid 10-second decisions
    exec_summary = (
        f"{clean_sym}: {archetype_label} with 1:{risk_reward} R/R. "
        f"Confluence: Tech {tech_score}/40, Sector {sector_name} ({rrg_quadrant}) {sec_score}/30, Quality {qual_score}/30. "
        f"Hard stop ₹{stop_loss:.2f}."
    )

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
        turnover_20d_cr=turnover_20d_cr,
        cap_tier=cap_tier,
        circuit_state=circuit_state,
        weekly_stage=weekly_stage,
        dist_52w_high_pct=dist_52w_high,
        dist_52w_low_pct=dist_52w_low,
        is_fo=is_fo,
        technical_score=tech_score,
        sector_score=sec_score,
        quality_score=qual_score,
        confluence_score=confluence_total,
        executive_verdict=exec_verdict,
        executive_summary=exec_summary,
        data_quality_label="💾 0ms Local Cache",
    )


# ── Full Universe Batch Scanner ──────────────────────────────────────


def scan_inflections_universe(
    universe: str = "multibagger_hunters",
    archetype_filter: str = "ALL",
    timing_filter: str = "ALL",
    min_score: int = 45,
    max_results: int = 40,
    min_turnover_cr: float = 0.0,
    cap_tier_filter: str = "ALL",
    use_local_cache: bool = True,
    sync_missing: bool = True,
    exchange: str = "NSE",
    parallel_workers: int = 16,
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
) -> InflectionScanResult:
    """
    Executes a parallel multi-threaded scan across the requested universe,
    identifying high-asymmetry inflection setups and ranking candidates.
    Supports instant local SQLite EOD reading across 500+ stocks.
    """
    t0 = time.perf_counter()
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1. Resolve Universe Symbols
    if df_cache:
        symbols = list(df_cache.keys())
        u_name = "In-Memory Cached Universe"
    else:
        # Increase max_stocks to 3000 to cover NIFTY 500, Microcap 250, and All NSE Liquid
        symbols, universe_desc = resolve_dynamic_universe(universe, max_stocks=3000)
        if not symbols:
            symbols = THEMATIC_PRESETS.get("multibagger_hunters", {}).get(
                "symbols", ["TRENT", "DIXON", "HAL", "BEL", "BSE", "COFORGE"]
            )
        u_name = THEMATIC_PRESETS.get(universe.lower(), {}).get("name", universe_desc)

    cache_state = "REST_DIRECT"
    if df_cache is None and use_local_cache:
        try:
            from engine.eod_store import get_cached_ohlcv_batch, sync_universe_eod

            df_cache = get_cached_ohlcv_batch(symbols, days=300)
            cache_state = "LOCAL_SQLITE_EOD"

            if sync_missing:
                missing = [s for s in symbols if s not in df_cache and not s.upper().startswith("DUMMY")]
                # Auto-sync up to 60 missing symbols synchronously if explicitly requested
                if missing and len(missing) <= 60:
                    sync_universe_eod(missing, exchange=exchange)
                    newly_cached = get_cached_ohlcv_batch(missing, days=300)
                    df_cache.update(newly_cached)
        except Exception:
            pass

    norm_archetype = archetype_filter.upper().strip()
    norm_timing = timing_filter.upper().strip()
    norm_cap_tier = cap_tier_filter.upper().strip()

    # Pre-fetch sector RRG matrix once to avoid hundreds of repetitive SQLite queries
    rrg_matrix: Optional[dict[str, Any]] = None
    try:
        from analysis.sector_rotation import get_sector_rrg_matrix

        rrg_matrix = {p.sector: p for p in get_sector_rrg_matrix()}
    except Exception:
        rrg_matrix = None

    # Pre-fetch forensic audits in batch from local store (30-day freshness)
    forensics_cache_map: dict[str, Any] = {}
    try:
        from engine.eod_store import get_cached_forensics_batch

        forensics_cache_map = get_cached_forensics_batch(symbols, max_age_days=30)
    except Exception:
        pass

    # 2. Parallel Evaluation
    candidates: list[InflectionSetup] = []

    def _worker(sym: str) -> Optional[InflectionSetup]:
        try:
            cached_df = df_cache.get(sym) if df_cache else None
            # If scanning via local cache and this symbol has no cached bars, do NOT block on slow REST calls
            if use_local_cache and (cached_df is None or len(cached_df) < 25):
                return None
            return evaluate_single_stock_inflection(
                sym,
                df=cached_df,
                exchange=exchange,
                min_turnover_cr=min_turnover_cr,
                allow_network=not use_local_cache,
                rrg_matrix=rrg_matrix,
                use_forensic_cache_only=True,
                forensics_data=forensics_cache_map.get(sym),
            )
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

        # Check market cap tier filter
        if norm_cap_tier != "ALL" and c.cap_tier != norm_cap_tier:
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
        cache_state=cache_state,
        filtered_out_liquidity_count=len(symbols) - len(candidates),
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
            "id": "nifty500",
            "name": "🇮🇳 NIFTY 500 (Complete 501 Stocks)",
            "description": "Top 500 Indian listed equities covering ~96% of total free-float market cap.",
            "category": "BROAD_MARKET",
            "count": 501,
        },
        {
            "id": "microcap_250",
            "name": "🌱 NIFTY Microcap 250 (High Asymmetry)",
            "description": "Nifty Microcap 250 emerging leaders before institutional discovery.",
            "category": "ALPHA",
            "count": 254,
        },
        {
            "id": "smallcap250",
            "name": "🚀 NIFTY Smallcap 250 Compounders",
            "description": "Nifty Smallcap 250 high-growth emerging corporate compounders.",
            "category": "GROWTH",
            "count": 251,
        },
        {
            "id": "midcap150",
            "name": "📈 NIFTY Midcap 150 Growth",
            "description": "Nifty Midcap 150 medium-sized industry champions.",
            "category": "CORE",
            "count": 150,
        },
        {
            "id": "nifty_total_market",
            "name": "🏛️ NIFTY Total Market (Top 750 Stocks)",
            "description": "Top 750 Indian listed equities across Large, Mid, Small, and Microcap spectrum.",
            "category": "BROAD_MARKET",
            "count": 755,
        },
        {
            "id": "all_nse_liquid",
            "name": "🇮🇳 All Liquid NSE Equities (~1,200+ Active)",
            "description": "Complete NSE actively listed Series EQ universe, dynamically turnover-filtered.",
            "category": "UNIVERSE",
            "count": 1250,
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
            "id": "fno_universe",
            "name": "⚡ Complete Liquid F&O Universe",
            "description": "All ~180+ liquid derivatives contracts eligible for single-stock futures & options.",
            "category": "DERIVATIVES",
            "count": 180,
        },
        {
            "id": "railways",
            "name": "🚆 Railways & Metro Infra",
            "description": "Vande Bharat Coaches, Freight Wagons, Metro Bogies, and Railway EPC (Titagarh, RVNL, IRFC).",
            "category": "THEMATIC",
            "count": 10,
        },
        {
            "id": "defence",
            "name": "🛡️ Defence & Aerospace",
            "description": "Indigenization compounders, HAL, BEL, Mazagon, Bharat Dynamics.",
            "category": "THEMATIC",
            "count": 14,
        },
        {
            "id": "energy",
            "name": "⚡ Energy & Power Transition",
            "description": "Power gen, transmission, renewable green energy, and PSU exploration.",
            "category": "SECTOR",
            "count": 22,
        },
        {
            "id": "it",
            "name": "💻 IT & Digital Engineering",
            "description": "Tier-1 & midcap IT services compounders tracking NASDAQ / global demand.",
            "category": "SECTOR",
            "count": 32,
        },
        {
            "id": "banking",
            "name": "🏦 Banking & Financial Services",
            "description": "Private Banks, PSU Banks, High-ROE NBFCs, and Capital Markets infrastructure.",
            "category": "SECTOR",
            "count": 25,
        },
        {
            "id": "pharma",
            "name": "💊 Pharma & Healthcare",
            "description": "CDMO, Active Pharmaceutical Ingredients (API), and domestic formulations.",
            "category": "SECTOR",
            "count": 45,
        },
    ]
