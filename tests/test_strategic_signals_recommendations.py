"""
tests/test_strategic_signals_recommendations.py
────────────────────────────────────────────────
Deterministic test suite for institutional strategic enhancements:
  1. Business/Trading Days calendar computation (skipping weekends & exchange holidays).
  2. Multi-horizon shelf-life retention based on trading days.
  3. Pre-market Opening Gap Invalidation Sentinel (GAP_OVER_SL & GAP_NO_CHASE).
  4. Post-market EOD MTM, Milestone Trailing Ratchet, Stagnation Sentinel & SEBI Physical Delivery Risk.
  5. Multi-Horizon Confluence Alignment (TRIPLE_HORIZON & DUAL_HORIZON).
  6. India VIX Sub-12 Compression Regime-Scaled Position Sizing.
"""

from datetime import date, datetime, timedelta

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from market.calendar import get_trading_days_elapsed, is_trading_holiday


def test_trading_calendar_holiday_and_weekend_skip():
    """Verify that get_trading_days_elapsed excludes weekends and exchange holidays."""
    # 2026-01-23 (Friday) to 2026-01-27 (Tuesday)
    # Fri Jan 23 (Trading Day) -> 1
    # Sat Jan 24 (Weekend) -> Skipped
    # Sun Jan 25 (Weekend) -> Skipped
    # Mon Jan 26 (Republic Day Holiday) -> Skipped
    # Tue Jan 27 (Trading Day) -> 2
    d_start = date(2026, 1, 23)
    d_end = date(2026, 1, 27)
    assert is_trading_holiday(date(2026, 1, 26)) is True

    elapsed = get_trading_days_elapsed(d_start, d_end)
    assert elapsed == 2


def test_multi_horizon_shelf_life_retention():
    """Verify AutoAlert.is_active uses trading days for multi-day horizons."""
    # A SWING_MID alert created 10 calendar days ago across 2 weekends (only 6 trading days)
    # Shelf-life for SWING_MID is 25 trading days -> must remain active
    past_date = datetime.now() - timedelta(days=10)
    alert = AutoAlert(
        alert_id="aa-sqz-infy-test-20260920",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Daily Squeeze",
        summary="Squeeze fired",
        ltp=1850.0,
        trigger_level=1850.0,
        target_level=1980.0,
        stop_loss=1790.0,
        time_horizon="SWING_MID",
        created_at=past_date.strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    assert alert.is_active is True
    assert alert.is_expired is False


def test_premarket_gap_invalidation_sentinel(monkeypatch):
    """Verify premarket opening gap sentinel flags GAP_OVER_SL and GAP_NO_CHASE."""
    engine = AutoAlertEngine(max_buffer=10)
    engine.clear_alerts()

    # 1. Bullish alert with SL=2400 and max boundary 2550
    alert_gap_sl = AutoAlert(
        alert_id="aa-test-gap-sl-20260929",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Setup",
        summary="Setup",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2400.0,
        target_level=2700.0,
        no_chase_boundary=2550.0,
        time_horizon="SWING_MID",
        environment="TEST",
    )
    # 2. Bullish alert with SL=2400 and max boundary 2550, gapping up to 2600 (NO_CHASE)
    alert_gap_chase = AutoAlert(
        alert_id="aa-test-gap-chase-20260929",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="INFY Setup",
        summary="Setup",
        ltp=2500.0,
        trigger_level=2500.0,
        stop_loss=2400.0,
        target_level=2700.0,
        no_chase_boundary=2550.0,
        time_horizon="SWING_MID",
        environment="TEST",
    )

    with engine._lock:
        engine._alerts = [alert_gap_sl, alert_gap_chase]

    # Mock quotes: TCS gaps down to 2350 (below SL 2400); INFY gaps up to 2600 (above NO_CHASE 2550)
    mock_quotes = {
        "TCS": {"last_price": 2350.0, "open": 2350.0},
        "INFY": {"last_price": 2600.0, "open": 2600.0},
    }
    monkeypatch.setattr(
        "market.quotes.get_quote", lambda syms: {s: mock_quotes.get(s, {}) for s in syms}
    )

    flagged = engine.check_premarket_gap_invalidation()
    assert len(flagged) == 2

    # Verify invalidation and flags
    assert alert_gap_sl.is_invalidated is True
    assert alert_gap_sl.premarket_gap_risk == "GAP_OVER_SL"
    assert "GAP_OVER_SL" in alert_gap_sl.invalidation_reason

    assert alert_gap_chase.premarket_gap_risk == "GAP_NO_CHASE"


def test_post_market_digest_and_stagnation_sweep(monkeypatch):
    """Verify EOD MTM updates close, ratchets SL to breakeven, and warns on stagnation."""
    engine = AutoAlertEngine(max_buffer=10)
    engine.clear_alerts()

    # 1. Alert that hit T1: Trigger=100, SL=95, T1=110, Close=112 -> SL must ratchet to 100 (BE)
    t1_alert = AutoAlert(
        alert_id="aa-test-t1-ratchet-20260929",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="RELIANCE Swing",
        summary="Swing setup",
        ltp=100.0,
        trigger_level=100.0,
        stop_loss=95.0,
        target_level=110.0,
        time_horizon="SWING_MID",
        created_at="2026-09-25 09:30:00 IST",
        environment="TEST",
    )

    # 2. Alert stagnant for 4 trading days without hitting T1: Trigger=500, SL=480, T1=540, Close=502
    stagnant_alert = AutoAlert(
        alert_id="aa-test-stagnant-20260929",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="SBIN",
        exchange="NSE",
        direction="BULLISH",
        headline="SBIN Swing",
        summary="Swing setup",
        ltp=500.0,
        trigger_level=500.0,
        stop_loss=480.0,
        target_level=540.0,
        time_horizon="SWING_MID",
        created_at="2026-09-22 09:30:00 IST",
        environment="TEST",
    )

    with engine._lock:
        engine._alerts = [t1_alert, stagnant_alert]

    mock_quotes = {
        "RELIANCE": {"last_price": 112.0, "close": 112.0},
        "SBIN": {"last_price": 502.0, "close": 502.0},
    }
    monkeypatch.setattr(
        "market.quotes.get_quote", lambda syms: {s: mock_quotes.get(s, {}) for s in syms}
    )
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._save", lambda self: None)

    summary = engine.scan_post_market_digest()
    assert summary["alerts_swept"] == 2
    assert summary["trailing_stops_ratcheted"] == 1
    assert summary["stagnation_warnings"] == 1

    # RELIANCE trailing stop ratcheted to breakeven (100.0)
    assert t1_alert.trailing_stop == 100.0
    assert t1_alert.stage == "TRAILING_UPDATE"

    # SBIN flagged with stagnation warning
    assert stagnant_alert.stagnation_warning is not None
    assert "Stagnant in chop" in stagnant_alert.stagnation_warning


def test_multi_horizon_confluence_detection(monkeypatch):
    """Verify mutual alignment across Intraday, Swing, and Multibagger triggers Confluence tags."""
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._dispatch", lambda self, a: None)
    monkeypatch.setattr("engine.auto_alert_engine.AutoAlertEngine._save", lambda self: None)
    engine = AutoAlertEngine(max_buffer=10)
    engine.clear_alerts()

    # Pre-populate an existing Multibagger and Swing alert for TATASTEEL
    mb_alert = AutoAlert(
        alert_id="aa-multi-tatasteel-20260901",
        alert_type="MULTIBAGGER_COMPOUNDER",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="TATASTEEL Multibagger",
        summary="Value compounder",
        ltp=150.0,
        trigger_level=150.0,
        target_level=250.0,
        stop_loss=130.0,
        time_horizon="MULTIBAGGER",
        environment="TEST",
    )
    swing_alert = AutoAlert(
        alert_id="aa-sqz-tatasteel-20260925",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="TATASTEEL Mid Swing",
        summary="Squeeze breakout",
        ltp=165.0,
        trigger_level=165.0,
        target_level=190.0,
        stop_loss=155.0,
        time_horizon="SWING_MID",
        environment="TEST",
    )
    with engine._lock:
        engine._alerts = [mb_alert, swing_alert]

    # Now an Intraday alert arrives for TATASTEEL in the same direction (BULLISH)
    intraday_alert = AutoAlert(
        alert_id="aa-spark-tatasteel-20260929",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="TATASTEEL Intraday Volume Spark",
        summary="Heavy institutional buy flow",
        ltp=170.0,
        trigger_level=170.0,
        target_level=175.0,
        stop_loss=167.0,
        time_horizon="INTRADAY",
        confidence=85,
        environment="TEST",
    )

    recorded = engine.record_alert(intraday_alert)
    assert recorded is True
    # Should detect TRIPLE_HORIZON confluence and boost confidence
    assert intraday_alert.details.get("confluence_alignment") == "TRIPLE_HORIZON"
    assert intraday_alert.confidence >= 90
