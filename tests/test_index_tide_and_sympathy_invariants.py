"""
tests/test_index_tide_and_sympathy_invariants.py
────────────────────────────────────────────────
Deterministic invariant tests for:
  1. Gate 31: Institutional Index Tide & Regime Alignment Gate
     - Suppresses non-decoupled equity shorts when benchmark is advancing above VWAP.
     - Suppresses non-decoupled equity longs when benchmark is plunging below VWAP.
     - Exempts true statistical volume decouplers (RVOL >= 2.5x, |chg| >= 2.5%).
     - Resolves banking stocks to BANKNIFTY authority.
  2. Thematic Peer Sympathy Hardening (Invariant 26 Concurrency)
     - Enforces max 2 peer sympathy alerts per sector per session date.
     - Enforces true Time-of-Day RVOL confirmation (eliminates fake raw volume bypass).
     - Incorporates Gate 31 Index Tide evaluation.
"""

from unittest.mock import MagicMock
import pytest

from engine.market_regime_gate import (
    evaluate_index_tide_gate,
    clear_index_tide_cache,
)
from engine.thematic_peer_sympathy import (
    ThematicPeerSympathyEngine,
    SectorLeaderActivation,
)


@pytest.fixture(autouse=True)
def _isolate_test_state():
    clear_index_tide_cache()
    yield
    clear_index_tide_cache()


def test_index_tide_gate_vetoes_bearish_breakdown_into_advancing_benchmark():
    """Bearish equity setup must be suppressed when NIFTY is advancing above VWAP."""
    mock_nifty = MagicMock()
    mock_nifty.last_price = 23050.0
    mock_nifty.vwap = 23020.0
    mock_nifty.change_pct = 0.51

    quotes_map = {"NSE:NIFTY": mock_nifty}

    res = evaluate_index_tide_gate(
        symbol="ONGC",
        direction="BEARISH",
        ltp=245.0,
        rvol=1.3,
        change_pct=-0.9,
        quotes_map=quotes_map,
    )
    assert res.is_vetoed is True, "Must veto bearish breakdown when NIFTY is advancing above VWAP"
    assert "Index Tide Veto" in (res.veto_reason or "")
    assert res.is_decoupled is False


def test_index_tide_gate_vetoes_bullish_breakout_into_plunging_benchmark():
    """Bullish equity setup must be suppressed when NIFTY is liquidating below VWAP."""
    mock_nifty = MagicMock()
    mock_nifty.last_price = 22700.0
    mock_nifty.vwap = 22850.0
    mock_nifty.change_pct = -0.75

    quotes_map = {"NSE:NIFTY": mock_nifty}

    res = evaluate_index_tide_gate(
        symbol="TATASTEEL",
        direction="BULLISH",
        ltp=155.0,
        rvol=1.4,
        change_pct=1.1,
        quotes_map=quotes_map,
    )
    assert res.is_vetoed is True, "Must veto bullish breakout when NIFTY is liquidating below VWAP"
    assert "falling" in (res.veto_reason or "")


def test_index_tide_gate_exempts_explosive_volume_decoupler():
    """True statistical decouplers with explosive RVOL (>= 2.5x) or major move (>= 2.5%) are exempt."""
    mock_nifty = MagicMock()
    mock_nifty.last_price = 23050.0
    mock_nifty.vwap = 23020.0
    mock_nifty.change_pct = 0.51
    quotes_map = {"NSE:NIFTY": mock_nifty}

    # 1. High RVOL Decoupler
    res_rvol = evaluate_index_tide_gate(
        symbol="BPCL",
        direction="BEARISH",
        ltp=310.0,
        rvol=3.2,  # Explosive RVOL
        change_pct=-1.5,
        quotes_map=quotes_map,
    )
    assert res_rvol.is_vetoed is False, "Explosive volume decoupler must not be vetoed"
    assert res_rvol.is_decoupled is True

    # 2. Major Price Mover Decoupler
    res_pct = evaluate_index_tide_gate(
        symbol="INOXWIND",
        direction="BEARISH",
        ltp=55.0,
        rvol=1.6,
        change_pct=-4.5,  # Major move
        quotes_map=quotes_map,
    )
    assert res_pct.is_vetoed is False, "Major price mover must not be vetoed"
    assert res_pct.is_decoupled is True


def test_index_tide_gate_never_vetoes_benchmark_indices():
    """Benchmark indices themselves (NIFTY, SENSEX, BANKNIFTY) must never be vetoed."""
    for idx in ("NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"):
        res = evaluate_index_tide_gate(symbol=idx, direction="BEARISH")
        assert res.is_vetoed is False, (
            f"Benchmark index {idx} must never be vetoed by index tide gate"
        )


def test_index_tide_gate_routes_banking_stocks_to_banknifty():
    """Banking stocks (e.g. HDFCBANK, SBIN) must resolve to BANKNIFTY as primary authority."""
    mock_bn = MagicMock()
    mock_bn.last_price = 54600.0
    mock_bn.vwap = 54800.0
    mock_bn.change_pct = -0.55

    quotes_map = {"NSE:BANKNIFTY": mock_bn}

    res = evaluate_index_tide_gate(
        symbol="SBIN",
        direction="BULLISH",
        ltp=810.0,
        rvol=1.3,
        change_pct=0.8,
        quotes_map=quotes_map,
    )
    assert res.benchmark_symbol == "BANKNIFTY"
    assert res.is_vetoed is True, "Must veto bullish SBIN breakout when BANKNIFTY is falling"


def test_thematic_sympathy_engine_enforces_max_2_alerts_per_sector():
    """Thematic sympathy engine must enforce strict quota of max 2 alerts per sector per session."""
    engine = ThematicPeerSympathyEngine()
    engine.clear_sympathy_session_state()

    # Activate IT sector
    engine._active_sectors["it"] = SectorLeaderActivation(
        sector_id="it",
        sector_name="Information Technology",
        leader_symbol="TCS",
        direction="BULLISH",
        alert_type="GAMMA_BLAST",
        confidence=90,
    )
    engine._sector_symbols["it"] = ["TCS", "INFY", "WIPRO", "COFORGE", "PERSISTENT"]

    # Provide valid quotes for all peers
    quotes_map = {}
    for sym, ltp in [
        ("INFY", 1850.0),
        ("WIPRO", 520.0),
        ("COFORGE", 6100.0),
        ("PERSISTENT", 5400.0),
    ]:
        q = MagicMock()
        q.last_price = ltp
        q.vwap = ltp * 0.995
        q.change_pct = 1.8
        q.volume = 2000000
        q.average_volume = 1000000
        quotes_map[sym] = q

    alerts_round_1 = engine.evaluate_peer_sympathy(quotes_map=quotes_map)
    # Must only pick top 2 peers
    assert len(alerts_round_1) <= 2, (
        f"Expected at most 2 sympathy alerts, got {len(alerts_round_1)}"
    )

    # Subsequent evaluation in same session must not produce more alerts for the same sector
    alerts_round_2 = engine.evaluate_peer_sympathy(quotes_map=quotes_map)
    assert len(alerts_round_2) == 0, "Sector quota must prevent 3rd sympathy alert in same session"
