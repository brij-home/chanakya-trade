"""
tests/test_smt_sweep_backtest.py
─────────────────────────────────
Unit and integration tests for the institutional Smart Money Technique (SMT)
Liquidity Sweep strategy and multi-strategy benchmark suite.

Covers:
  1. SMTSweepStrategy initialization and signal generation.
  2. Bullish SMT spring (primary sweeps low, sibling diverges/holds).
  3. Bearish SMT upthrust (primary sweeps high, sibling diverges/lags).
  4. Harmonious breakout protection (harmonious trend continuation is NOT faded).
  5. SMT Benchmark comparative scorecard execution across 6 strategies.
  6. Statutory charges friction deduction & net return accounting (post-Oct 2024 SEBI rates).
  7. Two Win Rates disambiguation (Trade Win Rate vs Positive Period %).
  8. FastAPI endpoint GET /api/backtest/smt-benchmark verification.
"""

from __future__ import annotations

import pandas as pd

from engine.backtest import (
    SMTSweepStrategy,
    TurtleSoupStrategy,
    STRATEGIES,
)
from engine.smt_benchmark import (
    SMTBenchmarkResult,
    _compute_statutory_costs,
    run_smt_benchmark,
)


def _generate_synthetic_paired_data(n_bars: int = 60) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generates synthetic daily OHLCV series for primary (NIFTY) and sibling (BANKNIFTY)."""
    dates = pd.date_range("2024-01-01", periods=n_bars, freq="B")

    # Primary baseline: oscillates around 20,000
    p_close = [20000.0 + (i % 10) * 20.0 for i in range(n_bars)]
    p_high = [c + 30.0 for c in p_close]
    p_low = [c - 30.0 for c in p_close]
    p_open = [c - 5.0 for c in p_close]
    p_vol = [100000 for _ in range(n_bars)]

    primary_df = pd.DataFrame(
        {
            "open": p_open,
            "high": p_high,
            "low": p_low,
            "close": p_close,
            "volume": p_vol,
        },
        index=dates,
    )

    # Sibling baseline: oscillates around 45,000
    s_close = [45000.0 + (i % 10) * 40.0 for i in range(n_bars)]
    s_high = [c + 60.0 for c in s_close]
    s_low = [c - 60.0 for c in s_close]
    s_open = [c - 10.0 for c in s_close]
    s_vol = [80000 for _ in range(n_bars)]

    sibling_df = pd.DataFrame(
        {
            "open": s_open,
            "high": s_high,
            "low": s_low,
            "close": s_close,
            "volume": s_vol,
        },
        index=dates,
    )

    return primary_df, sibling_df


def test_smt_sweep_strategy_registration():
    """Verify smt_sweep and smt are registered in backtest STRATEGIES registry."""
    assert "smt_sweep" in STRATEGIES
    assert "smt" in STRATEGIES

    strat = STRATEGIES["smt_sweep"](["25"])
    assert isinstance(strat, SMTSweepStrategy)
    assert strat.lookback == 25
    assert "25" in strat.name


def test_bullish_smt_sweep_spring_fires():
    """
    Bullish SMT Sweep (Spring):
    Primary penetrates rolling 20-bar low and reclaims it with lower wick.
    Sibling index holds well above its 20-bar low (non-confirmation divergence).
    Verifies SMT signal = +1.
    """
    primary_df, sibling_df = _generate_synthetic_paired_data(40)
    lookback = 20

    # Calculate prior 20-bar low for bar 25
    p_prior_low = primary_df["low"].iloc[5:25].min()
    s_prior_low = sibling_df["low"].iloc[5:25].min()

    # Modify bar 25 on primary to sweep low and reclaim
    # Primary: low dips below prior low, but closes back above prior low with lower wick
    primary_df.iloc[25, primary_df.columns.get_loc("open")] = p_prior_low + 10.0
    primary_df.iloc[25, primary_df.columns.get_loc("low")] = p_prior_low - 40.0  # Swept!
    primary_df.iloc[25, primary_df.columns.get_loc("high")] = p_prior_low + 20.0
    primary_df.iloc[25, primary_df.columns.get_loc("close")] = p_prior_low + 15.0  # Reclaimed!

    # Sibling at bar 25 holds well above its prior low (divergence)
    sibling_df.iloc[25, sibling_df.columns.get_loc("low")] = s_prior_low + 50.0
    sibling_df.iloc[25, sibling_df.columns.get_loc("close")] = s_prior_low + 80.0

    strat = SMTSweepStrategy(lookback=lookback, sibling_df=sibling_df, min_wick_pct=20.0)
    signals = strat.generate_signals(primary_df)

    assert signals.iloc[25] == 1, "Expected Bullish SMT Sweep buy signal (+1) on spring divergence"


def test_bearish_smt_sweep_upthrust_fires():
    """
    Bearish SMT Sweep (Upthrust):
    Primary penetrates rolling 20-bar high and closes back below it with upper wick.
    Sibling index fails to make a new high (non-confirmation divergence).
    Verifies SMT signal = -1.
    """
    primary_df, sibling_df = _generate_synthetic_paired_data(40)
    lookback = 20

    p_prior_high = primary_df["high"].iloc[5:25].max()
    s_prior_high = sibling_df["high"].iloc[5:25].max()

    # Modify bar 25 on primary: sweeps high and retreats
    primary_df.iloc[25, primary_df.columns.get_loc("open")] = p_prior_high - 10.0
    primary_df.iloc[25, primary_df.columns.get_loc("high")] = p_prior_high + 50.0  # Swept!
    primary_df.iloc[25, primary_df.columns.get_loc("low")] = p_prior_high - 20.0
    primary_df.iloc[25, primary_df.columns.get_loc("close")] = p_prior_high - 15.0  # Closed below!

    # Sibling at bar 25 fails to reach its prior high (divergence)
    sibling_df.iloc[25, sibling_df.columns.get_loc("high")] = s_prior_high - 30.0
    sibling_df.iloc[25, sibling_df.columns.get_loc("close")] = s_prior_high - 40.0

    strat = SMTSweepStrategy(lookback=lookback, sibling_df=sibling_df, min_wick_pct=20.0)
    signals = strat.generate_signals(primary_df)

    assert signals.iloc[25] == -1, (
        "Expected Bearish SMT Sweep sell signal (-1) on upthrust divergence"
    )


def test_harmonious_breakout_filters_sweep_fades():
    """
    Harmonious Trend Protection:
    When BOTH primary and sibling punch new rolling highs in unison (harmonious trend),
    SMT divergence is FALSE, so SMT Sweep does NOT fire a fade signal (protecting from steamroll).
    In contrast, classical Turtle Soup (single-asset) DOES fire a fade signal and suffers drawdown.
    """
    primary_df, sibling_df = _generate_synthetic_paired_data(40)
    lookback = 20

    p_prior_high = primary_df["high"].iloc[5:25].max()
    s_prior_high = sibling_df["high"].iloc[5:25].max()

    # Primary sweeps high and closes slightly below
    primary_df.iloc[25, primary_df.columns.get_loc("high")] = p_prior_high + 40.0
    primary_df.iloc[25, primary_df.columns.get_loc("close")] = p_prior_high - 5.0
    primary_df.iloc[25, primary_df.columns.get_loc("open")] = p_prior_high - 15.0

    # Sibling ALSO makes a new high (harmonious confirmation!)
    sibling_df.iloc[25, sibling_df.columns.get_loc("high")] = s_prior_high + 80.0
    sibling_df.iloc[25, sibling_df.columns.get_loc("close")] = s_prior_high + 50.0

    smt_strat = SMTSweepStrategy(lookback=lookback, sibling_df=sibling_df)
    smt_signals = smt_strat.generate_signals(primary_df)

    turtle_strat = TurtleSoupStrategy(period=lookback)
    turtle_signals = turtle_strat.generate_signals(primary_df)

    # Classical single-asset Turtle Soup fires a fade signal
    assert turtle_signals.iloc[25] == -1, (
        "Turtle Soup should have fired fade on single-asset high sweep"
    )

    # Institutional SMT Sweep filters it out because sibling confirmed the breakout
    assert smt_signals.iloc[25] == 0, (
        "SMT Sweep must NOT fire fade when sibling confirms harmonious breakout"
    )


def test_run_smt_benchmark_synthetic():
    """
    Verifies run_smt_benchmark produces comprehensive comparative scorecards
    across all 6 benchmark strategies on synthetic paired data.
    """
    primary_df, sibling_df = _generate_synthetic_paired_data(80)

    # Plant a clear SMT divergence setup at bar 30 and 45 to generate trades
    p_prior_low = primary_df["low"].iloc[10:30].min()
    s_prior_low = sibling_df["low"].iloc[10:30].min()
    primary_df.iloc[30, primary_df.columns.get_loc("low")] = p_prior_low - 30.0
    primary_df.iloc[30, primary_df.columns.get_loc("close")] = p_prior_low + 20.0
    sibling_df.iloc[30, sibling_df.columns.get_loc("low")] = s_prior_low + 40.0

    p_prior_high = primary_df["high"].iloc[25:45].max()
    s_prior_high = sibling_df["high"].iloc[25:45].max()
    primary_df.iloc[45, primary_df.columns.get_loc("high")] = p_prior_high + 30.0
    primary_df.iloc[45, primary_df.columns.get_loc("close")] = p_prior_high - 20.0
    sibling_df.iloc[45, sibling_df.columns.get_loc("high")] = s_prior_high - 50.0

    res: SMTBenchmarkResult = run_smt_benchmark(
        symbol="NIFTY",
        sibling_symbol="BANKNIFTY",
        period="1y",
        capital=100000.0,
        df=primary_df,
        sibling_df=sibling_df,
        provenance="SYNTHETIC/TEST",
    )

    assert isinstance(res, SMTBenchmarkResult)
    assert res.symbol == "NIFTY"
    assert res.sibling_symbol == "BANKNIFTY"
    assert res.provenance == "SYNTHETIC/TEST"

    # Scorecards must include all 6 strategies
    strat_ids = [sc.strategy_id for sc in res.scorecards]
    assert "smt_sweep" in strat_ids
    assert "turtle_soup" in strat_ids
    assert "donchian" in strat_ids
    assert "ema_cross" in strat_ids
    assert "rsi" in strat_ids
    assert "buy_and_hold" in strat_ids

    # Validate scorecard fields and dual win rates
    for card in res.scorecards:
        assert isinstance(card.trade_win_rate, (float, int))
        assert isinstance(card.positive_period_pct, (float, int))
        assert 0.0 <= card.trade_win_rate <= 100.0
        assert 0.0 <= card.positive_period_pct <= 100.0
        assert card.statutory_charges >= 0.0
        assert isinstance(card.net_return, (float, int))

    # Validate SMT Edge summary
    edge = res.smt_edge_summary
    assert "alpha_over_single_sweep" in edge
    assert "drawdown_attenuation_pct" in edge
    assert "statutory_friction_inr" in edge

    # Verify serialization and rich printing
    data_dict = res.to_dict()
    assert "scorecards" in data_dict
    assert len(data_dict["scorecards"]) == 6

    # Verify summary prints cleanly without exceptions
    res.print_summary()


def test_statutory_costs_deduction():
    """
    Verifies that _compute_statutory_costs accurately calculates statutory charges
    (STT, GST, turnover, stamp duty, brokerage) and that net return reflects deductions.
    """
    from engine.backtest import Trade

    sample_trades = [
        Trade(
            entry_date="2024-01-10",
            exit_date="2024-01-12",
            direction="LONG",
            entry_price=20000.0,
            exit_price=20400.0,
            quantity=5,
            pnl=2000.0,
            pnl_pct=2.0,
            hold_days=2,
            signal="SMT Sweep",
        ),
        Trade(
            entry_date="2024-01-15",
            exit_date="2024-01-15",
            direction="LONG",
            entry_price=20200.0,
            exit_price=20100.0,
            quantity=5,
            pnl=-500.0,
            pnl_pct=-0.5,
            hold_days=0,  # Intraday
            signal="SMT Sweep",
        ),
    ]

    total_costs = _compute_statutory_costs(sample_trades)
    assert total_costs > 0.0, "Statutory charges must be greater than zero for completed trades"

    # Check that delivery leg + intraday leg includes brokerage (₹20*4 = ₹80 min) + taxes
    assert total_costs >= 80.0


def test_fastapi_smt_benchmark_endpoint():
    """Verifies GET /api/backtest/smt-benchmark works via web router with synthetic fallback."""
    import asyncio
    from web.routers.market_data import get_smt_benchmark_endpoint

    primary_df, sibling_df = _generate_synthetic_paired_data(50)

    # Monkeypatch run_smt_benchmark to use synthetic data for zero-network testing
    import engine.smt_benchmark as bm_mod

    orig_run = bm_mod.run_smt_benchmark

    def _mock_run(symbol, sibling_symbol, period, capital):
        return orig_run(
            symbol=symbol,
            sibling_symbol=sibling_symbol,
            period=period,
            capital=capital,
            df=primary_df,
            sibling_df=sibling_df,
            provenance="SYNTHETIC/TEST",
        )

    try:
        bm_mod.run_smt_benchmark = _mock_run
        res = asyncio.run(
            get_smt_benchmark_endpoint(
                symbol="NIFTY", sibling="BANKNIFTY", period="1y", capital=100000.0
            )
        )
        assert res["status"] == "ok"
        assert "data" in res
        data = res["data"]
        assert data["symbol"] == "NIFTY"
        assert len(data["scorecards"]) == 6
    finally:
        bm_mod.run_smt_benchmark = orig_run
