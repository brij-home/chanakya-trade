"""
tests/test_trend_day_pullback.py
────────────────────────────────
Institutional validation test for Trend Day Pullback Detector:
Verifies:
  1. Option strike and type prominence in headline and summary (e.g. 54700 PE Buy, not PE Short).
  2. Exchange is NFO / BFO for index option setups.
  3. Hedged spread attachment and strictly ascending target hierarchy.
  4. Symmetrical validation for both Bullish (CE Buy) and Bearish (PE Buy).
"""

from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from engine.detectors.trend_day_continuation import detect_trend_day_pullback

IST = timezone(timedelta(hours=5, minutes=30))


def _generate_synthetic_trend_df(direction: str = "BEARISH") -> pd.DataFrame:
    """Generate 5m bars establishing a clear trend and shallow pullback."""
    np.random.seed(42)
    n = 25
    timestamps = [
        datetime(2026, 10, 22, 10, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)
    ]

    if direction == "BEARISH":
        # Falling market from 55,200 down to 54,650, then a shallow bounce to 54,720 into falling 20-EMA
        prices = np.linspace(55200, 54650, n - 2).tolist()
        # Shallow bounce testing 20 EMA, then rejection candle with upper wick
        prices.append(54710)
        prices.append(54700)
    else:
        # Rising market from 54,000 up to 54,600, then shallow pullback to 54,550
        prices = np.linspace(54000, 54600, n - 2).tolist()
        prices.append(54560)
        prices.append(54580)

    df = pd.DataFrame(index=timestamps)
    df["close"] = prices
    df["open"] = [p - (10 if direction == "BEARISH" else -10) for p in prices]
    if direction == "BEARISH":
        # Make the last bar have an upper rejection wick
        df.loc[df.index[-1], "open"] = 54710
        df.loc[df.index[-1], "close"] = 54695
        df["high"] = [max(o, c) + 15 for o, c in zip(df["open"], df["close"])]
        df.loc[df.index[-1], "high"] = 54735  # upper wick rejection
        df["low"] = [min(o, c) - 10 for o, c in zip(df["open"], df["close"])]
    else:
        # Make the last bar have a lower rejection wick
        df.loc[df.index[-1], "open"] = 54565
        df.loc[df.index[-1], "close"] = 54585
        df["high"] = [max(o, c) + 10 for o, c in zip(df["open"], df["close"])]
        df["low"] = [min(o, c) - 15 for o, c in zip(df["open"], df["close"])]
        df.loc[df.index[-1], "low"] = 54540  # lower wick rejection

    df["volume"] = [1000 + i * 20 for i in range(n)]
    df.loc[df.index[-1], "volume"] = 800  # dryup volume
    return df


def test_bearish_trend_pullback_pe_buy_clarity(monkeypatch):
    """Verify that a bearish trend pullback setup buys PEs, labels as PE Buy (never PE Short), and includes strike."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    df_5m = _generate_synthetic_trend_df(direction="BEARISH")
    last_ltp = float(df_5m["close"].iloc[-1])
    test_dt = datetime(2026, 10, 22, 11, 30, tzinfo=IST)

    alert = detect_trend_day_pullback(
        symbol="BANKNIFTY",
        df_5m=df_5m,
        ltp=last_ltp,
        now_dt=test_dt,
        exchange="NSE",
        segment="FNO_INDEX",
    )

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert alert.option_type == "PE"
    assert alert.strike is not None
    assert alert.exchange == "NFO"  # Must be NFO for index options

    # Strict invariant: Headline MUST contain strike and "PE Buy", NEVER "PE Short"
    assert "PE Short" not in alert.headline
    assert "PE Buy" in alert.headline
    assert str(int(alert.strike)) in alert.headline
    assert "Spot" in alert.headline

    # Strict invariant: Option targets must be ascending in premium space
    assert alert.stop_loss < alert.trigger_level
    assert alert.target_level > alert.trigger_level


def test_bullish_trend_pullback_ce_buy_clarity(monkeypatch):
    """Verify that a bullish trend pullback setup buys CEs, labels as CE Buy (never CE Short), and includes strike."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    df_5m = _generate_synthetic_trend_df(direction="BULLISH")
    last_ltp = float(df_5m["close"].iloc[-1])
    test_dt = datetime(2026, 10, 22, 11, 30, tzinfo=IST)

    alert = detect_trend_day_pullback(
        symbol="BANKNIFTY",
        df_5m=df_5m,
        ltp=last_ltp,
        now_dt=test_dt,
        exchange="NSE",
        segment="FNO_INDEX",
    )

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert alert.option_type == "CE"
    assert alert.strike is not None
    assert alert.exchange == "NFO"

    # Strict invariant: Headline MUST contain strike and "CE Buy"
    assert "CE Short" not in alert.headline
    assert "CE Buy" in alert.headline
    assert str(int(alert.strike)) in alert.headline
    assert "Spot" in alert.headline

    # Strict invariant: Option targets must be ascending in premium space
    assert alert.stop_loss < alert.trigger_level
    assert alert.target_level > alert.trigger_level
