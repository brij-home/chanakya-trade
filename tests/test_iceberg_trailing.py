"""
tests/test_iceberg_trailing.py
──────────────────────────────
Tests for TBT 50-Depth Dynamic Iceberg Wall Stop Anchoring.
"""

from unittest.mock import MagicMock
import pytest

from engine.alert_evaluator import (
    resolve_iceberg_trailing_anchor,
    evaluate_alert_targets_and_trailing,
)
from engine.alert_model import AutoAlert


def test_resolve_iceberg_trailing_anchor_bullish(monkeypatch):
    """
    When a resting bid wall exists below LTP and above current stop,
    anchored stop must trail directly behind the institutional wall.
    """
    mock_depth = {
        "status": "LIVE",
        "bid_walls": [
            {"price": 25050.0, "qty": 45000, "strength": "FORTRESS"},
            {"price": 24950.0, "qty": 12000, "strength": "MODERATE"},
        ],
        "ask_walls": [],
    }

    mock_mgr = MagicMock()
    mock_mgr.is_connected = True
    mock_mgr.get_50_depth.return_value = mock_depth

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_mgr)

    # Bullish position: LTP = 25100, current stop = 25000
    stop_p, note = resolve_iceberg_trailing_anchor(
        "NSE:NIFTY26OCT25000CE",
        direction_is_bullish=True,
        current_ltp=25100.0,
        current_stop=25000.0,
    )

    assert stop_p is not None
    # 25050 * 0.999 = 25024.95
    assert stop_p == pytest.approx(25024.95, rel=1e-2)
    assert "Institutional Bid Wall Shield" in note
    assert "45,000" in note


def test_resolve_iceberg_trailing_anchor_bearish(monkeypatch):
    """
    When a resting ask wall exists above LTP and below current stop,
    anchored stop must sit directly behind the institutional ask wall.
    """
    mock_depth = {
        "status": "LIVE",
        "bid_walls": [],
        "ask_walls": [
            {"price": 24900.0, "qty": 38000, "strength": "FORTRESS"},
        ],
    }

    mock_mgr = MagicMock()
    mock_mgr.is_connected = True
    mock_mgr.get_50_depth.return_value = mock_depth

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_mgr)

    # Bearish position: LTP = 24850, current stop = 24950
    stop_p, note = resolve_iceberg_trailing_anchor(
        "NSE:NIFTY26OCT25000PE",
        direction_is_bullish=False,
        current_ltp=24850.0,
        current_stop=24950.0,
    )

    assert stop_p is not None
    # 24900 * 1.001 = 24924.9
    assert stop_p == pytest.approx(24924.9, rel=1e-2)
    assert "Institutional Ask Wall Shield" in note
    assert "38,000" in note


def test_t1_achieved_with_iceberg_anchor(monkeypatch):
    """
    When T1 (+2R) is reached, trailing stop ratchets behind resting iceberg wall if superior to breakeven.
    """
    mock_depth = {
        "status": "LIVE",
        "bid_walls": [
            {"price": 25080.0, "qty": 50000, "strength": "FORTRESS"},
        ],
        "ask_walls": [],
    }

    mock_mgr = MagicMock()
    mock_mgr.is_connected = True
    mock_mgr.get_50_depth.return_value = mock_depth

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_mgr)

    alert = AutoAlert(
        alert_id="test-t1-iceberg",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="Nifty Long",
        summary="Test setup",
        ltp=25000.0,
        trigger_level=25000.0,
        target_level=25200.0,
        stop_loss=24950.0,  # Risk = 50 pts, T1 = 25100
        actionable_plan={
            "action": "BUY",
            "trade_plan": {
                "entry_price": 25000.0,
                "invalidation_stop": 24950.0,
                "target_1": 25100.0,
                "target_2": 25200.0,
            },
        },
    )

    # Price crosses T1 to 25105
    res = evaluate_alert_targets_and_trailing(alert, current_ltp=25105.0)

    assert res is not None
    assert res.new_milestone == "T1_ACHIEVED"
    assert res.should_trail is True
    # Breakeven was 25050.0, but iceberg wall at 25080 gave 25054.92 stop
    assert res.recommended_stop > 25050.0
    assert "Institutional Bid Wall Shield" in res.trailing_rationale
