"""
tests/test_morning_session_reversal_and_anti_trap.py
────────────────────────────────────────────────────
Regression and invariant tests for morning session (09:15-10:00 IST) execution:
  1. Bar 2 (09:25 IST) late-session exhaustion must NEVER fire an Opening Drive breakdown.
  2. SMT Sweep must NEVER fire a Bearish PE setup into an active green expansion breakout candle.
  3. 09:30 V-bottom demand rejection must immediately fire an IGNITED CE call setup.
  4. Day High proximity must NOT downgrade an active structural reversal into a PRIMED watch-only stage.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.opening_drive import detect_opening_drive
from engine.detectors.smt_sweep import detect_smt_sweep

IST = ZoneInfo("Asia/Kolkata")


def _build_mock_chain(spot: float, symbol: str) -> list[Any]:
    step = 100.0 if symbol in ("BANKNIFTY", "SENSEX") else 50.0
    chain = []
    atm = round(spot / step) * step
    for offset in (-3, -2, -1, 0, 1, 2, 3):
        k = atm + (offset * step)
        chain.append(
            SimpleNamespace(
                symbol=f"{symbol}{int(k)}CE",
                strike=k,
                option_type="CE",
                last_price=max(5.0, 180.0 - (offset * 35.0)),
                volume=35000,
                oi=120000,
                pchange=5.0,
                expiry="2026-11-23",
                delta=0.55 - (offset * 0.08),
                gamma=0.002,
                iv=14.5,
            )
        )
        chain.append(
            SimpleNamespace(
                symbol=f"{symbol}{int(k)}PE",
                strike=k,
                option_type="PE",
                last_price=max(5.0, 150.0 + (offset * 35.0)),
                volume=35000,
                oi=120000,
                pchange=-5.0,
                expiry="2026-11-23",
                delta=-0.45 - (offset * 0.08),
                gamma=0.002,
                iv=14.5,
            )
        )
    return chain


def test_opening_drive_bar2_exhaustion_suppression():
    """Bar 2 (09:25 IST) with Open == High must NOT trigger an Opening Drive breakdown."""
    bars = [
        {"open": 25186.8, "high": 25255.6, "low": 25151.5, "close": 25199.15, "volume": 8000000},
        {"open": 25203.2, "high": 25203.2, "low": 25139.3, "close": 25162.05, "volume": 9500000},
        {"open": 25164.55, "high": 25167.4, "low": 25115.9, "close": 25116.2, "volume": 6500000},
    ]
    idx = pd.date_range("2026-11-19 09:15", periods=3, freq="5min", tz=IST)
    df_5m = pd.DataFrame(bars, index=idx)

    alert = detect_opening_drive(
        symbol="NIFTY",
        df_5m=df_5m,
        ltp=25116.0,
        vwap=25180.0,
        ref_time=datetime(2026, 11, 19, 9, 25, 0, tzinfo=IST),
    )
    assert alert is None, (
        "Opening drive must not trigger on Bar 2 (09:25 IST) exhaustion into support"
    )


def test_smt_sweep_green_expansion_suppression():
    """An index rocketing up with a strong green candle must not trigger Bearish SMT PE setup."""
    bars = [
        {"open": 13998.0, "high": 14015.0, "low": 13985.0, "close": 13990.0, "volume": 50000},
        {"open": 13990.0, "high": 13995.0, "low": 13970.0, "close": 13975.0, "volume": 60000},
        {"open": 13975.0, "high": 14040.2, "low": 13970.0, "close": 14011.5, "volume": 90000},
    ]
    idx = pd.date_range("2026-11-19 09:20", periods=3, freq="5min", tz=IST)
    df_5m = pd.DataFrame(bars, index=idx)

    quotes_map = {"NIFTY": {"ltp": 25140.8, "vwap": 25224.7, "high": 25255.6, "low": 25104.8}}
    chain = _build_mock_chain(14011.5, "MIDCPNIFTY")

    alerts = detect_smt_sweep(
        underlying="MIDCPNIFTY",
        spot=14011.5,
        chain=chain,
        vwap=14000.0,
        day_high=14040.2,
        day_low=13970.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 11, 19, 9, 34, 0, tzinfo=IST),
        quotes_map=quotes_map,
    )
    assert len(alerts) == 0, (
        "Bearish SMT sweep must not fire PE into an active green expansion candle"
    )


def test_nifty_0930_v_bottom_reversal_ignition():
    """NIFTY wicking off 25104 at 09:30 must fire an IGNITED CE call setup."""
    bars = [
        {"open": 25186.8, "high": 25255.6, "low": 25151.5, "close": 25199.15, "volume": 8000000},
        {"open": 25203.2, "high": 25203.2, "low": 25139.3, "close": 25162.05, "volume": 9500000},
        {"open": 25164.55, "high": 25167.4, "low": 25115.9, "close": 25116.2, "volume": 6500000},
        {"open": 25118.7, "high": 25152.8, "low": 25104.8, "close": 25141.7, "volume": 7700000},
    ]
    idx = pd.date_range("2026-11-19 09:15", periods=4, freq="5min", tz=IST)
    df_5m = pd.DataFrame(bars, index=idx)
    chain = _build_mock_chain(25141.7, "NIFTY")

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=25141.7,
        chain=chain,
        vwap=25190.0,
        day_high=25255.6,
        day_low=25104.8,
        prev_day_high=25240.0,
        prev_day_low=25080.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 11, 19, 9, 30, 0, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert len(alerts) >= 1, "Must detect 09:30 V-bottom reversal on NIFTY"
    a = alerts[0]
    assert a.stage == "IGNITED", f"Reversal setup must be IGNITED, got {a.stage}"
    assert a.direction == "BULLISH"
    assert a.strike in (25100.0, 25150.0)
    assert any(
        s in a.metrics.get("signals", [])
        for s in ("PDL_DEMAND_REJECTION", "ACCUMULATION_BOTTOM", "DAY_LOW_DEMAND_BOUNCE")
    )


def test_banknifty_0930_v_bottom_reversal_ignition():
    """BANKNIFTY wicking off 61951 at 09:30 must fire an IGNITED CE call setup."""
    bars = [
        {"open": 62081.3, "high": 62261.95, "low": 61951.1, "close": 62157.15, "volume": 800000},
        {"open": 62160.0, "high": 62180.0, "low": 62020.0, "close": 62040.0, "volume": 750000},
        {"open": 62040.0, "high": 62060.0, "low": 61998.65, "close": 62005.0, "volume": 650000},
        {"open": 62005.0, "high": 62080.0, "low": 61964.0, "close": 62050.0, "volume": 850000},
    ]
    idx = pd.date_range("2026-11-19 09:15", periods=4, freq="5min", tz=IST)
    df_5m = pd.DataFrame(bars, index=idx)
    chain = _build_mock_chain(62050.0, "BANKNIFTY")

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=62050.0,
        chain=chain,
        vwap=62120.0,
        day_high=62261.95,
        day_low=61951.1,
        prev_day_high=62200.0,
        prev_day_low=61900.0,
        ohlcv_5m=df_5m,
        ref_time=datetime(2026, 11, 19, 9, 30, 0, tzinfo=IST),
        ignore_time_gate=True,
    )
    assert len(alerts) >= 1, "Must detect 09:30 V-bottom reversal on BANKNIFTY"
    a = alerts[0]
    assert a.stage == "IGNITED"
    assert a.direction == "BULLISH"
    assert a.strike in (62000.0, 62100.0)
