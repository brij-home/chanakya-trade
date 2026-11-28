"""
tests/test_rca_limit_pullback_and_day_extreme_rebound.py
────────────────────────────────────────────────────────
Institutional Regression & Invariant Test Suite for Postmortem RCA (2026-10-30):
1. Limit on Pullback Adverse Slip Protection (> 5% slip disqualified).
2. Minimum Risk Runway / Buffer to Stop-Loss (> 8% or 25 pts cushion enforced).
3. Honest Stage Promotion Headline (limit filled vs crossed).
4. Day Low Demand Absorption / Rebound Suppression of fake DAY_LOW_PROXIMITY.
5. Tiger Stalking Restoration (VWAP oscillation does NOT bypass chop filter).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from config.constants import IST_ZONE as IST


class TestLimitPullbackAdverseSlipAndRiskCushion:
    """Tests for AutoAlertEngine limit pullback execution safety guards."""

    def test_adverse_slip_disqualifies_limit_entry(self):
        """
        RCA: When SENSEX 74200 PE had a limit trigger at ₹625.20, but market price
        collapsed to ₹559.39 (-10.5% below trigger), it was mistakenly ignited.
        Fix: Any slip > 5.0% below trigger must be marked EXPIRED (Adverse Momentum Slip).
        """
        engine = AutoAlertEngine()
        contract_sym = "BFO:SENSEX26NOV74200PE"
        alert = AutoAlert(
            alert_id="test-aa-put-slip-rca",
            symbol="SENSEX",
            exchange="BFO",
            segment="FNO_INDEX",
            alert_type="INDEX_PUT_SETUP",
            stage="PRIMED",
            direction="BEARISH",
            headline="SENSEX 74200 PE Primed",
            summary="Testing adverse slip guard",
            ltp=625.20,
            trigger_level=625.20,
            stop_loss=530.20,
            target_level=815.20,
            strike=74200.0,
            option_type="PE",
            contract_symbol=contract_sym,
            entry_type="LIMIT_ON_PULLBACK",
            actionable_plan={"execution_trigger": "LIMIT_ON_PULLBACK_OTE"},
            metrics={},
            is_live=True,
            environment="LIVE",
        )
        engine._alerts = [alert]

        lookup = engine._lookup_sym(alert)
        # 559.39 is > 5% slip below 625.20 (adversely broken down)
        ignited = engine.check_and_ignite_early_warnings(quotes_map={lookup: 559.39})

        # Must NOT ignite! Must be disqualified as EXPIRED due to Adverse Momentum Slip
        assert len(ignited) == 0, "Adverse slip > 5% must NOT be ignited"
        assert alert.stage == "EXPIRED"
        assert alert.is_invalidated is True
        assert "Adverse Momentum Slip" in alert.invalidation_reason

    def test_insufficient_risk_cushion_holds_ignition(self):
        """
        RCA: Even if within 5% of trigger, entering with only 15 points cushion to SL
        guarantees an instant stop-out on routine index noise.
        Fix: Minimum remaining buffer of max(8% of LTP, 25 pts) enforced before limit fill.
        """
        engine = AutoAlertEngine()
        contract_sym = "BFO:SENSEX26NOV74200PE"
        alert = AutoAlert(
            alert_id="test-aa-put-cushion-rca",
            symbol="SENSEX",
            exchange="BFO",
            segment="FNO_INDEX",
            alert_type="INDEX_PUT_SETUP",
            stage="PRIMED",
            direction="BEARISH",
            headline="SENSEX 74200 PE Primed",
            summary="Testing risk cushion guard",
            ltp=600.0,
            trigger_level=600.0,
            stop_loss=585.0,  # Buffer = 15 pts < min 25 pts
            target_level=800.0,
            strike=74200.0,
            option_type="PE",
            contract_symbol=contract_sym,
            entry_type="LIMIT_ON_PULLBACK",
            actionable_plan={"execution_trigger": "LIMIT_ON_PULLBACK"},
            metrics={},
            is_live=True,
            environment="LIVE",
        )
        engine._alerts = [alert]

        lookup = engine._lookup_sym(alert)
        # Price at 598.0 (within 5% slip, but buffer to SL 585 is only 13 pts < 25 pts)
        ignited = engine.check_and_ignite_early_warnings(quotes_map={lookup: 598.0})

        assert len(ignited) == 0, "Insufficient risk cushion must hold ignition"
        assert alert.stage == "PRIMED"  # Remains in primed surveillance, not blown out

    def test_honest_headline_distinguishes_limit_fill_from_cross(self):
        """
        RCA: When limit order filled at ₹559, headline falsely claimed 'crossed ₹625.2'.
        Fix: Limit fills must explicitly state 'limit filled at ₹X.X (Plan: ₹Y.Y)'.
        """
        engine = AutoAlertEngine()
        contract_sym = "BFO:SENSEX26NOV74200PE"
        alert = AutoAlert(
            alert_id="test-aa-put-honest-hl",
            symbol="SENSEX",
            exchange="BFO",
            segment="FNO_INDEX",
            alert_type="INDEX_PUT_SETUP",
            stage="PRIMED",
            direction="BEARISH",
            headline="SENSEX 74200 PE Primed",
            summary="Testing headline truthfulness",
            ltp=620.0,
            trigger_level=620.0,
            stop_loss=520.0,
            target_level=800.0,
            strike=74200.0,
            option_type="PE",
            contract_symbol=contract_sym,
            entry_type="LIMIT_ON_PULLBACK",
            actionable_plan={"execution_trigger": "LIMIT_ON_PULLBACK"},
            metrics={},
            is_live=True,
            environment="LIVE",
        )
        engine._alerts = [alert]

        lookup = engine._lookup_sym(alert)
        # Price at 610.0 (favorable limit pullback within 5%, buffer to SL = 90 pts > 25)
        with patch.object(engine, "_dispatch"):
            ignited = engine.check_and_ignite_early_warnings(quotes_map={lookup: 610.0})

        assert len(ignited) == 1
        assert "limit filled at ₹610.0" in alert.headline
        assert "crossed" not in alert.headline


class TestDayExtremeReboundAndRegimeGates:
    """Tests for day extreme rebound detection and adaptive regime discipline."""

    def test_day_low_rebound_suppresses_fake_day_low_proximity(self):
        """
        RCA: SENSEX printed a hammer at 74,082 and bounced +100 pts to 74,182.
        Because 74,182 was within -0.13% of Day Low, DAY_LOW_PROXIMITY fired.
        Fix: If price hit Day Low and latest candles are green and rising away,
        suppress DAY_LOW_PROXIMITY.
        """
        from engine.detectors.index_put_setup import detect_index_put_setup

        dates = pd.date_range("2026-10-30 10:30", periods=8, freq="5min")
        df_bounce = pd.DataFrame(
            {
                "open": [74150, 74120, 74090, 74085, 74110, 74140, 74160, 74175],
                "high": [74160, 74130, 74100, 74110, 74145, 74165, 74185, 74190],
                "low": [74110, 74085, 74082, 74082, 74105, 74135, 74155, 74170],
                "close": [74120, 74090, 74085, 74110, 74140, 74160, 74175, 74182],
                "volume": [1000, 1500, 3000, 2500, 2000, 1800, 1600, 1400],
            },
            index=dates,
        )

        quotes_map = {
            "SENSEX": MagicMock(
                last_price=74182.0,
                open=74199.0,
                high=74422.0,
                low=74082.0,  # Day Low
                close=74151.0,
                volume=50000,
                vwap=74243.0,
            )
        }

        opt_chain = [
            {
                "strike": 74200.0,
                "option_type": "PE",
                "ltp": 560.0,
                "volume": 25000,
                "oi": 80000,
                "symbol": "SENSEX26NOV74200PE",
                "pchange": 5.0,
            }
        ]

        alerts = detect_index_put_setup(
            underlying="SENSEX",
            spot=74182.0,
            chain=opt_chain,
            vwap=74243.0,
            day_high=74422.0,
            day_low=74082.0,
            prev_day_high=74200.0,
            prev_day_low=73800.0,
            ohlcv_5m=df_bounce,
            ref_time=datetime(2026, 10, 30, 10, 42, tzinfo=IST),
            quotes_map=quotes_map,
        )

        # Alerts should NOT include DAY_LOW_PROXIMITY because price is actively rebounding
        for a in alerts:
            sigs = a.metrics.get("signals", [])
            assert "DAY_LOW_PROXIMITY" not in sigs, (
                f"DAY_LOW_PROXIMITY must be suppressed during demand absorption bounce off Day Low, got {sigs}"
            )

    def test_tiger_stalking_not_bypassed_by_vwap_cross(self):
        """
        RCA: Routine slip below VWAP was classified as 'structural_breakdowns',
        bypassing Tiger Stalking capital preservation in chop.
        Fix: VWAP_BREAKDOWN_PE removed from structural_breakdowns.
        """
        from engine.detectors.index_put_setup import detect_index_put_setup

        dates = pd.date_range("2026-10-30 11:35", periods=10, freq="5min")
        df_chop = pd.DataFrame(
            {
                "open": [74220] * 10,
                "high": [74235] * 10,
                "low": [74205] * 10,
                "close": [74215] * 10,
                "volume": [800] * 10,
            },
            index=dates,
        )

        quotes_map = {
            "SENSEX": MagicMock(
                last_price=74215.0,
                open=74220.0,
                high=74350.0,
                low=74100.0,
                close=74220.0,
                volume=10000,
                vwap=74230.0,
            )
        }

        opt_chain = [
            {
                "strike": 74200.0,
                "option_type": "PE",
                "ltp": 250.0,
                "volume": 5000,
                "oi": 50000,
                "symbol": "SENSEX26NOV74200PE",
                "pchange": 1.0,
            }
        ]

        alerts = detect_index_put_setup(
            underlying="SENSEX",
            spot=74215.0,
            chain=opt_chain,
            vwap=74230.0,
            day_high=74350.0,
            day_low=74100.0,
            prev_day_high=74300.0,
            prev_day_low=74000.0,
            ohlcv_5m=df_chop,
            ref_time=datetime(2026, 10, 30, 11, 45, tzinfo=IST),
            quotes_map=quotes_map,
        )

        assert len(alerts) == 0, "Tiger Stalking must suppress routine VWAP slip in midday chop"


def test_ignited_summary_strips_pre_breakdown_watchlist_boilerplate():
    """PRIMED -> IGNITED promotion must strip stale watchlist staging instructions from Reason/summary."""
    engine = AutoAlertEngine()
    contract_sym = "BFO:SENSEX26D0383700PE"
    alert = AutoAlert(
        alert_id="test-aa-ignited-strip",
        symbol="SENSEX",
        exchange="BFO",
        segment="FNO_INDEX",
        alert_type="INDEX_PUT_SETUP",
        stage="PRIMED",
        direction="BEARISH",
        headline="SENSEX 83700 PE Primed",
        summary=(
            "Pre-Breakdown Proximity Watch: Spot (₹83,634.8) approaching Session Low (₹83,547.1, 0.10% above). "
            "Stage contract now in broker watchlist to capture immediate momentum on breakdown. "
            "Entry Trigger: Spot ₹83,547.1 (Est. Prem ₹776.0)"
        ),
        ltp=776.0,
        trigger_level=776.0,
        stop_loss=682.6,
        target_level=962.9,
        strike=83700.0,
        option_type="PE",
        contract_symbol=contract_sym,
        entry_type="LIMIT_ON_PULLBACK",
        actionable_plan={
            "execution_trigger": "LIMIT_ON_PULLBACK_OTE",
            "when_to_buy": (
                "⚡ Pre-Breakdown Proximity: Stage contract in broker terminal now. "
                "Place pending BUY SL-LIMIT or execute when spot crosses below Session Low (₹83,547.1). "
                "Invalidation stop anchored at ₹682.6."
            ),
        },
        metrics={},
        is_live=True,
        environment="LIVE",
    )
    engine._alerts = [alert]

    lookup = engine._lookup_sym(alert)
    with patch.object(engine, "_dispatch"):
        ignited = engine.check_and_ignite_early_warnings(quotes_map={lookup: 766.1})

    assert len(ignited) == 1
    assert "Confirmed put breakdown past ₹776.0 (Live ₹766.1)" in alert.summary
    assert "Pre-Breakdown Proximity Watch" not in alert.summary
    assert "broker watchlist" not in alert.summary
    assert "Entry Trigger:" not in alert.summary
    assert "Stage contract in broker terminal now" not in alert.actionable_plan["when_to_buy"]


def test_range_entry_uses_plan_anchor_for_rr_and_lot_risk():
    """OTE entry brackets (₹745.0 – ₹787.7) must compute R:R and Risk/lot from plan/CMP, not extreme lower bound."""
    from bot.alert_templates import render_auto_alert

    alert = AutoAlert(
        alert_id="test-aa-range-rr",
        symbol="SENSEX",
        exchange="BFO",
        segment="FNO_INDEX",
        alert_type="INDEX_PUT_SETUP",
        stage="IGNITED",
        direction="BEARISH",
        headline="🔴 🔥 PUT BREAKDOWN IGNITED: SENSEX 83700 PE (Lot: 20) limit filled at ₹766.1 (Plan: ₹776.0)",
        summary="Confirmed put breakdown past ₹776.0 (Live ₹766.1).",
        ltp=776.05,
        trigger_level=776.0,
        stop_loss=682.6,
        target_level=962.9,
        strike=83700.0,
        option_type="PE",
        contract_symbol="BFO:SENSEX26D0383700PE",
        expiry_date="2026-12-03",
        lot_size=20,
        option_premium=776.05,
        option_stop_loss=682.6,
        underlying_spot=83634.8,
        structural_spot_sl=83811.1,
        time_horizon="INTRADAY",
        actionable_plan={
            "action": "BUY PE",
            "entry_range": "₹745.0 – ₹787.7",
            "recommended_entry": "₹745.0 – ₹787.7",
            "stop_loss": "₹682.60",
            "target_1": "₹962.9",
            "target_2": "₹1,075.1",
            "target_3": "₹1,187.3",
            "lot_size": 20,
            "risk_reward": "1:2.0",
        },
        is_live=True,
        environment="LIVE",
    )

    rendered = render_auto_alert(alert, in_market=True)
    assert "R:R:</b> <b>1:2.0</b>" in rendered
    assert "1:3.5" not in rendered
    assert "Risk: ₹1,869/lot" in rendered
    assert "Risk: ₹1,248/lot" not in rendered


def test_index_put_setup_never_fabricates_rvol_from_voi():
    """INDEX_PUT_SETUP must never synthesize a 10x V/OI RVOL metric (e.g. 254.7x when V/OI=25.5x)."""
    from pathlib import Path

    src = Path("engine/detectors/index_put_setup.py").read_text(encoding="utf-8")
    assert "oi * 0.1" not in src
