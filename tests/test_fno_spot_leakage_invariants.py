"""
tests/test_fno_spot_leakage_invariants.py
──────────────────────────────────────────
Regression and invariant tests preventing spot price and wrong info leakage
in Stocks F&O Signals across the entire alert ingestion and template rendering pipeline.

Addresses:
- Scale Separation Invariant (Rule 14 in AGENTS.md): Stock option premiums are < 35% of underlying spot.
- Zero Spot Leakage in Option Ticket: Action line, SL, Targets, No-Chase, and Opt CMP MUST operate in option premium space.
- Spot Context Quarantine: Underlying spot price and invalidation anchor quarantined as context reference.
- Risk Per Lot Integrity: Risk per lot = option risk points * lot size (capped at premium for naked buys).
"""

from unittest.mock import patch, MagicMock
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from bot.alert_templates import render_auto_alert


def test_fno_stock_enrichment_converts_ticket_to_option_space():
    """
    Verify that when an F&O stock alert (e.g. LT SMC Orderblock Re-Test at ₹3,607–₹3,702)
    is ingested into AutoAlertEngine, _enrich_fno_contract_if_applicable converts the
    execution blueprint entirely into option premium space while preserving spot baseline in metrics.
    """
    engine = AutoAlertEngine()

    spot_price = 3628.10
    spot_sl = 3588.86
    spot_t1 = 3864.90
    spot_t2 = 3996.20
    spot_t3 = 4160.30
    spot_no_chase = 3702.00

    alert = AutoAlert(
        alert_id="aa-smc-lt-20261022",
        alert_type="SMC_OB_RETEST",
        stage="EARLY_WARNING",
        symbol="NSE:LT",
        exchange="NSE",
        direction="BULLISH",
        headline=f"🧲 SMC Demand OB Re-Test: LT at ₹3,607.00–₹3,702.00 (TIER_2_VALID) | SL ₹{spot_sl:,.2f} | R:R 1:8.71",
        summary="Price retesting unmitigated institutional Demand OB.",
        ltp=spot_price,
        trigger_level=3620.0,
        target_level=spot_t1,
        stop_loss=spot_sl,
        confidence=96,
        metrics={
            "expected_value_r": 4.83,
        },
        actionable_plan={
            "action": "BUY",
            "recommended_entry": "₹3,607.00 – ₹3,687.75",
            "entry_range": "₹3,607.00 – ₹3,687.75",
            "stop_loss": f"₹{spot_sl:,.2f}",
            "target_1": f"₹{spot_t1:,.1f}",
            "target_2": f"₹{spot_t2:,.1f}",
            "target_3": f"₹{spot_t3:,.1f}",
            "no_chase_boundary": f"₹{spot_no_chase:,.1f}",
        },
    )

    mock_resolved = MagicMock()
    mock_resolved.contract_symbol = "NSE:LT26OCT3650CE"
    mock_resolved.strike = 3650.0
    mock_resolved.option_type = "CE"
    mock_resolved.expiry_date = "29-Oct-2026"
    mock_resolved.expiry = "29-Oct-2026"
    mock_resolved.lot_size = 175
    mock_resolved.entry_premium = 54.20
    mock_resolved.sl_premium = 38.00
    mock_resolved.t1_premium = 85.00
    mock_resolved.t2_premium = 115.00
    mock_resolved.t3_premium = 145.00
    mock_resolved.spot = spot_price
    mock_resolved.as_dict.return_value = {
        "contract": "NSE:LT26OCT3650CE",
        "strike": 3650.0,
        "option_type": "CE",
        "expiry_date": "29-Oct-2026",
        "lot_size": 175,
        "entry_premium": 54.20,
        "sl_premium": 38.00,
        "t1_premium": 85.00,
        "t2_premium": 115.00,
        "t3_premium": 145.00,
        "spot": spot_price,
    }

    with (
        patch("engine.position_sizer.is_fno_symbol", return_value=True),
        patch("engine.option_resolver.resolve_option_contract", return_value=mock_resolved),
    ):
        engine._enrich_fno_contract_if_applicable(alert)

    # 1. Option identity & Scale Separation
    assert alert.contract_symbol == "NSE:LT26OCT3650CE"
    assert alert.strike == 3650.0
    assert alert.option_type == "CE"
    assert alert.segment == "FNO_STOCK"
    assert alert.lot_size == 175
    assert alert.underlying_spot == spot_price
    assert alert.option_premium == 54.20
    # Scale Separation Invariant: Option premium < 35% of underlying spot
    assert alert.option_premium < (alert.underlying_spot * 0.35)

    # 2. Actionable Plan Ticket is completely in option premium space
    ap = alert.actionable_plan
    assert ap["action"] == "BUY_CALL"
    assert "₹54.20" in ap["recommended_entry"]
    assert "₹38.00" in ap["stop_loss"]
    assert "₹85.00" in ap["target_1"]
    assert "₹115.00" in ap["target_2"]
    assert "₹145.00" in ap["target_3"]
    # No-chase must be option space (+5% of option entry = ~56.91)
    assert "₹56.91" in ap["no_chase_boundary"]

    # 3. Spot baseline quarantined in metrics
    assert alert.metrics["underlying_spot"] == spot_price
    assert alert.metrics["underlying_sl"] == spot_sl
    assert alert.metrics["spot_entry_range"] == "₹3,607.00 – ₹3,687.75"
    assert alert.metrics["spot_stop_loss"] == f"₹{spot_sl:,.2f}"

    # 4. Render Telegram message and verify zero spot leakage
    msg = render_auto_alert(alert, in_market=True)

    # Blunder 1: Opt CMP must NOT be ₹3,628.10
    assert "Opt CMP: ₹3,628" not in msg
    assert "Opt CMP: 3628" not in msg

    # Blunder 2: Option action must NOT be @ ₹3,607
    assert "@ ₹3,607" not in msg
    assert "@ ₹3,687" not in msg
    assert "BUY LT 3650 CE @ ₹5" in msg or "BUY CE @ <code>₹5" in msg or "₹54.20" in msg

    # Blunder 3: Option SL must NOT be ₹3,588.86
    # It must be ₹38.00
    assert "SL:</b> <code>₹38.00</code>" in msg or "SL:</b> <code>₹38.0" in msg or "₹38.00" in msg

    # Blunder 4: Option targets must NOT be ₹3,864 or ₹3,996
    assert "T1:</b> <code>₹3,864" not in msg
    assert "T2:</b> <code>₹3,996" not in msg
    assert "₹85.0" in msg

    # Blunder 5: Risk per lot must NOT be spot points * lot size (e.g. ₹3,174/lot)
    # Risk per lot = (54.20 - 38.00) * 175 = 16.20 * 175 = ₹2,835/lot
    assert "[Risk: ₹3,174/lot]" not in msg
    assert "Risk: ₹2,835/lot" in msg

    # Blunder 6: No-Chase must NOT be above ₹3,702.0
    assert "No-Chase:</b> <i>above ₹3,702" not in msg
    assert "No-Chase:</b> <i>above ₹56.9" in msg

    # Blunder 7: Headline must NOT have conflicting spot SL beside option contract
    assert (
        "LT 3650 CE (Lot: 175) · 🧲 SMC Demand OB Re-Test: LT at ₹3,607.00–₹3,702.00 (TIER_2_VALID) | SL ₹3,588.86"
        not in msg
    )
    assert "| SL ₹3,588.86" not in msg


def test_rescue_defense_when_alert_reaches_template_with_spot_leakage():
    """
    Defensive verification: Even if an alert bypassed enrichment or was constructed with
    spot levels inside actionable_plan, render_auto_alert detects that entry > 0.35 * spot
    and rescues the ticket from option_plan, preventing any spot leakage in the output.
    """
    spot_price = 3628.10
    spot_sl = 3588.86

    alert = AutoAlert(
        alert_id="aa-leaked-lt",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:LT",
        exchange="NSE",
        direction="BULLISH",
        headline="OPTIONS MOMENTUM: LT 3650 CE",
        summary="Volume expansion on call strike.",
        ltp=spot_price,  # Blunder: ltp set to spot price
        trigger_level=spot_price,
        target_level=3900.0,
        stop_loss=spot_sl,
        strike=3650.0,
        option_type="CE",
        contract_symbol="NSE:LT26OCT3650CE",
        lot_size=175,
        underlying_spot=spot_price,
        actionable_plan={
            "action": "BUY",
            "contract": "NSE:LT26OCT3650CE",
            "recommended_entry": "₹3,607.00 – ₹3,687.75",  # Blunder: spot entry
            "stop_loss": f"₹{spot_sl:,.2f}",  # Blunder: spot SL
            "target_1": "₹3,864.9",  # Blunder: spot target
            "option_plan": {
                "contract": "NSE:LT26OCT3650CE",
                "entry_premium": 54.20,
                "sl_premium": 38.00,
                "t1_premium": 85.00,
                "t2_premium": 115.00,
                "lot_size": 175,
                "spot": spot_price,
            },
        },
    )

    msg = render_auto_alert(alert, in_market=True)

    # Opt CMP must NOT be ₹3,628.10
    assert "Opt CMP: ₹3,628" not in msg
    assert "Opt CMP: 3628" not in msg

    # Rescued entry and SL
    assert "@ <code>₹54.20</code>" in msg or "₹54.20" in msg
    assert "@ ₹3,607" not in msg
    assert "SL:</b> <code>₹38.00</code>" in msg or "SL:</b> <code>₹38.0" in msg or "₹38.00" in msg
    assert "₹3,588" not in msg


def test_scale_separation_invariant_rejects_spot_as_opt_cmp():
    """
    Verify Scale Separation Invariant:
    If alert.option_premium is mistakenly set to spot price (>= 0.35 * spot),
    render_auto_alert and render_fno_alert discard it and never display it as Opt CMP.
    """
    alert = AutoAlert(
        alert_id="aa-scale-test",
        alert_type="OPTIONS_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:RELIANCE",
        exchange="NSE",
        direction="BULLISH",
        headline="OPTIONS MOMENTUM: RELIANCE 1300 CE",
        summary="Call buying surge.",
        ltp=1295.0,
        trigger_level=1295.0,
        target_level=1350.0,
        stop_loss=1270.0,
        strike=1300.0,
        option_type="CE",
        contract_symbol="NSE:RELIANCE26OCT1300CE",
        underlying_spot=1295.0,
        option_premium=1295.0,  # Blunder: option_premium set to spot
        actionable_plan={
            "action": "BUY",
            "contract": "NSE:RELIANCE26OCT1300CE",
            "recommended_entry": "₹28.50",
            "stop_loss": "₹19.00",
            "target_1": "₹45.00",
            "option_plan": {
                "entry_premium": 28.50,
                "sl_premium": 19.00,
                "t1_premium": 45.00,
                "spot": 1295.0,
            },
        },
    )

    msg = render_auto_alert(alert, in_market=True)
    assert "Opt CMP: ₹1,295" not in msg
    assert "Opt CMP: 1295" not in msg
    assert "₹28.50" in msg
