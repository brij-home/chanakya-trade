import { useState, useEffect, useCallback, useMemo } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { useToastStore } from '../../hooks/useToast'

/**
 * OpsDeckView — Institutional Operations, Maintenance & Monitoring Terminal.
 * Provides complete visibility into system health, Fyers circuit breaker status,
 * WebSocket subscription capacity, priority-segregated incidents (P0–P3),
 * broker connectivity, SLO tracking, and 1-click maintenance tools.
 */
export default function OpsDeckView() {
  const port = useChatStore((s) => s.port)
  const addToast = useToastStore((s) => s.addToast)

  const [activeTab, setActiveTab] = useState('incidents')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPriority, setSelectedPriority] = useState('ALL')
  const [selectedComponent, setSelectedComponent] = useState('ALL')
  const [expandedTracebacks, setExpandedTracebacks] = useState({})
  const [actionInProgress, setActionInProgress] = useState('')

  const fetchHubData = useCallback(async () => {
    if (!port) return
    try {
      setLoading(true)
      const res = await fetch(`${getBaseUrl(port)}/api/system/health-hub?limit=150`, {
        signal: AbortSignal.timeout(4000),
      })
      if (res.ok) {
        const json = await res.json()
        setData(json)
      }
    } catch (e) {
      // Degraded
    } finally {
      setLoading(false)
    }
  }, [port])

  useEffect(() => {
    fetchHubData()
    const interval = setInterval(fetchHubData, 6000)
    return () => clearInterval(interval)
  }, [fetchHubData])

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
      addToast({ title: 'Action Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleProbeBreaker = async () => {
    try {
      setActionInProgress('probe_cb')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/circuit-breaker/probe`, { method: 'POST' })
      if (res.ok) {
        addToast({ title: 'Breaker in HALF_OPEN', message: 'Fyers circuit breaker opened for single probe request.', type: 'info' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Action Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleClearIncidents = async () => {
    try {
      setActionInProgress('clear_incidents')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/incidents/clear`, { method: 'POST' })
      if (res.ok) {
        addToast({ title: 'Incidents Cleared', message: 'All telemetry logs and incident records cleared.', type: 'info' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Clear Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handlePurgeStorage = async (vacuum = false) => {
    try {
      setActionInProgress('purge_storage')
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/purge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_tick_retention_days: 7,
          disk_cache_retention_days: 7,
          export_retention_days: 14,
          vacuum_databases: vacuum,
        }),
      })
      if (res.ok) {
        addToast({
          title: vacuum ? 'Storage Purged & Vacuumed' : 'Ephemeral Cache Purged',
          message: 'Preserved order ledger; cleared ephemeral ticks and cached states.',
          type: 'success',
        })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Purge Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleTriggerEODSync = async () => {
    try {
      setActionInProgress('sync_eod')
      addToast({ title: 'EOD Sync Started', message: 'Synchronizing daily historical bars in background…', type: 'info' })
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/sync-eod`, { method: 'POST' })
      if (res.ok) {
        addToast({ title: 'EOD Sync Complete', message: 'Daily bars verified and SQLite WAL checkpointed.', type: 'success' })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'EOD Sync Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const toggleTraceback = (id) => {
    setExpandedTracebacks((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  // Filtered incidents
  const filteredIncidents = useMemo(() => {
    const list = data?.incidents || []
    return list.filter((inc) => {
      if (selectedPriority !== 'ALL' && inc.priority !== selectedPriority) return false
      if (selectedComponent !== 'ALL' && !inc.component?.toLowerCase().includes(selectedComponent.toLowerCase())) {
        return false
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchReason = inc.reason?.toLowerCase().includes(q)
        const matchComp = inc.component?.toLowerCase().includes(q)
        const matchId = inc.incident_id?.toLowerCase().includes(q)
        const matchAction = inc.action_taken?.toLowerCase().includes(q)
        if (!matchReason && !matchComp && !matchId && !matchAction) return false
      }
      return true
    })
  }, [data?.incidents, selectedPriority, selectedComponent, searchQuery])

  const overall = data?.overall_status || 'UNKNOWN'
  const cb = data?.circuit_breaker || {}
  const ws = data?.websocket || {}
  const counts = data?.incident_counts || { P0: 0, P1: 0, P2: 0, P3: 0 }
  const brokers = data?.brokers || {}
  const slo = data?.slo_report || {}
  const providerHealth = data?.provider_health || {}
  const telem = data?.telemetry_summary || {}
  const memory = data?.memory || {}
  const storage = data?.storage || {}

  const overallColor = overall === 'HEALTHY' ? 'var(--color-emerald)' : overall === 'DEGRADED' ? 'var(--color-gold)' : 'var(--color-rose)'

  return (
    <div className="flex flex-col h-full bg-surface overflow-hidden select-none font-ui">
      {/* ── Top Bar / Header ────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-panel flex-shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-3">
          <span className="text-xl select-none">🛠️</span>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-black font-ui tracking-wide" style={{ color: 'var(--color-text)' }}>
                OpsDeck & System Health Terminal
              </h1>
              <span
                className="px-2 py-0.5 rounded font-mono text-[10px] font-bold tracking-wider uppercase border"
                style={{
                  background: overall === 'HEALTHY' ? 'rgba(0,214,143,0.12)' : overall === 'DEGRADED' ? 'rgba(245,166,35,0.15)' : 'rgba(255,79,123,0.2)',
                  borderColor: overallColor,
                  color: overallColor,
                }}
              >
                ● {overall}
              </span>
            </div>
            <p className="text-xs font-mono text-muted">
              Live Observability • Circuit Breakers • Prioritized Triage (P0–P3)
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchHubData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-elevated hover:bg-highlight border border-border text-text transition-all cursor-pointer"
            title="Refresh all metrics"
          >
            <span>{loading ? '⟳' : '🔄'}</span>
            <span>{loading ? 'Refreshing…' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* ── Vitals Overview Ribbon ─────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-3 bg-panel/40 border-b border-border/70 flex-shrink-0">
        {/* Card 1: Fyers Circuit Breaker */}
        <div
          className="p-3 rounded-xl border flex flex-col justify-between"
          style={{
            background: cb.state === 'OPEN' ? 'rgba(255, 79, 123, 0.08)' : 'var(--color-elevated)',
            borderColor: cb.state === 'OPEN' ? 'var(--color-rose)' : 'var(--color-border)',
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider">
              Fyers Circuit Breaker
            </span>
            <span
              className="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold"
              style={{
                background: cb.state === 'CLOSED' ? 'rgba(0,214,143,0.15)' : 'rgba(255,79,123,0.2)',
                color: cb.state === 'CLOSED' ? 'var(--color-emerald)' : 'var(--color-rose)',
              }}
            >
              {cb.state || 'CLOSED'}
            </span>
          </div>

          <div className="my-1.5">
            {cb.state === 'OPEN' ? (
              <div className="text-xs font-mono text-rose font-bold">
                Cooldown: {Math.ceil(cb.remaining_cooldown_seconds || 0)}s left
              </div>
            ) : (
              <div className="text-xs font-mono text-emerald font-semibold">
                ✓ Normal Operation (10 req/s cap)
              </div>
            )}
          </div>

          <div className="flex items-center gap-1.5 pt-1">
            <button
              type="button"
              onClick={handleProbeBreaker}
              disabled={actionInProgress === 'probe_cb'}
              className="px-2 py-0.5 rounded text-[10px] font-mono bg-panel hover:bg-highlight border border-border text-muted hover:text-text cursor-pointer flex-1 text-center"
            >
              Probe
            </button>
            <button
              type="button"
              onClick={handleResetBreaker}
              disabled={actionInProgress === 'reset_cb'}
              className="px-2 py-0.5 rounded text-[10px] font-mono bg-panel hover:bg-highlight border border-border text-muted hover:text-text cursor-pointer flex-1 text-center"
            >
              Force Reset
            </button>
          </div>
        </div>

        {/* Card 2: WebSocket Capacity */}
        <div
          className="p-3 rounded-xl border flex flex-col justify-between"
          style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider">
              WebSocket Capacity
            </span>
            <span className="text-[11px] font-mono font-bold text-text">
              {ws.total_subscribed || 0} / {ws.max_capacity || 5000}
            </span>
          </div>

          <div className="my-1.5 space-y-1">
            <div className="w-full h-1.5 rounded-full bg-surface overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(ws.utilization_pct || 0, 100)}%`,
                  background: (ws.utilization_pct || 0) > 90 ? 'var(--color-rose)' : 'var(--color-sapphire)',
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] font-mono text-muted">
              <span>{ws.utilization_pct || 0}% used</span>
              <span>{5000 - (ws.total_subscribed || 0)} slots free</span>
            </div>
          </div>

          <div className="text-[10px] font-mono text-muted">
            Core: {ws.core_count || 0} • Dynamic: {ws.dynamic_count || 0}
          </div>
        </div>

        {/* Card 3: System Memory & SSD */}
        <div
          className="p-3 rounded-xl border flex flex-col justify-between"
          style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider">
              Host Vitals
            </span>
            <span
              className="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold"
              style={{
                color: (memory.process_rss_mb || 0) > 2000 ? 'var(--color-gold)' : 'var(--color-emerald)',
              }}
            >
              RSS: {Math.round(memory.process_rss_mb || 0)} MB
            </span>
          </div>

          <div className="my-1.5 text-xs font-mono space-y-0.5">
            <div className="flex justify-between text-muted">
              <span>System RAM:</span>
              <span className="text-text font-bold">{memory.system_ram_pct || 0}%</span>
            </div>
            <div className="flex justify-between text-muted">
              <span>SSD Free:</span>
              <span className="text-text font-bold">{storage.ssd_free_gb || '—'} GB</span>
            </div>
          </div>

          <div className="text-[10px] font-mono text-muted">
            SQLite WAL: {storage.tiers?.business?.wal_mb || 0} MB
          </div>
        </div>

        {/* Card 4: Incident Counts by Priority */}
        <div
          className="p-3 rounded-xl border flex flex-col justify-between"
          style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider">
              Prioritized Incidents
            </span>
            <span className="text-[10px] font-mono text-muted">Rolling buffer</span>
          </div>

          <div className="grid grid-cols-4 gap-1.5 my-1.5">
            <div className="text-center p-1 rounded bg-surface border border-rose/30">
              <span className="text-[9px] font-mono text-rose block font-bold">P0</span>
              <span className="text-xs font-mono font-black text-rose">{counts.P0 || 0}</span>
            </div>
            <div className="text-center p-1 rounded bg-surface border border-gold/30">
              <span className="text-[9px] font-mono text-gold block font-bold">P1</span>
              <span className="text-xs font-mono font-black text-gold">{counts.P1 || 0}</span>
            </div>
            <div className="text-center p-1 rounded bg-surface border border-sapphire/30">
              <span className="text-[9px] font-mono text-sapphire block font-bold">P2</span>
              <span className="text-xs font-mono font-black text-sapphire">{counts.P2 || 0}</span>
            </div>
            <div className="text-center p-1 rounded bg-surface border border-border">
              <span className="text-[9px] font-mono text-muted block font-bold">P3</span>
              <span className="text-xs font-mono font-black text-muted">{counts.P3 || 0}</span>
            </div>
          </div>

          <div className="text-[10px] font-mono text-muted flex justify-between">
            <span>Critical: {counts.P0 || 0}</span>
            <span>Degraded: {counts.P1 || 0}</span>
          </div>
        </div>
      </div>

      {/* ── Sub-Tabs Navigation Strip ───────────────────────────────── */}
      <div
        className="flex items-center justify-between px-4 border-b border-border bg-panel flex-shrink-0"
        style={{ borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center gap-1">
          <button
            type="button"
            data-testid="tab-incidents"
            onClick={() => setActiveTab('incidents')}
            className={`px-3 py-2 text-xs font-mono font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'incidents'
                ? 'border-gold text-gold bg-elevated/60'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            🚨 Incidents Matrix ({counts.P0 + counts.P1 + counts.P2 + counts.P3})
          </button>
          <button
            type="button"
            data-testid="tab-feeds"
            onClick={() => setActiveTab('feeds')}
            className={`px-3 py-2 text-xs font-mono font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'feeds'
                ? 'border-gold text-gold bg-elevated/60'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            📡 Feeds & Brokers
          </button>
          <button
            type="button"
            data-testid="tab-telemetry"
            onClick={() => setActiveTab('telemetry')}
            className={`px-3 py-2 text-xs font-mono font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'telemetry'
                ? 'border-gold text-gold bg-elevated/60'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            🤖 AI & SLO Telemetry
          </button>
          <button
            type="button"
            data-testid="tab-maintenance"
            onClick={() => setActiveTab('maintenance')}
            className={`px-3 py-2 text-xs font-mono font-bold border-b-2 transition-all cursor-pointer ${
              activeTab === 'maintenance'
                ? 'border-gold text-gold bg-elevated/60'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            🧹 Storage & Maintenance Tools
          </button>

        </div>

        {/* Quick Action Button */}
        {activeTab === 'incidents' && (
          <button
            type="button"
            onClick={handleClearIncidents}
            disabled={actionInProgress === 'clear_incidents'}
            className="text-[11px] font-mono text-muted hover:text-rose cursor-pointer px-2 py-1 rounded hover:bg-elevated transition-colors"
          >
            Clear All Incidents
          </button>
        )}
      </div>

      {/* ── Main Tab Content ────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4 no-scrollbar">
        {/* ─────────── TAB 1: INCIDENTS MATRIX ─────────── */}
        {activeTab === 'incidents' && (
          <div className="space-y-3 max-w-6xl mx-auto">
            {/* Filter toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-xl border border-border bg-panel">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] font-mono text-muted mr-1">Priority:</span>
                {['ALL', 'P0', 'P1', 'P2', 'P3'].map((p) => {
                  const isActive = selectedPriority === p
                  const color = p === 'P0' ? 'var(--color-rose)' : p === 'P1' ? 'var(--color-gold)' : p === 'P2' ? 'var(--color-sapphire)' : 'var(--color-muted)'
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setSelectedPriority(p)}
                      className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold cursor-pointer transition-all border ${
                        isActive ? 'bg-elevated' : 'border-transparent text-muted hover:text-text'
                      }`}
                      style={{
                        borderColor: isActive ? color : 'transparent',
                        color: isActive ? color : undefined,
                      }}
                    >
                      {p === 'ALL' ? 'All Priorities' : `${p} (${counts[p] || 0})`}
                    </button>
                  )
                })}
              </div>

              {/* Search Box */}
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="Search error, component, ID…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="px-2.5 py-1 text-xs font-mono bg-elevated border border-border rounded-lg outline-none w-48 focus:border-gold text-text"
                />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery('')}
                    className="text-xs text-muted hover:text-text cursor-pointer"
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>

            {/* Incidents List */}
            {filteredIncidents.length === 0 ? (
              <div className="p-12 text-center border border-border rounded-2xl bg-panel/30">
                <span className="text-3xl block mb-2">🎉</span>
                <h3 className="text-sm font-bold font-ui text-text">No Matching Incidents</h3>
                <p className="text-xs font-mono text-muted mt-1">
                  All systems operating within acceptable parameters for the selected filters.
                </p>
              </div>
            ) : (
              <div className="space-y-2.5">
                {filteredIncidents.map((inc, idx) => {
                  const isP0 = inc.priority === 'P0'
                  const isP1 = inc.priority === 'P1'
                  const pColor = isP0 ? 'var(--color-rose)' : isP1 ? 'var(--color-gold)' : 'var(--color-sapphire)'
                  const incKey = inc.incident_id || idx
                  const isExpanded = !!expandedTracebacks[incKey]

                  return (
                    <div
                      key={incKey}
                      className="p-3.5 rounded-xl border text-xs font-mono transition-all space-y-2"
                      style={{
                        background: isP0 ? 'rgba(255, 79, 123, 0.05)' : 'var(--color-panel)',
                        borderColor: isP0 ? 'rgba(255, 79, 123, 0.35)' : 'var(--color-border)',
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span
                            className="px-2 py-0.5 rounded font-black text-[10px] tracking-wider uppercase"
                            style={{
                              background: isP0 ? 'rgba(255, 79, 123, 0.2)' : isP1 ? 'rgba(245, 166, 35, 0.2)' : 'rgba(77, 155, 255, 0.15)',
                              color: pColor,
                            }}
                          >
                            {inc.priority || 'P2'}
                          </span>
                          <span className="text-text font-bold">
                            {inc.component || 'SYSTEM'}
                          </span>
                          <span className="text-muted/60">•</span>
                          <span className="text-muted text-[10px]">
                            {inc.event_type || 'INCIDENT'}
                          </span>
                          {inc.incident_id && (
                            <span className="text-muted/60 text-[10px]">
                              [{inc.incident_id}]
                            </span>
                          )}
                        </div>

                        <span className="text-muted text-[11px]">
                          {inc.timestamp ? new Date(inc.timestamp).toLocaleTimeString('en-IN') : 'Just now'}
                        </span>
                      </div>

                      <div className="text-sm font-bold text-text leading-snug">
                        {inc.reason || 'Unhandled System Condition'}
                      </div>

                      {inc.action_taken && (
                        <div className="text-xs text-muted flex items-start gap-1">
                          <span className="text-muted/60 font-semibold">Remediation / Action Taken:</span>
                          <span className="text-text">{inc.action_taken}</span>
                        </div>
                      )}

                      {/* Expandable Traceback */}
                      {inc.details?.traceback && (
                        <div className="pt-1">
                          <button
                            type="button"
                            onClick={() => toggleTraceback(incKey)}
                            className="text-xs text-sapphire hover:underline cursor-pointer flex items-center gap-1"
                          >
                            <span>{isExpanded ? '▲ Hide Full Traceback' : '▼ Inspect Full Traceback & Context'}</span>
                          </button>
                          {isExpanded && (
                            <div className="mt-2 p-3 rounded-lg bg-black/50 border border-border/80 text-[11px] font-mono text-muted overflow-x-auto max-h-60 no-scrollbar space-y-2">
                              <pre className="text-rose/90">{inc.details.traceback}</pre>
                              {inc.details?.system_vitals && (
                                <div className="pt-2 border-t border-border/40 text-[10px] text-muted flex gap-4">
                                  <span>RSS: {Math.round(inc.details.system_vitals.process_rss_mb || 0)} MB</span>
                                  <span>RAM: {inc.details.system_vitals.system_ram_pct || 0}%</span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ─────────── TAB 2: FEEDS & BROKERS ─────────── */}
        {activeTab === 'feeds' && (
          <div className="space-y-4 max-w-6xl mx-auto">
            {/* Brokers Connectivity Matrix */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                Broker Integrations & Session Status
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {Object.entries(brokers).map(([name, b]) => {
                  const isAuth = b.authenticated
                  const isConfig = b.configured
                  return (
                    <div
                      key={name}
                      className="p-3 rounded-xl border border-border bg-elevated flex items-center justify-between"
                    >
                      <div>
                        <span className="text-xs font-bold font-mono uppercase block text-text">
                          {name}
                        </span>
                        <span className="text-[10px] font-mono text-muted">
                          Role: {b.role || 'Data / Exec'}
                        </span>
                      </div>
                      <div className="text-right">
                        <span
                          className={`px-2 py-0.5 rounded font-mono text-[10px] font-bold ${
                            isAuth ? 'bg-emerald/15 text-emerald' : isConfig ? 'bg-gold/15 text-gold' : 'bg-surface text-muted'
                          }`}
                        >
                          {isAuth ? 'AUTHENTICATED' : isConfig ? 'CONFIGURED' : 'NOT CONFIGURED'}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* SLO Table */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                Service Level Objectives (SLO) — Latency & Availability
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono text-left">
                  <thead>
                    <tr className="border-b border-border text-muted text-[10px] uppercase">
                      <th className="py-2">Critical Journey</th>
                      <th>Availability</th>
                      <th>Target Avail</th>
                      <th>p95 Latency</th>
                      <th>p95 Target</th>
                      <th>Budget Consumed</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {Object.values(slo.journeys || {}).map((j, idx) => (
                      <tr key={j.journey_id || `slo-${idx}`} className="hover:bg-elevated/40">
                        <td className="py-2 font-bold text-text">{j.description || j.journey_id}</td>

                        <td className="text-emerald">{j.availability_pct}%</td>
                        <td className="text-muted">{j.slo_availability_target || '—'}%</td>
                        <td className="text-text">{j.p95_latency_ms ? `${Math.round(j.p95_latency_ms)} ms` : '—'}</td>
                        <td className="text-muted">{j.slo_p95_target_ms ? `${j.slo_p95_target_ms} ms` : '—'}</td>
                        <td className="text-muted">{j.error_budget_consumed_pct ?? 0}%</td>
                        <td>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              j.status === 'OK' ? 'bg-emerald/15 text-emerald' : 'bg-rose/20 text-rose'
                            }`}
                          >
                            {j.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ─────────── TAB 3: AI & TELEMETRY ─────────── */}
        {activeTab === 'telemetry' && (
          <div className="space-y-4 max-w-6xl mx-auto">
            {/* Failure Pattern & Recommendations */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                Engineering Diagnoses & Operational Recommendations
              </h3>
              <div className="space-y-2">
                {(telem.recommendations || []).map((rec, i) => (
                  <div
                    key={i}
                    className="p-3 rounded-lg border border-border bg-elevated flex items-start gap-3"
                  >
                    <span className="text-base">💡</span>
                    <p className="text-xs font-mono text-text leading-relaxed">{rec}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Event Breakdown */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 rounded-xl border border-border bg-panel space-y-2">
                <h4 className="text-xs font-bold font-ui text-muted uppercase">Event Breakdown</h4>
                <div className="space-y-1 text-xs font-mono">
                  {Object.entries(telem.event_breakdown || {}).map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1 border-b border-border/30">
                      <span className="text-muted">{k}</span>
                      <span className="font-bold text-text">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="p-4 rounded-xl border border-border bg-panel space-y-2">
                <h4 className="text-xs font-bold font-ui text-muted uppercase">Top Failure Patterns</h4>
                <div className="space-y-1 text-xs font-mono">
                  {Object.entries(telem.top_error_patterns || {}).map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1 border-b border-border/30">
                      <span className="text-muted truncate max-w-xs">{k}</span>
                      <span className="font-bold text-rose">{v}</span>
                    </div>
                  ))}
                  {Object.keys(telem.top_error_patterns || {}).length === 0 && (
                    <p className="text-muted text-xs">No recurring failure patterns detected.</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─────────── TAB 4: STORAGE & MAINTENANCE TOOLS ─────────── */}
        {activeTab === 'maintenance' && (
          <div className="space-y-4 max-w-6xl mx-auto">
            {/* Storage Footprint Breakdown */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                  Disk Storage Allocations
                </h3>
                <span className="text-xs font-mono text-text font-bold">
                  Total Allocated: {storage.total_size_mb || 0} MB
                </span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Business Orders & Fills</span>
                  <span className="text-sm font-mono font-bold text-text">{storage.tiers?.business?.size_mb || 0} MB</span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Market Data Ticks</span>
                  <span className="text-sm font-mono font-bold text-text">{storage.tiers?.market_data?.size_mb || 0} MB</span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Analytical Cache</span>
                  <span className="text-sm font-mono font-bold text-text">{storage.tiers?.analytics?.size_mb || 0} MB</span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Telemetry Logs</span>
                  <span className="text-sm font-mono font-bold text-text">{storage.tiers?.telemetry?.size_mb || 0} MB</span>
                </div>
              </div>
            </div>

            {/* 1-Click Operations */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                1-Click Maintenance Operations
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="p-3 rounded-xl border border-border bg-elevated flex flex-col justify-between space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-text">Purge Ephemeral Cache</h4>
                    <p className="text-[11px] font-mono text-muted mt-1 leading-normal">
                      Removes raw tick buffers &gt;7 days old. Preserves all order/audit records.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handlePurgeStorage(false)}
                    disabled={actionInProgress === 'purge_storage'}
                    className="w-full py-1.5 px-3 rounded-lg text-xs font-mono font-bold bg-panel hover:bg-highlight border border-border text-text transition-colors cursor-pointer"
                  >
                    {actionInProgress === 'purge_storage' ? 'Purging…' : '🧹 Run Purge'}
                  </button>
                </div>

                <div className="p-3 rounded-xl border border-border bg-elevated flex flex-col justify-between space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-text">Vacuum SQLite Databases</h4>
                    <p className="text-[11px] font-mono text-muted mt-1 leading-normal">
                      Checkpoints WAL logs, recovers fragmented pages, and executes VACUUM.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handlePurgeStorage(true)}
                    disabled={actionInProgress === 'purge_storage'}
                    className="w-full py-1.5 px-3 rounded-lg text-xs font-mono font-bold bg-panel hover:bg-highlight border border-border text-text transition-colors cursor-pointer"
                  >
                    {actionInProgress === 'purge_storage' ? 'Vacuuming…' : '🗄️ Purge & Vacuum'}
                  </button>
                </div>

                <div className="p-3 rounded-xl border border-border bg-elevated flex flex-col justify-between space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-text">Sync Post-Market EOD</h4>
                    <p className="text-[11px] font-mono text-muted mt-1 leading-normal">
                      Delta-syncs missing daily bars for NIFTY500 and checkpoints envelope stores.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleTriggerEODSync}
                    disabled={actionInProgress === 'sync_eod'}
                    className="w-full py-1.5 px-3 rounded-lg text-xs font-mono font-bold bg-panel hover:bg-highlight border border-border text-text transition-colors cursor-pointer"
                  >
                    {actionInProgress === 'sync_eod' ? 'Syncing…' : '📊 Sync EOD Bars'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
