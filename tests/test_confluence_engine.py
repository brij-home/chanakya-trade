"""
tests/test_confluence_engine.py
────────────────────────────────
Unit and invariant tests for Institutional Confluence Engine.
"""

import pandas as pd
import pytest

from analysis.confluence_engine import find_confluence_clusters, ConfluenceCluster


@pytest.fixture
def synthetic_ohlcv():
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    closes = [2000.0 + i * 5.0 for i in range(80)] + [2400.0 - i * 10.0 for i in range(20)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 15.0 for c in closes],
            "low": [c - 15.0 for c in closes],
            "close": closes,
            "volume": [100000] * 100,
        },
        index=dates,
    )


def test_find_confluence_clusters_bullish(synthetic_ohlcv):
    clusters = find_confluence_clusters(
        symbol="RELIANCE",
        ltp=2250.0,
        direction="BULLISH",
        df=synthetic_ohlcv,
    )
    assert isinstance(clusters, list)
    if clusters:
        c = clusters[0]
        assert isinstance(c, ConfluenceCluster)
        assert c.direction == "BULLISH"
        assert c.cluster_type == "DEMAND_CLUSTER"
        assert c.invalidation_stop < c.bottom
        assert c.midpoint > 0


def test_find_confluence_clusters_bearish(synthetic_ohlcv):
    clusters = find_confluence_clusters(
        symbol="RELIANCE",
        ltp=2250.0,
        direction="BEARISH",
        df=synthetic_ohlcv,
    )
    assert isinstance(clusters, list)
    if clusters:
        c = clusters[0]
        assert isinstance(c, ConfluenceCluster)
        assert c.direction == "BEARISH"
        assert c.cluster_type == "SUPPLY_CLUSTER"
        assert c.invalidation_stop > c.top
        assert c.midpoint > 0


def test_confluence_cluster_to_dict():
    c = ConfluenceCluster(
        symbol="NIFTY",
        direction="BULLISH",
        cluster_type="DEMAND_CLUSTER",
        top=24200.0,
        bottom=24100.0,
        midpoint=24150.0,
        confluence_score=85,
        factors_count=3,
        confluence_factors=["Demand OB", "VPOC", "Put Wall"],
        has_order_block=True,
        has_volume_poc=True,
        has_oi_wall=True,
        is_prime_cluster=True,
        invalidation_stop=24050.0,
        distance_to_ltp_pct=-0.2,
        summary="Prime Demand Cluster",
    )
    d = c.to_dict()
    assert d["symbol"] == "NIFTY"
    assert d["confluence_score"] == 85
    assert d["is_prime_cluster"] is True
