import { useState, useEffect } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { useMarketClock } from '../../hooks/useMarketClock'
import { useAPI } from '../../hooks/useAPI'
import SmartTypeahead from '../Common/SmartTypeahead'
import { fuzzySearchUniverse } from '../../data/universeData'

/**
 * HorizonSwitcher — Global Intraday vs Swing context toggle pill
 */
export function MarketDynamicsPill() {
  const port = useChatStore((s) => s.port)
  const sidecarError = useChatStore((s) => s.sidecarError)
  const setActiveView = useChatStore((s) => s.setActiveView)
  const [dyn, setDyn] = useState(null)
  const [indicators, setIndicators] = useState(null)

  useEffect(() => {
    if (!port || sidecarError) return
    let active = true
    const fetchDyn = async () => {
      try {
        const [resDyn, resInd] = await Promise.allSettled([
          fetch(`${getBaseUrl(port)}/api/market/dynamics?symbol=NIFTY`, {
            signal: AbortSignal.timeout(3000),
          }),
          fetch(`${getBaseUrl(port)}/api/market/indicators?symbol=NIFTY`, {
            signal: AbortSignal.timeout(3000),
          }),
        ])
        if (active) {
          if (resDyn.status === 'fulfilled' && resDyn.value.ok) {
            setDyn(await resDyn.value.json())
          }
          if (resInd.status === 'fulfilled' && resInd.value.ok) {
            const indJson = await resInd.value.json()
            setIndicators(indJson?.indicators || null)
          }
        }
      } catch (_) {}
    }
    fetchDyn()
    const interval = setInterval(fetchDyn, 10000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [port, sidecarError])

  if (!dyn) return null

  const phase = dyn.current_phase || 'OFF_MARKET'
  const vix = dyn.india_vix || 14.0

  const phaseLabels = {
    OPENING_AUCTION_DISCOVERY: '🌅 DISCOVERY',
    MORNING_INSTITUTIONAL_EXPANSION: '🚀 EXPANSION',
    MIDDAY_MEAN_REVERSION_CHOP: '⚖️ CHOP',
    AFTERNOON_TREND_IGNITION: '⚡ IGNITION',
    EXPIRY_0DTE_GAMMA_UNPIN: '💥 GAMMA',
    SESSION_MOC_HARDBOARD_CUTOFF: '🛑 MOC',
    OFF_MARKET_POSTCLOSE: '🌙 POST-CLOSE',
    OFF_MARKET_PREOPEN: '⏳ PRE-OPEN',
  }

  const phaseColor = phase.includes('CHOP')
    ? 'var(--color-amber)'
    : phase.includes('CUTOFF') || phase.includes('OFF')
    ? 'var(--color-subtle)'
    : 'var(--color-emerald)'

  const basis = indicators?.futures_basis
  const cpr = indicators?.cpr_regime ? indicators.cpr_regime.replace('_CPR', '') : null

  return (
    <button
      type="button"
      onClick={() => setActiveView('opsdeck')}
      className="flex items-center gap-1.5 px-2 py-0.5 rounded-lg text-[10px] font-mono font-bold border transition-all cursor-pointer select-none no-drag"
      style={{
        background: 'rgba(255,255,255,0.03)',
        borderColor: 'var(--color-border)',
        color: phaseColor,
      }}
      title={`Market Dynamics: ${phase} | VIX: ${vix.toFixed(1)}${cpr ? ` | CPR: ${cpr}` : ''}${indicators?.atr_daily ? ` | ATR: ${indicators.atr_daily.toFixed(1)}` : ''}${basis != null ? ` | Fut Basis: ${basis > 0 ? '+' : ''}${basis.toFixed(1)} pts` : ''} (Click to open OpsDeck Dynamics matrix)`}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: phaseColor }} />
      <span>{phaseLabels[phase] || phase}</span>
      <span className="text-muted">|</span>
      <span className="text-text font-bold">VIX {vix.toFixed(1)}</span>
      {cpr && (
        <>
          <span className="text-muted">|</span>
          <span className="text-amber/90 font-bold" title={`Daily CPR: ${indicators.cpr_regime}`}>
            CPR {cpr}
          </span>
        </>
      )}
      {basis != null && (
        <>
          <span className="text-muted">|</span>
          <span
            className={basis >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}
            title={`Nifty Near-Month Futures Basis (${basis > 0 ? '+' : ''}${basis.toFixed(1)} pts)`}
          >
            Basis {basis > 0 ? '+' : ''}{Math.round(basis)}
          </span>
        </>
      )}
    </button>
  )
}

export function HorizonSwitcher() {
  const { horizon, toggleHorizon } = useChatStore()
  const isIntraday = horizon === 'INTRADAY'

  return (
    <button
      type="button"
      onClick={toggleHorizon}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-mono font-bold transition-all cursor-pointer select-none no-drag"
      style={{
        background: isIntraday ? 'rgba(245, 166, 35, 0.12)' : 'rgba(74, 144, 226, 0.12)',
        border: `1.5px solid ${isIntraday ? 'rgba(245, 166, 35, 0.45)' : 'rgba(74, 144, 226, 0.45)'}`,
        color: isIntraday ? 'var(--color-gold)' : 'var(--color-sapphire)',
        boxShadow: isIntraday ? '0 0 10px rgba(245, 166, 35, 0.15)' : '0 0 10px rgba(74, 144, 226, 0.15)',
      }}
      title={`Trading Horizon: ${horizon} — Click to switch between Intraday Scalp and Swing/Positional context`}
      aria-label={`Trading Horizon: ${horizon}`}
    >
      <span className="text-xs">{isIntraday ? '⚡' : '📈'}</span>
      <span className="tracking-wider">{horizon}</span>
    </button>
  )
}

/**
 * MarketClock — IST clock + market open/close countdown ring + Dalal Street milestones
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

  // Dynamic Dalal Street Milestone Countdown
  const getMilestoneInfo = () => {
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Kolkata',
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
        hour12: false,
      }).formatToParts(time)
      const h = parseInt(parts.find((p) => p.type === 'hour')?.value ?? '0', 10)
      const m = parseInt(parts.find((p) => p.type === 'minute')?.value ?? '0', 10)
      const totalMinutes = h * 60 + m

      // 09:15 to 14:45 IST: Intraday MIS trading open, countdown to 14:45 MIS cutoff
      if (totalMinutes >= 555 && totalMinutes < 885) {
        const diff = 885 - totalMinutes
        const hrs = Math.floor(diff / 60)
        const mins = diff % 60
        return {
          text: `⏳ ${hrs > 0 ? `${hrs}h ` : ''}${mins}m to MIS Cutoff`,
          color: diff <= 30 ? 'var(--color-gold)' : 'var(--color-muted)',
        }
      }
      // 14:45 to 15:30 IST: MIS squared off, countdown to 15:30 Cash close
      if (totalMinutes >= 885 && totalMinutes < 930) {
        const diff = 930 - totalMinutes
        return {
          text: `⚠️ MIS SQUARED · ${diff}m to Cash Close`,
          color: 'var(--color-gold)',
        }
      }
      // 15:30 to 23:30 IST: Cash closed, MCX open
      if (totalMinutes >= 930 && totalMinutes < 1410) {
        return {
          text: '🌙 Cash Closed · MCX Open',
          color: 'var(--color-subtle)',
        }
      }
      return {
        text: '○ Markets Closed',
        color: 'var(--color-subtle)',
      }
    } catch {
      return null
    }
  }

  const milestone = getMilestoneInfo()

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
      className="hidden md:flex items-center gap-2 px-3 py-1 rounded-xl no-drag"
      style={{
        background: 'var(--color-elevated)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex flex-col items-end leading-tight">
        <div className="flex items-center gap-1.5">
          <span
            className="text-[11px] font-bold tracking-widest font-mono"
            style={{ color: statusColor }}
          >
            {statusLabel}
          </span>
          <span className="text-xs font-mono font-semibold" style={{ color: 'var(--color-text)' }}>
            {istStr}
            <span className="text-[10px] text-muted ml-1">IST</span>
          </span>
        </div>
        {milestone && (
          <span
            className="text-[9px] font-mono tracking-tight font-medium"
            style={{ color: milestone.color }}
          >
            {milestone.text}
          </span>
        )}
      </div>
    </div>
  )
}

import { useRealtimeMarket } from '../../hooks/useRealtimeMarket'
import { formatLivePrice, formatLiveChange } from '../../utils/marketDataUtils'

/**
 * LiveIndexTicker — dynamic real-time ticker strip for Indices, Commodities & Crypto
 */
export function LiveIndexTicker({ onSymbolChange }) {
  const { tickers, connectionState } = useRealtimeMarket()

  // Curated multi-asset indices, commodities & crypto for quick reference
  const targetSymbols = [
    'NIFTY',
    'BANKNIFTY',
    'INDIA VIX',
    'CRUDEOIL',
    'NATURALGAS',
    'GOLD',
    'SILVER',
    'BTC',
    'ETH',
    'SOL',
  ]
  const displayItems = tickers.filter((t) => targetSymbols.includes(t.symbol))

  if (displayItems.length === 0) {
    return (
      <div className="hidden md:flex items-center gap-2 no-drag font-mono text-[10px]" style={{ color: 'var(--color-subtle)' }}>
        <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: connectionState === 'live' ? 'var(--color-emerald)' : 'var(--color-gold)' }} />
        <span>{connectionState === 'live' ? 'Awaiting ticks...' : 'Connecting live market feed...'}</span>
      </div>
    )
  }

  return (
    <div className="hidden md:flex items-center gap-2 no-drag overflow-x-auto no-scrollbar max-w-[800px]">
      {displayItems.map((idx) => {
        const rawPrice = idx.ltp != null ? idx.ltp : idx.price
        const changeObj = formatLiveChange(idx.change, idx.change_pct)
        const isUp = (idx.direction === 'up') || (idx.change_pct > 0) || changeObj.isPositive
        const isDown = (idx.direction === 'down') || (idx.change_pct < 0) || (changeObj.direction === 'down')
        const changeColor = isUp ? 'var(--color-emerald)' : isDown ? 'var(--color-rose)' : 'var(--color-subtle)'

        return (
          <button
            key={idx.symbol}
            onClick={() => onSymbolChange?.(idx.symbol)}
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-lg hover:bg-elevated/90 transition-all cursor-pointer text-left flex-shrink-0"
            title={`Switch view to ${idx.display_name || idx.symbol}`}
          >
            <span
              className="text-[11px] font-bold tracking-wider font-mono"
              style={{ color: 'var(--color-subtle)' }}
            >
              {idx.display_name?.replace(' 50', '') || idx.symbol}
            </span>
            <span
              className="text-xs font-mono font-bold tabular-nums"
              style={{ color: 'var(--color-text)' }}
            >
              {formatLivePrice(rawPrice, idx.unit || '₹')}
            </span>
            <span
              className="text-[10px] font-semibold font-mono tabular-nums"
              style={{ color: changeColor }}
            >
              {changeObj.pctText}
            </span>
          </button>
        )
      })}
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
  const { activeView, terminalShowChart, toggleTerminalShowChart } = useChatStore()
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

  // Candlestick timeframes and multi-pane layouts only belong to charting views
  const viewsWithTimeframe = ['charts']
  const viewsWithLayout = ['charts']

  return (
    <div
      className="no-drag flex items-center gap-2 px-3 py-1 border-b flex-shrink-0 flex-wrap"
      style={{
        background: 'var(--color-surface)',
        borderColor: 'var(--color-border-subtle)',
        minHeight: '32px',
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
            className="hidden sm:inline-block text-[11px] px-1 py-0.5 rounded font-mono"
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

      {/* Horizon Switcher (Intraday vs Swing) */}
      <HorizonSwitcher />
      <MarketDynamicsPill />

      {/* Relevant View Badges & Quick Action Links */}
      {activeView === 'options' && (
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-amber/15 text-amber border border-amber/30">
            Options Desk
          </span>
          <button
            type="button"
            onClick={() => useChatStore.getState().setActiveView('charts')}
            className="hidden sm:flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold font-mono text-muted hover:text-amber border border-border/70 hover:border-amber/40 bg-elevated transition-colors cursor-pointer"
            title={`Open ${selectedSymbol || 'Symbol'} Candlestick Chart in Chart Studio`}
          >
            <span>📈</span>
            <span>Chart Studio ↗</span>
          </button>
          <button
            type="button"
            onClick={() => {
              useChatStore.getState().sendDraft?.(`analyze ${selectedSymbol || 'NIFTY'}`)
              useChatStore.getState().setActiveView('debate')
            }}
            className="hidden md:flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold font-mono text-muted hover:text-cyan-400 border border-border/70 hover:border-cyan-500/40 bg-elevated transition-colors cursor-pointer"
            title={`Analyze ${selectedSymbol || 'Symbol'} with AI Bull/Bear Councils`}
          >
            <span>⚔️</span>
            <span>AI Debate</span>
          </button>
        </div>
      )}

      {activeView === 'debate' && (
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
            AI Debate Arena
          </span>
          <button
            type="button"
            onClick={() => useChatStore.getState().setActiveView('options')}
            className="hidden sm:flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold font-mono text-muted hover:text-amber border border-border/70 hover:border-amber/40 bg-elevated transition-colors cursor-pointer"
            title={`Open ${selectedSymbol || 'Symbol'} Option Chain & Greeks`}
          >
            <span>⚡</span>
            <span>Options Desk ↗</span>
          </button>
        </div>
      )}

      {/* Timeframe pills — ONLY shown for dedicated charting views that require candle intervals */}
      {viewsWithTimeframe.includes(activeView) && onTimeframeChange && (
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

      {/* Layout switcher — ONLY for dedicated charting views with multi-pane layouts */}
      {viewsWithLayout.includes(activeView) && onLayoutChange && (
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
    </div>
  )
}
