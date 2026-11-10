# Engineering Roadmap 2027 — production hardening for ChanakyaTrade

Status: working document, 8 November 2026. Owner: @brij-home.
Scope: correctness, safety, operability and developer velocity of the trading
platform. This document records evidence, the fixes landed in this pass, and the
sequenced work that follows. It does not claim alpha, deployment readiness or
live-execution qualification.

Read together with `docs/SAFETY_CONTRACTS.md` (behavioural contracts) and
`docs/FNO_DESK_ROADMAP.md` (desk architecture). Where they disagree, the safety
contract wins.

---

## 1. Snapshot

| Dimension | Value (8 Nov 2026) |
| --- | --- |
| Branch | `fix/tick-warehouse-append-only` |
| Python source | 378 modules, ~247k lines across `engine/`, `market/`, `web/`, `analysis/`, `agent/`, `app/`, `brokers/`, `bot/`, `config/`, `ui/` |
| Tests | 5,420 collected (5,403 selected by default; `slow`/`network` excluded) |
| Lint / format | `ruff check .` clean; `ruff format --check` clean |
| CI | Python 3.11/3.12/3.13 matrix, lint, frontend typecheck + vitest + bundle, nightly slow tier |
| Execution posture | PAPER/SIMULATE by default; live placement requires `TRADING_MODE=EXECUTE` + `ALLOW_LIVE_TRADING=1` + `LIVE_EXECUTION_QUALIFIED=1` and remains partially blocked by design |

Largest modules (maintainability debt):

| Module | Lines |
| --- | ---: |
| `engine/auto_alert_engine.py` | 17,136 |
| `web/skills.py` | 7,921 |
| `bot/alert_templates.py` | 7,663 |
| `engine/alert_scrutiny.py` | 6,090 |
| `web/api.py` | 4,371 |

---

## 2. Landed in this pass

Five defects were fixed at the root cause, all with regression cover. No safety
gate, threshold or live-trading flag was changed.

### 2.1 Test network quarantine was escapable (P0, fixed)

Evidence: a full `-n 4` run produced 7 failures. Three were in
`tests/test_auto_alerts.py`; the captured failure showed a live NIFTY print
(`Live ₹24,986.4`) inside a synthetic test, and `market.quotes._QUOTE_CACHE`
held `NSE:NIFTY 50 = 24,986.4 (REST/fyers)`.

Root cause: `tests/conftest.py` decided whether to block sockets from
`CHANAKYA_TESTING`/`PYTEST_CURRENT_TEST` **at connect time**. A test that
deletes `CHANAKYA_TESTING` to exercise a production branch (19 call sites), or
a background thread that outlives its test, re-opened live broker traffic for
the rest of the process. Real quotes then leaked into deterministic tests.

Fix: the quarantine is latched at import (`_GUARD_ACTIVE`). Covered by
`tests/test_harness_network_quarantine.py`.
Outcome: `tests/test_auto_alerts.py` goes from 1 failed / 84 passed (serial) and
3 failed under xdist to 85 passed.

### 2.2 Commodity option grids were fabricated (P0, fixed)

Evidence: `market/ws_subscription_manager.get_active_commodity_grid` built
`MCX:CRUDEOIL{month}{atm}CE/PE` from `now.strftime("%y%b")`, a hardcoded
`or 6500.0` fallback and a fixed 50-point strike step. `market/fyers_tbt_manager`
carried the same construction. `docs/FNO_DESK_ROADMAP.md` already listed this as
a code-confirmed gap.

Consequence: plausible but unlisted contracts could be subscribed, consuming
provider slots, polluting depth state and failing silently at the broker.

Fix: `market.contract_selection` now resolves MCX options strictly from the
published `MCX_COM` master (active status, token, lot, tick, CE/PE pairing,
same-day and expired exclusion) and anchors the ATM strike on a fresh
front-month quote. Any missing input returns an empty grid: futures remain, no
option tier is invented. Covered by
`tests/test_commodity_contract_selection.py` (10 tests) and the updated roll
contract in `tests/test_ws_subscription_manager.py`.

### 2.3 Broker SDK log handlers were unbounded and duplicated (P1, fixed)

Evidence: the checkout contained `fyersRequests.log` at 235 MB and
`fyersDataSocket.log` at 39 MB. The FYERS SDK attaches a plain
`logging.FileHandler` to `FyersAPI`/`FyersAPIRequest` on every client
construction and writes into the process working directory; each new client adds
another handler to the same logger.

Fix: `config/log_hygiene.install()` relocates SDK handlers under
`app_data_path("logs")`, collapses duplicates to one handler and bounds growth
with `RotatingFileHandler` (10 MB × 5 backups). It is idempotent, preserves
formatters and non-file handlers, and is wired at the four SDK construction
sites (REST client, data socket, order socket, TBT). Covered by
`tests/test_log_hygiene.py`.

### 2.4 Detector unit test depended on ambient CPR data (P1, fixed)

Evidence: `test_opening_drive_detector_dual_invalidation` passed in the morning
run and failed later the same evening with a live wide CPR
("Spot ₹24,920 trapped inside Wide CPR core [₹24,709.2 - ₹24,923.3]").

Root cause: the detector consults `engine.daily_levels` for a real CPR gate; the
unit test supplied synthetic bars but not daily levels, so it inherited whatever
CPR was cached for the current session. The gate is correct in production; the
test was not hermetic. Fixed by stubbing `get_daily_levels` and
`evaluate_cpr_gate` in that test (CPR behaviour keeps its own coverage).

### 2.5 Fyers auth backoff leaked across tests (P1, fixed)

Evidence: `test_fyers_is_authenticated_concurrent_deduplication` failed under
4-worker load with `all([False, False, False, False, False])` while passing in
isolation. `is_authenticated()` returns `False` early when the process-global
auth backoff is active, and the suite reset the rate gate and circuit breaker but
not `brokers.fyers._GLOBAL_AUTH_BACKOFF_UNTIL`. One auth-failure test therefore
disabled headless auth for later tests in the same worker.

Fix: `tests/conftest.py` resets `_reset_auth_backoff()` before and after every
test, alongside the existing singleton resets.

---

## 3. Findings register

Severity: P0 correctness/safety, P1 operational or architectural risk,
P2 quality/velocity, P3 optional.

| # | Sev | Finding | Evidence | Required action |
| --- | --- | --- | --- | --- |
| F1 | P0 | Test quarantine escapable | §2.1 | Fixed |
| F2 | P0 | Fabricated MCX option symbols | §2.2 | Fixed |
| F3 | P1 | Unbounded/duplicated SDK logs | §2.3 | Fixed |
| F4 | P1 | Session-close duplication | 76 `15:30` literals in `engine/`, 49 in `market/`; only `engine/pretrade.py` and `market/calendar.py` call `market.rule_schedule` | Audit every literal; route derivative/cash close decisions through `market.rule_schedule` and delete the rest |
| F5 | P1 | Broad exception handling | 2,996 broad handlers; only 2 are bare `pass`, but many log at DEBUG and continue ("Non-fatal exception suppressed") | Classify: expected degradation (typed, logged at INFO/WARN with provenance) vs defect (fail closed). Ban DEBUG-only catches on money/data paths |
| F6 | P1 | Monolith modules | `auto_alert_engine.py` 17k lines, `skills.py` 7.9k, `alert_templates.py` 7.7k | Extract alert lifecycle / dispatch / enrichment / rendering into domain modules behind typed interfaces |
| F7 | P2 | CI does not gate types, dependencies or secrets | `ci.yml` runs ruff + pytest + frontend only | Add `pyright`, `pip-audit`, secret scan, `permissions:`, SHA-pinned actions, coverage trend |
| F8 | P2 | No lockfile | `pyproject.toml` + `requirements.txt` only | Adopt `uv lock` (or pip-tools constraints) and install from it in CI |
| F9 | P2 | Test temp residue | `.pytest_trading_platform*` worker trees with ACL-denied `pytest-tmp-*` children break repo-wide `rg`/glob | Identify tests that set restrictive ACLs; clean on `pytest_unconfigure`; add a disk budget |
| F10 | P2 | No distributed tracing / SLOs | Correlation IDs exist in `engine/observability`, but no spans or RED/USE metrics | Instrument order lifecycle, quote fetch, alert pipeline, rate gate; define SLOs and alert on queue age |
| F11 | P2 | Frontend runtime lag | React 18.3.1 while React 19 is current | Upgrade with the compiler, keep vitest/biome/typecheck green |
| F12 | P2 | No property/mutation testing on risk math | Risk, sizing and payoff code is unit-tested by example only | Add Hypothesis invariants (monotonicity, bounds, conservation) and a scoped mutation run |
| F13 | P3 | Historical master reconstruction | Contract selection correctly refuses to serve a past `ref_time` from today's master | Persist dated master snapshots for replay research |
| F14 | P1 | Quarantine does not cover libcurl | `yfinance` (via `curl_cffi`) still produces live-scraper warnings during tests; the socket patch only intercepts Python sockets | Fail closed at the provider boundary when `CHANAKYA_TESTING=1`; assert zero outbound fetch attempts |
| F15 | P2 | Unit tests can inherit live market context | §2.4 (daily levels/CPR); same pattern is possible for quotes, sector rankings and VIX | Add an autouse "market context is explicit" guard; tests that need context must opt in with fixtures |
| F16 | P3 | Intermittent load-sensitive concurrency test | `test_quotes_ws_integration_with_kotak` failed once in a 4-worker full run; 8/8 passes in isolation | Capture the singleton state on failure before changing code; do not mask with retries |
| F17 | P2 | Parallel-only risk-gate failures | `test_risk_limits_central_order_path` passed serially and with all risk suites in one process, yet two cases failed in a full `-n 2` run ("DID NOT RAISE") | Instrument `risk_limits._db` and `TRADING_MODE` at failure; likely a leaked module-level override. Add a `risk_limits.reset_all()` autouse reset once the writer is identified |
| F18 | P2 | Quote-cache tests fail together in one worker | `test_quotes_flight`, `test_data_reuse_pipeline`, and `test_broker_kotak` returned `{}`/`None` in the same worker while passing in isolation; `get_quote` swallows broker-path exceptions and returns an empty dict. Hypothesis: a leaked background thread owns the single-flight entry for the same instrument, fails (network blocked), and publishes `None` to test followers | (a) followers that receive a `None` leader result should retry as leader instead of accepting it; (b) capture the owning thread id/stack on empty results. This is also a production robustness gap for UI quotes during a failed background fetch |

---

## 4. Strategic pillars

### P0 — Determinism and market-truth (next 30 days)

1. **Session-clock SSOT (F4).** One effective-dated authority for cash and
   derivative sessions. Acceptance: no module outside `market/rule_schedule` and
   `market/calendar` compares a clock to a hardcoded close time; a table test
   proves 6 Dec 2026 and 7 Dec 2026 behaviour differs correctly.
2. **Quarantine and hermeticity (done, extend).** Add a per-worker disk budget
   and a failing test if any test leaves a socket, thread or temp tree behind.
3. **Replay determinism.** A recorded session replay must produce byte-identical
   alert decisions and order intents. Any wall-clock, random or cache dependency
   fails the replay.

### P1 — Execution safety (30–90 days)

The live gate stays closed until all of the following are durable and tested:

- Account-scoped execution ledger with idempotency keys and no `INSERT OR REPLACE`.
- Child-order, partial-fill and protection tracking with restart recovery.
- `UNKNOWN_FREEZE` recovery runbook executed against broker sandbox/replay.
- Reconciliation from independent broker snapshots, never from the internal book.
- Basket, freeze-limit slicing and protective GTT remain blocked until the above
  is proven; removing a block requires evidence, not a flag.

### P2 — Operability (30–90 days)

- OpenTelemetry traces (order, quote, alert, LLM) with correlation IDs; RED
  metrics per provider; queue-age and quota saturation dashboards (F10).
- Log policy: every long-lived handler rotating and app-owned (done for FYERS);
  structured JSON for machine ingestion; a disk budget alarm.
- Crash-only design: startup reconciles persisted state, never mutates history.

### P3 — Architecture and velocity (60–180 days)

- Decompose the alert monolith (F6) along the existing SSOT domains: ingestion,
  scoring/scrutiny, lifecycle, dispatch, rendering.
- Typed boundaries: Pydantic models at API/tool edges; `pyright` gate with a
  ratchet (fail only on new errors).
- Test strategy: property-based risk math (F12), contract tests (exists), and a
  nightly mutation sample on `engine/position_sizer.py`, `engine/charges.py`,
  `engine/risk_gate.py`.

### P4 — Research edge (continuous, evidence-gated)

- Options replay with licensed raw feed evidence, as-of contracts and IV history
  before any IV-rank claim (see safety contract).
- Held-out validation for every detector change; report missed moves and net
  expectancy, not only hit rate.
- No provider, model or indicator is promoted as alpha without out-of-sample
  evidence.

### P5 — Client platform (60–120 days)

- React 19 upgrade with the compiler; keep bundle budgets and the hook audit.
- Accessibility and keyboard-first flows for the trading ticket.
- Contract tests between JSX payload expectations and backend serializers
  (`tests/test_api_ui_contracts.py`) extended to every new endpoint.

---

## 5. Technology alignment (late 2026)

| Area | Current | Next step | Guardrail |
| --- | --- | --- | --- |
| Python | 3.12 local, 3.11–3.13 CI | Evaluate 3.14 once pandas/numpy/scipy wheels are stable; free-threaded build only for isolated market-data fan-out | Keep the 3.11 floor until CI proves otherwise |
| Packaging | pip + requirements.txt | `uv` lockfile, hash-checked installs (F8) | No unpinned production installs |
| API | FastAPI + Pydantic v2 | Lifespan-scoped clients, explicit timeouts, bounded concurrency | No blocking I/O on the event loop |
| Storage | SQLite | WAL + `busy_timeout`, STRICT tables, versioned migrations | Migrations only through the migration layer |
| Observability | Correlation IDs, provider registry | OpenTelemetry traces/metrics, SLOs | Never log secrets or full tokens |
| Frontend | React 18.3, Zustand, Vite, Vitest, Biome | React 19 + compiler (F11) | No client-side mode inference |
| AI | Multi-provider routing with deadlines | Structured outputs, eval sets, prompt-injection boundary on all tool output | AI output never overrides safety gates |

---

## 6. Regulatory watch

Effective-dated behaviour is already encoded in `market/rule_schedule.py`; do
not activate future rules early.

- **SEBI circular of 15 October 2026 (CAS review).** From 7 December 2026 the
  closing auction runs 15:30–15:40 with a random close between 15:38 and 15:40;
  index derivatives trade to 15:45 except expiring index derivatives, which stop
  at 15:30; stock derivatives trade to 15:45 including expiry day; post-close
  cash session 15:50–16:00. Expiring derivatives settle on a 30-minute VWAP of
  the underlying. Order-transition provisions apply from 8 February 2027.
- **Position limits.** Delta-based/position-limit framework and intraday
  monitoring remain a pre-trade and EOD obligation; monitored limits must come
  from the exchange/clearing corporation, not local constants.
- **STT.** Securities F&O sale rates changed on 1 April 2026; historical
  backtests must pass the historical date.
- **FYERS.** Prime limits changed on 16 October 2026; access tokens expire daily
  at 06:30 IST; quantity freeze comes from the published master.

Anything in this list changed in code requires a primary source, an effective
date and a behaviour test at the real boundary.

---

## 7. Anti-patterns banned in this codebase

1. Calendar- or price-guessed instrument symbols (fixed in §2.2; keep it that way).
2. Default/placeholder market values that masquerade as live data.
3. Test guards that depend on mutable environment variables (fixed in §2.1).
4. Unbounded or per-client `FileHandler`s (fixed for FYERS in §2.3).
5. `except Exception: pass` and DEBUG-only catches on money or market-data paths.
6. Direct broker mutation outside the OMS; shadow execution of any kind.
7. Weakening a test or a safety gate to obtain a green build.
8. Claiming edge, IV rank or deployment readiness without sourced evidence.

---

## 8. Verification for this pass

Observed after this pass:

- `tests/test_auto_alerts.py`: 85 passed (was 1 failed / 84 passed serial, 3 failed under xdist).
- Commodity selection + subscription + discovery: 40 passed.
- Log hygiene: 6 passed; SDK smoke test relocates and dedupes live handlers.
- Full suite at CI parallelism (`-n 2`, `--dist loadfile`), repeated:
  5,401/5,400 passed with 2–3 failures that rotate among parallel-only quote-cache
  and risk-gate cases. Every one passes serially and in its own module. The
  crypto-dedup failure was root-caused and fixed in §2.5. Parallel hermeticity is
  not yet proven (F16–F18); there is no deterministic failure in the suite.

```powershell
# Targeted
.\.venv\Scripts\python.exe -m pytest tests/test_auto_alerts.py tests/test_commodity_contract_selection.py tests/test_log_hygiene.py tests/test_harness_network_quarantine.py tests/test_ws_subscription_manager.py -q

# Full suite
.\.venv\Scripts\python.exe -m pytest -q -n 4 --dist loadfile

# Static
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

---

## 9. References

- SEBI, *Review of Closing Auction Session, market timings and settlement
  methodology for derivatives*, 15 October 2026.
  <https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792079571420.pdf>
- NSE, *Introduction of Closing Auction Session* and F&O expiry transition
  (FAOP/68685). <https://nsearchives.nseindia.com/content/circulars/FAOP68685.pdf>
- NSE, securities transaction tax.
  <https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax>
- FYERS, API rate limits (16 October 2026) and authentication flow.
  <https://fyers.in/notice-board/changes-to-fyers-api-rate-limits-and-usage>
- Python 3.13/3.14 release notes and free-threading status.
  <https://docs.python.org/3/whatsnew/>
- OpenTelemetry semantic conventions.
  <https://opentelemetry.io/docs/specs/semconv/>
- React 19 release notes. <https://react.dev/blog>
