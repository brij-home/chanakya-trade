"""
Unit tests for Institutional API wiring: Smart-Route, SABR Vol-Surface, and Tick Warehouse endpoints in web/api.py.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient

from analysis.vol_surface import SABRCalibrationResult, SABRParameters, StrikeMispricing
from web.api import app

client = TestClient(app, base_url="http://127.0.0.1:8765")


def test_api_smart_route_twap_and_vwap():
    """Verify POST /api/execution/smart-route correctly processes TWAP and VWAP_POV parameters."""
    # 1. TWAP Request
    resp_twap = client.post(
        "/api/execution/smart-route",
        json={
            "symbol": "NIFTY",
            "side": "BUY",
            "quantity": 1300,
            "ltp": 25000.0,
            "lot_size": 65,
            "routing_mode": "TWAP",
            "duration_minutes": 20,
        },
    )
    assert resp_twap.status_code == 200
    data_twap = resp_twap.json()
    assert data_twap["routing_mode"] == "TWAP"
    assert data_twap["total_quantity"] == 1300
    assert len(data_twap["tranches"]) > 1

    # 2. VWAP_POV Request
    resp_vwap = client.post(
        "/api/execution/smart-route",
        json={
            "symbol": "RELIANCE",
            "side": "SELL",
            "quantity": 500,
            "ltp": 2900.0,
            "lot_size": 1,
            "routing_mode": "VWAP_POV",
            "duration_minutes": 30,
            "target_pov_pct": 0.05,
        },
    )
    assert resp_vwap.status_code == 200
    data_vwap = resp_vwap.json()
    assert data_vwap["routing_mode"] == "VWAP_POV"
    assert data_vwap["total_quantity"] == 500


def test_api_warehouse_stats_and_purge():
    """Verify GET /api/warehouse/stats and POST /api/warehouse/purge."""
    resp_stats = client.get("/api/warehouse/stats")
    assert resp_stats.status_code == 200
    stats = resp_stats.json()
    assert "total_bytes" in stats
    assert "parquet_files" in stats
    assert "warehouse_path" in stats

    resp_purge = client.post("/api/warehouse/purge?retention_days=60")
    assert resp_purge.status_code == 200
    purge_data = resp_purge.json()
    assert purge_data["status"] == "OK"
    assert "purged_partitions" in purge_data


def test_api_vol_surface_endpoint_mocked():
    """Verify GET /api/options/vol-surface/{symbol} returns calibrated SABR parameters and mispricings."""
    mock_result = SABRCalibrationResult(
        underlying="NIFTY",
        forward_price=25000.0,
        expiry_years=0.0411,
        dte_days=15.0,
        parameters=SABRParameters(
            alpha=3.35,
            beta=0.7,
            rho=-0.32,
            nu=0.55,
            rmse=0.12,
            mae=0.09,
            converged=True,
        ),
        mispricings=[
            StrikeMispricing(
                strike=24000.0,
                market_iv=18.5,
                sabr_iv=16.8,
                iv_edge_pts=1.7,
                edge_pct=10.12,
                verdict="OVERPRICED",
                recommendation="Sell Volatility / Credit Spread",
            )
        ],
        fitted_strikes=[24000.0, 25000.0, 26000.0],
        fitted_ivs=[16.8, 15.5, 15.1],
        skew_verdict="PUT_SKEW",
    )

    with patch("analysis.vol_surface.analyze_volatility_surface", return_value=mock_result):
        resp = client.get("/api/options/vol-surface/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "OK"
        assert data["underlying"] == "NIFTY"
        assert data["skew_verdict"] == "PUT_SKEW"
        assert data["parameters"]["alpha"] == 3.35
        assert len(data["mispricings"]) == 1
        assert data["mispricings"][0]["verdict"] == "OVERPRICED"
        assert len(data["fitted_curve"]) == 3
