"""
engine/alert_postmortem_runner.py
──────────────────────────────────
Automated End-Of-Day (EOD) alert post-mortem runner.

Runs after market close (15:30 IST) as part of the nightly chain or as an on-demand task.
Iterates over today's generated alerts, identifies setups that:
  1. Were stopped out or invalidated
  2. Failed to achieve Target 1 (+2R) before session end
  3. Closed with adverse drift

Conducts forensic root-cause analysis via `PatternLearningEngine`,
persists outcomes to pattern_outcomes.json, and recalibrates factor weights.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from config.constants import IST
from engine.learning_engine import pattern_learning_engine

logger = logging.getLogger("engine.alert_postmortem_runner")


def run_eod_alert_postmortems(
    auto_engine: Optional[Any] = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Scan today's alerts, run retrospective post-mortems on failed/unfulfilled setups,
    and trigger closed-loop factor weight recalibration.

    Args:
        auto_engine: Optional AutoAlertEngine instance (lazily imported if None).
        force: If True, bypass market close time check.

    Returns:
        Structured dictionary summarizing post-mortems conducted.
    """
    now_ist = datetime.now(IST)
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    report: dict[str, Any] = {
        "timestamp": now_str,
        "processed_count": 0,
        "post_mortems_conducted": 0,
        "outcomes_recorded": 0,
        "details": [],
        "factor_weights": {},
        "status": "COMPLETED",
    }

    if not force:
        # Require after-market execution (after 15:30 IST) on weekdays
        hhmm = now_ist.hour * 100 + now_ist.minute
        if now_ist.weekday() < 5 and hhmm < 1530:
            report["status"] = "SKIPPED_MARKET_OPEN"
            report["reason"] = "Market is still open (pre-15:30 IST). Use force=True to override."
            logger.info("[AlertPostMortem] %s", report["reason"])
            return report

    # Resolve AutoAlertEngine
    if auto_engine is None:
        try:
            from engine.auto_alert_engine import get_auto_alert_engine

            auto_engine = get_auto_alert_engine()
        except Exception as e:
            logger.warning("[AlertPostMortem] Could not load AutoAlertEngine: %s", e)
            report["status"] = "ENGINE_UNAVAILABLE"
            return report

    # Retrieve all alerts from memory buffer
    try:
        alerts = auto_engine.get_alerts() if hasattr(auto_engine, "get_alerts") else []
    except Exception as e:
        logger.warning("[AlertPostMortem] Error fetching alerts: %s", e)
        alerts = []

    today_date = now_ist.strftime("%Y-%m-%d")
    today_alerts = []
    for a in alerts:
        created_at = getattr(a, "created_at", "") or ""
        if created_at.startswith(today_date) or not created_at:
            today_alerts.append(a)

    report["processed_count"] = len(today_alerts)
    logger.info("[AlertPostMortem] Evaluating %d alerts for EOD post-mortem", len(today_alerts))

    for alert in today_alerts:
        alert_id = getattr(alert, "alert_id", "") or str(getattr(alert, "id", ""))
        symbol = getattr(alert, "symbol", "") or ""
        is_invalidated = getattr(alert, "is_invalidated", False)
        achieved_milestones = getattr(alert, "achieved_milestones", []) or []
        t1_reached = any("T1" in str(m) for m in achieved_milestones)

        # We conduct post-mortem if the alert was invalidated, or if it expired/closed without hitting T1
        needs_postmortem = is_invalidated or (not t1_reached)
        if not needs_postmortem:
            continue

        try:
            entry = float(
                getattr(alert, "entry_price", 0.0)
                or getattr(alert, "trigger_level", 0.0)
                or getattr(alert, "ltp", 0.0)
                or 0.0
            )
            is_opt = bool(
                getattr(alert, "option_type", None) or getattr(alert, "contract_symbol", None)
            )

            # Resolve appropriate exit price
            if is_invalidated and getattr(alert, "stop_loss", None) and alert.stop_loss > 0:
                exit_price = float(alert.stop_loss)
            else:
                exit_price = float(getattr(alert, "ltp", 0.0) or entry)

            # If for an option alert exit_price is in spot coordinates, clamp to premium SL
            if is_opt and entry > 0 and exit_price > 3.0 * entry:
                exit_price = float(getattr(alert, "stop_loss", entry * 0.72) or (entry * 0.72))

            exchange = getattr(alert, "exchange", "NSE")

            # 1. Conduct forensic post-mortem
            pm = pattern_learning_engine.conduct_invalidation_post_mortem(
                alert=alert,
                exit_price=exit_price,
                exchange=exchange,
            )
            report["post_mortems_conducted"] += 1

            # 2. Record trade outcome into learning history
            r_mult = getattr(alert, "r_multiple", None)
            if r_mult is None or r_mult == 0.0:
                sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
                risk = abs(entry - sl) if sl > 0 and sl != entry else (entry * 0.015)
                is_bull = (
                    getattr(alert, "direction", "BULLISH") in ("BULLISH", "LONG", "BUY")
                    or getattr(alert, "option_type", "") == "CE"
                )
                r_mult = round(
                    ((exit_price - entry) if is_bull else (entry - exit_price)) / max(0.01, risk),
                    2,
                )

            outcome_label = "STOPPED_OUT" if is_invalidated else "UNFULFILLED_EOD"

            pattern_learning_engine.record_trade_outcome(
                alert_id=alert_id,
                symbol=symbol,
                archetype=getattr(alert, "alert_type", "MOMENTUM"),
                entry_price=entry,
                exit_price=exit_price,
                outcome=outcome_label,
                realized_rr=r_mult,
                factors_present=getattr(alert, "matched_factors", []),
            )
            report["outcomes_recorded"] += 1

            report["details"].append(
                {
                    "alert_id": alert_id,
                    "symbol": symbol,
                    "outcome": outcome_label,
                    "realized_rr": r_mult,
                    "root_cause": pm.root_cause
                    if hasattr(pm, "root_cause")
                    else "EOD Session Close",
                }
            )
        except Exception as exc:
            logger.debug("[AlertPostMortem] Error conducting post-mortem for %s: %s", symbol, exc)

    # 3. Recalibrate factor weights based on updated outcomes
    try:
        updated_weights = pattern_learning_engine.recalibrate_factor_weights()
        report["factor_weights"] = updated_weights
        logger.info("[AlertPostMortem] Recalibrated factor weights: %s", updated_weights)
    except Exception as exc:
        logger.warning("[AlertPostMortem] Recalibration error: %s", exc)

    return report
