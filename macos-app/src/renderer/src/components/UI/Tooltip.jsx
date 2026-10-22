import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useInspectorStore } from '../../store/inspectorStore'
import { METRIC_ENCYCLOPEDIA } from '../../data/metricEncyclopedia'

/**
 * Modern Institutional Tooltip Component
 * Rendered via React Portal with viewport-clamped positioning to prevent
 * scroll container clipping and 100% solid opacity to prevent text bleed.
 */
export default function Tooltip({
  children,
  content,
  title,
  decisionHelp,
  formula,
  metricKey,
  position = 'top',
  className = '',
}) {
  const [isVisible, setIsVisible] = useState(false)
  const [rect, setRect] = useState(null)
  const containerRef = useRef(null)
  const openInspector = useInspectorStore((s) => s.openInspector)
  const timeoutRef = useRef(null)

  // Auto-populate from METRIC_ENCYCLOPEDIA if metricKey provided
  const meta = (metricKey && METRIC_ENCYCLOPEDIA[metricKey]) || {}
  const displayTitle = title || meta.title
  const displayContent = content || meta.explanation
  const displayFormula = formula || meta.formula
  const displayGuide = decisionHelp || meta.institutionalGuide
  const displayCategory = meta.category
  const displayThresholds = meta.thresholds

  const handleMouseEnter = (e) => {
    const el = e.currentTarget
    timeoutRef.current = setTimeout(() => {
      if (el) {
        setRect(el.getBoundingClientRect())
      }
      setIsVisible(true)
    }, 120)
  }

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setIsVisible(false)
    setRect(null)
  }

  const handleClick = (e) => {
    if (metricKey) {
      e.stopPropagation()
      openInspector(metricKey)
    }
  }

  // Dismiss on any descendant scroll or window resize
  useEffect(() => {
    if (!isVisible) return
    const handleDismiss = () => {
      setIsVisible(false)
      setRect(null)
    }
    window.addEventListener('scroll', handleDismiss, true)
    window.addEventListener('resize', handleDismiss)
    return () => {
      window.removeEventListener('scroll', handleDismiss, true)
      window.removeEventListener('resize', handleDismiss)
    }
  }, [isVisible])

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  // Viewport-adaptive positioning
  const cardWidth = 320
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1920
  const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 1080

  const rectTop = rect ? (rect.top || 100) : 100
  const rectBottom = rect ? (rect.bottom || 140) : 140
  const rectLeft = rect ? (rect.left || 100) : 100
  const rectRight = rect ? (rect.right || 420) : 420

  const spaceBelow = viewportHeight - rectBottom
  const spaceAbove = rectTop

  let preferBelow
  if (position === 'bottom') {
    preferBelow = spaceBelow >= 200 || spaceBelow >= spaceAbove
  } else if (position === 'top') {
    preferBelow = spaceAbove < 200 && spaceBelow > spaceAbove
  } else {
    preferBelow = spaceBelow >= 220 || spaceBelow >= spaceAbove
  }

  const tooltipStyle = {
    position: 'fixed',
    width: `${cardWidth}px`,
    zIndex: 99999,
    backgroundColor: '#0d1527',
    boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.95), 0 0 0 1px rgba(51, 65, 85, 0.8)',
  }

  if (preferBelow) {
    const topPos = Math.max(12, Math.min(rectBottom + 6, viewportHeight - 120))
    tooltipStyle.top = `${Math.round(topPos)}px`
    tooltipStyle.maxHeight = `${Math.max(160, viewportHeight - topPos - 16)}px`
  } else {
    const bottomPos = Math.max(12, Math.min(viewportHeight - rectTop + 6, viewportHeight - 120))
    tooltipStyle.bottom = `${Math.round(bottomPos)}px`
    tooltipStyle.maxHeight = `${Math.max(160, rectTop - 18)}px`
  }

  const targetCenterX = (rectLeft + rectRight) / 2
  let leftPos = targetCenterX - (cardWidth / 2)
  leftPos = Math.max(16, Math.min(leftPos, viewportWidth - cardWidth - 16))
  tooltipStyle.left = `${Math.round(leftPos)}px`

  const tooltipPortal = isVisible && (displayTitle || displayContent || displayGuide) && typeof document !== 'undefined'
    ? createPortal(
        <div
          role="tooltip"
          className="pointer-events-none p-3.5 rounded-xl border border-slate-700/80 text-left font-ui animate-in fade-in zoom-in-95 duration-150 overflow-y-auto"
          style={tooltipStyle}
        >
          {/* Header */}
          {(displayTitle || displayCategory) && (
            <div className="flex items-center justify-between gap-1.5 border-b border-slate-700/70 pb-2 mb-2">
              <div className="flex items-center gap-1.5 min-w-0">
                {displayCategory && (
                  <span className="text-[10px] uppercase font-mono font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/25 shrink-0">
                    {displayCategory}
                  </span>
                )}
                {displayTitle && (
                  <span className="text-xs font-bold text-slate-100 truncate">
                    {displayTitle}
                  </span>
                )}
              </div>
              {metricKey && (
                <span className="text-[10px] bg-emerald-500/15 text-emerald-300 px-1.5 py-0.5 rounded font-mono font-bold shrink-0 border border-emerald-500/30">
                  Inspect ↗
                </span>
              )}
            </div>
          )}

          {/* Description (Plain English) */}
          {displayContent && (
            <p className="text-[11px] text-slate-300 leading-relaxed font-ui mb-2">
              {displayContent}
            </p>
          )}

          {/* Actionable Decision Guidance ("🎯 How It Helps You Decide") */}
          {displayGuide && (
            <div className="mt-2 p-2.5 rounded-lg bg-emerald-950/60 border border-emerald-500/30 text-[10.5px] text-emerald-300 font-ui leading-tight">
              <div className="flex items-center gap-1 font-bold text-[11px] uppercase tracking-wider text-emerald-400 mb-1">
                <span>🎯</span>
                <span>How It Helps You Decide:</span>
              </div>
              <p className="font-normal leading-relaxed text-emerald-200">
                {displayGuide}
              </p>
            </div>
          )}

          {/* Key Thresholds Preview (if available) */}
          {displayThresholds && displayThresholds.length > 0 && (
            <div className="mt-2 space-y-1">
              <span className="text-[10px] uppercase font-bold text-slate-400 font-mono tracking-wider block">
                Rule of Thumb:
              </span>
              <div className="flex flex-wrap gap-1">
                {displayThresholds.slice(0, 3).map((t, idx) => (
                  <span
                    key={idx}
                    className={`text-[11px] font-mono px-1.5 py-0.5 rounded border ${
                      t.color === 'green'
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                        : t.color === 'red'
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/40'
                        : 'bg-amber-500/15 text-amber-300 border-amber-500/40'
                    }`}
                  >
                    {t.condition}: <strong>{t.label}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Formula preview */}
          {displayFormula && (
            <div className="mt-2 p-2 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-amber-400 overflow-x-auto whitespace-pre">
              {displayFormula}
            </div>
          )}

          {/* Bottom Hint */}
          {metricKey && (
            <div className="mt-2 pt-1.5 border-t border-slate-700/60 flex items-center justify-between text-[11px] text-slate-400 font-ui">
              <span>💡 Click to inspect model & variables</span>
              <span className="text-emerald-400 font-bold">➔</span>
            </div>
          )}
        </div>,
        document.body
      )
    : null

  return (
    <div
      ref={containerRef}
      className={`relative inline-flex items-center ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      {children}
      {tooltipPortal}
    </div>
  )
}

/**
 * Reusable InfoBadge icon for placing next to labels or metrics
 */
export function InfoBadge({ title, content, metricKey, formula, decisionHelp, className = '' }) {
  const openInspector = useInspectorStore((s) => s.openInspector)

  return (
    <Tooltip
      title={title}
      content={content}
      metricKey={metricKey}
      formula={formula}
      decisionHelp={decisionHelp}
    >
      <button
        type="button"
        aria-label={title || 'Click for deep explanation'}
        onClick={(e) => {
          e.stopPropagation()
          if (metricKey) openInspector(metricKey)
        }}
        className={`inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-elevated hover:bg-amber-500/20 text-muted hover:text-amber-500 text-[10px] font-mono border border-border/60 transition-colors cursor-pointer ${className}`}
        title="Click for deep explanation"
      >
        ℹ
      </button>
    </Tooltip>
  )
}

/**
 * Compact, lightweight HelpHint icon for column headers, badge chips, and labels.
 * Hover shows plain English explanation & decision takeaway.
 * Click opens full institutional model in MetricExplainerModal.
 */
export function HelpHint({
  metricKey,
  title,
  content,
  decisionHelp,
  formula,
  position = 'top',
  size = 'sm', // 'xs' | 'sm' | 'md'
  className = '',
  icon = '?',
}) {
  const openInspector = useInspectorStore((s) => s.openInspector)
  const sizeClasses = {
    xs: 'w-3 h-3 text-[10px]',
    sm: 'w-3.5 h-3.5 text-[11px]',
    md: 'w-4 h-4 text-[10px]',
  }[size] || 'w-3.5 h-3.5 text-[11px]'

  return (
    <Tooltip
      metricKey={metricKey}
      title={title}
      content={content}
      decisionHelp={decisionHelp}
      formula={formula}
      position={position}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          if (metricKey) openInspector(metricKey)
        }}
        className={`inline-flex items-center justify-center rounded-full bg-black/5 dark:bg-white/10 hover:bg-amber-500/20 text-muted hover:text-amber-500 dark:hover:text-amber-400 border border-border/60 hover:border-amber-500/40 font-mono font-bold transition-all cursor-pointer shadow-2xs select-none shrink-0 ${sizeClasses} ${className}`}
        aria-label={title || metricKey || 'Help hint'}
        title="Hover to understand • Click for model"
      >
        {icon}
      </button>
    </Tooltip>
  )
}
