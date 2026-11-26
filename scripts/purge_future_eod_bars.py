"""
scripts/purge_future_eod_bars.py
─────────────────────────────────
Explicit administrative remediation script to purge future-dated (> today IST)
corrupted rows from `data/eod_bars.db` (`ohlcv_daily` / `symbol_meta`) and
the Parquet `warehouse/day/` store.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

from config.constants import IST_ZONE as IST
from config.paths import app_data_path
from engine.eod_store import DEFAULT_EOD_DB_PATH, clear_l1_caches


def purge_future_bars(cutoff_date: str | None = None) -> dict[str, int]:
    today_str = cutoff_date or datetime.now(IST).strftime("%Y-%m-%d")
    today_ts = pd.Timestamp(today_str)

    deleted_db_rows = 0
    recomputed_meta = 0
    if DEFAULT_EOD_DB_PATH.exists():
        conn = sqlite3.connect(str(DEFAULT_EOD_DB_PATH), timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            affected = [
                r["symbol"]
                for r in conn.execute(
                    "SELECT DISTINCT symbol FROM ohlcv_daily WHERE date > ?", (today_str,)
                ).fetchall()
            ]
            cur = conn.execute("DELETE FROM ohlcv_daily WHERE date > ?", (today_str,))
            deleted_db_rows = cur.rowcount

            # Also check any symbol_meta pointing into the future even if ohlcv_daily had no rows left
            meta_fut = [
                r["symbol"]
                for r in conn.execute(
                    "SELECT symbol FROM symbol_meta WHERE last_date > ?", (today_str,)
                ).fetchall()
            ]
            for s in set(affected) | set(meta_fut):
                rows = conn.execute(
                    "SELECT date, open, high, low, close, volume FROM ohlcv_daily WHERE symbol = ? ORDER BY date DESC LIMIT 260",
                    (s,),
                ).fetchall()
                if not rows:
                    conn.execute("DELETE FROM symbol_meta WHERE symbol = ?", (s,))
                else:
                    rows = list(reversed(rows))
                    agg = conn.execute(
                        "SELECT COUNT(*), MIN(date) FROM ohlcv_daily WHERE symbol = ?", (s,)
                    ).fetchone()
                    look_52 = rows[-250:]
                    look_20 = rows[-20:]
                    turn = [(float(r["close"]) * float(r["volume"])) / 1e7 for r in look_20]
                    med_t = float(np.median(turn)) if turn else 0.0
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO symbol_meta
                        (symbol, last_date, first_date, bar_count, median_turnover_20d, high_52w, low_52w, last_close, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            s,
                            rows[-1]["date"],
                            agg[1],
                            agg[0],
                            round(med_t, 3),
                            round(max(float(r["high"]) for r in look_52), 2),
                            round(min(float(r["low"]) for r in look_52), 2),
                            round(float(rows[-1]["close"]), 2),
                            datetime.now(IST).isoformat(),
                        ),
                    )
                recomputed_meta += 1
            conn.commit()
        finally:
            conn.close()
        clear_l1_caches()

    # Clean parquet files under warehouse/day/
    cleaned_parquets = 0
    dropped_parquet_rows = 0
    wh_day = app_data_path("warehouse") / "day"
    if wh_day.exists():
        for pq in wh_day.rglob("*.parquet"):
            try:
                df = pd.read_parquet(pq)
                if df.empty or not isinstance(df.index, pd.DatetimeIndex):
                    continue
                idx_norm = (
                    df.index.tz_localize(None).normalize()
                    if df.index.tz is not None
                    else df.index.normalize()
                )
                fut_mask = idx_norm > today_ts
                if fut_mask.any():
                    dropped_parquet_rows += int(fut_mask.sum())
                    cleaned_df = df[~fut_mask]
                    tmp_path = pq.with_name(f".{pq.name}.{os.getpid()}.tmp")
                    cleaned_df.to_parquet(tmp_path)
                    os.replace(tmp_path, pq)
                    cleaned_parquets += 1
            except Exception as e:
                print(f"[purge_future_eod_bars] Skipped {pq}: {e}")

    return {
        "cutoff_date": today_str,
        "deleted_db_rows": deleted_db_rows,
        "recomputed_meta": recomputed_meta,
        "cleaned_parquets": cleaned_parquets,
        "dropped_parquet_rows": dropped_parquet_rows,
    }


if __name__ == "__main__":
    print(purge_future_bars())
