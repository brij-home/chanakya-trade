import { useEffect, useRef } from 'react'
import { useToastStore, TOAST_CONFIGS } from '../../hooks/useToast'

/**
 * Individual Toast Item
 */
function ToastItem({ toast }) {
  const dismissToast = useToastStore((s) => s.dismissToast)
  const progressRef = useRef(null)
  const cfg = TOAST_CONFIGS[toast.type] || TOAST_CONFIGS.info

  // Animate progress bar depletion
  useEffect(() => {
    if (!progressRef.current || toast.duration === 0) return
    const el = progressRef.current
    el.style.transition = `width ${toast.duration}ms linear`
    // Trigger via microtask so CSS transition kicks in
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.style.width = '0%'
      })
    })
  }, [toast.duration])

  return (
    <div
      className={`relative flex items-start gap-3 min-w-[320px] max-w-[420px] rounded-2xl overflow-hidden font-ui
        ${toast.exiting ? 'animate-toast-out' : 'animate-toast-in'}`}
      style={{
        background: 'var(--color-panel)',
        border: `1px solid ${cfg.borderColor}`,
        boxShadow: `var(--shadow-float), ${cfg.glow}`,
        padding: '12px 14px',
      }}
    >
      {/* Left accent border */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-2xl"
        style={{ background: cfg.borderColor }}
      />

      {/* Icon */}
      <div
        className="flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center text-sm font-bold"
        style={{ background: cfg.iconBg, color: cfg.iconColor }}
      >
        {toast.type === 'debate' ? '⚔️' : cfg.icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pr-6">
        {toast.title && (
          <div className="text-xs font-bold text-text leading-tight mb-0.5 truncate">
            {toast.title}
          </div>
        )}
        {toast.message && (
          <div className="text-[11px] text-muted leading-snug">
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
            className="mt-1.5 text-[11px] font-bold transition-colors cursor-pointer"
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
        <div key={toast.id} className="pointer-events-all">
          <ToastItem toast={toast} />
        </div>
      ))}
    </div>
  )
}
