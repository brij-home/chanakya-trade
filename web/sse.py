"""
web/sse.py
──────────
Server-Sent Events bus for real-time price and alert streaming.

Usage:
    from web.sse import event_bus

    event_bus.publish("price", {"symbol": "NIFTY", "ltp": 24500.0})
    event_bus.publish("alert", {"symbol": "INFY", "message": "RSI > 70"})

    # In FastAPI endpoint:
    async for chunk in event_bus.subscribe("price"):
        yield chunk
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator

logger = logging.getLogger("web.sse")


class SSEEventBus:
    """
    Simple pub/sub bus for SSE streams.

    Each channel (e.g. "price", "alert", "ticker") has a list of subscriber queues.
    Publishers push events; subscribers receive them via async generators.

    Max queue size: 100 events per subscriber (oldest dropped if full).
    Heartbeat: sends ": heartbeat\\n\\n" every 15s to keep connections alive.
    """

    HEARTBEAT_INTERVAL = 15  # seconds
    MAX_QUEUE_SIZE = 100

    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def _dispatch_to_queues(self, channel: str, data: dict) -> int:
        """Internal helper to push data to all subscriber queues for a channel."""
        queues = list(self._channels.get(channel, []))
        count = 0
        for q in queues:
            try:
                q.put_nowait(data)
                count += 1
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                    count += 1
                except Exception:
                    pass
            except Exception:
                pass
        if count > 0 or queues:
            logger.debug(f"[SSEEventBus] Dispatched {channel} event to {count}/{len(queues)} queues")
        return count

    async def publish(self, channel: str, data: dict) -> int:
        """Publish to all subscribers on channel. Returns subscriber count."""
        return self._dispatch_to_queues(channel, data)

    async def subscribe(self, channel: str) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings: 'data: {...}\\n\\n'"""
        q: asyncio.Queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._channels[channel].append(q)
        logger.info(f"[SSEEventBus] Subscriber connected to '{channel}' (total={len(self._channels[channel])})")

        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=self.HEARTBEAT_INTERVAL)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            try:
                self._channels[channel].remove(q)
                logger.info(f"[SSEEventBus] Subscriber disconnected from '{channel}' (remaining={len(self._channels[channel])})")
            except ValueError:
                pass

    def publish_sync(self, channel: str, data: dict) -> None:
        """Thread-safe publish from sync code (e.g. background polling threads)."""
        target_loop = getattr(self, "_main_loop", None)
        if target_loop and target_loop.is_running():
            try:
                target_loop.call_soon_threadsafe(self._dispatch_to_queues, channel, data)
                return
            except Exception as e:
                logger.warning(f"[SSEEventBus] call_soon_threadsafe error: {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self._dispatch_to_queues, channel, data)
        except RuntimeError:
            self._dispatch_to_queues(channel, data)


event_bus = SSEEventBus()  # module-level singleton

