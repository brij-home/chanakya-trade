import { useState, useEffect } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { useMarketClock } from '../../hooks/useMarketClock'
import SmartTypeahead from '../Common/SmartTypeahead'
import { fuzzySearchUniverse } from '../../data/universeData'

/**
 * MarketClock — IST clock + market open/close countdown ring
 */
export function MarketClock() {
  const [time, setTime] = useState(() => new Date())
  const { status } = useMarketClock()

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const istStr = time.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })

  const statusColor = {
    open: 'var(--color-emerald)',
    'pre-open': 'var(--color-gold)',
    'post-close': 'var(--color-gold)',
    closed: 'var(--color-subtle)',
  }[status] ?? 'var(--color-subtle)'

  const statusLabel = {
    open: '● LIVE',
    'pre-open': '◐ PRE',
    'post-close': '◑ POST',
    closed: '○ CLOSED',
  }[status] ?? '○'

  return (
    <div
      className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-xl no-drag"
      style={{
        background: 'var(--color-elevated)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex flex-col items-end">
        <span
          className="text-[9px] font-bold tracking-widest font-mono"
          style={{ color: statusColor }}
        >
          {statusLabel}
        </span>
        <span className="text-xs font-mono font-semibold" style={{ color: 'var(--color-text)' }}>
          {istStr}
          <span className="text-[9px] text-muted ml-1">IST</span>
        </span>
      </div>
    </div>
  )
}

/**
 * LiveIndexTicker — compact NIFTY / BankNifty strip
 */
export function LiveIndexTicker() {
  const { nifty, status } = useMarketClock()
  const [bnifty] = useState(57496)

  const indices = [
    { label: 'NIFTY', value: nifty || 24175, change: 0.45 },
    { label: 'BKNIFTY', value: bnifty, change: 0.62 },
  ]

  return (
    <div className="hidden lg:flex items-center gap-3 no-drag">
      {indices.map((idx) => (
        <div key={idx.label} className="flex items-center gap-1.5">
          <span
            className="text-[9px] font-bold tracking-wider"
            style={{ color: 'var(--color-subtle)' }}
          >
            {idx.label}
          </span>
          <span
            className="text-xs font-mono font-bold tabular-nums"
            style={{ color: 'var(--color-text)' }}
          >
            {Number(idx.value).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </span>
          <span
            className="text-[10px] font-semibold font-mono tabular-nums"
            style={{ color: idx.change >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}
          >
            {idx.change >= 0 ? '+' : ''}{idx.change.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  )
}

/**
 * ContextBar — tier-2 context-sensitive action bar
 * Shows below the main nav bar for Terminal/Debate/Options views.
 * Provides: symbol search, timeframe, layout, quick analytics strip.
 */
export default function ContextBar({
  selectedSymbol,
  onSymbolChange,
  timeframe,
  onTimeframeChange,
  layoutMode,
  onLayoutChange,
}) {
  const { activeView } = useChatStore()
  const [searchQuery, setSearchQuery] = useState('')
  const [showTypeahead, setShowTypeahead] = useState(false)
  const [typeaheadIdx, setTypeaheadIdx] = useState(0)

  // Only render for data-heavy views
  if (!['terminal', 'debate', 'options'].includes(activeView)) return null

  const timeframes = ['5m', '15m', '1h', '4h', '1D', 'W']
  const layouts = [
    { id: 'single', icon: '▣', label: 'Single' },
    { id: 'dual',   icon: '▤', label: 'Dual-TF' },
    { id: 'whales', icon: '🐋', label: 'Whales' },
    { id: 'accuracy', icon: '🏆', label: 'Accuracy' },
  ]

  return (
    <div
      className="no-drag flex items-center gap-2.5 px-3 py-1.5 border-b flex-shrink-0 flex-wrap"
      style={{
        background: 'var(--color-surface)',
        borderColor: 'var(--color-border-subtle)',
        minHeight: '36px',
      }}
    >
      {/* Symbol Quick-Switcher */}
      <div className="relative z-50 flex-shrink-0">
        <div
          className="flex items-center gap-2 px-2.5 py-1 rounded-xl text-xs transition-all"
          style={{
            background: 'var(--color-elevated)',
            border: `1.5px solid ${searchQuery ? 'var(--color-gold)' : 'var(--color-border)'}`,
            boxShadow: searchQuery ? '0 0 0 3px rgba(245,166,35,0.15)' : 'none',
          }}
        >
          <span style={{ color: 'var(--color-gold)', fontSize: '11px' }}>⌕</span>
          <input
            type="text"
            placeholder={selectedSymbol || 'Search symbol…'}
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value)
              setShowTypeahead(true)
              setTypeaheadIdx(0)
            }}
            onFocus={() => setShowTypeahead(true)}
            onKeyDown={(e) => {
              const items = fuzzySearchUniverse(searchQuery, selectedSymbol, 8).filter(r => r.type === 'symbol')
              if (e.key === 'ArrowDown') { e.preventDefault(); setTypeaheadIdx(p => (p+1) % Math.max(items.length,1)) }
              if (e.key === 'ArrowUp')   { e.preventDefault(); setTypeaheadIdx(p => (p-1+Math.max(items.length,1)) % Math.max(items.length,1)) }
              if (e.key === 'Enter' && items.length) {
                e.preventDefault()
                onSymbolChange?.(items[typeaheadIdx]?.symbol || items[0]?.symbol)
                setSearchQuery('')
                setShowTypeahead(false)
              }
              if (e.key === 'Escape') setShowTypeahead(false)
            }}
            className="w-28 bg-transparent font-mono font-bold uppercase outline-none text-xs"
            style={{ color: 'var(--color-text)' }}
          />
          <kbd
            className="hidden sm:inline-block text-[9px] px-1 py-0.5 rounded font-mono"
            style={{
              background: 'var(--color-panel)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-muted)',
            }}
          >
            /
          </kbd>
        </div>

        <SmartTypeahead
          query={searchQuery}
          activeSymbol={selectedSymbol}
          isOpen={showTypeahead && searchQuery.length > 0}
          onSelect={(item) => {
            onSymbolChange?.(item.symbol)
            setSearchQuery('')
            setShowTypeahead(false)
          }}
          onClose={() => setShowTypeahead(false)}
          mode="symbols_only"
          position="below"
          selectedIndex={typeaheadIdx}
          setSelectedIndex={setTypeaheadIdx}
        />
      </div>

      {/* Timeframe pills */}
      {onTimeframeChange && (
        <div
          className="flex items-center p-0.5 rounded-xl text-xs gap-px flex-shrink-0"
          style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)' }}
        >
          {timeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => onTimeframeChange(tf)}
              className="px-2 py-1 rounded-lg font-medium transition-all cursor-pointer"
              style={
                timeframe === tf
                  ? { background: 'var(--color-gold)', color: '#000', fontWeight: 800 }
                  : { color: 'var(--color-muted)' }
              }
            >
              {tf}
            </button>
          ))}
        </div>
      )}

      {/* Layout switcher */}
      {onLayoutChange && (
        <div
          className="flex items-center p-0.5 rounded-xl text-xs gap-px flex-shrink-0"
          style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)' }}
        >
          {layouts.map((l) => (
            <button
              key={l.id}
              onClick={() => onLayoutChange(l.id)}
              title={l.label}
              className="px-2 py-1 rounded-lg font-medium transition-all cursor-pointer"
              style={
                layoutMode === l.id
                  ? { background: 'var(--color-gold)', color: '#000', fontWeight: 800 }
                  : { color: 'var(--color-muted)' }
              }
            >
              {l.icon}
            </button>
          ))}
        </div>
      )}

      {/* Divider */}
      <div
        className="hidden md:block h-4 w-px flex-shrink-0"
        style={{ background: 'var(--color-border)' }}
      />

      {/* Key market metrics strip */}
      <LiveIndexTicker />
    </div>
  )
}
