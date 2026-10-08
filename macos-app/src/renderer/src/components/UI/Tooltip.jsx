import { useState, useRef, useEffect } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import { METRIC_ENCYCLOPEDIA } from '../../data/metricEncyclopedia'

/**
 * Modern Glassmorphic Tooltip Component
 * Displays rich hover information with title, plain-English description,
 * actionable decision guidance, formula, and click-to-explain deep dive.
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

  const handleMouseEnter = () => {
    timeoutRef.current = setTimeout(() => setIsVisible(true), 120)
  }

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setIsVisible(false)
  }

  const handleClick = (e) => {
    if (metricKey) {
      e.stopPropagation()
      openInspector(metricKey)
    }
  }

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }[position] || 'bottom-full left-1/2 -translate-x-1/2 mb-2'

  return (
    <div
      className={`relative inline-flex items-center ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      {children}

      {isVisible && (displayTitle || displayContent || displayGuide) && (
        <div
          role="tooltip"
          className={`absolute z-50 w-72 sm:w-80 pointer-events-none p-3 rounded-xl bg-panel/95 backdrop-blur-md border border-border/90 shadow-2xl text-left font-ui ${positionClasses} animate-in fade-in zoom-in-95 duration-150`}
        >
          {/* Header */}
          {(displayTitle || displayCategory) && (
            <div className="flex items-center justify-between gap-1.5 border-b border-border/50 pb-1.5 mb-2">
              <div className="flex items-center gap-1.5 min-w-0">
                {displayCategory && (
                  <span className="text-[8.5px] uppercase font-mono font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/25 shrink-0">
                    {displayCategory}
                  </span>
                )}
                {displayTitle && (
                  <span className="text-xs font-bold text-text truncate">
                    {displayTitle}
                  </span>
                )}
              </div>
              {metricKey && (
                <span className="text-[8.5px] bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded font-mono font-bold shrink-0">
                  Inspect ↗
                </span>
              )}
            </div>
          )}

          {/* Description (Plain English) */}
          {displayContent && (
            <p className="text-[11px] text-muted leading-relaxed font-ui">
              {displayContent}
            </p>
          )}

          {/* Actionable Decision Guidance ("🎯 How It Helps You Decide") */}
          {displayGuide && (
            <div className="mt-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-[10.5px] text-emerald-600 dark:text-emerald-300 font-ui leading-tight">
              <div className="flex items-center gap-1 font-bold text-[9px] uppercase tracking-wider text-emerald-700 dark:text-emerald-300 mb-1">
                <span>🎯</span>
                <span>How It Helps You Decide:</span>
              </div>
              <p className="font-normal leading-relaxed text-emerald-800 dark:text-emerald-200">
                {displayGuide}
              </p>
            </div>
          )}

          {/* Key Thresholds Preview (if available) */}
          {displayThresholds && displayThresholds.length > 0 && (
            <div className="mt-2 space-y-1">
              <span className="text-[8.5px] uppercase font-bold text-muted font-mono tracking-wider block">
                Rule of Thumb:
              </span>
              <div className="flex flex-wrap gap-1">
                {displayThresholds.slice(0, 3).map((t, idx) => (
                  <span
                    key={idx}
                    className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${
                      t.color === 'green'
                        ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                        : t.color === 'red'
                        ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30'
                        : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30'
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
            <div className="mt-2 p-1.5 rounded bg-elevated/80 border border-border/50 text-[9.5px] font-mono text-amber-600 dark:text-amber-400/90 overflow-x-auto whitespace-pre">
              {displayFormula}
            </div>
          )}

          {/* Bottom Hint */}
          {metricKey && (
            <div className="mt-2 pt-1 border-t border-border/30 flex items-center justify-between text-[9.5px] text-muted font-ui">
              <span>💡 Click to inspect model & variables</span>
              <span className="text-emerald-500 font-bold">➔</span>
            </div>
          )}
        </div>
      )}
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
    xs: 'w-3 h-3 text-[8px]',
    sm: 'w-3.5 h-3.5 text-[9px]',
    md: 'w-4 h-4 text-[10px]',
  }[size] || 'w-3.5 h-3.5 text-[9px]'

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
