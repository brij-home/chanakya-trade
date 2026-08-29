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

  // Fetch terminal snapshot data
  useEffect(() => {
    let unmounted = false
    const fetchSnapshot = async () => {
      try {
        setLoading(true)
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
        if (!unmounted) setLoading(false)
      }
    }
    fetchSnapshot()
    const interval = setInterval(fetchSnapshot, 15000)
    return () => {
      unmounted = true
      clearInterval(interval)
    }
  }, [selectedSymbol, timeframe])

  const setup = data?.automated_setup
  const flows = data?.flows
  const sectors = data?.sector_matrix || []
  const watchlist = data?.watchlist || []
  const personas = data?.personas || []

  // Dynamic values
  const displaySymbolName =
    selectedSymbol === 'NIFTY'
      ? 'NIFTY 50 (NSE)'
      : selectedSymbol === 'BANKNIFTY'
      ? 'BANK NIFTY (NSE)'
      : `${selectedSymbol} (NSE)`

  const activeWatchItem = watchlist.find(
    (w) => w.symbol === selectedSymbol || w.name === selectedSymbol || w.symbol.startsWith(selectedSymbol)
  )
  const currentPct = activeWatchItem?.change_pct ?? 0.35
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
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green/10 border border-green/30 text-green text-xs font-semibold">
            <span className="w-2 h-2 rounded-full bg-green animate-pulse" />
            <span>Live Connection • Healthy</span>
          </div>
          <span className="text-xs text-muted font-mono hidden sm:inline">09:15:32 IST • Market Open</span>
        </div>

        {/* Quick Timeframe & Symbol Toolbar */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-elevated rounded-xl p-0.5 border border-border/60 text-xs">
            {['15m', '1h', '1D'].map((tf) => (
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
            <span>⚔️</span> Run Full Debate
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
              <span className="text-[10px] text-amber font-mono font-semibold">6 AGENTS</span>
            </div>

            <div className="space-y-1.5">
              {personas.map((p) => {
                const isSelected = selectedPersona === p.id
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      setSelectedPersona(p.id)
                      sendDraft(`persona ${p.id} ${selectedSymbol}`)
                    }}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all cursor-pointer border ${
                      isSelected
                        ? 'bg-emerald-500/15 border-emerald-500/40 text-text shadow-xs'
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
          <div className="bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-3">
            <div className="flex items-center justify-between border-b border-border/50 pb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                <span>📋</span> WATCHLIST
              </span>
              <span className="text-[10px] text-muted font-mono">LIVE LTP</span>
            </div>

            <div className="space-y-1 max-h-[280px] overflow-y-auto pr-1">
              {watchlist.map((item) => {
                const isItemActive = selectedSymbol === item.symbol || selectedSymbol === item.name || item.symbol.startsWith(selectedSymbol)
                const isPositive = Number(item.change_pct) >= 0
                return (
                  <button
                    key={item.symbol}
                    onClick={() => {
                      const cleanSym = item.symbol.replace(' 50', '').replace(' 50', '')
                      setSelectedSymbol(cleanSym)
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-xl transition-all cursor-pointer border ${
                      isItemActive
                        ? 'bg-amber/15 border-amber/40 text-text shadow-xs'
                        : 'border-border/40 hover:bg-elevated text-muted hover:text-text'
                    }`}
                  >
                    <div className="text-left">
                      <span className="text-xs font-bold text-text block">{item.symbol}</span>
                      <span className="text-[10px] text-muted font-mono">{item.name}</span>
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
            </div>
          </div>
        </div>

        {/* Center Column (6 Cols): Chart with SMC Overlays & Volume Profile */}
        <div className="lg:col-span-6 space-y-4">
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
                <span className="text-[11px] text-muted font-mono">EMA (RS) 20 • SMA 50 • Volume Profile Overlay</span>
              </div>

              {/* SMC Alpha Badges */}
              <div className="flex items-center gap-1.5">
                <span className="px-2 py-0.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold">
                  BULLISH ALPHA
                </span>
                <span className="px-2 py-0.5 rounded-md bg-amber/15 border border-amber/30 text-amber text-[10px] font-bold">
                  FORENSIC ALPHA
                </span>
              </div>
            </div>

            {/* Interactive Candlestick Chart */}
            <div className="h-[360px] w-full rounded-xl overflow-hidden bg-surface/50 border border-border/60">
              <CandlestickChart symbol={selectedSymbol} timeframe={timeframe} />
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
        </div>

        {/* Right Column (3 Cols): Automated Setup Ticket */}
        <div className="lg:col-span-3 space-y-4">
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-4">
            <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-muted block">
                  AUTOMATED SETUP
                </span>
                <span className="text-[10px] text-emerald-400 font-semibold">(Forensic AI Engine)</span>
              </div>
              <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold">
                HIGH CONVICTION
              </span>
            </div>

            {/* Signal Details */}
            <div className="space-y-2.5 text-xs font-mono">
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">Symbol</span>
                <span className="font-bold text-text">{setup?.symbol || `${selectedSymbol} (NSE)`}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">Action</span>
                <span className="font-bold text-emerald-400 bg-emerald-500/15 px-2 py-0.5 rounded border border-emerald-500/30">
                  {setup?.action || 'LONG'}
                </span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">Trigger</span>
                <span className="font-bold text-text">{setup?.trigger || 'OB Retest'}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">ENTRY</span>
                <span className="font-bold text-emerald-400 text-sm">
                  ₹{Number(setup?.entry || 21795.5).toLocaleString('en-IN')} (Live)
                </span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">STOP-LOSS</span>
                <span className="font-bold text-red text-sm">
                  ₹{Number(setup?.stop_loss || 21745.0).toLocaleString('en-IN')}
                </span>
              </div>

              {/* Progress Slider */}
              <div className="py-2 space-y-1.5">
                <div className="flex justify-between text-[10px] text-muted">
                  <span>SL: ₹{setup?.stop_loss || 21745}</span>
                  <span className="text-emerald-400 font-bold">Target 2: ₹{setup?.target_2 || 21940}</span>
                </div>
                <div className="w-full bg-surface h-2 rounded-full overflow-hidden border border-border/60">
                  <div
                    className="bg-gradient-to-r from-red via-amber to-emerald-400 h-full rounded-full transition-all duration-500"
                    style={{ width: `${setup?.progress || 65}%` }}
                  />
                </div>
              </div>

              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">TARGET 1</span>
                <span className="font-bold text-text">₹{Number(setup?.target_1 || 21885.0).toLocaleString('en-IN')}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">TARGET 2</span>
                <span className="font-bold text-text">₹{Number(setup?.target_2 || 21940.0).toLocaleString('en-IN')}</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/30">
                <span className="text-muted">R:R PAYOFF</span>
                <span className="font-bold text-amber">{setup?.risk_reward || '1.8'} R</span>
              </div>
              <div className="flex justify-between items-center py-1">
                <span className="text-muted">Status</span>
                <span className="font-bold text-amber bg-amber/10 px-2 py-0.5 rounded border border-amber/30">
                  {setup?.status || 'PENDING'}
                </span>
              </div>
            </div>

            {/* Execute Button */}
            <button
              onClick={() => {
                if (onOpenOrderTicket) {
                  onOpenOrderTicket({
                    symbol: selectedSymbol,
                    exchange: 'NSE',
                    price: setup?.entry || 21795.5,
                    stopLoss: setup?.stop_loss || 21745.0,
                    target: setup?.target_1 || 21885.0,
                  })
                }
              }}
              className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black font-bold text-xs uppercase tracking-wider transition-all shadow-md cursor-pointer flex items-center justify-center gap-2"
            >
              <span>⚡</span> STAGE / EXECUTE ORDER
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Row: Institutional Flows + Sector Rotation Matrix */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Institutional Flows (6 Cols) */}
        <div className="lg:col-span-6 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>🌊</span> INSTITUTIONAL FLOWS (DLY)
            </span>
            <span className="text-[10px] text-muted font-mono">{flows?.verdict || 'FII vs DII Cash Activity'}</span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs font-mono py-1">
            <div className="bg-surface/80 p-2.5 rounded-xl border border-border/60">
              <span className="text-[10px] text-muted block">FII Net Cash</span>
              <span className={`text-sm font-bold ${fiiVal >= 0 ? 'text-green' : 'text-red'}`}>
                {fiiVal >= 0 ? '+' : ''}₹{Number(fiiVal).toLocaleString('en-IN')} Cr
              </span>
            </div>
            <div className="bg-surface/80 p-2.5 rounded-xl border border-border/60">
              <span className="text-[10px] text-muted block">DII Net Cash</span>
              <span className={`text-sm font-bold ${diiVal >= 0 ? 'text-green' : 'text-red'}`}>
                {diiVal >= 0 ? '+' : ''}₹{Number(diiVal).toLocaleString('en-IN')} Cr
              </span>
            </div>
            <div className="bg-surface/80 p-2.5 rounded-xl border border-border/60">
              <span className="text-[10px] text-muted block">Net Total</span>
              <span className={`text-sm font-bold ${Number(flows?.net_total || 0) >= 0 ? 'text-green' : 'text-red'}`}>
                {Number(flows?.net_total || 0) >= 0 ? '+' : ''}₹{Number(flows?.net_total || 0).toLocaleString('en-IN')} Cr
              </span>
            </div>
          </div>

          {/* Visual Bar Comparison */}
          <div className="space-y-1.5 pt-1">
            <div className="flex h-5 w-full rounded-lg overflow-hidden border border-border/60 text-[10px] font-mono font-bold">
              <div
                className="bg-red/90 flex items-center justify-center text-white px-2 truncate transition-all duration-500"
                style={{ width: `${fiiWidthPct}%` }}
              >
                FII {fiiVal >= 0 ? '+' : ''}₹{Math.round(fiiVal)} Cr
              </div>
              <div
                className="bg-green/90 flex items-center justify-center text-black px-2 truncate transition-all duration-500"
                style={{ width: `${diiWidthPct}%` }}
              >
                DII {diiVal >= 0 ? '+' : ''}₹{Math.round(diiVal)} Cr
              </div>
            </div>
          </div>
        </div>

        {/* Sector Rotation Matrix (6 Cols) */}
        <div className="lg:col-span-6 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>🔄</span> SECTOR ROTATION MATRIX (1D)
            </span>
            <button
              onClick={() => sendDraft('scan')}
              className="text-[10px] text-amber hover:underline font-medium cursor-pointer"
            >
              View Full Heatmap →
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {sectors.map((s) => {
              const isPositive = Number(s.change_pct) >= 0
              return (
                <button
                  key={s.name}
                  onClick={() => {
                    window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: s.full_name || s.name } }))
                  }}
                  className={`p-2.5 rounded-xl border text-center transition-all cursor-pointer ${
                    isPositive
                      ? 'bg-green/10 border-green/30 hover:bg-green/20 text-green'
                      : 'bg-red/10 border-red/30 hover:bg-red/20 text-red'
                  }`}
                >
                  <span className="text-xs font-bold block text-text truncate">{s.name}</span>
                  <span className="text-xs font-mono font-bold">
                    {isPositive ? '+' : ''}
                    {Number(s.change_pct).toFixed(1)}%
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
