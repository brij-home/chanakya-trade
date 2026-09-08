import { useState } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'

export default function AlertsCard({ data }) {
  const port    = useChatStore((s) => s.port)
  const d       = data?.data ?? data ?? {}
  const [alerts, setAlerts] = useState(d.alerts ?? d.active_alerts ?? (Array.isArray(data) ? data : []))
  const [removing, setRemoving] = useState(null)

  async function remove(alertId) {
    setRemoving(alertId)
    try {
      await fetch(`${getBaseUrl(port)}/skills/alerts/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alert_id: alertId }),
      })
      setAlerts(prev => prev.filter(a => (a.id ?? a.alert_id) !== alertId))
    } catch (_) {}
    setRemoving(null)
  }

  if (!alerts.length) {
    return (
      <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full">
        <p className="text-muted text-[10px] uppercase tracking-widest font-ui mb-3">Alerts</p>
        <p className="text-muted text-sm font-ui">No active alerts. Use <code className="font-mono text-amber">alert SYMBOL above/below PRICE</code> to add one.</p>
      </div>
    )
  }

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full">
      <p className="text-muted text-[10px] uppercase tracking-widest font-ui mb-3">
        Alerts <span className="text-subtle">({alerts.length})</span>
      </p>
      <div className="space-y-2">
        {alerts.map((a, idx) => {
          // Stable key: never use Math.random() — causes every alert to re-render on each tick.
          const id = a.id ?? a.alert_id ?? `${a.symbol ?? 'unk'}-${a.triggered_at ?? a.created_at ?? a.timestamp ?? idx}`
          const symbol    = a.symbol ?? '—'
          const condition = a.condition ?? a.description ?? '—'
          const threshold = a.threshold != null ? `₹${Number(a.threshold).toLocaleString('en-IN')}` : ''
          const isTest     = a.environment === 'TEST' || a.is_live === false
          const isInvalidated = a.is_invalidated || a.stage === 'INVALIDATED'
          const triggered = Boolean(a.triggered || a.target_achieved)
          const isTargetAchieved = Boolean(a.target_achieved || a.target_status === 'T1_HIT' || a.target_status === 'TARGET_HIT')
          const isFinalHit = a.target_status === 'TARGET_HIT'
          const hasTrail = Boolean(a.should_trail && a.trailing_stop)

          const rawTime = a.timestamp || a.triggered_at || a.invalidated_at || a.created_at || ''
          let timeDisplay = ''
          if (rawTime) {
            const parts = rawTime.trim().split(' ')
            timeDisplay = parts.length >= 2 ? parts[1] : parts[0]
          }

          return (
            <div key={id} className={`flex items-start justify-between rounded-lg border px-3 py-2.5
              ${isInvalidated ? 'border-rose-500/40 bg-rose-500/5' : isFinalHit ? 'border-emerald-500/40 bg-emerald-500/5' : isTargetAchieved ? 'border-cyan-500/40 bg-cyan-500/5' : triggered ? 'border-green/40 bg-green/5' : 'border-border bg-panel'}`}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-text text-[12px] font-mono font-semibold">{symbol}</span>
                  <span className={`text-[9px] px-1.5 py-0.2 rounded font-black uppercase tracking-wider ${isTest ? 'bg-purple-500/20 text-purple-300' : 'bg-emerald-500/20 text-emerald-300'}`}>
                    {isTest ? '🧪 TEST' : '🟢 LIVE'}
                  </span>
                  {isInvalidated ? (
                    <span className="text-[10px] font-ui text-rose-400 font-bold">❌ INVALIDATED</span>
                  ) : isFinalHit ? (
                    <span className="text-[10px] font-ui text-emerald-400 font-bold">🏁 TARGET HIT</span>
                  ) : isTargetAchieved ? (
                    <span className="text-[10px] font-ui text-cyan-400 font-bold">🎯 T1 HIT</span>
                  ) : (
                    <span className={`text-[10px] font-ui ${triggered ? 'text-green font-semibold' : 'text-muted'}`}>
                      {triggered ? '✓ triggered' : '● active'}
                    </span>
                  )}
                  {hasTrail && (
                    <span className="text-[9px] px-1.5 py-0.2 rounded font-mono font-bold bg-amber-500/20 text-amber-300">
                      📈 TRAIL: ₹{Number(a.trailing_stop).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </span>
                  )}
                  {timeDisplay && (
                    <span className="text-[9px] font-mono text-muted/70 ml-auto flex items-center gap-0.5" title={rawTime}>
                      🕒 {timeDisplay}
                    </span>
                  )}
                </div>
                <p className="text-muted text-[11px] font-ui mt-0.5 truncate">
                  {condition} {threshold}
                </p>
                {isInvalidated && a.invalidation_reason && (
                  <p className="text-rose-400 text-[10px] font-ui mt-0.5">
                    ⚠️ {a.invalidation_reason}
                  </p>
                )}
                {a.trailing_decision && (
                  <div className="mt-1.5 px-2 py-1 rounded bg-surface/80 border border-border/60 text-[10px] font-ui flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-text">
                      {a.should_trail ? '⚡ TRAIL STOP:' : '🛡️ MAINTAIN:'}
                    </span>
                    <span className={`px-1 rounded font-mono font-semibold ${a.should_trail ? 'text-emerald-300 bg-emerald-500/10' : 'text-amber-300 bg-amber-500/10'}`}>
                      {a.trailing_decision}
                    </span>
                    {a.locked_profit_pct != null && (
                      <span className="text-emerald-400 font-mono">
                        +{Number(a.locked_profit_pct).toFixed(1)}% Locked
                      </span>
                    )}
                    {a.trailing_rationale && (
                      <span className="text-subtle truncate max-w-xs" title={a.trailing_rationale}>
                        • {a.trailing_rationale}
                      </span>
                    )}
                  </div>
                )}
              </div>
              <button
                onClick={() => remove(id)}
                disabled={removing === id}
                className="ml-3 text-subtle hover:text-red text-[11px] font-ui transition-colors
                           disabled:opacity-40 flex-shrink-0"
              >
                {removing === id ? '…' : '✕'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
