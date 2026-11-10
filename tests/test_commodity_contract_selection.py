"""MCX option grids must be built from published contracts, never a calendar guess.

Regression cover for the F&O desk roadmap gap: get_default_core_grid and
get_active_commodity_grid previously assembled CRUDEOIL option tickers from a
month suffix, a hardcoded 6500 fallback and an assumed strike step. Those symbols
can be unlisted, which the broker rejects and which corrupts subscription state.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from config.constants import IST
from market.contract_selection import (
    front_month_commodity_future,
    get_commodity_option_contracts,
    get_commodity_option_grid,
)
from market.instruments import canonical_symbol

AS_OF = datetime(2026, 11, 8, 20, 0, tzinfo=IST)
EXPIRY = date(2026, 11, 17)
EXPIRY_EPOCH = str(datetime(2026, 11, 17, 19, 30, tzinfo=IST).timestamp())


def _row(
    symbol: str,
    *,
    underlying: str = "CRUDEOIL",
    option_type: str = "CE",
    strike: float = 6500.0,
    expiry_epoch: str = EXPIRY_EPOCH,
    trade_status: int = 1,
    token: str = "1120261117582829",
) -> dict:
    return {
        "symTicker": symbol,
        "underSym": underlying,
        "optType": option_type,
        "strikePrice": strike,
        "expiryDate": expiry_epoch,
        "minLotSize": 1,
        "tickSize": 0.1,
        "fyToken": token,
        "tradeStatus": trade_status,
    }


def _master() -> dict:
    rows = {
        "MCX:CRUDEOIL26NOVFUT": {
            "underSym": "CRUDEOIL",
            "optType": "XX",
            "strikePrice": -1.0,
            "expiryDate": EXPIRY_EPOCH,
            "minLotSize": 1,
            "tickSize": 0.1,
            "fyToken": "1120261117000001",
            "tradeStatus": 1,
        },
        "MCX:CRUDEOIL26DECFUT": {
            "underSym": "CRUDEOIL",
            "optType": "XX",
            "strikePrice": -1.0,
            "expiryDate": str(datetime(2026, 12, 17, 19, 30, tzinfo=IST).timestamp()),
            "minLotSize": 1,
            "tickSize": 0.1,
            "fyToken": "1120261217000001",
            "tradeStatus": 1,
        },
    }
    for strike in (6400.0, 6450.0, 6500.0, 6550.0, 6600.0):
        for side in ("CE", "PE"):
            symbol = f"MCX:CRUDEOIL26NOV{int(strike)}{side}"
            rows[symbol] = _row(symbol, option_type=side, strike=strike)
    # Inactive, expired and same-day contracts must never enter a new grid.
    rows["MCX:CRUDEOIL26NOV6700CE"] = _row("MCX:CRUDEOIL26NOV6700CE", strike=6700.0, trade_status=0)
    rows["MCX:CRUDEOIL26NOV6700PE"] = _row(
        "MCX:CRUDEOIL26NOV6700PE", option_type="PE", strike=6700.0, trade_status=0
    )
    rows["MCX:CRUDEOIL26OCT6000CE"] = _row(
        "MCX:CRUDEOIL26OCT6000CE",
        strike=6000.0,
        expiry_epoch=str(datetime(2026, 10, 19, 19, 30, tzinfo=IST).timestamp()),
    )
    rows["MCX:CRUDEOIL26NOV6000CE"] = _row(
        "MCX:CRUDEOIL26NOV6000CE",
        strike=6000.0,
        expiry_epoch=str(datetime(2026, 11, 8, 19, 30, tzinfo=IST).timestamp()),
    )
    return rows


def _quote(
    price: float = 6505.0,
    *,
    age_seconds: float = 0.0,
    provider: str = "FYERS",
    base: datetime = AS_OF,
):
    from brokers.base import Quote

    received = base - timedelta(seconds=age_seconds)
    return Quote(
        symbol="MCX:CRUDEOIL26NOVFUT",
        last_price=price,
        source="REST",
        provider=provider,
        data_state="LIVE",
        received_at=received.isoformat(),
    )


def test_contracts_are_master_listed_only():
    contracts = get_commodity_option_contracts("CRUDEOIL", as_of=AS_OF, records=_master())

    symbols = {c.symbol for c in contracts}
    assert "MCX:CRUDEOIL26NOV6500CE" in symbols
    assert "MCX:CRUDEOIL26NOV6500PE" in symbols
    # Inactive, expired and same-day-expiry rows are excluded.
    assert "MCX:CRUDEOIL26NOV6700CE" not in symbols
    assert "MCX:CRUDEOIL26OCT6000CE" not in symbols
    assert "MCX:CRUDEOIL26NOV6000CE" not in symbols
    assert all(c.underlying == canonical_symbol("CRUDEOIL") for c in contracts)


def test_front_month_future_uses_nearest_listed_expiry():
    assert front_month_commodity_future("CRUDEOIL", as_of=AS_OF, records=_master()) == (
        "MCX:CRUDEOIL26NOVFUT"
    )
    expired_only = {
        "MCX:CRUDEOIL26OCTFUT": {
            "underSym": "CRUDEOIL",
            "optType": "XX",
            "strikePrice": -1.0,
            "expiryDate": str(datetime(2026, 10, 19, 19, 30, tzinfo=IST).timestamp()),
            "fyToken": "1",
            "tradeStatus": 1,
        }
    }
    assert front_month_commodity_future("CRUDEOIL", as_of=AS_OF, records=expired_only) is None


def test_grid_selects_paired_listed_strikes(monkeypatch):
    from market import quotes as quotes_module

    monkeypatch.setattr("market.symbol_master.load_master", lambda *a, **k: _master())
    monkeypatch.setattr(
        quotes_module, "get_quote", lambda instruments: {"MCX:CRUDEOIL26NOVFUT": _quote()}
    )

    grid = get_commodity_option_grid("CRUDEOIL", strikes_per_side=1, as_of=AS_OF)

    assert grid == [
        "MCX:CRUDEOIL26NOV6450CE",
        "MCX:CRUDEOIL26NOV6450PE",
        "MCX:CRUDEOIL26NOV6500CE",
        "MCX:CRUDEOIL26NOV6500PE",
        "MCX:CRUDEOIL26NOV6550CE",
        "MCX:CRUDEOIL26NOV6550PE",
    ]


@pytest.mark.parametrize(
    "quote",
    [
        None,
        _quote(age_seconds=120.0),
        _quote(provider="MOCK"),
        _quote(price=0.0),
    ],
)
def test_grid_fails_closed_without_usable_quote(monkeypatch, quote):
    from market import quotes as quotes_module

    monkeypatch.setattr("market.symbol_master.load_master", lambda *a, **k: _master())
    monkeypatch.setattr(
        quotes_module,
        "get_quote",
        lambda instruments: {} if quote is None else {"MCX:CRUDEOIL26NOVFUT": quote},
    )

    assert get_commodity_option_grid("CRUDEOIL", as_of=AS_OF) == []


def test_grid_fails_closed_when_master_unavailable(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("master snapshot unavailable")

    monkeypatch.setattr("market.symbol_master.load_master", _raise)
    assert get_commodity_option_grid("CRUDEOIL", as_of=AS_OF) == []


def test_active_grid_contains_only_listed_options(monkeypatch):
    from market import quotes as quotes_module
    from market import ws_subscription_manager as module

    master = _master()
    monkeypatch.setattr("market.symbol_master.load_master", lambda *a, **k: master)
    monkeypatch.setattr(
        quotes_module,
        "get_quote",
        lambda instruments: {"MCX:CRUDEOIL26NOVFUT": _quote(base=datetime.now(IST))},
    )
    monkeypatch.setattr(
        "brokers.fyers._resolve_commodity_contract",
        lambda name, ref_time=None: f"MCX:{name}26NOVFUT",
    )
    monkeypatch.setattr(
        "brokers.fyers._resolve_currency_contract", lambda name: f"NSE:{name}26NOVFUT"
    )

    grid = module.get_active_commodity_grid()
    options = [s for s in grid if s.endswith(("CE", "PE"))]
    assert options, "listed paired strikes should be seeded"
    assert set(options) <= set(master)
    assert not any("6525" in s for s in options)


def test_historical_reference_time_never_fabricates_options(monkeypatch):
    from market import ws_subscription_manager as module

    monkeypatch.setattr(
        "brokers.fyers._resolve_commodity_contract",
        lambda name, ref_time=None: f"MCX:{name}26MAYFUT",
    )
    monkeypatch.setattr(
        "brokers.fyers._resolve_currency_contract", lambda name: f"NSE:{name}26MAYFUT"
    )

    grid = module.get_active_commodity_grid(ref_time=datetime(2026, 5, 16, 10, 0, tzinfo=IST))
    assert grid
    assert not [s for s in grid if s.endswith(("CE", "PE"))]
