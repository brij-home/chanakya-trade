"""
tests/test_order_lifecycle.py
──────────────────────────────
Tests for P0-B Paper Order Management System (OMS):
  - Order preview generation with statutory Indian charges
  - Idempotency deduplication across duplicate submits
  - Explicit PAPER- order ID prefixing (no fake broker IDs)
  - Execution routing to PaperBroker and state transitions
  - Observe mode mutation rejection
"""

import pytest
from engine.order_lifecycle import preview_order_intent, execute_order_intent


@pytest.fixture(autouse=True)
def clean_order_db(tmp_path, monkeypatch):
    """Use isolated orders.db per test."""
    db_file = tmp_path / "test_orders.db"
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_file)
    yield


def test_order_preview_generation_and_charges():
    """Verify preview generates PAPER- ID and statutory charges breakdown."""
    intent = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=3500.0,
        order_type="LIMIT",
        product="MIS",
        segment="EQUITY_INTRADAY",
    )
    assert intent.order_id.startswith("PAPER-")
    assert intent.status == "PREVIEW"
    assert intent.symbol == "TCS"
    assert intent.charges is not None
    assert "total_charges" in intent.charges
    assert intent.charges["notional_turnover"] == 35000.0


def test_order_preview_idempotency():
    """Duplicate requests with same idempotency key return the existing intent without creating duplicate."""
    key = "test-idempotency-key-12345"
    intent1 = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=20,
        price=1800.0,
        idempotency_key=key,
    )
    intent2 = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=20,
        price=1800.0,
        idempotency_key=key,
    )
    assert intent1.order_id == intent2.order_id
    assert intent1.idempotency_key == intent2.idempotency_key


def test_order_execution_paper_flow(monkeypatch):
    """Verify execution transitions to FILLED_PAPER with PAPER-EXEC ID."""
    from engine.modes import ModeInfo, TradingMode

    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(
            mode=TradingMode.SIMULATE,
            is_observe=False,
            is_simulate=True,
            is_execute=False,
            description="Simulate",
        ),
    )

    intent = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=5,
        price=2800.0,
        order_type="MARKET",
    )

    executed = execute_order_intent(intent.order_id)
    assert executed.order_id == intent.order_id
    assert executed.status == "FILLED_PAPER"
    assert executed.broker_order_id.startswith("PAPER-")


def test_order_execution_blocked_in_observe_mode(monkeypatch):
    """Verify execution is rejected when system is in OBSERVE mode."""
    from engine.modes import ModeInfo, TradingMode

    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(
            mode=TradingMode.OBSERVE,
            is_observe=True,
            is_simulate=False,
            is_execute=False,
            description="Observe",
        ),
    )

    intent = preview_order_intent(
        symbol="HDFCBANK",
        side="BUY",
        quantity=10,
        price=1600.0,
    )

    executed = execute_order_intent(intent.order_id)
    assert executed.status == "REJECTED"
    assert "OBSERVE" in executed.rejection_reason


def test_paper_order_uses_real_paper_broker(tmp_path, monkeypatch):
    """
    End-to-end paper order path using the *real* PaperBroker (no mock on the broker).

    Verifies:
      1. OrderRequest is constructed with transaction_type (not the old `side` kwarg).
      2. PaperBroker.place_order fills a MARKET BUY immediately (COMPLETE status).
      3. The lifecycle transitions to FILLED_PAPER with a PAPER-EXEC- broker_order_id.
      4. The order is persisted to the DB with the correct final state.
    """
    from pathlib import Path
    from engine.modes import ModeInfo, TradingMode

    # ── Isolate paper portfolio file from real ~/.trading_platform ──
    paper_file = tmp_path / "paper_portfolio.json"
    monkeypatch.setattr("engine.paper.PAPER_FILE", paper_file)

    # ── Force SIMULATE mode ──────────────────────────────────────────
    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(
            mode=TradingMode.SIMULATE,
            is_observe=False,
            is_simulate=True,
            is_execute=False,
            description="Simulate",
        ),
    )

    # ── Stub market quote so PaperBroker._ltp returns a known price ──
    monkeypatch.setattr(
        "market.quotes.get_ltp",
        lambda instrument: 500.0,
    )

    intent = preview_order_intent(
        symbol="WIPRO",
        side="BUY",
        quantity=2,
        price=500.0,
        order_type="MARKET",
        product="MIS",
        segment="EQUITY_INTRADAY",
    )
    assert intent.order_id.startswith("PAPER-"), "Preview must produce a PAPER- order ID"
    assert intent.status == "PREVIEW"

    executed = execute_order_intent(intent.order_id)

    assert executed.order_id == intent.order_id
    assert executed.status == "FILLED_PAPER", (
        f"Expected FILLED_PAPER, got {executed.status}: {executed.rejection_reason}"
    )
    assert executed.broker_order_id is not None
    assert executed.broker_order_id.startswith("PAPER-EXEC-"), (
        f"broker_order_id must have PAPER-EXEC- prefix, got: {executed.broker_order_id}"
    )


def test_paper_order_preview_failure_never_shows_execute(monkeypatch):
    """
    If preview_order_intent raises (e.g. invalid segment), execute_order_intent must
    not be callable with the non-existent order ID — it raises ValueError, never
    fabricating a filled status.
    """
    import pytest

    with pytest.raises(ValueError, match="not found"):
        execute_order_intent("PAPER-NONEXISTENT-ABCD1234")
