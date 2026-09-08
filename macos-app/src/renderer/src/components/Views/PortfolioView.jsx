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
  const { get } = useAPI()
  const getRef = useRef(get)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Search & Sorting State
  const [searchQuery, setSearchQuery] = useState('')
  const [sortColumn, setSortColumn] = useState('pnl')
  const [sortDirection, setSortDirection] = useState('desc')

  useEffect(() => {
    getRef.current = get
  }, [get])

  const loadPortfolio = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPortfolio(await getRef.current('/api/portfolio'))
    } catch (err) {
      setPortfolio(null)
      setError(err.message || 'Portfolio unavailable')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPortfolio()
  }, [loadPortfolio])

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
          <h1 className="text-lg font-black text-text">📈 Portfolio Doctor Pro</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            {portfolio
              ? `${portfolio.brokers?.join(', ') || 'Connected broker'} · account-backed positions`
              : 'Connect a broker to view account-backed data'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => sendDraft('portfolio doctor')} disabled={!portfolio} className="btn btn-sm">
            🔬 Health Check
          </button>
          <button onClick={loadPortfolio} className="btn btn-sm btn-ghost">
            ↻ Refresh
          </button>
        </div>
      </header>

      {loading ? (
        <UnavailableState title="Loading portfolio" reason="Retrieving your connected broker account." />
      ) : error ? (
        <UnavailableState
          title="Portfolio unavailable"
          reason="Connect an authenticated broker to view positions, P&L, and portfolio analysis. No sample holdings are shown."
          onRetry={loadPortfolio}
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
              title="No open holdings or positions"
              reason="Your connected broker returned no currently open account positions."
              size="lg"
            />
          ) : (
            <section
              className="rounded-2xl overflow-hidden"
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
                  gridTemplateColumns: '1.4fr 0.7fr 0.8fr 0.9fr 1fr 0.8fr',
                  color: 'var(--color-muted)',
                  borderColor: 'var(--color-border)',
                }}
              >
                {renderColHeader('symbol', 'Instrument')}
                {renderColHeader('qty', 'Qty')}
                {renderColHeader('avg_price', 'Average')}
                {renderColHeader('ltp', 'LTP')}
                {renderColHeader('pnl', 'P&L')}
                <span className="text-right">Review</span>
              </div>

              {/* Table Rows */}
              {sortedRows.map((row, index) => {
                const pnl = Number(row.pnl || 0)
                const tone = pnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'
                return (
                  <div
                    key={`${row.broker || 'broker'}-${row.symbol}-${index}`}
                    className="grid items-center px-4 py-3 border-b gap-2 hover:bg-amber-500/[0.04] dark:hover:bg-white/[0.03] transition-all"
                    style={{
                      gridTemplateColumns: '1.4fr 0.7fr 0.8fr 0.9fr 1fr 0.8fr',
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
                    <div className="flex justify-end">
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
        </>
      )}
    </div>
  )
}
