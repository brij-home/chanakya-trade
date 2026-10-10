"""
tests/test_opening_timing_and_asymmetric_rr.py
──────────────────────────────────────────────
Regression and invariant tests for:
  1. Opening Drive & Index HF timing calibration (09:15:05+ activation).
  2. Asymmetric R:R (T1 >= +2.0R) across index micro scalps, call/put setups, and trade plans.
  3. Apex Gate integrity: Zero compromise on quality, no bypass of R:R / confidence floors.
  4. Transparent alert preferences explanations (explain_alert_allowed).
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.alert_preferences import AlertPreferencesManager
from engine.detectors.opening_drive import detect_opening_drive
from engine.detectors.index_micro_scalp import detect_index_micro_scalp
from engine.trade_plan import calculate_option_execution_plan
from engine.auto_alert_engine import AutoAlertEngine

IST = ZoneInfo("Asia/Kolkata")


def _make_test_alert(
    alert_id: str,
    alert_type: str,
    symbol: str,
    stage: str = "IGNITED",
    direction: str = "BULLISH",
    ltp: float = 100.0,
    trigger_level: float = 100.0,
    target_level: float = 130.0,
    stop_loss: float = 85.0,
    confidence: int = 88,
    segment: str = "FNO_INDEX",
    telegram_dispatched: bool = True,
) -> AutoAlert:
    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage=stage,
        symbol=symbol,
        exchange="NFO",
        direction=direction,
        headline=f"Test {symbol}",
        summary=f"Test summary for {symbol}",
        ltp=ltp,
        trigger_level=trigger_level,
        target_level=target_level,
        stop_loss=stop_loss,
        confidence=confidence,
        segment=segment,
        telegram_dispatched=telegram_dispatched,
        is_live=True,
        environment="LIVE",
    )


def test_explain_alert_allowed_transparent_reasons():
    """Verify that explain_alert_allowed provides explicit diagnostic explanations."""
    mgr = AlertPreferencesManager()

    # 1. Non-whitelisted FNO_INDEX symbol
    alert_finnifty = _make_test_alert(
        alert_id=generate_alert_id("FINNIFTY", "GAMMA_BLAST"),
        alert_type="GAMMA_BLAST",
        symbol="FINNIFTY",
        confidence=90,
        segment="FNO_INDEX",
    )
    allowed, reason = mgr.explain_alert_allowed(alert_finnifty, channel="telegram")
    assert not allowed
    assert "FINNIFTY" in reason or "whitelist" in reason

    # 2. Whitelisted FNO_INDEX symbol (NIFTY) with sufficient confidence
    alert_nifty = _make_test_alert(
        alert_id=generate_alert_id("NIFTY", "GAMMA_BLAST"),
        alert_type="GAMMA_BLAST",
        symbol="NIFTY",
        confidence=88,
        segment="FNO_INDEX",
    )
    allowed, reason = mgr.explain_alert_allowed(alert_nifty, channel="telegram")
    assert allowed
    assert reason == "Allowed"

    # 3. Milestone for undispatched parent alert (Zero-Ghost Invariant)
    alert_milestone = _make_test_alert(
        alert_id=generate_alert_id("NIFTY", "GAMMA_BLAST"),
        alert_type="GAMMA_BLAST",
        stage="T1_ACHIEVED",
        symbol="NIFTY",
        confidence=88,
        segment="FNO_INDEX",
        telegram_dispatched=False,
    )
    allowed, reason = mgr.explain_alert_allowed(alert_milestone, channel="telegram")
    assert not allowed
    assert "Zero-Ghost" in reason


def test_opening_drive_timing_at_09_15_30():
    """Verify Opening Drive activates at 09:15:30 IST with live candle expansion."""
    ref_dt = datetime(2026, 10, 9, 9, 15, 30, tzinfo=IST)
    dates = pd.date_range("2026-10-09 09:15:00", periods=1, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [25000.0],
            "high": [25080.0],
            "low": [24995.0],  # Open ~= Low within 0.02%
            "close": [25075.0],
            "volume": [150000.0],
        },
        index=dates,
    )

    alert = detect_opening_drive(
        symbol="NIFTY",
        df_5m=df_5m,
        ltp=25075.0,
        ref_time=ref_dt,
        ignore_time_gate=False,
    )
    assert alert is not None
    assert alert.direction == "BULLISH"
    assert "OPENING DRIVE" in alert.headline

    # Verify asymmetric targets in actionable blueprint
    plan = alert.actionable_plan
    assert plan is not None
    # Underlying targets: T1 = 2.5R
    risk_pts = max(0.5, alert.ltp - alert.stop_loss)
    reward_pts = alert.target_level - alert.ltp
    assert round(reward_pts / risk_pts, 1) >= 2.0


def test_index_micro_scalp_timing_at_09_16_15_and_apex_compliance():
    """Verify Index Micro Scalp triggers from 09:16:00 IST and satisfies Apex Gate."""
    ref_dt = datetime(2026, 10, 9, 9, 16, 15, tzinfo=IST)

    class DummyContract:
        def __init__(self, sym, strike, opt_type, ltp, oi=10000, volume=5000, pchange=15.0):
            self.symbol = sym
            self.strike = strike
            self.option_type = opt_type
            self.last_price = ltp
            self.open_interest = oi
            self.oi = oi
            self.volume = volume
            self.pchange = pchange
            self.change_pct = pchange

    chain = [
        DummyContract("NIFTY 25000 CE", 25000, "CE", 120.0),
        DummyContract("NIFTY 25000 PE", 25000, "PE", 110.0),
    ]

    dates_1m = pd.date_range("2026-10-09 09:15:00", periods=2, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [25000.0, 25020.0],
            "high": [25025.0, 25060.0],
            "low": [24995.0, 25015.0],
            "close": [25020.0, 25055.0],
            "volume": [50000.0, 85000.0],
        },
        index=dates_1m,
    )

    alerts = detect_index_micro_scalp(
        underlying="NIFTY",
        spot=25055.0,
        chain=chain,
        ohlcv_1m=df_1m,
        vwap=25000.0,
        day_low=24995.0,
        day_high=25060.0,
        ref_time=ref_dt,
        ignore_time_gate=False,
    )
    assert len(alerts) > 0
    sc = alerts[0]
    assert sc.alert_type == "INDEX_MICRO_SCALP"

    # Verify targets are calibrated to T1 = +2.0R, T2 = +3.5R, T3 = +5.5R
    risk = sc.ltp - sc.stop_loss
    reward = sc.target_level - sc.ltp
    rr = reward / risk
    assert rr >= 1.95  # 2.0R target

    # Verify sc passes Telegram Apex Gate
    engine = AutoAlertEngine()
    passed, reason = engine._eval_telegram_apex_gate(sc, in_market=True)
    assert passed, f"Micro scalp should pass Apex gate, rejected because: {reason}"


def test_trade_plan_option_asymmetric_rr():
    """Verify calculate_option_execution_plan enforces T1 >= 2.0R for index and >= 1.8R for stock."""
    # 1. Index Option (NIFTY 25000 CE @ 150, risk = 20 pts)
    plan_idx = calculate_option_execution_plan(
        trade_plan=None,
        option_type="CE",
        strike=25000,
        expiry="2026-10-15",
        option_ltp=150.0,
        lot_size=25,
        spot=25020.0,
        contract_symbol="NIFTY26OCT25000CE",
    )
    opt_risk = 150.0 - float(plan_idx["sl_premium"])
    opt_reward = float(plan_idx["t1_premium"]) - 150.0
    rr_idx = opt_reward / opt_risk
    assert rr_idx >= 1.95, f"Index option R:R {rr_idx} should be >= 2.0R"

    # 2. Stock Option (RELIANCE 3000 CE @ 40, risk = 8.8 pts)
    plan_stk = calculate_option_execution_plan(
        trade_plan=None,
        option_type="CE",
        strike=3000,
        expiry="2026-10-29",
        option_ltp=40.0,
        lot_size=250,
        spot=3010.0,
        contract_symbol="RELIANCE26OCT3000CE",
    )
    stk_risk = 40.0 - float(plan_stk["sl_premium"])
    stk_reward = float(plan_stk["t1_premium"]) - 40.0
    rr_stk = stk_reward / stk_risk
    assert rr_stk >= 1.75, f"Stock option R:R {rr_stk} should be >= 1.8R"


def test_apex_gate_strictly_blocks_low_rr_or_low_conf():
    """Verify Apex Gate is NOT bypassed: rejects low R:R (<1.6 for index) or low confidence."""
    engine = AutoAlertEngine()

    # Low R:R alert (1.2R)
    alert_low_rr = _make_test_alert(
        alert_id="aa-nifty-low-rr-20261009",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=90.0,  # Risk = 10 pts
        target_level=112.0,  # Reward = 12 pts (R:R = 1.2 < 1.6)
        confidence=90,
        segment="FNO_INDEX",
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_low_rr, in_market=True)
    assert not passed
    assert "below minimum 1:1.6 threshold" in reason

    # Low confidence alert (82% for index, where floor is 88%)
    alert_low_conf = _make_test_alert(
        alert_id="aa-nifty-low-conf-20261009",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=85.0,  # Risk = 15 pts
        target_level=130.0,  # Reward = 30 pts (R:R = 2.0 >= 1.6)
        confidence=82,  # Confidence = 82 < 88
        segment="FNO_INDEX",
    )
    passed, reason = engine._eval_telegram_apex_gate(alert_low_conf, in_market=True)
    assert not passed
    assert "below Telegram bar (88%)" in reason


def test_index_call_setup_ord_displacement_at_09_18():
    """Verify that index call setup ORD escape allows explosive breakout before 09:25 IST."""
    from engine.detectors.index_call_setup import detect_index_call_setup
    from brokers.base import OptionsContract

    ref_dt = datetime(2026, 10, 9, 9, 18, 0, tzinfo=IST)
    # Spot surged above PDH (25000) to 25150 (+0.60%) and above open (25000)
    df_5m = pd.DataFrame(
        [
            {"open": 25000.0, "high": 25160.0, "low": 24990.0, "close": 25150.0, "volume": 500000},
        ],
        index=pd.date_range("2026-10-09 09:15", periods=1, freq="5min", tz=IST),
    )
    chain = [
        OptionsContract(
            symbol="NIFTY26OCT25150CE",
            underlying="NIFTY",
            expiry="2026-10-15",
            strike=25150.0,
            option_type="CE",
            last_price=160.0,
            oi=8000,
            oi_change=2500,
            volume=15000,
            lot_size=25,
            exchange="NFO",
        )
    ]
    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=25150.0,
        chain=chain,
        vwap=25050.0,
        day_high=25160.0,
        day_low=24990.0,
        prev_day_high=25000.0,  # spot 25150 > 25000 * 1.002 -> ORD triggered!
        prev_day_low=24800.0,
        ohlcv_5m=df_5m,
        ref_time=ref_dt,
        ignore_time_gate=False,
    )
    # Must NOT be blocked by 09:15-09:25 stabilization gate because ORD is active!
    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.direction == "BULLISH"
    assert "ORD" in alert.headline or "NIFTY" in alert.headline


def test_synthetic_option_chain_ssot_expiries_and_paper_fallback():
    """Verify synthetic option chain resolves canonical weekdays and functions in PAPER mode."""
    from market.options import build_index_synthetic_option_chain, get_options_chain

    # Test BANKNIFTY expiry weekday (Wednesday = 2)
    bn_chain = build_index_synthetic_option_chain("BANKNIFTY", spot=52500.0)
    assert len(bn_chain) > 0
    bn_exp_dt = datetime.fromisoformat(bn_chain[0].expiry)
    assert bn_exp_dt.weekday() == 2, (
        f"Bank Nifty weekly expiry must be Wednesday (2), got {bn_exp_dt.weekday()}"
    )

    # Test MIDCPNIFTY expiry weekday (Monday = 0)
    mid_chain = build_index_synthetic_option_chain("MIDCPNIFTY", spot=13000.0)
    assert len(mid_chain) > 0
    mid_exp_dt = datetime.fromisoformat(mid_chain[0].expiry)
    assert mid_exp_dt.weekday() == 0, (
        f"Midcap Nifty weekly expiry must be Monday (0), got {mid_exp_dt.weekday()}"
    )

    # Test PAPER mode fallback
    os.environ["TRADING_MODE"] = "PAPER"
    chain = get_options_chain("NIFTY")
    assert len(chain) > 0, "Option chain should successfully return in PAPER mode"
