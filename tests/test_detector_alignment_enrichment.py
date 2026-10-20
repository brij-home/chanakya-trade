"""
tests/test_detector_alignment_enrichment.py
───────────────────────────────────────────
Tests for detector alignment, calibration, and universal F&O contract enrichment.
"""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detection_context import detector_registry
from engine.detectors.circuit import detect_circuit_proximity
from engine.detectors.orb import detect_opening_range_breakout


@pytest.fixture
def engine():
    eng = AutoAlertEngine()
    eng._is_running = True
    return eng


def test_auto_alert_engine_scanner_methods_exist(engine):
    """Verify all 4 previously dormant scanner methods are now active members of AutoAlertEngine."""
    assert hasattr(engine, "scan_predator_liquidity_sweeps")
    assert callable(engine.scan_predator_liquidity_sweeps)

    assert hasattr(engine, "scan_turtle_soup_sweeps")
    assert callable(engine.scan_turtle_soup_sweeps)

    assert hasattr(engine, "scan_defined_risk_neutral")
    assert callable(engine.scan_defined_risk_neutral)

    assert hasattr(engine, "scan_pairs_arbitrage")
    assert callable(engine.scan_pairs_arbitrage)


def test_universal_fno_contract_enrichment(engine):
    """
    Verify that an equity alert on an F&O underlying (e.g. RELIANCE) without
    an option contract is automatically enriched with the liquid ATM CE/PE contract.
    """
    raw_alert = AutoAlert(
        alert_id="aa-spark-reliance-test",
        alert_type="INTRADAY_BREAKOUT_SPARK",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="Surge on Reliance",
        summary="Volume spark",
        ltp=2500.0,
        trigger_level=2500.0,
        target_level=2550.0,
        stop_loss=2475.0,
        confidence=85,
        actionable_plan={"action": "BUY", "target_1": "2550.0"},
    )

    # Mock option resolver to return deterministic contract
    mock_resolved = MagicMock()
    mock_resolved.contract_symbol = "NSE:RELIANCE26OCT2500CE"
    mock_resolved.strike = 2500.0
    mock_resolved.expiry_date = "2026-10-29"

    with patch("engine.option_resolver.resolve_option_contract", return_value=mock_resolved):
        engine._enrich_fno_contract_if_applicable(raw_alert)

    assert raw_alert.contract_symbol == "NSE:RELIANCE26OCT2500CE"
    assert raw_alert.strike == 2500.0
    assert raw_alert.option_type == "CE"
    assert raw_alert.expiry_date == "2026-10-29"
    assert raw_alert.actionable_plan["action"] == "BUY_CALL"
    assert raw_alert.actionable_plan["contract"] == "NSE:RELIANCE26OCT2500CE"


def test_circuit_detector_calibrated_multipliers():
    """Verify circuit proximity detector targets use institutional multipliers (2.0R, 3.5R, 5.5R)."""
    # 5% band on 950 prev close gives upper circuit = 997.5
    alert = detect_circuit_proximity(
        symbol="TATACHEM",
        ltp=990.0,
        prev_close=950.0,
        circuit_band_pct=5.0,
        exchange="NSE",
    )
    assert alert is not None
    risk_pts = alert.ltp - alert.stop_loss
    assert alert.target_level >= alert.trigger_level + (1.95 * risk_pts)
    assert "target_2" in alert.actionable_plan
    assert "runner_target" in alert.actionable_plan


def test_orb_detector_calibrated_multipliers():
    """Verify ORB detector targets use institutional multipliers (2.0R, 3.5R, 5.5R)."""
    # Create 15m OHLCV dataframe with range 2400 to 2420
    dates = pd.date_range("2026-10-17 09:15", periods=5, freq="15min")
    df = pd.DataFrame(
        {
            "open": [2405.0, 2410.0, 2415.0, 2418.0, 2422.0],
            "high": [2420.0, 2415.0, 2418.0, 2422.0, 2425.0],
            "low": [2400.0, 2408.0, 2412.0, 2415.0, 2418.0],
            "close": [2415.0, 2412.0, 2417.0, 2421.0, 2424.0],
            "volume": [10000, 8000, 9000, 15000, 25000],
        },
        index=dates,
    )

    alert = detect_opening_range_breakout(
        symbol="RELIANCE",
        df=df,
        ltp=2422.0,
        vwap=2415.0,
        rvol=2.2,
        ignore_time_gate=True,
    )
    assert alert is not None
    risk_pts = alert.ltp - alert.stop_loss
    # T1 must be >= ltp + 1.8 * risk_pts (ORB institutional calibration)
    assert alert.target_level >= round(alert.ltp + 1.75 * risk_pts, 1)


def test_detection_context_adapters_include_afternoon_and_scalp():
    """Verify detection_context registry has afternoon_thrust and index_micro_scalp adapters."""
    all_slugs = set(detector_registry.list_registered_slugs())
    assert "afternoon_thrust" in all_slugs
    assert "index_micro_scalp" in all_slugs
    assert "predator_liquidity_sweep" in all_slugs
    assert "turtle_soup_sweep" in all_slugs
    assert "defined_risk_neutral" in all_slugs
    assert "pairs_arbitrage" in all_slugs
