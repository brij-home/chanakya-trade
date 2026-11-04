# ChanakyaTrade system review and implementation plan

Knowledge cutoff: 30 October 2026. Repository inspection and local verification: 31 October 2026 IST.

Audited baseline: main, commit 82114d06c38c8a8f297fa3e7a48b6ac91787e8ab. This is a dated review supplement to the September implementation plan in the parent directory. It does not authorize deployment, live order placement, or automatic execution of the phases below.

The platform has useful foundations: a server generated order preview and confirmation hash, atomic single-row submission claims, explicit unknown-order states, a provider-verified derivative registry, an independent reconciliation interface, bounded streaming queues, and substantial backend and frontend tests. The verified failures below nevertheless prevent an institutional live-execution readiness claim. Statistical superiority cannot be established from feature breadth, terminology, or passing implementation tests.

The recommended sequence is to repair authority boundaries and accounting, establish trustworthy market data, validate strategy economics, and then expand capabilities. Several current invariants and regression tests preserve outdated assumptions. Updating those instructions is part of the engineering work.

## Review scope and evidence strength

Reviewed paths include execution, broker routing, pretrade validation, reconciliation, transaction costs, instrument and expiry resolution, settlement risk, quote/depth/options fallbacks, backtesting, detector governance, alert outcomes, LLM orchestration, authentication, maintenance routes, persistence, SSE, the order ticket, CI, dependency setup, and representative tests.

This is a broad architectural review with deep tracing of selected critical paths. It is not a line-by-line audit of every module, a penetration test, a broker certification, or a validation of private trade history.

Evidence labels:

- Reproduced: exercised in a separate process using temporary storage, blocked networking, and fake broker objects.
- Code confirmed: the relevant implementation and caller establish the failure path; no live financial action was performed.
- Design risk: a missing guarantee or evaluation gap requiring the acceptance tests specified below.

All line references below refer to the audited commit. Production files remain unchanged. The accompanying probes.py and evidence.json make selected findings reproducible. The probes never use real broker orders.

## Verification results

| Check | Observed result | Interpretation |
| --- | --- | --- |
| Targeted execution, charges, reconciliation, auth, instrument, backtest and governor suites | 119 passed in 10.27 seconds | Existing behavior is internally consistent in those tests |
| Expiry mandate and real FNO backtest suites | 7 passed in 1.21 seconds, 10 pandas deprecation warnings | Passing expiry assertions include obsolete exchange weekdays |
| Four frontend provenance, market data, component and alerts suites | 73 passed in 70.22 seconds | Representative frontend tests pass; this is not full UI coverage |
| Isolated failure probes | Completed with exit code 0 | Confirmed failures are summarized below |
| Python dependency check | Failed | Fyers has missing dependencies and an incompatible requests pin |
| Fyers WebSocket import | Failed with missing pkg_resources | Top-level SDK import success does not establish streaming readiness |
| npm lockfile audit on 31 October | 24 advisories: 20 moderate, 4 high | Current registry observation; no claim about historical advisory publication dates |
| Earlier local application smoke check | API health 200, PAPER mode, desktop window rendered | Liveness does not establish broker readiness or safe order semantics |

The backend total is 126 passing tests across the selected suites, and the frontend total is 73 passing tests. No full-suite, full-load, exchange mock-session, or real-order execution result is claimed.

~~~powershell
.venv\Scripts\python.exe -m pytest tests/test_charges.py tests/test_order_lifecycle.py tests/test_live_oms_p3b.py tests/test_reconciliation_typed.py tests/test_reconciliation_unavailable.py tests/test_auth_security.py tests/test_canonical_instruments.py tests/test_backtest.py tests/test_detector_circuit_breaker.py -q -p no:cacheprovider --tb=short

.venv\Scripts\python.exe -m pytest tests/test_sebi_expiry_mandate_invariants.py tests/test_options_backtest_real_fno.py -q -p no:cacheprovider --tb=short

# Run from macos-app
npx vitest run src/__tests__/provenance.test.js src/__tests__/realtimeMarket.test.jsx src/__tests__/componentRenders.test.jsx src/__tests__/alertsView.test.jsx --maxWorkers=1
~~~

## Priority and release policy

P0 means a blocker for the affected live or network-exposed deployment path. P1 means material trading, research, integration or reliability correctness work. P2 means quality and scalability work after the principal correctness gaps are closed. A P0 finding in a live path does not mean the local PAPER desktop was observed sending a real order.

| ID | Priority | Finding |
| --- | --- | --- |
| F01 | P0 | CLI and emergency execution can bypass the central mode and order authority |
| F02 | P0 for network hosting | Maintenance and diagnostic routes bypass authentication and CSRF |
| F03 | P1 | Derivatives transaction taxes are obsolete and lack effective dates |
| F04 | P0 for expiry and close trading | Expiry, session and physical-settlement logic has stale calendars and unsafe defaults |
| F05 | P0 | Multi-step database operations assume transactions that the pool does not provide |
| F06 | P0 | Pretrade callers and gates use incompatible segment names and incomplete context |
| F07 | P0 | Internal positions and cash are derived from order intentions across accounts |
| F08 | P0 | Sliced and basket orders can lose partial exposure and submission evidence |
| F09 | P0 | Protective exits are not reliably established after asynchronous fills |
| F10 | P1 | Confirmation and no-chase protection do not bind the complete execution decision |
| F11 | P0 for signal publication | Mode and provenance are conflated; synthetic chains and depth enter market pathways |
| F12 | P1 | The basic SMC backtest is noncausal and its default signal is unreachable |
| F13 | P1 | Backtest pricing, costs and provenance are insufficient for execution or alpha claims |
| F14 | P1 | Detector learning treats assumptions and duplicate outcomes as empirical evidence |
| F15 | P1 | Fixed reward targets and heuristic confidence cannot establish economic edge |
| F16 | P1 | The UI invents protection levels and duplicates contract specifications |
| F17 | P1 | LLM timeout wrappers do not enforce their stated wall-clock deadline |
| F18 | P1 | Alert persistence and delivery lack a durable common commit and replay protocol |
| F19 | P1 | Tests can preserve business errors and conceal production lifecycle defects |
| F20 | P1 | Optional broker dependencies and bootstrap readiness are inconsistent |
| F21 | P2 | Large domain modules and synchronous administrative work increase failure coupling |
| F22 | P1 before live expansion | Broker capability and regulatory qualification need explicit deployment gates |

## Findings and root causes

### F01 Unify every execution origin and repair emergency semantics

Evidence: app/repl.py:2473–2510; app/commands/trade.py:229–280; engine/trade_executor.py:286–455; brokers/session.py:376–383; engine/order_lifecycle.py:2493–2677.

Code confirmed: the REPL checks a string named LIVE to choose its warning, then calls get_execution_broker().place_order directly after a generic confirmation. The broker selector returns the configured execution broker or primary broker and does not choose PaperBroker based on runtime mode. Several strategy and CLI paths also call broker placement outside the lifecycle. Audit-after-placement is not equivalent to persisting a confirmed intent before placement.

Reproduced: emergency_flatten_all_positions in SIMULATE called a fake execution broker once. The fake returned REJECTED, yet the function returned SUCCESS and counted one flattened position. The emergency path reads mode for reporting but does not enforce mode before cancellation, native exit, or counter-orders. It also marks pending internal rows CANCELLED without proving cancellation and can issue counter-orders after a native exit request before fills have settled.

Root cause: broker selection, trading mode and financial mutation are enforced by individual entrypoints instead of one unavoidable authority. Emergency logic treats requests as completed outcomes.

Implementation: make the mutation-capable adapter reachable only through one order authority. Route CLI, REPL, strategies, agent tools, UI and emergency operations through it. The emergency coordinator must distinguish cancel requested, cancel confirmed, reduction submitted, partially filled and verified flat. Apply the entry lock before starting cancellation. Reconcile native exit responses before any residual counter-order. Preserve unresolved orders rather than rewriting them as cancelled. Emergency reduction can have a dedicated risk-reducing policy, but mode, account, quantity, idempotency and immutable evidence still apply.

Acceptance: in OBSERVE, every origin produces zero mutations; in SIMULATE, a connected real broker still receives zero calls. A rejected close is never counted as flat. Repeated emergency requests, delayed native exits and partial fills cannot reverse a position. No production broker placement call may bypass the authority.

### F02 Protect administrative routes before network hosting

Evidence: web/api.py:495–556 and 1402–1564.

Code confirmed: the authentication middleware excludes all /api/maintenance and /api/diagnostics paths before self-hosted authentication and CSRF checks. The excluded endpoints include circuit-breaker reset/probe, incident clearing, purge and synchronization. Several handlers have no separate auth dependency.

Root cause: a prefix allowlist intended for health and onboarding grew to include state-changing administration.

Implementation: replace prefixes with explicit route policy. Expose minimal liveness publicly; require authenticated administrator capability and CSRF for maintenance mutations. Redact secrets and account identifiers in diagnostics. Use a scoped local desktop capability token, strict Origin/Host checks and explicit proxy trust rather than treating all loopback traffic as authorized. Keep onboarding public only for the minimal initial-account operation.

Acceptance: enumerate every route and assert unauthenticated denial for all administrative writes under self-hosted mode. Test CSRF, local-browser origins, proxy headers and role restrictions. Use fake maintenance services so denial tests cannot purge real data. Circuit resets must append an audit record.

### F03 Make charges effective dated and exchange specific

Evidence: engine/charges.py:91–195; tests/test_charges.py:63–112.

Reproduced: a sell turnover of Rs 100,000 produces futures STT of Rs 20 and options STT of Rs 100. For eligible securities derivatives on 30 October 2026, the corresponding revised STT amounts are Rs 50 and Rs 150. The official schedule changed from 1 April 2026. The charge function takes neither trade date nor an exercise event. Existing tests explicitly expect the old rates.

Root cause: a function described as effective-dated contains one static rate set. Exchange, broker plan and settlement event are not full inputs.

Implementation: introduce versioned charge schedules with effective_from/effective_to, venue, segment, side and event type. Model option exercise on intrinsic value separately from premium sale. Carry brokerage plan, statutory rounding and settlement charges explicitly. Use the same evaluator for preview, paper, backtest and realized fill accounting, with the historical trade date. Reconcile line items against anonymized contract notes before promotion.

Acceptance: golden examples straddling 31 March/1 April 2026; options sale versus exercise; BSE/NSE/MCX/CDS scope; charge rounding; partial fills; brokerage caps; repeated fill aggregation. Historical simulations must retain historical schedules.

Source: [NSE STT schedule](https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax), updated 1 April 2026.

### F04 Resolve expiries sessions and settlement from effective rules

Evidence: engine/alert_model.py:37; market/calendar.py weekly/monthly helpers; engine/alert_expiry.py:660–712; market/instruments.py:560–579; engine/eod_rebalancer.py:263–320; engine/position_sizer.py:795–817; config/constants.py market close definitions; engine/pretrade.py:173–237; tests/test_sebi_expiry_mandate_invariants.py:43–90; AGENTS.md invariants 4, 37 and 43.

Code confirmed: multiple authorities still encode NIFTY Thursday and SENSEX Friday, and the tests require October 2026 NSE monthly expiry to be 29 October. The exchange transition in September 2025 moved NSE expiry to Tuesday and BSE expiry to Thursday, subject to contract and holiday rules. A single weekly index per exchange is a different rule from the weekday of its expiry.

Reproduced: the settlement audit uses int(pos.get('days_to_expiry', 4) or 4), so an explicit zero becomes four. An ITM stock call supplied at zero DTE was assessed at four DTE with a 20% margin rate and ELEVATED_MARGIN status. Missing lots default to 250 and missing metadata to estimated values. The sizing discount has a one-lot floor, so halving a one-lot position still leaves one lot.

Code confirmed: a general 15:30 close and a 15:15–15:30 MOC window do not model the current closing-auction structure. As of the cutoff, NSE distinguishes eligible cash stocks' CAS from 15:15–15:35, other cash stocks' continuous trading to 15:30, and equity derivatives trading to 15:40. Indicative auction values cannot be treated as continuous-trade fills. See the [NSE session specification](https://www.nseindia.com/static/products-services/closing-auction-session).

Known future change, not current behavior: the [15 October 2026 SEBI circular](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792079571420.pdf) schedules most revised CAS/session/settlement rules for 7 December 2026 and the specified unexecuted-order transition provisions for 8 February 2027. Policies must distinguish announcement, effective date and historical applicability.

Root cause: historical weekday rules and rough settlement safeguards have been promoted into permanent institutional requirements. Missing metadata is replaced by plausible defaults.

Implementation: resolve listed contract expiry, settlement type, lot, tick, last trading session and broker cutoffs from versioned exchange and broker records. Model continuous, transition, auction collection, random close, matching and post-close phases per instrument. Distinguish last trade, indicative equilibrium, official close and final settlement values throughout data, scanners, fills and backtests. Treat unavailable metadata as unavailable. Preserve zero DTE. Use the holiday-adjusted listed contract, not a generic last-weekday calculation. Calculate actual delivery obligation, available shares/cash and broker margin schedule by side and moneyness. Allow zero lots when a risk budget cannot fund one lot. Review both calls and puts, futures, long and short positions, and neutral spreads.

Acceptance: exchange circular fixtures spanning changes; actual October contract examples; holiday shifts; DTE zero; missing fields; exactly one lot; long ITM call cash requirement; short call delivery; put obligations; intra-day and next-month rollovers; CAS versus non-CAS cash stocks; indicative versus executed auction prices; broker-specific MIS cutoffs; 7 December and 8 February activation boundaries. Historical tests must use the contract and session specifications applicable at their historical date.

Sources: [NSE expiry transition circular](https://nsearchives.nseindia.com/content/circulars/FAOP68685.pdf), [BSE circular reference](https://www.bseindia.com/markets/MarketInfo/DispNewNoticesCirculars.aspx?page=20250617-11), and [broker announcement linking both exchanges](https://zerodha.com/marketintel/bulletin/417370/revision-in-expiry-day-of-index-and-stock-derivatives-contracts). BSE blocked automated retrieval; the broker announcement corroborates its linked circular.

### F05 Repair transaction boundaries and concurrent audit appends

Evidence: engine/db_pool.py:58–65 and 71–133; engine/order_lifecycle.py:1727–1741; engine/security_audit.py:136–160.

Reproduced: a first write using the pool survived rollback after a second write failed. Connections run in autocommit mode. The batch lifecycle updates each order separately and then calls commit without first beginning a transaction. Therefore its multi-row claim is not atomic. The existing single-row conditional UPDATE remains atomic; the defect concerns operations spanning multiple statements.

Code confirmed design risk: audit append reads the latest hash and inserts the next record without a writer transaction or serialization. Concurrent writers can read the same head. The pool also returns connections after exceptions without a generic transaction rollback policy.

Root cause: connection pooling is being used as if it were a transaction unit of work.

Implementation: provide separate read contexts and explicit write transactions. Use BEGIN IMMEDIATE for serialized SQLite writer operations, rollback on failure, and never hold database transactions across broker or LLM calls. Commit intent/state/event/outbox changes together in the same domain database. Treat a global audit database as a durable outbox projection, or consolidate the required audit records; independent commits across WAL databases do not become one transaction. Serialize hash-chain appends inside the same transaction; retain signed external checkpoints if tamper evidence beyond the local process is required. Choose stronger durability settings for money records based on a measured crash and power-loss policy.

Acceptance: force failure at every batch claim index and prove all-or-none changes; two concurrent appenders; process crash before/after intent and outbox commit; pool reuse after exception; integrity checks after restart. Do not interpret commit() in autocommit mode as a transaction boundary.

### F06 Pass one complete typed pretrade context

Evidence: engine/order_lifecycle.py:319–350, 1260–1273 and 1793–1808; engine/pretrade.py:173–237, 240–280, 314–372 and 608–758; market/instrument_master.py:128–137.

Reproduced at Friday 30 October, 18:00 IST: the session gate rejects EQ but passes OPTIONS and FUTURES as unknown segments. Those are the names passed by the order lifecycle. Default lot validation accepts one option unit. The OPT buying-power helper accepts a Rs 100,000 premium purchase with Rs 20,000 cash because it applies a generic 15% multiplier. This last probe exercises that helper directly; the canonical OPTIONS caller takes another branch, which illustrates the naming inconsistency rather than proving this exact multiplier applies to every order.

Code confirmed: the live caller omits authoritative lot/tick, broker/user/strategy, previous close, portfolio value and daily P&L. It gets a verified derivative record for venue classification but does not propagate all contract attributes. The verified-contract getter does not check expiry or verified_at freshness. Cash-equity fallback accepts a nonexistent symbol as ACTIVE and tradable.

Root cause: string aliases, permissive defaults and optional safety context make gate coverage depend on the caller.

Implementation: define one Segment enum and one immutable PretradeContext carrying account, broker, strategy, instrument version, units, side, order kind, live quote timestamps, circuit bounds, actual margin result and portfolio reservations. Required evidence cannot be omitted for live orders. Fail on unknown segments and invalid contracts. Broker margin APIs must distinguish bought premium from short-option/futures margin. Reserve buying power across simultaneous intents and all legs. Risk-reducing orders need an explicit separate policy.

Acceptance: test the actual HTTP-to-authority-to-gates boundary with call spies, not only gate helpers. Cover every segment alias, exchange holiday, expired/stale contract, quantity remainder, dynamic tick, missing account risk, broker-specific kill switch, competing intents and short-option margin.

### F07 Build reconciliation from immutable fills scoped to an account

Evidence: engine/order_lifecycle.py:176–259, 2198–2264 and 2267–2354.

Reproduced: two independently named cash baselines both consume the same global filled-order row and report identical positions and cash. Order rows contain no execution-account column used by this query.

Code confirmed: the snapshot takes the order's requested quantity and preview price as executed quantity and price. PARTIALLY_FILLED rows are also counted with the full requested quantity. State synchronization logs a fill quantity in an event but does not build an execution ledger with actual prices, fees and trade IDs. Short-cover and cross-zero average-cost calculations are not a complete position accounting model.

Root cause: intentions and aggregate statuses are being used as financial facts.

Implementation: persist immutable executions keyed by broker/account/exchange trade ID, incremental quantity, actual fill price and event time. Maintain account cash movements, opening positions, corporate actions, transfers, settlement obligations and charge adjustments. Project positions/P&L from those facts. Reconcile independently with broker orders, trades, positions and funds, with account-specific checkpoints and explicit timing tolerances. Preserve manual/external broker fills as separately sourced facts.

Acceptance: 30/100 partial fill, multiple prices, duplicate/out-of-order fills, short-cover/cross-zero, two accounts sharing an order ID, deposits/withdrawals, holdings baseline, costs and trading-day rollover. Replaying the same input events twice must give identical positions and cash. A clean report requires independent complete inputs.

### F08 Persist each child order and resolve uncertain submissions

Evidence: engine/order_lifecycle.py:1034–1082, 1471–1553, 1614–1905 and 2267–2354.

Code confirmed: sliced execution can fill earlier tranches and mark the parent REJECTED when a later tranche rejects. Successful child IDs are combined into a SLICED string, while order synchronization compares stored IDs directly with broker IDs. A timeout can replace the parent's broker ID with None even after earlier child submissions.

Basket execution sorts BUY before SELL, then submits one broker basket. Sorting requests alone does not establish that protective buys filled before shorts. Batch request construction also omits the trigger_price populated on single-order requests. A local multi-row claim, even after F05 is fixed, cannot make exchange/broker multi-leg fills atomic.

Root cause: parent intent status is overloaded to represent several independently executing orders, and broker acceptance is treated as strategy completion.

Implementation: introduce parent strategy, child intent and submission-attempt records. Persist each child before transmission with a stable broker correlation tag and retain every response. Aggregate accepted, filled, rejected and unknown quantities. Execute required hedges to the specified fill milestone before sending dependent shorts, with a bounded residual-risk budget and a recovery policy. Reconcile unknown attempts against broker trade/order histories before any resend.

Acceptance: child one fills and child two rejects; timeout after any child; empty success ID; partial basket response; reordered responses; disconnect after exchange acceptance; crash before response persistence; derivative stop orders in baskets; hedge acknowledgement without fill; hedge fill then short rejection. The system must never report zero exposure because a later child failed.

### F09 Make protective exits part of the fill lifecycle

Evidence: engine/order_lifecycle.py:1340–1418 and 2267–2354; brokers/fyers.py:2153–2227.

Code confirmed: live GTT auto-arming occurs only when place_order immediately reports COMPLETE. The Fyers adapter normally returns OPEN for an accepted placement. Later synchronization updates status but does not establish protective exits. GTT arming failure is only logged. Accepted response handling does not require a nonempty broker ID before marking OPEN/FILLED.

Root cause: protection is a side effect of synchronous placement rather than a durable obligation derived from fills.

Implementation: model protection required, protection pending, active, degraded and resolved. Create/resize exits from reconciled incremental fills, verify broker acknowledgement, and reconcile every protection child on restart. Use a broker capability matrix for GTT, OCO, exchange stops and segment/product limitations. Define what happens when protection cannot be placed, without silently implying coverage. Keep stop-limit gap risk visible.

Acceptance: OPEN then partial then full fill; duplicate updates; protection rejection; unsupported GTT; disconnect while arming; user cancellation; reduce-only exit sizing; OCO double-trigger races; partial target exits; restart with an unprotected fill. Broker acceptance is distinct from execution, as documented in [Kite order APIs](https://kite.trade/docs/connect/v3/orders/).

### F10 Bind confirmation to the account and complete policy

Evidence: engine/order_lifecycle.py:510–518, 739–810, 919–948, 1244–1255 and 1786–1792.

Code confirmed: the preview hash binds the main order fields and trigger, but omits account identity, stop/target/protection policy and reference-data/policy versions. Confirmation has a preview TTL, but execution does not revalidate a separate confirmed-intent expiry. The broker/account can be selected again at execution.

The no-chase readers inspect d['charges']; rows loaded from SQLite carry charges_json. That makes persisted policy unavailable to these readers. A visual client guard cannot substitute for this missing server policy.

Root cause: the preview is a price-shaped string rather than a versioned execution decision.

Implementation: canonicalize a typed decision envelope containing account, venue/contract ID, quantity units, all legs and exits, order kind, policy version, source quote version and expiry. Hash and persist it; bind confirmation to the actor and envelope. Revalidate time, mode, account and policy immediately before the atomic submission claim. Decode JSON through one serializer. A hash does not grant authorization by itself.

Acceptance: same idempotency key with a changed stop, account, trigger or leg must conflict; stale confirmation must require a new preview; no-chase survives persistence and restart; broker switching invalidates the confirmation; malformed stored policy is rejected.

### F11 Separate execution mode from data provenance

Evidence: market/options.py:450–495 and 531–637; market/order_book.py:929–962.

Code confirmed: synthetic option fallback is allowed in PAPER/SIMULATE, empty mode, or absent broker. It contains fallback index anchor prices and deterministic fabricated OI, OI change and volume. The builder returns the same contract shape without mandatory per-contract provenance. A local telemetry source label does not guarantee downstream eligibility checks.

The order-book fallback derives equal bid/ask quantity from 5% of session volume, or uses 50. It can label that result LIVE_STREAM_L1/CACHED_L1. Session cumulative volume is not resting queue size; the manufactured quantity can bias liquidity and fill estimates.

Root cause: paper execution is treated as permission to fabricate research inputs, and a quote is upgraded into depth information it does not contain.

Implementation: distinguish execution_mode from data_origin and quality. Allow synthetic datasets only under an isolated demo/scenario namespace; they cannot qualify publication, empirical learning or execution. Every quote/chain/depth row must carry provider, exchange timestamp, receipt timestamp, quality, completeness and modeling status. Missing L1 quantities remain null; L2-only metrics are unavailable without genuine L2 evidence. Partition caches by source class and contract version.

Acceptance: real and paper modes with failed providers produce UNAVAILABLE/DEGRADED, not synthetic chains. Test/demo data cannot enter alerts, Telegram, journals, learning stores or real-market performance reports. Zero manufactured quantities may influence sweep VWAP, OBI, liquidity or sizing.

### F12 Repair the causal SMC signal before evaluating it

Evidence: engine/backtest.py:789–818.

Reproduced: 300 valid synthetic OHLCV bars yield zero default SMC signals. The centered rolling high at i-1 includes candle i for the default five-bar window. A valid candle has high[i] >= close[i], so close[i] cannot exceed that maximum. The bearish comparison has the mirrored problem. The centered window also includes future information.

Root cause: retrospective swing annotation was reused as a tradable signal without a confirmation delay.

Implementation: define when a swing becomes observable. Use trailing windows or emit a fractal only after the required right-side bars exist, with the actual availability timestamp. Test both causal availability and signal reachability; a zero-signal strategy should not silently be graded as a tested strategy.

Acceptance: handcrafted bullish and bearish breakouts, no breakout controls, flat/NaN/gap series and neutral regimes. For every strategy, a prefix-invariance test must show that extending future data cannot change already-observable decisions.

### F13 Qualify each backtest by execution realism and data coverage

Evidence: engine/backtest.py:888–990; engine/backtest_vectorized.py:191–260; engine/options_backtest.py:886–941, 981–986 and 1174–1176; engine/backtest_advanced.py.

Code confirmed: the basic Backtester computes a close-based signal and fills at that same close, with no statutory cost call or spread/slippage model in the run loop. Its reported quantity is calculated after exit from post-trade capital and exit price, rather than the executed entry quantity. Forced-close reporting uses zero quantity. The vectorized engine explicitly omits fill simulation.

The options engine supports real historical contracts, which is useful, but falls back to modeled premiums per observation. It labels the entire result REAL_EXPIRED_FNO if even one real bar was used. Missing IV falls back to 20%, and present-day lot specifications are reused unless overridden.

Root cause: exploratory simulation and tradable historical evidence share result labels.

Implementation: keep the lightweight engine for exploration with explicit limitations. Establish a production replay engine with event/availability time, next-executable-price fills, side-specific spread, impact, participation, partial fills, historical fees/lots/contracts, dividends/corporate actions and survivorship-safe universes. Resolve ambiguous intra-bar stop/target order conservatively or with finer data. Report mixed real/model coverage per fill and bar. Modeled scenarios remain scenario research.

Acceptance: no same-bar execution without an explicit auction/order-timing model; consistent entry quantities and cash; realistic gap fills; real-data coverage floors; historical contract changes; unavailable expired contracts; modeled/observed mixed runs labeled MIXED. Compare selected replays against anonymized broker trades and contract notes.

### F14 Repair outcomes and uncertainty before using Kelly or confidence boosts

Evidence: engine/detector_circuit_breaker.py:107–205; engine/auto_alert_engine.py:7735–7757, 8125–8167 and 4890–4905.

Reproduced: zero samples report win_rate 0.5, expectancy 0.5 and Kelly 0.25 as normal fields; recording the same alert ID twice yields two samples. Code confirmed: TEST/environment labels are used for alert presentation near the outcome writers but are not enforced by the outcome store API. Any target-hit vocabulary can become a WIN. The scrutiny update takes the maximum of existing and adjusted confidence, which can preserve a prior higher score and does not itself reapply a newly HALTED state.

Root cause: hypothetical alert progress, execution outcomes, priors and empirical measurements are not distinct data types. Sampling and governance lack immutable outcome identity/version.

Implementation: separate setup forward outcomes, paper executions and real executions. Enforce provenance at the store boundary. Record one immutable position outcome with corrections/retractions by version; deduplicate by account/position/strategy version. Calculate net R from actual weighted exits and fees, not from milestone names. Use abstention/INSUFFICIENT_DATA, uncertainty intervals and shrinkage instead of displaying assumed empirical metrics. Recheck HALTED status at publication and execution. Estimate strategy-specific risk budgets under tail scenarios; never allocate capital from an uncalibrated LLM score.

Acceptance: duplicate/corrected outcomes, TEST rejection, partial scale-outs, fee-negative target hits, multi-day positions, halt after scrutiny, reset semantics, independent strategy versions and sample thresholds chosen from uncertainty rather than a universal small count.

### F15 Replace confidence theater with measured decision quality

Evidence: engine/alert_model.py ActionableBlueprint; engine/alert_scrutiny.py:130 and 1050–1167; engine/defined_risk_spreads.py:107–174; engine/position_sizer.py:736–817; frontend AlertsView confluence display.

Code confirmed: the policy documents prescribe universal 2R/4R/6R targets and R:R >= 3, while tests and runtime minima vary. Defined-risk spread construction uses modeled premiums and price-level strike heuristics. Confluence boosts and tiny-sample governor labels do not establish independent confirmation.

Design risk: bullish, bearish and neutral structures have different payoff distributions. A neutral credit spread can have positive expected value with a payoff ratio below three, while a three-R target can still have negative expected value after costs and low fill probability.

Implementation: define strategy-specific hypotheses and net expected value, fill probability, maximum loss, liquidity/capacity and tail loss constraints. Keep structural stops rooted in observable invalidation and permit NO TRADE. Validate CALL, PUT and NEUTRAL cohorts separately; use symmetry tests for mirrored code but do not force statistical symmetry on asymmetric markets. Label heuristic scores as scores until calibrated against forward outcomes. Treat VPIN, OBI and macro lead/lag as measurable hypotheses rather than proof of institutional intent.

Acceptance: held-out calibration by strategy/regime/DTE/liquidity; ablation of every filter and LLM layer; correlated-detector analysis; realistic costs; capacity decay; negative controls; stable performance intervals. Do not repair weak R:R by moving targets farther away without evidence.

### F16 Remove fabricated protection from order tickets

Evidence: macos-app/src/renderer/src/components/Modals/OrderTicketModal.jsx:76–90, 140–157 and 228–232; macos-app/tsconfig.json.

Code confirmed: missing or considered-invalid protection becomes 25% stops and 35% targets; contract lots are duplicated in client branches. Underlying/premium unit mismatches can become another percentage boundary. TypeScript allows JavaScript with checkJs false and strict false, so a successful typecheck does not establish contract safety for these JSX paths.

Implementation: the ticket consumes a server typed blueprint with explicit premium-versus-underlying units. Missing levels remain unset and show the reason. Any suggested level carries its deterministic source and timestamp. Fetch exact contract specifications and validate quantities at the server. Generate client API schemas/types and progressively enable strict checking. Preserve explicit user confirmation and the current cryptographically random intent keys.

Acceptance: no source stop/target produces no invented order field; underlying and premium are distinct types; BFO/NFO lot changes; stale preview; keyboard and screen-reader flow; duplicate click and slow response; errors remain visible with correlation ID.

### F17 Enforce LLM deadlines at transport and scheduling boundaries

Evidence: agent/multi_agent.py:2000–2042 and similar wrappers; agent/dag_orchestrator.py:278–308.

Reproduced: a fake local chat sleeping roughly 150 ms with a 5 ms configured timeout returned fallback after about 156 ms in the saved evidence. ThreadPoolExecutor context exit waits for its running task. Therefore future.result(timeout) does not implement the advertised end-to-end deadline. DAG as_completed timeout can also leave unfinished work while executor shutdown waits.

Root cause: waiting timeout is confused with cancellation of the underlying operation.

Implementation: propagate a request deadline into provider transport connect/read/total timeouts. Use bounded long-lived execution resources, admission control, cancellation-aware async operations and a documented fallback deadline. Do not create unbounded abandoned threads. Persist model/provider/prompt/evidence versions for each decision. Keep all actionable levels and order permissions under deterministic authority. Treat external news and filings as untrusted content, with restricted tools and schema-validated outputs.

Acceptance: stalled transport, rate limit, malformed/truncated JSON, prompt injection in retrieved content, cancelled client and exhausted workers. Measure actual wall time, outstanding tasks and fallback completeness. Run an LLM-versus-deterministic ablation before claiming the AI layer improves trades.

### F18 Commit decisions and delivery obligations together

Evidence: engine/storage/alert_repository.py:32–158; web/sse.py:36–130.

Code confirmed: alert storage dual-writes SQLite and a JSON snapshot with independent error handling. A fallback writes directly to the target after rename failure. Different repository instances have separate in-process locks. Some storage resolution bypasses config.paths and prioritizes only TRADING_PLATFORM_DATA, explaining why a HOME-only override did not consistently redirect writes during local setup.

SSE queues drop older messages at capacity and emit data without event IDs or a replay cursor. This is acceptable for replaceable ticks only if clients can resnapshot; it is insufficient as the durable delivery record for critical lifecycle changes.

Root cause: persistence, projections and notification delivery have no shared durable commit boundary.

Implementation: one authoritative database per domain; transactional domain event and outbox writes; derived JSON snapshots for export/recovery only; sequence/versioned projections; idempotent Telegram delivery with SENT/HELD/FAILED reasons. Stream critical transitions with IDs, cursor recovery and full snapshot reconciliation. Coalesce ticks separately from order/alert transitions. Route all paths through config.paths and document single-process limits until cross-process writer coordination exists.

Acceptance: crash between commit and dispatch, reconnect after queue overflow, duplicate dispatch, JSON failure, two writers, Windows file contention, HOME-only override, lost Telegram acknowledgement and prolonged consumer outage.

### F19 Make tests independent of the implementation assumptions

Evidence: tests/test_charges.py; tests/test_sebi_expiry_mandate_invariants.py; tests/test_live_oms_p3b.py; tests/test_api_ui_contracts.py; tests/conftest.py:63–72 and 177–193.

Code confirmed: regression tests assert obsolete taxes and exchange dates. Gate tests supply fields that production callers omit. A global monkeypatch makes every test thread daemon, which can hide shutdown leaks. The fixture writes a calibration file under the real user home when missing, despite isolated test storage. Many resets suppress exceptions, so failed isolation can go unnoticed. The API/UI contract file checks selected response keys; it does not establish complete JSX-to-API parity.

Implementation: use externally sourced, effective-dated golden fixtures; end-to-end fake broker tests through real production boundaries; model-based lifecycle testing; property tests for money conservation and causal features; fault injection at I/O boundaries. Remove global thread mutation from correctness suites and test clean shutdown explicitly. Deny writes outside a per-test root. Treat failed cleanup/reset as a test failure. Keep real-network tests separately authorized and credential-free by default.

Acceptance: mutation tests must catch removal of mode, account, lot, session, provenance and confirmation guards. Crash/restart tests must catch missing children/fills/protection. A source-string test may supplement but cannot replace behavioral assertions. Report coverage by financial guarantee and failure scenario rather than total test count.

### F20 Qualify clean installation and broker readiness

Evidence: pyproject.toml optional dependencies; scripts/bootstrap.ps1 Test-Venv and install commands; .github/workflows/ci.yml; local pip check and Fyers WebSocket import.

Observed: bootstrap installs [dev] but its final readiness check requires fyers_apiv3. Installing the declared Fyers extra conflicts with Exa over requests. The prior no-dependencies workaround allows a top-level SDK import, but leaves missing aiohttp, websocket-client, aws-lambda-powertools, setuptools and the declared asyncio distribution. WebSocket import fails on pkg_resources. The installed requests version also violates the SDK pin.

Root cause: dependency presence, importability, transport capability and authenticated readiness are treated as the same condition. Broad dependency ranges and optional broker stacks are not installed as a tested deployment profile.

Implementation: define supported Python/Node/broker profiles with reproducible locks or constraints and automated dependency/security checks. Do not promote no-dependencies installation as a supported solution. Prefer an upstream-compatible SDK or a separately isolated broker worker with a narrow typed protocol if dependency resolution remains impossible. Review transitive security risk before selecting legacy versions. Probe quote, depth, order-status and account-read capabilities independently using safe provider checks.

Acceptance: fresh Windows and Linux install; selected optional profiles; full WebSocket submodule import; startup/shutdown; reconnect; SDK compatibility; secret-free support logs. Update runbooks and bootstrap to check only the selected profile. Separate service liveness from broker readiness.

### F21 Reduce coupling through measured extraction

Evidence: engine/auto_alert_engine.py, engine/alert_scrutiny.py, web/api.py, web/skills.py and agent/core.py; synchronous maintenance handlers in web/api.py:1517–1560.

Code confirmed: large modules mix policies, data access, threading, state mutation and delivery. Several async administrative handlers run synchronous storage or synchronization work directly. This can contend with SSE and order request responsiveness.

Implementation: retain a modular monolith initially. Extract contracts and transaction boundaries first, then calendar/cost/risk policies, scanner scheduling, alert persistence and transport projections. Use bounded background jobs for expensive administrative work, idempotent job IDs and observable progress. Separate critical order work from scanning, news/LLM and maintenance budgets. Use structured errors and trace IDs; suppress only explicitly expected cancellation cases.

Acceptance: controlled profiling under representative symbols/streams; bounded queues and caches; resource limits; no maintenance job blocks the main loop; leak-free shutdown. Set latency SLOs from measured budgets and broker limits, not marketing targets.

### F22 Introduce a broker and regulatory capability policy

Evidence: order paths support MARKET orders and broker-specific features, while deployment policy is mostly general mode and safety flags.

Design gap: a local personal trading tool, a hosted service and an algo-provider product need different broker and exchange qualification. Forcing IPv4 is not the same as verifying a registered static egress address. Request sorting is not exchange basket atomicity.

Implementation: maintain an effective-dated capability matrix per broker/account/segment: allowed order kinds, modification/cancellation behavior, rate limits, expiry instruments, margin APIs, GTT/OCO support, session rules, tagging, static-IP eligibility and deployment approval. Obtain broker confirmation of the applicable API/algo route and order types before enabling that profile. Document market-data redistribution and third-party-data retention rights if expanding beyond personal use.

Acceptance: reject unsupported capabilities before confirmation; classify broker errors; prove no blind order resend; exercise approved exchange/broker mock sessions. Product distribution requires a specific compliance review rather than inferring approval from local API connectivity.

Sources: [SEBI implementation extension](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf) establishes broad applicability from 1 April 2026; [NSE retail algo FAQ](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf) describes tagging, static-IP/hosting distinctions and algo order-type restrictions. Scope and current broker implementation must be verified for each deployment.

## Crosscutting root causes

1. Multiple financial authorities: direct execution, order lifecycle, OMS abstractions and emergency handlers do not share an unavoidable mutation boundary.
2. Incompatible contracts: segment names, account identity, quantity units, modeled/observed data and state vocabulary are optional strings rather than enforced types.
3. Intentions treated as facts: an order request becomes a fill, a native exit request becomes a flat position, a target touch becomes a win, and a modeled premium becomes real history.
4. Transaction assumptions: connection contexts and separate file writes are mistaken for atomic units of work.
5. Self-referential evidence: implementation constants become tests, prompts and operational guidance, which then certify the original assumption.
6. Feature accumulation: heuristics and fallbacks are added faster than evidence, versioned policies and end-to-end failure tests.

## Target architecture

The proposal is a modular monolith with narrow isolated broker processes only where dependencies or fault containment require them. Kafka, distributed microservices and a wholesale language rewrite are not prerequisites.

~~~mermaid
flowchart LR
    EX[Exchange and broker feeds] --> MD[Versioned market data gateway]
    MD --> EV[Evidence envelopes with event and receipt time]
    EV --> SIG[Deterministic strategy decision]
    SIG --> DS[(Decision and outcome store)]
    DS --> PLAN[Typed trade plan and portfolio risk]
    PLAN --> CONF[Account bound preview and confirmation]
    CONF --> OA[Single order authority]
    OA --> BR[Broker capability adapter]
    BR --> FE[Order and fill events]
    FE --> LED[(Account execution and cash ledger)]
    LED --> REC[Independent broker reconciliation]
    DS --> OUT[(Transactional outbox)]
    LED --> OUT
    OUT --> UI[Desktop and stream projections]
    OUT --> TG[Audited Telegram delivery]
    LLM[Restricted LLM explanation] --> SIG
    DEMO[Isolated synthetic scenario namespace] --> DEMOUI[Demo only projections]
~~~

LLM output may propose explanations or hypotheses, but cannot create authoritative prices, contracts, fills, permissions or account state. Demo data cannot cross into the real evidence or execution namespaces.

Proposed shared contracts include InstrumentRef, MarketEvidence, StrategyDecision, TradeBlueprint, ConfirmedIntent, SubmissionAttempt, BrokerOrderEvent, ExecutionFill, CashMovement, PositionProjection, OutcomeRevision and DeliveryRecord. Each carries stable identity, versions, provenance and timestamps appropriate to its domain.

## Implementation work packages

Estimates below are planning ranges, not measured delivery promises. With three engineers, one quant/research owner and shared QA/security support, budget 12–16 weeks initially for engineering and qualification work in Phases 0–6. Phase 7 requires an additional evidence-driven observation period; stable, frozen strategy cohorts can begin observation while unrelated engineering finishes. A smaller team should sequence work rather than compress verification.

### Phase 0 Contain and specify the release boundary

Timing: 2–3 engineering days. Owner: execution lead with security/QA review. Findings: F01, F02, F04, F11.

Deliverables:

- Inventory every financial mutation call and classify entrypoint, mode, account, audit and recovery behavior.
- Record current deployment profiles and ensure real execution remains an explicit owner-controlled capability.
- Prevent synthetic market evidence from qualifying real-market alerts and learning.
- Replace maintenance-prefix exemptions with explicit protected route policy.
- Add boundary tests for PAPER with a connected real broker and emergency rejection reporting.
- Correct stale operational instructions with authoritative references and effective dates.

Exit: the boundary matrix has no unexplained financial origin; affected live deployment profiles remain unqualified until the later safety gates pass. Do not enable live flags as part of this review or phase automation.

### Phase 1 Contracts and transactional foundations

Timing: 1–2 weeks. Owners: backend/execution and data engineers. Dependencies: Phase 0. Findings: F03–F06, F10.

Work packages:

- P1.1 Normalize segment/order/status/unit enums and typed server serialization; remove permissive live defaults.
- P1.2 Introduce explicit read and write unit-of-work contexts, rollback handling and transactional audit/outbox operations.
- P1.3 Introduce versioned contract, calendar/session/auction and cost schedules, retaining historical validity intervals and scheduled future activation.
- P1.4 Bind previews to account, instrument and policy versions, source evidence and all protection legs.
- P1.5 Pass a complete pretrade context and reserve account funds/risk across pending intents.
- P1.6 Add offline, idempotent schema migration and rollback tooling with preflight backups.

Exit: all-or-none multi-order state claims; unknown/missing safety context fails; confirmed decisions cannot change account or protection silently; external golden calendar/cost fixtures pass.

### Phase 2 Execution ledger and recovery

Timing: 2–3 weeks. Owner: execution lead. Dependencies: transactional and identity work in Phase 1. Findings: F01, F07–F09.

Work packages:

- P2.1 Consolidate mutation entrypoints and remove shadow placement paths.
- P2.2 Persist parent strategies, child orders, attempts, broker correlation and immutable fill IDs.
- P2.3 Project account-specific positions/cash from actual execution and account events.
- P2.4 Resolve unknown submission attempts through broker histories before retry.
- P2.5 Build protection obligations from incremental fills and reconcile them after restart.
- P2.6 Build the emergency coordinator with verified cancellation and residual position reduction.
- P2.7 Reconcile orders/trades/positions/funds, including external broker activity.

Exit: crash at every submission boundary preserves discoverable exposure; duplicate/out-of-order events are harmless; partial fills are never counted as full; account mixing is impossible; no unverified success or claimed protection.

### Phase 3 Market evidence and delivery integrity

Timing: 1–2 weeks, can overlap the latter part of Phase 2 after shared schemas stabilize. Owners: data engineer and backend engineer. Findings: F04, F11, F18, F20.

Work packages:

- P3.1 Enforce provenance and freshness on every quote, option leg, depth snapshot and scanner decision.
- P3.2 Isolate modeled/demo datasets and remove fabricated depth quantities.
- P3.3 Qualify supported broker dependency profiles and full streaming imports.
- P3.4 Route every runtime path through config.paths.
- P3.5 Make alert state and delivery obligations one transactional commit.
- P3.6 Add stream sequence IDs, resnapshot/replay and channel-specific overflow behavior.

Exit: provider loss yields honest unavailable states; demo inputs cannot affect learning or publication; reconnect recovers critical transitions; installation is reproducible for each advertised profile.

### Phase 4 Research validity and economic calibration

Timing: 3–4 weeks after Phase 1 cost/calendar contracts and Phase 3 evidence policy. Owner: quant/research lead with engineer support. Findings: F12–F15.

Work packages:

- P4.1 Repair causal SMC and add prefix-invariance across all feature/signal families.
- P4.2 Label exploratory backtests, then implement/qualify execution replay and accounting.
- P4.3 Record point-in-time datasets, corporate actions, historical constituents and contract specifications.
- P4.4 Separate observed, paper, forward-setup and modeled outcomes; deduplicate/correct outcome revisions.
- P4.5 Build a trial registry and locked out-of-sample validation before strategy promotion.
- P4.6 Calibrate confidence, exit policy, risk allocation and liquidity/capacity by strategy/regime.
- P4.7 Run ablations for filters, confluence boosts, LLM scrutiny and macro features.

Exit: no future-data leakage; net-cost metrics and positions reconcile; each promoted model has independently frozen validation evidence and known coverage limits. Strategies with inadequate evidence remain research-only.

### Phase 5 Decision interface and LLM reliability

Timing: 1–2 weeks, partly overlapping Phase 4. Owners: frontend and backend engineers. Findings: F10, F16, F17.

Work packages:

- P5.1 Remove invented ticket stops/targets and client contract authority.
- P5.2 Generate schema contracts and progressively enable meaningful static checking.
- P5.3 Show evidence age, unavailable fields, modeled scenarios and protection state consistently.
- P5.4 Enforce provider transport deadlines, bounded inference resources and deterministic fallback.
- P5.5 Restrict tools and external-content trust; add prompt-injection and output-schema evaluation.
- P5.6 Validate keyboard, screen reader, error recovery and slow-response behavior.

Exit: every displayed actionable field maps to authoritative source evidence or explicit user input; actual fallback latency meets its measured deadline; unavailable data cannot look like a verified decision.

### Phase 6 Operational qualification

Timing: 1–2 weeks. Owners: QA/reliability, execution and data leads. Findings: F18–F22.

Work packages:

- P6.1 Add clean Windows/Linux installation matrices and selected broker SDK contract suites.
- P6.2 Run event replay, crash recovery, storage contention, clock skew, DST/holiday and queue-overflow exercises.
- P6.3 Establish baseline latency/resource SLOs under representative symbol and subscriber loads.
- P6.4 Drill backup restoration and compare restored ledger projections with known event hashes.
- P6.5 Validate administrative authorization, local desktop Origin/Host policy and secret redaction.
- P6.6 Document broker-approved capabilities, rates, IP/hosting requirements and order types.

Exit: no unresolved critical execution/security defect; all required deployment profiles have passing evidence; support can explain an order, alert or reconciliation journey from immutable records.

### Phase 7 Forward qualification and constrained pilot

Timing: initially 4–8 weeks of representative paper/shadow observation; sufficient evidence may require longer. Owner: trading risk/research with explicit owner approval for any live phase.

- Freeze one or two liquid, clearly specified strategies. Do not expand the universe to dilute a weak result.
- Compare decisions and simulated executions with actual contemporaneous bid/ask, fills, fees and missed-trade behavior.
- Track latency, fill probability, slippage, adverse selection, outcome calibration, exposure and operational incidents.
- Require the predefined net expectancy and tail-risk evidence, plus broker qualification, before proposing a small live pilot.
- Set owner-approved exposure/position/strategy limits and independent stop/reconciliation conditions.
- Treat a pilot as learning under a controlled loss budget; do not promote on a short winning streak.

Exit criteria for capital allocation must be specified before observing the sample. Calendar duration alone is not a statistical qualification.

## Test design matrix

| Financial guarantee | Required scenarios | Primary layer |
| --- | --- | --- |
| Mode isolation | Every origin, connected real broker in PAPER, OBSERVE, invalid mode | Boundary and fake broker |
| Confirmation integrity | Different account, stop/target, quote/policy version, expired confirmation | API to ledger integration |
| Submission idempotency | Duplicate click, concurrent request, broker timeout, crash before acknowledgement | State model and fault injection |
| Child order exposure | First fill/later rejection, missing response, mismatched response order, hedge not filled | Broker contract replay |
| Protection | Async/partial fill, GTT reject/unsupported, resize, restart | Lifecycle integration |
| Accounting | Actual prices, fees, partial fills, shorts/cross-zero, two accounts, transfers | Golden ledger replay |
| Reference data | Effective dates, holidays, contract expiry, stale master, tick/lot transition, CAS phases and future rule activation | External golden fixtures |
| Settlement | Zero DTE, missing metadata, long/short calls/puts/futures, one-lot budget | Risk and broker capability |
| Data truthfulness | Failed providers, zero quote, stale tick, synthetic chain, missing depth size | Data gateway and consumer contract |
| Strategy causality | Prefix invariance, delayed publication, revised fundamentals | Property and replay tests |
| Learning integrity | Duplicate/retracted outcome, TEST exclusion, weighted exits, small samples | Outcome store and governor |
| Auth and diagnostics | Unauthenticated writes, CSRF, roles, loopback origins, secret redaction | Security integration |
| Delivery | Commit/crash/dispatch, reconnect, overflow, duplicated Telegram acknowledgement | Outbox and replay |
| Shutdown/resource safety | Unmocked daemon behavior, stalled LLM, queue saturation, connection cleanup | Isolated subprocess and load |
| UI usability | Source-less levels, premium/spot units, stale preview, failed action, keyboard | Browser/Electron journey |

Keep API helper tests, but spend new test effort on these boundaries. Use mutation testing on critical guards and mandatory negative scenarios for adapters. Treat a build/typecheck as one signal of quality, not evidence that financial contracts are sound.

## How to establish a defensible trading edge

The likely advantage is an audited decision-and-execution loop with credible costs and disciplined abstention. Additional indicators, more AI personas and stronger conviction language are not evidence of advantage.

1. Pre-register a hypothesis: which market behavior, which liquid instruments, what holding horizon, what observable trigger and what invalidates it.
2. Freeze dataset availability times, feature versions, universe membership and contract/cost schedules.
3. Record every attempted variant, including rejected ones. Reserve a final untouched period and use chronological splits with purging/embargo for overlapping labels.
4. Measure selection bias and robustness using methods such as the Deflated Sharpe Ratio and Probability of Backtest Overfitting, with assumptions and dependence caveats. These tools evaluate evidence; they do not guarantee future profit.
5. Evaluate net expectancy, drawdown, expected shortfall, gap/expiry stress, turnover, capital/margin use, fill probability, opportunity cost and capacity.
6. Use block/bootstrap methods that respect serial dependence where appropriate. Reordering a fixed set of profitable trades does not prove predictive power.
7. Compare BULL/CALL, BEAR/PUT and NEUTRAL policies by regime/DTE/spread/liquidity; measure mirrored code correctness and actual market asymmetry separately.
8. Test incremental value: deterministic baseline, each filter, LLM layer, alternative exit policies and costs at stressed levels.
9. Require forward calibration, drift monitoring and versioned rollback. Allocate by conservative evidence and portfolio interaction, not nominal confidence.

Useful research directions after correctness: true event-time order-flow imbalance and fill toxicity, post-event price discovery, regime-conditioned trend versus mean reversion, robust option-surface quality checks, and stock-specific overnight/settlement risk. Every candidate must survive the same held-out and capacity process.

Primary methodology sources: [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) and [Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). The statistical procedures require thoughtful sampling, trial accounting and interpretation.

## Proposed measurable quality gates

These are design requirements to adopt, not claims that they are already satisfied.

- Every financial mutation has a mode/account-bound intent and persistent submission evidence.
- No broker call can occur before the relevant durable submission record.
- Every filled unit has an immutable broker/account trade identity and an accountable protection state.
- Replaying input events gives the same positions, cash, alerts and delivery obligations.
- Every actionable market field has timestamped provenance; unavailable evidence remains unavailable.
- Every published strategy result discloses observed versus modeled coverage and applicable cost/contract versions.
- Every promoted strategy has frozen out-of-sample and forward evidence, capacity limits and withdrawal conditions.
- All critical route, mode, account, provenance and lifecycle mutations are caught by negative tests.
- Backups restore to a reconciled state within owner-defined RPO/RTO, demonstrated in drills.
- Latency, loss budgets and queue/drop/reconnect policies are explicit and measured by workload.

## Decisions to record before implementation

The review can proceed without these answers; the responsible phase must record them before its design is frozen.

| Decision | Proposed default | Why it matters |
| --- | --- | --- |
| Product/deployment scope | Personal local research and PAPER first | Determines auth, data licensing and broker qualification |
| Initial broker profile | One execution broker and one independent data route, explicitly selected | Reduces adapter and recovery complexity |
| First promoted strategy set | One or two liquid, testable strategies | Avoids broad uncontrolled search and fragmented evidence |
| Canonical persistence | SQLite with explicit single-writer transactions initially | Preserves simplicity while fixing actual failure boundaries |
| Financial facts | Broker/account executions and cash events | Enables independent accounting and recovery |
| Historical data qualification | Real contract data for execution/alpha claims; model scenarios labeled separately | Prevents apparent edges from pricing assumptions |
| Live eligibility | Only after P0 closure, broker qualification and forward evidence | Keeps deployment tied to proof |
| Risk ownership | Named human owner sets hard capital/operational limits and permitted advisory overrides | Distinguishes behavioral coaching from mandatory integrity controls |

## Handoff

Start with Phase 0, then Phase 1's contracts and transactional foundation. Do not begin by adding indicators or rewriting the UI. Each phase should produce a scoped design, migration/rollback approach, negative tests, measured verification and a factual completion record. Reconcile the older September plan against these findings before using it as the current implementation authority.

Accompanying artifacts:

- evidence.json contains isolated probe observations.
- probes.py reproduces those observations using temporary data and fake brokers.
- Test commands and dependency observations above apply to the audited local environment; SDK/exchange behavior must also pass the deployment qualification phase.

