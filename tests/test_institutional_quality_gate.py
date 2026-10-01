"""
tests/test_institutional_quality_gate.py
────────────────────────────────────────
Comprehensive tests for Institutional Quality Gate, Hard Veto Matrix,
Conviction Tiers, and Free-Roll Protocol.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from engine.quality_gate import (
    evaluate_institutional_quality_gate,
    is_lunchtime_theta_window,
    is_eod_close_window,
)
from engine.auto_alert_engine import AutoAlert, AutoAlertEngine
from engine.trade_plan import calculate_trade_plan, calculate_option_execution_plan

IST = timezone(timedelta(hours=5, minutes=30))


class TestHeadroomAndRRChecks:
    """Tests headroom vs barrier collision and minimum R:R floor (1:1.8)."""

    def test_poor_rr_below_floor_is_vetoed(self):
        """Verify that setup with Target 2 < 1.8R against stop risk is vetoed."""
        alert = AutoAlert(
            alert_id="NIFTY-POOR-RR-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="Nifty Weak Headroom Breakout",
            summary="Target is compressed against overhead barrier",
            ltp=24000.0,
            symbol="NIFTY",
            direction="BULLISH",
            trigger_level=24000.0,
            stop_loss=23920.0,  # 80 pts risk
            target_level=24050.0,
            actionable_plan={"target_2": 24080.0},  # 80 pts reward -> R:R 1.0 < 1.8
            confidence=85,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert)
        assert verdict.is_vetoed is True
        assert "Poor Structural R:R" in verdict.veto_reason
        assert verdict.conviction_tier == "REJECTED"
        assert verdict.execution_mandate == "VETOED"

    def test_viable_rr_passes_gate(self):
        """Verify that setup with Target 2 >= 1.8R passes the gate."""
        alert = AutoAlert(
            alert_id="NIFTY-GOOD-RR-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="Nifty High Headroom Breakout",
            summary="Clear runway to weekly volume node",
            ltp=24000.0,
            symbol="NIFTY",
            direction="BULLISH",
            trigger_level=24000.0,
            stop_loss=23940.0,  # 60 pts risk
            target_level=24120.0,  # 120 pts reward -> 2.0R
            actionable_plan={"target_2": 24200.0},  # 200 pts reward -> 3.33R
            confidence=88,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert)
        assert verdict.is_vetoed is False
        assert verdict.conviction_tier in ("HIGH_CONVICTION", "APEX_CONFLUENCE")


class TestTimeOfDayThetaTrapFilters:
    """Tests Lunchtime (11:30–13:15 IST) and EOD (post-15:00 IST) filters."""

    def test_lunchtime_window_mandates_defined_risk_spread(self):
        """Verify lunchtime option buying alerts get mandated to defined-risk spreads."""
        # Monday 12:15 IST (middle of chop window)
        lunch_dt = datetime(2026, 9, 28, 12, 15, tzinfo=IST)
        assert is_lunchtime_theta_window(lunch_dt) is True

        alert = AutoAlert(
            alert_id="NIFTY-LUNCH-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="Nifty Midday Call",
            summary="Midday breakout attempt",
            ltp=120.0,
            symbol="NIFTY",
            direction="BULLISH",
            trigger_level=120.0,
            stop_loss=90.0,
            target_level=180.0,
            strike=24500,
            option_type="CE",
            contract_symbol="NIFTY2692824500CE",
            confidence=82,  # < 92 exceptional conviction
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert, ref_dt=lunch_dt)
        assert verdict.is_vetoed is False
        assert verdict.execution_mandate == "HEDGED_SPREAD_MANDATORY"
        assert any("Lunchtime Theta Trap" in n for n in verdict.coaching_notes)

    def test_eod_terminal_window_vetoes_directional_option_buys(self):
        """Verify post-15:00 IST intraday option buying is strictly vetoed."""
        # Monday 15:05 IST
        eod_dt = datetime(2026, 9, 28, 15, 5, tzinfo=IST)
        assert is_eod_close_window(eod_dt) is True

        alert = AutoAlert(
            alert_id="NIFTY-EOD-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="Nifty Late Option Buy",
            summary="Late session scalping",
            ltp=85.0,
            symbol="NIFTY",
            direction="BULLISH",
            trigger_level=85.0,
            stop_loss=60.0,
            target_level=140.0,
            strike=24500,
            option_type="CE",
            contract_symbol="NIFTY2692824500CE",
            confidence=85,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert, ref_dt=eod_dt)
        assert verdict.is_vetoed is True
        assert "EOD Terminal Window" in verdict.veto_reason
        assert verdict.conviction_tier == "REJECTED"


class TestMultiTimeframeAndVWAPAlignment:
    """Tests MTF and VWAP anchor trend consistency."""

    def test_long_below_vwap_vetoed(self):
        """Verify long setup trading below intraday VWAP without sweep confirmation is vetoed."""
        alert = AutoAlert(
            alert_id="INFY-VWAP-CONFLICT-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="Infosys Long Signal",
            summary="Trying to buy into supply",
            ltp=1780.0,
            symbol="INFY",
            direction="BULLISH",
            trigger_level=1780.0,
            stop_loss=1760.0,
            target_level=1830.0,
            underlying_spot=1780.0,
            confidence=84,  # < 88
            environment="LIVE",
            is_live=True,
        )
        # Spot 1780 is 1.1% below VWAP 1800
        verdict = evaluate_institutional_quality_gate(
            alert, current_ltp=1780.0, current_vwap=1800.0
        )
        assert verdict.is_vetoed is True
        assert "VWAP Breakdown Conflict" in verdict.veto_reason


class TestConvictionTieringAndVetoMatrix:
    """Tests 3-tier conviction classification and rejection floor."""

    def test_apex_confluence_tier_classification(self):
        """Verify setup with >=90 confidence or >=3 confluences is APEX_CONFLUENCE."""
        alert = AutoAlert(
            alert_id="TCS-APEX-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="TCS Apex Breakout",
            summary="Triple confluence breakout",
            ltp=4200.0,
            symbol="TCS",
            direction="BULLISH",
            trigger_level=4200.0,
            stop_loss=4150.0,
            target_level=4350.0,
            confidence=94,
            metrics={"confluence_types": ["SQUEEZE", "VOLUME_PROFILE", "RRG_LEADING"]},
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert)
        assert verdict.is_vetoed is False
        assert verdict.conviction_tier == "APEX_CONFLUENCE"

    def test_sub_par_conviction_below_70_is_rejected(self):
        """Verify setup with confidence < 70 is vetoed."""
        alert = AutoAlert(
            alert_id="WEAK-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="Weak Speculative Call",
            summary="Low conviction noise",
            ltp=500.0,
            symbol="TATAMOTORS",
            direction="BULLISH",
            trigger_level=500.0,
            stop_loss=490.0,
            target_level=525.0,
            confidence=64,  # < 70 floor
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert)
        assert verdict.is_vetoed is True
        assert "Sub-Par Conviction" in verdict.veto_reason
        assert verdict.conviction_tier == "REJECTED"


class TestFreeRollProtocolAndEngineIntegration:
    """Tests Free-Roll blueprint generation and AutoAlertEngine integration."""

    def test_calculate_option_execution_plan_includes_free_roll_plan(self):
        """Verify calculate_option_execution_plan generates complete Free-Roll protocol."""
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
        assert "free_roll_plan" in plan
        fr = plan["free_roll_plan"]
        assert fr["status"] == "ELIGIBLE"
        assert fr["t1_scale_action"] == "SCALE_OUT_50_PCT"
        assert fr["runner_size_pct"] == 50.0
        assert fr["net_risk_after_t1"] == 0.0
        assert fr["breakeven_stop"] > 0
        assert "Free-Roll" in fr["protocol_summary"]

    def test_engine_record_alert_attaches_quality_verdict_and_tier(self):
        """Verify AutoAlertEngine records quality gate verdict and stamps conviction tier."""
        engine = AutoAlertEngine()
        engine._alerts = []
        engine._cooldowns = {}
        alert = AutoAlert(
            alert_id="TITAN-LIVE-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="Titan Company Breakout",
            summary="Institutional volume breakout above consolidation",
            ltp=3500.0,
            symbol="TITAN",
            direction="BULLISH",
            trigger_level=3500.0,
            stop_loss=3460.0,
            target_level=3620.0,
            confidence=91,
            metrics={"is_decoupler": True},
            is_live=True,
            environment="LIVE",
        )
        recorded = engine.record_alert(alert)
        assert recorded is True
        assert alert.metrics.get("conviction_tier") == "APEX_CONFLUENCE"
        assert alert.metrics.get("quality_gate_verdict") is not None
        # Audit trail must document quality gate passage
        assert any(evt.get("event_type") == "QUALITY_GATE_PASSED" for evt in alert.audit_trail)

    def test_engine_record_alert_vetoes_poor_rr_setup(self):
        """Verify AutoAlertEngine vetoes and suppresses setup with poor R:R."""
        engine = AutoAlertEngine()
        engine._alerts = []
        engine._cooldowns = {}
        alert = AutoAlert(
            alert_id="SBIN-BAD-RR-01",
            alert_type="INTRADAY_BREAKOUT_SPARK",
            stage="IGNITED",
            exchange="NSE",
            headline="SBI Compressed Target",
            summary="Overhead supply immediately above entry",
            ltp=800.0,
            symbol="SBIN",
            direction="BULLISH",
            trigger_level=800.0,
            stop_loss=780.0,  # 20 pts risk
            target_level=830.0,  # 30 pts reward -> 1.5R (passes Tier 1 sanity)
            actionable_plan={"target_2": 834.0},  # 34 pts reward -> 1.7R < 1.8R floor
            confidence=82,
            metrics={"is_decoupler": True},
            is_live=True,
            environment="LIVE",
        )
        recorded = engine.record_alert(alert)
        assert recorded is False
        assert any(evt.get("event_type") == "QUALITY_GATE_VETOED" for evt in alert.audit_trail)

    def test_sebi_physical_settlement_week_vetoes_near_month_stock_derivative(self):
        """Verify quality gate strictly vetoes near-month stock options in monthly expiry week."""
        # 2026-09-24 is last Thursday of Sept 2026. Ref date: 2026-09-22 (DTE=2, settlement week)
        ref_dt = datetime(2026, 9, 22, 10, 0, tzinfo=IST)
        alert = AutoAlert(
            alert_id="RELIANCE-PHYS-TRAP-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="Reliance Near Month Call",
            summary="Expiring stock option in physical settlement week",
            ltp=45.0,
            symbol="RELIANCE",
            direction="BULLISH",
            trigger_level=45.0,
            stop_loss=35.0,
            target_level=70.0,
            strike=3000.0,
            option_type="CE",
            contract_symbol="RELIANCE26SEP3000CE",
            expiry_date="2026-09-24",
            segment="FNO_STOCK",
            confidence=85,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert, ref_dt=ref_dt)
        assert verdict.is_vetoed is True
        assert "SEBI Physical Settlement Week Trap" in verdict.veto_reason
        assert verdict.conviction_tier == "REJECTED"

    def test_sebi_physical_settlement_week_allows_next_month_stock_derivative(self):
        """Verify quality gate allows stock options correctly routed to next month expiry."""
        # Ref date: 2026-09-22 (settlement week for Sept), but contract is Oct (2026-10-29)
        ref_dt = datetime(2026, 9, 22, 10, 0, tzinfo=IST)
        alert = AutoAlert(
            alert_id="RELIANCE-NEXT-MONTH-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="Reliance Next Month Call",
            summary="Rolled over stock option in safe next-month cycle",
            ltp=65.0,
            symbol="RELIANCE",
            direction="BULLISH",
            trigger_level=65.0,
            stop_loss=50.0,
            target_level=105.0,
            strike=3000.0,
            option_type="CE",
            contract_symbol="RELIANCE26OCT3000CE",
            expiry_date="2026-10-29",
            segment="FNO_STOCK",
            confidence=85,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert, ref_dt=ref_dt)
        assert verdict.is_vetoed is False
        assert verdict.conviction_tier == "HIGH_CONVICTION"

    def test_sebi_physical_settlement_week_allows_cash_settled_index(self):
        """Verify quality gate permits cash-settled indices on expiry day/week (zero delivery risk)."""
        ref_dt = datetime(2026, 9, 24, 10, 0, tzinfo=IST)
        alert = AutoAlert(
            alert_id="NIFTY-EXPIRY-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="Nifty Cash Settled Weekly",
            summary="Index weekly option trading on expiry day",
            ltp=120.0,
            symbol="NIFTY",
            direction="BULLISH",
            trigger_level=120.0,
            stop_loss=90.0,
            target_level=180.0,
            strike=24500.0,
            option_type="CE",
            contract_symbol="NIFTY24500CE",
            expiry_date="2026-09-24",
            segment="FNO_INDEX",
            confidence=85,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert, ref_dt=ref_dt)
        assert verdict.is_vetoed is False

    def test_high_india_vix_mandates_hedged_spread(self):
        """Verify elevated India VIX (>= 19.0) mandates defined-risk vertical spread."""
        alert = AutoAlert(
            alert_id="NIFTY-HIGH-VIX-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="High VIX Option Buying",
            summary="Setup during heightened volatility",
            ltp=150.0,
            symbol="NIFTY",
            direction="BULLISH",
            trigger_level=150.0,
            stop_loss=110.0,
            target_level=230.0,
            strike=24500.0,
            option_type="CE",
            contract_symbol="NIFTY24500CE",
            expiry_date="2026-10-08",
            segment="FNO_INDEX",
            confidence=86,
            metrics={"india_vix": 21.4},
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert)
        assert verdict.is_vetoed is False
        assert verdict.execution_mandate == "HEDGED_SPREAD_MANDATORY"
        assert any(
            "High India VIX" in n or "Elevated India VIX" in n for n in verdict.coaching_notes
        )

    def test_conviction_tier_position_sizing_multipliers(self):
        """Verify position sizer scales lot allocation based on conviction tier."""
        from engine.position_sizer import (
            calculate_position_size_for_alert,
            generate_execution_ticket,
        )

        base_res = calculate_position_size_for_alert(
            alert_type="INTRADAY_BREAKOUT_SPARK",
            symbol="RELIANCE",
            entry_price=3000.0,
            stop_loss=2950.0,
            capital=500000.0,
            conviction_tier="HIGH_CONVICTION",
        )

        apex_res = calculate_position_size_for_alert(
            alert_type="INTRADAY_BREAKOUT_SPARK",
            symbol="RELIANCE",
            entry_price=3000.0,
            stop_loss=2950.0,
            capital=500000.0,
            conviction_tier="APEX_CONFLUENCE",
        )

        tier3_res = calculate_position_size_for_alert(
            alert_type="INTRADAY_BREAKOUT_SPARK",
            symbol="RELIANCE",
            entry_price=3000.0,
            stop_loss=2950.0,
            capital=500000.0,
            conviction_tier="DEFINED_RISK_ONLY",
        )

        # APEX tier should allocate more lots/shares than DEFINED_RISK_ONLY
        assert apex_res.lots >= base_res.lots
        assert tier3_res.lots <= base_res.lots
        assert "APEX_CONFLUENCE" in apex_res.notes
        assert "DEFINED_RISK_ONLY" in tier3_res.notes

        ticket = generate_execution_ticket(
            symbol="RELIANCE",
            entry_price=3000.0,
            stop_loss=2950.0,
            target_price=3120.0,
            alert_type="INTRADAY_BREAKOUT_SPARK",
            conviction_tier="APEX_CONFLUENCE",
        )
        assert ticket["conviction_tier"] == "APEX_CONFLUENCE"
        assert ticket["shares"] > 0

    def test_is_monthly_physical_expiry_week_calendar_mode(self):
        """Verify is_monthly_physical_expiry_week detects expiry week even without expiry_str."""
        from engine.alert_expiry import (
            is_monthly_physical_expiry_week,
            check_monthly_physical_settlement_status,
        )

        # 2026-09-24 is last Thursday of Sept 2026
        # Tuesday 2026-09-22: DTE=2 -> Monthly physical settlement week
        tue_dt = datetime(2026, 9, 22, 11, 0, tzinfo=IST)
        assert is_monthly_physical_expiry_week(symbol="RELIANCE", ref_dt=tue_dt) is True
        assert is_monthly_physical_expiry_week(symbol="NIFTY", ref_dt=tue_dt) is False

        is_wk, dte = check_monthly_physical_settlement_status(symbol="RELIANCE", ref_dt=tue_dt)
        assert is_wk is True
        assert dte == 2

        is_wk_idx, _ = check_monthly_physical_settlement_status(symbol="NIFTY", ref_dt=tue_dt)
        assert is_wk_idx is False

        # Mid-month: Thursday 2026-09-10 (DTE=14) -> Not expiry week
        mid_dt = datetime(2026, 9, 10, 11, 0, tzinfo=IST)
        assert is_monthly_physical_expiry_week(symbol="RELIANCE", ref_dt=mid_dt) is False

    def test_quality_gate_vetoes_unrouted_stock_derivative_during_expiry_week(self):
        """Verify quality gate vetoes F&O stock derivative without next-month routing during settlement week."""
        tue_dt = datetime(2026, 9, 22, 11, 0, tzinfo=IST)
        alert = AutoAlert(
            alert_id="TCS-EXPIRY-UNROUTED-01",
            alert_type="OPTIONS_MOMENTUM",
            stage="IGNITED",
            exchange="NFO",
            headline="TCS Call Option",
            summary="Single stock option without explicit next-month rollover",
            ltp=40.0,
            symbol="TCS",
            direction="BULLISH",
            trigger_level=40.0,
            stop_loss=30.0,
            target_level=65.0,
            strike=4200.0,
            option_type="CE",
            segment="FNO_STOCK",
            confidence=85,
            environment="LIVE",
            is_live=True,
        )
        verdict = evaluate_institutional_quality_gate(alert, ref_dt=tue_dt)
        assert verdict.is_vetoed is True
        assert "SEBI Physical Settlement Week Trap" in verdict.veto_reason
        assert verdict.conviction_tier == "REJECTED"

    def test_get_options_chain_routes_fno_stock_to_next_month_during_settlement_week(
        self, monkeypatch
    ):
        """Verify get_options_chain defaults to next-month contract for F&O stocks in settlement week."""
        from market.options import get_options_chain, _CHAIN_CACHE
        from brokers.base import OptionsContract

        _CHAIN_CACHE.clear()

        # Mock broker to capture requested expiry
        requested_expiries = []

        class DummyBroker:
            def get_options_chain(self, underlying, expiry=None):
                requested_expiries.append((underlying, expiry))
                return [
                    OptionsContract(
                        symbol=f"{underlying}NEXTCE",
                        underlying=underlying,
                        expiry=expiry or "2026-10-29",
                        strike=3000.0,
                        option_type="CE",
                        last_price=55.0,
                        oi=10000,
                        oi_change=500,
                        volume=25000,
                        lot_size=250,
                    )
                ]

        monkeypatch.setattr("market.options.get_data_broker", lambda: DummyBroker())
        monkeypatch.setattr(
            "engine.alert_expiry.is_monthly_physical_expiry_week",
            lambda symbol=None, ref_dt=None, expiry_str=None, **kwargs: True,
        )
        monkeypatch.setattr(
            "engine.alert_expiry.resolve_recommended_derivative_expiry",
            lambda **kwargs: {"is_next_month_routed": True, "recommended_expiry": "2026-10-29"},
        )
        monkeypatch.setattr(
            "market.options.get_expiries",
            lambda underlying: ["2026-09-24", "2026-10-29", "2026-11-26"],
        )

        chain = get_options_chain("RELIANCE")
        assert len(chain) == 1
        assert len(requested_expiries) == 1
        und, exp_arg = requested_expiries[0]
        assert und == "RELIANCE"
        # Must have requested the safe next-month contract, not current month
        assert exp_arg == "2026-10-29"
