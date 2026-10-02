"""
market/fyers_order_stream.py
────────────────────────────
Real-time Order, Trade, and Position stream via Fyers Order WebSocket (order_ws).

Features:
  - Real-time order lifecycle push notifications (Placed, Filled, Partial, Rejected, Cancelled)
  - Instant trade fill updates without REST polling
  - Position change broadcasts
  - Direct integration with web SSE event bus and order lifecycle state machine
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("market.fyers_order_stream")


class FyersOrderStreamManager:
    """Manages real-time order execution, trade fills, and position streaming."""

    def __init__(self) -> None:
        self._ws = None
        self._connected = False
        self._access_token = ""
        self._callbacks_orders: list[Callable] = []
        self._callbacks_trades: list[Callable] = []
        self._callbacks_positions: list[Callable] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, access_token: str, app_id: str = "") -> None:
        """Start the Fyers Order WebSocket in a background daemon thread."""
        if self._connected:
            return

        # Fyers Order WebSocket expects access_token in the format f"{app_id}:{token}"
        if app_id and ":" not in access_token:
            self._access_token = f"{app_id}:{access_token}"
        else:
            self._access_token = access_token

        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Gracefully disconnect the Order WebSocket without blocking."""
        ws_to_close = self._ws
        self._connected = False
        self._ws = None

        if ws_to_close:
            def _close():
                try:
                    setattr(ws_to_close, "restart_flag", False)
                    ws_obj = getattr(ws_to_close, "_FyersOrderSocket__ws_object", None)
                    if ws_obj and hasattr(ws_obj, "close"):
                        try:
                            ws_obj.close()
                        except Exception:
                            pass
                except Exception:
                    pass

            t = threading.Thread(target=_close, daemon=True)
            t.start()
            t.join(timeout=timeout)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def on_order(self, callback: Callable) -> None:
        """Register a callback for order updates."""
        self._callbacks_orders.append(callback)

    def on_trade(self, callback: Callable) -> None:
        """Register a callback for trade executions."""
        self._callbacks_trades.append(callback)

    def on_position(self, callback: Callable) -> None:
        """Register a callback for position changes."""
        self._callbacks_positions.append(callback)

    # ── Private ──────────────────────────────────────────────

    def _connect(self) -> None:
        try:
            from fyers_apiv3.FyersWebsocket import order_ws

            self._ws = order_ws.FyersOrderSocket(
                access_token=self._access_token,
                write_to_file=True,
                log_path="",
                on_orders=self._handle_orders,
                on_trades=self._handle_trades,
                on_positions=self._handle_positions,
                on_general=self._handle_general,
                on_connect=self._handle_connect,
                on_close=self._handle_close,
                on_error=self._handle_error,
                reconnect=True,
            )
            # Ensure background thread is daemon
            setattr(self._ws, "background_flag", True)
            self._ws.connect()
        except ImportError:
            logger.warning("fyers-apiv3 order_ws unavailable")
        except Exception as e:
            logger.debug(f"Fyers order websocket connection failed: {e}")

    def _handle_connect(self) -> None:
        self._connected = True
        logger.info("Fyers Order WebSocket: connected")
        try:
            if self._ws:
                self._ws.subscribe(data_type="OnOrders,OnTrades,OnPositions,OnGeneral")
                logger.info("Fyers Order WebSocket: subscribed to OnOrders, OnTrades, OnPositions, OnGeneral")
        except Exception as e:
            logger.warning("Fyers Order WebSocket subscription failed: %s", e)

    def _handle_close(self, *args, **kwargs) -> None:
        self._connected = False
        logger.info("Fyers Order WebSocket: disconnected")

    def _handle_error(self, message) -> None:
        logger.debug(f"Fyers Order WebSocket error: {message}")

    def _handle_orders(self, message) -> None:
        """Process incoming order lifecycle events."""
        try:
            logger.info("Fyers Order Update: %s", message)
            # Broadcast to SSE event bus
            try:
                from web.sse import event_bus

                event_bus.publish_sync(
                    "orders",
                    {
                        "type": "order_update",
                        "provider": "fyers",
                        "data": message,
                    },
                )
            except Exception:
                pass

            for cb in self._callbacks_orders:
                try:
                    cb(message)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Order event parse error: {e}")

    def _handle_trades(self, message) -> None:
        """Process incoming trade fill executions."""
        try:
            logger.info("Fyers Trade Fill: %s", message)
            try:
                from web.sse import event_bus

                event_bus.publish_sync(
                    "orders",
                    {
                        "type": "trade_fill",
                        "provider": "fyers",
                        "data": message,
                    },
                )
            except Exception:
                pass

            for cb in self._callbacks_trades:
                try:
                    cb(message)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Trade event parse error: {e}")

    def _handle_positions(self, message) -> None:
        """Process incoming position adjustments."""
        try:
            try:
                from web.sse import event_bus

                event_bus.publish_sync(
                    "portfolio",
                    {
                        "type": "position_update",
                        "provider": "fyers",
                        "data": message,
                    },
                )
            except Exception:
                pass

            for cb in self._callbacks_positions:
                try:
                    cb(message)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Position event parse error: {e}")

    def _handle_general(self, message) -> None:
        logger.debug(f"Fyers General Event: {message}")


# Singleton instance
fyers_order_stream = FyersOrderStreamManager()
