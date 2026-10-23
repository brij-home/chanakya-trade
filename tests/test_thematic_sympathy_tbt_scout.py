"""
tests/test_thematic_sympathy_tbt_scout.py
─────────────────────────────────────────
Deterministic unit tests for JIT 50-Depth TBT Scout Pre-Evaluation
in Thematic Basket & Sector Peer Sympathy Engine.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.thematic_peer_sympathy import ThematicPeerSympathyEngine


@pytest.fixture
def sympathy_engine() -> ThematicPeerSympathyEngine:
    return ThematicPeerSympathyEngine()


def test_thematic_sympathy_tbt_scout_promotion_and_clearance(monkeypatch, sympathy_engine):
    """
    When leader RVNL ignites in Railways, peer IRFC qualifies.
    TBT 50-depth shows bullish OBI (+0.35) and clear order book.
    JIT Scout is promoted for 60s and alert is dispatched with microstructure badge.
    """
    leader_alert = AutoAlert(
        alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:RVNL",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ RVNL Ignition",
        summary="RVNL opens strong",
        ltp=450.0,
        trigger_level=450.0,
        target_level=475.0,
        stop_loss=440.0,
        confidence=90,
        is_live=True,
    )
    sympathy_engine.record_leader_alert(leader_alert)

    mock_quotes = {
        "NSE:IRFC": MagicMock(
            symbol="NSE:IRFC",
            ltp=155.0,
            open=150.0,
            close=150.0,
            low=150.0,
            high=155.5,
            volume=20000000,
        )
    }

    mock_depth = {
        "status": "LIVE",
        "symbol": "NSE:IRFC-EQ",
        "obi_50": 0.35,
        "bid_walls": [],
        "ask_walls": [],
    }

    mock_tbt_mgr = MagicMock()
    mock_tbt_mgr.is_connected = True
    mock_tbt_mgr.get_50_depth.return_value = mock_depth

    promoted_scouts = []

    def mock_promote(sym, duration_sec=60.0, reason=""):
        promoted_scouts.append((sym, duration_sec, reason))
        return True

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_tbt_mgr)
    monkeypatch.setattr("market.fyers_tbt_manager.promote_jit_tbt_scout", mock_promote)

    with patch("market.quotes.get_computed_vwap", return_value=152.0):
        alerts = sympathy_engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

    assert len(alerts) == 1
    a = alerts[0]
    assert a.symbol == "IRFC"
    assert a.metrics.get("tbt_scout_active") is True
    assert "TBT 50-Depth Microstructure Cleared" in a.metrics.get("tbt_pre_eval", "")
    assert "Microstructure Cleared" in a.summary
    assert len(promoted_scouts) == 1
    assert promoted_scouts[0][0] == "IRFC"
    assert promoted_scouts[0][1] == 60.0


def test_thematic_sympathy_tbt_scout_veto_on_adverse_seller_obi(monkeypatch, sympathy_engine):
    """
    Bullish peer candidate IRFC is suppressed when 50-depth reveals
    heavy resting seller dominance (OBI 50 = -0.42 < -0.25).
    """
    leader_alert = AutoAlert(
        alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:RVNL",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ RVNL Ignition",
        summary="RVNL opens strong",
        ltp=450.0,
        trigger_level=450.0,
        target_level=475.0,
        stop_loss=440.0,
        confidence=90,
        is_live=True,
    )
    sympathy_engine.record_leader_alert(leader_alert)

    mock_quotes = {
        "NSE:IRFC": MagicMock(
            symbol="NSE:IRFC",
            ltp=155.0,
            open=150.0,
            close=150.0,
            low=150.0,
            high=155.5,
            volume=20000000,
        )
    }

    mock_depth = {
        "status": "LIVE",
        "symbol": "NSE:IRFC-EQ",
        "obi_50": -0.42,  # Heavy adverse seller book!
        "bid_walls": [],
        "ask_walls": [],
    }

    mock_tbt_mgr = MagicMock()
    mock_tbt_mgr.is_connected = True
    mock_tbt_mgr.get_50_depth.return_value = mock_depth

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_tbt_mgr)
    monkeypatch.setattr("market.fyers_tbt_manager.promote_jit_tbt_scout", lambda *a, **k: True)

    with patch("market.quotes.get_computed_vwap", return_value=152.0):
        alerts = sympathy_engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

    # Must be vetoed by OBI filter
    assert len(alerts) == 0


def test_thematic_sympathy_tbt_scout_veto_on_overhead_ask_wall(monkeypatch, sympathy_engine):
    """
    Bullish peer candidate IRFC is suppressed when an institutional resting
    ask wall sits directly overhead within 0.3% of LTP (e.g. LTP 155.0, Wall at 155.25).
    """
    leader_alert = AutoAlert(
        alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:RVNL",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ RVNL Ignition",
        summary="RVNL opens strong",
        ltp=450.0,
        trigger_level=450.0,
        target_level=475.0,
        stop_loss=440.0,
        confidence=90,
        is_live=True,
    )
    sympathy_engine.record_leader_alert(leader_alert)

    mock_quotes = {
        "NSE:IRFC": MagicMock(
            symbol="NSE:IRFC",
            ltp=155.0,
            open=150.0,
            close=150.0,
            low=150.0,
            high=155.5,
            volume=20000000,
        )
    }

    mock_depth = {
        "status": "LIVE",
        "symbol": "NSE:IRFC-EQ",
        "obi_50": 0.10,
        "bid_walls": [],
        "ask_walls": [
            {"price": 155.25, "qty": 150000, "strength": "FORTRESS"},  # 0.16% above LTP
        ],
    }

    mock_tbt_mgr = MagicMock()
    mock_tbt_mgr.is_connected = True
    mock_tbt_mgr.get_50_depth.return_value = mock_depth

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_tbt_mgr)
    monkeypatch.setattr("market.fyers_tbt_manager.promote_jit_tbt_scout", lambda *a, **k: True)

    with patch("market.quotes.get_computed_vwap", return_value=152.0):
        alerts = sympathy_engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

    # Must be vetoed by overhead ask wall filter
    assert len(alerts) == 0


def test_thematic_sympathy_tbt_scout_veto_on_underlying_bid_wall_in_bearish_cascade(
    monkeypatch, sympathy_engine
):
    """
    Bearish peer candidate ITC is suppressed when an institutional resting
    bid wall sits directly underneath within 0.3% of LTP (e.g. LTP 400.0, Wall at 399.20).
    """
    leader_alert = AutoAlert(
        alert_id=generate_alert_id("DABUR", "SQUEEZE_BREAKOUT"),
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:DABUR",
        exchange="NSE",
        direction="BEARISH",
        headline="⚡ DABUR Breakdown",
        summary="DABUR breaks key support",
        ltp=520.0,
        trigger_level=520.0,
        target_level=500.0,
        stop_loss=530.0,
        confidence=88,
        is_live=True,
    )
    sympathy_engine.record_leader_alert(leader_alert)

    mock_quotes = {
        "NSE:ITC": MagicMock(
            symbol="NSE:ITC",
            ltp=400.0,
            open=405.0,
            close=405.0,
            low=399.5,
            high=405.0,
            volume=15000000,
        )
    }

    mock_depth = {
        "status": "LIVE",
        "symbol": "NSE:ITC-EQ",
        "obi_50": -0.05,
        "bid_walls": [
            {"price": 399.20, "qty": 200000, "strength": "FORTRESS"},  # 0.20% below LTP
        ],
        "ask_walls": [],
    }

    mock_tbt_mgr = MagicMock()
    mock_tbt_mgr.is_connected = True
    mock_tbt_mgr.get_50_depth.return_value = mock_depth

    monkeypatch.setattr("market.fyers_tbt_manager.FyersTbtManager", lambda: mock_tbt_mgr)
    monkeypatch.setattr("market.fyers_tbt_manager.promote_jit_tbt_scout", lambda *a, **k: True)

    with patch("market.quotes.get_computed_vwap", return_value=403.0):
        alerts = sympathy_engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

    # Must be vetoed by underlying bid wall filter
    assert len(alerts) == 0
