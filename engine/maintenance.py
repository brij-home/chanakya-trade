"""
engine/maintenance.py
─────────────────────
Central Production-Grade Storage Maintenance & Purge Engine for ChanakyaTrade.

Enforces institutional storage quotas tailored for a 100 GB SSD environment:
  - Target total storage footprint: < 10 GB (keeping 90+ GB free for SSD health & wear-leveling).
  - Tier A (Business Data): Permanent / strictly retained (orders, audit logs, accounts, journal).
  - Tier B (EOD & Models): 90-180 days retention (eod_snapshots, persona track records).
  - Tier C (Analytical Cache): 7-14 days retention (AI analyses, macro snapshots, FTS search index).
  - Tier D (Ephemeral & Diagnostics): 3-7 days retention (raw market ticks, disk JSON cache, rotated logs).
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.paths import app_data_dir, app_data_path

logger = logging.getLogger(__name__)


@dataclass
class StorageBreakdown:
    business_data_mb: float
    market_data_mb: float
    analysis_cache_mb: float
    disk_cache_mb: float
    telemetry_mb: float
    total_app_data_mb: float
    free_ssd_gb: float
    total_ssd_gb: float

    def to_dict(self) -> dict:
        return {
            "business_data_mb": round(self.business_data_mb, 2),
            "market_data_mb": round(self.market_data_mb, 2),
            "analysis_cache_mb": round(self.analysis_cache_mb, 2),
            "disk_cache_mb": round(self.disk_cache_mb, 2),
            "telemetry_mb": round(self.telemetry_mb, 2),
            "total_app_data_mb": round(self.total_app_data_mb, 2),
            "free_ssd_gb": round(self.free_ssd_gb, 2),
            "total_ssd_gb": round(self.total_ssd_gb, 2),
        }


@dataclass
class MaintenanceReport:
    timestamp: str
    actions_taken: List[str]
    items_deleted: int
    bytes_reclaimed: int
    before_breakdown: StorageBreakdown
    after_breakdown: StorageBreakdown

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "actions_taken": self.actions_taken,
            "items_deleted": self.items_deleted,
            "bytes_reclaimed": self.bytes_reclaimed,
            "reclaimed_mb": round(self.bytes_reclaimed / (1024 * 1024), 2),
            "storage_before": self.before_breakdown.to_dict(),
            "storage_after": self.after_breakdown.to_dict(),
        }


def _file_or_dir_size_bytes(path: Path) -> int:
    """Return total bytes for a file or directory tree."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += Path(root, f).stat().st_size
            except Exception:
                pass
    return total


def get_storage_breakdown() -> StorageBreakdown:
    """Analyze current storage allocation across tiers and SSD free space."""
    root = app_data_dir()
    
    # Business files
    business_files = [
        root / "orders.db",
        root / "audit.db",
        root / "users.db",
        root / "risk_limits.db",
        root / "paper_portfolio.json",
        root / "trade_journal.json",
        root / "trade_memory.json",
    ]
    b_bytes = sum(_file_or_dir_size_bytes(f) for f in business_files)

    # Market data
    m_bytes = _file_or_dir_size_bytes(root / "market_data.db") + _file_or_dir_size_bytes(root / "persona_track_records.db")

    # Analysis Cache
    ac_bytes = _file_or_dir_size_bytes(root / "analysis_cache.db") + _file_or_dir_size_bytes(root / "analysis_search.db")

    # Disk Cache JSON files
    dc_bytes = _file_or_dir_size_bytes(root / "cache")

    # Telemetry and logs
    t_bytes = _file_or_dir_size_bytes(root / "telemetry")

    total_bytes = _file_or_dir_size_bytes(root)

    # Free SSD space
    try:
        usage = shutil.disk_usage(root)
        free_ssd_gb = usage.free / (1024 ** 3)
        total_ssd_gb = usage.total / (1024 ** 3)
    except Exception:
        free_ssd_gb = 0.0
        total_ssd_gb = 0.0

    return StorageBreakdown(
        business_data_mb=b_bytes / (1024 * 1024),
        market_data_mb=m_bytes / (1024 * 1024),
        analysis_cache_mb=ac_bytes / (1024 * 1024),
        disk_cache_mb=dc_bytes / (1024 * 1024),
        telemetry_mb=t_bytes / (1024 * 1024),
        total_app_data_mb=total_bytes / (1024 * 1024),
        free_ssd_gb=free_ssd_gb,
        total_ssd_gb=total_ssd_gb,
    )


def run_maintenance_purge(
    raw_tick_retention_days: int = 7,
    disk_cache_retention_days: int = 7,
    export_retention_days: int = 14,
    vacuum_databases: bool = False,
) -> MaintenanceReport:
    """
    Execute institutional purge policy across ephemeral data while preserving business data.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    before_breakdown = get_storage_breakdown()
    actions: List[str] = []
    items_deleted = 0

    # 1. Tier D: Purge raw market ticks (high write churn)
    try:
        from market.tick_store import prune_tick_archive

        deleted_ticks = prune_tick_archive(retention_days=raw_tick_retention_days, max_rows=250_000)
        if deleted_ticks > 0:
            actions.append(f"Pruned {deleted_ticks} ephemeral market ticks older than {raw_tick_retention_days} days.")
            items_deleted += deleted_ticks
    except Exception as e:
        logger.warning(f"Error pruning market ticks: {e}")

    # 2. Tier D: Prune JSON disk cache files
    try:
        from market.disk_cache import prune_disk_cache

        deleted_files = prune_disk_cache(max_age_days=disk_cache_retention_days, max_total_mb=150.0)
        if deleted_files > 0:
            actions.append(f"Purged {deleted_files} stale OHLCV JSON cache files from ~/.trading_platform/cache/.")
            items_deleted += deleted_files
    except Exception as e:
        logger.warning(f"Error pruning disk cache: {e}")

    # 3. Tier C: Prune expired AI analysis & macro entries
    try:
        from engine.analysis_cache import analysis_cache

        deleted_analyses = analysis_cache.prune()
        if deleted_analyses > 0:
            actions.append(f"Pruned {deleted_analyses} expired AI multi-agent & macro analyses from analysis_cache.db.")
            items_deleted += deleted_analyses
    except Exception as e:
        logger.warning(f"Error pruning analysis cache: {e}")

    # 4. Tier D: Prune old exported PDFs & reports
    try:
        exports_dir = app_data_path("exports")
        if exports_dir.exists():
            cutoff = (now - timedelta(days=export_retention_days)).timestamp()
            deleted_exports = 0
            for f in exports_dir.glob("*"):
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    deleted_exports += 1
            if deleted_exports > 0:
                actions.append(f"Purged {deleted_exports} exported reports older than {export_retention_days} days.")
                items_deleted += deleted_exports
    except Exception as e:
        logger.warning(f"Error pruning exports: {e}")

    # 5. Checkpoint WAL logs for SQLite databases
    databases = [
        app_data_path("orders.db"),
        app_data_path("audit.db"),
        app_data_path("users.db"),
        app_data_path("market_data.db"),
        app_data_path("analysis_cache.db"),
        app_data_path("analysis_search.db"),
    ]

    for db_file in databases:
        if db_file.exists():
            conn = None
            try:
                conn = sqlite3.connect(str(db_file), timeout=10.0)
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                if vacuum_databases:
                    conn.execute("VACUUM")
            except Exception:
                pass
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    after_breakdown = get_storage_breakdown()
    bytes_reclaimed = max(
        0,
        int((before_breakdown.total_app_data_mb - after_breakdown.total_app_data_mb) * 1024 * 1024),
    )

    if not actions:
        actions.append("All storage tiers within retention quotas. No purge required.")

    report = MaintenanceReport(
        timestamp=timestamp,
        actions_taken=actions,
        items_deleted=items_deleted,
        bytes_reclaimed=bytes_reclaimed,
        before_breakdown=before_breakdown,
        after_breakdown=after_breakdown,
    )
    return report
