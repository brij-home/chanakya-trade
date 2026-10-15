"""
tests/test_pacing_and_dual_invalidation_reentry.py
──────────────────────────────────────────────────
Deterministic regression test suite validating:
  1. Telegram burst pacing bypass for FNO_INDEX and APEX opportunities (zero throttle delay).
  2. Distinct index symbols in FNO_INDEX (NIFTY vs MIDCPNIFTY) never throttle each other.
  3. Synthetic Spot SL Shielding for index micro-scalps when underlying spot is intact.
  4. Honest invalidation reporting (tightened loss-curtailing stop vs true breakeven exit).
  5. In-session secondary re-entry admission (-v2 variant elevation) after scratch exits.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo


from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.alert_evaluator import evaluate_alert_invalidation
from engine.synthetic_sl import evaluate_synthetic_spot_sl, extract_spot_invalidation_anchor
from engine.detectors.index_micro_scalp import detect_index_micro_scalp

IST = ZoneInfo("Asia/Kolkata")


class MockOptionContract:
    def __init__(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 5000,
        oi: int = 6000,
        pchange: float = 15.0,
    ):
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.pchange = pchange
        self.change_pct = pchange
        self.expiry = "2026-10-15"
        self.expiry_date = "2026-10-15"


def test_index_burst_pacing_and_cross_symbol_isolation():
    """
    Verifies that:
      A. NIFTY and MIDCPNIFTY do not throttle each other.
      B. FNO_INDEX alerts with confidence >= 90 have 0s burst cooldown and dispatch immediately.
    """
    engine = AutoAlertEngine()
    engine._alerts.clear()
    engine._hourly_telegram_dispatches = {"INDEX": [], "STOCKS": []}
    engine._dispatch_cooldowns.clear()

    # 1. Dispatch NIFTY alert at t0
    now_t = time.time()
    nifty_alert = AutoAlert(
        alert_id="aa-index-micro-scalp-nifty-pe-22550-20261012",
        alert_type="INDEX_MICRO_SCALP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ NIFTY 22550 PE 1m Micro Breakout",
        summary="NIFTY Put breakout",
        ltp=210.0,
        trigger_level=210.0,
        target_level=242.0,
        stop_loss=194.0,
        confidence=95,
        segment="FNO_INDEX",
        contract_symbol="NIFTY26O1222550PE",
        is_live=True,
        environment="LIVE",
        metrics={"conviction_tier": "APEX_CONFLUENCE"},
    )
    passed_nifty, reason_nifty = engine._eval_telegram_apex_gate(nifty_alert, in_market=True)
    assert passed_nifty, f"NIFTY APEX alert must pass, got: {reason_nifty}"

    # Record NIFTY dispatch in cooldown tracker
    engine._dispatch_cooldowns["PACING:FNO_INDEX:NIFTY"] = now_t
    engine._dispatch_cooldowns["PACING:FNO_INDEX"] = now_t

    # 2. MIDCPNIFTY arrives 11 seconds later (exactly reproducing the Oct 12 incident)
    midcp_alert = AutoAlert(
        alert_id="aa-index-micro-scalp-midcpnifty-pe-13625-20261012",
        alert_type="INDEX_MICRO_SCALP",
        stage="IGNITED",
        symbol="MIDCPNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ MIDCPNIFTY 13625 PE 1m Micro Breakout",
        summary="MIDCPNIFTY Put breakout",
        ltp=196.5,
        trigger_level=196.5,
        target_level=216.5,
        stop_loss=186.5,
        confidence=95,
        segment="FNO_INDEX",
        contract_symbol="MIDCPNIFTY26O1213625PE",
        is_live=True,
        environment="LIVE",
        metrics={"conviction_tier": "APEX_CONFLUENCE"},
    )

    # In the old code, this was blocked by: "Telegram pacing throttle active on FNO_INDEX (11s < 15s)"
    passed_midcp, reason_midcp = engine._eval_telegram_apex_gate(midcp_alert, in_market=True)
    assert passed_midcp, (
        f"MIDCPNIFTY must not be throttled by NIFTY dispatch! Reason: {reason_midcp}"
    )


def test_detector_populates_underlying_sl_and_synthetic_sl_protects_trade():
    """
    Verifies that:
      A. detect_index_micro_scalp populates underlying_sl and structural_spot_sl.
      B. evaluate_synthetic_spot_sl shields an option position when the spot index is intact.
    """
    chain = [
        MockOptionContract("NIFTY22550PE", 22550.0, "PE", 210.0),
        MockOptionContract("NIFTY22500CE", 22500.0, "CE", 180.0),
    ]
    ref_dt = datetime(2026, 10, 12, 13, 17, 0, tzinfo=IST)

    alerts = detect_index_micro_scalp(
        underlying="NIFTY",
        spot=22530.0,
        chain=chain,
        vwap=22550.0,
        day_high=22600.0,
        day_low=22480.0,
        ref_time=ref_dt,
        ignore_time_gate=True,
    )

    pe_alert = next((a for a in alerts if a.direction == "BEARISH"), None)
    assert pe_alert is not None, "Expected BEARISH Put micro-scalp alert"

    # Invariant verification: Dual Invalidation coordinates must exist
    assert pe_alert.underlying_sl is not None
    assert pe_alert.structural_spot_sl is not None
    assert pe_alert.underlying_sl >= 22550.0  # Must anchor above VWAP / resistance for Put
    assert extract_spot_invalidation_anchor(pe_alert) == pe_alert.underlying_sl

    # Now simulate momentary option premium dip from ₹210.0 to ₹190.0 (below nominal SL of ₹194.0)
    # BUT live spot index is at 22520.0 (healthy breakdown, well below spot anchor 22550.0)
    synth_eval = evaluate_synthetic_spot_sl(
        pe_alert,
        current_option_ltp=190.0,
        current_spot_override=22520.0,
    )
    assert synth_eval.is_freak_wick_shielded, (
        "Option must be shielded because underlying spot is completely intact"
    )
    assert not synth_eval.is_invalidated


def test_honest_invalidation_reporting_for_tightened_stop():
    """
    Verifies that when a stop is tightened (e.g. from 194.3 to 201.8 with entry 210.3)
    and triggered without hitting targets, it is reported as a protective stop-loss curtailing risk,
    and NOT falsely claimed as a breakeven capital protected exit.
    """
    alert = AutoAlert(
        alert_id="aa-index-micro-scalp-nifty-pe-22550-20261012",
        alert_type="INDEX_MICRO_SCALP",
        stage="COMPRESS_STALL_RISK",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ NIFTY 22550 PE 1m Micro Breakout",
        summary="NIFTY Put breakout",
        ltp=208.0,
        trigger_level=210.3,
        target_level=242.3,
        stop_loss=201.8,  # Ratcheted from 194.3, but STILL BELOW entry 210.3
        initial_stop_loss=194.3,
        option_premium=210.3,
        confidence=95,
        segment="FNO_INDEX",
        contract_symbol="NIFTY26O1222550PE",
        is_live=True,
        environment="LIVE",
    )

    # LTP dips to 198.6 (breaching tightened stop 201.8)
    msg = evaluate_alert_invalidation(alert, current_ltp=198.6)
    assert msg is not None, "Alert must be invalidated at 198.6"
    assert "breakeven (capital protected)" not in msg, (
        "Must NOT claim breakeven when exiting at a loss below entry!"
    )
    assert "Protective stop triggered" in msg
    assert "curtailed loss before initial SL" in msg


def test_secondary_reentry_admission_as_v2_variant():
    """
    Verifies that when an initial alert exits on a scratch/runner stop,
    a secondary setup for the same strike is admitted as a controlled '-v2' variant,
    preventing the system from missing afternoon trend legs.
    """
    engine = AutoAlertEngine()
    engine._alerts.clear()

    # 1. Existing alert closed with RUNNER_EXIT earlier
    alert_v1 = AutoAlert(
        alert_id="aa-index-micro-scalp-nifty-pe-22550-20261012",
        alert_type="INDEX_MICRO_SCALP",
        stage="RUNNER_EXIT",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ NIFTY 22550 PE",
        summary="Prior scalp closed",
        ltp=198.6,
        trigger_level=210.3,
        target_level=242.3,
        stop_loss=201.8,
        confidence=95,
        segment="FNO_INDEX",
        contract_symbol="NIFTY26O1222550PE",
    )
    engine._alerts.append(alert_v1)

    # 2. Later in session (e.g. 14:05), new breakdown occurs on the same contract
    new_setup = AutoAlert(
        alert_id="aa-index-micro-scalp-nifty-pe-22550-20261012",
        alert_type="INDEX_MICRO_SCALP",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="⚡ NIFTY 22550 PE Second Wave Breakdown",
        summary="Secondary institutional thrust",
        ltp=215.0,
        trigger_level=215.0,
        target_level=255.0,
        stop_loss=200.0,
        confidence=95,
        segment="FNO_INDEX",
        contract_symbol="NIFTY26O1222550PE",
        environment="TEST",
        is_live=False,
        metrics={"conviction_tier": "APEX_CONFLUENCE"},
    )

    # Must be admitted under -v2 variant ID
    accepted = engine.record_alert(new_setup)
    assert accepted, "Secondary re-entry must be admitted!"
    assert new_setup.alert_id == "aa-index-micro-scalp-nifty-pe-22550-v2-20261012"
    assert any(
        a.alert_id == "aa-index-micro-scalp-nifty-pe-22550-v2-20261012" for a in engine._alerts
    )
