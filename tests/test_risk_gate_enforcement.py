"""
tests/test_risk_gate_enforcement.py
===================================
Institutional regression test suite for Task P2-D:
1. allowed=False whenever max_qty == 0 and existing_value <= 0.
2. Removal of /100 share estimate; missing price allocates zero shares.
3. Bearish direction passed to correlation shield.
4. Multi-agent pipeline aborts on risk gate exception without leaking open analysis.
"""

from unittest.mock import MagicMock
from engine.risk_gate import compute_allowed_actions


def test_at_limit_blocks_with_direction_none():
    """When portfolio or position limit allows 0 shares and no shares are held, allowed is False and direction is NONE."""
    # Total capital 200,000, 10% limit = 20,000. Existing position = 20,000 in another stock of same sector
    portfolio = {"TCS": {"qty": 15, "avg_price": 4000.0, "current_price": 4000.0}}
    res = compute_allowed_actions(
        symbol="INFY",
        exchange="NSE",
        capital=200_000.0,
        portfolio=portfolio,
        prices={"INFY": 1400.0},
        max_sector_pct=0.30,  # 30% = 60,000. TCS is 60,000 (100% of sector limit)
    )
    assert res.max_qty == 0
    assert res.direction == "NONE"
    assert res.allowed is False
    assert "SECTOR_CONCENTRATION_LIMIT" in res.flags


def test_missing_price_does_not_invent_shares():
    """Missing price must allocate zero shares, not remaining_room / 100."""
    res = compute_allowed_actions(
        symbol="INFY",
        exchange="NSE",
        capital=200_000.0,
        portfolio={},
        prices=None,  # Price is completely missing
    )
    assert res.max_qty == 0
    assert res.allowed is False
    assert res.direction == "NONE"
    assert "MISSING_PRICE" in res.flags


def test_correlation_shield_receives_actual_direction(monkeypatch):
    """Correlation shield must receive the actual proposed trade direction."""
    captured_direction = None

    def mock_audit(sym, direction, open_positions):
        nonlocal captured_direction
        captured_direction = direction
        return {"shield_triggered": False}

    import engine.options_hedging

    monkeypatch.setattr(
        engine.options_hedging,
        "audit_heavyweight_correlation_shield",
        mock_audit,
    )

    compute_allowed_actions(
        symbol="NIFTY",
        exchange="NSE",
        capital=500_000.0,
        prices={"NIFTY": 24500.0},
        direction="BEARISH",
    )
    assert captured_direction == "BEARISH"


def test_multi_agent_fails_closed_on_risk_gate_exception(monkeypatch):
    """When compute_allowed_actions raises an exception, multi-agent aborts and returns blocked message."""
    from agent.multi_agent import MultiAgentAnalyzer

    analyzer = MultiAgentAnalyzer(
        registry=MagicMock(),
        llm_provider=MagicMock(),
        verbose=False,
    )

    def failing_gate(*args, **kwargs):
        raise RuntimeError("Database connection down during risk gate check")

    import engine.risk_gate

    monkeypatch.setattr(engine.risk_gate, "compute_allowed_actions", failing_gate)

    # Mock the pipeline run_analysis_pipeline to return reports and a scorecard
    class DummyCtx:
        reports = [MagicMock(error=None)]
        scorecard = MagicMock(summary=lambda: "Dummy Scorecard")

    import analysis.pipeline

    monkeypatch.setattr(
        analysis.pipeline, "run_analysis_pipeline", lambda *args, **kwargs: DummyCtx()
    )

    result = analyzer.analyze("RELIANCE", "NSE")
    assert "[RISK GATE BLOCKED — RELIANCE]" in result
    assert "Database connection down" in result
