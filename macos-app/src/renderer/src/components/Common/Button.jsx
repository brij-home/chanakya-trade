import React from 'react'

/**
 * Accessible Institutional Button component adhering to WCAG 2.2 AA.
 *
 * Features:
 * - High contrast visual styling with explicit focus-visible rings
 * - Loading indicator with aria-busy and aria-live status
 * - Keyboard accessible with Enter / Spacebar activation
 * - Variants: primary, secondary, danger, ghost, outline
 */
export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  disabled = false,
  icon = null,
  type = 'button',
  ariaLabel,
  className = '',
  onClick,
  ...props
}) {
  const isDisabled = disabled || isLoading

  // Base styling with prominent focus rings and calm institutional feel
  const baseStyles =
    'inline-flex items-center justify-center font-medium rounded-lg transition-all duration-150 select-none outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-slate-900 disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none'

  const sizeStyles = {
    sm: 'text-xs px-2.5 py-1.5 gap-1.5 min-h-[32px]',
    md: 'text-sm px-3.5 py-2 gap-2 min-h-[38px]',
    lg: 'text-base px-5 py-2.5 gap-2.5 min-h-[46px]',
  }

  const variantStyles = {
    primary:
      'bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white shadow-sm hover:shadow shadow-emerald-950/40 border border-emerald-500/30',
    secondary:
      'bg-slate-800 hover:bg-slate-700 active:bg-slate-900 text-slate-100 border border-slate-700 hover:border-slate-600 shadow-sm',
    danger:
      'bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white shadow-sm hover:shadow shadow-rose-950/40 border border-rose-500/30',
    ghost:
      'bg-transparent hover:bg-slate-800/80 active:bg-slate-800 text-slate-300 hover:text-slate-100 border border-transparent',
    outline:
      'bg-transparent hover:bg-slate-800/60 active:bg-slate-800 text-emerald-400 hover:text-emerald-300 border border-emerald-500/40 hover:border-emerald-500/70',
  }

  return (
    <button
      type={type}
      disabled={isDisabled}
      aria-disabled={isDisabled}
      aria-busy={isLoading}
      aria-label={ariaLabel}
      onClick={onClick}
      className={`${baseStyles} ${sizeStyles[size] || sizeStyles.md} ${variantStyles[variant] || variantStyles.primary} ${className}`}
      {...props}
    >
      {isLoading ? (
        <>
          <svg
            className="animate-spin -ml-0.5 h-4 w-4 text-current"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          <span>{typeof children === 'string' ? 'Processing...' : children}</span>
        </>
      ) : (
        <>
          {icon && <span className="flex-shrink-0" aria-hidden="true">{icon}</span>}
          {children}
        </>
      )}
    </button>
  )
}
