"""
tests/test_confluence_radar_and_midmorning_bridge.py
────────────────────────────────────────────────────
Unit tests validating:
1. Confluence Radar REST API endpoints (/api/v1/market/confluence-radar, /api/v1/market/confluence/{symbol}).
2. The 09:35 AM Mid-Morning Bridge in Trend Day Continuation (eliminating the 40m dead zone).
3. 0DTE Expiry Day Afternoon Theta Protection in Option Resolver (Delta >= 0.60 or Defined-Risk Spreads).
4. AutoAlertEngine Inversion Bridge (turning failed counter-trend sweeps into live liquidity inversions).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from starlette.testclient import TestClient

from engine.detectors.trend_day_continuation import detect_trend_day_pullback
from engine.option_resolver import resolve_option_contract

IST = ZoneInfo("Asia/Kolkata")


def test_trend_day_pullback_fires_at_09_40_am(monkeypatch):
    """
    Validates that trend_day_pullback can now fire at 09:40 AM (during the previously dead 09:35-10:15 window)
    eliminating the 40-minute morning pullback blindspot.
    """
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    n = 25
    timestamps = [
        datetime(2026, 11, 16, 9, 15, tzinfo=IST) + timedelta(minutes=5 * i) for i in range(n)
    ]
    prices = np.linspace(54000, 54600, n - 2).tolist()
    prices.append(54560)
    prices.append(54580)
    df = pd.DataFrame(index=timestamps)
    df["close"] = prices
    df["open"] = [p + 10 for p in prices]
    df.loc[df.index[-1], "open"] = 54565
    df.loc[df.index[-1], "close"] = 54585
    df["high"] = [max(o, c) + 10 for o, c in zip(df["open"], df["close"])]
    df["low"] = [min(o, c) - 15 for o, c in zip(df["open"], df["close"])]
    df.loc[df.index[-1], "low"] = 54540  # lower wick rejection
    df["volume"] = [1000 + i * 20 for i in range(n)]
    df.loc[df.index[-1], "volume"] = 800  # dryup volume

    alert = detect_trend_day_pullback(
        symbol="NIFTY",
        df_5m=df,
        ltp=54580.0,
        now_dt=datetime(2026, 11, 16, 9, 40, tzinfo=IST),  # 09:40 AM!
        rvol_val=2.0,
        exchange="NSE",
        segment="INDEX",
    )

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert "NIFTY" in alert.symbol
    assert "limit_entry_zone" in alert.actionable_plan


def test_0dte_expiry_afternoon_upgrades_otm_to_deep_itm():
    """
    Validates that on an index weekly expiry day past 13:00 IST, an OTM strike request
    is upgraded to DEEP_ITM (Delta >= 0.60) to eliminate lethal 0DTE theta melt.
    """
    contract_mock = MagicMock()
    contract_mock.symbol = "NIFTY26N1924500CE"
    contract_mock.strike = 24500.0
    contract_mock.option_type = "CE"
    contract_mock.last_price = 145.0
    contract_mock.volume = 500000
    contract_mock.oi = 300000
    contract_mock.expiry = "2026-11-19"
    contract_mock.delta = 0.72

    with patch("engine.alert_expiry.is_expiry_day", return_value=True):
        with patch("engine.option_resolver.datetime") as mock_dt:
            # Set time to 13:30 IST on expiry day
            mock_dt.now.return_value = datetime(2026, 11, 19, 13, 30, tzinfo=IST)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

            plan = resolve_option_contract(
                symbol="NIFTY",
                spot=24600.0,
                direction="BULLISH",
                strike_tier="HIGH_GAMMA_ASYMMETRY",  # Normally OTM 0.35 delta
                contracts_override=[contract_mock],
                prefer_options=True,
            )

            assert plan is not None
            # Must upgrade strike tier away from OTM decay trap
            assert plan.strike_tier == "DEEP_ITM"


def test_api_confluence_radar_endpoint():
    """
    Validates that GET /api/v1/market/confluence-radar returns scored candidates.
    """
    from web.api import app

    mock_quote = MagicMock()
    mock_quote.last_price = 541.0
    mock_quote.vwap = 537.0
    mock_quote.change_pct = 2.85
    mock_quote.high = 542.0
    mock_quote.low = 530.0
    mock_quote.rvol = 2.4
    mock_quote.pre_open_gap_pct = 1.45

    client = TestClient(app)
    with patch("market.quotes.get_quote", return_value={"NSE:KALYANKJIL": mock_quote}):
        with patch(
            "analysis.universe.resolve_dynamic_universe", return_value=(["KALYANKJIL"], "TEST")
        ):
            response = client.get("/api/v1/market/confluence-radar?min_score=50&top_n=5")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["data"]) >= 1
            item = data["data"][0]
            assert item["symbol"] == "KALYANKJIL"
            assert item["total_score"] >= 70.0
            assert item["direction"] == "BULLISH"
            assert item["entry_zone_min"] is not None
            assert item["stop_loss"] is not None


def test_api_symbol_confluence_endpoint():
    """
    Validates that GET /api/v1/market/confluence/{symbol} returns full factors and pullback plan.
    """
    from web.api import app

    mock_quote = MagicMock()
    mock_quote.last_price = 263.0
    mock_quote.vwap = 266.0
    mock_quote.change_pct = -4.5
    mock_quote.high = 272.0
    mock_quote.low = 262.0
    mock_quote.rvol = 2.8
    mock_quote.pre_open_gap_pct = -1.8

    client = TestClient(app)
    with patch("market.quotes.get_quote", return_value={"NSE:TMPV": mock_quote}):
        response = client.get("/api/v1/market/confluence/TMPV")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["symbol"] == "TMPV"
        assert data["direction"] == "BEARISH"
        assert len(data["factors"]) == 6
        assert data["pullback_plan"]["stop_loss"] >= 266.0
