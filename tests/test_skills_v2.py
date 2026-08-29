"""
Tests for new skill endpoints added in v2:
  iv_smile, gex, delta_hedge, risk_report, walkforward, whatif, strategy,
  drift, memory, memory/query, audit, telegram/status, provider (GET+POST),
  analyze/followup

All tests use FastAPI TestClient with mocked dependencies.
No real broker, LLM, or network calls.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


# ── App fixture ───────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    import os

    os.environ["DEPLOY_MODE"] = "self-hosted"
    os.environ["AUTH_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
    with (
        patch("config.credentials.load_all", return_value=None),
        patch("dotenv.load_dotenv", return_value=None),
    ):
        from web.api import app

        yield TestClient(app)


# ── Shared fake dataclasses ───────────────────────────────────


@dataclass
class FakeDeltaHedge:
    current_delta: float = 50.0
    target_delta: float = 0.0
    gap: float = -50.0
    suggestions: list = field(default_factory=list)
    cost_estimate: float = 0.0


@dataclass
class FakeRiskReport:
    portfolio_value: float = 500000.0
    portfolio_var_95: float = 12000.0
    portfolio_var_99: float = 18000.0
    portfolio_cvar_95: float = 15000.0
    portfolio_volatility: float = 0.18
    holding_vars: list = field(default_factory=list)
    correlation_matrix: dict = None
    high_correlations: list = field(default_factory=list)
    top_concentration: list = field(default_factory=list)
    hhi: float = 0.25
    concentration_risk: str = "LOW"


@dataclass
class FakeWalkForwardResult:
    symbol: str = "NIFTY"
    strategy: str = "rsi"
    windows: list = field(default_factory=list)
    avg_return: float = 12.5
    avg_sharpe: float = 0.9
    consistency: str = "MODERATE"


@dataclass
class FakeScenarioResult:
    scenario_name: str = "Market -5%"
    description: str = "test"
    current_value: float = 100000.0
    projected_value: float = 95000.0
    projected_pnl: float = -5000.0
    projected_pnl_pct: float = -5.0
    impacts: list = field(default_factory=list)


@dataclass
class FakeStrategyReport:
    symbol: str = "NIFTY"
    spot: float = 24000.0
    view: str = "BULLISH"
    dte: int = 30
    capital: float = 100000.0
    risk_pct: float = 2.0
    max_risk_inr: float = 2000.0
    strategies: list = field(default_factory=list)
    top: None = None


@dataclass
class FakeDriftReport:
    total_trades: int = 50
    trades_with_outcome: int = 30
    recent_win_rate: float = 0.6
    older_win_rate: float = 0.55
    win_rate_trend: str = "IMPROVING"
    win_rate_delta: float = 0.05
    low_vix_win_rate: float = 0.65
    high_vix_win_rate: float = 0.50
    buy_accuracy: float = 0.62
    sell_accuracy: float = 0.55
    hold_accuracy: float = 0.48
    analyst_accuracy: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)


@dataclass
class FakeAuditReport:
    trade_id: str = "trade-123"
    symbol: str = "INFY"
    verdict: str = "BULLISH"
    outcome: str = "WIN"
    pnl: float = 5000.0
    analyst_grades: list = field(default_factory=list)
    most_accurate: str = "Technical"
    most_wrong: str = "Sentiment"
    entry_quality: str = "GOOD"
    sl_assessment: str = "FAIR"
    hold_assessment: str = "GOOD"
    lessons: list = field(default_factory=lambda: ["Cut losses early"])


# ── /skills/iv_smile ──────────────────────────────────────────


class TestIVSmile:
    def _fake_df(self):
        return pd.DataFrame(
            {
                "strike": [24000, 24500],
                "ce_iv": [0.18, 0.22],
                "pe_iv": [0.20, 0.24],
                "moneyness": [-0.02, 0.02],
            }
        )

    def test_returns_rows_for_valid_symbol(self, client):
        with patch("analysis.volatility_surface.compute_iv_smile", return_value=self._fake_df()):
            r = client.post("/skills/iv_smile", json={"symbol": "NIFTY"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert isinstance(d["rows"], list)
        assert len(d["rows"]) == 2
        assert d["rows"][0]["strike"] == 24000

    def test_returns_empty_rows_when_none(self, client):
        with patch("analysis.volatility_surface.compute_iv_smile", return_value=None):
            r = client.post("/skills/iv_smile", json={"symbol": "NIFTY"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["rows"] == []

    def test_500_on_exception(self, client):
        with patch(
            "analysis.volatility_surface.compute_iv_smile",
            side_effect=RuntimeError("surface computation failed"),
        ):
            r = client.post("/skills/iv_smile", json={"symbol": "NIFTY"})
        assert r.status_code == 500


# ── /skills/gex ───────────────────────────────────────────────


class TestGEX:
    def _fake_gex(self):
        return {
            "total_net_gex": 1250000.0,
            "flip_point": 24200.0,
            "regime": "POSITIVE_GEX",
            "strikes": [{"strike": 24000, "net_gex": 500000.0}],
        }

    def test_returns_gex_data(self, client):
        with patch("analysis.gex.get_gex_analysis", return_value=self._fake_gex()):
            r = client.post("/skills/gex", json={"symbol": "NIFTY"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["total_net_gex"] == 1250000.0
        assert d["flip_point"] == 24200.0
        assert d["regime"] == "POSITIVE_GEX"
        assert isinstance(d["strikes"], list)

    def test_returns_error_dict_from_backend(self, client):
        # Errors are surfaced in data payload, not as HTTP errors
        with patch("analysis.gex.get_gex_analysis", return_value={"error": "No data"}):
            r = client.post("/skills/gex", json={"symbol": "NIFTY"})
        assert r.status_code == 200
        assert r.json()["data"]["error"] == "No data"

    def test_500_on_exception(self, client):
        with patch(
            "analysis.gex.get_gex_analysis",
            side_effect=RuntimeError("options chain unavailable"),
        ):
            r = client.post("/skills/gex", json={"symbol": "NIFTY"})
        assert r.status_code == 500


# ── /skills/delta_hedge ───────────────────────────────────────


class TestDeltaHedge:
    def test_returns_demo_when_no_broker(self, client):
        with patch("brokers.session.get_broker", side_effect=RuntimeError("no broker")):
            r = client.post("/skills/delta_hedge")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["demo"] is True
        assert d["suggestions"] == []

    def test_returns_hedge_suggestion_when_broker_connected(self, client):
        fake_pg = MagicMock()
        fake_pg.net_delta = 50.0

        with (
            patch("brokers.session.get_broker", return_value=MagicMock()),
            patch("engine.portfolio.get_position_greeks", return_value=fake_pg),
            patch("engine.greeks_manager.compute_delta_hedge", return_value=FakeDeltaHedge()),
        ):
            r = client.post("/skills/delta_hedge")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["current_delta"] == 50.0
        assert d["target_delta"] == 0.0
        assert d["gap"] == -50.0

    def test_500_on_exception(self, client):
        fake_pg = MagicMock()
        fake_pg.net_delta = 50.0

        with (
            patch("brokers.session.get_broker", return_value=MagicMock()),
            patch("engine.portfolio.get_position_greeks", return_value=fake_pg),
            patch(
                "engine.greeks_manager.compute_delta_hedge",
                side_effect=RuntimeError("greeks computation failed"),
            ),
        ):
            r = client.post("/skills/delta_hedge")
        assert r.status_code == 500


# ── /skills/risk_report ───────────────────────────────────────


class TestRiskReport:
    def test_returns_demo_when_no_broker(self, client):
        with patch("brokers.session.get_broker", side_effect=RuntimeError("no broker")):
            r = client.post("/skills/risk_report")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["demo"] is True

    def test_returns_report_when_connected(self, client):
        with (
            patch("brokers.session.get_broker", return_value=MagicMock()),
            patch("engine.risk_metrics.compute_portfolio_risk", return_value=FakeRiskReport()),
        ):
            r = client.post("/skills/risk_report")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["portfolio_value"] == 500000.0
        assert d["portfolio_var_95"] == 12000.0
        assert d["concentration_risk"] == "LOW"


# ── /skills/walkforward ───────────────────────────────────────


class TestWalkForward:
    def test_returns_result(self, client):
        with patch("engine.backtest.walk_forward_test", return_value=FakeWalkForwardResult()):
            r = client.post(
                "/skills/walkforward",
                json={"symbol": "NIFTY", "strategy": "rsi"},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["symbol"] == "NIFTY"
        assert d["avg_return"] == 12.5
        assert d["consistency"] == "MODERATE"

    def test_default_strategy_is_rsi(self, client):
        with patch(
            "engine.backtest.walk_forward_test", return_value=FakeWalkForwardResult()
        ) as mock:
            client.post("/skills/walkforward", json={"symbol": "NIFTY"})
        _, kwargs = mock.call_args
        assert kwargs["strategy_name"] == "rsi"

    def test_500_on_exception(self, client):
        with patch(
            "engine.backtest.walk_forward_test",
            side_effect=RuntimeError("backtest engine error"),
        ):
            r = client.post("/skills/walkforward", json={"symbol": "NIFTY"})
        assert r.status_code == 500


# ── /skills/whatif ────────────────────────────────────────────


class TestWhatIf:
    def test_returns_demo_when_no_broker(self, client):
        with patch("brokers.session.get_broker", side_effect=RuntimeError("no broker")):
            r = client.post("/skills/whatif", json={"scenario": "market", "nifty_change": -5.0})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["demo"] is True

    def test_market_move_scenario(self, client):
        fake_sim = MagicMock()
        fake_sim.scenario_market_move.return_value = FakeScenarioResult()

        with (
            patch("brokers.session.get_broker", return_value=MagicMock()),
            patch("engine.simulator.Simulator", return_value=fake_sim),
        ):
            r = client.post(
                "/skills/whatif",
                json={"scenario": "market", "nifty_change": -5.0},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["projected_pnl"] == -5000.0
        fake_sim.scenario_market_move.assert_called_once_with(-5.0)

    def test_stock_move_scenario(self, client):
        fake_sim = MagicMock()
        fake_sim.scenario_stock_move.return_value = FakeScenarioResult(
            scenario_name="RELIANCE +10%",
            projected_pnl=10000.0,
        )

        with (
            patch("brokers.session.get_broker", return_value=MagicMock()),
            patch("engine.simulator.Simulator", return_value=fake_sim),
        ):
            r = client.post(
                "/skills/whatif",
                json={"scenario": "stock", "symbol": "RELIANCE", "stock_change": 10.0},
            )
        assert r.status_code == 200
        fake_sim.scenario_stock_move.assert_called_once_with("RELIANCE", 10.0)

    def test_default_three_scenario_sweep(self, client):
        fake_sim = MagicMock()
        fake_sim.scenario_market_move.side_effect = [
            FakeScenarioResult(scenario_name="Market -5%"),
            FakeScenarioResult(scenario_name="Market flat"),
            FakeScenarioResult(scenario_name="Market +5%"),
        ]

        with (
            patch("brokers.session.get_broker", return_value=MagicMock()),
            patch("engine.simulator.Simulator", return_value=fake_sim),
        ):
            # No nifty_change provided — should trigger three-scenario sweep
            r = client.post("/skills/whatif", json={"scenario": "market"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["multi"] is True
        assert len(d["scenarios"]) == 3
        assert fake_sim.scenario_market_move.call_count == 3


# ── /skills/strategy ──────────────────────────────────────────


class TestStrategy:
    def test_returns_strategies(self, client):
        with (
            patch("market.quotes.get_ltp", return_value=24000.0),
            patch("engine.strategy.recommend", return_value=FakeStrategyReport()),
        ):
            r = client.post(
                "/skills/strategy",
                json={"symbol": "NIFTY", "view": "BULLISH", "dte": 30},
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["symbol"] == "NIFTY"
        assert d["spot"] == 24000.0
        assert isinstance(d["strategies"], list)

    def test_500_when_spot_fails(self, client):
        with patch("market.quotes.get_ltp", side_effect=Exception("quote fetch failed")):
            r = client.post(
                "/skills/strategy",
                json={"symbol": "NIFTY", "view": "BULLISH"},
            )
        assert r.status_code == 500

    def test_view_is_uppercased(self, client):
        with (
            patch("market.quotes.get_ltp", return_value=24000.0),
            patch("engine.strategy.recommend", return_value=FakeStrategyReport()) as mock_rec,
        ):
            client.post(
                "/skills/strategy",
                json={"symbol": "NIFTY", "view": "bullish"},
            )
        _, kwargs = mock_rec.call_args
        assert kwargs["view"] == "BULLISH"


# ── /skills/drift ─────────────────────────────────────────────


class TestDrift:
    def test_returns_report(self, client):
        with patch("engine.drift.detect_drift", return_value=FakeDriftReport()):
            r = client.post("/skills/drift")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["total_trades"] == 50
        assert d["win_rate_trend"] == "IMPROVING"
        assert d["recent_win_rate"] == 0.6

    def test_500_on_exception(self, client):
        with patch("engine.drift.detect_drift", side_effect=RuntimeError("memory read failed")):
            r = client.post("/skills/drift")
        assert r.status_code == 500


# ── /skills/memory ────────────────────────────────────────────


class TestMemory:
    def test_returns_stats_and_records(self, client):
        fake_stats = {"total": 100, "wins": 60, "losses": 40}
        fake_records = [{"trade_id": "t1", "symbol": "INFY"}]

        mock_tm = MagicMock()
        mock_tm.get_stats.return_value = fake_stats
        mock_tm.query.return_value = fake_records

        with patch("engine.memory.trade_memory", mock_tm):
            r = client.post("/skills/memory")
        assert r.status_code == 200
        d = r.json()["data"]
        assert "stats" in d
        assert "records" in d
        assert d["stats"]["total"] == 100
        assert isinstance(d["records"], list)

    def test_memory_query_with_filters(self, client):
        fake_records = [{"trade_id": "t2", "symbol": "INFY"}]

        mock_tm = MagicMock()
        mock_tm.query.return_value = fake_records

        with patch("engine.memory.trade_memory", mock_tm):
            r = client.post(
                "/skills/memory/query",
                json={"symbol": "INFY", "limit": 10},
            )
        assert r.status_code == 200
        mock_tm.query.assert_called_once_with(
            symbol="INFY",
            verdict=None,
            limit=10,
            days_back=None,
        )


# ── /skills/audit ─────────────────────────────────────────────


class TestAudit:
    def test_returns_audit_report(self, client):
        with patch("engine.audit.audit_trade", return_value=FakeAuditReport()):
            r = client.post("/skills/audit", json={"trade_id": "trade-123"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["trade_id"] == "trade-123"
        assert d["verdict"] == "BULLISH"
        assert d["outcome"] == "WIN"
        assert d["pnl"] == 5000.0
        assert d["most_accurate"] == "Technical"

    def test_500_on_bad_trade_id(self, client):
        with patch(
            "engine.audit.audit_trade",
            side_effect=ValueError("trade not found in memory"),
        ):
            r = client.post("/skills/audit", json={"trade_id": "nonexistent-trade"})
        assert r.status_code == 500


# ── /skills/telegram/status ───────────────────────────────────


class TestTelegramStatus:
    def test_not_configured_when_no_env_var(self, client, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        r = client.get("/skills/telegram/status")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["configured"] is False
        assert d["token_hint"] is None

    def test_configured_when_token_set(self, client, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:token123")
        r = client.get("/skills/telegram/status")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["configured"] is True
        assert d["token_hint"].endswith("ken123")


# ── /skills/provider ──────────────────────────────────────────


class TestProvider:
    def test_get_returns_current_provider(self, client, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        r = client.post("/skills/provider")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["current"] == "anthropic"
        assert "anthropic" in d["available"]
        assert "ollama" in d["available"]

    def test_post_switches_provider(self, client, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        r = client.post("/skills/provider/switch", json={"provider": "openai"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["current"] == "openai"

    def test_post_rejects_invalid_provider(self, client):
        r = client.post("/skills/provider/switch", json={"provider": "badprovider"})
        assert r.status_code == 400


# ── /skills/analyze/followup ──────────────────────────────────


class TestAnalyzeFollowup:
    def _mock_provider(self):
        mock = MagicMock()
        mock.chat.return_value = "The ideal entry for INFY is \u20b91,580."
        return mock

    def test_returns_response(self, client):
        mock_provider = self._mock_provider()
        with patch("agent.core.get_provider", return_value=mock_provider):
            r = client.post(
                "/skills/analyze/followup",
                json={
                    "symbol": "INFY",
                    "question": "What is the ideal entry?",
                    "session_id": "resp-test-1",
                },
            )
        assert r.status_code == 200
        d = r.json()["data"]
        assert "response" in d
        assert "INFY" in d["symbol"]

    def test_seeds_context_on_first_call(self, client):
        """On first call with context, provider.chat is called with system + question."""
        mock_provider = self._mock_provider()
        with patch("agent.core.get_provider", return_value=mock_provider):
            r = client.post(
                "/skills/analyze/followup",
                json={
                    "symbol": "INFY",
                    "question": "What is the ideal entry?",
                    "session_id": "ctx-seed-test-1",
                    "context": {
                        "analysts": [
                            {
                                "name": "Technical",
                                "verdict": "BULLISH",
                                "confidence": 80,
                                "key_points": ["RSI oversold"],
                            }
                        ],
                        "synthesis_text": "Overall bullish bias.",
                    },
                },
            )
        assert r.status_code == 200
        # Direct LLM call with system + user messages
        assert mock_provider.chat.call_count == 1
        call_kwargs = mock_provider.chat.call_args
        messages = (
            call_kwargs.kwargs.get("messages")
            or call_kwargs[1].get("messages")
            or call_kwargs[0][0]
        )
        # Should have system message + user question
        assert any("INFY" in str(m) for m in messages)

    def test_reuses_session_on_second_call(self, client):
        """Second call reuses session history — no new context priming."""
        from web.skills import _chat_sessions

        session_key = "followup_MSFT_NSE_reuse-session-99"
        _chat_sessions[session_key] = {
            "system": "You are analyzing MSFT.",
            "history": [
                {"role": "user", "content": "First question"},
                {"role": "assistant", "content": "First answer"},
            ],
        }

        mock_provider = self._mock_provider()
        with patch("agent.core.get_provider", return_value=mock_provider):
            r = client.post(
                "/skills/analyze/followup",
                json={
                    "symbol": "MSFT",
                    "exchange": "NSE",
                    "question": "Any updated view?",
                    "session_id": "reuse-session-99",
                },
            )
        assert r.status_code == 200
        # Session history should now have 4 items (2 old + 1 new question + 1 new answer)
        assert len(_chat_sessions[session_key]["history"]) == 4

    def test_500_on_provider_error(self, client):
        mock_provider = self._mock_provider()
        mock_provider.chat.side_effect = RuntimeError("LLM timeout")

        with patch("agent.core.get_provider", return_value=mock_provider):
            r = client.post(
                "/skills/analyze/followup",
                json={
                    "symbol": "TCS",
                    "question": "Should I hold?",
                    "session_id": "err-session-1",
                },
            )
        assert r.status_code == 500


# ── Test RRG, Forensic, Position Size, and Funnel Skills ───────


class TestSkillRRGAndForensics:
    def test_skill_rrg_returns_sectors(self, client):
        r = client.post("/skills/rrg", json={"symbol": "INFY"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        res = data["data"]
        assert "sectors" in res
        assert len(res["sectors"]) >= 5
        assert "stock_alignment" in res
        if res["stock_alignment"]:
            assert res["stock_alignment"]["symbol"] == "INFY"

    def test_skill_forensic_returns_audit(self, client):
        r = client.post("/skills/forensic", json={"symbol": "RELIANCE"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        res = data["data"]
        assert res["symbol"] == "RELIANCE"
        assert "beneish_m_score" in res
        assert "altman_z_score" in res
        assert "piotroski_f_score" in res
        assert "quality_rating" in res

    def test_skill_position_size_calculates(self, client):
        r = client.post(
            "/skills/position_size",
            json={
                "symbol": "INFY",
                "entry_price": 1500,
                "stop_loss": 1470,
                "capital": 200000,
                "max_risk_pct": 1.5,
                "sizing_model": "atr_volatility",
                "is_fno": False,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        res = data["data"]
        assert res["symbol"] == "INFY"
        assert res["shares"] > 0
        assert res["capital_allocated"] <= 200000

    def test_skill_funnel_runs(self, client):
        from agent.smart_funnel import SmartFunnelResult, PreFilterReport

        fake_res = SmartFunnelResult(
            total_screened=2,
            qualified_count=1,
            filtered_count=1,
            pre_filter_reports=[
                PreFilterReport(symbol="TCS", score=82.0, qualified=True, pass_reason="High quality"),
                PreFilterReport(symbol="XYZ", score=40.0, qualified=False, rejection_reason="Low momentum"),
            ],
            qualified_symbols=["TCS"],
            trade_plans=[],
            elapsed_sec=0.2,
        )
        with patch.object(
            __import__("agent.smart_funnel", fromlist=["SmartFunnel"]).SmartFunnel,
            "run",
            return_value=fake_res,
        ):
            r = client.post("/skills/funnel", json={"symbols": ["TCS", "XYZ"], "top_n": 2})
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert data["data"]["qualified_count"] == 1


class TestSkillSMCAndLifecycle:
    def test_skill_market_structure(self, client):
        import pandas as pd
        dates = pd.date_range("2025-01-01", periods=30, freq="D")
        closes = [100 + i * 2 for i in range(30)]
        fake_df = pd.DataFrame({"date": dates, "open": closes, "high": [c + 2 for c in closes], "low": [c - 2 for c in closes], "close": closes, "volume": [10000]*30})

        with patch("analysis.market_structure.analyze_market_structure") as mock_ms:
            from analysis.market_structure import MarketStructureReport
            mock_ms.return_value = MarketStructureReport(
                symbol="RELIANCE",
                ltp=2400.0,
                regime="BULLISH",
                structure_score=75,
                setup_type="BREAKOUT_EXPANSION",
                setup_confidence=80,
            )
            r = client.post("/skills/market_structure", json={"symbol": "RELIANCE"})
            assert r.status_code == 200
            assert r.json()["data"]["regime"] == "BULLISH"

    def test_skill_volume_profile(self, client):
        with patch("analysis.volume_profile.analyze_volume_profile") as mock_vp:
            from analysis.volume_profile import VolumeProfileReport
            mock_vp.return_value = VolumeProfileReport(
                symbol="NIFTY",
                ltp=24000.0,
                rvol_20d=2.1,
                rvol_50d=1.9,
                volume_tier="HIGH",
                footprint_bias="ACCUMULATION",
                footprint_score=60,
                poc_price=23950.0,
                vah_price=24100.0,
                val_price=23800.0,
                price_vs_value_area="INSIDE_VALUE_AREA",
            )
            r = client.post("/skills/volume_profile", json={"symbol": "NIFTY"})
            assert r.status_code == 200
            assert r.json()["data"]["rvol_20d"] == 2.1

    def test_skill_multibagger(self, client):
        with patch("analysis.multibagger.scan_multibagger_opportunity") as mock_mb:
            from analysis.multibagger import MultibaggerReport
            mock_mb.return_value = MultibaggerReport(
                symbol="TRENT",
                ltp=6500.0,
                multibagger_score=85,
                category="STAGE_2_SUPERPERFORMER",
                trend_template_passed=8,
                trend_template_qualified=True,
                weinstein_stage="STAGE_2_MARKUP",
            )
            r = client.post("/skills/multibagger", json={"symbol": "TRENT"})
            assert r.status_code == 200
            assert r.json()["data"]["multibagger_score"] == 85

    def test_skill_lifecycle(self, client):
        with patch("engine.trade_lifecycle.audit_position_lifecycle") as mock_lc:
            from engine.trade_lifecycle import PositionLifecycleReport
            mock_lc.return_value = PositionLifecycleReport(
                symbol="INFY",
                ltp=1650.0,
                entry_price=1500.0,
                initial_stop_loss=1450.0,
                initial_risk_per_share=50.0,
                current_pnl_pts=150.0,
                current_pnl_pct=10.0,
                current_r_multiple=3.0,
                health_status="HEALTHY_ACCELERATING",
                health_score=90,
                breakeven_reached=True,
                recommended_action="HOLD_RUNNER",
            )
            r = client.post(
                "/skills/lifecycle",
                json={"symbol": "INFY", "entry_price": 1500, "initial_stop_loss": 1450},
            )
            assert r.status_code == 200
            assert r.json()["data"]["current_r_multiple"] == 3.0

    def test_skill_top_conviction(self, client):
        with patch("analysis.high_conviction.scan_high_conviction_opportunities") as mock_scan:
            from analysis.high_conviction import HighConvictionScanResult, HighConvictionOpportunity
            fake_opp = HighConvictionOpportunity(
                rank=1,
                symbol="TRENT",
                sector="Retail",
                ltp=6500.0,
                conviction_score=95,
                setup_type="VCP_CONTRACTION",
                setup_title="⚡ VCP Contraction",
                trade_bias="LONG",
                entry_price=6500.0,
                stop_loss=6250.0,
                target_1=7000.0,
                target_2=7500.0,
                risk_reward_ratio=2.0,
                risk_pts=250.0,
                reward_pts=500.0,
                catalyst_summary="Stage 2 Superperformer",
                structure_regime="BULLISH",
                weinstein_stage="STAGE_2_MARKUP",
                trend_template_passed=8,
                rvol_20d=2.4,
                vcp_detected=True,
                forensic_quality="A+",
            )
            mock_scan.return_value = HighConvictionScanResult(
                timestamp="28 Aug 2026, 03:00 PM IST",
                scanned_universe="nifty50",
                total_scanned=1,
                market_posture="BULLISH_EXPANSION",
                leading_sectors=["Retail", "IT"],
                opportunities=[fake_opp],
                summary="Top setups scanned.",
            )
            r = client.post("/skills/top_conviction", json={"universe": "nifty50", "top_n": 1})
            assert r.status_code == 200
            d = r.json()["data"]
            assert d["market_posture"] == "BULLISH_EXPANSION"
            assert len(d["opportunities"]) == 1
            assert d["opportunities"][0]["symbol"] == "TRENT"

    def test_skill_universe_categories(self, client):
        r = client.get("/skills/universe_categories")
        assert r.status_code == 200
        d = r.json()["data"]
        assert "categories" in d
        assert len(d["categories"]) >= 10
        types = {c["type"] for c in d["categories"]}
        assert "THEMATIC" in types
        assert "SECTOR" in types

    def test_skill_big_move(self, client):
        with patch("analysis.big_move.predict_large_move") as mock_pred:
            from analysis.big_move import BigMovePrediction, SqueezeState, OptionsFlowBias
            mock_pred.return_value = BigMovePrediction(
                symbol="NIFTY",
                ltp=24500.0,
                directional_bias="BULLISH",
                directional_probability=88,
                prediction_verdict="EXPLOSIVE_BULLISH_EXPANSION",
                timing_trigger="TRIGGER_NOW",
                expected_move_pts=350.0,
                expected_move_pct=1.43,
                target_price=24850.0,
                invalidation_price=24300.0,
                risk_reward_ratio=1.75,
                squeeze=SqueezeState(False, True, 3, 45.2, "BULLISH_EXPANSION", 24600, 24300, 24550, 24350),
                options_flow=OptionsFlowBias(True, 1.35, 24500, "LONG_BUILDUP", 100000, 135000, 24800, 24300, "AGGRESSIVE_BULLISH"),
                catalysts=["Squeeze Fired", "Aggressive Long Buildup"],
                action_plan="Enter Bullish Breakout",
            )
            r = client.post("/skills/big_move", json={"symbol": "NIFTY", "exchange": "NSE"})
            assert r.status_code == 200
            d = r.json()["data"]
            assert d["directional_bias"] == "BULLISH"
            assert d["directional_probability"] == 88
            assert d["prediction_verdict"] == "EXPLOSIVE_BULLISH_EXPANSION"

    def test_skill_execution_gate(self, client):
        with patch("analysis.execution_gate.evaluate_execution_gate") as mock_eval:
            from analysis.execution_gate import ExecutionGateReport
            mock_eval.return_value = ExecutionGateReport(
                symbol="JSWSTEEL",
                sector="Metals",
                sector_icon="⛏️",
                ltp=1337.50,
                strategic_score=86,
                tactical_score=88,
                execution_status="READY",
                setup_title="Stage 2 Superperformer",
                trade_bias="LONG",
                entry_price=1337.50,
                stop_loss=1285.80,
                target_1=1440.80,
                target_2=1518.40,
                risk_reward_ratio=2.0,
                rvol=1.6,
                options_oi_regime="LONG_BUILDUP",
                squeeze_fired=True,
                catalysts=["Squeeze Fired"],
                action_summary="Execute now",
                telegram_sent=False,
            )
            r = client.post("/skills/execution_gate", json={"symbol": "JSWSTEEL", "notify_telegram": False})
            assert r.status_code == 200
            d = r.json()["data"]
            assert d["execution_status"] == "READY"
            assert d["strategic_score"] == 86
            assert d["tactical_score"] == 88

    def test_skill_scan_and_alert(self, client):
        with patch("analysis.execution_gate.scan_and_alert_execution_candidates") as mock_scan:
            from analysis.execution_gate import ExecutionGateReport
            mock_scan.return_value = [
                ExecutionGateReport(
                    symbol="JSWSTEEL",
                    sector="Metals",
                    sector_icon="⛏️",
                    ltp=1337.50,
                    strategic_score=86,
                    tactical_score=88,
                    execution_status="READY",
                    setup_title="Stage 2 Superperformer",
                    trade_bias="LONG",
                    entry_price=1337.50,
                    stop_loss=1285.80,
                    target_1=1440.80,
                    target_2=1518.40,
                    risk_reward_ratio=2.0,
                    rvol=1.6,
                    options_oi_regime="LONG_BUILDUP",
                    squeeze_fired=True,
                    catalysts=["Squeeze Fired"],
                    action_summary="Execute now",
                    telegram_sent=True,
                )
            ]
            r = client.post("/skills/scan_and_alert", json={"universe": "auto_market_aware", "notify_telegram": True})
            assert r.status_code == 200
            d = r.json()["data"]
            assert d["total_candidates"] == 1
            assert d["candidates"][0]["symbol"] == "JSWSTEEL"






