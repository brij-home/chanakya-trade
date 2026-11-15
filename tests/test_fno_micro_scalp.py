"""
tests/test_fno_micro_scalp.py
──────────────────────────────
Unit tests for Fast-Tier Single-Stock F&O Micro Scalp Detector:
1. Detects high-speed opening momentum on catalyst F&O stocks (e.g., APOLLOHOSP, POWERINDIA)
   between 09:16 and 09:25 IST on 1m/3m bars.
2. Formulates fast scalp blueprint (+1.5R T1, +2.8R T2, Runner) with tight spot/option stops.
3. Suppresses micro-scalps during midday chop lull (11:15–13:15 IST).
"""

from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pandas as pd

from engine.detectors.index_micro_scalp import detect_fno_micro_scalp

IST = ZoneInfo("Asia/Kolkata")


def _make_mock_contract(
    symbol: str, strike: float, opt_type: str, ltp: float, vol: int = 500, oi: int = 1000
):
    return SimpleNamespace(
        symbol=symbol,
        strike=strike,
        option_type=opt_type,
        last_price=ltp,
        volume=vol,
        oi=oi,
        pchange=18.0,
        change_pct=18.0,
    )


def test_fno_micro_scalp_opening_catalyst_bullish():
    """Verify that APOLLOHOSP 8500 CE is captured at 09:18 IST on Open=Low drive."""
    # 09:18 IST
    ref_dt = datetime(2026, 11, 14, 9, 18, tzinfo=IST)

    spot = 8480.0
    spot_open = 8460.0
    day_low = 8460.0  # Open == Low drive!
    day_high = 8520.0

    chain = [
        _make_mock_contract("APOLLOHOSP8400CE", 8400.0, "CE", 220.0, vol=600, oi=1200),
        _make_mock_contract("APOLLOHOSP8500CE", 8500.0, "CE", 170.0, vol=1500, oi=2200),
        _make_mock_contract("APOLLOHOSP8500PE", 8500.0, "PE", 140.0, vol=400, oi=1500),
        _make_mock_contract("APOLLOHOSP8600CE", 8600.0, "CE", 125.0, vol=800, oi=1800),
    ]

    ohlcv_1m = pd.DataFrame(
        [
            {"open": 8460.0, "high": 8472.0, "low": 8460.0, "close": 8470.0, "volume": 12000},
            {"open": 8470.0, "high": 8485.0, "low": 8468.0, "close": 8480.0, "volume": 18000},
        ]
    )

    with patch("engine.position_sizer.get_lot_size", return_value=125):
        alerts = detect_fno_micro_scalp(
            underlying="APOLLOHOSP",
            spot=spot,
            chain=chain,
            ohlcv_1m=ohlcv_1m,
            vwap=8470.0,
            day_high=day_high,
            day_low=day_low,
            spot_open=spot_open,
            spot_change_pct=1.8,
            ref_time=ref_dt,
        )

    assert len(alerts) >= 1
    a = alerts[0]
    assert a.symbol == "APOLLOHOSP"
    assert a.segment == "FNO_STOCK"
    assert a.alert_type == "INDEX_MICRO_SCALP"
    assert a.direction == "BULLISH"
    assert a.time_horizon == "SCALP"
    assert a.option_type == "CE"
    assert a.strike == 8500.0
    assert a.trigger_level == 170.0
    # Stop loss ~9% risk (approx 15.3 pts -> SL 154.7)
    assert a.stop_loss < 170.0
    assert a.target_1 > 170.0
    assert a.lot_size == 125
    assert "Micro Scalp" in a.headline


def test_fno_micro_scalp_suppressed_during_midday_chop():
    """Verify that single-stock micro-scalp breakouts are suppressed during 11:15–13:15 IST midday lull."""
    # 12:15 IST (midday lull)
    ref_dt = datetime(2026, 11, 14, 12, 15, tzinfo=IST)

    spot = 8480.0
    chain = [
        _make_mock_contract("APOLLOHOSP8500CE", 8500.0, "CE", 170.0, vol=500, oi=1200),
    ]

    with (
        patch("engine.position_sizer.get_lot_size", return_value=125),
        patch("engine.detectors.index_micro_scalp.os.environ.get", return_value="0"),
    ):
        alerts = detect_fno_micro_scalp(
            underlying="APOLLOHOSP",
            spot=spot,
            chain=chain,
            ref_time=ref_dt,
            ignore_time_gate=False,
        )

    assert len(alerts) == 0
