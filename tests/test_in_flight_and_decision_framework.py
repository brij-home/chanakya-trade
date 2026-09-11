"""
tests/test_in_flight_and_decision_framework.py
────────────────────────────────────────────────
Comprehensive test suite verifying:
  1. Decision Making Framework:
     - Rule 10: Multi-Timeframe (MTF) 15m Trend Alignment Gate.
     - Options Delta OI Confirmation & Call Writing Resistance Wall trap prevention.
     - Dynamic India VIX Regime Scaling & Tail-Risk naked option buying veto.
  2. Alert Messaging System:
     - Proactive Danger Zone In-Flight Warning (>= 70% risk budget eroded / <= 1.5% from SL).
     - Theta Decay Stagnation Warning (>= 15m elapsed without upside progress).
     - Strict One-Shot Latching (zero duplicate warnings/spam).
     - Standardized Telegram templates with actionable coaching friction.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from engine.alert_model import AutoAlert
from engine.alert_evaluator import (
    evaluate_alert_in_flight_decay,
    InFlightWarningEvaluation,
)
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.auto_alert_engine import AutoAlertEngine
from engine.position_sizer import calculate_position_size, PositionSizeResult
from bot.alert_templates import (
    render_auto_alert,
    render_in_flight_warning_alert,
    render_milestone_alert,
    MilestoneAlertData,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_engine():
    engine = AutoAlertEngine(max_buffer=50)
    engine.clear_alerts()
    return engine


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor(min_rr_ratio=1.5, max_intraday_risk_pct=8.0)


# ── Decision Making Framework Tests ──────────────────────────────────────────

class TestDecisionMakingFramework:
    def test_mtf_15m_trend_alignment_gate_rejects_counter_trend(self, auditor):
        """Rule 10: 5m Bullish setup conflicting with 15m structural downtrend must be rejected."""
        alert = AutoAlert(
            alert_id="test-mtf-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="MTF_TEST_STOCK",
            exchange="NSE",
            direction="BULLISH",
            headline="MTF Test Squeeze Breakout",
            summary="Testing MTF 15m confluence",
            ltp=1500.0,
            trigger_level=1500.0,
            stop_loss=1480.0,
            target_level=1550.0,
            confidence=85,
            metrics={"mtf_15m_trend": "BEARISH_DOWNTREND"},  # Direct conflict!
        )
        with patch("engine.learning_engine.pattern_learning_engine.is_symbol_locked_out", return_value=(False, "")):
            passed, reason, flags = auditor.verify_tier1_sanity(alert)
            assert not passed, "Counter-trend trade should be rejected by MTF 15m alignment gate"
            assert "MTF Confluence Failure" in reason

    def test_mtf_15m_trend_alignment_gate_passes_confluent_trend(self, auditor):
        """Rule 10: 5m Bullish setup aligning with 15m structural uptrend must pass."""
        alert = AutoAlert(
            alert_id="test-mtf-2",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="TCS",
            exchange="NSE",
            direction="BULLISH",
            headline="TCS Confluent Breakout",
            summary="Aligned with 15m trend",
            ltp=4000.0,
            trigger_level=4000.0,
            stop_loss=3950.0,
            target_level=4120.0,
            confidence=88,
            metrics={"mtf_15m_trend": "BULLISH_UPTREND"},
        )
        passed, reason, flags = auditor.verify_tier1_sanity(alert)
        assert passed is True
        assert reason == ""

    def test_india_vix_regime_adaptation_scales_rr_and_vetoes_tail_risk(self, auditor):
        """Extreme VIX (> 25.0) vetoes naked option buying; Elevated VIX (> 18.0) demands strict >= 1:2.0 R:R."""
        # Scenario A: Elevated VIX with weak 1:1.4 R:R -> Rejected
        with patch("market.indices.get_vix", return_value={"ltp": 20.5}):
            alert_weak_rr = AutoAlert(
                alert_id="test-vix-1",
                alert_type="PRECURSOR_RADAR",
                stage="EARLY_WARNING",
                symbol="NIFTY",
                exchange="NSE",
                direction="BULLISH",
                headline="Nifty Weak RR Setup",
                summary="Elevated VIX requires 1:2.0 RR",
                ltp=24000.0,
                trigger_level=24000.0,
                stop_loss=23900.0,     # Risk = 100
                target_level=24140.0,  # Reward = 140 -> R:R = 1:1.4 (Fails requirement of 1:2.0 at VIX 20.5)
                confidence=85,
            )
            passed, reason, flags = auditor.verify_tier1_sanity(alert_weak_rr)
            assert not passed
            assert "Unfavorable Risk:Reward ratio" in reason

        # Scenario B: Extreme VIX (> 25.0) with naked option buying -> Vetoed
        with patch("market.indices.get_vix", return_value={"ltp": 26.5}):
            alert_naked_opt = AutoAlert(
                alert_id="test-vix-2",
                alert_type="OPTIONS_MOMENTUM",
                stage="IGNITED",
                symbol="NIFTY",
                exchange="NFO",
                direction="BULLISH",
                headline="Nifty Call Option Buy",
                summary="Naked option buying during extreme turbulence",
                ltp=120.0,
                trigger_level=120.0,
                option_premium=120.0,
                stop_loss=90.0,
                target_level=220.0,
                strike=24500,
                option_type="CE",
                actionable_plan={"action": "BUY"},
                confidence=90,
            )
            passed2, reason2, flags2 = auditor.verify_tier1_sanity(alert_naked_opt)
            assert not passed2
            assert "VIX Tail Risk Veto" in reason2
            assert "IV crush" in reason2

    def test_position_sizer_adaptive_vix_scaling(self):
        """calculate_position_size scales down risk budget when India VIX is elevated or extreme."""
        base_res = calculate_position_size(
            symbol="RELIANCE",
            entry_price=2800.0,
            stop_loss=2750.0,
            capital=100000.0,
            max_risk_pct=1.5,  # 1500 risk budget
            sizing_model="fixed_fractional",
            vix=14.0,  # Normal VIX
        )
        assert base_res.risk_pct <= 1.5

        # Elevated VIX (20.0) -> 30% reduction (effective risk ~1.05%)
        elevated_res = calculate_position_size(
            symbol="RELIANCE",
            entry_price=2800.0,
            stop_loss=2750.0,
            capital=100000.0,
            max_risk_pct=1.5,
            sizing_model="fixed_fractional",
            vix=20.0,
        )
        assert elevated_res.risk_pct <= 1.10
        assert "ELEVATED: Risk scaled down 30%" in elevated_res.notes

        # Extreme VIX (26.0) -> 50% reduction (effective risk ~0.75%)
        extreme_res = calculate_position_size(
            symbol="RELIANCE",
            entry_price=2800.0,
            stop_loss=2750.0,
            capital=100000.0,
            max_risk_pct=1.5,
            sizing_model="fixed_fractional",
            vix=26.0,
        )
        assert extreme_res.risk_pct <= 0.80
        assert "EXTREME: Risk scaled down 50%" in extreme_res.notes


# ── In-Flight Decay & Danger Zone Warning Tests ──────────────────────────────

class TestInFlightDecayAlerts:
    def test_danger_zone_triggers_when_70pct_risk_consumed(self):
        """When price erodes >= 70% of initial risk budget, evaluate_alert_in_flight_decay triggers DANGER_ZONE."""
        alert = AutoAlert(
            alert_id="danger-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="TRENT",
            exchange="NSE",
            direction="BULLISH",
            headline="Trent Long Breakout",
            summary="Monitoring in-flight decay",
            ltp=7000.0,
            trigger_level=7000.0,
            stop_loss=6900.0,  # Total initial risk = 100 pts
            target_level=7300.0,
            confidence=85,
        )
        # At LTP 6925, 75 pts consumed out of 100 (75% risk budget eroded)
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=6925.0)
        assert eval_res is not None
        assert eval_res.triggered
        assert eval_res.warning_type == "DANGER_ZONE"
        assert eval_res.coaching_decision == "SCRATCH_OR_TIGHTEN_STOP"
        assert "75% of risk budget is eroded" in eval_res.summary
        assert "SCRATCH POSITION AT MARKET" in eval_res.summary

    def test_danger_zone_triggers_when_within_1_5_percent_of_sl(self):
        """When price is within 1.5% of Stop-Loss, evaluate_alert_in_flight_decay triggers DANGER_ZONE."""
        alert = AutoAlert(
            alert_id="danger-2",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="HDFCBANK",
            exchange="NSE",
            direction="BULLISH",
            headline="HDFC Bank Setup",
            summary="Checking proximity to SL",
            ltp=1650.0,
            trigger_level=1650.0,
            stop_loss=1630.0,
            target_level=1720.0,
            confidence=88,
        )
        # LTP 1640 is 10 pts above SL 1630 -> (1640 - 1630) / 1640 = 0.61% away from SL!
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=1640.0)
        assert eval_res is not None
        assert eval_res.triggered
        assert eval_res.warning_type == "DANGER_ZONE"
        assert eval_res.current_ltp == 1640.0

    def test_theta_decay_stagnation_triggers_after_15m_with_no_progress(self):
        """Option position open for >= 15 minutes with P&L <= 0% triggers THETA_STAGNATION."""
        now_dt = datetime.now(IST)
        twenty_mins_ago = (now_dt - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S IST")

        alert = AutoAlert(
            alert_id="theta-1",
            alert_type="OPTIONS_MOMENTUM_BREAKOUT",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty Call Option Breakout",
            summary="Theta stagnation tracking",
            ltp=100.0,
            trigger_level=100.0,
            option_premium=100.0,
            stop_loss=70.0,
            target_level=160.0,
            option_type="CE",
            strike=24200,
            contract_symbol="NIFTY 24200 CE",
            created_at=twenty_mins_ago,
            original_call_time=twenty_mins_ago,
            confidence=88,
        )
        # Option bought at 100 is now trading at 96 after 20 mins (-4% P&L)
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=96.0)
        assert eval_res is not None
        assert eval_res.triggered
        assert eval_res.warning_type == "THETA_STAGNATION"
        assert eval_res.coaching_decision == "EXIT_STAGNANT_OPTION"
        assert "Theta Stagnation: 20m No Progress" in eval_res.headline
        assert "SCRATCH / EXIT AT MARKET" in eval_res.summary

    def test_0dte_afternoon_theta_cliff_8min_threshold(self):
        """0DTE option post-13:30 IST compresses stagnation threshold to 8m (480s)."""
        thursday_afternoon = datetime(2026, 9, 10, 14, 0, 0, tzinfo=IST)
        with patch("engine.alert_evaluator.datetime") as mock_dt:
            mock_dt.now.return_value = thursday_afternoon
            mock_dt.strptime.side_effect = datetime.strptime

            # 9 minutes elapsed (540s > 480s) -> MUST trigger 0DTE_AFTERNOON_THETA_CLIFF
            alert_9m = AutoAlert(
                alert_id="0dte-cliff-1",
                alert_type="OPTIONS_MOMENTUM_BREAKOUT",
                stage="IGNITED",
                symbol="NIFTY",  # Thursday expiry = 0DTE
                exchange="NFO",
                direction="BULLISH",
                headline="Nifty 0DTE Call",
                summary="0DTE testing",
                trigger_level=100.0,
                target_level=160.0,
                ltp=95.0,
                option_premium=100.0,
                stop_loss=70.0,
                option_type="CE",
                strike=24200,
                created_at="2026-09-10 13:51:00",
                is_live=True,
            )
            eval_res = evaluate_alert_in_flight_decay(alert_9m, current_ltp=95.0)
            assert eval_res is not None
            assert eval_res.triggered is True
            assert eval_res.warning_type == "0DTE_AFTERNOON_THETA_CLIFF"
            assert eval_res.coaching_decision == "EXIT_0DTE_OPTION_IMMEDIATELY"
            assert "0DTE Theta Cliff: 9m No Progress" in eval_res.headline
            assert "PIN-RISK PREMIUM EVAPORATION" in eval_res.summary

            # 6 minutes elapsed (360s < 480s) -> Under threshold, must NOT trigger
            alert_6m = AutoAlert(
                alert_id="0dte-cliff-2",
                alert_type="OPTIONS_MOMENTUM_BREAKOUT",
                stage="IGNITED",
                symbol="NIFTY",
                exchange="NFO",
                direction="BULLISH",
                headline="Nifty 0DTE Call",
                summary="0DTE testing",
                trigger_level=100.0,
                target_level=160.0,
                ltp=95.0,
                option_premium=100.0,
                stop_loss=70.0,
                option_type="CE",
                strike=24200,
                created_at="2026-09-10 13:54:00",
                is_live=True,
            )
            eval_res_6m = evaluate_alert_in_flight_decay(alert_6m, current_ltp=95.0)
            assert eval_res_6m is None

    def test_0dte_morning_decay_10min_threshold(self):
        """0DTE option morning session compresses stagnation threshold to 10m (600s)."""
        thursday_morning = datetime(2026, 9, 10, 10, 30, 0, tzinfo=IST)
        with patch("engine.alert_evaluator.datetime") as mock_dt:
            mock_dt.now.return_value = thursday_morning
            mock_dt.strptime.side_effect = datetime.strptime

            # 11 minutes elapsed (660s > 600s) -> MUST trigger 0DTE_INTRADAY_DECAY
            alert_11m = AutoAlert(
                alert_id="0dte-morning-1",
                alert_type="OPTIONS_MOMENTUM_BREAKOUT",
                stage="IGNITED",
                symbol="NIFTY",
                exchange="NFO",
                direction="BULLISH",
                headline="Nifty 0DTE Morning Call",
                summary="0DTE testing",
                trigger_level=100.0,
                target_level=160.0,
                ltp=96.0,
                option_premium=100.0,
                stop_loss=70.0,
                option_type="CE",
                strike=24200,
                created_at="2026-09-10 10:19:00",
                is_live=True,
            )
            eval_res = evaluate_alert_in_flight_decay(alert_11m, current_ltp=96.0)
            assert eval_res is not None
            assert eval_res.triggered is True
            assert eval_res.warning_type == "0DTE_INTRADAY_DECAY"
            assert eval_res.coaching_decision == "EXIT_0DTE_STAGNANT_OPTION"
            assert "0DTE Decay: 11m No Progress" in eval_res.headline

            # Non-0DTE alert (e.g. Friday for Nifty) at 11m -> Standard 15m threshold -> Must NOT trigger
            friday_morning = datetime(2026, 9, 11, 10, 30, 0, tzinfo=IST)
            mock_dt.now.return_value = friday_morning
            alert_weekly = AutoAlert(
                alert_id="weekly-opt-1",
                alert_type="OPTIONS_MOMENTUM_BREAKOUT",
                stage="IGNITED",
                symbol="NIFTY",
                exchange="NFO",
                direction="BULLISH",
                headline="Nifty Weekly Call",
                summary="Weekly testing",
                trigger_level=100.0,
                target_level=160.0,
                ltp=96.0,
                option_premium=100.0,
                stop_loss=70.0,
                option_type="CE",
                strike=24200,
                created_at="2026-09-11 10:19:00",
                is_live=True,
            )
            eval_res_weekly = evaluate_alert_in_flight_decay(alert_weekly, current_ltp=96.0)
            assert eval_res_weekly is None  # 11m < 15m standard weekly

    def test_vwap_band_breakdown_warning_bullish_equity(self):
        """Spot price breaching below -1.0σ VWAP band triggers institutional order flow breakdown alert."""
        alert = AutoAlert(
            alert_id="vwap-equity-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="TRENT",
            exchange="NSE",
            direction="BULLISH",
            headline="Trent Long Breakout",
            summary="Monitoring VWAP band reversion",
            ltp=2850.0,
            trigger_level=2850.0,
            stop_loss=2750.0,
            target_level=3050.0,
            metrics={"vwap": 2850.0, "vwap_std": 30.0},  # Lower band = 2820.0
            is_live=True,
        )
        # Spot price at 2815.0 breaks below lower band (2820.0), well above nominal SL (2750.0)
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=2815.0)
        assert eval_res is not None
        assert eval_res.triggered is True
        assert eval_res.warning_type == "VWAP_BAND_BREAKDOWN"
        assert eval_res.coaching_decision == "SCRATCH_OR_TIGHTEN_TO_VWAP"
        assert "VWAP -1.0σ Institutional Band Breakdown" in eval_res.headline
        assert "broke below -1.0σ band (₹2,820.00)" in eval_res.reason
        assert "TIGHTEN STOP TO VWAP LOWER BAND" in eval_res.summary

    def test_vwap_band_breakout_warning_bearish_setup(self):
        """Bearish setup price surging above +1.0σ VWAP band triggers institutional invalidation alert."""
        alert = AutoAlert(
            alert_id="vwap-bearish-1",
            alert_type="BREAKDOWN_SHORT",
            stage="IGNITED",
            symbol="BAJFINANCE",
            exchange="NSE",
            direction="BEARISH",
            headline="Bajaj Finance Short Breakdown",
            summary="Monitoring VWAP upper band",
            ltp=6800.0,
            trigger_level=6800.0,
            stop_loss=7000.0,
            target_level=6500.0,
            metrics={"vwap": 6800.0, "vwap_std": 40.0},  # Upper band = 6840.0
            is_live=True,
        )
        # Price surges to 6850.0 (above upper band 6840.0, before SL 7000.0)
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=6850.0)
        assert eval_res is not None
        assert eval_res.triggered is True
        assert eval_res.warning_type == "VWAP_BAND_BREAKDOWN"
        assert eval_res.coaching_decision == "SCRATCH_OR_TIGHTEN_TO_VWAP"
        assert "VWAP +1.0σ Institutional Band Breakout" in eval_res.headline
        assert "broke above +1.0σ band (₹6,840.00)" in eval_res.reason

    def test_vwap_band_breakdown_warning_options_underlying_spot(self):
        """Option setup underlying spot breaching below VWAP -1.0σ band warns before premium SL is hit."""
        alert = AutoAlert(
            alert_id="vwap-opt-1",
            alert_type="OPTIONS_MOMENTUM_BREAKOUT",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty Call Momentum",
            summary="Spot VWAP tracking",
            ltp=95.0,
            trigger_level=100.0,
            target_level=160.0,
            option_premium=100.0,
            stop_loss=60.0,
            option_type="CE",
            strike=24500,
            underlying_spot=24450.0,  # Underlying spot
            metrics={"vwap": 24500.0, "vwap_std": 35.0},  # Lower band = 24465.0
            is_live=True,
        )
        # Option premium is 95.0 (well above SL 60.0), but underlying spot 24450 < 24465 band!
        eval_res = evaluate_alert_in_flight_decay(alert, current_ltp=95.0)
        assert eval_res is not None
        assert eval_res.triggered is True
        assert eval_res.warning_type == "VWAP_BAND_BREAKDOWN"
        assert eval_res.coaching_decision == "SCRATCH_OR_TIGHTEN_TO_VWAP"

    def test_in_flight_warning_one_shot_latching_in_auto_alert_engine(self, mock_engine):
        """check_and_alert_in_flight_decay must strictly dispatch only once (one-shot latching)."""
        alert = AutoAlert(
            alert_id="latch-test-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="SBIN",
            exchange="NSE",
            direction="BULLISH",
            headline="SBI Squeeze Ignition",
            summary="Testing one-shot latching",
            ltp=800.0,
            trigger_level=800.0,
            stop_loss=780.0,  # 20 pts risk
            target_level=860.0,
            confidence=85,
            is_live=True,
            environment="LIVE",
            in_flight_warning_sent=False,
        )
        mock_engine._alerts = [alert]

        # Quote drops to 785 (15 pts risk consumed = 75%)
        with patch("market.quotes.get_ltp", return_value=785.0):
            with patch.object(mock_engine, "_dispatch") as mock_dispatch:
                warned = mock_engine.check_and_alert_in_flight_decay()
                assert len(warned) == 1
                assert alert.in_flight_warning_sent is True
                assert alert.stage == "IN_FLIGHT_WARNING"
                assert mock_dispatch.call_count == 1

                # Second run with same price -> MUST NOT send duplicate warning!
                warned_second = mock_engine.check_and_alert_in_flight_decay()
                assert len(warned_second) == 0
                assert mock_dispatch.call_count == 1  # Still 1!

    def test_danger_zone_disqualified_when_trade_in_profit(self):
        """A trade in profit (e.g. MCX:CRUDEOIL short) MUST NEVER trigger DANGER_ZONE even if distance to SL < 1.5%."""
        # Short trade: Entry 9522.05, SL 9555.40, LTP 9509.10 (+12.95 pts profit)
        # Note: Raw distance from 9509.10 to 9555.40 is 46.3 pts (0.49% of spot price),
        # but because the position is WINNING, it must NEVER be flagged in Danger Zone!
        crude_short = AutoAlert(
            alert_id="crude-prof-1",
            alert_type="COMMODITY_MOMENTUM",
            stage="IGNITED",
            symbol="CRUDEOIL",
            exchange="MCX",
            direction="BEARISH",
            headline="Crude Short",
            summary="Testing profit exclusion",
            trigger_level=9522.05,
            stop_loss=9555.40,
            target_level=9460.0,
            ltp=9509.10,
            is_live=True,
        )
        res = evaluate_alert_in_flight_decay(crude_short, current_ltp=9509.10)
        assert res is None  # Must NOT trigger!

        # Long trade in profit: Entry 2800, SL 2760, LTP 2820 (+20 pts profit)
        # Raw distance to SL 2760 is 60 pts (2.1%), in profit.
        trent_long = AutoAlert(
            alert_id="trent-prof-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IGNITED",
            symbol="TRENT",
            exchange="NSE",
            direction="BULLISH",
            headline="Trent Long",
            summary="Testing profit exclusion",
            trigger_level=2800.0,
            stop_loss=2760.0,
            target_level=2950.0,
            ltp=2820.0,
            is_live=True,
        )
        res_long = evaluate_alert_in_flight_decay(trent_long, current_ltp=2820.0)
        assert res_long is None  # Must NOT trigger!

    def test_in_flight_warning_disqualified_when_target_1_already_achieved(self):
        """Trades that have achieved Target 1 are risk-free or trailing, and must NEVER receive in-flight warnings."""
        alert = AutoAlert(
            alert_id="t1-achieved-1",
            alert_type="COMMODITY_MOMENTUM",
            stage="IGNITED",
            symbol="CRUDEOIL",
            exchange="MCX",
            direction="BEARISH",
            headline="Crude Short T1",
            summary="T1 achieved testing",
            trigger_level=9522.05,
            stop_loss=9555.40,
            target_level=9460.0,
            ltp=9515.0,
            is_live=True,
            target_status="T1_ACHIEVED",
            achieved_milestones=["T1_ACHIEVED"],
        )
        res = evaluate_alert_in_flight_decay(alert, current_ltp=9515.0)
        assert res is None

    def test_dispatch_milestone_latch_prevents_duplicate_in_flight_warnings(self, mock_engine):
        """_dispatch() must latch IN_FLIGHT_WARNING in _dispatched_milestones and never send duplicates."""
        alert = AutoAlert(
            alert_id="latch-dispatch-1",
            alert_type="COMMODITY_MOMENTUM",
            stage="IN_FLIGHT_WARNING",
            symbol="CRUDEOIL",
            exchange="MCX",
            direction="BEARISH",
            headline="Crude Warning",
            summary="Warning testing",
            trigger_level=9522.05,
            stop_loss=9555.40,
            target_level=9460.0,
            ltp=9550.0,
            is_live=True,
            environment="LIVE",
            in_flight_warning_sent=True,
            in_flight_warning_reason="DANGER ZONE: 84% risk budget consumed.",
        )
        with patch("engine.alerts._telegram_notify") as mock_notify:
            # First dispatch -> dispatches to Telegram
            mock_engine._dispatch(alert)
            assert mock_notify.call_count == 1
            latch_key = f"CRUDEOIL:latch-dispatch-1:IN_FLIGHT_WARNING"
            assert latch_key in mock_engine._dispatched_milestones

            # Second dispatch -> MUST be suppressed by milestone latch!
            mock_engine._dispatch(alert)
            assert mock_notify.call_count == 1  # Still 1! Zero duplicate!

    def test_load_restores_in_flight_warning_fields(self, tmp_path, monkeypatch):
        """_load() accurately restores in_flight_warning_sent and seeds _dispatched_milestones."""
        data_file = tmp_path / "auto_alerts.json"
        monkeypatch.setattr("engine.auto_alert_engine.get_auto_alerts_file", lambda: data_file)

        engine = AutoAlertEngine()
        alert = AutoAlert(
            alert_id="persist-warn-1",
            alert_type="COMMODITY_MOMENTUM",
            stage="IN_FLIGHT_WARNING",
            symbol="CRUDEOIL",
            exchange="MCX",
            direction="BEARISH",
            headline="Crude Warning",
            summary="Warning testing",
            trigger_level=9522.05,
            stop_loss=9555.40,
            target_level=9460.0,
            ltp=9550.0,
            is_live=True,
            environment="LIVE",
            in_flight_warning_sent=True,
            in_flight_warning_reason="DANGER ZONE: 84% risk consumed.",
            in_flight_warning_at="2026-09-11 22:00:00 IST",
        )
        engine._alerts = [alert]
        engine._save()

        # Create fresh engine instance loading from disk
        new_engine = AutoAlertEngine()
        assert len(new_engine._alerts) == 1
        loaded = new_engine._alerts[0]
        assert loaded.in_flight_warning_sent is True
        assert loaded.in_flight_warning_reason == "DANGER ZONE: 84% risk consumed."
        assert loaded.in_flight_warning_at == "2026-09-11 22:00:00 IST"
        # Seeded milestone check
        assert f"CRUDEOIL:persist-warn-1:IN_FLIGHT_WARNING" in new_engine._dispatched_milestones


# ── Telegram Alert Template Formatting Tests ─────────────────────────────────

class TestInFlightAlertTemplates:
    def test_render_danger_zone_in_flight_warning_alert(self):
        """Verifies Telegram formatting for Danger Zone in-flight warning alert."""
        alert = AutoAlert(
            alert_id="tg-warn-1",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IN_FLIGHT_WARNING",
            symbol="RELIANCE",
            exchange="NSE",
            direction="BULLISH",
            headline="Reliance Danger Zone Warning",
            summary="DANGER ZONE: 87% risk budget consumed. LTP ₹2,825.00 near SL ₹2,820.00",
            ltp=2825.0,
            trigger_level=2860.0,
            stop_loss=2820.0,
            target_level=2980.0,
            in_flight_warning_sent=True,
            in_flight_warning_reason="DANGER ZONE: 87% risk budget consumed. LTP ₹2,825.00 near SL ₹2,820.00",
            trailing_decision="SCRATCH_OR_TIGHTEN_STOP",
            environment="LIVE",
            is_live=True,
            created_at="2026-09-11 10:15:00 IST",
        )
        msg = render_auto_alert(alert, in_market=True)
        assert "IN-FLIGHT DANGER WARNING" in msg
        assert "RELIANCE (SQUEEZE BREAKOUT)" in msg
        assert "₹2,825.00" in msg
        assert "DANGER ZONE: 87% risk budget consumed" in msg
        assert "SCRATCH_OR_TIGHTEN_STOP" in msg

    def test_render_theta_stagnation_in_flight_warning_alert(self):
        """Verifies Telegram formatting for Theta Stagnation in-flight warning alert."""
        alert = AutoAlert(
            alert_id="tg-warn-2",
            alert_type="OPTIONS_MOMENTUM_BREAKOUT",
            stage="IN_FLIGHT_WARNING",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty Theta Stagnation Warning",
            summary="THETA STAGNATION: 18m elapsed without momentum (P&L: -8.0%).",
            contract_symbol="NIFTY 24500 CE",
            option_type="CE",
            strike=24500,
            ltp=92.0,
            trigger_level=100.0,
            option_premium=100.0,
            stop_loss=70.0,
            target_level=160.0,
            in_flight_warning_sent=True,
            in_flight_warning_reason="THETA STAGNATION: 18m elapsed without momentum (P&L: -8.0%).",
            trailing_decision="EXIT_STAGNANT_OPTION",
            environment="LIVE",
            is_live=True,
            created_at="2026-09-11 10:00:00 IST",
        )
        msg = render_auto_alert(alert, in_market=True)
        assert "THETA DECAY WARNING" in msg
        assert "NIFTY 24500 CE" in msg
        assert "THETA STAGNATION: 18m elapsed" in msg
        assert "EXIT_STAGNANT_OPTION" in msg

    def test_render_vwap_band_in_flight_warning_alert(self):
        """Verifies Telegram formatting for VWAP Band Breakdown warning alert."""
        alert = AutoAlert(
            alert_id="tg-warn-3",
            alert_type="SQUEEZE_BREAKOUT",
            stage="IN_FLIGHT_WARNING",
            symbol="TRENT",
            exchange="NSE",
            direction="BULLISH",
            headline="Trent VWAP Band Warning",
            summary="VWAP BAND BREAKDOWN: Price ₹2,815.00 broke below -1.0σ band (₹2,820.00).",
            ltp=2815.0,
            trigger_level=2850.0,
            stop_loss=2750.0,
            target_level=3050.0,
            in_flight_warning_sent=True,
            in_flight_warning_reason="VWAP BAND BREAKDOWN: Price ₹2,815.00 broke below -1.0σ band (₹2,820.00).",
            trailing_decision="SCRATCH_OR_TIGHTEN_TO_VWAP",
            environment="LIVE",
            is_live=True,
            created_at="2026-09-11 11:00:00 IST",
        )
        msg = render_auto_alert(alert, in_market=True)
        assert "🌊" in msg
        assert "VWAP BAND WARNING" in msg
        assert "TRENT (SQUEEZE BREAKOUT)" in msg
        assert "₹2,815.00" in msg
        assert "broke below -1.0σ band" in msg
        assert "SCRATCH_OR_TIGHTEN_TO_VWAP" in msg

    def test_render_0dte_cliff_in_flight_warning_alert(self):
        """Verifies Telegram formatting for 0DTE Afternoon Theta Cliff warning alert."""
        alert = AutoAlert(
            alert_id="tg-warn-4",
            alert_type="OPTIONS_MOMENTUM_BREAKOUT",
            stage="IN_FLIGHT_WARNING",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="Nifty 0DTE Cliff Warning",
            summary="0DTE_AFTERNOON_THETA_CLIFF: 9m elapsed without momentum (P&L: -5.0%).",
            contract_symbol="NIFTY 24200 CE",
            option_type="CE",
            strike=24200,
            ltp=40.0,
            trigger_level=45.0,
            option_premium=45.0,
            stop_loss=25.0,
            target_level=75.0,
            in_flight_warning_sent=True,
            in_flight_warning_reason="0DTE_AFTERNOON_THETA_CLIFF: 9m elapsed without momentum (P&L: -5.0%).",
            trailing_decision="EXIT_0DTE_OPTION_IMMEDIATELY",
            environment="LIVE",
            is_live=True,
            created_at="2026-09-10 13:51:00 IST",
        )
        msg = render_auto_alert(alert, in_market=True)
        assert "⏳" in msg
        assert "0DTE THETA CLIFF WARNING" in msg
        assert "NIFTY 24200 CE" in msg
        assert "0DTE_AFTERNOON_THETA_CLIFF" in msg
        assert "EXIT_0DTE_OPTION_IMMEDIATELY" in msg

    def test_create_test_in_flight_warning_alert_engine(self, mock_engine):
        """Engine test helper create_test_in_flight_warning_alert generates valid test alerts for all variants."""
        with patch.object(mock_engine, "_dispatch") as mock_dispatch:
            # Theta stagnation test alert
            alert = mock_engine.create_test_in_flight_warning_alert(
                warning_type="THETA_STAGNATION",
                symbol="TCS",
            )
            assert alert.environment == "TEST"
            assert alert.stage == "IN_FLIGHT_WARNING"
            assert alert.in_flight_warning_sent is True
            assert "Theta Stagnation" in alert.headline
            assert mock_dispatch.call_count == 1

            # VWAP band breakdown test alert
            vwap_alert = mock_engine.create_test_in_flight_warning_alert(
                warning_type="VWAP_BAND_BREAKDOWN",
                symbol="INFY",
            )
            assert vwap_alert.stage == "IN_FLIGHT_WARNING"
            assert "VWAP -1.0σ Institutional Band Breakdown" in vwap_alert.headline
            assert vwap_alert.trailing_decision == "SCRATCH_OR_TIGHTEN_TO_VWAP"
            assert mock_dispatch.call_count == 2

            # 0DTE theta cliff test alert
            cliff_alert = mock_engine.create_test_in_flight_warning_alert(
                warning_type="0DTE_AFTERNOON_THETA_CLIFF",
                symbol="BANKNIFTY",
            )
            assert cliff_alert.stage == "IN_FLIGHT_WARNING"
            assert "0DTE Theta Cliff" in cliff_alert.headline
            assert cliff_alert.trailing_decision == "EXIT_0DTE_OPTION_IMMEDIATELY"
            assert mock_dispatch.call_count == 3
