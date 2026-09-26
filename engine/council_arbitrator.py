# engine/council_arbitrator.py
# Multi-Agent Council Pre-Screening Arbitrator
#
# Runs a 10-minute interval arbitration panel that:
#   1. Collects all fresh IGNITED alerts generated in the last 10 minutes.
#   2. Scores each setup deterministically via a multi-factor supremacy matrix.
#   3. Selects Top 2-3 Setups of the Day (SOTD) - highest absolute conviction.
#   4. Stamps winners with council_rank in actionable_plan.
#
# Scoring Matrix (deterministic, zero tokens):
#   - Base confidence (0-100): 40% weight
#   - R:R ratio (capped 6x): 25% weight
#   - Smart money score from metrics: 15% weight
#   - Spread-configured bonus: +5
#   - Expiry urgency bonus (weekly < 2 days): +3
#   - Benchmark alignment bonus: +4
#
# AGENTS.md invariant 15: Never invokes LLM on unfiltered scanner loops.

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_ARBITRATION_INTERVAL: float = 600.0
_SOTD_COUNT: int = 3
_FRESH_WINDOW: float = 660.0

_arb_lock = threading.Lock()
_last_arb_at: float = 0.0
_last_winners: list = []


def _score_alert(alert: object, nifty_posture: str = "NEUTRAL") -> float:
    try:
        conf = float(getattr(alert, "confidence", 60) or 60)
        ltp = float(getattr(alert, "ltp", 0) or 0)
        target = float(getattr(alert, "target_level", 0) or 0)
        sl = float(getattr(alert, "stop_loss", 0) or 0)
        metrics = getattr(alert, "metrics", {}) or {}
        direction = str(getattr(alert, "direction", "") or "")

        if ltp > 0 and target > 0 and sl > 0:
            risk = abs(ltp - sl)
            reward = abs(target - ltp)
            rr = min(reward / max(0.01, risk), 6.0)
        else:
            rr = 2.0

        sms = float(metrics.get("smart_money_score", 0) or 0)

        vix_bonus = 0.0
        action_plan = getattr(alert, "actionable_plan", {}) or {}
        preferred_vehicle = action_plan.get("preferred_vehicle", "") or ""
        if "SPREAD" in preferred_vehicle.upper():
            vix_bonus = 5.0

        expiry_bonus = 0.0
        expiry_date = getattr(alert, "expiry_date", None)
        if expiry_date:
            try:
                from dateutil.parser import parse as dateutil_parse
                exp_dt = dateutil_parse(expiry_date)
                days_to_exp = (exp_dt.date() - datetime.now(IST).date()).days
                if 0 < days_to_exp <= 2:
                    expiry_bonus = 3.0
            except Exception:
                pass

        bench_bonus = 0.0
        if nifty_posture == "BULLISH" and direction == "BULLISH":
            bench_bonus = 4.0
        elif nifty_posture == "BEARISH" and direction == "BEARISH":
            bench_bonus = 4.0

        score = (
            conf * 0.40
            + rr * 10.0 * 0.25
            + sms * 0.15
            + vix_bonus
            + expiry_bonus
            + bench_bonus
        )
        return round(score, 2)
    except Exception:
        return 50.0


def run_council_arbitration(engine: object) -> list:
    global _last_arb_at, _last_winners

    now = time.time()
    with _arb_lock:
        if (now - _last_arb_at) < _ARBITRATION_INTERVAL:
            return _last_winners[:]

    try:
        alerts = list(getattr(engine, "_alerts", []) or [])
    except Exception:
        return []

    fresh_cutoff = now - _FRESH_WINDOW
    candidates = []
    for a in alerts:
        if getattr(a, "is_invalidated", False) or getattr(a, "is_archived", False):
            continue
        if getattr(a, "stage", "") not in ("IGNITED", "EARLY_WARNING", "ACTIVE"):
            continue
        created_at_str = getattr(a, "created_at", "") or ""
        try:
            from dateutil.parser import parse as dateutil_parse
            created_epoch = dateutil_parse(created_at_str).timestamp()
        except Exception:
            created_epoch = now

        if created_epoch >= fresh_cutoff:
            candidates.append(a)

    if not candidates:
        with _arb_lock:
            _last_arb_at = now
            _last_winners = []
        return []

    nifty_posture = "NEUTRAL"
    try:
        from market.indices import get_market_snapshot
        snap = get_market_snapshot()
        nifty_posture = snap.posture
    except Exception:
        pass

    scored = [(a, _score_alert(a, nifty_posture)) for a in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    winners = scored[:_SOTD_COUNT]

    winner_ids: list = []
    for rank, (alert, score) in enumerate(winners, start=1):
        alert_id = getattr(alert, "alert_id", "")
        action_plan = getattr(alert, "actionable_plan", None)
        if not isinstance(action_plan, dict):
            try:
                alert.actionable_plan = {}
                action_plan = alert.actionable_plan
            except Exception:
                action_plan = {}

        action_plan["council_rank"] = rank
        action_plan["council_score"] = score
        action_plan["council_approved"] = True
        action_plan["council_note"] = (
            "SOTD #%d: Selected by Multi-Agent Council arbitration (score %.1f). "
            "Benchmark: %s. This is the highest-conviction setup in current cycle."
            % (rank, score, nifty_posture)
        )
        winner_ids.append(alert_id)
        logger.info(
            "[CouncilArbitrator] SOTD #%d: %s %s %s (score=%.1f, conf=%s)",
            rank,
            getattr(alert, "symbol", "?"),
            getattr(alert, "direction", "?"),
            getattr(alert, "alert_type", "?"),
            score,
            getattr(alert, "confidence", "?"),
        )

    winner_set = set(winner_ids)
    for a in candidates:
        if getattr(a, "alert_id", "") not in winner_set:
            action_plan = getattr(a, "actionable_plan", None)
            if isinstance(action_plan, dict):
                action_plan["council_approved"] = False

    try:
        engine._save()
    except Exception:
        pass

    with _arb_lock:
        _last_arb_at = now
        _last_winners = winner_ids[:]

    logger.info(
        "[CouncilArbitrator] Arbitration complete: %d candidates -> %d SOTD winners. Benchmark: %s",
        len(candidates), len(winner_ids), nifty_posture,
    )
    return winner_ids


def should_run_arbitration() -> bool:
    with _arb_lock:
        return (time.time() - _last_arb_at) >= _ARBITRATION_INTERVAL


def get_last_winners() -> list:
    with _arb_lock:
        return _last_winners[:]
