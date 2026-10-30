"""
market/fyers_socket_patch.py
────────────────────────────
Institutional monkeypatch for fyers_apiv3 WebSocket SDK.

Root Cause Solved:
fyers_apiv3's FyersDataSocket, FyersOrderSocket, and FyersTbtSocket create internal
worker threads (ping_thread, message_thread, running_thread, infy_loop, and ws_thread)
without daemon=True. This causes Python runtime exit (threading._shutdown) to hang
indefinitely when tests, scripts, or REPL sessions finish.

This module patches the Thread references in fyers_apiv3 so that ALL threads
created by the Fyers WebSocket SDK are guaranteed to be daemon threads.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_PATCHED = False


class _AutoDaemonThread(threading.Thread):
    """Drop-in threading.Thread replacement that forces daemon=True."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["daemon"] = True
        super().__init__(*args, **kwargs)


class _ThreadingProxy:
    """Proxy object that routes Thread to _AutoDaemonThread while preserving threading module attrs."""

    Thread = _AutoDaemonThread

    def __getattr__(self, name: str) -> Any:
        return getattr(threading, name)


def patch_fyers_websocket_daemon_threads() -> None:
    """Ensure all threads spawned by fyers_apiv3 are daemon threads and shim pkg_resources with modern importlib."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        import sys

        # Institutional shim: fyers_apiv3 only uses pkg_resources to locate map.json:
        # resource_filename('fyers_apiv3.FyersWebsocket', 'map.json')
        # Providing a modern importlib.resources shim prevents setuptools.pkg_resources
        # from loading, scanning site-packages, and emitting deprecation warnings.
        if "pkg_resources" not in sys.modules:
            import importlib.resources
            import types

            shim = types.ModuleType("pkg_resources")
            shim.resource_filename = lambda pkg, res: str(
                importlib.resources.files(pkg).joinpath(res)
            )
            shim.declare_namespace = lambda ns: None
            sys.modules["pkg_resources"] = shim

        from fyers_apiv3.FyersWebsocket import data_ws, order_ws, tbt_ws

        proxy = _ThreadingProxy()
        for mod in (data_ws, order_ws, tbt_ws):
            mod.Thread = _AutoDaemonThread
            mod.threading = proxy

        # Patch FyersTbtSocket to fix official SDK bugs:
        # 1. SDK clobbers self.onopen = on_connect with self.onopen = on_open (where on_open defaults to None)
        # 2. SDK hardcodes self.background_flag = False which forces self.t.daemon = False
        # 3. SDK implements FyersTbtSocket as a singleton (_instance = None), preventing multi-socket pools
        # 4. SDK crashes in close_connection if running_thread is None
        tbt_ws.FyersTbtSocket.__new__ = lambda cls, *args, **kwargs: object.__new__(cls)

        _orig_tbt_init = tbt_ws.FyersTbtSocket.__init__

        def _patched_tbt_init(self, *args, **kwargs):
            cb = kwargs.get("on_open") or kwargs.get("on_connect")
            if cb:
                kwargs["on_open"] = cb
                kwargs["on_connect"] = cb
            _orig_tbt_init(self, *args, **kwargs)
            if cb:
                self.onopen = cb
            self.background_flag = True

        def _patched_tbt_close(self):
            ws_obj = getattr(self, "_FyersTbtSocket__ws_object", None)
            if ws_obj is not None:
                self.restart_flag = False
                try:
                    ws_obj.close()
                except Exception as e:
                    logger.debug(f"[FyersSocketPatch] ws_obj.close suppressed: {e}")
                setattr(self, "_FyersTbtSocket__ws_object", None)
                setattr(self, "_FyersTbtSocket__ws_run", None)
                for th_name in ("running_thread", "t", "ping_thread"):
                    th = getattr(self, th_name, None)
                    if th is not None:
                        try:
                            th.join(timeout=0.5)
                        except Exception as e:
                            logger.debug(f"[FyersSocketPatch] thread join suppressed: {e}")

        tbt_ws.FyersTbtSocket.__init__ = _patched_tbt_init
        tbt_ws.FyersTbtSocket.close_connection = _patched_tbt_close

        # 5. SDK crashes with KeyError in on_open/switchChannel if a channel is in _activeChannels but not yet in _symbols
        subs_cls = getattr(tbt_ws, "SubscriptionInfo", getattr(tbt_ws, "Subscription_info", None))
        if subs_cls is not None:

            def _safe_get_symbols(self, chanNo: Any):
                symbols = getattr(self, "_symbols", {})
                if chanNo in symbols:
                    return symbols[chanNo]
                if str(chanNo) in symbols:
                    return symbols[str(chanNo)]
                try:
                    int_k = int(chanNo)
                    if int_k in symbols:
                        return symbols[int_k]
                except (ValueError, TypeError) as e_cast:
                    logger.debug(
                        "[FyersSocketPatch] Failed casting chanNo to int for symbols: %s", e_cast
                    )
                return set()

            def _safe_get_mode(self, chanNo: Any):
                default_mode = getattr(tbt_ws.SubscriptionModes, "DEPTH", None)
                mode_info = getattr(self, "_modeInfo", {})
                if chanNo in mode_info:
                    return mode_info[chanNo]
                if str(chanNo) in mode_info:
                    return mode_info[str(chanNo)]
                try:
                    int_k = int(chanNo)
                    if int_k in mode_info:
                        return mode_info[int_k]
                except (ValueError, TypeError) as e_cast:
                    logger.debug(
                        "[FyersSocketPatch] Failed casting chanNo to int for mode_info: %s", e_cast
                    )
                return default_mode

            subs_cls.getSymbolsInfo = _safe_get_symbols
            subs_cls.getModeInfo = _safe_get_mode

        # 6. Stop infinite reconnect loops when SDK receives 403 Forbidden handshake rejections
        if hasattr(order_ws, "FyersOrderSocket") and hasattr(order_ws.FyersOrderSocket, "On_error"):
            _orig_order_error = order_ws.FyersOrderSocket.On_error

            def _patched_order_error(self, message: str) -> None:
                if "403" in str(message) or "forbidden" in str(message).lower():
                    self.restart_flag = False
                _orig_order_error(self, message)

            order_ws.FyersOrderSocket.On_error = _patched_order_error

        if hasattr(data_ws, "FyersDataSocket") and hasattr(data_ws.FyersDataSocket, "On_error"):
            _orig_data_error = data_ws.FyersDataSocket.On_error

            def _patched_data_error(self, message: str) -> None:
                if "403" in str(message) or "forbidden" in str(message).lower():
                    self.restart_flag = False
                _orig_data_error(self, message)

            data_ws.FyersDataSocket.On_error = _patched_data_error

        if hasattr(tbt_ws, "FyersTbtSocket") and hasattr(tbt_ws.FyersTbtSocket, "On_error"):
            _orig_tbt_error = tbt_ws.FyersTbtSocket.On_error

            def _patched_tbt_error(self, message: str) -> None:
                if "403" in str(message) or "forbidden" in str(message).lower():
                    self.restart_flag = False
                _orig_tbt_error(self, message)

            tbt_ws.FyersTbtSocket.On_error = _patched_tbt_error

        _PATCHED = True
        logger.debug(
            "[FyersSocketPatch] Patched fyers_apiv3 WebSocket SDK threads to daemon=True, fixed TbtSocket onopen, and added 403 halt."
        )
    except ImportError as e_suppressed:
        logger.debug(f"[market.fyers_socket_patch] Non-fatal exception suppressed: {e_suppressed}")
    except Exception as exc:
        logger.warning("[FyersSocketPatch] Failed to patch fyers_apiv3: %s", exc)


# Auto-apply on module import
patch_fyers_websocket_daemon_threads()
