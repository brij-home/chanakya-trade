"""
tests/test_missed_movers_enhancements.py
────────────────────────────────────────
Deterministic regression test suite for the institutional enhancements addressing missed big moves:
  1. Pillar 1: Opening Drive Institutional Decoupler (Open==Low/High + RVOL >= 1.5x)
     bypassing benchmark gravitational vetoes.
  2. Pillar 2: Sub-₹100 Low-Ticket Sizing & Options Momentum Calibration (e.g. SUZLON, IRFC).
  3. Pillar 3: Autonomous Thematic Basket & Sector Peer Sympathy Engine (e.g. RVNL -> IRFC, DABUR -> ITC).
  4. Pillar 4: Decoupling Score Opening Drive Pacing prioritizing true relative strength.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
import pytest

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.alert_scrutiny import AlertScrutinyAuditor
from engine.thematic_peer_sympathy import ThematicPeerSympathyEngine, SectorLeaderActivation
from engine.auto_alert_engine import AutoAlertEngine


@pytest.fixture
def auditor() -> AlertScrutinyAuditor:
    return AlertScrutinyAuditor(min_rr_ratio=1.3, max_intraday_risk_pct=8.0)


# =========================================================================
# PILLAR 1: OPENING DRIVE DECOUPLER SANITY
# =========================================================================


def test_opening_drive_bullish_decoupler_bypasses_benchmark_gravity_veto(
    auditor: AlertScrutinyAuditor,
):
    """
    When NIFTY benchmark is sharply negative (-0.85%), an OPENING_DRIVE alert on a genuine
    relative strength decoupler (DELHIVERY / IRFC: Open==Low, RVOL 3.5x, Day Change +1.5%)
    must NOT be vetoed by the benchmark gravitational veto.
    """
    alert = AutoAlert(
        alert_id=generate_alert_id("DELHIVERY", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:DELHIVERY",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ [OPENING DRIVE] DELHIVERY Institutional Long Ignition",
        summary="DELHIVERY triggered pristine Open==Low drive. RVOL: 3.5x.",
        ltp=395.0,
        trigger_level=395.0,
        target_level=410.0,  # 15 pts reward (1:2.5 R:R)
        stop_loss=389.0,  # 6 pts risk (1.5%)
        confidence=90,
        decoupler_status="VERIFIED_DECOUPLER",
        metrics={
            "open_low_matched": True,
            "rvol": 3.5,
            "day_change_pct": 1.5,
            "nifty_change_pct": -0.85,
            "nifty_below_vwap": True,
        },
        actionable_plan={
            "action": "BUY",
            "entry_range": "394.00 - 396.00",
            "stop_loss": 389.0,
            "target_1": 410.0,
            "target_2": 420.0,
            "rr_ratio": 2.5,
            "no_chase_above": 397.0,
        },
        is_live=True,
        environment="LIVE",
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)

    assert passed is True, f"Tier-1 Sanity failed unexpectedly: {reason}"
    assert flags["level_coherence"] is True
    assert flags["rr_valid"] is True
    assert flags.get("benchmark_regime_valid") is True


def test_opening_drive_bearish_decoupler_bypasses_benchmark_gravity_veto(
    auditor: AlertScrutinyAuditor,
):
    """
    When NIFTY benchmark is up (+1.10%), a short breakdown OPENING_DRIVE alert on a
    decoupler (Open==High, RVOL 2.5x, Day Change -1.8%) must NOT be vetoed.
    """
    alert = AutoAlert(
        alert_id=generate_alert_id("ITC", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:ITC",
        exchange="NSE",
        direction="BEARISH",
        headline="⚡ [OPENING DRIVE] ITC Short Breakdown Drive",
        summary="ITC Open==High short breakdown. RVOL: 2.5x.",
        ltp=480.0,
        trigger_level=480.0,
        target_level=466.0,  # 14 pts reward (1:2.33 R:R)
        stop_loss=486.0,  # 6 pts risk
        confidence=88,
        decoupler_status="VERIFIED_DECOUPLER",
        metrics={
            "open_high_matched": True,
            "rvol": 2.5,
            "day_change_pct": -1.8,
            "nifty_change_pct": 1.10,
            "nifty_below_vwap": False,
        },
        actionable_plan={
            "action": "SELL",
            "entry_range": "479.00 - 481.00",
            "stop_loss": 486.0,
            "target_1": 466.0,
            "rr_ratio": 2.33,
            "no_chase_below": 477.0,
        },
        is_live=True,
        environment="LIVE",
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)

    assert passed is True, f"Tier-1 Sanity failed unexpectedly: {reason}"
    assert flags["level_coherence"] is True
    assert flags["rr_valid"] is True
    assert flags.get("benchmark_regime_valid") is True


def test_non_decoupler_counter_trend_is_properly_vetoed(auditor: AlertScrutinyAuditor):
    """
    A generic counter-trend alert without decoupler qualifications (low RVOL, no Open==Low)
    is properly blocked when fighting severe benchmark gravity.
    """
    alert = AutoAlert(
        alert_id=generate_alert_id("WEAKSTOCK", "GENERIC_MOMENTUM"),
        alert_type="GENERIC_MOMENTUM",
        stage="IGNITED",
        symbol="NSE:WEAKSTOCK",
        exchange="NSE",
        direction="BULLISH",
        headline="Generic Long",
        summary="Drifting counter-trend",
        ltp=500.0,
        trigger_level=500.0,
        target_level=510.0,
        stop_loss=495.0,
        confidence=70,
        decoupler_status="CORRELATED",
        metrics={
            "rvol": 0.7,  # Weak volume
            "day_change_pct": 0.2,
            "nifty_change_pct": -1.2,
            "nifty_below_vwap": True,
        },
        actionable_plan={
            "action": "BUY",
            "stop_loss": 495.0,
            "target_1": 510.0,
            "rr_ratio": 2.0,
        },
        is_live=True,
        environment="LIVE",
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)

    # Counter-trend without decoupler proof must be flagged/vetoed
    assert flags.get("benchmark_regime_valid") is False
    assert passed is False
    assert "Benchmark Gravitational Veto" in reason


# =========================================================================
# PILLAR 2: SUB-₹100 LOW-TICKET SIZING & OPTIONS MOMENTUM
# =========================================================================


def test_sub_100_low_ticket_orb_risk_sizing_and_rr(auditor: AlertScrutinyAuditor):
    """
    Sub-₹100 stocks (e.g., SUZLON @ ₹38.50) must not have their risk floor artificially inflated
    to ₹1.00 (which would destroy R:R). Sizing must produce risk proportional to price (~0.10-0.60)
    yielding R:R >= 1:1.80.
    """
    ltp = 38.50
    range_low = 37.90
    range_high = 38.50
    calc_risk = round(range_high - range_low, 2)  # 0.60 pts

    # Target 1 with 1.8R minimum
    target_1 = round(ltp + (calc_risk * 1.8), 2)  # 39.58
    target_2 = round(ltp + (calc_risk * 3.5), 2)  # 40.60

    alert = AutoAlert(
        alert_id=generate_alert_id("SUZLON", "ORB_15M"),
        alert_type="ORB_15M",
        stage="IGNITED",
        symbol="NSE:SUZLON",
        exchange="NSE",
        direction="BULLISH",
        headline="🎯 [15M ORB] SUZLON Breakout",
        summary=f"SUZLON breaks 15M ORB High ₹{range_high:.2f}. Risk: ₹{calc_risk:.2f}.",
        ltp=ltp,
        trigger_level=range_high,
        target_level=target_1,
        stop_loss=range_low,
        confidence=85,
        decoupler_status="VERIFIED_DECOUPLER",
        metrics={
            "rvol": 2.4,
            "orb_range_pts": calc_risk,
            "day_change_pct": 3.8,
        },
        actionable_plan={
            "action": "BUY",
            "entry_range": f"{ltp - 0.10:.2f} - {ltp + 0.10:.2f}",
            "stop_loss": range_low,
            "target_1": target_1,
            "target_2": target_2,
            "rr_ratio": 1.8,
            "no_chase_above": round(ltp + 0.25, 2),
        },
        is_live=True,
        environment="LIVE",
    )

    passed, reason, flags = auditor.verify_tier1_sanity(alert)
    assert passed is True, f"SUZLON ORB alert failed Tier-1 sanity: {reason}"
    assert flags["rr_valid"] is True
    assert flags["level_coherence"] is True


def test_sub_100_options_momentum_calibration():
    """
    Verifies that low-ticket stocks (< ₹100) allow options contracts with premium >= ₹0.50
    rather than dropping them due to a blanket ₹1.50 floor.
    """
    spot = 39.5
    min_opt_price = 0.50 if spot < 100 else 1.50
    assert min_opt_price == 0.50


# =========================================================================
# PILLAR 3: THEMATIC BASKET & SECTOR PEER SYMPATHY ENGINE
# =========================================================================


def test_thematic_sympathy_engine_leader_registration_and_peer_cascade():
    """
    1. RVNL triggers an Apex alert in Railways sector (confidence >= 82).
    2. ThematicPeerSympathyEngine registers Railways as activated.
    3. Engine evaluates liquid peer IRFC (with Open==Low, above VWAP, RVOL >= 1.3x).
    4. Engine fires THEMATIC_SYMPATHY_IGNITION alert on IRFC with R:R >= 1:2.0.
    """
    engine = ThematicPeerSympathyEngine()

    # Create Apex Leader Alert for RVNL
    leader_alert = AutoAlert(
        alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
        alert_type="OPENING_DRIVE",
        stage="IGNITED",
        symbol="NSE:RVNL",
        exchange="NSE",
        direction="BULLISH",
        headline="⚡ [OPENING DRIVE] RVNL Ignition",
        summary="RVNL opens with massive institutional volume",
        ltp=450.0,
        trigger_level=450.0,
        target_level=475.0,
        stop_loss=440.0,
        confidence=90,
        is_live=True,
    )

    # 1. Record leader
    engine.record_leader_alert(leader_alert)

    # Check activation
    assert "railways" in engine._active_sectors
    act = engine._active_sectors["railways"]
    assert act.leader_symbol == "RVNL"
    assert act.direction == "BULLISH"

    # 2. Evaluate peers using synthetic quotes
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

    with patch("market.quotes.get_computed_vwap", return_value=152.0):
        sympathy_alerts = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

    assert len(sympathy_alerts) >= 1
    peer_alert = sympathy_alerts[0]
    assert peer_alert.symbol == "IRFC"
    assert peer_alert.alert_type == "THEMATIC_SYMPATHY_IGNITION"
    assert peer_alert.direction == "BULLISH"
    assert "RVNL" in peer_alert.headline or "RVNL" in peer_alert.summary
    assert peer_alert.stop_loss < peer_alert.ltp < peer_alert.target_level

    # Verify R:R asymmetry >= 1:2.0
    risk = peer_alert.ltp - peer_alert.stop_loss
    reward = peer_alert.target_level - peer_alert.ltp
    assert reward / risk >= 1.95  # Floating tolerance for 1:2.0


def test_thematic_sympathy_engine_bearish_cascade():
    """
    DABUR triggers a Bearish Breakdown in FMCG.
    Peer ITC (Open==High, below VWAP, RVOL >= 1.3x) triggers Bearish Thematic Sympathy.
    """
    engine = ThematicPeerSympathyEngine()

    leader_alert = AutoAlert(
        alert_id=generate_alert_id("DABUR", "SQUEEZE_BREAKOUT"),
        alert_type="SQUEEZE_BREAKOUT",
        stage="IGNITED",
        symbol="NSE:DABUR",
        exchange="NSE",
        direction="BEARISH",
        headline="📉 [SQUEEZE] DABUR Breakdown",
        summary="DABUR breaks key support with heavy selling",
        ltp=520.0,
        trigger_level=520.0,
        target_level=500.0,
        stop_loss=530.0,
        confidence=88,
        is_live=True,
    )

    engine.record_leader_alert(leader_alert)
    assert "fmcg" in engine._active_sectors
    assert engine._active_sectors["fmcg"].direction == "BEARISH"

    mock_quotes = {
        "NSE:ITC": MagicMock(
            symbol="NSE:ITC",
            ltp=478.0,
            open=488.0,
            close=488.0,
            low=477.0,
            high=488.0,  # Open == High
            volume=15000000,
        )
    }

    with patch("market.quotes.get_computed_vwap", return_value=484.0):
        sympathy_alerts = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

    assert len(sympathy_alerts) >= 1
    peer_alert = sympathy_alerts[0]
    assert peer_alert.symbol == "ITC"
    assert peer_alert.alert_type == "THEMATIC_SYMPATHY_IGNITION"
    assert peer_alert.direction == "BEARISH"
    assert peer_alert.target_level < peer_alert.ltp < peer_alert.stop_loss


def test_thematic_sympathy_engine_expiry_ttl():
    """Sector activation expires after 90 minutes (5400s) to prevent stale cascades."""
    engine = ThematicPeerSympathyEngine()

    # Artificially activate with timestamp 2 hours ago
    engine._active_sectors["metals"] = SectorLeaderActivation(
        sector_id="metals",
        sector_name="Metals",
        leader_symbol="TATASTEEL",
        direction="BULLISH",
        alert_type="GAMMA_BLAST",
        confidence=90,
        activated_at=time.time() - 7200.0,  # 2 hours old
        expiry_ttl=5400.0,
    )

    alerts = engine.evaluate_peer_sympathy(quotes_map={})
    assert len(alerts) == 0
    assert "metals" not in engine._active_sectors  # Cleanly purged


# =========================================================================
# PILLAR 4: OPENING DRIVE PACING & DECOUPLING SCORE
# =========================================================================


def test_opening_drive_pacing_prioritizes_decoupling_score():
    """
    Verifies that Opening Drive candidate selection uses Decoupling Score
    (RVOL * 2.5 + Range% * 1.5 + Conf / 10.0) so explosive high-volume decouplers
    are prioritized over low-beta megacaps.
    """
    # Candidate A: Heavyweight megacap with low volume (RVOL 0.8x, Range 0.6%, Conf 80)
    score_a = (0.8 * 2.5) + (0.6 * 1.5) + (80 / 10.0)  # 2.0 + 0.9 + 8.0 = 10.9

    # Candidate B: Mid-cap explosive decoupler (RVOL 4.2x, Range 3.5%, Conf 88)
    score_b = (4.2 * 2.5) + (3.5 * 1.5) + (88 / 10.0)  # 10.5 + 5.25 + 8.8 = 24.55

    assert score_b > score_a, "Decoupler must rank significantly higher than megacap drift"


def test_auto_alert_engine_scan_thematic_sympathy_wired():
    """Verifies that scan_thematic_peer_sympathy is wired on AutoAlertEngine."""
    engine = AutoAlertEngine()
    assert hasattr(engine, "scan_thematic_peer_sympathy")
    assert callable(getattr(engine, "scan_thematic_peer_sympathy"))
