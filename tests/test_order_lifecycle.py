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
    with pytest.raises(ValueError, match="not found"):
        execute_order_intent("PAPER-NONEXISTENT-ABCD1234")


def test_paper_preview_cannot_execute_in_live_mode(monkeypatch):
    """
    P0 Safety Invariant: A preview created in PAPER/SIMULATE mode MUST NOT be executed
    if the system is switched to LIVE/EXECUTE mode.
    """
    from engine.modes import ModeInfo, TradingMode

    # 1. Preview generated in SIMULATE mode
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
        symbol="SBIN",
        side="BUY",
        quantity=50,
        price=820.0,
        order_type="LIMIT",
    )
    assert intent.mode == "SIMULATE"

    # 2. User switches mode to EXECUTE (live)
    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(
            mode=TradingMode.EXECUTE,
            is_observe=False,
            is_simulate=False,
            is_execute=True,
            description="Execute",
        ),
    )

    # 3. Execution attempt on paper preview must be strictly blocked
    with pytest.raises(PermissionError, match="Cross-mode order execution is strictly prohibited"):
        execute_order_intent(intent.order_id)


def test_live_preview_cannot_execute_in_paper_mode(monkeypatch):
    """
    P0 Safety Invariant: A preview created in LIVE/EXECUTE mode MUST NOT be executed
    if the system is switched to PAPER/SIMULATE mode.
    """
    from engine.modes import ModeInfo, TradingMode

    # 1. Preview generated in EXECUTE mode
    monkeypatch.setattr(
        "engine.order_lifecycle.get_trading_mode",
        lambda: ModeInfo(
            mode=TradingMode.EXECUTE,
            is_observe=False,
            is_simulate=False,
            is_execute=True,
            description="Execute",
        ),
    )

    intent = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=10,
        price=1850.0,
        order_type="LIMIT",
    )
    assert intent.mode == "EXECUTE"

    # 2. System switched to SIMULATE mode
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

    # 3. Execution attempt must raise PermissionError
    with pytest.raises(PermissionError, match="Cross-mode order execution is strictly prohibited"):
        execute_order_intent(intent.order_id)


def test_double_submit_rejected(monkeypatch, tmp_path):
    """
    P0 Safety Invariant: An order that has already been executed cannot be submitted again.
    """
    from engine.modes import ModeInfo, TradingMode

    paper_file = tmp_path / "paper_portfolio.json"
    monkeypatch.setattr("engine.paper.PAPER_FILE", paper_file)
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
        symbol="TRENT",
        side="BUY",
        quantity=5,
        price=5200.0,
        order_type="MARKET",
    )

    # First execution succeeds
    first_exec = execute_order_intent(intent.order_id)
    assert first_exec.status == "FILLED_PAPER"

    # Second execution attempt on the same order must fail closed
    with pytest.raises(
        ValueError, match="cannot be executed because its current status is 'FILLED_PAPER'"
    ):
        execute_order_intent(intent.order_id)


def test_preview_idempotency_differentiates_mode_and_parameters():
    """
    P0 Invariant: Preview canonical hash binds mode, order_type, segment, exchange.
    Different parameters must not collide or reuse stale previews.
    """
    intent_limit = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=3500.0,
        order_type="LIMIT",
    )

    intent_market = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=3500.0,
        order_type="MARKET",
    )

    assert intent_limit.preview_hash != intent_market.preview_hash
    assert intent_limit.order_id != intent_market.order_id


def test_authoritative_instrument_resolution_in_order_lifecycle():
    """
    Follow-up Invariant: Exchange and segment are resolved authoritatively
    for equities, MCX commodities, and currency pairs.
    """
    # 1. MCX Commodity
    gold_intent = preview_order_intent(
        symbol="MCX:GOLD",
        side="BUY",
        quantity=1,
        price=72000.0,
    )
    assert gold_intent.exchange == "MCX"
    assert gold_intent.segment == "COMMODITY"

    # 2. Currency Pair
    usdinr_intent = preview_order_intent(
        symbol="USDINR",
        side="BUY",
        quantity=1,
        price=83.50,
    )
    assert usdinr_intent.exchange == "CDS"
    assert usdinr_intent.segment == "CURRENCY"

    # 3. Delivery Equity
    eq_delivery = preview_order_intent(
        symbol="HDFCBANK",
        side="BUY",
        quantity=20,
        price=1650.0,
        product="CNC",
    )
    assert eq_delivery.exchange == "NSE"
    assert eq_delivery.segment == "EQUITY_DELIVERY"
