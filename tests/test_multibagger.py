"""
tests/test_multibagger.py
─────────────────────────
Unit tests for Minervini Trend Template, Weinstein Stage Analysis, and Multibagger Screener.
Runs offline using deterministic synthetic data.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.multibagger import (
    classify_weinstein_stage,
    detect_vcp,
    evaluate_trend_template,
    scan_multibagger_opportunity,
)


@pytest.fixture
def stage2_growth_df():
    """Generates 250 bars of powerful Stage 2 uptrend."""
    dates = pd.date_range(start="2024-01-01", periods=250, freq="D")
    opens, highs, lows, closes, vols = [], [], [], [], []

    for i in range(250):
        # Base price grows from 200 to 800
        c = 200.0 + (i * 2.4) + (10.0 * np.sin(i / 10.0))
        o = c - 1.5
        h = c + 4.0
        l = o - 3.0
        v = 100000 + int(i * 500)
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(v)

    return pd.DataFrame(
        {"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}
    )


def test_evaluate_trend_template(stage2_growth_df):
    passed_count, criteria = evaluate_trend_template(stage2_growth_df)
    assert passed_count >= 6
    assert len(criteria) == 8


def test_classify_weinstein_stage(stage2_growth_df):
    stage, conf = classify_weinstein_stage(stage2_growth_df)
    assert stage == "STAGE_2_MARKUP"
    assert conf >= 80


def test_detect_vcp(stage2_growth_df):
    is_vcp, contractions, pivot = detect_vcp(stage2_growth_df)
    assert isinstance(contractions, list)
    assert pivot > 0


def test_scan_multibagger_opportunity(stage2_growth_df):
    report = scan_multibagger_opportunity("GROWTH_LEADER", df=stage2_growth_df)
    assert report.symbol == "GROWTH_LEADER"
    assert report.multibagger_score >= 60
    assert report.weinstein_stage == "STAGE_2_MARKUP"
    assert report.trend_template_qualified is True
