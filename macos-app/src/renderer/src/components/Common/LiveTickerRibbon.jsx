import { useState, useRef } from 'react'
import { useRealtimeMarket } from '../../hooks/useRealtimeMarket'
import { formatLivePrice, formatLiveChange, classifyDataSource } from '../../utils/marketDataUtils'

/**
 * LiveTickerRibbon — High-density, institutional-grade real-time ticker ribbon
 * for Major Indian Indices (NIFTY, BANK NIFTY, SENSEX, FIN NIFTY, INDIA VIX),
 * MCX Commodities (CRUDE OIL, GOLD, SILVER), and Crypto (BITCOIN).
 *
 * Connected directly to useRealtimeMarket singleton SSOT stream.
 */
export default function LiveTickerRibbon({
  tickers: propTickers = null,
  selectedSymbol = 'NIFTY',
  onSelectSymbol = () => {},
  className = '',
}) {
  const {
    tickers: storeTickers,
    flashMap,
    connectionState,
    isRealtime,
    dataSource,
    lastUpdated,
    refresh,
  } = useRealtimeMarket()

  const [isRefreshing, setIsRefreshing] = useState(false)
  const scrollContainerRef = useRef(null)

  const tickers = (propTickers && propTickers.length > 0) ? propTickers : storeTickers
  const loading = tickers.length === 0
  const isStreaming = connectionState === 'live'

  const handleManualRefresh = () => {
    setIsRefreshing(true)
    refresh()
    setTimeout(() => setIsRefreshing(false), 500)
  }

  const scrollLeft = () => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollBy({ left: -260, behavior: 'smooth' })
    }
  }

  const scrollRight = () => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollBy({ left: 260, behavior: 'smooth' })
    }
  }

  const formatPrice = (val, unit) => {
    if (val === null || val === undefined || isNaN(val)) return '—'
    const num = Number(val)
    if (unit === '$') {
      return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    }
    if (unit === 'pts') {
      return `${num.toFixed(2)}`
    }
    return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }

  const getAssetCategoryIcon = (category, symbol) => {
    if (category === 'CRYPTO' || symbol === 'BTC') return '₿'
    if (category === 'COMMODITY') {
      if (symbol === 'CRUDEOIL') return '🛢️'
      if (symbol === 'GOLD') return '🪙'
      if (symbol === 'SILVER') return '🥈'
      return '📦'
    }
    if (category === 'VIX') return '⚡'
    if (symbol === 'BANKNIFTY') return '🏦'
    if (symbol === 'FINNIFTY') return '💳'
    return '🇮🇳'
  }

  return (
    <div
      className={`relative z-20 flex items-center gap-2 px-2 sm:px-2.5 py-1 rounded-xl select-none transition-all ${className}`}
      style={{
        background: 'var(--color-panel)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      {/* Live Streaming Indicator & Manual Refresh */}
      <div className="flex items-center gap-1.5 pl-0.5 pr-2 py-0.5 border-r flex-shrink-0" style={{ borderColor: 'var(--color-border-subtle)' }}>
        {isStreaming ? (
          <div className="flex items-center gap-1.5" title={`Real-time SSE Stream Connected • Updated ${lastUpdated ? lastUpdated.toLocaleTimeString() : 'now'}`}>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="text-[10px] font-extrabold tracking-wider font-mono uppercase hidden sm:inline" style={{ color: 'var(--color-emerald)' }}>
              LIVE
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5" title="Connecting to live SSE stream...">
            <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse"></span>
            <span className="text-[10px] font-bold tracking-wider font-mono uppercase hidden sm:inline text-amber-400">
              CONNECTING
            </span>
          </div>
        )}
        <button
          onClick={handleManualRefresh}
          className={`text-[11px] p-0.5 rounded text-muted hover:text-text transition-all cursor-pointer ${isRefreshing ? 'animate-spin text-amber' : ''}`}
          title="Manual refresh"
          aria-label="Refresh live tickers"
        >
          ↻
        </button>
      </div>

      {/* Left Scroll Navigation Button */}
      <button
        onClick={scrollLeft}
        className="hidden md:flex items-center justify-center w-5 h-5 rounded-md text-xs font-bold text-muted hover:text-text hover:bg-elevated transition-colors flex-shrink-0 cursor-pointer"
        aria-label="Scroll left"
      >
        ‹
      </button>

      {/* Scrollable Ribbon Container */}
      <div
        ref={scrollContainerRef}
        className="flex items-center gap-1.5 overflow-x-auto no-scrollbar scroll-smooth py-0.5 flex-1"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        {loading && tickers.length === 0 ? (
          <div className="flex items-center gap-2 py-0.5 px-2 text-xs text-muted font-mono animate-pulse">
            <span>⚡ Connecting to live multi-asset stream (Indices, Crude, Gold, Silver, BTC)...</span>
          </div>
        ) : (
          tickers.map((t) => {
            const isSelected = selectedSymbol && selectedSymbol.toUpperCase() === t.symbol.toUpperCase()
            const isUp = t.direction === 'up' || t.change_pct > 0
            const isDown = t.direction === 'down' || t.change_pct < 0
            const icon = getAssetCategoryIcon(t.category, t.symbol)
            const flash = flashMap[t.symbol]

            const changeColor = isUp ? 'var(--color-emerald)' : isDown ? 'var(--color-rose)' : 'var(--color-muted)'
            const badgeBg = isUp ? 'rgba(16, 185, 129, 0.12)' : isDown ? 'rgba(244, 63, 94, 0.12)' : 'rgba(255, 255, 255, 0.05)'
            const badgeBorder = isUp ? 'rgba(16, 185, 129, 0.25)' : isDown ? 'rgba(244, 63, 94, 0.25)' : 'var(--color-border-subtle)'

            // Tick flash animation classes
            let flashStyle = {}
            if (flash === 'up') {
              flashStyle = { borderColor: 'var(--color-emerald)', background: 'rgba(16, 185, 129, 0.18)' }
            } else if (flash === 'down') {
              flashStyle = { borderColor: 'var(--color-rose)', background: 'rgba(244, 63, 94, 0.18)' }
            }

            return (
              <button
                key={t.symbol}
                onClick={() => onSelectSymbol(t.symbol)}
                className={`flex-shrink-0 flex items-center gap-2 px-2 py-1 rounded-lg border text-left transition-all duration-150 cursor-pointer ${
                  isSelected
                    ? 'ring-2 ring-amber/80 shadow-xs'
                    : 'hover:border-border hover:bg-elevated/70'
                }`}
                style={{
                  background: isSelected ? 'var(--color-elevated)' : 'var(--color-surface)',
                  borderColor: isSelected ? 'var(--color-gold)' : 'var(--color-border)',
                  minWidth: '138px',
                  ...flashStyle,
                }}
                title={`Click to switch terminal to ${t.display_name} (${t.symbol})`}
              >
                {/* Icon & Symbol Header */}
                <div className="flex flex-col">
                  <div className="flex items-center gap-1">
                    <span className="text-[11px] leading-none">{icon}</span>
                    <span
                      className="text-[11px] font-bold font-mono tracking-tight"
                      style={{ color: isSelected ? 'var(--color-gold)' : 'var(--color-text)' }}
                    >
                      {t.display_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 mt-0.5">
                    <span className="text-[8px] font-mono px-1 rounded uppercase font-semibold text-muted" style={{ background: 'var(--color-panel)' }}>
                      {t.category === 'COMMODITY' ? 'MCX' : t.category}
                    </span>
                    {t.unit && t.unit !== '₹' && (
                      <span className="text-[8px] font-mono text-muted">
                        {t.unit}
                      </span>
                    )}
                  </div>
                </div>

                {/* Price and Up/Down Pill Badge */}
                <div className="flex flex-col items-end ml-auto">
                  <span className="text-[11px] font-mono font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>
                    {formatPrice(t.ltp, t.unit)}
                  </span>
                  <div
                    className="flex items-center gap-0.5 px-1 py-0.2 rounded text-[9px] font-mono font-bold tabular-nums mt-0.5"
                    style={{
                      background: badgeBg,
                      border: `1px solid ${badgeBorder}`,
                      color: changeColor,
                    }}
                  >
                    <span>{isUp ? '▲' : isDown ? '▼' : '●'}</span>
                    <span>
                      {isUp ? '+' : ''}{Number(t.change_pct || 0).toFixed(2)}%
                    </span>
                  </div>
                </div>
              </button>
            )
          })
        )}
      </div>

      {/* Right Scroll Navigation Button */}
      <button
        onClick={scrollRight}
        className="hidden md:flex items-center justify-center w-6 h-6 rounded-lg text-xs font-bold text-muted hover:text-text hover:bg-elevated transition-colors flex-shrink-0 cursor-pointer"
        aria-label="Scroll right"
      >
        ›
      </button>
    </div>
  )
}
