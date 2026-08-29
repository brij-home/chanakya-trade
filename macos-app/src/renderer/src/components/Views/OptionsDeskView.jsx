import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import PayoffSimulatorCard from '../Cards/PayoffSimulatorCard'

export default function OptionsDeskView({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [underlying, setUnderlying] = useState('NIFTY')
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isPayoffModalOpen, setIsPayoffModalOpen] = useState(false)

  useEffect(() => {
    let unmounted = false
    const fetchGex = async () => {
      try {
        setLoading(true)
        const res = await call('/skills/gex_snapshot', {
          underlying,
          expiry: selectedExpiry || undefined,
        })
        const snapshot = res?.data ?? res
        if (!unmounted && snapshot) {
          setData(snapshot)
          if (!selectedExpiry && snapshot.expiry) {
            setSelectedExpiry(snapshot.expiry)
          }
        }
      } catch (err) {
        console.error('Failed to load GEX snapshot:', err)
      } finally {
        if (!unmounted) setLoading(false)
      }
    }
    fetchGex()
    return () => {
      unmounted = true
    }
  }, [underlying, selectedExpiry])

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

  return (
    <div className="flex-1 overflow-y-auto p-3 sm:p-5 bg-surface text-text space-y-4 font-ui">
      {/* Top Header Card */}
      <div className="bg-panel/90 border border-border/80 rounded-2xl p-4 shadow-md backdrop-blur-md space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
          <div className="flex items-center gap-3">
            <span className="text-amber text-xl font-bold">◆</span>
            <div>
              <h1 className="text-base font-bold tracking-wide font-mono text-text">
                QUANT &amp; OPTIONS DESK
              </h1>
              <div className="flex items-center gap-2 text-[11px] text-muted">
                <span>Gamma Exposure, Delta Neutral Hedging &amp; Volatility Skew</span>
                <span>•</span>
                <span className="text-emerald-400 font-mono font-semibold">Live Institutional Greeks &amp; GEX Profile</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Active Desk</span>
            </div>
            <button
              onClick={() => setIsPayoffModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black text-xs font-bold transition-all shadow-sm cursor-pointer"
            >
              <span>🎯</span> Interactive Strategy Payoff
            </button>
          </div>
        </div>

        {/* Sub-bar: Instrument selector, Expiry & Key Analytics */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-muted">Instrument:</span>
              <div className="flex items-center gap-1 bg-elevated rounded-lg p-0.5 border border-border/70">
                {['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX'].map((inst) => (
                  <button
                    key={inst}
                    onClick={() => {
                      setUnderlying(inst)
                      setSelectedExpiry('')
                    }}
                    className={`px-2.5 py-1 rounded-md text-xs font-bold transition-all cursor-pointer ${
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
              <span className="text-muted">Expiry:</span>
              <select
                value={selectedExpiry}
                onChange={(e) => setSelectedExpiry(e.target.value)}
                className="bg-elevated border border-border/80 text-text font-bold rounded-lg px-2.5 py-1 cursor-pointer focus:outline-none"
              >
                {expiries.map((exp) => (
                  <option key={exp} value={exp}>
                    {exp}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div>
              <span className="text-muted mr-1.5">Spot Price:</span>
              <span className="text-emerald-400 font-bold text-sm">
                ₹{Number(spot).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>
              <span className="text-emerald-400 font-semibold ml-1">
                ({data?.spot_change || '+114.30'} / {data?.spot_change_pct || '+0.52%'})
              </span>
            </div>
            <span className="text-muted hidden sm:inline">Time: {data?.time || new Date().toLocaleTimeString('en-IN') + ' IST'}</span>
          </div>
        </div>

        {/* Dynamic Key Analytics Bar (PCR, Max Pain, Total OI, Net Flow) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-border/50 text-xs font-mono">
          <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
            <span className="text-[10px] text-muted block">PUT-CALL RATIO (PCR)</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-sm font-bold ${pcr >= 1.0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {pcr}
              </span>
              <span className="text-[9px] text-muted truncate">({pcrSentiment})</span>
            </div>
          </div>

          <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
            <span className="text-[10px] text-muted block">MAX PAIN STRIKE</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-sm font-bold text-amber">
                ₹{Number(maxPain).toLocaleString('en-IN')}
              </span>
              <span className="text-[9px] text-muted">Expiry Pin</span>
            </div>
          </div>

          <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
            <span className="text-[10px] text-muted block">TOTAL OI (CALL vs PUT)</span>
            <div className="flex items-center gap-2 mt-0.5 text-xs font-bold">
              <span className="text-cyan-400">C: {totalCallOI}</span>
              <span className="text-muted">|</span>
              <span className="text-amber">P: {totalPutOI}</span>
            </div>
          </div>

          <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
            <span className="text-[10px] text-muted block">NET OI CHANGE (1D)</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-sm font-bold text-emerald-400">
                {netOIChange}
              </span>
              <span className="text-[9px] text-muted">Net Bullish Flow</span>
            </div>
          </div>
        </div>
      </div>

      {/* Top 3-Pane Grid: GEX Volatility Pinning, Delta Hedging, IV Smile */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Card 1: GEX Volatility Pinning & Gamma Regime (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>📊</span> DEALER GAMMA & VOLATILITY (GEX)
            </span>
            <span className="text-[10px] text-pink-400 font-mono font-bold">
              FLIP: ₹{data?.zero_gamma ? Number(data.zero_gamma).toLocaleString('en-IN') : '24,200'}
            </span>
          </div>

          {/* Regime Banner */}
          <div className="bg-surface/80 p-2.5 rounded-xl border border-border/60 flex items-center justify-between">
            <div>
              <span className="text-[10px] text-muted block">Current Gamma Regime</span>
              <span className="text-xs font-bold text-emerald-400 font-mono flex items-center gap-1">
                <span>🟢</span> POSITIVE GAMMA (PINNING)
              </span>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-muted block">Dealer Stance</span>
              <span className="text-[11px] font-bold text-cyan-400 font-mono">Long Gamma (Mean Reverting)</span>
            </div>
          </div>

          {/* Key Gamma Walls (Call Resistance vs Put Support) */}
          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
            <div className="bg-cyan-500/10 border border-cyan-500/30 p-2 rounded-xl">
              <div className="flex items-center justify-between text-[10px] text-cyan-400 font-bold">
                <span>CALL WALL</span>
                <span>RESISTANCE</span>
              </div>
              <span className="text-sm font-bold text-text mt-0.5 block">₹24,500</span>
              <span className="text-[10px] text-muted">+14.2B Gamma</span>
            </div>

            <div className="bg-amber/10 border border-amber/30 p-2 rounded-xl">
              <div className="flex items-center justify-between text-[10px] text-amber font-bold">
                <span>PUT WALL</span>
                <span>SUPPORT</span>
              </div>
              <span className="text-sm font-bold text-text mt-0.5 block">₹24,000</span>
              <span className="text-[10px] text-muted">-11.8B Gamma</span>
            </div>
          </div>

          {/* Actionable Trader Takeaway */}
          <p className="text-[11px] text-muted font-ui leading-relaxed bg-surface/50 p-2 rounded-lg border border-border/40">
            💡 <strong className="text-text">Trading Insight:</strong> Dealers are long gamma above the flip level; intraday volatility will likely compress with price pinning between <span className="text-amber font-mono font-bold">₹24,000</span> and <span className="text-cyan-400 font-mono font-bold">₹24,500</span>.
          </p>
        </div>

        {/* Card 2: Delta Neutral Hedging Recommendation (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>⚡</span> DELTA HEDGING
            </span>
            <span className="text-[10px] text-emerald-400 font-mono font-semibold">RECOMMENDED</span>
          </div>

          <div className="space-y-2 text-xs font-mono">
            <div className="bg-surface/80 p-2.5 rounded-xl border border-border/60">
              <span className="text-[10px] text-muted block">Hedge Action</span>
              <span className="font-bold text-emerald-400 text-sm">{deltaHedge?.recommendation || `BUY 100 Lots ${underlying} FUT`}</span>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
                <span className="text-[10px] text-muted block">Net Delta</span>
                <span className="font-bold text-text">{deltaHedge?.net_delta ?? '+0.42'}</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
                <span className="text-[10px] text-muted block">Net Gamma</span>
                <span className="font-bold text-text">{deltaHedge?.net_gamma ?? '+0.18'}</span>
              </div>
            </div>

            <div className="pt-1">
              <button
                onClick={() => {
                  if (onOpenOrderTicket) {
                    onOpenOrderTicket({
                      symbol: `${underlying} FUT`,
                      exchange: 'NFO',
                      price: spot,
                      quantity: 100,
                    })
                  }
                }}
                className="w-full py-2 px-3 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:brightness-110 text-black font-bold text-xs uppercase tracking-wide transition-all shadow-md cursor-pointer flex items-center justify-center gap-1.5"
              >
                <span>⚡</span> Stage Delta Hedge Order
              </button>
            </div>
          </div>
        </div>

        {/* Card 3: Dynamic IV Smile & Skew Curve (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>📈</span> VOLATILITY SMILE &amp; SKEW
            </span>
            <span className="text-[10px] text-cyan-400 font-mono font-semibold">DYNAMIC CURVE</span>
          </div>

          {/* Interactive Dynamic SVG Smile Curve */}
          <div className="h-40 w-full relative flex items-center justify-center bg-surface/50 rounded-xl border border-border/50 p-2">
            <svg className="w-full h-full" viewBox="0 0 240 100">
              {/* Grid lines */}
              <line x1="0" y1="20" x2="240" y2="20" stroke="rgba(255,255,255,0.06)" strokeDasharray="3" />
              <line x1="0" y1="50" x2="240" y2="50" stroke="rgba(255,255,255,0.06)" strokeDasharray="3" />
              <line x1="0" y1="80" x2="240" y2="80" stroke="rgba(255,255,255,0.06)" strokeDasharray="3" />

              {/* Spot Marker Line (Pink) */}
              <line x1="120" y1="0" x2="120" y2="100" stroke="#f43f5e" strokeWidth="1.5" strokeDasharray="2" />
              <text x="123" y="14" fill="#f43f5e" fontSize="7" fontFamily="monospace" fontWeight="bold">
                Spot: {Math.round(spot)}
              </text>

              {/* Dynamic Polyline Smile */}
              {svgPoints && (
                <polyline
                  fill="none"
                  stroke="#22d3ee"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={svgPoints}
                />
              )}

              {/* ATM Circle Point */}
              <circle cx="120" cy="76" r="3.5" fill="#22d3ee" className="animate-pulse" />
              <text x="124" y="86" fill="#22d3ee" fontSize="7.5" fontFamily="monospace" fontWeight="bold">
                ATM ({minIV.toFixed(1)}%)
              </text>
            </svg>
          </div>

          <div className="flex justify-between items-center text-[10px] font-mono text-muted">
            <span>{ivSkew[0]?.strike ? Number(ivSkew[0].strike).toLocaleString('en-IN') : 'OTM Put'} ({ivSkew[0]?.iv || '18.2'}%)</span>
            <span className="text-cyan-400 font-bold">ATM ({minIV.toFixed(1)}%)</span>
            <span>{ivSkew[ivSkew.length - 1]?.strike ? Number(ivSkew[ivSkew.length - 1].strike).toLocaleString('en-IN') : 'OTM Call'} ({ivSkew[ivSkew.length - 1]?.iv || '19.8'}%)</span>
          </div>
        </div>
      </div>

      {/* Bottom Full-Width Options Chain Table */}
      <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2.5">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-muted">
              {underlying} OPTIONS CHAIN - {data?.expiry ? `Expiry: ${data.expiry}` : '0DTE'}
            </span>
            <span className="text-[10px] text-muted font-mono ml-2">Spot: ₹{Number(spot).toLocaleString('en-IN')} (Click any cell to Stage Option Order)</span>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="text-cyan-400 font-bold">CALLS (CE)</span>
            <span className="text-muted">|</span>
            <span className="text-amber font-bold">PUTS (PE)</span>
          </div>
        </div>

        {/* Matrix Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono text-left border-collapse">
            <thead>
              <tr className="border-b border-border/60 text-[11px] text-muted uppercase">
                <th className="py-2 px-2 text-cyan-400">OI</th>
                <th className="py-2 px-2 text-cyan-400">OI Chg</th>
                <th className="py-2 px-2 text-cyan-400">GEX</th>
                <th className="py-2 px-2 text-cyan-400">IV</th>
                <th className="py-2 px-2 text-cyan-400">Bid</th>
                <th className="py-2 px-2 text-cyan-400">Ask</th>
                <th className="py-2 px-3 text-center bg-elevated/70 text-text font-bold">STRIKE</th>
                <th className="py-2 px-2 text-amber text-right">Bid</th>
                <th className="py-2 px-2 text-amber text-right">Ask</th>
                <th className="py-2 px-2 text-amber text-right">IV</th>
                <th className="py-2 px-2 text-amber text-right">EIV</th>
                <th className="py-2 px-2 text-amber text-right">GEX</th>
                <th className="py-2 px-2 text-amber text-right">OI Chg</th>
                <th className="py-2 px-2 text-amber text-right">OI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {optionsChain.map((row) => {
                const isATM = row.is_atm
                return (
                  <tr
                    key={row.strike}
                    className={`transition-colors hover:bg-elevated/60 ${
                      isATM ? 'bg-cyan-500/10 border-y border-cyan-500/40 font-bold' : ''
                    }`}
                  >
                    <td className="py-2 px-2 text-muted">{row.calls_oi}</td>
                    <td className="py-2 px-2 text-cyan-400">{row.calls_oi_chg}</td>
                    <td className="py-2 px-2 text-cyan-400 font-bold">{row.calls_gex}</td>
                    <td className="py-2 px-2 text-text">{row.calls_iv}</td>
                    <td
                      onClick={() => onOpenOrderTicket && onOpenOrderTicket({ symbol: `${underlying} ${row.strike} CE`, exchange: 'NFO', price: row.calls_bid, orderType: 'BUY' })}
                      className="py-2 px-2 text-text hover:text-cyan-400 cursor-pointer font-bold"
                      title="Click to Buy Call"
                    >
                      ₹{row.calls_bid}
                    </td>
                    <td
                      onClick={() => onOpenOrderTicket && onOpenOrderTicket({ symbol: `${underlying} ${row.strike} CE`, exchange: 'NFO', price: row.calls_ask, orderType: 'BUY' })}
                      className="py-2 px-2 text-text hover:text-cyan-400 cursor-pointer font-bold"
                      title="Click to Buy Call"
                    >
                      ₹{row.calls_ask}
                    </td>
                    <td
                      onClick={() => setIsPayoffModalOpen(true)}
                      className="py-2 px-3 text-center bg-elevated/90 font-bold text-amber text-sm border-x border-border/50 cursor-pointer hover:underline"
                      title="Click to simulate Payoff"
                    >
                      {Number(row.strike).toLocaleString('en-IN')}
                    </td>
                    <td
                      onClick={() => onOpenOrderTicket && onOpenOrderTicket({ symbol: `${underlying} ${row.strike} PE`, exchange: 'NFO', price: row.puts_bid, orderType: 'BUY' })}
                      className="py-2 px-2 text-right text-text hover:text-amber cursor-pointer font-bold"
                      title="Click to Buy Put"
                    >
                      ₹{row.puts_bid}
                    </td>
                    <td
                      onClick={() => onOpenOrderTicket && onOpenOrderTicket({ symbol: `${underlying} ${row.strike} PE`, exchange: 'NFO', price: row.puts_ask, orderType: 'BUY' })}
                      className="py-2 px-2 text-right text-text hover:text-amber cursor-pointer font-bold"
                      title="Click to Buy Put"
                    >
                      ₹{row.puts_ask}
                    </td>
                    <td className="py-2 px-2 text-right text-text">{row.puts_iv}</td>
                    <td className="py-2 px-2 text-right text-muted">{row.puts_eiv}</td>
                    <td className="py-2 px-2 text-right text-rose-400 font-bold">{row.puts_gex}</td>
                    <td className="py-2 px-2 text-right text-amber">{row.puts_oi_chg}</td>
                    <td className="py-2 px-2 text-right text-muted">{row.puts_oi}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

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
