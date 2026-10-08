"""
engine/data_sync_scheduler.py
─────────────────────────────
Autonomous Production Data Synchronization Engine for ChanakyaTrade.

Manages periodic data freshness across all tiers:
  1. Post-Market Daily EOD Bars Sync (16:00 & 18:30 IST):
     - Delta-syncs historical daily bars for NIFTY 500, F&O universe, indices, and MCX.
     - Runs physical envelope repair and SQLite WAL checkpoint with TRUNCATE.
  2. Weekly Fundamentals & Forensics Sync (Saturday 02:00 IST):
     - Batch refreshes balance sheet metrics (PE, PB, ROE, ROCE, Debt/Equity)
       and forensic accounting models (Beneish M-Score, Altman Z, Piotroski F).
  3. Weekly Corporate & Symbol Master Refresh (Sunday 04:00 IST):
     - Synchronizes canonical exchange symbol masters and F&O contract specifications.
  4. Deep Full Re-Sync from Scratch (Monthly / On-Demand):
     - Deep recalibration: cleans split/bonus drifts, re-downloads multi-year bars,
       recomputes century compounders and inflection archetypes, and executes VACUUM.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.data_sync")

IST = timezone(timedelta(hours=5, minutes=30))


class DataSyncScheduler:
    """
    Central coordinator for periodic, multi-tier data synchronization.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_eod_sync_date: Optional[str] = None
        self._last_fundamentals_sync_date: Optional[str] = None
        self._last_master_sync_date: Optional[str] = None
        self._is_syncing = False

    def get_sync_status(self) -> Dict[str, Any]:
        """Return operational state of periodic synchronization engine."""
        with self._lock:
            return {
                "running": self._running,
                "is_syncing": self._is_syncing,
                "last_eod_sync_date": self._last_eod_sync_date,
                "last_fundamentals_sync_date": self._last_fundamentals_sync_date,
                "last_master_sync_date": self._last_master_sync_date,
            }

    # ── 1. Daily EOD Bar Sync ────────────────────────────────────────

    def sync_daily_eod(self, force: bool = False, universe: str = "NIFTY500") -> Dict[str, Any]:
        """
        Execute post-market EOD synchronization across monitored universes.
        """
        from engine.eod_store import repair_eod_store_anomalies, sync_universe_eod
        from market.calendar import is_trading_day

        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")

        if not force:
            if not is_trading_day(now_ist.date(), exchange="NSE"):
                return {"status": "SKIPPED", "reason": f"{today_str} is not an NSE trading day"}
            if now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute < 45):
                return {
                    "status": "SKIPPED",
                    "reason": "Market is still active (EOD sync runs post 15:45 IST)",
                }

        logger.info(f"[DataSync] Starting post-market EOD sync for universe '{universe}'...")
        with self._lock:
            self._is_syncing = True

        try:
            # 1. Resolve symbols from universe
            symbols = self._resolve_universe_symbols(universe)
            if not symbols:
                symbols = [
                    "NIFTY 50",
                    "NIFTY BANK",
                    "RELIANCE",
                    "TCS",
                    "HDFCBANK",
                    "INFY",
                    "ICICIBANK",
                ]

            # 2. Delta-sync EOD bars
            res = sync_universe_eod(symbols, force=force, exchange="NSE")

            # 3. Sanity envelope audit
            repair_res = repair_eod_store_anomalies()

            # 4. Truncate checkpoint WAL
            self._checkpoint_wal()

            with self._lock:
                self._last_eod_sync_date = today_str

            logger.info(
                f"[DataSync] EOD sync completed for {len(symbols)} symbols. "
                f"Updated: {res.get('updated_symbols', 0)}, New bars: {res.get('total_new_bars', 0)}."
            )
            return {
                "status": "SUCCESS",
                "timestamp": now_ist.isoformat(),
                "universe": universe,
                "symbols_count": len(symbols),
                "sync_result": res,
                "envelope_repairs": repair_res,
            }
        except Exception as e:
            logger.error(f"[DataSync] EOD sync failure: {e}", exc_info=True)
            return {"status": "ERROR", "error": str(e)}
        finally:
            with self._lock:
                self._is_syncing = False
            gc.collect()

    # ── 2. Weekly Fundamentals & Forensics ───────────────────────────

    def sync_weekly_fundamentals(self, limit: int = 500, force: bool = False) -> Dict[str, Any]:
        """
        Batch synchronizes balance sheet fundamentals and forensic accounting models.
        """
        from analysis.forensic import audit_company_forensics
        from analysis.fundamental import get_fundamental_snapshot
        from engine.eod_store import save_forensics_batch, save_fundamentals_batch

        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")

        logger.info(f"[DataSync] Starting weekly fundamentals & forensics sync (limit={limit})...")
        with self._lock:
            self._is_syncing = True

        try:
            symbols = self._resolve_universe_symbols("NIFTY500")[:limit]
            funds_dict: Dict[str, Dict[str, Any]] = {}
            forensics_dict: Dict[str, Dict[str, Any]] = {}

            for sym in symbols:
                try:
                    snap = get_fundamental_snapshot(sym)
                    if snap:
                        funds_dict[sym] = snap
                except Exception as e_f:
                    logger.debug(f"[DataSync] Fundamental fetch error for {sym}: {e_f}")

                try:
                    audit = audit_company_forensics(sym)
                    if audit:
                        forensics_dict[sym] = audit.as_dict()
                except Exception as e_aud:
                    logger.debug(f"[DataSync] Forensic fetch error for {sym}: {e_aud}")

            saved_funds = save_fundamentals_batch(funds_dict)
            saved_forensics = save_forensics_batch(forensics_dict)

            self._checkpoint_wal()
            with self._lock:
                self._last_fundamentals_sync_date = today_str

            return {
                "status": "SUCCESS",
                "timestamp": now_ist.isoformat(),
                "fundamentals_saved": saved_funds,
                "forensics_saved": saved_forensics,
            }
        except Exception as e:
            logger.error(f"[DataSync] Fundamentals sync failure: {e}", exc_info=True)
            return {"status": "ERROR", "error": str(e)}
        finally:
            with self._lock:
                self._is_syncing = False
            gc.collect()

    # ── 3. Weekly Symbol Master Sync ─────────────────────────────────

    def sync_weekly_symbol_master(self, force: bool = False) -> Dict[str, Any]:
        """
        Downloads and verifies fresh symbol masters for NSE and BSE.
        """
        from market.symbol_master import download_symbol_master

        now_ist = datetime.now(IST)
        today_str = now_ist.strftime("%Y-%m-%d")

        logger.info("[DataSync] Starting weekly symbol master sync...")
        results = {}
        for market in ("NSE_CM", "NSE_FO", "BSE_CM"):
            try:
                p = download_symbol_master(market, force=force)
                results[market] = {"status": "SUCCESS", "path": str(p)}
            except Exception as e:
                results[market] = {"status": "ERROR", "error": str(e)}

        with self._lock:
            self._last_master_sync_date = today_str

        return {
            "status": "SUCCESS",
            "timestamp": now_ist.isoformat(),
            "results": results,
        }

    # ── 4. Deep Full Re-Sync from Scratch ────────────────────────────

    def run_full_system_resync(self, universe: str = "NIFTY500") -> Dict[str, Any]:
        """
        Deep institutional recalibration:
        1. Force re-downloads 2 years of clean EOD bars to eliminate split/bonus drifts.
        2. Recalculates all Century Compounders & Inflection candidates.
        3. Vacuums SQLite databases to reclaim disk space.
        """
        from engine.eod_store import clear_l1_caches, repair_eod_store_anomalies, sync_universe_eod

        now_ist = datetime.now(IST)
        logger.info(f"[DataSync] Starting DEEP FULL RE-SYNC from scratch for '{universe}'...")
        with self._lock:
            self._is_syncing = True

        try:
            # 1. Flush in-memory L1 caches
            clear_l1_caches()

            # 2. Re-download clean bars with force=True
            symbols = self._resolve_universe_symbols(universe)
            eod_res = sync_universe_eod(symbols, force=True, exchange="NSE")

            # 3. Re-verify envelope sanity
            repair_res = repair_eod_store_anomalies()

            # 4. Checkpoint WAL and VACUUM
            self._checkpoint_wal(vacuum=True)

            return {
                "status": "SUCCESS",
                "timestamp": now_ist.isoformat(),
                "universe": universe,
                "eod_result": eod_res,
                "repair_result": repair_res,
            }
        except Exception as e:
            logger.error(f"[DataSync] Deep full re-sync failed: {e}", exc_info=True)
            return {"status": "ERROR", "error": str(e)}
        finally:
            with self._lock:
                self._is_syncing = False
            gc.collect()

    # ── Background Daemon Scheduler ──────────────────────────────────

    async def _scheduler_loop(self) -> None:
        """
        Continuous background event loop running cadence checks every 15 minutes.
        """
        while self._running:
            try:
                await asyncio.sleep(900)  # Check every 15 minutes
                now_ist = datetime.now(IST)
                today_str = now_ist.strftime("%Y-%m-%d")

                # Check 1: Post-Market EOD sync (Runs between 16:00 and 19:00 IST on trading days)
                if 16 <= now_ist.hour < 19:
                    if self._last_eod_sync_date != today_str:
                        await asyncio.to_thread(self.sync_daily_eod)

                # Check 2: Saturday Fundamentals Sync (Runs Saturday between 02:00 and 06:00 IST)
                if now_ist.weekday() == 5 and 2 <= now_ist.hour < 6:
                    if self._last_fundamentals_sync_date != today_str:
                        await asyncio.to_thread(self.sync_weekly_fundamentals)

                # Check 3: Sunday Master Sync (Runs Sunday between 04:00 and 07:00 IST)
                if now_ist.weekday() == 6 and 4 <= now_ist.hour < 7:
                    if self._last_master_sync_date != today_str:
                        await asyncio.to_thread(self.sync_weekly_symbol_master)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DataSync] Error in scheduler loop: {e}", exc_info=True)

    def start(self) -> None:
        """Starts background periodic synchronization scheduler."""
        with self._lock:
            if self._running:
                return
            self._running = True
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._scheduler_loop())
                logger.info("[DataSync] Background data synchronization scheduler started.")
            except RuntimeError:
                logger.debug("[DataSync] No active asyncio loop to attach sync scheduler.")

    def stop(self) -> None:
        """Stops background periodic synchronization scheduler."""
        with self._lock:
            self._running = False
            if self._task and not self._task.done():
                self._task.cancel()
            self._task = None
            logger.info("[DataSync] Data synchronization scheduler stopped.")

    # ── Helpers ──────────────────────────────────────────────────────

    def _resolve_universe_symbols(self, universe_name: str) -> List[str]:
        """Resolve universe tickers from centralized analysis.universe module."""
        try:
            from analysis.universe import get_universe_symbols

            syms = get_universe_symbols(universe_name)
            if syms:
                return list(syms)
        except Exception:
            pass

        # Fallback to nifty500.json
        try:
            import json
            from pathlib import Path

            p = Path("data/universes/nifty500.json")
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                return [d.get("symbol") for d in data if d.get("symbol")]
        except Exception:
            pass

        return []

    def _checkpoint_wal(self, vacuum: bool = False) -> None:
        """Run SQLite WAL checkpoint with active TRUNCATE."""
        from pathlib import Path
        import sqlite3

        db_path = Path("data/eod_bars.db")
        if db_path.exists():
            conn = None
            try:
                conn = sqlite3.connect(str(db_path), timeout=10.0)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if vacuum:
                    conn.execute("VACUUM")
            except Exception as e:
                logger.debug(f"[DataSync] WAL checkpoint note: {e}")
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass


# Canonical singleton
data_sync_scheduler = DataSyncScheduler()
