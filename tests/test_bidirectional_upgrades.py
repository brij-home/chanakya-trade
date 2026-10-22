"""
tests/test_bidirectional_upgrades.py
────────────────────────────────────
Deterministic unit tests verifying the bidirectional calibration across:
  1. Bidirectional Obstacle Runway & Roadblock Geometry in engine/institutional_context.py
  2. Bidirectional Reverse Locomotive Polarization in engine/market_regime_gate.py
  3. Bidirectional Regime Filtering in AutoAlertEngine (Call & Put Setups)
  4. Domestic WebSocket Real-Time Event-Driven Impulse Spike Detector
"""

import time
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd

from engine.institutional_context import (
    build_institutional_context,
)
from engine.market_regime_gate import (
    _fetch_locomotive_polarization,
    evaluate_market_regime,
)


# ── Test 1: Bidirectional Obstacle Runway (institutional_context.py) ───


def test_bidirectional_obstacle_runway_bullish():
    """Verify that overhead resistance (ceilings) are calculated for BULLISH setups."""
    # Synthetic 5m data
    dates = pd.date_range("2026-10-21 09:15", periods=20, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(24900, 25000, 20),
            "high": np.linspace(24910, 25020, 20),
            "low": np.linspace(24890, 24990, 20),
            "close": np.linspace(24905, 25015, 20),
            "volume": np.ones(20) * 50000,
        },
        index=dates,
    )

    # Mock daily levels with CPR and PDH
    mock_dl = MagicMock()
    mock_dl.pdh = 25050.0  # 35 pts above 25015
    mock_dl.pdl = 24800.0
    mock_dl.pdc = 24950.0
    mock_dl.atr_14 = 100.0
    mock_dl.cpr = {"pivot": 24933.3, "tc": 24950.0, "bc": 24916.6, "is_narrow": False}
    mock_dl.camarilla = {"h4": 25060.0, "l4": 24840.0}

    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        ctx = build_institutional_context(
            symbol="NIFTY",
            ltp=25015.0,
            df_5m=df_5m,
            rvol=2.0,
            direction="BULLISH",
        )

        assert ctx.velocity.direction == "BULLISH"
        # Nearest roadblock overhead is PDH at 25050.0 (dist = 35.0 pts)
        assert ctx.velocity.nearest_roadblock == 25050.0
        assert ctx.velocity.nearest_roadblock_type == "PDH"
        assert ctx.velocity.obstacle_runway_pts == 35.0
        # 35.0 pts / 100.0 ATR = 0.35 ATR multiple < 1.5 -> choked!
        assert ctx.velocity.is_runway_choked is True


def test_bidirectional_obstacle_runway_bearish():
    """Verify that underlying support (floors) are calculated for BEARISH setups."""
    dates = pd.date_range("2026-10-21 09:15", periods=20, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(25000, 24900, 20),
            "high": np.linspace(25010, 24910, 20),
            "low": np.linspace(24990, 24890, 20),
            "close": np.linspace(24995, 24895, 20),
            "volume": np.ones(20) * 50000,
        },
        index=dates,
    )

    mock_dl = MagicMock()
    mock_dl.pdh = 25150.0
    mock_dl.pdl = 24870.0  # Only 25 pts below 24895!
    mock_dl.pdc = 25000.0
    mock_dl.atr_14 = 100.0
    mock_dl.cpr = {"pivot": 25006.6, "tc": 25020.0, "bc": 24993.3, "is_narrow": False}
    mock_dl.camarilla = {"h4": 25100.0, "l4": 24850.0}

    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        ctx = build_institutional_context(
            symbol="NIFTY",
            ltp=24895.0,
            df_5m=df_5m,
            rvol=2.0,
            direction="BEARISH",
        )

        assert ctx.velocity.direction == "BEARISH"
        # Nearest roadblock below is PDL at 24870.0 (dist = 25.0 pts)
        assert ctx.velocity.nearest_roadblock == 24870.0
        assert ctx.velocity.nearest_roadblock_type == "PDL"
        assert ctx.velocity.obstacle_runway_pts == 25.0
        # 25.0 / 100.0 ATR = 0.25 ATR multiple < 1.5 -> choked!
        assert ctx.velocity.is_runway_choked is True


def test_bidirectional_obstacle_runway_clear_skies():
    """Verify that when no hurdles exist within proximity, runway is open."""
    dates = pd.date_range("2026-10-21 09:15", periods=20, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": np.linspace(25000, 24500, 20),
            "high": np.linspace(25010, 24510, 20),
            "low": np.linspace(24990, 24490, 20),
            "close": np.linspace(24995, 24495, 20),
            "volume": np.ones(20) * 50000,
        },
        index=dates,
    )

    mock_dl = MagicMock()
    # Floor hurdles are far below (pdl=24000 vs ltp=24495, dist=495 pts on 100 ATR)
    mock_dl.pdh = 25200.0
    mock_dl.pdl = 24000.0
    mock_dl.pdc = 25100.0
    mock_dl.atr_14 = 100.0
    mock_dl.cpr = {"pivot": 25100.0, "tc": 25120.0, "bc": 25080.0, "is_narrow": False}
    mock_dl.camarilla = {"h4": 25250.0, "l4": 23900.0}

    with patch("engine.daily_levels.get_daily_levels", return_value=mock_dl):
        ctx = build_institutional_context(
            symbol="NIFTY",
            ltp=24495.0,
            df_5m=df_5m,
            rvol=2.0,
            direction="BEARISH",
        )

        assert ctx.velocity.direction == "BEARISH"
        assert ctx.velocity.nearest_roadblock == 24000.0
        assert ctx.velocity.nearest_roadblock_type == "PDL"
        # 495 pts / 100 ATR = 4.95 ATR multiple >= 1.5 -> NOT choked!
        assert ctx.velocity.is_runway_choked is False


# ── Test 2: Bidirectional Reverse Locomotive Polarization (market_regime_gate.py) ───


def test_locomotive_polarization_bullish_trap():
    """Verify Bullish Locomotive Trap: Heavyweights held green while A/D < 0.85 -> NAKED CALLS VETOED."""
    mock_quotes = {
        "NSE:HDFCBANK": MagicMock(change_pct=0.85),
        "NSE:RELIANCE": MagicMock(change_pct=0.45),
        "NSE:ICICIBANK": MagicMock(change_pct=0.30),
    }

    with patch("market.quotes.get_quote", return_value=mock_quotes):
        is_loco, detail, direction = _fetch_locomotive_polarization(ad_ratio=0.55)
        assert is_loco is True
        assert direction == "BULLISH"
        assert "Locomotive Trap" in detail
        assert "A/D 0.55" in detail


def test_locomotive_polarization_bearish_reverse_trap():
    """Verify Bearish Reverse Locomotive Trap: Heavyweights dumped red while A/D > 1.25 -> NAKED PUTS VETOED."""
    mock_quotes = {
        "NSE:HDFCBANK": MagicMock(change_pct=-0.95),
        "NSE:RELIANCE": MagicMock(change_pct=-0.65),
        "NSE:ICICIBANK": MagicMock(change_pct=-0.40),
    }

    with patch("market.quotes.get_quote", return_value=mock_quotes):
        is_loco, detail, direction = _fetch_locomotive_polarization(ad_ratio=1.65)
        assert is_loco is True
        assert direction == "BEARISH"
        assert "Reverse Locomotive Trap" in detail
        assert "A/D 1.65" in detail


def test_locomotive_polarization_neutral_breadth():
    """Verify that when market breadth is balanced (0.85 <= A/D <= 1.25), no locomotive trap fires."""
    is_loco, detail, direction = _fetch_locomotive_polarization(ad_ratio=1.05)
    assert is_loco is False
    assert direction == ""


def test_evaluate_market_regime_reverse_locomotive_banner():
    """Verify evaluate_market_regime banner and reason under reverse locomotive polarization."""
    with (
        patch("engine.market_regime_gate._fetch_vix", return_value=14.0),
        patch("engine.market_regime_gate._fetch_ad_ratio", return_value=1.50),
        patch(
            "engine.market_regime_gate._fetch_locomotive_polarization",
            return_value=(True, "Reverse Locomotive Trap Mock", "BEARISH"),
        ),
    ):
        regime = evaluate_market_regime(force_refresh=True)
        assert regime.is_locomotive_polarized is True
        assert regime.locomotive_direction == "BEARISH"
        assert "REVERSE LOCOMOTIVE POLARIZATION — NAKED PUTS VETOED" in regime.banner
        assert "Naked index puts suppressed" in regime.reason


# ── Test 3: AutoAlertEngine Domestic Impulse Tick History & Detector ───


def test_domestic_tick_impulse_spike_tracker():
    """Verify AutoAlertEngine records domestic tick history and detects rapid impulse moves."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    now = time.time()

    # Feed ticks for NIFTY over a 5-second interval showing 0.20% impulse jump (25000 -> 25050)
    tick1 = {"symbol": "NSE:NIFTY", "ltp": 25000.0, "timestamp": now - 5.0}
    tick2 = {"symbol": "NSE:NIFTY", "ltp": 25050.0, "timestamp": now}

    # First tick stores in history
    engine._on_domestic_tick(tick1)
    history = engine._domestic_tick_history["NIFTY"]
    assert len(history) == 1
    assert history[0] == (now - 5.0, 25000.0)

    # Mock _scan_single_domestic_symbol so it doesn't run full background network queries
    with patch.object(engine, "_scan_single_domestic_symbol"):
        engine._on_domestic_tick(tick2)

        # Delta is (25050 - 25000) / 25000 * 100 = 0.20% in 5s (threshold for index is 0.15%)
        # Cooldown should be recorded
        assert engine._domestic_last_surge_eval.get("NIFTY") == now

        # Subsequent tick within cooldown (e.g. 10s later) must NOT trigger another scan
        tick3 = {"symbol": "NSE:NIFTY", "ltp": 25100.0, "timestamp": now + 10.0}
        engine._on_domestic_tick(tick3)
        # last surge eval should still be unchanged or preserved
        assert engine._domestic_last_surge_eval.get("NIFTY") == now
