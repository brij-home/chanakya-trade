"""
tests/test_fno_market_leaders_and_inversion_guards.py
────────────────────────────────────────────────────
Regression tests verifying institutional guards against the Trend Inversion Paradox:
1. Universal Call Writer Defense Gate (Single-Stock F&O Short Buildup Veto, e.g. TMPV -8%).
2. Fail-Closed PDL/PDH Liquidity Sweep Gate (prev_day_low=None fails closed, zero false bypass).
3. Trend Day & Relative Strength Lockouts in Turtle Soup and Predator Sweep (protecting gainers like KALYANKJIL & TATACONSUM).
4. Multi-Index & Full-Universe Pre-Open Radar (09:08 AM uncrossing coverage).
5. F&O Derivative Contract Lot-Notional Liquidity Prioritization (e.g. INOXWIND lot 10,250).
"""

from __future__ import annotations

import pandas as pd
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from engine.detectors.gamma_blast import detect_gamma_blast
from engine.detectors.turtle_soup import detect_turtle_soup_sweep
from engine.detectors.liquidity_sweep import detect_predator_liquidity_sweep
from engine.detectors.preopen_bias import _INDEX_UNIVERSE, detect_preopen_stock_catalyst

IST = ZoneInfo("Asia/Kolkata")


def test_single_stock_call_resistance_writing_vetoed_on_falling_stock():
    """
    Validates that when a single-stock F&O equity is trading below VWAP (e.g. TMPV at ₹263 vs VWAP ₹265),
    an expanding Call OI (+ΔOI: +3,033,600) is classified as Short Call Buildup (resistance writing)
    and STRICTLY VETOED from firing a Call Gamma Blast.
    """
    mock_ce = MagicMock()
    mock_ce.symbol = "NSE:TMPV26NOV265CE"
    mock_ce.strike = 265.0
    mock_ce.option_type = "CE"
    mock_ce.last_price = 4.20
    mock_ce.volume = 18299200
    mock_ce.oi = 5076800
    mock_ce.oi_change = 3033600  # Massive Call Writing (+148%)
    mock_ce.pchange = -15.0
    mock_ce.expiry = "2026-11-26"

    alerts = detect_gamma_blast(
        underlying="TMPV",
        spot=263.05,
        chain=[mock_ce],
        vwap=264.98,  # Spot is below VWAP
        day_high=272.95,
        day_low=260.35,
        prev_day_high=None,
        prev_day_low=None,
    )
    assert len(alerts) == 0, (
        "TMPV Call Gamma Blast must be vetoed due to Short Call Buildup below VWAP!"
    )


def test_pdl_sweep_fails_closed_when_prev_day_low_is_none():
    """
    Validates that if prev_day_low is None/0, PDL sweep CANNOT be claimed,
    preventing arbitrary intraday bounces from bypassing the VWAP gate.
    """
    mock_ce = MagicMock()
    mock_ce.symbol = "NSE:TEST26NOV100CE"
    mock_ce.strike = 100.0
    mock_ce.option_type = "CE"
    mock_ce.last_price = 2.50
    mock_ce.volume = 50000
    mock_ce.oi = 100000
    mock_ce.oi_change = -15000  # Unwinding
    mock_ce.pchange = 10.0
    mock_ce.expiry = "2026-11-26"

    # Spot is sitting below VWAP (98.0 vs 100.0) and prev_day_low is None
    alerts = detect_gamma_blast(
        underlying="TESTSTOCK",
        spot=98.0,
        chain=[mock_ce],
        vwap=100.0,
        day_high=102.0,
        day_low=97.5,
        prev_day_high=None,
        prev_day_low=None,  # Not provided
    )
    # Must fail closed: cannot claim PDL sweep when prev_day_low is None,
    # so spot below VWAP must cause rejection!
    assert len(alerts) == 0, "Missing prev_day_low must fail closed and not bypass VWAP gate!"


def test_turtle_soup_trend_day_lockout_protects_strong_gainers():
    """
    Validates that Turtle Soup Sweep does NOT fade market leaders (e.g. TATACONSUM +2.36%)
    with Bearish Upthrust Puts when trading above VWAP in an active uptrend.
    """
    # 20 bars of ascending 15m candles
    prices = [1080.0 + i * 1.5 for i in range(20)]
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 2.0 for p in prices],
            "low": [p - 1.0 for p in prices],
            "close": [p + 1.0 for p in prices],
            "volume": [100000] * 20,
        }
    )
    # Last bar has an upper wick above prior 20-bar high
    df.loc[df.index[-1], "high"] = 1115.0
    df.loc[df.index[-1], "close"] = 1109.0  # closed below 1110

    alert = detect_turtle_soup_sweep(
        symbol="TATACONSUM",
        df=df,
        ltp=1112.0,
        vwap=1103.0,  # Spot is firmly above VWAP
        change_pct=2.36,  # Strong trend day
    )
    assert alert is None, "Turtle Soup must NOT short strong leaders holding above VWAP!"


def test_predator_sweep_trend_day_lockout_protects_strong_gainers():
    """
    Validates that Predator Liquidity Sweep does NOT short top gainers (e.g. KALYANKJIL +3.13%)
    on 5-minute wicks when trading above VWAP.
    """
    prices = [694.0 + i * 1.0 for i in range(20)]
    df = pd.DataFrame(
        {
            "open": prices,
            "high": [p + 1.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": [p + 0.8 for p in prices],
            "volume": [200000] * 20,
        }
    )
    df.loc[df.index[-1], "high"] = 720.0
    df.loc[df.index[-1], "close"] = 716.0

    alert = detect_predator_liquidity_sweep(
        symbol="KALYANKJIL",
        df=df,
        ltp=718.0,
        vwap=705.0,  # Spot is firmly above VWAP
        change_pct=3.13,  # Top gainer
    )
    assert alert is None, "Predator Sweep must NOT short top gainers on opening drive wicks!"


def test_preopen_index_universe_includes_all_major_indices():
    """
    Validates that pre-open radar covers all major traded indices (SENSEX, FINNIFTY, MIDCPNIFTY).
    """
    assert "SENSEX" in _INDEX_UNIVERSE
    assert "MIDCPNIFTY" in _INDEX_UNIVERSE
    assert "FINNIFTY" in _INDEX_UNIVERSE
    assert "BANKEX" in _INDEX_UNIVERSE


def test_preopen_stock_catalyst_fires_on_major_company_gap():
    """
    Validates that a decisive pre-open gap (e.g. +2.8% or -7.0%) fires catalyst alerts
    even when standalone company news drives the price without prior sector bias.
    """
    alert = detect_preopen_stock_catalyst(
        symbol="FORTIS",
        preopen_price=785.0,
        prev_close=764.0,  # +2.75% gap
        direction_bias=None,  # No explicit sector bias required
        min_gap_pct=1.0,
    )
    assert alert is not None
    assert alert.direction == "BULLISH"
    assert "FORTIS" in alert.headline
