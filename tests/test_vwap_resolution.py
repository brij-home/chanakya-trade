"""
tests/test_vwap_resolution.py
──────────────────────────────
Regression tests verifying:
1. Quote enrichment populates VWAP from computed session bars or WebSocket atp.
2. Dynamic momentum escape for VWAP overextension filter in both Call and Put index detectors.
"""

from __future__ import annotations

import pandas as pd
from unittest.mock import patch

from brokers.base import Quote
from engine.detectors.index_call_setup import detect_index_call_setup
from market.quotes import _enrich_quote
from market.vwap_session_cache import get_vwap_session_cache


def test_quote_enrichment_populates_vwap_for_index():
    get_vwap_session_cache().clear()
    raw_q = Quote(
        symbol="NIFTY",
        last_price=22500.0,
        open=22450.0,
        high=22550.0,
        low=22420.0,
        close=22400.0,
        volume=1000000,
        vwap=None,
    )
    with patch("market.quotes.get_computed_vwap", return_value=22485.5):
        enriched = _enrich_quote(
            raw_q,
            instrument="NSE:NIFTY",
            provider="test",
            source="REST",
            correlation_id="corr-test",
        )
        assert enriched.vwap == 22485.5
        assert enriched.last_price == 22500.0


def test_index_call_setup_dynamic_momentum_vwap_escape():
    """Verify that explosive CE momentum escapes the strict 0.65% VWAP overextension cap up to 2.0%."""
    spot = 22680.0
    vwap = 22500.0  # spot is +0.80% above VWAP (> 0.65% default cap)

    # 1. Normal momentum (ce_pchange=5%, vol_oi=0.8) -> suppressed by 0.65% cap
    class MockCall:
        option_type = "CE"
        strike = 22700.0
        last_price = 120.0
        volume = 2000
        oi = 4000
        pchange = 5.0
        oi_change = -100

    alerts_suppressed = detect_index_call_setup(
        underlying="NIFTY",
        spot=spot,
        chain=[MockCall()],
        vwap=vwap,
        ignore_time_gate=True,
    )
    assert len(alerts_suppressed) == 0

    # 2. Explosive momentum (ce_pchange=30%, vol_oi=4.1x, volume=25000) -> bypasses 0.65% cap (cap rises to 2.0%)
    class MockExplosiveCall:
        option_type = "CE"
        strike = 22700.0
        last_price = 145.0
        volume = 25000
        oi = 6000
        pchange = 30.0
        oi_change = -500

    dates = pd.date_range("2026-09-29 09:15", periods=10, freq="5min")
    df_5m = pd.DataFrame(
        {
            "open": [22650.0] * 10,
            "high": [22690.0] * 10,
            "low": [22640.0] * 10,
            "close": [22680.0] * 10,
            "volume": [50000] * 10,
        },
        index=dates,
    )

    with patch("market.sentiment.get_market_breadth", return_value=None):
        alerts_explosive = detect_index_call_setup(
            underlying="NIFTY",
            spot=spot,
            chain=[MockExplosiveCall()],
            vwap=vwap,
            ohlcv_5m=df_5m,
            prev_day_low=22645.0,  # triggers PDL demand rejection
            day_low=22640.0,
            ignore_time_gate=True,
        )
        assert len(alerts_explosive) > 0
        assert alerts_explosive[0].metrics["vwap"] == vwap
