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


def test_websocket_dedupes_bloated_sdk_channel_and_frees_capacity_on_unsubscribe():
    """
    Regression test for FyersDataSocket -99 (5254 > 5000):
    When SDK `scrips_per_channel[11]` contains duplicate HSM tokens for fewer than 5000
    unique `symbol_token` entries, `subscribe()` must deduplicate against `symbol_token`
    instead of falsely capping new symbols to 0, skip symbols already in `symbol_token`,
    and `unsubscribe()` must reclaim capacity immediately.
    """
    mgr = WebSocketManager()
    mgr._connected = True

    class FakeFyersWs:
        def __init__(self):
            self.symbol_token = {f"101000{i}": f"NSE:EXTRA_{i}-EQ" for i in range(100)}
            # Simulate FyersDataSocket += duplicate bloat (e.g. 52x duplicated > 5000)
            self.scrips_per_channel = {11: list(self.symbol_token.keys()) * 53}
            self.scrips_count = {11: list(self.symbol_token.keys())[-10:]}
            self.sub_calls = []
            self.unsub_calls = []

        def subscribe(self, batch):
            self.sub_calls.append(list(batch))
            for idx, s in enumerate(batch):
                tok = f"202000{len(self.symbol_token) + idx}"
                self.symbol_token[tok] = s
                self.scrips_per_channel[11].append(tok)
            self.scrips_count[11] = [f"202000{i}" for i in range(len(batch))]

        def unsubscribe(self, batch):
            self.unsub_calls.append((list(batch), list(self.scrips_count[11])))

    fake_ws = FakeFyersWs()
    mgr._ws = fake_ws
    mgr._subscribed = {f"NSE:EXTRA_{i}-EQ" for i in range(50)}  # out-of-sync local set

    with patch("market.ws_subscription_manager.get_ws_subscription_manager") as mock_get_mgr:
        mock_get_mgr.return_value = MagicMock()
        # Subscribe 1 already-in-SDK symbol + 2 genuinely new symbols
        mgr.subscribe(
            ["NSE:EXTRA_75-EQ", "NSE:PERSIST_NEW1-EQ", "NSE:PERSIST_NEW2-EQ"],
            record_in_manager=False,
        )

    assert len(fake_ws.sub_calls) == 1
    assert fake_ws.sub_calls[0] == ["NSE:PERSIST_NEW1-EQ", "NSE:PERSIST_NEW2-EQ"]
    assert len(fake_ws.scrips_per_channel[11]) == 102
    assert "NSE:EXTRA_75-EQ" in mgr._subscribed
    assert "NSE:PERSIST_NEW1-EQ" in mgr._subscribed

    # Unsubscribe an earlier symbol (not in final batch) and ensure scrips_count was seeded
    mgr.unsubscribe(["NSE:EXTRA_0-EQ"])
    assert len(fake_ws.unsub_calls) == 1
    assert "1010000" in fake_ws.unsub_calls[0][1]
    assert "1010000" not in fake_ws.symbol_token
    assert "1010000" not in fake_ws.scrips_per_channel[11]
    assert "NSE:EXTRA_0-EQ" not in mgr._subscribed


def test_tbt_get_active_slots_status_does_not_stall_on_busy_lock():
    """HealthHub diagnostics must return fast cached snapshot instead of blocking 2.0s when _slots_lock is held."""
    tbt = FyersTbtManager()
    tbt._last_slots_status_cache = {"max_slots": 15, "active_total": 3, "cached": True}

    holder_ready = threading.Event()
    release_holder = threading.Event()

    def _hold_lock():
        with tbt._slots_lock:
            holder_ready.set()
            release_holder.wait(timeout=1.5)

    t = threading.Thread(target=_hold_lock, daemon=True)
    t.start()
    assert holder_ready.wait(timeout=1.0)
    try:
        t0 = time.perf_counter()
        status = tbt.get_active_slots_status()
        elapsed = time.perf_counter() - t0
        assert status["cached"] is True
        assert elapsed < 0.5
    finally:
        release_holder.set()
        t.join(timeout=2.0)


def test_index_setup_effective_dated_cutoff_transition():
    """Verify 15:05 IST pre-Dec-7 vs 15:20 IST post-Dec-7 non-expiry option cutoff via rule_schedule."""
    from datetime import date, datetime, time as dtime, timedelta
    from market.rule_schedule import expiry_weekday, intraday_squareoff_cutoff

    pre_dec7 = date(2026, 11, 25)
    post_dec7_non_exp = date(2026, 12, 9)  # Wednesday (neither NSE Tue nor BSE Thu expiry)
    assert expiry_weekday("NSE", post_dec7_non_exp) != post_dec7_non_exp.weekday()

    sq_pre = intraday_squareoff_cutoff(pre_dec7, is_derivative=True, expiring_index=False)
    sq_post = intraday_squareoff_cutoff(post_dec7_non_exp, is_derivative=True, expiring_index=False)
    assert (datetime.combine(pre_dec7, sq_pre) - timedelta(minutes=10)).time() == dtime(15, 5)
    assert (datetime.combine(post_dec7_non_exp, sq_post) - timedelta(minutes=10)).time() == dtime(
        15, 20
    )
