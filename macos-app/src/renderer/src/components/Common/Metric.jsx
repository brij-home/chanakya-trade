import React from 'react'

/**
 * Accessible Financial Metric Tile adhering to WCAG 2.2 AA.
 *
 * Features:
 * - Clear semantic structure with dual visual + textual change indicators
 * - High-contrast palette compliant with 4.5:1 text contrast ratios
 * - Support for Indian financial units (₹Cr, ₹L, ₹)
 */
export default function Metric({
  label,
  value,
  change = null,
  changePct = null,
  unit = '',
  status = 'neutral', // 'positive' | 'negative' | 'neutral' | 'warning'
  subtext = null,
  tooltip = null,
  className = '',
}) {
  // Determine status automatically if change or changePct is provided and status is neutral
  let resolvedStatus = status
  if (status === 'neutral') {
    const num = change !== null ? change : changePct
    if (num !== null && num !== undefined) {
      if (num > 0) resolvedStatus = 'positive'
      else if (num < 0) resolvedStatus = 'negative'
    }
  }

  const statusColors = {
    positive: {
      text: 'text-emerald-700 dark:text-emerald-300',
      badge: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
      icon: '▲ +',
    },
    negative: {
      text: 'text-rose-700 dark:text-rose-300',
      badge: 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30',
      icon: '▼ -',
    },
    warning: {
      text: 'text-amber-700 dark:text-amber-300',
      badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30',
      icon: '●',
    },
    neutral: {
      text: 'text-text',
      badge: 'bg-elevated text-muted border-border',
      icon: '',
    },
  }

  const currentTheme = statusColors[resolvedStatus] || statusColors.neutral

  return (
    <div
      role="group"
      aria-label={`${label}: ${value}`}
      title={tooltip || undefined}
      className={`rounded-xl bg-panel border border-border p-3.5 sm:p-4 flex flex-col justify-between transition-all duration-150 hover:border-subtle shadow-card ${className}`}
    >
      {/* Label */}
      <div className="flex items-center justify-between text-xs font-medium text-muted mb-1.5">
        <span>{label}</span>
        {tooltip && (
          <span
            className="cursor-help text-muted hover:text-text text-[10px]"
            aria-hidden="true"
          >
            ⓘ
          </span>
        )}
      </div>

      {/* Primary Value */}
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-lg sm:text-xl font-bold font-mono tracking-tight text-text">
          {value !== null && value !== undefined ? (
            <>
              {value}
              {unit && <span className="text-xs font-normal text-muted ml-1">{unit}</span>}
            </>
          ) : (
            <span className="text-muted font-sans text-sm font-normal">Unavailable</span>
          )}
        </div>

        {/* Change Badge */}
        {(change !== null || changePct !== null) && (
          <div
            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-mono font-bold border ${currentTheme.badge}`}
          >
            <span className="mr-0.5 text-[9px]" aria-hidden="true">
              {resolvedStatus === 'positive' ? '▲' : resolvedStatus === 'negative' ? '▼' : ''}
            </span>
            <span>
              {changePct !== null && changePct !== undefined
                ? `${changePct > 0 ? '+' : ''}${typeof changePct === 'number' ? changePct.toFixed(2) : changePct}%`
                : `${change > 0 ? '+' : ''}${change}`}
            </span>
          </div>
        )}
      </div>

      {/* Subtext */}
      {subtext && <div className="text-[11px] text-muted mt-1.5">{subtext}</div>}
    </div>
  )
}
