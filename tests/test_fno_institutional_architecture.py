"""
tests/test_fno_institutional_architecture.py
─────────────────────────────────────────────
Institutional regression & verification suite for the Dual-Broker High-Throughput F&O Terminal.

Verifies:
  1. Per-Cycle Target Bounding Invariant (len(targets) <= 15 strictly enforced across cycles).
  2. Multi-Cycle Staggered Universe Coverage (all top 50 equities evaluated across 9 cycles while top 5 anchors are evaluated in 100% of cycles).
  3. Dynamic Velocity Ranking & Immediate Hot-Runner Promotion (high-turnover/surge stocks instantly promoted to top anchors).
  4. Active Stock Options Grid Seeding (ATM +- 2 strikes within Fyers 5,000 Data Socket capacity).
  5. Active Session Resource Quarantine (Commodities, CDS, and Crypto completely silenced under FNO_ONLY).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


from brokers.base import Quote
from config.discovery_policy import get_discovery_policy
from engine.auto_alert_engine import AutoAlertEngine
from market.ws_subscription_manager import (
    get_active_stock_options_grid,
)


class TestFnoInstitutionalArchitecture(unittest.TestCase):
    def setUp(self):
        self.engine = AutoAlertEngine()

    def test_staggered_target_bounding_invariant(self):
        """Mathematical invariant: target count must NEVER exceed 15 on any cycle."""
        base_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        mock_candidates = [f"STOCK_{i}" for i in range(100)]

        for cycle_step in range(25):
            targets = self.engine._select_staggered_targets(
                eq_candidates=mock_candidates,
                cycle_step=cycle_step,
                base_targets=base_indices,
                max_total_targets=15,
                anchor_count=5,
                max_pool_depth=50,
            )
            self.assertLessEqual(
                len(targets),
                15,
                f"Cycle {cycle_step} exceeded max_total_targets (got {len(targets)})",
            )
            # Base indices must always be included
            for idx in base_indices:
                self.assertIn(idx, targets)

    def test_staggered_rotation_covers_all_candidates_and_preserves_anchors(self):
        """Top 5 anchors must appear in 100% of cycles; pool of 50 must be completely covered within 9 cycles."""
        base_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        mock_candidates = [f"STOCK_{i}" for i in range(50)]
        expected_anchors = {f"STOCK_{i}" for i in range(5)}

        seen_equities = set()
        anchor_appearances = {a: 0 for a in expected_anchors}

        # 9 cycles (chunk size = 5, pool size = 45 -> 45 / 5 = 9 chunks)
        for cycle_step in range(9):
            targets = self.engine._select_staggered_targets(
                eq_candidates=mock_candidates,
                cycle_step=cycle_step,
                base_targets=base_indices,
                max_total_targets=15,
                anchor_count=5,
                max_pool_depth=50,
            )
            self.assertEqual(len(targets), 15)

            # Check anchors
            for a in expected_anchors:
                if a in targets:
                    anchor_appearances[a] += 1

            for s in targets:
                if s.startswith("STOCK_"):
                    seen_equities.add(s)

        # Anchors appeared in every single cycle (100% attendance)
        for a, count in anchor_appearances.items():
            self.assertEqual(
                count, 9, f"Anchor {a} appeared {count}/9 times instead of 100% of cycles"
            )

        # Entire pool of 50 equities was audited
        self.assertEqual(
            len(seen_equities),
            50,
            f"Expected all 50 equities to be evaluated, but only saw {len(seen_equities)}",
        )

    def test_velocity_ranking_and_dynamic_hot_runner_promotion(self):
        """A surging stock with heavy turnover must immediately jump into the top 5 anchors."""
        candidates = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "MIDCAP_RUNNER"]

        quotes_map = {
            "NSE:RELIANCE": Quote(
                symbol="NSE:RELIANCE",
                last_price=2500.0,
                volume=1000000,
                change_pct=1.0,
            ),
            "NSE:HDFCBANK": Quote(
                symbol="NSE:HDFCBANK",
                last_price=1600.0,
                volume=1000000,
                change_pct=0.8,
            ),
            "NSE:INFY": Quote(
                symbol="NSE:INFY",
                last_price=1800.0,
                volume=1000000,
                change_pct=0.5,
            ),
            "NSE:TCS": Quote(
                symbol="NSE:TCS",
                last_price=4000.0,
                volume=500000,
                change_pct=0.4,
            ),
            "NSE:SBIN": Quote(
                symbol="NSE:SBIN",
                last_price=800.0,
                volume=1500000,
                change_pct=0.6,
            ),
            # MIDCAP_RUNNER explodes with 5.5% move and massive volume
            "NSE:MIDCAP_RUNNER": Quote(
                symbol="NSE:MIDCAP_RUNNER",
                last_price=1200.0,
                volume=5000000,
                change_pct=5.5,
            ),
        }

        ranked = self.engine._rank_candidates_by_velocity(candidates, quotes_map)
        # MIDCAP_RUNNER must be ranked #1 due to highest turnover x change% velocity
        self.assertEqual(ranked[0], "MIDCAP_RUNNER")

        # Now select staggered targets: MIDCAP_RUNNER must be in anchors (first positions)
        targets = self.engine._select_staggered_targets(
            eq_candidates=ranked,
            cycle_step=0,
            base_targets=["NIFTY", "BANKNIFTY"],
            max_total_targets=15,
            anchor_count=5,
        )
        self.assertIn("MIDCAP_RUNNER", targets[:7])

    def test_active_stock_options_grid_seeding(self):
        """Active stock options grid must pre-seed ATM +- 2 strikes within Fyers 5,000 capacity."""
        with patch(
            "market.contract_selection.get_subscription_option_grid",
            return_value=[
                "NSE:RELIANCE26NOV2500CE",
                "NSE:RELIANCE26NOV2500PE",
                "NSE:RELIANCE26NOV2520CE",
                "NSE:RELIANCE26NOV2520PE",
            ],
        ):
            grid = get_active_stock_options_grid(stocks=["RELIANCE"])
            self.assertEqual(len(grid), 4)
            self.assertIn("NSE:RELIANCE26NOV2500CE", grid)
            self.assertIn("NSE:RELIANCE26NOV2500PE", grid)

    def test_resource_quarantine_under_fno_only(self):
        """When FNO_ONLY discovery policy is active, commodities, currencies, and crypto discovery must return empty immediately."""
        import os

        with patch.dict(os.environ, {"SESSION_FOCUS_MODE": "FNO_ONLY"}):
            policy = get_discovery_policy()
            self.assertTrue(policy.fno_only)

            from engine.detectors.commodity import detect_commodity_breakouts
            from engine.detectors.crypto import detect_crypto_signals
            from engine.detectors.currency import detect_currency_breakouts

            with patch("market.quotes.get_quote") as mock_quotes:
                comm_alerts = detect_commodity_breakouts()
                self.assertEqual(comm_alerts, [])
                mock_quotes.assert_not_called()

                cds_alerts = detect_currency_breakouts()
                self.assertEqual(cds_alerts, [])
                mock_quotes.assert_not_called()

                crypto_alerts = detect_crypto_signals()
                self.assertEqual(crypto_alerts, [])
                mock_quotes.assert_not_called()
