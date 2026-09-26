"""
web/domain_events.py
────────────────────
Strongly-typed SSE Domain Event Contract for ChanakyaTrade.

Institutional Intent:
1. Schema Stability: Replaces loose dictionary broadcasts with validated domain dataclasses.
2. Cross-Boundary Integrity: Enforces contract consistency between Python backend and React frontend.
3. Observability & Audit Trail: Every event carries a correlation ID and exact timestamp.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from config.constants import IST

EventType = Literal[
    "ALERT_CREATED",
    "ALERT_IGNITED",
    "MILESTONE_ACHIEVED",
    "TRAILING_STOP_UPDATE",
    "IN_FLIGHT_WARNING",
    "ALERT_INVALIDATED",
    "RUNNER_CLOSED",
    "ALERT_EXPIRED",
    "RECONCILIATION_REPORT",
    "REGIME_SHIFT",
]


@dataclass(frozen=True)
class AlertDomainEvent:
    """
    Strongly-typed alert lifecycle event broadcast over SSE.
    """

    event_type: EventType
    alert_id: str
    symbol: str
    exchange: str
    stage: str
    headline: str
    summary: str
    ltp: float
    trigger_level: float
    target_level: float
    stop_loss: float
    correlation_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    timestamp_iso: str = field(default_factory=lambda: datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"))
    environment: str = "LIVE"
    metrics: dict[str, Any] = field(default_factory=dict)
    actionable_plan: dict[str, Any] = field(default_factory=dict)

    def to_sse_dict(self) -> dict[str, Any]:
        """Converts domain event to clean SSE broadcast dictionary."""
        d = asdict(self)
        # Flatten for frontend backward compatibility
        return {
            "type": self.event_type.lower(),
            "event_type": self.event_type,
            "data": d,
            "alert": d,
            "timestamp": self.timestamp_iso,
            "correlation_id": self.correlation_id,
        }


def create_alert_domain_event(
    alert: Any,
    event_type: EventType = "ALERT_CREATED",
    *,
    correlation_id: Optional[str] = None,
) -> AlertDomainEvent:
    """Factory helper converting an AutoAlert into a strongly-typed domain event."""
    return AlertDomainEvent(
        event_type=event_type,
        alert_id=getattr(alert, "alert_id", ""),
        symbol=getattr(alert, "symbol", ""),
        exchange=getattr(alert, "exchange", "NSE"),
        stage=getattr(alert, "stage", "EARLY_WARNING"),
        headline=getattr(alert, "headline", ""),
        summary=getattr(alert, "summary", ""),
        ltp=float(getattr(alert, "ltp", 0.0) or 0.0),
        trigger_level=float(getattr(alert, "trigger_level", 0.0) or 0.0),
        target_level=float(getattr(alert, "target_level", 0.0) or 0.0),
        stop_loss=float(getattr(alert, "stop_loss", 0.0) or 0.0),
        correlation_id=correlation_id or f"evt-{uuid.uuid4().hex[:8]}",
        timestamp_iso=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        environment=getattr(alert, "environment", "LIVE"),
        metrics=getattr(alert, "metrics", {}) or {},
        actionable_plan=getattr(alert, "actionable_plan", {}) or {},
    )
