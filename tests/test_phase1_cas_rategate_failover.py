"""Deterministic regression tests for Phase 1 fixes (25-Nov-2026)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from config.constants import IST_ZONE as IST


def test_rule_schedule_cas_vwap_and_sensex_2027_lot_revision():
    from market.instruments import get_fno_lot_size
    from market.rule_schedule import closing_vwap_window, is_cas_window

    assert is_cas_window(datetime(2026, 12, 7, 15, 35, tzinfo=IST)) is True
    assert is_cas_window(datetime(2026, 12, 7, 15, 20, tzinfo=IST)) is False
    assert is_cas_window(datetime(2026, 11, 25, 15, 20, tzinfo=IST)) is True

    assert closing_vwap_window(datetime(2026, 12, 8, 15, 10, tzinfo=IST), is_expiry=True) is True
    assert closing_vwap_window(datetime(2026, 12, 8, 15, 10, tzinfo=IST), is_expiry=False) is False

    # BSE Notice 20260930-58: Sensex 20 -> 25 for expiries >= 2027-01-25
    assert get_fno_lot_size("SENSEX", expiry_date=date(2026, 12, 24)) == 20
    assert get_fno_lot_size("SENSEX", expiry_date=date(2027, 1, 28)) == 25


def test_tbt_market_session_uses_cas_close_and_holidays(monkeypatch):
    import market.fyers_tbt_manager as tbt

    # 2026-12-07 15:38 IST: derivative desk open until 15:45 IST -> EQUITY_NFO
    class _DtOpen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 7, 15, 38, tzinfo=IST)

    monkeypatch.setattr(tbt, "datetime", _DtOpen)
    monkeypatch.setattr("market.calendar.is_trading_holiday", lambda *a, **k: False)
    assert tbt.get_market_session() == "EQUITY_NFO"

    # Official holiday -> OFF_MARKET during NSE & MCX closed
    monkeypatch.setattr("market.calendar.is_trading_holiday", lambda *a, **k: True)
    assert tbt.get_market_session() == "OFF_MARKET"


def test_fyers_rate_gate_separates_data_and_tx_buckets(tmp_path, monkeypatch):
    from market.fyers_rate_gate import FyersCallCategory, UnifiedFyersRateGate

    qfile = tmp_path / "fyers_quota_split.json"
    monkeypatch.setattr("market.fyers_rate_gate._QUOTA_FILE", qfile)

    gate = UnifiedFyersRateGate(max_per_sec=1000.0, max_per_min=3.0, max_per_day=100.0)
    # Saturate DATA sliding window to 3/min
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE, timeout=0.5) is True
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE, timeout=0.5) is True
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE, timeout=0.5) is True
    assert gate.acquire(category=FyersCallCategory.SCANNER_QUOTE, timeout=0.05) is False

    # TRANSACTION bucket (ORDER) must remain unblocked on Fyers Prime!
    assert gate.acquire(category=FyersCallCategory.ORDER, timeout=0.5) is True
    diag = gate.get_diagnostics()
    assert diag["data_requests_last_min"] == 3
    assert diag["tx_requests_last_min"] == 1

    # Flush and reload persists category breakdown
    gate.flush_quota()
    gate2 = UnifiedFyersRateGate(max_per_sec=1000.0, max_per_min=3.0, max_per_day=100.0)
    assert gate2.get_diagnostics()["daily_requests_by_tier"]["ORDER"] == 1
    assert gate2.get_diagnostics()["daily_requests_by_tier"]["SCANNER_QUOTE"] == 3


def test_flattrade_instrument_tpseries_spot_failclosed_and_subscribe():
    from brokers.flattrade import FlattradeAPI, _CACHE_LOCK, _FLATTRADE_RESOLVED_CACHE

    with _CACHE_LOCK:
        _FLATTRADE_RESOLVED_CACHE.clear()

    b = FlattradeAPI.__new__(FlattradeAPI)
    b._token = "tok"
    b._token_date = "2026-11-25"
    b._instrument_cache = {}
    b._token_map = {}
    b._subscriptions = set()
    b._ws = None
    b._ws_thread = None
    b.is_authenticated = lambda: True

    def _fake_post(endpoint, payload):
        if endpoint == "SearchScrip":
            return {
                "values": [
                    {
                        "exch": "NFO",
                        "token": "55555",
                        "tsym": "NIFTY26NOV25000CE",
                        "ls": "65",
                        "ti": "0.05",
                    }
                ]
            }
        if endpoint == "TPSeries":
            assert payload["intrv"] == "5"  # previously corrupted to '5ute'!
            return {"values": []}
        return {"values": []}

    b._post = _fake_post
    res = b._resolve_instrument("NFO:NIFTY26NOV25000CE")
    assert res["token"] == "55555"
    # Dead code previously skipped populating _token_map!
    assert b.get_symbol_for_token("55555", exch="NFO") == "NIFTY26NOV25000CE"

    b.get_historical_data("NFO:NIFTY26NOV25000CE", exchange="NFO", interval="5minute")

    # Option chain must fail closed (return []) instead of fabricating spot = step * 100
    b.get_quote = lambda *a, **k: {}
    assert b.get_options_chain("NIFTY") == []

    # subscribe_websocket method must exist and register token subscriptions
    b.start_websocket = MagicMock()
    b.subscribe_websocket(["NFO:NIFTY26NOV25000CE"], on_tick=lambda t: None)
    assert "NFO|55555" in b._subscriptions


def test_options_chain_fails_over_to_flattrade_when_fyers_cb_tripped(monkeypatch):
    from brokers.base import OptionsContract
    from market.options import _CHAIN_CACHE, _CHAIN_CACHE_LOCK, get_options_chain

    with _CHAIN_CACHE_LOCK:
        _CHAIN_CACHE.clear()

    tripped_cb = MagicMock()
    tripped_cb.is_tripped.return_value = True
    monkeypatch.setattr(
        "market.fyers_circuit_breaker.get_fyers_circuit_breaker", lambda: tripped_cb
    )

    sec_contract = OptionsContract(
        symbol="NFO:NIFTY26NOV25000CE",
        underlying="NIFTY",
        strike=25000.0,
        option_type="CE",
        expiry="2026-11-26",
        last_price=125.0,
        oi=100000,
        oi_change=0,
        volume=0,
    )
    sec_broker = MagicMock()
    sec_broker._is_mock = False
    sec_broker.get_options_chain.return_value = [sec_contract]

    monkeypatch.setattr("brokers.session.get_data_broker_key", lambda: "fyers")
    monkeypatch.setattr(
        "brokers.session.get_all_brokers",
        lambda: {"fyers": MagicMock(_is_mock=False), "flattrade": sec_broker},
    )

    res = get_options_chain("NIFTY", bypass_cache=True)
    assert len(res) == 1
    assert res[0].last_price == 125.0
    sec_broker.get_options_chain.assert_called_once()


def test_pretrade_bse_holiday_and_live_option_market_requires_depth(monkeypatch):
    from engine.pretrade import _gate_bid_ask_spread, _gate_market_session

    seen_exchanges = []

    def _fake_holiday(check_date=None, exchange="NSE", ref_time=None):
        seen_exchanges.append(exchange)
        return True

    monkeypatch.setattr("market.calendar.is_trading_holiday", _fake_holiday)
    monkeypatch.setattr("market.calendar.get_holiday_reason", lambda **kw: "BSE Holiday")
    sess_res = _gate_market_session("OPT", symbol="BFO:SENSEX26DEC80000CE")
    assert sess_res.passed is False
    assert seen_exchanges[-1] == "BSE"

    spread_res = _gate_bid_ask_spread(
        symbol="NFO:NIFTY26DEC25000CE",
        order_type="MARKET",
        side="BUY",
        ltp=120.0,
        best_bid=None,
        best_ask=None,
        segment="OPT",
        require_depth=True,
    )
    assert spread_res.passed is False


def test_outbox_worker_blocks_ack_when_telegram_send_fails(monkeypatch):
    from engine.outbox_worker import OutboxWorker

    mock_store = MagicMock()
    mock_store.claim_pending_outbox_entries.return_value = [
        {
            "outbox_id": "obx-test-1",
            "channel": "TELEGRAM",
            "payload": {"alert_id": "aa-1", "symbol": "NIFTY", "headline": "Test"},
        }
    ]

    recorded_waits = []

    def _fake_send_push(*args, wait=False, **kwargs):
        recorded_waits.append(wait)
        return False

    worker = OutboxWorker(store=mock_store, worker_id="w1")
    with patch("bot.telegram_bot.get_telegram_bot", return_value=None):
        with patch("bot.telegram_bot.send_push", new=_fake_send_push):
            count = worker.process_outbox_batch()

    assert count == 0
    assert recorded_waits == [True]
    mock_store.mark_outbox_acknowledged.assert_not_called()
    mock_store.mark_outbox_failed.assert_called_once()
