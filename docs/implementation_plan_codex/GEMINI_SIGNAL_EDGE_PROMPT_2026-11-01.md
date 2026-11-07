# Antigravity / Gemini 3.8 Flash High: signal integrity, timeliness and demonstrated edge

## Mission and authorization

Implement this plan in the existing ChanakyaTrade workspace. Prioritize NSE/BSE index options, then stock F&O during active derivative sessions. Deliver fewer redundant alerts, timely evidence-backed opportunities, realistic net risk/reward, and measurable improvements in false signals, missed moves and churn. No guarantee of predicting big moves or outperforming competitors is justified by this prompt.

Review date: 1 November 2026. Workspace: `C:\Users\brije\.gemini\antigravity\scratch\chanakya-trade`. Read `AGENTS.md`, `docs/SAFETY_CONTRACTS.md`, `docs/FNO_DESK_ROADMAP.md`, the relevant alert/backtesting/broker runbooks and both implementation checkpoint documents before each dependent phase. Preserve existing edits and completed valid fixes. Prefer reuse of established modules over adding competing authorities.

Authorized: reversible local fixes, focused regression tests, deterministic replay, documentation, read-only diagnostics and shadow evaluation. Never expose secrets, submit live orders, enable `LIVE_EXECUTION_QUALIFIED`, push code or send Telegram test messages. Do not repair historical production records on startup. Do not restart the daily service while the release candidate is unqualified. Continue independent authorized phases without repeated permission requests. If external evidence is unavailable, build and validate the pipeline but report the empirical acceptance item as pending.

## Current evidence: do not inherit completion claims blindly

The previous implementation made useful changes: active-contract and snapshot-validation services, strict spread quote handling, explicit research labels, enrichment before sizing, negative enrichment tests, and removal of the production regime test fallback. Preserve these directions, subject to the defects below.

The checkpoint `IMPLEMENTATION_CHECKPOINT_2026-11-01.md` labels F01–F10 resolved. Those labels overstate completion. For example, `engine/order_lifecycle.py::get_internal_ledger_snapshot()` still explicitly returns `None` because account-scoped broker fills are not persisted. Retaining live qualification restrictions does not implement the account ledger, unknown-attempt recovery or fill-driven protection. Discovery diagnostics do not establish a durable alert outbox. Outcome-provenance safeguards do not establish statistical alpha.

Independent review run: 54 passed across `test_verified_market_safety.py`, `test_fno_enrichment_negative_invariants.py`, `test_listed_contract_selection.py`, and `test_signal_quality_and_learning_enhancements.py`. This was a focused run, not a full current-tree qualification. Two isolated real-function reproductions below succeeded despite that green suite. Do not copy old totals as current evidence.

## P0: correctness defects to fix before signal optimization

### E01. Bought-put premium risk is inverted — reproduced

Location: `engine/position_sizer.py::calculate_position_size`, called by `engine/auto_alert_engine.py::record_alert`.

Reproduction with lot lookup isolated to 65 and no cached regime: exact PE contract; entry premium 150; stop 120; target 240; explicit capital 100000; VIX 15; `direction='BEARISH'`; `payoff_type='LONG_OPTION'`. Current output changes stop to 153 and target to 144 and returns two lots. The correct premium coordinate is long: the bought put loses value toward 120 and gains toward 240, even though its underlying thesis is bearish.

RCA: stop/target orientation follows underlying direction rather than instrument payoff. `payoff_type` is not the central authority for this arithmetic. The caller also labels option alerts `LONG_OPTION` without adequately distinguishing sellers or spreads.

Implement an explicit payoff/side contract shared by sizing, lifecycle, ticket, outcome and replay: underlying direction; action per leg; premium coordinate; strategy exposure. Bought CE and bought PE both have long premium arithmetic. Sold CE/PE have short premium arithmetic and require verified margin/bounded-risk policy. Multi-leg risk comes from joint leg payoff, not the primary leg. Use signed payoff logic, validate anchors, and return unavailable for inconsistent inputs. Never silently replace invalid anchors with percentage stops/targets. Preserve original evidence and explain rejection.

Acceptance: bought CE/PE mirror tests preserve 150/120/240; sold CE/PE tests preserve 150/180/90 with appropriate risk/margin evidence; bull/bear cash controls; multi-leg controls; contradictory direction/side; missing/nonfinite prices; target on wrong side; gap beyond stop. End-to-end assert the same risk units in stored plan, Telegram projection and ticket.

### E02. Old market observations pass fresh-receipt validation — reproduced

Location: `market/contract_selection.py::validate_options_snapshot_provenance`.

Reproduction: valid FYERS/BROKER_REST/LIVE flags, aware `as_of=now`, `receipt_time=now`, `observation_time=now-1 hour`. Current result: `is_valid=True`. Optional malformed observation/receipt fields are silently ignored; absent fields become the same `as_of` timestamp. The function also tolerates a small future age without a documented clock-skew policy.

RCA: envelope freshness is being used as evidence of the underlying market observation's freshness.

Implement distinct exchange observation, local receipt and acquisition-completion times plus monotonic processing age. Validate per-field provenance, ordering, age and cross-leg skew. A provider without exchange timestamps may use explicit receipt-only quality with measured transport limits; do not relabel that receipt as an observed exchange event. Unknown observation age cannot satisfy strategies that require it. Validate cached evidence at consumption; never rejuvenate it on retrieval. Keep provider capability definitions centralized and versioned. Log parse failures with safe context.

Acceptance: fresh receipt/old observation rejects affected actionable features; naive/future/malformed/missing timestamps; receipt preceding observation beyond measured clock tolerance; delayed packet; out-of-order tick; reconnect cache; stale one-leg spread; current cache crossing market close. Both positive controls and missing-data controls must exercise production logic.

### E03. Hypothetical capital and invented anchors remain in application sizing — code-confirmed

`calculate_position_size()` still assigns 100000 when capital is omitted, regardless of the default `is_research=False`. A supplied but unusable account snapshot can leave capital unresolved. Nonpositive entry becomes 100; bad stops and targets become percentage/2R defaults. `record_alert()` supplies no account capital, falls back to premium stops/targets of 0.8/1.3 multiples, and fixes option payoff as LONG_OPTION. Inspect propagation of result status/capital basis: do not expose nonzero research lots as an account recommendation. Other sizing wrappers also contain fallback capital.

Implement mandatory validated account budget or explicit owner scenario budget for actionable quantities. Validate freshness, account identity, currency, encumbrances and available risk. Research mode must be explicit and incapable of gaining actionable status through field copying. Return a typed zero executable quantity with reason when evidence is missing. Avoid treating `available_balance=0` as permission to fall through to another cash field. Margin is not maximum loss or deployable cash. Propagate `status`, `capital_basis`, `reason` and version through all projections.

Acceptance includes missing/zero/negative/nonfinite budget, empty snapshot, fresh balance but stale margin, research-only scenario, existing exposure risk and zero-lot reduction. No percentage repair can turn an unverified setup into an actionable plan.

### E04. Contract identity and multi-leg validation remain incomplete — code-confirmed

`resolve_active_contract()` chooses a supplied prefix ahead of `expected_venue` without explicitly rejecting conflicting expectations. It passes the returned row's own ticker back as the row-validation key; verify exact equality with the requested contract, rather than accepting a different valid row from the lookup. The strict spread branch checks chain expiry strings against each other but must also check both against canonical master expiries, option types/strikes and venue. It currently lacks an explicit shared per-leg observation-time/skew and tradable-size contract. Selecting the first hedge at a strike can reject or accept the wrong expiry while a correct leg exists elsewhere.

Implement exact canonical requested identity and explicit expected constraints. Select hedge from eligible matching expiry/venue/type/lot records before ranking. Require finite non-crossed bid/ask, enough size for the proposed quantity or an honest insufficient-depth state, and tick-valid executable prices. Preserve conservative buy-ask/sell-bid debit. Distinguish expiry payoff R:R from an intraday exit forecast; neither is a probability of winning. Remove claims that a spread eliminates theta/vega risk: current resolver thesis still makes that claim.

### E05. Plan mutation and repeated enrichment can drift — inspect and fix with evidence

`record_alert()` now calls enrichment near entry and retains a later call before insertion. It also rewrites stops/targets to fixed risk multiples in intervening normalization paths. The resolver still constructs percentage premium targets and estimated-delta transformations while `is_estimated=False` can reflect only entry-price provenance. Trace every caller, especially direct option detectors and fallback paths.

Create one finalized versioned decision plan after deterministic evidence qualification. Typed numbers and units belong in the domain plan; templates format them. Record structural target evidence, modeled level assumptions, maximum acceptable entry, invalidation and each dependency's timestamp/version. If normalization finds an invalid plan, reject or regenerate from the same evidence with a new audited version; never stretch a target to force 1:3. Gate cash discovery scope and cheap eligibility/dedup before expensive option fetches. Call the resolver once per evidence version.

## P1: obtain timely, selective signals through one decision pipeline

### S01. One signal-policy authority and an inspectable candidate funnel

Map existing authorities (`detection_context`, `auto_alert_engine`, `alert_scrutiny`, `quality_gate`, `market_regime_gate`, `regime_governor`, `signal_ensemble`, learning lockouts). Consolidate policy ownership without introducing another independent governor. Use one evaluation context: session, instrument, payoff, feature snapshot, regime, policy version and risk budget. Each gate returns accept/hold/reject plus reason and evidence. Derived views consume that result.

Separate non-negotiable data/execution safety gates from empirical strategy filters and contextual features. A data defect always blocks affected actionable output. A learned alpha rule requires recorded out-of-sample evidence. A heuristic can be research/shadow-only until qualified. Preserve exits and exposure care regardless of discovery policy.

Acceptance: CLI/API/background/direct-detector inputs reach the same authority; cache keys include universe, strategy/policy, feature version and as-of; no alternate dispatch bypass; one audit timeline explains every candidate in under a minute.

### S02. Measure missed opportunities alongside prevented noise

Code-confirmed concerns: RSI vetoes at 72/28 or 78/22, fixed VWAP extension gates, two-strike eight-hour learning lockouts, 120-minute strike quarantine, hourly index lockouts and trend overrides coexist. Strong trends can remain extreme; a second stop can precede a valid breakout. Do not assume any of these rules improves expectancy. Do not immediately remove established controls either.

Inventory all suppressors and precedence. Record shadow candidates before empirical filters, with deterministic feature snapshots and later forward-price evaluation. Deduplicate underlying episodes so many detectors/strikes do not multiply one market event. Track veto reason, avoided adverse move, missed favorable move, re-entry delay, remaining net runway and signal density by regime/time-of-day/DTE. Compare each gate via ablation. Keep safety failures excluded from actionable evaluation even if a later price move was favorable.

Lockouts need exchange session IDs, direction/setup/episode scope, idempotent invalidation event IDs and restart persistence. An eight-hour duration is not a session boundary. Current lockout storage uses a symbol key while counters use symbol+direction; verify that alternating directions cannot overwrite each other's protection. Remove test-environment behavior changes such as a zero refractory time; use an injected clock. Permit evidence-backed new-episode/reclaim transitions only after shadow validation. Distinguish duplicate stop reports, alert invalidations and reconciled account losses.

### S03. Preparation, trigger and tradeability must have separate states

Reuse the existing STALK/PRIMED/IGNITED lifecycle; do not create competing status machines. Prepare causal levels and eligible contracts before the trigger so expensive work does not begin only after the move. A watchlist/early warning is not an entry instruction. Triggered tradeability requires current price within the maximum acceptable entry, refreshed quote/depth/risk evidence, and adequate target runway after costs.

Timestamp first evidence, detector evaluation, decision, enrichment, queue insertion, channel acceptance and expiry. Human receipt/read time is unknown unless measured. Report p50/p95/p99 latency and queue age by stage. Define an entry-validity budget from movement speed, spread and measured manual reaction time; do not declare a universal milliseconds SLA without baseline measurements. If an alert is late, downgrade it or retain context with explicit NO CHASE. Candle-close confirmations must not be backdated to the intrabar breach.

Acceptance: fast gap, fleeting wick, slow grind, stale queue, slow LLM/news, price moving beyond the boundary during enrichment, dropped connection, reconnect and service restart. LLM timeout falls back deterministically only if the quantitative candidate itself qualifies; never adds fake conviction or delays the risk path.

### S04. Rank independent opportunities, not overlapping indicator votes

Group features by information family: price structure; participation/breadth; derivatives liquidity/flow; volatility; event context. RSI, EMA, momentum and MACD are often transformations of the same price series, so counting them as independent confirmations needs evidence. Existing `signal_ensemble.py` uses fixed regime weights, a weighted-vote value called confidence, and a VIX fallback separate from the shared authority. Classify that output as a score until calibrated; never display it as win probability.

Use simple baselines first. Train/calibrate only on qualified causal observations with specified target/horizon. Purge overlapping label windows and split chronologically by trading session, grouping correlated index/constituent episodes. Validate ranking, precision-recall, calibration, coverage and abstention. New features must improve held-out net outcomes or timeliness through ablation, including their compute/data cost. No automatic live retuning from a few stop-outs or a single market day.

### S05. Net executable R:R and opportunity concentration

Store separately: underlying structural R, option premium scenario R, spread expiry payoff R, executable indicative R after friction, and observed outcome R. Compute long entry from ask and conservative exit from bid; include dated statutory charges and broker fees, expected manual latency/slippage and sensitivity bands. Do not imply fill certainty or queue priority from displayed depth. Stops can gap; risk figures must include stress scenarios.

Aggregate repeated NIFTY/BankNifty/Sensex/sector/constituent signals into common risk episodes, showing distinct evidence rather than issuing competing tickets. Evaluate portfolio delta/gamma/vega, concentration, correlated risk and capital already committed. A cash sector/breadth input may explain an index setup without generating an unrelated cash trading desk. Rank index opportunities first, then eligible liquid stock F&O, subject to exposure priority and actual tradability.

### S06. Fyers Prime resources and market-data quality

Use one capability/quota authority per account/user across REST/socket workers. Prime is owner-confirmed. Verify actual configured SDK/transport capability, aggregate quotas and live subscription acknowledgments. Current FYERS documentation gives Prime TBT up to 15 symbols per user across connections; treat this as provider capacity, not a target to fill or proof of quality. Existing exposure preempts discovery; report uncovered exposure and BSE capability differences. Do not borrow NSE TBT evidence for BSE contracts.

Record sequence gaps, reconnects, out-of-order events, heartbeat age, quote/trade source and feature completeness. Microstructure signals require reliable observations over time: persistence, replenishment, cancellation and traded flow when available. Resting OBI alone is not proof of informed activity or spoofing. Do not fabricate trade aggressor classification or infer institutional identity. Backfill and news/LLM work use bounded lower-priority queues; protect event-loop health and watch-list trigger processing.

### S07. News and event data with as-of integrity

Persist event occurrence, publication, first-seen, revision, source identity, affected instruments and confidence in entity linkage. Prefer exchange/company/regulator evidence for scheduled announcements and filings. Deduplicate syndication and revised headlines without losing the revision history. Historical evaluation uses first available versions. Surprise news and scheduled events have different timing and slippage profiles. LLM summaries may explain sourced evidence, never invent levels or supply missing numbers. Global context is a hypothesis, not a directional veto by default. Add a new provider only after documenting a material coverage/latency improvement and licensing/operational fit.

## P2: demonstrate edge before promoting changes

### R01. Event recorder, causal replay and dataset manifest

Extend existing storage/history/backtest services. Store immutable raw observations and versioned features/decisions with schema, source, checksum and exchange session; retain legal/data entitlements. Use append-only events and materialized read views rather than competing stores with different facts. All feature joins must respect first availability, master validity and event time. Separate underlying bars, actual option quotes/trades, modeled option estimates and broker executions.

Replay the same production decision policy with a controllable clock and event order. Verify prefix invariance, session transitions and positive/negative controls. Daily-close or theoretical-price option backtests remain research-only when executable intraday evidence is absent. Handle ambiguous same-bar stop/target ordering conservatively or report an outcome interval; never choose the favorable path. Expired-contract API availability alone is not a comparable historical IV surface.

### R02. Pre-registered validation and promotion

Before tuning, freeze the outcome definitions, horizons, net-cost assumptions, comparison baselines, minimum detectable improvement, confidence/uncertainty method, safety regressions and promotion/rejection thresholds. Estimate required independent sessions from effect size and dependence; no arbitrary universal sample count guarantees adequacy. Reserve an untouched chronological holdout. Use rolling/anchored walk-forward evaluation with overlap purging/embargo where needed. Record every tested variant, including failures, to account for selection bias and multiple testing. Statistical correction does not repair lookahead; data integrity tests come first.

Report per regime, DTE, time-of-day, direction, liquidity and news state: qualified candidate count, trigger precision, big-move recall, false-breakout rate, abstention, alert timeliness, achievable entry, net expectancy, drawdown, turnover, churn, MAE/MFE and data coverage. Define a big move using a predeclared volatility-scaled magnitude and horizon; retrospective labels are evaluation only. Entry is the first realistically attainable post-alert price, not an earlier ideal trigger. Block-bootstrap uncertainty by trading session where appropriate. Keep forward price-path statistics separate from reconciled account P&L.

Evaluate the current policy, a simple causal baseline, and each proposed change on identical evidence. Include adverse execution/cost sensitivity. Promote through historical validation → live shadow → owner-reviewed paper deployment. If evidence is insufficient, retain research status and collect data. Never tune and assess on the same holdout. Drift monitoring triggers diagnosis/rollback or controlled recalibration, not reactive production parameter mutation.

### R03. Honest account and delivery foundations

Reopen unresolved prior F08/F09: independent account-scoped fill ledger, immutable broker execution IDs, partial fills, protection acknowledgment/restart recovery and durable alert delivery. Keep live execution blocks. Account reconciliation remains unavailable until independent facts exist. For manually executed Telegram trades, import verified broker executions/account statements through an explicit account-bound process and preserve signal linkage uncertainty; an alert ID match alone is not proof.

Use one authoritative alert store with a durable transactional outbox or equivalent recoverable publication record, stable channel delivery keys and audited retry/ambiguity states. A network timeout cannot establish Telegram delivered or failed. Measure dispatch acceptance separately from human receipt and broker execution. No new signal-quality model may calibrate on fabricated/reconstructed account fills.

## Implementation sequence and artifacts

1. **Baseline and status correction:** Inventory the current diff/untracked files and runtime provenance. Create `docs/implementation_plan_codex/SIGNAL_EDGE_CHECKPOINT_2026-11-01.md`. Reclassify earlier findings as implemented/tested/deployed/empirically-qualified independently. Record reproduced defects and ownership. Do not claim F08/F09 implemented merely because their blocks remain.
2. **Correctness release:** Fix E01–E05 with actual-boundary regressions and positive controls. Update safety contracts for payoff orientation, observation freshness, explicit capital and immutable finalized plan. No strategy tuning in these patches.
3. **Policy and observability:** Implement S01–S03 and candidate/suppression/latency recording. Preserve all safety gates. Establish a measurable baseline before changing empirical vetoes.
4. **Replay and evaluation:** Implement R01/R02. Compare RSI/extension/lockout/confirmation alternatives in shadow, then S04/S05 ranking and net-R improvements. Promote only passing variants; retain negative results.
5. **Data and operational integration:** Complete S06/S07 and R03 in bounded increments with failure/recovery tests. Existing safe operations continue; unresolved live qualification stays disabled.
6. **Final review:** Provide changed-file coverage, domain ownership diagram, exact test outputs, dataset/policy manifests, comparison report, runtime-versus-workspace status, rollback instructions and unresolved owner/broker acceptance items.

For each work package, record RCA, real callers, evidence requirements, changed files, test names/results, migration/backward-compatibility implications, rollback and acceptance status. Migrations are explicit offline operations. Unknown/legacy subscription purposes are reconciled, not silently deleted. Reject speculative architecture rewrites and new providers without a demonstrated need.

## Verification discipline

Use `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` with affected suites. Keep the verified-market-safety suite mandatory. Tests must not touch real broker mutation routes, Telegram or production app-data. Add meaningful regressions for the two reproduced defects; verify both rejection and success paths so “reject everything” cannot pass. Use production policy with injected clock/data; no test-environment time or VIX bypass. Audit the global autouse VIX fixture: missing-data behavior must remain covered at real application boundaries, not only a special excluded module.

Run Ruff and `git diff --check`; then the full backend suite once relevant suites pass. Run renderer tests/build when payload semantics change. Review warning classes explicitly. Do not repeatedly rerun unchanged broad suites or add overlapping counts. Tests prove bounded behavior; replay proves bounded historical performance; neither alone proves deployment or future edge.

## Efficient Gemini execution and GPT review

Work one dependency-coherent package at a time; targeted search/read, minimal patch, focused tests, checkpoint. Reuse `market.contract_selection`, canonical paths/timezone/rules, existing alert identity/storage and OMS. Publish an ownership table before extracting services; retire old call paths in the same migration. Avoid parallel policy engines, new generic frameworks, heuristic confidence inflation or mechanical “more confirmations” features.

Reserve GPT-6.1 SOL review for payoff math, provenance/accounting invariants, causal replay design, contradictory statistical results and final release diff. Prepare a compact packet: finding ID, exact caller/diff, reproduction, negative/positive tests and unresolved decision. Routine implementation remains with Gemini. Persistent checkpoints prevent repeated repository-wide context loading.

## Primary references checked for this review

- FYERS API changes notice, published 15 October 2026, effective 16 October 2026: https://fyers.in/notice-board/changes-to-fyers-api-rate-limits-and-usage . Recheck limits/capabilities at implementation time.
- FYERS TBT overview, updated 14 October 2026: https://fyers.in/api-docs/v3/api/websockets/tick-by-tick-socket/ . Current indexed documentation states Prime capacity is per user across connections; verify exact exchange support and plan constraints before transport changes.
- Bailey, Borwein, López de Prado and Zhu, *The Probability of Backtest Overfitting*, November 2014: https://www.carmamaths.org/resources/jon/backtest2.pdf . Use its selection-bias reasoning with appropriate chronological/causal evaluation; do not treat any one statistic as proof of edge.

Do not change exchange rules from memory. Retain current primary sources/effective dates in `docs/SAFETY_CONTRACTS.md` and verify any proposed market-rule change independently.

Start by reproducing E01/E02, correcting the completion register, and fixing payoff and freshness semantics. Do not add a new detector until the evidence and evaluation paths can measure whether it improves decisions.
