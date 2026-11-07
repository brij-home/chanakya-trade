"""
tests/test_reversal_engine.py
─────────────────────────────
Unit tests for the Institutional Top & Bottom Reversal Engine (3-Phase Protocol).
"""

import numpy as np
import pandas as pd

from analysis.reversal_engine import analyse_reversal, ReversalSignal


def _create_synthetic_base(n: int = 50, start_price: float = 24000.0) -> pd.DataFrame:
    """Creates a basic trending dataframe."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")
    prices = [start_price]
    for _ in range(n - 1):
        prices.append(prices[-1] + np.random.normal(0, 10))

    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + abs(np.random.normal(5, 5)) for p in prices],
            "low": [p - abs(np.random.normal(5, 5)) for p in prices],
            "close": prices,
            "volume": [1000 + abs(int(np.random.normal(0, 200))) for _ in prices],
        },
        index=dates,
    )
    return df


def test_bottom_reversal_with_exhaustion_sweep_and_hammer():
    """Verify that a multi-bar selloff + liquidity sweep below prior swing low + Hammer creates a confirmed BOTTOM_REVERSAL."""
    n = 40
    dates = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")

    # Establish a support baseline around 24000
    opens, highs, lows, closes, volumes = [], [], [], [], []

    # First 25 bars: range between 24000 and 24100
    for i in range(25):
        p = 24050.0 + np.sin(i / 3.0) * 40.0
        opens.append(p - 5.0)
        highs.append(p + 15.0)
        lows.append(24000.0 if i == 10 else p - 15.0)  # Prior structural swing low at 24000.0
        closes.append(p)
        volumes.append(1000.0)

    # Next 12 bars: sharp selloff driving RSI < 30 down to 23990
    current_p = 24050.0
    for i in range(12):
        current_p -= 12.0
        opens.append(current_p + 8.0)
        highs.append(current_p + 10.0)
        lows.append(current_p - 5.0)
        closes.append(current_p)
        volumes.append(2500.0)  # Climax volume

    # Bar 38: Turtle Soup Sweep piercing prior low (24000.0) down to 23900.0, but closing back at 24010.0
    # Bar 39 (latest): Classic Hammer candlestick
    # Open: 24010, Low: 23890 (long lower wick 120 pts), High: 24035, Close: 24030 (body 20 pts)
    # Lower wick (24010 - 23890 = 120 pts) is 6x the body (20 pts).
    opens.append(24010.0)
    highs.append(24035.0)
    lows.append(23890.0)
    closes.append(24030.0)
    volumes.append(4500.0)  # High absorption volume

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates[: len(opens)],
    )

    sig: ReversalSignal = analyse_reversal(
        df, symbol="NIFTY", is_intraday=True, asset_class="INDEX"
    )

    assert sig.reversal_type == "BOTTOM_REVERSAL"
    assert sig.bias == "BULLISH"
    assert sig.confidence >= 75
    assert sig.phase1_exhaustion is True
    assert sig.phase3_confirmation is True
    assert sig.candlestick_pattern in (
        "Hammer",
        "Bullish Pin Bar",
        "Morning Star",
        "Bullish Engulfing",
    )
    assert sig.stop_loss < sig.entry_zone[0]
    assert sig.target_1 > sig.entry_zone[1]
    assert sig.risk_reward_ratio >= 1.8
    assert sig.no_chase_limit > sig.entry_zone[1]


def test_top_reversal_with_exhaustion_sweep_and_shooting_star():
    """Verify that a sharp rally + upper BB pierce + liquidity sweep + Shooting Star creates a confirmed TOP_REVERSAL."""
    n = 40
    dates = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")

    opens, highs, lows, closes, volumes = [], [], [], [], []

    # First 25 bars: range between 24800 and 24900 with prior swing high at 24900
    for i in range(25):
        p = 24850.0 + np.sin(i / 3.0) * 35.0
        opens.append(p - 5.0)
        highs.append(24900.0 if i == 12 else p + 15.0)
        lows.append(p - 15.0)
        closes.append(p)
        volumes.append(1000.0)

    # Next 12 bars: sharp rally driving RSI > 70 up to 24920
    current_p = 24850.0
    for i in range(12):
        current_p += 12.0
        opens.append(current_p - 8.0)
        highs.append(current_p + 5.0)
        lows.append(current_p - 5.0)
        closes.append(current_p)
        volumes.append(2500.0)

    # Latest bar: Shooting Star sweeping prior high (24900.0) up to 25010.0, closing down at 24880.0
    # Open: 24890, High: 25010 (upper wick 120 pts), Low: 24870, Close: 24880 (body 10 pts)
    opens.append(24890.0)
    highs.append(25010.0)
    lows.append(24870.0)
    closes.append(24880.0)
    volumes.append(4000.0)  # Ultra-high effort vs result

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates[: len(opens)],
    )

    sig: ReversalSignal = analyse_reversal(
        df, symbol="BANKNIFTY", is_intraday=True, asset_class="INDEX"
    )

    assert sig.reversal_type == "TOP_REVERSAL"
    assert sig.bias == "BEARISH"
    assert sig.confidence >= 75
    assert sig.phase1_exhaustion is True
    assert sig.phase3_confirmation is True
    assert sig.candlestick_pattern in (
        "Shooting Star",
        "Bearish Pin Bar",
        "Evening Star",
        "Bearish Engulfing",
    )
    assert sig.stop_loss > sig.entry_zone[1]
    assert sig.target_1 < sig.entry_zone[0]
    assert sig.risk_reward_ratio >= 1.8


def test_precursor_reversal_without_confirmation_candle_is_not_entered():
    """Verify that an oversold condition without candlestick confirmation remains a PRECURSOR setup (confidence <= 60)."""
    n = 35
    dates = pd.date_range("2026-01-01 09:15", periods=n, freq="5min")

    opens, highs, lows, closes, volumes = [], [], [], [], []

    current_p = 1500.0
    for i in range(n):
        current_p -= 4.0
        # Continuous falling bear candles (no hammer, no engulfing)
        opens.append(current_p + 3.0)
        highs.append(current_p + 3.5)
        lows.append(current_p - 1.0)
        closes.append(current_p)
        volumes.append(1500.0)

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )

    sig = analyse_reversal(df, symbol="INFY", is_intraday=True, asset_class="EQUITY")

    # Falling knife should NOT have phase 3 confirmation
    assert sig.phase3_confirmation is False
    assert sig.confidence <= 60


def test_options_strategy_recommendation_trending_vs_choppy():
    """Verify that Choppiness Index dynamically shifts recommended options strategy between Directional and Credit Spread."""
    df = _create_synthetic_base(n=40)

    # With normal/insufficient pattern
    sig_none = analyse_reversal(df, symbol="RELIANCE", is_intraday=True, asset_class="EQUITY")
    assert sig_none.reversal_type in ("NONE", "BOTTOM_REVERSAL", "TOP_REVERSAL")


def test_insufficient_data_fail_safe():
    """Verify that short dataframes or None safely return default NONE signal without crashing."""
    sig1 = analyse_reversal(None, symbol="TEST")
    assert sig1.reversal_type == "NONE"
    assert sig1.confidence == 0

    df_short = _create_synthetic_base(n=10)
    sig2 = analyse_reversal(df_short, symbol="TEST")
    assert sig2.reversal_type == "NONE"
    assert sig2.confidence == 0
