"""The pytest network quarantine must not depend on mutable environment state.

A test that unsets CHANAKYA_TESTING (to exercise a production branch) used to
re-open outbound sockets for the whole process. Background threads that outlived
their test then fetched live broker quotes, polluted the shared quote cache and
made unrelated detections non-deterministic.
"""

from __future__ import annotations

import socket
import sys

import pytest


def _harness():
    module = sys.modules.get("conftest") or sys.modules.get("tests.conftest")
    assert module is not None, "pytest conftest must be imported before tests run"
    return module


def test_quarantine_is_latched_at_import():
    harness = _harness()
    assert harness._GUARD_ACTIVE is True
    assert harness._PROCESS_ALLOW_NETWORK is False


def test_removing_chanakya_testing_does_not_reopen_the_network(monkeypatch):
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        with pytest.raises(RuntimeError, match="Outbound network connection blocked"):
            probe.connect(("1.1.1.1", 443))
    finally:
        probe.close()
