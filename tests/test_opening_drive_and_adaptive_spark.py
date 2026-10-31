"""
tests/test_opening_drive_and_adaptive_spark.py
───────────────────────────────────────────────
Unit tests validating full-universe Opening Drive screening,
adaptive trend-day RVOL floors in Intraday Spark, and
index call breadth decoupling on verified markup trends.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pandas as pd

from engine.detectors.intraday_spark import detect_intraday_mover_sparks
from engine.detectors.opening_drive import detect_opening_drive
from engine.detectors.index_call_setup import detect_index_call_setup

IST = ZoneInfo("Asia/Kolkata")


def test_opening_drive_catches_open_equals_low_runner():
    """Verify OpeningDrive detects clean Open == Low expansion (e.g. COFORGE archetype)."""
    # 5m bar with Open == Low
    dates = [datetime(2026, 10, 30, 9, 15, tzinfo=IST)]
    df_5m = pd.DataFrame(
        {
            "open": [1972.0],
            "high": [2013.7],
            "low": [1972.0],  # Open == Low!
            "close": [2008.0],
            "volume": [241469.0],
        },
        index=dates,
    )

    alert = detect_opening_drive(
        symbol="COFORGE",
        df_5m=df_5m,
        ltp=2008.0,
        vwap=2000.0,
        rvol=2.5,
        ref_time=datetime(2026, 10, 30, 9, 20, tzinfo=IST),
        prev_close=1962.0,
        prev_high=1975.0,
        prev_low=1940.0,
        ignore_time_gate=True,
    )

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert "COFORGE" in alert.symbol
    assert alert.metrics.get("bar_open") == 1972.0
    assert alert.metrics.get("open_pattern") == "OPEN_EQUALS_LOW"
    assert alert.underlying_spot == 2008.0


def test_intraday_spark_adaptive_rvol_on_trend_markup(monkeypatch):
    """Verify IntradaySpark fires on quiet trend-day markups with RVOL 1.25x when change_pct >= 1.8%."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    q_mock = MagicMock()
    q_mock.last_price = 3020.0
    q_mock.change_pct = 2.10  # Strong move > 1.8%
    q_mock.volume = 500000
    q_mock.vwap = 3000.0  # Above VWAP
    q_mock.upper_circuit = 0.0
    q_mock.lower_circuit = 0.0
    q_mock.circuit_limit = 0.0

    # In a quiet trend day, RVOL is 1.25x (below 1.50x standard floor, but above 1.15x adaptive floor)
    with patch("engine.detectors.intraday_spark.get_cached_avg_volume_20", return_value=400000):
        with patch("engine.auto_alert_engine.compute_time_of_day_rvol", return_value=1.25):
            with patch(
                "engine.detectors.intraday_spark.compute_time_of_day_rvol", return_value=1.25
            ):
                with patch("market.sentiment.get_market_breadth", return_value=None):
                    alerts = detect_intraday_mover_sparks(
                        universe=["TRENT"],
                        quotes_map={"NSE:TRENT": q_mock},
                    )

                    assert len(alerts) == 1
                    assert alerts[0].direction == "BULLISH"
                    assert alerts[0].symbol == "TRENT"


def test_index_call_setup_bypasses_breadth_on_strong_vwap_trend():
    """Verify IndexCallSetup overrides negative broad breadth when index itself is firmly above VWAP."""
    contract = MagicMock()
    contract.symbol = "NIFTY26N0323000CE"
    contract.strike = 23000.0
    contract.option_type = "CE"
    contract.last_price = 120.0
    contract.volume = 150000
    contract.oi = 100000
    contract.oi_change = -5000
    contract.pchange = 18.0

    # Mock negative breadth (A/D ratio 0.45)
    mb_mock = MagicMock()
    mb_mock.verdict = "BROAD_DECLINE"
    mb_mock.ad_ratio = 0.45
    mb_mock.advances = 150
    mb_mock.declines = 350

    with patch("market.sentiment.get_market_breadth", return_value=mb_mock):
        alerts = detect_index_call_setup(
            underlying="NIFTY",
            spot=23050.0,
            chain=[contract],
            vwap=23000.0,  # Spot is +0.22% above VWAP
            day_high=23060.0,
            day_low=22905.0,  # Bounced from low
            prev_day_high=22980.0,
            prev_day_low=22850.0,
            prev_close=22960.0,  # Spot is +0.39% from prev_close
            ref_time=datetime(2026, 10, 30, 10, 30, tzinfo=IST),
            ignore_time_gate=True,
        )

        assert len(alerts) >= 1
        assert alerts[0].direction == "BULLISH"


def test_banknifty_opening_drive_requires_dual_locomotive_alignment():
    """Verify BankNifty opening drive vetoes when HDFCBANK or ICICIBANK opposes the move."""
    dates = [datetime(2026, 10, 30, 9, 15, tzinfo=IST)]
    df_5m = pd.DataFrame(
        {
            "open": [49000.0],
            "high": [49250.0],
            "low": [49000.0],  # Open == Low
            "close": [49200.0],
            "volume": [150000.0],
        },
        index=dates,
    )

    # Mock heavyweights posture where 3 mid-tier banks are bullish, but HDFCBANK is bearish
    opposed_posture = {
        "heavyweights": [
            {"symbol": "HDFCBANK", "change_pct": -0.85, "is_bullish": False, "is_bearish": True},
            {"symbol": "ICICIBANK", "change_pct": 0.40, "is_bullish": True, "is_bearish": False},
            {"symbol": "SBIN", "change_pct": 0.50, "is_bullish": True, "is_bearish": False},
            {"symbol": "AXISBANK", "change_pct": 0.30, "is_bullish": True, "is_bearish": False},
            {"symbol": "KOTAKBANK", "change_pct": 0.25, "is_bullish": True, "is_bearish": False},
        ],
        "bull_count": 4,
        "bear_count": 1,
        "all_bullish": False,
        "all_bearish": False,
    }

    aligned_posture = {
        "heavyweights": [
            {"symbol": "HDFCBANK", "change_pct": 0.65, "is_bullish": True, "is_bearish": False},
            {"symbol": "ICICIBANK", "change_pct": 0.80, "is_bullish": True, "is_bearish": False},
            {"symbol": "SBIN", "change_pct": 0.50, "is_bullish": True, "is_bearish": False},
            {"symbol": "AXISBANK", "change_pct": 0.30, "is_bullish": True, "is_bearish": False},
            {"symbol": "KOTAKBANK", "change_pct": 0.25, "is_bullish": True, "is_bearish": False},
        ],
        "bull_count": 5,
        "bear_count": 0,
        "all_bullish": True,
        "all_bearish": False,
    }

    # 1. Opposed: HDFCBANK is bearish -> VETOED
    with patch("market.indices.get_heavyweights_posture", return_value=opposed_posture):
        alert_vetoed = detect_opening_drive(
            symbol="BANKNIFTY",
            df_5m=df_5m,
            ltp=49200.0,
            vwap=49100.0,
            rvol=2.0,
            ref_time=datetime(2026, 10, 30, 9, 20, tzinfo=IST),
            prev_close=48900.0,
            prev_high=49100.0,
            prev_low=48700.0,
            ignore_time_gate=True,
        )
        assert alert_vetoed is None

    # 2. Aligned: Both HDFCBANK and ICICIBANK are bullish -> ALLOWED
    with patch("market.indices.get_heavyweights_posture", return_value=aligned_posture):
        alert_allowed = detect_opening_drive(
            symbol="BANKNIFTY",
            df_5m=df_5m,
            ltp=49200.0,
            vwap=49100.0,
            rvol=2.0,
            ref_time=datetime(2026, 10, 30, 9, 20, tzinfo=IST),
            prev_close=48900.0,
            prev_high=49100.0,
            prev_low=48700.0,
            ignore_time_gate=True,
        )
        assert alert_allowed is not None
        assert alert_allowed.direction == "BULLISH"
