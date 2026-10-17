"""
tests/test_websocket_dispatcher.py
──────────────────────────────────
Unit tests verifying decoupled asynchronous dispatch queue in WebSocketManager.
"""

from __future__ import annotations

import queue
import time

from market.websocket import WebSocketManager, Tick


def test_websocket_dispatcher_async_fanout():
    mgr = WebSocketManager()
    received = []

    def on_tick(tick: Tick):
        received.append(tick)

    mgr.on_tick(on_tick)

    # Ingest 5 ticks
    for i in range(5):
        t = Tick(
            symbol=f"NSE:SYM{i}-EQ",
            ltp=100.0 + i,
            volume=1000 * i,
            timestamp=time.time(),
        )
        mgr._dispatch_queue.put_nowait(t)

    # Wait briefly for worker thread to dispatch
    for _ in range(20):
        if len(received) == 5:
            break
        time.sleep(0.05)

    assert len(received) == 5
    assert received[0].symbol == "NSE:SYM0-EQ"
    assert received[-1].symbol == "NSE:SYM4-EQ"

    # Stop dispatcher
    mgr.stop(timeout=0.5)


def test_websocket_dispatcher_backpressure_drop_oldest():
    mgr = WebSocketManager()
    # Create small queue for backpressure test
    mgr._dispatch_queue = queue.Queue(maxsize=3)

    t1 = Tick(symbol="T1", ltp=10.0)
    t2 = Tick(symbol="T2", ltp=20.0)
    t3 = Tick(symbol="T3", ltp=30.0)
    t4 = Tick(symbol="T4", ltp=40.0)

    # Put 3 items to fill queue
    mgr._dispatch_queue.put_nowait(t1)
    mgr._dispatch_queue.put_nowait(t2)
    mgr._dispatch_queue.put_nowait(t3)
    assert mgr._dispatch_queue.full()

    # Simulate _on_message load shedding
    try:
        mgr._dispatch_queue.put_nowait(t4)
    except queue.Full:
        _ = mgr._dispatch_queue.get_nowait()
        mgr._dispatch_queue.put_nowait(t4)

    # Queue should contain t2, t3, t4 (t1 dropped)
    remaining = []
    while not mgr._dispatch_queue.empty():
        remaining.append(mgr._dispatch_queue.get_nowait().symbol)

    assert remaining == ["T2", "T3", "T4"]
