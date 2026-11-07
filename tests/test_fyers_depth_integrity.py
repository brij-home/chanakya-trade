"""Depth queues must never become traded-volume or session OHLC evidence."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from brokers.fyers import FyersAPI
from market import fyers_tbt_manager as tbt_module


@pytest.mark.parametrize("age", [0, 14, 16, -1, float("nan"), None])
def test_local_packet_age_controls_depth_liveness(age):
    snapshot = {"status": "LIVE"} if age is None else {"status": "LIVE", "received_at": 1000 - age}
    assert tbt_module.is_fresh_tbt_depth(snapshot, now=1000) is (age in (0, 14))


def test_incomplete_sdk_transport_is_cached_as_unavailable(monkeypatch):
    importer = Mock(side_effect=ModuleNotFoundError("websocket"))
    monkeypatch.setattr(tbt_module, "_FYERS_APIV3_AVAILABLE", None)
    monkeypatch.setattr(tbt_module, "import_module", importer)
    assert tbt_module._is_fyers_sdk_available() is False
    assert tbt_module._is_fyers_sdk_available() is False
    importer.assert_called_once_with("fyers_apiv3.FyersWebsocket.tbt_ws")


def test_depth_keeps_queues_distinct_from_trade_volume_and_session_vwap(monkeypatch):
    snapshot = {
        "status": "LIVE",
        "received_at": time.time(),
        "ltp": 100.0,
        "bids": [{"price": 99.0, "qty": 1500, "orders": 4}],
        "asks": [{"price": 101.0, "qty": 500, "orders": 2}],
        "tbq": 1500,
        "tsq": 500,
        "rolling_tick_vwap": 99.5,
    }
    manager = SimpleNamespace(_depth_lock=threading.Lock(), _depth_cache={"TCS": snapshot})
    monkeypatch.setattr(tbt_module, "FyersTbtManager", lambda: manager)
    api = FyersAPI.__new__(FyersAPI)
    api._depth_cache_lock = threading.Lock()
    api._depth_cache = {}
    api._depth_cache_ttl = 3.0
    api._get_fyers = Mock(return_value=None)
    monkeypatch.setattr(
        "brokers.fyers.get_fyers_circuit_breaker", lambda: SimpleNamespace(is_tripped=lambda: False)
    )

    result = api.get_market_depth("TCS")
    assert result["provider"] == "FYERS_TBT_50"
    assert result["total_buy_qty"] == 1500
    assert result["bid_ask_ratio"] == 3.0
    assert result["rolling_tick_vwap"] == 99.5
    for key in ("volume", "open", "high", "low", "close", "oi", "pdoi", "atp"):
        assert result[key] is None
    assert result["ohlcv_status"] == "UNAVAILABLE"
    assert api._depth_cache == {}

    # A disconnected stream cannot have its old snapshot relabeled LIVE or
    # receive the REST cache's five-minute off-market extension.
    snapshot["received_at"] = time.time() - 60
    assert api.get_market_depth("TCS")["status"] == "UNAVAILABLE"
    api._get_fyers.assert_called_once()
