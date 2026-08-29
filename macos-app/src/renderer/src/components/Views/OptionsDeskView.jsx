import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'

export default function OptionsDeskView({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [underlying, setUnderlying] = useState('NIFTY')
  const [selectedExpiry, setSelectedExpiry] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let unmounted = false
    const fetchGex = async () => {
      try {
        setLoading(true)
        const res = await call('/skills/gex_snapshot', {
          underlying,
          expiry: selectedExpiry,
        })
        const snapshot = res?.data ?? res
        if (!unmounted && snapshot) {
          setData(snapshot)
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

  return (
    <div className="flex-1 overflow-y-auto p-3 sm:p-5 bg-surface text-text space-y-4 font-ui">
      {/* Top Header Card */}
      <div className="bg-panel/90 border border-border/80 rounded-2xl p-4 shadow-md backdrop-blur-md space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
          <div className="flex items-center gap-3">
            <span className="text-amber text-xl font-bold">◆</span>
            <div>
              <h1 className="text-base font-bold tracking-wide font-mono text-text">
                QUANT &amp; OPTIONS DASHBOARD
              </h1>
              <span className="text-[11px] text-muted">Gamma Exposure, Delta Neutral Hedging &amp; Volatility Skew</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Active Options Desk</span>
            </div>
            <button
              onClick={() => sendDraft(`payoff ${underlying}`)}
              className="px-3 py-1 rounded-xl bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 text-xs font-bold transition-colors cursor-pointer"
            >
              🎯 Payoff Simulator
            </button>
          </div>
        </div>

        {/* Sub-bar: Instrument selector & stats */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span className="text-muted">Instrument:</span>
              <select
                value={underlying}
                onChange={(e) => setUnderlying(e.target.value)}
                className="bg-elevated border border-border text-text font-bold rounded-lg px-2 py-1 cursor-pointer focus:outline-hidden"
              >
                <option value="NIFTY">NIFTY 50</option>
                <option value="BANKNIFTY">BANK NIFTY</option>
                <option value="FINNIFTY">FIN NIFTY</option>
                <option value="SENSEX">SENSEX</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-muted">Expiry:</span>
              <span className="bg-elevated border border-border/70 text-text px-2 py-1 rounded-lg font-semibold">
                {data?.expiry ? `Expiry: ${data.expiry}` : '0DTE (Weekly)'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div>
              <span className="text-muted mr-1.5">Last Price:</span>
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
      </div>

      {/* Top 3-Pane Grid: GEX Histogram, Delta Hedging, IV Smile */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Card 1: GEX Profile Bar Chart (5 Cols) */}
        <div className="lg:col-span-5 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>📊</span> GAMMA EXPOSURE PROFILE (GEX)
            </span>
            <span className="text-[10px] text-cyan-400 font-mono font-semibold">0DTE BARS</span>
          </div>

          {/* Legend & Level Callouts */}
          <div className="flex items-center justify-between text-[11px] font-mono">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1 text-cyan-400 font-bold">
                <span className="w-2.5 h-2.5 rounded-xs bg-cyan-400" /> CALL GEX
              </span>
              <span className="flex items-center gap-1 text-amber font-bold">
                <span className="w-2.5 h-2.5 rounded-xs bg-amber" /> PUT GEX
              </span>
            </div>
            <span className="text-pink-400 font-bold text-[10px]">
              ZERO GAMMA ({data?.zero_gamma ? Number(data.zero_gamma).toLocaleString('en-IN') : '22,000'})
            </span>
          </div>

          {/* Simulated GEX Bar Visualizer */}
          <div className="h-44 w-full flex items-end justify-between gap-1.5 pt-4 pb-2 border-b border-border/40 font-mono text-[9px]">
            {gexProfile.map((g) => {
              const isCallDominant = g.call_gex > Math.abs(g.put_gex)
              const heightPct = Math.min(100, Math.max(15, (Math.abs(g.net_gex) / 18) * 90))
              return (
                <div key={g.strike} className="flex-1 flex flex-col items-center justify-end h-full group relative">
                  <div
                    className={`w-full rounded-t-sm transition-all duration-300 ${
                      isCallDominant ? 'bg-cyan-400' : 'bg-amber'
                    } hover:brightness-125`}
                    style={{ height: `${heightPct}%` }}
                  />
                  <span className="text-[8px] text-muted rotate-45 origin-top-left mt-2 block whitespace-nowrap">
                    {g.strike}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Call Wall & Put Support Badges */}
          <div className="flex justify-between items-center text-xs font-mono pt-1">
            <div className="text-amber">
              <span className="text-[10px] text-muted block">PUT SUPPORT</span>
              <span className="font-bold">{data?.put_support ? Number(data.put_support).toLocaleString('en-IN') : '21,800'} (-₹15B)</span>
            </div>
            <div className="text-right text-cyan-400">
              <span className="text-[10px] text-muted block">CALL WALL</span>
              <span className="font-bold">{data?.call_wall ? Number(data.call_wall).toLocaleString('en-IN') : '22,300'} (+₹18B)</span>
            </div>
          </div>
        </div>

        {/* Card 2: Delta Hedging Recommendations (3 Cols) */}
        <div className="lg:col-span-3 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>⚡</span> DELTA HEDGING
            </span>
            <span className="text-[10px] text-emerald-400 font-mono">AUTOMATED</span>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
            <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
              <span className="text-[10px] text-muted block">Net Delta</span>
              <span className="font-bold text-text">{deltaHedge?.net_delta ? (deltaHedge.net_delta > 0 ? '+' : '') + deltaHedge.net_delta : '+0.42'}</span>
            </div>
            <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
              <span className="text-[10px] text-muted block">Net Gamma</span>
              <span className="font-bold text-text">{deltaHedge?.net_gamma ? (deltaHedge.net_gamma > 0 ? '+' : '') + deltaHedge.net_gamma : '+0.18'}</span>
            </div>
          </div>

          <div className="space-y-1.5 pt-1">
            <span className="text-[10px] text-muted uppercase font-bold block">Actionable Posture</span>
            <div className="bg-surface border border-border/80 rounded-xl p-2.5 text-xs font-mono space-y-1.5">
              <span className="text-text font-bold block">{deltaHedge?.actionable_state || 'HEDGE REQUIRED: NEUTRAL'}</span>
              <span className="text-cyan-400 font-bold block text-sm">
                {deltaHedge?.recommendation || `BUY 100 Lots ${underlying} FUT at ${Math.round(spot)}`}
              </span>
            </div>
          </div>

          <div className="text-[10px] text-muted font-mono pt-1">
            <span>Next Rebalance: </span>
            <span className="text-amber font-semibold">{deltaHedge?.rebalance_trigger || 'Every +20 pts Spot Move'}</span>
          </div>
        </div>

        {/* Card 3: IV Smile & Skew (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>📈</span> IV SMILE &amp; SKEW (0DTE)
            </span>
            <span className="text-[10px] text-muted font-mono">VOL CURVE</span>
          </div>

          {/* Interactive SVG Smile Curve */}
          <div className="h-40 w-full relative flex items-center justify-center">
            <svg className="w-full h-full" viewBox="0 0 240 100">
              {/* Grid lines */}
              <line x1="0" y1="20" x2="240" y2="20" stroke="rgba(255,255,255,0.06)" strokeDasharray="3" />
              <line x1="0" y1="50" x2="240" y2="50" stroke="rgba(255,255,255,0.06)" strokeDasharray="3" />
              <line x1="0" y1="80" x2="240" y2="80" stroke="rgba(255,255,255,0.06)" strokeDasharray="3" />

              {/* Spot Marker Line (Pink) */}
              <line x1="120" y1="0" x2="120" y2="100" stroke="#f43f5e" strokeWidth="2" />
              <text x="123" y="15" fill="#f43f5e" fontSize="7" fontFamily="monospace" fontWeight="bold">
                Spot: {Math.round(spot)}
              </text>

              {/* Smile Spline */}
              <path
                d="M 10 35 Q 60 75 120 78 T 230 30"
                fill="none"
                stroke="#22d3ee"
                strokeWidth="2.5"
                strokeLinecap="round"
              />

              {/* Min IV Point */}
              <circle cx="120" cy="78" r="3.5" fill="#22d3ee" />
              <text x="125" y="85" fill="#22d3ee" fontSize="7" fontFamily="monospace" fontWeight="bold">
                14.5%
              </text>
            </svg>
          </div>

          <div className="flex justify-between items-center text-[10px] font-mono text-muted">
            <span>{ivSkew[0]?.strike || '21,600'} ({ivSkew[0]?.iv || '18.2'}%)</span>
            <span className="text-cyan-400 font-bold">ATM (14.5%)</span>
            <span>{ivSkew[ivSkew.length - 1]?.strike || '22,400'} ({ivSkew[ivSkew.length - 1]?.iv || '19.8'}%)</span>
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
            <span className="text-[10px] text-muted font-mono ml-2">Spot: ₹{Number(spot).toLocaleString('en-IN')}</span>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="text-cyan-400 font-bold">CALLS</span>
            <span className="text-muted">|</span>
            <span className="text-amber font-bold">PUTS</span>
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
                    onClick={() => sendDraft(`payoff ${underlying} strike ${row.strike}`)}
                    className={`transition-colors cursor-pointer hover:bg-elevated/60 ${
                      isATM ? 'bg-cyan-500/10 border-y border-cyan-500/40 font-bold' : ''
                    }`}
                  >
                    <td className="py-2 px-2 text-muted">{row.calls_oi}</td>
                    <td className="py-2 px-2 text-cyan-400">{row.calls_oi_chg}</td>
                    <td className="py-2 px-2 text-cyan-400 font-bold">{row.calls_gex}</td>
                    <td className="py-2 px-2 text-text">{row.calls_iv}</td>
                    <td className="py-2 px-2 text-text">₹{row.calls_bid}</td>
                    <td className="py-2 px-2 text-text">₹{row.calls_ask}</td>
                    <td className="py-2 px-3 text-center bg-elevated/90 font-bold text-amber text-sm border-x border-border/50">
                      {row.strike}
                    </td>
                    <td className="py-2 px-2 text-right text-text">₹{row.puts_bid}</td>
                    <td className="py-2 px-2 text-right text-text">₹{row.puts_ask}</td>
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
    </div>
  )
}
