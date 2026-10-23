"""
tests/test_smt_sweep_and_horizon.py
───────────────────────────────────
Institutional test suite for:
  1. Offensive SMT Liquidity Sweep & Locomotive Polarization Detector (engine/detectors/smt_sweep.py)
  2. SMT Divergence Non-Confirmation & Bull/Bear Traps
  3. Session Runway Index F&O Calibration (engine/session_runway.py)
  4. Dynamic Capitulation Scrutiny Expansion (engine/alert_scrutiny.py)
  5. Strategic Horizon Forward-Looking Battleground Synthesis (engine/strategic_horizon.py)
  6. Strategic Horizon Web API Endpoint (web/routers/market_data.py)
"""

from __future__ import annotations

import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi.testclient import TestClient

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.detectors.smt_sweep import detect_smt_sweep
from engine.session_runway import (
    evaluate_session_runway,
)
from engine.strategic_horizon import (
    StrategicHorizonReport,
    generate_strategic_horizon,
)
from web.api import app

IST = ZoneInfo("Asia/Kolkata")


def _generate_synthetic_5m_bars(
    last_price: float,
    high_price: float,
    low_price: float,
    vwap: float,
    num_bars: int = 40,
) -> pd.DataFrame:
    """Generates synthetic 5m OHLCV bars for detector testing."""
    times = pd.date_range("2026-10-21 09:15:00", periods=num_bars, freq="5min", tz="Asia/Kolkata")
    records = []
    base = vwap
    for i in range(num_bars - 1):
        c = base + (i * 2.0)
        records.append(
            {
                "datetime": times[i],
                "open": c - 5.0,
                "high": c + 10.0,
                "low": c - 10.0,
                "close": c,
                "volume": 25000,
                "vwap": vwap,
            }
        )
    # Last candle testing high or low with rejection wick
    records.append(
        {
            "datetime": times[-1],
            "open": last_price - 5.0,
            "high": high_price,
            "low": low_price,
            "close": last_price,
            "volume": 60000,
            "vwap": vwap,
        }
    )
    df = pd.DataFrame(records)
    df.set_index("datetime", inplace=True)
    return df


def _build_mock_chain(spot: float, symbol: str) -> list[Any]:
    """Builds realistic CE & PE options chain around the index spot."""
    step = 100.0 if symbol in ("BANKNIFTY", "SENSEX") else 50.0
    chain = []
    atm = round(spot / step) * step

    for offset in (-2, -1, 0, 1, 2):
        k = atm + (offset * step)
        # Call
        chain.append(
            SimpleNamespace(
                symbol=f"{symbol}{int(k)}CE",
                strike=k,
                option_type="CE",
                last_price=max(5.0, 150.0 - (offset * 35.0)),
                volume=45000,
                oi=120000,
            )
        )
        # Put
        chain.append(
            SimpleNamespace(
                symbol=f"{symbol}{int(k)}PE",
                strike=k,
                option_type="PE",
                last_price=max(5.0, 150.0 + (offset * 35.0)),
                volume=52000,
                oi=140000,
            )
        )
    return chain


# -------------------------------------------------------------------------
# 1. Bearish SMT Sweep at Day High with Sibling Non-Confirmation
# -------------------------------------------------------------------------
def test_bearish_smt_sweep_detection_sibling_nonconfirmation():
    """
    NIFTY is sweeping day high (25,000), but sibling BANKNIFTY is trapped below VWAP (51,500 vs 51,800).
    Must trigger an offensive Bearish SMT Sweep with tight SL pegged above day high.
    """
    spot = 24995.0
    day_high = 25000.0
    day_low = 24800.0
    vwap = 24900.0

    df_5m = _generate_synthetic_5m_bars(spot, day_high, day_low, vwap)
    chain = _build_mock_chain(spot, "NIFTY")

    quotes_map = {
        "BANKNIFTY": {
            "ltp": 51500.0,
            "vwap": 51800.0,
            "high": 52100.0,
            "low": 51400.0,
        }
    }

    alerts = detect_smt_sweep(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ignore_time_gate=True,
        quotes_map=quotes_map,
    )

    assert len(alerts) >= 1
    a = alerts[0]
    assert isinstance(a, AutoAlert)
    assert a.direction == "BEARISH"
    assert a.alert_type == "SMT_SWEEP"
    assert a.metrics.get("invalidation_spot") > day_high
    assert a.target_level > a.ltp  # Option premium target > entry
    assert "SMT REVERSAL" in a.headline
    assert "trapped below VWAP" in a.summary


# -------------------------------------------------------------------------
# 2. Bearish SMT Sweep via Locomotive Polarization Distribution
# -------------------------------------------------------------------------
def test_bearish_smt_sweep_locomotive_polarization():
    """
    NIFTY is at day high (25,000), but market breadth is collapsing (A/D = 0.30)
    and heavyweights are artificially propping the index (Locomotive Polarization).
    Must trigger an offensive Bearish SMT Sweep.
    """
    spot = 24998.0
    day_high = 25000.0
    day_low = 24850.0
    vwap = 24920.0

    df_5m = _generate_synthetic_5m_bars(spot, day_high, day_low, vwap)
    chain = _build_mock_chain(spot, "NIFTY")

    mock_regime = MagicMock()
    mock_regime.is_locomotive_polarized = True
    mock_regime.locomotive_detail = "RELIANCE, HDFCBANK pumped while 38 of Nifty 50 declining"
    mock_regime.ad_ratio = 0.32

    with patch("engine.market_regime_gate.evaluate_market_regime", return_value=mock_regime):
        alerts = detect_smt_sweep(
            underlying="NIFTY",
            spot=spot,
            chain=chain,
            vwap=vwap,
            day_high=day_high,
            day_low=day_low,
            ohlcv_5m=df_5m,
            ignore_time_gate=True,
            quotes_map={},
        )

        assert len(alerts) >= 1
        a = alerts[0]
        assert a.direction == "BEARISH"
        assert a.alert_type == "SMT_SWEEP"
        assert a.metrics.get("invalidation_spot") > day_high
        assert "LOCOMOTIVE POLARIZATION TRAP" in a.headline


# -------------------------------------------------------------------------
# 3. Bullish SMT Sweep (Wyckoff Spring) at Day Low
# -------------------------------------------------------------------------
def test_bullish_smt_sweep_wyckoff_spring():
    """
    BANKNIFTY sweeps day low (51,400), but sibling NIFTY is holding strong above VWAP.
    Must trigger an offensive Bullish SMT Sweep / Wyckoff Spring with tight SL below day low.
    """
    spot = 51410.0
    day_high = 52200.0
    day_low = 51400.0
    vwap = 51800.0

    df_5m = _generate_synthetic_5m_bars(spot, day_high, day_low, vwap)
    chain = _build_mock_chain(spot, "BANKNIFTY")

    quotes_map = {
        "NIFTY": {
            "ltp": 25050.0,
            "vwap": 24950.0,
            "high": 25100.0,
            "low": 24920.0,
        }
    }

    alerts = detect_smt_sweep(
        underlying="BANKNIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ignore_time_gate=True,
        quotes_map=quotes_map,
    )

    assert len(alerts) >= 1
    a = alerts[0]
    assert a.direction == "BULLISH"
    assert a.alert_type == "SMT_SWEEP"
    assert a.metrics.get("invalidation_spot") < day_low
    assert "SMT SPRING" in a.headline


# -------------------------------------------------------------------------
# 4. Session Runway Index F&O RVOL Calibration
# -------------------------------------------------------------------------
def test_session_runway_index_fno_exemption():
    """
    During MORNING_REVERSAL_ZONE (10:30) and MIDDAY_COMPRESSION (12:00),
    equity setups require RVOL >= 2.2 and 1.8.
    Index F&O setups must have a calibrated threshold of min_rvol = 1.0 to avoid locking out clean trends.
    """
    reversal_dt = datetime(2026, 10, 21, 10, 30, tzinfo=IST)
    midday_dt = datetime(2026, 10, 21, 12, 0, tzinfo=IST)

    os.environ["FORCE_RUNWAY_CHECK"] = "1"
    try:
        # 1. Equity setup with RVOL 1.3 during reversal zone -> should FAIL (min 2.2 required)
        equity_eval = evaluate_session_runway(
            symbol="RELIANCE",
            alert_type="INTRADAY_MOVER_SPARK",
            time_horizon="INTRADAY",
            segment="EQUITY",
            rvol=1.3,
            now_dt=reversal_dt,
        )
        assert equity_eval.is_allowed is False
        assert "Morning Reversal Trap" in (equity_eval.veto_reason or "")

        # 2. Index F&O setup with RVOL 1.1 during reversal zone -> should PASS (min 1.0 calibrated)
        index_rev_eval = evaluate_session_runway(
            symbol="NIFTY",
            alert_type="SMT_SWEEP",
            time_horizon="INTRADAY",
            segment="FNO_INDEX",
            rvol=1.1,
            now_dt=reversal_dt,
        )
        assert index_rev_eval.is_allowed is True

        # 3. Index F&O setup with RVOL 1.1 during midday compression -> should PASS (min 1.0 calibrated)
        index_mid_eval = evaluate_session_runway(
            symbol="BANKNIFTY",
            alert_type="INDEX_PUT_SETUP",
            time_horizon="INTRADAY",
            segment="FNO_INDEX",
            rvol=1.1,
            now_dt=midday_dt,
        )
        assert index_mid_eval.is_allowed is True
    finally:
        os.environ.pop("FORCE_RUNWAY_CHECK", None)


# -------------------------------------------------------------------------
# 5. Dynamic Capitulation Expansion in Alert Scrutiny
# -------------------------------------------------------------------------
def test_dynamic_capitulation_scrutiny_expansion():
    """
    Static VWAP extension cap is 0.65%.
    When an index alert exhibits verified trend expansion (SMT_SWEEP or A/D <= 0.45),
    the scrutiny cap dynamically expands up to 1.25% for NIFTY.
    """
    vwap = 25000.0
    extended_ltp = 24787.5  # -0.85% below VWAP

    # 1. Unconfirmed generic alert at -0.85% below VWAP -> fails with Capitulation Exhaustion
    generic_alert = AutoAlert(
        alert_id="aa-precursor-radar-nifty-20261021",
        alert_type="PRECURSOR_RADAR",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="NIFTY Generic Breakdown",
        summary="Test Generic",
        ltp=extended_ltp,
        trigger_level=extended_ltp,
        target_level=24200.0,
        stop_loss=25010.0,
        confidence=80,
        time_horizon="INTRADAY",
        environment="LIVE",
        underlying_spot=extended_ltp,
        metrics={"vwap": vwap, "spot_to_vwap_pct": -0.85},
    )

    auditor = AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)

    with patch("market.sentiment.get_market_breadth") as mock_mb:
        mock_mb_inst = MagicMock()
        mock_mb_inst.verdict = "NEUTRAL"
        mock_mb_inst.ad_ratio = 1.0
        mock_mb.return_value = mock_mb_inst

        gen_passed, gen_reason, _ = auditor.verify_tier1_sanity(generic_alert)
        assert gen_passed is False
        assert "Capitulation Exhaustion" in gen_reason

    # 2. SMT_SWEEP alert at -0.85% below VWAP -> dynamically expands threshold to 1.25%, passes!
    smt_alert = AutoAlert(
        alert_id="aa-smt-sweep-nifty-20261021",
        alert_type="SMT_SWEEP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BEARISH",
        headline="NIFTY SMT Bearish Sweep",
        summary="Test SMT Sweep",
        ltp=extended_ltp,
        trigger_level=extended_ltp,
        target_level=24200.0,
        stop_loss=25010.0,
        confidence=88,
        time_horizon="INTRADAY",
        environment="LIVE",
        underlying_spot=extended_ltp,
        metrics={"vwap": vwap, "spot_to_vwap_pct": -0.85},
    )

    with patch("market.sentiment.get_market_breadth") as mock_mb:
        mock_mb_inst = MagicMock()
        mock_mb_inst.verdict = "BEARISH"
        mock_mb_inst.ad_ratio = 0.35
        mock_mb.return_value = mock_mb_inst

        smt_passed, smt_reason, smt_flags = auditor.verify_tier1_sanity(smt_alert)
        # Should NOT fail with Capitulation Exhaustion
        assert "Capitulation Exhaustion" not in smt_reason


# -------------------------------------------------------------------------
# 6. Strategic Horizon Synthesis Generation
# -------------------------------------------------------------------------
def test_strategic_horizon_generation():
    """
    Verifies that generate_strategic_horizon compiles a complete, mathematically
    grounded StrategicHorizonReport with battleground levels and tactical coaching.
    """
    mock_quote = MagicMock()
    mock_quote.last_price = 24850.0
    mock_quote.high = 25010.0
    mock_quote.low = 24780.0
    mock_quote.vwap = 24920.0

    with (
        patch("market.quotes.get_quote", return_value={"NSE:NIFTY": mock_quote}),
        patch("market.sentiment.get_market_breadth") as mock_mb,
        patch("market.indices.get_vix", return_value=14.2),
    ):
        mock_mb_inst = MagicMock()
        mock_mb_inst.verdict = "BEARISH"
        mock_mb_inst.ad_ratio = 0.40
        mock_mb_inst.advances = 12
        mock_mb_inst.declines = 38
        mock_mb.return_value = mock_mb_inst

        report = generate_strategic_horizon("NIFTY")

        assert isinstance(report, StrategicHorizonReport)
        assert report.symbol == "NIFTY"
        assert report.spot == 24850.0
        assert report.vwap == 24920.0
        assert report.day_high == 25010.0
        assert report.day_low == 24780.0
        assert report.bias_direction in ("BEARISH", "BULLISH", "NEUTRAL")
        assert 0 <= report.conviction_score <= 100
        assert len(report.battleground_zone) > 0
        assert report.immediate_resistance >= report.spot or report.immediate_resistance > 0
        assert report.immediate_support <= report.spot or report.immediate_support > 0
        assert report.invalidation_level > 0
        assert len(report.actionable_coaching) > 0

        # Verify serialization
        r_dict = report.to_dict()
        assert r_dict["symbol"] == "NIFTY"
        assert "tactical_scenarios" in r_dict
        assert "market_breadth" in r_dict
        assert "smt_alignment" in r_dict


# -------------------------------------------------------------------------
# 7. Strategic Horizon FastAPI Web Endpoint
# -------------------------------------------------------------------------
def test_strategic_horizon_endpoint():
    """
    Tests GET /api/market/strategic-horizon via TestClient.
    """
    client = TestClient(app)
    response = client.get("/api/market/strategic-horizon?symbol=NIFTY")

    assert response.status_code == 200
    json_data = response.json()
    assert json_data.get("status") == "ok"
    data = json_data.get("data", {})
    assert data.get("symbol") == "NIFTY"
    assert "bias_direction" in data
    assert "conviction_score" in data
    assert "battleground_zone" in data
    assert "actionable_coaching" in data
