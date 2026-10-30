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
            "THETA_STAGNATION_SCRATCH",
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
        from engine.learning_engine import pattern_learning_engine

        pattern_learning_engine.clear_symbol_lockout("WIPRO")
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
            is_live=False,
            environment="TEST",
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
            is_live=False,
            environment="TEST",
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
        # Restore a1, a2 is_live=True for live sector tracking
        a1.is_live = True
        a1.environment = "LIVE"
        a2.is_live = True
        a2.environment = "LIVE"

        from unittest.mock import patch
        from engine.alert_scrutiny import alert_scrutiny_auditor
        from types import SimpleNamespace

        mock_scrutiny = SimpleNamespace(
            status="PASSED",
            score=85,
            trap_risk_warning=None,
            rejection_reason=None,
            to_dict=lambda: {"status": "PASSED", "score": 85},
        )
        with patch.object(alert_scrutiny_auditor, "scrutinize_alert", return_value=mock_scrutiny):
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


# ─────────────────────────────────────────────────────────────────────────────
# Regression tests for Fix 2 (2026-10-30): hedge spread spot resolution bug
# Invariant: build_defined_risk_spread MUST produce realistic SENSEX-scale strikes
#            when primary_strike is provided; MUST NOT produce phantom 680/660 strikes
#            when the option premium (~660) was mistakenly used as spot_price.
# ─────────────────────────────────────────────────────────────────────────────


class TestHedgeSpreadSpotResolutionRegression:
    """
    Regression guard: SMT_SWEEP SENSEX alert with underlying_spot=None but
    metrics.spot_at_sweep=74132 MUST produce a hedge spread with strikes > 70000.

    Background (RCA 2026-10-30):
        alert.underlying_spot was None for SMT_SWEEP alerts.
        auto_alert_engine fell back to alert.ltp = 660.35 (option premium).
        build_defined_risk_spread received spot_price=660 -> atm_strike=660 ->
        built a phantom 680/660 PE spread completely disconnected from reality.
    """

    def test_bear_put_spread_anchors_to_primary_strike(self):
        """
        When primary_strike is provided, buy_strike must equal primary_strike.
        The sell_strike must be 2 steps below (for SENSEX: 2 * 100 = 200 below).
        BS premiums for SENSEX-scale strikes must be > 0.
        """
        from engine.defined_risk_spreads import build_defined_risk_spread

        spread = build_defined_risk_spread(
            underlying="SENSEX",
            spot_price=74132.0,  # correct index spot
            strategy="BEAR_PUT_SPREAD",
            primary_strike=74200.0,  # alert's actual option strike
            primary_premium=593.8,  # alert's actual market premium
        )

        assert spread is not None, "Spread must be constructed"
        legs = spread.legs
        buy_leg = next((l for l in legs if l.side == "BUY"), None)
        sell_leg = next((l for l in legs if l.side == "SELL"), None)

        assert buy_leg is not None, "Must have a BUY leg"
        assert sell_leg is not None, "Must have a SELL leg"

        # Strike sanity: both must be SENSEX-scale (> 70000), not option-premium-scale
        assert buy_leg.strike > 70000, (
            f"Buy strike {buy_leg.strike} is not SENSEX-scale — "
            f"spot proxy contamination detected (phantom 680 PE bug)"
        )
        assert sell_leg.strike > 70000, (
            f"Sell strike {sell_leg.strike} is not SENSEX-scale — phantom 660 PE bug detected"
        )

        # Buy leg must be anchored to the provided primary_strike
        assert buy_leg.strike == 74200.0, (
            f"Expected buy_strike=74200 (alert's actual strike), got {buy_leg.strike}"
        )

        # Buy leg premium must equal primary_premium (real market value, not BS estimate)
        assert buy_leg.premium == 593.8, (
            f"Expected buy_prem=593.8 (from alert.entry_price), got {buy_leg.premium}"
        )

        # Sell strike must be below buy strike by exactly 2 steps (SENSEX step=100)
        assert buy_leg.strike - sell_leg.strike == 200.0, (
            f"Strike width should be 2*100=200, got {buy_leg.strike - sell_leg.strike}"
        )

        # Sell premium must be a plausible BS value (not 0 or > buy_prem)
        assert 0 < sell_leg.premium < 593.8, f"Sell leg premium {sell_leg.premium} out of bounds"

    def test_bear_put_spread_phantom_strike_regression(self):
        """
        When spot_price is the OPTION PREMIUM (bug: ~660) instead of actual SENSEX (~74132),
        WITHOUT primary_strike anchor, the resulting ATM strike is ~660 (phantom).
        This test documents the old broken behavior and asserts the fix works:
        now the spot guard (spot_p < 1000) in auto_alert_engine prevents this call
        from ever reaching build_defined_risk_spread.

        Here we test build_defined_risk_spread directly to confirm that the function
        CAN still handle it (it has no guard itself — the guard is upstream), and that
        with primary_strike provided, the result is anchored regardless of spot_price.
        """
        from engine.defined_risk_spreads import build_defined_risk_spread

        # Old broken call — spot_price is option LTP, no primary_strike
        broken_spread = build_defined_risk_spread(
            underlying="SENSEX",
            spot_price=660.35,  # was alert.ltp — option premium, NOT index spot
            strategy="BEAR_PUT_SPREAD",
            # no primary_strike → falls back to atm computed from 660 = phantom 660
        )
        buy_leg_broken = next((l for l in broken_spread.legs if l.side == "BUY"), None)
        # Confirm the phantom strike is indeed low (this is the OLD broken result)
        assert buy_leg_broken.strike < 1000, (
            "Old phantom behavior expected: strike should be ~660 without fix"
        )

        # Fixed call — spot_price is real, primary_strike is the alert's actual strike
        fixed_spread = build_defined_risk_spread(
            underlying="SENSEX",
            spot_price=74132.0,
            strategy="BEAR_PUT_SPREAD",
            primary_strike=74200.0,
            primary_premium=593.8,
        )
        buy_leg_fixed = next((l for l in fixed_spread.legs if l.side == "BUY"), None)
        assert buy_leg_fixed.strike > 70000, (
            f"Fixed call must produce SENSEX-scale strikes, got {buy_leg_fixed.strike}"
        )

    def test_to_dict_exposes_net_debit_per_unit(self):
        """
        DefinedRiskSpread.to_dict() must include net_debit_per_unit for correct
        frontend per-contract display. Previously only net_cashflow (lot-level) was exposed,
        causing the '/ share' label to show the lot-total value.
        """
        from engine.defined_risk_spreads import build_defined_risk_spread

        spread = build_defined_risk_spread(
            underlying="SENSEX",
            spot_price=74132.0,
            strategy="BEAR_PUT_SPREAD",
            primary_strike=74200.0,
            primary_premium=593.8,
            lot_size=20,
        )
        d = spread.to_dict()

        assert "net_debit_per_unit" in d, (
            "to_dict() must expose net_debit_per_unit for frontend per-contract display"
        )
        lot_sz = d["lot_size"]
        expected_per_unit = round(d["net_cashflow"] / max(1, lot_sz), 2)
        assert d["net_debit_per_unit"] == expected_per_unit, (
            f"net_debit_per_unit mismatch: got {d['net_debit_per_unit']}, "
            f"expected {expected_per_unit} (cashflow={d['net_cashflow']}/lot={lot_sz})"
        )

        # Per-unit value must be dramatically smaller than lot-level cashflow
        assert d["net_debit_per_unit"] < d["net_cashflow"], (
            "Per-unit debit must be < lot-level cashflow (lot_size > 1)"
        )

    def test_spot_guard_skips_spread_when_spot_too_low(self):
        """
        Validate the guard logic: spot_p < 1000 must not produce a realistic spread.
        The function itself has no guard (guard is in auto_alert_engine), but this
        test verifies the output would be obviously wrong — confirming why the upstream
        guard is necessary and must not be removed.
        """
        from engine.defined_risk_spreads import build_defined_risk_spread

        # Simulate the old bug: ltp=660 used as spot
        phantom = build_defined_risk_spread(
            underlying="SENSEX",
            spot_price=660.0,
            strategy="BEAR_PUT_SPREAD",
        )
        d = phantom.to_dict()
        buy_leg = next((l for l in phantom.legs if l.side == "BUY"), None)

        # Document: strikes are phantom low — this is WRONG output
        assert buy_leg.strike < 1000, "Expected phantom low strike from wrong spot"
        # And the net_cashflow is unrealistically small
        assert abs(d["net_cashflow"]) < 500, (
            "Expected tiny cashflow from phantom strike — confirms guard is needed upstream"
        )

    def test_bull_call_spread_unaffected_by_primary_strike_none(self):
        """
        Existing BULL_CALL_SPREAD path with no primary_strike must still work
        correctly (no regression in CE paths).
        """
        from engine.defined_risk_spreads import build_defined_risk_spread

        spread = build_defined_risk_spread(
            underlying="NIFTY",
            spot_price=24500.0,
            strategy="BULL_CALL_SPREAD",
            # primary_strike=None (default) — uses ATM from spot
        )
        assert spread is not None
        d = spread.to_dict()
        assert d["strategy_name"] == "BULL_CALL_SPREAD"
        assert d["sentiment"] == "BULLISH"
        assert "net_debit_per_unit" in d

        buy_leg = next((l for l in spread.legs if l.side == "BUY"), None)
        # ATM should be near 24500 (NIFTY step=50 for 15k-30k range)
        assert 24400 <= buy_leg.strike <= 24600
