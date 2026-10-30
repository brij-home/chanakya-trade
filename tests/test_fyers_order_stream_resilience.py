"""
Unit tests for FyersOrderStreamManager reconnection lifecycle,
silence health check, and autonomous reconnect control.
"""

from unittest.mock import MagicMock, patch
import time

from market.fyers_order_stream import FyersOrderStreamManager


def test_order_stream_connect_disables_sdk_reconnect():
    """Verify that FyersOrderStreamManager forces reconnect=False on FyersOrderSocket."""
    mgr = FyersOrderStreamManager()
    mgr._access_token = "TEST_APP:TEST_TOKEN"
    mgr._running = True

    mock_ws_cls = MagicMock()
    mock_instance = MagicMock()
    mock_ws_cls.return_value = mock_instance
    mock_order_ws_mod = MagicMock(FyersOrderSocket=mock_ws_cls)
    mock_fyers_ws = MagicMock(order_ws=mock_order_ws_mod)
    mock_fyers_pkg = MagicMock(FyersWebsocket=mock_fyers_ws)

    with patch.dict(
        "sys.modules",
        {
            "fyers_apiv3": mock_fyers_pkg,
            "fyers_apiv3.FyersWebsocket": mock_fyers_ws,
            "fyers_apiv3.FyersWebsocket.order_ws": mock_order_ws_mod,
        },
    ):
        mgr._connect()

        # Must pass reconnect=False to avoid the Fyers SDK silent abandonment bug
        mock_ws_cls.assert_called_once()
        _, kwargs = mock_ws_cls.call_args
        assert kwargs.get("reconnect") is False
        mock_instance.connect.assert_called_once()


def test_order_stream_handle_close_triggers_reconnect():
    """Verify that _handle_close schedules autonomous reconnection when running."""
    mgr = FyersOrderStreamManager()
    mgr._access_token = "TEST_APP:TEST_TOKEN"
    mgr._running = True
    mgr._connected = True

    with patch.object(mgr, "_schedule_proactive_reconnect") as mock_reconn:
        mgr._handle_close("Connection closed")

        assert mgr.is_connected is False
        mock_reconn.assert_called_once_with(delay_sec=2.0)


def test_order_stream_health_check_detects_silence():
    """Verify that prolonged silence (>300s) during market hours triggers reconnect."""
    mgr = FyersOrderStreamManager()
    mgr._access_token = "TEST_APP:TEST_TOKEN"
    mgr._running = True
    mgr._connected = True
    mgr._last_packet_at = time.time() - 350.0  # 350s of silence

    with (
        patch("market.calendar.is_market_open", return_value=True),
        patch.object(mgr, "_schedule_proactive_reconnect") as mock_reconn,
    ):
        healthy = mgr._check_connection_health()

        assert healthy is False
        assert mgr.is_connected is False
        mock_reconn.assert_called_once_with(delay_sec=1.0)
