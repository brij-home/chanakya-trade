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
    assert "Trader Execution Playbook:</b> <i>Book 50% at T1, SL to Cost</i>" in msg
    assert "Chanakya Institutional Gamma Desk" in msg

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

    lines = [l for l in msg.split("\n") if l.strip()]
    assert len(lines) <= 13, f"Equity alert exceeded 13 lines: {len(lines)} lines"


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
    assert "CHANAKYA HIGH-CONVICTION PRECURSOR RADAR" in p_msg
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
    assert "CHANAKYA ASYMMETRIC OPPORTUNITY" in a_msg
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
    assert "Data-Driven Options Plan" in msg3
    assert "NIFTY 24500 CE" in msg3
    assert "Expiry:</b>" in msg3


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
