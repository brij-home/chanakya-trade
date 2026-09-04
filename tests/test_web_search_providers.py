"""
tests/test_web_search_providers.py
───────────────────────────────────
Tests for multi-provider web search (Exa → Tavily → Perplexity) and
yfinance-first fundamentals fallback in FundamentalAnalyst.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── web_search_available ──────────────────────────────────────────


class TestWebSearchAvailable:
    def test_false_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        from agent.web_search import web_search_available

        assert web_search_available() is False

    def test_true_when_only_tavily(self, monkeypatch):
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        from agent.web_search import web_search_available

        assert web_search_available() is True

    def test_true_when_only_exa(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "exa-test")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        from agent.web_search import web_search_available

        assert web_search_available() is True

    def test_true_when_only_perplexity(self, monkeypatch):
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        from agent.web_search import web_search_available

        assert web_search_available() is True


# ── Provider priority ─────────────────────────────────────────────


class TestProviderPriority:
    def test_exa_used_first_when_available(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "exa-test")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        with patch("agent.web_search._exa_search", return_value=[]) as mock_exa:
            from agent.web_search import web_search

            web_search("test query")
            mock_exa.assert_called_once()

    def test_tavily_used_when_exa_absent(self, monkeypatch):
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)

        with patch("agent.web_search._tavily_search", return_value=[]) as mock_tavily:
            from agent.web_search import web_search

            web_search("test query")
            mock_tavily.assert_called_once()

    def test_perplexity_used_when_only_key(self, monkeypatch):
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")

        with patch("agent.web_search._perplexity_search", return_value=[]) as mock_pplx:
            from agent.web_search import web_search

            web_search("test query")
            mock_pplx.assert_called_once()

    def test_falls_back_to_tavily_when_exa_fails(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "exa-test")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)

        from agent.web_search import SearchResult

        tavily_result = [SearchResult(title="Tavily result", url="https://t.com", text="content")]

        with patch("agent.web_search._exa_search", side_effect=RuntimeError("exa down")):
            with patch("agent.web_search._tavily_search", return_value=tavily_result):
                from agent.web_search import web_search

                results = web_search("test query")
                assert len(results) == 1
                assert results[0].title == "Tavily result"

    def test_returns_empty_when_all_fail(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "bad")
        monkeypatch.setenv("TAVILY_API_KEY", "bad")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "bad")

        with patch("agent.web_search._exa_search", side_effect=RuntimeError("fail")):
            with patch("agent.web_search._tavily_search", side_effect=RuntimeError("fail")):
                with patch("agent.web_search._perplexity_search", side_effect=RuntimeError("fail")):
                    from agent.web_search import web_search

                    assert web_search("test") == []

    def test_provider_forced_via_arg(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "exa-test")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

        with patch("agent.web_search._tavily_search", return_value=[]) as mock_tavily:
            from agent.web_search import web_search

            web_search("test", provider="tavily")
            mock_tavily.assert_called_once()


# ── Tavily provider ───────────────────────────────────────────────


class TestTavilyProvider:
    def _mock_tavily_module(self, search_results: list[dict]):
        """Create a fake tavily module with TavilyClient that returns given results."""
        mock_client_instance = MagicMock()
        mock_client_instance.search.return_value = {"results": search_results}
        mock_client_class = MagicMock(return_value=mock_client_instance)
        mock_module = MagicMock()
        mock_module.TavilyClient = mock_client_class
        return mock_module, mock_client_instance

    def test_maps_fields_correctly(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        tavily_results = [
            {
                "title": "INFY Q4 beats",
                "url": "https://example.com/infy",
                "content": "Infosys Q4 revenue grew 12%.",
                "published_date": "2026-05-01",
                "score": 0.92,
            }
        ]
        mock_module, _ = self._mock_tavily_module(tavily_results)

        with patch.dict("sys.modules", {"tavily": mock_module}):
            from agent.web_search import _tavily_search

            results = _tavily_search("INFY India stock", max_results=2)
            assert len(results) == 1
            assert results[0].title == "INFY Q4 beats"
            assert results[0].url == "https://example.com/infy"
            assert "12%" in results[0].text
            assert results[0].score == 0.92

    def test_raises_without_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        import pytest

        mock_module = MagicMock()
        mock_module.TavilyClient = MagicMock()
        with patch.dict("sys.modules", {"tavily": mock_module}):
            from agent.web_search import _tavily_search

            with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
                _tavily_search("test")

    def test_raises_when_sdk_missing(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        import pytest

        with patch.dict("sys.modules", {"tavily": None}):
            from agent.web_search import _tavily_search

            with pytest.raises((RuntimeError, ImportError)):
                _tavily_search("test")

    def test_empty_results_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        mock_module, _ = self._mock_tavily_module([])

        with patch.dict("sys.modules", {"tavily": mock_module}):
            from agent.web_search import _tavily_search

            results = _tavily_search("empty query")
            assert results == []


# ── yfinance fundamentals fallback ────────────────────────────────


class TestYfinanceFundamentalsFallback:
    """FundamentalAnalyst._fundamentals_fallback: score_fundamentals first, then Perplexity.

    Tier 1 calls analysis.fundamental.score_fundamentals(symbol) which returns a
    FundamentalsScore with a .metrics dict. We patch at that boundary to avoid
    real network/yfinance calls.
    """

    def _make_analyst(self):
        from agent.multi_agent import FundamentalAnalyst

        registry = MagicMock()
        registry.execute.side_effect = RuntimeError("broker unavailable")
        return FundamentalAnalyst(registry)

    def _make_fs(self, pe=22.5, roe=28.0, pb=3.1, d_e=0.15, rev_growth=12.0):
        """Returns a mock FundamentalsScore with the correct .metrics dict."""
        mock_fs = MagicMock()
        mock_fs.metrics = {
            "pe": pe,
            "roe": roe,  # already in percentage (e.g. 28.0 = 28%)
            "pb": pb,
            "debt_to_equity": d_e,
            "revenue_growth": rev_growth,
        }
        return mock_fs

    _PATCH = "analysis.fundamental.score_fundamentals"

    def test_yfinance_used_as_primary_fallback(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        mock_fs = self._make_fs()

        with patch(self._PATCH, return_value=mock_fs):
            analyst = self._make_analyst()
            report = analyst.analyze("INFY", "NSE")

        assert report.verdict in ("BULLISH", "NEUTRAL", "BEARISH")
        assert report.error == ""
        assert any("PE" in p for p in report.key_points)
        assert any("ROE" in p for p in report.key_points)

    def test_yfinance_uses_ns_suffix(self, monkeypatch):
        """score_fundamentals should be called with the raw symbol — NS suffix handled internally."""
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        mock_fs = self._make_fs()

        with patch(self._PATCH, return_value=mock_fs) as mock_sf:
            analyst = self._make_analyst()
            analyst.analyze("RELIANCE", "NSE")
            call_kwargs = mock_sf.call_args
            assert call_kwargs is not None, "score_fundamentals was not called"
            called_symbol = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("symbol")
            assert "RELIANCE" in str(called_symbol).upper()

    def test_yfinance_does_not_add_ns_twice(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        mock_fs = self._make_fs()

        with patch(self._PATCH, return_value=mock_fs) as mock_sf:
            analyst = self._make_analyst()
            analyst.analyze("INFY.NS", "NSE")
            call_kwargs = mock_sf.call_args
            assert call_kwargs is not None
            called_symbol = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("symbol")
            assert str(called_symbol).upper().count(".NS") <= 1

    def test_bullish_verdict_for_high_roe(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        # ROE=45% (very high), PE=18 (fair) → heuristic score should be BULLISH (>=60)
        mock_fs = self._make_fs(roe=45.0, pe=18.0)

        with patch(self._PATCH, return_value=mock_fs):
            analyst = self._make_analyst()
            report = analyst.analyze("INFY", "NSE")

        assert report.verdict == "BULLISH"

    def test_falls_through_to_perplexity_when_yfinance_empty(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        # score_fundamentals returns a FundamentalsScore with empty metrics (no PE or ROE)
        empty_fs = MagicMock()
        empty_fs.metrics = {}
        with patch(self._PATCH, return_value=empty_fs):
            with patch("agent.perplexity_finance.perplexity_finance_available", return_value=True):
                from agent.perplexity_finance import FinanceSearchResult

                good = FinanceSearchResult(query="test", summary="INFY PE=25 ROE=28%")
                with patch(
                    "agent.perplexity_finance.finance_fundamentals_for_symbol", return_value=good
                ):
                    analyst = self._make_analyst()
                    report = analyst.analyze("INFY", "NSE")

        assert report.verdict == "NEUTRAL"
        assert any("Perplexity Finance" in p for p in report.key_points)

    def test_returns_unknown_when_both_fail(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        with patch(self._PATCH, side_effect=Exception("network error")):
            analyst = self._make_analyst()
            report = analyst.analyze("INFY", "NSE")

        assert report.verdict == "UNKNOWN"
        assert report.error != ""

    def test_confidence_is_50_for_yfinance(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        mock_fs = self._make_fs()

        with patch(self._PATCH, return_value=mock_fs):
            analyst = self._make_analyst()
            report = analyst.analyze("INFY", "NSE")

        assert report.confidence == 50

    def test_yfinance_source_tagged_in_key_points(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        mock_fs = self._make_fs()

        with patch(self._PATCH, return_value=mock_fs):
            analyst = self._make_analyst()
            report = analyst.analyze("INFY", "NSE")

        assert any("yfinance" in p for p in report.key_points)
