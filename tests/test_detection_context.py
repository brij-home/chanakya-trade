"""
tests/test_detection_context.py
─────────────────────────────────
Unit tests verifying the DetectionContext dataclass, BaseDetector protocol,
and DetectorRegistry for pure and decoupled detector evaluation.
"""

from __future__ import annotations

from datetime import datetime
import pandas as pd
import pytest

from engine.alert_model import AutoAlert
from engine.detection_context import (
    BaseDetector,
    DetectionContext,
    DetectorRegistry,
    FunctionalDetectorAdapter,
    build_detection_context,
)


def test_build_detection_context_normalization():
    """Verify build_detection_context normalizes symbols and sets defaults."""
    ctx = build_detection_context(
        "NSE:TATASTEEL",
        exchange="NSE",
        ltp=155.50,
        prev_close=150.0,
    )
    assert ctx.symbol == "NSE:TATASTEEL"
    assert ctx.canonical_symbol == "TATASTEEL"
    assert ctx.exchange == "NSE"
    assert ctx.ltp == 155.50
    assert ctx.day_change_pct == 3.67
    assert ctx.is_index is False


def test_detection_context_index_detection():
    """Verify is_index property detects benchmark indices."""
    ctx_nifty = build_detection_context("NIFTY", ltp=25000.0)
    assert ctx_nifty.is_index is True

    ctx_stock = build_detection_context("RELIANCE", ltp=3000.0)
    assert ctx_stock.is_index is False


def test_detection_context_immutability():
    """Verify that DetectionContext is frozen to prevent side-effects."""
    ctx = build_detection_context("INFY", ltp=1500.0)
    with pytest.raises(Exception):
        ctx.ltp = 1520.0  # type: ignore


class MockBreakoutDetector:
    """Mock detector implementing BaseDetector protocol."""

    detector_slug = "mock_breakout"
    detector_name = "Mock Breakout Detector"
    supported_segments = ("EQUITY", "FNO_STOCK")

    def detect(self, ctx: DetectionContext) -> list[AutoAlert]:
        if ctx.ltp > 200.0:
            return [
                AutoAlert(
                    alert_id=f"aa-mock-{ctx.canonical_symbol.lower()}-20260926",
                    alert_type="MOCK_BREAKOUT",
                    stage="IGNITED",
                    symbol=ctx.canonical_symbol,
                    exchange=ctx.exchange,
                    direction="BULLISH",
                    ltp=ctx.ltp,
                    trigger_level=200.0,
                    stop_loss=195.0,
                    target_level=210.0,
                    headline=f"Mock Breakout: {ctx.canonical_symbol}",
                    summary="Test mock summary",
                    environment="TEST",
                )
            ]
        return []


def test_base_detector_protocol_compliance():
    """Verify that MockBreakoutDetector satisfies runtime BaseDetector check."""
    detector = MockBreakoutDetector()
    assert isinstance(detector, BaseDetector)


def test_detector_registry_and_evaluation():
    """Verify DetectorRegistry registration, segment filtering, and evaluation."""
    registry = DetectorRegistry()
    detector = MockBreakoutDetector()
    registry.register(detector)

    assert len(registry.get_detectors()) == 1
    assert len(registry.get_detectors("COMMODITY")) == 0
    assert len(registry.get_detectors("EQUITY")) == 1

    # Candidate below trigger: 0 alerts
    ctx_low = build_detection_context("SBIN", ltp=180.0)
    alerts_low = registry.evaluate_all(ctx_low)
    assert len(alerts_low) == 0

    # Candidate above trigger: 1 alert
    ctx_high = build_detection_context("SBIN", ltp=215.0)
    alerts_high = registry.evaluate_all(ctx_high)
    assert len(alerts_high) == 1
    assert alerts_high[0].alert_id == "aa-mock-sbin-20260926"
    assert alerts_high[0].symbol == "SBIN"


def test_functional_detector_adapter():
    """Verify FunctionalDetectorAdapter wraps standard functions seamlessly."""
    def legacy_func(ctx: DetectionContext):
        if ctx.day_change_pct >= 5.0:
            return AutoAlert(
                alert_id=f"aa-leg-{ctx.canonical_symbol.lower()}-20260926",
                alert_type="LEGACY_MOVER",
                stage="IGNITED",
                symbol=ctx.canonical_symbol,
                exchange=ctx.exchange,
                direction="BULLISH",
                ltp=ctx.ltp,
                trigger_level=ctx.ltp,
                stop_loss=ctx.ltp * 0.98,
                target_level=ctx.ltp * 1.04,
                headline="Legacy test",
                summary="Legacy summary",
                environment="TEST",
            )
        return None

    adapter = FunctionalDetectorAdapter(
        slug="legacy_mover",
        name="Legacy Mover",
        supported_segments=("EQUITY",),
        func=legacy_func,
    )

    ctx_flat = build_detection_context("INFY", ltp=100.0, prev_close=100.0)
    assert adapter.detect(ctx_flat) == []

    ctx_surge = build_detection_context("INFY", ltp=106.0, prev_close=100.0)
    res = adapter.detect(ctx_surge)
    assert len(res) == 1
    assert res[0].alert_type == "LEGACY_MOVER"


def test_detection_context_liquidity_and_spread():
    """Verify bid-ask spread calculation and wide spread liquidity warnings."""
    # Normal spread (< 3%)
    ctx_normal = build_detection_context(
        "NIFTY25000CE",
        ltp=100.0,
        extra_metrics={"bid": 99.5, "ask": 100.5},
    )
    assert ctx_normal.bid_ask_spread_pct == 1.0
    assert ctx_normal.liquidity_warning is None

    # Illiquid wide spread (> 3%)
    ctx_wide = build_detection_context(
        "NIFTY25000CE",
        ltp=100.0,
        extra_metrics={"bid": 97.0, "ask": 102.0},
    )
    assert ctx_wide.bid_ask_spread_pct == 5.0
    assert ctx_wide.liquidity_warning is not None
    assert "WIDE BID-ASK SPREAD" in ctx_wide.liquidity_warning


def test_detection_context_atr_and_dynamic_stop():
    """Verify ATR(14) computation and volatility-scaled dynamic stop loss."""
    # Build synthetic 20-bar candle DataFrame
    data = []
    base = 100.0
    for i in range(20):
        h = base + 2.0 + (i * 0.1)
        l = base - 2.0 + (i * 0.1)
        c = base + (i * 0.1)
        data.append({"high": h, "low": l, "close": c, "volume": 1000})

    df = pd.DataFrame(data)
    ctx = build_detection_context("RELIANCE", ltp=102.0, candles_5m=df, vix=15.0)

    atr = ctx.compute_atr(period=14)
    assert atr is not None
    assert atr == pytest.approx(4.0, abs=0.2)

    # Bullish dynamic stop loss: LTP - (ATR * 1.5 * vix_mult)
    bull_sl = ctx.get_dynamic_stop_loss(direction="BULLISH", multiplier=1.5)
    assert bull_sl < 102.0
    assert bull_sl > 90.0

    # Bearish dynamic stop loss: LTP + (ATR * 1.5 * vix_mult)
    bear_sl = ctx.get_dynamic_stop_loss(direction="BEARISH", multiplier=1.5)
    assert bear_sl > 102.0
    assert bear_sl < 115.0


def test_register_default_detectors_integration():
    """Verify register_default_detectors populates the global registry."""
    from engine.detection_context import detector_registry, register_default_detectors

    register_default_detectors()
    detectors = detector_registry.get_detectors()
    assert len(detectors) >= 12

    slugs = {d.detector_slug for d in detectors}
    assert "orb" in slugs
    assert "gamma_blast" in slugs
    assert "circuit_proximity" in slugs
    assert "squeeze_breakout" in slugs
    assert "pre_inflection_dryup" in slugs
