"""
tests/test_health_hub_opsdeck.py
─────────────────────────────────
Unit tests for OpsDeck & Health Hub backend endpoints and priority classification.
"""

from engine.telemetry import (
    record_event,
    derive_priority,
    get_incident_counts,
    get_prioritized_incidents,
    clear_telemetry,
    EVENT_EXCEPTION,
    EVENT_LLM_COOLDOWN,
    EVENT_API_RETRY,
)
from market.fyers_circuit_breaker import FyersCircuitBreaker, CircuitState


def test_derive_priority_hierarchy():
    """Verify priority assignment rules from P0 (Critical) to P3 (Info)."""
    # P0: Critical or live execution failures
    assert (
        derive_priority("EVENT_BROKER_FAILOVER", "EXECUTION_ENGINE", "ERROR", "Broker freeze")
        == "P0"
    )
    assert (
        derive_priority(EVENT_EXCEPTION, "ORDER_LIFECYCLE", "ERROR", "Failed to place order")
        == "P0"
    )
    assert (
        derive_priority("EVENT_CIRCUIT_TRIP", "FYERS_API", "WARNING", "CIRCUIT BREAKER LOCKOUT")
        == "P0"
    )

    # P1: High - Rate limits, cooldowns, fallbacks
    assert (
        derive_priority(
            EVENT_LLM_COOLDOWN, "LLM_GATEWAY", "WARNING", "Gemini 429 rate limit exceeded"
        )
        == "P1"
    )
    assert (
        derive_priority("DATA_FALLBACK", "MARKET_QUOTES", "WARNING", "Fallback to historical cache")
        == "P1"
    )
    assert (
        derive_priority(EVENT_EXCEPTION, "SCANNER", "ERROR", "HTTP 429 too many requests") == "P1"
    )

    # P2: Medium - Retries, minor warnings, latency
    assert derive_priority(EVENT_API_RETRY, "FYERS_REST", "INFO", "API retry attempt 2") == "P2"
    assert (
        derive_priority(
            "PERFORMANCE", "MARKET_FEED", "WARNING", "Quote latency exceeded p95 SLO target"
        )
        == "P2"
    )

    # P3: Info - Normal telemetry
    assert (
        derive_priority("CACHE_CHECKPOINT", "STORAGE", "INFO", "Routine WAL checkpoint completed")
        == "P3"
    )


def test_incident_aggregation_and_filtering():
    """Verify in-memory recording, priority classification, and filtering."""
    clear_telemetry()

    record_event(
        event_type="ORDER_FAIL",
        component="ORDER_LIFECYCLE",
        action_taken="Fail-closed freeze",
        reason="Broker rejected live order intent",
        severity="CRITICAL",
    )
    record_event(
        event_type=EVENT_LLM_COOLDOWN,
        component="AI_GATEWAY",
        action_taken="Switched to Quant SEPA model",
        reason="Gemini 1.5 429 quota exhaustion",
        severity="WARNING",
    )
    record_event(
        event_type=EVENT_API_RETRY,
        component="DATA_FEED",
        action_taken="Retrying connection",
        reason="Temporary connection reset",
        severity="WARNING",
    )

    counts = get_incident_counts()
    assert counts["P0"] >= 1
    assert counts["P1"] >= 1
    assert counts["P2"] >= 1

    p0_list = get_prioritized_incidents(priority="P0")
    assert len(p0_list) >= 1
    assert p0_list[0]["priority"] == "P0"

    clear_telemetry()


def test_circuit_breaker_manual_controls():
    """Verify manual reset and probe controls for OpsDeck."""
    cb = FyersCircuitBreaker(failure_threshold=2, cooldown_sec=60.0)
    cb.record_failure(status_code=429, error_message="Rate limit 429")
    assert cb.is_tripped() is True
    assert cb.state == CircuitState.OPEN

    # Test manual probe
    cb.probe()
    assert cb.state == CircuitState.HALF_OPEN

    # Test manual reset
    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.is_tripped() is False


def test_memory_and_storage_host_vitals():
    """Verify host vitals metrics contract for OpsDeck."""
    from engine.maintenance import get_storage_breakdown
    from engine.memory_guard import get_memory_status

    mem = get_memory_status().to_dict()
    assert "used_ram_pct" in mem
    assert "system_ram_pct" in mem
    assert "process_rss_mb" in mem
    assert mem["system_ram_pct"] == mem["used_ram_pct"]

    storage = get_storage_breakdown().to_dict()
    assert "free_ssd_gb" in storage
    assert "ssd_free_gb" in storage
    assert "total_size_mb" in storage
    assert "wal_mb" in storage
    assert "tiers" in storage
    assert "business" in storage["tiers"]
    assert "wal_mb" in storage["tiers"]["business"]


def test_fundamental_snapshot_and_scheduler_sync():
    """Verify get_fundamental_snapshot export and batch synchronization."""
    from analysis.fundamental import get_fundamental_snapshot
    from engine.data_sync_scheduler import data_sync_scheduler

    snap = get_fundamental_snapshot("INFY", fast=True)
    if snap:
        assert isinstance(snap, dict)
        assert "symbol" in snap

    res = data_sync_scheduler.sync_weekly_fundamentals(limit=1)
    assert res["status"] == "SUCCESS"
    assert "fundamentals_saved" in res
    assert "forensics_saved" in res


def test_telemetry_handler_external_scraper_downgrade():
    """Verify external library logs (yfinance, websocket) are not elevated to P1 critical incidents."""
    import logging
    from engine.telemetry import TelemetryLogHandler, get_prioritized_incidents, clear_telemetry

    clear_telemetry()
    handler = TelemetryLogHandler()

    # 1. Benign yfinance scraper message should be P2, not P1
    rec_yf = logging.LogRecord(
        name="yfinance.scrapers",
        level=logging.ERROR,
        pathname="yfinance/history.py",
        lineno=372,
        msg="$NIFTY_FIN_SERVICE.NS: possibly delisted; no price data found",
        args=(),
        exc_info=None,
    )
    handler.emit(rec_yf)

    # 2. Routine websocket client closure should be P2, not P1
    rec_ws = logging.LogRecord(
        name="websocket",
        level=logging.ERROR,
        pathname="websocket/client.py",
        lineno=100,
        msg="Connection to remote host was lost. - goodbye",
        args=(),
        exc_info=None,
    )
    handler.emit(rec_ws)

    # Verify neither was recorded as P1
    p1_incs = get_prioritized_incidents(priority="P1")
    assert len(p1_incs) == 0

    # Verify both are accessible as operational diagnostics (P2)
    p2_incs = get_prioritized_incidents(priority="P2")
    assert len(p2_incs) == 2

    clear_telemetry()


def test_observability_off_market_slo_protection():
    """Verify off-market queries do not flag false live SLO breaches."""
    from engine.observability import ObservabilityRegistry

    obs = ObservabilityRegistry()
    obs.clear_metrics()

    # Record 50 off-market unfulfilled option chain measurements
    for _ in range(50):
        obs.record_metric(
            journey_id="options_chain",
            latency_ms=12000.0,
            success=False,
            metadata={"symbol": "NIFTY", "off_market": True},
        )

    report = obs.get_slo_report(journey_id="options_chain")
    journey = report["journeys"]["options_chain"]
    assert journey["slo_breach"] is False
    assert journey["status"] == "OK"
    assert report["overall_status"] == "OK"

    obs.clear_metrics()
