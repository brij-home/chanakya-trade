---
name: fastapi-sidecar
description: >-
  Develop, test, and maintain the FastAPI sidecar server (port 8765), SSE
  streaming endpoints, OpenClaw skill manifests, OAuth callback handlers,
  and desktop/web UI integration in web/.
---

# FastAPI Sidecar & Web API Runbook

## Server Overview

The FastAPI sidecar (`web.api:app`) acts as the local backend service on port `8765`:
- **Local Browser OAuth**: Handles redirect authentication for Zerodha, Fyers, Upstox, and Groww without exposing credentials.
- **REST APIs**: Provides portfolio, order book, watchlist, quote, and market breadth endpoints for the Desktop (Electron/macOS) and Web UIs.
- **Server-Sent Events (SSE)** ([`web/sse.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/sse.py)): Streams live market ticks, agent debate turns, and trade notifications to frontends in real time.
- **OpenClaw Integration** ([`web/openclaw.py`](file:///c:/Users/brije/.gemini/antigravity/scratch/chanakya-trade/web/openclaw.py)): Exposes tool manifests and remote execution capabilities for external AI agents.

---

## Server Endpoints

| Path | Method | Purpose |
| :--- | :--- | :--- |
| `/` | `GET` | HTML broker login dashboard |
| `/<broker>/login` | `GET` | Initiates OAuth flow for specified broker |
| `/<broker>/callback`| `GET` | Receives auth code / token from broker redirect |
| `/api/status` | `GET` | JSON status of active broker sessions |
| `/api/portfolio` | `GET` | Combined portfolio positions and holdings |
| `/api/stream/events` | `GET` | SSE stream for real-time market updates & agent output |
| `/api/skills` | `GET/POST`| Dynamic execution of registered platform skills |

---

## Running and Testing the Sidecar

```powershell
# Start FastAPI sidecar with auto-reload
.venv\Scripts\python.exe -m uvicorn web.api:app --host 127.0.0.1 --port 8765 --reload

# Test sidecar authentication and endpoints
.venv\Scripts\pytest.exe tests/test_api_broker.py -v

# Test SSE streaming functionality
.venv\Scripts\pytest.exe tests/test_sse_streaming.py -v
```

---

## Operational Best Practices

1. **Daemon Lifecycle**: Background daemons cache imports. After backend changes in `analysis/`, `engine/`, or `web/`, always kill and restart the daemon.
2. **Cache Poisoning Prevention**: Never cache empty collections (`opportunities: []`) in SQLite `analysis_cache`. Always verify `len(items) > 0` before caching and treat empty cache results as misses.
3. **Route Aliasing**: Register standard alias routes (`/high_conviction` + `/top_conviction`, `/taxonomy` + `/universe_categories`) with both `GET` and `POST` support where appropriate.
4. **Data Provenance**: Always return `data_source` (`LIVE_TICK` vs `HISTORICAL_EOD`), `as_of_date`, and `dataset_timeline` in payloads so clients understand the data basis.
5. **1-Click Direct Execution**: Interactive buttons and quick prompts must trigger `sendDraft(cmd)` (`autoSubmit: true, showDashboard: false`) to immediately run the action without requiring manual typing or pressing Enter.
6. **Modal Dismissal on Action**: All interactive modals (Top 10 Radar, Sector Drilldown, Command Palette) must close automatically (`close-all-modals` event) when an action button is clicked, seamlessly switching to the active stream view.
7. **Bi-directional Navigation**: Provide a sticky `← 🏠 Dashboard` button and a `← Return to Active View` banner to toggle effortlessly between the welcome dashboard and loaded analysis cards.
8. **Non-Blocking UI**: Modal dialogs must support backdrop dismiss (`onClick={onClose}` + `e.stopPropagation()`) and avoid blocking browser `alert()` popups.
9. **Connection Lifecycle & Socket Hygiene**: Wrap all scraper `httpx.Client()` instances in context managers (`with httpx.Client(...) as session:`) to prevent unclosed TCP connection leaks.
10. **Bounded In-Memory Caches**: Always cap in-memory dictionaries (`_chat_sessions`, `_sessions`, `_df_memory_cache`) with maximum capacity LRU evictions and TTL checks to prevent memory leaks during long-running sidecar sessions.
11. **Filtering, Sorting & Pagination Consistency**: Data cards, radar screeners, and option chains must implement client/server multi-factor filtering, multi-column sorting (`score_desc`, `gain_desc`, `symbol_asc`, `strike_asc`), and configurable pagination (e.g. 5/10/20 per page) to ensure optimal visual density and zero layout shifts.
12. **Activity & Cancellation Protocol**: Frontend streaming must support graceful client-side abort (`EventSource.close()`, activity reset) and render institutional step progress with timers via `ActivityHUD`.
13. **Full-Market Option Ladder Coverage**: Always generate wide strike ladders ($\ge 41$ strikes, `range(-20, 21)`) in `/skills/gex_snapshot` so that high-distance filters (`ATM ±10`, `ATM ±15`, `All Strikes`) provide realistic market depth across far OTM and deep ITM strikes.
14. **Typeahead Viewport Boundary Safety**: Search suggestions and quick-switch menus must dynamically calculate viewport positioning to prevent horizontal overflow or clipping against screen edges.
15. **Institutional Spacing & Ergonomics**: All desktop terminal views must follow high-density spacing standards (`p-2.5 sm:p-3.5 space-y-2.5`, `gap-2.5`, `py-1 px-2` table rows) to maximize screen real estate for charts, order flow, and option matrices.
16. **Frontend Static Asset & Root Error Boundary Synchronization**:
    - When updating React components in `macos-app/src/renderer/`, always verify the production web bundle (`npm run build:web`) compiles without errors and syncs to `web/static/`.
    - Ensure all API data parsers and metric tables implement defensive null checks (`?.toLowerCase()`, `typeof === 'object'`) to prevent DOM rendering crashes.


