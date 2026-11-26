"""
Unit and invariant test suite for:
1. Microstructure Liquidity & Bid-Ask Spread Expansion Gate (Gate 11)
2. SEBI Physical Settlement & Delivery Margin Risk Sentinel (Gate 12)
3. Live Tick Peak MFE / MAE Excursion Tracking in Alert Evaluator
4. Transactional Outbox Worker Channel Parameter Forwarding
"""

from unittest.mock import patch
from datetime import datetime

from engine.pretrade import (
    _gate_bid_ask_spread,
    _gate_sebi_physical_settlement,
)


# ==============================================================================
# Gate 11: Real-Time Bid-Ask Spread Expansion Gate Tests
# ==============================================================================


def test_spread_gate_options_market_order_blocked_on_spread_expansion():
    """Option MARKET order into blown-out bid-ask spread must be blocked."""
    res = _gate_bid_ask_spread(
        symbol="NIFTY26NOV24000CE",
        order_type="MARKET",
        side="BUY",
        ltp=100.0,
        best_bid=95.0,
        best_ask=105.0,
        segment="OPT",
        tick_size=0.05,
    )
    assert res.passed is False
    assert res.gate == "bid_ask_spread"
    assert "Market orders prohibited during spread expansion shock" in res.reason
    assert res.details["spread"] == 10.0


def test_spread_gate_options_limit_order_allowed_on_wide_spread():
    """Option LIMIT order should NOT be blocked by wide spread (trader names their price)."""
    res = _gate_bid_ask_spread(
        symbol="NIFTY26NOV24000CE",
        order_type="LIMIT",
        side="BUY",
        ltp=100.0,
        best_bid=95.0,
        best_ask=105.0,
        segment="OPT",
        tick_size=0.05,
    )
    assert res.passed is True
    assert res.gate == "bid_ask_spread"


def test_spread_gate_options_tight_market_order_allowed():
    """Option MARKET order with tight inside spread (<= 6 ticks) passes cleanly."""
    res = _gate_bid_ask_spread(
        symbol="NIFTY26NOV24000CE",
        order_type="MARKET",
        side="BUY",
        ltp=100.0,
        best_bid=100.0,
        best_ask=100.15,
        segment="OPT",
        tick_size=0.05,
    )
    assert res.passed is True


def test_spread_gate_equity_market_order_blocked_on_illiquidity():
    """Cash equity MARKET order with spread > 0.40% and > 5 ticks is blocked."""
    res = _gate_bid_ask_spread(
        symbol="RELIANCE",
        order_type="MARKET",
        side="BUY",
        ltp=2500.0,
        best_bid=2480.0,
        best_ask=2520.0,
        segment="EQ",
        tick_size=0.05,
    )
    assert res.passed is False
    assert "Microstructure Liquidity Gate" in res.reason
    assert "Market orders prohibited during wide spread shock" in res.reason


def test_spread_gate_equity_tight_spread_allowed():
    """Cash equity MARKET order with normal tight spread (<= 0.40%) passes."""
    res = _gate_bid_ask_spread(
        symbol="RELIANCE",
        order_type="MARKET",
        side="BUY",
        ltp=2500.0,
        best_bid=2499.75,
        best_ask=2500.00,
        segment="EQ",
        tick_size=0.05,
    )
    assert res.passed is True


def test_spread_gate_crossed_book_anomaly_halts_execution():
    """Crossed book anomaly (Bid > Ask) halts execution immediately."""
    res = _gate_bid_ask_spread(
        symbol="INFY",
        order_type="LIMIT",
        side="BUY",
        ltp=1500.0,
        best_bid=1505.0,
        best_ask=1500.0,
        segment="EQ",
    )
    assert res.passed is False
    assert "Crossed order book detected" in res.reason


# ==============================================================================
# Gate 12: SEBI Physical Settlement & Delivery Margin Risk Tests
# ==============================================================================


def test_sebi_physical_settlement_index_option_exempt():
    """Index derivatives (NIFTY/BANKNIFTY) are cash-settled and exempt from physical delivery rules."""
    res, warnings = _gate_sebi_physical_settlement(
        symbol="NIFTY26NOV24000CE",
        segment="OPT",
        quantity=25,
        price=100.0,
        available_cash=50000.0,
        dte=1,
    )
    assert res.passed is True
    assert len(warnings) == 0


def test_sebi_physical_settlement_far_expiry_stock_option_exempt():
    """Stock options with DTE > 4 are outside the physical delivery window."""
    res, warnings = _gate_sebi_physical_settlement(
        symbol="RELIANCE26DEC2500CE",
        segment="OPT",
        quantity=250,
        price=50.0,
        available_cash=50000.0,
        dte=15,
    )
    assert res.passed is True
    assert len(warnings) == 0


def test_sebi_physical_settlement_stock_option_near_expiry_warning_or_block():
    """Stock option with DTE <= 4 triggers delivery margin check."""
    # When available capital is severely inadequate for full physical delivery
    res, warnings = _gate_sebi_physical_settlement(
        symbol="RELIANCE26NOV2500CE",
        segment="OPT",
        quantity=250,
        price=50.0,
        available_cash=5000.0,  # Far below contract delivery margin
        dte=2,
    )
    # Depending on check_sebi_physical_settlement_risk output, it either blocks or records warning
    assert res.passed is False or len(warnings) > 0


# ==============================================================================
# Live Excursion Tracking (peak_mfe_r / peak_mae_r) Tests
# ==============================================================================


def test_alert_evaluator_updates_peak_mfe_and_mae():
    """evaluate_alert_targets_and_trailing must record peak_mfe_r and peak_mae_r on live ticks."""
    from engine.alert_evaluator import evaluate_alert_targets_and_trailing
    from engine.auto_alert_engine import AutoAlert

    alert = AutoAlert(
        alert_id="aa-orb_breakout-TCS-20261124",
        alert_type="orb_breakout",
        stage="IGNITED",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Breakout",
        summary="Testing MFE/MAE",
        ltp=3500.0,
        trigger_level=3500.0,
        target_level=3600.0,
        stop_loss=3450.0,  # 1R = 50.0
        created_at=datetime.now().isoformat(),
    )

    # 1. Tick moves to +1.5R (3575.0)
    evaluate_alert_targets_and_trailing(alert, current_ltp=3575.0)
    assert getattr(alert, "peak_mfe_r", 0.0) >= 1.5

    # 2. Tick pulls back to -0.4R (3480.0)
    evaluate_alert_targets_and_trailing(alert, current_ltp=3480.0)
    assert getattr(alert, "peak_mae_r", 0.0) >= 0.4
    # MFE must be preserved at peak
    assert getattr(alert, "peak_mfe_r", 0.0) >= 1.5


# ==============================================================================
# Outbox Worker Forwarding Tests
# ==============================================================================


def test_outbox_worker_forwards_signal_threading_parameters():
    """OutboxWorker.dispatch_channel_entry must forward signal_id, is_update, etc. to send_push."""
    from engine.outbox_worker import OutboxWorker

    worker = OutboxWorker()

    payload = {
        "text": "<b>NIFTY 24000 CE</b>",
        "signal_id": "SIG_NIFTY_24000CE_20261124",
        "is_update": True,
        "reply_to_message_id": 12345,
        "disable_notification": True,
        "chat_id": "12345678",
    }
    entry = {
        "channel": "TELEGRAM",
        "payload": payload,
    }

    with patch("bot.telegram_bot.send_push", return_value=True) as mock_send:
        res = worker.dispatch_channel_entry(entry)
        assert res is True
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs.get("signal_id") == "SIG_NIFTY_24000CE_20261124"
        assert kwargs.get("is_update") is True
        assert kwargs.get("reply_to_message_id") == 12345
        assert kwargs.get("disable_notification") is True
