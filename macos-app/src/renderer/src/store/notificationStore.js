import { create } from 'zustand'
import { isTestOrSimAlert, isAlertActive } from '../components/Views/alerts/alertHelpers'

const STORAGE_KEY = 'chanakya_notifications_v1'
// Singleton polling interval — only ONE interval runs across the entire app
let _pollTimer = null
const MAX_NOTIFICATIONS = 300

// Safe localStorage loader with prior-day intraday expiration sanitization and test alert pruning
function loadStoredNotifications() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // Sanitize any legacy test/sim alerts right upon initial load!
    const sanitized = parsed.filter((item) => !isTestOrSimAlert(item))
    if (sanitized.length !== parsed.length) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitized.slice(0, MAX_NOTIFICATIONS)))
      } catch (_) {}
    }
    const now = new Date()
    return sanitized.map((item) => {
      const isIntraday = item.time_horizon === 'INTRADAY' || item.timeHorizon === 'INTRADAY'
      const isSwingOrPositional = ['SWING_SHORT', 'SWING_MID', 'POSITIONAL', 'LONG_TERM', 'MULTIBAGGER'].includes(item.time_horizon || item.timeHorizon)
      const isGammaOrZeroDte = (item.alert_type || '').includes('GAMMA') || (item.alert_type || '').includes('0DTE')
      const exch = String(item.exchange || '').toUpperCase()
      const seg = String(item.segment || item.metrics?.segment || '').toUpperCase()
      const isCrypto = exch === 'CRYPTO' || exch === 'BINANCE' || exch === 'DERIBIT' || seg === 'CRYPTO' || String(item.symbol || '').toUpperCase().endsWith('USDT')
      const timeStr = item.created_at || item.timestamp

      if (timeStr) {
        try {
          const d = new Date(String(timeStr).replace(' IST', '').trim())
          if (!isNaN(d.getTime())) {
            const ageDays = (now.getTime() - d.getTime()) / 86_400_000
            if (isCrypto) {
              if (ageDays >= 1) {
                return {
                  ...item,
                  is_invalidated: true,
                  isInvalidated: true,
                  is_active: false,
                  stage: 'EXPIRED',
                  invalidation_reason: item.invalidation_reason || '24x7 Crypto session expired (24h rolling limit reached). Trade closed.'
                }
              }
            } else if ((isIntraday || isGammaOrZeroDte) && d.toDateString() !== now.toDateString()) {
              return {
                ...item,
                is_invalidated: true,
                isInvalidated: true,
                is_active: false,
                stage: 'EXPIRED',
                invalidation_reason: item.invalidation_reason || 'Session expired (market cutoff reached). Trade closed.'
              }
            } else if (ageDays > 5) {
              return {
                ...item,
                is_invalidated: true,
                isInvalidated: true,
                is_active: false,
                stage: 'EXPIRED',
                invalidation_reason: item.invalidation_reason || 'Signal window exceeded (5-day limit). Trade closed.'
              }
            }
          }
        } catch (_) {}
      }

      if (item.expiry_date) {
        try {
          const exp = new Date(item.expiry_date)
          if (!isNaN(exp.getTime())) {
            const today = new Date()
            today.setHours(0, 0, 0, 0)
            if (exp < today) {
              return {
                ...item,
                is_invalidated: true,
                isInvalidated: true,
                is_active: false,
                stage: 'EXPIRED',
                invalidation_reason: item.invalidation_reason || `Contract expired (${item.expiry_date}).`
              }
            }
          }
        } catch (_) {}
      }

      return item
    })
  } catch (_) {
    return []
  }
}

// Safe localStorage saver
function saveNotifications(items) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_NOTIFICATIONS)))
  } catch (_) {}
}

/**
 * Normalizes alert payloads into a consistent, institutional notification structure.
 */
export function normalizeNotification(payload) {
  if (!payload) return null
  const now = new Date()
  const id = payload.id || payload.alert_id || `notif_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`

  const cleanSym = String(payload.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const isTest = payload.environment === 'TEST' || payload.is_live === false
  const isInvalidated = payload.is_invalidated === true || payload.stage === 'INVALIDATED'
  const isTarget = payload.is_target === true || payload.stage === 'T1_ACHIEVED' || payload.stage === 'TARGET_ACHIEVED' || payload.target_achieved === true
  const isTrail = payload.is_trail === true || payload.stage === 'TRAILING_UPDATE'

  const plan = payload.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const optType = payload.option_type || (payload.contract_symbol?.endsWith('PE') ? 'PE' : payload.contract_symbol?.endsWith('CE') ? 'CE' : null)
  const strikeNum = payload.strike ? Number(String(payload.strike).replace(/[^0-9.-]/g, '')) : null
  const spotNum = payload.underlying_spot ? Number(payload.underlying_spot) : null
  const isOption = Boolean(optType || payload.contract_symbol?.endsWith('PE') || payload.contract_symbol?.endsWith('CE') || payload.derivative_type === 'OPTIONS')
  const rawLtp = payload.ltp ? Number(String(payload.ltp).replace(/[^0-9.-]/g, '')) : null
  const isSpotLeak = isOption && rawLtp != null && (rawLtp > 5000 || (spotNum && Math.abs(rawLtp - spotNum) < 10))
  const premiumNum = payload.option_premium ? Number(payload.option_premium) : (isSpotLeak ? null : rawLtp)
  const ltpNum = isSpotLeak ? null : rawLtp

  const slNum = optPlan?.sl_premium ? Number(optPlan.sl_premium) : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (payload.stop_loss ? Number(payload.stop_loss) : (payload.sl ? Number(payload.sl) : null)))
  const entryNum = optPlan?.entry_premium ? Number(optPlan.entry_premium) : (tradePlan.entry_price ? Number(tradePlan.entry_price) : (payload.trigger_level ? Number(payload.trigger_level) : (payload.entry ? Number(payload.entry) : (premiumNum || ltpNum))))
  const t1Num = optPlan?.t1_premium ? Number(optPlan.t1_premium) : (tradePlan.target_1 ? Number(tradePlan.target_1) : (payload.target_level ? Number(payload.target_level) : (payload.t1 ? Number(payload.t1) : null)))
  const t2Num = optPlan?.t2_premium ? Number(optPlan.t2_premium) : (tradePlan.target_2 ? Number(tradePlan.target_2) : (payload.t2 ? Number(payload.t2) : null))
  const t3Num = optPlan?.t3_premium ? Number(optPlan.t3_premium) : (tradePlan.target_3 ? Number(tradePlan.target_3) : (payload.t3 ? Number(payload.t3) : null))

  const rawTime = payload.created_at || payload.timestamp || payload.triggered_at || now.toISOString()
  const isIntradayType = Boolean(
    payload.alert_type &&
    (payload.alert_type.toUpperCase().includes('INTRADAY') ||
     payload.alert_type.toUpperCase().includes('GAMMA') ||
     payload.alert_type.toUpperCase().includes('OPTIONS_MOMENTUM') ||
     payload.alert_type.toUpperCase().includes('SCALP') ||
     payload.alert_type.toUpperCase().includes('ORB'))
  )
  const timeHorizon =
    payload.time_horizon ||
    payload.timeHorizon ||
    (isIntradayType ? 'INTRADAY' : (tradePlan?.timeframe?.toUpperCase().includes('SWING') ? 'SWING_MID' : 'INTRADAY'))

  return {
    id,
    alert_id: id,
    symbol: cleanSym || 'UNKNOWN',
    contract_symbol: payload.contract_symbol || null,
    exchange: payload.exchange || 'NSE',
    segment: payload.segment || null,
    strike: strikeNum,
    option_type: optType,
    direction: payload.direction || (payload.headline?.includes('BULL') ? 'BULLISH' : 'BEARISH'),
    alert_type: payload.alert_type || 'ALERT',
    stage: payload.stage || (isInvalidated ? 'INVALIDATED' : isTarget ? 'TARGET_ACHIEVED' : isTrail ? 'TRAILING_UPDATE' : 'ACTIVE'),
    time_horizon: timeHorizon,
    timeHorizon: timeHorizon,
    is_active: payload.is_active !== undefined ? Boolean(payload.is_active) : isAlertActive(payload),
    is_archived: Boolean(payload.is_archived || payload.isArchived),
    is_expired: Boolean(payload.is_expired || payload.isExpired),
    is_invalidated: isInvalidated,
    invalidation_reason: payload.invalidation_reason || null,
    invalidated_at: payload.invalidated_at || null,
    archived_at: payload.archived_at || null,
    archive_reason: payload.archive_reason || null,
    target_status: payload.target_status || 'PENDING',
    achieved_milestones: payload.achieved_milestones || [],
    is_target: isTarget,
    is_trail: isTrail,
    is_test: isTest,
    spot: spotNum,
    premium: premiumNum,
    ltp: ltpNum,
    entry: entryNum,
    sl: slNum,
    t1: t1Num,
    t2: t2Num,
    t3: t3Num,
    confidence: Number(payload.confidence || payload.metrics?.scrutiny?.score || 75),
    headline: payload.headline || `${cleanSym} ${payload.alert_type || 'Signal'}`,
    summary: payload.invalidation_reason || payload.trailing_rationale || payload.summary || payload.message || payload.description || '',
    lot_size: payload.lot_size || payload.metrics?.lot_size || null,
    expiry_date: payload.expiry_date || null,
    metrics: payload.metrics || {},
    actionable_plan: plan,
    rawPayload: payload,
    created_at: payload.created_at || rawTime,
    timestamp: rawTime,
    read: false,
  }
}

const initialNotifications = loadStoredNotifications()

export const useNotificationStore = create((set, get) => ({
  notifications: initialNotifications,
  unreadCount: initialNotifications.filter((n) => !n.read).length,
  isDropdownOpen: false,
  selectedNotification: null,

  isLoading: false,
  lastSyncedAt: null,
  setIsLoading: (isLoading) => set({ isLoading }),

  setDropdownOpen: (isOpen) => set({ isDropdownOpen: isOpen }),
  toggleDropdown: () => set((s) => ({ isDropdownOpen: !s.isDropdownOpen })),

  setSelectedNotification: (notif) => set({ selectedNotification: notif }),

  syncRecentAlerts: (rawList) => {
    if (!Array.isArray(rawList)) return
    const normalized = rawList
      .map((item) => normalizeNotification(item))
      .filter(Boolean)
      .filter((item) => !isTestOrSimAlert(item))

    set((s) => {
      const existingMap = new Map(s.notifications.map((n) => [n.id, n]))
      const merged = []

      for (const item of normalized) {
        if (existingMap.has(item.id)) {
          // Preserve local read state and user modifications
          const existing = existingMap.get(item.id)
          merged.push({ ...item, read: existing.read })
          existingMap.delete(item.id)
        } else {
          merged.push(item)
        }
      }

      // Preserve only recently received in-flight SSE alerts (< 90s) not yet captured in backend snapshot
      const now = new Date()
      for (const rem of existingMap.values()) {
        const timeStr = rem.created_at || rem.timestamp
        if (timeStr) {
          try {
            const d = new Date(String(timeStr).replace(' IST', '').trim())
            if (!isNaN(d.getTime()) && (now.getTime() - d.getTime()) < 90_000) {
              merged.push(rem)
            }
          } catch (_) {}
        }
      }

      // Sort newest-first based on timestamp / created_at
      merged.sort((a, b) => {
        const timeA = new Date(String(a.timestamp || a.created_at || '').replace(' IST', '')).getTime() || 0
        const timeB = new Date(String(b.timestamp || b.created_at || '').replace(' IST', '')).getTime() || 0
        return timeB - timeA
      })

      const next = merged.slice(0, MAX_NOTIFICATIONS)
      saveNotifications(next)
      return {
        notifications: next,
        unreadCount: next.filter((n) => !n.read).length,
        lastSyncedAt: new Date().toISOString(),
        isLoading: false,
      }
    })
  },

  updateAlertArchived: (alertId, isArchived) => {
    if (!alertId) return
    set((s) => {
      const next = s.notifications.map((n) =>
        (n.id === alertId || n.alert_id === alertId)
          ? {
              ...n,
              is_archived: isArchived,
              isArchived: isArchived,
              is_active: !isArchived && isAlertActive({ ...n, is_archived: false, isArchived: false }),
            }
          : n
      )
      saveNotifications(next)
      return { notifications: next }
    })
  },

  archiveAllInvalidated: () => {
    set((s) => {
      const next = s.notifications.map((n) =>
        (n.is_invalidated || n.stage === 'INVALIDATED')
          ? {
              ...n,
              is_archived: true,
              isArchived: true,
              is_active: false,
            }
          : n
      )
      saveNotifications(next)
      return { notifications: next }
    })
  },

  addNotification: (rawPayload) => {
    const item = normalizeNotification(rawPayload)
    if (!item) return

    set((s) => {
      // Avoid duplicate alert by ID or exact same contract + timestamp
      const existingIdx = s.notifications.findIndex((n) => n.id === item.id)
      let next
      if (existingIdx >= 0) {
        next = [...s.notifications]
        next[existingIdx] = { ...next[existingIdx], ...item, read: false }
      } else {
        next = [item, ...s.notifications].slice(0, MAX_NOTIFICATIONS)
      }
      saveNotifications(next)
      return {
        notifications: next,
        unreadCount: next.filter((n) => !n.read).length,
      }
    })
  },

  markAsRead: (id) => {
    set((s) => {
      const next = s.notifications.map((n) => (n.id === id ? { ...n, read: true } : n))
      saveNotifications(next)
      return {
        notifications: next,
        unreadCount: next.filter((n) => !n.read).length,
      }
    })
  },

  markAllAsRead: () => {
    set((s) => {
      const next = s.notifications.map((n) => ({ ...n, read: true }))
      saveNotifications(next)
      return {
        notifications: next,
        unreadCount: 0,
      }
    })
  },

  removeNotification: (id) => {
    set((s) => {
      const next = s.notifications.filter((n) => n.id !== id)
      saveNotifications(next)
      return {
        notifications: next,
        unreadCount: next.filter((n) => !n.read).length,
        selectedNotification: s.selectedNotification?.id === id ? null : s.selectedNotification,
      }
    })
  },

  clearAll: () => {
    saveNotifications([])
    set({
      notifications: [],
      unreadCount: 0,
      selectedNotification: null,
    })
  },

  purgeTestAlerts: () => {
    set((s) => {
      const next = s.notifications.filter((n) => !isTestOrSimAlert(n))
      saveNotifications(next)
      return {
        notifications: next,
        unreadCount: next.filter((n) => !n.read).length,
      }
    })
  },

  /**
   * Fetches alerts from the backend using the provided `call` function and
   * merges them into the store. Safe to call concurrently — uses a guard flag.
   */
  fetchAlerts: async (call) => {
    if (!call) return
    const state = useNotificationStore.getState()
    if (state.isLoading) return // skip if a fetch is already in-flight
    set({ isLoading: true })
    try {
      let list = []
      try {
        const res = await call('/skills/alerts/auto/list', { view_mode: 'ALL', limit: 300 })
        list = res?.data ?? res ?? []
      } catch (_callErr) {
        // Vite browser dev fallback — sidecar IPC unavailable
        try {
          const controller = new AbortController()
          const timer = setTimeout(() => controller.abort(), 8000)
          try {
            const directRes = await fetch('http://127.0.0.1:8765/skills/alerts/auto/list', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ view_mode: 'ALL', limit: 300 }),
              signal: controller.signal,
            })
            if (directRes.ok) {
              const data = await directRes.json()
              list = data?.data ?? data ?? []
            }
          } finally {
            clearTimeout(timer)
          }
        } catch (_netErr) {
          // Backend offline or reloading; fallback gracefully without logging uncaught error
        }
      }
      if (Array.isArray(list) && list.length > 0) {
        useNotificationStore.getState().syncRecentAlerts(list)
      }
    } catch (err) {
      console.error('[notificationStore] fetchAlerts error:', err)
    } finally {
      set({ isLoading: false })
    }
  },

  /**
   * Starts the singleton background polling loop (30s interval).
   * Idempotent — calling it multiple times is safe; only one timer ever runs.
   * @param {Function} call - the useAPI `call` function
   */
  startPolling: (call) => {
    if (_pollTimer !== null) return // already running
    // Immediate first fetch
    useNotificationStore.getState().fetchAlerts(call)
    _pollTimer = setInterval(() => {
      useNotificationStore.getState().fetchAlerts(call)
    }, 30_000)
  },

  /**
   * Stops the singleton polling loop. Call on app unmount or broker disconnect.
   */
  stopPolling: () => {
    if (_pollTimer !== null) {
      clearInterval(_pollTimer)
      _pollTimer = null
    }
  },
}))
