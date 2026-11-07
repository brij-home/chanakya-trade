"""Release contracts preventing realized volatility from masquerading as IV."""

from analysis.options import compute_iv_rank_from_history
from market.earnings import get_pre_earnings_iv


def test_iv_rank_is_unavailable_without_historical_option_iv():
    assert compute_iv_rank_from_history("NIFTY") is None


def test_pre_earnings_context_does_not_invent_neutral_iv(monkeypatch):
    class Registry:
        @staticmethod
        def execute(_name, _arguments):
            return {
                "iv_rank": None,
                "iv_status": "UNAVAILABLE",
                "reason": "No option IV history",
            }

    monkeypatch.setattr("agent.tools.build_registry", lambda: Registry())
    result = get_pre_earnings_iv("RELIANCE")
    assert result["iv_rank"] is None
    assert result["action"] == "UNAVAILABLE"
    assert result["status"] == "UNAVAILABLE"


def test_realized_volatility_tool_is_separate_from_iv_tool(monkeypatch):
    from agent.tools import build_registry
    import analysis.options as options

    monkeypatch.setattr(
        options, "compute_realized_volatility_rank_from_history", lambda _symbol: 82.0
    )
    registry = build_registry()
    iv = registry.execute("get_iv_rank", {"symbol": "NIFTY"})
    rv = registry.execute("get_realized_volatility_rank", {"symbol": "NIFTY"})
    assert iv["iv_rank"] is None
    assert iv["iv_status"] == "UNAVAILABLE"
    assert rv["realized_volatility_rank"] == 82.0
    assert "iv_rank" not in rv
