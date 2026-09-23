"""
engine/nightly_chain.py
────────────────────────────────────────────────────────────────────────────────
Post-Market Nightly Quality Chain (runs after 15:30 IST).

Orchestrates:
  Stage 1: MoverAutopsyEngine.perform_daily_autopsy()  -- causal forensics
  Stage 2: PatternLearningEngine.recalibrate_from_snr() -- factor weight update
  Stage 3: nightly_drift_check()  -- drift detection + closed-loop correction
  Stage 4: Telegram health digest (best-effort)

Usage:
    from engine.nightly_chain import run_nightly_post_market_chain
    result = run_nightly_post_market_chain()

    # To start an auto-scheduler at 15:45 IST (call once at app startup):
    from engine.nightly_chain import schedule_nightly_chain
    schedule_nightly_chain()
"""

from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("engine.nightly_chain")

from config.constants import IST


def run_nightly_post_market_chain(
    force: bool = False,
    send_telegram: bool = True,
) -> dict[str, Any]:
    """
    Execute the full post-market quality pipeline.

    Args:
        force:          Run even during market hours (useful for testing).
        send_telegram:  Dispatch a Telegram summary if bot is configured.

    Returns:
        Structured result dict with keys:
          - stage1_autopsy: autopsy dict or None
          - stage2_snr:     SNR table dict
          - stage2b_alert_postmortems: alert post-mortem report dict
          - stage3_drift:   drift correction report
          - status:         "COMPLETED" | "SKIPPED"
          - timestamp:      IST timestamp string
    """
    now_ist = datetime.now(IST)
    result: dict[str, Any] = {
        "timestamp": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "stage1_autopsy": None,
        "stage2_snr": {},
        "stage2b_alert_postmortems": {},
        "stage3_drift": {},
        "status": "SKIPPED",
    }

    # Safety gate: skip during market hours and weekends unless forced
    if now_ist.weekday() >= 5:
        result["reason"] = "Weekend — no market data to process"
        logger.info("[NightlyChain] Skipped — weekend")
        return result

    market_open = now_ist.replace(hour=9, minute=10, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if market_open <= now_ist <= market_close and not force:
        result["reason"] = "Market hours — run after 15:30 IST"
        logger.info("[NightlyChain] Skipped — market still open")
        return result

    logger.info("[NightlyChain] Starting post-market pipeline at %s", result["timestamp"])

    snr_table: dict[str, float] = {}

    # ── Stage 1: Mover Autopsy ─────────────────────────────────────────────
    try:
        from engine.mover_autopsy import mover_autopsy_engine

        autopsy = mover_autopsy_engine.perform_daily_autopsy()
        if autopsy:
            result["stage1_autopsy"] = autopsy.to_dict()
            snr_table = autopsy.factor_snr or {}
            result["stage2_snr"] = snr_table
            logger.info(
                "[NightlyChain] Stage 1 complete — %d gainers, %d losers, %d traps filtered",
                len(autopsy.gainers),
                len(autopsy.losers),
                autopsy.traps_filtered,
            )
        else:
            logger.warning("[NightlyChain] Stage 1: autopsy returned None")
    except Exception as exc:
        logger.error("[NightlyChain] Stage 1 failed: %s", exc, exc_info=True)

    # ── Stage 2: Explicit SNR Recalibration ────────────────────────────────
    # (belt-and-suspenders: perform_daily_autopsy already calls recalibrate_from_snr,
    #  but we call it again to guarantee execution even if stage 1 partially failed)
    if snr_table:
        try:
            from engine.learning_engine import pattern_learning_engine

            if hasattr(pattern_learning_engine, "recalibrate_from_snr"):
                pattern_learning_engine.recalibrate_from_snr(snr_table)
                top5 = {
                    k: round(v, 2) for k, v in sorted(snr_table.items(), key=lambda x: -x[1])[:5]
                }
                logger.info(
                    "[NightlyChain] Stage 2 complete — SNR recalibration. Top factors: %s", top5
                )
        except Exception as exc:
            logger.error("[NightlyChain] Stage 2 (SNR recalibration) failed: %s", exc)

    # ── Stage 2b: Alert Invalidation Post-Mortem & Recalibration ────────────
    try:
        from engine.alert_postmortem_runner import run_eod_alert_postmortems

        pm_report = run_eod_alert_postmortems(force=force)
        result["stage2b_alert_postmortems"] = pm_report
        logger.info(
            "[NightlyChain] Stage 2b complete — %d post-mortems conducted, %d outcomes recorded",
            pm_report.get("post_mortems_conducted", 0),
            pm_report.get("outcomes_recorded", 0),
        )
    except Exception as exc:
        logger.error("[NightlyChain] Stage 2b (alert post-mortems) failed: %s", exc)

    # ── Stage 3: Drift Detection + Closed-Loop Correction ─────────────────
    try:
        from engine.drift import nightly_drift_check

        drift_result = nightly_drift_check()
        result["stage3_drift"] = drift_result
        corrections = drift_result.get("corrections", {})
        if corrections.get("correction_applied"):
            logger.warning(
                "[NightlyChain] Stage 3: drift corrections applied — %s",
                " | ".join(corrections.get("actions_taken", [])),
            )
        else:
            logger.info(
                "[NightlyChain] Stage 3 complete — trend: %s, WR: %.0f%%",
                drift_result.get("report", {}).get("win_rate_trend", "?"),
                drift_result.get("report", {}).get("recent_win_rate", 0),
            )
    except Exception as exc:
        logger.error("[NightlyChain] Stage 3 (drift check) failed: %s", exc)

    result["status"] = "COMPLETED"

    # ── Stage 4: Telegram summary (best-effort) ────────────────────────────
    if send_telegram:
        try:
            _dispatch_telegram_summary(result)
        except Exception:
            pass

    logger.info("[NightlyChain] Pipeline complete. Status: %s", result["status"])
    return result


def _dispatch_telegram_summary(result: dict[str, Any]) -> None:
    """Send a concise post-market health digest via Telegram bot."""
    try:
        from bot.telegram_bot import get_telegram_bot

        bot = get_telegram_bot()
        if not bot:
            return

        autopsy = result.get("stage1_autopsy") or {}
        drift_rep = result.get("stage3_drift", {}).get("report", {})
        corrections = result.get("stage3_drift", {}).get("corrections", {})

        gainers_n = len(autopsy.get("gainers", []))
        losers_n = len(autopsy.get("losers", []))
        traps_n = autopsy.get("traps_filtered", 0)
        precursors = autopsy.get("top_predictive_precursors", [])[:3]
        trend = drift_rep.get("win_rate_trend", "N/A")
        wr = drift_rep.get("recent_win_rate", 0)
        delta = drift_rep.get("win_rate_delta", 0)
        trend_icon = {"IMPROVING": "📈", "DECLINING": "📉"}.get(trend, "➡️")
        acts = corrections.get("actions_taken", [])
        corr_text = ""
        if acts:
            corr_lines = "\n".join(f"  \u2022 {a[:80]}" for a in acts)
            corr_text = f"\n⚡ <b>Corrections Applied:</b>\n{corr_lines}"

        precursor_str = ", ".join(precursors) if precursors else "N/A"
        msg = (
            f"🌙 <b>ChanakyaTrade — Post-Market Digest</b>\n"
            f"<code>{result['timestamp']}</code>\n\n"
            f"📊 <b>Autopsy</b>: {gainers_n}G / {losers_n}L / {traps_n} traps\n"
            f"   Top precursors: {precursor_str}\n\n"
            f"{trend_icon} <b>Model Drift</b>: {wr:.0f}% WR | {trend} ({delta:+.0f}pp)"
            f"{corr_text}"
        )
        bot.send_message(msg)
    except Exception:
        pass


def schedule_nightly_chain(hour: int = 15, minute: int = 45) -> None:
    """
    Start a background daemon thread that fires the nightly chain
    at the given IST time on every weekday.

    Call this once at app startup (after broker login). No APScheduler dependency.
    """

    def _loop() -> None:
        while True:
            now = datetime.now(IST)
            if now.weekday() >= 5:
                _time.sleep(3600)
                continue
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now > target:
                target += timedelta(days=1)
            sleep_secs = (target - now).total_seconds()
            logger.info(
                "[NightlyChain] Next run in %.0fs at %s",
                sleep_secs,
                target.strftime("%Y-%m-%d %H:%M IST"),
            )
            _time.sleep(max(1, sleep_secs))
            try:
                threading.Thread(
                    target=run_nightly_post_market_chain,
                    name="nightly-chain-run",
                    daemon=True,
                ).start()
            except Exception as exc:
                logger.error("[NightlyChain] Launch failed: %s", exc)
            _time.sleep(60)  # Debounce — prevent double-fire in same minute

    t = threading.Thread(target=_loop, name="nightly-chain-scheduler", daemon=True)
    t.start()
    logger.info("[NightlyChain] Scheduler started — fires weekdays at %02d:%02d IST", hour, minute)
