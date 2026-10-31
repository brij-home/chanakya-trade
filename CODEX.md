# CODEX.md — ChanakyaTrade Developer & Operations Guide for ChatGPT Codex IDE

> Operational handbook, local runbook, and architectural guardrails for OpenAI / ChatGPT Codex IDE working on the `chanakya-trade` codebase.

---

## 1. System Overview & Technology Stack

`ChanakyaTrade` is an institutional-grade **AI-Powered Strategic Quant Terminal & Multi-Agent Intelligence** platform built for Indian Financial Markets (**NSE, BSE, NFO, MCX**).

- **Backend**: Python 3.11+ (FastAPI sidecar on `http://127.0.0.1:8765`, SQLite audit ledgers, WebSockets, asyncio, pandas/numpy/scipy).
- **Frontend / Terminal**: React 18 + TypeScript + Vite + Tailwind CSS + TradingView Lightweight Charts (`macos-app/`), plus Python Rich/Textual interactive REPL & TUI (`app/main.py`).
- **Broker Integrations**: Fyers (primary market data & historical), Zerodha Kite, Angel One, Groww, Upstox, Dhan, Mock Broker.
- **AI Routing**: Dual-LLM routing with 4-stage zero-token pre-LLM filter (Groq, Google Gemini, Claude, OpenAI, NVIDIA NIM).

---

## 2. Component Map & Single Source of Truth (SSOT)

| Directory | Responsibility | Key Modules |
| :--- | :--- | :--- |
| **`web/`** | FastAPI sidecar API (port `8765`), SSE streaming, OAuth, MCP bridge | [`api.py`](web/api.py), [`sse.py`](web/sse.py), [`auth.py`](web/auth.py), [`mcp.py`](web/mcp.py) |
| **`engine/`** | Risk gate, fail-closed order lifecycle, position sizing, auto alert engine | [`order_lifecycle.py`](engine/order_lifecycle.py), [`risk_gate.py`](engine/risk_gate.py), [`auto_alert_engine.py`](engine/auto_alert_engine.py), [`security_360.py`](engine/security_360.py) |
| **`market/`** | Quotes gateway, option chain manager, order book, indices feeds | [`quotes.py`](market/quotes.py), [`options.py`](market/options.py), [`instruments.py`](market/instruments.py), [`order_book.py`](market/order_book.py) |
| **`analysis/`** | Quantitative sector rotation (RRG), SMC, DCF, forensics (Beneish/Altman) | [`sector_rotation.py`](analysis/sector_rotation.py), [`market_structure.py`](analysis/market_structure.py), [`forensic.py`](analysis/forensic.py), [`dcf.py`](analysis/dcf.py) |
| **`agent/`** | Multi-agent reasoning, Smart Funnel (Stages 1-4), Bull/Bear debates | [`smart_funnel.py`](agent/smart_funnel.py), [`multi_agent.py`](agent/multi_agent.py), [`dag_orchestrator.py`](agent/dag_orchestrator.py) |
| **`brokers/`** | Broker sessions, unified order routing & quote mapping | [`session.py`](brokers/session.py), [`fyers.py`](brokers/fyers.py), [`zerodha.py`](brokers/zerodha.py), [`mock.py`](brokers/mock.py) |
| **`macos-app/`** | React + Electron UI (Dark Bloomberg theme, Zustand, Vite) | [`src/App.tsx`](macos-app/src/App.tsx), [`src/store/`](macos-app/src/store/) |
| **`app/`** | Terminal interactive REPL, CLI commands & launcher | [`main.py`](app/main.py), [`repl.py`](app/repl.py) |
| **`config/`** | Constants, credentials, Windows UTF-8 console encoding | [`constants.py`](config/constants.py), [`credentials.py`](config/credentials.py), [`encoding.py`](config/encoding.py) |
| **`scripts/`** | Greenfield bootstrap, service manager, health preflights, validators | [`dev.ps1`](scripts/dev.ps1), [`service.ps1`](scripts/service.ps1), [`preflight.py`](scripts/preflight.py), [`validate_all.py`](scripts/validate_all.py) |
| **`tests/`** | Deterministic unit & integration test suites (synthetic/mock data) | [`conftest.py`](tests/conftest.py), 90+ test suites |

---

## 3. Local Environment & Execution Runbook (Windows)

All Python commands must use the local virtual environment interpreter: `.venv\Scripts\python.exe`.

### How Codex Discovers Local Code & Credentials (.env)

1. **Workspace Root & Code Discovery**:
   - When ChatGPT Codex IDE opens this repository, its execution and search context are rooted at the project root (`c:\Users\brije\.gemini\antigravity\scratch\chanakya-trade`).
   - Codex reads this `CODEX.md` file as its primary directive and directly accesses all submodules (`engine/`, `market/`, `analysis/`, `web/`, `macos-app/`).
2. **Automatic `.env` Credential Ingestion**:
   - Every system entrypoint (`web/api.py`, `app/main.py`, `agent/smart_funnel.py`, `brokers/fyers.py`, `bot/telegram_bot.py`) automatically invokes `load_dotenv(Path(__file__).parent.parent / ".env")`.
   - To provide local credentials, copy `.env.example` to `.env` at the project root:
     ```powershell
     Copy-Item .env.example .env
     ```
   - Populate `.env` with your broker keys (`FYERS_APP_ID`, `FYERS_SECRET_KEY`, `KITE_API_KEY`), AI keys (`GEMINI_API_KEY`, `GROQ_API_KEY`), and preferences.
   - `.env` is strictly excluded in `.gitignore` and is never committed.
3. **Credential Resolution Order** (`config/credentials.py`):
   - **Priority 1**: Active process environment variables / `.env` file (via `python-dotenv`).
   - **Priority 2**: OS Keychain (`keyring`) service `"chanakya-trade"` (populated via `.venv\Scripts\python.exe -m config.credentials setup`).
   - **Priority 3**: Interactive terminal prompt on initial setup.

### A. One-Command Dev Stack (Full-Stack Bootstrap)
Spins up both the FastAPI backend and the Vite frontend:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```
*Options:*
- Backend only: `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -NoFrontend`
- Custom API Port: `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -ApiPort 8765`
- Skip Preflight: `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -SkipPreflight`

### B. Standalone Backend (FastAPI Sidecar on port 8765)
```powershell
.venv\Scripts\python.exe -m web.api
# Or via uvicorn directly:
.venv\Scripts\uvicorn.exe web.api:app --host 127.0.0.1 --port 8765 --reload
```

### C. Standalone Frontend (Vite Dev Server on port 5173)
```powershell
cd macos-app
npm install
npm run dev:renderer
```
Browser interface is available at: `http://localhost:5173`

### D. Background / Daemon Service Management
```powershell
# Check background service status
powershell -ExecutionPolicy Bypass -File .\scripts\service.ps1 -Action status

# Start or restart background daemon
powershell -ExecutionPolicy Bypass -File .\scripts\service.ps1 -Action restart

# Stop background daemon
powershell -ExecutionPolicy Bypass -File .\scripts\service.ps1 -Action stop
```

### E. Interactive Terminal Terminal / REPL
```powershell
.venv\Scripts\python.exe -m app.main
```

### F. Testing & Static Verification
Run verification prior to committing:
```powershell
# Fast regression validation
.venv\Scripts\python.exe scripts/validate_all.py --fast

# Full pytest run
.venv\Scripts\pytest.exe tests/ -q

# Run an individual test file
.venv\Scripts\pytest.exe tests/test_order_lifecycle.py -v
```

---

## 4. Safety & Trading Guardrails (Core Invariants)

> **CRITICAL RULE**: Never commit `.env` or credentials. All API keys and tokens are stored in the OS keychain via `config.credentials`.

1. **Default to Paper Mode**: `TRADING_MODE=PAPER` is the safety baseline. Real live broker orders are impossible without explicit user confirmation AND `ALLOW_LIVE_TRADING=1` in the environment.
2. **Fail-Closed Order Execution Pipeline** (`engine/order_lifecycle.py`):
   - `execute_order_intent()` MUST execute: `assert_live_execution_allowed()` → pilot safety gate → `validate_pretrade()` → broker `place_order()`.
   - Any timeout, ambiguous response, or disconnect MUST fail closed with `status=UNKNOWN_FREEZE` and `broker_order_id=None`. Never fabricate mock live order IDs or emit `FILLED` on unverified states.
3. **Truthful Mode Banner** (`GET /api/mode`):
   - Canonical modes: `OBSERVE -> DEMO`, `SIMULATE -> PAPER`, `EXECUTE -> LIVE`.
   - Never allow unknown modes to silently default to PAPER. Client UI reads solely from `/api/mode`.
4. **Zero AI Hallucinations & Deterministic Grounding**:
   - Every price target, stop loss, conviction score, and setup level MUST be derived from live verified market feeds or deterministic quantitative models (SMC, Minervini SEPA, VPA, Beneish, Altman, RRG).
   - If market feeds are unreachable or off-hours, return explicit `UNAVAILABLE` or `DEGRADED` states. Never inject placeholder quotes or hardcoded multipliers (e.g. `price * 1.15`).
5. **Deterministic Alert Identity & Symbol Canonicalization**:
   - Alert IDs must only be produced via `engine.alert_identity.generate_alert_id()`.
   - Alert IDs are strictly deterministic per calendar session date (`%Y%m%d`), canonical symbol, and slug: `aa-{alert_type_slug}-{canonical_symbol}[-{variant}]-{YYYYMMDD}`.
   - Never embed volatile timestamps (`%H%M%S`) or random UUIDs in alert IDs.
6. **Single Source of Truth (SSOT)**:
   - **Alerts**: `AutoAlertEngine` (`data/auto_alerts.json`) is the sole write authority. Telegram, SSE, and UI are read-only projections.
   - **Orders & Positions**: Broker execution pipeline (`engine/order_lifecycle.py`) and SQLite audit ledger (`engine/security_audit.py`).
   - **Market Quotes**: `market.quotes` gateway with SLA tracking.
   - **Instruments**: Canonical exchange master lists (`market/instruments.py`). Never guess lot sizes or tick sizes.
7. **SEBI IPv4 Network Binding**:
   - Indian broker APIs require whitelisted IPv4 addresses. The `socket.getaddrinfo` override in `app/main.py` forces IPv4 resolution. Keep it intact.
8. **Clean Windows UTF-8 Console**:
   - At script entrypoints, call `fix_windows_console()` from `config.encoding` to prevent mojibake and encoding corruption on Windows.
9. **Async Loop Health**:
   - Heavy pandas computations, database queries, and blocking network I/O inside FastAPI endpoints must be wrapped in `asyncio.to_thread(...)` to ensure the SSE streaming connection never starves.

---

## 5. Development & Troubleshooting Workflow

### Root Cause Analysis (RCA-First Protocol)
When encountering errors, anomalies, or test failures:
1. **Check Logs**:
   - FastAPI errors: `uvicorn.err`, `uvicorn.log`, `backend_err.log`
   - Application logs: `.logs/`
2. **Inspect Pipeline**: Trace the issue from source feed → detection engine → state persistence → SSE dispatch → UI render.
3. **Strategic Fix**: Never apply superficial frontend suppressions (e.g. artificial client debounces) to mask backend engine bugs. Fix the failure mode at its source.
4. **Verify**: Always write a deterministic regression test in `tests/` that locks in the fix.

### Git Commit Etiquette
- Follow conventional commits format: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- Keep commit messages concise and descriptive.
- Do NOT add AI co-author attributions (e.g. `Co-Authored-By: ...`).
