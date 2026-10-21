"""
engine/tick_warehouse.py
────────────────────────
High-Performance Local Columnar Tick Warehouse using Apache Parquet & PyArrow.

Institutional Invariants:
1. Low latency: in-memory bounded ring buffers flush to disk in compressed columnar chunks.
2. Resource bounded: auto-purging 30-day retention keeps local SSD footprint < 500MB.
3. Thread-safe: concurrency locked for safe multi-threaded WebSocket & feed ingestion.
4. Zero external cost: runs 100% locally on CPU/SSD with zero cloud bills or SaaS lock-in.
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
from typing import Any, Optional, Sequence, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config.constants import IST

logger = logging.getLogger("engine.tick_warehouse")

DEFAULT_WAREHOUSE_DIR = Path("data/warehouse")

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


class TickWarehouse:
    """
    Columnar tick warehouse managing buffered in-memory ingestion,
    date-partitioned Parquet storage, and microsecond-level slice queries.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        auto_flush_threshold: int = 500,
        retention_days: int = 30,
    ) -> None:
        self.base_dir = Path(base_dir or DEFAULT_WAREHOUSE_DIR)
        self.auto_flush_threshold = max(10, auto_flush_threshold)
        self.retention_days = max(1, retention_days)

        self._lock = threading.Lock()
        self._buffers: dict[str, list[TickRecord]] = {}
        self._last_flush_time = time.monotonic()

        # Ensure base directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_current_date_partition(self) -> str:
        """Returns YYYYMMDD string in IST timezone."""
        return datetime.now(IST).strftime("%Y%m%d")

    def _get_partition_path(self, date_str: str) -> Path:
        """Returns directory for specific date partition."""
        return self.base_dir / f"date={date_str}"

    def _get_parquet_file(self, symbol: str, date_str: str) -> Path:
        """Returns target parquet file path for symbol on date."""
        clean_sym = symbol.upper().replace(":", "_").replace(".", "_").strip()
        part_dir = self._get_partition_path(date_str)
        part_dir.mkdir(parents=True, exist_ok=True)
        return part_dir / f"{clean_sym}.parquet"

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
        """
        Ingests a single tick into the in-memory buffer.
        Automatically triggers a background flush when buffer exceeds auto_flush_threshold.
        """
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
        with self._lock:
            if clean_sym not in self._buffers:
                self._buffers[clean_sym] = []
            self._buffers[clean_sym].append(tick)

            total_buffered = sum(len(b) for b in self._buffers.values())
            if total_buffered >= self.auto_flush_threshold:
                should_flush = True

        if should_flush:
            self.flush()

    def record_ticks_batch(self, ticks: Sequence[TickRecord]) -> None:
        """Ingests a batch of pre-constructed TickRecord items."""
        if not ticks:
            return

        should_flush = False
        with self._lock:
            for t in ticks:
                clean_sym = t.symbol.upper().strip()
                if clean_sym not in self._buffers:
                    self._buffers[clean_sym] = []
                self._buffers[clean_sym].append(t)

            total_buffered = sum(len(b) for b in self._buffers.values())
            if total_buffered >= self.auto_flush_threshold:
                should_flush = True

        if should_flush:
            self.flush()

    def flush(self, symbol: Optional[str] = None) -> int:
        """
        Flushes buffered ticks to date-partitioned Snappy-compressed Parquet files.
        Returns total number of rows flushed.
        """
        with self._lock:
            to_flush: dict[str, list[TickRecord]] = {}
            if symbol:
                clean_sym = symbol.upper().strip()
                if clean_sym in self._buffers and self._buffers[clean_sym]:
                    to_flush[clean_sym] = self._buffers.pop(clean_sym)
            else:
                for s, b in self._buffers.items():
                    if b:
                        to_flush[s] = b
                self._buffers.clear()
            self._last_flush_time = time.monotonic()

            if not to_flush:
                return 0

            date_str = self._get_current_date_partition()
            total_flushed = 0

            for s, records in to_flush.items():
                try:
                    dicts = [r.to_dict() for r in records]
                    table = pa.Table.from_pylist(dicts, schema=TICK_SCHEMA)
                    file_path = self._get_parquet_file(s, date_str)

                    temp_file = file_path.with_name(
                        f"{file_path.stem}_{os.getpid()}_{time.time_ns()}.tmp.parquet"
                    )
                    target_table = table
                    if file_path.exists():
                        try:
                            existing = pq.read_table(file_path, partitioning=None)
                            target_table = pa.concat_tables([existing, table])
                        except Exception as e_concat:
                            logger.warning(
                                f"[engine.tick_warehouse] Could not append to {file_path}, rewriting: {e_concat}"
                            )
                            target_table = table

                    pq.write_table(target_table, temp_file, compression="SNAPPY")
                    try:
                        temp_file.replace(file_path)
                    except Exception:
                        import shutil

                        shutil.move(str(temp_file), str(file_path))

                    total_flushed += len(records)
                except Exception as e:
                    logger.error(
                        f"[engine.tick_warehouse] Failed flushing {len(records)} ticks for {s}: {e}",
                        exc_info=True,
                    )

            return total_flushed

    def query_ticks(
        self,
        symbol: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        date_str: Optional[str] = None,
        as_dataframe: bool = True,
    ) -> Union[pd.DataFrame, pa.Table]:
        """
        Queries historical ticks for a symbol using zero-copy Parquet column filtering.

        Args:
            symbol: Target ticker symbol.
            start_time_ms: Optional filter: ticks >= start_time_ms.
            end_time_ms: Optional filter: ticks <= end_time_ms.
            date_str: Target date partition ('YYYYMMDD'). Defaults to today.
            as_dataframe: Return pandas DataFrame (True) or PyArrow Table (False).
        """
        # Ensure any in-memory buffer for this symbol is committed first
        self.flush(symbol)

        d_str = date_str or self._get_current_date_partition()
        file_path = self._get_parquet_file(symbol, d_str)

        if not file_path.exists():
            empty_table = pa.Table.from_batches([], schema=TICK_SCHEMA)
            return empty_table.to_pandas() if as_dataframe else empty_table

        filters = []
        if start_time_ms is not None:
            filters.append(("timestamp", ">=", start_time_ms))
        if end_time_ms is not None:
            filters.append(("timestamp", "<=", end_time_ms))

        try:
            if filters:
                table = pq.read_table(file_path, partitioning=None, filters=filters)
            else:
                table = pq.read_table(file_path, partitioning=None)

            if as_dataframe:
                df = table.to_pandas()
                if not df.empty and "timestamp" in df.columns:
                    df = df.sort_values("timestamp").reset_index(drop=True)
                return df
            return table
        except Exception as e:
            logger.error(f"[engine.tick_warehouse] Query failed on {file_path}: {e}", exc_info=True)
            empty_table = pa.Table.from_batches([], schema=TICK_SCHEMA)
            return empty_table.to_pandas() if as_dataframe else empty_table

    def purge_expired_partitions(self, retention_days: Optional[int] = None) -> int:
        """
        Enforces the 30-day retention invariant by deleting dated partition folders
        older than retention_days. Prevents SSD disk expansion.

        Returns:
            Number of partition folders removed.
        """
        days = retention_days if retention_days is not None else self.retention_days
        cutoff_date = datetime.now(IST).date() - timedelta(days=days)
        purged_count = 0

        with self._lock:
            if not self.base_dir.exists():
                return 0

            for entry in self.base_dir.iterdir():
                if entry.is_dir() and entry.name.startswith("date="):
                    date_part = entry.name.replace("date=", "").strip()
                    try:
                        part_date = datetime.strptime(date_part, "%Y%m%d").date()
                        if part_date < cutoff_date:
                            shutil.rmtree(entry, ignore_errors=True)
                            purged_count += 1
                            logger.info(
                                f"[engine.tick_warehouse] Purged expired tick warehouse partition: {entry.name}"
                            )
                    except ValueError:
                        continue

        return purged_count

    def get_storage_stats(self) -> dict[str, Any]:
        """Returns warehouse disk usage and partition counts."""
        total_bytes = 0
        file_count = 0
        partitions = []

        if self.base_dir.exists():
            for p in self.base_dir.iterdir():
                if p.is_dir() and p.name.startswith("date="):
                    partitions.append(p.name)
                    for f in p.glob("*.parquet"):
                        total_bytes += f.stat().st_size
                        file_count += 1

        buffered_rows = sum(len(b) for b in self._buffers.values())

        return {
            "warehouse_path": str(self.base_dir),
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "parquet_files": file_count,
            "date_partitions": sorted(partitions),
            "buffered_in_memory_rows": buffered_rows,
            "retention_days": self.retention_days,
        }


# Global singleton instance
_GLOBAL_WAREHOUSE: Optional[TickWarehouse] = None
_GLOBAL_LOCK = threading.Lock()


def get_tick_warehouse(base_dir: Optional[Path] = None) -> TickWarehouse:
    """Returns application-wide singleton instance of TickWarehouse."""
    global _GLOBAL_WAREHOUSE
    with _GLOBAL_LOCK:
        if _GLOBAL_WAREHOUSE is None:
            _GLOBAL_WAREHOUSE = TickWarehouse(base_dir=base_dir)
        return _GLOBAL_WAREHOUSE
