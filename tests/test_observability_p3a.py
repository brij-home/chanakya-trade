"""
tests/test_observability_p3a.py
────────────────────────────────
P3-A unit tests: Structured Observability, SLO Metrics, and Provider Health.
"""

import pytest
from engine.observability import (
    new_correlation_id,
    ObservabilityRegistry,
    CRITICAL_JOURNEY_SLOS,
)
from fastapi.testclient import TestClient
from web.api import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def obs():
    """Fresh registry for each test (not the singleton)."""
    return ObservabilityRegistry()


# ── Correlation ID Tests ─────────────────────────────────────────────────────


def test_correlation_id_format():
    """Verify generated correlation IDs have the correct structure."""
    cid = new_correlation_id("req")
    parts = cid.split("-")
    assert parts[0] == "req"
    assert len(parts) == 3
    assert len(parts[2]) == 8  # 8-char hex


def test_correlation_id_uniqueness():
    """Each generated correlation ID must be unique."""
    ids = {new_correlation_id("req") for _ in range(100)}
    assert len(ids) == 100  # All unique


def test_correlation_id_custom_prefix():
    """Custom prefix is respected."""
    cid = new_correlation_id("order")
    assert cid.startswith("order-")


def test_registry_stores_correlation_ids(obs):
    """Registry stores and retrieves recent correlation IDs."""
    cid1 = new_correlation_id("req")
    cid2 = new_correlation_id("order")
    obs.register_correlation_id(cid1)
    obs.register_correlation_id(cid2)

    recent = obs.recent_correlation_ids(limit=10)
    assert cid2 in recent
    assert cid1 in recent


# ── SLO Metric Tests ─────────────────────────────────────────────────────────


def test_slo_report_empty_registry(obs):
    """Empty registry returns OK status and empty journeys."""
    report = obs.get_slo_report()
    assert report["overall_status"] == "OK"
    assert report["journeys"] == {}


def test_slo_report_records_and_computes_availability(obs):
    """SLO availability is computed correctly from success/failure counts."""
    for i in range(90):
        obs.record_metric("quote_fetch", latency_ms=100.0, success=True)
    for i in range(10):
        obs.record_metric(
            "quote_fetch", latency_ms=100.0, success=False, error_type="PROVIDER_TIMEOUT"
        )

    report = obs.get_slo_report(journey_id="quote_fetch")
    journey = report["journeys"]["quote_fetch"]
    assert journey["total_measurements"] == 100
    assert abs(journey["availability_pct"] - 90.0) < 0.01


def test_slo_breach_when_below_target(obs):
    """SLO breach is flagged when availability falls below target."""
    target = CRITICAL_JOURNEY_SLOS["paper_order_submit"]
    assert target.availability_pct == 99.9
    # paper_order_submit needs 99.9% availability — inject enough failures
    for i in range(980):
        obs.record_metric("paper_order_submit", latency_ms=50.0, success=True)
    for i in range(20):
        obs.record_metric("paper_order_submit", latency_ms=50.0, success=False)

    report = obs.get_slo_report(journey_id="paper_order_submit")
    journey = report["journeys"]["paper_order_submit"]
    # 980/1000 = 98% < 99.9% target → breach
    assert journey["slo_breach"] is True
    assert journey["status"] == "BREACHED"


def test_slo_ok_when_above_target(obs):
    """No SLO breach when availability exceeds target."""
    for i in range(1000):
        obs.record_metric("quote_fetch", latency_ms=200.0, success=True)

    report = obs.get_slo_report(journey_id="quote_fetch")
    journey = report["journeys"]["quote_fetch"]
    assert journey["availability_pct"] == 100.0
    assert journey["slo_breach"] is False
    assert journey["status"] == "OK"


def test_critical_journey_slos_are_defined():
    """All expected critical journeys have SLO targets defined."""
    required = {
        "quote_fetch",
        "options_chain",
        "multi_agent_analyze",
        "paper_order_submit",
        "backtest_run",
    }
    assert required.issubset(set(CRITICAL_JOURNEY_SLOS.keys()))


# ── Provider Freshness Tests ─────────────────────────────────────────────────


def test_provider_health_empty_registry(obs):
    """Empty provider registry returns healthy status."""
    health = obs.get_provider_health()
    assert health["providers"] == {}
    assert health["overall_health"] == "HEALTHY"


def test_provider_success_marks_healthy(obs):
    """Recording a success marks the provider as healthy (non-stale within threshold)."""
    obs.record_provider_success("fyers")
    health = obs.get_provider_health()
    provider = health["providers"]["fyers"]
    assert provider["health"] == "HEALTHY"
    assert provider["is_stale"] is False
    assert provider["total_requests"] == 1
    assert provider["error_count"] == 0


def test_provider_error_increments_counts(obs):
    """Recording errors increments error_count and consecutive_errors."""
    obs.record_provider_success("yfinance")
    obs.record_provider_error("yfinance", is_stale=False)
    obs.record_provider_error("yfinance", is_stale=True)

    health = obs.get_provider_health()
    provider = health["providers"]["yfinance"]
    assert provider["total_requests"] == 3
    assert provider["error_count"] == 2
    assert provider["stale_count"] == 1
    assert provider["consecutive_errors"] == 2


def test_provider_success_resets_consecutive_errors(obs):
    """A success after errors resets consecutive_errors to 0."""
    obs.record_provider_error("fyers")
    obs.record_provider_error("fyers")
    obs.record_provider_success("fyers")

    health = obs.get_provider_health()
    assert health["providers"]["fyers"]["consecutive_errors"] == 0


def test_provider_unhealthy_after_many_errors(obs):
    """Provider with 3+ consecutive errors is classified as UNHEALTHY."""
    for _ in range(5):
        obs.record_provider_error("zerodha")

    health = obs.get_provider_health()
    assert health["providers"]["zerodha"]["health"] == "UNHEALTHY"


# ── Liveness / Readiness Tests ───────────────────────────────────────────────


def test_liveness_always_alive(obs):
    """Liveness probe returns 'alive' status."""
    result = obs.get_liveness()
    assert result["status"] == "alive"
    assert result["uptime_seconds"] >= 0.0
    assert "timestamp" in result


def test_readiness_with_no_providers(obs):
    """Readiness is 'ready' when no providers have been tracked."""
    result = obs.get_readiness()
    assert result["status"] == "ready"


def test_readiness_not_ready_with_unhealthy_provider(obs):
    """Readiness fails when any provider has 3+ consecutive errors (UNHEALTHY)."""
    for _ in range(5):
        obs.record_provider_error("fyers")

    result = obs.get_readiness()
    assert result["status"] == "not_ready"
    assert "fyers" in result["checks"]["unhealthy_providers"]


# ── API Contract Tests ────────────────────────────────────────────────────────


def test_health_endpoint_returns_alive(client):
    """GET /health returns alive status."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "alive"
    assert "uptime_seconds" in data


def test_health_live_endpoint(client):
    """GET /health/live returns 200 with alive status."""
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json()["status"] == "alive"


def test_health_ready_endpoint(client):
    """GET /health/ready returns 200 or 503 with status field."""
    res = client.get("/health/ready")
    assert res.status_code in (200, 503)
    data = res.json()
    assert "status" in data


def test_slo_endpoint_returns_report(client):
    """GET /api/slo returns SLO report with overall_status."""
    res = client.get("/api/slo")
    assert res.status_code == 200
    data = res.json()
    assert "overall_status" in data
    assert "journeys" in data


def test_provider_health_endpoint(client):
    """GET /api/provider_health returns provider health report."""
    res = client.get("/api/provider_health")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "overall_health" in data


def test_correlation_ids_endpoint(client):
    """GET /api/correlation_ids returns list of recent correlation IDs."""
    res = client.get("/api/correlation_ids")
    assert res.status_code == 200
    data = res.json()
    assert "correlation_ids" in data
    assert isinstance(data["correlation_ids"], list)


def test_correlation_id_in_response_headers(client):
    """Every API response must include X-Correlation-ID header (P3-A middleware)."""
    res = client.get("/api/mode")
    assert "x-correlation-id" in res.headers
    cid = res.headers["x-correlation-id"]
    assert len(cid) > 10  # Non-trivial ID
