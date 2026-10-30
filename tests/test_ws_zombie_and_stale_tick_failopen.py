"""
Deterministic unit & integration regression tests for WebSocket zombie detection,
stale tick rejection, in-flight fail-open REST fallback, and options grid expiry accuracy.
"""

from datetime import datetime
from unittest.mock import patch
import time

from market.websocket import Tick, WebSocketManager
from market.quotes import _ws_quotes, Quote
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from market.ws_subscription_manager import get_active_index_options_grid


def test_ws_quotes_rejects_stale_ticks_during_market_hours():
    """Verify _ws_quotes does not return a stale tick (>30s old) during market hours."""
    with (
        patch("market.websocket.ws_manager") as mock_ws_mgr,
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
        patch("market.calendar.is_market_open", return_value=True),
    ):
        mock_ws_mgr.connected = True

        # When max_age_seconds=30.0 is passed, get_tick returns None for stale tick
        def fake_get_tick(inst, max_age_seconds=None):
            if max_age_seconds is not None:
                return None  # Stale!
            return Tick(symbol="BFO:SENSEX26OCT73800CE", ltp=210.65, received_at=time.time() - 3600)

        mock_ws_mgr.get_tick.side_effect = fake_get_tick

        quotes = _ws_quotes(["BFO:SENSEX26OCT73800CE"], correlation_id="test-corr")

        # Stale tick should be rejected and not included in quotes
        assert "BFO:SENSEX26OCT73800CE" not in quotes
        # Missing symbol must be re-subscribed
        mock_ws_mgr.subscribe.assert_called_with(["BFO:SENSEX26OCT73800CE"])


def test_ws_quotes_accepts_fresh_ticks_during_market_hours():
    """Verify _ws_quotes accepts ticks when fresh (<=30s old)."""
    with (
        patch("market.websocket.ws_manager") as mock_ws_mgr,
        patch("market.quotes.get_data_broker_key", return_value="fyers"),
        patch("market.calendar.is_market_open", return_value=True),
    ):
        mock_ws_mgr.connected = True
        fresh_tick = Tick(
            symbol="BFO:SENSEX26OCT73800CE",
            ltp=284.10,
            received_at=time.time() - 2.0,
            timestamp=time.time() - 2.0,
        )
        mock_ws_mgr.get_tick.return_value = fresh_tick

        quotes = _ws_quotes(["BFO:SENSEX26OCT73800CE"], correlation_id="test-corr")
        assert "BFO:SENSEX26OCT73800CE" in quotes
        assert quotes["BFO:SENSEX26OCT73800CE"].last_price == 284.10


def test_websocket_watchdog_detects_zombie_and_disconnects():
    """Verify watchdog detects silence > 30s during market hours and triggers disconnect/reconnect."""
    mgr = WebSocketManager()
    mgr._connected = True
    mgr._access_token = "valid_token"
    mgr._subscribed = {"NSE:NIFTY50-INDEX"}
    mgr._last_packet_at = time.time() - 45.0  # 45 seconds of silence

    with (
        patch("market.calendar.is_market_open", return_value=True),
        patch.object(mgr, "_schedule_proactive_reconnect") as mock_reconn,
    ):
        # Run health check
        healthy = mgr._check_connection_health()

        # Must flag zombie connection
        assert healthy is False
        assert mgr.connected is False
        mock_reconn.assert_called_once_with(delay_sec=1.0)


def test_batch_refresh_quotes_failopen_for_active_inflight_trades():
    """Verify _batch_refresh_quotes triggers urgent REST fallback when active in-flight trade is missing from stream."""
    engine = AutoAlertEngine()

    active_alert = AutoAlert(
        alert_id="aa-index-contagion-sensex-bullish-20261029",
        symbol="SENSEX",
        alert_type="INDEX_CONTAGION",
        direction="BULLISH",
        headline="Sensex Bullish Breakout",
        summary="Target 1 hit, trailing runner active",
        ltp=210.65,
        trigger_level=167.15,
        target_level=245.90,
        stop_loss=122.15,
        exchange="BFO",
        stage="TARGET_05_REACHED",  # Active in-flight stage!
        contract_symbol="BSE:SENSEX26OCT73800CE",
        is_live=True,
    )

    untriggered_radar = AutoAlert(
        alert_id="aa-radar-reliance-stalk-20261029",
        symbol="RELIANCE",
        alert_type="VOL_COMPRESSION",
        direction="BULLISH",
        headline="Reliance Stalk",
        summary="Awaiting ignition above trigger",
        ltp=1250.0,
        trigger_level=1260.0,
        target_level=1280.0,
        stop_loss=1240.0,
        exchange="NSE",
        stage="STALK",  # Radar stage, NOT active in-flight
        is_live=True,
    )

    # When get_quote is called with ws_only=True, simulate that active_alert is missing from WebSocket
    def fake_get_quote(
        sym_list, priority="NORMAL", category=None, ws_only=False, rate_gate_acquired=False
    ):
        if ws_only:
            # WebSocket stream is zombie, returns empty
            return {}
        # REST fallback returns live quote
        res = {}
        for s in sym_list:
            res[s] = Quote(symbol=s, last_price=284.10)
        return res

    with patch("market.quotes.get_quote", side_effect=fake_get_quote):
        quote_map = engine._batch_refresh_quotes(
            [active_alert, untriggered_radar], priority="URGENT", ws_only=True
        )

        # Active trade must have its price resolved via REST fallback
        assert "BSE:SENSEX26OCT73800CE" in quote_map
        assert quote_map["BSE:SENSEX26OCT73800CE"] == 284.10

        # Radar symbol (STALK) was not called via REST fallback to save API quota
        assert "NSE:RELIANCE" not in quote_map


def test_options_grid_expiry_accuracy_near_month_end():
    """Verify get_active_index_options_grid accurately includes current month contracts on day 29 before expiry."""
    # Mock datetime to 2026-10-29 13:30 IST
    mock_now = datetime(2026, 10, 29, 13, 30)

    with (
        patch("market.ws_subscription_manager.datetime") as mock_dt,
        patch("market.quotes.get_ltp", return_value=81500.0),
    ):
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        grid = get_active_index_options_grid(num_strikes_per_side=4)

        # Grid must contain BSE SENSEX 26OCT contracts (NOT just 26NOV)
        sensex_oct_contracts = [c for c in grid if "SENSEX26OCT" in c]
        assert len(sensex_oct_contracts) > 0, (
            "Current month 26OCT contracts must be included in options grid!"
        )

        # Must include the ATM strike (81500 CE)
        assert any("81500CE" in c for c in sensex_oct_contracts)
