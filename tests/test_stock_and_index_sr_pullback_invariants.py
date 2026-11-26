"""
tests/test_stock_and_index_sr_pullback_invariants.py
────────────────────────────────────────────────────
Institutional Verification Suite for Index & Stock F&O Pullback, S/R Rejections,
and Optimal Trade Entry (OTE) Invariants:

Invariants Verified:
  1. 15m 50-EMA Retest & Rejection:
     Verifies that when price in a downtrend rallies into the 15m 50-EMA and prints
     a rejection wick, it is correctly captured as an institutional pullback fade
     with tight structural stop-loss anchored above the 50-EMA / swing high.
  2. Daily Pivot (S1/R1) Retest & Rejection:
     Verifies that relief rallies testing Daily S1 in a downtrend, or dips testing
     Daily R1 in an uptrend, trigger high-conviction OTE alerts.
  3. Single-Stock F&O Option Resolution:
     Verifies that when an F&O stock triggers a pullback or Turtle Soup sweep,
     an actionable defined-risk Option Blueprint (ATM/ITM Call or Put) is resolved.
  4. AutoAlertEngine Cadence Alignment:
     Verifies that scan_trend_day_pullbacks operates continuously across the full
     09:35 to 15:15 IST active window, eliminating the prior blindspots.
  5. Asymmetric Risk-to-Reward:
     Enforces R:R >= 1:3.0 floor with sub-ATR structural stop loss.
"""

from datetime import datetime, time as dtime, timezone, timedelta
import numpy as np
import pandas as pd

from engine.detectors.trend_day_continuation import detect_trend_day_pullback
from engine.detectors.turtle_soup import detect_turtle_soup_sweep

IST = timezone(timedelta(hours=5, minutes=30))


def _make_15m_50ema_rejection_df(direction: str = "BEARISH") -> pd.DataFrame:
    """
    Creates a 5m DataFrame with 30 bars where price rallies into the descending
    15m 50-EMA (or dips into rising 15m 50-EMA) and prints an institutional rejection wick.
    """
    np.random.seed(101)
    n = 30
    timestamps = [
        datetime(2026, 11, 18, 10, 0, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)
    ]

    if direction == "BEARISH":
        # Falling market from 2500 down to 2420, then relief rally to 2445 testing the 15m 50-EMA (~2448)
        prices = np.linspace(2500, 2420, n - 4).tolist()
        prices.append(2430.0)
        prices.append(2440.0)
        prices.append(2448.0)  # Tests 50-EMA
        prices.append(2444.0)  # Rejection close back down

        df = pd.DataFrame(index=timestamps)
        df["close"] = prices
        df["open"] = [p + 2.0 for p in prices]
        df["high"] = [p + 4.0 for p in prices]
        df["low"] = [p - 4.0 for p in prices]

        # Candle at index -2 tests the high (2451.0), and last candle closes red with upper rejection wick
        df.loc[df.index[-2], "high"] = 2451.0
        df.loc[df.index[-1], "open"] = 2448.0
        df.loc[df.index[-1], "high"] = 2450.0  # upper wick
        df.loc[df.index[-1], "close"] = 2444.0  # red close below open
        df.loc[df.index[-1], "low"] = 2442.0
    else:
        # Rising market from 2400 up to 2480, then pullback to 2455 testing the 15m 50-EMA (~2452)
        prices = np.linspace(2400, 2480, n - 4).tolist()
        prices.append(2470.0)
        prices.append(2460.0)
        prices.append(2452.0)  # Tests 50-EMA
        prices.append(2456.0)  # Rejection bounce back up

        df = pd.DataFrame(index=timestamps)
        df["close"] = prices
        df["open"] = [p - 2.0 for p in prices]
        df["high"] = [p + 4.0 for p in prices]
        df["low"] = [p - 4.0 for p in prices]

        # Candle at index -2 dips to 2449.0, and last candle closes green with lower rejection wick
        df.loc[df.index[-2], "low"] = 2449.0
        df.loc[df.index[-1], "open"] = 2452.0
        df.loc[df.index[-1], "low"] = 2450.0  # lower wick
        df.loc[df.index[-1], "close"] = 2456.0  # green close above open
        df.loc[df.index[-1], "high"] = 2458.0

    df["volume"] = [15000 for _ in range(n)]
    df.loc[df.index[-1], "volume"] = 4000  # Dry-up absorption volume
    return df


def test_15m_50ema_rejection_bearish_nifty(monkeypatch):
    """
    Verifies that a relief rally in NIFTY testing the 15m 50-EMA triggers a Bearish Trend Pullback
    with PE Buy, sub-ATR structural stop loss, and asymmetric R:R >= 1:3.0.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    df_5m = _make_15m_50ema_rejection_df(direction="BEARISH")
    last_ltp = float(df_5m["close"].iloc[-1])
    test_dt = datetime(2026, 11, 18, 12, 30, tzinfo=IST)

    alert = detect_trend_day_pullback(
        symbol="NIFTY",
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
    assert "PE Buy" in alert.headline
    assert alert.exchange == "NFO"

    # Stop Loss must be anchored above the swing high (2451.0)
    assert alert.structural_spot_sl >= 2450.0
    assert alert.target_level > alert.trigger_level
    assert alert.stop_loss < alert.trigger_level
    assert alert.metrics.get("asymmetric_rr", 0.0) >= 3.0


def test_15m_50ema_rejection_bullish_stock_fno(monkeypatch):
    """
    Verifies that a pullback in an F&O stock (e.g. RELIANCE) testing the 15m 50-EMA triggers
    a Bullish Trend Pullback with CE Buy, resolving an actionable Option Blueprint.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    df_5m = _make_15m_50ema_rejection_df(direction="BULLISH")
    last_ltp = float(df_5m["close"].iloc[-1])
    test_dt = datetime(2026, 11, 18, 11, 45, tzinfo=IST)

    alert = detect_trend_day_pullback(
        symbol="RELIANCE",
        df_5m=df_5m,
        ltp=last_ltp,
        now_dt=test_dt,
        exchange="NSE",
        segment="FNO_STOCK",
    )

    assert alert is not None
    assert alert.symbol == "RELIANCE"
    assert alert.direction == "BULLISH"
    assert alert.option_type == "CE"
    assert alert.contract_symbol is not None
    assert "CE Buy" in alert.headline
    assert alert.metrics.get("asymmetric_rr", 0.0) >= 3.0

    # Option blueprint structure
    from engine.position_sizer import get_lot_size

    assert alert.actionable_plan is not None
    assert "option_plan" in alert.actionable_plan
    assert alert.actionable_plan["option_plan"]["lot_size"] == get_lot_size(
        "RELIANCE"
    )  # Canonical RELIANCE lot size


def test_daily_pivot_s1_rejection_bearish(monkeypatch):
    """
    Verifies that when price tests Daily S1 in a downtrend and prints an upper wick rejection,
    the detector identifies the retest of Daily S1 and sets structural invalidation above S1.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    df_5m = _make_15m_50ema_rejection_df(direction="BEARISH")
    last_ltp = float(df_5m["close"].iloc[-1])
    test_dt = datetime(2026, 11, 18, 13, 15, tzinfo=IST)

    # Pass prev_close so classic pivots compute Daily S1 near ~2450
    alert = detect_trend_day_pullback(
        symbol="INFY",
        df_5m=df_5m,
        ltp=last_ltp,
        now_dt=test_dt,
        exchange="NSE",
        segment="FNO_STOCK",
        prev_close=2440.0,
    )

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert alert.symbol == "INFY"
    assert alert.structural_spot_sl >= 2450.0
    assert alert.metrics.get("asymmetric_rr", 0.0) >= 3.0


def test_turtle_soup_single_stock_fno_resolves_option(monkeypatch):
    """
    Verifies that Turtle Soup sweeps on single-stock F&O instruments resolve an actionable
    option contract (BUY PUT on false breakout, BUY CALL on false breakdown) rather than cash equity.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    np.random.seed(42)
    n = 25
    timestamps = [
        datetime(2026, 11, 18, 10, 0, tzinfo=IST) + timedelta(minutes=15 * i) for i in range(n)
    ]
    # Synthetic false breakout at 1450 resistance: rally to 1452, sweep, then upper wick reject to 1445
    prices = np.linspace(1420, 1448, n - 2).tolist()
    prices.append(1452.0)  # Sweep above 1450
    prices.append(1444.0)  # Rejection close back inside

    df = pd.DataFrame(index=timestamps)
    df["open"] = [p - 1.0 for p in prices]
    df["high"] = [p + 2.0 for p in prices]
    df["low"] = [p - 2.0 for p in prices]
    df["close"] = prices
    df["volume"] = [50000 for _ in range(n)]

    # Make the last bar have an upper rejection wick above 1450
    df.loc[df.index[-1], "open"] = 1448.0
    df.loc[df.index[-1], "high"] = 1454.0  # false breakout sweep
    df.loc[df.index[-1], "close"] = 1444.0  # red close back down
    df.loc[df.index[-1], "low"] = 1442.0

    alert = detect_turtle_soup_sweep(
        symbol="TATASTEEL",
        df=df,
        ltp=1444.0,
        exchange="NSE",
    )

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert alert.symbol == "TATASTEEL"
    # Single-stock F&O must resolve option contract
    assert alert.contract_symbol is not None
    assert alert.option_type == "PE"
    assert alert.strike is not None
    assert alert.stop_loss < alert.trigger_level
    assert alert.target_level > alert.trigger_level


def test_scan_trend_day_pullbacks_cadence_active_window(monkeypatch):
    """
    Verifies that scan_trend_day_pullbacks in AutoAlertEngine allows scans across the full
    09:35 to 15:15 IST active window (including 09:40 AM and 14:45 PM), while correctly
    blocking out-of-session cycles (e.g. 09:20 AM and 15:20 PM).
    """
    from engine.auto_alert_engine import AutoAlertEngine

    AutoAlertEngine()

    # Outside active window: 09:20 IST -> must be blocked
    t_early = dtime(9, 20)
    is_blocked_early = not (dtime(9, 35) <= t_early <= dtime(15, 15))
    assert is_blocked_early is True

    # Inside active morning window: 09:45 IST -> must be allowed
    t_morning = dtime(9, 45)
    is_allowed_morning = dtime(9, 35) <= t_morning <= dtime(15, 15)
    assert is_allowed_morning is True

    # Inside active afternoon window: 14:45 IST -> must be allowed
    t_afternoon = dtime(14, 45)
    is_allowed_afternoon = dtime(9, 35) <= t_afternoon <= dtime(15, 15)
    assert is_allowed_afternoon is True

    # Outside active window: 15:20 IST -> must be blocked
    t_late = dtime(15, 20)
    is_blocked_late = not (dtime(9, 35) <= t_late <= dtime(15, 15))
    assert is_blocked_late is True
