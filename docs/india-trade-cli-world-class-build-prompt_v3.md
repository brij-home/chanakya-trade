# World-Class India Trade CLI Modernization and Build Prompt

**Revision:** v3 — adds a greenfield local-first bootstrap contract for a runnable cross-platform MVP

## Role

Act as a principal software architect, senior Indian-market trading-systems engineer, quantitative researcher, product designer, security engineer, SRE, and rigorous code reviewer.

You are improving the open-source India Trade CLI project into a trustworthy, evidence-first, high-performance trading operating system for Indian markets. Think like the person accountable for user capital, broker credentials, data correctness, incident recovery, and long-term maintainability.

Do not optimize for the number of agents, strategies, screens, or lines of code. Optimize for correctness, safety, explainability, user confidence, operational resilience, and a delightful but unambiguous experience.

## Project context

Repository: https://github.com/hopit-ai/india-trade-cli

DeepWiki index: https://deepwiki.com/brij-home/india-trade-cli

Review baseline: commit fd03578ae0cb10ef2cc7fc1f1f9a5992a028a230

The DeepWiki target is under brij-home while the reviewed GitHub snapshot is under hopit-ai. Pin your work to the actual checked-out commit and verify whether the two sources still match. Treat DeepWiki, README, specifications, issues, and code as inputs to reconcile, not as automatically correct facts.

The product currently includes:

- CLI REPL and Textual TUI;
- FastAPI/web skills and server;
- macOS Electron shell;
- Telegram bot;
- Fyers, Zerodha, Angel One, Upstox, Groww, and mock broker concepts;
- a Dhan adapter that is not consistently represented in the documented support matrix, illustrating code/documentation capability drift;
- separate data, primary, and execution broker roles;
- broker/yfinance/NSE/disk data fallbacks;
- technical, fundamental, options, news/macro, sentiment, sector, risk, and debate agents;
- DCF, reverse DCF, ML analyst, strategy templates, AI strategy builder, standard backtests, options backtests;
- portfolio aggregation, risk limits, alerts, trade memory, PDFs, and OpenClaw-style interfaces.

The current breadth is valuable. The following risks must be treated as first-class engineering work:

- authentication and authorization are not consistently fail-closed;
- sessions, streams, alerts, memory, risk state, and other state are global, in-memory, JSON-backed, or weakly scoped;
- live execution can receive dummy price/quantity values, has permissive mode behavior, has a confirmation bypass, and can record trades before broker reconciliation;
- risk failures can be swallowed rather than blocking;
- multi-leg execution is not atomic or spread-safe;
- broker symbols, option contracts, lot sizes, expiry rules, and pseudo symbols do not have one authoritative canonical model;
- live, delayed, scraped, cached, and proxy data can be blended without a universal freshness and provenance contract;
- ordinary backtests can use same-bar signal/fill assumptions and simplified full-capital P&L;
- options backtests can use reconstructed proxy premiums rather than historical chains;
- Python skills and generated strategies are dynamically imported; AST checks are not a security boundary;
- onboarding accepts dangerous arbitrary keys/URLs or can run installation subprocesses;
- raw errors, HTML, webhook destinations, and external content are not sufficiently controlled;
- Electron localhost/IPC/external URL behavior needs hardening;
- dependencies, CI action references, builds, security scans, and release signing are not yet institutional-grade;
- documentation and specifications contain implementation mismatches and stale or overconfident claims.
- portfolio totals, day P&L, blocked margin, partial broker failures, option expiry, and Greeks do not yet share an authoritative accounting/reconciliation contract;
- bare numeric position sizes can be heuristically interpreted as rupees or shares;
- OAuth callbacks are not consistently bound with per-attempt state, nonce, PKCE, expiry, one-time use, and user/account identity;
- the post-mortem module called audit is learning memory, not an immutable financial/security audit trail;
- live API automation and commercial market-data use need current, effective-dated regulatory and licensing controls.

## Mission

Make the product:

1. safe by default for a real user;
2. paper-first and impossible to confuse with live trading;
3. correct for NSE/BSE/NFO workflows and broker-specific contracts;
4. transparent about data source, freshness, assumptions, uncertainty, and limitations;
5. deterministic at risk, order, and reconciliation boundaries;
6. resilient to stale data, broker outages, partial fills, restarts, duplicate requests, and worker failover;
7. secure against auth bypass, cross-user leakage, SSRF, XSS, CSRF, prompt injection, secret leakage, supply-chain issues, and arbitrary code execution;
8. fast and responsive under concurrent research, quotes, portfolios, alerts, and backtests;
9. coherent across web, Electron, TUI, CLI, and Telegram;
10. maintainable through typed contracts, migrations, observability, tests, release gates, and truthful documentation.

Do not claim profitability, regulatory approval, broker certification, institutional-grade readiness, or SEBI compliance unless there is direct, documented evidence and qualified review. This is engineering work, not personal investment advice.

## Non-negotiable safety rules

- Never submit a live broker order during development, tests, demos, or evaluation.
- Never read, print, store, or transmit real broker credentials in test workflows.
- Use a deterministic fake broker, synthetic instruments, and replayed fixtures for all automated tests.
- Keep live execution disabled by default and behind an explicit server-side feature flag and account allowlist.
- The LLM may propose research or an order intent, but it may not bypass deterministic risk policy, invent executable fields, or directly place a live order.
- Risk, instrument mapping, quote freshness, buying power, market calendar, confirmation, and reconciliation failures must fail closed.
- A broker timeout after submission is an unknown order state, not a safe failure and not permission to blindly retry.
- Never use delayed, scraped, cached, or proxy data for live order pricing unless an explicit, separately approved policy says it is valid. The default policy must block.
- Never use an underlying price as an option premium or a pseudo symbol as a broker order symbol.
- Never treat an application alert as a broker stop-loss or protection order.
- Never dynamically execute untrusted Python in the main process.
- Never make an external request to a user-supplied URL while attaching a secret or bearer token.
- Never accept arbitrary credential key names, arbitrary outbound webhook destinations, or remote package-install commands.
- Never place secrets in logs, HTML, API errors, LLM context, child-process environments, plain backups, browser storage, or generated reports.
- Never infer whether a numeric order size means rupees, shares, contracts, or lots. Require explicit units.
- Never infer that SELL means close. Require open, close, reduce-only, close-only, hedge, or rebalance intent and validate the resulting exposure.
- Never report a missing broker, stale account, missing Greek, or approximate expiry as complete or as numeric zero.
- Never treat a post-mortem learning record as the regulatory, financial, or security audit trail.
- Never launch live/commercial behavior without an applicability decision for retail-algo controls, product role, privacy, and market-data entitlements.
- Preserve existing user changes. Inspect repository status before modifying files. Use small, reviewable changes and avoid destructive rewrites.

## How to begin

### Phase 1: inspect and reconcile before editing

1. Inspect the exact checkout, branch, commit, working-tree status, package manifests, tests, docs, specs, Docker files, CI, and frontend.
2. Read the entire supplied DeepWiki page set and compare it with the actual implementation.
3. Build a capability matrix with columns:
   - capability;
   - documented behavior;
   - actual behavior;
   - implemented;
   - tested;
   - safe for live;
   - data requirement;
   - known limitations;
   - source file and commit;
   - proposed owner and priority.
4. Search for all order placement paths, broker calls, risk checks, credential reads/writes, subprocesses, dynamic imports, outbound HTTP calls, global state, file persistence, and public endpoints.
5. Identify every P0 security, execution, data-integrity, and recovery risk.
6. Build a product-role and applicability matrix covering private personal tool, internal desk, broker integration, research/advisory product, and commercial algo provider.
7. Build a market-data entitlement matrix covering display, non-display, derived data, redistribution, retention, model use, and export.
8. Produce an architecture decision record and phased implementation plan before making broad changes.
9. Ask questions only when a missing decision materially changes the design. If the user does not answer, use these defaults:
   - local-first or private-server deployment;
   - one tenant-safe user model even for single-user installs;
   - Observe, Simulate, and Execute modes;
   - paper trading by default;
   - manual live confirmation only after all safety gates;
   - one thoroughly certified execution broker before multi-broker expansion;
   - official broker/licensed data for live decisions;
   - cash equities before futures, then defined-risk options;
   - read-only Telegram;
   - supported provider APIs or local models, never unofficial session APIs;
   - conservative risk defaults.

Do not start by adding another agent or strategy. First make the safety and domain contracts authoritative.

## Target product model

Expose three explicit modes everywhere:

| Mode | Meaning | Allowed actions |
| --- | --- | --- |
| Observe | Read-only market, portfolio, and research | No order mutation |
| Simulate | Paper, what-if, strategy, and backtest | Fake broker or simulator only |
| Execute | High-assurance live workflow | Fresh supported data, deterministic policy, confirmation, idempotency, reconciliation |

Keep these concepts separate:

1. Observation: provider facts and market state.
2. Analysis: indicator, fundamental, ML, or agent inference.
3. Decision: deterministic policy result and reasons.
4. Order: requested, acknowledged, filled, rejected, cancelled, or unknown broker action.

The primary user journey should be:

1. select account and mode;
2. inspect watchlist/market state and data freshness;
3. open an evidence-rich research view;
4. inspect bull case, bear case, disagreement, assumptions, and invalidation;
5. simulate or create an order intent;
6. see exact instrument, quantity, margin, costs, protection, and risk checks;
7. confirm only in Execute mode;
8. observe broker acknowledgement and live state;
9. reconcile and journal the result.

## Target architecture

Use a modular, typed, event-aware architecture:

~~~text
Clients: Web / Electron / TUI / CLI / Telegram
    |
API gateway: authentication, origin policy, tenant/account context, rate limits
    |
Application services:
  research and analysis
  portfolio and positions
  risk and policy
  order intent and execution
  alerts and journal
    |
Workers and events:
  analysis jobs, backtests, reports, broker polling, reconciliation, alerts
    |
Infrastructure:
  Postgres for durable domain state
  Redis or durable broker for jobs, locks, rate limits, fanout
  object storage for reports and immutable run artifacts
  provider adapters for brokers, market data, news, fundamentals, and models
~~~

Keep the API stateless. Long-running work must return a job ID, progress, cancellation, timeout, retry policy, dead-letter handling, and a durable result reference.

Use dependency inversion:

- domain models and policy must not depend on provider SDKs;
- provider adapters must map into canonical contracts;
- UI clients must consume versioned API contracts;
- LLM orchestration must call application tools, never private module internals;
- execution must not depend on LLM availability after an intent is created;
- a kill switch must remain usable when the LLM, web UI, or primary broker is unavailable.

## Canonical domain contracts

Implement and validate typed models for:

### Authoritative value types

Do not use unitless primitive numbers at money-risk boundaries. Define:

- Money as Decimal amount, INR currency, and rounding policy;
- Price as Decimal value, tick size, instrument, source, and as-of time;
- Quantity as shares or contracts;
- Lots as lot count plus effective lot size and instrument-master version;
- Percentage as a bounded decimal with a named denominator;
- PositionIntent as open, close, reduce-only, close-only, hedge, or rebalance;
- AccountingStatus as complete, partial, stale, reconciling, failed, or disputed.

Reject ambiguous commands such as “buy 50” unless an explicit user-visible default has been configured and is repeated in preview and confirmation. Never use a price-based heuristic to decide whether 50 means INR 50 or 50 shares.

### Instrument

Include immutable instrument ID, exchange, segment, underlying, display symbol, broker token mappings, asset type, expiry, strike, option type, lot size, freeze quantity, tick size, currency, price bands, status, effective dates, settlement rules, margin/product eligibility, and instrument-master version.

All broker symbols are mappings. Never make a provider-specific symbol the primary identity.

### QuoteSnapshot

Include instrument ID, bid, ask, last, volume, open/high/low/close where applicable, source, provider request ID, market timestamp, received timestamp, freshness age, market-session state, live/delayed/historical/proxy classification, corporate-action adjustment, completeness, anomaly flags, and fallback reason.

### OrderIntent

Include tenant, user, workspace, account, mode, strategy/run ID, side, purpose, all legs, expected notional, risk budget, policy version, quote/data versions, idempotency key, correlation ID, confirmation state, expiry, and audit references.

### OrderLeg

Include canonical instrument ID, resolved broker symbol/token, side, quantity, lot count, order type, limit price, trigger price, product, validity, disclosed quantity where applicable, protection instructions, expected margin, estimated fees/taxes, and price guard.

### RiskDecision

Include allow/block/warn, reasons, evaluated limits, current inputs, reservations, data freshness, market state, account state, policy version, decision time, expiry, and approver/override metadata.

### BrokerOrder, Fill, Position, Reservation, AuditEvent

Persist broker request IDs, client IDs, status history, fill IDs, fees/taxes, timestamps, quantities, average prices, realized/unrealized P&L, margin, risk reservations, actor identity, before/after hashes, policy/model/data versions, and correlation IDs.

AuditEvent is an append-only operational/security event. Keep it separate from research memory, journal notes, analyst grading, and model-training feedback.

## Order lifecycle and execution

Implement an explicit, durable state machine:

~~~text
Draft
  -> Preview
  -> Confirmed
  -> Submitting
  -> Open or PartiallyFilled or Filled
  -> CancelPending
  -> Cancelled
  -> Reconciled

Submitting may also become Rejected or Unknown.
Unknown must be reconciled before a new submit is permitted.
Every transition emits an immutable event.
~~~

Requirements:

- server-generated identity and idempotency; never trust a client session ID as ownership;
- duplicate requests with the same idempotency key return the existing outcome;
- order preview must be immutable or versioned between preview and confirmation;
- confirmation is bound to user, account, full order intent, quote guard, policy version, and expiry;
- quote age, price movement, instrument status, market session, buying power, margin, and risk must be revalidated immediately before submit;
- submit only canonical broker-mapped instruments;
- translate provider statuses into a canonical state and preserve raw status safely;
- poll/webhook/reconcile orders and positions after every uncertain outcome;
- record partial fills and fees accurately;
- make cancellation and cancel-all independent, auditable operations;
- enforce rate limits and broker throttling;
- use broker-native stop/OCO/cover/protection orders when supported;
- show an explicit unprotected state when they are not supported;
- validate every multi-leg spread before any leg is submitted;
- validate whether each side opens, closes, reduces, hedges, or reverses a position;
- prevent a close-only/reduce-only action from increasing exposure;
- enforce holdings/borrow/product rules before an equity SELL and coverage/margin rules before an option SELL;
- reserve margin and define the maximum allowed temporary naked exposure;
- use broker-native basket/atomic functionality where possible;
- otherwise use a staged workflow with remediation, alerting, and operator intervention;
- never silently convert a strategy into a pseudo-option order.

## Risk and policy engine

Build a deterministic, account-scoped risk service. It must:

- use the actual order legs, positions, open orders, current quote, account funds, margin, and instrument rules;
- use exchange calendar and IST policy;
- reserve notional, margin, and risk budget atomically;
- include existing and pending exposure;
- model concentration, sector/underlying correlation, leverage, liquidity, price bands, freeze quantity, gap risk, and options Greeks;
- support daily loss, weekly loss, drawdown, per-trade, portfolio, sector, strategy, instrument, leverage, and margin limits;
- distinguish hard blocks, warnings, approvals, and time-bounded overrides;
- record all evaluated inputs and policy versions;
- fail closed if risk data, account data, quote, calendar, or instrument mapping is unavailable;
- expose a kill switch and cancel-all action;
- never treat an exception as permission to trade.

Use scenario tables rather than one “risk meter”. Include gap moves, volatility shocks, correlation spikes, spread widening, liquidity loss, and liquidation horizon.

Unify configuration names, units, and semantics across CLI, web, desktop, Docker, and tests. Use a strict enum for Observe/Simulate/Execute; reject unknown mode values.

Risk must consume reconciled account state. A partial or stale portfolio snapshot cannot silently become zero exposure. Closing orders may be allowed under a separately defined degraded-mode policy, but new exposure must remain blocked.

## Market data and Indian-market correctness

Create a central data quality and provenance policy:

- live broker/licensed data for live execution;
- delayed public sources for research only;
- cache/disk data for reproducible offline analysis;
- proxy estimates clearly labeled and excluded from live decisions;
- no silent downgrade from live to delayed/proxy;
- stale or incomplete data blocks Execute mode.

Create a versioned instrument and contract-master service for NSE, BSE, and NFO. Handle effective dates, corporate actions, contract changes, lot-size changes, expiry changes, strike/tick rules, freeze quantities, price bands, settlement, and broker token mapping.

Create a central exchange-calendar service for holidays, special sessions, settlement days, expiry schedules, and session states. Do not encode a permanent weekday/hour rule.

For streaming:

- reconnect with backoff;
- track sequence numbers or gap detection;
- resubscribe;
- resync from a snapshot;
- use bounded queues and backpressure;
- provide Last-Event-ID or equivalent resume semantics;
- isolate streams per authenticated user/workspace;
- never expose a global stream of portfolio or alert data.

For options:

- use current contract metadata;
- model bid/ask, stale chains, missing strikes, discrete dividends where relevant, exercise/settlement, margin, assignment, IV smile, skew, and term structure;
- state GEX convention, units, data coverage, and assumptions;
- do not use the underlying LTP as the option premium;
- do not assume a universal expiry weekday;
- make unsupported contracts abstain rather than guess.

For news and sentiment:

- persist source, publisher, URL, article ID, publication and ingestion times, language, entities, event type, duplicate cluster, credibility, model/version, and confidence;
- distinguish reported fact, market reaction, and model inference;
- protect against prompt injection in all external content;
- do not make causal claims from keyword polarity.

## AI, agents, and model governance

Preserve the useful multi-agent design but make it evidence-first and bounded.

Every analyst must return a typed result containing:

- conclusion or abstain;
- horizon;
- evidence IDs;
- data context;
- assumptions;
- invalidation conditions;
- risks;
- uncertainty interval or calibrated probability where justified;
- model/provider/version;
- timestamp and validity window;
- reason for insufficient data or disagreement.

The synthesizer must return:

- bullish evidence;
- bearish evidence;
- unresolved disagreements;
- base/bull/bear scenarios;
- assumptions;
- catalysts;
- invalidation;
- confidence with coverage and calibration context;
- freshness deadline;
- explicit abstain state.

The deterministic policy layer decides what actions are permitted. An LLM cannot:

- bypass a risk block;
- invent a broker symbol, price, lot, expiry, or quote;
- convert prose into an executable order without schema and policy validation;
- override account selection;
- treat an external source as an instruction;
- claim a backtest is historical when it is proxy-based.

External documents, search results, news, tool results, and user-generated strategy code are untrusted. Separate instructions from data, use strict schemas, sanitize active content, cite sources, and test prompt injection.

Add model governance:

- model/provider registry;
- prompt/template versioning;
- token and cost budgets;
- per-request timeouts;
- model fallback policy that never silently lowers safety;
- prompt/tool/output traces with redaction;
- deterministic fixtures and regression corpus;
- evaluation for grounding, tool selection, citation completeness, numerical correctness, risk refusal, hallucinated contracts, prompt injection, context compaction, latency, and cost;
- calibrated confidence and reliability curves;
- drift and quality monitoring;
- reproducible run manifests.

Use only supported provider APIs or documented local models. Do not restore unofficial subscription/session APIs.

## Quant, ML, DCF, and backtesting

### Technical and fundamental analysis

Treat thresholds as configurable hypotheses, not universal truths. Add sector-relative normalization, liquidity filters, missing-bar and corporate-action handling, parameter provenance, regime labels, and “which evidence changed the score?” explanations.

### DCF

Show WACC, risk-free rate, ERP, beta, debt, tax, terminal growth, growth, margin, reinvestment, and share-count assumptions. Provide sensitivity ranges and a heatmap. Flag terminal-value dominance. Separate market-implied assumptions from analyst assumptions. Use appropriate bank/NBFC methodology. Never present a single point estimate without its uncertainty and assumptions.

### ML

Implement point-in-time feature joins, availability timestamps, leakage tests, feature lineage, purged/embargoed walk-forward validation where labels overlap, multiple regimes and years, cost-aware targets, calibrated probabilities, no-skill baselines, prediction intervals, abstention, model registry, drift detection, and out-of-distribution checks.

Do not make Kelly sizing authoritative until estimation uncertainty, dependency, drawdown, tail risk, and costs are validated. Use conservative caps and a separate research-only state.

### Standard backtest

The engine must:

- generate signals only from data available before fill;
- use next-bar/tick or a documented intrabar execution rule;
- use actual cash, positions, quantities, and margin;
- model bid/ask, slippage, fees, taxes, impact, latency, rejects, partial fills, and liquidity;
- handle corporate actions, delistings, survivorship bias, and exchange calendar;
- close open positions with their actual quantity;
- include sensible benchmarks and risk-adjusted metrics;
- separate in-sample, validation, and out-of-sample;
- report exposure, turnover, trade count, drawdown duration, tail loss, capacity, and confidence intervals;
- preserve data manifest, code hash, parameter hash, engine version, and run ID;
- never silently swallow exceptions.

### Options backtest

Use historical option-chain snapshots or label any reconstructed spot/volatility estimate as Indicative proxy. Include the label in the UI, API, PDF, and export. Model contract lifecycle, lot changes, expiry/calendar, bid/ask, margin, assignment/settlement, costs, latency, partial fills, and multi-leg execution.

Prevent proxy results from silently entering live recommendations.

## Strategy builder and code safety

Prefer a declarative strategy DSL with an audited vocabulary. If Python execution is unavoidable, use an isolated worker with:

- no broker credentials or secrets;
- read-only versioned input data;
- restricted filesystem;
- no network by default;
- CPU, memory, process, output-size, and wall-clock limits;
- process termination;
- package allowlist;
- signed/versioned artifacts;
- resource and syscall monitoring where available;
- deterministic replay;
- separate service identity from the API.

AST validation may be a usability check, not the security boundary.

Require generated strategies to pass schema/type checks, unit/property tests, no-lookahead tests, liquidity/sample-size checks, out-of-sample and walk-forward tests, cost/slippage sensitivity, parameter perturbation, benchmark comparison, and risk-policy compatibility. Require human approval before live enablement.

Cache by strategy/code hash, parameters, data manifest, calendar, engine version, and model/provider version. Preserve prior versions.

Remote strategy import is a combined SSRF, supply-chain, and code-execution boundary. Do not fetch an arbitrary URL directly from the API process. Resolve packages through an allowlisted registry or isolated downloader, validate size/content/signature/license/provenance, scan the artifact, and execute only in the sandbox.

## Portfolio accounting, charges, reconciliation, and audit

Build a canonical accounting layer before treating portfolio/risk screens as authoritative:

- store broker-reported cash, collateral, free margin, used margin, holdings, positions, orders, fills, and charges as immutable source snapshots;
- maintain an internal ledger of reservations, cash movements, fills, fees, taxes, transfers, corporate actions, and adjustments;
- reconcile internal and broker states by account and instrument;
- preserve and display discrepancies rather than silently selecting or summing values;
- distinguish account equity, free cash, collateral, blocked margin, gross exposure, net exposure, realized P&L, unrealized P&L, and day P&L;
- mark every portfolio result complete, partial, stale, reconciling, failed, or disputed;
- show missing or failed brokers/accounts;
- use Decimal and explicit rounding for authoritative money calculations;
- use the contract master for option expiry and all Greeks;
- represent missing Greeks as unavailable, never zero;
- prevent holdings and positions from being double counted.

Create an effective-dated Indian transaction-cost engine for the applicable brokerage, STT, exchange charges, GST, stamp duty, SEBI turnover fees, and broker/product-specific charges. Use the same versioned engine for preview, paper trading, backtesting, P&L, and reconciliation.

Separate four records:

1. immutable operational/security audit trail;
2. broker/accounting ledger;
3. user trade journal;
4. research/model evaluation memory.

Do not automatically reweight analysts from small, selected, binary WIN/LOSS outcomes. Evaluate with time-aligned returns, horizon, benchmark, costs, confidence intervals, and selection-bias controls.

## Regulatory applicability and market-data rights

This is an engineering control plane, not legal advice.

At the review date, the official SEBI implementation extension states that the retail-algo framework applies to all stock brokers from 1 April 2026:

https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf

The NSE implementation standards describe controls including static-IP mapping, daily API-session logout, order-rate thresholds, algo identifiers/tagging, user traceability, OAuth/2FA, security requirements, hosted-server requirements, restricted order/instrument policy, kill controls, and audit retention:

https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf

Do not hardcode a circular value as permanent truth. Build an effective-dated compliance registry containing jurisdiction, exchange, segment, broker, product role, client type, effective interval, rate limit, IP/API-key mapping, algo ID, allowed/restricted actions, authentication/session controls, retention, owner, legal interpretation, broker confirmation, evidence, test, and exception.

The application-wide IPv4 DNS monkeypatch is not proof of compliant static egress. Replace it with deployment-level fixed egress, startup/pre-trade public-IP attestation, broker-side mapping verification, and targeted network configuration.

Market-data rights must be enforced by intended use. Use the official NSE policies as primary inputs:

- https://www.nseindia.com/static/market-data/nse-data-policy
- https://nsearchives.nseindia.com/web/mediaattachment/2026-03/Non_Display_Policy_20260323164430.pdf

Track provider agreement, dataset class, display/non-display use, automated decision support, portfolio/risk use, derived data, redistribution, user/device/site/geography limits, retention, model-training/prompt/cache rights, export rights, and revocation. Block a production use case whose entitlement is absent or expired.

For multi-user or commercial deployment, perform an applicability review against the Digital Personal Data Protection Rules, 2025 and determine whether the product is a personal tool, research/advisory product, broker integration, or algo provider. Link each conclusion to qualified counsel, broker/exchange confirmation, owner, effective date, control, and test.

## UX and frontend

Create one design system shared by web, desktop, TUI, and CLI. Recommended navigation:

1. Home / Morning Brief
2. Research
3. Watchlists
4. Strategy Lab
5. Portfolio and Risk
6. Orders and Execution
7. Alerts
8. Trade Journal / Memory
9. Settings / Connections / Audit

Every surface must show mode, account, broker role, market session, data source, freshness, environment, sync state, loading state, and error state.

### Decision card

Show recommendation or abstain, horizon, timestamp, calibrated uncertainty, current data age, bull case, bear case, invalidation, catalysts, risks, analyst disagreement, evidence links, sizing range, risk-policy result, and what would change the view.

### Order ticket

Before confirmation, show exact account and mode; canonical instrument and broker token; side, product, order type, quantity, lot count, limit/trigger, validity; bid/ask and quote age; notional, margin, fees, taxes; worst-case and scenario loss; all spread legs; protection status; risk results; maximum allowed quantity; idempotency/correlation reference; and an explicit irreversible-action confirmation.

Use progressive disclosure, not hidden safety information. Pair colors with text/icons, support keyboard navigation and a command palette, provide contrast and reduced motion, and make live updates screen-reader friendly.

Telegram must be read-only and authenticated by default. Any future chat approval must use a short-lived challenge bound to the complete order intent, account, price guard, expiry, and correlation ID.

For Electron:

- keep node integration disabled;
- enable context isolation and sandbox where compatible;
- use a strict content security policy;
- validate preload/IPC inputs;
- allowlist external URL schemes and domains;
- use random loopback port and one-time sidecar token;
- protect against local sidecar impersonation;
- keep secrets out of renderer storage;
- sign, notarize, and update-sign releases;
- build and test the packaged application in CI.

## API, auth, privacy, and security

Implement:

- Argon2id or bcrypt password hashing;
- durable sessions with expiry, revocation, rotation, and secure cookies;
- CSRF protection for cookie-authenticated mutation;
- strict origin allowlist;
- authenticated and tenant-scoped API, skills, SSE, and report access;
- explicit RBAC for read, simulate, approve, execute, configure, and administer;
- no localhost or no-user bypass except an explicit development profile that cannot be used in production;
- cryptographically random per-attempt OAuth state and nonce, PKCE where supported, exact redirect binding, short expiry, one-time consumption, and initiating-user/account binding;
- daily API-session lifecycle and reauthentication controls where applicable, without storing long-lived sessions contrary to provider rules;
- rate limits, quotas, model spend budgets, and abuse controls;
- tenant/user/workspace/account filters on every repository query;
- secure secret manager abstraction, rotation, and redaction;
- allowlisted credential names;
- no credential-bearing requests to user-controlled URLs;
- SSRF protection through URL allowlists, DNS/IP validation, private-range blocking, and egress policy;
- signed, allowlisted, queued webhooks with retries and timeouts;
- output escaping, safe HTML rendering, CSP, and content-type protections;
- no raw exception strings in user-facing responses;
- audit events for auth, credentials, configuration, risk overrides, order actions, and admin operations;
- data retention, deletion, export, and encryption policy.

Threat-model at least:

- remote unauthenticated client;
- compromised authenticated user;
- cross-tenant request;
- malicious strategy or skill;
- prompt-injected web page/news article;
- malicious webhook destination;
- malicious provider/model URL;
- local process attacking Electron sidecar;
- compromised dependency or CI action;
- broker timeout and replay;
- database/queue compromise.

## Persistence, events, operations, and performance

Replace global dictionaries and ad hoc JSON persistence for domain state with transactional persistence. Use migrations, indexes, constraints, optimistic/pessimistic locking where appropriate, atomic risk reservations, backups, restore tests, and event replay.

Use synchronized clocks, monotonic durations, explicit Asia/Kolkata exchange time, and recorded clock offset. Authentication expiry, quote freshness, order sequencing, audit retention, and reconciliation must not depend on an unchecked host clock.

Metrics must include quote age, fallback rate, stale-data blocks, broker rejects, unknown orders, reconciliation lag, risk blocks, queue depth, job duration, model cost, model latency, alert delivery, auth failures, and webhook failures.

Use correlation IDs and structured redacted logs. Trace client → API → job → policy → broker. Provide dashboards and runbooks for broker outages, data staleness, unknown orders, alert storms, worker failure, and credential rotation.

Starting engineering targets to measure, not claims:

- cached quote p95 under 300 ms;
- broker quote p95 under 1.5 s with source/freshness visible;
- portfolio snapshot p95 under 1 s for a normal account;
- research acknowledgement under 500 ms with a job ID;
- research progress visible within 2 s and refreshed at least every 5 s;
- order preview p95 under 1 s or an explicit blocked/unavailable state;
- bounded broker timeout and no indefinite request;
- reconciliation alarm when the defined lag threshold is exceeded;
- realtime reconnect with snapshot resync.

Use async I/O, connection pools, bounded workers, batching, caching with provenance, duplicate-request coalescing, backpressure, job cancellation, and database indexes. Measure before and after with realistic concurrency and provider limits.

## Testing and delivery gates

Add all of the following:

1. Unit tests for domain rules, risk, instruments, calendars, pricing, costs, and state transitions.
2. Broker contract tests using fake and recorded fixtures.
3. Deterministic event and market replay tests.
4. Property tests for quantities, lots, price ticks, risk reservations, and state machines.
5. Integration tests with Postgres, Redis, workers, auth, SSE, report storage, and two-user isolation.
6. Failure injection for submit timeout, duplicate request, partial fill, cancellation race, stale quote, provider outage, restart during transition, corrupt cache, and queue replay.
7. Security tests for auth bypass, cross-tenant access, CSRF, CORS, SSRF, XSS, prompt injection, secret leakage, webhook abuse, and sandbox escape.
8. Backtest tests proving no same-bar look-ahead, realistic quantity/cost treatment, corporate actions, and proxy labeling.
9. Load tests for quote fanout, portfolios, concurrent research, alert storms, worker queues, and reconnects.
10. Frontend accessibility tests for keyboard, contrast, screen readers, and reduced motion.
11. Web production-build, Electron packaging, Docker health, migration, backup/restore, and rollback tests.
12. Dependency, license, secret, SAST, SBOM, and artifact-signature checks.
13. Golden broker-statement reconciliation tests for cash, holdings, positions, margin, P&L, fills, taxes, and fees.
14. OAuth transaction tests for wrong state, replay, wrong user, expiry, parallel login attempts, and callback races.
15. Compliance-policy tests for effective dates, applicable order-rate limits, algo IDs, session lifecycle, egress identity, retention, and restricted orders.
16. Data-entitlement tests proving prohibited display, non-display, derived, model, cache, and export uses are blocked.

CI must run formatting, linting, type checking, unit/integration tests, coverage threshold, security checks, frontend build, packaged desktop build, migrations, and artifact verification. Pin third-party action references to immutable commit SHAs. Keep a deterministic fast suite and a full release-candidate suite.

## Phased implementation order

### Phase 0: contain risk

- disable live by default;
- remove confirmation bypass from remote paths;
- fail closed on risk, data, instrument, account, calendar, and broker uncertainty;
- fix auth, sessions, CORS, CSRF, streams, ownership, and raw errors;
- remove arbitrary credential keys, SSRF paths, remote installation, and secret backups;
- disable unofficial providers;
- unify configuration names and strict mode parsing;
- add kill switch and explicit paper/proxy labels.
- remove ambiguous quantity/rupee sizing and require typed units and position intent;
- add secure OAuth transaction binding;
- make a product-role, regulatory, privacy, and data-entitlement launch decision.

### Phase 1: platform foundation

- canonical models and migrations;
- Postgres repositories and account/tenant context;
- Redis/job/event infrastructure;
- secret manager interface;
- OpenAPI contract and generated clients;
- instrument master and exchange-calendar service;
- audit/correlation model;
- canonical accounting, charges, reconciliation, and portfolio-status model;
- effective-dated compliance and data-entitlement registries;
- configuration validation.

### Phase 2: execution correctness

- broker capability contract and adapter tests;
- order intent/state machine/idempotency;
- risk reservations and deterministic policy;
- broker reconciliation;
- multi-leg spread workflow;
- broker-native protection;
- realistic paper simulator.
- explicit open/close/reduce-only semantics;
- applicable static-egress, session, rate, algo-ID, traceability, and retention controls.

### Phase 3: quantitative correctness

- data quality and freshness;
- event-time backtests;
- actual costs, quantities, fills, margin, and contracts;
- historical options data or explicit proxy engine;
- walk-forward/purged validation;
- run manifests, calibration, DCF sensitivity, ML lineage.
- versioned Indian transaction costs and broker-statement reconciliation.

### Phase 4: product polish

- unified design system/navigation;
- Observe/Simulate/Execute UX;
- evidence-first research cards;
- typed agents, abstention, evals, traces, and budgets;
- safe strategy DSL/sandbox;
- hardened Electron;
- read-only authenticated Telegram.

### Phase 5: production operations

- SLOs, dashboards, traces, runbooks, DR;
- horizontal scale and load tests;
- signed releases and SBOM;
- external security review;
- broker certification matrix;
- privacy and retention controls;
- qualified compliance/legal review.

## Acceptance gates

Do not call the system production-ready unless all are true:

- the default deployment cannot submit a live order;
- a live order requires authenticated identity, account, Execute mode, fresh supported data, current mapped instrument, policy approval, idempotency, and user confirmation;
- risk-service failure blocks execution;
- broker timeout becomes Unknown and is reconciled;
- duplicate intent cannot create duplicate broker orders;
- multi-leg failure cannot create unbounded naked exposure;
- all orders, fills, positions, cancellations, overrides, and risk decisions are auditable;
- market data always exposes source, as-of, received-at, freshness, quality, and fallback;
- every portfolio number exposes account, source time, accounting definition, reconciliation status, and missing providers;
- no bare numeric order size is accepted and no close/reduce action can increase exposure;
- AI outputs expose model/version, evidence, timestamp, uncertainty, disagreement, and abstention;
- external content cannot modify tool policy;
- generated code cannot read secrets, unrestricted files, or the network;
- users and tenants cannot access one another’s state;
- secrets are absent from logs, errors, HTML, model context, child processes, and plain backups;
- restart, worker failover, provider outage, broker outage, queue replay, and restore tests pass;
- backtests prove no look-ahead and disclose costs, data limitations, and proxy status;
- API, web, Electron, TUI, and Telegram share canonical mode and data semantics;
- CI verifies types, tests, security, dependencies, builds, migrations, coverage, and signed artifacts;
- documentation matches the exact release and distinguishes implemented, tested, simulated, proxy, licensed, and live-safe capabilities.
- every applicable regulatory and data-license obligation has an effective-dated control, owner, evidence artifact, and automated or documented test.

## Greenfield local-first bootstrap contract

If the user is creating a fresh application rather than modifying an existing checkout, switch to greenfield mode. Do not spend the first implementation cycle trying to reproduce every existing feature. Build a small, runnable vertical slice first, then expand behind stable contracts.

### Default stack

Use these defaults unless the user explicitly chooses otherwise:

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, and Alembic.
- Frontend: React, TypeScript, Vite, and an accessible component/design system.
- Local durable database: SQLite with migrations and transactional repositories.
- Production database: PostgreSQL through the same repository interfaces.
- Local jobs: deterministic in-process job runner with cancellation and bounded execution.
- Production jobs: Redis or a durable queue with separate workers.
- Local market data: seeded synthetic fixtures and replay files.
- Local broker: MockBroker only.
- Local model provider: deterministic stub provider; hosted/local LLMs are optional integrations.
- Reports: local filesystem in development and object storage in production.
- Packaging: Docker Compose plus native scripts for Bash and PowerShell.

If you select a different stack, record the reason, local installation impact, migration path, and equivalent safety guarantees.

### First runnable vertical slice

The first greenfield milestone must include only:

1. a local login or explicitly isolated demo profile;
2. a home screen showing seeded NIFTY/stock data with source, as-of time, freshness, and Simulate mode;
3. a watchlist and research result using deterministic fixtures;
4. a paper order preview;
5. a mock order lifecycle from Draft through Confirmed, Submitted, Filled or Rejected, and Reconciled;
6. a portfolio snapshot with cash, holdings, positions, P&L, and accounting status;
7. an append-only audit event for every order transition;
8. health/readiness endpoints;
9. smoke tests that prove the complete flow after a restart.

Do not implement live broker connectivity, real credentials, public deployment, unrestricted generated code, real-money execution, historical options claims, or autonomous trading in this first milestone.

### One-command local setup

The README must provide a clean Windows path and a Bash path:

- Windows: PowerShell script such as scripts/dev.ps1;
- macOS/Linux: scripts/dev.sh or Make target;
- Docker fallback: docker compose up --build.

The first run must:

- check Python, Node, Docker, and required ports;
- create or migrate the local database;
- generate a local development session secret in an ignored local-data directory;
- seed demo user, watchlist, instruments, quotes, and a paper account;
- start backend and frontend with configurable host/port;
- print exact URLs and demo login instructions;
- require no broker key, LLM key, paid data subscription, Redis, or cloud account;
- expose a single command to run unit and smoke tests;
- preserve local data across restart and provide a clearly named, opt-in reset command.

Use 127.0.0.1 by default. Do not bind a local development server to all interfaces unless the user explicitly enables it. Do not use macOS-only brew, open, osascript, or shell assumptions in the cross-platform core. Put platform-specific behavior behind adapters.

### Configuration contract

Create an explicit environment profile model:

- local;
- test;
- staging;
- production.

Reject unknown profiles and unknown trading modes. The local profile must select MockBroker, seeded/replay data, Simulate mode, local SQLite, in-process jobs, redacted logs, and loopback binding. Production must require explicit secrets, external durable services, supported broker configuration, secure origins, live feature flags, and an operator kill switch.

Provide:

- a complete .env.example with safe values only;
- typed settings validation at startup;
- one documented name for each setting;
- no secret values in the repository;
- provider configuration as optional extras or lazy-loaded adapters;
- a preflight command that reports missing or unsafe configuration without printing secret values;
- a configuration reference generated from the typed settings model.

### Local quality gate

The greenfield application is not runnable until a clean machine or clean container can:

1. copy the repository;
2. run the documented setup command;
3. open the web application;
4. see seeded data and mode labels;
5. run research without an LLM key;
6. preview and simulate a paper order without a broker key;
7. restart the services and see durable state;
8. run the smoke suite successfully;
9. prove that no outbound broker order or credentialed provider request occurs.

Stop after this vertical slice and report the exact files, commands, screenshots or HTTP checks, test results, and remaining work. Only then proceed to the broader architecture phases.

## Required output from you

For each work session, respond in this order:

1. Executive summary of what you found.
2. Exact commit and working-tree status.
3. Blocking decisions or explicit assumptions.
4. P0/P1/P2 findings with source files and acceptance tests.
5. Architecture decision records for material choices.
6. Regulatory/product-role and market-data entitlement matrices.
7. Phased implementation plan with dependencies.
8. Files changed and why.
9. Tests added and commands/results.
10. Security, accounting, regulatory, licensing, and operational impact.
11. Known limitations and remaining risks.
12. Next smallest safe step.

When implementing, make small coherent changes, run relevant tests after each change, and show the evidence. Never say “complete” while a P0 issue remains. If a requirement cannot be safely implemented, explain the blocker and keep the system in the safer state.

## Final product standard

The finished application should answer, for every displayed number and attempted order:

> Which user and account? Which exact instrument? Which source and timestamp? How fresh and complete is the data? Which assumptions and model versions were used? Which risks were evaluated? Which policy allowed or blocked it? Which user approved it? What did the broker actually acknowledge or fill? What happens if the next call, worker, process, or provider fails?

That chain of evidence, policy, execution, and recovery is the definition of world-class for this product.
