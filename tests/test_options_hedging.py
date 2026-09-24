"""
tests/test_options_hedging.py
──────────────────────────────
Institutional unit test suite for Defined-Risk Options Hedging,
VIX-Adaptive Strategy Dispatch, In-Flight Composite Spread Tracking,
and Telegram Defined-Risk Template Rendering.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from engine.options_hedging import (
    build_defined_risk_hedge_plan,
    evaluate_spread_in_flight,
)
from bot.alert_templates import render_auto_alert
from engine.auto_alert_engine import AutoAlert

IST = timezone(timedelta(hours=5, minutes=30))


class DummyContract:
    def __init__(
        self,
        strike: float,
        option_type: str,
        last_price: float,
        volume: int = 5000,
        oi: int = 10000,
    ):
        self.strike = strike
        self.option_type = option_type
        self.last_price = last_price
        self.volume = volume
        self.oi = oi
        self.symbol = f"NIFTY{int(strike)}{option_type}"


# ── Test Suite 1: Strategy Construction & VIX Adaptation ───────────


def test_build_hedge_plan_bull_call_spread_low_vix():
    """Under low/normal volatility (VIX <= 16.5), long momentum selects Debit Bull Call Spread."""
    spot = 25000.0
    strike = 25000.0
    opt_ltp = 180.0
    chain = [
        DummyContract(25000.0, "CE", 180.0),
        DummyContract(25050.0, "CE", 150.0),
        DummyContract(25100.0, "CE", 120.0),
    ]

    hedge = build_defined_risk_hedge_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        strike=strike,
        opt_type="CE",
        opt_ltp=opt_ltp,
        chain=chain,
        lot_size=25,
        vix=14.2,
    )

    assert hedge is not None
    assert hedge["strategy"] == "BULL_CALL_SPREAD"
    assert hedge["strategy_type"] == "DEBIT_SPREAD"
    assert hedge["sentiment"] == "BULLISH"
    assert hedge["buy_strike"] == 25000.0
    assert hedge["sell_strike"] == 25050.0
    assert hedge["net_debit_per_share"] > 0
    assert hedge["max_loss"] > 0
    assert hedge["max_profit"] > 0
    assert hedge["booking_target_70"] > hedge["net_debit_per_share"]
    assert hedge["spread_stop_loss"] < hedge["net_debit_per_share"]
    assert "SEBI Hedged Margin" in hedge["margin_benefit_note"]
    assert len(hedge["legs"]) == 2
    assert hedge["legs"][0]["side"] == "BUY" and hedge["legs"][0]["strike"] == 25000.0
    assert hedge["legs"][1]["side"] == "SELL" and hedge["legs"][1]["strike"] == 25050.0


def test_build_hedge_plan_credit_spread_high_vix():
    """Under elevated volatility (VIX > 16.5), strategy shifts to Credit Spread to sell extrinsic premium."""
    spot = 25000.0
    strike = 25000.0
    opt_ltp = 240.0

    hedge = build_defined_risk_hedge_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=spot,
        strike=strike,
        opt_type="CE",
        opt_ltp=opt_ltp,
        lot_size=25,
        vix=18.5,
    )

    assert hedge is not None
    assert hedge["strategy"] == "BULL_PUT_CREDIT_SPREAD"
    assert hedge["strategy_type"] == "CREDIT_SPREAD"


def test_build_hedge_plan_bear_put_spread():
    """Bearish momentum selects Bear Put Spread."""
    spot = 56000.0
    strike = 56000.0
    opt_ltp = 320.0

    hedge = build_defined_risk_hedge_plan(
        symbol="BANKNIFTY",
        direction="BEARISH",
        spot=spot,
        strike=strike,
        opt_type="PE",
        opt_ltp=opt_ltp,
        lot_size=15,
        vix=13.8,
    )

    assert hedge is not None
    assert hedge["strategy"] == "BEAR_PUT_SPREAD"
    assert hedge["sentiment"] == "BEARISH"
    assert hedge["buy_strike"] == 56000.0
    assert hedge["sell_strike"] < 56000.0  # Lower strike sold for Bear Put
    assert len(hedge["legs"]) == 2
    assert hedge["legs"][0]["side"] == "BUY" and hedge["legs"][0]["option_type"] == "PE"
    assert hedge["legs"][1]["side"] == "SELL" and hedge["legs"][1]["option_type"] == "PE"


def test_midday_chop_window_sets_hedged_spread_preference():
    """During 11:30 - 14:00 IST with low velocity score, preferred_vehicle is HEDGED_SPREAD."""
    midday_dt = datetime(2026, 9, 24, 12, 15, tzinfo=IST)
    hedge = build_defined_risk_hedge_plan(
        symbol="NIFTY",
        direction="BULLISH",
        spot=25000.0,
        strike=25000.0,
        opt_type="CE",
        opt_ltp=150.0,
        now_dt=midday_dt,
        vel_score=60.0,
    )

    assert hedge is not None
    assert hedge["preferred_vehicle"] == "HEDGED_SPREAD"
    assert "MIDDAY CHOP WINDOW" in hedge["execution_guidance"]


def test_single_stock_strike_step():
    """Single-stock F&O dynamic step scaling adheres to price tiers."""
    # RELIANCE @ 2900: step = 50
    hedge_rel = build_defined_risk_hedge_plan(
        symbol="RELIANCE",
        direction="BULLISH",
        spot=2900.0,
        strike=2900.0,
        opt_type="CE",
        opt_ltp=45.0,
        lot_size=250,
    )
    assert hedge_rel is not None
    assert hedge_rel["strike_width"] == 50.0

    # TATASTEEL @ 160: step = 5
    hedge_ts = build_defined_risk_hedge_plan(
        symbol="TATASTEEL",
        direction="BULLISH",
        spot=160.0,
        strike=160.0,
        opt_type="CE",
        opt_ltp=4.5,
        lot_size=5500,
    )
    assert hedge_ts is not None
    assert hedge_ts["strike_width"] == 5.0


def make_dummy_alert(**kwargs) -> AutoAlert:
    defaults = {
        "alert_id": "test-spread-01",
        "alert_type": "OPTIONS_MOMENTUM",
        "stage": "IGNITED",
        "symbol": "NIFTY",
        "exchange": "NFO",
        "direction": "BULLISH",
        "headline": "TEST ALERT",
        "summary": "Test summary",
        "ltp": 25000.0,
        "trigger_level": 25000.0,
        "target_level": 25100.0,
        "stop_loss": 24900.0,
    }
    pnl_pts_val = kwargs.pop("pnl_pts", None)
    defaults.update(kwargs)
    alert = AutoAlert(**defaults)
    if pnl_pts_val is not None:
        alert.pnl_pts = pnl_pts_val
    return alert


# ── Test Suite 2: In-Flight Spread Performance & Booking Rules ─────


def test_evaluate_spread_70_pct_profit_target():
    """Triggers SPREAD_PROFIT_70 when spread value captures >= 70% of potential profit."""
    alert = make_dummy_alert(
        alert_id="test-spread-01",
        symbol="NIFTY",
        ltp=25045.0,
        underlying_spot=25045.0,
        strike=25000.0,
        option_type="CE",
        actionable_plan={
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "sentiment": "BULLISH",
                "buy_strike": 25000.0,
                "sell_strike": 25050.0,
                "strike_width": 50.0,
                "net_debit_per_share": 20.0,
                "booking_target_70": 41.0,  # 20 + 0.7*(50-20) = 41
                "spread_stop_loss": 10.0,
            }
        },
    )

    # Spot @ 25045 is deep in the money for 25000 CE, spread expanded to >= 41.0
    res = evaluate_spread_in_flight(alert, current_ltp=25045.0)
    assert res is not None
    assert res.triggered is True
    assert res.milestone_type in ("SPREAD_PROFIT_70", "SPREAD_SHORT_STRIKE_TOUCH")
    assert res.pnl_pts > 0


def test_evaluate_spread_short_strike_wall_touch():
    """Triggers SPREAD_SHORT_STRIKE_TOUCH when underlying spot hits or breaches the short strike wall."""
    alert = make_dummy_alert(
        alert_id="test-spread-02",
        symbol="NIFTY",
        ltp=25055.0,
        underlying_spot=25055.0,
        strike=25000.0,
        option_type="CE",
        actionable_plan={
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "sentiment": "BULLISH",
                "buy_strike": 25000.0,
                "sell_strike": 25050.0,
                "strike_width": 50.0,
                "net_debit_per_share": 20.0,
                "booking_target_70": 41.0,
                "spread_stop_loss": 10.0,
            }
        },
    )

    res = evaluate_spread_in_flight(alert, current_ltp=25055.0)
    assert res is not None
    assert res.triggered is True
    assert res.milestone_type == "SPREAD_SHORT_STRIKE_TOUCH"
    assert "Short Strike Wall" in res.summary
    assert res.coaching_decision == "CLOSE_SPREAD_OR_ROLL"


def test_evaluate_spread_stop_loss():
    """Triggers SPREAD_STOP_LOSS when spread value drops below 50% net debit."""

    class DummyQuote:
        def __init__(self, last_price):
            self.last_price = last_price

    alert = make_dummy_alert(
        alert_id="test-spread-03",
        symbol="NIFTY",
        ltp=24920.0,
        underlying_spot=24920.0,
        strike=25000.0,
        option_type="CE",
        actionable_plan={
            "hedge_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "sentiment": "BULLISH",
                "buy_strike": 25000.0,
                "sell_strike": 25050.0,
                "strike_width": 50.0,
                "net_debit_per_share": 20.0,
                "booking_target_70": 41.0,
                "spread_stop_loss": 10.0,
                "legs": [
                    {"instrument": "NIFTY 25000 CE", "strike": 25000.0},
                    {"instrument": "NIFTY 25050 CE", "strike": 25050.0},
                ],
            }
        },
    )

    quotes = {
        "NIFTY 25000 CE": DummyQuote(12.0),
        "NIFTY 25050 CE": DummyQuote(4.0),
    }

    res = evaluate_spread_in_flight(alert, quotes_map=quotes)
    assert res is not None
    assert res.triggered is True
    assert res.milestone_type == "SPREAD_STOP_LOSS"
    assert res.current_net_value == 8.0
    assert "50% Debit Eroded" in res.headline


# ── Test Suite 3: Telegram Defined-Risk Template Rendering ──────────


def test_render_auto_alert_includes_defined_risk_hedge_box():
    """Telegram alert message includes structured Defined-Risk Hedge Spread box."""
    hedge_plan = {
        "strategy": "BULL_CALL_SPREAD",
        "buy_leg": "BUY NIFTY 25000 CE @ ₹180.0",
        "sell_leg": "SELL NIFTY 25050 CE @ ₹145.0",
        "net_debit_per_share": 35.0,
        "max_loss": 875.0,
        "max_profit": 375.0,
        "risk_reward": "1:0.4",
        "booking_target_70": 45.5,
        "spread_stop_loss": 17.5,
        "short_strike": 25050.0,
        "preferred_vehicle": "HEDGED_SPREAD",
        "legs": [{"side": "BUY"}, {"side": "SELL"}],
    }

    alert = make_dummy_alert(
        alert_id="test-tg-01",
        symbol="NIFTY",
        ltp=180.0,
        underlying_spot=25010.0,
        strike=25000.0,
        option_type="CE",
        contract_symbol="NIFTY25000CE",
        actionable_plan={
            "action": "BUY CE",
            "contract": "NIFTY 25000 CE",
            "recommended_entry": "₹180.0",
            "stop_loss": "₹140.0",
            "target": "₹240.0",
            "hedge_plan": hedge_plan,
        },
    )

    msg = render_auto_alert(alert, in_market=True)

    assert "🛡️ <b>DEFINED-RISK HEDGE SPREAD" in msg
    assert "• <b>Strategy:</b> <code>Bull Call Spread</code>" in msg
    assert "• <b>Leg 1 (Long):</b> <code>BUY NIFTY 25000 CE @ ₹180.0</code>" in msg
    assert "• <b>Leg 2 (Short):</b> <code>SELL NIFTY 25050 CE @ ₹145.0</code>" in msg
    assert "• <b>Net Debit / Max Loss:</b> <code>₹35.0/sh (₹875 total)</code>" in msg
    assert (
        "• <b>Booking Target (70%):</b> <code>₹45.5 spread value</code> or <code>Spot ₹25,050</code>"
        in msg
    )
    assert "• <b>Spread SL:</b> <code>₹17.5</code>" in msg
    assert "SEBI Hedged Margin" in msg
    assert "Midday Chop Defense: Preferred" in msg


def test_render_spread_milestone_alerts():
    """Verify spread lifecycle milestones render distinctive Telegram coaching messages."""
    alert = make_dummy_alert(
        alert_id="test-ms-01",
        symbol="NIFTY",
        ltp=42.5,
        underlying_spot=25048.0,
        contract_symbol="NIFTY 25000/25050 SPREAD",
        stage="SPREAD_PROFIT_70",
        target_status="SPREAD_PROFIT_70",
        pnl_pts=22.5,
        pnl_pct=112.5,
    )

    msg = render_auto_alert(alert, in_market=True)
    assert "🎯 <b>[REAL/LIVE] SPREAD 70% PROFIT TARGET CAPTURED</b>" in msg
    assert "Spread Net Value:</b> ₹42.50" in msg
    assert "+112.5%" in msg
    assert "CLOSE BOTH LEGS AT MARKET" in msg

    # Short strike touch
    alert.stage = "SPREAD_SHORT_STRIKE_TOUCH"
    alert.target_status = "SPREAD_SHORT_STRIKE_TOUCH"
    msg_touch = render_auto_alert(alert, in_market=True)
    assert "⚠️ <b>[REAL/LIVE] SPREAD SHORT STRIKE PIN WALL</b>" in msg_touch
    assert "CLOSE SPREAD OR ROLL SHORT LEG HIGHER" in msg_touch

    # Stop loss
    alert.stage = "SPREAD_STOP_LOSS"
    alert.target_status = "SPREAD_STOP_LOSS"
    alert.pnl_pts = -10.0
    alert.pnl_pct = -50.0
    alert.ltp = 10.0
    msg_sl = render_auto_alert(alert, in_market=True)
    assert "🛑 <b>[REAL/LIVE] SPREAD RISK MITIGATION EXIT</b>" in msg_sl
    assert "50% DEBIT EROSION" in msg_sl
    assert "SCRATCH / EXIT SPREAD AT MARKET" in msg_sl
