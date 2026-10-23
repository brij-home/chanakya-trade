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
import logging

logger = logging.getLogger("engine.telemetry")


import json
import threading
import time
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
    priority: str = "P3"  # "P0", "P1", "P2", "P3"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_priority(event_type: str, component: str, severity: str, reason: str) -> str:
    """Classify incident into institutional priority levels P0 (Critical) to P3 (Info)."""
    sev = (severity or "INFO").upper()
    comp = (component or "").upper()
    rsn = (reason or "").upper()

    # Multi-key LLM failover, Guardian screening vetoes, risk suppressions, delisted/expired symbols,
    # in-flight trade coaching/warnings, and self-healing rewrites are informational audits (P3)
    if event_type == EVENT_LLM_FAILOVER or any(
        k in rsn
        for k in (
            "VETO",
            "CODE -300",
            "INVALID_SYMBOLS",
            "PLEASE PROVIDE A VALID SYMBOL",
            "DELISTED",
            "EXPIRED",
            "SUPPRESS",
            "POLARIZATION",
            "REWRITING",
            "IN-FLIGHT WARNING",
            "NO PRICE DATA FOUND",
            "POSSIBLY DELISTED",
            "FAILOVER TO FALLBACK",
            "THROTTLED OR HIGH DEMAND",
        )
    ):
        return "P3"

    if (
        sev == "CRITICAL"
        or "ORDER" in comp
        or "EXECUTION" in comp
        or "FREEZE" in rsn
        or "CIRCUIT BREAKER" in rsn
        or "LOCKOUT" in rsn
    ):
        return "P0"
    if sev in ("ERROR", "WARNING") and (
        sev == "ERROR"
        or event_type in (EVENT_LLM_COOLDOWN, EVENT_DATA_FALLBACK, EVENT_QUANT_FALLBACK)
        or "RATE LIMIT" in rsn
        or "429" in rsn
        or "TIMEOUT" in rsn
        or "-360" in rsn
    ):
        return "P1"
    if sev == "WARNING" or event_type == EVENT_API_RETRY or "LATENCY" in rsn or "DEGRADED" in rsn:
        return "P2"
    return "P3"


# ── In-Memory Ring Buffer & File Persistence ────────────────────────────────

_MAX_IN_MEMORY_EVENTS = 500
_events_buffer: deque[TelemetryEvent] = deque(maxlen=_MAX_IN_MEMORY_EVENTS)
_lock = threading.Lock()


def _get_telemetry_file() -> Path:
    telemetry_dir = app_data_path("telemetry")
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    return telemetry_dir / "events.jsonl"


def _load_recent_events_from_disk(limit: int = 250) -> None:
    """
    Safely pre-populate in-memory ring buffer with recent incidents from disk on startup.
    Guarantees zero operational amnesia across process restarts while keeping startup fast and bounded.
    """
    try:
        target_file = _get_telemetry_file()
        if not target_file.exists():
            return
        loaded: list[TelemetryEvent] = []
        with target_file.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    ev_type = data.get("event_type", "INCIDENT")
                    comp = data.get("component", "SYSTEM")
                    sev = data.get("severity", "INFO")
                    rsn = data.get("reason", "")
                    # Suppress spurious Starlette SSE client disconnect or Windows socket teardown artifacts from historical memory
                    if any(
                        s in rsn
                        for s in (
                            "RuntimeError: No response returned.",
                            "Accept failed on a socket",
                            "IocpProactor.accept",
                            "Task exception was never retrieved",
                        )
                    ):
                        continue
                    prio = data.get("priority")
                    comp_lower = comp.lower()
                    is_ext = any(
                        ign in comp_lower
                        for ign in (
                            "yfinance",
                            "urllib3",
                            "websocket",
                            "fyerswebsocket",
                            "fyersdatasocket",
                            "fyerstbtsocket",
                            "httpcore",
                            "starlette",
                        )
                    )
                    is_rate_lim = (
                        "429" in rsn
                        or "RATE LIMIT" in rsn.upper()
                        or "TOO MANY REQUESTS" in rsn.upper()
                    )
                    if is_ext:
                        if is_rate_lim:
                            prio = "P2"
                        else:
                            prio = "P3" if sev != "ERROR" else "P2"
                    elif ev_type == EVENT_LLM_FAILOVER or any(
                        k in rsn.upper()
                        for k in (
                            "VETO",
                            "CODE -300",
                            "INVALID_SYMBOLS",
                            "PLEASE PROVIDE A VALID SYMBOL",
                            "DELISTED",
                            "EXPIRED",
                            "SUPPRESS",
                            "POLARIZATION",
                            "REWRITING",
                            "IN-FLIGHT WARNING",
                            "THROTTLED OR HIGH DEMAND",
                        )
                    ):
                        prio = "P3"
                    elif (
                        not prio
                        or prio not in ("P0", "P1", "P2", "P3")
                        or "CIRCUIT" in rsn.upper()
                        or "VETO" in rsn.upper()
                    ):
                        prio = derive_priority(ev_type, comp, sev, rsn)
                    ev = TelemetryEvent(
                        event_type=ev_type,
                        component=comp,
                        action_taken=data.get("action_taken", ""),
                        reason=rsn,
                        timestamp=data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                        details=data.get("details", {}),
                        severity=sev,
                        incident_id=data.get("incident_id"),
                        priority=prio,
                    )
                    loaded.append(ev)
                    if len(loaded) > limit * 2:
                        loaded = loaded[-limit:]
                except Exception:
                    continue
        with _lock:
            _events_buffer.clear()
            for ev in loaded[-limit:]:
                _events_buffer.append(ev)
    except Exception as e_suppressed:
        logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")


# Pre-warm buffer from disk
_load_recent_events_from_disk(limit=250)


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
    except Exception as e_suppressed:
        logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")


def record_event(
    event_type: str,
    component: str,
    action_taken: str,
    reason: str,
    details: Optional[dict[str, Any]] = None,
    severity: str = "INFO",
    incident_id: Optional[str] = None,
    priority: Optional[str] = None,
) -> TelemetryEvent:
    """
    Record a fallback, failover, or exception event.

    Thread-safe, size-rotated disk append with in-memory ring buffer.
    """
    clean_details = sanitize_sensitive_data(details or {})
    resolved_priority = priority or derive_priority(event_type, component, severity, reason)
    event = TelemetryEvent(
        event_type=event_type,
        component=component,
        action_taken=action_taken,
        reason=str(reason),
        details=clean_details,
        severity=severity,
        incident_id=incident_id,
        priority=resolved_priority,
    )

    with _lock:
        _events_buffer.append(event)
        try:
            target_file = _get_telemetry_file()
            _rotate_logs_if_needed(target_file)
            with target_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e_suppressed:
            # Observability logging should never crash the caller
            logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")

    # Real-time SSE dispatch for critical/high priority incidents
    if resolved_priority in ("P0", "P1"):
        try:
            from web.sse import event_bus

            event_bus.publish_sync(
                "system",
                {
                    "type": "system_incident",
                    "incident": event.to_dict(),
                },
            )
        except Exception as e_suppressed:
            logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")

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
    err_str = str(error)
    # Ignore spurious Starlette SSE client disconnect artifacts
    if (
        "No response returned" in err_str
        and context
        and (
            "stream" in context.get("path", "")
            or "text/event-stream" in str(context.get("headers", {}).get("accept", "")).lower()
        )
    ):
        return {
            "incident_id": "DISCONNECT-IGNORED",
            "error_type": type(error).__name__,
            "error_message": err_str,
        }

    now = datetime.now(timezone.utc)
    incident_id = f"ERR-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    # Capture system memory and SSD status at the moment of failure
    vitals = {}
    try:
        from engine.memory_guard import get_memory_status

        vitals = get_memory_status().to_dict()
    except Exception as e_suppressed:
        logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")

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


def get_prioritized_incidents(
    limit: int = 100,
    priority: Optional[str] = None,
    component: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return incidents matching priority and component filters, sorted newest first."""
    with _lock:
        events = list(_events_buffer)

    events.reverse()
    results = []
    target_prio = priority.upper() if priority else None
    target_comp = component.lower() if component else None

    for ev in events:
        ev_prio = getattr(ev, "priority", None) or "P3"
        if target_prio and ev_prio != target_prio:
            continue
        if target_comp and target_comp not in (ev.component or "").lower():
            continue
        results.append(ev.to_dict())
        if len(results) >= limit:
            break
    return results


def get_incident_counts(window_minutes: Optional[int] = None) -> dict[str, int]:
    """Return counts of events segregated by priority level.

    Args:
        window_minutes: If specified, counts only events occurring within the
            last N minutes (for active system health evaluation). If None,
            counts all events in the in-memory rolling buffer.
    """
    with _lock:
        events = list(_events_buffer)
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    now = datetime.now(timezone.utc)

    for ev in events:
        if window_minutes is not None:
            ts_str = getattr(ev, "timestamp", None)
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if (now - ts).total_seconds() > window_minutes * 60:
                        continue
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}"
                    )
        p = getattr(ev, "priority", None)
        if not p or p not in counts:
            p = derive_priority(
                getattr(ev, "event_type", "INCIDENT"),
                getattr(ev, "component", "SYSTEM"),
                getattr(ev, "severity", "INFO"),
                getattr(ev, "reason", ""),
            )
        counts[p] = counts.get(p, 0) + 1
    return counts


def query_historical_events(
    limit: int = 100,
    priority: Optional[str] = None,
    component: Optional[str] = None,
    event_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Query historical telemetry events directly from disk archives.
    Reads newest-to-oldest across events.jsonl and rotated events.1.jsonl ... events.5.jsonl.
    """
    results: list[dict[str, Any]] = []
    target_prio = priority.upper() if priority else None
    target_comp = component.lower() if component else None
    target_type = event_type.upper() if event_type else None

    telemetry_dir = app_data_path("telemetry")
    files_to_check = [telemetry_dir / "events.jsonl"]
    for i in range(1, MAX_BACKUP_FILES + 1):
        f = telemetry_dir / f"events.{i}.jsonl"
        if f.exists():
            files_to_check.append(f)

    for fpath in files_to_check:
        if not fpath.exists():
            continue
        try:
            lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue

                ev_prio = data.get("priority")
                if not ev_prio or ev_prio not in ("P0", "P1", "P2", "P3"):
                    ev_prio = derive_priority(
                        data.get("event_type", "INCIDENT"),
                        data.get("component", "SYSTEM"),
                        data.get("severity", "INFO"),
                        data.get("reason", ""),
                    )
                    data["priority"] = ev_prio

                if target_prio and ev_prio != target_prio:
                    continue
                if target_comp and target_comp not in (data.get("component") or "").lower():
                    continue
                if target_type and (data.get("event_type") or "").upper() != target_type:
                    continue

                results.append(data)
                if len(results) >= limit:
                    return results
        except Exception as e_suppressed:
            logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")

    return results


def clear_telemetry() -> None:
    """Clear in-memory and disk telemetry logs."""
    with _lock:
        _events_buffer.clear()
        TelemetryLogHandler._seen_hashes.clear()
        try:
            telemetry_dir = app_data_path("telemetry")
            target_file = telemetry_dir / "events.jsonl"
            if target_file.exists():
                target_file.unlink()
            for i in range(1, MAX_BACKUP_FILES + 1):
                bf = telemetry_dir / f"events.{i}.jsonl"
                if bf.exists():
                    bf.unlink()
        except Exception as e_suppressed:
            logger.debug(f"[engine.telemetry] Non-fatal exception suppressed: {e_suppressed}")


class TelemetryLogHandler(logging.Handler):
    """
    Automatic logging bridge: Captures application ERROR/CRITICAL logs (and important warnings)
    and records them as prioritized incidents in engine.telemetry for OpsDeck visibility.
    """

    _seen_hashes: dict[str, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Prevent infinite recursion if logging comes from telemetry itself
            if record.name.startswith("engine.telemetry"):
                return

            if record.levelno < logging.WARNING:
                return

            msg = str(record.getMessage())
            rec_name = str(record.name or "")

            # Deduplicate frequent identical log messages within 10 seconds
            import hashlib

            h = hashlib.md5(f"{record.name}:{msg}".encode("utf-8")).hexdigest()
            now_ts = time.time()
            last_ts = self._seen_hashes.get(h, 0.0)
            if now_ts - last_ts < 10.0:
                return
            self._seen_hashes[h] = now_ts
            if len(self._seen_hashes) > 200:
                cutoff = now_ts - 60.0
                self._seen_hashes = {k: v for k, v in self._seen_hashes.items() if v > cutoff}

            # Ignore routine process shutdown socket teardowns
            if any(
                s in msg
                for s in (
                    "Accept failed on a socket",
                    "IocpProactor.accept",
                    "RuntimeError: No response returned.",
                )
            ):
                return

            # Benign external scraper noise or normal socket closures should not trigger P1 critical alert
            is_external_noise = any(
                ign in rec_name.lower()
                for ign in (
                    "yfinance",
                    "urllib3",
                    "websocket",
                    "httpcore",
                    "starlette",
                    "fyerswebsocket",
                    "fyersdatasocket",
                    "fyerstbtsocket",
                )
            )
            is_rate_limit = (
                "429" in msg or "RATE LIMIT" in msg.upper() or "TOO MANY REQUESTS" in msg.upper()
            )

            if is_external_noise:
                # Scraper ticker misses or routine socket drops are operational diagnostics
                # Fyers broker socket invalid_symbols feedback is P3 informational audit
                if any(
                    k in msg.upper()
                    for k in ("CODE -300", "INVALID_SYMBOLS", "PLEASE PROVIDE A VALID SYMBOL")
                ):
                    severity = "INFO"
                    priority = "P3"
                elif is_rate_limit:
                    # External socket/scraper rate throttle with active backoff is P2 Warning (degraded rate gate)
                    severity = "WARNING"
                    priority = "P2"
                else:
                    severity = "INFO" if record.levelno < logging.ERROR else "WARNING"
                    priority = "P3" if record.levelno < logging.ERROR else "P2"
            else:
                prio = derive_priority("SYSTEM_LOG", record.name, record.levelname, msg)
                if any(
                    k in msg.upper()
                    for k in (
                        "VETO",
                        "CODE -300",
                        "INVALID_SYMBOLS",
                        "PLEASE PROVIDE A VALID SYMBOL",
                        "DELISTED",
                        "EXPIRED",
                        "SUPPRESS",
                        "POLARIZATION",
                        "REWRITING",
                        "IN-FLIGHT WARNING",
                        "THROTTLED OR HIGH DEMAND",
                    )
                ):
                    severity = "INFO"
                    priority = "P3"
                elif record.levelno >= logging.ERROR:
                    severity = "ERROR"
                    priority = prio if prio in ("P0", "P1") else "P1"
                else:
                    severity = "WARNING"
                    priority = prio if prio in ("P2", "P3") else "P2"

            record_event(
                event_type="SYSTEM_LOG",
                component=record.name,
                action_taken="LOG_RECORDED",
                reason=msg[:140],
                severity=severity,
                priority=priority,
                details={
                    "logger": record.name,
                    "level": record.levelname,
                    "message": msg,
                    "pathname": record.pathname,
                    "lineno": record.lineno,
                },
            )
        except Exception:
            self.handleError(record)


_telemetry_handler_installed = False


def install_telemetry_log_handler() -> None:
    """Attach TelemetryLogHandler to the root logger to bridge all logs to OpsDeck."""
    global _telemetry_handler_installed
    if _telemetry_handler_installed:
        return
    try:
        handler = TelemetryLogHandler()
        handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(handler)
        _telemetry_handler_installed = True
    except Exception as exc:
        logger.debug(f"[engine.telemetry] Could not attach log handler: {exc}")


# Auto-install log handler on module load
install_telemetry_log_handler()
