"""
tests/test_index_proximity.py
─────────────────────────────
Comprehensive Unit Tests for Index Options PRIMED Proximity Surveillance:
  1. Camarilla H4 Proximity (CALL setup: spot within 0.35% below H4).
  2. Day High Proximity (CALL setup: spot within 0.35% below Session High).
  3. Camarilla L4 Proximity (PUT setup: spot within 0.35% above L4).
  4. Day Low Proximity (PUT setup: spot within 0.35% above Session Low).
  5. Stage PRIMED, confidence >= 85, headline format, and blueprint integrity.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pandas as pd

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup

IST = timezone(timedelta(hours=5, minutes=30))


class MockContract:
    def __init__(
        self,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 25000,
        oi: int = 15000,
        oi_change: int = 2000,
        pchange: float = 6.0,
    ):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = oi_change
        self.pchange = pchange
        self.symbol = f"NIFTY{int(strike)}{option_type}"
        self.expiry = "2026-10-22"


def _make_dummy_5m_ohlcv(
    bars: int = 15, base_price: float = 25000.0, trend: str = "UP"
) -> pd.DataFrame:
    records = []
    curr = base_price
    start_time = datetime(2026, 10, 19, 9, 30, tzinfo=IST)
    for i in range(bars):
        t = start_time + timedelta(minutes=5 * i)
        step = 8.0 if trend == "UP" else (-8.0 if trend == "DOWN" else 0.0)
        o = curr
        h = o + 6.0
        l = o - 3.0
        c = o + step
        records.append(
            {
                "timestamp": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 12000 + (i * 200),
            }
        )
        curr = c
    df = pd.DataFrame(records)
    df.set_index("timestamp", inplace=True)
    return df


def test_camarilla_h4_proximity_call():
    """
    Spot is within 0.35% below Camarilla H4 with bullish posture.
    Must emit stage='PRIMED', confidence >= 85, and signal='CAMARILLA_H4_PROXIMITY'.
    """
    prev_day_high = 25000.0
    prev_day_low = 24850.0
    prev_close = 25050.0
    # Range = 150. H4 = 25050 + 150 * 1.1 / 2 = 25132.5
    # Let spot = 25115.0 -> distance to H4 is 17.5 pts (0.07%), well within 0.35%
    spot = 25115.0
    day_high = 25120.0
    day_low = 25060.0
    vwap = 25090.0

    chain = [
        MockContract(25100.0, "CE", 125.0, volume=30000, oi=18000, pchange=6.5),
        MockContract(25150.0, "CE", 95.0, volume=22000, oi=14000, pchange=5.0),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=12, base_price=25080.0, trend="UP")
    ref_t = datetime(2026, 10, 19, 9, 45, tzinfo=IST)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        prev_day_high=prev_day_high,
        prev_day_low=prev_day_low,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.stage == "PRIMED"
    assert alert.confidence >= 85
    assert "CAMARILLA_H4_PROXIMITY" in alert.metrics["signals"]
    assert "[PRIMED PROXIMITY]" in alert.headline
    assert "CAMARILLA H4 BREAKOUT WATCH" in alert.headline
    assert alert.direction == "BULLISH"
    assert alert.stop_loss > 0
    assert alert.target_level > alert.ltp


def test_day_high_proximity_call():
    """
    Spot is within 0.35% below Day High with bullish structure (when not at H4).
    Must emit stage='PRIMED', confidence >= 85, and signal='DAY_HIGH_PROXIMITY'.
    """
    # Cam H4 is far above (e.g. 25300) so only Day High proximity fires
    prev_day_high = 25250.0
    prev_day_low = 24950.0
    prev_close = 25150.0
    # Range = 300. H4 = 25150 + 300 * 1.1 / 2 = 25315
    day_high = 25120.0
    spot = 25095.0  # 25 pts below Day High = 0.10%, within 0.35%
    day_low = 25020.0
    vwap = 25060.0

    chain = [
        MockContract(25100.0, "CE", 115.0, volume=28000, oi=16000, pchange=4.5),
        MockContract(25150.0, "CE", 85.0, volume=20000, oi=12000, pchange=3.0),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=12, base_price=25050.0, trend="UP")
    ref_t = datetime(2026, 10, 19, 10, 5, tzinfo=IST)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        prev_day_high=prev_day_high,
        prev_day_low=prev_day_low,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.stage == "PRIMED"
    assert alert.confidence >= 85
    assert "DAY_HIGH_PROXIMITY" in alert.metrics["signals"]
    assert "[PRIMED PROXIMITY]" in alert.headline
    assert "DAY HIGH BREAKOUT WATCH" in alert.headline


def test_camarilla_l4_proximity_put():
    """
    Spot is within 0.35% above Camarilla L4 with bearish posture.
    Must emit stage='PRIMED', confidence >= 85, and signal='CAMARILLA_L4_PROXIMITY'.
    """
    prev_day_high = 25250.0
    prev_day_low = 25100.0
    prev_close = 25000.0
    # Range = 150. L4 = 25000 - 150 * 1.1 / 2 = 24917.5
    # Let spot = 24935.0 -> distance to L4 is 17.5 pts (0.07%), well within 0.35%
    spot = 24935.0
    day_high = 25030.0
    day_low = 24925.0
    vwap = 24980.0

    chain = [
        MockContract(24950.0, "PE", 120.0, volume=32000, oi=20000, pchange=7.0),
        MockContract(24900.0, "PE", 90.0, volume=24000, oi=15000, pchange=5.5),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=12, base_price=24990.0, trend="DOWN")
    ref_t = datetime(2026, 10, 19, 9, 45, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        prev_day_high=prev_day_high,
        prev_day_low=prev_day_low,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.stage == "PRIMED"
    assert alert.confidence >= 85
    assert "CAMARILLA_L4_PROXIMITY" in alert.metrics["signals"]
    assert "[PRIMED PROXIMITY]" in alert.headline
    assert "CAMARILLA L4 BREAKDOWN WATCH" in alert.headline
    assert alert.direction == "BEARISH"
    assert alert.stop_loss > 0
    assert alert.target_level > alert.ltp


def test_day_low_proximity_put():
    """
    Spot is within 0.35% above Day Low with bearish structure (when not at L4).
    Must emit stage='PRIMED', confidence >= 85, and signal='DAY_LOW_PROXIMITY'.
    """
    # Cam L4 is far below so only Day Low proximity triggers
    prev_day_high = 25200.0
    prev_day_low = 24800.0
    prev_close = 25100.0
    # Range = 400. L4 = 25100 - 400 * 1.1 / 2 = 24880
    day_low = 25000.0
    spot = 25025.0  # 25 pts above Day Low = 0.10%, within 0.35%
    day_high = 25150.0
    vwap = 25080.0

    chain = [
        MockContract(25000.0, "PE", 110.0, volume=28000, oi=17000, pchange=4.0),
        MockContract(24950.0, "PE", 80.0, volume=21000, oi=13000, pchange=3.0),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=12, base_price=25120.0, trend="DOWN")
    ref_t = datetime(2026, 10, 19, 10, 10, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        prev_day_high=prev_day_high,
        prev_day_low=prev_day_low,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.stage == "PRIMED"
    assert alert.confidence >= 85
    assert "DAY_LOW_PROXIMITY" in alert.metrics["signals"]
    assert "[PRIMED PROXIMITY]" in alert.headline
    assert "DAY LOW BREAKDOWN WATCH" in alert.headline
