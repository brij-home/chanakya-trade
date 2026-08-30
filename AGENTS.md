# AGENTS.md — chanakya-trade Agent Guidelines

> Operational handbook and architectural guidelines for AI agents working in the `chanakya-trade` codebase.

---

## 1. Project Context & High-Level Architecture

`ChanakyaTrade` is an institutional-grade AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence for Indian Markets (**NSE, BSE, NFO, MCX**).

### Component Map

| Directory | Responsibility | Key Modules |
| :--- | :--- | :--- |
| **`agent/`** | Multi-agent reasoning, smart funnel, screening & debates | [`smart_funnel.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/smart_funnel.py), [`multi_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/multi_agent.py), [`dag_orchestrator.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/dag_orchestrator.py), [`personas.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/personas.py), [`tools.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/tools.py) |
| **`analysis/`** | Quantitative sector rotation, forensic accounting, DCF, SMC & Multibagger | [`sector_rotation.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/sector_rotation.py), [`market_structure.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/market_structure.py), [`volume_profile.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/volume_profile.py), [`multibagger.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/multibagger.py), [`forensic.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/forensic.py), [`dcf.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/dcf.py) |
| **`brokers/`** | Broker unified abstraction (data vs execution) | [`session.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py), [`fyers.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/fyers.py) *(data)*, [`zerodha.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/zerodha.py) *(execution)*, [`angelone.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/angelone.py), [`groww.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/groww.py), [`upstox.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/upstox.py), [`mock.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/mock.py) |
| **`engine/`** | Backtesting, risk gate, execution, sizing, lifecycle & cache | [`backtest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest.py), [`trade_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trade_lifecycle.py), [`position_sizer.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/position_sizer.py), [`risk_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/risk_gate.py), [`analysis_cache.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/analysis_cache.py), [`paper.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/paper.py), [`trader.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trader.py) |
| **`market/`** | Market feeds, options chain, quotes & sentiment | [`quotes.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/quotes.py), [`options.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/options.py), [`indices.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/indices.py), [`websocket.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/websocket.py), [`sentiment.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/sentiment.py) |
| **`web/`** | FastAPI sidecar API (port `8765`), OAuth & SSE | [`api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py), [`auth.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/auth.py), [`sse.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/sse.py), [`openclaw.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/openclaw.py), [`skills.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/skills.py) |
| **`app/`** | Interactive REPL, CLI commands & launcher | [`main.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/main.py), [`repl.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/repl.py), [`commands/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/commands) |
| **`ui/`** | Rich terminal TUI & Textual widgets | [`app.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/ui/app.py), [`widgets/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/ui/widgets) |
| **`config/`** | Credential management (keychain + .env) & paths | [`credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py), [`paths.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/paths.py) |
| **`tests/`** | Comprehensive unit & integration tests | [`conftest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/conftest.py), 90+ test suites (deterministic, synthetic data) |

---

## 2. Critical Safety & Trading Guardrails

1. **Default to Paper/Mock Mode**:
   - Automated scripts, CLI commands, and test suites must **always** operate in `PAPER` or `mock` mode unless explicitly configured otherwise.
   - `TRADING_MODE=PAPER` is the safety default in `.env`.
   - Never execute real broker order placement without explicit user intent and confirmation.
2. **Credential & Secret Protection**:
   - Never commit, log, or hardcode API keys, API secrets, access tokens, TOTP secrets, passwords, or `.env` files.
   - Use [`config.credentials`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py) and OS keychain storage for sensitive tokens.
3. **SEBI IPv4 Network Binding**:
   - Indian broker APIs enforce registered static/whitelisted IPv4 addresses for order placement.
   - Keep the IPv4 `socket.getaddrinfo` override intact in [`app/main.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/main.py).
4. **Market Hours & IST Timings**:
   - Equity & F&O: 09:15 AM to 03:30 PM IST.
   - Commodity (MCX): Up to 11:30 PM / 11:55 PM IST.
   - Always handle market-closed edge cases gracefully when fetching live feeds.

---

## 3. Architecture & Design Patterns

### AI Multi-Agent & Smart Funnel Pipeline
1. **Stage 1 (Pure Quant Pre-Filter)**: 0-token deterministic screening on technicals, valuation, sector RRG momentum, forensic accounting flags, and Minervini Stage 2 status before any LLM is called.
2. **Stage 2 (Macro & Sector Context)**: India VIX, NIFTY 50 breadth, FII/DII institutional flows, and Sector RRG rotation matrix.
3. **Stage 3 (Adversarial Multi-Agent Debate & Persona Councils)**:
   - Bull vs Bear analysts + 13 Specialist Personas:
     - *Value & Moat*: `buffett`, `munger`, `lynch`
     - *Indian Growth & Multibaggers*: `jhunjhunwala`, `kedia` (SMILE Framework)
     - *Momentum & Breakouts*: `minervini` (SEPA/VCP), `wyckoff` (VSA/Spring), `oneil` (CAN SLIM)
     - *Macro, Quant & Convexity*: `soros`, `simons` (Statistical Arbitrage), `taleb` (Defined-Risk Asymmetry)
     - *Price Action & Liquidity*: `smc` (ICT Order Blocks & Sweeps)
     - *Forensic Quality*: `forensic` (Beneish M-Score, Altman Z''-Score, Pledging)
   - Specialized **Council Ensembles**:
     - `breakout`: Minervini + Wyckoff + O'Neil + Forensic Auditor
     - `options_sniper`: SMC + Taleb + Simons
     - `multibagger`: Kedia + Buffett + Munger + Jhunjhunwala + Forensic Auditor
     - `macro_regime`: Soros + Jhunjhunwala + Simons + Forensic Auditor
     - `core_value`: Buffett + Munger + Lynch + Forensic Auditor
4. **Dual-LLM Routing**:
   - Fast extraction layer (`AI_FAST_PROVIDER` e.g. Gemini Flash / Groq) for high-speed parallel extraction.
   - Deep reasoning layer (`AI_DEEP_PROVIDER` e.g. NVIDIA NIM / Claude / OpenAI / DeepSeek R1) for synthesis & risk gating.

### Quantitative, Price Action & Risk Models
- **Smart Money Concepts (SMC)**: Fractal Swings, `CHoCH` / `MSS` (reversals), `BOS` (breakouts), unmitigated Demand & Supply Order Blocks (OB), Fair Value Gaps (FVG), and Liquidity Sweeps.
- **Volume Price Analysis (VPA)**: Relative Volume (`RVOL` 20D/50D), Wyckoff Volume Spread Analysis (Absorption, Stopping Volume, Effort vs Result), and Volume Profile (`POC`, `VAH`, `VAL`).
- **Multibagger & Positional Discovery**: Mark Minervini 8-point Trend Template, Stan Weinstein 4-Stage Classification (`STAGE_2_MARKUP`), Volatility Contraction Pattern (`VCP`), and Multibagger composite score (0-100).
- **Active Position Lifecycle & Trailing Stops**: Real-time $R$-multiple payoff, $2R$ Breakeven scale-out (+0.2% cost buffer), `STRUCTURE_HL_TRAIL`, `CHANDELIER_ATR_TRAIL` ($3.0 \times \text{ATR}$), and daily 20-EMA trail.
- **Relative Rotation Graphs (RRG)**: JdK RS-Ratio (trend) and RS-Momentum (velocity) classifying sectors into `LEADING`, `WEAKENING`, `LAGGING`, `IMPROVING`.
- **Forensic Accounting**: Beneish M-Score ($>-1.78$ flag), Altman Z''-Score ($>2.60$ SAFE), Piotroski 9-point F-Score, promoter share pledging ($>10\%$/$>20\%$), and accruals quality.
- **Position Sizing**: Volatility risk-parity ($1.5 \times \text{ATR}$ risk budget), Half-Kelly growth sizing, and standard F&O lot quantization.

### Broker Routing Pattern
- **Fyers**: Primary choice for market data & options chains (free API v3).
- **Zerodha / Angel One / Groww / Upstox / Dhan / Stoxkart**: Supported execution & account management.
- Always use the fallback chain (`brokers.session.get_broker()`) with graceful degradation to `yfinance` or mock providers if a live broker is disconnected.

---

## 4. Continuous Evolution & Lessons Learned

1. **Deterministic Test Isolation (No External HTTP in Tests)**:
   - All unit tests must be self-contained and run in $<1$s without making live HTTP requests to Screener.in, Yahoo Finance, or broker APIs.
   - Pass explicit synthetic data dictionaries (`data={...}`) or monkeypatch indices/quotes to guarantee deterministic outcomes.
2. **Windows Process & Concurrency Management**:
   - On Windows environments, run full pytest suites with `.venv\Scripts\pytest.exe -n 4` to prevent OS thread/worker pool exhaustion.
3. **Persistent SQLite Caching & Poisoning Prevention**:
   - Persist computed metrics in `analysis_cache` (15m for RRG/macro, 24h for fundamental forensics) to prevent duplicate compute and eliminate redundant API calls.
   - **Never cache empty results or failed computations**: Guard `cache_set` with `if use_cache and len(results) > 0:`. When reading from cache, if the payload has 0 items, treat it as a cache miss and recompute.
4. **Daemon Server Hot-Reload & In-Memory Lifecycle**:
   - Background Python daemon processes (e.g. `uvicorn web.api:app`) hold module bytecode in memory. Edits to `analysis/` or `web/` modules do not reflect in running background tasks until the server is explicitly killed and restarted.
   - When diagnosing API or UI discrepancies, always verify background task status and restart the daemon after backend code edits.
5. **API Route Aliasing & Method Robustness**:
   - Provide route aliases for key skills (`@router.post("/high_conviction")` alongside `@router.post("/top_conviction")`, and `@router.get("/taxonomy")` alongside `@router.post("/taxonomy")` & `/universe_categories`) to prevent 404s from subtle frontend nomenclature or HTTP method mismatches.
6. **Transparent Data Provenance & Fallback Metadata**:
   - When real-time broker feeds are offline or the market is closed, quantitative engines must gracefully fall back to the most recent historical 250-day Daily OHLCV dataset without crashing.
   - Payloads and UI cards must explicitly indicate provenance (`data_source: "LIVE_TICK"` vs `"HISTORICAL_EOD"`, `as_of_date: "28 Aug 2026"`, and `dataset_timeline: "Dataset: 250D Daily Historical Bars (As of 28 Aug 2026 Close)"`).
7. **Modal UI/UX Standards**:
   - All overlay dialogs must support backdrop click dismiss (`onClick={onClose}` on the fixed container) and prevent event bubbling on the modal card (`onClick={(e) => e.stopPropagation()}`).
   - Never use blocking browser `alert(...)` popups; use non-blocking in-modal toast banners with auto-dismiss timers.
8. **Git Commits & Push ("Always Ask First")**:
   - **ALWAYS** request explicit user confirmation before executing any `git commit` or `git push` to GitHub.
   - Follow Conventional Commits format (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `perf:`).
   - **Do NOT** add `Co-Authored-By: Claude` or any AI attribution headers in commit messages.
9. **Timezone Normalization (tz-naive contract)**:
   - All historical OHLCV data pipelines ([`market/history.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/history.py)), live tick injectors (`inject_live_tick`), and backtesting engines ([`engine/backtest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest.py), [`engine/backtest_vectorized.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest_vectorized.py)) must strictly enforce timezone-naive DatetimeIndex (`df.index.tz_localize(None)`). Never perform index subtraction between mixed timezone-aware and timezone-naive timestamps.
10. **1-Click Frictionless Execution & Bi-directional Navigation**:
    - Never use `setDraft(text)` for interactive buttons or action chips where the user intends immediate execution. Always use `sendDraft(text)` (`autoSubmit: true, showDashboard: false`) to immediately run the action with 0 unnecessary clicks.
    - All action modals (e.g. Top 10 Radar, Sector Drilldown, Command Palette) must dispatch the `close-all-modals` event upon triggering an action so the interface transitions seamlessly into the live analysis stream.
    - Maintain seamless bi-directional navigation between Overview Dashboard and active card sessions (`showDashboard` state machine) without destroying loaded chat messages.
11. **Institutional Decision Clarity & Actionable Hierarchy**:
    - Outputs must never create confusion. Present clear hierarchical signals:
      - Two-tier execution status (`🟢 READY` vs `🟡 STALK` vs `🔴 STAND_DOWN`).
      - Concrete trade levels: Entry Price, Invalidation Stop-Loss, Target 1 ($2R$), Target 2 ($3.5R$).
      - Explicit "Why Pick / Why Avoid" rationale, holding timelines (e.g. 5–15 Trading Days), and trailing stop rules (`2R Breakeven`, `Chandelier ATR 3x`).
12. **Resource Leak Prevention & Connection Lifecycle**:
    - Always wrap HTTP scraper sessions (`httpx.Client`) in `with` context managers (or enforce `finally: session.close()`) to guarantee immediate TCP socket cleanup and eliminate socket/connection leaks across market scanners.
    - All unbounded in-memory dictionaries (`_df_memory_cache`, `_chat_sessions`, `_sessions`) must enforce bounded maximum capacities with LRU eviction and TTL invalidation to prevent memory growth across extended server uptimes.
13. **Dual-LLM Routing & Phase 2 Debate Latency Contract**:
    - Always wire both `deep_provider` and `fast_llm_provider` into `MultiAgentAnalyzer` across CLI, REPL, and FastAPI sidecar endpoints.
    - Route parallel research calls (Bull R1, Bear R1, Bull R2, Bear R2, Aggressive/Conservative risk debate) to `self.fast_llm` for ultra-fast parallel execution.
    - Reserve `self.llm` (Deep Reasoning) strictly for Facilitator consensus and final Fund Manager synthesis.
    - Wrap all debate futures in defensive 18.0s timeout wrappers with deterministic quantitative fallbacks.
    - Fast-fail provider authentication/key errors (`api_key_invalid`, `401`, `unauthorized`) immediately to prevent retry storms across model fallback loops.
    - Dispatch an immediate SSE start pulse (`type="debate_step", step="starting"`) as soon as Phase 2 starts to maintain responsive UI feedback.
14. **RCA First & Holistic Strategic Fixes (No Patch Work)**:
    - Never apply shallow surface-level band-aids. Always diagnose the true Root Cause Analysis (RCA) across the entire stack (data schemas, API contracts, state management, LLM routing, and DOM rendering).
    - When a bug or exception occurs, identify *why* the failure mode was possible (e.g. unhandled status codes, missing model aliases, temporal dead zone ordering, unmounted states) and refactor the architecture to make that entire class of bugs impossible.
    - If an immediate tactical fix is required for uptime, immediately follow up with the permanent strategic architectural fix.
15. **Continuous Learning & Multi-Tier Model Resilience**:
    - Treat external API limits, rate throttles, model deprecations, and network transient states (e.g. `503 UNAVAILABLE`, `429 RESOURCE_EXHAUSTED`, `high demand`) as expected operational realities.
    - Build self-healing multi-tier resilience: (1) Comma-separated API key pools with automatic round-robin cooldown rotation, (2) Validated fallback model chains (`gemini-3.6-flash` -> `gemini-3.5-flash-lite` -> `gemini-3.5-flash`), and (3) Rich deterministic quantitative engine fallback (VIX + FII/DII + Minervini + SMC) so the terminal NEVER presents raw error strings or blank cards to the user.
16. **Holistic Automated Validation & Regression Gates**:
    - Whenever modifications are made to any core module (`agent/`, `analysis/`, `engine/`, `web/`, `ui/`, `macos-app/`), execute thorough automated validation suites to ensure cross-module integrity.
    - Rebuild and test both ends of the bridge: verify the Vite bundle (`npm run build:web`), restart daemon processes, and validate API HTTP contracts end-to-end.
17. **Explicit Fallback Observability & Self-Healing Telemetry Loop**:
    - Whenever any fallback is triggered (`LLM_FAILOVER`, `LLM_COOLDOWN`, `QUANT_FALLBACK`, `DATA_FALLBACK`, `BROKER_FAILOVER`, `EXCEPTION`), the system MUST record a structured telemetry event via [`engine/telemetry.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/telemetry.py).
    - API payloads and UI views must state their execution mode explicitly (e.g. `Analysis Engine: AI Multi-Agent` vs `Quantitative Engine (Deterministic Fallback)`).
    - Periodically inspect telemetry events via `GET /skills/telemetry/summary` and CLI diagnostics to detect recurring rate limits, API drops, or missing data points, and proactively implement permanent architectural improvements.
18. **High-Density Data Controls (Filtering, Sorting & Pagination Standards)**:
    - All institutional data tables, radar cards, sector drilldown modals, and option chains must support rich data controls: (1) multi-factor filtering (e.g. Execution Status `READY`/`STALK`, Setup patterns, Strike distance `ATM ±5/±10`), (2) multi-column sorting (e.g. Conviction Score, Max Gain %, RS-Ratio, Alphabetical), (3) instant fuzzy search, and (4) paginated navigation with configurable page sizes (e.g. 5, 10, 20 items per view).
    - Never overwhelm the DOM with unbounded lists; ensure predictable vertical bounds and immediate visual feedback.
19. **Living Operational Memory & Continuous Self-Improvement**:
    - Always learn from runtime anomalies, demand spikes, and user workflows.
    - Permanently document newly discovered architectural invariants, UI ergonomics, and error prevention patterns in `AGENTS.md` and `.agents/skills/` runbooks to maintain a living, self-evolving institutional codebase.
20. **Dynamic Risk-Gated Level Calibration & Directional Invariance**:
    - Never use static legacy price levels (e.g. `21795.5` from 2024) in frontend state fallbacks or backend payload generators. Always compute dynamic levels relative to the currently active instrument's live price and ATR volatility bounds ($1.0\times - 1.2\times \text{ATR}$).
    - Enforce strict directional integrity: trade actions (`LONG (BUY)` vs `SHORT (SELL)`) must strictly match the market structure score. Never default `action = "LONG"` when market structure is bearish, which inverts the stop-loss above entry on a "long" label.
    - Every automated trade setup ticket must provide: (1) explicit timeline horizon (e.g. `1–3 Trading Sessions (Intraday Swing)`, `5–15 Trading Days (Positional Markup)`), (2) structured setup thesis explaining the technical confluence, and (3) explicit trailing stop rules (`2R Breakeven`, `Chandelier 3x ATR`).
21. **Fullscreen Viewport Adaptability & 1-Click Chart Recenter Ergonomics**:
    - All modal overlay charts and fullscreen displays must dynamically calculate available viewport heights (`Math.max(520, window.innerHeight * 0.92 - 95)`) so that secondary sub-panes (such as Stochastic RSI or MACD) are guaranteed dedicated vertical space without scroll cutoffs or clipping.
    - Order Block (OB) ribbons must use ultra-sheer background fills ($1.5\%\text{--}2.5\%$ alpha) with dashed boundaries and semi-translucent glass chip badges to ensure candlesticks and wicks remain 100% visible and uncluttered.
    - Charts must provide a dedicated 1-click `⟲ Reset View` button that calls `fitContent()`, restores price autoscale, and recalculates DOM overlay coordinates at 60fps.
22. **Advisory Risk Friction & Double-Confirmation Principle (Co-Pilot, Not Police)**:
    - Trading platforms must act as an empowering institutional risk co-pilot rather than a paternalistic police. Never hard-block user actions without providing a clear escape path.
    - When behavioral flags (consecutive loss streak $\ge 3$, anti-pyramiding into underwater positions, daily loss threshold) are triggered, present **mindful friction**:
      1. High-visibility **Behavioral Risk & Coaching Advisory** displaying psychological context and statistical probabilities (e.g. 78% failure rate on immediate tilt re-entries).
      2. Actionable coaching alternatives (e.g. reducing position risk to 0.5% or taking a 15-minute breather).
      3. Explicit **Double Confirmation** (`[x] I acknowledge the heightened risk and choose to proceed with conscious awareness`).
    - The backend engine must evaluate preflight (`evaluate_preflight`) and allow execution with user acknowledgment (`allow_override=True`), logging an immutable audit record.
23. **Specialist Personas & Council Ensemble Consensus Architecture**:
    - The terminal supports 13 specialist market personas across value, momentum, price action, quantitative statistics, macro flows, and forensic accounting:
      - `buffett`, `jhunjhunwala`, `lynch`, `soros`, `munger`, `forensic`, `minervini`, `wyckoff`, `oneil`, `taleb`, `kedia`, `simons`, `smc`.
    - Always provide predefined high-conviction **Council Ensembles** (`breakout`, `options_sniper`, `multibagger`, `macro_regime`, `core_value`) combining complementary minds to eliminate false positives and synthesize conviction scores (0-100).
    - Every persona must support both AI multi-agent LLM execution and deterministic quantitative rule-based fallback so the terminal never fails or renders blank cards.
24. **Dynamic UI Intelligence Deck Synchronization & Multi-Persona Ergonomics**:
    - The terminal overview dashboard and debate views must maintain full bidirectional synchronization between left panel navigation controls (`councils` vs `personas` vs `watchlist`) and center intelligence cards.
    - The center intelligence deck directly below the primary chart must dynamically display: (1) Full Council Ensemble Consensus with individual specialist member signal breakdowns, confidence scores, and thesis confluences, or (2) 13 Specialist Personas in a high-density carousel with authentic checklist verification, evaluated dimension metrics, and 1-click execution staging.
    - Always provide dedicated in-place mode toggles (`[ 🏛️ Councils View ]` ↔ `[ 🧠 13 Personas View ]`) with zero flash, smooth transitions, and instant action triggers.

---

## 5. Environment & Common Commands

### Running Tests
```powershell
# Run the complete fast test suite (skips network/slow tests automatically)
.venv\Scripts\pytest.exe -n 4

# Run a specific test suite with verbose output
.venv\Scripts\pytest.exe tests/test_smart_funnel.py -v

# Run with single process (debug mode)
.venv\Scripts\pytest.exe tests/test_schemas.py -n 0 -s
```

### Running the Application
```powershell
# Launch interactive terminal CLI (no broker / demo mode)
.venv\Scripts\python.exe -m app.main --no-broker

# Launch Textual TUI
.venv\Scripts\python.exe -m app.main --tui

# Start FastAPI Sidecar Web Server on port 8765
.venv\Scripts\python.exe -m uvicorn web.api:app --host 127.0.0.1 --port 8765 --reload
```

---

## 6. On-Demand Skills

Specialized step-by-step runbooks are available under `.agents/skills/`:
- **`backtesting`** (`.agents/skills/backtesting/SKILL.md`): Vectorized & regime-based strategy backtesting workflows.
- **`broker-management`** (`.agents/skills/broker-management/SKILL.md`): Adding/debugging broker authentications and OAuth callbacks.
- **`multi-agent-system`** (`.agents/skills/multi-agent-system/SKILL.md`): Agent personas, Smart Funnel, tool definitions, and LLM routing.
- **`quantitative-analysis`** (`.agents/skills/quantitative-analysis/SKILL.md`): Relative Rotation Graphs (RRG), Forensic accounting audits, and Volatility risk-parity position sizing.
- **`fastapi-sidecar`** (`.agents/skills/fastapi-sidecar/SKILL.md`): FastAPI endpoints, SSE streaming, and frontend bridges.
