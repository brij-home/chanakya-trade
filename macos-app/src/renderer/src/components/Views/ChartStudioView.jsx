import { useState, useEffect, useMemo, memo } from 'react'
import CandlestickChart from '../Charts/CandlestickChart'
import SmartTypeahead from '../Common/SmartTypeahead'
import { useRealtimeMarket } from '../../hooks/useRealtimeMarket'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import { formatLivePrice, formatLiveChange } from '../../utils/marketDataUtils'
import { getSymbolExchange } from '../../data/universeData'

/**
 * ChartStudioView — Dedicated Full-Screen Advanced Technical Workspace.
 * 
 * Provides an institutional-grade, full-viewport TradingView/Lightweight charting
 * environment with multi-timeframe controls, SMC order blocks, volume profile,
 * indicator toggles, and a sidecar intelligence deck for 1-click execution.
 */
function ChartStudioView({
  onOpenOrderTicket,
  initialSymbol = 'NIFTY',
  initialTimeframe = '15m',
}) {
  const { call } = useAPI()
  const { getTicker } = useRealtimeMarket()
  const activeView = useChatStore((s) => s.activeView)
  const setActiveView = useChatStore((s) => s.setActiveView)

  const [symbol, setSymbol] = useState(initialSymbol)
  const [timeframe, setTimeframe] = useState(initialTimeframe)
  const [layoutMode, setLayoutMode] = useState('single') // 'single' | 'dual'
  const [isSidecarOpen, setIsSidecarOpen] = useState(true)
  const [setupData, setSetupData] = useState(null)
  const [loadingSetup, setLoadingSetup] = useState(false)

  const resolvedExchange = useMemo(() => getSymbolExchange(symbol), [symbol])
  const liveTick = getTicker(symbol)
  const curLtp = liveTick?.ltp != null && Number(liveTick.ltp) > 0
    ? Number(liveTick.ltp)
    : (liveTick?.price != null && Number(liveTick.price) > 0 ? Number(liveTick.price) : null)

  // Fetch quick quantitative context & levels for sidecar
  useEffect(() => {
    let cancelled = false
    async function fetchSetup() {
      setLoadingSetup(true)
      try {
        const res = await call(`/skills/terminal/target_setup?symbol=${symbol}&timeframe=${timeframe}`)
        if (!cancelled && res?.data) {
          setSetupData(res.data)
        }
      } catch (_) {
        // Graceful fallback if setup endpoint fails
      } finally {
        if (!cancelled) setLoadingSetup(false)
      }
    }
    fetchSetup()
    return () => { cancelled = true }
  }, [symbol, timeframe])

  const timeframes = [
    { id: '1m', label: '1m' },
    { id: '5m', label: '5m' },
    { id: '15m', label: '15m' },
    { id: '1h', label: '1H' },
    { id: '1D', label: '1D' },
    { id: '1W', label: '1W' },
  ]

  const quickWatchlist = ['NIFTY', 'BANKNIFTY', 'RELIANCE', 'TCS', 'HDFCBANK', 'CRUDEOIL', 'GOLD']

  return (
    <div className="flex flex-col flex-1 h-full overflow-hidden" style={{ background: 'var(--color-bg)' }}>
      {/* ── Studio Top Action Bar ─────────────────────────────────────────── */}
      <div
        className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b glass-header flex-shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        {/* Left: Symbol Selector & Live Quote Pill */}
        <div className="flex items-center gap-2.5">
          <div className="w-52">
            <SmartTypeahead
              value={symbol}
              onChange={(sym) => setSymbol(sym.toUpperCase())}
              placeholder="Search ticker (e.g. RELIANCE)..."
            />
          </div>

          <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg border bg-surface/80 shadow-2xs" style={{ borderColor: 'var(--color-border)' }}>
            <span className="text-xs font-mono font-bold text-amber">{resolvedExchange}:</span>
            <span className="text-xs font-mono font-black" style={{ color: 'var(--color-text)' }}>
              {symbol}
            </span>
            <span className="text-xs font-mono font-black" style={{ color: 'var(--color-text)' }}>
              {formatLivePrice(curLtp ?? setupData?.live_quote?.ltp)}
            </span>
            <span className="text-[11px] font-mono font-bold text-emerald-500">
              {formatLiveChange(null, liveTick?.change_pct ?? setupData?.live_quote?.change_pct).pctText}
            </span>
          </div>

          {/* Quick symbol switcher chips */}
          <div className="hidden xl:flex items-center gap-1">
            {quickWatchlist.map((sym) => (
              <button
                key={sym}
                type="button"
                onClick={() => setSymbol(sym)}
                className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold transition-all cursor-pointer ${
                  symbol === sym
                    ? 'bg-amber/20 text-amber border border-amber/40 shadow-xs'
                    : 'text-muted hover:text-text hover:bg-surface border border-transparent'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>

        {/* Center: Timeframe Pills & Layout Split Switcher */}
        <div className="flex items-center gap-2">
          <div
            className="flex items-center p-0.5 rounded-lg border text-xs"
            style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
          >
            {timeframes.map((tf) => (
              <button
                key={tf.id}
                type="button"
                onClick={() => setTimeframe(tf.id)}
                className={`px-2 py-0.5 rounded-md font-mono text-[11px] font-bold transition-all cursor-pointer ${
                  timeframe === tf.id
                    ? 'bg-amber text-black shadow-xs'
                    : 'text-muted hover:text-text'
                }`}
              >
                {tf.label}
              </button>
            ))}
          </div>

          <div
            className="hidden sm:flex items-center p-0.5 rounded-lg border text-xs"
            style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
          >
            <button
              type="button"
              onClick={() => setLayoutMode('single')}
              className={`px-2 py-0.5 rounded-md font-mono text-[11px] font-bold transition-all cursor-pointer ${
                layoutMode === 'single'
                  ? 'bg-panel text-text shadow-xs border border-border'
                  : 'text-muted hover:text-text'
              }`}
              title="Single Chart View"
            >
              Single
            </button>
            <button
              type="button"
              onClick={() => setLayoutMode('dual')}
              className={`px-2 py-0.5 rounded-md font-mono text-[11px] font-bold transition-all cursor-pointer ${
                layoutMode === 'dual'
                  ? 'bg-panel text-text shadow-xs border border-border'
                  : 'text-muted hover:text-text'
              }`}
              title="Dual Timeframe Split (15m + 1D)"
            >
              Dual-TF
            </button>
          </div>
        </div>

        {/* Right: Sidecar Drawer Toggle & Terminal Return Action */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setActiveView('terminal')}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer border hover:bg-surface"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-dim)',
            }}
            title="Return to Strategic Quant Terminal Cockpit"
          >
            ← <span className="hidden sm:inline">Terminal Cockpit</span>
          </button>

          <button
            type="button"
            onClick={() => setIsSidecarOpen((p) => !p)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer border ${
              isSidecarOpen
                ? 'bg-amber/15 text-amber border-amber/40 shadow-xs'
                : 'text-muted border-border hover:text-text bg-surface'
            }`}
            title="Toggle Sidecar Intelligence Panel"
          >
            <span>⚡ Levels & Order</span>
          </button>
        </div>
      </div>

      {/* ── Main Canvas & Sidecar Container ───────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden relative">
        {/* Left / Center: Full Chart Viewport */}
        <div className="flex-1 flex flex-col h-full overflow-hidden p-2">
          {layoutMode === 'dual' ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 h-full">
              <div className="h-full flex flex-col rounded-xl overflow-hidden border bg-surface/50 p-2" style={{ borderColor: 'var(--color-border)' }}>
                <div className="flex items-center justify-between pb-1 px-1 border-b border-border/40 text-xs font-mono font-bold text-amber">
                  <span>⚡ 15m Intraday Structure (SMC Liquidity)</span>
                </div>
                <div className="flex-1 relative min-h-0 pt-1">
                  <CandlestickChart
                    key={`${symbol}-15m-${resolvedExchange}`}
                    symbol={symbol}
                    exchange={resolvedExchange}
                    timeframe="15m"
                    height={560}
                    livePrice={curLtp}
                  />
                </div>
              </div>
              <div className="h-full flex flex-col rounded-xl overflow-hidden border bg-surface/50 p-2" style={{ borderColor: 'var(--color-border)' }}>
                <div className="flex items-center justify-between pb-1 px-1 border-b border-border/40 text-xs font-mono font-bold text-emerald-500">
                  <span>💎 1D Positional Markup (Stage 2 Trend)</span>
                </div>
                <div className="flex-1 relative min-h-0 pt-1">
                  <CandlestickChart
                    key={`${symbol}-1D-${resolvedExchange}`}
                    symbol={symbol}
                    exchange={resolvedExchange}
                    timeframe="1D"
                    height={560}
                    livePrice={curLtp}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col rounded-xl overflow-hidden border bg-surface/50 p-2" style={{ borderColor: 'var(--color-border)' }}>
              <div className="flex-1 relative min-h-0">
                <CandlestickChart
                  key={`${symbol}-${timeframe}-${resolvedExchange}`}
                  symbol={symbol}
                  exchange={resolvedExchange}
                  timeframe={timeframe}
                  height={620}
                  livePrice={curLtp}
                />
              </div>
            </div>
          )}
        </div>

        {/* Right: Sidecar Intelligence Deck (Collapsible) */}
        {isSidecarOpen && (
          <aside
            className="w-80 flex-shrink-0 flex flex-col border-l glass-card overflow-y-auto p-3 space-y-3"
            style={{ borderColor: 'var(--color-border)' }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b pb-2 border-border/50">
              <span className="text-xs font-bold font-mono uppercase tracking-wider text-muted">
                Market Intelligence & Order
              </span>
              <button
                type="button"
                onClick={() => setIsSidecarOpen(false)}
                className="text-xs text-muted hover:text-text cursor-pointer"
                title="Collapse Sidecar"
              >
                ✕
              </button>
            </div>

            {/* SMC & Volume Profile Key Levels */}
            <div className="p-2.5 rounded-xl border bg-panel/70 space-y-2" style={{ borderColor: 'var(--color-border)' }}>
              <span className="text-[11px] font-bold text-amber font-mono block">
                🎯 Institutional Zones & POC
              </span>
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="p-1.5 rounded bg-surface/80 border border-border/50">
                  <span className="text-[9px] text-muted block uppercase">Unmitigated OB</span>
                  <span className="font-bold text-emerald-400">
                    {setupData?.order_block?.bottom && setupData?.order_block?.top
                      ? `₹${setupData.order_block.bottom} – ₹${setupData.order_block.top}`
                      : '—'}
                  </span>
                </div>
                <div className="p-1.5 rounded bg-surface/80 border border-border/50">
                  <span className="text-[9px] text-muted block uppercase">POC (Max Vol)</span>
                  <span className="font-bold text-amber">
                    {setupData?.volume_profile?.poc ? `₹${setupData.volume_profile.poc}` : '—'}
                  </span>
                </div>
                <div className="p-1.5 rounded bg-surface/80 border border-border/50">
                  <span className="text-[9px] text-muted block uppercase">VAH (70% High)</span>
                  <span className="font-bold text-blue-400">
                    {setupData?.volume_profile?.vah ? `₹${setupData.volume_profile.vah}` : '—'}
                  </span>
                </div>
                <div className="p-1.5 rounded bg-surface/80 border border-border/50">
                  <span className="text-[9px] text-muted block uppercase">VAL (70% Low)</span>
                  <span className="font-bold text-purple-400">
                    {setupData?.volume_profile?.val ? `₹${setupData.volume_profile.val}` : '—'}
                  </span>
                </div>
              </div>
            </div>

            {/* ATR Volatility & Setup Trigger */}
            <div className="p-2.5 rounded-xl border bg-panel/70 space-y-1.5" style={{ borderColor: 'var(--color-border)' }}>
              <span className="text-[11px] font-bold text-cyan-400 font-mono block">
                📐 Volatility & Execution Bounds
              </span>
              <div className="flex justify-between text-xs font-mono py-0.5 border-b border-border/30">
                <span className="text-muted">ATR-14 Volatility</span>
                <span className="font-bold text-text">
                  ₹{Number(setupData?.atr || (curLtp ? curLtp * 0.015 : 0)).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-xs font-mono py-0.5 border-b border-border/30">
                <span className="text-muted">Target 1 (2R Payoff)</span>
                <span className="font-bold text-emerald-400">
                  ₹{Number(setupData?.target_1 || (curLtp ? curLtp * 1.03 : 0)).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-xs font-mono py-0.5">
                <span className="text-muted">Stop Loss (1.5×ATR)</span>
                <span className="font-bold text-rose-400">
                  ₹{Number(setupData?.stop_loss || (curLtp ? curLtp * 0.985 : 0)).toFixed(2)}
                </span>
              </div>
            </div>

            {/* Quick Order Actions */}
            <div className="space-y-2 pt-1">
              <span className="text-[11px] font-bold font-mono text-muted uppercase block">
                ⚡ Rapid Order Staging
              </span>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => onOpenOrderTicket && onOpenOrderTicket({
                    symbol,
                    exchange: resolvedExchange,
                    action: 'BUY',
                    price: curLtp,
                    stop_loss: setupData?.stop_loss,
                    target: setupData?.target_1,
                  })}
                  className="w-full py-2 px-3 rounded-lg text-xs font-extrabold tracking-wide uppercase cursor-pointer transition-all shadow-md active:scale-98"
                  style={{
                    background: 'linear-gradient(135deg, #059669 0%, #047857 100%)',
                    color: '#ffffff',
                  }}
                >
                  ⚡ Buy / Long
                </button>
                <button
                  type="button"
                  onClick={() => onOpenOrderTicket && onOpenOrderTicket({
                    symbol,
                    exchange: resolvedExchange,
                    action: 'SELL',
                    price: curLtp,
                    stop_loss: setupData?.stop_loss,
                    target: setupData?.target_1,
                  })}
                  className="w-full py-2 px-3 rounded-lg text-xs font-extrabold tracking-wide uppercase cursor-pointer transition-all shadow-md active:scale-98"
                  style={{
                    background: 'linear-gradient(135deg, #e11d48 0%, #be123c 100%)',
                    color: '#ffffff',
                  }}
                >
                  🔻 Sell / Short
                </button>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}

export default memo(ChartStudioView)
