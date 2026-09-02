import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const money = (value) => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function Metric({ label, value, tone = 'var(--color-text)' }) {
  return <div className="rounded-xl p-3" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}><div className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>{label}</div><div className="text-sm font-mono font-black mt-1" style={{ color: tone }}>{value}</div></div>
}

function TradeRow({ entry, onAnalyze }) {
  const pnl = Number(entry.realized_pnl || 0)
  const isOpen = entry.status === 'OPEN'
  const tone = isOpen ? 'var(--color-gold)' : pnl >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'
  return <div className="grid items-center px-4 py-3 border-b gap-2" style={{ gridTemplateColumns: '1.5fr 0.8fr 0.9fr 1fr 0.8fr', borderColor: 'var(--color-border-subtle)' }}><div><div className="text-xs font-bold">{entry.symbol}</div><div className="text-[9px] mt-0.5" style={{ color: 'var(--color-muted)' }}>{entry.setup_type || '—'} · {entry.direction}</div></div><span className="text-[10px] font-mono" style={{ color: 'var(--color-muted)' }}>{entry.entry_time_ist || '—'}</span><span className="text-xs font-mono">{money(entry.entry_price)}</span><span className="text-xs font-mono font-bold" style={{ color: tone }}>{isOpen ? 'OPEN' : `${pnl >= 0 ? '+' : ''}${money(pnl)}`}</span><button onClick={() => onAnalyze(entry)} className="text-[10px] px-2 py-1 rounded-lg font-bold" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}>Review</button></div>
}

export default function JournalView() {
  const { call } = useAPI()
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [entries, setEntries] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  useEffect(() => { callRef.current = call }, [call])
  const loadJournal = useCallback(async () => { setLoading(true); setError(null); try { const [list, statistics] = await Promise.all([callRef.current('/skills/journal/list'), callRef.current('/skills/journal/stats')]); setEntries(list?.data?.entries ?? []); setStats(statistics?.data ?? null) } catch (err) { setError(err.message || 'Journal is unavailable') } finally { setLoading(false) } }, [])
  useEffect(() => { loadJournal() }, [loadJournal])
  const closedEntries = useMemo(() => entries.filter((entry) => entry.status !== 'OPEN'), [entries])
  const review = (entry) => sendDraft(`post mortem ${entry.symbol} ${entry.direction} entry ${entry.entry_price} exit ${entry.exit_price || 'open'} setup ${entry.setup_type || 'unspecified'}`)
  const pnlTone = Number(stats?.total_realized_pnl || 0) >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'
  return <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
    <header className="flex items-center justify-between flex-wrap gap-2"><div><h1 className="text-lg font-black">📋 Trade Journal</h1><p className="text-xs" style={{ color: 'var(--color-muted)' }}>{stats ? `${stats.total_trades} recorded · ${stats.closed_trades} closed` : 'Authoritative trading records'}</p></div><button onClick={loadJournal} className="btn btn-sm btn-ghost">↻ Refresh</button></header>
    {loading ? <UnavailableState title="Loading journal" reason="Retrieving your recorded trades and analytics." /> : error ? <UnavailableState title="Journal unavailable" reason={error} onRetry={loadJournal} /> : entries.length === 0 ? <UnavailableState title="No journal entries yet" reason="Executed or manually recorded trades will appear here. Performance metrics remain empty until real outcomes exist." size="lg" /> : <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2"><Metric label="Realized P&L" value={`${Number(stats?.total_realized_pnl || 0) >= 0 ? '+' : ''}${money(stats?.total_realized_pnl)}`} tone={pnlTone} /><Metric label="Win rate" value={`${Number(stats?.win_rate_pct || 0).toFixed(1)}%`} tone="var(--color-emerald)" /><Metric label="Expectancy" value={`${Number(stats?.expectancy_r || 0).toFixed(2)}R`} /><Metric label="Profit factor" value={Number(stats?.profit_factor || 0).toFixed(2)} /></div>
      <section className="rounded-2xl overflow-hidden" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}><div className="grid px-4 py-2 text-[9px] font-bold uppercase tracking-wider border-b" style={{ gridTemplateColumns: '1.5fr 0.8fr 0.9fr 1fr 0.8fr', color: 'var(--color-muted)', borderColor: 'var(--color-border)' }}><span>Trade</span><span>Opened</span><span>Entry</span><span>Realized P&L</span><span>Review</span></div>{entries.map((entry) => <TradeRow key={entry.id} entry={entry} onAnalyze={review} />)}</section>
      {closedEntries.length > 0 && <p className="text-[10px] px-1" style={{ color: 'var(--color-muted)' }}>Metrics are calculated only from {closedEntries.length} recorded closed trade{closedEntries.length === 1 ? '' : 's'}; open positions are excluded.</p>}
    </>}
  </div>
}
