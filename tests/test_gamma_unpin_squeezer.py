"""
tests/test_gamma_unpin_squeezer.py
──────────────────────────────────
Deterministic unit tests for 0DTE Expiry Afternoon Dealer Gamma Unpin Volatility Squeezer.
"""

from __future__ import annotations

import pytest

from engine.detection_context import build_detection_context, detector_registry
from engine.detectors.gamma_unpin_squeezer import (
    detect_0dte_gamma_unpin,
)


@pytest.fixture
def synthetic_nifty_chain():
    return [
        {
            "strike": 24900.0,
            "option_type": "CE",
            "oi": 50000,
            "ltp": 190.0,
            "iv": 0.14,
            "gamma": 0.0012,
        },
        {
            "strike": 25000.0,
            "option_type": "CE",
            "oi": 150000,
            "ltp": 105.0,
            "iv": 0.13,
            "gamma": 0.0022,
        },
        {
            "strike": 25100.0,
            "option_type": "CE",
            "oi": 200000,
            "ltp": 35.0,
            "iv": 0.12,
            "gamma": 0.0035,
        },
        {
            "strike": 25200.0,
            "option_type": "CE",
            "oi": 80000,
            "ltp": 8.0,
            "iv": 0.11,
            "gamma": 0.0018,
        },
        {
            "strike": 24900.0,
            "option_type": "PE",
            "oi": 80000,
            "ltp": 6.0,
            "iv": 0.13,
            "gamma": 0.0015,
        },
        {
            "strike": 25000.0,
            "option_type": "PE",
            "oi": 180000,
            "ltp": 22.0,
            "iv": 0.12,
            "gamma": 0.0030,
        },
        {
            "strike": 25100.0,
            "option_type": "PE",
            "oi": 60000,
            "ltp": 75.0,
            "iv": 0.13,
            "gamma": 0.0020,
        },
        {
            "strike": 25200.0,
            "option_type": "PE",
            "oi": 30000,
            "ltp": 160.0,
            "iv": 0.14,
            "gamma": 0.0010,
        },
    ]


def test_gamma_unpin_bullish_squeeze(synthetic_nifty_chain):
    """
    When NIFTY unpins above the Zero-Gamma Flip strike on expiry afternoon
    with positive microstructure order flow, detector fires 0DTE_GAMMA_UNPIN_SQUEEZE.
    """
    ctx = build_detection_context(
        symbol="NSE:NIFTY",
        ltp=25160.0,
        vwap=25120.0,
        option_chain=synthetic_nifty_chain,
        extra_metrics={
            "depth_50": {
                "obi_50": 0.35,
                "micro_price_skew_bps": 0.8,
            }
        },
    )

    alerts = detect_0dte_gamma_unpin(ctx)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.alert_type == "0DTE_GAMMA_UNPIN_SQUEEZE"
    assert a.direction == "BULLISH"
    assert a.symbol == "NIFTY"
    assert a.strike == 25200.0
    assert a.option_type == "CE"
    assert a.actionable_plan["action"] == "BUY CE"
    assert a.confidence >= 86
    assert a.metrics["asymmetric_rr"] == "1:3.0+"


def test_gamma_unpin_bearish_flush():
    """
    When SENSEX breaks down below Zero-Gamma Flip strike on Friday expiry afternoon,
    detector fires Bearish 0DTE Gamma Flush.
    """
    sensex_chain = [
        {
            "strike": 81000.0,
            "option_type": "CE",
            "oi": 80000,
            "ltp": 220.0,
            "iv": 0.14,
            "gamma": 0.0015,
        },
        {
            "strike": 81200.0,
            "option_type": "CE",
            "oi": 150000,
            "ltp": 95.0,
            "iv": 0.13,
            "gamma": 0.0025,
        },
        {
            "strike": 81400.0,
            "option_type": "CE",
            "oi": 200000,
            "ltp": 25.0,
            "iv": 0.12,
            "gamma": 0.0035,
        },
        {
            "strike": 81000.0,
            "option_type": "PE",
            "oi": 190000,
            "ltp": 38.0,
            "iv": 0.12,
            "gamma": 0.0032,
        },
        {
            "strike": 81200.0,
            "option_type": "PE",
            "oi": 80000,
            "ltp": 120.0,
            "iv": 0.13,
            "gamma": 0.0022,
        },
        {
            "strike": 81400.0,
            "option_type": "PE",
            "oi": 30000,
            "ltp": 280.0,
            "iv": 0.14,
            "gamma": 0.0012,
        },
    ]

    ctx = build_detection_context(
        symbol="BSE:SENSEX",
        ltp=80920.0,
        vwap=81050.0,
        option_chain=sensex_chain,
        extra_metrics={
            "depth_50": {
                "obi_50": -0.40,
                "micro_price_skew_bps": -0.9,
            }
        },
    )

    alerts = detect_0dte_gamma_unpin(ctx)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.alert_type == "0DTE_GAMMA_UNPIN_SQUEEZE"
    assert a.direction == "BEARISH"
    assert a.symbol == "SENSEX"
    assert a.option_type == "PE"
    assert a.actionable_plan["action"] == "BUY PE"


def test_gamma_unpin_non_expiry_index_rejected(synthetic_nifty_chain):
    """
    Per Rule 37 (single weekly expiry mandate), non-weekly indices like
    BANKNIFTY or MIDCPNIFTY must be rejected from 0DTE unpin squeezer.
    """
    ctx = build_detection_context(
        symbol="NSE:BANKNIFTY",
        ltp=52000.0,
        vwap=51950.0,
        option_chain=synthetic_nifty_chain,
    )
    alerts = detect_0dte_gamma_unpin(ctx)
    assert len(alerts) == 0


def test_gamma_unpin_registered_in_detector_registry():
    """Verify that GammaUnpinSqueezerDetector is registered in detector_registry."""
    det = detector_registry.get("0dte_gamma_unpin")
    assert det is not None
    assert det.detector_slug == "0dte_gamma_unpin"
    assert "FNO_INDEX" in det.supported_segments
