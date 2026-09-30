"""
tests/test_v_reversal_and_ord_setups.py
───────────────────────────────────────
Validates:
1. Dynamic V-Reversal Breadth Escape in detect_index_call_setup (recovering from severe session dump).
2. INTRADAY_CAPITULATION_REVERSAL (ICR) detector capturing V-bottoms.
3. Benchmark Decoupling in AutoAlertEngine (Bank Nifty independent evaluation).
4. Opening Range Displacement (ORD) exception in detect_index_put_setup.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup

IST = ZoneInfo("Asia/Kolkata")


class MockOptionContract:
    def __init__(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 15000,
        oi: int = 10000,
        oi_change: int = -500,
        pchange: float = 18.0,
        expiry: str = "2026-10-01",
    ):
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = oi_change
        self.pchange = pchange
        self.expiry = expiry


def _make_reversal_ohlcv(
    start_time: str = "2026-09-29 09:15:00",
    open_p: float = 22750.0,
    low_p: float = 22570.0,
    current_p: float = 22710.0,
) -> pd.DataFrame:
    """Builds a synthetic 5m OHLCV DataFrame depicting a morning dump and V-reversal."""
    timestamps = pd.date_range(start_time, periods=16, freq="5min")
    # First 8 bars dump from 22750 to 22570; next 8 bars rally to 22710
    prices = [
        22750.0,
        22710.0,
        22670.0,
        22640.0,
        22610.0,
        22585.0,
        22570.0,
        22575.0,
        22595.0,
        22620.0,
        22645.0,
        22665.0,
        22685.0,
        22700.0,
        22705.0,
        current_p,
    ]
    rows = []
    for i, p in enumerate(prices):
        o = prices[i - 1] if i > 0 else open_p
        l = min(o, p) - 5.0
        h = max(o, p) + 5.0
        rows.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": p,
                "volume": 20000.0 + i * 2000,
            }
        )
    df = pd.DataFrame(rows, index=timestamps)
    return df


def test_v_reversal_breadth_escape_allows_call_setup():
    """Verify that a strong bounce (+0.5% from low + VWAP reclaim) bypasses BROAD_DECLINE breadth filter."""
    spot = 22655.0
    day_low = 22530.0
    day_high = 22700.0
    vwap = 22630.0  # Spot (22655) is +0.11% above VWAP (22630), within proximity envelope

    chain = [
        MockOptionContract(
            "NIFTY26OCT22650CE", 22650.0, "CE", 125.0, volume=25000, oi=12000, pchange=22.0
        ),
        MockOptionContract(
            "NIFTY26OCT22650PE", 22650.0, "PE", 110.0, volume=20000, oi=15000, oi_change=-2000
        ),
    ]
    df_5m = _make_reversal_ohlcv(open_p=22700.0, low_p=day_low, current_p=spot)

    mock_mb = MagicMock()
    mock_mb.verdict = "BROAD_DECLINE"
    mock_mb.ad_ratio = 0.55  # Severely negative breadth
    mock_mb.advances = 160
    mock_mb.declines = 340

    with patch.dict(os.environ, {"ENFORCE_TEST_BREADTH": "1"}):
        with patch("market.sentiment.get_market_breadth", return_value=mock_mb):
            alerts = detect_index_call_setup(
                underlying="NIFTY",
                spot=spot,
                chain=chain,
                vwap=vwap,
                day_high=day_high,
                day_low=day_low,
                ohlcv_5m=df_5m,
                ignore_time_gate=True,
            )

    assert len(alerts) >= 1, (
        "V-Reversal escape should allow setup even when broader market A/D is 0.55 (BROAD_DECLINE)"
    )
    alert = alerts[0]
    assert alert.direction == "BULLISH"
    assert "VWAP_RECLAIM" in alert.metrics.get(
        "signals", []
    ) or "INTRADAY_CAPITULATION_REVERSAL" in alert.metrics.get("signals", [])
    assert alert.stop_loss < alert.ltp < alert.target_level


def test_intraday_capitulation_reversal_detection():
    """Verify that an oversold dip below VWAP with 5m CHoCH structure detects INTRADAY_CAPITULATION_REVERSAL."""
    spot = 53980.0
    day_low = 53780.0  # -0.7% below VWAP
    day_high = 54400.0
    vwap = 54180.0  # Spot is still below VWAP, but has bounced +0.37% from low

    # Build 5m bars where last bar prints CHoCH higher close
    timestamps = pd.date_range("2026-09-29 09:15:00", periods=10, freq="5min")
    rows = [
        {"open": 54400.0, "high": 54410.0, "low": 54300.0, "close": 54320.0, "volume": 10000},
        {"open": 54320.0, "high": 54330.0, "low": 54100.0, "close": 54120.0, "volume": 12000},
        {"open": 54120.0, "high": 54130.0, "low": 53950.0, "close": 53970.0, "volume": 15000},
        {"open": 53970.0, "high": 53980.0, "low": 53850.0, "close": 53870.0, "volume": 18000},
        {
            "open": 53870.0,
            "high": 53880.0,
            "low": 53780.0,
            "close": 53800.0,
            "volume": 25000,
        },  # capitulation bar
        {
            "open": 53800.0,
            "high": 53890.0,
            "low": 53790.0,
            "close": 53880.0,
            "volume": 22000,
        },  # bounce
        {"open": 53880.0, "high": 53940.0, "low": 53860.0, "close": 53930.0, "volume": 20000},
        {
            "open": 53930.0,
            "high": 53990.0,
            "low": 53910.0,
            "close": 53980.0,
            "volume": 24000,
        },  # CHoCH bar
    ]
    df_bn = pd.DataFrame(rows, index=timestamps[: len(rows)])

    chain = [
        MockOptionContract(
            "BANKNIFTY26OCT54000CE", 54000.0, "CE", 130.0, volume=35000, oi=18000, pchange=15.0
        ),
        MockOptionContract(
            "BANKNIFTY26OCT54000PE", 54000.0, "PE", 140.0, volume=28000, oi=20000, oi_change=-1500
        ),
    ]

    mock_mb = MagicMock()
    mock_mb.verdict = "NEUTRAL"
    mock_mb.ad_ratio = 1.0

    alerts = detect_index_call_setup(
        underlying="BANKNIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_bn,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    signals = alerts[0].metrics.get("signals", [])
    assert "INTRADAY_CAPITULATION_REVERSAL" in signals
    assert "CAPITULATION REVERSAL" in alerts[0].headline


def test_opening_range_displacement_exception_index_put():
    """Verify that an aggressive morning liquidation slicing PDL by >=0.2% bypasses 09:25 gate."""
    # Spot 22700 sliced through PDL (22760) by -0.26% and is -0.5% below open (22820)
    spot = 22700.0
    day_open = 22820.0
    prev_day_low = 22760.0

    timestamps = pd.date_range("2026-09-29 09:15:00", periods=2, freq="5min")
    df_ord = pd.DataFrame(
        [
            {"open": day_open, "high": 22825.0, "low": 22730.0, "close": 22740.0, "volume": 35000},
            {"open": 22740.0, "high": 22745.0, "low": 22695.0, "close": spot, "volume": 42000},
        ],
        index=timestamps,
    )

    chain = [
        MockOptionContract(
            "NIFTY26OCT22700PE", 22700.0, "PE", 145.0, volume=25000, oi=15000, pchange=35.0
        ),
    ]

    # Test at 09:21 IST (inside the normal 09:15-09:25 buffer)
    ref_time = datetime(2026, 9, 29, 9, 21, 0, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=22750.0,
        day_high=22825.0,
        day_low=22695.0,
        prev_day_low=prev_day_low,
        ohlcv_5m=df_ord,
        ref_time=ref_time,
        ignore_time_gate=False,  # Enforce time gate
    )

    assert len(alerts) >= 1, (
        "Opening Range Displacement (ORD) must allow PE setup before 09:25 IST when PDL is cleanly sliced"
    )
    assert alerts[0].direction == "BEARISH"


def test_tier1_sanity_reversal_exempt_from_hbcm_and_benchmark_trap():
    """Verify that Tier-1 sanity exempts reversal setups from HBCM 4/5 breakout veto and benchmark drag veto."""
    from engine.alert_model import AutoAlert
    from engine.alert_scrutiny import AlertScrutinyAuditor

    auditor = AlertScrutinyAuditor()

    # 1. Reversal Alert: BANKNIFTY Call setup with INTRADAY_CAPITULATION_REVERSAL
    reversal_alert = AutoAlert(
        alert_id="aa-index_call_setup-banknifty-ce-54000-20260929",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🔥 INTRADAY CAPITULATION REVERSAL: BANKNIFTY 54000 CE",
        summary="Spot bounced +0.5% off day low with 5m CHoCH structure",
        ltp=150.0,
        trigger_level=150.0,
        target_level=210.0,
        stop_loss=110.0,
        strike=54000.0,
        option_type="CE",
        contract_symbol="BANKNIFTY26OCT54000CE",
        underlying_spot=54050.0,
        is_live=True,
        segment="FNO_INDEX",
        lot_size=15,
        confidence=82,
        metrics={
            "signals": ["INTRADAY_CAPITULATION_REVERSAL"],
            "spot": 54050.0,
            "vwap": 54100.0,
            "day_low": 53780.0,  # Bounced +0.50% from low
            "day_high": 54400.0,
            "hbcm": {
                "total_heavyweights": 5,
                "confluence_pass": False,  # Only 2/5 heavyweights above VWAP during V-bottom
                "rejection_reason": "Heavyweight breadth unaligned: only 2/5 constituents bullish above VWAP",
            },
            "nifty_change_pct": -0.65,  # Primary benchmark NIFTY is red
            "strike": 54000.0,
            "oi": 15000,
            "volume": 35000,
        },
    )

    passed, reason, flags = auditor.verify_tier1_sanity(reversal_alert)
    assert passed is True, (
        f"Reversal alert should pass Tier-1 sanity despite Nifty red & HBCM unaligned, but failed with: {reason}"
    )
    assert reason == ""

    # 2. Breakout Alert: Under the exact same unaligned HBCM, a pure breakout MUST fail
    breakout_alert = AutoAlert(
        alert_id="aa-day_high_breakout-banknifty-ce-54000-20260929",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🚀 DAY HIGH BREAKOUT: BANKNIFTY 54000 CE",
        summary="Spot breaking day high",
        ltp=150.0,
        trigger_level=150.0,
        target_level=210.0,
        stop_loss=110.0,
        strike=54000.0,
        option_type="CE",
        contract_symbol="BANKNIFTY26OCT54000CE",
        underlying_spot=54410.0,
        is_live=True,
        segment="FNO_INDEX",
        lot_size=15,
        confidence=85,
        metrics={
            "signals": ["DAY_HIGH_BREAKOUT"],
            "spot": 54410.0,
            "vwap": 54100.0,
            "day_low": 53780.0,
            "day_high": 54400.0,
            "hbcm": {
                "total_heavyweights": 5,
                "confluence_pass": False,
                "rejection_reason": "Heavyweight breadth unaligned: only 2/5 constituents bullish above VWAP",
            },
            "nifty_change_pct": 0.50,
            "strike": 54000.0,
            "oi": 15000,
            "volume": 35000,
        },
    )

    b_passed, b_reason, b_flags = auditor.verify_tier1_sanity(breakout_alert)
    assert b_passed is False, "Pure breakout alert must be vetoed when HBCM confluence fails"
    assert "HBCM Confluence Veto" in b_reason


def test_vwap_reclaim_overextension_rejected():
    """Verify that VWAP_RECLAIM is NOT generated when spot is already +0.32% overextended above VWAP."""
    # Spot is 22722, VWAP is 22650.1 (+0.32% above VWAP)
    spot = 22722.25
    vwap = 22650.10
    day_low = 22570.0
    day_high = 22730.0

    chain = [
        MockOptionContract(
            "NIFTY26OCT22650CE", 22650.0, "CE", 108.0, volume=25000, oi=12000, pchange=15.0
        ),
        MockOptionContract(
            "NIFTY26OCT22700CE", 22700.0, "CE", 73.0, volume=20000, oi=15000, pchange=10.0
        ),
    ]

    # Without any other signal, pure VWAP reclaim should not trigger when spot is +0.32% away
    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ignore_time_gate=True,
    )

    # Either no alert or if an alert is generated (e.g. from other detectors), VWAP_RECLAIM must not be in signals
    for alert in alerts:
        signals = alert.metrics.get("signals", [])
        assert "VWAP_RECLAIM" not in signals, "Spot +0.32% above VWAP must not trigger VWAP_RECLAIM"


def test_0dte_midday_spread_mandate_enforced():
    """Verify that on 0DTE between 11:30 and 14:00 IST, Bull Call Spread is mandated over naked call."""
    spot = 22680.0
    vwap = 22660.0  # within proximity (0.08% above VWAP)
    day_low = 22570.0
    day_high = 22730.0
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    chain = [
        MockOptionContract(
            "NIFTY26SEP22650CE",
            22650.0,
            "CE",
            80.0,
            volume=25000,
            oi=12000,
            pchange=15.0,
            expiry=today_str,
        ),
        MockOptionContract(
            "NIFTY26SEP22700CE",
            22700.0,
            "CE",
            50.0,
            volume=20000,
            oi=15000,
            pchange=10.0,
            expiry=today_str,
        ),
    ]

    # Reference time at 12:20 IST (Midday theta trap window)
    ref_dt = datetime.strptime(f"{today_str} 12:20:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    # Primary action MUST be BULL CALL SPREAD, not BUY CE
    assert alert.actionable_plan.get("action") == "BULL CALL SPREAD"
    assert "HEDGED SPREAD MANDATE" in alert.headline
    assert alert.actionable_plan.get("instrument_type") == "OPTION_SPREAD"


def test_day_high_supply_rejection_pe_setup():
    """Verify that Day High rejection above VWAP generates high-probability PE setup (12:29 PM scenario)."""
    # Spot 22705.0 retreating from Day High 22725.0 (-0.09%) while holding above VWAP 22650.0 (+0.24%)
    spot = 22705.0
    day_high = 22725.0
    day_low = 22570.0
    vwap = 22650.0

    chain = [
        MockOptionContract(
            "NIFTY26OCT22700PE", 22700.0, "PE", 58.0, volume=35000, oi=22000, pchange=12.0
        ),
        MockOptionContract(
            "NIFTY26OCT22650PE", 22650.0, "PE", 38.0, volume=20000, oi=18000, pchange=8.0
        ),
    ]

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert "DAY_HIGH_SUPPLY_REJECTION" in alert.metrics.get("signals", [])
    assert alert.strike == 22700.0
    assert alert.option_type == "PE"
    assert alert.stop_loss < alert.ltp < alert.target_level
    # Risk-Reward check: SL ~₹46.40, Target ~₹75.40
    assert alert.stop_loss <= 48.0
    assert alert.target_level >= 70.0


def test_intraday_capitulation_top_pe_setup():
    """Verify that an overbought spike above VWAP with 5m CHoCH breakdown detects INTRADAY_CAPITULATION_TOP."""
    spot = 22695.0
    day_high = 22725.0  # +0.33% overbought above VWAP 22650.0
    day_low = 22570.0
    vwap = 22650.0

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    timestamps = pd.date_range(f"{today_str} 11:45:00", periods=10, freq="5min")
    rows = [
        {"open": 22630.0, "high": 22645.0, "low": 22625.0, "close": 22640.0, "volume": 12000},
        {"open": 22640.0, "high": 22650.0, "low": 22635.0, "close": 22648.0, "volume": 14000},
        {"open": 22648.0, "high": 22660.0, "low": 22645.0, "close": 22655.0, "volume": 13000},
        {"open": 22655.0, "high": 22665.0, "low": 22650.0, "close": 22662.0, "volume": 15000},
        {"open": 22660.0, "high": 22675.0, "low": 22655.0, "close": 22670.0, "volume": 15000},
        {"open": 22670.0, "high": 22690.0, "low": 22668.0, "close": 22685.0, "volume": 18000},
        {"open": 22685.0, "high": 22710.0, "low": 22680.0, "close": 22705.0, "volume": 22000},
        {
            "open": 22705.0,
            "high": 22725.0,
            "low": 22700.0,
            "close": 22722.0,
            "volume": 28000,
        },  # Day High peak bar
        {
            "open": 22722.0,
            "high": 22725.0,
            "low": 22708.0,
            "close": 22710.0,
            "volume": 25000,
        },  # Upper wick rejection
        {
            "open": 22710.0,
            "high": 22712.0,
            "low": 22695.0,
            "close": 22698.0,
            "volume": 32000,
        },  # Bearish CHoCH bar
    ]
    df_5m = pd.DataFrame(rows, index=timestamps[: len(rows)])

    chain = [
        MockOptionContract(
            "NIFTY26OCT22700PE", 22700.0, "PE", 60.0, volume=35000, oi=20000, pchange=15.0
        ),
    ]

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert "INTRADAY_CAPITULATION_TOP" in alert.metrics.get("signals", [])
    assert "CAPITULATION TOP" in alert.headline


def test_day_low_demand_bounce_ce_setup():
    """Verify that a bounce off the session Day Low triggers DAY_LOW_DEMAND_BOUNCE for CE."""
    spot = 22605.0
    day_low = 22580.0  # bounced +0.11% from Day Low
    day_high = 22750.0
    vwap = 22670.0

    chain = [
        MockOptionContract(
            "NIFTY26OCT22600CE", 22600.0, "CE", 75.0, volume=35000, oi=20000, pchange=12.0
        ),
    ]

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.direction == "BULLISH"
    assert "DAY_LOW_DEMAND_BOUNCE" in alert.metrics.get("signals", [])
    assert "DAY LOW DEMAND BOUNCE" in alert.headline


def test_failed_day_low_breakdown_bear_trap_ce_setup():
    """Verify that a liquidity sweep / bear trap below Day Low detects FAILED_DAY_LOW_BREAKDOWN."""
    spot = 22585.0
    day_low = 22580.0
    day_high = 22750.0
    vwap = 22660.0

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    timestamps = pd.date_range(f"{today_str} 10:10:00", periods=10, freq="5min")
    rows = [
        {"open": 22620.0, "high": 22630.0, "low": 22615.0, "close": 22625.0, "volume": 12000},
        {"open": 22625.0, "high": 22630.0, "low": 22610.0, "close": 22615.0, "volume": 13000},
        {"open": 22615.0, "high": 22620.0, "low": 22605.0, "close": 22610.0, "volume": 14000},
        {"open": 22610.0, "high": 22615.0, "low": 22600.0, "close": 22605.0, "volume": 14000},
        {"open": 22605.0, "high": 22610.0, "low": 22590.0, "close": 22595.0, "volume": 15000},
        {"open": 22595.0, "high": 22600.0, "low": 22585.0, "close": 22588.0, "volume": 16000},
        {"open": 22588.0, "high": 22592.0, "low": 22580.0, "close": 22582.0, "volume": 18000},
        {"open": 22582.0, "high": 22588.0, "low": 22580.0, "close": 22581.0, "volume": 17000},
        {
            "open": 22581.0,
            "high": 22584.0,
            "low": 22565.0,
            "close": 22570.0,
            "volume": 25000,
        },  # breach low
        {
            "open": 22570.0,
            "high": 22588.0,
            "low": 22568.0,
            "close": 22585.0,
            "volume": 35000,
        },  # Bear trap: closed back above 22580 with 85% wick
    ]
    df_5m = pd.DataFrame(rows, index=timestamps[: len(rows)])

    chain = [
        MockOptionContract(
            "NIFTY26OCT22600CE", 22600.0, "CE", 70.0, volume=40000, oi=22000, pchange=15.0
        ),
    ]

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.direction == "BULLISH"
    assert "FAILED_DAY_LOW_BREAKDOWN" in alert.metrics.get("signals", [])
    assert "FAILED DAY LOW BREAKDOWN" in alert.headline


def test_failed_day_high_breakout_bull_trap_pe_setup():
    """Verify that a liquidity sweep / bull trap above Day High detects FAILED_DAY_HIGH_BREAKOUT."""
    spot = 22715.0
    day_high = 22720.0
    day_low = 22580.0
    vwap = 22650.0

    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    timestamps = pd.date_range(f"{today_str} 11:40:00", periods=10, freq="5min")
    rows = [
        {"open": 22650.0, "high": 22665.0, "low": 22645.0, "close": 22660.0, "volume": 12000},
        {"open": 22660.0, "high": 22675.0, "low": 22655.0, "close": 22670.0, "volume": 13000},
        {"open": 22670.0, "high": 22685.0, "low": 22665.0, "close": 22680.0, "volume": 14000},
        {"open": 22680.0, "high": 22695.0, "low": 22675.0, "close": 22690.0, "volume": 14000},
        {"open": 22690.0, "high": 22700.0, "low": 22685.0, "close": 22695.0, "volume": 15000},
        {"open": 22695.0, "high": 22710.0, "low": 22690.0, "close": 22705.0, "volume": 17000},
        {"open": 22705.0, "high": 22718.0, "low": 22700.0, "close": 22715.0, "volume": 19000},
        {"open": 22715.0, "high": 22720.0, "low": 22710.0, "close": 22718.0, "volume": 20000},
        {
            "open": 22718.0,
            "high": 22735.0,
            "low": 22715.0,
            "close": 22730.0,
            "volume": 30000,
        },  # pierce high
        {
            "open": 22730.0,
            "high": 22735.0,
            "low": 22712.0,
            "close": 22715.0,
            "volume": 38000,
        },  # Bull trap: closed back below 22720 with upper wick
    ]
    df_5m = pd.DataFrame(rows, index=timestamps[: len(rows)])

    chain = [
        MockOptionContract(
            "NIFTY26OCT22700PE", 22700.0, "PE", 58.0, volume=35000, oi=18000, pchange=18.0
        ),
    ]

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=vwap,
        day_high=day_high,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ignore_time_gate=True,
    )

    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.direction == "BEARISH"
    assert "FAILED_DAY_HIGH_BREAKOUT" in alert.metrics.get("signals", [])
    assert "FAILED DAY HIGH BREAKOUT" in alert.headline
