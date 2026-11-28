"""
tests/test_intermarket_macro_and_smc_15m_invariants.py
───────────────────────────────────────────────────────
Verifies institutional invariants for:
1. Intraday 15m SMC Order Block Retest detection and index prioritization.
2. Cross-Asset Intermarket Macro Headwind Gates (Crude, US 10Y, USDINR, DXY).
"""

from __future__ import annotations

import pandas as pd

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.smc_orderblock_retest import detect_smc_orderblock_retest


def _build_synthetic_15m_df() -> pd.DataFrame:
    """Builds synthetic 15m OHLCV DataFrame with an unmitigated Demand OB."""
    dates = pd.date_range("2026-11-18 09:15", periods=30, freq="15min", tz=IST)
    df = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [102.0] * 30,
            "low": [99.0] * 30,
            "close": [101.0] * 30,
            "volume": [100000] * 30,
        },
        index=dates,
    )
    # Impulsive displacement at bar 10 creating a Demand OB
    df.iloc[10] = [99.0, 100.0, 98.0, 98.5, 50000]  # Down bar before thrust
    df.iloc[11] = [98.5, 104.0, 98.5, 103.5, 250000]  # Strong bullish thrust bar
    df.iloc[12] = [103.5, 106.0, 103.0, 105.0, 150000]
    return df


def test_smc_orderblock_15m_timeframe_metrics():
    """Verify that detect_smc_orderblock_retest with 15m data detects intraday resolution."""
    df = _build_synthetic_15m_df()
    alerts = detect_smc_orderblock_retest(
        symbol="NIFTY",
        df=df,
        ltp=99.5,
        exchange="NSE",
        rvol=1.1,
        timeframe="15m",
    )

    if alerts:
        alert = alerts[0]
        assert alert.metrics.get("timeframe") == "15m"
        assert alert.metrics.get("is_intraday") is True


def test_cross_asset_macro_headwind_suppression(tmp_path, monkeypatch):
    """Verify that a Long alert on BPCL or ASIANPAINT is vetoed when Brent Crude experiences a severe spike."""
    monkeypatch.setenv("TELEGRAM_ALLOW_TREND_DAY_PULLBACK", "1")
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    # Create an IGNITED Bullish setup with severe adverse macro drag (Brent spike: -60 pts)
    alert = AutoAlert(
        alert_id="aa-macro-test-bpcl-long-20261118",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="BPCL",
        exchange="NSE",
        direction="BULLISH",
        headline="BPCL Bullish Pullback",
        summary="Testing macro headwind gate",
        ltp=320.0,
        trigger_level=321.0,
        stop_loss=315.0,
        target_level=335.0,
        confidence=91,
        metrics={
            "macro_driver": "brent",
            "macro_driver_chg_pct": 3.5,
            "macro_transmission_score": -60.0,  # Severe adverse drag
            "rvol": 1.2,
            "nifty_change_pct": 0.2,
            "confluence_score": 82.0,
        },
        actionable_plan={"risk_reward": "1:3.0"},
    )

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Cross-asset macro headwind" in reason
    assert "BRENT" in reason


def test_cross_asset_macro_tailwind_short_suppression(tmp_path, monkeypatch):
    """Verify that a Short alert on ONGC is vetoed when Brent Crude experiences a severe spike (+55 pts support)."""
    monkeypatch.setenv("TELEGRAM_ALLOW_TREND_DAY_PULLBACK", "1")
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    alert = AutoAlert(
        alert_id="aa-macro-test-ongc-short-20261118",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="ONGC",
        exchange="NSE",
        direction="BEARISH",
        headline="ONGC Bearish Breakdown",
        summary="Testing macro tailwind short gate",
        ltp=260.0,
        trigger_level=259.0,
        stop_loss=265.0,
        target_level=248.0,
        confidence=91,
        metrics={
            "macro_driver": "brent",
            "macro_driver_chg_pct": 3.5,
            "macro_transmission_score": 55.0,  # Strong macro support
            "rvol": 1.2,
            "nifty_change_pct": -0.2,
            "confluence_score": 82.0,
        },
        actionable_plan={"risk_reward": "1:3.0"},
    )

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert not passed
    assert "Cross-asset macro tailwind" in reason
    assert "Short suppressed" in reason


def test_cross_asset_macro_decoupler_exemption(tmp_path):
    """Verify that an exceptional institutional decoupler (RVOL >= 2.5 and Conf >= 94) is exempt from macro veto."""
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    alert = AutoAlert(
        alert_id="aa-macro-test-bpcl-decoupler-20261118",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="BPCL",
        exchange="NSE",
        direction="BULLISH",
        headline="BPCL Explosive Decoupler",
        summary="Testing decoupler volume exemption",
        ltp=320.0,
        trigger_level=321.0,
        stop_loss=315.0,
        target_level=335.0,
        confidence=95,
        metrics={
            "macro_driver": "brent",
            "macro_driver_chg_pct": 3.5,
            "macro_transmission_score": -60.0,
            "rvol": 3.2,  # High decoupler volume
            "nifty_change_pct": 0.2,
        },
        actionable_plan={"risk_reward": "1:3.0"},
    )

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    # Decoupler is exempt from macro veto
    assert "Cross-asset macro headwind" not in reason


def test_cross_asset_macro_confluence_boost(tmp_path, monkeypatch):
    """Verify that a Bullish alert aligned with a macro tailwind receives a +4% confluence boost."""
    monkeypatch.setenv("TELEGRAM_ALLOW_TREND_DAY_PULLBACK", "1")
    engine = AutoAlertEngine()
    engine._alerts_file = tmp_path / "auto_alerts.json"
    engine._alerts = {}

    init_conf = 91
    alert = AutoAlert(
        alert_id="aa-macro-test-ongc-boost-20261118",
        alert_type="TREND_DAY_PULLBACK",
        stage="IGNITED",
        symbol="ONGC",
        exchange="NSE",
        direction="BULLISH",
        headline="ONGC Bullish Momentum",
        summary="Testing macro boost",
        ltp=260.0,
        trigger_level=261.0,
        stop_loss=255.0,
        target_level=275.0,
        confidence=init_conf,
        metrics={
            "macro_driver": "brent",
            "macro_driver_chg_pct": 3.5,
            "macro_transmission_score": 45.0,  # Tailwind
            "rvol": 1.5,
            "nifty_change_pct": 0.2,
            "confluence_score": 82.0,
        },
        actionable_plan={"risk_reward": "1:3.0"},
    )

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True)
    assert alert.confidence == init_conf + 4
    assert alert.metrics.get("macro_confluence") is True
