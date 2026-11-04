"""
tests/test_winglock_sourced_evidence.py
───────────────────────────────────────
Regression tests for EXEC-14 and TASK P1-H:
  - Free-roll wing lock must reject when no authentic limit price or credit source exists (no ₹10 fallback).
  - Free-roll wing lock only sets free_roll_locked=True when the hedge order is FILLED.
"""

import pytest
from engine.auto_alert_engine import AutoAlert, get_auto_alert_engine
from engine.order_lifecycle import execute_wing_lock_hedge


def test_wing_lock_rejects_without_price_source(monkeypatch):
    """execute_wing_lock_hedge must raise ValueError if limit_price and estimated credit are missing/zero."""
    engine = get_auto_alert_engine()

    alert = AutoAlert(
        alert_id="aa-test-no-price-source",
        alert_type="GAMMA_BLAST",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Test Headline",
        summary="Test Summary",
        ltp=150.0,
        trigger_level=100.0,
        target_level=200.0,
        stop_loss=80.0,
        actionable_plan={
            "hedge_ticket": {
                "action": "SELL",
                "symbol": "NIFTY24750CE",
                # missing limit_price!
                "shares": 25,
            },
            # missing free_roll_plan!
        },
        metrics={},
    )
    with engine._lock:
        engine._alerts.insert(0, alert)

    with pytest.raises(ValueError, match="requires an authentic limit price"):
        execute_wing_lock_hedge(alert_id="aa-test-no-price-source")


def test_wing_lock_open_order_does_not_claim_locked(monkeypatch):
    """When the hedge order remains OPEN (unfilled), free_roll_locked must be False."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("DEPLOY_MODE", "test")

    # Mock market quote to be 20.0, but order is SELL LIMIT @ 50.0 -> PaperBroker leaves OPEN
    monkeypatch.setattr("market.quotes.get_ltp", lambda sym: 20.0)
    monkeypatch.setattr(
        "market.instrument_master.get_verified_contract",
        lambda sym: {
            "lookup_symbol": sym,
            "provider": "fyers",
            "provider_symbol": f"NSE:{sym}",
            "provider_token": "12345",
            "exchange": "NFO",
            "segment": "OPTIONS",
            "lot_size": 25,
            "tick_size": 0.05,
        },
    )

    engine = get_auto_alert_engine()
    alert = AutoAlert(
        alert_id="aa-test-unfilled-wing",
        alert_type="GAMMA_BLAST",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Test Unfilled Wing",
        summary="Test Summary",
        ltp=150.0,
        trigger_level=100.0,
        target_level=200.0,
        stop_loss=80.0,
        actionable_plan={
            "hedge_ticket": {
                "action": "SELL",
                "symbol": "NIFTY24800CE",
                "limit_price": 50.0,
                "shares": 25,
            },
        },
        metrics={},
    )
    with engine._lock:
        engine._alerts.insert(0, alert)

    _res = execute_wing_lock_hedge(alert_id="aa-test-unfilled-wing")
    updated = engine.get_alert_by_id("aa-test-unfilled-wing")

    assert updated.metrics.get("free_roll_locked") is False
    assert updated.actionable_plan.get("free_roll_active") is False
    assert updated.actionable_plan.get("free_roll_pending_order_id") is not None
