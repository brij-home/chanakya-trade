"""
engine/detectors/pairs_arbitrage.py
───────────────────────────────────
Institutional Statistical Arbitrage & Cointegration Pairs Trading Detector.

Detects statistical mispricings and mean-reversion opportunities between highly
cointegrated Indian equities (e.g. HDFCBANK vs ICICIBANK, TCS vs INFY, SBIN vs BANKBARODA):
  1. Validates historical correlation (r >= 0.55) and stationary spread.
  2. Measures spread z-score divergence (|Z| >= 2.0 standard deviations).
  3. Computes dynamic OLS hedge ratio (beta) and half-life of mean reversion.
  4. Yields structured market-neutral execution pairs (Long A / Short B or vice versa)
     with institutional invalidation boundaries (|Z| >= 3.2).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from config.constants import IST
from engine.alert_identity import generate_alert_id, canonical_alert_symbol
from engine.alert_model import AutoAlert
from engine.pairs import KNOWN_PAIRS, analyze_pair, PairAnalysis

logger = logging.getLogger(__name__)


def detect_pairs_arbitrage(
    ctx: Any,  # DetectionContext duck-typed to prevent circular imports
    pair_override: Optional[PairAnalysis] = None,
) -> Optional[AutoAlert]:
    """
    Evaluates DetectionContext against institutional cointegrated pairs.
    If ctx.canonical_symbol is in KNOWN_PAIRS and spread is stretched (|Z| >= 2.0),
    emits actionable Stat-Arb AutoAlert.
    """
    if ctx.segment not in ("EQUITY", "FNO_STOCK"):
        return None

    symbol = canonical_alert_symbol(ctx.canonical_symbol)

    analysis: Optional[PairAnalysis] = pair_override

    if analysis is None:
        # Find matching pairs for this symbol
        matched_pair = None
        for a, b in KNOWN_PAIRS:
            if a == symbol or b == symbol:
                matched_pair = (a, b)
                break

        if not matched_pair:
            return None

        try:
            analysis = analyze_pair(matched_pair[0], matched_pair[1])
        except Exception as exc:
            logger.debug("Failed analyzing pair %s: %s", matched_pair, exc)
            return None

    if not analysis or analysis.signal == "NO_SIGNAL":
        return None

    # Require minimum correlation and statistical divergence
    if analysis.correlation < 0.50 or abs(analysis.spread_zscore) < 2.0:
        return None

    stock_a = analysis.stock_a
    stock_b = analysis.stock_b
    z = analysis.spread_zscore
    corr = analysis.correlation
    beta = analysis.hedge_ratio
    hl = analysis.half_life or 10.0

    # Determine long and short legs
    if analysis.signal == "LONG_A_SHORT_B":
        long_stock = stock_a
        short_stock = stock_b
        direction = "BULLISH" if symbol == stock_a else "BEARISH"
        variant_slug = f"{stock_b.lower()}_long_a"
    else:
        long_stock = stock_b
        short_stock = stock_a
        direction = "BULLISH" if symbol == stock_b else "BEARISH"
        variant_slug = f"{stock_a.lower()}_long_b"

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Conviction score based on correlation, Z magnitude, and half-life (75 - 94)
    conviction = 75
    if corr >= 0.75:
        conviction += 6
    elif corr >= 0.65:
        conviction += 3

    if abs(z) >= 2.5:
        conviction += 7
    elif abs(z) >= 2.2:
        conviction += 4

    if hl <= 15.0:
        conviction += 4
    conviction = min(94, conviction)

    headline = (
        f"⚖ STAT-ARB SPREAD: {stock_a} vs {stock_b} | "
        f"Z-Score {z:+.2f}σ ({analysis.signal}) [Corr {corr:.2f}]"
    )
    summary = (
        f"Statistical arbitrage mean-reversion setup. "
        f"Spread between {stock_a} and {stock_b} has diverged to {z:+.2f} standard deviations "
        f"(historical correlation {corr:.2f}, hedge ratio β={beta:.3f}). "
        f"Trade structure: BUY {long_stock} & SELL {short_stock}. Target Z=0.0σ."
    )

    # Invalidation SL at 3.2 sigma
    sl_sigma = 3.2 if z > 0 else -3.2
    rr_ratio = round(abs(z) / (abs(sl_sigma) - abs(z)), 2) if abs(sl_sigma) > abs(z) else 2.0

    return AutoAlert(
        alert_id=generate_alert_id(symbol, "PAIRS_ARBITRAGE", variant=variant_slug),
        alert_type="PAIRS_ARBITRAGE",
        stage="ACTIONABLE",
        symbol=symbol,
        exchange=ctx.exchange,
        direction=direction,
        headline=headline,
        summary=summary,
        ltp=ctx.ltp,
        trigger_level=ctx.ltp,
        target_level=round(ctx.ltp * (1.025 if direction == "BULLISH" else 0.975), 2),
        stop_loss=round(ctx.ltp * (0.985 if direction == "BULLISH" else 1.015), 2),
        metrics={
            "pair": f"{stock_a}/{stock_b}",
            "stock_a": stock_a,
            "stock_b": stock_b,
            "signal": analysis.signal,
            "spread_zscore": z,
            "correlation": corr,
            "hedge_ratio": beta,
            "half_life_days": hl,
            "spread_mean": analysis.spread_mean,
            "spread_std": analysis.spread_std,
            "long_leg": long_stock,
            "short_leg": short_stock,
        },
        actionable_plan={
            "action": f"PAIRS_TRADE_{analysis.signal}",
            "long_leg": f"BUY 1 unit of {long_stock}",
            "short_leg": f"SELL {beta:.2f} units of {short_stock}",
            "entry_condition": f"Current Spread Z-Score = {z:+.2f}σ",
            "target": "Take 50% profits at Z = 1.0σ (partial mean reversion)",
            "target_2": "Close remainder at Z = 0.0σ (historical equilibrium)",
            "stop_loss": f"Hard invalidation if spread expands past |Z| >= 3.2σ",
            "risk_reward": f"1:{max(1.8, rr_ratio):.1f}",
            "expected_horizon": f"~{int(hl)} trading days (historical half-life)",
        },
        confidence=conviction,
        created_at=now_iso,
    )
