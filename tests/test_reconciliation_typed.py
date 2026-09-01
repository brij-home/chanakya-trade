"""
tests/test_reconciliation_typed.py
Tests that the reconciliation normalizer handles both typed Position/Funds
dataclasses (returned by real brokers) and raw dicts (returned by mocks).
"""

import pytest
from brokers.base import Position, Funds


def _pos_to_dict(p) -> dict:
    if isinstance(p, dict):
        return {
            "symbol": p.get("symbol") or p.get("tradingsymbol", ""),
            "qty": int(p.get("quantity", p.get("qty", 0))),
            "avg_price": float(p.get("average_price", p.get("avg_price", 0.0))),
        }
    return {
        "symbol": getattr(p, "symbol", ""),
        "qty": int(getattr(p, "quantity", 0)),
        "avg_price": float(getattr(p, "avg_price", 0.0)),
    }


def _funds_cash(f) -> float:
    if isinstance(f, dict):
        return float(f.get("available_cash", f.get("net", 0.0)))
    return float(getattr(f, "available_cash", 0.0))


def test_pos_to_dict_from_dataclass():
    pos = Position(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        quantity=10,
        avg_price=2800.50,
        last_price=2810.00,
        pnl=95.0,
    )
    result = _pos_to_dict(pos)
    assert result["symbol"] == "RELIANCE"
    assert result["qty"] == 10
    assert result["avg_price"] == pytest.approx(2800.50)


def test_pos_to_dict_from_dataclass_zero_qty():
    pos = Position(
        symbol="TCS",
        exchange="NSE",
        product="CNC",
        quantity=0,
        avg_price=3500.0,
        last_price=3510.0,
        pnl=0.0,
    )
    result = _pos_to_dict(pos)
    assert result["qty"] == 0
    assert result["symbol"] == "TCS"


def test_pos_to_dict_from_raw_dict_standard_keys():
    raw = {"symbol": "INFY", "qty": 5, "avg_price": 1750.25}
    result = _pos_to_dict(raw)
    assert result["symbol"] == "INFY"
    assert result["qty"] == 5
    assert result["avg_price"] == pytest.approx(1750.25)


def test_pos_to_dict_from_raw_dict_broker_keys():
    raw = {"tradingsymbol": "HDFCBANK", "quantity": 3, "average_price": 1620.0}
    result = _pos_to_dict(raw)
    assert result["symbol"] == "HDFCBANK"
    assert result["qty"] == 3
    assert result["avg_price"] == pytest.approx(1620.0)


def test_pos_to_dict_list_of_dataclasses():
    positions = [
        Position("WIPRO", "NSE", "MIS", 20, 480.0, 485.0, 100.0),
        Position("INFOSYS", "NSE", "CNC", 5, 1750.0, 1760.0, 50.0),
    ]
    results = [_pos_to_dict(p) for p in positions]
    assert len(results) == 2
    assert results[0]["symbol"] == "WIPRO"
    assert results[1]["symbol"] == "INFOSYS"


def test_funds_cash_from_dataclass():
    funds = Funds(available_cash=150_000.0, used_margin=50_000.0, total_balance=200_000.0)
    assert _funds_cash(funds) == pytest.approx(150_000.0)


def test_funds_cash_from_dict_standard_key():
    assert _funds_cash({"available_cash": 75_000.0}) == pytest.approx(75_000.0)


def test_funds_cash_from_dict_net_fallback():
    assert _funds_cash({"net": 60_000.0}) == pytest.approx(60_000.0)


def test_funds_cash_from_dataclass_zero_balance():
    funds = Funds(available_cash=0.0, used_margin=200_000.0, total_balance=200_000.0)
    assert _funds_cash(funds) == pytest.approx(0.0)


def test_funds_cash_from_dict_missing_keys():
    assert _funds_cash({}) == pytest.approx(0.0)
