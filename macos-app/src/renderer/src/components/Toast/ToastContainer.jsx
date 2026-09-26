import { useState, useEffect, useRef, useCallback } from 'react'
import { useToastStore, TOAST_CONFIGS } from '../../hooks/useToast'
import { useNotificationStore } from '../../store/notificationStore'
import { useChatStore } from '../../store/chatStore'

const STAGE_CONFIG = {
  INVALIDATED: { label: 'INVALIDATED', bg: 'bg-rose-500/20', text: 'text-rose-400', border: 'border-rose-500/40', icon: '❌' },
  TARGET_ACHIEVED: { label: 'TARGET HIT', bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40', icon: '🎯' },
  T1_ACHIEVED: { label: 'T1 HIT', bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40', icon: '🎯' },
  T2_ACHIEVED: { label: 'T2 HIT', bg: 'bg-cyan-500/20', text: 'text-cyan-400', border: 'border-cyan-500/40', icon: '🚀' },
  TRAILING_UPDATE: { label: 'TRAILING STOP', bg: 'bg-blue-500/20', text: 'text-blue-400', border: 'border-blue-500/40', icon: '📈' },
  IGNITED: { label: 'IGNITED', bg: 'bg-amber-500/20', text: 'text-amber-400', border: 'border-amber-500/40', icon: '🔥' },
  EARLY_WARNING: { label: 'EARLY WARNING', bg: 'bg-amber-500/15', text: 'text-amber-300', border: 'border-amber-500/30', icon: '⏳' },
  SPREAD_SHORT_STRIKE_TOUCH: { label: 'SPREAD TOUCH', bg: 'bg-purple-500/20', text: 'text-purple-400', border: 'border-purple-500/40', icon: '⚡' },
  SPREAD_PROFIT_70: { label: '70% MAX PROFIT', bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40', icon: '💰' },
  ACTIVE: { label: 'ACTIVE', bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/30', icon: '🟢' },
}

function fmtPrice(val) {
  if (val == null || isNaN(val) || val === '') return '—'
  const num = Number(val)
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: num < 10 ? 2 : (num < 100 ? 1 : 0),
    maximumFractionDigits: 2,
  })
}

/**
 * Individual Toast Item with graceful hover-pause & smooth animations
 */
function ToastItem({ toast }) {
  const dismissToast = useToastStore((s) => s.dismissToast)
  const progressRef = useRef(null)
  const cfg = TOAST_CONFIGS[toast.type] || TOAST_CONFIGS.info

  const [isHovered, setIsHovered] = useState(false)
  const remainingRef = useRef(toast.duration ?? 5000)
  const startTimeRef = useRef(Date.now())
  const timerRef = useRef(null)

  // Start / Resume auto-dismiss timer
  const startTimer = useCallback(() => {
    if (remainingRef.current <= 0 || toast.duration === 0) return
    startTimeRef.current = Date.now()
    timerRef.current = setTimeout(() => {
      dismissToast(toast.id)
    }, remainingRef.current)

    if (progressRef.current) {
      progressRef.current.style.transition = `width ${remainingRef.current}ms linear`
      requestAnimationFrame(() => {
        if (progressRef.current) {
          progressRef.current.style.width = '0%'
        }
      })
    }
  }, [toast.duration, toast.id, dismissToast])

  // Pause timer when hovered so user can inspect without rushing
  const pauseTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const elapsed = Date.now() - startTimeRef.current
    remainingRef.current = Math.max(1200, remainingRef.current - elapsed)

    if (progressRef.current) {
      const computedWidth = window.getComputedStyle(progressRef.current).width
      progressRef.current.style.transition = 'none'
      progressRef.current.style.width = computedWidth
    }
  }, [])

  useEffect(() => {
    if (toast.duration === 0) return
    startTimer()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [startTimer, toast.duration])

  const handleMouseEnter = () => {
    setIsHovered(true)
    pauseTimer()
  }

  const handleMouseLeave = () => {
    setIsHovered(false)
    startTimer()
  }

  // ── Trade Alert Attributes Extraction ────────────────────────────────────
  const alert = toast.alert
  const isAlertToast = Boolean(alert && (alert.symbol || alert.contract_symbol))

  const symbol = alert?.symbol || ''
  const strike = alert?.strike
  const optionType = alert?.option_type
  const isPut = optionType === 'PE' || alert?.direction === 'BEARISH'
  const isCall = optionType === 'CE' || alert?.direction === 'BULLISH'
  const contractDetails = strike && optionType ? `${strike} ${optionType}` : (optionType || '')

  const direction = alert?.direction || (isPut ? 'BEARISH' : 'BULLISH')
  const isBearish = direction === 'BEARISH' || direction === 'SHORT' || direction === 'SELL'
  const actionTag = alert?.actionable_plan?.action || (isPut ? 'BUY PE' : (isCall ? 'BUY CE' : (isBearish ? 'SELL SHORT' : 'BUY')))

  const rawStage = alert?.stage || (alert?.is_invalidated ? 'INVALIDATED' : (alert?.is_target ? 'TARGET_ACHIEVED' : 'ACTIVE'))
  const isInvalidated = Boolean(alert?.is_invalidated || rawStage === 'INVALIDATED')
  const stageStyle = STAGE_CONFIG[rawStage] || STAGE_CONFIG.ACTIVE

  const entryPrice = alert?.trigger_level ?? alert?.entry_price ?? alert?.ltp
  const stopLoss = alert?.stop_loss ?? alert?.initial_stop_loss
  const targetPrice = alert?.target_level ?? alert?.target_1
  const hasLevels = Boolean(entryPrice && (stopLoss || targetPrice))

  const confidence = alert?.confidence || alert?.conviction_score
  const isTest = alert?.environment === 'TEST' || alert?.is_live === false

  // Clean headline without duplicate environmental/mode badges
  let cleanHeadline = alert?.headline || toast.title || ''
  cleanHeadline = cleanHeadline
    .replace(/\[REAL\/LIVE\]/gi, '')
    .replace(/\[TEST\]/gi, '')
    .replace(/^[🟢🧪⚠️🎯📈🔥💰⚡\s:]+/, '')
    .trim()
  if (!cleanHeadline) cleanHeadline = alert?.alert_type?.replace(/_/g, ' ') || 'Trade Alert'

  const summaryText = alert?.trailing_decision
    ? `⚡ ${alert.trailing_decision}: ${alert.trailing_rationale || alert.summary || ''}`
    : (alert?.invalidation_reason || alert?.trailing_rationale || alert?.summary || toast.message || '')

  // ── Action Handlers ──────────────────────────────────────────────────────
  const handleTrade = (e) => {
    e?.stopPropagation()
    if (!alert) return
    const act = (alert.direction === 'BEARISH' && alert.option_type === 'PE') ? 'BUY' : (alert.direction === 'BEARISH' ? 'SELL' : 'BUY')
    const ticketData = {
      symbol: alert.contract_symbol || alert.contract || alert.symbol,
      exchange: alert.exchange || 'NFO',
      action: act,
      orderType: 'LIMIT',
      product: alert.segment === 'EQUITY' ? 'MIS' : 'NRML',
      price: alert.trigger_level || alert.ltp || alert.entry_price || '',
      stopLoss: alert.stop_loss || alert.initial_stop_loss || '',
      target: alert.target_level || alert.target_1 || '',
      lotSize: alert.lot_size || 1,
    }
    window.dispatchEvent(new CustomEvent('open-order-ticket', { detail: ticketData }))
    dismissToast(toast.id)
  }

  const handleViewDetails = (e) => {
    e?.stopPropagation()
    if (!alert) return
    useNotificationStore.getState().setSelectedNotification(alert)
    dismissToast(toast.id)
  }

  const handleCardClick = (e) => {
    if (e.target.closest('button')) return
    if (isInvalidated || rawStage === 'RUNNER_EXIT') {
      handleViewDetails(e)
    } else {
      handleTrade(e)
    }
  }

  return (
    <div
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={isAlertToast ? handleCardClick : undefined}
      className={`relative flex items-center justify-between gap-2 w-[310px] sm:w-[330px] rounded-xl overflow-hidden font-ui transition-all duration-150
        ${isAlertToast ? 'cursor-pointer group hover:brightness-105' : ''}
        ${toast.exiting ? 'animate-toast-out pointer-events-none' : 'animate-toast-in'}`}
      style={{
        background: 'var(--color-panel)',
        border: `1px solid ${cfg.borderColor}55`,
        boxShadow: isHovered
          ? `0 4px 16px rgba(0,0,0,0.5), 0 0 12px ${cfg.borderColor}30`
          : '0 2px 10px rgba(0,0,0,0.4)',
        padding: '7px 9px 8px 10px',
        transform: isHovered ? 'translateY(-1px)' : 'none',
      }}
    >
      {/* Left accent border */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px]"
        style={{ background: cfg.borderColor }}
      />

      {/* Content Body */}
      {isAlertToast ? (
        <div className="flex-1 min-w-0 pr-1">
          {/* Line 1: Icon + Symbol + Contract + Action Tag + Stage Tag */}
          <div className="flex items-center gap-1.5 leading-none">
            <span className="text-[12px] flex-shrink-0" role="img" aria-label="stage">
              {stageStyle.icon || '⚡'}
            </span>
            <span className="text-[11px] font-black font-mono text-text tracking-wide truncate max-w-[110px]">
              {symbol}
            </span>
            {contractDetails && (
              <span className={`text-[9px] font-mono font-bold px-1 py-0.2 rounded border flex-shrink-0 ${
                isPut ? 'bg-rose-500/15 text-rose-400 border-rose-500/30' : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
              }`}>
                {contractDetails}
              </span>
            )}
            <span className={`text-[8.5px] font-black uppercase px-1 py-0.5 rounded leading-none flex-shrink-0 ${
              isBearish ? 'bg-rose-500/20 text-rose-300' : 'bg-emerald-500/20 text-emerald-300'
            }`}>
              {actionTag}
            </span>
            <span className={`text-[8px] font-bold px-1 py-0.2 rounded border uppercase tracking-wider flex-shrink-0 ${stageStyle.bg} ${stageStyle.text} ${stageStyle.border}`}>
              {stageStyle.label}
            </span>
          </div>

          {/* Line 2: Monospace Price Levels or 1-line reason */}
          <div className="flex items-center gap-2 mt-1 text-[10px] font-mono leading-none truncate text-muted">
            {hasLevels ? (
              <>
                <span className="text-text font-bold">₹{fmtPrice(entryPrice)}</span>
                {stopLoss && <span className="text-rose-400">SL ₹{fmtPrice(stopLoss)}</span>}
                {targetPrice && <span className="text-emerald-400">Tgt ₹{fmtPrice(targetPrice)}</span>}
              </>
            ) : (
              <span className="truncate text-text/80 text-[10px] font-ui">
                {summaryText || cleanHeadline}
              </span>
            )}
          </div>
        </div>
      ) : (
        /* Standard Non-Alert Toast (e.g. system notifications) */
        <div className="flex-1 min-w-0 pr-1">
          <div className="flex items-center gap-1.5 leading-none">
            <span className="text-xs flex-shrink-0" style={{ color: cfg.iconColor }}>
              {cfg.icon}
            </span>
            {toast.title && (
              <span className="text-[11px] font-bold text-text truncate">
                {toast.title}
              </span>
            )}
          </div>
          {toast.message && (
            <div className="text-[10px] text-muted truncate mt-1 leading-tight">
              {toast.message}
            </div>
          )}
          {toast.action && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                toast.action.onClick?.()
                dismissToast(toast.id)
              }}
              className="mt-0.5 text-[9px] font-bold hover:underline cursor-pointer"
              style={{ color: cfg.borderColor }}
            >
              {toast.action.label} →
            </button>
          )}
        </div>
      )}

      {/* Action button & Close button */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {isAlertToast && !isInvalidated && rawStage !== 'RUNNER_EXIT' && (
          <button
            onClick={handleTrade}
            className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 transition-colors flex items-center gap-0.5 cursor-pointer"
            title="Open Order Ticket"
          >
            ⚡ Ticket
          </button>
        )}
        {isAlertToast && (isInvalidated || rawStage === 'RUNNER_EXIT') && (
          <button
            onClick={handleViewDetails}
            className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-surface hover:bg-elevated text-text border border-border/70 transition-colors flex items-center gap-0.5 cursor-pointer"
            title="View Details"
          >
            🔍 Details
          </button>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation()
            dismissToast(toast.id)
          }}
          className="w-4 h-4 flex items-center justify-center rounded text-muted hover:text-text hover:bg-surface text-[10px] font-bold transition-colors cursor-pointer"
          title="Dismiss"
        >
          ✕
        </button>
      </div>

      {/* Progress bar */}
      {toast.duration > 0 && (
        <div
          className="absolute bottom-0 left-0 right-0 h-[1.5px]"
          style={{ background: 'var(--color-border)' }}
        >
          <div
            ref={progressRef}
            className="h-full rounded-full"
            style={{
              width: '100%',
              background: cfg.borderColor,
              transition: 'none',
            }}
          />
        </div>
      )}
    </div>
  )
}

/**
 * ToastContainer — renders the toast stack in bottom-right
 * Mount this once in the root of your app.
 */
export default function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts)

  if (toasts.length === 0) return null

  return (
    <div
      className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-1.5 pointer-events-none"
      aria-live="polite"
      aria-label="Notifications"
    >
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} />
        </div>
      ))}
    </div>
  )
}
