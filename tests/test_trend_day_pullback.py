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


def test_single_stock_equity_trend_pullback_asymmetry(monkeypatch):
    """Verify single-stock equity pullback captures clean structural pivot SL and asymmetric R:R >= 1:3.5."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    np.random.seed(42)
    n = 25
    timestamps = [
        datetime(2026, 10, 26, 10, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)
    ]
    # Synthetic LAURUSLABS trend day: Open 1960 -> 2010 -> shallow dip to 2000 -> bounce to 2005
    prices = np.linspace(1960, 2015, n - 3).tolist()
    prices.append(2003.0)
    prices.append(2001.0)
    prices.append(2006.0)

    df = pd.DataFrame(index=timestamps)
    df["close"] = prices
    df["open"] = [p - 3.0 for p in prices]
    df["high"] = [p + 4.0 for p in prices]
    df["low"] = [p - 4.0 for p in prices]
    # Set the dip candle at index -2 and rejection candle at index -1
    df.loc[df.index[-2], "low"] = 1999.0
    df.loc[df.index[-1], "open"] = 2002.0
    df.loc[df.index[-1], "close"] = 2006.0
    df.loc[df.index[-1], "high"] = 2008.0
    df.loc[df.index[-1], "low"] = 2000.5  # Lower wick rejection

    df["volume"] = [25000 for _ in range(n)]
    df.loc[df.index[-1], "volume"] = 6000  # Dry-up volume on pullback

    alert = detect_trend_day_pullback(
        symbol="LAURUSLABS",
        df_5m=df,
        ltp=2006.0,
        now_dt=datetime(2026, 10, 26, 12, 15, tzinfo=IST),
        exchange="NSE",
        segment="FNO_STOCK",
    )

    assert alert is not None
    assert alert.symbol == "LAURUSLABS"
    assert alert.direction == "BULLISH"
    assert alert.alert_type == "TREND_DAY_PULLBACK"

    # Invariant: Structural Stop-Loss must be below the pullback pivot floor (2000)
    assert alert.stop_loss < alert.trigger_level
    assert alert.stop_loss <= 2000.5
    # Risk should be structural (~6-8 pts), not bloated
    risk = alert.trigger_level - alert.stop_loss
    assert 2.0 <= risk <= 12.0

    # Invariant: Asymmetric R:R must be >= 1:3.5 (Target 3 is 6.0R)
    assert alert.metrics.get("asymmetric_rr", 0.0) >= 3.5
    assert alert.r_multiple is None

    # Invariant: Alpha Quality Score must be present, quantified, and high
    aqs = alert.metrics.get("alpha_quality_score", 0.0)
    assert aqs >= 70.0
    assert alert.confidence >= 80


def test_bearish_single_stock_equity_trend_pullback_symmetry(monkeypatch):
    """Verify symmetrical bearish single-stock equity pullback captures clean structural ceiling SL and asymmetric R:R."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    np.random.seed(42)
    n = 25
    timestamps = [
        datetime(2026, 10, 26, 10, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)
    ]
    # Downward trending equity: Open 2050 -> 2000 -> shallow bounce to 2015 -> reject to 2010
    prices = np.linspace(2050, 1995, n - 3).tolist()
    prices.append(2010.0)
    prices.append(2015.0)
    prices.append(2008.0)

    df = pd.DataFrame(index=timestamps)
    df["close"] = prices
    df["open"] = [p + 3.0 for p in prices]
    df["high"] = [p + 4.0 for p in prices]
    df["low"] = [p - 4.0 for p in prices]
    # Set the bounce peak at index -2 and rejection candle at index -1
    df.loc[df.index[-2], "high"] = 2016.0
    df.loc[df.index[-1], "open"] = 2014.0
    df.loc[df.index[-1], "close"] = 2008.0
    df.loc[df.index[-1], "high"] = 2015.5  # Upper wick rejection
    df.loc[df.index[-1], "low"] = 2006.0

    df["volume"] = [25000 for _ in range(n)]
    df.loc[df.index[-1], "volume"] = 5500  # Dry-up volume on retracement

    alert = detect_trend_day_pullback(
        symbol="HINDALCO",
        df_5m=df,
        ltp=2008.0,
        now_dt=datetime(2026, 10, 26, 12, 15, tzinfo=IST),
        exchange="NSE",
        segment="FNO_STOCK",
    )

    assert alert is not None
    assert alert.symbol == "HINDALCO"
    assert alert.direction == "BEARISH"
    assert alert.alert_type == "TREND_DAY_PULLBACK"

    # Invariant: If option contract resolved (PE Buy), option premium targets ascend while underlying spot SL is above spot
    if alert.contract_symbol:
        assert alert.stop_loss < alert.trigger_level
        assert alert.target_level > alert.trigger_level
        assert alert.structural_spot_sl >= 2015.0
        assert alert.structural_spot_sl > alert.underlying_spot
    else:
        assert alert.stop_loss > alert.trigger_level
        assert alert.target_level < alert.trigger_level
        assert alert.stop_loss >= 2015.0

    # Invariant: Asymmetric R:R must be >= 1:3.5
    assert alert.metrics.get("asymmetric_rr", 0.0) >= 3.5
    assert alert.r_multiple is None

    # Invariant: Alpha Quality Score must be present and quantified
    aqs = alert.metrics.get("alpha_quality_score", 0.0)
    assert aqs >= 70.0


def test_morning_reversal_zone_and_midday_pullback_runway_exemption():
    """Verify that Trend Day Pullbacks are exempt from the breakout trap gates in 10:15-11:00 and 11:00-13:15."""
    import os
    from engine.session_runway import evaluate_session_runway

    orig_force = os.environ.get("FORCE_RUNWAY_CHECK")
    os.environ["FORCE_RUNWAY_CHECK"] = "1"
    try:
        # 1. 10:30 IST (Morning Reversal Zone): Breakout chase should be vetoed (< 2.2x floor)
        mrz_dt = datetime(2026, 10, 27, 10, 30, tzinfo=IST)
        res_breakout_mrz = evaluate_session_runway(
            symbol="NAUKRI",
            alert_type="MOMENTUM_BREAKOUT",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=1.30,
            now_dt=mrz_dt,
        )
        assert res_breakout_mrz.is_allowed is False
        assert "Morning Reversal Trap" in (res_breakout_mrz.veto_reason or "")

        # 2. 10:30 IST (Morning Reversal Zone): TREND_DAY_PULLBACK must PASS even with dry-up volume (e.g. 0.15x)
        res_pullback_mrz = evaluate_session_runway(
            symbol="NAUKRI",
            alert_type="TREND_DAY_PULLBACK",
            time_horizon="INTRADAY",
            segment="FNO_STOCK",
            rvol=0.15,
            now_dt=mrz_dt,
        )
        assert res_pullback_mrz.is_allowed is True, (
            f"TREND_DAY_PULLBACK in Morning Reversal Zone unexpectedly vetoed: {res_pullback_mrz.veto_reason}"
        )

        # 3. 11:48 IST (Midday Compression): SENSEX index pullback must PASS even with 0.20x dry-up volume
        midday_dt = datetime(2026, 10, 27, 11, 48, tzinfo=IST)
        res_sensex_midday = evaluate_session_runway(
            symbol="SENSEX",
            alert_type="TREND_DAY_PULLBACK",
            time_horizon="INTRADAY",
            segment="FNO_INDEX",
            rvol=0.20,
            now_dt=midday_dt,
        )
        assert res_sensex_midday.is_allowed is True, (
            f"SENSEX index pullback in Midday Compression unexpectedly vetoed: {res_sensex_midday.veto_reason}"
        )
    finally:
        if orig_force is not None:
            os.environ["FORCE_RUNWAY_CHECK"] = orig_force
        else:
            del os.environ["FORCE_RUNWAY_CHECK"]


def test_trend_day_pullback_index_regime_gate(monkeypatch):
    """Verifies that counter-trend pullbacks are suppressed when benchmark index trades counter to setup."""
    from brokers.base import Quote
    import market.quotes

    df_bull = _generate_synthetic_trend_df("BULLISH")
    ltp_bull = float(df_bull["close"].iloc[-1])
    dt = df_bull.index[-1]

    # Case 1: Stock is Bullish, but NIFTY 50 is below VWAP (bearish market)
    monkeypatch.setattr(
        market.quotes,
        "get_quote",
        lambda sym: {
            "NSE:NIFTY 50": Quote(symbol="NSE:NIFTY 50", last_price=24200.0, vwap=24350.0)
        },
    )
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("CHANAKYA_TESTING", "0")

    alert = detect_trend_day_pullback(
        "RELIANCE", df_bull, ltp=ltp_bull, now_dt=dt, segment="EQUITY"
    )
    assert alert is None, "Bullish continuation should be suppressed when NIFTY 50 is below VWAP"

    # Case 2: Stock is Bullish, and NIFTY 50 is above VWAP (bullish market)
    monkeypatch.setattr(
        market.quotes,
        "get_quote",
        lambda sym: {
            "NSE:NIFTY 50": Quote(symbol="NSE:NIFTY 50", last_price=24400.0, vwap=24350.0)
        },
    )
    alert = detect_trend_day_pullback(
        "RELIANCE", df_bull, ltp=ltp_bull, now_dt=dt, segment="EQUITY"
    )
    assert alert is not None, "Bullish continuation should trigger when NIFTY 50 is above VWAP"
    assert alert.direction == "BULLISH"
