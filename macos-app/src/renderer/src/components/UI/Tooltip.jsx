import { useState, useRef, useEffect } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'

/**
 * Modern Glassmorphic Tooltip Component
 * Displays rich hover information with title, description, formula, and click-to-explain.
 */
export default function Tooltip({
  children,
  content,
  title,
  formula,
  metricKey,
  position = 'top',
  className = '',
}) {
  const [isVisible, setIsVisible] = useState(false)
  const openInspector = useInspectorStore((s) => s.openInspector)
  const timeoutRef = useRef(null)

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

      {isVisible && (
        <div
          role="tooltip"
          className={`absolute z-50 w-64 pointer-events-none p-3 rounded-xl bg-panel/95 backdrop-blur-md border border-border/90 shadow-2xl text-left font-ui ${positionClasses} animate-in fade-in zoom-in-95 duration-150`}
        >
          {/* Header */}
          {title && (
            <div className="flex items-center justify-between gap-2 border-b border-border/40 pb-1.5 mb-1.5">
              <span className="text-xs font-bold text-text truncate">{title}</span>
              {metricKey && (
                <span className="text-[9px] bg-amber/15 text-amber px-1.5 py-0.5 rounded font-mono font-semibold">
                  Click for formula
                </span>
              )}
            </div>
          )}

          {/* Description */}
          {content && (
            <p className="text-[11px] text-muted leading-relaxed font-ui">
              {content}
            </p>
          )}

          {/* Formula preview */}
          {formula && (
            <div className="mt-1.5 p-1.5 rounded bg-elevated/80 border border-border/50 text-[10px] font-mono text-amber/90 overflow-x-auto whitespace-pre">
              {formula}
            </div>
          )}

          {/* Bottom Hint */}
          {metricKey && (
            <div className="mt-2 pt-1 border-t border-border/30 flex items-center justify-between text-[10px] text-subtle font-ui">
              <span>💡 Click to inspect full model</span>
              <span className="text-amber">➔</span>
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
export function InfoBadge({ title, content, metricKey, formula, className = '' }) {
  const openInspector = useInspectorStore((s) => s.openInspector)

  return (
    <Tooltip title={title} content={content} metricKey={metricKey} formula={formula}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          if (metricKey) openInspector(metricKey)
        }}
        className={`inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-elevated hover:bg-amber/20 text-muted hover:text-amber text-[10px] font-mono border border-border/60 transition-colors cursor-pointer ${className}`}
        title="Click for deep explanation"
      >
        ℹ
      </button>
    </Tooltip>
  )
}
