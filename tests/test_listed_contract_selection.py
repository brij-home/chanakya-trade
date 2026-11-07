"""Contract subscriptions require observed price evidence and exact master rows."""

from datetime import datetime, date, timedelta
import io
import json
from unittest.mock import Mock

import pytest

from brokers.base import Quote
from config.constants import IST
from market.contract_selection import (
    contracts_from_master,
    fresh_underlying_price,
    paired_option_grid,
    get_subscription_option_grid,
)

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=IST)


def _row(
    strike=25000,
    side="CE",
    expiry=date(2026, 11, 3),
    underlying="NIFTY",
    exchange="NSE",
    **overrides,
):
    symbol = f"{exchange}:{underlying}{expiry:%y%m%d}{strike}{side}"
    row = {
        "symTicker": symbol,
        "underSym": underlying,
        "optType": side,
        "expiryDate": int(
            datetime.combine(expiry, datetime.min.time(), IST)
            .replace(hour=15, minute=40)
            .timestamp()
        ),
        "strikePrice": strike,
        "minLotSize": 65,
        "tickSize": 0.05,
        "fyToken": "123456",
        "tradeStatus": 1,
    }
    row.update(overrides)
    return symbol, row


def _quote(**kwargs):
    values = {
        "symbol": "NSE:NIFTY 50",
        "last_price": 25010,
        "provider": "FYERS",
        "source": "STREAM",
        "data_state": "LIVE",
        "received_at": NOW.isoformat(),
    }
    values.update(kwargs)
    return Quote(**values)


def test_actual_nonuniform_strikes_and_expiries_preserve_both_sides():
    rows = dict(_row(strike, side) for strike in (24950, 25000, 25100) for side in ("CE", "PE"))
    rows.update([_row(25050, "CE")])  # No listed PE: do not manufacture it.
    rows.update([_row(25000, "PE", underlying="BANKNIFTY")])
    contracts = contracts_from_master(rows, "NIFTY", exchange="NSE", as_of=NOW)
    grid = paired_option_grid(contracts, 25010, strikes_per_side=1)
    assert len(grid) == 6
    assert set(grid) <= rows.keys()
    assert not any("25050" in symbol or "BANKNIFTY" in symbol for symbol in grid)
    assert sum(symbol.endswith("CE") for symbol in grid) == sum(
        symbol.endswith("PE") for symbol in grid
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"tradeStatus": 0},
        {"minLotSize": 0},
        {"minLotSize": 1.5},
        {"tickSize": float("nan")},
        {"fyToken": ""},
        {"expiryDate": "bad"},
        {"symTicker": "NSE:WRONG"},
    ],
)
def test_incomplete_or_nontradable_master_rows_are_excluded(overrides):
    row = _row(**overrides)
    assert contracts_from_master(dict([row]), "NIFTY", exchange="NSE", as_of=NOW) == []


def test_expiry_cutoff_and_exchange_boundaries_are_not_guessed():
    rows = dict([_row(exchange="BSE", underlying="SENSEX", strike=81000)])
    assert contracts_from_master(rows, "SENSEX", exchange="NSE", as_of=NOW) == []
    after_close = datetime(2026, 11, 3, 15, 41, tzinfo=IST)
    assert contracts_from_master(rows, "SENSEX", exchange="BSE", as_of=after_close) == []
    with pytest.raises(ValueError, match="aware"):
        contracts_from_master(rows, "SENSEX", exchange="BSE", as_of=NOW.replace(tzinfo=None))


def test_listed_expiring_monthly_pair_remains_available_before_exchange_cutoff():
    expiry = date(2026, 10, 29)
    rows = dict(
        _row(strike=81500, side=side, expiry=expiry, underlying="SENSEX", exchange="BSE")
        for side in ("CE", "PE")
    )
    before_close = datetime(2026, 10, 29, 13, 30, tzinfo=IST)
    contracts = contracts_from_master(rows, "SENSEX", exchange="BSE", as_of=before_close)
    assert {contract.symbol for contract in contracts} == set(rows)
    assert set(paired_option_grid(contracts, 81500, strikes_per_side=0)) == set(rows)

    after_close = datetime(2026, 10, 29, 15, 41, tzinfo=IST)
    assert contracts_from_master(rows, "SENSEX", exchange="BSE", as_of=after_close) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"last_price": 0},
        {"last_price": float("nan")},
        {"provider": "MOCK"},
        {"source": "EOD_SNAPSHOT"},
        {"data_state": "DEGRADED"},
        {"received_at": (NOW - timedelta(seconds=11)).isoformat()},
        {"received_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"received_at": NOW.replace(tzinfo=None).isoformat()},
    ],
)
def test_missing_stale_synthetic_and_future_quote_evidence_is_not_an_atm_price(overrides):
    assert fresh_underlying_price(_quote(**overrides), as_of=NOW) is None


def test_subscription_boundary_has_no_scalar_or_calendar_fallback(monkeypatch):
    rows = dict(_row(25000, side) for side in ("CE", "PE"))
    monkeypatch.setattr(
        "market.quotes.get_quote", lambda *args, **kwargs: {"NSE:NIFTY 50": _quote()}
    )
    loader = Mock(return_value=rows)
    monkeypatch.setattr("market.symbol_master.load_master", loader)
    assert set(get_subscription_option_grid("NIFTY", as_of=NOW)) == set(rows)
    loader.assert_called_once_with("NSE_FO", offline_fallback=False)
    monkeypatch.setattr("market.quotes.get_quote", lambda *args, **kwargs: {})
    loader.reset_mock()
    assert get_subscription_option_grid("NIFTY", as_of=NOW) == []
    loader.assert_not_called()


def test_degraded_master_cannot_be_promoted_by_a_stricter_reader(monkeypatch, tmp_path):
    from market import symbol_master as module

    monkeypatch.setenv("TRADING_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(module, "_IN_MEMORY_CACHE", {})
    monkeypatch.setattr(module, "_MASTER_CHECKED_ON", {})
    monkeypatch.setattr(module, "_MASTER_CACHE_PATHS", {})
    monkeypatch.setattr(module, "_DEGRADED_MASTERS", set())
    path = module._cache_path("NSE_FO")
    path.parent.mkdir()
    path.write_text(json.dumps(dict([_row()])), encoding="utf-8")
    monkeypatch.setattr(module, "_is_fresh", lambda path: False)
    fetch = Mock(side_effect=OSError("feed down"))
    monkeypatch.setattr(module.urllib.request, "urlopen", fetch)
    assert module.load_master("NSE_FO", offline_fallback=True)
    with pytest.raises(RuntimeError, match="feed down"):
        module.load_master("NSE_FO", offline_fallback=False)
    assert fetch.call_count == 2


def test_master_rollover_and_storage_override_cannot_reuse_prior_snapshot(monkeypatch, tmp_path):
    from market import symbol_master as module

    monkeypatch.setenv("TRADING_PLATFORM_DATA", str(tmp_path))
    monkeypatch.setattr(module, "_IN_MEMORY_CACHE", {"NSE_FO": {"old": {}}})
    monkeypatch.setattr(
        module, "_MASTER_CHECKED_ON", {"NSE_FO": datetime.now(IST).date() - timedelta(days=1)}
    )
    monkeypatch.setattr(module, "_MASTER_CACHE_PATHS", {"NSE_FO": tmp_path / "other"})
    monkeypatch.setattr(module, "_DEGRADED_MASTERS", set())
    rows = dict([_row()])
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(rows).encode()),
    )
    assert module.load_master("NSE_FO", offline_fallback=False) == rows
    assert module._cache_path("NSE_FO") == tmp_path / "sym_master" / "NSE_FO.json"
