"""
tests/test_audit_traceability.py
─────────────────────────────────
Tests for institutional Single Source of Truth (SSOT), audit trail recording,
lifecycle event tracking, and observability endpoints in ChanakyaTrade.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def test_auto_alert_record_audit():
    """Verify AutoAlert.record_audit() appends structured chronological events and caps at 50."""
    alert = AutoAlert(
        alert_id="aa-audit-test-INFY-20260928",
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Gamma Blast",
        summary="Test alert",
        ltp=1850.0,
        trigger_level=1850.0,
        target_level=1920.0,
        stop_loss=1810.0,
        confidence=85,
    )

    # Initialized event should already be in audit_trail from __post_init__
    assert len(alert.audit_trail) >= 1
    assert alert.audit_trail[0]["event_type"] == "INITIALIZED"
    assert alert.audit_trail[0]["actor"] == "ALERT_FACTORY"

    # Add custom audit events
    alert.record_audit("SSE_BROADCAST", "Sent to UI via SSE", actor="DISPATCH_GATE")
    alert.record_audit("TELEGRAM_SENT", "Dispatched to Telegram", actor="TELEGRAM_GATE")

    assert len(alert.audit_trail) == 3
    assert alert.audit_trail[1]["event_type"] == "SSE_BROADCAST"
    assert alert.audit_trail[2]["event_type"] == "TELEGRAM_SENT"
    assert alert.audit_trail[2]["actor"] == "TELEGRAM_GATE"

    # Verify audit trail is capped at 50 to avoid unbounded memory / JSON growth
    for i in range(60):
        alert.record_audit("UPDATE", f"Update {i}")
    assert len(alert.audit_trail) == 50


def test_audit_trail_serialization_and_deserialization(tmp_path, monkeypatch):
    """Verify audit_trail survives _save() and _load() cycle cleanly."""
    data_file = tmp_path / "auto_alerts_audit.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    alert = AutoAlert(
        alert_id="aa-audit-persist-TCS-20260928",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Squeeze",
        summary="Audit persistence test",
        ltp=4200.0,
        trigger_level=4200.0,
        target_level=4400.0,
        stop_loss=4100.0,
        confidence=88,
    )
    alert.record_audit(
        "TELEGRAM_HELD",
        "Held from Telegram: Post-market session closed",
        actor="TELEGRAM_GATE",
        details={"reason": "session_closed"},
    )
    engine._alerts.append(alert)
    engine._save()

    # Load in a fresh engine instance
    new_engine = AutoAlertEngine(max_buffer=20)
    new_engine._load()

    loaded = new_engine.get_alert_by_id("aa-audit-persist-TCS-20260928")
    assert loaded is not None
    assert len(loaded.audit_trail) >= 2
    types = [e["event_type"] for e in loaded.audit_trail]
    assert "INITIALIZED" in types
    assert "TELEGRAM_HELD" in types


def test_get_audit_trail_filtering():
    """Verify query filtering on get_audit_trail (by symbol, event_type, alert_id)."""
    engine = AutoAlertEngine(max_buffer=20)
    engine.clear_alerts()

    a1 = AutoAlert(
        alert_id="aa-filt-RELIANCE-20260928",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Blast",
        summary="Test",
        ltp=2950.0,
        trigger_level=2950.0,
        target_level=3050.0,
        stop_loss=2900.0,
    )
    a1.record_audit("TELEGRAM_SENT", "Dispatched to Telegram", actor="TELEGRAM_GATE")

    a2 = AutoAlert(
        alert_id="aa-filt-INFY-20260928",
        alert_type="OPTIONS_MOMENTUM",
        stage="EARLY_WARNING",
        symbol="INFY",
        exchange="NSE",
        direction="BEARISH",
        headline="INFY PE",
        summary="Test",
        ltp=185.0,
        trigger_level=185.0,
        target_level=280.0,
        stop_loss=157.0,
    )
    a2.record_audit("TELEGRAM_HELD", "Held: Confidence < 82%", actor="TELEGRAM_GATE")

    engine._alerts.extend([a1, a2])

    # Filter by symbol
    rel_events = engine.get_audit_trail(symbol="RELIANCE")
    assert all(e["symbol"] == "RELIANCE" for e in rel_events)
    assert any(e["event_type"] == "TELEGRAM_SENT" for e in rel_events)

    # Filter by event_type
    held_events = engine.get_audit_trail(event_type="TELEGRAM_HELD")
    assert len(held_events) == 1
    assert held_events[0]["symbol"] == "INFY"
    assert "Confidence < 82%" in held_events[0]["message"]


def test_api_audit_endpoints():
    """Verify /api/alerts/auto/audit-trail and /api/alerts/auto/{alert_id}/audit endpoints."""
    from web.api import app
    from engine.auto_alert_engine import auto_alert_engine

    test_alert = AutoAlert(
        alert_id="aa-api-audit-HDFC-20260928",
        alert_type="CIRCUIT_WARNING",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NSE",
        direction="BULLISH",
        headline="HDFCBANK Alert",
        summary="API audit test",
        ltp=1650.0,
        trigger_level=1650.0,
        target_level=1720.0,
        stop_loss=1620.0,
    )
    test_alert.record_audit("SSE_BROADCAST", "Broadcast to UI", actor="DISPATCH_GATE")
    auto_alert_engine._alerts.append(test_alert)

    client = TestClient(app)

    # 1. Global audit trail
    res1 = client.get("/api/alerts/auto/audit-trail?symbol=HDFCBANK")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ok"
    assert data1["count"] >= 1
    assert any(e["event_type"] == "SSE_BROADCAST" for e in data1["data"])

    # 2. Alert-specific audit detail
    res2 = client.get("/api/alerts/auto/aa-api-audit-HDFC-20260928/audit")
    assert res2.status_code == 200
    data2 = res2.json()["data"]
    assert data2["alert_id"] == "aa-api-audit-HDFC-20260928"
    assert data2["trace_id"] is not None
    assert len(data2["audit_trail"]) >= 2

    # 3. Non-existent alert
    res3 = client.get("/api/alerts/auto/non-existent-alert-id/audit")
    assert res3.status_code == 404
