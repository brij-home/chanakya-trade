"""
Unit tests for the shared cross-process file lock (engine/file_lock.py).

The lock sidecar is intentionally persistent: deleting it would let a waiter
lock a stale inode while a third process locks a freshly created file.
"""

from pathlib import Path

import pytest

import engine.file_lock as fl
from engine.file_lock import file_lock


def test_lock_is_exclusive_and_times_out(tmp_path: Path):
    """A held lock must block a second acquirer until the timeout."""
    target = tmp_path / "dataset"

    with file_lock(target, timeout_s=1.0) as got:
        assert got is True

        with pytest.raises(TimeoutError):
            with file_lock(target, timeout_s=0.1):
                pass

        with file_lock(target, timeout_s=0.1, raise_on_timeout=False) as got2:
            assert got2 is False

    # Released: acquire again immediately.
    with file_lock(target, timeout_s=0.5) as got3:
        assert got3 is True


def test_sidecar_is_persistent(tmp_path: Path):
    """The .lock sidecar must survive release (unlink-race prevention)."""
    target = tmp_path / "dataset"
    lock_path = tmp_path / "dataset.lock"

    with file_lock(target, timeout_s=0.5):
        assert lock_path.exists()

    assert lock_path.exists(), "sidecar must not be deleted on release"


def test_fallback_without_platform_primitive(tmp_path: Path, monkeypatch):
    """Without msvcrt/fcntl the lock degrades to in-process semantics, not error."""
    monkeypatch.setattr(fl, "msvcrt", None)
    monkeypatch.setattr(fl, "fcntl", None)

    target = tmp_path / "dataset"
    with file_lock(target, timeout_s=0.2) as got:
        assert got is True


def test_creates_parent_directories(tmp_path: Path):
    """Locking a path in a not-yet-created dataset directory must work."""
    target = tmp_path / "5m" / "TCS" / "compact"
    with file_lock(target, timeout_s=0.5) as got:
        assert got is True
        assert (target.parent / "compact.lock").exists()
