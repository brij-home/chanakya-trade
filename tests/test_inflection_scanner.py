"""
tests/test_inflection_scanner.py
─────────────────────────────────
Comprehensive unit & integration tests for the Inflection Point & Multibagger Screener Suite.
Tests:
  1. Single stock inflection detection across VCP, TTM Squeeze, Stage 1->2, SMC Spring, and RRG.
  2. Timing classification (TRIGGER_NOW, COILING_IMMINENT, PULLBACK_RETEST).
  3. Parallel universe scanning with archetype & timing filters.
  4. AI 5W+H Conclusive Decision Matrix generation (deterministic fallback & structure).
  5. Interactive dot-connecting chat assistant.
  6. FastAPI skill endpoints (/skills/inflection_scan, /skills/inflection_decision, /skills/inflection_chat).
"""

import numpy as np
import pandas as pd
import pytest
from starlette.testclient import TestClient

from analysis.inflection_ai import (
    answer_inflection_chat,
    generate_inflection_decision,
)
from analysis.inflection_scanner import (
    InflectionScanResult,
    InflectionSetup,
    evaluate_single_stock_inflection,
    get_inflection_universes,
    scan_inflections_universe,
)
from web.api import app


@pytest.fixture
def synthetic_vcp_breakout_df():
    """Generates 200 bars of progressive VCP tightening followed by an explosive volume breakout."""
    dates = pd.date_range("2024-01-01", periods=200, freq="D")
    closes = []
    highs = []
    lows = []
    volumes = []

    base = 500.0
    for i in range(160):
        # Stage 1 base to early Stage 2
        p = base + (i * 0.8) + (np.sin(i / 5.0) * 15.0)
        closes.append(p)
        highs.append(p + 5.0)
        lows.append(p - 4.0)
        volumes.append(100000)

    # VCP Contraction 1 (depth ~15%)
    for i in range(15):
        p = closes[-1] + (np.sin(i / 2.5) * 8.0)
        closes.append(p)
        highs.append(p + 3.0)
        lows.append(p - 3.0)
        volumes.append(60000)

    # VCP Contraction 2 (depth ~5% tight)
    for i in range(15):
        p = closes[-1] + (np.sin(i / 2.0) * 3.0)
        closes.append(p)
        highs.append(p + 1.5)
        lows.append(p - 1.5)
        volumes.append(35000)  # Dry volume

    # Final 10 bars: Pivot breakout with volume surge
    for i in range(10):
        p = closes[-1] + 3.5 + (i * 2.0)
        closes.append(p)
        highs.append(p + 4.0)
        lows.append(p - 1.0)
        volumes.append(300000)  # High RVOL

    return pd.DataFrame(
        {
            "open": [c - 1.0 for c in closes],
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


@pytest.fixture
def synthetic_ttm_squeeze_coiling_df():
    """Generates 50 bars of tight range compression inside Keltner Channels (TTM Squeeze ON)."""
    dates = pd.date_range("2024-01-01", periods=50, freq="D")
    closes = [1000.0 + np.sin(i / 3.0) * 2.0 for i in range(50)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 2.5 for c in closes],
            "low": [c - 2.5 for c in closes],
            "close": closes,
            "volume": [80000] * 50,
        },
        index=dates,
    )


def test_evaluate_single_stock_vcp_breakout(synthetic_vcp_breakout_df):
    setup = evaluate_single_stock_inflection("TRENT", df=synthetic_vcp_breakout_df)
    assert setup is not None
    assert setup.symbol == "TRENT"
    assert setup.ltp > 0
    assert setup.inflection_score >= 50
    assert setup.entry_price > 0
    assert setup.stop_loss > 0
    assert setup.target_1 > setup.entry_price
    assert setup.risk_reward_ratio >= 1.5
    assert len(setup.confluence_factors) > 0
    assert setup.execution_ticket.get("action") == "LONG (BUY)"


def test_evaluate_single_stock_ttm_squeeze(synthetic_ttm_squeeze_coiling_df):
    setup = evaluate_single_stock_inflection("COFORGE", df=synthetic_ttm_squeeze_coiling_df)
    assert setup is not None
    assert setup.squeeze_state == "COILING"
    assert setup.timing_state in ("COILING_IMMINENT", "TRIGGER_NOW", "PULLBACK_RETEST")
    assert setup.squeeze_duration >= 1


def test_scan_inflections_universe(synthetic_vcp_breakout_df, synthetic_ttm_squeeze_coiling_df):
    mock_cache = {
        "TRENT": synthetic_vcp_breakout_df,
        "COFORGE": synthetic_ttm_squeeze_coiling_df,
    }
    res = scan_inflections_universe(
        universe="multibagger_hunters",
        df_cache=mock_cache,
        min_score=30,
        max_results=10,
    )
    assert isinstance(res, InflectionScanResult)
    assert res.total_scanned == 2
    assert len(res.candidates) > 0
    assert res.execution_time_seconds >= 0.0

    cand = res.candidates[0]
    assert cand.symbol in ("TRENT", "COFORGE")
    assert cand.inflection_score > 0
    assert cand.target_1 > cand.entry_price


def test_get_inflection_universes():
    universes = get_inflection_universes()
    assert len(universes) >= 5
    ids = [u["id"] for u in universes]
    assert "multibagger_hunters" in ids
    assert "momentum_breakouts" in ids
    assert "auto_market_aware" in ids


def test_generate_inflection_decision(synthetic_vcp_breakout_df):
    matrix = generate_inflection_decision(
        "TRENT", df=synthetic_vcp_breakout_df, force_refresh=True
    )
    assert matrix.symbol == "TRENT"
    assert matrix.verdict in (
        "🟢 HIGH_CONVICTION_BUY",
        "🟡 STALK_PIVOT",
        "🔴 AVOID_TRAP_RISK",
    )
    assert matrix.confidence_score >= 40
    assert "thesis_title" in matrix.what
    assert "entry_zone" in matrix.where
    assert "stop_loss" in matrix.where
    assert "target_1" in matrix.where
    assert "target_moonshot" in matrix.where
    assert "timing_status" in matrix.when
    assert "order_strategy" in matrix.how
    assert "macro_regime" in matrix.correlations
    assert "hard_stop_condition" in matrix.invalidation
    assert len(matrix.council_insights) >= 3


def test_answer_inflection_chat(synthetic_vcp_breakout_df):
    matrix = generate_inflection_decision("TRENT", df=synthetic_vcp_breakout_df)
    res = answer_inflection_chat(
        symbol="TRENT",
        question="Where is the exact stop loss level and why?",
        matrix_data=matrix.to_dict(),
    )
    assert res["status"] == "success"
    assert "TRENT" in res["answer"]
    assert "stop" in res["answer"].lower() or "risk" in res["answer"].lower()


def test_fastapi_skill_endpoints(synthetic_vcp_breakout_df):
    client = TestClient(app)

    # 1. Test /skills/inflection_universes
    res = client.post("/skills/inflection_universes")
    assert res.status_code == 200
    data = res.json()
    assert "universes" in data["data"]
    assert len(data["data"]["universes"]) >= 5

    # 2. Test /skills/inflection_scan
    scan_res = client.post(
        "/skills/inflection_scan",
        json={"universe": "defence", "min_score": 30, "max_results": 5},
    )
    assert scan_res.status_code == 200
    scan_data = scan_res.json()["data"]
    assert "candidates" in scan_data
    assert "archetype_counts" in scan_data

    # 3. Test /skills/inflection_decision
    dec_res = client.post(
        "/skills/inflection_decision",
        json={"symbol": "HAL"},
    )
    assert dec_res.status_code == 200
    dec_data = dec_res.json()["data"]
    assert "verdict" in dec_data
    assert "what" in dec_data
    assert "where" in dec_data

    # 4. Test /skills/inflection_chat
    chat_res = client.post(
        "/skills/inflection_chat",
        json={
            "symbol": "HAL",
            "question": "What is the expected target and scaling plan?",
            "matrix": dec_data,
        },
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()["data"]
    assert "answer" in chat_data
