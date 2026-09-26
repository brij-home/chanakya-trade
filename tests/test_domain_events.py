"""
tests/test_domain_events.py
───────────────────────────
Unit tests for strongly-typed SSE Domain Event Contract.
Verifies contract stability, schema serialization, and event bus dispatch.
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from engine.alert_model import AutoAlert
from web.domain_events import AlertDomainEvent, create_alert_domain_event
from web.sse import event_bus


def test_alert_domain_event_creation():
    """Verify creating domain event directly preserves all institutional fields."""
    event = AlertDomainEvent(
        event_type="ALERT_CREATED",
        alert_id="aa-gamma-blast-nifty-20260926",
        symbol="NIFTY",
        exchange="NSE",
        stage="EARLY_WARNING",
        headline="NIFTY Early Warning Gamma Blast",
        summary="Call unwinding observed at 24200 strike.",
        ltp=24210.0,
        trigger_level=24220.0,
        target_level=24350.0,
        stop_loss=24150.0,
    )

    assert event.event_type == "ALERT_CREATED"
    assert event.alert_id == "aa-gamma-blast-nifty-20260926"
    assert event.correlation_id.startswith("evt-")
    assert "IST" in event.timestamp_iso

    sse_dict = event.to_sse_dict()
    assert sse_dict["type"] == "alert_created"
    assert sse_dict["event_type"] == "ALERT_CREATED"
    assert sse_dict["alert"]["symbol"] == "NIFTY"
    assert sse_dict["alert"]["ltp"] == 24210.0


def test_create_alert_domain_event_from_auto_alert():
    """Verify factory accurately extracts AutoAlert fields into strongly-typed event."""
    alert = AutoAlert(
        alert_id="aa-squeeze-breakout-reliance-20260926",
        symbol="RELIANCE",
        exchange="NSE",
        segment="EQUITY",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        direction="BULLISH",
        headline="RELIANCE Squeeze Expansion",
        summary="Bollinger band squeeze breakout above 3020.",
        ltp=3025.0,
        trigger_level=3020.0,
        target_level=3080.0,
        stop_loss=2990.0,
        confidence=88.0,
    )

    event = create_alert_domain_event(alert, event_type="ALERT_IGNITED")
    assert event.event_type == "ALERT_IGNITED"
    assert event.symbol == "RELIANCE"
    assert event.stage == "IGNITED"
    assert event.ltp == 3025.0
    assert event.stop_loss == 2990.0


def test_publish_domain_event_on_sse_bus(monkeypatch):
    """Verify publish_domain_event dispatches correctly to SSE bus without exceptions."""
    mock_publish = MagicMock()
    monkeypatch.setattr(event_bus, "publish_sync", mock_publish)

    event = AlertDomainEvent(
        event_type="TRAILING_STOP_UPDATE",
        alert_id="aa-orb-infy-20260926",
        symbol="INFY",
        exchange="NSE",
        stage="IGNITED",
        headline="INFY Trailing SL Adjusted",
        summary="Trailing stop tightened to breakeven.",
        ltp=1850.0,
        trigger_level=1820.0,
        target_level=1890.0,
        stop_loss=1820.0,
    )

    event_bus.publish_domain_event(event)
    mock_publish.assert_called_once()
    channel, data = mock_publish.call_args[0]
    assert channel == "alert"
    assert data["type"] == "trailing_stop_update"
    assert data["alert"]["symbol"] == "INFY"
