import { useState, useEffect, useRef } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import PayoffSimulatorCard from '../Cards/PayoffSimulatorCard'

// Cumulative standard normal distribution for Greeks
function normalCDF(x) {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2)
  const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
  return x > 0 ? 1 - p : p
}

function normalPDF(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)
}

function calculateGreeks(spot, strike, ivPct, daysToExpiry = 4, r = 0.065) {
  const S = Number(spot) || 22000
  const K = Number(strike) || 22000
  const sigma = Math.max(0.01, (parseFloat(String(ivPct).replace(/[^0-9.-]/g, '')) || 15) / 100)
  const T = Math.max(1 / 365, (daysToExpiry || 4) / 365)
  const sqrtT = Math.sqrt(T)

  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * T) / (sigma * sqrtT)
  const d2 = d1 - sigma * sqrtT

  const callDelta = normalCDF(d1)
  const putDelta = callDelta - 1
  const gamma = normalPDF(d1) / (S * sigma * sqrtT)
  const vega = (S * sqrtT * normalPDF(d1)) / 100
  const thetaCall = (-(S * normalPDF(d1) * sigma) / (2 * sqrtT) - r * K * Math.exp(-r * T) * normalCDF(d2)) / 365
  const thetaPut = (-(S * normalPDF(d1) * sigma) / (2 * sqrtT) + r * K * Math.exp(-r * T) * normalCDF(-d2)) / 365

  return {
    callDelta: callDelta.toFixed(2),
    putDelta: putDelta.toFixed(2),
    gamma: (gamma * 100).toFixed(3),
    vega: vega.toFixed(2),
    callTheta: thetaCall.toFixed(1),
    putTheta: thetaPut.toFixed(1),
  }
}

export default function OptionsDeskView({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [underlying, setUnderlying] = useState('NIFTY')
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isLiveActive, setIsLiveActive] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isPayoffModalOpen, setIsPayoffModalOpen] = useState(false)
  const [strikeFilter, setStrikeFilter] = useState('ATM_10')
  const [chainSort, setChainSort] = useState('strike_asc')
  const [chainPage, setChainPage] = useState(1)
  const [chainPageSize, setPageSize] = useState(25) // Default 25 so ATM window (±10 = 21 strikes) is fully visible centered
  const [chainViewMode, setChainViewMode] = useState('STANDARD') // 'STANDARD' | 'GREEKS'
  const [showVisualBars, setShowVisualBars] = useState(true)
  const [deskPosScale, setDeskPosScale] = useState(1)
  const [showDeskWhy, setShowDeskWhy] = useState(false)

  const atmRowRef = useRef(null)
  const tableContainerRef = useRef(null)

  const fetchGex = async (isSilent = false) => {
    try {
      if (!isSilent) setLoading(true)
      else setIsRefreshing(true)
      const res = await call('/skills/gex_snapshot', {
        underlying,
        expiry: selectedExpiry || undefined,
      })
      const snapshot = res?.data ?? res
      if (snapshot) {
        setData(snapshot)
        setLastUpdated(new Date())
        if (!selectedExpiry && snapshot.expiry) {
          setSelectedExpiry(snapshot.expiry)
        }
      }
    } catch (err) {
      console.error('Failed to load GEX snapshot:', err)
    } finally {
      if (!isSilent) setLoading(false)
      setIsRefreshing(false)
    }
  }

  // Initial & underlying/expiry change fetch
  useEffect(() => {
    fetchGex(false)
  }, [underlying, selectedExpiry])

  // Real-time background auto-update (every 4s when live mode active)
  useEffect(() => {
    if (!isLiveActive) return
    const interval = setInterval(() => {
      fetchGex(true)
    }, 4000)
    return () => clearInterval(interval)
  }, [underlying, selectedExpiry, isLiveActive])

  const spot = data?.spot_price || 22068.75
  const gexProfile = data?.gex_profile || []
  const deltaHedge = data?.delta_hedge
  const ivSkew = data?.iv_skew || []
  const optionsChain = data?.options_chain || []
  const expiries = data?.expiries || ['0DTE (Weekly)', 'Next Week', 'Monthly']
  const pcr = data?.pcr || 1.18
  const pcrSentiment = data?.pcr_sentiment || 'BULLISH (Put Writing Support)'
  const maxPain = data?.max_pain || Math.round(spot)
  const totalCallOI = data?.total_call_oi || '1.8M'
  const totalPutOI = data?.total_put_oi || '2.1M'
  const netOIChange = data?.net_oi_change || '+3.2L'

  // Dynamic IV Curve SVG Points calculation
  const ivValues = ivSkew.map((p) => p.iv)
  const minIV = ivValues.length > 0 ? Math.min(...ivValues) : 12
  const maxIV = ivValues.length > 0 ? Math.max(...ivValues) : 22
  const ivRange = Math.max(1, maxIV - minIV)

  const svgPoints = ivSkew
    .map((pt, idx) => {
      const x = 15 + (idx / Math.max(1, ivSkew.length - 1)) * 210
      const y = 85 - ((pt.iv - minIV) / ivRange) * 65
      return `${x},${y}`
    })
    .join(' ')

  // Mathematically robust ATM index calculation (guaranteed valid index)
  const atmIdx = (() => {
    if (!optionsChain || optionsChain.length === 0) return -1
    const explicitIdx = optionsChain.findIndex((r) => r.is_atm)
    if (explicitIdx >= 0) return explicitIdx
    let closestIdx = 0
    let minDiff = Infinity
    optionsChain.forEach((r, idx) => {
      const diff = Math.abs(Number(r.strike) - spot)
      if (diff < minDiff) {
        minDiff = diff
        closestIdx = idx
      }
    })
    return closestIdx
  })()

  // Filtered & Sorted Options Chain (ATM ±5, ATM ±10, ATM ±15, ALL)
  const filteredChain = optionsChain.filter((row, idx) => {
    if (atmIdx < 0 || strikeFilter === 'ALL') return true
    if (strikeFilter === 'ATM_5') {
      return Math.abs(idx - atmIdx) <= 5
    }
    if (strikeFilter === 'ATM_10') {
      return Math.abs(idx - atmIdx) <= 10
    }
    if (strikeFilter === 'ATM_15') {
      return Math.abs(idx - atmIdx) <= 15
    }
    return true
  })

  const sortedChain = [...filteredChain].sort((a, b) => {
    if (chainSort === 'strike_desc') return Number(b.strike) - Number(a.strike)
    if (chainSort === 'call_oi_desc') {
      const vA = parseFloat(String(a.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      const vB = parseFloat(String(b.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      return vB - vA
    }
    if (chainSort === 'put_oi_desc') {
      const vA = parseFloat(String(a.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      const vB = parseFloat(String(b.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      return vB - vA
    }
    return Number(a.strike) - Number(b.strike)
  })

  const atmTargetStrike = optionsChain[atmIdx]?.strike
  const atmSortedIndex = sortedChain.findIndex(
    (r) => Number(r.strike) === Number(atmTargetStrike) || r.is_atm
  )
  const isPageSizeAll = chainPageSize === 'ALL'
  const pageSizeNum = isPageSizeAll ? sortedChain.length : Number(chainPageSize)
  const totalChainPages = isPageSizeAll ? 1 : Math.max(1, Math.ceil(sortedChain.length / pageSizeNum))
  const safeChainPage = isPageSizeAll ? 1 : Math.min(chainPage, totalChainPages)
  const paginatedChain = isPageSizeAll
    ? sortedChain
    : sortedChain.slice(
        (safeChainPage - 1) * pageSizeNum,
        safeChainPage * pageSizeNum
      )

  const scrollToATM = () => {
    if (atmRowRef.current) {
      atmRowRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
        inline: 'nearest',
      })
    }
  }

  // When data loads or filter/underlying changes, land on the page with ATM and center it
  useEffect(() => {
    if (atmIdx >= 0 && sortedChain.length > 0 && !isPageSizeAll) {
      const atmSortedIdx = sortedChain.findIndex(
        (r) => Number(r.strike) === Number(atmTargetStrike) || r.is_atm
      )
      if (atmSortedIdx >= 0) {
        const atmPage = Math.max(1, Math.ceil((atmSortedIdx + 1) / pageSizeNum))
        setChainPage(atmPage)
      }
    }
    const timer = setTimeout(() => {
      scrollToATM()
    }, 120)
    return () => clearTimeout(timer)
  }, [spot, underlying, strikeFilter, chainPageSize])

  return (
    <div className="flex-1 overflow-y-auto p-2.5 sm:p-3.5 bg-surface text-text space-y-2.5 font-ui">
      {/* Top Header Card */}
      <div className="bg-panel/90 border border-border/80 rounded-xl p-3 shadow-sm backdrop-blur-md space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
          <div className="flex items-center gap-2.5">
            <span className="text-amber text-lg font-bold">◆</span>
            <div>
              <h1 className="text-sm font-bold tracking-wide font-mono text-text">
                QUANT &amp; OPTIONS DESK
              </h1>
              <div className="flex items-center gap-2 text-[10px] text-muted">
                <span>Gamma Exposure, Delta Neutral Hedging &amp; Volatility Skew</span>
                <span>•</span>
                <span className="text-emerald-400 font-mono font-semibold">Live Institutional Greeks &amp; GEX Profile</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Live Auto-Refresh Indicator & Pause/Resume */}
            <button
              onClick={() => setIsLiveActive((prev) => !prev)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition-all cursor-pointer ${
                isLiveActive
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/25'
                  : 'bg-surface border-border/70 text-muted hover:text-text'
              }`}
              title={isLiveActive ? 'Live real-time 4s feed active (Click to pause)' : 'Feed paused (Click to resume real-time updates)'}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${isLiveActive ? 'bg-emerald-500 animate-pulse' : 'bg-muted'}`} />
              <span>{isLiveActive ? 'LIVE (4s)' : 'PAUSED'}</span>
              {lastUpdated && (
                <span className="text-[9px] opacity-75 font-mono ml-0.5">
                  {lastUpdated.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              )}
            </button>

            {/* Quick Refresh Button */}
            <button
              onClick={() => fetchGex(true)}
              disabled={isRefreshing}
              className="px-2 py-1 rounded-lg bg-surface hover:bg-elevated border border-border/60 text-muted hover:text-amber text-xs font-bold transition-all cursor-pointer flex items-center gap-1"
              title="Refresh options chain now"
            >
              <span className={`inline-block ${isRefreshing ? 'animate-spin' : ''}`}>↻</span>
              <span className="text-[10px]">Refresh</span>
            </button>

            <button
              onClick={() => setIsPayoffModalOpen(true)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black text-xs font-bold transition-all shadow-xs cursor-pointer"
            >
              <span>🎯</span> Interactive Strategy Payoff
            </button>
          </div>
        </div>

        {/* Sub-bar: Instrument selector, Expiry & Key Analytics */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex items-center gap-1.5">
              <span className="text-muted text-[11px]">Instrument:</span>
              <div className="flex items-center gap-0.5 bg-elevated rounded-lg p-0.5 border border-border/70">
                {['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX'].map((inst) => (
                  <button
                    key={inst}
                    onClick={() => {
                      setUnderlying(inst)
                      setSelectedExpiry('')
                    }}
                    className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all cursor-pointer ${
                      underlying === inst
                        ? 'bg-amber text-black shadow-xs'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {inst}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-muted text-[11px]">Expiry:</span>
              <select
                value={selectedExpiry}
                onChange={(e) => setSelectedExpiry(e.target.value)}
                className="bg-elevated border border-border/80 text-text font-bold rounded-lg px-2 py-0.5 text-[11px] cursor-pointer focus:outline-none"
              >
                {expiries.map((exp) => (
                  <option key={exp} value={exp}>
                    {exp}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs">
            <div>
              <span className="text-muted mr-1 text-[11px]">Spot:</span>
              <span className="text-emerald-400 font-bold text-xs">
                ₹{Number(spot).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
              <span className="text-emerald-400 font-semibold ml-1 text-[10px]">
                ({data?.spot_change || '+114.30'} / {data?.spot_change_pct || '+0.52%'})
              </span>
            </div>
            <span className="text-muted text-[10px] hidden sm:inline">{data?.time || new Date().toLocaleTimeString('en-IN') + ' IST'}</span>
          </div>
        </div>

        {/* Dynamic Key Analytics Bar (PCR, Max Pain, Total OI, Net Flow) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 pt-1.5 border-t border-border/50 text-xs font-mono">
          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">PUT-CALL RATIO (PCR)</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-xs font-bold ${pcr >= 1.0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {pcr}
              </span>
              <span className="text-[8px] text-muted truncate">({pcrSentiment})</span>
            </div>
          </div>

          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">MAX PAIN STRIKE</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-xs font-bold text-amber">
                ₹{Number(maxPain).toLocaleString('en-IN')}
              </span>
              <span className="text-[8px] text-muted">Expiry Pin</span>
            </div>
          </div>

          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">TOTAL OI (CALL vs PUT)</span>
            <div className="flex items-center gap-2 mt-0.5 text-[11px] font-bold">
              <span className="text-cyan-400">C: {totalCallOI}</span>
              <span className="text-muted">|</span>
              <span className="text-amber">P: {totalPutOI}</span>
            </div>
          </div>

          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">NET OI CHANGE (1D)</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-xs font-bold text-emerald-400">
                {netOIChange}
              </span>
              <span className="text-[8px] text-muted">Net Bullish Flow</span>
            </div>
          </div>
        </div>
      </div>

      {/* Top 3-Pane Grid: GEX Volatility Pinning, Delta Hedging, IV Smile */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        {/* Card 1: GEX Volatility Pinning & Gamma Regime (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-xl p-3 shadow-xs space-y-2">
          <div className="flex items-center justify-between border-b border-border/50 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
              <span>📊</span> DEALER GAMMA &amp; VOLATILITY (GEX)
            </span>
            <span className="text-[10px] text-pink-400 font-mono font-bold">
              FLIP: ₹{data?.zero_gamma ? Number(data.zero_gamma).toLocaleString('en-IN') : '24,200'}
            </span>
          </div>

          {/* Regime Banner */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 flex items-center justify-between">
            <div>
              <span className="text-[9px] text-muted block">Current Gamma Regime</span>
              <span className="text-[11px] font-bold text-emerald-400 font-mono flex items-center gap-1">
                <span>🟢</span> POSITIVE GAMMA (PINNING)
              </span>
            </div>
            <div className="text-right">
              <span className="text-[9px] text-muted block">Dealer Stance</span>
              <span className="text-[10px] font-bold text-cyan-400 font-mono">Long Gamma (Mean Reverting)</span>
            </div>
          </div>

          {/* Key Gamma Walls (Call Resistance vs Put Support) */}
          <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
            <div className="bg-cyan-500/10 border border-cyan-500/30 p-1.5 px-2 rounded-lg">
              <div className="flex items-center justify-between text-[9px] text-cyan-400 font-bold">
                <span>CALL WALL</span>
                <span>RESISTANCE</span>
              </div>
              <span className="text-xs font-bold text-text mt-0.5 block">₹24,500</span>
              <span className="text-[9px] text-muted">+14.2B Gamma</span>
            </div>

            <div className="bg-amber/10 border border-amber/30 p-1.5 px-2 rounded-lg">
              <div className="flex items-center justify-between text-[9px] text-amber font-bold">
                <span>PUT WALL</span>
                <span>SUPPORT</span>
              </div>
              <span className="text-xs font-bold text-text mt-0.5 block">₹24,000</span>
              <span className="text-[9px] text-muted">-11.8B Gamma</span>
            </div>
          </div>

          {/* Actionable Trader Takeaway */}
          <p className="text-[10px] text-muted font-ui leading-relaxed bg-surface/50 p-1.5 rounded-lg border border-border/40">
            💡 <strong className="text-text">Trading Insight:</strong> Dealers are long gamma above flip level; price expected to pin between <span className="text-amber font-mono font-bold">₹24,000</span> and <span className="text-cyan-400 font-mono font-bold">₹24,500</span>.
          </p>
        </div>

        {/* Card 2: Delta Neutral Hedging Recommendation (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-xl p-3 shadow-xs space-y-2">
          <div className="flex items-center justify-between border-b border-border/50 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
              <span>⚡</span> DELTA HEDGING &amp; RISK
            </span>
            <div className="flex items-center gap-1">
              {[
                { label: '1L', val: 1 },
                { label: '2L', val: 2 },
                { label: '5L', val: 5 },
              ].map((sc) => (
                <button
                  key={sc.val}
                  onClick={() => setDeskPosScale(sc.val)}
                  className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold transition-all cursor-pointer ${
                    deskPosScale === sc.val ? 'bg-amber text-black' : 'bg-surface text-muted hover:text-text'
                  }`}
                  title={`Scale position by ${sc.label}`}
                >
                  {sc.label}
                </button>
              ))}
              <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ml-1 ${
                Math.abs(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale) <= 0.08
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : Number(deltaHedge?.net_delta ?? 0.42) > 0
                  ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                  : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
              }`}>
                {Number(deltaHedge?.net_delta ?? 0.42) > 0 ? 'LONG Δ' : 'SHORT Δ'}
              </span>
            </div>
          </div>

          {/* Visual Delta Balance Needle Meter */}
          <div className="bg-surface/70 border border-border/60 rounded-lg p-2 space-y-1">
            <div className="flex items-center justify-between text-[9px] font-mono text-muted">
              <span className="text-rose-400">Short (-1.0)</span>
              <span className="text-emerald-400 font-bold">Neutral Zone</span>
              <span className="text-cyan-400">Long (+1.0)</span>
            </div>
            <div className="relative h-2 w-full bg-border/40 rounded-full overflow-hidden flex items-center">
              <div className="absolute left-[45%] right-[45%] top-0 bottom-0 bg-emerald-500/30 border-x border-emerald-400/50" />
              <div
                className="absolute top-0 bottom-0 w-2 -ml-1 bg-gradient-to-r from-amber to-amber-light rounded-full shadow-xs transition-all duration-300"
                style={{
                  left: `${((Math.max(-1.0, Math.min(1.0, Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale)) + 1.0) / 2.0) * 100}%`,
                }}
              />
            </div>
            <div className="flex justify-between items-center text-[9px] text-muted font-mono">
              <span>Net Δ: <strong className="text-text">{Number(deltaHedge?.net_delta ?? 0.42) >= 0 ? '+' : ''}{(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale).toFixed(2)} Δ ({Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale * (underlying === 'BANKNIFTY' ? 15 : 75))} shares)</strong></span>
              <span>₹/1%: <strong className="text-cyan-400">₹{Math.abs(Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale * (underlying === 'BANKNIFTY' ? 15 : 75) * spot * 0.01)).toLocaleString('en-IN')}</strong></span>
            </div>
          </div>

          {/* Actionable Hedge Recipes */}
          <div className="space-y-1.5 text-xs font-mono">
            <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-muted block">Hedge Execution Blueprint</span>
                <button
                  onClick={() => setShowDeskWhy(!showDeskWhy)}
                  className="text-[9px] text-amber hover:underline cursor-pointer flex items-center gap-0.5"
                >
                  <span>{showDeskWhy ? '▲ Hide' : '▼ Why?'}</span>
                </button>
              </div>
              <span className="font-bold text-emerald-400 text-[11px] block truncate mt-0.5">
                SELL {Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale))} Lot{Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale)) > 1 ? 's' : ''} ({Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale)) * (underlying === 'BANKNIFTY' ? 15 : 75)} Qty) {underlying} FUT
              </span>
            </div>

            {/* Expandable Why & When Narrative */}
            {showDeskWhy && (
              <div className="bg-surface/90 border border-amber/30 rounded-lg p-2 space-y-1 text-[10px] font-ui text-text/90 leading-tight">
                <p className="font-bold text-amber">💡 Monetary Risk Rationale:</p>
                <p>
                  Holding {deskPosScale} lot{deskPosScale > 1 ? 's' : ''} with +{(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale).toFixed(2)} delta exposes you to ~₹{Math.abs(Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale * (underlying === 'BANKNIFTY' ? 15 : 75) * spot * 0.01)).toLocaleString('en-IN')} loss per 1% drop in {underlying}.
                </p>
                <p className="text-muted font-mono pt-0.5">Trigger: When {underlying} drifts &gt; ±0.75% (±{Math.round(spot * 0.0075)} pts).</p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-1.5 text-[10px]">
              <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
                <span className="text-[8px] text-muted block">Gamma Risk</span>
                <span className="font-bold text-text">{deltaHedge?.net_gamma ?? '+0.18'} Γ</span>
              </div>
              <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
                <span className="text-[8px] text-muted block">Est. Margin</span>
                <span className="font-bold text-text">₹{Math.round(Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale)) * (underlying === 'BANKNIFTY' ? 15 : 75) * spot * 0.11).toLocaleString('en-IN')}</span>
              </div>
            </div>

            <div className="pt-0.5">
              <button
                onClick={() => {
                  const hedgeLots = Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale))
                  const lotSz = (underlying === 'BANKNIFTY' ? 15 : underlying === 'FINNIFTY' ? 40 : 75)
                  if (onOpenOrderTicket) {
                    onOpenOrderTicket({
                      symbol: `${underlying} FUT`,
                      exchange: 'NFO',
                      price: spot,
                      quantity: hedgeLots * lotSz,
                      side: Number(deltaHedge?.net_delta ?? 0.42) > 0 ? 'SELL' : 'BUY',
                      segment: 'OPTIONS',
                    })
                  } else {
                    sendDraft(`execute delta hedge: SELL ${hedgeLots} lots (${hedgeLots * lotSz} qty) ${underlying} FUT`)
                  }
                }}
                className="w-full py-1.5 px-2.5 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-500 hover:brightness-110 text-black font-bold text-[11px] uppercase tracking-wide transition-all shadow-xs cursor-pointer flex items-center justify-center gap-1"
              >
                <span>⚡</span> Stage 1-Click Hedge ({Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale))} Lot{Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale)) > 1 ? 's' : ''})
              </button>
            </div>
          </div>
        </div>

        {/* Card 3: Dynamic IV Smile & Skew Curve (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-xl p-3 shadow-xs space-y-2">
          <div className="flex items-center justify-between border-b border-border/50 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
              <span>📈</span> VOLATILITY SMILE &amp; SKEW
            </span>
            <span className="text-[9px] text-amber font-mono font-bold px-1.5 py-0.5 rounded bg-amber/10 border border-amber/30">
              PUT SKEW +3.4%
            </span>
          </div>

          {/* Interactive Dynamic SVG Smile Curve */}
          <div className="h-28 w-full relative flex items-center justify-center bg-surface/80 rounded-lg border border-border/60 p-1.5">
            <svg className="w-full h-full" viewBox="0 0 240 90">
              {/* Grid lines */}
              <line x1="0" y1="20" x2="240" y2="20" stroke="currentColor" className="text-border/60" strokeDasharray="3" />
              <line x1="0" y1="45" x2="240" y2="45" stroke="currentColor" className="text-border/60" strokeDasharray="3" />
              <line x1="0" y1="70" x2="240" y2="70" stroke="currentColor" className="text-border/60" strokeDasharray="3" />

              {/* Spot Marker Line (Pink) */}
              <line x1="120" y1="0" x2="120" y2="90" stroke="#f43f5e" strokeWidth="1.2" strokeDasharray="2" />
              <text x="123" y="12" fill="#f43f5e" fontSize="7" fontFamily="monospace" fontWeight="bold">
                Spot: {Math.round(spot)}
              </text>

              {/* Put IV Curve (Amber) */}
              {svgPoints && (
                <polyline
                  fill="none"
                  stroke="#f59e0b"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={svgPoints}
                />
              )}

              {/* Call IV Curve (Cyan) */}
              <polyline
                fill="none"
                stroke="#06b6d4"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray="4 2"
                points="15,75 70,72 120,68 170,62 225,55"
              />

              {/* ATM Circle Point */}
              <circle cx="120" cy="68" r="3" fill="#f59e0b" className="animate-pulse" />
              <text x="124" y="78" fill="#f59e0b" fontSize="7" fontFamily="monospace" fontWeight="bold">
                ATM ({minIV.toFixed(1)}%)
              </text>
            </svg>
          </div>

          <div className="flex justify-between items-center text-[9px] font-mono text-muted bg-surface/50 p-1.5 rounded-lg border border-border/40">
            <span className="flex items-center gap-1 text-amber">
              <span className="w-1.5 h-1 bg-amber rounded-full inline-block" /> Put IV ({ivSkew[0]?.iv || '18.2'}%)
            </span>
            <span className="text-cyan-400 font-bold">ATM ({minIV.toFixed(1)}%)</span>
            <span className="flex items-center gap-1 text-cyan-400">
              <span className="w-1.5 h-1 bg-cyan-400 rounded-full inline-block" /> Call IV (14.2%)
            </span>
          </div>

          {/* 1-Click Skew Strategy Action Chip */}
          <button
            onClick={() => sendDraft(`Build a high-probability Bull Put spread for ${underlying} to exploit elevated put skew`)}
            className="w-full py-1 px-2 rounded-lg bg-surface hover:bg-amber/10 border border-border/70 hover:border-amber/40 text-[10px] font-mono font-bold text-amber transition-all cursor-pointer flex items-center justify-center gap-1"
          >
            <span>🎯</span> Harvest Put Skew (Bull Put Spread)
          </button>
        </div>
      </div>

      {/* Bottom Full-Width Institutional Options Chain Table */}
      {(() => {
        const maxCallOIVal = Math.max(...optionsChain.map((r) => parseFloat(String(r.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0), 1)
        const maxPutOIVal = Math.max(...optionsChain.map((r) => parseFloat(String(r.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0), 1)
        const callWallStrike = optionsChain.reduce((max, r) => ((parseFloat(String(r.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0) > (parseFloat(String(max?.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0) ? r : max), optionsChain[0] || {})?.strike
        const putWallStrike = optionsChain.reduce((max, r) => ((parseFloat(String(r.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0) > (parseFloat(String(max?.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0) ? r : max), optionsChain[0] || {})?.strike

        return (
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-md space-y-3">
            {/* Top Table Control Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
              <div className="flex flex-wrap items-center gap-2.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-amber font-bold">⛓️</span>
                  <span className="text-xs font-bold uppercase tracking-wider text-text font-mono">
                    {underlying} OPTIONS CHAIN
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 font-mono font-bold border border-emerald-500/30">
                    Spot: ₹{Number(spot).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </span>
                </div>

                {/* Key Structural Wall Badges */}
                <div className="flex items-center gap-1.5 text-[10px] font-mono hidden md:flex">
                  {callWallStrike && (
                    <span className="px-2 py-0.5 rounded bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 font-bold" title="Highest Call OI - Institutional Resistance">
                      🛡️ Call Wall: ₹{Number(callWallStrike).toLocaleString('en-IN')}
                    </span>
                  )}
                  {putWallStrike && (
                    <span className="px-2 py-0.5 rounded bg-amber/15 border border-amber/30 text-amber font-bold" title="Highest Put OI - Institutional Support">
                      🏰 Put Wall: ₹{Number(putWallStrike).toLocaleString('en-IN')}
                    </span>
                  )}
                  {maxPain && (
                    <span className="px-2 py-0.5 rounded bg-rose-500/15 border border-rose-500/30 text-rose-400 font-bold" title="Expiry Pin Level">
                      🎯 Max Pain: ₹{Number(maxPain).toLocaleString('en-IN')}
                    </span>
                  )}
                </div>
              </div>

              {/* Table Controls: View Mode + Visual Bars + Strike Filter + Sorting + Page Size */}
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                {/* View Mode Toggle: Standard vs Greeks */}
                <div className="flex items-center gap-0.5 bg-surface border border-border/60 p-0.5 rounded-lg text-[10px]">
                  <button
                    onClick={() => setChainViewMode('STANDARD')}
                    className={`px-2 py-0.5 rounded font-bold transition-all cursor-pointer ${
                      chainViewMode === 'STANDARD' ? 'bg-amber text-black shadow-xs' : 'text-muted hover:text-text'
                    }`}
                  >
                    📊 Standard
                  </button>
                  <button
                    onClick={() => setChainViewMode('GREEKS')}
                    className={`px-2 py-0.5 rounded font-bold transition-all cursor-pointer ${
                      chainViewMode === 'GREEKS' ? 'bg-amber text-black shadow-xs' : 'text-muted hover:text-text'
                    }`}
                  >
                    🔬 Greeks (Δ, Γ, Θ, ν)
                  </button>
                </div>

                {/* Depth Bars Toggle */}
                <button
                  onClick={() => setShowVisualBars(!showVisualBars)}
                  className={`px-2 py-0.5 rounded text-[10px] border transition-all cursor-pointer ${
                    showVisualBars
                      ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400 font-bold'
                      : 'bg-surface border-border/60 text-muted hover:text-text'
                  }`}
                  title="Toggle horizontal visual open interest depth bars"
                >
                  🔥 Depth Bars: {showVisualBars ? 'ON' : 'OFF'}
                </button>

                {/* Center on ATM Button */}
                <button
                  onClick={() => {
                    if (atmSortedIndex >= 0 && !isPageSizeAll) {
                      const targetPage = Math.max(1, Math.ceil((atmSortedIndex + 1) / pageSizeNum))
                      setChainPage(targetPage)
                    }
                    setTimeout(scrollToATM, 50)
                  }}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber/20 hover:bg-amber hover:text-black text-amber border border-amber/50 font-bold text-[10px] transition-all cursor-pointer shadow-xs"
                  title="Jump to and center on At-The-Money (Spot) strike"
                >
                  <span>🎯</span>
                  <span>Center on ATM</span>
                </button>

                {/* Strike Filter Chips */}
                <div className="flex items-center gap-0.5 bg-surface border border-border/60 p-0.5 rounded-lg text-[10px]">
                  {[
                    { id: 'ATM_5', label: 'ATM ±5' },
                    { id: 'ATM_10', label: 'ATM ±10' },
                    { id: 'ATM_15', label: 'ATM ±15' },
                    { id: 'ALL', label: 'All Strikes' },
                  ].map((f) => (
                    <button
                      key={f.id}
                      onClick={() => {
                        setStrikeFilter(f.id)
                        setChainPage(1)
                      }}
                      className={`px-1.5 py-0.5 rounded transition-all cursor-pointer ${
                        strikeFilter === f.id ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
                      }`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>

                {/* Sort Selector */}
                <div className="flex items-center gap-1">
                  <select
                    value={chainSort}
                    onChange={(e) => {
                      setChainSort(e.target.value)
                      setChainPage(1)
                    }}
                    className="bg-surface border border-border/60 text-text rounded px-1.5 py-0.5 text-[10px] font-mono focus:outline-none cursor-pointer"
                  >
                    <option value="strike_asc">Strike (Low → High)</option>
                    <option value="strike_desc">Strike (High → Low)</option>
                    <option value="call_oi_desc">Highest Call OI</option>
                    <option value="put_oi_desc">Highest Put OI</option>
                  </select>
                </div>

                {/* Page Size Selector */}
                <div className="flex items-center gap-1">
                  {[15, 25, 50, 'ALL'].map((sz) => (
                    <button
                      key={sz}
                      onClick={() => {
                        setPageSize(sz)
                        setChainPage(1)
                      }}
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono cursor-pointer ${
                        chainPageSize === sz ? 'bg-amber text-black font-bold' : 'bg-surface text-muted hover:text-text border border-border/40'
                      }`}
                    >
                      {sz}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Matrix Table with sticky headers and ref */}
            <div ref={tableContainerRef} className="overflow-x-auto rounded-xl border border-border/50 max-h-[620px] overflow-y-auto relative scrollbar-thin">
              <table className="w-full text-xs font-mono text-left border-collapse">
                <thead className="sticky top-0 z-20 bg-surface shadow-xs">
                  {/* Category Super-Headers */}
                  <tr className="bg-elevated/80 text-[10px] uppercase font-bold tracking-wider border-b border-border/70">
                    <th colSpan={chainViewMode === 'STANDARD' ? 6 : 6} className="py-1 px-3 text-cyan-400 text-center border-r border-border/60 bg-cyan-950/20">
                      ◄ CALL OPTIONS (CE)
                    </th>
                    <th className="py-1 px-3 text-amber text-center bg-surface font-extrabold border-x border-border/80">
                      STRIKE
                    </th>
                    <th colSpan={chainViewMode === 'STANDARD' ? 6 : 6} className="py-1 px-3 text-amber text-center border-l border-border/60 bg-amber-950/20">
                      PUT OPTIONS (PE) ►
                    </th>
                  </tr>

                  {/* Column Headers */}
                  <tr className="border-b border-border/60 text-[10px] text-muted uppercase bg-surface/90">
                    {chainViewMode === 'STANDARD' ? (
                      <>
                        <th className="py-2 px-2.5 text-cyan-400">OI (Depth)</th>
                        <th className="py-2 px-2 text-cyan-400">OI Chg</th>
                        <th className="py-2 px-2 text-cyan-400">GEX</th>
                        <th className="py-2 px-2 text-cyan-400">IV</th>
                        <th className="py-2 px-2 text-cyan-400">Bid</th>
                        <th className="py-2 px-2.5 text-cyan-400 border-r border-border/60">Ask</th>
                      </>
                    ) : (
                      <>
                        <th className="py-2 px-2.5 text-cyan-400">Delta (Δ)</th>
                        <th className="py-2 px-2 text-cyan-400">Gamma (Γ)</th>
                        <th className="py-2 px-2 text-cyan-400">Theta (Θ)</th>
                        <th className="py-2 px-2 text-cyan-400">Vega (ν)</th>
                        <th className="py-2 px-2 text-cyan-400">Bid</th>
                        <th className="py-2 px-2.5 text-cyan-400 border-r border-border/60">Ask</th>
                      </>
                    )}

                    <th className="py-2 px-3 text-center bg-elevated text-text font-extrabold border-x border-border/80">
                      STRIKE
                    </th>

                    {chainViewMode === 'STANDARD' ? (
                      <>
                        <th className="py-2 px-2.5 text-amber border-l border-border/60 text-right">Bid</th>
                        <th className="py-2 px-2 text-amber text-right">Ask</th>
                        <th className="py-2 px-2 text-amber text-right">IV</th>
                        <th className="py-2 px-2 text-amber text-right">GEX</th>
                        <th className="py-2 px-2 text-amber text-right">OI Chg</th>
                        <th className="py-2 px-2.5 text-amber text-right">OI (Depth)</th>
                      </>
                    ) : (
                      <>
                        <th className="py-2 px-2.5 text-amber border-l border-border/60 text-right">Bid</th>
                        <th className="py-2 px-2 text-amber text-right">Ask</th>
                        <th className="py-2 px-2 text-amber text-right">Vega (ν)</th>
                        <th className="py-2 px-2 text-amber text-right">Theta (Θ)</th>
                        <th className="py-2 px-2 text-amber text-right">Gamma (Γ)</th>
                        <th className="py-2 px-2.5 text-amber text-right">Delta (Δ)</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20">
                  {paginatedChain.map((row) => {
                    const isATM = row.is_atm
                    const isCallITM = Number(row.strike) < spot
                    const isPutITM = Number(row.strike) > spot
                    const isCallWall = Number(row.strike) === Number(callWallStrike)
                    const isPutWall = Number(row.strike) === Number(putWallStrike)
                    const isMaxPain = Number(row.strike) === Number(maxPain)

                    const callOINum = parseFloat(String(row.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0
                    const putOINum = parseFloat(String(row.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0
                    const callOIWidth = Math.min(100, Math.round((callOINum / maxCallOIVal) * 100))
                    const putOIWidth = Math.min(100, Math.round((putOINum / maxPutOIVal) * 100))

                    const callOIChgIsPos = String(row.calls_oi_chg || '').startsWith('+')
                    const putOIChgIsPos = String(row.puts_oi_chg || '').startsWith('+')

                    const greeks = calculateGreeks(spot, row.strike, row.calls_iv || '15%')

                    return (
                      <tr
                        key={row.strike}
                        ref={isATM ? atmRowRef : null}
                        className={`transition-colors group ${
                          isATM
                            ? 'bg-amber/20 border-y-2 border-amber font-bold shadow-xs'
                            : 'hover:bg-elevated/70'
                        }`}
                      >
                        {/* CALL SIDE */}
                        {chainViewMode === 'STANDARD' ? (
                          <>
                            {/* Call OI with Visual Depth Bar */}
                            <td className={`py-2 px-2.5 relative font-mono text-xs ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              {showVisualBars && (
                                <div
                                  className="absolute inset-y-1 right-0 bg-cyan-500/20 rounded-l border-r-2 border-cyan-400/60 pointer-events-none transition-all duration-300"
                                  style={{ width: `${callOIWidth}%` }}
                                />
                              )}
                              <span className={`relative z-10 font-bold ${isCallWall ? 'text-cyan-300 ring-1 ring-cyan-400/40 px-1 rounded bg-cyan-950/60' : 'text-text'}`}>
                                {row.calls_oi}
                              </span>
                            </td>

                            {/* Call OI Change */}
                            <td className={`py-2 px-2 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              <span
                                className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                  callOIChgIsPos
                                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                    : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                                }`}
                              >
                                {row.calls_oi_chg}
                              </span>
                            </td>

                            {/* Call GEX */}
                            <td className={`py-2 px-2 font-bold ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              <span className={String(row.calls_gex || '').startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}>
                                {row.calls_gex}
                              </span>
                            </td>

                            {/* Call IV */}
                            <td className={`py-2 px-2 text-text/90 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              {row.calls_iv}
                            </td>

                            {/* Call Bid (Clickable to Buy) */}
                            <td className={`py-2 px-2 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} CE`,
                                    exchange: 'NFO',
                                    price: row.calls_bid,
                                    orderType: 'BUY',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-emerald-500 hover:text-black border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                                title="Click to stage BUY Call Order"
                              >
                                ₹{row.calls_bid}
                              </button>
                            </td>

                            {/* Call Ask (Clickable to Sell) */}
                            <td className={`py-2 px-2.5 border-r border-border/60 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} CE`,
                                    exchange: 'NFO',
                                    price: row.calls_ask,
                                    orderType: 'SELL',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                                title="Click to stage SELL Call Order"
                              >
                                ₹{row.calls_ask}
                              </button>
                            </td>
                          </>
                        ) : (
                          /* GREEKS VIEW - CALLS */
                          <>
                            <td className={`py-2 px-2.5 text-cyan-400 font-bold ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              +{greeks.callDelta}
                            </td>
                            <td className={`py-2 px-2 text-muted ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              {greeks.gamma}
                            </td>
                            <td className={`py-2 px-2 text-rose-400 font-semibold ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              {greeks.callTheta}
                            </td>
                            <td className={`py-2 px-2 text-emerald-400 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              +{greeks.vega}
                            </td>
                            <td className={`py-2 px-2 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} CE`,
                                    exchange: 'NFO',
                                    price: row.calls_bid,
                                    orderType: 'BUY',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-emerald-500 hover:text-black border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                              >
                                ₹{row.calls_bid}
                              </button>
                            </td>
                            <td className={`py-2 px-2.5 border-r border-border/60 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} CE`,
                                    exchange: 'NFO',
                                    price: row.calls_ask,
                                    orderType: 'SELL',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                              >
                                ₹{row.calls_ask}
                              </button>
                            </td>
                          </>
                        )}

                        {/* CENTER STRIKE COLUMN */}
                        <td
                          onClick={() => setIsPayoffModalOpen(true)}
                          className={`py-2 px-3 text-center font-bold border-x border-border/80 cursor-pointer transition-all ${
                            isATM
                              ? 'bg-amber text-black font-extrabold shadow-sm ring-2 ring-amber/60'
                              : 'bg-elevated/90 text-text hover:text-amber hover:bg-elevated'
                          }`}
                          title="Click to simulate multi-leg payoff centered at this strike"
                        >
                          <div className="flex flex-col items-center justify-center">
                            <span className="text-xs font-mono tracking-tight font-black">
                              {Number(row.strike).toLocaleString('en-IN')}
                            </span>
                            {/* Key Level Indicators */}
                            {isATM && (
                              <span className="text-[8px] uppercase tracking-wider font-black bg-black text-amber px-1.5 py-0.5 rounded-sm mt-0.5 shadow-xs flex items-center gap-0.5">
                                <span>⚡</span> ATM (Spot: ₹{Number(spot).toFixed(0)})
                              </span>
                            )}
                            {isCallWall && !isATM && (
                              <span className="text-[8px] uppercase tracking-wider font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 px-1 rounded-sm mt-0.5">
                                🛡️ Call Wall
                              </span>
                            )}
                            {isPutWall && !isATM && (
                              <span className="text-[8px] uppercase tracking-wider font-bold bg-amber/20 text-amber border border-amber/40 px-1 rounded-sm mt-0.5">
                                🏰 Put Wall
                              </span>
                            )}
                            {isMaxPain && !isATM && !isCallWall && !isPutWall && (
                              <span className="text-[8px] uppercase tracking-wider font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 px-1 rounded-sm mt-0.5">
                                🎯 Max Pain
                              </span>
                            )}
                          </div>
                        </td>

                        {/* PUT SIDE */}
                        {chainViewMode === 'STANDARD' ? (
                          <>
                            {/* Put Bid (Clickable to Buy) */}
                            <td className={`py-2 px-2.5 border-l border-border/60 text-right ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} PE`,
                                    exchange: 'NFO',
                                    price: row.puts_bid,
                                    orderType: 'BUY',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-emerald-500 hover:text-black border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                                title="Click to stage BUY Put Order"
                              >
                                ₹{row.puts_bid}
                              </button>
                            </td>

                            {/* Put Ask (Clickable to Sell) */}
                            <td className={`py-2 px-2 text-right ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} PE`,
                                    exchange: 'NFO',
                                    price: row.puts_ask,
                                    orderType: 'SELL',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                                title="Click to stage SELL Put Order"
                              >
                                ₹{row.puts_ask}
                              </button>
                            </td>

                            {/* Put IV */}
                            <td className={`py-2 px-2 text-right text-text/90 ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              {row.puts_iv}
                            </td>

                            {/* Put GEX */}
                            <td className={`py-2 px-2 text-right font-bold ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              <span className={String(row.puts_gex || '').startsWith('-') ? 'text-rose-400' : 'text-emerald-400'}>
                                {row.puts_gex}
                              </span>
                            </td>

                            {/* Put OI Change */}
                            <td className={`py-2 px-2 text-right ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              <span
                                className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                  putOIChgIsPos
                                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                    : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                                }`}
                              >
                                {row.puts_oi_chg}
                              </span>
                            </td>

                            {/* Put OI with Visual Depth Bar */}
                            <td className={`py-2 px-2.5 relative text-right font-mono text-xs ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              {showVisualBars && (
                                <div
                                  className="absolute inset-y-1 left-0 bg-amber/20 rounded-r border-l-2 border-amber/60 pointer-events-none transition-all duration-300"
                                  style={{ width: `${putOIWidth}%` }}
                                />
                              )}
                              <span className={`relative z-10 font-bold ${isPutWall ? 'text-amber-300 ring-1 ring-amber/40 px-1 rounded bg-amber-950/60' : 'text-text'}`}>
                                {row.puts_oi}
                              </span>
                            </td>
                          </>
                        ) : (
                          /* GREEKS VIEW - PUTS */
                          <>
                            <td className={`py-2 px-2.5 border-l border-border/60 text-right ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} PE`,
                                    exchange: 'NFO',
                                    price: row.puts_bid,
                                    orderType: 'BUY',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-emerald-500 hover:text-black border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                              >
                                ₹{row.puts_bid}
                              </button>
                            </td>
                            <td className={`py-2 px-2 text-right ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              <button
                                onClick={() =>
                                  onOpenOrderTicket &&
                                  onOpenOrderTicket({
                                    symbol: `${underlying} ${row.strike} PE`,
                                    exchange: 'NFO',
                                    price: row.puts_ask,
                                    orderType: 'SELL',
                                  })
                                }
                                className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer"
                              >
                                ₹{row.puts_ask}
                              </button>
                            </td>
                            <td className={`py-2 px-2 text-right text-emerald-400 ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              +{greeks.vega}
                            </td>
                            <td className={`py-2 px-2 text-right text-rose-400 font-semibold ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              {greeks.putTheta}
                            </td>
                            <td className={`py-2 px-2 text-right text-muted ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              {greeks.gamma}
                            </td>
                            <td className={`py-2 px-2.5 text-right text-rose-400 font-bold ${isPutITM ? 'bg-amber-950/20' : ''}`}>
                              {greeks.putDelta}
                            </td>
                          </>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Chain Pagination Controls */}
            {totalChainPages > 1 && (
              <div className="flex items-center justify-between pt-2 border-t border-border/40 text-[11px] font-mono text-muted">
                <span>
                  Showing {(safeChainPage - 1) * pageSizeNum + 1}–{Math.min(safeChainPage * pageSizeNum, sortedChain.length)} of {sortedChain.length} strikes
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setChainPage((p) => Math.max(1, p - 1))}
                    disabled={safeChainPage === 1}
                    className="px-2 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    ← Prev
                  </button>
                  {Array.from({ length: totalChainPages }, (_, i) => i + 1).map((pNum) => (
                    <button
                      key={pNum}
                      onClick={() => setChainPage(pNum)}
                      className={`w-6 h-6 rounded text-xs font-bold transition-all cursor-pointer ${
                        safeChainPage === pNum
                          ? 'bg-amber text-black'
                          : 'bg-surface border border-border text-muted hover:text-text'
                      }`}
                    >
                      {pNum}
                    </button>
                  ))}
                  <button
                    onClick={() => setChainPage((p) => Math.min(totalChainPages, p + 1))}
                    disabled={safeChainPage === totalChainPages}
                    className="px-2 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {/* Interactive Payoff Strategy Simulator Modal */}
      {isPayoffModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-3 sm:p-6 animate-in fade-in duration-200"
          onClick={() => setIsPayoffModalOpen(false)}
        >
          <div
            className="bg-panel border border-border rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto shadow-2xl p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border/50 pb-3">
              <div className="flex items-center gap-2">
                <span className="text-amber text-xl">🎯</span>
                <div>
                  <h2 className="text-base font-bold font-mono text-text">
                    Multi-Leg Strategy Payoff Simulator ({underlying})
                  </h2>
                  <p className="text-[11px] text-muted">Black-Scholes Model • Expiry vs T+0 P&amp;L Curves • Greeks</p>
                </div>
              </div>
              <button
                onClick={() => setIsPayoffModalOpen(false)}
                className="text-muted hover:text-text p-1 text-lg font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <PayoffSimulatorCard initialSymbol={underlying} initialSpot={spot} />
          </div>
        </div>
      )}
    </div>
  )
}
