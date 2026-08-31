import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

/* ── Mock portfolio positions ────────────────────────────────────────────── */
const MOCK_POSITIONS = [
  { symbol: 'RELIANCE', sector: 'Energy',  qty: 70,  avgPrice: 2784, ltp: 2847, pnl: 4410,  pnlPct: 2.26,  allocation: 22.3, riskPct: 1.8, stage: 2, status: 'HOLD' },
  { symbol: 'HDFCBANK', sector: 'Banking', qty: 130, avgPrice: 1698, ltp: 1720, pnl: 2860,  pnlPct: 1.29,  allocation: 19.8, riskPct: 1.2, stage: 2, status: 'HOLD' },
  { symbol: 'INFY',     sector: 'IT',      qty: 90,  avgPrice: 1695, ltp: 1750, pnl: 4950,  pnlPct: 3.24,  allocation: 17.6, riskPct: 2.1, stage: 2, status: 'ADD'  },
  { symbol: 'TATAMOTORS',sector:'Auto',   qty: 55,  avgPrice: 955,  ltp: 985,  pnl: 1650,  pnlPct: 3.14,  allocation: 12.0, riskPct: 2.4, stage: 2, status: 'HOLD' },
  { symbol: 'ZOMATO',   sector: 'Tech',   qty: 200, avgPrice: 290,  ltp: 275,  pnl: -3000, pnlPct: -5.17, allocation: 6.1,  riskPct: 3.2, stage: 1, status: 'REVIEW'},
  { symbol: 'ADANIENT', sector: 'Infra',  qty: 30,  avgPrice: 2980, ltp: 3045, pnl: 1950,  pnlPct: 2.18,  allocation: 10.2, riskPct: 2.8, stage: 2, status: 'HOLD' },
]

const PERF_STATS = {
  totalValue: 198450,
  totalPnL: 12820,
  totalPnLPct: 6.9,
  dayPnL: 2340,
  dayPnLPct: 1.19,
  maxDrawdown: -8.4,
  winRate: 72.3,
  profitFactor: 2.14,
  sharpe: 1.85,
  openPositions: 6,
  capital: 200000,
}

/* ── Heatmap tile ────────────────────────────────────────────────────────── */
function HeatmapTile({ pos, onClick }) {
  const isPos = pos.pnl >= 0
  const intensity = Math.min(Math.abs(pos.pnlPct) / 6, 1)
  const bg = isPos
    ? `rgba(0, 214, 143, ${0.08 + intensity * 0.35})`
    : `rgba(255, 79, 123, ${0.08 + intensity * 0.35})`
  const border = isPos
    ? `rgba(0, 214, 143, ${0.2 + intensity * 0.4})`
    : `rgba(255, 79, 123, ${0.2 + intensity * 0.4})`

  return (
    <div
      className="rounded-xl p-3 cursor-pointer transition-all hover:scale-105 hover:shadow-lg"
      style={{
        background: bg,
        border: `1px solid ${border}`,
        minHeight: `${60 + pos.allocation * 3}px`,
        flex: `${pos.allocation} 1 0`,
        minWidth: '120px',
      }}
      onClick={() => onClick(pos)}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>{pos.symbol}</span>
        <span
          className="text-[9px] px-1.5 py-0.5 rounded-full font-bold"
          style={{
            background: pos.status === 'ADD' ? 'rgba(0,214,143,0.25)' : pos.status === 'REVIEW' ? 'rgba(255,79,123,0.25)' : 'rgba(77,155,255,0.15)',
            color: pos.status === 'ADD' ? 'var(--color-emerald)' : pos.status === 'REVIEW' ? 'var(--color-rose)' : 'var(--color-sapphire)',
          }}
        >
          {pos.status}
        </span>
      </div>
      <div className="text-sm font-mono font-black" style={{ color: isPos ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
        {isPos ? '+' : ''}₹{pos.pnl.toLocaleString('en-IN')}
      </div>
      <div className="text-[10px] font-mono" style={{ color: isPos ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
        {isPos ? '+' : ''}{pos.pnlPct.toFixed(2)}%
      </div>
      <div className="text-[9px] mt-1" style={{ color: 'var(--color-muted)' }}>
        {pos.allocation.toFixed(1)}% alloc
      </div>
    </div>
  )
}

/* ── Stat card ───────────────────────────────────────────────────────────── */
function StatCard({ label, value, sub, color, icon }) {
  return (
    <div
      className="rounded-xl p-3 space-y-0.5"
      style={{
        background: 'var(--color-panel)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
        {icon} {label}
      </div>
      <div className="text-lg font-mono font-black tabular-nums" style={{ color: color || 'var(--color-text)' }}>
        {value}
      </div>
      {sub && <div className="text-[10px]" style={{ color: 'var(--color-muted)' }}>{sub}</div>}
    </div>
  )
}

/* ── Main View ───────────────────────────────────────────────────────────── */
export default function PortfolioView({ onOpenOrderTicket }) {
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [selectedPos, setSelectedPos] = useState(null)
  const [tab, setTab] = useState('heatmap')

  const totalPnLPos = PERF_STATS.totalPnL >= 0
  const dayPnLPos   = PERF_STATS.dayPnL >= 0

  const tabs = [
    { id: 'heatmap', label: '🗺️ Heatmap' },
    { id: 'positions', label: '📋 Positions' },
    { id: 'analytics', label: '📈 Analytics' },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-black" style={{ color: 'var(--color-text)' }}>📈 Portfolio Doctor Pro</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            {PERF_STATS.openPositions} open positions · ₹{PERF_STATS.totalValue.toLocaleString('en-IN')} total value
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => sendDraft('portfolio doctor')}
            className="btn btn-sm"
            style={{ background: 'rgba(157,125,255,0.15)', border: '1px solid rgba(157,125,255,0.4)', color: 'var(--color-violet)', fontWeight: 700 }}
          >
            🔬 AI Health Check
          </button>
          <button
            onClick={() => onOpenOrderTicket?.()}
            className="btn btn-sm"
            style={{ background: 'rgba(0,214,143,0.15)', border: '1px solid rgba(0,214,143,0.4)', color: 'var(--color-emerald)', fontWeight: 700 }}
          >
            ⚡ New Position
          </button>
        </div>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        <StatCard
          icon="💰" label="Portfolio Value"
          value={`₹${(PERF_STATS.totalValue / 1000).toFixed(1)}K`}
          sub={`of ₹${(PERF_STATS.capital / 1000).toFixed(0)}K capital`}
        />
        <StatCard
          icon="📊" label="Total P&L"
          value={`${totalPnLPos ? '+' : ''}₹${PERF_STATS.totalPnL.toLocaleString('en-IN')}`}
          sub={`${totalPnLPos ? '+' : ''}${PERF_STATS.totalPnLPct}% overall`}
          color={totalPnLPos ? 'var(--color-emerald)' : 'var(--color-rose)'}
        />
        <StatCard
          icon="📅" label="Day P&L"
          value={`${dayPnLPos ? '+' : ''}₹${PERF_STATS.dayPnL.toLocaleString('en-IN')}`}
          sub={`${dayPnLPos ? '+' : ''}${PERF_STATS.dayPnLPct}% today`}
          color={dayPnLPos ? 'var(--color-emerald)' : 'var(--color-rose)'}
        />
        <StatCard
          icon="📉" label="Max Drawdown"
          value={`${PERF_STATS.maxDrawdown}%`}
          sub="Peak to trough"
          color="var(--color-rose)"
        />
        <StatCard
          icon="🎯" label="Win Rate"
          value={`${PERF_STATS.winRate}%`}
          sub="Closed trades"
          color="var(--color-emerald)"
        />
        <StatCard
          icon="⚡" label="Profit Factor"
          value={PERF_STATS.profitFactor}
          sub="Gross profit / loss"
          color={PERF_STATS.profitFactor >= 2 ? 'var(--color-emerald)' : 'var(--color-gold)'}
        />
        <StatCard
          icon="📐" label="Sharpe Ratio"
          value={PERF_STATS.sharpe}
          sub="Risk-adj return"
          color={PERF_STATS.sharpe >= 1.5 ? 'var(--color-emerald)' : 'var(--color-gold)'}
        />
      </div>

      {/* Tab switcher */}
      <div className="tab-bar">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`tab-item ${tab === t.id ? 'active' : ''}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── HEATMAP TAB ── */}
      {tab === 'heatmap' && (
        <div
          className="rounded-2xl p-4 animate-slide-up-fade"
          style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
              Portfolio Heatmap — size = allocation, color = P&L
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {MOCK_POSITIONS.map((pos) => (
              <HeatmapTile key={pos.symbol} pos={pos} onClick={setSelectedPos} />
            ))}
          </div>
          {selectedPos && (
            <div
              className="mt-4 p-4 rounded-xl animate-slide-up-fade"
              style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>
                  📊 {selectedPos.symbol} — Position Detail
                </span>
                <button onClick={() => setSelectedPos(null)} className="text-muted text-xs cursor-pointer hover:text-text">✕ Close</button>
              </div>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
                {[
                  ['Avg Price', `₹${selectedPos.avgPrice}`],
                  ['LTP', `₹${selectedPos.ltp}`],
                  ['Qty', selectedPos.qty],
                  ['P&L', `${selectedPos.pnl >= 0 ? '+' : ''}₹${selectedPos.pnl.toLocaleString('en-IN')}`],
                  ['Return', `${selectedPos.pnlPct >= 0 ? '+' : ''}${selectedPos.pnlPct.toFixed(2)}%`],
                  ['Minervini Stage', `Stage ${selectedPos.stage}`],
                ].map(([label, value]) => (
                  <div key={label} className="text-center">
                    <div className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>{label}</div>
                    <div className="text-sm font-mono font-bold mt-0.5" style={{ color: 'var(--color-text)' }}>{value}</div>
                  </div>
                ))}
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => { onOpenOrderTicket?.({ symbol: selectedPos.symbol, action: 'SELL' }); setSelectedPos(null) }}
                  className="btn btn-sm btn-rose"
                >
                  Exit Position
                </button>
                <button
                  onClick={() => sendDraft(`analyze ${selectedPos.symbol}`)}
                  className="btn btn-sm btn-ghost"
                >
                  Run Analysis
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── POSITIONS TAB ── */}
      {tab === 'positions' && (
        <div
          className="rounded-2xl overflow-hidden animate-slide-up-fade"
          style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
        >
          {/* Table header */}
          <div
            className="grid text-[9px] font-bold uppercase tracking-wider px-4 py-2.5 border-b"
            style={{
              gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr 1fr',
              color: 'var(--color-muted)',
              borderColor: 'var(--color-border)',
              background: 'var(--color-elevated)',
            }}
          >
            <span>Symbol</span><span className="text-right">Qty</span><span className="text-right">Avg</span>
            <span className="text-right">LTP</span><span className="text-right">P&L</span><span className="text-right">Action</span>
          </div>
          {MOCK_POSITIONS.map((pos) => (
            <div
              key={pos.symbol}
              className="grid items-center px-4 py-2.5 border-b transition-colors hover:bg-highlight cursor-pointer"
              style={{
                gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr 1fr',
                borderColor: 'var(--color-border-subtle)',
              }}
            >
              <div>
                <div className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>{pos.symbol}</div>
                <div className="text-[9px]" style={{ color: 'var(--color-muted)' }}>{pos.sector}</div>
              </div>
              <div className="text-right text-xs font-mono" style={{ color: 'var(--color-text)' }}>{pos.qty}</div>
              <div className="text-right text-xs font-mono" style={{ color: 'var(--color-muted)' }}>₹{pos.avgPrice}</div>
              <div className="text-right text-xs font-mono font-bold" style={{ color: 'var(--color-text)' }}>₹{pos.ltp}</div>
              <div className="text-right">
                <div className="text-xs font-mono font-bold tabular-nums" style={{ color: pos.pnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                  {pos.pnl >= 0 ? '+' : ''}₹{pos.pnl.toLocaleString('en-IN')}
                </div>
                <div className="text-[10px] font-mono" style={{ color: pos.pnlPct >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                  {pos.pnlPct >= 0 ? '+' : ''}{pos.pnlPct.toFixed(2)}%
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => onOpenOrderTicket?.({ symbol: pos.symbol })}
                  className="text-[10px] px-2 py-1 rounded-lg font-bold transition-all cursor-pointer"
                  style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}
                >
                  Trade
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── ANALYTICS TAB ── */}
      {tab === 'analytics' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 animate-slide-up-fade">
          {/* Sector allocation donut placeholder */}
          <div
            className="rounded-2xl p-4 space-y-3"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
          >
            <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
              🥧 Sector Allocation
            </div>
            {['Energy', 'Banking', 'IT', 'Auto', 'Infra', 'Tech'].map((s, i) => {
              const pos = MOCK_POSITIONS.filter(p => p.sector === s)
              const pct = pos.reduce((a, p) => a + p.allocation, 0)
              if (!pct) return null
              const colors = ['var(--color-gold)','var(--color-sapphire)','var(--color-violet)','var(--color-emerald)','var(--color-cyan)','var(--color-rose)']
              return (
                <div key={s} className="flex items-center gap-3">
                  <span className="text-[10px] w-16 flex-shrink-0" style={{ color: 'var(--color-muted)' }}>{s}</span>
                  <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-elevated)' }}>
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: colors[i % colors.length] }} />
                  </div>
                  <span className="text-[10px] font-mono font-bold w-10 text-right" style={{ color: 'var(--color-text)' }}>{pct.toFixed(1)}%</span>
                </div>
              )
            })}
          </div>

          {/* Key metrics */}
          <div
            className="rounded-2xl p-4 space-y-3"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
          >
            <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
              ⚕️ Portfolio Health Checks
            </div>
            {[
              { check: 'All positions in Stage 2 Markup', pass: false, detail: 'ZOMATO in Stage 1 — review required' },
              { check: 'Max single position ≤ 25%', pass: true, detail: 'RELIANCE at 22.3% — within limit' },
              { check: 'Sector concentration ≤ 40%', pass: true, detail: 'IT+Banking = 37.4% — within limit' },
              { check: 'Portfolio risk ≤ 5% daily loss cap', pass: true, detail: 'Current risk: 2.8%' },
              { check: 'All stops active and not widened', pass: true, detail: '6/6 positions have active stops' },
              { check: 'No loss streak ≥ 3', pass: true, detail: 'Last 3 closed: +1.2R, +0.8R, +1.5R' },
            ].map(({ check, pass, detail }) => (
              <div key={check} className="flex items-start gap-2.5">
                <span className="text-sm flex-shrink-0 mt-0.5" style={{ color: pass ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                  {pass ? '✓' : '⚠'}
                </span>
                <div>
                  <div className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>{check}</div>
                  <div className="text-[10px]" style={{ color: 'var(--color-muted)' }}>{detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
