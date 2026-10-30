import threading
import time
from unittest.mock import MagicMock, patch

from market.websocket import WebSocketManager
from market.fyers_tbt_manager import FyersTbtManager


def test_websocket_reconnect_single_flight():
    """Verify multiple rapid _on_close calls trigger at most one reconnect thread."""
    mgr = WebSocketManager()
    mgr._running = True
    mgr._access_token = "mock_token"

    with (
        patch.object(mgr, "_connect") as mock_connect,
        patch("market.calendar.is_market_open", return_value=True),
    ):
        # Fire _on_close rapidly 50 times
        for _ in range(50):
            mgr._on_close()

        # Exactly one reconnect thread should be running or active
        assert mgr._is_reconnecting is True
        assert mgr._reconnect_thread is not None
        assert mgr._reconnect_thread.is_alive()

        # Let the worker finish
        mgr._reconnect_thread.join(timeout=4.0)
        assert mgr._is_reconnecting is False
        assert mock_connect.call_count == 1


def test_websocket_token_refresh_single_flight():
    """Verify multiple rapid token expiry errors trigger at most one refresh thread."""
    mgr = WebSocketManager()

    mock_broker = MagicMock()
    mock_broker._access_token = "fresh_token_123"
    mock_broker._app_id = "app_123"

    with (
        patch("brokers.session.get_data_broker", return_value=mock_broker),
        patch.object(mgr, "start", side_effect=lambda **kw: time.sleep(0.2)) as mock_start,
    ):
        # Fire _on_error rapidly 20 times with token expired
        for _ in range(20):
            mgr._on_error({"code": -99, "message": "Token is expired"})

        assert mgr._refreshing_token is True
        assert mgr._token_refresh_thread is not None
        assert mgr._token_refresh_thread.is_alive()

        # Wait for thread to finish
        mgr._token_refresh_thread.join(timeout=3.0)
        assert mgr._refreshing_token is False
        assert mock_start.call_count == 1


def test_tbt_scout_promotion_no_thread_leak():
    """Verify promoting scouts updates _scout_ttl without spawning background threads."""
    threads_before = threading.active_count()

    tbt = FyersTbtManager()
    with (
        patch(
            "market.fyers_tbt_manager.resolve_tradable_tbt_symbol", return_value="NSE:RELIANCE-EQ"
        ),
        patch("market.fyers_tbt_manager.is_tbt_eligible_symbol", return_value=True),
        patch.object(tbt, "sync_subscriptions"),
    ):
        # Promote 25 scouts using both sample_symbol and promote_jit_scout
        for i in range(25):
            tbt.sample_symbol(f"STOCK{i}", duration_sec=60.0)
            tbt.promote_jit_scout(f"STOCK{i}", duration_sec=60.0)

        # No new OS threads should have been spawned
        threads_after = threading.active_count()
        assert threads_after == threads_before

        # All 25 should have their custom TTL recorded
        assert "NSE:RELIANCE-EQ" in tbt._scout_ttl
        assert tbt._scout_ttl["NSE:RELIANCE-EQ"] == 60.0
