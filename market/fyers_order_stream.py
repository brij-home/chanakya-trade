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
        self._running = False
        self._access_token = ""
        self._callbacks_orders: list[Callable] = []
        self._callbacks_trades: list[Callable] = []
        self._callbacks_positions: list[Callable] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._reconnect_lock = threading.Lock()
        self._is_reconnecting = False
        self._reconnect_thread: Optional[threading.Thread] = None
        self._last_packet_at: float = 0.0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, access_token: str, app_id: str = "") -> None:
        """Start the Fyers Order WebSocket in a background daemon thread."""
        target_token = (
            f"{app_id}:{access_token}" if app_id and ":" not in access_token else access_token
        )
        if self._connected and self._access_token == target_token:
            return

        if self._connected and self._access_token != target_token:
            logger.info("[OrderStream] Restarting order socket with renewed access token")
            self.stop()

        self._running = True
        self._access_token = target_token
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def update_token(self, access_token: str, app_id: str = "") -> None:
        """Update access token and reconnect if changed."""
        self.start(access_token=access_token, app_id=app_id)

    def stop(self, timeout: float = 1.0) -> None:
        """Gracefully disconnect the Order WebSocket without blocking."""
        self._running = False
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
                        except Exception as e_suppressed:
                            logger.debug(
                                f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                            )
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                    )

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

    def _schedule_proactive_reconnect(self, delay_sec: Optional[float] = None) -> None:
        """Schedules single-flight thread-safe reconnect with backoff."""
        with self._reconnect_lock:
            if self._is_reconnecting or (
                self._reconnect_thread is not None and self._reconnect_thread.is_alive()
            ):
                logger.debug("[OrderStream] Reconnect worker already in flight; skipping.")
                return
            self._is_reconnecting = True

            effective_delay = delay_sec if delay_sec is not None else 3.0

            def _reconnect_worker():
                import time

                try:
                    time.sleep(effective_delay)
                    if not getattr(self, "_running", False) or getattr(self, "_connected", False):
                        return
                    try:
                        from market.calendar import is_market_open

                        if not is_market_open("NSE"):
                            logger.info(
                                "[OrderStream] Off-market session detected. Pausing order stream reconnect."
                            )
                            return
                    except Exception as e_suppressed:
                        logger.debug(f"[OrderStream] Market open check non-fatal: {e_suppressed}")

                    logger.info("[OrderStream] Executing proactive order socket reconnect...")
                    self._connect()
                except Exception as e_recon:
                    logger.warning(f"[OrderStream] Proactive reconnect failed: {e_recon}")
                finally:
                    with self._reconnect_lock:
                        self._is_reconnecting = False

            self._reconnect_thread = threading.Thread(
                target=_reconnect_worker, daemon=True, name="FyersOrderReconnect"
            )
            self._reconnect_thread.start()

    def _check_connection_health(self) -> bool:
        """Evaluates order socket connection health. Triggers reconnect if zombie."""
        if not self._connected or not self._access_token or not self._running:
            return True
        import time

        now = time.time()
        silence_sec = now - self._last_packet_at if self._last_packet_at > 0 else 0.0
        # If active market and silence > 180s (order stream has lower frequency than quote stream)
        if self._last_packet_at > 0 and silence_sec > 300.0:
            try:
                from market.calendar import is_market_open

                if not is_market_open("NSE"):
                    return True
            except Exception as e_suppressed:
                logger.debug(f"[OrderStream] Health check market status non-fatal: {e_suppressed}")
            logger.warning(
                f"[OrderStream] 🚨 Order WebSocket silence detected ({silence_sec:.1f}s). Proactively reconnecting."
            )
            self._connected = False
            self._schedule_proactive_reconnect(delay_sec=1.0)
            return False
        return True

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
                reconnect=False,  # Autonomous control: ensures on_close triggers our self-healing reconnect
            )
            # Ensure background thread is daemon
            setattr(self._ws, "background_flag", True)
            self._ws.connect()
        except ImportError:
            logger.warning("fyers-apiv3 order_ws unavailable")
        except Exception as e:
            logger.debug(f"Fyers order websocket connection failed: {e}")
            if self._running:
                self._schedule_proactive_reconnect(delay_sec=5.0)

    def _handle_connect(self) -> None:
        import time

        self._connected = True
        self._last_packet_at = time.time()
        logger.info("Fyers Order WebSocket: connected")
        try:
            if self._ws:
                self._ws.subscribe(data_type="OnOrders,OnTrades,OnPositions,OnGeneral")
                logger.info(
                    "Fyers Order WebSocket: subscribed to OnOrders, OnTrades, OnPositions, OnGeneral"
                )
        except Exception as e:
            logger.warning("Fyers Order WebSocket subscription failed: %s", e)

    def _handle_close(self, *args, **kwargs) -> None:
        self._connected = False
        logger.info("Fyers Order WebSocket: disconnected")
        if getattr(self, "_running", False) and getattr(self, "_access_token", ""):
            self._schedule_proactive_reconnect(delay_sec=2.0)

    def _handle_error(self, message) -> None:
        logger.debug(f"Fyers Order WebSocket error: {message}")
        msg_str = str(message)
        if "403" in msg_str or "forbidden" in msg_str.lower() or "unauthorized" in msg_str.lower():
            logger.warning(
                "[FyersOrderStream] 403 Forbidden received. Halting reconnect loop and notifying broker."
            )
            self.stop()
            try:
                from brokers.session import get_data_broker

                b = get_data_broker()
                if hasattr(b, "_handle_auth_failure"):
                    b._handle_auth_failure()
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_order_stream] Auth failure notification suppressed: {e_suppressed}"
                )

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
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                )

            for cb in self._callbacks_orders:
                try:
                    cb(message)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                    )
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
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                )

            try:
                from brokers.session import get_execution_broker

                b = get_execution_broker()
                if hasattr(b, "invalidate_portfolio_caches"):
                    b.invalidate_portfolio_caches()
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_order_stream] Cache invalidation non-fatal: {e_suppressed}"
                )

            for cb in self._callbacks_trades:
                try:
                    cb(message)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                    )
        except Exception as e:
            logger.debug(f"Trade event parse error: {e}")

    def _handle_positions(self, message) -> None:
        """Process incoming position adjustments."""
        try:
            try:
                from brokers.session import get_execution_broker

                b = get_execution_broker()
                if hasattr(b, "invalidate_portfolio_caches"):
                    b.invalidate_portfolio_caches()
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_order_stream] Cache invalidation non-fatal: {e_suppressed}"
                )

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
            except Exception as e_suppressed:
                logger.debug(
                    f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                )

            for cb in self._callbacks_positions:
                try:
                    cb(message)
                except Exception as e_suppressed:
                    logger.debug(
                        f"[market.fyers_order_stream] Non-fatal exception suppressed: {e_suppressed}"
                    )
        except Exception as e:
            logger.debug(f"Position event parse error: {e}")

    def _handle_general(self, message) -> None:
        logger.debug(f"Fyers General Event: {message}")


# Singleton instance
fyers_order_stream = FyersOrderStreamManager()
