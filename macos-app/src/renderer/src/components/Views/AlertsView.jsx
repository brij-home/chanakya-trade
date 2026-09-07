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
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED'
  const isBull = alert.direction === 'BULLISH'
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isT1 = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isFinalTarget = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED'
  const isTarget = isT1 || isFinalTarget
  const isTrail = alert.stage === 'TRAILING_UPDATE'

  return (
    <article
      className="rounded-2xl p-4 space-y-3 animate-slide-up-fade transition-all duration-150 hover:border-gold/40"
      style={{
        background: isInvalidated ? 'rgba(255, 79, 123, 0.05)' : 'var(--color-panel)',
        border: isInvalidated ? '1px solid rgba(255, 79, 123, 0.5)' : `1px solid ${style.border}`,
        boxShadow: isInvalidated
          ? '0 0 16px rgba(255, 79, 123, 0.12)'
          : isEarly
          ? 'var(--shadow-card)'
          : '0 0 16px rgba(245, 166, 35, 0.15)',
      }}
    >
      {/* Header Bar */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
            style={{
              background: isInvalidated ? 'rgba(255, 79, 123, 0.15)' : style.bg,
              border: `1px solid ${isInvalidated ? 'rgba(255, 79, 123, 0.4)' : style.border}`,
            }}
          >
            {isInvalidated ? '🛑' : isFinalTarget ? '🏁' : isT1 ? '🎯' : isTrail ? '📈' : style.icon}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-black tracking-wide">{alert.symbol}</span>
              {alert.contract_symbol && (
                <span className="text-xs font-mono font-bold text-gold px-1.5 py-0.5 rounded bg-gold/10">
                  {alert.contract_symbol}
                </span>
              )}

              {/* REAL/LIVE vs TEST Badge */}
              <span
                className={`text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider ${
                  isTest
                    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                    : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                }`}
              >
                {isTest ? '🧪 TEST ALERT' : '🟢 REAL / LIVE'}
              </span>

              <span
                className="text-[9px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider"
                style={{ background: style.bg, color: style.color, border: `1px solid ${style.border}` }}
              >
                {style.label}
              </span>

              {/* Status / Stage Badge */}
              {isInvalidated ? (
                <span className="text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse">
                  ❌ INVALIDATED (No Longer Valid)
                </span>
              ) : isFinalTarget ? (
                <span className="text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse">
                  🏁 FINAL TARGET REACHED
                </span>
              ) : isT1 ? (
                <span className="text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 animate-pulse">
                  🎯 T1 REACHED (Breakeven Locked)
                </span>
              ) : isTrail ? (
                <span className="text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider bg-blue-500/20 text-blue-300 border border-blue-500/40">
                  📈 TRAILING UPDATED
                </span>
              ) : (
                <span
                  className={`text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider ${
                    isEarly
                      ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                      : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 animate-pulse'
                  }`}
                >
                  {isEarly ? '⏳ EARLY-WARNING (Coiling)' : '🔥 IGNITED (Active)'}
                </span>
              )}

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

        {/* Timestamp & Confidence */}
        <div className="text-right flex-shrink-0 space-y-1">
          {alert.timestamp || alert.created_at ? (
            <div
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface/90 border border-border/60 text-[10px] font-mono text-muted shadow-sm"
              title={`Alert Timestamp: ${alert.created_at || alert.timestamp}`}
            >
              <span className="text-cyan-400">🕒</span>
              <span className="font-semibold text-text">
                {(alert.timestamp || alert.created_at).includes(' ')
                  ? (alert.timestamp || alert.created_at).split(' ').slice(-2).join(' ')
                  : (alert.timestamp || alert.created_at)}
              </span>
            </div>
          ) : null}
          <div className="text-[10px] font-mono text-muted">
            Confidence: <span className="font-black text-gold">{alert.confidence || 85}%</span>
          </div>
        </div>
      </div>

      {/* Invalidation Callout if invalidated */}
      {isInvalidated && (
        <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300 flex items-start gap-2">
          <span className="text-base flex-shrink-0">⚠️</span>
          <div>
            <span className="font-bold block">Trade Setup / View Invalidated:</span>
            <span className="leading-relaxed">{alert.invalidation_reason || alert.summary}</span>
            {alert.invalidated_at && (
              <span className="text-[10px] text-muted block mt-1 font-mono">
                Invalidated at: {alert.invalidated_at}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Target & Trailing Stop Decisive Guidance Callout */}
      {(alert.trailing_decision || alert.trailing_stop || isTarget || isTrail) && !isInvalidated && (
        <div
          className="p-3 rounded-xl border text-xs space-y-2 animate-slide-up-fade"
          style={{
            background: isFinalTarget
              ? (alert.should_trail ? 'rgba(56, 189, 248, 0.08)' : 'rgba(16, 185, 129, 0.08)')
              : isT1
              ? 'rgba(16, 185, 129, 0.08)'
              : 'rgba(56, 189, 248, 0.08)',
            borderColor: isFinalTarget
              ? (alert.should_trail ? 'rgba(56, 189, 248, 0.35)' : 'rgba(16, 185, 129, 0.35)')
              : isT1
              ? 'rgba(16, 185, 129, 0.35)'
              : 'rgba(56, 189, 248, 0.35)',
          }}
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 font-bold">
              <span className="text-base">{isFinalTarget ? (alert.should_trail ? '🚀' : '🏁') : isT1 ? '🎯' : '📈'}</span>
              <span style={{ color: 'var(--color-text)' }}>
                {isFinalTarget ? 'Final Target Milestone' : isT1 ? 'Target 1 Milestone (Partial Lock)' : 'Dynamic Trailing Active'}
              </span>
            </div>
            <span
              className={`text-[10px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider ${
                alert.trailing_decision === 'BOOK_50_TRAIL_BREAKEVEN'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : alert.trailing_decision === 'TRAIL_DYNAMIC_ATR'
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                  : alert.trailing_decision === 'BOOK_FULL_PROFIT_NO_TRAIL'
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                  : 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40'
              }`}
            >
              ⚡ {alert.trailing_decision || (alert.should_trail ? 'TRAIL STOP' : 'HOLD STOP')}
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-[11px] pt-1 border-t border-border/20">
            {alert.trailing_stop && (
              <div>
                <span className="text-[9px] text-muted uppercase block">Recommended Stop Loss</span>
                <span className="font-bold text-gold">₹{alert.trailing_stop.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
              </div>
            )}
            {alert.locked_profit_pct !== undefined && alert.locked_profit_pct !== null && (
              <div>
                <span className="text-[9px] text-muted uppercase block">Locked Profit</span>
                <span className="font-bold text-emerald-400">
                  {alert.locked_profit_pts ? `+₹${alert.locked_profit_pts} ` : ''}(+{alert.locked_profit_pct}%)
                </span>
              </div>
            )}
            <div>
              <span className="text-[9px] text-muted uppercase block">Trailing Action</span>
              <span className={`font-bold ${alert.should_trail ? 'text-cyan-400' : 'text-amber-400'}`}>
                {alert.should_trail ? '✅ TRAIL SL RECOMMENDED' : '🛑 DO NOT TRAIL (FULL EXIT)'}
              </span>
            </div>
          </div>

          {alert.trailing_rationale && (
            <p className="text-[11px] leading-relaxed pt-1" style={{ color: 'var(--color-text-dim)' }}>
              {alert.trailing_rationale}
            </p>
          )}
        </div>
      )}

      {/* Summary */}
      {!isInvalidated && !alert.trailing_rationale && (
        <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text-dim)' }}>
          {alert.summary}
        </p>
      )}

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

        {alert.option_type && !isInvalidated && (
          <button
            onClick={() => onInspectOptions(alert.symbol)}
            className="btn btn-sm btn-ghost text-xs text-gold"
          >
            ⚡ Options Desk
          </button>
        )}

        {!isInvalidated ? (
          <button
            onClick={() => onOpenTicket(alert)}
            className="btn btn-sm btn-gold text-xs ml-auto"
          >
            🎫 Order Ticket
          </button>
        ) : (
          <span className="text-[10px] text-rose-400 font-bold ml-auto">
            🛑 Orders Disabled (Invalidated)
          </span>
        )}
      </div>

      {/* Footer Timestamp Strip */}
      <div className="flex items-center justify-between text-[10px] font-mono text-muted/80 pt-2 border-t border-border/20 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span>🕒 Triggered: {alert.timestamp || alert.created_at || 'Live'}</span>
          {alert.invalidated_at && (
            <span className="text-rose-400 font-semibold">⚠️ Invalidated: {alert.invalidated_at}</span>
          )}
        </div>
        <span className="text-[9px] uppercase tracking-wider text-muted/60">
          ID: {alert.alert_id?.slice(-8) || alert.symbol}
        </span>
      </div>
    </article>
  )
}

function ManualAlertCard({ alert, onRemove, onAnalyze, removing }) {
  const style = TYPE_STYLE[alert.alert_type] || { icon: '🔔', color: 'var(--color-sapphire)' }
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isInvalidated = alert.is_invalidated
  const alertTime = alert.timestamp || alert.triggered_at || alert.invalidated_at || alert.created_at || ''
  const timeShort = alertTime.includes(' ') ? alertTime.split(' ').slice(-2).join(' ') : alertTime

  return (
    <article
      className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
      style={{
        background: isInvalidated ? 'rgba(255,79,123,0.06)' : 'var(--color-panel)',
        border: isInvalidated ? '1px solid rgba(255,79,123,0.4)' : '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
          style={{ background: `${style.color}18`, border: `1px solid ${style.color}33` }}
        >
          {isInvalidated ? '🛑' : style.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-black">{alert.symbol}</span>
              <span
                className={`text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider ${
                  isTest
                    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                    : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                }`}
              >
                {isTest ? '🧪 TEST' : '🟢 REAL / LIVE'}
              </span>
              <span
                className="text-[9px] px-1.5 py-0.5 rounded font-bold"
                style={{ background: `${style.color}18`, color: style.color }}
              >
                {alert.alert_type}
              </span>
              {isInvalidated && (
                <span className="text-[9px] px-1.5 py-0.5 rounded font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40">
                  ❌ INVALIDATED
                </span>
              )}
              <span className="text-[9px] font-mono" style={{ color: 'var(--color-muted)' }}>
                {alert.exchange}
              </span>
            </div>
            {timeShort && (
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface/90 border border-border/60 text-[10px] font-mono text-muted shadow-sm"
                title={alertTime}
              >
                <span className="text-cyan-400">🕒</span>
                <span className="font-semibold text-text">{timeShort}</span>
              </span>
            )}
          </div>
          <p className="text-xs mt-1.5" style={{ color: 'var(--color-text)' }}>
            {alert.message || `${alert.condition} ${alert.threshold}`}
          </p>
          {isInvalidated && alert.invalidation_reason && (
            <p className="text-xs mt-1 text-rose-400 font-medium">
              Reason: {alert.invalidation_reason}
            </p>
          )}
          <div className="flex items-center gap-3 text-[10px] mt-1.5 font-mono text-muted flex-wrap">
            <span>🕒 Created: {alert.created_at || '—'}</span>
            {alert.triggered_at && <span className="text-emerald-400 font-semibold">✓ Triggered: {alert.triggered_at}</span>}
            {alert.invalidated_at && <span className="text-rose-400 font-semibold">⚠️ Invalidated: {alert.invalidated_at}</span>}
          </div>
        </div>
      </div>
      <div className="flex gap-2 pt-2 border-t" style={{ borderColor: 'var(--color-border-subtle)' }}>
        <button onClick={() => onAnalyze(alert.symbol)} className="btn btn-sm btn-ghost">
          Analyze
        </button>
        <button
          onClick={() => onRemove(alert.id)}
          disabled={removing}
          className="btn btn-sm ml-auto"
          style={{
            background: 'rgba(255,79,123,0.10)',
            border: '1px solid rgba(255,79,123,0.30)',
            color: 'var(--color-rose)',
          }}
        >
          {removing ? 'Removing…' : 'Remove'}
        </button>
      </div>
    </article>
  )
}

function CreateAlertPanel({ onClose, onCreate, creating }) {
  const [symbol, setSymbol] = useState('')
  const [condition, setCondition] = useState('ABOVE')
  const [threshold, setThreshold] = useState('')
  const [invalidationThreshold, setInvalidationThreshold] = useState('')
  const canSubmit = symbol.trim() && Number(threshold) > 0

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) {
          onCreate({
            symbol: symbol.trim(),
            condition,
            threshold: Number(threshold),
            invalidation_threshold: invalidationThreshold ? Number(invalidationThreshold) : undefined,
          })
        }
      }}
      className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
      style={{
        background: 'var(--color-panel)',
        border: '1px solid var(--color-gold)',
        boxShadow: 'var(--glow-gold)',
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-bold">🔔 New price alert</span>
        <button type="button" onClick={onClose} className="text-muted text-xs">
          ✕
        </button>
      </div>
      <p className="text-[10px]" style={{ color: 'var(--color-muted)' }}>
        Alerts use the connected market-data feed. Alerts clearly indicate REAL/LIVE vs TEST and alert upon invalidation.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Symbol
          <input
            required
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="RELIANCE"
            className="input-field mt-1 text-xs w-full"
          />
        </label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Condition
          <select
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            className="input-field mt-1 text-xs w-full"
          >
            <option value="ABOVE">Crosses above</option>
            <option value="BELOW">Crosses below</option>
          </select>
        </label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Price
          <input
            required
            min="0.01"
            step="any"
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            placeholder="0.00"
            className="input-field mt-1 text-xs w-full"
          />
        </label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Invalidation SL (Opt)
          <input
            min="0.01"
            step="any"
            type="number"
            value={invalidationThreshold}
            onChange={(e) => setInvalidationThreshold(e.target.value)}
            placeholder="0.00"
            className="input-field mt-1 text-xs w-full"
          />
        </label>
      </div>
      <button disabled={!canSubmit || creating} className="btn btn-sm btn-gold">
        {creating ? 'Creating…' : 'Create alert'}
      </button>
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
  const [testing, setTesting] = useState(false)
  const [selectedFilter, setSelectedFilter] = useState('ALL')
  const [selectedStage, setSelectedStage] = useState('ALL')
  const [selectedEnv, setSelectedEnv] = useState('ALL') // ALL | LIVE | TEST

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

    // 1. Instant real-time update when SSE alert arrives
    const handleLiveAlert = (event) => {
      const newAlert = event.detail
      if (!newAlert) return

      if (newAlert.alert_type === 'PRICE' || newAlert.alert_type === 'TECHNICAL' || newAlert.alert_type === 'CONDITIONAL') {
        setAlerts((prev) => {
          const id = newAlert.alert_id || newAlert.id
          const exists = prev.some((a) => (a.id || a.alert_id) === id)
          if (exists) {
            return prev.map((a) => ((a.id || a.alert_id) === id ? { ...a, ...newAlert } : a))
          }
          return [newAlert, ...prev]
        })
      } else {
        setAutoAlerts((prev) => {
          const id = newAlert.alert_id || newAlert.id
          const exists = prev.some((a) => (a.alert_id || a.id) === id)
          if (exists) {
            return prev.map((a) => ((a.alert_id || a.id) === id ? { ...a, ...newAlert } : a))
          }
          return [newAlert, ...prev]
        })
      }
    }

    window.addEventListener('new-market-alert', handleLiveAlert)

    // 2. Background polling sync every 15s while view is active
    const syncTimer = setInterval(() => {
      loadAlerts()
      loadAutoAlerts()
    }, 15000)

    return () => {
      window.removeEventListener('new-market-alert', handleLiveAlert)
      clearInterval(syncTimer)
    }
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

  // Trigger test alert (clearly marked as TEST)
  const handleTriggerTest = async (isInvalidation = false) => {
    setTesting(true)
    try {
      await callRef.current('/skills/alerts/auto/test', {
        alert_type: isInvalidation ? 'SQUEEZE_BREAKOUT' : 'GAMMA_BLAST',
        stage: isInvalidation ? 'INVALIDATED' : 'EARLY_WARNING',
        symbol: isInvalidation ? 'RELIANCE' : 'NIFTY',
        is_invalidation: isInvalidation,
      })
      await loadAutoAlerts()
    } catch (_) {
    } finally {
      setTesting(false)
    }
  }

  // Check invalidations immediately
  const handleCheckInvalidations = async () => {
    try {
      await callRef.current('/skills/alerts/auto/check_invalidations', {})
      await loadAutoAlerts()
    } catch (_) {}
  }

  // Trigger test target achieved or trailing alert
  const handleTriggerTestTarget = async (milestone = 'T1', shouldTrail = true) => {
    setTesting(true)
    try {
      await callRef.current('/skills/alerts/auto/test_target', {
        milestone,
        should_trail: shouldTrail,
        symbol: 'RELIANCE',
      })
      await loadAutoAlerts()
    } catch (_) {
    } finally {
      setTesting(false)
    }
  }

  // Check targets and trailing stops immediately
  const handleCheckTargets = async () => {
    try {
      await callRef.current('/skills/alerts/auto/check_targets', {})
      await loadAutoAlerts()
    } catch (_) {}
  }

  const handleClearAuto = async () => {
    try {
      await callRef.current('/skills/alerts/auto/clear', {})
      setAutoAlerts([])
    } catch (_) {}
  }

  const handleInspectOptions = () => {
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

  // Invalidation count for banner
  const invalidatedAlerts = autoAlerts.filter((a) => a.is_invalidated || a.stage === 'INVALIDATED')
  const invalidatedCount = invalidatedAlerts.length

  // Filter auto-alerts
  const filteredAutoAlerts = autoAlerts.filter((a) => {
    if (selectedFilter === 'INVALIDATED') {
      if (!a.is_invalidated && a.stage !== 'INVALIDATED') return false
    } else if (selectedFilter === 'TARGET_HIT') {
      if (
        a.stage !== 'T1_ACHIEVED' &&
        a.stage !== 'TARGET_ACHIEVED' &&
        a.target_status !== 'T1_ACHIEVED' &&
        a.target_status !== 'TARGET_ACHIEVED'
      ) return false
    } else if (selectedFilter !== 'ALL' && a.alert_type !== selectedFilter) {
      return false
    }

    if (selectedStage !== 'ALL') {
      if (selectedStage === 'INVALIDATED' && !a.is_invalidated && a.stage !== 'INVALIDATED') return false
      if (selectedStage === 'T1_ACHIEVED' && a.stage !== 'T1_ACHIEVED' && a.target_status !== 'T1_ACHIEVED') return false
      if (selectedStage === 'TARGET_ACHIEVED' && a.stage !== 'TARGET_ACHIEVED' && a.target_status !== 'TARGET_ACHIEVED') return false
      if (
        selectedStage !== 'INVALIDATED' &&
        selectedStage !== 'T1_ACHIEVED' &&
        selectedStage !== 'TARGET_ACHIEVED' &&
        a.stage !== selectedStage
      ) return false
    }

    if (selectedEnv === 'LIVE') {
      if (a.environment === 'TEST' || a.is_live === false) return false
    } else if (selectedEnv === 'TEST') {
      if (a.environment !== 'TEST' && a.is_live !== false) return false
    }

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
            Real-time early warnings · Live vs Test clear distinction · Proactive View Invalidation alerts
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

      {/* Invalidation Alert Banner */}
      {invalidatedCount > 0 && activeTab === 'auto' && (
        <div className="p-3 rounded-2xl bg-rose-500/10 border border-rose-500/35 text-rose-200 flex items-center justify-between gap-3 animate-slide-up-fade">
          <div className="flex items-center gap-2.5 text-xs">
            <span className="text-xl flex-shrink-0">🛑</span>
            <div>
              <span className="font-bold">
                ⚠️ {invalidatedCount} Trade {invalidatedCount === 1 ? 'Setup' : 'Setups'} Invalidated:
              </span>
              <span className="ml-1 text-rose-300/80">
                {invalidatedAlerts.map((a) => `${a.symbol} (${a.alert_type.replace('_', ' ')})`).slice(0, 3).join(', ')}
                {invalidatedCount > 3 ? '...' : ''} no longer valid due to stop-loss breach or structural failure.
              </span>
            </div>
          </div>
          <button
            onClick={() => {
              setSelectedFilter('INVALIDATED')
              setSelectedStage('ALL')
            }}
            className="btn btn-sm btn-ghost text-rose-300 hover:bg-rose-500/20 text-xs flex-shrink-0"
          >
            View Invalidated ({invalidatedCount}) →
          </button>
        </div>
      )}

      {/* ── TAB 1: Real-Time Auto-Alerts ────────────────────────────── */}
      {activeTab === 'auto' && (
        <div className="space-y-3">
          {/* Action Toolbar */}
          <div className="flex items-center justify-between flex-wrap gap-2 p-2 rounded-xl bg-panel border border-border">
            {/* Category Filter Chips */}
            <div className="flex items-center gap-1 flex-wrap text-[11px]">
              {[
                { id: 'ALL', label: 'All Alerts' },
                { id: 'TARGET_HIT', label: '🎯 Targets Achieved' },
                { id: 'GAMMA_BLAST', label: '⚡ Gamma Blast' },
                { id: 'SQUEEZE_BREAKOUT', label: '🎯 Squeeze Breakout' },
                { id: 'CIRCUIT_WARNING', label: '🔒 Circuit Warning' },
                { id: 'INVALIDATED', label: `❌ Invalidated (${invalidatedCount})` },
              ].map((chip) => (
                <button
                  key={chip.id}
                  onClick={() => setSelectedFilter(chip.id)}
                  className={`px-2.5 py-1 rounded-lg font-bold transition-all ${
                    selectedFilter === chip.id
                      ? chip.id === 'INVALIDATED'
                        ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                        : chip.id === 'TARGET_HIT'
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                        : 'bg-gold/20 text-gold border border-gold/40'
                      : 'text-muted hover:text-text hover:bg-elevated'
                  }`}
                >
                  {chip.label}
                </button>
              ))}
            </div>

            {/* Stage, Environment & Testing Buttons */}
            <div className="flex items-center gap-2 ml-auto flex-wrap">
              {/* Environment Filter */}
              <select
                value={selectedEnv}
                onChange={(e) => setSelectedEnv(e.target.value)}
                className="input-field text-[11px] py-1 px-2"
                title="Filter by Live market data vs Test simulation"
              >
                <option value="ALL">All Environments</option>
                <option value="LIVE">🟢 Real / Live Only</option>
                <option value="TEST">🧪 Test Only</option>
              </select>

              {/* Stage Filter */}
              <select
                value={selectedStage}
                onChange={(e) => setSelectedStage(e.target.value)}
                className="input-field text-[11px] py-1 px-2"
              >
                <option value="ALL">All Stages</option>
                <option value="EARLY_WARNING">⏳ Early-Warning Only</option>
                <option value="IGNITED">🔥 Ignited Only</option>
                <option value="T1_ACHIEVED">🎯 Target 1 Reached</option>
                <option value="TARGET_ACHIEVED">🏁 Final Target Reached</option>
                <option value="INVALIDATED">❌ Invalidated Only</option>
              </select>

              {/* Action Buttons */}
              <button
                onClick={handleScanNow}
                disabled={scanning}
                className="btn btn-sm btn-gold text-xs flex items-center gap-1"
                title="Scan live market feeds now"
              >
                {scanning ? '⚡ Scanning…' : '⚡ Scan Now'}
              </button>

              {/* Test Trigger Buttons */}
              <button
                onClick={() => handleTriggerTestTarget('T1', true)}
                disabled={testing}
                className="btn btn-sm btn-ghost text-xs text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/20 flex items-center gap-1"
                title="Trigger simulated Target 1 hit with Breakeven Trailing Stop"
              >
                🎯 Test Target
              </button>

              <button
                onClick={() => handleTriggerTestTarget('FINAL', false)}
                disabled={testing}
                className="btn btn-sm btn-ghost text-xs text-amber-300 border border-amber-500/30 hover:bg-amber-500/20 flex items-center gap-1"
                title="Trigger simulated Final Target hit with Book Full Profit advice"
              >
                🏁 Test Full Target
              </button>

              <button
                onClick={() => handleTriggerTestTarget('TRAIL', true)}
                disabled={testing}
                className="btn btn-sm btn-ghost text-xs text-blue-300 border border-blue-500/30 hover:bg-blue-500/20 flex items-center gap-1"
                title="Trigger simulated Trailing Stop ratchet update"
              >
                📈 Test Trail SL
              </button>

              <button
                onClick={() => handleTriggerTest(true)}
                disabled={testing}
                className="btn btn-sm btn-ghost text-xs text-rose-300 border border-rose-500/30 hover:bg-rose-500/20 flex items-center gap-1"
                title="Trigger a simulated invalidation alert"
              >
                ⚠️ Test Invalidation
              </button>

              <button
                onClick={handleCheckTargets}
                className="btn btn-sm btn-ghost text-xs text-muted hover:text-cyan-300 border border-border"
                title="Check for newly reached targets and trailing stop adjustments"
              >
                🔍 Check Targets
              </button>

              <button
                onClick={handleCheckInvalidations}
                className="btn btn-sm btn-ghost text-xs text-muted hover:text-amber-300 border border-border"
                title="Check for newly invalidated setups against live LTP"
              >
                🔍 Check Invalidations
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
            <UnavailableState title="Checking market feeds" reason="Scanning for real-time Gamma Blasts, Squeezes, and Invalidations." size="md" />
          ) : filteredAutoAlerts.length === 0 ? (
            <div className="p-8 text-center rounded-2xl bg-panel border border-border space-y-2">
              <div className="text-3xl">📡</div>
              <div className="text-sm font-bold text-text">No active alerts match this filter</div>
              <p className="text-xs text-muted max-w-md mx-auto">
                The alert engine actively monitors Gamma Blasts, TTM Squeezes, Circuit Proxies, and tracks whether active setups remain valid.
                Use <span className="text-gold font-bold">Scan Now</span> or <span className="text-purple-300 font-bold">Test Alert</span> to verify notifications.
              </p>
              <div className="flex items-center justify-center gap-2 pt-2">
                <button onClick={handleScanNow} className="btn btn-sm btn-gold">
                  ⚡ Scan Watchlist Now
                </button>
                <button onClick={() => handleTriggerTest(false)} className="btn btn-sm btn-ghost text-purple-300 border border-purple-500/30">
                  🧪 Send Test Alert
                </button>
              </div>
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
