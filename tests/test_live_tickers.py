"""
Unit and API integration tests for Multi-Asset Live Ticker Ribbon
(Indices, Commodities, Crypto).
"""

import pytest
from fastapi.testclient import TestClient
from web.skills import _compute_live_tickers_sync


def test_compute_live_tickers_sync_structure():
    """Verify _compute_live_tickers_sync returns proper payload for all 9 key assets."""
    tickers = _compute_live_tickers_sync()
    assert isinstance(tickers, list)
    assert len(tickers) >= 8

    symbols = {t["symbol"] for t in tickers}
    assert "NIFTY" in symbols
    assert "BANKNIFTY" in symbols
    assert "CRUDEOIL" in symbols
    assert "GOLD" in symbols
    assert "SILVER" in symbols
    assert "BTC" in symbols

    for t in tickers:
        assert "symbol" in t
        assert "display_name" in t
        assert "category" in t
        assert "unit" in t
        assert "ltp" in t
        assert "change_pct" in t
        assert t["direction"] in ("up", "down", "flat")
        assert isinstance(t["ltp"], (int, float))
        assert isinstance(t["change_pct"], (int, float))

    btc = next(t for t in tickers if t["symbol"] == "BTC")
    assert btc["unit"] == "$"
    assert btc["category"] == "CRYPTO"

    crude = next(t for t in tickers if t["symbol"] == "CRUDEOIL")
    assert "bbl" in crude["unit"]
    assert crude["category"] == "COMMODITY"


def test_live_tickers_api_endpoint():
    """Verify /skills/live_tickers endpoint responds with ok status and tickers list."""
    from web.api import app

    client = TestClient(app)
    response = client.get("/skills/live_tickers")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    tickers = data["data"]["tickers"]
    assert isinstance(tickers, list)
    assert len(tickers) >= 8


@pytest.mark.anyio
async def test_stream_ticker_handler():
    """Verify stream_ticker returns StreamingResponse with text/event-stream and snapshot."""
    from web.api import stream_ticker
    import json

    resp = await stream_ticker()
    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"
    gen = resp.body_iterator
    first_chunk = await gen.__anext__()
    assert first_chunk.startswith("data: ")
    payload = json.loads(first_chunk[6:].strip())
    assert payload.get("type") == "ticker_snapshot"
    assert "tickers" in payload or "data" in payload


def test_websocket_ticker_endpoint():
    """Verify /ws/ticker WebSocket endpoint connects and sends ticker_snapshot."""
    from web.api import app
    import json

    client = TestClient(app)
    with client.websocket_connect("/ws/ticker") as websocket:
        data = websocket.receive_text()
        payload = json.loads(data)
        assert payload.get("type") == "ticker_snapshot"
        assert "data" in payload
