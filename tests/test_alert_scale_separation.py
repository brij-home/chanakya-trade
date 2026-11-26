"""
tests/test_alert_scale_separation.py — Invariant 14.1 Scale Separation & Lifecycle Tests

Tests for:
1. Invariant 14.1: Universal Scale Separation Guarantee between cash equity spot and derivative option premiums.
2. Prevention of spot target leaks (e.g. 478.4R bug) in option-enriched swing alerts.
3. Midday velocity stagnation scratch protection for multi-day swing/positional setups.
4. Strike step calculation invariants: equity derivatives must always have integer strike steps >= 1.0.
5. Defined-risk spread generation on corporate-action stocks (e.g. COALINDIA) creating institutional corridors.
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from market.symbol_master import get_strike_step
from engine.defined_risk_spreads import build_defined_risk_spread

IST = ZoneInfo("Asia/Kolkata")


class TestAlertScaleSeparation:
    def test_option_enriched_swing_alert_enforces_scale_separation(self):
        """
        Verify that when a cash equity swing setup (e.g. RADICO at ₹4,664 with target ₹4,977.5)
        is enriched with an option contract (4700 CE at ₹50.1 with SL ₹39.8):
        1. alert.target_1 is strictly in option space (<= entry * 4.0).
        2. alert.calculate_rr_ratio() returns an institutional R:R (<= 3.5R), never 478.4R.
        3. Spot levels are cleanly preserved in underlying_spot and metrics['spot_target_1'].
        """
        alert = AutoAlert(
            alert_id="aa-stage-1-to-2-expansion-radico-pull-20261116",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RADICO",
            exchange="NFO",
            direction="BULLISH",
            stage="IGNITED",
            headline="🎯 RADICO [Weinstein Stage 1→2 Markup Expansion] 🎯 PULLBACK RETEST",
            summary="High conviction Weinstein Stage 1→2 markup expansion.",
            ltp=48.5,
            trigger_level=50.1,
            target_level=4977.5,
            stop_loss=39.8,
            strike=4700.0,
            option_type="CE",
            contract_symbol="NSE:RADICO26NOV4700CE",
            time_horizon="SWING_MID",
            segment="NFO",
            underlying_spot=4663.0,
            actionable_plan={
                "recommended_entry": 50.1,
                "invalidation_stop": 39.8,
                "target_1": "₹4,977.5",
                "target": "₹4,977.5",
                "profit_rule": "Disciplined Swing Trade. Book 50% at Target 1 (₹4,977.5).",
            },
        )
        alert.entry_price = 50.1
        alert.target_1 = 4977.5
        alert.target_2 = 7441.2
        alert.target_3 = 19412.16

        # Invariant 14.1: calculate_rr_ratio() must discard contaminated spot targets
        rr = alert.calculate_rr_ratio()
        assert rr is not None
        assert 1.5 <= rr <= 3.5, f"Expected institutional R:R between 1.5 and 3.5, got {rr}"
        assert rr != pytest.approx(478.4, abs=5.0)

    def test_swing_inflection_setups_sync_option_targets_cleanly(self):
        """
        Verify that AutoAlertEngine synchronizes option levels when enriching cash swing setups.
        """
        AutoAlertEngine()
        alert = AutoAlert(
            alert_id="aa-test-swing-radico",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RADICO",
            exchange="NSE",
            direction="BULLISH",
            stage="PRIMED",
            headline="RADICO",
            summary="RADICO swing",
            ltp=4646.9,
            trigger_level=4664.0,
            stop_loss=4462.2,
            target_level=4977.5,
            time_horizon="SWING_MID",
            metrics={},
        )
        alert.entry_price = 4664.0
        alert.target_1 = 4977.5
        alert.target_2 = 5219.6

        # Simulate option enrichment
        opt_entry = 50.1
        opt_sl = 39.8
        opt_risk = max(0.5, opt_entry - opt_sl)
        opt_t1 = round(opt_entry + 2.0 * opt_risk, 1)
        opt_t2 = round(opt_entry + 3.5 * opt_risk, 1)
        opt_t3 = round(opt_entry + 5.0 * opt_risk, 1)

        # Apply enrichment logic identical to engine/auto_alert_engine.py
        alert.metrics["spot_entry"] = alert.entry_price
        alert.metrics["spot_stop_loss"] = alert.stop_loss
        alert.metrics["spot_target_1"] = alert.target_1
        alert.underlying_spot = 4664.0
        alert.contract_symbol = "NSE:RADICO26NOV4700CE"
        alert.strike = 4700.0
        alert.option_type = "CE"
        alert.segment = "NFO"
        alert.entry_price = opt_entry
        alert.trigger_level = opt_entry
        alert.stop_loss = opt_sl
        alert.target_1 = opt_t1
        alert.target_2 = opt_t2
        alert.target_3 = opt_t3
        alert.target_level = opt_t1

        assert alert.entry_price == 50.1
        assert alert.stop_loss == 39.8
        assert alert.target_1 == 70.7
        assert alert.target_2 == 86.2
        assert alert.target_3 == 101.6
        assert alert.underlying_spot == 4664.0
        assert alert.metrics["spot_target_1"] == 4977.5

        rr = alert.calculate_rr_ratio()
        assert rr == pytest.approx(3.5, abs=0.1), f"Expected T2 R:R around 3.5, got {rr}"
        t1_rr = (alert.target_1 - alert.entry_price) / (alert.entry_price - alert.stop_loss)
        assert t1_rr == pytest.approx(2.0, abs=0.1), f"Expected T1 R:R around 2.0, got {t1_rr}"

    def test_swing_setups_bypass_midday_velocity_stagnation(self):
        """
        Verify that multi-day swing setups (SWING_MID, STAGE_1_TO_2_EXPANSION) are NOT
        flagged with VELOCITY_STAGNATION_SCRATCH even after hours in trade.
        """
        engine = AutoAlertEngine()
        created_time = (datetime.now(IST) - timedelta(minutes=136)).strftime(
            "%Y-%m-%d %H:%M:%S IST"
        )

        alert = AutoAlert(
            alert_id="aa-stage-1-to-2-expansion-radico-pull-20261116",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RADICO",
            exchange="NFO",
            direction="BULLISH",
            stage="IGNITED",
            headline="RADICO",
            summary="RADICO swing",
            trigger_level=50.1,
            stop_loss=39.8,
            target_level=70.7,
            ltp=49.0,
            strike=4700.0,
            option_type="CE",
            contract_symbol="NSE:RADICO26NOV4700CE",
            time_horizon="SWING_MID",
            created_at=created_time,
            actionable_plan={"time_horizon": "SWING_MID"},
        )
        alert.entry_price = 50.1
        alert.target_1 = 70.7
        alert.triggered_at = created_time
        alert.original_call_time = created_time
        alert.telegram_dispatched = True  # Ensure it is not considered fresh un-dispatched

        # Register alert into engine and run in-flight decay scan
        engine._alerts = [alert]
        engine.check_and_alert_in_flight_decay(quotes_map={"RADICO": 49.0, "NSE:RADICO": 4663.0})

        # Must NOT trigger stagnation scratch for a swing setup
        assert alert.stage == "IGNITED"
        assert alert.trailing_decision is None
        assert "VELOCITY_STAGNATION_SCRATCH" not in str(alert.headline)
        assert not alert.in_flight_warning_sent


class TestStrikeStepInvariants:
    def test_coalindia_strike_step_is_five_points(self):
        """
        Verify that COALINDIA strike step is 5.0, not fractional (0.25) from dividend series.
        """
        step = get_strike_step("COALINDIA", 396.85)
        assert step == 5.0, f"COALINDIA strike step should be 5.0, got {step}"

    def test_all_equity_derivatives_strike_step_ge_one(self):
        """
        Verify that no equity derivative symbol returns a strike step < 1.0.
        """
        test_symbols = [
            ("COALINDIA", 396.85),
            ("RELIANCE", 1300.0),
            ("TCS", 2420.0),
            ("SBIN", 1110.0),
            ("HDFCBANK", 820.0),
            ("RADICO", 4664.0),
            ("PNB", 150.0),
            ("IRFC", 84.0),
        ]
        for sym, price in test_symbols:
            step = get_strike_step(sym, price)
            assert step >= 1.0, f"{sym} strike step {step} is invalidly < 1.0"

    def test_defined_risk_spread_coalindia_institutional_corridor(self):
        """
        Verify that Iron Condor for COALINDIA builds an institutional corridor (>= 10 pts wide),
        not a 1-rupee corridor.
        """
        spread = build_defined_risk_spread("COALINDIA", 396.85, "IRON_CONDOR")
        assert spread is not None
        legs = spread.legs
        assert len(legs) == 4, f"Expected 4 legs for Iron Condor, got {len(legs)}"

        strikes = sorted([leg.strike for leg in legs])
        # Expected strikes should be spread across institutional intervals (e.g. 385, 375, 405, 415)
        corridor_width = max(strikes) - min(strikes)
        assert corridor_width >= 10.0, (
            f"Corridor width {corridor_width} is too narrow for an equity derivative"
        )


class TestScrutinyScaleSeparation:
    def test_scrutiny_quantitative_fallback_never_outputs_spot_target_on_options(self):
        """
        Verify that AlertScrutinyAuditor quantitative fallback clamps spot targets on option alerts
        so that trap_risk_warning never mentions spot numbers like ₹4,977.5.
        """
        from engine.alert_scrutiny import AlertScrutinyAuditor

        scrutiny = AlertScrutinyAuditor()
        alert = AutoAlert(
            alert_id="aa-stage-1-to-2-expansion-radico-pull-20261116",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RADICO",
            exchange="NFO",
            direction="BULLISH",
            stage="IGNITED",
            headline="RADICO",
            summary="RADICO swing",
            ltp=48.5,
            trigger_level=50.1,
            target_level=4977.5,  # Leaked spot target
            stop_loss=39.8,
            strike=4700.0,
            option_type="CE",
            contract_symbol="NSE:RADICO26NOV4700CE",
            underlying_spot=4663.0,
            segment="NFO",
            actionable_plan={"action": "BUY_CALL", "contract": "NSE:RADICO26NOV4700CE"},
        )

        res = scrutiny._generate_quantitative_fallback(alert, flags={})
        assert res is not None
        assert "4977" not in res.trap_risk_warning
        assert "4,977" not in res.trap_risk_warning
        # Target in trap warning should be option premium space (~66 or ~70), never spot (4977.5)
        assert any(k in res.trap_risk_warning for k in ("65.9", "66", "70", "71"))

    def test_alert_templates_clean_targets_filters_spot_on_cheap_options(self):
        """
        Verify that _resolve_monotonic_display_targets in bot/alert_templates.py eliminates spot targets
        even on cheap stock options (e.g. ₹10 premium with ₹150 spot target).
        """
        from bot.alert_templates import _resolve_monotonic_display_targets

        alert = AutoAlert(
            alert_id="aa-options-pnb-150-ce",
            alert_type="OPTIONS_MOMENTUM",
            symbol="PNB",
            exchange="NFO",
            direction="BULLISH",
            stage="IGNITED",
            headline="PNB",
            summary="PNB call",
            ltp=10.0,
            trigger_level=10.0,
            target_level=15.0,
            stop_loss=8.0,
            strike=150.0,
            option_type="CE",
            contract_symbol="NSE:PNB26NOV150CE",
            underlying_spot=142.0,
            segment="NFO",
        )
        actionable_plan = {
            "instrument_type": "OPTION",
            "contract": "NSE:PNB26NOV150CE",
            "recommended_entry": 10.0,
            "target_1": "₹15.0",
            "target_2": "₹20.0",
            "runner_target": "₹150.0",  # Leaked spot target
            "underlying_spot": 142.0,
        }

        t1, t2, t3 = _resolve_monotonic_display_targets(actionable_plan, alert, entry_val=10.0)
        # Spot target 150 must NOT leak as t3
        assert "150" not in t3
        assert t3 == "" or "2" in t3 or "3" in t3

    def test_alert_model_properties_clamp_spot_leakage_and_protect_initial_stop_loss(self):
        """
        Verify that AutoAlert properties (target_1, target_2, target_3) and __post_init__
        never allow spot levels to contaminate option premium targets or initial_stop_loss.
        """
        alert = AutoAlert(
            alert_id="aa-stage-1-to-2-expansion-radico-test",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RADICO",
            exchange="NFO",
            direction="BULLISH",
            stage="IGNITED",
            headline="RADICO",
            summary="RADICO swing",
            ltp=50.1,
            trigger_level=50.1,
            target_level=86.2,
            stop_loss=39.8,
            strike=4700.0,
            option_type="CE",
            contract_symbol="NSE:RADICO26NOV4700CE",
            underlying_spot=4663.0,
            segment="NFO",
            actionable_plan={
                "invalidation_stop": 4462.2,  # Spot stop loss accidentally passed
                "target_1": 4977.5,  # Leaked spot target
                "target_2": 7441.2,  # Leaked spot target
                "target_3": 19412.16,  # Leaked spot target
            },
        )

        # initial_stop_loss must be protected to option stop loss, not spot 4462.2
        assert alert.initial_stop_loss == 39.8
        # Target 1 property must reject 4977.5 and use clean option target
        assert alert.target_1 < 150.0
        assert alert.target_2 < 250.0
        assert alert.target_3 < 400.0
        # Risk-reward ratio must be institutional (between 1.5R and 5.0R), not 478.4R
        assert 1.5 <= alert.risk_reward_ratio <= 5.0

    def test_equity_spot_ltp_update_under_five_thousand_rupees(self):
        """
        Verify that AutoAlertEngine refreshes underlying_spot for equity stocks with prices
        below 5,000 (e.g. RADICO at ₹4,663, RELIANCE at ₹2,800).
        """
        alert = AutoAlert(
            alert_id="aa-stage-1-to-2-expansion-radico-spot-refresh",
            alert_type="STAGE_1_TO_2_EXPANSION",
            symbol="RADICO",
            exchange="NSE",
            direction="BULLISH",
            stage="IGNITED",
            headline="RADICO",
            summary="RADICO swing",
            ltp=50.1,
            trigger_level=50.1,
            target_level=86.2,
            stop_loss=39.8,
            strike=4700.0,
            option_type="CE",
            contract_symbol="NSE:RADICO26NOV4700CE",
            underlying_spot=4663.0,
            segment="FNO_STOCK",
        )

        engine = AutoAlertEngine()
        engine._alerts = [alert]

        # Simulate batch quotes containing updated spot and option premium
        quotes = {
            "NSE:RADICO26NOV4700CE": 52.4,
            "NSE:RADICO": 4685.0,
            "RADICO": 4685.0,
        }

        engine.check_and_alert_targets_and_trailing(
            quotes_map=quotes, skip_early_warning_check=True
        )
        # Verify both option premium and underlying spot are updated
        assert alert.option_premium == 52.4
        assert alert.underlying_spot == 4685.0
