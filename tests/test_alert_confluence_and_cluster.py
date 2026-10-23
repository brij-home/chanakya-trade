"""
tests/test_alert_confluence_and_cluster.py
──────────────────────────────────────────
Verification suite for:
  1. Multi-Detector Apex Confluence Synthesis on Index alerts.
  2. Sector Cluster Correlation Governor for single-stock alerts.
"""

from datetime import datetime
from config.constants import IST
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def test_apex_confluence_synthesis_on_index(monkeypatch):
    """
    Verifies that when an active index alert (e.g. INDEX_CALL_SETUP) is running,
    a secondary detector firing on the same index in the same direction
    (e.g. GAMMA_BLAST) upgrades the active alert to APEX_CONFLUENCE rather
    than creating a duplicate alert or being silently lost.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    engine = AutoAlertEngine()
    engine.clear_alerts()

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. First alert: SMC Index Call Setup on NIFTY
    alert1 = AutoAlert(
        alert_id="aa-index-call-nifty-20261018",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 25000 CE — SMC Demand Sweep Reclaim",
        summary="Reclaimed VWAP with double bottom confirmation",
        ltp=150.0,
        trigger_level=148.0,
        target_level=190.0,
        stop_loss=130.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        confidence=80,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
        metrics={"underlying": "NIFTY", "signals": ["SMC_VWAP_RECLAIM"]},
    )

    recorded1 = engine.record_alert(alert1)
    assert recorded1 is True
    assert len(engine._alerts) == 1
    assert engine._alerts[0].confidence >= 80
    assert not engine._alerts[0].metrics.get("is_apex_confluence")

    # 2. Second alert: Gamma Blast on NIFTY in the same direction
    alert2 = AutoAlert(
        alert_id="aa-gamma-blast-nifty-ce-25000-20261018",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="NIFTY 25000 CE — Gamma Blast OI Unwinding",
        summary="Negative dOI on 25000 PE + turnover surge",
        ltp=152.0,
        trigger_level=148.0,
        target_level=200.0,
        stop_loss=130.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        confidence=85,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
        metrics={"underlying": "NIFTY", "signals": ["GAMMA_OI_UNWIND"]},
    )

    recorded2 = engine.record_alert(alert2)
    # Secondary alert returns False (deduplicated into active setup)
    assert recorded2 is False
    # No second alert card spawned in the buffer
    assert len(engine._alerts) == 1

    # Active setup is upgraded to APEX CONFLUENCE!
    active = engine._alerts[0]
    assert active.metrics.get("is_apex_confluence") is True
    assert active.metrics.get("conviction_tier") == "APEX_CONFLUENCE"
    assert "GAMMA_BLAST" in active.metrics.get("confluence_detectors", [])
    assert "INDEX_CALL_SETUP" in active.metrics.get("confluence_detectors", [])
    # Confidence is boosted (+10% on top of highest confidence >= 85 -> >= 95)
    assert active.confidence >= 95
    # Both signals merged
    assert "SMC_VWAP_RECLAIM" in active.metrics.get("signals", [])
    assert "GAMMA_OI_UNWIND" in active.metrics.get("signals", [])


def test_sector_cluster_governor_suppresses_correlated_followers(monkeypatch):
    """
    Verifies that when an active alert exists in a sector (e.g. INFY in 'it'),
    a weaker simultaneous breakout in the same sector (e.g. WIPRO in 'it')
    is held/suppressed to prevent correlated portfolio cluster risk.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    engine = AutoAlertEngine()
    engine.clear_alerts()

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Leader: INFY with high RVOL 2.5x and 88% confidence
    infy_alert = AutoAlert(
        alert_id="aa-squeeze-infy-20261018",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY — TTM Squeeze Breakout",
        summary="Volume expansion above VCP pivot",
        ltp=1850.0,
        trigger_level=1845.0,
        target_level=1920.0,
        stop_loss=1815.0,
        confidence=88,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
        time_horizon="SWING_MID",
        metrics={"tod_rvol": 2.5},
    )

    recorded_infy = engine.record_alert(infy_alert)
    assert recorded_infy is True
    assert len(engine._alerts) == 1

    # 2. Correlated follower: WIPRO with lower RVOL 1.4x and 78% confidence
    wipro_alert = AutoAlert(
        alert_id="aa-squeeze-wipro-20261018",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="WIPRO",
        exchange="NSE",
        direction="BULLISH",
        headline="WIPRO — Squeeze Breakout",
        summary="Testing resistance",
        ltp=520.0,
        trigger_level=518.0,
        target_level=545.0,
        stop_loss=505.0,
        confidence=78,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
        time_horizon="SWING_MID",
        metrics={"tod_rvol": 1.4},
    )

    recorded_wipro = engine.record_alert(wipro_alert)
    # WIPRO should be held/suppressed by Sector Cluster Governor
    assert recorded_wipro is False
    assert len(engine._alerts) == 1
    assert engine._alerts[0].symbol == "INFY"


def test_sector_cluster_promotes_stronger_leader(monkeypatch):
    """
    Verifies that if a subsequent stock in the same sector breaks out with
    decisively stronger institutional volume (>1.25x leader RVOL and higher confidence),
    it is promoted as the new Sector Leader.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    engine = AutoAlertEngine()
    engine.clear_alerts()

    now_iso = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Initial moderate setup: WIPRO with RVOL 1.5x, 75% confidence
    wipro_alert = AutoAlert(
        alert_id="aa-squeeze-wipro-20261018",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="WIPRO",
        exchange="NSE",
        direction="BULLISH",
        headline="WIPRO — Squeeze Breakout",
        summary="Testing resistance",
        ltp=520.0,
        trigger_level=518.0,
        target_level=545.0,
        stop_loss=505.0,
        confidence=75,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
        time_horizon="SWING_MID",
        metrics={"tod_rvol": 1.5},
    )
    assert engine.record_alert(wipro_alert) is True

    # 2. Institutional monster breakout: TCS with RVOL 3.2x, 90% confidence
    tcs_alert = AutoAlert(
        alert_id="aa-squeeze-tcs-20261018",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS — Major Squeeze Explosion",
        summary="Massive institutional surge",
        ltp=4200.0,
        trigger_level=4180.0,
        target_level=4350.0,
        stop_loss=4100.0,
        confidence=90,
        created_at=now_iso,
        environment="LIVE",
        is_live=True,
        time_horizon="SWING_MID",
        metrics={"tod_rvol": 3.2},
    )
    assert engine.record_alert(tcs_alert) is True
    # TCS is promoted as Sector Leader
    assert tcs_alert.metrics.get("is_sector_leader") is True
    assert tcs_alert.metrics.get("promoted_over") == "WIPRO"
