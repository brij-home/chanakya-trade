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

            import pandas as pd
            from engine.trade_plan import calculate_trade_plan

            tp = calculate_trade_plan(
                symbol, direction="BULLISH", spot=ltp, timeframe="SWING_SHORT", exchange=exchange, df=df
            )

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

            if tp and tp.is_asymmetry_viable and tp.target_1 > ltp and tp.invalidation_stop < ltp:
                t1 = tp.target_1
                sl = tp.invalidation_stop
                rr_str = f"1:{tp.rr_t1}"
                tp_dict = tp.as_dict()
            else:
                atr20 = ltp * 0.015
                if df is not None and len(df) >= 14:
                    try:
                        h = df["high"] if "high" in df.columns else df["High"]
                        l = df["low"] if "low" in df.columns else df["Low"]
                        c = df["close"] if "close" in df.columns else df["Close"]
                        tr = pd.concat(
                            [h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1
                        ).max(axis=1)
                        atr20 = float(tr.rolling(14).mean().iloc[-1])
                    except Exception:
                        pass
                risk_pts = max(1.0, round(max(0.8 * atr20, ltp * 0.015), 2))
                sl = round(ltp - risk_pts, 2)
                t1 = round(ltp + 2.5 * risk_pts, 2)
                rr_str = "1:2.5"
                tp_dict = None

            # Volatility Noise Floor: Ensure stop-loss is not placed within intraday noise chop
            min_sl_dist = round(max(ltp * 0.012, 1.0), 2)
            if (ltp - sl) < min_sl_dist:
                sl = round(ltp - min_sl_dist, 2)

            tick_offset = max(0.05, min(0.5, round(ltp * 0.001, 2)))
            e_min = round(max(sl + tick_offset, ltp * 0.998), 1)
            e_max = round(min(t1 - tick_offset, ltp * 1.005), 1)
            if e_min >= e_max:
                e_min = round(ltp * 0.998, 1)
                e_max = round(ltp * 1.005, 1)
            entry_rg = f"₹{e_min:,.1f} – ₹{e_max:,.1f}"

            act_plan = {
                "action": res.recommended_entry_action,
                "entry_range": entry_rg,
                "target": f"₹{t1:.1f}",
                "stop_loss": f"₹{sl:.1f}",
                "risk_reward": rr_str,
            }
            if tp_dict:
                act_plan["trade_plan"] = tp_dict

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
