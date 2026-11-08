"""
engine/tick_warehouse.py
────────────────────────
High-Performance Local Columnar Tick Warehouse using Apache Parquet & PyArrow.

Storage model (log-structured, append-only):
  1. Writes are IMMUTABLE SEGMENTS: each flush creates a new part-<seq>.parquet
     in date=YYYYMMDD/parts/<SYMBOL>/. Nothing is ever rewritten in place, so
     the historic read-modify-write (and its lost-update / WinError 32 failure
     modes) cannot occur. The write path takes no file lock at all.
  2. Compaction merges segments into a single merged-<gen>.parquet where gen is
     the highest segment sequence it covers. Readers select the newest merged
     generation and only the segments with seq > gen, so a crash between
     "write merged" and "delete covered segments" can never double-count:
     covered segments are ignored by generation, not by deletion success.
  3. Legacy single-file layout date=<d>/<SYMBOL>.parquet (pre-segment writes)
     is still read as a read-only base and is never modified.

Durability: every segment is written to a temp file, fsynced, then atomically
renamed into place, so a reader never observes a partial file.

Concurrency:
  - Cross-process exclusion is needed only for compaction, via a persistent
    compact.lock sidecar (Windows msvcrt / POSIX fcntl). The sidecar is never
    deleted, which removes the classic unlink race where two processes can hold
    locks on different inodes.
  - In-process state is guarded by short, narrowly scoped locks; no lock is held
    across segment I/O for the write path, so one symbol cannot stall another.

Tiering: this is the columnar analytics store. market.tick_store (SQLite) is the
live streaming archive used by the REPL/API for recent ticks; the two are
complementary, not duplicates.

Institutional invariants:
  1. Low latency: bounded in-memory buffers spill to compressed columnar chunks.
  2. Resource bounded: 30-day retention plus generation-based compaction.
  3. Thread-safe: concurrency locked for multi-threaded WebSocket & feed ingestion.
  4. Zero external cost: runs 100% locally on CPU/SSD.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config.constants import IST

logger = logging.getLogger("engine.tick_warehouse")

DEFAULT_WAREHOUSE_DIR = Path("data/warehouse")

# Segment count per symbol/date that triggers opportunistic compaction.
_SEGMENT_COMPACT_THRESHOLD = 8

# ── Cross-process lock (shared primitive) ────────────────────────────────────
from engine.file_lock import file_lock as _file_lock  # noqa: E402  (after defaults)


# Columnar Arrow Schema
TICK_SCHEMA = pa.schema(
    [
        ("timestamp", pa.int64()),  # Unix epoch in milliseconds
        ("symbol", pa.string()),
        ("ltp", pa.float64()),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("bid_qty", pa.int64()),
        ("ask_qty", pa.int64()),
        ("volume", pa.int64()),
        ("oi", pa.int64()),
        ("iv", pa.float64()),
        ("delta", pa.float64()),
        ("gamma", pa.float64()),
        ("theta", pa.float64()),
        ("vega", pa.float64()),
        ("flag", pa.string()),  # "QUOTE", "TRADE", "L2", "GREEK"
    ]
)


@dataclass(slots=True)
class TickRecord:
    timestamp: int  # Epoch ms
    symbol: str
    ltp: float
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: int = 0
    ask_qty: int = 0
    volume: int = 0
    oi: int = 0
    iv: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    flag: str = "QUOTE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "ltp": float(self.ltp),
            "bid": float(self.bid),
            "ask": float(self.ask),
            "bid_qty": int(self.bid_qty),
            "ask_qty": int(self.ask_qty),
            "volume": int(self.volume),
            "oi": int(self.oi),
            "iv": float(self.iv) if self.iv is not None else None,
            "delta": float(self.delta) if self.delta is not None else None,
            "gamma": float(self.gamma) if self.gamma is not None else None,
            "theta": float(self.theta) if self.theta is not None else None,
            "vega": float(self.vega) if self.vega is not None else None,
            "flag": str(self.flag),
        }


def _clean_symbol(symbol: str) -> str:
    return symbol.upper().replace(":", "_").replace(".", "_").strip()


class TickWarehouse:
    """Append-only columnar tick warehouse with generation-based compaction."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        auto_flush_threshold: int = 500,
        retention_days: int = 30,
    ) -> None:
        self.base_dir = Path(base_dir or DEFAULT_WAREHOUSE_DIR)
        self.auto_flush_threshold = max(10, auto_flush_threshold)
        self.retention_days = max(1, retention_days)

        # Narrowly scoped locks: buffers never wait on segment I/O.
        self._buffer_lock = threading.Lock()
        self._compact_lock = threading.Lock()
        self._seq_lock = threading.Lock()
        self._last_seq = 0

        self._buffers: dict[str, list[TickRecord]] = {}
        self._last_flush_time = time.monotonic()

        # Lightweight operational counters surfaced by get_storage_stats().
        self._counter_lock = threading.Lock()
        self._counters: dict[str, int] = {
            "segments_written": 0,
            "batches_requeued": 0,
            "rows_requeued": 0,
            "compaction_runs": 0,
            "segments_compacted": 0,
            "compaction_skipped_locked": 0,
            "compaction_skipped_unreadable": 0,
        }

        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _bump(self, name: str, amount: int = 1) -> None:
        """Increments an operational counter."""
        with self._counter_lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    # ── Paths ────────────────────────────────────────────────────────────────
    def _get_current_date_partition(self) -> str:
        """Returns YYYYMMDD string in IST timezone."""
        return datetime.now(IST).strftime("%Y%m%d")

    def _get_partition_path(self, date_str: str) -> Path:
        """Returns directory for specific date partition."""
        return self.base_dir / f"date={date_str}"

    def _legacy_path(self, symbol: str, date_str: str) -> Path:
        """Legacy single-file location (read-only base for pre-segment data)."""
        return self._get_partition_path(date_str) / f"{_clean_symbol(symbol)}.parquet"

    def _symbol_parts_dir(self, symbol: str, date_str: str) -> Path:
        """Directory holding immutable segments for one symbol/date."""
        return self._get_partition_path(date_str) / "parts" / _clean_symbol(symbol)

    def _get_parquet_file(self, symbol: str, date_str: str) -> Path:
        """Backwards-compatible alias for the legacy base path."""
        return self._legacy_path(symbol, date_str)

    # ── Segment sequencing ───────────────────────────────────────────────────
    def _next_seq(self) -> int:
        """Strictly increasing allocation sequence (ns + monotonic guard)."""
        with self._seq_lock:
            seq = max(time.time_ns(), self._last_seq + 1)
            self._last_seq = seq
            return seq

    # ── Atomic durable writes ────────────────────────────────────────────────
    @staticmethod
    def _fsync_dir(path: Path) -> None:
        """Best-effort directory fsync (unsupported on Windows; ignored there)."""
        if os.name == "nt":
            return
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError as e_fsync:
            logger.debug(
                f"[engine.tick_warehouse] Directory fsync unavailable for {path}: {e_fsync}"
            )
        finally:
            os.close(fd)

    def _write_table_atomic(self, table: pa.Table, target: Path) -> None:
        """Write a table durably: temp file -> fsync -> atomic rename."""
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            with open(temp, "wb") as fh:
                pq.write_table(table, fh, compression="SNAPPY")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, target)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError as e_cleanup:
                    logger.debug(
                        f"[engine.tick_warehouse] Temp cleanup deferred for {temp.name}: {e_cleanup}"
                    )
        self._fsync_dir(target.parent)

    # ── Reading ──────────────────────────────────────────────────────────────
    def _read_parquet_with_retry(
        self, file_path: Path, max_retries: int = 3, filters: Any = None
    ) -> Optional[pa.Table]:
        """Reads a parquet file, retrying transient Windows sharing violations.

        filters is a pyarrow predicate list, e.g. ("timestamp", ">=", ts), so row
        groups outside the query window are never materialised.
        """
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                return pq.read_table(file_path, partitioning=None, filters=filters)
            except (PermissionError, OSError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(0.08 * (2**attempt))
                    continue
                logger.warning(
                    f"[engine.tick_warehouse] Could not read {file_path} after "
                    f"{max_retries} attempts: {last_error}"
                )
        return None

    @staticmethod
    def _parse_seq(path: Path) -> int:
        """Extracts the sequence from part-<seq>-p<pid>.parquet / merged-<gen>.parquet."""
        stem = path.name[: -len(".parquet")]
        try:
            head = stem.split("-", 1)[1]
            return int(head.split("-", 1)[0])
        except (IndexError, ValueError):
            return -1

    def _latest_merged(self, parts_dir: Path) -> tuple[int, Optional[Path]]:
        """Returns (generation, path) of the newest merged segment, or (0, None)."""
        if not parts_dir.exists():
            return 0, None
        best_gen, best_path = 0, None
        for p in parts_dir.glob("merged-*.parquet"):
            gen = self._parse_seq(p)
            if gen > best_gen:
                best_gen, best_path = gen, p
        return best_gen, best_path

    def _visible_parts(self, parts_dir: Path, merged_gen: int) -> list[Path]:
        """Segments not covered by the merged generation watermark."""
        if not parts_dir.exists():
            return []
        return sorted(
            (p for p in parts_dir.glob("part-*.parquet") if self._parse_seq(p) > merged_gen),
            key=self._parse_seq,
        )

    # ── Ingestion ────────────────────────────────────────────────────────────
    def record_tick(
        self,
        symbol: str,
        ltp: float,
        bid: float = 0.0,
        ask: float = 0.0,
        bid_qty: int = 0,
        ask_qty: int = 0,
        volume: int = 0,
        oi: int = 0,
        iv: Optional[float] = None,
        delta: Optional[float] = None,
        gamma: Optional[float] = None,
        theta: Optional[float] = None,
        vega: Optional[float] = None,
        flag: str = "QUOTE",
        timestamp_ms: Optional[int] = None,
    ) -> None:
        """Buffers a single tick; flushes automatically past the threshold."""
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        clean_sym = symbol.upper().strip()
        tick = TickRecord(
            timestamp=ts,
            symbol=clean_sym,
            ltp=ltp,
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            volume=volume,
            oi=oi,
            iv=iv,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            flag=flag,
        )
        should_flush = False
        with self._buffer_lock:
            self._buffers.setdefault(clean_sym, []).append(tick)
            if sum(len(b) for b in self._buffers.values()) >= self.auto_flush_threshold:
                should_flush = True
        if should_flush:
            self.flush()

    def record_ticks_batch(self, ticks: Sequence[TickRecord]) -> None:
        """Buffers a batch of pre-constructed tick records."""
        if not ticks:
            return
        should_flush = False
        with self._buffer_lock:
            for t in ticks:
                self._buffers.setdefault(t.symbol.upper().strip(), []).append(t)
            if sum(len(b) for b in self._buffers.values()) >= self.auto_flush_threshold:
                should_flush = True
        if should_flush:
            self.flush()

    # ── Flush (append-only, lock-free) ───────────────────────────────────────
    def flush(self, symbol: Optional[str] = None) -> int:
        """Writes buffered ticks as immutable segments. Returns rows persisted."""
        with self._buffer_lock:
            if symbol:
                clean_sym = symbol.upper().strip()
                records = self._buffers.pop(clean_sym, [])
                to_flush = {clean_sym: records} if records else {}
            else:
                to_flush = {s: b for s, b in self._buffers.items() if b}
                self._buffers.clear()
            self._last_flush_time = time.monotonic()

        if not to_flush:
            return 0

        date_str = self._get_current_date_partition()
        total_flushed = 0

        for sym, records in to_flush.items():
            if not records:
                continue
            try:
                table = pa.Table.from_pylist([r.to_dict() for r in records], schema=TICK_SCHEMA)
                # Idempotent ingestion: multi-feed pollers can deliver the same
                # tick more than once; identical rows add no information and
                # would double count in VWAP/volume downstream.
                if table.num_rows > 1:
                    table = pa.Table.from_pandas(
                        table.to_pandas().drop_duplicates(),
                        schema=TICK_SCHEMA,
                        preserve_index=False,
                    )
                parts_dir = self._symbol_parts_dir(sym, date_str)
                # PID suffix: Windows timer granularity (~15.6 ms) lets two
                # processes mint the same nanosecond sequence, which would make
                # one segment overwrite the other. The sequence still drives
                # ordering and the compaction watermark.
                target = parts_dir / f"part-{self._next_seq():020d}-p{os.getpid()}.parquet"
                self._write_table_atomic(table, target)
                self._bump("segments_written")
                total_flushed += len(records)
            except Exception as e:
                # Never drop ticks: return them to the buffer for the next flush.
                logger.error(
                    f"[engine.tick_warehouse] Segment write failed for {sym}; "
                    f"{len(records)} ticks requeued: {e}",
                    exc_info=True,
                )
                self._bump("batches_requeued")
                self._bump("rows_requeued", len(records))
                with self._buffer_lock:
                    self._buffers.setdefault(sym, []).extend(records)

        # Bound segment count: merge once a symbol accumulates enough segments.
        for sym in to_flush:
            try:
                if self._count_parts(sym, date_str) >= _SEGMENT_COMPACT_THRESHOLD:
                    self._compact_symbol(sym, date_str, lock_timeout_s=0.25)
            except Exception as e_compact:
                logger.warning(
                    f"[engine.tick_warehouse] Opportunistic compaction failed for "
                    f"{sym}: {e_compact}"
                )

        return total_flushed

    # ── Compaction (generation watermark) ────────────────────────────────────
    def _count_parts(self, symbol: str, date_str: str) -> int:
        """Counts segments still visible (not covered by a merged generation)."""
        parts_dir = self._symbol_parts_dir(symbol, date_str)
        merged_gen, _ = self._latest_merged(parts_dir)
        return len(self._visible_parts(parts_dir, merged_gen))

    def compact_all_symbols(self, date_str: Optional[str] = None) -> int:
        """Compacts every symbol with pending segments. Returns segments absorbed.

        Called by the periodic maintenance scheduler so segment counts stay
        bounded even for symbols that stopped receiving ticks mid-session.
        """
        with self._compact_lock:
            d_str = date_str or self._get_current_date_partition()
            parts_root = self._get_partition_path(d_str) / "parts"
            if not parts_root.exists():
                return 0
            total = 0
            for symbol_dir in sorted(parts_root.iterdir()):
                if not symbol_dir.is_dir():
                    continue
                if self._count_parts(symbol_dir.name, d_str) < 2:
                    continue
                total += self._compact_symbol(symbol_dir.name, d_str, lock_timeout_s=0.5)
            return total

    def compact_increments(
        self, symbol: Optional[str] = None, date_str: Optional[str] = None
    ) -> int:
        """Compacts segments into a merged generation. Returns segments absorbed."""
        with self._compact_lock:
            return self._compact(symbol, date_str)

    def _compact(self, symbol: Optional[str], date_str: Optional[str]) -> int:
        d_str = date_str or self._get_current_date_partition()
        if symbol:
            symbols: Iterable[str] = [symbol.upper().strip()]
        else:
            parts_root = self._get_partition_path(d_str) / "parts"
            symbols = (
                [p.name for p in parts_root.iterdir() if p.is_dir()] if parts_root.exists() else []
            )
        return sum(self._compact_symbol(s, d_str, lock_timeout_s=2.0) for s in symbols)

    def _compact_symbol(self, symbol: str, date_str: str, lock_timeout_s: float = 2.0) -> int:
        """Merges visible segments into merged-<gen>.parquet. Returns count absorbed."""
        parts_dir = self._symbol_parts_dir(symbol, date_str)
        if not parts_dir.exists():
            return 0

        with _file_lock(
            parts_dir / "compact", timeout_s=lock_timeout_s, raise_on_timeout=False
        ) as got:
            if not got:
                self._bump("compaction_skipped_locked")
                logger.warning(
                    f"[engine.tick_warehouse] Compaction skipped for {symbol}: lock busy"
                )
                return 0

            merged_gen, merged_path = self._latest_merged(parts_dir)
            parts = self._visible_parts(parts_dir, merged_gen)
            if not parts and merged_path is None:
                return 0

            # Read everything first; never merge a segment we could not read.
            tables: list[pa.Table] = []
            absorbed: list[Path] = []
            if merged_path is not None:
                current = self._read_parquet_with_retry(merged_path)
                if current is None:
                    logger.warning(
                        f"[engine.tick_warehouse] Compaction skipped for {symbol}: "
                        f"merged generation unreadable"
                    )
                    return 0
                tables.append(current)

            # The watermark invariant is "merged-<gen> contains every segment with
            # seq <= gen". Therefore only a CONTIGUOUS ascending prefix may be
            # absorbed: on the first unreadable segment we stop, so the watermark
            # can never advance past data that is not in the merged output.
            new_gen = merged_gen
            for part in parts:
                table = self._read_parquet_with_retry(part)
                if table is None:
                    self._bump("compaction_skipped_unreadable")
                    logger.warning(
                        f"[engine.tick_warehouse] Compaction stopped before segment "
                        f"{part.name} (unreadable); it stays visible"
                    )
                    break
                tables.append(table)
                absorbed.append(part)
                new_gen = self._parse_seq(part)

            if not absorbed:
                return 0

            out_path = parts_dir / f"merged-{new_gen:020d}.parquet"
            combined = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
            self._write_table_atomic(combined, out_path)

            # Cleanup is best-effort: readers filter by generation, so a failed
            # delete can never cause double counting.
            removed = 0
            for part in absorbed:
                try:
                    part.unlink(missing_ok=True)
                    removed += 1
                except OSError as e_unlink:
                    logger.warning(
                        f"[engine.tick_warehouse] Could not delete merged segment "
                        f"{part.name}: {e_unlink}"
                    )
            self._bump("compaction_runs")
            self._bump("segments_compacted", removed)
            if merged_path is not None and merged_path != out_path:
                try:
                    merged_path.unlink(missing_ok=True)
                except OSError as e_unlink:
                    logger.warning(
                        f"[engine.tick_warehouse] Could not delete superseded merged "
                        f"generation {merged_path.name}: {e_unlink}"
                    )
            return removed

    # ── Query ────────────────────────────────────────────────────────────────
    def query_ticks(
        self,
        symbol: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        date_str: Optional[str] = None,
        as_dataframe: bool = True,
    ) -> Union[pd.DataFrame, pa.Table]:
        """Queries ticks across legacy base, newest merged generation and segments."""
        self.flush(symbol)

        d_str = date_str or self._get_current_date_partition()
        parts_dir = self._symbol_parts_dir(symbol, d_str)
        merged_gen, merged_path = self._latest_merged(parts_dir)

        # Push the time window down into every file so out-of-range row groups
        # are skipped instead of being read and filtered in memory.
        pq_filters: Any = None
        if start_time_ms is not None or end_time_ms is not None:
            pq_filters = []
            if start_time_ms is not None:
                pq_filters.append(("timestamp", ">=", start_time_ms))
            if end_time_ms is not None:
                pq_filters.append(("timestamp", "<=", end_time_ms))

        tables: list[pa.Table] = []

        # Legacy base (read-only, disjoint from segments).
        legacy = self._legacy_path(symbol, d_str)
        if legacy.exists():
            base_table = self._read_parquet_with_retry(legacy, filters=pq_filters)
            if base_table is not None:
                tables.append(base_table)

        # Newest merged generation.
        if merged_path is not None:
            merged_table = self._read_parquet_with_retry(merged_path, filters=pq_filters)
            if merged_table is not None:
                tables.append(merged_table)

        # Segments newer than the merged watermark.
        for part in self._visible_parts(parts_dir, merged_gen):
            part_table = self._read_parquet_with_retry(part, filters=pq_filters)
            if part_table is None:
                logger.warning(
                    f"[engine.tick_warehouse] Segment {part.name} unreadable during query"
                )
                continue
            tables.append(part_table)

        if not tables:
            empty_table = pa.Table.from_batches([], schema=TICK_SCHEMA)
            return empty_table.to_pandas() if as_dataframe else empty_table

        combined = pa.concat_tables(tables) if len(tables) > 1 else tables[0]

        # Source-level duplicate suppression. Historic single-file appends and
        # repeated polling already stored identical ticks; without this, VWAP,
        # volume and R-multiple maths would double count them. Dedupe is by exact
        # row, so legitimately distinct ticks in the same millisecond survive.
        try:
            combined = pa.Table.from_pandas(
                combined.to_pandas().drop_duplicates(),
                schema=TICK_SCHEMA,
                preserve_index=False,
            )
        except Exception as e_dedupe:
            logger.warning(
                f"[engine.tick_warehouse] Duplicate suppression failed for {symbol}: {e_dedupe}"
            )

        if start_time_ms is not None or end_time_ms is not None:
            try:
                df = combined.to_pandas()
                if start_time_ms is not None:
                    df = df[df["timestamp"] >= start_time_ms]
                if end_time_ms is not None:
                    df = df[df["timestamp"] <= end_time_ms]
                combined = pa.Table.from_pandas(df, schema=TICK_SCHEMA, preserve_index=False)
            except Exception as e_filter:
                logger.warning(
                    f"[engine.tick_warehouse] In-memory time filter failed for {symbol}: {e_filter}"
                )

        if as_dataframe:
            df = combined.to_pandas()
            if not df.empty and "timestamp" in df.columns:
                df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        return combined

    # ── Retention & stats ────────────────────────────────────────────────────
    def purge_expired_partitions(self, retention_days: Optional[int] = None) -> int:
        """Deletes date partitions older than the retention window."""
        days = retention_days if retention_days is not None else self.retention_days
        cutoff_date = datetime.now(IST).date() - timedelta(days=days)
        purged_count = 0

        with self._compact_lock:
            if not self.base_dir.exists():
                return 0
            for entry in self.base_dir.iterdir():
                if entry.is_dir() and entry.name.startswith("date="):
                    date_part = entry.name.replace("date=", "").strip()
                    try:
                        part_date = datetime.strptime(date_part, "%Y%m%d").date()
                    except ValueError:
                        continue
                    if part_date < cutoff_date:
                        shutil.rmtree(entry, ignore_errors=True)
                        purged_count += 1
                        logger.info(
                            f"[engine.tick_warehouse] Purged expired tick warehouse "
                            f"partition: {entry.name}"
                        )
        return purged_count

    def get_storage_stats(self) -> dict[str, Any]:
        """Returns warehouse disk usage, partition and segment counts."""
        total_bytes = 0
        file_count = 0
        partitions: list[str] = []
        segments = 0

        if self.base_dir.exists():
            for p in self.base_dir.iterdir():
                if p.is_dir() and p.name.startswith("date="):
                    partitions.append(p.name)
                    for f in p.rglob("*.parquet"):
                        total_bytes += f.stat().st_size
                        file_count += 1
                        if f.name.startswith(("part-", "merged-")):
                            segments += 1

        with self._buffer_lock:
            buffered_rows = sum(len(b) for b in self._buffers.values())

        return {
            "warehouse_path": str(self.base_dir),
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "parquet_files": file_count,
            "segment_files": segments,
            "date_partitions": sorted(partitions),
            "buffered_in_memory_rows": buffered_rows,
            "retention_days": self.retention_days,
            "storage_model": "append_only_segments",
            "counters": dict(self._counters),
        }


# Global singleton instance
_GLOBAL_WAREHOUSE: Optional[TickWarehouse] = None
_GLOBAL_LOCK = threading.Lock()


def get_tick_warehouse(base_dir: Optional[Path] = None) -> TickWarehouse:
    """Returns the application-wide singleton tick warehouse."""
    global _GLOBAL_WAREHOUSE
    with _GLOBAL_LOCK:
        if _GLOBAL_WAREHOUSE is None:
            _GLOBAL_WAREHOUSE = TickWarehouse(base_dir=base_dir)
        return _GLOBAL_WAREHOUSE
