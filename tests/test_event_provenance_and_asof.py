"""
tests/test_event_provenance_and_asof.py
───────────────────────────────────────
Verifies event/news provenance fields (publication timestamp, first-seen timestamp,
revision ID, and source entity) and ensures as-of filtering prevents lookahead bias
in historical replay and backtests (S07).
"""

from __future__ import annotations

from datetime import datetime, timezone

from market.events import (
    EarningsEvent,
    filter_events_as_of,
)
from market.earnings import (
    EarningsEntry,
    filter_earnings_as_of,
)
from market.news import (
    NewsItem,
    filter_news_as_of,
)


def test_events_asof_filtering():
    """Verify market events are strictly filtered by as_of bar timestamp."""
    ev1 = EarningsEvent(
        symbol="TCS",
        company="Tata Consultancy Services",
        date="2026-10-15",
        purpose="Quarterly Results",
        published_at="2026-10-15T16:30:00+05:30",
        first_seen_at="2026-10-15T16:31:00+05:30",
        revision_id="rev-001",
        source_entity="NSE",
    )
    ev2 = EarningsEvent(
        symbol="INFY",
        company="Infosys",
        date="2026-10-18",
        purpose="Quarterly Results",
        published_at="2026-10-18T16:00:00+05:30",
        first_seen_at="2026-10-18T16:02:00+05:30",
        revision_id="rev-002",
        source_entity="NSE",
    )

    events = [ev1, ev2]

    # Bar timestamp before INFY announcement
    bar_ts = "2026-10-16T09:15:00+05:30"
    as_of_events = filter_events_as_of(events, bar_ts)
    assert len(as_of_events) == 1
    assert as_of_events[0].symbol == "TCS"

    # Bar timestamp after INFY announcement
    bar_ts_later = "2026-10-19T09:15:00+05:30"
    all_events = filter_events_as_of(events, bar_ts_later)
    assert len(all_events) == 2


def test_earnings_entry_asof_filtering():
    """Verify earnings entries filter out future announcements during replay."""
    e1 = EarningsEntry(
        symbol="RELIANCE",
        result_date="2026-10-20",
        quarter="Q2FY27",
        published_at="2026-10-20T18:00:00Z",
        first_seen_at="2026-10-20T18:05:00Z",
        revision_id="rel-q2",
    )
    e2 = EarningsEntry(
        symbol="HDFCBANK",
        result_date="2026-10-25",
        quarter="Q2FY27",
        published_at="2026-10-25T14:00:00Z",
        first_seen_at="2026-10-25T14:02:00Z",
        revision_id="hdfc-q2",
    )

    entries = [e1, e2]

    # As of Oct 22, only RELIANCE should be visible
    as_of_dt = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
    filtered = filter_earnings_as_of(entries, as_of_dt)
    assert len(filtered) == 1
    assert filtered[0].symbol == "RELIANCE"


def test_news_item_asof_filtering_and_provenance():
    """Verify news items capture first_seen_at and prevent future news leakage."""
    item1 = NewsItem(
        title="RBI keeps repo rate unchanged",
        source="ET Markets",
        url="https://example.com/rbi",
        published="2026-10-06T10:00:00Z",
        first_seen_at="2026-10-06T10:01:15Z",
    )
    item2 = NewsItem(
        title="Crude surges on geopolitical tension",
        source="MoneyControl",
        url="https://example.com/crude",
        published="2026-10-10T08:30:00Z",
        first_seen_at="2026-10-10T08:31:00Z",
    )

    # Check auto-aliasing of published_at and source_entity
    assert item1.published_at == "2026-10-06T10:00:00Z"
    assert item1.source_entity == "ET Markets"

    # Filter as of Oct 8
    as_of_dt = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    news_asof = filter_news_as_of([item1, item2], as_of_dt)
    assert len(news_asof) == 1
    assert news_asof[0].title == "RBI keeps repo rate unchanged"
