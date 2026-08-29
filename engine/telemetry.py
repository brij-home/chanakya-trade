"""
engine/telemetry.py
───────────────────
Institutional Observability, Fallback & Exception Telemetry for ChanakyaTrade.

Captures, persists, and analyzes:
  - LLM Failovers & Rate Limit Cooldowns (503, 429, Quota exhaustion)
  - Deterministic Quantitative Fallbacks (Rule-based vs LLM)
  - Market Data Fallbacks (Live Ticks vs EOD Historical vs Mock)
  - Broker Routing Failovers (Fyers -> Zerodha -> Mock)
  - System Exceptions & Edge Conditions

Provides structured self-learning summaries and actionable architectural recommendations.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config.paths import app_data_path


# ── Event Types ─────────────────────────────────────────────────────────────

EVENT_LLM_FAILOVER = "LLM_FAILOVER"
EVENT_LLM_COOLDOWN = "LLM_COOLDOWN"
EVENT_QUANT_FALLBACK = "QUANT_FALLBACK"
EVENT_DATA_FALLBACK = "DATA_FALLBACK"
EVENT_BROKER_FAILOVER = "BROKER_FAILOVER"
EVENT_EXCEPTION = "EXCEPTION"
EVENT_API_RETRY = "API_RETRY"

VALID_EVENT_TYPES = {
    EVENT_LLM_FAILOVER,
    EVENT_LLM_COOLDOWN,
    EVENT_QUANT_FALLBACK,
    EVENT_DATA_FALLBACK,
    EVENT_BROKER_FAILOVER,
    EVENT_EXCEPTION,
    EVENT_API_RETRY,
}


@dataclass
class TelemetryEvent:
    event_type: str
    component: str
    action_taken: str
    reason: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: dict[str, Any] = field(default_factory=dict)
    severity: str = "INFO"  # "INFO", "WARNING", "ERROR", "CRITICAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── In-Memory Ring Buffer & File Persistence ────────────────────────────────

_MAX_IN_MEMORY_EVENTS = 500
_events_buffer: deque[TelemetryEvent] = deque(maxlen=_MAX_IN_MEMORY_EVENTS)
_lock = threading.Lock()


def _get_telemetry_file() -> Path:
    telemetry_dir = app_data_path("telemetry")
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    return telemetry_dir / "events.jsonl"


def record_event(
    event_type: str,
    component: str,
    action_taken: str,
    reason: str,
    details: Optional[dict[str, Any]] = None,
    severity: str = "INFO",
) -> TelemetryEvent:
    """
    Record a fallback, failover, or exception event.

    Thread-safe, non-blocking disk append with in-memory ring buffer.
    """
    event = TelemetryEvent(
        event_type=event_type,
        component=component,
        action_taken=action_taken,
        reason=str(reason),
        details=details or {},
        severity=severity,
    )

    with _lock:
        _events_buffer.append(event)
        try:
            target_file = _get_telemetry_file()
            with target_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception:
            # Observability logging should never crash the caller
            pass

    return event


def get_recent_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return the most recent telemetry events matching optional filters."""
    with _lock:
        events = list(_events_buffer)

    # Reverse to return newest first
    events.reverse()

    filtered = []
    for ev in events:
        if event_type and ev.event_type != event_type:
            continue
        if severity and ev.severity != severity:
            continue
        filtered.append(ev.to_dict())
        if len(filtered) >= limit:
            break

    return filtered


def get_telemetry_summary() -> dict[str, Any]:
    """
    Generate an institutional telemetry summary with failure pattern diagnosis
    and actionable engineering recommendations.
    """
    with _lock:
        events = list(_events_buffer)

    total_events = len(events)
    type_counts = Counter(ev.event_type for ev in events)
    component_counts = Counter(ev.component for ev in events)
    severity_counts = Counter(ev.severity for ev in events)

    # Extract common error patterns
    error_reasons = Counter()
    for ev in events:
        if ev.severity in ("WARNING", "ERROR", "CRITICAL") or ev.event_type in (
            EVENT_LLM_COOLDOWN,
            EVENT_EXCEPTION,
        ):
            # Shorten reason to top 60 chars
            short_reason = ev.reason[:60] if ev.reason else "Unknown"
            error_reasons[short_reason] += 1

    # Formulate recommendations
    recommendations = []
    if type_counts.get(EVENT_LLM_COOLDOWN, 0) > 3:
        recommendations.append(
            "Frequent LLM cooldowns detected: Consider adding additional pooled API keys or switching AI_FAST_MODEL to a higher quota tier (e.g. gemini-3.5-flash-lite / Groq)."
        )
    if type_counts.get(EVENT_DATA_FALLBACK, 0) > 5:
        recommendations.append(
            "Frequent market data fallbacks to EOD: Verify broker API credentials or SEBI IPv4 whitelisting if live trading during market hours."
        )
    if type_counts.get(EVENT_QUANT_FALLBACK, 0) > 0:
        recommendations.append(
            f"Deterministic quantitative fallback executed {type_counts[EVENT_QUANT_FALLBACK]} time(s): Protected user experience from LLM network timeout."
        )
    if not recommendations:
        recommendations.append("System running smoothly. All telemetry indicators within normal operational bounds.")

    return {
        "status": "HEALTHY" if severity_counts.get("CRITICAL", 0) == 0 else "DEGRADED",
        "total_events_captured": total_events,
        "event_breakdown": dict(type_counts),
        "component_breakdown": dict(component_counts),
        "severity_breakdown": dict(severity_counts),
        "top_error_patterns": dict(error_reasons.most_common(5)),
        "recommendations": recommendations,
        "recent_fallbacks": [ev.to_dict() for ev in reversed(events[-10:])],
    }


def clear_telemetry() -> None:
    """Clear in-memory and disk telemetry logs."""
    with _lock:
        _events_buffer.clear()
        try:
            target_file = _get_telemetry_file()
            if target_file.exists():
                target_file.unlink()
        except Exception:
            pass
