"""
tests/test_multibagger_pipeline.py
──────────────────────────────────
Comprehensive deterministic test suite for:
  1. Minervini 8-Point Trend Template Evaluator
  2. Stan Weinstein 4-Stage Classifier
  3. Minervini Volatility Contraction Pattern (VCP) Detector
  4. 3-Horizon Multibagger Scoring (Short, Mid, Long Term)
  5. High-Performance Universe Batch Scanner
  6. Real-Time Multibagger Alerting Engine
  7. FastAPI Sidecar Skills Endpoints
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.multibagger import (
    classify_weinstein_stage,
    detect_vcp,
    evaluate_long_term_horizon,
    evaluate_mid_term_horizon,
    evaluate_short_term_horizon,
    evaluate_trend_template,
    scan_multibagger_opportunity,
)
from analysis.multibagger_scanner import scan_multibagger_universe
from engine.multibagger_alerts import MultibaggerAlertManager
from web.api import app


def _create_synthetic_superperformer_df(n: int = 260) -> pd.DataFrame:
    """Generates an idealized Minervini Stage 2 upward trending DataFrame."""
    np.random.seed(42)
    # Strong upward trend from 100 to 280
    base = np.linspace(100, 280, n)
    noise = np.random.normal(0, 1.5, n)
    closes = base + noise
    highs = closes + np.random.uniform(0.5, 2.5, n)
    lows = closes - np.random.uniform(0.5, 2.5, n)
    volumes = np.random.uniform(100000, 500000, n)
    volumes[-5:] *= 2.5  # volume surge at breakout

    dates = pd.date_range(end="2026-08-30", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes * 0.99,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


def _create_synthetic_downtrend_df(n: int = 260) -> pd.DataFrame:
    """Generates a Stage 4 declining DataFrame."""
    np.random.seed(42)
    base = np.linspace(300, 120, n)
    noise = np.random.normal(0, 1.5, n)
    closes = base + noise
    highs = closes + np.random.uniform(0.5, 2.5, n)
    lows = closes - np.random.uniform(0.5, 2.5, n)
    volumes = np.random.uniform(50000, 150000, n)

    dates = pd.date_range(end="2026-08-30", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes * 1.01,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


# ── 1. Minervini & Weinstein Core Tests ─────────────────────────


def test_minervini_trend_template_superperformer():
    df = _create_synthetic_superperformer_df()
    passed, criteria = evaluate_trend_template(df)

    assert passed >= 6, f"Expected superperformer to pass >=6 rules, got {passed}"
    assert len(criteria) == 8


def test_weinstein_stage_classifier():
    df_up = _create_synthetic_superperformer_df()
    stage_up, conf_up = classify_weinstein_stage(df_up)
    assert stage_up == "STAGE_2_MARKUP"
    assert conf_up >= 80

    df_down = _create_synthetic_downtrend_df()
    stage_down, conf_down = classify_weinstein_stage(df_down)
    assert stage_down == "STAGE_4_MARKDOWN"
    assert conf_down >= 80


def test_vcp_contraction_detection():
    # Construct a synthetic 3-wave contraction (depths: 18% -> 8% -> 3%)
    closes = np.ones(50) * 100
    highs = np.ones(50) * 100
    lows = np.ones(50) * 100

    # Wave 1 (bars 0-15): High 100, Low 82 (18% depth)
    highs[0:15] = 100
    lows[0:15] = 82
    closes[0:15] = 90

    # Wave 2 (bars 15-30): High 100, Low 92 (8% depth)
    highs[15:30] = 100
    lows[15:30] = 92
    closes[15:30] = 96

    # Wave 3 (bars 30-45): High 100, Low 97 (3% depth)
    highs[30:45] = 100
    lows[30:45] = 97
    closes[30:45] = 99.5

    df_vcp = pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.ones(50) * 1000,
        }
    )

    is_vcp, contractions, pivot = detect_vcp(df_vcp)
    assert is_vcp is True
    assert len(contractions) == 3
    assert pivot == 100.0


# ── 2. 3-Horizon Scoring Tests ─────────────────────────────────


def test_3_horizon_evaluations():
    df = _create_synthetic_superperformer_df()
    ltp = float(df["close"].iloc[-1])

    # Short term
    st_score, st_verdict, st_details = evaluate_short_term_horizon(df, ltp, True, ltp * 1.01, 85)
    assert st_score >= 70
    assert "rvol_20d" in st_details

    # Mid term
    mt_score, mt_verdict, mt_details = evaluate_mid_term_horizon(df, ltp, 8, "STAGE_2_MARKUP", 90)
    assert mt_score >= 80
    assert mt_verdict == "🚀 STAGE_2_SUPERPERFORMER"

    # Long term
    lt_score, lt_verdict, lt_details = evaluate_long_term_horizon("TRENT", df, ltp, True)
    assert lt_score >= 75
    assert lt_details["forensic_safe"] is True


def test_scan_multibagger_opportunity_full():
    df = _create_synthetic_superperformer_df()
    report = scan_multibagger_opportunity("TRENT", df=df)

    assert report.symbol == "TRENT"
    assert report.multibagger_score >= 70
    assert report.best_horizon in ("SHORT_TERM", "MID_TERM", "LONG_TERM")
    assert report.execution_ticket["action"] == "LONG (BUY)"
    assert report.execution_ticket["entry_price"] > 0
    assert report.execution_ticket["stop_loss"] < report.execution_ticket["entry_price"]


# ── 3. Universe Batch Scanner Tests ─────────────────────────────


def test_multibagger_universe_scanner():
    df_synthetic = _create_synthetic_superperformer_df()
    cache = {
        "TRENT": df_synthetic,
        "DIXON": df_synthetic,
        "HAL": df_synthetic,
        "BEL": df_synthetic,
        "BSE": df_synthetic,
    }

    result = scan_multibagger_universe(
        universe="multibagger_hunters",
        horizon="ALL_HORIZONS",
        min_conviction=50,
        max_results=5,
        df_cache=cache,
    )

    assert result.total_scanned >= 5
    assert len(result.candidates) > 0
    top = result.candidates[0]
    assert top.multibagger_score >= 50
    assert top.conviction_tier in ("🟢 HIGH_CONVICTION", "🟡 STALK_RADAR", "⚪ DEVELOPING")


# ── 4. Real-Time Alert Engine Tests ─────────────────────────────


def test_multibagger_alert_manager():
    mgr = MultibaggerAlertManager()
    mgr.clear_alerts()

    df = _create_synthetic_superperformer_df()
    report = scan_multibagger_opportunity("DIXON", df=df)

    alerts = mgr.check_and_generate_alerts(report, prev_stage="STAGE_1_BASE")
    assert len(alerts) >= 1
    assert alerts[0].symbol == "DIXON"

    recent = mgr.get_recent_alerts(limit=10)
    assert len(recent) >= 1


# ── 5. FastAPI Endpoints Integration Tests ───────────────────────


def test_fastapi_multibagger_endpoints():
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # 1. Universes list
    res_u = client.get("/skills/multibagger_universes")
    assert res_u.status_code == 200
    data_u = res_u.json()
    assert "universes" in data_u["data"]
    assert data_u["data"]["total_universes"] >= 5

    # 2. Alerts query
    res_a = client.get("/skills/multibagger_alerts")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert "alerts" in data_a["data"]
