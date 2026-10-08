import { useState, useEffect, useMemo, useRef } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import { useRealtimeMarket } from '../../hooks/useRealtimeMarket'
import { formatINR, formatPct } from '../../utils/formatINR'
import UnavailableState from '../Common/UnavailableState'
import Badge from '../Common/Badge'
import Tooltip, { HelpHint } from '../UI/Tooltip'

const ARCHETYPE_TABS = [
  { id: 'ALL', label: 'All Inflections', icon: '🌐' },
  { id: 'VCP_PIVOT_BREAKOUT', label: 'VCP Pivots', icon: '🎯' },
  { id: 'TTM_SQUEEZE_EXPLOSION', label: 'TTM Squeeze', icon: '⚡' },
  { id: 'STAGE_1_TO_2_EXPANSION', label: 'Stage 1→2 Markup', icon: '🚀' },
  { id: 'SMC_SPRING_SWEEP', label: 'SMC Springs & Sweeps', icon: '🎪' },
  { id: 'RRG_SECTOR_ROTATION', label: 'Sector RRG', icon: '🔄' },
]

const TIMING_TABS = [
  { id: 'ALL', label: 'All Timing' },
  { id: 'TRIGGER_NOW', label: '🔥 Trigger Now' },
  { id: 'COILING_IMMINENT', label: '⏳ Coiling (1–3d)' },
  { id: 'PULLBACK_RETEST', label: '🎯 Retest Zone' },
]

export default function InflectionScannerView({
  onOpenOrderTicket,
  onNavigateToTerminal,
  onNavigateToDebate,
}) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)
  const startActivity = useChatStore((s) => s.startActivity)
  const stopActivity = useChatStore((s) => s.stopActivity)
  const { getTicker, connectionState } = useRealtimeMarket()
  const isLiveConnected = connectionState === 'live' || connectionState === 'connected'

  // Scanner State
  const [universe, setUniverse] = useState('multibagger_hunters')
  const [universesList, setUniversesList] = useState([])
  const [archetypeFilter, setArchetypeFilter] = useState('ALL')
  const [timingFilter, setTimingFilter] = useState('ALL')
  const [minTurnoverCr, setMinTurnoverCr] = useState(0.5) // ₹50L median 20D turnover floor
  const [capTierFilter, setCapTierFilter] = useState('ALL') // 'ALL' | 'LARGE' | 'MID' | 'SMALL' | 'MICRO'
  const [sectorFilter, setSectorFilter] = useState('ALL') // 'ALL' | Specific sector name
  const [minScoreFilter, setMinScoreFilter] = useState(0) // 0 | 50 | 65 | 75
  const [filterCoilingOnly, setFilterCoilingOnly] = useState(false)
  const [filterVolumeSurge, setFilterVolumeSurge] = useState(false)
  const [filterMinerviniOnly, setFilterMinerviniOnly] = useState(false)
  const [filterExcludeUCLocked, setFilterExcludeUCLocked] = useState(false)
  const [filterHighRR, setFilterHighRR] = useState(false)
  const [minScore, setMinScore] = useState(50)
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState('table') // 'table' | 'cards'
  const [sortColumn, setSortColumn] = useState('inflection_score')
  const [sortDirection, setSortDirection] = useState('desc')

  // Multi-Horizon & Incubation Pipeline State
  const [horizonFilter, setHorizonFilter] = useState('ALL') // 'ALL' | 'SHORT_TERM' | 'MID_TERM' | 'LONG_TERM'
  const [activeMainTab, setActiveMainTab] = useState('scanner') // 'scanner' | 'incubation'
  const [incubatedCandidates, setIncubatedCandidates] = useState([])
  const [isLoadingIncubation, setIsLoadingIncubation] = useState(false)
  const [incubationNotice, setIncubationNotice] = useState('')
  const [centuryCandidates, setCenturyCandidates] = useState([])
  const [isLoadingCentury, setIsLoadingCentury] = useState(false)
  const [centuryUniverse, setCenturyUniverse] = useState('microcap250')
  const [isSyncingMarket, setIsSyncingMarket] = useState(false)
  const [syncMarketMsg, setSyncMarketMsg] = useState('')

  // Century Compounder Search, Filter & Tabular Sorting State
  const [centurySearchQuery, setCenturySearchQuery] = useState('')
  const [centuryTierFilter, setCenturyTierFilter] = useState('ALL')
  const [centuryDirectiveFilter, setCenturyDirectiveFilter] = useState('ALL')
  const [centuryMinScore, setCenturyMinScore] = useState(0)
  const [centurySortColumn, setCenturySortColumn] = useState('century_score')
  const [centurySortDirection, setCenturySortDirection] = useState('desc')
  const [centuryViewMode, setCenturyViewMode] = useState('table') // 'table' | 'cards'

  // Scan Data & Loading
  const [isScanning, setIsScanning] = useState(false)
  const [scanResult, setScanResult] = useState(null)
  const [lastScanTime, setLastScanTime] = useState('')

  // Local SQLite EOD Store Batch Sync State
  const [isSyncingEod, setIsSyncingEod] = useState(false)
  const [syncStatusMsg, setSyncStatusMsg] = useState('')
  const [storeStats, setStoreStats] = useState(null)

  // AI Decision Matrix Drawer State
  const [activeCandidate, setActiveCandidate] = useState(null)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const [decisionLoading, setDecisionLoading] = useState(false)
  const [decisionMatrix, setDecisionMatrix] = useState(null)
  const [activeDrawerTab, setActiveDrawerTab] = useState('what') // 'what'|'where'|'when'|'how'|'correlations'|'invalidation'

  // Interactive Position Sizer State in Drawer
  const [sizerCapital, setSizerCapital] = useState(500000)
  const [sizerRiskPct, setSizerRiskPct] = useState(1.5)

  // Interactive Dot-Connecting Chat State in Drawer
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatScrollRef = useRef(null)

  const scanAbortRef = useRef(null)

  // ── 1. Load Universes & Store Diagnostics on Mount ────────────────────
  const loadStoreStats = async () => {
    try {
      const res = await call('/skills/eod_store_status')
      if (res?.data) {
        setStoreStats(res.data)
      }
    } catch (err) {
      console.error('Failed to load store statistics:', err)
    }
  }

  useEffect(() => {
    async function loadUniverses() {
      try {
        const res = await call('/skills/inflection_universes')
        if (res?.data?.universes) {
          setUniversesList(res.data.universes)
        }
      } catch (err) {
        console.error('Failed to load inflection universes:', err)
      }
    }
    loadUniverses()
    loadStoreStats()
    return () => {
      if (scanAbortRef.current) {
        try { scanAbortRef.current.abort() } catch {}
      }
    }
  }, [])

  // ── 2. Run Inflection Scan ──────────────────────────────────────────
  const executeScan = async (
    targetUniverse = universe,
    overrideTurnover = minTurnoverCr,
    overrideCap = capTierFilter,
    force = false
  ) => {
    if (isScanning && !force) {
      return
    }
    if (scanAbortRef.current) {
      try { scanAbortRef.current.abort() } catch {}
    }
    const abortCtrl = new AbortController()
    scanAbortRef.current = abortCtrl
    setIsScanning(true)

    startActivity({
      title: 'Inflection & Multibagger Radar',
      details: `Screening ${targetUniverse} across quantitative engines (Floor: ₹${overrideTurnover} Cr)...`,
      type: 'quant',
      targetView: 'scanner',
      cancelFn: () => {
        try { abortCtrl.abort() } catch {}
        setIsScanning(false)
        stopActivity()
      },
    })

    try {
      const res = await call(
        '/skills/inflection_scan',
        {
          universe: targetUniverse,
          archetype: 'ALL',
          timing: 'ALL',
          horizon: horizonFilter,
          min_score: 45,
          max_results: 100,
          min_turnover_cr: overrideTurnover,
          cap_tier: overrideCap,
          use_local_cache: true,
          sync_missing: false,
          refresh: force,
        },
        { timeoutMs: 120000, signal: abortCtrl.signal }
      )
      const resultData = res?.data ?? res
      setScanResult(resultData)
      setLastScanTime(new Date().toLocaleTimeString('en-IN', { hour12: false }))
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Inflection scan failed:', err)
      }
    } finally {
      if (scanAbortRef.current === abortCtrl) {
        setIsScanning(false)
        stopActivity()
      }
    }
  }

  // ── 2b. Local SQLite EOD Batch Sync ─────────────────────────────────
  const executeEodSync = async () => {
    if (isSyncingEod) return
    setIsSyncingEod(true)
    setSyncStatusMsg(`Syncing historical daily bars for ${universe} into local SQLite store...`)

    try {
      const res = await call('/skills/inflection_sync', {
        universe: universe,
        force: false,
      })
      const data = res?.data ?? res
      if (data.status === 'UP_TO_DATE') {
        setSyncStatusMsg(`✓ Local EOD store already up-to-date (${data.already_cached || 0} stocks)`)
      } else {
        setSyncStatusMsg(
          `✓ Synced ${data.synced_count || 0} stocks (${data.failed_count || 0} failed) in ${data.duration_sec || 0}s`
        )
        // Auto precompute inflection setups and instant load
        try {
          await call('/skills/inflection_precompute', { universe: universe, min_turnover_cr: minTurnoverCr })
        } catch (e) {
          console.warn('[InflectionScanner] Auto precompute background warning:', e)
        }
        await executeScan(universe, minTurnoverCr, capTierFilter, false)
      }
      loadStoreStats()
    } catch (err) {
      console.error('EOD sync failed:', err)
      setSyncStatusMsg('⚠️ EOD sync failed. Check network or try again.')
    } finally {
      setIsSyncingEod(false)
      loadStoreStats()
      setTimeout(() => setSyncStatusMsg(''), 6000)
    }
  }

  // Note: Scanning is triggered manually by user via 'Scan Market' / 'Rescan' buttons

  // Incubation Pipeline Lifecycle
  const loadIncubationPipeline = async () => {
    setIsLoadingIncubation(true)
    try {
      const res = await call('/skills/incubation_pipeline', {
        horizon: horizonFilter,
        cycle_state: 'ALL',
      })
      if (res?.data?.candidates) {
        setIncubatedCandidates(res.data.candidates)
      }
    } catch (err) {
      console.error('Failed to load incubation pipeline:', err)
    } finally {
      setIsLoadingIncubation(false)
    }
  }

  useEffect(() => {
    loadIncubationPipeline()
  }, [])

  useEffect(() => {
    if (activeMainTab === 'incubation') {
      loadIncubationPipeline()
    } else if (activeMainTab === 'century') {
      loadCenturyCompounders()
    }
  }, [activeMainTab, horizonFilter])

  const loadCenturyCompounders = async (universeToUse, refresh = false) => {
    setIsLoadingCentury(true)
    try {
      const u = universeToUse || centuryUniverse
      const res = await call('/skills/century_compounders', {
        universe: u,
        min_score: 60,
        top_n: 25,
        use_cache: !refresh,
        refresh: refresh,
      })
      const cands = res?.data?.candidates || res?.candidates || []
      setCenturyCandidates(cands)
    } catch (err) {
      console.error('Failed to load century compounders:', err)
    } finally {
      setIsLoadingCentury(false)
    }
  }

  const handleSyncEntireMarket = async () => {
    setIsSyncingMarket(true)
    setSyncMarketMsg(`Syncing entire ${centuryUniverse} market into persistent SQLite store...`)
    try {
      const res = await call(
        '/skills/century_sync_market',
        {
          universe: centuryUniverse,
        },
        { timeoutMs: 120000 }
      )
      const data = res?.data || res
      setSyncMarketMsg(`✓ Synced ${data.precomputed_count || 0} stocks into SQLite in ${data.duration_sec || 0}s!`)
      await loadCenturyCompounders(centuryUniverse)
    } catch (err) {
      console.error('Market batch sync failed:', err)
      setSyncMarketMsg('⚠️ Batch market sync failed. Check server logs.')
    } finally {
      setIsSyncingMarket(false)
      setTimeout(() => setSyncMarketMsg(''), 8000)
    }
  }

  const handleAddToIncubation = async (candidate, e) => {
    if (e) e.stopPropagation()
    try {
      const payload = {
        symbol: candidate.symbol,
        name: candidate.name,
        sector: candidate.sector,
        horizon: candidate.horizon || 'MID_TERM',
        cycle_state: candidate.cycle_state || 'COILING_PIVOT',
        eta_days: candidate.eta_days || 3,
        eta_label: candidate.eta_label || '2–5 Sessions',
        entry_pivot: candidate.entry_price || candidate.ltp,
        current_price: candidate.ltp,
        stop_loss: candidate.stop_loss,
        target_1: candidate.target_1,
        target_2: candidate.target_2,
        target_moonshot: candidate.target_moonshot,
        risk_reward_ratio: candidate.risk_reward_ratio || 2.5,
        conviction_score: candidate.inflection_score || 75,
        primary_archetype: candidate.primary_archetype || 'VCP_PIVOT_BREAKOUT',
        catalyst_badges: candidate.catalyst_badges || [],
        catalyst_summary: candidate.catalyst_summary || '',
      }
      await call('/skills/incubation_add', payload)
      setIncubationNotice(`📌 ${candidate.symbol} retained in Incubation Pipeline!`)
      setTimeout(() => setIncubationNotice(''), 4000)
      loadIncubationPipeline()
    } catch (err) {
      console.error('Failed to add to incubation:', err)
    }
  }

  const handleRemoveFromIncubation = async (symbol, e) => {
    if (e) e.stopPropagation()
    try {
      await call('/skills/incubation_remove', { symbol })
      setIncubatedCandidates((prev) => prev.filter((x) => x.symbol !== symbol))
    } catch (err) {
      console.error('Failed to remove from incubation:', err)
    }
  }

  const handleEvaluateIncubation = async () => {
    setIsLoadingIncubation(true)
    try {
      const res = await call('/skills/incubation_evaluate', {})
      const d = res?.data || {}
      setIncubationNotice(`Evaluated ${d.total_evaluated || 0} setups. Triggered: ${d.triggered_breakouts?.length || 0}`)
      setTimeout(() => setIncubationNotice(''), 5000)
      loadIncubationPipeline()
    } catch (err) {
      console.error('Failed to evaluate incubation:', err)
    } finally {
      setIsLoadingIncubation(false)
    }
  }

  // ── 3. Open AI Decision Matrix Drawer ───────────────────────────────
  const openDecisionDrawer = async (candidate) => {
    setActiveCandidate(candidate)
    setIsDrawerOpen(true)
    setDecisionLoading(true)
    setDecisionMatrix(null)
    setChatMessages([
      {
        role: 'system',
        text: `Connected to ${candidate.symbol} Inflection Copilot. 5W+H Decision Matrix active. Ask any dot-connecting question below.`,
      },
    ])

    try {
      const res = await call('/skills/inflection_decision', {
        symbol: candidate.symbol,
        exchange: 'NSE',
      })
      const data = res?.data ?? res
      setDecisionMatrix(data)
    } catch (err) {
      console.error('Failed to fetch AI decision matrix:', err)
    } finally {
      setDecisionLoading(false)
    }
  }

  // ── 4. Interactive Drawer Chat ───────────────────────────────────────
  const handleSendDrawerChat = async (overrideText = null) => {
    const textToSend = overrideText || chatInput.trim()
    if (!textToSend || !activeCandidate || chatLoading) return

    const newMsgs = [...chatMessages, { role: 'user', text: textToSend }]
    setChatMessages(newMsgs)
    if (!overrideText) setChatInput('')
    setChatLoading(true)

    try {
      const res = await call('/skills/inflection_chat', {
        symbol: activeCandidate.symbol,
        question: textToSend,
        matrix: decisionMatrix,
      })
      const ans = res?.data?.answer || res?.answer || 'Analysis complete.'
      setChatMessages([...newMsgs, { role: 'assistant', text: ans }])
    } catch (err) {
      setChatMessages([
        ...newMsgs,
        { role: 'assistant', text: '⚠️ Unable to process query. Please try again.' },
      ])
    } finally {
      setChatLoading(false)
    }
  }

  // Auto-scroll chat
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
    }
  }, [chatMessages])

  // Close drawer on ESC
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isDrawerOpen) {
        setIsDrawerOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isDrawerOpen])

  // ── 5. Available Sectors & Counts ──────────────────────────────────
  const availableSectors = useMemo(() => {
    if (!scanResult?.candidates) return []
    const counts = {}
    scanResult.candidates.forEach((c) => {
      if (c.sector) {
        counts[c.sector] = (counts[c.sector] || 0) + 1
      }
    })
    return Object.entries(counts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
  }, [scanResult])

  const archetypeCounts = useMemo(() => {
    const counts = { ALL: scanResult?.candidates?.length || 0 }
    scanResult?.candidates?.forEach((c) => {
      if (c.primary_archetype) {
        counts[c.primary_archetype] = (counts[c.primary_archetype] || 0) + 1
      }
    })
    return counts
  }, [scanResult])

  const timingCounts = useMemo(() => {
    const counts = { ALL: scanResult?.candidates?.length || 0 }
    scanResult?.candidates?.forEach((c) => {
      if (c.timing_state) {
        counts[c.timing_state] = (counts[c.timing_state] || 0) + 1
      }
    })
    return counts
  }, [scanResult])

  const horizonCounts = useMemo(() => {
    const counts = { ALL: scanResult?.candidates?.length || 0 }
    scanResult?.candidates?.forEach((c) => {
      const h = (c.horizon || 'MID_TERM').toUpperCase()
      counts[h] = (counts[h] || 0) + 1
    })
    return counts
  }, [scanResult])

  const activeFilterCount = useMemo(() => {
    let count = 0
    if (searchQuery.trim()) count++
    if (horizonFilter !== 'ALL') count++
    if (archetypeFilter !== 'ALL') count++
    if (timingFilter !== 'ALL') count++
    if (capTierFilter !== 'ALL') count++
    if (sectorFilter !== 'ALL') count++
    if (minScoreFilter > 0) count++
    if (filterCoilingOnly) count++
    if (filterVolumeSurge) count++
    if (filterMinerviniOnly) count++
    if (filterExcludeUCLocked) count++
    if (filterHighRR) count++
    return count
  }, [
    searchQuery,
    horizonFilter,
    archetypeFilter,
    timingFilter,
    capTierFilter,
    sectorFilter,
    minScoreFilter,
    filterCoilingOnly,
    filterVolumeSurge,
    filterMinerviniOnly,
    filterExcludeUCLocked,
    filterHighRR,
  ])

  const resetAllFilters = () => {
    setSearchQuery('')
    setHorizonFilter('ALL')
    setArchetypeFilter('ALL')
    setTimingFilter('ALL')
    setCapTierFilter('ALL')
    setSectorFilter('ALL')
    setMinScoreFilter(0)
    setFilterCoilingOnly(false)
    setFilterVolumeSurge(false)
    setFilterMinerviniOnly(false)
    setFilterExcludeUCLocked(false)
    setFilterHighRR(false)
  }

  // ── 5b. Multi-Criteria Filtering and Column Sorting ──────────────────
  const filteredCandidates = useMemo(() => {
    if (!scanResult?.candidates) return []
    let list = [...scanResult.candidates]

    // 1. Multi-field text search
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      list = list.filter(
        (c) =>
          (c.symbol && c.symbol.toLowerCase().includes(q)) ||
          (c.name && c.name.toLowerCase().includes(q)) ||
          (c.sector && c.sector.toLowerCase().includes(q)) ||
          (c.archetype_label && c.archetype_label.toLowerCase().includes(q)) ||
          (c.timing_label && c.timing_label.toLowerCase().includes(q))
      )
    }

    // 2. Archetype filter
    if (archetypeFilter && archetypeFilter !== 'ALL') {
      list = list.filter((c) => c.primary_archetype === archetypeFilter)
    }

    // 2b. Horizon filter (Short, Mid, Long Multibagger)
    if (horizonFilter && horizonFilter !== 'ALL') {
      list = list.filter((c) => (c.horizon || 'MID_TERM').toUpperCase() === horizonFilter)
    }

    // 3. Timing state filter
    if (timingFilter && timingFilter !== 'ALL') {
      list = list.filter((c) => c.timing_state === timingFilter)
    }

    // 4. Market Cap Tier filter
    if (capTierFilter && capTierFilter !== 'ALL') {
      list = list.filter((c) => (c.cap_tier || '').toUpperCase() === capTierFilter)
    }

    // 5. Sector filter
    if (sectorFilter && sectorFilter !== 'ALL') {
      list = list.filter((c) => c.sector === sectorFilter)
    }

    // 6. Min Score / Conviction filter
    if (minScoreFilter > 0) {
      list = list.filter((c) => (c.inflection_score ?? 0) >= minScoreFilter)
    }

    // 7. Quick Setup Condition Toggles
    if (filterCoilingOnly) {
      list = list.filter((c) => c.squeeze_state === 'COILING' || c.timing_state === 'COILING_IMMINENT')
    }
    if (filterVolumeSurge) {
      list = list.filter((c) => (c.rvol_20d ?? 0) >= 1.5)
    }
    if (filterMinerviniOnly) {
      list = list.filter((c) => (c.trend_template_passed ?? 0) >= 7)
    }
    if (filterExcludeUCLocked) {
      list = list.filter((c) => c.circuit_state !== 'UPPER_CIRCUIT_LOCKED')
    }
    if (filterHighRR) {
      list = list.filter((c) => (c.risk_reward_ratio ?? 0) >= 2.5)
    }

    // 8. Robust Type-Aware Column Sorting
    list.sort((a, b) => {
      let aVal = a[sortColumn]
      let bVal = b[sortColumn]

      if (sortColumn === 'primary_archetype') {
        aVal = a.archetype_label || a.primary_archetype || ''
        bVal = b.archetype_label || b.primary_archetype || ''
      } else if (sortColumn === 'timing_state') {
        const priority = { TRIGGER_NOW: 3, COILING_IMMINENT: 2, PULLBACK_RETEST: 1 }
        aVal = priority[a.timing_state] || 0
        bVal = priority[b.timing_state] || 0
      }

      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }

      const aStr = String(aVal).toLowerCase()
      const bStr = String(bVal).toLowerCase()
      const cmp = aStr.localeCompare(bStr)
      return sortDirection === 'asc' ? cmp : -cmp
    })

    return list
  }, [
    scanResult,
    searchQuery,
    horizonFilter,
    archetypeFilter,
    timingFilter,
    capTierFilter,
    sectorFilter,
    minScoreFilter,
    filterCoilingOnly,
    filterVolumeSurge,
    filterMinerviniOnly,
    filterExcludeUCLocked,
    filterHighRR,
    sortColumn,
    sortDirection,
  ])

  const handleSort = (col) => {
    if (sortColumn === col) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortColumn(col)
      const isNumeric = [
        'inflection_score',
        'ltp',
        'day_change_pct',
        'rvol_20d',
        'trend_template_passed',
        'entry_price',
        'risk_reward_ratio',
      ].includes(col)
      setSortDirection(isNumeric ? 'desc' : 'asc')
    }
  }

  const SCANNER_HEADER_METRIC_MAP = {
    inflection_score: 'century_score',
    primary_archetype: 'vcp_pivot',
    timing_state: 'timing_state',
    rvol_20d: 'rvol',
    trend_template_passed: 'minervini_trend_template',
    entry_price: 'fair_value_zone',
    risk_reward_ratio: 'risk_reward_ratio',
  }

  // Interactive sortable header renderer
  const renderHeader = (colKey, label, align = 'left', extraClass = '', metricKey = null) => {
    const isSorted = sortColumn === colKey
    const dir = sortDirection
    const resolvedMetric = metricKey || SCANNER_HEADER_METRIC_MAP[colKey]
    return (
      <th
        key={colKey}
        onClick={() => handleSort(colKey)}
        className={`py-2 px-2 cursor-pointer select-none transition-all group ${
          align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
        } ${
          isSorted
            ? 'text-amber-600 dark:text-amber-400 font-bold bg-amber-500/10 dark:bg-amber-400/10 rounded-md'
            : 'text-muted hover:text-text hover:bg-black/[0.04] dark:hover:bg-white/[0.05] rounded-md'
        } ${extraClass}`}
        aria-sort={isSorted ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
        title={`Sort by ${label} (${isSorted ? (dir === 'asc' ? 'Ascending' : 'Descending') : 'Click to sort'})`}
      >
        <div
          className={`inline-flex items-center gap-1.5 ${
            align === 'right' ? 'justify-end' : align === 'center' ? 'justify-center' : 'justify-start'
          }`}
        >
          <span>{label}</span>
          <span
            className={`text-[9px] font-mono transition-all ${
              isSorted
                ? 'opacity-100 text-amber-600 dark:text-amber-400 font-bold'
                : 'opacity-30 group-hover:opacity-100 group-hover:text-amber-500'
            }`}
          >
            {isSorted ? (dir === 'asc' ? '▲' : '▼') : '⇅'}
          </span>
          {resolvedMetric && (
            <span onClick={(e) => e.stopPropagation()} className="inline-flex">
              <HelpHint metricKey={resolvedMetric} size="xs" />
            </span>
          )}
        </div>
      </th>
    )
  }

  // Position Sizing Calculations
  const calculatedPosition = useMemo(() => {
    if (!activeCandidate) return { shares: 0, capital: 0, riskAmount: 0 }
    const riskAmt = sizerCapital * (sizerRiskPct / 100)
    const riskPerShare = Math.max(0.5, activeCandidate.entry_price - activeCandidate.stop_loss)
    const shares = Math.max(1, Math.floor(riskAmt / riskPerShare))
    const totalCap = shares * activeCandidate.entry_price
    return {
      shares,
      capital: totalCap,
      riskAmount: shares * riskPerShare,
      heatPct: ((totalCap / sizerCapital) * 100).toFixed(1),
    }
  }, [activeCandidate, sizerCapital, sizerRiskPct])

  // Summary Metrics
  const summaryMetrics = useMemo(() => {
    const list = scanResult?.candidates || []
    const total = list.length
    const highConviction = list.filter((c) => c.inflection_score >= 75).length
    const coiling = list.filter((c) => c.squeeze_state === 'COILING').length
    const triggerNow = list.filter((c) => c.timing_state === 'TRIGGER_NOW').length
    const rrList = list.filter((c) => c.risk_reward_ratio != null)
    const avgRR =
      rrList.length > 0
        ? (rrList.reduce((acc, c) => acc + c.risk_reward_ratio, 0) / rrList.length).toFixed(1)
        : null
    const topSector = scanResult?.top_sectors?.[0]?.sector || 'Mixed'

    return { total, highConviction, coiling, triggerNow, avgRR, topSector }
  }, [scanResult])

  // Render Cycle Incubation Pipeline Board
  const renderIncubationBoard = () => {
    const displayed = horizonFilter === 'ALL'
      ? incubatedCandidates
      : incubatedCandidates.filter((c) => (c.horizon || 'MID_TERM').toUpperCase() === horizonFilter)

    return (
      <div className="flex flex-col gap-4 font-ui">
        {/* Banner / Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl border border-border bg-surface shadow-xs">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-500/15 border border-purple-500/30 flex items-center justify-center text-xl">
              📌
            </div>
            <div>
              <h2 className="text-sm font-bold text-text flex items-center gap-2">
                <span>Cycle Incubation Pipeline</span>
                <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-purple-500/20 text-purple-600 dark:text-purple-400 font-bold">
                  {displayed.length} Active Candidates
                </span>
              </h2>
              <p className="text-xs text-muted">
                Persistent quantitative incubation radar tracking setups across their cycle ETA until breakout ignition.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {incubationNotice && (
              <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-lg">
                {incubationNotice}
              </span>
            )}
            <button
              type="button"
              onClick={handleEvaluateIncubation}
              disabled={isLoadingIncubation}
              className="text-xs font-bold px-3 py-1.5 rounded-lg border border-purple-500/40 bg-purple-500/15 text-purple-600 dark:text-purple-400 hover:bg-purple-500/25 flex items-center gap-1.5 transition-all cursor-pointer shadow-xs"
              title="Evaluate price milestones & detect breakouts"
            >
              <span>🔄</span>
              <span>{isLoadingIncubation ? 'Evaluating...' : 'Evaluate Cycles Now'}</span>
            </button>
          </div>
        </div>

        {/* Empty State */}
        {displayed.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-80 rounded-2xl border border-dashed border-border bg-surface/50 text-center p-6">
            <span className="text-4xl mb-3">🌱</span>
            <h3 className="text-sm font-bold text-text">No Candidates Retained in Incubation</h3>
            <p className="text-xs text-muted mt-1.5 max-w-md">
              When screening Short, Mid, or Long-Term Multibaggers in the Radar, click the{' '}
              <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 font-mono">📌</span>{' '}
              button on any candidate to retain and monitor it until its breakout moment arrives.
            </p>
            <button
              type="button"
              onClick={() => setActiveMainTab('scanner')}
              className="mt-4 text-xs font-bold px-4 py-2 rounded-lg border border-gold/40 bg-gold/15 text-amber-600 dark:text-amber-400 hover:bg-gold/25 cursor-pointer transition-all"
            >
              📡 Return to Inflection Radar
            </button>
          </div>
        ) : (
          /* Table of Incubated Setups */
          <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-card">
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-border bg-panel text-[10px] font-mono text-muted uppercase tracking-wider">
                  <th className="py-2.5 px-3">Symbol / Horizon</th>
                  <th className="py-2.5 px-2">Cycle State / ETA</th>
                  <th className="py-2.5 px-2 text-right">Pivot / Last Price</th>
                  <th className="py-2.5 px-2 text-right">Stop Loss</th>
                  <th className="py-2.5 px-2 text-left">Targets (T1 / T2 / 🚀T3)</th>
                  <th className="py-2.5 px-2 text-center">Score & Payoff</th>
                  <th className="py-2.5 px-2 text-left">Catalyst Badges</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {displayed.map((c) => {
                  const isTriggerReady = c.cycle_state === 'TRIGGER_READY'
                  const isInvalidated = c.cycle_state === 'CYCLE_INVALIDATED'
                  return (
                    <tr
                      key={c.symbol}
                      className="hover:bg-purple-500/[0.04] transition-all group cursor-pointer"
                      onClick={() => openDecisionDrawer(c)}
                    >
                      {/* Symbol & Horizon */}
                      <td className="py-2.5 px-3">
                        <div className="flex flex-col">
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold text-text text-xs group-hover:text-purple-400 transition-colors">
                              {c.symbol}
                            </span>
                            <span
                              className={`text-[8.5px] font-bold px-1.5 py-0.2 rounded border uppercase font-mono ${
                                c.horizon === 'LONG_TERM'
                                  ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                                  : c.horizon === 'SHORT_TERM'
                                  ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/30'
                                  : 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30'
                              }`}
                            >
                              {c.horizon === 'LONG_TERM' ? '💎 MULTIBAGGER' : c.horizon === 'SHORT_TERM' ? '⚡ SHORT-TERM' : '📈 MID-TERM'}
                            </span>
                          </div>
                          <span className="text-[10px] text-muted truncate max-w-[130px] font-ui">
                            {c.name || c.sector}
                          </span>
                        </div>
                      </td>

                      {/* Cycle State & ETA */}
                      <td className="py-2.5 px-2">
                        <div className="flex flex-col gap-0.5">
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded-full border inline-block max-w-fit ${
                              isTriggerReady
                                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/40 animate-pulse font-bold'
                                : isInvalidated
                                ? 'bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/30'
                                : 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30'
                            }`}
                          >
                            {c.cycle_state.replace('_', ' ')}
                          </span>
                          <span className="text-[9.5px] text-muted">
                            {c.eta_label} ({c.days_in_incubation || 0}d inc)
                          </span>
                        </div>
                      </td>

                      {/* Pivot vs Last Price */}
                      <td className="py-2.5 px-2 text-right">
                        <div className="flex flex-col items-end">
                          <span className="font-bold text-text">₹{c.entry_pivot.toFixed(1)}</span>
                          <span className="text-[10px] text-muted">
                            LTP: ₹{c.current_price.toFixed(1)}
                          </span>
                        </div>
                      </td>

                      {/* Stop Loss */}
                      <td className="py-2.5 px-2 text-right text-rose-600 dark:text-rose-400 font-medium">
                        ₹{c.stop_loss.toFixed(1)}
                      </td>

                      {/* Targets */}
                      <td className="py-2.5 px-2">
                        <div className="flex items-center gap-1.5 text-[10.5px]">
                          <span className="text-emerald-600 dark:text-emerald-400 font-bold" title="Target 1 (+2R)">
                            T1: ₹{c.target_1.toFixed(1)}
                          </span>
                          <span className="text-muted text-[8px]">•</span>
                          <span className="text-amber-600 dark:text-amber-400 font-bold" title="Target 2 (+3.5R)">
                            T2: ₹{c.target_2.toFixed(1)}
                          </span>
                          <span className="text-muted text-[8px]">•</span>
                          <span className="text-purple-600 dark:text-purple-400 font-bold flex items-center gap-0.5" title="Target Moonshot (+6.5R)">
                            <span>🚀</span>₹{c.target_moonshot.toFixed(1)}
                          </span>
                        </div>
                      </td>

                      {/* Score & Payoff */}
                      <td className="py-2.5 px-2 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-bold text-[10px]">
                            {c.conviction_score}
                          </span>
                          <span className="text-[10px] text-muted">
                            1:{c.risk_reward_ratio}
                          </span>
                        </div>
                      </td>

                      {/* Catalyst Badges */}
                      <td className="py-2.5 px-2 font-ui">
                        <div className="flex flex-wrap gap-1 max-w-[200px]">
                          {c.catalyst_badges && c.catalyst_badges.length > 0 ? (
                            c.catalyst_badges.map((b, i) => (
                              <span
                                key={i}
                                className="text-[8.5px] px-1.5 py-0.5 rounded bg-surface border border-border text-muted font-mono"
                              >
                                {b}
                              </span>
                            ))
                          ) : (
                            <span className="text-[9px] text-muted">Technical setup</span>
                          )}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => openDecisionDrawer(c)}
                            className="p-1 rounded hover:bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30 transition-all cursor-pointer"
                            title="AI 5W+H Decision Matrix"
                          >
                            🧠
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (onOpenOrderTicket) {
                                onOpenOrderTicket({
                                  symbol: c.symbol,
                                  exchange: 'NSE',
                                  price: c.current_price || c.entry_pivot,
                                  stopLoss: c.stop_loss,
                                  target: c.target_1,
                                  target2: c.target_2,
                                  targetMoonshot: c.target_moonshot,
                                  _priceSource: 'INCUBATION_PIVOT',
                                })
                              }
                            }}
                            className="p-1 rounded hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 transition-all cursor-pointer"
                            title="Open Order Ticket"
                          >
                            ⚡
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleRemoveFromIncubation(c.symbol, e)}
                            className="p-1 rounded hover:bg-rose-500/20 text-rose-500 border border-rose-500/30 transition-all cursor-pointer"
                            title="Remove from Incubation"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }

  // ── Century Compounder Multi-Criteria Filtering and Column Sorting ──────
  const filteredCenturyCandidates = useMemo(() => {
    if (!Array.isArray(centuryCandidates)) return []
    let list = [...centuryCandidates]

    // 1. Text Search across Symbol, Badges, Summary, Tier, Directive
    if (centurySearchQuery.trim()) {
      const q = centurySearchQuery.toLowerCase().trim()
      list = list.filter((c) => {
        const sym = (c.symbol || '').toLowerCase()
        const tier = (c.compounder_tier || '').toLowerCase()
        const summary = (c.summary || '').toLowerCase()
        const directive = (c.anti_fomo?.action_directive || '').toLowerCase()
        const badges = Array.isArray(c.catalyst_badges)
          ? c.catalyst_badges.join(' ').toLowerCase()
          : ''
        return (
          sym.includes(q) ||
          tier.includes(q) ||
          summary.includes(q) ||
          directive.includes(q) ||
          badges.includes(q)
        )
      })
    }

    // 2. Compounder Tier Filter
    if (centuryTierFilter && centuryTierFilter !== 'ALL') {
      list = list.filter((c) => {
        const t = c.compounder_tier || c.twin_engines?.compounder_tier || ''
        return t === centuryTierFilter
      })
    }

    // 3. Anti-FOMO Directive Filter
    if (centuryDirectiveFilter && centuryDirectiveFilter !== 'ALL') {
      list = list.filter((c) => {
        const d = c.anti_fomo?.action_directive || ''
        return d === centuryDirectiveFilter
      })
    }

    // 4. Min Score Filter
    if (centuryMinScore > 0) {
      list = list.filter((c) => (c.century_score ?? 0) >= centuryMinScore)
    }

    // 5. Column Sorting
    list.sort((a, b) => {
      let aVal = a[centurySortColumn]
      let bVal = b[centurySortColumn]

      if (centurySortColumn === 'total_projected_multiple') {
        aVal = a.twin_engines?.total_projected_multiple ?? 0
        bVal = b.twin_engines?.total_projected_multiple ?? 0
      } else if (centurySortColumn === 'current_market_cap_cr') {
        aVal = a.twin_engines?.current_market_cap_cr ?? 0
        bVal = b.twin_engines?.current_market_cap_cr ?? 0
      } else if (centurySortColumn === 'forecast_pat_cagr_pct') {
        aVal = a.twin_engines?.forecast_pat_cagr_pct ?? 0
        bVal = b.twin_engines?.forecast_pat_cagr_pct ?? 0
      } else if (centurySortColumn === 'current_pe') {
        aVal = a.twin_engines?.current_pe ?? 0
        bVal = b.twin_engines?.current_pe ?? 0
      } else if (centurySortColumn === 'action_directive') {
        aVal = a.anti_fomo?.action_directive ?? ''
        bVal = b.anti_fomo?.action_directive ?? ''
      }

      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return centurySortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }

      const aStr = String(aVal).toLowerCase()
      const bStr = String(bVal).toLowerCase()
      const cmp = aStr.localeCompare(bStr)
      return centurySortDirection === 'asc' ? cmp : -cmp
    })

    return list
  }, [
    centuryCandidates,
    centurySearchQuery,
    centuryTierFilter,
    centuryDirectiveFilter,
    centuryMinScore,
    centurySortColumn,
    centurySortDirection,
  ])

  const handleCenturySort = (col) => {
    if (centurySortColumn === col) {
      setCenturySortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setCenturySortColumn(col)
      const isNumeric = [
        'century_score',
        'total_projected_multiple',
        'current_market_cap_cr',
        'forecast_pat_cagr_pct',
        'current_pe',
        'ltp',
      ].includes(col)
      setCenturySortDirection(isNumeric ? 'desc' : 'asc')
    }
  }

  const resetCenturyFilters = () => {
    setCenturySearchQuery('')
    setCenturyTierFilter('ALL')
    setCenturyDirectiveFilter('ALL')
    setCenturyMinScore(0)
  }

  const activeCenturyFilterCount = useMemo(() => {
    let count = 0
    if (centurySearchQuery.trim()) count++
    if (centuryTierFilter !== 'ALL') count++
    if (centuryDirectiveFilter !== 'ALL') count++
    if (centuryMinScore > 0) count++
    return count
  }, [centurySearchQuery, centuryTierFilter, centuryDirectiveFilter, centuryMinScore])

  const centurySummaryMetrics = useMemo(() => {
    const total = centuryCandidates.length
    const c100x = centuryCandidates.filter((c) => {
      const t = c.compounder_tier || c.twin_engines?.compounder_tier || ''
      return t === '100X_CENTURY' || t === '1000X_POTENTIAL'
    }).length
    const inAccumulate = centuryCandidates.filter(
      (c) => c.anti_fomo?.action_directive === 'ACCUMULATE_FAIR_VALUE'
    ).length
    const multiples = centuryCandidates
      .map((c) => c.twin_engines?.total_projected_multiple)
      .filter((m) => typeof m === 'number' && m > 0)
    const avgMultiple = multiples.length
      ? Math.round(multiples.reduce((a, b) => a + b, 0) / multiples.length)
      : 0
    return { total, c100x, inAccumulate, avgMultiple }
  }, [centuryCandidates])

  const CENTURY_HEADER_METRIC_MAP = {
    century_score: 'century_score',
    total_projected_multiple: 'ten_year_multiple',
    forecast_pat_cagr_pct: 'pat_expansion',
    current_pe: 'pe_rerating',
    ltp: 'fair_value_zone',
    action_directive: 'anti_fomo',
  }

  const renderCenturyHeader = (colKey, label, align = 'left', extraClass = '', metricKey = null) => {
    const isSorted = centurySortColumn === colKey
    const dir = centurySortDirection
    const resolvedMetric = metricKey || CENTURY_HEADER_METRIC_MAP[colKey]
    return (
      <th
        key={colKey}
        onClick={() => handleCenturySort(colKey)}
        className={`py-2 px-2.5 cursor-pointer select-none transition-all group ${
          align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
        } ${
          isSorted
            ? 'text-emerald-600 dark:text-emerald-400 font-bold bg-emerald-500/10 dark:bg-emerald-400/10 rounded-md'
            : 'text-muted hover:text-text hover:bg-black/[0.04] dark:hover:bg-white/[0.05] rounded-md'
        } ${extraClass}`}
        aria-sort={isSorted ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
        title={`Sort by ${label} (${isSorted ? (dir === 'asc' ? 'Ascending' : 'Descending') : 'Click to sort'})`}
      >
        <div
          className={`inline-flex items-center gap-1.5 ${
            align === 'right' ? 'justify-end' : align === 'center' ? 'justify-center' : 'justify-start'
          }`}
        >
          <span>{label}</span>
          <span
            className={`text-[9px] font-mono transition-all ${
              isSorted
                ? 'opacity-100 text-emerald-600 dark:text-emerald-400 font-bold'
                : 'opacity-0 group-hover:opacity-60 text-muted'
            }`}
          >
            {isSorted ? (dir === 'asc' ? '▲' : '▼') : '↕'}
          </span>
          {resolvedMetric && (
            <span onClick={(e) => e.stopPropagation()} className="inline-flex">
              <HelpHint metricKey={resolvedMetric} size="xs" />
            </span>
          )}
        </div>
      </th>
    )
  }

  // Render 100x & 1,000x Century Compounder Discovery Board
  const renderCenturyBoard = () => {
    return (
      <div className="space-y-3 font-ui">
        {/* Banner with Twin Engine explanation & Market-Wide DB Control (Streamlined Compact 38px) */}
        <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 flex flex-col sm:flex-row sm:items-center justify-between gap-2 shadow-xs">
          <div className="flex items-center gap-2 flex-wrap min-w-0">
            <span className="text-lg">💎</span>
            <h3 className="font-bold text-text text-sm whitespace-nowrap">
              100x & 1,000x Century Compounder Terminal
            </h3>
            <span className="inline-flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded-full font-mono bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 font-bold border border-emerald-500/30">
              <span>Twin Engines: PAT Growth × P/E Re-rating</span>
              <HelpHint metricKey="twin_engines" size="xs" />
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-mono bg-panel text-muted border border-border">
              💾 SQLite Cached ({centuryCandidates.length} Active)
            </span>
          </div>

          {/* Fast Trigger Actions */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => loadCenturyCompounders(centuryUniverse, false)}
              disabled={isLoadingCentury || isSyncingMarket}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-xs font-bold text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/30 transition-all cursor-pointer whitespace-nowrap shadow-xs"
              title="Instant query cached compounders in under 50ms"
            >
              <span className={isLoadingCentury ? 'animate-spin' : ''}>⚡</span>
              <span>{isLoadingCentury ? 'Querying...' : 'Instant Query (<50ms)'}</span>
            </button>

            <button
              type="button"
              onClick={() => loadCenturyCompounders(centuryUniverse, true)}
              disabled={isLoadingCentury || isSyncingMarket}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-sky-500/40 bg-sky-500/20 text-xs font-bold text-sky-600 dark:text-sky-400 hover:bg-sky-500/30 transition-all cursor-pointer whitespace-nowrap shadow-xs"
              title="Perform fresh scan of this universe without cache"
            >
              <span className={isLoadingCentury ? 'animate-spin' : ''}>🔄</span>
              <span>{isLoadingCentury ? 'Scanning...' : 'Rescan Market'}</span>
            </button>

            <button
              type="button"
              onClick={handleSyncEntireMarket}
              disabled={isSyncingMarket || isLoadingCentury}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-purple-500/40 bg-purple-500/15 text-xs font-bold text-purple-600 dark:text-purple-400 hover:bg-purple-500/25 transition-all cursor-pointer whitespace-nowrap shadow-xs"
              title="Batch-sync and precompute entire Indian market universe into local SQLite store"
            >
              <span className={isSyncingMarket ? 'animate-spin' : ''}>💾</span>
              <span>{isSyncingMarket ? 'Syncing Market...' : 'Sync Market into DB'}</span>
            </button>
          </div>
        </div>

        {/* Market Sync Feedback Toast */}
        {syncMarketMsg && (
          <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-3 py-1 rounded-lg animate-pulse font-mono">
            {syncMarketMsg}
          </div>
        )}

        {/* ── QUANTITATIVE FILTER TOOLBAR (Unified Dropdowns, Search & Telemetry) ── */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 rounded-lg border border-border bg-panel text-xs">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            {/* Market Universe Dropdown */}
            <select
              value={centuryUniverse}
              onChange={(e) => {
                const newUni = e.target.value
                setCenturyUniverse(newUni)
                loadCenturyCompounders(newUni, false)
              }}
              disabled={isSyncingMarket || isLoadingCentury}
              className="text-xs py-1 px-2.5 rounded-lg bg-surface border border-border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer hover:border-gold/50"
              title="Select target market universe"
            >
              <option value="microcap250">🌱 Microcap 250 (Emerging)</option>
              <option value="smallcap250">🚀 Smallcap 250 (Scale)</option>
              <option value="nifty_total_market">🏛️ Nifty Total Market (750)</option>
              <option value="all_nse_liquid">🇮🇳 All NSE Liquid (~2,100)</option>
              <option value="bse_high_growth">💎 BSE High-Growth</option>
            </select>

            {/* Compounder Tier Dropdown */}
            <div className="flex items-center gap-1">
              <select
                value={centuryTierFilter}
                onChange={(e) => setCenturyTierFilter(e.target.value)}
                className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-emerald-500 transition-colors font-sans cursor-pointer ${
                  centuryTierFilter !== 'ALL'
                    ? 'border-emerald-400 text-emerald-400 font-bold bg-emerald-500/10'
                    : 'border-border hover:border-emerald-500/50'
                }`}
                title="Filter by projected compounding multiple tier"
              >
                <option value="ALL">All Multiples</option>
                <option value="1000X_POTENTIAL">🔥 1000x Potential (500x+)</option>
                <option value="100X_CENTURY">💎 100x Century (75x+)</option>
                <option value="25X_MULTIBAGGER">🚀 25x Multibagger (25x–75x)</option>
                <option value="10X_QUALITY">⚡ 10x Quality (10x–25x)</option>
              </select>
              <HelpHint metricKey="ten_year_multiple" size="xs" />
            </div>

            {/* Anti-FOMO Directive Dropdown */}
            <div className="flex items-center gap-1">
              <select
                value={centuryDirectiveFilter}
                onChange={(e) => setCenturyDirectiveFilter(e.target.value)}
                className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-emerald-500 transition-colors font-sans cursor-pointer ${
                  centuryDirectiveFilter !== 'ALL'
                    ? 'border-emerald-400 text-emerald-400 font-bold bg-emerald-500/10'
                    : 'border-border hover:border-emerald-500/50'
                }`}
                title="Filter by Anti-FOMO execution boundary"
              >
                <option value="ALL">All Anti-FOMO Directives</option>
                <option value="ACCUMULATE_FAIR_VALUE">🟢 Accumulate (Fair Value)</option>
                <option value="WAIT_FOR_PULLBACK">🔴 Wait Pullback (No Chase)</option>
                <option value="PROFIT_SCALING">🟡 Profit Scaling</option>
                <option value="STALK_PIVOT">🟡 Stalk Pivot</option>
              </select>
              <HelpHint metricKey="anti_fomo" size="xs" />
            </div>

            {/* Min Score Dropdown */}
            <div className="flex items-center gap-1">
              <select
                value={centuryMinScore}
                onChange={(e) => setCenturyMinScore(Number(e.target.value))}
                className={`text-xs py-1 px-2 rounded-lg bg-surface border text-text focus:outline-none focus:border-emerald-500 transition-colors font-mono cursor-pointer ${
                  centuryMinScore > 0
                    ? 'border-amber-400 text-amber-300 font-bold bg-amber-500/10'
                    : 'border-border hover:border-emerald-500/50'
                }`}
                title="Filter by minimum Dalal Street compounder score"
              >
                <option value={0}>Score: All</option>
                <option value={60}>Score: 60+</option>
                <option value={70}>Score: 70+</option>
                <option value={80}>Score: 80+ (Elite)</option>
              </select>
              <HelpHint metricKey="century_score" size="xs" />
            </div>

            {/* Search Input */}
            <div className="relative flex items-center">
              <input
                type="text"
                placeholder="🔍 Search..."
                value={centurySearchQuery}
                onChange={(e) => setCenturySearchQuery(e.target.value)}
                className="w-28 sm:w-36 text-xs pl-2.5 pr-6 py-1 rounded-lg bg-surface border border-border text-text placeholder:text-muted focus:outline-none focus:border-emerald-500 transition-colors font-sans"
                title="Search symbol, tier, or catalyst"
              />
              {centurySearchQuery && (
                <button
                  type="button"
                  onClick={() => setCenturySearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-text text-xs cursor-pointer"
                  title="Clear search"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Reset Filters */}
            {activeCenturyFilterCount > 0 && (
              <button
                type="button"
                onClick={resetCenturyFilters}
                className="btn btn-sm btn-ghost text-xs text-rose-400 hover:text-rose-300 border border-rose-500/30 hover:bg-rose-500/10 flex items-center gap-1 font-bold px-2 py-0.5 cursor-pointer"
                title="Reset all filters"
              >
                ✕ Reset Filters
              </button>
            )}

            {/* View Mode Toggle: Table vs Cards */}
            <div className="flex items-center rounded-lg border border-border p-0.5 bg-elevated">
              <button
                type="button"
                onClick={() => setCenturyViewMode('table')}
                className={`text-xs px-2 py-0.5 rounded transition-all cursor-pointer ${
                  centuryViewMode === 'table'
                    ? 'font-bold bg-panel text-emerald-600 dark:text-emerald-400 shadow-xs'
                    : 'text-muted hover:text-text'
                }`}
                title="Century Compounders Table View"
              >
                ☰ Table
              </button>
              <button
                type="button"
                onClick={() => setCenturyViewMode('cards')}
                className={`text-xs px-2 py-0.5 rounded transition-all cursor-pointer ${
                  centuryViewMode === 'cards'
                    ? 'font-bold bg-panel text-emerald-600 dark:text-emerald-400 shadow-xs'
                    : 'text-muted hover:text-text'
                }`}
                title="Century Compounders Cards Matrix"
              >
                ☷ Cards
              </button>
            </div>
          </div>

          {/* Right: Inline Telemetry Metrics */}
          <div className="flex items-center gap-2 font-mono text-[10px] text-muted flex-shrink-0 ml-auto">
            <span>
              Setups: <strong className="text-text">{filteredCenturyCandidates.length}</strong>/{centurySummaryMetrics.total}
            </span>
            <span>·</span>
            <span>
              100x+ Tier: <strong className="text-emerald-500">{centurySummaryMetrics.c100x}</strong>
            </span>
            <span>·</span>
            <span>
              In FV Zone: <strong className="text-cyan-500">{centurySummaryMetrics.inAccumulate}</strong>
            </span>
            <span>·</span>
            <span>
              Avg Multiple: <strong className="text-amber-500">{centurySummaryMetrics.avgMultiple}x</strong>
            </span>
          </div>
        </div>

        {/* ── MAIN CONTENT CONTAINER (Table vs Cards) ── */}
        {isLoadingCentury ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin" />
            <span className="text-xs font-mono text-muted tracking-wider uppercase">
              Computing Twin Engines & Forensic Integrity...
            </span>
          </div>
        ) : centuryCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center gap-2 rounded-xl border border-dashed border-border bg-surface/50 p-6">
            <span className="text-3xl">💎</span>
            <span className="text-sm font-bold text-text">No Candidates in Selected Universe Meeting 100x Criteria</span>
            <p className="text-xs text-muted max-w-md">
              No precomputed compounders meet the threshold for <strong>{centuryUniverse}</strong> yet. Click <strong>Sync Market into DB</strong> to analyze and persist this universe.
            </p>
            <button
              type="button"
              onClick={handleSyncEntireMarket}
              disabled={isSyncingMarket || isLoadingCentury}
              className="mt-2 px-3 py-1.5 rounded-lg border border-purple-500/40 bg-purple-500/20 text-xs font-bold text-purple-600 dark:text-purple-400 hover:bg-purple-500/30 transition-all cursor-pointer shadow-xs"
            >
              {isSyncingMarket ? 'Syncing...' : `💾 Sync ${centuryUniverse} into DB`}
            </button>
          </div>
        ) : filteredCenturyCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center gap-2 rounded-xl border border-dashed border-border bg-surface/50 p-6">
            <span className="text-3xl">🔍</span>
            <span className="text-sm font-bold text-text">No Compounders Matching Filter Criteria</span>
            <p className="text-xs text-muted max-w-md">
              None of the {centuryCandidates.length} setups in {centuryUniverse} match your {activeCenturyFilterCount} active filters.
            </p>
            <button
              type="button"
              onClick={resetCenturyFilters}
              className="mt-2 text-xs font-semibold px-3 py-1.5 rounded-lg border border-border bg-elevated text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/15 transition-all cursor-pointer"
            >
              ✕ Clear All Filters ({centuryCandidates.length} Available)
            </button>
          </div>
        ) : centuryViewMode === 'table' ? (
          /* ── HIGH-DENSITY TABULAR VIEW ──────────────────────────────── */
          <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-card">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-border bg-panel text-[10px] font-mono text-muted uppercase tracking-wider">
                    {renderCenturyHeader('symbol', 'Symbol / MCap', 'left', 'px-3')}
                    {renderCenturyHeader('century_score', 'Score', 'center')}
                    {renderCenturyHeader('total_projected_multiple', '10Y Multiple', 'center')}
                    {renderCenturyHeader('forecast_pat_cagr_pct', 'Engine 1: PAT CAGR', 'left')}
                    {renderCenturyHeader('current_pe', 'Engine 2: P/E Re-rating', 'left')}
                    {renderCenturyHeader('ltp', 'LTP & Fair Value', 'left')}
                    {renderCenturyHeader('action_directive', 'Anti-FOMO State', 'left')}
                    <th className="py-2 px-2 text-left font-mono">Key Catalysts</th>
                    <th className="py-2 px-3 text-right text-muted font-mono">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60 font-mono">
                  {filteredCenturyCandidates.map((c) => {
                    const te = c.twin_engines || {}
                    const af = c.anti_fomo || {}
                    const is100x = (c.compounder_tier === '100X_CENTURY' || c.compounder_tier === '1000X_POTENTIAL')
                    return (
                      <tr
                        key={c.symbol}
                        className="hover:bg-emerald-500/[0.04] dark:hover:bg-white/[0.04] transition-all group cursor-pointer"
                        onClick={() => openDecisionDrawer({
                          symbol: c.symbol,
                          name: c.symbol,
                          sector: 'Century Compounder',
                          ltp: c.ltp,
                          inflection_score: c.century_score,
                          primary_archetype: 'STAGE_1_TO_2_EXPANSION',
                          entry_price: af.fair_value_anchor || c.ltp,
                          stop_loss: af.invalidation_stop,
                          target_1: (af.fair_value_anchor || c.ltp) * 2.0,
                          target_2: (af.fair_value_anchor || c.ltp) * 4.0,
                          target_moonshot: (af.fair_value_anchor || c.ltp) * 10.0,
                          risk_reward_ratio: 4.5,
                        })}
                      >
                        {/* Symbol / MCap */}
                        <td className="py-2 px-3">
                          <div className="flex items-center gap-2">
                            <span className="text-base">{is100x ? '💎' : '🚀'}</span>
                            <div>
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span className="font-bold text-text text-xs group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors">
                                  {c.symbol}
                                </span>
                                <span className={`text-[8.5px] font-bold px-1.5 py-0.2 rounded border uppercase font-mono ${
                                  is100x
                                    ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
                                    : 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                                }`}>
                                  {c.compounder_tier || 'COMPOUNDER'}
                                </span>
                              </div>
                              <div className="text-[10px] text-muted font-sans mt-0.5">
                                MCap: ₹{te.current_market_cap_cr ? te.current_market_cap_cr.toLocaleString() : '—'} Cr
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* Score */}
                        <td className="py-2 px-2 text-center">
                          <span className={`inline-flex items-center justify-center font-bold px-2 py-0.5 rounded text-[11px] font-mono ${
                            c.century_score >= 80
                              ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                              : c.century_score >= 65
                              ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30'
                              : 'bg-panel text-text border border-border'
                          }`}>
                            {c.century_score}/100
                          </span>
                        </td>

                        {/* 10Y Multiple */}
                        <td className="py-2 px-2 text-center">
                          <div className="font-black text-sm text-emerald-600 dark:text-emerald-400">
                            {te.total_projected_multiple}x
                          </div>
                          <div className="text-[9px] text-muted font-mono">
                            ➔ ₹{te.target_market_cap_cr ? (te.target_market_cap_cr / 1000).toFixed(1) + 'k' : '—'} Cr
                          </div>
                        </td>

                        {/* Engine 1: PAT CAGR */}
                        <td className="py-2 px-2">
                          <div className="font-bold text-text text-xs">
                            +{te.forecast_pat_cagr_pct}% <span className="text-[10px] font-normal text-muted">CAGR</span>
                          </div>
                          <div className="text-[10px] text-muted">
                            {te.pat_expansion_multiple}x 10Y PAT
                          </div>
                        </td>

                        {/* Engine 2: P/E Expansion */}
                        <td className="py-2 px-2">
                          <div className="font-bold text-amber-600 dark:text-amber-400 text-xs">
                            {te.current_pe}x ➔ {te.projected_terminal_pe}x
                          </div>
                          <div className="text-[10px] text-muted">
                            {te.pe_expansion_multiple}x Re-rating
                          </div>
                        </td>

                        {/* LTP & Fair Value */}
                        <td className="py-2 px-2">
                          <div className="font-bold text-text text-xs">
                            ₹{c.ltp?.toLocaleString() || '—'}
                          </div>
                          <div className="text-[10px] text-muted" title="Fair Value Accumulation Zone">
                            FV: ₹{af.accumulate_low} – ₹{af.accumulate_high}
                          </div>
                        </td>

                        {/* Anti-FOMO State */}
                        <td className="py-2 px-2">
                          <span className={`inline-block text-[9.5px] font-bold px-2 py-0.5 rounded font-mono ${
                            af.action_directive === 'ACCUMULATE_FAIR_VALUE'
                              ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                              : af.action_directive === 'WAIT_FOR_PULLBACK'
                              ? 'bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-500/30'
                              : 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30'
                          }`}>
                            {af.action_directive === 'ACCUMULATE_FAIR_VALUE'
                              ? '🟢 Accumulate FV'
                              : af.action_directive === 'WAIT_FOR_PULLBACK'
                              ? '🔴 Wait Pullback'
                              : '🟡 Stalk Pivot'}
                          </span>
                          <div className="text-[9.5px] text-rose-500/90 mt-0.5">
                            Ceiling: ₹{af.no_chase_boundary}
                          </div>
                        </td>

                        {/* Key Catalysts */}
                        <td className="py-2 px-2">
                          <div className="flex flex-wrap gap-1 max-w-xs font-sans">
                            {(c.catalyst_badges || []).slice(0, 2).map((b, i) => (
                              <span
                                key={i}
                                className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-elevated border border-border text-text font-mono truncate max-w-[130px]"
                                title={b}
                              >
                                {b}
                              </span>
                            ))}
                            {(c.catalyst_badges || []).length > 2 && (
                              <span className="text-[9px] text-muted font-mono self-center">
                                +{c.catalyst_badges.length - 2}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Actions */}
                        <td className="py-2 px-3 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              type="button"
                              onClick={() => handleAddToIncubation({
                                symbol: c.symbol,
                                name: c.symbol,
                                sector: 'Quality Microcap',
                                horizon: 'LONG_TERM',
                                cycle_state: 'STAGE_1_ACCUMULATION',
                                eta_days: 15,
                                eta_label: 'Stage 1 Base',
                                entry_price: af.fair_value_anchor || c.ltp,
                                ltp: c.ltp,
                                stop_loss: af.invalidation_stop,
                                target_1: (af.fair_value_anchor || c.ltp) * 2.0,
                                target_2: (af.fair_value_anchor || c.ltp) * 4.0,
                                target_moonshot: (af.fair_value_anchor || c.ltp) * 10.0,
                                risk_reward_ratio: 4.5,
                                inflection_score: c.century_score,
                                primary_archetype: 'STAGE_1_TO_2_EXPANSION',
                                catalyst_badges: c.catalyst_badges || [],
                                catalyst_summary: c.summary,
                              })}
                              className="p-1 px-1.5 rounded-lg border border-purple-500/40 bg-purple-500/10 text-[10px] font-bold text-purple-600 dark:text-purple-400 hover:bg-purple-500/20 transition-all cursor-pointer"
                              title="Retain in Incubation Pipeline"
                            >
                              📌
                            </button>

                            <button
                              type="button"
                              onClick={() => {
                                if (onOpenOrderTicket) {
                                  onOpenOrderTicket({
                                    symbol: c.symbol,
                                    exchange: 'NSE',
                                    price: af.accumulate_low || c.ltp,
                                    stopLoss: af.invalidation_stop,
                                    target: (af.fair_value_anchor || c.ltp) * 2.0,
                                    target2: (af.fair_value_anchor || c.ltp) * 4.0,
                                    targetMoonshot: (af.fair_value_anchor || c.ltp) * 10.0,
                                    _priceSource: 'FAIR_VALUE_POC',
                                  })
                                }
                              }}
                              className="px-2.5 py-1 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-xs font-bold text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/30 transition-all cursor-pointer whitespace-nowrap shadow-xs"
                              title="Stage limit accumulation order at Fair Value"
                            >
                              ⚡ Buy
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          /* ── CONDENSED CARDS MATRIX VIEW ────────────────────────────── */
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {filteredCenturyCandidates.map((c) => {
              const te = c.twin_engines || {}
              const af = c.anti_fomo || {}
              const is100x = (c.compounder_tier === '100X_CENTURY' || c.compounder_tier === '1000X_POTENTIAL')
              return (
                <div
                  key={c.symbol}
                  className="rounded-xl border border-border bg-surface p-3.5 space-y-2.5 shadow-card hover:border-emerald-500/40 transition-all"
                >
                  {/* Card Header */}
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-base text-text">{c.symbol}</span>
                        <span className="text-xs font-mono text-muted">₹{c.ltp}</span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border uppercase font-mono ${
                          is100x
                            ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30'
                            : 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                        }`}>
                          {c.compounder_tier}
                        </span>
                      </div>
                      <p className="text-[11px] text-muted font-ui mt-0.5">
                        Current MCap: ₹{te.current_market_cap_cr ? te.current_market_cap_cr.toLocaleString() : '—'} Cr • Current P/E: {te.current_pe}x
                      </p>
                    </div>

                    <div className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <span className="text-xl font-black text-emerald-600 dark:text-emerald-400 font-mono">
                          {te.total_projected_multiple}x
                        </span>
                      </div>
                      <span className="text-[9px] text-muted font-mono uppercase">
                        Projected 10Y Multiple
                      </span>
                    </div>
                  </div>

                  {/* Twin Engines Breakdown */}
                  <div className="grid grid-cols-2 gap-2 text-xs font-mono p-2 rounded-lg bg-panel border border-border">
                    <div>
                      <span className="text-[9.5px] text-muted font-ui block">ENGINE 1: PAT EXPANSION</span>
                      <span className="font-bold text-text">
                        {te.pat_expansion_multiple}x ({te.forecast_pat_cagr_pct}% CAGR)
                      </span>
                    </div>
                    <div>
                      <span className="text-[9.5px] text-muted font-ui block">ENGINE 2: P/E RE-RATING</span>
                      <span className="font-bold text-amber-600 dark:text-amber-400">
                        {te.pe_expansion_multiple}x ({te.current_pe}x ➔ {te.projected_terminal_pe}x)
                      </span>
                    </div>
                  </div>

                  {/* Badges */}
                  <div className="flex flex-wrap gap-1 font-ui">
                    {c.catalyst_badges?.map((b, i) => (
                      <span
                        key={i}
                        className="text-[9px] font-semibold px-2 py-0.5 rounded bg-elevated border border-border text-text font-mono"
                      >
                        {b}
                      </span>
                    ))}
                  </div>

                  {/* Anti-FOMO Execution Box */}
                  <div className="p-2.5 rounded-lg border border-border/80 bg-surface/80 space-y-1.5">
                    <div className="flex items-center justify-between font-ui">
                      <span className="text-[10px] font-bold text-text flex items-center gap-1">
                        <span>🛡️</span>
                        <span>Anti-FOMO Accumulation Blueprint</span>
                      </span>
                      <span className={`text-[9.5px] font-bold px-2 py-0.5 rounded font-mono ${
                        af.action_directive === 'ACCUMULATE_FAIR_VALUE'
                          ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                          : af.action_directive === 'WAIT_FOR_PULLBACK'
                          ? 'bg-rose-500/20 text-rose-600 dark:text-rose-400'
                          : 'bg-amber-500/20 text-amber-600 dark:text-amber-400'
                      }`}>
                        {af.action_directive}
                      </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs font-mono">
                      <div>
                        <span className="text-[9px] text-muted font-ui block">FAIR VALUE ZONE</span>
                        <span className="font-bold text-text">
                          ₹{af.accumulate_low} – ₹{af.accumulate_high}
                        </span>
                      </div>
                      <div>
                        <span className="text-[9px] text-rose-500 font-ui block">NO CHASE CEILING</span>
                        <span className="font-bold text-rose-600 dark:text-rose-400">
                          ₹{af.no_chase_boundary}
                        </span>
                      </div>
                      <div>
                        <span className="text-[9px] text-cyan-600 dark:text-cyan-400 font-ui block">PULLBACK LIMIT</span>
                        <span className="font-bold text-cyan-600 dark:text-cyan-400">
                          ₹{af.pullback_limit_entry}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex items-center justify-between pt-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10.5px] font-mono text-muted">
                        Score: <strong className="text-text">{c.century_score}/100</strong>
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleAddToIncubation({
                          symbol: c.symbol,
                          name: c.symbol,
                          sector: 'Quality Microcap',
                          horizon: 'LONG_TERM',
                          cycle_state: 'STAGE_1_ACCUMULATION',
                          eta_days: 15,
                          eta_label: 'Stage 1 Base',
                          entry_price: af.fair_value_anchor || c.ltp,
                          ltp: c.ltp,
                          stop_loss: af.invalidation_stop,
                          target_1: (af.fair_value_anchor || c.ltp) * 2.0,
                          target_2: (af.fair_value_anchor || c.ltp) * 4.0,
                          target_moonshot: (af.fair_value_anchor || c.ltp) * 10.0,
                          risk_reward_ratio: 4.5,
                          inflection_score: c.century_score,
                          primary_archetype: 'STAGE_1_TO_2_EXPANSION',
                          catalyst_badges: c.catalyst_badges || [],
                          catalyst_summary: c.summary,
                        })}
                        className="px-2.5 py-1 rounded-lg border border-purple-500/40 bg-purple-500/15 text-xs font-semibold text-purple-600 dark:text-purple-400 hover:bg-purple-500/25 transition-all cursor-pointer flex items-center gap-1"
                        title="Retain in Incubation Pipeline"
                      >
                        <span>📌</span>
                        <span>Retain</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => {
                          if (onOpenOrderTicket) {
                            onOpenOrderTicket({
                              symbol: c.symbol,
                              exchange: 'NSE',
                              price: af.accumulate_low || c.ltp,
                              stopLoss: af.invalidation_stop,
                              target: (af.fair_value_anchor || c.ltp) * 2.0,
                              target2: (af.fair_value_anchor || c.ltp) * 4.0,
                              targetMoonshot: (af.fair_value_anchor || c.ltp) * 10.0,
                              _priceSource: 'FAIR_VALUE_POC',
                            })
                          }
                        }}
                        className="px-3 py-1 rounded-lg border border-emerald-500/30 bg-emerald-500/15 text-xs font-bold text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/25 transition-all cursor-pointer flex items-center gap-1"
                      >
                        <span>⚡</span>
                        <span>Accumulate</span>
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 h-full overflow-hidden select-none bg-void text-text">
      {/* ── ROW 1: MASTER CONTROLS & COMMAND DECK (Streamlined 36px) ─────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 border-b border-border bg-surface text-xs">
        {/* Left: Title & Mode Toggle (Radar vs Incubation) */}
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-lg border border-border p-0.5 bg-elevated">
            <button
              type="button"
              onClick={() => setActiveMainTab('scanner')}
              className={`text-xs px-2.5 py-1 rounded transition-all cursor-pointer flex items-center gap-1.5 ${
                activeMainTab === 'scanner'
                  ? 'font-bold bg-panel text-amber-600 dark:text-amber-400 shadow-xs'
                  : 'text-muted hover:text-text'
              }`}
            >
              <span>📡</span>
              <span>Inflection Radar</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveMainTab('incubation')}
              className={`text-xs px-2.5 py-1 rounded transition-all cursor-pointer flex items-center gap-1.5 ${
                activeMainTab === 'incubation'
                  ? 'font-bold bg-panel text-purple-600 dark:text-purple-400 shadow-xs'
                  : 'text-muted hover:text-text'
              }`}
            >
              <span>📌</span>
              <span>Incubation Pipeline</span>
              {incubatedCandidates.length > 0 && (
                <span className="text-[9px] px-1.5 py-0.2 rounded-full font-mono bg-purple-500/20 text-purple-600 dark:text-purple-400 font-bold">
                  {incubatedCandidates.length}
                </span>
              )}
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveMainTab('century')
                if (centuryCandidates.length === 0) loadCenturyCompounders()
              }}
              className={`text-xs px-2.5 py-1 rounded transition-all cursor-pointer flex items-center gap-1.5 ${
                activeMainTab === 'century'
                  ? 'font-bold bg-panel text-emerald-600 dark:text-emerald-400 shadow-xs'
                  : 'text-muted hover:text-text'
              }`}
            >
              <span>💎</span>
              <span>100x Century Compounders</span>
            </button>
          </div>

          <Badge variant="emerald" size="xs">
            5W+H
          </Badge>
          {isLiveConnected ? (
            <span className="flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              LIVE
            </span>
          ) : (
            <span className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
              EOD
            </span>
          )}
          {storeStats && (
            <span className="text-[10px] text-muted font-mono hidden xl:inline">
              ({storeStats.cached_symbols_count} cached)
            </span>
          )}
        </div>

        {/* Center/Right Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Universe Selector */}
          <div className="flex items-center gap-1">
            <span className="text-muted text-[11px] hidden lg:inline">Universe:</span>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="text-xs py-1 px-2.5 rounded-lg bg-panel border border-border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer hover:border-gold/50"
              title="Target market universe to scan"
            >
              {universesList.length > 0 ? (
                universesList.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.count})
                  </option>
                ))
              ) : (
                <>
                  <option value="multibagger_hunters">🚀 Multibagger Hunters (45)</option>
                  <option value="momentum_breakouts">⚡ Momentum & Squeeze (50)</option>
                  <option value="auto_market_aware">🌐 Market-Aware RRG (60)</option>
                  <option value="nifty50">🏛️ NIFTY 50 (50)</option>
                  <option value="nifty500">🏢 NIFTY 500 (501)</option>
                  <option value="smallcap_250">🚀 Smallcap 250 (251)</option>
                  <option value="microcap_250">🌱 Microcap 250 (254)</option>
                  <option value="all_nse_liquid">🌊 All Liquid NSE Series EQ (1,200+)</option>
                </>
              )}
            </select>
          </div>

          {/* Liquidity Floor */}
          <select
            value={minTurnoverCr}
            onChange={(e) => setMinTurnoverCr(Number(e.target.value))}
            className="text-xs py-1 px-2.5 rounded-lg bg-panel border border-border text-text focus:outline-none focus:border-gold transition-colors font-mono cursor-pointer hover:border-gold/50"
            title="20-Day Median Turnover floor"
          >
            <option value={0}>Liq: All</option>
            <option value={0.25}>Liq: ₹25 L</option>
            <option value={0.5}>Liq: ₹50 L (Rec)</option>
            <option value={1.0}>Liq: ₹1 Cr</option>
            <option value={2.0}>Liq: ₹2 Cr</option>
            <option value={5.0}>Liq: ₹5 Cr</option>
          </select>

          {/* View Mode Toggle */}
          <div className="flex items-center rounded-lg border border-border p-0.5 bg-elevated">
            <button
              type="button"
              onClick={() => setViewMode('table')}
              className={`text-xs px-2 py-0.5 rounded transition-all cursor-pointer ${
                viewMode === 'table' ? 'font-bold bg-panel text-amber-600 dark:text-amber-400 shadow-xs' : 'text-muted hover:text-text'
              }`}
              title="Table View"
            >
              ☰ Table
            </button>
            <button
              type="button"
              onClick={() => setViewMode('cards')}
              className={`text-xs px-2 py-0.5 rounded transition-all cursor-pointer ${
                viewMode === 'cards' ? 'font-bold bg-panel text-amber-600 dark:text-amber-400 shadow-xs' : 'text-muted hover:text-text'
              }`}
              title="Cards Matrix"
            >
              ☷ Cards
            </button>
          </div>

          {/* Sync EOD Button */}
          <button
            type="button"
            onClick={executeEodSync}
            disabled={isSyncingEod || isScanning}
            className={`flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-lg border transition-all cursor-pointer ${
              isSyncingEod
                ? 'bg-sapphire/20 border-sapphire text-blue-600 dark:text-blue-400'
                : 'bg-elevated border-border text-text hover:border-subtle'
            }`}
            title="Bulk sync daily bars into local SQLite store"
          >
            <span className={isSyncingEod ? 'animate-spin' : ''}>{isSyncingEod ? '⏳' : '🔄'}</span>
            <span>{isSyncingEod ? 'Syncing...' : 'Sync EOD'}</span>
          </button>

          {/* Scan Market Button */}
          <button
            type="button"
            onClick={(e) => executeScan(universe, minTurnoverCr, capTierFilter, Boolean(e.shiftKey))}
            disabled={isScanning}
            className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1 rounded-lg border transition-all cursor-pointer shadow-xs ${
              !scanResult
                ? 'border-gold bg-gold/25 text-amber-700 dark:text-amber-300 hover:bg-gold/35 ring-1 ring-gold/50 animate-pulse font-bold'
                : 'border-gold/40 bg-gold/15 text-amber-600 dark:text-amber-400 hover:bg-gold/25'
            }`}
            title={scanResult ? 'Click for instant cache (<25ms) or Shift+Click for full recalculation' : 'Run instant inflection scan on target universe'}
          >
            <span className={isScanning ? 'animate-spin' : ''}>{isScanning ? '🔄' : '⚡'}</span>
            <span>{isScanning ? 'Scanning...' : 'Scan Market'}</span>
          </button>

          {/* Recalculate Button (when result exists) */}
          {scanResult && (
            <button
              type="button"
              onClick={() => executeScan(universe, minTurnoverCr, capTierFilter, true)}
              disabled={isScanning}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border border-border bg-elevated text-muted hover:text-text cursor-pointer transition-all"
              title="Recalculate entire universe from raw quantitative engine (~4s)"
            >
              <span className={isScanning ? 'animate-spin' : ''}>🔄</span>
              <span>Recalculate</span>
            </button>
          )}
        </div>
      </div>

      {/* ── ROW 2: QUANTITATIVE FILTER TOOLBAR (Unified Dropdowns & Telemetry) ─────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 border-b border-border bg-panel text-xs">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          {/* Horizon Dropdown */}
          <select
            value={horizonFilter}
            onChange={(e) => setHorizonFilter(e.target.value)}
            className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer ${
              horizonFilter !== 'ALL'
                ? 'border-purple-400 text-purple-300 font-bold bg-purple-500/10'
                : 'border-border hover:border-gold/50'
            }`}
            title="Filter by investment / holding horizon"
          >
            <option value="ALL">All Horizons {scanResult && horizonCounts.ALL ? `(${horizonCounts.ALL})` : ''}</option>
            <option value="SHORT_TERM">⚡ Short (1–4W) {scanResult && horizonCounts.SHORT_TERM ? `(${horizonCounts.SHORT_TERM})` : ''}</option>
            <option value="MID_TERM">📈 Mid (1–6M) {scanResult && horizonCounts.MID_TERM ? `(${horizonCounts.MID_TERM})` : ''}</option>
            <option value="LONG_TERM">💎 Multibagger (1–3Y) {scanResult && horizonCounts.LONG_TERM ? `(${horizonCounts.LONG_TERM})` : ''}</option>
          </select>

          {/* Archetype Dropdown */}
          <div className="flex items-center gap-1">
            <select
              value={archetypeFilter}
              onChange={(e) => setArchetypeFilter(e.target.value)}
              className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer ${
                archetypeFilter !== 'ALL'
                  ? 'border-gold text-gold font-bold bg-gold/10'
                  : 'border-border hover:border-gold/50'
              }`}
              title="Filter by quantitative inflection archetype"
            >
              <option value="ALL">All Inflections {scanResult && archetypeCounts.ALL ? `(${archetypeCounts.ALL})` : ''}</option>
              <option value="VCP_PIVOT_BREAKOUT">🎯 VCP Pivots {scanResult && archetypeCounts.VCP_PIVOT_BREAKOUT ? `(${archetypeCounts.VCP_PIVOT_BREAKOUT})` : ''}</option>
              <option value="TTM_SQUEEZE_EXPLOSION">⚡ TTM Squeeze Breakouts {scanResult && archetypeCounts.TTM_SQUEEZE_EXPLOSION ? `(${archetypeCounts.TTM_SQUEEZE_EXPLOSION})` : ''}</option>
              <option value="STAGE_1_TO_2_EXPANSION">🚀 Stage 1→2 Markup {scanResult && archetypeCounts.STAGE_1_TO_2_EXPANSION ? `(${archetypeCounts.STAGE_1_TO_2_EXPANSION})` : ''}</option>
              <option value="SMC_SPRING_SWEEP">🎪 SMC Springs & Sweeps {scanResult && archetypeCounts.SMC_SPRING_SWEEP ? `(${archetypeCounts.SMC_SPRING_SWEEP})` : ''}</option>
              <option value="RRG_SECTOR_ROTATION">🔄 Sector RRG Leaders {scanResult && archetypeCounts.RRG_SECTOR_ROTATION ? `(${archetypeCounts.RRG_SECTOR_ROTATION})` : ''}</option>
            </select>
            <HelpHint metricKey="vcp_pivot" size="xs" />
          </div>

          {/* Timing Dropdown */}
          <div className="flex items-center gap-1">
            <select
              value={timingFilter}
              onChange={(e) => setTimingFilter(e.target.value)}
              className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer ${
                timingFilter !== 'ALL'
                  ? 'border-emerald-400 text-emerald-300 font-bold bg-emerald-500/10'
                  : 'border-border hover:border-gold/50'
              }`}
              title="Filter by entry timing urgency"
            >
              <option value="ALL">All Timing {scanResult && timingCounts.ALL ? `(${timingCounts.ALL})` : ''}</option>
              <option value="TRIGGER_NOW">🔥 Trigger Now / Active {scanResult && timingCounts.TRIGGER_NOW ? `(${timingCounts.TRIGGER_NOW})` : ''}</option>
              <option value="COILING_IMMINENT">⏳ Coiling (1–3d) {scanResult && timingCounts.COILING_IMMINENT ? `(${timingCounts.COILING_IMMINENT})` : ''}</option>
              <option value="PULLBACK_RETEST">🎯 Retest Zone {scanResult && timingCounts.PULLBACK_RETEST ? `(${timingCounts.PULLBACK_RETEST})` : ''}</option>
            </select>
            <HelpHint metricKey="timing_state" size="xs" />
          </div>

          {/* Market Cap Tier */}
          <select
            value={capTierFilter}
            onChange={(e) => setCapTierFilter(e.target.value)}
            className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer ${
              capTierFilter !== 'ALL'
                ? 'border-gold text-gold font-bold bg-gold/10'
                : 'border-border hover:border-gold/50'
            }`}
            title="Filter by Market Cap Tier"
          >
            <option value="ALL">All Caps</option>
            <option value="LARGE">🏛️ Large Cap</option>
            <option value="MID">⚡ Mid Cap</option>
            <option value="SMALL">🚀 Small Cap</option>
            <option value="MICRO">🌱 Micro Cap</option>
          </select>

          {/* Sector Filter */}
          <select
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
            className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer max-w-[130px] truncate ${
              sectorFilter !== 'ALL'
                ? 'border-gold text-gold font-bold bg-gold/10'
                : 'border-border hover:border-gold/50'
            }`}
            title="Filter by Sector"
          >
            <option value="ALL">All Sectors {availableSectors.length > 0 ? `(${availableSectors.length})` : ''}</option>
            {availableSectors.map((sec) => (
              <option key={sec.name} value={sec.name}>
                {sec.name} ({sec.count})
              </option>
            ))}
          </select>

          {/* Score Selector */}
          <select
            value={minScoreFilter}
            onChange={(e) => setMinScoreFilter(Number(e.target.value))}
            className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer ${
              minScoreFilter > 0
                ? 'border-amber-400 text-amber-300 font-bold bg-amber-500/10'
                : 'border-border hover:border-gold/50'
            }`}
            title="Filter by minimum quantitative conviction score"
          >
            <option value={0}>Score: All</option>
            <option value={75}>Score: 75+ (High Conviction)</option>
            <option value={65}>Score: 65+ (Strong Setup)</option>
            <option value={50}>Score: 50+ (Base Filter)</option>
          </select>

          {/* Quick Condition Chips (RVOL & Exclude UC) */}
          <button
            type="button"
            onClick={() => setFilterVolumeSurge((p) => !p)}
            className={`px-2 py-1 rounded-lg text-xs font-semibold border transition-all cursor-pointer flex items-center gap-1 ${
              filterVolumeSurge
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40 shadow-xs'
                : 'bg-surface text-muted border-border hover:text-text'
            }`}
            title="Filter for relative volume expansion (RVOL >= 1.5x)"
          >
            <span>🔥</span>
            <span>RVOL ≥ 1.5x</span>
          </button>

          <button
            type="button"
            onClick={() => setFilterExcludeUCLocked((p) => !p)}
            className={`px-2 py-1 rounded-lg text-xs font-semibold border transition-all cursor-pointer flex items-center gap-1 ${
              filterExcludeUCLocked
                ? 'bg-rose-500/15 text-rose-300 border-rose-500/40 shadow-xs'
                : 'bg-surface text-muted border-border hover:text-text'
            }`}
            title="Exclude stocks currently locked in upper circuit (unactionable)"
          >
            <span>🛡️</span>
            <span>Exclude UC Locked</span>
          </button>

          {/* Search Input */}
          <div className="relative flex items-center">
            <input
              type="text"
              placeholder="🔍 Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-28 sm:w-36 text-xs pl-2.5 pr-6 py-1 rounded-lg bg-surface border border-border text-text placeholder:text-muted focus:outline-none focus:border-gold transition-colors font-sans"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-text text-xs cursor-pointer"
                title="Clear search"
              >
                ✕
              </button>
            )}
          </div>

          {/* Reset Filters Button */}
          {activeFilterCount > 0 && (
            <button
              type="button"
              onClick={resetAllFilters}
              className="btn btn-sm btn-ghost text-xs text-rose-400 hover:text-rose-300 border border-rose-500/30 hover:bg-rose-500/10 flex items-center gap-1 font-bold px-2 py-0.5 cursor-pointer"
              title="Reset all filters"
            >
              ✕ Reset Filters
            </button>
          )}
        </div>

        {/* Right: High-Density Inline Metrics Telemetry */}
        <div className="flex items-center gap-2 font-mono text-[10px] text-muted flex-shrink-0 ml-auto">
          <span>
            Setups: <strong className="text-text">{summaryMetrics.total}</strong>
          </span>
          <span>·</span>
          <span>
            75+ Score: <strong className="text-amber-500">{summaryMetrics.highConviction}</strong>
          </span>
          <span>·</span>
          <span>
            Coiling: <strong className="text-cyan-500">{summaryMetrics.coiling}</strong>
          </span>
          <span>·</span>
          <span>
            Fired: <strong className="text-emerald-500">{summaryMetrics.triggerNow}</strong>
          </span>
          <span>·</span>
          <span>
            Avg R:R: <strong className="text-text">{summaryMetrics.avgRR ? `1:${summaryMetrics.avgRR}` : '—'}</strong>
          </span>
        </div>
      </div>

      {/* ── MAIN CANDIDATES VIEW CONTAINER ──────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeMainTab === 'incubation' ? (
          renderIncubationBoard()
        ) : activeMainTab === 'century' ? (
          renderCenturyBoard()
        ) : isScanning && filteredCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-gold border-t-transparent animate-spin" />
            <span className="text-xs font-mono tracking-wider text-muted uppercase">
              Screening 5 Inflection Engines & Computing Confluences...
            </span>
          </div>
        ) : !scanResult ? (
          <div className="flex flex-col items-center justify-center h-80 rounded-2xl border border-dashed border-border bg-surface/50 text-center p-6 my-4 shadow-sm font-ui">
            <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-center text-2xl mb-3 shadow-inner">
              📡
            </div>
            <h3 className="text-sm font-bold text-text">
              Strategic Inflection Radar Standby
            </h3>
            <p className="text-xs text-muted mt-1.5 max-w-md leading-relaxed">
              Target universe configured to <strong className="text-text font-mono">{universe}</strong> (Liquidity Floor: ₹{minTurnoverCr} Cr).
              Click <strong className="text-amber-500">Scan Market</strong> when ready to evaluate 5 quantitative inflection engines (VCP, Volume Profiles, Wyckoff, Super-Trend, Anti-FOMO).
            </p>
            <button
              type="button"
              onClick={() => executeScan(universe, minTurnoverCr, capTierFilter, false)}
              className="mt-4 flex items-center gap-2 text-xs font-bold px-5 py-2.5 rounded-xl border border-gold/40 bg-gold/15 text-amber-600 dark:text-amber-400 hover:bg-gold/25 shadow-md hover:shadow-gold/10 transition-all cursor-pointer font-mono"
            >
              <span>⚡</span>
              <span>Scan Market ({universe})</span>
            </button>
          </div>
        ) : filteredCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <span className="text-3xl mb-2">🔍</span>
            <span className="text-sm font-bold text-text">No Inflection Setups Matching Criteria</span>
            <p className="text-xs text-muted mt-1 max-w-md">
              {activeFilterCount > 0
                ? `None of the ${scanResult?.candidates?.length || 0} setups match your ${activeFilterCount} active filters. Try clearing filters or selecting a different setup.`
                : 'Try switching the universe (e.g. Multibagger Hunters or Microcap 250) or running a rescan.'}
            </p>
            {activeFilterCount > 0 && (
              <button
                type="button"
                onClick={resetAllFilters}
                className="mt-3 text-xs font-semibold px-3 py-1.5 rounded-lg border border-border bg-elevated text-amber-600 dark:text-amber-400 hover:bg-gold/15 transition-all cursor-pointer"
              >
                ✕ Clear All Filters ({scanResult?.candidates?.length || 0} Setups Available)
              </button>
            )}
          </div>
        ) : viewMode === 'table' ? (
          /* ── TABLE VIEW ──────────────────────────────────────────────── */
          <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-card">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-border bg-panel text-[10px] font-mono text-muted uppercase tracking-wider">
                  {renderHeader('symbol', 'Symbol / Asset', 'left', 'px-3')}
                  {renderHeader('inflection_score', 'Inflection Score', 'left')}
                  {renderHeader('primary_archetype', 'Primary Archetype', 'left')}
                  {renderHeader('timing_state', 'Timing State', 'left')}
                  {renderHeader('ltp', 'LTP (₹)', 'right')}
                  {renderHeader('day_change_pct', 'Day Chg', 'right')}
                  {renderHeader('rvol_20d', 'RVOL 20D', 'center')}
                  {renderHeader('trend_template_passed', 'Stage / Minervini', 'center')}
                  {renderHeader('entry_price', 'Trade Levels (Entry / SL / Targets T1-T2-🚀T3)', 'left')}
                  {renderHeader('risk_reward_ratio', 'Payoff (R:R)', 'center')}
                  <th className="py-2.5 px-3 text-right text-muted">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60 font-mono">
                {filteredCandidates.map((c) => {
                  const isReady = c.timing_state === 'TRIGGER_NOW'
                  const isCoiling = c.timing_state === 'COILING_IMMINENT'
                  return (
                    <tr
                      key={c.symbol}
                      className="hover:bg-amber-500/[0.04] dark:hover:bg-white/[0.04] transition-all group cursor-pointer"
                      onClick={() => openDecisionDrawer(c)}
                    >
                      {/* Symbol & Name */}
                      <td className="py-2.5 px-3">
                        <div className="flex items-center gap-2">
                          <span className="text-base">{c.sector_icon || '🏢'}</span>
                          <div>
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="font-bold text-text text-xs group-hover:text-amber-600 dark:group-hover:text-amber-400 transition-colors">
                                {c.symbol}
                              </span>
                              {c.horizon && (
                                <span
                                  className={`text-[8px] font-bold px-1.5 py-0.2 rounded border uppercase font-mono ${
                                    c.horizon === 'LONG_TERM'
                                      ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                                      : c.horizon === 'SHORT_TERM'
                                      ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/30'
                                      : 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30'
                                  }`}
                                  title={`Investment Horizon: ${c.horizon}`}
                                >
                                  {c.horizon === 'LONG_TERM' ? '💎 MULTIBAGGER' : c.horizon === 'SHORT_TERM' ? '⚡ SHORT' : '📈 MID'}
                                </span>
                              )}
                              {c.eta_label && (
                                <span
                                  className="text-[8px] font-mono px-1 py-0.2 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20"
                                  title={`Cycle ETA: ${c.eta_label}`}
                                >
                                  {c.eta_label}
                                </span>
                              )}
                              {c.executive_verdict && (
                                <span
                                  className={`text-[8px] font-bold px-1.5 py-0.2 rounded uppercase font-mono ${
                                    c.executive_verdict.includes('CIRCUIT')
                                      ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30'
                                      : c.executive_verdict.includes('STRONG')
                                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                                      : 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30'
                                  }`}
                                >
                                  {c.executive_verdict}
                                </span>
                              )}
                              {c.cap_tier && (
                                <span
                                  className={`text-[8px] font-bold px-1 py-0.2 rounded border uppercase font-mono ${
                                    c.cap_tier === 'LARGE'
                                      ? 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30'
                                      : c.cap_tier === 'MID'
                                      ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30'
                                      : c.cap_tier === 'SMALL'
                                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                                      : 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border border-purple-500/30'
                                  }`}
                                  title={`Market Cap Tier: ${c.cap_tier}`}
                                >
                                  {c.cap_tier}
                                </span>
                              )}
                              {c.circuit_state === 'UPPER_CIRCUIT_LOCKED' && (
                                <span
                                  className="text-[8px] font-bold px-1 py-0.2 rounded bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/40 animate-pulse"
                                  title="Upper Circuit Locked (No Sellers Available)"
                                >
                                  🔒 UC LOCKED
                                </span>
                              )}
                              {c.circuit_state === 'NEAR_UPPER_CIRCUIT' && (
                                <span
                                  className="text-[8px] font-bold px-1 py-0.2 rounded bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/40"
                                  title="Within 1.5% of Upper Circuit Ceiling"
                                >
                                  ⚠️ NEAR UC
                                </span>
                              )}
                              {c.weekly_stage === 'STAGE_2_UPTREND' && (
                                <span
                                  className="text-[8px] font-bold px-1 py-0.2 rounded bg-yellow-500/15 text-yellow-800 dark:text-yellow-300 border border-yellow-500/30"
                                  title="Aligned with Weekly 30-week EMA Stage 2 Uptrend"
                                >
                                  👑 W-S2
                                </span>
                              )}
                              {c.rrg_quadrant === 'LEADING' && (
                                <span className="text-[9px] px-1 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30 font-bold">
                                  LEADING
                                </span>
                              )}
                            </div>
                            <span className="text-[10px] text-muted font-ui block truncate max-w-[140px]">
                              {c.name}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Inflection Score with 3-Pillar Micro Metric */}
                      <td className="py-2.5 px-2">
                        <div className="flex items-center gap-1.5">
                          <div
                            className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shadow-xs ${
                              c.inflection_score >= 75 ? 'score-badge-gold' : 'score-badge-sapphire'
                            }`}
                          >
                            {c.inflection_score}
                          </div>
                          <div className="flex flex-col">
                            <span className="text-[9px] font-mono text-muted" title="Technical / Sector / Quality Pillars">
                              {c.technical_score != null ? c.technical_score : '—'}T • {c.sector_score != null ? c.sector_score : '—'}S • {c.quality_score != null ? c.quality_score : '—'}Q
                            </span>
                            <span className="text-[8px] font-mono text-emerald-600 dark:text-emerald-400 font-bold">
                              💾 0ms
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Primary Archetype */}
                      <td className="py-2.5 px-2 font-ui">
                        <Badge variant="gold" size="md">
                          {c.archetype_label}
                        </Badge>
                      </td>

                      {/* Timing State */}
                      <td className="py-2.5 px-2 font-ui">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full border inline-block ${
                            isReady
                              ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/40 animate-pulse font-bold'
                              : isCoiling
                              ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/40 font-bold'
                              : 'bg-blue-500/15 text-blue-700 dark:text-blue-400 border border-blue-500/40 font-bold'
                          }`}
                        >
                          {c.timing_label}
                        </span>
                      </td>

                      {/* LTP — live tick overlay */}
                      <td className="py-2.5 px-2 text-right font-bold text-text">
                        {(() => {
                          const liveTick = getTicker(c.symbol)
                          const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                          const displayLtp = livePrice ?? c.ltp
                          return (
                            <div className="flex flex-col items-end gap-0.5">
                              <span>₹{displayLtp.toLocaleString('en-IN', { minimumFractionDigits: 1 })}</span>
                              {livePrice ? (
                                <span className="text-[8px] font-mono text-emerald-500 flex items-center gap-0.5">
                                  <span className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />LIVE
                                </span>
                              ) : (
                                <span className="text-[8px] font-mono text-muted">EOD</span>
                              )}
                            </div>
                          )
                        })()}
                      </td>

                      {/* Day Change */}
                      <td
                        className={`py-2.5 px-2 text-right font-bold ${
                          c.day_change_pct >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {formatPct(c.day_change_pct).text}
                      </td>

                      {/* RVOL 20D & Median Turnover */}
                      <td className="py-2.5 px-2 text-center">
                        <div className="flex flex-col items-center">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[11px] font-semibold ${
                              c.rvol_20d >= 1.8
                                ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 font-bold'
                                : c.rvol_20d < 0.6
                                ? 'text-cyan-600 dark:text-cyan-400'
                                : 'text-muted'
                            }`}
                          >
                            {c.rvol_20d}x
                          </span>
                          <span className="text-[9px] text-muted font-mono mt-0.5" title="20-Day Median Turnover">
                            ₹{c.turnover_20d_cr > 0 ? c.turnover_20d_cr.toFixed(2) : '0.00'} Cr
                          </span>
                        </div>
                      </td>

                      {/* Stage / Minervini & 52W High Proximity */}
                      <td className="py-2.5 px-2 text-center font-ui text-[11px]">
                        <div className="flex flex-col items-center">
                          <span className="text-text font-bold">{c.trend_template_passed}/8</span>
                          <div className="flex items-center gap-1 text-[10px] text-muted font-mono">
                            <span>({c.weinstein_stage.replace('STAGE_', 'S')})</span>
                            {c.dist_52w_high_pct !== null && c.dist_52w_high_pct !== undefined && (
                              <span
                                className={c.dist_52w_high_pct >= -5 ? 'text-emerald-600 dark:text-emerald-400 font-bold' : 'text-muted'}
                                title="Distance to 52-Week High"
                              >
                                {c.dist_52w_high_pct.toFixed(0)}%
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Trade Levels: Entry, SL, T1, T2, Moonshot T3 */}
                      <td className="py-2 px-2 font-mono text-[11px]">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1.5">
                            <span className="text-text font-bold" title="Optimal Entry Zone">
                              ₹{c.entry_price.toFixed(1)}
                            </span>
                            <span className="text-muted text-[10px]">/</span>
                            <span className="text-rose-600 dark:text-rose-400 font-medium" title="Structural Invalidation Stop Loss">
                              SL: ₹{c.stop_loss.toFixed(1)}
                            </span>
                          </div>
                          <div className="flex items-center gap-1 text-[10px]">
                            <span className="text-emerald-600 dark:text-emerald-400 font-bold" title="Target 1 (+2R Scale 50% & SL to Breakeven)">
                              T1: ₹{c.target_1.toFixed(1)}
                            </span>
                            <span className="text-muted text-[8px]">•</span>
                            <span className="text-amber-600 dark:text-amber-400 font-bold" title="Target 2 (+3.5R Primary Positional Swing)">
                              T2: ₹{(c.target_2 || (c.entry_price + (3.5 * Math.max(0.5, c.entry_price - c.stop_loss)))).toFixed(1)}
                            </span>
                            <span className="text-muted text-[8px]">•</span>
                            <span className="text-purple-600 dark:text-purple-400 font-bold flex items-center gap-0.5" title="Moonshot Target (+6.5R Runner)">
                              <span>🚀</span>T3: ₹{(c.target_moonshot || (c.entry_price + (6.5 * Math.max(0.5, c.entry_price - c.stop_loss)))).toFixed(1)}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Risk / Reward */}
                      <td className="py-2.5 px-2 text-center">
                        <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">
                          1:{c.risk_reward_ratio}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => openDecisionDrawer(c)}
                            className="p-1 rounded hover:bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30 transition-all cursor-pointer"
                            title="AI 5W+H Decision Matrix"
                          >
                            🧠
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleAddToIncubation(c, e)}
                            className="p-1 rounded hover:bg-purple-500/20 text-purple-400 border border-purple-500/30 transition-all cursor-pointer"
                            title="Retain in Cycle Incubation Pipeline"
                          >
                            📌
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (onNavigateToTerminal) onNavigateToTerminal(c.symbol)
                              else setActiveView('terminal')
                            }}
                            className="p-1 rounded hover:bg-black/5 dark:hover:bg-white/10 text-muted hover:text-text border border-border transition-all cursor-pointer"
                            title="View in Quant Terminal"
                          >
                            📊
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (onOpenOrderTicket) {
                                const liveTick = getTicker(c.symbol)
                                const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                                onOpenOrderTicket({
                                  symbol: c.symbol,
                                  exchange: 'NSE',
                                  price: livePrice ?? c.entry_price,
                                  stopLoss: c.stop_loss,
                                  target: c.target_1,
                                  target2: c.target_2,
                                  targetMoonshot: c.target_moonshot,
                                  _priceSource: livePrice ? 'LIVE' : 'EOD_ENTRY',
                                })
                              }
                            }}
                            className="p-1 rounded hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 transition-all cursor-pointer"
                            title="Open Order Ticket"
                          >
                            ⚡
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          /* ── CARDS MATRIX VIEW ────────────────────────────────────────── */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredCandidates.map((c) => (
              <div
                key={c.symbol}
                onClick={() => openDecisionDrawer(c)}
                className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between gap-3 shadow-xs hover:shadow-md hover:border-amber-500/40 transition-all cursor-pointer group"
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-2xl p-1.5 rounded-lg bg-panel border border-border">
                      {c.sector_icon || '🏢'}
                    </span>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-text text-sm group-hover:text-amber-600 dark:group-hover:text-amber-400 transition-colors">
                          {c.symbol}
                        </span>
                        {c.executive_verdict && (
                          <span
                            className={`text-[8px] font-bold px-1.5 py-0.2 rounded uppercase font-mono ${
                              c.executive_verdict.includes('CIRCUIT')
                                ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30'
                                : c.executive_verdict.includes('STRONG')
                                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                                : 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30'
                            }`}
                          >
                            {c.executive_verdict}
                          </span>
                        )}
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-panel border border-border text-muted">
                          {c.sector}
                        </span>
                      </div>
                      <span className="text-xs text-muted block truncate max-w-[180px]">
                        {c.name}
                      </span>
                    </div>
                  </div>

                  <div className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-sm shadow-xs score-badge-gold">
                    {c.inflection_score}
                  </div>
                </div>

                {/* Badges Strip */}
                <div className="flex flex-wrap items-center gap-1.5">
                  {c.horizon && (
                    <span
                      className={`text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase font-mono ${
                        c.horizon === 'LONG_TERM'
                          ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                          : c.horizon === 'SHORT_TERM'
                          ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/30'
                          : 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30'
                      }`}
                      title={`Horizon: ${c.horizon}`}
                    >
                      {c.horizon === 'LONG_TERM' ? '💎 MULTIBAGGER' : c.horizon === 'SHORT_TERM' ? '⚡ SHORT' : '📈 MID'}
                    </span>
                  )}
                  {c.eta_label && (
                    <span
                      className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20"
                      title={`ETA: ${c.eta_label}`}
                    >
                      {c.eta_label}
                    </span>
                  )}
                  {c.cap_tier && (
                    <span
                      className={`text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase font-mono ${
                        c.cap_tier === 'LARGE'
                          ? 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30'
                          : c.cap_tier === 'MID'
                          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30'
                          : c.cap_tier === 'SMALL'
                          ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                          : 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                      }`}
                      title={`Market Cap Tier: ${c.cap_tier}`}
                    >
                      {c.cap_tier}
                    </span>
                  )}
                  {c.circuit_state === 'UPPER_CIRCUIT_LOCKED' && (
                    <span
                      className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/40 animate-pulse"
                      title="Upper Circuit Locked"
                    >
                      🔒 UC LOCKED
                    </span>
                  )}
                  {c.weekly_stage === 'STAGE_2_UPTREND' && (
                    <span
                      className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-800 dark:text-yellow-300 border border-yellow-500/30"
                      title="Aligned with Weekly 30-week EMA Stage 2 Uptrend"
                    >
                      👑 W-S2
                    </span>
                  )}
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/30">
                    {c.archetype_label}
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30">
                    {c.timing_label}
                  </span>
                  {c.squeeze_state === 'COILING' && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-700 dark:text-cyan-400 border border-cyan-500/30">
                      Coiling ({c.squeeze_duration}b)
                    </span>
                  )}
                  {c.turnover_20d_cr > 0 && (
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-panel border border-border text-muted">
                      ₹{c.turnover_20d_cr.toFixed(1)} Cr/d
                    </span>
                  )}
                  {c.vcp_detected && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-700 dark:text-purple-400 border border-purple-500/30">
                      VCP {c.vcp_tightness_pct}%
                    </span>
                  )}
                </div>

                {/* 3-Pillar Score Micro Strip & Executive Summary */}
                <div className="space-y-1.5 font-mono">
                  <div className="flex items-center justify-between text-[10px] p-1.5 rounded bg-panel border border-border">
                    <span className="text-cyan-700 dark:text-cyan-400 font-semibold">⚡ Tech {c.technical_score != null ? c.technical_score : '—'}/40</span>
                    <span className="text-muted">•</span>
                    <span className="text-amber-700 dark:text-amber-400 font-semibold">🔄 Sector {c.sector_score != null ? c.sector_score : '—'}/30</span>
                    <span className="text-muted">•</span>
                    <span className="text-emerald-700 dark:text-emerald-400 font-semibold">🛡️ Qual {c.quality_score != null ? c.quality_score : '—'}/30</span>
                  </div>
                  {c.executive_summary && (
                    <p className="text-[11px] text-text-dim leading-relaxed font-ui line-clamp-2 px-1">
                      {c.executive_summary}
                    </p>
                  )}
                </div>

                {/* Trade Setup Coordinates */}
                <div className="p-2.5 rounded-lg bg-panel border border-border font-mono text-xs space-y-2">
                  {/* Row 1: LTP, Optimal Entry, Structural Stop Loss */}
                  <div className="grid grid-cols-3 gap-2 text-center pb-2 border-b border-border/60">
                    {(() => {
                      const liveTick = getTicker(c.symbol)
                      const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                      const displayLtp = livePrice ?? c.ltp
                      const entryDelta = c.entry_price > 0 ? ((displayLtp - c.entry_price) / c.entry_price * 100) : null
                      return (
                        <div className="flex flex-col items-center">
                          <span className="text-[9.5px] text-muted block">
                            LTP {livePrice ? <span className="text-emerald-500 text-[8px] ml-0.5">● LIVE</span> : <span className="text-muted text-[8px] ml-0.5">EOD</span>}
                          </span>
                          <span className="font-bold text-text">₹{displayLtp.toLocaleString('en-IN', { minimumFractionDigits: 1 })}</span>
                          {entryDelta != null && (
                            <span className={`text-[8.5px] ${Math.abs(entryDelta) <= 1 ? 'text-emerald-600 dark:text-emerald-400 font-bold' : entryDelta > 3 ? 'text-amber-600 dark:text-amber-400' : 'text-muted'}`}>
                              {entryDelta >= 0 ? '+' : ''}{entryDelta.toFixed(1)}% vs entry
                            </span>
                          )}
                        </div>
                      )
                    })()}
                    <div>
                      <span className="text-[9.5px] text-muted block">ENTRY</span>
                      <span className="font-bold text-text">₹{c.entry_price.toFixed(1)}</span>
                    </div>
                    <div>
                      <span className="text-[9.5px] text-muted block">STOP LOSS</span>
                      <span className="font-bold text-rose-600 dark:text-rose-400">₹{c.stop_loss.toFixed(1)}</span>
                    </div>
                  </div>

                  {/* Row 2: 3-Target Ladder + Payoff */}
                  <div className="grid grid-cols-4 gap-1 text-center">
                    <div className="p-1 rounded bg-surface/50 border border-emerald-500/20" title="Target 1: +2.0R Breakeven Scale-out">
                      <span className="text-[9px] text-emerald-600 dark:text-emerald-400 font-semibold block">T1 (+2R)</span>
                      <span className="font-bold text-emerald-600 dark:text-emerald-400 text-xs">₹{c.target_1.toFixed(1)}</span>
                    </div>
                    <div className="p-1 rounded bg-surface/50 border border-amber-500/20" title="Target 2: +3.5R Positional Swing Target">
                      <span className="text-[9px] text-amber-600 dark:text-amber-400 font-semibold block">T2 (+3.5R)</span>
                      <span className="font-bold text-amber-600 dark:text-amber-400 text-xs">
                        ₹{(c.target_2 || (c.entry_price + (3.5 * Math.max(0.5, c.entry_price - c.stop_loss)))).toFixed(1)}
                      </span>
                    </div>
                    <div className="p-1 rounded bg-surface/50 border border-purple-500/20" title="Moonshot Target: +6.5R Multibagger Horizon">
                      <span className="text-[9px] text-purple-600 dark:text-purple-400 font-semibold block">🚀 T3++</span>
                      <span className="font-bold text-purple-600 dark:text-purple-400 text-xs">
                        ₹{(c.target_moonshot || (c.entry_price + (6.5 * Math.max(0.5, c.entry_price - c.stop_loss)))).toFixed(1)}
                      </span>
                    </div>
                    <div className="p-1 rounded bg-surface/50 border border-border" title="Risk:Reward Multiple">
                      <span className="text-[9px] text-muted block">PAYOFF</span>
                      <span className="font-bold text-text text-xs">1:{c.risk_reward_ratio ?? '—'}</span>
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center justify-between pt-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => openDecisionDrawer(c)}
                    className="text-xs font-bold px-2.5 py-1.5 rounded-lg border border-gold/30 bg-gold/15 text-amber-600 dark:text-amber-400 hover:bg-gold/25 flex items-center gap-1.5 transition-all cursor-pointer"
                  >
                    <span>🧠</span>
                    <span>AI Decision Matrix</span>
                  </button>

                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={(e) => handleAddToIncubation(c, e)}
                      className="px-2 py-1.5 rounded-lg border border-purple-500/40 bg-purple-500/15 text-xs font-semibold text-purple-600 dark:text-purple-400 hover:bg-purple-500/25 transition-all cursor-pointer flex items-center gap-1"
                      title="Retain in Cycle Incubation Pipeline"
                    >
                      <span>📌</span>
                      <span>Retain</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (onNavigateToTerminal) onNavigateToTerminal(c.symbol)
                        else setActiveView('terminal')
                      }}
                      className="px-2.5 py-1.5 rounded-lg border border-border bg-elevated text-xs font-medium text-muted hover:text-text hover:border-subtle transition-all cursor-pointer"
                    >
                      Chart
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (onOpenOrderTicket) {
                          const liveTick = getTicker(c.symbol)
                          const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                          onOpenOrderTicket({
                            symbol: c.symbol,
                            exchange: 'NSE',
                            price: livePrice ?? c.entry_price,
                            stopLoss: c.stop_loss,
                            target: c.target_1,
                            target2: c.target_2,
                            targetMoonshot: c.target_moonshot,
                            _priceSource: livePrice ? 'LIVE' : 'EOD_ENTRY',
                          })
                        }
                      }}
                      className="px-2.5 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/15 text-xs font-bold text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/25 transition-all cursor-pointer"
                    >
                      ⚡ Order
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── AI 5W+H DECISION MATRIX DRAWER ──────────────────────────────── */}
      {isDrawerOpen && (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-black/30 dark:bg-black/65 backdrop-blur-sm animate-in fade-in duration-150"
          onClick={() => setIsDrawerOpen(false)}
        >
          <div
            className="w-full max-w-2xl h-full flex flex-col border-l border-border bg-panel shadow-modal overflow-hidden font-ui animate-in slide-in-from-right duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-border bg-surface">
              <div className="flex items-center gap-3">
                <span className="text-2xl p-1.5 rounded-lg bg-panel border border-border">
                  {activeCandidate?.sector_icon || '🏢'}
                </span>
                <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-bold text-text">{activeCandidate?.symbol}</h2>
                  <span className="text-xs text-muted">| {activeCandidate?.name}</span>
                  <Badge
                    variant={decisionMatrix?.verdict?.includes('BUY') ? 'emerald' : 'gold'}
                    size="sm"
                  >
                    {decisionMatrix?.verdict || 'ANALYZING...'}
                  </Badge>
                </div>
                <p className="text-[11px] text-muted">
                  {(() => {
                    const liveTick = getTicker(activeCandidate?.symbol)
                    const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                    const displayLtp = livePrice ?? activeCandidate?.ltp
                    return (
                      <>
                        <span className="font-mono font-bold text-text">LTP: ₹{displayLtp}</span>
                        {livePrice ? (
                          <span className="ml-1 text-[9px] text-emerald-500 font-mono">● LIVE</span>
                        ) : (
                          <span className="ml-1 text-[9px] text-muted font-mono">EOD</span>
                        )}
                      </>
                    )
                  })()}
                  {' '}({formatPct(activeCandidate?.day_change_pct).text}) •{' '}
                  {activeCandidate?.sector} •{' '}
                  <span className="text-text font-mono font-bold">{activeCandidate?.cap_tier} CAP</span> •{' '}
                  <span className="font-mono">Turnover: ₹{activeCandidate?.turnover_20d_cr ? activeCandidate.turnover_20d_cr.toFixed(2) : '0.00'} Cr/d</span>
                </p>
              </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (onOpenOrderTicket && activeCandidate) {
                      const liveTick = getTicker(activeCandidate.symbol)
                      const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                      onOpenOrderTicket({
                        symbol: activeCandidate.symbol,
                        exchange: 'NSE',
                        price: livePrice ?? activeCandidate.entry_price,
                        stopLoss: activeCandidate.stop_loss,
                        target: activeCandidate.target_1,
                        _priceSource: livePrice ? 'LIVE' : 'EOD_ENTRY',
                      })
                    }
                  }}
                  className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-all cursor-pointer ${
                    activeCandidate?.circuit_state === 'UPPER_CIRCUIT_LOCKED'
                      ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30'
                      : 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25'
                  }`}
                  title={activeCandidate?.circuit_state === 'UPPER_CIRCUIT_LOCKED' ? 'Stock is Upper Circuit Locked' : 'Open Order Ticket'}
                >
                  {activeCandidate?.circuit_state === 'UPPER_CIRCUIT_LOCKED' ? '🔒 Circuit Ticket (Limit)' : '⚡ Order Ticket'}
                </button>
                <button
                  type="button"
                  onClick={() => setIsDrawerOpen(false)}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-muted hover:text-text border border-border hover:bg-black/5 dark:hover:bg-white/10 transition-all cursor-pointer"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Drawer Body Scroll */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {decisionLoading && !decisionMatrix ? (
                <div className="flex flex-col items-center justify-center h-48 gap-3">
                  <div className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin border-amber-400" />
                  <span className="text-xs font-mono text-muted uppercase tracking-wider">
                    Assembling 5-Persona Council & Synthesizing 5W+H Decision Matrix...
                  </span>
                </div>
              ) : (
                <>
                  {/* Upper Circuit Locked Warning Shield */}
                  {activeCandidate?.circuit_state === 'UPPER_CIRCUIT_LOCKED' && (
                    <div className="p-3.5 rounded-xl bg-rose-500/15 border border-rose-500/30 text-rose-800 dark:text-rose-200 text-xs flex items-start gap-2.5 shadow-sm">
                      <span className="text-xl">🔒</span>
                      <div className="space-y-1">
                        <span className="font-bold text-rose-700 dark:text-rose-300 block text-xs tracking-wide uppercase font-mono">
                          Upper Circuit Locked (100% Buyers / Zero Sellers)
                        </span>
                        <p className="text-[11px] leading-relaxed text-rose-900/80 dark:text-rose-200/90 font-ui">
                          Stock is frozen at upper price band. Immediate Market buy orders will be REJECTED by exchange matching engines. Place a Limit GTT order at the circuit band or wait for volatility unlocks before entering.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* 10-Second Executive Decision Matrix Hero Card */}
                  <div className="p-4 rounded-xl border border-gold/35 bg-gradient-to-br from-gold-dim/60 to-panel space-y-3 font-ui shadow-xs">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono font-bold uppercase tracking-wider text-muted">
                          10-Second Executive Verdict:
                        </span>
                        <span
                          className={`text-xs px-2.5 py-0.5 rounded-full font-bold uppercase font-mono ${
                            activeCandidate?.circuit_state === 'UPPER_CIRCUIT_LOCKED'
                              ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30'
                              : activeCandidate?.executive_verdict?.includes('STRONG')
                              ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                              : 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30'
                          }`}
                        >
                          {activeCandidate?.executive_verdict || '⚡ HIGH CONVICTION SETUP'}
                        </span>
                      </div>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-panel border border-border text-emerald-600 dark:text-emerald-400 font-bold">
                        {activeCandidate?.data_quality_label || '💾 0ms Local Cache'}
                      </span>
                    </div>

                    <p className="text-xs text-text leading-relaxed font-medium">
                      {activeCandidate?.executive_summary || activeCandidate?.catalyst_summary}
                    </p>

                    {/* 3-Pillar Confluence Scoreboard */}
                    <div className="grid grid-cols-4 gap-2 pt-1 border-t border-border/50 text-center font-mono">
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">⚡ Technical</span>
                        <span className="text-xs font-bold text-cyan-700 dark:text-cyan-400">
                          {activeCandidate?.technical_score != null ? `${activeCandidate.technical_score}/40` : '—'}
                        </span>
                      </div>
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">🔄 Sector</span>
                        <span className="text-xs font-bold text-amber-700 dark:text-amber-400">
                          {activeCandidate?.sector_score != null ? `${activeCandidate.sector_score}/30` : '—'}
                        </span>
                      </div>
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">🛡️ Forensic</span>
                        <span className="text-xs font-bold text-emerald-700 dark:text-emerald-400">
                          {activeCandidate?.quality_score != null ? `${activeCandidate.quality_score}/30` : '—'}
                        </span>
                      </div>
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">🎯 R:R</span>
                        <span className="text-xs font-bold text-text">
                          {activeCandidate?.risk_reward_ratio != null ? `1:${activeCandidate.risk_reward_ratio}` : '—'}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Confluence Radar Ribbon */}
                  <div className="p-3 rounded-xl border border-border bg-surface grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-center font-mono">
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Minervini</span>
                      <span className="text-xs font-bold text-text">
                        {activeCandidate?.trend_template_passed}/8 ({activeCandidate?.weinstein_stage?.replace('STAGE_', 'S')})
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Squeeze / VCP</span>
                      <span className="text-xs font-bold text-cyan-700 dark:text-cyan-400">
                        {activeCandidate?.squeeze_state === 'COILING'
                          ? `Coiling (${activeCandidate?.squeeze_duration}b)`
                          : activeCandidate?.vcp_detected
                          ? `VCP ${activeCandidate?.vcp_tightness_pct}%`
                          : 'Normal'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">RVOL (20D)</span>
                      <span className="text-xs font-bold text-emerald-700 dark:text-emerald-400">
                        {activeCandidate?.rvol_20d}x
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Sector RRG</span>
                      <span className="text-xs font-bold text-amber-700 dark:text-amber-400">
                        {activeCandidate?.rrg_quadrant} ({activeCandidate?.sector_tailwind_score}/100)
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">20D Liq</span>
                      <span className="text-xs font-bold text-text">
                        ₹{activeCandidate?.turnover_20d_cr ? activeCandidate.turnover_20d_cr.toFixed(1) : '0.0'} Cr
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">W-Trend</span>
                      <span className={`text-xs font-bold ${activeCandidate?.weekly_stage === 'STAGE_2_UPTREND' ? 'text-yellow-700 dark:text-yellow-400' : 'text-muted'}`}>
                        {activeCandidate?.weekly_stage === 'STAGE_2_UPTREND' ? '👑 W-Stage 2' : 'Neutral'}
                      </span>
                    </div>
                  </div>

                  {/* 5W+H Navigation Tabs */}
                  <div className="flex items-center gap-1 border-b border-border pb-1 text-xs">
                    {[
                      { id: 'what', label: '🎯 WHAT (Thesis)', icon: '' },
                      { id: 'where', label: '📍 WHERE (Levels)', icon: '' },
                      { id: 'when', label: '⏰ WHEN (Timing)', icon: '' },
                      { id: 'how', label: '🛠️ HOW (Execution)', icon: '' },
                      { id: 'correlations', label: '🌐 CORRELATIONS', icon: '' },
                      { id: 'invalidation', label: '⚠️ INVALIDATION', icon: '' },
                    ].map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setActiveDrawerTab(tab.id)}
                        className={`px-2.5 py-1 rounded-md font-bold text-xs transition-all cursor-pointer ${
                          activeDrawerTab === tab.id
                            ? 'bg-amber-500/20 text-amber-700 dark:text-amber-400 border border-amber-500/40'
                            : 'text-muted hover:text-text hover:bg-black/5 dark:hover:bg-white/5'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {/* Tab Content Panels */}
                  <div className="p-4 rounded-xl border border-border bg-surface text-xs leading-relaxed">
                    {activeDrawerTab === 'what' && (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <h3 className="font-bold text-text text-sm">
                            {decisionMatrix?.what?.thesis_title || 'Core Inflection Thesis'}
                          </h3>
                        </div>
                        <p className="text-text-dim">
                          {decisionMatrix?.what?.primary_catalyst}
                        </p>
                        <div>
                          <span className="font-bold text-amber-700 dark:text-amber-400 block mb-1">
                            🛡️ False Breakout Protection Checks:
                          </span>
                          <ul className="list-disc pl-4 space-y-1 text-muted">
                            {decisionMatrix?.what?.false_breakout_checks?.map((chk, i) => (
                              <li key={i}>{chk}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'where' && (
                      <div className="space-y-3 font-mono">
                        <div className="flex items-center justify-between">
                          <h3 className="font-bold text-text text-sm font-ui">
                            📍 Price Coordinates & Risk Boundaries
                          </h3>
                          {(() => {
                            const liveTick = getTicker(activeCandidate?.symbol)
                            const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                            return livePrice ? (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                                LIVE FEED ACTIVE
                              </span>
                            ) : (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30">
                                EOD BENCHMARK
                              </span>
                            )
                          })()}
                        </div>

                        {/* Live Price Context Strip */}
                        {(() => {
                          const liveTick = getTicker(activeCandidate?.symbol)
                          const livePrice = liveTick?.ltp != null && liveTick.ltp > 0 ? liveTick.ltp : null
                          const entryPrice = activeCandidate?.entry_price
                          const stopPrice = activeCandidate?.stop_loss
                          const t1Price = activeCandidate?.target_1
                          const distFromEntryPct = (livePrice && entryPrice) ? ((livePrice - entryPrice) / entryPrice * 100) : null
                          const isStopBreached = livePrice && stopPrice && livePrice <= stopPrice
                          const isTargetReached = livePrice && t1Price && livePrice >= t1Price

                          return (
                            <div className="space-y-2">
                              <div className="p-2.5 rounded-lg bg-panel border border-border flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                  <span className="text-muted font-ui text-[11px]">CMP:</span>
                                  <span className="text-base font-bold text-text">
                                    ₹{livePrice ? livePrice.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : activeCandidate?.ltp?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                                  </span>
                                  {livePrice ? (
                                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 font-bold">
                                      LIVE
                                    </span>
                                  ) : (
                                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-elevated text-muted border border-border">
                                      EOD
                                    </span>
                                  )}
                                </div>
                                {distFromEntryPct != null && (
                                  <div className="flex items-center gap-1 font-ui text-[11px]">
                                    <span className="text-muted">Dist to Entry:</span>
                                    <span className={`font-bold font-mono ${Math.abs(distFromEntryPct) <= 1 ? 'text-emerald-600 dark:text-emerald-400' : distFromEntryPct > 1 ? 'text-amber-600 dark:text-amber-400' : 'text-rose-600 dark:text-rose-400'}`}>
                                      {distFromEntryPct > 0 ? `+${distFromEntryPct.toFixed(2)}%` : `${distFromEntryPct.toFixed(2)}%`}
                                    </span>
                                  </div>
                                )}
                              </div>

                              {isStopBreached && (
                                <div className="p-2 rounded bg-rose-500/15 border border-rose-500/40 text-rose-700 dark:text-rose-300 text-xs font-ui flex items-center gap-2">
                                  <span>⚠️</span>
                                  <span>
                                    <strong>SL BREACHED:</strong> Live price (₹{livePrice}) is at or below stop loss (₹{stopPrice}). Setup invalidated.
                                  </span>
                                </div>
                              )}

                              {isTargetReached && (
                                <div className="p-2 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-700 dark:text-emerald-300 text-xs font-ui flex items-center gap-2">
                                  <span>🎯</span>
                                  <span>
                                    <strong>T1 REACHED:</strong> Live price (₹{livePrice}) has hit Target 1 (₹{t1Price}). Consider partial scale-out.
                                  </span>
                                </div>
                              )}
                            </div>
                          )
                        })()}
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">ENTRY ZONE</span>
                            <span className="font-bold text-text text-sm">
                              {decisionMatrix?.where?.entry_zone}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">STRUCTURAL SL</span>
                            <span className="font-bold text-rose-600 dark:text-rose-400 text-sm">
                              {decisionMatrix?.where?.stop_loss}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">T1 (+2R BE)</span>
                            <span className="font-bold text-emerald-600 dark:text-emerald-400 text-sm">
                              {decisionMatrix?.where?.target_1}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">T2 (+3.5R SWING)</span>
                            <span className="font-bold text-amber-600 dark:text-amber-400 text-sm">
                              {decisionMatrix?.where?.target_2}
                            </span>
                          </div>
                        </div>
                        <div className="p-2.5 rounded bg-panel border border-border flex items-center justify-between">
                          <span className="text-muted font-ui">🚀 T3 / Moonshot (+6.5R):</span>
                          <span className="font-bold text-purple-600 dark:text-purple-400">
                            {decisionMatrix?.where?.target_moonshot}
                          </span>
                        </div>
                        <p className="text-[11px] text-muted font-ui">
                          {decisionMatrix?.where?.sizing_guideline}
                        </p>
                      </div>
                    )}

                    {activeDrawerTab === 'when' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-text text-sm">
                          ⏰ Timing Window & Squeeze Countdown
                        </h3>
                        <div className="p-3 rounded-lg bg-panel border border-border space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-muted">Timing Status:</span>
                            <span className="font-bold text-amber-600 dark:text-amber-400">
                              {decisionMatrix?.when?.timing_status}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-muted">Squeeze Status:</span>
                            <span className="text-text-dim">
                              {decisionMatrix?.when?.squeeze_countdown}
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-muted">Time Invalidation Stop:</span>
                            <span className="text-text font-mono font-bold">
                              {decisionMatrix?.when?.time_stop_days} Trading Days
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-muted">Holding Horizon:</span>
                            <span className="text-text font-bold">
                              {decisionMatrix?.when?.holding_period}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'how' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-text text-sm">
                          🛠️ Step-by-Step Tactical Execution Playbook
                        </h3>
                        <div className="space-y-2 text-text-dim">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-amber-600 dark:text-amber-400 block mb-0.5">1. Order Type:</span>
                            <p>{decisionMatrix?.how?.order_strategy}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-emerald-600 dark:text-emerald-400 block mb-0.5">2. Scaling & Breakeven:</span>
                            <p>{decisionMatrix?.how?.scaling_plan}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-cyan-600 dark:text-cyan-400 block mb-0.5">3. Trailing Mechanics:</span>
                            <p>{decisionMatrix?.how?.trailing_mechanics}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-purple-600 dark:text-purple-400 block mb-0.5">4. Moonshot Compounder:</span>
                            <p>{decisionMatrix?.how?.moonshot_management}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'correlations' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-text text-sm">
                          🌐 Cross-Market Dots Connected & Correlations
                        </h3>
                        <div className="space-y-2 text-text-dim">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-text block mb-0.5">Global Macro Transmission:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.macro_regime}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-text block mb-0.5">Sector RRG Trajectory:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.sector_rrg_tailwind}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-text block mb-0.5">Options & Smart Money Flow:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.options_smart_money}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-text block mb-0.5">Crude Oil Transmission:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.crude_oil_impact}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'invalidation' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-rose-600 dark:text-rose-400 text-sm">
                          ⚠️ Hard Structural Invalidation Triggers
                        </h3>
                        <div className="space-y-2 text-text-dim">
                          <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/30">
                            <span className="font-bold text-rose-600 dark:text-rose-400 block mb-0.5">Hard Stop Rule:</span>
                            <p>{decisionMatrix?.invalidation?.hard_stop_condition}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-amber-600 dark:text-amber-400 block mb-0.5">Time Stop Invalidation:</span>
                            <p>{decisionMatrix?.invalidation?.time_invalidation}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-text block mb-0.5">Structural Breakdown:</span>
                            <p>{decisionMatrix?.invalidation?.structural_failure}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-text block mb-0.5">Gap-Down Protocol:</span>
                            <p>{decisionMatrix?.invalidation?.gap_down_protocol}</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Persona Council Insights */}
                  {decisionMatrix?.council_insights?.length > 0 && (
                    <div className="space-y-2">
                      <span className="text-[11px] font-bold text-muted font-mono uppercase">
                        Council Persona Testimonials:
                      </span>
                      <div className="space-y-2">
                        {decisionMatrix.council_insights.map((ins, i) => (
                          <div
                            key={i}
                            className="p-3 rounded-lg border border-border bg-surface text-xs"
                          >
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-bold text-amber-600 dark:text-amber-400">{ins.persona}</span>
                              <span className="text-[10px] text-muted font-mono">{ins.style}</span>
                            </div>
                            <p className="text-text-dim leading-relaxed">{ins.commentary}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Interactive Position Sizer */}
                  <div className="p-4 rounded-xl border border-border bg-surface space-y-3 font-mono">
                    <div className="flex items-center justify-between font-ui">
                      <h4 className="font-bold text-text text-xs flex items-center gap-1.5">
                        <span>⚖️</span>
                        <span>ATR Volatility Position Sizer</span>
                      </h4>
                      <span className="text-[10px] text-muted">Max Risk Parity</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div>
                        <span className="text-[10px] text-muted block font-ui mb-1">Account Capital (₹):</span>
                        <input
                          type="number"
                          value={sizerCapital}
                          onChange={(e) => setSizerCapital(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 rounded bg-panel border border-border text-text font-bold outline-none focus:border-gold"
                        />
                      </div>
                      <div>
                        <span className="text-[10px] text-muted block font-ui mb-1">Max Risk (%):</span>
                        <input
                          type="number"
                          step="0.1"
                          value={sizerRiskPct}
                          onChange={(e) => setSizerRiskPct(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 rounded bg-panel border border-border text-amber-600 dark:text-amber-400 font-bold outline-none focus:border-gold"
                        />
                      </div>
                    </div>

                    <div className="p-2.5 rounded bg-panel border border-border grid grid-cols-3 gap-2 text-center text-xs">
                      <div>
                        <span className="text-[10px] text-muted font-ui block">ALLOCATED SHARES</span>
                        <span className="font-bold text-text text-sm">{calculatedPosition.shares}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui block">CAPITAL (₹)</span>
                        <span className="font-bold text-text text-sm">
                          ₹{calculatedPosition.capital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui block">MAX RISK (₹)</span>
                        <span className="font-bold text-rose-600 dark:text-rose-400 text-sm">
                          ₹{calculatedPosition.riskAmount.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Interactive Dot-Connecting Chat */}
                  <div className="p-4 rounded-xl border border-border bg-surface space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="font-bold text-text text-xs flex items-center gap-1.5">
                        <span>💬</span>
                        <span>Ask Inflection Copilot (Connect Dots)</span>
                      </h4>
                      <span className="text-[10px] text-muted font-mono">Live Grounded AI</span>
                    </div>

                    {/* Quick Question Chips */}
                    <div className="flex flex-wrap gap-1.5">
                      {[
                        'Why prefer this over a market order?',
                        'What if Crude Oil spikes?',
                        'Explain the exact invalidation rule',
                        'Check promoter pledging & governance',
                      ].map((chip, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => handleSendDrawerChat(chip)}
                          className="text-[10px] px-2 py-0.5 rounded-full border text-text-dim hover:text-amber-600 dark:hover:text-amber-400 hover:border-gold/40 bg-panel transition-all cursor-pointer"
                        >
                          {chip}
                        </button>
                      ))}
                    </div>

                    {/* Chat Messages Log */}
                    <div
                      ref={chatScrollRef}
                      className="max-h-48 overflow-y-auto space-y-2 p-2.5 rounded-lg bg-panel border border-border text-xs"
                    >
                      {chatMessages.map((msg, i) => (
                        <div
                          key={i}
                          className={`p-2 rounded-lg leading-relaxed ${
                            msg.role === 'user'
                              ? 'bg-amber-500/15 border border-amber-500/30 text-text ml-6'
                              : msg.role === 'system'
                              ? 'text-muted font-mono text-[10px]'
                              : 'bg-elevated border border-border text-text-dim mr-4'
                          }`}
                        >
                          <span className="font-bold text-[10px] block text-muted mb-0.5 uppercase font-mono">
                            {msg.role === 'user' ? 'You' : msg.role === 'assistant' ? 'Copilot' : 'System'}
                          </span>
                          <p>{msg.text}</p>
                        </div>
                      ))}
                      {chatLoading && (
                        <div className="text-[10px] text-muted font-mono animate-pulse">
                          Connecting dots & synthesizing answer...
                        </div>
                      )}
                    </div>

                    {/* Chat Input */}
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        placeholder="Ask anything about this setup..."
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleSendDrawerChat()
                        }}
                        className="flex-1 text-xs px-3 py-2 rounded-lg border outline-none text-text bg-panel border-border focus:border-gold transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => handleSendDrawerChat()}
                        disabled={chatLoading || !chatInput.trim()}
                        className="text-xs font-bold px-3 py-2 rounded-lg border text-amber-600 dark:text-amber-400 bg-amber-500/15 border-amber-500/30 hover:bg-amber-500/25 transition-all cursor-pointer disabled:opacity-50"
                      >
                        Send
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
