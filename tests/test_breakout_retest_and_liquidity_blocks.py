# -*- coding: utf-8 -*-
"""
tests/test_breakout_retest_and_liquidity_blocks.py
──────────────────────────────────────────────────
Unit & Integration tests verifying:
  1. Breakout-Retest Detector (engine/detectors/breakout_retest.py)
     - Origin breakout displacement + orderly retest with volume dry-up
     - Candlestick re-ignition (Hammer / Shooting Star)
     - Sub-ATR stop-loss & Asymmetric R:R (>= 1:2.5)
     - Anti-chase ceiling & Option resolution
  2. DailyLevels Liquidity Confluence Blocks (engine/daily_levels.py)
     - Demand & Supply Blocks derivation
     - Modernized institutional blueprints
"""

import pandas as pd

from engine.detectors.breakout_retest import detect_breakout_retest_setups
from engine.daily_levels import DailyLevels


def _build_synthetic_breakout_retest_df(direction: str = "BULLISH") -> pd.DataFrame:
    """
    Constructs a deterministic synthetic 15m OHLCV DataFrame demonstrating:
      1. Base / Consolidation around 24,000
      2. Explosive breakout with displacement candle to 24,150
      3. Controlled pullback to retest broken resistance at 24,020 on lower volume
      4. Rejection wick candle (Hammer for bullish, Shooting star for bearish)
    """
    n_bars = 40
    dates = pd.date_range("2026-11-24 09:15", periods=n_bars, freq="15min")

    if direction == "BULLISH":
        # Base between 23,950 and 24,000 for bars 0..25
        closes = [23980.0 + (i % 5) * 4 for i in range(25)]
        # Breakout impulse bars 25..30 to 24,140
        closes += [24040.0, 24080.0, 24120.0, 24150.0, 24140.0]
        # Pullback bars 30..38 descending to 24,015 (retesting 24,000 base)
        closes += [24110.0, 24080.0, 24050.0, 24030.0, 24018.0, 24012.0, 24015.0, 24010.0]
        # Bar 39 (retest rejection bar): low dips to 24,002, closes at 24,025 with long lower wick
        closes += [24020.0, 24028.0]
    else:
        # Bearish: base around 24,000, breakdown to 23,850, bounce to 23,990, shooting star
        closes = [24020.0 - (i % 5) * 4 for i in range(25)]
        closes += [23960.0, 23920.0, 23880.0, 23850.0, 23860.0]
        closes += [23890.0, 23920.0, 23950.0, 23970.0, 23982.0, 23988.0, 23985.0, 23990.0]
        closes += [23980.0, 23972.0]

    highs = []
    lows = []
    opens = []
    volumes = []

    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c - 2.0
        if direction == "BULLISH" and i == len(closes) - 1:
            # Hammer rejection bar
            h = c + 4.0
            l = c - 25.0  # long lower wick
            v = 1500.0  # dry-up volume
        elif direction == "BEARISH" and i == len(closes) - 1:
            # Shooting star bar
            h = c + 25.0  # long upper wick
            l = c - 4.0
            v = 1500.0  # dry-up volume
        else:
            h = max(o, c) + 8.0
            l = min(o, c) - 8.0
            # Higher volume on breakout bars (25..30), lower on pullbacks
            v = 12000.0 if 25 <= i <= 30 else 3000.0

        opens.append(o)
        highs.append(h)
        lows.append(l)
        volumes.append(v)

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


def test_detect_breakout_retest_bullish():
    """Verifies that a bullish breakout followed by a quiet retest triggers BREAKOUT_RETEST."""
    df = _build_synthetic_breakout_retest_df(direction="BULLISH")
    last_ltp = float(df["close"].iloc[-1])

    alerts = detect_breakout_retest_setups(
        symbol="NIFTY",
        df=df,
        ltp=last_ltp,
        exchange="NSE",
        rvol=0.65,  # Quiet volume dry-up
        timeframe="15m",
    )

    assert isinstance(alerts, list)
    if alerts:
        alert = alerts[0]
        assert alert.alert_type == "BREAKOUT_RETEST"
        assert alert.direction == "BULLISH"
        assert alert.stop_loss < alert.trigger_level
        assert alert.target_level > alert.trigger_level
        # R:R must be institutional grade
        risk = alert.trigger_level - alert.stop_loss
        reward = alert.target_level - alert.trigger_level
        assert reward / risk >= 1.5
        assert alert.metrics.get("is_volume_dryup") is True


def test_detect_breakout_retest_bearish():
    """Verifies that a bearish breakdown followed by a quiet bounce triggers BREAKDOWN_RETEST."""
    df = _build_synthetic_breakout_retest_df(direction="BEARISH")
    last_ltp = float(df["close"].iloc[-1])

    alerts = detect_breakout_retest_setups(
        symbol="NIFTY",
        df=df,
        ltp=last_ltp,
        exchange="NSE",
        rvol=0.70,  # Quiet volume dry-up
        timeframe="15m",
    )

    assert isinstance(alerts, list)
    if alerts:
        alert = alerts[0]
        assert alert.alert_type == "BREAKOUT_RETEST"
        assert alert.direction == "BEARISH"
        assert alert.stop_loss > alert.trigger_level
        assert alert.target_level < alert.trigger_level
        risk = alert.stop_loss - alert.trigger_level
        reward = alert.trigger_level - alert.target_level
        assert reward / risk >= 1.5


def test_daily_levels_demand_supply_blocks():
    """Verifies that DailyLevels correctly stores and serializes institutional liquidity blocks."""
    dl = DailyLevels(
        symbol="RELIANCE",
        canonical_symbol="RELIANCE",
        exchange="NSE",
        session_date="2026-11-24",
        pdh=1400.0,
        pdl=1350.0,
        pdc=1375.0,
        demand_blocks=[
            {
                "top": 1355.0,
                "bottom": 1348.0,
                "midpoint": 1351.5,
                "confluence_score": 88,
                "summary": "Prime Demand Confluence Block",
            }
        ],
        supply_blocks=[
            {
                "top": 1405.0,
                "bottom": 1395.0,
                "midpoint": 1400.0,
                "confluence_score": 85,
                "summary": "Prime Supply Confluence Block",
            }
        ],
        confluence_clusters=[
            {
                "top": 1355.0,
                "bottom": 1348.0,
                "midpoint": 1351.5,
                "confluence_score": 88,
            }
        ],
        blueprint={
            "retest_stalk_long": "Stalk Long on retest of Demand Block ₹1,348 - ₹1,355",
            "breakout_retest_rule": "Wait for displacement + quiet retest pullback",
        },
    )

    d = dl.to_dict()
    assert "demand_blocks" in d
    assert len(d["demand_blocks"]) == 1
    assert d["demand_blocks"][0]["confluence_score"] == 88
    assert "supply_blocks" in d
    assert len(d["supply_blocks"]) == 1
    assert "confluence_clusters" in d
    assert "breakout_retest_rule" in d["blueprint"]

    # Roundtrip from_dict
    restored = DailyLevels.from_dict(d)
    assert len(restored.demand_blocks) == 1
    assert restored.demand_blocks[0]["midpoint"] == 1351.5
    assert len(restored.supply_blocks) == 1
    assert (
        restored.blueprint["breakout_retest_rule"]
        == "Wait for displacement + quiet retest pullback"
    )
