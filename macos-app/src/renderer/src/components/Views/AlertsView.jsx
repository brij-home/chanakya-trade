import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'

const MOCK_ALERTS = [
  { id: 1, symbol: 'RELIANCE', type: 'PRICE',    condition: '≥ ₹2,890', status: 'ACTIVE',    fired: false, created: '2026-08-30', priority: 'HIGH',   icon: '📊' },
  { id: 2, symbol: 'NIFTY',    type: 'BREAKOUT', condition: '> 24,500 (52W High)', status: 'ACTIVE', fired: false, created: '2026-08-29', priority: 'HIGH', icon: '🚀' },
  { id: 3, symbol: 'BANKNIFTY',type: 'SMC',      condition: 'Order Block Retest @ 52,400', status: 'FIRED', fired: true, firedAt: '14:23 IST', created: '2026-08-28', priority: 'MEDIUM', icon: '⚡' },
  { id: 4, symbol: 'INFY',     type: 'VOLUME',   condition: 'RVOL > 2.5×', status: 'ACTIVE',  fired: false, created: '2026-08-30', priority: 'MEDIUM', icon: '📊' },
  { id: 5, symbol: 'TATAMOTORS',type: 'VIX',    condition: 'VIX < 12.0 (low fear zone)', status: 'PAUSED', fired: false, created: '2026-08-27', priority: 'LOW', icon: '⚡' },
  { id: 6, symbol: 'HDFCBANK', type: 'RSI',      condition: 'RSI < 40 (oversold reset)', status: 'ACTIVE', fired: false, created: '2026-08-31', priority: 'HIGH', icon: '📉' },
  { id: 7, symbol: 'ZOMATO',   type: 'PRICE',    condition: '≤ ₹265 (stop level)', status: 'ACTIVE', fired: false, created: '2026-08-31', priority: 'HIGH', icon: '🛡️' },
  { id: 8, symbol: 'NIFTY',    type: 'BREADTH',  condition: 'A/D Ratio < 0.8 (breadth collapse)', status: 'ACTIVE', fired: false, created: '2026-08-29', priority: 'MEDIUM', icon: '📉' },
]

const ALERT_TYPE_CONFIGS = {
  PRICE:    { color: 'var(--color-gold)',    icon: '💰' },
  BREAKOUT: { color: 'var(--color-emerald)', icon: '🚀' },
  SMC:      { color: 'var(--color-violet)',  icon: '⚡' },
  VOLUME:   { color: 'var(--color-cyan)',    icon: '📊' },
  VIX:      { color: 'var(--color-sapphire)',icon: '⚡' },
  RSI:      { color: 'var(--color-rose)',    icon: '📉' },
  BREADTH:  { color: 'var(--color-sapphire)',icon: '📉' },
}

const PRIORITY_STYLE = {
  HIGH:   { bg: 'rgba(255,79,123,0.12)',   border: 'rgba(255,79,123,0.4)',  color: 'var(--color-rose)',    dot: 'var(--color-rose)' },
  MEDIUM: { bg: 'rgba(245,166,35,0.12)',   border: 'rgba(245,166,35,0.4)',  color: 'var(--color-gold)',   dot: 'var(--color-gold)' },
  LOW:    { bg: 'rgba(77,155,255,0.08)',   border: 'rgba(77,155,255,0.25)', color: 'var(--color-sapphire)',dot: 'var(--color-sapphire)' },
}

/* ── Alert Card ──────────────────────────────────────────────────────────── */
function AlertCard({ alert, onToggle, onDelete, onTrade }) {
  const tc = ALERT_TYPE_CONFIGS[alert.type] || {}
  const pc = PRIORITY_STYLE[alert.priority]

  return (
    <div
      className="group rounded-2xl p-4 transition-all hover:scale-[1.01] animate-slide-up-fade"
      style={{
        background: alert.fired ? 'rgba(245,166,35,0.06)' : 'var(--color-panel)',
        border: alert.fired
          ? '1px solid rgba(245,166,35,0.5)'
          : `1px solid var(--color-border)`,
        boxShadow: alert.fired ? 'var(--glow-gold)' : 'var(--shadow-card)',
      }}
    >
      <div className="flex items-start gap-3">
        {/* Type icon */}
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
          style={{ background: `${tc.color}18`, border: `1px solid ${tc.color}33` }}
        >
          {tc.icon || '🔔'}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-black" style={{ color: 'var(--color-text)' }}>{alert.symbol}</span>
            <span
              className="text-[9px] px-1.5 py-0.5 rounded font-bold"
              style={{ background: `${tc.color}18`, color: tc.color }}
            >
              {alert.type}
            </span>

            {/* Priority dot */}
            <span className="flex items-center gap-1 text-[9px] font-bold" style={{ color: pc.color }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: pc.dot }} />
              {alert.priority}
            </span>

            {/* Fired badge */}
            {alert.fired && (
              <span
                className="text-[9px] px-2 py-0.5 rounded-full font-bold animate-gold-pulse"
                style={{ background: 'rgba(245,166,35,0.25)', color: 'var(--color-gold)', border: '1px solid rgba(245,166,35,0.5)' }}
              >
                🔔 FIRED {alert.firedAt}
              </span>
            )}
          </div>

          <div className="text-xs mt-1 font-medium" style={{ color: 'var(--color-muted)' }}>
            {alert.condition}
          </div>

          <div className="text-[9px] mt-0.5" style={{ color: 'var(--color-subtle)' }}>
            Created {alert.created}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          {alert.fired && (
            <button
              onClick={() => onTrade?.(alert.symbol)}
              className="text-[10px] px-2 py-1 rounded-lg font-bold cursor-pointer transition-all"
              style={{ background: 'rgba(0,214,143,0.15)', border: '1px solid rgba(0,214,143,0.4)', color: 'var(--color-emerald)' }}
            >
              Trade
            </button>
          )}
          <button
            onClick={() => onToggle?.(alert.id)}
            className="text-[10px] px-2 py-1 rounded-lg font-bold cursor-pointer transition-all"
            style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}
          >
            {alert.status === 'PAUSED' ? 'Enable' : 'Pause'}
          </button>
          <button
            onClick={() => onDelete?.(alert.id)}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-xs cursor-pointer transition-all hover:bg-rose-dim"
            style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Status indicator bar */}
      <div className="mt-3 h-0.5 rounded-full overflow-hidden" style={{ background: 'var(--color-border)' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: alert.status === 'ACTIVE' ? '100%' : alert.status === 'FIRED' ? '100%' : '0%',
            background: alert.fired ? 'var(--color-gold)' : alert.status === 'ACTIVE' ? tc.color : 'transparent',
          }}
        />
      </div>
    </div>
  )
}

/* ── Create Alert Panel ──────────────────────────────────────────────────── */
function CreateAlertPanel({ onClose }) {
  const [symbol, setSymbol] = useState('')
  const [type, setType] = useState('PRICE')
  const [condition, setCondition] = useState('')
  const [priority, setPriority] = useState('HIGH')

  return (
    <div
      className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
      style={{ background: 'var(--color-panel)', border: '1px solid var(--color-gold)', boxShadow: 'var(--glow-gold)' }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>🔔 Create New Alert</span>
        <button onClick={onClose} className="text-muted text-xs cursor-pointer hover:text-text">✕</button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>Symbol</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="NIFTY, RELIANCE…"
            className="input-field mt-1 text-xs"
          />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>Alert Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="input-field mt-1 text-xs cursor-pointer"
          >
            {Object.keys(ALERT_TYPE_CONFIGS).map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div className="col-span-2">
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>Condition</label>
          <input
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            placeholder="e.g. Price ≥ ₹2,890 or RVOL > 2.0×"
            className="input-field mt-1 text-xs"
          />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>Priority</label>
          <div className="flex gap-2 mt-1">
            {['HIGH','MEDIUM','LOW'].map((p) => (
              <button
                key={p}
                onClick={() => setPriority(p)}
                className="flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all cursor-pointer"
                style={
                  priority === p
                    ? { background: PRIORITY_STYLE[p].dot, color: '#fff' }
                    : { background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }
                }
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-end">
          <button
            onClick={onClose}
            className="w-full py-2 rounded-xl text-xs font-bold cursor-pointer transition-all"
            style={{ background: 'var(--color-gold)', color: '#000', fontWeight: 800 }}
          >
            Create Alert
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Main View ───────────────────────────────────────────────────────────── */
export default function AlertsView({ onOpenOrderTicket }) {
  const [alerts, setAlerts] = useState(MOCK_ALERTS)
  const [showCreate, setShowCreate] = useState(false)
  const [filterStatus, setFilterStatus] = useState('ALL')

  const firedCount = alerts.filter((a) => a.fired).length
  const activeCount = alerts.filter((a) => a.status === 'ACTIVE' && !a.fired).length

  const displayAlerts = filterStatus === 'ALL'
    ? alerts
    : filterStatus === 'FIRED'
    ? alerts.filter((a) => a.fired)
    : alerts.filter((a) => a.status === filterStatus)

  // Sort: fired first, then HIGH priority, then others
  const sorted = [...displayAlerts].sort((a, b) => {
    if (a.fired !== b.fired) return b.fired - a.fired
    const pOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 }
    return (pOrder[a.priority] ?? 3) - (pOrder[b.priority] ?? 3)
  })

  const handleToggle = (id) => {
    setAlerts((prev) => prev.map((a) =>
      a.id === id ? { ...a, status: a.status === 'PAUSED' ? 'ACTIVE' : 'PAUSED' } : a
    ))
  }

  const handleDelete = (id) => setAlerts((prev) => prev.filter((a) => a.id !== id))

  const handleTrade = (symbol) => onOpenOrderTicket?.({ symbol })

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-black" style={{ color: 'var(--color-text)' }}>🔔 Alerts Manager</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            {activeCount} active · <span style={{ color: 'var(--color-gold)', fontWeight: 700 }}>{firedCount} fired</span> · {alerts.length} total
          </p>
        </div>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="btn btn-sm btn-gold"
        >
          + New Alert
        </button>
      </div>

      {/* Create alert panel */}
      {showCreate && <CreateAlertPanel onClose={() => setShowCreate(false)} />}

      {/* Status filters */}
      <div className="flex gap-2 flex-wrap">
        {['ALL', 'ACTIVE', 'FIRED', 'PAUSED'].map((s) => (
          <button
            key={s}
            onClick={() => setFilterStatus(s)}
            className="text-xs px-3 py-1.5 rounded-xl font-bold transition-all cursor-pointer"
            style={
              filterStatus === s
                ? { background: 'var(--color-gold)', color: '#000' }
                : { background: 'var(--color-panel)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }
            }
          >
            {s}
            {s === 'FIRED' && firedCount > 0 && (
              <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded-full" style={{ background: 'var(--color-rose)', color: '#fff' }}>
                {firedCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Alert cards */}
      <div className="space-y-2 stagger-children">
        {sorted.map((alert) => (
          <AlertCard
            key={alert.id}
            alert={alert}
            onToggle={handleToggle}
            onDelete={handleDelete}
            onTrade={handleTrade}
          />
        ))}
        {sorted.length === 0 && (
          <div className="text-center py-16" style={{ color: 'var(--color-subtle)' }}>
            <div className="text-4xl mb-3">🔔</div>
            <div className="text-sm font-semibold">No alerts in this filter</div>
            <div className="text-xs mt-1">Create an alert using the button above</div>
          </div>
        )}
      </div>
    </div>
  )
}
