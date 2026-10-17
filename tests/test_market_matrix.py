"""
tests/test_market_matrix.py
───────────────────────────
Institutional Unit & Concurrency Test Suite for In-RAM MarketMatrix and LiveCandleWeaver.
"""

from __future__ import annotations

import pandas as pd

from engine.market_matrix import (
    LiveCandleWeaver,
    MarketMatrix,
    get_market_matrix,
)
from market.websocket import Tick


def test_live_candle_weaver_single_bar():
    weaver = LiveCandleWeaver(max_bars=50)
    base_ts = 1776249600.0  # Normalized round epoch

    # Ingest 3 ticks in same 1-minute bucket (interval 60s)
    weaver.on_tick("RELIANCE", ltp=2500.0, day_volume=100, tick_ts=base_ts + 5)
    weaver.on_tick("RELIANCE", ltp=2520.0, day_volume=150, tick_ts=base_ts + 15)
    weaver.on_tick("RELIANCE", ltp=2490.0, day_volume=200, tick_ts=base_ts + 25)

    candles = weaver.get_candles("RELIANCE", timeframe="1m", include_active=True)
    assert len(candles) == 1
    active = candles[0]
    assert active["open"] == 2500.0
    assert active["high"] == 2520.0
    assert active["low"] == 2490.0
    assert active["close"] == 2490.0
    assert active["trades"] == 3


def test_live_candle_weaver_rollover_and_dataframe():
    weaver = LiveCandleWeaver(max_bars=50)
    base_ts = 1776249600.0

    # Bar 1 (0 to 59s)
    weaver.on_tick("INFY", ltp=1500.0, day_volume=100, tick_ts=base_ts + 10)
    weaver.on_tick("INFY", ltp=1510.0, day_volume=200, tick_ts=base_ts + 40)

    # Bar 2 (60 to 119s) triggers rollover of Bar 1
    weaver.on_tick("INFY", ltp=1520.0, day_volume=350, tick_ts=base_ts + 75)
    weaver.on_tick("INFY", ltp=1515.0, day_volume=400, tick_ts=base_ts + 90)

    candles = weaver.get_candles("INFY", timeframe="1m", include_active=True)
    assert len(candles) == 2

    # Completed bar 1
    b1 = candles[0]
    assert b1["open"] == 1500.0
    assert b1["high"] == 1510.0
    assert b1["close"] == 1510.0

    # Active bar 2
    b2 = candles[1]
    assert b2["open"] == 1520.0
    assert b2["high"] == 1520.0
    assert b2["low"] == 1515.0
    assert b2["close"] == 1515.0

    # Verify DataFrame export matches historical format
    df = weaver.get_candles_df("INFY", timeframe="1m", include_active=True)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None  # Timezone naive invariant


def test_market_matrix_tick_dataclass_and_dict_ingestion():
    matrix = MarketMatrix(buffer_capacity=100)

    # Ingest dataclass tick
    t1 = Tick(
        symbol="NSE:TCS-EQ",
        ltp=3800.0,
        volume=1000,
        timestamp=1776249600.0,
        atp=3795.0,
    )
    matrix.on_tick(t1)

    # Ingest dict tick
    t2 = {
        "symbol": "TCS",
        "ltp": 3820.0,
        "volume": 1200,
        "timestamp": 1776249610.0,
        "atp": 3805.0,
    }
    matrix.on_tick(t2)

    # Verify LTP and Canonical symbol resolution
    assert matrix.get_ltp("TCS") == 3820.0
    assert matrix.get_ltp("NSE:TCS-EQ") == 3820.0

    # Verify stats
    stats = matrix.get_quant_stats("TCS")
    assert stats["count"] == 2
    assert stats["last_price"] == 3820.0
    assert stats["min"] == 3800.0
    assert stats["max"] == 3820.0
    assert stats["vwap"] > 0


def test_market_matrix_singleton_and_memory_clear():
    matrix = get_market_matrix()
    matrix.on_tick({"symbol": "HDFCBANK", "ltp": 1650.0, "volume": 500})
    assert matrix.get_ltp("HDFCBANK") == 1650.0

    # Clear memory
    cleared = matrix.clear()
    assert cleared >= 1
    assert matrix.get_ltp("HDFCBANK") is None
