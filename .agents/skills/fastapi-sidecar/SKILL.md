---
name: fastapi-sidecar
description: >-
  Develop, test, and maintain the FastAPI sidecar server (port 8765), SSE
  streaming endpoints, OpenClaw skill manifests, OAuth callback handlers,
  and desktop/web UI integration in web/.
---

# FastAPI Sidecar & Web API Runbook

## Server Overview

The FastAPI sidecar (`web.api:app`) runs on `http://127.0.0.1:8765`:

| Feature | Module | Purpose |
| :--- | :--- | :--- |
| **OAuth Callbacks** | [`web/auth.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/auth.py) | Redirect auth for Zerodha, Fyers, Upstox, Groww |
| **REST APIs** | [`web/skills.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/skills.py) | Portfolio, quotes, watchlist, market breadth, analysis |
| **SSE Streaming** | [`web/sse.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/sse.py) | Live ticks, agent debate turns, trade notifications |
| **OpenClaw** | [`web/openclaw.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/openclaw.py) | Tool manifests for external AI agents |

---

## Endpoint Map

| Path | Method | Purpose |
| :--- | :--- | :--- |
| `/` | `GET` | HTML broker login dashboard |
| `/<broker>/login` | `GET` | Initiate OAuth flow |
| `/<broker>/callback` | `GET` | Receive auth code/token from broker |
| `/api/mode` | `GET` | Canonical server-authoritative mode (`DEMO`, `PAPER`, `LIVE`) |
| `/api/reconciliation` | `GET` | Live broker vs internal ledger reconciliation (`UNAVAILABLE` if disconnected) |
| `/api/status` | `GET` | Active broker session status |
| `/api/portfolio` | `GET` | Combined positions & holdings |
| `/api/stream/events` | `GET` | SSE real-time market updates & agent output |
| `/skills/chat` | `POST` | AI copilot chat endpoint |
| `/skills/analyse` | `POST` | Full multi-agent analysis |
| `/skills/high_conviction` | `POST` | Top conviction radar scan |
| `/skills/gex_snapshot` | `POST` | Options chain with GEX/DIX |
| `/skills/payoff` | `POST` | Multi-leg option payoff simulation & metrics |
| `/skills/global_macro` | `GET` / `POST` | High-Correlation 6 macro report, GIFT NIFTY gap & sector transmission |
| `/skills/thematic_baskets/list` | `GET` / `POST` | List 6 institutional super-investor thematic baskets |
| `/skills/thematic_baskets/scan` | `POST` | Scan and rank basket candidates via 3-Axis Magic Trend |
| `/skills/portfolio/doctor` | `GET` / `POST` | Full AI Health Diagnosis on connected broker portfolio |
| `/skills/prompts/proven` | `GET` / `POST` | Curated institutional super-investor prompts |
| `/skills/export-pdf` | `POST` | Export analysis report as clean PDF |
| `/skills/explain` | `POST` | Simplify quant analysis into plain language |
| `/skills/market_overview` | `GET` | Combined India VIX, FII/DII, breadth & sector RRG |
| `/skills/backtest` | `POST` | Quantitative vectorized backtest engine |
| `/skills/telemetry/summary` | `GET` | Fallback & error telemetry |

---

## Data Feed Modes

The sidecar supports two data feed modes with automatic fallback:

| Mode | Source | Indicator | Latency |
| :--- | :--- | :--- | :--- |
| **Live** | WebSocket via Fyers SDK | `🟢 Live` badge | Sub-second |
| **Polling** | REST API at 60s intervals | `🟡 Polling` badge | ~60s |

The frontend must always display the current feed mode so the user knows their data freshness. WebSocket is attempted first; if unavailable, the system degrades to REST polling automatically.

---

## Operational Best Practices

### Server Lifecycle
1. **Hot-Reload Awareness**: Background daemons cache imports. After backend changes in `analysis/`, `engine/`, or `web/`, always kill and restart the daemon.
2. **Frontend Bundle Sync**: After React component changes, verify `npm run build:web` compiles cleanly and syncs to `web/static/`.

### Data Integrity
3. **Cache Poisoning Prevention**: Never cache empty collections (`opportunities: []`). Verify `len(items) > 0` before caching; treat empty results as cache misses.
4. **Data Provenance**: Always return `data_source` (`LIVE_TICK` / `HISTORICAL_EOD`), `as_of_date`, and `dataset_timeline` in API payloads.
5. **Route Aliasing**: Register aliases (`/high_conviction` + `/top_conviction`, `/taxonomy` + `/universe_categories`) with both GET and POST.

### Frontend Integration
6. **1-Click Execution**: Interactive buttons use `sendDraft(cmd)` (`autoSubmit: true`) — never `setDraft(text)`.
7. **Modal Dismiss on Action**: All modals dispatch `close-all-modals` event when action buttons are clicked.
8. **Bi-directional Navigation**: Sticky `← 🏠 Dashboard` and `← Return to Active View` banners.
9. **Non-Blocking UI**: Backdrop dismiss (`onClick={onClose}` + `e.stopPropagation()`). No `alert()` popups.
10. **Zero-Latency Cancel**: `EventSource.close()` + `AbortController` for streaming abort.

### Resource Management
11. **Connection Hygiene**: Wrap `httpx.Client()` in `with` context managers. No dangling TCP sockets.
12. **Bounded Caches**: Cap in-memory dicts with LRU eviction and TTL checks.
13. **Options Coverage**: Generate ≥41 strikes (`range(-20, 21)`) in `/skills/gex_snapshot`.
14. **Typeahead Safety**: Dynamically calculate viewport boundaries to prevent overflow/clipping.

### CI/CD & Tiered Validation
15. **Pre-Commit Gate**: Run `.venv\Scripts\python.exe scripts/validate_all.py --fast` (< 20s) before any commit.
16. **Pre-Push Gate**: Run `.venv\Scripts\python.exe scripts/validate_all.py --full` (< 40s) for full 2,188+ test matrix.
17. **Cleanup Utility**: Run `.venv\Scripts\python.exe scripts/cleanup.py` to kill orphaned workers and free port 8765.

---

## Testing

```powershell
# Start sidecar with auto-reload
.venv\Scripts\python.exe -m uvicorn web.api:app --host 127.0.0.1 --port 8765 --reload

# Fast pre-commit validation (< 20s)
.venv\Scripts\python.exe scripts/validate_all.py --fast

# Test authentication & endpoints
.venv\Scripts\pytest.exe tests/test_api_broker.py -v

# Test SSE streaming
.venv\Scripts\pytest.exe tests/test_sse_streaming.py -v
```
