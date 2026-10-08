"""
tests/test_index_micro_scalp_and_reversals.py
──────────────────────────────────────────────
Deterministic test suite verifying:
  1. Index Micro Scalp 1m/3m breakout detector.
  2. Dead-cat bounce guard on Call setups below VWAP.
  3. High-velocity ITM option strike selection in morning sessions.
  4. Predatory structural reversal interception in auto_alert_engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.detectors.index_micro_scalp import detect_index_micro_scalp
from engine.detectors.index_call_setup import detect_index_call_setup
from engine.detectors.index_put_setup import detect_index_put_setup

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class MockOptionContract:
    symbol: str
    strike: float
    option_type: str
    last_price: float
    volume: int
    oi: int
    pchange: float = 0.0
    change_pct: float = 0.0
    expiry: str = "2026-10-06"
    expiry_date: str = "2026-10-06"
    oi_change: int = 500


def _build_synthetic_chain(spot: float = 22550.0) -> list[MockOptionContract]:
    """Generates synthetic NIFTY option chain around spot."""
    chain = []
    strikes = [22400.0, 22450.0, 22500.0, 22550.0, 22600.0, 22650.0, 22700.0]
    for strk in strikes:
        # CE contracts
        ce_prem = max(5.0, (spot - strk) + 60.0 if strk <= spot else 60.0 - (strk - spot) * 0.4)
        chain.append(
            MockOptionContract(
                symbol=f"NIFTY20261006{int(strk)}CE",
                strike=strk,
                option_type="CE",
                last_price=round(ce_prem, 2),
                volume=15000,
                oi=25000,
                pchange=18.5,
                oi_change=1200,
            )
        )
        # PE contracts
        pe_prem = max(5.0, (strk - spot) + 60.0 if strk >= spot else 60.0 - (spot - strk) * 0.4)
        chain.append(
            MockOptionContract(
                symbol=f"NIFTY20261006{int(strk)}PE",
                strike=strk,
                option_type="PE",
                last_price=round(pe_prem, 2),
                volume=18000,
                oi=22000,
                pchange=22.0,
                oi_change=1500,
            )
        )
    return chain


def test_index_micro_scalp_detection():
    """Verify 1m/3m micro option breakout detector on NIFTY option strikes."""
    chain = _build_synthetic_chain(spot=22550.0)
    ref_dt = datetime(2026, 10, 5, 10, 10, 0, tzinfo=IST)

    alerts = detect_index_micro_scalp(
        underlying="NIFTY",
        spot=22545.0,
        chain=chain,
        vwap=22580.0,
        day_high=22621.8,
        day_low=22500.0,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    assert len(alerts) > 0, "Expected index micro scalp alerts"
    pe_alert = next((a for a in alerts if a.direction == "BEARISH"), None)
    assert pe_alert is not None, "Expected a BEARISH PE micro-scalp alert"

    # Invariants
    assert pe_alert.alert_type == "INDEX_MICRO_SCALP"
    assert pe_alert.symbol == "NIFTY"
    assert pe_alert.direction == "BEARISH"
    assert pe_alert.stage == "IGNITED"
    assert pe_alert.ltp > 0
    assert pe_alert.stop_loss < pe_alert.trigger_level < pe_alert.target_level

    # Blueprint checks
    plan = pe_alert.actionable_plan
    assert "Buy above" in plan["when_to_buy"]
    assert "DO NOT CHASE" in plan["when_to_wait"]
    assert "Scale Blueprint" in plan["profit_rule"]
    assert pe_alert.no_chase_boundary > pe_alert.trigger_level


def test_dead_cat_bounce_suppression():
    """Verify that a dead-cat bounce below VWAP after sweeping Day High suppresses Call alerts."""
    chain = _build_synthetic_chain(spot=22562.0)
    ref_dt = datetime(2026, 10, 5, 10, 5, 0, tzinfo=IST)

    # Spot is 22562 (below VWAP 22585), after dropping from Day High 22621 (-0.26% drop)
    alerts = detect_index_call_setup(
        underlying="NIFTY",
        spot=22562.0,
        chain=chain,
        vwap=22585.0,
        day_high=22621.8,
        day_low=22531.0,
        prev_day_high=22600.0,
        prev_day_low=22450.0,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    # Should not produce false Day Low demand bounce or trend pullback reclaim
    signals = []
    for a in alerts:
        signals.extend(a.metrics.get("signals", []))

    assert "DAY_LOW_DEMAND_BOUNCE" not in signals
    assert "TREND_PULLBACK_RECLAIM" not in signals
    assert "CPR_DEMAND_BOUNCE" not in signals


def test_morning_itm_strike_selection():
    """Verify that during morning sessions (09:15–10:30 IST), 1-to-2 strike ITM options are prioritized."""
    chain = _build_synthetic_chain(spot=22580.0)
    ref_dt = datetime(2026, 10, 5, 9, 58, 0, tzinfo=IST)

    alerts = detect_index_put_setup(
        underlying="NIFTY",
        spot=22580.0,
        chain=chain,
        vwap=22585.0,
        day_high=22621.8,
        day_low=22507.5,
        prev_day_high=22600.0,
        prev_day_low=22450.0,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    assert len(alerts) > 0, "Expected put alert at 09:58"
    best_alert = alerts[0]
    # Selected strike must be >= spot (ITM Put)
    assert best_alert.strike >= 22580.0, (
        f"Expected ITM put strike >= 22580, got {best_alert.strike}"
    )
    assert best_alert.strike in (22600.0, 22650.0, 22700.0)


def test_predatory_reversal_interception_logic():
    """Verify that auto_alert_engine invalidates a failing long trade when an institutional reversal arrives."""
    from engine.auto_alert_engine import AutoAlertEngine

    engine = AutoAlertEngine()
    engine._alerts.clear()

    # Seed an active in-flight Call alert
    call_alert = AutoAlert(
        alert_id="aa-index-call-setup-nifty-ce-22550-20261005",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Nifty Call Buy",
        summary="Nifty Call Setup",
        ltp=112.0,
        trigger_level=112.0,
        target_level=152.0,
        stop_loss=84.0,
        confidence=90,
        underlying_spot=22562.0,
        created_at=(datetime.now(IST) - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S IST"),
    )
    engine._alerts.append(call_alert)

    # Incoming structural reversal Put alert (spot has dropped to 22540, carrying PDH_SUPPLY_REJECTION)
    put_alert = AutoAlert(
        alert_id="aa-index-put-setup-nifty-pe-22600-20261005",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="Nifty Put Reversal",
        summary="Nifty Put Setup on structural reversal",
        ltp=158.0,
        trigger_level=158.0,
        target_level=210.0,
        stop_loss=118.0,
        confidence=95,
        underlying_spot=22540.0,
        contract_symbol="NIFTY2026100822600PE",
        strike=22600.0,
        option_type="PE",
        option_premium=158.0,
        metrics={
            "signals": ["PDH_SUPPLY_REJECTION", "VWAP_BREAKDOWN"],
            "is_institutional_thrust": True,
            "spot": 22540.0,
        },
    )

    # Record the reversal alert
    res = engine.record_alert(put_alert)
    assert res is True, "Reversal alert should be accepted"

    # Assert that prior call alert was invalidated
    assert call_alert.is_invalidated is True, "Struggling long alert should be invalidated"
    assert call_alert.stage == "INVALIDATED"
    assert "BEARISH reversal" in (call_alert.invalidation_reason or "")
