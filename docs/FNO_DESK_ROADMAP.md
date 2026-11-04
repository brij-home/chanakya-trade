# NSE/BSE intraday F&O desk: implementation and research roadmap

31 October 2026. Owner mandate: index options first, stock F&O second; concentrate discovery and active-session resources on NSE/BSE derivatives. Cash constituents and global markets may supply explanatory context. This document specifies the target architecture; it does not claim these controls have been implemented or deployed. Read SAFETY_CONTRACTS.md and the architectural review before implementation.

## Honest status

The prior hardening addresses important correctness defects, but does not establish a profitable strategy, prediction skill, live execution qualification or complete deployment. The last runtime inspection reported PAPER/SIMULATE and stale in-memory code. The workspace Fyers dependency profile remains unqualified. Existing tests establish selected software contracts, not statistical edge.

## Implementation checkpoint: 1 November 2026

Implemented locally, not yet loaded into the running service:

- A validated `config.discovery_policy` now owns the FNO_ONLY default and explicit FNO_PRIORITY/BALANCED compatibility profiles. `/api/mode` exposes discovery policy separately from the execution-mode mapping. The local .env has no discovery-profile override; credentials were not edited.
- Non-F&O discovery gates cover commodity, currency, crypto, direct crypto-symbol scans, cash circuit/incubation/pairs scans, multibagger and swing-inflection entry points. Strict AUTO/ALL discovery stays within the domestic session. Direct detector registry calls and ingestion also apply scope; candidate F&O enrichment must resolve a derivative setup before a new cash-origin candidate enters the strict alert list.
- Strict watched-underlying lists use the canonical F&O universe. New subscription seeds, fallback seeds, commodity-grid seeding and ticker quote requests apply scope. The generic crypto transport no longer starts for discovery in strict scope; existing alert monitoring may explicitly start it. Crypto tick exit/target evaluation remains ahead of the discovery gate.
- Precursor/asymmetric universes use the canonical F&O scope, with profile-separated caches and explicit-universe filtering. Historical broad cache entries cannot be reused under FNO_ONLY.
- The TBT manager retains more than four exposure registrations. Exposure preempts discovery up to the 15-symbol provider capacity, with subscription-coverage diagnostics for the remainder. Focused stock discovery no longer outranks index option discovery in strict scope. Off-hours/commodity TBT grids perform no strict-profile discovery.
- Persisted subscriptions with unknown purpose are deliberately retained and listed in `retained_out_of_scope_symbols`. The discovery profile does not certify that manual broker positions are known, that every legacy subscription is required, or that all infrastructure consumption is exclusive to F&O. Purpose-aware subscriptions and account reconciliation remain open.

Verification: 90 tests passed across focus, registry, subscriptions, TBT/rate-gate, radar and mode contracts. After the final transport/ticker changes, 104 tests passed across focus, crypto transport, ticker, WebSocket, alert lifecycle, order lifecycle and mode behavior. Sets overlap. The latter run emitted eight pandas inplace-deprecation warnings in existing market.history paths; no warnings were suppressed. A stale Thursday expiry assertion in the subscription test was corrected to the already verified October 2026 Tuesday schedule. New TBT tests use isolated objects instead of mutating the production singleton.

Remaining: qualify the Fyers deployment and scoped reload; migrate legacy subscription purposes; finish all remaining worker-budget and account-exposure boundaries; replace guessed ATM inputs with actual master-listed contract selection; calibrate symmetric regime/reversal logic; implement causal option replay, durable delivery and reconciled fills. These changes do not establish alpha or enable live order execution.

## Additional code-confirmed gaps

| Gap | Evidence | Consequence / required correction |
| --- | --- | --- |
| FNO_PRIORITY does not control all discovery | auto_alert_engine.scan_fresh_signals_now has a focus gate, while the background loop independently calls scan_currency_now, scan_commodities_now, scan_crypto_now and scan_multibagger_compounders | One central discovery policy must govern every entry point and scheduler before I/O or LLM invocation. Preserve monitoring and exits for existing exposure in any segment. |
| Broad subscriptions consume attention and capacity | ws_subscription_manager.CORE_BASE_SYMBOLS adds commodities, taxonomy equities and total-market constituents | Construct the subscription universe from listed F&O contracts, their underlyings, index constituents and necessary context; rank subscriptions and expose why each exists. |
| Guessed ATM inputs can generate wrong contracts | get_default_core_grid uses fallback spot values including 25000, 52000, 13200, 81500 and 1000; get_active_index_options_grid also contains static price inputs | No spot/contract evidence means no ATM contract. Select actual listed, unexpired contracts from the canonical master and verify quote freshness; do not merely format a plausible symbol. |
| Primary focus can outrank index discovery | _tbt_symbol_priority elevates a focused stock option above generic index options | Separate risk monitoring priority from discovery preference. Existing exposure always wins; index discovery precedes stock discovery unless an explicitly recorded tactical override applies. |
| Non-weekly is confused with deprecated | _tbt_symbol_priority comments label FINNIFTY/BANKEX options and futures deprecated | Monthly contracts remain eligible when listed and sufficiently tradable; rank actual liquidity, expiry and opportunity rather than the existence of weekly expiries. |
| Regime routing is asymmetric and brittle | scan_equity_nfo_now removes index_calls/opening_drives/afternoon_thrusts under distribution; chop and clock rules broadly suppress detector families | Evaluate bull, bear and neutral hypotheses symmetrically; allow causal reclaim/reversal evidence to change state. Measure the cost of suppression, including missed moves, before promoting a regime rule. |
| Feed capabilities differ by exchange | TBT symbol resolver rejects BSE; FYERS documents TBT for NSE/NFO | BFO/SENSEX needs a distinct five-level depth path and explicit capability flags. Missing unsupported TBT must not masquerade as missing data that the provider promised, nor silently borrow NIFTY microstructure. |

## 1. One operating policy and resource scheduler

Introduce a validated persisted FNO_ONLY profile, distinct from legacy FNO_PRIORITY and explicit multi-asset research. Do not add another trading execution mode. The policy must cover startup subscriptions, scan_all/scan_fresh calls, direct detector calls, periodic workers, TBT scouts, news/LLM jobs, learning and user-triggered scans. Return a recorded FILTERED_BY_FOCUS reason for excluded discovery.

Outside NSE/BSE derivative trading sessions, perform bounded next-session preparation, contract/holiday synchronization, replay and reports. Suspend unrelated live discovery. Session authority must include holidays and exchange/segment sessions; a weekday clock is insufficient. Health checks, outbox recovery and management of existing positions continue regardless of discovery scope.

Priority order: execution/protection and reconciliation; existing-position market data; index option discovery; stock F&O discovery; context features; historical backfill and optional research. Separate bounded queues and pools so slow news, pandas jobs and LLM calls cannot delay protection or fresh signals. Reserve headroom and measure queue age; do not treat full utilization as success.

Use one shared Prime entitlement and quota authority across all workers and connections. Existing UnifiedFyersRateGate already contains Prime presets; verify adapter paths actually delegate to it before changing limits. Sum usage per account/user across connections, implement quotas by API category, honor 429 cooldown, and reserve transaction/status capacity. A configured PRIME string is not proof of an active entitlement.

Prime Data Socket: broad, economical surveillance of relevant underlyings and near-money listed contracts. Subscribe a wider strike range only as underlying movement and liquidity warrant it. Do not fill all 5,000 slots automatically.

Prime TBT: allocate the 15 symbols dynamically to existing exposure, selected index futures and paired CE/PE candidates, then stock F&O finalists. Bids on one option must not evict the mirror-side evidence merely because the current view is bullish. A 3-future/8-option/4-scout allocation is an experiment, not a fixed optimum; active exposure preempts discovery. More than four exposed contracts must not lose protection simply because a current list is sliced to four.

BSE: use supported Data Socket/depth capabilities with exchange-specific liquidity, expiry and lot metadata. Do not request unsupported BSE TBT or synthesize its depth.

Acceptance: under the FNO_ONLY profile no new crypto/MCX/CDS/multibagger discovery consumes feed, CPU or LLM budgets; risk monitoring of existing exposure survives. Exercise all scanner entry points, holidays, reconnects, subscription rejections, quota exhaustion, overload and more exposed contracts than reserved TBT capacity. Assert resource use and observed exchange subscriptions, not only method return values.

## 2. Detect preparation, trigger and failure separately

Define an event lifecycle: WATCH -> ARMED -> TRIGGERED -> MANAGEMENT -> CLOSED/INVALIDATED/EXPIRED. Store the first availability time and the evidence snapshot for each transition. An early heads-up is conditional preparation; crossing a level alone does not establish a profitable entry. Telegram should distinguish heads-up, actionable trigger and management messages with the same persisted event identity and explicit no-chase boundary.

Build causal, complementary hypotheses: volatility contraction followed by expansion; opening-range acceptance; trend pullback and reclaim; failed breakout/liquidity sweep; relative strength/weakness and constituent participation. Defined-risk neutral strategies require their own payoff and execution evidence; NO_TRADE is a valid decision. Avoid a checklist of highly correlated indicators that delays entries without adding information.

Use underlying/futures structure for the thesis and the option contract for tradability and economics. Spot indices have no traded order book or traded volume: label futures/constituent proxies. Do not call a futures VWAP an observed spot-index VWAP. Store chain, underlying and futures timestamps independently and bound permissible skew.

Acceptance: an identical event prefix produces identical decisions; no future candle, daily close, refreshed historical fundamental or end-of-day institutional flow is available earlier than its publication. Bullish, bearish, neutral and reversal controls must be reachable. Record why an alert was rejected as well as why it fired.

## 3. Trap and option-economics controls

Hard eligibility: authentic fresh evidence; actual listed contract; supported exchange capability; valid expiry/lot/tick; executable two-sided quote; appropriate spread/depth for the proposed quantity; known session and applicable trading restrictions. Incomplete mandatory evidence yields UNAVAILABLE, not a favorable score.

Research features: breakout acceptance versus a transient print, participation beyond one heavyweight, time-of-day-normalized volume, futures basis, cross-strike confirmation, persistence of book pressure, and follow-through versus immediate re-entry into range. Cancelled walls or imbalance alone cannot prove spoofing or informed buying. Only label aggression/CVD when feed semantics justify it; otherwise explicitly label the proxy and quantify classification uncertainty.

OI increases do not identify whether buyers or sellers initiated the exposure. Public chain OI does not identify dealer inventory or signed dealer gamma. Any gamma-positioning estimate must carry assumptions and scenario sensitivity, never a factual institutional-position label.

Separate a directional forecast from option profitability. Estimate movement magnitude and timing versus spread, slippage, charges, IV changes, theta and gamma. Low premium and distant OTM strikes do not imply cheap exposure. Select expiry/strike using tradability and a range of underlying/IV/time scenarios, with source-tagged Greeks and clear model uncertainty. Do not force 0DTE or a fixed delta band in every regime. Fixed 3R/6R targets are hypotheses to evaluate, not proof of attainable edge.

For stock F&O include point-in-time derivative eligibility, ban/MWPL status under the applicable exchange rules, corporate actions, earnings/events, liquidity and physical-settlement exposure. A futures hedge and a long option have different funding/payoff contracts. Preserve separate underlying invalidation and premium-risk limits.

Acceptance: replay spread widening, IV crush despite correct direction, thin OTM jumps, stale chain/fresh spot, one-stock index distortion, failed breakouts, genuine V reversals, expiry afternoons, corporate actions and stock-ban transitions. Compare every added filter against missed profitable opportunities and total net expectancy.

## 4. Prove early-move capture with a reproducible options replay

Record licensed raw feed evidence, contract master versions, exchange/local timestamps, chain snapshots, packet gaps and publication times. Use seconds/expired-option history where provided, while recording its actual fields and limitations. Candle history cannot recreate unavailable historical bid/ask queues or establish queue-level fill priority.

Define a big-move event before tuning: direction, horizon, volatility normalization, minimum economically tradable premium move, and overlap rules. Resolve the contract as of the decision, not the contract that later performed best. Use chronological walk-forward evaluation with overlap purging, realistic costs, executable bid/ask, latency/slippage sensitivity, and separate unseen sessions for final evaluation. Retain failed and delisted/expired candidates to avoid survivor selection.

Report event-level precision and recall, false alerts per session, first-heads-up lead time, trigger delay, percentage of moves still capturable on receipt, maximum favorable/adverse excursion, net option expectancy, tail loss, drawdown, fill feasibility and alert delivery age. Segment by index/stock, BULL/BEAR/NEUTRAL, expiry/DTE, time of day and volatility regime. Use confidence intervals and minimum evidence requirements; many parameter trials require correction for selection bias.

Run ablations: simple futures/price baseline; plus participation; plus options; plus depth; plus LLM. Keep a feature/integration only when it improves held-out outcomes or verified reliability enough to justify latency, cost and complexity. Reconcile future manual/executed trades separately from alert-price paths; no invented fills.

## 5. Integrations, in priority order

1. Qualify the existing Fyers profile and use its documented Data/TBT/General WebSocket, option-chain/Greeks and historical/expired F&O capabilities. Prime entitlement is owner-confirmed. The adapter now requests expired-contract OI and option Greeks and parses named fields with null preservation. This is research/backtest data only: the API covers expired contracts, and comparable as-of constant-tenor IV history is still not integrated. Do not expose IV rank or grant alert conviction until the historical surface is constructed without look-ahead and improves held-out results. General order/trade updates must reconcile with persisted broker facts before establishing account fills.
2. Canonical exchange masters, trading calendar, derivative eligibility, contract adjustments, ban/MWPL reports and exchange corporate announcements; scheduled earnings, RBI and other relevant official events. Record publication times and stale-source behavior.
3. Optional independent data/broker source for outage detection and reference-price checks. Compare the exact same contract and timestamps, retain provider identity, never average incompatible sources or silently switch underlying/expiry. An alternate feed is not automatic execution failover.
4. Optional licensed historical/options feed when Fyers coverage cannot answer the replay questions. NSE lists authorized real-time vendors. Evaluate coverage, event timestamps, exact-contract versus rolling history, rights to store/use data and cost before purchase. Dhan documents expired-options access as a possible research adapter; validate actual granularity and rolling-series limitations.
5. Licensed timely news only if causal evaluation demonstrates incremental value. Additional LLMs, broker MCPs and competing signal services are not an execution authority or demonstrated alpha source. Keep external content untrusted and outside money mutation permissions.

No subscription purchase or new credential integration is authorized by this document itself. No claim is made that these additions outperform institutions or identify every move in advance.

## Delivery order and release criteria

| Milestone | Deliverable | Release criterion |
| --- | --- | --- |
| A: deployable data foundation | Compatible/isolated broker environment; capability and freshness probes; scoped service reload | Clean selected-profile checks; real data on the required NSE/BSE contracts; fresh runtime provenance; reconnect and quota tests; no live order placement |
| B: focused desk | Central FNO_ONLY discovery policy; index-first scheduler; bounded Data/TBT allocations | All entry-point and overload tests pass; existing-exposure monitoring unaffected; excluded discovery consumes no budget |
| C: contract and signal truth | Remove guessed ATM/master inputs; causal state transitions; symmetric regime/reversal logic | Real-boundary tests and historical replay; correct BFO capability handling; no future inputs or manufactured metrics |
| D: early-move research | Raw evidence/replay, event labels, option-cost scenarios, filter ablations | Held-out improvement versus the simple baseline with uncertainty and tail behavior reported; no target win rate assumed |
| E: reliable delivery and accounting | Transactional alert outbox/replay; manual/broker fill ledger; account-bound OMS recovery/protection | Crash/restart, duplicate, partial-fill and lost-acknowledgement tests pass; only verified fills establish account performance |

Run B-D in shadow research until their acceptance evidence exists. Existing live execution qualification blockers continue to apply. Promote independent, reviewable changes; do not replace the entire engine or rewrite production history at startup.

## Implementation checkpoint, 1 November 2026

- Contract discovery now requires a fresh, source-qualified underlying quote and active contracts from the canonical symbol master. It selects paired CE/PE rows from listed strikes with actual venue, lot, tick, token and expiry data. Missing/stale/future/mock quotes, degraded master snapshots, malformed rows and expired contracts produce no grid. Subscription grids no longer construct options from guessed spot prices or calendar-based symbol strings.
- NSE TBT core futures resolve from current master rows. Focused index-option pairs are allocated together; a capacity limit cannot leave only one side of a selected pair. Existing exposures remain ahead of discovery. This does not complete broker-account subscription-purpose reconciliation, nor does it certify that a subscription has a fresh quote or protective order.
- Bullish, bearish and neutral detector families now reach candidate-level regime eligibility during distribution/chop rather than being removed wholesale by scheduler lists. The regime gate receives the actual alert direction. RVOL-governed breakouts treat missing RVOL as unknown/zero evidence; test mode no longer injects 1.5x RVOL. `OPTIONS_MOMENTUM` uses independently supplied contract volume and OI evidence because that detector does not publish underlying RVOL; scrutiny rejects the option signal if either field is absent or non-positive. FNO_ONLY ingestion also rejects a cash-equity alert unless it carries a derivative contract and classifies as stock/index F&O. These changes improve reachability and evidence integrity, not proven predictive edge.
- Regime classification no longer promotes missing production India VIX to a synthetic 13.5 reading or consumes private cached VIX without freshness/provider checks. It requires a recent LIVE quote, exposes `UNAVAILABLE` when absent, and the regime eligibility gate suppresses new governed signals while the volatility input is unavailable. A deterministic value remains confined to isolated test mode.
- Focused verification: the integrated release-critical run passed 318 tests across verified market safety, dated expiry/charges, listed-contract selection, regime reachability, scrutiny, FNO_ONLY discovery, subscriptions/TBT, execution modes, order lifecycle, alert lifecycle and relevant NSE/BSE F&O session tests. This combined count avoids adding overlapping earlier runs. Repository Ruff passed; `git diff --check` reported no whitespace errors. The listed-contract and regime-reachability regressions are included in the verified-market-safety CI workflow.
- After the final VIX receipt-time change (including future-dated packet rejection), 48 focused regime, scrutiny and FNO-ingestion tests passed; repository Ruff and touched-file formatting checks also passed.
- A separate full-repository run collected 4,937 tests but was stopped at about 66% after surfacing failures in several older equity/event-volatility/OBI/in-flight/index suites. It was not a completed full-suite result and must not be represented as one. Those groups need separate RCA and, where they affect the F&O desk, their own release evidence.
- Remaining signal-quality work: as-of market-regime inputs with explicit unavailable states; validated, causal feature definitions and directional sweep evidence; instrument capability/compliance filters including BSE-specific feeds; historical options replay with executable quotes, costs and delivery latency; event-level precision/recall/lead-time and ablation evidence. No live trade performance or institutional outperformance is established.
- No service restart or live order action was performed. The current running application is still stale in memory until a compatible environment is qualified and reloaded. Discovery/contract fixes do not qualify the account for live automation.
- Options event analysis previously labeled underlying realized volatility as implied-volatility rank, fabricated neutral defaults and published strike-step-derived risk/reward as though premiums were known. The IV tool now returns unavailable without historical option-IV observations; realized volatility has a separately named tool/API. Earnings context no longer invents a neutral rank or static historical-move estimate. Event structures with explicitly supplied IV are labeled `RESEARCH_ONLY`, `actionable=false`, and carry no fabricated payoff or IV-crush guarantee; they cannot add scrutiny conviction. This closes a semantic safety gap, not an alpha improvement. Integrating a licensed, timestamped option-IV/history source and exact leg quotes remains necessary before event-volatility research can be evaluated.
- Zero-DTE theta exits now require explicit expiry-date or DTE evidence; the weekday-only inference is removed. Stock physical-settlement fallback now routes through the effective-dated NFO monthly schedule and holiday adjustment. Legacy helpers named `get_last_thursday_of_month` retain compatibility but return canonical current monthly expiry dates. Stale Thursday-date tests were corrected to Tuesday under the September 2025 NSE rule change. Index-expiry prioritization uses the canonical nearest-expiry resolver instead of a weekday map.

## Primary sources checked on 31 October 2026

- FYERS plans, API categories, Prime limits and historical access (page updated 14 October 2026): https://fyers.in/api-docs/v3/getting-started/plans-and-limits/
- FYERS Data Socket capabilities: https://fyers.in/api-docs/v3/api/websockets/data-socket/overview/
- FYERS TBT supported exchanges, delta/snapshot reconstruction and 15-symbol/3-connection limits: https://fyers.in/api-docs/v3/api/websockets/tick-by-tick-socket/overview/
- NSE real-time data and authorized-vendor resources: https://www.nseindia.com/static/market-data/real-time-data-subscription
- NSE derivative reports: https://www.nse.in/all-reports-derivatives
- NCL current position-limit/ban-period explanatory material: https://www.nseclearing.in/sites/default/files/2026-01/Recent_changes_in_Equity_Derivative_segment_focusing_on_position_limits%2C_Limit_Monitoring%2C_and_Securities_in_Ban_Period.pdf
- Dhan historical/expired data capability changes: https://dhanhq.co/docs/v2/releases/
