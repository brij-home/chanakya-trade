"""
tests/test_universe_velocity_rotator.py
---------------------------------------
Unit and invariant verification for Frontier 4:
In-Memory Universe Velocity Rotator in AutoAlertEngine.

Verifies:
1. Hard invariant: len(targets) <= 15 for any cycle.
2. Successive calls to _get_prioritized_targets(max_targets=15) yield staggered slices of equities.
3. Benchmark indices remain anchored at the top of every cycle.
4. High-velocity surge stocks (volume surge >= 2.5x or |Delta%| >= 3.0%) preemptively jump into the immediate cycle.
5. Unbounded call (max_targets=None) returns full un-sliced universe.
6. Cycle index wrapping after full universe rotation.
"""

from unittest.mock import patch

from engine.auto_alert_engine import AutoAlertEngine
from market.quotes import Quote, _QUOTE_CACHE, _quote_cache_lock

MOCK_INDEX_ORDER = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]


def test_universe_rotator_staggered_slices_and_invariant_limit():
    """Successive calls to _get_prioritized_targets(max_targets=15) yield staggered

    slices of the universe and never exceed 15 targets.
    """
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]

    # 40 synthetic equities
    equities = [f"EQUITY_{i:02d}" for i in range(40)]
    engine.watched_equities = list(equities)

    # Disable cache TTL expiry interference
    engine._prioritized_targets_cache = []
    engine._prioritized_targets_ts = 0.0

    # Ensure FNO_INDEX is allowed, mock index velocity & cycle quotes to prevent external I/O
    with (
        patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=True),
        patch(
            "engine.index_velocity.get_prioritized_index_symbols",
            return_value=list(MOCK_INDEX_ORDER),
        ),
        patch.object(engine, "_get_cycle_quotes", return_value={}),
    ):
        cycle_1 = engine._get_prioritized_targets(max_targets=15)
        cycle_2 = engine._get_prioritized_targets(max_targets=15)
        cycle_3 = engine._get_prioritized_targets(max_targets=15)
        cycle_4 = engine._get_prioritized_targets(max_targets=15)

    # 1. Hard invariant: len <= 15
    assert len(cycle_1) <= 15
    assert len(cycle_2) <= 15
    assert len(cycle_3) <= 15
    assert len(cycle_4) <= 15
    assert len(cycle_1) == 15
    assert len(cycle_2) == 15
    assert len(cycle_3) == 15
    assert len(cycle_4) == 15

    # 2. Benchmark indices anchored at the front (positions 0..4)
    expected_indices = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}
    assert set(cycle_1[:5]) == expected_indices
    assert set(cycle_2[:5]) == expected_indices
    assert set(cycle_3[:5]) == expected_indices
    assert set(cycle_4[:5]) == expected_indices

    # 3. Equities are staggered across batches (positions 5..14)
    eq_1 = cycle_1[5:]
    eq_2 = cycle_2[5:]
    eq_3 = cycle_3[5:]
    eq_4 = cycle_4[5:]

    assert len(eq_1) == 10
    assert len(eq_2) == 10
    assert len(eq_3) == 10
    assert len(eq_4) == 10

    # Disjoint slices
    assert set(eq_1).isdisjoint(set(eq_2))
    assert set(eq_2).isdisjoint(set(eq_3))
    assert set(eq_3).isdisjoint(set(eq_4))

    # All 40 equities covered across 4 cycles (10 * 4 = 40)
    all_covered = set(eq_1) | set(eq_2) | set(eq_3) | set(eq_4)
    assert all_covered == set(equities)


def test_universe_rotator_surge_preemptive_jump():
    """A stock with volume surge >= 2.5x or |Delta%| >= 3.0% jumps preemptively

    into the immediate cycle ahead of its regular scheduled batch.
    """
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    equities = [f"EQUITY_{i:02d}" for i in range(40)]
    engine.watched_equities = list(equities)

    # EQUITY_35 is normally in batch 4 (Cycle index 3).
    # Inject a +4.2% change and 3.0x RVOL into EQUITY_35 in quote cache.
    q_surge = Quote(
        symbol="EQUITY_35", last_price=1042.0, open=1000.0, change_pct=4.20, volume=1500000.0
    )
    q_surge.rvol = 3.1
    with _quote_cache_lock:
        _QUOTE_CACHE["EQUITY_35"] = (
            9999999999.0,
            q_surge,
        )

    try:
        # Reset engine cache
        engine._prioritized_targets_cache = []
        engine._prioritized_targets_ts = 0.0

        with (
            patch(
                "engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=True
            ),
            patch(
                "engine.index_velocity.get_prioritized_index_symbols",
                return_value=list(MOCK_INDEX_ORDER),
            ),
            patch.object(engine, "_get_cycle_quotes", return_value={}),
        ):
            # In Cycle 1 (which normally evaluates batch 0: EQUITY_00 to EQUITY_09),
            # EQUITY_35 must preemptively jump into the immediate cycle!
            cycle_1 = engine._get_prioritized_targets(max_targets=15, cycle_index=0)

        assert len(cycle_1) <= 15
        assert "EQUITY_35" in cycle_1
        # It appears right after the 5 benchmark indices
        assert cycle_1[5] == "EQUITY_35"
    finally:
        with _quote_cache_lock:
            _QUOTE_CACHE.pop("EQUITY_35", None)


def test_universe_rotator_unbounded_call_returns_full_universe():
    """When max_targets=None, returns full unrotated universe without truncating."""
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY"]
    engine.watched_equities = ["RELIANCE", "TCS", "INFY", "SBIN"]

    engine._prioritized_targets_cache = []
    engine._prioritized_targets_ts = 0.0

    with (
        patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=True),
        patch(
            "engine.index_velocity.get_prioritized_index_symbols",
            return_value=["NIFTY", "BANKNIFTY"],
        ),
        patch.object(engine, "_get_cycle_quotes", return_value={}),
    ):
        full_list = engine._get_prioritized_targets(max_targets=None)

    assert len(full_list) == 6
    assert "NIFTY" in full_list
    assert "BANKNIFTY" in full_list
    assert "RELIANCE" in full_list
    assert "TCS" in full_list


def test_universe_rotator_indices_disabled_allocates_all_15_slots_to_equities():
    """When FNO_INDEX is disallowed, all 15 slots in cycle targets are given to equities."""
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    equities = [f"EQUITY_{i:02d}" for i in range(30)]
    engine.watched_equities = list(equities)

    engine._prioritized_targets_cache = []
    engine._prioritized_targets_ts = 0.0

    with (
        patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=False),
        patch.object(engine, "_get_cycle_quotes", return_value={}),
    ):
        cycle_targets = engine._get_prioritized_targets(max_targets=15)

    assert len(cycle_targets) == 15
    # Zero indices present
    assert not any(idx in cycle_targets for idx in engine._watched_indices)
    # 15 equities present
    assert all(sym.startswith("EQUITY_") for sym in cycle_targets)


def test_universe_rotator_wrap_around_and_determinism():
    """Cycles wrap around deterministically after exhausting total batches."""
    engine = AutoAlertEngine()
    engine._watched_indices = ["NIFTY", "BANKNIFTY"]
    # 20 equities -> 2 batches of 10 (when 2 index slots used, 13 equity slots available)
    equities = [f"EQUITY_{i:02d}" for i in range(20)]
    engine.watched_equities = list(equities)

    engine._prioritized_targets_cache = []
    engine._prioritized_targets_ts = 0.0

    with (
        patch("engine.alert_preferences.alert_preferences.is_segment_allowed", return_value=True),
        patch(
            "engine.index_velocity.get_prioritized_index_symbols",
            return_value=["NIFTY", "BANKNIFTY"],
        ),
        patch.object(engine, "_get_cycle_quotes", return_value={}),
    ):
        c0 = engine._get_prioritized_targets(max_targets=15, cycle_index=0)
        c1 = engine._get_prioritized_targets(max_targets=15, cycle_index=1)
        c0_repeat = engine._get_prioritized_targets(max_targets=15, cycle_index=2)

    assert len(c0) <= 15
    assert len(c1) <= 15
    assert len(c0_repeat) <= 15
    # Cycle 2 wraps back to Cycle 0's selection
    assert c0 == c0_repeat
