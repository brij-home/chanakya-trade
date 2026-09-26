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
        metrics={"atr": 120.0},
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
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Gamma Blast",
        summary="OI unwinding surge",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2450.0,
        target_level=2600.0,
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


def test_tier2_quant_fallback_long_put_guidance(auditor):
    """
    Quant fallback scrutiny on a Long Put (BUY PE) must generate coherent option buyer
    guidance, not short-selling commands.
    """
    alert = AutoAlert(
        alert_id="opt-mom-coforge-pe",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="COFORGE",
        exchange="NFO",
        direction="BEARISH",
        headline="Coforge 1840 PE Surge",
        summary="Put buying",
        ltp=48.0,
        trigger_level=48.0,
        stop_loss=36.0,
        target_level=72.0,
        strike=1840.0,
        option_type="PE",
        contract_symbol="COFORGE1840PE",
        actionable_plan={"action": "BUY PE", "entry_range": "₹47.0 – ₹49.0"},
        is_live=True,
        environment="LIVE",
    )
    result = auditor._generate_quantitative_fallback(alert, {"level_coherence": True})
    assert result.status == "APPROVED"
    assert "Buy PE" in result.actionable_guidance
    assert "Rs.36.0" in result.actionable_guidance
    assert "Short near" not in result.actionable_guidance
    assert "Put momentum" in result.logic_confirmation


def test_scrutiny_ttl_cache(auditor):
    """
    Subsequent scrutiny invocations for the exact same setup within the TTL window
    must return cached ScrutinyResult without re-invoking LLM.
    """
    alert = AutoAlert(
        alert_id="test-cache-1",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:CACHEDSYM",
        exchange="NSE",
        direction="BULLISH",
        headline="Cache Test Setup",
        summary="Testing cache",
        ltp=500.0,
        trigger_level=500.0,
        stop_loss=485.0,
        target_level=550.0,
        is_live=True,
        environment="LIVE",
    )
    # First call - populates cache
    with patch.object(auditor, "_execute_fast_llm_scrutiny", return_value=None) as mock_llm:
        res1 = auditor.scrutinize_alert(alert)
        assert res1.status == "APPROVED"
        assert mock_llm.call_count == 1

    # Second call - returns from cache without calling LLM
    with patch.object(auditor, "_execute_fast_llm_scrutiny") as mock_llm2:
        res2 = auditor.scrutinize_alert(alert)
        assert res2.status == "APPROVED"
        assert res2.score == res1.score
        assert mock_llm2.call_count == 0


def test_tier1_bid_ask_spread_slippage_rejection(auditor):
    """Excessive bid-ask spread triggers institutional slippage veto."""
    # Equity with 2.5% spread (threshold 1.5%)
    alert_equity_wide = AutoAlert(
        alert_id="test-spread-wide-eq",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:ILLIQUIDCO",
        exchange="NSE",
        direction="BULLISH",
        headline="Illiquid Co Setup",
        summary="Wide spread test",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,
        target_level=1060.0,
        metrics={"bid": 980.0, "ask": 1005.0},  # Spread = 25 / 1000 = 2.5%
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_equity_wide)
    assert passed is False
    assert "Slippage Hazard Veto" in reason
    assert flags["spread_valid"] is False

    # Equity with 0.4% tight spread passes
    alert_equity_tight = AutoAlert(
        alert_id="test-spread-tight-eq",
        alert_type="PRECURSOR_RADAR",
        stage="EARLY_WARNING",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Setup",
        summary="Tight spread test",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=980.0,
        target_level=1060.0,
        metrics={"bid": 998.0, "ask": 1002.0},  # Spread = 4 / 1000 = 0.4%
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_equity_tight)
    assert passed is True
    assert flags["spread_valid"] is True


def test_tier1_stock_option_illiquidity_rejection(auditor):
    """Stock options with dry OI or low volume must be rejected to prevent execution traps."""
    # Stock option with OI < 100
    alert_low_oi = AutoAlert(
        alert_id="test-opt-low-oi",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:TATACHEM",
        exchange="NFO",
        direction="BULLISH",
        headline="Tata Chem Call Surge",
        summary="Low OI test",
        ltp=45.0,
        trigger_level=45.0,
        stop_loss=36.0,
        target_level=65.0,
        strike=1100.0,
        option_type="CE",
        metrics={"oi": 40, "volume": 150},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_low_oi)
    assert passed is False
    assert "Stock Option Illiquidity Trap" in reason
    assert "Open Interest (40) < 50" in reason

    # Stock option with Volume < 50
    alert_low_vol = AutoAlert(
        alert_id="test-opt-low-vol",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:TATACHEM",
        exchange="NFO",
        direction="BULLISH",
        headline="Tata Chem Call Low Volume",
        summary="Low volume test",
        ltp=45.0,
        trigger_level=45.0,
        stop_loss=36.0,
        target_level=65.0,
        strike=1100.0,
        option_type="CE",
        metrics={"oi": 500, "volume": 25},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_low_vol)
    assert passed is False
    assert "Stock Option Illiquidity Trap" in reason
    assert "Daily Volume (25) < 50" in reason

    # Liquid stock option passes
    alert_liquid_opt = AutoAlert(
        alert_id="test-opt-liquid",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:TATACHEM",
        exchange="NFO",
        direction="BULLISH",
        headline="Tata Chem Call Liquid",
        summary="Liquid opt test",
        ltp=45.0,
        trigger_level=45.0,
        stop_loss=36.0,
        target_level=65.0,
        strike=1100.0,
        option_type="CE",
        metrics={"oi": 2500, "volume": 850},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_liquid_opt)
    assert passed is True
    assert flags["liquidity_valid"] is True


def test_tier1_midday_lunch_lull_rvol_rejection(auditor):
    """Breakouts attempted during 11:30-13:00 IST without RVOL >= 1.8x are vetoed as false breakouts."""

    # 12:15 IST with low RVOL (1.2x) -> VETO
    alert_midday_low_vol = AutoAlert(
        alert_id="test-midday-low-vol",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Infy Midday Breakout",
        summary="Midday test",
        ltp=1950.0,
        trigger_level=1950.0,
        stop_loss=1925.0,
        target_level=2020.0,
        created_at="2026-09-14 12:15:00 IST",
        metrics={"rvol": 1.2},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_midday_low_vol)
    assert passed is False
    assert "Midday False Breakout Trap" in reason
    assert flags["midday_rvol_valid"] is False

    # 12:15 IST with institutional volume (2.5x) -> PASS
    alert_midday_high_vol = AutoAlert(
        alert_id="test-midday-high-vol",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Infy Midday Breakout High Volume",
        summary="Midday high volume test",
        ltp=1950.0,
        trigger_level=1950.0,
        stop_loss=1925.0,
        target_level=2020.0,
        created_at="2026-09-14 12:15:00 IST",
        metrics={"rvol": 2.5},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_midday_high_vol)
    assert passed is True
    assert flags["midday_rvol_valid"] is True

    # 10:15 IST (morning rush) with RVOL 1.2x -> PASS
    alert_morning = AutoAlert(
        alert_id="test-morning-vol",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Infy Morning Breakout",
        summary="Morning test",
        ltp=1950.0,
        trigger_level=1950.0,
        stop_loss=1925.0,
        target_level=2020.0,
        created_at="2026-09-14 10:15:00 IST",
        metrics={"rvol": 1.2},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_morning)
    assert passed is True
    assert flags["midday_rvol_valid"] is True


def test_tier1_stock_option_morning_ramp_up_volume(auditor):
    """At 09:25 IST, 20 contracts volume passes morning ramp-up threshold (min 15)."""
    alert_morning_opt = AutoAlert(
        alert_id="test-opt-morning-ramp",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:TATACHEM",
        exchange="NFO",
        direction="BULLISH",
        headline="Tata Chem Morning Call",
        summary="Morning ramp-up test",
        ltp=45.0,
        trigger_level=45.0,
        stop_loss=36.0,
        target_level=65.0,
        strike=1100.0,
        option_type="CE",
        created_at="2026-09-14 09:25:00 IST",
        metrics={"oi": 1500, "volume": 20},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_morning_opt)
    assert passed is True
    assert flags["liquidity_valid"] is True


def test_tier1_stock_option_shares_to_contracts_normalization(auditor):
    """If OI is passed in shares (e.g. 25,000 shares for lot size 500 = 50 contracts), it is correctly rejected if < 100 contracts."""
    alert_shares_oi = AutoAlert(
        alert_id="test-opt-shares-norm",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:TATACHEM",
        exchange="NFO",
        direction="BULLISH",
        headline="Tata Chem Shares Normalization",
        summary="Shares normalization test",
        ltp=45.0,
        trigger_level=45.0,
        stop_loss=36.0,
        target_level=65.0,
        strike=1100.0,
        option_type="CE",
        lot_size=500,
        created_at="2026-09-14 11:00:00 IST",
        # 15,000 shares / 500 = 30 contracts < 50 contracts -> VETO
        metrics={"oi": 15000, "volume": 50000},
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_shares_oi)
    assert passed is False
    assert "Stock Option Illiquidity Trap" in reason
    assert "Open Interest (30) < 50" in reason


def test_tier1_commodity_option_exemption_from_stock_gate(auditor):
    """MCX Commodity options are exempt from equity single-stock options liquidity rules."""
    alert_mcx_opt = AutoAlert(
        alert_id="test-mcx-opt",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="MCX:CRUDEOIL",
        exchange="MCX",
        segment="COMMODITY",
        direction="BULLISH",
        headline="Crude Oil Call Surge",
        summary="MCX test",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=120.0,
        target_level=220.0,
        strike=6000.0,
        option_type="CE",
        metrics={"oi": 35, "volume": 18},
        is_live=True,
        environment="LIVE",
        created_at="2026-09-23 11:00:00",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_mcx_opt)
    assert passed is True
    assert flags["liquidity_valid"] is True


def test_tier1_opposing_supply_collision_veto(auditor):
    """Bullish/CE alert right beneath PDH/Day High is vetoed as Opposing Supply Collision."""
    alert_supply_trap = AutoAlert(
        alert_id="test-supply-collision",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NSE:NIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="Nifty Call Surge",
        summary="Nifty CE test",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=180.0,
        strike=23600.0,
        option_type="CE",
        metrics={
            "spot": 23595.0,
            "vwap": 23570.0,
            "prev_day_high": 23600.0,  # Only 5 pts / 0.02% above spot!
            "day_high": 23598.0,
            "day_low": 23480.0,
        },
        is_live=True,
        environment="LIVE",
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert_supply_trap)
    assert passed is False
    assert "Opposing Supply Collision" in reason
    assert "Day High" in reason or "Previous Day High (PDH)" in reason


def test_tier1_opposing_demand_collision_veto(auditor):
    """Bearish/PE alert right above PDL/Day Low is vetoed as Opposing Demand Collision."""
    alert_demand_trap = AutoAlert(
        alert_id="test-demand-collision",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NSE:NIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BEARISH",
        headline="Nifty Put Surge",
        summary="Nifty PE test",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=180.0,
        strike=23400.0,
        option_type="PE",
        metrics={
            "spot": 23405.0,
            "vwap": 23430.0,
            "prev_day_low": 23400.0,  # Only 5 pts / 0.02% below spot!
            "day_high": 23550.0,
            "day_low": 23402.0,
        },
        is_live=True,
        environment="LIVE",
    )
    with patch(
        "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
        return_value=(False, ""),
    ):
        passed, reason, flags = auditor.verify_tier1_sanity(alert_demand_trap)
    assert passed is False
    assert "Opposing Demand Collision" in reason
    assert "Day Low" in reason or "Previous Day Low (PDL)" in reason


def test_tier1_vwap_overextension_veto(auditor):
    """Index CE alert with spot extended > 0.65% above VWAP is vetoed as Climax Exhaustion."""
    alert_vwap_ext = AutoAlert(
        alert_id="test-vwap-ext",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NSE:NIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BULLISH",
        headline="Nifty Call Chase",
        summary="Nifty CE test",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=180.0,
        strike=23800.0,
        option_type="CE",
        metrics={
            "spot": 23700.0,
            "vwap": 23500.0,  # +0.85% above VWAP
            "spot_to_vwap_pct": 0.85,
        },
        is_live=True,
        environment="LIVE",
    )
    with patch(
        "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
        return_value=(False, ""),
    ):
        passed, reason, flags = auditor.verify_tier1_sanity(alert_vwap_ext)
    assert passed is False
    assert "Climax Exhaustion" in reason
    assert "extended" in reason


def test_tier1_vwap_capitulation_veto(auditor):
    """Index PE alert with spot extended < -0.65% below VWAP is vetoed as Capitulation Exhaustion."""
    alert_vwap_cap = AutoAlert(
        alert_id="test-vwap-cap",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NSE:NIFTY",
        exchange="NFO",
        segment="FNO_INDEX",
        direction="BEARISH",
        headline="Nifty Put Chase",
        summary="Nifty PE test",
        ltp=120.0,
        trigger_level=120.0,
        stop_loss=90.0,
        target_level=180.0,
        strike=23300.0,
        option_type="PE",
        metrics={
            "spot": 23300.0,
            "vwap": 23500.0,  # -0.85% below VWAP
            "spot_to_vwap_pct": -0.85,
        },
        is_live=True,
        environment="LIVE",
    )
    with patch(
        "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
        return_value=(False, ""),
    ):
        passed, reason, flags = auditor.verify_tier1_sanity(alert_vwap_cap)
    assert passed is False
    assert "Capitulation Exhaustion" in reason
    assert "extended" in reason
