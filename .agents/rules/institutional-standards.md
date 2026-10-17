# Institutional Engineering, Data Quality & UI Aesthetics Standard

> **MANDATORY INVARIANT**: This rule governs all development, architectural decisions, analytical logic, data pipelines, and UI implementations across ChanakyaTrade. Real money and real financial risk depend on this system.

---

## 1. Zero AI Hallucinations & Deterministic Grounding
- **Grounded Facts Only**: Every signal, conviction score, price level, target, and recommendation MUST be derived from real-time broker feeds, historical OHLCV data, or verified quantitative models (SMC, Minervini, VPA, Beneish, Altman, RRG).
- **Zero Fabrications**: Never fabricate or guess order IDs, fill prices, P&L amounts, execution confirmations, or forensic results.
- **Deterministic Quant Fallbacks**: All LLM interactions must be defensive with 18s timeouts. If an LLM is throttled or fails, the system MUST seamlessly fall back to pure quantitative analysis (VIX + FII/DII + Minervini + SMC). Never output raw error messages, blank cards, or hallucinated numbers.
- **Honest Feed State**: If market data is unreachable or disconnected, explicitly return `UNAVAILABLE` or `DEGRADED`. Never invent synthetic dummy prices to conceal disconnected infrastructure.

---

## 2. Zero Hardcoding & Zero False Data Representation
- **No Dummy Prices in Production**: Hardcoding static stock prices, artificial DCF multiples (e.g., `price * 1.15`), or dummy forensic statuses (e.g., hardcoded `"CLEAN"`) in production code paths is strictly prohibited.
- **Transparent Provenance**: Every event, quote, and chart snapshot must be explicitly tagged with its true provenance:
  - `REAL/LIVE` — Verified live broker WebSocket or REST feed during market hours.
  - `OFF-MARKET/EOD` — Post-market settlement / EOD candle.
  - `TEST` — Explicit synthetic test data.
  - `DEGRADED` / `UNAVAILABLE` — Stale or disconnected feed.
- **Exchange & Instrument Authority**: Instrument specifications (lot size, tick size, token, segment) must resolve from canonical exchange masters, never from client assumptions.

---

## 3. Strong, Decisive & Logically Valid Outputs
- **No Indecisive Filler**: Eliminate wishy-washy language (*"This stock could go up or it could go down"*). Be crisp, quantitative, and decisive.
- **Complete Actionable Blueprints**: Every trade recommendation, radar candidate, or alert must specify:
  1. **Exact Entry Zone**: Specific price band anchored to structural support/VWAP.
  2. **Invalidation Stop-Loss**: Structurally placed level (below 10-EMA, 200-EMA, base low, or VWAP) with exact point risk.
  3. **Target 1 (+2R)**: 50% scale-out level with immediate stop-loss adjustment to breakeven.
  4. **Target 2 (+4R)**: Extended swing target with 20-EMA / 3.0×ATR trailing stop.
  5. **Moonshot Runner (+6R+)**: High-convexity runner level for generational trends.
  6. **Strict "NO CHASE" Boundary**: Exact price limit beyond which entry is disqualified without a retest.
  7. **Risk:Reward Standard**: Enforce strict minimum $1:3.0$ R:R for asymmetric opportunities; reject unfavorable setups.

---

## 4. Elimination of Architectural Anti-Patterns
- **Fail-Closed Execution**:
  - Live orders require pilot safety gate check $\to$ pre-trade validation $\to$ execution broker call in strict sequence.
  - Broker errors must yield `status=REJECTED` with the genuine error message.
  - Ambiguous/timed-out live orders must yield `status=UNKNOWN_FREEZE` with `broker_order_id=None`. Never fabricate `LIVE-XXXXXX` IDs or assume an order was filled.
- **Hygiene & Concurrency**:
  - All HTTP requests must use `httpx` within `with` or `async with` context managers. No dangling TCP sockets.
  - All shared memory caches and state dictionaries must have thread locks (`threading.Lock()`) and LRU/TTL bounds to prevent memory leaks.
  - Enforce timezone-naive DatetimeIndex (`df.index.tz_localize(None)`) across all pandas computations.
  - Never silently swallow exceptions (`except: pass`) without structured logging or telemetry emission.
  - Frontend components must never leave unhandled Promise rejections.

---

## 5. Niche Institutional UI Aesthetics & Density
- **Bloomberg / TradingView Standard**: Institutional density, compact padding (`p-2.5`, `gap-2`, `py-1 px-2` table cells), dark theme default with crisp typography (Google Inter for body, monospace for tabular numbers).
- **Curated Color Tokens**:
  - 🟢 **Emerald (`#10B981`)**: Profit, Bullish, Verified Live, T1/T2 Targets.
  - 🔴 **Rose / Crimson (`#F43F5E`)**: Invalidation Stop-Loss, Bearish, Traps Quarantined.
  - 🟡 **Amber / Gold (`#F59E0B`)**: High Conviction Score, Precursors, Asymmetric Setups.
  - 🟣 **Indigo (`#6366F1`)**: F&O Derivatives, Greeks, Open Interest.
  - 🔵 **Sky (`#0EA5E9`)**: Benchmark Indices, Macro Contagion, Sector RRG.
- **Rich Micro-Interactions**:
  - Smooth transitions (`transition: transform 0.15s ease, opacity 0.2s`).
  - Glassmorphism overlays (`backdrop-filter: blur(12px); background: rgba(0,0,0,0.45)`).
  - 1-Click frictionless execution: all action buttons must immediately dispatch orders or ticket drafts (`autoSubmit: true`), never leaving the user stranded.
- **Zero Placeholders**: Never render broken, blank, or generic toy mockups. Every card, table, and modal must be production-grade.

---

## 6. Code Organization & Size Limits

- **Module Size Cap**: No single Python source file should exceed **800 lines** of code. If a module grows beyond this, split it into a subpackage (`module/` directory with `__init__.py`). God-files are architectural debt that kills maintainability and test isolation.
- **Duplicate Constants Prohibited**: Never define the same constant in multiple files. `IST = timezone(timedelta(hours=5, minutes=30))` and similar constants belong in `config/constants.py` and imported from there.
- **Windows Console Fix Singleton**: The UTF-8 reconfiguration block (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`) must NOT be copy-pasted across files. Import `fix_windows_console()` from `config/encoding.py` at entrypoints only.

---

## 7. Memory & Session Safety

- **Unbounded Dict Prohibition**: Never use an unbounded `dict[str, object]` for session or cache storage in a long-running server process without explicit LRU eviction bounds and TTL expiry. Unbounded dicts are guaranteed OOM vectors. Use `_LRUSessionStore` (maxsize=50, TTL=2h) for chat sessions, or a capped `collections.OrderedDict` for any cache.
- **Delisted Symbol Cache**: Any market data provider that makes network calls for a symbol MUST maintain a `_DELISTED_CACHE` with a minimum 6-hour TTL blacklist. Retrying the same delisted symbol every poll cycle is prohibited — it pollutes logs and wastes network resources.
- **WebSocket Circuit Breaker**: Any WebSocket reconnection loop MUST implement a circuit breaker. After 5 consecutive connection failures, the client MUST: (a) stop retrying for a minimum of 10 minutes, (b) emit a `DEGRADED` SSE event to the UI, and (c) log a structured circuit-open event. Silent infinite retry loops masking infrastructure failures are prohibited.

---

## 8. Watchlist & Data Integrity

- **Dynamic Universe Resolution (Zero Static Tickers)**: Watchlist presets (`WATCHLIST_PRESETS` in `agent/smart_funnel.py`) MUST NOT hardcode static ticker lists. They must resolve dynamically from canonical SSOT registries in `analysis.universe` (`SECTOR_TAXONOMY` and `THEMATIC_PRESETS`).
- **Cache Integrity**: Never cache empty collections (`opportunities: []`, `alerts: []`). Treat empty results as cache misses. Only persist verified, non-empty data. Empty caches poison downstream queries that rely on fresh data.

---

## 9. Rapid Iteration & Fast Validation Protocol

- **Skip Full Pre-Commit Gates During Development**:
  - Never execute `scripts/validate_all.py` (which runs 21 Vitest frontend workers, linters, and full multi-worker pytest matrices) during rapid interactive development or single-bug fixes. It wastes minutes and locks the terminal.
  - **Always execute targeted pytest only**: `python -m pytest tests/<relevant_test>.py -k "<test_filter>" -q`.
  - Apply the fix, run the targeted test (must take $<3$s), restart the background daemon via `scripts\service.ps1 -Action restart`, and confirm resolution directly.
  - Reserve `validate_all.py` exclusively for when the user explicitly asks for full pre-commit/pre-push validation or before production tagging.

---

## 10. Unified Order Execution Authority & Audit Parity

- **Zero Shadow Order Pathways**: All order placements — whether triggered via Desktop Web API, interactive CLI REPL (`engine/trade_executor.py`), automated agents, or scripts — MUST record immutable audit events in `orders.db` via `record_audit_event` and `_record_order_event`.
- **Reconciliation Parity**: A trade placed from the terminal must be immediately visible in `/api/reconciliation` with consistent audit lineage.

---

## 11. Detector Circuit Breaker & Scrutiny Conviction Integrity

- **Mathematical Degradation Gate**: Detectors are governed by `engine/detector_circuit_breaker.py`. Tripped detectors (`HALTED`) are suppressed; degraded detectors (`PROBATION`) receive a mandatory 25% confidence discount (`0.75x`).
- **Conviction Integrity**: Downstream AI Scrutiny or asynchronous enrichment MUST NEVER overwrite or remove the probation discount. The final confidence score must preserve the penalty: `target.confidence = max(target.confidence, int(round(scrutiny.score * cb_multiplier)))`.
- **Realized Outcome Loop**: Milestone targets (T1, T2), runner trailing stops, and invalidations must immediately record empirical WIN/LOSS outcomes into `detector_circuit_breaker.record_outcome(...)`.

---

## 12. SEBI Derivatives Physical Settlement Risk Gate

- **Single-Stock Expiry Week Risk**: Near-month single-stock options incur severe physical delivery margins in expiry week.
- **Mandatory Position Discount**: `engine.position_sizer.py` must enforce a 50% lot discount / margin buffer for stock F&O during expiry week (`is_physical_expiry_week=True`). Never size expiring stock options assuming index-style cash settlement.

---

## 13. Hermetic Test Isolation for Persistent Singletons

- **Clean State Teardown**: Any singleton or service that persists state to disk (ledgers, caches, circuit breakers) must provide a `reset_all()` method.
- **Autouse Fixture Registration**: Global autouse fixtures in `tests/conftest.py` (`sanitize_test_env`) MUST call `reset_all()` to ensure no accumulated test outcomes leak across unrelated test suites.

---

## 14. Zero Blocking Calls on Async Event Loop Threads

- **Async Event Loop Purity**: Never execute synchronous database queries, SQLite audit transactions, pandas number-crunching, or broker network requests directly on the FastAPI asyncio event loop thread.
- **Worker Thread Offloading**: Always wrap blocking operations with `await asyncio.to_thread(...)` to ensure smooth real-time SSE event publishing and WebSocket responsiveness.

---

## 15. "Right First Time" Contract Parity & Pre-Handoff Smoke Invariant

- **Zero "Fantasy Mocking"**: Frontend test mocks must NEVER be invented from imagination. They must be validated against the exact dictionary returned by the backend serializer (or generated from real API responses). Mismatches between frontend expectation and backend reality are strictly unacceptable.
- **Contract Parity Tests**: Every UI view that fetches backend data must have an automated contract parity test (`tests/test_api_ui_contracts.py`) verifying that 100% of the JSON keys referenced in JSX actually exist in the backend schema.
- **Mandatory Pre-Handoff Smoke Protocol**: Before claiming a feature, bug fix, or integration is complete, the agent MUST:
  1. Run targeted backend & frontend unit tests (`pytest` and `vitest`).
  2. Execute a real live HTTP call against the running FastAPI daemon (`GET` and `POST`) to verify status 200 OK.
  3. Verify secondary button actions (e.g. sync, reset, clear, purge) actually invoke valid backend methods without runtime exceptions or missing imports.
  4. Never leave the user to discover broken buttons or missing card fields.

---

## 16. Temporal Anchoring & Knowledge Currency Standard

- **Explicit Temporal Anchoring**: All analytical reasoning, quant strategy evaluations, macro commentaries, and backtest evaluations MUST be explicitly anchored to the current calendar date (`datetime.now(IST)` / system prompt anchor, e.g. `2026-10-17`).
- **Zero Stale Regulatory / Structural Assumptions**: Never rely on stale pre-trained LLM memory for Indian market regulatory parameters (e.g. lot sizes, weekly expiry cycles, index derivatives frameworks, STT charges). Always resolve them from canonical exchange master feeds (`market/instruments.py`, `market/symbol_master.py`) or verify via live web search (`search_web`).
- **Data Provenance Currency**: All market quotes, fundamentals, and forensic scores must carry verifiable timestamped provenance (`REAL/LIVE`, `OFF-MARKET/EOD as of YYYY-MM-DD`). If data is older than the staleness threshold, mark it explicitly as `DEGRADED` rather than presenting stale numbers as current.

