"""
tests/test_resilient_regime_filtering.py
────────────────────────────────────────
Deterministic verification of institutional regime resilience, anti-whipsaw,
and anti-exhaustion trade signal hardening.
"""

import pytest
import pandas as pd
import numpy as np
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.detectors.squeeze_breakout import detect_squeeze_breakout


@pytest.fixture(autouse=True)
def clean_lockouts():
    from engine.learning_engine import pattern_learning_engine

    pattern_learning_engine._symbol_lockouts.clear()
    pattern_learning_engine._invalidation_counts.clear()
    yield
    pattern_learning_engine._symbol_lockouts.clear()
    pattern_learning_engine._invalidation_counts.clear()


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor()


def test_benchmark_gravitational_veto_bullish_in_markdown(auditor: AlertScrutinyAuditor):
    """When NIFTY is in structural markdown (< VWAP and down -0.60%), high-beta long equity breakout is vetoed."""
    alert = AutoAlert(
        alert_id="test-nifty-markdown-veto",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:TATASTEEL",
        exchange="NSE",
        direction="BULLISH",
        headline="Tata Steel Breakout",
        summary="Testing bullish spark during Nifty markdown",
        ltp=155.0,
        trigger_level=155.0,
        stop_loss=152.0,  # 3 pts risk (~1.9%)
        target_level=162.0,  # 7 pts reward (1:2.3 R:R)
        is_live=True,
        environment="LIVE",
        metrics={
            "nifty_change_pct": -0.65,
            "nifty_below_vwap": True,
            "sector_name": "NIFTY_METAL",
            "rrg_quadrant": "WEAKENING",
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Benchmark Gravitational Veto" in reason
    assert "NIFTY 50 in structural markdown" in reason
    assert flags["macro_regime_aligned"] is False


def test_benchmark_gravitational_pass_defensive_pharma_in_markdown(auditor: AlertScrutinyAuditor):
    """When NIFTY is in markdown, leading defensive sector decoupler (e.g. Pharma in LEADING) is approved."""
    alert = AutoAlert(
        alert_id="test-nifty-markdown-pharma-pass",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:SUNPHARMA",
        exchange="NSE",
        direction="BULLISH",
        headline="Sun Pharma Defensive Decoupler",
        summary="Sun Pharma surging with institutional inflows in defensive sector",
        ltp=1850.0,
        trigger_level=1850.0,
        stop_loss=1820.0,  # 30 pts risk (~1.6%)
        target_level=1920.0,  # 70 pts reward (1:2.3 R:R)
        is_live=True,
        environment="LIVE",
        metrics={
            "nifty_change_pct": -0.65,
            "nifty_below_vwap": True,
            "sector_name": "NIFTY_PHARMA",
            "rrg_quadrant": "LEADING",
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True
    assert flags["macro_regime_aligned"] is True


def test_benchmark_gravitational_veto_bearish_in_markup(auditor: AlertScrutinyAuditor):
    """When NIFTY is in strong markup (+0.80%, above VWAP), non-lagging short equity breakdown is vetoed."""
    alert = AutoAlert(
        alert_id="test-nifty-markup-short-veto",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:MARUTI",
        exchange="NSE",
        direction="BEARISH",
        headline="Maruti Breakdown",
        summary="Testing short breakdown during Nifty rally",
        ltp=12500.0,
        trigger_level=12500.0,
        stop_loss=12700.0,  # 200 pts risk (~1.6%)
        target_level=12000.0,  # 500 pts reward (1:2.5 R:R)
        is_live=True,
        environment="LIVE",
        metrics={
            "nifty_change_pct": 0.85,
            "nifty_below_vwap": False,
            "sector_name": "NIFTY_AUTO",
            "rrg_quadrant": "LEADING",
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Benchmark Gravitational Veto" in reason
    assert "NIFTY 50 in strong structural markup" in reason
    assert flags["macro_regime_aligned"] is False


def test_intraday_rsi_exhaustion_tightened(auditor: AlertScrutinyAuditor):
    """Intraday 5m RSI > 72 is vetoed as climax exhaustion, while daily swing allows up to 78."""
    # 1. 5m Intraday Setup with RSI 74.0 -> Must be VETOED
    intraday_alert = AutoAlert(
        alert_id="test-rsi-intraday-veto",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NFO",
        direction="BULLISH",
        headline="Reliance Call Surge",
        summary="Call surge with RSI 74",
        ltp=55.0,
        trigger_level=55.0,
        stop_loss=48.0,
        target_level=72.0,
        option_type="CE",
        strike=3000.0,
        contract_symbol="RELIANCE3000CE",
        is_live=True,
        environment="LIVE",
        metrics={"rsi_5m": 74.5, "timeframe": "5m"},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(intraday_alert)
    assert passed is False
    assert "Climax Exhaustion: Intraday RSI (74.5) > 72" in reason

    # 2. Daily Swing Setup with RSI 74.0 -> Allowed (limit is 78)
    swing_alert = AutoAlert(
        alert_id="test-rsi-swing-pass",
        alert_type="ASYMMETRIC_OPPORTUNITY",
        stage="EARLY_WARNING",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Reliance Daily Pocket Pivot",
        summary="Daily setup",
        ltp=2950.0,
        trigger_level=2950.0,
        stop_loss=2890.0,
        target_level=3100.0,
        is_live=True,
        environment="LIVE",
        metrics={"rsi": 74.5, "timeframe": "day"},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(swing_alert)
    assert passed is True


def test_intraday_oversold_exhaustion_tightened(auditor: AlertScrutinyAuditor):
    """Intraday short setup with underlying RSI < 28 is vetoed as capitulation floor."""
    alert = AutoAlert(
        alert_id="test-oversold-intraday-veto",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BEARISH",
        headline="Infosys Breakdown",
        summary="Short breakdown with RSI 25",
        ltp=1800.0,
        trigger_level=1800.0,
        stop_loss=1835.0,
        target_level=1710.0,
        is_live=True,
        environment="LIVE",
        metrics={"rsi_5m": 25.0, "timeframe": "5m"},
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Oversold Exhaustion: Intraday RSI (25.0) < 28" in reason


def test_intraday_20ema_mean_reversion_extension_tightened(auditor: AlertScrutinyAuditor):
    """Intraday setup extended > 2.2x ATR from 20-EMA without base is rejected."""
    # LTP = 1000, 20-EMA = 970, ATR = 12.
    # Extension = 30 pts = 2.5x ATR (> 2.2x limit for intraday)
    alert = AutoAlert(
        alert_id="test-ema-extension-intraday",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:SBIN",
        exchange="NSE",
        direction="BULLISH",
        headline="SBI Breakout",
        summary="Extended from EMA",
        ltp=1000.0,
        trigger_level=1000.0,
        stop_loss=982.0,
        target_level=1045.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "ema20": 970.0,
            "atr": 12.0,
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Mean Reversion Risk: Extended 2.5x ATR from 20-EMA" in reason


def test_3bar_parabolic_velocity_climax_rejection(auditor: AlertScrutinyAuditor):
    """Asset that moved > 2.0x ATR over the last 3 bars is flagged as a parabolic climax."""
    alert = AutoAlert(
        alert_id="test-velocity-climax",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:BHARTIARTL",
        exchange="NSE",
        direction="BULLISH",
        headline="Bharti Airtel Vertical Surge",
        summary="Moved 2.4x ATR in 3 bars",
        ltp=1650.0,
        trigger_level=1650.0,
        stop_loss=1625.0,
        target_level=1710.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "move_3b_atr": 2.4,
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Parabolic Velocity Climax: Asset expanded 2.4x ATR" in reason
    assert flags["velocity_sustainable"] is False


def test_squeeze_breakout_upper_wick_rejection():
    """A squeeze breakout candle with upper wick ratio > 0.35 (shooting star) is rejected."""
    # Synthetic 25-bar DataFrame coiling in squeeze
    np.random.seed(42)
    closes = np.linspace(100, 105, 25)
    highs = closes + 0.5
    lows = closes - 0.5
    vols = np.full(25, 10000)

    # Make the last candle a shooting star wick rejection at pivot high:
    # Open: 104.5, High: 107.0, Low: 104.2, Close: 104.8
    # Range: 2.8 pts, Upper Wick = 107.0 - 104.8 = 2.2 pts (Wick Ratio = 2.2 / 2.8 = 0.78 > 0.35)
    highs[-1] = 107.0
    closes[-1] = 104.8
    lows[-1] = 104.2

    df = pd.DataFrame(
        {
            "open": closes - 0.2,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        }
    )
    df.loc[df.index[-1], "open"] = 104.5

    # Trigger with LTP at 106.0 (attempting ignited breakout above 105.5 pivot)
    alert = detect_squeeze_breakout("NSE:TESTSYM", df, ltp=106.0, timeframe="15m")
    # Because the bar has a 78% upper wick rejection, it must NOT fire an IGNITED breakout alert!
    assert alert is None


def test_intraday_sector_drag_veto_bullish(auditor: AlertScrutinyAuditor, monkeypatch):
    """When a stock triggers a bullish signal but its sector is lagging NIFTY by >= 1.0%, it is vetoed."""
    monkeypatch.setattr(
        "engine.learning_engine.pattern_learning_engine.is_symbol_locked_out",
        lambda *a, **k: (False, None),
    )
    alert = AutoAlert(
        alert_id="test-sector-drag-veto",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:INFY",
        exchange="NSE",
        direction="BULLISH",
        headline="Infosys Breakout Attempt",
        summary="Infosys trying to break out while IT sector dumps",
        ltp=1850.0,
        trigger_level=1850.0,
        stop_loss=1820.0,
        target_level=1920.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "intraday_sector_rs": -1.45,  # IT sector is underperforming NIFTY by 1.45% intraday
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Intraday Sector Drag Veto" in reason
    assert "lagging NIFTY by 1.45% intraday" in reason
    assert flags["sector_aligned"] is False


def test_intraday_sector_tailwind_veto_bearish(auditor: AlertScrutinyAuditor):
    """When an alert triggers a short breakdown but its sector is surging (+1.2% vs NIFTY), it is vetoed."""
    alert = AutoAlert(
        alert_id="test-sector-tailwind-short-veto",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:HDFCBANK",
        exchange="NSE",
        direction="BEARISH",
        headline="HDFC Bank Breakdown Attempt",
        summary="HDFC Bank breakdown while Banking sector is surging",
        ltp=1650.0,
        trigger_level=1650.0,
        stop_loss=1675.0,
        target_level=1600.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "intraday_sector_rs": 1.60,  # Banking is beating NIFTY by 1.60% intraday
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is False
    assert "Intraday Sector Tailwind Veto" in reason
    assert "outperforming NIFTY by +1.60% intraday" in reason
    assert flags["sector_aligned"] is False


def test_intraday_sector_aligned_pass(auditor: AlertScrutinyAuditor):
    """When a stock triggers a bullish signal and its sector has healthy relative strength, it passes."""
    alert = AutoAlert(
        alert_id="test-sector-tailwind-pass",
        alert_type="INTRADAY_SPARK",
        stage="IGNITED",
        symbol="NSE:TCS",
        exchange="NSE",
        direction="BULLISH",
        headline="TCS Breakout with Sector Tailwind",
        summary="TCS breakout with IT leading intraday",
        ltp=4000.0,
        trigger_level=4000.0,
        stop_loss=3940.0,
        target_level=4150.0,
        is_live=True,
        environment="LIVE",
        metrics={
            "intraday_sector_rs": 0.85,
            "timeframe": "5m",
        },
    )
    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True
    assert flags["sector_aligned"] is True


def test_stock_tailwind_intraday_rs_calculation():
    """Verify get_stock_tailwind computes intraday_rs and applies penalties on sector underperformance."""
    from analysis.sector_rotation import get_stock_tailwind, SectorRRGPoint

    # Synthetic matrix where IT is in LEADING quadrant, but today is suffering an intraday flush
    # day_change_pct = -1.8%, benchmark_change_pct = -0.2% -> intraday_rs = -1.6% (Severe Headwind)
    mock_point = SectorRRGPoint(
        sector="IT",
        symbol="^CNXIT",
        rs_ratio=103.5,
        rs_momentum=102.0,
        quadrant="LEADING",
        day_change_pct=-1.8,
        benchmark_change_pct=-0.2,
    )
    mock_matrix = {"IT": mock_point}

    tw = get_stock_tailwind("INFY", rrg_matrix=mock_matrix)
    assert tw.symbol == "INFY"
    assert tw.sector == "IT"
    assert tw.quadrant == "LEADING"
    assert tw.intraday_rs == -1.60
    assert tw.intraday_alignment == "SEVERE_INTRADAY_HEADWIND"
    # Base score for LEADING is 85 + 1 (momentum adj) = 86.
    # Severe headwind penalty is -20 -> score becomes 66 (MODERATE_TAILWIND instead of STRONG_TAILWIND)
    assert tw.tailwind_score <= 68
    assert tw.alignment == "MODERATE_TAILWIND"
    assert "CAUTION: Sector is lagging NIFTY by 1.60% intraday" in tw.analysis
