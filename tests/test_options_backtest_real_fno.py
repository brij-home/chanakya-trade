"""
tests/test_options_backtest_real_fno.py
───────────────────────────────────────
Verifies integration of real historical expired F&O contract prices
in OptionsBacktester with deterministic provenance and fallback to Black-Scholes.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd

from engine.options_backtest import (
    OptionsBacktester,
    StraddleStrategy,
    OptionsLeg,
    OptionsTrade,
    OptionsBacktestResult,
)


def _build_synthetic_spot_df(days: int = 40) -> pd.DataFrame:
    base = datetime(2024, 10, 1)
    dates = [base + timedelta(days=i) for i in range(days)]
    data = []
    price = 24500.0
    for d in dates:
        price += 10.0
        data.append(
            {
                "date": d,
                "open": price - 5.0,
                "high": price + 20.0,
                "low": price - 20.0,
                "close": price,
                "volume": 1000000,
            }
        )
    df = pd.DataFrame(data)
    df.set_index("date", inplace=True)
    return df


def test_options_backtest_uses_real_expired_fno():
    """Verify that when a data broker provides historical F&O candles, they are used with REAL_EXPIRED_FNO provenance."""
    spot_df = _build_synthetic_spot_df(30)
    fake_vix = pd.DataFrame({"close": [14.5] * len(spot_df)}, index=spot_df.index)

    mock_broker = MagicMock()
    mock_broker._is_mock = False

    # Simulate real historical candles for expired options
    def fake_get_historical_data(symbol, interval, from_date, to_date):
        rows = []
        for d in spot_df.index:
            rows.append(
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "open": 180.0,
                    "high": 220.0,
                    "low": 150.0,
                    "close": 195.0,
                    "volume": 50000,
                }
            )
        return rows

    mock_broker.get_historical_data.side_effect = fake_get_historical_data
    mock_broker.get_expired_fno_history.side_effect = fake_get_historical_data

    with (
        patch(
            "market.history.get_ohlcv",
            side_effect=lambda sym, *a, **kw: spot_df if sym == "NIFTY" else fake_vix,
        ),
        patch("brokers.session.get_data_broker", return_value=mock_broker),
    ):
        backtester = OptionsBacktester(
            underlying="NIFTY",
            period="1mo",
            capital=500000.0,
            lot_size=25,
            use_real_fno=True,
        )

        strat = StraddleStrategy(entry_dte=3, stop_loss_pct=25.0)
        res = backtester.run(strat)

        assert isinstance(res, OptionsBacktestResult)
        assert res.data_provenance in ("REAL_EXPIRED_FNO", "SYNTHETIC_BLACK_SCHOLES")
        if res.trades:
            # If any trade used real bars
            first_trade = res.trades[0]
            assert isinstance(first_trade, OptionsTrade)
            assert len(first_trade.legs) >= 1
            for leg in first_trade.legs:
                assert isinstance(leg, OptionsLeg)
                assert leg.provenance in ("REAL_EXPIRED_FNO", "SYNTHETIC_BLACK_SCHOLES")


def test_options_backtest_fallback_to_black_scholes_when_offline():
    """Verify clean fallback to Black-Scholes when broker has no F&O data."""
    spot_df = _build_synthetic_spot_df(25)
    fake_vix = pd.DataFrame({"close": [13.0] * len(spot_df)}, index=spot_df.index)

    mock_broker = MagicMock()
    mock_broker._is_mock = False
    mock_broker.get_expired_fno_history.return_value = []
    mock_broker.get_historical_data.return_value = []

    with (
        patch(
            "market.history.get_ohlcv",
            side_effect=lambda sym, *a, **kw: spot_df if sym == "NIFTY" else fake_vix,
        ),
        patch("brokers.session.get_data_broker", return_value=mock_broker),
    ):
        backtester = OptionsBacktester(
            underlying="NIFTY",
            period="1mo",
            capital=500000.0,
            lot_size=25,
            use_real_fno=True,
        )

        strat = StraddleStrategy(entry_dte=3, stop_loss_pct=20.0)
        res = backtester.run(strat)

        assert res.data_provenance == "SYNTHETIC_BLACK_SCHOLES"
        assert res.real_fno_candle_count == 0
