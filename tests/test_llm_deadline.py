from __future__ import annotations

import threading
import time

import pytest

from engine.llm_deadline import MAX_INFLIGHT, reset_deadline_slots, run_with_deadline


def test_deadline_returns_without_waiting_for_stalled_provider():
    finished = threading.Event()

    def stalled_provider():
        try:
            time.sleep(0.25)
            return "late response"
        finally:
            finished.set()

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="deadline"):
        run_with_deadline(stalled_provider, timeout=0.01, label="test-stalled")
    elapsed = time.monotonic() - started
    assert elapsed < 0.15
    assert finished.wait(0.5)


def test_stalled_provider_calls_have_a_global_concurrency_cap():
    reset_deadline_slots()
    release = threading.Event()
    started: list[threading.Event] = [threading.Event() for _ in range(MAX_INFLIGHT)]

    def blocked_provider(index: int):
        started[index].set()
        release.wait(10.0)
        return index

    try:
        for index in range(MAX_INFLIGHT):
            with pytest.raises(TimeoutError, match="deadline"):
                run_with_deadline(
                    lambda i=index: blocked_provider(i),
                    timeout=0.01,
                    label=f"test-cap-{index}",
                )
        assert all(event.wait(5.0) for event in started)
        with pytest.raises(TimeoutError, match="capacity exhausted"):
            run_with_deadline(lambda: "must not start", timeout=0.1, label="test-over-cap")
    finally:
        release.set()


def test_deadline_helper_returns_and_propagates_provider_errors():
    assert run_with_deadline(lambda: "ok", timeout=0.1, label="test-ok") == "ok"

    def failed_provider():
        raise RuntimeError("provider failure")

    with pytest.raises(RuntimeError, match="provider failure"):
        run_with_deadline(failed_provider, timeout=0.1, label="test-error")
