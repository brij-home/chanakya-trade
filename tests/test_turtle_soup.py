"""
tests/test_turtle_soup.py
─────────────────────────
Unit tests for the Turtle Soup / Liquidity Sweep Inversion detector.
Verifies identification of Bullish Spring (Bear Trap) and Bearish Upthrust (Bull Trap).
"""

from __future__ import annotations

from datetime import date
import pandas as pd
import numpy as np

from engine.detectors.turtle_soup import detect_turtle_soup_sweep


def _generate_synthetic_base(n_bars: int = 25, base_price: float = 1000.0) -> pd.DataFrame:
    """Generates a stable trading range dataframe."""
    np.random.seed(42)
    rows = []
    curr = base_price
    for i in range(n_bars):
        o = curr
        h = o + 4.0 + np.random.uniform(0, 3)
        l = o - 4.0 - np.random.uniform(0, 3)
        c = o + np.random.uniform(-2, 2)
        v = 10000.0 + np.random.uniform(0, 2000)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        curr = c
    return pd.DataFrame(rows)


def test_turtle_soup_bullish_spring():
    """Verify detection of a Bear Trap (Bullish Spring) at swing low."""
    df = _generate_synthetic_base(n_bars=22, base_price=1000.0)

    # Establish a clear swing low in the prior 20 bars
    prior_low = float(df["low"].iloc[:-2].min())

    # Create a spring candle on the last bar:
    # Pierces below prior_low by ~0.4%, but closes well back above it with a long lower wick
    spring_open = prior_low + 2.0
    spring_low = prior_low - (prior_low * 0.004)  # 0.4% sweep
    spring_close = prior_low + 3.0
    spring_high = spring_close + 1.0

    df.iloc[-1] = {
        "open": spring_open,
        "high": spring_high,
        "low": spring_low,
        "close": spring_close,
        "volume": 25000.0,
    }

    d = date(2026, 10, 3)
    alert = detect_turtle_soup_sweep("NSE:INFY", df=df, ltp=spring_close, session_date=d)

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert alert.alert_type == "TURTLE_SOUP_SWEEP"
    assert alert.stop_loss < spring_low
    assert alert.target_level > alert.trigger_level
    assert alert.actionable_plan is not None
    assert alert.actionable_plan["action"] in ("BUY", "BUY_CALL")
    assert alert.metrics["sweep_type"] == "BULLISH_SPRING"
    assert alert.alert_id.startswith("aa-turtle-soup-sweep-infy-spring-20261003")


def test_turtle_soup_bearish_upthrust():
    """Verify detection of a Bull Trap (Bearish Upthrust) at swing high."""
    df = _generate_synthetic_base(n_bars=22, base_price=2000.0)

    # Establish a clear swing high in the prior 20 bars
    prior_high = float(df["high"].iloc[:-2].max())

    # Create an upthrust candle on the last bar:
    # Pierces above prior_high by ~0.4%, but closes well back below it with a long upper wick
    upthrust_open = prior_high - 3.0
    upthrust_high = prior_high + (prior_high * 0.004)  # 0.4% sweep
    upthrust_close = prior_high - 4.0
    upthrust_low = upthrust_close - 1.0

    df.iloc[-1] = {
        "open": upthrust_open,
        "high": upthrust_high,
        "low": upthrust_low,
        "close": upthrust_close,
        "volume": 28000.0,
    }

    d = date(2026, 10, 3)
    alert = detect_turtle_soup_sweep("NSE:RELIANCE", df=df, ltp=upthrust_close, session_date=d)

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert alert.alert_type == "TURTLE_SOUP_SWEEP"
    assert alert.stop_loss > upthrust_high
    assert alert.target_level < alert.trigger_level
    assert alert.actionable_plan is not None
    assert alert.actionable_plan["action"] in ("SELL", "BUY_PUT")
    assert alert.metrics["sweep_type"] == "BEARISH_UPTHRUST"
    assert alert.alert_id.startswith("aa-turtle-soup-sweep-reliance-upthrust-20261003")


def test_turtle_soup_genuine_breakout_ignored():
    """Verify that a genuine expansive breakout with close above level does not trigger a false reversal."""
    df = _generate_synthetic_base(n_bars=22, base_price=1500.0)
    prior_high = float(df["high"].iloc[:-2].max())

    # Strong breakout candle closing near its high, well above prior_high
    df.iloc[-1] = {
        "open": prior_high - 1.0,
        "high": prior_high + 25.0,
        "low": prior_high - 2.0,
        "close": prior_high + 23.0,
        "volume": 40000.0,
    }

    alert = detect_turtle_soup_sweep("NSE:HDFCBANK", df=df, ltp=prior_high + 23.0)
    # Genuine breakout should NOT trigger a Turtle Soup reversal!
    assert alert is None
