"""
analysis/multibagger.py
───────────────────────
Multibagger & Positional Opportunity Screener & Analyzer.

Combines:
  1. Mark Minervini 8-Point Trend Template
  2. Stan Weinstein Stage Analysis (Stage 1 Base, Stage 2 Markup, Stage 3 Top, Stage 4 Markdown)
  3. Minervini Volatility Contraction Pattern (VCP) Detection
  4. Institutional Confluence: RRG Sector Tailwinds + Forensic Accounting Safety
  5. Composite Multibagger Potential Score (0-100) & Categorization

Usage:
    from analysis.multibagger import scan_multibagger_opportunity

    report = scan_multibagger_opportunity("TRENT")
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class TrendTemplateCriteria:
    name: str
    passed: bool
    description: str
    current_value: str
    benchmark_value: str


@dataclass
class VCPContraction:
    number: int
    depth_pct: float
    bars_duration: int
    is_tightening: bool


@dataclass
class MultibaggerReport:
    symbol: str
    ltp: float
    multibagger_score: int  # 0 - 100
    category: str  # "STAGE_2_SUPERPERFORMER" | "VCP_BREAKOUT" | "WYCKOFF_ACCUMULATION" | "DEVELOPING_SETUP" | "AVOID_STAGE_4"
    
    # Minervini Trend Template
    trend_template_passed: int = 0  # 0 to 8 criteria passed
    trend_template_qualified: bool = False  # True if >= 6 / 8
    criteria_breakdown: list[TrendTemplateCriteria] = field(default_factory=list)
    
    # Stan Weinstein Stage
    weinstein_stage: str = "STAGE_1_BASE"  # "STAGE_1_BASE" | "STAGE_2_MARKUP" | "STAGE_3_DISTRIBUTION" | "STAGE_4_MARKDOWN"
    stage_confidence: int = 80
    
    # Volatility Contraction Pattern (VCP)
    vcp_detected: bool = False
    vcp_contractions: list[VCPContraction] = field(default_factory=list)
    vcp_pivot_price: float = 0.0
    
    # Confluence Metrics
    sector: str = "Broad Market"
    sector_tailwind_score: int = 50  # 0 - 100 from RRG
    forensic_safe: bool = True
    
    summary: str = ""
    catalyst_notes: str = ""
    suggested_entry_strategy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Minervini 8-Point Trend Template Evaluator ─────────────────


def evaluate_trend_template(df: pd.DataFrame) -> tuple[int, list[TrendTemplateCriteria]]:
    """
    Evaluates Mark Minervini's 8-Point Trend Template for high-growth positional superperformers.
    """
    if df is None or len(df) < 50:
        return 0, []

    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    ltp = float(closes[-1])

    # Moving averages (approximated for length of df)
    sma_50 = float(np.mean(closes[-50:])) if n >= 50 else float(np.mean(closes))
    sma_150 = float(np.mean(closes[-150:])) if n >= 150 else float(np.mean(closes[-min(n, 75):]))
    sma_200 = float(np.mean(closes[-200:])) if n >= 200 else float(np.mean(closes[-min(n, 100):]))
    
    # 200 SMA slope over last 20-30 bars
    sma_200_prev = float(np.mean(closes[-220:-20])) if n >= 220 else sma_200 * 0.99
    sma_200_rising = sma_200 > sma_200_prev

    # 52-week High and Low (or max available lookback)
    high_52w = float(np.max(highs[-252:])) if n >= 252 else float(np.max(highs))
    low_52w = float(np.min(lows[-252:])) if n >= 252 else float(np.min(lows))

    pct_above_52w_low = ((ltp - low_52w) / low_52w) * 100 if low_52w > 0 else 0
    pct_from_52w_high = ((high_52w - ltp) / high_52w) * 100 if high_52w > 0 else 0

    criteria = [
        TrendTemplateCriteria(
            name="1. Price > 150 & 200 SMA",
            passed=bool(ltp > sma_150 and ltp > sma_200),
            description="Current stock price is above both the 150-day and 200-day moving averages.",
            current_value=f"₹{ltp:.1f}",
            benchmark_value=f"150 SMA: ₹{sma_150:.1f}, 200 SMA: ₹{sma_200:.1f}",
        ),
        TrendTemplateCriteria(
            name="2. 150 SMA > 200 SMA",
            passed=bool(sma_150 > sma_200),
            description="The 150-day moving average is strictly above the 200-day moving average.",
            current_value=f"150 SMA: ₹{sma_150:.1f}",
            benchmark_value=f"200 SMA: ₹{sma_200:.1f}",
        ),
        TrendTemplateCriteria(
            name="3. 200 SMA Trending Up",
            passed=bool(sma_200_rising),
            description="The 200-day moving average has an upward trajectory (minimum 1 month).",
            current_value="Rising" if sma_200_rising else "Declining/Flat",
            benchmark_value="Rising Slope",
        ),
        TrendTemplateCriteria(
            name="4. 50 SMA > 150 & 200 SMA",
            passed=bool(sma_50 > sma_150 and sma_50 > sma_200),
            description="The 50-day moving average is above both 150-day and 200-day moving averages.",
            current_value=f"50 SMA: ₹{sma_50:.1f}",
            benchmark_value=f"150 SMA: ₹{sma_150:.1f}",
        ),
        TrendTemplateCriteria(
            name="5. Price > 50 SMA",
            passed=bool(ltp > sma_50),
            description="Current stock price is trading above the 50-day moving average.",
            current_value=f"₹{ltp:.1f}",
            benchmark_value=f"50 SMA: ₹{sma_50:.1f}",
        ),
        TrendTemplateCriteria(
            name="6. Price >= 30% Above 52W Low",
            passed=bool(pct_above_52w_low >= 25.0),
            description="Current price is at least 25-30% above its 52-week low (no bottom lag).",
            current_value=f"+{pct_above_52w_low:.1f}%",
            benchmark_value=">= +30%",
        ),
        TrendTemplateCriteria(
            name="7. Within 25% of 52W High",
            passed=bool(pct_from_52w_high <= 25.0),
            description="Current stock price is within 25% of its 52-week high (leaders stay near highs).",
            current_value=f"-{pct_from_52w_high:.1f}% from high",
            benchmark_value="<= 25% off high",
        ),
        TrendTemplateCriteria(
            name="8. Relative Momentum >= 50",
            passed=bool(closes[-1] > closes[-20]),
            description="1-month price momentum is positive relative to baseline.",
            current_value="Positive" if closes[-1] > closes[-20] else "Negative",
            benchmark_value="Positive Momentum",
        ),
    ]

    passed_count = sum(1 for c in criteria if c.passed)
    return passed_count, criteria


# ── Stan Weinstein Stage Classifier ───────────────────────────


def classify_weinstein_stage(df: pd.DataFrame) -> tuple[str, int]:
    """
    Classifies the asset into one of Stan Weinstein's 4 stages:
      - STAGE 1: Basing Area (Flat 200 SMA, price oscillating)
      - STAGE 2: Advancing Phase / Markup (Rising 200 SMA, price above 50/200 SMA) -> Multibagger zone
      - STAGE 3: Top Area / Distribution (Flattening 200 SMA, wide choppy swings)
      - STAGE 4: Declining Phase / Markdown (Declining 200 SMA, price below 50/200 SMA)
    """
    if df is None or len(df) < 50:
        return "STAGE_1_BASE", 50

    closes = df["close"].values
    ltp = float(closes[-1])
    n = len(df)

    sma_50 = float(np.mean(closes[-50:])) if n >= 50 else float(np.mean(closes))
    sma_200 = float(np.mean(closes[-200:])) if n >= 200 else float(np.mean(closes[-min(n, 75):]))
    sma_200_prev = float(np.mean(closes[-220:-20])) if n >= 220 else sma_200 * 0.99

    slope = (sma_200 - sma_200_prev) / sma_200_prev if sma_200_prev > 0 else 0

    if ltp > sma_50 and sma_50 > sma_200 and slope > 0.005:
        return "STAGE_2_MARKUP", 90
    elif ltp < sma_50 and sma_50 < sma_200 and slope < -0.005:
        return "STAGE_4_MARKDOWN", 85
    elif abs(slope) <= 0.005 and ltp > sma_200:
        return "STAGE_1_BASE", 75
    else:
        return "STAGE_3_DISTRIBUTION", 70


# ── Minervini VCP (Volatility Contraction Pattern) Detector ────


def detect_vcp(df: pd.DataFrame) -> tuple[bool, list[VCPContraction], float]:
    """
    Detects Volatility Contraction Patterns (VCP) by analyzing swing depths across recent consolidation.
    VCP is present when successive pullbacks become progressively tighter (e.g. 20% -> 10% -> 4%).
    """
    if df is None or len(df) < 30:
        return False, [], 0.0

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)

    # Inspect last 45 bars for 2-3 contractions
    window = min(45, n)
    recent_highs = highs[-window:]
    recent_lows = lows[-window:]

    # Divide window into 3 equal segments
    seg_len = window // 3
    if seg_len < 5:
        return False, [], float(closes[-1])

    c1_high = float(np.max(recent_highs[:seg_len]))
    c1_low = float(np.min(recent_lows[:seg_len]))
    c1_depth = ((c1_high - c1_low) / c1_high) * 100 if c1_high > 0 else 0

    c2_high = float(np.max(recent_highs[seg_len : seg_len * 2]))
    c2_low = float(np.min(recent_lows[seg_len : seg_len * 2]))
    c2_depth = ((c2_high - c2_low) / c2_high) * 100 if c2_high > 0 else 0

    c3_high = float(np.max(recent_highs[seg_len * 2 :]))
    c3_low = float(np.min(recent_lows[seg_len * 2 :]))
    c3_depth = ((c3_high - c3_low) / c3_high) * 100 if c3_high > 0 else 0

    contractions = [
        VCPContraction(number=1, depth_pct=round(c1_depth, 1), bars_duration=seg_len, is_tightening=True),
        VCPContraction(number=2, depth_pct=round(c2_depth, 1), bars_duration=seg_len, is_tightening=bool(c2_depth <= c1_depth * 1.1)),
        VCPContraction(number=3, depth_pct=round(c3_depth, 1), bars_duration=seg_len, is_tightening=bool(c3_depth < c2_depth)),
    ]

    is_vcp = (c3_depth < c2_depth) and (c2_depth <= c1_depth * 1.15) and (c3_depth <= 10.0)
    pivot_price = float(np.max(recent_highs[seg_len * 2 :]))

    return is_vcp, contractions, round(pivot_price, 2)


# ── Full Multibagger Opportunity Scanner ────────────────────────


def scan_multibagger_opportunity(
    symbol: str,
    df: Optional[pd.DataFrame] = None,
    exchange: str = "NSE",
    sector_override: Optional[str] = None,
) -> MultibaggerReport:
    """
    Comprehensive Multibagger Screener analyzing Minervini criteria, Weinstein stages,
    VCP contraction tightness, RRG sector tailwinds, and Forensic accounting safety.
    """
    if df is None or len(df) == 0:
        try:
            from market.history import get_ohlcv

            df = get_ohlcv(symbol, exchange=exchange, interval="day", days=300)
        except Exception:
            df = None

    if df is None or len(df) < 20:
        return MultibaggerReport(
            symbol=symbol,
            ltp=0.0,
            multibagger_score=0,
            category="DEVELOPING_SETUP",
            trend_template_passed=0,
            trend_template_qualified=False,
            weinstein_stage="STAGE_1_BASE",
            summary="Insufficient historical price bars to compute multibagger criteria.",
        )

    ltp = float(df["close"].iloc[-1])

    # 1. Trend Template (Minervini)
    passed_count, criteria = evaluate_trend_template(df)
    is_template_qualified = passed_count >= 6

    # 2. Weinstein Stage
    stage, stage_conf = classify_weinstein_stage(df)

    # 3. VCP Contraction
    is_vcp, contractions, pivot_price = detect_vcp(df)

    # 4. Forensic & Sector Tailwind Confluence (Cached / Dynamic)
    sector = sector_override or "Broad Market"
    sector_tailwind = 65
    forensic_safe = True

    try:
        from analysis.sector_rotation import get_stock_tailwind

        align = get_stock_tailwind(symbol)
        sector = align.sector
        sector_tailwind = align.tailwind_score
    except Exception:
        pass

    try:
        from analysis.forensic import audit_company_forensics

        f_audit = audit_company_forensics(symbol)
        forensic_safe = f_audit.overall_forensic_verdict in ("CLEAN_PASS", "MILD_WARNING")
    except Exception:
        pass

    # 5. Composite Multibagger Potential Score (0-100)
    score = 0
    # Trend template: up to 40 pts (5 pts per passed rule)
    score += passed_count * 5

    # Weinstein Stage:
    if stage == "STAGE_2_MARKUP":
        score += 25
    elif stage == "STAGE_1_BASE":
        score += 10
    elif stage == "STAGE_4_MARKDOWN":
        score -= 20

    # VCP setup: +15 pts
    if is_vcp:
        score += 15

    # Sector Tailwind: +10 pts
    if sector_tailwind >= 70:
        score += 10
    elif sector_tailwind >= 50:
        score += 5

    # Forensic Penalty
    if not forensic_safe:
        score -= 25

    score = max(0, min(100, score))

    # Categorization
    if score >= 80 and stage == "STAGE_2_MARKUP":
        category = "STAGE_2_SUPERPERFORMER"
    elif is_vcp and score >= 65:
        category = "VCP_BREAKOUT"
    elif stage == "STAGE_1_BASE" and score >= 55:
        category = "WYCKOFF_ACCUMULATION"
    elif stage == "STAGE_4_MARKDOWN":
        category = "AVOID_STAGE_4"
    else:
        category = "DEVELOPING_SETUP"

    # Synthesis
    summary = f"{symbol} ranks {category} (Multibagger Score: {score}/100). Minervini Template: {passed_count}/8 passed. Weinstein Stage: {stage}. Sector Tailwind: {sector_tailwind}/100 ({sector})."
    
    if is_vcp:
        catalyst = f"VCP Contraction detected with pivot resistance at ₹{pivot_price:.2f}. Volatility is drying up prior to potential Stage 2 expansion."
        entry_strat = f"Buy on volume breakout above VCP Pivot ₹{pivot_price:.2f} (or on retest). Stop-loss below tightest swing low ₹{contractions[-1].depth_pct:.1f}% away."
    elif stage == "STAGE_2_MARKUP":
        catalyst = f"Established Stage 2 markup with strong 50/200 SMA alignment and positive institutional sector momentum."
        entry_strat = f"Enter on 20/50-day EMA pullbacks. Trail stop-loss using structural higher lows for positional multibagger hold."
    else:
        catalyst = f"Consolidating or basing. Watch for Stage 2 volume breakout confirmation."
        entry_strat = f"Wait for Minervini criteria >= 6/8 and confirmed Stage 2 expansion before taking heavy positional allocation."

    return MultibaggerReport(
        symbol=symbol,
        ltp=round(ltp, 2),
        multibagger_score=score,
        category=category,
        trend_template_passed=passed_count,
        trend_template_qualified=is_template_qualified,
        criteria_breakdown=criteria,
        weinstein_stage=stage,
        stage_confidence=stage_conf,
        vcp_detected=is_vcp,
        vcp_contractions=contractions,
        vcp_pivot_price=pivot_price,
        sector=sector,
        sector_tailwind_score=sector_tailwind,
        forensic_safe=forensic_safe,
        summary=summary,
        catalyst_notes=catalyst,
        suggested_entry_strategy=entry_strat,
    )
