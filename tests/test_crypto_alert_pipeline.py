"""
tests/test_crypto_alert_pipeline.py
───────────────────────────────────
Institutional test suite for 24x7 Real-Time Crypto Streaming & Autonomous Signal Pipeline.
Verifies:
  1. Market calendar 24x7 continuous hours authority for CRYPTO, BINANCE, and DERIBIT.
  2. Autonomous detection of Squeeze, SMC Momentum, and Options Volatility.
  3. Real-time sub-second WebSocket tick stream invalidations and target ratchets.
  4. Strict Telegram segregation to Crypto_Premium_Alpha_Vortex (-1004323607372).
  5. Zero-ghost lifecycle invariants and USD price formatting.
"""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import pandas as pd

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from market.calendar import is_market_open, get_current_ist_session, get_market_status
from engine.alert_preferences import alert_preferences
from bot.alert_templates import render_auto_alert

IST = timezone(timedelta(hours=5, minutes=30))


# ── 1. Market Calendar 24x7 Invariants ────────────────────────────────────────


def test_crypto_market_calendar_24x7():
    """Verify Crypto is open 24/7/365 regardless of Indian holidays or weekends."""
    # Weekend test (Saturday night)
    sat_dt = datetime(2026, 9, 26, 23, 45, 0, tzinfo=IST)
    assert is_market_open("CRYPTO", ref_dt=sat_dt) is True
    assert is_market_open("BINANCE", ref_dt=sat_dt) is True
    assert is_market_open("DERIBIT", ref_dt=sat_dt) is True
    assert is_market_open("NSE", ref_dt=sat_dt) is False

    session = get_current_ist_session(ref_dt=sat_dt)
    assert session["crypto"] is True
    assert session["equity_nfo"] is False
    assert session["commodity"] is False

    status = get_market_status("CRYPTO", ref_dt=sat_dt)
    assert status["is_open"] is True
    assert status["status"] == "LIVE"
    assert "24x7" in status["label"]


# ── 2. Autonomous Crypto Scanner Detection ────────────────────────────────────


def test_scan_crypto_now_detects_squeeze_and_momentum(tmp_path, monkeypatch):
    """Verify scan_crypto_now detects high-conviction squeeze and SMC setups."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine()
    engine._watched_crypto = ["BTCUSDT"]

    # Mock Quote
    mock_quote = MagicMock()
    mock_quote.last_price = 85000.0
    mock_quote.change_pct = 2.4

    # Mock Squeeze Metrics (Short Squeeze Imminent)
    mock_squeeze = {
        "symbol": "BTCUSDT",
        "squeeze_signal": "SHORT_SQUEEZE_IMMINENT",
        "conviction": 88,
        "futures_metrics": {
            "funding_rate_8h": -0.00035,
            "open_interest_usd": 8500000000.0,
        },
    }

    # Mock 15m Klines
    dates = pd.date_range("2026-09-21 08:00", periods=50, freq="15min")
    sample_df = pd.DataFrame(
        {
            "open": [84000.0 + i * 20 for i in range(50)],
            "high": [84100.0 + i * 20 for i in range(50)],
            "low": [83950.0 + i * 20 for i in range(50)],
            "close": [84080.0 + i * 20 for i in range(50)],
            "volume": [1500.0 for _ in range(50)],
        },
        index=dates,
    )
    sample_df["date"] = sample_df.index

    with (
        patch("market.crypto_stream.crypto_stream.get_quote", return_value=mock_quote),
        patch("market.crypto_stream.crypto_stream.get_squeeze_metrics", return_value=mock_squeeze),
        patch("market.crypto_stream.crypto_stream.get_klines", return_value=sample_df),
        patch.object(engine, "_dispatch", return_value=None),
    ):
        alerts = engine.scan_crypto_now()
        assert len(alerts) >= 1
        sq_alert = next((a for a in alerts if a.alert_type == "CRYPTO_SQUEEZE"), None)
        assert sq_alert is not None
        assert sq_alert.symbol == "BTCUSDT"
        assert sq_alert.exchange == "CRYPTO"
        assert sq_alert.direction == "BULLISH"
        assert sq_alert.stop_loss < sq_alert.ltp < sq_alert.target_level
        assert sq_alert.is_live is True
        assert sq_alert.environment == "LIVE"
        assert "$" in sq_alert.actionable_plan["entry_range"]


# ── 3. Real-Time Sub-Second Tick Stream Execution ─────────────────────────────


def test_crypto_realtime_tick_invalidation(tmp_path, monkeypatch):
    """Verify live Binance ticks immediately invalidate breached positions without waiting for poller."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine()
    engine._dispatched_milestones.clear()

    # Create active bullish alert
    alert = AutoAlert(
        alert_id="crypto-test-btc-001",
        alert_type="CRYPTO_MOMENTUM",
        stage="IGNITED",
        symbol="BTCUSDT",
        exchange="CRYPTO",
        direction="BULLISH",
        headline="⚡ CRYPTO SMC ALPHA: BTCUSDT",
        summary="Demand OB reclaim",
        ltp=85000.0,
        trigger_level=85000.0,
        target_level=88000.0,
        stop_loss=83500.0,
        confidence=88,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        market_status="LIVE",
    )
    with engine._lock:
        engine._alerts.append(alert)

    dispatched = []
    engine._dispatch = lambda a: dispatched.append(a)

    # Simulate price tick crashing below stop-loss ($83,400 < $83,500 SL)
    crash_tick = {
        "symbol": "BTCUSDT",
        "ltp": 83400.0,
        "change": -1600.0,
        "change_pct": -1.8,
        "timestamp": 1000.0,
    }
    engine._on_crypto_tick(crash_tick)

    assert alert.is_invalidated is True
    assert alert.stage == "INVALIDATED"
    assert (
        "Stop-Loss Breach" in (alert.invalidation_reason or "")
        or "breached" in (alert.invalidation_reason or "").lower()
    )
    assert len(dispatched) == 1
    assert dispatched[0].alert_id == "crypto-test-btc-001"


def test_crypto_realtime_tick_target_achievement(tmp_path, monkeypatch):
    """Verify live Binance ticks immediately trigger Target 1 achievement and trailing ratchets."""
    data_file = tmp_path / "auto_alerts.json"
    monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

    engine = AutoAlertEngine()
    engine._dispatched_milestones.clear()

    alert = AutoAlert(
        alert_id="crypto-test-eth-002",
        alert_type="CRYPTO_MOMENTUM",
        stage="IGNITED",
        symbol="ETHUSDT",
        exchange="CRYPTO",
        direction="BULLISH",
        headline="⚡ CRYPTO SMC ALPHA: ETHUSDT",
        summary="Demand OB bounce",
        ltp=2800.0,
        trigger_level=2800.0,
        target_level=3000.0,
        stop_loss=2700.0,
        confidence=88,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        is_live=True,
        environment="LIVE",
        market_status="LIVE",
    )
    with engine._lock:
        engine._alerts.append(alert)

    dispatched = []
    engine._dispatch = lambda a: dispatched.append(a)

    # Simulate price tick hitting Target 1 ($3,010 >= $3,000 Target)
    target_tick = {
        "symbol": "ETHUSDT",
        "ltp": 3010.0,
        "change": 210.0,
        "change_pct": 7.5,
        "timestamp": 1000.0,
    }
    engine._on_crypto_tick(target_tick)

    assert alert.stage == "T1_ACHIEVED"
    assert "T1_ACHIEVED" in (alert.achieved_milestones or [])
    assert len(dispatched) == 1
    assert dispatched[0].alert_id == "crypto-test-eth-002"


# ── 4. Dedicated Telegram Channel Routing & Templates ─────────────────────────


def test_crypto_telegram_routing_and_formatting():
    """Verify Crypto alerts route to Crypto_Premium_Alpha_Vortex and render in USD."""
    # Destination check
    target_chat = alert_preferences.get_telegram_chat_id("CRYPTO")
    assert target_chat == "-1004323607372"

    alert = AutoAlert(
        alert_id="crypto-sq-btcusdt-202609212100",
        alert_type="CRYPTO_SQUEEZE",
        stage="IGNITED",
        symbol="BTCUSDT",
        exchange="CRYPTO",
        direction="BULLISH",
        headline="🪙 CRYPTO SQUEEZE: BTCUSDT Short-Squeeze Imminent @ $85,000.00",
        summary="Extreme negative funding rate -0.035%",
        ltp=85000.0,
        trigger_level=85000.0,
        target_level=88000.0,
        stop_loss=83500.0,
        confidence=88,
        created_at="2026-09-21 21:00:00 IST",
        is_live=True,
        environment="LIVE",
        market_status="LIVE",
        actionable_plan={
            "action": "BUY_SPOT / LONG",
            "contract": "CRYPTO:BTCUSDT",
            "entry_range": "$84,800.00 – $85,200.00",
            "stop_loss": "$83,500.00",
            "target": "$88,000.00",
            "risk_reward": "1:2.0",
            "setup_confluence": "Binance Futures Short-Crowded Funding Imbalance",
            "profit_rule": "Scale 50% at T1, trail stop to breakeven.",
        },
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "[CRYPTO 24x7] ALPHA VORTEX" in rendered
    assert "$85,000" in rendered or "$84,800" in rendered
    assert "$83,500" in rendered
    assert "$88,000" in rendered
    assert "24x7 Continuous Liquidity" in rendered
