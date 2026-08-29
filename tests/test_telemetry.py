"""
tests/test_telemetry.py
───────────────────────
Unit tests for engine/telemetry.py observability and self-learning telemetry.
"""

import pytest
from engine.telemetry import (
    record_event,
    get_recent_events,
    get_telemetry_summary,
    clear_telemetry,
    EVENT_LLM_FAILOVER,
    EVENT_LLM_COOLDOWN,
    EVENT_QUANT_FALLBACK,
    EVENT_DATA_FALLBACK,
)


@pytest.fixture(autouse=True)
def clean_telemetry():
    clear_telemetry()
    yield
    clear_telemetry()


def test_record_and_get_recent_events():
    record_event(
        event_type=EVENT_LLM_FAILOVER,
        component="gemini_provider",
        action_taken="Rotated to key #2",
        reason="Rate limit 429",
        details={"model": "gemini-3.6-flash"},
        severity="INFO",
    )
    record_event(
        event_type=EVENT_QUANT_FALLBACK,
        component="persona_agent",
        action_taken="Used rule-based signal",
        reason="LLM timeout",
        details={"persona": "buffett"},
        severity="WARNING",
    )

    events = get_recent_events(limit=10)
    assert len(events) == 2
    assert events[0]["event_type"] == EVENT_QUANT_FALLBACK
    assert events[1]["event_type"] == EVENT_LLM_FAILOVER


def test_telemetry_summary_and_recommendations():
    # Record multiple events to trigger recommendations
    for _ in range(4):
        record_event(
            event_type=EVENT_LLM_COOLDOWN,
            component="gemini_provider",
            action_taken="Key cooldown 45s",
            reason="Quota exceeded",
            severity="WARNING",
        )
    record_event(
        event_type=EVENT_QUANT_FALLBACK,
        component="persona_agent",
        action_taken="Fallback to quant",
        reason="API 503",
        severity="WARNING",
    )

    summary = get_telemetry_summary()
    assert summary["total_events_captured"] == 5
    assert summary["event_breakdown"][EVENT_LLM_COOLDOWN] == 4
    assert summary["event_breakdown"][EVENT_QUANT_FALLBACK] == 1
    assert len(summary["recommendations"]) >= 2
    assert any("Frequent LLM cooldowns" in r for r in summary["recommendations"])
