"""
tests/test_technical_indicators_provenance.py
──────────────────────────────────────────────
Tests verifying that technical indicators calculate on genuine market data,
include explicit timeframe and provenance, and do not suffer from synthetic
overwrites (like RSI 99.9) or false bearish crossovers.
"""

import pytest
import pandas as pd
import numpy as np

from analysis.technical import analyse, rsi, macd, TechnicalSnapshot
from agent.tools import build_registry
from agent.multi_agent import TechnicalAnalyst
from analysis.pipeline import build_compact_signals


def test_technical_snapshot_attributes():
    """Verify TechnicalSnapshot has timeframe, as_of, and MACD attributes."""
    snap = TechnicalSnapshot(
        symbol="TRENT",
        ltp=2800.0,
        rsi=33.7,
        macd=-44.1,
        macd_sig=-33.2,
        macd_hist=-10.9,
        macd_signal="BEARISH",
        macd_detail="Below signal line",
        timeframe="1D (Daily)",
        as_of="2026-09-08",
        data_source="NSE Historical EOD",
    )
    assert snap.timeframe == "1D (Daily)"
    assert snap.as_of == "2026-09-08"
    assert snap.macd_signal == "BEARISH"
    assert snap.macd_detail == "Below signal line"
    assert snap.rsi == 33.7


def test_technical_analyse_synthetic_df(monkeypatch):
    """Verify technical analyse generates accurate RSI, MACD signal and detail on known data."""
    # 50 days of gently declining prices (should yield low RSI, not 99.9)
    dates = pd.date_range("2026-01-01", periods=60, freq="B")
    # Base price 100 dropping to 70
    closes = np.linspace(100, 70, 60)
    fake_df = pd.DataFrame(
        {
            "open": closes + 0.5,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": [100000.0] * 60,
        },
        index=dates,
    )
    fake_df.attrs["provenance"] = {"provider": "test_provider"}

    monkeypatch.setattr("analysis.technical.get_ohlcv", lambda **kwargs: fake_df)

    snap = analyse("TEST_STOCK")
    assert snap.timeframe == "1D (Daily)"
    assert snap.as_of == str(dates[-1].date())
    assert snap.data_source == "test_provider"
    assert snap.rsi < 30.0  # Strongly declining prices must have oversold RSI, not 99.9!
    assert snap.macd_signal == "BEARISH"
    assert "Below signal line" in snap.macd_detail or "Bearish crossover" in snap.macd_detail


def test_technical_analyst_key_points_formatting():
    """Verify TechnicalAnalyst formats crisp key points with timeframe and parameters."""
    reg = build_registry()
    ta = TechnicalAnalyst(reg)

    mock_result = {
        "symbol": "TRENT",
        "ltp": 2793.6,
        "rsi": 33.7,
        "macd": -44.13,
        "macd_sig": -33.18,
        "macd_hist": -10.95,
        "macd_signal": "BEARISH",
        "macd_detail": "Below signal line",
        "ema20": 2890.8,
        "ema50": 2927.0,
        "sma200": 2967.1,
        "support": 2773.2,
        "resistance": 2855.1,
        "timeframe": "1D (Daily)",
        "as_of": "2026-09-08",
        "data_source": "NSE EOD",
        "score": -39,
        "verdict": "BEARISH",
        "signals": [],
    }

    ta.registry.execute = lambda name, args: mock_result

    report = ta.analyze("TRENT", "NSE")
    assert report.analyst == "Technical"
    assert any("RSI(14, 1D (Daily)): 33.7" in p for p in report.key_points)
    assert any("MACD(12,26,9, 1D (Daily)): -44.13" in p for p in report.key_points)
    assert any("Below signal line" in p for p in report.key_points)
    assert not any("bearish crossover" in p for p in report.key_points)  # Must NOT falsely claim crossover!
    assert any("Provenance: NSE EOD as of 2026-09-08" in p for p in report.key_points)

    # Test compact signals table header
    compact = build_compact_signals("TRENT", "NSE", [report], ltp=2793.6)
    assert "Timeframe: 1D (Daily EOD)" in compact
    assert "As-of: 2026-09-08" in compact
