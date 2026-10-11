"""
tests/test_domain_events.py
───────────────────────────
Unit tests for strongly-typed SSE Domain Event Contract.
Verifies contract stability, schema serialization, and event bus dispatch.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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


def test_create_regime_shift_event():
    """Verify factory accurately produces REGIME_SHIFT domain event with VIX metrics."""
    from web.domain_events import create_regime_shift_event

    evt = create_regime_shift_event(
        from_regime="NORMAL",
        to_regime="ELEVATED_VOLATILITY",
        vix_level=23.4,
        reason="VIX spike above 22.0",
    )
    assert evt.event_type == "REGIME_SHIFT"
    assert evt.symbol == "INDIA_VIX"
    assert evt.ltp == 23.4
    assert evt.metrics["from_regime"] == "NORMAL"
    assert evt.metrics["to_regime"] == "ELEVATED_VOLATILITY"
    assert "REGIME_SHIFT" in evt.headline or "Regime Shift" in evt.headline
    sse_dict = evt.to_sse_dict()
    assert sse_dict["type"] == "regime_shift"


def test_regime_shift_emission_from_signal_ensemble(monkeypatch):
    """Verify get_regime_weights broadcasts REGIME_SHIFT event when VIX changes regime."""
    import engine.signal_ensemble
    from engine.signal_ensemble import get_regime_weights

    mock_publish = MagicMock()
    monkeypatch.setattr(event_bus, "publish_domain_event", mock_publish)

    # Initial state
    engine.signal_ensemble._last_vix_regime = "NORMAL"

    # Shift to ELEVATED_VOLATILITY (VIX = 24.0)
    weights = get_regime_weights(24.0)
    assert weights["volatility"] == 0.25
    mock_publish.assert_called_once()
    evt = mock_publish.call_args[0][0]
    assert evt.event_type == "REGIME_SHIFT"
    assert evt.metrics["from_regime"] == "NORMAL"
    assert evt.metrics["to_regime"] == "ELEVATED_VOLATILITY"


def test_regime_shift_emission_from_commodity_regime(monkeypatch):
    """Verify evaluate_commodity_eagle_regime broadcasts REGIME_SHIFT event when MCX commodity regime shifts."""
    import engine.commodity_adaptive_regime
    from engine.commodity_adaptive_regime import evaluate_commodity_eagle_regime

    mock_publish = MagicMock()
    monkeypatch.setattr(event_bus, "publish_domain_event", mock_publish)

    # Initial state
    with engine.commodity_adaptive_regime._commodity_regime_lock:
        engine.commodity_adaptive_regime._last_commodity_regime["CRUDEOIL"] = "BALANCED_RANGE"

    # Evaluate with trap detected -> shifts to COUNTER_TREND_EXHAUSTION
    reg = evaluate_commodity_eagle_regime(
        symbol="CRUDEOIL",
        spot=6200.0,
        trap_detected=True,
        trap_reason="Delta absorption divergence",
    )
    assert reg.overall_environment == "COUNTER_TREND_EXHAUSTION"
    mock_publish.assert_called_once()
    evt = mock_publish.call_args[0][0]
    assert evt.event_type == "REGIME_SHIFT"
    assert evt.metrics["from_regime"] == "BALANCED_RANGE"
    assert evt.metrics["to_regime"] == "COUNTER_TREND_EXHAUSTION"
