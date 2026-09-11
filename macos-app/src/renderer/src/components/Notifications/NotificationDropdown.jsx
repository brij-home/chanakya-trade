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
  INVALIDATED:     { label: '❌ INVALID', bg: 'bg-rose-500/15', text: 'text-rose-300', border: 'border-rose-500/30' },
  TARGET_ACHIEVED: { label: '🎯 TARGET', bg: 'bg-emerald-500/15', text: 'text-emerald-300', border: 'border-emerald-500/30' },
  T1_ACHIEVED:     { label: '🎯 T1 HIT', bg: 'bg-emerald-500/15', text: 'text-emerald-300', border: 'border-emerald-500/30' },
  TRAILING_UPDATE: { label: '📈 TRAIL', bg: 'bg-blue-500/15', text: 'text-blue-300', border: 'border-blue-500/30' },
  IGNITED:         { label: '🔥 IGNITED', bg: 'bg-amber-500/20', text: 'text-amber-300', border: 'border-amber-500/40' },
  EARLY_WARNING:   { label: '⏳ EARLY', bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20' },
  ACTIVE:          { label: '🟢 ACTIVE', bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20' },
}

export default function NotificationDropdown({ isOpen, onClose, onOpenOrderTicket }) {
  const [filter, setFilter] = useState('all') // 'all' | 'unread'
  const dropdownRef = useRef(null)

  const notifications = useNotificationStore((s) => s.notifications)
  const unreadCount = useNotificationStore((s) => s.unreadCount)
  const markAsRead = useNotificationStore((s) => s.markAsRead)
  const markAllAsRead = useNotificationStore((s) => s.markAllAsRead)
  const clearAll = useNotificationStore((s) => s.clearAll)
  const removeNotification = useNotificationStore((s) => s.removeNotification)
  const setSelectedNotification = useNotificationStore((s) => s.setSelectedNotification)

  const setSelectedSymbol = useChatStore((s) => s.setSelectedSymbol)
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

  const filtered = filter === 'unread'
    ? notifications.filter((n) => !n.read)
    : notifications

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
      className="absolute top-12 right-3 z-[9999] w-[400px] max-w-[calc(100vw-24px)] rounded-2xl border shadow-2xl overflow-hidden font-ui animate-fade-in"
      style={{
        background: 'var(--color-panel)',
        borderColor: 'var(--color-border)',
        backdropFilter: 'blur(16px)',
        boxShadow: '0 20px 50px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.06)',
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
          <span className="text-sm font-black tracking-wide" style={{ color: 'var(--color-text)' }}>
            🔔 Live Notifications
          </span>
          {unreadCount > 0 && (
            <span
              className="text-[10px] font-black font-mono px-1.5 py-0.2 rounded-full"
              style={{
                background: 'var(--color-rose)',
                color: '#fff',
              }}
            >
              {unreadCount}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {unreadCount > 0 && (
            <button
              type="button"
              onClick={markAllAsRead}
              className="text-[10px] font-bold px-2 py-0.5 rounded-lg text-muted hover:text-emerald-400 hover:bg-surface transition-all cursor-pointer"
              title="Mark all as read"
            >
              ✓✓ Mark all read
            </button>
          )}
          {notifications.length > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="text-[10px] font-bold px-2 py-0.5 rounded-lg text-muted hover:text-rose-400 hover:bg-surface transition-all cursor-pointer"
              title="Clear all notifications"
            >
              🗑️ Clear
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded-lg text-muted hover:text-text hover:bg-surface text-xs font-bold transition-all cursor-pointer ml-1"
          >
            ✕
          </button>
        </div>
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────── */}
      <div
        className="flex items-center gap-1 px-3 py-1.5 border-b text-xs"
        style={{
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border-subtle)',
        }}
      >
        <button
          type="button"
          onClick={() => setFilter('all')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer ${
            filter === 'all'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          All ({notifications.length})
        </button>
        <button
          type="button"
          onClick={() => setFilter('unread')}
          className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all cursor-pointer flex items-center gap-1 ${
            filter === 'unread'
              ? 'bg-elevated text-text shadow-sm border border-border'
              : 'text-muted hover:text-text'
          }`}
        >
          <span>Unread</span>
          {unreadCount > 0 && (
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
          )}
        </button>
      </div>

      {/* ── Notification List ──────────────────────────────────── */}
      <div className="max-h-[420px] overflow-y-auto divide-y divide-border/40">
        {filtered.length === 0 ? (
          <div className="p-8 text-center flex flex-col items-center justify-center">
            <span className="text-2xl mb-2 select-none opacity-60">🔔</span>
            <div className="text-xs font-bold text-text mb-0.5">
              {filter === 'unread' ? 'All caught up!' : 'No notifications yet'}
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

            return (
              <div
                key={item.id}
                onClick={() => handleItemClick(item)}
                className={`p-3 transition-colors cursor-pointer group hover:bg-elevated/80 relative ${
                  isUnread ? 'bg-panel' : 'bg-transparent opacity-85 hover:opacity-100'
                }`}
              >
                {/* Left unread bar */}
                {isUnread && (
                  <div
                    className="absolute left-0 top-0 bottom-0 w-[3px]"
                    style={{ background: 'var(--color-gold)' }}
                  />
                )}

                {/* Row 1: Badges + Contract + Time */}
                <div className="flex items-center gap-1.5 flex-wrap mb-1">
                  {/* Stage pill */}
                  <span
                    className={`text-[8px] font-black px-1.5 py-0.5 rounded-md border whitespace-nowrap ${stageCfg.bg} ${stageCfg.text} ${stageCfg.border}`}
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
                      className={`text-[8px] px-1 py-px rounded font-black ${
                        item.option_type === 'CE'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : 'bg-rose-500/20 text-rose-300'
                      }`}
                    >
                      {item.option_type}
                    </span>
                  )}

                  {/* Direction */}
                  <span
                    className={`text-[9px] font-black whitespace-nowrap ml-0.5 ${
                      isBull ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                  >
                    {isBull ? '▲ BULL' : '▼ BEAR'}
                  </span>

                  {/* Test badge */}
                  {item.is_test && (
                    <span className="text-[7px] font-black px-1 py-px rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">
                      TEST
                    </span>
                  )}

                  {/* Relative timestamp */}
                  <span className="text-[9px] font-mono text-muted ml-auto whitespace-nowrap">
                    {formatRelativeTime(item.timestamp)}
                  </span>
                </div>

                {/* Row 2: Headline / Reason */}
                {item.summary && (
                  <div className="text-[11px] text-muted line-clamp-1 mb-1.5 leading-snug">
                    {item.summary}
                  </div>
                )}

                {/* Row 3: Key Price Levels & 1-Click Trade */}
                <div className="flex items-center justify-between gap-2 mt-1">
                  <div className="flex items-center gap-2 text-[10px] font-mono flex-wrap">
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
                    {item.sl && (
                      <span className="text-rose-400 font-bold">
                        SL ₹{fmt(item.sl)}
                      </span>
                    )}
                    {item.t1 && (
                      <span className="text-emerald-400 font-bold">
                        T1 ₹{fmt(item.t1)}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5 opacity-90 group-hover:opacity-100 transition-opacity">
                    {/* 1-Click Trade */}
                    <button
                      type="button"
                      onClick={(e) => handleTrade(e, item)}
                      className="text-[10px] font-bold px-2 py-0.5 rounded-lg text-emerald-300 hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 hover:border-emerald-500/50 transition-all cursor-pointer"
                      title="1-Click pre-fill order ticket"
                    >
                      ⚡ Trade
                    </button>

                    {/* Details arrow */}
                    <span className="text-[10px] font-bold text-muted group-hover:text-text transition-colors">
                      →
                    </span>

                    {/* Dismiss single item */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeNotification(item.id)
                      }}
                      className="w-5 h-5 flex items-center justify-center rounded text-muted hover:text-rose-400 text-[10px] transition-colors ml-0.5"
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
        className="flex items-center justify-between px-3 py-2 border-t text-[10px] font-mono"
        style={{
          background: 'var(--color-elevated)',
          borderColor: 'var(--color-border)',
          color: 'var(--color-muted)',
        }}
      >
        <span>Chanakya Real-Time Alert Bus</span>
        <button
          type="button"
          onClick={() => {
            onClose()
            setActiveView('alerts')
          }}
          className="font-bold hover:underline cursor-pointer"
          style={{ color: 'var(--color-gold)' }}
        >
          Open Alerts Manager (^7) →
        </button>
      </div>
    </div>
  )
}
