"""
tests/test_neutral_and_pairs_detectors.py
──────────────────────────────────────────
Verification suite for Defined-Risk Neutral (Iron Condor) and Pairs Arbitrage detectors.
"""

from __future__ import annotations

import pandas as pd

from engine.detection_context import DetectionContext, detector_registry
from engine.detectors.defined_risk_neutral import detect_defined_risk_neutral, compute_adx
from engine.detectors.pairs_arbitrage import detect_pairs_arbitrage
from engine.pairs import PairAnalysis


def _make_range_bound_candles(n: int = 50, center: float = 24500.0) -> pd.DataFrame:
    """Generate synthetic range-bound consolidating candles with low ADX."""
    records = []
    for i in range(n):
        # Oscillate in a narrow +/- 30 pt band
        offset = 15.0 * (1 if i % 2 == 0 else -1)
        close_p = center + offset
        high_p = close_p + 10.0
        low_p = close_p - 10.0
        open_p = center - offset
        records.append(
            {
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": 5000,
            }
        )
    return pd.DataFrame(records)


def test_adx_computation():
    df = _make_range_bound_candles(40)
    adx_val = compute_adx(df, period=14)
    assert adx_val is not None
    # Oscillating synthetic candles have low directional movement
    assert adx_val < 30.0


def test_defined_risk_neutral_detector_triggers_on_consolidation():
    candles = _make_range_bound_candles(50, center=24500.0)
    ctx = DetectionContext(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        segment="FNO_INDEX",
        ltp=24500.0,
        prev_close=24490.0,  # 0.04% change
        vix=13.0,
        candles_15m=candles,
        option_chain=[
            {"option_type": "PE", "strike": 24300, "oi": 500000},
            {"option_type": "PE", "strike": 24200, "oi": 200000},
            {"option_type": "CE", "strike": 24700, "oi": 600000},
            {"option_type": "CE", "strike": 24800, "oi": 250000},
        ],
    )

    alert = detect_defined_risk_neutral(ctx)
    assert alert is not None
    assert alert.alert_type == "DEFINED_RISK_NEUTRAL"
    assert alert.direction == "NEUTRAL"
    assert "CONDOR" in alert.headline
    assert alert.metrics["strategy"] == "IRON_CONDOR"
    assert alert.metrics["net_credit"] > 0
    assert alert.metrics["max_profit"] > 0
    assert alert.metrics["max_loss"] > 0
    assert alert.actionable_plan["action"] == "EXECUTE_IRON_CONDOR"
    assert "Corridor" in alert.headline


def test_defined_risk_neutral_filters_high_vix():
    candles = _make_range_bound_candles(50, center=24500.0)
    ctx = DetectionContext(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        segment="FNO_INDEX",
        ltp=24500.0,
        prev_close=24500.0,
        vix=26.5,  # Panic VIX regime -> Neutral Iron Condors unsafe!
        candles_15m=candles,
    )
    alert = detect_defined_risk_neutral(ctx)
    assert alert is None


def test_pairs_arbitrage_detector_triggers():
    mock_analysis = PairAnalysis(
        stock_a="HDFCBANK",
        stock_b="ICICIBANK",
        correlation=0.82,
        spread_zscore=-2.45,  # Stretched spread -> Long A, Short B
        spread_mean=120.0,
        spread_std=15.0,
        signal="LONG_A_SHORT_B",
        signal_strength="STRONG",
        half_life=8.5,
        hedge_ratio=1.35,
    )

    ctx = DetectionContext(
        symbol="HDFCBANK",
        canonical_symbol="HDFCBANK",
        exchange="NSE",
        segment="EQUITY",
        ltp=1650.0,
        prev_close=1645.0,
    )

    alert = detect_pairs_arbitrage(ctx, pair_override=mock_analysis)
    assert alert is not None
    assert alert.alert_type == "PAIRS_ARBITRAGE"
    assert "HDFCBANK vs ICICIBANK" in alert.headline
    assert alert.metrics["spread_zscore"] == -2.45
    assert alert.metrics["correlation"] == 0.82
    assert alert.metrics["long_leg"] == "HDFCBANK"
    assert alert.metrics["short_leg"] == "ICICIBANK"
    assert "PAIRS_TRADE_LONG_A_SHORT_B" in alert.actionable_plan["action"]
    assert alert.confidence >= 75


def test_pairs_arbitrage_skips_when_normal():
    mock_analysis = PairAnalysis(
        stock_a="HDFCBANK",
        stock_b="ICICIBANK",
        correlation=0.82,
        spread_zscore=0.45,  # Normal spread, no arbitrage opportunity
        spread_mean=120.0,
        spread_std=15.0,
        signal="NO_SIGNAL",
        signal_strength="WEAK",
        half_life=8.5,
        hedge_ratio=1.35,
    )

    ctx = DetectionContext(
        symbol="HDFCBANK",
        canonical_symbol="HDFCBANK",
        exchange="NSE",
        segment="EQUITY",
        ltp=1650.0,
    )

    alert = detect_pairs_arbitrage(ctx, pair_override=mock_analysis)
    assert alert is None


def test_detector_registry_contains_new_detectors():
    slugs = detector_registry.list_slugs()
    assert "defined_risk_neutral" in slugs
    assert "pairs_arbitrage" in slugs
    assert len(slugs) >= 20  # 18 earlier + 2 new


def test_pairs_arbitrage_detector_rejects_zero_ltp():
    """Verify detect_pairs_arbitrage strictly rejects 0.0 or negative LTP (Invariant 11 & 23)."""
    mock_analysis = PairAnalysis(
        stock_a="TATASTEEL",
        stock_b="JSWSTEEL",
        correlation=0.85,
        spread_zscore=-2.5,
        spread_mean=0.0,
        spread_std=1.0,
        signal="LONG_A_SHORT_B",
        signal_strength="STRONG",
        half_life=10.0,
        hedge_ratio=1.0,
    )

    ctx_zero = DetectionContext(
        symbol="TATASTEEL",
        canonical_symbol="TATASTEEL",
        exchange="NSE",
        segment="EQUITY",
        ltp=0.0,
    )
    assert detect_pairs_arbitrage(ctx_zero, pair_override=mock_analysis) is None

    ctx_neg = DetectionContext(
        symbol="TATASTEEL",
        canonical_symbol="TATASTEEL",
        exchange="NSE",
        segment="EQUITY",
        ltp=-10.0,
    )
    assert detect_pairs_arbitrage(ctx_neg, pair_override=mock_analysis) is None


def test_scan_pairs_arbitrage_resolves_authentic_quotes(monkeypatch):
    """Verify scan_pairs_arbitrage uses authentic quote and NEVER hardcodes 100.0."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    monkeypatch.setattr(engine, "record_alert", lambda a: True)

    mock_analysis = PairAnalysis(
        stock_a="TATASTEEL",
        stock_b="JSWSTEEL",
        correlation=0.85,
        spread_zscore=-2.5,  # Stretched: LONG_A_SHORT_B
        spread_mean=0.0,
        spread_std=1.0,
        signal="LONG_A_SHORT_B",
        signal_strength="STRONG",
        half_life=10.0,
        hedge_ratio=0.13,
        last_close_a=171.50,
        last_close_b=980.00,
    )

    # Patch analyze_pair so only TATASTEEL/JSWSTEEL produces a signal
    def mock_analyze(a, b):
        if a == "TATASTEEL" and b == "JSWSTEEL":
            return mock_analysis
        return None

    monkeypatch.setattr("engine.pairs.analyze_pair", mock_analyze)

    # 1. Provide authentic quote in quotes_map (e.g. ₹172.40)
    class DummyQuote:
        last_price = 172.40

    quotes_map = {"NSE:TATASTEEL": DummyQuote()}

    alerts = engine.scan_pairs_arbitrage(quotes_map=quotes_map)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.symbol == "TATASTEEL"
    assert alert.ltp == 172.40  # Must match real quote, NOT 100.0!
    assert alert.trigger_level == 172.40
    assert alert.entry_price == 172.40
    assert alert.stop_loss == round(172.40 * 0.985, 2)
    assert alert.target_level == round(172.40 * 1.025, 2)


def test_alert_evaluator_suppresses_extreme_rmultiple_and_spot_scale_dislocation():
    """Verify AlertEvaluator suppresses evaluation on price scale dislocation or extreme R-multiple."""
    from engine.alert_evaluator import evaluate_alert_targets_and_trailing
    from engine.alert_model import AutoAlert

    # Corrupted alert with entry=100.0, stop=98.5 on TATASTEEL (real CMP 171.4)
    corrupted_alert = AutoAlert(
        alert_id="aa-pairs-arbitrage-tatasteel-corrupted-20261027",
        alert_type="PAIRS_ARBITRAGE",
        stage="ACTIONABLE",
        symbol="TATASTEEL",
        exchange="NSE",
        segment="FNO_STOCK",
        direction="BULLISH",
        headline="Stat-Arb Test",
        summary="Test",
        ltp=100.0,
        trigger_level=100.0,
        target_level=102.5,
        stop_loss=98.5,
        confidence=75,
        is_live=True,
    )

    # Ratio is 171.41 / 100 = 1.714x (> 1.60 scale dislocation limit)
    # R-multiple is (171.41 - 100) / 1.5 = 47.61R (> 25R extreme spike limit)
    # Must return None and NOT mark COMPLETED / target hit!
    eval_result = evaluate_alert_targets_and_trailing(corrupted_alert, current_ltp=171.41)
    assert eval_result is None
