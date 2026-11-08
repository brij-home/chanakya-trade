"""
engine/file_lock.py
──────────────────
Cross-process advisory file locking shared by the local Parquet stores.

The lock is a persistent 0-byte sidecar (<target>.lock). It is never deleted:
deleting it would allow a waiter to lock a stale inode while a third process
locks a freshly created file, defeating mutual exclusion. Sidecars age out with
their parent partition or dataset.

Windows uses msvcrt byte-range locks (mandatory); POSIX uses fcntl.flock.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("engine.file_lock")

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]
try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


@contextmanager
def file_lock(
    lock_target: Path,
    timeout_s: float = 2.0,
    poll_ms: float = 20.0,
    raise_on_timeout: bool = True,
):
    """Exclusive advisory lock on the persistent sidecar <lock_target>.lock.

    Yields:
        True when the lock is held, or False on timeout if raise_on_timeout is
        False.
    """
    lock_path = lock_target.with_name(lock_target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))

    def _try_lock() -> bool:
        try:
            if msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            elif fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock() -> None:
        try:
            if msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception as e_unlock:
            logger.debug(f"[engine.file_lock] Release note for {lock_path.name}: {e_unlock}")

    deadline = time.monotonic() + timeout_s
    acquired = msvcrt is None and fcntl is None  # no primitive: in-process only
    while not acquired:
        if _try_lock():
            acquired = True
            break
        if time.monotonic() >= deadline:
            os.close(fd)
            if raise_on_timeout:
                raise TimeoutError(
                    f"Could not acquire lock {lock_path.name} within {timeout_s:.1f}s"
                )
            yield False
            return
        time.sleep(poll_ms / 1000.0)

    try:
        yield True
    finally:
        _unlock()
        os.close(fd)
