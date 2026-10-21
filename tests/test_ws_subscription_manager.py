"""
tests/test_ws_subscription_manager.py
─────────────────────────────────────
Unit tests for WsSubscriptionManager LRU capacity and disk restoration.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from market.ws_subscription_manager import WsSubscriptionManager, CORE_BASE_SYMBOLS


def test_ws_subscription_manager_core_retention_and_lru():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch(
            "market.ws_subscription_manager._get_cache_path",
            return_value=Path(tmp_dir) / "sub.json",
        ):
            # Set a low limit for easy testing: 45 symbols (core base has 40, leaving 5 dynamic slots)
            max_limit = len(CORE_BASE_SYMBOLS) + 5
            mgr = WsSubscriptionManager(max_subscriptions=max_limit)

            mock_ws = MagicMock()

            # Add 5 dynamic symbols
            dyn1 = [f"NSE:EXTRA_{i}-EQ" for i in range(5)]
            mgr.add_subscriptions(dyn1, ws_client=mock_ws)

            current = mgr.get_all_desired_subscriptions()
            assert len(current) == max_limit

            # Add a 6th dynamic symbol -> should evict EXTRA_0
            mgr.add_subscriptions(["NSE:EXTRA_5-EQ"], ws_client=mock_ws)
            current_after = mgr.get_all_desired_subscriptions()

            assert len(current_after) == max_limit
            assert "NSE:EXTRA_5-EQ" in current_after
            assert "NSE:EXTRA_0-EQ" not in current_after
            # Core base symbols must never be evicted
            assert "NSE:RELIANCE-EQ" in current_after


def test_ws_subscription_manager_disk_restore_on_restart():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sub_file = Path(tmp_dir) / "sub.json"
        with patch("market.ws_subscription_manager._get_cache_path", return_value=sub_file):
            max_limit = len(CORE_BASE_SYMBOLS) + 10
            mgr1 = WsSubscriptionManager(max_subscriptions=max_limit)
            mgr1.add_subscriptions(["NSE:PERSIST_1-EQ", "NSE:PERSIST_2-EQ"])

            # Simulate restart: instantiate new manager from same disk file
            mgr2 = WsSubscriptionManager(max_subscriptions=max_limit)
            desired = mgr2.get_all_desired_subscriptions()

            assert "NSE:PERSIST_1-EQ" in desired
            assert "NSE:PERSIST_2-EQ" in desired

            mock_ws = MagicMock()
            mgr2.on_ws_connected(mock_ws)
            mock_ws.subscribe.assert_called_once_with(desired)


def test_ws_subscription_manager_seed_active_derivatives():
    from market.ws_subscription_manager import (
        WsSubscriptionManager,
        get_active_index_options_grid,
        get_active_commodity_grid,
    )

    opt_grid = get_active_index_options_grid(num_strikes_per_side=4)
    assert len(opt_grid) > 0
    # Must include NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX
    assert any("NIFTY" in s for s in opt_grid)
    assert any("BANKNIFTY" in s for s in opt_grid)
    assert any("MIDCPNIFTY" in s for s in opt_grid)
    assert any("SENSEX" in s for s in opt_grid)
    assert any(s.endswith("CE") for s in opt_grid)
    assert any(s.endswith("PE") for s in opt_grid)

    comm_grid = get_active_commodity_grid()
    assert len(comm_grid) > 0
    assert any("CRUDEOIL" in s for s in comm_grid)
    assert any("GOLD" in s for s in comm_grid)
    assert any("USDINR" in s for s in comm_grid)

    with tempfile.TemporaryDirectory() as tmp_dir:
        sub_file = Path(tmp_dir) / "sub.json"
        with patch("market.ws_subscription_manager._get_cache_path", return_value=sub_file):
            mgr = WsSubscriptionManager(max_subscriptions=5000)
            mock_ws = MagicMock()
            seeded = mgr.seed_active_derivatives(ws_client=mock_ws)
            assert len(seeded) > 50
            desired = mgr.get_all_desired_subscriptions()
            # Verified that index options are now in desired subscriptions
            assert any("NIFTY" in s and ("CE" in s or "PE" in s) for s in desired)
            mock_ws.subscribe.assert_called_once()


def test_parse_contract_expiry_and_is_contract_expired():
    from datetime import date, datetime
    from config.constants import IST_ZONE as IST
    from market.ws_subscription_manager import parse_contract_expiry, is_contract_expired

    # 1. Weekly Options
    exp_w = parse_contract_expiry("NSE:NIFTY26O1922900CE")
    assert exp_w == date(2026, 10, 19)

    # 2. Monthly Options
    exp_m = parse_contract_expiry("NSE:NIFTY26OCT23000CE")
    assert exp_m == date(2026, 10, 29)  # Last Thursday of Oct 2026

    # 3. Futures
    exp_f = parse_contract_expiry("NSE:NIFTY26OCTFUT")
    assert exp_f == date(2026, 10, 29)

    # 4. Non-derivatives
    assert parse_contract_expiry("NSE:RELIANCE-EQ") is None
    assert parse_contract_expiry("NSE:NIFTY50-INDEX") is None
    assert parse_contract_expiry("MCX:CRUDEOIL") is None

    # 5. Expired contracts vs Active contracts
    # October 2024 contract is definitely expired as of 2026
    ref_dt = datetime(2026, 10, 19, 12, 0, tzinfo=IST)
    assert is_contract_expired("NSE:NIFTY24O1725000CE", ref_dt=ref_dt) is True
    # December 2026 contract is not expired
    assert is_contract_expired("NSE:NIFTY26D3126000CE", ref_dt=ref_dt) is False
    # Cash equities never expire
    assert is_contract_expired("NSE:RELIANCE-EQ", ref_dt=ref_dt) is False

    # 6. Expiry day session cutoff
    # On expiry day before 15:30 IST -> active
    ref_day_active = datetime(2026, 10, 19, 14, 0, tzinfo=IST)
    assert is_contract_expired("NSE:NIFTY26O1922900CE", ref_dt=ref_day_active) is False
    # On expiry day after 15:30 IST -> expired
    ref_day_closed = datetime(2026, 10, 19, 15, 35, tzinfo=IST)
    assert is_contract_expired("NSE:NIFTY26O1922900CE", ref_dt=ref_day_closed) is True


def test_cleanse_expired_derivatives():
    from market.ws_subscription_manager import WsSubscriptionManager

    with tempfile.TemporaryDirectory() as tmp_dir:
        sub_file = Path(tmp_dir) / "sub.json"
        with patch("market.ws_subscription_manager._get_cache_path", return_value=sub_file):
            mgr = WsSubscriptionManager(max_subscriptions=5000)
            mock_ws = MagicMock()

            # Seed an expired contract and a future active contract
            expired_sym = "NSE:NIFTY24O1725000CE"  # 2024
            active_sym = "NSE:NIFTY26D3126000CE"  # Dec 2026

            mgr.add_subscriptions([expired_sym, active_sym], ws_client=mock_ws)
            desired = mgr.get_all_desired_subscriptions()
            assert expired_sym in desired
            assert active_sym in desired

            # Run cleanse
            purged = mgr.cleanse_expired_derivatives(ws_client=mock_ws)
            assert expired_sym in purged
            assert active_sym not in purged
            mock_ws.unsubscribe.assert_called_with([expired_sym])

            # Check memory state
            desired_after = mgr.get_all_desired_subscriptions()
            assert expired_sym not in desired_after
            assert active_sym in desired_after
            # Core equities strictly retained
            assert "NSE:RELIANCE-EQ" in desired_after

            # Check disk state on restart
            mgr2 = WsSubscriptionManager(max_subscriptions=5000)
            desired_reloaded = mgr2.get_all_desired_subscriptions()
            assert expired_sym not in desired_reloaded
            assert active_sym in desired_reloaded


def test_websocket_tick_staleness_and_zero_ltp_guard():
    import time
    from market.websocket import WebSocketManager, Tick

    # 1. Tick staleness test
    now = time.time()
    fresh_tick = Tick(symbol="NSE:TEST-EQ", ltp=100.0, timestamp=now)
    stale_tick = Tick(symbol="NSE:TEST-EQ", ltp=100.0, timestamp=now - 120.0)

    assert fresh_tick.is_stale(max_age_seconds=60.0) is False
    assert stale_tick.is_stale(max_age_seconds=60.0) is True

    # 2. WebSocketManager get_tick staleness filter
    ws_mgr = WebSocketManager()
    with ws_mgr._lock:
        ws_mgr._ticks["NSE:FRESH-EQ"] = fresh_tick
        ws_mgr._ticks["NSE:STALE-EQ"] = stale_tick

    assert ws_mgr.get_tick("NSE:FRESH-EQ", max_age_seconds=60.0) is not None
    assert ws_mgr.get_tick("NSE:STALE-EQ", max_age_seconds=60.0) is None
    # Without filter, returns the cached tick
    assert ws_mgr.get_tick("NSE:STALE-EQ") is not None

    # 3. Zero-LTP overwrite poisoning guard
    # First message: valid trade
    ws_mgr._on_message([{"symbol": "NSE:GUARD-EQ", "ltp": 500.0, "exch_feed_time": now}])
    assert ws_mgr.get_tick("NSE:GUARD-EQ").ltp == 500.0

    # Second message: depth or heartbeat packet with ltp=0
    ws_mgr._on_message([{"symbol": "NSE:GUARD-EQ", "ltp": 0.0, "bid": 499.5, "ask": 500.5}])
    # Invariant: valid traded price must NOT be overwritten by 0.0
    tick_after = ws_mgr.get_tick("NSE:GUARD-EQ")
    assert tick_after.ltp == 500.0
    assert tick_after.bid == 499.5
    assert tick_after.ask == 500.5

    # 4. Cleanse stale ticks
    with ws_mgr._lock:
        ws_mgr._ticks["NSE:VERY_OLD-EQ"] = Tick(
            symbol="NSE:VERY_OLD-EQ", ltp=50.0, timestamp=now - 100000.0
        )
    purged_count = ws_mgr.cleanse_stale_ticks(max_age_seconds=86400.0)
    assert purged_count >= 1
    assert ws_mgr.get_tick("NSE:VERY_OLD-EQ") is None


def test_mcx_tender_auto_roll_resolution():
    """
    Assert 48-hour pre-tender period auto-roll logic:
    - Crude Oil futures roll to next month from day 17 (tender starts ~17th).
    - Natural Gas futures roll to next month from day 23 (tender starts ~23rd).
    - Crude Oil options roll to next month from day 16 (options expire 2 days before futures).
    """
    import datetime as dt
    from brokers.fyers import _resolve_commodity_contract
    from market.ws_subscription_manager import get_active_commodity_grid

    # Case A: Crude Oil before day 17 -> current month
    mid_month = dt.datetime(2026, 5, 10, 10, 0, 0)
    res_crude_early = _resolve_commodity_contract("CRUDEOIL", ref_time=mid_month)
    assert res_crude_early == "MCX:CRUDEOIL26MAYFUT"

    # Case B: Crude Oil on day 17 -> rolled to next month (JUN)
    tender_crude = dt.datetime(2026, 5, 17, 10, 0, 0)
    res_crude_tender = _resolve_commodity_contract("CRUDEOIL", ref_time=tender_crude)
    assert res_crude_tender == "MCX:CRUDEOIL26JUNFUT"

    # Case C: Natural Gas before day 23 -> current month (MAY)
    mid_gas = dt.datetime(2026, 5, 20, 10, 0, 0)
    res_gas_early = _resolve_commodity_contract("NATURALGAS", ref_time=mid_gas)
    assert res_gas_early == "MCX:NATURALGAS26MAYFUT"

    # Case D: Natural Gas on day 23 -> rolled to next month (JUN)
    tender_gas = dt.datetime(2026, 5, 23, 10, 0, 0)
    res_gas_tender = _resolve_commodity_contract("NATURALGAS", ref_time=tender_gas)
    assert res_gas_tender == "MCX:NATURALGAS26JUNFUT"

    # Case E: Crude Oil options grid rolls on day 16
    grid_rolled = get_active_commodity_grid(ref_time=dt.datetime(2026, 5, 16, 10, 0, 0))
    assert any("MCX:CRUDEOIL26JUN" in s and ("CE" in s or "PE" in s) for s in grid_rolled)
