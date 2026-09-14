"""
tests/test_participant_oi.py
────────────────────────────
Unit tests for market.participant_oi parsing, caching, and fallback metrics.
"""

from market.participant_oi import (
    parse_participant_csv,
    get_latest_participant_oi,
    ParticipantOISummary,
)

SAMPLE_NSE_CSV = """Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Total Long Contracts,Total Short Contracts
Client,150000,120000,850000,150000,320000,280000,150000,180000,1320000,450000
DII,45000,52000,1200000,50000,10000,15000,5000,2000,1255000,104000
FII,65000,115000,1100000,220000,180000,240000,90000,85000,1345000,420000
Pro,55000,28000,350000,80000,120000,90000,385000,298000,525000,406000
TOTAL,315000,315000,3500000,500000,630000,625000,630000,565000,4445000,1380000
"""


def test_parse_participant_csv_computes_ratios():
    summary = parse_participant_csv(SAMPLE_NSE_CSV, as_of_date="2026-09-11")
    assert summary is not None
    assert summary.as_of_date == "2026-09-11"
    assert summary.provenance == "LIVE_NSE"

    # FII: Long = 65000, Short = 115000 -> Total = 180000
    # Ratio = 65000 / 180000 = 0.361
    assert 0.35 <= summary.fii_index_long_ratio <= 0.37
    assert summary.fii_net_index_futures == -50000  # 65000 - 115000
    assert summary.pro_net_index_futures == 27000  # 55000 - 28000
    assert summary.client_net_index_futures == 30000

    # PCR checks
    assert summary.fii_index_pcr > 0.5
    assert summary.records["FII"]["future_index_long"] == 65000


def test_extreme_depressed_fii_triggers_short_squeeze_bias():
    extreme_bearish_csv = """Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short
Client,150000,120000,850000,150000,320000,280000,150000,180000
DII,45000,52000,1200000,50000,10000,15000,5000,2000
FII,15000,95000,1100000,220000,180000,240000,90000,85000
Pro,55000,28000,350000,80000,120000,90000,385000,298000
"""
    summary = parse_participant_csv(extreme_bearish_csv)
    assert summary is not None
    # FII: Long = 15k / 110k = ~13.6%
    assert summary.fii_index_long_ratio <= 0.20
    assert summary.market_bias == "SHORT_SQUEEZE_COILING"


def test_get_latest_participant_oi_returns_valid_object():
    summary = get_latest_participant_oi()
    assert isinstance(summary, ParticipantOISummary)
    assert 0.0 <= summary.fii_index_long_ratio <= 1.0
    assert summary.to_dict()["market_bias"] in (
        "STRONGLY_BULLISH",
        "BULLISH",
        "NEUTRAL",
        "BEARISH",
        "STRONGLY_BEARISH",
        "SHORT_SQUEEZE_COILING",
    )
