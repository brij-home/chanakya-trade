"""
tests/test_alert_dedup_and_dispatch_hygiene.py
───────────────────────────────────────────────
Institutional regression test suite verifying RCA-first alert deduplication,
confluence upgrade in-place isolation, in-session re-entry reset buffers,
high-ticket strike-drift shielding, concurrent post-terminal shields,
and signal reference immutability.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import patch

import pytest

from config.constants import IST
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from bot.alert_templates import render_auto_alert, MilestoneAlertData


def make_alert(**kwargs) -> AutoAlert:
    defaults = {
        "alert_id": "aa-gamma-MIDCPNIFTY-20261019",
        "alert_type": "GAMMA_BLAST",
        "stage": "PRIMED",
        "symbol": "MIDCPNIFTY",
        "exchange": "NFO",
        "direction": "BULLISH",
        "headline": "Test Alert Headline",
        "summary": "Test Alert Summary",
        "ltp": 100.0,
        "trigger_level": 100.0,
        "target_level": 110.0,
        "stop_loss": 95.0,
        "environment": "LIVE",
        "is_live": True,
        "created_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    }
    defaults.update(kwargs)
    return AutoAlert(**defaults)


@pytest.fixture
def clean_engine(tmp_path):
    """Provides an isolated AutoAlertEngine instance backed by a temporary file."""
    data_file = str(tmp_path / "test_auto_alerts.json")
    with patch.dict(os.environ, {"AUTO_ALERTS_FILE": data_file}):
        engine = AutoAlertEngine()
        engine._alerts.clear()
        engine._dispatched_milestones.clear()
        engine._dispatch_cooldowns.clear()
        yield engine


def test_apex_confluence_upgrade_does_not_redispatch_primary_card(clean_engine):
    """
    RCA 1: Confluence upgrade must upgrade the active alert in-place and broadcast
    to UI via SSE, but NEVER re-dispatch duplicate primary cards to Telegram.
    """
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Active initial alert on MIDCPNIFTY
    alert1 = make_alert(
        alert_id="aa-gamma-MIDCPNIFTY-20261019",
        symbol="MIDCPNIFTY",
        direction="BULLISH",
        alert_type="GAMMA_BLAST",
        stage="PRIMED",
        created_at=now_str,
        confidence=88,
        strike=12500.0,
        option_type="CE",
        contract_symbol="MIDCPNIFTY26OCT12500CE",
        telegram_dispatched=True,
    )
    clean_engine._alerts.append(alert1)

    # 2. Incoming second detector alert on same underlying & direction
    alert2 = make_alert(
        alert_id="aa-options_momentum-MIDCPNIFTY-20261019",
        symbol="MIDCPNIFTY",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        stage="PRIMED",
        created_at=now_str,
        confidence=90,
        strike=12500.0,
        option_type="CE",
        contract_symbol="MIDCPNIFTY26OCT12500CE",
    )

    with (
        patch.object(clean_engine, "_dispatch") as mock_dispatch,
        patch("web.sse.event_bus.publish_sync") as mock_sse,
        patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor.verify_tier1_sanity",
            return_value=(True, "OK", {}),
        ),
    ):
        res = clean_engine.record_alert(alert2)

        # Alert 2 must be suppressed from creating a new separate card
        assert res is False

        # Alert 1 must be upgraded in-place to APEX_CONFLUENCE
        assert alert1.confidence >= 93
        assert (alert1.metrics or {}).get("conviction_tier") == "APEX_CONFLUENCE"

        # Confluence upgrade must NOT call _dispatch (which sends duplicate Telegram cards)
        mock_dispatch.assert_not_called()

        # Confluence upgrade must push in-place update to UI via SSE
        mock_sse.assert_called()


def test_apex_confluence_upgrade_suppressed_when_active_trade_in_drawdown(clean_engine):
    """
    RCA: When an active trade is in negative drawdown (>= 8% loss), incoming secondary detectors
    must NOT boost conviction or trigger APEX_CONFLUENCE_UPGRADE (preventing averaging into losers).
    """
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Active initial alert on MIDCPNIFTY entered at 100.0, but currently in drawdown at 88.0 (-12%)
    alert1 = make_alert(
        alert_id="aa-gamma-MIDCPNIFTY-20261026",
        symbol="MIDCPNIFTY",
        direction="BEARISH",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        created_at=now_str,
        confidence=85,
        strike=12825.0,
        option_type="PE",
        contract_symbol="MIDCPNIFTY26OCT12825PE",
        initial_entry_premium=100.0,
        ltp=88.0,
        pnl_pct=-12.0,
        telegram_dispatched=True,
    )
    clean_engine._alerts.append(alert1)

    # 2. Incoming second detector alert (INDEX_PUT_SETUP) arrives while active trade is in drawdown
    alert2 = make_alert(
        alert_id="aa-index_put_setup-MIDCPNIFTY-20261026",
        symbol="MIDCPNIFTY",
        direction="BEARISH",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        created_at=now_str,
        confidence=90,
        strike=12825.0,
        option_type="PE",
        contract_symbol="MIDCPNIFTY26OCT12825PE",
    )

    with (
        patch.object(clean_engine, "_dispatch") as mock_dispatch,
        patch("web.sse.event_bus.publish_sync"),
        patch(
            "engine.alert_scrutiny.alert_scrutiny_auditor.verify_tier1_sanity",
            return_value=(True, "OK", {}),
        ),
    ):
        res = clean_engine.record_alert(alert2)

        # Must return False (suppressed)
        assert res is False

        # Alert 1 MUST NOT be upgraded to APEX_CONFLUENCE
        assert alert1.confidence == 85, "Confidence must NOT be boosted on a trade in drawdown"
        assert (alert1.metrics or {}).get("conviction_tier") != "APEX_CONFLUENCE"

        # No duplicate dispatches or false confluence upgrades
        mock_dispatch.assert_not_called()


def test_in_session_secondary_reentry_15m_reset_buffer(clean_engine):
    """
    RCA 3: Zero-delay in-session re-entry must be suppressed.
    A secondary re-entry (-v2-) is only allowed after a 15-minute (900s) structural reset buffer.
    """
    now = datetime.now(IST)
    exit_time_recent = now.strftime("%Y-%m-%d %H:%M:%S IST")

    # Prior alert that just exited on RUNNER_EXIT
    alert_prior = make_alert(
        alert_id="aa-index_put_setup-BANKNIFTY-20261019",
        symbol="BANKNIFTY",
        direction="BEARISH",
        alert_type="INDEX_PUT_SETUP",
        stage="RUNNER_EXIT",
        archived_at=exit_time_recent,
        created_at=exit_time_recent,
        strike=55500.0,
        option_type="PE",
        ltp=100.0,
        stop_loss=60.0,
        target_level=180.0,
    )
    clean_engine._alerts.append(alert_prior)

    # Immediate new alert on the same instrument
    alert_new = make_alert(
        alert_id="aa-index_put_setup-BANKNIFTY-20261019",
        symbol="BANKNIFTY",
        direction="BEARISH",
        alert_type="INDEX_PUT_SETUP",
        stage="PRIMED",
        created_at=exit_time_recent,
        strike=55500.0,
        option_type="PE",
        ltp=100.0,
        stop_loss=60.0,
        target_level=180.0,
    )

    with patch.dict(os.environ, {"CHANAKYA_TESTING": "0"}):
        # 1. Immediate re-entry attempt: must be suppressed by the 15-minute reset buffer
        res_immediate = clean_engine.record_alert(alert_new)
        assert res_immediate is False
        assert "-v2-" not in alert_new.alert_id

        # 2. Fast forward 901 seconds (15m 1s)
        old_exit_dt = datetime.fromtimestamp(now.timestamp() - 901, tz=IST)
        alert_prior.archived_at = old_exit_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        # Now re-entry is permitted and upgraded to -v2-
        res_after_buffer = clean_engine.record_alert(alert_new)
        assert res_after_buffer is True
        assert "-v2-" in alert_new.alert_id


def test_high_ticket_strike_drift_sensex_shield(clean_engine):
    """
    RCA 4: On high-ticket indices like SENSEX (75,000+), strike drift up to 1.5%
    (~1,100 pts) must be shielded as the same thesis, preventing competing strikes
    (e.g., 74800 PE vs 74300 PE) from cluttering Telegram.
    """
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    # Active alert: SENSEX 74800 PE
    active_sensex = make_alert(
        alert_id="aa-index_put_setup-SENSEX-20261019",
        symbol="SENSEX",
        direction="BEARISH",
        alert_type="INDEX_PUT_SETUP",
        stage="ACTIONABLE",
        created_at=now_str,
        strike=74800.0,
        option_type="PE",
        contract_symbol="SENSEX26OCT74800PE",
    )
    clean_engine._alerts.append(active_sensex)

    # New incoming alert 5 minutes later: SENSEX 74300 PE (500 pts difference = 0.66%)
    competing_sensex = make_alert(
        alert_id="aa-gamma-SENSEX-20261019",
        symbol="SENSEX",
        direction="BEARISH",
        alert_type="GAMMA_BLAST",
        stage="PRIMED",
        created_at=now_str,
        strike=74300.0,
        option_type="PE",
        contract_symbol="SENSEX26OCT74300PE",
    )

    # Should be shielded and suppressed by In-Flight Index Thesis Shield
    res = clean_engine.record_alert(competing_sensex)
    assert res is False


def test_universal_signal_once_and_post_terminal_shield(clean_engine):
    """
    RCA 2 & Universal Signal Once:
    1. Once an alert has telegram_dispatched=True, duplicate non-milestone cards are suppressed.
    2. Once an alert has suffered a TERMINAL_EXIT, any subsequent dispatch is rejected by the Post-Terminal Shield.
    """
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = make_alert(
        alert_id="aa-breakout-TCS-20261019",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        alert_type="SQUEEZE_BREAKOUT",
        stage="PRIMED",
        created_at=now_str,
        confidence=92,
        environment="LIVE",
        is_live=True,
        telegram_dispatched=True,
    )

    with (
        patch("engine.alerts._telegram_notify") as mock_tg,
        patch("engine.alerts._is_market_hours", return_value=True),
    ):
        # 1. Attempting to dispatch a duplicate non-milestone card in ACTIONABLE stage
        alert.stage = "ACTIONABLE"
        clean_engine._dispatch(alert)
        mock_tg.assert_not_called()

        # 2. Attempting to dispatch in IGNITED stage
        alert.stage = "IGNITED"
        clean_engine._dispatch(alert)
        mock_tg.assert_not_called()

        # 3. Valid lifecycle milestone: T1_ACHIEVED (allowed through with valid price reaching target)
        alert.stage = "T1_ACHIEVED"
        alert.target_status = "T1_ACHIEVED"
        alert.ltp = 112.0
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 1

        # 4. First exit: RUNNER_EXIT (allowed through and latches TERMINAL_EXIT)
        alert.stage = "RUNNER_EXIT"
        alert.target_status = "RUNNER_EXIT"
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 2
        assert f"{alert.alert_id}:TERMINAL_EXIT" in clean_engine._dispatched_milestones

        # 5. Concurrent / late thread attempting a second exit or duplicate RUNNER_EXIT
        clean_engine._dispatch(alert)
        # Must be blocked by Post-Terminal Shield — call count remains 2!
        assert mock_tg.call_count == 2

        # 6. Attempting cross-path INVALIDATED after RUNNER_EXIT
        alert.stage = "INVALIDATED"
        alert.is_invalidated = True
        clean_engine._dispatch(alert)
        # Blocked — call count remains 2!
        assert mock_tg.call_count == 2


def test_signal_ref_latched_and_immutable():
    """
    Verify that an alert's signal reference (#SIG_...) is latched on first render
    and remains strictly immutable across all subsequent updates and milestones.
    """
    now_str = "2026-10-19 13:50:00 IST"
    alert = make_alert(
        alert_id="aa-options_momentum-RELIANCE-20261019",
        symbol="RELIANCE",
        direction="BULLISH",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        created_at=now_str,
        confidence=95,
        strike=3100.0,
        option_type="CE",
        contract_symbol="RELIANCE26OCT3100CE",
        actionable_plan={"action": "BUY", "contract": "RELIANCE26OCT3100CE"},
    )

    # 1. First render
    render_auto_alert(alert, in_market=True)
    initial_sig_ref = getattr(alert, "signal_ref", None)
    assert initial_sig_ref is not None
    assert initial_sig_ref.startswith("#SIG_RELIANCE_")

    # 2. Subsequent milestone update 30 minutes later
    later_str = "2026-10-19 14:20:00 IST"
    alert.stage = "T1_ACHIEVED"
    alert.target_status = "T1_ACHIEVED"
    alert.updated_at = later_str

    data = MilestoneAlertData.from_alert(alert, "TARGET_1", in_market=True)
    # The signal reference on the update MUST match the initial latched reference exactly
    assert data.signal_id == initial_sig_ref
    assert alert.signal_ref == initial_sig_ref


def test_held_primary_setup_never_leaks_downstream_milestones_or_updates(clean_engine):
    """
    RCA Regression Guard (Invariant 16 & Invariant 19):
    When a primary trade setup is held by Telegram gates (e.g., directional mutex,
    stage cooldown, apex bar, or pacing throttle), it MUST NOT mutate telegram_dispatched=True
    or latch PRIMARY_SETUP. Furthermore, ALL subsequent downstream milestones
    (IN_FLIGHT_WARNING, T0_5, T1, T2, SPREAD_FREE_ROLL, RUNNER_EXIT, INVALIDATED)
    MUST fail-closed and strictly suppress Telegram dispatch (Zero-Ghost Invariant).
    """
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    alert = make_alert(
        alert_id="aa-index_call_setup-SENSEX-CE-73500-20261029",
        symbol="SENSEX",
        exchange="BFO",
        direction="BULLISH",
        alert_type="INDEX_CALL_SETUP",
        stage="IGNITED",
        created_at=now_str,
        confidence=98,
        strike=73500.0,
        option_type="CE",
        contract_symbol="BSE:SENSEX26OCT73500CE",
        trigger_level=251.05,
        stop_loss=205.86,
        target_level=341.4,
        environment="LIVE",
        is_live=True,
    )

    # 1. Simulate directional mutex cooldown active for SENSEX BULLISH calls (900s)
    clean_engine._dispatch_cooldowns["SENSEX:BULLISH:INDEX_DIR_IGNITED"] = datetime.now(
        IST
    ).timestamp()

    with (
        patch("engine.alerts._telegram_notify") as mock_tg,
        patch("engine.alerts._is_market_hours", return_value=True),
        patch.dict(os.environ, {"ALLOW_MANUAL_TELEGRAM_DISPATCH": "1"}),
    ):
        # Step 1: Initial primary setup evaluation in IGNITED stage
        clean_engine._dispatch(alert)

        # Must NOT be dispatched to Telegram
        assert mock_tg.call_count == 0
        assert alert.telegram_dispatched is False, "telegram_dispatched MUST be False when held!"
        assert alert.telegram_delivery_status == "HELD"
        assert f"{alert.alert_id}:PRIMARY_SETUP" not in clean_engine._dispatched_milestones

        # Step 2: In-Flight Warning (Theta Decay Warning) triggers
        alert.stage = "IN_FLIGHT_WARNING"
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 0, "IN_FLIGHT_WARNING must NOT dispatch when setup was held!"
        assert (
            "zero-ghost" in alert.telegram_suppression_reason.lower()
            or "held" in alert.telegram_suppression_reason.lower()
        )

        # Step 3: Target 0.5 milestone
        alert.stage = "T0_5_ACHIEVED"
        alert.target_status = "T0_5_ACHIEVED"
        alert.ltp = 276.5
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 0, "T0_5 must NOT dispatch when setup was held!"

        # Step 4: Spread Free Roll milestone
        alert.stage = "SPREAD_FREE_ROLL"
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 0, "SPREAD_FREE_ROLL must NOT dispatch when setup was held!"

        # Step 5: Target 1 Hit
        alert.stage = "T1_ACHIEVED"
        alert.target_status = "T1_ACHIEVED"
        alert.ltp = 345.0
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 0, "T1 must NOT dispatch when setup was held!"

        # Step 6: Runner Exit
        alert.stage = "RUNNER_EXIT"
        alert.target_status = "RUNNER_EXIT"
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 0, "RUNNER_EXIT must NOT dispatch when setup was held!"

        # Step 7: View Invalidation
        alert.stage = "INVALIDATED"
        alert.is_invalidated = True
        clean_engine._dispatch(alert)
        assert mock_tg.call_count == 0, "INVALIDATED must NOT dispatch when setup was held!"
