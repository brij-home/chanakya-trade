# Antigravity implementation prompt — deep review remediation, 3 November 2026

> **How to use this file:** paste the entire document as the Antigravity task prompt. Execute one task group at a time, in the order in Part 3, and stop at the verification gauntlet after each group. Do not start with the quant or architecture work.

**Contents**

- Part 1 — Verified findings register (A–H, 114 findings)
- Part 2 — Implementation plan (Phases 0–5)
- Part 3 — Execution order and dependencies
- Part 4 — Verification gauntlet
- Part 5 — Prohibited actions
- Part 6 — Definition of done
- Appendix A — Reproduction evidence
- Appendix B — Finding → task traceability
- Appendix C — Owner decisions
- Appendix D — Notes for the implementing model

## Role and objective

Act as the implementing engineer for ChanakyaTrade. Fix the verified safety, execution-integrity, risk-enforcement, data-truthfulness and authorization defects listed below. Work spec → failing test at the real boundary → code → passing test. This is a repair-and-harden pass, not a feature pass.

Workspace: `C:\Users\brije\.gemini\antigravity\scratch\chanakya-trade`
Branch reviewed: `codex/verified-market-safety`
HEAD reviewed: `82114d0` plus a large uncommitted working tree (241 modified paths, 44 untracked paths).
Review date: 3 November 2026.

This prompt authorizes reversible local edits and test execution. It does **not** authorize: committing, pushing, submitting broker orders, enabling `ALLOW_LIVE_TRADING`, `LIVE_EXECUTION_QUALIFIED`, `PILOT_ALLOW_LIVE_EXECUTION`, sending Telegram messages, mutating production alert history, or printing `.env`/tokens/passwords/OTP seeds/account identifiers.

Before editing, re-run `git status` and re-locate every cited symbol. Line numbers move. If a cited defect is already fixed in the current tree, record the evidence and skip it; do not re-implement it.

## Mandatory reading (in this order)

1. `AGENTS.md` — 44 core invariants.
2. `docs/SAFETY_CONTRACTS.md` — release contracts; this document supersedes older examples.
3. `docs/implementation_plan_codex/GEMINI_RELEASE_BLOCKERS_2026-11-02.md` — prior P0 work on fill ingestion, outbox and R:R. Verify its current status before duplicating work.
4. The relevant `.agents/skills/<domain>/SKILL.md` runbook before touching that domain.
5. `engine/modes.py`, `engine/order_lifecycle.py`, `engine/risk_limits.py`, `engine/pretrade.py`, `web/api.py`, `market/data_events.py`, `market/quotes.py`, `market/fyers_tbt_manager.py`.

## Baseline evidence (from this review)

Targeted suites were run on the current tree and are green, which proves the defects below are **not covered** by existing tests:

| Command scope | Result |
|---|---|
| `tests/test_verified_market_safety.py tests/test_trade_executor.py` | 47 passed |
| `tests/test_risk_limits.py tests/test_risk_gate.py tests/test_order_lifecycle.py tests/test_modes.py tests/test_auth_security.py tests/test_web_auth.py tests/test_reconciliation_typed.py tests/test_reconciliation_unavailable.py tests/test_execution_gate.py tests/test_order_execution_boundary.py` | 139 passed |
| `tests/test_live_oms_p3b.py tests/test_broker_gtt_oco.py tests/test_broker_exceptions.py tests/test_execution_routing.py tests/test_broker_roles.py` | 92 passed |
| `tests/test_csrf_and_security.py tests/test_csrf_integration.py tests/test_mode_banner_mapping.py tests/test_preflight_endpoint.py tests/test_api_contracts.py` | 42 passed |

Full-suite results in this review are not a certification of the current tree. The prior checkpoint reported roughly 4,972 passed / 4 failed on an older tree. Test collection is clean (5,120 collected, 17 deselected by markers, no import errors). There are **0** first-party TODO/FIXME/XXX/HACK markers and **0** committed logs/DBs/binaries/secrets; the hygiene problems are untracked local artifacts and untracked safety tests, not leaks.

Two defects were reproduced directly (Appendix A): synthetic futures quotes classify as `LIVE`, and a preflight run under `TRADING_MODE=EXECUTE` reports `SIMULATE`.

## If you can only complete ten things, do these first

1. **SEC-01/02/03** — close unauthenticated credential, mode and onboarding writes (`web/api.py`, `config/credentials.py`).
2. **SEC-04** — add Host/Origin validation and a sidecar token for local mode.
3. **DATA-01/02/03** — never label synthetic or TBT top-of-book data `LIVE`; stop fabricating OHLC/volume.
4. **BRK-01** — translate `SL_LIMIT`/`SL_MARKET` correctly in every adapter (a protective stop must not become a market order).
5. **BRK-02/06** — stop fabricating fills; preserve the broker order id on accepted-but-not-terminal responses.
6. **EXEC-01/02** — never leave an order `SUBMITTING` after a local rejection; make `UNKNOWN_FREEZE` recoverable.
7. **EXEC-03/04** — ingest fills on `OPEN` and via sync; fix the reconciliation schema mismatch.
8. **RISK-01/02/03** — put a real risk gate (notional, position, daily loss, tilt) inside the central order path.
9. **EXEC-23** — emergency flatten must never report paper or unverified outcomes as live liquidations.
10. **OPS-01** — preflight must report `EXECUTE`/`OBSERVE`/`SIMULATE` truthfully.

**Do TEST-06 first:** `tests/test_verified_market_safety.py` and 28 other safety tests, plus `verified-market-safety.yml`, are untracked — CI never runs them, and the workflow references eight files that are not in git. Commit the tests and a corrected workflow before anything else, or none of the fixes below are protected by CI.

Everything else is still required; this is the minimum containment set.

## Severity and sequencing rules

- **P0** = can lose money, enable unauthorized live trading, fabricate fills/prices, or leave the order ledger permanently wrong. Land before any live/paper pilot.
- **P1** = can silently bypass a control, corrupt accounting, or mislead the operator. Land before a controlled paper deployment.
- **P2** = maintainability, observability, dependency and test gaps. Land before release.
- One PR per task group. Do not mix unrelated formatting or refactors into a safety PR.
- Do not delete or weaken a test to obtain green. Add a regression test that fails on the current code first.
- Prefer deleting a dead control over advertising it. If a feature cannot be made truthful now, mark it `UNAVAILABLE` and block the action.

---

# Part 1 — Verified findings register

Each finding is evidence-backed. IDs are used in the task traceability matrix (Appendix B).

## A. Authorization, exposure and operator trust

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| SEC-01 | **P0** | Unauthenticated `POST /api/onboarding/credential` writes **any** environment variable and keychain entry. `set_credential` performs `os.environ[key] = value` with no key allowlist. An unauthenticated caller can set `ALLOW_LIVE_TRADING=1`, `LIVE_EXECUTION_QUALIFIED=1`, `TRADING_MODE=EXECUTE`, `OPENAI_BASE_URL` (API-key exfiltration), `PATH`, `PYTHONPATH`. | `web/api.py:3108-3118`; public allowlist `web/api.py:498-523`; `config/credentials.py:351-358` |
| SEC-02 | **P0** | `POST /api/mode` is public in every deploy mode. It mutates process-global `os.environ["TRADING_MODE"]`, gates only on `ALLOW_LIVE_TRADING`, and records no audit event. Any reachable client can flip a live desk to `EXECUTE`, `PAPER` or `OBSERVE`. | `web/api.py:1125-1186`; allowlist `web/api.py:503` |
| SEC-03 | **P0** | `/api/onboarding/complete` is public and writes `TRADING_MODE`, `TOTAL_CAPITAL`, `DEFAULT_RISK_PCT` into `os.environ` and `.env` with no range validation. It bypasses even the `ALLOW_LIVE_TRADING` check in `POST /api/mode`. | `web/api.py:3378-3423` |
| SEC-04 | **P0** | Local-mode auth trusts socket peer `127.0.0.1` with no `Host`/`Origin` validation and no sidecar token. DNS rebinding (or any local process/OS user) reaches every `/api/*` route unauthenticated. | `web/api.py:556-560`; no `TrustedHostMiddleware` |
| SEC-05 | **P0** | In default deploy mode, `/auth/signup` is open and `docker/Dockerfile` binds `0.0.0.0`. The documented raw `docker run` path therefore exposes a service where anyone can create an account and obtain a session for all order/portfolio routes. | `web/auth.py:322-348`; `docker/Dockerfile:50`; `docs/happy-flows.md` |
| SEC-06 | **P1** | `/stream/*` SSE endpoints and `/ws/*` WebSockets bypass the HTTP auth middleware. Alert payloads include symbol, LTP, trigger, target, stop and actionable plan. No connection cap. | `web/api.py:4108-4265`; `web/sse.py:72-75` |
| SEC-07 | **P1** | Public onboarding status leaks capital, risk %, mode, AI provider and broker connectivity. `/docs`, `/redoc`, `/openapi.json` are public. | `web/api.py:3078-3105`, `:368-374` |
| SEC-08 | **P1** | SSRF: public `POST /api/onboarding/test-provider` accepts an arbitrary `http` base URL and sends `Authorization: Bearer <key>` to it. | `web/api.py:3160-3174` |
| SEC-09 | **P1** | Public `POST /api/onboarding/setup-provider` runs blocking `subprocess.run` on the event loop (300–600 s) and installs software unattended. | `web/api.py:3193-3354` |
| SEC-10 | **P1** | Sessions are in-memory only, cookie omits `Secure`/`__Host-`, signup can force-evict sessions after 1,000 entries, and login throttling is per-(IP,email) only. | `web/auth.py:266-309`, `:341-376`, `:230-258` |
| SEC-11 | **P1** | OAuth callbacks ignore `state`; Fyers postback has no signature verification and publishes accepted JSON into the order SSE channel. | `web/api.py:2527-2568`; `brokers/fyers.py:819-827`; `web/routers/market_data.py:900-936` |
| SEC-12 | **P2** | Error responses echo `str(exc)`; telemetry stores full URLs including OAuth `auth_code`/`request_token`; diagnostics can return them. | `web/api.py:428-490`, `:1447-1510`; `web/routers/orders_api.py:168` |
| SEC-13 | **P2** | No request-body size limit; batch order IDs and onboarding numbers are unbounded. | `web/routers/orders_api.py:84-85`; `web/api.py:3108-3110` |
| SEC-14 | **P1** | `assert_live_execution_allowed(account_id)` ignores `account_id`; no account allowlist exists despite the docstring. | `engine/modes.py:108-137` |
| SEC-15 | **P2** | A personal IP is hardcoded as `DEFAULT_SEBI_WHITELISTED_IP`, and mstock's OAuth callback is plain HTTP to that public IP. | `config/constants.py:101-115` |
| SEC-16 | **P1** | CSRF is enforced only when `DEPLOY_MODE == "self-hosted"`. Any other value — including the production overlay's `cloud` — checks only the session cookie and skips CSRF; strong-secret enforcement is likewise self-hosted-only. The documented production path is therefore weaker than the tested one. | `web/api.py:526-559`, `:418-423`; `docker/docker-compose.prod.yml:13` |

## B. Data provenance and market truth

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| DATA-01 | **P0** | `classify_data_state` labels `source="FALLBACK"` as `LIVE` for any provider not named `yfinance`/`yahoo`/`cache`/`unknown`. The cost-of-carry synthetic futures provider is therefore `LIVE`. Live pre-trade accepts `data_state == "LIVE"`, so an order can be validated against an invented futures price when the broker feed is down. Reproduced. | `market/data_events.py:76-84`; `market/quotes.py:596-634`; `engine/order_lifecycle.py:1517-1530` |
| DATA-02 | **P0** | The TBT depth parser never reads a last-traded price: `ltp = bids[0]["price"]` (or best ask). `_handle_depth_update` copies that into the central quote cache as `Quote.last_price` with `data_state="LIVE"`. Every TBT-subscribed symbol's "LTP" is top-of-book. | `market/fyers_tbt_manager.py:1423`, `:1299-1341` |
| DATA-03 | **P0** | The same TBT bridge fabricates OHLC (`open=high=low=close=ltp`) and `volume = tbq + tsq` (resting book quantity, not traded volume) and labels it `LIVE`. This violates SAFETY_CONTRACTS #22. | `market/fyers_tbt_manager.py:1320-1333`; `market/quotes.py:818-834` |
| DATA-04 | **P1** | `market/quotes.py` reads `_depth_cache` directly and does not call `is_fresh_tbt_depth`, so stale/expired depth is published as fresh. | `market/quotes.py:801-838` vs `market/fyers_tbt_manager.py:43-52` |
| DATA-05 | **P1** | `_enrich_quote` assigns `received_at = now` at enrichment, not the exchange/tick observation time. Off-market cached ticks can be re-stamped as fresh. | `market/quotes.py:206-218`, `:241` |
| DATA-06 | **P1** | Off-market quote-cache TTL is extended to 300 s while the `Quote.data_state` stays `LIVE`. | `market/quotes.py:773-790` |
| DATA-07 | **P1** | Synthetic futures are also produced in `ws_only` mode and returned through normal quote paths without a provenance gate. | `market/quotes.py:1015-1021` |
| DATA-08 | **P1** | `get_ltp` silently substitutes the previous session close when no last price is available and returns `0.0` on failure. Callers cannot distinguish a live trade, yesterday's close and an outage; paper fills, sizing and alerts consume it as an LTP. | `market/quotes.py:1085-1106` |

## C. Broker adapters and order-status truth

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| BRK-01 | **P0** | Canonical OMS order types `SL_LIMIT`/`SL_MARKET` exist in no adapter. Angel One/mstock default unknown types to `MARKET` (protective stop becomes an immediate market order); Fyers defaults to `LIMIT` at the stop price (often immediately marketable); Shoonya/Dhan/Kotak/Zerodha/Upstox/Groww pass the raw token and are rejected. | `engine/order_lifecycle.py:137-138`, `:1636`; `brokers/angelone.py:687-693`; `brokers/mstock.py:1585`; `brokers/fyers.py:2145-2157`; `brokers/stoxkart.py:410` |
| BRK-02 | **P0** | mstock `place_order` returns `average_price=order.price` and `filled_quantity=order.quantity` on HTTP 200 with no trade-book evidence. Fabricated full fill. | `brokers/mstock.py:1626-1632` |
| BRK-03 | **P0** | Fyers silently resubmits `place_order` after an auth-classified response, with no orderbook lookup or idempotency key. Can duplicate a live order. | `brokers/fyers.py:2208-2224` |
| BRK-04 | **P0** | Adapters use `[]`/`0` as the failure sentinel for positions, orders and funds. A failed read is indistinguishable from a flat account. Emergency flatten then reports success after touching nothing. | `brokers/fyers.py:1405-1428`, `:2593-2618`; `brokers/kotak.py:432`, `:469-475`; `brokers/mstock.py:739-771`, `:827-879`; `brokers/upstox.py:315-329`; `brokers/stoxkart.py:382`; `brokers/base.py:429-438` |
| BRK-05 | **P0** | Fyers `get_orders` inverts order types (`type==1`→MARKET though 1=LIMIT), hardcodes `exchange="NSE"`, and strips the venue. Sync therefore corrupts order semantics. | `brokers/fyers.py:2625-2640` vs `:2145-2157` |
| BRK-06 | **P0** | mstock/Stoxkart return `PLACED` on success; the OMS only handles `COMPLETE|OPEN|REJECTED`, so a genuinely accepted order freezes as `UNKNOWN_FREEZE` and its real broker ID is discarded. | `brokers/mstock.py:1628`; `brokers/stoxkart.py:426`; `engine/order_lifecycle.py:1645`, `:1800-1811` |
| BRK-07 | **P1** | Upstox passes non-existent dataclass kwargs (`metadata=`, `day_change=`, `avg_price=` on `Order`). `place_order` raises **after** the broker accepted the order, producing `UNKNOWN_FREEZE` for a live fill. It also hardcodes `NSE_EQ` for every exchange. | `brokers/upstox.py:219`, `:231`, `:251-255`, `:274-277`, `:376`, `:388`, `:406-407`; `brokers/base.py:21-66`, `:171-214` |
| BRK-08 | **P1** | Angel One hardcodes `"symboltoken": ""`; every NORMAL order is malformed. | `brokers/angelone.py:542-556`, `:631-640` |
| BRK-09 | **P1** | Kotak resolves the instrument token then never includes it; forwards raw platform codes; returns `OPEN` with an empty id on 2xx without an order id. | `brokers/kotak.py:851-875` |
| BRK-10 | **P1** | Dhan hardcodes `securityId=""` and defaults missing status to `OPEN`. | `brokers/dhan.py:254-268` |
| BRK-11 | **P1** | `_try_auto_restore_sessions` assigns `is_testing` only inside the Fyers branch, then uses it in mstock/Shoonya/Kotak branches. A `NameError` is swallowed, so those brokers never auto-restore when Fyers is absent. | `brokers/session.py:185-282` |
| BRK-12 | **P1** | Broker token files are written with default permissions (0644 under umask 022); no `chmod 0600`. Some persist API secrets. | `brokers/zerodha.py:65-75`; `brokers/fyers.py:776-786`; `brokers/angelone.py:155-170`; `brokers/shoonya.py:144-169`; `brokers/kotak.py:355-374`; `brokers/mstock.py:403-430`; `brokers/groww.py:63-67`; `brokers/stoxkart.py:133-145`; `brokers/upstox.py:93-102` |
| BRK-13 | **P1** | Fyers ignores rate-gate/limiter rejection, bypassing the emergency order cap. | `brokers/fyers.py:2206`, `:2272`, `:2599`; `market/fyers_rate_gate.py:465-477` |
| BRK-14 | **P1** | Adapter input fallbacks silently change intent: unknown side → SELL, unknown product → CNC/MIS/INTRADAY, unknown exchange → NSE cash, unresolved token → raw symbol. | `brokers/fyers.py:2192-2193`; `brokers/mstock.py:1582-1584`, `:303`; `brokers/stoxkart.py:408-411`; `brokers/angelone.py:684` |
| BRK-15 | **P2** | Shoonya treats missing `stat` as success and missing order status as `OPEN`; Stoxkart submits TOTP `"123456"` when no secret is configured. | `brokers/shoonya.py:274`, `:692`; `brokers/stoxkart.py:188` |
| BRK-16 | **P2** | Stoxkart `is_authenticated` is a property overriding an abstract method; generic callers raise `TypeError`. Quote signature/return type also diverge. | `brokers/stoxkart.py:234-236`, `:351-382` |
| BRK-17 | **P1** | `get_execution_broker()` falls back to the primary broker even if that broker's role is data-only, contradicting the explicit-role invariant. | `brokers/session.py:376-391`, `:394-401` |

## D. Order lifecycle, OMS and ledger

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| EXEC-01 | **P0** | Local safety gates run **after** the atomic `CONFIRMED → SUBMITTING` transition. If the pilot gate, instrument resolution or pre-trade validation raises, the order is stranded in `SUBMITTING` with no broker call. SAFETY_CONTRACTS #12 requires it to remain `CONFIRMED`. | `engine/order_lifecycle.py:1206-1219`, `:1470-1595` |
| EXEC-02 | **P0** | `UNKNOWN_FREEZE` clears `broker_order_id = None` even when the broker response contained an authentic ID. No code transitions `UNKNOWN_FREEZE` back. `sync_execution_orders` only matches rows with a non-null broker ID. Recovery is manual DB surgery. | `engine/order_lifecycle.py:1800-1811`, `:1907-1940`, `:2943-2949` |
| EXEC-03 | **P0** | Live fills are almost never ingested: both primary adapters return `OPEN`, and ingestion runs only for `FILLED|PARTIALLY_FILLED`. `sync_execution_orders` changes status but never ingests fills. The Fyers postback only publishes SSE. | `engine/order_lifecycle.py:1656-1668`, `:2912-2999`; `brokers/fyers.py:2230-2234`; `brokers/zerodha.py:393-397`; `web/routers/market_data.py:900-933` |
| EXEC-04 | **P0** | Reconciliation reads `qty`/`avg_price`, but `get_internal_ledger_snapshot` emits `quantity`/`average_price`. Every internal position is seen as qty 0 → false `DISPUTED`. Reproduced. | `engine/reconciliation.py:111-141`; `engine/order_lifecycle.py:2870-2885`; `web/routers/orders_api.py:446-453` |
| EXEC-05 | **P0** | Reconciliation defaults both cash sides to `1_000_000.0`, and `allow_trading` is true for `PARTIAL`. A funds-parse failure becomes `broker_cash=0` → `PARTIAL` → trading allowed. | `engine/reconciliation.py:74-75`, `:182-202`; `web/routers/orders_api.py:391-394` |
| EXEC-06 | **P1** | Reconciliation keys positions by bare symbol, collapsing distinct exchange/product/expiry rows last-wins, and treats broker zero-qty rows as HIGH `MISSING_IN_LEDGER`. | `engine/reconciliation.py:96-136` |
| EXEC-07 | **P1** | `sync_execution_orders` has no per-order exception isolation, lacks `EXPIRED`/numeric status normalization, and never updates `filled_quantity`/`average_fill_price` (columns do not exist). Partial-then-cancel loses the filled quantity. | `engine/order_lifecycle.py:2912-2999`; `brokers/fyers.py:2635` |
| EXEC-08 | **P1** | Paper sliced execution: completed child fills are discarded if a later tranche rejects (aggregate becomes REJECTED) or rests OPEN; recorded fill price falls back to preview price, not the broker fill. | `engine/order_lifecycle.py:1299-1401` |
| EXEC-09 | **P1** | Paper rest orders store `PAPER-OPEN-{PAPER-…}`, but `PaperBroker.cancel_order` expects the native id, so paper cancels never confirm and stick in `CANCEL_PENDING`. | `engine/order_lifecycle.py:1292-1298`, `:967-1001`; `engine/paper.py:241-267` |
| EXEC-10 | **P1** | `cancel_order_intent` sets `CANCEL_PENDING` before contacting the broker; a crash or a rejected cancel leaves it pending forever. | `engine/order_lifecycle.py:934-1001` |
| EXEC-11 | **P1** | Multi-leg auto-unwind calls `preview_order_intent(price=0.0, order_type="MARKET")`, which always raises `price must be positive`; the error is swallowed and the caller unconditionally reports `LEGGING_FAILED_UNWOUND` + `unwind_performed=True`. | `engine/multi_leg_executor.py:304-335`, `:276-279` |
| EXEC-12 | **P1** | Multi-leg treats `OPEN` legs as filled and marks the spread `FILLED`; `net_fill_price` is computed from requested limit prices, not fills. A naked short can be reported as a completed defined-risk spread. | `engine/multi_leg_executor.py:208-216`, `:255-295` |
| EXEC-13 | **P1** | Multi-leg MARKET legs pass `price=0.0` to preview, which validation rejects, so any leg without a limit price fails. | `engine/multi_leg_executor.py:194-201`, `:244-251`; `engine/order_lifecycle.py:412-418` |
| EXEC-14 | **P1** | Wing-lock invents `₹10.00` when no price source exists and unconditionally sets `free_roll_locked=True` and returns `SUCCESS`, even when the order rests OPEN or is rejected. | `engine/order_lifecycle.py:3055-3135` |
| EXEC-15 | **P1** | `_record_order_event` reads the chain head and inserts on an autocommit pooled connection with no `BEGIN IMMEDIATE`; concurrent writers fork the audit chain. Any persistence failure is swallowed at debug level, so a missing event after a broker call is invisible. | `engine/order_lifecycle.py:306-361`, `:359-361` |
| EXEC-16 | **P1** | `orders_ledger.account_id` is never populated; idempotency keys are globally scoped, not per account. Any authenticated user who knows an order id can confirm/execute it. | `engine/order_lifecycle.py:694-725`, `:551-563` |
| EXEC-17 | **P1** | The preview hash omits `stop_loss`, `target` and `auto_gtt_oco`. Re-previewing with the same key and changed protection silently returns the old intent. | `engine/order_lifecycle.py:557-563`, `:425-459` |
| EXEC-18 | **P1** | `confirm_order_intent` silently skips the 60-second TTL if `created_at` cannot be parsed. | `engine/order_lifecycle.py:819-840` |
| EXEC-19 | **P1** | `get_internal_ledger_snapshot` always returns `is_complete: True` and `data_quality_status: "AVAILABLE"`; `PENDING_FACTS` is never persisted; the `INGESTION_FAILED` query filters an `account_id` that is never written. | `engine/order_lifecycle.py:1665-1668`, `:2555-2570`, `:2887-2907` |
| EXEC-20 | **P1** | PaperBroker fills at ₹0 when no quote exists; lifecycle books the preview price instead, so the two stores diverge. | `engine/paper.py:314-347`; `engine/order_lifecycle.py:1375` |
| EXEC-21 | **P1** | PaperBroker short accounting: opening a short never sets `avg_price`, credits the full notional as realized PnL, and credits margin at the exit price. | `engine/paper.py:380-394` |
| EXEC-22 | **P1** | PaperBroker state is a JSON file read-modify-written with no lock; every `execute_order_intent` builds a fresh instance, so concurrent executions lose fills. | `engine/paper.py` state load/save; `engine/order_lifecycle.py:1246` |
| EXEC-23 | **P1** | Emergency flatten: ignores `cancel_order` return values and appends every attempt to `cancelled_orders`; Fyers numeric statuses never match the cancel filter; in EXECUTE mode a real broker without `square_off_intraday_positions` falls back to `PaperBroker()` and reports **paper** closures as live liquidations. | `engine/order_lifecycle.py:3197-3245` |
| EXEC-24 | **P2** | `_generate_order_id` uses 32 bits (`uuid4().hex[:8]`); collision surfaces as an unhandled PK error. | `engine/order_lifecycle.py:142-145` |
| EXEC-25 | **P2** | `engine/oms.py` has a real transition table but is unused in production; its `fill()` mutates state before validating the transition, allows a second `PARTIAL→PARTIAL` to raise after mutation, permits `FILLED` below quantity, and persists non-atomically without replaying JSONL. | `engine/oms.py:478-517`, `:288-307`, `:340-406` |
| EXEC-26 | **P1** | `outbox_worker.dispatch_channel_entry` returns `True` for live TELEGRAM and unknown channels without delivering, so the worker acknowledges and permanently drops alerts. | `engine/outbox_worker.py:49-84` |
| EXEC-27 | **P1** | No startup or scheduled recovery job for `SUBMITTING`, `UNKNOWN_FREEZE`, `PENDING_FACTS` or `INGESTION_FAILED`; `sync_execution_orders` is only reachable from `GET /api/reconciliation`. | repo-wide call search |

## E. Risk and pre-trade enforcement

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| RISK-01 | **P0** | Risk limits are not enforced on the real order path. `risk_limits.check` is called only by the SIMULATE-only legacy CLI executor. Web, Telegram, OMS and multi-leg never call it. | `engine/order_lifecycle.py` (no call); `engine/trade_executor.py:308-316` is the sole caller |
| RISK-02 | **P0** | `evaluate_preflight`/`check` never evaluates order size. A ₹1,450-crore order passes on a fresh DB. Reproduced. | `engine/risk_limits.py:194-345` |
| RISK-03 | **P0** | `record_trade` defaults `pnl=0.0` and the only production caller omits PnL, so `MAX_DAILY_LOSS` and consecutive-loss/tilt lockout can never trigger. | `engine/risk_limits.py:349-374`; `engine/trade_executor.py:345-350` |
| RISK-04 | **P1** | `MAX_DAILY_DRAWDOWN_PCT` is dead config (defined, never read). | `engine/risk_limits.py:110-113` |
| RISK-05 | **P1** | Pre-trade buying power passes when `available_cash is None` and for every SELL. No holdings check for equity sells and no short-option margin. | `engine/pretrade.py:371-429` |
| RISK-06 | **P1** | The live call site never supplies `prev_close`, `portfolio_value` or `daily_pnl`, so price-band and portfolio-risk gates always pass; the 3% daily-loss advisory is inert and warning-only. | `engine/order_lifecycle.py:1566-1584`; `engine/pretrade.py:337-364`, `:459-494` |
| RISK-07 | **P1** | `_gate_market_session` is weekday+clock only and ignores exchange holidays; `_gate_price_band` defaults every stock to ±20%. | `engine/pretrade.py:174-266`, `:337-364` |
| RISK-08 | **P1** | `engine/margin_engine.py` (SPAN/exposure/ELM/calendar-spread checks) has no production caller. | `engine/margin_engine.py:86-232`; caller search |
| RISK-09 | **P1** | `risk_gate` returns `allowed=True` with `max_qty=0`; its only consumer checks `.allowed`. The only caller supplies no portfolio/prices/VIX/DTE, so most checks never run; the no-price branch invents `position_limit/100` shares. | `engine/risk_gate.py:257-273`, `:364-375`; `agent/multi_agent.py:1606-1632` |
| RISK-10 | **P1** | Risk-gate exceptions are swallowed and analysis proceeds (fail-open). Sector lookup failures silently return zero exposure. | `agent/multi_agent.py:1631-1632`; `engine/risk_gate.py:109-114` |
| RISK-11 | **P1** | Risk counters are global, not per account or mode; paper fills can exhaust the live budget and two accounts share one loss/tilt budget. | `engine/risk_limits.py:119-190` |
| RISK-12 | **P1** | `date.today()` is used for the trading-day boundary instead of IST. On a UTC host the limit day rolls at 05:30 IST; on US-Pacific it rolls mid-session. | `engine/risk_limits.py:148-149`; `engine/risk_gate.py:156`; 12 total `date.today()` sites |
| RISK-13 | **P2** | `remaining_loss_room` sign is inverted while the day is losing (returns negative "room"). | `engine/risk_limits.py:383-393` |
| RISK-14 | **P2** | Capital env vars disagree: `TOTAL_CAPITAL` (default 200,000) vs `TRADING_CAPITAL` (default 100,000); onboarding writes `TOTAL_CAPITAL`, skills expose `TRADING_CAPITAL`. | `engine/risk_gate.py:59-63`; `engine/trade_executor.py:40-42`; `web/skills.py:3363`; `config/credentials.py:182` |
| RISK-15 | **P1** | Kill-switch persistence fails open: `_load_state` swallows every error and resets `_active = {}` (a corrupt state file silently drops a SYSTEM halt); `_persist_state`/`_audit` swallow failures at debug level while `activate()` still returns success. ISO-string expiry comparison is timezone-fragile. | `engine/kill_switch.py:98-108`, `:111-135`, `:226-228` |

## F. Quant, options and portfolio correctness

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| QUANT-01 | **P1** | 0-DTE is computed as 1 day: `max(1, (exp - date.today()).days)` treats expiry day and expired contracts as T=1/365. | `analysis/options.py:110-129` |
| QUANT-02 | **P1** | The Black-Scholes fallback applies the call theta formula to puts (`-rK e^{-rT} N(d2)` instead of `+rK e^{-rT} N(-d2)`). | `analysis/options.py:214-228` |
| QUANT-03 | **P1** | Half-Kelly floors negative edge at 2% and is seeded with invented `win_rate=0.55`, `profit_factor=1.8`. | `engine/position_sizer.py:853-861`, `:486-487` |
| QUANT-04 | **P1** | Missing VIX returns multiplier 1.0 ("NORMAL_MARKET"), granting a full risk budget, contrary to SAFETY_CONTRACTS #23. Hierarchical sizing defaults capital to ₹1,00,000. | `engine/dynamic_risk.py:268-279`, `:557`, `:616-628` |
| QUANT-05 | **P1** | Portfolio Greeks treats every position as linear `EQUITY`, defaults `dte=7`, and substitutes hardcoded NIFTY 24,500 / BANKNIFTY 52,000 spots. | `engine/portfolio_greeks.py:132`, `:149-175`; `web/api.py:3685-3726` |
| QUANT-06 | **P1** | Backtests default to same-bar close fills with zero costs (`execute_on_next_bar=False`, `conservative_fills=False`); `options_backtest` applies no charges; `batch_backtest` uses a stale duplicate charge model. | `engine/backtest.py:909-913`; `engine/options_backtest.py:949-954`, `:1120`; `engine/batch_backtest.py:72-123` |
| QUANT-07 | **P2** | PaperBroker `available_cash = cash - pos_margin` double-deducts margin already debited from cash. | `engine/paper.py:147-161` |
| QUANT-08 | **P2** | Portfolio `net_gamma` is always 0 (`PositionRow` has no gamma field). | `engine/portfolio.py:396-401`, `:441` |
| QUANT-09 | **P2** | `portfolio_greeks` hedge conversion uses a 25-share NIFTY lot while `market/instruments.py` uses 65. | `engine/portfolio_greeks.py:206` vs `market/instruments.py:35` |
| QUANT-10 | **P2** | The 14:40 0-DTE gate fires only for `segment == "FNO_INDEX"`; index options tagged `OPTIONS`/`EQUITY` bypass it. | `engine/session_runway.py:324-330` |

## G. Operator surface, preflight and agent

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| OPS-01 | **P0** | Preflight reports `SIMULATE` for both `TRADING_MODE=EXECUTE` and `OBSERVE`; it only recognises the legacy string `LIVE`. A live desk is told "No real broker orders will be placed." Reproduced. | `engine/preflight.py:423-425` |
| OPS-02 | **P1** | Telegram handlers (`/flatten`, `/analyze`, `/scan`, callbacks) have no chat/user authorization. Any chat that can reach the bot can run them. `exec_live` is still gated by env flags, but `/flatten` follows the process mode. | `bot/telegram_bot.py:2505-2532`, `:2534-2707`, handlers at `:3369-3371`; no allowlist search hit |
| OPS-03 | **P1** | Tool `permission="ask"` is never enforced. `ToolRegistry.execute` only denies `"deny"`; `execute_trade` runs immediately despite the documented confirmation gate. | `agent/tools.py:128-149`; `agent/harness.py:238-345`; no `.permission(` check |
| OPS-04 | **P1** | Telegram `exec_paper` references `res.executed_legs`/`res.failed_legs` on `DefinedRiskSpreadExecutionResult`; verify the real fields before use. It also hardcodes "PAPER SPREAD DISPATCHED". | `bot/telegram_bot.py:2556-2615` |
| OPS-05 | **P1** | `POST /api/mode` and mode switches write no audit event. | `web/api.py:1125-1186` |
| OPS-06 | **P2** | `CLAUDE.md` says live execution requires only `ALLOW_LIVE_TRADING=1`; the code also requires `LIVE_EXECUTION_QUALIFIED=1` and `PILOT_ALLOW_LIVE_EXECUTION=1`. Operators will misdiagnose a block. | `CLAUDE.md` vs `engine/modes.py:108-137`, `engine/pilot_safety.py:35-63` |
| OPS-07 | **P2** | No lockfile, no `pip-audit`/`npm audit`; `[dev]` omits `pytest-cov`; Dependabot covers only `pip` (not npm or Actions); Actions use mutable major tags; `build-mac.yml` creates a Release on tag push with no test job and no `permissions:` block; the `fyers` extra still exposes an acknowledged-vulnerable SDK. | `pyproject.toml:34-97`; `.github/dependabot.yml`; `.github/workflows/build-mac.yml:91-100` |
| OPS-08 | **P2** | 2,819 broad `except Exception` handlers across `engine/market/brokers/web/agent/bot/app/analysis`; several return zero/empty values (see BRK-04). Giant modules: `auto_alert_engine.py` 17,949 LOC, `web/skills.py` 9,132, `bot/alert_templates.py` 7,779, `alert_scrutiny.py` 6,082; 55 first-party files exceed 1,000 LOC; 10 test files exceed 1,000 LOC (largest 5,014). | file metrics |
| OPS-09 | **P2** | Local artifact sprawl: `data/eod_bars.db` ~543 MB, `fyersRequests.log` ~210 MB, `fyersApi.log` ~19 MB, `.logs/` ~19 MB, `.pytest_trading_platform*` ~500 MB, `tmp_test.db`, stray `1/instrument_master.db`. None is git-tracked (`.gitignore` is correct), but they slow tooling and hide data-integrity skips. `.gitignore` lists `package-lock.json` although it is tracked. | disk inventory; `git ls-files` |
| OPS-11 | **P2** | `engine/paper_execute.py` has zero importers (the CLI `paper-execute` routes through `engine/trade_executor.py`); `engine/eod_store.py` and `market/eod_store.py` share a name with different schemas. | import search; `app/repl.py:2034-2048` |
| OPS-10 | **P2** | Two divergent execution helpers (`engine/trade_executor.py`, `engine/paper_execute.py`) plus `engine/oms.py`; unclear authority invites future bypass. | module inventory |

## H. Test and CI gaps

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| TEST-01 | **P1** | An autouse fixture monkeypatches `analysis.regime_governor._fresh_live_vix` to `15.0` for nearly every test (only two modules exempt), masking the production missing-VIX path. | `tests/conftest.py:89-101` |
| TEST-02 | **P1** | No regression test covers any P0 in this register: risk-limit integration, order-type translation, data-state classification, onboarding auth, mode POST auth, reconciliation schema, TBT LTP, flatten truth. Targeted suites are green (Appendix A6). | test inventory |
| TEST-03 | **P1** | No coverage threshold; `.github/workflows/verified-market-safety.yml` is untracked and therefore does not run; no lockfile. | `.github/workflows/`, repo status |
| TEST-04 | **P2** | Nine test modules set `ALLOW_LIVE_TRADING`/`LIVE_EXECUTION_QUALIFIED`/pilot flags. Confirm each restores env and none leaks across tests; `tests/conftest.py:45` correctly pops qualification by default. | `tests/test_{modes,order_lifecycle,trade_executor,broker_mstock,csrf_and_security,live_oms_p3b,pilot_data_foundation,telegram_interactive_actions}.py` |
| TEST-05 | **P2** | `DEPLOY_MODE=test` is set globally, so most endpoint tests never exercise self-hosted auth/CSRF; only opt-in auth tests do. This let SEC-01/02/03 ship green. | `tests/conftest.py:50`, `:197-233` |
| TEST-06 | **P0** | The central safety suite and the safety workflow are **untracked**. `git ls-files` includes only `ci.yml` and `build-mac.yml`; `tests/test_verified_market_safety.py` and 28 other safety tests are untracked, and `verified-market-safety.yml` references eight files that are not tracked. CI checks out git contents only, so none of it runs. Committing the workflow as-is would fail. | `git status`; `.github/workflows/verified-market-safety.yml:16,21`; `docs/SAFETY_CONTRACTS.md` change procedure step 4 |
| TEST-07 | **P1** | The documented pre-commit gate does not run the safety/auth suites. `validate_all.py --fast` runs 8 smoke files, none of which is a safety/auth contract; `.githooks/pre-push` calls `shift_left_check.py` without `--full`, whose invariant list omits `test_modes.py`, `test_csrf_and_security.py`, `test_risk_limits.py` and `test_verified_market_safety.py`. Pre-push prints "Remote CI parity guaranteed", which is false. | `scripts/validate_all.py:136-166`; `.githooks/pre-commit:13`, `pre-push:18`; `scripts/shift_left_check.py:430-445` |
| TEST-08 | **P1** | Tracked tests and `AGENTS.md` encode stale expiry weekdays that contradict the effective-dated code (NSE Tuesday / BSE Thursday). Examples: NIFTY "Thursday" in `test_alert_templates.py:689,713`, `test_fyers_tbt_depth.py:454-460`, `test_regime_governor.py:65`; `AGENTS.md:239-240`; a SEBI test comment says Thursday while asserting Tuesday (`test_sebi_expiry_mandate_invariants.py:52-53`). `resolve_expiry_cycle` classifies weekly/monthly by month rollover, so stale dates can still pass. | files as cited; `market/rule_schedule.py:11-17` |
| TEST-09 | **P2** | 78 `test_*` functions contain no assertion (rely on "does not raise"); 4 assert only on mock calls; one is vacuous (`test_harness.py:169-174` builds an empty registry and asserts a tool is absent). | AST scan; cited lines |
| TEST-10 | **P2** | No coverage measurement or threshold; `pytest-cov` is absent from `[dev]`; 208 wall-clock/`time.sleep` uses in tests without `freezegun`/`time-machine`, a flake source. `data/*` is gitignored, so `test_data_integrity_audit.py` silently skips in CI. | `.github/workflows/ci.yml`; `pyproject.toml:92-97`; `tests/test_data_integrity_audit.py:71,103,122` |

---

# Part 2 — Implementation plan

## Operating rules for the implementing model

1. **One task group per branch/PR.** Do not batch P0 auth fixes with quant refactors.
2. **Real boundary tests only.** A test that calls a helper directly while the production caller remains broken does not count (see prior checkpoints).
3. **No fabricated success in tests.** Use controlled broker stubs that can return `UNKNOWN`, timeouts, partial fills and unauthenticated states.
4. **Fail closed.** Unknown status, missing cash, missing quote, missing token → unavailable/blocked. Never default to `OPEN`, `LIVE`, `0`, `100000`, or `₹10`.
5. **Preserve existing user changes.** The working tree is large; never reset or checkout files.
6. **Record evidence.** After each task, append command output (test names + counts) to the task's completion note.
7. **Stop and surface** if a fix requires enabling live qualification, changing an exchange rule, or deleting a safety test.

## Phase 0 — Containment (land first; can ship independently)

### TASK P0-A — Lock down privileged onboarding and mode endpoints
**Fixes:** SEC-01, SEC-02, SEC-03, SEC-05, OPS-05
**Files:** `web/api.py`, `web/auth.py`, `config/credentials.py`
**Steps:**
1. Replace the path-only public allowlist with a method-aware allowlist. `GET /api/mode` stays public; `POST /api/mode` requires an authenticated session (self-hosted) or loopback + Host/Origin validation (local).
2. Remove the blanket `/api/onboarding/` public exemption. Allow only a **minimal** `GET /api/onboarding/status` before first-run, returning presence booleans (`onboarding_complete`, `broker_connected`, `ai_provider_set`) and never capital/risk/mode/provider values; require a one-time setup secret (generated at launch, written to the app-data dir with 0600, printed once to the console) for onboarding mutations when `user_count() == 0`. After setup, require a session.
3. In `set_credential`, reject keys outside `KNOWN_CREDENTIALS | SETTING_KEYS | {"AI_PROVIDER","AI_MODEL",...}`. Explicitly deny runtime mutation of `ALLOW_LIVE_TRADING`, `LIVE_EXECUTION_QUALIFIED`, `PILOT_ALLOW_LIVE_EXECUTION`, `TRADING_MODE`, `DEPLOY_MODE`, `PATH`, `PYTHONPATH`, `LD_PRELOAD`, `*_BASE_URL` (unless the key is in the allowlist).
4. `POST /api/mode` must call `record_audit_event("MODE_CHANGED", actor, {from,to})` and require both `ALLOW_LIVE_TRADING=1` and `LIVE_EXECUTION_QUALIFIED=1` to enter `EXECUTE` (delegate to `engine.modes.assert_live_execution_allowed` for EXECUTE).
5. Validate `OnboardingCompleteRequest`: `capital > 0`, `0 < risk_pct <= 10`, `trading_mode` in `{PAPER,SIMULATE,DEMO,OBSERVE}` only. Never allow `EXECUTE` through onboarding. Do not write secrets into `.env`; if writing config, set 0600.
6. Set `Secure` + `__Host-` cookie in self-hosted mode and reject signup unless `ALLOW_SIGNUP=1` or first-run.
**Tests (new `tests/test_authz_privileged_endpoints.py`):**
- Unauthenticated `POST /api/onboarding/credential` → 401/403 in self-hosted.
- Attempting to set each forbidden key → 400/403, env unchanged.
- Unauthenticated `POST /api/mode` → 401/403; GET still 200.
- `POST /api/onboarding/complete` with `trading_mode=EXECUTE` or negative risk → 422.
- Mode change writes a `MODE_CHANGED` audit row.
**Acceptance:** No public route can mutate execution flags, mode, capital or credentials. Audit row exists for every mode change.

### TASK P0-B — Local-mode request authenticity
**Fixes:** SEC-04, (with SEC-10)
**Files:** `web/api.py`, `app/repl.py`, `macos-app/src/main/index.js`, `docker/Dockerfile`
**Steps:**
1. Add `TrustedHostMiddleware` allowing only `127.0.0.1`, `localhost`, `[::1]` and the configured deployment host.
2. On mutating methods in local mode, reject requests with a present `Origin` that is not an allowed origin.
3. Add a per-launch `SIDECAR_TOKEN` (32 bytes, memory + 0600 file). The Electron parent passes it to the renderer via preload and to the sidecar; requests must send `X-Sidecar-Token` in local mode. Keep a compatibility grace only for `CHANAKYA_TESTING=1`.
4. Set `ENV DEPLOY_MODE=self-hosted` in `docker/Dockerfile` (the container must keep `--host 0.0.0.0` for port publishing) and change the documented run command to `docker run --rm -p 127.0.0.1:8765:8765 -e DEPLOY_MODE=self-hosted ...`.
5. Force an explicit `DEPLOY_MODE`; if unset, fail closed with a startup error (or default to `local` only when bound to loopback).
**Tests:** Host-header spoof (`Host: evil.example`) → 400/403; missing token on mutating local request → 401; allowed loopback+token → 200.
**Acceptance:** DNS rebinding and local non-Electron processes cannot reach mutating routes.

### TASK P0-C — Protect streams and WebSockets
**Fixes:** SEC-06
**Files:** `web/api.py:4100-4265`, `web/sse.py`
**Steps:**
1. Extend the authenticated prefix set to `/stream/` and `/ws/`.
2. Authenticate the WebSocket handshake using `ws.cookies`/`ws.client` and the same session/token rules.
3. Cap concurrent SSE/WS connections per user/channel and add a heartbeat timeout.
4. Validate `/stream/prices?symbols=` against the instrument master, cap the set, and evict idle symbols.
**Tests:** self-hosted unauthenticated GET `/stream/alerts` → 401; unauth WS handshake rejected; symbol-set growth capped.
**Acceptance:** No alert/price data is readable without auth; connection flooding is bounded.

### TASK P0-D — Truthful quote provenance and TBT handling
**Fixes:** DATA-01..07
**Files:** `market/data_events.py`, `market/quotes.py`, `market/fyers_tbt_manager.py`, `engine/order_lifecycle.py`, `engine/pretrade.py`
**Steps:**
1. Rework `classify_data_state`:
   - `price <= 0` → `UNAVAILABLE`.
   - `source == "EOD_SNAPSHOT"` → `EOD`.
   - `source == "FALLBACK"` → `DEGRADED`.
   - `source == "CACHE"` → `DEGRADED` (with age).
   - `source in {"STREAM","REST"}` → `LIVE` only when `provider` is in an explicit verified-provider allowlist; otherwise `DEGRADED`.
   - Unknown/missing provenance → `UNAVAILABLE`.
2. `_futures_quotes` must emit `source="SYNTHETIC"` (add to `DataSource`) and `quality_flags=("COST_OF_CARRY_ESTIMATE","SYNTHETIC_PRICE")`. Do not populate OHLC/volume; leave them `None`. Never return a synthetic price from a live-execution quote lookup.
3. TBT parser: do not derive `ltp` from the book. If the packet has an explicit last-traded field, read and validate it; otherwise set `ltp=None`/unavailable and keep depth only. Do not write a `Quote` with fabricated OHLC/volume into `_QUOTE_CACHE`. If a real ltp field exists, propagate it with the packet timestamp.
4. `market/quotes.py` TBT branch must call `is_fresh_tbt_depth` and copy only verified fields (bid/ask/source/provider/received_at). Remove `open=high=low=close=ltp`, `volume=tbq+tsq`, and `vwap=rolling_tick_vwap` as `Quote` fields.
5. Pre-trade live execution must require: `quote.source in {"STREAM","REST"}`, `quote.data_state == "LIVE"`, `quote.provider` in the verified allowlist, `quote.age_seconds` finite and ≤ 60. Add an explicit unit test for a synthetic quote → blocked.
6. Do not re-stamp `received_at` at enrichment; preserve the observation/receipt time. Add `cached_at` if needed for cache-age display.
7. Split `get_ltp` into two explicit APIs: `get_live_ltp(instrument)` returning a typed `(price, provenance)` or `UNAVAILABLE`, and `get_reference_price(instrument)` for off-market/close use. Update sizing/paper/alerts to use `get_live_ltp` for actionable decisions; never let a prior close or `0.0` masquerade as an LTP.
**Tests (new `tests/test_data_provenance_truth.py`):**
- `classify_data_state(FALLBACK, cost_of_carry_synthetic, 100)` → `DEGRADED` (fails today).
- `get_quote` on a synthetic futures path returns `data_state != LIVE` and no OHLC/volume.
- TBT packet → quote has no fabricated `last_price`; depth remains available.
- Stale TBT snapshot → excluded.
- Live pre-trade with synthetic/stale/unknown quote → `is_eligible=False`.
**Acceptance:** No path labels synthetic or depth-only data `LIVE`; live execution cannot consume synthetic prices.

### TASK P0-E — Canonical order-type/status/product translation
**Fixes:** BRK-01, BRK-06, BRK-14
**Files:** new `brokers/order_types.py`; `brokers/{fyers,zerodha,angelone,mstock,stoxkart,shoonya,dhan,kotak,groww,upstox}.py`; `engine/order_lifecycle.py`
**Steps:**
1. Create a single module with:
   - `CANONICAL_ORDER_TYPES = {"MARKET","LIMIT","SL_LIMIT","SL_MARKET"}`.
   - `normalize_order_status(raw) -> {"OPEN","SUBMITTED","COMPLETE","PARTIALLY_FILLED","CANCELLED","REJECTED","EXPIRED","UNKNOWN"}`. Unknown → `UNKNOWN`, never `OPEN`.
   - `normalize_product(raw)` and `normalize_side(raw)`, raising on unknown.
2. Update every adapter's outgoing map to translate `SL_LIMIT`/`SL_MARKET` to its native code. Remove every `default="MARKET"/"LIMIT"` fallback; raise `BrokerOrderRejectedError`/`ValueError` on unknown.
3. Update every adapter's incoming order parsing to use `normalize_order_status` (including Fyers numeric `1/2/3/4` and postback `1/2`).
4. The OMS live branch must treat `SUBMITTED`/`PLACED`-normalized values correctly: any accepted broker id → persist id + status `OPEN`; never discard the id.
**Tests (new `tests/test_broker_order_type_translation.py`):**
- Parametrize all adapters: `SL_LIMIT`/`SL_MARKET` produce the native stop code, never MARKET/LIMIT.
- Unknown order type → raises.
- Fyers numeric status `2` → `COMPLETE`; `1` → `OPEN`.
- mstock `PLACED` → accepted with broker id, not UNKNOWN_FREEZE.
**Acceptance:** A protective stop cannot become an immediate market/limit order on any adapter.

### TASK P0-F — Adapter fail-closed responses and token safety
**Fixes:** BRK-02..05, BRK-07..13, BRK-15..17
**Files:** all `brokers/*.py`, `brokers/session.py`
**Steps:**
1. mstock: return `filled_quantity=0`, `average_price=None` on placement; ingest fills only from `get_trade_book()`/order details.
2. Upstox: remove invalid dataclass kwargs (`metadata`, `day_change` on Position, `avg_price` on Order, `metadata` on OrderResponse); map exchange to the correct Upstox instrument-key segment; raise on unknown exchange.
3. Angel One: resolve and pass `symboltoken`; fail closed when unresolved.
4. Kotak: include the resolved token; map product/order type to Kotak codes; reject empty order ids.
5. Dhan: resolve `securityId` or refuse; require `orderStatus`/`orderId` before `OPEN`.
6. Fyers: remove the implicit re-submit after auth-classified responses; first reconcile the orderbook by client tag. Check rate-gate return values. Fix `get_orders` type mapping and preserve exchange.
7. Stoxkart: `is_authenticated()` method, expiry check, conform quote signature; refuse TOTP `"123456"`.
8. Shoonya: require explicit `stat == "Ok"`; unknown status → `UNKNOWN`.
9. `session.py`: compute `is_testing` once at function start; do not swallow `NameError`; `get_execution_broker` must return `None` (or raise) when no execution-role broker exists rather than falling back to a data broker.
10. Token files: write with `os.open(..., 0o600)` / `os.chmod(0o600)`; move secrets toward keyring where feasible; on load, tighten existing file permissions.
11. Introduce `BrokerDataUnavailableError` and raise it for positions/orders/funds read failures. Update emergency flatten, reconciliation and portfolio aggregation to treat it as `UNAVAILABLE` (not empty/zero).
**Tests:** per-adapter tests using a stubbed transport:
- placement returns no filled qty/avg price without trade evidence;
- unknown status → UNKNOWN;
- auth-classified response does not call `place_order` twice (assert call count);
- read failure raises `BrokerDataUnavailableError`;
- token file mode is 0600 (POSIX; skip on Windows).
**Acceptance:** No adapter fabricates a fill, an empty book or a zero price on failure.

### TASK P0-G — Truthful emergency flatten
**Fixes:** EXEC-23, part of BRK-04
**Files:** `engine/order_lifecycle.py:3138-3335`
**Steps:**
1. In `EXECUTE` mode, never instantiate `PaperBroker` and never append paper closures.
2. Treat `BrokerDataUnavailableError`/empty-with-error as `UNVERIFIED`; do not report a count. Return `status="UNVERIFIED"` with `positions_verified=False`.
3. Count a cancellation only when `cancel_order` returns `True` **and** a subsequent broker snapshot shows the order cancelled/absent. Track attempted vs confirmed.
4. Normalize status comparisons via `brokers/order_types.py`.
5. In `SIMULATE`, report paper closures explicitly as `simulated=True`.
6. Audit both confirmed and unverified outcomes.
**Tests (new `tests/test_emergency_flatten_truth.py`):**
- EXECUTE + failing `get_positions` → status UNVERIFIED, zero claimed liquidations, no PaperBroker calls.
- EXECUTE + real broker → never touches `PaperBroker`.
- `cancel_order` returns False → not counted as cancelled.
- Paper mode → `simulated=True`.
**Acceptance:** A live emergency never reports paper or unverified outcomes as liquidations.

## Phase 1 — Execution and ledger integrity

### TASK P1-A — Gate ordering and recoverable rejection
**Fixes:** EXEC-01
**Files:** `engine/order_lifecycle.py:1074-1595`
**Steps:**
1. Move the `CONFIRMED → SUBMITTING` atomic update to immediately before `live_broker.place_order`, after all local gates (mode, pilot, instrument resolution, pre-trade, freeze-limit, GTT block).
2. If any post-transition local validation fails, revert to `CONFIRMED` with a reason and audit event. Pre-trade rejection must be non-terminal.
3. Add a test that a pilot/session/pretrade rejection leaves status `CONFIRMED` and no broker call was made.
**Acceptance:** SAFETY_CONTRACTS #12 is true under automated test.

### TASK P1-B — Fill ingestion on every accepted order and via sync/postback
**Fixes:** EXEC-03, EXEC-07, EXEC-19 (with prior RELEASE_BLOCKERS P0-1)
**Files:** `engine/order_lifecycle.py` (`execute_order_intent`, `sync_execution_orders`, `ingest_broker_executions`), `web/routers/market_data.py`
**Steps:**
1. Call `ingest_broker_executions` for `OPEN`/`SUBMITTED`/`FILLED`/`PARTIALLY_FILLED` responses, not just terminal fills.
2. On sync transitions to `FILLED`/`PARTIALLY_FILLED`, ingest fills before/with the status update.
3. Add `filled_quantity`, `average_fill_price`, `last_sync_at` to `orders_ledger` via migration. Persist `PENDING_FACTS`/`INGESTION_FAILED` on the row.
4. Ingest in the Fyers postback path as well as publishing SSE.
5. Schedule a retry for `PENDING_FACTS` (see P1-C).
**Acceptance:** A live order that returns `OPEN` then fills produces `execution_fills` rows and a ledger position without manual intervention.

### TASK P1-C — Recovery worker for SUBMITTING/UNKNOWN_FREEZE/PENDING_FACTS
**Fixes:** EXEC-02, EXEC-27
**Files:** new `engine/recovery_worker.py`; `web/api.py` lifespan; `app/repl.py`; `engine/order_lifecycle.py`
**Steps:**
1. Persist a client tag on every submission (`tag = order_id`) and ensure every adapter forwards it.
2. On ambiguous responses, persist any returned broker id instead of nulling it.
3. Recovery algorithm: for each `UNKNOWN_FREEZE`/`SUBMITTING` order, query broker orderbook by tag/id; if found, persist id and normalized status, ingest fills; if not found after N polls/grace, keep frozen, alert, and require operator action.
4. Run on startup and every 30 s while any such order exists.
5. Block new live entries while an unresolved `UNKNOWN_FREEZE` exists for the same account (configurable, default on).
**Tests:** simulate timeout-after-accept, timeout-before-accept, restart with frozen row, tag match, no match, partial fill. Assert no manual DB edits required.
**Acceptance:** No order can remain unrecoverably stuck.

### TASK P1-D — Reconciliation contract repair
**Fixes:** EXEC-04, EXEC-05, EXEC-06
**Files:** `engine/reconciliation.py`, `web/routers/orders_api.py`, `engine/order_lifecycle.py`
**Steps:**
1. Define one position DTO (`quantity`, `average_price`, `symbol`, `exchange`, `product`, `segment`) shared by ledger and reconciler.
2. Make `internal_cash`/`broker_cash` required (no defaults). `None` → `UNAVAILABLE`.
3. Key positions by `(exchange, symbol, product, segment)`; drop zero-qty rows on both sides; fail loudly on blank symbols.
4. `allow_trading` only for `COMPLETE`. Cash difference beyond tolerance → `DISPUTED`.
5. `_funds_cash` must return `None`/raise when `available_cash` is absent, not 0.0.
6. `is_complete` must be false when fills are missing or ingestion failed.
**Tests:** round-trip internal snapshot → reconcile → COMPLETE for matching books; one share difference → DISPUTED; duplicate symbol rows preserved; missing cash → UNAVAILABLE; PARTIAL → allow_trading False.
**Acceptance:** Reconciliation can actually return COMPLETE for a correct book and blocks on any unresolved discrepancy.

### TASK P1-E — Paper execution correctness
**Fixes:** EXEC-08, EXEC-09, EXEC-10, EXEC-20, EXEC-21, EXEC-22, QUANT-07
**Files:** `engine/paper.py`, `engine/order_lifecycle.py:1235-1401`, `:912-1010`
**Steps:**
1. Reject fills when `ltp <= 0`; mark the order `REJECTED`/`UNAVAILABLE`, never fill at 0.
2. Store the native broker order id in a dedicated column; cancellation uses it unchanged.
3. Record each child fill as it completes; parent becomes `PARTIALLY_FILLED` when any child filled, never back to `REJECTED`.
4. On cancel: persist `CANCEL_REQUESTED` with a timestamp; revert to `OPEN` on a definitive broker rejection; leave `CANCEL_PENDING` only while the broker snapshot is unresolved, and escalate on timeout. A crash must not strand the order.
4. Use the broker's `average_price` for the fill record, not the preview price.
5. Fix short accounting: set `avg_price` on open, realize only on cover, release the exact margin debited.
6. Fix `available_cash` double deduction.
7. Add a process-wide `PaperBroker` lock/shared instance; make JSON writes atomic (temp + `os.replace`).
**Tests:** sliced partial fill, later-tranche rejection, resting cancel, zero-quote rejection, short open/mark/cover, concurrent execute.
**Acceptance:** Paper ledger and PaperBroker agree in all cases.

### TASK P1-F — Order identity, idempotency and account scope
**Fixes:** EXEC-16, EXEC-17, EXEC-18, EXEC-24
**Files:** `engine/order_lifecycle.py`
**Steps:**
1. Persist `account_id` at preview (from authenticated execution account; explicit `UNKNOWN` is allowed only in SIMULATE).
2. Scope idempotency uniqueness to `(account_id, idempotency_key)`.
3. Include `stop_loss`, `target`, `auto_gtt_oco` in the preview hash; include them in `_intent_from_ledger_row` mismatch checks.
4. On unparseable `created_at`, fail closed (reject) instead of skipping TTL.
5. Use 128-bit order ids (`uuid4().hex`), keeping the `PAPER-`/`LIVE-` prefix.
6. Add authorization scope to confirm/execute if multi-user is supported: only the creating session/account may confirm.
**Tests:** same key changed SL → conflict; two accounts same key; unparseable TTL; collision-free id length.
**Acceptance:** A confirmed ticket cannot silently change protection or cross accounts.

### TASK P1-G — Multi-leg executor must not claim unverified success
**Fixes:** EXEC-11, EXEC-12, EXEC-13
**Files:** `engine/multi_leg_executor.py`
**Steps:**
1. Allow MARKET previews with a positive reference price (or add explicit `market_reference_price`); never pass `0.0`.
2. Require `FILLED` (and verified filled quantity) before submitting short legs. `OPEN` → pending/abort path.
3. `_unwind_filled_hedges` must verify the unwind fill; if it cannot, set `UNKNOWN_FREEZE`/`MANUAL_INTERVENTION`.
4. `result.net_fill_price` must come from ledger fills, not requested prices.
5. Never set `unwind_performed=True` unless every unwind is confirmed.
**Tests:** short-leg rejection with a filled hedge; unwind failure; OPEN hedge leg; MARKET leg.
**Acceptance:** A naked leg is never reported as a completed spread.

### TASK P1-H — Wing-lock requires sourced evidence
**Fixes:** EXEC-14
**Files:** `engine/order_lifecycle.py:3002-3136`
**Steps:** remove the `₹10.0` fallback; require `limit_price` or a verified ticket/credit; set `free_roll_locked` only on `FILLED`; return `OPEN/PENDING` for submission-only; audit the actual status.
**Acceptance:** No invented price or locked claim without a verified fill.

### TASK P1-I — Append-serialized order-event chain
**Fixes:** EXEC-15
**Files:** `engine/order_lifecycle.py:306-361`
**Steps:** wrap head-read + insert in `_get_orders_pool().transaction()` (`BEGIN IMMEDIATE`); order by a monotonic `sequence` column rather than timestamp string. Surface persistence failure to a durable fallback/alert instead of debug-only. Add a concurrent-writer test and a write-failure test.
**Acceptance:** Chain verification passes under concurrent events; an audit write failure is visible and does not silently drop an execution event.

### TASK P1-J — Outbox delivery truth
**Fixes:** EXEC-26 (aligns with RELEASE_BLOCKERS P0-2)
**Files:** `engine/outbox_worker.py`, `engine/storage/alert_repository.py`
**Steps:** live TELEGRAM and unknown channels must raise or return False, not True; route real sends through the configured transport; unknown channel → failed, not acknowledged. Add a test that a placeholder channel is not acknowledged.
**Acceptance:** No alert is ACKed without a real delivery attempt.

### TASK P1-K — Resolve the dual-OMS ambiguity
**Fixes:** EXEC-25, OPS-10
**Files:** `engine/oms.py`, `engine/trade_executor.py`, `engine/paper_execute.py`
**Decision:** either (a) wire `engine/oms.py` as the single state authority and delete the free-text lifecycle, or (b) delete `engine/oms.py` and enforce the transition table inside `order_lifecycle`. Prefer (b) for minimal disruption, but document the choice.
**Steps:** add a DB `CHECK`/application transition guard for `orders_ledger.status`; fix `fill()` ordering and `FILLED` quantity; make persistence atomic; or remove the module. Remove/rename the duplicate CLI executor after confirming no caller.
**Acceptance:** One documented order state machine; illegal transitions rejected.

## Phase 2 — Risk enforcement

### TASK P2-A — Central risk gate with real size limits
**Fixes:** RISK-01, RISK-02, SEC-14
**Files:** `engine/risk_limits.py`, `engine/order_lifecycle.py` (`preview_order_intent`, `execute_order_intent`, `modify_order_intent`), `engine/paper_execute.py`, `bot/telegram_bot.py`
**Steps:**
1. Add to `RiskLimits`: `max_order_notional`, `max_position_value`, and `max_risk_per_trade` (`qty × |entry − stop|`), all env-driven with sane defaults; reject unknown/missing price or stop for live orders.
2. Call `risk_limits.check(...)` in `execute_order_intent` for both SIMULATE and EXECUTE (mode-scoped rows, see P2-G), after pre-trade and before submission.
3. Re-run the gate on `modify_order_intent` with the new quantity/price.
4. Block live entries when `allow_override` is not explicitly provided by an authenticated operator; the default is deny.
5. Implement the account allowlist promised by `assert_live_execution_allowed(account_id)` (env `LIVE_ALLOWED_ACCOUNTS`) or remove the unused parameter and the docstring claim. Never accept a live order whose resolved broker account is not allowlisted.
6. Return a typed `RiskPreflightResult` and map to HTTP 409/403 with reason codes.
**Tests:** huge notional blocked; oversized position blocked; missing stop blocked for live; modify 65→6,500 blocked; Telegram path blocked; paper path records but does not consume live budget; unallowlisted live account blocked.
**Acceptance:** No order path can submit an order that violates a configured cap.

### TASK P2-B — PnL from the execution ledger
**Fixes:** RISK-03, RISK-04, RISK-13
**Files:** `engine/risk_limits.py`, `engine/order_lifecycle.py`, `engine/paper.py`
**Steps:**
1. Record realized PnL on closing fills from `execution_fills` using the inventory cost basis; never default to 0 when unknown — use `NULL`/`UNKNOWN`.
2. `record_trade` accepts explicit PnL or derives it; missing PnL blocks the daily-loss check rather than passing.
3. Implement `MAX_DAILY_DRAWDOWN_PCT` using an opening-equity snapshot and current equity; block when breached.
4. Fix `remaining_loss_room` sign.
**Tests:** five losing closes trip the cap; one unknown-PnL fill blocks; drawdown 1% vs limit 0.5% blocks; status field positive.
**Acceptance:** Daily loss, tilt and drawdown controls can actually fire.

### TASK P2-C — Pre-trade fail-closed
**Fixes:** RISK-05, RISK-06, RISK-07, RISK-08, QUANT-10
**Files:** `engine/pretrade.py`, `engine/order_lifecycle.py`, `engine/margin_engine.py`
**Steps:**
1. `available_cash is None` → block for live BUY.
2. For SELL, compute required margin via `margin_engine.calculate_order_margin` (SPAN+exposure+ELM) and block if unavailable; for equity sells, require holdings/position quantity.
3. Pass `prev_close` from a verified quote/snapshot; use the actual price band or block when unknown (do not default ±20%).
4. Pass `portfolio_value` and `daily_pnl` from the ledger; make the daily-loss gate blocking for live.
5. Use `market.rule_schedule`/`market.calendar` for holidays and exchange sessions.
6. Fix the 0-DTE session runway segment check.
**Tests:** naked short blocked; held-quantity sell allowed; holiday blocked; missing cash blocked; missing prev_close blocked; correct band.
**Acceptance:** Missing context blocks rather than passes.

### TASK P2-D — `risk_gate` semantics and context
**Fixes:** RISK-09, RISK-10
**Files:** `engine/risk_gate.py`, `agent/multi_agent.py`
**Steps:**
1. `allowed=False` whenever `max_qty == 0` or required context is missing; keep `direction="NONE"`.
2. Remove the `/100` share estimate.
3. Require `prices` and `portfolio` for production callers; return a typed `UNAVAILABLE` reason otherwise.
4. On any exception in `compute_allowed_actions`, return `BLOCKED` and surface the error; do not `logger.debug` and continue.
5. Fix the correlation shield to receive the actual direction, not hardcoded `"BULLISH"`.
**Tests:** at-limit → blocked; missing price → blocked; sector import failure → blocked; bearish direction uses bearish shield.
**Acceptance:** `allowed=True` implies a positive, context-backed maximum.

### TASK P2-E — VIX and capital fail-closed
**Fixes:** QUANT-04, RISK-14
**Files:** `engine/dynamic_risk.py`, `engine/risk_gate.py`, `engine/trade_executor.py`, `config/credentials.py`, `web/skills.py`
**Steps:** missing/unverified VIX → `VIX_UNAVAILABLE` and block new risk; capital mandatory and positive/finite; one capital SSOT (`TOTAL_CAPITAL`) with a single documented default; remove the dead `TRADING_CAPITAL` helper or alias it.
**Acceptance:** No invented neutral VIX or capital default can size a trade.

### TASK P2-F — Per-account, per-mode, IST-scoped risk state
**Fixes:** RISK-11, RISK-12
**Files:** `engine/risk_limits.py`, migrations
**Steps:** add `account_id`, `mode`, and IST `trade_date` columns; scope every query; migrate existing rows with `UNKNOWN`; use `config.constants.now_ist().date()`.
**Tests:** paper and live budgets independent; two accounts independent; UTC host rolls at IST midnight.
**Acceptance:** No cross-mode/account contamination.

## Phase 3 — Quant correctness

### TASK P3-A — Option time and Greeks
**Fixes:** QUANT-01, QUANT-02
**Files:** `analysis/options.py`, `engine/options_backtest.py`
**Steps:** DTE 0 for expiry day, negative/expired → invalid; use IST; implement intraday time-to-close for 0-DTE; branch theta for puts (`+rK e^{-rT} N(-d2)`); add fixture tests against known values.
**Acceptance:** Expiry-day T and put theta match reference values.

### TASK P3-B — Sizing fail-closed
**Fixes:** QUANT-03, QUANT-05
**Files:** `engine/position_sizer.py`, `engine/portfolio_greeks.py`
**Steps:** half-Kelly → 0 when `full_kelly <= 0`; remove invented win-rate/payoff defaults (require empirical inputs or return `UNAVAILABLE`); portfolio Greeks require instrument metadata; missing strike/type/spot/DTE → per-position `UNAVAILABLE`; remove hardcoded spots and the 25-lot mismatch.
**Acceptance:** Negative edge allocates zero; a long put's delta is negative and greeks are populated when metadata exists.

### TASK P3-C — Backtest honesty
**Fixes:** QUANT-06
**Files:** `engine/backtest.py`, `engine/backtest_vectorized.py`, `engine/options_backtest.py`, `engine/batch_backtest.py`
**Steps:** default `execute_on_next_bar=True` and `conservative_fills=True`; always apply `calculate_transaction_charges`; delete `NSECharges`/use the SSOT; add charges to options backtests; fail closed on missing IV instead of 20% fallback; label research-only output.
**Acceptance:** Documented look-ahead/cost-free defaults are gone; batch/options costs reconcile with `engine/charges.py`.

### TASK P3-D — Paper accounting (covered by P1-E; keep here for traceability)
**Fixes:** QUANT-07.

## Phase 4 — Operator surface, channels and agent

### TASK P4-A — Telegram owner allowlist
**Fixes:** OPS-02, OPS-04
**Files:** `bot/telegram_bot.py`
**Steps:** add `TELEGRAM_ALLOWED_USER_IDS`/`TELEGRAM_ALLOWED_CHAT_IDS`; a middleware rejects all commands/callbacks from others; `/flatten` requires an explicit confirm callback and an owner; fix the execution result field access; do not hardcode "PAPER" if the mode changed.
**Tests:** unauthorized user → no action; owner `/flatten` prompts; wrong callback → ignored.
**Acceptance:** Only the configured owner(s) can command the bot.

### TASK P4-B — Enforce agent tool permissions
**Fixes:** OPS-03
**Files:** `agent/tools.py`, `agent/harness.py`, `agent/core.py`
**Steps:**
1. `ToolRegistry.execute` must enforce `permission == "ask"` through an injected approval callback; in non-interactive/auto contexts, treat `"ask"` as `"deny"`.
2. Ensure `execute_trade` cannot be called without approval in every provider loop (Anthropic/OpenAI/Gemini/legacy JSON).
3. Treat tool outputs as untrusted data in the prompt; do not let ingested web/news content alter tool permissions.
**Tests:** destructive tool without approval → denied; auto mode → denied; approval → executes.
**Acceptance:** The documented confirmation gate actually exists.

### TASK P4-C — Sessions, CSRF, OAuth and postbacks
**Fixes:** SEC-10, SEC-11, SEC-12, SEC-13, SEC-16
**Files:** `web/auth.py`, `web/api.py`, `brokers/fyers.py`, `web/routers/market_data.py`, `docker/docker-compose.prod.yml`
**Steps:**
1. Invert the CSRF policy: require session + CSRF for **every** deployment that is not the local desktop (explicit allowlist of local-only modes). `cloud` must get the same enforcement as `self-hosted`, including a strong `CSRF_SECRET`; fail startup otherwise.
2. `Secure` + `__Host-` cookies for non-local deployments; persistent session store with per-user caps; per-IP + global rate limits and bounded attempt store.
3. Add body-size middleware; OAuth `state` generation/validation; Fyers postback signature verification; generic error responses with `incident_id`; redact URL query values in telemetry.
**Tests:** cloud-mode CSRF rejection/acceptance; missing/weak secret fails startup; cookie flags; state mismatch rejected; unsigned postback rejected.
**Acceptance:** Login CSRF, postback forgery, session eviction and unbounded bodies are closed in every non-desktop deployment.

### TASK P4-D — Preflight and documentation truth
**Fixes:** OPS-01, OPS-06
**Files:** `engine/preflight.py`, `CLAUDE.md`, `.env.example`
**Steps:** use `TradingMode.from_str` for the reported mode; report `OBSERVE`/`SIMULATE`/`EXECUTE` accurately; surface `ALLOW_LIVE_TRADING` and `LIVE_EXECUTION_QUALIFIED` states; if EXECUTE, mark `healthy=False` or require an explicit acknowledgment; update `CLAUDE.md` with the triple gate; add `MAX_DAILY_LOSS`, `MAX_DAILY_TRADES`, etc. to `.env.example`.
**Tests:** parametrize all mode strings incl. `LIVE`, `EXECUTE`, `OBSERVE`, `PAPER`; assert the reported mode.
**Acceptance:** A live desk can never be told it is in paper mode.

### TASK P4-E — OAuth callback hardening
**Fixes:** SEC-11, SEC-15
**Files:** `config/constants.py`, broker OAuth routes
**Steps:** remove the hardcoded personal IP; require HTTPS for non-loopback callbacks; make the callback base configurable; validate `state`.
**Acceptance:** No personal infrastructure data in the repo; no plaintext public callback.

## Phase 5 — Quality, tests and operations

### TASK P5-A — Make CI actually run the safety suite
**Fixes:** OPS-07, TEST-03, TEST-06, TEST-07
**Steps:**
1. **First, inventory and track the missing safety tests.** `tests/test_verified_market_safety.py` and 28 other safety tests are untracked, and `verified-market-safety.yml` references 8 files that are not tracked. `git add` the workflow and every referenced test in the same PR; verify with `git ls-files tests/test_*.py | wc -l` against the on-disk count.
2. Add a CI guard that fails when the on-disk test count and `git ls-files` count differ (prevents a future untracked safety test from silently not running).
3. Remove the global `LIVE_EXECUTION_QUALIFIED: '1'` from the workflow; set it only in the specific tests that need it via `monkeypatch`.
4. Fix the pre-commit/pre-push gate: add `test_verified_market_safety.py`, `test_modes.py`, `test_csrf_and_security.py`, `test_risk_limits.py`, `test_order_lifecycle.py` and the new regression suite to `shift_left_check.py`'s invariant list; make `--full`/pre-push run the fast suite; remove the false "Remote CI parity guaranteed" message.
5. Add `pytest-cov` and a ratcheting `--cov-fail-under` (measure the baseline first, then set the threshold slightly below it). Publish XML/HTML artifacts.
6. Add a nightly integration job that runs controlled broker-stub scenarios (no network).
**Acceptance:** A clean checkout runs the safety contracts, and a safety regression fails CI, not just a local run.

### TASK P5-E — Test-suite quality and rule fixtures
**Fixes:** TEST-01, TEST-02, TEST-04, TEST-05, TEST-08, TEST-09, TEST-10
**Files:** `tests/conftest.py`, `tests/test_alert_templates.py`, `tests/test_fyers_tbt_depth.py`, `tests/test_regime_governor.py`, `tests/test_sebi_expiry_mandate_invariants.py`, `AGENTS.md`, `market/rule_schedule.py`
**Steps:**
1. Remove the autouse `_fresh_live_vix → 15.0` patch. Provide an explicit `vix_value` fixture that tests must request, so missing-VIX behavior is exercised by default.
2. Rewrite stale expiry fixtures/assertions against `market.rule_schedule.expiry_weekday` / the effective-dated calendar (NSE Tuesday, BSE Thursday from the contract dates). Correct `AGENTS.md` invariant 37. Do not change a rule to make an old fixture pass.
3. Replace 78 no-assertion tests with observable-state assertions; rewrite or delete the vacuous registry test to call `harness.run(..., broker=None)`.
4. Add `freezegun`/`time-machine` (or an injectable clock) and remove `date.today()`/`sleep` anchors from tests.
5. Consolidate the 24 duplicated `client` fixtures into `conftest.py` factories.
6. Provide a small fixture DB for `test_data_integrity_audit.py` (or make it fail, not skip, when the DB is required).
7. Audit the 9 modules that set live flags: each must restore env and must not leak `TRADING_MODE`/qualification across tests.
**Acceptance:** The suite exercises production missing-data behavior, encodes the effective calendar, and has no vacuous tests.

### TASK P5-B — Regression suite for this plan
Add one test module per task group (names in each task). At minimum:
`test_authz_privileged_endpoints.py`, `test_local_mode_authenticity.py`, `test_stream_auth.py`, `test_data_provenance_truth.py`, `test_broker_order_type_translation.py`, `test_broker_fail_closed.py`, `test_emergency_flatten_truth.py`, `test_order_gate_ordering.py`, `test_fill_ingestion_on_open.py`, `test_unknown_freeze_recovery.py`, `test_reconciliation_contract.py`, `test_paper_execution_accounting.py`, `test_risk_gate_enforcement.py`, `test_pretrade_fail_closed.py`, `test_quant_time_and_theta.py`, `test_telegram_authorization.py`, `test_agent_permission_enforcement.py`, `test_preflight_mode_truth.py`.
**Acceptance:** Every P0/P1 finding has a test that fails before the fix.

### TASK P5-C — Dependency and repo hygiene
**Fixes:** OPS-07, OPS-08, OPS-09
**Steps:** pin/upper-bound risky transitive SDKs; add a lockfile; remove the stray `1/` directory; ensure logs/DBs remain ignored; document optional-SDK failure modes; add a lint rule for broad `except Exception: pass` in order/data modules (incremental, not a mass rewrite).
**Acceptance:** Reproducible installs; no stray runtime artifacts in the repo root.

### TASK P5-D — Reduce control duplication
**Fixes:** OPS-10 (with P1-K)
**Steps:** choose one order authority; remove or alias the duplicate CLI executor; document which modules are production vs legacy in `AGENTS.md`.
**Acceptance:** One documented path from UI/CLI/Telegram to the broker.

## Structural improvement backlog (P2, non-blocking — do after containment)

These are not defects to fix before the P0/P1 work, but they are the highest-leverage maintainability changes.

1. **Split `web/api.py` (4,718 LOC)** into routers by domain and add a single dependency-based auth guard instead of path-prefix middleware. Path allowlists are how SEC-01/02 slipped through.
2. **Split `engine/auto_alert_engine.py` (17,949 LOC)** along ingestion, qualification, lifecycle and dispatch seams. Add a boundary test per seam.
3. **One typed error taxonomy** for broker, data and risk failures (`BrokerDataUnavailable`, `BrokerOrderRejected`, `BrokerOrderAmbiguous`, `DataUnavailable`, `RiskBlocked`) and delete blanket `except Exception` on order/data paths.
4. **One position/fill DTO** shared by ledger, reconciliation, portfolio and UI. The reconciliation schema mismatch (EXEC-04) is a symptom of missing shared types.
5. **Schema migrations**: replace ad-hoc `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` blocks with a small versioned migration runner and a schema-version table.
6. **Property-based tests** for money math: inventory cost basis, partial closes, short cover, charges, rounding. Use Hypothesis or parametrized invariants (`sum(fills) == position`, `cash delta == -notional - fees`).
7. **Chaos tests** for broker outages: timeout after accept, timeout before accept, empty body, unauthenticated, rate-limited, malformed status, duplicate postback. Assert the OMS state, not just an exception.
8. **Secret and dependency hygiene**: secret scanning in CI, lockfile, upper bounds on broker SDKs, and a documented optional-SDK failure mode.
9. **Observability**: one metric/trace per order state transition with `order_id`, `mode`, `broker`, `account`, `latency`, `outcome`; alert on any order in `SUBMITTING`/`UNKNOWN_FREEZE` older than 60 s.

---

# Part 3 — Execution order and dependencies

Recommended PR sequence (each independently reviewable):

0. **P5-A / TEST-06** — commit the untracked safety suite and a corrected workflow, and fix the pre-commit gate. Without this, later fixes are not covered in CI.
1. **P0-A, P0-B, P0-C** — auth/exposure. No dependency on trading logic.
2. **P0-D** — data provenance. Blocks safe live execution.
3. **P0-E, P0-F** — broker truth. Depends on the canonical mapping module.
4. **P0-G** — emergency flatten. Depends on P0-F error types.
5. **P1-A, P1-B, P1-C** — order gate, ingestion, recovery. Depends on P0-E status normalization.
6. **P1-D** — reconciliation. Depends on P1-B ledger fields.
7. **P1-E, P1-F, P1-G, P1-H, P1-I, P1-J, P1-K** — remaining execution truth.
8. **P2-A → P2-F** — risk enforcement. P2-A depends on P1-B PnL source.
9. **P3-A → P3-C** — quant correctness.
10. **P4-A → P4-E** — operator/channel/agent.
11. **P5-A → P5-E** — CI/hygiene/test quality (P5-A is step 0; P5-E can follow Phase 4).

Do not start Phase 2 before Phase 1's ledger fields exist; risk enforcement without a trustworthy PnL source will just block the wrong things.

# Part 4 — Verification gauntlet

Run after each task group and once at the end. Record exact output.

```powershell
# 1. Fast validation required by CLAUDE.md
.venv\Scripts\python.exe scripts/validate_all.py --fast

# 2. Safety contracts
.venv\Scripts\python.exe -m pytest tests/test_verified_market_safety.py tests/test_live_oms_p3b.py tests/test_order_execution_boundary.py tests/test_execution_gate.py -q

# 3. New regression suite from P5-B
.venv\Scripts\python.exe -m pytest tests/test_authz_privileged_endpoints.py tests/test_local_mode_authenticity.py tests/test_stream_auth.py tests/test_data_provenance_truth.py tests/test_broker_order_type_translation.py tests/test_broker_fail_closed.py tests/test_emergency_flatten_truth.py tests/test_order_gate_ordering.py tests/test_fill_ingestion_on_open.py tests/test_unknown_freeze_recovery.py tests/test_reconciliation_contract.py tests/test_paper_execution_accounting.py tests/test_risk_gate_enforcement.py tests/test_pretrade_fail_closed.py tests/test_quant_time_and_theta.py tests/test_telegram_authorization.py tests/test_agent_permission_enforcement.py tests/test_preflight_mode_truth.py -q

# 4. Broader affected suites
.venv\Scripts\python.exe -m pytest tests/test_risk_limits.py tests/test_risk_gate.py tests/test_order_lifecycle.py tests/test_modes.py tests/test_auth_security.py tests/test_web_auth.py tests/test_reconciliation_typed.py tests/test_reconciliation_unavailable.py tests/test_broker_gtt_oco.py tests/test_broker_exceptions.py tests/test_execution_routing.py tests/test_broker_roles.py -q

# 5. Full fast suite (CI parity)
.venv\Scripts\python.exe -m pytest tests/ -q -m "not network and not slow" -n 2

# 6. Lint/format/diff
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
git diff --check
```

Stop if any command fails. Do not report a task complete on a partial run.

# Part 5 — Prohibited actions

- Do not set `ALLOW_LIVE_TRADING=1`, `LIVE_EXECUTION_QUALIFIED=1`, or `PILOT_ALLOW_LIVE_EXECUTION=1`.
- Do not call a real broker `place_order`, cancel, modify or flatten as part of testing.
- Do not send Telegram messages, including "test" messages.
- Do not mutate production alert/order/ledger databases. Use `TRADING_PLATFORM_HOME` temp dirs.
- Do not weaken, skip or delete a safety test; do not change expected behavior just to pass.
- Do not change market rules, expiry weekdays, STT or lot sizes without a primary source, publication date and effective date.
- Do not replace missing data with neutral/zero defaults (`LIVE`, `OPEN`, `0.0`, `100000`, `₹10`, `win_rate=0.55`).
- Do not mass-format unrelated files or rename public APIs without updating UI/tests.
- Do not commit or push; leave the tree for owner review.

# Part 6 — Definition of done

A task is done only when all of the following are true:

1. The cited defect is reproduced by a new failing test at the production boundary.
2. The fix is implemented without weakening an invariant.
3. The new test passes and the affected suites pass.
4. Missing/unknown data paths return `UNAVAILABLE`/blocked, never a success-shaped default.
5. An audit event exists for any execution-affecting action.
6. No live flag, broker call or external message was triggered during the test run.
7. The completion note lists: files changed, commands run, test counts, residual risk.

A phase is done when its tasks are done and the phase's cross-cutting acceptance holds:
- **Phase 0:** no unauthenticated privileged mutation; no synthetic quote reaches live execution; protective stops translate correctly; no fabricated fills; nothing reports paper as live.
- **Phase 1:** every accepted order is recoverable and its fills are in the ledger; reconciliation can return COMPLETE; paper and live accounting agree.
- **Phase 2:** daily loss, tilt, drawdown, notional and margin can all block an order on every path.
- **Phase 3:** expiry-day Greek/DTE values are correct; negative-edge sizing is zero; backtests are cost-aware and next-bar.
- **Phase 4:** only the owner can command the bot; `permission="ask"` is enforced; preflight reports the real mode.

---

# Appendix A — Reproduction evidence from this review

These commands were run read-only on the reviewed tree.

**A1. Synthetic futures are labelled LIVE**

```text
>>> from market.data_events import classify_data_state
>>> classify_data_state(source="FALLBACK", provider="cost_of_carry_synthetic", price=100.0)
'LIVE'
>>> classify_data_state(source="FALLBACK", provider="yfinance", price=100.0)
'DELAYED'
```

**A2. Preflight misreports EXECUTE as SIMULATE**

```text
$ TRADING_MODE=EXECUTE ALLOW_LIVE_TRADING=1 python -c "from engine.preflight import run_preflight; r=run_preflight(False); print(r.mode)"
SIMULATE
(PASS) Safe Default: SIMULATE (Paper Mode). No real broker orders will be placed.
raw: EXECUTE
```

**A3. Reconciliation schema mismatch**

```text
>>> reconcile_ledger(
...   [{"symbol":"RELIANCE","quantity":100,"average_price":2500.0}],
...   [{"symbol":"RELIANCE","qty":100,"avg_price":2500.0}],
...   internal_cash=100.0, broker_cash=100.0)
status: DISPUTED
discrepancies: [('QTY_MISMATCH','HIGH',0,100)]
```

**A4. No per-order notional cap**

```text
>>> rl.check("RELIANCE","BUY",5_000_000,2900.0)
allowed: True
flags: []
```

**A5. TBT parser has no last-traded source**

`market/fyers_tbt_manager.py:1423`:

```python
ltp = bids[0]["price"] if bids else (asks[0]["price"] if asks else 0.0)
```

The parser reads only `bidprice`, `askprice`, `bidqty`, `askqty`, `bidordn`, `askordn`, `tbq`, `tsq`, `timestamp`. No traded-price field is read. `_handle_depth_update` then writes this value as `Quote.last_price` with `data_state="LIVE"` (`:1320-1333`).

**A6. Targeted tests are green while these defects exist**

```text
47 passed  (verified market safety + trade executor)
139 passed (risk, modes, auth, lifecycle, reconciliation, execution gates)
92 passed  (live OMS, broker GTT/exceptions, routing, roles)
42 passed  (CSRF, mode banner, preflight endpoint, API contracts)
```

Collection is clean: 5,120 tests collected, 17 deselected by markers, 0 collection errors. But see A7.

**A7. The central safety tests and workflow are untracked**

```text
$ git ls-files .github/workflows/
.github/workflows/build-mac.yml
.github/workflows/ci.yml

$ git status --porcelain | grep '^??'
?? .github/workflows/verified-market-safety.yml
?? tests/test_verified_market_safety.py
... 28 other untracked safety test files ...
```

CI checks out git contents only, so the safety suite and the safety workflow do not run on any runner. `verified-market-safety.yml` also names eight tests that are not tracked; committing it unchanged would fail.

# Appendix B — Finding → task traceability

| Task | Findings closed |
|---|---|
| P0-A | SEC-01, SEC-02, SEC-03, SEC-05, SEC-07 (status), SEC-10 (partial), OPS-05 |
| P0-B | SEC-04, SEC-10 (partial) |
| P0-C | SEC-06, SEC-07 |
| P0-D | DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, DATA-08 |
| P0-E | BRK-01, BRK-06 (partial), BRK-14 (order types), EXEC-07 (status) |
| P0-F | BRK-02, BRK-03, BRK-04, BRK-05, BRK-07, BRK-08, BRK-09, BRK-10, BRK-11, BRK-12, BRK-13, BRK-15, BRK-16, BRK-17 |
| P0-G | EXEC-23, BRK-04 (flatten) |
| P1-A | EXEC-01 |
| P1-B | EXEC-03, EXEC-07, EXEC-19 |
| P1-C | EXEC-02, EXEC-27 |
| P1-D | EXEC-04, EXEC-05, EXEC-06 |
| P1-E | EXEC-08, EXEC-09, EXEC-10, EXEC-20, EXEC-21, EXEC-22, QUANT-07 |
| P1-F | EXEC-16, EXEC-17, EXEC-18, EXEC-24 |
| P1-G | EXEC-11, EXEC-12, EXEC-13 |
| P1-H | EXEC-14 |
| P1-I | EXEC-15 |
| P1-J | EXEC-26 |
| P1-K | EXEC-25, OPS-10 |
| P2-A | RISK-01, RISK-02, SEC-14 |
| P2-B | RISK-03, RISK-04, RISK-13 |
| P2-C | RISK-05, RISK-06, RISK-07, RISK-08, QUANT-10 |
| P2-D | RISK-09, RISK-10 |
| P2-E | QUANT-04, RISK-14 |
| P2-F | RISK-11, RISK-12, RISK-15 |
| P3-A | QUANT-01, QUANT-02 |
| P3-B | QUANT-03, QUANT-05, QUANT-08, QUANT-09 |
| P3-C | QUANT-06 |
| P4-A | OPS-02, OPS-04 |
| P4-B | OPS-03 |
| P4-C | SEC-07 (docs), SEC-08, SEC-09, SEC-10, SEC-11, SEC-12, SEC-13, SEC-16 |
| P4-D | OPS-01, OPS-06 |
| P4-E | SEC-15 |
| P5-A | OPS-07, TEST-03, TEST-06, TEST-07 |
| P5-B | TEST-02 |
| P5-C | OPS-07, OPS-08, OPS-09 |
| P5-D | OPS-10, OPS-11 |
| P5-E | TEST-01, TEST-04, TEST-05, TEST-08, TEST-09, TEST-10 |

Some findings intentionally overlap tasks. Close them only when every listed task is complete.

# Appendix C — Owner decisions required before implementation

These cannot be resolved from code; ask the owner once, then proceed.

1. **Deployment model:** Is the sidecar ever exposed beyond loopback? If yes, `DEPLOY_MODE=self-hosted` plus a TLS reverse proxy and a sidecar token are mandatory.
2. **Multi-user/multi-account:** Is per-user order ownership and per-account risk state required? If single-owner only, document that and still add account scoping to the ledger.
3. **Live qualification:** Confirm `LIVE_EXECUTION_QUALIFIED` stays `0` throughout this plan. Do not set it to make a test pass.
4. **Legacy CLI authority:** Keep `engine/trade_executor.py`/`engine/paper_execute.py` as the supported paper path, or route CLI through the same OMS? Prefer one path.
5. **Market-data contract:** If the Fyers TBT packet genuinely carries a last-traded field, provide the SDK field name and a captured fixture; otherwise depth-only is the contract.
6. **Telegram scope:** Owner-only bot, or an explicitly allowlisted group? Provide the numeric user/chat ids.

# Appendix D — Notes for the implementing model

- The working tree already contains substantial uncommitted safety work (new `docs/SAFETY_CONTRACTS.md`, `config/discovery_policy.py`, `engine/executable_risk_reward.py`, `engine/outbox_worker.py`, `engine/shadow_evaluator.py`, `market/contract_selection.py`, `market/rule_schedule.py`, and many tests). Preserve it.
- `docs/implementation_plan_codex/GEMINI_RELEASE_BLOCKERS_2026-11-02.md` already tracks fill-ingestion, outbox and R:R defects. Verify each is still open; do not duplicate a fix that already landed.
- Prefer small, evidence-rich commits/PRs. The owner reviews the diff; a 2,000-line mixed change will be rejected.
- When a cited line no longer matches, search for the symbol and fix the current implementation. Do not edit a stale line number blindly.
- If a fix would require enabling live execution to verify, stop and report the exact verification gap instead.
