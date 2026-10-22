"""
tests/test_tbt_opportunistic_sector_leaders.py
─────────────────────────────────────────────
Deterministic tests for Opportunistic Sector Leaders Baseline in Fyers 50-Depth TBT Manager:
  1. Automated spare slot utilization with top sector momentum leaders.
  2. Strict Preemption Hierarchy: IN_FLIGHT > JIT Alert Scouts > CORE_GRID > SECTOR_LEADER_SCOUT.
  3. Preemption & slot restoration lifecycle.
  4. Proper role classification as SECTOR_LEADER_SCOUT in get_active_slots_status.
"""

import time
import pytest
from market.fyers_tbt_manager import FyersTbtManager, MAX_TBT_SYMBOLS


@pytest.fixture
def tbt_mgr():
    mgr = FyersTbtManager()
    with mgr._slots_lock:
        mgr._in_flight.clear()
        mgr._core_grid = ["NSE:NIFTY26OCTFUT", "NSE:BANKNIFTY26OCTFUT", "NSE:MIDCPNIFTY26OCTFUT"]
        mgr._todays_expiry.clear()
        mgr._scout.clear()
        mgr._sector_scouts.clear()
        mgr._last_sector_scouts_refresh = 0.0
        mgr._evicted_cooldowns.clear()
        mgr._current_session = "EQUITY_NFO"
        mgr._slot_allocated_at.clear()
        mgr._workers.clear()
        mgr._subscribed.clear()
    return mgr


def test_sector_leaders_resolution_and_caching(tbt_mgr):
    """Verify _get_cached_sector_scouts returns valid F&O stock futures and caches them."""
    sector_leaders = tbt_mgr._get_cached_sector_scouts(force_refresh=True)

    assert isinstance(sector_leaders, list)
    assert len(sector_leaders) >= 5
    # Must contain top benchmark heavyweights or sector momentum leaders
    assert any("RELIANCE" in s for s in sector_leaders)
    assert any("HDFCBANK" in s or "ICICIBANK" in s for s in sector_leaders)
    # All symbols must be valid tradable NSE futures
    for s in sector_leaders:
        assert s.startswith("NSE:")
        assert s.endswith("FUT")

    # Second call should use cache without error
    cached = tbt_mgr._get_cached_sector_scouts(force_refresh=False)
    assert cached == sector_leaders


def test_spare_slots_auto_filled_by_sector_leaders(tbt_mgr):
    """When in-flight and dynamic scouts are empty, sector leaders fill up to MAX_TBT_SYMBOLS (15)."""
    with tbt_mgr._slots_lock:
        tbt_mgr._in_flight.clear()
        tbt_mgr._scout.clear()

    desired = tbt_mgr.compute_desired_subscriptions()

    # Total desired subscriptions must be full (15 slots) or utilize all available sector leaders
    assert len(desired) == MAX_TBT_SYMBOLS
    # First 3 are benchmark futures
    assert desired[0] == "NSE:NIFTY26OCTFUT"
    assert desired[1] == "NSE:BANKNIFTY26OCTFUT"
    assert desired[2] == "NSE:MIDCPNIFTY26OCTFUT"
    # Remaining slots are populated by sector leaders
    assert len(desired[3:]) == 12


def test_strict_preemption_hierarchy_when_jit_alert_fires(tbt_mgr):
    """
    When an alert promotes a JIT scout, it immediately takes slot priority,
    evicting the lowest-priority sector leader.
    """
    desired_initial = tbt_mgr.compute_desired_subscriptions()
    assert len(desired_initial) == MAX_TBT_SYMBOLS

    # Now promote a JIT alert scout (e.g. an SMC or Breakout setup candidate)
    jit_sym = "NSE:COFORGE26OCTFUT"
    tbt_mgr.promote_jit_scout(jit_sym, duration_sec=60.0, reason="SMC_ORDER_BLOCK")

    desired_with_jit = tbt_mgr.compute_desired_subscriptions()
    assert len(desired_with_jit) == MAX_TBT_SYMBOLS

    # The JIT scout must be included in the desired slots
    assert jit_sym in desired_with_jit
    # Core grid is preserved
    assert "NSE:NIFTY26OCTFUT" in desired_with_jit
    assert "NSE:BANKNIFTY26OCTFUT" in desired_with_jit
    assert "NSE:MIDCPNIFTY26OCTFUT" in desired_with_jit

    # When the JIT scout is cleared, sector leader reclaims the slot
    with tbt_mgr._slots_lock:
        tbt_mgr._scout.pop(jit_sym, None)

    desired_after_release = tbt_mgr.compute_desired_subscriptions()
    assert len(desired_after_release) == MAX_TBT_SYMBOLS
    assert jit_sym not in desired_after_release


def test_role_classification_in_active_slots_status(tbt_mgr):
    """get_active_slots_status accurately assigns SECTOR_LEADER_SCOUT role."""
    tbt_mgr.sync_subscriptions()
    status = tbt_mgr.get_active_slots_status()

    assert "slots" in status
    slots = status["slots"]
    assert len(slots) > 0

    roles = [s["role"] for s in slots]
    # Core grid must be labeled CORE_GRID
    assert "CORE_GRID" in roles
    # Sector leaders must be labeled SECTOR_LEADER_SCOUT
    assert "SECTOR_LEADER_SCOUT" in roles
    assert "sector_scouts" in status
    assert len(status["sector_scouts"]) > 0


def test_cooldown_excludes_evicted_symbol(tbt_mgr):
    """An evicted sector scout on cooldown must not be immediately re-subscribed."""
    sector_leaders = tbt_mgr._get_cached_sector_scouts()
    assert len(sector_leaders) > 0

    evicted = sector_leaders[0]
    with tbt_mgr._slots_lock:
        tbt_mgr._evicted_cooldowns[evicted] = time.time() + 300.0

    desired = tbt_mgr.compute_desired_subscriptions()
    assert evicted not in desired
