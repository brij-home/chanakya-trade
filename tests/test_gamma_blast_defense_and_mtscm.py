"""
tests/test_gamma_blast_defense_and_mtscm.py
───────────────────────────────────────────
Deterministic regression tests for:
1. Index Put Gamma Blast: Rejection of OTM Puts with positive ΔOI (institutional support writing).
2. Index Call Gamma Blast: Rejection of OTM Calls with positive ΔOI (institutional resistance writing).
3. Universal Options Symmetry: Allowing true writer capitulation (negative ΔOI on ATM/ITM).
4. Institutional Quality Gate: Ensuring DEFENSIVE_CAUTION (<70 MTSCM) downgrades to DEFINED_RISK_ONLY.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone, timedelta
from unittest.mock import patch


from engine.detectors.gamma_blast import detect_gamma_blast
from engine.quality_gate import evaluate_institutional_quality_gate
from engine.alert_model import AutoAlert
from engine.mtscm import MTSCMResult

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class MockContract:
    symbol: str
    underlying: str
    strike: float
    option_type: str  # "CE" | "PE"
    last_price: float
    oi: int
    oi_change: int
    volume: int
    expiry: str = "2026-10-29"
    high: float = 350.0
    low: float = 250.0
    pchange: float = 8.0
    bid: float = 345.0
    ask: float = 347.0


class TestGammaBlastWriterDefenseAndSymmetry:
    """Tests that institutional writing walls (positive ΔOI on OTM strikes) are suppressed."""

    def test_otm_index_pe_with_positive_oi_is_rejected_as_support_writing(self):
        """
        SENSEX Spot: 73,344.45
        Strike: 73,000 PE (344 pts OTM)
        ΔOI: +108,480 (Put writers aggressively adding supply to defend support)
        Result: Must be REJECTED, not alerted as a long gamma blast.
        """
        spot = 73344.45
        vwap = 73395.50

        chain = [
            MockContract(
                symbol="BSE:SENSEX26OCT73000PE",
                underlying="SENSEX",
                strike=73000.0,
                option_type="PE",
                last_price=346.90,
                oi=800000,
                oi_change=108480,  # Positive ΔOI (Put writing wall defense)
                volume=1500000,
                expiry="2026-10-29",
            )
        ]

        alerts = detect_gamma_blast("SENSEX", spot=spot, chain=chain, vwap=vwap, day_low=73342.0)
        assert len(alerts) == 0, "OTM Put with positive ΔOI must be suppressed as support writing"

    def test_atm_index_pe_with_writer_capitulation_is_allowed(self):
        """
        SENSEX Spot: 73,344.45
        Strike: 73,300 PE (ATM, near spot)
        ΔOI: -45,000 (Writers panic unwinding / covering)
        Result: Must be ALLOWED as a genuine Put Gamma Blast.
        """
        spot = 73344.45
        vwap = 73395.50

        chain = [
            MockContract(
                symbol="BSE:SENSEX26OCT73300PE",
                underlying="SENSEX",
                strike=73300.0,
                option_type="PE",
                last_price=420.0,
                oi=500000,
                oi_change=-45000,  # Negative ΔOI (True capitulation)
                volume=800000,
                expiry="2026-10-29",
            )
        ]

        alerts = detect_gamma_blast("SENSEX", spot=spot, chain=chain, vwap=vwap, day_low=73342.0)
        assert len(alerts) >= 1
        assert alerts[0].option_type == "PE"
        assert alerts[0].strike == 73300.0

    def test_otm_index_ce_with_positive_oi_is_rejected_as_resistance_writing(self):
        """
        Universal Options Symmetry (Bull Counterpart):
        SENSEX Spot: 73,344.45
        Strike: 73,700 CE (355 pts OTM)
        ΔOI: +95,000 (Call writers adding resistance ceiling)
        Result: Must be REJECTED, not alerted as a long call gamma blast.
        """
        spot = 73344.45
        vwap = 73300.0  # Spot is above VWAP

        chain = [
            MockContract(
                symbol="BSE:SENSEX26OCT73700CE",
                underlying="SENSEX",
                strike=73700.0,
                option_type="CE",
                last_price=310.0,
                oi=750000,
                oi_change=95000,  # Positive ΔOI (Call writing ceiling)
                volume=1200000,
                expiry="2026-10-29",
            )
        ]

        alerts = detect_gamma_blast("SENSEX", spot=spot, chain=chain, vwap=vwap, day_high=73360.0)
        assert len(alerts) == 0, (
            "OTM Call with positive ΔOI must be suppressed as resistance writing"
        )

    def test_atm_index_ce_with_writer_capitulation_is_allowed(self):
        """
        Universal Options Symmetry (Bull Counterpart):
        SENSEX Spot: 73,344.45
        Strike: 73,400 CE (ATM)
        ΔOI: -55,000 (Call writers covering in panic)
        Result: Must be ALLOWED as a genuine Call Gamma Blast.
        """
        spot = 73344.45
        vwap = 73300.0

        chain = [
            MockContract(
                symbol="BSE:SENSEX26OCT73400CE",
                underlying="SENSEX",
                strike=73400.0,
                option_type="CE",
                last_price=390.0,
                oi=600000,
                oi_change=-55000,  # Negative ΔOI (True capitulation)
                volume=950000,
                expiry="2026-10-29",
            )
        ]

        alerts = detect_gamma_blast("SENSEX", spot=spot, chain=chain, vwap=vwap, day_high=73360.0)
        assert len(alerts) >= 1
        assert alerts[0].option_type == "CE"
        assert alerts[0].strike == 73400.0


class TestQualityGateMTSCMIntegrity:
    """Tests that DEFENSIVE_CAUTION or DEFENSIVE_VETO MTSCM blocks APEX_CONFLUENCE."""

    def test_defensive_caution_downgrades_apex_to_defined_risk_only(self):
        """
        When confidence is 98-100%, but MTSCM evaluates to DEFENSIVE_CAUTION (Score 60.0),
        Quality Gate must NOT grant APEX_CONFLUENCE or STANDARD mandate.
        Must downgrade to DEFINED_RISK_ONLY with HEDGED_SPREAD_MANDATORY.
        """
        alert = AutoAlert(
            alert_id="TEST-SENSEX-QG-01",
            alert_type="GAMMA_BLAST",
            stage="EARLY_WARNING",
            exchange="BFO",
            headline="SENSEX 73000 PE",
            summary="Put volume surge",
            ltp=346.90,
            symbol="SENSEX",
            direction="BEARISH",
            trigger_level=346.90,
            stop_loss=290.48,
            target_level=459.70,
            confidence=98,
            environment="LIVE",
            is_live=True,
            actionable_plan={"target_2": 544.40},
        )

        fake_mtscm = MTSCMResult(
            symbol="SENSEX",
            direction="BEARISH",
            total_score=60.0,
            tier="DEFENSIVE_CAUTION",
            lot_multiplier=0.85,
            htf_score=24.0,
            itf_score=19.0,
            ltf_score=17.0,
            confluences=["Holding firmly below VWAP"],
            headwinds=[],
            summary="MTSCM Score: 60.0/100 [DEFENSIVE_CAUTION]",
        )

        with patch("engine.mtscm.evaluate_mtscm", return_value=fake_mtscm):
            verdict = evaluate_institutional_quality_gate(alert)

            assert verdict.conviction_tier == "DEFINED_RISK_ONLY", (
                f"Expected DEFINED_RISK_ONLY, got {verdict.conviction_tier}"
            )
            assert verdict.execution_mandate == "HEDGED_SPREAD_MANDATORY", (
                f"Expected HEDGED_SPREAD_MANDATORY, got {verdict.execution_mandate}"
            )
            assert verdict.metrics["confidence"] <= 75, "Confidence should be clamped to <= 75%"
            assert "MTSCM Downgrade" in verdict.coaching_notes[0]
