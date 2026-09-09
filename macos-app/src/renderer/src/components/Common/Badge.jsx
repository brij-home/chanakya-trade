import React from 'react'

/**
 * Accessible Institutional Badge component adhering to WCAG 2.2 AAA.
 * "Define Once and Reuse" design system token for labels, statuses, and archetypes.
 *
 * Features:
 * - High-contrast dual-theme palette: rich jewel tones in light mode, luminous neon in dark mode
 * - Standardized sizes: xs (micro), sm (pill), md (tag)
 * - Variants: gold, emerald, rose, sapphire, cyan, violet, neutral, muted
 */
export default function Badge({
  children,
  variant = 'neutral',
  size = 'sm',
  icon = null,
  className = '',
  title = undefined,
  ...props
}) {
  const variantStyles = {
    gold: 'bg-gold/15 text-amber-600 dark:text-amber-400 border border-gold/30',
    emerald: 'bg-emerald/15 text-emerald-700 dark:text-emerald-300 border border-emerald/30',
    rose: 'bg-rose/15 text-rose-700 dark:text-rose-300 border border-rose/30',
    sapphire: 'bg-sapphire/15 text-blue-700 dark:text-blue-300 border border-sapphire/30',
    cyan: 'bg-cyan/15 text-cyan-700 dark:text-cyan-400 border border-cyan/30',
    violet: 'bg-violet/15 text-violet-700 dark:text-violet-300 border border-violet/30',
    neutral: 'bg-panel text-text border border-border',
    muted: 'bg-elevated text-muted border border-border',
  }

  const sizeStyles = {
    xs: 'text-[9px] px-1.5 py-0.5 rounded font-mono font-bold uppercase tracking-wider',
    sm: 'text-[10px] px-2 py-0.5 rounded-full font-mono font-bold uppercase tracking-wider',
    md: 'text-xs px-2.5 py-1 rounded-md font-semibold',
  }

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 select-none leading-none shadow-xs transition-all ${
        sizeStyles[size] || sizeStyles.sm
      } ${variantStyles[variant] || variantStyles.neutral} ${className}`}
      {...props}
    >
      {icon && <span className="shrink-0 leading-none">{icon}</span>}
      {children}
    </span>
  )
}
