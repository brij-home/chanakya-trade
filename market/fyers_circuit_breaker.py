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
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


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

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
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
            if now - self._tripped_at >= self._cooldown_sec:
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
            # Check 429 Too Many Requests
            if (
                is_429
                or status_code == 429
                or "429" in error_message
                or "rate limit" in error_message.lower()
            ):
                trip_needed = True
                reason = f"Fyers Rate Limit Exceeded (HTTP 429): {error_message}"
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
                    f"[CircuitBreaker] TRIPPED! Reason: {reason}. Cooldown: {self._cooldown_sec}s"
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
                    "cooldown_seconds": self._cooldown_sec,
                    "reason": reason,
                    "timestamp": now_iso,
                },
            )
        except Exception as exc:
            logger.warning(f"[CircuitBreaker] SSE publication failed: {exc}", exc_info=True)

        # 2. Dispatch Telegram alert (debounced)
        now = time.time()
        if now - self._last_tg_alert_at >= self._cooldown_sec:
            self._last_tg_alert_at = now
            try:
                from bot.telegram_bot import send_push

                tg_msg = (
                    f"🚨 <b>FYERS API CIRCUIT BREAKER TRIPPED</b> 🚨\n\n"
                    f"<b>Reason:</b> {reason}\n"
                    f"<b>Failsafe Action:</b> Blocking outbound Fyers calls. System running in <b>DEGRADED</b> "
                    f"mode using last-known cached values for {int(self._cooldown_sec)}s to prevent account ban.\n"
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

    def get_diagnostics(self) -> dict[str, Any]:
        """Return circuit breaker status for diagnostics endpoint."""
        with self._lock:
            self._evaluate_state_locked()
            now = time.time()
            remaining_cooldown = (
                max(0.0, self._cooldown_sec - (now - self._tripped_at))
                if self._state == CircuitState.OPEN
                else 0.0
            )
            return {
                "state": self._state.value,
                "is_tripped": self._state == CircuitState.OPEN,
                "cooldown_seconds": self._cooldown_sec,
                "remaining_cooldown_seconds": round(remaining_cooldown, 1),
                "last_trip_reason": self._trip_reason,
                "recent_failures_count": len(self._failure_timestamps),
            }


# Global singleton
fyers_circuit_breaker = FyersCircuitBreaker()


def get_fyers_circuit_breaker() -> FyersCircuitBreaker:
    return fyers_circuit_breaker
