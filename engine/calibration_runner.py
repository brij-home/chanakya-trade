"""
engine/calibration_runner.py
────────────────────────────
Thread-safe background execution and lifecycle manager for 95-day Fyers
historical walk-forward model calibration.

Provides:
  - Non-blocking asynchronous calibration triggering (Rule 24).
  - Mutex lock preventing concurrent / race calibration runs.
  - State tracking: IDLE, RUNNING, COMPLETED, FAILED.
  - Staleness detection (auto-trigger when calibration is older than 24 hours or from prior date).
  - Integration across FastAPI sidecar, Telegram bot, and AutoAlertEngine.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("chanakya.calibration_runner")
IST = ZoneInfo("Asia/Kolkata")


@dataclass
class CalibrationStatus:
    state: str = "IDLE"  # "IDLE" | "RUNNING" | "COMPLETED" | "FAILED"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_run: Optional[str] = None
    last_error: Optional[str] = None
    metrics_summary: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CalibrationRunner:
    """Manages asynchronous calibration lifecycle with thread-safe execution lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = CalibrationStatus()
        self._thread: Optional[threading.Thread] = None

    def get_status(self) -> CalibrationStatus:
        """Returns the current calibration status."""
        with self._lock:
            # If idle and calibration artifact exists on disk, load its metadata
            if self._status.state == "IDLE" and not self._status.last_run:
                self._load_disk_metadata()
            return CalibrationStatus(**asdict(self._status))

    def _load_disk_metadata(self) -> None:
        """Reads metadata from index_calibration.json if present."""
        try:
            import json

            from config.paths import app_data_path

            cal_path = app_data_path("calibration", "index_calibration.json")
            if cal_path.exists():
                with open(cal_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._status.last_run = data.get("generated_at")
                self._status.metrics_summary = {
                    "version": data.get("version"),
                    "indices_count": len(data.get("indices", {})),
                    "fno_stocks_count": len(data.get("fno_stocks", {})),
                    "coiling_squeezes_count": len(data.get("fno_coiling_squeezes", [])),
                }
        except Exception as e:
            logger.debug(f"[CalibrationRunner] Could not load disk metadata: {e}")

    def is_calibration_stale(self, max_age_hours: float = 24.0) -> bool:
        """
        Determines whether the stored calibration is stale.
        Returns True if the file does not exist, was generated > max_age_hours ago,
        or was generated on a calendar date prior to today.
        """
        from config.paths import app_data_path

        cal_path = app_data_path("calibration", "index_calibration.json")
        if not cal_path.exists():
            return True

        try:
            import json

            with open(cal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            gen_str = data.get("generated_at", "")
            if not gen_str:
                return True

            now_ist = datetime.now(IST)
            clean_gen = gen_str.replace(" IST", "").strip()
            gen_dt = datetime.strptime(clean_gen, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)

            age_hours = (now_ist - gen_dt).total_seconds() / 3600.0
            if age_hours > max_age_hours:
                return True

            # Check calendar date freshness: if today is a new trading day, prior date calibration is stale
            if gen_dt.date() < now_ist.date():
                return True

            return False
        except Exception as exc:
            logger.debug(f"[CalibrationRunner] Error checking staleness: {exc}")
            return True

    def trigger_calibration_async(self, force: bool = False) -> tuple[bool, str]:
        """
        Launches full walk-forward calibration in a background daemon thread.
        Returns (success, message).
        """
        with self._lock:
            if self._status.state == "RUNNING":
                return False, "Calibration is already currently executing in background."

            self._status.state = "RUNNING"
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
            self._status.started_at = now_str
            self._status.last_error = None

            self._thread = threading.Thread(
                target=self._worker_run,
                name="FyersModelCalibrationWorker",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"[CalibrationRunner] Background calibration initiated at {now_str}")
            return True, f"Calibration started in background at {now_str}."

    def _collect_options_replay_diagnostics(self) -> dict[str, Any]:
        """Run research-only purged walk-forward tournament, meta-model fit, IV backfill & compaction."""
        try:
            from engine.detector_tournament import (
                run_multi_profile_tournament,
                save_tournament_report,
            )
            from engine.historical_warehouse import historical_warehouse
            from engine.iv_surface import build_iv_surface_from_warehouse
            from engine.meta_labeler import save_meta_model, train_purged_meta_model
            from engine.tick_warehouse import get_tick_warehouse

            target_universe = [
                "NIFTY",
                "BANKNIFTY",
                "SENSEX",
                "MIDCPNIFTY",
                "RELIANCE",
                "HDFCBANK",
                "ICICIBANK",
                "INFY",
                "TCS",
                "SBIN",
                "AXISBANK",
                "LT",
                "BHARTIARTL",
                "BAJFINANCE",
                "CRUDEOIL",
                "NATURALGAS",
                "GOLD",
                "SILVER",
            ]
            bars_by_sym: dict[str, Any] = {}
            daily_bars_by_sym: dict[str, Any] = {}
            for sym in target_universe:
                df_5m = historical_warehouse.load_bars(sym, interval="5m")
                if df_5m is not None and not df_5m.empty and len(df_5m) >= 60:
                    bars_by_sym[sym] = df_5m
                    try:
                        daily_bars_by_sym[sym] = (
                            df_5m.resample("D")
                            .agg(
                                {
                                    "open": "first",
                                    "high": "max",
                                    "low": "min",
                                    "close": "last",
                                    "volume": "sum",
                                }
                            )
                            .dropna()
                        )
                    except Exception as e_bar:
                        logger.debug(f"[CalibrationRunner] Bar resample skipped for {sym}: {e_bar}")

            if not bars_by_sym:
                return {"status": "UNCALIBRATED", "reason": "INSUFFICIENT_WAREHOUSE_BARS"}

            report = run_multi_profile_tournament(bars_by_sym, collect_meta_samples=True)
            meta_samples = report.pop("meta_samples", [])
            save_tournament_report(report)

            meta_model = train_purged_meta_model(meta_samples)
            save_meta_model(meta_model)

            # Backfill constant-tenor IV surface records across archived TickWarehouse chain partitions
            iv_updated = 0
            compacted_segments = 0
            wh = get_tick_warehouse()
            stats = wh.get_storage_stats()
            parts = stats.get("date_partitions", [])
            for part_name in parts:
                d_str = part_name.replace("date=", "")
                oc_root = wh._get_partition_path(d_str) / "option_chains"
                if oc_root.exists():
                    for sym_dir in oc_root.iterdir():
                        if sym_dir.is_dir():
                            snap = build_iv_surface_from_warehouse(
                                sym_dir.name,
                                ohlcv_daily=daily_bars_by_sym.get(sym_dir.name),
                                date_str=d_str,
                                persist=True,
                            )
                            if snap.status == "AVAILABLE":
                                iv_updated += 1

            # Backfill historical constant-tenor BS IV observations from Fyers active monthly options
            # if iv_daily_surface depth is < 25 sessions (strictly preserves live chain records).
            fyers_iv_backfilled = 0
            try:
                import os as _os
                from brokers.session import get_data_broker
                from engine.iv_history_backfill import backfill_priority_iv_universe
                from engine.iv_surface import load_historical_30d_ivs
                from market.calendar import is_market_open

                allow_intraday_bf = (
                    _os.environ.get("CHANAKYA_ALLOW_INTRADAY_BACKFILL", "").strip() == "1"
                )
                if (not (is_market_open("NFO") or is_market_open("NSE"))) or allow_intraday_bf:
                    brk = get_data_broker()
                    if brk is not None and getattr(brk, "has_token", lambda: False)():
                        if any(
                            len(load_historical_30d_ivs(s)) < 25
                            for s in ("NIFTY", "BANKNIFTY", "SENSEX")
                        ):
                            bf_res = backfill_priority_iv_universe(
                                [
                                    "NIFTY",
                                    "BANKNIFTY",
                                    "SENSEX",
                                    "RELIANCE",
                                    "HDFCBANK",
                                    "ICICIBANK",
                                ],
                                broker=brk,
                                lookback_days=90,
                                target_min_sessions=25,
                            )
                            fyers_iv_backfilled = int(bf_res.get("total_persisted") or 0)
                else:
                    logger.info(
                        "[CalibrationRunner] Skipping historical BS IV backfill during peak NSE/NFO session."
                    )
            except Exception as exc_bf:
                logger.debug(f"[CalibrationRunner] Historical BS IV backfill skipped: {exc_bf}")

            # Compact segments bounded in background so CalibrationRunner never blocks >20s
            try:
                from engine.pipeline.universe_scheduler import background_task_runner

                def _compact_async() -> None:
                    for pn in parts:
                        wh.compact_all_symbols(date_str=pn.replace("date=", ""))

                background_task_runner.submit("wh-compact-partitions", _compact_async)
            except Exception as e_cmp_sub:
                logger.debug(
                    f"[CalibrationRunner] Background compaction submit skipped: {e_cmp_sub}"
                )

            summary = {
                det: {
                    "status": info.get("status"),
                    "governance": info.get("governance"),
                    "trades": info.get("trades"),
                    "net_expectancy_r": info.get("net_expectancy_r"),
                }
                for det, info in (report.get("detectors") or {}).items()
            }
            return {
                "status": "COMPLETED",
                "provenance": "RESEARCH_ONLY_PURGED_WALK_FORWARD",
                "symbols_count": len(bars_by_sym),
                "detectors": summary,
                "meta_model": {
                    "status": meta_model.status,
                    "sample_count": meta_model.sample_count,
                    "win_count": meta_model.win_count,
                    "loss_count": meta_model.loss_count,
                    "oos_brier_score": meta_model.oos_brier_score,
                },
                "iv_snapshots_persisted": iv_updated + fyers_iv_backfilled,
                "fyers_iv_backfilled": fyers_iv_backfilled,
                "tick_segments_compacted": compacted_segments,
            }
        except Exception as exc_rep:
            logger.debug(f"[CalibrationRunner] Options replay diagnostics skipped: {exc_rep}")
            return {"status": "UNCALIBRATED", "reason": str(exc_rep)}

    def _worker_run(self) -> None:
        """Worker thread executing the 90-day calibration steps."""
        try:
            from scripts.calibrate_fyers_historical_models import (
                calibrate_fno_stocks,
                calibrate_index_parameters,
                compute_tod_volume_profile,
                save_calibration_payload,
                sync_historical_index_data,
            )

            sync_historical_index_data(days=90)
            tod_curve = compute_tod_volume_profile()
            index_metrics = calibrate_index_parameters()
            fno_metrics, coiling_squeezes = calibrate_fno_stocks()
            out_file = save_calibration_payload(
                tod_curve, index_metrics, fno_metrics, coiling_squeezes
            )
            replay_diag = self._collect_options_replay_diagnostics()

            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
            with self._lock:
                self._status.state = "COMPLETED"
                self._status.completed_at = now_str
                self._status.last_run = now_str
                self._status.last_error = None
                self._status.metrics_summary = {
                    "output_file": str(out_file),
                    "indices_count": len(index_metrics),
                    "fno_stocks_count": len(fno_metrics),
                    "coiling_squeezes_count": len(coiling_squeezes),
                    "options_replay": replay_diag,
                }
            logger.info(
                f"[CalibrationRunner] Calibration completed successfully at {now_str}: "
                f"{len(index_metrics)} indices, {len(fno_metrics)} F&O stocks, {len(coiling_squeezes)} coilers."
            )
        except Exception as exc:
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
            with self._lock:
                self._status.state = "FAILED"
                self._status.completed_at = now_str
                self._status.last_error = str(exc)
            logger.error(f"[CalibrationRunner] Calibration failed: {exc}", exc_info=True)

    def auto_trigger_premarket_calibration(self) -> bool:
        """
        Checks if calibration is stale and automatically triggers background run.
        Safe to call during pre-market loops (08:45–09:14 IST).
        """
        if self.is_calibration_stale():
            logger.info(
                "[CalibrationRunner] Calibration is stale/missing; auto-triggering background calibration."
            )
            success, _ = self.trigger_calibration_async()
            return success
        return False


# Global singleton instance
calibration_runner = CalibrationRunner()
