"""
engine/historical_warehouse.py
──────────────────────────────
High-Performance Local Parquet Historical Market Warehouse.

Provides persistent, microsecond-latency local columnar caching for:
  1. Intraday historical OHLCV bars (1m, 5m, 15m, 60m).
  2. Daily historical OHLCV bars.
  3. Historical derivative and expired F&O contract candles.

Architecture:
  - Columnar Apache Parquet storage with Snappy compression for maximum compression & vectorized I/O.
  - Delta synchronization: merges new candles with existing bars, deduplicates on timestamp, sorts chronologically.
  - Timezone Normalization: enforces timezone-naive DatetimeIndex (Invariant 13).
  - Multi-threaded batch ingestion from active broker (Fyers/AngelOne/Zerodha).
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import threading
from typing import Any, Optional

import pandas as pd

from config.paths import app_data_path

logger = logging.getLogger("chanakya.historical_warehouse")

# Thread lock for concurrent file operations per symbol/interval
_warehouse_lock = threading.Lock()


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


class HistoricalWarehouse:
    """
    Local Columnar Parquet Market Warehouse for high-speed quant backtesting & scanning.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or get_warehouse_dir()

    def _get_file_path(self, symbol: str, interval: str) -> Path:
        clean_sym = (
            symbol.upper()
            .replace("NSE:", "")
            .replace("BSE:", "")
            .replace("NFO:", "")
            .replace("MCX:", "")
            .replace("/", "_")
            .strip()
        )
        norm_inv = interval.lower().replace("minute", "m")
        folder = self.base_dir / norm_inv
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{clean_sym}.parquet"

    def save_bars(
        self,
        symbol: str,
        interval: str,
        df: pd.DataFrame,
        provider: str = "fyers",
    ) -> int:
        """
        Saves or merges OHLCV bars into the local parquet warehouse.
        Deduplicates on datetime index, sorts ascending, and writes atomically.

        Returns:
            int: Total count of bars persisted in the warehouse file.
        """
        if df is None or df.empty:
            return 0

        # Normalize column names to lowercase
        norm_df = df.copy()
        norm_df.columns = [str(c).lower() for c in norm_df.columns]

        # Ensure datetime index
        if "date" in norm_df.columns and not isinstance(norm_df.index, pd.DatetimeIndex):
            norm_df["date"] = pd.to_datetime(norm_df["date"])
            norm_df.set_index("date", inplace=True)

        if not isinstance(norm_df.index, pd.DatetimeIndex):
            norm_df.index = pd.to_datetime(norm_df.index)

        # Enforce timezone-naive index per Invariant 13: normalize to Asia/Kolkata first if tz-aware
        if norm_df.index.tz is not None:
            norm_df.index = norm_df.index.tz_convert("Asia/Kolkata").tz_localize(None)

        # Conditionally heal any unshifted UTC bars (hour < 9) to Asia/Kolkata (+5:30)
        norm_inv = str(interval).lower()
        if norm_inv not in ("day", "1d", "d", "week", "1w", "month", "1mo") and not norm_df.empty:
            mask = norm_df.index.hour < 9
            if mask.any():
                norm_df.index = norm_df.index.where(
                    ~mask, norm_df.index + pd.Timedelta(hours=5, minutes=30)
                )

        # Required columns
        for req in ("open", "high", "low", "close"):
            if req not in norm_df.columns:
                raise ValueError(f"Missing required OHLCV column '{req}' in dataframe")
        if "volume" not in norm_df.columns:
            norm_df["volume"] = 0

        keep_cols = [c for c in ("open", "high", "low", "close", "volume") if c in norm_df.columns]
        norm_df = norm_df[keep_cols]

        file_path = self._get_file_path(symbol, interval)

        with _warehouse_lock:
            if file_path.exists():
                try:
                    existing_df = pd.read_parquet(file_path)
                    if existing_df.index.tz is not None:
                        existing_df.index = existing_df.index.tz_convert(
                            "Asia/Kolkata"
                        ).tz_localize(None)
                    if (
                        norm_inv not in ("day", "1d", "d", "week", "1w", "month", "1mo")
                        and not existing_df.empty
                    ):
                        e_mask = existing_df.index.hour < 9
                        if e_mask.any():
                            existing_df.index = existing_df.index.where(
                                ~e_mask, existing_df.index + pd.Timedelta(hours=5, minutes=30)
                            )
                    # Combine existing and new bars, deduplicating on timestamp (preferring new data)
                    combined = pd.concat([existing_df, norm_df])
                    combined = combined[~combined.index.duplicated(keep="last")]
                    combined.sort_index(inplace=True)
                except Exception as e:
                    logger.warning(
                        f"[HistoricalWarehouse] Corrupted parquet read for {symbol}, overwriting: {e}"
                    )
                    combined = norm_df[~norm_df.index.duplicated(keep="last")].sort_index()
            else:
                combined = norm_df[~norm_df.index.duplicated(keep="last")].sort_index()

            # Atomic write via temp file
            temp_path = file_path.with_suffix(".tmp.parquet")
            combined.to_parquet(temp_path, compression="snappy")
            temp_path.replace(file_path)
            return len(combined)

    def load_bars(
        self,
        symbol: str,
        interval: str = "day",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        days: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Loads OHLCV bars from local parquet warehouse in < 5ms.

        Returns:
            pd.DataFrame: Sliced dataframe with timezone-naive DatetimeIndex, or empty DataFrame.
        """
        file_path = self._get_file_path(symbol, interval)
        if not file_path.exists():
            return pd.DataFrame()

        with _warehouse_lock:
            try:
                df = pd.read_parquet(file_path)
            except Exception as e:
                logger.debug(f"[HistoricalWarehouse] Error loading {file_path}: {e}")
                return pd.DataFrame()

        if df.empty:
            return df

        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)

        # Conditionally auto-heal legacy parquet files where intraday bars were written with raw UTC hours (< 9)
        norm_inv = str(interval).lower()
        if (
            norm_inv not in ("day", "1d", "d", "week", "1w", "month", "1mo", "1m_month")
            and not df.empty
        ):
            mask = df.index.hour < 9
            if mask.any():
                df.index = df.index.where(~mask, df.index + pd.Timedelta(hours=5, minutes=30))

        # Apply slicing
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
            # If dates don't align (e.g. historical data slice requested by days), return tail bars
            bars_to_take = min(
                len(df),
                max(10, days * (75 if interval.lower() not in ("day", "1d", "d") else 1)),
            )
            return df.iloc[-bars_to_take:].copy()

        return df.copy()

    def has_bars(self, symbol: str, interval: str = "day", min_bars: int = 10) -> bool:
        """Checks if a valid dataset exists locally for the given symbol and interval."""
        file_path = self._get_file_path(symbol, interval)
        if not file_path.exists():
            return False
        try:
            df = self.load_bars(symbol, interval=interval)
            return len(df) >= min_bars
        except Exception:
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
        """
        Synchronizes historical candles from the active data broker into the local warehouse.
        """
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
        """Concurrently syncs an entire list of symbols into the local warehouse."""
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
                    count = future.result()
                    results[sym] = count
                except Exception as e:
                    logger.debug(f"[HistoricalWarehouse] Error in sync task for {sym}: {e}")
                    results[sym] = 0
        return results

    def get_warehouse_stats(self) -> dict[str, Any]:
        """Returns storage metrics and inventory of the local warehouse."""
        stats = {
            "total_files": 0,
            "total_size_mb": 0.0,
            "intervals": {},
        }
        if not self.base_dir.exists():
            return stats

        total_bytes = 0
        for p in self.base_dir.rglob("*.parquet"):
            stats["total_files"] += 1
            sz = p.stat().st_size
            total_bytes += sz
            inv = p.parent.name
            stats["intervals"][inv] = stats["intervals"].get(inv, 0) + 1

        stats["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)
        return stats


# Global Singleton Instance
historical_warehouse = HistoricalWarehouse()
