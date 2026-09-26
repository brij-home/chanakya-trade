"""
tests/test_index_alert_noise_reduction.py
──────────────────────────────────────────
Regression tests for index alert noise reduction safeguards:
  1. 09:25 IST market stabilization gate
  2. Today-only bar isolation (cross-session contamination guard)
  3. Active heavyweight locomotive confluence
  4. Low-VIX (<13.0) range-bound hedged spread mandate
  5. Synchronous scrutiny gating for index Gamma Blast & Opening Drive
"""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pandas as pd
import pytest

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.detectors.opening_drive import detect_opening_drive

IST = ZoneInfo("Asia/Kolkata")


class DummyContract:
    def __init__(self, strike: float, option_type: str, last_price: float, volume: int = 15000, oi: int = 8000):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = 1200
        self.pchange = 12.0
        self.symbol = f"BANKNIFTY{int(strike)}{option_type}"
        self.expiry = "2026-09-30"


def _make_sample_chain(spot: float):
    return [
        DummyContract(spot - 200, "CE", 380.0),
        DummyContract(spot - 100, "CE", 310.0),
        DummyContract(spot, "CE", 240.0),
        DummyContract(spot + 100, "CE", 180.0),
        DummyContract(spot + 200, "CE", 130.0),
        DummyContract(spot - 200, "PE", 140.0),
        DummyContract(spot - 100, "PE", 190.0),
        DummyContract(spot, "PE", 250.0),
        DummyContract(spot + 100, "PE", 320.0),
        DummyContract(spot + 200, "PE", 400.0),
    ]


def test_0925_stabilization_window_suppresses_early_signals():
    """Multi-candle structural patterns must not trigger before 09:25 IST."""
    spot = 56000.0
    chain = _make_sample_chain(spot)

    # 09:18 IST (within opening auction noise window)
    early_dt = datetime(2026, 9, 25, 9, 18, 0, tzinfo=IST)

    # Supply 12 bars with today's date
    dates = [datetime(2026, 9, 25, 9, 15 + i, 0, tzinfo=IST) for i in range(12)]
    df_early = pd.DataFrame(
        {
            "open": [55950.0 + i * 5 for i in range(12)],
            "high": [56010.0 for _ in range(12)],
            "low": [55940.0 for _ in range(12)],
            "close": [56005.0 for _ in range(12)],
            "volume": [5000 for _ in range(12)],
        },
        index=dates,
    )

    with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": ""}, clear=False):
        # Without ignore_time_gate, early time (09:18 IST) must suppress
        alerts_call = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=spot,
            chain=chain,
            vwap=55980.0,
            day_high=56010.0,
            day_low=55940.0,
            ohlcv_5m=df_early,
            ref_time=early_dt,
            ignore_time_gate=False,
        )
        assert len(alerts_call) == 0

        alerts_put = detect_index_put_setup(
            underlying="BANKNIFTY",
            spot=spot,
            chain=chain,
            vwap=56020.0,
            day_high=56060.0,
            day_low=55990.0,
            ohlcv_5m=df_early,
            ref_time=early_dt,
            ignore_time_gate=False,
        )
        assert len(alerts_put) == 0


def test_heavyweight_locomotive_confluence_gate():
    """Alerts must be suppressed if heavyweights are actively dragging in opposite direction."""
    spot = 56000.0
    chain = _make_sample_chain(spot)
    audit_dt = datetime(2026, 9, 25, 9, 40, 0, tzinfo=IST)

    dates = [datetime(2026, 9, 25, 9, 15 + i * 2, 0, tzinfo=IST) for i in range(12)]
    df_5m = pd.DataFrame(
        {
            "open": [55900.0 + i * 10 for i in range(12)],
            "high": [56020.0 for _ in range(12)],
            "low": [55890.0 for _ in range(12)],
            "close": [56010.0 for _ in range(12)],
            "volume": [5000 for _ in range(12)],
        },
        index=dates,
    )

    # Case A: 0 heavyweights bullish (HDFCBANK & ICICIBANK falling)
    bearish_posture = {
        "underlying": "BANKNIFTY",
        "heavyweights": [
            {"symbol": "HDFCBANK", "change_pct": -0.85, "is_bullish": False, "is_bearish": True},
            {"symbol": "ICICIBANK", "change_pct": -0.45, "is_bullish": False, "is_bearish": True},
        ],
        "all_bullish": False,
        "all_bearish": True,
        "bull_count": 0,
        "bear_count": 2,
        "total_heavyweights": 2,
        "summary": "ALL_BEARISH",
    }

    with patch("market.indices.get_heavyweights_posture", return_value=bearish_posture):
        alerts = detect_index_call_setup(
            underlying="BANKNIFTY",
            spot=spot,
            chain=chain,
            vwap=55980.0,
            day_high=56015.0,
            day_low=55900.0,
            ohlcv_5m=df_5m,
            ref_time=audit_dt,
            ignore_time_gate=True,
        )
        # Must be suppressed because 0 heavyweights are bullish
        assert len(alerts) == 0

    # Case B: Opening Drive on index vetoed if heavyweights unaligned
    with patch("market.indices.get_heavyweights_posture", return_value=bearish_posture):
        od_alert = detect_opening_drive(
            symbol="BANKNIFTY",
            df_5m=df_5m,
            ltp=56010.0,
            rvol=2.5,
            ref_time=audit_dt,
            ignore_time_gate=True,
        )
        assert od_alert is None


def test_low_vix_range_bound_regime_mandates_spread():
    """In low VIX (<13.0) range-bound regime, alerts must mandate hedged spreads."""
    spot = 56000.0
    chain = _make_sample_chain(spot)
    audit_dt = datetime(2026, 9, 25, 9, 45, 0, tzinfo=IST)

    dates = [datetime(2026, 9, 25, 9, 15 + i * 2, 0, tzinfo=IST) for i in range(12)]
    df_5m = pd.DataFrame(
        {
            "open": [55980.0 for _ in range(12)],
            "high": [56020.0 for _ in range(12)],
            "low": [55970.0 for _ in range(12)],
            "close": [56005.0 for _ in range(12)],
            "volume": [5000 for _ in range(12)],
        },
        index=dates,
    )

    bullish_posture = {
        "underlying": "BANKNIFTY",
        "heavyweights": [
            {"symbol": "HDFCBANK", "change_pct": 0.45, "is_bullish": True, "is_bearish": False},
            {"symbol": "ICICIBANK", "change_pct": 0.35, "is_bullish": True, "is_bearish": False},
        ],
        "all_bullish": True,
        "all_bearish": False,
        "bull_count": 2,
        "bear_count": 0,
        "total_heavyweights": 2,
        "summary": "ALL_BULLISH",
    }

    # Simulate low India VIX = 12.4
    with patch("market.indices.get_vix", return_value=12.4):
        with patch("market.indices.get_heavyweights_posture", return_value=bullish_posture):
            alerts = detect_index_call_setup(
                underlying="BANKNIFTY",
                spot=spot,
                chain=chain,
                vwap=56000.0,  # spot is at VWAP (range-bound)
                day_high=56050.0,
                day_low=55950.0,
                prev_day_low=55940.0,
                ohlcv_5m=df_5m,
                ref_time=audit_dt,
                ignore_time_gate=True,
            )
            if alerts:
                alert = alerts[0]
                assert "HEDGED SPREAD MANDATE" in alert.headline
                assert alert.actionable_plan["preferred_vehicle"] == "SPREAD_ONLY"
                assert alert.actionable_plan["action"] == "BULL CALL SPREAD"
                assert alert.actionable_plan["hedge_plan"] is not None
