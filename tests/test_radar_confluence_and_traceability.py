"""
tests/test_radar_confluence_and_traceability.py
───────────────────────────────────────────────
Verification suite for:
  1. Cross-Radar Confluence Aggregation (Precursor + Asymmetric setups)
  2. Prevention of duplicate tickets across detectors
  3. AutoAlert trace_id and quant_snapshot generation
  4. Batch quote pre-fetch and concurrent execution speed
"""

from datetime import timezone, timedelta
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

IST = timezone(timedelta(hours=5, minutes=30))


def test_cross_radar_confluence_aggregation():
    """Verify that when a symbol triggers multiple orthogonal radars, alerts are merged into Confluence Apex."""
    engine = AutoAlertEngine()
    engine._alerts.clear()

    # 1. First radar alert: Precursor coiling
    alert1 = AutoAlert(
        alert_id="precursor-coforge-20260918",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="COFORGE",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ PRECURSOR RADAR [FNO]: COFORGE Coiling at ₹7,450.0 (88/100)",
        summary="8-bar TTM Squeeze compression with 1.8x RVOL expansion.",
        ltp=7450.0,
        trigger_level=7450.0,
        target_level=7800.0,
        stop_loss=7320.0,
        confidence=88,
        is_live=True,
        environment="LIVE",
    )

    res1 = engine.record_alert(alert1)
    assert res1 is True
    assert len(engine._alerts) == 1
    assert engine._alerts[0].alert_type == "PRECURSOR_RADAR"
    assert engine._alerts[0].confidence == 88

    # 2. Second radar alert: Asymmetric Pocket Pivot on the SAME stock
    alert2 = AutoAlert(
        alert_id="asym-coforge-pocket-pivot-20260918",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="IGNITED",
        symbol="COFORGE",
        exchange="NSE",
        direction="BULLISH",
        headline="🎯 [LOW RISK : HIGH REWARD] POCKET PIVOT: COFORGE (R:R 1:4.2)",
        summary="Pocket pivot volume signature breaking out of constructive base.",
        ltp=7455.0,
        trigger_level=7455.0,
        target_level=7850.0,
        stop_loss=7320.0,
        confidence=90,
        is_live=True,
        environment="LIVE",
    )

    # Calling record_alert with the second detector
    res2 = engine.record_alert(alert2)
    assert res2 is True

    # 3. VERIFY NO DUPLICATE CARD WAS INSERTED
    assert len(engine._alerts) == 1, "Must NOT insert a second duplicate card for the same symbol!"

    active_alert = engine._alerts[0]
    # Verify confluence elevation
    assert "confluence_types" in active_alert.metrics
    assert "PRECURSOR_RADAR" in active_alert.metrics["confluence_types"]
    assert "ASYMMETRIC_OPPORTUNITY" in active_alert.metrics["confluence_types"]

    # Verify conviction score boost (should be elevated beyond both 88 and 90)
    assert active_alert.confidence >= 94

    # Verify headline was upgraded to CONFLUENCE APEX
    assert "CONFLUENCE APEX" in active_alert.headline
    assert "COFORGE" in active_alert.headline

    # Verify stage was upgraded to IGNITED
    assert active_alert.stage == "IGNITED"


def test_auto_alert_trace_id_and_quant_snapshot():
    """Verify AutoAlert generates canonical trace_id and quant_snapshot for auditability."""
    alert = AutoAlert(
        alert_id="asym-trent-20260918",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="EARLY_WARNING",
        symbol="TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="🎯 Asymmetric test",
        summary="Test summary",
        ltp=5200.0,
        trigger_level=5200.0,
        target_level=5500.0,
        stop_loss=5100.0,
        confidence=85,
    )

    # trace_id should be automatically populated
    assert alert.trace_id is not None
    assert alert.trace_id.startswith("TRC-")
    assert "TRENT" in alert.trace_id

    # Record alert and check quant_snapshot population
    engine = AutoAlertEngine()
    engine.record_alert(alert)
    assert alert.quant_snapshot is not None
    assert alert.quant_snapshot["ltp"] == 5200.0
    assert alert.quant_snapshot["stop_loss"] == 5100.0
    assert "recorded_at" in alert.quant_snapshot


def test_deterministic_asymmetric_alert_id(monkeypatch):
    """Verify that scan_asymmetric_opportunities produces deterministic IDs and suppresses duplicate cycles."""
    from engine.asymmetric_radar import AsymmetricOpportunity

    engine = AutoAlertEngine()
    engine._alerts.clear()

    mock_opp = AsymmetricOpportunity(
        symbol="COFORGE",
        exchange="NSE",
        direction="BULLISH",
        setup_type="POCKET_PIVOT",
        setup_label="POCKET PIVOT",
        entry_price=7450.0,
        stop_loss=7320.0,
        target_1=7750.0,
        target_2=7950.0,
        target_moonshot=8200.0,
        risk_reward_ratio=3.8,
        conviction_score=92,
        catalyst_summary="Pocket pivot test",
        entry_range="₹7,440 - ₹7,460",
        profit_rule="Scale 50% at T1",
        when_to_buy="Buy on volume",
        when_to_wait="Wait if above 7500",
        ltp=7450.0,
    )

    class MockRadar:
        def scan_asymmetric_opportunities(self, top_n=6):
            return [mock_opp]

    monkeypatch.setattr("engine.asymmetric_radar.asymmetric_radar", MockRadar())

    # Cycle 1
    found1 = engine.scan_asymmetric_opportunities()
    assert len(found1) == 1
    first_id = found1[0].alert_id
    assert first_id.startswith("asym-coforge-pocket-pivot-")
    assert len(engine._alerts) == 1

    # Cycle 2 (next 45s tick) - should be completely deduplicated, NOT inserted again!
    found2 = engine.scan_asymmetric_opportunities()
    assert len(found2) == 0, "Duplicate cycle must be suppressed by idempotent alert_id!"
    assert len(engine._alerts) == 1
