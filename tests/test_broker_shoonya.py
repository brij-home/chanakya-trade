"""Deterministic Shoonya adapter tests; no broker credentials or network needed."""

from __future__ import annotations

import json

import pytest

from brokers import shoonya
from brokers.shoonya import ShoonyaAPI


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_missing_credentials_fails_closed(monkeypatch):
    for key in (
        "SHOONYA_USER_ID",
        "SHOONYA_PASSWORD",
        "SHOONYA_API_KEY",
        "SHOONYA_VENDOR_CODE",
        "SHOONYA_TOTP_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    broker = ShoonyaAPI()
    with pytest.raises(RuntimeError, match="credentials are incomplete"):
        broker.complete_login(two_fa="123456")
    assert broker.is_authenticated() is False


def test_login_persists_session_without_fabricating_data(tmp_path, monkeypatch):
    token_file = tmp_path / "shoonya.json"
    monkeypatch.setattr(shoonya, "TOKEN_FILE", token_file)
    broker = ShoonyaAPI(user_id="U1", password="pw", api_key="AK", vendor_code="VC")
    requests = []

    def post(url, data):
        requests.append((url, data))
        return _Response(
            {
                "stat": "Ok",
                "susertoken": "session",
                "actid": "A1",
                "uname": "Trader",
                "email": "t@example.com",
            }
        )

    monkeypatch.setattr(broker._client, "post", post)
    profile = broker.complete_login(two_fa="123456")
    assert profile.broker == "SHOONYA"
    assert broker.is_authenticated() is True
    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["token"] == "session"
    assert saved["account_id"] == "A1"
    assert requests and "QuickAuth" in requests[0][0]
    assert "jKey" not in requests[0][1]


def test_noren_list_response_is_normalized():
    rows = ShoonyaAPI._rows(
        [{"stat": "Ok", "tsym": "ABC-EQ"}, {"stat": "Not_Ok", "emsg": "ignored"}], "values"
    )
    assert rows == [{"stat": "Ok", "tsym": "ABC-EQ"}]
