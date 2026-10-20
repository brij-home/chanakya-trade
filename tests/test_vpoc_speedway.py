"""
tests/test_vpoc_speedway.py
───────────────────────────
Institutional test suite for Virgin Point of Control (VPOC) & Liquidity Vacuum Speedway Engine.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.vpoc_speedway import (
    check_alert_speedway,
    evaluate_liquidity_vacuum_speedway,
    find_virgin_pocs,
)
from engine.alert_scrutiny import AlertScrutinyAuditor


@pytest.fixture
def sample_daily_data() -> pd.DataFrame:
    """
    Creates 10 daily bars:
    - Day 0: Low 24000, High 24200, Close 24100 -> POC ~24100.
    - Day 1: Low 24150, High 24350, Close 24250 -> Touches 24100? No, 24150 > 24100.
    - Day 2: Low 24200, High 24400, Close 24300 -> Still hasn't touched 24100.
    - Day 3: Low 24300, High 24500, Close 24400 -> POC ~24400.
    - Day 4: Low 24450, High 24650, Close 24550.
    - Day 5: Low 24500, High 24700, Close 24600.
    - Day 6: Low 24600, High 24800, Close 24700 -> POC ~24700.
    - Day 7: Low 24750, High 24950, Close 24850.
    - Day 8: Low 24800, High 25000, Close 24900.
    - Day 9 (latest): Low 24850, High 25050, Close 24950.
    Day 6 POC ~24700 was touched on Day 7? Low is 24750, so 24700 was NOT touched!
    Day 0, 3, 6 are untouched VPOCs.
    """
    dates = pd.date_range("2026-09-01", periods=10, freq="B")
    data = [
        {"high": 24200.0, "low": 24000.0, "close": 24100.0, "volume": 1_000_000},
        {"high": 24350.0, "low": 24150.0, "close": 24250.0, "volume": 1_200_000},
        {"high": 24400.0, "low": 24200.0, "close": 24300.0, "volume": 1_100_000},
        {"high": 24500.0, "low": 24300.0, "close": 24400.0, "volume": 1_500_000},
        {"high": 24650.0, "low": 24450.0, "close": 24550.0, "volume": 1_300_000},
        {"high": 24700.0, "low": 24500.0, "close": 24600.0, "volume": 1_400_000},
        {"high": 24800.0, "low": 24600.0, "close": 24700.0, "volume": 1_800_000},
        {"high": 24950.0, "low": 24750.0, "close": 24850.0, "volume": 1_600_000},
        {"high": 25000.0, "low": 24800.0, "close": 24900.0, "volume": 1_500_000},
        {"high": 25050.0, "low": 24850.0, "close": 24950.0, "volume": 1_700_000},
    ]
    df = pd.DataFrame(data, index=dates)
    return df


def test_find_virgin_pocs(sample_daily_data: pd.DataFrame):
    """Verifies that untested daily POCs are discovered and categorized."""
    current_ltp = 24950.0
    vpocs = find_virgin_pocs(sample_daily_data, current_ltp=current_ltp)

    assert len(vpocs) >= 1
    # Check that prices are below current LTP
    for v in vpocs:
        assert v["side"] == "BELOW"
        assert v["distance_pct"] < 0
        assert v["price"] < current_ltp


def test_evaluate_liquidity_vacuum_speedway_directional():
    """Verifies directional speedway matching and magnetic pull scoring."""
    ltp = 25000.0
    # Candidate VPOC at 25300 (1.2% above LTP)
    candidate_vpocs = [
        {
            "price": 25300.0,
            "date": "2026-10-10",
            "session_day_index": 5,
            "distance_pct": 1.20,
            "side": "ABOVE",
            "volume": 2_500_000,
        }
    ]

    # Bullish direction should match VPOC above
    res_bull = evaluate_liquidity_vacuum_speedway(
        symbol="NIFTY",
        ltp=ltp,
        direction="BULLISH",
        candidate_vpocs=candidate_vpocs,
    )
    assert res_bull is not None
    assert res_bull["is_speedway"] is True
    assert res_bull["target_vpoc"] == 25300.0
    assert res_bull["vacuum_spread_pts"] == 300.0
    assert res_bull["vacuum_spread_pct"] == 1.20
    assert res_bull["magnetic_pull_score"] >= 80
    assert "LIQUIDITY VACUUM SPEEDWAY" in res_bull["summary_badge"]

    # Bearish direction should NOT match a VPOC above LTP
    res_bear = evaluate_liquidity_vacuum_speedway(
        symbol="NIFTY",
        ltp=ltp,
        direction="BEARISH",
        candidate_vpocs=candidate_vpocs,
    )
    assert res_bear is None


def test_check_alert_speedway_and_scrutiny_integration(monkeypatch):
    """Verifies that alert scrutiny leverages VPOC speedway for elephant footprint and scoring."""
    from types import SimpleNamespace

    auditor = AlertScrutinyAuditor(min_rr_ratio=1.5)
    # Ensure deterministic quant fallback without interactive LLM prompts
    monkeypatch.setattr(auditor, "_execute_fast_llm_scrutiny", lambda *args, **kwargs: None)

    alert_obj = SimpleNamespace(
        symbol="NIFTY",
        ltp=25000.0,
        trigger_level=25000.0,
        stop_loss=24900.0,
        target_level=25300.0,
        direction="BULLISH",
        alert_type="BREAKOUT",
        rvol=2.2,
        environment="TEST",
        is_live=False,
        alert_id="test-speedway-1",
        metrics={
            "candidate_vpocs": [
                {
                    "price": 25300.0,
                    "date": "2026-10-12",
                    "session_day_index": 8,
                    "distance_pct": 1.20,
                    "side": "ABOVE",
                    "volume": 2_000_000,
                }
            ]
        },
    )

    # Evaluate speedway directly
    sp = check_alert_speedway(alert_obj)
    assert sp is not None
    assert sp["target_vpoc"] == 25300.0

    # Scrutinize alert
    res = auditor.scrutinize_alert(alert_obj)
    assert res.status == "APPROVED"
    assert res.score >= 85
    assert "LIQUIDITY VACUUM SPEEDWAY" in res.logic_confirmation
    assert (
        alert_obj.metrics["predatory_pipeline"]["elephant"]["status"] == "INSTITUTIONAL_FOOTPRINT"
    )
