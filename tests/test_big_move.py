import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from analysis.big_move import (
    compute_ttm_squeeze,
    analyze_options_flow,
    predict_large_move,
    BigMovePrediction,
    SqueezeState,
)
from brokers.base import OptionsContract


@pytest.fixture
def squeeze_coiling_df():
    # Construct a dataset with tight, low-volatility range (inside Keltner channels)
    dates = pd.date_range("2025-01-01", periods=40, freq="D")
    closes = [1000.0 + np.sin(i / 2.0) * 2.0 for i in range(40)]
    return pd.DataFrame({
        "open": closes,
        "high": [c + 3.0 for c in closes],
        "low": [c - 3.0 for c in closes],
        "close": closes,
        "volume": [100000] * 40,
    }, index=dates)


@pytest.fixture
def bullish_breakout_df():
    # Construct a dataset with sudden upward explosion
    dates = pd.date_range("2025-01-01", periods=40, freq="D")
    base_closes = [1000.0 + i * 0.2 for i in range(35)]
    # Explosive final 5 bars
    surge_closes = [1007.0, 1025.0, 1050.0, 1080.0, 1120.0]
    all_closes = base_closes + surge_closes
    return pd.DataFrame({
        "open": all_closes,
        "high": [c + 10.0 for c in all_closes],
        "low": [c - 5.0 for c in all_closes],
        "close": all_closes,
        "volume": [100000] * 35 + [500000] * 5,
    }, index=dates)


def test_compute_ttm_squeeze_coiling(squeeze_coiling_df):
    squeeze = compute_ttm_squeeze(squeeze_coiling_df)
    assert squeeze.is_squeeze_on is True
    assert squeeze.squeeze_duration_bars >= 1


def test_compute_ttm_squeeze_fired_breakout(bullish_breakout_df):
    squeeze = compute_ttm_squeeze(bullish_breakout_df)
    assert squeeze.momentum_value > 0
    assert "BULLISH" in squeeze.momentum_direction


def test_analyze_options_flow_long_buildup():
    fake_chain = [
        OptionsContract(symbol="NIFTY24APR24000CE", underlying="NIFTY", expiry="2025-04-30", strike=24000, option_type="CE", last_price=150, oi=50000, oi_change=5000, volume=10000),
        OptionsContract(symbol="NIFTY24APR24000PE", underlying="NIFTY", expiry="2025-04-30", strike=24000, option_type="PE", last_price=80, oi=80000, oi_change=12000, volume=20000),
    ]
    with patch("market.options.get_options_chain", return_value=fake_chain):
        flow = analyze_options_flow("NIFTY", ltp=24100)
        assert flow.has_options is True
        assert flow.pcr == 1.6  # 80000 / 50000
        assert flow.dominant_regime == "LONG_BUILDUP"
        assert flow.institutional_sentiment == "AGGRESSIVE_BULLISH"



def test_predict_large_move_bullish_high_probability(bullish_breakout_df):
    with (
        patch("analysis.sector_rotation.get_stock_sector_alignment", return_value={"sector": "METALS", "quadrant": "LEADING"}),
    ):
        pred = predict_large_move("TATASTEEL", df=bullish_breakout_df)
        assert isinstance(pred, BigMovePrediction)
        assert pred.directional_bias == "BULLISH"
        assert pred.directional_probability >= 75
        assert pred.target_price > pred.ltp
        assert pred.invalidation_price < pred.ltp
        assert pred.expected_move_pct > 0
        assert len(pred.catalysts) > 0
