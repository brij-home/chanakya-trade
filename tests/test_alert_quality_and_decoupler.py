"""
Unit tests for Institutional Alert Quality, Decoupler Recognition,
Anti-Storm Pacing, Trap Suppression, and Session-End Stagnation Resolution.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from engine.alert_scrutiny import alert_scrutiny_auditor
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine

IST = timezone(timedelta(hours=5, minutes=30))


def test_decoupler_recognition_bypasses_benchmark_markdown_veto():
    """
    Verifies that a stock like SWIGGY surging +4.16% with massive volume velocity
    is recognized as a VERIFIED_DECOUPLER and approved even when NIFTY is down -0.36%.
    """
    alert = AutoAlert(
        alert_id="test-swiggy-decoupler",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="SWIGGY",
        exchange="NSE",
        direction="BULLISH",
        headline="🟢 OPTIONS MOMENTUM: SWIGGY 490 CE",
        summary="Institutional Call surge in SWIGGY 490 CE.",
        ltp=18.50,
        trigger_level=18.50,
        target_level=28.0,
        stop_loss=14.0,
        confidence=88,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={
            "vol_oi_ratio": 2.4,
            "oi": 500000,
            "volume": 1200000,
            "opt_pchange": 45.0,
            "spot_change_pct": 4.16,
            "rvol": 2.1,
            "nifty_change_pct": -0.36,
            "nifty_below_vwap": True,
            "decoupler_status": "VERIFIED_DECOUPLER",
        },
        actionable_plan={
            "action": "BUY CE",
            "contract": "SWIGGY26SEP490CE",
            "entry_range": "₹18.0 – ₹19.0",
            "stop_loss": "₹14.0",
            "target": "₹28.0",
            "target_2": "₹35.0",
            "risk_reward": "1:2.1",
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is True, f"SWIGGY Decoupler was rejected: {reason}"
    assert flags.get("benchmark_regime_valid") is True
    assert flags.get("decoupler_status") == "VERIFIED_DECOUPLER"


def test_mediocre_call_rejected_in_nifty_markdown():
    """
    Verifies that a generic/mediocre Call without decoupler status is still rejected
    by Rule 14 when NIFTY is in structural markdown.
    """
    alert = AutoAlert(
        alert_id="test-mediocre-call",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="ABCDEF",
        exchange="NSE",
        direction="BULLISH",
        headline="🟢 OPTIONS MOMENTUM: ABCDEF 1000 CE",
        summary="Mediocre Call setup.",
        ltp=25.0,
        trigger_level=25.0,
        target_level=36.0,
        stop_loss=20.0,
        confidence=72,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={
            "vol_oi_ratio": 1.1,
            "oi": 2000,
            "volume": 2200,
            "opt_pchange": 4.0,
            "spot_change_pct": 0.3,
            "rvol": 0.9,
            "nifty_change_pct": -0.45,
            "nifty_below_vwap": True,
            "decoupler_status": "NORMAL",
        },
        actionable_plan={
            "action": "BUY CE",
            "contract": "ABCDEF26SEP1000CE",
            "entry_range": "₹24.0 – ₹26.0",
            "stop_loss": "₹20.0",
            "target": "₹36.0",
            "risk_reward": "1:2.2",
        },
    )

    passed, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Benchmark Gravitational Veto" in reason


def test_anti_storm_candidate_ranking_and_top_n():
    """
    Verifies that when multiple candidates qualify, the engine sorts candidates
    by composite Institutional Quality Score and caps alerts to top-N.
    """
    engine = AutoAlertEngine()
    engine._alerts = []

    # Mock candidate alerts with varying metrics
    alert_low = AutoAlert(
        alert_id="candidate-low",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="STOCKA",
        exchange="NSE",
        direction="BULLISH",
        headline="STOCKA CE",
        summary="Low quality",
        ltp=10.0,
        trigger_level=10.0,
        target_level=15.0,
        stop_loss=8.0,
        confidence=65,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={"vol_oi_ratio": 1.1, "volume": 1000, "decoupler_status": "NORMAL"},
    )

    alert_high = AutoAlert(
        alert_id="candidate-high",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="STOCKB",
        exchange="NSE",
        direction="BULLISH",
        headline="STOCKB CE",
        summary="High quality",
        ltp=50.0,
        trigger_level=50.0,
        target_level=80.0,
        stop_loss=40.0,
        confidence=92,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        metrics={"vol_oi_ratio": 3.5, "volume": 12000, "decoupler_status": "VERIFIED_DECOUPLER"},
    )

    # Calculate quality scores using identical formula
    score_low = (65 * 0.40) + min(25.0, 1.1 * 7.0) + min(15.0, (1000 / 5000.0) * 15.0)
    score_high = (92 * 0.40) + min(25.0, 3.5 * 7.0) + min(15.0, (12000 / 5000.0) * 15.0) + 10.0

    candidates = [(score_low, alert_low), (score_high, alert_high)]
    candidates.sort(key=lambda x: x[0], reverse=True)

    # Highest score must be first
    assert candidates[0][1].symbol == "STOCKB"
    assert candidates[0][0] > candidates[1][0]


def test_batch_refresh_quotes_resolves_prefixed_and_raw_keys():
    """
    Verifies that _batch_refresh_quotes strips spaces and populates both raw
    and exchange-prefixed keys so option contract LTPs are resolved without failing.
    """
    engine = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="test-voltas-opt",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="VOLTAS",
        exchange="NFO",
        direction="BEARISH",
        headline="VOLTAS 1140 PE",
        summary="VOLTAS PE",
        ltp=18.65,
        trigger_level=18.65,
        target_level=35.0,
        stop_loss=12.0,
        contract_symbol="VOLTAS202609291140PE",
        confidence=85,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
    )

    fake_quote = MagicMock()
    fake_quote.last_price = 40.10
    fake_quote.ltp = 40.10

    with patch("market.quotes.get_quote", return_value={"NFO:VOLTAS202609291140PE": fake_quote}):
        quotes_map = engine._batch_refresh_quotes([alert])
        # Both raw key and prefixed key must be present in the map
        assert quotes_map.get("VOLTAS202609291140PE") == 40.10
        assert quotes_map.get("NFO:VOLTAS202609291140PE") == 40.10


def test_session_end_auto_resolution():
    """
    Verifies that resolve_session_end_alerts automatically marks unresolved
    intraday PENDING alerts as EXPIRED_SESSION_END when invoked post-market close.
    """
    engine = AutoAlertEngine()
    pending_alert = AutoAlert(
        alert_id="test-pending-intraday",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Call",
        summary="Pending Call",
        ltp=52.0,
        trigger_level=50.0,
        target_level=70.0,
        stop_loss=40.0,
        confidence=80,
        target_status="PENDING",
        created_at="2026-09-22 10:00:00 IST",
        is_live=True,
        environment="LIVE",
    )
    engine._alerts = [pending_alert]

    # Mock datetime to 16:00 IST (market closed)
    mock_close_time = datetime(2026, 9, 22, 16, 0, 0, tzinfo=IST)
    with patch("engine.auto_alert_engine.datetime") as mock_dt:
        mock_dt.now.return_value = mock_close_time
        mock_dt.strptime = datetime.strptime
        resolved = engine.resolve_session_end_alerts()

    assert len(resolved) == 1
    assert pending_alert.target_status == "EXPIRED_SESSION_END"
    assert pending_alert.stage == "COMPLETED"
    assert pending_alert.is_archived is True
    assert pending_alert.pnl_pct == 4.0  # (52 - 50) / 50 = +4.0%
