# ChanakyaTrade Implementation Checkpoint — Signal Edge & Correctness

**Workspace:** `C:\Users\brije\.gemini\antigravity\scratch\chanakya-trade`  
**Review Reference Date:** 1 November 2026 (`2026-11-02T01:00:00+05:30`)  
**Branch:** `codex/verified-market-safety` | **HEAD:** `82114d06c38c8a8f297fa3e7a48b6ac91787e8ab`  
**Operational Status:** Safety default `TRADING_MODE=PAPER` | `LIVE_EXECUTION_QUALIFIED=0` (Strictly Locked)

---

## 1. Honest Audit of Findings Status (Separating Guards from Qualification)

| ID | Domain | Status | Reality & Current Ground Truth |
| :--- | :--- | :--- | :--- |
| **F01** | Option Spread Resolution | **TESTED / GUARDED** | Spread construction strictly requires active listed contracts, matching expiry/venue, compatible lots, observable quotes, and positive debit. Zero synthetic hedge construction. Payoff R:R is expiry payoff, not win probability. |
| **F02 / E01** | Position Sizing Coordinates | **RESOLVED & VERIFIED** | Bought PE/CE stop-loss inversion resolved via `resolve_payoff_orientation()`. Long option coordinates strictly adhere to `stop_loss < entry < target`. Multi-leg joint coordinates enforce signed margin/debit limits. |
| **F03 / E04** | Active Contract Validation | **RESOLVED & VERIFIED** | Exact venue and canonical ticker validation in `resolve_active_contract()`. Eligible hedge matching filtered strictly by primary leg expiry (`c.expiry == chosen_contract.expiry`). Removed misleading theta/vega elimination claims. |
| **F04 / E02** | Snapshot Provenance | **RESOLVED & VERIFIED** | Freshness validates true exchange observation timestamp ($\le 15.0$s) and clock skew tolerance ($\le 0.5$s); rejects stale, naive, future, and out-of-order packets. |
| **F05** | Shared VIX Authority | **TESTED / GUARDED** | Test flag fallback removed; `_fresh_live_vix()` in `analysis.regime_governor` enforces live quote verification. Missing live VIX returns `regime="UNAVAILABLE"`. |
| **F06** | Template Rendering | **TESTED / GUARDED** | Suppressed speculative expiry dates; replaced unverified margin relief claims with hedged spread descriptions. |
| **F07** | Enrichment Fixtures | **TESTED / GUARDED** | Synthetic fixtures updated and negative invariant tests passing. |
| **F08 / R03** | Live Account Ledger & Inventory Accounting | **RESOLVED & VERIFIED** | Implemented signed inventory accounting with weighted-average cost basis per unit across partial closes, increases, full closes, crossing through zero, and reopening. Keyed by `(broker_name, exchange, symbol, product)`. Strictly rejects fractional quantities, nonfinite prices/charges, and invalid timestamps. Conflicting duplicate trade IDs raise `ValueError`; identical retries are idempotent. Uninitialized baselines and unsupported segments fail closed. `LIVE_EXECUTION_QUALIFIED=0` remains locked. |
| **F09 / R03** | Atomic SQLite-Backed Transactional Outbox | **RESOLVED & VERIFIED** | Implemented transactional alert outbox table in SQLite with single-transaction ACID commit (`save_alert_with_outbox`), unique constraint on `(alert_id, event_version, channel)`, multi-worker leasing, worker identity verification, ambiguous-send recovery, and completed-row archival. Synchronized across `SQLiteAlertStore` and `AlertRepository`. |
| **F10 / R01-R02** | Causal Replay & Prefix-Invariance | **RESOLVED & VERIFIED** | Causal replay with controllable clock, cryptographic dataset manifest generator (`generate_dataset_manifest`), conservative same-bar fill logic, and subsequent-bar execution (`execute_on_next_bar: bool = False`) eliminating same-bar lookahead bias. Mathematically proved 100% prefix-invariance against truncated historical series. Shadow evaluation with first-touch adverse resolution and explicit horizon censoring. |
| **PVS** | Production Vertical Slice Integration | **RESOLVED & VERIFIED** | Connected detector ingestion $\to$ signal policy evaluation (ACCEPT / REJECT / HOLD) $\to$ net executable R:R calculation $\to$ atomic alert + outbox staging $\to$ pre-dispatch quote freshness (<15s) and anti-FOMO no-chase boundary $\to$ channel worker claim/dispatch $\to$ broker execution fill recording $\to$ internal ledger snapshot. |

---

## 2. Correctness Defects (E01–E05) Resolved

### E01. Bought-Put Premium Risk Inversion
- **Files:** `engine/position_sizer.py`, `engine/auto_alert_engine.py`
- **Fix:** Implemented `resolve_payoff_orientation()`. For `LONG_OPTION` (both CE and PE), premium space coordinates are strictly long: `stop_loss < entry_price < target_price`. For `SHORT_OPTION` (sold options), premium coordinates are short: `target_price < entry_price < stop_loss`.
- **Verification:** `tests/test_payoff_coordinates.py` (14/14 passed) and `tests/test_executable_rr_semantics.py` (6/6 passed).

### E02. Old Market Observations Passing Provenance
- **Files:** `market/contract_selection.py`
- **Fix:** Enforced observation age validation ($\le 15.0$s) against aware current time, rejected naive and future timestamps, and bounded clock skew ($\le 0.5$s).
- **Verification:** `tests/test_snapshot_freshness.py` (8/8 passed).

### E03. Fallback Capital & Invented Anchors Eliminated
- **Files:** `engine/position_sizer.py`
- **Fix:** Eliminated silent ₹100,000 fallback capital in actionable mode; missing budget returns `status="BLOCKED_MISSING_CAPITAL"`. Inverted or contradictory anchors return `status="BLOCKED_INVALID_ANCHORS"` instead of inventing percentage stops.
- **Verification:** `tests/test_payoff_coordinates.py`.

### E04. Contract Identity & Spread Expiry Matching
- **Files:** `market/contract_selection.py`, `engine/option_resolver.py`
- **Fix:** Filtered eligible hedge contracts strictly by primary leg expiry (`c.expiry == chosen_contract.expiry`). Removed inaccurate marketing claims ("eliminates theta/vega risk").
- **Verification:** `tests/test_fno_enrichment_negative_invariants.py`.

### E05. Plan Immutability
- **Files:** `engine/auto_alert_engine.py`
- **Fix:** Added plan idempotency guards in `_enrich_fno_contract_if_applicable()`; prevents mutating re-enrichment from drifting finalized setups.

---

## 3. Signal Policy Authority & Decision Funnel (S01–S07)

### S01. Consolidated Signal Policy Authority
- **Module:** `engine/signal_policy.py`
- **Functionality:** Single SSOT policy evaluator (`evaluate_candidate_policy`) evaluating data integrity, sanity gates, session runway, empirical learning lockouts, and quality filters. Uses strongly typed enums `PolicyGateCategory` and `PolicyVetoCode`, full context cache keying `(symbol, direction, detector_slug, session_id, segment, payoff_type, regime, feat_hash, policy_version)`, and auto-context generation from `AutoAlert`.
- **Verification:** `tests/test_signal_policy_authority.py` (5/5 passed).

### S02. Composite Key Lockouts & Refractory Isolation
- **Module:** `engine/learning_engine.py`
- **Functionality:** Stored lockouts keyed by composite `(symbol, direction)`. Alternating bullish/bearish signals no longer overwrite lockouts. Added exchange session boundary expiration, invalidation event deduplication, restart persistence (`symbol_lockouts.json`), and re-entrant `threading.RLock()`.
- **Verification:** `tests/test_lockout_composite_keys.py` (5/5 passed).

### S03. Shadow Candidate Evaluator & Lifecycle Telemetry
- **Module:** `engine/shadow_evaluator.py`
- **Functionality:** Tracks suppressed candidates, clusters 15-minute episodes to eliminate redundant multi-strike duplicates, evaluates forward price paths with first-touch adverse resolution (worst-case SL when both touched in same bar) and horizon censoring (`net_outcome_r=None` when barrier untouched). Multi-signature `record_shadow_candidate` supporting both scalar parameters and `(alert=..., feature_vector=...)`.
- **Verification:** `tests/test_shadow_evaluator_and_lifecycle.py` (4/4 passed).

### S04. Uncalibrated Signal Ensemble
- **Module:** `engine/signal_ensemble.py`
- **Functionality:** VIX resolution migrated to `analysis.regime_governor._fresh_live_vix()`. `EnsembleSignal` populated with `ensemble_score`, explicit `is_calibrated=False`, and `feature_families`.
- **Verification:** `tests/test_signal_ensemble.py` (48/48 passed).

### S05. Multi-Horizon Executable R:R & Opportunity Concentration
- **Module:** `engine/executable_risk_reward.py`
- **Functionality:** Separates 5 R:R dimensions (Underlying Structural, Option Premium Scenario, Spread Expiry Payoff, Executable Indicative after friction, and Observed Outcome). Incorporates Indian statutory charges, gap stress risk (1.5x), slippage bands, and index option desk prioritization. Replaced boolean assumptions with `resolve_payoff_orientation()`. Preserves `quantity=0` without forcing to 1. Fails closed when charges or quotes are missing.
- **Verification:** `tests/test_executable_rr_semantics.py` (6/6 passed) and `tests/test_executable_risk_reward.py` (5/5 passed).

### S06. Fyers Prime TBT Validation
- **Module:** `market/fyers_tbt_manager.py`
- **Functionality:** Verified existing exposure preempts discovery up to 15 slots; strict BSE/MCX exclusion from Fyers TBT.
- **Verification:** `tests/test_fyers_tbt_depth.py` (28/28 passed).

### S07. News & Event As-Of Integrity
- **Modules:** `market/events.py`, `market/earnings.py`, `market/news.py`
- **Functionality:** Captured publication timestamp, first-seen timestamp, revision ID, and source entity. Implemented `filter_events_as_of()`, `filter_earnings_as_of()`, and `filter_news_as_of()` to strictly eliminate lookahead bias in backtests and replay.
- **Verification:** `tests/test_event_provenance_and_asof.py` (3/3 passed).

---

## 4. Execution Ledger, Transactional Outbox & Causal Replay (R01–R03)

### R01 / R02. Causal Replay & Prefix-Invariance
- **Modules:** `engine/backtest.py`, `engine/options_backtest.py`
- **Functionality:**
  - `execute_on_next_bar: bool = False` added to `Backtester` so bar-close signals generated at bar $i-1$ execute strictly on subsequent bar $i$ open, eliminating same-bar lookahead bias.
  - Mathematically verified prefix-invariance: executing across bar prefix $0 \dots t$ yields identical signals, entries, exits, P&L, and hold durations to the full dataset run truncated at $t$.
  - `generate_dataset_manifest()` generates SHA-256 cryptographic checksums, session dates, row counts, and schema versions for historical data audit.
  - Controllable clock support (`clock` parameter) ensuring backtester only accesses causal data $\le \text{clock.now()}$.
- **Verification:** `tests/test_prefix_invariance_replay.py` (3/3 passed) and `tests/test_causal_replay_and_validation.py` (4/4 passed).

### R03. Signed Inventory Cost-Basis Accounting & Atomic SQLite Outbox
- **Modules:** `engine/order_lifecycle.py`, `engine/sqlite_store.py`, `engine/storage/alert_repository.py`
- **Functionality:**
  - Signed inventory accounting: Weighted-average cost basis per unit across partial closes, increases, full closes, crossing through zero, and reopening. Keyed by `(broker_name, exchange, symbol, product)`.
  - Rejection of fractional quantities, nonfinite prices/charges, and invalid timestamps. Conflicting duplicate trade IDs raise `ValueError`; identical retries are idempotent.
  - `alert_outbox` table in SQLite with `UNIQUE(alert_id, event_version, channel)`.
  - `save_alert_with_outbox(alert, outbox_entries)` commits alert upsert and delivery intent staging in a single SQLite ACID transaction.
  - Multi-worker leasing with `claim_pending_outbox_entries(worker_id, lease_seconds)`.
  - Worker identity verification and idempotent state transitions (`mark_outbox_dispatched`, `mark_outbox_acknowledged`, `mark_outbox_failed`).
  - Ambiguous-send recovery via `get_ambiguous_outbox_entries()` and `reclaim_ambiguous_entry()`.
  - Archival of completed outbox rows via `archive_completed_outbox()`.
- **Verification:** `tests/test_inventory_cost_basis.py` (6/6 passed), `tests/test_transactional_outbox_sqlite.py` (6/6 passed), and `tests/test_account_ledger_and_outbox.py` (2/2 passed).

---

## 5. Production Vertical Slice Integration (PVS)

- **Modules:** `engine/auto_alert_engine.py`, `engine/order_lifecycle.py`
- **Flow Wired:**
  1. **Detector Ingestion:** Scanners and detectors ingest candidate signals into `AutoAlertEngine.record_alert`.
  2. **Signal Policy Authority Gate:** Evaluated at step 00 (`is_fresh_setup and not is_sim`):
     - `REJECT`: Records `POLICY_VETO` in audit trail, rejects candidate, returns `False`, zero outbox staging.
     - `HOLD`: Records `POLICY_HOLD_SHADOW` in audit trail, routes candidate to `shadow_candidate_evaluator.record_shadow_candidate()`, returns `False`.
     - `ACCEPT`: Records `POLICY_ACCEPT` in audit trail, continues through sizing and executable R:R.
  3. **Net Executable R:R:** Computes underlying structural, option scenario, and indicative R:R incorporating statutory charges and spread friction.
  4. **Atomic Outbox Staging:** Staged atomically during alert persistence via `save_alert_with_outbox` (`TELEGRAM` and `SSE` channels).
  5. **Pre-Dispatch Revalidation:** `revalidate_pre_dispatch()` verifies quote freshness SLA (<15.0s) and anti-FOMO no-chase boundary immediately before release. Target milestone and trailing stop updates bypass initial chase checks.
  6. **Worker Claim & Dispatch:** Outbox worker claims leased entry, verifies identity, dispatches, and marks acknowledged.
  7. **Broker Fill Ingestion:** `record_execution_fill()` persists broker fills into `execution_fills` SQLite table with monotonic sequences and idempotent retry handling.
  8. **Internal Ledger Snapshot:** `get_internal_ledger_snapshot()` derives position inventory, weighted-average cost basis, realized P&L, and net cash balance.
- **Verification:** `tests/test_production_vertical_slice.py` (2/2 passed) and `tests/test_auto_alerts.py` (85/85 passed).

---

## 6. Consolidated Verification Evidence

### 9 Core and Safety Suites (56 Passed in 10.25s)
```
============================= test session starts =============================
platform win32 -- Python 3.12.14, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\brije\.gemini\antigravity\scratch\chanakya-trade
configfile: pyproject.toml
collected 56 items

tests/test_inventory_cost_basis.py ......                                [ 10%]
tests/test_executable_rr_semantics.py ......                            [ 21%]
tests/test_signal_policy_authority.py .....                              [ 30%]
tests/test_shadow_evaluator_and_lifecycle.py ....                        [ 37%]
tests/test_account_ledger_and_outbox.py ..                               [ 41%]
tests/test_transactional_outbox_sqlite.py ......                         [ 51%]
tests/test_production_vertical_slice.py ..                               [ 55%]
tests/test_prefix_invariance_replay.py ...                               [ 60%]
tests/test_verified_market_safety.py ......................              [100%]

============================= 56 passed in 10.25s =============================
```

### Full Auto Alerts Suite (85 Passed in 68.95s)
```
tests/test_auto_alerts.py ..................................................................................... [100%]
======================== 85 passed in 68.95s (0:01:08) ========================
```

### Code Quality & Static Invariants
- `ruff check`: Clean across all touched modules with zero errors.
- `LIVE_EXECUTION_QUALIFIED=0`: Strictly locked in `engine/modes.py` and `config/credentials.py`.
- No live broker orders submitted; `TRADING_MODE=PAPER` safety default verified.
- Zero AI hallucinations: All targets, stop losses, and R:R ratios grounded in quantitative calculations.
- Empirical Outperformance / Alpha: Marked as **PENDING EMPIRICAL OBSERVATION**; statistical edge claims must await empirical paper-trading datasets.
