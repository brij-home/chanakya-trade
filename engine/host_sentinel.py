"""
engine/host_sentinel.py
───────────────────────
Host Machine Resource Sentinel & Hardware Governor for ChanakyaTrade.

Optimized specifically for Windows 10/11 on Intel 12th+ Gen Hybrid Architectures
(Performance Cores + Efficient Cores) and High-RAM (16GB-32GB) laptops.

Responsibilities:
  1. Windows Modern Standby / Sleep Prevention (Anti-Sleep API):
     Prevents Windows from suspending WebSocket ingestion, order monitoring,
     and background timers during active Indian Market Hours (09:00 - 15:35 IST).
  2. Thread & Process Priority Governor:
     Elevates live trading execution and WebSocket processing priority
     (ABOVE_NORMAL_PRIORITY_CLASS) to prevent audio/video or browser apps
     from starving the trading engine of CPU cycles.
  3. CPU Core Affinity Routing:
     Pins latency-critical threads (order execution, tick dispatch) to Intel P-Cores,
     while routing background scanners and postmortems to E-Cores.
  4. Non-Windows / Degraded OS Fallback:
     Safely degrades to standard threading without throwing exceptions if running
     on Linux/macOS or if platform-specific API privileges are unavailable.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("engine.host_sentinel")

# Windows Kernel32 Execution State Flags
# Reference: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
ES_CONTINUOUS: int = 0x80000000
ES_SYSTEM_REQUIRED: int = 0x00000001
ES_DISPLAY_REQUIRED: int = 0x00000002
ES_AWAYMODE_REQUIRED: int = 0x00000040

# Windows Process Priority Constants
ABOVE_NORMAL_PRIORITY_CLASS: int = 0x00008000
NORMAL_PRIORITY_CLASS: int = 0x00000020


@dataclass
class HostSystemCapabilities:
    os_name: str
    is_windows: bool
    logical_cores: int
    physical_cores: int
    has_hybrid_cores: bool
    sleep_prevention_active: bool = False
    priority_elevated: bool = False


class HostSentinel:
    """
    Singleton Host Machine Resource & Power Sentinel.
    Safely controls execution state, CPU affinity, and power states.
    """

    _instance: Optional[HostSentinel] = None
    _lock = threading.Lock()

    def __new__(cls) -> HostSentinel:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self.os_name = platform.system()
        self.is_windows = self.os_name == "Windows"
        self.logical_cores = os.cpu_count() or 4
        self.physical_cores = max(1, self.logical_cores // 2)
        # Intel 12th Gen+ typically has >= 8 logical cores with asymmetric P/E allocation
        self.has_hybrid_cores = self.logical_cores >= 8
        self._sleep_prevention_active = False
        self._priority_elevated = False
        self._initialized = True

    def get_capabilities(self) -> HostSystemCapabilities:
        """Return the current capabilities and host status."""
        return HostSystemCapabilities(
            os_name=self.os_name,
            is_windows=self.is_windows,
            logical_cores=self.logical_cores,
            physical_cores=self.physical_cores,
            has_hybrid_cores=self.has_hybrid_cores,
            sleep_prevention_active=self._sleep_prevention_active,
            priority_elevated=self._priority_elevated,
        )

    def prevent_sleep(self, keep_display_on: bool = False) -> bool:
        """
        Prevent the host OS from entering system sleep or modern standby.
        Essential during Indian market hours (09:00 - 15:35 IST) to keep
        WebSockets and risk monitors active.
        """
        if not self.is_windows:
            logger.debug("[host_sentinel] Sleep prevention is only applicable on Windows host.")
            return False

        try:
            flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            if keep_display_on:
                flags |= ES_DISPLAY_REQUIRED

            result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
            if result != 0:
                self._sleep_prevention_active = True
                logger.info(
                    "[host_sentinel] Windows sleep prevention ACTIVE (continuous system & away mode)."
                )
                return True
            else:
                logger.warning(
                    "[host_sentinel] SetThreadExecutionState returned 0. Could not set execution state."
                )
                return False
        except Exception as e:
            logger.warning(f"[host_sentinel] Failed to set Windows sleep prevention: {e}")
            return False

    def allow_sleep(self) -> bool:
        """
        Restore normal OS power management behavior (allows PC to sleep normally).
        Should be called after market close (15:35+ IST) or on clean shutdown.
        """
        if not self.is_windows:
            return False

        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            if result != 0:
                self._sleep_prevention_active = False
                logger.info(
                    "[host_sentinel] Windows sleep prevention RELEASED (restored default power management)."
                )
                return True
            return False
        except Exception as e:
            logger.warning(f"[host_sentinel] Failed to restore normal Windows sleep state: {e}")
            return False

    def elevate_process_priority(self) -> bool:
        """
        Elevate the trading process to ABOVE_NORMAL_PRIORITY_CLASS on Windows.
        Ensures market data ingestion and order gates are not pre-empted by heavy background apps.
        """
        if not self.is_windows:
            return False

        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            success = ctypes.windll.kernel32.SetPriorityClass(handle, ABOVE_NORMAL_PRIORITY_CLASS)
            if success:
                self._priority_elevated = True
                logger.info(
                    "[host_sentinel] Process priority elevated to ABOVE_NORMAL_PRIORITY_CLASS."
                )
                return True
            else:
                logger.warning("[host_sentinel] Failed to set priority class.")
                return False
        except Exception as e:
            logger.warning(f"[host_sentinel] Exception setting process priority: {e}")
            return False

    def restore_process_priority(self) -> bool:
        """Restore process priority back to normal."""
        if not self.is_windows:
            return False

        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            success = ctypes.windll.kernel32.SetPriorityClass(handle, NORMAL_PRIORITY_CLASS)
            if success:
                self._priority_elevated = False
                logger.info("[host_sentinel] Process priority restored to NORMAL_PRIORITY_CLASS.")
                return True
            return False
        except Exception as e:
            logger.warning(f"[host_sentinel] Exception restoring process priority: {e}")
            return False

    def get_recommended_cpu_affinity(self, role: str) -> Optional[list[int]]:
        """
        Provides recommended CPU core indices for specific workloads on hybrid CPUs:
          - 'EXECUTION' / 'LIVE_FEED': Performance Cores (typically lower core indices 0..3 or 0..7)
          - 'BACKGROUND_SCANNER' / 'BACKTEST': Efficiency Cores (higher core indices)
        """
        total = self.logical_cores
        if total < 6:
            # Symmetrical quad-core or dual-core: use all cores
            return list(range(total))

        # Hybrid 12th Gen i5 (e.g., 4 P-cores hyperthreaded = 8 threads, + 4 or 8 E-cores = 12-16 total)
        p_core_count = min(8, max(4, total // 2))

        if role.upper() in ("EXECUTION", "LIVE_FEED", "RISK_GATE", "OMS"):
            return list(range(0, p_core_count))
        elif role.upper() in ("BACKGROUND_SCANNER", "BACKTEST", "POSTMORTEM", "EOD"):
            return list(range(p_core_count, total))
        else:
            return list(range(total))


# Global singleton access
host_sentinel = HostSentinel()
