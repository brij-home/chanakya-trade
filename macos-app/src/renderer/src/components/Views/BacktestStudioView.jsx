import { useState, useEffect, useMemo } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import { formatINR, formatINRFull, formatPct } from '../../utils/formatINR'
import SmartTypeahead from '../Common/SmartTypeahead'
import UnavailableState from '../Common/UnavailableState'
import { fuzzySearchUniverse, getSymbolExchange } from '../../data/universeData'

const STRATEGY_PRESETS = [
  { id: 'rsi', name: 'RSI Mean Reversion', icon: '📉', desc: 'RSI(14) oversold <30 buy, overbought >70 exit' },
  { id: 'ema', name: 'EMA Crossover (9/21)', icon: '⚡', desc: 'Fast EMA 9 crossing Slow EMA 21 trend continuation' },
  { id: 'bb', name: 'Bollinger Band Squeeze', icon: '🎯', desc: '20-SMA with 2.0 std dev volatility breakout' },
  { id: 'supertrend', name: 'SuperTrend Trend Follower', icon: '🚀', desc: '10-period ATR 3.0 trailing trend rider' },
  { id: 'donchian', name: 'Donchian 20D Channel', icon: '📊', desc: 'Turtle 20-day high breakout with ATR stop-loss' },
  { id: 'smc', name: 'SMC Order Block Sniper', icon: '🎪', desc: 'ICT CHoCH, Fair Value Gap & Order Block sweep' },
]

const TIMEFRAMES = ['1D', '1H', '15m', '5m']
const PERIODS = ['1Y', '2Y', '3Y', '5Y', 'YTD']

export default function BacktestStudioView({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const startActivity = useChatStore((s) => s.startActivity)
  const updateActivity = useChatStore((s) => s.updateActivity)
  const stopActivity = useChatStore((s) => s.stopActivity)

  // Configuration State
  const [symbol, setSymbol] = useState('RELIANCE')
  const [inputSymbol, setInputSymbol] = useState('')
  const [showTypeahead, setShowTypeahead] = useState(false)
  const [typeaheadIndex, setTypeaheadIndex] = useState(0)
  const [strategy, setStrategy] = useState('rsi')
  const [timeframe, setTimeframe] = useState('1D')
  const [period, setPeriod] = useState('2Y')
  const [initialCapital, setInitialCapital] = useState(1000000)
  const [riskPerTrade, setRiskPerTrade] = useState(1.5)

  // Execution & Results State
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [tradeFilter, setTradeFilter] = useState('ALL') // 'ALL' | 'WIN' | 'LOSS'
  const [tradePage, setTradePage] = useState(1)
  const pageSize = 8

  // Typeahead suggestions
  const typeaheadResults = useMemo(() => {
    if (!inputSymbol.trim()) return []
    return fuzzySearchUniverse(inputSymbol, 6)
  }, [inputSymbol])

  // Run Quantitative Simulation
  const executeBacktest = async (targetSymbol = symbol, targetStrat = strategy) => {
    setLoading(true)
    const stratName = STRATEGY_PRESETS.find((s) => s.id === targetStrat)?.name || targetStrat
    const title = `Backtest: ${targetSymbol} (${stratName})`
    const abortController = new AbortController()

    startActivity({
      title,
      details: `Running ${period} simulation on ${targetSymbol}...`,
      type: 'backtest',
      targetView: 'backtest',
      cancelFn: () => {
        try { abortController.abort() } catch {}
        setLoading(false)
        stopActivity()
      },
    })

    try {
      const res = await call(
        '/skills/backtest',
        {
          symbol: targetSymbol,
          strategy: targetStrat,
          timeframe,
          period,
          initial_capital: initialCapital,
          risk_pct: riskPerTrade,
        },
        { signal: abortController.signal }
      )
      const resData = res?.data ?? res
      if (resData) {
        setData(resData)
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Backtest error:', err)
      }
    } finally {
      setLoading(false)
      stopActivity()
    }
  }

  // Run on mount
  useEffect(() => {
    executeBacktest(symbol, strategy)
  }, []) // eslint-disable-line

  // Normalized summary metrics
  const r = data?.data ?? data ?? {}
  const requiredMetrics = ['total_return', 'cagr', 'sharpe_ratio', 'max_drawdown', 'win_rate', 'total_trades', 'profit_factor']
  const hasBacktestData = requiredMetrics.every((key) => Number.isFinite(Number(r[key]))) && Array.isArray(r.equity_curve) && r.equity_curve.length > 1

  if (!loading && !hasBacktestData) {
    return (
      <div className="flex h-full items-center justify-center p-6" style={{ background: 'var(--color-surface)' }}>
        <UnavailableState
          title="Backtest results unavailable"
          reason="The backtest did not return a complete, reproducible result set. No performance figures or simulated trades are shown."
          hint="Check the historical-data provider, then run the backtest again."
          onRetry={() => executeBacktest()}
          size="lg"
        />
      </div>
    )
  }

  const totalReturn = Number(r.total_return)
  const cagr = Number(r.cagr)
  const sharpe = Number(r.sharpe_ratio)
  const maxDd = Number(r.max_drawdown)
  const winRate = Number(r.win_rate)
  const totalTrades = Number(r.total_trades)
  const profitFactor = Number(r.profit_factor)
  const isPos = totalReturn >= 0

  const rawCurve = Array.isArray(r.equity_curve) ? r.equity_curve : []

  const equityCurve = rawCurve.map((p, i) => ({
    step: i,
    value: typeof p === 'number' ? p : Number(p?.value),
    benchmark: typeof p === 'object' && Number.isFinite(Number(p?.benchmark)) ? Number(p.benchmark) : null,
  }))

  const peakValue = equityCurve.length ? Math.max(...equityCurve.map((p) => p.value)) : initialCapital
  const finalValue = equityCurve[equityCurve.length - 1]?.value || initialCapital
  const netPnL = finalValue - initialCapital

  const rawTrades = Array.isArray(r.trades) ? r.trades : []

  const allTrades = rawTrades.map((t, i) => {
    const pnlVal = Number(t.pnl ?? 0)
    const pnlPct = Number(t.pnl_pct ?? t.pct ?? 0)
    const entryVal = Number(t.entry_price ?? t.entry ?? 0)
    const exitVal = Number(t.exit_price ?? t.exit ?? 0)
    const direction = String(t.direction || t.type || 'LONG').toUpperCase()
    const rMultiple = t.r != null ? Number(t.r) : (pnlPct !== 0 ? pnlPct / 0.8 : 0)
    const tradeDate = t.entry_date || t.date || `Day ${i + 1}`
    const exitReason = t.signal || t.reason || 'Target / Trailing exit'

    return {
      date: tradeDate,
      type: direction,
      entry: entryVal,
      exit: exitVal,
      pnl: pnlVal,
      pct: pnlPct,
      r: Number.isFinite(rMultiple) ? rMultiple : 0,
      reason: exitReason,
    }
  })

  const filteredTrades = allTrades.filter((t) => {
    if (tradeFilter === 'WIN') return t.pnl > 0
    if (tradeFilter === 'LOSS') return t.pnl <= 0
    return true
  })

  const paginatedTrades = filteredTrades.slice((tradePage - 1) * pageSize, tradePage * pageSize)
  const totalPages = Math.ceil(filteredTrades.length / pageSize) || 1

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 sm:p-6 space-y-5 animate-fade-slide" style={{ background: 'var(--color-surface)' }}>
      {/* ── Header & Config Rail ────────────────────────────────────────── */}
      <div className="bg-panel border border-border/80 rounded-2xl p-4 sm:p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl">⚡</span>
              <h1 className="text-lg sm:text-xl font-black font-ui tracking-wide" style={{ color: 'var(--color-text)' }}>
                Quantitative Backtest Studio
              </h1>
              <span className="text-[10px] font-mono font-bold bg-amber/15 text-amber border border-amber/30 px-2 py-0.5 rounded-full">
                Vectorized Execution Engine
              </span>
            </div>
            <p className="text-xs text-muted mt-1">
              Multi-regime strategy validation · Indian F&O & Cash Equities · Walk-forward analysis
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => executeBacktest(symbol, strategy)}
              disabled={loading}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-amber hover:bg-amber/90 text-black font-black text-xs uppercase tracking-wider transition-all shadow-md cursor-pointer disabled:opacity-50"
            >
              <span>{loading ? '⏳' : '⚡'}</span>
              <span>{loading ? 'Simulating...' : 'Run Backtest'}</span>
            </button>
          </div>
        </div>

        {/* Configuration Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 pt-3 border-t border-border/50 text-xs">
          {/* Symbol input with Typeahead */}
          <div className="relative">
            <label className="text-[10px] font-bold uppercase text-muted block mb-1">Underlying Symbol</label>
            <input
              type="text"
              value={inputSymbol || symbol}
              onChange={(e) => {
                setInputSymbol(e.target.value.toUpperCase())
                setShowTypeahead(true)
              }}
              onFocus={() => setShowTypeahead(true)}
              onBlur={() => setTimeout(() => setShowTypeahead(false), 200)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const pick = typeaheadResults[typeaheadIndex]?.symbol || inputSymbol || symbol
                  setSymbol(pick)
                  setInputSymbol('')
                  setShowTypeahead(false)
                  executeBacktest(pick, strategy)
                }
              }}
              placeholder="e.g. RELIANCE, NIFTY"
              className="w-full bg-elevated border border-border rounded-xl px-3 py-2 text-text font-bold font-mono uppercase focus:border-amber outline-none"
            />

            {showTypeahead && (
              <SmartTypeahead
                query={inputSymbol}
                isOpen={showTypeahead}
                results={typeaheadResults}
                selectedIndex={typeaheadIndex}
                setSelectedIndex={setTypeaheadIndex}
                onSelect={(item) => {
                  setSymbol(item.symbol)
                  setInputSymbol('')
                  setShowTypeahead(false)
                  executeBacktest(item.symbol, strategy)
                }}
                onClose={() => setShowTypeahead(false)}
                position="below"
              />
            )}
          </div>

          {/* Strategy Preset */}
          <div>
            <label className="text-[10px] font-bold uppercase text-muted block mb-1">Strategy Model</label>
            <select
              value={strategy}
              onChange={(e) => {
                setStrategy(e.target.value)
                executeBacktest(symbol, e.target.value)
              }}
              className="w-full bg-elevated border border-border rounded-xl px-3 py-2 text-text font-bold focus:border-amber outline-none cursor-pointer"
            >
              {STRATEGY_PRESETS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.icon} {s.name}
                </option>
              ))}
            </select>
          </div>

          {/* Timeframe */}
          <div>
            <label className="text-[10px] font-bold uppercase text-muted block mb-1">Bar Timeframe</label>
            <div className="flex rounded-xl bg-elevated border border-border p-0.5">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-bold font-mono transition-all cursor-pointer ${
                    timeframe === tf ? 'bg-amber text-black shadow-sm' : 'text-muted hover:text-text'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          {/* Lookback Period */}
          <div>
            <label className="text-[10px] font-bold uppercase text-muted block mb-1">Lookback Window</label>
            <div className="flex rounded-xl bg-elevated border border-border p-0.5">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-bold font-mono transition-all cursor-pointer ${
                    period === p ? 'bg-amber text-black shadow-sm' : 'text-muted hover:text-text'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Initial Capital */}
          <div>
            <label className="text-[10px] font-bold uppercase text-muted block mb-1">Capital (₹)</label>
            <select
              value={initialCapital}
              onChange={(e) => setInitialCapital(Number(e.target.value))}
              className="w-full bg-elevated border border-border rounded-xl px-3 py-2 text-text font-bold font-mono focus:border-amber outline-none cursor-pointer"
            >
              <option value={200000}>₹2 Lakh (Retail Base)</option>
              <option value={500000}>₹5 Lakh (Standard)</option>
              <option value={1000000}>₹10 Lakh (HNI Core)</option>
              <option value={2500000}>₹25 Lakh (Institutional)</option>
              <option value={10000000}>₹1 Crore (Prop Desk)</option>
            </select>
          </div>
        </div>
      </div>

      {/* ── Top Performance KPI Scorecard ───────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Net Return */}
        <div className="bg-panel border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-[10px] uppercase font-bold text-muted font-ui block">Net Return</span>
          <div className="flex items-baseline gap-1.5">
            <span className={`text-xl font-black font-mono tabular-nums ${isPos ? 'text-green' : 'text-red'}`}>
              {isPos ? '+' : ''}{totalReturn.toFixed(2)}%
            </span>
          </div>
          <span className="text-[10px] text-muted font-mono block">
            PnL: <strong className={isPos ? 'text-green' : 'text-red'}>{formatINR(netPnL)}</strong>
          </span>
        </div>

        {/* CAGR */}
        <div className="bg-panel border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-[10px] uppercase font-bold text-muted font-ui block">CAGR</span>
          <span className="text-xl font-black font-mono text-text tabular-nums block">
            +{cagr.toFixed(2)}%
          </span>
          <span className="text-[10px] text-muted font-ui block">Annualized rate</span>
        </div>

        {/* Sharpe Ratio */}
        <div className="bg-panel border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-[10px] uppercase font-bold text-muted font-ui block">Sharpe Ratio</span>
          <span className="text-xl font-black font-mono text-amber tabular-nums block">
            {sharpe.toFixed(2)}
          </span>
          <span className="text-[10px] text-muted font-ui block">
            {sharpe >= 1.5 ? 'Institutional Grade' : 'Standard Alpha'}
          </span>
        </div>

        {/* Max Drawdown */}
        <div className="bg-panel border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-[10px] uppercase font-bold text-muted font-ui block">Max Drawdown</span>
          <span className="text-xl font-black font-mono text-red tabular-nums block">
            {maxDd.toFixed(2)}%
          </span>
          <span className="text-[10px] text-muted font-ui block">Peak-to-trough</span>
        </div>

        {/* Win Rate */}
        <div className="bg-panel border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-[10px] uppercase font-bold text-muted font-ui block">Win Rate</span>
          <span className="text-xl font-black font-mono text-green tabular-nums block">
            {winRate.toFixed(1)}%
          </span>
          <span className="text-[10px] text-muted font-mono block">
            {Math.round(totalTrades * winRate / 100)}W / {totalTrades - Math.round(totalTrades * winRate / 100)}L
          </span>
        </div>

        {/* Profit Factor */}
        <div className="bg-panel border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-[10px] uppercase font-bold text-muted font-ui block">Profit Factor</span>
          <span className="text-xl font-black font-mono text-cyan-400 tabular-nums block">
            {profitFactor.toFixed(2)}×
          </span>
          <span className="text-[10px] text-muted font-ui block">Gross Win / Gross Loss</span>
        </div>
      </div>

      {/* ── Main Visualizations: Equity Curve & Benchmark ────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Equity Curve SVG Chart (8 Cols) */}
        <div className="lg:col-span-8 bg-panel border border-border rounded-2xl p-5 shadow-sm space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
            <div>
              <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">
                Equity Progression vs Benchmark
              </span>
              <h2 className="text-sm font-bold text-text">
                {symbol} ({STRATEGY_PRESETS.find(s => s.id === strategy)?.name}) vs NIFTY 50
              </h2>
            </div>
            <div className="flex items-center gap-4 text-xs font-mono">
              <span className="flex items-center gap-1.5 text-green">
                <span className="w-3 h-1 bg-green rounded-full inline-block" /> Strategy Portfolio
              </span>
              <span className="flex items-center gap-1.5 text-muted">
                <span className="w-3 h-0.5 bg-muted border-dashed inline-block" /> NIFTY 50 (Benchmark)
              </span>
              <span className="text-amber">
                Peak: <strong>{formatINR(peakValue)}</strong>
              </span>
            </div>
          </div>

          <div className="relative bg-surface rounded-xl p-3 border border-border/40 overflow-hidden">
            <InteractiveEquityChart curve={equityCurve} isPositive={isPos} />
          </div>
        </div>

        {/* Strategy Description & Parameter Tuning (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border rounded-2xl p-5 shadow-sm space-y-4 flex flex-col justify-between">
          <div className="space-y-3">
            <div className="border-b border-border/50 pb-2.5">
              <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">Strategy Architecture</span>
              <h3 className="text-sm font-extrabold text-amber mt-0.5">
                {STRATEGY_PRESETS.find(s => s.id === strategy)?.name}
              </h3>
            </div>
            <p className="text-xs text-text/80 leading-relaxed font-ui">
              {STRATEGY_PRESETS.find(s => s.id === strategy)?.desc}
            </p>

            <div className="space-y-2 pt-2 border-t border-border/40 text-xs">
              <div className="flex justify-between">
                <span className="text-muted">Risk/Trade Cap:</span>
                <span className="font-mono font-bold text-text">{riskPerTrade}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Execution Mode:</span>
                <span className="font-mono font-bold text-amber">Next-Bar Open (Zero Lookahead)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Slippage + Brokerage:</span>
                <span className="font-mono font-bold text-text">0.05% per leg modeled</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Trailing Stop Rule:</span>
                <span className="font-mono font-bold text-emerald-400">2.5× ATR Dynamic Trail</span>
              </div>
            </div>
          </div>

          <div className="space-y-2 pt-4 border-t border-border/50">
            <button
              onClick={() => {
                const exch = getSymbolExchange(symbol)
                sendDraft(`analyze ${symbol}${exch !== 'NSE' ? ' ' + exch : ''}`)
              }}
              className="w-full py-2 rounded-xl bg-elevated hover:bg-elevated/80 border border-border text-text font-bold text-xs transition-all cursor-pointer"
            >
              🔍 Open Deep AI Copilot Analysis
            </button>
          </div>
        </div>
      </div>

      {/* ── Trade Log Table ─────────────────────────────────────────────── */}
      <div className="bg-panel border border-border rounded-2xl p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
          <div>
            <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">Execution Ledger</span>
            <h3 className="text-sm font-bold text-text">
              Simulated Trade History ({filteredTrades.length} Trades)
            </h3>
          </div>

          {/* Win / Loss Filter Buttons */}
          <div className="flex items-center gap-1.5 text-xs font-ui">
            <button
              onClick={() => { setTradeFilter('ALL'); setTradePage(1) }}
              className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                tradeFilter === 'ALL' ? 'bg-elevated text-text border border-border' : 'text-muted hover:text-text'
              }`}
            >
              All ({allTrades.length})
            </button>
            <button
              onClick={() => { setTradeFilter('WIN'); setTradePage(1) }}
              className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                tradeFilter === 'WIN' ? 'bg-green/15 text-green border border-green/30' : 'text-muted hover:text-text'
              }`}
            >
              Wins ({allTrades.filter(t => t.pnl > 0).length})
            </button>
            <button
              onClick={() => { setTradeFilter('LOSS'); setTradePage(1) }}
              className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                tradeFilter === 'LOSS' ? 'bg-red/15 text-red border border-red/30' : 'text-muted hover:text-text'
              }`}
            >
              Losses ({allTrades.filter(t => t.pnl <= 0).length})
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="text-[10px] uppercase text-muted border-b border-border/50">
                <th className="py-2 px-3">#</th>
                <th className="py-2 px-3">Date</th>
                <th className="py-2 px-3">Type</th>
                <th className="py-2 px-3">Entry</th>
                <th className="py-2 px-3">Exit</th>
                <th className="py-2 px-3">P&L (₹)</th>
                <th className="py-2 px-3">Return</th>
                <th className="py-2 px-3">R-Multiple</th>
                <th className="py-2 px-3">Exit Trigger</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {paginatedTrades.map((t, idx) => {
                const tradeIsWin = t.pnl > 0
                return (
                  <tr key={idx} className="hover:bg-elevated/40 transition-colors">
                    <td className="py-2.5 px-3 text-muted">{(tradePage - 1) * pageSize + idx + 1}</td>
                    <td className="py-2.5 px-3 text-text font-ui">{t.date}</td>
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-extrabold ${
                        t.type === 'LONG' ? 'bg-green/15 text-green border border-green/30' : 'bg-red/15 text-red border border-red/30'
                      }`}>
                        {t.type}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-text">₹{Number(t.entry).toFixed(2)}</td>
                    <td className="py-2.5 px-3 text-text">₹{Number(t.exit).toFixed(2)}</td>
                    <td className={`py-2.5 px-3 font-bold ${tradeIsWin ? 'text-green' : 'text-red'}`}>
                      {tradeIsWin ? '+' : ''}{formatINR(t.pnl)}
                    </td>
                    <td className={`py-2.5 px-3 font-bold ${tradeIsWin ? 'text-green' : 'text-red'}`}>
                      {tradeIsWin ? '+' : ''}{t.pct.toFixed(2)}%
                    </td>
                    <td className="py-2.5 px-3 font-bold text-amber">
                      {t.r >= 0 ? `+${t.r.toFixed(1)}R` : `${t.r.toFixed(1)}R`}
                    </td>
                    <td className="py-2.5 px-3 text-muted text-[11px] font-ui">{t.reason}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="flex items-center justify-between text-xs font-ui text-muted pt-3 border-t border-border/40">
          <span>
            Showing {(tradePage - 1) * pageSize + 1} to {Math.min(tradePage * pageSize, filteredTrades.length)} of {filteredTrades.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setTradePage((p) => Math.max(1, p - 1))}
              disabled={tradePage === 1}
              className="px-3 py-1 rounded bg-elevated border border-border text-text disabled:opacity-40 cursor-pointer"
            >
              ← Prev
            </button>
            <span className="font-mono text-text">{tradePage} / {totalPages}</span>
            <button
              onClick={() => setTradePage((p) => Math.min(totalPages, p + 1))}
              disabled={tradePage === totalPages}
              className="px-3 py-1 rounded bg-elevated border border-border text-text disabled:opacity-40 cursor-pointer"
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
/* Interactive SVG Equity Curve */
function InteractiveEquityChart({ curve = [], isPositive = true }) {
  if (curve.length === 0) return null

  const width = 760
  const height = 240
  const pad = { top: 20, right: 30, bottom: 30, left: 65 }

  const values = curve.map((c) => c.value)
  const benchValues = curve.map((c) => c.benchmark).filter((value) => value != null)
  const all = [...values, ...benchValues]

  const minVal = Math.min(...all) * 0.98
  const maxVal = Math.max(...all) * 1.02

  const scaleX = (i) => pad.left + (i / (curve.length - 1 || 1)) * (width - pad.left - pad.right)
  const scaleY = (v) => pad.top + ((maxVal - v) / (maxVal - minVal || 1)) * (height - pad.top - pad.bottom)

  const stratPath = curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i)} ${scaleY(p.value)}`).join(' ')
  const hasBenchmark = benchValues.length === curve.length
  const benchPath = hasBenchmark
    ? curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i)} ${scaleY(p.benchmark)}`).join(' ')
    : ''

  const areaPath = `${stratPath} L ${scaleX(curve.length - 1)} ${scaleY(minVal)} L ${scaleX(0)} ${scaleY(minVal)} Z`

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-56 overflow-visible">
      <defs>
        <linearGradient id="equityGrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={isPositive ? 'var(--color-emerald)' : 'var(--color-gold)'} stopOpacity="0.25" />
          <stop offset="100%" stopColor={isPositive ? 'var(--color-emerald)' : 'var(--color-gold)'} stopOpacity="0.0" />
        </linearGradient>
      </defs>

      {/* Grid Lines */}
      {[0.25, 0.5, 0.75].map((pct) => {
        const val = minVal + pct * (maxVal - minVal)
        const y = scaleY(val)
        return (
          <g key={pct}>
            <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} stroke="var(--color-border)" strokeWidth="1" strokeDasharray="3 3" />
            <text x={pad.left - 8} y={y + 3} textAnchor="end" fill="var(--color-muted)" fontSize="9" fontFamily="monospace">
              {formatINR(val, 0)}
            </text>
          </g>
        )
      })}

      {/* Area under curve */}
      <path d={areaPath} fill="url(#equityGrad)" />

      {/* Benchmark Line */}
      {hasBenchmark && <path d={benchPath} fill="none" stroke="var(--color-muted)" strokeWidth="1.5" strokeDasharray="4 4" opacity="0.6" />}

      {/* Strategy Line */}
      <path
        d={stratPath}
        fill="none"
        stroke={isPositive ? 'var(--color-emerald)' : 'var(--color-gold)'}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Peak marker */}
      {curve.length > 0 && (
        <circle
          cx={scaleX(curve.length - 1)}
          cy={scaleY(curve[curve.length - 1].value)}
          r="4"
          fill={isPositive ? 'var(--color-emerald)' : 'var(--color-gold)'}
          stroke="var(--color-panel)"
          strokeWidth="2"
        />
      )}
    </svg>
  )
}
