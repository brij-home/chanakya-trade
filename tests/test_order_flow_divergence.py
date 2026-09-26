"""
tests/test_order_flow_divergence.py
───────────────────────────────────
Unit tests for Institutional Order Flow & Cumulative Volume Delta (CVD) Divergence Detector.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.detection_context import build_detection_context, detector_registry
from engine.detectors.order_flow import compute_bar_volume_delta, detect_order_flow_divergence


def test_compute_bar_volume_delta():
    """Verify candle volume decomposition into buyer and seller aggressor volume."""
    # Strong bullish bar closing at top tick
    b_vol, s_vol, net_delta = compute_bar_volume_delta(
        open_p=100.0, high_p=105.0, low_p=100.0, close_p=105.0, volume=10000.0
    )
    assert net_delta > 0
    assert b_vol > s_vol

    # Strong bearish bar closing at bottom tick
    b_vol_bear, s_vol_bear, net_delta_bear = compute_bar_volume_delta(
        open_p=105.0, high_p=105.0, low_p=98.0, close_p=98.0, volume=10000.0
    )
    assert net_delta_bear < 0
    assert s_vol_bear > b_vol_bear


def test_bullish_absorption_divergence():
    """Verify detection of institutional accumulation when price sweeps low with higher CVD."""
    # Build 15 synthetic candles
    # Low at bar 5: 24200, volume 50,000, high sell delta
    # Bar 6-13: sideways consolidation
    # Bar 14 (current): price retests 24200, but closed strong near high with 100,000 buyer volume
    data = []
    prices = [24300, 24280, 24250, 24220, 24200, 24205, 24210, 24215, 24220, 24225, 24210, 24205, 24200, 24201]
    
    for i, p in enumerate(prices):
        if i == 4:  # Prior low
            data.append({"open": p + 10, "high": p + 12, "low": p, "close": p + 1, "volume": 50000.0})
        elif i == 13:  # Absorption retest
            data.append({"open": p, "high": p + 15, "low": p - 1, "close": p + 14, "volume": 120000.0})
        else:
            data.append({"open": p, "high": p + 5, "low": p - 5, "close": p + 2, "volume": 10000.0})

    df = pd.DataFrame(data)

    ctx = build_detection_context(
        symbol="NIFTY",
        ltp=24201.0,
        exchange="NSE",
        segment="NFO",
        candles_5m=df,
    )

    alerts = detect_order_flow_divergence(ctx)
    assert len(alerts) >= 1
    alert = alerts[0]
    assert alert.symbol == "NIFTY"
    assert alert.alert_type == "ORDER_FLOW_DIVERGENCE"
    assert alert.direction == "BULLISH"
    assert alert.metrics["pattern"] == "BULLISH_ABSORPTION"
    assert "execution_ticket" in alert.actionable_plan
    assert alert.actionable_plan["execution_ticket"]["smart_routing"]["routing_mode"] in ("DIRECT_LIMIT", "PASSIVE_PEG", "ICEBERG")


def test_order_flow_detector_registered():
    """Verify OrderFlowDivergenceDetector is registered in global DetectorRegistry."""
    slugs = detector_registry.list_registered_slugs()
    assert "order_flow_divergence" in slugs
