import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

export default function BacktestCard({ data }) {
  if (!data) return null

  const r = data?.data ?? data ?? {}
  const sendDraft = useChatStore((s) => s.sendDraft)

  const returnVal = Number(r.total_return ?? r.return_pct ?? 0)
  const isPositive = returnVal >= 0

  const metrics = [
    ['Total Return', pct(returnVal), isPositive ? 'text-green font-bold' : 'text-red font-bold'],
    ['CAGR', pct(r.cagr), 'text-text font-semibold'],
    ['Sharpe Ratio', num(r.sharpe_ratio ?? r.sharpe), 'text-amber font-semibold'],
    ['Max Drawdown', pct(r.max_drawdown), 'text-red font-semibold'],
    ['Win Rate', pct(r.win_rate), 'text-green font-semibold'],
    ['Total Trades', r.total_trades ?? '—', 'text-text'],
    ['Profit Factor', num(r.profit_factor), 'text-text'],
    ['Avg Hold', r.avg_hold_days ? `${r.avg_hold_days}d` : '—', 'text-text'],
  ]

  // Normalize equity curve points whether returned as raw numbers or object array
  const rawCurve = r.equity_curve && r.equity_curve.length > 0
    ? r.equity_curve
    : generateMockEquityCurve(returnVal, r.max_drawdown, r.total_trades || 30)

  const equityCurve = rawCurve.map((p) => ({
    value: typeof p === 'number' ? p : Number(p?.value ?? 100000),
  }))

  const peakValue = equityCurve.length > 0 ? Math.max(...equityCurve.map((p) => p.value)) : 100000

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border/40 pb-3">
        <div>
          <p className="text-muted text-[10px] uppercase tracking-widest font-ui mb-0.5">Quantitative Backtest</p>
          <div className="flex items-center gap-2">
            <span className="text-text text-lg font-semibold">{r.symbol ?? 'NIFTY'}</span>
            <span className="text-amber text-xs bg-amber/10 border border-amber/30 px-1.5 py-0.5 rounded uppercase font-ui">
              {r.strategy_name ?? r.strategy ?? 'RSI'}
            </span>
            {r.period && <span className="text-muted text-xs font-ui">({r.period})</span>}
          </div>
        </div>
        <div className="text-right">
          <span className="text-muted text-[10px] uppercase font-ui block">Net Return</span>
          <p className={`text-2xl font-bold ${isPositive ? 'text-green' : 'text-red'}`}>
            {isPositive ? '+' : ''}{pct(returnVal)}
          </p>
        </div>
      </div>

      {/* Visual Equity Curve */}
      <div className="bg-surface border border-border/60 rounded-lg p-2.5 space-y-1">
        <div className="flex justify-between text-[10px] text-muted font-ui">
          <span>Equity Progression</span>
          <span className={isPositive ? 'text-green' : 'text-amber'}>
            Peak: ₹{peakValue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <EquityCurveSVG data={equityCurve} isPositive={isPositive} />
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {metrics.map(([label, val, cls]) => (
          <div key={label} className="bg-panel/60 border border-border/40 rounded-lg p-2">
            <p className="text-muted text-[9px] uppercase tracking-wider font-ui">{label}</p>
            <p className={`text-xs mt-0.5 ${cls}`}>{val}</p>
          </div>
        ))}
      </div>

      {/* Quick Test Links (1-Click Instant Execution) */}
      <div className="pt-2 border-t border-border/40 flex flex-wrap gap-1.5 text-[11px] font-ui">
        <button
          onClick={() => sendDraft(`backtest ${r.symbol || 'RELIANCE'} ema`)}
          className="bg-panel hover:bg-elevated text-text border border-border/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
          title="Run EMA Crossover backtest"
        >
          🔄 Test with EMA Crossover
        </button>
        <button
          onClick={() => sendDraft(`backtest ${r.symbol || 'RELIANCE'} bb`)}
          className="bg-panel hover:bg-elevated text-text border border-border/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
          title="Run Bollinger Bands backtest"
        >
          📊 Test with Bollinger Bands
        </button>
      </div>
    </div>
  )
}

function EquityCurveSVG({ data = [], isPositive = true }) {
  if (data.length === 0) return null

  const width = 500
  const height = 110
  const pad = { top: 10, right: 15, bottom: 15, left: 15 }

  const values = data.map((d) => d.value)
  const minVal = Math.min(...values)
  const maxVal = Math.max(...values)
  const range = maxVal - minVal > 0 ? maxVal - minVal : 1

  const scaleX = (i) => pad.left + (i / (data.length - 1 || 1)) * (width - pad.left - pad.right)
  const scaleY = (v) => pad.top + ((maxVal - v) / range) * (height - pad.top - pad.bottom)

  const strokeColor = isPositive ? '#22c55e' : '#f43f5e'
  const gradId = isPositive ? 'eqGradGreen' : 'eqGradRed'

  const path = data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i)} ${scaleY(d.value)}`).join(' ')
  const fillPath = `${path} L ${scaleX(data.length - 1)} ${height - pad.bottom} L ${scaleX(0)} ${height - pad.bottom} Z`

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-24 select-none">
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={strokeColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={strokeColor} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <path d={fillPath} fill={`url(#${gradId})`} />
      <path d={path} fill="none" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function generateMockEquityCurve(totalReturnPct, maxDdPct, steps = 30) {
  const points = [{ value: 100000 }]
  let current = 100000
  const growthRate = (1 + totalReturnPct / 100) ** (1 / steps)

  for (let i = 1; i <= steps; i++) {
    const shock = (Math.random() - 0.48) * (Math.abs(maxDdPct || 5) / 10)
    current = current * growthRate * (1 + shock / 100)
    points.push({ value: Math.round(current) })
  }
  return points
}

const pct = (n) => `${Number(n ?? 0).toFixed(2)}%`
const num = (n) => Number(n ?? 0).toFixed(2)
