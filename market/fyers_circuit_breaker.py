"""
market/fyers_circuit_breaker.py
───────────────────────────────
Fyers API Circuit Breaker with Automated Trip Mitigation.

State Transitions:
  - CLOSED   : Normal operation. Requests pass through.
  - OPEN     : Rate limit 429 or 3 consecutive network failures tripped.
               Blocks outgoing Fyers calls, returns DEGRADED status with last-known values.
               Dispatches SSE event and Telegram operational notification.
  - HALF_OPEN: Cooldown period expired (60s). Permits single probe request.
               On success -> resets to CLOSED.
               On failure -> returns to OPEN with new cooldown.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any

from config.constants import IST_ZONE as IST

logger = logging.getLogger(__name__)


def _seconds_until_midnight_ist() -> float:
    """Calculate remaining seconds until midnight in Indian Standard Time (IST)."""
    now_ist = datetime.now(IST)
    tomorrow_ist = (now_ist + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, (tomorrow_ist - now_ist).total_seconds())


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class FyersCircuitBreaker:
    """
    Thread-safe circuit breaker protecting Fyers API against multi-strike lockouts.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        failure_window_sec: float = 30.0,
        cooldown_sec: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._failure_window_sec = failure_window_sec
        self._cooldown_sec = cooldown_sec
        self._active_cooldown_sec = cooldown_sec

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._daily_quota_exhausted = False
        self._failure_timestamps: list[float] = []
        self._tripped_at: float = 0.0
        self._trip_reason: str = ""
        self._last_tg_alert_at: float = 0.0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_state_locked()
            return self._state

    def _evaluate_state_locked(self) -> None:
        now = time.time()
        if self._state == CircuitState.OPEN:
            if now - self._tripped_at >= self._active_cooldown_sec:
                self._state = CircuitState.HALF_OPEN
                logger.info("[CircuitBreaker] Cooldown elapsed; transitioning OPEN -> HALF_OPEN")

    def is_tripped(self) -> bool:
        """Return True if circuit breaker is currently OPEN (blocking requests)."""
        with self._lock:
            self._evaluate_state_locked()
            return self._state == CircuitState.OPEN

    def record_success(self) -> None:
        """Record successful Fyers call. Clears failures and resets HALF_OPEN -> CLOSED."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("[CircuitBreaker] Probe succeeded; resetting HALF_OPEN -> CLOSED")
                self._notify_recovery()
            self._state = CircuitState.CLOSED
            self._failure_timestamps.clear()

    def record_failure(
        self,
        status_code: int = 0,
        error_message: str = "",
        is_429: bool = False,
    ) -> None:
        """
        Record failed Fyers call.
        Trips immediately on HTTP 429 or when failure threshold is reached.
        """
        now = time.time()
        trip_needed = False
        reason = ""
        with self._lock:
            err_lower = (error_message or "").lower()
            is_daily_limit = (
                "standard plan limit" in err_lower
                or "5,000 requests" in err_lower
                or "5000 requests" in err_lower
                or "requests/day" in err_lower
                or "daily limit" in err_lower
                or "per day" in err_lower
            )

            # Check 429 Too Many Requests or -360 Rate Limit (10 req/s or 500 req/min rolling window on Prime)
            is_rate_limit = (
                is_429
                or status_code in (429, -360, 360)
                or "429" in str(status_code)
                or "-360" in str(status_code)
                or "-360" in str(error_message)
                or "rate limit" in err_lower
                or "limit" in err_lower
            )
            if is_daily_limit:
                trip_needed = True
                self._daily_quota_exhausted = True
                self._active_cooldown_sec = _seconds_until_midnight_ist()
                try:
                    from market.fyers_rate_gate import get_fyers_rate_gate

                    gate = get_fyers_rate_gate()
                    plan_name = gate.plan
                    max_day = int(gate._max_per_day)
                    reason = f"Fyers REST Daily Quota Limit Exceeded ({max_day:,} req/day {plan_name} Plan): {error_message}"
                    gate.record_external_exhaustion()
                except Exception as e_suppressed:
                    reason = f"Fyers REST Daily Quota Limit Exceeded: {error_message}"
                    logger.debug(
                        f"[market.fyers_circuit_breaker] Non-fatal exception suppressed: {e_suppressed}"
                    )
            elif is_rate_limit:
                trip_needed = True
                self._active_cooldown_sec = (
                    self._cooldown_sec
                )  # 60s cooldown allows rolling window to reset
                try:
                    from market.fyers_rate_gate import get_fyers_rate_gate

                    gate = get_fyers_rate_gate()
                    plan_name = gate.plan
                    limit_desc = (
                        f"10 req/s or 500 req/min ({plan_name} Plan)"
                        if plan_name == "PRIME"
                        else f"5 req/s or 50 req/min ({plan_name} Plan)"
                    )
                except Exception:
                    limit_desc = "10 req/s or rolling window"
                reason = f"Fyers REST Rate Limit Exceeded ({limit_desc}): {error_message}"
            else:
                self._failure_timestamps = [
                    t for t in self._failure_timestamps if now - t <= self._failure_window_sec
                ]
                self._failure_timestamps.append(now)

                if self._state == CircuitState.HALF_OPEN:
                    trip_needed = True
                    reason = f"Fyers probe call failed in HALF_OPEN: {error_message}"
                elif len(self._failure_timestamps) >= self._failure_threshold:
                    trip_needed = True
                    reason = (
                        f"{len(self._failure_timestamps)} consecutive Fyers failures in "
                        f"{self._failure_window_sec}s: {error_message}"
                    )

            if trip_needed and self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                self._tripped_at = now
                self._trip_reason = reason
                logger.error(
                    f"[CircuitBreaker] TRIPPED! Reason: {reason}. Cooldown: {self._active_cooldown_sec:.1f}s"
                )

        if trip_needed:
            self._dispatch_trip_notifications(reason)

    def _dispatch_trip_notifications(self, reason: str) -> None:
        """Emit SSE event and dispatch Telegram alert on trip."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Emit Server-Sent Event (SSE) to UI
        try:
            from web.sse import event_bus

            event_bus.publish_sync(
                "system",
                {
                    "type": "fyers_circuit_breaker_tripped",
                    "service": "FYERS_API",
                    "state": CircuitState.OPEN.value,
                    "daily_quota_exhausted": self._daily_quota_exhausted,
                    "cooldown_seconds": self._active_cooldown_sec,
                    "reason": reason,
                    "timestamp": now_iso,
                },
            )
        except Exception as exc:
            logger.warning(f"[CircuitBreaker] SSE publication failed: {exc}", exc_info=True)

        # 2. Dispatch Telegram alert (debounced)
        now = time.time()
        debounce_window = self._active_cooldown_sec if self._daily_quota_exhausted else 300.0
        if now - self._last_tg_alert_at >= debounce_window:
            self._last_tg_alert_at = now
            try:
                from bot.telegram_bot import send_push

                if self._daily_quota_exhausted:
                    tg_msg = (
                        f"🚨 <b>FYERS API DAILY REST QUOTA EXHAUSTED (5,000 req/day)</b> 🚨\n\n"
                        f"<b>Reason:</b> {reason}\n"
                        f"<b>Failsafe Action:</b> Blocking outbound Fyers REST calls until midnight IST. System running in <b>DEGRADED</b> "
                        f"mode using WebSocket ticker stream and cached feeds. Upgrade to Fyers Prime or enable secondary data broker (Shoonya/Angel One).\n"
                        f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                    )
                else:
                    tg_msg = (
                        f"🚨 <b>FYERS API CIRCUIT BREAKER TRIPPED</b> 🚨\n\n"
                        f"<b>Reason:</b> {reason}\n"
                        f"<b>Failsafe Action:</b> Blocking outbound Fyers calls. System running in <b>DEGRADED</b> "
                        f"mode using last-known cached values for {int(self._active_cooldown_sec)}s to prevent account ban.\n"
                        f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                    )
                send_push(tg_msg, parse_mode="HTML", bypass_dedup=True)
            except Exception as exc:
                logger.warning(
                    f"[CircuitBreaker] Telegram notification failed: {exc}", exc_info=True
                )

    def _notify_recovery(self) -> None:
        """Emit SSE event when circuit breaker recovers."""
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            from web.sse import event_bus

            event_bus.publish_sync(
                "system",
                {
                    "type": "fyers_circuit_breaker_recovered",
                    "service": "FYERS_API",
                    "state": CircuitState.CLOSED.value,
                    "timestamp": now_iso,
                },
            )
        except Exception as exc:
            logger.warning(f"[CircuitBreaker] SSE recovery broadcast failed: {exc}", exc_info=True)

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state and clear failure counters."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._daily_quota_exhausted = False
            self._active_cooldown_sec = self._cooldown_sec
            self._failure_timestamps.clear()
            self._tripped_at = 0.0
            self._trip_reason = ""
            logger.info("[CircuitBreaker] Manually reset to CLOSED")
        self._notify_recovery()

    def probe(self) -> None:
        """Manually advance circuit breaker to HALF_OPEN state to permit immediate probe call."""
        with self._lock:
            self._state = CircuitState.HALF_OPEN
            self._tripped_at = 0.0
            logger.info("[CircuitBreaker] Manually advanced to HALF_OPEN for probing")

    @property
    def is_daily_quota_exhausted(self) -> bool:
        """Return True if Fyers REST 5,000 requests/day quota was exceeded."""
        with self._lock:
            return self._daily_quota_exhausted

    def get_diagnostics(self) -> dict[str, Any]:
        """Return circuit breaker status for diagnostics endpoint."""
        with self._lock:
            self._evaluate_state_locked()
            now = time.time()
            remaining_cooldown = (
                max(0.0, self._active_cooldown_sec - (now - self._tripped_at))
                if self._state == CircuitState.OPEN
                else 0.0
            )
            return {
                "state": self._state.value,
                "is_tripped": self._state == CircuitState.OPEN,
                "daily_quota_exhausted": self._daily_quota_exhausted,
                "cooldown_seconds": self._active_cooldown_sec,
                "remaining_cooldown_seconds": round(remaining_cooldown, 1),
                "last_trip_reason": self._trip_reason,
                "recent_failures_count": len(self._failure_timestamps),
            }


# Global singleton
fyers_circuit_breaker = FyersCircuitBreaker()


def get_fyers_circuit_breaker() -> FyersCircuitBreaker:
    return fyers_circuit_breaker
