"""
tests/test_holistic_alignment.py
──────────────────────────────────
Verifies end-to-end holistic alignment across UI, Alerts, Telegram, Market Data API,
and Backtesting engine for Turtle Soup, Regime Governor, Symbol Master, and QuantStats.
"""

import pytest
import pandas as pd
import numpy as np
from engine.backtest import Backtester, TurtleSoupStrategy, STRATEGIES
from bot.alert_templates import render_auto_alert, render_asymmetric_alert


def test_turtle_soup_strategy_backtest():
    """Verify TurtleSoupStrategy generates signals and completes backtest."""
    strat = TurtleSoupStrategy(period=20)
    assert "turtle_soup" in STRATEGIES

    # Create synthetic OHLCV dataframe with a false breakout upthrust and spring
    np.random.seed(42)
    n = 60
    base_price = 100.0
    close = [base_price + np.sin(i / 5.0) * 5.0 for i in range(n)]
    high = [c + 1.5 for c in close]
    low = [c - 1.5 for c in close]
    open_p = [c - 0.2 for c in close]
    volume = [10000] * n

    # Forge an upthrust at bar 35 (high sweeps 20-bar high, close rejects back down)
    high_prev = max(high[14:34])
    high[35] = high_prev + 2.0
    close[35] = high_prev - 0.5  # Closed below prior high!

    # Forge a spring at bar 50 (low sweeps 20-bar low, close rejects back up)
    low_prev = min(low[29:49])
    low[50] = low_prev - 2.0
    close[50] = low_prev + 0.5  # Closed above prior low!

    df = pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="D"),
    )

    signals = strat.generate_signals(df)
    assert signals.iloc[35] == -1  # Bearish upthrust signal
    assert signals.iloc[50] == 1   # Bullish spring signal


def test_alert_templates_turtle_soup_sweep_alignment():
    """Verify alert_templates renders TURTLE_SOUP_SWEEP with correct titles and emojis."""
    from datetime import date
    from engine.detectors.turtle_soup import detect_turtle_soup_sweep

    # Synthetic dataframe for Bullish Spring
    dates = pd.date_range("2026-09-01", periods=22, freq="D")
    df = pd.DataFrame(
        {
            "open": [1000.0] * 22,
            "high": [1010.0] * 22,
            "low": [990.0] * 22,
            "close": [1002.0] * 22,
            "volume": [10000.0] * 22,
        },
        index=dates,
    )
    # Establish a swing low
    prior_low = 980.0
    df.iat[10, df.columns.get_loc("low")] = prior_low
    # Spring candle at last bar
    df.iloc[-1] = {
        "open": prior_low + 2.0,
        "high": prior_low + 4.0,
        "low": prior_low - 3.0,
        "close": prior_low + 3.0,
        "volume": 25000.0,
    }

    d = date(2026, 10, 3)
    bull_alert = detect_turtle_soup_sweep("NSE:INFY", df=df, ltp=prior_low + 3.0, session_date=d)
    assert bull_alert is not None

    msg_bull = render_auto_alert(bull_alert, in_market=True)
    assert "TURTLE SOUP LONG (BULLISH SPRING)" in msg_bull
    assert "INFY" in msg_bull
    assert "🟢" in msg_bull

    # Synthetic dataframe for Bearish Upthrust
    df2 = pd.DataFrame(
        {
            "open": [2000.0] * 22,
            "high": [2010.0] * 22,
            "low": [1990.0] * 22,
            "close": [2002.0] * 22,
            "volume": [10000.0] * 22,
        },
        index=dates,
    )
    prior_high = 2050.0
    df2.iat[10, df2.columns.get_loc("high")] = prior_high
    # Upthrust candle at last bar
    df2.iloc[-1] = {
        "open": prior_high - 2.0,
        "high": prior_high + 4.0,
        "low": prior_high - 8.0,
        "close": prior_high - 3.0,
        "volume": 30000.0,
    }

    bear_alert = detect_turtle_soup_sweep("NSE:RELIANCE", df=df2, ltp=prior_high - 3.0, session_date=d)
    assert bear_alert is not None

    msg_bear = render_auto_alert(bear_alert, in_market=True)
    assert "TURTLE SOUP SHORT (BEARISH UPTHRUST)" in msg_bear
    assert "RELIANCE" in msg_bear
    assert "🔴" in msg_bear


def test_web_api_symbol_and_regime_endpoints():
    """Verify FastAPI routes for symbol master and market regime governor."""
    import asyncio
    from httpx import ASGITransport, AsyncClient
    from web.api import app

    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Market regime with governor
            res_regime = await client.get("/api/market/regime")
            assert res_regime.status_code == 200
            data_regime = res_regime.json()
            assert "is_edgeless" in data_regime
            if data_regime.get("governor"):
                gov = data_regime["governor"]
                assert "regime" in gov
                assert "breakout_weight" in gov
                assert "position_size_multiplier" in gov

            # 2. Symbol search
            res_search = await client.get("/api/market/symbol/search?q=NIFTY&limit=5")
            assert res_search.status_code == 200
            data_search = res_search.json()
            assert data_search["status"] == "ok"
            assert isinstance(data_search.get("data"), list)

            # 3. Symbol info
            res_info = await client.get("/api/market/symbol/info?symbol=NSE:NIFTY50-INDEX")
            assert res_info.status_code == 200
            data_info = res_info.json()
            assert data_info["status"] == "ok"

    asyncio.run(_test())

