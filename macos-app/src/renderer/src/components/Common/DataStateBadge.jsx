/**
 * DataStateBadge — P0-A Truthful Data Envelope
 * Renders a status pill showing data quality, source, and freshness.
 * Never show a blank where data is missing; show this badge instead.
 *
 * @param {object} props
 * @param {'live'|'delayed'|'cached_fresh'|'stale'|'derived_proxy'|'estimated'|'unavailable'|'demo'} props.status
 * @param {string} [props.sourceName]    — e.g. "yfinance (COMEX proxy)"
 * @param {string} [props.asOf]          — ISO-8601 timestamp string
 * @param {boolean} [props.tradable]     — false = show non-tradable warning
 * @param {boolean} [props.compact]      — slim pill without label text
 * @param {string} [props.className]
 */
export default function DataStateBadge({
  status = 'unavailable',
  sourceName,
  asOf,
  tradable,
  compact = false,
  className = '',
}) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.unavailable

  // Format as-of timestamp as relative time (e.g. "2m ago") or HH:MM IST
  const asOfLabel = asOf ? formatAsOf(asOf) : null

  if (compact) {
    return (
      <span
        role="status"
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold border ${cfg.classes} ${className}`}
        title={[cfg.label, sourceName, asOf].filter(Boolean).join(' | ')}
        aria-label={`Data status: ${cfg.label}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotClass}`} aria-hidden="true" />
        {cfg.abbrev}
      </span>
    )
  }

  return (
    <span
      role="status"
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold border ${cfg.classes} ${className}`}
      aria-label={`Data status: ${cfg.label}${sourceName ? `, source: ${sourceName}` : ''}${asOfLabel ? `, as of: ${asOfLabel}` : ''}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cfg.dotClass}`} aria-hidden="true" />
      <span>{cfg.label}</span>
      {asOfLabel && (
        <span className="opacity-70">· {asOfLabel}</span>
      )}
      {tradable === false && (
        <span
          className="ml-0.5 px-1 py-px rounded bg-amber-500/20 border border-amber-500/40 text-amber-400 text-[8px] font-bold"
          title="This value is a proxy and is NOT your tradable instrument price"
        >
          NON-TRADABLE
        </span>
      )}
    </span>
  )
}

// ── Configuration ──────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  live: {
    label: 'Live',
    abbrev: 'L',
    classes: 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400',
    dotClass: 'bg-emerald-400 animate-pulse',
  },
  delayed: {
    label: 'Delayed',
    abbrev: 'D',
    classes: 'bg-amber-500/15 border-amber-500/30 text-amber-400',
    dotClass: 'bg-amber-400',
  },
  cached_fresh: {
    label: 'Cached',
    abbrev: 'C',
    classes: 'bg-sky-500/15 border-sky-500/30 text-sky-400',
    dotClass: 'bg-sky-400',
  },
  stale: {
    label: 'Stale',
    abbrev: 'S',
    classes: 'bg-orange-500/15 border-orange-500/30 text-orange-400',
    dotClass: 'bg-orange-400',
  },
  derived_proxy: {
    label: 'Proxy',
    abbrev: 'P',
    classes: 'bg-violet-500/15 border-violet-500/30 text-violet-400',
    dotClass: 'bg-violet-400',
  },
  estimated: {
    label: 'Estimated',
    abbrev: 'E',
    classes: 'bg-indigo-500/15 border-indigo-500/30 text-indigo-400',
    dotClass: 'bg-indigo-400',
  },
  unavailable: {
    label: 'Unavailable',
    abbrev: 'U',
    classes: 'bg-rose-500/10 border-rose-500/20 text-rose-400',
    dotClass: 'bg-rose-400',
  },
  demo: {
    label: 'Demo',
    abbrev: '✦',
    classes: 'bg-fuchsia-500/15 border-fuchsia-500/30 text-fuchsia-400',
    dotClass: 'bg-fuchsia-400 animate-pulse',
  },
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatAsOf(isoString) {
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return null
    const diffMs = Date.now() - d.getTime()
    const diffSec = Math.floor(diffMs / 1000)
    if (diffSec < 60) return `${diffSec}s ago`
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
  } catch {
    return null
  }
}
