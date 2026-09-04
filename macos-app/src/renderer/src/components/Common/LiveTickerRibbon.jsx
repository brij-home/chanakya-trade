import { useState, useEffect, useRef, useCallback } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { useSSEStream } from '../../hooks/useSSEStream'

/**
 * LiveTickerRibbon — High-density, institutional-grade real-time ticker ribbon
 * for Major Indian Indices (NIFTY, BANK NIFTY, SENSEX, FIN NIFTY, INDIA VIX),
 * MCX Commodities (CRUDE OIL, GOLD, SILVER), and Crypto (BITCOIN).
 *
 * Real-Time Features:
 * - Direct SSE (Server-Sent Events) live streaming from /api/ticker/stream
 * - Sub-second visual flash animations on tick updates (emerald for up, rose for down)
 * - Automatic connection status indicator (● LIVE STREAM vs ● CONNECTING)
 * - Standard physical quotation unit badges (₹/bbl, ₹/10g, ₹/kg, $, pts)
 * - 1-Click symbol switching to sync active Terminal chart and multi-agent setup
 * - Smooth horizontal scroll controls and responsive touch/wheel panning
 */
export default function LiveTickerRibbon({
  tickers: initialTickers = null,
  selectedSymbol = 'NIFTY',
  onSelectSymbol = () => {},
  className = '',
}) {
  const { call } = useAPI()
  const port = useChatStore((s) => s.port)
  const baseUrl = getBaseUrl(port)

  const [tickers, setTickers] = useState(initialTickers || [])
  const [loading, setLoading] = useState(!initialTickers || initialTickers.length === 0)
  const [lastUpdated, setLastUpdated] = useState(new Date())
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [flashMap, setFlashMap] = useState({}) // { [symbol]: 'up' | 'down' }
  const scrollContainerRef = useRef(null)
  // Ref-tracked flash timers — cleared on unmount, never fire on unmounted component
  const flashTimersRef = useRef([])

  // Sync initial tickers from parent if passed
  useEffect(() => {
    if (initialTickers && initialTickers.length > 0 && tickers.length === 0) {
      setTickers(initialTickers)
      setLoading(false)
      setLastUpdated(new Date())
    }
  }, [initialTickers])

  // Fallback REST fetcher with dual-endpoint resilience
  const fetchLiveTickers = async (showPulse = false) => {
    try {
      if (showPulse) setIsRefreshing(true)
      let list = null
      try {
        const res = await call('/skills/live_tickers', {}, { method: 'GET' })
        list = res?.data?.tickers || res?.tickers
      } catch {}
      if (!Array.isArray(list) || list.length === 0) {
        try {
          const snapRes = await call('/api/ticker/snapshot', {}, { method: 'GET' })
          list = snapRes?.tickers || snapRes?.data?.tickers
        } catch {}
      }
      if (Array.isArray(list) && list.length > 0) {
        setTickers(list)
        setLastUpdated(new Date())
        setLoading(false)
      }
    } catch (err) {
      console.warn('Live tickers fetch error:', err)
    } finally {
      if (showPulse) {
        setTimeout(() => setIsRefreshing(false), 400)
      }
    }
  }

  // ── REAL-TIME SSE STREAMING via useSSEStream ─────────────────────────────
  // Fix: useSSEStream uses internal refs — no stale closure, no spurious reconnects.
  // The fallback REST poll is driven by a ref, not stale state.
  const handleSSEMessage = useCallback((payload) => {
    const incomingTickers = payload?.tickers || payload?.data?.tickers
    if (!Array.isArray(incomingTickers) || incomingTickers.length === 0) return

    setTickers((prev) => {
      const flashes = {}
      for (const inc of incomingTickers) {
        const old = prev.find((p) => p.symbol === inc.symbol)
        if (old && typeof inc.ltp === 'number' && typeof old.ltp === 'number' && inc.ltp !== old.ltp) {
          flashes[inc.symbol] = inc.ltp > old.ltp ? 'up' : 'down'
        }
      }
      if (Object.keys(flashes).length > 0) {
        setFlashMap(flashes)
        // Fix: use ref-tracked timer so it won't fire after unmount
        const t = setTimeout(() => setFlashMap({}), 700)
        flashTimersRef.current.push(t)
      }
      return incomingTickers
    })
    setLoading(false)
    setLastUpdated(new Date())
  }, [])

  const { connectionState } = useSSEStream(`${baseUrl}/api/ticker/stream`, {
    onMessage: handleSSEMessage,
    onOpen: () => {
      setLoading(false)
      setLastUpdated(new Date())
    },
    enabled: !!baseUrl,
  })

  const isStreaming = connectionState === 'live'

  // Clear all pending flash timers on unmount
  useEffect(() => {
    return () => {
      flashTimersRef.current.forEach(clearTimeout)
      flashTimersRef.current = []
    }
  }, [])

  // Resilient fallback REST poll ONLY when SSE is not live.
  // Fix: uses connectionState (current render value) not a stale closure variable.
  useEffect(() => {
    if (!tickers || tickers.length === 0) {
      fetchLiveTickers(false)
    }
    if (isStreaming) return // SSE is live — no polling needed
    const fallbackTimer = setInterval(() => fetchLiveTickers(false), 5000)
    return () => clearInterval(fallbackTimer)
  }, [isStreaming])

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
      className={`relative z-20 flex items-center gap-2 px-2 sm:px-3 py-1.5 rounded-2xl select-none transition-all ${className}`}
      style={{
        background: 'var(--color-panel)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      {/* Live Streaming Indicator & Manual Refresh */}
      <div className="flex items-center gap-2 pl-1 pr-2 py-0.5 border-r flex-shrink-0" style={{ borderColor: 'var(--color-border)' }}>
        {isStreaming ? (
          <div className="flex items-center gap-1.5" title={`Real-time SSE Stream Connected • Updated ${lastUpdated.toLocaleTimeString()}`}>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="text-[10px] font-bold tracking-wider font-mono uppercase hidden sm:inline" style={{ color: 'var(--color-emerald)' }}>
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
          onClick={() => fetchLiveTickers(true)}
          className={`text-[11px] p-1 rounded-md text-muted hover:text-text transition-all cursor-pointer ${isRefreshing ? 'animate-spin text-amber' : ''}`}
          title="Manual refresh"
          aria-label="Refresh live tickers"
        >
          ↻
        </button>
      </div>

      {/* Left Scroll Navigation Button */}
      <button
        onClick={scrollLeft}
        className="hidden md:flex items-center justify-center w-6 h-6 rounded-lg text-xs font-bold text-muted hover:text-text hover:bg-elevated transition-colors flex-shrink-0 cursor-pointer"
        aria-label="Scroll left"
      >
        ‹
      </button>

      {/* Scrollable Ribbon Container */}
      <div
        ref={scrollContainerRef}
        className="flex items-center gap-2 overflow-x-auto no-scrollbar scroll-smooth py-0.5 flex-1"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        {loading && tickers.length === 0 ? (
          <div className="flex items-center gap-2 py-1 px-3 text-xs text-muted font-mono animate-pulse">
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
            const badgeBorder = isUp ? 'rgba(16, 185, 129, 0.3)' : isDown ? 'rgba(244, 63, 94, 0.3)' : 'var(--color-border)'

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
                className={`flex-shrink-0 flex items-center gap-2 px-2.5 py-1.5 rounded-xl border text-left transition-all duration-200 cursor-pointer ${
                  isSelected
                    ? 'ring-2 ring-amber/80 shadow-md transform -translate-y-0.5'
                    : 'hover:border-border hover:bg-elevated/70 transform hover:-translate-y-0.5'
                }`}
                style={{
                  background: isSelected ? 'var(--color-elevated)' : 'var(--color-surface)',
                  borderColor: isSelected ? 'var(--color-gold)' : 'var(--color-border)',
                  minWidth: '152px',
                  ...flashStyle,
                }}
                title={`Click to switch terminal to ${t.display_name} (${t.symbol})`}
              >
                {/* Icon & Symbol Header */}
                <div className="flex flex-col">
                  <div className="flex items-center gap-1">
                    <span className="text-xs">{icon}</span>
                    <span
                      className="text-xs font-bold font-mono tracking-tight"
                      style={{ color: isSelected ? 'var(--color-gold)' : 'var(--color-text)' }}
                    >
                      {t.display_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 mt-0.5">
                    <span className="text-[9px] font-mono px-1 rounded uppercase font-semibold text-muted" style={{ background: 'var(--color-panel)' }}>
                      {t.category === 'COMMODITY' ? 'MCX' : t.category}
                    </span>
                    {t.unit && t.unit !== '₹' && (
                      <span className="text-[9px] font-mono text-muted">
                        {t.unit}
                      </span>
                    )}
                  </div>
                </div>

                {/* Price and Up/Down Pill Badge */}
                <div className="flex flex-col items-end ml-auto">
                  <span className="text-xs font-mono font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>
                    {formatPrice(t.ltp, t.unit)}
                  </span>
                  <div
                    className="flex items-center gap-0.5 px-1 py-0.2 rounded text-[10px] font-mono font-bold tabular-nums mt-0.5"
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
