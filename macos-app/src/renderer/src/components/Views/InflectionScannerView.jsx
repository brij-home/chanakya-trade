import { useState, useEffect, useMemo, useRef } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import { formatINR, formatPct } from '../../utils/formatINR'
import UnavailableState from '../Common/UnavailableState'
import Badge from '../Common/Badge'

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
  }, [])

  // ── 2. Run Inflection Scan ──────────────────────────────────────────
  const executeScan = async (
    targetUniverse = universe,
    overrideTurnover = minTurnoverCr,
    overrideCap = capTierFilter
  ) => {
    setIsScanning(true)
    const abortCtrl = new AbortController()

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
      const res = await call('/skills/inflection_scan', {
        universe: targetUniverse,
        archetype: archetypeFilter,
        timing: timingFilter,
        min_score: minScore,
        max_results: 60,
        min_turnover_cr: overrideTurnover,
        cap_tier: overrideCap,
        use_local_cache: true,
        sync_missing: false,
      })
      const resultData = res?.data ?? res
      setScanResult(resultData)
      setLastScanTime(new Date().toLocaleTimeString('en-IN', { hour12: false }))
    } catch (err) {
      console.error('Inflection scan failed:', err)
    } finally {
      setIsScanning(false)
      stopActivity()
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
        // Auto re-scan using the newly cached EOD store
        await executeScan(universe, minTurnoverCr, capTierFilter)
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

  // Trigger scan when universe, archetype, timing, minScore, minTurnoverCr, or capTierFilter changes
  useEffect(() => {
    executeScan(universe, minTurnoverCr, capTierFilter)
  }, [universe, archetypeFilter, timingFilter, minScore, minTurnoverCr, capTierFilter])

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

  const activeFilterCount = useMemo(() => {
    let count = 0
    if (searchQuery.trim()) count++
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

  // Interactive sortable header renderer
  const renderHeader = (colKey, label, align = 'left', extraClass = '') => {
    const isSorted = sortColumn === colKey
    const dir = sortDirection
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
    const avgRR =
      total > 0
        ? (list.reduce((acc, c) => acc + (c.risk_reward_ratio || 2.0), 0) / total).toFixed(1)
        : '0.0'
    const topSector = scanResult?.top_sectors?.[0]?.sector || 'Mixed'

    return { total, highConviction, coiling, triggerNow, avgRR, topSector }
  }, [scanResult])

  return (
    <div className="flex flex-col flex-1 h-full overflow-hidden select-none bg-void text-text">
      {/* ── TOP CONTROL BAR ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-border bg-surface">
        {/* Left: Title & Pulse */}
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-xl font-bold text-base bg-gold/15 border border-gold text-amber-600 dark:text-amber-400 shadow-glow-gold">
            📡
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold tracking-wide uppercase font-mono text-text">
                Inflection & Multibagger Radar
              </h1>
              <Badge variant="emerald" size="sm">
                AI 5W+H Matrix
              </Badge>
            </div>
            <p className="text-[11px] text-muted">
              Pinpoints high-asymmetry pivots before explosive expansion across NSE/BSE
            </p>
          </div>
        </div>

        {/* Center/Right Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Universe Selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted font-mono uppercase">Universe:</span>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="select-input"
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

          {/* Liquidity Floor (20D Median Turnover) */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted font-mono uppercase" title="Minimum 20-Day Median Turnover (Cr) to exclude illiquid operator traps">
              Min Liq:
            </span>
            <select
              value={minTurnoverCr}
              onChange={(e) => setMinTurnoverCr(Number(e.target.value))}
              className="select-input font-mono"
              title="20-Day Median Turnover filter"
            >
              <option value={0}>All (₹0)</option>
              <option value={0.25}>₹25 L</option>
              <option value={0.5}>₹50 L (Rec)</option>
              <option value={1.0}>₹1.0 Cr</option>
              <option value={2.0}>₹2.0 Cr</option>
              <option value={5.0}>₹5.0 Cr</option>
            </select>
          </div>

          {/* Market Cap Tier Selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted font-mono uppercase">Cap:</span>
            <select
              value={capTierFilter}
              onChange={(e) => setCapTierFilter(e.target.value)}
              className={`select-input ${capTierFilter !== 'ALL' ? 'active-filter' : ''}`}
            >
              <option value="ALL">All Caps</option>
              <option value="LARGE">🏛️ Large</option>
              <option value="MID">⚡ Mid</option>
              <option value="SMALL">🚀 Small</option>
              <option value="MICRO">🌱 Micro</option>
            </select>
          </div>

          {/* Sector Filter Selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted font-mono uppercase">Sector:</span>
            <select
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
              className={`select-input max-w-[130px] truncate ${sectorFilter !== 'ALL' ? 'active-filter' : ''}`}
              title="Filter by Sector"
            >
              <option value="ALL">All Sectors ({availableSectors.length})</option>
              {availableSectors.map((sec) => (
                <option key={sec.name} value={sec.name}>
                  {sec.name} ({sec.count})
                </option>
              ))}
            </select>
          </div>

          {/* Conviction / Min Score Selector */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted font-mono uppercase">Score:</span>
            <select
              value={minScoreFilter}
              onChange={(e) => setMinScoreFilter(Number(e.target.value))}
              className={`select-input font-mono ${minScoreFilter > 0 ? 'active-filter' : ''}`}
              title="Filter by Min Inflection Score"
            >
              <option value={0}>All Scores</option>
              <option value={75}>🔥 75+ (High Conviction)</option>
              <option value={65}>⚡ 65+ (Strong Setup)</option>
              <option value={50}>📈 50+ (Baseline)</option>
            </select>
          </div>

          {/* Search Input with inline clear button */}
          <div className="relative flex items-center">
            <input
              type="text"
              placeholder="Search symbol, sector, pattern..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`search-input w-36 sm:w-44 focus:w-52 ${searchQuery ? 'border-gold' : ''}`}
            />
            <span className="absolute left-2 text-xs text-muted pointer-events-none">🔍</span>
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 text-xs text-muted hover:text-text cursor-pointer"
                title="Clear search"
              >
                ✕
              </button>
            )}
          </div>

          {/* View Mode Toggle */}
          <div className="flex items-center rounded-lg border border-border p-0.5 bg-elevated">
            <button
              type="button"
              onClick={() => setViewMode('table')}
              className={`text-xs px-2 py-1 rounded transition-all cursor-pointer ${
                viewMode === 'table' ? 'font-bold bg-panel text-amber-600 dark:text-amber-400 shadow-xs' : 'text-muted hover:text-text'
              }`}
              title="Table View"
            >
              ☰ Table
            </button>
            <button
              type="button"
              onClick={() => setViewMode('cards')}
              className={`text-xs px-2 py-1 rounded transition-all cursor-pointer ${
                viewMode === 'cards' ? 'font-bold bg-panel text-amber-600 dark:text-amber-400 shadow-xs' : 'text-muted hover:text-text'
              }`}
              title="Cards Matrix"
            >
              ☷ Cards
            </button>
          </div>

          {/* Local SQLite EOD Store Sync Button */}
          <button
            type="button"
            onClick={executeEodSync}
            disabled={isSyncingEod || isScanning}
            className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-lg border transition-all cursor-pointer ${
              isSyncingEod
                ? 'bg-sapphire/20 border-sapphire text-blue-600 dark:text-blue-400'
                : 'bg-elevated border-border text-text hover:border-subtle'
            }`}
            title="Bulk sync daily bars into local SQLite store to avoid future API hits"
          >
            <span className={isSyncingEod ? 'animate-spin' : ''}>{isSyncingEod ? '⏳' : '⚡'}</span>
            <span>{isSyncingEod ? 'Syncing...' : 'Sync EOD'}</span>
          </button>

          {/* Refresh Scan Button */}
          <button
            type="button"
            onClick={() => executeScan(universe)}
            disabled={isScanning}
            className="flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg border border-gold/40 bg-gold/15 text-amber-600 dark:text-amber-400 hover:bg-gold/25 shadow-xs cursor-pointer transition-all"
          >
            <span className={isScanning ? 'animate-spin' : ''}>🔄</span>
            <span>{isScanning ? 'Scanning...' : 'Rescan'}</span>
          </button>
        </div>
      </div>

      {/* ── SYNC STATUS & RISK SHIELD BANNER ─────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-1.5 border-b border-border bg-surface text-xs font-mono">
        <div className="flex items-center gap-3 flex-wrap">
          {syncStatusMsg ? (
            <div className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
              <span className="animate-pulse">⚡</span>
              <span>{syncStatusMsg}</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>
                💾 Local Store: {storeStats ? `${storeStats.cached_symbols_count} stocks (${storeStats.total_bars_count?.toLocaleString()} bars, ${storeStats.fundamentals_count || 0} fundamentals, 0ms local)` : 'Active'}
              </span>
            </div>
          )}
        </div>

        {scanResult?.filtered_out_liquidity_count > 0 && (
          <Badge variant="rose" size="xs" title="Illiquid stocks excluded by turnover floor to prevent operator traps">
            <span>🛡️</span>
            <span>{scanResult.filtered_out_liquidity_count} illiquid stocks excluded (&lt; ₹{minTurnoverCr} Cr median turnover)</span>
          </Badge>
        )}
      </div>

      {/* ── FILTER CHIPS STRIP & QUICK CONDITIONS ─────────────────────── */}
      <div className="flex flex-col gap-2 px-4 py-2 border-b border-border bg-panel text-xs">
        {/* Row 1: Archetype Chips & Timing Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          {/* Archetype Chips */}
          <div className="flex flex-wrap items-center gap-1.5 overflow-x-auto py-0.5">
            <span className="text-[10px] text-muted uppercase font-mono mr-1">Archetype:</span>
            {ARCHETYPE_TABS.map((tab) => {
              const active = archetypeFilter === tab.id
              const count = archetypeCounts[tab.id] ?? 0
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setArchetypeFilter(tab.id)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all cursor-pointer ${
                    active
                      ? 'bg-gold/15 border border-gold text-amber-600 dark:text-amber-400 shadow-xs'
                      : 'bg-elevated border border-border text-muted hover:text-text hover:border-subtle'
                  }`}
                >
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                  <span className="text-[9px] px-1 rounded-full font-mono bg-surface text-text">
                    {count}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Timing Filters */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-muted uppercase font-mono mr-1">Timing:</span>
            {TIMING_TABS.map((tab) => {
              const active = timingFilter === tab.id
              const count = timingCounts[tab.id] ?? 0
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setTimingFilter(tab.id)}
                  className={`flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium transition-all cursor-pointer ${
                    active
                      ? 'bg-emerald/15 border border-emerald/40 text-emerald-700 dark:text-emerald-300 font-bold'
                      : 'text-muted hover:text-text hover:bg-elevated border border-transparent'
                  }`}
                >
                  <span>{tab.label}</span>
                  {count > 0 && <span className="text-[9px] font-mono opacity-80">({count})</span>}
                </button>
              )
            })}
          </div>
        </div>

        {/* Row 2: Quick Condition Filters & Active Filter Reset Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-border/30">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] text-muted uppercase font-mono mr-1">Conditions:</span>

            <button
              type="button"
              onClick={() => setFilterCoilingOnly((p) => !p)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-all cursor-pointer ${
                filterCoilingOnly
                  ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/40 shadow-xs'
                  : 'bg-elevated text-muted border-border hover:text-text'
              }`}
            >
              ⚡ Squeeze Coiling
            </button>

            <button
              type="button"
              onClick={() => setFilterVolumeSurge((p) => !p)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-all cursor-pointer ${
                filterVolumeSurge
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/40 shadow-xs'
                  : 'bg-elevated text-muted border-border hover:text-text'
              }`}
            >
              🔥 RVOL ≥ 1.5x
            </button>

            <button
              type="button"
              onClick={() => setFilterMinerviniOnly((p) => !p)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-all cursor-pointer ${
                filterMinerviniOnly
                  ? 'bg-gold/15 text-amber-600 dark:text-amber-400 border-gold/40 shadow-xs'
                  : 'bg-elevated text-muted border-border hover:text-text'
              }`}
            >
              👑 Minervini Stage 2
            </button>

            <button
              type="button"
              onClick={() => setFilterExcludeUCLocked((p) => !p)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-all cursor-pointer ${
                filterExcludeUCLocked
                  ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/40 shadow-xs'
                  : 'bg-elevated text-muted border-border hover:text-text'
              }`}
            >
              🛡️ Exclude UC Locked
            </button>

            <button
              type="button"
              onClick={() => setFilterHighRR((p) => !p)}
              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border transition-all cursor-pointer ${
                filterHighRR
                  ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-400 border-cyan-500/40 shadow-xs'
                  : 'bg-elevated text-muted border-border hover:text-text'
              }`}
            >
              🎯 R:R ≥ 2.5x
            </button>
          </div>

          {/* Active Filter Counter & Reset Button */}
          {activeFilterCount > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-amber-700 dark:text-amber-300 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">
                Filtered: {filteredCandidates.length} / {scanResult?.candidates?.length || 0} setups ({activeFilterCount} active)
              </span>
              <button
                type="button"
                onClick={resetAllFilters}
                className="text-[10px] font-bold text-rose-700 dark:text-rose-400 hover:text-rose-800 dark:hover:text-rose-300 px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/30 hover:bg-rose-500/20 transition-all cursor-pointer"
              >
                ✕ Reset Filters
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── EXECUTIVE SUMMARY METRICS STRIP ─────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 px-4 py-2.5 border-b border-border bg-surface">
        <div className="flex flex-col p-2.5 rounded-xl border border-border bg-elevated shadow-xs">
          <span className="text-[10px] text-muted font-mono uppercase tracking-wider">Scanned Universe</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold text-text font-mono">{summaryMetrics.total}</span>
            <span className="text-[10px] text-muted">Stocks</span>
          </div>
        </div>

        <div className="flex flex-col p-2.5 rounded-xl border border-border bg-elevated shadow-xs">
          <span className="text-[10px] text-muted font-mono uppercase tracking-wider">High Conviction (75+)</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono text-amber-600 dark:text-amber-400">
              {summaryMetrics.highConviction}
            </span>
            <span className="text-[10px] text-muted">Picks</span>
          </div>
        </div>

        <div className="flex flex-col p-2.5 rounded-xl border border-border bg-elevated shadow-xs">
          <span className="text-[10px] text-muted font-mono uppercase tracking-wider">Active Squeezes</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono text-cyan-700 dark:text-cyan-400">
              {summaryMetrics.coiling}
            </span>
            <span className="text-[10px] text-muted">Coiling</span>
          </div>
        </div>

        <div className="flex flex-col p-2.5 rounded-xl border border-border bg-elevated shadow-xs">
          <span className="text-[10px] text-muted font-mono uppercase tracking-wider">Breakout Fired</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono text-emerald-700 dark:text-emerald-300">
              {summaryMetrics.triggerNow}
            </span>
            <span className="text-[10px] text-muted">Actionable</span>
          </div>
        </div>

        <div className="flex flex-col p-2.5 rounded-xl border border-border bg-elevated shadow-xs">
          <span className="text-[10px] text-muted font-mono uppercase tracking-wider">Avg Risk/Reward</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono text-text">
              1:{summaryMetrics.avgRR}
            </span>
            <span className="text-[10px] text-muted">Payoff</span>
          </div>
        </div>

        <div className="flex flex-col p-2.5 rounded-xl border border-border bg-elevated shadow-xs">
          <span className="text-[10px] text-muted font-mono uppercase tracking-wider">Top Inflection Sector</span>
          <div className="flex items-baseline gap-1 mt-0.5 truncate">
            <span className="text-xs font-bold text-text truncate" title={summaryMetrics.topSector}>
              {summaryMetrics.topSector}
            </span>
          </div>
        </div>
      </div>

      {/* ── MAIN CANDIDATES VIEW CONTAINER ──────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4">
        {isScanning && filteredCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-gold border-t-transparent animate-spin" />
            <span className="text-xs font-mono tracking-wider text-muted uppercase">
              Screening 5 Inflection Engines & Computing Confluences...
            </span>
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
                  {renderHeader('entry_price', 'Trade Levels (Entry / SL / T1)', 'left')}
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
                              {c.technical_score || 35}T • {c.sector_score || 25}S • {c.quality_score || 25}Q
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

                      {/* LTP */}
                      <td className="py-2.5 px-2 text-right font-bold text-text">
                        ₹{c.ltp.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
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

                      {/* Trade Levels */}
                      <td className="py-2.5 px-2 font-mono text-[11px]">
                        <div className="flex items-center gap-1.5">
                          <span className="text-text font-bold" title="Entry">
                            ₹{c.entry_price.toFixed(1)}
                          </span>
                          <span className="text-muted">/</span>
                          <span className="text-rose-600 dark:text-rose-400 font-medium" title="Stop Loss">
                            ₹{c.stop_loss.toFixed(1)}
                          </span>
                          <span className="text-muted">/</span>
                          <span className="text-emerald-600 dark:text-emerald-400 font-bold" title="Target 1 (+2R)">
                            ₹{c.target_1.toFixed(1)}
                          </span>
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
                                onOpenOrderTicket({
                                  symbol: c.symbol,
                                  exchange: 'NSE',
                                  price: c.entry_price,
                                  stopLoss: c.stop_loss,
                                  target: c.target_1,
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
                    <span className="text-cyan-700 dark:text-cyan-400 font-semibold">⚡ Tech {c.technical_score || 35}/40</span>
                    <span className="text-muted">•</span>
                    <span className="text-amber-700 dark:text-amber-400 font-semibold">🔄 Sector {c.sector_score || 25}/30</span>
                    <span className="text-muted">•</span>
                    <span className="text-emerald-700 dark:text-emerald-400 font-semibold">🛡️ Qual {c.quality_score || 25}/30</span>
                  </div>
                  {c.executive_summary && (
                    <p className="text-[11px] text-text-dim leading-relaxed font-ui line-clamp-2 px-1">
                      {c.executive_summary}
                    </p>
                  )}
                </div>

                {/* Price & Levels Ribbon */}
                <div className="rounded-lg p-2.5 font-mono text-xs border border-border bg-panel flex items-center justify-between">
                  <div>
                    <span className="text-[10px] text-muted block">ENTRY</span>
                    <span className="font-bold text-text">₹{c.entry_price.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted block">STOP</span>
                    <span className="font-bold text-rose-600 dark:text-rose-400">₹{c.stop_loss.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted block">TARGET 1</span>
                    <span className="font-bold text-emerald-600 dark:text-emerald-400">₹{c.target_1.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted block">PAYOFF</span>
                    <span className="font-bold text-amber-600 dark:text-amber-400">1:{c.risk_reward_ratio}</span>
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
                          onOpenOrderTicket({
                            symbol: c.symbol,
                            exchange: 'NSE',
                            price: c.entry_price,
                            stopLoss: c.stop_loss,
                            target: c.target_1,
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
          className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-in fade-in duration-150"
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
                    LTP: ₹{activeCandidate?.ltp} ({formatPct(activeCandidate?.day_change_pct).text}) •{' '}
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
                      onOpenOrderTicket({
                        symbol: activeCandidate.symbol,
                        exchange: 'NSE',
                        price: activeCandidate.entry_price,
                        stopLoss: activeCandidate.stop_loss,
                        target: activeCandidate.target_1,
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
                          {activeCandidate?.technical_score || 35}/40
                        </span>
                      </div>
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">🔄 Sector Tailwind</span>
                        <span className="text-xs font-bold text-amber-700 dark:text-amber-400">
                          {activeCandidate?.sector_score || 25}/30
                        </span>
                      </div>
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">🛡️ Forensic Quality</span>
                        <span className="text-xs font-bold text-emerald-700 dark:text-emerald-400">
                          {activeCandidate?.quality_score || 25}/30
                        </span>
                      </div>
                      <div className="p-2 rounded bg-panel/70 border border-border/70">
                        <span className="text-[9px] text-muted uppercase block font-ui">🎯 Risk : Reward</span>
                        <span className="text-xs font-bold text-text">
                          1:{activeCandidate?.risk_reward_ratio || 3.5} R
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Confluence Radar Ribbon */}
                  <div className="p-3 rounded-xl border border-border bg-surface grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-center font-mono">
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Minervini / Stage</span>
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
                      <span className="text-[10px] text-muted uppercase block">RVOL Expansion</span>
                      <span className="text-xs font-bold text-emerald-700 dark:text-emerald-400">
                        {activeCandidate?.rvol_20d}x (20D)
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Sector Momentum</span>
                      <span className="text-xs font-bold text-amber-700 dark:text-amber-400">
                        {activeCandidate?.rrg_quadrant} ({activeCandidate?.sector_tailwind_score}/100)
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">20D Median Liq</span>
                      <span className="text-xs font-bold text-text">
                        ₹{activeCandidate?.turnover_20d_cr ? activeCandidate.turnover_20d_cr.toFixed(1) : '0.0'} Cr
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Weekly Trend</span>
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
                        <h3 className="font-bold text-text text-sm font-ui">
                          📍 Price Coordinates & Risk Boundaries
                        </h3>
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">OPTIMAL ENTRY ZONE</span>
                            <span className="font-bold text-text text-sm">
                              {decisionMatrix?.where?.entry_zone}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">STRUCTURAL STOP LOSS</span>
                            <span className="font-bold text-rose-600 dark:text-rose-400 text-sm">
                              {decisionMatrix?.where?.stop_loss}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">TARGET 1 (+2R BREAKEVEN)</span>
                            <span className="font-bold text-emerald-600 dark:text-emerald-400 text-sm">
                              {decisionMatrix?.where?.target_1}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">TARGET 2 (+3.5R SWING)</span>
                            <span className="font-bold text-amber-600 dark:text-amber-400 text-sm">
                              {decisionMatrix?.where?.target_2}
                            </span>
                          </div>
                        </div>
                        <div className="p-2.5 rounded bg-panel border border-border flex items-center justify-between">
                          <span className="text-muted font-ui">🚀 Moonshot Target (+6.5R):</span>
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
