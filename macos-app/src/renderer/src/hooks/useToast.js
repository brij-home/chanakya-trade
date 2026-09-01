import { create } from 'zustand'
import { useCallback } from 'react'

/**
 * Toast types and their visual configs
 */
export const TOAST_CONFIGS = {
  success: {
    icon: '✓',
    borderColor: 'var(--color-emerald)',
    iconBg: 'rgba(0, 214, 143, 0.15)',
    iconColor: 'var(--color-emerald)',
    glow: '0 0 16px rgba(0, 214, 143, 0.25)',
  },
  error: {
    icon: '✕',
    borderColor: 'var(--color-rose)',
    iconBg: 'rgba(255, 79, 123, 0.15)',
    iconColor: 'var(--color-rose)',
    glow: '0 0 16px rgba(255, 79, 123, 0.25)',
  },
  warning: {
    icon: '⚠',
    borderColor: 'var(--color-gold)',
    iconBg: 'rgba(245, 166, 35, 0.15)',
    iconColor: 'var(--color-gold)',
    glow: '0 0 16px rgba(245, 166, 35, 0.25)',
  },
  info: {
    icon: 'ℹ',
    borderColor: 'var(--color-sapphire)',
    iconBg: 'rgba(77, 155, 255, 0.15)',
    iconColor: 'var(--color-sapphire)',
    glow: '0 0 16px rgba(77, 155, 255, 0.25)',
  },
  trade: {
    icon: '⚡',
    borderColor: 'var(--color-gold)',
    iconBg: 'rgba(245, 166, 35, 0.20)',
    iconColor: 'var(--color-gold)',
    glow: '0 0 20px rgba(245, 166, 35, 0.35)',
  },
  debate: {
    icon: '⚔️',
    borderColor: 'var(--color-violet)',
    iconBg: 'rgba(157, 125, 255, 0.15)',
    iconColor: 'var(--color-violet)',
    glow: '0 0 16px rgba(157, 125, 255, 0.25)',
  },
}

let _toastId = 0

/**
 * Zustand store for toast state
 */
export const useToastStore = create((set) => ({
  toasts: [],

  addToast: (toast) => {
    const id = ++_toastId
    set((s) => ({
      toasts: [
        ...s.toasts.slice(-4), // Keep max 5 toasts
        {
          id,
          type: 'info',
          title: '',
          message: '',
          duration: 5000,
          action: null,
          ...toast,
          exiting: false,
        },
      ],
    }))
    return id
  },

  dismissToast: (id) => {
    // Mark as exiting for animation
    set((s) => ({
      toasts: s.toasts.map((t) => (t.id === id ? { ...t, exiting: true } : t)),
    }))
    // Remove after animation completes
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 280)
  },

  clearAll: () => set({ toasts: [] }),
}))

/**
 * useToast — convenience hook for triggering toasts
 *
 * Usage:
 *   const toast = useToast()
 *   toast.success('Order placed!', 'RELIANCE BUY @ ₹2,847')
 *   toast.trade('Signal fired', 'NIFTY READY — Demand OB Retest', { action: { label: 'View', onClick: fn } })
 */
export function useToast() {
  const addToast = useToastStore((s) => s.addToast)
  const dismissToast = useToastStore((s) => s.dismissToast)

  const show = useCallback(
    (type, title, message, opts = {}) => {
      const id = addToast({ type, title, message, ...opts })
      if (opts.duration !== 0) {
        setTimeout(() => dismissToast(id), opts.duration ?? 5000)
      }
      return id
    },
    [addToast, dismissToast],
  )

  return {
    success: (title, message, opts) => show('success', title, message, opts),
    error:   (title, message, opts) => show('error',   title, message, { duration: 7000, ...opts }),
    warning: (title, message, opts) => show('warning', title, message, opts),
    info:    (title, message, opts) => show('info',    title, message, opts),
    trade:   (title, message, opts) => show('trade',   title, message, { duration: 8000, ...opts }),
    debate:  (title, message, opts) => show('debate',  title, message, opts),
    dismiss: dismissToast,
    clearAll: useToastStore.getState().clearAll,
  }
}

export default useToast
