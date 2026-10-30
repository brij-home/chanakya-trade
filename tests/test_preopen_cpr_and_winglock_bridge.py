"""
tests/test_preopen_cpr_and_winglock_bridge.py
─────────────────────────────────────────────
Comprehensive unit tests for:
  1. Untested Virgin CPR Detection & Magnet Logic (engine/daily_levels.py)
  2. Automated Pre-Open 09:08 IST Radar with Day Archetypes (engine/detectors/preopen_bias.py)
  3. 1-Click Fyers / Paper Multi-Leg Execution Bridge for Wing Lock (engine/order_lifecycle.py & web/routers/orders_api.py)
  4. Real-Time Fyers 50-Level DOM Greeks & DEX Fusion (market/fyers_tbt_manager.py)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import get_auto_alert_engine
from engine.daily_levels import DailyLevels, detect_virgin_cpr
from engine.detectors.preopen_bias import detect_preopen_bias
from engine.order_lifecycle import execute_wing_lock_hedge
from market.fyers_tbt_manager import get_realtime_orderbook_greeks
from web.api import app


# ── 1. Virgin CPR Tests ────────────────────────────────────────────────────────


def test_detect_virgin_cpr_untouched():
    """Verify that a session where prices never entered the CPR corridor is identified as Virgin CPR."""
    # Day 1: Basis for Day 2 CPR
    # H=100, L=90, C=95 -> Pivot=95, BC=95, TC=95. Top=95, Bottom=95.
    # Day 2: H=120, L=102, C=115 -> Entire day traded ABOVE 95! (Virgin CPR)
    # Day 3: H=130, L=108, C=125 -> Did NOT touch 95.
    dates = pd.date_range("2026-10-25", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [92.0, 105.0, 116.0],
            "high": [100.0, 120.0, 130.0],
            "low": [90.0, 102.0, 108.0],
            "close": [95.0, 115.0, 125.0],
        },
        index=dates,
    )

    res = detect_virgin_cpr("NIFTY", history_df=df, current_price=125.0, lookback_days=5)
    assert res["has_virgin_cpr"] is True
    assert len(res["virgin_cprs"]) >= 1

    nearest = res["nearest_magnet"]
    assert nearest is not None
    assert nearest["pivot"] == 95.0
    assert nearest["magnet_bias"] == "MAGNET_BELOW"
    assert res["magnet_target"] == 95.0
    assert res["distance_pts"] == 30.0  # 125 - 95 = 30
    assert "Active Untested Virgin CPR" in res["summary"]


def test_detect_virgin_cpr_filled_invalidates():
    """Verify that if subsequent sessions touch or fill all prior CPRs, no active virgin CPR remains."""
    # Day 1: H=100, L=90, C=95 -> Day 2 CPR = 95.
    # Day 2: H=120, L=102, C=115 -> Day 2 is virgin (L=102 > 95).
    # Day 3: H=115, L=92, C=105 -> Day 3 CPR from Day 2 is [111.0, 113.66].
    # Day 3 Low 92 <= 111 and High 115 >= 113.66 (Day 3 touches its own CPR).
    # And Day 3 Low 92 breaches Day 2's CPR of 95 (fills Day 2 CPR).
    dates = pd.date_range("2026-10-25", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [92.0, 105.0, 108.0],
            "high": [100.0, 120.0, 115.0],
            "low": [90.0, 102.0, 92.0],
            "close": [95.0, 115.0, 105.0],
        },
        index=dates,
    )

    res = detect_virgin_cpr("NIFTY", history_df=df, current_price=105.0, lookback_days=5)
    assert res["has_virgin_cpr"] is False
    assert res["nearest_magnet"] is None
    assert "No active untested Virgin CPR" in res["summary"]


# ── 2. Pre-Open 09:08 Radar & Archetypes ──────────────────────────────────────


def test_detect_preopen_bias_trend_expansion_archetype(monkeypatch):
    """Verify TREND_EXPANSION_DAY archetype with narrow CPR and pro-gap."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    # Mock daily levels to return Narrow CPR
    mock_dl = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-31",
        pdh=24500.0,
        pdl=24300.0,
        pdc=24400.0,
        cpr={
            "tc": 24405.0,
            "pivot": 24400.0,
            "bc": 24395.0,
            "top": 24405.0,
            "bottom": 24395.0,
            "width_pct": 0.04,  # Narrow CPR (<0.15%)
            "is_narrow": True,
            "is_wide": False,
            "cpr_type": "NARROW",
        },
    )

    with patch("engine.detectors.preopen_bias.get_daily_levels", return_value=mock_dl):
        with patch("analysis.gex.get_gex_analysis") as mock_gex:
            mock_gex.return_value = MagicMock(
                call_wall=24600.0,
                put_wall=24300.0,
                gamma_flip=24450.0,
                dex_regime="DEALER_NET_SHORT_DELTA",
                dex_neutral_level=24480.0,
                total_net_gex_cr=120.0,
                total_net_dex_cr=-350.0,
                to_dict=lambda: {
                    "call_wall": 24600.0,
                    "put_wall": 24300.0,
                    "dex_regime": "DEALER_NET_SHORT_DELTA",
                },
            )

            alerts = detect_preopen_bias(
                underlying="NIFTY",
                gift_futures_price=24520.0,  # +0.49% gap up
                prev_close=24400.0,
                chain=[],
            )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.metrics["day_archetype"] == "TREND_EXPANSION_DAY"
    assert alert.metrics["cpr_type"] == "NARROW"
    assert "TREND_EXPANSION_DAY" in alert.headline
    assert alert.confidence >= 80
    assert alert.actionable_plan["day_archetype"] == "TREND_EXPANSION_DAY"
    assert "Call Wall: ₹24,600" in alert.actionable_plan["gex_pinning_summary"]


def test_detect_preopen_bias_pinned_chop_archetype(monkeypatch):
    """Verify PINNED_CHOP_DAY archetype with wide CPR."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")

    mock_dl = DailyLevels(
        symbol="NIFTY",
        canonical_symbol="NIFTY",
        exchange="NSE",
        session_date="2026-10-31",
        pdh=24600.0,
        pdl=24200.0,
        pdc=24400.0,
        cpr={
            "tc": 24480.0,
            "pivot": 24400.0,
            "bc": 24320.0,
            "top": 24480.0,
            "bottom": 24320.0,
            "width_pct": 0.65,  # Wide CPR (>0.35%)
            "is_narrow": False,
            "is_wide": True,
            "cpr_type": "WIDE",
        },
    )

    with patch("engine.detectors.preopen_bias.get_daily_levels", return_value=mock_dl):
        alerts = detect_preopen_bias(
            underlying="NIFTY",
            gift_futures_price=24480.0,  # +0.33% modest gap
            prev_close=24400.0,
            chain=[],
        )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.metrics["day_archetype"] == "PINNED_CHOP_DAY"
    assert alert.metrics["cpr_type"] == "WIDE"
    assert "PINNED_CHOP_DAY" in alert.headline


# ── 3. 1-Click Wing Lock Execution Bridge ──────────────────────────────────────


def test_execute_wing_lock_hedge(monkeypatch):
    """Verify 1-Click Wing Lock execution converts alert into hedged spread."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("DEPLOY_MODE", "test")

    from market.instrument_master import upsert_verified_contract

    upsert_verified_contract(
        lookup_symbol="NIFTY24750CE",
        provider="fyers",
        provider_symbol="NSE:NIFTY26OCT24750CE",
        provider_token="10001",
        exchange="NSE",
        segment="OPTIONS",
        lot_size=25,
        tick_size=0.05,
        expiry_date="2026-10-29",
    )

    engine = get_auto_alert_engine()

    # Create an alert that has reached free-roll eligibility
    alert = AutoAlert(
        alert_id="aa-gamma-blast-nifty-24500ce-test-20261031",
        alert_type="GAMMA_BLAST",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24500 CE Free-Roll Milestone",
        summary="Gain +48%, eligible for Free-Roll Wing Lock",
        ltp=148.0,
        trigger_level=100.0,
        target_level=160.0,
        stop_loss=80.0,
        lot_size=25,
        locked_profit_pts=28.0,
        actionable_plan={
            "hedge_ticket": {
                "action": "SELL",
                "symbol": "NIFTY24750CE",
                "strike": 24750.0,
                "option_type": "CE",
                "limit_price": 42.0,
                "order_type": "LIMIT",
                "shares": 25,
            },
            "free_roll_plan": {
                "short_strike_candidate": 24750.0,
                "option_type": "CE",
                "estimated_credit_collected": 42.0,
                "net_locked_profit_pts": 28.0,
            },
        },
        metrics={},
    )
    with engine._lock:
        engine._alerts.insert(0, alert)

    # Execute wing lock hedge
    result = execute_wing_lock_hedge(
        alert_id="aa-gamma-blast-nifty-24500ce-test-20261031",
        actor="TEST_USER",
    )

    assert result["status"] == "SUCCESS"
    assert result["hedge_symbol"] == "NIFTY24750CE"
    assert result["locked_profit_pts"] == 28.0
    assert "Order:" in result["message"]

    # Verify updated alert state
    updated = engine.get_alert_by_id("aa-gamma-blast-nifty-24500ce-test-20261031")
    assert updated is not None
    assert updated.metrics.get("free_roll_locked") is True
    assert updated.actionable_plan.get("wing_lock_executed") is True
    assert updated.actionable_plan.get("free_roll_active") is True

    # Verify audit trail contains WING_LOCK_EXECUTED
    trail = [a.get("event_type") or a.get("action") for a in updated.audit_trail]
    assert any("WING_LOCK_EXECUTED" in str(evt) for evt in trail)


def test_execute_wing_lock_hedge_invalid_alert():
    """Verify that attempting wing-lock on invalid alert raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        execute_wing_lock_hedge("nonexistent-alert-id-999")


def test_api_orders_wing_lock_endpoint(monkeypatch):
    """Verify FastAPI /api/orders/wing-lock endpoint dispatches wing lock cleanly."""
    monkeypatch.setenv("CHANAKYA_TESTING", "1")
    monkeypatch.setenv("DEPLOY_MODE", "test")

    from market.instrument_master import upsert_verified_contract

    upsert_verified_contract(
        lookup_symbol="NIFTY24800CE",
        provider="fyers",
        provider_symbol="NSE:NIFTY26OCT24800CE",
        provider_token="10002",
        exchange="NSE",
        segment="OPTIONS",
        lot_size=25,
        tick_size=0.05,
        expiry_date="2026-10-29",
    )

    engine = get_auto_alert_engine()
    alert = AutoAlert(
        alert_id="aa-test-api-winglock-alert",
        alert_type="GAMMA_BLAST",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="NIFTY 24500 CE Free-Roll",
        summary="Test Free Roll",
        ltp=150.0,
        trigger_level=100.0,
        target_level=160.0,
        stop_loss=80.0,
        lot_size=25,
        actionable_plan={
            "hedge_ticket": {
                "action": "SELL",
                "symbol": "NIFTY24800CE",
                "strike": 24800.0,
                "option_type": "CE",
                "limit_price": 38.0,
                "order_type": "LIMIT",
                "shares": 25,
            },
        },
        metrics={},
    )
    with engine._lock:
        engine._alerts.insert(0, alert)

    client = TestClient(app)
    resp = client.post(
        "/api/orders/wing-lock",
        json={"alert_id": "aa-test-api-winglock-alert", "limit_price": 38.0, "quantity": 25},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["hedge_symbol"] == "NIFTY24800CE"

    # Also test RESTful route alias /api/alerts/auto/{alert_id}/wing-lock
    resp_alias = client.post("/api/alerts/auto/aa-test-api-winglock-alert/wing-lock")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["status"] == "SUCCESS"


# ── 4. DOM Greeks Fusion Tests ────────────────────────────────────────────────


def test_get_realtime_orderbook_greeks_confluence():
    """Verify DOM 50-level depth and GEX/DEX wall confluence fusion."""
    mock_depth = {
        "symbol": "NIFTY",
        "status": "LIVE_50_DEPTH",
        "obi_50": 0.35,
        "density_score": 88.0,
        "bids": [
            {"level": 1, "price": 24395.0, "qty": 1200, "orders": 5},
            {"level": 2, "price": 24400.0, "qty": 8500, "orders": 12},  # Massive Bid Wall at 24400
        ],
        "asks": [
            {"level": 1, "price": 24405.0, "qty": 800, "orders": 4},
            {"level": 2, "price": 24500.0, "qty": 6500, "orders": 9},  # Ask Wall at 24500
        ],
        "fortress_bid_wall_confirmed": True,
        "fortress_ask_wall_confirmed": False,
    }

    mock_gex_obj = MagicMock(
        call_wall=24500.0,
        put_wall=24400.0,  # Aligns with DOM Bid Wall at 24400!
        gamma_flip=24420.0,
        dex_regime="DEALER_NET_SHORT_DELTA",
        dex_neutral_level=24440.0,
        total_net_gex_cr=210.0,
        total_net_dex_cr=-450.0,
    )

    with patch("market.fyers_tbt_manager.fyers_tbt_manager.get_50_depth", return_value=mock_depth):
        with patch("analysis.gex.get_gex_analysis", return_value=mock_gex_obj):
            res = get_realtime_orderbook_greeks("NIFTY", spot=24410.0)

    assert res["symbol"] == "NIFTY"
    assert res["spot"] == 24410.0
    assert res["bid_confluence"] is True  # Bid Wall 24400 == Put Wall 24400
    assert res["ask_confluence"] is True  # Ask Wall 24500 == Call Wall 24500
    assert res["fortress_bid_wall"] is True
    assert res["dex_regime"] == "DEALER_NET_SHORT_DELTA"
    assert res["microstructure_wall_conviction"] >= 80
    assert "CONFLUENCE:" in res["synthesis"]
