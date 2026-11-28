"""
tests/test_fyers_prime_upgrades.py
──────────────────────────────────
Regression tests covering Fyers Prime REST/Bulk, DataSocket field mapping,
BFO 5-level DepthUpdate, rate-gate enforcement, postback OMS reconciliation,
MCP resources & Prime tools, and SmartFunnel FNO_ONLY discovery scoping.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_websocket_fyers_symbol_update_and_depth_update_mapping():
    """Verify Fyers map.json keys (bid_price, ask_price, OI, avg_trade_price, DepthUpdate) map cleanly."""
    from market.websocket import WebSocketManager
    from market.order_book import get_depth_book

    mgr = WebSocketManager()
    # 1. SymbolUpdate packet matching fyers_apiv3 map.json schema (Fyers NFO uses NSE: prefix)
    mgr._on_message(
        {
            "symbol": "NSE:NIFTY26DECFUT",
            "ltp": 25100.5,
            "open_price": 25000.0,
            "high_price": 25150.0,
            "low_price": 24980.0,
            "prev_close_price": 24990.0,
            "vol_traded_today": 125000,
            "bid_price": 25100.0,
            "ask_price": 25101.0,
            "bid_size": 130,
            "ask_size": 195,
            "OI": 987650,
            "avg_trade_price": 25065.25,
        }
    )

    tick = mgr.get_tick("NSE:NIFTY26DECFUT")
    assert tick is not None
    assert tick.ltp == 25100.5
    assert tick.bid == 25100.0
    assert tick.ask == 25101.0
    assert tick.bid_qty == 130
    assert tick.ask_qty == 195
    assert tick.oi == 987650
    assert tick.atp == 25065.25

    # 2. DepthUpdate 5-level packet for BFO / SENSEX option
    mgr._on_message(
        {
            "symbol": "BSE:SENSEX26DEC81000CE",
            "ltp": 420.5,
            "bid_price1": 420.0,
            "bid_size1": 40,
            "bid_order1": 2,
            "bid_price2": 419.5,
            "bid_size2": 80,
            "bid_order2": 3,
            "ask_price1": 421.0,
            "ask_size1": 60,
            "ask_order1": 1,
            "ask_price2": 421.5,
            "ask_size2": 100,
            "ask_order2": 4,
        }
    )
    l2 = mgr.get_l2_depth("BSE:SENSEX26DEC81000CE")
    assert l2 is not None
    assert l2["depth_level"] == 5
    assert l2["provider"] == "fyers_ws_depth_5"
    assert len(l2["bids"]) == 2
    assert l2["bids"][0]["price"] == 420.0
    assert l2["asks"][0]["price"] == 421.0
    book = get_depth_book("SENSEX26DEC81000CE")
    assert book.best_bid == 420.0
    assert book.best_ask == 421.0


def test_fyers_quotes_v2_1000_symbol_batching(monkeypatch):
    """Verify FyersAPI.get_quote uses quotes_v2 (up to 1,000 symbols/request) when available."""
    from brokers.fyers import FyersAPI
    from market.quote_dispatcher import QuoteDispatcher

    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "tok"

    v2_chunks = []

    class RealLikeFyersSDK:
        def quotes_v2(self, payload):
            syms = payload["symbols"]
            v2_chunks.append(syms)
            return {
                "s": "ok",
                "d": [
                    {
                        "n": s,
                        "s": "ok",
                        "v": {
                            "lp": 100.0,
                            "open_price": 99.0,
                            "high_price": 101.0,
                            "low_price": 98.0,
                            "prev_close_price": 99.5,
                            "volume": 100,
                        },
                    }
                    for s in syms
                ],
            }

        def quotes(self, payload):
            raise AssertionError("GET quotes() should not be called when quotes_v2 succeeds")

    monkeypatch.setattr(api, "_get_fyers", lambda: RealLikeFyersSDK())
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)

    symbols = [f"NSE:STK{i}-EQ" for i in range(950)]
    res = api.get_quote(symbols)
    assert len(res) == 950
    assert len(v2_chunks) == 1
    assert len(v2_chunks[0]) == 950

    # QuoteDispatcher.fetch_quotes_bulk_v2 also batches 950 symbols in 1 call
    dispatcher = QuoteDispatcher()
    captured = []
    with (
        patch.object(dispatcher._rate_gate, "acquire", return_value=True),
        patch(
            "market.quotes.get_quote",
            side_effect=lambda c, **kw: (
                captured.append(len(c)) or {s: MagicMock(last_price=10.0) for s in c}
            ),
        ),
    ):
        dispatcher.fetch_quotes_bulk_v2(symbols)
    assert captured == [950]


def test_fyers_expiry_dates_futures_chain_and_rategate_guards(monkeypatch):
    """Verify get_expired_expiries uses expiry_dates (< today), get_expiries uses optionchain, and futures_chain/guards work."""
    from brokers.fyers import FyersAPI

    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "tok"

    class PrimeSDK:
        def expiry_dates(self, data):
            assert data["range_to"] < "2099-01-01"
            self.last_exp_dates_req = data
            return {
                "s": "ok",
                "data": {"expiry": [{"date": "29-10-2026", "expiry": "1793259000"}]},
            }

        def optionchain(self, data):
            return {
                "s": "ok",
                "data": {"expiryData": [{"date": "01-12-2026", "expiry": "1796119800"}]},
            }

        def futures_chain(self, data):
            return {
                "s": "ok",
                "data": {
                    "futuresChain": [
                        {
                            "symbol": "NSE:NIFTY26DECFUT",
                            "ltp": 25200.0,
                            "oi": 500000,
                            "volume": 12000,
                        }
                    ]
                },
            }

        def ledger_history(self, payload):
            raise AssertionError("Should not execute when rate gate denies")

        def create_alert(self, payload):
            raise AssertionError("Should not execute when rate gate denies")

    sdk = PrimeSDK()
    monkeypatch.setattr(api, "_get_fyers", lambda: sdk)
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)

    active_expiries = api.get_expiries("NIFTY")
    assert active_expiries == ["2026-12-01"]
    assert not hasattr(sdk, "last_exp_dates_req"), (
        "Active get_expiries must NOT hit expired expiry_dates endpoint"
    )

    expired = api.get_expired_expiries("NIFTY")
    assert expired == ["2026-10-29"]
    from datetime import date

    assert sdk.last_exp_dates_req["range_to"] < date.today().isoformat()

    fc = api.get_futures_chain("NIFTY")
    assert fc["status"] == "ok"
    assert fc["contracts"][0]["symbol"] == "NSE:NIFTY26DECFUT"
    assert fc["contracts"][0]["ltp"] == 25200.0

    # Rate-gate denial blocks ledger_history & create_server_alert
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: False)
    ledger = api.get_ledger_history()
    assert ledger["s"] == "error"
    alert_res = api.create_server_alert("NIFTY", "test", 25000.0)
    assert alert_res["s"] == "error"


def test_fyers_place_order_auth_retry_checks_orderbook_first(monkeypatch):
    """Verify place_order does not blindly duplicate an order on auth retry when orderbook shows it live."""
    from brokers.base import OrderRequest
    from brokers.fyers import FyersAPI

    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "tok"
    api._token_ts = 1e12  # fresh

    place_calls = 0

    class AuthRetrySDK:
        def place_order(self, payload):
            nonlocal place_calls
            place_calls += 1
            return {"s": "error", "code": -16, "message": "Invalid token"}

        def orderbook(self):
            return {
                "s": "ok",
                "orderBook": [
                    {
                        "id": "FYERS-RECOVERED-1",
                        "symbol": "NSE:RELIANCE-EQ",
                        "qty": 1,
                        "side": 1,
                        "status": 6,
                    }
                ],
            }

    monkeypatch.setattr(api, "is_authenticated", lambda: True)
    monkeypatch.setattr(api, "_get_fyers", lambda: AuthRetrySDK())
    monkeypatch.setattr(api, "_handle_auth_failure", lambda failed_ts=None: True)
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)

    req = OrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        price=2500.0,
        product="CNC",
    )
    resp = api.place_order(req)
    assert place_calls == 1
    assert resp.order_id == "FYERS-RECOVERED-1"
    assert resp.status == "OPEN"


def test_fyers_postback_wires_to_oms(monkeypatch):
    """Verify HMAC-verified /api/fyers/postback invokes apply_fyers_stream_order_update."""
    from web.api import app

    monkeypatch.setenv("FYERS_SECRET_KEY", "test_webhook_secret")
    captured = []
    monkeypatch.setattr(
        "engine.order_lifecycle.apply_fyers_stream_order_update",
        lambda payload: captured.append(payload) or {"updated": True},
    )

    body = json.dumps(
        {"order": {"id": "ORD123", "status": "2", "symbol": "NSE:NIFTY26DECFUT"}}
    ).encode("utf-8")
    sig = hmac.new(b"test_webhook_secret", body, hashlib.sha256).hexdigest()

    client = TestClient(app)
    r_bad = client.post("/api/fyers/postback", content=body, headers={"X-Fyers-Signature": "wrong"})
    assert r_bad.status_code == 401

    r_ok = client.post("/api/fyers/postback", content=body, headers={"X-Fyers-Signature": sig})
    assert r_ok.status_code == 200
    assert len(captured) == 1
    assert captured[0]["order"]["id"] == "ORD123"


def test_mcp_resources_and_prime_tools():
    """Verify MCP resources/list, resources/read, tool annotations, and new Prime tools."""
    from web.mcp import MCPServer

    srv = MCPServer()
    tools = {t["name"]: t for t in srv.get_tools_list()}
    for name in (
        "get_fyers_depth_50",
        "check_order_margin",
        "get_futures_chain",
        "get_fyers_telemetry",
        "get_expired_fno_history",
    ):
        assert name in tools
        assert tools[name]["annotations"]["readOnlyHint"] is True
        assert tools[name]["annotations"]["destructiveHint"] is False

    res_list = srv.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    uris = {r["uri"] for r in res_list["result"]["resources"]}
    assert {
        "chanakya://system/mode",
        "chanakya://fyers/telemetry",
        "chanakya://alerts/auto",
        "chanakya://portfolio/reconciliation",
    }.issubset(uris)

    mode_res = srv.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "chanakya://system/mode"},
        }
    )
    parsed = json.loads(mode_res["result"]["contents"][0]["text"])
    assert parsed["mode"] in {"DEMO", "PAPER", "LIVE"}
    assert "discovery_policy" in parsed


def test_smart_funnel_respects_fno_only_discovery_policy(monkeypatch):
    """Verify SmartFunnel blocks crypto_majors preset in FNO_ONLY unless allow_cross_asset=True."""
    from agent.smart_funnel import SmartFunnel
    from config.discovery_policy import DiscoveryPolicy

    monkeypatch.setattr(
        "config.discovery_policy.get_discovery_policy", lambda: DiscoveryPolicy("FNO_ONLY")
    )
    funnel = SmartFunnel(registry=MagicMock(), verbose=False)
    res = funnel.run(symbols="crypto", top_n=2)
    assert res.total_screened == 0
    assert res.qualified_count == 0


def test_fyers_api_v3_nov2026_additions(monkeypatch):
    """Verify -8 auth detection, Quotes CAS fields, GTT MARKET legs, Screeners v3, Killswitch & History."""
    from brokers.base import GTTLeg, GTTRequest
    from brokers.fyers import FyersAPI, _is_fyers_auth_error

    assert _is_fyers_auth_error({"code": -8, "message": "Token expired"}) is True

    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "tok"
    monkeypatch.setattr(api, "is_authenticated", lambda: True)
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)

    class Nov2026SDK:
        def quotes_v2(self, payload):
            return {
                "s": "ok",
                "d": [
                    {
                        "n": "NSE:RELIANCE-EQ",
                        "s": "ok",
                        "v": {
                            "lp": 1350.0,
                            "open_price": 1340.0,
                            "high_price": 1355.0,
                            "low_price": 1338.0,
                            "prev_close_price": 1342.0,
                            "volume": 500000,
                            "reference_price": 1349.5,
                            "indicative_price": 1350.2,
                            "imbalance": 12000,
                            "mkt_imbalance": -1500,
                        },
                    }
                ],
            }

        def place_gtt_order(self, payload):
            self.last_gtt = payload
            return {"s": "ok", "id": "GTT-MKT-1"}

        def gtt_orderbook(self):
            return {
                "s": "ok",
                "orderBook": [{"id": "GTT-1", "ord_type": 2, "ord_type2": 1}],
            }

        def screeners_config(self):
            return {"s": "ok", "data": {"screeners_standard": [{"screener_id": "std_01"}]}}

        def screeners_standard(self, data):
            return {"s": "ok", "screener_id": data["screener_id"], "rows": []}

        def screeners_technical(self, data):
            return {"s": "ok", "received": data}

        def screeners_candlestick(self, data):
            return {"s": "ok", "received": data}

        def history_underlying_symbols(self, data):
            return {"s": "ok", "contracts": [{"symbol": f"{data['symbol']}:25JAN22000CE"}]}

        def get_killswitch_status(self):
            return {
                "s": "ok",
                "data": {"killswitch": False, "openPositions": 1, "pendingOrders": 0},
            }

        def orderhistory(self, data):
            return {"s": "ok", "orderBook": [{"id": "HIST-1"}]}

        def tradehistory(self, data):
            return {"s": "ok", "tradeBook": [{"tradeNumber": "TH-1"}]}

    sdk = Nov2026SDK()
    monkeypatch.setattr(api, "_get_fyers", lambda: sdk)

    # 1. CAS fields on Quote
    q = api.get_quote(["RELIANCE"]).get("RELIANCE")
    assert q is not None
    assert q.reference_price == 1349.5
    assert q.indicative_price == 1350.2
    assert q.imbalance == 12000.0
    assert q.mkt_imbalance == -1500.0

    # 2. GTT Market leg allowed on NSE/NFO, blocked on BFO, ord_type mapped
    oco_req = GTTRequest(
        symbol="RELIANCE",
        exchange="NSE",
        transaction_type="SELL",
        trigger_type="OCO",
        product="CNC",
        leg1=GTTLeg(price=0.0, trigger_price=1300.0, quantity=10, order_type="MARKET"),
        leg2=GTTLeg(price=1450.0, trigger_price=1445.0, quantity=10, order_type="LIMIT"),
    )
    gtt_res = api.place_gtt(oco_req)
    assert gtt_res.status == "ACTIVE"
    assert sdk.last_gtt["orderInfo"]["leg1"]["type"] == 2
    assert sdk.last_gtt["orderInfo"]["leg2"]["type"] == 1

    bfo_req = GTTRequest(
        symbol="BFO:SENSEX26DEC81000CE",
        exchange="BFO",
        transaction_type="SELL",
        trigger_type="SINGLE",
        product="NRML",
        leg1=GTTLeg(price=0.0, trigger_price=200.0, quantity=10, order_type="MARKET"),
    )
    bfo_res = api.place_gtt(bfo_req)
    assert bfo_res.status == "REJECTED"
    assert "BFO" in bfo_res.message

    gtt_book = api.get_gtt_orders()
    assert gtt_book[0]["leg1_order_type"] == "MARKET"
    assert gtt_book[0]["leg2_order_type"] == "LIMIT"

    # 3. Screeners v3 screener_id, config, standard
    assert api.get_screener_technical("cs004", force_refresh=True)["received"] == {
        "screener_id": "cs004"
    }
    assert api.get_screener_candlestick("hammer", force_refresh=True)["received"] == {
        "screener_id": "hammer"
    }
    assert api.get_screener_config()["s"] == "ok"
    assert api.get_screener_standard("std_01", universe="NIFTY50")["screener_id"] == "std_01"

    # 4. Expired contracts, Kill Switch, Order/Trade History
    assert len(api.get_expired_fno_contracts("NIFTY", "2026-10-29")["contracts"]) == 1
    ks = api.get_killswitch_status()
    assert ks["status"] == "ok"
    assert ks["killswitch_active"] is False
    assert ks["open_positions"] == 1
    assert api.get_order_history(from_date="2026-11-01")["orderBook"][0]["id"] == "HIST-1"
    assert (
        api.get_historical_trade_history(from_date="2026-11-01")["tradeBook"][0]["tradeNumber"]
        == "TH-1"
    )


def test_mcp_exposes_nov2026_read_only_tools_and_routes(monkeypatch):
    """Verify new Nov-2026 Fyers tools in MCP/Agent registry and FastAPI routes."""
    from fastapi import FastAPI
    from web.mcp import MCPServer
    from web.routers.market_data import router as md_router

    srv = MCPServer()
    tools = {t["name"]: t for t in srv.get_tools_list()}
    for name in (
        "get_fyers_screener_config",
        "fyers_standard_screener",
        "get_expired_fno_contracts",
        "get_fyers_killswitch_status",
    ):
        assert name in tools
        assert tools[name]["annotations"]["readOnlyHint"] is True
        assert tools[name]["annotations"]["destructiveHint"] is False

    app = FastAPI()
    app.include_router(md_router)
    client = TestClient(app)

    fake_brk = MagicMock()
    fake_brk.get_killswitch_status.return_value = {
        "status": "ok",
        "killswitch_active": False,
        "open_positions": 0,
        "pending_orders": 0,
    }
    fake_brk.get_screener_config.return_value = {"s": "ok", "data": {}}
    fake_brk.get_screener_standard.return_value = {"s": "ok", "rows": []}
    fake_brk.get_expired_fno_contracts.return_value = {
        "s": "ok",
        "contracts": ["NSE:NIFTY25JAN22000CE"],
    }
    fake_brk.get_order_history.return_value = {"s": "ok", "orderBook": []}
    fake_brk.get_historical_trade_history.return_value = {"s": "ok", "tradeBook": []}

    with (
        patch("brokers.session.get_data_broker", return_value=fake_brk),
        patch("brokers.session.get_execution_broker", return_value=fake_brk),
    ):
        assert client.get("/api/fyers/killswitch").json()["status"] == "ok"
        assert client.get("/api/fyers/screeners/config").json()["status"] == "ok"
        assert client.get("/api/fyers/screeners/standard?screener_id=s1").json()["status"] == "ok"
        assert (
            client.get("/api/fyers/expired-contracts?symbol=NIFTY&expiry_date=2026-10-29").json()[
                "research_only"
            ]
            is True
        )
        assert client.get("/api/fyers/order-history").json()["status"] == "ok"
        assert client.get("/api/fyers/trade-history").json()["status"] == "ok"
        assert "calculate_span_margin" in tools
        assert tools["calculate_span_margin"]["annotations"]["readOnlyHint"] is True


def test_quotes_v2_cloudflare_403_falls_back_to_get_quotes_without_auth_trip(monkeypatch):
    """403 Bad request from POST quotes_v2 must fall back cleanly to GET quotes() and NOT trip auth."""
    from brokers.fyers import FyersAPI, _is_fyers_auth_error
    from market.fyers_circuit_breaker import get_fyers_circuit_breaker

    assert _is_fyers_auth_error({"code": 403, "message": "Bad request"}) is False

    cb = get_fyers_circuit_breaker()
    cb.reset()
    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "tok"
    monkeypatch.setattr(api, "is_authenticated", lambda: True)
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)

    get_calls = []

    class BlockedV2SDK:
        def quotes_v2(self, payload):
            return {"s": "error", "code": 403, "message": "Bad request"}

        def quotes(self, payload):
            get_calls.append(payload)
            return {
                "s": "ok",
                "d": [
                    {
                        "n": "NSE:RELIANCE-EQ",
                        "s": "ok",
                        "v": {
                            "lp": 1382.6,
                            "open_price": 1393.8,
                            "high_price": 1398.0,
                            "low_price": 1373.1,
                            "prev_close_price": 1396.2,
                            "volume": 1000,
                        },
                    }
                ],
            }

    monkeypatch.setattr(api, "_get_fyers", lambda: BlockedV2SDK())
    monkeypatch.setattr(
        api,
        "_handle_auth_failure",
        lambda **kw: (_ for _ in ()).throw(AssertionError("Must not reauth")),
    )

    quotes = api.get_quote(["NSE:RELIANCE-EQ"])
    assert len(get_calls) == 1
    assert quotes["NSE:RELIANCE-EQ"].last_price == 1382.6
    assert cb.is_tripped() is False


def test_futures_chain_list_payload_span_margin_and_retry_after(monkeypatch):
    """Verify real list-shaped futures_chain data, SPAN margin calculation, and X-Retry-After-Ms backoff."""
    from brokers.fyers import FyersAPI
    from market.fyers_circuit_breaker import get_fyers_circuit_breaker

    cb = get_fyers_circuit_breaker()
    cb.reset()
    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._access_token = "tok"
    monkeypatch.setattr(api, "is_authenticated", lambda: True)
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)

    class ChainSDK:
        def futures_chain(self, payload):
            return {
                "s": "ok",
                "code": 200,
                "data": [
                    {"symbol": "NSE:NIFTY50-INDEX", "expiry": "", "lp": 25607.2, "volume": 0},
                    {
                        "symbol": "NSE:NIFTY26DECFUT",
                        "expiry": "1798539000",
                        "lp": 25699.3,
                        "volume": 3216915,
                        "chp": -1.27,
                    },
                ],
            }

    monkeypatch.setattr(api, "_get_fyers", lambda: ChainSDK())
    fc = api.get_futures_chain("NIFTY")
    assert fc["status"] == "ok"
    assert fc["spot_price"] == 25607.2
    assert len(fc["contracts"]) == 1
    assert fc["contracts"][0]["symbol"] == "NSE:NIFTY26DECFUT"

    # Reject cash equities for SPAN margin
    eq_res = api.calculate_span_margin([{"symbol": "NSE:RELIANCE-EQ", "qty": 1, "side": "BUY"}])
    assert eq_res["status"] == "error"

    fake_client = MagicMock()
    ok_resp = MagicMock(status_code=200)
    ok_resp.json.return_value = {
        "s": "ok",
        "code": 200,
        "data": {"span": 156404.0, "expo": 33409.09, "total": 189813.09, "benefit": 0.0},
        "individual_info": {"101126": {"total": 189813.09}},
    }
    fake_client.post.return_value = ok_resp
    with patch("market.http_pool.get_shared_client", return_value=fake_client):
        span_res = api.calculate_span_margin(
            [{"symbol": "NSE:NIFTY26DECFUT", "qty": 65, "side": "BUY"}]
        )
    assert span_res["status"] == "ok"
    assert span_res["span"] == 156404.0
    assert span_res["total"] == 189813.09

    # 429 X-Retry-After-Ms trips CB with bounded retry cooldown
    rl_resp = MagicMock(status_code=429, text="Rate limited", headers={"X-Retry-After-Ms": "90000"})
    fake_client.post.return_value = rl_resp
    with patch("market.http_pool.get_shared_client", return_value=fake_client):
        fail_res = api.calculate_span_margin(
            [{"symbol": "NSE:NIFTY26DECFUT", "qty": 65, "side": "BUY"}]
        )
    assert fail_res["status"] == "error"
    assert cb.is_tripped() is True
    assert cb.get_diagnostics()["cooldown_seconds"] >= 90.0
    cb.reset()


def test_order_stream_reconnect_resync_tbt_switch_and_ws_lite_mode():
    """Verify OrderStream reconnect resync hook, TbtSocketWorker.switch_channels, and WebSocketManager lite_mode."""
    import threading
    from market.fyers_order_stream import FyersOrderStreamManager
    from market.fyers_tbt_manager import TbtSocketWorker
    from market.websocket import WebSocketManager

    # 1. OrderStream reconnect invokes on_reconnect_sync callback with is_reconnect=True
    osm = FyersOrderStreamManager()
    events = []
    done = threading.Event()

    def _sync_cb(is_reconn: bool):
        events.append(is_reconn)
        if is_reconn:
            done.set()

    osm.on_reconnect_sync(_sync_cb)
    osm._handle_connect()
    osm._handle_connect()
    assert done.wait(timeout=2.0)
    assert events == [False, True] or True in events

    # 2. TbtSocketWorker.switch_channels proxies cleanly
    worker = TbtSocketWorker(0, lambda: "tok", lambda s, d: None, lambda i, st: None)
    worker.connected = True
    worker.ws = MagicMock()
    assert worker.switch_channels(resume_channels={"2"}, pause_channels={"1"}) is True
    worker.ws.switchChannel.assert_called_once_with(resume_channels={"2"}, pause_channels={"1"})

    # 3. WebSocketManager lite_mode toggle
    ws_mgr = WebSocketManager(lite_mode=True)
    assert ws_mgr.lite_mode is True
    ws_mgr.set_lite_mode(False)
    assert ws_mgr.lite_mode is False


def test_rca_fyers_jwt_account_id_quotes_latch_and_exit_idempotency(monkeypatch):
    """Verify JWT fy_id account_id extraction, quotes_v2 session latch, and idempotent alert exits."""
    import base64
    from brokers.fyers import FyersAPI, _extract_fy_id_from_token

    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(b'{"fy_id":"FAK99999","sub":"user"}').decode().rstrip("=")
    fake_jwt = f"{header}.{payload}.sig"
    assert _extract_fy_id_from_token(fake_jwt) == "FAK99999"

    api = FyersAPI(app_id="TEST-100", secret_key="secret")
    api._fy_id = None
    api._profile = None
    api._access_token = fake_jwt
    assert api.account_id == "FAK99999"
    assert api.client_id == "FAK99999"

    # Second call after 403 WAF does not retry quotes_v2 in same session
    monkeypatch.setattr("brokers.fyers._fyers_rate_limiter.acquire", lambda **kw: True)
    v2_calls = 0

    class WafSDK:
        def quotes_v2(self, p):
            nonlocal v2_calls
            v2_calls += 1
            return {"s": "error", "code": 403, "message": "Bad request"}

        def quotes(self, p):
            return {"s": "ok", "d": [{"n": "NSE:RELIANCE-EQ", "s": "ok", "v": {"lp": 1380.0}}]}

    monkeypatch.setattr(api, "_get_fyers", lambda: WafSDK())
    api.get_quote(["NSE:RELIANCE-EQ"])
    api.get_quote(["NSE:RELIANCE-EQ"])
    assert v2_calls == 1

    # Duplicate terminal exit on archived alert short-circuits before calling record_terminal_forward_outcome
    from engine.auto_alert_engine import AutoAlertEngine

    eng = AutoAlertEngine.__new__(AutoAlertEngine)
    import threading

    eng._lock = threading.RLock()
    archived_alert = MagicMock(
        alert_id="aa-test-crude-20261127",
        is_active=False,
        is_archived=True,
        stage="TIME_STOP_EXIT",
        is_invalidated=False,
    )
    assert eng._handle_alert_exit(archived_alert, "Velocity stagnation reached") is False
