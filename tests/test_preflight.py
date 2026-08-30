"""
tests/test_preflight.py
───────────────────────
Unit tests for system preflight diagnostics and environment masking.
"""

from __future__ import annotations

from scripts.preflight import (
    run_preflight,
    mask_secret,
    is_port_available,
    PreflightReport,
)


def test_mask_secret():
    assert mask_secret(None) == "<unset>"
    assert mask_secret("") == "<unset>"
    assert mask_secret("short") == "***"
    assert mask_secret("123456") == "***"
    assert mask_secret("my_secret_token_1234") == "****************1234"
    assert mask_secret("sk-proj-abc123xyz") == "*************3xyz"


def test_is_port_available():
    # Port 0 or a high random port should be available
    available = is_port_available(59123)
    assert isinstance(available, bool)


def test_run_preflight():
    report = run_preflight(verbose=False)
    assert isinstance(report, PreflightReport)
    assert len(report.checks) >= 5
    assert report.mode in ("SIMULATE", "EXECUTE", "OBSERVE")

    d = report.to_dict()
    assert "healthy" in d
    assert "checks" in d
    assert "masked_env" in d

    # Verify no raw secret is leaked in masked_env
    for key, val in d["masked_env"].items():
        if "KEY" in key or "SECRET" in key:
            assert not val.startswith("sk-live")
            assert not (len(val) > 10 and "*" not in val)
