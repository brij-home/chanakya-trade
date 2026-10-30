"""
tests/test_options_five_pillars.py
──────────────────────────────────
Unit tests for the 5 Advanced Institutional Options Capabilities:
  1. Pillar 1: In-Flight "Free-Roll" Conversion Engine (evaluate_naked_option_free_roll)
  2. Pillar 2: Expiry-Day "0DTE Intraday Phase Engine" (get_0dte_intraday_phase)
  3. Pillar 3: Hard Liquidity & Bid-Ask Slippage Guard (audit_option_liquidity)
  4. Pillar 4: Real-Time Options IV Skew Calculator (compute_options_iv_skew)
  5. Pillar 5: Automated Short Strike "Roll or 80% Take-Profit" Engine (evaluate_short_strike_roll_plan)
"""

from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

from market.options import audit_option_liquidity, compute_options_iv_skew
from engine.options_hedging import (
    get_0dte_intraday_phase,
    evaluate_naked_option_free_roll,
    evaluate_short_strike_roll_plan,
    evaluate_spread_in_flight,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ── Pillar 1: In-Flight "Free-Roll" Conversion Engine ────────────────────────


def test_free_roll_conversion_below_threshold():
    """Verify naked option under 40% gain remains in HOLD_NAKED status."""
    alert = SimpleNamespace(
        symbol="NIFTY",
        contract_symbol="NIFTY26OCT24500CE",
        strike=24500.0,
        direction="BULLISH",
        entry_price=100.0,
        is_t1_achieved=False,
    )
    # Current LTP is 125 (+25% gain) -> below 40% threshold
    res = evaluate_naked_option_free_roll(alert, current_ltp=125.0, spot_price=24600.0)
    assert res["eligible"] is False
    assert res["action"] == "HOLD_NAKED"
    assert res["pnl_pct"] == 25.0


def test_free_roll_conversion_triggered():
    """Verify naked option with >= 40% gain calculates zero-downside free-roll conversion."""
    alert = SimpleNamespace(
        symbol="NIFTY",
        contract_symbol="NIFTY26OCT24500CE",
        strike=24500.0,
        direction="BULLISH",
        entry_price=100.0,
        is_t1_achieved=False,
    )
    # Current LTP is 160 (+60% gain)
    res = evaluate_naked_option_free_roll(alert, current_ltp=160.0, spot_price=24650.0)
    assert res["eligible"] is True
    assert res["action"] == "CONVERT_TO_FREE_ROLL"
    assert res["pnl_pct"] == 60.0
    assert res["short_strike_candidate"] >= 24600.0
    assert res["estimated_credit_collected"] > 0.0
    assert "recommendation" in res
    assert "Sell NIFTY" in res["recommendation"]


def test_free_roll_conversion_target_1_achieved():
    """Verify hitting Target 1 unlocks Free-Roll conversion eligibility."""
    alert = SimpleNamespace(
        symbol="BANKNIFTY",
        contract_symbol="BANKNIFTY26OCT52000CE",
        strike=52000.0,
        direction="BULLISH",
        entry_price=250.0,
        is_t1_achieved=True,
    )
    # LTP is 330 (+32% gain, below 40% purely on %, but T1 achieved)
    res = evaluate_naked_option_free_roll(alert, current_ltp=330.0, spot_price=52350.0)
    assert res["eligible"] is True
    assert res["action"] == "CONVERT_TO_FREE_ROLL"
    assert res["short_strike_candidate"] >= 52200.0


# ── Pillar 2: Expiry-Day "0DTE Intraday Phase Engine" ────────────────────────


def test_0dte_phase_weekly_schedule():
    """Verify correct 0DTE classification under SEBI's single-benchmark weekly regime."""
    # Under SEBI index derivative regulations (effective Nov 2024):
    # Mon (MIDCPNIFTY), Tue (FINNIFTY), Wed (BANKNIFTY) weekly expiries are DISCONTINUED.
    # Only NSE NIFTY (Thursday) and BSE SENSEX (Friday) offer weekly options.
    mon_dt = datetime(2026, 10, 26, 10, 30, tzinfo=IST)
    res_midcp = get_0dte_intraday_phase("MIDCPNIFTY", now_dt=mon_dt)
    res_nifty_mon = get_0dte_intraday_phase("NIFTY", now_dt=mon_dt)
    assert res_midcp["is_0dte"] is False  # Discontinued! No false 0DTE on Monday
    assert res_nifty_mon["is_0dte"] is False

    # Tuesday (2026-10-27): FINNIFTY weekly discontinued -> is_0dte is False
    tue_dt = datetime(2026, 10, 27, 10, 30, tzinfo=IST)
    assert get_0dte_intraday_phase("FINNIFTY", now_dt=tue_dt)["is_0dte"] is False

    # Wednesday (2026-10-28): BANKNIFTY weekly discontinued -> is_0dte is False
    wed_dt = datetime(2026, 10, 28, 10, 30, tzinfo=IST)
    assert get_0dte_intraday_phase("BANKNIFTY", now_dt=wed_dt)["is_0dte"] is False

    # Thursday (2026-10-29): NSE NIFTY 50 authorized weekly expiry -> is_0dte is True
    thu_dt = datetime(2026, 10, 29, 10, 30, tzinfo=IST)
    assert get_0dte_intraday_phase("NIFTY", now_dt=thu_dt)["is_0dte"] is True

    # Friday (2026-10-30): BSE SENSEX authorized weekly expiry -> is_0dte is True
    fri_dt = datetime(2026, 10, 30, 10, 30, tzinfo=IST)
    assert get_0dte_intraday_phase("SENSEX", now_dt=fri_dt)["is_0dte"] is True

    # Monthly Expiry: BANKNIFTY on last Thursday of the month (2026-10-29) -> is_0dte is True!
    assert get_0dte_intraday_phase("BANKNIFTY", now_dt=thu_dt)["is_0dte"] is True

    # Contract-level DTE: Any contract with dte=0 is explicitly 0DTE regardless of day
    assert get_0dte_intraday_phase("RELIANCE", dte=0, now_dt=mon_dt)["is_0dte"] is True
    assert get_0dte_intraday_phase("RELIANCE", dte=10, now_dt=mon_dt)["is_0dte"] is False


def test_0dte_intraday_clock_phases():
    """Verify the 4 daily intraday phases and tactical biases."""
    thu_dt = datetime(2026, 10, 29, 9, 45, tzinfo=IST)
    # Morning: 09:15 - 11:00
    res_morning = get_0dte_intraday_phase("NIFTY", now_dt=thu_dt)
    assert res_morning["phase"] == "MORNING_EXPANSION"
    assert res_morning["tactical_bias"] == "NAKED_FAVORED"
    assert res_morning["volatility_multiplier"] == 1.35

    # Midday: 11:00 - 13:30
    midday_dt = datetime(2026, 10, 29, 12, 15, tzinfo=IST)
    res_midday = get_0dte_intraday_phase("NIFTY", now_dt=midday_dt)
    assert res_midday["phase"] == "MIDDAY_THETA_GRIND"
    assert res_midday["tactical_bias"] == "SPREAD_FAVORED"
    assert res_midday["volatility_multiplier"] == 0.85

    # Afternoon Gamma Squeeze: 13:30 - 15:00
    afternoon_dt = datetime(2026, 10, 29, 14, 15, tzinfo=IST)
    res_afternoon = get_0dte_intraday_phase("NIFTY", now_dt=afternoon_dt)
    assert res_afternoon["phase"] == "AFTERNOON_GAMMA_SQUEEZE"
    assert res_afternoon["tactical_bias"] == "GAMMA_SNIPER"
    assert res_afternoon["volatility_multiplier"] == 1.80

    # Terminal Closing: 15:00 - 15:30
    closing_dt = datetime(2026, 10, 29, 15, 10, tzinfo=IST)
    res_closing = get_0dte_intraday_phase("NIFTY", now_dt=closing_dt)
    assert res_closing["phase"] == "TERMINAL_CLOSING"
    assert res_closing["tactical_bias"] == "SQUARE_OFF"

    # Off-market
    post_dt = datetime(2026, 10, 29, 16, 0, tzinfo=IST)
    assert get_0dte_intraday_phase("NIFTY", now_dt=post_dt)["phase"] == "OFF_MARKET"


# ── Pillar 3: Hard Liquidity & Bid-Ask Slippage Guard ────────────────────────


def test_audit_option_liquidity_slippage_guard():
    """Verify midpoint pricing and <= 1.8% slippage guard pass/fail."""
    # 1. Liquid contract with tight spread (0.4% spread)
    quote_tight = {
        "bid": 99.8,
        "ask": 100.2,
        "ltp": 100.0,
        "oi": 50000,
        "volume": 12000,
    }
    res_tight = audit_option_liquidity(quote_tight, underlying="NIFTY")
    assert res_tight["is_liquid"] is True
    assert res_tight["slippage_guard_passed"] is True
    assert res_tight["midpoint_price"] == 100.0
    assert res_tight["smart_limit_entry"] == 100.0
    assert res_tight["recommended_order_type"] == "LIMIT_OR_MARKET"

    # 2. Moderate contract with 1.2% spread (requires LIMIT_MIDPOINT)
    quote_mod = {
        "bid": 99.0,
        "ask": 100.2,
        "ltp": 100.0,
        "oi": 15000,
        "volume": 3000,
    }
    res_mod = audit_option_liquidity(quote_mod, underlying="NIFTY")
    assert res_mod["is_liquid"] is True
    assert res_mod["slippage_guard_passed"] is True
    assert res_mod["midpoint_price"] == 99.6
    assert res_mod["recommended_order_type"] == "LIMIT_MIDPOINT"

    # 3. Illiquid stock option with wide spread (6.0% spread > 1.8%)
    quote_wide = {
        "bid": 97.0,
        "ask": 103.0,
        "ltp": 100.0,
        "oi": 80,
        "volume": 40,
    }
    res_wide = audit_option_liquidity(quote_wide, underlying="RELIANCE")
    assert res_wide["slippage_guard_passed"] is False
    assert res_wide["liquidity_status"] == "WIDE_SPREAD_CAUTION"


# ── Pillar 4: Real-Time Options IV Skew Calculator ───────────────────────────


def test_compute_options_iv_skew():
    """Verify detection of Institutional Call Squeeze vs Downside Panic."""
    # Mock chain with Call IV >> Put IV (+2.5% spread) -> Institutional Call Squeeze
    chain_squeeze = [
        SimpleNamespace(strike=24500.0, option_type="CE", iv=16.5, last_price=120.0),
        SimpleNamespace(strike=24500.0, option_type="PE", iv=14.0, last_price=110.0),
        SimpleNamespace(strike=24600.0, option_type="CE", iv=17.0, last_price=60.0),
        SimpleNamespace(strike=24400.0, option_type="PE", iv=14.2, last_price=55.0),
    ]
    res_squeeze = compute_options_iv_skew(chain_squeeze, spot=24500.0, underlying="NIFTY")
    assert res_squeeze["status"] == "ACTIVE"
    assert res_squeeze["regime"] == "INSTITUTIONAL_CALL_SQUEEZE"
    assert res_squeeze["atm_skew"] == 2.5
    assert res_squeeze["is_call_skew_elevated"] is True
    assert res_squeeze["is_put_skew_elevated"] is False

    # Mock chain with Put IV >> Call IV (+4.0% spread) -> Downside Crash Panic
    chain_panic = [
        SimpleNamespace(strike=24500.0, option_type="CE", iv=13.0, last_price=90.0),
        SimpleNamespace(strike=24500.0, option_type="PE", iv=17.5, last_price=150.0),
        SimpleNamespace(strike=24600.0, option_type="CE", iv=13.2, last_price=40.0),
        SimpleNamespace(strike=24400.0, option_type="PE", iv=18.0, last_price=80.0),
    ]
    res_panic = compute_options_iv_skew(chain_panic, spot=24500.0, underlying="NIFTY")
    assert res_panic["regime"] == "DOWNSIDE_CRASH_PANIC"
    assert res_panic["atm_skew"] == -4.5
    assert res_panic["is_put_skew_elevated"] is True


# ── Pillar 5: Automated Short Strike "Roll or 80% Take-Profit" Engine ────────


def test_evaluate_short_strike_roll_plan_80_pct_decay():
    """Verify 80% short strike theta decay generates buy-to-close take-profit recommendation."""
    alert = SimpleNamespace(
        symbol="NIFTY",
        actionable_plan={
            "hedge_plan": {
                "buy_strike": 24500.0,
                "sell_strike": 24700.0,
                "strike_width": 200.0,
                "sentiment": "BULLISH",
                "legs": [
                    {"instrument": "NIFTY26OCT24500CE", "premium": 120.0},
                    {"instrument": "NIFTY26OCT24700CE", "premium": 50.0},
                ],
            }
        },
    )
    # Short leg sold at 50 is now trading at 8 (84% decay)
    chain_decay = [
        SimpleNamespace(strike=24700.0, option_type="CE", last_price=8.0),
    ]
    res = evaluate_short_strike_roll_plan(alert, current_spot=24550.0, chain=chain_decay)
    assert res["action"] == "BUY_BACK_SHORT_LEG_80_PCT_DECAY"
    assert res["decay_pct"] == 84.0
    assert "BUY TO CLOSE" in res["recommendation"]
    assert "running unhedged" in res["recommendation"]


def test_evaluate_short_strike_roll_plan_wall_approach():
    """Verify spot pressing within 25% of short strike generates ROLL_SHORT_STRIKE_OTM."""
    alert = SimpleNamespace(
        symbol="NIFTY",
        actionable_plan={
            "hedge_plan": {
                "buy_strike": 24500.0,
                "sell_strike": 24700.0,
                "strike_width": 200.0,
                "sentiment": "BULLISH",
                "legs": [
                    {"instrument": "NIFTY26OCT24500CE", "premium": 120.0},
                    {"instrument": "NIFTY26OCT24700CE", "premium": 50.0},
                ],
            }
        },
    )
    # Short strike is 24700, width is 200. 25% boundary is 24700 - 50 = 24650.
    # Spot is at 24680 (pressing directly into the short strike wall).
    res = evaluate_short_strike_roll_plan(alert, current_spot=24680.0)
    assert res["action"] == "ROLL_SHORT_STRIKE_OTM"
    assert res["candidate_roll_strike"] == 24750.0
    assert res["additional_runway_pts"] == 50.0
    assert "ROLL SHORT LEG" in res["recommendation"]


def test_evaluate_spread_in_flight_wires_roll_plan():
    """Verify evaluate_spread_in_flight populates roll_plan on SpreadEvaluationResult."""
    alert = SimpleNamespace(
        symbol="NIFTY",
        actionable_plan={
            "hedge_plan": {
                "buy_strike": 24500.0,
                "sell_strike": 24700.0,
                "net_debit_per_share": 70.0,
                "strike_width": 200.0,
                "sentiment": "BULLISH",
                "entry_spot": 24500.0,
                "booking_target_70": 160.0,
                "spread_stop_loss": 35.0,
                "legs": [
                    {"instrument": "NIFTY26OCT24500CE", "premium": 120.0},
                    {"instrument": "NIFTY26OCT24700CE", "premium": 50.0},
                ],
            }
        },
        achieved_milestones=[],
        environment="LIVE",
    )
    # Spot reaches short strike 24705 (touching wall)
    res = evaluate_spread_in_flight(alert, current_ltp=24705.0)
    assert res is not None
    assert res.triggered is True
    assert res.milestone_type == "SPREAD_SHORT_STRIKE_TOUCH"
    assert res.roll_plan is not None
    assert res.roll_plan["action"] == "ROLL_SHORT_STRIKE_OTM"


# ── Calibrations: Order Sequencing, Physical Settlement & Penny Trap ─────────


def test_get_optimal_expiry_stock_fno_physical_delivery():
    """Verify stock options get routed to NEXT_MONTHLY during SEBI physical delivery week."""
    from engine.options_hedging import get_optimal_expiry_recommendation

    # 2026-10-27 is Tuesday of monthly expiry week (last Thursday is 2026-10-29)
    settlement_tue = datetime(2026, 10, 27, 11, 0, tzinfo=IST)
    res_stock = get_optimal_expiry_recommendation("RELIANCE", now_dt=settlement_tue)
    assert res_stock["preferred_expiry"] == "NEXT_MONTHLY"
    assert res_stock["reason"] == "SEBI_PHYSICAL_SETTLEMENT_WEEK"
    assert "PHYSICAL SETTLEMENT" in res_stock["warning"]

    # Normal mid-month session (e.g. 2026-10-14) returns CURRENT_MONTHLY
    normal_dt = datetime(2026, 10, 14, 11, 0, tzinfo=IST)
    res_normal = get_optimal_expiry_recommendation("RELIANCE", now_dt=normal_dt)
    assert res_normal["preferred_expiry"] == "CURRENT_MONTHLY"
    assert res_normal["reason"] == "NORMAL_MONTHLY_CYCLE"


def test_execute_order_batch_buy_first_sequencing(tmp_path, monkeypatch):
    """Verify execute_order_batch strictly executes BUY orders before SELL orders to ensure margin relief."""
    from engine.order_lifecycle import (
        preview_order_intent,
        confirm_order_intent,
        execute_order_batch,
    )

    # Create sell order first, then buy order
    intent_sell = preview_order_intent(symbol="INFY", side="SELL", quantity=10, price=1800.0)
    intent_buy = preview_order_intent(symbol="INFY", side="BUY", quantity=10, price=1800.0)

    confirm_order_intent(intent_sell.order_id, intent_sell.preview_hash)
    confirm_order_intent(intent_buy.order_id, intent_buy.preview_hash)

    # Pass in [SELL, BUY] sequence
    results = execute_order_batch([intent_sell.order_id, intent_buy.order_id])
    assert len(results) == 2
    # Verify the executed order results place BUY first!
    assert results[0].order_id == intent_buy.order_id
    assert results[0].side == "BUY"
    assert results[1].order_id == intent_sell.order_id
    assert results[1].side == "SELL"
