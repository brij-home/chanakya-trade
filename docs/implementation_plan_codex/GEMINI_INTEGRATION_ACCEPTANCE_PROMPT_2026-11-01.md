# Next Antigravity task: integrate and qualify the signal-edge foundation

## Objective and current evidence

Complete the existing implementation through real production boundaries before adding strategy features. Read AGENTS.md, SAFETY_CONTRACTS.md, FNO_DESK_ROADMAP.md and the two prior Gemini prompts. Preserve valid fixes and existing user edits. No live orders, live qualification flag, Telegram test sends, push or production-history mutation. Continue reversible local implementation without repeated permission requests.

Independent review on 1 November 2026: 51 tests passed across payoff coordinates, snapshot freshness, policy authority, ledger/outbox and verified market safety. The earlier bought-put and stale-observation defects now have regression coverage. This does not qualify the full current tree or its runtime.

Production-call search found `evaluate_candidate_policy`, shadow evaluator and executable-R:R helpers only in their own implementation files; the outbox is imported by the alert engine but its staging/dispatch methods are not called there. `record_execution_fill` has no production caller. Verify the current tree again before editing. Existing module unit tests cannot establish production integration.

## 1. Fix the new foundations before connecting them

### A. Fill accounting is wrong for partial closes and reopening

Location: engine/order_lifecycle.py, get_internal_ledger_snapshot(). Current average cost subtracts sale proceeds from acquisition cost, then divides by remaining quantity. Example: buy 100 at 100, sell 50 at 120; remaining cost basis should remain 100 per unit under weighted-average accounting, but current math gives 80. Full close followed by reopening also carries old realized gains into the new cost basis.

Implement a signed inventory accounting method with explicit weighted-average/FIFO policy, separate realized P&L, fees and cash flows. Test long and short partial close, increase, full close, crossing through zero and reopening. Key positions by account, broker, exchange, exact contract and product, not bare symbol. Futures MTM/margin accounting cannot be modeled as full-notional equity cash movement. Keep unsupported segments explicitly unavailable.

Fill writer issues to address: MAX(sequence)+1 is read before insert without an explicit serialized writer transaction; fractional quantity is truncated; nonfinite prices/fees and invalid timestamps need rejection. A duplicate broker execution retry should be idempotent only when its immutable facts match; a conflicting retry must fail visibly. Require authenticated account/broker source and provenance, verified ingestion completeness and explicit baseline scope/watermark. A baseline plus zero locally imported fills is not proof that the broker account is flat. Preserve live qualification blocks and UNKNOWN_FREEZE recovery work.

Acceptance: concurrent writers, rollback, identical/conflicting replay, out-of-order arrival, late fee correction as an append-only adjustment, account/venue separation, beginning-of-baseline fills and incomplete import. Reconciliation must fail unavailable/incomplete when independent evidence is missing.

### B. Outbox is a JSON state helper, not a transactional publication system

Location: engine/storage/alert_repository.py, AlertOutbox. Alert state and outbox are separate files, so saving them is not one transaction. stage_alert overwrites an existing acknowledged item and resets attempts. Persistence errors are logged but not propagated; callers can report staging success after failed storage. DISPATCHED entries are excluded from pending recovery. Each instance has only a local lock; no multi-process claim authority exists. Dispatched+failed can count attempts twice.

Implement durable atomic alert-version/event plus delivery-intent publication, using the established storage domain with explicit schema migration where necessary. Stable keys must distinguish lifecycle event/version and channel while remaining idempotent on identical retries. Use transactional claims/leases and explicit ambiguous-send recovery. Reject illegal transitions; enforce one attempt count per actual send attempt. Never infer human receipt from Telegram API acknowledgment. Define SSE replay semantics separately from persistent notifications. Propagate persistence failure to the authoritative caller.

Acceptance: crash before/after alert commit, before/after send, provider timeout, lease expiry, duplicate stage, same event retry, distinct lifecycle update, multi-worker contention and storage failure. Preserve evidence on corrupt storage; never silently reset to an empty outbox and overwrite pending records. Bound retention through auditable archival.

### C. Net executable R:R introduces incorrect payoff and price semantics

Location: engine/executable_risk_reward.py. It uses underlying BULLISH/BEARISH to choose BUY/SELL premium arithmetic, repeating the bought-put error fixed in position_sizer. It may use today's bid as the future target exit quote. Absolute price differences can turn a losing path into positive reward. Missing underlying coordinates fall back to option premium while being labeled underlying structural R. Charge errors use a fabricated fixed 40; quantity is forced to at least one; gap stress is a fixed multiplier.

Reuse the shared payoff orientation and validated plan. Reject bad anchors/nonfinite quantities. Keep missing dimensions null. Price current entry with the correct side of the current book; future exit bid/ask must be an explicitly modeled scenario with stated spread/slippage assumptions, never a reused current quote. Separate target-exit and stop-exit fee calculations. Costs unavailable means net R unavailable. Preserve zero quantity. Scenario stress is labeled as a scenario; choose stress assumptions with evidence and report sensitivity.

Acceptance: bought CE and PE equivalent in premium coordinates; sold options require their policy; profitable and losing target paths; zero lot; unavailable fee calculator; no underlying evidence; spread joint payoff; current book distinct from future scenario.

### D. Policy and shadow semantics need boundary corrections

signal_policy.py currently classifies gate categories by strings in rejection text, skips some production checks based on TEST/is_live metadata, and derives payoff_type from a function returning LONG/SHORT rather than a full payoff enum. It wraps existing gates without yet retiring duplicate production authorities. Cache keys omit some context fields advertised in the module comment.

Use typed reason/category enums and validated instrument/payoff context. Execution simulation must not bypass evidence validation for real-market actionable alerts. Missing source cannot become ACCEPT because is_live=False. Explicit isolated demo fixtures remain separate. Include all decision dependencies in cache identity with stable canonical serialization. Preserve independent coverage for production missing-data paths.

shadow_evaluator.py uses underlying direction for forward premium outcomes and has no explicit trigger attainment, per-observation as-of or censoring contract. Neither barrier hit becomes zero R rather than an observed horizon exit or censored record. Fifteen-minute bucketing can merge separate setups and split one continuing episode. Empty telemetry reports 100% on-time; reversed timestamps can appear as zero latency/on time.

Reuse payoff-aware outcome logic and causal trigger semantics. Do not call a price path account P&L. Require a specified horizon and qualified data; missing/unfinished paths are censored, not flat. Distinguish first-touch ambiguity. Make episode grouping auditable with stability tests. Invalid latency ordering is unavailable/error, never a zero-success sample; no samples gives null rates. Bound and persist evidence appropriately.

## 2. Wire one actual production vertical slice

After the above contracts pass, trace a deterministic real candidate from detector/registry through existing AutoAlertEngine ingestion, canonical evidence/plan, policy, sizing/R:R, authoritative persistence, shadow-or-action decision, delivery intent and read-only UI/Telegram projections. Use the existing authority; do not create a second alert engine.

Evaluate policy once per decision/evidence version and retire duplicated gate calls in the same change. Cheap session/discovery/dedup checks precede expensive broker/LLM work. All rejected/held candidates receive typed audit reasons. Empirical suppressions can enter shadow only after safety evidence passes. Timing is recorded at actual events, including queue delay, not invented by subtracting test values.

No direct detector, CLI, API or scheduled path may bypass the policy. Valid lifecycle/exit updates retain their exposure priority. Revalidate price/no-chase/freshness immediately before actionable dispatch. Update templates and tickets from the same finalized plan/status; no local fallback arithmetic.

Connect fill ingestion only from independently verified broker executions or a clearly isolated test/paper source. Persist source cursor/watermark and recovery state. Do not label an API writer or manually supplied broker_trade_id verified merely because the fields exist.

## 3. Prove integration with actual-boundary tests

Add tests invoking real ingestion with controlled source providers and clock. Stub only the external boundary, not the newly introduced policy/outbox/ledger helpers. Assert records created in the authoritative stores and consumed by actual dispatch projections. Negative controls: stale observation, missing capital, bought PE, missing hedge, beyond-no-chase, empirical suppression, storage failure and restart with a pending/ambiguous delivery. Positive controls must prove qualified candidates remain reachable.

Run relevant existing suites plus tests/test_verified_market_safety.py using `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`. After affected tests pass, run the full backend suite; frontend tests/build when payloads change; Ruff and git diff --check. Keep production app-data and network mutations isolated.

## 4. Qualify replay before claiming edge

The new backtest clock currently filters the input frame at a reference timestamp; that is not proof that each indicator, news join, contract lookup and decision uses only evidence available at each simulated event. A conservative fill formula does not establish order timing. Bar-close decisions cannot receive an earlier intrabar entry. Use production policy replay with clock advancement and prefix-invariance controls. Preserve unknown same-bar ordering as adverse/interval outcomes and model only executable post-decision prices.

Generate dataset/policy/source manifests, chronological development/validation/untouched holdout splits and a complete tested-variant ledger. Compare current filters against simple causal baselines and each filter removed, with realistic costs/latency and trading-session uncertainty estimates. Keep missed-move recall, false signals, churn, drawdown, net expectancy and entry timeliness visible together. No empirical promotion from unit-test counts or a chosen winning backtest.

## 5. Controlled shadow acceptance and accurate completion status

After software integration/recovery qualification, document a scoped PAPER/shadow deployment and rollback plan. Check installed broker profile, process/code provenance, feed coverage and data quality first. Collect real candidate decisions, suppression reasons, timing and attainable entry observations without test Telegram sends or broker mutations. Decide required independent-session coverage from the intended effect size and market-regime coverage; do not promise that a fixed small number of sessions proves alpha.

Update SIGNAL_EDGE_CHECKPOINT_2026-11-01.md with separate states: implemented, unit-tested, integrated, recovery-tested, deployed, empirically-qualified. For each package include real caller links, exact validation output and unresolved constraints. Live execution remains unqualified until account/recovery/protection and owner/broker acceptance are complete.

Begin with the cost-basis and executable-R:R correctness tests, then the atomic outbox foundation, then one end-to-end signal vertical slice. Do not add more detectors or tune RSI/lockout thresholds during this work.
