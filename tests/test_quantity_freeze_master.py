from __future__ import annotations

import pytest

from market import symbol_master
from engine.smart_order_router import get_exchange_freeze_limit


def _row(
    symbol: str,
    underlying: str,
    quantity: str,
    *,
    lot_size: int = 25,
    status: int = 1,
) -> dict:
    return {
        "symTicker": symbol,
        "underSym": underlying,
        "qtyFreeze": quantity,
        "minLotSize": lot_size,
        "tradeStatus": status,
        "lastUpdate": "2026-10-30",
    }


def test_exact_contract_freeze_comes_from_fresh_exchange_master(monkeypatch):
    records = {
        "NSE:NIFTY26NOV25000CE": _row("NSE:NIFTY26NOV25000CE", "NIFTY", "1755"),
    }
    calls = []

    def load(name, **kwargs):
        calls.append((name, kwargs))
        return records

    monkeypatch.setattr(symbol_master, "load_master", load)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())
    info = symbol_master.get_quantity_freeze_info("NFO:NIFTY26NOV25000CE")

    assert info["quantity"] == 1755
    assert info["lot_size"] == 25
    assert info["source"] == "FYERS_PUBLISHED_EXCHANGE_MASTER"
    assert calls == [("NSE_FO", {"offline_fallback": False})]


def test_underlying_only_freeze_requires_one_unambiguous_active_value(monkeypatch):
    records = {
        "NSE:NIFTY26NOVFUT": _row("NSE:NIFTY26NOVFUT", "NIFTY", "1755"),
        "NSE:NIFTY26NOV25000CE": _row("NSE:NIFTY26NOV25000CE", "NIFTY", "1755"),
        "NSE:NIFTY26NOV25100PE": _row("NSE:NIFTY26NOV25100PE", "NIFTY", "1755"),
    }
    monkeypatch.setattr(symbol_master, "load_master", lambda *args, **kwargs: records)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())

    info = symbol_master.get_quantity_freeze_info("NIFTY")
    assert info["quantity"] == 1755
    assert info["symbol"] == "NSE:NIFTY"

    records["NSE:NIFTY26NOV25100PE"] = _row("NSE:NIFTY26NOV25100PE", "NIFTY", "1800")
    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        symbol_master.get_quantity_freeze_info("NIFTY")


def test_inactive_or_missing_contract_never_uses_another_contract_limit(monkeypatch):
    records = {
        "NSE:NIFTY26NOV25000CE": _row("NSE:NIFTY26NOV25000CE", "NIFTY", "1755", status=0),
        "NSE:NIFTY26NOVFUT": _row("NSE:NIFTY26NOVFUT", "NIFTY", "1755"),
    }
    monkeypatch.setattr(symbol_master, "load_master", lambda *args, **kwargs: records)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())

    with pytest.raises(RuntimeError, match="No unambiguous active published quantity freeze"):
        symbol_master.get_quantity_freeze_info("NSE:NIFTY26NOV25000CE")
    with pytest.raises(RuntimeError, match="absent from the current"):
        symbol_master.get_quantity_freeze_info("NSE:NIFTY26DEC25000CE")


def test_stale_master_failure_fails_closed(monkeypatch):
    def fail(name, **kwargs):
        assert kwargs == {"offline_fallback": False}
        raise RuntimeError("current master unavailable")

    monkeypatch.setattr(symbol_master, "load_master", fail)
    with pytest.raises(RuntimeError, match="current master unavailable"):
        symbol_master.get_quantity_freeze_info("NSE:NIFTY26NOV25000CE")


def test_execution_router_rejects_stale_or_mismatched_lot_size(monkeypatch):
    records = {
        "NSE:NIFTY26NOV25000CE": _row("NSE:NIFTY26NOV25000CE", "NIFTY", "1755", lot_size=65),
    }
    monkeypatch.setattr(symbol_master, "load_master", lambda *args, **kwargs: records)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())

    with pytest.raises(RuntimeError, match="does not match current published lot size"):
        get_exchange_freeze_limit("NFO:NIFTY26NOV25000CE", lot_size=50)
    assert get_exchange_freeze_limit("NFO:NIFTY26NOV25000CE", lot_size=65) == 1755


def test_underlying_lot_size_must_be_unambiguous(monkeypatch):
    records = {
        "NSE:NIFTY26NOVFUT": _row("NSE:NIFTY26NOVFUT", "NIFTY", "1755", lot_size=65),
        "NSE:NIFTY26NOV25000CE": _row("NSE:NIFTY26NOV25000CE", "NIFTY", "1755", lot_size=25),
    }
    monkeypatch.setattr(symbol_master, "load_master", lambda *args, **kwargs: records)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())

    with pytest.raises(RuntimeError, match="lot size is missing or ambiguous"):
        symbol_master.get_quantity_freeze_info("NIFTY")


def test_bse_contract_reads_bse_derivative_master(monkeypatch):
    records = {
        "BSE:SENSEX26NOVFUT": _row("BSE:SENSEX26NOVFUT", "SENSEX", "500"),
    }
    calls = []

    def load(name, **kwargs):
        calls.append(name)
        return records

    monkeypatch.setattr(symbol_master, "load_master", load)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())

    assert symbol_master.get_quantity_freeze_info("BFO:SENSEX26NOVFUT")["quantity"] == 500
    assert calls == ["BSE_FO"]


def test_bse_segment_hint_never_routes_contract_to_nse_master(monkeypatch):
    calls = []

    def load(name, **kwargs):
        calls.append(name)
        return {"BSE:SENSEX26NOVFUT": _row("BSE:SENSEX26NOVFUT", "SENSEX", "500")}

    monkeypatch.setattr(symbol_master, "load_master", load)
    monkeypatch.setattr(symbol_master, "_DEGRADED_MASTERS", set())

    result = symbol_master.get_quantity_freeze_info("BSE:SENSEX26NOVFUT", segment="FUTURES")
    assert result["quantity"] == 500
    assert calls == ["BSE_FO"]
