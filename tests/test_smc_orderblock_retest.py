"""
tests/test_smc_orderblock_retest.py
───────────────────────────────────
Unit tests for institutional SMC Order Block Re-Test Detector.

Validates:
1. Demand Order Block re-test detection with sub-ATR stop-loss & >= 1.5R/3.0R targets.
2. Supply Order Block re-test detection with sub-ATR stop-loss & >= 1.5R/3.0R targets.
3. High RVOL (>1.8) trap suppression (filters capitulation / breakout liquidation).
4. Strict Invariant 17 deterministic alert ID conformity: aa-smc-ob-retest-{symbol}-{variant}-{date}.
5. BaseDetector protocol & detector_registry integration via DetectionContext.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd

from engine.alert_identity import generate_alert_id
from engine.detection_context import build_detection_context, detector_registry
from engine.detectors.smc_orderblock_retest import detect_smc_orderblock_retest


def _build_demand_ob_df() -> pd.DataFrame:
    """Builds synthetic daily OHLCV forming a validated Demand Order Block at 99.0-102.0."""
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(50)]
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(50):
        if i < 20:
            o, h, l, c, v = 100.0, 102.0, 98.0, 100.0, 10000
        elif i == 20:
            # Down candle before the energetic blast (Demand OB)
            o, h, l, c, v = 101.0, 102.0, 99.0, 99.5, 15000
        elif i == 21:
            # Energetic expansion up
            o, h, l, c, v = 100.0, 112.0, 100.0, 110.0, 45000
        elif i == 22:
            # Trend continuation
            o, h, l, c, v = 111.0, 125.0, 110.0, 124.0, 40000
        elif i == 23:
            # Swing High
            o, h, l, c, v = 125.0, 135.0, 124.0, 133.0, 30000
        else:
            # Controlled, low-volume pullback re-testing the 100-102 demand zone
            factor = (i - 23) / 27.0
            val = 133.0 - factor * (133.0 - 101.0)
            o, h, l, c, v = val + 0.5, val + 1.0, val - 0.5, val, 8000
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )


def _build_supply_ob_df() -> pd.DataFrame:
    """Builds synthetic daily OHLCV forming a validated Supply Order Block at 198.0-201.0."""
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(50)]
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(50):
        if i < 20:
            o, h, l, c, v = 200.0, 202.0, 198.0, 200.0, 10000
        elif i == 20:
            # Up candle before energetic sell-off (Supply OB)
            o, h, l, c, v = 199.0, 201.0, 198.0, 200.5, 15000
        elif i == 21:
            # Aggressive markdown
            o, h, l, c, v = 200.0, 200.0, 188.0, 190.0, 45000
        elif i == 22:
            # Second leg down
            o, h, l, c, v = 189.0, 190.0, 175.0, 176.0, 40000
        elif i == 23:
            # Swing Low
            o, h, l, c, v = 175.0, 176.0, 165.0, 167.0, 30000
        else:
            # Low-volume rally re-testing the 198-201 supply zone
            factor = (i - 23) / 27.0
            val = 167.0 + factor * (200.0 - 167.0)
            o, h, l, c, v = val - 0.5, val + 0.5, val - 1.0, val, 8000
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )


def test_smc_orderblock_bullish_retest():
    """Validates bullish Demand OB retest generates high-asymmetry alert."""
    df = _build_demand_ob_df()
    ltp = 101.0  # Inside 99.0-102.0 OB

    alerts = detect_smc_orderblock_retest(
        symbol="RELIANCE",
        df=df,
        ltp=ltp,
        exchange="NSE",
        rvol=1.1,
    )

    assert len(alerts) == 1
    alert = alerts[0]

    # Invariant 17: Deterministic session alert ID
    expected_id = generate_alert_id("RELIANCE", "SMC_OB_RETEST", variant="bull")
    assert alert.alert_id == expected_id

    # Core fields
    assert alert.symbol == "RELIANCE"
    assert alert.direction == "BULLISH"
    assert alert.stage == "EARLY_WARNING"
    assert alert.alert_type == "SMC_OB_RETEST"
    assert alert.stop_loss < alert.ltp
    assert alert.target_level > alert.ltp

    # Risk-to-Reward and institutional blueprint
    assert alert.metrics["rr_t1"] >= 1.5
    assert alert.metrics["rr_t2"] >= 3.0
    assert alert.metrics["ob_type"] == "DEMAND"

    # Actionable Blueprint
    plan = alert.actionable_plan
    assert plan["action"] == "BUY"
    assert "no_chase_rule" in plan
    assert "runner_target" in plan


def test_smc_orderblock_bearish_retest():
    """Validates bearish Supply OB retest generates high-asymmetry short alert."""
    df = _build_supply_ob_df()
    ltp = 199.5  # Inside 198.0-201.0 OB

    alerts = detect_smc_orderblock_retest(
        symbol="TATASTEEL",
        df=df,
        ltp=ltp,
        exchange="NSE",
        rvol=1.0,
    )

    assert len(alerts) == 1
    alert = alerts[0]

    expected_id = generate_alert_id("TATASTEEL", "SMC_OB_RETEST", variant="bear")
    assert alert.alert_id == expected_id

    assert alert.symbol == "TATASTEEL"
    assert alert.direction == "BEARISH"
    assert alert.stage == "EARLY_WARNING"
    assert alert.stop_loss > alert.ltp
    assert alert.target_level < alert.ltp
    assert alert.metrics["rr_t1"] >= 1.5
    assert alert.metrics["rr_t2"] >= 3.0
    assert alert.metrics["ob_type"] == "SUPPLY"
    assert alert.actionable_plan["action"] == "SELL_SHORT"


def test_smc_orderblock_rvol_trap_suppressed():
    """Ensures that price slamming into an OB on high RVOL (>1.8) is rejected as a trap/liquidation."""
    df = _build_demand_ob_df()
    ltp = 101.0

    # RVOL = 2.4 indicates heavy distribution / panic selling into the OB (not absorption)
    alerts = detect_smc_orderblock_retest(
        symbol="RELIANCE",
        df=df,
        ltp=ltp,
        exchange="NSE",
        rvol=2.4,
    )

    assert len(alerts) == 0, "High RVOL re-test must be suppressed to avoid liquidation traps"


def test_detection_context_smc_ob_adapter():
    """Validates the smc_ob_retest adapter registered with DetectionContext and detector_registry."""
    df = _build_demand_ob_df()
    ctx = build_detection_context(
        symbol="RELIANCE",
        ltp=101.0,
        exchange="NSE",
        segment="EQUITY",
        candles_daily=df,
        rvol=1.2,
    )

    detector = detector_registry.get("smc_ob_retest")
    assert detector is not None, "smc_ob_retest must be registered in detector_registry"

    result = detector.detect(ctx)
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].alert_type == "SMC_OB_RETEST"
    assert result[0].direction == "BULLISH"
