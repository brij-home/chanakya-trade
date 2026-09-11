import { create } from 'zustand'

const STORAGE_KEY = 'chanakya_notifications_v1'
const MAX_NOTIFICATIONS = 100

// Safe localStorage loader
function loadStoredNotifications() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
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
  const premiumNum = payload.option_premium ? Number(payload.option_premium) : (payload.ltp ? Number(payload.ltp) : null)
  const ltpNum = payload.ltp ? Number(String(payload.ltp).replace(/[^0-9.-]/g, '')) : null

  const slNum = optPlan?.sl_premium ? Number(optPlan.sl_premium) : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (payload.stop_loss ? Number(payload.stop_loss) : (payload.sl ? Number(payload.sl) : null)))
  const entryNum = optPlan?.entry_premium ? Number(optPlan.entry_premium) : (tradePlan.entry_price ? Number(tradePlan.entry_price) : (payload.trigger_level ? Number(payload.trigger_level) : (payload.entry ? Number(payload.entry) : (premiumNum || ltpNum))))
  const t1Num = optPlan?.t1_premium ? Number(optPlan.t1_premium) : (tradePlan.target_1 ? Number(tradePlan.target_1) : (payload.target_level ? Number(payload.target_level) : (payload.t1 ? Number(payload.t1) : null)))
  const t2Num = optPlan?.t2_premium ? Number(optPlan.t2_premium) : (tradePlan.target_2 ? Number(tradePlan.target_2) : (payload.t2 ? Number(payload.t2) : null))
  const t3Num = optPlan?.t3_premium ? Number(optPlan.t3_premium) : (tradePlan.target_3 ? Number(tradePlan.target_3) : (payload.t3 ? Number(payload.t3) : null))

  const rawTime = payload.created_at || payload.timestamp || payload.triggered_at || now.toISOString()

  return {
    id,
    symbol: cleanSym || 'UNKNOWN',
    contract_symbol: payload.contract_symbol || null,
    strike: strikeNum,
    option_type: optType,
    direction: payload.direction || (payload.headline?.includes('BULL') ? 'BULLISH' : 'BEARISH'),
    alert_type: payload.alert_type || 'ALERT',
    stage: payload.stage || (isInvalidated ? 'INVALIDATED' : isTarget ? 'TARGET_ACHIEVED' : isTrail ? 'TRAILING_UPDATE' : 'ACTIVE'),
    is_invalidated: isInvalidated,
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

  setDropdownOpen: (isOpen) => set({ isDropdownOpen: isOpen }),
  toggleDropdown: () => set((s) => ({ isDropdownOpen: !s.isDropdownOpen })),

  setSelectedNotification: (notif) => set({ selectedNotification: notif }),

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
}))
