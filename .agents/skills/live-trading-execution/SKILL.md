---
name: live-trading-execution
description: >-
  Order lifecycle state machine, safety gate sequence, live vs paper mode
  contracts, UNKNOWN_FREEZE handling, reconciliation honesty, and idempotency
  semantics for all execution code in chanakya-trade.
---

# Live Trading Execution Runbook

> ⚠️ **MANDATORY**: Read this skill IN FULL before modifying any file in `engine/order_lifecycle.py`, `engine/trade_executor.py`, `engine/oms.py`, `engine/pilot_safety.py`, `engine/pretrade.py`, or any broker `place_order()` path.

<!-- TOC -->
- [1. Order Lifecycle State Machine](#1-order-lifecycle-state-machine)
- [2. Mandatory Execution Gate Sequence](#2-mandatory-execution-gate-sequence)
- [3. Mode Contract](#3-mode-contract)
- [4. Fail-Closed Safety Contracts](#4-fail-closed-safety-contracts)
- [5. Idempotency Semantics](#5-idempotency-semantics)
- [6. Reconciliation Honesty Contract](#6-reconciliation-honesty-contract)
- [7. Key Functions & Files](#7-key-functions--files)
- [8. Testing](#8-testing)
<!-- /TOC -->

---

## 1. Order Lifecycle State Machine

```
DRAFT -> PREVIEW -> CONFIRMED -> SUBMITTING -> OPEN
                                             -> FILLED
                                             -> PARTIALLY_FILLED
                                             -> REJECTED
                                             -> UNKNOWN_FREEZE
                 -> CANCELLED (user cancel before SUBMITTING)
```

| Status | Meaning | Who Sets It |
|--------|---------|-------------|
| `DRAFT` | Intent created, not previewed | Client |
| `PREVIEW` | Charges + pre-trade computed | Server |
| `CONFIRMED` | User confirmed the preview hash | Client |
| `SUBMITTING` | Written to ledger, about to hit broker | Server (atomic) |
| `OPEN` | Broker acknowledged, order resting | Broker response |
| `FILLED` | Fully executed | Broker fill event |
| `PARTIALLY_FILLED` | Partial fill | Broker fill event |
| `REJECTED` | Broker/pre-trade hard-rejected | Broker or gate |
| `UNKNOWN_FREEZE` | Ambiguous/timed-out response | Fail-closed handler |
| `CANCELLED` | User or system cancelled pre-submit | Server |

### Critical Transition Rules
- A **PREVIEW is NOT executable**. The client must submit the **exact server-generated `preview_hash`** to transition to `CONFIRMED`.
- Only `CONFIRMED -> SUBMITTING` is permitted — atomically, via the ledger.
- Never skip `SUBMITTING`. Writing to ledger before broker contact is mandatory for crash recovery.
- `UNKNOWN_FREEZE` is terminal until reconciliation resolves it — do NOT auto-retry.

---

## 2. Mandatory Execution Gate Sequence

Every `execute_order_intent()` call MUST follow this exact order. Any short-circuit is a **safety violation**:

```python
# engine/order_lifecycle.py — required call sequence
assert_live_execution_allowed()   # checks TRADING_MODE + ALLOW_LIVE_TRADING
pilot_safety_gate()               # behavioral flags: TILT_LOCKOUT, DAILY_LOSS_CAP
validate_pretrade(order)          # STT/GST checks, margin, position limits
# Write SUBMITTING to ledger (atomic) before any broker network call
transition_status(order_id, "SUBMITTING")
result = get_execution_broker().place_order(order)
# Handle result (see section 4)
```

### `assert_live_execution_allowed()`
- Raises `PermissionError` if `TRADING_MODE != "EXECUTE"` OR `ALLOW_LIVE_TRADING != "1"`
- File: `engine/order_lifecycle.py`

### `pilot_safety_gate()`
- Checks behavioral risk flags: loss streak >= 3, pyramiding into losers, daily loss cap
- Presents coaching alternatives, requires `allow_override=True` to proceed — never hard-blocks
- File: `engine/pilot_safety.py`

### `validate_pretrade(order)`
- Computes STT, GST, SEBI charges, checks margin, verifies instrument from canonical master
- File: `engine/pretrade.py`

---

## 3. Mode Contract

| `.env` Setting | Mode | `/api/mode` Returns | Behavior |
|----------------|------|--------------------|-|
| `TRADING_MODE=OBSERVE` | Demo | `"DEMO"` | Read-only — no orders placed |
| `TRADING_MODE=SIMULATE` | Paper | `"PAPER"` | Paper broker only |
| `TRADING_MODE=EXECUTE` + `ALLOW_LIVE_TRADING=1` | Live | `"LIVE"` | Real broker orders |
| `TRADING_MODE=EXECUTE` without `ALLOW_LIVE_TRADING=1` | Blocked | — | `PermissionError` raised |

**Rules:**
- Do NOT add a 4th mode
- Do NOT infer mode client-side — always call `GET /api/mode`
- `ModeBanner.jsx` reads exclusively from `/api/mode`
- If an unknown backend mode is received, raise — never silently default to `PAPER`

---

## 4. Fail-Closed Safety Contracts

### Paper Broker Exception -> `REJECTED`
```python
try:
    result = paper_broker.place_order(order)
except Exception as e:
    # CORRECT:
    return OrderResult(status="REJECTED", rejection_reason=str(e), broker_order_id=None)
    # NEVER: return OrderResult(status="FILLED_PAPER", broker_order_id="PAPER-fake-123")
```

### Live Broker Ambiguous/Timeout -> `UNKNOWN_FREEZE`
```python
try:
    result = live_broker.place_order(order)
    # if response is ambiguous (no order_id, no status):
    return OrderResult(status="UNKNOWN_FREEZE", broker_order_id=None)
except (TimeoutError, ConnectionError):
    # CORRECT:
    return OrderResult(status="UNKNOWN_FREEZE", broker_order_id=None)
    # NEVER: return OrderResult(status="OPEN", broker_order_id="LIVE-fabricated-id")
```

### What NEVER to do
- Never fabricate `broker_order_id` (e.g. `"LIVE-XXXXXX"`) on timeout
- Never set `status="OPEN"` on ambiguous response
- Never set `status="FILLED_PAPER"` on paper broker exception
- Never retry an `UNKNOWN_FREEZE` order without reconciliation first

---

## 5. Idempotency Semantics

- Each order intent gets a **cryptographically random** `idempotency_key` (UUID4)
- Reuse the same key ONLY to retry the exact same request
- **Never** derive `idempotency_key` from order fields (symbol + price + qty)
- **Never** use `INSERT OR REPLACE` on the order ledger — use `INSERT OR IGNORE` + detect duplicate
- The ledger is the **source of truth** — broker response is secondary

```python
# Correct idempotency key generation
idempotency_key = str(uuid.uuid4())  # always fresh per new intent

# Wrong: never do this
idempotency_key = hashlib.sha256(f"{symbol}{qty}{price}".encode()).hexdigest()
```

---

## 6. Reconciliation Honesty Contract

`GET /api/reconciliation` MUST:

1. Call `get_execution_broker().get_positions()` — real broker positions
2. Call `get_execution_broker().get_funds()` — real broker funds
3. Internal side comes from **persisted local fills + opening-cash baseline** (never same source as broker)
4. If broker/ledger is unavailable -> return `{"status": "UNAVAILABLE"}` — never fabricate clean reconciliation
5. Successful response MUST include: `broker_account_id`, `broker_snapshot_at`, `correlation_id`

```python
# Correct
broker_positions = get_execution_broker().get_positions()
internal_fills = load_fills_from_ledger()  # different source

# Wrong — never do this
broker_positions = internal_positions  # circular self-comparison
```

---

## 7. Key Functions & Files

| Function | File | Purpose |
|----------|------|---------|
| `execute_order_intent()` | `engine/order_lifecycle.py` | Main execution entry point |
| `assert_live_execution_allowed()` | `engine/order_lifecycle.py` | Mode + env gate |
| `pilot_safety_gate()` | `engine/pilot_safety.py` | Behavioral risk check |
| `validate_pretrade()` | `engine/pretrade.py` | Charge + margin validation |
| `transition_status()` | `engine/order_lifecycle.py` | Atomic ledger state machine |
| `get_execution_broker()` | `brokers/session.py` | Returns active execution broker |
| `calculate_transaction_charges()` | `engine/charges.py` | STT, GST, SEBI computation |
| `record_audit_event()` | `engine/security_audit.py` | Immutable audit trail |

---

## 8. Testing

```powershell
# Live OMS, pre-trade gates & execution safety
.venv\Scripts\pytest.exe tests/test_live_oms_p3b.py tests/test_order_lifecycle.py -v

# Mode banner truthfulness
.venv\Scripts\pytest.exe tests/test_mode_banner_mapping.py -v

# Reconciliation unavailable contract
.venv\Scripts\pytest.exe tests/test_reconciliation_unavailable.py tests/test_reconciliation_typed.py -v

# Pilot safety gate
.venv\Scripts\pytest.exe tests/test_risk_gate.py tests/test_preflight.py -v

# Full execution routing
.venv\Scripts\pytest.exe tests/test_execution_routing.py tests/test_trade_executor.py -v
```
