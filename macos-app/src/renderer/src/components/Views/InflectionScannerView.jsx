import { useState, useEffect, useMemo, useRef } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import { formatINR, formatPct } from '../../utils/formatINR'
import UnavailableState from '../Common/UnavailableState'

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
  const [minScore, setMinScore] = useState(50)
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState('table') // 'table' | 'cards'
  const [sortColumn, setSortColumn] = useState('inflection_score')
  const [sortDirection, setSortDirection] = useState('desc')

  // Scan Data & Loading
  const [isScanning, setIsScanning] = useState(false)
  const [scanResult, setScanResult] = useState(null)
  const [lastScanTime, setLastScanTime] = useState('')

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

  // ── 1. Load Universes on Mount ───────────────────────────────────────
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
  }, [])

  // ── 2. Run Inflection Scan ──────────────────────────────────────────
  const executeScan = async (targetUniverse = universe) => {
    setIsScanning(true)
    const abortCtrl = new AbortController()

    startActivity({
      title: 'Inflection & Multibagger Radar',
      details: `Screening ${targetUniverse} across 5 quantitative inflection engines...`,
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
        max_results: 40,
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

  // Trigger scan when universe, archetype, or timing changes
  useEffect(() => {
    executeScan(universe)
  }, [universe, archetypeFilter, timingFilter, minScore])

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

  // ── 5. Filtering and Sorting ─────────────────────────────────────────
  const filteredCandidates = useMemo(() => {
    if (!scanResult?.candidates) return []
    let list = [...scanResult.candidates]

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      list = list.filter(
        (c) =>
          c.symbol.toLowerCase().includes(q) ||
          c.name.toLowerCase().includes(q) ||
          c.sector.toLowerCase().includes(q)
      )
    }

    list.sort((a, b) => {
      let aVal = a[sortColumn]
      let bVal = b[sortColumn]
      if (typeof aVal === 'string') aVal = aVal.toLowerCase()
      if (typeof bVal === 'string') bVal = bVal.toLowerCase()

      if (sortDirection === 'asc') return aVal > bVal ? 1 : -1
      return aVal < bVal ? 1 : -1
    })

    return list
  }, [scanResult, searchQuery, sortColumn, sortDirection])

  const handleSort = (col) => {
    if (sortColumn === col) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(col)
      setSortDirection('desc')
    }
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
    <div
      className="flex flex-col flex-1 h-full overflow-hidden select-none"
      style={{ background: 'var(--color-void)', color: 'var(--color-text)' }}
    >
      {/* ── TOP CONTROL BAR ─────────────────────────────────────────────── */}
      <div
        className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        {/* Left: Title & Pulse */}
        <div className="flex items-center gap-3">
          <div
            className="flex items-center justify-center w-9 h-9 rounded-xl font-bold text-base shadow-lg"
            style={{
              background: 'linear-gradient(135deg, rgba(245,166,35,0.25), rgba(0,214,143,0.25))',
              border: '1px solid var(--color-gold)',
              boxShadow: 'var(--glow-gold)',
            }}
          >
            📡
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold tracking-wide uppercase font-mono text-white">
                Inflection & Multibagger Radar
              </h1>
              <span
                className="text-[10px] font-bold px-2 py-0.5 rounded-full font-mono uppercase"
                style={{
                  background: 'rgba(0,214,143,0.15)',
                  color: 'var(--color-emerald)',
                  border: '1px solid rgba(0,214,143,0.3)',
                }}
              >
                AI 5W+H Matrix
              </span>
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
              className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border cursor-pointer outline-none transition-all"
              style={{
                background: 'var(--color-elevated)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
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
                  <option value="microcap_250">🌱 Microcap 250 (80)</option>
                  <option value="defence">🛡️ Defence & Aerospace (12)</option>
                  <option value="it">💻 IT Services (22)</option>
                  <option value="banking">🏦 Banking & Financials (25)</option>
                </>
              )}
            </select>
          </div>

          {/* Search Input */}
          <div className="relative">
            <input
              type="text"
              placeholder="Search symbol/sector..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="text-xs px-2.5 py-1.5 pl-7 rounded-lg border outline-none w-36 sm:w-44 focus:w-52 transition-all"
              style={{
                background: 'var(--color-elevated)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            <span className="absolute left-2 top-2 text-xs text-muted pointer-events-none">🔍</span>
          </div>

          {/* View Mode Toggle */}
          <div
            className="flex items-center rounded-lg border p-0.5"
            style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
          >
            <button
              type="button"
              onClick={() => setViewMode('table')}
              className={`text-xs px-2 py-1 rounded transition-all cursor-pointer ${
                viewMode === 'table' ? 'font-bold' : 'text-muted'
              }`}
              style={viewMode === 'table' ? { background: 'var(--color-panel)', color: 'var(--color-gold)' } : {}}
              title="Table View"
            >
              ☰ Table
            </button>
            <button
              type="button"
              onClick={() => setViewMode('cards')}
              className={`text-xs px-2 py-1 rounded transition-all cursor-pointer ${
                viewMode === 'cards' ? 'font-bold' : 'text-muted'
              }`}
              style={viewMode === 'cards' ? { background: 'var(--color-panel)', color: 'var(--color-gold)' } : {}}
              title="Cards Matrix"
            >
              ☷ Cards
            </button>
          </div>

          {/* Refresh Scan Button */}
          <button
            type="button"
            onClick={() => executeScan(universe)}
            disabled={isScanning}
            className="flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg border transition-all cursor-pointer"
            style={{
              background: 'linear-gradient(135deg, rgba(245,166,35,0.2), rgba(245,166,35,0.1))',
              borderColor: 'var(--color-gold)',
              color: 'var(--color-gold)',
            }}
          >
            <span className={isScanning ? 'animate-spin' : ''}>🔄</span>
            <span>{isScanning ? 'Scanning...' : 'Rescan'}</span>
          </button>
        </div>
      </div>

      {/* ── FILTER CHIPS STRIP ──────────────────────────────────────────── */}
      <div
        className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b text-xs"
        style={{ background: 'var(--color-panel)', borderColor: 'var(--color-border)' }}
      >
        {/* Archetype Chips */}
        <div className="flex flex-wrap items-center gap-1.5 overflow-x-auto py-0.5">
          <span className="text-[10px] text-muted uppercase font-mono mr-1">Archetype:</span>
          {ARCHETYPE_TABS.map((tab) => {
            const active = archetypeFilter === tab.id
            const count = scanResult?.archetype_counts?.[tab.id]
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setArchetypeFilter(tab.id)}
                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all cursor-pointer"
                style={{
                  background: active ? 'rgba(245,166,35,0.2)' : 'var(--color-elevated)',
                  border: active ? '1px solid var(--color-gold)' : '1px solid var(--color-border)',
                  color: active ? 'var(--color-gold-bright)' : 'var(--color-text-dim)',
                }}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                {count !== undefined && (
                  <span
                    className="text-[9px] px-1 rounded-full font-mono"
                    style={{ background: 'var(--color-surface)', color: 'var(--color-text)' }}
                  >
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Timing Filters */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted uppercase font-mono mr-1">Timing:</span>
          {TIMING_TABS.map((tab) => {
            const active = timingFilter === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setTimingFilter(tab.id)}
                className="px-2 py-0.5 rounded text-[11px] font-medium transition-all cursor-pointer"
                style={{
                  background: active ? 'rgba(0,214,143,0.2)' : 'transparent',
                  border: active ? '1px solid var(--color-emerald)' : '1px solid transparent',
                  color: active ? 'var(--color-emerald)' : 'var(--color-muted)',
                }}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── EXECUTIVE SUMMARY METRICS STRIP ─────────────────────────────── */}
      <div
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 px-4 py-2.5 border-b"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex flex-col p-2 rounded-lg border" style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}>
          <span className="text-[10px] text-muted font-mono uppercase">Scanned Universe</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold text-white font-mono">{summaryMetrics.total}</span>
            <span className="text-[10px] text-muted">Stocks</span>
          </div>
        </div>

        <div className="flex flex-col p-2 rounded-lg border" style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}>
          <span className="text-[10px] text-muted font-mono uppercase">High Conviction (75+)</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono" style={{ color: 'var(--color-gold)' }}>
              {summaryMetrics.highConviction}
            </span>
            <span className="text-[10px] text-muted">Picks</span>
          </div>
        </div>

        <div className="flex flex-col p-2 rounded-lg border" style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}>
          <span className="text-[10px] text-muted font-mono uppercase">Active Squeezes</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono text-cyan-400">
              {summaryMetrics.coiling}
            </span>
            <span className="text-[10px] text-muted">Coiling</span>
          </div>
        </div>

        <div className="flex flex-col p-2 rounded-lg border" style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}>
          <span className="text-[10px] text-muted font-mono uppercase">Breakout Fired</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono" style={{ color: 'var(--color-emerald)' }}>
              {summaryMetrics.triggerNow}
            </span>
            <span className="text-[10px] text-muted">Actionable</span>
          </div>
        </div>

        <div className="flex flex-col p-2 rounded-lg border" style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}>
          <span className="text-[10px] text-muted font-mono uppercase">Avg Risk/Reward</span>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-base font-bold font-mono text-white">
              1:{summaryMetrics.avgRR}
            </span>
            <span className="text-[10px] text-muted">Payoff</span>
          </div>
        </div>

        <div className="flex flex-col p-2 rounded-lg border" style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}>
          <span className="text-[10px] text-muted font-mono uppercase">Top Inflection Sector</span>
          <div className="flex items-baseline gap-1 mt-0.5 truncate">
            <span className="text-xs font-bold text-white truncate" title={summaryMetrics.topSector}>
              {summaryMetrics.topSector}
            </span>
          </div>
        </div>
      </div>

      {/* ── MAIN CANDIDATES VIEW CONTAINER ──────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-4">
        {isScanning && filteredCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: 'var(--color-gold)', borderTopColor: 'transparent' }} />
            <span className="text-xs font-mono tracking-wider text-muted uppercase">
              Screening 5 Inflection Engines & Computing Confluences...
            </span>
          </div>
        ) : filteredCandidates.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <span className="text-3xl mb-2">🔍</span>
            <span className="text-sm font-bold text-white">No Inflection Setups Matching Criteria</span>
            <p className="text-xs text-muted mt-1 max-w-md">
              Try switching the universe (e.g. Multibagger Hunters or Microcap 250) or resetting archetype and timing filters.
            </p>
            <button
              type="button"
              onClick={() => { setArchetypeFilter('ALL'); setTimingFilter('ALL'); setSearchQuery('') }}
              className="mt-3 text-xs font-semibold px-3 py-1.5 rounded-lg border cursor-pointer"
              style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)', color: 'var(--color-gold)' }}
            >
              Reset Filters
            </button>
          </div>
        ) : viewMode === 'table' ? (
          /* ── TABLE VIEW ──────────────────────────────────────────────── */
          <div
            className="rounded-xl border overflow-hidden shadow-xl"
            style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr
                  className="border-b text-[10px] font-mono text-muted uppercase"
                  style={{ background: 'var(--color-panel)', borderColor: 'var(--color-border)' }}
                >
                  <th className="py-2.5 px-3 cursor-pointer" onClick={() => handleSort('symbol')}>
                    Symbol / Asset {sortColumn === 'symbol' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                  </th>
                  <th className="py-2.5 px-2 cursor-pointer" onClick={() => handleSort('inflection_score')}>
                    Inflection Score {sortColumn === 'inflection_score' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                  </th>
                  <th className="py-2.5 px-2">Primary Archetype</th>
                  <th className="py-2.5 px-2">Timing State</th>
                  <th className="py-2.5 px-2 cursor-pointer text-right" onClick={() => handleSort('ltp')}>
                    LTP (₹) {sortColumn === 'ltp' ? (sortDirection === 'asc' ? '▲' : '▼') : ''}
                  </th>
                  <th className="py-2.5 px-2 text-right">Day Chg</th>
                  <th className="py-2.5 px-2 text-center">RVOL 20D</th>
                  <th className="py-2.5 px-2 text-center">Stage / Minervini</th>
                  <th className="py-2.5 px-2">Trade Levels (Entry / SL / T1)</th>
                  <th className="py-2.5 px-2 text-center">Payoff (R:R)</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/40 font-mono">
                {filteredCandidates.map((c) => {
                  const isReady = c.timing_state === 'TRIGGER_NOW'
                  const isCoiling = c.timing_state === 'COILING_IMMINENT'
                  return (
                    <tr
                      key={c.symbol}
                      className="hover:bg-white/[0.03] transition-colors group cursor-pointer"
                      onClick={() => openDecisionDrawer(c)}
                    >
                      {/* Symbol & Name */}
                      <td className="py-2.5 px-3">
                        <div className="flex items-center gap-2">
                          <span className="text-base">{c.sector_icon || '🏢'}</span>
                          <div>
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-white text-xs group-hover:text-amber-400 transition-colors">
                                {c.symbol}
                              </span>
                              {c.rrg_quadrant === 'LEADING' && (
                                <span className="text-[9px] px-1 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                  LEADING
                                </span>
                              )}
                            </div>
                            <span className="text-[10px] text-muted font-ui block truncate max-w-[130px]">
                              {c.name}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Inflection Score */}
                      <td className="py-2.5 px-2">
                        <div className="flex items-center gap-1.5">
                          <div
                            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shadow"
                            style={{
                              background:
                                c.inflection_score >= 75
                                  ? 'rgba(245,166,35,0.2)'
                                  : 'rgba(77,155,255,0.15)',
                              color:
                                c.inflection_score >= 75
                                  ? 'var(--color-gold-bright)'
                                  : 'var(--color-sapphire)',
                              border: `1px solid ${
                                c.inflection_score >= 75 ? 'var(--color-gold)' : 'var(--color-border)'
                              }`,
                            }}
                          >
                            {c.inflection_score}
                          </div>
                          <div className="w-12 bg-gray-800 rounded-full h-1.5 hidden md:block overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{
                                width: `${c.inflection_score}%`,
                                background:
                                  c.inflection_score >= 75
                                    ? 'linear-gradient(90deg, #f5a623, #00d68f)'
                                    : '#4d9bff',
                              }}
                            />
                          </div>
                        </div>
                      </td>

                      {/* Primary Archetype */}
                      <td className="py-2.5 px-2 font-ui">
                        <span
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-md border inline-block"
                          style={{
                            background: 'rgba(245,166,35,0.08)',
                            borderColor: 'rgba(245,166,35,0.25)',
                            color: 'var(--color-gold)',
                          }}
                        >
                          {c.archetype_label}
                        </span>
                      </td>

                      {/* Timing State */}
                      <td className="py-2.5 px-2 font-ui">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full border inline-block ${
                            isReady
                              ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40 animate-pulse'
                              : isCoiling
                              ? 'bg-amber-500/15 text-amber-400 border-amber-500/40'
                              : 'bg-blue-500/15 text-blue-400 border-blue-500/40'
                          }`}
                        >
                          {c.timing_label}
                        </span>
                      </td>

                      {/* LTP */}
                      <td className="py-2.5 px-2 text-right font-bold text-white">
                        ₹{c.ltp.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
                      </td>

                      {/* Day Change */}
                      <td
                        className={`py-2.5 px-2 text-right font-bold ${
                          c.day_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {formatPct(c.day_change_pct).text}
                      </td>

                      {/* RVOL 20D */}
                      <td className="py-2.5 px-2 text-center">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[11px] font-semibold ${
                            c.rvol_20d >= 1.8
                              ? 'bg-emerald-500/20 text-emerald-400 font-bold'
                              : c.rvol_20d < 0.6
                              ? 'text-cyan-400'
                              : 'text-muted'
                          }`}
                        >
                          {c.rvol_20d}x
                        </span>
                      </td>

                      {/* Stage / Minervini */}
                      <td className="py-2.5 px-2 text-center font-ui text-[11px]">
                        <span className="text-white font-medium">{c.trend_template_passed}/8</span>
                        <span className="text-muted text-[10px] ml-1">
                          ({c.weinstein_stage.replace('STAGE_', 'S')})
                        </span>
                      </td>

                      {/* Trade Levels */}
                      <td className="py-2.5 px-2 font-mono text-[11px]">
                        <div className="flex items-center gap-1.5">
                          <span className="text-white" title="Entry">
                            ₹{c.entry_price.toFixed(1)}
                          </span>
                          <span className="text-muted">/</span>
                          <span className="text-rose-400" title="Stop Loss">
                            ₹{c.stop_loss.toFixed(1)}
                          </span>
                          <span className="text-muted">/</span>
                          <span className="text-emerald-400 font-semibold" title="Target 1 (+2R)">
                            ₹{c.target_1.toFixed(1)}
                          </span>
                        </div>
                      </td>

                      {/* Risk / Reward */}
                      <td className="py-2.5 px-2 text-center">
                        <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">
                          1:{c.risk_reward_ratio}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => openDecisionDrawer(c)}
                            className="p-1 rounded hover:bg-amber-500/20 text-amber-400 border border-amber-500/30 transition-all cursor-pointer"
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
                            className="p-1 rounded hover:bg-white/10 text-text-dim border border-border transition-all cursor-pointer"
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
                className="rounded-xl border p-3.5 flex flex-col justify-between gap-3 shadow-lg hover:border-amber-400/50 transition-all cursor-pointer group"
                style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-2xl p-1.5 rounded-lg bg-panel border border-border">
                      {c.sector_icon || '🏢'}
                    </span>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold text-white text-sm group-hover:text-amber-400 transition-colors">
                          {c.symbol}
                        </span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-panel border border-border text-muted">
                          {c.sector}
                        </span>
                      </div>
                      <span className="text-xs text-muted block truncate max-w-[180px]">
                        {c.name}
                      </span>
                    </div>
                  </div>

                  <div
                    className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-sm"
                    style={{
                      background: 'rgba(245,166,35,0.15)',
                      color: 'var(--color-gold)',
                      border: '1px solid rgba(245,166,35,0.35)',
                    }}
                  >
                    {c.inflection_score}
                  </div>
                </div>

                {/* Badges Strip */}
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                    {c.archetype_label}
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    {c.timing_label}
                  </span>
                  {c.squeeze_state === 'COILING' && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                      Coiling ({c.squeeze_duration}b)
                    </span>
                  )}
                  {c.vcp_detected && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/30">
                      VCP {c.vcp_tightness_pct}%
                    </span>
                  )}
                </div>

                {/* Price & Levels Ribbon */}
                <div
                  className="rounded-lg p-2.5 font-mono text-xs border flex items-center justify-between"
                  style={{ background: 'var(--color-panel)', borderColor: 'var(--color-border)' }}
                >
                  <div>
                    <span className="text-[10px] text-muted block">ENTRY</span>
                    <span className="font-bold text-white">₹{c.entry_price.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted block">STOP</span>
                    <span className="font-bold text-rose-400">₹{c.stop_loss.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted block">TARGET 1</span>
                    <span className="font-bold text-emerald-400">₹{c.target_1.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted block">PAYOFF</span>
                    <span className="font-bold text-amber-400">1:{c.risk_reward_ratio}</span>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center justify-between pt-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => openDecisionDrawer(c)}
                    className="text-xs font-bold px-2.5 py-1.5 rounded-lg border flex items-center gap-1.5 transition-all cursor-pointer"
                    style={{
                      background: 'rgba(245,166,35,0.12)',
                      borderColor: 'rgba(245,166,35,0.3)',
                      color: 'var(--color-gold)',
                    }}
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
                      className="px-2.5 py-1.5 rounded-lg border text-xs font-medium text-text-dim hover:text-white transition-all cursor-pointer"
                      style={{ background: 'var(--color-elevated)', borderColor: 'var(--color-border)' }}
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
                      className="px-2.5 py-1.5 rounded-lg border text-xs font-bold text-emerald-400 hover:bg-emerald-500/20 transition-all cursor-pointer"
                      style={{
                        background: 'rgba(0,214,143,0.12)',
                        borderColor: 'rgba(0,214,143,0.3)',
                      }}
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
            className="w-full max-w-2xl h-full flex flex-col border-l shadow-2xl overflow-hidden font-ui animate-in slide-in-from-right duration-200"
            style={{ background: 'var(--color-panel)', borderColor: 'var(--color-border)' }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div
              className="flex items-center justify-between px-5 py-3.5 border-b"
              style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl p-1.5 rounded-lg bg-panel border border-border">
                  {activeCandidate?.sector_icon || '🏢'}
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-white">{activeCandidate?.symbol}</h2>
                    <span className="text-xs text-muted">| {activeCandidate?.name}</span>
                    <span
                      className="text-[10px] font-bold px-2 py-0.5 rounded-full border"
                      style={{
                        background:
                          decisionMatrix?.verdict?.includes('BUY')
                            ? 'rgba(0,214,143,0.15)'
                            : 'rgba(245,166,35,0.15)',
                        borderColor:
                          decisionMatrix?.verdict?.includes('BUY')
                            ? 'var(--color-emerald)'
                            : 'var(--color-gold)',
                        color:
                          decisionMatrix?.verdict?.includes('BUY')
                            ? 'var(--color-emerald)'
                            : 'var(--color-gold)',
                      }}
                    >
                      {decisionMatrix?.verdict || 'ANALYZING...'}
                    </span>
                  </div>
                  <p className="text-[11px] text-muted">
                    LTP: ₹{activeCandidate?.ltp} ({formatPct(activeCandidate?.day_change_pct).text}) •{' '}
                    {activeCandidate?.sector}
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
                  className="text-xs font-bold px-3 py-1.5 rounded-lg border text-emerald-400 transition-all cursor-pointer"
                  style={{
                    background: 'rgba(0,214,143,0.12)',
                    borderColor: 'rgba(0,214,143,0.3)',
                  }}
                >
                  ⚡ Order Ticket
                </button>
                <button
                  type="button"
                  onClick={() => setIsDrawerOpen(false)}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-muted hover:text-white border border-border hover:bg-white/10 transition-all cursor-pointer"
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
                  {/* Confluence Radar Ribbon */}
                  <div
                    className="p-3.5 rounded-xl border grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center font-mono"
                    style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
                  >
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Minervini / Stage</span>
                      <span className="text-xs font-bold text-white">
                        {activeCandidate?.trend_template_passed}/8 ({activeCandidate?.weinstein_stage?.replace('STAGE_', 'S')})
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Squeeze / VCP</span>
                      <span className="text-xs font-bold text-cyan-400">
                        {activeCandidate?.squeeze_state === 'COILING'
                          ? `Coiling (${activeCandidate?.squeeze_duration}b)`
                          : activeCandidate?.vcp_detected
                          ? `VCP ${activeCandidate?.vcp_tightness_pct}%`
                          : 'Normal'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">RVOL Expansion</span>
                      <span className="text-xs font-bold text-emerald-400">
                        {activeCandidate?.rvol_20d}x (20D)
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-muted uppercase block">Sector Momentum</span>
                      <span className="text-xs font-bold text-amber-400">
                        {activeCandidate?.rrg_quadrant} ({activeCandidate?.sector_tailwind_score}/100)
                      </span>
                    </div>
                  </div>

                  {/* 5W+H Navigation Tabs */}
                  <div
                    className="flex items-center gap-1 border-b pb-1 text-xs"
                    style={{ borderColor: 'var(--color-border)' }}
                  >
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
                            ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                            : 'text-muted hover:text-white'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {/* Tab Content Panels */}
                  <div
                    className="p-4 rounded-xl border text-xs leading-relaxed"
                    style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
                  >
                    {activeDrawerTab === 'what' && (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <h3 className="font-bold text-white text-sm">
                            {decisionMatrix?.what?.thesis_title || 'Core Inflection Thesis'}
                          </h3>
                        </div>
                        <p className="text-text-dim">
                          {decisionMatrix?.what?.primary_catalyst}
                        </p>
                        <div>
                          <span className="font-bold text-amber-400 block mb-1">
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
                        <h3 className="font-bold text-white text-sm font-ui">
                          📍 Price Coordinates & Risk Boundaries
                        </h3>
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">OPTIMAL ENTRY ZONE</span>
                            <span className="font-bold text-white text-sm">
                              {decisionMatrix?.where?.entry_zone}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">STRUCTURAL STOP LOSS</span>
                            <span className="font-bold text-rose-400 text-sm">
                              {decisionMatrix?.where?.stop_loss}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">TARGET 1 (+2R BREAKEVEN)</span>
                            <span className="font-bold text-emerald-400 text-sm">
                              {decisionMatrix?.where?.target_1}
                            </span>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="text-[10px] text-muted block font-ui">TARGET 2 (+3.5R SWING)</span>
                            <span className="font-bold text-amber-400 text-sm">
                              {decisionMatrix?.where?.target_2}
                            </span>
                          </div>
                        </div>
                        <div className="p-2.5 rounded bg-panel border border-border flex items-center justify-between">
                          <span className="text-muted font-ui">🚀 Moonshot Target (+6.5R):</span>
                          <span className="font-bold text-purple-400">
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
                        <h3 className="font-bold text-white text-sm">
                          ⏰ Timing Window & Squeeze Countdown
                        </h3>
                        <div className="p-3 rounded-lg bg-panel border border-border space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-muted">Timing Status:</span>
                            <span className="font-bold text-amber-400">
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
                            <span className="text-white font-mono">
                              {decisionMatrix?.when?.time_stop_days} Trading Days
                            </span>
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="text-muted">Holding Horizon:</span>
                            <span className="text-white">
                              {decisionMatrix?.when?.holding_period}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'how' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-white text-sm">
                          🛠️ Step-by-Step Tactical Execution Playbook
                        </h3>
                        <div className="space-y-2 text-text-dim">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-amber-400 block mb-0.5">1. Order Type:</span>
                            <p>{decisionMatrix?.how?.order_strategy}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-emerald-400 block mb-0.5">2. Scaling & Breakeven:</span>
                            <p>{decisionMatrix?.how?.scaling_plan}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-cyan-400 block mb-0.5">3. Trailing Mechanics:</span>
                            <p>{decisionMatrix?.how?.trailing_mechanics}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-purple-400 block mb-0.5">4. Moonshot Compounder:</span>
                            <p>{decisionMatrix?.how?.moonshot_management}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'correlations' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-white text-sm">
                          🌐 Cross-Market Dots Connected & Correlations
                        </h3>
                        <div className="space-y-2 text-text-dim">
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-white block mb-0.5">Global Macro Transmission:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.macro_regime}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-white block mb-0.5">Sector RRG Trajectory:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.sector_rrg_tailwind}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-white block mb-0.5">Options & Smart Money Flow:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.options_smart_money}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-white block mb-0.5">Crude Oil Transmission:</span>
                            <p className="text-muted">{decisionMatrix?.correlations?.crude_oil_impact}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {activeDrawerTab === 'invalidation' && (
                      <div className="space-y-3">
                        <h3 className="font-bold text-rose-400 text-sm">
                          ⚠️ Hard Structural Invalidation Triggers
                        </h3>
                        <div className="space-y-2 text-text-dim">
                          <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/30">
                            <span className="font-bold text-rose-400 block mb-0.5">Hard Stop Rule:</span>
                            <p>{decisionMatrix?.invalidation?.hard_stop_condition}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-amber-400 block mb-0.5">Time Stop Invalidation:</span>
                            <p>{decisionMatrix?.invalidation?.time_invalidation}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-white block mb-0.5">Structural Breakdown:</span>
                            <p>{decisionMatrix?.invalidation?.structural_failure}</p>
                          </div>
                          <div className="p-2.5 rounded bg-panel border border-border">
                            <span className="font-bold text-white block mb-0.5">Gap-Down Protocol:</span>
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
                            className="p-3 rounded-lg border text-xs"
                            style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-bold text-amber-400">{ins.persona}</span>
                              <span className="text-[10px] text-muted font-mono">{ins.style}</span>
                            </div>
                            <p className="text-text-dim leading-relaxed">{ins.commentary}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Interactive Position Sizer */}
                  <div
                    className="p-4 rounded-xl border space-y-3 font-mono"
                    style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
                  >
                    <div className="flex items-center justify-between font-ui">
                      <h4 className="font-bold text-white text-xs flex items-center gap-1.5">
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
                          className="w-full px-2.5 py-1.5 rounded bg-panel border border-border text-white font-bold outline-none"
                        />
                      </div>
                      <div>
                        <span className="text-[10px] text-muted block font-ui mb-1">Max Risk (%):</span>
                        <input
                          type="number"
                          step="0.1"
                          value={sizerRiskPct}
                          onChange={(e) => setSizerRiskPct(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 rounded bg-panel border border-border text-amber-400 font-bold outline-none"
                        />
                      </div>
                    </div>

                    <div className="p-2.5 rounded bg-panel border border-border grid grid-cols-3 gap-2 text-center text-xs">
                      <div>
                        <span className="text-[10px] text-muted font-ui block">ALLOCATED SHARES</span>
                        <span className="font-bold text-white text-sm">{calculatedPosition.shares}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui block">CAPITAL (₹)</span>
                        <span className="font-bold text-white text-sm">
                          ₹{calculatedPosition.capital.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui block">MAX RISK (₹)</span>
                        <span className="font-bold text-rose-400 text-sm">
                          ₹{calculatedPosition.riskAmount.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Interactive Dot-Connecting Chat */}
                  <div
                    className="p-4 rounded-xl border space-y-3"
                    style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
                  >
                    <div className="flex items-center justify-between">
                      <h4 className="font-bold text-white text-xs flex items-center gap-1.5">
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
                          className="text-[10px] px-2 py-0.5 rounded-full border text-text-dim hover:text-amber-400 hover:border-amber-400/40 bg-panel transition-all cursor-pointer"
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
                              ? 'bg-amber-500/15 border border-amber-500/30 text-white ml-6'
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
                        className="flex-1 text-xs px-3 py-2 rounded-lg border outline-none text-white bg-panel border-border focus:border-amber-400 transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => handleSendDrawerChat()}
                        disabled={chatLoading || !chatInput.trim()}
                        className="text-xs font-bold px-3 py-2 rounded-lg border text-amber-400 bg-amber-500/20 border-amber-500/40 hover:bg-amber-500/30 transition-all cursor-pointer disabled:opacity-50"
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
