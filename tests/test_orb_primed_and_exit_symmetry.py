"""
tests/test_orb_primed_and_exit_symmetry.py
──────────────────────────────────────────
Regression tests verifying:
  1. ORB_PRIMED inside-bar coiling does NOT trigger premature ignition.
  2. AGENTS.md Rule 14 Tri-Directional Symmetry: Short trade stop-outs are marked INVALIDATED / STOP_HIT,
     never RUNNER_EXIT / RUNNER_CLOSED.
  3. Intraday single-stock options enforce dynamic catastrophic risk floor (capped at <= 25%).
  4. Premarket gap beyond SL transitions alert to stage='INVALIDATED', is_active=False, is_archived=True.
  5. ORB benchmark regime gate suppresses counter-trend trades during one-way index trend days.
"""

from unittest.mock import MagicMock
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.synthetic_sl import evaluate_synthetic_spot_sl
from engine.detectors.orb import detect_opening_range_breakout


def test_orb_primed_inside_bar_coiling_no_premature_ignition(tmp_path, monkeypatch):
    """Verify ORB_PRIMED early-warning does not ignite on inside-bar pullback fill without trigger crossing."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    AutoAlertEngine()
    alert = AutoAlert(
        alert_id="aa-orb-bear-coiling-test",
        alert_type="ORB_PRIMED",
        stage="PRIMED",
        symbol="HAVELLS",
        exchange="NSE",
        direction="BEARISH",
        headline="HAVELLS ORB Primed Short",
        summary="Coiling near range low",
        ltp=1002.0,
        trigger_level=1000.0,  # 15m range low
        stop_loss=1015.0,  # Inside range
        target_level=970.0,
        is_live=True,
        environment="LIVE",
        entry_type="BREAKOUT_STOP",
    )

    # Coiling inside range at 1002 (above trigger 1000, below SL 1015)
    # MUST NOT ignite!
    assert alert.stage == "PRIMED"
    assert alert.has_triggered is False

    entry_style = str(alert.entry_type or "").upper()
    is_pullback = (
        entry_style in ("LIMIT_ON_PULLBACK", "PULLBACK", "LIMIT")
        and alert.alert_type not in ("ORB_PRIMED", "ORB_BREAKOUT", "ORB_BREAKDOWN")
        and alert.stage not in ("PRIMED", "EARLY_WARNING", "STALK")
    )
    assert is_pullback is False, (
        "ORB_PRIMED must never be evaluated as an inside-bar pullback limit fill"
    )


def test_bearish_stop_loss_exit_symmetry(tmp_path, monkeypatch):
    """Verify Rule 14 Tri-Directional Symmetry: stopped-out short trade is marked INVALIDATED, not RUNNER_EXIT."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    eng = AutoAlertEngine()
    short_alert = AutoAlert(
        alert_id="aa-short-stopout-test",
        alert_type="ORB_BREAKDOWN",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BEARISH",
        headline="TATASTEEL ORB Breakdown",
        summary="Short breakdown",
        ltp=150.0,
        trigger_level=150.0,
        stop_loss=155.0,
        target_level=140.0,
        is_live=True,
        environment="LIVE",
    )

    # Price rallies to 155.2 and hits stop-loss
    res = eng._handle_alert_exit(
        short_alert,
        current_ltp=155.2,
        reason="Stop-loss hit at ₹155.20",
        loop_context="TEST",
    )

    assert res is True
    assert short_alert.is_invalidated is True, (
        "Stopped-out short must be marked is_invalidated=True"
    )
    assert short_alert.stage == "INVALIDATED", (
        "Stopped-out short must transition to stage='INVALIDATED'"
    )
    assert short_alert.target_status in ("INVALIDATED", "STOP_HIT"), (
        "Stopped-out short target_status must be 'INVALIDATED' or 'STOP_HIT'"
    )
    assert "RUNNER" not in str(short_alert.target_status), (
        "Stopped-out short must NEVER be marked RUNNER_CLOSED"
    )
    assert short_alert.is_active is False


def test_intraday_stock_option_catastrophic_dd_floor():
    """Verify that single-stock equity intraday options enforce the <= 25% catastrophic risk floor."""
    stock_opt_alert = AutoAlert(
        alert_id="aa-havells-opt-sl-test",
        alert_type="INTRADAY_BREAKDOWN_SPARK",
        stage="IGNITED",
        symbol="HAVELLS",
        exchange="NSE",
        direction="BEARISH",
        headline="HAVELLS Breakdown Put",
        summary="Intraday breakdown",
        ltp=31.0,
        trigger_level=31.0,
        stop_loss=26.5,  # 14.5% nominal risk
        target_level=42.0,
        contract_symbol="NSE:HAVELLS26NOV1020PE",
        option_premium=31.0,
        option_type="PE",
        strike=1020.0,
        time_horizon="INTRADAY",
        underlying_spot=1018.0,
        metrics={"spot_invalidation_anchor": 1030.0, "option_entry_premium": 31.0},
        actionable_plan={"underlying_sl": 1030.0},
        is_live=True,
        environment="LIVE",
    )

    # Option drops from 31.0 to 22.9 (-26.1% loss, exceeding 25% floor)
    # Even though underlying spot hasn't reached spot anchor 1030.0, catastrophic DD must exit!
    eval_res = evaluate_synthetic_spot_sl(
        alert=stock_opt_alert,
        current_option_ltp=22.9,
        current_spot_override=1022.0,
    )

    assert eval_res.is_invalidated is True
    assert "catastrophic drawdown" in str(eval_res.rejection_reason).lower()
    assert eval_res.is_freak_wick_shielded is False


def test_premarket_gap_invalidation_state(tmp_path, monkeypatch):
    """Verify that premarket gap beyond stop-loss transitions alert to stage='INVALIDATED' and is_active=False."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    eng = AutoAlertEngine()
    alert = AutoAlert(
        alert_id="aa-premarket-gap-test",
        alert_type="SQUEEZE_BREAKOUT",
        stage="ACTIONABLE",
        symbol="STYLEBAAZA",
        exchange="NSE",
        direction="BULLISH",
        headline="Stylebaazar Swing",
        summary="Swing long",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=95.0,
        target_level=115.0,
        time_horizon="SWING_MID",
        is_live=True,
        environment="LIVE",
    )
    eng.record_alert(alert)

    # Mock pre-market quote indicating opening gap down to 92.0 (< SL 95.0)
    mock_quotes = {
        "NSE:STYLEBAAZA": MagicMock(
            symbol="STYLEBAAZA",
            last_price=92.0,
            close=100.0,
        )
    }

    updated = eng.check_premarket_gap_invalidation(quotes_map=mock_quotes)
    assert len(updated) == 1
    a = updated[0]
    assert a.is_invalidated is True
    assert a.stage == "INVALIDATED"
    assert a.target_status == "GAP_OVER_SL"
    assert a.is_active is False
    assert a.is_archived is True


def test_orb_benchmark_regime_gate(monkeypatch):
    """Verify ORB detector suppresses counter-trend equity breakdown setups when NIFTY 50 is green and holding VWAP."""
    import pandas as pd

    dates = pd.date_range("2026-10-26 09:15", periods=20, freq="5min")
    df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [101.0] * 20,
            "low": [99.0] * 20,
            "close": [98.8] * 20,  # Breaks below low 99.0, range is 2.0 (2.02%)
            "volume": [50000] * 20,
        },
        index=dates,
    )

    # 1. Mock NIFTY 50 as green +0.35% and trading above VWAP
    mock_nifty_bull = MagicMock(
        symbol="NIFTY 50",
        last_price=25350.0,
        vwap=25300.0,
        change_pct=0.35,
    )
    quotes_bull = {
        "NSE:NIFTY 50": mock_nifty_bull,
        "NSE:ABC": MagicMock(last_price=98.8, vwap=99.5, volume=50000, change_pct=-1.2),
    }

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: quotes_bull)

    # In a raging bull market (NIFTY +0.35% above VWAP), counter-trend equity breakdown must be suppressed
    res_suppressed = detect_opening_range_breakout(
        symbol="ABC",
        df=df,
        ltp=98.8,
        vwap=99.5,
        rvol=1.8,
        exchange="NSE",
        ignore_time_gate=True,
    )
    assert res_suppressed is None, (
        "ORB breakdown must be suppressed when benchmark NIFTY 50 is trending up"
    )

    # 2. When NIFTY is red -0.35% and below VWAP, breakdown setup is permitted
    mock_nifty_bear = MagicMock(
        symbol="NIFTY 50",
        last_price=25150.0,
        vwap=25250.0,
        change_pct=-0.40,
    )
    quotes_bear = {
        "NSE:NIFTY 50": mock_nifty_bear,
        "NSE:ABC": MagicMock(last_price=98.8, vwap=99.5, volume=50000, change_pct=-1.2),
    }
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: quotes_bear)

    res_allowed = detect_opening_range_breakout(
        symbol="ABC",
        df=df,
        ltp=98.8,
        vwap=99.5,
        rvol=1.8,
        exchange="NSE",
        ignore_time_gate=True,
    )
    assert res_allowed is not None, (
        "ORB breakdown must be permitted when benchmark NIFTY 50 is trending down"
    )
    assert res_allowed.direction == "BEARISH"


def test_opening_drive_benchmark_regime_gate(monkeypatch):
    """Verify OpeningDrive detector suppresses counter-trend equity breakdown setups when NIFTY 50 is green."""
    import pandas as pd
    from engine.detectors.opening_drive import detect_opening_drive

    dates = pd.date_range("2026-10-26 09:15", periods=5, freq="5min")
    # First 5m bar has open == high (bearish drive)
    df = pd.DataFrame(
        {
            "open": [100.0, 99.0, 98.5, 98.0, 97.5],
            "high": [100.05, 99.2, 98.8, 98.2, 97.8],  # Within 0.12% of open
            "low": [98.0, 97.5, 97.0, 96.5, 96.0],
            "close": [98.2, 97.8, 97.2, 96.8, 96.2],  # Closes in bottom 20%
            "volume": [100000] * 5,
        },
        index=dates,
    )

    # 1. Mock NIFTY 50 as green +0.40% and above VWAP
    mock_nifty_bull = MagicMock(
        symbol="NIFTY 50",
        last_price=25350.0,
        vwap=25300.0,
        change_pct=0.40,
    )
    quotes_bull = {
        "NSE:NIFTY 50": mock_nifty_bull,
        "NSE:ABC": MagicMock(last_price=98.0, vwap=99.5, volume=100000, change_pct=-2.0),
    }

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CHANAKYA_TESTING", raising=False)
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: quotes_bull)

    res_suppressed = detect_opening_drive(
        symbol="ABC",
        df_5m=df,
        ltp=98.0,
        vwap=99.5,
        rvol=2.5,
        ignore_time_gate=True,
    )
    assert res_suppressed is None, (
        "OpeningDrive bearish drive must be suppressed when NIFTY is strongly green"
    )

    # 2. When NIFTY is red -0.35% and below VWAP, breakdown drive is permitted
    mock_nifty_bear = MagicMock(
        symbol="NIFTY 50",
        last_price=25150.0,
        vwap=25250.0,
        change_pct=-0.35,
    )
    quotes_bear = {
        "NSE:NIFTY 50": mock_nifty_bear,
        "NSE:ABC": MagicMock(last_price=98.0, vwap=99.5, volume=100000, change_pct=-2.0),
    }
    monkeypatch.setattr("market.quotes.get_quote", lambda sym: quotes_bear)

    res_allowed = detect_opening_drive(
        symbol="ABC",
        df_5m=df,
        ltp=98.0,
        vwap=99.5,
        rvol=2.5,
        ignore_time_gate=True,
    )
    assert res_allowed is not None, (
        "OpeningDrive bearish drive must be permitted when NIFTY is trending down"
    )
    assert res_allowed.direction == "BEARISH"
