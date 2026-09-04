"""
tests/test_ticker_stream.py
───────────────────────────
Tests for MarketTickerStream and /api/ticker endpoints (Indian & Global indices).
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from market.mstock_websocket import MStockTick
from market.ticker_stream import MarketTickerStream


def test_ticker_stream_initialization():
    stream = MarketTickerStream()
    snap = stream.get_snapshot()

    assert "indian" in snap
    assert "global" in snap
    assert "commodities" in snap
    assert "all" in snap
    assert len(snap["indian"]) >= 5
    assert len(snap["global"]) >= 5


def test_ticker_stream_mstock_tick_handling():
    stream = MarketTickerStream()

    # Synthetic m.Stock NIFTY tick
    tick = MStockTick(
        mode=3,
        exchange_type=1,
        token="26000",
        symbol="NSE:NIFTY 50",
        sequence=123,
        timestamp=1756980000.0,
        ltp=24650.25,
        open=24500.0,
        high=24700.0,
        low=24480.0,
        close=24550.0,
        volume=2000000,
    )

    stream._on_mstock_tick(tick)
    snap = stream.get_snapshot()
    nifty = next((item for item in snap["indian"] if item["key"] == "nifty_50"), None)

    assert nifty is not None
    assert nifty["price"] == 24650.25
    assert nifty["change"] == 100.25
    assert nifty["source"] == "MSTOCK_WS"
    assert snap["status"] == "LIVE_STREAMING"


def test_ticker_stream_refresh_sync_mock():
    stream = MarketTickerStream()

    mock_macro = MagicMock()
    mock_macro.items = {
        "gift_nifty": MagicMock(ltp=24720.0, change=120.0, change_pct=0.49),
        "nasdaq": MagicMock(ltp=19850.0, change=150.0, change_pct=0.76),
        "sp500": MagicMock(ltp=5650.0, change=25.0, change_pct=0.44),
        "dxy": MagicMock(ltp=102.5, change=-0.2, change_pct=-0.19),
        "us10y": MagicMock(ltp=4.15, change=0.02, change_pct=0.48),
        "brent": MagicMock(ltp=78.50, change=-0.8, change_pct=-1.01),
        "gold": MagicMock(ltp=2520.0, change=15.0, change_pct=0.60),
    }

    mock_indices = MagicMock(
        nifty=24600.0,
        nifty_chg=0.5,
        banknifty=52000.0,
        banknifty_chg=0.3,
        sensex=81000.0,
        sensex_chg=0.4,
        india_vix=13.5,
    )

    with (
        patch("market.global_macro.fetch_global_macro_report", return_value=mock_macro),
        patch("market.indices.get_market_snapshot", return_value=mock_indices),
    ):
        stream.refresh_indices_sync()
        snap = stream.get_snapshot()

        gift = next((i for i in snap["global"] if i["key"] == "gift_nifty"), None)
        assert gift is not None
        assert gift["price"] == 24720.0

        nasdaq = next((i for i in snap["global"] if i["key"] == "nasdaq"), None)
        assert nasdaq is not None
        assert nasdaq["price"] == 19850.0

        brent = next((i for i in snap["commodities"] if i["key"] == "brent"), None)
        assert brent is not None
        assert brent["price"] == 78.50


@pytest.fixture
def web_client():
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


def test_api_ticker_snapshot_endpoint(web_client):
    with patch("market.ticker_stream.ticker_stream.refresh_indices_sync"):
        resp = web_client.get("/api/ticker/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert "indian" in data
        assert "global" in data
        assert "commodities" in data
        assert "status" in data


def test_api_ticker_stream_routes_registered(web_client):
    from web.api import app

    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/api/ticker/stream" in paths
    assert "/stream/ticker" in paths


def test_api_ticker_stream_generator_logic():
    import asyncio

    async def _test():
        from web.api import stream_ticker

        resp = await stream_ticker()
        assert resp.status_code == 200
        assert resp.media_type == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"

        async for chunk in resp.body_iterator:
            assert "ticker_snapshot" in chunk
            assert "data:" in chunk
            break

    asyncio.run(_test())
