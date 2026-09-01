/**
 * ProxyDisclosure — P0-A Truthful Data Envelope
 * Renders a persistent disclosure banner/tooltip for yfinance-derived
 * global and commodity values. Prevents users from treating a COMEX/NYMEX
 * proxy as their actual tradable MCX price.
 *
 * Per AGENTS.md §4.5: Any global/commodity value from yfinance must show:
 *   - source_type: derived_proxy
 *   - Actual source ticker and venue
 *   - FX source and FX as-of timestamp
 *   - tradable: false when not the user's actual tradable instrument
 *
 * @param {object} props
 * @param {string} [props.sourceTicker]       — e.g. "GC=F"
 * @param {string} [props.sourceVenue]        — e.g. "COMEX"
 * @param {string} [props.targetInstrument]   — e.g. "MCX:GOLD"
 * @param {string} [props.conversionFormula]  — e.g. "× USDINR × (10 / 31.1034768)"
 * @param {string} [props.fxPair]             — e.g. "USD/INR"
 * @param {number} [props.fxRate]             — e.g. 84.23
 * @param {string} [props.fxAsOf]             — ISO-8601 FX timestamp
 * @param {'banner'|'badge'|'tooltip'} [props.variant]
 * @param {string} [props.className]
 */
export default function ProxyDisclosure({
  sourceTicker,
  sourceVenue,
  targetInstrument,
  conversionFormula,
  fxPair,
  fxRate,
  fxAsOf,
  variant = 'banner',
  className = '',
}) {
  if (variant === 'badge') {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold
          bg-violet-500/15 border border-violet-500/30 text-violet-400 ${className}`}
        title={buildTooltipText({ sourceTicker, sourceVenue, targetInstrument, conversionFormula, fxPair, fxRate })}
        aria-label={`Research proxy: sourced from ${sourceVenue ?? 'external exchange'}, not your tradable ${targetInstrument ?? 'instrument'}`}
      >
        ⟳ PROXY
      </span>
    )
  }

  // Default: banner variant
  return (
    <div
      className={`rounded-lg p-2.5 border text-[10px] font-ui leading-relaxed
        bg-violet-500/8 border-violet-500/25 text-violet-300 ${className}`}
      role="note"
      aria-label="Proxy data disclosure"
    >
      <div className="flex items-start gap-2">
        <span className="text-[13px] flex-shrink-0 mt-0.5" aria-hidden="true">⟳</span>
        <div className="space-y-1">
          <div className="font-bold text-violet-300">
            Research Proxy — Not Your Tradable Price
          </div>
          <div className="opacity-80">
            {sourceTicker && sourceVenue
              ? `Sourced from ${sourceTicker} on ${sourceVenue}`
              : 'Sourced from an external exchange'}
            {targetInstrument && ` as a reference proxy for ${targetInstrument}`}.
            {' '}This value may differ from the actual{' '}
            {targetInstrument ? targetInstrument.split(':')[0] : 'exchange'} quote
            due to contract differences, expiry basis, and settlement methodology.
          </div>
          {conversionFormula && (
            <div className="opacity-60 font-mono text-[9px]">
              Conversion: {conversionFormula}
              {fxPair && fxRate ? ` using ${fxPair} @ ${fxRate.toFixed(4)}` : ''}
              {fxAsOf ? ` (FX as of ${formatFxAsOf(fxAsOf)})` : ''}
            </div>
          )}
          <div className="font-bold text-amber-400 text-[9px]">
            ⚠ Do not use this price for order placement on {targetInstrument?.split(':')[0] ?? 'MCX'}.
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function buildTooltipText({ sourceTicker, sourceVenue, targetInstrument, conversionFormula, fxPair, fxRate }) {
  const parts = []
  if (sourceTicker && sourceVenue) parts.push(`Source: ${sourceTicker} on ${sourceVenue}`)
  if (targetInstrument) parts.push(`Proxy for: ${targetInstrument}`)
  if (conversionFormula) parts.push(`Conversion: ${conversionFormula}`)
  if (fxPair && fxRate) parts.push(`FX: ${fxPair} @ ${fxRate}`)
  parts.push('NOT tradable on target exchange')
  return parts.join(' | ')
}

function formatFxAsOf(isoString) {
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return isoString
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }) + ' IST'
  } catch {
    return isoString
  }
}
