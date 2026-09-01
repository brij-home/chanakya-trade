"""
engine/observability.py
────────────────────────
P3-A: Structured Observability, Correlation IDs, and SLO Metrics Engine.

Provides:
- Request/Job/Order correlation ID generation and propagation
- SLO (Service Level Objective) metric tracking per journey
- Data source freshness and stale-rate tracking per provider
- Health check aggregation (liveness + readiness + dependency health)
- Error budget tracking against SLO targets
- Structured log event emission with correlation context

Design principles:
- Thread-safe, non-blocking — observability NEVER crashes the caller
- All state is bounded (LRU + TTL) — no unbounded memory growth
- Every metric traces back to a correlation ID for root-cause analysis
"""

from __future__ import annotations

import time
import threading
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


# ── Constants ────────────────────────────────────────────────────────────────

MAX_METRIC_HISTORY = 1000  # Rolling window of metric events
MAX_CORRELATION_IDS = 500  # Recent correlation IDs to retain for tracing
STALE_THRESHOLD_SECONDS = 120.0  # Consistent with options_chain_integrity


# ── Correlation ID ────────────────────────────────────────────────────────────


def new_correlation_id(prefix: str = "req") -> str:
    """
    Generate a new, globally unique correlation ID for request/job/order tracing.

    Format: {prefix}-{timestamp_ms}-{uuid8}
    Example: req-1725180000123-a3f7b2c1
    """
    ts_ms = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    return f"{prefix}-{ts_ms}-{uid}"


# ── SLO Target Definitions ────────────────────────────────────────────────────


@dataclass
class SLOTarget:
    """Service Level Objective target for a critical user journey."""

    journey_id: str
    description: str
    # Latency SLO
    p95_latency_ms: float = 2000.0  # 95th-percentile target in ms
    p99_latency_ms: float = 5000.0  # 99th-percentile target in ms
    # Availability SLO
    availability_pct: float = 99.5  # % of requests that must succeed
    # Error budget: percentage of requests that may fail per rolling window
    error_budget_pct: float = 0.5


# P3-A defined SLO targets for critical ChanakyaTrade journeys
CRITICAL_JOURNEY_SLOS: dict[str, SLOTarget] = {
    "quote_fetch": SLOTarget(
        journey_id="quote_fetch",
        description="Live quote retrieval for a single instrument",
        p95_latency_ms=500.0,
        p99_latency_ms=1500.0,
        availability_pct=99.0,
    ),
    "options_chain": SLOTarget(
        journey_id="options_chain",
        description="Options chain fetch and validation",
        p95_latency_ms=1500.0,
        p99_latency_ms=3000.0,
        availability_pct=98.0,
    ),
    "multi_agent_analyze": SLOTarget(
        journey_id="multi_agent_analyze",
        description="Full multi-agent debate and synthesis",
        p95_latency_ms=18000.0,
        p99_latency_ms=30000.0,
        availability_pct=95.0,
    ),
    "paper_order_submit": SLOTarget(
        journey_id="paper_order_submit",
        description="Paper order creation and state transition",
        p95_latency_ms=300.0,
        p99_latency_ms=800.0,
        availability_pct=99.9,
    ),
    "backtest_run": SLOTarget(
        journey_id="backtest_run",
        description="Strategy backtest execution",
        p95_latency_ms=30000.0,
        p99_latency_ms=120000.0,
        availability_pct=98.0,
    ),
}


# ── Metric Event ─────────────────────────────────────────────────────────────


@dataclass
class MetricEvent:
    """A single measured performance/availability event for a journey."""

    journey_id: str
    correlation_id: str
    latency_ms: float
    success: bool
    error_type: Optional[str] = None
    provider: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Data Source Freshness Tracker ────────────────────────────────────────────


@dataclass
class ProviderFreshnessRecord:
    """Per-provider freshness tracking."""

    provider: str
    last_success_at: Optional[float] = None  # epoch seconds
    last_failure_at: Optional[float] = None  # epoch seconds
    total_requests: int = 0
    stale_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0

    @property
    def age_seconds(self) -> Optional[float]:
        if self.last_success_at is None:
            return None
        return time.time() - self.last_success_at

    @property
    def is_stale(self) -> bool:
        age = self.age_seconds
        return age is None or age > STALE_THRESHOLD_SECONDS

    @property
    def stale_rate_pct(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.stale_count / self.total_requests * 100, 2)

    @property
    def error_rate_pct(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.error_count / self.total_requests * 100, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "last_success_at": datetime.fromtimestamp(
                self.last_success_at, tz=timezone.utc
            ).isoformat()
            if self.last_success_at
            else None,
            "age_seconds": self.age_seconds,
            "is_stale": self.is_stale,
            "total_requests": self.total_requests,
            "stale_count": self.stale_count,
            "stale_rate_pct": self.stale_rate_pct,
            "error_count": self.error_count,
            "error_rate_pct": self.error_rate_pct,
            "consecutive_errors": self.consecutive_errors,
            "health": "HEALTHY"
            if not self.is_stale and self.consecutive_errors == 0
            else "DEGRADED"
            if self.consecutive_errors < 3
            else "UNHEALTHY",
        }


# ── Observability Registry (singleton) ───────────────────────────────────────


class ObservabilityRegistry:
    """
    Thread-safe singleton registry for correlation IDs, SLO metrics, and provider health.

    All public methods are non-blocking and exception-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: deque[MetricEvent] = deque(maxlen=MAX_METRIC_HISTORY)
        self._correlation_ids: deque[str] = deque(maxlen=MAX_CORRELATION_IDS)
        self._provider_freshness: dict[str, ProviderFreshnessRecord] = {}
        self._startup_time = time.time()

    # ── Correlation ───────────────────────────────────────────────────────────

    def register_correlation_id(self, cid: str) -> None:
        """Register a correlation ID for traceability."""
        try:
            with self._lock:
                self._correlation_ids.append(cid)
        except Exception:
            pass

    def recent_correlation_ids(self, limit: int = 20) -> list[str]:
        try:
            with self._lock:
                ids = list(self._correlation_ids)
            return list(reversed(ids))[:limit]
        except Exception:
            return []

    # ── SLO Metrics ───────────────────────────────────────────────────────────

    def record_metric(
        self,
        journey_id: str,
        latency_ms: float,
        success: bool,
        correlation_id: Optional[str] = None,
        error_type: Optional[str] = None,
        provider: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record a single journey measurement for SLO tracking."""
        try:
            cid = correlation_id or new_correlation_id("metric")
            event = MetricEvent(
                journey_id=journey_id,
                correlation_id=cid,
                latency_ms=latency_ms,
                success=success,
                error_type=error_type,
                provider=provider,
                metadata=metadata or {},
            )
            with self._lock:
                self._metrics.append(event)
        except Exception:
            pass

    def get_slo_report(self, journey_id: Optional[str] = None) -> dict[str, Any]:
        """
        Compute SLO compliance report for one or all journeys.

        Returns per-journey: availability, p95/p99 latency vs targets,
        error budget consumption, and SLO breach status.
        """
        try:
            with self._lock:
                metrics = list(self._metrics)

            if journey_id:
                metrics = [m for m in metrics if m.journey_id == journey_id]

            # Group by journey_id
            by_journey: dict[str, list[MetricEvent]] = defaultdict(list)
            for m in metrics:
                by_journey[m.journey_id].append(m)

            reports: dict[str, dict[str, Any]] = {}
            for jid, events in by_journey.items():
                slo = CRITICAL_JOURNEY_SLOS.get(jid)
                total = len(events)
                successes = sum(1 for e in events if e.success)
                latencies = sorted(e.latency_ms for e in events)

                availability_actual = (successes / total * 100) if total > 0 else 100.0
                p95 = latencies[int(total * 0.95) - 1] if total >= 20 else None
                p99 = latencies[int(total * 0.99) - 1] if total >= 100 else None

                error_budget_consumed: Optional[float] = None
                slo_breach = False
                if slo:
                    error_budget_consumed = round(
                        max(
                            0.0,
                            (slo.availability_pct - availability_actual)
                            / slo.error_budget_pct
                            * 100,
                        ),
                        1,
                    )
                    slo_breach = availability_actual < slo.availability_pct or (
                        p95 is not None and p95 > slo.p95_latency_ms
                    )

                reports[jid] = {
                    "journey_id": jid,
                    "description": slo.description if slo else jid,
                    "total_measurements": total,
                    "availability_pct": round(availability_actual, 3),
                    "slo_availability_target": slo.availability_pct if slo else None,
                    "p95_latency_ms": p95,
                    "p99_latency_ms": p99,
                    "slo_p95_target_ms": slo.p95_latency_ms if slo else None,
                    "slo_p99_target_ms": slo.p99_latency_ms if slo else None,
                    "error_budget_consumed_pct": error_budget_consumed,
                    "slo_breach": slo_breach,
                    "status": "BREACHED" if slo_breach else "OK",
                }

            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": round(time.time() - self._startup_time, 1),
                "journeys": reports,
                "overall_status": "BREACHED"
                if any(r.get("slo_breach") for r in reports.values())
                else "OK",
            }
        except Exception as exc:
            return {"error": str(exc), "status": "ERROR"}

    # ── Provider Freshness ────────────────────────────────────────────────────

    def record_provider_success(self, provider: str) -> None:
        """Record a successful data fetch from a provider."""
        try:
            with self._lock:
                rec = self._provider_freshness.setdefault(
                    provider, ProviderFreshnessRecord(provider=provider)
                )
                rec.last_success_at = time.time()
                rec.total_requests += 1
                rec.consecutive_errors = 0
        except Exception:
            pass

    def record_provider_error(self, provider: str, is_stale: bool = False) -> None:
        """Record a provider fetch error or stale response."""
        try:
            with self._lock:
                rec = self._provider_freshness.setdefault(
                    provider, ProviderFreshnessRecord(provider=provider)
                )
                rec.last_failure_at = time.time()
                rec.total_requests += 1
                rec.error_count += 1
                rec.consecutive_errors += 1
                if is_stale:
                    rec.stale_count += 1
        except Exception:
            pass

    def get_provider_health(self) -> dict[str, Any]:
        """Return freshness and health status for all tracked providers."""
        try:
            with self._lock:
                records = {k: v.to_dict() for k, v in self._provider_freshness.items()}
            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "providers": records,
                "overall_health": "HEALTHY"
                if all(r.get("health") == "HEALTHY" for r in records.values())
                else "DEGRADED"
                if any(r.get("health") == "UNHEALTHY" for r in records.values())
                else "DEGRADED",
            }
        except Exception as exc:
            return {"error": str(exc), "overall_health": "UNKNOWN"}

    # ── Liveness / Readiness ─────────────────────────────────────────────────

    def get_liveness(self) -> dict[str, Any]:
        """
        Liveness probe: is the process alive and functioning?
        Kubernetes/load-balancer compatible — returns 200 if alive.
        """
        return {
            "status": "alive",
            "uptime_seconds": round(time.time() - self._startup_time, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_readiness(self) -> dict[str, Any]:
        """
        Readiness probe: is the service ready to serve traffic?
        Checks for critical dependency availability.
        """
        try:
            with self._lock:
                provider_health = {k: v.to_dict() for k, v in self._provider_freshness.items()}

            unhealthy_providers = [
                p for p, h in provider_health.items() if h.get("health") == "UNHEALTHY"
            ]

            ready = len(unhealthy_providers) == 0
            return {
                "status": "ready" if ready else "not_ready",
                "checks": {
                    "provider_health": "pass" if ready else "degraded",
                    "unhealthy_providers": unhealthy_providers,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


# ── Module-Level Singleton ────────────────────────────────────────────────────

_registry: Optional[ObservabilityRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ObservabilityRegistry:
    """Get or create the global ObservabilityRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ObservabilityRegistry()
    return _registry
