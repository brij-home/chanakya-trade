---
name: frontend-development
description: >-
  React/Electron frontend development guide for ChanakyaTrade macos-app/.
  Covers component architecture, Bloomberg color tokens, SSE event handling,
  sendDraft execution pattern, state management (Zustand), and build pipeline.
---

# Frontend Development Runbook (macos-app/)

> All React/Electron UI work lives in `macos-app/src/renderer/src/`.
> Run the build pipeline AFTER every component change: `npm run build:web`

<!-- TOC -->
- [1. Project Structure](#1-project-structure)
- [2. Component Architecture](#2-component-architecture)
- [3. State Management (Zustand)](#3-state-management-zustand)
- [4. Bloomberg Color Token System](#4-bloomberg-color-token-system)
- [5. sendDraft vs setDraft Pattern](#5-senddraft-vs-setdraft-pattern)
- [6. SSE Event Handling](#6-sse-event-handling)
- [7. Build Pipeline](#7-build-pipeline)
- [8. Institutional Design Standards](#8-institutional-design-standards)
- [9. Testing](#9-testing)
<!-- /TOC -->

---

## 1. Project Structure

```
macos-app/
  src/
    main/          # Electron main process (IPC handlers, window management)
    preload/       # Electron preload scripts (contextBridge APIs)
    renderer/
      src/
        App.jsx              # Root: routing, lazy-loaded views, SSE init
        main.jsx             # Electron/Browser entry point
        index.css            # Design system: CSS variables, utilities (~52KB)
        store/               # Zustand stores
          chatStore.js       # Chat sessions, base URL, API helpers
          notificationStore.js # Alert notifications
          inspectorStore.js  # Inspector panel state
        hooks/               # Custom React hooks
        components/
          Cards/             # Data display cards (quote, metric, position)
          Charts/            # TradingView / Canvas chart wrappers
          Chat/              # Chat area, message bubbles, streaming
          Common/            # Shared: ModeBanner, LiveTickerRibbon, ActivityHUD
          Input/             # InputBar, command draft handling
          Modals/            # OrderTicketModal, CommandPalette, etc.
          Notifications/     # NotificationBell, detail modal
          Onboarding/        # OnboardingWizard
          Shell/             # ActivityBar, ContextBar, sidebar frame
          Sidebar/           # Navigation sidebar + SettingsPanel
          Toast/             # Toast notifications
          UI/                # HotkeyPanel, generic UI primitives
          Views/             # Full workspace views (one per activity bar icon)
```

---

## 2. Component Architecture

### Views (full workspace panels)
Each view = one activity bar icon. Views are **lazy-loaded** in `App.jsx`:
```jsx
const AlertsView = lazy(() => import('./components/Views/AlertsView'))
const TerminalView = lazy(() => import('./components/Views/TerminalView'))
```

**Directory**: `components/Views/`

**Rules**:
- Max ~400 lines per view file — split into sub-components in the same `Views/alerts/` sub-dir if larger
- Views own their own local state + may subscribe to Zustand stores
- Views communicate with backend via the API functions in `chatStore.js`

### Cards (data display)
Compact, reusable data cards. Directory: `components/Cards/`
- Props: `title`, `value`, `change`, `color`, `badge`
- Use CSS variables for color — never hardcode hex in JSX

### Modals
Directory: `components/Modals/`. All modals MUST:
- Accept `onClose` prop, call `onClose()` on backdrop click and escape key
- Dispatch `close-all-modals` custom event when action buttons execute trades
- Never use `window.alert()` or `window.confirm()` — use Toast or in-modal confirmation

---

## 3. State Management (Zustand)

### Available Stores

| Store | File | Purpose |
|-------|------|---------|
| `useChatStore` | `store/chatStore.js` | Chat history, session, base URL, API helpers |
| `useNotificationStore` | `store/notificationStore.js` | Alert notifications, bell badge |
| `useInspectorStore` | `store/inspectorStore.js` | Inspector panel state |
| `useToastStore` | `hooks/useToast.js` | Toast notifications |

### Adding State for a New Feature
1. Add to the appropriate existing store OR create `store/featureNameStore.js`
2. Use Zustand's `create()` with `immer` middleware for complex nested state
3. For AlertsView sub-components, use the `useNotificationStore` for shared alert state + local `useState` for UI-only state (filters, selected item, etc.)

### API Helper
Use `getBaseUrl()` from `chatStore.js` for all backend API calls — never hardcode `http://127.0.0.1:8765`:
```js
import { getBaseUrl } from '../store/chatStore'
const resp = await fetch(`${getBaseUrl()}/skills/quote`, { method: 'POST', ... })
```

---

## 4. Bloomberg Color Token System

**All colors defined as CSS variables in `index.css`. Use variables, never raw hex in components.**

| Variable | Hex | Usage |
|----------|-----|-------|
| `var(--color-profit)` / `var(--color-emerald)` | `#10B981` | Profit, Bullish, Live feeds, T1/T2 targets |
| `var(--color-loss)` / `var(--color-rose)` | `#F43F5E` | Stop-loss, Bearish, Invalidation, Errors |
| `var(--color-gold)` | `#F59E0B` | High conviction, Alerts, Asymmetric setups |
| `var(--color-indigo)` | `#6366F1` | F&O, Greeks, Open Interest |
| `var(--color-sky)` | `#0EA5E9` | Indices, Macro, Sector RRG |
| `var(--color-surface)` | dark bg | Card backgrounds |
| `var(--color-border)` | subtle | Card/table borders |
| `var(--color-muted)` | dim text | Secondary labels, timestamps |

```jsx
// Correct
<span style={{ color: 'var(--color-profit)' }}>+2.3%</span>

// Wrong
<span style={{ color: '#10B981' }}>+2.3%</span>
```

### Status Badges
```jsx
// Standard badge pattern
<span className="px-1.5 py-0.5 rounded text-xs font-mono font-semibold"
      style={{ background: 'rgba(16,185,129,0.15)', color: 'var(--color-profit)' }}>
  LIVE
</span>
```

---

## 5. sendDraft vs setDraft Pattern

**Critical**: Use the right pattern or trades will not execute.

### `sendDraft(cmd, opts)` — for 1-click execution
Immediately submits the command as if the user typed and pressed Enter.
Used on ALL action buttons that should execute trades or run analysis.

```jsx
import { useChatStore } from '../../store/chatStore'
const { sendDraft } = useChatStore()

// 1-click analysis button
<button onClick={() => sendDraft(`analyse ${symbol}`, { autoSubmit: true })}>
  Analyse
</button>
```

### `setDraft(text)` — for pre-population only
Only populates the input bar without sending. Use ONLY for "fill in" helpers where the user should review before submitting.

```jsx
const { setDraft } = useChatStore()

// Let user edit before sending
<button onClick={() => setDraft(`buy ${symbol} 100 at market`)}>
  Draft Order
</button>
```

**Rule**: Action buttons that dispatch orders or ticket drafts MUST use `sendDraft` with `autoSubmit: true`. Never leave the user with a half-filled input that requires an extra Enter press for execution-critical flows.

---

## 6. SSE Event Handling

Pattern for subscribing to SSE streams from the backend (`/api/stream/events`):

```jsx
import { useSSEStream } from '../../hooks/useSSEStream'

// In component:
const { events, isConnected, error } = useSSEStream()

// Or manual EventSource for component-specific streams:
useEffect(() => {
  const abortController = new AbortController()
  const source = new EventSource(`${getBaseUrl()}/skills/some-stream`)

  source.onmessage = (e) => {
    const data = JSON.parse(e.data)
    // handle data
  }

  source.onerror = () => {
    source.close()  // Always close on error
  }

  return () => {
    source.close()           // Cleanup on unmount
    abortController.abort()  // Cancel any pending fetches
  }
}, [])
```

### SSE Event Types to Handle
| `type` | Meaning |
|--------|---------|
| `alert` | New market alert (show in notification bell) |
| `trade_notification` | Order fill/cancel event |
| `debate_step` | Multi-agent debate progress |
| `feed_state` | Data feed status change (LIVE/DEGRADED/UNAVAILABLE) |
| `ticker_update` | Live ticker ribbon update |

### Feed State Display
Always display current feed state — never hide connectivity issues:
```jsx
// LIVE: green dot
// DEGRADED: amber dot + tooltip with reason
// UNAVAILABLE: red dot + retry button
```

---

## 7. Build Pipeline

### Development (Electron hot-reload)
```powershell
cd macos-app
npm run dev
```

### Production build (sync to FastAPI static server)
```powershell
cd macos-app
npm run build:web           # Builds renderer to macos-app/renderer/dist/
# Sync to FastAPI static directory:
npm run sync:static         # Copies dist/ -> web/static/
# Or manually:
Copy-Item -Recurse -Force "macos-app\renderer\dist\*" "web\static\"
```

### After backend changes that affect UI
1. Kill and restart uvicorn (background daemon caches imports)
2. Rebuild frontend if any API response shape changed
3. Verify routes still exist via `GET http://127.0.0.1:8765/openapi.json`

### Linting & formatting
```powershell
cd macos-app
npx biome check --write src/    # Biome handles both lint + format
```

---

## 8. Institutional Design Standards

### Typography
- Body text: `Inter` (Google Font, loaded in index.css)
- Numbers/tables: monospace (`font-mono` Tailwind class)
- Terminal output: `JetBrains Mono` or `Fira Code`

### Density (Bloomberg Standard)
- Table cells: `py-1 px-2` (not `p-4`)
- Card padding: `p-2.5` (not `p-6`)
- Gap between elements: `gap-2` (not `gap-6`)
- Font size for data: `text-xs` or `text-[11px]`

### Micro-Animations (Required)
```css
/* Standard hover transition */
transition: transform 0.15s ease, opacity 0.2s;

/* Glassmorphism overlay */
backdrop-filter: blur(12px);
background: rgba(0, 0, 0, 0.45);
```

### Non-Negotiable Rules
- No `window.alert()` or `window.confirm()` — use Toast or modal confirmation
- All modals must close on backdrop click (`onClick={onClose}`) + `e.stopPropagation()`
- No unhandled Promise rejections — always add `.catch()` or `try/catch`
- No broken, blank, or placeholder cards — every card must show UNAVAILABLE state gracefully
- 1-click execution: action buttons dispatch immediately via `sendDraft` with `autoSubmit: true`

---

## 9. Testing

```powershell
# Run frontend unit tests (Vitest)
cd macos-app
npx vitest run

# Check for TypeScript/JSX errors
npx biome check src/

# Verify backend API routes after skill split
curl http://127.0.0.1:8765/openapi.json | python -m json.tool | findstr "/skills/"
```
