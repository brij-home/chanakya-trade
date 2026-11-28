"""Tests for Fyers active-monthly Black-Scholes IV surface reconstruction & backfill."""

from __future__ import annotations

from datetime import date
import sqlite3

import numpy as np
import pandas as pd
import pytest

from engine.iv_history_backfill import (
    backfill_symbol_iv_history,
    black76_option_price,
    implied_volatility_black76,
    implied_volatility_bs,
    select_historical_monthly_contracts,
)
from engine.iv_surface import (
    build_iv_surface_snapshot,
    interpolate_constant_tenor_variance,
    load_historical_30d_ivs,
    record_iv_observation,
)
from market.contract_selection import ListedContract


def test_black76_and_bs_iv_round_trip():
    """Verify Black-76 and spot BS inversion round-trip exact implied vol and reject arbitrage."""
    forward = 25000.0
    strike = 25000.0
    dte = 45
    true_sigma = 0.165

    ce_px = black76_option_price(forward, strike, dte, true_sigma, option_type="CE")
    pe_px = black76_option_price(forward, strike, dte, true_sigma, option_type="PE")

    ce_iv = implied_volatility_black76(ce_px, forward, strike, dte, option_type="CE")
    pe_iv = implied_volatility_black76(pe_px, forward, strike, dte, option_type="PE")

    assert ce_iv is not None and abs(ce_iv - true_sigma) < 1e-4
    assert pe_iv is not None and abs(pe_iv - true_sigma) < 1e-4

    # Sub-intrinsic arbitrage prices must fail closed to None
    assert implied_volatility_black76(100.0, 25500.0, 25000.0, 30, option_type="CE") is None
    assert implied_volatility_black76(0.0, 25000.0, 25000.0, 30, option_type="CE") is None
    assert implied_volatility_bs(10.0, 25000.0, 25000.0, 0, option_type="CE") is None


def test_constant_tenor_out_of_bracket_preserves_annualized_scale():
    """Verify flat annualized extrapolation above target_dte does not multiply by sqrt(dte/target)."""
    # Both tenors >= 30D: constant-30D IV must remain flat near short leg annualized vol, not inflated
    iv_30 = interpolate_constant_tenor_variance(15.0, 60, 16.0, 90, target_dte=30)
    assert iv_30 == 15.0

    # Both tenors < 30D (e.g., SENSEX weekly 7D & 14D): flat long-wing annualized vol
    iv_30_short = interpolate_constant_tenor_variance(14.0, 7, 14.5, 14, target_dte=30)
    assert iv_30_short == 14.5


def test_backfill_reconstructs_real_iv_history_and_preserves_live_rows(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """Verify active-monthly BS IV backfill populates >= 20 sessions without overwriting live rows."""
    db_file = tmp_path / "iv_history.db"
    monkeypatch.setattr("engine.iv_surface._get_iv_db_path", lambda: db_file)

    today = date(2026, 11, 27)
    weekly_dec22 = date(2026, 12, 22)
    exp1 = date(2026, 12, 29)
    exp2 = date(2027, 1, 25)

    # Create causal trading sessions ending 2026-11-26 (plus an extra Dec-22 weekly trap contract)
    dates = pd.bdate_range("2026-10-08", "2026-11-26")
    rng = np.random.default_rng(7)
    spots = 25000.0 + np.cumsum(rng.normal(0.0, 90.0, size=len(dates)))
    spot_df = pd.DataFrame(
        {
            "open": spots - 20.0,
            "high": spots + 45.0,
            "low": spots - 45.0,
            "close": spots,
            "volume": 100000.0,
        },
        index=dates,
    )

    contracts = []
    for k in (24500.0, 25000.0, 25500.0):
        for opt in ("CE", "PE"):
            contracts.append(
                ListedContract(
                    symbol=f"NSE:NIFTY26D22{int(k)}{opt}",
                    underlying="NIFTY",
                    expiry=weekly_dec22,
                    option_type=opt,
                    strike=k,
                    lot_size=65,
                    tick_size=0.05,
                    token=f"26D22-{int(k)}-{opt}",
                )
            )
    for exp, tag in [(exp1, "26DEC"), (exp2, "27JAN")]:
        for k in (24500.0, 25000.0, 25500.0):
            for opt in ("CE", "PE"):
                contracts.append(
                    ListedContract(
                        symbol=f"NSE:NIFTY{tag}{int(k)}{opt}",
                        underlying="NIFTY",
                        expiry=exp,
                        option_type=opt,
                        strike=k,
                        lot_size=65,
                        tick_size=0.05,
                        token=f"{tag}-{int(k)}-{opt}",
                    )
                )

    picked = select_historical_monthly_contracts(
        "NIFTY",
        spot_df["close"],
        listed_contracts=contracts,
        max_expiries=2,
        strikes_per_expiry=3,
        as_of_date=today,
    )
    assert len(picked) == 12
    assert all("26D22" not in c.symbol for c in picked)

    # Live chain capture for 2026-11-26 MUST NOT be overwritten when backfill runs
    live_snap = build_iv_surface_snapshot(
        symbol="NIFTY",
        near_atm_iv=14.44,
        near_dte=10,
        next_atm_iv=15.2,
        next_dte=40,
        now_dt=pd.Timestamp("2026-11-26 15:30:00").to_pydatetime(),
        source_provenance="LIVE_CHAIN",
    )
    assert live_snap.atm_iv_30d is not None
    assert record_iv_observation(live_snap, session_date="2026-11-26", overwrite_existing=True)

    class _FakeBroker:
        def has_token(self) -> bool:
            return True

        def get_historical_data(
            self, symbol: str, exchange: str, interval: str, *, from_date, to_date
        ):
            exp = exp1 if "26DEC" in symbol else exp2
            opt = "CE" if symbol.endswith("CE") else "PE"
            strike_str = symbol.replace("NSE:NIFTY26DEC", "").replace("NSE:NIFTY27JAN", "")[:-2]
            strike = float(strike_str)
            rows = []
            for idx, (ts, row) in enumerate(spot_df.iterrows()):
                d = ts.date()
                dte = (exp - d).days
                if dte <= 0:
                    continue
                spot = float(row["close"])
                # Genuine varying market IV across sessions [13%..21%]
                sigma = 0.13 + 0.08 * (idx / max(1, len(spot_df) - 1))
                fwd = spot * np.exp((0.065 - 0.012) * (dte / 365.0))
                px = black76_option_price(fwd, strike, dte, sigma, option_type=opt)
                rows.append(
                    {
                        "date": ts.to_pydatetime(),
                        "open": px,
                        "high": px * 1.02,
                        "low": px * 0.98,
                        "close": round(px, 2),
                        "volume": 5000.0,
                    }
                )
            return rows

    res = backfill_symbol_iv_history(
        "NIFTY",
        broker=_FakeBroker(),
        lookback_days=90,
        target_min_sessions=25,
        overwrite_existing=False,
        spot_df=spot_df,
        listed_contracts=contracts,
        strikes_per_expiry=3,
        force=True,
    )
    assert res["status"] == "COMPLETED"
    assert res["total_sessions"] >= 25

    hist = load_historical_30d_ivs("NIFTY", limit=252)
    assert len(hist) >= 25

    # Verify 2026-11-26 retained LIVE_CHAIN provenance and exact live IV
    with sqlite3.connect(str(db_file)) as conn:
        live_row = conn.execute(
            "SELECT atm_iv_30d, source_provenance FROM iv_daily_surface WHERE symbol='NIFTY' AND session_date='2026-11-26'"
        ).fetchone()
        hist_row = conn.execute(
            "SELECT source_provenance FROM iv_daily_surface WHERE symbol='NIFTY' AND session_date < '2026-11-26' LIMIT 1"
        ).fetchone()
    assert live_row == (live_snap.atm_iv_30d, "LIVE_CHAIN")
    assert hist_row == ("FYERS_ACTIVE_MONTHLY_BS_IV",)

    # Verify IV Rank is now AVAILABLE using empirical option-derived IV history
    cur_snap = build_iv_surface_snapshot(
        symbol="NIFTY",
        near_atm_iv=18.5,
        near_dte=12,
        next_atm_iv=18.8,
        next_dte=40,
        historical_30d_ivs=hist,
        now_dt=pd.Timestamp("2026-11-27 15:30:00").to_pydatetime(),
    )
    assert cur_snap.iv_rank is not None and 0.0 <= cur_snap.iv_rank <= 100.0
    assert cur_snap.iv_percentile is not None
    assert cur_snap.sample_count >= 25


def test_expired_fno_greeks_fusion_for_sensex(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Verify Fyers 3.2+ expired monthly F&O Greeks + active monthly BS IV brackets 30D cleanly."""
    from engine.iv_history_backfill import _parse_expired_option_contract_symbol

    assert _parse_expired_option_contract_symbol(
        "BSE:SENSEX26OCT84000CE", "SENSEX", date(2026, 10, 29)
    ) == (84000.0, "CE")
    assert (
        _parse_expired_option_contract_symbol(
            "BSE:SENSEX26N1984000CE", "SENSEX", date(2026, 11, 26)
        )
        is None
    )

    db_file = tmp_path / "iv_history_exp.db"
    monkeypatch.setattr("engine.iv_surface._get_iv_db_path", lambda: db_file)

    exp_oct = date(2026, 10, 29)
    exp_nov = date(2026, 11, 26)
    exp_dec = date(2026, 12, 31)
    dates = pd.bdate_range("2026-10-05", "2026-11-25")
    spot_df = pd.DataFrame(
        {
            "open": 84000.0,
            "high": 84300.0,
            "low": 83800.0,
            "close": 84100.0,
            "volume": 50000.0,
        },
        index=dates,
    )

    active_contracts = [
        ListedContract(
            symbol=f"BSE:SENSEX26DEC84000{opt}",
            underlying="SENSEX",
            expiry=exp_dec,
            option_type=opt,
            strike=84000.0,
            lot_size=20,
            tick_size=0.05,
            token=f"DEC-{opt}",
        )
        for opt in ("CE", "PE")
    ]

    class _FakeRawFyers:
        def expiry_dates(self, payload):
            return {
                "s": "ok",
                "data": {"expiry_dates": {"options": ["2026-10-29", "2026-11-19", "2026-11-26"]}},
            }

        def history_underlying_symbols(self, payload):
            tag = "26OCT" if payload["expiry_date"] == "2026-10-29" else "26NOV"
            return {
                "s": "ok",
                "data": {
                    "contracts": {
                        "options": [
                            f"BSE:SENSEX{tag}84000CE",
                            f"BSE:SENSEX{tag}84000PE",
                        ]
                    }
                },
            }

        def fno_historical_data(self, payload):
            return {"s": "ok", "candles": []}

    class _FakeExpiredBroker:
        def has_token(self) -> bool:
            return True

        def _get_fyers(self):
            return _FakeRawFyers()

        def get_expired_fno_history(
            self, symbol, exchange="BFO", interval="D", from_date=None, to_date=None, **_kwargs
        ):
            exp = exp_oct if "26OCT" in symbol else exp_nov
            opt = "CE" if symbol.endswith("CE") else "PE"
            rows = []
            for ts, row in spot_df.iterrows():
                d = ts.date()
                dte = (exp - d).days
                if dte <= 0:
                    continue
                fwd = float(row["close"]) * np.exp((0.065 - 0.012) * (dte / 365.0))
                px = black76_option_price(fwd, 84000.0, dte, 0.148, option_type=opt)
                rows.append(
                    {
                        "date": ts.to_pydatetime(),
                        "open": px,
                        "high": px * 1.01,
                        "low": px * 0.99,
                        "close": round(px, 2),
                        "volume": 1000.0,
                        "implied_volatility": 14.8,
                    }
                )
            return rows

        def get_historical_data(self, symbol, exchange, interval, *, from_date, to_date):
            opt = "CE" if symbol.endswith("CE") else "PE"
            rows = []
            for ts, row in spot_df.iterrows():
                d = ts.date()
                dte = (exp_dec - d).days
                if dte <= 0:
                    continue
                fwd = float(row["close"]) * np.exp((0.065 - 0.012) * (dte / 365.0))
                px = black76_option_price(fwd, 84000.0, dte, 0.155, option_type=opt)
                rows.append(
                    {
                        "date": ts.to_pydatetime(),
                        "open": px,
                        "high": px * 1.01,
                        "low": px * 0.99,
                        "close": round(px, 2),
                        "volume": 1200.0,
                    }
                )
            return rows

    res = backfill_symbol_iv_history(
        "SENSEX",
        broker=_FakeExpiredBroker(),
        lookback_days=90,
        target_min_sessions=25,
        overwrite_existing=False,
        spot_df=spot_df,
        listed_contracts=active_contracts,
        strikes_per_expiry=2,
        force=True,
    )
    assert res["status"] == "COMPLETED"
    assert res["provenance"] == "FYERS_EXPIRED_PLUS_ACTIVE_BS_IV"
    assert res["expired_contracts"] >= 4
    assert res["total_sessions"] >= 25

    with sqlite3.connect(str(db_file)) as conn:
        row = conn.execute(
            "SELECT near_dte, next_dte, source_provenance FROM iv_daily_surface WHERE symbol='SENSEX' AND near_dte <= 30 AND next_dte > 30 LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[2] == "FYERS_EXPIRED_PLUS_ACTIVE_BS_IV"
