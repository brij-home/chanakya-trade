# Antigravity repair prompt — 2 November 2026 release acceptance

Read AGENTS.md, SAFETY_CONTRACTS.md and the preceding integration acceptance prompt. Preserve verified fixes. Implement the repairs below with real-boundary regressions before strategy tuning or deployment. No live orders, live qualification flag, test Telegram sends, production-history mutation or push. Use isolated app-data and controlled external sources in tests.

## Independent verification

74 tests passed in two disjoint runs: 66 across payoff, snapshot freshness, executable-R:R semantics, SQLite outbox, account ledger, policy, replay and verified safety; another 8 across production vertical slice and inventory cost basis. These results cover selected behavior, not the full current tree. Production call sites now exist for policy, shadow, R:R, fill recording and outbox staging. Integration has progressed, but the following code-confirmed failures remain.

## P0-1. Remove fabricated execution evidence and fix broken fill ingestion

In engine/order_lifecycle.py, live COMPLETE response handling constructs:

- account_id from `d.get('account_id') or 'LIVE_ACCOUNT'`;
- broker_trade_id from broker trade_id or `TRD-{broker_order_id}`;
- fill price from average_price or the preview/order price;
- filled quantity from intent quantity rather than independent execution records.

These fallbacks cannot enter a verified execution ledger. An order completion message is not an individual broker execution record. Retrieve account-bound executions with authentic trade IDs, actual filled quantities, execution prices/timestamps and source watermark. Partial fills and subsequent polling/reconnect must use the same idempotent ingestion authority. Missing facts remain explicitly incomplete/unavailable. Never infer filled facts from preview values. Paper fills must carry simulation provenance and remain segregated from real account reconciliation/calibration.

The new paper/live fill-recording calls pass `exchange` and `product` to calculate_transaction_charges and read `.total`. The actual engine.charges function accepts `price, quantity, segment, side, ...` and returns `.total_charges`. As written, these calls fail before writing fills and are caught as non-fatal debug messages. Fix the real callers and propagate ingestion failure into visible reconciliation/data-quality status; do not claim ledger parity after a swallowed error.

Acceptance: real execute_order_intent path with controlled broker order response AND separate execution source; missing average/trade ID/account never fabricates a fill; two partial fills; identical/conflicting retries; actual quantity different from requested; charges failure; paper isolation; subsequent reconciliation poll. Assert persisted execution rows, not merely FILLED order status. Existing direct writer tests do not cover this boundary.

## P0-2. Complete outbox worker integration and enforce publication failure semantics

AutoAlertEngine catches save_alert_with_outbox errors, logs a warning, then continues saving and dispatching. This bypasses durable publication on storage failure. Make publication failure an explicit pending/failed authoritative state with zero uncontrolled channel sends. Preserve the candidate/evidence for recovery without falsely recording successful staging.

Production searches currently find claim/ack/reclaim calls only in SQLite methods and AlertOutbox wrapper definitions. The direct _dispatch path still publishes channels. A wrapper plus unit lease tests is not a running worker. Implement the application-managed worker lifecycle and route intended durable channel delivery through its actual claims. Remove shadow direct sends for the same event. Define SSE projection/replay behavior separately. Ensure one stable event/version/channel key and one persisted source of dispatch truth.

Acceptance invokes actual ingestion and a worker with stub transport: commit→claim→send→ack, storage failure, worker crash before/after send, ambiguous timeout, lease expiry, restart, duplicate workers and lifecycle update version. Do not manually call store transition methods as a substitute for worker integration. Report Telegram API acknowledgment separately from human receipt. Keep live transport disabled in tests.

## P1-3. Finish current-book versus future-exit semantics

engine/executable_risk_reward.py still reuses the current bid as the future target-exit bid whenever bid exceeds historical/planned entry; short-side ask has the analogous issue. Separate fields/types for current_entry_book and modeled_target_exit_book. Snapshot quotes can validate today's entry/tradability; they cannot represent a future target quote based on a numeric comparison. Add a moved-price case: planned long entry 150, current bid 151/ask 152, target 240; current bid must not replace target-exit scenario.

The alert adapter still invents missing option stops/targets with 0.8/1.3 multiples and can fall through to underlying target_level. Remove these fallbacks from actionable R:R and preserve missing evidence. Its default segment OPTIONS prevents `segment or alert.segment` from resolving cash correctly; require canonical explicit instrument segment.

AutoAlertEngine restores a one-lot quantity for R:R when recommended_shares is zero, using bare-underlying get_lot_size first. This violates zero-size semantics and can attach executable-looking metrics to an unallocated trade. Preserve zero executable size; if a one-lot research scenario is useful, expose it under separate research fields with explicit capital assumptions. Current metrics access statutory_charges_rupees while the result defines statutory_charges_total, yielding a false default zero; fix schema and add contract tests. Never describe unavailable fees as zero.

## P1-4. Complete ledger transaction and evidence scope

record_execution_fill still uses _get_orders_db(), which acquires a pooled connection without BEGIN IMMEDIATE, for duplicate check/MAX(sequence)+1/insert. Use the explicit writer transaction with uniqueness constraints and concurrency tests. Duplicate comparison must include broker, venue, segment, product, execution timestamp and defined fee-adjustment semantics; do not accept changed immutable fields because symbol/side/price match.

Validate aware execution time and authentic account identity. Preserve signed weighted-average accounting fixes. Verify baseline scope/watermark, ingestion completeness, opening inventory and broker-specific cash/margin/MTM semantics; unsupported segments return unavailable. Baseline plus no local executions cannot establish a reconciled flat account. Ledger fill IDs and dedup keys must not collide across broker/account scopes. Keep live qualification disabled.

## P1-5. Gate ownership and coverage

The unified policy is called early, but later ingestion retains other future/data/scrutiny/quality gates. Map each invariant and its sole decision authority; consolidate without weakening safety or dropping exit coverage. Classify gate categories with typed reason codes rather than rejection-text substrings. Exercise HOLD/shadow through real ingestion and positive eligible controls with no production test-mode bypass.

Expand end-to-end tests to expose the failures above: tests that directly exercise new helpers while existing production caller errors are swallowed must not establish “integrated.” Keep implementation/testing/deployment/empirical qualification statuses separate in the checkpoint. Delete no tests to obtain green results.

## Completion and next stage

Run affected integration suites and verified-market-safety first, Ruff and git diff --check, then full backend suite and affected frontend checks. Record exact commands/results and outstanding failure classes. Do not repeat overlapping totals as independent coverage.

Once these pass, qualify a controlled PAPER/shadow deployment with installed broker transport checks, code provenance, feed freshness, recovery and rollback. Collect candidate/suppression/latency/attainable-entry evidence. Use chronological replay, untouched holdout and filter ablation to measure missed moves, false signals, churn, net expectancy and drawdown. No new detectors or RSI/lockout tuning before that baseline. Unit-test counts cannot establish statistical edge.

Deliver a compact release report linking each blocker to source, RCA, real-boundary test, result and remaining external acceptance requirement. Do not enable live execution or certify all gaps closed.
