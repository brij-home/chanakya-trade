"""tests/test_dynamic_position_sizing.py
──────────────────────────────────────
Deterministic unit test suite for MarketDynamicsGovernor-coupled position sizing:
  - Low-VIX debit spread recommendation
  - Crisis-VIX 50% lot haircut
  - SEBI physical delivery quarantine vehicle alignment
  - Audit trail and dictionary serialization integrity
"""

from unittest.mock import patch
import pytest

from engine.market_dynamics_governor import (
    get_market_dynamics_governor,
)
from engine.position_sizer import (
    PositionSizeResult,
    calculate_position_size,
    calculate_position_size_for_alert,
)


@pytest.fixture(autouse=True)
def reset_governor():
    """Ensure clean governor cache for each test."""
    get_market_dynamics_governor().reset_for_testing()
    yield
    get_market_dynamics_governor().reset_for_testing()


def test_position_size_result_serialization_includes_recommended_structure():
    """PositionSizeResult.as_dict() must serialize recommended_structure."""
    res = PositionSizeResult(
        symbol="NIFTY",
        shares=75,
        lots=1,
        lot_size=75,
        capital_allocated=150_000.0,
        capital_pct=15.0,
        risk_amount=3_750.0,
        risk_pct=0.375,
        entry_price=24_000.0,
        stop_loss=23_950.0,
        target_price=24_100.0,
        r_multiple=2.0,
        sizing_model="atr_volatility",
        recommended_structure="DEBIT_SPREAD",
    )
    d = res.as_dict()
    assert d["recommended_structure"] == "DEBIT_SPREAD"
    assert d["symbol"] == "NIFTY"


def test_low_vix_regime_recommends_debit_spread():
    """Under Low VIX (<12.0), position sizer must recommend DEBIT_SPREAD to mitigate theta bleed."""
    # NIFTY with VIX = 10.5
    res = calculate_position_size(
        symbol="NIFTY",
        entry_price=24_000.0,
        stop_loss=23_950.0,
        capital=1_000_000.0,
        vix=10.5,
        is_fno=True,
    )
    assert res.recommended_structure == "DEBIT_SPREAD"


def test_crisis_vix_applies_fifty_percent_lot_haircut():
    """Under Crisis VIX (>22.0), lot sizing must be cut by 50% to prevent ruin during volatility shocks."""
    # Sized with normal VIX (14.0) on NIFTY option: 65 lot size, 50 pt stop = 3250 risk per lot
    # On 2,000,000 capital at 1.5% max risk = 30,000 risk budget
    res_normal = calculate_position_size(
        symbol="NIFTY",
        entry_price=150.0,
        stop_loss=100.0,
        capital=2_000_000.0,
        vix=14.0,
        is_fno=True,
    )

    # Sized with crisis VIX (26.0)
    res_crisis = calculate_position_size(
        symbol="NIFTY",
        entry_price=150.0,
        stop_loss=100.0,
        capital=2_000_000.0,
        vix=26.0,
        is_fno=True,
    )

    assert "CRISIS_VIX" in res_crisis.notes or "50% lot haircut" in res_crisis.notes
    assert res_crisis.lots < res_normal.lots


def test_quarantined_stock_option_recommends_futures_or_far_month():
    """When a stock option is in SEBI monthly expiry quarantine, structure must redirect to FUTURES_OR_FAR_MONTH."""
    with patch(
        "engine.market_dynamics_governor.is_stock_option_quarantined",
        return_value=True,
    ):
        res = calculate_position_size(
            symbol="RELIANCE",
            entry_price=2500.0,
            stop_loss=2480.0,
            capital=1_000_000.0,
            is_fno=True,
        )
        assert res.recommended_structure == "FUTURES_OR_FAR_MONTH"
        assert "DELIVERY_QUARANTINE" in res.notes


def test_calculate_position_size_for_alert_forwards_recommended_structure():
    """calculate_position_size_for_alert must propagate recommended_structure from baseline."""
    res = calculate_position_size_for_alert(
        alert_type="ORB_BREAKOUT",
        symbol="NIFTY",
        entry_price=24_000.0,
        stop_loss=23_950.0,
        capital=1_000_000.0,
        vix=11.0,
        is_fno=True,
    )
    assert res.recommended_structure == "DEBIT_SPREAD"
