import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const money = (value) => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function Metric({ label, value, tone }) {
  return <div className="rounded-xl p-3" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}><div className="text-[9px] uppercase font-bold tracking-wider" style={{ color: 'var(--color-muted)' }}>{label}</div><div className="text-sm mt-1 font-mono font-black" style={{ color: tone || 'var(--color-text)' }}>{value}</div></div>
}

export default function PortfolioView() {
  const { get } = useAPI()
  const getRef = useRef(get)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  useEffect(() => { getRef.current = get }, [get])
  const loadPortfolio = useCallback(async () => { setLoading(true); setError(null); try { setPortfolio(await getRef.current('/api/portfolio')) } catch (err) { setPortfolio(null); setError(err.message || 'Portfolio unavailable') } finally { setLoading(false) } }, [])
  useEffect(() => { loadPortfolio() }, [loadPortfolio])
  const rows = useMemo(() => [...(portfolio?.holdings || []), ...(portfolio?.positions || [])], [portfolio])
  const totalValue = rows.reduce((sum, row) => sum + Number(row.current_value || (Number(row.ltp || 0) * Math.abs(Number(row.qty || 0)))), 0)
  const totalPnl = Number(portfolio?.total_pnl || 0)
  const pnlTone = totalPnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'
  return <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
    <header className="flex items-center justify-between flex-wrap gap-2"><div><h1 className="text-lg font-black">📈 Portfolio Doctor Pro</h1><p className="text-xs" style={{ color: 'var(--color-muted)' }}>{portfolio ? `${portfolio.brokers?.join(', ') || 'Connected broker'} · account-backed positions` : 'Connect a broker to view account-backed data'}</p></div><div className="flex gap-2"><button onClick={() => sendDraft('portfolio doctor')} disabled={!portfolio} className="btn btn-sm">🔬 Health Check</button><button onClick={loadPortfolio} className="btn btn-sm btn-ghost">↻ Refresh</button></div></header>
    {loading ? <UnavailableState title="Loading portfolio" reason="Retrieving your connected broker account." /> : error ? <UnavailableState title="Portfolio unavailable" reason="Connect an authenticated broker to view positions, P&L, and portfolio analysis. No sample holdings are shown." onRetry={loadPortfolio} size="lg" /> : <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2"><Metric label="Account balance" value={money(portfolio?.funds?.total_balance)} /><Metric label="Invested value" value={money(totalValue)} /><Metric label="Open P&L" value={`${totalPnl >= 0 ? '+' : ''}${money(totalPnl)}`} tone={pnlTone} /><Metric label="Available cash" value={money(portfolio?.funds?.available_cash)} tone="var(--color-cyan)" /></div>
      {rows.length === 0 ? <UnavailableState title="No open holdings or positions" reason="Your connected broker returned no currently open account positions." size="lg" /> : <section className="rounded-2xl overflow-hidden" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}><div className="grid px-4 py-2 text-[9px] font-bold uppercase tracking-wider border-b" style={{ gridTemplateColumns: '1.4fr 0.7fr 0.8fr 0.9fr 1fr 0.8fr', color: 'var(--color-muted)', borderColor: 'var(--color-border)' }}><span>Instrument</span><span>Qty</span><span>Average</span><span>LTP</span><span>P&L</span><span>Review</span></div>{rows.map((row, index) => { const pnl = Number(row.pnl || 0); const tone = pnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'; return <div key={`${row.broker || 'broker'}-${row.symbol}-${index}`} className="grid items-center px-4 py-3 border-b gap-2" style={{ gridTemplateColumns: '1.4fr 0.7fr 0.8fr 0.9fr 1fr 0.8fr', borderColor: 'var(--color-border-subtle)' }}><div><div className="text-xs font-bold">{row.symbol}</div><div className="text-[9px]" style={{ color: 'var(--color-muted)' }}>{row.broker || '—'} {row.product ? `· ${row.product}` : ''}</div></div><span className="text-xs font-mono">{row.qty}</span><span className="text-xs font-mono">{money(row.avg_price)}</span><span className="text-xs font-mono font-bold">{money(row.ltp)}</span><span className="text-xs font-mono font-bold" style={{ color: tone }}>{pnl >= 0 ? '+' : ''}{money(pnl)}</span><button onClick={() => sendDraft(`analyze ${row.symbol}`)} className="text-[10px] px-2 py-1 rounded-lg font-bold" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}>Analyze</button></div> })}</section>}
    </>}
  </div>
}
