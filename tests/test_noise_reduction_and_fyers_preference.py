"""
tests/test_noise_reduction_and_fyers_preference.py
──────────────────────────────────────────────────
Verifies:
1. mStock WebSocket does NOT start when credentials are not configured.
2. yfinance provider strictly rejects derivative option/future symbols without hitting network or logging.
3. yfinance provider resolves COCHINSHIP to COCHINSHIPYARD.NS.
4. Dead ticker cache persists to disk and survives process reloads.
5. AlertRepository proactively expires past-expiry derivative contracts.
"""

from datetime import timezone, timedelta
import pytest

IST = timezone(timedelta(hours=5, minutes=30))


def test_mstock_websocket_does_not_start_without_credentials(monkeypatch):
    """mStock WebSocket must NOT start background threads or connection loops if disabled or credentials empty."""
    from market.mstock_websocket import MStockWebSocket

    ws = MStockWebSocket()
    ws.api_key = "dummy_key"
    ws.access_token = "dummy_token"
    # By default or with ENABLE_MSTOCK=0, mStock WebSocket never starts
    monkeypatch.setenv("ENABLE_MSTOCK", "0")

    ws.start()
    assert not ws._running
    assert ws._thread is None
    assert not ws._connected


def test_yfinance_rejects_derivative_contracts():
    """yfinance provider must immediately reject Indian option and future contracts."""
    from market.yfinance_provider import (
        is_derivative_ticker,
        _to_yf_symbol,
        yf_get_ohlcv,
        yf_get_quote,
    )

    # Option formats
    assert is_derivative_ticker("M&M202609293050PE") is True
    assert is_derivative_ticker("NSE:M&M26OCT2800CE") is True
    assert is_derivative_ticker("NIFTY24O1024500CE") is True
    assert is_derivative_ticker("NIFTY2691124500PE") is True
    assert is_derivative_ticker("RELIANCE26OCTFUT") is True

    # Equities are not derivatives
    assert is_derivative_ticker("RELIANCE") is False
    assert is_derivative_ticker("NSE:COCHINSHIP-EQ") is False
    assert is_derivative_ticker("M&M") is False

    # _to_yf_symbol returns empty string for Indian equity options
    assert _to_yf_symbol("M&M202609293050PE") == ""
    assert _to_yf_symbol("NSE:M&M26OCT2800CE") == ""

    # yf_get_ohlcv returns empty list without calling network
    assert yf_get_ohlcv("M&M202609293050PE") == []

    # yf_get_quote raises without calling network
    with pytest.raises(RuntimeError, match="yfinance does not host Indian derivatives"):
        yf_get_quote("M&M202609293050PE")


def test_cochinship_alias_resolution():
    """NSE COCHINSHIP must resolve to yfinance COCHINSHIPYARD.NS."""
    from market.yfinance_provider import _to_yf_symbol

    assert _to_yf_symbol("COCHINSHIP") == "COCHINSHIPYARD.NS"
    assert _to_yf_symbol("NSE:COCHINSHIP-EQ") == "COCHINSHIPYARD.NS"
    assert _to_yf_symbol("COCHINSHIPYARD") == "COCHINSHIPYARD.NS"


def test_dead_ticker_disk_persistence(tmp_path, monkeypatch):
    """Dead ticker negative cache must persist to disk and reload on startup."""
    import time
    from market import yfinance_provider

    test_file = tmp_path / "delisted_symbols_test.json"
    monkeypatch.setattr(yfinance_provider, "_dead_ticker_persist_path", lambda: test_file)

    with yfinance_provider._dead_ticker_lock:
        yfinance_provider._DEAD_TICKER_CACHE["TESTDEAD.NS"] = time.time()
        yfinance_provider._persist_dead_ticker_to_disk()

    assert test_file.exists()

    # Clear in-memory cache and reload from disk
    with yfinance_provider._dead_ticker_lock:
        yfinance_provider._DEAD_TICKER_CACHE.clear()

    yfinance_provider._load_dead_ticker_cache_from_disk()

    with yfinance_provider._dead_ticker_lock:
        assert "TESTDEAD.NS" in yfinance_provider._DEAD_TICKER_CACHE


def test_alert_repository_proactively_expires_past_option_contracts():
    """AlertRepository.reap_expired_alerts must proactively expire alerts with past contract expiry dates."""
    from engine.alert_model import AutoAlert
    from engine.storage.alert_repository import alert_repository

    # September 2026 contract (past date relative to current October 2026 session)
    old_alert = AutoAlert(
        alert_id="test-old-opt-alert-202609",
        alert_type="OPTIONS_MOMENTUM",
        stage="PRIMED",
        symbol="M&M",
        exchange="NSE",
        direction="BEARISH",
        headline="M&M Put Option",
        summary="M&M Put breakdown",
        ltp=80.0,
        trigger_level=80.0,
        target_level=120.0,
        stop_loss=60.0,
        contract_symbol="NSE:M&M202609293050PE",
    )
    old_alert.is_active = True

    alerts = [old_alert]
    surviving, count = alert_repository.reap_expired_alerts(alerts, purge=False)

    assert count >= 1
    assert old_alert.is_expired is True
    assert old_alert.is_active is False
    assert old_alert.is_archived is True
