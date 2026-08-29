import { useState } from 'react'
import CandlestickChart from '../Charts/CandlestickChart'
import { useChatStore } from '../../store/chatStore'

export default function QuoteCard({ data }) {
  const [showChart, setShowChart] = useState(false)
  const sendDraft = useChatStore((s) => s.sendDraft)

  if (!data) return <Card><p className="text-muted text-sm font-ui">No quote data.</p></Card>

  const ltp = data.last_price ?? data.ltp ?? 0
  const change = data.change ?? data.net_change ?? 0
  const changePct = data.change_pct ?? data.pct_change ?? 0
  const symbol = data.symbol ?? data.tradingsymbol ?? '—'
  const exchange = data.exchange ?? 'NSE'
  const positive = change >= 0

  return (
    <Card>
      {/* Top row: Symbol and LTP */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-muted text-[10px] uppercase tracking-widest font-ui mb-0.5">Market Quote</p>
          <div className="flex items-center gap-2">
            <span className="text-text text-xl font-semibold font-mono">{symbol}</span>
            <span className="text-[10px] font-ui bg-panel border border-border px-1.5 py-0.5 rounded text-muted">
              {exchange}
            </span>
          </div>
        </div>
        <div className="text-right">
          <p className="text-text text-2xl font-mono font-semibold">
            ₹{fmt(ltp)}
          </p>
          <p className={`text-xs font-mono mt-0.5 ${positive ? 'text-green' : 'text-red'}`}>
            {positive ? '+' : ''}{Number(change).toFixed(2)}
            {' '}({positive ? '+' : ''}{Number(changePct).toFixed(2)}%)
          </p>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-border/50 text-xs font-mono">
        {[
          ['Open', `₹${fmt(data.open)}`],
          ['High', `₹${fmt(data.high)}`],
          ['Low', `₹${fmt(data.low)}`],
          ['Volume', vol(data.volume)],
        ].map(([label, val]) => (
          <div key={label} className="bg-panel/40 p-1.5 rounded border border-border/30">
            <p className="text-muted text-[9px] uppercase tracking-wider font-ui">{label}</p>
            <p className="text-text font-semibold mt-0.5">{val}</p>
          </div>
        ))}
      </div>

      {/* Interactive Candlestick Chart toggle */}
      <div className="mt-3 pt-3 border-t border-border/50">
        <div className="flex items-center justify-between">
          <button
            onClick={() => setShowChart((s) => !s)}
            className="flex items-center gap-1.5 text-xs text-amber font-ui font-semibold hover:underline"
          >
            <span>{showChart ? '▲ Hide Interactive Chart' : '▼ Expand Interactive Candlestick Chart'}</span>
          </button>
        </div>

        {showChart && (
          <div className="mt-3">
            <CandlestickChart symbol={symbol} exchange={exchange} height={280} />
          </div>
        )}
      </div>

      {/* Quick Action Chips (1-Click Execution) */}
      <div className="mt-3 pt-3 border-t border-border/40 flex flex-wrap gap-1.5 text-[11px] font-ui">
        <button
          onClick={() => sendDraft(`analyze ${symbol}`)}
          className="bg-amber/10 text-amber border border-amber/30 hover:bg-amber/20 px-2.5 py-1 rounded-lg transition-colors cursor-pointer font-semibold shadow-xs"
          title={`Launch full multi-agent AI debate for ${symbol}`}
        >
          ⚡ Multi-Agent Analysis
        </button>
        <button
          onClick={() => sendDraft(`oi ${symbol}`)}
          className="bg-panel hover:bg-elevated text-text border border-border/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
          title={`Analyze options & OI structure for ${symbol}`}
        >
          📊 Options &amp; OI
        </button>
        <button
          onClick={() => sendDraft(`backtest ${symbol} rsi`)}
          className="bg-panel hover:bg-elevated text-text border border-border/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
          title={`Run RSI backtest on ${symbol}`}
        >
          🧪 Backtest
        </button>
      </div>
    </Card>
  )
}

const fmt = (n) =>
  Number(n ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const vol = (n) => {
  const v = Number(n ?? 0)
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)}L`
  return v.toLocaleString('en-IN')
}

function Card({ children }) {
  return <div className="bg-elevated border border-border rounded-xl p-4 max-w-xl w-full">{children}</div>
}
