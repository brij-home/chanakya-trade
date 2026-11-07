import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const money = (value) => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function MetricCard({ label, value, subtext, tone = 'var(--color-text)', icon }) {
  return (
    <div
      className="rounded-xl p-3 flex flex-col justify-between border shadow-2xs transition-all hover:border-gold/30"
      style={{ background: 'var(--color-panel)', borderColor: 'var(--color-border)' }}
    >
      <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-muted">
        <span>{label}</span>
        {icon && <span className="text-xs">{icon}</span>}
      </div>
      <div className="text-base font-mono font-black mt-1 tabular-nums" style={{ color: tone }}>
        {value}
      </div>
      {subtext && (
        <div className="text-[10px] font-mono text-muted mt-0.5 truncate">
          {subtext}
        </div>
      )}
    </div>
  )
}

/**
 * Cumulative Equity Curve SVG component
 */
function EquityCurveChart({ entries }) {
  const points = useMemo(() => {
    const closed = entries
      .filter((e) => e.status !== 'OPEN' && e.realized_pnl != null)
      .slice()
      .reverse() // Oldest to newest
    if (closed.length === 0) return []

    let cum = 0
    const res = [{ idx: 0, pnl: 0, cum: 0 }]
    closed.forEach((e, idx) => {
      cum += Number(e.realized_pnl || 0)
      res.push({ idx: idx + 1, pnl: Number(e.realized_pnl || 0), cum })
    })
    return res
  }, [entries])

  if (points.length < 2) {
    return (
      <div className="h-32 flex items-center justify-center text-xs text-muted font-mono border rounded-xl bg-panel/50 border-border/60">
        Record 2 or more closed trades to visualize cumulative equity curve.
      </div>
    )
  }

  const cumVals = points.map((p) => p.cum)
  const minVal = Math.min(0, ...cumVals)
  const maxVal = Math.max(0, ...cumVals)
  const range = Math.max(100, maxVal - minVal)

  const width = 600
  const height = 120
  const pad = 15

  const getX = (idx) => pad + (idx / (points.length - 1)) * (width - 2 * pad)
  const getY = (val) => height - pad - ((val - minVal) / range) * (height - 2 * pad)
  const zeroY = getY(0)

  const pathD = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(p.cum).toFixed(1)}`)
    .join(' ')

  const areaD = `${pathD} L ${getX(points.length - 1).toFixed(1)} ${zeroY.toFixed(1)} L ${getX(0).toFixed(1)} ${zeroY.toFixed(1)} Z`
  const lastVal = cumVals[cumVals.length - 1]
  const isNetProfit = lastVal >= 0

  return (
    <div className="rounded-xl border p-3 bg-panel/60 border-border/70 space-y-2">
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="font-bold text-muted uppercase text-[10px] tracking-wider">
          📈 Cumulative Performance Curve (Closed Fills)
        </span>
        <span className={`font-bold font-mono text-xs ${isNetProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
          {isNetProfit ? '+' : ''}{money(lastVal)}
        </span>
      </div>
      <div className="w-full overflow-hidden">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-28 overflow-visible">
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={isNetProfit ? '#10b981' : '#f43f5e'} stopOpacity="0.25" />
              <stop offset="100%" stopColor={isNetProfit ? '#10b981' : '#f43f5e'} stopOpacity="0.0" />
            </linearGradient>
          </defs>
          {/* Zero baseline */}
          <line
            x1={pad}
            y1={zeroY}
            x2={width - pad}
            y2={zeroY}
            stroke="var(--color-border)"
            strokeDasharray="3 3"
            strokeWidth="1"
          />
          {/* Shaded Area */}
          <path d={areaD} fill="url(#equityGrad)" />
          {/* Equity Line */}
          <path
            d={pathD}
            fill="none"
            stroke={isNetProfit ? '#10b981' : '#f43f5e'}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* End marker */}
          <circle
            cx={getX(points.length - 1)}
            cy={getY(lastVal)}
            r="3.5"
            fill={isNetProfit ? '#10b981' : '#f43f5e'}
            stroke="#000"
            strokeWidth="1.5"
          />
        </svg>
      </div>
    </div>
  )
}

function TradeRow({ entry, onAnalyze }) {
  const pnl = Number(entry.realized_pnl || 0)
  const isOpen = entry.status === 'OPEN'
  const isWin = entry.status === 'WIN' || pnl > 0
  const isLoss = entry.status === 'LOSS' || pnl < 0
  const tone = isOpen ? 'var(--color-gold)' : isWin ? 'var(--color-emerald)' : 'var(--color-rose)'

  return (
    <tr className="border-b transition-colors hover:bg-elevated/60 text-xs font-mono" style={{ borderColor: 'var(--color-border-subtle)' }}>
      {/* Symbol & Direction */}
      <td className="py-2.5 px-3">
        <div className="font-bold font-mono text-text flex items-center gap-1.5">
          <span className={`text-[10px] px-1.5 py-0.2 rounded font-bold ${
            entry.direction === 'BUY'
              ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
              : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
          }`}>
            {entry.direction}
          </span>
          <span>{entry.symbol}</span>
        </div>
        <div className="text-[10px] font-ui text-muted truncate mt-0.5" title={entry.thesis || entry.setup_type}>
          {entry.setup_type || 'SYSTEM'} · {entry.thesis || 'Technical setup'}
        </div>
      </td>

      {/* Date & Time */}
      <td className="py-2.5 px-3 text-[11px] text-muted">
        <div>{entry.entry_time_ist || '—'}</div>
        {entry.exit_time_ist && (
          <div className="text-[10px] opacity-75">Closed: {entry.exit_time_ist}</div>
        )}
      </td>

      {/* Execution Levels */}
      <td className="py-2.5 px-3">
        <div>Entry: <span className="font-bold text-text">{money(entry.entry_price)}</span></div>
        <div className="text-[10px] text-muted">
          SL: {money(entry.stop_loss)} · TGT: {money(entry.target)}
        </div>
      </td>

      {/* Exit Price & Qty */}
      <td className="py-2.5 px-3">
        <div className="text-text font-bold">
          {entry.exit_price ? money(entry.exit_price) : <span className="text-amber">OPEN</span>}
        </div>
        <div className="text-[10px] text-muted">Qty: {entry.qty}</div>
      </td>

      {/* Realized R:R */}
      <td className="py-2.5 px-3">
        <span className={`px-1.5 py-0.5 rounded text-[11px] font-bold ${
          isOpen ? 'bg-amber-500/15 text-amber border border-amber-500/30' :
          isWin ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' :
          'bg-rose-500/15 text-rose-400 border border-rose-500/30'
        }`}>
          {isOpen ? 'IN RUN' : `${Number(entry.realized_r || 0) > 0 ? '+' : ''}${Number(entry.realized_r || 0).toFixed(2)} R`}
        </span>
      </td>

      {/* Realized P&L */}
      <td className="py-2.5 px-3 font-bold tabular-nums text-right" style={{ color: tone }}>
        {isOpen ? 'OPEN' : `${pnl >= 0 ? '+' : ''}${money(pnl)}`}
      </td>

      {/* Review CTA */}
      <td className="py-2.5 px-3 text-right">
        <button
          onClick={() => onAnalyze(entry)}
          className="text-[10px] px-2 py-1 rounded-lg font-bold cursor-pointer hover:brightness-110 transition-all border"
          style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)', color: 'var(--color-muted)' }}
          title="Dispatch Post-Mortem Analysis to Copilot / AI Councils"
        >
          🔍 Post-Mortem
        </button>
      </td>
    </tr>
  )
}

export default function JournalView() {
  const { call } = useAPI()
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)

  const [entries, setEntries] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Filters
  const [statusFilter, setStatusFilter] = useState('ALL') // ALL | CLOSED | WIN | LOSS | OPEN
  const [directionFilter, setDirectionFilter] = useState('ALL') // ALL | BUY | SELL
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    callRef.current = call
  }, [call])

  const loadJournal = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, statistics] = await Promise.all([
        callRef.current('/skills/journal/list'),
        callRef.current('/skills/journal/stats'),
      ])
      setEntries(list?.data?.entries ?? [])
      setStats(statistics?.data ?? null)
    } catch (err) {
      setError(err.message || 'Journal is unavailable')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadJournal()
  }, [loadJournal])

  const closedEntries = useMemo(
    () => entries.filter((entry) => entry.status !== 'OPEN'),
    [entries]
  )

  const filteredEntries = useMemo(() => {
    return entries.filter((entry) => {
      if (statusFilter === 'CLOSED' && entry.status === 'OPEN') return false
      if (statusFilter === 'OPEN' && entry.status !== 'OPEN') return false
      if (statusFilter === 'WIN' && entry.status !== 'WIN' && Number(entry.realized_pnl || 0) <= 0) return false
      if (statusFilter === 'LOSS' && entry.status !== 'LOSS' && Number(entry.realized_pnl || 0) >= 0) return false
      if (directionFilter !== 'ALL' && entry.direction !== directionFilter) return false
      if (searchQuery) {
        const q = searchQuery.toUpperCase()
        if (!entry.symbol?.toUpperCase().includes(q) && !entry.setup_type?.toUpperCase().includes(q)) return false
      }
      return true
    })
  }, [entries, statusFilter, directionFilter, searchQuery])

  const review = (entry) => {
    sendDraft(
      `post mortem ${entry.symbol} ${entry.direction} entry ${entry.entry_price} exit ${entry.exit_price || 'open'} setup ${entry.setup_type || 'unspecified'}`
    )
    setActiveView('debate')
  }

  const pnlTone = Number(stats?.total_realized_pnl || 0) >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4 font-ui" style={{ background: 'var(--color-surface)' }}>
      {/* Header */}
      <header className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-border/40">
        <div>
          <h1 className="text-lg font-black tracking-tight flex items-center gap-2">
            <span>📋</span>
            <span>Institutional Trade Journal</span>
          </h1>
          <p className="text-xs text-muted mt-0.5">
            {stats
              ? `${stats.total_trades} trades recorded · ${stats.closed_trades} closed · Verified post-mortem audit`
              : 'Authoritative execution and performance ledger'}
          </p>
        </div>
        <button
          onClick={loadJournal}
          className="btn btn-sm btn-ghost border border-border/60 hover:border-gold/50 text-xs font-mono cursor-pointer flex items-center gap-1.5 px-3 py-1.5 rounded-xl shadow-xs"
        >
          <span>↻</span>
          <span>Refresh Journal</span>
        </button>
      </header>

      {loading ? (
        <UnavailableState title="Loading journal" reason="Retrieving your recorded trades and quantitative analytics." />
      ) : error ? (
        <UnavailableState title="Journal unavailable" reason={error} onRetry={loadJournal} />
      ) : entries.length === 0 ? (
        <UnavailableState
          title="No journal entries yet"
          reason="Executed orders and manual trade blueprints will be recorded here automatically. Performance metrics remain empty until real outcomes exist."
          size="lg"
        />
      ) : (
        <>
          {/* Institutional KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5">
            <MetricCard
              label="Realized P&L"
              value={`${Number(stats?.total_realized_pnl || 0) >= 0 ? '+' : ''}${money(stats?.total_realized_pnl)}`}
              tone={pnlTone}
              icon="💰"
            />
            <MetricCard
              label="Win Rate"
              value={`${Number(stats?.win_rate_pct || 0).toFixed(1)}%`}
              subtext={`${stats?.winning_trades || 0}W · ${stats?.losing_trades || 0}L · ${stats?.breakeven_trades || 0}BE`}
              tone="var(--color-emerald)"
              icon="🎯"
            />
            <MetricCard
              label="Expectancy"
              value={`${Number(stats?.expectancy_r || 0).toFixed(2)} R`}
              subtext="Expected return per 1R risk"
              tone={Number(stats?.expectancy_r || 0) >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'}
              icon="📐"
            />
            <MetricCard
              label="Profit Factor"
              value={Number(stats?.profit_factor || 0).toFixed(2)}
              subtext="Gross Win / Gross Loss"
              icon="⚖️"
            />
            <MetricCard
              label="Avg Win / Loss"
              value={`+${Number(stats?.avg_win_r || 0).toFixed(1)}R / -${Number(stats?.avg_loss_r || 0).toFixed(1)}R`}
              subtext="Realized R-multiples"
              icon="📊"
            />
            <MetricCard
              label="Largest Win"
              value={`+${Number(stats?.largest_win_r || 0).toFixed(1)} R`}
              subtext={`Loss: -${Number(stats?.largest_loss_r || 0).toFixed(1)}R`}
              tone="var(--color-gold)"
              icon="🏆"
            />
          </div>

          {/* Cumulative Equity Curve */}
          <EquityCurveChart entries={entries} />

          {/* Filter Bar */}
          <div className="flex items-center justify-between flex-wrap gap-2 p-2 rounded-xl border bg-panel/70 border-border/60 text-xs">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[10px] text-muted uppercase font-ui font-semibold mr-1">Status:</span>
              {[
                { id: 'ALL', label: 'All' },
                { id: 'CLOSED', label: 'Closed' },
                { id: 'WIN', label: '🟢 Winners' },
                { id: 'LOSS', label: '🔴 Losers' },
                { id: 'OPEN', label: '⚡ Open' },
              ].map((st) => (
                <button
                  key={st.id}
                  onClick={() => setStatusFilter(st.id)}
                  className={`px-2 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    statusFilter === st.id
                      ? 'bg-amber text-black shadow-xs'
                      : 'text-muted hover:text-text bg-elevated/60'
                  }`}
                >
                  {st.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1">
                {['ALL', 'BUY', 'SELL'].map((dir) => (
                  <button
                    key={dir}
                    onClick={() => setDirectionFilter(dir)}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold cursor-pointer transition-all ${
                      directionFilter === dir
                        ? 'bg-elevated text-gold border border-gold/40'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {dir}
                  </button>
                ))}
              </div>
              <input
                type="text"
                placeholder="Filter symbol or setup..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-elevated border border-border/80 rounded-lg px-2.5 py-1 text-text text-xs font-mono outline-none w-44"
              />
            </div>
          </div>

          {/* Rich Tabular Ledger */}
          <div className="rounded-2xl overflow-hidden border" style={{ background: 'var(--color-panel)', borderColor: 'var(--color-border)' }}>
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b text-[10px] uppercase font-bold text-muted bg-surface/50" style={{ borderColor: 'var(--color-border)' }}>
                  <th className="py-2.5 px-3">Trade &amp; Setup</th>
                  <th className="py-2.5 px-3">Timestamp (IST)</th>
                  <th className="py-2.5 px-3">Entry &amp; Plan</th>
                  <th className="py-2.5 px-3">Exit &amp; Qty</th>
                  <th className="py-2.5 px-3">Realized R</th>
                  <th className="py-2.5 px-3 text-right">Realized P&amp;L</th>
                  <th className="py-2.5 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredEntries.length === 0 ? (
                  <tr>
                    <td colSpan="7" className="py-8 text-center text-xs text-muted font-mono">
                      No trades matched the active filter.
                    </td>
                  </tr>
                ) : (
                  filteredEntries.map((entry) => (
                    <TradeRow key={entry.id} entry={entry} onAnalyze={review} />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {closedEntries.length > 0 && (
            <p className="text-[10.5px] px-1 text-muted font-mono">
              Metrics are computed strictly from {closedEntries.length} closed fill{closedEntries.length === 1 ? '' : 's'}; {entries.length - closedEntries.length} active open position{entries.length - closedEntries.length === 1 ? '' : 's'} are excluded from mathematical expectancy.
            </p>
          )}
        </>
      )}
    </div>
  )
}
