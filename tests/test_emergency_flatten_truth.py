"""
tests/test_emergency_flatten_truth.py
─────────────────────────────────────
Regression tests for EXEC-23 and BRK-04 (flatten truthfulness):
  - In EXECUTE mode, PaperBroker is NEVER instantiated or executed.
  - An unavailable broker returns status="UNVERIFIED", positions_verified=False.
  - Failed cancellations (cancel_order returning False) are not counted.
  - In SIMULATE mode, operations are explicitly marked as simulated.
"""

import pytest
from unittest.mock import MagicMock, patch
from engine.order_lifecycle import emergency_flatten_all_positions, clear_emergency_lockout


@pytest.fixture(autouse=True)
def clean_lockout():
    clear_emergency_lockout()
    yield
    clear_emergency_lockout()


def test_emergency_flatten_in_execute_mode_never_touches_paper(monkeypatch):
    """In EXECUTE mode, emergency flatten must never fall back to PaperBroker."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    # Mock broker that has NO square_off_intraday_positions
    mock_broker = MagicMock()
    mock_broker.get_orders.return_value = []
    mock_broker.get_positions.return_value = []
    del mock_broker.exit_all_positions
    del mock_broker.square_off_intraday_positions

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        with patch("engine.paper.PaperBroker") as mock_paper_cls:
            res = emergency_flatten_all_positions(actor="TEST", reason="TEST_FLATTEN")
            mock_paper_cls.assert_not_called()
            assert res.get("mode") == "EXECUTE"
            assert not any("PaperBroker" in str(p) for p in res.get("flattened_positions", []))


def test_emergency_flatten_unavailable_broker_returns_unverified(monkeypatch):
    """If execution broker is unreachable or raises on positions, status must be UNVERIFIED."""
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("LIVE_EXECUTION_QUALIFIED", "1")

    with patch("brokers.session.get_execution_broker", return_value=None):
        res = emergency_flatten_all_positions(actor="TEST", reason="TEST_FLATTEN")
        assert res.get("status") == "UNVERIFIED"
        assert res.get("positions_verified") is False
        assert res.get("flattened_positions_count") == 0


def test_failed_cancellations_not_counted(monkeypatch):
    """If cancel_order returns False, order must not be counted as cancelled."""
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    mock_broker = MagicMock()
    mock_order = MagicMock()
    mock_order.order_id = "ORD-123"
    mock_order.status = "OPEN"
    mock_broker.get_orders.return_value = [mock_order]
    mock_broker.cancel_order.return_value = False  # Cancellation rejected by broker
    mock_broker.get_positions.return_value = []

    with patch("brokers.session.get_execution_broker", return_value=mock_broker):
        with patch("engine.paper.PaperBroker", return_value=mock_broker):
            res = emergency_flatten_all_positions(actor="TEST", reason="TEST_FLATTEN")
            assert "ORD-123" not in res.get("cancelled_orders", [])
            assert res.get("cancelled_orders_count") == 0
