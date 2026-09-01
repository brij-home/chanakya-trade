"""
tests/test_mode_banner_mapping.py
──────────────────────────────────
Gap 2: Verifies that /api/mode normalises the backend TradingMode enum
to the canonical UI enum (PAPER | DEMO | LIVE) that ModeBanner.jsx understands.

An EXECUTE-mode system MUST return "LIVE" — never silently "PAPER".
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Import the FastAPI app with test client (localhost auth bypassed)."""
    from web.api import app

    return TestClient(app)


def test_api_mode_simulate_returns_paper(client, monkeypatch):
    """TRADING_MODE=SIMULATE (default) → mode='PAPER'."""
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")
    # Invalidate cached mode so env var takes effect
    import importlib
    import engine.modes as modes_mod

    importlib.reload(modes_mod)

    resp = client.get("/api/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "PAPER", f"SIMULATE should map to 'PAPER', got {data['mode']!r}"
    assert data["backend_mode"] == "SIMULATE"


def test_api_mode_observe_returns_demo(client, monkeypatch):
    """TRADING_MODE=OBSERVE → mode='DEMO'."""
    monkeypatch.setenv("TRADING_MODE", "OBSERVE")
    import importlib
    import engine.modes as modes_mod

    importlib.reload(modes_mod)

    resp = client.get("/api/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "DEMO", f"OBSERVE should map to 'DEMO', got {data['mode']!r}"
    assert data["backend_mode"] == "OBSERVE"


def test_api_mode_execute_returns_live(client, monkeypatch):
    """
    TRADING_MODE=EXECUTE → mode='LIVE'.

    This is the critical P0 case: an EXECUTE-mode system must NOT
    display 'Paper Mode' in the UI banner.
    """
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    import importlib
    import engine.modes as modes_mod

    importlib.reload(modes_mod)

    resp = client.get("/api/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "LIVE", (
        f"EXECUTE must map to 'LIVE', got {data['mode']!r}. "
        "An EXECUTE-mode system showing 'Paper Mode' is a P0 safety failure."
    )
    assert data["backend_mode"] == "EXECUTE"


def test_api_mode_unset_defaults_to_paper(client, monkeypatch):
    """Unset TRADING_MODE → defaults to SIMULATE → 'PAPER' in UI."""
    monkeypatch.delenv("TRADING_MODE", raising=False)
    import importlib
    import engine.modes as modes_mod

    importlib.reload(modes_mod)

    resp = client.get("/api/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "PAPER", (
        f"Unset TRADING_MODE should default to 'PAPER', got {data['mode']!r}"
    )


def test_api_mode_paper_env_maps_to_paper(client, monkeypatch):
    """TRADING_MODE=PAPER (legacy env value) → mode='PAPER'."""
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    import importlib
    import engine.modes as modes_mod

    importlib.reload(modes_mod)

    resp = client.get("/api/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "PAPER"


def test_api_mode_response_includes_description(client, monkeypatch):
    """Response must include a human-readable description field."""
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")
    import importlib
    import engine.modes as modes_mod

    importlib.reload(modes_mod)

    resp = client.get("/api/mode")
    data = resp.json()
    assert "description" in data
    assert len(data["description"]) > 0
