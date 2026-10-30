import { useState, useEffect, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useChatStore, getBaseUrl } from '../../store/chatStore'
import { useToastStore } from '../../hooks/useToast'
import DepthLadderWidget from '../Widgets/DepthLadderWidget'
import MultiSelectDropdown from '../Common/MultiSelectDropdown'

/**
 * Normalizes filter selection state to a Set, handling Set, Array, string, or empty/ALL states.
 */
function isAllOrEmpty(val) {
  if (!val) return true
  if (typeof val === 'string') return val === 'ALL' || val === ''
  if (val instanceof Set) return val.size === 0 || val.has('ALL')
  if (Array.isArray(val)) return val.length === 0 || val.includes('ALL')
  return true
}

function normalizeToSet(val) {
  if (!val) return new Set()
  if (val instanceof Set) return val
  if (Array.isArray(val)) return new Set(val.filter((v) => v !== 'ALL'))
  if (typeof val === 'string') return val === 'ALL' || val === '' ? new Set() : new Set([val])
  return new Set()
}

/**
 * OpsDeckView — Institutional Operations, Maintenance & Monitoring Terminal.
 * Provides complete visibility into system health, Fyers circuit breaker status,
 * WebSocket subscription capacity, priority-segregated incidents (P0–P3),
 * broker connectivity, SLO tracking, and 1-click maintenance tools.
 */
/**
 * Translates raw Level-3 market depth signals into clear, actionable institutional intelligence.
 */
function deriveSentinelIntel(slot) {
  if (slot.sentinel_intel && typeof slot.sentinel_intel === 'object') {
    return slot.sentinel_intel
  }
  const isSpoof = Boolean(slot.spoof_trap_warning)
  const isBidFortress = Boolean(slot.fortress_bid_wall_confirmed)
  const isAskFortress = Boolean(slot.fortress_ask_wall_confirmed)
  const obi = Number(slot.obi_50 || 0)

  if (isSpoof) {
    const isAskSpoof = String(slot.spoof_trap_warning).includes('ASK_SPOOF')
    if (isAskSpoof) {
      return {
        bias: 'BULLISH',
        badge: '🚀 SHORT SQUEEZE (BEAR TRAP)',
        tag: 'ASK SPOOF',
        headline: 'Fake Asks Vanished — Resistance Removed',
        meaning: 'A large resting sell block vanished as spot approached. Bluffing sellers fled, clearing the path upward.',
        decision: 'FAVOR LONGS / CALLS: Overhead ceiling was an illusion. Expect accelerated upside breakout as trapped shorts cover.',
      }
    }
    return {
      bias: 'CAUTION_BEAR',
      badge: '⚠️ BULL TRAP / RUGPULL',
      tag: 'BID SPOOF',
      headline: 'Fake Bids Vanished — Support Pulled',
      meaning: 'A large resting buy wall vanished as spot approached within 0.15%. Deceptive liquidity intended to lure retail buyers.',
      decision: 'DO NOT CHASE LONGS: High risk of sudden downside dump. Wait for verified absorption or look for put entries.',
    }
  }

  if (isBidFortress) {
    return {
      bias: 'BULLISH',
      badge: '🛡️ BULLISH DEMAND FLOOR',
      tag: 'FORTRESS BID',
      headline: 'Institutional Buyer Fortress Holding >15s',
      meaning: 'Massive institutional buy orders holding firmly across multiple levels without cancelling.',
      decision: 'FAVOR CALLS / LONGS: Defended support level. Anchor your Invalidation Stop-Loss just below this floor.',
    }
  }

  if (isAskFortress) {
    return {
      bias: 'BEARISH',
      badge: '🏰 BEARISH SUPPLY CEILING',
      tag: 'FORTRESS ASK',
      headline: 'Institutional Seller Fortress Holding >15s',
      meaning: 'Heavy institutional sell orders capping upside across multiple levels without cancelling.',
      decision: 'FAVOR PUTS / SHORTS: Immovable overhead roadblock. Take profit on longs; do not chase breakout until cleared.',
    }
  }

  if (obi >= 0.25) {
    return {
      bias: 'BULLISH',
      badge: '📈 NET BUY PRESSURE',
      tag: `OBI +${Math.round(obi * 100)}%`,
      headline: `Deep Bid Absorption (+${(obi * 100).toFixed(0)}%)`,
      meaning: 'Buyers command dominant depth across 50 levels. Persistent bid layering indicates institutional accumulation.',
      decision: 'BULLISH ACCUMULATION: Order flow supports upward drift. Favorable backdrop for continuation longs.',
    }
  }

  if (obi <= -0.25) {
    return {
      bias: 'BEARISH',
      badge: '📉 NET SELL PRESSURE',
      tag: `OBI ${Math.round(obi * 100)}%`,
      headline: `Heavy Ask Distribution (${(obi * 100).toFixed(0)}%)`,
      meaning: 'Sellers command dominant depth across 50 levels. Persistent ask stacking indicates institutional distribution.',
      decision: 'BEARISH DISTRIBUTION: Heavy overhead supply. Favorable backdrop for put setups; caution on longs.',
    }
  }

  return {
    bias: 'NEUTRAL',
    badge: '⚖️ BALANCED AUCTION',
    tag: `DENSITY ${slot.density_score || 0}%`,
    headline: 'Symmetric Two-Sided Depth',
    meaning: 'Bids and asks are evenly matched with no predatory resting barriers or fleeing orders.',
    decision: 'TRADE PRICE ACTION: No order book distortion detected. Rely on standard VWAP, Camarilla pivots, and price action.',
  }
}

export default function OpsDeckView({ onOpenOrderTicket }) {
  const port = useChatStore((s) => s.port)
  const addToast = useToastStore((s) => s.addToast)

  const [activeTab, setActiveTab] = useState('incidents')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPriority, setSelectedPriority] = useState(() => new Set())
  const [selectedComponent, setSelectedComponent] = useState(() => new Set())
  const [scopeFilter, setScopeFilter] = useState('ALL')
  const [expandedTracebacks, setExpandedTracebacks] = useState({})
  const [actionInProgress, setActionInProgress] = useState('')
  const [newTbtSymbol, setNewTbtSymbol] = useState('')
  const [tbtFilterRole, setTbtFilterRole] = useState('ALL')
  const [showSentinelGuide, setShowSentinelGuide] = useState(false)
  const [copiedIncKey, setCopiedIncKey] = useState(null)

  // ── L2 Universe Depth Radar State ─────────────────────────────────
  const [radarItems, setRadarItems] = useState([])
  const [radarLoading, setRadarLoading] = useState(false)
  const [radarSegment, setRadarSegment] = useState('ALL')
  const [radarSort, setRadarSort] = useState('OBI_DESC')
  const [radarSearch, setRadarSearch] = useState('')
  const [selectedRadarSymbol, setSelectedRadarSymbol] = useState(null)
  const [radarAutoRefresh, setRadarAutoRefresh] = useState(true)
  const [radarInspectorOpen, setRadarInspectorOpen] = useState(() => {
    try {
      const saved = localStorage.getItem('chanakya_depth_radar_inspector_open')
      return saved !== null ? JSON.parse(saved) : false
    } catch (_) {
      return false
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem('chanakya_depth_radar_inspector_open', JSON.stringify(radarInspectorOpen))
    } catch (_) {
      // Ignore
    }
  }, [radarInspectorOpen])

  // ── Sentinel Hover Intel Portal State (Screen-Adaptive & Zero Scroll Clipping) ──
  const [hoveredSentinel, setHoveredSentinel] = useState(null) // { intel, rect }

  const handleSentinelHover = useCallback((intel, element) => {
    if (!intel || !element) return
    const rect = element.getBoundingClientRect()
    setHoveredSentinel({ intel, rect })
  }, [])

  // Auto-dismiss Sentinel hover portal when scrolling or resizing to prevent misaligned clipping
  useEffect(() => {
    const handleDismiss = () => {
      setHoveredSentinel(null)
    }
    window.addEventListener('scroll', handleDismiss, true)
    window.addEventListener('resize', handleDismiss)
    return () => {
      window.removeEventListener('scroll', handleDismiss, true)
      window.removeEventListener('resize', handleDismiss)
    }
  }, [])

  const fetchDepthRadar = useCallback(async () => {
    if (!port) return
    try {
      setRadarLoading(true)
      const backendSeg =
        radarSegment === 'COMMODITIES'
          ? 'COMMODITIES'
          : radarSegment === 'CURRENCY'
          ? 'CURRENCY'
          : radarSegment === 'INDICES'
          ? 'INDICES'
          : radarSegment === 'STOCKS'
          ? 'STOCKS'
          : radarSegment === 'ALERTS'
          ? 'ALERTS'
          : 'ALL'
      const res = await fetch(`${getBaseUrl(port)}/api/market/depth-radar?segment=${backendSeg}&limit=80&allow_rest=false`, {
        signal: AbortSignal.timeout(9000),
      })
      if (res.ok) {
        const json = await res.json()
        const items = json.data || []
        setRadarItems(items)
        setSelectedRadarSymbol((prev) => prev || (items.length > 0 ? items[0].symbol : null))
      }
    } catch (e) {
      // Degraded
    } finally {
      setRadarLoading(false)
    }
  }, [port, radarSegment])

  useEffect(() => {
    if (activeTab === 'depth_radar') {
      fetchDepthRadar()
      if (radarAutoRefresh) {
        const timer = setInterval(fetchDepthRadar, 5000)
        return () => clearInterval(timer)
      }
    }
  }, [activeTab, fetchDepthRadar, radarAutoRefresh])

  const filteredRadarItems = useMemo(() => {
    let result = [...radarItems]

    // Segment filter
    if (radarSegment === 'INDICES') {
      result = result.filter(
        (it) => it.segment?.includes('INDEX') || ['NIFTY', 'BANKNIFTY', 'SENSEX', 'MIDCPNIFTY'].includes(it.symbol)
      )
    } else if (radarSegment === 'STOCKS') {
      result = result.filter((it) => it.segment?.includes('STOCK'))
    } else if (radarSegment === 'COMMODITIES') {
      result = result.filter(
        (it) =>
          it.segment?.includes('COMMODITY') ||
          it.symbol?.startsWith('MCX:') ||
          ['CRUDEOIL', 'NATURALGAS', 'GOLD', 'SILVER', 'COPPER', 'ZINC', 'ALUMINIUM'].some((c) =>
            it.symbol?.includes(c)
          )
      )
    } else if (radarSegment === 'CURRENCY') {
      result = result.filter(
        (it) =>
          it.segment?.includes('CURRENCY') ||
          it.symbol?.startsWith('CDS:') ||
          ['USDINR', 'EURINR', 'GBPINR', 'JPYINR'].some((c) => it.symbol?.includes(c))
      )
    } else if (radarSegment === 'ALERTS') {
      result = result.filter((it) => it.segment?.includes('RADAR') || it.segment?.includes('ALERT'))
    } else if (radarSegment === 'HIGH_OBI') {
      result = result.filter((it) => Math.abs(Number(it.obi || 0)) >= 0.3)
    } else if (radarSegment === 'WALLS') {
      result = result.filter((it) => Boolean(it.has_resting_wall))
    }

    // Search query filter
    if (radarSearch.trim()) {
      const q = radarSearch.trim().toUpperCase()
      result = result.filter((it) => it.symbol.toUpperCase().includes(q))
    }

    // Sort
    result.sort((a, b) => {
      if (radarSort === 'OBI_DESC') return (Number(b.obi) || 0) - (Number(a.obi) || 0)
      if (radarSort === 'OBI_ASC') return (Number(a.obi) || 0) - (Number(b.obi) || 0)
      if (radarSort === 'MICRO_SKEW_DESC') return (Number(b.micro_skew_bps) || 0) - (Number(a.micro_skew_bps) || 0)
      if (radarSort === 'SPREAD_ASC') return (Number(a.spread_bps) || 0) - (Number(b.spread_bps) || 0)
      if (radarSort === 'NOTIONAL_DESC') {
        const notionalA = (Number(a.bid_notional_cr) || 0) + (Number(a.ask_notional_cr) || 0)
        const notionalB = (Number(b.bid_notional_cr) || 0) + (Number(b.ask_notional_cr) || 0)
        return notionalB - notionalA
      }
      if (radarSort === 'PRICE_DESC') return (Number(b.ltp) || 0) - (Number(a.ltp) || 0)
      return 0
    })

    return result
  }, [radarItems, radarSegment, radarSearch, radarSort])

  // Synchronize active inspector symbol whenever segment changes
  useEffect(() => {
    if (radarSegment !== 'ALL' && filteredRadarItems.length > 0) {
      if (!filteredRadarItems.some((it) => it.symbol === selectedRadarSymbol)) {
        setSelectedRadarSymbol(filteredRadarItems[0].symbol)
      }
    }
  }, [radarSegment])

  const fetchHubData = useCallback(async () => {
    if (!port) return
    try {
      setLoading(true)
      const sinceParam = scopeFilter === 'SESSION' ? '&since_boot=true' : ''
      const res = await fetch(`${getBaseUrl(port)}/api/system/health-hub?limit=150${sinceParam}`, {
        signal: AbortSignal.timeout(10000),
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
  }, [port, scopeFilter])

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

  const handleTriggerFundamentalsSync = async () => {
    try {
      setActionInProgress('sync_fundamentals')
      addToast({
        title: 'Fundamentals Sync Started',
        message: 'Synchronizing balance sheet & forensic audit data in background…',
        type: 'info',
      })
      const res = await fetch(`${getBaseUrl(port)}/api/maintenance/sync-fundamentals?limit=50`, { method: 'POST' })
      if (res.ok) {
        const json = await res.json()
        addToast({
          title: 'Fundamentals Sync Complete',
          message: `Saved ${json.fundamentals_saved || 0} fundamentals and ${json.forensics_saved || 0} forensic audits.`,
          type: 'success',
        })
        fetchHubData()
      } else {
        const err = await res.json().catch(() => ({}))
        addToast({
          title: 'Fundamentals Sync Failed',
          message: err.detail || err.error || 'Server error during fundamentals sync.',
          type: 'error',
        })
      }
    } catch (e) {
      addToast({ title: 'Fundamentals Sync Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const toggleTraceback = (id) => {
    setExpandedTracebacks((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const handleCopyIncident = useCallback((inc, incKey) => {
    try {
      const parts = [
        `[${inc.priority || 'P2'}] ${inc.component || 'SYSTEM'} • ${inc.event_type || 'INCIDENT'} ${inc.incident_id ? `[${inc.incident_id}]` : ''}`.trim(),
        `Time: ${inc.timestamp ? new Date(inc.timestamp).toLocaleString('en-IN') : 'N/A'}`,
        `Error: ${inc.reason || 'Unhandled System Condition'}`,
      ]
      if (inc.action_taken) {
        parts.push(`Remediation: ${inc.action_taken}`)
      }
      if (inc.details?.traceback) {
        parts.push(`\nTraceback:\n${inc.details.traceback}`)
      }
      navigator.clipboard.writeText(parts.join('\n'))
      setCopiedIncKey(incKey)
      setTimeout(() => setCopiedIncKey(null), 2000)
      if (addToast) {
        addToast({ title: 'Copied to Clipboard', message: 'Incident error details copied.', type: 'info' })
      }
    } catch {
      // Ignore clipboard fallback
    }
  }, [addToast])

  const handleCopyTraceback = useCallback((traceback, incKey) => {
    try {
      navigator.clipboard.writeText(traceback || '')
      setCopiedIncKey(`${incKey}-tb`)
      setTimeout(() => setCopiedIncKey(null), 2000)
      if (addToast) {
        addToast({ title: 'Traceback Copied', message: 'Full traceback copied to clipboard.', type: 'info' })
      }
    } catch {}
  }, [addToast])

  // TBT 50-Depth & Rate Gate Actions
  const handleEvictTbtSlot = async (symbol) => {
    try {
      setActionInProgress(`evict_${symbol}`)
      const res = await fetch(`${getBaseUrl(port)}/api/fyers/tbt-evict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, cooldown_seconds: 300 }),
      })
      if (res.ok) {
        addToast({
          title: 'TBT Slot Evicted',
          message: `Evicted ${symbol} from 15-slot TBT depth. 5-min cooldown active.`,
          type: 'success',
        })
        fetchHubData()
      } else {
        const err = await res.json().catch(() => ({}))
        addToast({ title: 'Eviction Failed', message: err.detail || 'Could not evict symbol', type: 'error' })
      }
    } catch (e) {
      addToast({ title: 'Eviction Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleRebalanceTbt = async () => {
    try {
      setActionInProgress('rebalance_tbt')
      const res = await fetch(`${getBaseUrl(port)}/api/fyers/tbt-rebalance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const json = await res.json()
        addToast({
          title: 'TBT Grid Rebalanced',
          message: `Re-evaluated ATM strikes; cleansed ${json.cleansed_scouts_count || 0} stale scouts.`,
          type: 'success',
        })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Rebalance Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleSetTbtFocus = async (focus) => {
    try {
      setActionInProgress('focus_tbt')
      const res = await fetch(`${getBaseUrl(port)}/api/fyers/tbt-focus`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ focus: focus || null }),
      })
      if (res.ok) {
        addToast({
          title: 'TBT Focus Updated',
          message: `Primary TBT depth focus set to ${focus || 'Multi-Index Balanced'}.`,
          type: 'info',
        })
        fetchHubData()
      }
    } catch (e) {
      addToast({ title: 'Focus Update Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleManualTbtSubscribe = async (e) => {
    if (e) e.preventDefault()
    if (!newTbtSymbol.trim()) return
    const sym = newTbtSymbol.trim().toUpperCase()
    try {
      setActionInProgress('sub_tbt')
      const res = await fetch(`${getBaseUrl(port)}/api/fyers/tbt-subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: [sym] }),
      })
      if (res.ok) {
        addToast({
          title: 'Symbol Subscribed',
          message: `Registered ${sym} to TBT 50-depth stream.`,
          type: 'success',
        })
        setNewTbtSymbol('')
        fetchHubData()
      } else {
        const err = await res.json().catch(() => ({}))
        addToast({ title: 'Subscribe Failed', message: err.detail || 'Could not subscribe symbol', type: 'error' })
      }
    } catch (e) {
      addToast({ title: 'Subscribe Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  const handleClearTbtCooldowns = async (symbol = null) => {
    try {
      setActionInProgress('clear_tbt_cooldowns')
      const res = await fetch(`${getBaseUrl(port)}/api/fyers/tbt-clear-cooldowns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(symbol ? { symbol } : {}),
      })
      if (res.ok) {
        addToast({
          title: 'Cooldowns Cleared',
          message: symbol ? `Cleared cooldown for ${symbol}` : 'Cleared all active eviction cooldowns.',
          type: 'success',
        })
        fetchHubData()
      } else {
        const err = await res.json().catch(() => ({}))
        addToast({ title: 'Clear Failed', message: err.detail || 'Could not clear cooldowns', type: 'error' })
      }
    } catch (e) {
      addToast({ title: 'Clear Failed', message: String(e), type: 'error' })
    } finally {
      setActionInProgress('')
    }
  }

  // Dynamic options for incident components with occurrence counts
  const componentOptions = useMemo(() => {
    const list = data?.incidents || []
    const map = new Map()
    for (const inc of list) {
      const comp = (inc.component || 'GENERAL').toUpperCase()
      map.set(comp, (map.get(comp) || 0) + 1)
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([comp, count]) => ({
        value: comp,
        label: comp,
        count,
      }))
  }, [data?.incidents])

  // Filtered incidents
  const filteredIncidents = useMemo(() => {
    const list = data?.incidents || []
    return list.filter((inc) => {
      // 1. Priority Multi-Filter
      if (!isAllOrEmpty(selectedPriority)) {
        const pSet = normalizeToSet(selectedPriority)
        if (!pSet.has(inc.priority)) return false
      }

      // 2. Component Multi-Filter
      if (!isAllOrEmpty(selectedComponent)) {
        const cSet = normalizeToSet(selectedComponent)
        const comp = (inc.component || 'GENERAL').toUpperCase()
        const matches = Array.from(cSet).some((target) => comp.includes(target))
        if (!matches) return false
      }

      // 3. Search Query Filter
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

  const overall = data?.overall_status || (loading ? 'SYNCING…' : 'NOMINAL')
  const cb = data?.circuit_breaker || {}
  const rg = data?.rate_gate || {}
  const tbt = data?.tbt || {}
  const ws = data?.websocket || {}
  const counts = useMemo(() => {
    const list = data?.incidents || []
    const derived = { P0: 0, P1: 0, P2: 0, P3: 0 }
    for (const inc of list) {
      const p = inc.priority || 'P2'
      if (derived[p] !== undefined) derived[p]++
    }
    return derived
  }, [data?.incidents])
  const brokers = data?.brokers || {}
  const slo = data?.slo_report || {}
  const providerHealth = data?.provider_health || {}
  const telem = data?.telemetry_summary || {}
  const memory = data?.memory || {}
  const storage = data?.storage || {}

  const overallColor =
    overall === 'HEALTHY' || overall === 'NOMINAL'
      ? 'var(--color-emerald)'
      : overall === 'DEGRADED' || overall === 'SYNCING…'
        ? 'var(--color-gold)'
        : 'var(--color-rose)'

  return (
    <div className="flex flex-col h-full bg-surface overflow-hidden font-ui">
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
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 p-3 bg-panel/40 border-b border-border/70 flex-shrink-0">
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

        {/* Card 2: Fyers REST Rate Governor */}
        <div
          className="p-3 rounded-xl border flex flex-col justify-between"
          style={{
            background: rg.status === 'EXHAUSTED' ? 'rgba(255, 79, 123, 0.08)' : 'var(--color-elevated)',
            borderColor: rg.status === 'EXHAUSTED' ? 'var(--color-rose)' : rg.status === 'WARNING' ? 'var(--color-gold)' : 'var(--color-border)',
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider">
              REST Rate Governor
            </span>
            <span
              className="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold"
              style={{
                background: rg.status === 'HEALTHY' ? 'rgba(0,214,143,0.15)' : rg.status === 'WARNING' ? 'rgba(245,166,35,0.15)' : 'rgba(255,79,123,0.2)',
                color: rg.status === 'HEALTHY' ? 'var(--color-emerald)' : rg.status === 'WARNING' ? 'var(--color-gold)' : 'var(--color-rose)',
              }}
            >
              {rg.plan || 'PRIME'} • {rg.status || 'HEALTHY'}
            </span>
          </div>

          <div className="my-1.5 space-y-1">
            <div className="flex items-center justify-between text-xs font-mono font-bold">
              <span className="text-text">
                {rg.requests_last_min ?? 0} / {Math.round(rg.max_per_min || 500)} req/min
              </span>
              <span className={(rg.utilization_pct || 0) > 80 ? 'text-rose' : 'text-muted'}>
                {rg.utilization_pct || 0}%
              </span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-surface overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(rg.utilization_pct || 0, 100)}%`,
                  background: (rg.utilization_pct || 0) > 85 ? 'var(--color-rose)' : (rg.utilization_pct || 0) > 50 ? 'var(--color-gold)' : 'var(--color-emerald)',
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] font-mono text-muted">
              <span>Now: {rg.requests_last_sec || 0}/{Math.round(rg.max_per_sec || 10)} req/s</span>
              <span>Daily: {rg.daily_requests || 0} reqs</span>
            </div>
          </div>

          <div className="text-[10px] font-mono text-muted flex items-center justify-between pt-0.5">
            <span>Peak: {rg.peak_minute_recorded || 0}/min</span>
            <span>Left: {rg.daily_budget_remaining != null ? Math.round(rg.daily_budget_remaining / 1000) + 'k' : '—'}</span>
          </div>
        </div>

        {/* Card 3: WebSocket Streaming Capacity */}
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

        {/* Card 4: Level-3 50-Depth TBT Governor */}
        <div
          onClick={() => setActiveTab('tbt')}
          className="p-3 rounded-xl border flex flex-col justify-between cursor-pointer hover:border-gold/60 transition-colors"
          style={{ background: 'var(--color-elevated)', borderColor: activeTab === 'tbt' ? 'var(--color-gold)' : 'var(--color-border)' }}
          title="Click to inspect 15-slot L3 order book depth & manage evictions"
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider flex items-center gap-1">
              <span>⚡</span> 50-Depth TBT
            </span>
            <span
              className="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold"
              style={{
                background: (tbt.active_total || 0) >= 15 ? 'rgba(255,79,123,0.2)' : 'rgba(0,214,143,0.15)',
                color: (tbt.active_total || 0) >= 15 ? 'var(--color-rose)' : 'var(--color-emerald)',
              }}
            >
              {tbt.active_total || 0} / 15 SLOTS
            </span>
          </div>

          <div className="my-1.5 space-y-1">
            <div className="w-full h-1.5 rounded-full bg-surface overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(((tbt.active_total || 0) / 15) * 100, 100)}%`,
                  background: (tbt.active_total || 0) >= 15 ? 'var(--color-rose)' : 'var(--color-gold)',
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] font-mono text-muted">
              <span>{tbt.free_slots ?? (15 - (tbt.active_total || 0))} slots free</span>
              <span className="text-gold font-bold">{tbt.primary_focus ? `Focus: ${tbt.primary_focus}` : 'Balanced'}</span>
            </div>
          </div>

          <div className="text-[10px] font-mono text-muted flex items-center justify-between">
            <span>In-Flight: {(tbt.in_flight || []).length} • Core: {(tbt.core_grid || []).length}</span>
            <span className="text-muted hover:text-text">Manage →</span>
          </div>
        </div>

        {/* Card 5: Prioritized Incidents & Host Vitals */}
        <div
          className="p-3 rounded-xl border flex flex-col justify-between"
          style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-bold text-muted uppercase tracking-wider">
              Incidents & Vitals
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

          <div className="grid grid-cols-4 gap-1.5 my-1.5">
            <div className="text-center p-0.5 rounded bg-surface border border-rose/30">
              <span className="text-[10px] font-mono text-rose block font-bold">P0</span>
              <span className="text-xs font-mono font-black text-rose">{counts.P0 || 0}</span>
            </div>
            <div className="text-center p-0.5 rounded bg-surface border border-gold/30">
              <span className="text-[10px] font-mono text-gold block font-bold">P1</span>
              <span className="text-xs font-mono font-black text-gold">{counts.P1 || 0}</span>
            </div>
            <div className="text-center p-0.5 rounded bg-surface border border-sapphire/30">
              <span className="text-[10px] font-mono text-sapphire block font-bold">P2</span>
              <span className="text-xs font-mono font-black text-sapphire">{counts.P2 || 0}</span>
            </div>
            <div className="text-center p-0.5 rounded bg-surface border border-border">
              <span className="text-[10px] font-mono text-muted block font-bold">P3</span>
              <span className="text-xs font-mono font-black text-muted">{counts.P3 || 0}</span>
            </div>
          </div>

          <div className="text-[10px] font-mono text-muted flex justify-between">
            <span>RAM: {Math.round(memory.used_ram_pct ?? memory.system_ram_pct ?? 0)}%</span>
            <span>SSD: {(storage.free_ssd_gb ?? storage.ssd_free_gb ?? 0) ? `${Math.round((storage.free_ssd_gb ?? storage.ssd_free_gb) * 10) / 10} GB` : '—'}</span>
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
            data-testid="tab-tbt"
            onClick={() => setActiveTab('tbt')}
            className={`px-3 py-2 text-xs font-mono font-bold border-b-2 transition-all cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'tbt'
                ? 'border-gold text-gold bg-elevated/60'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            <span>⚡</span>
            <span>50-Depth TBT Slots</span>
            <span
              className="px-1.5 py-0.2 rounded text-[10px] font-bold"
              style={{
                background: (tbt.active_total || 0) >= 15 ? 'rgba(255,79,123,0.2)' : 'rgba(0,214,143,0.15)',
                color: (tbt.active_total || 0) >= 15 ? 'var(--color-rose)' : 'var(--color-emerald)',
              }}
            >
              {tbt.active_total || 0}/15
            </span>
          </button>
          <button
            type="button"
            data-testid="tab-depth-radar"
            onClick={() => setActiveTab('depth_radar')}
            className={`px-3 py-2 text-xs font-mono font-bold border-b-2 transition-all cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'depth_radar'
                ? 'border-gold text-gold bg-elevated/60'
                : 'border-transparent text-muted hover:text-text'
            }`}
          >
            <span>🌊</span>
            <span>Universe Depth Radar</span>
            <span
              className="px-1.5 py-0.2 rounded text-[10px] font-bold"
              style={{
                background: 'rgba(59,130,246,0.15)',
                color: 'var(--color-sapphire)',
              }}
            >
              L2 / 5-Depth
            </span>
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
                  const pSet = normalizeToSet(selectedPriority)
                  const isActive = p === 'ALL' ? isAllOrEmpty(selectedPriority) : pSet.has(p)
                  const color = p === 'P0' ? 'var(--color-rose)' : p === 'P1' ? 'var(--color-gold)' : p === 'P2' ? 'var(--color-sapphire)' : 'var(--color-muted)'
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => {
                        if (p === 'ALL') {
                          setSelectedPriority(new Set())
                        } else {
                          const next = new Set(pSet)
                          if (next.has(p)) {
                            next.delete(p)
                          } else {
                            next.add(p)
                          }
                          setSelectedPriority(next)
                        }
                      }}
                      className={`px-2 py-0.5 rounded text-[11px] font-mono font-bold cursor-pointer transition-all border ${
                        isActive ? 'bg-elevated' : 'border-transparent text-muted hover:text-text'
                      }`}
                      style={{
                        borderColor: isActive ? color : 'transparent',
                        color: isActive ? color : undefined,
                      }}
                      title={p === 'ALL' ? 'Reset to All Priorities' : `Toggle ${p} filter (Multi-select enabled)`}
                    >
                      {p === 'ALL' ? 'All Priorities' : `${p} (${counts[p] || 0})`}
                    </button>
                  )
                })}

                {/* Component MultiSelectDropdown */}
                <div className="h-3 w-px bg-border mx-1" />
                <MultiSelectDropdown
                  title="Component"
                  allLabel="All Components"
                  options={componentOptions}
                  selected={selectedComponent}
                  onChange={setSelectedComponent}
                  colorTheme="gold"
                  className="w-auto"
                />

                <div className="h-3 w-px bg-border mx-1" />
                <span className="text-[11px] font-mono text-muted mr-1">Scope:</span>
                <button
                  type="button"
                  onClick={() => setScopeFilter('ALL')}
                  className={`px-2 py-0.5 rounded text-[11px] font-mono cursor-pointer transition-all border ${
                    scopeFilter === 'ALL'
                      ? 'bg-elevated border-gold text-gold font-bold'
                      : 'border-transparent text-muted hover:text-text'
                  }`}
                >
                  All Logs
                </button>
                <button
                  type="button"
                  onClick={() => setScopeFilter('SESSION')}
                  className={`px-2 py-0.5 rounded text-[11px] font-mono cursor-pointer transition-all border ${
                    scopeFilter === 'SESSION'
                      ? 'bg-elevated border-emerald text-emerald font-bold'
                      : 'border-transparent text-muted hover:text-text'
                  }`}
                >
                  Current Session
                </button>

                {/* Reset Filters */}
                {(!isAllOrEmpty(selectedPriority) || !isAllOrEmpty(selectedComponent) || searchQuery || scopeFilter !== 'ALL') && (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedPriority(new Set())
                      setSelectedComponent(new Set())
                      setSearchQuery('')
                      setScopeFilter('ALL')
                    }}
                    className="px-2 py-0.5 rounded text-[11px] font-mono font-bold text-gold hover:text-amber-200 border border-gold/30 hover:bg-gold/10 transition-colors cursor-pointer ml-1"
                    title="Reset priority, component, and search filters"
                  >
                    ✕ Reset
                  </button>
                )}
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
              <div className="space-y-2.5 select-text">
                {filteredIncidents.map((inc, idx) => {
                  const isP0 = inc.priority === 'P0'
                  const isP1 = inc.priority === 'P1'
                  const pColor = isP0 ? 'var(--color-rose)' : isP1 ? 'var(--color-gold)' : 'var(--color-sapphire)'
                  const incKey = inc.incident_id || idx
                  const isExpanded = !!expandedTracebacks[incKey]
                  const isCopied = copiedIncKey === incKey

                  return (
                    <div
                      key={incKey}
                      className="p-3.5 rounded-xl border text-xs font-mono transition-all space-y-2 select-text"
                      style={{
                        background: isP0 ? 'rgba(255, 79, 123, 0.05)' : 'var(--color-panel)',
                        borderColor: isP0 ? 'rgba(255, 79, 123, 0.35)' : 'var(--color-border)',
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span
                            className="px-2 py-0.5 rounded font-black text-[10px] tracking-wider uppercase select-none"
                            style={{
                              background: isP0 ? 'rgba(255, 79, 123, 0.2)' : isP1 ? 'rgba(245, 166, 35, 0.2)' : 'rgba(77, 155, 255, 0.15)',
                              color: pColor,
                            }}
                          >
                            {inc.priority || 'P2'}
                          </span>
                          <span className="text-text font-bold select-text cursor-text">
                            {inc.component || 'SYSTEM'}
                          </span>
                          <span className="text-muted/60 select-none">•</span>
                          <span className="text-muted text-[10px] select-text">
                            {inc.event_type || 'INCIDENT'}
                          </span>
                          {inc.incident_id && (
                            <span className="text-muted/70 text-[10px] font-mono select-text cursor-text bg-elevated px-1.5 py-0.5 rounded border border-border/60">
                              [{inc.incident_id}]
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-2 flex-shrink-0">
                          <span className="text-muted text-[11px] select-text">
                            {inc.timestamp ? new Date(inc.timestamp).toLocaleTimeString('en-IN') : 'Just now'}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleCopyIncident(inc, incKey)}
                            className="px-2 py-0.5 rounded text-[10px] font-mono border transition-all cursor-pointer flex items-center gap-1 select-none"
                            style={{
                              background: isCopied ? 'rgba(0,214,143,0.15)' : 'var(--color-elevated)',
                              borderColor: isCopied ? 'var(--color-emerald)' : 'var(--color-border)',
                              color: isCopied ? 'var(--color-emerald)' : 'var(--color-muted)',
                            }}
                            title="Copy incident error summary and details"
                          >
                            {isCopied ? '✓ Copied' : '📋 Copy Error'}
                          </button>
                        </div>
                      </div>

                      <div className="text-sm font-bold text-text leading-snug select-text cursor-text">
                        {inc.reason || 'Unhandled System Condition'}
                      </div>

                      {inc.action_taken && (
                        <div className="text-xs text-muted flex items-start gap-1 select-text cursor-text">
                          <span className="text-muted/60 font-semibold select-none">Remediation / Action Taken:</span>
                          <span className="text-text select-text">{inc.action_taken}</span>
                        </div>
                      )}

                      {/* Expandable Traceback */}
                      {inc.details?.traceback && (
                        <div className="pt-1">
                          <div className="flex items-center justify-between">
                            <button
                              type="button"
                              onClick={() => toggleTraceback(incKey)}
                              className="text-xs text-sapphire hover:underline cursor-pointer flex items-center gap-1 select-none"
                            >
                              <span>{isExpanded ? '▲ Hide Full Traceback' : '▼ Inspect Full Traceback & Context'}</span>
                            </button>
                            {isExpanded && (
                              <button
                                type="button"
                                onClick={() => handleCopyTraceback(inc.details.traceback, incKey)}
                                className="text-[10px] text-muted hover:text-text cursor-pointer select-none flex items-center gap-1 font-mono"
                              >
                                {copiedIncKey === `${incKey}-tb` ? '✓ Traceback Copied' : '📋 Copy Traceback'}
                              </button>
                            )}
                          </div>
                          {isExpanded && (
                            <div className="mt-2 p-3 rounded-lg bg-black/50 border border-border/80 text-[11px] font-mono text-muted overflow-x-auto max-h-60 no-scrollbar space-y-2 select-text">
                              <pre className="text-rose/90 select-text cursor-text font-mono whitespace-pre-wrap">{inc.details.traceback}</pre>
                              {inc.details?.system_vitals && (
                                <div className="pt-2 border-t border-border/40 text-[10px] text-muted flex gap-4 select-text cursor-text">
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
            {/* Data Feeds & Provider Health */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                  Data Providers & Freshness Health
                </h3>
                <span
                  className="px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase border"
                  style={{
                    background:
                      providerHealth.overall_health === 'HEALTHY'
                        ? 'rgba(0,214,143,0.12)'
                        : providerHealth.overall_health === 'DEGRADED'
                        ? 'rgba(245,166,35,0.15)'
                        : 'rgba(255,79,123,0.2)',
                    borderColor:
                      providerHealth.overall_health === 'HEALTHY'
                        ? 'var(--color-emerald)'
                        : providerHealth.overall_health === 'DEGRADED'
                        ? 'var(--color-gold)'
                        : 'var(--color-rose)',
                    color:
                      providerHealth.overall_health === 'HEALTHY'
                        ? 'var(--color-emerald)'
                        : providerHealth.overall_health === 'DEGRADED'
                        ? 'var(--color-gold)'
                        : 'var(--color-rose)',
                  }}
                >
                  ● {providerHealth.overall_health || 'HEALTHY'}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {Object.keys(providerHealth.providers || {}).length === 0 ? (
                  <div className="col-span-3 p-4 rounded-xl border border-border bg-elevated/40 text-center text-xs font-mono text-muted">
                    No active external provider calls recorded yet in current session. Primary broker initialized.
                  </div>
                ) : (
                  Object.entries(providerHealth.providers).map(([pName, pRec]) => {
                    const isHealthy = pRec.health === 'HEALTHY'
                    const isDegraded = pRec.health === 'DEGRADED'
                    const statusColor = isHealthy
                      ? 'var(--color-emerald)'
                      : isDegraded
                      ? 'var(--color-gold)'
                      : 'var(--color-rose)'
                    const statusBg = isHealthy
                      ? 'rgba(0,214,143,0.15)'
                      : isDegraded
                      ? 'rgba(245,166,35,0.15)'
                      : 'rgba(255,79,123,0.2)'
                    return (
                      <div
                        key={pName}
                        className="p-3 rounded-xl border border-border bg-elevated flex flex-col justify-between space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold font-mono uppercase text-text">{pName}</span>
                          <span
                            className="px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase"
                            style={{ background: statusBg, color: statusColor }}
                          >
                            {pRec.health || 'HEALTHY'}
                          </span>
                        </div>
                        <div className="text-[11px] font-mono space-y-1 text-muted">
                          <div className="flex justify-between">
                            <span>Requests:</span>
                            <span className="text-text font-bold">{pRec.total_requests || 0}</span>
                          </div>
                          <div className="flex justify-between">
                            <span>Freshness Age:</span>
                            <span className="text-text">
                              {pRec.age_seconds !== null && pRec.age_seconds !== undefined
                                ? `${Math.round(pRec.age_seconds)}s ago`
                                : 'Active'}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span>Errors / Stale:</span>
                            <span
                              style={{
                                color: (pRec.error_count || 0) > 0 ? 'var(--color-rose)' : undefined,
                              }}
                            >
                              {pRec.error_count || 0} errors • {pRec.stale_count || 0} stale
                            </span>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>

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
                    {Object.keys(slo.journeys || {}).length === 0 ? (
                      <tr>
                        <td colSpan="7" className="py-6 text-center text-muted font-mono">
                          No journey latency measurements recorded in current session. All systems nominal.
                        </td>
                      </tr>
                    ) : (
                      Object.values(slo.journeys).map((j, idx) => (
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
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ─────────── TAB 2.5: 50-DEPTH TBT SLOTS GOVERNOR ─────────── */}
        {activeTab === 'tbt' && (() => {
          const isTbtStandby = tbt.session_state === 'STANDBY_EOD' || ['COMMODITY_CDS', 'OFF_MARKET'].includes(tbt.current_session)
          return (
          <div className="space-y-4 max-w-6xl mx-auto">
            {/* Header Control Strip */}
            <div className="p-4 rounded-xl border border-border bg-panel flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold font-ui uppercase tracking-wider text-text flex items-center gap-1.5">
                    <span>⚡</span> Level-3 50-Depth TBT Governor
                  </h3>
                  <span
                    className="px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase border"
                    style={{
                      background: (tbt.active_total || 0) >= 15 ? 'rgba(255,79,123,0.15)' : 'rgba(0,214,143,0.12)',
                      borderColor: (tbt.active_total || 0) >= 15 ? 'var(--color-rose)' : 'var(--color-emerald)',
                      color: (tbt.active_total || 0) >= 15 ? 'var(--color-rose)' : 'var(--color-emerald)',
                    }}
                  >
                    ● {tbt.active_total || 0} / 15 SLOTS ALLOCATED
                  </span>
                  <span className="px-2 py-0.5 rounded font-mono text-[10px] bg-elevated border border-border text-muted">
                    Session: {tbt.current_session || 'EQUITY_NFO'}
                  </span>
                  {isTbtStandby && (
                    <span className="px-2 py-0.5 rounded font-mono text-[10px] bg-gold/15 border border-gold/40 text-gold font-bold">
                      🌙 STANDBY (EOD)
                    </span>
                  )}
                </div>
                <p className="text-xs font-mono text-muted mt-0.5">
                  Fyers physical 15-slot DOM cap • Real-time 50-level OBI • Resting Fortress Wall & Spoof Trap Sentinel
                </p>
              </div>

              {/* Action Controls & Primary Focus Selector */}
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-1.5 bg-elevated border border-border rounded-lg px-2.5 py-1">
                  <span className="text-[10px] font-mono font-bold text-muted uppercase">Focus:</span>
                  <select
                    value={tbt.primary_focus || ''}
                    onChange={(e) => handleSetTbtFocus(e.target.value)}
                    disabled={actionInProgress === 'focus_tbt' || isTbtStandby}
                    className="bg-transparent text-xs font-mono font-bold text-text outline-none cursor-pointer disabled:opacity-50"
                  >
                    <option value="" className="bg-panel text-text">Multi-Index Balanced</option>
                    <option value="NIFTY" className="bg-panel text-text">NIFTY (ATM ± 2 Wings)</option>
                    <option value="BANKNIFTY" className="bg-panel text-text">BANKNIFTY</option>
                    <option value="SENSEX" className="bg-panel text-text">SENSEX</option>
                    <option value="MIDCPNIFTY" className="bg-panel text-text">MIDCPNIFTY</option>
                  </select>
                </div>

                <button
                  type="button"
                  onClick={() => setShowSentinelGuide(!showSentinelGuide)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold border transition-all cursor-pointer ${
                    showSentinelGuide
                      ? 'bg-amber/20 border-amber text-amber shadow-xs'
                      : 'bg-elevated hover:bg-highlight border-border text-text'
                  }`}
                  title="Microstructure Decision Guide: How to interpret Fortress Walls, Spoofs, and OBI"
                >
                  <span>💡</span>
                  <span>{showSentinelGuide ? 'Hide Decision Guide' : 'Sentinel Decision Guide'}</span>
                </button>

                <button
                  type="button"
                  onClick={handleRebalanceTbt}
                  disabled={actionInProgress === 'rebalance_tbt' || isTbtStandby}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-elevated hover:bg-highlight border border-border text-text transition-all cursor-pointer disabled:opacity-50"
                  title="Recalculate ATM strikes against spot drift and prune expired scouts"
                >
                  <span>🔄</span>
                  <span>{actionInProgress === 'rebalance_tbt' ? 'Rebalancing…' : 'Force Rebalance'}</span>
                </button>
              </div>
            </div>

            {/* EOD Standby Banner (Institutional Notice during Evening Session) */}
            {isTbtStandby && (
              <div className="p-3.5 rounded-xl border border-gold/40 bg-gold/10 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs font-mono">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">🌙</span>
                  <div>
                    <div className="font-bold text-gold text-xs uppercase tracking-wide flex items-center gap-2">
                      <span>Versova L3 TBT Standby Mode (EOD)</span>
                      <span className="px-1.5 py-0.2 rounded text-[11px] bg-gold/20 text-gold border border-gold/30">
                        NSE CLOSED 15:30 IST
                      </span>
                    </div>
                    <p className="text-muted text-[11px] mt-0.5">
                      {tbt.session_note || 'NSE Equity & F&O closed at 15:30 IST. Versova TBT socket is in standby mode. Active evening trading is live on MCX Commodities via L2 Depth Radar.'}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setActiveTab('depth_radar')
                    setRadarSegment('COMMODITIES')
                  }}
                  className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-sapphire/20 hover:bg-sapphire/30 text-sapphire border border-sapphire/40 cursor-pointer whitespace-nowrap transition-all flex items-center gap-1.5 shrink-0"
                >
                  <span>🌊</span> Switch to Live MCX Depth Radar →
                </button>
              </div>
            )}

            {/* Quota & Allocation Summary Ribbon */}
            <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-muted block uppercase font-bold">Total Subscribed</span>
                <span className="text-base font-mono font-black text-text">{tbt.active_total || 0} / 15</span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-sapphire block uppercase font-bold">In-Flight Guardian</span>
                <span className="text-base font-mono font-black text-sapphire">{(tbt.in_flight || []).length} / 4</span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-purple block uppercase font-bold">Core Benchmark</span>
                <span className="text-base font-mono font-black text-purple">{(tbt.core_grid || []).length} / 6</span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-gold block uppercase font-bold">Today's Expiry</span>
                <span className="text-base font-mono font-black text-gold">{(tbt.todays_expiry || []).length} / 3</span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-emerald block uppercase font-bold">Dynamic Scouts</span>
                <span className="text-base font-mono font-black text-emerald">{(tbt.scout || []).length}</span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-muted block uppercase font-bold">Free Slots</span>
                <span className="text-base font-mono font-black text-emerald">{tbt.free_slots ?? (15 - (tbt.active_total || 0))}</span>
              </div>
            </div>

            {/* Quick Subscribe Bar */}
            <form onSubmit={handleManualTbtSubscribe} className="p-3 rounded-xl border border-border bg-panel flex items-center gap-2">
              <span className="text-xs font-mono text-muted font-bold whitespace-nowrap">
                ⚡ Quick Allocate Slot:
              </span>
              <input
                type="text"
                placeholder={isTbtStandby ? "NSE closed (15:30 IST) • Versova TBT in EOD standby • Trade MCX via L2 Radar" : "e.g. NSE:NIFTY26OCT23200CE or NSE:RELIANCE-EQ"}
                value={newTbtSymbol}
                onChange={(e) => setNewTbtSymbol(e.target.value)}
                disabled={isTbtStandby}
                className="flex-1 px-3 py-1.5 rounded-lg text-xs font-mono bg-surface border border-border text-text placeholder-muted/60 outline-none focus:border-gold disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={isTbtStandby || !newTbtSymbol.trim() || actionInProgress === 'sub_tbt'}
                className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-elevated hover:bg-highlight border border-border text-text transition-all cursor-pointer whitespace-nowrap disabled:opacity-50"
              >
                {actionInProgress === 'sub_tbt' ? 'Subscribing…' : '+ Allocate Slot'}
              </button>
            </form>

            {/* Active Cooldowns Banner (if any) */}
            {Object.keys(tbt.cooldowns || {}).length > 0 && (
              <div className="p-3 rounded-xl border border-gold/30 bg-gold/5 flex items-center justify-between gap-3 text-xs font-mono">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-gold font-bold">⏳ Active Eviction Cooldowns:</span>
                  {Object.entries(tbt.cooldowns).map(([sym, remSec]) => (
                    <span key={sym} className="px-2 py-0.5 rounded bg-surface border border-border text-muted inline-flex items-center gap-1.5">
                      <span>{sym} ({Math.ceil(remSec)}s left)</span>
                      <button
                        type="button"
                        onClick={() => handleClearTbtCooldowns(sym)}
                        className="text-[10px] text-muted hover:text-rose cursor-pointer ml-0.5 font-bold"
                        title={`Clear cooldown for ${sym}`}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-2 whitespace-nowrap">
                  <span className="text-[10px] text-muted hidden lg:inline">
                    Automated loops will not re-subscribe these symbols until cooldown expires.
                  </span>
                  <button
                    type="button"
                    onClick={() => handleClearTbtCooldowns(null)}
                    disabled={actionInProgress === 'clear_tbt_cooldowns'}
                    className="px-2 py-1 rounded bg-elevated hover:bg-highlight border border-border text-[11px] font-bold text-text cursor-pointer transition-all"
                  >
                    {actionInProgress === 'clear_tbt_cooldowns' ? 'Clearing…' : '⚡ Clear All'}
                  </button>
                </div>
              </div>
            )}

            {/* Sentinel Decision Blueprint Guide */}
            {showSentinelGuide && (
              <div className="p-4 rounded-xl border border-amber/30 bg-amber/5 space-y-3 font-mono text-xs animate-in fade-in duration-200">
                <div className="flex items-center justify-between border-b border-amber/20 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-base">💡</span>
                    <h4 className="font-bold text-amber text-sm uppercase tracking-wide">
                      TBT Microstructure Sentinel & Decision Blueprint Guide
                    </h4>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowSentinelGuide(false)}
                    className="text-xs text-muted hover:text-text cursor-pointer"
                  >
                    ✕ Close
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                  {/* Card 1: Fortress Bid */}
                  <div className="p-3 rounded-lg border border-emerald/30 bg-emerald/5 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-emerald font-bold text-xs uppercase">
                      <span>🛡️</span>
                      <span>Demand Floor (Bullish)</span>
                    </div>
                    <p className="text-[11px] text-text/80 leading-relaxed font-sans">
                      <strong>What it is:</strong> Massive institutional buy orders (≥15% of depth) persistently holding for &gt;15s without cancelling.
                    </p>
                    <div className="p-1.5 rounded bg-emerald/15 border border-emerald/30 text-[10px] text-emerald font-bold">
                      🎯 <strong>Decision:</strong> FAVOR CALLS / LONGS. High bounce probability. Anchor your Stop-Loss 1-2 ticks below this price floor.
                    </div>
                  </div>

                  {/* Card 2: Fortress Ask */}
                  <div className="p-3 rounded-lg border border-rose/30 bg-rose/5 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-rose font-bold text-xs uppercase">
                      <span>🏰</span>
                      <span>Supply Ceiling (Bearish)</span>
                    </div>
                    <p className="text-[11px] text-text/80 leading-relaxed font-sans">
                      <strong>What it is:</strong> Immovable institutional sell orders (≥15% of depth) parked overhead capping upside for &gt;15s without cancelling.
                    </p>
                    <div className="p-1.5 rounded bg-rose/15 border border-rose/30 text-[10px] text-rose font-bold">
                      🎯 <strong>Decision:</strong> FAVOR PUTS / SHORTS. Hard ceiling. Take profit on long trades; do not buy breakouts until this wall is swept.
                    </div>
                  </div>

                  {/* Card 3: Bid Spoof */}
                  <div className="p-3 rounded-lg border border-amber/30 bg-amber/5 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-amber font-bold text-xs uppercase">
                      <span>⚠️</span>
                      <span>Bid Spoof / Rugpull (Bear)</span>
                    </div>
                    <p className="text-[11px] text-text/80 leading-relaxed font-sans">
                      <strong>What it is:</strong> A large resting buy wall vanished the moment price approached within 0.15% (deceptive liquidity to lure retail buyers).
                    </p>
                    <div className="p-1.5 rounded bg-amber/15 border border-amber/30 text-[10px] text-amber font-bold">
                      🎯 <strong>Decision:</strong> DO NOT CHASE LONGS. Fake support is gone. High probability of a sharp dump; wait for real absorption.
                    </div>
                  </div>

                  {/* Card 4: Ask Spoof */}
                  <div className="p-3 rounded-lg border border-sapphire/30 bg-sapphire/5 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-sapphire font-bold text-xs uppercase">
                      <span>🚀</span>
                      <span>Ask Spoof / Squeeze (Bull)</span>
                    </div>
                    <p className="text-[11px] text-text/80 leading-relaxed font-sans">
                      <strong>What it is:</strong> A large resting sell wall vanished as price approached (bluffing short sellers fled, removing overhead roadblock).
                    </p>
                    <div className="p-1.5 rounded bg-sapphire/15 border border-sapphire/30 text-[10px] text-sapphire font-bold">
                      🎯 <strong>Decision:</strong> FAVOR LONGS / CALLS. Overhead ceiling was a bluff. Expect accelerated upward breakout as trapped shorts cover.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 15 Slots Full Interactive Table */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                  Active 15-Slot L3 Market Depth Allocations & Microstructure Status
                </h3>
                <span className="text-xs font-mono text-muted">
                  Click 'Evict' on any blocking strike to immediately liberate capacity
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono text-left">
                  <thead>
                    <tr className="border-b border-border text-muted text-[10px] uppercase">
                      <th className="py-2.5 px-2">Slot</th>
                      <th className="px-2">Instrument</th>
                      <th className="px-2">Role / Tier</th>
                      <th className="px-2">Held Duration</th>
                      <th className="px-2">Depth Freshness</th>
                      <th className="px-2 text-right">LTP (₹)</th>
                      <th className="px-2 text-right">Spread</th>
                      <th className="px-2 text-center">OBI-50</th>
                      <th className="px-2">Order Flow Sentinel & Decision Bias</th>
                      <th className="px-2 text-right">Operator Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {(tbt.slots || []).length === 0 ? (
                      <tr>
                        <td colSpan="10" className="py-8 text-center text-muted font-mono">
                          No active TBT subscriptions. Click 'Force Rebalance' or allocate above.
                        </td>
                      </tr>
                    ) : (
                      (tbt.slots || []).map((slot, sIdx) => {
                        const isStale = slot.is_stale
                        const roleColor =
                          slot.role === 'IN_FLIGHT_GUARDIAN'
                            ? 'var(--color-sapphire)'
                            : slot.role === 'CORE_GRID'
                            ? '#a855f7'
                            : slot.role === 'TODAYS_EXPIRY'
                            ? 'var(--color-gold)'
                            : slot.role === 'SECTOR_LEADER_SCOUT'
                            ? '#38bdf8'
                            : 'var(--color-emerald)'
                        const roleBg =
                          slot.role === 'IN_FLIGHT_GUARDIAN'
                            ? 'rgba(56, 189, 248, 0.12)'
                            : slot.role === 'CORE_GRID'
                            ? 'rgba(168, 85, 247, 0.12)'
                            : slot.role === 'TODAYS_EXPIRY'
                            ? 'rgba(245, 166, 35, 0.15)'
                            : slot.role === 'SECTOR_LEADER_SCOUT'
                            ? 'rgba(56, 189, 248, 0.12)'
                            : 'rgba(0, 214, 143, 0.12)'

                        const durationStr =
                          slot.duration_seconds < 60
                            ? `${Math.round(slot.duration_seconds)}s`
                            : slot.duration_seconds < 3600
                            ? `${Math.floor(slot.duration_seconds / 60)}m ${Math.round(slot.duration_seconds % 60)}s`
                            : `${Math.floor(slot.duration_seconds / 3600)}h ${Math.floor((slot.duration_seconds % 3600) / 60)}m`

                        const freshStr =
                          slot.last_packet_age_seconds === null
                            ? 'Awaiting tick'
                            : slot.last_packet_age_seconds < 1.0
                            ? `${Math.round(slot.last_packet_age_seconds * 1000)}ms ago`
                            : `${Math.round(slot.last_packet_age_seconds)}s ago`

                        const obi = slot.obi_50 || 0.0
                        const obiColor =
                          obi > 0.15 ? 'var(--color-emerald)' : obi < -0.15 ? 'var(--color-rose)' : 'var(--color-text)'

                        return (
                          <tr key={slot.symbol} className="hover:bg-elevated/40 transition-colors">
                            <td className="py-2 px-2 text-muted font-bold font-mono">
                              #{String(slot.slot_number).padStart(2, '0')}
                            </td>
                            <td className="px-2 font-bold text-text">
                              <span className="font-mono">{slot.symbol}</span>
                            </td>
                            <td className="px-2">
                              <span
                                className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase border"
                                style={{
                                  background: roleBg,
                                  borderColor: roleColor,
                                  color: roleColor,
                                }}
                              >
                                {slot.role === 'SECTOR_LEADER_SCOUT' ? 'SECTOR LEADER' : slot.role.replace(/_/g, ' ')}
                              </span>
                            </td>
                            <td className="px-2 text-muted">{durationStr}</td>
                            <td className="px-2">
                              <span
                                className="inline-flex items-center gap-1.5 font-bold"
                                style={{
                                  color: isStale ? 'var(--color-rose)' : 'var(--color-emerald)',
                                }}
                              >
                                <span className="h-1.5 w-1.5 rounded-full inline-block" style={{ background: isStale ? 'var(--color-rose)' : 'var(--color-emerald)' }} />
                                {freshStr}
                                {isStale && <span className="text-[11px] uppercase px-1 rounded bg-rose/15 text-rose">STALE</span>}
                              </span>
                            </td>
                            <td className="px-2 text-right font-bold text-text">
                              {slot.ltp ? `₹${Number(slot.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                            </td>
                            <td className="px-2 text-right text-muted">
                              {slot.spread ? `₹${slot.spread}` : '—'}
                            </td>
                            <td className="px-2 text-center font-bold" style={{ color: obiColor }}>
                              {obi > 0 ? `+${obi.toFixed(2)}` : obi.toFixed(2)}
                            </td>
                            <td
                              className="px-2 py-1.5 relative group/sentinel"
                              onMouseEnter={(e) => {
                                const intel = deriveSentinelIntel(slot)
                                handleSentinelHover(intel, e.currentTarget)
                              }}
                              onMouseLeave={() => setHoveredSentinel(null)}
                              data-testid={`tbt-sentinel-cell-${slot.symbol}`}
                            >
                              {(() => {
                                const intel = deriveSentinelIntel(slot)
                                const isBull = intel.bias === 'BULLISH'
                                const isBear = intel.bias === 'BEARISH'
                                const isCaution = intel.bias === 'CAUTION_BEAR' || intel.bias === 'CAUTION'
                                const badgeBg = isBull
                                  ? 'bg-emerald/15 border-emerald/40 text-emerald'
                                  : isCaution
                                  ? 'bg-amber/15 border-amber/40 text-amber'
                                  : isBear
                                  ? 'bg-rose/15 border-rose/40 text-rose'
                                  : 'bg-surface border-border text-muted'

                                return (
                                  <div className="inline-block text-left cursor-help">
                                    <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-bold ${badgeBg}`}>
                                      <span>{intel.badge}</span>
                                    </div>
                                    <div className="text-[10px] font-mono text-muted/90 truncate max-w-[210px] mt-0.5">
                                      {intel.headline}
                                    </div>
                                  </div>
                                )
                              })()}
                            </td>
                            <td className="px-2 text-right">
                              <button
                                type="button"
                                onClick={() => handleEvictTbtSlot(slot.symbol)}
                                disabled={actionInProgress === `evict_${slot.symbol}`}
                                className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose/15 hover:bg-rose/25 text-rose border border-rose/30 cursor-pointer transition-colors"
                                title="Evict this symbol immediately to free a slot for higher priority setups"
                              >
                                {actionInProgress === `evict_${slot.symbol}` ? 'Evicting…' : '✕ Evict Slot'}
                              </button>
                            </td>
                          </tr>
                        )
                      })
                    )}

                    {/* Unallocated Slots Placeholder Rows */}
                    {Array.from({ length: Math.max(0, 15 - (tbt.slots || []).length) }).map((_, i) => {
                      const slotNum = (tbt.slots || []).length + i + 1
                      return (
                        <tr key={`empty-slot-${slotNum}`} className="opacity-40 border-dashed hover:opacity-70 transition-opacity">
                          <td className="py-2 px-2 text-muted font-mono font-bold">
                            #{String(slotNum).padStart(2, '0')}
                          </td>
                          <td colSpan="8" className="px-2 text-muted italic font-mono text-[11px]">
                            — Available Slot (Ready for dynamic JIT scout or execution guardian) —
                          </td>
                          <td className="px-2 text-right">
                            <span className="text-[10px] text-emerald font-mono uppercase font-bold">
                              FREE
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          )
        })()}

        {/* ─────────── TAB: UNIVERSE DEPTH RADAR ─────────── */}
        {activeTab === 'depth_radar' && (
          <div className="space-y-4 max-w-7xl 2xl:max-w-[1560px] mx-auto">
            {/* Header & Status Banner */}
            <div className="p-4 rounded-xl border border-border bg-panel flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold font-ui uppercase tracking-wider text-text flex items-center gap-1.5">
                    <span>🌊</span> Institutional L2 Market Depth Radar
                  </h3>
                  <span
                    className="px-2 py-0.5 rounded font-mono text-[10px] font-bold uppercase border"
                    style={{
                      background: 'rgba(59,130,246,0.12)',
                      borderColor: 'var(--color-sapphire)',
                      color: 'var(--color-sapphire)',
                    }}
                  >
                    ● {filteredRadarItems.length} SYMBOLS MONITORED
                  </span>
                  <span className="px-2 py-0.5 rounded font-mono text-[10px] bg-elevated border border-border text-muted">
                    L2 5-Depth • Sub-Second Microstructure
                  </span>
                </div>
                <p className="text-xs font-mono text-muted mt-0.5">
                  Order Book Imbalance (OBI) • Micro-Price Lead Skew • Spread Friction • Resting Pocket Sentinel
                </p>
              </div>

              {/* Action Controls & Auto-Refresh Toggle */}
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  onClick={() => setRadarAutoRefresh(!radarAutoRefresh)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold border transition-all cursor-pointer ${
                    radarAutoRefresh
                      ? 'bg-emerald/15 border-emerald/40 text-emerald'
                      : 'bg-elevated border-border text-muted hover:text-text'
                  }`}
                  title="Toggle automatic 3.5s real-time depth polling"
                >
                  <span>{radarAutoRefresh ? '⚡' : '⏸️'}</span>
                  <span>{radarAutoRefresh ? 'Live (3.5s)' : 'Paused'}</span>
                </button>

                <button
                  type="button"
                  onClick={fetchDepthRadar}
                  disabled={radarLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-elevated hover:bg-highlight border border-border text-text transition-all cursor-pointer"
                  title="Refresh L2 depth snapshots immediately"
                >
                  <span className={radarLoading ? 'animate-spin' : ''}>🔄</span>
                  <span>{radarLoading ? 'Refreshing…' : 'Refresh Now'}</span>
                </button>

                <button
                  type="button"
                  data-testid="toggle-radar-inspector"
                  onClick={() => setRadarInspectorOpen(!radarInspectorOpen)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold border transition-all cursor-pointer ${
                    radarInspectorOpen
                      ? 'bg-gold/20 border-gold/50 text-gold shadow-xs'
                      : 'bg-elevated hover:bg-highlight border-border text-muted hover:text-text'
                  }`}
                  title={
                    radarInspectorOpen
                      ? 'Collapse L2 DOM Inspector (Expand table to full-width)'
                      : 'Open L2 DOM Inspector Dock'
                  }
                >
                  <span>🔬</span>
                  <span>Inspector: {radarInspectorOpen ? 'Docked' : 'Hidden'}</span>
                  <span className="text-[10px] opacity-75">{radarInspectorOpen ? '◀' : '▶'}</span>
                </button>
              </div>
            </div>

            {/* KPI Summary Ribbon */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-muted block uppercase font-bold">Total Monitored</span>
                <span className="text-base font-mono font-black text-text">{radarItems.length}</span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-emerald block uppercase font-bold">Buyer Dominance (OBI ≥ +20%)</span>
                <span className="text-base font-mono font-black text-emerald">
                  {radarItems.filter((x) => (x.obi || 0) >= 0.2).length}
                </span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-rose block uppercase font-bold">Supply Overhang (OBI ≤ -20%)</span>
                <span className="text-base font-mono font-black text-rose">
                  {radarItems.filter((x) => (x.obi || 0) <= -0.2).length}
                </span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-gold block uppercase font-bold">Resting Walls Active</span>
                <span className="text-base font-mono font-black text-gold">
                  {radarItems.filter((x) => Boolean(x.has_resting_wall)).length}
                </span>
              </div>
              <div className="p-2.5 rounded-xl border border-border bg-elevated text-center">
                <span className="text-[10px] font-mono text-cyan-400 block uppercase font-bold">Ultra-Tight Spread (&lt;2 bps)</span>
                <span className="text-base font-mono font-black text-cyan-400">
                  {radarItems.filter((x) => (x.spread_bps || 0) <= 2.0).length}
                </span>
              </div>
            </div>

            {/* Command & Filter Bar */}
            <div className="p-3 rounded-xl border border-border bg-panel flex flex-col md:flex-row md:items-center justify-between gap-3">
              {/* Search & Segment Pills */}
              <div className="flex items-center gap-2 flex-wrap flex-1">
                <div className="relative min-w-[200px]">
                  <input
                    type="text"
                    value={radarSearch}
                    onChange={(e) => setRadarSearch(e.target.value)}
                    placeholder="Search symbol (e.g. NIFTY, RELIANCE, CE)..."
                    className="w-full bg-elevated border border-border rounded-lg pl-8 pr-7 py-1.5 text-xs font-mono text-text outline-none focus:border-gold"
                  />
                  <span className="absolute left-2.5 top-2 text-xs text-muted">🔍</span>
                  {radarSearch && (
                    <button
                      type="button"
                      onClick={() => setRadarSearch('')}
                      className="absolute right-2.5 top-1.5 text-xs text-muted hover:text-text cursor-pointer"
                    >
                      ✕
                    </button>
                  )}
                </div>

                <div className="flex items-center gap-1 bg-elevated p-1 rounded-lg border border-border flex-wrap">
                  {(() => {
                    const isEvening = tbt.session_state === 'STANDBY_EOD' || ['COMMODITY_CDS', 'OFF_MARKET'].includes(tbt.current_session)
                    return [
                      { id: 'ALL', label: 'All Universe' },
                      { id: 'COMMODITIES', label: '🛢️ Commodities (MCX)', live: isEvening },
                      { id: 'CURRENCY', label: '💱 Currency (CDS)' },
                      { id: 'INDICES', label: isEvening ? '🏛️ Indices (EOD)' : '🏛️ Indices' },
                      { id: 'STOCKS', label: isEvening ? '⚡ F&O Stocks (EOD)' : '⚡ F&O Stocks' },
                      { id: 'ALERTS', label: '🎯 Active Alerts' },
                      { id: 'HIGH_OBI', label: '🔥 High OBI (≥30%)' },
                      { id: 'WALLS', label: '🛡️ Walls Active' },
                    ].map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setRadarSegment(tab.id)}
                        className={`px-2.5 py-1 rounded-md text-[11px] font-mono font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
                          radarSegment === tab.id
                            ? 'bg-panel text-gold shadow-xs border border-border'
                            : 'text-muted hover:text-text'
                        }`}
                      >
                        <span>{tab.label}</span>
                        {tab.live && (
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald animate-pulse" title="Active Evening Session" />
                        )}
                      </button>
                    ))
                  })()}
                </div>
              </div>

              {/* Sort Selector */}
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono uppercase font-bold text-muted">Sort:</span>
                <select
                  value={radarSort}
                  onChange={(e) => setRadarSort(e.target.value)}
                  className="bg-elevated border border-border rounded-lg px-2.5 py-1 text-xs font-mono font-bold text-text outline-none cursor-pointer"
                >
                  <option value="OBI_DESC">Demand Skew (OBI Highest ▼)</option>
                  <option value="OBI_ASC">Supply Skew (OBI Lowest ▲)</option>
                  <option value="MICRO_SKEW_DESC">Micro-Price Skew (Breakout Lead ▼)</option>
                  <option value="SPREAD_ASC">Tightest Spread (Lowest Friction ▲)</option>
                  <option value="NOTIONAL_DESC">Depth Capital (₹ Cr Highest ▼)</option>
                  <option value="PRICE_DESC">Price (LTP Highest ▼)</option>
                </select>
              </div>
            </div>

            {/* Master-Detail Workspace (Full-Width Table when Inspector is Collapsed) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
              {/* Left / Master Heatmap Table (12 columns when collapsed, 8 columns when inspector docked) */}
              <div
                className={`${
                  radarInspectorOpen ? 'lg:col-span-8' : 'lg:col-span-12'
                } rounded-xl border border-border bg-panel overflow-hidden shadow-xs transition-all duration-200`}
              >
                <div className="overflow-x-auto max-h-[720px] overflow-y-auto">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead className="sticky top-0 z-20 bg-elevated/95 backdrop-blur-xs border-b border-border text-[10px] font-mono text-muted uppercase">
                      <tr>
                        <th className="py-2.5 px-3">Symbol & Segment</th>
                        <th className="px-2 text-right">LTP</th>
                        <th className="px-2 text-center">Spread</th>
                        <th className="px-3 text-center">Capital Depth (Bid / Ask)</th>
                        <th className="px-3 text-center">OBI Imbalance</th>
                        <th className="px-2 text-center">Micro-Skew</th>
                        <th className="px-3">Sentinel & Trading Bias</th>
                        <th className="px-3 text-right">Inspect</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40 font-mono">
                      {filteredRadarItems.length === 0 ? (
                        <tr>
                          <td colSpan="8" className="py-12 text-center text-muted italic">
                            {radarLoading ? 'Scanning universe order books…' : 'No matching symbols found for selected filter.'}
                          </td>
                        </tr>
                      ) : (
                        filteredRadarItems.map((item, idx) => {
                          const isSelected = selectedRadarSymbol === item.symbol
                          const obi = Number(item.obi || 0)
                          const obiPct = Number(item.obi_pct || (obi * 100))
                          const intel = item.decision_intel || {}
                          const isBull = intel.bias === 'BULLISH'
                          const isBear = intel.bias === 'BEARISH'
                          const isCaution = intel.bias === 'CAUTION'
                          const isTight = item.spread_status === 'TIGHT'
                          const isWide = item.spread_status === 'WIDE'

                          // Visual split bar for capital depth
                          const bidCr = Number(item.bid_notional_cr || 0)
                          const askCr = Number(item.ask_notional_cr || 0)
                          const totalCr = bidCr + askCr
                          const bidRatioPct = totalCr > 0 ? Math.round((bidCr / totalCr) * 100) : 50

                          return (
                            <tr
                              key={`radar-${item.symbol}-${idx}`}
                              onClick={() => setSelectedRadarSymbol(item.symbol)}
                              onDoubleClick={() => {
                                setSelectedRadarSymbol(item.symbol)
                                setRadarInspectorOpen(true)
                              }}
                              className={`transition-colors cursor-pointer group ${
                                isSelected
                                  ? 'bg-elevated border-l-2 border-l-gold'
                                  : 'hover:bg-elevated/60'
                              }`}
                              title="Click to select • Double-click to open L2 Inspector"
                            >
                              {/* Symbol & Segment */}
                              <td className="py-2.5 px-3">
                                <div className="flex items-center gap-1.5">
                                  <span className="font-bold text-text group-hover:text-gold transition-colors">
                                    {item.symbol}
                                  </span>
                                  {item.has_resting_wall && (
                                    <span
                                      className="text-[11px] px-1 py-px rounded font-bold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/40"
                                      title={`Resting Wall: ${item.wall_ratio || 1.0}x average depth`}
                                    >
                                      🛡️ WALL
                                    </span>
                                  )}
                                </div>
                                <div className="text-[11px] text-muted flex items-center gap-1 mt-0.5">
                                  <span
                                    className={`px-1 py-px rounded border text-[10px] font-bold ${
                                      item.segment?.includes('COMMODITY')
                                        ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                                        : item.segment?.includes('CURRENCY')
                                        ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'
                                        : item.segment?.includes('INDEX')
                                        ? 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
                                        : item.segment?.includes('STOCK')
                                        ? 'bg-purple-500/15 text-purple-300 border-purple-500/30'
                                        : 'bg-surface border-border text-muted'
                                    }`}
                                  >
                                    {item.segment === 'COMMODITY_MCX'
                                      ? '🛢️ MCX'
                                      : item.segment === 'CURRENCY_CDS'
                                      ? '💱 CDS'
                                      : item.segment === 'INDEX_FNO'
                                      ? '🏛️ INDEX'
                                      : item.segment === 'STOCK_FNO'
                                      ? '⚡ F&O'
                                      : item.segment || 'EQUITY'}
                                  </span>
                                  {item.is_market_open === false && (
                                    <span className="text-[10px] px-1 py-px rounded font-bold uppercase bg-muted/20 text-muted border border-muted/30">
                                      EOD
                                    </span>
                                  )}
                                  {item.is_market_open === true && item.segment?.includes('COMMODITY') && (
                                    <span className="text-[10px] px-1 py-px rounded font-bold uppercase bg-emerald/20 text-emerald border border-emerald/40 animate-pulse">
                                      ● LIVE
                                    </span>
                                  )}
                                  <span>{item.provenance || 'L2'}</span>
                                </div>
                              </td>

                              {/* LTP */}
                              <td className="px-2 text-right font-bold text-text">
                                ₹{Number(item.ltp || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                              </td>

                              {/* Spread */}
                              <td className="px-2 text-center">
                                <span
                                  className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                    isTight
                                      ? 'bg-emerald/15 text-emerald border border-emerald/30'
                                      : isWide
                                      ? 'bg-rose/15 text-rose border border-rose/30'
                                      : 'bg-surface text-muted border border-border'
                                  }`}
                                  title={`Spread: ₹${item.spread || 0} (${item.spread_bps || 0} bps)`}
                                >
                                  {item.spread_bps != null ? `${item.spread_bps} bps` : '—'}
                                </span>
                              </td>

                              {/* Capital Depth Notional (Bid vs Ask Cr) */}
                              <td className="px-3 text-center">
                                <div className="w-32 mx-auto space-y-1">
                                  <div className="flex justify-between text-[11px] text-muted font-bold">
                                    <span className="text-emerald">₹{bidCr}Cr</span>
                                    <span className="text-rose">₹{askCr}Cr</span>
                                  </div>
                                  <div className="h-1.5 w-full rounded-full bg-surface overflow-hidden flex">
                                    <div
                                      className="h-full bg-emerald transition-all"
                                      style={{ width: `${bidRatioPct}%` }}
                                      title={`Bid Capital: ₹${bidCr} Cr (${bidRatioPct}%)`}
                                    />
                                    <div
                                      className="h-full bg-rose transition-all"
                                      style={{ width: `${100 - bidRatioPct}%` }}
                                      title={`Ask Capital: ₹${askCr} Cr (${100 - bidRatioPct}%)`}
                                    />
                                  </div>
                                </div>
                              </td>

                              {/* OBI Imbalance */}
                              <td className="px-3 text-center">
                                <div className="inline-flex items-center gap-1.5">
                                  <span
                                    className={`text-[11px] font-black ${
                                      obi >= 0.2
                                        ? 'text-emerald'
                                        : obi <= -0.2
                                        ? 'text-rose'
                                        : 'text-muted'
                                    }`}
                                  >
                                    {obiPct > 0 ? `+${obiPct}%` : `${obiPct}%`}
                                  </span>
                                  <div className="w-12 h-1.5 rounded-full bg-surface overflow-hidden relative">
                                    <div
                                      className="absolute top-0 bottom-0 rounded-full transition-all"
                                      style={{
                                        left: obi < 0 ? `${50 + (obi * 50)}%` : '50%',
                                        width: `${Math.abs(obi * 50)}%`,
                                        background: obi > 0 ? 'var(--color-emerald)' : 'var(--color-rose)',
                                      }}
                                    />
                                  </div>
                                </div>
                              </td>

                              {/* Micro-Skew */}
                              <td className="px-2 text-center">
                                <span
                                  className={`text-[10px] font-bold ${
                                    (item.micro_skew_bps || 0) > 1.0
                                      ? 'text-emerald'
                                      : (item.micro_skew_bps || 0) < -1.0
                                      ? 'text-rose'
                                      : 'text-muted'
                                  }`}
                                  title={`Micro-Price: ₹${item.micro_price || item.ltp} (Leading Skew: ${item.micro_skew_bps || 0} bps)`}
                                >
                                  {(item.micro_skew_bps || 0) > 0 ? `+${item.micro_skew_bps}` : item.micro_skew_bps} bps
                                </span>
                              </td>

                              {/* Sentinel Posture & Hover Blueprint */}
                              <td
                                className="px-3 relative group/sentinel"
                                onMouseEnter={(e) => handleSentinelHover(intel, e.currentTarget)}
                                onMouseLeave={() => setHoveredSentinel(null)}
                                data-testid={`sentinel-cell-${item.symbol}`}
                              >
                                {(() => {
                                  const badgeBg = isBull
                                    ? 'bg-emerald/15 border-emerald/40 text-emerald'
                                    : isCaution
                                    ? 'bg-amber/15 border-amber/40 text-amber'
                                    : isBear
                                    ? 'bg-rose/15 border-rose/40 text-rose'
                                    : 'bg-surface border-border text-muted'

                                  return (
                                    <div className="inline-block text-left cursor-help">
                                      <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-bold ${badgeBg}`}>
                                        <span>{intel.badge || '⚖️ BALANCED'}</span>
                                      </div>
                                      <div className={`text-[10px] font-mono text-muted truncate mt-0.5 ${
                                        radarInspectorOpen ? 'max-w-[190px]' : 'max-w-[320px]'
                                      }`}>
                                        {intel.headline || 'Equilibrium Depth'}
                                      </div>
                                    </div>
                                  )
                                })()}
                              </td>

                              {/* Inspect / Stage */}
                              <td className="px-3 text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  <button
                                    type="button"
                                    data-testid={`inspect-dom-${item.symbol}`}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setSelectedRadarSymbol(item.symbol)
                                      setRadarInspectorOpen(true)
                                    }}
                                    className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-colors cursor-pointer ${
                                      isSelected && radarInspectorOpen
                                        ? 'bg-gold/25 border-gold text-gold font-black'
                                        : 'bg-elevated hover:bg-highlight border-border text-muted hover:text-text'
                                    }`}
                                    title={
                                      radarInspectorOpen && isSelected
                                        ? 'Currently inspecting in DOM ladder'
                                        : `Open L2 DOM Inspector for ${item.symbol}`
                                    }
                                  >
                                    DOM {isSelected && radarInspectorOpen ? '●' : '→'}
                                  </button>

                                  {onOpenOrderTicket && (
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        onOpenOrderTicket({
                                          symbol: item.symbol,
                                          price: item.ltp,
                                          side: item.decision_intel?.bias === 'BEARISH' ? 'SELL' : 'BUY',
                                        })
                                      }}
                                      className="px-2 py-0.5 rounded text-[10px] font-bold bg-sapphire/20 hover:bg-sapphire/30 text-sapphire border border-sapphire/40 transition-colors cursor-pointer"
                                      title="Stage Order in Ticket Modal"
                                    >
                                      Stage
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Right / Live DOM Inspector Dock (Rendered only when open) */}
              {radarInspectorOpen && (
                <div className="lg:col-span-4 rounded-xl border border-border bg-panel p-3 sticky top-4 shadow-sm space-y-3 transition-all duration-200">
                  <div className="flex items-center justify-between pb-2 border-b border-border">
                    <div className="flex items-center gap-2">
                      <span className="text-base">🔬</span>
                      <div>
                        <h4 className="text-xs font-bold font-mono text-text">
                          {selectedRadarSymbol || 'Select Symbol'}
                        </h4>
                        <span className="text-[11px] font-mono text-muted uppercase">
                          Real-Time 5-Level Depth Ladder
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {selectedRadarSymbol && (
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-elevated border border-border text-gold font-bold">
                          ACTIVE INSPECTOR
                        </span>
                      )}
                      <button
                        type="button"
                        data-testid="close-radar-inspector"
                        onClick={() => setRadarInspectorOpen(false)}
                        className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-elevated hover:bg-highlight border border-border text-muted hover:text-text transition-colors cursor-pointer"
                        title="Collapse Inspector (Expand table full-width)"
                        aria-label="Close Inspector"
                      >
                        ✕
                      </button>
                    </div>
                  </div>

                  {selectedRadarSymbol ? (
                    <div className="space-y-3">
                      <DepthLadderWidget
                        symbol={selectedRadarSymbol}
                        compact={true}
                        onPriceSelect={(p) => {
                          if (onOpenOrderTicket) {
                            onOpenOrderTicket({ symbol: selectedRadarSymbol, price: p })
                          }
                        }}
                      />

                      {/* Quick 1-Click Order Staging Bar */}
                      {onOpenOrderTicket && (
                        <div className="pt-2 border-t border-border grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              const curItem = radarItems.find((x) => x.symbol === selectedRadarSymbol)
                              onOpenOrderTicket({
                                symbol: selectedRadarSymbol,
                                price: curItem?.ltp || 0,
                                side: 'BUY',
                              })
                            }}
                            className="py-1.5 px-2 rounded-lg bg-emerald/20 hover:bg-emerald/30 text-emerald border border-emerald/40 text-[10px] font-mono font-bold transition-all cursor-pointer text-center"
                          >
                            Stage BUY Order
                          </button>

                          <button
                            type="button"
                            onClick={() => {
                              const curItem = radarItems.find((x) => x.symbol === selectedRadarSymbol)
                              onOpenOrderTicket({
                                symbol: selectedRadarSymbol,
                                price: curItem?.ltp || 0,
                                side: 'SELL',
                              })
                            }}
                            className="py-1.5 px-2 rounded-lg bg-rose/20 hover:bg-rose/30 text-rose border border-rose/40 text-[10px] font-mono font-bold transition-all cursor-pointer text-center"
                          >
                            Stage SELL Order
                          </button>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="py-16 text-center text-muted italic font-mono text-xs">
                      Click any symbol in the radar table to inspect live order book ladder.
                    </div>
                  )}
                </div>
              )}
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
                  Total Allocated: {Math.round((storage.total_size_mb ?? storage.total_app_data_mb ?? 0) * 10) / 10} MB
                </span>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Business Orders & Fills</span>
                  <span className="text-sm font-mono font-bold text-text">
                    {Math.round((storage.tiers?.business?.size_mb ?? storage.business_data_mb ?? 0) * 10) / 10} MB
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Market Data Ticks</span>
                  <span className="text-sm font-mono font-bold text-text">
                    {Math.round((storage.tiers?.market_data?.size_mb ?? storage.market_data_mb ?? 0) * 10) / 10} MB
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Analytical Cache</span>
                  <span className="text-sm font-mono font-bold text-text">
                    {Math.round((storage.tiers?.analytics?.size_mb ?? storage.analysis_cache_mb ?? 0) * 10) / 10} MB
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-elevated">
                  <span className="text-[10px] font-mono text-muted block uppercase">Telemetry Logs</span>
                  <span className="text-sm font-mono font-bold text-text">
                    {Math.round((storage.tiers?.telemetry?.size_mb ?? storage.telemetry_mb ?? 0) * 10) / 10} MB
                  </span>
                </div>
              </div>
            </div>

            {/* 1-Click Operations */}
            <div className="p-4 rounded-xl border border-border bg-panel space-y-3">
              <h3 className="text-xs font-bold font-ui uppercase tracking-wider text-muted">
                1-Click Maintenance Operations
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
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

                <div className="p-3 rounded-xl border border-border bg-elevated flex flex-col justify-between space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-text">Sync Fundamentals</h4>
                    <p className="text-[11px] font-mono text-muted mt-1 leading-normal">
                      Synchronizes financial metrics, balance sheets, and forensic models.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleTriggerFundamentalsSync}
                    disabled={actionInProgress === 'sync_fundamentals'}
                    className="w-full py-1.5 px-3 rounded-lg text-xs font-mono font-bold bg-panel hover:bg-highlight border border-border text-text transition-colors cursor-pointer"
                  >
                    {actionInProgress === 'sync_fundamentals' ? 'Syncing…' : '📑 Sync Financials'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Dynamic Viewport-Clamped Sentinel Intel Portal (Zero Scroll Clipping, 100% Solid Opacity) */}
      {hoveredSentinel && typeof document !== 'undefined' && createPortal(
        (() => {
          const { intel, rect } = hoveredSentinel
          if (!intel) return null

          const isBull = intel.bias === 'BULLISH'
          const isBear = intel.bias === 'BEARISH'
          const isCaution = intel.bias === 'CAUTION_BEAR' || intel.bias === 'CAUTION'

          const cardWidth = 340
          const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1920
          const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 1080

          const rectTop = rect ? (rect.top || 120) : 120
          const rectBottom = rect ? (rect.bottom || 160) : 160
          const rectRight = rect ? (rect.right || 400) : 400

          // Calculate available vertical space below vs above
          const spaceBelow = viewportHeight - rectBottom
          const spaceAbove = rectTop
          const preferBelow = spaceBelow >= 220 || spaceBelow >= spaceAbove

          const style = {
            position: 'fixed',
            width: `${cardWidth}px`,
            zIndex: 99999,
            backgroundColor: '#0d1527',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.95), 0 0 0 1px rgba(51, 65, 85, 0.8)',
          }

          if (preferBelow) {
            const topPos = Math.max(12, Math.min(rectBottom + 6, viewportHeight - 120))
            style.top = `${Math.round(topPos)}px`
            style.maxHeight = `${Math.max(160, viewportHeight - topPos - 16)}px`
          } else {
            const bottomPos = Math.max(12, Math.min(viewportHeight - rectTop + 6, viewportHeight - 120))
            style.bottom = `${Math.round(bottomPos)}px`
            style.maxHeight = `${Math.max(160, rectTop - 18)}px`
          }

          let leftPos = rectRight - cardWidth
          leftPos = Math.max(16, Math.min(leftPos, viewportWidth - cardWidth - 16))
          style.left = `${Math.round(leftPos)}px`

          return (
            <div
              data-testid="sentinel-portal-card"
              className="p-3.5 rounded-xl border border-slate-700/80 text-left pointer-events-none overflow-y-auto"
              style={style}
            >
              <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-700/80">
                <span
                  className={`text-[11px] font-black uppercase tracking-wider ${
                    isBull
                      ? 'text-emerald-400'
                      : isCaution
                      ? 'text-amber-400'
                      : isBear
                      ? 'text-rose-400'
                      : 'text-cyan-400'
                  }`}
                >
                  {intel.badge || 'SENTINEL INTEL'}
                </span>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded border border-slate-700 text-slate-300 bg-slate-900/90 font-bold">
                  {intel.tag || 'ORDER FLOW'}
                </span>
              </div>

              <p className="text-[11px] text-slate-200 font-medium leading-relaxed mb-2.5 font-sans">
                {intel.meaning}
              </p>

              {intel.decision && (
                <div
                  className={`p-2.5 rounded-lg border text-[10px] font-mono leading-normal bg-slate-950 ${
                    isBull
                      ? 'border-emerald-500/40 text-emerald-300'
                      : isCaution
                      ? 'border-amber-500/40 text-amber-300'
                      : isBear
                      ? 'border-rose-500/40 text-rose-300'
                      : 'border-slate-700 text-slate-200'
                  }`}
                >
                  <span className="block text-[11px] uppercase tracking-wider text-slate-400 font-bold mb-1 font-mono">
                    🎯 Trading Decision Blueprint:
                  </span>
                  <span className="text-slate-100 font-semibold">{intel.decision}</span>
                </div>
              )}
            </div>
          )
        })(),
        document.body
      )}
    </div>
  )
}
