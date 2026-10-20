"""
tests/test_zero_futures_intraday_and_preorder.py
────────────────────────────────────────────────
Deterministic verification of:
  1. Zero Futures for Intraday rule: Intraday index setups never recommend Futures.
  2. STAGE_PRIMED Broker Pre-Order SL-Limit instructions: Generates exact trigger & limit prices.
  3. 09:18 IST Opening Range Radar: Pre-stages 3-minute opening bracket CE & PE strikes.
"""

import pytest
from unittest.mock import MagicMock, patch
from bot.alert_templates import render_auto_alert, render_asymmetric_alert
from market.indices import get_opening_range_battle_plan, format_opening_range_radar


def test_zero_futures_for_intraday_asymmetric_alert():
    """Verify that an intraday asymmetric index alert suppresses the Futures Preferred line."""
    asym_intraday = {
        "symbol": "NIFTY",
        "score": 92,
        "verdict": "MAX_CONVICTION",
        "ltp": 24850.0,
        "stop_loss": 24750.0,
        "target_1": 25050.0,
        "timeframe": "INTRADAY",
        "segment": "FNO_INDEX",
        "direction": "BULLISH",
        "actionable_plan": {
            "timeframe": "INTRADAY",
            "entry_range": "₹24,840 – ₹24,860",
            "stop_loss": 24750.0,
            "target_1": 25050.0,
            "lot_size": 25,
            "futures_plan": {
                "contract_symbol": "NIFTY26OCTFUT",
                "entry_price": 24860.0,
                "stop_loss": 24750.0,
                "target_1": 25050.0,
                "lot_size": 25,
            },
            "option_plan": {
                "contract_symbol": "NIFTY 24900 CE",
                "entry_premium": 135.0,
                "sl_premium": 95.0,
                "t1_premium": 215.0,
                "lot_size": 25,
            },
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "strategy_title": "Bull Call Spread",
                "buy_leg": "BUY NIFTY 24900 CE @ ₹135",
                "sell_leg": "SELL NIFTY 25100 CE @ ₹45",
                "net_debit_per_share": 90.0,
                "max_loss": 2250.0,
                "max_profit": 2750.0,
                "risk_reward": "1:1.2",
            },
        },
    }

    rendered = render_asymmetric_alert(asym_intraday)

    # 1. Futures Preferred line must be strictly suppressed for Intraday
    assert "Futures Preferred:" not in rendered
    assert "Delta 1.0 · Zero Theta Decay" not in rendered

    # 2. Hedged Spread line must be rendered
    assert "Hedged Spread (Preferred):" in rendered
    assert "Bull Call Spread" in rendered

    # 3. F&O Alternative Option must be rendered
    assert "F&O Alternative:" in rendered
    assert "NIFTY 24900 CE" in rendered


def test_stage_primed_generates_broker_sl_limit_preorder():
    """Verify that when an index alert is in STAGE_PRIMED, it emits Broker Pre-Order SL-Limit guidance."""
    from engine.alert_model import AutoAlert

    alert = AutoAlert(
        alert_id="aa-index-call-setup-nifty-ce-24900-morning-20261019",
        alert_type="INDEX_CALL_SETUP",
        stage="PRIMED",
        symbol="NIFTY",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ [PRIMED PROXIMITY] NIFTY Approaching Camarilla H4 Breakout",
        summary="Spot within 0.25% of H4 trigger",
        ltp=140.0,
        trigger_level=140.0,
        target_level=185.0,
        stop_loss=105.0,
        strike=24900,
        option_type="CE",
        contract_symbol="NIFTY 24900 CE",
        segment="FNO_INDEX",
        lot_size=25,
        confidence=88,
        actionable_plan={
            "action": "BUY CE",
            "contract": "NIFTY 24900 CE",
            "instrument": "NIFTY 24900 CE",
            "recommended_entry": "₹140.00",
            "stop_loss": "₹105.00",
            "target_1": "₹185.00",
            "broker_order_type": "BUY SL-LIMIT",
            "sl_limit_trigger": "₹143.5",
            "sl_limit_price": "₹145.7",
            "risk_reward": "1:2.8",
            "underlying_sl": "24,850.0",
        },
    )

    rendered = render_auto_alert(alert)

    # 1. Header must display STAGE PRIMED
    assert "ADVANCE CALL" in rendered
    assert "[STAGE PRIMED]" in rendered

    # 2. Broker Pre-Order line must be present with exact SL-Limit instructions
    assert "Broker Pre-Order:" in rendered
    assert "BUY SL-LIMIT @ Trigger: ₹143.5 | Limit: ₹145.7" in rendered
    assert "Auto-fills on trigger breach with zero manual latency!" in rendered

    # 3. No Futures lines
    assert "Futures Preferred:" not in rendered


def test_opening_range_battle_plan_and_radar_formatting():
    """Verify that get_opening_range_battle_plan and format_opening_range_radar compute clean brackets."""
    mock_quote = MagicMock()
    mock_quote.ltp = 24950.0
    mock_quote.close = 24900.0
    mock_quote.high = 24980.0  # 3-min ORH
    mock_quote.low = 24910.0  # 3-min ORL

    with patch("market.quotes.get_quote") as mock_get_quote:
        mock_get_quote.return_value = {"NSE:NIFTY 50": mock_quote, "NIFTY": mock_quote}

        plan = get_opening_range_battle_plan(["NIFTY"])

        assert "NIFTY" in plan
        nifty = plan["NIFTY"]
        assert nifty["orh"] == 24980.0
        assert nifty["orl"] == 24910.0
        assert nifty["orb_range"] == 70.0
        assert nifty["midpoint"] == 24945.0
        assert nifty["bull_strike"] == 25000
        assert nifty["bear_strike"] == 24900
        assert nifty["bull_contract"] == "NIFTY 25000 CE"
        assert nifty["bear_contract"] == "NIFTY 24900 PE"

        radar_msg = format_opening_range_radar(plan)

        assert "OPENING RANGE RADAR (09:18 IST)" in radar_msg
        assert "BULL TRIGGER:" in radar_msg
        assert "Above ₹24,980.0" in radar_msg
        assert "<code>NIFTY 25000 CE</code>" in radar_msg
        assert "BEAR TRIGGER:" in radar_msg
        assert "Below ₹24,910.0" in radar_msg
        assert "<code>NIFTY 24900 PE</code>" in radar_msg
        assert "FUT" not in radar_msg


def test_order_lifecycle_preview_and_execute_sl_limit(monkeypatch):
    """Verify preview_order_intent and execute_order_intent support SL_LIMIT and trigger_price."""
    from engine.order_lifecycle import (
        preview_order_intent,
        confirm_order_intent,
        execute_order_intent,
    )

    # 1. Invalid trigger_price for SL_LIMIT must raise ValueError
    with pytest.raises(ValueError, match="trigger_price must be a finite positive number"):
        preview_order_intent(
            symbol="INFY",
            side="BUY",
            quantity=10,
            price=1900.0,
            order_type="SL_LIMIT",
            trigger_price=-50.0,
        )

    # 2. Valid SL_LIMIT preview generates immutable hash and records trigger_price
    intent = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=10,
        price=1900.0,
        order_type="SL_LIMIT",
        trigger_price=1895.0,
        stop_loss=1850.0,
        target=2000.0,
    )
    assert intent.order_type == "SL_LIMIT"
    assert intent.charges.get("trigger_price") == 1895.0
    assert intent.preview_hash is not None

    # 3. Confirm and execute in paper mode: status should be OPEN (pending trigger)
    confirm_res = confirm_order_intent(intent.order_id, intent.preview_hash)
    assert confirm_res.status == "CONFIRMED"

    exec_res = execute_order_intent(intent.order_id)
    assert exec_res.status == "OPEN"
    assert exec_res.broker_order_id.startswith("PAPER-OPEN-")


def test_orders_api_preview_request_with_trigger_price():
    """Verify OrderPreviewRequest accepts trigger_price without validation errors."""
    from web.routers.orders_api import OrderPreviewRequest

    req = OrderPreviewRequest(
        symbol="RELIANCE",
        side="BUY",
        quantity=25,
        price=2950.0,
        order_type="SL_LIMIT",
        trigger_price=2945.0,
        stop_loss=2900.0,
        target=3050.0,
    )
    assert req.symbol == "RELIANCE"
    assert req.order_type == "SL_LIMIT"
    assert req.trigger_price == 2945.0
