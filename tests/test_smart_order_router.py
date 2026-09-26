"""
tests/test_smart_order_router.py
────────────────────────────────
Unit tests for Smart Order Router (SOR) and Passive PEG / Iceberg execution.
"""

from __future__ import annotations

import pytest

from engine.smart_order_router import build_smart_execution_plan, resolve_tick_size


def test_resolve_tick_size():
    """Verify correct tick size for standard equity, F&O and commodities."""
    assert resolve_tick_size(24500.0, "NIFTY") == 0.05
    assert resolve_tick_size(1500.0, "INFY") == 0.05
    assert resolve_tick_size(6500.0, "CRUDEOIL") == 1.0


def test_direct_limit_small_order_tight_spread():
    """Single lot with tight spread (<= 1 tick) routes directly as DIRECT_LIMIT."""
    plan = build_smart_execution_plan(
        symbol="NIFTY",
        side="BUY",
        total_quantity=25,
        ltp=24500.0,
        bid_price=24500.0,
        ask_price=24500.05,
        lot_size=25,
    )

    assert plan.routing_mode == "DIRECT_LIMIT"
    assert plan.total_lots == 1
    assert plan.num_tranches == 1
    assert plan.tranches[0].quantity == 25


def test_passive_peg_moderate_spread():
    """Moderate spread order uses PASSIVE_PEG to capture half-spread."""
    plan = build_smart_execution_plan(
        symbol="BANKNIFTY",
        side="BUY",
        total_quantity=30,  # 2 lots
        ltp=52000.0,
        bid_price=51995.0,
        ask_price=52005.0,  # 10 pts spread
        lot_size=15,
        max_tranche_lots=3,
    )

    assert plan.routing_mode == "PASSIVE_PEG"
    assert plan.spread_pts == 10.0
    assert plan.peg_limit_price == 51995.05  # Best Bid + 1 tick
    assert plan.estimated_spread_savings_inr == 30 * 5.0  # 30 shares * 5 pts half-spread = 150 INR


def test_iceberg_slicer_institutional_lots():
    """Large orders (> max_tranche_lots) slice into discrete tranches."""
    plan = build_smart_execution_plan(
        symbol="RELIANCE",
        side="SELL",
        total_quantity=1500,  # 6 lots (lot size 250)
        ltp=3000.0,
        bid_price=2998.0,
        ask_price=3002.0,
        lot_size=250,
        max_tranche_lots=2,  # 2 lots per tranche -> 3 tranches
    )

    assert plan.routing_mode == "ICEBERG"
    assert plan.total_lots == 6
    assert plan.num_tranches == 3
    assert plan.tranche_size == 500  # 2 lots * 250
    assert len(plan.tranches) == 3
    assert plan.tranches[0].quantity == 500
    assert plan.tranches[1].quantity == 500
    assert plan.tranches[2].quantity == 500
    assert plan.tranches[1].delay_ms > plan.tranches[0].delay_ms
