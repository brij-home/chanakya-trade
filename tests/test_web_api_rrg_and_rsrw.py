"""
tests/test_api_rrg_and_rsrw.py
──────────────────────────────
Verification tests for the upgraded /api/v1/market/rrg and /api/v1/market/rs-rw-radar endpoints.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from web.api import app
from brokers.base import Quote
from analysis.sector_rotation import SectorRRGPoint


@pytest.fixture
def client():
    return TestClient(app)


def test_api_market_rrg_bidirectional_contract(client):
    """Verify /api/v1/market/rrg returns bidirectional quadrants and constituent mapping."""
    mock_rrg_points = [
        SectorRRGPoint(
            sector="INFRA",
            symbol="^CNXINFRA",
            rs_ratio=103.5,
            rs_momentum=102.1,
            quadrant="LEADING",
            day_change_pct=1.8,
            benchmark_change_pct=0.4,
            relative_strength=107.0,
        ),
        SectorRRGPoint(
            sector="IT",
            symbol="^CNXIT",
            rs_ratio=96.2,
            rs_momentum=95.4,
            quadrant="LAGGING",
            day_change_pct=-1.2,
            benchmark_change_pct=0.4,
            relative_strength=92.0,
        ),
    ]

    with patch("analysis.sector_rotation.get_sector_rrg_matrix", return_value=mock_rrg_points):
        res = client.get("/api/v1/market/rrg")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "success"
        assert "INFRA" in data["leading_sectors"]
        assert "IT" in data["lagging_sectors"]
        assert "directional_constituents" in data

        dir_const = data["directional_constituents"]
        assert "BULLISH" in dir_const
        assert "BEARISH" in dir_const

        # POWERINDIA and ABB should be in BULLISH constituents because INFRA is LEADING
        assert "POWERINDIA" in dir_const["BULLISH"]
        assert "ABB" in dir_const["BULLISH"]
        # TCS and INFY should be in BEARISH constituents because IT is LAGGING
        assert "TCS" in dir_const["BEARISH"]
        assert "INFY" in dir_const["BEARISH"]


def test_api_rs_rw_radar_endpoint(client):
    """Verify /api/v1/market/rs-rw-radar returns institutional accumulation leaders and distribution laggards."""
    mock_quotes = {
        "NSE:NIFTY50-INDEX": Quote(
            symbol="NSE:NIFTY50-INDEX",
            last_price=24150.0,
            change_pct=0.45,
            volume=0,
        ),
        "NSE:POWERINDIA": Quote(
            symbol="NSE:POWERINDIA",
            last_price=31500.0,
            change_pct=4.80,
            vwap=30800.0,
            volume=250000,
        ),
        "NSE:WEAKSTOCK": Quote(
            symbol="NSE:WEAKSTOCK",
            last_price=450.0,
            change_pct=-2.10,
            vwap=465.0,
            volume=80000,
        ),
    }

    with patch("market.quotes.get_quote", return_value=mock_quotes):
        res = client.get(
            "/api/v1/market/rs-rw-radar?universe=POWERINDIA,WEAKSTOCK&bypass_cache=true"
        )
        assert res.status_code == 200
        payload = res.json()

        assert payload["status"] == "success"
        data = payload["data"]
        assert data["status"] == "OK"
        assert data["benchmark_symbol"] == "NSE:NIFTY50-INDEX"
        assert data["benchmark_change_pct"] == 0.45
        assert data["benchmark_state"] == "BULLISH"

        leaders = data["leaders"]
        laggards = data["laggards"]

        assert len(leaders) >= 1
        assert leaders[0]["clean_symbol"] == "POWERINDIA"
        assert leaders[0]["net_rs"] > 4.0
        assert leaders[0]["bias"] == "RELATIVE_STRENGTH"

        assert len(laggards) >= 1
        assert laggards[0]["clean_symbol"] == "WEAKSTOCK"
        assert laggards[0]["net_rs"] < -2.0
        assert laggards[0]["bias"] == "RELATIVE_WEAKNESS"
