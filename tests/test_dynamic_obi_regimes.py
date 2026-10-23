"""
Test suite for Dynamic Regime-Aware OBI & Time-of-Day Adaptation in Scrutiny Gate 25.

Verifies:
1. Lunch Doldrums (11:30 - 13:30 IST): Tightens allowable negative OBI threshold from 0.45 to ~0.36,
   blocking fake lunch breakouts with mild supply overhead (-0.40).
2. Opening Impulse (09:15 - 09:45 IST): Expands allowable negative OBI threshold up to ~0.54,
   allowing valid institutional momentum breakouts with OBI = -0.50.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from engine.alert_scrutiny import AlertScrutinyAuditor
from config.constants import IST


def _create_candidate_alert(symbol="NSE:TATAMOTORS", direction="BULLISH", obi_50=-0.40):
    alert = SimpleNamespace(
        alert_id="aa-dyn-test-001",
        symbol=symbol,
        contract_symbol=symbol,
        direction=direction,
        alert_type="BREAKOUT",
        entry=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,
        target_level=1050.0,
        target1=1050.0,
        target2=1080.0,
        ltp=1001.0,
        stage="TRIGGERED",
        setup_type="MOMENTUM_EXPANSION",
        time_horizon="INTRADAY",
        environment="LIVE",
        is_live=True,
        option_type="CE",
        metrics={},
        extra_metrics={
            "l3_microstructure": {
                "obi_50": obi_50,
                "fleeing_bid_wall_detected": False,
                "fleeing_ask_wall_detected": False,
                "fortress_ask_wall_confirmed": False,
                "fortress_bid_wall_confirmed": False,
            }
        },
    )
    return alert


def test_gate25_lunch_doldrums_tightens_threshold(monkeypatch):
    """At 12:15 IST, allowable OBI threshold tightens to 0.36, vetoing OBI = -0.40."""
    auditor = AlertScrutinyAuditor()
    alert = _create_candidate_alert(obi_50=-0.40)

    # Mock datetime to lunch time (12:15 IST)
    mock_now = datetime(2026, 10, 19, 12, 15, 0, tzinfo=IST)
    monkeypatch.setattr("engine.alert_scrutiny.datetime", MagicMock(now=lambda tz=None: mock_now))

    passed, reason, flags = auditor.verify_tier1_sanity(alert)

    assert not passed
    assert "Order Book Imbalance Veto" in reason
    assert flags.get("l3_adaptive_threshold") == 0.36


def test_gate25_opening_impulse_relaxes_threshold(monkeypatch):
    """At 09:25 IST, allowable OBI threshold relaxes to 0.54, permitting breakout with OBI = -0.50."""
    auditor = AlertScrutinyAuditor()
    alert = _create_candidate_alert(obi_50=-0.50)

    # Mock datetime to opening impulse (09:25 IST)
    mock_now = datetime(2026, 10, 19, 9, 25, 0, tzinfo=IST)
    monkeypatch.setattr("engine.alert_scrutiny.datetime", MagicMock(now=lambda tz=None: mock_now))

    passed, reason, flags = auditor.verify_tier1_sanity(alert)

    # OBI -0.50 does NOT breach the relaxed threshold of -0.54
    assert flags.get("l3_adaptive_threshold") == 0.54
    assert flags.get("order_book_sanctity_valid", True)
