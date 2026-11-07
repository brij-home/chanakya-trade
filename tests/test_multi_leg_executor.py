"""
tests/test_multi_leg_executor.py
────────────────────────────────
Unit tests for engine/multi_leg_executor.py (Multi-Leg Spread Execution & Legging Risk Shield).
"""

import pytest
from unittest.mock import MagicMock

from engine.defined_risk_spreads import DefinedRiskSpread, SpreadLeg
from engine.multi_leg_executor import (
    execute_defined_risk_spread,
    SpreadExecutionResult,
)
from engine.order_lifecycle import OrderIntent


@pytest.fixture
def sample_bull_call_spread():
    leg1 = SpreadLeg(
        symbol="NIFTY24OCT24500CE",
        option_type="CE",
        strike=24500.0,
        side="BUY",
        premium=150.0,
        lot_size=25,
        quantity=25,
    )
    leg2 = SpreadLeg(
        symbol="NIFTY24OCT24700CE",
        option_type="CE",
        strike=24700.0,
        side="SELL",
        premium=60.0,
        lot_size=25,
        quantity=25,
    )
    return DefinedRiskSpread(
        strategy_name="BULL_CALL_SPREAD",
        underlying="NIFTY",
        spot_price=24520.0,
        lot_size=25,
        legs=[leg1, leg2],
        net_debit_or_credit=2250.0,
        max_profit=2750.0,
        max_loss=2250.0,
        risk_reward_ratio=1.22,
        breakeven_points=[24590.0],
        capital_required=2250.0,
        sentiment="BULLISH",
        thesis="Bull Call Spread test",
    )


def test_multi_leg_happy_path(sample_bull_call_spread, monkeypatch):
    # Mock order creation and execution
    def mock_exec(order_id: str) -> OrderIntent:
        return OrderIntent(
            order_id=order_id,
            idempotency_key=f"idemp-{order_id}",
            symbol="TEST_OPT",
            side="BUY",
            quantity=25,
            price=100.0,
            status="FILLED",
            broker_order_id=f"BRK-{order_id}",
        )

    monkeypatch.setattr(
        "engine.multi_leg_executor.preview_order_intent",
        lambda **kw: MagicMock(order_id=f"ord-{kw['side']}", preview_hash="hash"),
    )
    monkeypatch.setattr("engine.multi_leg_executor.confirm_order_intent", lambda o, h: None)

    res: SpreadExecutionResult = execute_defined_risk_spread(
        spread=sample_bull_call_spread,
        executor_fn=mock_exec,
    )

    assert res.status == "FILLED"
    assert len(res.legs) == 2
    assert res.legs[0].side == "BUY"
    assert res.legs[0].status == "FILLED"
    assert res.legs[1].side == "SELL"
    assert res.legs[1].status == "FILLED"
    assert not res.unwind_performed
    assert len(res.audit_events) >= 3


def test_multi_leg_short_leg_failure_triggers_auto_unwind(sample_bull_call_spread, monkeypatch):
    # Mock executor where BUY succeeds but SELL fails
    def mock_exec(order_id: str) -> OrderIntent:
        if "BUY" in order_id:
            return OrderIntent(
                order_id=order_id,
                idempotency_key=f"idemp-{order_id}",
                symbol="NIFTY24OCT24500CE",
                side="BUY",
                quantity=25,
                price=150.0,
                status="FILLED",
                broker_order_id="BRK-BUY-1",
            )
        else:
            raise RuntimeError("Broker RMS Rejection: Margin Shortfall on Short Strike")

    unwind_mock = MagicMock(return_value=True)

    monkeypatch.setattr(
        "engine.multi_leg_executor.preview_order_intent",
        lambda **kw: MagicMock(order_id=f"ord-{kw['side']}", preview_hash="hash"),
    )
    monkeypatch.setattr("engine.multi_leg_executor.confirm_order_intent", lambda o, h: None)

    res = execute_defined_risk_spread(
        spread=sample_bull_call_spread,
        executor_fn=mock_exec,
        unwind_fn=unwind_mock,
    )

    assert res.status == "LEGGING_FAILED_UNWOUND"
    assert res.unwind_performed is True
    assert "Margin Shortfall on Short Strike" in res.rejection_reason
    unwind_mock.assert_called_once_with("NIFTY24OCT24500CE", 25, "SELL")


def test_multi_leg_unwind_failure_transitions_to_unknown_freeze(
    sample_bull_call_spread, monkeypatch
):
    """When short leg fails and emergency unwind fails, status must be UNKNOWN_FREEZE."""

    def mock_exec(order_id: str) -> OrderIntent:
        if "BUY" in order_id:
            return OrderIntent(
                order_id=order_id,
                idempotency_key=f"idemp-{order_id}",
                symbol="NIFTY24OCT24500CE",
                side="BUY",
                quantity=25,
                price=150.0,
                status="FILLED",
                broker_order_id="BRK-BUY-1",
            )
        else:
            raise RuntimeError("Broker reject on SELL")

    # Unwind fails (e.g. market order timed out or broker rejected exit)
    unwind_mock = MagicMock(return_value=False)

    monkeypatch.setattr(
        "engine.multi_leg_executor.preview_order_intent",
        lambda **kw: MagicMock(order_id=f"ord-{kw['side']}", preview_hash="hash"),
    )
    monkeypatch.setattr("engine.multi_leg_executor.confirm_order_intent", lambda o, h: None)

    res = execute_defined_risk_spread(
        spread=sample_bull_call_spread,
        executor_fn=mock_exec,
        unwind_fn=unwind_mock,
    )

    assert res.status == "UNKNOWN_FREEZE"
    assert res.unwind_performed is False
    assert "auto-unwind failed" in res.rejection_reason


def test_multi_leg_open_hedge_blocks_short_legs(sample_bull_call_spread, monkeypatch):
    """If hedge leg returns OPEN (not FILLED), short leg submission is blocked."""

    def mock_exec(order_id: str) -> OrderIntent:
        return OrderIntent(
            order_id=order_id,
            idempotency_key=f"idemp-{order_id}",
            symbol="NIFTY24OCT24500CE",
            side="BUY",
            quantity=25,
            price=150.0,
            status="OPEN",  # Still resting on orderbook!
            broker_order_id="BRK-BUY-RESTING",
        )

    monkeypatch.setattr(
        "engine.multi_leg_executor.preview_order_intent",
        lambda **kw: MagicMock(order_id=f"ord-{kw['side']}", preview_hash="hash"),
    )
    monkeypatch.setattr("engine.multi_leg_executor.confirm_order_intent", lambda o, h: None)

    res = execute_defined_risk_spread(
        spread=sample_bull_call_spread,
        executor_fn=mock_exec,
    )

    assert res.status == "REJECTED"
    assert "must be FILLED before proceeding" in res.rejection_reason


def test_default_unwind_uses_positive_price_not_zero(monkeypatch):
    """The default _unwind_filled_hedges must pass price > 0 to preview_order_intent."""
    from engine.multi_leg_executor import _unwind_filled_hedges, ChildLegExecution

    leg = ChildLegExecution(
        leg_index=0,
        symbol="NIFTY24OCT24500CE",
        option_type="CE",
        strike=24500.0,
        side="BUY",
        quantity=25,
        limit_price=150.0,
        status="FILLED",
        order_id="ORD-UNWIND-TEST-1",
        fill_price=152.0,
    )

    captured_prices = []

    def mock_preview(**kw):
        captured_prices.append(kw["price"])
        return MagicMock(order_id="unwind-ord-1", preview_hash="hash")

    monkeypatch.setattr("engine.multi_leg_executor.preview_order_intent", mock_preview)
    monkeypatch.setattr("engine.multi_leg_executor.confirm_order_intent", lambda o, h: None)
    monkeypatch.setattr(
        "engine.multi_leg_executor.execute_order_intent",
        lambda o: MagicMock(status="FILLED"),
    )

    ok = _unwind_filled_hedges([leg])
    assert ok is True
    assert len(captured_prices) == 1
    assert captured_prices[0] > 0.0
    assert captured_prices[0] == 152.0
