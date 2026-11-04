"""
tests/test_lockout_composite_keys.py
───────────────────────────────────
Unit tests for institutional two-strike learning lockouts:
1. Composite keys (symbol:direction) preventing alternating direction overwrites.
2. Invalidation event idempotency (same event_id does not double-count strikes).
3. Session boundary expiry (session_id changes clear intraday lockouts).
4. Injected clock & mandatory 15-minute refractory window before structural reclaim.
5. Restart persistence to symbol_lockouts.json.
"""

from __future__ import annotations

import pytest

from engine.learning_engine import PatternLearningEngine


class MockClock:
    def __init__(self, initial_time: float = 1793507400.0):
        self.current_time = initial_time

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


@pytest.fixture
def mock_clock():
    return MockClock(1793507400.0)


@pytest.fixture
def lockout_engine(tmp_path, mock_clock, monkeypatch):
    """Provides a fresh PatternLearningEngine backed by temporary storage and mock clock."""
    lock_file = tmp_path / "symbol_lockouts.json"
    monkeypatch.setattr("engine.learning_engine.get_pattern_lockouts_file", lambda: lock_file)
    monkeypatch.setattr(
        "engine.learning_engine.get_pattern_memory_file", lambda: tmp_path / "mem.json"
    )
    monkeypatch.setattr(
        "engine.learning_engine.get_pattern_outcomes_file", lambda: tmp_path / "out.json"
    )
    monkeypatch.setattr(
        "engine.learning_engine.get_pattern_post_mortems_file", lambda: tmp_path / "pm.json"
    )

    return PatternLearningEngine(clock=mock_clock, refractory_seconds=900.0)


def test_alternating_directions_cannot_overwrite_lockouts(lockout_engine):
    """BULLISH and BEARISH lockouts on the same symbol must coexist independently."""
    eng = lockout_engine

    # 1. Place NIFTY on BULLISH lockout
    lock_bull = eng.set_symbol_lockout(
        symbol="NIFTY",
        direction="BULLISH",
        duration_seconds=5400.0,
        reason="Bullish stop breach",
        session_id="20261101",
    )
    assert lock_bull["direction"] == "BULLISH"

    # 2. Place NIFTY on BEARISH lockout 5 minutes later
    lock_bear = eng.set_symbol_lockout(
        symbol="NIFTY",
        direction="BEARISH",
        duration_seconds=5400.0,
        reason="Bearish stop breach",
        session_id="20261101",
    )
    assert lock_bear["direction"] == "BEARISH"

    # 3. Both directions must remain locked out independently!
    is_locked_bull, reason_bull = eng.is_symbol_locked_out(
        "NIFTY", direction="BULLISH", session_id="20261101"
    )
    assert is_locked_bull is True
    assert "Bullish stop breach" in reason_bull or "Recent invalidation" in reason_bull

    is_locked_bear, reason_bear = eng.is_symbol_locked_out(
        "NIFTY", direction="BEARISH", session_id="20261101"
    )
    assert is_locked_bear is True
    assert "Bearish stop breach" in reason_bear or "Recent invalidation" in reason_bear


def test_invalidation_event_idempotency(lockout_engine):
    """Repeated reports with the same event_id must not double-increment strike counter."""
    eng = lockout_engine

    # Report invalidation event-1
    l1 = eng.set_symbol_lockout(
        symbol="RELIANCE",
        direction="BULLISH",
        event_id="evt-rel-001",
        session_id="20261101",
    )
    assert l1["invalidation_count"] == 1
    assert l1["is_hard_session_lockout"] is False

    # Duplicate report of event-1 (e.g. from network retry or multi-consumer webhook)
    l1_dup = eng.set_symbol_lockout(
        symbol="RELIANCE",
        direction="BULLISH",
        event_id="evt-rel-001",
        session_id="20261101",
    )
    assert l1_dup["invalidation_count"] == 1
    assert l1_dup["is_hard_session_lockout"] is False

    # Second distinct event triggers strike 2 -> hard session lockout
    l2 = eng.set_symbol_lockout(
        symbol="RELIANCE",
        direction="BULLISH",
        event_id="evt-rel-002",
        session_id="20261101",
    )
    assert l2["invalidation_count"] == 2
    assert l2["is_hard_session_lockout"] is True


def test_session_boundary_clears_lockout(lockout_engine):
    """Lockouts set for session 20261101 must not block setups on session 20261102."""
    eng = lockout_engine

    eng.set_symbol_lockout(
        symbol="BANKNIFTY",
        direction="BULLISH",
        session_id="20261101",
    )

    # Locked in same session
    locked_same, _ = eng.is_symbol_locked_out(
        "BANKNIFTY", direction="BULLISH", session_id="20261101"
    )
    assert locked_same is True

    # Cleared across session boundary
    locked_next, _ = eng.is_symbol_locked_out(
        "BANKNIFTY", direction="BULLISH", session_id="20261102"
    )
    assert locked_next is False


def test_mandatory_refractory_window_before_structural_reclaim(lockout_engine, mock_clock):
    """Reclaim is strictly disabled during the 15-minute refractory window to eliminate noise churn."""
    eng = lockout_engine

    eng.set_symbol_lockout(
        symbol="TATASTEEL",
        direction="BULLISH",
        reclaim_level=150.0,
        session_id="20261101",
    )

    # 1. Price is above reclaim (152.0) after only 2 minutes (120s < 900s refractory)
    mock_clock.advance(120.0)
    is_locked_early, _ = eng.is_symbol_locked_out(
        "TATASTEEL", direction="BULLISH", ltp=152.0, vwap=151.0, session_id="20261101"
    )
    assert is_locked_early is True  # Refractory window blocks early reclaim!

    # 2. Advance clock past 15 minutes (950s total elapsed)
    mock_clock.advance(830.0)
    is_locked_mature, _ = eng.is_symbol_locked_out(
        "TATASTEEL", direction="BULLISH", ltp=152.0, vwap=151.0, session_id="20261101"
    )
    assert is_locked_mature is False  # Reclaim successfully unlocks after refractory period!


def test_lockout_restart_persistence(tmp_path, mock_clock, monkeypatch):
    """Lockouts must survive process restarts via symbol_lockouts.json persistence."""
    lock_file = tmp_path / "symbol_lockouts.json"
    monkeypatch.setattr("engine.learning_engine.get_pattern_lockouts_file", lambda: lock_file)
    monkeypatch.setattr(
        "engine.learning_engine.get_pattern_memory_file", lambda: tmp_path / "mem.json"
    )
    monkeypatch.setattr(
        "engine.learning_engine.get_pattern_outcomes_file", lambda: tmp_path / "out.json"
    )
    monkeypatch.setattr(
        "engine.learning_engine.get_pattern_post_mortems_file", lambda: tmp_path / "pm.json"
    )

    # Instance 1 sets a lockout
    eng1 = PatternLearningEngine(clock=mock_clock, refractory_seconds=900.0)
    eng1.set_symbol_lockout(
        symbol="INFY",
        direction="BEARISH",
        duration_seconds=3600.0,
        session_id="20261101",
    )
    assert lock_file.exists()

    # Instance 2 starts up and reloads from disk
    eng2 = PatternLearningEngine(clock=mock_clock, refractory_seconds=900.0)
    is_locked, reason = eng2.is_symbol_locked_out(
        "INFY", direction="BEARISH", session_id="20261101"
    )
    assert is_locked is True
    assert "BEARISH" in str(eng2.get_locked_out_symbols())
