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
