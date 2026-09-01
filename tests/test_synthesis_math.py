"""
tests/test_synthesis_math.py
─────────────────────────────
Comprehensive unit tests for mathematical accuracy in synthesis trade setups:
- Verified 2.0R and 3.5R target calculations (Long & Short)
- Specific regression test for BAJAJ_AUTO levels
- Prevention of nearby minor resistance truncating target calculations
- Zero-hallucination post-validation layer
"""

from agent.multi_agent import AnalystReport, MultiAgentAnalyzer
from agent.schema_parser import parse_synthesis_output
from engine.trader import TraderAgent


def _make_reports(
    ltp: float,
    support: float,
    resistance: float,
    atr: float = 0.0,
    verdict: str = "BUY",
    score: float = 45.0,
) -> list[AnalystReport]:
    """Helper to build synthetic analyst reports."""
    tech_data = {
        "ltp": ltp,
        "close": ltp,
        "support": support,
        "resistance": resistance,
        "atr": atr,
        "rsi": 58.5,
    }
    return [
        AnalystReport(
            analyst="Technical",
            verdict="BULLISH"
            if "BUY" in verdict
            else "BEARISH"
            if "SELL" in verdict
            else "NEUTRAL",
            confidence=75,
            score=score,
            key_points=[
                "RSI in bullish zone",
                f"Support at {support}",
                f"Resistance at {resistance}",
            ],
            data=tech_data,
        ),
        AnalystReport(
            analyst="Fundamental",
            verdict="BULLISH"
            if "BUY" in verdict
            else "BEARISH"
            if "SELL" in verdict
            else "NEUTRAL",
            confidence=80,
            score=score,
            key_points=["ROE > 18%", "Strong balance sheet"],
            data={"roe": 19.5, "pe": 24.0},
        ),
    ]


class TestSynthesisMath:
    """Test mathematical precision in deterministic synthesis."""

    def test_bajaj_auto_trade_setup_math(self):
        """
        Verify that BAJAJ_AUTO (LTP: 11991.00, Support: 11794.67, Resistance: 11999.67)
        computes mathematically accurate 2.0R (12383.66) and 3.5R (12678.16) targets.
        """
        analyzer = MultiAgentAnalyzer.__new__(MultiAgentAnalyzer)
        reports = _make_reports(
            ltp=11991.00,
            support=11794.67,
            resistance=11999.67,
            atr=150.0,
            verdict="BUY",
            score=50.0,
        )

        synthesis = analyzer._build_deterministic_synthesis(
            symbol="BAJAJ-AUTO",
            exchange="NSE",
            reports=reports,
            winner="BULL",
        )

        parsed = parse_synthesis_output(synthesis)
        assert parsed.verdict in ("BUY", "STRONG_BUY")

        # Check raw text values
        assert "₹11,991.00" in synthesis
        assert "₹11,794.67" in synthesis

        # Target 1 must be strictly Entry + 2.0 * Risk = 11991 + 2 * (11991 - 11794.67) = 12383.66
        assert "₹12,383.66" in synthesis
        # Target 2 must be strictly Entry + 3.5 * Risk = 11991 + 3.5 * (11991 - 11794.67) = 12678.15 / 12678.16
        assert "₹12,678.15" in synthesis or "₹12,678.16" in synthesis

        # Ensure the flawed values are NOT present
        assert "11,999.67 (2R)" not in synthesis
        assert "12,004.00 (3.5R)" not in synthesis

    def test_short_setup_directionality_and_targets(self):
        """
        Verify that Short/SELL setups have Stop-Loss ABOVE entry and targets BELOW entry.
        """
        analyzer = MultiAgentAnalyzer.__new__(MultiAgentAnalyzer)
        reports = _make_reports(
            ltp=2500.00,
            support=2400.00,
            resistance=2560.00,  # 60 pts risk
            atr=35.0,
            verdict="SELL",
            score=-55.0,
        )

        synthesis = analyzer._build_deterministic_synthesis(
            symbol="TATAMOTORS",
            exchange="NSE",
            reports=reports,
            winner="BEAR",
        )

        parsed = parse_synthesis_output(synthesis)
        assert parsed.verdict in ("SELL", "STRONG_SELL")

        # Stop-Loss must be above entry (2560.00)
        assert "₹2,560.00" in synthesis
        # Target 1 must be Entry - 2.0 * 60 = 2380.00
        assert "₹2,380.00" in synthesis
        # Target 2 must be Entry - 3.5 * 60 = 2290.00
        assert "₹2,290.00" in synthesis

    def test_rangebound_hold_does_not_generate_fake_buy(self):
        """
        Verify that HOLD / neutral setups state range boundaries without fake execution buy tickets.
        """
        analyzer = MultiAgentAnalyzer.__new__(MultiAgentAnalyzer)
        reports = _make_reports(
            ltp=1500.00,
            support=1460.00,
            resistance=1540.00,
            atr=20.0,
            verdict="HOLD",
            score=0.0,
        )

        synthesis = analyzer._build_deterministic_synthesis(
            symbol="INFY",
            exchange="NSE",
            reports=reports,
            winner="NEUTRAL",
        )

        assert "VERDICT: HOLD" in synthesis
        assert "RANGE_BOUND / STAND_DOWN" in synthesis
        assert "Await Breakout" in synthesis


class TestSynthesisValidationLayer:
    """Test the zero-hallucination post-validation layer."""

    def test_detects_and_fixes_inverted_long_stop_loss(self):
        """If an LLM returns a BUY verdict with Stop Loss above Entry, it must be auto-corrected."""
        analyzer = MultiAgentAnalyzer.__new__(MultiAgentAnalyzer)
        reports = _make_reports(
            ltp=1000.00,
            support=970.00,
            resistance=1050.00,
            atr=15.0,
            verdict="BUY",
            score=45.0,
        )

        hallucinated_text = """\
VERDICT: BUY
CONFIDENCE: 80%
WINNER: BULL

TRADE RECOMMENDATION:
Strategy  : Long Delivery
Entry     : ₹1,000.00
Stop-Loss : ₹1,080.00 (+8.0%)
Target 1  : ₹950.00 (-5.0%)
R:R Ratio : Inverted

RATIONALE (3 bullets):
- Hallucinated analysis
"""
        calibrated = analyzer._validate_and_calibrate_synthesis(
            hallucinated_text, "TEST", "NSE", reports, "BULL"
        )

        # Corrupt levels must have been replaced with valid math
        assert "₹970.00" in calibrated  # Valid SL
        assert "₹1,060.00" in calibrated  # Valid 2.0R target (1000 + 2*30)

    def test_trader_agent_exit_plan_not_collapsed_by_minor_resistance(self):
        """
        Verify TraderAgent does not collapse T1 to nearby resistance when resistance is < 1.5R.
        """
        trader = TraderAgent()
        strategy = {"direction": "LONG", "timeframe": "SWING"}
        sizing = {"sl_distance": 196.33}

        exit_plan = trader._build_exit_plan(
            strategy=strategy,
            ltp=11991.00,
            atr=150.0,
            sizing=sizing,
            support=11794.67,
            resistance=11999.67,  # Only 8.67 pts away (< 1.5R)
            vix_factor=1.0,
        )

        # Target 1 should be calculated with full t1_rr (1.5x to 2.0x), not capped to 11999.67
        assert exit_plan.target_1 > 12200.00
        assert exit_plan.target_1 != 11999.67
