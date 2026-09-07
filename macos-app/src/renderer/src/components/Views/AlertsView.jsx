import { useCallback, useEffect, useRef, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

const TYPE_STYLE = {
  PRICE: { icon: '💰', color: 'var(--color-gold)' },
  TECHNICAL: { icon: '📊', color: 'var(--color-violet)' },
  CONDITIONAL: { icon: '⚡', color: 'var(--color-cyan)' },
}

const AUTO_TYPE_STYLE = {
  GAMMA_BLAST: {
    icon: '⚡',
    label: 'GAMMA BLAST',
    color: 'var(--color-gold)',
    bg: 'rgba(245, 166, 35, 0.12)',
    border: 'rgba(245, 166, 35, 0.35)',
  },
  SQUEEZE_BREAKOUT: {
    icon: '🎯',
    label: 'SQUEEZE BREAKOUT',
    color: 'var(--color-emerald)',
    bg: 'rgba(0, 214, 143, 0.12)',
    border: 'rgba(0, 214, 143, 0.35)',
  },
  CIRCUIT_WARNING: {
    icon: '🔒',
    label: 'CIRCUIT WARNING',
    color: 'var(--color-rose)',
    bg: 'rgba(255, 79, 123, 0.12)',
    border: 'rgba(255, 79, 123, 0.35)',
  },
  SMC_SWEEP: {
    icon: '🌊',
    label: 'SMC LIQUIDITY',
    color: 'var(--color-violet)',
    bg: 'rgba(157, 125, 255, 0.12)',
    border: 'rgba(157, 125, 255, 0.35)',
  },
  CONFLUENCE_INFLECTION: {
    icon: '👑',
    label: 'CONFLUENCE INFLECTION',
    color: 'var(--color-sapphire)',
    bg: 'rgba(77, 155, 255, 0.12)',
    border: 'rgba(77, 155, 255, 0.35)',
  },
}

function AutoAlertCard({ alert, onAnalyze, onInspectOptions, onOpenTicket }) {
  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const isEarly = alert.stage === 'EARLY_WARNING'
  const isBull = alert.direction === 'BULLISH'

  return (
    <article
      className="rounded-2xl p-4 space-y-3 animate-slide-up-fade transition-all duration-150 hover:border-gold/40"
      style={{
        background: 'var(--color-panel)',
        border: `1px solid ${style.border}`,
        boxShadow: isEarly ? 'var(--shadow-card)' : '0 0 16px rgba(245, 166, 35, 0.15)',
      }}
    >
      {/* Header Bar */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
            style={{ background: style.bg, border: `1px solid ${style.border}` }}
          >
            {style.icon}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-black tracking-wide">{alert.symbol}</span>
              {alert.contract_symbol && (
                <span className="text-xs font-mono font-bold text-gold px-1.5 py-0.5 rounded bg-gold/10">
                  {alert.contract_symbol}
                </span>
              )}
              <span
                className="text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider"
                style={{ background: style.bg, color: style.color, border: `1px solid ${style.border}` }}
              >
                {style.label}
              </span>
              <span
                className={`text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider ${
                  isEarly
                    ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                    : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 animate-pulse'
                }`}
              >
                {isEarly ? '⏳ EARLY-WARNING (Coiling)' : '🔥 IGNITED (Active)'}
              </span>
              <span
                className={`text-[9px] font-bold px-1.5 py-0.2 rounded ${
                  isBull ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'
                }`}
              >
                {alert.direction}
              </span>
            </div>
            <p className="text-xs font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
              {alert.headline}
            </p>
          </div>
        </div>

        {/* Confidence pill */}
        <div className="text-right flex-shrink-0">
          <div className="text-[10px] text-muted font-mono">Confidence</div>
          <div className="text-xs font-mono font-black text-gold">{alert.confidence || 85}%</div>
        </div>
      </div>

      {/* Summary */}
      <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-dim)' }}>
        {alert.summary}
      </p>

      {/* Quantitative Proof Metrics */}
      {alert.metrics && Object.keys(alert.metrics).length > 0 && (
        <div
          className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-2.5 rounded-xl text-[11px] font-mono"
          style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border-subtle)' }}
        >
          {alert.metrics.vol_oi_ratio !== undefined && (
            <div>
              <span className="text-[9px] text-muted uppercase block">Vol / OI Ratio</span>
              <span className="font-bold text-gold">{alert.metrics.vol_oi_ratio}x</span>
            </div>
          )}
          {alert.metrics.oi_change_pct !== undefined && (
            <div>
              <span className="text-[9px] text-muted uppercase block">Δ OI Unwinding</span>
              <span className={`font-bold ${alert.metrics.oi_change_pct < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                {alert.metrics.oi_change_pct}%
              </span>
            </div>
          )}
          {alert.metrics.dist_to_pivot_pct !== undefined && (
            <div>
              <span className="text-[9px] text-muted uppercase block">Pivot Distance</span>
              <span className="font-bold text-emerald-400">{alert.metrics.dist_to_pivot_pct}%</span>
            </div>
          )}
          {alert.metrics.dist_to_uc_pct !== undefined && (
            <div>
              <span className="text-[9px] text-muted uppercase block">To Circuit Ceiling</span>
              <span className="font-bold text-rose-400">{alert.metrics.dist_to_uc_pct}%</span>
            </div>
          )}
          {alert.metrics.rvol !== undefined && (
            <div>
              <span className="text-[9px] text-muted uppercase block">RVOL 20D</span>
              <span className="font-bold text-cyan-400">{alert.metrics.rvol}x</span>
            </div>
          )}
          {alert.metrics.spot !== undefined && (
            <div>
              <span className="text-[9px] text-muted uppercase block">Spot Price</span>
              <span className="font-bold">₹{alert.metrics.spot}</span>
            </div>
          )}
          {alert.target_level > 0 && (
            <div>
              <span className="text-[9px] text-muted uppercase block">Target</span>
              <span className="font-bold text-emerald-400">₹{alert.target_level}</span>
            </div>
          )}
          {alert.stop_loss > 0 && (
            <div>
              <span className="text-[9px] text-muted uppercase block">Stop Loss</span>
              <span className="font-bold text-rose-400">₹{alert.stop_loss}</span>
            </div>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-2 pt-2 border-t flex-wrap" style={{ borderColor: 'var(--color-border-subtle)' }}>
        <button
          onClick={() => onAnalyze(alert.symbol)}
          className="btn btn-sm btn-ghost text-xs"
        >
          📊 Analyze {alert.symbol}
        </button>

        {alert.option_type && (
          <button
            onClick={() => onInspectOptions(alert.symbol)}
            className="btn btn-sm btn-ghost text-xs text-gold"
          >
            ⚡ Options Desk
          </button>
        )}

        <button
          onClick={() => onOpenTicket(alert)}
          className="btn btn-sm btn-gold text-xs ml-auto"
        >
          🎫 Order Ticket
        </button>
      </div>
    </article>
  )
}

function ManualAlertCard({ alert, onRemove, onAnalyze, removing }) {
  const style = TYPE_STYLE[alert.alert_type] || { icon: '🔔', color: 'var(--color-sapphire)' }
  return (
    <article className="rounded-2xl p-4 space-y-3 animate-slide-up-fade" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0" style={{ background: `${style.color}18`, border: `1px solid ${style.color}33` }}>{style.icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-black">{alert.symbol}</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded font-bold" style={{ background: `${style.color}18`, color: style.color }}>{alert.alert_type}</span>
            <span className="text-[9px] font-mono" style={{ color: 'var(--color-muted)' }}>{alert.exchange}</span>
          </div>
          <p className="text-xs mt-1.5" style={{ color: 'var(--color-text)' }}>{alert.message || `${alert.condition} ${alert.threshold}`}</p>
          <p className="text-[10px] mt-1" style={{ color: 'var(--color-muted)' }}>Created {alert.created_at || '—'} · actively monitored</p>
        </div>
      </div>
      <div className="flex gap-2 pt-2 border-t" style={{ borderColor: 'var(--color-border-subtle)' }}>
        <button onClick={() => onAnalyze(alert.symbol)} className="btn btn-sm btn-ghost">Analyze</button>
        <button onClick={() => onRemove(alert.id)} disabled={removing} className="btn btn-sm ml-auto" style={{ background: 'rgba(255,79,123,0.10)', border: '1px solid rgba(255,79,123,0.30)', color: 'var(--color-rose)' }}>{removing ? 'Removing…' : 'Remove'}</button>
      </div>
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
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>Symbol<input required value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="RELIANCE" className="input-field mt-1 text-xs w-full" /></label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>Condition<select value={condition} onChange={(e) => setCondition(e.target.value)} className="input-field mt-1 text-xs w-full"><option value="ABOVE">Crosses above</option><option value="BELOW">Crosses below</option></select></label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>Price<input required min="0.01" step="any" type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="0.00" className="input-field mt-1 text-xs w-full" /></label>
      </div>
      <button disabled={!canSubmit || creating} className="btn btn-sm btn-gold">{creating ? 'Creating…' : 'Create alert'}</button>
    </form>
  )
}

export default function AlertsView() {
  const { call } = useAPI()
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)

  // Active tab: 'auto' (Live Auto-Alerts) vs 'manual' (User Price Alerts)
  const [activeTab, setActiveTab] = useState('auto')

  // Auto alerts state
  const [autoAlerts, setAutoAlerts] = useState([])
  const [autoLoading, setAutoLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [selectedFilter, setSelectedFilter] = useState('ALL')
  const [selectedStage, setSelectedStage] = useState('ALL')

  // Manual alerts state
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState(null)

  useEffect(() => { callRef.current = call }, [call])

  // Load manual alerts
  const loadAlerts = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await callRef.current('/skills/alerts/list')
      setAlerts(response?.data ?? response ?? [])
    } catch (err) {
      setError(err.message || 'Alerts are unavailable')
    } finally {
      setLoading(false)
    }
  }, [])

  // Load auto alerts
  const loadAutoAlerts = useCallback(async () => {
    setAutoLoading(true)
    try {
      const res = await callRef.current('/skills/alerts/auto/list', {})
      setAutoAlerts(res?.data ?? res ?? [])
    } catch (_) {
      // Fallback empty
    } finally {
      setAutoLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAlerts()
    loadAutoAlerts()
  }, [loadAlerts, loadAutoAlerts])

  // Manual alert creation/deletion
  const createAlert = async (payload) => {
    setCreating(true)
    try {
      await callRef.current('/skills/alerts/add', payload)
      setShowCreate(false)
      await loadAlerts()
    } catch (err) {
      setError(err.message || 'Could not create the alert')
    } finally {
      setCreating(false)
    }
  }

  const removeAlert = async (id) => {
    setRemoving(id)
    try {
      await callRef.current('/skills/alerts/remove', { alert_id: id })
      await loadAlerts()
    } catch (err) {
      setError(err.message || 'Could not remove the alert')
    } finally {
      setRemoving(null)
    }
  }

  // Auto-alert scan trigger
  const handleScanNow = async () => {
    setScanning(true)
    try {
      const res = await callRef.current('/skills/alerts/auto/scan_now', {})
      const fresh = res?.data?.all_recent ?? res?.data ?? []
      setAutoAlerts(fresh)
    } catch (_) {
    } finally {
      setScanning(false)
    }
  }

  const handleClearAuto = async () => {
    try {
      await callRef.current('/skills/alerts/auto/clear', {})
      setAutoAlerts([])
    } catch (_) {}
  }

  const handleInspectOptions = (symbol) => {
    setActiveView('options')
  }

  const handleOpenTicket = (alt) => {
    window.dispatchEvent(
      new CustomEvent('open-order-ticket-modal', {
        detail: {
          symbol: alt.contract_symbol || alt.symbol,
          exchange: alt.exchange || 'NSE',
          price: alt.trigger_level || alt.ltp,
          target: alt.target_level,
          stopLoss: alt.stop_loss,
        },
      })
    )
  }

  // Filter auto-alerts
  const filteredAutoAlerts = autoAlerts.filter((a) => {
    if (selectedFilter !== 'ALL' && a.alert_type !== selectedFilter) return false
    if (selectedStage !== 'ALL' && a.stage !== selectedStage) return false
    return true
  })

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
      {/* Header Bar */}
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-black tracking-wide flex items-center gap-2">
            🔔 Institutional Alert Center
          </h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            Real-time early warnings for Gamma Blasts, Squeeze Breakouts & Circuit Proxies
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-elevated border border-border">
          <button
            onClick={() => setActiveTab('auto')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              activeTab === 'auto' ? 'bg-gold text-panel font-black shadow-sm' : 'text-muted hover:text-text'
            }`}
          >
            ⚡ Live Auto-Alerts ({autoAlerts.length})
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              activeTab === 'manual' ? 'bg-gold text-panel font-black shadow-sm' : 'text-muted hover:text-text'
            }`}
          >
            🔔 Manual Price Alerts ({alerts.length})
          </button>
        </div>
      </header>

      {/* ── TAB 1: Real-Time Auto-Alerts ────────────────────────────── */}
      {activeTab === 'auto' && (
        <div className="space-y-3">
          {/* Action Toolbar */}
          <div className="flex items-center justify-between flex-wrap gap-2 p-2 rounded-xl bg-panel border border-border">
            {/* Category Filter Chips */}
            <div className="flex items-center gap-1 flex-wrap text-[11px]">
              {[
                { id: 'ALL', label: 'All Alerts' },
                { id: 'GAMMA_BLAST', label: '⚡ Gamma Blast' },
                { id: 'SQUEEZE_BREAKOUT', label: '🎯 Squeeze Breakout' },
                { id: 'CIRCUIT_WARNING', label: '🔒 Circuit Warning' },
              ].map((chip) => (
                <button
                  key={chip.id}
                  onClick={() => setSelectedFilter(chip.id)}
                  className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
                    selectedFilter === chip.id
                      ? 'bg-gold/20 text-gold border border-gold/40'
                      : 'text-muted hover:text-text hover:bg-elevated'
                  }`}
                >
                  {chip.label}
                </button>
              ))}
            </div>

            {/* Stage Toggle & Scan Buttons */}
            <div className="flex items-center gap-2 ml-auto">
              <select
                value={selectedStage}
                onChange={(e) => setSelectedStage(e.target.value)}
                className="input-field text-[11px] py-1 px-2"
              >
                <option value="ALL">All Stages</option>
                <option value="EARLY_WARNING">⏳ Early-Warning Only</option>
                <option value="IGNITED">🔥 Ignited Only</option>
              </select>

              <button
                onClick={handleScanNow}
                disabled={scanning}
                className="btn btn-sm btn-gold text-xs flex items-center gap-1"
              >
                {scanning ? '⚡ Scanning Market…' : '⚡ Scan Now'}
              </button>

              {autoAlerts.length > 0 && (
                <button
                  onClick={handleClearAuto}
                  className="btn btn-sm btn-ghost text-xs text-muted hover:text-rose-400"
                  title="Clear alert feed"
                >
                  🗑️
                </button>
              )}
            </div>
          </div>

          {/* Alert Cards Feed */}
          {autoLoading ? (
            <UnavailableState title="Checking market feeds" reason="Scanning for real-time Gamma Blasts and Breakouts." size="md" />
          ) : filteredAutoAlerts.length === 0 ? (
            <div className="p-8 text-center rounded-2xl bg-panel border border-border space-y-2">
              <div className="text-3xl">📡</div>
              <div className="text-sm font-bold text-text">No active auto-alerts in this window</div>
              <p className="text-xs text-muted max-w-md mx-auto">
                The early-warning engine actively monitors options chain OI shedding, TTM squeezes, and circuit bands.
                Click <span className="text-gold font-bold">Scan Now</span> to perform a fresh diagnostic sweep.
              </p>
              <button onClick={handleScanNow} className="btn btn-sm btn-gold mt-2">
                ⚡ Scan Watchlist Now
              </button>
            </div>
          ) : (
            <div className="space-y-2.5 stagger-children">
              {filteredAutoAlerts.map((alt) => (
                <AutoAlertCard
                  key={alt.alert_id}
                  alert={alt}
                  onAnalyze={(sym) => sendDraft(`analyze ${sym}`)}
                  onInspectOptions={handleInspectOptions}
                  onOpenTicket={handleOpenTicket}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── TAB 2: Manual Price Alerts ──────────────────────────────── */}
      {activeTab === 'manual' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted">
              {alerts.length} user-defined price alert{alerts.length === 1 ? '' : 's'} · monitored continuously
            </p>
            <button onClick={() => setShowCreate((v) => !v)} className="btn btn-sm btn-gold">
              + New Alert
            </button>
          </div>

          {showCreate && (
            <CreateAlertPanel onClose={() => setShowCreate(false)} onCreate={createAlert} creating={creating} />
          )}

          {loading ? (
            <UnavailableState title="Loading alerts" reason="Checking your active alerts." size="md" />
          ) : error ? (
            <UnavailableState title="Alerts unavailable" reason={error} onRetry={loadAlerts} size="md" />
          ) : alerts.length === 0 ? (
            <UnavailableState
              title="No active price alerts"
              reason="Create a price alert to monitor a level from your connected market-data feed."
              size="lg"
            />
          ) : (
            <div className="space-y-2 stagger-children">
              {alerts.map((alert) => (
                <ManualAlertCard
                  key={alert.id}
                  alert={alert}
                  onRemove={removeAlert}
                  onAnalyze={(symbol) => sendDraft(`analyze ${symbol}`)}
                  removing={removing === alert.id}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
