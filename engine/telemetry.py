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
import traceback
import uuid
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

MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per rotated log
MAX_BACKUP_FILES = 5


@dataclass
class TelemetryEvent:
    event_type: str
    component: str
    action_taken: str
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: dict[str, Any] = field(default_factory=dict)
    severity: str = "INFO"  # "INFO", "WARNING", "ERROR", "CRITICAL"
    incident_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── In-Memory Ring Buffer & File Persistence ────────────────────────────────

_MAX_IN_MEMORY_EVENTS = 500
_events_buffer: deque[TelemetryEvent] = deque(maxlen=_MAX_IN_MEMORY_EVENTS)
_lock = threading.Lock()


def sanitize_sensitive_data(obj: Any) -> Any:
    """Recursively scrub tokens, passwords, and secret keys from logs and payloads."""
    sensitive_substrings = {
        "password",
        "secret",
        "token",
        "totp",
        "api_key",
        "key",
        "auth",
        "credential",
        "pin",
    }
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in sensitive_substrings):
                cleaned[k] = "***REDACTED***"
            else:
                cleaned[k] = sanitize_sensitive_data(v)
        return cleaned
    elif isinstance(obj, list):
        return [sanitize_sensitive_data(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_sensitive_data(item) for item in obj)
    return obj


def _get_telemetry_file() -> Path:
    telemetry_dir = app_data_path("telemetry")
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    return telemetry_dir / "events.jsonl"


def _rotate_logs_if_needed(target_file: Path) -> None:
    """Rotate events.jsonl into events.1.jsonl ... events.5.jsonl if size exceeds cap."""
    if not target_file.exists():
        return
    try:
        if target_file.stat().st_size >= MAX_LOG_SIZE_BYTES:
            # Shift older backups
            for i in range(MAX_BACKUP_FILES - 1, 0, -1):
                old_f = target_file.parent / f"events.{i}.jsonl"
                new_f = target_file.parent / f"events.{i + 1}.jsonl"
                if old_f.exists():
                    if i + 1 > MAX_BACKUP_FILES:
                        old_f.unlink(missing_ok=True)
                    else:
                        old_f.replace(new_f)
            # Move current log to .1
            target_file.replace(target_file.parent / "events.1.jsonl")
    except Exception:
        pass


def record_event(
    event_type: str,
    component: str,
    action_taken: str,
    reason: str,
    details: Optional[dict[str, Any]] = None,
    severity: str = "INFO",
    incident_id: Optional[str] = None,
) -> TelemetryEvent:
    """
    Record a fallback, failover, or exception event.

    Thread-safe, size-rotated disk append with in-memory ring buffer.
    """
    clean_details = sanitize_sensitive_data(details or {})
    event = TelemetryEvent(
        event_type=event_type,
        component=component,
        action_taken=action_taken,
        reason=str(reason),
        details=clean_details,
        severity=severity,
        incident_id=incident_id,
    )

    with _lock:
        _events_buffer.append(event)
        try:
            target_file = _get_telemetry_file()
            _rotate_logs_if_needed(target_file)
            with target_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception:
            # Observability logging should never crash the caller
            pass

    return event


def record_exception(
    component: str,
    error: BaseException,
    action_taken: str = "Interception & Diagnostic Capture",
    context: Optional[dict[str, Any]] = None,
    severity: str = "ERROR",
) -> dict[str, Any]:
    """
    Record an unhandled exception with full stack trace, system vitals, and unique incident_id.
    """
    now = datetime.now(timezone.utc)
    incident_id = f"ERR-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    # Capture system memory and SSD status at the moment of failure
    vitals = {}
    try:
        from engine.memory_guard import get_memory_status
        vitals = get_memory_status().to_dict()
    except Exception:
        pass

    details = {
        "incident_id": incident_id,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "traceback": tb_str,
        "context": context or {},
        "system_vitals": vitals,
    }

    record_event(
        event_type=EVENT_EXCEPTION,
        component=component,
        action_taken=action_taken,
        reason=f"{type(error).__name__}: {str(error)[:120]}",
        details=details,
        severity=severity,
        incident_id=incident_id,
    )

    return {
        "incident_id": incident_id,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": now.isoformat(),
        "traceback": tb_str,
        "system_vitals": vitals,
    }


def get_error_incidents(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent error and exception incidents formatted for review and fixing."""
    with _lock:
        events = list(_events_buffer)

    events.reverse()
    incidents = []
    for ev in events:
        if ev.event_type == EVENT_EXCEPTION or ev.severity in ("ERROR", "CRITICAL"):
            incidents.append(ev.to_dict())
            if len(incidents) >= limit:
                break
    return incidents



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
        recommendations.append(
            "System running smoothly. All telemetry indicators within normal operational bounds."
        )

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
