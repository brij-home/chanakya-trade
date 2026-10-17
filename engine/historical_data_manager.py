"""
engine/historical_data_manager.py
----------------------------------
Local Historical Data Manager for ChanakyaTrade Backtesting.

Purpose: Maintain a persistent local SQLite copy of 5-10 years of daily OHLCV
data for all NSE/BSE indices and stocks, eliminating repeated yfinance/broker
API hits during backtesting, scanning, and strategy optimization.

Architecture:
  - SINGLE WRITE AUTHORITY: all OHLCV writes go through engine.eod_store.save_ohlcv_batch()
    with physical envelope validation and WAL-mode SQLite.
  - L1 -> L2 -> Network: reads always check eod_store L1 (in-memory, <0.001ms),
    then L2 (SQLite, <1ms), then network only if truly missing.
  - Delta-Only Nightly Updates: only fetches bars that are genuinely missing since
    the last_date stored in symbol_meta -- never re-downloads history.
  - Chunked Parallel Download: ThreadPoolExecutor with configurable workers for
    the one-time 10y seed (yfinance group download is most efficient in chunks of 60).

Key API:
  seed_historical_data(symbols, period="10y")  - one-time bulk download
  nightly_delta_sync(symbols)                  - post-market delta append
  get_local_ohlcv(symbol, days)               - query local store (SSOT for backtests)
  audit_coverage(symbols)                      - per-symbol gap analysis
  get_store_health()                           - diagnostics
  seed_standard_universes(period="10y")        - convenience wrapper for all universes

AGENTS.md Invariants:
  - No hardcoded prices or synthetic data.
  - Returns explicit UNAVAILABLE dict (not raise) when data is missing.
  - Every exception is logged with full operational context.
  - Production store never accepts TEST/DUMMY symbols.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any

import pandas as pd

from engine.eod_store import (
    _clean_eod_symbol,
    _download_chunk_yfinance,
    _get_db_path,
    get_cached_ohlcv,
    get_cached_ohlcv_batch,
    get_latest_expected_trading_date,
    get_store_statistics,
    get_symbol_meta_batch,
    save_ohlcv_batch,
    sync_universe_eod,
)

logger = logging.getLogger(__name__)

# -- Constants ----------------------------------------------------------------

MIN_BARS_10Y = 2400
MIN_BARS_5Y = 1200
MIN_BARS_2Y = 480

YFINANCE_CHUNK_SIZE = 60
DEFAULT_WORKERS = 8

PERIOD_TO_DAYS: dict[str, int] = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "3y": 1095,
    "5y": 1825,
    "10y": 3650,
}

PERIOD_TO_MIN_BARS: dict[str, int] = {
    "1mo": 20,
    "3mo": 60,
    "6mo": 120,
    "1y": 240,
    "2y": 480,
    "3y": 720,
    "5y": 1200,
    "10y": 2400,
}


# -- Seed Historical Data -----------------------------------------------------


def seed_historical_data(
    symbols: list[str],
    period: str = "10y",
    exchange: str = "NSE",
    force: bool = False,
    n_workers: int = DEFAULT_WORKERS,
    chunk_size: int = YFINANCE_CHUNK_SIZE,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """
    One-time (or forced) bulk download of historical OHLCV for the given symbol list.

    - Checks which symbols genuinely need seeding (bar_count < min_bars for period).
    - Downloads in parallel chunks via yfinance group download.
    - Saves all data through eod_store.save_ohlcv_batch() with physical envelope validation.
    - Skips symbols that already have sufficient bars unless force=True.

    Returns:
        {
            "status": "SEED_COMPLETE" | "SEED_PARTIAL" | "UP_TO_DATE",
            "requested": int, "already_seeded": int, "downloaded": int,
            "failed": list[str], "total_bars_saved": int,
            "period": str, "elapsed_seconds": float,
        }
    """
    t0 = time.time()
    min_bars = PERIOD_TO_MIN_BARS.get(period, MIN_BARS_10Y)

    clean_syms = [_clean_eod_symbol(s) for s in symbols if s and not s.upper().startswith("DUMMY")]
    clean_syms = list(dict.fromkeys(clean_syms))

    if not clean_syms:
        return {
            "status": "UP_TO_DATE",
            "requested": 0,
            "already_seeded": 0,
            "downloaded": 0,
            "failed": [],
            "total_bars_saved": 0,
            "period": period,
            "elapsed_seconds": 0.0,
        }

    targets_to_seed: list[str] = []
    already_seeded: list[str] = []

    if force:
        targets_to_seed = clean_syms
    else:
        meta_map = get_symbol_meta_batch(clean_syms)
        for sym in clean_syms:
            meta = meta_map.get(sym)
            if meta and meta.get("bar_count", 0) >= min_bars:
                already_seeded.append(sym)
            else:
                targets_to_seed.append(sym)

    if not targets_to_seed:
        logger.info(
            f"[HistDataMgr] All {len(clean_syms)} symbols already seeded "
            f"({min_bars}+ bars for {period}). No download needed."
        )
        return {
            "status": "UP_TO_DATE",
            "requested": len(clean_syms),
            "already_seeded": len(already_seeded),
            "downloaded": 0,
            "failed": [],
            "total_bars_saved": 0,
            "period": period,
            "elapsed_seconds": round(time.time() - t0, 2),
        }

    logger.info(
        f"[HistDataMgr] Seeding {len(targets_to_seed)} symbols "
        f"(period={period}, workers={n_workers}, chunk={chunk_size}) ..."
    )

    chunks = [
        targets_to_seed[i : i + chunk_size] for i in range(0, len(targets_to_seed), chunk_size)
    ]
    failed: list[str] = []

    def _download_chunk(syms: list[str]) -> dict[str, pd.DataFrame]:
        try:
            result = _download_chunk_yfinance(syms, period=period, exchange=exchange)
            return result or {}
        except Exception as e:
            logger.warning(f"[HistDataMgr] Chunk download failed for {syms[:3]}...: {e}")
            return {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
        future_map = {executor.submit(_download_chunk, ch): ch for ch in chunks}
        total_bars = 0
        successful_count = 0
        done_count = 0
        for future in concurrent.futures.as_completed(future_map):
            chunk_syms = future_map[future]
            try:
                chunk_result = future.result()
                if chunk_result:
                    bars = save_ohlcv_batch(chunk_result)
                    total_bars += bars
                    successful_count += len(chunk_result)
                chunk_failed = [s for s in chunk_syms if s not in chunk_result]
                failed.extend(chunk_failed)
            except Exception as e:
                logger.error(
                    f"[HistDataMgr] Chunk future error for {chunk_syms[:3]}: {e}",
                    exc_info=True,
                )
                failed.extend(chunk_syms)
            done_count += len(chunk_syms)
            if progress_callback:
                try:
                    progress_callback(done_count, len(targets_to_seed))
                except Exception as e_suppressed:
                    logger.debug(
                        f"[engine.historical_data_manager] Non-fatal exception suppressed: {e_suppressed}"
                    )

    elapsed = round(time.time() - t0, 2)
    status = "SEED_COMPLETE" if not failed else "SEED_PARTIAL"
    logger.info(
        f"[HistDataMgr] Seed done in {elapsed}s -- "
        f"downloaded={successful_count}, failed={len(failed)}, bars={total_bars:,}"
    )
    return {
        "status": status,
        "requested": len(clean_syms),
        "already_seeded": len(already_seeded),
        "downloaded": successful_count,
        "failed": failed,
        "total_bars_saved": total_bars,
        "period": period,
        "elapsed_seconds": elapsed,
    }


# -- Nightly Delta Sync -------------------------------------------------------


def nightly_delta_sync(
    symbols: list[str],
    exchange: str = "NSE",
    n_workers: int = DEFAULT_WORKERS,
    force: bool = False,
) -> dict[str, Any]:
    """
    Post-market nightly sync -- appends ONLY the missing trading days since last_date.

    Delegates to eod_store.sync_universe_eod() which implements:
    - Staleness check via symbol_meta.last_date
    - delta_period="1mo" for fast incremental downloads
    - Chunked parallel ThreadPoolExecutor downloads
    - Atomic SQLite batch write with metadata recompute

    Should be called by DataSyncScheduler at 16:00 IST post-market close.
    """
    logger.info(
        f"[HistDataMgr] Nightly delta sync for {len(symbols)} symbols "
        f"(exchange={exchange}, force={force}) ..."
    )
    try:
        result = sync_universe_eod(
            symbols=symbols,
            force=force,
            chunk_size=YFINANCE_CHUNK_SIZE,
            max_workers=n_workers,
            exchange=exchange,
            delta_period="1mo",
            initial_period="2y",
            backfill_min_bars=500,
        )
        logger.info(f"[HistDataMgr] Delta sync complete: {result}")
        return result
    except Exception as e:
        logger.error(f"[HistDataMgr] Nightly delta sync failed: {e}", exc_info=True)
        return {"status": "FAILED", "error": str(e), "symbols_requested": len(symbols)}


# -- SSOT Query for Backtests -------------------------------------------------


def get_local_ohlcv(
    symbol: str,
    days: int = 2520,
    exchange: str = "NSE",
    auto_seed_if_missing: bool = False,
    period_if_seeding: str = "10y",
) -> pd.DataFrame | dict[str, str]:
    """
    SINGLE SOURCE OF TRUTH for OHLCV data during backtesting.

    Query priority:
      1. L1 in-memory cache (eod_store, <0.001ms)
      2. L2 SQLite local store (eod_store, <1ms)
      3. Auto-seed from yfinance if auto_seed_if_missing=True (network, ~5-15s)
      4. Returns {"status": "UNAVAILABLE", ...} if data cannot be obtained.

    Never returns hardcoded/synthetic prices. Status UNAVAILABLE is explicit.
    """
    clean_sym = _clean_eod_symbol(symbol)

    # Tier 1+2: Local Store
    df = get_cached_ohlcv(clean_sym, days=days)
    if df is not None and not df.empty and len(df) >= 15:
        return df

    # Tier 3: Auto-seed from network
    if auto_seed_if_missing:
        logger.info(
            f"[HistDataMgr] Local store miss for {clean_sym} -- auto-seeding "
            f"from network (period={period_if_seeding}) ..."
        )
        try:
            seed_result = seed_historical_data(
                symbols=[clean_sym],
                period=period_if_seeding,
                exchange=exchange,
                force=False,
            )
            if seed_result.get("downloaded", 0) > 0:
                df = get_cached_ohlcv(clean_sym, days=days)
                if df is not None and not df.empty:
                    return df
        except Exception as e:
            logger.warning(f"[HistDataMgr] Auto-seed failed for {clean_sym}: {e}")

    # Tier 4: UNAVAILABLE
    logger.warning(
        f"[HistDataMgr] OHLCV UNAVAILABLE for {clean_sym} "
        f"(days={days}, auto_seed={auto_seed_if_missing})"
    )
    return {
        "status": "UNAVAILABLE",
        "symbol": clean_sym,
        "exchange": exchange,
        "days_requested": days,
        "reason": (
            "No local historical data found. "
            "Run seed_historical_data([symbol]) to populate the local store."
        ),
    }


def get_local_ohlcv_batch(
    symbols: list[str],
    days: int = 2520,
) -> dict[str, pd.DataFrame]:
    """
    Batch query -- returns only symbols with valid local data.
    Missing symbols are excluded (caller should check coverage via audit_coverage()).
    """
    return get_cached_ohlcv_batch(symbols=symbols, days=days, copy=True)


# -- Coverage Audit -----------------------------------------------------------


def audit_coverage(
    symbols: list[str],
    required_bars: int = MIN_BARS_10Y,
) -> dict[str, Any]:
    """
    Audit local store coverage for a list of symbols.

    Returns per-symbol breakdown: FULL / PARTIAL / MISSING, bar_count, date range, gap.
    Use this before a universe-wide backtest to identify symbols needing re-seeding.
    """
    clean_map = {_clean_eod_symbol(s): s for s in symbols}
    meta_map = get_symbol_meta_batch(list(clean_map.keys()))

    result_symbols: dict[str, Any] = {}
    fully_covered = 0
    partial = 0
    missing = 0

    for clean_sym, orig_sym in clean_map.items():
        meta = meta_map.get(clean_sym)
        if not meta:
            result_symbols[orig_sym] = {
                "status": "MISSING",
                "bar_count": 0,
                "first_date": None,
                "last_date": None,
                "gap_bars": required_bars,
            }
            missing += 1
        else:
            bar_count = meta.get("bar_count", 0)
            if bar_count >= required_bars:
                status = "FULL"
                fully_covered += 1
            else:
                status = "PARTIAL"
                partial += 1
            result_symbols[orig_sym] = {
                "status": status,
                "bar_count": bar_count,
                "first_date": meta.get("first_date"),
                "last_date": meta.get("last_date"),
                "gap_bars": max(0, required_bars - bar_count),
            }

    total = len(clean_map)
    coverage_pct = round(fully_covered / total * 100, 1) if total > 0 else 0.0
    return {
        "total": total,
        "fully_covered": fully_covered,
        "partial": partial,
        "missing": missing,
        "coverage_pct": coverage_pct,
        "required_bars": required_bars,
        "symbols": result_symbols,
    }


# -- Store Health -------------------------------------------------------------


def get_store_health() -> dict[str, Any]:
    """
    Returns diagnostic status of the local historical data store:
    symbol count, total bars, DB size, last update, L1 cache state.
    """
    try:
        stats = get_store_statistics()
        return {
            "status": "HEALTHY",
            "db_path": str(_get_db_path()),
            "db_size_mb": stats.get("db_size_mb", 0.0),
            "cached_symbols": stats.get("cached_symbols_count", 0),
            "total_bars": stats.get("total_bars_count", 0),
            "fundamentals_cached": stats.get("fundamentals_count", 0),
            "forensics_cached": stats.get("forensics_count", 0),
            "last_updated_at": stats.get("last_updated_at"),
            "latest_expected_trading_date": get_latest_expected_trading_date(),
            "l1_cache": stats.get("l1_cache", {}),
        }
    except Exception as e:
        logger.error(f"[HistDataMgr] get_store_health failed: {e}", exc_info=True)
        return {"status": "UNAVAILABLE", "error": str(e)}


# -- Standard Universe Seed ---------------------------------------------------


def seed_standard_universes(
    period: str = "10y",
    force: bool = False,
    n_workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """
    Convenience function to seed all standard ChanakyaTrade universes in one call.

    Seeds (in order): NSE Indices, Nifty50, Nifty500, F&O Universe.

    Args:
        period:    History depth ("5y" or "10y"). Default "10y".
        force:     If True, re-seeds all even if already cached.
        n_workers: Parallel workers.
    """
    try:
        from analysis.universe import get_universe
    except Exception as e:
        logger.error(f"[HistDataMgr] Cannot import analysis.universe: {e}")
        return {"status": "FAILED", "error": str(e)}

    indices = [
        "NIFTY",
        "BANKNIFTY",
        "MIDCAP100",
        "SMALLCAP100",
        "NIFTYIT",
        "NIFTYPHARMA",
        "NIFTYFMCG",
        "NIFTYAUTO",
        "NIFTYBANK",
        "NIFTYMETAL",
        "NIFTYREALTY",
        "SENSEX",
    ]
    results: dict[str, Any] = {}

    logger.info(f"[HistDataMgr] Seeding {len(indices)} NSE indices (period={period}) ...")
    results["indices"] = seed_historical_data(
        symbols=indices,
        period=period,
        exchange="NSE",
        force=force,
        n_workers=n_workers,
    )

    for universe_key in ["NIFTY50", "NIFTY500", "FNO"]:
        try:
            syms = get_universe(universe_key)
            logger.info(f"[HistDataMgr] Seeding {len(syms)} {universe_key} stocks ...")
            results[universe_key.lower()] = seed_historical_data(
                symbols=syms,
                period=period,
                exchange="NSE",
                force=force,
                n_workers=n_workers,
            )
        except Exception as e:
            logger.warning(f"[HistDataMgr] {universe_key} seed failed: {e}")
            results[universe_key.lower()] = {"status": "FAILED", "error": str(e)}

    total_bars = sum(r.get("total_bars_saved", 0) for r in results.values() if isinstance(r, dict))
    logger.info(
        f"[HistDataMgr] Standard universe seed complete -- "
        f"total_bars={total_bars:,} across {len(results)} universes"
    )
    results["_summary"] = {
        "total_bars_saved": total_bars,
        "period": period,
        "universes_seeded": [k for k in results if not k.startswith("_")],
    }
    return results
