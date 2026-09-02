import { useCallback, useEffect, useRef, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const TYPE_STYLE = {
  PRICE: { icon: '💰', color: 'var(--color-gold)' },
  TECHNICAL: { icon: '📊', color: 'var(--color-violet)' },
  CONDITIONAL: { icon: '⚡', color: 'var(--color-cyan)' },
}

function AlertCard({ alert, onRemove, onAnalyze, removing }) {
  const style = TYPE_STYLE[alert.alert_type] || { icon: '🔔', color: 'var(--color-sapphire)' }
  return (
    <article className="rounded-2xl p-4 space-y-3 animate-slide-up-fade" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0" style={{ background: `${style.color}18`, border: `1px solid ${style.color}33` }}>{style.icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap"><span className="text-xs font-black">{alert.symbol}</span><span className="text-[9px] px-1.5 py-0.5 rounded font-bold" style={{ background: `${style.color}18`, color: style.color }}>{alert.alert_type}</span><span className="text-[9px] font-mono" style={{ color: 'var(--color-muted)' }}>{alert.exchange}</span></div>
          <p className="text-xs mt-1.5" style={{ color: 'var(--color-text)' }}>{alert.message || `${alert.condition} ${alert.threshold}`}</p>
          <p className="text-[10px] mt-1" style={{ color: 'var(--color-muted)' }}>Created {alert.created_at || '—'} · actively monitored</p>
        </div>
      </div>
      <div className="flex gap-2 pt-2 border-t" style={{ borderColor: 'var(--color-border-subtle)' }}><button onClick={() => onAnalyze(alert.symbol)} className="btn btn-sm btn-ghost">Analyze</button><button onClick={() => onRemove(alert.id)} disabled={removing} className="btn btn-sm ml-auto" style={{ background: 'rgba(255,79,123,0.10)', border: '1px solid rgba(255,79,123,0.30)', color: 'var(--color-rose)' }}>{removing ? 'Removing…' : 'Remove'}</button></div>
    </article>
  )
}

function CreateAlertPanel({ onClose, onCreate, creating }) {
  const [symbol, setSymbol] = useState('')
  const [condition, setCondition] = useState('ABOVE')
  const [threshold, setThreshold] = useState('')
  const canSubmit = symbol.trim() && Number(threshold) > 0
  return (
    <form onSubmit={(event) => { event.preventDefault(); if (canSubmit) onCreate({ symbol: symbol.trim(), condition, threshold: Number(threshold) }) }} className="rounded-2xl p-4 space-y-3 animate-slide-up-fade" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-gold)', boxShadow: 'var(--glow-gold)' }}>
      <div className="flex items-center justify-between"><span className="text-sm font-bold">🔔 New price alert</span><button type="button" onClick={onClose} className="text-muted text-xs">✕</button></div>
      <p className="text-[10px]" style={{ color: 'var(--color-muted)' }}>Alerts use the connected market-data feed. A trigger opens analysis; it never places an order.</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3"><label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>Symbol<input required value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="RELIANCE" className="input-field mt-1 text-xs w-full" /></label><label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>Condition<select value={condition} onChange={(e) => setCondition(e.target.value)} className="input-field mt-1 text-xs w-full"><option value="ABOVE">Crosses above</option><option value="BELOW">Crosses below</option></select></label><label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>Price<input required min="0.01" step="any" type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="0.00" className="input-field mt-1 text-xs w-full" /></label></div>
      <button disabled={!canSubmit || creating} className="btn btn-sm btn-gold">{creating ? 'Creating…' : 'Create alert'}</button>
    </form>
  )
}

export default function AlertsView() {
  const { call } = useAPI()
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState(null)
  useEffect(() => { callRef.current = call }, [call])
  const loadAlerts = useCallback(async () => { setLoading(true); setError(null); try { const response = await callRef.current('/skills/alerts/list'); setAlerts(response?.data ?? response ?? []) } catch (err) { setError(err.message || 'Alerts are unavailable') } finally { setLoading(false) } }, [])
  useEffect(() => { loadAlerts() }, [loadAlerts])
  const createAlert = async (payload) => { setCreating(true); try { await callRef.current('/skills/alerts/add', payload); setShowCreate(false); await loadAlerts() } catch (err) { setError(err.message || 'Could not create the alert') } finally { setCreating(false) } }
  const removeAlert = async (id) => { setRemoving(id); try { await callRef.current('/skills/alerts/remove', { alert_id: id }); await loadAlerts() } catch (err) { setError(err.message || 'Could not remove the alert') } finally { setRemoving(null) } }
  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
      <header className="flex items-center justify-between flex-wrap gap-2"><div><h1 className="text-lg font-black">🔔 Alerts Manager</h1><p className="text-xs" style={{ color: 'var(--color-muted)' }}>{alerts.length} active alert{alerts.length === 1 ? '' : 's'} · data-backed monitoring</p></div><button onClick={() => setShowCreate((value) => !value)} className="btn btn-sm btn-gold">+ New Alert</button></header>
      {showCreate && <CreateAlertPanel onClose={() => setShowCreate(false)} onCreate={createAlert} creating={creating} />}
      {loading ? <UnavailableState title="Loading alerts" reason="Checking your active alerts." size="md" /> : error ? <UnavailableState title="Alerts unavailable" reason={error} onRetry={loadAlerts} size="md" /> : alerts.length === 0 ? <UnavailableState title="No active alerts" reason="Create a price alert to monitor a level from your connected market-data feed." size="lg" /> : <div className="space-y-2 stagger-children">{alerts.map((alert) => <AlertCard key={alert.id} alert={alert} onRemove={removeAlert} onAnalyze={(symbol) => sendDraft(`analyze ${symbol}`)} removing={removing === alert.id} />)}</div>}
    </div>
  )
}
