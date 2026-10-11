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
    """Ensure all threads spawned by fyers_apiv3 are daemon threads."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        from fyers_apiv3.FyersWebsocket import data_ws, order_ws, tbt_ws

        proxy = _ThreadingProxy()
        for mod in (data_ws, order_ws, tbt_ws):
            mod.Thread = _AutoDaemonThread
            mod.threading = proxy

        _PATCHED = True
        logger.debug("[FyersSocketPatch] Patched fyers_apiv3 WebSocket SDK threads to daemon=True.")
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("[FyersSocketPatch] Failed to patch fyers_apiv3: %s", exc)


# Auto-apply on module import
patch_fyers_websocket_daemon_threads()
