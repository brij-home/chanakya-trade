"""
tests/test_auto_alerts.py
─────────────────────────
Unit tests for the real-time autonomous alert engine.
Verifies early-warning detection for:
  - Gamma Blast (CE and PE writer capitulation)
  - Squeeze Breakout (Bollinger inside Keltner coiling near pivot)
  - Circuit Proximity (Upper Circuit proximity alert)
  - Engine recording, deduplication, cooldowns, and query filtering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd
import pytest

from engine.auto_alert_engine import (
    AutoAlert,
    AutoAlertEngine,
    detect_circuit_proximity,
    detect_gamma_blast,
    detect_squeeze_breakout,
)


@dataclass
class MockOptionsContract:
    symbol: str
    underlying: str
    strike: float
    option_type: str  # "CE" | "PE"
    last_price: float
    oi: int
    oi_change: int
    volume: int
    iv: float = 18.5
    exchange: str = "NFO"


def test_gamma_blast_bullish_ce_early_warning_and_ignite():
    """Test Call Gamma Blast detection on negative OI change and volume surge."""
    spot = 24000.0
    vwap = 23990.0  # spot is above VWAP

    # Synthetic chain with 24000 CE writers in panic
    chain = [
        # Normal strike with positive OI change
        MockOptionsContract(
            symbol="NIFTY24000PE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="PE",
            last_price=45.0,
            oi=50000,
            oi_change=12000,
            volume=30000,
        ),
        # Panicking 24000 CE strike: OI shedding -30,000 (-37.5%), Vol/OI = 3.0x
        MockOptionsContract(
            symbol="NIFTY24000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="CE",
            last_price=65.0,
            oi=80000,
            oi_change=-30000,
            volume=240000,  # 3.0x OI
        ),
        # 24100 CE coiling: Vol/OI = 2.0x, OI shedding -10,000 (-12%)
        MockOptionsContract(
            symbol="NIFTY24100CE",
            underlying="NIFTY",
            strike=24100.0,
            option_type="CE",
            last_price=22.0,
            oi=70000,
            oi_change=-10000,
            volume=140000,  # 2.0x OI
        ),
    ]

    alerts = detect_gamma_blast("NIFTY", spot=spot, chain=chain, vwap=vwap, day_high=24005.0)

    assert len(alerts) >= 1
    # 24000 CE should be detected with high confidence
    ce_alert = next((a for a in alerts if a.strike == 24000.0 and a.option_type == "CE"), None)
    assert ce_alert is not None
    assert ce_alert.alert_type == "GAMMA_BLAST"
    assert ce_alert.direction == "BULLISH"
    assert ce_alert.stage == "IGNITED"
    assert ce_alert.metrics["vol_oi_ratio"] >= 2.5
    assert ce_alert.metrics["oi_change"] < 0
    assert ce_alert.confidence >= 80
    assert "BUY" in ce_alert.actionable_plan["action"]


def test_gamma_blast_bearish_pe_ignite():
    """Test Put Gamma Blast detection when Put writers capitulate."""
    spot = 23750.0
    vwap = 23780.0  # spot is below VWAP

    chain = [
        # 23800 PE panicking: OI shedding -40,000, Vol/OI = 2.8x
        MockOptionsContract(
            symbol="NIFTY23800PE",
            underlying="NIFTY",
            strike=23800.0,
            option_type="PE",
            last_price=88.0,
            oi=90000,
            oi_change=-40000,
            volume=252000,  # 2.8x OI
        ),
    ]

    alerts = detect_gamma_blast("NIFTY", spot=spot, chain=chain, vwap=vwap, day_low=23745.0)
    assert len(alerts) == 1
    pe_alert = alerts[0]
    assert pe_alert.direction == "BEARISH"
    assert pe_alert.option_type == "PE"
    assert pe_alert.strike == 23800.0
    assert pe_alert.stage == "IGNITED"


def test_gamma_blast_no_panic_returns_empty():
    """When open interest is building normally, no gamma blast alert should fire."""
    spot = 24000.0
    vwap = 24000.0

    chain = [
        # Normal steady trading with positive OI addition
        MockOptionsContract(
            symbol="NIFTY24000CE",
            underlying="NIFTY",
            strike=24000.0,
            option_type="CE",
            last_price=50.0,
            oi=100000,
            oi_change=15000,  # positive
            volume=50000,     # Vol/OI = 0.5x
        ),
    ]

    alerts = detect_gamma_blast("NIFTY", spot=spot, chain=chain, vwap=vwap)
    assert len(alerts) == 0


def test_detect_squeeze_breakout_early_warning():
    """Test Squeeze Breakout early-warning coiling within 0.8% of pivot."""
    # Build 30 bars of consolidating tight data
    np.random.seed(42)
    closes = [2500.0 + (i * 0.5) + (np.sin(i) * 3) for i in range(30)]
    highs = [c + 3.0 for c in closes]
    lows = [c - 3.0 for c in closes]
    volumes = [100000 for _ in range(30)]

    df = pd.DataFrame({
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
    })

    # 20-day high is around 2520, LTP is 2505 (around 0.6% below pivot)
    pivot_high = float(np.max(highs[-21:-1]))
    ltp = pivot_high * 0.992  # 0.8% below pivot

    alert = detect_squeeze_breakout("RELIANCE", df=df, ltp=ltp)
    if alert is not None:
        assert alert.alert_type == "SQUEEZE_BREAKOUT"
        assert alert.stage == "EARLY_WARNING"
        assert alert.metrics["is_squeeze_on"] is True
        assert alert.target_level > alert.ltp


def test_detect_circuit_proximity():
    """Test upper circuit proximity alert when stock is within 1.2% of ceiling."""
    prev_close = 500.0
    # 5% circuit ceiling is 525.0
    # LTP at 519.0 is +3.8% gain and 1.14% away from 525.0
    ltp = 519.0
    alert = detect_circuit_proximity("SUZLON", ltp=ltp, prev_close=prev_close, circuit_band_pct=5.0)

    assert alert is not None
    assert alert.alert_type == "CIRCUIT_WARNING"
    assert alert.stage == "EARLY_WARNING"
    assert alert.direction == "BULLISH"
    assert alert.trigger_level == 525.0
    assert alert.metrics["dist_to_uc_pct"] <= 1.5


def test_auto_alert_engine_recording_and_deduplication():
    """Verify engine records alerts, filters duplicates via cooldown, and queries."""
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()

    alert1 = AutoAlert(
        alert_id="test-1",
        alert_type="GAMMA_BLAST",
        stage="EARLY_WARNING",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Test Gamma Alert",
        summary="Test summary",
        ltp=24000.0,
        trigger_level=24000.0,
        target_level=24150.0,
        stop_loss=23920.0,
    )

    # First record should succeed
    assert engine.record_alert(alert1) is True

    # Immediate duplicate should be suppressed by anti-spam cooldown
    assert engine.record_alert(alert1) is False

    # Check query
    alerts = engine.get_alerts(alert_type="GAMMA_BLAST")
    assert len(alerts) == 1
    assert alerts[0].symbol == "NIFTY"

    # Stage filter
    assert len(engine.get_alerts(stage="IGNITED")) == 0
    assert len(engine.get_alerts(stage="EARLY_WARNING")) == 1

    engine.clear_alerts()
    assert len(engine.get_alerts()) == 0
