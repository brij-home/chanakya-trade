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
import logging

logger = logging.getLogger("engine.observability")


import contextvars
import logging
import time
import threading
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


# ── Correlation Context (contextvars) ────────────────────────────────────────

_CORRELATION_ID_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)
_CORRELATION_SYMBOL_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_symbol", default=None
)


def set_correlation_context(
    correlation_id: Optional[str] = None, symbol: Optional[str] = None
) -> None:
    """Set the correlation context for the current async task / thread."""
    if correlation_id is not None:
        _CORRELATION_ID_VAR.set(correlation_id)
    if symbol is not None:
        _CORRELATION_SYMBOL_VAR.set(symbol)


def get_current_correlation_id() -> Optional[str]:
    """Retrieve current correlation ID from contextvars."""
    return _CORRELATION_ID_VAR.get()


def get_current_correlation_symbol() -> Optional[str]:
    """Retrieve current symbol from contextvars."""
    return _CORRELATION_SYMBOL_VAR.get()


def clear_correlation_context() -> None:
    """Clear the correlation context."""
    _CORRELATION_ID_VAR.set(None)
    _CORRELATION_SYMBOL_VAR.set(None)


class InstitutionalCorrelationFilter(logging.Filter):
    """
    Standard Python logging.Filter that enriches LogRecord with correlation attributes.
    Enables log formatters to output %(correlation_id)s and %(symbol)s automatically.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        cid = getattr(record, "correlation_id", None)
        if not cid or cid == "-":
            cid = get_current_correlation_id()
        sym = getattr(record, "symbol", None)
        if not sym or sym == "-":
            sym = get_current_correlation_symbol()
        record.correlation_id = cid or "-"
        record.symbol = sym or "-"
        return True


def install_institutional_correlation_filter(logger_name: Optional[str] = None) -> None:
    """
    Attach InstitutionalCorrelationFilter to the specified logger (or root if None).
    Guarantees idempotency so the filter is never attached more than once.
    """
    target = logging.getLogger(logger_name)
    for f in target.filters:
        if isinstance(f, InstitutionalCorrelationFilter):
            return
    target.addFilter(InstitutionalCorrelationFilter())


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
        """
        Check if the provider is returning or experiencing stale data.

        Institutional provenance semantics:
        1. If no success has occurred, it is only stale if requests were attempted and failed.
        2. If last_success_at is within STALE_THRESHOLD_SECONDS, it is fresh (not stale).
        3. If last_success_at exceeds STALE_THRESHOLD_SECONDS:
           - If Indian markets are closed (weekends, off-market hours), quotes do not update
             continuously, so elapsed time does not indicate staleness.
           - If the provider is an auxiliary/fallback source (e.g. yfinance, secondary broker)
             rather than the active primary data broker, elapsed time does not indicate staleness
             unless it actively experienced consecutive errors or explicit stale responses.
           - If the provider is the active primary data broker during open market hours and no
             quote has arrived in >120s, it is genuinely stale.
        """
        if self.last_success_at is None:
            return self.total_requests > 0 and self.error_count == self.total_requests

        age = self.age_seconds
        if age is None or age <= STALE_THRESHOLD_SECONDS:
            return False

        # If age > STALE_THRESHOLD_SECONDS, verify market hours and active primary role
        try:
            from market.calendar import is_market_open

            if not is_market_open("NSE"):
                return False
        except Exception as e_suppressed:
            logger.debug(f"[engine.observability] Non-fatal exception suppressed: {e_suppressed}")

        try:
            from brokers.session import get_data_broker_key

            primary = (get_data_broker_key() or "").lower()
            prov_lower = self.provider.lower()
            if primary and prov_lower != primary and prov_lower != "primary":
                return self.consecutive_errors > 0 and self.stale_count > 0
        except Exception as e_suppressed:
            logger.debug(f"[engine.observability] Non-fatal exception suppressed: {e_suppressed}")

        return True

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
        except Exception as e_suppressed:
            logger.debug(f"[engine.observability] Non-fatal exception suppressed: {e_suppressed}")

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
        except Exception as e_suppressed:
            logger.debug(f"[engine.observability] Non-fatal exception suppressed: {e_suppressed}")

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
        except Exception as e_suppressed:
            logger.debug(f"[engine.observability] Non-fatal exception suppressed: {e_suppressed}")

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
        except Exception as e_suppressed:
            logger.debug(f"[engine.observability] Non-fatal exception suppressed: {e_suppressed}")

    def get_provider_health(self) -> dict[str, Any]:
        """Return freshness and health status for all tracked providers."""
        try:
            with self._lock:
                records = {k: v.to_dict() for k, v in self._provider_freshness.items()}

            if not records:
                overall_health = "HEALTHY"
            else:
                try:
                    from brokers.session import get_data_broker_key

                    primary_key = (get_data_broker_key() or "").lower()
                except Exception:
                    primary_key = ""

                primary_rec = None
                if primary_key and primary_key in records:
                    primary_rec = records[primary_key]
                elif "fyers" in records:
                    primary_rec = records["fyers"]

                if primary_rec and primary_rec.get("health") == "UNHEALTHY":
                    overall_health = "UNHEALTHY"
                elif all(r.get("health") == "UNHEALTHY" for r in records.values()):
                    overall_health = "UNHEALTHY"
                elif (primary_rec and primary_rec.get("health") == "DEGRADED") or any(
                    r.get("health") in ("DEGRADED", "UNHEALTHY") for r in records.values()
                ):
                    overall_health = "DEGRADED"
                else:
                    overall_health = "HEALTHY"

            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "providers": records,
                "overall_health": overall_health,
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
