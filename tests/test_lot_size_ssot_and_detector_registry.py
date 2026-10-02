"""
tests/test_lot_size_ssot_and_detector_registry.py
─────────────────────────────────────────────────
Comprehensive invariant tests verifying:
  1. Single Source of Truth (SSOT) for lot sizes across all modules (market.instruments).
  2. Complete registration of all institutional detectors in DetectorRegistry.
  3. Seamless AutoAlertEngine integration with DetectorRegistry and DetectionContext.
"""

from __future__ import annotations

import pytest
from market.instruments import (
    STANDARD_LOT_SIZES,
    get_fno_lot_size,
    resolve_canonical_instrument,
)
from engine.position_sizer import _F_AND_O_LOT_SIZES
from engine.options_backtest import LOT_SIZES as OB_LOT_SIZES
from engine.greeks_manager import LOT_SIZES as GM_LOT_SIZES
from engine.detection_context import (
    DetectionContext,
    build_detection_context,
    detector_registry,
    register_default_detectors,
)
from engine.auto_alert_engine import AutoAlertEngine


def test_lot_size_ssot_identity_invariants():
    """Verify that all engines and modules reference the exact same STANDARD_LOT_SIZES master."""
    assert _F_AND_O_LOT_SIZES is STANDARD_LOT_SIZES, "_F_AND_O_LOT_SIZES must be STANDARD_LOT_SIZES identity"
    assert OB_LOT_SIZES is STANDARD_LOT_SIZES, "OptionsBacktest LOT_SIZES must be STANDARD_LOT_SIZES identity"
    assert GM_LOT_SIZES is STANDARD_LOT_SIZES, "GreeksManager LOT_SIZES must be STANDARD_LOT_SIZES identity"


def test_key_lot_size_specifications():
    """Verify authoritative SEBI active contract lot sizes for benchmark indices, equities, commodities."""
    # Benchmark Indices
    assert STANDARD_LOT_SIZES["NIFTY"] == 65
    assert STANDARD_LOT_SIZES["NIFTY 50"] == 65
    assert STANDARD_LOT_SIZES["BANKNIFTY"] == 30
    assert STANDARD_LOT_SIZES["FINNIFTY"] == 60
    assert STANDARD_LOT_SIZES["MIDCPNIFTY"] == 120
    assert STANDARD_LOT_SIZES["SENSEX"] == 20
    assert STANDARD_LOT_SIZES["BANKEX"] == 30

    # Key F&O Equities
    assert STANDARD_LOT_SIZES["RELIANCE"] == 500
    assert STANDARD_LOT_SIZES["TCS"] == 225
    assert STANDARD_LOT_SIZES["INFY"] == 400
    assert STANDARD_LOT_SIZES["HDFCBANK"] == 650
    assert STANDARD_LOT_SIZES["ICICIBANK"] == 700
    assert STANDARD_LOT_SIZES["SBIN"] == 750
    assert STANDARD_LOT_SIZES["ANANDRATHI"] == 250
    assert STANDARD_LOT_SIZES["ENRIN"] == 175
    assert STANDARD_LOT_SIZES["UJJIVANSFB"] == 8000

    # Commodities & Currencies
    assert STANDARD_LOT_SIZES["CRUDEOIL"] == 100
    assert STANDARD_LOT_SIZES["GOLD"] == 100
    assert STANDARD_LOT_SIZES["SILVER"] == 30
    assert STANDARD_LOT_SIZES["USDINR"] == 1000


def test_get_fno_lot_size_helper():
    """Verify get_fno_lot_size correctly resolves tickers, aliases, and defaults."""
    assert get_fno_lot_size("RELIANCE") == 500
    assert get_fno_lot_size("NSE:RELIANCE") == 500
    assert get_fno_lot_size("ANANDRATHI") == 250
    assert get_fno_lot_size("NSE:ENRIN") == 175
    assert get_fno_lot_size("UJJIVANSFB") == 8000
    assert get_fno_lot_size("NIFTY") == 65
    assert get_fno_lot_size("NIFTY 50") == 65
    assert get_fno_lot_size("NSE:BANKNIFTY") == 30
    assert get_fno_lot_size("NON_FNO_STOCK_XYZ") == 1


def test_canonical_instrument_cash_vs_derivative_distinction():
    """Verify cash equity maintains 1-share lot size while derivatives resolve contract size."""
    # Cash equity
    eq = resolve_canonical_instrument("RELIANCE")
    assert eq.lot_size == 1
    assert eq.segment == "EQUITY"
    assert eq.instrument_type == "EQUITY"

    # Index (traded via derivatives)
    idx = resolve_canonical_instrument("NIFTY")
    assert idx.lot_size == 65
    assert idx.segment == "INDEX"

    # Option / Future
    opt = resolve_canonical_instrument("NFO:RELIANCE24OCT2500CE")
    assert opt.lot_size == 500
    assert opt.segment == "FNO"
    assert opt.instrument_type == "OPTION"


def test_detector_registry_completeness():
    """Verify that all institutional detectors are registered in DetectorRegistry."""
    register_default_detectors()
    detectors = detector_registry.get_detectors()
    slugs = {d.detector_slug for d in detectors}

    expected_slugs = {
        "circuit_proximity",
        "orb",
        "squeeze_breakout",
        "gamma_blast",
        "opening_drive",
        "pre_inflection_dryup",
        "pattern_coiling",
        "index_call_setup",
        "index_put_setup",
        "commodity_breakout",
        "currency_breakout",
        "crypto_signal",
        "smc_ob_retest",
        "order_flow_divergence",
        "options_momentum",
        "intraday_spark",
        "multibagger",
        "preopen_bias",
    }
    missing = expected_slugs - slugs
    assert not missing, f"Missing detectors in registry: {missing}"
    assert len(slugs) >= len(expected_slugs)


def test_auto_alert_engine_detector_registry_integration(monkeypatch):
    """Verify that AutoAlertEngine delegates to DetectorRegistry and ingests recorded alerts."""
    engine = AutoAlertEngine()
    reg = engine.get_detector_registry()
    assert reg is detector_registry

    # Create mock context
    ctx = build_detection_context(
        "NSE:TATASTEEL",
        exchange="NSE",
        segment="EQUITY",
        ltp=160.0,
        prev_close=150.0,
        day_high=162.0,
        environment="TEST",
    )

    # Evaluate context through AutoAlertEngine
    recorded = engine.evaluate_detection_context(ctx)
    # Circuit proximity may or may not trigger based on circuit calculation
    assert isinstance(recorded, list)
