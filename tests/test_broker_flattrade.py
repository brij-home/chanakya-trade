"""Deterministic Flattrade adapter tests; no broker credentials or network needed."""

from __future__ import annotations

import json

import pytest

from brokers import flattrade
from brokers.flattrade import FlattradeAPI


class _Response:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text or (
            json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        )

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _isolate_flattrade_token(tmp_path, monkeypatch):
    test_token_file = tmp_path / "flattrade.json"
    monkeypatch.setattr(flattrade, "TOKEN_FILE", test_token_file)


def test_missing_credentials_fails_closed(monkeypatch):
    for key in (
        "FLATTRADE_USER_ID",
        "FLATTRADE_PASSWORD",
        "FLATTRADE_TOTP_SECRET",
        "FLATTRADE_API_KEY",
        "FLATTRADE_API_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    broker = FlattradeAPI()
    with pytest.raises(RuntimeError, match="Flattrade credentials incomplete"):
        broker.complete_login(two_fa="123456")
    assert broker.is_authenticated() is False


def test_missing_totp_secret_fails_closed(monkeypatch):
    broker = FlattradeAPI(
        user_id="FT100",
        password="secretpassword",
        api_key="apikey123",
        api_secret="apisecret456",
        totp_secret="",
    )
    with pytest.raises(RuntimeError, match="requires FLATTRADE_TOTP_SECRET"):
        broker.complete_login()
    assert broker.is_authenticated() is False


def test_headless_login_persists_session_and_normalizes_profile(tmp_path, monkeypatch):
    token_file = tmp_path / "flattrade.json"
    monkeypatch.setattr(flattrade, "TOKEN_FILE", token_file)
    broker = FlattradeAPI(
        user_id="FT100",
        password="pwd",
        totp_secret="JBSWY3DPEHPK3PXP",
        api_key="FT_API_KEY",
        api_secret="FT_API_SECRET",
    )

    posted = []

    def mock_httpx_post(url, **kwargs):
        posted.append((url, kwargs))
        if "auth/session" in url:
            return _Response({}, text="test-sid-token-xyz")
        elif "ftauth" in url:
            return _Response(
                {
                    "RedirectURL": "https://httpbin.org/get?code=auth_code_999&client=FT100",
                }
            )
        elif "trade/apitoken" in url:
            return _Response(
                {
                    "stat": "Ok",
                    "token": "valid_session_token_12345",
                }
            )
        raise ValueError(f"Unexpected url: {url}")

    monkeypatch.setattr(flattrade.httpx, "post", mock_httpx_post)

    # Mock _post for profile query
    def mock_internal_post(endpoint, payload=None):
        if endpoint == "UserDetails":
            return {
                "stat": "Ok",
                "actid": "FT100",
                "uname": "Quant Trader",
                "email": "trader@example.com",
            }
        return {"stat": "Ok"}

    monkeypatch.setattr(broker, "_post", mock_internal_post)

    profile = broker.complete_login()
    assert profile.user_id == "FT100"
    assert profile.broker == "FLATTRADE"
    assert profile.name == "Quant Trader"
    assert profile.email == "trader@example.com"
    assert broker.is_authenticated() is True

    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["token"] == "valid_session_token_12345"
    assert saved["user_id"] == "FT100"
    assert len(posted) == 3


def test_login_rejected_by_authapi(monkeypatch):
    broker = FlattradeAPI(
        user_id="FT100",
        password="pwd",
        totp_secret="JBSWY3DPEHPK3PXP",
        api_key="FT_API_KEY",
        api_secret="FT_API_SECRET",
    )

    def mock_httpx_post(url, **kwargs):
        if "auth/session" in url:
            return _Response({}, text="sid-123")
        elif "ftauth" in url:
            return _Response({"emsg": "Invalid TOTP or credentials"})
        raise ValueError(f"Unexpected url: {url}")

    monkeypatch.setattr(flattrade.httpx, "post", mock_httpx_post)

    with pytest.raises(RuntimeError, match="Invalid TOTP or credentials"):
        broker.complete_login()


def test_get_quote_and_positions_normalization(monkeypatch):
    broker = FlattradeAPI(user_id="FT100", api_key="AK", api_secret="AS")
    broker._token = "tok"
    broker._token_date = flattrade._today_ist()

    def mock_post(endpoint, payload=None):
        if endpoint == "SearchScrip":
            return {
                "stat": "Ok",
                "values": [
                    {
                        "exch": "NFO",
                        "token": "45678",
                        "tsym": "NIFTY24DEC24200CE",
                        "ls": "50",
                        "ti": "0.05",
                    }
                ],
            }
        elif endpoint == "GetQuotes":
            return {
                "stat": "Ok",
                "lp": "24200.50",
                "c": "24100.00",
                "o": "24150.00",
                "h": "24250.00",
                "l": "24120.00",
                "v": "500000",
                "oi": "120000",
                "bp1": "24200.00",
                "sp1": "24201.00",
            }
        elif endpoint == "PositionBook":
            return [
                {
                    "stat": "Ok",
                    "tsym": "NIFTY24DEC24200CE",
                    "exch": "NFO",
                    "prd": "M",
                    "netqty": "50",
                    "rpnl": "1500.00",
                    "urmtom": "800.00",
                    "netavgprc": "120.50",
                    "lp": "136.50",
                }
            ]
        elif endpoint == "Limits":
            return {
                "stat": "Ok",
                "cash": "100000.00",
                "payin": "0.00",
                "marginused": "25000.00",
            }
        return {"stat": "Ok"}

    monkeypatch.setattr(broker, "_post", mock_post)

    quotes = broker.get_quote(["NFO:NIFTY24DEC24200CE"])
    assert "NFO:NIFTY24DEC24200CE" in quotes
    quote = quotes["NFO:NIFTY24DEC24200CE"]
    assert quote.symbol == "NFO:NIFTY24DEC24200CE"
    assert quote.ltp == 24200.50
    assert quote.change == 100.50
    assert quote.open == 24150.00

    positions = broker.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.symbol == "NIFTY24DEC24200CE"
    assert pos.quantity == 50
    assert pos.product == "NRML"
    assert pos.avg_price == 120.50
    assert pos.last_price == 136.50
    assert pos.pnl == 2300.00

    funds = broker.get_funds()
    assert funds.available_cash == 100000.00
    assert funds.used_margin == 25000.00


def test_normalize_flattrade_tick():
    from market.streaming import normalize_flattrade_tick

    raw_tick = {
        "e": "NSE",
        "tk": "26000",
        "ts": "Nifty 50",
        "lp": "25010.50",
        "bp1": "25010.00",
        "sp1": "25011.00",
        "v": "1250000",
        "oi": "450000",
    }
    event = normalize_flattrade_tick(raw_tick)
    assert event is not None
    assert event.provider == "flattrade"
    assert event.provider_symbol == "Nifty 50"
    assert event.last_price == 25010.50
    assert event.bid == 25010.00
    assert event.ask == 25011.00
    assert event.volume == 1250000
    assert event.oi == 450000
    assert event.data_state == "LIVE"
    assert event.source == "STREAM"


def test_normalize_flattrade_tick_with_atp():
    from market.streaming import normalize_flattrade_tick

    raw_tick = {
        "e": "NSE",
        "tk": "26000",
        "ts": "Nifty 50",
        "lp": "25010.50",
        "ap": "25005.20",
        "v": "100",
    }
    event = normalize_flattrade_tick(raw_tick)
    assert event is not None
    assert event.atp == 25005.20


def test_flattrade_websocket_subscription_batching(monkeypatch):
    broker = FlattradeAPI(user_id="FT100", api_key="AK", api_secret="AS")
    sent_payloads = []

    class DummyWS:
        def send(self, payload):
            sent_payloads.append(json.loads(payload))

    dummy_ws = DummyWS()
    # 60 tokens should be split into 3 chunks: 25, 25, 10
    tokens = [f"NSE|{i}" for i in range(1, 61)]
    broker._send_subscription_batches(dummy_ws, tokens, task="t", batch_size=25)

    assert len(sent_payloads) == 3
    assert sent_payloads[0]["t"] == "t"
    assert len(sent_payloads[0]["k"].split("#")) == 25
    assert len(sent_payloads[1]["k"].split("#")) == 25
    assert len(sent_payloads[2]["k"].split("#")) == 10
