"""
tests/test_alert_templates.py
─────────────────────────────
Comprehensive unit tests for the institutional Telegram alert template engine:
- F&O Options / Gamma Blast templates
- Equity Execution Readiness & Breakout templates
- Precursor Radar & Asymmetric Opportunity templates
- Milestone Lifecycle (Target 1, Final Target, Trail Ratchet, Invalidation)
- Zero-redundancy and mobile height reduction checks
"""

from datetime import date
import pytest
from bot.alert_templates import (
    FNOAlertData,
    EquityAlertData,
    MilestoneAlertData,
    render_fno_alert,
    render_equity_alert,
    render_precursor_alert,
    render_asymmetric_alert,
    render_milestone_alert,
    render_price_alert,
    render_auto_alert,
    resolve_expiry_cycle,
    escape_tg,
    format_price,
    normalize_env_tag,
    build_signal_ref,
    _format_call_time_and_elapsed,
)
from engine.auto_alert_engine import AutoAlert


def test_escape_tg_and_helpers():
    """Verify HTML escaping prevents malformed tags in Telegram output."""
    raw = "NIFTY <24000> & BANKNIFTY"
    escaped = escape_tg(raw)
    assert "&lt;24000&gt;" in escaped
    assert "&amp;" in escaped

    assert format_price(1234.5) == "₹1,234.50"
    assert format_price("₹500.00") == "₹500.00"
    assert format_price("Open") == "Open"

    assert normalize_env_tag("LIVE", in_market=True) == "[REAL/LIVE]"
    assert normalize_env_tag("TEST", in_market=True) == "[TEST]"
    assert normalize_env_tag("LIVE", in_market=False) == "[OFF-MARKET]"


def test_render_fno_alert_dataclass():
    """Verify F&O alert rendered from typed FNOAlertData is crisp, complete, and compact."""
    data = FNOAlertData(
        contract="NIFTY 24500 CE",
        underlying="NIFTY",
        spot=24480.0,
        action="BUY",
        score=92,
        entry_range="₹85.00 – ₹92.00",
        premium=88.0,
        stop_loss=66.0,
        stop_loss_pct="-25.0%",
        target_1=118.0,
        target_1_pct="+34.0%",
        target_2=145.0,
        target_2_pct="+65.0%",
        risk_reward="1:2.6",
        no_chase_limit="₹105.00",
        vol_oi=3.8,
        imbalance=3.2,
        trigger_reason="Aggressive call writer capitulation",
        profit_rule="Book 50% at T1, SL to Cost",
        conviction_score={
            "total_score": 92,
            "verdict": "MAX_CONVICTION",
            "recommended_position_size": "2X",
        },
        environment="LIVE",
        in_market=True,
    )

    msg = render_fno_alert(data)

    # Content assertions
    assert "NIFTY 24500 CE" in msg
    assert "Spot: <b>₹24,480.00</b>" in msg
    assert "Expiry:</b>" in msg
    assert "Weekly" in msg or "Monthly" in msg
    assert "Action:</b> <b>BUY NIFTY 24500 CE</b>" in msg
    assert "Entry Zone:</b> <code>₹85.00 – ₹92.00</code>" in msg
    assert "Invalidation SL:</b> <code>₹66.00</code> (-25.0%)" in msg
    assert "Target 1 (1.5R):</b> <code>₹118.00</code> (+34.0%)" in msg
    assert "Target 2 (2.5R):</b> <code>₹145.00</code> (+65.0%)" in msg
    assert "DO NOT CHASE:</b> Above <code>₹105.00</code>" in msg
    assert "Conviction:</b> <b>92/100</b> (MAX_CONVICTION) · ⚡ 2X Size" in msg
    assert "Playbook:</b> <i>Book 50% at T1, SL to Cost</i>" in msg
    assert "Chanakya" not in msg
    assert "GAMMA BLAST SURGE" in msg
    assert "🏷️ <b>Ref:</b> <code>#SIG_NIFTY_24500CE" in msg

    # Height and compactness assertions (<= 14 lines)
    lines = [line for line in msg.split("\n") if line.strip()]
    assert len(lines) <= 14, f"F&O alert exceeded 14 lines: {len(lines)} lines"


def test_render_fno_alert_dict_fallback():
    """Verify raw dict input is cleanly normalized and rendered."""
    blast_dict = {
        "contract": "BANKNIFTY 52000 PE",
        "action_title": "BUY BANKNIFTY 52000 PE",
        "score": 88,
        "blast_reason": "Heavy put buyer sweep",
        "vol_oi_ratio": 2.8,
        "imbalance_ratio": 2.4,
        "premium": 150.0,
        "entry_range": "₹145.00 – ₹155.00",
        "stop_loss": 112.50,
        "target_1": 202.50,
        "target_2": 247.50,
        "when_to_wait": "DO NOT CHASE if premium exceeds ₹175.00",
        "profit_rule": "Scale 50% at T1, move SL to breakeven",
    }
    msg = render_fno_alert(blast_dict, underlying="BANKNIFTY", spot=52100.0)

    assert "BANKNIFTY 52000 PE" in msg
    assert "BUY BANKNIFTY 52000 PE" in msg
    assert "Expiry:</b>" in msg
    assert "₹145.00 – ₹155.00" in msg
    assert "₹112.50" in msg
    assert "₹202.50" in msg
    assert "Above <code>₹175.00</code>" in msg


def test_render_equity_alert_dataclass_and_dict():
    """Verify Equity execution alert contains all necessary signals and quick sizing command."""
    eq_dict = {
        "symbol": "TRENT",
        "sector": "Retail",
        "sector_icon": "🛍️",
        "ltp": 7100.0,
        "execution_status": "READY",
        "strategic_score": 94,
        "tactical_score": 90,
        "entry_price": 7100.0,
        "stop_loss": 6880.0,
        "target_1": 7520.0,
        "target_2": 7890.0,
        "risk_reward_ratio": 2.5,
        "setup_title": "Stage 2 VCP Breakout",
        "rvol": 2.1,
        "options_oi_regime": "LONG_BUILDUP",
        "catalysts": ["TTM Squeeze Fired", "2.1x RVOL Expansion"],
        "when_to_wait": "DO NOT CHASE if price exceeds ₹7,220.00",
    }

    msg = render_equity_alert(eq_dict)

    assert "READY TO EXECUTE" in msg
    assert "TRENT" in msg
    assert "₹7,100.00" in msg
    assert "Strategic: <b>94/100</b>" in msg
    assert "Live Tactical: <b>90/100</b>" in msg
    assert "RVOL: <b>2.1x</b>" in msg
    assert "Target 1 (2R):</b> <code>₹7,520.00</code>" in msg
    assert "Target 2 (3.5R):</b> <code>₹7,890.00</code>" in msg
    assert "DO NOT CHASE:</b> Above <code>₹7,220.00</code>" in msg
    assert "/size TRENT 7100.00 6880.00" in msg
    assert "🏷️ <b>Ref:</b> <code>#SIG_TRENT" in msg

    lines = [l for l in msg.split("\n") if l.strip()]
    assert len(lines) <= 14, f"Equity alert exceeded 14 lines: {len(lines)} lines"


def test_render_precursor_and_asymmetric_alerts():
    """Verify Precursor and Asymmetric setups render crisp, decisive institutional cards."""
    prec_dict = {
        "symbol": "DIXON",
        "segment": "FNO",
        "conviction_score": 90,
        "verdict": "MAX_CONVICTION",
        "ltp": 12400.0,
        "entry_range": "₹12,350 – ₹12,450",
        "stop_loss": 12150.0,
        "target_1": 12800.0,
        "target_2": 13150.0,
        "risk_reward": "1:2.8",
        "matched_factors": ["Volume Dry-Up (18% of 20D)", "4-day TTM Squeeze"],
        "when_to_wait": "DO NOT CHASE if price gaps > 1.8% to ₹12,600",
    }
    p_msg = render_precursor_alert(prec_dict)
    assert "PRECURSOR RADAR" in p_msg
    assert "Chanakya" not in p_msg
    assert "DIXON [FNO]" in p_msg
    assert "90/100" in p_msg
    assert "MAX_CONVICTION" in p_msg
    assert "DO NOT CHASE" in p_msg or "Above" in p_msg

    asym_dict = {
        "symbol": "POLYCAB",
        "segment": "EQUITY",
        "conviction_score": 89,
        "verdict": "HIGH_CONVICTION",
        "ltp": 6400.0,
        "entry_range": "₹6,380 – ₹6,420",
        "stop_loss": 6250.0,
        "target_1": 6700.0,
        "target_2": 7000.0,
        "moonshot_target": 7400.0,
        "risk_reward_ratio": 3.5,
        "confluences": ["Pocket Pivot", "Weekly Base Breakout"],
    }
    a_msg = render_asymmetric_alert(asym_dict)
    assert "ASYMMETRIC SETUP" in a_msg
    assert "Chanakya" not in a_msg
    assert "POLYCAB" in a_msg
    assert "Moonshot (+6R+):</b> <code>₹7,400.00</code>" in a_msg
    assert "1:3.5 R:R" in a_msg


def test_render_milestone_alerts():
    """Verify all lifecycle milestones (T1, Final, Trailing Stop, Invalidation) render decisive actions."""
    # 1. Target 1
    t1_data = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="BEL",
        alert_type="SQUEEZE BREAKOUT",
        ltp=315.0,
        target_level=315.0,
        trailing_stop=302.5,
        locked_profit_pct=0.8,
        environment="LIVE",
    )
    t1_msg = render_milestone_alert(t1_data)
    assert "TARGET 1 ACHIEVED" in t1_msg
    assert "BOOK 50% PROFIT NOW & HOLD RUNNER" in t1_msg
    assert "100% risk-free" in t1_msg.lower()

    # 2. Final Target Hit
    final_data = MilestoneAlertData(
        milestone_type="FINAL_TARGET",
        symbol="BEL",
        alert_type="SQUEEZE BREAKOUT",
        ltp=335.0,
        target_level=330.0,
        should_trail=False,
    )
    final_msg = render_milestone_alert(final_data)
    assert "FINAL TARGET REACHED" in final_msg
    assert "CLOSE ALL POSITIONS (BOOK FULL PROFIT)" in final_msg

    # 3. Runner Extension (Trailing)
    runner_data = MilestoneAlertData(
        milestone_type="FINAL_TARGET",
        symbol="BEL",
        alert_type="SQUEEZE BREAKOUT",
        ltp=345.0,
        target_level=330.0,
        trailing_stop=332.0,
        locked_profit_pct=8.5,
        should_trail=True,
    )
    runner_msg = render_milestone_alert(runner_data)
    assert "RUNNER EXTENSION" in runner_msg
    assert "LET RUNNER RIDE (TRAIL SL)" in runner_msg
    assert "₹332.00" in runner_msg

    # 4. Trailing Stop Ratchet
    trail_data = MilestoneAlertData(
        milestone_type="TRAIL_RATCHET",
        symbol="BEL",
        ltp=322.0,
        trailing_stop=312.0,
        locked_profit_pts=10.0,
        locked_profit_pct=3.2,
    )
    trail_msg = render_milestone_alert(trail_data)
    assert "TRAILING STOP RATCHET" in trail_msg
    assert "UPDATE SL ORDER TO ₹312.00" in trail_msg

    # 5. Invalidation
    inval_data = MilestoneAlertData(
        milestone_type="INVALIDATED",
        symbol="HAL",
        alert_type="PRECURSOR RADAR",
        invalidation_reason="Breached base floor support ₹4,650",
    )
    inval_msg = render_milestone_alert(inval_data)
    assert "VIEW INVALIDATED" in inval_msg
    assert "NO LONGER VALID" in inval_msg
    assert "CANCEL PENDING ORDERS & CLOSE POSITIONS" in inval_msg


def test_render_milestone_alert_full_traceability():
    """Verify Target 1 alert renders full traceability: contract, hashtag ref, call time, original plan, P&L gain."""
    t1_trace_data = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="HAL",
        contract="HAL 26SEP 4500 CE",
        alert_type="OPTIONS MOMENTUM",
        ltp=118.10,
        signal_id="#SIG_HAL_4500CE_11SEP_0942",
        call_time="2026-09-11 09:42:00 IST",
        timestamp="2026-09-11 10:45:12 IST",
        entry_price=105.00,
        initial_sl=92.00,
        target_1=118.00,
        target_2=180.83,
        trailing_stop=96.54,
        locked_profit_pct=0.2,
        pnl_pts=13.10,
        pnl_pct=12.5,
        r_multiple=1.0,
        environment="LIVE",
    )
    rendered = render_milestone_alert(t1_trace_data)

    # 1. Header & Instrument
    assert "TARGET 1 HIT" in rendered
    assert "HAL 26SEP 4500 CE (OPTIONS MOMENTUM) — TARGET 1 ACHIEVED" in rendered

    # 2. Traceability Tag & Original Call Time
    assert "🏷️ <b>Ref:</b> <code>#SIG_HAL_4500CE_11SEP_0942</code>" in rendered
    assert "📞 <b>Call Given:</b> 9:42 AM IST" in rendered
    assert "⏱️ 1h 03m ago" in rendered

    # 3. Original Plan Baseline
    assert "Original Plan:" in rendered
    assert "Entry: ₹105.00" in rendered
    assert "SL: ₹92.00" in rendered
    assert "T1: ₹118.00" in rendered
    assert "T2: ₹180.83" in rendered

    # 4. Current Opt CMP & P&L Attribution
    assert "Opt CMP:</b> ₹118.10 | <b>Target 1:</b> ₹118.00" in rendered
    assert "Move:</b> <b>+₹13.10 (+12.5% | +1.0R)</b>" in rendered

    # 5. Trailing Stop & Decisive Action
    assert "Trail Stop:</b> <code>₹96.54</code> (+0.2% Breakeven Lock) (100% risk-free)" in rendered
    assert "BOOK 50% PROFIT NOW & HOLD RUNNER (Target 2: ₹180.83)" in rendered


def test_render_auto_alert_target_1_traceability():
    """Verify AutoAlert at T1_ACHIEVED translates seamlessly into a fully traceable Telegram alert."""
    alert = AutoAlert(
        alert_id="opt-hal-26sep-4500-ce-12345",
        alert_type="OPTIONS_MOMENTUM",
        stage="T1_ACHIEVED",
        symbol="HAL",
        exchange="NFO",
        direction="BULLISH",
        headline="🎯 [REAL/LIVE] OPTIONS MOMENTUM: HAL 26SEP 4500 CE @ ₹118.10",
        summary="Target 1 reached at ₹118.10.",
        ltp=118.10,
        trigger_level=105.00,
        target_level=180.83,
        stop_loss=92.00,
        strike=4500.0,
        option_type="CE",
        contract_symbol="HAL 26SEP 4500 CE",
        created_at="2026-09-11 09:42:00 IST",
        actionable_plan={
            "action": "BUY CE",
            "contract": "HAL 26SEP 4500 CE",
            "recommended_entry": "₹105.00",
            "stop_loss": "₹92.00",
            "target_1": "₹118.00",
            "target_2": "₹180.83",
        },
        trailing_stop=96.54,
        locked_profit_pct=0.2,
        confidence=92,
        is_live=True,
        environment="LIVE",
    )

    rendered = render_auto_alert(alert, in_market=True)

    assert "TARGET 1 HIT" in rendered
    assert "HAL 26SEP 4500 CE" in rendered
    assert "#SIG_HAL_4500CE_11SEP_0942" in rendered
    assert "Original Plan:" in rendered
    assert "Entry: ₹105.00" in rendered
    assert "Target 1:</b> ₹118.00" in rendered
    assert "BOOK 50% PROFIT NOW & HOLD RUNNER" in rendered


def test_build_signal_ref_and_time_formatting():
    """Verify unique, non-clashing hashtag generation and elapsed time formatting."""
    # 1. Options contract with call timestamp
    ref1 = build_signal_ref("HAL", alert_id="aa-opt-1234", contract="HAL 26SEP 4500 CE", created_at="2026-09-11 09:42:00 IST")
    assert ref1 == "#SIG_HAL_4500CE_11SEP_0942"

    # 2. Another call at later time has distinct timestamp hashtag
    ref2 = build_signal_ref("HAL", alert_id="aa-opt-5678", contract="HAL 26SEP 4500 CE", created_at="2026-09-11 10:15:00 IST")
    assert ref2 == "#SIG_HAL_4500CE_11SEP_1015"
    assert ref1 != ref2, "Two distinct calls must never share the same hashtag"

    # 3. Related milestone updates for call 1 strictly reuse call 1's unique hashtag
    update_data_call1 = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="HAL",
        contract="HAL 26SEP 4500 CE",
        signal_id=ref1,
        ltp=118.10,
    )
    rendered = render_milestone_alert(update_data_call1)
    assert ref1 in rendered
    assert ref2 not in rendered

    # 4. Put option hashtag with deterministic timestamp
    ref_pe = build_signal_ref("BANKNIFTY", alert_id="opt-52000-pe-a9f1", contract="BANKNIFTY 52000 PE", created_at="2026-09-11 09:42:00 IST")
    assert ref_pe == "#SIG_BANKNIFTY_52000PE_11SEP_0942"

    # 5. Equity alert hashtag
    ref_eq = build_signal_ref("TRENT", created_at="2026-09-11 09:42:00 IST")
    assert ref_eq == "#SIG_TRENT_11SEP_0942"

    # 6. Time formatting & elapsed duration
    call_fmt, elap_fmt = _format_call_time_and_elapsed(
        "2026-09-11 09:42:00 IST",
        "2026-09-11 10:45:00 IST",
    )
    assert "9:42 AM IST" in call_fmt
    assert "1h 03m ago" in elap_fmt


def test_render_price_alert():
    """Verify user price alert trigger formatting."""
    msg = render_price_alert("INFY", "price crossed ABOVE ₹1,950.00", ltp=1955.0)
    assert "ALERT TRIGGERED" in msg
    assert "INFY" in msg
    assert "LTP: <b>₹1,955.00</b>" in msg


def test_render_auto_alert_integration():
    """Verify AutoAlert objects route to correct templates seamlessly."""
    # Squeeze coiling early warning
    coiling_alert = AutoAlert(
        alert_id="auto-1",
        alert_type="SQUEEZE_BREAKOUT",
        stage="EARLY_WARNING",
        symbol="HDFCBANK",
        exchange="NSE",
        direction="BULLISH",
        headline="Squeeze Compression: HDFCBANK",
        summary="Coiling within 0.8% of 20D pivot.",
        ltp=1680.0,
        trigger_level=1680.0,
        target_level=1750.0,
        stop_loss=1655.0,
        confidence=90,
    )
    msg = render_auto_alert(coiling_alert)
    assert "EARLY WARNING" in msg
    assert "BREAKOUT IGNITED" not in msg
    assert "HDFCBANK" in msg

    # Ignited breakout
    ignited_alert = AutoAlert(
        alert_id="auto-2",
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NSE",
        direction="BULLISH",
        headline="Breakout Ignited: HDFCBANK",
        summary="Surging with 2.4x volume.",
        ltp=1695.0,
        trigger_level=1680.0,
        target_level=1750.0,
        stop_loss=1665.0,
        confidence=92,
    )
    msg2 = render_auto_alert(ignited_alert)
    assert "BREAKOUT IGNITED" in msg2

    # Options alert with contract plan and expiry
    opt_alert = AutoAlert(
        alert_id="auto-3",
        alert_type="GAMMA_BLAST",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",
        headline="Gamma Blast: NIFTY 24500 CE",
        summary="Call writers liquidation.",
        ltp=88.0,
        trigger_level=24500.0,
        target_level=145.0,
        stop_loss=66.0,
        strike=24500.0,
        option_type="CE",
        contract_symbol="NIFTY 24500 CE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹88.0",
            "target": "₹145.0",
            "stop_loss": "₹66.0",
            "risk_reward": "1:2.6",
            "expiry": "2026-09-17",
        },
        confidence=92,
    )
    msg3 = render_auto_alert(opt_alert)
    assert "Data-Driven Options Plan" not in msg3
    assert "NIFTY 24500 CE" in msg3
    assert "Expiry:</b>" in msg3
    assert "Action:</b> BUY <b>NIFTY 24500 CE</b>" in msg3
    assert "Invalidation SL:</b> <code>₹66.0</code>" in msg3


def test_minimalist_alert_hierarchy_and_deduplication():
    """Verify zero duplicate tags, reason placed after levels, and compact vertical footprint."""
    opt_alert = AutoAlert(
        alert_id="auto-dedup-1",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="BANKNIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="🎯 [REAL/LIVE] OPTIONS MOMENTUM (PUT SURGE): BANKNIFTY 52000 PE @ ₹145.0",
        summary="Put buyer surge with 3.2x Vol/OI. Retest of 5m VWAP.",
        ltp=145.0,
        trigger_level=52100.0,
        target_level=240.0,
        stop_loss=105.0,
        strike=52000.0,
        option_type="PE",
        contract_symbol="BANKNIFTY 52000 PE",
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹145.0",
            "target": "₹240.0",
            "stop_loss": "₹105.0",
            "risk_reward": "1:2.4",
            "expiry": "2026-09-17",
        },
        confidence=94,
    )

    rendered = render_auto_alert(opt_alert, in_market=True)

    # 1. Zero duplicate [REAL/LIVE]
    assert rendered.count("[REAL/LIVE]") == 1, f"Found multiple [REAL/LIVE] tags in alert: {rendered}"
    assert "[REAL / LIVE" not in rendered
    assert "Chanakya" not in rendered
    assert "Data-Driven Options Plan" not in rendered

    # 2. Hierarchy: Action & Levels appear BEFORE Reason
    idx_action = rendered.find("Action:")
    assert idx_action != -1
    idx_sl = rendered.find("Invalidation SL:")
    assert idx_sl != -1
    idx_reason = rendered.find("Reason:")
    assert idx_reason != -1

    assert idx_action < idx_reason, "Action must appear before Reason"
    assert idx_sl < idx_reason, "Stop Loss must appear before Reason"

    # 3. Compact line count <= 12 lines
    lines = [l for l in rendered.split("\n") if l.strip()]
    assert len(lines) <= 12, f"Alert exceeded 12 lines: {len(lines)} lines"


def test_resolve_expiry_cycle_all_scenarios():
    """Verify institutional F&O contract expiry resolution across index/equity and weekly/monthly rules."""
    ref_date = date(2026, 9, 10)  # Thursday

    # 1. 0DTE (Today's expiry on Thursday for NIFTY)
    res_0dte = resolve_expiry_cycle(
        contract="NIFTY 24500 CE",
        expiry_date="2026-09-10",
        underlying="NIFTY",
        as_of=ref_date,
    )
    assert res_0dte["is_0dte"] is True
    assert res_0dte["dte"] == 0
    assert "0DTE" in res_0dte["cycle"]
    assert "⚡ 0DTE / Today's Expiry" in res_0dte["badge"]

    # 2. Current Weekly (Next Thursday, DTE 7)
    res_cw = resolve_expiry_cycle(
        contract="NIFTY 24500 CE",
        expiry_date="2026-09-17",
        underlying="NIFTY",
        as_of=ref_date,
    )
    assert res_cw["cycle"] == "Current Weekly"
    assert res_cw["dte"] == 7
    assert res_cw["is_weekly"] is True
    assert "Current Weekly · 17-Sep-2026 (7 DTE)" == res_cw["badge"]

    # 3. Monthly Expiry (Last Thursday of September = 2026-09-24, DTE 14)
    res_cm = resolve_expiry_cycle(
        contract="NIFTY 24500 CE",
        expiry_date="2026-09-24",
        underlying="NIFTY",
        as_of=ref_date,
    )
    assert res_cm["cycle"] == "Current Monthly"
    assert res_cm["is_monthly"] is True
    assert "Current Monthly · 24-Sep-2026 (14 DTE)" == res_cm["badge"]

    # 4. Single-Stock Equity F&O (Strictly Monthly on NSE/BSE)
    res_stock = resolve_expiry_cycle(
        contract="RELIANCE 3000 CE",
        underlying="RELIANCE",
        as_of=ref_date,
    )
    assert res_stock["is_monthly"] is True
    assert res_stock["cycle"] == "Current Monthly"
    assert "24-Sep-2026" in res_stock["badge"]

    # 5. Extract date directly from contract name
    res_parse = resolve_expiry_cycle(
        contract="NIFTY 17-Sep-2026 24500 CE",
        as_of=ref_date,
    )
    assert res_parse["cycle"] == "Current Weekly"
    assert res_parse["dte"] == 7
    assert "17-Sep-2026" in res_parse["badge"]

    # 6. Extract from NSE Weekly code NIFTY2691724500CE
    res_nse_code = resolve_expiry_cycle(
        contract="NIFTY2691724500CE",
        as_of=ref_date,
    )
    assert res_nse_code["cycle"] == "Current Weekly"
    assert res_nse_code["dte"] == 7

    # 7. Next Month contract (October)
    res_nm = resolve_expiry_cycle(
        contract="TCS 4200 CE",
        expiry_date="2026-10-29",
        underlying="TCS",
        as_of=ref_date,
    )
    assert res_nm["cycle"] == "Next Monthly"
    assert res_nm["is_monthly"] is True
    assert "Next Monthly · 29-Oct-2026" in res_nm["badge"]


def test_gamma_blast_alert_contract_and_rr_resolution():
    """Verify that Gamma Blast alerts resolve specific strike/type, avoid TYOPTION, and meet institutional R:R."""
    raw_data = {
        "underlying": "NIFTY",
        "spot": 25150.0,
        "score": 92,
        "vol_oi_ratio": 3.8,
        "imbalance_ratio": 2.4,
        "blast_reason": "Institutional order flow surge",
        "profit_rule": "Scale 50% & SL to Cost",
    }
    rendered = render_fno_alert(raw_data, underlying="NIFTY", spot=25150.0)

    # 1. Contract resolution: Must NOT be generic "NIFTY OPTION"
    assert "NIFTY 25150 CE" in rendered
    assert "NIFTY OPTION" not in rendered

    # 2. Ref hashtag: Must NOT contain "TYOPTION"
    assert "TYOPTION" not in rendered
    assert "#SIG_NIFTY_25150CE" in rendered

    # 3. Dynamic spot-based premium with [TEST] provenance since real-time quote was absent
    assert "₹50.00" not in rendered
    assert "₹201.20" in rendered or "₹201." in rendered
    assert "[TEST]" in rendered
    assert "Spot: <b>₹25,150.00</b>" in rendered
    assert "Opt CMP:" in rendered

    # 4. Institutional R:R >= 1:3.0
    assert "1:3.2 R:R" in rendered
    assert "Target 1 (1.8R):" in rendered
    assert "Target 2 (3.2R):" in rendered


def test_fno_and_equity_price_showcase_and_provenance():
    """Verify that FnO alerts showcase both Spot and Opt CMP, equities showcase Spot CMP, and provenance is truthful."""
    # 1. Authentic Real-Time FnO alert
    real_fno = {
        "contract": "NIFTY 25150 CE",
        "underlying": "NIFTY",
        "spot": 25150.0,
        "premium": 195.50,
        "action_title": "BUY NIFTY 25150 CE",
        "score": 92,
        "environment": "LIVE",
        "is_realtime": True,
        "is_live": True,
    }
    rendered_fno = render_fno_alert(real_fno, spot=25150.0)
    assert "[REAL/LIVE]" in rendered_fno
    assert "Spot: <b>₹25,150.00</b> | Opt CMP: <b>₹195.50</b>" in rendered_fno
    assert "(Opt CMP: ₹195.50)" in rendered_fno

    # 2. Missing/Fallback premium forces [TEST] provenance tag
    fallback_fno = {
        "contract": "NIFTY 25150 CE",
        "underlying": "NIFTY",
        "spot": 25150.0,
        "premium": 0.0,  # Missing real quote
        "environment": "LIVE",  # Caller mistakenly claimed LIVE
    }
    rendered_fallback = render_fno_alert(fallback_fno, spot=25150.0)
    assert "[TEST]" in rendered_fallback
    assert "[REAL/LIVE]" not in rendered_fallback

    # 3. Equity alert showcases Spot CMP
    eq_data = {
        "symbol": "RELIANCE",
        "ltp": 2980.50,
        "environment": "LIVE",
    }
    rendered_eq = render_equity_alert(eq_data)
    assert "Spot CMP: <b>₹2,980.50</b>" in rendered_eq
    assert "(Spot CMP: ₹2,980.50)" in rendered_eq

    # 4. Milestone alert differentiates Opt CMP vs Spot CMP
    opt_ms = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="NIFTY",
        contract="NIFTY 25150 CE",
        alert_type="OPTIONS MOMENTUM",
        ltp=265.00,
        target_level=265.00,
    )
    rendered_opt_ms = render_milestone_alert(opt_ms)
    assert "Opt CMP:</b> ₹265.00" in rendered_opt_ms

    eq_ms = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="TCS",
        alert_type="BREAKOUT",
        ltp=4250.00,
        target_level=4250.00,
    )
    rendered_eq_ms = render_milestone_alert(eq_ms)
    assert "Spot CMP:</b> ₹4,250.00" in rendered_eq_ms


def test_milestone_alert_elapsed_time_and_not_0s_ago():
    """Verify that call time elapsed calculates true elapsed time and never shows 0s ago."""
    # Call given at 12:23 PM, update triggered at 12:31 PM (8 minutes elapsed)
    data = MilestoneAlertData(
        milestone_type="TARGET_1",
        symbol="NIFTY",
        contract="NIFTY 23150 PE",
        alert_type="OPTIONS MOMENTUM",
        ltp=58.50,
        signal_id="#SIG_NIFTY_23150PE_11SEP_1223",
        call_time="2026-09-11 12:23:00 IST",
        timestamp="2026-09-11 12:31:00 IST",
        entry_price=39.00,
        initial_sl=29.25,
        target_1=58.50,
        target_2=73.10,
        trailing_stop=39.08,
        locked_profit_pct=0.2,
        pnl_pts=19.50,
        pnl_pct=50.0,
        r_multiple=2.0,
    )
    rendered = render_milestone_alert(data)

    assert "0s ago" not in rendered
    assert "8m ago" in rendered
    assert "12:23 PM IST (Today)" in rendered
    assert "TARGET 1 ACHIEVED" in rendered
    assert "Move:</b> <b>+₹19.50 (+50.0% | +2.0R)</b>" in rendered
    assert "Trail Stop:</b> <code>₹39.08</code> (+0.2% Breakeven Lock)" in rendered


def test_auto_alert_engine_milestone_evaluation_consistency():
    """Verify that AutoAlertEngine respects recommended_entry, doesn't falsely trigger T1 at entry, and locks breakeven."""
    from engine.auto_alert_engine import AutoAlert, evaluate_alert_targets_and_trailing

    alert = AutoAlert(
        alert_id="opt-nifty-23150-pe-1223",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BULLISH",  # Option buyer
        headline="NIFTY 23150 PE Momentum",
        summary="Put buying flow",
        ltp=39.00,
        trigger_level=23150.0,  # strike
        target_level=73.10,
        stop_loss=29.25,
        strike=23150.0,
        option_type="PE",
        contract_symbol="NIFTY23150PE",
        option_premium=39.00,
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹39.00",
            "stop_loss": "₹29.25",
            "target_1": "₹58.50",
            "target_2": "₹73.10",
        },
        created_at="2026-09-11 12:23:00 IST",
    )

    # 1. At LTP ₹39.25 (+₹0.25 above entry), Target 1 (58.50) MUST NOT trigger!
    res_entry = evaluate_alert_targets_and_trailing(alert, current_ltp=39.25)
    assert res_entry is None or res_entry.new_milestone is None

    # 2. At LTP ₹58.50, Target 1 triggers with breakeven stop at ₹39.08 (+0.2% above ₹39.00, NEVER ₹19.54)
    res_t1 = evaluate_alert_targets_and_trailing(alert, current_ltp=58.50)
    assert res_t1 is not None
    assert res_t1.new_milestone == "T1_ACHIEVED"
    assert res_t1.recommended_stop == 39.08
    assert res_t1.r_multiple == 2.0
    assert res_t1.pnl_pct == 50.0


def test_put_option_buyer_milestone_rendering_correct_pnl():
    """Verify that Put option buyers with direction='BEARISH' calculate correct payoff (ltp - entry)."""
    # 1. Option price drops below entry: MUST show negative loss, NEVER fake profit!
    alert_loss = AutoAlert(
        alert_id="aa-optmom-pe-loss-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="ACTIVE",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23100 PE Momentum",
        summary="Put buying flow",
        ltp=28.85,
        trigger_level=30.55,
        target_level=45.80,
        stop_loss=22.90,
        strike=23100.0,
        option_type="PE",
        contract_symbol="NIFTY23100PE",
        option_premium=30.55,
        actionable_plan={
            "action": "BUY PE",
            "entry_range": "₹29.9 – ₹31.2",
            "stop_loss": "₹22.90",
            "target": "₹45.80",
            "target_2": "₹57.30",
        },
        created_at="2026-09-11 13:18:00 IST",
    )
    data_loss = MilestoneAlertData.from_alert(alert_loss, "TARGET_1")
    assert data_loss.pnl_pts == -1.70, f"Expected -1.70 pts, got {data_loss.pnl_pts}"
    assert data_loss.pnl_pct == -5.6, f"Expected -5.6%, got {data_loss.pnl_pct}"
    assert data_loss.r_multiple == -0.22, f"Expected -0.22R, got {data_loss.r_multiple}"

    # 2. Option price reaches Target 1 (₹45.80): MUST show positive profit and breakeven stop >= entry * 1.002
    alert_profit = AutoAlert(
        alert_id="aa-optmom-pe-win-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="T1_ACHIEVED",
        symbol="NIFTY",
        exchange="NFO",
        direction="BEARISH",
        headline="NIFTY 23100 PE Target 1",
        summary="Target 1 reached",
        ltp=45.80,
        trigger_level=30.55,
        target_level=45.80,
        stop_loss=22.90,
        strike=23100.0,
        option_type="PE",
        contract_symbol="NIFTY23100PE",
        option_premium=30.55,
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹30.55",
            "stop_loss": "₹22.90",
            "target": "₹45.80",
            "target_2": "₹57.30",
        },
        trailing_stop=30.61,
        created_at="2026-09-11 13:18:00 IST",
    )
    data_profit = MilestoneAlertData.from_alert(alert_profit, "TARGET_1")
    assert data_profit.pnl_pts == 15.25
    assert data_profit.pnl_pct == 49.9
    assert data_profit.trailing_stop >= 30.61
    rendered = render_milestone_alert(data_profit)
    assert "+₹15.25 (+49.9%" in rendered
    assert "TARGET 1 HIT" in rendered


def test_render_auto_alert_no_conflicting_cmp_or_stale_timestamp():
    """Verify that render_auto_alert does not render conflicting Opt CMP and uses triggered_at timestamp."""
    alert = AutoAlert(
        alert_id="aa-optmom-ce-hdfc-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="HDFCBANK",
        exchange="NFO",
        direction="BULLISH",
        headline="🚀 [REAL/LIVE] OPTIONS MOMENTUM: HDFCBANK680CE @ ₹22.1 (Vol/OI 4.05x)",
        summary="Institutional Call surge in HDFCBANK 680 CE. Turnover: 17,634 contracts (4.05x OI)",
        ltp=22.10,
        trigger_level=22.10,
        target_level=33.20,
        stop_loss=16.60,
        strike=680.0,
        option_type="CE",
        contract_symbol="HDFCBANK680CE",
        option_premium=22.10,
        underlying_spot=693.80,
        confidence=92,
        actionable_plan={
            "action": "BUY CE",
            "recommended_entry": "₹22.1",
            "stop_loss": "₹16.6",
            "target": "₹33.2",
            "risk_reward": "1:3.5",
        },
        created_at="2026-09-10 19:51:54 IST",
        triggered_at="2026-09-11 14:05:00 IST",
    )

    rendered = render_auto_alert(alert, in_market=True)

    # 1. Must NOT render redundant | Opt CMP: in headline because headline already specifies @ ₹22.1
    assert "Opt CMP: ₹22.10" not in rendered
    assert "Opt CMP: ₹24.70" not in rendered

    # 2. Must NOT render (Opt CMP: ...) in Action line because entry matches
    assert "BUY CE <b>HDFCBANK680CE</b> @ <code>₹22.1</code>\n" in rendered or "BUY CE <b>HDFCBANK680CE</b> @ <code>₹22.1</code> (Spot: ₹693.80)" in rendered

    # 3. Timestamp MUST show triggered_at (2026-09-11), not yesterday's created_at (2026-09-10)
    assert "2026-09-11 14:05:00 IST" in rendered
    assert "2026-09-10 19:51:54" not in rendered


def test_render_auto_alert_sanitizes_degenerate_h_and_s():
    """Verify that degenerate 'h' headline, 's' reason, and static R:R are repaired to institutional quality."""
    from engine.auto_alert_engine import AutoAlert
    from bot.alert_templates import render_auto_alert

    alert = AutoAlert(
        alert_id="aa-optmom-pe-DIXON-13500-123456",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="DIXON",
        exchange="NFO",
        direction="BEARISH",
        headline="h",
        summary="s",
        ltp=450.0,
        trigger_level=450.0,
        target_level=732.5,
        stop_loss=382.5,
        strike=13500.0,
        option_type="PE",
        contract_symbol="DIXON13500PE",
        option_premium=450.0,
        underlying_spot=13520.0,
        confidence=88,
        actionable_plan={
            "action": "BUY PE",
            "recommended_entry": "₹450.0",
            "stop_loss": "₹382.5",
            "target": "₹732.5",
            "risk_reward": "1:3.0",  # Stale static fallback
        },
        triggered_at="2026-09-11 15:28:36 IST",
    )

    rendered = render_auto_alert(alert, in_market=True)

    # 1. Must NOT render degenerate single-character 'h' or 's'
    assert "<b>h</b>" not in rendered
    assert "<b>Reason:</b> <i>s</i>" not in rendered
    assert "DIXON 13500 PE" in rendered

    # 2. Dynamic R:R calculation must accurately reflect 282.5 / 67.5 = 1:4.2, NOT static 1:3.0
    assert "1:4.2" in rendered

    # 3. Zero-redundancy spot presentation: Spot: ₹13,520.00 must appear exactly ONCE
    assert rendered.count("Spot:") == 1




