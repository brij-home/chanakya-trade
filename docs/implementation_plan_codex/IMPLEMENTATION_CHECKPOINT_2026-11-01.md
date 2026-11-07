# ChanakyaTrade Implementation Checkpoint — 1 November 2026

**Workspace:** `C:\Users\brije\.gemini\antigravity\scratch\chanakya-trade`  
**Execution Date:** 1 November 2026 (`2026-11-01T21:00:00+05:30`)  
**Branch:** `codex/verified-market-safety`  
**HEAD:** `82114d06c38c8a8f297fa3e7a48b6ac91787e8ab`  
**Operational Status:** Paper/Simulate default (`TRADING_MODE=PAPER`); `LIVE_EXECUTION_QUALIFIED=0` (Strictly Disabled). No real orders, no Telegram pushes, no `.env` mutations.

---

## 1. Inventory & Baseline Verification

### 1.1 Git Inventory & Diff Statistics
- **Tracked modified files:** 168 files (including conftest and test suites).
- **Untracked files:**
  - `.github/workflows/verified-market-safety.yml`
  - `config/discovery_policy.py`
  - `docs/FNO_DESK_ROADMAP.md`
  - `docs/SAFETY_CONTRACTS.md`
  - `docs/implementation_plan_codex/`
  - `engine/alert_outcomes.py`
  - `engine/llm_deadline.py`
  - `market/contract_selection.py`
  - `market/rule_schedule.py`
  - `scripts/audit_alert_evidence.py`
  - `tests/test_alert_outcomes.py`
  - `tests/test_discovery_policy.py`
  - `tests/test_fno_enrichment_negative_invariants.py`
  - `tests/test_fyers_depth_integrity.py`
  - `tests/test_listed_contract_selection.py`
  - `tests/test_llm_deadline.py`
  - `tests/test_options_iv_provenance.py`
  - `tests/test_quantity_freeze_master.py`
  - `tests/test_regime_reachability.py`
  - `tests/test_verified_market_safety.py`

---

## 2. Architectural Findings Resolution (F01–F10)

| Finding | Severity | Status | Root Cause & Implementation Summary |
| :--- | :--- | :--- | :--- |
| **F01: Spread resolution strict evidence contract** | P0 | **RESOLVED & VERIFIED** | **RCA:** Spread resolution fabricated synthetic hedge legs (`opt_ltp * 0.42`) and rewritten debits when legs were missing or expensive. **Fix:** Spreads in actionable mode (`require_listed_contract=True`) require both legs to be exact active listed contracts from canonical master, identical underlying/venue/expiry, compatible lot sizes, positive strike width, observable bid/ask quotes, and non-crossed book. Indicative debit is strictly calculated as `buy_ask - sell_bid`. Missing or unviable legs return `None` (unavailable). Zero manufactured spreads. |
| **F02: Position sizing coordinates & capital controls** | P0 | **RESOLVED & VERIFIED** | **RCA:** Sizing preceded contract enrichment, resulting in spot units being applied to option premium tickets, while stops above entry were treated as invalid long-style stops. **Fix:** Evaluates enrichment before sizing; resolves immutable instrument/contract evidence first; separates cash equity sizing (shares) from derivative options (lots); calculates direction-aware stop distances (`stop_loss - entry_price` for shorts); requires margin evidence for short options; blocks unallocated or non-positive capital with `BLOCKED_MISSING_CAPITAL` and unbounded short risk with `BLOCKED_UNBOUNDED_RISK`. |
| **F03: Active contract resolution authority** | P0 | **RESOLVED & VERIFIED** | **RCA:** Raw master row lookups were treated as valid tradable contracts without verifying integer lot size, tick size, active trading status, or listed expiry. **Fix:** Created `resolve_active_contract()` in `market/contract_selection.py` enforcing canonical active contract criteria: positive integer `minLotSize`, positive `tickSize`, valid `fyToken`, `tradeStatus == 1`, unexpired `expiryDate`, and exact underlying symbol match. Centralized lot size lookup in `engine/position_sizer.py::get_lot_size` routes through this authority. |
| **F04: Options snapshot provenance validation** | P0/P1 | **RESOLVED & VERIFIED** | **RCA:** Naive timestamps were parsed without timezone awareness, and provider checks relied on partial denylists, allowing off-market or synthetic chains into actionable paths. **Fix:** Implemented `validate_options_snapshot_provenance()` in `market/contract_selection.py`. Validates timezone-aware timestamps, bounds snapshot age ($\le 15.0$ seconds), requires `data_state == "LIVE"`, and enforces provider capability checks that exclude simulated/mock providers (`MOCK`, `TEST`, `PAPER`, `SIMULATE`). Distinguishes acquisition timestamp from observation timestamp. |
| **F05: Shared verified VIX authority & elimination of 13.5 substitution** | P1 | **RESOLVED & VERIFIED** | **RCA:** `analysis/regime_governor.py` contained an inline test bypass (`elif vix_val is None and is_test_env: vix_val = 13.5`) that masked missing-data behavior during test execution. **Fix:** Removed the synthetic 13.5 fallback completely. Missing volatility quotes now strictly return `regime="UNAVAILABLE"`, `data_status="UNAVAILABLE"`, and `unavailable_reasons=["FRESH_LIVE_INDIA_VIX_MISSING"]`. `option_resolver` routes VIX resolution through `_fresh_live_vix()`. Test suites supply explicit test VIX fixtures via `tests/conftest.py::_supply_test_vix_fixture` while preserving raw production missing-data handling in negative/regime suites. |
| **F06: Alert template rendering integrity** | P1 | **RESOLVED & VERIFIED** | **RCA:** Speculative expiry date inference when contract and expiry were absent; unverified claims of "70% margin relief" and "zero theta bleed". **Fix:** In `bot/alert_templates.py`, suppressed speculative calendar inferences when `contract` and `expiry_date` are absent (`dt = None`, badge `"📅 Expiry Unavailable"`). Replaced unverified margin claims with `[Hedged Spread · Defined Risk Payoff]`. Renders actionable quantities and expiries only from validated plans. |
| **F07: Interrupted enrichment patch & negative invariants** | P1 | **RESOLVED & VERIFIED** | **RCA:** 4 tests failed because the stricter production path required a live broker snapshot that synthetic test fixtures did not provide. **Fix:** Updated test fixtures in `test_alert_identity_invariants.py`, `test_detector_alignment_enrichment.py`, `test_fno_spot_leakage_invariants.py`, and `test_multi_asset_signals.py` with valid broker snapshot sources and active contract rows. Created `tests/test_fno_enrichment_negative_invariants.py` with 7 comprehensive negative tests (rejecting estimated pricing, stale snapshot >15s, off-market snapshot, mock provider, unlisted master row, missing hedge leg, crossed book). |
| **F08: Order lifecycle fail-closed boundaries & live qualification locks** | P0 | **RESOLVED & VERIFIED** | **RCA:** Live platform order execution requires strict fail-closed boundaries, immutable state transitions, and owner qualification. **Fix:** Verified `assert_live_execution_allowed()` is called atomically before any transition to `SUBMITTING` in `engine/order_lifecycle.py`. Unconfirmed previews and modified fields cannot transition to `SUBMITTING`. Paper broker exceptions yield `REJECTED` with original error as `rejection_reason`. Ambiguous live broker responses yield `UNKNOWN_FREEZE` with `broker_order_id=None`. Live basket placement, slice routing, and automatic protective GTT remain blocked pending durable tracking. `LIVE_EXECUTION_QUALIFIED=0` is strictly enforced. |
| **F09: Discovery scope, subscription managers & worker lifecycle** | P1 | **RESOLVED & VERIFIED** | **RCA:** Unbounded subscriptions, out-of-scope ticker pollution, and lingering worker threads. **Fix:** `market/ws_subscription_manager.py` maintains LRU capacity management (max 5,000 symbols); `CORE_BASE_SYMBOLS` prioritizes benchmark indices, commodities, and liquid equities; `cleanse_expired_derivatives()` purges expired options and futures; `get_diagnostics()` exposes `retained_out_of_scope_symbols` under `FNO_ONLY` discovery policy; worker threads in `market/fyers_tbt_manager.py` are joined cleanly during shutdown. |
| **F10: Statistical edge & learning engine outcome boundaries** | P2 | **RESOLVED & VERIFIED** | **RCA:** Forward price trajectories could be conflated with realized broker execution in learning weights. **Fix:** `engine/alert_outcomes.py::calculate_terminal_forward_outcome` strictly uses immutable `entry_price` and `initial_stop_loss`; untriggered alerts have no trade outcome; partial scale milestones are not calibrated as full exits; wrong-side initial stops are rejected; `engine/learning_engine.py` enforces two-strike session lockouts with adaptive reclaim levels, preserving causal boundaries between research price paths and account P&L. |

---

## 3. Test Verification Matrix

### Core Safety, Invariants & F&O Desk Suites (358+ Tests)
| Test Suite | Tests Passed | Pass Rate | Key Invariant Verified |
| :--- | :--- | :--- | :--- |
| `tests/test_verified_market_safety.py` | 22 / 22 | 100% | SEBI Tuesday/Thursday index expiries, STT changes, live execution gate locks, fail-closed unknown states |
| `tests/test_fno_enrichment_negative_invariants.py` | 7 / 7 | 100% | Rejection of estimated pricing, stale quotes (>15s), mock providers, unlisted contracts, crossed book |
| `tests/test_alert_identity_invariants.py` | 11 / 11 | 100% | Deterministic alert ID generation, symbol canonicalization, zero UUID/volatile timestamps |
| `tests/test_detector_alignment_enrichment.py` | 5 / 5 | 100% | Universal F&O contract enrichment, options chain integration, strike/expiry validation |
| `tests/test_fno_spot_leakage_invariants.py` | 3 / 3 | 100% | Zero spot-level leakage into option space, ticket coordinate isolation |
| `tests/test_multi_asset_signals.py` | 7 / 7 | 100% | Multi-asset signal generation, option enrichment signatures |
| `tests/test_position_sizer.py` | 11 / 11 | 100% | F&O lot quantization, directional stops, capital validation, short margin gate |
| `tests/test_listed_contract_selection.py` | 21 / 21 | 100% | Active listed contract resolution, expiry cycle validation, lot/tick size integrity |
| `tests/test_regime_governor.py` | 10 / 10 | 100% | Deterministic market regime classification, shared VIX authority, missing-data rejection |
| `tests/test_regime_reachability.py` | 6 / 6 | 100% | Regime reachability, direction neutrality, candidate governor exceptions |
| `tests/test_modes.py` | 6 / 6 | 100% | Mode banner truthfulness (`OBSERVE` / `SIMULATE` / `EXECUTE`), strict live qualification lock |
| `tests/test_alert_templates.py` | 61 / 61 | 100% | Alert template rendering, absence of speculative expiry inference, honest hedged spread descriptions |
| `tests/test_order_lifecycle.py` | 27 / 27 | 100% | Idempotency deduplication, statutory Indian charges, paper prefixing, transition validation |
| `tests/test_live_oms_p3b.py` | 43 / 43 | 100% | Kill switch system, pre-trade risk validation, OMS state machine, fail-closed boundaries |
| `tests/test_portfolio_journal_reconciliation.py` | 3 / 3 | 100% | Independent portfolio journal reconciliation, fill tracking |
| `tests/test_reconciliation.py` | 3 / 3 | 100% | Broker vs internal reconciliation honesty |
| `tests/test_reconciliation_typed.py` | 10 / 10 | 100% | Typed reconciliation models, discrepancy detection |
| `tests/test_reconciliation_unavailable.py` | 4 / 4 | 100% | Honest `UNAVAILABLE` status when independent ledger or broker baseline is missing |
| `tests/test_ws_subscription_manager.py` | 7 / 7 | 100% | WS subscription LRU capacity, expired contract cleansing, diagnostic scope reporting |
| `tests/test_alert_outcomes.py` | 9 / 9 | 100% | Causal forward outcomes, immutable entry/stop, option seller decay payoffs |
| `tests/test_learning_engine.py` | 6 / 6 | 100% | Two-strike session lockout, pattern memory persistence, reclaim levels |
| `tests/test_signal_quality_and_learning_enhancements.py` | 4 / 4 | 100% | Climax exhaustion filter (RSI > 78 / < 22), session lockouts |
| `tests/test_alert_scrutiny.py` | 31 / 31 | 100% | Two-tier AI sanity & scrutiny funnel, deterministic quantitative fallback |
| `tests/test_alert_dedup_and_dispatch_hygiene.py` | 7 / 7 | 100% | Alert deduplication, dispatch hygiene, zero shadow alerts |
| `tests/test_alert_channel_parity.py` | 4 / 4 | 100% | Telegram / UI channel parity, delivery status transparency |
| `tests/test_alert_session_rca_invariants.py` | 20 / 20 | 100% | Session RCA invariants, 14:00 intraday cutoffs, time window enforcement |
| `tests/test_alert_preferences.py` | 10 / 10 | 100% | Alert preference management and filtering |
| `tests/test_fyers_tbt_depth.py` | 28 / 28 | 100% | 50-level depth manager, OBI-50 calculation, iceberg wall veto, slippage modeling |
| **Total Verified** | **386+ Passed / 0 Failed** | **100%** | **All tested core domains passing cleanly** |

---

## 4. Operational Guardrails & Acceptance Checklist

1. **Safety Contract Invariant:**
   - `TRADING_MODE=PAPER` remains the safety default across all execution environments.
   - `LIVE_EXECUTION_QUALIFIED=0` is strictly enforced. It MUST NOT be enabled until the owner completes documented account-ledger, unknown-attempt recovery, and broker acceptance criteria.
2. **Credential & Secret Protection:**
   - Zero hardcoded API keys, TOTP secrets, or session contents.
   - `.env` is uncommitted and protected via `.gitignore`.
3. **Fail-Closed Execution:**
   - Any ambiguous broker response yields `UNKNOWN_FREEZE` with `broker_order_id=None`.
   - Paper broker exceptions yield `REJECTED` with the original error in `rejection_reason`.
4. **Single Source of Truth:**
   - Active contract validation: `market.contract_selection.resolve_active_contract()`.
   - Snapshot provenance: `market.contract_selection.validate_options_snapshot_provenance()`.
   - Verified volatility: `analysis.regime_governor._fresh_live_vix()`.
