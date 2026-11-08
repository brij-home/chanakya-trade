"""
engine/historical_warehouse.py
──────────────────────────────
High-Performance Local Parquet Historical Market Warehouse.

Storage model (append-only, bar-keyed):
  1. Writes are IMMUTABLE SEGMENTS: save_bars() appends a new
     part-<seq>-p<pid>.parquet under <interval>/<SYMBOL>/. Existing history is
     never read and rewritten, so the classic read-modify-write lost-update and
     WinError 32 failure modes do not exist. The write path takes no file lock.
  2. Compaction merges segments into merged-<gen>.parquet where gen is the
     highest segment sequence it covers. Readers take the newest merged
     generation plus only the segments with seq > gen, so a crash between
     "write merged" and "delete covered segments" cannot double count.
  3. Legacy single-file layout <interval>/<SYMBOL>.parquet is still read as a
     read-only base and is never modified.

Durability: every segment is written to a temp file, fsynced and atomically
renamed, so a reader never observes a partial file.

Architecture:
  - Columnar Apache Parquet storage with Snappy compression.
  - Delta synchronization: bars dedupe on the datetime index, newest wins.
  - Timezone Normalization: enforces timezone-naive DatetimeIndex (Invariant 13).
  - Multi-threaded batch ingestion from the active broker.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Optional

import pandas as pd

from config.paths import app_data_path
from engine.file_lock import file_lock

logger = logging.getLogger("chanakya.historical_warehouse")

# Thread lock for concurrent compaction per process.
_warehouse_lock = threading.Lock()

# Segments per dataset that trigger opportunistic compaction.
_SEGMENT_COMPACT_THRESHOLD = 3

_BAR_COLUMNS = ["open", "high", "low", "close", "volume"]
_DAILY_INTERVALS = ("day", "1d", "d", "week", "1w", "month", "1mo", "1m_month")


def get_warehouse_dir() -> Path:
    """Returns the root directory for local historical parquet datasets."""
    env_dir = os.environ.get("CHANAKYA_WAREHOUSE_DIR")
    if env_dir:
        p = Path(env_dir)
    elif os.environ.get("CHANAKYA_TESTING") == "1":
        test_dir = Path(os.environ.get("TRADING_PLATFORM_DATA", ".pytest_trading_platform"))
        p = test_dir / "warehouse"
    else:
        p = app_data_path("warehouse")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _clean_symbol(symbol: str) -> str:
    return (
        symbol.upper()
        .replace("NSE:", "")
        .replace("BSE:", "")
        .replace("NFO:", "")
        .replace("MCX:", "")
        .replace("/", "_")
        .strip()
    )


class HistoricalWarehouse:
    """Append-only columnar bar warehouse with generation-based compaction."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or get_warehouse_dir()
        self._seq_lock = threading.Lock()
        self._last_seq = 0

    # ── Paths ────────────────────────────────────────────────────────────────
    def _interval_key(self, interval: str) -> str:
        return str(interval).lower().replace("minute", "m")

    def _legacy_path(self, symbol: str, interval: str) -> Path:
        """Legacy single-file location (read-only base for pre-segment data)."""
        folder = self.base_dir / self._interval_key(interval)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_clean_symbol(symbol)}.parquet"

    def _get_file_path(self, symbol: str, interval: str) -> Path:
        """Backwards-compatible alias for the legacy base path."""
        return self._legacy_path(symbol, interval)

    def _dataset_dir(self, symbol: str, interval: str) -> Path:
        """Directory holding immutable segments for one symbol/interval."""
        return self.base_dir / self._interval_key(interval) / _clean_symbol(symbol)

    # ── Segment sequencing ───────────────────────────────────────────────────
    def _next_seq(self, min_exclusive: int = 0) -> int:
        """Strictly increasing sequence that always clears the given watermark.

        Readers only see segments with seq > merged generation, so a segment
        stamped below the watermark (clock rollback) would be invisible forever.
        """
        with self._seq_lock:
            seq = max(time.time_ns(), self._last_seq + 1, min_exclusive + 1)
            self._last_seq = seq
            return seq

    @staticmethod
    def _parse_seq(path: Path) -> int:
        stem = path.name[: -len(".parquet")]
        try:
            head = stem.split("-", 1)[1]
            return int(head.split("-", 1)[0])
        except (IndexError, ValueError):
            return -1

    def _latest_merged(self, dataset_dir: Path) -> tuple[int, Optional[Path]]:
        if not dataset_dir.exists():
            return 0, None
        best_gen, best_path = 0, None
        for p in dataset_dir.glob("merged-*.parquet"):
            gen = self._parse_seq(p)
            if gen > best_gen:
                best_gen, best_path = gen, p
        return best_gen, best_path

    def _visible_segments(self, dataset_dir: Path, merged_gen: int) -> list[Path]:
        if not dataset_dir.exists():
            return []
        return sorted(
            (p for p in dataset_dir.glob("part-*.parquet") if self._parse_seq(p) > merged_gen),
            key=self._parse_seq,
        )

    # ── Durable IO ───────────────────────────────────────────────────────────
    def _write_frame_atomic(self, df: pd.DataFrame, target: Path) -> None:
        """Write a dataframe durably: temp file -> fsync -> atomic rename."""
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            with open(temp, "wb") as fh:
                df.to_parquet(fh, compression="snappy")
                fh.flush()
                os.fsync(fh.fileno())
            for attempt in range(5):
                try:
                    os.replace(temp, target)
                    break
                except (PermissionError, OSError) as e_replace:
                    if attempt == 4:
                        logger.error(
                            f"[HistoricalWarehouse] Atomic replace failed for {target}: {e_replace}"
                        )
                        raise
                    time.sleep(0.05 * (2**attempt))
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError as e_cleanup:
                    logger.debug(
                        f"[HistoricalWarehouse] Temp cleanup deferred for {temp.name}: {e_cleanup}"
                    )

    def _read_parquet_with_retry(self, file_path: Path, max_retries: int = 3) -> pd.DataFrame:
        """Reads a parquet file with retry for Windows sharing violations.

        A transient external lock (antivirus, indexer, another reader) raises
        PermissionError/OSError on Windows; those are retried with backoff and
        then re-raised so callers never mistake a lock for corruption.
        """
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                return pd.read_parquet(file_path)
            except (PermissionError, OSError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(0.08 * (2**attempt))
                    continue
                logger.warning(
                    f"[HistoricalWarehouse] File locked beyond retry budget: {file_path} ({e})"
                )
                raise
        raise last_error if last_error else RuntimeError("unreachable")

    def _read_safely(self, file_path: Path) -> Optional[pd.DataFrame]:
        """Best-effort read for the query path: returns None and logs on failure."""
        if not file_path.exists():
            return None
        try:
            return self._read_parquet_with_retry(file_path)
        except Exception as e_read:
            logger.warning(
                f"[HistoricalWarehouse] Skipping unreadable file {file_path.name}: {e_read}"
            )
            return None

    # ── Normalization ────────────────────────────────────────────────────────
    def _normalize(self, df: pd.DataFrame, interval: str) -> pd.DataFrame:
        norm_df = df.copy()
        norm_df.columns = [str(c).lower() for c in norm_df.columns]

        if "date" in norm_df.columns and not isinstance(norm_df.index, pd.DatetimeIndex):
            norm_df["date"] = pd.to_datetime(norm_df["date"])
            norm_df = norm_df.set_index("date")

        if not isinstance(norm_df.index, pd.DatetimeIndex):
            norm_df.index = pd.to_datetime(norm_df.index)

        if norm_df.index.tz is not None:
            norm_df.index = norm_df.index.tz_convert("Asia/Kolkata").tz_localize(None)

        norm_inv = str(interval).lower()
        if norm_inv not in _DAILY_INTERVALS and not norm_df.empty:
            mask = norm_df.index.hour < 9
            if mask.any():
                norm_df.index = norm_df.index.where(
                    ~mask, norm_df.index + pd.Timedelta(hours=5, minutes=30)
                )

        for req in ("open", "high", "low", "close"):
            if req not in norm_df.columns:
                raise ValueError(f"Missing required OHLCV column '{req}' in dataframe")
        if "volume" not in norm_df.columns:
            norm_df["volume"] = 0

        return norm_df[_BAR_COLUMNS]

    # ── Read model ───────────────────────────────────────────────────────────
    def _frame(self, symbol: str, interval: str) -> pd.DataFrame:
        """Assembles legacy base + newest merged generation + live segments."""
        dataset_dir = self._dataset_dir(symbol, interval)
        merged_gen, merged_path = self._latest_merged(dataset_dir)

        frames: list[pd.DataFrame] = []

        legacy = self._read_safely(self._legacy_path(symbol, interval))
        if legacy is not None and not legacy.empty:
            frames.append(legacy)

        if merged_path is not None:
            merged = self._read_safely(merged_path)
            if merged is not None and not merged.empty:
                frames.append(merged)

        for part in self._visible_segments(dataset_dir, merged_gen):
            segment = self._read_safely(part)
            if segment is not None and not segment.empty:
                frames.append(segment)

        if not frames:
            return pd.DataFrame()

        combined = frames[0] if len(frames) == 1 else pd.concat(frames)
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined[[c for c in _BAR_COLUMNS if c in combined.columns]]
        return combined.sort_index()

    # ── Write path ───────────────────────────────────────────────────────────
    def save_bars(
        self,
        symbol: str,
        interval: str,
        df: pd.DataFrame,
        provider: str = "fyers",
    ) -> int:
        """Appends bars as an immutable segment and returns the dataset row count."""
        if df is None or df.empty:
            return 0

        norm_df = self._normalize(df, interval)
        norm_df = norm_df[~norm_df.index.duplicated(keep="last")].sort_index()
        if norm_df.empty:
            return 0

        dataset_dir = self._dataset_dir(symbol, interval)
        merged_gen, _ = self._latest_merged(dataset_dir)
        seq = self._next_seq(merged_gen)
        target = dataset_dir / f"part-{seq:020d}-p{os.getpid()}.parquet"
        self._write_frame_atomic(norm_df, target)

        if self._count_segments(symbol, interval) >= _SEGMENT_COMPACT_THRESHOLD:
            try:
                self.compact(symbol, interval, lock_timeout_s=0.5)
            except Exception as e_compact:
                logger.warning(
                    f"[HistoricalWarehouse] Opportunistic compaction failed for "
                    f"{symbol} {interval}: {e_compact}"
                )

        # The segment is already durable. Row counting is best-effort: a locked
        # or unreadable file must never turn a successful write into an error.
        try:
            total = len(self._frame(symbol, interval))
        except Exception as e_count:
            logger.warning(
                f"[HistoricalWarehouse] Row count unavailable for {symbol} "
                f"{interval} (write succeeded): {e_count}"
            )
            total = 0
        # When history cannot be read right now, report what this call wrote.
        return total if total > 0 else len(norm_df)

    # ── Compaction ───────────────────────────────────────────────────────────
    def _count_segments(self, symbol: str, interval: str) -> int:
        dataset_dir = self._dataset_dir(symbol, interval)
        merged_gen, _ = self._latest_merged(dataset_dir)
        return len(self._visible_segments(dataset_dir, merged_gen))

    def compact(self, symbol: str, interval: str, lock_timeout_s: float = 2.0) -> int:
        """Merges visible segments into merged-<gen>.parquet. Returns count absorbed."""
        dataset_dir = self._dataset_dir(symbol, interval)
        if not dataset_dir.exists():
            return 0

        with _warehouse_lock:
            with file_lock(
                dataset_dir / "compact",
                timeout_s=lock_timeout_s,
                raise_on_timeout=False,
            ) as got:
                if not got:
                    logger.warning(
                        f"[HistoricalWarehouse] Compaction skipped for {symbol} "
                        f"{interval}: lock busy"
                    )
                    return 0

                merged_gen, merged_path = self._latest_merged(dataset_dir)
                segments = self._visible_segments(dataset_dir, merged_gen)
                if not segments and merged_path is None:
                    return 0

                frames: list[pd.DataFrame] = []
                absorbed: list[Path] = []
                if merged_path is not None:
                    current = self._read_safely(merged_path)
                    if current is None:
                        logger.warning(
                            f"[HistoricalWarehouse] Compaction skipped for {symbol} "
                            f"{interval}: merged generation unreadable"
                        )
                        return 0
                    frames.append(current)

                # Watermark invariant: merged-<gen> holds every segment with
                # seq <= gen, so only a contiguous ascending prefix may absorb.
                new_gen = merged_gen
                for segment in segments:
                    frame = self._read_safely(segment)
                    if frame is None:
                        logger.warning(
                            f"[HistoricalWarehouse] Compaction stopped before "
                            f"{segment.name} (unreadable); it stays visible"
                        )
                        break
                    frames.append(frame)
                    absorbed.append(segment)
                    new_gen = self._parse_seq(segment)

                if not absorbed:
                    return 0

                combined = frames[0] if len(frames) == 1 else pd.concat(frames)
                combined = combined[~combined.index.duplicated(keep="last")]
                combined = combined[[c for c in _BAR_COLUMNS if c in combined.columns]]
                combined = combined.sort_index()

                out_path = dataset_dir / f"merged-{new_gen:020d}.parquet"
                self._write_frame_atomic(combined, out_path)

                removed = 0
                for segment in absorbed:
                    try:
                        segment.unlink(missing_ok=True)
                        removed += 1
                    except OSError as e_unlink:
                        logger.warning(
                            f"[HistoricalWarehouse] Could not delete merged segment "
                            f"{segment.name}: {e_unlink}"
                        )
                if merged_path is not None and merged_path != out_path:
                    try:
                        merged_path.unlink(missing_ok=True)
                    except OSError as e_unlink:
                        logger.warning(
                            f"[HistoricalWarehouse] Could not delete superseded merged "
                            f"generation {merged_path.name}: {e_unlink}"
                        )
                return removed

    def compact_all(self) -> int:
        """Compacts every dataset with pending segments. Returns segments absorbed."""
        total = 0
        for symbol_dir in sorted(self.base_dir.glob("*/*")):
            if not symbol_dir.is_dir():
                continue
            interval = symbol_dir.parent.name
            try:
                if self._count_segments(symbol_dir.name, interval) >= 2:
                    total += self.compact(symbol_dir.name, interval, lock_timeout_s=0.5)
            except Exception as e_compact:
                logger.warning(
                    f"[HistoricalWarehouse] Compact-all skipped "
                    f"{symbol_dir.name}/{interval}: {e_compact}"
                )
        return total

    # ── Query path ───────────────────────────────────────────────────────────
    def load_bars(
        self,
        symbol: str,
        interval: str = "day",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        days: Optional[int] = None,
    ) -> pd.DataFrame:
        """Loads OHLCV bars from the local warehouse.

        Returns:
            pd.DataFrame: Sliced dataframe with timezone-naive DatetimeIndex, or empty.
        """
        try:
            df = self._frame(symbol, interval)
        except Exception as e_frame:
            logger.warning(
                f"[HistoricalWarehouse] Frame assembly failed for {symbol} {interval}: {e_frame}"
            )
            return pd.DataFrame()

        if df.empty:
            return df

        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)

        norm_inv = str(interval).lower()
        if norm_inv not in _DAILY_INTERVALS and not df.empty:
            mask = df.index.hour < 9
            if mask.any():
                df.index = df.index.where(~mask, df.index + pd.Timedelta(hours=5, minutes=30))

        if from_date or to_date:
            start = from_date.replace(tzinfo=None) if from_date else df.index[0]
            end = to_date.replace(tzinfo=None) if to_date else df.index[-1]
            sliced = df.loc[start:end]
            if not sliced.empty:
                return sliced.copy()

        if days and days > 0:
            cutoff = df.index[-1] - timedelta(days=days)
            sliced = df.loc[cutoff:]
            if not sliced.empty:
                return sliced.copy()
            bars_to_take = min(
                len(df),
                max(10, days * (75 if norm_inv not in _DAILY_INTERVALS else 1)),
            )
            return df.iloc[-bars_to_take:].copy()

        return df.copy()

    def has_bars(self, symbol: str, interval: str = "day", min_bars: int = 10) -> bool:
        """Checks if a valid dataset exists locally for the given symbol and interval."""
        try:
            return len(self.load_bars(symbol, interval=interval)) >= min_bars
        except Exception as e_check:
            logger.debug(
                f"[HistoricalWarehouse] has_bars check failed for {symbol} {interval}: {e_check}"
            )
            return False

    def sync_symbol_from_broker(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 15,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> int:
        """Synchronizes historical candles from the active data broker."""
        try:
            from brokers.session import get_data_broker, get_data_broker_key

            broker = get_data_broker()
            if not broker or getattr(broker, "_is_mock", False):
                logger.debug(
                    f"[HistoricalWarehouse] Cannot sync {symbol}: No active real data broker"
                )
                return 0

            to_dt = to_date or datetime.now()
            from_dt = from_date or (to_dt - timedelta(days=days))

            fetch_fn = getattr(broker, "get_historical_data", None)
            if not callable(fetch_fn):
                return 0

            raw = fetch_fn(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                from_date=from_dt,
                to_date=to_dt,
            )

            if raw:
                df = pd.DataFrame(raw)
                provider = get_data_broker_key() or "fyers"
                return self.save_bars(symbol, interval=interval, df=df, provider=provider)

        except Exception as e:
            logger.warning(f"[HistoricalWarehouse] Sync failed for {symbol} ({interval}): {e}")

        return 0

    def sync_universe(
        self,
        symbols: list[str],
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 10,
        max_workers: int = 4,
    ) -> dict[str, int]:
        """Concurrently syncs a list of symbols into the local warehouse."""
        results: dict[str, int] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_sym = {
                executor.submit(
                    self.sync_symbol_from_broker,
                    sym,
                    exchange=exchange,
                    interval=interval,
                    days=days,
                ): sym
                for sym in symbols
            }
            for future in concurrent.futures.as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    results[sym] = future.result()
                except Exception as e:
                    logger.debug(f"[HistoricalWarehouse] Error in sync task for {sym}: {e}")
                    results[sym] = 0
        return results

    def get_warehouse_stats(self) -> dict[str, Any]:
        """Returns storage metrics and inventory of the local warehouse."""
        stats: dict[str, Any] = {
            "total_files": 0,
            "total_size_mb": 0.0,
            "intervals": {},
            "storage_model": "append_only_segments",
        }
        if not self.base_dir.exists():
            return stats

        total_bytes = 0
        for p in self.base_dir.rglob("*.parquet"):
            stats["total_files"] += 1
            total_bytes += p.stat().st_size
            try:
                inv = p.relative_to(self.base_dir).parts[0]
            except ValueError:
                inv = p.parent.name
            stats["intervals"][inv] = stats["intervals"].get(inv, 0) + 1

        stats["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)
        return stats


# Global Singleton Instance
historical_warehouse = HistoricalWarehouse()
