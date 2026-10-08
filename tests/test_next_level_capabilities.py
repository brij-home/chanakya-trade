"""
tests/test_next_level_capabilities.py
─────────────────────────────────────
Comprehensive test suite for the 4 Strategic Next-Level Terminal Modules:
  1. Options Gamma Exposure (GEX) & Dealer Zero-Gamma Levels
  2. Order Flow & Cumulative Volume Delta (CVD) Divergence
  3. Automated Volatility Risk-Parity Position Sizing
  4. Broker Margin Pre-Flight Estimator
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from analysis.gex import get_gex_analysis, compute_gex_at_strike, find_gex_flip, classify_gex_regime
from analysis.order_flow import analyze_order_flow, OrderFlowSnapshot
from engine.position_sizer import calculate_volatility_risk_parity_size, PositionSizeResult
from brokers.fyers import FyersAPI


# ── 1. Options GEX & Dealer Zero-Gamma Tests ─────────────────────────────────


def test_gex_core_math():
    """Verify analytical Black-Scholes GEX formulas and regime classification."""
    # Positive gamma call: 100,000 contracts, gamma 0.0001, spot 22000, lot 65
    call_gex = compute_gex_at_strike(
        oi=100000, gamma=0.0001, spot=22000.0, lot_size=65, is_call=True
    )
    assert call_gex > 0

    put_gex = compute_gex_at_strike(
        oi=100000, gamma=0.0001, spot=22000.0, lot_size=65, is_call=False
    )
    assert put_gex < 0
    assert abs(put_gex + call_gex) < 0.01

    # Zero-gamma flip interpolation
    strip = [(22000.0, 50.0), (22100.0, 20.0), (22200.0, -30.0), (22300.0, -80.0)]
    flip = find_gex_flip(strip)
    assert flip is not None
    assert 22100.0 < flip < 22200.0

    # Regime classification
    assert classify_gex_regime(150.0) == "POSITIVE"
    assert classify_gex_regime(-150.0) == "NEGATIVE"
    assert classify_gex_regime(5.0) == "NEUTRAL"


def test_gex_full_analysis():
    """Verify end-to-end institutional GEX output."""
    res = get_gex_analysis("NIFTY")
    assert res is not None
    assert "status" in res
    if res.get("status") == "ok":
        assert res["spot"] > 0
        assert res["regime"] in ("POSITIVE", "NEGATIVE", "NEUTRAL")
        assert "total_net_gex_cr" in res
        assert "strikes" in res
        assert len(res["strikes"]) > 0
        assert "volatility_acceleration_zones" in res
        assert "interpretation" in res


# ── 2. Order Flow & CVD Divergence Tests ─────────────────────────────────────


def test_order_flow_analysis():
    """Verify Order Flow Snapshot generation with Level 2 Depth and CVD."""
    snap = analyze_order_flow("SBIN")
    assert isinstance(snap, OrderFlowSnapshot)
    assert snap.symbol == "SBIN"
    assert snap.bid_ask_ratio >= 0
    assert -1.0 <= snap.order_book_imbalance <= 1.0
    assert snap.cvd_divergence in (
        "BULLISH_ABSORPTION",
        "BEARISH_EXHAUSTION",
        "AGGRESSIVE_BUYING",
        "AGGRESSIVE_SELLING",
        "NEUTRAL",
    )
    assert isinstance(snap.recommendation, str)
    assert len(snap.recommendation) > 0

    d = snap.to_dict()
    assert "order_book_imbalance" in d
    assert "cvd_series" in d


# ── 3. Automated Volatility Risk-Parity Sizing Tests ─────────────────────────


def test_volatility_risk_parity_sizing():
    """Verify 14-period ATR volatility risk-parity equalizes rupee risk."""
    res_eq = calculate_volatility_risk_parity_size(
        symbol="RELIANCE",
        entry_price=1200.0,
        stop_loss=1160.0,
        capital=100000.0,
        target_risk_pct=1.0,  # 1000 INR risk budget
        max_margin_pct=25.0,  # 25,000 INR cap
        atr=25.0,
        is_fno=False,
    )
    assert isinstance(res_eq, PositionSizeResult)
    assert res_eq.shares > 0
    assert res_eq.capital_allocated <= 25000.0 + 1.0  # Respects 25% margin cap
    assert res_eq.risk_amount <= 1000.0 + 1.0  # Respects 1% risk budget
    assert "Volatility Risk-Parity" in res_eq.notes

    # Sizing for high-volatility midcap (higher ATR -> fewer shares)
    res_high_vol = calculate_volatility_risk_parity_size(
        symbol="HIGH_BETA",
        entry_price=1200.0,
        stop_loss=1120.0,
        capital=100000.0,
        target_risk_pct=1.0,
        max_margin_pct=25.0,
        atr=60.0,  # High volatility
        is_fno=False,
    )
    assert res_high_vol.shares < res_eq.shares


# ── 4. Broker Margin Pre-Flight Estimator Tests ──────────────────────────────


def test_fyers_margin_check_offline():
    """Verify statutory charge calculation and margin parsing in check_order_margin."""
    fyers = FyersAPI(app_id="TEST-100", secret_key="test_secret")
    # Simulate active token
    fyers._access_token = "mock_token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "s": "ok",
        "code": 200,
        "message": "",
        "data": {
            "margin_avail": 50000.0,
            "margin_total": 15000.0,
            "margin_new_order": 15000.0,
            "prevMargin": 0,
        },
    }

    with patch("requests.post", return_value=mock_resp):
        res = fyers.check_order_margin(
            [
                {
                    "symbol": "NSE:SBIN-EQ",
                    "qty": 50,
                    "side": "BUY",
                    "product_type": "INTRADAY",
                    "price": 800.0,
                }
            ]
        )

        assert res["status"] == "ok"
        assert res["preflight_verdict"] == "CLEARED"
        assert res["required_margin"] == 15000.0
        assert res["available_margin"] == 50000.0
        assert res["is_sufficient"] is True
        assert res["shortfall"] == 0.0
        assert res["total_transaction_charges"] > 0
        assert "brokerage" in res["charges_breakdown"]
        assert "gst" in res["charges_breakdown"]
        assert "stamp_duty" in res["charges_breakdown"]
