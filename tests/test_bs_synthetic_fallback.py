"""
Unit tests for Black-Scholes synthetic option premium fallback in AutoAlertEngine.
Ensures in-flight guardian loops never go blind when option ticks drop.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine


def test_black_scholes_synthetic_fallback_when_quote_missing():
    engine = AutoAlertEngine()

    exp_date = date.today() + timedelta(days=2)
    yyyymmdd = exp_date.strftime("%Y%m%d")
    contract_sym = f"NSE:NIFTY{yyyymmdd}25000CE"

    alert = AutoAlert(
        alert_id="aa-test-bs-001-20261029",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        headline="Nifty Call Setup",
        summary="Testing synthetic BS fallback",
        ltp=150.0,
        trigger_level=120.0,
        target_level=200.0,
        stop_loss=90.0,
        exchange="NFO",
        contract_symbol=contract_sym,
        stage="TARGET_05_REACHED",
        is_live=True,
    )

    # Mock get_quote returning spot price for NIFTY, but MISSING contract_sym
    def mock_get_quote(symbols, **kwargs):
        res = {}
        for s in symbols:
            if "NIFTY" in s and "CE" not in s:
                mock_q = MagicMock()
                mock_q.last_price = 25100.0  # Spot is ITM by 100 pts
                res[s] = mock_q
        return res

    with patch("market.quotes.get_quote", side_effect=mock_get_quote):
        with patch("market.quotes.get_ltp", return_value=25100.0):
            quotes_batch = engine._batch_refresh_quotes([alert])

            assert contract_sym in quotes_batch, f"Contract {contract_sym} should be synthesized"
            price = quotes_batch[contract_sym]
            # Since Spot is 25100 and Strike is 25000 CE (ITM), price must be at least intrinsic (>= 100)
            assert price >= 100.0, f"Expected ITM call price >= 100, got {price}"


def test_real_quote_not_overwritten_by_synthetic():
    engine = AutoAlertEngine()

    contract_sym = "NSE:NIFTY2026110525000CE"
    alert = AutoAlert(
        alert_id="aa-test-bs-002-20261029",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        headline="Nifty Call Real Quote",
        summary="Testing real quote preservation",
        ltp=145.50,
        trigger_level=120.0,
        target_level=200.0,
        stop_loss=90.0,
        exchange="NFO",
        contract_symbol=contract_sym,
        stage="TARGET_05_REACHED",
        is_live=True,
    )

    # Real quote exists
    def mock_get_quote(symbols, **kwargs):
        res = {}
        for s in symbols:
            mock_q = MagicMock()
            if "CE" in s:
                mock_q.last_price = 145.50
            else:
                mock_q.last_price = 25050.0
            res[s] = mock_q
        return res

    with patch("market.quotes.get_quote", side_effect=mock_get_quote):
        quotes_batch = engine._batch_refresh_quotes([alert])
        assert quotes_batch[contract_sym] == 145.50


def test_subsecond_spot_tick_evaluates_synthetic_option_milestone():
    """Verify sub-second Spot ticks update option premium and evaluate milestones without spot price leakage."""
    engine = AutoAlertEngine()

    exp_date = date.today() + timedelta(days=2)
    yyyymmdd = exp_date.strftime("%Y%m%d")
    contract_sym = f"NSE:NIFTY{yyyymmdd}25000CE"

    alert = AutoAlert(
        alert_id="aa-test-bs-spot-003-20261029",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        headline="Nifty Call Spot Driven",
        summary="Testing sub-second spot tick synthetic evaluation",
        ltp=150.0,
        trigger_level=120.0,
        target_level=200.0,
        stop_loss=90.0,
        exchange="NFO",
        contract_symbol=contract_sym,
        stage="TRIGGERED",
        is_live=True,
    )
    alert.option_premium = 150.0
    engine._alerts.append(alert)

    # Incoming live tick is for the UNDERLYING SPOT (NIFTY), surging to 25300
    spot_tick = {
        "symbol": "NSE:NIFTY50-INDEX",
        "ltp": 25300.0,
        "timestamp": 1730200000.0,
    }

    with patch.object(engine, "_save"):
        with patch.object(engine, "_dispatch"):
            engine._on_domestic_tick(spot_tick)

    # 1. Underlying spot should be updated
    assert alert.underlying_spot == 25300.0
    # 2. Option premium should be synthesized from spot (ITM by 300 pts, so >= 300)
    assert alert.option_premium >= 300.0
    # 3. No spot price leak: alert.ltp must be the option premium, NOT 25300
    assert alert.ltp == alert.option_premium
    assert alert.ltp < 1000.0
