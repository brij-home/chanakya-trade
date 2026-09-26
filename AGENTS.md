# AGENTS.md — ChanakyaTrade Agent Guidelines

> Operational handbook, architectural invariants, and institutional-grade standards for AI agents working in the `chanakya-trade` codebase.
> Deep domain runbooks are maintained on-demand under [`.agents/skills/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills).

---

<!-- TOC -->
- [1. Project Overview & Component Map](#1-project-overview--component-map)
- [2. Safety & Trading Guardrails (18 Core Invariants)](#2-safety--trading-guardrails-18-core-invariants)
- [3. LLM Model Hierarchy & Multi-Key Resilience](#3-llm-model-hierarchy--multi-key-resilience)
- [4. Environment & Common Commands](#4-environment--common-commands)
- [5. On-Demand Skills Directory](#5-on-demand-skills-directory)
<!-- /TOC -->

---

## 1. Project Overview & Component Map

`ChanakyaTrade` is an institutional-grade **AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence** for Indian Markets (**NSE, BSE, NFO, MCX**).

| Directory | Responsibility | Key Modules |
| :--- | :--- | :--- |
| **`agent/`** | Multi-agent reasoning, smart funnel, screening & debates | [`smart_funnel.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/smart_funnel.py), [`multi_agent.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/multi_agent.py), [`dag_orchestrator.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/dag_orchestrator.py), [`personas.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/personas.py), [`tools.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/agent/tools.py) |
| **`analysis/`** | Quantitative sector rotation, forensic accounting, DCF, SMC & Multibagger | [`sector_rotation.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/sector_rotation.py), [`market_structure.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/market_structure.py), [`volume_profile.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/volume_profile.py), [`multibagger.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/multibagger.py), [`forensic.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/forensic.py), [`dcf.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/analysis/dcf.py) |
| **`brokers/`** | Broker unified abstraction (data vs execution) | [`session.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/session.py), [`fyers.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/fyers.py), [`shoonya.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/shoonya.py), [`zerodha.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/zerodha.py), [`angelone.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/angelone.py), [`mstock.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/mstock.py), [`mock.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/brokers/mock.py) |
| **`engine/`** | Backtesting, risk gate, execution, sizing, lifecycle & cache | [`alert_identity.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/alert_identity.py), [`backtest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/backtest.py), [`trade_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/trade_lifecycle.py), [`position_sizer.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/position_sizer.py), [`risk_gate.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/risk_gate.py), [`auto_alert_engine.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/auto_alert_engine.py), [`alert_postmortem_runner.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/alert_postmortem_runner.py), [`paper.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/paper.py) |
| **`market/`** | Market feeds, options chain, quotes, sentiment & global macro | [`quotes.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/quotes.py), [`global_macro.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/global_macro.py), [`gift_nifty.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/gift_nifty.py), [`options.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/options.py), [`indices.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/indices.py), [`mstock_websocket.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/market/mstock_websocket.py) |
| **`web/`** | FastAPI sidecar API (port `8765`), OAuth & SSE | [`api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py), [`auth.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/auth.py), [`sse.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/sse.py), [`openclaw.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/openclaw.py), [`skills.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/skills.py) |
| **`app/`** | Interactive REPL, CLI commands & launcher | [`main.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/main.py), [`repl.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/repl.py), [`commands/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/commands) |
| **`ui/`** | Rich terminal TUI & Textual widgets | [`app.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/ui/app.py), [`widgets/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/ui/widgets) |
| **`bot/`** | Telegram bot for remote trade management | [`telegram_bot.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/bot/telegram_bot.py) |
| **`config/`** | Centralized constants, encoding, credentials & paths | [`constants.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/constants.py), [`encoding.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/encoding.py), [`credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py) |
| **`tests/`** | Comprehensive unit & integration tests | [`conftest.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/conftest.py), 90+ test suites (deterministic, synthetic data) |

---

## 2. Safety & Trading Guardrails (18 Core Invariants)

> **⚠️ Never commit `.env` — see [`config/credentials.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/credentials.py) for secure token management.**

1. **Default to Paper/Mock Mode**: `TRADING_MODE=PAPER` is the safety default. Never execute real broker orders without explicit user intent and double-confirmation.
2. **Credential & Secret Protection**: Never commit, log, or hardcode API keys, TOTP secrets, or passwords. Use OS keychain storage via `config.credentials`.
3. **SEBI IPv4 Network Binding**: Indian broker APIs enforce whitelisted IPv4 addresses. Keep the `socket.getaddrinfo` override intact in [`app/main.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/app/main.py).
4. **Market Hours & IST**: Equity & F&O: 09:15–15:30 IST. MCX: up to 23:30/23:55 IST. Centralized constants live in [`config/constants.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/constants.py).
5. **Advisory Risk Friction (Co-Pilot, Not Police)**: When behavioral flags (loss streak ≥3, pyramiding into losers, daily loss cap) trigger, present mindful friction with coaching alternatives and double-confirmation — never hard-block without an escape path.
6. **Live Execution Pipeline — Fail-Closed Contract** (enforced in [`engine/order_lifecycle.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/order_lifecycle.py)):
   - `execute_order_intent()` MUST call `assert_live_execution_allowed()` → pilot safety gate → `validate_pretrade()` → real `get_execution_broker().place_order()` in that order. Any short-circuit is a safety violation.
   - A paper broker exception MUST yield `status=REJECTED` with the real error as `rejection_reason`. It MUST NOT fabricate a `FILLED_PAPER` result.
   - An ambiguous or timed-out live broker response MUST yield `status=UNKNOWN_FREEZE` with `broker_order_id=None`. It MUST NOT fabricate a `LIVE-XXXXXX` ID or set `status=OPEN`.
   - `TRADING_MODE=EXECUTE` is gated by `ALLOW_LIVE_TRADING=1`. Absent that env var, `execute_order_intent()` raises `PermissionError`.
   - **Confirmation Boundary**: A `PREVIEW` is not executable. The client must submit the exact server-generated `preview_hash` to transition it to `CONFIRMED`; only `CONFIRMED → SUBMITTING` is permitted, atomically.
   - **Idempotency Semantics**: Each user order intent has a cryptographically random idempotency key. Reuse a key only to retry the same request; never derive it from order fields or use `INSERT OR REPLACE` on the order ledger.
   - **Instrument Authority**: Exchange and segment are resolved from the canonical instrument master at the server boundary. Client-provided venue/segment overrides must be rejected, not trusted.
7. **Mode Banner Truthfulness** (`GET /api/mode` in [`web/api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py)):
   - The canonical mapping is: `OBSERVE → DEMO`, `SIMULATE → PAPER`, `EXECUTE → LIVE`.
   - Do NOT add a fourth mode or let an unknown backend mode silently default to `PAPER`. Add it to the map or raise.
   - ModeBanner reads exclusively from `/api/mode`; never infer mode client-side from other signals.
8. **Security 360 Truthfulness Contract** ([`engine/security_360.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/security_360.py)):
   - If the live quote is unavailable or zero, return `_status="UNAVAILABLE"`, `decision=None`, empty lenses. Never use a hardcoded price fallback.
   - `valuation_fair_value` MUST come from a real DCF computation. Never return `price × 1.15`. Until DCF is wired, set to `None` with `valuation_status="UNAVAILABLE"`.
   - `forensic_status` MUST be the result of `audit_company_forensics(symbol)`. Never hardcode `"CLEAN"`.
   - `methodology_lenses` MUST be empty `[]` until real per-lens computation is wired. Never hardcode four BULLISH verdicts.
   - `decision` MUST be `None` when `methodology_lenses` is empty.
9. **Reconciliation Honesty Contract** (`GET /api/reconciliation` in [`web/api.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/api.py)):
   - MUST call `get_execution_broker().get_positions()` and `get_execution_broker().get_funds()` for the broker side. Never pass `internal_positions` as `broker_positions`.
   - The internal side MUST come from persisted local fills plus an explicit opening-cash baseline; never from the same broker portfolio response.
   - If the execution broker or independent ledger baseline is unavailable, return `{"status": "UNAVAILABLE"}`. Never fabricate a clean reconciliation report.
   - A successful reconciliation response MUST include `broker_account_id`, `broker_snapshot_at`, and `correlation_id` for auditability.
10. **Zero AI Hallucinations & Deterministic Grounding**:
   - Every recommendation, conviction score, price level, target, and signal MUST be derived from live market feeds or verified deterministic quantitative models (SMC, Minervini SEPA, VPA, Beneish, Altman, RRG).
   - NEVER invent, simulate, or hallucinate metrics, order IDs, fill prices, historical audit logs, or P&L figures.
   - Deterministic Quantitative Fallback: If any LLM times out (18.0s) or is rate-limited, fall back to pure quantitative models (VIX + FII/DII + Minervini + SMC). Never output raw error strings, blank cards, or hallucinated placeholder numbers.
   - Honest Feed State: When live market data is unreachable, return explicit `UNAVAILABLE` or `DEGRADED` status codes — never substitute pleasant-looking mock data to conceal a disconnected feed.
11. **Zero Hardcoding & Absolute Data Provenance**:
   - Hardcoding static quotes, arbitrary multiples (e.g., `price * 1.15`), synthetic volumes, or pre-canned "CLEAN" forensic verdicts in production pathways is strictly prohibited.
   - Every market event and UI payload must carry unambiguous provenance tags (`REAL/LIVE`, `OFF-MARKET/EOD`, `TEST`, `DEGRADED`, `UNAVAILABLE`).
   - Exchange & Instrument Authority: Instrument specifications (lot size, tick size, token, segment) must resolve from canonical exchange masters, never from client assumptions.
12. **Strong, Decisive & Actionable Logic (Zero Wishy-Washy Language)**:
   - Output must be mathematically justified, crisp, and decisive. Eliminate indecisive filler.
   - Every trade setup, radar candidate, or alert must provide a complete Actionable Blueprint: Exact Entry Zone, Invalidation Stop-Loss, Target 1 (+2R Scale 50% & SL to Breakeven), Target 2 (+4R Extension), Runner (+6R+), R:R $\ge 1:3.0$, and explicit "NO CHASE" boundary.
13. **Elimination of Architectural Anti-Patterns**:
   - Fail-Closed Gate: Any error, timeout, or ambiguity in broker order pipelines must fail closed (status `REJECTED` or `UNKNOWN_FREEZE`).
   - Connection Hygiene: Wrap `httpx` and WebSockets in context managers. No dangling TCP sockets.
   - Concurrency Safety: Shared caches must use thread locks and bounded LRU/TTL stores (see [`config/constants.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/constants.py)).
   - Timezone Normalization: Enforce timezone-naive DatetimeIndex (`df.index.tz_localize(None)`) across pandas computations.
   - Clean UTF-8: Call `fix_windows_console()` from [`config/encoding.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/config/encoding.py) at entrypoints. Zero mojibake encoding corruption.
14. **Niche Institutional UI Aesthetics & Density**:
   - Bloomberg / TradingView institutional density, compact padding (`p-2.5`, `gap-2`, `py-1 px-2` table cells), dark theme default with Inter font and tabular monospace numbers.
   - Curated color tokens: 🟢 Emerald (`#10B981`) profit, 🔴 Rose (`#F43F5E`) stop-loss, 🟡 Amber (`#F59E0B`) conviction, 🟣 Indigo (`#6366F1`) F&O, 🔵 Sky (`#0EA5E9`) macro.
   - 1-Click frictionless execution: all action buttons dispatch orders or ticket drafts (`autoSubmit: true`). Zero placeholders.
15. **Holistic Architecture & Need-Basis AI Invariants**:
   - **Strict Need-Basis AI Invocation**: AI models must NEVER be invoked unconditionally on raw market ticks or unfiltered scanner loops.
   - **4-Stage Zero-Token Pre-LLM Filter**: Lockout Gate → In-Memory TTL Dedup Cache → Deterministic Quantitative Conviction Gate → Local Pool Circuit Breaker.
   - **Zero Truncation Guarantee**: Maintain bounded token allocations with a 1.5× to 2.5× safety buffer. Enforce defensive JSON parsing with deterministic quantitative zero-blackout fallback.
16. **Institutional RCA-First Engineering Protocol**:
   - Whenever an issue, anomaly, or surge occurs (e.g. repetitive popups, duplicate dispatches, or unexpected state transitions), ALWAYS inspect the entire data pipeline (backend logs, engine events, SSE broadcast, identity generation) to isolate the true Root Cause Analysis (RCA) BEFORE proposing code changes.
   - NEVER apply cosmetic UI patches (such as client-side debouncing, hiding, or artificial rate-limiting) to mask underlying engine or backend architecture bugs. Fix the failure mode strategically at its source (schema, factory, state machine, deduplication).
   - Defensive verification: For any bug fix, write a deterministic regression test or static invariant test that prevents recurrence permanently.
17. **Centralized Alert Identity & Symbol Canonicalization Invariant**:
   - All detectors and alert creators MUST generate alert IDs exclusively via [`engine.alert_identity.generate_alert_id()`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/engine/alert_identity.py).
   - Alert IDs are strictly deterministic per calendar session date (`%Y%m%d`), canonical symbol, and variant slug: `aa-{alert_type_slug}-{canonical_symbol}[-{variant}]-{YYYYMMDD}`.
   - NEVER incorporate minute/second timestamps (`%H%M`, `%S`) or random UUIDs (`uuid.uuid4()`) in alert IDs — volatile IDs bypass in-session deduplication and trigger alert storms.
   - Symbol normalization MUST use `canonical_alert_symbol()`, uniformly stripping exchange prefixes across NSE, BSE, NFO, BFO, MCX, CDS, and Crypto.
   - Enforce static and runtime invariants via [`tests/test_alert_identity_invariants.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/tests/test_alert_identity_invariants.py).
18. **Zero In-Line Startup Migrations**:
   - Startup, file-loading, and critical loops (`_load()`) must remain idempotent, deterministic, and free of historical mutation or regex rehabilitation loops.
   - Historical database repairs, one-off schema transformations, and legacy error reconciliations belong strictly in offline administrative scripts (`scripts/remediate_corrupted_alerts.py`) or dedicated explicit methods, never executed on hot startup paths.

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

**Deprecated**: `llama-3.3-70b-versatile` was removed from Groq Cloud (returns 404). Do NOT reference it.

### Other Supported LLM Providers

| Provider | Env Var | Use Case |
| :--- | :--- | :--- |
| **Gemini** | `GEMINI_API_KEY` | Fast-LLM & Deep (`gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-1.5-flash-latest`) |
| **NVIDIA NIM** | `NVIDIA_API_KEY` | Deep reasoning (`meta/llama-3.3-70b-instruct`) |
| **OpenRouter** | `OPENROUTER_API_KEY` | Multi-model gateway fallback |
| **Anthropic** | `ANTHROPIC_API_KEY` | Deep reasoning (`claude-sonnet-4-7`) |
| **OpenAI** | `OPENAI_API_KEY` | Deep reasoning (`gpt-4o`, `o3-mini`) |

### Dual-LLM Routing & Calibrated Token Budgets

- **Fast-LLM** (`AI_FAST_PROVIDER`): Routes parallel debate rounds for sub-second extraction.
- **Deep-LLM** (`AI_DEEP_PROVIDER`): Reserved for Facilitator consensus and final Fund Manager synthesis.
- Wrap all debate futures in defensive **18.0s timeout** wrappers with deterministic quantitative fallbacks.
- **Bounded Token Budgets**:
  - `alert_scrutiny`: `max_tokens=500`
  - `quick_scan`: `max_tokens=500`
  - `persona_agent`: `max_tokens=650`
  - Multi-agent debate rounds: `max_tokens=550–650`
  - Facilitator consensus: `max_tokens=850`
  - Fund Manager synthesis: `max_tokens=1200`

---

## 4. Environment & Common Commands

### ⚡ Rapid Iteration Protocol (Zero Wait-Time Invariant)
- **During Active Iteration & Debugging**:
  - **DO NOT** run `scripts/validate_all.py` (which spins up 21 Vitest workers, Ruff, and full multi-worker Pytest smoke matrix, adding 1+ minute overhead per turn).
  - **ONLY** run targeted pytest for the modified module/test:
    `& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_specific.py -k "test_name" -q` (execution: 1–2s).
  - Apply the targeted fix, run the specific test, restart the service with `scripts\service.ps1`, and respond immediately.
- **Pre-Push / Release Gate Only**:
  - Reserve `validate_all.py --fast` or `--full` exclusively for when the user explicitly requests full pre-commit validation or when preparing a final release push.

```powershell
# Services & Lifecycle (Detached background daemon — 0 agent tasks, no prompt lock)
powershell -ExecutionPolicy Bypass -File scripts\service.ps1 -Action restart
powershell -ExecutionPolicy Bypass -File scripts\service.ps1 -Action status
powershell -ExecutionPolicy Bypass -File scripts\service.ps1 -Action stop

# Targeted Test Execution (< 2s) — MANDATORY FOR RAPID ITERATION
& "C:\Users\brije\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/test_auto_alerts.py -k "test_name" -q

# Fast Pre-Commit Gate (~60s) — USE ONLY ON EXPLICIT USER REQUEST OR FINAL PRE-PUSH
python scripts/validate_all.py --fast

# Full CI/CD Pre-Push Gate (~90s)
python scripts/validate_all.py --full
```

---

## 5. On-Demand Skills Directory

Detailed architectural runbooks and step-by-step procedures are maintained under [`.agents/skills/`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills):

| Skill | File | Purpose |
| :--- | :--- | :--- |
| **Live Trading Execution** | [`.agents/skills/live-trading-execution/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/live-trading-execution/SKILL.md) | Order lifecycle state machine, safety gates, UNKNOWN_FREEZE, reconciliation honesty |
| **Alert System** | [`.agents/skills/alert-system/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/alert-system/SKILL.md) | Alert lifecycle, 4-stage pre-LLM filter, detector registration, scrutiny tiers |
| **Frontend Development** | [`.agents/skills/frontend-development/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/frontend-development/SKILL.md) | React/Electron component architecture, Bloomberg color tokens, SSE, build pipeline |
| **Multi-Agent System** | [`.agents/skills/multi-agent-system/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/multi-agent-system/SKILL.md) | Smart Funnel, 13 specialist personas, Dual-LLM routing, tool definitions |
| **Quantitative Analysis** | [`.agents/skills/quantitative-analysis/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/quantitative-analysis/SKILL.md) | RRG, Forensic audits, SMC, VPA, Position sizing, Trade lifecycle |
| **FastAPI Sidecar** | [`.agents/skills/fastapi-sidecar/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/fastapi-sidecar/SKILL.md) | REST endpoints, SSE streaming, OAuth handlers, frontend bridges |
| **Broker Management** | [`.agents/skills/broker-management/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/broker-management/SKILL.md) | Adding/debugging broker auth, OAuth callbacks, TOTP login |
| **Backtesting** | [`.agents/skills/backtesting/SKILL.md`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/.agents/skills/backtesting/SKILL.md) | Vectorized & regime-based strategy backtesting, options backtesting |
