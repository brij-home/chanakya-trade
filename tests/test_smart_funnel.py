"""
tests/test_smart_funnel.py
──────────────────────────
Unit tests for the Institutional Smart Funnel 3-stage screener and debate pipeline.
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.smart_funnel import (
    SmartFunnel,
    PreFilterReport,
    TradePlanSummary,
    SmartFunnelResult,
    WATCHLIST_PRESETS,
)


class TestSmartFunnelPresets:
    """Test watchlist presets and normalization."""

    def test_presets_exist(self):
        assert "nifty50" in WATCHLIST_PRESETS
        assert "nifty_it" in WATCHLIST_PRESETS
        assert "nifty_bank" in WATCHLIST_PRESETS
        assert len(WATCHLIST_PRESETS["nifty50"]) == 50
        assert "INFY" in WATCHLIST_PRESETS["nifty_it"]
        assert "HDFCBANK" in WATCHLIST_PRESETS["nifty_bank"]


class TestQuantPreFilter:
    """Test pure Python quantitative pre-filtering."""

    def test_evaluate_stock_quant_bullish(self):
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = lambda tool, args: {
            "technical_analyse": {
                "ltp": 1500.0,
                "rsi": 54.0,
                "ema20": 1480.0,
                "ema50": 1450.0,
                "sma200": 1400.0,
                "macd_hist": 2.5,
                "volume_ratio": 1.2,
            },
            "fundamental_analyse": {
                "pe": 22.0,
                "roe": 25.0,
                "debt_to_equity": 0.05,
                "revenue_growth_3y": 15.0,
                "free_cash_flow": 1200.0,
            },
        }.get(tool, {})

        funnel = SmartFunnel(registry=mock_registry, verbose=False)
        report = funnel.evaluate_stock_quant("TESTSYM")

        assert isinstance(report, PreFilterReport)
        assert report.symbol == "TESTSYM"
        assert report.qualified is True
        assert report.score >= 75.0
        assert "RSI" in report.pass_reason
        assert report.metrics["roe"] == 25.0 and ("ROE" in report.pass_reason or "RSI" in report.pass_reason)

    def test_evaluate_stock_quant_rejected_overbought_and_overleveraged(self):
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = lambda tool, args: {
            "technical_analyse": {
                "ltp": 500.0,
                "rsi": 82.0,  # Overbought
                "ema20": 480.0,
                "ema50": 510.0,  # Downtrend
                "sma200": 600.0,  # Deep below 200DMA
                "macd_hist": -5.0,
                "volume_ratio": 0.2,  # Anemic
            },
            "fundamental_analyse": {
                "pe": 120.0,  # Extreme
                "roe": 2.0,   # Anemic
                "debt_to_equity": 3.5,  # Overleveraged
            },
        }.get(tool, {})

        funnel = SmartFunnel(registry=mock_registry, verbose=False)
        report = funnel.evaluate_stock_quant("BADSYM")

        assert report.qualified is False
        assert report.score < 40.0
        assert "overbought" in report.rejection_reason or "200-DMA" in report.rejection_reason or "D/E" in report.rejection_reason

    def test_run_pre_filter_batch_sorting(self):
        mock_registry = MagicMock()

        def side_effect(tool, args):
            sym = args.get("symbol", "")
            if sym == "GOOD":
                return {
                    "rsi": 52.0, "ema20": 100, "ema50": 90, "sma200": 80, "roe": 20.0, "debt_to_equity": 0.1
                }
            return {
                "rsi": 85.0, "ema20": 50, "ema50": 60, "sma200": 80, "roe": 1.0, "debt_to_equity": 4.0
            }

        mock_registry.execute.side_effect = side_effect
        funnel = SmartFunnel(registry=mock_registry, verbose=False)
        reports = funnel.run_pre_filter_batch(["BAD", "GOOD"])

        assert len(reports) == 2
        assert reports[0].symbol == "GOOD"
        assert reports[0].score > reports[1].score

    def test_fallback_selection_when_zero_qualified(self):
        mock_registry = MagicMock()
        mock_registry.execute.side_effect = lambda tool, args: {
            "rsi": 85.0, "ema20": 50, "ema50": 60, "sma200": 80, "roe": 1.0, "debt_to_equity": 4.0
        }
        with patch.object(SmartFunnel, "_get_providers", return_value=(None, None)):
            funnel = SmartFunnel(registry=mock_registry, verbose=False)
            res = funnel.run(symbols=["BAD1", "BAD2"], top_n=1)
            assert res.qualified_count == 0
            assert res.is_fallback_selection is True
            assert len(res.candidate_symbols) == 1


class TestSynthesisParser:
    """Test parsing Fund Manager synthesis text."""

    def test_parse_synthesis_output_structured(self):
        funnel = SmartFunnel(verbose=False)
        text = """
VERDICT: BUY
CONFIDENCE: 82%
WINNER: BULL

TRADE RECOMMENDATION:
Strategy  : Buy on Pullback (CNC)
Entry     : ₹1,510 - ₹1,530
Stop-Loss : ₹1,440 (-5.2%)
Target    : ₹1,680 (+11.2%)
R:R Ratio : 2.1:1
Position  : 25 shares (₹38k, 1.9% max risk)

RATIONALE:
- Fortress balance sheet with 33.9% ROE and 0% debt
- RSI 54 base accumulation with weekly golden cross
- FII institutional flow acceleration

RISKS:
- US visa overhang
- IT sector short-term rotation
"""
        plan = funnel._parse_synthesis_output("INFY", text)

        assert plan.symbol == "INFY"
        assert plan.verdict == "BUY"
        assert plan.confidence == 82
        assert plan.winner == "BULL"
        assert plan.strategy == "Buy on Pullback (CNC)"
        assert "1,440" in plan.stop_loss
        assert "1,680" in plan.target
        assert len(plan.rationale) == 3
        assert len(plan.risks) == 2
