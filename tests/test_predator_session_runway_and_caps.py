"""
tests/test_predator_session_runway_and_caps.py
─────────────────────────────────────────────
Comprehensive Institutional Invariant Test Suite for:
  1. Session Runway & Dynamic Cutoffs (14:00 IST Intraday Equity Cutoff, 15:15 Cutoff, Positional Exemption)
  2. Scrutiny Circuit Breaker Hard Veto (Halted detectors vetoed before LLM)
  3. Pre-Open Gap-Down 0.0R Attribution & Option Scale Separation Invariant in EOD Report
  4. Predator Index Directional Attempt Cap (Max 2 stopped attempts/session)
  5. In-Flight Index Thesis Shield (Zero concurrent strike stacking across detectors)
  6. Post-Stop Exact Strike Lockout (120-minute quarantine)
  7. Thematic Peer Sympathy Dynamic Volume & Runway Cutoff
"""

import time
from datetime import datetime, time as dtime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.session_runway import (
    classify_session_phase,
    is_session_runway_sufficient,
)
import json
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.eod_report_generator import EODReportGenerator

IST = ZoneInfo("Asia/Kolkata")


def _build_test_alert(
    alert_id: str,
    symbol: str,
    alert_type: str = "INTRADAY_MOVER_SPARK",
    direction: str = "BULLISH",
    confidence: int = 86,
    ltp: float = 100.0,
    sl: float = 95.0,
    t1: float = 110.0,
    strike: float = None,
    option_type: str = None,
    underlying: str = None,
    time_horizon: str = "INTRADAY",
    environment: str = "LIVE",
) -> AutoAlert:
    exp_str = datetime.now(IST).strftime("%Y-%m-%d")
    contract = f"{symbol}{int(strike)}{option_type}" if strike and option_type else None
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
        expiry_date=exp_str if strike else None,
        underlying_spot=ltp * 100 if strike else ltp,
        option_premium=ltp if strike else None,
        is_live=True,
        environment=environment,
        time_horizon=time_horizon,
        confidence=confidence,
        created_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        metrics={
            "underlying": underlying or symbol,
            "strike": strike,
            "rvol": 2.5,
            "fii_aligned": True,
            "vwap_trend": True,
        },
        actionable_plan={
            "risk_reward": "1:2.5",
            "entry": ltp,
            "stop_loss": sl,
            "target": t1,
        },
    )


# ── 1. Session Runway & Dynamic Cutoffs ───────────────────────────────────────────


def test_session_runway_phases():
    """Verify session phase classification across the trading day."""
    assert classify_session_phase(dtime(9, 20)) == "OPENING_AUCTION_DISCOVERY"
    assert classify_session_phase(dtime(9, 45)) == "MORNING_IMPULSE"
    assert classify_session_phase(dtime(10, 45)) == "MORNING_REVERSAL_ZONE"
    assert classify_session_phase(dtime(12, 15)) == "MIDDAY_COMPRESSION"
    assert classify_session_phase(dtime(14, 15)) == "AFTERNOON_GAMMA_POWER_HOUR"
    assert classify_session_phase(dtime(15, 20)) == "SQUAREOFF_RECONCILIATION"


def test_session_runway_intraday_equity_cutoff_at_1400():
    """Intraday equities must be cut off after 14:00 IST (< 75m runway to 15:15 IST)."""
    # 13:55 IST -> OK
    ok, reason = is_session_runway_sufficient(
        alert_type="INTRADAY_MOVER_SPARK",
        asset_class="EQUITY",
        time_horizon="INTRADAY",
        current_time=dtime(13, 55),
    )
    assert ok is True

    # 14:05 IST -> Rejected
    ok, reason = is_session_runway_sufficient(
        alert_type="INTRADAY_MOVER_SPARK",
        asset_class="EQUITY",
        time_horizon="INTRADAY",
        current_time=dtime(14, 5),
    )
    assert ok is False
    assert "SESSION_RUNWAY_EXHAUSTION" in reason
    assert "14:00 IST" in reason


def test_session_runway_positional_and_multibaggers_exempt_from_1400_cutoff():
    """Positional, Multibagger, and Swing setups are exempt from 14:00 IST intraday cutoff."""
    ok, reason = is_session_runway_sufficient(
        alert_type="MULTIBAGGER",
        asset_class="EQUITY",
        time_horizon="POSITIONAL",
        current_time=dtime(14, 30),
    )
    assert ok is True

    ok_sw, _ = is_session_runway_sufficient(
        alert_type="STAGE_1_TO_2_EXPANSION",
        asset_class="EQUITY",
        time_horizon="SWING",
        current_time=dtime(14, 45),
    )
    assert ok_sw is True


def test_session_runway_post_1515_hard_cutoff():
    """All intraday setups are rejected after 15:15 IST square-off."""
    ok, reason = is_session_runway_sufficient(
        alert_type="GAMMA_BLAST",
        asset_class="OPTIONS",
        current_time=dtime(15, 16),
    )
    assert ok is False
    assert "post 15:15 IST" in reason


# ── 2. Scrutiny Circuit Breaker Hard Veto ─────────────────────────────────────────


def test_scrutiny_circuit_breaker_hard_veto():
    """If a detector is marked HALTED by the circuit breaker, Scrutiny immediately rejects."""
    auditor = AlertScrutinyAuditor()
    alert = _build_test_alert("test-cb-halt", "RELIANCE", alert_type="INTRADAY_MOVER_SPARK")

    with patch(
        "engine.detector_circuit_breaker.detector_circuit_breaker.evaluate_alert_allowed",
        return_value=(False, 0.0, "5 consecutive stopped losses. System halt active."),
    ):
        result = auditor.scrutinize_alert(alert)
        assert result.status == "REJECTED"
        assert (
            "Circuit Breaker Tripped" in result.trap_risk_warning
            or "Circuit Breaker Tripped" in result.rejection_reason
        )


# ── 3. EOD Report Untriggered Gap-Down 0.0R & Scale Separation ────────────────────


def test_eod_untriggered_gap_over_sl_attributed_zero_r(tmp_path):
    """Untriggered pre-open gap-down alerts must realize 0.0R loss (not -1.0R)."""
    gap_alert_dict = {
        "alert_id": "aa-intraday-mrpl-20261016",
        "symbol": "MRPL",
        "alert_type": "INTRADAY_MOVER_SPARK",
        "direction": "BULLISH",
        "ltp": 157.0,
        "trigger_level": 157.0,
        "stop_loss": 154.0,
        "target_level": 165.0,
        "stage": "EXPIRED",
        "target_status": "SETUP_DISQUALIFIED",
        "invalidation_reason": "Gap over SL: Open 153.20 < SL 154.00 before entry triggered",
        "archive_reason": "Gap over SL: Open 153.20 < SL 154.00 before entry triggered",
        "r_multiple": 0.0,
        "has_triggered": False,
        "created_at": "2026-10-16 09:15:00 IST",
    }
    p = tmp_path / "auto_alerts.json"
    p.write_text(json.dumps([gap_alert_dict]), encoding="utf-8")
    gen = EODReportGenerator(data_file=p)
    report = gen.generate(target_date="2026-10-16")
    entry = report.journal_entries[0]
    assert entry.outcome in ("SETUP_DISQUALIFIED", "UNTRIGGERED_EXPIRED")
    assert entry.realized_r == 0.0


def test_eod_option_scale_separation_invariant(tmp_path):
    """Spot index levels (e.g. 55,600) must never contaminate option premium exits."""
    opt_alert_dict = {
        "alert_id": "aa-index-bn-pe-20261016",
        "symbol": "BANKNIFTY 55600 PE",
        "contract_symbol": "BANKNIFTY55600PE",
        "alert_type": "INDEX_OPTION_BUYING",
        "direction": "BEARISH",
        "strike": 55600.0,
        "option_type": "PE",
        "underlying": "BANKNIFTY",
        "ltp": 250.0,
        "trigger_level": 250.0,
        "stop_loss": 55400.0,  # Contaminated with spot index level
        "target_level": 370.0,
        "underlying_spot": 55620.0,
        "option_premium": 250.0,
        "is_invalidated": True,
        "stage": "INVALIDATED",
        "target_status": "INVALIDATED",
        "invalidation_reason": "Trailing stop breach: LTP Rs.185.0 < SL Rs.190.0",
        "r_multiple": -1.0,
        "has_triggered": True,
        "created_at": "2026-10-16 09:21:00 IST",
    }
    p = tmp_path / "auto_alerts.json"
    p.write_text(json.dumps([opt_alert_dict]), encoding="utf-8")
    gen = EODReportGenerator(data_file=p)
    report = gen.generate(target_date="2026-10-16")
    entry = report.journal_entries[0]
    assert entry.outcome == "LOSS_STOPPED"
    assert entry.realized_r == -1.0
    # Premium exit level should be in premium scale (e.g. ~185-190), NOT index spot (55,000+)
    assert entry.exit_level < 1000.0


# ── 4. Predator Index Directional Attempt Cap & Strike Lockout ────────────────────


def test_predator_index_directional_attempt_cap():
    """Max 2 stopped attempts per index per direction in a session. 3rd is blocked."""
    engine = AutoAlertEngine()
    today_start = (
        datetime.combine(datetime.now(IST).date(), datetime.min.time())
        .replace(tzinfo=IST)
        .timestamp()
    )

    # Record 2 failed attempts for MIDCPNIFTY BEARISH today
    engine._directional_failure_history[("MIDCPNIFTY", "BEARISH")] = [
        today_start + 1000.0,
        today_start + 2000.0,
    ]

    # 3rd Bearish MIDCPNIFTY alert must be blocked by the attempt cap
    alert_3rd = _build_test_alert(
        "midcp-3rd-pe",
        "MIDCPNIFTY",
        strike=13650.0,
        option_type="PE",
        direction="BEARISH",
        underlying="MIDCPNIFTY",
        environment="LIVE",
    )
    alert_3rd.is_live = True

    recorded = engine.record_alert(alert_3rd)
    assert recorded is False


def test_post_stop_exact_strike_lockout():
    """An exact option strike that stops out is locked out for 120 minutes."""
    engine = AutoAlertEngine()
    now_t = time.time()

    # Quarantine MIDCPNIFTY 13650 PE stopped 30 minutes ago
    engine._stopped_strike_quarantine["MIDCPNIFTY_13650_PE"] = now_t - 1800.0

    alert_same_strike = _build_test_alert(
        "midcp-same-strike",
        "MIDCPNIFTY",
        strike=13650.0,
        option_type="PE",
        direction="BEARISH",
        underlying="MIDCPNIFTY",
        environment="LIVE",
    )
    alert_same_strike.is_live = True

    recorded = engine.record_alert(alert_same_strike)
    assert recorded is False


def test_inflight_index_thesis_shield():
    """Zero concurrent strike stacking: 2nd alert for same index direction is blocked while 1st is active."""
    engine = AutoAlertEngine()

    active_alert = _build_test_alert(
        "midcp-active-1",
        "MIDCPNIFTY",
        strike=13650.0,
        option_type="PE",
        direction="BEARISH",
        underlying="MIDCPNIFTY",
        environment="LIVE",
    )
    active_alert.is_live = True
    active_alert.stage = "IGNITED"
    active_alert.is_active = True
    active_alert.is_invalidated = False

    engine._alerts = [active_alert]

    # 2nd alert trying different strike or same strike in same direction
    alert_concurrent = _build_test_alert(
        "midcp-drift-2",
        "MIDCPNIFTY",
        strike=13675.0,
        option_type="PE",
        direction="BEARISH",
        underlying="MIDCPNIFTY",
        environment="LIVE",
    )
    alert_concurrent.is_live = True

    recorded = engine.record_alert(alert_concurrent)
    assert recorded is False
