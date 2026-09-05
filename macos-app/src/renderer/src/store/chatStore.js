import { create } from 'zustand'
import { getSymbolExchange } from '../data/universeData'

/** Get the API base URL — works in both Electron and web mode. */
export function getBaseUrl(port) {
  if (window.__CHANAKYA_TRADE_WEB__ && window.location.port !== '5173') return window.location.origin
  return port ? `http://127.0.0.1:${port}` : 'http://127.0.0.1:8765'
}

/** Generate a UUID-like id for sessions. */
function uuid() {
  return 'sess-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8)
}

/**
 * Derive a short title from the first user message in a session.
 */
function deriveTitle(text) {
  const parts = text.trim().split(/\s+/)
  const cmd = parts[0].toLowerCase()
  const arg = parts[1]?.toUpperCase()

  if ((cmd === 'analyze' || cmd === 'analyse' || cmd === 'a') && arg) return `${arg} Analysis`
  if (cmd === 'gex' && arg) return `${arg} GEX`
  if (cmd === 'morning-brief' || cmd === 'brief' || cmd === 'mb') return 'Morning Brief'
  if (cmd === 'iv-smile' || cmd === 'smile') return `${arg || 'NIFTY'} IV Smile`
  if (cmd === 'strategy' || cmd === 'strat') return `${arg || 'NIFTY'} Strategy`
  if (cmd === 'risk-report' || cmd === 'risk') return 'Risk Report'
  if (cmd === 'delta-hedge' || cmd === 'dh') return 'Delta Hedge'
  if (cmd === 'whatif' || cmd === 'what-if') return 'What-If'
  if (cmd === 'drift') return 'Drift'
  if (cmd === 'memory' || cmd === 'mem') return 'Memory'
  if (cmd === 'holdings' || cmd === 'h') return 'Holdings'
  if (cmd === 'positions' || cmd === 'pos') return 'Positions'
  if (cmd === 'orders') return 'Orders'
  if (cmd === 'funds') return 'Funds'
  if (cmd === 'flows') return 'FII/DII Flows'
  if (cmd === 'quote' || cmd === 'q') return `${arg || ''} Quote`
  if (cmd === 'oi') return `${arg || ''} OI`
  if (cmd === 'scan') return 'Scan'
  if (cmd === 'patterns') return 'Patterns'
  if (cmd === 'deep-analyze' || cmd === 'da') return `${arg || ''} Deep Analysis`
  if (cmd === 'backtest' || cmd === 'bt') return `${arg || ''} Backtest`

  // Fallback: first 30 chars
  return text.length > 30 ? text.slice(0, 30) + '...' : text
}

/**
 * Helper to derive the currently active stock/ticker context from session messages.
 */
export function getActiveSymbol(messages) {
  if (!messages || !Array.isArray(messages) || messages.length === 0) return null
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m?.data?.symbol) return String(m.data.symbol).toUpperCase()
    if (m?.data?.stock) return String(m.data.stock).toUpperCase()
    if (m?.role === 'user' && typeof m.text === 'string') {
      const match = m.text.match(
        /(?:analyze|analyse|quote|q|forensic|fa|smc|structure|multibagger|vcp|lifecycle|trail|oi|payoff|backtest|bt|deals|size|da|deep-analyze|iv-smile|gex)\s+([A-Za-z0-9_&]+)/i
      )
      if (match && match[1]) {
        const sym = match[1].toUpperCase()
        if (!['NIFTY_50', 'NIFTY50', 'FNO', 'ALL', 'THEMATIC', 'INDEX'].includes(sym)) {
          return sym
        }
      }
    }
  }
  return null
}

// Create the default initial session
const defaultId = uuid()

/**
 * Build an O(1) Map<id, arrayIndex> from the messages array.
 * Rebuilt on mutations that add/remove messages (not per SSE update).
 * @param {Array} msgs
 * @returns {Map<number|string, number>}
 */
function _buildMsgIndex(msgs) {
  const m = new Map()
  for (let i = 0; i < msgs.length; i++) m.set(msgs[i].id, i)
  return m
}

const initialPort = (() => {
  try {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('chanakya_sidecar_port')
      if (saved) return parseInt(saved, 10)
      if (window.location?.port && window.location.port !== '5173') {
        return parseInt(window.location.port, 10) || 8765
      }
    }
  } catch (_) {}
  return 8765
})()

export const useChatStore = create((set, get) => ({
  // ── Multi-session state ───────────────────────────────────
  sessions: {
    [defaultId]: { id: defaultId, title: 'New Session', messages: [], createdAt: Date.now() },
  },
  activeSessionId: defaultId,

  // ── High-Fidelity Workspace Views ('terminal' | 'debate' | 'options' | 'copilot') ──
  activeView: (typeof window !== 'undefined' && localStorage.getItem('chanakya_active_view')) || 'terminal',
  setActiveView: (view) => {
    try { localStorage.setItem('chanakya_active_view', view) } catch (_) {}
    set({ activeView: view })
  },

  // ── Global In-Flight Activity & Progress HUD State ─────────
  activeActivity: null, // { id, title, details, progress, type, targetView, cancelFn, startedAt }
  completedNotification: null, // { id, title, message, targetView, actionLabel, timestamp }

  startActivity: (activity) => {
    set({
      activeActivity: {
        id: 'act-' + Date.now(),
        title: activity.title || 'Processing Market Intelligence...',
        details: activity.details || 'Computing institutional models...',
        type: activity.type || 'quant',
        targetView: activity.targetView || 'copilot',
        progress: activity.progress || null,
        cancelFn: activity.cancelFn || null,
        startedAt: Date.now(),
      },
    })
  },
  updateActivity: (updates) => {
    set((s) => {
      if (!s.activeActivity) return {}
      return { activeActivity: { ...s.activeActivity, ...updates } }
    })
  },
  stopActivity: () => set({ activeActivity: null }),
  cancelActiveActivity: () => {
    const { activeActivity, streamCancel } = get()
    if (activeActivity?.cancelFn) {
      try {
        activeActivity.cancelFn()
      } catch (e) {
        console.error('Cancel fn error', e)
      }
    }
    if (streamCancel) {
      try {
        streamCancel()
      } catch (e) {
        console.error('Stream cancel error', e)
      }
    }
    set({ activeActivity: null, streamCancel: null, isLoading: false })
  },

  notifyCompletedActivity: (notif) => {
    const id = 'notif-' + Date.now()
    set({
      completedNotification: {
        id,
        title: notif.title || 'AI Intelligence Ready',
        message: notif.message || 'Background analysis completed.',
        targetView: notif.targetView || 'copilot',
        actionLabel: notif.actionLabel || 'View Analysis →',
        timestamp: Date.now(),
      },
    })
    setTimeout(() => {
      const current = get().completedNotification
      if (current && current.id === id) {
        set({ completedNotification: null })
      }
    }, 8500)
  },
  dismissNotification: () => set({ completedNotification: null }),

  // ── Backward-compatible flat messages (swapped on session switch) ──
  messages:      [],
  // ── O(1) message index: Map<id, index> kept in sync with messages array ──
  // Eliminates O(N) scan in updateStreamingMessage (called per SSE chunk).
  _msgIndex:     new Map(),
  isLoading:     false,
  port:          initialPort,
  sidecarError:  null,
  brokerStatus:   { connected: false, broker: null },
  brokerStatuses: {},   // full /api/status response
  streamCancel:  null,   // () => void — closes the active EventSource
  activeStreamId: null,  // stream_id from SSE started event (#113)

  // ── Server-authoritative application mode (P0-A) ──────────
  // PAPER: real data, simulated execution (default for new installs)
  // DEMO:  synthetic fixtures, isolated from paper/live stores
  // LIVE:  real data + real execution (requires explicit activation)
  appMode:     'PAPER',   // 'PAPER' | 'DEMO' | 'LIVE'
  modeLoading: false,     // true while fetching mode from /api/mode

  setPort:         (port)   => {
    try { if (port) localStorage.setItem('chanakya_sidecar_port', String(port)) } catch (_) {}
    set({ port, sidecarError: null })
  },
  setSidecarError: (msg)    => set({ sidecarError: msg }),
  setBrokerStatus:   (status)   => set({ brokerStatus: status }),
  setBrokerStatuses: (statuses) => {
    // also derive the simple brokerStatus from the full response
    const connected = Object.values(statuses).some(b => b.authenticated)
    const broker    = Object.entries(statuses).find(([, b]) => b.authenticated)?.[0] ?? null
    const name      = broker ? ({ zerodha: 'Zerodha', groww: 'Groww', angel_one: 'Angel One', upstox: 'Upstox', fyers: 'Fyers' }[broker] ?? broker) : null
    set({ brokerStatuses: statuses, brokerStatus: { connected, broker: name } })
  },

  // Set server-authoritative app mode (PAPER / DEMO / LIVE)
  setAppMode: (mode) => set({ appMode: mode, modeLoading: false }),
  setModeLoading: (loading) => set({ modeLoading: loading }),

  // ── Session management ────────────────────────────────────

  createSession: () => {
    const { sessions, activeSessionId, messages } = get()
    // Save current session messages
    const updated = { ...sessions }
    if (activeSessionId && updated[activeSessionId]) {
      updated[activeSessionId] = { ...updated[activeSessionId], messages }
    }
    const id = uuid()
    updated[id] = { id, title: 'New Session', messages: [], createdAt: Date.now() }
    set({ sessions: updated, activeSessionId: id, messages: [], _msgIndex: new Map(), isLoading: false })
  },

  switchSession: (id) => {
    const { sessions, activeSessionId, messages } = get()
    if (id === activeSessionId) return
    // Save current session messages
    const updated = { ...sessions }
    if (activeSessionId && updated[activeSessionId]) {
      updated[activeSessionId] = { ...updated[activeSessionId], messages }
    }
    const target = updated[id]
    if (!target) return
    set({ sessions: updated, activeSessionId: id, messages: target.messages, _msgIndex: _buildMsgIndex(target.messages), isLoading: false })
  },

  deleteSession: (id) => {
    const { sessions, activeSessionId, messages } = get()
    const updated = { ...sessions }
    delete updated[id]
    const remaining = Object.keys(updated)
    if (remaining.length === 0) {
      // Create a fresh default session
      const newId = uuid()
      updated[newId] = { id: newId, title: 'New Session', messages: [], createdAt: Date.now() }
      set({ sessions: updated, activeSessionId: newId, messages: [] })
      return
    }
    if (id === activeSessionId) {
      const nextId = remaining[0]
      set({ sessions: updated, activeSessionId: nextId, messages: updated[nextId].messages })
    } else {
      // Save current messages before updating sessions
      if (activeSessionId && updated[activeSessionId]) {
        updated[activeSessionId] = { ...updated[activeSessionId], messages }
      }
      set({ sessions: updated })
    }
  },

  renameSession: (id, title) => {
    const { sessions } = get()
    if (!sessions[id]) return
    set({ sessions: { ...sessions, [id]: { ...sessions[id], title } } })
  },

  // ── Message actions (operate on active session) ───────────

  addUserMessage: (text) => set((s) => {
    const newMessages = [...s.messages, {
      id: Date.now(), role: 'user', text,
    }]
    // Auto-title: if this is the first user message in the session
    const session = s.sessions[s.activeSessionId]
    let sessions = s.sessions
    if (session && session.title === 'New Session') {
      sessions = {
        ...s.sessions,
        [s.activeSessionId]: { ...session, title: deriveTitle(text), messages: newMessages },
      }
    } else if (session) {
      sessions = {
        ...s.sessions,
        [s.activeSessionId]: { ...session, messages: newMessages },
      }
    }
    return { messages: newMessages, _msgIndex: _buildMsgIndex(newMessages), isLoading: true, sessions }
  }),

  addResponse: (card) => set((s) => {
    const newMessages = [...s.messages, { id: Date.now() + 1, role: 'assistant', ...card }]
    const session = s.sessions[s.activeSessionId]
    let sessions = s.sessions
    if (session) {
      sessions = { ...s.sessions, [s.activeSessionId]: { ...session, messages: newMessages } }
    }
    return { messages: newMessages, _msgIndex: _buildMsgIndex(newMessages), isLoading: false, sessions }
  }),

  addError: (text) => set((s) => {
    const newMessages = [...s.messages, { id: Date.now() + 1, role: 'error', text }]
    const session = s.sessions[s.activeSessionId]
    let sessions = s.sessions
    if (session) {
      sessions = { ...s.sessions, [s.activeSessionId]: { ...session, messages: newMessages } }
    }
    return { messages: newMessages, _msgIndex: _buildMsgIndex(newMessages), isLoading: false, sessions }
  }),

  setLoading: (v) => set({ isLoading: v }),

  setStreamCancel: (fn) => set({ streamCancel: fn }),
  setActiveStreamId: (id) => set({ activeStreamId: id }),

  cancelStream: () => {
    const { streamCancel } = get()
    if (streamCancel) { streamCancel(); set({ streamCancel: null, isLoading: false }) }
  },

  // Streaming support — used by analyze SSE
  startStreamingMessage: (id, symbol, exchange) => set((s) => {
    const sym = symbol ? String(symbol).toUpperCase().trim() : symbol
    const resolvedExch = (!exchange || exchange === 'NSE') ? getSymbolExchange(sym) : exchange
    const newMessages = [...s.messages, {
      id,
      role: 'assistant',
      cardType: 'streaming_analysis',
      data: { symbol: sym, exchange: resolvedExch, analysts: [], debate_steps: [], synthesis_text: null, phase: 'analysts', report: null, trade_plans: null },
    }]
    const session = s.sessions[s.activeSessionId]
    let sessions = s.sessions
    if (session) {
      sessions = { ...s.sessions, [s.activeSessionId]: { ...session, messages: newMessages } }
    }
    return { messages: newMessages, _msgIndex: _buildMsgIndex(newMessages), isLoading: true, sessions }
  }),

  // ── O(1) streaming update — replaces O(N) messages.map ────────────────────
  // Called per SSE chunk (up to 200× per analysis). Critical hot path.
  updateStreamingMessage: (id, updater) => set((s) => {
    const idx = s._msgIndex.get(id)
    if (idx === undefined) return {} // message not found — no-op
    const msg = s.messages[idx]
    if (!msg) return {}
    // Splice the single updated message — no full array scan
    const newMessages = [
      ...s.messages.slice(0, idx),
      { ...msg, data: updater(msg.data) },
      ...s.messages.slice(idx + 1),
    ]
    const session = s.sessions[s.activeSessionId]
    let sessions = s.sessions
    if (session) {
      sessions = { ...s.sessions, [s.activeSessionId]: { ...session, messages: newMessages } }
    }
    // Index doesn't change since we only mutated in-place at same index
    return { messages: newMessages, sessions }
  }),

  finalizeStreamingMessage: (_id) => set({ isLoading: false, activeStreamId: null }),

  // Navigation & View Mode
  showDashboard: false,
  setShowDashboard: (val) => set({ showDashboard: val }),

  // Draft message — lets cards pre-fill or auto-execute in the input bar
  draft: '',
  autoSubmit: false,
  setDraft: (text) => set({ draft: text, autoSubmit: false }),
  sendDraft: (text) => set({ draft: text, autoSubmit: true, showDashboard: false, activeView: 'copilot' }),
  clearAutoSubmit: () => set({ autoSubmit: false }),

  // Context queued while a streaming analysis is running (#102)
  // Shown as a user bubble and auto-injected into the first follow-up
  pendingContext: '',
  setPendingContext: (text) => set({ pendingContext: text }),
  clearPendingContext: () => set({ pendingContext: '' }),
})
)
