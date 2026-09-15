import React, { useState, useRef, useEffect } from 'react'
import { useNotificationStore } from '../../store/notificationStore'
import { useChatStore } from '../../store/chatStore'

function formatRelativeTime(dateStr) {
  if (!dateStr) return ''
  try {
    const clean = String(dateStr).replace(' IST', '').trim()
    const d = new Date(clean)
    if (isNaN(d.getTime())) return dateStr
    const diffSec = Math.floor((Date.now() - d.getTime()) / 1000)
    if (diffSec < 45) return 'just now'
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch (_) {
    return dateStr
  }
}

const STAGE_CONFIG = {
  INVALIDATED:     { label: '❌ INVALIDATED', bg: 'bg-rose-500/15', text: 'text-rose-600 dark:text-rose-300', border: 'border-rose-500/30' },
  TARGET_ACHIEVED: { label: '🎯 TARGET HIT', bg: 'bg-emerald-500/15', text: 'text-emerald-600 dark:text-emerald-300', border: 'border-emerald-500/30' },
  T1_ACHIEVED:     { label: '🎯 T1 HIT', bg: 'bg-emerald-500/15', text: 'text-emerald-600 dark:text-emerald-300', border: 'border-emerald-500/30' },
  TRAILING_UPDATE: { label: '📈 TRAILING STOP', bg: 'bg-blue-500/15', text: 'text-blue-600 dark:text-blue-300', border: 'border-blue-500/30' },
  IGNITED:         { label: '🔥 IGNITED', bg: 'bg-amber-500/20', text: 'text-amber-600 dark:text-amber-300', border: 'border-amber-500/40' },
  EARLY_WARNING:   { label: '⏳ EARLY WARNING', bg: 'bg-amber-500/15', text: 'text-amber-600 dark:text-amber-300', border: 'border-amber-500/30' },
  ACTIVE:          { label: '🟢 ACTIVE', bg: 'bg-emerald-500/15', text: 'text-emerald-600 dark:text-emerald-400', border: 'border-emerald-500/30' },
}

export default function NotificationDropdown({ isOpen, onClose, onOpenOrderTicket, onRefresh, isLoading = false }) {
  const [filter, setFilter] = useState('all') // 'all' | 'active' | 'targets' | 'invalidated' | 'unread'
  const dropdownRef = useRef(null)

  const notifications = useNotificationStore((s) => s.notifications)
  const unreadCount = useNotificationStore((s) => s.unreadCount)
  const markAsRead = useNotificationStore((s) => s.markAsRead)
  const markAllAsRead = useNotificationStore((s) => s.markAllAsRead)
  const clearAll = useNotificationStore((s) => s.clearAll)
  const removeNotification = useNotificationStore((s) => s.removeNotification)
  const setSelectedNotification = useNotificationStore((s) => s.setSelectedNotification)

  const setActiveView = useChatStore((s) => s.setActiveView)

  // Click outside to dismiss
  useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        onClose()
      }
    }
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  // Category counts
  const activeCount = notifications.filter((n) =>
    n.stage === 'IGNITED' || n.stage === 'ACTIVE' || n.stage === 'EARLY_WARNING'
  ).length

  const targetCount = notifications.filter((n) =>
    n.is_target || n.stage === 'TARGET_ACHIEVED' || n.stage === 'T1_ACHIEVED'
  ).length

  const invalidCount = notifications.filter((n) =>
    n.is_invalidated || n.stage === 'INVALIDATED'
  ).length

  // Filtered list
  const filtered = notifications.filter((n) => {
    if (filter === 'unread') return !n.read
    if (filter === 'active') return n.stage === 'IGNITED' || n.stage === 'ACTIVE' || n.stage === 'EARLY_WARNING'
    if (filter === 'targets') return n.is_target || n.stage === 'TARGET_ACHIEVED' || n.stage === 'T1_ACHIEVED'
    if (filter === 'invalidated') return n.is_invalidated || n.stage === 'INVALIDATED'
    return true
  })

  const handleItemClick = (item) => {
    markAsRead(item.id)
    setSelectedNotification(item)
  }

  const handleTrade = (e, item) => {
    e.stopPropagation()
    markAsRead(item.id)
    if (onOpenOrderTicket) {
      onOpenOrderTicket({
        symbol: item.contract_symbol || item.symbol,
        exchange: item.symbol?.includes('MCX') ? 'MCX' : 'NSE',
        price: item.entry || item.premium || item.ltp || item.spot || 100,
        stopLoss: item.sl,
        target: item.t1,
      })
    }
  }

  const fmt = (n, dec = 1) =>
    n != null && !isNaN(n)
      ? Number(n).toLocaleString('en-IN', {
          minimumFractionDigits: Number(n) < 100 ? dec : 0,
          maximumFractionDigits: dec,
        })
      : null

  return (
    <div
      ref={dropdownRef}
      className="absolute top-full mt-2 right-0 z-[9999] w-[440px] max-w-[calc(100vw-24px)] rounded-2xl border shadow-2xl overflow-hidden font-ui animate-fade-in"
      style={{
        background: 'var(--color-panel)',
        borderColor: 'var(--color-border)',
        backdropFilter: 'blur(20px)',
        boxShadow: '0 20px 50px rgba(0,0,0,0.65), 0 0 0 1px rgba(255,255,255,0.08)',
      }}
      role="dialog"
      aria-label="Notifications Center"
    >
      {/* ── Top Header ─────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-3.5 py-2.5 border-b"
        style={{
          background: 'var(--color-elevated)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-black tracking-wide flex items-center gap-1.5 text-text">
            <span>🔔</span>
            <span>Recent Alerts & Signals</span>
          </span>
          <span
            className="text-[10px] font-black font-mono px-1.5 py-0.5 rounded-full"
            style={{
              background: unreadCount > 0 ? 'var(--color-rose)' : 'var(--color-surface)',
              color: unreadCount > 0 ? '#fff' : 'var(--color-muted)',
              border: '1px solid var(--color-border)',
            }}
          >
            {notifications.length}
          </span>
        </div>

        <div className="flex items-center gap-1">
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              className={`p-1.5 rounded-lg text-muted hover:text-text hover:bg-surface text-xs font-bold transition-all cursor-pointer ${
                isLoading ? 'animate-spin text-gold' : ''
              }`}
              title="Refresh latest alerts from server"
            >
              🔄
            </button>
          )}

          {unreadCount > 0 && (
            <button
              type="button"
              onClick={markAllAsRead}
              className="text-[11px] font-bold px-2 py-0.5 rounded-lg text-muted hover:text-emerald-400 hover:bg-surface transition-all cursor-pointer"
              title="Mark all as read"
            >
              ✓✓ Mark read
            </button>
          )}

          {notifications.length > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="text-[11px] font-bold px-2 py-0.5 rounded-lg text-muted hover:text-rose-400 hover:bg-surface transition-all cursor-pointer"
              title="Clear all alerts"
            >
              🗑️
            </button>
          )}

          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded-lg text-muted hover:text-text hover:bg-surface text-xs font-bold transition-all cursor-pointer ml-1"
            title="Close"
          >
            ✕
          </button>
        </div>
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────── */}
      <div
        className="flex items-center gap-1 px-3 py-1.5 border-b text-xs overflow-x-auto no-scrollbar"
        style={{
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border-subtle)',
        }}
      >
        <button
          type="button"
          onClick={() => setFilter('all')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer whitespace-nowrap ${
            filter === 'all'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          All ({notifications.length})
        </button>

        <button
          type="button"
          onClick={() => setFilter('active')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer whitespace-nowrap ${
            filter === 'active'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          🔥 Active ({activeCount})
        </button>

        <button
          type="button"
          onClick={() => setFilter('targets')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer whitespace-nowrap ${
            filter === 'targets'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          🎯 Targets ({targetCount})
        </button>

        <button
          type="button"
          onClick={() => setFilter('invalidated')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer whitespace-nowrap ${
            filter === 'invalidated'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          ❌ Invalid ({invalidCount})
        </button>

        <button
          type="button"
          onClick={() => setFilter('unread')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer flex items-center gap-1 whitespace-nowrap ${
            filter === 'unread'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          <span>Unread ({unreadCount})</span>
          {unreadCount > 0 && (
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
          )}
        </button>
      </div>

      {/* ── Notification List ──────────────────────────────────── */}
      <div className="max-h-[460px] overflow-y-auto divide-y divide-border/30 custom-scrollbar">
        {isLoading && filtered.length === 0 ? (
          <div className="p-8 text-center flex flex-col items-center justify-center">
            <span className="text-2xl mb-2 select-none animate-spin">🔄</span>
            <div className="text-xs font-bold text-text mb-0.5">Syncing Real-Time Market Alerts…</div>
            <div className="text-[11px] text-muted max-w-[260px] leading-relaxed">
              Fetching active signals, gamma blasts, and breakouts from the backend engine.
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center flex flex-col items-center justify-center">
            <span className="text-2xl mb-2 select-none opacity-60">🔔</span>
            <div className="text-xs font-bold text-text mb-0.5">
              {filter === 'unread'
                ? 'All caught up!'
                : filter === 'active'
                ? 'No active setups currently'
                : 'No alerts in this category'}
            </div>
            <div className="text-[11px] text-muted max-w-[260px] leading-relaxed">
              Real-time gamma blasts, squeezes, invalidations, and target triggers will land here automatically.
            </div>
          </div>
        ) : (
          filtered.map((item) => {
            const isBull = item.direction === 'BULLISH'
            const stageCfg = STAGE_CONFIG[item.stage] || STAGE_CONFIG.ACTIVE
            const isUnread = !item.read

            // Left accent bar color
            const accentBg = item.is_invalidated || item.stage === 'INVALIDATED'
              ? 'var(--color-rose)'
              : item.is_target || item.stage?.includes('TARGET')
              ? 'var(--color-emerald)'
              : item.stage === 'IGNITED'
              ? 'var(--color-gold)'
              : isBull
              ? 'var(--color-emerald)'
              : 'var(--color-rose)'

            return (
              <div
                key={item.id}
                onClick={() => handleItemClick(item)}
                className={`p-3 transition-colors cursor-pointer group hover:bg-elevated relative ${
                  isUnread ? 'bg-elevated/40' : 'bg-transparent'
                }`}
              >
                {/* Left accent indicator bar */}
                <div
                  className="absolute left-0 top-0 bottom-0 w-[3px]"
                  style={{ background: accentBg }}
                />

                {/* Row 1: Badges + Contract + Time */}
                <div className="flex items-center gap-1.5 flex-wrap mb-1 pl-1">
                  {/* Stage pill */}
                  <span
                    className={`text-[9px] font-black px-1.5 py-0.5 rounded-md border whitespace-nowrap ${stageCfg.bg} ${stageCfg.text} ${stageCfg.border}`}
                  >
                    {stageCfg.label}
                  </span>

                  {/* Contract Symbol */}
                  <span className="text-xs font-black font-mono text-text">
                    {item.contract_symbol || item.symbol}
                  </span>

                  {/* Option Type */}
                  {item.option_type && (
                    <span
                      className={`text-[9px] px-1.5 py-0.2 rounded font-black font-mono border ${
                        item.option_type === 'CE'
                          ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-300 border-emerald-500/30'
                          : 'bg-rose-500/20 text-rose-600 dark:text-rose-300 border-rose-500/30'
                      }`}
                    >
                      {item.option_type}
                    </span>
                  )}

                  {/* Direction */}
                  <span
                    className={`text-[10px] font-black font-mono whitespace-nowrap ml-0.5 ${
                      isBull ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {isBull ? '▲ BULL' : '▼ BEAR'}
                  </span>

                  {/* Test badge */}
                  {item.is_test && (
                    <span className="text-[8px] font-black px-1 py-px rounded bg-purple-500/20 text-purple-600 dark:text-purple-300 border border-purple-500/30">
                      TEST
                    </span>
                  )}

                  {/* Relative timestamp */}
                  <span className="text-[10px] font-mono text-muted ml-auto whitespace-nowrap" title={item.timestamp}>
                    {formatRelativeTime(item.timestamp)}
                  </span>
                </div>

                {/* Row 2: Headline / Reason (readable 2-line preview) */}
                {(item.headline || item.summary) && (
                  <div className="text-xs text-text/80 line-clamp-2 mb-1.5 leading-snug pl-1">
                    {item.summary || item.headline}
                  </div>
                )}

                {/* Row 3: Key Numerical Levels Strip */}
                <div className="flex items-center justify-between gap-2 mt-1 pl-1">
                  <div className="flex items-center gap-2 text-[11px] font-mono flex-wrap">
                    {item.spot && (
                      <span className="text-muted">
                        Spot <span className="text-text font-bold">₹{fmt(item.spot, 0)}</span>
                      </span>
                    )}
                    {item.premium && (
                      <span className="text-gold font-bold">
                        Prem ₹{fmt(item.premium)}
                      </span>
                    )}
                    {!item.premium && item.ltp && (
                      <span className="text-muted">
                        LTP <span className="text-text font-bold">₹{fmt(item.ltp)}</span>
                      </span>
                    )}
                    {item.sl && (
                      <span className="text-rose-500 dark:text-rose-400 font-bold">
                        SL ₹{fmt(item.sl)}
                      </span>
                    )}
                    {item.t1 && (
                      <span className="text-emerald-500 dark:text-emerald-400 font-bold">
                        T1 ₹{fmt(item.t1)}
                      </span>
                    )}
                    {item.confidence && (
                      <span className="text-gold font-bold">
                        {item.confidence}%
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5 opacity-90 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    {/* 1-Click Trade */}
                    <button
                      type="button"
                      onClick={(e) => handleTrade(e, item)}
                      className="text-[11px] font-bold px-2 py-0.5 rounded-lg text-emerald-700 dark:text-emerald-300 hover:text-emerald-900 dark:hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-400/40 dark:border-emerald-500/30 hover:border-emerald-500/50 transition-all cursor-pointer flex items-center gap-0.5 shadow-sm"
                      title="1-Click pre-fill order ticket"
                    >
                      ⚡ Trade
                    </button>

                    {/* Details indicator */}
                    <span className="text-[11px] font-bold text-muted group-hover:text-text transition-colors">
                      →
                    </span>

                    {/* Dismiss single item */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeNotification(item.id)
                      }}
                      className="w-5 h-5 flex items-center justify-center rounded text-muted hover:text-rose-400 text-xs transition-colors ml-0.5"
                      title="Dismiss notification"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* ── Bottom Footer ───────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-3 py-2 border-t text-[11px] font-mono"
        style={{
          background: 'var(--color-elevated)',
          borderColor: 'var(--color-border)',
          color: 'var(--color-muted)',
        }}
      >
        <span>Chanakya Institutional Alert Bus</span>
        <button
          type="button"
          onClick={() => {
            onClose()
            setActiveView('alerts')
          }}
          className="font-bold hover:underline cursor-pointer flex items-center gap-1"
          style={{ color: 'var(--color-gold)' }}
        >
          <span>Open Alerts Manager (^7)</span>
          <span>→</span>
        </button>
      </div>
    </div>
  )
}
