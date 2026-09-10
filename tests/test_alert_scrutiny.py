"""
tests/test_alert_scrutiny.py
────────────────────────────
Comprehensive test suite for the Two-Tiered AI Sanity and Scrutiny Funnel.
Verifies:
  - Tier-1 Mathematical Sanity Gate (level coherence, R:R asymmetry, no-chase boundary)
  - Tier-2 Fast-LLM Devil's Advocate Scrutiny
  - Deterministic Quantitative Fallback
  - Integration with AutoAlertEngine.record_alert() for gated vs urgent signals.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from engine.alert_scrutiny import AlertScrutinyAuditor, ScrutinyResult
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)


def test_tier1_level_sanctity_bullish(auditor: AlertScrutinyAuditor):
    """Valid bullish setup passes Tier-1 sanity."""
    alert = AutoAlert(
        alert_id="test-bull-1",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Trent VCP Squeeze Ignition",
        summary="Coiling at 20-day high with dry volume",
        ltp=6800.0,
        trigger_level=6800.0,
        stop_loss=6650.0,  # 150 pts risk (2.2%)
        target_level=7250.0,  # 450 pts reward (1:3.0 R:R)
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True
    assert reason == ""
    assert flags["level_coherence"] is True
    assert flags["rr_valid"] is True
    assert flags["no_chase"] is True


def test_tier1_inverted_stop_loss_rejection(auditor: AlertScrutinyAuditor):
    """Bullish setup with Stop-Loss >= LTP is rejected immediately."""
    alert = AutoAlert(
        alert_id="test-bull-inverted",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Trent Inverted SL",
        summary="Bad SL",
        ltp=6800.0,
        trigger_level=6800.0,
        stop_loss=6850.0,  # Inverted! Higher than LTP
        target_level=7200.0,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Inverted Stop-Loss" in reason
    assert flags["level_coherence"] is False


def test_tier1_bearish_inverted_target_rejection(auditor: AlertScrutinyAuditor):
    """Bearish setup with Target >= LTP is rejected."""
    alert = AutoAlert(
        alert_id="test-bear-inverted-tgt",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:DIXON",
        exchange="NSE",
        direction="BEARISH",
        headline="Dixon Breakdown",
        summary="Short breakdown",
        ltp=13500.0,
        trigger_level=13500.0,
        stop_loss=13650.0,
        target_level=13800.0,  # Inverted! Higher than LTP
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Inverted Bearish Target" in reason


def test_tier1_unfavorable_rr_ratio_rejection(auditor: AlertScrutinyAuditor):
    """Setup with R:R < 1:1.3 is rejected."""
    alert = AutoAlert(
        alert_id="test-poor-rr",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Infy Coiling",
        summary="Low asymmetry",
        ltp=1900.0,
        trigger_level=1900.0,
        stop_loss=1850.0,  # 50 pts risk
        target_level=1930.0,  # 30 pts reward -> 1:0.6 R:R < 1:1.3
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Unfavorable Risk:Reward ratio" in reason
    assert flags["rr_valid"] is False


def test_tier1_no_chase_violation(auditor: AlertScrutinyAuditor):
    """Setup where LTP is extended >2.5% past trigger level is rejected."""
    alert = AutoAlert(
        alert_id="test-chase",
        alert_type="PRECURSOR_RADAR",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Breakout",
        summary="Extended candle",
        ltp=3085.0,  # 2.83% above trigger 3000!
        trigger_level=3000.0,
        stop_loss=2950.0,  # 135 pts risk
        target_level=3400.0,  # 315 pts reward -> 1:2.33 R:R
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "No-Chase Violation" in reason


def test_tier2_deterministic_fallback(auditor: AlertScrutinyAuditor):
    """When LLM is unavailable, deterministic quantitative fallback scores setup cleanly."""
    alert = AutoAlert(
        alert_id="test-fallback",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="EARLY_WARNING",
        symbol="NSE:PERSISTENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Persistent Pocket Pivot",
        summary="Accumulation inside base",
        ltp=5400.0,
        trigger_level=5400.0,
        stop_loss=5280.0,  # 120 pts risk
        target_level=5800.0,  # 400 pts reward -> 1:3.3 R:R
        metrics={"rvol": 2.2},
        is_live=True,
        environment="LIVE",
    )
    # Force LLM exception to verify zero-blackout fallback
    with patch.object(
        auditor, "_execute_fast_llm_scrutiny", side_effect=RuntimeError("Provider 429")
    ):
        result = auditor.scrutinize_alert(alert)

    assert result.status == "APPROVED"
    assert result.score >= 80
    assert result.auditor_model == "QUANT_FALLBACK"
    assert "structural pivot holds" in result.logic_confirmation
    assert "Overhead resistance" in result.trap_risk_warning


def test_tier2_fast_llm_approval(auditor: AlertScrutinyAuditor):
    """Mock Fast-LLM returning valid structured JSON is parsed correctly."""
    alert = AutoAlert(
        alert_id="test-llm-approval",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:DIXON",
        exchange="NSE",
        direction="BEARISH",
        headline="Dixon Breakdown Below Base",
        summary="Heavy institutional distribution",
        ltp=13550.0,
        trigger_level=13550.0,
        stop_loss=13680.0,  # 130 pts risk
        target_level=13100.0,  # 450 pts reward (1:3.4 R:R)
        is_live=True,
        environment="LIVE",
    )
    mock_llm_json = (
        "{\n"
        '  "verdict": "APPROVED",\n'
        '  "score": 88,\n'
        '  "logic_confirmation": "Structural breakdown below 5-day base confirmed by Short Buildup.",\n'
        '  "trap_risk_warning": "Immediate 200-EMA support at ₹13,350; scale 50% quickly.",\n'
        '  "actionable_guidance": "Short on retest of ₹13,580; stop above ₹13,680."\n'
        "}"
    )
    mock_provider = MagicMock()
    mock_provider.chat.return_value = mock_llm_json

    with patch("agent.core.get_fast_provider", return_value=mock_provider):
        result = auditor.scrutinize_alert(alert)

    assert result.status == "APPROVED"
    assert result.score == 88
    assert result.auditor_model == "FAST_LLM"
    assert "Structural breakdown" in result.logic_confirmation
    assert "200-EMA support" in result.trap_risk_warning


def test_auto_alert_engine_gated_rejection_on_inverted_sl(tmp_path):
    """AutoAlertEngine rejects alert if Tier-1 sanity fails."""
    engine = AutoAlertEngine()
    engine._alerts = []
    bad_alert = AutoAlert(
        alert_id="bad-gated-1",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:BADTICKER",
        exchange="NSE",
        direction="BULLISH",
        headline="Inverted SL Alert",
        summary="Bad SL",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=110.0,  # Inverted!
        target_level=150.0,
        is_live=True,
        environment="LIVE",
    )
    recorded = engine.record_alert(bad_alert)
    assert recorded is False
    assert len(engine._alerts) == 0


def test_auto_alert_engine_gated_approval_attaches_scrutiny():
    """Gated alert passing scrutiny gets scrutiny dossier attached and confidence updated."""
    engine = AutoAlertEngine()
    engine._alerts = []
    good_alert = AutoAlert(
        alert_id="good-gated-1",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:GOODTICKER",
        exchange="NSE",
        direction="BULLISH",
        headline="Good Coiling",
        summary="Valid setup",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=970.0,
        target_level=1100.0,
        confidence=75,
        is_live=True,
        environment="LIVE",
    )
    with patch(
        "engine.alert_scrutiny.alert_scrutiny_auditor._execute_fast_llm_scrutiny",
        return_value=ScrutinyResult(
            status="APPROVED",
            score=91,
            logic_confirmation="High edge VCP setup.",
            trap_risk_warning="Watch 50-SMA pivot.",
            actionable_guidance="Trail on 20-EMA.",
            auditor_model="FAST_LLM",
        ),
    ):
        recorded = engine.record_alert(good_alert)

    assert recorded is True
    assert len(engine._alerts) == 1
    stored = engine._alerts[0]
    assert stored.metrics.get("scrutiny") is not None
    assert stored.metrics["scrutiny"]["score"] == 91
    assert stored.confidence == 91


def test_auto_alert_engine_urgent_signal_enrichment():
    """Urgent signal (Gamma Blast) records immediately with QUANT_VERIFIED and runs async enrichment."""
    engine = AutoAlertEngine()
    engine._alerts = []
    urgent_alert = AutoAlert(
        alert_id="urgent-gamma-1",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NSE:NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma Blast",
        summary="OI unwinding surge",
        ltp=25000.0,
        trigger_level=25000.0,
        stop_loss=24900.0,
        target_level=25300.0,
        confidence=82,
        is_live=True,
        environment="LIVE",
    )
    with patch.object(engine, "_async_enrich_scrutiny") as mock_async:
        recorded = engine.record_alert(urgent_alert)

    assert recorded is True
    assert len(engine._alerts) == 1
    assert urgent_alert.metrics["scrutiny"]["status"] == "QUANT_VERIFIED"
    mock_async.assert_called_once_with(urgent_alert)


def test_tier1_bearish_with_option_recommendation(auditor: AlertScrutinyAuditor):
    """
    Underlying bearish trade (e.g. Dixon breakdown) with recommended Put option metadata
    must NOT be rejected as an inverted stop-loss.
    LTP=13500, SL=13650 (above LTP), T1=13200 (below LTP), strike=13500, option_type=PE, option_premium=450.
    """
    alert = AutoAlert(
        alert_id="spark-bear-dixon",
        alert_type="INTRADAY_BREAKDOWN_SPARK",
        stage="IGNITED",
        symbol="NSE:DIXON",
        exchange="NSE",
        direction="BEARISH",
        headline="Dixon Breakdown Spark",
        summary="Lost VWAP with 2.5x RVOL",
        ltp=13500.0,
        trigger_level=13500.0,
        stop_loss=13650.0,  # 150 pts risk (1.11%)
        target_level=13200.0,  # 300 pts reward (1:2.0 R:R)
        strike=13500.0,
        option_type="PE",
        option_premium=450.0,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True, f"Failed Tier-1 sanity unexpectedly: {reason}"
    assert reason == ""
    assert flags["level_coherence"] is True
    assert flags["risk_within_bounds"] is True
    assert flags["rr_valid"] is True
    assert flags["no_chase"] is True


def test_tier1_options_momentum_put_buyer(auditor: AlertScrutinyAuditor):
    """
    Buying an option (even a Put) represents long option premium where SL < LTP < T1.
    LTP=450.0, SL=337.5 (below LTP), T1=675.0 (above LTP).
    """
    alert = AutoAlert(
        alert_id="opt-mom-put",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:DIXON",
        exchange="NFO",
        direction="BEARISH",
        headline="Dixon 13500 PE Institutional Surge",
        summary="Heavy Put buying",
        ltp=450.0,
        trigger_level=450.0,
        stop_loss=337.5,  # 25% risk stop
        target_level=675.0,  # 2x risk reward
        strike=13500.0,
        option_type="PE",
        option_premium=450.0,
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True, f"Failed Tier-1 sanity unexpectedly: {reason}"
    assert reason == ""
    assert flags["level_coherence"] is True
    assert flags["risk_within_bounds"] is True
    assert flags["rr_valid"] is True
    assert flags["no_chase"] is True
