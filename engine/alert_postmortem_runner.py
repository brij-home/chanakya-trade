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


def generate_session_scorecard(
    today_alerts: list[Any],
    session_date: Optional[str] = None,
) -> dict[str, Any]:
    """
    Computes institutional session performance attribution across all trade setups generated today:
      - Total Setups Fired
      - Wins (Target 1, Target 2, Runner reached or Net PnL > 0)
      - Losses (Invalidated / Stopped Out with Net PnL < 0)
      - Unfulfilled / Flat (Neither stopped out nor hit T1 before session close)
      - Win Rate (%)
      - Profit Factor (Gross Realized R from Wins / Gross Realized R from Losses)
      - Net Realized R-Multiple
      - Best Trade of the Day
      - Strategy Archetype Attribution (GAMMA_BLAST, INTRADAY_EQUITY, INDEX_CALL_SETUP, etc.)
    """
    if not session_date:
        session_date = datetime.now(IST).strftime("%Y-%m-%d")

    wins = 0
    losses = 0
    unfulfilled = 0
    pos_r_sum = 0.0
    neg_r_sum = 0.0
    best_trade = None
    best_trade_r = -999.0
    archetype_stats: dict[str, dict[str, Any]] = {}

    for alert in today_alerts:
        sym = getattr(alert, "contract_symbol", None) or getattr(alert, "symbol", "") or "UNKNOWN"
        archetype = str(getattr(alert, "alert_type", "MOMENTUM") or "MOMENTUM").upper()
        if archetype not in archetype_stats:
            archetype_stats[archetype] = {"total": 0, "wins": 0, "losses": 0, "net_r": 0.0}

        stat = archetype_stats[archetype]
        stat["total"] += 1

        is_inv = getattr(alert, "is_invalidated", False)
        milestones = getattr(alert, "achieved_milestones", []) or []
        t1_reached = any("T1" in str(m) for m in milestones) or any(
            "TARGET" in str(m) for m in milestones
        )

        r_mult = getattr(alert, "r_multiple", None)
        if r_mult is None or r_mult == 0.0:
            entry = float(
                getattr(alert, "entry_price", 0.0)
                or getattr(alert, "trigger_level", 0.0)
                or getattr(alert, "ltp", 0.0)
                or 0.0
            )
            sl = float(getattr(alert, "stop_loss", 0.0) or 0.0)
            cur = float(getattr(alert, "ltp", 0.0) or entry)
            risk = abs(entry - sl) if sl > 0 and sl != entry else (entry * 0.015)
            is_bull = (
                getattr(alert, "direction", "BULLISH") in ("BULLISH", "LONG", "BUY")
                or getattr(alert, "option_type", "") == "CE"
            )
            if is_inv and sl > 0:
                cur = sl
            r_val = round(((cur - entry) if is_bull else (entry - cur)) / max(0.01, risk), 2)
        else:
            r_val = float(r_mult)

        if t1_reached or r_val > 0.3:
            wins += 1
            pos_r_sum += max(0.0, r_val)
            stat["wins"] += 1
            stat["net_r"] = round(stat["net_r"] + r_val, 2)
            if r_val > best_trade_r:
                best_trade_r = r_val
                best_trade = {"symbol": sym, "archetype": archetype, "r_multiple": r_val}
        elif is_inv or r_val < -0.3:
            losses += 1
            neg_r_sum += abs(min(0.0, r_val))
            stat["losses"] += 1
            stat["net_r"] = round(stat["net_r"] + r_val, 2)
        else:
            unfulfilled += 1
            stat["net_r"] = round(stat["net_r"] + r_val, 2)

    total_closed = wins + losses
    win_rate = round((wins / total_closed * 100.0), 1) if total_closed > 0 else 0.0
    profit_factor = (
        round((pos_r_sum / neg_r_sum), 2)
        if neg_r_sum > 0
        else (round(pos_r_sum, 2) if pos_r_sum > 0 else 1.0)
    )
    net_r = round(pos_r_sum - neg_r_sum, 2)

    return {
        "session_date": session_date,
        "total_alerts": len(today_alerts),
        "wins": wins,
        "losses": losses,
        "unfulfilled": unfulfilled,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "net_realized_r": net_r,
        "gross_gain_r": round(pos_r_sum, 2),
        "gross_loss_r": round(neg_r_sum, 2),
        "best_trade": best_trade,
        "archetype_breakdown": archetype_stats,
    }


def format_eod_scorecard_telegram(scorecard: dict[str, Any]) -> str:
    """Format institutional EOD session performance card for Telegram."""
    date_str = scorecard.get("session_date", "")
    total = scorecard.get("total_alerts", 0)
    wins = scorecard.get("wins", 0)
    losses = scorecard.get("losses", 0)
    unf = scorecard.get("unfulfilled", 0)
    wr = scorecard.get("win_rate_pct", 0.0)
    pf = scorecard.get("profit_factor", 1.0)
    net_r = scorecard.get("net_realized_r", 0.0)
    r_sign = "+" if net_r >= 0 else ""
    r_icon = "🟢" if net_r >= 0 else "🔴"
    best = scorecard.get("best_trade")

    breakdown_lines = []
    for arch, st in (scorecard.get("archetype_breakdown") or {}).items():
        sub_sign = "+" if st["net_r"] >= 0 else ""
        breakdown_lines.append(
            f"  • <b>{arch}</b>: {st['wins']}/{st['total']} wins ({sub_sign}{st['net_r']}R)"
        )
    bd_str = "\n".join(breakdown_lines) if breakdown_lines else "  • <i>No trades executed</i>"

    best_str = (
        f"<b>{best['symbol']}</b> ({best['archetype']}) <b>+{best['r_multiple']:.1f}R</b>"
        if best
        else "None"
    )

    return (
        f"🏁 <b>[EOD QUANTITATIVE SESSION SCORECARD]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Session:</b> {date_str} | <b>Close:</b> 15:35 IST\n"
        f"📊 <b>Total Setups:</b> {total} | 🟢 <b>Wins:</b> {wins} | 🔴 <b>Losses:</b> {losses}"
        + (f" | ⚪ <b>Flat:</b> {unf}" if unf > 0 else "")
        + f"\n"
        f"🎯 <b>Win Rate:</b> <b>{wr:.1f}%</b> | <b>Profit Factor:</b> <b>{pf:.2f}x</b>\n"
        f"{r_icon} <b>Net Realized PnL:</b> <b>{r_sign}{net_r:.1f}R</b>\n\n"
        f"🏆 <b>Best Setup:</b> {best_str}\n\n"
        f"📋 <b>Strategy Attribution:</b>\n"
        f"{bd_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <i>Factor weights recalibrated in Pattern Learning Engine.</i>"
    )


def broadcast_eod_scorecard(scorecard: dict[str, Any]) -> None:
    """Send EOD scorecard to Telegram and SSE."""
    msg = format_eod_scorecard_telegram(scorecard)
    try:
        from bot.telegram_bot import send_message

        send_message(msg, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"[AlertPostMortem] Telegram EOD scorecard broadcast failed: {e}")

    try:
        from web.sse import event_bus

        event_bus.publish_sync("eod_scorecard", scorecard)
    except Exception:
        pass


def run_eod_alert_postmortems(
    auto_engine: Optional[Any] = None,
    force: bool = False,
    broadcast: bool = False,
) -> dict[str, Any]:
    """
    Scan today's alerts, compute session quantitative scorecard, run retrospective
    post-mortems on failed/unfulfilled setups, and trigger closed-loop factor weight recalibration.

    Args:
        auto_engine: Optional AutoAlertEngine instance (lazily imported if None).
        force: If True, bypass market close time check.
        broadcast: If True, send Telegram scorecard and emit SSE event.

    Returns:
        Structured dictionary summarizing post-mortems conducted and session scorecard.
    """
    now_ist = datetime.now(IST)
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    report: dict[str, Any] = {
        "timestamp": now_str,
        "processed_count": 0,
        "post_mortems_conducted": 0,
        "outcomes_recorded": 0,
        "scorecard": {},
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

    # Compute institutional session scorecard
    scorecard = generate_session_scorecard(today_alerts, session_date=today_date)
    report["scorecard"] = scorecard
    if broadcast and len(today_alerts) > 0:
        broadcast_eod_scorecard(scorecard)

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
