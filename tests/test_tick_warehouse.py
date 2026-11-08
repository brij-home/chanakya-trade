"""
Unit tests for the append-only segment tick warehouse (engine/tick_warehouse.py).

Covers: buffered ingestion, threshold flushing, append-only durability, time
filter pushdown, retention purging, thread safety, generation-watermark
compaction, crash-window idempotency, write-failure requeue and lock-free writes.
"""

import threading
from pathlib import Path

import pyarrow as pa

import engine.tick_warehouse as tw
from engine.tick_warehouse import TickWarehouse


def _mp_worker(base_dir: str, tag: int, count: int) -> None:
    """Module-level worker so Windows 'spawn' can pickle it."""
    from pathlib import Path

    from engine.tick_warehouse import TickWarehouse as _TW

    wh = _TW(base_dir=Path(base_dir), auto_flush_threshold=1000)
    for i in range(count):
        wh.record_tick(
            symbol="NSE_XPROC-EQ",
            ltp=float(tag * 1000 + i),
            timestamp_ms=tag * 100000 + i,
        )
        if (i + 1) % 10 == 0:
            wh.flush()
    wh.flush()


def test_tick_warehouse_ingestion_and_flush(tmp_path: Path):
    """Verify single and batch tick ingestion and on-demand flush."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NIFTY"

    wh.record_tick(symbol=symbol, ltp=25100.5, bid=25100.0, ask=25101.0, volume=5000)
    wh.record_tick(symbol=symbol, ltp=25102.0, bid=25101.5, ask=25102.5, volume=5500)

    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 2

    flushed = wh.flush()
    assert flushed == 2
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 0

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

    stats = wh.get_storage_stats()
    assert stats["buffered_in_memory_rows"] == 5

    df = wh.query_ticks(symbol)
    assert len(df) == 15
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 0


def test_tick_warehouse_append_durability(tmp_path: Path):
    """Verify subsequent flushes append without corruption or row loss."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "RELIANCE"

    wh.record_tick(symbol=symbol, ltp=2950.0, timestamp_ms=1000)
    wh.flush()

    wh.record_tick(symbol=symbol, ltp=2955.0, timestamp_ms=2000)
    wh.flush()

    wh.record_tick(symbol=symbol, ltp=2960.0, timestamp_ms=3000)
    wh.flush()

    df = wh.query_ticks(symbol)
    assert len(df) == 3
    assert list(df["timestamp"]) == [1000, 2000, 3000]
    assert list(df["ltp"]) == [2950.0, 2955.0, 2960.0]


def test_tick_warehouse_time_filters(tmp_path: Path):
    """Verify time window filtering."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "TCS"

    for t in [100, 200, 300, 400, 500]:
        wh.record_tick(symbol=symbol, ltp=4000.0, timestamp_ms=t)
    wh.flush()

    df_window = wh.query_ticks(symbol, start_time_ms=200, end_time_ms=400)
    assert len(df_window) == 3
    assert list(df_window["timestamp"]) == [200, 300, 400]


def test_tick_warehouse_purge_retention(tmp_path: Path):
    """Verify rolling retention deletes partitions older than the threshold."""
    wh = TickWarehouse(base_dir=tmp_path, retention_days=30)

    today_part = wh._get_partition_path(wh._get_current_date_partition())
    today_part.mkdir(parents=True, exist_ok=True)
    (today_part / "NIFTY.parquet").write_bytes(b"dummy")

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


# ─────────────────────────────────────────────────────────────────────────────
# Append-only segment architecture
# ─────────────────────────────────────────────────────────────────────────────


def test_flush_writes_immutable_segments_without_rewriting(tmp_path: Path):
    """Each flush must create a new segment and never rewrite existing data."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_SEG-EQ"
    date = wh._get_current_date_partition()
    parts_dir = wh._symbol_parts_dir(symbol, date)

    wh.record_tick(symbol=symbol, ltp=100.0, timestamp_ms=1)
    assert wh.flush() == 1
    first = sorted(parts_dir.glob("part-*.parquet"))
    assert len(first) == 1
    first_size = first[0].stat().st_size

    wh.record_tick(symbol=symbol, ltp=200.0, timestamp_ms=2)
    assert wh.flush() == 1
    parts = sorted(parts_dir.glob("part-*.parquet"))
    assert len(parts) == 2

    # The first segment must be byte-identical: nothing was rewritten in place.
    assert first[0].exists()
    assert first[0].stat().st_size == first_size

    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2]


def test_compaction_merges_segments_with_generation_watermark(tmp_path: Path):
    """Compaction absorbs all visible segments into one merged generation."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_COMPACT-EQ"
    date = wh._get_current_date_partition()
    parts_dir = wh._symbol_parts_dir(symbol, date)

    for i in range(5):
        wh.record_tick(symbol=symbol, ltp=float(i), timestamp_ms=i + 1)
        wh.flush()
    parts = sorted(parts_dir.glob("part-*.parquet"))
    assert len(parts) == 5
    max_seq = max(wh._parse_seq(p) for p in parts)

    assert wh.compact_increments(symbol) == 5

    merged = list(parts_dir.glob("merged-*.parquet"))
    assert len(merged) == 1
    assert not list(parts_dir.glob("part-*.parquet"))
    assert wh._parse_seq(merged[0]) == max_seq

    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2, 3, 4, 5]


def test_query_ignores_covered_segments_after_crash(tmp_path: Path):
    """Crash between merged write and segment delete must not double-count."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_WATERMARK-EQ"
    date = wh._get_current_date_partition()
    parts_dir = wh._symbol_parts_dir(symbol, date)

    for i in range(3):
        wh.record_tick(symbol=symbol, ltp=float(i), timestamp_ms=i + 1)
        wh.flush()

    parts = sorted(parts_dir.glob("part-*.parquet"))
    max_seq = max(wh._parse_seq(p) for p in parts)

    # Simulate the crash window: merged generation exists, covered parts not deleted.
    combined = pa.concat_tables([tw_pq.read_table(p) for p in parts], promote_options="default")
    wh._write_table_atomic(combined, parts_dir / f"merged-{max_seq:020d}.parquet")
    assert len(list(parts_dir.glob("part-*.parquet"))) == 3

    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2, 3]  # 3 rows, not 6


def test_compaction_keeps_unreadable_segment_visible(tmp_path: Path, monkeypatch):
    """A segment that cannot be read must never be deleted by compaction."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_UNREADABLE-EQ"
    date = wh._get_current_date_partition()
    parts_dir = wh._symbol_parts_dir(symbol, date)

    for i in range(3):
        wh.record_tick(symbol=symbol, ltp=float(i), timestamp_ms=i + 1)
        wh.flush()

    parts = sorted(parts_dir.glob("part-*.parquet"))
    stuck = parts[1].name  # middle segment: prefix absorb of parts[0] is allowed
    real_read = wh._read_parquet_with_retry

    def _fake_read(path, *args, **kwargs):
        if Path(path).name == stuck:
            return None
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(wh, "_read_parquet_with_retry", _fake_read)

    # Compaction may absorb only the contiguous prefix before the stuck segment,
    # and must never advance the watermark past it.
    absorbed = wh.compact_increments(symbol)
    assert absorbed == 1
    assert (parts_dir / stuck).exists()

    monkeypatch.undo()
    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2, 3]


def test_flush_requeues_ticks_on_write_failure(tmp_path: Path, monkeypatch):
    """A failed segment write must return ticks to the buffer, never drop them."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_REQUEUE-EQ"

    def _boom(*_args, **_kwargs):
        raise OSError(28, "simulated disk full")

    monkeypatch.setattr(wh, "_write_table_atomic", _boom)
    wh.record_tick(symbol=symbol, ltp=100.0, timestamp_ms=1)
    wh.record_tick(symbol=symbol, ltp=200.0, timestamp_ms=2)
    assert wh.flush() == 0
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 2

    monkeypatch.undo()
    assert wh.flush() == 2
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 0

    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2]


def test_flush_does_not_block_on_compaction_lock(tmp_path: Path):
    """The write path takes no file lock: a held compaction lock cannot stall it."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_LOCKFREE-EQ"
    date = wh._get_current_date_partition()
    parts_dir = wh._symbol_parts_dir(symbol, date)

    with tw._file_lock(parts_dir / "compact", timeout_s=0.2) as got:
        assert got
        wh.record_tick(symbol=symbol, ltp=100.0, timestamp_ms=1)
        assert wh.flush() == 1  # would raise/timeout if the write path locked

    assert len(list(parts_dir.glob("part-*.parquet"))) == 1
    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1]


def test_legacy_single_file_is_still_read_as_base(tmp_path: Path):
    """Pre-segment single-file layout must remain readable alongside segments."""
    import pyarrow.parquet as _pq

    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_LEGACY-EQ"
    date = wh._get_current_date_partition()

    legacy = wh._get_parquet_file(symbol, date)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    _pq.write_table(
        pa.Table.from_pylist(
            [tw.TickRecord(timestamp=1, symbol=symbol, ltp=100.0).to_dict()],
            schema=tw.TICK_SCHEMA,
        ),
        legacy,
    )

    wh.record_tick(symbol=symbol, ltp=200.0, timestamp_ms=2)
    wh.flush()

    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2]
    assert legacy.exists()  # legacy base is never modified or deleted


tw_pq = __import__("pyarrow.parquet", fromlist=["parquet"])


def test_cross_process_concurrent_writes_lose_no_rows(tmp_path: Path):
    """Three concurrent processes writing one symbol must not lose or duplicate rows."""
    import multiprocessing as mp
    import os

    import pytest

    if os.name != "nt":
        pytest.skip("Windows multiprocessing-spawn semantics under test")

    ctx = mp.get_context("spawn")
    per_proc = 40
    procs = [
        ctx.Process(target=_mp_worker, args=(str(tmp_path), tag, per_proc)) for tag in (1, 2, 3)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)

    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]

    wh = TickWarehouse(base_dir=tmp_path)
    df = wh.query_ticks("NSE_XPROC-EQ")
    expected = per_proc * len(procs)
    assert len(df) == expected, f"lost rows: {len(df)} of {expected}"
    assert len(df.drop_duplicates()) == expected, "duplicate ticks detected"


def test_query_suppresses_exact_duplicate_rows(tmp_path: Path):
    """The same tick delivered twice must count once (VWAP/volume integrity)."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_DUPTICK-EQ"

    for _ in range(3):
        wh.record_tick(symbol=symbol, ltp=100.0, timestamp_ms=1)
        wh.flush()

    wh.record_tick(symbol=symbol, ltp=200.0, timestamp_ms=2)
    wh.flush()

    df = wh.query_ticks(symbol)
    assert list(df["timestamp"]) == [1, 2]
    assert list(df["ltp"]) == [100.0, 200.0]


def test_flush_dedupes_within_batch(tmp_path: Path):
    """Identical ticks inside one batch must be stored once."""
    import pyarrow.parquet as _pq

    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_BATCHDUP-EQ"
    date = wh._get_current_date_partition()

    for _ in range(5):
        wh.record_tick(symbol=symbol, ltp=100.0, timestamp_ms=1)
    assert wh.flush() == 5  # buffered count

    parts = list(wh._symbol_parts_dir(symbol, date).glob("part-*.parquet"))
    assert len(parts) == 1
    stored = _pq.read_table(parts[0]).to_pandas()
    assert len(stored) == 1


def test_retention_purges_expired_segments(tmp_path: Path):
    """Retention must delete expired partitions (including their segments)."""
    wh = TickWarehouse(base_dir=tmp_path, retention_days=30)

    old_dir = tmp_path / "date=20200101" / "parts" / "OLD"
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "part-00000000000000000001-p1.parquet").write_bytes(b"x")

    today = wh._get_partition_path(wh._get_current_date_partition())
    today.mkdir(parents=True, exist_ok=True)

    assert wh.purge_expired_partitions(30) == 1
    assert not (tmp_path / "date=20200101").exists()
    assert today.exists()


def test_compact_all_symbols_merges_pending_segments(tmp_path: Path):
    """The scheduled compaction entry point merges every pending symbol."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    date = wh._get_current_date_partition()

    for symbol in ("NSE_AAA-EQ", "NSE_BBB-EQ"):
        for i in range(2):
            wh.record_tick(symbol=symbol, ltp=float(i), timestamp_ms=i + 1)
            wh.flush()

    assert wh.compact_all_symbols() == 4

    for symbol in ("NSE_AAA-EQ", "NSE_BBB-EQ"):
        parts_dir = wh._symbol_parts_dir(symbol, date)
        assert not list(parts_dir.glob("part-*.parquet"))
        assert len(list(parts_dir.glob("merged-*.parquet"))) == 1
        assert len(wh.query_ticks(symbol)) == 2


def test_record_ticks_batch_buffers_and_flushes(tmp_path: Path):
    """Batch ingestion path must buffer and persist identically."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    ticks = [tw.TickRecord(timestamp=i + 1, symbol="NSE_BATCH-EQ", ltp=float(i)) for i in range(3)]
    wh.record_ticks_batch(ticks)
    assert wh.get_storage_stats()["buffered_in_memory_rows"] == 3
    assert wh.flush() == 3
    assert len(wh.query_ticks("NSE_BATCH-EQ")) == 3


def test_file_lock_timeout_raises_or_reports_false(tmp_path: Path):
    """A contended lock must time out cleanly, raising or yielding False."""
    import pytest

    target = tmp_path / "compact"
    with tw._file_lock(target, timeout_s=1.0) as got:
        assert got is True

        with pytest.raises(TimeoutError):
            with tw._file_lock(target, timeout_s=0.1):
                pass

        with tw._file_lock(target, timeout_s=0.1, raise_on_timeout=False) as got2:
            assert got2 is False


def test_query_time_filter_uses_pushdown(tmp_path: Path, monkeypatch):
    """Time filters must be pushed into parquet reads, not applied in memory only."""
    wh = TickWarehouse(base_dir=tmp_path, auto_flush_threshold=100)
    symbol = "NSE_PUSHDOWN-EQ"
    for t in (100, 200, 300):
        wh.record_tick(symbol=symbol, ltp=float(t), timestamp_ms=t)
    wh.flush()

    seen_filters = []
    real_read = wh._read_parquet_with_retry

    def _spy(path, *args, **kwargs):
        seen_filters.append(kwargs.get("filters"))
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(wh, "_read_parquet_with_retry", _spy)
    df = wh.query_ticks(symbol, start_time_ms=150, end_time_ms=250)

    assert list(df["timestamp"]) == [200]
    assert any(f for f in seen_filters), "no parquet filter pushdown was used"
