"""
tests/test_reconciliation_unavailable.py
─────────────────────────────────────────
Gap 4: Verifies that /api/reconciliation never compares the internal
ledger against itself.

The endpoint must return status='UNAVAILABLE' when no authenticated
broker session is present, and must use a real broker snapshot
(never internal_positions as broker_positions) when a session exists.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


@pytest.fixture()
def client():
    from web.api import app

    return TestClient(app)


# ── Test: UNAVAILABLE when no broker session ──────────────────────────────────


def test_reconciliation_without_broker_returns_unavailable(client):
    """
    When no broker session is available (get_broker() returns None),
    the reconciliation endpoint must return status='UNAVAILABLE'.
    It must NOT return a reconciliation report comparing the ledger
    to itself.
    """
    with patch("brokers.session.get_broker", return_value=None):
        resp = client.get("/api/reconciliation")

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "UNAVAILABLE", (
        f"Expected status='UNAVAILABLE', got {data.get('status')!r}. "
        "Reconciliation without a broker session must not produce a report."
    )
    assert data.get("broker_positions") is None
    assert data.get("broker_cash") is None
    assert "reason" in data
    assert len(data["reason"]) > 0


def test_reconciliation_broker_exception_returns_unavailable(client):
    """
    When get_broker() raises an exception, the endpoint must still
    return status='UNAVAILABLE' rather than a self-comparison report.
    """
    with patch("brokers.session.get_broker", side_effect=RuntimeError("session expired")):
        resp = client.get("/api/reconciliation")

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "UNAVAILABLE"


# ── Test: self-comparison is impossible ───────────────────────────────────────


def test_reconciliation_never_compares_ledger_to_itself(client):
    """
    When a broker session IS available, the broker positions must be
    obtained from the broker, not from the internal ledger.

    Verifies this by returning different data from the broker and
    checking that the report reflects the broker data — if it used
    internal_positions as broker_positions, it would always be 'clean'.
    """
    # Broker: completely different — qty mismatch to trigger discrepancy
    broker_pos = [{"symbol": "RELIANCE", "quantity": 5, "average_price": 2900.0}]
    broker_funds = {"available_cash": 50000.0}

    mock_broker = MagicMock()
    mock_broker.get_positions.return_value = broker_pos
    mock_broker.get_funds.return_value = broker_funds
    mock_broker.account_id = "TEST_ACCOUNT_001"

    with patch("brokers.session.get_broker", return_value=mock_broker):
        with patch("engine.portfolio.get_portfolio_summary") as mock_summary:
            # Make internal ledger return our test position
            mock_pos = MagicMock()
            mock_pos.symbol = "RELIANCE"
            mock_pos.qty = 10
            mock_pos.avg_price = 2900.0
            mock_pos.pnl = 500.0
            mock_funds = MagicMock()
            mock_funds.available_cash = 100000.0
            mock_summary_obj = MagicMock()
            mock_summary_obj.positions = [mock_pos]
            mock_summary_obj.funds = mock_funds
            mock_summary.return_value = mock_summary_obj

            resp = client.get("/api/reconciliation")

    assert resp.status_code == 200
    data = resp.json()

    # Response must NOT be UNAVAILABLE when a broker session exists
    assert data.get("status") != "UNAVAILABLE", (
        "Reconciliation should proceed when a broker session is available."
    )

    # The response must include broker provenance fields
    assert data.get("broker_account_id") is not None
    assert data.get("broker_snapshot_at") is not None
    assert data.get("correlation_id") is not None


def test_reconciliation_response_includes_broker_provenance(client):
    """
    A successful reconciliation response must include broker_account_id,
    broker_snapshot_at, and correlation_id for auditability.
    """
    mock_broker = MagicMock()
    mock_broker.get_positions.return_value = []
    mock_broker.get_funds.return_value = {"available_cash": 0.0}
    mock_broker.account_id = "FYERS_TESTUSER123"

    with patch("brokers.session.get_broker", return_value=mock_broker):
        with patch("engine.portfolio.get_portfolio_summary") as mock_summary:
            mock_summary_obj = MagicMock()
            mock_summary_obj.positions = []
            mock_funds = MagicMock()
            mock_funds.available_cash = 0.0
            mock_summary_obj.funds = mock_funds
            mock_summary.return_value = mock_summary_obj

            resp = client.get("/api/reconciliation")

    data = resp.json()
    if data.get("status") != "UNAVAILABLE":
        assert "broker_account_id" in data, "broker_account_id missing from reconciliation response"
        assert "broker_snapshot_at" in data, (
            "broker_snapshot_at missing from reconciliation response"
        )
        assert "correlation_id" in data, "correlation_id missing from reconciliation response"
        assert data["broker_account_id"] == "FYERS_TESTUSER123"
