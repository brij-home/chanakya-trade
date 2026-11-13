"""Bounded caller-side deadlines for untrusted external LLM calls.

Python cannot safely terminate a provider call blocked in a thread. This helper
returns at the caller deadline, runs at most MAX_INFLIGHT daemon calls at once,
and refuses new calls while all slots remain occupied by stalled providers.
Provider-level HTTP timeouts are still required to reclaim a slot promptly.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
MAX_INFLIGHT = 4
_slots = threading.BoundedSemaphore(MAX_INFLIGHT)


def reset_deadline_slots() -> None:
    """Reset the semaphore to initial MAX_INFLIGHT slots (for test isolation)."""
    global _slots
    _slots = threading.BoundedSemaphore(MAX_INFLIGHT)


def run_with_deadline(call: Callable[[], T], *, timeout: float, label: str) -> T:
    """Run ``call`` without allowing its worker to extend caller wall time."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    sem = _slots
    if not sem.acquire(blocking=False):
        raise TimeoutError(
            f"LLM call capacity exhausted; {MAX_INFLIGHT} provider calls are still in flight"
        )

    completed = threading.Event()
    result: dict[str, object] = {}

    def _invoke() -> None:
        try:
            result["value"] = call()
        except Exception as exc:
            result["error"] = exc
        finally:
            completed.set()
            try:
                sem.release()
            except ValueError:
                logger.debug("[llm_deadline] Slot already released or reset")

    worker = threading.Thread(
        target=_invoke,
        name=f"llm-deadline-{label[:40]}",
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        sem.release()
        raise

    if not completed.wait(timeout):
        logger.warning("[llm_deadline] Provider call exceeded %.3fs deadline: %s", timeout, label)
        raise TimeoutError(f"LLM call exceeded {timeout:.3f}s deadline ({label})")
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")  # type: ignore[return-value]
