"""
tests/test_dead_money_ratchet.py
─────────────────────────────────
Unit tests for the 60-Minute "Dead-Money" Dynamic Ratchet Invariant:
1. Directional option buyers / equity breakouts stalling for >= 60 minutes with modest profit (>= +0.35R)
   ratchet SL to Breakeven (+0.2% fee cushion) to eliminate ruin risk.
2. Non-directional theta harvesters (DEFINED_RISK_NEUTRAL, IRON_CONDOR, option sellers) are strictly EXEMPTED.
3. Positions open < 60 minutes do not trigger premature breakeven ratchet.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.alert_evaluator import evaluate_alert_targets_and_trailing
from engine.alert_model import AutoAlert
from engine.lifecycle.trade_lifecycle_manager import TradeLifecycleManager

IST = ZoneInfo("Asia/Kolkata")


def test_dead_money_ratchet_triggers_at_60_mins():
    """Verify that a directional trade stagnant for >= 60 mins with >= 0.35R ratchets SL to Breakeven."""
    now_dt = datetime.now(IST)
    created_dt = now_dt - timedelta(minutes=65)
    created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="aa-orb-infy-20261114",
        alert_type="ORB",
        symbol="INFY",
        exchange="NSE",
        direction="BULLISH",
        stage="IGNITED",
        headline="INFY Breakout",
        summary="INFY ORB setup",
        ltp=1520.0,
        trigger_level=1500.0,
        stop_loss=1460.0,  # 40 pts initial risk (1.0R)
        target_level=1580.0,  # +2.0R target
        created_at=created_str,
        triggered_at=created_str,
        actionable_plan={"target_1": 1580.0, "entry_price": 1500.0},
    )

    # Current LTP = 1518 (+18 pts = +0.45R, +1.2% PnL)
    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=1518.0)

    assert eval_res is not None
    assert eval_res.new_milestone == "DEAD_MONEY_BREAKEVEN"
    assert eval_res.trailing_decision == "TRAIL_DEAD_MONEY_BREAKEVEN"
    # Breakeven with +0.2% fee cushion = 1500 * 1.002 = 1503.0
    assert eval_res.recommended_stop == 1503.0
    assert eval_res.is_risk_compression is True
    assert eval_res.risk_reduction_pct == 100.0

    # Apply milestone via lifecycle manager
    tlm = TradeLifecycleManager()
    now_ts = now_dt.timestamp()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    tlm.apply_milestone_state(alert, eval_res, cur_quote_ltp=1518.0, now_ts=now_ts, now_str=now_str)

    assert alert.stop_loss == 1503.0
    assert alert.trailing_stop == 1503.0
    assert alert.is_breakeven_ratcheted is True
    assert "DEAD_MONEY_BREAKEVEN" in alert.achieved_milestones
    assert alert.stage == "BREAKEVEN_LOCKED"
    assert "DEAD-MONEY RATCHET" in alert.headline


def test_dead_money_ratchet_exempts_non_directional_sellers():
    """Verify that non-directional option sellers & defined-risk neutral spreads are strictly exempt."""
    now_dt = datetime.now(IST)
    created_dt = now_dt - timedelta(minutes=75)
    created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="aa-condor-nifty-20261114",
        alert_type="DEFINED_RISK_NEUTRAL",
        symbol="NIFTY",
        exchange="NFO",
        direction="NEUTRAL",
        stage="ACTIONABLE",
        headline="NIFTY Condor",
        summary="NIFTY neutral condor",
        ltp=24200.0,
        trigger_level=24200.0,
        stop_loss=23950.0,
        target_level=24450.0,
        created_at=created_str,
        triggered_at=created_str,
        metrics={"strategy": "IRON_CONDOR"},
        actionable_plan={"strategy_type": "IRON_CONDOR", "action": "EXECUTE_IRON_CONDOR"},
    )

    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=24220.0)

    # Must NOT trigger DEAD_MONEY_BREAKEVEN
    if eval_res is not None:
        assert eval_res.new_milestone != "DEAD_MONEY_BREAKEVEN"


def test_dead_money_ratchet_does_not_fire_prematurely():
    """Verify that trades open for less than 60 minutes do not trigger time ratchet."""
    now_dt = datetime.now(IST)
    created_dt = now_dt - timedelta(minutes=35)  # only 35 minutes
    created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S IST")

    alert = AutoAlert(
        alert_id="aa-orb-tcs-20261114",
        alert_type="ORB",
        symbol="TCS",
        exchange="NSE",
        direction="BULLISH",
        stage="IGNITED",
        headline="TCS ORB",
        summary="TCS breakout setup",
        ltp=4150.0,
        trigger_level=4100.0,
        stop_loss=4020.0,  # 80 pts initial risk
        target_level=4260.0,
        created_at=created_str,
        triggered_at=created_str,
        actionable_plan={"target_1": 4260.0, "entry_price": 4100.0},
    )

    # Current LTP = 4136 (+36 pts = +0.45R)
    eval_res = evaluate_alert_targets_and_trailing(alert, current_ltp=4136.0)

    if eval_res is not None:
        assert eval_res.new_milestone != "DEAD_MONEY_BREAKEVEN"
