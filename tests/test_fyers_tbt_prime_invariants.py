"""
tests/test_fyers_tbt_prime_invariants.py
────────────────────────────────────────
Regression & Invariant suite for Fyers Prime 15-Symbol 50-Level Depth TBT WebSocket.
Verifies:
  1. MAX_SYMBOLS_PER_WORKER == 5 hard physical socket constraint.
  2. Multi-worker pool partitioning strictly assigns <= 5 symbols per connected worker.
  3. Channel synchronization uses single-channel activation (Channel '1') to prevent server-side symbol limit errors.
  4. Transient 429 errors do not permanently revoke multi-socket Prime entitlement.
"""

from unittest.mock import MagicMock

from market.fyers_tbt_manager import (
    FyersTbtManager,
    TbtSocketWorker,
    MAX_TBT_SYMBOLS,
    MAX_SYMBOLS_PER_WORKER,
)


def test_tbt_constants_invariants():
    """Verify core constants enforce Fyers Prime 15 total and 5 per connection."""
    assert MAX_TBT_SYMBOLS == 15
    assert MAX_SYMBOLS_PER_WORKER == 5


def test_tbt_worker_sync_single_channel_and_cap():
    """Verify that TbtSocketWorker.sync() clamps desired symbols to 5 and uses single channel '1'."""
    worker = TbtSocketWorker(
        worker_id=0,
        auth_token_getter=lambda: "MOCK:TOKEN",
        on_depth=lambda s, d: None,
        on_status=lambda wid, st: None,
    )
    worker.connected = True
    worker.ws = MagicMock()

    # Even if someone sets desired to 12 symbols:
    worker.desired = [f"NSE:SYM{i}FUT" for i in range(12)]
    worker.sync()

    # Worker subscribed must be strictly capped at 5
    assert len(worker.subscribed) == 5
    assert worker.subscribed == set([f"NSE:SYM{i}FUT" for i in range(5)])

    # Must only subscribe to channel '1'
    worker.ws.subscribe.assert_called_once()
    _, kwargs = worker.ws.subscribe.call_args
    assert kwargs.get("channelNo") == "1"
    assert len(kwargs.get("symbol_tickers", set())) == 5

    # switchChannel must only resume channel '1'
    worker.ws.switchChannel.assert_called_once_with(resume_channels={"1"}, pause_channels=set())


def test_tbt_pool_dynamic_allocation_respects_5_symbol_cap_per_connection():
    """
    Verify Fyers Prime multi-socket pool dynamically scales across 1, 2, or 3 workers
    WITHOUT EVER assigning > 5 symbols to any single connection.
    """
    mgr = FyersTbtManager()

    w0 = TbtSocketWorker(0, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    w1 = TbtSocketWorker(1, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    w2 = TbtSocketWorker(2, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    w0.ws = MagicMock()
    w1.ws = MagicMock()
    w2.ws = MagicMock()

    mgr._workers = [w0, w1, w2]
    symbols_15 = [f"NSE:MOCKFUT{i:02d}" for i in range(15)]
    mgr._core_grid = symbols_15[:15]

    # --- Case 1: Only Worker 0 is connected ---
    w0.connected = True
    w1.connected = False
    w2.connected = False

    mgr.sync_subscriptions()

    # Worker 0 MUST NOT take 10 or 15 symbols; it must strictly take the top 5!
    assert len(w0.desired) == 5
    assert w0.desired == symbols_15[:5]
    assert len(w1.desired) == 0
    assert len(w2.desired) == 0

    # --- Case 2: Worker 0 and Worker 1 are connected ---
    w1.connected = True
    mgr.sync_subscriptions()

    assert len(w0.desired) == 5
    assert w0.desired == symbols_15[:5]
    assert len(w1.desired) == 5
    assert w1.desired == symbols_15[5:10]
    assert len(w2.desired) == 0

    # --- Case 3: All 3 workers connected (Full Fyers Prime capacity) ---
    w2.connected = True
    mgr.sync_subscriptions()

    assert len(w0.desired) == 5
    assert w0.desired == symbols_15[:5]
    assert len(w1.desired) == 5
    assert w1.desired == symbols_15[5:10]
    assert len(w2.desired) == 5
    assert w2.desired == symbols_15[10:15]

    # Total subscribed across pool is exactly 15
    assert len(mgr._subscribed) == 15


def test_transient_429_does_not_revoke_multi_socket_entitlement():
    """Verify that a single transient 429 does not permanently downgrade account to single-socket mode."""
    mgr = FyersTbtManager()
    mgr._multi_socket_entitled = True

    w0 = TbtSocketWorker(0, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    w1 = TbtSocketWorker(1, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    mgr._workers = [w0, w1]

    # First 429 strike
    w1._consecutive_429 = 1
    mgr._handle_worker_status(1, "DEGRADED_429")

    # Entitlement remains True for retry
    assert mgr._multi_socket_entitled is True

    # After repeated failures (>= 5 strikes), entitlement safely parks
    w1._consecutive_429 = 5
    mgr._handle_worker_status(1, "DEGRADED_429")
    assert mgr._multi_socket_entitled is False
    assert mgr._multi_socket_suppressed_until > 0

    # Self-healing: once probation window passes, entitlement recovers automatically
    mgr._multi_socket_suppressed_until = 0.0
    assert mgr._eval_multi_socket_entitled() is True


def test_eval_multi_socket_entitled_with_plan_and_env(monkeypatch):
    """Verify that _eval_multi_socket_entitled honors FYERS_PLAN=PRIME and FYERS_TBT_WORKERS."""
    mgr = FyersTbtManager()
    mgr._multi_socket_suppressed_until = 0.0

    # 1. FYERS_PLAN=PRIME with no env worker override -> True
    monkeypatch.setenv("FYERS_PLAN", "PRIME")
    monkeypatch.delenv("FYERS_TBT_WORKERS", raising=False)
    assert mgr._eval_multi_socket_entitled() is True

    # 2. FYERS_TBT_WORKERS=3 -> True
    monkeypatch.setenv("FYERS_TBT_WORKERS", "3")
    assert mgr._eval_multi_socket_entitled() is True

    # 3. Explicit operator single-worker throttle FYERS_TBT_WORKERS=1 -> False
    monkeypatch.setenv("FYERS_TBT_WORKERS", "1")
    assert mgr._eval_multi_socket_entitled() is False

    # 4. Non-prime plan without override -> False
    monkeypatch.setenv("FYERS_PLAN", "BASIC")
    monkeypatch.delenv("FYERS_TBT_WORKERS", raising=False)
    assert mgr._eval_multi_socket_entitled() is False


def test_rebalance_grid_now_recovers_entitlement_and_connects_workers(monkeypatch):
    """Verify that rebalance_grid_now lifts expired probation and attempts reconnect on quiescent workers."""
    mgr = FyersTbtManager()
    monkeypatch.setenv("FYERS_PLAN", "PRIME")
    monkeypatch.setenv("FYERS_TBT_WORKERS", "3")

    w0 = TbtSocketWorker(0, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    w1 = TbtSocketWorker(1, lambda: "TOK", lambda s, d: None, lambda wid, st: None)
    w0.connected = True
    w1.connected = False
    w1.status = "DISCONNECTED"
    w1.connect = MagicMock()

    mgr._workers = [w0, w1]
    # Simulate expired probation
    mgr._multi_socket_suppressed_until = 1.0  # far in the past
    mgr._multi_socket_entitled = False

    res = mgr.rebalance_grid_now()
    assert res["status"] == "ok"
    assert mgr._multi_socket_entitled is True
    # Worker 1 should have been prompted to connect
    w1.connect.assert_called_once()
