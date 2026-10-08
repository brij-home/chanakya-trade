"""
tests/test_hedged_spread_and_concurrency.py
─────────────────────────────────────────────
Comprehensive tests for Institutional Hedging, Defined-Risk Spreads,
Session Trap Memory, and Sector Concurrency Caps.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from engine.alert_evaluator import (
    evaluate_alert_in_flight_decay,
    evaluate_alert_targets_and_trailing,
)
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from engine.learning_engine import pattern_learning_engine
from engine.trade_plan import calculate_option_execution_plan

IST = timezone(timedelta(hours=5, minutes=30))


class TestHedgedSpreadPlanning:
    """Tests defined-risk hedge blueprint generation in trade planning."""

    def test_calculate_option_execution_plan_includes_hedged_spread(self):
        """Verify calculate_option_execution_plan dynamically attaches defined-risk spread."""
        from engine.trade_plan import calculate_trade_plan

        base_plan = calculate_trade_plan(
            symbol="NIFTY",
            direction="BULLISH",
            spot=24500.0,
            timeframe="INTRADAY",
        )
        plan = calculate_option_execution_plan(
            trade_plan=base_plan,
            option_type="CE",
            strike=24500.0,
            expiry=datetime.now(IST).strftime("%Y-%m-%d"),
            option_ltp=120.0,
            lot_size=25,
            expiry_type="WEEKLY",
        )
        assert plan is not None
        assert "hedged_spread" in plan
        spread = plan["hedged_spread"]
        assert spread is not None
        assert spread["spread_name"] == "Bull Call Spread"
        assert spread["structure"] == "VERTICAL_DEBIT_SPREAD"
        assert spread["long_leg"]["strike"] == 24500.0
        assert spread["short_leg"]["strike"] > 24500.0
        assert spread["net_debit"] > 0
        assert spread["theta_reduction_pct"] == 75.0
        assert spread["max_risk_pts"] > 0
        assert spread["max_profit_pts"] > 0
        assert "1:" in spread["spread_rr"]

    def test_in_flight_decay_attaches_hedge_defense_plan(self):
        """Verify in-flight theta decay attaches hedge defense plan when spot holds support."""
        now_dt = datetime.now(IST)
        twenty_mins_ago = (now_dt - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S IST")
        alert = AutoAlert(
            alert_id="test-hedge-decay-1",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty Call Scalp",
            summary="Testing theta decay defense",
            trigger_level=120.0,
            target_level=190.0,
            stop_loss=80.0,
            ltp=114.0,  # -5% pnl
            option_premium=120.0,
            option_type="CE",
            strike=24500,
            contract_symbol="NIFTY2691724500CE",
            underlying_spot=24510.0,  # spot is holding above 24500 support
            created_at=twenty_mins_ago,
            original_call_time=twenty_mins_ago,
            is_live=True,
            environment="LIVE",
            actionable_plan={
                "action": "BUY",
                "instrument": "NIFTY2691724500CE",
                "recommended_entry": "₹120.0",
                "stop_loss": "₹80.0",
            },
        )
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=114.0)
        assert eval_res is not None
        assert eval_res.triggered is True
        assert eval_res.warning_type in (
            "THETA_STAGNATION",
            "0DTE_INTRADAY_DECAY",
            "0DTE_AFTERNOON_THETA_CLIFF",
        )
        assert eval_res.hedge_plan is not None
        assert eval_res.hedge_plan["action"] == "SELL_OTM_HEDGE"
        assert "HEDGE DEFENSE" in eval_res.summary


class TestSessionTrapPivotMemory:
    """Tests session trap memory and avoidance of repeat breakout traps."""

    def test_record_and_detect_session_trap_pivot(self):
        """Verify failed breakout pivot is stored and flagged on subsequent setups."""
        sym = "TRENT_TEST"
        pivot = 5400.0
        pattern_learning_engine.record_session_trap_pivot(
            symbol=sym,
            pivot_price=pivot,
            direction="BULLISH",
            trap_type="BULL_TRAP",
            note="Failed morning high breakout",
        )

        # Price near pivot (5410 is +0.18% from 5400, within 0.6% threshold)
        is_near, trap = pattern_learning_engine.is_near_session_trap_pivot(
            sym, current_price=5410.0
        )
        assert is_near is True
        assert trap is not None
        assert trap["pivot_price"] == 5400.0
        assert trap["trap_type"] == "BULL_TRAP"

        # Price far from pivot (5550 is +2.7% away)
        is_near_far, _ = pattern_learning_engine.is_near_session_trap_pivot(
            sym, current_price=5550.0
        )
        assert is_near_far is False


class TestDynamicATRTrailing:
    """Tests 1.5x ATR dynamic runner trailing stops."""

    def test_atr_trailing_stop_uses_dynamic_buffer(self):
        """Verify trailing ratchet scales by 1.5x ATR when available."""
        alert = AutoAlert(
            alert_id="test-trail-atr-1",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="TRAILING_UPDATE",
            symbol="INFY",
            exchange="NSE",
            direction="BULLISH",
            headline="Infosys Breakout",
            summary="Runner trailing test",
            trigger_level=1800.0,
            target_level=1900.0,
            stop_loss=1780.0,
            trailing_stop=1810.0,
            should_trail=True,
            ltp=1850.0,
            confidence=85,
            metrics={"atr": 10.0},  # ATR = 10 -> 1.5 * 10 = 15.0 pts trail buffer
            actionable_plan={"recommended_entry": "1800.0", "stop_loss": "1780.0"},
            target_status="T1_ACHIEVED",
        )
        res = evaluate_alert_targets_and_trailing(alert, current_ltp=1850.0)
        assert res is not None
        assert res.should_trail is True
        assert res.trailing_decision == "TRAIL_DYNAMIC_ATR"
        # current_ltp (1850) - 1.5 * 10 (15) = 1835.0
        assert res.recommended_stop == 1835.0


class TestSectorConcurrencyAndTelegramCard:
    """Tests sector concurrency caps and Telegram hedge formatting."""

    def test_sector_concurrency_cap_attaches_hedged_spread_mandate(self):
        """Verify that when 2 active trades exist in IT sector, 3rd trade gets tagged with hedged spread mandate."""
        engine = AutoAlertEngine()
        # Seed 2 active IT alerts
        a1 = AutoAlert(
            alert_id="it-act-1",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            symbol="INFY",
            exchange="NSE",
            direction="BULLISH",
            headline="Infosys Long",
            summary="IT active 1",
            trigger_level=1800.0,
            target_level=1900.0,
            stop_loss=1780.0,
            ltp=1810.0,
            confidence=85,
            metrics={"sector_id": "it"},
            is_live=True,
            environment="LIVE",
        )
        a2 = AutoAlert(
            alert_id="it-act-2",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            symbol="TCS",
            exchange="NSE",
            direction="BULLISH",
            headline="TCS Long",
            summary="IT active 2",
            trigger_level=4200.0,
            target_level=4400.0,
            stop_loss=4150.0,
            ltp=4220.0,
            confidence=86,
            metrics={"sector_id": "it"},
            is_live=True,
            environment="LIVE",
        )
        engine._alerts = [a1, a2]

        # 3rd incoming IT alert (WIPRO)
        a3 = AutoAlert(
            alert_id="it-incoming-3",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            symbol="WIPRO",
            exchange="NSE",
            direction="BULLISH",
            headline="Wipro Breakout",
            summary="IT incoming 3",
            trigger_level=550.0,
            target_level=580.0,
            stop_loss=540.0,
            ltp=552.0,
            confidence=84,
            metrics={},
            actionable_plan={"recommended_entry": "550.0", "stop_loss": "540.0"},
            is_live=True,
            environment="LIVE",
        )
        recorded = engine.record_alert(a3)
        assert recorded is True
        assert a3.metrics.get("sector_cluster_cap_reached") is True
        assert a3.actionable_plan.get("execution_style_mandate") == "HEDGED_SPREAD_MANDATORY"
        assert "Sector cluster limit reached" in a3.actionable_plan.get(
            "sector_concurrency_warning", ""
        )

    def test_telegram_renders_in_flight_hedge_defense_card(self):
        """Verify Telegram template renders HEDGE DEFENSE card during in-flight theta decay."""
        from bot.alert_templates import render_auto_alert

        alert = AutoAlert(
            alert_id="tg-hedge-test-1",
            alert_type="OPTIONS_MOMENTUM",
            stage="IN_FLIGHT_WARNING",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty Call Option Warning",
            summary="Theta decay warning test",
            trigger_level=120.0,
            target_level=190.0,
            stop_loss=80.0,
            ltp=112.0,
            option_premium=120.0,
            option_type="CE",
            strike=24500,
            contract_symbol="NIFTY 24500 CE",
            in_flight_warning_sent=True,
            in_flight_warning_reason="THETA STAGNATION: 18m elapsed without momentum.",
            trailing_decision="EXIT_STAGNANT_OPTION",
            metrics={
                "in_flight_hedge_plan": {
                    "action": "SELL_OTM_HEDGE",
                    "short_symbol": "NIFTY 24600 CE",
                    "short_premium_est": 45.0,
                    "net_risk_pts": 67.0,
                    "theta_reduction_pct": 75.0,
                }
            },
            is_live=True,
            environment="LIVE",
        )
        msg = render_auto_alert(alert, in_market=True)
        assert "THETA DECAY WARNING" in msg
        assert "HEDGE DEFENSE (Shift to Spread)" in msg
        assert "NIFTY 24600 CE" in msg
        assert "-75%" in msg
        assert "Risk Frozen" in msg
