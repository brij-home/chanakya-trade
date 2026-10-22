import { useState, useEffect, useCallback } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { useToastStore } from '../../hooks/useToast'

/**
 * OpsDrawer — Slide-out triage and operations drawer.
 * Provides instant visibility into critical P0/P1 incidents,
 * Fyers circuit breaker status, and 1-click remediation actions.
 */
export default function OpsDrawer({ isOpen, onClose, onOpenOpsDeck }) {
  const port = useChatStore((s) => s.port)
  const addToast = useToastStore((s) => s.addToast)

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [actionInProgress, setActionInProgress] = useState('')
  const [expandedIncident, setExpandedIncident] = useState(null)

  const fetchHubData = useCallback(async () => {
    if (!port || !isOpen) return
    try {
      setLoading(true)
      const res = await fetch(`${getBaseUrl(port)}/api/system/health-hub?limit=30`, {
        signal: AbortSignal.timeout(10000),
      })
      if (res.ok) {
        const json = await res.json()
        setData(json)
      }
    } catch (_) {
      // Degraded
    } finally {
      setLoading(false)
    }
  }, [port, isOpen])

  useEffect(() => {
    if (isOpen) {
      fetchHubData()
      const interval = setInterval(fetchHubData, 4000)
      return () => clearInterval(interval)
    }
  }, [isOpen, fetchHubData])

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  // Actions
  const handleResetBreaker = async () => {
    try {
      setActionInProgress('reset_cb')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/circuit-breaker/reset`, { method: 'POST' })
      if (res.ok) {
        addToast({ title: 'Circuit Breaker Reset', message: 'Fyers circuit breaker returned to CLOSED state.', type: 'success' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Reset Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleProbeBreaker = async () => {
    try {
      setActionInProgress('probe_cb')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/circuit-breaker/probe`, { method: 'POST' })
      if (res.ok) {
        addToast({ title: 'Breaker in HALF_OPEN', message: 'Circuit breaker permitted single probe request.', type: 'info' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Probe Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleClearIncidents = async () => {
    try {
      setActionInProgress('clear_incidents')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/incidents/clear`, { method: 'POST' })
      if (res.ok) {
        addToast({ title: 'Incidents Cleared', message: 'In-memory and disk telemetry logs cleared.', type: 'info' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Clear Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handlePurgeCache = async () => {
    try {
      setActionInProgress('purge_cache')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/purge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vacuum_databases: false }),
      })
      if (res.ok) {
        addToast({ title: 'Storage Purged', message: 'Ephemeral caches and old tick buffers purged.', type: 'success' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Purge Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  if (!isOpen) return null

  const overall = data?.overall_status || (loading ? 'SYNCING…' : 'NOMINAL')
  const cb = data?.circuit_breaker || {}
  const ws = data?.websocket || {}
  const counts = data?.incident_counts || { P0: 0, P1: 0, P2: 0, P3: 0 }
  const incidents = data?.incidents || []

  const statusColor =
    overall === 'HEALTHY' || overall === 'NOMINAL'
      ? 'var(--color-emerald)'
      : overall === 'DEGRADED' || overall === 'SYNCING…'
        ? 'var(--color-gold)'
        : 'var(--color-rose)'

  return (
    <div
      className="fixed inset-0 z-[160] flex justify-end bg-black/40 backdrop-blur-sm transition-opacity animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Operations and System Health Drawer"
    >
      <div
        className="w-[440px] md:w-[500px] h-full flex flex-col border-l border-border bg-panel shadow-2xl overflow-hidden animate-slide-left"
        onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--color-panel)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-elevated)' }}
        >
          <div className="flex items-center gap-2">
            <span className="text-base select-none">🛠️</span>
            <div>
              <h2 className="text-sm font-bold font-ui" style={{ color: 'var(--color-text)' }}>
                OpsDeck & Health Hub
              </h2>
              <p className="text-[10px] font-mono text-muted">
                System Diagnostics • Live Triage
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                onClose()
                onOpenOpsDeck()
              }}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer border"
              style={{
                background: 'rgba(245, 166, 35, 0.12)',
                borderColor: 'rgba(245, 166, 35, 0.35)',
                color: 'var(--color-gold)',
              }}
              title="Open full workspace view"
            >
              <span>Workspace ↗</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              className="w-7 h-7 flex items-center justify-center rounded-lg text-xs text-muted hover:text-text hover:bg-elevated transition-colors cursor-pointer"
              title="Close drawer (Esc)"
              aria-label="Close drawer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 no-scrollbar">
          {/* Status Ribbon */}
          <div
            className="p-3 rounded-xl border flex items-center justify-between"
            style={{
              background: 'var(--color-surface)',
              borderColor: 'var(--color-border)',
            }}
          >
            <div>
              <span className="text-[10px] font-mono uppercase text-muted tracking-wider block">
                Overall Health
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className={`w-2.5 h-2.5 rounded-full ${loading ? 'animate-pulse' : ''}`}
                  style={{ background: statusColor, boxShadow: `0 0 8px ${statusColor}` }}
                />
                <span className="text-sm font-mono font-black" style={{ color: statusColor }}>
                  {overall}
                </span>
              </div>
            </div>

            {/* Priority Counts */}
            <div className="flex items-center gap-1.5">
              <span
                className="px-2 py-0.5 rounded font-mono text-xs font-bold"
                style={{ background: 'rgba(255, 79, 123, 0.15)', color: 'var(--color-rose)' }}
                title="P0 Critical Issues"
              >
                P0: {counts.P0 || 0}
              </span>
              <span
                className="px-2 py-0.5 rounded font-mono text-xs font-bold"
                style={{ background: 'rgba(245, 166, 35, 0.15)', color: 'var(--color-gold)' }}
                title="P1 High / Degraded Issues"
              >
                P1: {counts.P1 || 0}
              </span>
              <span
                className="px-2 py-0.5 rounded font-mono text-xs font-bold"
                style={{ background: 'rgba(77, 155, 255, 0.15)', color: 'var(--color-sapphire)' }}
                title="P2/P3 Operational Events"
              >
                P2: {counts.P2 || 0}
              </span>
            </div>
          </div>

          {/* Fyers Circuit Breaker Card */}
          <div
            className="p-3 rounded-xl border space-y-2.5"
            style={{
              background: cb.state === 'OPEN' ? 'rgba(255, 79, 123, 0.08)' : 'var(--color-surface)',
              borderColor: cb.state === 'OPEN' ? 'var(--color-rose)' : 'var(--color-border)',
            }}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs">⚡</span>
                <span className="text-xs font-bold font-ui" style={{ color: 'var(--color-text)' }}>
                  Fyers REST Circuit Breaker
                </span>
              </div>
              <span
                className="px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase tracking-wider"
                style={{
                  background: cb.state === 'CLOSED' ? 'rgba(0,214,143,0.15)' : cb.state === 'HALF_OPEN' ? 'rgba(245,166,35,0.15)' : 'rgba(255,79,123,0.2)',
                  color: cb.state === 'CLOSED' ? 'var(--color-emerald)' : cb.state === 'HALF_OPEN' ? 'var(--color-gold)' : 'var(--color-rose)',
                }}
              >
                {cb.state || 'CLOSED'}
              </span>
            </div>

            {cb.state === 'OPEN' && (
              <div className="text-xs space-y-1.5 p-2 rounded bg-black/20 border border-rose/30">
                <div className="flex items-center justify-between text-rose font-mono font-bold">
                  <span>{cb.daily_quota_exhausted ? 'Daily 5K Cap Hit:' : 'Cooldown Active:'}</span>
                  <span>
                    {cb.daily_quota_exhausted
                      ? `${Math.max(1, Math.round((cb.remaining_cooldown_seconds || 0) / 3600))}h until Midnight IST`
                      : `${Math.ceil(cb.remaining_cooldown_seconds || 0)}s remaining`}
                  </span>
                </div>
                {cb.last_trip_reason && (
                  <p className="text-[11px] text-muted font-mono leading-tight">
                    {cb.last_trip_reason}
                  </p>
                )}
                {cb.daily_quota_exhausted && (
                  <div className="mt-1 p-2 rounded bg-amber-500/10 border border-amber-500/20 text-[10px] text-amber-300 space-y-1">
                    <p className="font-semibold">💡 Failsafe: WebSocket Quotes Streaming Active ({ws.total_subscribed || 676} symbols)</p>
                    <p className="text-muted leading-tight">
                      Fyers free Standard plan caps REST at 5,000 req/day. To eliminate rate caps, upgrade to Fyers Prime or enable a secondary data broker (Shoonya/Angel One).
                    </p>
                  </div>
                )}
              </div>
            )}

            <div className="flex items-center gap-2 pt-1">
              {cb.state === 'OPEN' && (
                <button
                  type="button"
                  disabled={actionInProgress === 'probe_cb'}
                  onClick={handleProbeBreaker}
                  className="flex-1 py-1 rounded text-xs font-mono font-semibold transition-all cursor-pointer bg-elevated hover:bg-highlight border border-border"
                >
                  {actionInProgress === 'probe_cb' ? 'Probing…' : 'Probe Breaker'}
                </button>
              )}
              <button
                type="button"
                disabled={actionInProgress === 'reset_cb'}
                onClick={handleResetBreaker}
                className="flex-1 py-1 rounded text-xs font-mono font-semibold transition-all cursor-pointer bg-elevated hover:bg-highlight border border-border"
              >
                {actionInProgress === 'reset_cb' ? 'Resetting…' : 'Force Reset'}
              </button>
            </div>
          </div>

          {/* WebSocket Capacity Card */}
          <div
            className="p-3 rounded-xl border space-y-2"
            style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold font-ui text-text">
                WebSocket Feed Subscriptions
              </span>
              <span className="text-xs font-mono font-bold text-muted">
                {ws.total_subscribed || 0} / {ws.max_capacity || 5000}
              </span>
            </div>
            {/* Progress bar */}
            <div className="w-full h-1.5 rounded-full bg-panel overflow-hidden border border-border/50">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${Math.min(ws.utilization_pct || 0, 100)}%`,
                  background: (ws.utilization_pct || 0) > 90 ? 'var(--color-rose)' : 'var(--color-sapphire)',
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] font-mono text-muted">
              <span>Core Index & F&O: {ws.core_count || 0}</span>
              <span>Dynamic Screener: {ws.dynamic_count || 0}</span>
            </div>
          </div>

          {/* Incident Stream (P0 & P1 Prioritized) */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold font-ui tracking-wide text-text uppercase">
                Active Incidents ({incidents.length})
              </span>
              <button
                type="button"
                onClick={handleClearIncidents}
                disabled={actionInProgress === 'clear_incidents'}
                className="text-[10px] font-mono text-muted hover:text-text cursor-pointer"
              >
                Clear History
              </button>
            </div>

            {incidents.length === 0 ? (
              <div className="p-4 rounded-xl border border-border text-center text-xs font-mono text-muted">
                ✓ No active system errors or warnings recorded.
              </div>
            ) : (
              <div className="space-y-2">
                {incidents.slice(0, 10).map((inc, i) => {
                  const isP0 = inc.priority === 'P0'
                  const isP1 = inc.priority === 'P1'
                  const pColor = isP0 ? 'var(--color-rose)' : isP1 ? 'var(--color-gold)' : 'var(--color-sapphire)'
                  const isExp = expandedIncident === inc.incident_id || expandedIncident === i

                  return (
                    <div
                      key={inc.incident_id || i}
                      className="p-2.5 rounded-lg border text-xs font-mono space-y-1 transition-all"
                      style={{
                        background: isP0 ? 'rgba(255, 79, 123, 0.06)' : 'var(--color-surface)',
                        borderColor: isP0 ? 'rgba(255, 79, 123, 0.4)' : 'var(--color-border)',
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className="px-1.5 py-0.2 rounded font-bold text-[11px]"
                          style={{
                            background: isP0 ? 'rgba(255, 79, 123, 0.2)' : isP1 ? 'rgba(245, 166, 35, 0.2)' : 'rgba(77, 155, 255, 0.15)',
                            color: pColor,
                          }}
                        >
                          {inc.priority || 'P2'} • {inc.component || 'SYSTEM'}
                        </span>
                        <span className="text-[10px] text-muted">
                          {inc.timestamp?.slice(11, 19) || 'Just now'}
                        </span>
                      </div>

                      <p className="font-semibold text-text leading-tight">
                        {inc.reason || inc.action_taken || 'Unknown anomaly'}
                      </p>

                      {inc.action_taken && (
                        <p className="text-[10px] text-muted">
                          <span className="text-muted/70">Action:</span> {inc.action_taken}
                        </p>
                      )}

                      {/* Expandable stack trace */}
                      {inc.details?.traceback && (
                        <div>
                          <button
                            type="button"
                            onClick={() => setExpandedIncident(isExp ? null : inc.incident_id || i)}
                            className="text-[10px] text-sapphire hover:underline cursor-pointer"
                          >
                            {isExp ? 'Hide Traceback ▲' : 'Show Traceback ▼'}
                          </button>
                          {isExp && (
                            <pre className="mt-1.5 p-2 rounded bg-black/40 text-[11px] text-muted overflow-x-auto max-h-40 no-scrollbar">
                              {inc.details.traceback}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Quick Maintenance Actions */}
          <div
            className="p-3 rounded-xl border space-y-2"
            style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <span className="text-xs font-bold font-ui text-text">
              1-Click Maintenance Operations
            </span>
            <div className="grid grid-cols-2 gap-2 pt-1">
              <button
                type="button"
                onClick={handlePurgeCache}
                disabled={actionInProgress === 'purge_cache'}
                className="py-1.5 px-2 rounded-lg text-xs font-mono font-medium bg-elevated hover:bg-highlight border border-border text-text transition-colors cursor-pointer text-center"
              >
                {actionInProgress === 'purge_cache' ? 'Purging…' : '🧹 Purge Ephemeral Cache'}
              </button>
              <button
                type="button"
                onClick={fetchHubData}
                disabled={loading}
                className="py-1.5 px-2 rounded-lg text-xs font-mono font-medium bg-elevated hover:bg-highlight border border-border text-text transition-colors cursor-pointer text-center"
              >
                {loading ? 'Refreshing…' : '🔄 Refresh Vitals'}
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div
          className="p-3 border-t flex items-center justify-between flex-shrink-0"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-elevated)' }}
        >
          <span className="text-[10px] font-mono text-muted">
            Auto-refreshes every 4s
          </span>
          <button
            type="button"
            onClick={() => {
              onClose()
              onOpenOpsDeck()
            }}
            className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer bg-gold text-black hover:brightness-105"
          >
            Launch Full OpsDeck Workspace →
          </button>
        </div>
      </div>
    </div>
  )
}
