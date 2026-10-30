"""
tests/test_host_sentinel.py
───────────────────────────
Unit tests for engine/host_sentinel.py hardware and power sentinel.
"""

from __future__ import annotations

import ctypes
import platform
from unittest.mock import MagicMock, patch

from engine.host_sentinel import HostSentinel, host_sentinel


def test_host_sentinel_singleton():
    s1 = HostSentinel()
    s2 = HostSentinel()
    assert s1 is s2
    assert s1 is host_sentinel


def test_host_sentinel_capabilities():
    caps = host_sentinel.get_capabilities()
    assert caps.logical_cores >= 1
    assert caps.physical_cores >= 1
    assert isinstance(caps.is_windows, bool)
    assert caps.os_name == platform.system()


def test_cpu_affinity_recommendation():
    # Test execution role (should return lower P-core indices)
    exec_cores = host_sentinel.get_recommended_cpu_affinity("EXECUTION")
    assert exec_cores is not None
    assert 0 in exec_cores

    # Test background role (should return higher E-core indices if hybrid)
    bg_cores = host_sentinel.get_recommended_cpu_affinity("BACKGROUND_SCANNER")
    assert bg_cores is not None
    if host_sentinel.logical_cores >= 8:
        # P-cores and E-cores should be disjoint
        assert set(exec_cores).isdisjoint(set(bg_cores))


def test_sleep_prevention_mocked():
    mock_windll = MagicMock()
    mock_windll.kernel32.SetThreadExecutionState.return_value = 1
    with patch.object(ctypes, "windll", mock_windll, create=True):
        with patch.object(host_sentinel, "is_windows", True):
            success = host_sentinel.prevent_sleep(keep_display_on=False)
            assert success is True
            assert host_sentinel.get_capabilities().sleep_prevention_active is True
            mock_windll.kernel32.SetThreadExecutionState.assert_called_once()

            # Test allow sleep
            restore_success = host_sentinel.allow_sleep()
            assert restore_success is True
            assert host_sentinel.get_capabilities().sleep_prevention_active is False


def test_priority_elevation_mocked():
    mock_windll = MagicMock()
    mock_windll.kernel32.GetCurrentProcess.return_value = 1234
    mock_windll.kernel32.SetPriorityClass.return_value = True
    with patch.object(ctypes, "windll", mock_windll, create=True):
        with patch.object(host_sentinel, "is_windows", True):
            elevate_ok = host_sentinel.elevate_process_priority()
            assert elevate_ok is True
            assert host_sentinel.get_capabilities().priority_elevated is True

            restore_ok = host_sentinel.restore_process_priority()
            assert restore_ok is True
            assert host_sentinel.get_capabilities().priority_elevated is False
