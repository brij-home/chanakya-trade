"""
tests/test_index_trading_excellence.py
──────────────────────────────────────
Institutional Test Suite for Index Intraday Trading Excellence:
  1. ATM & 1-Strike ITM Moneyness selection priority over far-OTM lottery strikes.
  2. CPR (Central Pivot Range) demand bounce & Narrow CPR regime detection.
  3. Camarilla H4 breakout (Call) and L4 breakdown (Put) confluence.
  4. High-Watermark Guaranteed Profit Floor (+1.0R at 2.5R, +2.0R at 3.5R).
  5. Dedicated High-Frequency Index Scanner loop lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from engine.alert_model import AutoAlert
from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.auto_alert_engine import AutoAlertEngine

IST = timezone(timedelta(hours=5, minutes=30))


class MockOptionContract:
    def __init__(
        self,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 20000,
        oi: int = 10000,
        oi_change: int = 1500,
        pchange: float = 12.0,
    ):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = oi_change
        self.pchange = pchange
        self.symbol = f"NIFTY{int(strike)}{option_type}"
        self.expiry = "2026-10-08"


def _make_dummy_5m_ohlcv(bars: int = 15, base_price: float = 25000.0, trend: str = "UP") -> pd.DataFrame:
    records = []
    curr = base_price
    start_time = datetime(2026, 10, 5, 9, 30, tzinfo=IST)
    for i in range(bars):
        t = start_time + timedelta(minutes=5 * i)
        step = 10.0 if trend == "UP" else (-10.0 if trend == "DOWN" else 0.0)
        o = curr
        h = o + 8.0
        l = o - 4.0
        c = o + step
        curr = c
        records.append({
            "datetime": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 25000 + i * 200,
        })
    df = pd.DataFrame(records)
    df.set_index("datetime", inplace=True)
    return df


# ── Test 1: Moneyness Selection (ATM / ITM Priority over Far OTM) ─────────────

def test_atm_moneyness_selection_priority():
    """Confirms that ATM or 1-strike ITM option is selected over cheap far-OTM options even if OTM has high retail volume."""
    spot = 25050.0
    day_high = 25050.0  # At session high (Breakout)
    # Chain with:
    # 1. ATM contract: 25050 CE @ 125.0, vol=18,000, oi=12,000
    # 2. 1-strike ITM contract: 25000 CE @ 160.0, vol=12,000, oi=9,000
    # 3. Far OTM contract: 25350 CE @ 25.0, vol=90,000 (huge retail gamble volume), oi=40,000
    chain = [
        MockOptionContract(25000.0, "CE", 160.0, volume=12000, oi=9000, pchange=18.0),
        MockOptionContract(25050.0, "CE", 125.0, volume=18000, oi=12000, pchange=20.0),
        MockOptionContract(25100.0, "CE", 95.0, volume=15000, oi=10000, pchange=14.0),
        MockOptionContract(25350.0, "CE", 25.0, volume=90000, oi=40000, pchange=25.0),  # 300 pts OTM
    ]

    ohlcv = _make_dummy_5m_ohlcv(bars=15, base_price=25000.0, trend="UP")
    ref_t = datetime(2026, 10, 5, 10, 15, tzinfo=IST)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=25010.0,
        day_high=day_high,
        day_low=24950.0,
        prev_day_high=25020.0,
        prev_day_low=24900.0,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    chosen_strike = alerts[0].strike
    # Must choose ATM (25050) or 1-strike ITM (25000), NEVER the far OTM 25350
    assert chosen_strike in (25050.0, 25000.0)
    assert chosen_strike != 25350.0


# ── Test 2: CPR & Camarilla Confluence in Index Call Setup ────────────────────

def test_cpr_and_camarilla_h4_confluence():
    """Confirms that CPR and Camarilla breakout levels are computed and tagged into metrics."""
    spot = 25150.0
    pdh = 25100.0
    pdl = 24950.0
    prev_close = 25050.0
    # Range = 150. H4 = 25050 + 150 * 1.1 / 2 = 25050 + 82.5 = 25132.5
    # Since spot (25150) > H4 (25132.5), Camarilla H4 breakout is active!

    chain = [
        MockOptionContract(25150.0, "CE", 130.0, volume=25000, oi=12000, pchange=22.0),
        MockOptionContract(25100.0, "CE", 165.0, volume=15000, oi=10000, pchange=18.0),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=15, base_price=25100.0, trend="UP")
    ref_t = datetime(2026, 10, 5, 10, 15, tzinfo=IST)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=25110.0,
        day_high=25155.0,
        day_low=25080.0,
        prev_day_high=pdh,
        prev_day_low=pdl,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    metrics = alert.metrics
    assert "cpr_data" in metrics
    cpr = metrics["cpr_data"]
    assert "pivot" in cpr
    assert "tc" in cpr
    assert "bc" in cpr
    assert "cam_h4" in cpr
    # Check Camarilla H4 signal was triggered
    assert "CAMARILLA_H4_BREAKOUT" in metrics["signals"] or "DAY_HIGH_BREAKOUT" in metrics["signals"]


# ── Test 3: Camarilla L4 Breakdown in Index Put Setup ─────────────────────────

def test_cpr_and_camarilla_l4_breakdown_put():
    """Confirms that Camarilla L4 breakdown is detected in index put setups."""
    spot = 24900.0
    pdh = 25100.0
    pdl = 24950.0
    prev_close = 25000.0
    # Range = 150. L4 = 25000 - 150 * 1.1 / 2 = 25000 - 82.5 = 24917.5
    # Since spot (24900) < L4 (24917.5), Camarilla L4 breakdown is active!

    chain = [
        MockOptionContract(24900.0, "PE", 125.0, volume=22000, oi=11000, pchange=20.0),
        MockOptionContract(24950.0, "PE", 155.0, volume=14000, oi=9000, pchange=16.0),
    ]
    ohlcv = _make_dummy_5m_ohlcv(bars=15, base_price=24980.0, trend="DOWN")
    ref_t = datetime(2026, 10, 5, 10, 30, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=24960.0,
        day_high=24990.0,
        day_low=24890.0,
        prev_day_high=pdh,
        prev_day_low=pdl,
        prev_close=prev_close,
        ohlcv_5m=ohlcv,
        ref_time=ref_t,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    metrics = alert.metrics
    assert "cpr_data" in metrics
    assert "cam_l4" in metrics["cpr_data"]
    assert "CAMARILLA_L4_BREAKDOWN" in metrics["signals"] or "DAY_LOW_BREAKDOWN" in metrics["signals"]


# ── Test 4: High-Watermark Guaranteed Profit Floor ────────────────────────────

def test_high_watermark_guaranteed_profit_floor():
    """Confirms that when trade expands to +2.5R and +3.5R, trailing stop is ratcheted to lock guaranteed profit."""
    # Create an active in-flight alert with T1 and T2 already booked
    alert = AutoAlert(
        alert_id="aa-index-call-nifty-25000-20261005",
        alert_type="INDEX_CALL_SETUP",
        stage="T2_ACHIEVED",
        target_status="T2_ACHIEVED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🏆 TARGET 2 ACHIEVED",
        summary="Target 2 hit",
        ltp=100.0,
        trigger_level=100.0,
        target_level=130.0,
        stop_loss=80.0,
        trailing_stop=130.0,  # T1 level locked
        should_trail=True,
        option_premium=100.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY26OCT25000CE",
        achieved_milestones=["T1_ACHIEVED", "T2_ACHIEVED"],
        actionable_plan={
            "recommended_entry": "₹100.00",
            "stop_loss": "₹80.00",
            "target_1": "₹130.00",
            "target_2": "₹160.00",
            "target_3": "₹210.00",
        },
    )

    # Initial risk = 100 - 80 = 20 pts.
    # When LTP expands to 175.0 (Gain = +75 pts = +3.75R):
    # Guaranteed floor should be at least entry + 2.0R = 100 + 40 = 140.0!
    eval_3_5r = evaluate_alert_targets_and_trailing(alert, current_ltp=175.0)
    assert eval_3_5r is not None
    assert eval_3_5r.should_trail is True
    assert eval_3_5r.new_trailing_stop >= 140.0  # +2.0R guaranteed locked!
    assert eval_3_5r.locked_profit_pts >= 40.0


# ── Test 5: Dedicated High-Frequency Index Scanner Lifecycle ──────────────────

def test_dedicated_index_scanner_thread_lifecycle():
    """Confirms that AutoAlertEngine initializes and cleanly stops the dedicated Index Scanner thread."""
    engine = AutoAlertEngine()
    assert hasattr(engine, "_index_scanner_thread")
    assert engine._index_scanner_thread is None

    # Start polling
    engine.start_polling(interval_seconds=30)
    assert engine._is_running is True
    assert engine._index_scanner_thread is not None
    assert engine._index_scanner_thread.is_alive()

    # Clean shutdown
    engine.stop_polling()
    assert engine._is_running is False
    assert engine._index_scanner_thread is None
