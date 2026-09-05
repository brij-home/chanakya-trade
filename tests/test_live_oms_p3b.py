"""
tests/test_live_oms_p3b.py
───────────────────────────
P3-B unit tests: OMS State Machine, Pre-Trade Validation, and Kill Switch System.
"""

import pytest

# ── Kill Switch Tests ─────────────────────────────────────────────────────────

from engine.kill_switch import KillSwitchLevel, KillSwitchRegistry


@pytest.fixture
def ks_registry(tmp_path):
    """Fresh kill switch registry backed by a temp directory."""
    return KillSwitchRegistry(data_dir=tmp_path)


def test_kill_switch_system_level_blocks_all(ks_registry):
    """SYSTEM-level kill switch blocks regardless of entity."""
    ks_registry.activate(KillSwitchLevel.SYSTEM, "ALL", "Market circuit breaker", "ADMIN")
    blocked, reasons = ks_registry.is_blocked(broker="fyers", user="u1", symbol="RELIANCE")
    assert blocked is True
    assert any("SYSTEM" in r for r in reasons)


def test_kill_switch_broker_level_specific(ks_registry):
    """BROKER kill switch only blocks the named broker."""
    ks_registry.activate(KillSwitchLevel.BROKER, "zerodha", "Broker API down", "ADMIN")
    blocked_z, _ = ks_registry.is_blocked(broker="zerodha", symbol="TCS")
    blocked_f, _ = ks_registry.is_blocked(broker="fyers", symbol="TCS")
    assert blocked_z is True
    assert blocked_f is False  # Different broker — not blocked


def test_kill_switch_symbol_level_specific(ks_registry):
    """SYMBOL kill switch only blocks the named symbol."""
    ks_registry.activate(KillSwitchLevel.SYMBOL, "ADANI", "NSE restriction", "SYSTEM")
    blocked_a, _ = ks_registry.is_blocked(symbol="ADANI")
    blocked_r, _ = ks_registry.is_blocked(symbol="RELIANCE")
    assert blocked_a is True
    assert blocked_r is False


def test_kill_switch_deactivation(ks_registry):
    """Deactivating a kill switch re-enables trading."""
    ks_registry.activate(KillSwitchLevel.SYSTEM, "ALL", "Test halt", "ADMIN")
    assert ks_registry.is_blocked()[0] is True

    result = ks_registry.deactivate(
        KillSwitchLevel.SYSTEM, "ALL", actor="ADMIN", reason="All clear"
    )
    assert result is True
    assert ks_registry.is_blocked()[0] is False


def test_kill_switch_idempotent_reactivation(ks_registry):
    """Re-activating an existing kill switch updates it (idempotent)."""
    ks_registry.activate(KillSwitchLevel.SYSTEM, "ALL", "Reason A", "ADMIN")
    ks_registry.activate(KillSwitchLevel.SYSTEM, "ALL", "Reason B — updated", "ADMIN")
    active = ks_registry.list_active()
    # Should still have only one SYSTEM switch
    system_switches = [r for r in active if r.level == "SYSTEM"]
    assert len(system_switches) == 1
    assert "Reason B" in system_switches[0].reason


def test_kill_switch_list_active(ks_registry):
    """list_active returns all active switches."""
    ks_registry.activate(KillSwitchLevel.BROKER, "zerodha", "API issue", "SYSTEM")
    ks_registry.activate(KillSwitchLevel.SYMBOL, "ADANI", "Restriction", "ADMIN")
    active = ks_registry.list_active()
    assert len(active) == 2


def test_kill_switch_no_block_when_none_active(ks_registry):
    """No block when no kill switches are active."""
    blocked, reasons = ks_registry.is_blocked(
        broker="fyers", account="ACC1", user="u1", symbol="RELIANCE"
    )
    assert blocked is False
    assert reasons == []


def test_kill_switch_strategy_level(ks_registry):
    """STRATEGY kill switch blocks only the named strategy."""
    ks_registry.activate(KillSwitchLevel.STRATEGY, "macd_cross_v2", "Over-loss", "SYSTEM")
    blocked_m, _ = ks_registry.is_blocked(strategy="macd_cross_v2")
    blocked_o, _ = ks_registry.is_blocked(strategy="rsi_reversal")
    assert blocked_m is True
    assert blocked_o is False


def test_kill_switch_status_report(ks_registry):
    """get_status returns correct active count and system_halted flag."""
    assert ks_registry.get_status()["system_halted"] is False
    ks_registry.activate(KillSwitchLevel.SYSTEM, "ALL", "Halt", "ADMIN")
    status = ks_registry.get_status()
    assert status["system_halted"] is True
    assert status["total_active"] == 1


# ── Pre-Trade Validation Tests ────────────────────────────────────────────────

from engine.pretrade import validate_pretrade


def test_pretrade_valid_market_order_passes(tmp_path, monkeypatch):
    """A clean market order with no kill switches, fresh data, and sufficient cash passes."""
    # Monkeypatch kill switch registry to use temp dir
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        order_type="MARKET",
        segment="EQ",
        ltp=2900.0,
        quote_age_seconds=5.0,
        available_cash=500_000.0,
        skip_session_check=True,  # Skip market hours in test
    )
    assert result.is_eligible is True
    assert result.blocking_reasons == []


def test_pretrade_system_kill_switch_blocks(tmp_path, monkeypatch):
    """System-level kill switch blocks the order."""
    from engine import kill_switch as ks_module

    reg = KillSwitchRegistry(data_dir=tmp_path)
    reg.activate(KillSwitchLevel.SYSTEM, "ALL", "Circuit breaker", "ADMIN")
    ks_module._registry = reg

    result = validate_pretrade(
        symbol="TCS",
        side="BUY",
        quantity=5,
        ltp=4000.0,
        quote_age_seconds=2.0,
        available_cash=200_000.0,
        skip_session_check=True,
    )
    assert result.is_eligible is False
    assert any("SYSTEM" in r for r in result.blocking_reasons)

    # Cleanup
    ks_module._registry = None


def test_pretrade_stale_data_blocks(tmp_path, monkeypatch):
    """Quote older than 60 seconds blocks the order."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="INFY",
        side="BUY",
        quantity=20,
        ltp=1800.0,
        quote_age_seconds=90.0,  # > 60s threshold
        available_cash=100_000.0,
        skip_session_check=True,
    )
    assert result.is_eligible is False
    assert any("stale" in r.lower() for r in result.blocking_reasons)


def test_pretrade_insufficient_cash_blocks(tmp_path, monkeypatch):
    """Insufficient buying power blocks the order."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="SBIN",
        side="BUY",
        quantity=1000,
        ltp=600.0,  # ₹600 × 1000 = ₹6L needed
        quote_age_seconds=10.0,
        available_cash=50_000.0,  # Only ₹50K available
        skip_session_check=True,
    )
    assert result.is_eligible is False
    assert any("margin" in r.lower() or "buying" in r.lower() for r in result.blocking_reasons)


def test_pretrade_lot_size_violation_blocks(tmp_path, monkeypatch):
    """Non-lot-size-aligned quantity blocks the order."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="NIFTY24SEP25000CE",
        side="BUY",
        quantity=3,  # Not a multiple of lot size 50
        lot_size=50,
        segment="OPT",
        ltp=250.0,
        quote_age_seconds=5.0,
        available_cash=500_000.0,
        skip_session_check=True,
    )
    assert result.is_eligible is False
    assert any("lot" in r.lower() for r in result.blocking_reasons)


def test_pretrade_price_band_violation_blocks(tmp_path, monkeypatch):
    """Limit price outside circuit band blocks the order."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="HDFC",
        side="BUY",
        quantity=10,
        order_type="LIMIT",
        price=5000.0,  # > 20% above prev_close=2500 → outside band
        prev_close=2500.0,
        quote_age_seconds=5.0,
        available_cash=500_000.0,
        skip_session_check=True,
    )
    assert result.is_eligible is False
    assert any("band" in r.lower() or "circuit" in r.lower() for r in result.blocking_reasons)


def test_pretrade_missing_quote_age_blocks(tmp_path, monkeypatch):
    """Missing quote age (unknown freshness) blocks the order."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="WIPRO",
        side="BUY",
        quantity=50,
        ltp=500.0,
        quote_age_seconds=None,  # Unknown — fail-safe block
        available_cash=100_000.0,
        skip_session_check=True,
    )
    assert result.is_eligible is False
    assert any(
        "fresh" in r.lower() or "age" in r.lower() or "unknown" in r.lower()
        for r in result.blocking_reasons
    )


def test_pretrade_sell_bypasses_buying_power(tmp_path, monkeypatch):
    """SELL orders skip buying power check."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="TCS",
        side="SELL",
        quantity=10,
        ltp=4000.0,
        quote_age_seconds=5.0,
        available_cash=0.0,  # Zero cash — but SELL doesn't need margin
        skip_session_check=True,
    )
    # Sell should pass buying_power gate
    assert result.gate_results["buying_power"].passed is True


def test_pretrade_concentration_warning_non_blocking(tmp_path, monkeypatch):
    """High portfolio concentration generates warning but doesn't block."""
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    result = validate_pretrade(
        symbol="RELIANCE",
        side="BUY",
        quantity=100,
        ltp=3000.0,  # ₹3L order
        quote_age_seconds=5.0,
        available_cash=5_000_000.0,
        portfolio_value=500_000.0,  # ₹3L / ₹5L = 60% → > 20% limit
        skip_session_check=True,
    )
    assert result.is_eligible is True  # Not blocked
    assert any("concentration" in w.lower() for w in result.warnings)


# ── OMS State Machine Tests ───────────────────────────────────────────────────

from engine.oms import (
    OrderBook,
    OrderState,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
    compute_preview_hash,
)


@pytest.fixture
def book(tmp_path):
    """Fresh order book backed by a temp directory."""
    return OrderBook(data_dir=tmp_path)


def test_oms_create_order_draft(book):
    """Creating an order starts in DRAFT state."""
    order = book.create(
        symbol="RELIANCE",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=10,
        actor="user1",
    )
    assert order.state == OrderState.DRAFT.value
    assert order.order_id.startswith("ORD-")
    assert len(order.events) == 1
    assert order.events[0]["event_type"] == "ORDER_CREATED"


def test_oms_full_happy_path_paper(book):
    """Full lifecycle: DRAFT → PREVIEWED → CONFIRMED → SUBMITTING → BROKER_ACCEPTED → OPEN → FILLED."""
    order = book.create(
        symbol="TCS",
        exchange="NSE",
        side="BUY",
        order_type="LIMIT",
        quantity=5,
        price=4000.0,
        actor="user1",
        mode="PAPER",
    )
    assert order.state == OrderState.DRAFT.value

    book.preview(order.order_id, "user1")
    order = book.get(order.order_id)
    assert order.state == OrderState.PREVIEWED.value

    book.confirm(order.order_id, "user1", preview_hash_check=order.preview_hash)
    order = book.get(order.order_id)
    assert order.state == OrderState.USER_CONFIRMED.value

    book.submit(order.order_id, "user1", broker_request_id="REQ-001")
    order = book.get(order.order_id)
    assert order.state == OrderState.SUBMITTING.value

    book.broker_accept(order.order_id, broker_order_id="BRK-12345", actor="BROKER")
    order = book.get(order.order_id)
    assert order.state == OrderState.BROKER_ACCEPTED.value

    book.open(order.order_id, "BROKER")
    order = book.get(order.order_id)
    assert order.state == OrderState.OPEN.value

    book.fill(order.order_id, filled_qty=5, fill_price=3995.0, actor="BROKER")
    order = book.get(order.order_id)
    assert order.state == OrderState.FILLED.value
    assert order.average_fill_price == 3995.0
    assert order.filled_quantity == 5
    assert order.is_terminal is True


def test_oms_partial_fill_then_fill(book):
    """Partial fill updates quantities correctly; then FILLED on completion."""
    order = book.create(
        symbol="INFY",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=100,
        actor="trader",
    )
    book.preview(order.order_id, "trader")
    book.confirm(order.order_id, "trader")
    book.submit(order.order_id, "trader")
    book.broker_accept(order.order_id, "BRK-001")
    book.open(order.order_id)

    book.fill(order.order_id, filled_qty=60, fill_price=1800.0, partial=True)
    order = book.get(order.order_id)
    assert order.state == OrderState.PARTIAL.value
    assert order.filled_quantity == 60
    assert order.remaining_quantity == 40

    book.fill(order.order_id, filled_qty=40, fill_price=1802.0, partial=False)
    order = book.get(order.order_id)
    assert order.state == OrderState.FILLED.value
    assert order.filled_quantity == 100
    assert order.fill_pct == 100.0
    # Weighted average: (60*1800 + 40*1802) / 100 = 1800.8
    assert abs(order.average_fill_price - 1800.8) < 0.1


def test_oms_rejection_path(book):
    """Rejected orders are terminal."""
    order = book.create(
        symbol="SBIN",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=50,
        actor="user2",
    )
    book.preview(order.order_id, "user2")
    book.confirm(order.order_id, "user2")
    book.submit(order.order_id, "user2")

    book.reject(order.order_id, reason="Insufficient margin at broker", actor="BROKER")
    order = book.get(order.order_id)
    assert order.state == OrderState.REJECTED.value
    assert order.is_terminal is True


def test_oms_unknown_state_and_reconciliation(book):
    """UNKNOWN → RECONCILIATION_REQUIRED path for broker timeout."""
    order = book.create(
        symbol="HDFCBANK",
        exchange="NSE",
        side="SELL",
        order_type="MARKET",
        quantity=20,
        actor="system",
    )
    book.preview(order.order_id, "system")
    book.confirm(order.order_id, "system")
    book.submit(order.order_id, "system")

    # Broker timed out — go to UNKNOWN
    book.mark_unknown(order.order_id, "SYSTEM", "Broker did not respond within 30s")
    order = book.get(order.order_id)
    assert order.state == OrderState.UNKNOWN.value

    # After manual review, mark as RECONCILIATION_REQUIRED
    book.reconcile_required(order.order_id, "ADMIN", "Manual review required")
    order = book.get(order.order_id)
    assert order.state == OrderState.RECONCILIATION_REQUIRED.value
    assert order.is_terminal is True


def test_oms_idempotency_same_key_returns_same_order(book):
    """Creating two orders with the same idempotency_key returns the same order."""
    idem = "unique-idem-key-abc"
    order1 = book.create(
        symbol="WIPRO",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=10,
        actor="user1",
        idempotency_key=idem,
    )
    order2 = book.create(
        symbol="WIPRO",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=10,
        actor="user1",
        idempotency_key=idem,
    )
    assert order1.order_id == order2.order_id


def test_oms_preview_hash_tamper_detection(book):
    """Tampered preview hash is rejected on confirm."""
    order = book.create(
        symbol="RELIANCE",
        exchange="NSE",
        side="BUY",
        order_type="LIMIT",
        quantity=5,
        price=3000.0,
        actor="user1",
    )
    book.preview(order.order_id, "user1")

    with pytest.raises(ValueError, match="Preview hash mismatch"):
        book.confirm(order.order_id, "user1", preview_hash_check="WRONG_HASH_TAMPERED")


def test_oms_terminal_state_blocks_further_transitions(book):
    """Orders in terminal states cannot be transitioned further."""
    order = book.create(
        symbol="LTIM",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=5,
        actor="user1",
    )
    book.preview(order.order_id, "user1")
    book.confirm(order.order_id, "user1")
    book.cancel(order.order_id, "user1", reason="Changed mind")

    order = book.get(order.order_id)
    assert order.state == OrderState.CANCELLED.value

    with pytest.raises(ValueError, match="terminal state"):
        book.preview(order.order_id, "user1")  # Should raise — already terminal


def test_oms_invalid_transition_raises(book):
    """Invalid state transitions raise ValueError."""
    order = book.create(
        symbol="COFORGE",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=10,
        actor="u1",
    )
    # DRAFT → FILLED is not a valid transition
    with pytest.raises(ValueError, match="Invalid transition"):
        from engine.oms import OrderState as OS

        book._transition(order, OS.FILLED, "u1", "Attempted invalid jump")


def test_oms_cancel_flow(book):
    """OPEN → CANCEL_PENDING → CANCELLED flow."""
    order = book.create(
        symbol="DRREDDY",
        exchange="NSE",
        side="BUY",
        order_type="LIMIT",
        quantity=5,
        price=6000.0,
        actor="user1",
    )
    book.preview(order.order_id, "user1")
    book.confirm(order.order_id, "user1")
    book.submit(order.order_id, "user1")
    book.broker_accept(order.order_id, "BRK-CXL-001")
    book.open(order.order_id)

    book.request_cancel(order.order_id, "user1")
    order = book.get(order.order_id)
    assert order.state == OrderState.CANCEL_PENDING.value

    book.cancel(order.order_id, "BROKER", "Cancellation confirmed by broker")
    order = book.get(order.order_id)
    assert order.state == OrderState.CANCELLED.value
    assert order.is_terminal is True


def test_oms_get_unreconciled(book):
    """get_unreconciled returns UNKNOWN and RECONCILIATION_REQUIRED orders."""
    order = book.create(
        symbol="AXISBANK",
        exchange="NSE",
        side="BUY",
        order_type="MARKET",
        quantity=10,
        actor="u1",
    )
    book.preview(order.order_id, "u1")
    book.confirm(order.order_id, "u1")
    book.submit(order.order_id, "u1")
    book.mark_unknown(order.order_id, "SYSTEM", "Timeout")

    unreconciled = book.get_unreconciled()
    assert len(unreconciled) == 1
    assert unreconciled[0].order_id == order.order_id


def test_oms_preview_hash_computation():
    """Preview hash is deterministic for same inputs."""
    h1 = compute_preview_hash("RELIANCE", "NSE", "BUY", "LIMIT", 10, 2900.0, "CNC", "PAPER")
    h2 = compute_preview_hash("RELIANCE", "NSE", "BUY", "LIMIT", 10, 2900.0, "CNC", "PAPER")
    h3 = compute_preview_hash(
        "RELIANCE", "NSE", "BUY", "LIMIT", 10, 2901.0, "CNC", "PAPER"
    )  # Different price
    assert h1 == h2
    assert h1 != h3


def test_oms_all_valid_transitions_covered():
    """Every state has a defined transition map (no missing states)."""
    for state in OrderState:
        assert state in VALID_TRANSITIONS, f"Missing transition map for {state}"


def test_oms_terminal_states_have_no_transitions():
    """Terminal states must have no outgoing transitions."""
    for ts in TERMINAL_STATES:
        assert VALID_TRANSITIONS[ts] == set(), f"{ts} should have no transitions"


# ── Gap 1: execute_order_intent safety gate tests ─────────────────────────────

import sqlite3
from engine.order_lifecycle import confirm_order_intent, execute_order_intent, preview_order_intent


def confirm_lifecycle_order(order):
    """All execution tests must cross the real server confirmation boundary."""
    return confirm_order_intent(order.order_id, order.preview_hash)


@pytest.fixture
def paper_order(tmp_path, monkeypatch):
    """Create a PREVIEW-state paper order in a temp DB for test."""
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    # Redirect the orders DB to a temp path
    monkeypatch.setattr(
        "engine.order_lifecycle._get_db_path",
        lambda: tmp_path / "orders.db",
    )
    # Use a minimal kill switch registry
    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    order = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        price=2900.0,
        order_type="LIMIT",
    )
    return order


def test_paper_broker_error_yields_rejected_not_filled(tmp_path, monkeypatch):
    """
    When PaperBroker raises an exception during execute_order_intent,
    the order status MUST be REJECTED with the real error as rejection_reason.
    It MUST NOT be FILLED_PAPER with a fabricated broker_order_id.
    """
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    # Create a preview order
    order = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=5,
        price=4000.0,
    )

    # Make PaperBroker always raise
    class _BrokenPaperBroker:
        def place_order(self, req):
            raise RuntimeError("Simulated disk failure")

    monkeypatch.setattr(
        "engine.order_lifecycle.PaperBroker",
        _BrokenPaperBroker,
        raising=False,
    )
    # Ensure the import path inside execute_order_intent resolves to our broken broker
    import engine.paper as paper_mod

    monkeypatch.setattr(paper_mod, "PaperBroker", _BrokenPaperBroker)

    confirm_lifecycle_order(order)
    result = execute_order_intent(order.order_id)

    assert result.status == "REJECTED", (
        f"Expected REJECTED, got {result.status}. "
        "Paper broker errors must never produce FILLED_PAPER."
    )
    assert result.broker_order_id is None, (
        "broker_order_id must be None when PaperBroker raised — never fabricate an ID."
    )
    assert result.rejection_reason is not None
    assert "PaperBroker error" in result.rejection_reason


def test_execute_order_blocks_without_live_flag(tmp_path, monkeypatch):
    """
    In EXECUTE mode without ALLOW_LIVE_TRADING=1,
    execute_order_intent must raise PermissionError — never fabricate an order.
    """
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "0")

    from engine import kill_switch as ks_module

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    from engine.order_lifecycle import confirm_order_intent

    order = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=10,
        price=1800.0,
        idempotency_key="LIVE-IDEMP-BLOCK-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    confirm_lifecycle_order(order)
    with pytest.raises(PermissionError, match="ALLOW_LIVE_TRADING"):
        execute_order_intent(order.order_id)


def test_execute_order_calls_pretrade_and_blocks_stale_data(tmp_path, monkeypatch):
    """
    In EXECUTE mode with ALLOW_LIVE_TRADING=1, execute_order_intent must run
    validate_pretrade. If pretrade validation blocks, the order must be rejected
    with ValueError — never fabricate a live order.
    """
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    # Exercise the downstream pre-trade path only after deliberately opening
    # the otherwise fail-closed personal-pilot guardrails.
    monkeypatch.setenv("PILOT_ALLOW_LIVE_EXECUTION", "1")
    monkeypatch.setenv("PILOT_ALLOWED_SEGMENTS", "EQUITY_INTRADAY")
    monkeypatch.setenv("PILOT_ALLOWED_PRODUCTS", "MIS")
    monkeypatch.setenv("PILOT_MAX_ORDER_NOTIONAL", "1000000")

    from engine import kill_switch as ks_module
    from engine.order_lifecycle import confirm_order_intent

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    order = preview_order_intent(
        symbol="HDFCBANK",
        side="BUY",
        quantity=5,
        price=1600.0,
        idempotency_key="LIVE-IDEMP-BLOCK-2",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    # Provide the execution account separately from a timestamped market-data
    # quote; live routing deliberately does not use the execution broker feed.
    class _ContextOnlyBroker:
        account_id = "CTX_TEST"

        def get_funds(self):
            return {"available_cash": 50_000.0}

    from brokers.base import Quote

    quote = Quote(
        symbol="NSE:HDFCBANK",
        last_price=1600.0,
        open=1600.0,
        high=1600.0,
        low=1600.0,
        close=1600.0,
        volume=1,
        provider="test",
        source="REST",
        data_state="LIVE",
    )
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: _ContextOnlyBroker())
    monkeypatch.setattr("market.quotes.get_quote", lambda instruments: {instruments[0]: quote})

    # Stub validate_pretrade to block due to stale/missing quote
    class _BlockedResult:
        is_eligible = False
        blocking_reasons = ["data_freshness: LTP unavailable (quote_age_seconds=0.0, ltp=None)"]

    monkeypatch.setattr("engine.pretrade.validate_pretrade", lambda **kw: _BlockedResult())

    confirm_lifecycle_order(order)
    with pytest.raises(ValueError, match="Pre-trade validation blocked"):
        execute_order_intent(order.order_id)


def test_execute_order_broker_timeout_transitions_to_unknown_freeze(tmp_path, monkeypatch):
    """
    When the live broker raises an exception (e.g. timeout) at place_order,
    the order must transition to UNKNOWN_FREEZE — never to OPEN with a fabricated ID.
    """
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("PILOT_ALLOW_LIVE_EXECUTION", "1")
    monkeypatch.setenv("PILOT_ALLOWED_SEGMENTS", "EQUITY_INTRADAY")
    monkeypatch.setenv("PILOT_ALLOWED_PRODUCTS", "MIS")
    monkeypatch.setenv("PILOT_MAX_ORDER_NOTIONAL", "1000000")

    from engine import kill_switch as ks_module
    from engine.order_lifecycle import confirm_order_intent

    ks_module._registry = KillSwitchRegistry(data_dir=tmp_path)

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    order = preview_order_intent(
        symbol="SBIN",
        side="BUY",
        quantity=10,
        price=600.0,
        idempotency_key="LIVE-IDEMP-TIMEOUT-1",
    )
    confirm_order_intent(order.order_id, preview_hash=order.preview_hash)

    # Patch validate_pretrade at its source module so the lazy import picks it up
    class _PassResult:
        is_eligible = True
        blocking_reasons = []

    monkeypatch.setattr("engine.pretrade.validate_pretrade", lambda **kw: _PassResult())

    # The execution adapter supplies account funds and submits the order; a
    # timestamped quote is supplied through the independent market boundary.
    class _TimeoutBroker:
        account_id = "TEST_ACCOUNT"

        def get_funds(self):
            """Return minimal funds so context fetch completes."""
            return {"available_cash": 100_000.0}

        def place_order(self, req):
            raise TimeoutError("Broker TCP connection timed out after 30s")

    from brokers.base import Quote

    quote = Quote(
        symbol="NSE:SBIN",
        last_price=600.0,
        open=600.0,
        high=600.0,
        low=600.0,
        close=600.0,
        volume=1,
        provider="test",
        source="REST",
        data_state="LIVE",
    )
    monkeypatch.setattr("brokers.session.get_execution_broker", lambda: _TimeoutBroker())
    monkeypatch.setattr("market.quotes.get_quote", lambda instruments: {instruments[0]: quote})

    confirm_lifecycle_order(order)
    with pytest.raises(RuntimeError, match="UNKNOWN_FREEZE"):
        execute_order_intent(order.order_id)

    # Verify the DB reflects UNKNOWN_FREEZE — not OPEN and not a fabricated ID
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, broker_order_id FROM orders_ledger WHERE order_id = ?",
            (order.order_id,),
        ).fetchone()

    assert row["status"] == "UNKNOWN_FREEZE", (
        f"Expected UNKNOWN_FREEZE, got {row['status']}. "
        "Broker timeout must never produce a fabricated OPEN order."
    )
    assert row["broker_order_id"] is None, (
        "broker_order_id must be None on broker timeout — never fabricate an ID."
    )


def test_paper_preview_cannot_execute_in_live_mode(tmp_path, monkeypatch):
    """
    P0 Safety: An order previewed in SIMULATE (Paper) mode must NEVER be executable
    if the system switches to EXECUTE (Live) mode. execute_order_intent must raise PermissionError.
    """
    import sqlite3
    from engine.order_lifecycle import preview_order_intent, execute_order_intent

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    # 1. Preview order under SIMULATE mode
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")
    paper_order = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        price=2850.0,
        order_type="LIMIT",
        product="MIS",
    )
    assert paper_order.mode == "SIMULATE"
    assert paper_order.order_id.startswith("PAPER-")

    # 2. Switch mode to EXECUTE (with live permission flag)
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")

    # 3. Attempt to execute the paper preview in EXECUTE mode -> MUST fail with PermissionError
    with pytest.raises(PermissionError, match="Cross-mode order execution is strictly prohibited"):
        execute_order_intent(paper_order.order_id)

    # Verify order was not executed or changed to LIVE
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, mode FROM orders_ledger WHERE order_id = ?",
            (paper_order.order_id,),
        ).fetchone()

    assert row["status"] == "PREVIEW"
    assert row["mode"] == "SIMULATE"


def test_order_intent_double_submit_fails(tmp_path, monkeypatch):
    """
    P0 Safety: Submitting an already executed or submitted order intent must fail atomically.
    Second execute_order_intent call must raise ValueError.
    """
    from engine.order_lifecycle import preview_order_intent, execute_order_intent
    from brokers.base import OrderResponse

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)

    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    class _MockPaperBroker:
        def place_order(self, req):
            return OrderResponse(order_id="PAPER-9999", status="COMPLETE", message="Filled")

    monkeypatch.setattr("engine.paper.PaperBroker", lambda: _MockPaperBroker())

    order = preview_order_intent(
        symbol="INFY",
        side="BUY",
        quantity=5,
        price=1800.0,
        order_type="LIMIT",
        product="MIS",
    )

    # First execution succeeds
    confirm_lifecycle_order(order)
    first_res = execute_order_intent(order.order_id)
    assert first_res.status == "FILLED_PAPER"

    # Second execution must raise ValueError
    with pytest.raises(ValueError, match="cannot be executed"):
        execute_order_intent(order.order_id)


def test_multi_asset_canonical_instrument_resolution(tmp_path, monkeypatch):
    """
    Authoritative Instrument Resolution: preview_order_intent must resolve exchange and segment
    accurately for equities, commodities (MCX), and currencies (CDS).
    """
    from engine.order_lifecycle import preview_order_intent

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    # 1. Commodity
    gold_order = preview_order_intent(
        symbol="MCX:GOLD",
        side="BUY",
        quantity=1,
        price=74000.0,
    )
    assert gold_order.exchange == "MCX"
    assert gold_order.segment == "COMMODITY"

    # 2. Currency
    usd_order = preview_order_intent(
        symbol="USDINR",
        side="BUY",
        quantity=1000,
        price=86.5,
    )
    assert usd_order.exchange == "CDS"
    assert usd_order.segment == "CURRENCY"

    # 3. Equity Delivery
    equity_order = preview_order_intent(
        symbol="TCS",
        side="BUY",
        quantity=10,
        price=3900.0,
        product="CNC",
    )
    assert equity_order.exchange == "NSE"
    assert equity_order.segment == "EQUITY_DELIVERY"


def test_live_order_requires_confirmed_status(tmp_path, monkeypatch):
    """
    P0 Double Confirmation Gate: In EXECUTE (Live) mode, direct execution of an order
    in PREVIEW status MUST be rejected. The order must first be explicitly CONFIRMED.
    """
    from engine.order_lifecycle import (
        preview_order_intent,
        confirm_order_intent,
        execute_order_intent,
    )

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "1")

    # 1. Preview order
    order = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=5,
        price=2900.0,
        idempotency_key="LIVE-IDEMP-CONFIRM-1",
    )
    assert order.status == "PREVIEW"

    # 2. Direct execute from PREVIEW must fail
    with pytest.raises(ValueError, match="must be CONFIRMED before live execution"):
        execute_order_intent(order.order_id)

    # 3. Explicitly confirm intent
    confirmed_order = confirm_order_intent(order.order_id, preview_hash=order.preview_hash)
    assert confirmed_order.status == "CONFIRMED"


def test_client_exchange_segment_override_rejected(tmp_path, monkeypatch):
    """
    Authoritative Resolution: Client attempts to pass crafted exchange or segment
    overrides are rejected rather than silently rewritten.
    """
    from engine.order_lifecycle import preview_order_intent

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    with pytest.raises(ValueError, match="conflicts with canonical"):
        preview_order_intent(
            symbol="MCX:GOLD",
            side="BUY",
            quantity=1,
            price=74000.0,
            exchange="BSE",  # Malicious/bogus client override
            segment="EQUITY_INTRADAY",  # Malicious/bogus client override
        )


def test_duplicate_intentional_orders_with_distinct_keys(tmp_path, monkeypatch):
    """
    Concurrency & Usability: Placing two intentional duplicate orders with distinct
    client UUID keys generates two separate orders in the ledger cleanly.
    Reusing the exact same idempotency key returns the existing order.
    """
    from engine.order_lifecycle import preview_order_intent

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setenv("TRADING_MODE", "SIMULATE")

    # Order 1 with key A
    order1 = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        price=2900.0,
        idempotency_key="INTENT-UUID-A",
    )

    # Order 2 with identical parameters but key B -> must succeed as separate order
    order2 = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        price=2900.0,
        idempotency_key="INTENT-UUID-B",
    )
    assert order1.order_id != order2.order_id
    assert order1.idempotency_key != order2.idempotency_key

    # Retry of Order 1 with key A -> must return order 1
    retry_order1 = preview_order_intent(
        symbol="RELIANCE",
        side="BUY",
        quantity=10,
        price=2900.0,
        idempotency_key="INTENT-UUID-A",
    )
    assert retry_order1.order_id == order1.order_id


def test_live_preview_requires_explicit_idempotency_key(tmp_path, monkeypatch):
    """
    P0 Safety: Live order previews must require an explicit client idempotency key.
    """
    from engine.order_lifecycle import preview_order_intent

    db_path = tmp_path / "orders.db"
    monkeypatch.setattr("engine.order_lifecycle._get_db_path", lambda: db_path)
    monkeypatch.setenv("TRADING_MODE", "EXECUTE")

    with pytest.raises(ValueError, match="idempotency_key is required for live order preview"):
        preview_order_intent(
            symbol="RELIANCE",
            side="BUY",
            quantity=10,
            price=2900.0,
            idempotency_key=None,
        )
