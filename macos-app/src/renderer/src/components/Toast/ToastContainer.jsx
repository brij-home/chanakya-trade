import { useState, useEffect, useRef, useCallback } from 'react'
import { useToastStore, TOAST_CONFIGS } from '../../hooks/useToast'

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
    remainingRef.current = Math.max(800, remainingRef.current - elapsed)

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

  return (
    <div
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className={`relative flex items-start gap-3 min-w-[320px] max-w-[420px] rounded-2xl overflow-hidden font-ui transition-transform duration-200
        ${toast.exiting ? 'animate-toast-out pointer-events-none' : 'animate-toast-in'}`}
      style={{
        background: 'var(--color-panel)',
        border: `1px solid ${cfg.borderColor}`,
        boxShadow: isHovered
          ? `var(--shadow-float), 0 0 24px ${cfg.borderColor}40`
          : `var(--shadow-float), ${cfg.glow}`,
        padding: '12px 14px',
        transform: isHovered ? 'scale(1.02)' : 'scale(1)',
      }}
    >
      {/* Left accent border */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3.5px] rounded-l-2xl"
        style={{ background: cfg.borderColor }}
      />

      {/* Icon */}
      <div
        className="flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center text-sm font-bold shadow-sm"
        style={{ background: cfg.iconBg, color: cfg.iconColor }}
      >
        {toast.type === 'debate' ? '⚔️' : cfg.icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pr-6">
        <div className="flex items-center justify-between gap-1.5 mb-0.5">
          {toast.title && (
            <div className="text-xs font-bold text-text leading-tight truncate">
              {toast.title}
            </div>
          )}
          {toast.timestamp && (
            <span className="text-[9px] font-mono font-semibold text-muted/90 flex-shrink-0 px-1.5 py-0.2 rounded bg-surface/80 border border-border/50">
              🕒 {toast.timestamp}
            </span>
          )}
        </div>
        {toast.message && (
          <div className="text-[11px] text-muted leading-snug break-words">
            {toast.message}
          </div>
        )}
        {/* Action button */}
        {toast.action && (
          <button
            onClick={() => {
              toast.action.onClick?.()
              dismissToast(toast.id)
            }}
            className="mt-1.5 text-[11px] font-bold transition-colors cursor-pointer flex items-center gap-1 hover:underline"
            style={{ color: cfg.borderColor }}
          >
            {toast.action.label} →
          </button>
        )}
      </div>

      {/* Close button */}
      <button
        onClick={() => dismissToast(toast.id)}
        className="absolute top-2.5 right-2.5 w-5 h-5 flex items-center justify-center rounded-md
          text-muted hover:text-text hover:bg-elevated text-[10px] font-bold transition-all cursor-pointer"
        title="Dismiss alert"
      >
        ✕
      </button>

      {/* Progress bar */}
      {toast.duration > 0 && (
        <div
          className="absolute bottom-0 left-0 right-0 h-[2px]"
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
      className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2.5 pointer-events-none"
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
