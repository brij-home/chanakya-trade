# Hardening implementation status

31 October 2026. Branch: codex/verified-market-safety. This is an implementation update to the review, not a claim that all 22 findings have been resolved.

## Implemented and verified

- PAPER option chains no longer fall back to invented market data; explicit mock DEMO/OBSERVE scenarios remain separate.
- Production Telegram eligibility rejects explicit synthetic/test evidence, including misleading LIVE metadata. Test metadata cannot enable production bypasses.
- Resting depth quantities are not manufactured from cumulative traded volume. Observed bid/ask spreads remain available without fictitious queue sizes.
- NSE/BSE expiry candidates use a shared dated rule schedule with existing holiday adjustment; Telegram template fallbacks, alert model, events and prompts were updated.
- Derivatives STT is effective dated from April 2026; option exercise requires explicit intrinsic value.
- Canonical segment aliases reach session validation; unknown segments fail closed. CAS-eligible cash stocks stop qualifying for ordinary continuous-session orders after their applicable close. This does not add a CAS order-entry implementation.
- Zero DTE remains zero; missing DTE is logged as unavailable; mandatory lot reductions may produce zero lots.
- Explicit writer transactions support rollback, atomic batch claims and serialized security-audit appends. Read acquisition remains separate.
- Persisted no-chase metadata is decoded consistently; verified lot/tick and broker identity reach live pretrade gates.
- Emergency operations are isolated by mode, no longer rewrite pending ledger rows as cancelled, avoid a second counter-order after a native exit request, and report pending reconciliation rather than unconditional success.
- The default SMC signal uses causal trailing boundaries and passes reachable bullish/bearish plus prefix-invariance tests.
- Mixed observed/modeled option backtests are labeled mixed at run level.
- Missing order-ticket stops and targets remain unset rather than receiving percentage defaults.
- Self-hosted maintenance/diagnostic routes no longer bypass authentication/CSRF by prefix.
- Live mode qualification is checked before `SUBMITTING`; blocked intents remain reviewable as `CONFIRMED`. Live baskets, freeze-limit slices and auto-GTT protected entries stay blocked pending durable child-fill and protection recovery.
- Fyers smart/GTT/multileg and untracked position mutation endpoints no longer call broker mutation APIs directly. Fyers panic-exit uses the central audited emergency coordinator, and order modification now requires an OMS-owned intent.
- Empty or one-sided winning detector history no longer implies a healthy edge; flat-only samples stay uncalibrated. Terminal forward-path samples require a current quote and immutable anchors, partial-scale paths are excluded, and only verified broker-fill provenance may produce `HEALTHY`/Kelly/positive-alpha results. Legacy unlabeled detector rows remain audit-only.
- Removed hand-seeded historical pattern cases and default 85%/3.2R analytics. Missing pattern inputs and expected-R estimates stay unavailable; user-submitted and legacy fingerprints do not enter similarity matching. Milestone events no longer recalibrate performance weights, and pattern analytics do not label them as account win rate or realized R.
- Caller-supplied and persisted `VERIFIED_BROKER_FILL` labels cannot establish reconciliation. The writer rejects that provenance pending the account-scoped fill-ledger integration. Synthetic TEST calibration is pytest-only and is excluded during normal application runs.
- Historical fingerprint extraction excludes current option chains, sector rankings and fundamental caches. Removed move-size-derived fingerprint confidence. Autonomous learning uses the canonical NIFTY 50 universe and the observed event-bar date, avoiding duplicate weekend/delayed-feed cases; a missing or zero volume baseline cannot generate RVOL through an invented denominator.
- Terminal single-price outcomes now reject neutral/unknown directions; bearish outcomes are tested as the mathematical mirror of bullish outcomes. Multi-leg and scaled outcomes remain excluded pending durable leg/fill evidence.
- Fyers TBT depth no longer fabricates traded volume, OHLC, OI, circuits or session ATP from book quantities, LTP or rolling tick VWAP. Those fields carry null/unavailable status. The bridge rejects stale/undated/future packet receipts and avoids recaching TBT behind the off-market REST TTL. SDK readiness imports the actual TBT transport and caches an honest unavailable result on missing dependencies.
- Core bootstrap readiness now checks the installed dev profile without requiring the optional Fyers SDK. The Fyers extra explicitly includes websocket-client, but the vendor dependency conflict remains unqualified.

## Evidence

- 215 selected backend tests passed across alert templates/calendar, position sizing/settlement, costs, order lifecycle/live OMS, auth, options backtests, alert identity/channel parity and order book.
- After the final CAS change: 62 focused tests passed, including 19 safety-contract cases. This overlaps the 215-test run; totals must not be added as independent coverage.
- 60 affected frontend tests passed across provenance, components and alerts.
- Changed Python files passed Ruff checks; formatting was applied; git diff whitespace check passed.
- Latest combined verification: 169 tests passed across alert lifecycle, order lifecycle/live OMS, mode gates, detector governance, LLM caller deadlines, Fyers endpoints, GTT behavior and verified market safety. This overlaps the earlier selected-suite count and is not additive. Ruff passed for all touched Python modules and tests.
- Read-only alert inventory: 126 stored records, 16 marked active, zero explicitly unverified markers. Missing markers do not certify authenticity. Historical records were not rewritten.
- Continuation verification: 203 selected execution/market-safety/lifecycle/learning tests passed. After the final learning changes, 32 focused outcome/calibration/learning tests passed. After the Fyers depth changes, 52 broker/depth/rate-gate tests passed. These sets overlap and must not be added as unique coverage. The optional vendor-SDK integration check in a separate OpsDeck run was skipped because websocket-client is absent (47 passed, one skipped). All changed Python files passed Ruff before the final TBT changes, and the TBT files subsequently passed Ruff. Bootstrap PowerShell syntax passed.
- Remote synchronization rechecked: HEAD, origin/main and GitHub main all resolve to `82114d06c38c8a8f297fa3e7a48b6ac91787e8ab`. The fixes remain local uncommitted changes on `codex/verified-market-safety`.

## Deployment checkpoint

The local `/api/mode` endpoint responds `PAPER` / `SIMULATE`. Its code-provenance endpoint reports stale in-memory code (19 changed files at the check), so the running process is not evidence that these fixes are deployed. No restart was performed in this continuation: the workspace Fyers profile fails `pip check` (missing aiohttp, asyncio distribution, aws-lambda-powertools, setuptools and websocket-client; installed requests 2.34.2 conflicts with the SDK's 2.31.0 pin). Do not downgrade shared HTTP dependencies or install the SDK with `--no-deps` to disguise this. Qualify a compatible or isolated broker profile, then reload the scoped service and verify source freshness, alert parity and code provenance. No live execution flags were enabled.

## Remaining work that still blocks institutional live qualification

The review's account/fill ledger redesign, full CLI/REPL execution unification, durable child-order/unknown-attempt recovery, asynchronous fill-driven protection, complete account/policy-bound confirmation, source-qualified detector calibration, transport-level LLM deadlines, durable alert outbox/replay, broker dependency qualification, and execution-realistic backtest revalidation remain open. Detector outcomes currently reflect alert price paths, not verified broker fills. The emergency coordinator reports uncertainty honestly; it does not yet establish verified flatness across every broker.

Full CAS-aware scanning and broker-specific cutoff integration remain necessary beyond the pretrade continuous-session guard. Explicitly tagged synthetic evidence is blocked, but historical untagged fabricated data cannot be identified safely merely from its numerical values.

Do not infer statistical edge, safe live execution, or the validity of old alerts from this patch or test counts. The running application remains in PAPER execution mode; users making manual real trades from research alerts still need fresh source evidence and independent risk sizing.

## Regression protection

### F&O discovery iteration, 1 November 2026

The FNO_ONLY default is now implemented in `config.discovery_policy` and wired to scanner/registry/ingestion boundaries, startup seeds, ticker polling, crypto transport startup, strict radar universes and profile-specific caches. Existing-alert lifecycle checks are not filtered. More than four TBT exposure registrations are retained and preempt discovery up to the provider's 15-symbol capacity; uncovered subscription diagnostics remain explicit. Legacy subscriptions of unknown purpose are retained, not silently deleted. See `docs/FNO_DESK_ROADMAP.md` for exact coverage and remaining resource-policy gaps.

Validation: 90 focused scanner/subscription/TBT/registry/mode tests passed; after final transport and ticker changes, 104 focused transport/lifecycle/order/mode tests passed (overlapping sets). Eight existing pandas deprecation warnings were observed, not suppressed. New tests use isolated objects rather than modifying the shared TBT singleton. General legacy suites explicitly use BALANCED while dedicated tests verify the strict production default and negative paths. The optional `.env` discovery override is absent, so the code default will apply on a corrected reload; credentials were not changed.

Deployment remains incomplete. The running `/api/mode` endpoint must report the new discovery policy after reload before this iteration can be considered active. No service restart, live execution flag change, order submission or test Telegram dispatch was performed in this iteration. The workspace Fyers SDK dependency profile is still unqualified; a read-only check of the separate system Python also found incompatible SDK pins. Do not infer that any interpreter with a clean core dependency check includes the required broker transport.

Read docs/SAFETY_CONTRACTS.md. AGENTS.md and the execution/alerts/backtesting skill headers point all AI providers to that contract. The Verified market safety workflow runs its behavioral tests on main pushes and pull requests. Existing CODEOWNERS names the repository owner. GitHub required status checks, owner review, stale-approval dismissal and restricted direct pushes must be enabled in repository branch rules to make these protections mandatory. Those remote rules have not been configured in this change.

No code was pushed, no production history was repaired, and no real orders or test Telegram messages were sent by the implementation checks.
