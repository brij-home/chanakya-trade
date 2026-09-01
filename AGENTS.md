# AGENTS.md — ChanakyaTrade Agent Guidelines

> Operational handbook, architectural invariants, and institutional-grade standards for AI agents working in the `chanakya-trade` codebase.

---

<!-- TOC -->
- [1. Project Overview](#1-project-overview)
- [2. Safety & Trading Guardrails](#2-safety--trading-guardrails)
- [3. LLM Model Hierarchy & Multi-Key Resilience](#3-llm-model-hierarchy--multi-key-resilience)
- [4. Architecture & Design Patterns](#4-architecture--design-patterns)
- [5. Data Pipeline & Quality Standards](#5-data-pipeline--quality-standards)
- [6. Frontend & UX Standards](#6-frontend--ux-standards)
- [7. Operational Invariants & Lessons Learned](#7-operational-invariants--lessons-learned)
- [8. Environment & Common Commands](#8-environment--common-commands)
- [9. On-Demand Skills](#9-on-demand-skills)
<!-- /TOC -->

---

## 1. Project Overview

`ChanakyaTrade` is an institutional-grade **AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence** for Indian Markets (**NSE, BSE, NFO, MCX**).

### Component Map

| Directory | Responsibility | Key Modules |
| :--- | :--- | :--- |
| **`agent/`** | Multi-agent reasoning, smart funnel, screening & debates | [`smart_funnel.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/smart_funnel.py), [`multi_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/multi_agent.py), [`dag_orchestrator.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/dag_orchestrator.py), [`personas.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/personas.py), [`tools.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/tools.py) |
| **`analysis/`** | Quantitative sector rotation, forensic accounting, DCF, SMC & Multibagger | [`sector_rotation.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/sector_rotation.py), [`market_structure.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/market_structure.py), [`volume_profile.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/volume_profile.py), [`multibagger.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/multibagger.py), [`forensic.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/forensic.py), [`dcf.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/dcf.py) |
| **`brokers/`** | Broker unified abstraction (data vs execution) | [`session.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py), [`fyers.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/fyers.py) *(data)*, [`zerodha.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/zerodha.py) *(execution)*, [`angelone.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/angelone.py), [`groww.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/groww.py), [`upstox.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/upstox.py), [`mock.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/mock.py) |
| **`engine/`** | Backtesting, risk gate, execution, sizing, lifecycle & cache | [`backtest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest.py), [`trade_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trade_lifecycle.py), [`position_sizer.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/position_sizer.py), [`risk_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/risk_gate.py), [`analysis_cache.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/analysis_cache.py), [`paper.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/paper.py), [`trader.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trader.py) |
| **`market/`** | Market feeds, options chain, quotes, sentiment & global macro | [`quotes.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/quotes.py), [`global_macro.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/global_macro.py), [`gift_nifty.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/gift_nifty.py), [`options.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/options.py), [`indices.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/indices.py), [`websocket.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/websocket.py), [`sentiment.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/sentiment.py) |
| **`web/`** | FastAPI sidecar API (port `8765`), OAuth & SSE | [`api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py), [`auth.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/auth.py), [`sse.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/sse.py), [`openclaw.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/openclaw.py), [`skills.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/skills.py) |
| **`app/`** | Interactive REPL, CLI commands & launcher | [`main.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/main.py), [`repl.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/repl.py), [`commands/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/commands) |
| **`ui/`** | Rich terminal TUI & Textual widgets | [`app.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/ui/app.py), [`widgets/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/ui/widgets) |
| **`bot/`** | Telegram bot for remote trade management | [`telegram_bot.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/bot/telegram_bot.py) |
| **`config/`** | Credential management (keychain + .env) & paths | [`credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py), [`paths.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/paths.py) |
| **`tests/`** | Comprehensive unit & integration tests | [`conftest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/conftest.py), 90+ test suites (deterministic, synthetic data) |

---

## 2. Safety & Trading Guardrails

> **⚠️ Never commit `.env` — see [`config/credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py) for secure token management.**

1. **Default to Paper/Mock Mode**: `TRADING_MODE=PAPER` is the safety default. Never execute real broker orders without explicit user intent and double-confirmation.
2. **Credential & Secret Protection**: Never commit, log, or hardcode API keys, TOTP secrets, or passwords. Use OS keychain storage via `config.credentials`.
3. **SEBI IPv4 Network Binding**: Indian broker APIs enforce whitelisted IPv4 addresses. Keep the `socket.getaddrinfo` override intact in [`app/main.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/main.py).
4. **Market Hours & IST**: Equity & F&O: 09:15–15:30 IST. MCX: up to 23:30/23:55 IST. Handle market-closed edge cases gracefully.
5. **Advisory Risk Friction (Co-Pilot, Not Police)**: When behavioral flags (loss streak ≥3, pyramiding into losers, daily loss cap) trigger, present mindful friction with coaching alternatives and double-confirmation — never hard-block without an escape path.

---

## 3. LLM Model Hierarchy & Multi-Key Resilience

### Groq Cloud Active Models (Verified 31 Aug 2026)

| Priority | Model ID | Latency | Tool-Calling | Best For |
| :---: | :--- | :---: | :---: | :--- |
| 1 | `qwen/qwen3.8-27b` | ~389 ms | ✅ Yes | **Fast-LLM**: Real-time tool calls (quotes, options, VPA), parallel debate rounds |
| 2 | `openai/gpt-oss-120b` | ~446 ms | ❌ No | **Deep-LLM**: Council consensus synthesis, Fund Manager final verdict |
| 3 | `openai/gpt-oss-20b` | ~471 ms | ❌ No | Lower-cost fallback for pure-text generation |
| 4 | `qwen/qwen3.6-27b` | ~660 ms | ❌ No | Secondary fallback when primary models are throttled |
| 5 | `groq/compound-mini` | — | ❌ No | Cheapest option for non-critical batch jobs |

**Deprecated / Unavailable**: `llama-3.3-70b-versatile` — removed from Groq Cloud (returns `404 model_not_found`). Do NOT reference this model in any configuration.

### Multi-Key Pooling & Self-Healing

- **Comma-Separated Key Pools**: `GROQ_API_KEY=key1,key2[,key3]` in `.env` — the provider automatically round-robins across keys.
- **Automatic Cooldown Rotation**: When any key hits `429 Too Many Requests` or TPM exhaustion, it enters a 45s cooldown and all traffic shifts to the next healthy key.
- **Model Failover Chain**: If a model returns `404` or `401`, the system immediately tries the next model in the priority chain without user-visible delay.
- **Deterministic Quantitative Fallback**: If ALL LLM providers fail, the system falls back to pure quantitative analysis (VIX + FII/DII + Minervini + SMC) — the terminal NEVER shows raw error strings or blank cards.

### Other Supported LLM Providers

| Provider | Env Var | Use Case |
| :--- | :--- | :--- |
| **Gemini** | `GEMINI_API_KEY` | Fast-LLM (`gemini-3.7-flash`, `gemini-3.6-flash`) |
| **NVIDIA NIM** | `NVIDIA_API_KEY` | Deep reasoning (`meta/llama-3.3-70b-instruct`) |
| **OpenRouter** | `OPENROUTER_API_KEY` | Multi-model gateway fallback |
| **Anthropic** | `ANTHROPIC_API_KEY` | Deep reasoning (`claude-sonnet-4`) |
| **OpenAI** | `OPENAI_API_KEY` | Deep reasoning (`gpt-4o`, `o3-mini`) |

### Dual-LLM Routing Contract

- **Fast-LLM** (`AI_FAST_PROVIDER`): Routes parallel debate rounds (Bull R1, Bear R1, Bull R2, Bear R2, Aggressive/Conservative risk) for sub-second extraction.
- **Deep-LLM** (`AI_DEEP_PROVIDER`): Reserved for Facilitator consensus and final Fund Manager synthesis only.
- All debate futures must be wrapped in defensive **18.0s timeout** wrappers with deterministic quantitative fallbacks.
- Fast-fail on auth errors (`api_key_invalid`, `401`) immediately — no retry storms.
- Dispatch SSE start pulse (`type="debate_step", step="starting"`) as Phase 2 begins.

---

## 4. Architecture & Design Patterns

### 4.1 AI Multi-Agent & Smart Funnel Pipeline

1. **Stage 1 (Pure Quant Pre-Filter)**: 0-token deterministic screening on technicals, valuation, sector RRG momentum, forensic flags, and Minervini Stage 2 status.
2. **Stage 2 (Macro & Sector Context)**: India VIX, NIFTY 50 breadth, FII/DII flows, Sector RRG rotation matrix.
3. **Stage 3 (Adversarial Multi-Agent Debate & Persona Councils)**:
   - Bull vs Bear analysts + **13 Specialist Personas**:
     - *Value & Moat*: `buffett`, `munger`, `lynch`
     - *Indian Growth & Multibaggers*: `jhunjhunwala`, `kedia` (SMILE Framework)
     - *Momentum & Breakouts*: `minervini` (SEPA/VCP), `wyckoff` (VSA/Spring), `oneil` (CAN SLIM)
     - *Macro, Quant & Convexity*: `soros`, `simons` (Statistical Arb), `taleb` (Defined-Risk)
     - *Price Action & Liquidity*: `smc` (ICT Order Blocks & Sweeps)
     - *Forensic Quality*: `forensic` (Beneish M-Score, Altman Z''-Score, Pledging)
   - **Council Ensembles**: `breakout`, `options_sniper`, `multibagger`, `macro_regime`, `core_value`
4. **Stage 4 (Fund Manager Synthesis)**: Final verdict with entry, stop-loss, targets, and position sizing.

### 4.2 Quantitative & Risk Models

- **SMC**: Fractal Swings, CHoCH/MSS reversals, BOS breakouts, Order Blocks, FVGs, Liquidity Sweeps.
- **VPA**: RVOL 20D/50D, Wyckoff VSA, Volume Profile (POC, VAH, VAL).
- **Multibagger Engine**: Minervini 8-point Trend Template, Weinstein Stage 2, VCP, Multibagger Score (0-100).
- **Position Lifecycle**: Real-time R-multiple payoff, 2R Breakeven scale-out, Chandelier ATR Trail (3.0×ATR), 20-EMA trail.
- **RRG Sector Rotation**: JdK RS-Ratio + RS-Momentum → LEADING / WEAKENING / LAGGING / IMPROVING.
- **Forensic Accounting**: Beneish M-Score (>−1.78 flag), Altman Z''-Score (>2.60 SAFE), Piotroski F-Score, promoter pledging.
- **Position Sizing**: ATR volatility risk-parity (1.5×ATR), Half-Kelly, F&O lot quantization.
- **3-Axis Magic Trend**: Moat/Quality (35pts) + Growth/Migration (35pts) + Timing/Asymmetry (30pts).

### 4.3 Broker Routing

- **Fyers**: Primary for market data & options chains (free API v3).
- **Zerodha / Angel One / Groww / Upstox / Dhan / Stoxkart**: Execution & account management.
- Always use fallback chain (`brokers.session.get_broker()`) with graceful degradation to `yfinance` or mock.

### 4.4 Real-Time Data Feed Strategy

- **Primary**: WebSocket via Fyers SDK ([`market/websocket.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/websocket.py)) for instant tick data.
- **Fallback**: REST polling at 60s intervals when WebSocket is unavailable.
- **UI Indicator**: Display `🟢 Live` badge when WebSocket is connected, `🟡 Polling` when using REST fallback. User must always know their data source.

### 4.5 Global Macro Transmission & Multi-Asset Universe Taxonomy

- **The High-Correlation 6** ([`market/global_macro.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/global_macro.py)):
  - **GIFT NIFTY (NSE IFSC)**: ~0.96 Correlation to NIFTY 50 opening price. Computes `implied_nifty_gap_pct` and `implied_nifty_gap_pts`.
  - **NASDAQ 100 (`^IXIC`) & S&P 500 (`^GSPC`)**: ~0.82 Correlation to Indian IT Services (`TCS`, `INFY`, `HCLTECH`, `COFORGE`).
  - **US Dollar Index (DXY) & USD/INR (`INR=X`)**: -0.74 Correlation with FII foreign equity flows.
  - **Brent Crude Oil (`BZ=F`)**: Bipolar correlation — Negative (-0.78) for Paints (`ASIANPAINT`), Aviation (`INDIGO`), Tyres, OMCs; Positive (+0.82) for Upstream Exploration (`ONGC`, `OIL`, `RELIANCE`).
  - **US 10-Year Treasury Yield (`^TNX`)**: -0.70 Correlation to High-PE growth valuations and multiple compression.
  - **US VIX vs India VIX**: Volatility contagion and options writing risk-parity.
- **Multi-Asset Universe Segmentation** ([`analysis/universe.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/universe.py)):
  - Intelligent auto-exchange prefix resolution:
    - Commodities (`GOLD`, `SILVER`, `CRUDEOIL`, `NATURALGAS`, `COPPER`) → `MCX:`
    - Currency pairs (`USDINR`, `EURINR`, `GBPINR`, `JPYINR`) → `CDS:`
    - BSE Indices (`SENSEX`, `BANKEX`) → `BSE:`
    - Equities & benchmark indices → `NSE:`
  - Dual-key quote dictionary lookup ensures queries for `GOLD` or `MCX:GOLD` resolve without KeyError.
- **MCX Commodity Quotation Unit Normalization** ([`market/yfinance_provider.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/yfinance_provider.py)):
  - COMEX/NYMEX futures on `yfinance` quote in US physical units (`GC=F` in USD/troy oz, `SI=F` in USD/troy oz, `HG=F` in USD/lb, `CL=F` in USD/bbl).
  - For MCX display, multiply by USD/INR rate AND standard physical quotation unit multipliers:
    - **Gold (`GC=F`)**: $\times \text{USDINR} \times (10 / 31.1034768)$ (₹ per 10 grams)
    - **Silver (`SI=F`)**: $\times \text{USDINR} \times (1000 / 31.1034768)$ (₹ per 1 kg)
    - **Copper (`HG=F`)**: $\times \text{USDINR} \times 2.20462262$ (₹ per 1 kg)
    - **Crude Oil (`CL=F`) / Natural Gas (`NG=F`)**: $\times \text{USDINR} \times 1.0$ (₹ per bbl / MMBtu)
  - Applied uniformly to both live quotes and historical OHLCV chart feeds.
- **Zero Static / False Data Policy**: Macro indicators and quotes MUST be fetched dynamically from real live feeds (`yfinance` fast_info, Fyers WebSocket, NSE IFSC). Static mock fallbacks are strictly prohibited in production pathways.

---

## 5. Data Pipeline & Quality Standards

1. **Transparent Provenance**: Every payload must include `data_source` (`LIVE_TICK` / `HISTORICAL_EOD`), `as_of_date`, and `dataset_timeline`.
2. **Cache Architecture**: SQLite `analysis_cache` with TTL (5min live quotes, 15min RRG/macro, 24h fundamentals).
3. **Never Cache Empty Results**: Guard `cache_set` with `if len(results) > 0:`. Treat empty cache reads as misses.
4. **Single-Source OHLCV**: Fetch 250D Daily OHLCV once, pass in-memory to all analyzers (66% network reduction).
5. **Timezone Normalization**: Enforce tz-naive DatetimeIndex (`df.index.tz_localize(None)`) everywhere. Never mix tz-aware and tz-naive timestamps.
6. **Bounded In-Memory Caches**: All dicts (`_df_memory_cache`, `_chat_sessions`, `_sessions`) must have LRU eviction and TTL to prevent memory growth.
7. **Connection Hygiene**: Wrap `httpx.Client` in `with` context managers. No dangling TCP sockets.
8. **Telemetry Observability**: Every fallback (`LLM_FAILOVER`, `LLM_COOLDOWN`, `QUANT_FALLBACK`, `DATA_FALLBACK`, `BROKER_FAILOVER`, `EXCEPTION`) emits structured telemetry via [`engine/telemetry.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/telemetry.py).
9. **Dynamic Cross-Module Pipeline Invariants**: Cross-module analytical interfaces (`get_stock_tailwind` in [`analysis/sector_rotation.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/sector_rotation.py), `audit_company_forensics` in [`analysis/forensic.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/forensic.py), and `get_options_chain` in [`market/options.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/options.py)) MUST always return structured objects with uniform attribute & dictionary compatibility (`StockTailwind`, `ForensicAuditResult`) and dynamic fallback chains without ever returning static mock fallbacks in production pathways.

---

## 6. Frontend & UX Standards

### 6.1 Theme & Visual Design
- **Default dark theme**; users can toggle to light via the `ThemeToggle` component.
- **Glass-morphism overlays** for modals: `backdrop-filter: blur(12px); background: rgba(0,0,0,0.45)`.
- **Inter font** from Google Fonts for all body text; monospace for data tables.
- **Micro-animations**: `transition: transform 0.15s ease, opacity 0.2s` on cards, buttons, hover states.
- **Institutional density**: Bloomberg/TradingView-style compact padding (`p-2.5 sm:p-3.5`, `gap-2.5`, `py-1 px-2` table cells).

### 6.2 Interaction Patterns
- **1-Click Frictionless Execution**: Use `sendDraft(text)` (`autoSubmit: true`) — never `setDraft(text)` for action buttons.
- **Modal Dismiss**: All modals support backdrop click dismiss + `e.stopPropagation()`. No blocking `alert()` popups.
- **Bi-directional Navigation**: Sticky `← 🏠 Dashboard` button and `← Return to Active View` banner between dashboard and analysis cards.
- **Zero-Latency Cancellation**: Wire `AbortController` + `⛔ Stop` buttons for all streaming operations.
- **Progressive Stage Indicators**: `⚡ Initializing...` → `🔍 Technicals & Patterns...` → `🔬 Cross-Examination...` → `⚖️ Consensus...`

### 6.3 Data Presentation
- **Top-Conviction Radar**: Show 10 items on ≥1280px screens, 5 on smaller viewports.
- **Signal Hierarchy**: `🟢 READY` / `🟡 STALK` / `🔴 STAND_DOWN` with concrete Entry, Stop-Loss, Target 1 (2R), Target 2 (3.5R).
- **High-Density Controls**: Multi-factor filtering, multi-column sorting, instant fuzzy search, paginated navigation (5/10/20 per page).
- **Smart Typeahead**: Punctuation-agnostic fuzzy match across symbols, company names, aliases, sectors. Category badges (`[STOCK]`, `[INDEX]`, `[ETF]`, `[COMMODITY]`). Full keyboard navigation (`↑/↓`, `Enter`, `Tab`, `Esc`).
- **Dynamic Chart Viewport**: `Math.max(520, window.innerHeight * 0.92 - 95)` for fullscreen charts. OB ribbons at 1.5–2.5% alpha. 1-click `⟲ Reset View`.
- **Options Chain**: Mathematical ATM strike index (`min(abs(strike - spot))`), ≥41 strikes coverage.

### 6.4 React & Build Standards
- **Hook Purity**: Hooks MUST be unconditional at the top of every component. Never place early returns before hooks.
- **Error Boundaries**: Every global modal and dynamic card wrapped in `<ErrorBoundary>` with graceful fallback.
- **AST Hook Linting**: `node scripts/audit-react-hooks.js` enforces 0 violations in `npm test` and `npm run build:web`.
- **Root Error Boundary**: Wrap root app in [`main.jsx`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/macos-app/src/renderer/src/main.jsx) to prevent white screens.
- **Web Mode**: Support standalone browser access (`window.__CHANAKYA_TRADE_WEB__ || !window.electronAPI`) with fallback port `8765`.

### 6.5 JSDoc & TypeScript Type Contracts
- **Type Definitions Repository**: All frontend data models are strongly typed in [`renderer/src/types/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/macos-app/src/renderer/src/types/) (`contracts.ts`, `market.js`, `options.js`, `personas.js`, `backtest.js`, `index.js`).
- **Mixed TS Support**: Configured via [`tsconfig.json`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/macos-app/tsconfig.json) (`allowJs: true`, `@/*` path alias) for zero-friction mixed JavaScript & TypeScript development.
- **1:1 Backend Parity**: Frontend types mirror Python Pydantic backend models in `engine/` and `agent/personas.py`.
- **Defensive Unwrapping**: Always normalize API responses via `const data = res?.data ?? res`.

### 6.6 9-Workspace Navigational Architecture
- **Persistent ActivityBar Rail**: 48px left rail with keyboard shortcut index:
  - `^1`: **Strategic Quant Terminal** (4-column layout with Symbol header, Lightweight Charts, and Trade Desk Rail)
  - `^2`: **Multi-Agent Debate Arena** (4-stage pipeline stepper + 13-member 3D flippable council cards)
  - `^3`: **Options & GEX Desk** (Bloomberg-style chain + Payoff Simulator)
  - `^4`: **AI Copilot** (Progressive typing wave + chronological date-grouped sessions)
  - `^5`: **Market Overview** (VIX gauge, RRG mini-map, FII/DII flow tracker)
  - `^6`: **Portfolio Doctor Pro** (Concentration & SEPA compliance diagnostics)
  - `^7`: **Alerts Manager** (Price & technical threshold monitors)
  - `^8`: **Trade Journal** (GitHub-style Win/Loss Calendar Heatmap + realized P&L stats)
  - `^9`: **Backtest Studio** (Interactive equity progression vs NIFTY 50 + trade execution ledger)

### 6.7 Indian Currency & Number Formatting Standard
- **Utility**: Always use [`formatINR.js`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/macos-app/src/renderer/src/utils/formatINR.js) (`formatINR`, `formatINRFull`, `formatPct`, `formatVol`) for all price, P&L, turnover, and volume values.
- **Units**: Automatic scaling (`₹Cr`, `₹L`, `₹K`) with null/NaN defensive guards and ₹ currency prefix.

---

## 7. Operational Invariants & Lessons Learned

### 7.1 Testing & CI
1. **Deterministic Test Isolation**: All unit tests run in <1s with synthetic data — no live HTTP calls. Enforced via `CHANAKYA_TESTING=1` and `sanitize_test_env` in `conftest.py`.
2. **Windows Concurrency**: Use `.venv\Scripts\pytest.exe -n 4` with cooperative thread teardowns to prevent worker accumulation.
3. **Tiered Validation Gates**:
   - **Fast Pre-Commit Gate (< 8s)**: `.venv\Scripts\python.exe scripts/validate_all.py --fast` (Ruff lint + Format + React Hook AST audit + Vitest + Fast smoke matrix).
   - **Full Pre-Push Gate (< 30s)**: `.venv\Scripts\python.exe scripts/validate_all.py --full` (All linters + Vitest + Web build + Full 2,188+ test matrix with 4 workers).
   - **Daily / Nightly Deep Regression**: `.venv\Scripts\python.exe scripts/validate_daily.py` (Full matrix + Monte Carlo & options stress tests + Live network integration).
   - **Environment & Process Cleanup**: `.venv\Scripts\python.exe scripts/cleanup.py` (Purges orphaned workers, frees port 8765, removes temp sqlite lock files).
4. **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `perf:`. No AI attribution headers.
5. **Always request explicit user confirmation** before executing `git commit` or `git push`.

### 7.2 Server & Daemon Lifecycle
6. **Thread Lifecycle & Cooperative Cancellation**: All background pollers in `engine/` MUST use `self._stop_event = threading.Event()`, wait on `self._stop_event.wait(timeout=...)` instead of blocking `time.sleep()`, and provide clean `.join(timeout=1.0)` in `stop_polling()`.
7. **Hot-Reload Awareness**: Background daemons (`uvicorn web.api:app`) cache imports. Always restart after backend code edits.
8. **API Route Aliasing**: Register aliases (`/high_conviction` + `/top_conviction`, `/taxonomy` + `/universe_categories`) with both GET and POST to prevent 404s.

### 7.3 LLM Provider Management
9. **Module Root Auto-loading**: Execute `load_dotenv()` and `config.credentials.load_all()` at module root in [`agent/core.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/core.py) and [`agent/persona_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/persona_agent.py), guarded by `if not os.environ.get("CHANAKYA_TESTING"):`.
10. **Keyring Precedence**: Never let stale keychain tokens override active `.env` keys. Filter out placeholders.
11. **Provider-Specific Model Isolation**: Groq, NVIDIA NIM, OpenRouter, and Gemini must each resolve to their own model IDs — no global `AI_MODEL` crosstalk.
12. **ToolRegistry Contract**: Always expose `.get_fn(name)` alongside `.execute(name, args)`.

### 7.4 Quantitative Engine
13. **Dynamic Risk Calibration**: Never use static legacy price levels. Compute levels from live price + ATR.
14. **Directional Integrity**: Trade actions must match market structure score. Never default `LONG` when bearish.
15. **Trade Ticket Completeness**: Every setup must include: timeline horizon, thesis, trailing stop rules.

### 7.5 Architecture Principles
16. **RCA First**: Diagnose root causes across the full stack. No surface-level band-aids.
17. **Living Documentation**: Update `AGENTS.md` and skill runbooks when new invariants are discovered.
18. **Self-Healing Resilience**: Multi-key pools → model failover chains → deterministic quant fallback. Terminal never shows raw errors.
19. **Python Linting**: `ruff check .` + `ruff format --check .` before commits. Zero undefined variable names.

### 7.6 Holistic Invariant Architecture & Zero-Patchwork Engineering Standard
20. **Single Source of Truth (SSOT) at Ingress Boundaries**:
    - Never write localized `if (symbol === '...')` or `exchange || 'NSE'` ternary expressions inside individual UI cards or individual route handlers.
    - All incoming instruments MUST pass through canonical normalizers at architectural boundaries:
      - **Backend**: Inherit from `InstrumentBaseRequest(BaseModel)` in [`web/skills.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/skills.py) which auto-resolves `(symbol, exchange)` via `analysis.universe.normalize_symbol_exchange()`.
      - **Frontend**: Call `resolveInstrument(rawSymbol, rawExchange)` in [`universeData.js`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/macos-app/src/renderer/src/data/universeData.js) across stores, input bars, typeaheads, and cards.
21. **Full Blast-Radius Auditing Protocol (No Piecemeal Fixes)**:
    - Whenever a domain rule or invariant is added/modified (e.g. multi-asset exchange mapping, formatting, risk rules, date handling), the agent MUST audit ALL 6 layers of the stack in the same pass:
      1. Schemas & Type Contracts (`web/skills.py`, `renderer/src/types/`)
      2. Core Logic & Analyzers (`agent/multi_agent.py`, `engine/`, `analysis/`)
      3. Backend APIs & Daemons (`web/api.py`, `web/skills.py`)
      4. Store & State Layer (`chatStore.js`, `inspectorStore.js`)
      5. Ingress & OmniSearch Routing (`InputBar.jsx`, `CommandPalette.jsx`, `SmartTypeahead.jsx`, `universeData.js`)
      6. Output Presentation & Views (`StreamingAnalysisCard.jsx`, `AnalysisCard.jsx`, `QuoteCard.jsx`, Workspace Views)
22. **Cross-Asset Taxonomy Matrix Testing**:
    - Every change touching symbols, quotes, or cards MUST be tested against the full asset taxonomy matrix:
      `[Equity (RELIANCE), Commodity (GOLD, CRUDEOIL), Forex (USDINR), Index (NIFTY50, SENSEX), ETF (GOLDBEES)]`
    - Test suites ([`tests/test_taxonomy_matrix.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_taxonomy_matrix.py) and [`macos-app/src/__tests__/taxonomyMatrix.test.js`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/macos-app/src/__tests__/taxonomyMatrix.test.js)) must verify zero fallback leakage of default values (`NSE`) to non-NSE assets.
23. **Zero Legacy Drift**:
    - Purge hardcoded fallback defaults at the root instead of layering defensive wrappers over stale code.

---

## 8. Environment & Common Commands

### Running Validation Gates
```powershell
# Fast local pre-commit check (< 8s)
.venv\Scripts\python.exe scripts/validate_all.py --fast

# Full CI/CD pre-push gate (2,188+ tests + Web build, < 30s)
.venv\Scripts\python.exe scripts/validate_all.py --full

# Daily/Nightly deep regression & simulation runner
.venv\Scripts\python.exe scripts/validate_daily.py

# Universal process & resource cleanup
.venv\Scripts\python.exe scripts/cleanup.py
```

### Running Tests
```powershell
# Complete fast test suite (skips network/slow tests)
.venv\Scripts\pytest.exe -n 4

# Specific test suite with verbose output
.venv\Scripts\pytest.exe tests/test_smart_funnel.py -v

# Single process debug mode
.venv\Scripts\pytest.exe tests/test_schemas.py -n 0 -s
```

### Running the Application
```powershell
# Interactive terminal CLI (no broker / demo mode)
.venv\Scripts\python.exe -m app.main --no-broker

# Textual TUI
.venv\Scripts\python.exe -m app.main --tui

# FastAPI Sidecar Web Server on port 8765
.venv\Scripts\python.exe -m uvicorn web.api:app --host 127.0.0.1 --port 8765 --reload
```

---

## 9. On-Demand Skills

Specialized step-by-step runbooks under [`.agents/skills/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills):

| Skill | File | Purpose |
| :--- | :--- | :--- |
| **Backtesting** | [`.agents/skills/backtesting/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/backtesting/SKILL.md) | Vectorized & regime-based strategy backtesting, options backtesting |
| **Broker Management** | [`.agents/skills/broker-management/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/broker-management/SKILL.md) | Adding/debugging broker auth, OAuth callbacks, TOTP login |
| **Multi-Agent System** | [`.agents/skills/multi-agent-system/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/multi-agent-system/SKILL.md) | Smart Funnel, persona agents, Dual-LLM routing, tool definitions |
| **Quantitative Analysis** | [`.agents/skills/quantitative-analysis/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/quantitative-analysis/SKILL.md) | RRG, Forensic audits, SMC, VPA, Position sizing, Trade lifecycle |
| **FastAPI Sidecar** | [`.agents/skills/fastapi-sidecar/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/fastapi-sidecar/SKILL.md) | REST endpoints, SSE streaming, OAuth handlers, frontend bridges |
