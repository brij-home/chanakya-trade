"""
market/disk_cache.py
────────────────────
Simple JSON disk cache for market data (holdings, positions, OHLCV).

Used as a last-resort fallback when all live data sources fail.
Cache files are stored in ~/.trading_platform/cache/.

Usage:
    from market.disk_cache import save_cache, load_cache

    save_cache("holdings", [{"symbol": "INFY", "qty": 10}])
    data, cached_at = load_cache("holdings")
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config.paths import app_data_path

DEFAULT_CACHE_DIR = app_data_path("cache")


def _cache_file(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.json"


def prune_disk_cache(
    cache_dir: Optional[Path] = None,
    max_age_days: int = 7,
    max_total_mb: float = 200.0,
) -> int:
    """
    Purge stale disk cache JSON files and enforce directory size ceiling.
    Returns the number of deleted files.
    """
    target_dir = cache_dir or DEFAULT_CACHE_DIR
    if not target_dir.exists():
        return 0

    deleted_count = 0
    now = datetime.now()
    cutoff_time = (now - timedelta(days=max_age_days)).timestamp()

    try:
        files = list(target_dir.glob("*.json"))
        # 1. Delete files older than max_age_days
        remaining = []
        for f in files:
            try:
                stat = f.stat()
                if stat.st_mtime < cutoff_time:
                    f.unlink(missing_ok=True)
                    deleted_count += 1
                else:
                    remaining.append((f, stat.st_size, stat.st_mtime))
            except Exception:
                pass

        # 2. Check total size and prune oldest if exceeding max_total_mb
        total_bytes = sum(size for _, size, _ in remaining)
        max_bytes = max_total_mb * 1024 * 1024

        if total_bytes > max_bytes:
            # Sort by modification time ascending (oldest first)
            remaining.sort(key=lambda x: x[2])
            for f, size, _ in remaining:
                try:
                    f.unlink(missing_ok=True)
                    deleted_count += 1
                    total_bytes -= size
                    if total_bytes <= max_bytes:
                        break
                except Exception:
                    pass
    except Exception:
        pass

    return deleted_count


def save_cache(key: str, data: list, cache_dir: Optional[Path] = None) -> None:
    """
    Save data to disk cache with automated directory pruning.

    Args:
        key:       Cache key (e.g. "holdings", "positions", "ohlcv_INFY")
        data:      List of dicts to cache
        cache_dir: Override default cache directory (for testing)
    """
    target_dir = cache_dir or DEFAULT_CACHE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "saved_at": datetime.now().isoformat(),
        "data": data,
    }
    try:
        _cache_file(key, target_dir).write_text(json.dumps(payload, default=str))
    except Exception:
        pass  # Cache write failure is never fatal

    # Periodic prune trigger
    try:
        prune_disk_cache(target_dir)
    except Exception:
        pass


def load_cache(key: str, cache_dir: Optional[Path] = None) -> tuple[list, Optional[datetime]]:
    """
    Load data from disk cache.

    Returns:
        (data, cached_at) — cached_at is None if no cache exists or is corrupt.
        Returns ([], None) when cache is missing or unreadable.
    """
    target_dir = cache_dir or DEFAULT_CACHE_DIR
    path = _cache_file(key, target_dir)

    if not path.exists():
        return [], None

    try:
        payload = json.loads(path.read_text())
        cached_at = datetime.fromisoformat(payload["saved_at"])
        return payload["data"], cached_at
    except Exception:
        return [], None

