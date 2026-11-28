"""
tests/test_turtle_soup.py
─────────────────────────
Unit tests for the Turtle Soup / Liquidity Sweep Inversion detector.
Verifies identification of Bullish Spring (Bear Trap) and Bearish Upthrust (Bull Trap).
"""

from __future__ import annotations

from datetime import date
import pandas as pd
import numpy as np

from engine.detectors.turtle_soup import detect_turtle_soup_sweep


def _generate_synthetic_base(n_bars: int = 25, base_price: float = 1000.0) -> pd.DataFrame:
    """Generates a stable trading range dataframe."""
    np.random.seed(42)
    rows = []
    curr = base_price
    for i in range(n_bars):
        o = curr
        h = o + 4.0 + np.random.uniform(0, 3)
        l = o - 4.0 - np.random.uniform(0, 3)
        c = o + np.random.uniform(-2, 2)
        v = 10000.0 + np.random.uniform(0, 2000)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        curr = c
    return pd.DataFrame(rows)


def test_turtle_soup_bullish_spring(monkeypatch):
    """Verify detection of a Bear Trap (Bullish Spring) at swing low."""
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda *args, **kwargs: None)
    df = _generate_synthetic_base(n_bars=22, base_price=1000.0)

    # Establish a clear swing low in the prior 20 bars
    prior_low = float(df["low"].iloc[:-2].min())

    # Create a spring candle on the last bar:
    # Pierces below prior_low by ~0.4%, but closes well back above it with a long lower wick
    spring_open = prior_low + 2.0
    spring_low = prior_low - (prior_low * 0.004)  # 0.4% sweep
    spring_close = prior_low + 3.0
    spring_high = spring_close + 1.0

    df.iloc[-1] = {
        "open": spring_open,
        "high": spring_high,
        "low": spring_low,
        "close": spring_close,
        "volume": 25000.0,
    }

    d = date(2026, 10, 3)
    alert = detect_turtle_soup_sweep("NSE:INFY", df=df, ltp=spring_close, session_date=d)

    assert alert is not None
    assert alert.direction == "BULLISH"
    assert alert.alert_type == "TURTLE_SOUP_SWEEP"
    assert alert.stop_loss < spring_low
    assert alert.target_level > alert.trigger_level
    assert alert.actionable_plan is not None
    assert alert.actionable_plan["action"] in ("BUY", "BUY_CALL")
    assert alert.metrics["sweep_type"] == "BULLISH_SPRING"
    assert alert.alert_id.startswith("aa-turtle-soup-sweep-infy-spring-20261003")
    assert "recommended_structure" in alert.metrics
    assert "market_phase" in alert.metrics


def test_turtle_soup_bearish_upthrust():
    """Verify detection of a Bull Trap (Bearish Upthrust) at swing high."""
    df = _generate_synthetic_base(n_bars=22, base_price=2000.0)

    # Establish a clear swing high in the prior 20 bars
    prior_high = float(df["high"].iloc[:-2].max())

    # Create an upthrust candle on the last bar:
    # Pierces above prior_high by ~0.4%, but closes well back below it with a long upper wick
    upthrust_open = prior_high - 3.0
    upthrust_high = prior_high + (prior_high * 0.004)  # 0.4% sweep
    upthrust_close = prior_high - 4.0
    upthrust_low = upthrust_close - 1.0

    df.iloc[-1] = {
        "open": upthrust_open,
        "high": upthrust_high,
        "low": upthrust_low,
        "close": upthrust_close,
        "volume": 28000.0,
    }

    d = date(2026, 10, 3)
    alert = detect_turtle_soup_sweep("NSE:RELIANCE", df=df, ltp=upthrust_close, session_date=d)

    assert alert is not None
    assert alert.direction == "BEARISH"
    assert alert.alert_type == "TURTLE_SOUP_SWEEP"
    if alert.contract_symbol:
        assert 0 < alert.stop_loss < alert.trigger_level < alert.target_level
        spot_sl = float(
            str(alert.actionable_plan["underlying_sl"]).replace("₹", "").replace(",", "")
        )
        assert spot_sl > upthrust_high
    else:
        assert alert.stop_loss > upthrust_high
        assert alert.target_level < alert.trigger_level
    assert alert.actionable_plan is not None
    assert alert.actionable_plan["action"] in ("SELL", "BUY_PUT")
    assert alert.metrics["sweep_type"] == "BEARISH_UPTHRUST"
    assert alert.alert_id.startswith("aa-turtle-soup-sweep-reliance-upthrust-20261003")


def test_turtle_soup_genuine_breakout_ignored():
    """Verify that a genuine expansive breakout with close above level does not trigger a false reversal."""
    df = _generate_synthetic_base(n_bars=22, base_price=1500.0)
    prior_high = float(df["high"].iloc[:-2].max())

    # Strong breakout candle closing near its high, well above prior_high
    df.iloc[-1] = {
        "open": prior_high - 1.0,
        "high": prior_high + 25.0,
        "low": prior_high - 2.0,
        "close": prior_high + 23.0,
        "volume": 40000.0,
    }

    alert = detect_turtle_soup_sweep("NSE:HDFCBANK", df=df, ltp=prior_high + 23.0)
    # Genuine breakout should NOT trigger a Turtle Soup reversal!
    assert alert is None


def test_turtle_soup_option_contract_rendering_bearish_and_bullish(monkeypatch):
    """
    Regression test for RVNL 195 PE coordinate collision & Lot=1 leak:
    Verifies both BEARISH (PE) and BULLISH (CE) TURTLE_SOUP_SWEEP alerts with
    resolved option contracts render in option-premium coordinates with real lot sizes,
    never mixing spot entry (e.g. ₹191.0) with option SL/targets (₹9.38 / ₹12.69).
    """
    from unittest.mock import patch
    from bot.alert_templates import render_asymmetric_alert, render_auto_alert
    from engine.option_resolver import ResolvedOptionPlan

    # 1. Legacy/dict payload matching the exact RVNL 195 PE live incident
    legacy_rvnl = {
        "alert_id": "aa-turtle-soup-sweep-rvnl-upthrust-20261127",
        "alert_type": "TURTLE_SOUP_SWEEP",
        "symbol": "RVNL",
        "segment": "FNO_STOCK",
        "direction": "BEARISH",
        "confidence": 82,
        "ltp": 11.04,
        "trigger_level": 11.04,
        "stop_loss": 9.38,
        "target_level": 12.69,
        "underlying_spot": 191.41,
        "structural_spot_sl": 194.20,
        "contract_symbol": "NFO:RVNL26DEC195PE",
        "strike": 195.0,
        "option_type": "PE",
        "option_premium": 11.04,
        "expiry_date": "2026-12-29",
        "lot_size": 1,  # Legacy leaked placeholder default
        "signal_ref": "#SIG_RVNL_195PE_27NOV_1255",
        "actionable_plan": {
            "action": "BUY_PUT",
            "entry_range": "₹10.82 – ₹11.26",
            "trigger_level": 11.04,
            "stop_loss": "₹9.38",
            "target_1": "₹12.69",
            "target_2": "₹14.35",
            "risk_reward": "1:2.2",
            "no_chase_boundary": 11.59,
            "lot_size": 1,
            "underlying_sl": "₹194.20",
        },
    }

    msg_legacy = render_asymmetric_alert(legacy_rvnl, in_market=True)
    assert "TURTLE SOUP SHORT (BEARISH UPTHRUST)" in msg_legacy
    assert "Action: BUY RVNL 195 PE" in msg_legacy
    assert "₹10.82 – ₹11.26" in msg_legacy
    assert "(Lot: 1925)" in msg_legacy
    assert "Lot: 1)" not in msg_legacy
    assert "SHORT (SELL)" not in msg_legacy
    assert "₹191.0 – ₹191.8" not in msg_legacy
    assert "Risk: ₹182.03" not in msg_legacy
    assert "SL (Option):</b> <code>₹9.38</code> (Risk: ₹1.66 | ₹3,196/lot)" in msg_legacy
    assert "Structural SL (Spot):</b> <code>₹194.20</code>" in msg_legacy
    assert "T1 (+2R):</b> <code>₹12.69</code>" in msg_legacy
    assert "T2 (+4R):</b> <code>₹14.35</code>" in msg_legacy
    assert "(Downside)" not in msg_legacy

    # 2. Full detector -> AutoAlert -> render_auto_alert for BEARISH Upthrust (PE)
    monkeypatch.setattr("engine.daily_levels.get_daily_levels", lambda *args, **kwargs: None)
    df_bear = _generate_synthetic_base(n_bars=22, base_price=190.0)
    prior_high = float(df_bear["high"].iloc[:-2].max())
    df_bear.iloc[-1] = {
        "open": prior_high - 1.0,
        "high": prior_high + 1.2,
        "low": prior_high - 2.0,
        "close": prior_high - 1.2,
        "volume": 35000.0,
    }
    spot_bear = prior_high - 1.2

    mock_pe = ResolvedOptionPlan(
        contract_symbol="NFO:RVNL26DEC195PE",
        strike=195.0,
        option_type="PE",
        entry_premium=11.04,
        sl_premium=9.38,
        t1_premium=12.69,
        t2_premium=14.35,
        t3_premium=17.50,
        lot_size=1925,
        underlying_spot=spot_bear,
        underlying_sl=round(prior_high + 2.0, 2),
        underlying_target=round(spot_bear - 6.0, 2),
        expiry="2026-12-29",
    )

    with patch("engine.detectors.turtle_soup.resolve_option_contract", return_value=mock_pe):
        bear_alert = detect_turtle_soup_sweep(
            "NSE:RVNL", df=df_bear, ltp=spot_bear, session_date=date(2026, 11, 27)
        )

    assert bear_alert is not None
    assert bear_alert.lot_size == 1925
    assert bear_alert.expiry_date == "2026-12-29"
    assert bear_alert.actionable_plan["lot_size"] == 1925
    assert bear_alert.actionable_plan["option_plan"]["contract_symbol"] == "NFO:RVNL26DEC195PE"
    rendered_bear = render_auto_alert(bear_alert, in_market=True)
    assert "Action: BUY RVNL 195 PE" in rendered_bear
    assert "(Lot: 1925)" in rendered_bear
    assert "SHORT (SELL)" not in rendered_bear
    assert "Risk: ₹1.66" in rendered_bear

    # 3. Full detector -> AutoAlert -> render_auto_alert for BULLISH Spring (CE)
    df_bull = _generate_synthetic_base(n_bars=22, base_price=190.0)
    prior_low = float(df_bull["low"].iloc[:-2].min())
    df_bull.iloc[-1] = {
        "open": prior_low + 1.0,
        "high": prior_low + 2.0,
        "low": prior_low - 1.1,
        "close": prior_low + 1.2,
        "volume": 35000.0,
    }
    spot_bull = prior_low + 1.2

    mock_ce = ResolvedOptionPlan(
        contract_symbol="NFO:RVNL26DEC190CE",
        strike=190.0,
        option_type="CE",
        entry_premium=10.50,
        sl_premium=8.50,
        t1_premium=14.50,
        t2_premium=18.50,
        t3_premium=22.50,
        lot_size=1925,
        underlying_spot=spot_bull,
        underlying_sl=round(prior_low - 2.0, 2),
        underlying_target=round(spot_bull + 6.0, 2),
        expiry="2026-12-29",
    )

    with patch("engine.detectors.turtle_soup.resolve_option_contract", return_value=mock_ce):
        bull_alert = detect_turtle_soup_sweep(
            "NSE:RVNL", df=df_bull, ltp=spot_bull, session_date=date(2026, 11, 27)
        )

    assert bull_alert is not None
    assert bull_alert.lot_size == 1925
    rendered_bull = render_auto_alert(bull_alert, in_market=True)
    assert "TURTLE SOUP LONG (BULLISH SPRING)" in rendered_bull
    assert "Action: BUY RVNL 190 CE" in rendered_bull
    assert "(Lot: 1925)" in rendered_bull
    assert "SL (Option):</b> <code>₹8.50</code> (Risk: ₹2.00 | ₹3,850/lot)" in rendered_bull
    assert "T1 (+2R):</b> <code>₹14.50</code>" in rendered_bull
    assert "T2 (+4R):</b> <code>₹18.50</code>" in rendered_bull
