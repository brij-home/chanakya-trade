"""
tests/test_smc_ob_tide_and_squeeze_radar_invariants.py
───────────────────────────────────────────────────────
Validates Gate 31 Index Tide Gate integration into SMC Order Block Re-Test,
mitigation touch filtering, Precursor Radar squeeze prioritization,
and FastAPI calibration/squeeze endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from engine.detectors.smc_orderblock_retest import detect_smc_orderblock_retest
from engine.market_regime_gate import clear_index_tide_cache
from engine.precursor_radar import PrecursorRadarScanner


@pytest.fixture(autouse=True)
def clean_tide_state():
    clear_index_tide_cache()
    yield
    clear_index_tide_cache()


def _build_demand_ob_df(prev_close: float = 101.0) -> pd.DataFrame:
    """Builds synthetic daily OHLCV forming a validated Demand Order Block at 99.0-102.0."""
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(50)]
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(50):
        if i < 20:
            o, h, l, c, v = 100.0, 102.0, 98.0, 100.0, 10000
        elif i == 20:
            o, h, l, c, v = 101.0, 102.0, 99.0, 99.5, 15000
        elif i == 21:
            o, h, l, c, v = 100.0, 112.0, 100.0, 110.0, 45000
        elif i == 22:
            o, h, l, c, v = 111.0, 125.0, 110.0, 124.0, 40000
        elif i == 23:
            o, h, l, c, v = 125.0, 135.0, 124.0, 133.0, 30000
        elif i == 48:
            # T-1 bar: custom prev_close with low staying above 99.0
            o, h, l, c, v = (
                prev_close,
                prev_close + 0.5,
                max(99.1, prev_close - 0.4),
                prev_close,
                8000,
            )
        else:
            factor = (i - 23) / 27.0
            val = 133.0 - factor * (133.0 - 101.0)
            o, h, l, c, v = val + 0.5, val + 1.0, val - 0.5, val, 8000
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )


def _build_supply_ob_df() -> pd.DataFrame:
    """Builds synthetic daily OHLCV forming a validated Supply Order Block at 198.0-201.0."""
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(50)]
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(50):
        if i < 20:
            o, h, l, c, v = 200.0, 202.0, 198.0, 200.0, 10000
        elif i == 20:
            o, h, l, c, v = 199.0, 201.0, 198.0, 200.5, 15000
        elif i == 21:
            o, h, l, c, v = 200.0, 200.0, 188.0, 190.0, 45000
        elif i == 22:
            o, h, l, c, v = 189.0, 190.0, 175.0, 176.0, 40000
        elif i == 23:
            o, h, l, c, v = 175.0, 176.0, 165.0, 167.0, 30000
        else:
            factor = (i - 23) / 27.0
            val = 167.0 + factor * (200.0 - 167.0)
            o, h, l, c, v = val - 0.5, val + 0.5, val - 1.0, val, 8000
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )


def test_smc_ob_supply_vetoed_when_index_advancing_above_vwap():
    """Gate 31: Supply OB short setup must be vetoed when NIFTY is advancing above VWAP."""
    df = _build_supply_ob_df()

    # Mock NIFTY advancing above VWAP (+0.50%, LTP 24800, VWAP 24650)
    advancing_nifty = MagicMock()
    advancing_nifty.last_price = 24800.0
    advancing_nifty.vwap = 24650.0
    advancing_nifty.change_pct = 0.50

    with patch("market.quotes.get_quote", return_value={"NSE:NIFTY50-INDEX": advancing_nifty}):
        alerts = detect_smc_orderblock_retest(
            symbol="ABC",
            df=df,
            ltp=199.5,
            exchange="NSE",
            rvol=1.2,  # Normal RVOL (not decoupled)
        )
        assert len(alerts) == 0, (
            "Supply OB short should be vetoed when benchmark index is advancing"
        )


def test_smc_ob_demand_vetoed_when_index_plunging_below_vwap():
    """Gate 31: Demand OB long setup must be vetoed when NIFTY is plunging below VWAP."""
    df = _build_demand_ob_df()

    # Mock NIFTY liquidating below VWAP (-0.60%, LTP 24300, VWAP 24500)
    plunging_nifty = MagicMock()
    plunging_nifty.last_price = 24300.0
    plunging_nifty.vwap = 24500.0
    plunging_nifty.change_pct = -0.60

    with patch("market.quotes.get_quote", return_value={"NSE:NIFTY50-INDEX": plunging_nifty}):
        alerts = detect_smc_orderblock_retest(
            symbol="XYZ",
            df=df,
            ltp=100.5,
            exchange="NSE",
            rvol=1.1,
        )
        assert len(alerts) == 0, "Demand OB long should be vetoed when benchmark index is plunging"


def test_smc_ob_exempts_explosive_volume_decoupler():
    """Outlier Decoupling Exemption: Decoupled catalyst price move (|change_pct| >= 2.5%) is allowed even into opposing tide."""
    # LTP 102.2 vs prev_close 99.5 -> +2.71% decoupled move
    df = _build_demand_ob_df(prev_close=99.5)

    plunging_nifty = MagicMock()
    plunging_nifty.last_price = 24300.0
    plunging_nifty.vwap = 24500.0
    plunging_nifty.change_pct = -0.60

    with patch("market.quotes.get_quote", return_value={"NSE:NIFTY50-INDEX": plunging_nifty}):
        alerts = detect_smc_orderblock_retest(
            symbol="XYZ",
            df=df,
            ltp=102.2,
            exchange="NSE",
            rvol=1.2,  # RVOL <= 1.8 for quiet absorption
        )
        assert len(alerts) == 1, (
            "Decoupled stock with change_pct >= 2.5% should be exempted from tide veto"
        )
        assert alerts[0].direction == "BULLISH"


def test_smc_ob_suppresses_multiple_mitigations():
    """Exhausted OB (tested >= 2 times) must be skipped."""
    df = _build_demand_ob_df()

    with patch("analysis.market_structure.analyze_market_structure") as mock_ms:
        ob = MagicMock()
        ob.type = "DEMAND"
        ob.top = 102.0
        ob.bottom = 99.0
        ob.midpoint = 100.5
        ob.formed_date = "2026-01-20"
        ob.mitigated = False
        ob.is_unmitigated = True
        ob.quality_tier = "TIER_1_PRIME"
        ob.test_count = 2  # Already tested twice!

        ms_instance = MagicMock()
        ms_instance.active_demand_zones = [ob]
        ms_instance.active_supply_zones = []
        mock_ms.return_value = ms_instance

        alerts = detect_smc_orderblock_retest(
            symbol="TESTSYM",
            df=df,
            ltp=100.5,
            exchange="NSE",
            rvol=1.0,
        )
        assert len(alerts) == 0, (
            "OB with test_count >= 2 should be skipped as liquidity is exhausted"
        )


def test_precursor_radar_prepends_calibrated_coilers():
    """PrecursorRadarScanner.get_scan_universe('FNO') must prioritize calibrated coiling stocks."""
    radar = PrecursorRadarScanner()
    fno_u = radar.get_scan_universe("FNO")
    assert len(fno_u) > 0
    # Top stocks should match the calibrated TTM Squeeze coilers
    assert "TATAELXSI" in fno_u[:5]


def test_fastapi_calibration_and_squeeze_endpoints():
    """FastAPI sidecar endpoints must return 200 with calibrated data."""
    from fastapi.testclient import TestClient
    from web.api import app

    client = TestClient(app)

    r_sq = client.get("/api/scanners/coiling-squeezes")
    assert r_sq.status_code == 200
    sq_data = r_sq.json()
    assert sq_data.get("status") == "success"
    assert sq_data.get("total_coiling") >= 20

    r_cal = client.get("/api/calibration/metrics")
    assert r_cal.status_code == 200
    cal_data = r_cal.json()
    assert cal_data.get("status") == "success"
    assert "version" in cal_data
    assert cal_data.get("fno_stock_count") >= 200
