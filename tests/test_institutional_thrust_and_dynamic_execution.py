"""
tests/test_institutional_thrust_and_dynamic_execution.py
─────────────────────────────────────────────────────────
Institutional-grade tests for:
  1. Institutional Expansion Thrust (Thrust Bar) detection in index_call_setup & index_put_setup.
  2. Edgeless Chop Bypass: Ordinary chop setups remain strictly suppressed (zero noise),
     while verified Institutional Expansion Thrusts bypass the gate to capture vertical rallies.
  3. Dynamic Execution Mode: Parabolic breakout thrust switches from LIMIT_ON_PULLBACK to
     MOMENTUM_STOP_LIMIT with exact trigger price, limit cap, and breakout-candle SL.
  4. Friday Afternoon Intraday-Only Scalp Window: Off-cycle index options (MIDCPNIFTY/FINNIFTY)
     tagged with INTRADAY_SCALP_ONLY and mandatory 15:15 IST square-off pass Tier-1 sanity scrutiny.
"""

from datetime import datetime
import os
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pandas as pd
import pytest

from engine.alert_model import AutoAlert
from engine.alert_scrutiny import alert_scrutiny_auditor
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup
from engine.market_regime_gate import RegimeSnapshot

IST = ZoneInfo("Asia/Kolkata")


class DummyContract:
    def __init__(
        self,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 25000,
        oi: int = 10000,
        pchange: float = 22.0,
    ):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.oi_change = 2500
        self.pchange = pchange
        self.symbol = f"NIFTY{int(strike)}{option_type}"
        self.expiry = "2026-10-01"


def _make_sample_chain(spot: float):
    return [
        DummyContract(spot - 100, "CE", 140.0, volume=35000, oi=12000, pchange=28.0),
        DummyContract(spot - 50, "CE", 105.0, volume=40000, oi=15000, pchange=25.0),
        DummyContract(spot, "CE", 75.0, volume=50000, oi=20000, pchange=22.0),
        DummyContract(spot + 50, "CE", 48.0, volume=30000, oi=18000, pchange=18.0),
        DummyContract(spot + 100, "CE", 28.0, volume=20000, oi=15000, pchange=15.0),
        DummyContract(spot - 100, "PE", 25.0, volume=15000, oi=15000, pchange=18.0),
        DummyContract(spot - 50, "PE", 45.0, volume=20000, oi=18000, pchange=20.0),
        DummyContract(spot, "PE", 70.0, volume=25000, oi=20000, pchange=22.0),
        DummyContract(spot + 50, "PE", 105.0, volume=20000, oi=15000, pchange=25.0),
        DummyContract(spot + 100, "PE", 145.0, volume=15000, oi=12000, pchange=28.0),
    ]


def _build_thrust_ohlcv(is_bullish: bool = True) -> pd.DataFrame:
    """Builds a 10-bar 5m DataFrame where bar 10 is an institutional expansion thrust."""
    base = 25000.0
    times = pd.date_range("2026-09-25 13:00", periods=10, freq="5min", tz=IST)
    rows = []
    # Bars 1 to 9: quiet consolidation (range ~15 pts, vol ~20,000)
    for i in range(9):
        o = base + (i * 1.5)
        h = o + 8.0
        l = o - 7.0
        c = o + 2.0
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 20000})

    if is_bullish:
        # Bar 10: Institutional Bullish Thrust (Range 55 pts >= 1.5x ATR, Vol 55,000 >= 2x MA, close at high)
        o_thrust = base + 15.0
        l_thrust = o_thrust - 3.0
        h_thrust = o_thrust + 55.0
        c_thrust = h_thrust - 2.0  # Upper wick = 2.0 pts out of 58 pts (< 4%)
        rows.append({
            "open": o_thrust,
            "high": h_thrust,
            "low": l_thrust,
            "close": c_thrust,
            "volume": 55000,
        })
    else:
        # Bar 10: Institutional Bearish Breakdown Flush
        o_thrust = base + 15.0
        h_thrust = o_thrust + 3.0
        l_thrust = o_thrust - 55.0
        c_thrust = l_thrust + 2.0  # Lower wick = 2.0 pts (< 4%)
        rows.append({
            "open": o_thrust,
            "high": h_thrust,
            "low": l_thrust,
            "close": c_thrust,
            "volume": 55000,
        })

    df = pd.DataFrame(rows, index=times)
    return df


def test_detect_index_call_setup_institutional_thrust():
    """Verifies that an explosive 5m candle breaking Day High produces INSTITUTIONAL_EXPANSION_THRUST."""
    spot = 25068.0
    chain = _make_sample_chain(spot)
    df_5m = _build_thrust_ohlcv(is_bullish=True)
    day_high = 25050.0  # Previous day high / session high broken by bar 10
    ref_dt = datetime(2026, 9, 25, 14, 0, tzinfo=IST)

    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=25010.0,
        day_high=day_high,
        day_low=24980.0,
        ohlcv_5m=df_5m,
        ref_time=ref_dt,
    )

    assert len(alerts) > 0, "Expected at least one call alert on institutional thrust"
    alert = alerts[0]
    assert alert.metrics.get("is_institutional_thrust") is True
    assert "INSTITUTIONAL_EXPANSION_THRUST" in alert.metrics.get("signals", [])
    assert alert.metrics.get("breakout_bar_low") is not None
    assert alert.confidence >= 90
    assert "INSTITUTIONAL EXPANSION THRUST" in alert.headline


def test_detect_index_put_setup_institutional_breakdown():
    """Verifies that an explosive 5m candle breaking Day Low produces INSTITUTIONAL_EXPANSION_BREAKDOWN."""
    spot = 24945.0
    chain = _make_sample_chain(spot)
    df_5m = _build_thrust_ohlcv(is_bullish=False)
    day_low = 24965.0  # Session low broken by bar 10
    ref_dt = datetime(2026, 9, 25, 14, 0, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=spot,
        chain=chain,
        vwap=25010.0,
        day_high=25030.0,
        day_low=day_low,
        ohlcv_5m=df_5m,
        ref_time=ref_dt,
    )

    assert len(alerts) > 0, "Expected at least one put alert on institutional breakdown"
    alert = alerts[0]
    assert alert.metrics.get("is_institutional_thrust") is True
    assert "INSTITUTIONAL_EXPANSION_BREAKDOWN" in alert.metrics.get("signals", [])
    assert alert.metrics.get("breakout_bar_high") is not None
    assert alert.confidence >= 90
    assert "INSTITUTIONAL EXPANSION BREAKDOWN" in alert.headline


def test_edgeless_chop_gate_filters_routine_setups_but_permits_thrust():
    """
    Verifies that under EDGELESS CHOP:
    - Routine setups without thrust are suppressed (zero noise).
    - Verified Institutional Expansion Thrusts bypass the chop gate and generate alerts.
    """
    engine = AutoAlertEngine()
    edgeless_regime = RegimeSnapshot(
        is_edgeless=True,
        vix=12.2,
        ad_ratio=0.92,
        vix_status="LOW",
        ad_status="NEUTRAL_CHOP",
        banner="EDGELESS CHOP - PRESERVE CAPITAL",
        reason="VIX 12.2 (< 12.5) + A/D 0.92 (neutral band).",
        prefer_spreads=True,
        data_quality="LIVE",
        evaluated_at=100.0,
    )

    spot = 25068.0
    chain = _make_sample_chain(spot)

    # 1. Non-thrust alert (routine trend retrace)
    alert_routine = AutoAlert(
        alert_id="test-routine",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Routine Setup",
        summary="Routine",
        ltp=75.0,
        trigger_level=75.0,
        target_level=95.0,
        stop_loss=60.0,
        metrics={"signals": ["TREND_PULLBACK_RECLAIM"], "is_institutional_thrust": False},
        actionable_plan={},
    )

    # 2. Thrust alert
    alert_thrust = AutoAlert(
        alert_id="test-thrust",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Thrust Setup",
        summary="Thrust",
        ltp=75.0,
        trigger_level=75.0,
        target_level=95.0,
        stop_loss=60.0,
        metrics={
            "signals": ["INSTITUTIONAL_EXPANSION_THRUST", "DAY_HIGH_BREAKOUT"],
            "is_institutional_thrust": True,
            "breakout_bar_low": 25012.0,
            "vol_oi_ratio": 2.2,
        },
        actionable_plan={},
    )

    q_dict = {"ltp": spot, "vwap": 25010.0, "high": 25050.0, "low": 24980.0, "change_pct": 0.35}
    q_map = {"NSE:NIFTY": q_dict, "NIFTY": q_dict}

    with patch.dict(os.environ, {"ENFORCE_TEST_REGIME": "1"}), \
         patch("engine.market_regime_gate.evaluate_market_regime", return_value=edgeless_regime), \
         patch.object(engine, "_watched_indices", {"NIFTY"}), \
         patch.object(engine, "_get_prioritized_targets", return_value=["NIFTY"]), \
         patch.object(engine, "record_alert", return_value=True), \
         patch("market.history.get_ohlcv", return_value=None), \
         patch("market.options.get_options_chain", return_value=chain):

        # Case A: detector returns only routine alert -> must be filtered out completely under chop
        with patch("engine.auto_alert_engine.detect_index_call_setup", return_value=[alert_routine]):
            results = engine.scan_index_call_setups(quotes_map=q_map)
            assert len(results) == 0, "Routine setup should be strictly suppressed under edgeless chop"

        # Case B: detector returns institutional thrust alert -> must bypass chop and emit alert
        with patch("engine.auto_alert_engine.detect_index_call_setup", return_value=[alert_thrust]):
            results = engine.scan_index_call_setups(quotes_map=q_map)
            assert len(results) == 1, "Institutional thrust setup must pass edgeless chop gate"
            emitted = results[0]
            assert emitted.entry_type == "MOMENTUM_STOP_LIMIT"
            assert emitted.actionable_plan["order_type"] == "STOP_LIMIT"
            assert "trigger_price" in emitted.actionable_plan["execution_strategy"]
            assert emitted.actionable_plan["execution_strategy"]["stop_loss_level"] == 25012.0


def test_friday_afternoon_intraday_scalp_passes_tier1_scrutiny():
    """
    Verifies that on Friday afternoon (post 13:00 IST), off-cycle MIDCPNIFTY option alerts
    tagged as INTRADAY_SCALP_ONLY with mandatory 15:15 exit pass Tier-1 sanity scrutiny.
    """
    alert = AutoAlert(
        alert_id="test-midcp-friday-scalp",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="🚀 INTRADAY SCALP: MIDCPNIFTY 13200 CE",
        summary="Intraday scalp only",
        ltp=65.0,
        trigger_level=65.0,
        target_level=85.0,
        stop_loss=50.0,
        strike=13200.0,
        option_type="CE",
        segment="FNO_INDEX",
        underlying_spot=13210.0,
        no_chase_boundary=70.0,
        time_horizon="INTRADAY_SCALP_ONLY",
        created_at="2026-09-25 14:00:00 IST",  # Friday 14:00 IST
        metrics={
            "day_high": 13200.0,
            "day_low": 13120.0,
            "signals": ["INSTITUTIONAL_EXPANSION_THRUST"],
            "vol_oi_ratio": 2.8,
            "is_institutional_thrust": True,
            "lot_size": 75,
            "time_horizon": "INTRADAY_SCALP_ONLY",
        },
        actionable_plan={
            "action": "BUY CE",
            "time_horizon": "INTRADAY_SCALP_ONLY",
            "mandatory_exit": "15:15 IST (Strict Zero-Overnight)",
            "target_1": "₹85.0",
            "stop_loss": "₹50.0",
        },
    )

    with patch.dict(os.environ, {"ENFORCE_TEST_FRIDAY_GATE": "1"}):
        ok, reason, flags = alert_scrutiny_auditor.verify_tier1_sanity(alert)
        assert ok is True, f"Expected Friday afternoon intraday scalp to pass Tier-1 sanity, but failed: {reason}"
        assert flags.get("is_intraday_scalp_only") is True
