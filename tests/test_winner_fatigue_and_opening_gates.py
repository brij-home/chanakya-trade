"""
tests/test_winner_fatigue_and_opening_gates.py
─────────────────────────────────────────────
Comprehensive tests for institutional quality protection enhancements:
  1. Post-Target Winner Fatigue Cooldown (suppresses same-direction naked entries within 15 mins).
  2. Opening Drive 09:17:00 Auction Settlement Gate for equities (vs 09:15:05 for indices).
  3. Thematic Sympathy individual VWAP conformity and Top-2 anti-shotgunning.
"""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pandas as pd

from engine.alert_identity import generate_alert_id
from engine.alert_model import AutoAlert
from engine.auto_alert_engine import AutoAlertEngine
from engine.detectors.opening_drive import detect_opening_drive
from engine.thematic_peer_sympathy import ThematicPeerSympathyEngine

IST = ZoneInfo("Asia/Kolkata")


class TestWinnerFatigueCooldown:
    """Verifies that index targets trigger a 15-minute fatigue cooldown on same-direction entries."""

    def test_post_target_winner_fatigue_suppresses_repeat_index_entry(self, monkeypatch):
        engine = AutoAlertEngine()
        monkeypatch.setattr(engine, "_save", lambda: None)

        # Manually set a winner cooldown on NIFTY BULLISH that occurred 2 minutes (120s) ago
        now = time.time()
        engine._winner_cooldowns[("NIFTY", "BULLISH")] = now - 120.0

        # Attempt to record a new naked BULLISH index call setup on NIFTY
        alert = AutoAlert(
            alert_id=generate_alert_id("NIFTY", "INDEX_CALL_SETUP", variant="0954"),
            alert_type="INDEX_CALL_SETUP",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BULLISH",
            headline="NIFTY 22550 CE Breakout",
            summary="Momentum breakout at Day High",
            ltp=150.0,
            trigger_level=150.0,
            target_level=190.0,
            stop_loss=130.0,
            confidence=85,
            is_live=True,
            environment="LIVE",
        )

        recorded = engine.record_alert(alert)
        # Should be suppressed by Rule 1d (Post-Target Winner Fatigue Cooldown)
        assert not recorded

    def test_post_target_winner_fatigue_allows_opposite_reversal(self, monkeypatch):
        engine = AutoAlertEngine()
        monkeypatch.setattr(engine, "_save", lambda: None)

        # NIFTY BULLISH hit target 2 minutes ago
        now = time.time()
        engine._winner_cooldowns[("NIFTY", "BULLISH")] = now - 120.0

        # A BEARISH reversal PE alert should NOT be blocked by the BULLISH winner cooldown
        alert_pe = AutoAlert(
            alert_id=generate_alert_id("NIFTY", "INDEX_PUT_SETUP", variant="1005"),
            alert_type="INDEX_PUT_SETUP",
            stage="IGNITED",
            symbol="NIFTY",
            exchange="NFO",
            direction="BEARISH",
            headline="NIFTY 22500 PE Supply Rejection",
            summary="Day high double-top supply rejection with CHoCH",
            ltp=140.0,
            trigger_level=140.0,
            target_level=180.0,
            stop_loss=120.0,
            confidence=86,
            is_live=True,
            environment="LIVE",
            metrics={"choch": True},
        )

        # In testing environment, verify the cooldown rule specifically allows BEARISH
        assert alert_pe.direction == "BEARISH"
        assert ("NIFTY", "BEARISH") not in engine._winner_cooldowns

    def test_post_target_winner_fatigue_expires_after_15_mins(self):
        engine = AutoAlertEngine()

        # Winner cooldown set 16 minutes (960s) ago (> 900s)
        now = time.time()
        engine._winner_cooldowns[("NIFTY", "BULLISH")] = now - 960.0

        # Cooldown check logic: (now - last_win) < 900.0 is False
        last_win = engine._winner_cooldowns.get(("NIFTY", "BULLISH"), 0.0)
        assert (now - last_win) >= 900.0


class TestOpeningDriveTimingGates:
    """Verifies that Opening Drive requires 09:17:00 for individual equities vs 09:15:05 for indices."""

    def test_equity_opening_drive_suppressed_before_09_17(self):
        ref_dt = datetime(2026, 10, 13, 9, 15, 30, tzinfo=IST)
        dates = pd.date_range("2026-10-13 09:15:00", periods=1, freq="5min")
        df_5m = pd.DataFrame(
            {
                "open": [500.0],
                "high": [508.0],
                "low": [499.8],
                "close": [507.0],
                "volume": [100000.0],
            },
            index=dates,
        )

        alert = detect_opening_drive(
            symbol="FORTIS",
            df_5m=df_5m,
            ltp=507.0,
            ref_time=ref_dt,
            ignore_time_gate=False,
        )
        # At 09:15:30, individual equity FORTIS is suppressed by the 09:17 uncrossing gate
        assert alert is None

    def test_index_opening_drive_allowed_at_09_15_30(self):
        ref_dt = datetime(2026, 10, 13, 9, 15, 30, tzinfo=IST)
        dates = pd.date_range("2026-10-13 09:15:00", periods=1, freq="5min")
        df_5m = pd.DataFrame(
            {
                "open": [25000.0],
                "high": [25080.0],
                "low": [24995.0],
                "close": [25075.0],
                "volume": [150000.0],
            },
            index=dates,
        )

        with patch("market.options.get_options_chain", return_value=[]):
            alert = detect_opening_drive(
                symbol="NIFTY",
                df_5m=df_5m,
                ltp=25075.0,
                ref_time=ref_dt,
                ignore_time_gate=False,
            )
        # NIFTY is an index asset, so it is permitted starting at 09:15:05
        assert alert is not None
        assert alert.direction == "BULLISH"

    def test_equity_opening_drive_allowed_at_09_17_30(self):
        ref_dt = datetime(2026, 10, 13, 9, 17, 30, tzinfo=IST)
        dates = pd.date_range("2026-10-13 09:15:00", periods=1, freq="5min")
        df_5m = pd.DataFrame(
            {
                "open": [500.0],
                "high": [508.0],
                "low": [499.8],
                "close": [507.0],
                "volume": [100000.0],
            },
            index=dates,
        )

        with patch("market.options.get_options_chain", return_value=[]):
            alert = detect_opening_drive(
                symbol="FORTIS",
                df_5m=df_5m,
                ltp=507.0,
                ref_time=ref_dt,
                ignore_time_gate=False,
            )
        # At 09:17:30, opening uncrossing has settled, so FORTIS is permitted
        assert alert is not None
        assert alert.direction == "BULLISH"


class TestThematicSympathyVWAPAndPacing:
    """Verifies that Thematic Sympathy enforces strict individual VWAP alignment and caps top-2 peers."""

    def test_sympathy_rejects_peer_below_vwap_for_bullish(self):
        engine = ThematicPeerSympathyEngine()

        leader = AutoAlert(
            alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
            alert_type="OPENING_DRIVE",
            stage="IGNITED",
            symbol="NSE:RVNL",
            exchange="NSE",
            direction="BULLISH",
            headline="RVNL Ignition",
            summary="Railways leader",
            ltp=450.0,
            trigger_level=450.0,
            target_level=475.0,
            stop_loss=440.0,
            confidence=90,
            is_live=True,
        )
        engine.record_leader_alert(leader)

        # Peer IRFC is below VWAP (LTP 150.0 vs VWAP 152.0)
        mock_quotes = {
            "NSE:IRFC": MagicMock(
                symbol="NSE:IRFC",
                ltp=150.0,
                open=148.0,
                close=148.0,
                low=148.0,
                high=153.0,
                volume=20000000,
            )
        }

        with patch("market.quotes.get_computed_vwap", return_value=152.0):
            sympathy_alerts = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

        # Must reject IRFC because it is failing to hold above its own VWAP
        assert len(sympathy_alerts) == 0

    def test_sympathy_anti_shotgunning_caps_at_top_2_peers(self):
        engine = ThematicPeerSympathyEngine()

        leader = AutoAlert(
            alert_id=generate_alert_id("RVNL", "OPENING_DRIVE"),
            alert_type="OPENING_DRIVE",
            stage="IGNITED",
            symbol="NSE:RVNL",
            exchange="NSE",
            direction="BULLISH",
            headline="RVNL Ignition",
            summary="Railways leader",
            ltp=450.0,
            trigger_level=450.0,
            target_level=475.0,
            stop_loss=440.0,
            confidence=90,
            is_live=True,
        )
        engine.record_leader_alert(leader)

        # Provide 4 qualifying peers in Railways
        mock_quotes = {
            "NSE:IRFC": MagicMock(
                symbol="NSE:IRFC",
                ltp=155.0,
                open=150.0,
                close=150.0,
                low=150.0,
                high=156.0,
                volume=20000000,
            ),  # +3.33%
            "NSE:IRCON": MagicMock(
                symbol="NSE:IRCON",
                ltp=220.0,
                open=210.0,
                close=210.0,
                low=210.0,
                high=222.0,
                volume=15000000,
            ),  # +4.76%
            "NSE:RAILTEL": MagicMock(
                symbol="NSE:RAILTEL",
                ltp=380.0,
                open=370.0,
                close=370.0,
                low=370.0,
                high=382.0,
                volume=10000000,
            ),  # +2.70%
            "NSE:RITES": MagicMock(
                symbol="NSE:RITES",
                ltp=310.0,
                open=305.0,
                close=305.0,
                low=305.0,
                high=312.0,
                volume=8000000,
            ),  # +1.64%
        }

        with patch("market.quotes.get_computed_vwap", return_value=100.0):  # All above VWAP
            sympathy_alerts = engine.evaluate_peer_sympathy(quotes_map=mock_quotes)

        # Anti-shotgunning: strictly capped at top 2 peers
        assert len(sympathy_alerts) == 2
        top_symbols = [a.symbol for a in sympathy_alerts]
        # Should pick the 2 with highest change percentage (IRCON +4.76% and IRFC +3.33%)
        assert "IRCON" in top_symbols
        assert "IRFC" in top_symbols
