"""
Unit tests for Institutional Columnar Tick Warehouse in engine/tick_warehouse.py.
"""

import threading
from pathlib import Path
from engine.tick_warehouse import TickWarehouse


def test_tick_warehouse_ingestion_and_flush(tmp_path: Path):
    """Verify single and batch tick ingestion and on-demand flush."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NIFTY"

    wh.record_tick(symbol=symbol, ltp=25100.5, bid=25100.0, ask=25101.0, volume=5000)
    wh.record_tick(symbol=symbol, ltp=25102.0, bid=25101.5, ask=25102.5, volume=5500)

    # 2 rows in memory before flush
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 2

    flushed = wh.flush()
    assert flushed == 2
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 0

    # Query back as DataFrame
    df = wh.query_ticks(symbol, as_dataframe=True)
    assert len(df) == 2
    assert df["symbol"].iloc[0] == "NIFTY"
    assert df["ltp"].iloc[0] == 25100.5
    assert df["ltp"].iloc[1] == 25102.0


def test_tick_warehouse_auto_flush_threshold(tmp_path: Path):
    """Verify tick warehouse auto-flushes when buffer threshold is reached."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=10)
    symbol = "BANKNIFTY"

    for i in range(15):
        wh.record_tick(symbol=symbol, ltp=51000.0 + i)

    # Buffer should have auto-flushed at 10, leaving 5 in buffer
    stats = wh.get_storage_stats()
    assert stats["buffered_in_memory_rows"] == 5

    # Query automatically triggers flush for target symbol
    df = wh.query_ticks(symbol)
    assert len(df) == 15
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 0


def test_tick_warehouse_append_durability(tmp_path: Path):
    """Verify subsequent flushes append to existing Parquet file without corruption."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "RELIANCE"

    # Batch 1
    wh.record_tick(symbol=symbol, ltp=2950.0, timestamp_ms=1000)
    wh.flush()

    # Batch 2
    wh.record_tick(symbol=symbol, ltp=2955.0, timestamp_ms=2000)
    wh.flush()

    # Batch 3
    wh.record_tick(symbol=symbol, ltp=2960.0, timestamp_ms=3000)
    wh.flush()

    df = wh.query_ticks(symbol)
    assert len(df) == 3
    assert list(df["timestamp"]) == [1000, 2000, 3000]
    assert list(df["ltp"]) == [2950.0, 2955.0, 2960.0]


def test_tick_warehouse_time_filters(tmp_path: Path):
    """Verify time window filtering via pushdown filters."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "TCS"

    for t in [100, 200, 300, 400, 500]:
        wh.record_tick(symbol=symbol, ltp=4000.0, timestamp_ms=t)
    wh.flush()

    # Filter between [200, 400]
    df_window = wh.query_ticks(symbol, start_time_ms=200, end_time_ms=400)
    assert len(df_window) == 3
    assert list(df_window["timestamp"]) == [200, 300, 400]


def test_tick_warehouse_purge_retention(tmp_path: Path):
    """Verify rolling retention deletes partitions older than specified threshold."""
    wh = TickWarehouse(base_dir=tmp_path, retention_days=30)

    # Create current date partition
    today_part = wh._get_partition_path(wh._get_current_date_partition())
    today_part.mkdir(parents=True, exist_ok=True)
    (today_part / "NIFTY.parquet").write_bytes(b"dummy")

    # Create expired date partition (from year 2020)
    expired_part = tmp_path / "date=20200101"
    expired_part.mkdir(parents=True, exist_ok=True)
    (expired_part / "OLD.parquet").write_bytes(b"dummy")

    assert expired_part.exists()
    assert today_part.exists()

    purged = wh.purge_expired_partitions(retention_days=30)
    assert purged == 1
    assert not expired_part.exists()
    assert today_part.exists()


def test_tick_warehouse_concurrent_thread_safety(tmp_path: Path):
    """Verify thread-safe concurrent tick ingestion from multiple workers."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=50)
    symbol = "INFY"
    threads = []
    ticks_per_thread = 40
    num_threads = 4

    def worker(worker_id: int):
        for i in range(ticks_per_thread):
            wh.record_tick(
                symbol=symbol,
                ltp=1900.0 + (worker_id * 10) + i,
                volume=100 + i,
                flag="TRADE",
            )

    for tid in range(num_threads):
        t = threading.Thread(target=worker, args=(tid,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    wh.flush()

    df = wh.query_ticks(symbol)
    expected_total = num_threads * ticks_per_thread
    assert len(df) == expected_total
