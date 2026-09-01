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
      text: 'text-emerald-400',
      badge: 'bg-emerald-950/60 text-emerald-300 border-emerald-500/30',
      icon: '▲ +',
    },
    negative: {
      text: 'text-rose-400',
      badge: 'bg-rose-950/60 text-rose-300 border-rose-500/30',
      icon: '▼ -',
    },
    warning: {
      text: 'text-amber-400',
      badge: 'bg-amber-950/60 text-amber-300 border-amber-500/30',
      icon: '●',
    },
    neutral: {
      text: 'text-slate-200',
      badge: 'bg-slate-800 text-slate-300 border-slate-700',
      icon: '',
    },
  }

  const currentTheme = statusColors[resolvedStatus] || statusColors.neutral

  return (
    <div
      role="group"
      aria-label={`${label}: ${value}`}
      title={tooltip || undefined}
      className={`rounded-xl bg-slate-900/80 border border-slate-800/80 p-3.5 sm:p-4 flex flex-col justify-between transition-all duration-150 hover:border-slate-700 shadow-sm ${className}`}
    >
      {/* Label */}
      <div className="flex items-center justify-between text-xs font-medium text-slate-400 mb-1.5">
        <span>{label}</span>
        {tooltip && (
          <span
            className="cursor-help text-slate-500 hover:text-slate-300 text-[10px]"
            aria-hidden="true"
          >
            ⓘ
          </span>
        )}
      </div>

      {/* Primary Value */}
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-lg sm:text-xl font-bold font-mono tracking-tight text-slate-100">
          {value !== null && value !== undefined ? (
            <>
              {value}
              {unit && <span className="text-xs font-normal text-slate-400 ml-1">{unit}</span>}
            </>
          ) : (
            <span className="text-slate-500 font-sans text-sm font-normal">Unavailable</span>
          )}
        </div>

        {/* Change Badge */}
        {(change !== null || changePct !== null) && (
          <div
            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-mono font-medium border ${currentTheme.badge}`}
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
      {subtext && <div className="text-[11px] text-slate-500 mt-1.5">{subtext}</div>}
    </div>
  )
}
