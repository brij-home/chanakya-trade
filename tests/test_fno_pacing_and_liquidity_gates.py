"""
tests/test_fno_pacing_and_liquidity_gates.py
─────────────────────────────────────────────
Deterministic regression & invariant tests for:
1. Priority 3: Stock Option Contract Liquidity Gate (OI >= 1,000, Spread <= 2.0%).
2. Priority 4: IV Percentile / Vega Crush Guard (> 75% mandates defined-risk spreads).
3. Predator Index Attempt Cap (1-hour lockout with Apex/Volume override).
4. In-Flight Index Thesis Shield & Hourly Pacing Governor (up to 2/hr, +1 for Apex, Confluence Upgrade).
5. Sector Cluster Correlation Governor (+1 leader expansion for Apex).
"""

from __future__ import annotations

import time
from datetime import datetime
import pytest

from config.constants import IST
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlertEngine


def _build_test_alert(
    alert_id: str,
    symbol: str,
    alert_type: str = "OPTIONS_MOMENTUM",
    direction: str = "BULLISH",
    confidence: int = 86,
    ltp: float = 35.0,
    sl: float = 28.0,
    t1: float = 49.0,
    strike: float = None,
    option_type: str = None,
    underlying: str = None,
    metrics: dict = None,
    actionable_plan: dict = None,
    lot_size: int = 1,
    time_horizon: str = "INTRADAY",
) -> AutoAlert:
    # Use next-month settlement expiry to avoid SEBI physical delivery expiry week veto
    exp_str = "2026-11-26" if strike else None
    contract = f"{symbol}{int(strike)}{option_type}" if strike and option_type else None
    m = {
        "underlying": underlying or symbol,
        "strike": strike,
        "rvol": 2.5,
        "fii_aligned": True,
        "hbcm": {"confluence_pass": True},
    }
    if metrics:
        m.update(metrics)

    und_spot = 25000.0 if (symbol in ("NIFTY", "BANKNIFTY") or strike) else ltp

    return AutoAlert(
        alert_id=alert_id,
        alert_type=alert_type,
        stage="IGNITED",
        symbol=symbol,
        exchange="NFO" if strike else "NSE",
        direction=direction,
        headline=f"Setup for {symbol}",
        summary=f"Analysis for {symbol}",
        ltp=ltp,
        trigger_level=ltp,
        target_level=t1,
        stop_loss=sl,
        strike=strike,
        option_type=option_type,
        contract_symbol=contract,
        expiry_date=exp_str,
        underlying_spot=und_spot,
        option_premium=ltp if strike else None,
        is_live=True,
        environment="LIVE",
        time_horizon=time_horizon,
        confidence=confidence,
        lot_size=lot_size,
        metrics=m,
        actionable_plan=actionable_plan or {},
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    )


@pytest.fixture
def scrutiny_auditor():
    return AlertScrutinyAuditor()


@pytest.fixture
def alert_engine():
    engine = AutoAlertEngine()
    engine._alerts.clear()
    engine._cooldowns.clear()
    engine._stopped_strike_quarantine.clear()
    engine._directional_quarantine.clear()
    engine._directional_failure_history.clear()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}
    yield engine
    engine._alerts.clear()
    engine._cooldowns.clear()
    engine._stopped_strike_quarantine.clear()
    engine._directional_quarantine.clear()
    engine._directional_failure_history.clear()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}


# ── 1. Priority 3: Stock Option Liquidity Gate ──────────────────────────────────────────


def test_stock_option_oi_gate_institutional_floor(scrutiny_auditor):
    """Stock options with 50 <= OI < 1,000 contracts are vetoed with downgrade to cash."""
    alert_sub_institutional = _build_test_alert(
        alert_id="aa-opt-oi-sub-inst-20261019",
        symbol="NSE:INFY",
        strike=1900.0,
        option_type="CE",
        lot_size=1,
        metrics={"oi": 500, "volume": 120, "bid": 34.8, "ask": 35.2},
    )
    passed, reason, flags = scrutiny_auditor.verify_tier1_sanity(alert_sub_institutional)
    assert passed is False
    assert "Stock Option Illiquidity Trap" in reason
    assert "< 1,000 contracts" in reason
    assert flags["liquidity_valid"] is False
    assert flags["downgrade_to_cash"] is True


def test_stock_option_spread_tightened_to_2_percent(scrutiny_auditor):
    """Stock options with bid-ask spread > 2.0% trigger Slippage Hazard Veto with cash downgrade."""
    # 2.85% spread: bid=34.0, ask=35.0 on LTP=35.0
    alert_wide_spread = _build_test_alert(
        alert_id="aa-opt-wide-spread-20261019",
        symbol="NSE:RELIANCE",
        strike=2900.0,
        option_type="CE",
        lot_size=1,
        metrics={"oi": 2500, "volume": 500, "bid": 34.0, "ask": 35.0},
    )
    passed, reason, flags = scrutiny_auditor.verify_tier1_sanity(alert_wide_spread)
    assert passed is False
    assert "Slippage Hazard Veto" in reason
    assert flags["spread_valid"] is False
    assert flags["downgrade_to_cash"] is True


def test_stock_option_institutional_liquidity_pass(scrutiny_auditor):
    """Stock options with OI >= 1,000 and spread <= 2.0% pass liquidity scrutiny."""
    # 1.14% spread: bid=34.8, ask=35.2 on LTP=35.0
    alert_liquid = _build_test_alert(
        alert_id="aa-opt-liquid-pass-20261019",
        symbol="NSE:TCS",
        strike=4100.0,
        option_type="CE",
        lot_size=1,
        metrics={"oi": 3000, "volume": 600, "bid": 34.8, "ask": 35.2},
    )
    passed, reason, flags = scrutiny_auditor.verify_tier1_sanity(alert_liquid)
    assert passed is True
    assert flags["liquidity_valid"] is True
    assert flags["spread_valid"] is True


# ── 2. Priority 4: IV Percentile / Vega Crush Guard ────────────────────────────────────


def test_iv_percentile_crush_veto_on_naked_long(scrutiny_auditor):
    """Naked option buying into IV Percentile > 75% is vetoed to prevent volatility crush."""
    alert_high_iv = _build_test_alert(
        alert_id="aa-opt-high-iv-20261019",
        symbol="NSE:INFY",
        strike=1900.0,
        option_type="CE",
        lot_size=1,
        metrics={"oi": 5000, "volume": 800, "bid": 34.8, "ask": 35.2, "iv_percentile": 84.5},
    )
    passed, reason, flags = scrutiny_auditor.verify_tier1_sanity(alert_high_iv)
    assert passed is False
    assert "IV Crush Hazard Veto" in reason
    assert "84.5%" in reason
    assert flags["iv_crush_hazard"] is True


def test_iv_percentile_allowed_for_defined_risk_spread(scrutiny_auditor):
    """Defined-Risk Vertical Spreads bypass the IV Crush Veto because short leg hedges vega."""
    alert_spread = _build_test_alert(
        alert_id="aa-opt-spread-pass-20261019",
        symbol="NSE:INFY",
        strike=1900.0,
        option_type="CE",
        lot_size=1,
        actionable_plan={"strategy_type": "VERTICAL_SPREAD"},
        metrics={"oi": 5000, "volume": 800, "bid": 34.8, "ask": 35.2, "iv_percentile": 84.5},
    )
    passed, reason, flags = scrutiny_auditor.verify_tier1_sanity(alert_spread)
    assert passed is True
    assert flags.get("iv_crush_hazard") is not True


# ── 3. Predator Index Attempt Cap with 1-Hour Lockout & Apex/Volume Override ─────────


def test_predator_index_lockout_and_apex_override(alert_engine):
    """2 stopped attempts locks out for 1 hour unless Apex Confluence or RVOL >= 2.5x overrides it."""
    now_t = time.time()
    idx_d_key = ("NIFTY", "BULLISH")

    # Record 2 recent failures in the last 20 minutes
    alert_engine._directional_failure_history[idx_d_key] = [
        now_t - 1200.0,
        now_t - 600.0,
    ]

    # Standard alert without Apex or high volume must be blocked
    standard_alert = _build_test_alert(
        alert_id="aa-nifty-std-20261019",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        confidence=82,
        ltp=150.0,
        sl=120.0,
        t1=210.0,
        strike=25000.0,
        option_type="CE",
        metrics={"tod_rvol": 1.4, "oi": 50000, "volume": 10000, "bid": 149.0, "ask": 151.0},
    )
    recorded = alert_engine.record_alert(standard_alert)
    assert recorded is False

    # Apex confluence candidate overrides the 1-hour lockout!
    apex_alert = _build_test_alert(
        alert_id="aa-nifty-apex-override-20261019",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        confidence=93,
        ltp=150.0,
        sl=120.0,
        t1=210.0,
        strike=25000.0,
        option_type="CE",
        metrics={
            "tod_rvol": 1.5,
            "is_apex_confluence": True,
            "oi": 50000,
            "volume": 10000,
            "bid": 149.0,
            "ask": 151.0,
        },
    )
    recorded_apex = alert_engine.record_alert(apex_alert)
    assert recorded_apex is True

    # High institutional volume (RVOL >= 2.5x) also overrides the lockout!
    volume_alert = _build_test_alert(
        alert_id="aa-nifty-vol-override-20261019",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        confidence=84,
        ltp=150.0,
        sl=120.0,
        t1=210.0,
        strike=25000.0,
        option_type="CE",
        metrics={"tod_rvol": 2.8, "oi": 50000, "volume": 10000, "bid": 149.0, "ask": 151.0},
    )
    alert_engine._alerts.clear()
    alert_engine._cooldowns.clear()
    recorded_vol = alert_engine.record_alert(volume_alert)
    assert recorded_vol is True


# ── 4. In-Flight Index Thesis Shield: Apex Confluence Upgrade & Anti-Stacking ──────────


def test_inflight_index_thesis_shield_confluence_upgrade(alert_engine):
    """Subsequent detector on running index setup executes Apex Confluence Upgrade (+10%)."""
    base_alert = _build_test_alert(
        alert_id="aa-nifty-base-20261019",
        symbol="NIFTY",
        alert_type="INDEX_CALL_SETUP",
        direction="BULLISH",
        confidence=80,
        ltp=150.0,
        sl=120.0,
        t1=210.0,
        strike=25000.0,
        option_type="CE",
        metrics={
            "confluence_detectors": ["INDEX_CALL_SETUP"],
            "signals": ["INDEX_CALL_SETUP"],
            "oi": 50000,
            "volume": 10000,
            "bid": 149.0,
            "ask": 151.0,
        },
    )
    recorded_base = alert_engine.record_alert(base_alert)
    assert recorded_base is True

    # Incoming second detector (GAMMA_BLAST) on the same index and direction
    second_detector = _build_test_alert(
        alert_id="aa-nifty-gamma-20261019",
        symbol="NIFTY",
        alert_type="GAMMA_BLAST",
        direction="BULLISH",
        confidence=85,
        ltp=150.0,
        sl=120.0,
        t1=210.0,
        strike=25050.0,
        option_type="CE",
        metrics={"oi": 50000, "volume": 10000, "bid": 149.0, "ask": 151.0},
    )
    recorded_second = alert_engine.record_alert(second_detector)
    # Must NOT record as separate competing card
    assert recorded_second is False

    # Base alert must be upgraded in-place
    active_nifty = alert_engine._alerts[0]
    assert active_nifty.confidence >= 95  # Confidence upgraded with +10% boost
    assert active_nifty.metrics["is_apex_confluence"] is True
    assert "GAMMA_BLAST" in active_nifty.metrics["confluence_detectors"]


# ── 5. Sector Cluster Correlation Governor: Apex Capacity Expansion (+1) ─────────────


def test_sector_cluster_apex_expansion(alert_engine):
    """Sector allows +1 leader when incoming candidate has Apex confluence."""
    # 1st IT stock leader: INFY
    infy_leader = _build_test_alert(
        alert_id="aa-infy-leader-20261019",
        symbol="INFY",
        alert_type="BREAKOUT",
        direction="BULLISH",
        confidence=84,
        ltp=1900.0,
        sl=1860.0,
        t1=1980.0,
        metrics={
            "sector_id": "IT",
            "sector_name": "Information Technology",
            "tod_rvol": 2.0,
            "bid": 1898.0,
            "ask": 1902.0,
        },
    )
    alert_engine.record_alert(infy_leader)

    # 2nd IT stock: TCS with standard confidence (held to prevent cluster crowding)
    tcs_follower = _build_test_alert(
        alert_id="aa-tcs-follower-20261019",
        symbol="TCS",
        alert_type="BREAKOUT",
        direction="BULLISH",
        confidence=82,
        ltp=4100.0,
        sl=4000.0,
        t1=4300.0,
        metrics={
            "sector_id": "IT",
            "sector_name": "Information Technology",
            "tod_rvol": 1.5,
            "bid": 4095.0,
            "ask": 4105.0,
        },
    )
    recorded_follower = alert_engine.record_alert(tcs_follower)
    assert recorded_follower is False  # Suppressed by single leader rule

    # 3rd IT stock: TCS with Apex Confluence (confidence >= 90) -> expands sector capacity (+1)
    tcs_apex = _build_test_alert(
        alert_id="aa-tcs-apex-20261019",
        symbol="TCS",
        alert_type="BREAKOUT",
        direction="BULLISH",
        confidence=92,
        ltp=4100.0,
        sl=4000.0,
        t1=4300.0,
        metrics={
            "sector_id": "IT",
            "sector_name": "Information Technology",
            "tod_rvol": 2.2,
            "is_apex_confluence": True,
            "bid": 4095.0,
            "ask": 4105.0,
        },
    )
    recorded_apex = alert_engine.record_alert(tcs_apex)
    assert recorded_apex is True  # Allowed as 2nd concurrent leader under Apex expansion!
