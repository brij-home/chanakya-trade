"""
tests/test_fyers_diagnostics_api.py
───────────────────────────────────
Test for GET /api/diagnostics/fyers-budget endpoint.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client():
    with (
        patch.dict(
            os.environ,
            {
                "DEPLOY_MODE": "desktop",
                "AUTH_DB_PATH": str(Path(tempfile.mkdtemp()) / "test.db"),
            },
        ),
        patch("config.credentials.load_all", return_value=None),
        patch("dotenv.load_dotenv", return_value=None),
    ):
        from web.api import app

        yield TestClient(app)


def test_fyers_budget_diagnostics_endpoint(client):
    resp = client.get("/api/diagnostics/fyers-budget")
    assert resp.status_code == 200
    data = resp.json()

    assert "status" in data
    assert "rate_gate" in data
    assert "circuit_breaker" in data
    assert "websocket_subscriptions" in data
    assert "vwap_session_cache" in data

    rate_gate = data["rate_gate"]
    assert rate_gate["max_per_sec"] == 8.0
    assert rate_gate["max_per_min"] == 160.0
    assert "utilization_pct" in rate_gate
    assert "requests_last_min_by_tier" in rate_gate

    cb = data["circuit_breaker"]
    assert cb["state"] in ("CLOSED", "OPEN", "HALF_OPEN")

    subs = data["websocket_subscriptions"]
    assert subs["max_limit"] == 180
    assert subs["total_count"] >= 40
