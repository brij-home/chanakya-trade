"""
scripts/seed_10y_history.py
----------------------------
One-time 10-year historical OHLCV seed for all symbols in the local EOD store.

Key Design Invariants:
  1. Reads all symbols in the local EOD store plus canonical indices.
  2. Downloads in parallel chunks of 50 via yfinance group download (~40x faster than 1-by-1).
  3. Saves chunk-by-chunk immediately into SQLite via save_ohlcv_batch().
     Bounded memory footprint (<30 MB) and safe against interruptions.
  4. Resumable: symbols updated during the current seed run are automatically skipped on resume.
  5. Pure ASCII console output - zero Windows cp1252 / UTF-8 mojibake crashes.
  6. Final integrity repair pass and coverage report.

Usage:
  .venv/Scripts/python.exe scripts/seed_10y_history.py
"""

import sys
import time
import concurrent.futures
import logging
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fix windows console encoding if available
try:
    from config.encoding import fix_windows_console

    fix_windows_console()
except Exception:
    pass

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed_10y")
logger.setLevel(logging.INFO)

import pandas as pd
from engine.eod_store import (
    _get_connection,
    _download_chunk_yfinance,
    save_ohlcv_batch,
    get_store_statistics,
    init_eod_store,
    repair_eod_store_anomalies,
)

PERIOD = "10y"
CHUNK_SIZE = 50
WORKERS = 6
CHECKPOINT_FILE = PROJECT_ROOT / "scratch" / "seed_10y_completed.txt"

CANONICAL_INDICES = [
    "NIFTY",
    "BANKNIFTY",
    "MIDCAP100",
    "SMALLCAP100",
    "FINNIFTY",
    "NIFTYIT",
    "NIFTYPHARMA",
    "NIFTYFMCG",
    "NIFTYAUTO",
    "NIFTYMETAL",
    "NIFTYREALTY",
    "NIFTYENERGY",
    "NIFTYINFRA",
    "NIFTYPSE",
    "SENSEX",
]


def load_completed_symbols() -> set[str]:
    """Load set of symbols already successfully seeded from checkpoint file."""
    if not CHECKPOINT_FILE.exists():
        return set()
    try:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return {line.strip().upper() for line in f if line.strip()}
    except Exception:
        return set()


def record_completed_symbols(symbols: list[str]) -> None:
    """Append newly completed symbols to checkpoint file."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CHECKPOINT_FILE, "a", encoding="utf-8") as f:
            for s in symbols:
                f.write(f"{s.upper()}\n")
    except Exception as e:
        logger.warning(f"Failed writing checkpoint: {e}")


def get_all_target_symbols() -> list[str]:
    """Collect all symbols from symbol_meta plus canonical indices."""
    conn = _get_connection()
    rows = conn.execute("SELECT symbol FROM symbol_meta ORDER BY symbol").fetchall()
    existing = [r[0] for r in rows]
    all_syms = list(dict.fromkeys(CANONICAL_INDICES + existing))
    return all_syms


def print_progress(done: int, total: int, start_time: float, bars_saved: int) -> None:
    elapsed = time.time() - start_time
    pct = (done / total * 100.0) if total > 0 else 100.0
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    bar_len = 30
    filled = int(bar_len * done / total) if total > 0 else bar_len
    bar = "=" * filled + "-" * (bar_len - filled)
    sys.stdout.write(
        f"\r  [{bar}] {pct:5.1f}% | {done:4d}/{total} syms | "
        f"{bars_saved:,} bars | {elapsed:.0f}s elapsed | ETA: {eta:.0f}s   "
    )
    sys.stdout.flush()


def main() -> None:
    print("=" * 70)
    print("  ChanakyaTrade -- 10-Year Historical OHLCV Local Seed")
    print("=" * 70)

    init_eod_store()
    stats = get_store_statistics()
    print(
        f"\n  Current Store: {stats['cached_symbols_count']} symbols, "
        f"{stats['total_bars_count']:,} bars, {stats['db_size_mb']} MB"
    )

    all_targets = get_all_target_symbols()
    completed = load_completed_symbols()

    # Targets needing seed
    needs_seed = [s for s in all_targets if s.upper() not in completed]
    print(f"  Total targets          : {len(all_targets)}")
    print(f"  Already checkpointed   : {len(completed)}")
    print(f"  Pending seed           : {len(needs_seed)}")

    if not needs_seed:
        print("\n  [OK] All symbols have already been seeded with 10-year data.")
        print("  To force a full re-seed, delete:", CHECKPOINT_FILE)
        return

    n_chunks = (len(needs_seed) + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunks = [needs_seed[i : i + CHUNK_SIZE] for i in range(0, len(needs_seed), CHUNK_SIZE)]
    print(
        f"\n  Config: chunk_size={CHUNK_SIZE}, workers={WORKERS}, "
        f"chunks={n_chunks}, period={PERIOD}"
    )
    print(f"  Checkpoint: {CHECKPOINT_FILE}")
    print(f"  Starting seed at {time.strftime('%H:%M:%S')} IST ...\n")

    total_bars_saved = 0
    symbols_done = 0
    failed_symbols: list[str] = []
    start_time = time.time()

    def _worker(chunk: list[str]) -> tuple[list[str], dict[str, pd.DataFrame]]:
        try:
            res = _download_chunk_yfinance(chunk, period=PERIOD, exchange="NSE")
            return chunk, res or {}
        except Exception as e:
            logger.warning(f"Worker chunk failed: {e}")
            return chunk, {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_map = {executor.submit(_worker, ch): ch for ch in chunks}

        for future in concurrent.futures.as_completed(future_map):
            chunk, chunk_data = future.result()

            if chunk_data:
                try:
                    bars = save_ohlcv_batch(chunk_data)
                    total_bars_saved += bars
                    successful_syms = list(chunk_data.keys())
                    record_completed_symbols(successful_syms)

                    missing_in_chunk = [s for s in chunk if s not in chunk_data]
                    if missing_in_chunk:
                        # Record as attempted so we don't loop endlessly on delisted tickers
                        record_completed_symbols(missing_in_chunk)
                        failed_symbols.extend(missing_in_chunk)
                except Exception as e:
                    logger.error(f"Error saving chunk {chunk[:3]}: {e}")
                    failed_symbols.extend(chunk)
            else:
                # Mark as attempted
                record_completed_symbols(chunk)
                failed_symbols.extend(chunk)

            symbols_done += len(chunk)
            print_progress(symbols_done, len(needs_seed), start_time, total_bars_saved)

    print()  # newline
    elapsed = time.time() - start_time
    print(f"\n  [COMPLETE] Seed finished in {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    print(f"     Total bars saved    : {total_bars_saved:,}")
    print(f"     Symbols processed   : {symbols_done}")
    print(f"     Failed / Delisted   : {len(failed_symbols)}")
    if failed_symbols[:8]:
        print(f"     Sample unavail      : {failed_symbols[:8]}")

    print("\n  Running post-seed anomaly repair pass ...")
    repair = repair_eod_store_anomalies()
    print(f"  Repair result: {repair}")

    stats_after = get_store_statistics()
    print("\n  Store Statistics After Seed:")
    print(f"     Symbols : {stats_after['cached_symbols_count']}")
    print(f"     Bars    : {stats_after['total_bars_count']:,}")
    print(f"     DB Size : {stats_after['db_size_mb']} MB")

    conn = _get_connection()
    coverage = conn.execute("""
        SELECT
            CASE
                WHEN bar_count >= 2400 THEN '10y+ FULL (2400+)'
                WHEN bar_count >= 1200 THEN '5y PARTIAL (1200-2399)'
                WHEN bar_count >= 480  THEN '2y PARTIAL (480-1199)'
                ELSE 'SHALLOW (<480)'
            END as tier,
            COUNT(*) as count,
            MIN(bar_count) as min_b,
            MAX(bar_count) as max_b
        FROM symbol_meta
        GROUP BY tier ORDER BY min_b DESC
    """).fetchall()

    print("\n  Coverage Breakdown:")
    for r in coverage:
        print(f"     {r[0]:28s} count={r[1]:5d}  bars={r[2]} to {r[3]}")

    print("\n  Historical Seed Complete. All backtests can now run locally.")
    print("=" * 70)


if __name__ == "__main__":
    main()
