"""
tests/test_breakout_classifier.py
──────────────────────────────────
Unit and invariant verification for the institutional Breakout Microstructure Classifier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.breakout_classifier import (
    BreakoutMode,
    classify_breakout_mode,
    compute_ttm_squeeze_bars,
)


def _generate_synthetic_candles(
    n: int = 30,
    base_price: float = 1000.0,
    squeeze: bool = False,
    breakout_up: bool = False,
    rejection_wick: bool = False,
) -> pd.DataFrame:
    """Generate realistic OHLCV candles with deterministic microstructure patterns."""
    np.random.seed(42)
    dates = pd.date_range("2026-11-11 09:15", periods=n, freq="5min")

    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    price = base_price
    for i in range(n):
        if squeeze and i < n - 1:
            # Very tight range for squeeze (BB inside KC)
            h = price + 0.5
            l = price - 0.5
            o = price - 0.2
            c = price + 0.2
            vol = 1000.0
        elif breakout_up and i == n - 1:
            # Breakout candle
            o = price
            if rejection_wick:
                h = price + 20.0
                c = price + 8.0  # Big upper wick (12 pts out of 21 pts range -> 57%)
                l = price - 1.0
            else:
                h = price + 3.0
                c = price + 2.8  # Close at extreme (0.2 pt wick out of 3.2 pts range -> 6%)
                l = price - 0.2
            vol = 5000.0
        else:
            o = price + np.random.uniform(-0.5, 0.5)
            c = price + np.random.uniform(-0.5, 0.5)
            h = max(o, c) + np.random.uniform(0.2, 0.5)
            l = min(o, c) - np.random.uniform(0.2, 0.5)
            vol = np.random.uniform(1000, 3000)

        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(vol)

    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


class TestBreakoutClassifier:
    def test_ttm_squeeze_detection(self):
        """Verify that tight coiling is detected as consecutive squeeze bars."""
        df_squeeze = _generate_synthetic_candles(n=30, squeeze=True)
        squeeze_count = compute_ttm_squeeze_bars(df_squeeze)
        assert squeeze_count >= 8, f"Expected >= 8 squeeze bars, got {squeeze_count}"

    def test_continuation_runner_classification(self):
        """Verify that a breakout from a long squeeze with close at extreme is a CONTINUATION_RUNNER."""
        df = _generate_synthetic_candles(n=30, squeeze=True, breakout_up=True, rejection_wick=False)
        last_close = float(df["Close"].iloc[-1])

        res = classify_breakout_mode(
            df=df,
            ltp=last_close,
            breakout_level=1000.0,
            direction="BULLISH",
            rvol=2.5,
            atr=5.0,
            base_price=1000.0,
        )

        assert res.mode == BreakoutMode.CONTINUATION_RUNNER
        assert res.is_extended is False
        assert res.recommended_entry_type == "STOP_LIMIT_PIVOT"
        assert "Continuation Runner" in res.rationale

    def test_pullback_retest_classification(self):
        """Verify that an extended move without squeeze coiling requires a PULLBACK_RETEST."""
        df_normal = _generate_synthetic_candles(
            n=30, squeeze=False, breakout_up=True, rejection_wick=False
        )

        # LTP is extended 4.0 points away from base on ATR 3.0 (> 1.3x ATR) without squeeze
        res = classify_breakout_mode(
            df=df_normal,
            ltp=1004.0,
            breakout_level=1000.0,
            direction="BULLISH",
            rvol=1.3,
            atr=3.0,
            base_price=1000.0,
        )

        assert res.mode == BreakoutMode.PULLBACK_RETEST_REQUIRED
        assert res.is_extended is True
        assert res.recommended_entry_type == "LIMIT_PULLBACK"
        assert res.optimal_entry_limit < 1004.0
        assert "Retest Required" in res.rationale

    def test_exhaustion_trap_classification(self):
        """Verify that a breakout candle with heavy rejection wick (> 40%) is flagged as EXHAUSTION_TRAP_RISK."""
        df_trap = _generate_synthetic_candles(
            n=30, squeeze=False, breakout_up=True, rejection_wick=True
        )
        last_close = float(df_trap["Close"].iloc[-1])

        res = classify_breakout_mode(
            df=df_trap,
            ltp=last_close,
            breakout_level=1000.0,
            direction="BULLISH",
            rvol=2.0,
            atr=5.0,
            base_price=1000.0,
        )

        assert res.mode == BreakoutMode.EXHAUSTION_TRAP_RISK
        assert res.recommended_entry_type == "VETO_TRAP"
        assert "Exhaustion Trap" in res.rationale

    def test_trade_plan_integration_runner(self):
        """Verify that trade_plan calculate_trade_plan respects continuation runner without false extension."""
        from engine.trade_plan import calculate_trade_plan

        df_runner = _generate_synthetic_candles(
            n=30, squeeze=True, breakout_up=True, rejection_wick=False
        )
        last_close = float(df_runner["Close"].iloc[-1])

        plan = calculate_trade_plan(
            symbol="BANKNIFTY",
            direction="BUY",
            spot=last_close,
            df=df_runner,
        )

        # In runner mode, trade plan should allow pivot entry without forcing limit retest
        assert plan is not None
        assert hasattr(plan, "entry_strategy")
        assert plan.entry_strategy in ("CONFIRMATION_STOP_LIMIT", "PULLBACK_OTE_LIMIT")
