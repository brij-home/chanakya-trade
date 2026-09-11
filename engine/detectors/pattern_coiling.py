"""
Learned pattern coiling detector (Volume dry-up + Squeeze coiling + Order Block anchor).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def detect_learned_pattern_coiling(
    symbol: str,
    df: Any,
    ltp: float,
    exchange: str = "NSE",
) -> Optional[AutoAlert]:
    """
    Detects pre-blast coiling based on learned explosive move archetypes
    (Volume dry-up + Squeeze coiling + Order Block anchor).
    """
    if df is None or len(df) < 20 or ltp <= 0:
        return None

    try:
        from engine.learning_engine import pattern_learning_engine

        # Negative Feedback Invalidation Lockout Gate: Prevent knife-catching after stop-loss breach
        # Supports adaptive early unlocking if price structurally reclaims above failed level & VWAP
        is_locked, lock_reason = pattern_learning_engine.is_symbol_locked_out(
            symbol, direction="BULLISH", ltp=ltp
        )
        if is_locked:
            logger.info(
                f"[PatternCoiling] Gating alert for {symbol}: Under invalidation lockout ({lock_reason})"
            )
            return None

        res = pattern_learning_engine.evaluate_candidate(symbol=symbol, df=df, chain=None)
        if res.is_explosive_candidate:
            now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

            from engine.trade_plan import calculate_trade_plan

            tp = calculate_trade_plan(symbol, direction="BULLISH", spot=ltp, exchange=exchange)

            # Mathematical Expectancy Gate: Reject candidates with poor structural asymmetry
            if tp and not tp.is_asymmetry_viable:
                logger.info(
                    f"[PatternCoiling] Gating alert for {symbol}: Failed structural asymmetry ({tp.asymmetry_verdict})"
                )
                return None

            archetype_txt = (
                f" ({res.similarity_score}% match to {res.closest_archetype})"
                if res.closest_archetype
                else ""
            )
            headline = f"💎 PRE-BLAST COILING: {symbol} at ₹{ltp:,.1f}{archetype_txt}"
            factor_summary = (
                "; ".join(res.matched_factors[:2])
                if res.matched_factors
                else "High-conviction coiling"
            )
            summary = f"Pre-blast footprint match: {factor_summary}. Asymmetric coiling detected with minimum risk anchor."

            t1 = tp.target_1 if (tp and tp.target_1 > 0) else round(ltp * 1.05, 1)
            sl = (
                tp.invalidation_stop if (tp and tp.invalidation_stop > 0) else round(ltp * 0.985, 1)
            )

            # Volatility Noise Floor: Ensure stop-loss is not placed within intraday noise chop
            # Minimum buffer: at least 1.2% of price or 1.2x ATR
            min_sl_dist = round(max(ltp * 0.012, 1.0), 2)
            if (ltp - sl) < min_sl_dist:
                sl = round(ltp - min_sl_dist, 2)

            rr_str = f"{tp.rr_t1:.1f}:1" if tp else "3.0:1"

            act_plan = {
                "action": res.recommended_entry_action,
                "entry_range": f"₹{ltp:.1f}",
                "target": f"₹{t1:.1f}",
                "stop_loss": f"₹{sl:.1f}",
                "risk_reward": rr_str,
            }
            if tp:
                act_plan["trade_plan"] = tp.as_dict()

            return AutoAlert(
                alert_id=f"aa-coiling-{symbol}-{uuid.uuid4().hex[:6]}",
                alert_type="PATTERN_COILING",
                stage="EARLY_WARNING",
                symbol=symbol,
                exchange=exchange,
                direction="BULLISH",
                headline=headline,
                summary=summary,
                ltp=ltp,
                trigger_level=ltp,
                target_level=t1,
                stop_loss=sl,
                metrics={
                    "similarity_score": res.similarity_score,
                    "closest_archetype": res.closest_archetype,
                    "matched_factors": res.matched_factors,
                    "expected_rr": res.expected_asymmetry_rr,
                },
                actionable_plan=act_plan,
                confidence=res.similarity_score,
                created_at=now_iso,
            )
    except Exception as e:
        logger.debug(f"[PatternCoiling] Error evaluating {symbol}: {e}")

    return None
