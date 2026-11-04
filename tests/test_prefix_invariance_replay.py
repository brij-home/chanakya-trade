"""
tests/test_prefix_invariance_replay.py
──────────────────────────────────────
Verifies causal replay and prefix-invariance controls:
1. Running through bar t yields identical decisions and trades to the full run truncated at t (zero lookahead).
2. Bar-close signals only execute on the subsequent bar open.
3. Shadow evaluator contracts: worst-case adverse first-touch resolution and horizon censoring.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from engine.backtest import Backtester, Strategy
from engine.shadow_evaluator import (
    ShadowCandidate,
    evaluate_shadow_outcomes,
)


class SimpleCausalSMAStrategy(Strategy):
    """Causal moving average crossover strategy (5 SMA vs 15 SMA)."""

    def __init__(self, fast_window: int = 5, slow_window: int = 15):
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast = close.rolling(window=self.fast_window, min_periods=self.fast_window).mean()
        slow = close.rolling(window=self.slow_window, min_periods=self.slow_window).mean()

        signals = pd.Series(0, index=df.index, dtype=int)
        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))

        signals[cross_up] = 1
        signals[cross_down] = -1
        return signals


def _generate_synthetic_ohlcv(n_bars: int = 120) -> pd.DataFrame:
    """Generates synthetic deterministic daily OHLCV series."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=n_bars, freq="B")

    t = np.linspace(0, 4 * np.pi, n_bars)
    trend = np.linspace(100, 150, n_bars)
    cycle = 15.0 * np.sin(t)
    noise = np.random.normal(0, 1.0, n_bars)
    close = trend + cycle + noise

    open_p = close + np.random.uniform(-1.5, 1.5, n_bars)
    high_p = np.maximum(open_p, close) + np.random.uniform(0.5, 3.0, n_bars)
    low_p = np.minimum(open_p, close) - np.random.uniform(0.5, 3.0, n_bars)
    volume = np.random.uniform(100000, 500000, n_bars)

    df = pd.DataFrame(
        {
            "open": np.round(open_p, 2),
            "high": np.round(high_p, 2),
            "low": np.round(low_p, 2),
            "close": np.round(close, 2),
            "volume": np.round(volume, 0),
        },
        index=dates,
    )
    return df


def test_prefix_invariance_causal_replay():
    """
    Invariance invariant: running through bar t yields identical decisions and trades
    to the full run truncated at t.
    """
    full_df = _generate_synthetic_ohlcv(120)
    strategy = SimpleCausalSMAStrategy(fast_window=5, slow_window=15)

    # Full backtest run
    bt_full = Backtester(
        symbol="NIFTY",
        capital=200000,
        conservative_fills=False,
        execute_on_next_bar=True,
    )
    bt_full._df = full_df.copy()
    res_full = bt_full.run(strategy)
    # Filter for naturally closed strategy trades (excluding artificial end-of-series open positions)
    full_strat_trades = [tr for tr in res_full.trades if not tr.signal.endswith("(open)")]

    assert len(full_strat_trades) >= 1, "Backtest should have generated naturally completed trades"

    # Truncate at prefix length t = 95 (well after Trade 1 exited naturally at bar ~83)
    t_idx = 95
    cutoff_date = str(full_df.index[t_idx])[:10]
    prefix_df = full_df.iloc[: t_idx + 1].copy()

    bt_prefix = Backtester(
        symbol="NIFTY",
        capital=200000,
        conservative_fills=False,
        execute_on_next_bar=True,
    )
    bt_prefix._df = prefix_df
    res_prefix = bt_prefix.run(strategy)
    prefix_strat_trades = [tr for tr in res_prefix.trades if not tr.signal.endswith("(open)")]

    # All strategy trades completed before cutoff_date in full run must match prefix run
    full_completed_before_t = [tr for tr in full_strat_trades if tr.exit_date <= cutoff_date]

    assert len(prefix_strat_trades) == len(full_completed_before_t)
    for tr_full, tr_pref in zip(full_completed_before_t, prefix_strat_trades):
        assert tr_full.entry_date == tr_pref.entry_date
        assert tr_full.exit_date == tr_pref.exit_date
        assert tr_full.entry_price == tr_pref.entry_price
        assert tr_full.exit_price == tr_pref.exit_price
        assert tr_full.direction == tr_pref.direction
        assert tr_full.pnl == tr_pref.pnl


def test_bar_close_signal_executes_on_next_bar_open():
    """
    Verifies that a bar-close signal at bar k executes on bar k+1 open,
    eliminating same-bar lookahead bias.
    """
    dates = pd.date_range("2026-02-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0],
            "high": [101.0, 103.0, 105.0, 107.0, 109.0, 111.0, 113.0, 115.0, 117.0, 119.0],
            "low": [99.0, 101.0, 103.0, 105.0, 107.0, 109.0, 111.0, 113.0, 115.0, 117.0],
            "close": [100.5, 102.5, 104.5, 106.5, 108.5, 110.5, 112.5, 114.5, 116.5, 118.5],
        },
        index=dates,
    )

    class ExplicitSignalStrategy(Strategy):
        def generate_signals(self, data):
            s = pd.Series(0, index=data.index, dtype=int)
            s.iloc[2] = 1
            s.iloc[5] = -1
            return s

    bt = Backtester(symbol="TEST", capital=100000, execute_on_next_bar=True)
    bt._df = df
    res = bt.run(ExplicitSignalStrategy())

    assert len(res.trades) == 1
    trade = res.trades[0]

    # Bar 2 close emitted buy (date index 2 = 2026-02-04)
    # Trade entered on subsequent bar (index 3 = 2026-02-05) at bar 3 open (106.0)
    expected_entry_date = str(dates[3])[:10]
    expected_entry_open = df.iloc[3]["open"]
    assert trade.entry_date == expected_entry_date
    assert trade.entry_price == expected_entry_open

    # Bar 5 close emitted exit (date index 5 = 2026-02-09)
    # Trade exited on subsequent bar (index 6 = 2026-02-10) at bar 6 open (112.0)
    expected_exit_date = str(dates[6])[:10]
    expected_exit_open = df.iloc[6]["open"]
    assert trade.exit_date == expected_exit_date
    assert trade.exit_price == expected_exit_open


def test_shadow_evaluator_causal_first_touch_and_censoring():
    """
    Verifies shadow candidate evaluation:
    1. First-touch adverse SL resolution when both SL and target are touched in same bar.
    2. Horizon censoring: returns net_outcome_r=None when untouched within max horizon.
    """
    cand = ShadowCandidate(
        candidate_id="sc-test-001",
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        entry_level=100.0,
        stop_loss=90.0,  # 10 pts risk
        target_level=120.0,  # 20 pts reward (2R)
        underlying_spot=24500.0,
        suppressed_by_gate="MOMENTUM_FILTER",
        suppression_reason="Sub-threshold momentum",
        session_id="20261101",
        recorded_at="2026-11-01 10:00:00 IST",
        recorded_ts=1761981000.0,
        episode_id="ep-001",
        feature_snapshot={"payoff_type": "LONG_ASSET"},
    )

    # Case 1: Adverse first-touch resolution
    # Bar touches both high=125.0 (target) and low=85.0 (SL) -> assumes worst case (SL)
    bars_both = [(125.0, 85.0)]
    outcomes = evaluate_shadow_outcomes([cand], {cand.candidate_id: bars_both})
    assert len(outcomes) == 1
    assert outcomes[0]["avoided_adverse_move"] is True
    assert outcomes[0]["missed_favorable_move"] is False
    assert outcomes[0]["net_outcome_r"] == -1.0

    # Case 2: Clean target touch
    cand.evaluated = False
    bars_target = [(105.0, 95.0), (122.0, 98.0)]
    outcomes_tgt = evaluate_shadow_outcomes([cand], {cand.candidate_id: bars_target})
    assert outcomes_tgt[0]["avoided_adverse_move"] is False
    assert outcomes_tgt[0]["missed_favorable_move"] is True
    assert outcomes_tgt[0]["net_outcome_r"] == 2.0

    # Case 3: Horizon censoring (neither touched within bars)
    cand.evaluated = False
    bars_untouched = [(105.0, 95.0), (108.0, 96.0), (102.0, 97.0)]
    outcomes_censored = evaluate_shadow_outcomes([cand], {cand.candidate_id: bars_untouched})
    assert outcomes_censored[0]["avoided_adverse_move"] is False
    assert outcomes_censored[0]["missed_favorable_move"] is False
    assert outcomes_censored[0]["net_outcome_r"] is None
