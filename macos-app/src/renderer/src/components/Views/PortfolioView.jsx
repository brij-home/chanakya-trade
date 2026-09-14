import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const money = (value) => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function Metric({ label, value, tone }) {
  return (
    <div
      className="rounded-xl p-3"
      style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
    >
      <div className="text-[9px] uppercase font-bold tracking-wider" style={{ color: 'var(--color-muted)' }}>
        {label}
      </div>
      <div className="text-sm mt-1 font-mono font-black" style={{ color: tone || 'var(--color-text)' }}>
        {value}
      </div>
    </div>
  )
}

export default function PortfolioView() {
  const { get, call } = useAPI()
  const getRef = useRef(get)
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  
  const [portfolioSource, setPortfolioSource] = useState('auto') // 'auto' | 'broker' | 'paper'
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Search & Sorting State
  const [searchQuery, setSearchQuery] = useState('')
  const [sortColumn, setSortColumn] = useState('pnl')
  const [sortDirection, setSortDirection] = useState('desc')

  // Lifecycle Audit Modal State
  const [selectedLifecycle, setSelectedLifecycle] = useState(null)
  const [lifecycleLoading, setLifecycleLoading] = useState(false)
  const [squareOffStatus, setSquareOffStatus] = useState(null)

  useEffect(() => {
    getRef.current = get
    callRef.current = call
  }, [get, call])

  const loadPortfolio = useCallback(async (sourceOverride) => {
    setLoading(true)
    setError(null)
    const targetSource = sourceOverride || portfolioSource
    try {
      const data = await getRef.current(`/api/portfolio?source=${targetSource}`)
      setPortfolio(data)
    } catch (err) {
      setPortfolio(null)
      setError(err.message || 'Portfolio unavailable')
    } finally {
      setLoading(false)
    }
  }, [portfolioSource])

  useEffect(() => {
    loadPortfolio()
  }, [loadPortfolio])

  const handleSwitchSource = (newSource) => {
    setPortfolioSource(newSource)
    loadPortfolio(newSource)
  }

  const rawRows = useMemo(
    () => [...(portfolio?.holdings || []), ...(portfolio?.positions || [])],
    [portfolio]
  )

  const handleSort = (col) => {
    if (sortColumn === col) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortColumn(col)
      const isNumeric = ['qty', 'avg_price', 'ltp', 'pnl'].includes(col)
      setSortDirection(isNumeric ? 'desc' : 'asc')
    }
  }

  const sortedRows = useMemo(() => {
    let list = [...rawRows]

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      list = list.filter(
        (r) =>
          (r.symbol && String(r.symbol).toLowerCase().includes(q)) ||
          (r.broker && String(r.broker).toLowerCase().includes(q)) ||
          (r.product && String(r.product).toLowerCase().includes(q))
      )
    }

    list.sort((a, b) => {
      let aVal = a[sortColumn]
      let bVal = b[sortColumn]

      if (sortColumn === 'qty') {
        aVal = Math.abs(Number(a.qty || 0))
        bVal = Math.abs(Number(b.qty || 0))
      } else if (sortColumn === 'avg_price') {
        aVal = Number(a.avg_price || 0)
        bVal = Number(b.avg_price || 0)
      } else if (sortColumn === 'ltp') {
        aVal = Number(a.ltp || 0)
        bVal = Number(b.ltp || 0)
      } else if (sortColumn === 'pnl') {
        aVal = Number(a.pnl || 0)
        bVal = Number(b.pnl || 0)
      }

      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }

      const aStr = String(aVal).toLowerCase()
      const bStr = String(bVal).toLowerCase()
      const cmp = aStr.localeCompare(bStr)
      return sortDirection === 'asc' ? cmp : -cmp
    })

    return list
  }, [rawRows, searchQuery, sortColumn, sortDirection])

  const totalValue = rawRows.reduce(
    (sum, row) => sum + Number(row.current_value || Number(row.ltp || 0) * Math.abs(Number(row.qty || 0))),
    0
  )
  const totalPnl = Number(portfolio?.total_pnl || 0)
  const pnlTone = totalPnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'

  // Handle Lifecycle Audit
  const handleAuditLifecycle = async (row) => {
    setLifecycleLoading(true)
    setSelectedLifecycle({ symbol: row.symbol, row, loading: true })
    try {
      const res = await callRef.current('/skills/lifecycle', {
        symbol: row.symbol,
        entry_price: Number(row.avg_price),
        initial_stop_loss: Number(row.avg_price) * 0.95,
        current_ltp: Number(row.ltp),
      })
      const reportData = res?.data ?? res
      setSelectedLifecycle({ symbol: row.symbol, row, data: reportData })
    } catch (err) {
      setSelectedLifecycle({ symbol: row.symbol, row, error: err.message || 'Audit failed' })
    } finally {
      setLifecycleLoading(false)
    }
  }

  // Handle Square Off in Paper Sandbox
  const handleSquareOffPaper = async (symbol) => {
    if (!window.confirm(`Are you sure you want to square off the paper position in ${symbol}?`)) return
    try {
      setSquareOffStatus({ loading: true, symbol })
      await callRef.current('/api/paper/square-off', { symbol })
      await loadPortfolio('paper')
      setSelectedLifecycle(null)
      setSquareOffStatus({ success: true, symbol, msg: `${symbol} squared off.` })
      setTimeout(() => setSquareOffStatus(null), 4000)
    } catch (err) {
      setSquareOffStatus({ error: true, symbol, msg: err.message || 'Square off failed' })
    }
  }

  const renderColHeader = (colKey, label, align = 'left') => {
    const isSorted = sortColumn === colKey
    const dir = sortDirection
    return (
      <span
        onClick={() => handleSort(colKey)}
        className={`cursor-pointer select-none transition-all inline-flex items-center gap-1.5 group py-1 px-1.5 rounded-md ${
          isSorted
            ? 'text-amber-600 dark:text-amber-400 font-bold bg-amber-500/10 dark:bg-amber-400/10'
            : 'text-muted hover:text-text hover:bg-black/[0.04] dark:hover:bg-white/[0.05]'
        } ${align === 'right' ? 'justify-end' : 'justify-start'}`}
        title={`Sort by ${label}`}
      >
        <span>{label}</span>
        <span
          className={`text-[8px] font-mono transition-all ${
            isSorted
              ? 'opacity-100 text-amber-600 dark:text-amber-400 font-bold'
              : 'opacity-30 group-hover:opacity-100 group-hover:text-amber-500'
          }`}
        >
          {isSorted ? (dir === 'asc' ? '▲' : '▼') : '⇅'}
        </span>
      </span>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-black text-text flex items-center gap-2">
            <span>📈 Portfolio Doctor Pro</span>
            {portfolio?.source === 'paper' ? (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30 uppercase font-mono">
                Paper Sandbox
              </span>
            ) : (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 uppercase font-mono">
                Broker Live
              </span>
            )}
          </h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            {portfolio
              ? `${portfolio.brokers?.join(', ') || 'Connected broker'} · account-backed positions`
              : 'Connect a broker to view account-backed data'}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Portfolio Source Switcher */}
          <div className="inline-flex rounded-lg p-0.5 border border-border/50 bg-panel shadow-sm text-xs">
            <button
              onClick={() => handleSwitchSource('broker')}
              className={`px-2.5 py-1 rounded-md font-bold transition-all ${
                portfolioSource !== 'paper'
                  ? 'bg-amber-500/20 text-gold shadow-sm'
                  : 'text-muted hover:text-text'
              }`}
            >
              🏛️ Connected Broker
            </button>
            <button
              onClick={() => handleSwitchSource('paper')}
              className={`px-2.5 py-1 rounded-md font-bold transition-all ${
                portfolioSource === 'paper'
                  ? 'bg-amber-500/20 text-gold shadow-sm'
                  : 'text-muted hover:text-text'
              }`}
            >
              🧪 Paper Sandbox
            </button>
          </div>

          <button onClick={() => sendDraft('portfolio doctor')} disabled={!portfolio} className="btn btn-sm">
            🔬 Health Check
          </button>
          <button onClick={() => loadPortfolio()} className="btn btn-sm btn-ghost">
            ↻ Refresh
          </button>
        </div>
      </header>

      {/* Action status notification */}
      {squareOffStatus && (
        <div
          className={`p-2.5 rounded-xl border text-xs font-mono flex items-center justify-between ${
            squareOffStatus.error
              ? 'bg-rose-500/10 border-rose-500/30 text-rose-400'
              : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
          }`}
        >
          <span>{squareOffStatus.msg || 'Processing position square-off...'}</span>
          <button onClick={() => setSquareOffStatus(null)} className="text-muted hover:text-text">✕</button>
        </div>
      )}

      {loading ? (
        <UnavailableState title="Loading portfolio" reason="Retrieving your account positions." />
      ) : error ? (
        <UnavailableState
          title="Portfolio unavailable"
          reason={error || "Connect an authenticated broker to view positions, P&L, and portfolio analysis. No sample holdings are shown."}
          onRetry={() => loadPortfolio()}
          size="lg"
        />
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            <Metric label="Account balance" value={money(portfolio?.funds?.total_balance)} />
            <Metric label="Invested value" value={money(totalValue)} />
            <Metric label="Open P&L" value={`${totalPnl >= 0 ? '+' : ''}${money(totalPnl)}`} tone={pnlTone} />
            <Metric label="Available cash" value={money(portfolio?.funds?.available_cash)} tone="var(--color-cyan)" />
          </div>

          {rawRows.length === 0 ? (
            <UnavailableState
              title={portfolioSource === 'paper' ? "No open paper positions" : "No open holdings or positions"}
              reason={portfolioSource === 'paper' ? "Your paper simulator sandbox currently has no active open positions." : "Your connected broker returned no currently open account positions."}
              size="lg"
            />
          ) : (
            <section
              className="rounded-2xl overflow-hidden shadow-sm"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
            >
              {/* Filter Toolbar */}
              <div
                className="flex items-center justify-between gap-3 px-4 py-2 border-b"
                style={{ borderColor: 'var(--color-border)', background: 'var(--color-elevated)' }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-text">Positions & Holdings</span>
                  <span className="text-[10px] text-muted font-mono">
                    ({sortedRows.length} of {rawRows.length})
                  </span>
                </div>
                <div className="relative flex items-center">
                  <input
                    type="text"
                    placeholder="Search instruments..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="text-xs px-2.5 py-1 pl-6 pr-5 rounded-lg border outline-none w-32 sm:w-44 focus:w-52 transition-all"
                    style={{
                      background: 'var(--color-panel)',
                      borderColor: searchQuery ? 'var(--color-gold)' : 'var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                  <span className="absolute left-2 text-[10px] text-muted pointer-events-none">🔍</span>
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="absolute right-1.5 text-xs text-muted hover:text-text cursor-pointer"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>

              {/* Table Header */}
              <div
                className="grid px-4 py-2 text-[9px] font-bold uppercase tracking-wider border-b"
                style={{
                  gridTemplateColumns: '1.4fr 0.6fr 0.8fr 0.8fr 0.9fr 1.5fr',
                  color: 'var(--color-muted)',
                  borderColor: 'var(--color-border)',
                }}
              >
                {renderColHeader('symbol', 'Instrument')}
                {renderColHeader('qty', 'Qty')}
                {renderColHeader('avg_price', 'Average')}
                {renderColHeader('ltp', 'LTP')}
                {renderColHeader('pnl', 'P&L')}
                <span className="text-right">Risk & Lifecycle Controls</span>
              </div>

              {/* Table Rows */}
              {sortedRows.map((row, index) => {
                const pnl = Number(row.pnl || 0)
                const tone = pnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'
                const isPaper = row.broker === 'Paper' || portfolio?.source === 'paper'
                return (
                  <div
                    key={`${row.broker || 'broker'}-${row.symbol}-${index}`}
                    className="grid items-center px-4 py-3 border-b gap-2 hover:bg-amber-500/[0.04] dark:hover:bg-white/[0.03] transition-all"
                    style={{
                      gridTemplateColumns: '1.4fr 0.6fr 0.8fr 0.8fr 0.9fr 1.5fr',
                      borderColor: 'var(--color-border-subtle)',
                    }}
                  >
                    <div>
                      <div className="text-xs font-bold text-text group-hover:text-gold transition-colors">{row.symbol}</div>
                      <div className="text-[9px]" style={{ color: 'var(--color-muted)' }}>
                        {row.broker || '—'} {row.product ? `· ${row.product}` : ''}
                      </div>
                    </div>
                    <span className="text-xs font-mono text-text">{row.qty}</span>
                    <span className="text-xs font-mono text-muted">{money(row.avg_price)}</span>
                    <span className="text-xs font-mono font-bold text-text">{money(row.ltp)}</span>
                    <span className="text-xs font-mono font-bold" style={{ color: tone }}>
                      {pnl >= 0 ? '+' : ''}
                      {money(pnl)}
                    </span>
                    <div className="flex items-center justify-end gap-1.5 flex-wrap">
                      <button
                        onClick={() => handleAuditLifecycle(row)}
                        className="text-[10px] px-2 py-1 rounded-lg font-bold text-amber-500 border border-amber-500/30 hover:bg-amber-500/10 transition-all cursor-pointer"
                        title="Audit R-Multiple Payoff, Position Health & Dynamic Trailing Stop-Loss"
                      >
                        ⚡ Health / SL
                      </button>
                      {isPaper && (
                        <button
                          onClick={() => handleSquareOffPaper(row.symbol)}
                          className="text-[10px] px-2 py-1 rounded-lg font-bold text-rose-400 border border-rose-500/30 hover:bg-rose-500/10 transition-all cursor-pointer"
                          title="Square off this paper position immediately"
                        >
                          ✕ Close
                        </button>
                      )}
                      <button
                        onClick={() => sendDraft(`analyze ${row.symbol}`)}
                        className="text-[10px] px-2 py-1 rounded-lg font-bold text-muted hover:text-text hover:border-gold/40 transition-all cursor-pointer"
                        style={{
                          background: 'var(--color-elevated)',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        Analyze
                      </button>
                    </div>
                  </div>
                )
              })}
            </section>
          )}

          {/* Institutional Lifecycle & Trailing SL Audit Modal */}
          {selectedLifecycle && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
              <div
                className="w-full max-w-xl rounded-2xl p-5 border border-border shadow-2xl space-y-4"
                style={{ background: 'var(--color-panel)' }}
              >
                <div className="flex items-center justify-between border-b border-border/50 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-base">⚡</span>
                    <div>
                      <h2 className="text-sm font-black text-text">
                        Position Lifecycle & Dynamic Trailing SL — {selectedLifecycle.symbol}
                      </h2>
                      <p className="text-[10px] text-muted">
                        Cost Basis: ₹{Number(selectedLifecycle.row?.avg_price || 0).toFixed(2)} · LTP: ₹{Number(selectedLifecycle.row?.ltp || 0).toFixed(2)}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedLifecycle(null)}
                    className="text-muted hover:text-text text-sm p-1"
                  >
                    ✕
                  </button>
                </div>

                {lifecycleLoading ? (
                  <div className="p-8 text-center text-muted text-xs font-mono">
                    Auditing position structure, ATR volatility, and trailing stops...
                  </div>
                ) : selectedLifecycle.error ? (
                  <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs font-mono">
                    {selectedLifecycle.error}
                  </div>
                ) : selectedLifecycle.data ? (
                  <div className="space-y-3.5 text-xs font-mono">
                    {/* Score & Health Header */}
                    <div className="grid grid-cols-3 gap-2">
                      <div className="p-2.5 rounded-xl bg-surface border border-border/50">
                        <span className="text-[9px] uppercase text-muted block font-bold">Health Status</span>
                        <span className={`text-xs font-black mt-0.5 block ${
                          selectedLifecycle.data.health_status === 'HEALTHY_ACCELERATING'
                            ? 'text-emerald-400'
                            : selectedLifecycle.data.health_status === 'HEALTHY_PULLBACK'
                            ? 'text-cyan-400'
                            : selectedLifecycle.data.health_status === 'MOMENTUM_STALLING'
                            ? 'text-amber-400'
                            : 'text-rose-400'
                        }`}>
                          {selectedLifecycle.data.health_status}
                        </span>
                      </div>
                      <div className="p-2.5 rounded-xl bg-surface border border-border/50">
                        <span className="text-[9px] uppercase text-muted block font-bold">Payoff Multiple</span>
                        <span className={`text-xs font-black mt-0.5 block ${
                          Number(selectedLifecycle.data.current_r_multiple || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}>
                          {Number(selectedLifecycle.data.current_r_multiple || 0) >= 0 ? '+' : ''}
                          {Number(selectedLifecycle.data.current_r_multiple || 0).toFixed(2)}R
                        </span>
                      </div>
                      <div className="p-2.5 rounded-xl bg-surface border border-border/50">
                        <span className="text-[9px] uppercase text-muted block font-bold">Health Score</span>
                        <span className="text-xs font-black mt-0.5 text-gold block">
                          {selectedLifecycle.data.health_score} / 100
                        </span>
                      </div>
                    </div>

                    {/* Active Trailing Stop Banner */}
                    {selectedLifecycle.data.trailing_stops && (
                      <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-bold uppercase text-amber-400">
                            🛡️ Recommended Trailing Stop ({selectedLifecycle.data.trailing_stops.stop_method})
                          </span>
                          <span className="text-sm font-black text-amber-300">
                            ₹{Number(selectedLifecycle.data.trailing_stops.recommended_active_stop).toFixed(2)}
                          </span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 pt-1 text-[9px] text-muted border-t border-amber-500/20">
                          <div>Structure: ₹{Number(selectedLifecycle.data.trailing_stops.structure_stop).toFixed(2)}</div>
                          <div>Chandelier: ₹{Number(selectedLifecycle.data.trailing_stops.chandelier_stop).toFixed(2)}</div>
                          <div>20-EMA: ₹{Number(selectedLifecycle.data.trailing_stops.ema20_stop).toFixed(2)}</div>
                        </div>
                      </div>
                    )}

                    {/* Milestones */}
                    {selectedLifecycle.data.milestones?.length > 0 && (
                      <div className="space-y-1.5">
                        <span className="text-[10px] uppercase font-bold text-muted">Profit Targets & Scaling</span>
                        <div className="space-y-1">
                          {selectedLifecycle.data.milestones.map((m, idx) => (
                            <div
                              key={idx}
                              className={`flex items-center justify-between p-2 rounded-lg border text-[10px] ${
                                m.reached
                                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                                  : 'bg-surface border-border/40 text-muted'
                              }`}
                            >
                              <div className="flex items-center gap-1.5">
                                <span>{m.reached ? '✅' : '⏳'}</span>
                                <span className="font-bold">{m.name} (₹{Number(m.target_price).toFixed(2)})</span>
                              </div>
                              <span>{m.action_required}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Diagnostic Summary */}
                    {selectedLifecycle.data.summary && (
                      <div className="p-2.5 rounded-xl bg-surface border border-border/40 text-[11px] font-sans text-text">
                        {selectedLifecycle.data.summary}
                      </div>
                    )}
                  </div>
                ) : null}

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/50">
                  <button
                    onClick={() => setSelectedLifecycle(null)}
                    className="btn btn-sm btn-ghost text-xs"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
