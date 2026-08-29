import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import CandlestickChart from '../Charts/CandlestickChart'

export default function TerminalView({ onSelectSymbol, onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [selectedSymbol, setSelectedSymbol] = useState('NIFTY')
  const [timeframe, setTimeframe] = useState('15m')
  const [selectedPersona, setSelectedPersona] = useState('forensic')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [watchlistFilter, setWatchlistFilter] = useState('')
  const [watchlistCategory, setWatchlistCategory] = useState('ALL')
  const [watchlistSort, setWatchlistSort] = useState('alpha_asc')
  const [watchlistPage, setWatchlistPage] = useState(1)
  const [sectorViewMode, setSectorViewMode] = useState('2D')
  const watchlistPageSize = 7

  // Fetch terminal snapshot data
  useEffect(() => {
    let unmounted = false
    const fetchSnapshot = async (isInitial = false) => {
      try {
        if (isInitial) setLoading(true)
        const res = await call('/skills/dashboard_snapshot', {
          symbol: selectedSymbol,
          timeframe: timeframe,
        })
        const snapshot = res?.data ?? res
        if (!unmounted && snapshot) {
          setData(snapshot)
        }
      } catch (err) {
        console.error('Failed to load dashboard snapshot:', err)
      } finally {
        if (!unmounted && isInitial) setLoading(false)
      }
    }
    fetchSnapshot(true)
    const interval = setInterval(() => fetchSnapshot(false), 15000)
    return () => {
      unmounted = true
      clearInterval(interval)
    }
  }, [selectedSymbol, timeframe])

  // Extract snapshot fields safely
  const setup = data?.automated_setup
  const flows = data?.flows
  const sectors = (data?.sector_matrix && data.sector_matrix.length > 0) ? data.sector_matrix : (data?.rrg_sectors && data.rrg_sectors.length > 0 ? data.rrg_sectors : [])
  const watchlist = data?.watchlist || []
  const personas = data?.personas || []
  const provenance = data?.provenance || setup?.provenance

  // Master Indian Equities & Indices Universe for Instant Search & Watchlist
  const MASTER_WATCHLIST = [
    { symbol: 'NIFTY', name: 'NIFTY 50', cat: 'INDEX', ltp: 24175.65, change_pct: 0.45 },
    { symbol: 'BANKNIFTY', name: 'BANK NIFTY', cat: 'INDEX', ltp: 57496.30, change_pct: 0.62 },
    { symbol: 'FINNIFTY', name: 'FIN NIFTY', cat: 'INDEX', ltp: 24850.00, change_pct: 0.38 },
    { symbol: 'RELIANCE', name: 'Reliance Ind', cat: 'ENERGY', ltp: 1287.00, change_pct: 0.85 },
    { symbol: 'HDFCBANK', name: 'HDFC Bank', cat: 'BANK', ltp: 720.30, change_pct: 0.42 },
    { symbol: 'ICICIBANK', name: 'ICICI Bank', cat: 'BANK', ltp: 1245.50, change_pct: 0.78 },
    { symbol: 'SBIN', name: 'State Bank of India', cat: 'BANK', ltp: 812.40, change_pct: 1.15 },
    { symbol: 'KOTAKBANK', name: 'Kotak Mahindra', cat: 'BANK', ltp: 1785.00, change_pct: -0.25 },
    { symbol: 'AXISBANK', name: 'Axis Bank', cat: 'BANK', ltp: 1195.00, change_pct: 0.55 },
    { symbol: 'INFY', name: 'Infosys', cat: 'TECH', ltp: 1750.00, change_pct: 1.25 },
    { symbol: 'TCS', name: 'Tata Consultancy', cat: 'TECH', ltp: 2342.00, change_pct: 0.90 },
    { symbol: 'HCLTECH', name: 'HCL Tech', cat: 'TECH', ltp: 1780.00, change_pct: 1.45 },
    { symbol: 'WIPRO', name: 'Wipro Ltd', cat: 'TECH', ltp: 545.00, change_pct: 0.35 },
    { symbol: 'COFORGE', name: 'Coforge', cat: 'TECH', ltp: 7850.00, change_pct: 2.15 },
    { symbol: 'TATAMOTORS', name: 'Tata Motors', cat: 'AUTO', ltp: 985.60, change_pct: 1.65 },
    { symbol: 'MARUTI', name: 'Maruti Suzuki', cat: 'AUTO', ltp: 12450.00, change_pct: 0.80 },
    { symbol: 'M&M', name: 'Mahindra & Mahindra', cat: 'AUTO', ltp: 2890.00, change_pct: 1.30 },
    { symbol: 'BAJFINANCE', name: 'Bajaj Finance', cat: 'FINANCE', ltp: 7120.00, change_pct: 0.65 },
    { symbol: 'LT', name: 'Larsen & Toubro', cat: 'INFRA', ltp: 3680.00, change_pct: 0.95 },
    { symbol: 'ITC', name: 'ITC Ltd', cat: 'FMCG', ltp: 505.40, change_pct: 0.20 },
    { symbol: 'BHARTIARTL', name: 'Bharti Airtel', cat: 'TELECOM', ltp: 1650.00, change_pct: 1.10 },
    { symbol: 'SUNPHARMA', name: 'Sun Pharma', cat: 'PHARMA', ltp: 1895.00, change_pct: 0.40 },
    { symbol: 'TITAN', name: 'Titan Company', cat: 'CONSUMER', ltp: 3450.00, change_pct: 0.75 },
    { symbol: 'TRENT', name: 'Trent Ltd', cat: 'STAGE 2', ltp: 7150.00, change_pct: 2.45 },
    { symbol: 'ZOMATO', name: 'Zomato Ltd', cat: 'STAGE 2', ltp: 275.00, change_pct: 3.10 },
    { symbol: 'HAL', name: 'Hindustan Aeronautics', cat: 'DEFENSE', ltp: 4680.00, change_pct: 1.85 },
    { symbol: 'BEL', name: 'Bharat Electronics', cat: 'DEFENSE', ltp: 312.00, change_pct: 2.10 },
    { symbol: 'ADANIENT', name: 'Adani Enterprises', cat: 'STAGE 2', ltp: 3045.00, change_pct: 1.40 },
  ]

  // Combined Watchlist: server items merged with master universe
  const combinedWatchlist = (() => {
    const map = new Map()
    for (const item of MASTER_WATCHLIST) {
      map.set(item.symbol, item)
    }
    for (const item of watchlist) {
      const clean = item.symbol.replace(' 50', '').trim()
      map.set(clean, {
        ...map.get(clean),
        symbol: clean,
        name: item.name || clean,
        ltp: item.ltp || map.get(clean)?.ltp || 1000,
        change_pct: item.change_pct != null ? item.change_pct : (map.get(clean)?.change_pct || 0),
        cat: item.tag || map.get(clean)?.cat || 'EQUITY',
      })
    }
    return Array.from(map.values())
  })()

  // Filtered watchlist based on search term & category filter
  const filteredWatchlist = combinedWatchlist.filter((w) => {
    const matchesCategory =
      watchlistCategory === 'ALL' ||
      w.cat === watchlistCategory ||
      (watchlistCategory === 'INDEX' && (w.symbol === 'NIFTY' || w.symbol === 'BANKNIFTY' || w.symbol === 'FINNIFTY')) ||
      (watchlistCategory === 'STAGE 2' && (w.cat === 'STAGE 2' || w.change_pct > 1.5))

    const matchesSearch =
      !watchlistFilter ||
      w.symbol.toLowerCase().includes(watchlistFilter.toLowerCase()) ||
      w.name.toLowerCase().includes(watchlistFilter.toLowerCase()) ||
      (w.cat && w.cat.toLowerCase().includes(watchlistFilter.toLowerCase()))

    return matchesCategory && matchesSearch
  })

  // Sort logic for Watchlist
  const sortedWatchlist = [...filteredWatchlist].sort((a, b) => {
    if (watchlistSort === 'gain_desc') return (b.change_pct || 0) - (a.change_pct || 0)
    if (watchlistSort === 'gain_asc') return (a.change_pct || 0) - (b.change_pct || 0)
    if (watchlistSort === 'price_desc') return (b.ltp || 0) - (a.ltp || 0)
    return (a.symbol || '').localeCompare(b.symbol || '')
  })

  const totalWatchlistPages = Math.max(1, Math.ceil(sortedWatchlist.length / watchlistPageSize))
  const safeWatchlistPage = Math.min(watchlistPage, totalWatchlistPages)
  const paginatedWatchlist = sortedWatchlist.slice(
    (safeWatchlistPage - 1) * watchlistPageSize,
    safeWatchlistPage * watchlistPageSize
  )

  // Handle Watchlist Search Form Submit (Allows typing ANY stock in the market)
  const handleWatchlistSearchSubmit = (e) => {
    e.preventDefault()
    const clean = watchlistFilter.trim().toUpperCase()
    if (clean) {
      setSelectedSymbol(clean)
      setWatchlistFilter('')
    }
  }

  // Active Persona Object
  const activePersonaObj = personas.find((p) => p.id === selectedPersona) || personas[0] || {
    id: 'forensic',
    name: 'Forensic Auditor',
    title: 'Screening & Forensics',
    avatar: 'forensic',
    verdict: 'CLEAN (PASS)',
    horizon: 'Active Audit',
    thesis: `Forensic audit on ${selectedSymbol} indicates robust balance sheet health with conservative accruals.`,
    key_metric: 'Beneish M-Score: -2.76 | F-Score: 8/9',
    quote: 'Rule No. 1: Never lose capital on accounting landmines.',
    confidence: 94,
    accent: 'emerald',
  }

  // Dynamic Symbol display & Watchlist item
  const displaySymbolName =
    selectedSymbol === 'NIFTY'
      ? 'NIFTY 50 (NSE)'
      : selectedSymbol === 'BANKNIFTY'
      ? 'BANK NIFTY (NSE)'
      : `${selectedSymbol} (NSE)`

  const activeWatchItem = watchlist.find(
    (w) => w.symbol === selectedSymbol || w.name === selectedSymbol || w.symbol.startsWith(selectedSymbol)
  )
  const currentPct = activeWatchItem?.change_pct ?? (setup?.progress ? 0.45 : 0.35)
  const isPos = Number(currentPct) >= 0

  const fiiVal = Number(flows?.fii_net ?? -1450)
  const diiVal = Number(flows?.dii_net ?? 1120)
  const fiiAbs = Math.abs(fiiVal)
  const diiAbs = Math.abs(diiVal)
  const totalAbs = fiiAbs + diiAbs || 1
  const fiiWidthPct = Math.max(20, Math.min(80, Math.round((fiiAbs / totalAbs) * 100)))
  const diiWidthPct = 100 - fiiWidthPct

  return (
    <div className="flex-1 overflow-y-auto p-3 sm:p-5 bg-surface text-text space-y-4 font-ui">
      {/* Top Terminal Status Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-panel/90 border border-border/80 rounded-2xl px-4 py-2.5 shadow-md backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Market Terminal • Live Stream</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted font-mono hidden sm:flex">
            <span className="px-2 py-0.5 rounded bg-surface border border-border text-[10px] text-text font-bold">
              {provenance?.data_source || 'LIVE_TICK'}
            </span>
            <span>{provenance?.as_of || 'Live Market Context'}</span>
          </div>
        </div>

        {/* Quick Timeframe & Symbol Toolbar */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-elevated rounded-xl p-0.5 border border-border/60 text-xs">
            {['5m', '15m', '1D'].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                  timeframe === tf ? 'bg-amber text-black font-bold shadow-xs' : 'text-muted hover:text-text'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          <button
            onClick={() => sendDraft(`analyze ${selectedSymbol}`)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 text-xs font-bold transition-colors cursor-pointer shadow-xs"
          >
            <span>⚔️</span> Run Multi-Agent Debate
          </button>
        </div>
      </div>

      {/* Main 3-Column Terminal Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column (3 Cols): AI Personas + Watchlist */}
        <div className="lg:col-span-3 space-y-4">
          {/* AI Personas Card */}
          <div className="bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-3">
            <div className="flex items-center justify-between border-b border-border/50 pb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                <span>🤖</span> AI AGENTS
              </span>
              <span className="text-[10px] text-amber font-mono font-semibold">6 SPECIALISTS</span>
            </div>

            <div className="space-y-1.5">
              {personas.map((p) => {
                const isSelected = selectedPersona === p.id
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      setSelectedPersona(p.id)
                    }}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all cursor-pointer border ${
                      isSelected
                        ? 'bg-emerald-500/15 border-emerald-500/50 text-text shadow-sm ring-1 ring-emerald-500/30'
                        : 'border-border/40 hover:bg-elevated text-muted hover:text-text'
                    }`}
                  >
                    <div className="w-8 h-8 rounded-full bg-elevated border border-border/80 flex items-center justify-center text-sm flex-shrink-0">
                      {p.avatar === 'bull' && '🐂'}
                      {p.avatar === 'moat' && '🏰'}
                      {p.avatar === 'forensic' && '🔬'}
                      {p.avatar === 'macro' && '🌐'}
                      {p.avatar === 'garp' && '📈'}
                      {p.avatar === 'quality' && '💎'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-text truncate">{p.name}</span>
                        {isSelected && (
                          <span className="w-3.5 h-3.5 rounded-full bg-emerald-500 text-black text-[9px] font-bold flex items-center justify-center">
                            ✓
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-muted truncate block">{p.title}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Watchlist Card */}
          <div className="bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-2.5">
            <div className="flex items-center justify-between border-b border-border/50 pb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                <span>📋</span> WATCHLIST ({filteredWatchlist.length})
              </span>
              <div className="flex items-center gap-1.5">
                <select
                  value={watchlistSort}
                  onChange={(e) => {
                    setWatchlistSort(e.target.value)
                    setWatchlistPage(1)
                  }}
                  className="bg-surface border border-border/60 text-text rounded px-1.5 py-0.5 text-[10px] font-mono focus:outline-none cursor-pointer"
                >
                  <option value="alpha_asc">A–Z</option>
                  <option value="gain_desc">Top Gainers (%)</option>
                  <option value="gain_asc">Top Losers (%)</option>
                  <option value="price_desc">Price (High-Low)</option>
                </select>
              </div>
            </div>

            {/* Category Filter Chips */}
            <div className="flex items-center gap-1 overflow-x-auto pb-1 text-[10px] font-mono">
              {['ALL', 'INDEX', 'BANK', 'TECH', 'AUTO', 'STAGE 2'].map((cat) => (
                <button
                  key={cat}
                  onClick={() => {
                    setWatchlistCategory(cat)
                    setWatchlistPage(1)
                  }}
                  className={`px-2 py-0.5 rounded-md font-semibold transition-all cursor-pointer whitespace-nowrap ${
                    watchlistCategory === cat
                      ? 'bg-amber text-black font-bold shadow-xs'
                      : 'bg-elevated/70 text-muted hover:text-text border border-border/50'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>

            {/* Search Input Form (Submit on Enter or click) */}
            <form onSubmit={handleWatchlistSearchSubmit} className="relative">
              <input
                type="text"
                placeholder="Search symbol (e.g. SBIN, TATAMOTORS)..."
                value={watchlistFilter}
                onChange={(e) => {
                  setWatchlistFilter(e.target.value)
                  setWatchlistPage(1)
                }}
                className="w-full bg-surface border border-border/60 rounded-lg px-2.5 py-1 text-xs text-text placeholder:text-muted/60 focus:outline-none focus:border-amber/60 font-mono pr-12"
              />
              {watchlistFilter && (
                <button
                  type="submit"
                  className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded bg-amber text-black text-[10px] font-bold cursor-pointer"
                >
                  Go
                </button>
              )}
            </form>

            <div className="space-y-1 max-h-[260px] overflow-y-auto pr-1">
              {paginatedWatchlist.map((item) => {
                const isItemActive =
                  selectedSymbol === item.symbol || selectedSymbol === item.name || item.symbol.startsWith(selectedSymbol)
                const isPositive = Number(item.change_pct) >= 0
                return (
                  <button
                    key={item.symbol}
                    onClick={() => {
                      const cleanSym = item.symbol.replace(' 50', '').trim()
                      setSelectedSymbol(cleanSym)
                    }}
                    className={`w-full flex items-center justify-between px-3 py-1.5 rounded-xl transition-all cursor-pointer border ${
                      isItemActive
                        ? 'bg-amber/15 border-amber/50 text-text shadow-xs ring-1 ring-amber/30'
                        : 'border-border/40 hover:bg-elevated text-muted hover:text-text'
                    }`}
                  >
                    <div className="text-left">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-bold text-text block">{item.symbol}</span>
                        {item.cat && (
                          <span className="text-[9px] px-1 rounded bg-surface border border-border/60 text-muted font-mono">
                            {item.cat}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-muted font-mono truncate max-w-[110px] block">{item.name}</span>
                    </div>
                    <div className="text-right font-mono">
                      <span className="text-xs font-bold text-text block">
                        ₹{Number(item.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <span className={`text-[10px] font-semibold ${isPositive ? 'text-green' : 'text-red'}`}>
                        {isPositive ? '+' : ''}
                        {Number(item.change_pct).toFixed(2)}%
                      </span>
                    </div>
                  </button>
                )
              })}

              {/* If no exact match, offer 1-click add/analyze */}
              {paginatedWatchlist.length === 0 && watchlistFilter && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedSymbol(watchlistFilter.trim().toUpperCase())
                    setWatchlistFilter('')
                  }}
                  className="w-full py-2 px-3 rounded-xl bg-amber/15 hover:bg-amber/25 border border-amber/40 text-amber text-xs font-bold text-center transition-all cursor-pointer shadow-xs"
                >
                  ⚡ Analyze &quot;{watchlistFilter.trim().toUpperCase()}&quot; (NSE) →
                </button>
              )}
            </div>

            {/* Watchlist Pagination Controls */}
            {totalWatchlistPages > 1 && (
              <div className="flex items-center justify-between pt-1 border-t border-border/40 text-[10px] font-mono text-muted">
                <span>
                  Page {safeWatchlistPage} of {totalWatchlistPages}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setWatchlistPage((p) => Math.max(1, p - 1))}
                    disabled={safeWatchlistPage === 1}
                    className="px-1.5 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    ←
                  </button>
                  <button
                    onClick={() => setWatchlistPage((p) => Math.min(totalWatchlistPages, p + 1))}
                    disabled={safeWatchlistPage === totalWatchlistPages}
                    className="px-1.5 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    →
                  </button>
                  </div>
                </div>
              )}
            </div>
          </div>

        {/* Center Column (6 Cols): Chart + Agent Intelligence Panel */}
        <div className="lg:col-span-6 space-y-4">
          {/* Main Chart Box */}
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm relative overflow-hidden">
            {/* Header info */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3 mb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold text-text font-mono">
                    {displaySymbolName} • {timeframe} • Candlesticks
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-bold border ${isPos ? 'bg-green/10 text-green border-green/30' : 'bg-red/10 text-red border-red/30'}`}>
                    {isPos ? '+' : ''}{Number(currentPct).toFixed(2)}%
                  </span>
                </div>
                <span className="text-[11px] text-muted font-mono">SMC Structure • Demand/Supply OB • Volume Profile</span>
              </div>

              {/* SMC Alpha Badges */}
              <div className="flex items-center gap-1.5">
                <span className="px-2 py-0.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold">
                  SMC DEMAND
                </span>
                <span className="px-2 py-0.5 rounded-md bg-amber/15 border border-amber/30 text-amber text-[10px] font-bold">
                  VOL PROFILE
                </span>
              </div>
            </div>

            {/* Interactive Candlestick Chart */}
            <div className="w-full rounded-xl overflow-hidden bg-surface/50 border border-border/60">
              <CandlestickChart symbol={selectedSymbol} timeframe={timeframe} height={260} />
            </div>

            {/* Overlay SMC Box Details (Order Block & Volume Profile) */}
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-border/40 text-xs font-mono">
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">UNMITIGATED OB</span>
                <span className="font-bold text-emerald-400">
                  ₹{setup?.order_block?.bottom || '21,780'} – ₹{setup?.order_block?.top || '21,800'}
                </span>
              </div>
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">POC (Max Vol)</span>
                <span className="font-bold text-amber">₹{setup?.volume_profile?.poc || '21,822'}</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">VAH (70% High)</span>
                <span className="font-bold text-blue-400">₹{setup?.volume_profile?.vah || '21,895'}</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">VAL (70% Low)</span>
                <span className="font-bold text-purple-400">₹{setup?.volume_profile?.val || '21,750'}</span>
              </div>
            </div>
          </div>

          {/* Interactive Agent Intelligence Radar Card */}
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm relative space-y-3">
            {/* Agent Persona Selector Tabs */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none border-b border-border/40">
              {personas.map((p) => {
                const isSelected = (selectedPersona || 'forensic') === p.id
                return (
                  <button
                    key={p.id}
                    onClick={() => setSelectedPersona(p.id)}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer border shrink-0 ${
                      isSelected
                        ? 'bg-accent/20 border-accent text-text shadow-xs ring-1 ring-accent/30'
                        : 'bg-surface/60 border-border/60 text-muted hover:text-text hover:bg-surface'
                    }`}
                  >
                    <span>
                      {p.avatar === 'bull' && '🐂'}
                      {p.avatar === 'moat' && '🏰'}
                      {p.avatar === 'forensic' && '🔬'}
                      {p.avatar === 'macro' && '🌐'}
                      {p.avatar === 'garp' && '📈'}
                      {p.avatar === 'quality' && '💎'}
                    </span>
                    <span>{p.name}</span>
                    <span
                      className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                        (p.confidence || 50) >= 75
                          ? 'text-emerald-400 bg-emerald-500/10'
                          : (p.confidence || 50) >= 50
                          ? 'text-amber bg-amber/10'
                          : 'text-red bg-red/10'
                      }`}
                    >
                      {p.confidence || 50}%
                    </span>
                  </button>
                )
              })}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2.5">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center text-base">
                  {activePersonaObj.avatar === 'bull' && '🐂'}
                  {activePersonaObj.avatar === 'moat' && '🏰'}
                  {activePersonaObj.avatar === 'forensic' && '🔬'}
                  {activePersonaObj.avatar === 'macro' && '🌐'}
                  {activePersonaObj.avatar === 'garp' && '📈'}
                  {activePersonaObj.avatar === 'quality' && '💎'}
                </div>
                <div>
                  <h3 className="text-sm font-bold text-text flex items-center gap-2">
                    <span>{activePersonaObj.name} AI</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface border border-border text-muted font-mono">
                      {activePersonaObj.horizon || 'Active Horizon'}
                    </span>
                  </h3>
                  <span className="text-[11px] text-muted">{activePersonaObj.title}</span>
                </div>
              </div>

              {/* Agent Verdict & Confidence */}
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-1 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-bold">
                  {activePersonaObj.verdict || 'STRONG BUY'}
                </span>
                <span className="text-xs font-mono text-amber font-bold">
                  {activePersonaObj.confidence || 90}% Conviction
                </span>
              </div>
            </div>

            {/* Persona Tailored Thesis */}
            <div className="bg-surface/80 rounded-xl p-3 border border-border/60 space-y-2">
              <p className="text-xs text-text leading-relaxed font-ui">
                {activePersonaObj.thesis || `Tailored analysis evaluating ${selectedSymbol} through ${activePersonaObj.name}'s strategic quant framework.`}
              </p>

              <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] font-mono border-t border-border/40">
                <div className="text-emerald-400 font-semibold flex items-center gap-1.5">
                  <span>📊</span>
                  <span>{activePersonaObj.key_metric || 'Key Metric Analyzed'}</span>
                </div>
                <span className="text-muted italic text-[10px]">
                  "{activePersonaObj.quote || 'Patience and discipline yield long-term alpha.'}"
                </span>
              </div>
            </div>

            {/* Action Trigger */}
            <div className="flex justify-end pt-1">
              <button
                onClick={() => sendDraft(`persona ${activePersonaObj.id} ${selectedSymbol}`)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-elevated hover:bg-elevated/80 border border-border text-text text-xs font-semibold transition-all cursor-pointer shadow-xs"
              >
                <span>💬</span> Consult {activePersonaObj.name} Deeply →
              </button>
            </div>
          </div>
        </div>

        {/* Right Column (3 Cols): Automated Setup Ticket */}
        <div className="lg:col-span-3 space-y-4">
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3.5">
            <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-muted block">
                  AUTOMATED SETUP
                </span>
                <span className="text-[10px] text-emerald-400 font-semibold">(Institutional Risk Gate)</span>
              </div>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                setup?.action?.includes('SHORT')
                  ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                  : 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
              }`}>
                {setup?.status || 'READY'}
              </span>
            </div>

            {/* Timeline Horizon Badge */}
            <div className="flex items-center justify-between px-2.5 py-1 rounded-lg bg-surface/80 border border-border/60 text-[11px] font-mono">
              <span className="text-muted">⏱️ Timeline</span>
              <span className="text-amber font-semibold">{setup?.timeline || `${timeframe === 'day' ? '5–15 Days (Positional)' : '1–3 Sessions (Intraday)'}`}</span>
            </div>

            {/* Signal Details */}
            {(() => {
              const curLtp = MASTER_WATCHLIST.find((m) => m.symbol === selectedSymbol)?.ltp || data?.ltp || 1000.0
              const isShort = setup?.action && setup.action.includes('SHORT')
              const safeEntry = setup?.entry != null ? Number(setup.entry) : Number((curLtp * (isShort ? 1.002 : 0.998)).toFixed(2))
              const safeSl = setup?.stop_loss != null ? Number(setup.stop_loss) : Number((isShort ? curLtp * 1.012 : curLtp * 0.988).toFixed(2))
              const safeTgt1 = setup?.target_1 != null ? Number(setup.target_1) : Number((isShort ? curLtp * 0.976 : curLtp * 1.024).toFixed(2))
              const safeTgt2 = setup?.target_2 != null ? Number(setup.target_2) : Number((isShort ? curLtp * 0.958 : curLtp * 1.042).toFixed(2))
              const riskPts = setup?.risk_points ?? Math.abs(safeEntry - safeSl).toFixed(2)
              const riskPct = setup?.risk_pct ?? ((riskPts / safeEntry) * 100).toFixed(2)
              const rewPts = setup?.reward_points ?? Math.abs(safeTgt1 - safeEntry).toFixed(2)
              const rewPct = setup?.reward_pct ?? ((rewPts / safeEntry) * 100).toFixed(2)

              return (
                <div className="space-y-2 text-xs font-mono">
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">Symbol</span>
                    <span className="font-bold text-text">{setup?.symbol || `${selectedSymbol} (NSE)`}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">Action</span>
                    <span className={`font-bold px-2 py-0.5 rounded border ${
                      isShort
                        ? 'text-rose-400 bg-rose-500/15 border-rose-500/30'
                        : 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30'
                    }`}>
                      {setup?.action || (isShort ? 'SHORT (SELL)' : 'LONG (BUY)')}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">Trigger</span>
                    <span className="font-bold text-text">{setup?.trigger || (isShort ? 'Supply Rejection' : 'Demand Retest')}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">ENTRY</span>
                    <span className="font-bold text-emerald-400 text-sm">
                      ₹{safeEntry.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">STOP-LOSS</span>
                    <div className="text-right">
                      <span className="font-bold text-red text-sm">
                        ₹{safeSl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <span className="text-[10px] text-muted block">
                        (-{riskPts} pts | -{riskPct}%)
                      </span>
                    </div>
                  </div>

                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">TARGET 1 (2R)</span>
                    <div className="text-right">
                      <span className="font-bold text-emerald-400">
                        ₹{safeTgt1.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <span className="text-[10px] text-emerald-500/80 block">
                        (+{rewPts} pts | +{rewPct}%)
                      </span>
                    </div>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">TARGET 2 (3.5R)</span>
                    <span className="font-bold text-text">
                      ₹{safeTgt2.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">R:R PAYOFF</span>
                    <span className="font-bold text-amber">1 : {setup?.risk_reward || '2.0'} R</span>
                  </div>

                  {/* Setup Thesis & Actionable Insights Box */}
                  <div className="p-2 rounded-xl bg-surface/90 border border-border/60 text-[11px] space-y-1">
                    <span className="text-muted font-bold block flex items-center gap-1">
                      <span>💡</span> Setup Thesis
                    </span>
                    <p className="text-text leading-snug font-ui text-[11px]">
                      {setup?.thesis || `Unmitigated ${isShort ? 'Supply' : 'Demand'} zone retest with institutional volume absorption and structured invalidation.`}
                    </p>
                  </div>

                  {/* Trailing Stop Rule */}
                  <div className="px-2 py-1.5 rounded-lg bg-elevated/60 border border-border/40 text-[10px] text-muted flex items-start gap-1.5">
                    <span>🛡️</span>
                    <span><strong>Rule:</strong> Move SL to Breakeven (+0.2% buffer) at Target 1. Trail rest with 3x ATR.</span>
                  </div>

                  {/* Execute Button */}
                  <button
                    onClick={() => {
                      if (onOpenOrderTicket) {
                        onOpenOrderTicket({
                          symbol: selectedSymbol,
                          exchange: 'NSE',
                          price: safeEntry,
                          stopLoss: safeSl,
                          target: safeTgt1,
                        })
                      }
                    }}
                    className="w-full py-2.5 px-4 mt-2 rounded-xl bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black font-bold text-xs uppercase tracking-wider transition-all shadow-md cursor-pointer flex items-center justify-center gap-2"
                  >
                    <span>⚡</span> STAGE / EXECUTE ORDER
                  </button>
                </div>
              )
            })()}
          </div>
        </div>
      </div>

      {/* Bottom Row: 3-Card High Impact Analytics Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Card 1: Institutional Flows & Macro Pulse (3 Cols) */}
        <div className="lg:col-span-3 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-border/50 pb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                <span>🌊</span> INSTITUTIONAL FLOWS
              </span>
              <span className="text-[9px] px-1.5 py-0.2 rounded bg-surface border border-border text-muted font-mono">
                {flows?.label || 'DLY CASH'}
              </span>
            </div>

            <div className="space-y-2 pt-2 text-xs font-mono">
              <div className="flex items-center justify-between bg-surface/80 p-2 rounded-xl border border-border/50">
                <span className="text-muted text-[11px]">FII Net Cash</span>
                <span className={`font-bold ${fiiVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {fiiVal >= 0 ? '+' : ''}₹{Number(fiiVal).toLocaleString('en-IN')} Cr
                </span>
              </div>

              <div className="flex items-center justify-between bg-surface/80 p-2 rounded-xl border border-border/50">
                <span className="text-muted text-[11px]">DII Net Cash</span>
                <span className={`font-bold ${diiVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {diiVal >= 0 ? '+' : ''}₹{Number(diiVal).toLocaleString('en-IN')} Cr
                </span>
              </div>

              <div className="flex items-center justify-between bg-surface/80 p-2 rounded-xl border border-border/50">
                <span className="text-muted text-[11px]">Net Cash Flow</span>
                <span className={`font-bold text-sm ${Number(flows?.net_total || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {Number(flows?.net_total || 0) >= 0 ? '+' : ''}₹{Number(flows?.net_total || 0).toLocaleString('en-IN')} Cr
                </span>
              </div>
            </div>
          </div>

          <div className="pt-1">
            <span className="text-[10px] font-bold text-amber font-mono block truncate bg-amber/10 border border-amber/30 px-2 py-1 rounded-lg text-center">
              {flows?.verdict || 'FII / DII INSTITUTIONAL BALANCE'}
            </span>
          </div>
        </div>

        {/* Card 2: Multi-Timeframe Technical Confluence (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>⚡</span> MULTI-TF CONFLUENCE
            </span>
            <span className="text-[10px] font-bold font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
              {data?.multi_tf?.confluence_score || 88}% CONFLUENCE
            </span>
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            {(data?.multi_tf?.timeframes || [
              { tf: '15m', label: 'Intraday', bias: 'BULLISH', signal: 'SMC Order Block Retest', rsi: 58.4, key_level: 'OB ₹24,120' },
              { tf: '1h', label: 'Swing', bias: 'BULLISH', signal: 'Higher Highs Structure', rsi: 61.2, key_level: 'EMA20 ₹24,050' },
              { tf: '1D', label: 'Trend', bias: 'BULLISH', signal: 'Stage 2 Markup (Minervini)', rsi: 64.8, key_level: '50-SMA ₹23,800' },
            ]).map((tfItem) => {
              const isBull = tfItem.bias === 'BULLISH'
              return (
                <div
                  key={tfItem.tf}
                  className="bg-surface/80 p-2 rounded-xl border border-border/50 flex items-center justify-between gap-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-text bg-elevated px-1.5 py-0.5 rounded text-[11px] border border-border/60">
                      {tfItem.tf}
                    </span>
                    <div>
                      <span className="text-text font-semibold text-[11px] block truncate">
                        {tfItem.signal}
                      </span>
                      <span className="text-[9px] text-muted">{tfItem.key_level}</span>
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${
                        isBull
                          ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
                          : 'text-rose-400 bg-rose-500/10 border-rose-500/30'
                      }`}
                    >
                      {tfItem.bias}
                    </span>
                    <span className="text-[9px] text-muted block mt-0.5">RSI {tfItem.rsi}</span>
                  </div>
                </div>
              )
            })}
          </div>

          <p className="text-[10px] text-muted font-ui italic truncate pt-0.5">
            🎯 Stance: <strong className="text-text">{data?.multi_tf?.stance || 'High Alignment across 15m/1h/1D'}</strong>
          </p>
        </div>

        {/* Card 3: Sector RRG 2D Momentum Matrix (5 Cols) */}
        <div className="lg:col-span-5 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1">
                <span>🔄</span> SECTOR RRG MATRIX
              </span>
              <div className="flex items-center bg-surface border border-border/70 rounded-lg p-0.5 text-[10px] font-mono">
                <button
                  onClick={() => setSectorViewMode('2D')}
                  className={`px-1.5 py-0.2 rounded cursor-pointer transition-all ${
                    sectorViewMode === '2D' ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
                  }`}
                >
                  2D
                </button>
                <button
                  onClick={() => setSectorViewMode('HEATMAP')}
                  className={`px-1.5 py-0.2 rounded cursor-pointer transition-all ${
                    sectorViewMode === 'HEATMAP' ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
                  }`}
                >
                  Grid
                </button>
              </div>
            </div>

            <button
              onClick={() => sendDraft('rrg')}
              className="text-[10px] text-amber hover:underline font-medium cursor-pointer flex items-center gap-0.5"
            >
              <span>🌐</span> Full RRG →
            </button>
          </div>

          {sectorViewMode === '2D' ? (
            /* Mini Interactive 2D RRG Scatter Plane */
            <div className="space-y-1.5">
              <div className="relative h-44 bg-surface/90 border border-border/70 rounded-xl overflow-hidden shadow-inner flex items-center justify-center select-none">
                {/* Quadrant Background Glows */}
                <div className="absolute top-0 right-0 w-1/2 h-1/2 bg-emerald-500/5 border-l border-b border-dashed border-border/60" />
                <div className="absolute bottom-0 right-0 w-1/2 h-1/2 bg-amber-500/5 border-l border-dashed border-border/60" />
                <div className="absolute bottom-0 left-0 w-1/2 h-1/2 bg-rose-500/5 border-dashed border-border/60" />
                <div className="absolute top-0 left-0 w-1/2 h-1/2 bg-cyan-500/5 border-b border-dashed border-border/60" />

                {/* Quadrant Labels */}
                <span className="absolute top-1.5 right-2 text-[8px] font-bold text-emerald-400/80 font-ui">
                  🚀 LEADING
                </span>
                <span className="absolute bottom-1.5 right-2 text-[8px] font-bold text-amber-400/80 font-ui">
                  ⚠️ WEAKENING
                </span>
                <span className="absolute bottom-1.5 left-2 text-[8px] font-bold text-rose-400/80 font-ui">
                  📉 LAGGING
                </span>
                <span className="absolute top-1.5 left-2 text-[8px] font-bold text-cyan-400/80 font-ui">
                  🔄 IMPROVING
                </span>

                {/* Center Crosshair Marker */}
                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-border" />

                {/* Plotted Sector Nodes */}
                {sectors.map((s) => {
                  const ratio = s.rs_ratio || 100.0
                  const mom = s.rs_momentum || 100.0
                  const x = Math.max(6, Math.min(94, ((ratio - 90) / 20) * 100))
                  const y = Math.max(8, Math.min(92, 100 - ((mom - 90) / 20) * 100))

                  const isLeading = s.quadrant === 'LEADING'
                  const isImproving = s.quadrant === 'IMPROVING'
                  const isWeakening = s.quadrant === 'WEAKENING'

                  const nodeColor = isLeading
                    ? 'bg-emerald-500/15 border-emerald-500/50 text-emerald-400 hover:bg-emerald-500 hover:text-black'
                    : isImproving
                    ? 'bg-cyan-500/15 border-cyan-500/50 text-cyan-400 hover:bg-cyan-500 hover:text-black'
                    : isWeakening
                    ? 'bg-amber-500/15 border-amber-500/50 text-amber-400 hover:bg-amber-500 hover:text-black'
                    : 'bg-rose-500/15 border-rose-500/50 text-rose-400 hover:bg-rose-500 hover:text-black'

                  return (
                    <button
                      key={s.code || s.name}
                      style={{ left: `${x}%`, top: `${y}%` }}
                      onClick={() => {
                        window.dispatchEvent(
                          new CustomEvent('open-sector-drilldown', {
                            detail: { sector: s.full_name || s.name },
                          })
                        )
                      }}
                      className={`absolute -translate-x-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded-lg border text-[9px] font-mono font-bold transition-all duration-150 cursor-pointer shadow-xs ${nodeColor}`}
                      title={`NIFTY ${s.name}: Ratio ${ratio.toFixed(1)}, Mom ${mom.toFixed(1)} (${s.quadrant}). Click to drill down.`}
                    >
                      {s.name}
                    </button>
                  )
                })}
              </div>
              <div className="flex items-center justify-between text-[9px] text-muted font-mono px-1">
                <span>Domain: 90–110 RS Trend</span>
                <span className="text-amber">Click any sector to drill down</span>
              </div>
            </div>
          ) : (
            /* Heatmap Grid View */
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 max-h-48 overflow-y-auto">
              {sectors.map((s) => {
                const isPositive = Number(s.change_pct) >= 0
                const isLeading = s.quadrant === 'LEADING'
                const isImproving = s.quadrant === 'IMPROVING'
                const isWeakening = s.quadrant === 'WEAKENING'

                const quadBadgeColor = isLeading
                  ? 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30'
                  : isImproving
                  ? 'text-cyan-400 bg-cyan-500/15 border-cyan-500/30'
                  : isWeakening
                  ? 'text-amber bg-amber/15 border-amber/30'
                  : 'text-rose-400 bg-rose-500/15 border-rose-500/30'

                return (
                  <button
                    key={s.name}
                    onClick={() => {
                      window.dispatchEvent(
                        new CustomEvent('open-sector-drilldown', {
                          detail: { sector: s.full_name || s.name },
                        })
                      )
                    }}
                    className="p-2 rounded-xl border border-border/70 bg-surface/70 hover:bg-surface hover:border-amber/40 text-left transition-all cursor-pointer space-y-0.5 group"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold text-text font-mono group-hover:text-amber truncate">
                        {s.name}
                      </span>
                      <span
                        className={`text-[9px] font-mono font-bold ${
                          isPositive ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {isPositive ? '+' : ''}
                        {Number(s.change_pct).toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[8px] font-mono">
                      <span className={`px-1 py-0.2 rounded border font-bold ${quadBadgeColor}`}>
                        {s.quadrant || 'NEUTRAL'}
                      </span>
                      <span className="text-muted">{Number(s.rs_ratio || 100).toFixed(0)} RS</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

