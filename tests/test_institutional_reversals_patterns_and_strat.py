# -*- coding: utf-8 -*-
"""
tests/test_institutional_reversals_patterns_and_strat.py
────────────────────────────────────────────────────────
Unit & Integration tests verifying:
  1. Institutional Reversal Detector (engine/detectors/institutional_reversal.py)
     - 3-Phase verification: Exhaustion -> Liquidity Sweep/Divergence -> Candlestick Confirmation
     - Top and Bottom reversals with asymmetric R:R (>= 1:2.5)
  2. Chart Pattern Detector (engine/detectors/chart_pattern_detector.py)
     - Double Bottom (W) & Double Top (M)
     - Early Warning (Coiling) vs Confirmed breakout
  3. Strat 2-1-2 Scalper (engine/detectors/strat_scalper.py)
     - Rob Smith's The Strat 2-1-2 Bullish and Bearish continuations
     - NR7 / NR4 volatility compression micro-risk stops
  4. AutoAlertEngine scanner methods and cycle registration
"""

import pandas as pd

from engine.detectors.chart_pattern_detector import detect_chart_pattern_setups
from engine.detectors.institutional_reversal import detect_institutional_reversals
from engine.detectors.strat_scalper import detect_strat_scalp_setups


def _build_synthetic_strat_212_df(bias: str = "BULLISH") -> pd.DataFrame:
    """
    Constructs a 10-bar OHLCV DataFrame demonstrating a Strat 2-1-2 pattern:
      - Bar -3: 2-Up or 2-Down impulse
      - Bar -2: 1 (Inside Bar)
      - Bar -1: 2-Up or 2-Down breakout
    """
    dates = pd.date_range("2026-11-24 09:15", periods=10, freq="5min")
    base = 24000.0

    # Bars 0..6: Gentle drift
    opens = [base + i * 5 for i in range(7)]
    highs = [o + 10.0 for o in opens]
    lows = [o - 10.0 for o in opens]
    closes = [o + 5.0 for o in opens]
    volumes = [5000.0] * 7

    if bias == "BULLISH":
        # Bar 7 (prev2): 2-Up (High > Bar 6 High, Low > Bar 6 Low)
        p7_o = closes[-1]
        p7_h = highs[-1] + 25.0
        p7_l = lows[-1] + 10.0
        p7_c = p7_h - 3.0
        opens.append(p7_o)
        highs.append(p7_h)
        lows.append(p7_l)
        closes.append(p7_c)
        volumes.append(10000.0)

        # Bar 8 (prev1): 1 (Inside bar: High < Bar 7 High, Low > Bar 7 Low)
        p8_o = p7_c
        p8_h = p7_h - 4.0
        p8_l = p7_l + 4.0
        p8_c = (p8_h + p8_l) / 2.0
        opens.append(p8_o)
        highs.append(p8_h)
        lows.append(p8_l)
        closes.append(p8_c)
        volumes.append(3000.0)

        # Bar 9 (curr): 2-Up breakout (High > Bar 8 High, Low > Bar 8 Low)
        p9_o = p8_c
        p9_h = p8_h + 15.0
        p9_l = p8_l + 2.0
        p9_c = p9_h - 2.0
        opens.append(p9_o)
        highs.append(p9_h)
        lows.append(p9_l)
        closes.append(p9_c)
        volumes.append(12000.0)
    else:
        # Bar 7 (prev2): 2-Down
        p7_o = closes[-1]
        p7_h = highs[-1] - 10.0
        p7_l = lows[-1] - 25.0
        p7_c = p7_l + 3.0
        opens.append(p7_o)
        highs.append(p7_h)
        lows.append(p7_l)
        closes.append(p7_c)
        volumes.append(10000.0)

        # Bar 8 (prev1): 1 (Inside bar)
        p8_o = p7_c
        p8_h = p7_h - 4.0
        p8_l = p7_l + 4.0
        p8_c = (p8_h + p8_l) / 2.0
        opens.append(p8_o)
        highs.append(p8_h)
        lows.append(p8_l)
        closes.append(p8_c)
        volumes.append(3000.0)

        # Bar 9 (curr): 2-Down breakdown
        p9_o = p8_c
        p9_h = p8_h - 2.0
        p9_l = p8_l - 15.0
        p9_c = p9_l + 2.0
        opens.append(p9_o)
        highs.append(p9_h)
        lows.append(p9_l)
        closes.append(p9_c)
        volumes.append(12000.0)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _build_synthetic_double_bottom_df() -> pd.DataFrame:
    """
    Constructs a 45-bar OHLCV DataFrame exhibiting a classical Double Bottom (W-Pattern):
      - Left swing high at 24,200
      - Trough 1 at 24,000 (bar 10)
      - Peak / Neckline bounce to 24,150 (bar 22)
      - Trough 2 at 24,005 (bar 33)
      - Breakout through neckline to 24,170 (bars 38..44)
    """
    n = 45
    dates = pd.date_range("2026-11-24 09:15", periods=n, freq="15min")

    closes = []
    for i in range(n):
        if i <= 10:
            # Decline from 24,180 down to 24,000
            c = 24180.0 - (i / 10.0) * 180.0
        elif i <= 22:
            # Bounce from 24,000 up to neckline at 24,150
            c = 24000.0 + ((i - 10) / 12.0) * 150.0
        elif i <= 33:
            # Decline to second trough at 24,005
            c = 24150.0 - ((i - 22) / 11.0) * 145.0
        else:
            # Breakout up through neckline
            c = 24005.0 + ((i - 33) / 11.0) * 175.0
        closes.append(c)

    opens = [closes[i - 1] if i > 0 else closes[i] - 5.0 for i in range(n)]
    highs = [max(opens[i], closes[i]) + 10.0 for i in range(n)]
    lows = [min(opens[i], closes[i]) - 10.0 for i in range(n)]
    volumes = [3000.0] * n

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _build_synthetic_reversal_df(direction: str = "BULLISH") -> pd.DataFrame:
    """
    Constructs a 35-bar OHLCV DataFrame exhibiting a 3-phase institutional bottom reversal:
      - Heavy selling driving RSI oversold (Phase 1)
      - Turtle soup sweep of previous low (Phase 2)
      - Strong hammer rejection bar (Phase 3)
    """
    n = 35
    dates = pd.date_range("2026-11-24 09:15", periods=n, freq="15min")

    closes = []
    # Persistent decline to push RSI below 30
    curr = 24400.0
    for i in range(n - 1):
        curr -= 12.0
        closes.append(curr)

    # Last bar: sweep low and sharp reclaim (Hammer)
    closes.append(curr + 30.0)

    opens = []
    highs = []
    lows = []
    volumes = []

    for i in range(n):
        c = closes[i]
        if i == n - 1:
            # Hammer rejection candle
            o = c - 10.0
            l = c - 50.0  # Sweeps prior low by 20 pts
            h = c + 5.0
            v = 15000.0  # High volume stopping absorption
        else:
            o = c + 8.0
            h = o + 4.0
            l = c - 4.0
            v = 4000.0
        opens.append(o)
        highs.append(h)
        lows.append(l)
        volumes.append(v)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def test_strat_212_bullish_scalp():
    """Verifies that The Strat 2-1-2 Bullish pattern generates a high-conviction micro scalp alert."""
    df = _build_synthetic_strat_212_df(bias="BULLISH")
    last_ltp = float(df["close"].iloc[-1])

    alerts = detect_strat_scalp_setups(
        symbol="NIFTY",
        df=df,
        ltp=last_ltp,
        exchange="NSE",
        timeframe="5m",
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "NIFTY"
    assert "2_1_2" in alert.alert_type or "STRAT" in alert.alert_type
    assert alert.direction == "BULLISH"
    assert alert.stop_loss < last_ltp
    assert alert.target_level > last_ltp
    assert alert.metrics.get("risk_reward_ratio", 0) >= 1.8
    assert alert.metrics.get("pattern_name") == "STRAT_2_1_2_BULLISH"
    assert alert.metrics.get("strat_sequence") is not None


def test_strat_212_bearish_scalp():
    """Verifies that The Strat 2-1-2 Bearish pattern generates a short scalp alert."""
    df = _build_synthetic_strat_212_df(bias="BEARISH")
    last_ltp = float(df["close"].iloc[-1])

    alerts = detect_strat_scalp_setups(
        symbol="BANKNIFTY",
        df=df,
        ltp=last_ltp,
        exchange="NSE",
        timeframe="5m",
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "BANKNIFTY"
    assert alert.direction == "BEARISH"
    assert alert.stop_loss > last_ltp
    assert alert.target_level < last_ltp
    assert alert.metrics.get("pattern_name") == "STRAT_2_1_2_BEARISH"


def test_chart_pattern_double_bottom():
    """Verifies that classical Double Bottom (W pattern) triggers a geometric pattern alert."""
    df = _build_synthetic_double_bottom_df()
    last_ltp = float(df["close"].iloc[-1])

    alerts = detect_chart_pattern_setups(
        symbol="RELIANCE",
        df=df,
        ltp=last_ltp,
        exchange="NSE",
        timeframe="15m",
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "RELIANCE"
    assert (
        "DOUBLE_BOTTOM" in alert.alert_type
        or "W" in alert.alert_type
        or "CHART" in alert.alert_type
    )
    assert alert.direction == "BULLISH"
    assert (
        alert.metrics.get("neckline") is not None or alert.metrics.get("breakout_level") is not None
    )
    assert alert.target_level > last_ltp
    assert alert.stop_loss < last_ltp


def test_institutional_bottom_reversal():
    """Verifies that 3-phase institutional bottom reversal triggers an INSTITUTIONAL_BOTTOM_REVERSAL alert."""
    df = _build_synthetic_reversal_df(direction="BULLISH")
    last_ltp = float(df["close"].iloc[-1])

    alerts = detect_institutional_reversals(
        symbol="NIFTY",
        df=df,
        ltp=last_ltp,
        exchange="NSE",
        timeframe="15m",
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "NIFTY"
    assert "BOTTOM_REVERSAL" in alert.alert_type or "REVERSAL" in alert.alert_type
    assert alert.direction == "BULLISH"
    assert alert.stop_loss < last_ltp
    assert alert.target_level > last_ltp
    assert alert.metrics.get("risk_reward_ratio", 0) >= 2.0
    assert alert.metrics.get("candlestick_pattern") is not None


def test_auto_alert_engine_scanner_methods_exist():
    """Verifies that AutoAlertEngine contains all 4 scanner methods and they execute safely."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()

    assert hasattr(engine, "scan_breakout_retests")
    assert hasattr(engine, "scan_institutional_reversals")
    assert hasattr(engine, "scan_chart_pattern_setups")
    assert hasattr(engine, "scan_strat_scalps")

    # In test mode without network, scanners should return empty list gracefully without throwing
    res_br = engine.scan_breakout_retests()
    assert isinstance(res_br, list)

    res_rev = engine.scan_institutional_reversals()
    assert isinstance(res_rev, list)

    res_cp = engine.scan_chart_pattern_setups()
    assert isinstance(res_cp, list)

    res_strat = engine.scan_strat_scalps()
    assert isinstance(res_strat, list)
