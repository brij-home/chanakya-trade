"""
tests/test_historical_warehouse.py
───────────────────────────────────
Unit tests for the High-Performance Local Parquet Historical Market Warehouse.
"""

from datetime import datetime, timedelta
import pandas as pd

from engine.historical_warehouse import HistoricalWarehouse
import market.history as mh


def _create_synthetic_bars(count: int = 50, start_dt: datetime = None) -> pd.DataFrame:
    if start_dt is None:
        start_dt = datetime(2024, 10, 1, 9, 15)
    dates = [start_dt + timedelta(minutes=5 * i) for i in range(count)]
    data = []
    base_price = 2500.0
    for i, d in enumerate(dates):
        p = base_price + i * 2.0
        data.append(
            {
                "date": d,
                "open": p,
                "high": p + 5.0,
                "low": p - 3.0,
                "close": p + 2.0,
                "volume": 15000 + i * 100,
            }
        )
    df = pd.DataFrame(data)
    df.set_index("date", inplace=True)
    return df


def test_warehouse_save_and_load(tmp_path):
    """Verify saving and loading intraday bars from local Parquet warehouse."""
    wh = HistoricalWarehouse(base_dir=tmp_path)
    df = _create_synthetic_bars(30)

    saved_count = wh.save_bars("RELIANCE", interval="5minute", df=df)
    assert saved_count == 30
    assert wh.has_bars("RELIANCE", interval="5minute", min_bars=15) is True

    loaded_df = wh.load_bars("RELIANCE", interval="5minute")
    assert not loaded_df.empty
    assert len(loaded_df) == 30
    assert list(loaded_df.columns) == ["open", "high", "low", "close", "volume"]
    assert loaded_df.index[0] == df.index[0]
    assert loaded_df.index[-1] == df.index[-1]


def test_warehouse_deduplication_and_merge(tmp_path):
    """Verify that merging new overlapping candles deduplicates timestamps and sorts ascending."""
    wh = HistoricalWarehouse(base_dir=tmp_path)
    base_time = datetime(2024, 10, 1, 9, 15)

    # First batch: bars 0..20
    df1 = _create_synthetic_bars(20, start_dt=base_time)
    wh.save_bars("TCS", interval="15minute", df=df1)

    # Second batch: bars 15..35 (overlap from 15 to 20)
    overlap_time = base_time + timedelta(minutes=5 * 15)
    df2 = _create_synthetic_bars(20, start_dt=overlap_time)
    total_saved = wh.save_bars("TCS", interval="15minute", df=df2)

    # Total unique bars should be 35 (20 + 20 - 5 overlap)
    assert total_saved == 35

    loaded = wh.load_bars("TCS", interval="15minute")
    assert len(loaded) == 35
    assert loaded.index.is_monotonic_increasing


def test_warehouse_integration_with_market_history(tmp_path, monkeypatch):
    """Verify market.history.get_ohlcv transparently serves intraday data from the warehouse."""
    wh = HistoricalWarehouse(base_dir=tmp_path)
    monkeypatch.setattr("engine.historical_warehouse.historical_warehouse", wh)
    mh.clear_df_memory_cache()

    from market.calendar import get_latest_trading_day

    latest_day = get_latest_trading_day(exchange="NSE")
    start_dt = datetime.combine(latest_day, datetime.min.time()) + timedelta(hours=9, minutes=15)
    df = _create_synthetic_bars(60, start_dt=start_dt)
    wh.save_bars("INFY", interval="5minute", df=df)

    res = mh.get_ohlcv("INFY", interval="5minute", days=1)
    assert not res.empty
    assert len(res) >= 10
    assert res.attrs.get("provenance", {}).get("data_source") == "LOCAL_PARQUET_WAREHOUSE"


def test_warehouse_stats(tmp_path):
    """Verify stats tracking for files and intervals."""
    wh = HistoricalWarehouse(base_dir=tmp_path)
    df = _create_synthetic_bars(20)

    wh.save_bars("NIFTY", interval="5minute", df=df)
    wh.save_bars("BANKNIFTY", interval="15minute", df=df)

    stats = wh.get_warehouse_stats()
    assert stats["total_files"] == 2
    assert "5m" in stats["intervals"] or "5minute" in stats["intervals"]
    assert stats["total_size_mb"] >= 0.0
