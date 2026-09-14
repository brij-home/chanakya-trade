"""
tests/test_smc_and_horizon_alerts.py
────────────────────────────────────
Unit tests for SMC 2.0 features, AutoAlert horizon classification,
and volume profile order flow indicators.
"""

import numpy as np
import pandas as pd
from analysis.market_structure import analyze_market_structure
from analysis.volume_profile import analyze_volume_profile
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def test_auto_alert_horizon_and_no_chase_inferral():
    # 1. Positional inferral from Stage 1 to 2
    pos_alert = AutoAlert(
        alert_id="test-pos-01",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="EARLY_WARNING",
        symbol="TRENT",
        exchange="NSE",
        direction="BULLISH",
        headline="Stage 2 breakout",
        summary="Testing positional breakout",
        ltp=5000.0,
        trigger_level=5000.0,
        target_level=6000.0,
        stop_loss=4600.0,
    )
    assert pos_alert.time_horizon == "POSITIONAL"
    assert pos_alert.no_chase_boundary == 5060.0  # 5000 * 1.012

    # 2. Intraday inferral from Gamma Blast
    intraday_alert = AutoAlert(
        alert_id="test-intra-01",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Gamma Blast",
        summary="Intraday options gamma",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25150.0,
        stop_loss=24920.0,
        time_horizon="INTRADAY",
    )
    assert intraday_alert.time_horizon == "INTRADAY"

    # 3. Short Swing inferral from Bearish Setup
    short_alert = AutoAlert(
        alert_id="test-short-01",
        alert_type="CIRCUIT_WARNING",
        stage="EARLY_WARNING",
        symbol="XYZ",
        exchange="NSE",
        direction="BEARISH",
        headline="Circuit warning",
        summary="Circuit test",
        ltp=100.0,
        trigger_level=100.0,
        target_level=90.0,
        stop_loss=105.0,
    )
    assert short_alert.time_horizon == "SWING_SHORT"
    assert short_alert.no_chase_boundary == 98.8  # 100 * 0.988 for bearish


def test_smc_2_order_block_and_dealing_range():
    # Create an uptrending price structure
    n = 60
    closes = np.linspace(100, 160, n)
    highs = closes + 2.0
    lows = closes - 2.0
    volumes = np.random.uniform(50000, 100000, n)

    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-07-01", periods=n, freq="D"),
            "open": closes - 0.5,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )

    report = analyze_market_structure("TEST_SYM", df=df)
    assert report is not None
    assert report.dealing_range_equilibrium > 0
    assert report.discount_zone_low < report.discount_zone_high
    assert isinstance(report.in_discount_zone, bool)

    # Check unmitigated order blocks have quality tier
    for ob in report.active_demand_zones:
        assert ob.is_unmitigated is True
        assert ob.quality_tier in ("TIER_1_PRIME", "TIER_2_VALID", "TIER_3_WEAK")


def test_volume_profile_cvd_and_delivery_spike():
    n = 40
    closes = np.linspace(200, 250, n)
    highs = closes + 3.0
    lows = closes - 1.0  # Strong closes near high -> positive delta
    volumes = np.random.uniform(10000, 20000, n)
    delivery_pcts = np.full(n, 35.0)
    delivery_pcts[-1] = 65.0  # Spike on the latest bar!

    df = pd.DataFrame(
        {
            "high": highs,
            "low": lows,
            "close": closes,
            "open": closes - 1.0,
            "volume": volumes,
            "delivery_pct": delivery_pcts,
        }
    )

    report = analyze_volume_profile("TEST_STOCK", df=df)
    assert report.poc_price > 0
    assert report.delivery_pct == 65.0
    assert report.delivery_spike is True
    assert report.cvd_divergence in ("BULLISH_ABSORPTION", "BEARISH_EXHAUSTION", "NEUTRAL")


def test_auto_alert_engine_get_alerts_with_horizon_filter(monkeypatch):
    engine = AutoAlertEngine()
    monkeypatch.setattr(engine, "_load", lambda: None)
    a1 = AutoAlert(
        alert_id="h-intra-01",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Gamma Blast",
        summary="Intraday scalp",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25100.0,
        stop_loss=24950.0,
        time_horizon="INTRADAY",
    )
    a2 = AutoAlert(
        alert_id="h-pos-02",
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage="EARLY_WARNING",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Stage 2",
        summary="Positional accumulation",
        ltp=3000.0,
        trigger_level=3000.0,
        target_level=3600.0,
        stop_loss=2800.0,
        time_horizon="POSITIONAL",
    )

    with engine._lock:
        engine._alerts = [a1, a2]

    # Filter for INTRADAY
    intra_res = engine.get_alerts(horizon="INTRADAY")
    assert len(intra_res) == 1
    assert intra_res[0].alert_id == "h-intra-01"

    # Filter for POSITIONAL
    pos_res = engine.get_alerts(horizon="POSITIONAL")
    assert len(pos_res) == 1
    assert pos_res[0].alert_id == "h-pos-02"
