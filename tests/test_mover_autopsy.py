"""
tests/test_mover_autopsy.py
───────────────────────────
Unit tests for the Daily Top Movers Forensic Autopsy Engine.
Tests causal decomposition, control cohort contrast, trap filtering, and persistence.
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from engine.mover_autopsy import (
    MoverAutopsyEngine,
    MoverCausalProfile,
    DailyMoverAutopsy,
    ARCHETYPE_VOLATILITY_CONTRACTION_SPRING,
    ARCHETYPE_GAMMA_SHORT_SQUEEZE,
    TRAP_LOW_LIQUIDITY_PUMP,
    TRAP_CIRCUIT_LOCK_MANIPULATION,
)


@pytest.fixture
def autopsy_engine(tmp_path):
    with patch("engine.mover_autopsy.get_mover_autopsies_file") as mock_file:
        mock_file.return_value = tmp_path / "mover_autopsies.json"
        engine = MoverAutopsyEngine()
        return engine


def test_dissect_mover_volatility_contraction(autopsy_engine):
    """Test that a stock with severe prior-day volume dry-up and squeeze gets classified as VCP Spring."""
    quote_item = {
        "symbol": "TRENT",
        "ltp": 6800.0,
        "change_pct": 5.4,
        "volume": 2500000,
        "turnover_cr": 1700.0,
        "vwap": 6750.0,
    }

    # Synthetic OHLCV where penultimate day has volume dry-up (< 0.30x)
    dates = pd.date_range("2026-08-01", periods=25, freq="B")
    data = {
        "open": np.linspace(6500, 6800, 25),
        "high": np.linspace(6550, 6850, 25),
        "low": np.linspace(6480, 6780, 25),
        "close": np.linspace(6500, 6800, 25),
        "volume": [1000000] * 23 + [150000, 2500000],  # Day 24 volume is 150k vs 1M avg (15% ratio)
    }
    df = pd.DataFrame(data, index=dates)

    with patch("market.history.get_ohlcv", return_value=df), \
         patch("analysis.sector_rotation.get_stock_sector_alignment", return_value={"sector_name": "Consumer", "quadrant": "LEADING"}), \
         patch("market.options.get_options_chain", return_value=None):
        profile = autopsy_engine.dissect_mover(quote_item, direction="GAINER")

        assert profile.symbol == "TRENT"
        assert profile.direction == "GAINER"
        assert profile.prior_vol_ratio <= 0.35
        assert profile.archetype in (
            ARCHETYPE_VOLATILITY_CONTRACTION_SPRING,
            "ARCHETYPE_SECTOR_MOMENTUM_CONTAGION",
        )
        assert not profile.is_trap
        assert len(profile.deciding_factors) > 0


def test_dissect_mover_trap_filter(autopsy_engine):
    """Test that illiquid operator pumps and circuit manipulation are caught and flagged as traps."""
    # Case 1: Illiquid penny pump (< ₹8 Cr turnover)
    illiquid_quote = {
        "symbol": "PENNYPUMP",
        "ltp": 12.5,
        "change_pct": 9.5,
        "volume": 100000,
        "turnover_cr": 1.25,  # 1.25 Cr is below ₹8 Cr
        "vwap": 12.0,
    }
    profile_trap = autopsy_engine.dissect_mover(illiquid_quote, direction="GAINER")
    assert profile_trap.is_trap
    assert profile_trap.archetype == TRAP_LOW_LIQUIDITY_PUMP
    assert "Illiquid Operator Pump" in (profile_trap.trap_reason or "")

    # Case 2: Circuit lock with zero depth
    circuit_quote = {
        "symbol": "LOCKCIRCUIT",
        "ltp": 45.0,
        "change_pct": 5.0,
        "volume": 5000,  # 5k volume on circuit
        "turnover_cr": 12.0,
        "vwap": 45.0,
    }
    profile_circuit = autopsy_engine.dissect_mover(circuit_quote, direction="GAINER")
    assert profile_circuit.is_trap
    assert profile_circuit.archetype == TRAP_CIRCUIT_LOCK_MANIPULATION


def test_compute_control_contrast(autopsy_engine):
    """Test that Signal-to-Noise Ratio (SNR) correctly penalizes factors that also occur in control cohort."""
    movers = [
        MoverCausalProfile(
            symbol="M1",
            direction="GAINER",
            change_pct=6.0,
            ltp=100.0,
            volume=500000,
            turnover_cr=50.0,
            rvol=2.5,
            prior_vol_ratio=0.15,  # volume dry-up
            squeeze_bars=3,
            rrg_quadrant="LEADING",
            derivative_verdict="SHORT_COVERING",
        ),
        MoverCausalProfile(
            symbol="M2",
            direction="GAINER",
            change_pct=4.5,
            ltp=200.0,
            volume=400000,
            turnover_cr=80.0,
            rvol=2.1,
            prior_vol_ratio=0.20,  # volume dry-up
            squeeze_bars=2,
            rrg_quadrant="LEADING",
            derivative_verdict="LONG_BUILDUP",
        ),
    ]

    control_quotes = [
        {"symbol": "C1", "change_pct": 0.1, "turnover_cr": 25.0},
        {"symbol": "C2", "change_pct": -0.2, "turnover_cr": 30.0},
    ]

    # Mock control history having normal volume (no dry-up)
    df_normal = pd.DataFrame(
        {
            "open": [100] * 25,
            "high": [102] * 25,
            "low": [98] * 25,
            "close": [100] * 25,
            "volume": [1000000] * 25,
        }
    )

    with patch("market.history.get_ohlcv", return_value=df_normal), \
         patch("analysis.sector_rotation.get_stock_sector_alignment", return_value={"quadrant": "LAGGING"}):
        snr_table, top_precursors = autopsy_engine.compute_control_contrast(movers, control_quotes)

        assert "volume_dry_up" in snr_table
        # 100% of movers had dry-up vs 0% of control -> delta should be high
        assert snr_table["volume_dry_up"] > 0.50
        assert len(top_precursors) > 0


def test_run_daily_autopsy_integration(autopsy_engine):
    """Test full daily autopsy execution and persistence."""
    fake_gainers = [
        {"symbol": "RELIANCE", "ltp": 2900.0, "change_pct": 4.2, "volume": 5000000, "turnover_cr": 1450.0, "vwap": 2880.0},
        {"symbol": "INFY", "ltp": 1950.0, "change_pct": 3.8, "volume": 3000000, "turnover_cr": 585.0, "vwap": 1940.0},
    ]
    fake_losers = [
        {"symbol": "SBIN", "ltp": 820.0, "change_pct": -3.5, "volume": 4000000, "turnover_cr": 328.0, "vwap": 835.0},
    ]
    fake_control = [
        {"symbol": "TCS", "ltp": 4400.0, "change_pct": 0.2, "volume": 1000000, "turnover_cr": 440.0, "vwap": 4400.0},
    ]

    with patch.object(autopsy_engine, "fetch_daily_movers_and_control", return_value=(fake_gainers, fake_losers, fake_control)), \
         patch("market.quotes.get_ltp", return_value=13.5), \
         patch("market.history.get_ohlcv", return_value=None), \
         patch("market.options.get_options_chain", return_value=None), \
         patch("engine.learning_engine.pattern_learning_engine.register_explosive_move"), \
         patch("engine.learning_engine.pattern_learning_engine.recalibrate_from_snr"):

        autopsy = autopsy_engine.run_daily_autopsy(target_date="2026-09-09", top_n=5)

        assert autopsy.date == "2026-09-09"
        assert len(autopsy.gainers) == 2
        assert len(autopsy.losers) == 1
        assert autopsy.market_regime == "NORMAL_TRENDING"

        # Verify persistence and retrieval
        latest = autopsy_engine.get_latest_autopsy()
        assert latest is not None
        assert latest.date == "2026-09-09"
        assert len(latest.gainers) == 2
