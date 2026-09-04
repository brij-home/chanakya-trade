import pytest
import asyncio
from web.skills import _ActiveAnalysisHub, _in_flight_hubs, skill_analyze_stream


@pytest.mark.anyio
async def test_active_analysis_hub_event_broadcasting():
    hub = _ActiveAnalysisHub("TESTSYM", "NSE", "stream_123")
    q1 = asyncio.Queue()
    q2 = asyncio.Queue()
    hub.subscribers.add(q1)
    hub.subscribers.add(q2)

    event = {"type": "analyst", "name": "Buffett", "verdict": "BULLISH"}
    hub.history.append(event)
    for q in list(hub.subscribers):
        await q.put(event)

    ev1 = await q1.get()
    ev2 = await q2.get()
    assert ev1 == event
    assert ev2 == event
    assert len(hub.history) == 1


@pytest.mark.anyio
async def test_skill_analyze_stream_deduplicates_in_flight():
    sym = "DEDUPTEST"
    exch = "NSE"
    hub_key = f"{sym}_{exch}"

    # Verify no hub exists initially
    assert hub_key not in _in_flight_hubs

    # Simulate an active hub already running
    existing_hub = _ActiveAnalysisHub(sym, exch, "stream_existing")
    _in_flight_hubs[hub_key] = existing_hub

    try:
        # Calling skill_analyze_stream for the same symbol should join the existing hub
        response = await skill_analyze_stream(symbol=sym, exchange=exch, force=False)
        assert response.status_code == 200
        # The existing hub should now have the new subscriber queue
        assert len(existing_hub.subscribers) == 1
    finally:
        # Cleanup
        _in_flight_hubs.pop(hub_key, None)
