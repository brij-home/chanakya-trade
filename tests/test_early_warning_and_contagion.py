"""
tests/test_early_warning_and_contagion.py
─────────────────────────────────────────
Unit & integration tests for institutional early-warning and precision timing improvements:
  1. Time-of-Day RVOL (TOD-RVOL)
  2. Index Heavyweight Lead-Lag Contagion Engine
  3. Multi-Timeframe (15m/5m) Volatility Squeeze
  4. High-Velocity Options OI Rate Unwinding
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from brokers.base import OptionsContract, Quote
from engine.auto_alert_engine import (
    compute_time_of_day_rvol,
    expected_volume_fraction,
    auto_alert_engine,
)
from engine.detectors.gamma_blast import detect_gamma_blast, _STRIKE_OI_SNAPSHOTS
from engine.detectors.squeeze_breakout import detect_squeeze_breakout
from engine.index_contagion import index_contagion_engine, IndexContagionResult

IST = ZoneInfo("Asia/Kolkata")


class TestTimeOfDayRvol:
    """Validates institutional Time-of-Day cumulative volume normalization."""

    def test_expected_volume_fraction_progression(self):
        # Pre-market
        assert expected_volume_fraction(-10) == 0.03
        # 09:30 IST (15 mins from 09:15)
        assert round(expected_volume_fraction(15), 2) == 0.12
        # 10:00 IST (45 mins from 09:15)
        assert round(expected_volume_fraction(45), 2) == 0.25
        # 11:30 IST (135 mins)
        assert round(expected_volume_fraction(135), 2) == 0.45
        # 13:30 IST (255 mins)
        assert round(expected_volume_fraction(255), 2) == 0.63
        # 15:00 IST (345 mins)
        assert round(expected_volume_fraction(345), 2) == 0.85
        # 15:30 IST (375 mins - market close)
        assert expected_volume_fraction(375) == 1.0
        assert expected_volume_fraction(400) == 1.0

    def test_tod_rvol_morning_vs_full_day(self):
        avg_daily_vol = 1_000_000.0

        # At 09:30 IST, current volume is 240,000 shares (24% of daily volume)
        dt_0930 = datetime(2026, 9, 15, 9, 30, tzinfo=IST)
        rvol_0930 = compute_time_of_day_rvol(240_000, avg_daily_vol, ref_dt=dt_0930)
        # Expected volume fraction at 09:30 is 12% (120,000 shares)
        # Therefore, TOD-RVOL = 240,000 / 120,000 = 2.0x!
        assert rvol_0930 == 2.0

        # At 15:30 IST, current volume is 2,000,000 shares (200% of daily volume)
        dt_1530 = datetime(2026, 9, 15, 15, 30, tzinfo=IST)
        rvol_1530 = compute_time_of_day_rvol(2_000_000, avg_daily_vol, ref_dt=dt_1530)
        assert rvol_1530 == 2.0


class TestIndexContagionEngine:
    """Validates heavyweights synchronization engine for NIFTY & BANKNIFTY."""

    def test_banknifty_bullish_synchronization(self):
        dt = datetime(2026, 9, 15, 10, 15, tzinfo=IST)

        # Mock quotes where HDFCBANK and ICICIBANK (>52% weight) are surging above VWAP
        quotes = {
            "NSE:BANKNIFTY": Quote(symbol="BANKNIFTY", last_price=54000.0, vwap=53950.0, change_pct=0.30),
            "NSE:HDFCBANK": Quote(symbol="HDFCBANK", last_price=1750.0, vwap=1740.0, change_pct=1.2, volume=800_000, high=1751.0),
            "NSE:ICICIBANK": Quote(symbol="ICICIBANK", last_price=1320.0, vwap=1310.0, change_pct=1.1, volume=700_000, high=1321.0),
            "NSE:SBIN": Quote(symbol="SBIN", last_price=840.0, vwap=835.0, change_pct=0.8, volume=500_000, high=841.0),
            "NSE:AXISBANK": Quote(symbol="AXISBANK", last_price=1220.0, vwap=1218.0, change_pct=0.4, volume=300_000, high=1222.0),
            "NSE:KOTAKBANK": Quote(symbol="KOTAKBANK", last_price=1880.0, vwap=1882.0, change_pct=-0.1, volume=200_000, high=1885.0),
        }

        res = index_contagion_engine.evaluate_index("BANKNIFTY", quotes_map=quotes, ref_dt=dt)
        assert res is not None
        assert res.index_name == "BANKNIFTY"
        # Over 70% weight should be bullish (HDFC + ICICI + SBIN + AXIS > 80%)
        assert res.bullish_weight_pct >= 70.0
        assert res.alert is not None
        assert res.alert.alert_type == "INDEX_CONTAGION"
        assert res.alert.direction == "BULLISH"
        assert res.alert.stage == "EARLY_WARNING"
        assert "HEAVYWEIGHT CONTAGION" in res.alert.headline

    def test_nifty_bearish_synchronization(self):
        dt = datetime(2026, 9, 15, 11, 0, tzinfo=IST)

        quotes = {
            "NSE:NIFTY": Quote(symbol="NIFTY", last_price=25000.0, vwap=25050.0, change_pct=-0.35),
            "NSE:HDFCBANK": Quote(symbol="HDFCBANK", last_price=1710.0, vwap=1725.0, change_pct=-1.1, volume=800_000, low=1709.0),
            "NSE:RELIANCE": Quote(symbol="RELIANCE", last_price=2950.0, vwap=2975.0, change_pct=-1.0, volume=600_000, low=2948.0),
            "NSE:ICICIBANK": Quote(symbol="ICICIBANK", last_price=1280.0, vwap=1295.0, change_pct=-1.2, volume=700_000, low=1279.0),
            "NSE:INFY": Quote(symbol="INFY", last_price=1850.0, vwap=1870.0, change_pct=-0.9, volume=400_000, low=1849.0),
            "NSE:TCS": Quote(symbol="TCS", last_price=4200.0, vwap=4230.0, change_pct=-0.8, volume=250_000, low=4198.0),
            "NSE:LT": Quote(symbol="LT", last_price=3600.0, vwap=3620.0, change_pct=-0.6, volume=200_000, low=3598.0),
            "NSE:BHARTIARTL": Quote(symbol="BHARTIARTL", last_price=1600.0, vwap=1605.0, change_pct=-0.4, volume=200_000, low=1598.0),
            "NSE:SBIN": Quote(symbol="SBIN", last_price=820.0, vwap=828.0, change_pct=-1.0, volume=500_000, low=819.0),
        }

        res = index_contagion_engine.evaluate_index("NIFTY", quotes_map=quotes, ref_dt=dt)
        assert res is not None
        assert res.bearish_weight_pct >= 70.0
        assert res.alert is not None
        assert res.alert.direction == "BEARISH"
        assert "HEAVYWEIGHT BREAKDOWN" in res.alert.headline


class TestMultiTimeframeSqueeze:
    """Validates 15m intraday TTM squeeze coiling detection."""

    def test_intraday_squeeze_early_warning(self):
        # Create synthetic 15m coiling candles where BB is inside Keltner
        np.random.seed(42)
        n = 30
        base = 54000.0
        # Very tight range to force BB inside KC
        closes = [base + np.sin(i / 2.0) * 15.0 for i in range(n)]
        highs = [c + 12.0 for c in closes]
        lows = [c - 12.0 for c in closes]
        vols = [10000 + i * 100 for i in range(n)]

        df = pd.DataFrame({
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": vols,
        })

        pivot_h = float(np.max(highs[-20:-1]))
        ltp = pivot_h - 10.0  # Within 0.2% of pivot

        alert = detect_squeeze_breakout("BANKNIFTY", df, ltp=ltp, timeframe="15m")
        assert alert is not None
        assert alert.stage == "EARLY_WARNING"
        assert alert.direction == "BULLISH"
        assert "SQUEEZE COILING" in alert.headline


class TestOptionsOiVelocity:
    """Validates high-velocity short-term unwinding detection in options."""

    def test_call_writer_panic_unwind_velocity(self):
        underlying = "NIFTY"
        spot = 25000.0
        _STRIKE_OI_SNAPSHOTS.clear()

        # Snapshot 1 at t=0
        c1 = OptionsContract(
            symbol="NIFTY25000CE",
            underlying="NIFTY",
            strike=25000.0,
            option_type="CE",
            expiry="2026-09-17",
            last_price=120.0,
            volume=5000,
            oi=80000,
            oi_change=-2000,
            pchange=5.0,
        )
        detect_gamma_blast(underlying, spot, [c1])

        # Snapshot 2: 60s later, OI drops from 80,000 to 65,000 (shedding 15,000 contracts in 60s)
        # Mocking time.time to advance by 60s
        with patch("time.time", side_effect=[1000.0, 1060.0, 1060.0]):
            _STRIKE_OI_SNAPSHOTS["NIFTY_25000_CE"] = (1000.0, 80000, 5000)
            c2 = OptionsContract(
                symbol="NIFTY25000CE",
                underlying="NIFTY",
                strike=25000.0,
                option_type="CE",
                expiry="2026-09-17",
                last_price=135.0,
                volume=25000,
                oi=65000,
                oi_change=-15000,
                pchange=8.0,
            )
            alerts = detect_gamma_blast(underlying, spot, [c2], vwap=24990.0)
            assert len(alerts) > 0
            assert alerts[0].alert_type == "GAMMA_BLAST"
            assert alerts[0].direction == "BULLISH"
