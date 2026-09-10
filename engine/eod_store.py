"""
engine/eod_store.py
───────────────────
High-Performance Multi-Tier Local SQLite EOD Store & Bulk Ingestion Engine.

Provides persistent, zero-latency local caching of:
  1. Daily historical OHLCV bars for Indian equities (immutable past bars).
  2. Delta-only historical synchronization (only fetch missing bars from last_date).
  3. Persistent corporate fundamentals (PE, PB, ROE, ROCE, debt/equity, 30-day TTL).
  4. Persistent forensic accounting & governance audits (Beneish, Altman, Piotroski, 30-day TTL).
  5. Tier-1 L1 In-Memory process caching to minimize repeated SQLite disk hits.

Features:
  1. SQLite WAL mode for fast concurrent reads and atomic writes.
  2. Batch single-query reading: Load 500 stocks in <300ms (L2) or <0.01ms (L1).
  3. Precomputed metadata: 20-day median turnover (₹ Cr), 52-week High/Low, bar count.
  4. Delta-only syncing: Only downloads missing recent days (period='1mo' or '5d')
     instead of re-downloading 1-2 years of history for already-cached stocks.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Optional

import numpy as np
import pandas as pd

from config.paths import app_data_path

# SQLite Store Location
DEFAULT_EOD_DB_PATH = Path("data/eod_bars.db")
if not DEFAULT_EOD_DB_PATH.parent.exists():
    try:
        DEFAULT_EOD_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        DEFAULT_EOD_DB_PATH = app_data_path("eod_bars.db")

_store_lock = threading.Lock()
_local_connections: dict[int, sqlite3.Connection] = {}

# ── L1 In-Memory Process Caches ──────────────────────────────────────
_L1_MAX_ITEMS = 1500
_L1_TTL_SECONDS = 3600.0  # 1 hour
_l1_ohlcv_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_l1_fundamentals_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_l1_forensics_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_l1_lock = threading.Lock()


def _get_db_path() -> Path:
    p = os.environ.get("CHANAKYA_EOD_DB_PATH")
    if p:
        return Path(p)
    if os.environ.get("CHANAKYA_TESTING") == "1":
        test_dir = Path(os.environ.get("TRADING_PLATFORM_DATA", ".pytest_trading_platform"))
        test_dir.mkdir(parents=True, exist_ok=True)
        return test_dir / "test_eod_bars.db"
    return DEFAULT_EOD_DB_PATH


def _get_connection() -> sqlite3.Connection:
    """Thread-local SQLite connection with WAL journal mode."""
    tid = threading.get_ident()
    conn = _local_connections.get(tid)
    if conn is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # Set performance pragmas
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
        conn.execute("PRAGMA temp_store = MEMORY")
        _local_connections[tid] = conn
    return conn


def reset_store_connections() -> None:
    """Closes all cached connections and clears L1 caches (useful for testing or connection refresh)."""
    with _store_lock:
        for tid, conn in list(_local_connections.items()):
            try:
                conn.close()
            except Exception:
                pass
        _local_connections.clear()
    clear_l1_caches()


def init_eod_store() -> None:
    """Initializes tables and indexes in eod_bars.db."""
    with _store_lock:
        conn = _get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv_daily (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL,
                PRIMARY KEY (symbol, date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS symbol_meta (
                symbol TEXT PRIMARY KEY,
                last_date TEXT NOT NULL,
                first_date TEXT NOT NULL,
                bar_count INTEGER NOT NULL,
                median_turnover_20d REAL,
                high_52w REAL,
                low_52w REAL,
                last_close REAL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_fundamentals (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                pe REAL,
                pb REAL,
                roe REAL,
                roce REAL,
                npm REAL,
                sales_growth REAL,
                profit_growth REAL,
                debt_equity REAL,
                current_ratio REAL,
                interest_coverage REAL,
                free_cash_flow REAL,
                promoter_holding REAL,
                institutional_holding REAL,
                pledged_pct REAL,
                dividend_yield REAL,
                ev_ebitda REAL,
                market_cap REAL,
                sector TEXT,
                industry TEXT,
                raw_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS company_forensics (
                symbol TEXT PRIMARY KEY,
                beneish_m_score REAL,
                is_manipulator_risk INTEGER,
                altman_z_score REAL,
                distress_zone TEXT,
                piotroski_f_score INTEGER,
                quality_rating TEXT,
                overall_forensic_verdict TEXT,
                red_flags_json TEXT,
                strengths_json TEXT,
                summary_text TEXT,
                raw_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ohlcv_sym_date ON ohlcv_daily (symbol, date DESC)"
        )
        conn.commit()


# Auto-init schema on module load
init_eod_store()


def clear_l1_caches() -> None:
    """Flushes process L1 caches (useful for testing or manual refresh)."""
    with _l1_lock:
        _l1_ohlcv_cache.clear()
        _l1_fundamentals_cache.clear()
        _l1_forensics_cache.clear()


# ── Market Hours & Trading Calendar Helpers ─────────────────────────


def get_latest_expected_trading_date() -> str:
    """
    Returns the most recent completed or active trading date (YYYY-MM-DD).
    Account for IST market hours (09:15-15:30 IST) and weekends.
    """
    now_utc = datetime.now(timezone.utc)
    ist_now = now_utc + timedelta(hours=5, minutes=30)
    current_date = ist_now.date()

    # If weekend, rollback to Friday
    if ist_now.weekday() == 5:  # Saturday
        return (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
    elif ist_now.weekday() == 6:  # Sunday
        return (current_date - timedelta(days=2)).strftime("%Y-%m-%d")

    # If weekday before 16:00 IST (market close 15:30 + settlement buffer),
    # the previous completed trading day is the expected full EOD bar.
    if ist_now.time() < datetime.strptime("16:00", "%H:%M").time():
        if ist_now.weekday() == 0:  # Monday morning/intraday -> Friday
            return (current_date - timedelta(days=3)).strftime("%Y-%m-%d")
        else:
            return (current_date - timedelta(days=1)).strftime("%Y-%m-%d")

    return current_date.strftime("%Y-%m-%d")


# ── Reading & Writing OHLCV (Multi-Tier Caching) ──────────────────────


def get_cached_ohlcv(symbol: str, days: int = 300) -> Optional[pd.DataFrame]:
    """
    Loads daily OHLCV dataframe from L1 process memory (0.001ms) or local SQLite (<1 ms).
    """
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    now_ts = time.time()

    # Tier 1: Check L1 In-Memory Cache
    with _l1_lock:
        if clean_sym in _l1_ohlcv_cache:
            ts, df = _l1_ohlcv_cache[clean_sym]
            if now_ts - ts < _L1_TTL_SECONDS:
                if days and len(df) > days:
                    return df.iloc[-days:].copy()
                return df.copy()

    # Tier 2: Check SQLite Store
    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, volume, turnover 
        FROM ohlcv_daily 
        WHERE symbol = ? 
        ORDER BY date ASC
        """,
        (clean_sym,),
    ).fetchall()

    if not rows or len(rows) < 15:
        return None

    data = [dict(r) for r in rows]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df.index = df.index.tz_localize(None)

    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)
    if "turnover" in df.columns:
        df["turnover"] = df["turnover"].astype(float)

    # Populate L1 cache
    with _l1_lock:
        if len(_l1_ohlcv_cache) >= _L1_MAX_ITEMS:
            oldest_key = min(_l1_ohlcv_cache.keys(), key=lambda k: _l1_ohlcv_cache[k][0])
            _l1_ohlcv_cache.pop(oldest_key, None)
        _l1_ohlcv_cache[clean_sym] = (now_ts, df)

    if days and len(df) > days:
        df = df.iloc[-days:]

    return df


def get_cached_ohlcv_batch(symbols: list[str], days: int = 300) -> dict[str, pd.DataFrame]:
    """
    Loads daily OHLCV dataframes for a batch of symbols with L1 cache bypass and single SQL batch query.
    Extremely fast: 0.01ms if L1 hit, ~200ms for 500 stocks from SQLite.
    """
    if not symbols:
        return {}

    clean_map = {s.upper().replace(".NS", "").replace("NSE:", "").strip(): s for s in symbols}
    now_ts = time.time()
    results: dict[str, pd.DataFrame] = {}
    missing_syms: list[str] = []

    # Check Tier 1 (L1 In-Memory)
    with _l1_lock:
        for clean_sym, orig_sym in clean_map.items():
            if clean_sym in _l1_ohlcv_cache:
                ts, df = _l1_ohlcv_cache[clean_sym]
                if now_ts - ts < _L1_TTL_SECONDS:
                    sub_df = df.iloc[-days:].copy() if (days and len(df) > days) else df.copy()
                    results[orig_sym] = sub_df
                    continue
            missing_syms.append(clean_sym)

    if not missing_syms:
        return results

    # Query Tier 2 (SQLite) for missing symbols
    conn = _get_connection()
    chunk_size = 400
    newly_loaded: dict[str, pd.DataFrame] = {}

    for i in range(0, len(missing_syms), chunk_size):
        chunk = missing_syms[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"""
            SELECT symbol, date, open, high, low, close, volume, turnover 
            FROM ohlcv_daily 
            WHERE symbol IN ({placeholders}) 
            ORDER BY symbol, date ASC
            """,
            chunk,
        ).fetchall()

        if not rows:
            continue

        grouped: dict[str, list[dict]] = {}
        for r in rows:
            sym = r["symbol"]
            if sym not in grouped:
                grouped[sym] = []
            grouped[sym].append(
                {
                    "date": r["date"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                    "turnover": float(r["turnover"] or 0.0),
                }
            )

        for sym, bar_list in grouped.items():
            if len(bar_list) >= 15:
                df = pd.DataFrame(bar_list)
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                df.index = df.index.tz_localize(None)
                newly_loaded[sym] = df
                orig_key = clean_map.get(sym, sym)
                results[orig_key] = (
                    df.iloc[-days:].copy() if (days and len(df) > days) else df.copy()
                )

    # Populate L1 cache with newly loaded
    if newly_loaded:
        with _l1_lock:
            for sym, df in newly_loaded.items():
                if len(_l1_ohlcv_cache) >= _L1_MAX_ITEMS:
                    oldest_key = min(_l1_ohlcv_cache.keys(), key=lambda k: _l1_ohlcv_cache[k][0])
                    _l1_ohlcv_cache.pop(oldest_key, None)
                _l1_ohlcv_cache[sym] = (now_ts, df)

    return results


def get_symbol_meta(symbol: str) -> Optional[dict[str, Any]]:
    """Returns cached metadata for a symbol (turnover, 52w high/low, last close)."""
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM symbol_meta WHERE symbol = ?",
        (clean_sym,),
    ).fetchone()
    if row:
        return dict(row)
    return None


def get_all_symbol_meta() -> dict[str, dict[str, Any]]:
    """Returns metadata for all cached symbols."""
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM symbol_meta").fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def validate_and_sanitize_ohlcv_dataframe(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """
    Validates and sanitizes an OHLCV DataFrame to guarantee physical market envelope and data quality:
      1. Drops rows with null, NaN, or infinite price/volume values.
      2. Drops rows with zero or negative prices (open <= 0, high <= 0, low <= 0, close <= 0).
      3. Clamps and fixes physical envelope anomalies:
           high = max(high, open, close)
           low = min(low, open, close)
      4. Drops fatal invalid bars where high < low.
      5. Ensures volume is non-negative: volume = max(0, volume).
      6. Drops duplicate date timestamps (keeping the latest).
      7. Normalizes and sorts the DatetimeIndex ascending (timezone-naive).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    clean_df = df.copy()

    # Column name normalization
    if isinstance(clean_df.columns, pd.MultiIndex):
        clean_df.columns = [str(c[0]).lower() for c in clean_df.columns]
    else:
        clean_df.columns = [str(c).lower() for c in clean_df.columns]

    req_cols = ["open", "high", "low", "close", "volume"]
    if not all(col in clean_df.columns for col in req_cols):
        return pd.DataFrame(columns=req_cols)

    # Convert columns to numeric float / int
    for col in ["open", "high", "low", "close"]:
        clean_df[col] = pd.to_numeric(clean_df[col], errors="coerce")
    clean_df["volume"] = pd.to_numeric(clean_df["volume"], errors="coerce")
    if "turnover" in clean_df.columns:
        clean_df["turnover"] = pd.to_numeric(clean_df["turnover"], errors="coerce")

    # Drop NaNs / Infs
    clean_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    clean_df.dropna(subset=req_cols, inplace=True)

    if clean_df.empty:
        return pd.DataFrame(columns=req_cols)

    # Filter out zero or negative prices
    valid_mask = (
        (clean_df["open"] > 0)
        & (clean_df["high"] > 0)
        & (clean_df["low"] > 0)
        & (clean_df["close"] > 0)
    )
    clean_df = clean_df[valid_mask]
    if clean_df.empty:
        return pd.DataFrame(columns=req_cols)

    # Physical Envelope Enforcement:
    # High can never be lower than open or close; low can never be higher than open or close.
    clean_df["high"] = clean_df[["high", "open", "close"]].max(axis=1)
    clean_df["low"] = clean_df[["low", "open", "close"]].min(axis=1)

    # Reject any fatal inverted bars where high < low
    clean_df = clean_df[clean_df["high"] >= clean_df["low"]]

    # Volume non-negative
    clean_df["volume"] = clean_df["volume"].clip(lower=0)

    # Index normalization & deduplication
    if not isinstance(clean_df.index, pd.DatetimeIndex):
        clean_df.index = pd.to_datetime(clean_df.index)
    if hasattr(clean_df.index, "tz") and clean_df.index.tz is not None:
        clean_df.index = clean_df.index.tz_localize(None)

    clean_df = clean_df[~clean_df.index.duplicated(keep="last")]
    clean_df.sort_index(inplace=True)

    return clean_df


def repair_eod_store_anomalies(db_path: Optional[Path] = None) -> dict[str, Any]:
    """
    Scans the SQLite store for corrupted OHLC bars violating physical envelopes or with non-positive prices,
    repairs valid bars to the physical envelope, purges unfixable records, and recomputes symbol_meta.
    """
    target_path = db_path or _get_db_path()
    if not target_path.exists():
        return {"status": "NOT_FOUND", "repaired_bars": 0, "deleted_bars": 0, "symbols_updated": 0}

    with _store_lock:
        conn = sqlite3.connect(str(target_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            # 1. Delete rows with non-positive prices
            del_cur = conn.execute(
                """
                DELETE FROM ohlcv_daily 
                WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                """
            )
            deleted_count = del_cur.rowcount

            # 2. Find rows with physical envelope violations:
            # high < open OR high < close OR low > open OR low > close OR high < low
            rows = conn.execute(
                """
                SELECT symbol, date, open, high, low, close, volume 
                FROM ohlcv_daily 
                WHERE high < low 
                   OR high < open 
                   OR high < close 
                   OR low > open 
                   OR low > close
                """
            ).fetchall()

            repaired_count = 0
            affected_symbols = set()

            for r in rows:
                sym = r["symbol"]
                d_str = r["date"]
                o = float(r["open"])
                h = float(r["high"])
                l = float(r["low"])
                c = float(r["close"])

                new_high = max(float(h), float(o), float(c))
                new_low = min(float(l), float(o), float(c))

                conn.execute(
                    """
                    UPDATE ohlcv_daily 
                    SET high = ?, low = ? 
                    WHERE symbol = ? AND date = ?
                    """,
                    (float(new_high), float(new_low), sym, d_str),
                )
                repaired_count += 1
                affected_symbols.add(sym)

            # 3. Recompute symbol_meta for affected symbols
            now_iso = datetime.now(timezone.utc).isoformat()
            for sym in affected_symbols:
                recent_rows = conn.execute(
                    """
                    SELECT date, open, high, low, close, volume, turnover 
                    FROM ohlcv_daily 
                    WHERE symbol = ? 
                    ORDER BY date DESC LIMIT 260
                    """,
                    (sym,),
                ).fetchall()
                if not recent_rows:
                    continue

                recent_rows = list(reversed(recent_rows))
                bar_count_row = conn.execute(
                    "SELECT COUNT(*), MIN(date) FROM ohlcv_daily WHERE symbol = ?",
                    (sym,),
                ).fetchone()
                total_bar_count = bar_count_row[0]
                first_date = bar_count_row[1]
                last_date = recent_rows[-1]["date"]
                last_close = float(recent_rows[-1]["close"])

                lookback_52w = min(len(recent_rows), 250)
                high_52w = max(float(r["high"]) for r in recent_rows[-lookback_52w:])
                low_52w = min(float(r["low"]) for r in recent_rows[-lookback_52w:])

                lookback_20d = min(len(recent_rows), 20)
                turnover_vals = [
                    (float(r["close"]) * float(r["volume"])) / 1e7
                    for r in recent_rows[-lookback_20d:]
                ]
                median_turnover = float(np.median(turnover_vals)) if len(turnover_vals) > 0 else 0.0

                conn.execute(
                    """
                    INSERT OR REPLACE INTO symbol_meta
                    (symbol, last_date, first_date, bar_count, median_turnover_20d, 
                     high_52w, low_52w, last_close, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sym,
                        last_date,
                        first_date,
                        total_bar_count,
                        round(median_turnover, 3),
                        round(high_52w, 2),
                        round(low_52w, 2),
                        round(last_close, 2),
                        now_iso,
                    ),
                )

            conn.commit()
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception:
                pass
        finally:
            conn.close()

    clear_l1_caches()
    return {
        "status": "REPAIRED",
        "repaired_bars": repaired_count,
        "deleted_bars": deleted_count,
        "symbols_updated": len(affected_symbols),
    }


def save_ohlcv_batch(data: dict[str, pd.DataFrame]) -> int:
    """
    Atomically saves or updates OHLCV DataFrames in SQLite and recomputes metadata.
    Enforces physical market envelope validation and strict test symbol isolation.
    Handles delta appends seamlessly without corrupting historical bar counts or 52w extremes.
    Warms process L1 cache. Returns total number of bars inserted/updated.
    """
    if not data:
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    ohlcv_rows = []
    affected_symbols = set()

    for symbol, df in data.items():
        if df is None or len(df) == 0:
            continue

        clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
        # Guard: In production store, never save test symbols
        if _get_db_path() == DEFAULT_EOD_DB_PATH and (
            clean_sym.startswith("TEST") or clean_sym.startswith("DUMMY")
        ):
            continue

        # Ingestion Quality Gate: validate & sanitize
        sanitized_df = validate_and_sanitize_ohlcv_dataframe(df, symbol=clean_sym)
        if sanitized_df.empty:
            continue

        affected_symbols.add(clean_sym)

        for idx, row in sanitized_df.iterrows():
            d_str = str(idx)[:10]
            c = float(row["close"])
            v = int(row["volume"])
            to = float(row.get("turnover", (c * v) / 1e7))
            ohlcv_rows.append(
                (
                    clean_sym,
                    d_str,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    c,
                    v,
                    round(to, 4),
                )
            )

    if not ohlcv_rows:
        return 0

    with _store_lock:
        conn = _get_connection()
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO ohlcv_daily 
                (symbol, date, open, high, low, close, volume, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ohlcv_rows,
            )

            # Recompute metadata accurately for affected symbols
            meta_rows = []
            for sym in affected_symbols:
                recent_rows = conn.execute(
                    """
                    SELECT date, open, high, low, close, volume, turnover 
                    FROM ohlcv_daily 
                    WHERE symbol = ? 
                    ORDER BY date DESC LIMIT 260
                    """,
                    (sym,),
                ).fetchall()

                if not recent_rows:
                    continue

                recent_rows = list(reversed(recent_rows))
                bar_count_row = conn.execute(
                    "SELECT COUNT(*), MIN(date) FROM ohlcv_daily WHERE symbol = ?",
                    (sym,),
                ).fetchone()
                total_bar_count = bar_count_row[0]
                first_date = bar_count_row[1]
                last_date = recent_rows[-1]["date"]
                last_close = float(recent_rows[-1]["close"])

                # 52w high/low over recent 250 bars
                lookback_52w = min(len(recent_rows), 250)
                high_52w = max(float(r["high"]) for r in recent_rows[-lookback_52w:])
                low_52w = min(float(r["low"]) for r in recent_rows[-lookback_52w:])

                # 20d median turnover in ₹ Cr
                lookback_20d = min(len(recent_rows), 20)
                turnover_vals = [
                    (float(r["close"]) * float(r["volume"])) / 1e7
                    for r in recent_rows[-lookback_20d:]
                ]
                median_turnover = float(np.median(turnover_vals)) if len(turnover_vals) > 0 else 0.0

                meta_rows.append(
                    (
                        sym,
                        last_date,
                        first_date,
                        total_bar_count,
                        round(median_turnover, 3),
                        round(high_52w, 2),
                        round(low_52w, 2),
                        round(last_close, 2),
                        now_iso,
                    )
                )

            conn.executemany(
                """
                INSERT OR REPLACE INTO symbol_meta
                (symbol, last_date, first_date, bar_count, median_turnover_20d, 
                 high_52w, low_52w, last_close, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                meta_rows,
            )
            conn.commit()
            total_bars = len(ohlcv_rows)
        except Exception as e:
            conn.rollback()
            raise e

    # Invalidate or update L1 cache for affected symbols
    with _l1_lock:
        for sym in affected_symbols:
            _l1_ohlcv_cache.pop(sym, None)

    return total_bars


# ── Fundamentals & Forensic Accounting Local Store (30-Day Freshness) ────────


def save_fundamentals(symbol: str, data: dict[str, Any]) -> None:
    """Saves single company fundamental metrics to local SQLite store and L1 cache."""
    save_fundamentals_batch({symbol: data})


def save_fundamentals_batch(data_dict: dict[str, dict[str, Any]]) -> int:
    """Atomically saves fundamentals for a batch of stocks."""
    if not data_dict:
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()
    rows = []

    for sym, d in data_dict.items():
        if not d:
            continue
        clean_sym = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
        rows.append(
            (
                clean_sym,
                d.get("name") or "",
                d.get("pe"),
                d.get("pb"),
                d.get("roe"),
                d.get("roce"),
                d.get("npm"),
                d.get("sales_growth"),
                d.get("profit_growth"),
                d.get("debt_equity"),
                d.get("current_ratio"),
                d.get("interest_coverage"),
                d.get("free_cash_flow"),
                d.get("promoter_holding"),
                d.get("institutional_holding"),
                d.get("pledged_pct"),
                d.get("dividend_yield"),
                d.get("ev_ebitda"),
                d.get("market_cap"),
                d.get("sector") or "",
                d.get("industry") or "",
                json.dumps(d, default=str),
                now_iso,
            )
        )

    with _store_lock:
        conn = _get_connection()
        conn.executemany(
            """
            INSERT OR REPLACE INTO company_fundamentals
            (symbol, name, pe, pb, roe, roce, npm, sales_growth, profit_growth,
             debt_equity, current_ratio, interest_coverage, free_cash_flow,
             promoter_holding, institutional_holding, pledged_pct, dividend_yield,
             ev_ebitda, market_cap, sector, industry, raw_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    with _l1_lock:
        for sym, d in data_dict.items():
            clean_sym = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
            _l1_fundamentals_cache[clean_sym] = (now_ts, d)

    return len(rows)


def get_cached_fundamentals(symbol: str, max_age_days: int = 30) -> Optional[dict[str, Any]]:
    """Loads fundamentals for symbol if updated within max_age_days (default 30 days)."""
    batch = get_cached_fundamentals_batch([symbol], max_age_days=max_age_days)
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    return batch.get(clean_sym)


def get_cached_fundamentals_batch(
    symbols: list[str], max_age_days: int = 30
) -> dict[str, dict[str, Any]]:
    """Loads fundamentals for batch of symbols from L1 memory or local SQLite."""
    if not symbols:
        return {}

    clean_map = {s.upper().replace(".NS", "").replace("NSE:", "").strip(): s for s in symbols}
    now_ts = time.time()
    results: dict[str, dict[str, Any]] = {}
    missing_syms = []

    # L1 Check
    with _l1_lock:
        for clean_sym in clean_map.keys():
            if clean_sym in _l1_fundamentals_cache:
                ts, d = _l1_fundamentals_cache[clean_sym]
                if (now_ts - ts) < (max_age_days * 86400):
                    results[clean_sym] = d
                    continue
            missing_syms.append(clean_sym)

    if not missing_syms:
        return results

    conn = _get_connection()
    chunk_size = 400
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

    for i in range(0, len(missing_syms), chunk_size):
        chunk = missing_syms[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"""
            SELECT * FROM company_fundamentals 
            WHERE symbol IN ({placeholders}) AND updated_at >= ?
            """,
            [*chunk, cutoff_iso],
        ).fetchall()

        for r in rows:
            sym = r["symbol"]
            d = dict(r)
            if d.get("raw_json"):
                try:
                    raw = json.loads(d["raw_json"])
                    raw["updated_at"] = d["updated_at"]
                    results[sym] = raw
                    with _l1_lock:
                        _l1_fundamentals_cache[sym] = (now_ts, raw)
                    continue
                except Exception:
                    pass
            results[sym] = d
            with _l1_lock:
                _l1_fundamentals_cache[sym] = (now_ts, d)

    return results


def save_forensics(symbol: str, data: dict[str, Any]) -> None:
    """Saves forensic audit result for a stock."""
    save_forensics_batch({symbol: data})


def save_forensics_batch(data_dict: dict[str, dict[str, Any]]) -> int:
    """Atomically saves forensic audit results for a batch of stocks."""
    if not data_dict:
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()
    rows = []

    for sym, d in data_dict.items():
        if not d:
            continue
        clean_sym = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
        rows.append(
            (
                clean_sym,
                d.get("beneish_m_score"),
                1 if d.get("is_manipulator_risk") else 0,
                d.get("altman_z_score"),
                d.get("distress_zone") or "UNAVAILABLE",
                d.get("piotroski_f_score"),
                d.get("quality_rating") or "UNAVAILABLE",
                d.get("overall_forensic_verdict") or "UNAVAILABLE",
                json.dumps(d.get("governance_red_flags", [])),
                json.dumps(d.get("strengths", [])),
                d.get("summary_text") or "",
                json.dumps(d, default=str),
                now_iso,
            )
        )

    with _store_lock:
        conn = _get_connection()
        conn.executemany(
            """
            INSERT OR REPLACE INTO company_forensics
            (symbol, beneish_m_score, is_manipulator_risk, altman_z_score,
             distress_zone, piotroski_f_score, quality_rating, overall_forensic_verdict,
             red_flags_json, strengths_json, summary_text, raw_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    with _l1_lock:
        for sym, d in data_dict.items():
            clean_sym = sym.upper().replace(".NS", "").replace("NSE:", "").strip()
            _l1_forensics_cache[clean_sym] = (now_ts, d)

    return len(rows)


def get_cached_forensics(symbol: str, max_age_days: int = 30) -> Optional[dict[str, Any]]:
    """Loads forensic audit for symbol if updated within max_age_days."""
    batch = get_cached_forensics_batch([symbol], max_age_days=max_age_days)
    clean_sym = symbol.upper().replace(".NS", "").replace("NSE:", "").strip()
    return batch.get(clean_sym)


def get_cached_forensics_batch(
    symbols: list[str], max_age_days: int = 30
) -> dict[str, dict[str, Any]]:
    """Loads forensic audits for batch of symbols from L1 memory or local SQLite."""
    if not symbols:
        return {}

    clean_map = {s.upper().replace(".NS", "").replace("NSE:", "").strip(): s for s in symbols}
    now_ts = time.time()
    results: dict[str, dict[str, Any]] = {}
    missing_syms = []

    # L1 Check
    with _l1_lock:
        for clean_sym in clean_map.keys():
            if clean_sym in _l1_forensics_cache:
                ts, d = _l1_forensics_cache[clean_sym]
                if (now_ts - ts) < (max_age_days * 86400):
                    results[clean_sym] = d
                    continue
            missing_syms.append(clean_sym)

    if not missing_syms:
        return results

    conn = _get_connection()
    chunk_size = 400
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

    for i in range(0, len(missing_syms), chunk_size):
        chunk = missing_syms[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"""
            SELECT * FROM company_forensics 
            WHERE symbol IN ({placeholders}) AND updated_at >= ?
            """,
            [*chunk, cutoff_iso],
        ).fetchall()

        for r in rows:
            sym = r["symbol"]
            d = dict(r)
            if d.get("raw_json"):
                try:
                    raw = json.loads(d["raw_json"])
                    raw["updated_at"] = d["updated_at"]
                    results[sym] = raw
                    with _l1_lock:
                        _l1_forensics_cache[sym] = (now_ts, raw)
                    continue
                except Exception:
                    pass
            results[sym] = d
            with _l1_lock:
                _l1_forensics_cache[sym] = (now_ts, d)

    return results


# ── Bulk Ingestion & Delta Synchronizer ──────────────────────────────


def get_stale_symbols_detailed(
    symbols: list[str],
) -> tuple[list[str], list[str]]:
    """
    Classifies symbols into:
      1. new_symbols: never downloaded / missing from SQLite store (needs full 1y history).
      2. delta_symbols: present in SQLite store, but last_date < latest expected trading date.
    """
    clean_syms = [
        s.upper().replace(".NS", "").replace("NSE:", "").strip()
        for s in symbols
        if not s.upper().startswith("DUMMY")
    ]
    latest_expected = get_latest_expected_trading_date()

    conn = _get_connection()
    new_symbols = []
    delta_symbols = []

    chunk_size = 400
    cached_dates: dict[str, str] = {}
    for i in range(0, len(clean_syms), chunk_size):
        chunk = clean_syms[i : i + chunk_size]
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"SELECT symbol, last_date FROM symbol_meta WHERE symbol IN ({placeholders})",
            chunk,
        ).fetchall()
        for r in rows:
            cached_dates[r["symbol"]] = r["last_date"]

    for sym in clean_syms:
        last_d = cached_dates.get(sym)
        if not last_d:
            new_symbols.append(sym)
        elif last_d < latest_expected:
            delta_symbols.append(sym)

    return new_symbols, delta_symbols


def get_stale_symbols(symbols: list[str]) -> list[str]:
    """Returns combined list of new and stale symbols."""
    new_syms, delta_syms = get_stale_symbols_detailed(symbols)
    return new_syms + delta_syms


def _download_chunk_yfinance(
    chunk_symbols: list[str],
    period: str = "1mo",
    exchange: str = "NSE",
) -> dict[str, pd.DataFrame]:
    """Downloads a chunk of symbols via yfinance with specified period."""
    if not chunk_symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}

    suffix = ".NS" if exchange.upper() in ("NSE", "NFO") else ".BO"
    ticker_map = {f"{s}{suffix}": s for s in chunk_symbols}
    tickers_str = " ".join(ticker_map.keys())

    try:
        data = yf.download(
            tickers_str,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception:
        return {}

    if data is None or data.empty:
        return {}

    results: dict[str, pd.DataFrame] = {}

    if len(chunk_symbols) == 1:
        s = chunk_symbols[0]
        df = data.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if len(df) >= 1:
            results[s] = df
    else:
        for ticker, sym in ticker_map.items():
            try:
                if ticker in data.columns.levels[1]:
                    sub_df = data.xs(ticker, level=1, axis=1).copy()
                    sub_df.columns = [c.lower() for c in sub_df.columns]
                    sub_df = sub_df.dropna()
                    if len(sub_df) >= 1:
                        results[sym] = sub_df
            except Exception:
                pass

    return results


def sync_universe_eod(
    symbols: list[str],
    force: bool = False,
    chunk_size: int = 60,
    max_workers: int = 8,
    exchange: str = "NSE",
    delta_period: str = "1mo",
    initial_period: str = "2y",
    backfill_min_bars: Optional[int] = None,
) -> dict[str, Any]:
    """
    High-efficiency multi-threaded bulk synchronizer with delta-only ingestion.
    - If stocks are new (or bar_count < backfill_min_bars): downloads initial_period (default 2y / ~500 bars).
    - If stocks are delta (missing only recent bars): downloads delta_period='1mo' and appends.
    - If stocks are already up-to-date: returns in 0.001s without touching the network!
    """
    clean_syms = list(
        dict.fromkeys(
            [
                s.upper().replace(".NS", "").replace("NSE:", "").strip()
                for s in symbols
                if not s.upper().startswith("DUMMY")
            ]
        )
    )

    if force:
        new_targets = clean_syms
        delta_targets = []
    else:
        new_targets, delta_targets = get_stale_symbols_detailed(clean_syms)

        # If backfill_min_bars is requested, check if any existing cached symbols have fewer than min bars
        if backfill_min_bars and backfill_min_bars > 0 and clean_syms:
            conn = _get_connection()
            placeholders = ",".join(["?"] * len(clean_syms))
            low_bar_rows = conn.execute(
                f"SELECT symbol FROM symbol_meta WHERE symbol IN ({placeholders}) AND bar_count < ?",
                [*clean_syms, backfill_min_bars],
            ).fetchall()
            low_bar_syms = {r["symbol"] for r in low_bar_rows}
            if low_bar_syms:
                # Move from delta_targets to new_targets to fetch full initial_period (2y)
                delta_targets = [s for s in delta_targets if s not in low_bar_syms]
                for s in low_bar_syms:
                    if s not in new_targets:
                        new_targets.append(s)

    total_targets = len(new_targets) + len(delta_targets)
    if total_targets == 0:
        return {
            "status": "UP_TO_DATE",
            "total_requested": len(clean_syms),
            "synced_count": 0,
            "new_symbols_synced": 0,
            "delta_symbols_synced": 0,
            "already_cached": len(clean_syms),
            "message": "All requested symbols are already up-to-date in local EOD store.",
            "latest_trading_date": get_latest_expected_trading_date(),
        }

    downloaded: dict[str, pd.DataFrame] = {}

    # 1. Download Delta Chunks (fast period='1mo' or '5d')
    if delta_targets:
        delta_chunks = [
            delta_targets[i : i + chunk_size] for i in range(0, len(delta_targets), chunk_size)
        ]

        def _worker_delta(c):
            return _download_chunk_yfinance(c, period=delta_period, exchange=exchange)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_worker_delta, ch) for ch in delta_chunks]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res:
                    downloaded.update(res)

    # 2. Download New / Backfill Chunks (comprehensive initial_period='2y')
    if new_targets:
        new_chunks = [
            new_targets[i : i + chunk_size] for i in range(0, len(new_targets), chunk_size)
        ]

        def _worker_new(c):
            return _download_chunk_yfinance(c, period=initial_period, exchange=exchange)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_worker_new, ch) for ch in new_chunks]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res:
                    downloaded.update(res)

    # Save to SQLite and update symbol_meta accurately
    total_bars = save_ohlcv_batch(downloaded)

    return {
        "status": "SYNC_COMPLETE",
        "total_requested": len(clean_syms),
        "stale_found": total_targets,
        "new_targets_count": len(new_targets),
        "delta_targets_count": len(delta_targets),
        "synced_count": len(downloaded),
        "failed_count": total_targets - len(downloaded),
        "total_bars_saved": total_bars,
        "latest_trading_date": get_latest_expected_trading_date(),
    }


def get_store_statistics() -> dict[str, Any]:
    """
    Returns diagnostic status and health metrics for the local store.
    """
    conn = _get_connection()
    sym_count = conn.execute("SELECT COUNT(*) FROM symbol_meta").fetchone()[0]
    bar_count = conn.execute("SELECT COUNT(*) FROM ohlcv_daily").fetchone()[0]
    fund_count = conn.execute("SELECT COUNT(*) FROM company_fundamentals").fetchone()[0]
    forensic_count = conn.execute("SELECT COUNT(*) FROM company_forensics").fetchone()[0]

    last_update_row = conn.execute("SELECT MAX(updated_at) FROM symbol_meta").fetchone()
    last_update = last_update_row[0] if last_update_row and last_update_row[0] else None

    db_path = _get_db_path()
    size_mb = round(db_path.stat().st_size / (1024 * 1024), 2) if db_path.exists() else 0.0

    with _l1_lock:
        l1_ohlcv = len(_l1_ohlcv_cache)
        l1_fund = len(_l1_fundamentals_cache)
        l1_for = len(_l1_forensics_cache)

    return {
        "cached_symbols_count": sym_count,
        "total_bars_count": bar_count,
        "fundamentals_count": fund_count,
        "forensics_count": forensic_count,
        "db_size_mb": size_mb,
        "last_updated_at": last_update,
        "l1_cache": {
            "ohlcv_symbols": l1_ohlcv,
            "fundamentals": l1_fund,
            "forensics": l1_for,
        },
        "latest_expected_trading_date": get_latest_expected_trading_date(),
    }


# Convenience aliases for batch loading
get_ohlcv_batch = get_cached_ohlcv_batch
load_ohlcv_batch = get_cached_ohlcv_batch
