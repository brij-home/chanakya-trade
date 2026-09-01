/**
 * UnavailableState — P0-A Truthful Data Envelope
 * Renders an explicit, honest empty state when data cannot be fetched.
 * Replaces hardcoded fallback numbers with this component.
 * Never use invented data to populate a card — use this instead.
 *
 * @param {object} props
 * @param {string} [props.title]         — e.g. "India VIX unavailable"
 * @param {string} [props.reason]        — human-readable reason (no credentials)
 * @param {string} [props.hint]          — optional action hint (e.g. "Check connection")
 * @param {() => void} [props.onRetry]   — if provided, shows a Retry button
 * @param {'sm'|'md'|'lg'} [props.size]  — controls padding/font size
 * @param {string} [props.className]
 */
export default function UnavailableState({
  title = 'Data unavailable',
  reason,
  hint,
  onRetry,
  size = 'md',
  className = '',
}) {
  const sizeClasses = {
    sm: 'py-4 gap-1.5',
    md: 'py-8 gap-2',
    lg: 'py-12 gap-3',
  }[size] || 'py-8 gap-2'

  const iconSize = { sm: 'text-xl', md: 'text-3xl', lg: 'text-4xl' }[size]
  const titleSize = { sm: 'text-[11px]', md: 'text-xs', lg: 'text-sm' }[size]
  const bodySize = { sm: 'text-[10px]', md: 'text-[11px]', lg: 'text-xs' }[size]

  return (
    <div
      className={`flex flex-col items-center justify-center text-center ${sizeClasses} ${className}`}
      role="status"
      aria-live="polite"
      aria-label={title}
    >
      <span className={`${iconSize} opacity-40`} aria-hidden="true">⚠</span>
      <div className={`${titleSize} font-semibold`} style={{ color: 'var(--color-muted)' }}>
        {title}
      </div>
      {reason && (
        <div className={`${bodySize} opacity-60 max-w-xs leading-relaxed`} style={{ color: 'var(--color-muted)' }}>
          {reason}
        </div>
      )}
      {hint && (
        <div className={`${bodySize} opacity-50 italic`} style={{ color: 'var(--color-muted)' }}>
          {hint}
        </div>
      )}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 px-3 py-1 rounded-lg text-[11px] font-semibold border transition-all hover:opacity-80 active:scale-95"
          style={{
            background: 'var(--color-elevated)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-muted)',
          }}
          aria-label="Retry fetching data"
        >
          ↻ Retry
        </button>
      )}
    </div>
  )
}
