# Antigravity implementation prompt — F&O correctness and release completion

## Role and objective

Act as the implementing architect for ChanakyaTrade. Complete the outstanding safety and integration work in the current workspace, then validate the existing change set. Prioritize NSE/BSE index options, followed by stock F&O during their active derivative sessions. Improve timeliness and measurable risk-adjusted opportunity selection without claiming predictive ability or profitable edge without evidence.

Workspace: `C:\Users\brije\.gemini\antigravity\scratch\chanakya-trade`.
Review reference date: 1 November 2026. Determine the actual date when executing. Branch reviewed: `codex/verified-market-safety`; HEAD: `82114d06c38c8a8f297fa3e7a48b6ac91787e8ab`.

This prompt authorizes reversible local implementation and verification. Work through the phases below without repeatedly asking permission. Do not commit, push, send Telegram messages, submit broker orders, or enable live-execution qualification. Preserve existing user changes. Never print `.env`, tokens, passwords, OTP seeds, account identifiers or session contents.

## Mandatory reading and authority

Read `AGENTS.md`, `docs/SAFETY_CONTRACTS.md`, and `docs/FNO_DESK_ROADMAP.md`. Read the relevant `.agents/skills/` runbook immediately before working on its domain. The safety contract supersedes older examples and outdated review plans. In particular, the September plan at `docs/implementation_plan_codex/chanakya-trade-final-agent-implementation-plan.md` has an obsolete baseline and approval workflow; do not treat it as current operating authority.

Preserve `tests/test_verified_market_safety.py`. Never remove a safety test or change its expected behavior just to obtain a green result. Correct an obsolete market assumption only with a primary source, publication date and effective date. Do not invent rules for future dates. Keep `LIVE_EXECUTION_QUALIFIED` disabled until owner acceptance of the documented account-ledger, recovery, protection and broker criteria.

## Baseline and honest validation status

- At this review, tracked changes span 167 files, approximately 6,103 insertions and 3,867 deletions. Additional untracked source, tests, workflows and documents also exist. Capture a fresh inventory; tracked diff statistics exclude untracked files.
- Prior full-suite evidence: 4,972 passed and 4 failed in roughly 319 seconds. That run predates the final enrichment/sizing edits and is NOT a clean validation of the current tree.
- The four earlier failures were template tests using expired/generic option symbols. Their fixtures were subsequently updated, and all four passed in a focused run. Keep their behavioral intent: display valid alternatives and suppress unverifiable/expired ones.
- Latest review run on the interrupted enrichment patch: **24 passed, 4 failed**. All 22 cases in `tests/test_verified_market_safety.py` passed, and two sizing cases passed. Four enrichment cases failed because the stricter production path now requires a live broker snapshot that those fixtures do not provide.
- Exact current failures: `test_scale_isolation_in_fno_enrichment` in `tests/test_alert_identity_invariants.py`; `test_universal_fno_contract_enrichment` in `tests/test_detector_alignment_enrichment.py`; `test_fno_stock_enrichment_converts_ticket_to_option_space` in `tests/test_fno_spot_leakage_invariants.py`; `test_auto_alert_engine_option_enrichment_signature` in `tests/test_multi_asset_signals.py`.
- Ruff passed for `engine/option_resolver.py`, `engine/auto_alert_engine.py`, `engine/alert_model.py`, and `tests/test_signal_data_integrity.py` during this review. This does not establish correctness of the entire diff.
- Previous deployment/dependency observations in `HARDENING_STATUS.md` are historical observations. Recheck them; do not repeat them as current facts.

The review is a risk-focused assessment of a large accumulated change set, not certification of every changed line or production readiness. Build a coverage register so no changed domain is silently treated as reviewed.

## Findings and root causes: address in this order

### F01 — Strict option resolution can still manufacture a spread (P0, code-confirmed)

Evidence: `engine/option_resolver.py`, `resolve_option_contract()`. New `contracts_override` and `require_listed_contract` arguments reject a missing primary leg, but later spread construction still creates a hedge symbol/premium when the hedge is absent (`opt_ltp * 0.42`), floors debit, and rewrites debit/hedge premium when the calculated spread looks expensive (`strike_width * 0.45`). Hedge selection does not establish matching expiry and master evidence for both legs. `is_est` is reset after the illiquid-spread branch, so it cannot reliably describe all modeled inputs.

RCA: one return type mixes research estimates, observed market evidence and executable plans; validation covers the primary contract but not the complete payoff structure.

Implement: distinguish observed execution evidence from research estimates. For actionable spreads require both exact active listed legs, same underlying/venue/expiry, compatible lot sizes, valid direction/strike ordering, fresh tradable quotes and measured liquidity. Buy at observable ask and sell at observable bid for conservative indicative debit; include explicit costs/slippage assumptions. Preserve the observed prices even when the trade is unattractive. Missing evidence yields unavailable/research-only, never invented premium, payoff or R:R. Reuse the same strict policy for every production caller; the default `require_listed_contract=False` must not provide a bypass into Telegram, UI tickets or order intents.

Acceptance: missing hedge, different expiries, stale quote, crossed book, no bid/ask, mismatched lot, expensive debit and absent master each produce no actionable spread. Valid bull and bear spreads retain exact observed premiums and correct bounded payoffs. Research output is visibly classified and cannot enter actionable dispatch or execution.

### F02 — Sizing precedes contract enrichment and can mix spot with premium (P0, code-confirmed)

Evidence: `engine/auto_alert_engine.py`, `record_alert()`: sizing population occurs before the later `_enrich_fno_contract_if_applicable()` call. Sizing can therefore use underlying entry/stop units, then enrichment changes the ticket to premium units and writes a different lot. `calculate_position_size()` defaults to capital 100,000 and replaces stops above entry with a long-style percentage stop. An underlying being F&O eligible also influences derivative sizing even when the intended instrument is cash context.

RCA: instrument selection, coordinate semantics, account risk and ticket construction are interleaved mutations rather than an explicit decision boundary.

Implement: resolve an immutable instrument/strategy evidence object first. Carry explicit underlying versus premium coordinate types, direction, long option versus short option/spread payoff, master version, expiry, lot, tick and source timestamps. Finalize executable sizing only after contract and premium-risk evidence are available. Use an explicit owner risk budget/account snapshot; label hypothetical research capital and never expose it as account sizing. Do not replace a valid bearish stop with a bullish stop. Reject missing/invalid risk anchors. Zero quantity is valid. Populate sizing status, capital basis and reason consistently; recompute after any coordinate or contract change. Separate cash sizing from F&O eligibility.

Acceptance: bull/bear mirror cases, long CE/PE, premium-space and underlying-space alerts, cash shares on F&O underlyings, missing capital, contract rollover, unaffordable lot, physical-expiry reduction and stale prefilled sizing. No stale lot/quantity survives enrichment. Short-option sizing requires margin and bounded-risk evidence, not long-premium arithmetic.

### F03 — Master lookup is not the same as active contract validation (P0, code-confirmed)

Evidence: `engine/position_sizer.py::get_lot_size()` and the strict resolver branch convert `minLotSize` with `int()` without consistently validating integrality, trade status, listed expiry/cutoff, venue, underlying, option type and strike. `get_symbol_info(require_fresh=True)` controls snapshot freshness; it returns raw rows, not a validated active instrument. Some template paths still look up a bare underlying lot.

RCA: callers attach different meanings to the same raw lookup. Duplicated checks drift.

Implement one canonical active-contract resolver using the established `market/contract_selection.py` validation, with a typed result and explicit failure reason. Reuse it for actionable lot/tick/expiry/venue/token resolution, sizing and render validation. Preserve the NFO→NSE_FO and BFO→BSE_FO mappings already added. Never guess symbols or lots from an underlying map for actionable contracts. Review malformed/display-only symbols and fractional/nonfinite/bool lot inputs. Keep research lookups explicitly separate.

Acceptance: active/inactive, expired, expiry-day cutoff, missing token, fractional/negative lot, wrong underlying/venue, stale/degraded master and NFO/BFO alias cases. Every consumer agrees on the same contract identity and authority.

### F04 — Snapshot provenance and time validation remain incomplete (P0/P1, code-confirmed)

Evidence: new enrichment code parses `as_of` then calls `astimezone()` without rejecting a naive timestamp; this treats server-local time as evidence. Provider filtering uses a small exact-name denylist. `market/options.py::get_options_snapshot()` constructs LIVE/BROKER_REST metadata based on transport and market-open status; that alone does not establish that each contract's market observation is fresh or that a provider is genuine. Snapshot receipt time and exchange observation time are distinct.

Implement shared provenance validation: aware timestamps; finite nonfuture bounded age; trustworthy provider identity/capability; explicit simulation exclusion; acquisition and observation times; per-leg freshness where available. Do not refresh the evidence timestamp on cache retrieval or off-market transition. Reject unknown source metadata rather than interpreting missing fields optimistically. Avoid duplicate per-caller freshness policies; justify age limits from the product SLA.

Acceptance: naive/future/stale/missing timestamps, mock-looking provider aliases, live metadata with synthetic evidence, cache aging, market close across a cached snapshot and out-of-order observations. Persist provenance in the alert audit and show why a candidate was held.

### F05 — Resolver business rules still embed assumed VIX, delta and target multipliers (P1, code-confirmed)

Evidence: `engine/option_resolver.py` defaults VIX to 14.5, estimates delta from strike tier, imposes percentage stops/targets and describes spread behavior with stronger certainty than the inputs support. `analysis/regime_governor.py` substitutes 13.5 when test-environment flags are present, which can hide missing-input behavior during verification.

Implement: route regime inputs through the verified shared VIX authority. Preserve unavailable inputs. Classify modeled option levels as estimates with their assumptions; they cannot satisfy the structural actionable-blueprint requirement merely because all fields are populated. Require causal structural invalidation and a stated premium-risk method. Supply test VIX explicitly in fixtures; exercise the same production missing-data branch under tests. Remove unsupported certainty claims and do not tune thresholds from a handful of examples.

### F06 — Template rendering can reintroduce unverified trade authority (P1, code-confirmed risk)

Evidence: `bot/alert_templates.py` now checks alternative lot/expiry, but expiry resolution can still infer a date; other lot/display and hedge paths remain separate. Positive renderer tests use an exact-looking symbol plus manually supplied expiry and minimal master stub, which is not a complete listed-contract control.

Implement: render actionable quantities/expiry/payoffs only from the finalized validated plan. Do not infer an executable expiry from a display label or calendar fallback. A context-only roadmap remains available with explicit status. Audit main headline, alternative, hedge, rollover and no-chase displays together. Remove claims such as universal margin safety/relief or elimination of theta/gap risk unless their exact preconditions are verified. Do not delete useful context merely to hide a failed actionable validation.

### F07 — Interrupted enrichment patch and fixtures need completion (P1, reproduced)

Complete F01–F06 before making the four failing tests green. For positive transformation tests, provide explicit fresh broker snapshot, exact active master rows, finite prices/lot values, explicit `is_estimated=False`, and a controlled clock. Avoid permissive MagicMock values acting as booleans or prices. For absent/delayed feeds assert no actionable enrichment. Fixtures must exercise contracts, not bypass the gate. Add negative end-to-end checks for estimated legs and stale sizing. Keep tests hermetic; the latest run attempted broker lookup in these cases.

### F08 — Live account ledger, recovery and protection are incomplete (P0 release blocker, documented)

Existing qualification, UNKNOWN_FREEZE, basket/slice/GTT and route restrictions are intentional controls. Keep them. Read the current order lifecycle, reconciliation and emergency implementations before proposing migrations.

Implement separately: account/broker/session scoped intents, confirmations and immutable attempts; durable client correlation and broker IDs; append-only fills with stable execution IDs; transactional state transitions; independent opening balance and fill-derived positions; fee/cash/margin accounting; partial-fill and protection acknowledgment tracking; restart recovery and unknown-attempt reconciliation. Never blindly retry an ambiguous placement. Cancellation/exit acceptance is pending until broker state establishes the result. Require owner acceptance and broker-specific paper/sandbox/read-only recovery evidence before any request to qualify live execution.

### F09 — Durable alert delivery and resource deployment remain unproven (P1, documented; revalidate)

Audit one authoritative ingestion path through storage, scrutiny, SSE, Telegram gating and delivery records. Add transactional outbox/replay and stable delivery keys; distinguish queued, attempted, acknowledged, failed and ambiguous delivery. Recover pending work after restart and record suppression reasons. Account for the Telegram API's actual retry/duplicate semantics; do not promise exactly-once delivery across a network without proof.

Recheck current Fyers SDK imports/dependency compatibility, Prime quota authority and transport capability. A confirmed Prime subscription is valid owner context; it does not prove all endpoints/transports work in this interpreter. Preserve exposure subscriptions before discovery and report coverage gaps. Budget CPU/I/O/LLM queues so news and analytics cannot starve exposure monitoring or fresh index signals. Preserve exits in excluded discovery segments.

### F10 — Statistical edge and news integration require independent evidence (P2 research gate)

Changes to learning/outcome provenance correctly aim to prevent alert-price paths becoming account win rate/Kelly evidence. Verify every writer/reader/export honors that boundary. No positive edge bonus from legacy, test, milestone or unreconciled data.

Build causal replay with as-of underlying/options/depth/event data, actual listed contracts, spread/cost/slippage/latency assumptions, and explicit limits for unavailable queue/impact data. Test prefix invariance and bull/bear/neutral symmetry. Compare against simple baselines using held-out chronological regimes and walk-forward evaluation; record multiple-testing/selection effects and confidence intervals. Track false signals, missed moves, alert age, lead time, no-chase violations, attainable R and drawdown separately from hypothetical maxima. A hindsight big move is not evidence it was predictable.

For news/events retain event time, publication time, first-seen time, source, revisions and dedup identity. Exchange/company/regulator announcements are primary evidence; unverified headlines cannot silently change conviction or risk. Test stale/repeated/revised news, scheduled versus surprise events and historical lookahead. Add providers only after a measured coverage/latency or held-out decision benefit justifies their cost.

## Execution phases and deliverables

1. **Inventory and RCA:** Record HEAD, branch, tracked/untracked change inventory and existing user edits. Map every changed file to domain, behavior, tests, deployment requirement and review status. Include rule schedule/charges/calendar, broker/session/depth/quotas, OMS/security/transactions, alerts/templates/outcomes, discovery/subscriptions, LLM deadlines/learning, API/frontend and CI/docs. Do not claim a domain complete from a passing unrelated suite. Capture current failures once.
2. **P0 evidence and plan boundary:** Implement F01–F04 in small coherent patches. Prefer one validated instrument/quote/strategy evidence authority over adding more local symbol/provenance checks. Characterize and migrate real callers. Preserve existing safe behaviors and fail closed with useful reasons.
3. **P1 semantics and integration:** Implement F05–F07; fix positive fixtures only after the corresponding policy is settled. Verify alert storage, UI, Telegram projection and ticket values derive from the same finalized plan. Persist audit trail at every held/accepted transition.
4. **Release foundation:** Implement F08–F09 incrementally, including explicit offline migrations where necessary, rollback and recovery. Keep live qualification disabled. Document any external broker limitation as an unresolved acceptance item.
5. **Research and calibration:** Implement F10 as shadow/replay evaluation. Promote a strategy or new data source only after its recorded validation gates pass. Failure to demonstrate alpha must result in an honest research status.
6. **Final integration review:** Inspect all remaining changed/untracked files against the coverage register. Run the full backend suite after affected suites pass, inspect every warning class, and run frontend tests/build if API payloads or renderer contracts changed. Recheck dependency health and deployment/code provenance through a read-only controlled smoke test. Do not restart the user's daily service until the build and broker profile are qualified and a scoped restart/recovery plan is documented.

For each phase, update `docs/implementation_plan_codex/IMPLEMENTATION_CHECKPOINT_2026-11-01.md` with: finding ID, RCA evidence, files changed, behavior before/after, tests and exact result, unresolved items, next phase. Continue to the next independent authorized step. Stop only dependent work when a real external requirement is missing; explain it precisely.

## Verification commands and test policy

Use the project interpreter: `.\.venv\Scripts\python.exe`. `pytest` is not on the shell PATH. The old default `.pytest_cache` path had permission errors; use `-p no:cacheprovider` or a dedicated workspace cache path. Do not alter unrelated permissions or delete arbitrary files to fix that warning.

Required baseline: `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_verified_market_safety.py`.

Add meaningful regression tests for the failures above, then run affected suites covering resolver, sizing, contract selection/master, contagion, templates, ingestion/scrutiny, discovery, OMS and outcomes. Use controlled clocks and isolated app-data roots. No real network, broker mutations, Telegram sends or production singleton persistence in deterministic tests. Mock the source boundary while retaining the actual production gates. Use concurrent/restart/crash controls where state safety matters.

Run Ruff for changed Python files and `git diff --check`. After focused checks pass, run the full suite with the established worker configuration and retain its final summary. Do not add overlapping test totals. A static lint pass is not a behavioral proof. A passing software suite is not proof of trading edge or broker acceptance.

## Regression protection across AI tools

Maintain concise shared behavioral contracts in `docs/SAFETY_CONTRACTS.md`, reference them from AGENTS/runbooks, and preserve independent negative tests. Record market-rule source/effective dates with the rule implementation. Update CI to cover the critical real boundaries, not only string/static assertions. Document required branch protection, owner review and status checks; do not claim local files enforce GitHub settings. No prompt can guarantee that another model or a direct repository owner change cannot undo a fix.

## Efficient implementation protocol for Gemini and later GPT review

- Read only the current phase's modules, real callers and relevant tests. Search targeted symbols before loading large files. Avoid repeatedly printing full logs/diffs or re-running an unchanged full suite.
- Keep reasoning summaries compact: evidence → RCA → change → acceptance result. Checkpoint decisions in the file above rather than replaying the entire conversation.
- Do not rewrite large modules, add speculative providers/models, or tune thresholds during safety repairs. Extract a shared service only where a demonstrated duplicate invariant warrants it.
- Use GPT-6.1 SOL for bounded escalation: transaction/recovery design, contradictory trading semantics, security boundaries or interpretation of failed held-out validation. Prepare a small packet containing the finding, relevant diff, reproduction, test result and exact unresolved decision. Routine fixture updates and mechanical implementation remain with Gemini.
- Final output: changed-file coverage register; implemented/remaining finding table; exact validation results; migration/deployment steps; current runtime-versus-workspace status; and acceptance items still blocking live qualification. Never state “all gaps fixed” without scope and evidence.

Begin with inventory, reproduce the four current failures, and complete the strict option-plan and sizing boundary before proceeding to additional strategy features.
