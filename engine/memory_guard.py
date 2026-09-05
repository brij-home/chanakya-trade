"""
engine/memory_guard.py
──────────────────────
Institutional Memory Guard & Resource Sentinel for ChanakyaTrade.

Tailored for laptop environments with 8 GB RAM DDR4-3200:
  - System budget: Windows OS (~3.8 GB) + Chromium/Electron (~1.5 GB) = ~5.3 GB.
  - ChanakyaTrade target: < 1.2 GB RSS.
  - Soft threshold: Process RSS > 1.2 GB or Available System Memory < 600 MB.
  - Proactively triggers cache trimming, DataFrame eviction, and garbage collection.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Registered cache purge callbacks
_trim_callbacks: List[Callable[[], int]] = []
_callbacks_lock = threading.Lock()


@dataclass
class MemoryStatus:
    total_ram_mb: float
    available_ram_mb: float
    used_ram_pct: float
    process_rss_mb: float
    pressure_level: str  # "NORMAL", "MODERATE", "CRITICAL"
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "total_ram_mb": round(self.total_ram_mb, 1),
            "available_ram_mb": round(self.available_ram_mb, 1),
            "used_ram_pct": round(self.used_ram_pct, 1),
            "process_rss_mb": round(self.process_rss_mb, 1),
            "pressure_level": self.pressure_level,
            "recommendation": self.recommendation,
        }


def register_trim_callback(callback: Callable[[], int]) -> None:
    """Register a callable that frees in-memory caches and returns count of items evicted."""
    with _callbacks_lock:
        if callback not in _trim_callbacks:
            _trim_callbacks.append(callback)


def unregister_trim_callback(callback: Callable[[], int]) -> None:
    """Remove a previously registered cache trim callback."""
    with _callbacks_lock:
        if callback in _trim_callbacks:
            _trim_callbacks.remove(callback)


def _get_process_rss_mb() -> float:
    """Return current process RSS memory in MB."""
    # 1. Try psutil if available
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    # 2. Windows ctypes fallback
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / (1024 * 1024)
        except Exception:
            pass

    return 0.0


def _get_system_ram_mb() -> tuple[float, float, float]:
    """Return (total_mb, available_mb, used_pct)."""
    # 1. Try psutil if available
    try:
        import psutil

        vm = psutil.virtual_memory()
        total_mb = vm.total / (1024 * 1024)
        avail_mb = vm.available / (1024 * 1024)
        return total_mb, avail_mb, vm.percent
    except Exception:
        pass

    # 2. Windows ctypes GlobalMemoryStatusEx fallback
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_mb = stat.ullTotalPhys / (1024 * 1024)
                avail_mb = stat.ullAvailPhys / (1024 * 1024)
                used_pct = float(stat.dwMemoryLoad)
                return total_mb, avail_mb, used_pct
        except Exception:
            pass

    # Default fallback assumption for 8 GB system
    return 8192.0, 2048.0, 75.0


def get_memory_status() -> MemoryStatus:
    """Evaluate current host and process memory metrics."""
    total_mb, avail_mb, used_pct = _get_system_ram_mb()
    rss_mb = _get_process_rss_mb()

    # Classification boundaries for 8 GB RAM profile
    if avail_mb < 500.0 or rss_mb > 1400.0:
        level = "CRITICAL"
        rec = "Memory pressure is severe. Aggressive cache trimming and garbage collection required."
    elif avail_mb < 900.0 or rss_mb > 1000.0:
        level = "MODERATE"
        rec = "Memory usage approaching limits for 8 GB RAM. Trimming expired in-memory items."
    else:
        level = "NORMAL"
        rec = "Memory consumption optimal within 8 GB RAM / 1.2 GB process budget."

    return MemoryStatus(
        total_ram_mb=total_mb,
        available_ram_mb=avail_mb,
        used_ram_pct=used_pct,
        process_rss_mb=rss_mb,
        pressure_level=level,
        recommendation=rec,
    )


def trim_memory_if_needed(force: bool = False) -> dict:
    """
    Check memory pressure and invoke registered trim callbacks if under pressure.
    Returns audit details of actions taken.
    """
    status = get_memory_status()
    evicted_total = 0
    triggered = force or status.pressure_level in ("MODERATE", "CRITICAL")

    if triggered:
        with _callbacks_lock:
            callbacks = list(_trim_callbacks)

        for cb in callbacks:
            try:
                evicted_total += cb()
            except Exception as e:
                logger.warning(f"Error in memory trim callback: {e}")

        # Explicit garbage collection pass
        gc.collect()

    return {
        "triggered": triggered,
        "pressure_level": status.pressure_level,
        "items_evicted": evicted_total,
        "process_rss_mb_after": round(_get_process_rss_mb(), 1),
    }
