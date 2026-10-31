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

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config.constants import IST
from config.paths import app_data_path
from engine.learning_engine import pattern_learning_engine

logger = logging.getLogger("engine.alert_postmortem_runner")

PROFIT_TARGET_MILESTONES = {
    "T0_5",
    "T0.5",
    "T1",
    "T2",
    "T3",
    "TARGET",
    "RUNNER_EXIT",
    "RUNNER",
    "PROFIT",
    "DE_RISK",
    "BREAKEVEN_LOCKED",
    "SPREAD_PROFIT_70",
}

WINNING_STAGES = {
    "COMPLETED",
    "RUNNER_EXIT",
    "T0_5_ACHIEVED",
    "T1_ACHIEVED",
    "T2_ACHIEVED",
    "TARGET_ACHIEVED",
    "SPREAD_PROFIT_70",
}


def is_target_or_profit_achieved(alert: Any, r_val: float = 0.0) -> bool:
    """
    Evaluates whether an alert achieved a profitable milestone, target exit, or runner scale.
    Guarantees that T0.5 scale-outs, runner exits, and profit milestones are recognized as wins
    rather than being discarded as unfulfilled setups.
    """
    milestones = getattr(alert, "achieved_milestones", []) or []
    for m in milestones:
        m_str = str(m).upper()
        if any(tm in m_str for tm in PROFIT_TARGET_MILESTONES):
            return True
    stage = str(getattr(alert, "stage", "") or "").upper()
    if stage in WINNING_STAGES:
        return True
    target_st = str(getattr(alert, "target_status", "") or "").upper()
    if any(tm in target_st for tm in PROFIT_TARGET_MILESTONES):
        return True
    return r_val >= 0.35


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
    active_swings = 0
    pos_r_sum = 0.0
    neg_r_sum = 0.0
    best_trade = None
    best_trade_r = -999.0
    archetype_stats: dict[str, dict[str, Any]] = {}
    microstructure_stats: dict[str, int] = {
        "wall_traps": 0,
        "obi_imbalances": 0,
        "spread_friction": 0,
    }

    for alert in today_alerts:
        sym = getattr(alert, "contract_symbol", None) or getattr(alert, "symbol", "") or "UNKNOWN"
        archetype = str(getattr(alert, "alert_type", "MOMENTUM") or "MOMENTUM").upper()
        if archetype not in archetype_stats:
            archetype_stats[archetype] = {"total": 0, "wins": 0, "losses": 0, "net_r": 0.0}

        stat = archetype_stats[archetype]
        stat["total"] += 1

        is_inv = getattr(alert, "is_invalidated", False)
        milestones = getattr(alert, "achieved_milestones", []) or []
        target_hit = is_target_or_profit_achieved(alert)
        t1_reached = target_hit

        has_triggered = getattr(alert, "has_triggered", True)
        is_disqualified = (
            getattr(alert, "target_status", "")
            in ("SETUP_DISQUALIFIED", "DISQUALIFIED", "SUPERSEDED")
            or getattr(alert, "stage", "") in ("CANCELLED", "SETUP_DISQUALIFIED", "SUPERSEDED")
            or getattr(alert, "is_disqualified", False)
        )
        if (
            hasattr(alert, "stage")
            and alert.stage
            in (
                "STALK",
                "EARLY_WARNING",
                "PRIMED",
                "CANCELLED",
                "SETUP_DISQUALIFIED",
                "SUPERSEDED",
            )
        ) or is_disqualified:
            has_triggered = False

        r_mult = getattr(alert, "r_multiple", None)
        if not has_triggered or is_disqualified:
            r_val = 0.0
        elif r_mult is not None:
            r_val = float(r_mult)
        else:
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

        # Scorecard Calibration Invariant:
        # If an alert has no achieved profit milestones/winning stages and is not invalidated, any report of R > 0.5
        # is a phantom/unreached target projection. Clamp R to 0.0 so it is properly categorized as unfulfilled/flat.
        if not target_hit and not is_inv and len(milestones) == 0 and r_val > 0.5:
            logger.warning(
                f"[Scorecard] Integrity Invariant Clamping: Alert {sym} ({getattr(alert, 'alert_id', '')}) "
                f"has 0 achieved milestones and is not invalidated, but reports R={r_val:.2f}R. Clamping R to 0.0."
            )
            r_val = 0.0

        th = (getattr(alert, "time_horizon", "") or "").upper()
        is_multi_session = th in (
            "SWING",
            "SWING_SHORT",
            "SWING_MID",
            "LONG_TERM",
            "POSITIONAL",
            "MULTIBAGGER",
        ) or getattr(alert, "setup_style", "") in ("SWING", "POSITIONAL")
        is_expired = getattr(alert, "is_expired", False)

        if not has_triggered:
            unfulfilled += 1
            stat["unfulfilled"] = stat.get("unfulfilled", 0) + 1
        elif t1_reached or r_val > 0.3:
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

            # Microstructure root-cause tracking
            pm = (getattr(alert, "metrics", {}) or {}).get("post_mortem") or {}
            reason_code = str(pm.get("primary_failure_reason", "") or "").upper()
            exit_micro = getattr(alert, "exit_microstructure", None) or (
                getattr(alert, "metrics", {}) or {}
            ).get("exit_microstructure")
            if reason_code == "ORDER_BOOK_ABSORPTION_WALL_TRAP" or (
                exit_micro and exit_micro.get("has_resting_wall")
            ):
                microstructure_stats["wall_traps"] += 1
            elif reason_code == "HEAVY_OBI_LIQUIDITY_RUN_IMBALANCE" or (
                exit_micro and abs(float(exit_micro.get("obi_50", 0.0) or 0.0)) >= 0.40
            ):
                microstructure_stats["obi_imbalances"] += 1
            elif reason_code == "EXCESSIVE_SPREAD_FRICTION_DRAG" or (
                exit_micro and float(exit_micro.get("spread_bps", 0.0) or 0.0) >= 35.0
            ):
                microstructure_stats["spread_friction"] += 1
        elif is_multi_session and not is_expired:
            active_swings += 1
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

    recommendations: list[dict[str, Any]] = []
    if total_closed >= 4 and win_rate < 50.0:
        recommendations.append(
            {
                "target": "scrutiny_conviction_threshold",
                "action": "INCREASE_MIN_CONVICTION",
                "adjustment": +5,
                "reason": f"Session win rate {win_rate:.1f}% below 50% baseline across {total_closed} closed setups.",
            }
        )
    if microstructure_stats.get("wall_traps", 0) >= 2:
        recommendations.append(
            {
                "target": "depth_wall_scrutiny",
                "action": "STRICT_RESTING_WALL_VETO",
                "adjustment": True,
                "reason": f"{microstructure_stats['wall_traps']} setups stopped out by Order Book absorption wall traps.",
            }
        )
    if microstructure_stats.get("spread_friction", 0) >= 2:
        recommendations.append(
            {
                "target": "spread_bps_cap",
                "action": "TIGHTEN_SPREAD_CAP",
                "adjustment": 20.0,
                "reason": f"{microstructure_stats['spread_friction']} setups suffered excessive spread friction drag.",
            }
        )
    if microstructure_stats.get("obi_imbalances", 0) >= 2:
        recommendations.append(
            {
                "target": "obi_skew_threshold",
                "action": "ENFORCE_COUNTER_FLOW_FILTER",
                "adjustment": 0.35,
                "reason": f"{microstructure_stats['obi_imbalances']} setups suffered severe order book imbalance sweeps.",
            }
        )

    return {
        "session_date": session_date,
        "total_alerts": len(today_alerts),
        "wins": wins,
        "losses": losses,
        "unfulfilled": unfulfilled,
        "active_swings": active_swings,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "net_realized_r": net_r,
        "gross_gain_r": round(pos_r_sum, 2),
        "gross_loss_r": round(neg_r_sum, 2),
        "best_trade": best_trade,
        "archetype_breakdown": archetype_stats,
        "microstructure_attribution": microstructure_stats,
        "calibration_recommendations": recommendations,
    }


def format_eod_scorecard_telegram(scorecard: dict[str, Any]) -> str:
    """Format institutional EOD session performance card for Telegram."""
    date_str = scorecard.get("session_date", "")
    total = scorecard.get("total_alerts", 0)
    wins = scorecard.get("wins", 0)
    losses = scorecard.get("losses", 0)
    unf = scorecard.get("unfulfilled", 0)
    active_sw = scorecard.get("active_swings", 0)
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

    micro = scorecard.get("microstructure_attribution") or {}
    micro_parts = []
    if micro.get("wall_traps", 0) > 0:
        micro_parts.append(f"{micro['wall_traps']} Wall Absorption")
    if micro.get("obi_imbalances", 0) > 0:
        micro_parts.append(f"{micro['obi_imbalances']} OBI Skew")
    if micro.get("spread_friction", 0) > 0:
        micro_parts.append(f"{micro['spread_friction']} Spread Drag")
    micro_str = (
        f"🔬 <b>Microstructure Root Causes:</b> {', '.join(micro_parts)}\n" if micro_parts else ""
    )

    recs = scorecard.get("calibration_recommendations") or []
    recs_parts = []
    for r in recs:
        recs_parts.append(f"  • <b>{r.get('target')}</b>: {r.get('action')} ({r.get('reason')})")
    recs_str = (
        "🛠️ <b>Autonomous Scrutiny Calibrations:</b>\n" + "\n".join(recs_parts) + "\n\n"
        if recs_parts
        else ""
    )

    return (
        f"🏁 <b>[EOD QUANTITATIVE SESSION SCORECARD]</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Session:</b> {date_str} | <b>Close:</b> 15:35 IST\n"
        f"📊 <b>Total Setups:</b> {total} | 🟢 <b>Wins:</b> {wins} | 🔴 <b>Losses:</b> {losses}"
        + (f" | ⏳ <b>Swings:</b> {active_sw}" if active_sw > 0 else "")
        + (f" | ⚪ <b>Flat:</b> {unf}" if unf > 0 else "")
        + f"\n"
        f"🎯 <b>Win Rate:</b> <b>{wr:.1f}%</b> | <b>Profit Factor:</b> <b>{pf:.2f}x</b>\n"
        f"{r_icon} <b>Net Realized PnL:</b> <b>{r_sign}{net_r:.1f}R</b>\n\n"
        f"🏆 <b>Best Setup:</b> {best_str}\n\n"
        f"📋 <b>Strategy Attribution:</b>\n"
        f"{bd_str}\n"
        + (f"\n{micro_str}" if micro_str else "")
        + (f"\n{recs_str}" if recs_str else "")
        + "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 <i>Factor weights recalibrated in Pattern Learning Engine.</i>"
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
    except Exception as e_suppressed:
        logger.debug(
            f"[engine.alert_postmortem_runner] Non-fatal exception suppressed: {e_suppressed}"
        )


def run_eod_alert_postmortems(
    auto_engine: Optional[Any] = None,
    force: bool = False,
    broadcast: bool = False,
    session_date: Optional[str] = None,
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
        # Require that today is an official trading day and post-market (after 15:30 IST)
        from market.calendar import is_trading_day

        if not is_trading_day(now_ist.date(), exchange="NSE"):
            report["status"] = "SKIPPED_WEEKEND_OR_HOLIDAY"
            report["reason"] = (
                f"Today ({now_ist.strftime('%Y-%m-%d')}) is not an active exchange trading day. "
                "EOD session scorecard skipped."
            )
            logger.info("[AlertPostMortem] %s", report["reason"])
            return report

        hhmm = now_ist.hour * 100 + now_ist.minute
        if hhmm < 1530:
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

    today_date = session_date or now_ist.strftime("%Y-%m-%d")
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

    # Persist daily scorecard to app_data postmortem storage and data/postmortem/
    session_slug = today_date.replace("-", "")
    scorecard_filename = f"daily_scorecard_{session_slug}.json"
    try:
        sc_dir = app_data_path("postmortem")
        sc_dir.mkdir(parents=True, exist_ok=True)
        sc_file = sc_dir / scorecard_filename
        sc_file.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
        report["scorecard_path"] = str(sc_file)
    except Exception as e_sc:
        logger.warning(f"[AlertPostMortem] Could not persist daily scorecard to app_data: {e_sc}")

    try:
        local_dir = Path("data/postmortem")
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / scorecard_filename).write_text(
            json.dumps(scorecard, indent=2), encoding="utf-8"
        )
    except Exception as e_local:
        logger.debug(f"[AlertPostMortem] Optional local scorecard save note: {e_local}")

    if broadcast and len(today_alerts) > 0:
        broadcast_eod_scorecard(scorecard)

    for alert in today_alerts:
        alert_id = getattr(alert, "alert_id", "") or str(getattr(alert, "id", ""))
        symbol = getattr(alert, "symbol", "") or ""
        is_invalidated = getattr(alert, "is_invalidated", False)
        achieved_milestones = getattr(alert, "achieved_milestones", []) or []
        t1_reached = any("T1" in str(m) for m in achieved_milestones)

        th = (getattr(alert, "time_horizon", "") or "").upper()
        is_multi_session = th in (
            "SWING",
            "SWING_SHORT",
            "SWING_MID",
            "LONG_TERM",
            "POSITIONAL",
            "MULTIBAGGER",
        ) or getattr(alert, "setup_style", "") in ("SWING", "POSITIONAL")
        is_expired = getattr(alert, "is_expired", False)

        # Multi-session swing setups that are neither invalidated nor expired are still active across calendar days.
        # Do not record premature UNFULFILLED_EOD post-mortems on Day 1.
        if is_multi_session and not is_invalidated and not is_expired:
            logger.info(
                f"[AlertPostMortem] Skipping premature EOD evaluation for active swing setup {alert_id} ({th})"
            )
            continue

        # Untriggered radar setups (never entered into market) do not conduct invalidation post-mortems
        has_triggered = getattr(alert, "has_triggered", True)
        is_disqualified = (
            getattr(alert, "target_status", "")
            in ("SETUP_DISQUALIFIED", "DISQUALIFIED", "SUPERSEDED")
            or getattr(alert, "stage", "") in ("CANCELLED", "SETUP_DISQUALIFIED", "SUPERSEDED")
            or getattr(alert, "is_disqualified", False)
        )
        if (
            hasattr(alert, "stage")
            and alert.stage
            in (
                "STALK",
                "EARLY_WARNING",
                "PRIMED",
                "CANCELLED",
                "SETUP_DISQUALIFIED",
                "SUPERSEDED",
            )
        ) or is_disqualified:
            has_triggered = False
        if not has_triggered or is_disqualified:
            continue

        # We conduct post-mortem if the alert was invalidated, or if it expired/closed without hitting any profit milestone
        target_hit = is_target_or_profit_achieved(alert)
        needs_postmortem = (
            is_invalidated
            or (not target_hit and is_expired)
            or (not is_multi_session and not target_hit and not has_triggered)
        )
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

    # 4. Autonomous Market Mover Learning: Ingest pre-blast fingerprints from today's top runners
    try:
        learned_movers = pattern_learning_engine.scan_and_learn_from_market_movers()
        report["learned_movers_count"] = len(learned_movers)
        if learned_movers:
            logger.info(
                f"[AlertPostMortem] Ingested {len(learned_movers)} new explosive mover fingerprints into pattern memory."
            )
    except Exception as exc:
        logger.warning(f"[AlertPostMortem] Mover learning error: {exc}")

    # 5. Continuous Experience Replay: Ingest all evaluated session setups into Episodic Trade Memory Store
    episodic_ingested = 0
    try:
        from engine.episodic_memory import get_episodic_memory_store, TradeEpisode
        from engine.daily_levels import daily_levels_store

        mem_store = get_episodic_memory_store()
        for alert in today_alerts:
            alert_id = getattr(alert, "alert_id", "") or str(getattr(alert, "id", ""))
            clean_sym = (
                str(getattr(alert, "symbol", "") or "")
                .replace("NSE:", "")
                .replace("BSE:", "")
                .strip()
            )
            has_trig = getattr(alert, "has_triggered", True)
            is_dq = (
                getattr(alert, "target_status", "")
                in ("SETUP_DISQUALIFIED", "DISQUALIFIED", "SUPERSEDED")
                or getattr(alert, "stage", "") in ("CANCELLED", "SETUP_DISQUALIFIED", "SUPERSEDED")
                or getattr(alert, "is_disqualified", False)
            )
            if not has_trig or is_dq or not clean_sym:
                continue

            entry_p = float(
                getattr(alert, "entry_price", 0.0)
                or getattr(alert, "trigger_level", 0.0)
                or getattr(alert, "ltp", 0.0)
                or 0.0
            )
            sl_p = float(getattr(alert, "stop_loss", 0.0) or 0.0)
            t1_p = float(
                getattr(alert, "target_level", 0.0) or getattr(alert, "target_1", 0.0) or 0.0
            )
            if entry_p <= 0:
                continue

            cur_p = float(getattr(alert, "ltp", 0.0) or entry_p)
            is_inv = getattr(alert, "is_invalidated", False)
            if is_inv and sl_p > 0:
                cur_p = sl_p

            direction = str(getattr(alert, "direction", "BULLISH")).upper()
            is_long = (
                direction in ("BULLISH", "LONG", "BUY") or getattr(alert, "option_type", "") == "CE"
            )
            risk = abs(entry_p - sl_p) if sl_p > 0 and sl_p != entry_p else (entry_p * 0.015)
            realized_r = round(
                ((cur_p - entry_p) if is_long else (entry_p - cur_p)) / max(0.01, risk),
                2,
            )

            milestones = getattr(alert, "achieved_milestones", []) or []
            t1_reached = any("T1" in str(m) for m in milestones) or any(
                "TARGET" in str(m) for m in milestones
            )

            if t1_reached or realized_r > 0.3:
                outcome_str = "WIN"
            elif is_inv or realized_r < -0.3:
                outcome_str = "LOSS"
            else:
                outcome_str = "BREAKEVEN"

            mfe_r = float(getattr(alert, "peak_mfe_r", 0.0) or 0.0)
            mae_r = float(getattr(alert, "peak_mae_r", 0.0) or 0.0)
            if mfe_r == 0.0 and outcome_str == "WIN":
                mfe_r = max(1.5, realized_r)
            if mae_r == 0.0 and outcome_str == "LOSS":
                mae_r = max(1.0, abs(realized_r))

            if outcome_str == "WIN" and mae_r <= 0.30:
                grade = "A+"
                lesson = "Institutional sniper execution: clean momentum expansion with minimal adverse excursion."
            elif outcome_str == "WIN":
                grade = "A"
                lesson = "Target achieved according to trade blueprint. Adhered to profit milestone scaling."
            elif outcome_str == "BREAKEVEN":
                grade = "B"
                lesson = "Capital preserved in range contraction session; trailing breakeven lock prevented loss."
            elif outcome_str == "LOSS" and realized_r >= -1.05:
                grade = "C"
                lesson = "Disciplined risk gate stop-loss respected. Invalidation caught cleanly."
            else:
                grade = "F"
                lesson = "Adverse excursion exceeded tolerance or trade slipped past stop boundary."

            dl = daily_levels_store.get_levels(clean_sym)
            day_arch = getattr(dl, "day_archetype", "NORMAL_DAY") if dl else "NORMAL_DAY"

            pnl_pts = round(cur_p - entry_p if is_long else entry_p - cur_p, 2)
            pnl_pct = round((pnl_pts / entry_p) * 100.0, 2) if entry_p > 0 else 0.0
            eer = round(max(0.0, min(1.0, realized_r / max(0.01, mfe_r))), 4) if mfe_r > 0 else 0.0
            exit_reason = (
                "T1_HIT"
                if outcome_str == "WIN"
                else ("STOPPED_OUT" if outcome_str == "LOSS" else "BREAKEVEN_EXIT")
            )

            episode = TradeEpisode(
                episode_id=alert_id,
                session_date=today_date,
                symbol=clean_sym,
                direction=direction,
                entry_price=entry_p,
                exit_price=cur_p,
                stop_loss=sl_p,
                target_1=t1_p,
                pnl_pts=pnl_pts,
                pnl_pct=pnl_pct,
                r_multiple=realized_r,
                mfe_r=round(mfe_r, 2),
                mae_r=round(mae_r, 2),
                execution_efficiency=eer,
                vix_regime=str(getattr(alert, "regime", "NORMAL_IV") or "NORMAL_IV"),
                day_archetype=day_arch,
                vpin_regime=str(getattr(alert, "vpin_regime", "LOW_TOXICITY")),
                holding_duration_mins=float(getattr(alert, "holding_duration_mins", 45) or 45),
                exit_reason=exit_reason,
                win_loss=outcome_str,
                narrative=f"[{grade}] {lesson}",
            )
            mem_store.record_episode(episode)
            episodic_ingested += 1
    except Exception as e_mem:
        logger.warning(f"[AlertPostMortem] Episodic trade memory ingestion degraded: {e_mem}")

    report["episodic_memories_ingested"] = episodic_ingested

    return report
