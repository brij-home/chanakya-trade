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
from pathlib import Path
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

            cal_path = Path.home() / ".trading_platform" / "calibration" / "index_calibration.json"
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
        cal_path = Path.home() / ".trading_platform" / "calibration" / "index_calibration.json"
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
