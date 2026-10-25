import { useState, useEffect, useCallback, useRef } from 'react'
import { useChatStore, getBaseUrl } from '../../store/chatStore'

/**
 * SystemHealthPill — Institutional proactive health badge in top navigation.
 * Replaces static status dot with prioritized telemetry (P0 Critical, P1 High, P2 Medium, P3 Info)
 * and Fyers Circuit Breaker live countdown state.
 */
export default function SystemHealthPill({ onOpenDrawer, onOpenOpsDeck }) {
  const port = useChatStore((s) => s.port)
  const sidecarError = useChatStore((s) => s.sidecarError)

  const [healthData, setHealthData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [cooldownRemaining, setCooldownRemaining] = useState(0)
  const timerRef = useRef(null)

  const fetchHealth = useCallback(async () => {
    if (!port || sidecarError) return
    try {
      setLoading(true)
      const res = await fetch(`${getBaseUrl(port)}/api/system/health-hub?limit=10&since_boot=true`, {
        signal: AbortSignal.timeout(3000),
      })
      if (res.ok) {
        const data = await res.json()
        setHealthData(data)
        if (data.circuit_breaker?.remaining_cooldown_seconds > 0) {
          setCooldownRemaining(Math.ceil(data.circuit_breaker.remaining_cooldown_seconds))
        } else {
          setCooldownRemaining(0)
        }
      }
    } catch (_) {
      // Degraded or transient network fetch failure
    } finally {
      setLoading(false)
    }
  }, [port, sidecarError])

  // Periodic polling every 10 seconds
  useEffect(() => {
    fetchHealth()
    const interval = setInterval(fetchHealth, 10000)
    return () => clearInterval(interval)
  }, [fetchHealth])

  // Listen to instantaneous SSE events dispatched from App.jsx
  useEffect(() => {
    const handleImmediateUpdate = () => {
      fetchHealth()
    }
    window.addEventListener('system-incident', handleImmediateUpdate)
    window.addEventListener('fyers-circuit-breaker-tripped', handleImmediateUpdate)
    window.addEventListener('fyers-circuit-breaker-recovered', handleImmediateUpdate)
    return () => {
      window.removeEventListener('system-incident', handleImmediateUpdate)
      window.removeEventListener('fyers-circuit-breaker-tripped', handleImmediateUpdate)
      window.removeEventListener('fyers-circuit-breaker-recovered', handleImmediateUpdate)
    }
  }, [fetchHealth])

  // Local 1-second countdown ticker for active circuit breaker cooldown
  useEffect(() => {
    if (cooldownRemaining > 0) {
      timerRef.current = setInterval(() => {
        setCooldownRemaining((prev) => {
          if (prev <= 1) {
            clearInterval(timerRef.current)
            fetchHealth()
            return 0
          }
          return prev - 1
        })
      }, 1000)
    }
    return () => clearInterval(timerRef.current)
  }, [cooldownRemaining, fetchHealth])

  const connected = !!port && !sidecarError
  if (!connected) {
    return (
      <button
        type="button"
        onClick={onOpenDrawer}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer border"
        style={{
          background: 'rgba(255, 79, 123, 0.15)',
          borderColor: 'var(--color-rose)',
          color: 'var(--color-rose)',
        }}
        title="Sidecar Offline — Click for diagnostic options"
      >
        <span className="w-2 h-2 rounded-full animate-ping" style={{ background: 'var(--color-rose)' }} />
        <span>OFFLINE</span>
      </button>
    )
  }

  const p0Count = healthData?.incident_counts?.P0 || 0
  const p1Count = healthData?.incident_counts?.P1 || 0
  const activeP0 = healthData?.active_incident_counts?.P0 ?? (healthData?.overall_status === 'HEALTHY' ? 0 : p0Count)
  const activeP1 = healthData?.active_incident_counts?.P1 ?? (healthData?.overall_status === 'HEALTHY' ? 0 : p1Count)
  const cb = healthData?.circuit_breaker || {}
  const cbState = cb.state || 'CLOSED'
  const isCbTripped = cbState === 'OPEN'
  const isDailyExhausted = !!cb.daily_quota_exhausted
  const overall = healthData?.overall_status || (isCbTripped || activeP0 > 0 ? 'CRITICAL' : activeP1 > 0 ? 'DEGRADED' : 'HEALTHY')

  let badgeColor = 'var(--color-emerald)'
  let badgeBg = 'rgba(0, 214, 143, 0.12)'
  let badgeBorder = 'rgba(0, 214, 143, 0.35)'
  let label = 'NOMINAL'
  let subText = ''

  if (overall === 'CRITICAL' || isCbTripped || activeP0 > 0) {
    badgeColor = 'var(--color-rose)'
    badgeBg = 'rgba(255, 79, 123, 0.18)'
    badgeBorder = 'var(--color-rose)'
    if (isDailyExhausted) {
      label = 'DAILY LIMIT (5K)'
    } else if (isCbTripped) {
      label = cooldownRemaining > 0 ? `BREAKER (${cooldownRemaining}s)` : 'BREAKER OPEN'
    } else {
      label = `CRITICAL (${activeP0})`
    }
  } else if (overall === 'DEGRADED' || activeP1 > 0 || cbState === 'HALF_OPEN') {
    badgeColor = 'var(--color-gold)'
    badgeBg = 'rgba(245, 166, 35, 0.15)'
    badgeBorder = 'var(--color-gold)'
    label = cbState === 'HALF_OPEN' ? 'PROBING' : activeP1 > 0 ? `DEGRADED (${activeP1})` : 'DEGRADED'
  }

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={onOpenDrawer}
        onDoubleClick={onOpenOpsDeck}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer border shadow-sm group hover:brightness-110"
        style={{
          background: badgeBg,
          borderColor: badgeBorder,
          color: badgeColor,
        }}
        title={`OpsDeck Health Status: ${overall}\nP0 Critical: ${p0Count} | P1 High: ${p1Count} | Breaker: ${cbState}\n• Click to open Ops Drawer\n• Double-click for full OpsDeck`}
      >
        <span
          className={`w-2 h-2 rounded-full ${overall !== 'HEALTHY' ? 'animate-pulse' : ''}`}
          style={{
            background: badgeColor,
            boxShadow: `0 0 6px ${badgeColor}`,
          }}
        />
        <span className="tracking-wide">{label}</span>
        {subText && <span className="text-[10px] opacity-80">{subText}</span>}
      </button>

      {/* Quick link button to full OpsDeck */}
      <button
        type="button"
        onClick={onOpenOpsDeck}
        className="hidden xl:flex items-center justify-center w-6 h-6 rounded-lg text-xs transition-colors hover:bg-elevated text-muted hover:text-text cursor-pointer"
        title="Open Full OpsDeck Workspace (^M)"
        aria-label="Open OpsDeck"
      >
        🛠️
      </button>
    </div>
  )
}
