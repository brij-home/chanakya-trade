"""
tests/test_pure_equity_unpaced_setups.py
────────────────────────────────────────
Deterministic regression & invariant tests for pure equity signals:
1. Pure equity signals that fit the setup bypass hourly stock pacing limits.
2. Pure equity signals that fit the setup bypass daily stock caps.
3. Pure equity signals that fit the setup bypass cross-symbol segment burst throttle (PACING:EQUITY).
4. Corrupted or inverted equity signals do NOT qualify for exemption and remain governed.
5. F&O stock options still strictly respect F&O pacing limits.
6. Pacing retry loop immediately dispatches fitting pure equity setups.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from unittest.mock import patch
import pytest

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def _make_equity_alert(
    alert_id: str,
    symbol: str,
    direction: str = "BULLISH",
    confidence: int = 85,
    ltp: float = 1500.0,
    entry: float = 1500.0,
    sl: float = 1470.0,
    t1: float = 1560.0,
    segment: str = "EQUITY",
    stage: str = "IGNITED",
    metrics: dict = None,
    actionable_plan: dict = None,
) -> AutoAlert:
    return AutoAlert(
        alert_id=alert_id,
        alert_type="STAGE_1_TO_2_EXPANSION",
        stage=stage,
        symbol=symbol,
        exchange="NSE",
        direction=direction,
        headline=f"🚀 {symbol} Pure Equity Breakout",
        summary=f"Technical breakout setup for {symbol}",
        ltp=ltp,
        trigger_level=entry,
        target_level=t1,
        stop_loss=sl,
        segment=segment,
        confidence=confidence,
        metrics=metrics or {"sector_id": "auto"},
        actionable_plan=actionable_plan or {"action": "BUY"},
        is_live=True,
        environment="LIVE",
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    )


@pytest.fixture
def engine():
    eng = AutoAlertEngine()
    eng._alerts.clear()
    eng._dispatch_cooldowns.clear()
    eng._hourly_telegram_dispatches = {
        "INDEX": [],
        "STOCKS": [],
        "FNO_STOCK": [],
        "EQUITY": [],
    }
    yield eng
    eng._alerts.clear()
    eng._dispatch_cooldowns.clear()


def test_fits_pure_equity_setup_validation(engine):
    """Verify that fits_pure_equity_setup strictly validates technical trade geometry."""
    # 1. Valid Bullish setup (SL 1470 < Entry 1500 < T1 1560, RR = 60/30 = 2.0 >= 1.4)
    valid_bull = _make_equity_alert("eq-tata-1", "TATAMOTORS", sl=1470.0, entry=1500.0, t1=1560.0)
    assert engine.is_pure_equity(valid_bull) is True
    assert engine.fits_pure_equity_setup(valid_bull) is True

    # 2. Valid Bearish setup (T1 1400 < Entry 1500 < SL 1550, RR = 100/50 = 2.0 >= 1.4)
    valid_bear = _make_equity_alert(
        "eq-tata-bear",
        "TATAMOTORS",
        direction="BEARISH",
        sl=1550.0,
        entry=1500.0,
        t1=1400.0,
    )
    assert engine.is_pure_equity(valid_bear) is True
    assert engine.fits_pure_equity_setup(valid_bear) is True

    # 3. Inverted Bullish SL (SL > Entry)
    inverted_sl = _make_equity_alert("eq-bad-sl", "INFY", sl=1520.0, entry=1500.0, t1=1560.0)
    assert engine.fits_pure_equity_setup(inverted_sl) is False

    # 4. Inverted Bullish Target (T1 < Entry)
    inverted_tp = _make_equity_alert("eq-bad-tp", "INFY", sl=1470.0, entry=1500.0, t1=1480.0)
    assert engine.fits_pure_equity_setup(inverted_tp) is False

    # 5. Inadequate Risk:Reward (Risk = 30, Reward = 20, RR = 0.67 < 1.4)
    poor_rr = _make_equity_alert("eq-poor-rr", "INFY", sl=1470.0, entry=1500.0, t1=1520.0)
    assert engine.fits_pure_equity_setup(poor_rr) is False

    # 6. Derivative option alert is NOT pure equity
    opt_alert = _make_equity_alert("eq-opt", "RELIANCE")
    opt_alert.contract_symbol = "RELIANCE26OCT2900CE"
    opt_alert.strike = 2900.0
    opt_alert.option_type = "CE"
    assert engine.is_pure_equity(opt_alert) is False
    assert engine.fits_pure_equity_setup(opt_alert) is False


def test_pure_equity_bypasses_hourly_stock_pacing(engine):
    """Pure equity signals fitting the setup are NOT blocked when hourly pacing limit is saturated."""
    now_t = time.time()
    # Saturate equity dispatches with 8 previous alerts in the last 30m
    engine._hourly_telegram_dispatches["EQUITY"] = [now_t - (i * 100) for i in range(8)]
    engine._hourly_telegram_dispatches["STOCKS"] = list(
        engine._hourly_telegram_dispatches["EQUITY"]
    )

    alert = _make_equity_alert(
        "eq-breakout-maruti",
        "MARUTI",
        ltp=12500.0,
        entry=12500.0,
        sl=12300.0,
        t1=13000.0,
        confidence=88,
    )

    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCKS_PER_HOUR": "2"}):
        passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True, now_ts=now_t)
        assert passed is True, (
            f"Expected pure equity setup to bypass hourly pacing, but got: {reason}"
        )


def test_pure_equity_bypasses_daily_stock_cap(engine):
    """Pure equity signals fitting the setup are NOT blocked when daily stock limit is reached."""
    now_t = time.time()
    today_str = datetime.fromtimestamp(now_t, tz=IST).strftime("%Y-%m-%d")
    # Simulate daily cap reached (12 dispatches today across sectors)
    engine._sector_daily_telegram[today_str]["auto"] = 6
    engine._sector_daily_telegram[today_str]["banking"] = 6

    alert = _make_equity_alert(
        "eq-breakout-tatasteel",
        "TATASTEEL",
        ltp=160.0,
        entry=160.0,
        sl=155.0,
        t1=172.0,
        confidence=86,
    )

    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCKS_PER_DAY": "6"}):
        passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True, now_ts=now_t)
        assert passed is True, (
            f"Expected pure equity setup to bypass daily stock cap, but got: {reason}"
        )


def test_pure_equity_bypasses_cross_symbol_burst_cooldown(engine):
    """Pure equity signals fitting setup are NOT held by 45s cross-symbol burst cooldown (PACING:EQUITY)."""
    now_t = time.time()
    # Simulate a recent dispatch on another equity ticker 5 seconds ago
    engine._dispatch_cooldowns["PACING:EQUITY"] = now_t - 5.0
    engine._dispatch_cooldowns["PACING:EQUITY:RELIANCE"] = now_t - 5.0

    # Incoming new equity setup for TATASTEEL (different symbol)
    alert = _make_equity_alert(
        "eq-breakout-tatasteel-2",
        "TATASTEEL",
        ltp=160.0,
        entry=160.0,
        sl=155.0,
        t1=172.0,
        confidence=86,
    )

    passed, reason = engine._eval_telegram_apex_gate(alert, in_market=True, now_ts=now_t)
    assert passed is True, f"Expected cross-symbol burst pacing bypass, but got: {reason}"


def test_corrupted_equity_setup_does_not_bypass_pacing(engine):
    """Corrupted equity signal (e.g. inverted SL) does NOT qualify for exemption and is governed."""
    now_t = time.time()
    engine._hourly_telegram_dispatches["EQUITY"] = [now_t - (i * 100) for i in range(5)]
    engine._hourly_telegram_dispatches["STOCKS"] = list(
        engine._hourly_telegram_dispatches["EQUITY"]
    )

    # Setup with inverted SL (SL 1550 > Entry 1500 on Long)
    bad_alert = _make_equity_alert(
        "eq-bad-setup",
        "WIPRO",
        direction="BULLISH",
        entry=1500.0,
        sl=1550.0,
        t1=1600.0,
        confidence=80,
    )

    with patch.dict(os.environ, {"TELEGRAM_MAX_STOCKS_PER_HOUR": "2"}):
        passed, reason = engine._eval_telegram_apex_gate(bad_alert, in_market=True, now_ts=now_t)
        assert passed is False
        assert "pacing limit reached" in reason or "Inverted" in reason


def test_fno_stock_options_still_strictly_paced(engine):
    """Stock options (F&O) do NOT receive pure equity exemption and strictly enforce pacing."""
    now_t = time.time()
    engine._hourly_telegram_dispatches["FNO_STOCK"] = [now_t - (i * 100) for i in range(5)]
    engine._hourly_telegram_dispatches["STOCKS"] = list(
        engine._hourly_telegram_dispatches["FNO_STOCK"]
    )

    # Stock option setup (confidence 88 < 95 Apex floor)
    opt_alert = AutoAlert(
        alert_id="opt-infy-ce",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="INFY",
        exchange="NFO",
        direction="BULLISH",
        headline="INFY 1900 CE Call Momentum",
        summary="Stock option momentum",
        ltp=35.0,
        trigger_level=35.0,
        target_level=50.0,
        stop_loss=25.0,
        segment="FNO_STOCK",
        strike=1900.0,
        option_type="CE",
        contract_symbol="NSE:INFY26OCT1900CE",
        confidence=88,
        is_live=True,
        environment="LIVE",
    )

    with patch.dict(os.environ, {"TELEGRAM_MAX_FNO_STOCKS_PER_HOUR": "2"}):
        passed, reason = engine._eval_telegram_apex_gate(opt_alert, in_market=True, now_ts=now_t)
        assert passed is False
        assert "stocks hourly pacing limit reached" in reason


def test_retry_pacing_throttled_alerts_for_pure_equity(engine):
    """Verify _retry_pacing_throttled_alerts immediately dispatches fitting pure equity setups."""
    now_t = time.time()
    today_str = datetime.fromtimestamp(now_t, tz=IST).strftime("%Y-%m-%d")

    alert = _make_equity_alert(
        "eq-retry-candidate",
        "BAJFINANCE",
        ltp=7000.0,
        entry=7000.0,
        sl=6850.0,
        t1=7350.0,
        confidence=90,
    )
    alert.created_at = f"{today_str} 10:15:00 IST"
    alert.telegram_dispatched = False
    alert.telegram_suppression_reason = "Telegram pacing throttle active on EQUITY (5s < 45s)"

    engine._alerts.append(alert)
    engine._dispatch_cooldowns["PACING:EQUITY"] = now_t - 5.0
    engine._dispatch_cooldowns["PACING:EQUITY:BAJFINANCE"] = now_t - 5.0

    with patch("engine.alerts._is_market_hours", return_value=True):
        with patch.object(engine, "_dispatch", wraps=engine._dispatch) as mock_dispatch:
            dispatched = engine._retry_pacing_throttled_alerts()
            assert len(dispatched) > 0
            assert mock_dispatch.called
