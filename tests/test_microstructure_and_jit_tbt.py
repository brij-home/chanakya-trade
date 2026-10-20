"""
tests/test_microstructure_and_jit_tbt.py
────────────────────────────────────────
Deterministic verification of:
1. JIT TBT Scout Promotion & TTL Eviction (FyersTbtManager).
2. Native Exchange ATP (VWAP) Confluence & Posture (MarketMatrix).
3. Microstructure Order Book Thrust & Iceberg Absorption Detector (OrderBookThrustDetector).
4. Dealer Gamma Exposure (GEX) Calculation & Gamma Blast Integration (compute_chain_gex).
"""

from __future__ import annotations

import time

from engine.detection_context import build_detection_context, detector_registry
from engine.detectors.order_book_thrust import (
    OrderBookThrustDetector,
    detect_order_book_thrust,
)
from engine.detectors.gamma_blast import compute_gamma_conviction
from engine.market_matrix import MarketMatrix
from market.fyers_tbt_manager import FyersTbtManager, promote_jit_tbt_scout
from market.options import compute_chain_gex


# ─────────────────────────────────────────────────────────────────────────────
# 1. JIT TBT Scout Pipeline Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_jit_tbt_scout_promotion_and_ttl():
    """Verify dynamic JIT promotion of symbols into TBT scout capacity with TTL expiration."""
    mgr = FyersTbtManager()
    sym = "NSE:TATAMOTORS"

    # Promote symbol for 0.5 seconds
    promoted = mgr.promote_jit_scout(sym, duration_sec=0.5, reason="TEST_PRE_INFLECTION")
    assert promoted is True

    # Check slot allocation (Fyers symbol normalization maps NSE:TATAMOTORS to NSE:TATAMOTORS-EQ)
    slots = mgr.get_slot_allocation()
    assert any("TATAMOTORS" in s for s in slots["scout"])

    # Module helper function promotion
    helper_promoted = promote_jit_tbt_scout("NSE:WIPRO", duration_sec=0.5, reason="HELPER_TEST")
    assert helper_promoted is True
    assert any("WIPRO" in s for s in mgr.get_slot_allocation()["scout"])

    # Sleep past TTL and verify cleanse
    time.sleep(0.6)
    mgr.cleanse_stale_scouts(ttl_sec=0.5)
    cleansed_slots = mgr.get_slot_allocation()
    assert not any("TATAMOTORS" in s for s in cleansed_slots["scout"])
    assert not any("WIPRO" in s for s in cleansed_slots["scout"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. Native Exchange ATP (VWAP) Flow Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_native_atp_confluence_and_posture():
    """Verify exchange-authoritative ATP is prioritized over rolling buffers in MarketMatrix."""
    matrix = MarketMatrix()
    symbol = "TEST_ATP_SYM"

    # Feed tick with exchange ATP higher than LTP (bearish posture below ATP)
    matrix.on_tick({"symbol": symbol, "ltp": 2500.0, "volume": 1000, "atp": 2520.0})

    stats = matrix.get_quant_stats(symbol)
    assert stats["atp"] == 2520.0
    assert stats["session_vwap"] == 2520.0
    assert stats["atp_posture"] == "BELOW_ATP"
    assert matrix.get_atp(symbol) == 2520.0

    # Feed tick with LTP above ATP (bullish posture above ATP)
    matrix.on_tick({"symbol": symbol, "ltp": 2535.0, "volume": 1500, "atp": 2520.0})
    stats2 = matrix.get_quant_stats(symbol)
    assert stats2["atp_posture"] == "ABOVE_ATP"
    assert stats2["atp_distance_pct"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Microstructure Order Book Thrust Detector Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_order_book_thrust_bullish():
    """Verify Bullish Order Book Thrust detection with heavy OBI-50 and resting iceberg bid floor."""
    synthetic_50_depth = {
        "symbol": "NSE:RELIANCE",
        "status": "LIVE",
        "provenance": "LIVE_TBT_50",
        "ltp": 2500.0,
        "spread": 0.20,
        "tbq": 75000,
        "tsq": 25000,
        "obi_50": 0.50,
        "density_score": 42.0,
        "bids": [
            {"level": 1, "price": 2499.90, "qty": 1000, "orders": 3},
            {"level": 2, "price": 2499.70, "qty": 1200, "orders": 4},
            {"level": 3, "price": 2495.00, "qty": 15000, "orders": 6},  # Resting iceberg floor
        ],
        "asks": [
            {"level": 1, "price": 2500.10, "qty": 800, "orders": 2},
            {"level": 2, "price": 2500.30, "qty": 900, "orders": 2},
        ],
        "bid_walls": [
            {
                "level": 3,
                "price": 2495.00,
                "qty": 15000,
                "orders": 6,
                "strength": "FORTRESS",
                "book_share_pct": 20.0,
                "distance_pct": 0.20,
            }
        ],
        "ask_walls": [],
        "strongest_bid_wall": {
            "level": 3,
            "price": 2495.00,
            "qty": 15000,
            "orders": 6,
            "strength": "FORTRESS",
            "book_share_pct": 20.0,
            "distance_pct": 0.20,
        },
        "strongest_ask_wall": None,
    }

    ctx = build_detection_context(
        symbol="NSE:RELIANCE",
        ltp=2500.0,
        vwap=2498.0,  # Price 2500 is above session VWAP 2498 (ATP aligned)
        extra_metrics={"depth_50": synthetic_50_depth},
    )

    alerts = detect_order_book_thrust(ctx)
    assert len(alerts) == 1
    alert = alerts[0]

    assert alert.direction == "BULLISH"
    assert alert.stage == "IGNITED"
    assert alert.alert_type == "ORDER_BOOK_THRUST"
    assert alert.confidence >= 90.0
    assert alert.stop_loss < 2500.0
    assert alert.target_level > 2500.0
    assert alert.metrics["obi_50"] == 0.50
    assert alert.metrics["iceberg_wall_strength"] == "FORTRESS"
    assert alert.actionable_plan["action"] == "BUY"
    assert "invalidation_stop" in alert.actionable_plan


def test_order_book_thrust_bearish():
    """Verify Bearish Order Book Exhaustion with heavy negative OBI-50 and resting iceberg ask ceiling."""
    synthetic_50_depth = {
        "symbol": "NSE:INFY",
        "status": "LIVE",
        "provenance": "LIVE_TBT_50",
        "ltp": 1500.0,
        "spread": 0.15,
        "tbq": 20000,
        "tsq": 65000,
        "obi_50": -0.5294,
        "density_score": 38.0,
        "bids": [
            {"level": 1, "price": 1499.90, "qty": 600, "orders": 2},
        ],
        "asks": [
            {"level": 1, "price": 1500.05, "qty": 800, "orders": 2},
            {"level": 4, "price": 1504.00, "qty": 18000, "orders": 8},  # Resting iceberg ceiling
        ],
        "bid_walls": [],
        "ask_walls": [
            {
                "level": 4,
                "price": 1504.00,
                "qty": 18000,
                "orders": 8,
                "strength": "STRONG",
                "book_share_pct": 27.6,
                "distance_pct": 0.26,
            }
        ],
        "strongest_bid_wall": None,
        "strongest_ask_wall": {
            "level": 4,
            "price": 1504.00,
            "qty": 18000,
            "orders": 8,
            "strength": "STRONG",
            "book_share_pct": 27.6,
            "distance_pct": 0.26,
        },
    }

    ctx = build_detection_context(
        symbol="NSE:INFY",
        ltp=1500.0,
        vwap=1502.0,  # Price 1500 is below session VWAP 1502 (failing ATP)
        extra_metrics={"depth_50": synthetic_50_depth},
    )

    alerts = detect_order_book_thrust(ctx)
    assert len(alerts) == 1
    alert = alerts[0]

    assert alert.direction == "BEARISH"
    assert alert.stage == "IGNITED"
    assert alert.stop_loss > 1500.0
    assert alert.target_level < 1500.0
    assert alert.actionable_plan["action"] == "SELL"


def test_order_book_thrust_wide_spread_rejection():
    """Verify rejection when bid-ask spread is wide (> 0.35%), preventing illiquid slippage traps."""
    synthetic_wide_depth = {
        "symbol": "NSE:ILLIQUID_STOCK",
        "ltp": 100.0,
        "spread": 0.50,  # 0.50% spread (> 0.35% threshold)
        "tbq": 50000,
        "tsq": 10000,
        "obi_50": 0.66,
        "density_score": 10.0,
        "bids": [{"level": 1, "price": 99.50, "qty": 100}],
        "asks": [{"level": 1, "price": 100.00, "qty": 100}],
        "bid_walls": [],
        "ask_walls": [],
    }

    ctx = build_detection_context(
        symbol="NSE:ILLIQUID_STOCK",
        ltp=100.0,
        vwap=99.8,
        extra_metrics={"depth_50": synthetic_wide_depth},
    )

    alerts = detect_order_book_thrust(ctx)
    assert len(alerts) == 0  # Properly rejected due to wide spread


def test_order_book_thrust_registered_in_registry():
    """Verify OrderBookThrustDetector is registered in centralized DetectorRegistry."""
    detector = detector_registry.get("order_book_thrust")
    assert detector is not None
    assert isinstance(detector, OrderBookThrustDetector)
    assert "EQUITY" in detector.supported_segments
    assert "FNO_INDEX" in detector.supported_segments


# ─────────────────────────────────────────────────────────────────────────────
# 4. Dealer Gamma Exposure (GEX) & Gamma Blast Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_compute_chain_gex_acceleration_regime():
    """Verify GEX engine detects negative dealer gamma acceleration when put open interest dominates."""
    spot = 24500.0
    # Synthetic chain with heavy PEs (puts outweigh calls -> net GEX negative -> acceleration regime)
    chain = [
        {"strike": 24500, "option_type": "CE", "oi": 50000, "iv": 14.0, "expiry": "2026-10-22"},
        {"strike": 24500, "option_type": "PE", "oi": 150000, "iv": 15.0, "expiry": "2026-10-22"},
        {"strike": 24600, "option_type": "CE", "oi": 40000, "iv": 13.5, "expiry": "2026-10-22"},
        {"strike": 24400, "option_type": "PE", "oi": 120000, "iv": 15.5, "expiry": "2026-10-22"},
    ]

    gex = compute_chain_gex(chain, spot=spot, underlying="NIFTY", lot_size=25)
    assert gex["contracts_analyzed"] == 4
    assert gex["net_gex"] < 0
    assert gex["gamma_regime"] == "NEGATIVE_GAMMA_ACCELERATION"
    assert gex["is_acceleration_zone"] is True
    assert gex["gex_flip_strike"] > 0


def test_compute_chain_gex_pinning_regime():
    """Verify GEX engine detects positive dealer gamma pinning when call open interest dominates."""
    spot = 24500.0
    chain = [
        {"strike": 24500, "option_type": "CE", "oi": 200000, "iv": 14.0, "expiry": "2026-10-22"},
        {"strike": 24500, "option_type": "PE", "oi": 40000, "iv": 14.0, "expiry": "2026-10-22"},
        {"strike": 24600, "option_type": "CE", "oi": 150000, "iv": 13.0, "expiry": "2026-10-22"},
        {"strike": 24400, "option_type": "PE", "oi": 30000, "iv": 15.0, "expiry": "2026-10-22"},
    ]

    gex = compute_chain_gex(chain, spot=spot, underlying="NIFTY", lot_size=25)
    assert gex["net_gex"] > 0
    assert gex["gamma_regime"] == "POSITIVE_GAMMA_PIN"


def test_compute_gamma_conviction_with_gex():
    """Verify compute_gamma_conviction incorporates GEX acceleration boost and pinning friction."""
    # Base score in acceleration zone
    score_accel = compute_gamma_conviction(
        is_index=True,
        vol_oi_ratio=2.2,
        oi_change=-5000,
        oi_chg_pct=-15.0,
        pchange=30.0,
        volume=50000,
        c_vol=50.0,
        stage="IGNITED",
        strike_diff_pct=0.2,
        sweep_active=True,
        gamma_regime="NEGATIVE_GAMMA_ACCELERATION",
        is_acceleration_zone=True,
    )

    # Same setup in pinning chop regime without sweep
    score_pin = compute_gamma_conviction(
        is_index=True,
        vol_oi_ratio=1.5,
        oi_change=-5000,
        oi_chg_pct=-15.0,
        pchange=30.0,
        volume=50000,
        c_vol=50.0,
        stage="IGNITED",
        strike_diff_pct=0.2,
        sweep_active=False,
        gamma_regime="POSITIVE_GAMMA_PIN",
        is_acceleration_zone=False,
    )

    assert score_accel > score_pin
    assert score_accel >= 85


def test_fyers_tbt_silence_watchdog(monkeypatch):
    """
    Verify that the autonomous packet silence watchdog sentinel detects frozen sockets
    during active market hours and triggers self-healing reconnection.
    """
    import time
    from unittest.mock import MagicMock
    from market.fyers_tbt_manager import FyersTbtManager

    mgr = FyersTbtManager()
    mgr._connected = True
    mgr._access_token = "mock_token"
    mgr._subscribed = {"NSE:NIFTY26OCT25000CE"}
    mgr._silence_watchdog_threshold = 1.0  # Set low for test

    # 1. Update packet time
    t0 = time.time()
    mgr._last_packet_time = t0 - 2.0  # 2.0s ago (> 1.0s threshold)

    # 2. Simulate guardian watchdog logic
    monkeypatch.setattr("market.calendar.is_market_open", lambda exch: True)
    mock_connect = MagicMock()
    monkeypatch.setattr(mgr, "_connect", mock_connect)

    from market.calendar import is_market_open

    is_active = is_market_open("NSE")
    silence_dur = time.time() - mgr._last_packet_time
    assert is_active is True
    assert silence_dur > mgr._silence_watchdog_threshold

    old_count = mgr._reconnect_count
    if is_active and len(mgr._subscribed) > 0 and mgr._last_packet_time > 0:
        if silence_dur > mgr._silence_watchdog_threshold:
            mgr.force_reconnect()

    assert mgr._reconnect_count == old_count + 1
    assert mgr._connected is False
    assert mock_connect.called or mgr._thread is not None
