# Release Acceptance Checkpoint — 2 November 2026

## Executive Summary
This document records the completed implementation and verification of the five release-blocking failure classes (P0-1, P0-2, P1-3, P1-4, P1-5) identified during independent review on 2 November 2026.

All changes have been validated through real-boundary regression test suites and verified against all 38 core safety invariants and institutional trading guardrails in `AGENTS.md` and `docs/SAFETY_CONTRACTS.md`.

---

## 1. Verified Resolution of Release Blockers

### P0-1 & P1-4: Authentic Broker Execution Ingestion & Concurrent Fill Ledger
- **Root Cause:**
  - Broker fill recording previously called `calculate_transaction_charges` with invalid kwargs (`exchange`, `product`) and attempted to read `.total` instead of `.total_charges`. The resulting `TypeError` was caught and swallowed by an empty/debug catch block, resulting in unpersisted fills and fabricated ledger reconciliation claims.
  - Live execution pipelines synthesized trade IDs as `TRD-{broker_order_id}` and defaulted `account_id` to `'LIVE_ACCOUNT'`, inferring execution quantities and prices from preview/requested order values rather than independent broker execution records.
- **Architectural Fix:**
  - Updated calls to `calculate_transaction_charges(price=..., quantity=..., segment=..., side=...)` and `.total_charges` in both live and simulation pathways.
  - Implemented `ingest_broker_executions()` in [`engine/order_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/order_lifecycle.py):
    - Extracts authentic trade IDs, quantities, prices, and timestamps from `broker_res.raw`, `broker_res.trades`, or live broker polling methods (`get_trades()` / `get_trade_history()`).
    - Explicitly rejects missing trade IDs, synthetic fallback prefixes (`TRD-`), generic account placeholders (`LIVE_ACCOUNT`), zero/negative quantities, and non-finite prices.
    - If trade facts are pending, fills remain unrecorded with order state marked `PENDING_FACTS`.
  - Serialized Concurrency: `record_execution_fill()` acquires an exclusive write lock using `conn.execute("BEGIN IMMEDIATE")` in SQLite, serializing monotonic sequence number allocation across concurrent execution fill arrivals.
  - Timezone Normalization: Enforces timezone-aware timestamps (rejects naive datetime strings).
  - Fact Immutability & Authorized Fee Adjustments: On duplicate broker trade arrival, validates all immutable trade facts (`broker_name`, `exchange`, `segment`, `product`, `symbol`, `side`, `quantity`, `fill_price`, `broker_order_id`). If facts match but charges differ, updates the fee, records audit, and returns `is_idempotent_retry=True, is_fee_adjustment=True`. If immutable trade facts conflict, raises `ValueError` and rolls back.
  - Ingestion Failure Propagation: Any statutory calculation failure or ingestion error updates `orders_ledger` to `ledger_status = "INGESTION_FAILED"`, persists `ledger_error`, logs an audit event, and raises visibly.
  - Simulation Segregation: Paper fills are recorded under `SIMULATED_PAPER_ACCOUNT` with distinct prefixing (`SIM-TRADE-{order_id}`) to prevent contamination of live reconciliation.
- **Verification Suite:** [`tests/test_order_execution_boundary.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_order_execution_boundary.py) (8/8 passed).

---

### P0-2: Transactional Outbox Worker & Publication Failure Semantics
- **Root Cause:**
  - `AutoAlertEngine.record_alert()` staged outbox entries into SQLite but did not integrate an active worker processor.
  - Storage failures during outbox staging were caught without updating `publication_status` or preventing subsequent direct multi-channel dispatches, violating fail-closed publication semantics.
- **Architectural Fix:**
  - Created [`engine/outbox_worker.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/outbox_worker.py):
    - Implemented `OutboxWorker` featuring the complete `claim -> dispatch -> acknowledge/fail` lifecycle.
    - Lease-based concurrency: `claim_pending_outbox_entries()` atomically leases pending entries to a specific `worker_id` with a bounded lease TTL (`lease_expires_at`).
    - Duplicate Prevention: Non-claiming workers cannot acknowledge, mutate, or dispatch entries leased to another worker.
    - Transport Failure & Retry Budgeting: Transports record failures via `mark_outbox_failed()`; entries transition to `FAILED_RETRY` until `attempts >= max_attempts`, at which point they become terminal `FAILED`.
    - Lease Timeout Reclamation: `reclaim_expired_leases()` queries unacknowledged entries across `CLAIMED` and `DISPATCHED` states past their lease expiry and safely reclaims them for worker recovery.
  - Fail-Closed Publication Semantics: In [`engine/auto_alert_engine.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/auto_alert_engine.py):
    - If `save_alert_with_outbox()` fails, the engine logs an error, records `OUTBOX_STAGING_FAILED` in `alert.audit_trail`, sets `alert.publication_status = "FAILED_STAGING"`, clears `to_dispatch = None`, and returns `False` immediately, aborting all downstream broadcasts.
- **Verification Suite:** [`tests/test_outbox_worker_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_outbox_worker_lifecycle.py) (5/5 passed).

---

### P1-3: Current-Book vs Future-Exit Semantics & Zero Sizing Preservation
- **Root Cause:**
  - `calculate_net_executable_rr()` previously reused current market bid/ask quotes as the future target exit price whenever the market price ticked towards target, contaminating modeled target exits with current entry books.
  - Alert adapter fabricated arbitrary `0.8` / `1.3` multiples for options when explicit option stop-loss or option target were missing, or erroneously fell through to spot index target levels (e.g. ₹24,500 spot index target applied to a ₹150 option premium).
  - When position sizing returned `recommended_shares == 0`, `AutoAlertEngine` previously forced a 1-lot floor (`qty = ls`), overriding the quantitative risk gate.
  - Schema divergence: Metrics used `statutory_charges_total` while consumers expected `statutory_charges_rupees`.
- **Architectural Fix:**
  - In [`engine/executable_risk_reward.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/executable_risk_reward.py):
    - Completely separated `current_entry_book` (for calculating entry friction at current ask/bid) from `modeled_target_exit_book` (for modeling exit friction at future target levels).
    - Future target exits are modeled from `target_price - (target_price * slippage_mult)` (for longs) or `target_price + (target_price * slippage_mult)` (for shorts), or use explicit `modeled_target_bid` / `modeled_target_ask` when provided. Current book quotes are never reused as target exit prices.
    - Alert Adapter: Removed arbitrary `0.8` / `1.3` multipliers and removed spot `target_level` fallthrough for options. Requires canonical segment and returns `None` when option-specific target/stop levels are missing.
    - Schema Alignment: `MultiHorizonRRMetrics` exposes both `statutory_charges_total` and `statutory_charges_rupees` on the object and in `.to_dict()`.
  - In [`engine/auto_alert_engine.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/auto_alert_engine.py):
    - Respects position sizer decisions: when `recommended_shares == 0`, preserves `qty = 0` and sets `net_executable_rr = None`.
- **Verification Suite:** [`tests/test_executable_rr_boundary.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_executable_rr_boundary.py) (5/5 passed) & [`tests/test_executable_rr_semantics.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_executable_rr_semantics.py) (6/6 passed).

---

### P1-5: Consolidated Gate Authority & Coverage
- **Root Cause:**
  - Signal policy evaluation was split across ad-hoc detector checks, with test-mode bypasses (`and not is_sim`) allowing invalid setups to bypass policy gates in testing environments.
- **Architectural Fix:**
  - Consolidated single-authority decision hierarchy in [`engine/signal_policy.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/signal_policy.py):
    - Added typed `veto_code: Optional[str]` to `GateVerdict` across all gates (`PolicyVetoCode.ZERO_FUTURES_VETO`, `TIER1_MATH_SANITY_VETO`, `CIRCUIT_BREAKER_VETO`, `QUALITY_GATE_VETO`, `LEARNING_LOCKOUT`).
    - Removed test-mode bypass (`and not is_sim`) from Step 00 policy check in `AutoAlertEngine.record_alert()`.
- **Verification Suite:** [`tests/test_signal_policy_authority.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_signal_policy_authority.py) (5/5 passed).

---

## 2. Test Suite Validation Matrix

The complete 12 core test suites passed with 100% green results (74/74 passed in 30.16s):

| Suite | Focus Domain | Tests | Status |
| :--- | :--- | :---: | :---: |
| `tests/test_order_execution_boundary.py` | P0-1 & P1-4: Authentic broker execution ingestion, charges, fact conflicts, fee adjustments, concurrency | 8 | ✅ PASSED |
| `tests/test_outbox_worker_lifecycle.py` | P0-2: Fail-closed publication, worker lease/ack lifecycle, retry budgeting, lease expiry reclamation | 5 | ✅ PASSED |
| `tests/test_executable_rr_boundary.py` | P1-3: Current quote vs future exit separation, zero sizing preservation, schema alignment | 5 | ✅ PASSED |
| `tests/test_inventory_cost_basis.py` | Account ledger signed inventory, partial close/reopening cost basis, product/segment separation | 6 | ✅ PASSED |
| `tests/test_executable_rr_semantics.py` | Payoff coordinates, bought-put/sold-call coordinate isolation, friction & charges | 6 | ✅ PASSED |
| `tests/test_signal_policy_authority.py` | Single-authority gate hierarchy, typed reason codes, zero-futures invariant, shadow routing | 5 | ✅ PASSED |
| `tests/test_shadow_evaluator_and_lifecycle.py` | Shadow candidate evaluation, episode deduplication, suppressor ablation | 4 | ✅ PASSED |
| `tests/test_account_ledger_and_outbox.py` | Baseline establishment, fill accounting, outbox persistence | 2 | ✅ PASSED |
| `tests/test_transactional_outbox_sqlite.py` | ACID transactional outbox, worker lease concurrency, archival | 6 | ✅ PASSED |
| `tests/test_production_vertical_slice.py` | End-to-end vertical slice: detector -> policy -> executable R:R -> outbox -> ledger fill | 2 | ✅ PASSED |
| `tests/test_prefix_invariance_replay.py` | Causal replay, bar-close execution on next open, censoring | 3 | ✅ PASSED |
| `tests/test_verified_market_safety.py` | Behavioral release tests: SEBI holiday roll, STT boundaries, zero-DTE, rollback, Cas cash | 22 | ✅ PASSED |
| **Total** | | **74** | **✅ 100% PASS** |

In addition:
- `tests/test_order_lifecycle.py`: 27/27 passed.
- `tests/test_executable_risk_reward.py`: 5/5 passed.
- Code hygiene: `ruff check` on all touched files passed with zero errors.

---

## 3. Operational Invariants Verified
1. **TRADING_MODE=PAPER default maintained**: Zero live orders placed, zero live qualification flags (`LIVE_EXECUTION_QUALIFIED=0` strictly enforced).
2. **Zero fabricated execution facts**: Orders missing authentic trade IDs, prices, or account IDs never fabricate fills into SQLite or claim ledger parity.
3. **Fail-Closed Publication**: Any failure in transactional outbox staging stops multi-channel dispatch immediately and logs `OUTBOX_STAGING_FAILED`.
4. **Current Book / Future Exit Isolation**: Current book bid/ask is never reused as a target exit price when price moves towards target.
5. **Zero Sizing Preservation**: Position sizing rejections (`recommended_shares == 0`) remain 0 shares with `net_executable_rr = None`.
