import React, { useEffect, useState, useCallback } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import UnavailableState from '../Common/UnavailableState'

export default function MoversAutopsyPanel({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)

  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [autopsyData, setAutopsyData] = useState(null)
  const [precursors, setPrecursors] = useState([])
  const [asymmetricOpps, setAsymmetricOpps] = useState([])
  const [activeSubTab, setActiveSubTab] = useState('precursors') // 'precursors' | 'asymmetric' | 'autopsy' | 'traps'
  const [selectedDirection, setSelectedDirection] = useState('ALL') // 'ALL' | 'GAINER' | 'LOSER'
  const [selectedSegment, setSelectedSegment] = useState('ALL') // 'ALL' | 'FNO' | 'NON_FNO' | 'INDEX'

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const segQuery = selectedSegment !== 'ALL' ? `?segment=${selectedSegment}` : ''
      const preQuery = selectedSegment !== 'ALL' ? `&segment=${selectedSegment}` : ''
      const asymQuery = selectedSegment !== 'ALL' ? `&segment=${selectedSegment}` : ''
      const [autopsyRes, precursorsRes, asymRes] = await Promise.all([
        call(`/api/movers/autopsy${segQuery}`, {}, { method: 'GET' }),
        call(`/api/movers/precursors?limit=8${preQuery}`, {}, { method: 'GET' }),
        call(`/api/opportunities/asymmetric?min_rr=3.0${asymQuery}`, {}, { method: 'GET' }),
      ])
      if (autopsyRes?.data) setAutopsyData(autopsyRes.data)
      if (precursorsRes?.data) setPrecursors(precursorsRes.data)
      if (asymRes?.data) setAsymmetricOpps(asymRes.data)
    } catch (err) {
      console.error('Failed to load mover autopsy data:', err)
    } finally {
      setLoading(false)
    }
  }, [call, selectedSegment])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleRunAutopsy = async () => {
    setRunning(true)
    try {
      const payload = { top_n: 10 }
      if (selectedSegment !== 'ALL') {
        payload.segment = selectedSegment
      }
      const res = await call('/api/movers/autopsy/run', payload, { method: 'POST' })
      if (res?.data) {
        setAutopsyData(res.data)
        // Refresh precursors & asymmetric opps too
        const preQuery = selectedSegment !== 'ALL' ? `&segment=${selectedSegment}` : ''
        const asymQuery = selectedSegment !== 'ALL' ? `&segment=${selectedSegment}` : ''
        const [pRes, aRes] = await Promise.all([
          call(`/api/movers/precursors?limit=8${preQuery}`, {}, { method: 'GET' }),
          call(`/api/opportunities/asymmetric?force_refresh=true${asymQuery}`, {}, { method: 'GET' }),
        ])
        if (pRes?.data) setPrecursors(pRes.data)
        if (aRes?.data) setAsymmetricOpps(aRes.data)
      }
    } catch (err) {
      console.error('Failed to run on-demand autopsy:', err)
    } finally {
      setRunning(false)
    }
  }

  const handleAnalyze = (symbol) => {
    sendDraft(`analyze ${symbol}`, { autoSubmit: true })
    setActiveView('overview')
  }

  const handleBuy = (cand) => {
    if (onOpenOrderTicket) {
      onOpenOrderTicket({
        symbol: cand.symbol,
        exchange: cand.exchange || 'NSE',
        side: 'BUY',
        limitPrice: cand.ltp,
        triggerPrice: cand.stop_loss,
      })
    } else {
      sendDraft(`buy ${cand.symbol} 1 @ limit ${cand.ltp}`, { autoSubmit: false })
    }
  }

  if (loading && !autopsyData) {
    return (
      <div className="p-8 text-center">
        <UnavailableState
          title="Deconstructing Market Movers..."
          reason="Analyzing 5-dimensional causal drivers, pre-breakout volume dry-up, and control cohort contrast."
          size="md"
        />
      </div>
    )
  }

  const rawGainers = autopsyData?.gainers || []
  const rawLosers = autopsyData?.losers || []
  const gainers = rawGainers.filter(
    (g) => selectedSegment === 'ALL' || (g.segment || 'FNO') === selectedSegment
  )
  const losers = rawLosers.filter(
    (l) => selectedSegment === 'ALL' || (l.segment || 'FNO') === selectedSegment
  )
  const allMovers = [...gainers, ...losers]
  const rawTraps = autopsyData?.traps || (autopsyData?.gainers || []).concat(autopsyData?.losers || []).filter((m) => m.is_trap)
  const traps = rawTraps.filter(
    (t) => selectedSegment === 'ALL' || (t.segment || 'NON_FNO') === selectedSegment
  )
  const validGainers = gainers.filter((g) => !g.is_trap)
  const validLosers = losers.filter((l) => !l.is_trap)

  const displayedPrecursors = precursors.filter(
    (p) => selectedSegment === 'ALL' || (p.segment || 'FNO') === selectedSegment
  )

  const displayedAsymmetric = (asymmetricOpps || []).filter(
    (o) => selectedSegment === 'ALL' || (o.segment || 'FNO') === selectedSegment
  )

  const displayedMovers =
    selectedDirection === 'GAINER'
      ? validGainers
      : selectedDirection === 'LOSER'
      ? validLosers
      : [...validGainers, ...validLosers]

  return (
    <div className="space-y-4 animate-fade-in text-text">
      {/* ── Top Header & Statistical Regime Bar ──────────────────────── */}
      <div className="p-4 rounded-2xl bg-panel border border-border flex flex-wrap items-center justify-between gap-4 shadow-sm">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xl">🔬</span>
            <h2 className="text-base font-black tracking-wide text-text uppercase">
              Daily Top Movers Forensic Autopsy & Precursor Radar
            </h2>
            <span className="px-2 py-0.5 text-[10px] font-black rounded-full bg-gold/15 text-gold border border-gold/30">
              {autopsyData?.date || 'Today'}
            </span>
            <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              Regime: {autopsyData?.market_regime || 'NORMAL'}
            </span>
          </div>
          <p className="text-xs text-muted">
            Deconstructs big moves across volume dry-up, squeeze coiling, sector RRG, and options gamma — benchmarked against a control group to prevent narrative fallacy.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={handleRunAutopsy}
            disabled={running}
            className={`btn btn-sm ${running ? 'opacity-50' : 'btn-gold'} flex items-center gap-1.5`}
          >
            <span>{running ? '⚡' : '🔄'}</span>
            <span className="font-bold">{running ? 'Conducting Autopsy...' : 'Run Autopsy Scan Now'}</span>
          </button>
        </div>
      </div>

      {/* ── Universe / Segment Switcher Bar ─────────────────────────── */}
      <div className="flex items-center justify-between gap-2 p-2 rounded-xl bg-panel border border-border">
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-muted font-bold text-[11px] uppercase tracking-wider px-1">
            Universe:
          </span>
          <button
            onClick={() => setSelectedSegment('ALL')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              selectedSegment === 'ALL'
                ? 'bg-amber-400 text-panel font-black shadow-sm'
                : 'text-muted hover:text-text bg-elevated'
            }`}
          >
            🌐 All Universes
          </button>
          <button
            onClick={() => setSelectedSegment('FNO')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              selectedSegment === 'FNO'
                ? 'bg-indigo-500 text-white font-black shadow-sm'
                : 'text-muted hover:text-text bg-elevated'
            }`}
          >
            ⚡ F&O Derivatives
          </button>
          <button
            onClick={() => setSelectedSegment('NON_FNO')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              selectedSegment === 'NON_FNO'
                ? 'bg-emerald-500 text-white font-black shadow-sm'
                : 'text-muted hover:text-text bg-elevated'
            }`}
          >
            📈 Non-F&O Cash
          </button>
          <button
            onClick={() => setSelectedSegment('INDEX')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              selectedSegment === 'INDEX'
                ? 'bg-sky-500 text-white font-black shadow-sm'
                : 'text-muted hover:text-text bg-elevated'
            }`}
          >
            🏛️ Indices
          </button>
        </div>
        <div className="text-[11px] text-muted hidden md:block">
          {selectedSegment === 'FNO'
            ? 'Scanning high-OI F&O derivative contracts'
            : selectedSegment === 'NON_FNO'
            ? 'Scanning high-turnover (≥ ₹10 Cr) cash equities'
            : selectedSegment === 'INDEX'
            ? 'Scanning benchmark & sectoral macro indices'
            : 'Cross-universe multi-segment surveillance'}
        </div>
      </div>

      {/* ── Sub-Tab Navigation Bar ──────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-border pb-2 gap-2">
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-elevated border border-border">
          <button
            onClick={() => setActiveSubTab('precursors')}
            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeSubTab === 'precursors'
                ? 'bg-amber-400 text-panel font-black shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            <span>⚡</span>
            <span>Precursor Radar (Tomorrow's Moves)</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-panel/30 text-panel">
              {displayedPrecursors.length}
            </span>
          </button>

          <button
            onClick={() => setActiveSubTab('asymmetric')}
            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeSubTab === 'asymmetric'
                ? 'bg-emerald-500 text-white font-black shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            <span>🎯</span>
            <span>Asymmetric Setups (1:3+ R:R)</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 text-white">
              {displayedAsymmetric.length}
            </span>
          </button>

          <button
            onClick={() => setActiveSubTab('autopsy')}
            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeSubTab === 'autopsy'
                ? 'bg-gold text-panel font-black shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            <span>📊</span>
            <span>Top Movers Autopsy</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-panel/30 text-panel">
              {validGainers.length + validLosers.length}
            </span>
          </button>

          <button
            onClick={() => setActiveSubTab('traps')}
            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeSubTab === 'traps'
                ? 'bg-rose-500 text-white font-black shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            <span>🛡️</span>
            <span>Traps Filtered</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 text-white">
              {traps.length}
            </span>
          </button>
        </div>

        {/* Informational badge */}
        {autopsyData?.top_predictive_precursors && autopsyData.top_predictive_precursors.length > 0 && (
          <div className="hidden lg:flex items-center gap-1.5 text-[11px] text-muted bg-panel px-3 py-1 rounded-lg border border-border">
            <span className="text-amber-400">💡 Top Alpha Precursor:</span>
            <span className="font-bold text-text">{autopsyData.top_predictive_precursors[0]}</span>
          </div>
        )}
      </div>

      {/* ── SUB-TAB 1: Precursor Radar (Tomorrow's Candidates) ──────── */}
      {activeSubTab === 'precursors' && (
        <div className="space-y-3">
          <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-between text-xs text-amber-200">
            <div className="flex items-center gap-2">
              <span className="text-lg">🎯</span>
              <span>
                <strong>Pre-Ignition Detection:</strong> Stocks coiling with the exact T-1 / T-2 DNA of past winners (Volume dry-up, Squeeze compression, Order block anchor, and Leading sector momentum).
              </span>
            </div>
            <span className="font-black px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px]">
              Min Conviction ≥ 75
            </span>
          </div>

          {displayedPrecursors.length === 0 ? (
            <UnavailableState
              title="No Qualified Precursors Detected"
              reason="No stocks currently meet the strict 75+ conviction score or were penalized below VWAP. Disciplined quants wait for setups to come to them."
              size="md"
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {displayedPrecursors.map((cand) => {
                const isMax = cand.conviction_score >= 85
                return (
                  <div
                    key={cand.symbol}
                    className={`p-4 rounded-2xl bg-panel border transition-all hover:border-amber-400/50 flex flex-col justify-between gap-3 shadow-sm ${
                      isMax ? 'border-amber-400/40 bg-amber-500/5' : 'border-border'
                    }`}
                  >
                    {/* Card Header */}
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-base font-black tracking-wide text-text">{cand.symbol}</span>
                          <span className="px-2 py-0.5 text-[10px] font-black rounded bg-elevated text-muted border border-border">
                            {cand.exchange}
                          </span>
                          <span className="px-2 py-0.5 text-[10px] font-black rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
                            {cand.segment === 'FNO' ? '⚡ F&O' : cand.segment === 'NON_FNO' ? '📈 Cash' : cand.segment === 'INDEX' ? '🏛️ Index' : (cand.segment || '⚡ F&O')}
                          </span>
                          <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                            {cand.sector_name} ({cand.rrg_quadrant})
                          </span>
                        </div>
                        <p className="text-xs text-muted mt-0.5">
                          LTP: <strong className="text-text">₹{cand.ltp?.toLocaleString('en-IN')}</strong> · Coiling Pivot High: ₹{cand.coiling_pivot_high?.toLocaleString('en-IN')}
                        </p>
                      </div>

                      <div className="text-right">
                        <span
                          className={`px-2.5 py-1 text-xs font-black rounded-lg border flex items-center gap-1 ${
                            isMax
                              ? 'bg-amber-400 text-panel border-amber-300'
                              : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                          }`}
                        >
                          <span>{isMax ? '🔥' : '✅'}</span>
                          <span>{cand.conviction_score}/100</span>
                        </span>
                        <span className="text-[10px] font-semibold text-muted block mt-0.5">
                          {cand.verdict}
                        </span>
                      </div>
                    </div>

                    {/* Matched Precursor Factors */}
                    <div className="space-y-1.5">
                      <span className="text-[10px] font-bold tracking-wider text-muted uppercase">
                        Matched Causal Precursors (Pre-Move DNA):
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {cand.matched_factors?.map((f, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 text-[11px] font-medium rounded-md bg-elevated text-text border border-border"
                          >
                            ✓ {f}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Actionable Blueprint Levels */}
                    <div className="grid grid-cols-4 gap-2 p-2.5 rounded-xl bg-elevated border border-border text-center">
                      <div>
                        <span className="text-[10px] text-muted block uppercase">Entry Range</span>
                        <span className="text-xs font-bold text-text">{cand.entry_range}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted block uppercase">Invalidation SL</span>
                        <span className="text-xs font-bold text-rose-400">₹{cand.stop_loss}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted block uppercase">Target 1 (1.5R)</span>
                        <span className="text-xs font-bold text-emerald-400">₹{cand.target_1}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted block uppercase">Risk : Reward</span>
                        <span className="text-xs font-black text-amber-400">{cand.risk_reward}</span>
                      </div>
                    </div>

                    {/* Execution Playbook note */}
                    <div className="text-[11px] text-muted bg-panel p-2 rounded-lg border border-border space-y-1">
                      <div>
                        <strong className="text-emerald-400">When to Buy:</strong> {cand.when_to_buy}
                      </div>
                      <div>
                        <strong className="text-rose-400">When to Wait:</strong> {cand.when_to_wait}
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center justify-end gap-2 pt-1 border-t border-border">
                      <button
                        onClick={() => handleAnalyze(cand.symbol)}
                        className="btn btn-xs btn-outline"
                      >
                        🔍 Full Multi-Agent Debate
                      </button>
                      <button
                        onClick={() => handleBuy(cand)}
                        className="btn btn-xs btn-gold font-bold"
                      >
                        ⚡ Place Precursor Order
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ── SUB-TAB 2: Top Movers Forensic Autopsy ───────────────────── */}
      {activeSubTab === 'autopsy' && (
        <div className="space-y-4">
          {/* Direction Filter Bar */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1 bg-elevated p-1 rounded-xl border border-border">
              <button
                onClick={() => setSelectedDirection('ALL')}
                className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
                  selectedDirection === 'ALL'
                    ? 'bg-gold text-panel font-black shadow-sm'
                    : 'text-muted hover:text-text'
                }`}
              >
                All Movers ({validGainers.length + validLosers.length})
              </button>
              <button
                onClick={() => setSelectedDirection('GAINER')}
                className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
                  selectedDirection === 'GAINER'
                    ? 'bg-emerald-500 text-white font-black shadow-sm'
                    : 'text-muted hover:text-text'
                }`}
              >
                🚀 Top Gainers ({validGainers.length})
              </button>
              <button
                onClick={() => setSelectedDirection('LOSER')}
                className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
                  selectedDirection === 'LOSER'
                    ? 'bg-rose-500 text-white font-black shadow-sm'
                    : 'text-muted hover:text-text'
                }`}
              >
                🩸 Top Losers ({validLosers.length})
              </button>
            </div>

            {/* Signal-to-Noise Ratio (SNR) Indicator */}
            {autopsyData?.factor_snr && (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted">Volume Dry-up SNR:</span>
                <span className="font-bold text-emerald-400">
                  {autopsyData.factor_snr.volume_dry_up > 0 ? `+${autopsyData.factor_snr.volume_dry_up}` : autopsyData.factor_snr.volume_dry_up}
                </span>
                <span className="text-muted ml-2">Sector Tailwind SNR:</span>
                <span className="font-bold text-emerald-400">
                  {autopsyData.factor_snr.sector_tailwind > 0 ? `+${autopsyData.factor_snr.sector_tailwind}` : autopsyData.factor_snr.sector_tailwind}
                </span>
              </div>
            )}
          </div>

          {/* Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {displayedMovers.map((mover) => {
              const isGainer = mover.direction === 'GAINER' || mover.change_pct > 0
              const cleanArch = (mover.archetype || 'UNKNOWN_CATALYST').replace('ARCHETYPE_', '').replace(/_/g, ' ')

              return (
                <div
                  key={mover.symbol}
                  className="p-4 rounded-2xl bg-panel border border-border flex flex-col justify-between gap-3 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-black tracking-wide text-text">{mover.symbol}</span>
                        <span className="px-2 py-0.5 text-[10px] font-black rounded bg-elevated text-muted border border-border">
                          {mover.segment === 'FNO' ? '⚡ F&O' : mover.segment === 'NON_FNO' ? '📈 Cash' : mover.segment === 'INDEX' ? '🏛️ Index' : (mover.segment || '⚡ F&O')}
                        </span>
                        <span
                          className={`px-2 py-0.5 text-xs font-black rounded-lg ${
                            isGainer ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                          }`}
                        >
                          {isGainer ? `+${mover.change_pct}%` : `${mover.change_pct}%`}
                        </span>
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-elevated text-muted border border-border">
                          RVOL: {mover.rvol}x
                        </span>
                      </div>
                      <p className="text-xs text-muted mt-0.5">
                        LTP: ₹{mover.ltp} · Sector: {mover.sector_name} ({mover.rrg_quadrant}) · Turnover: ₹{mover.turnover_cr} Cr
                      </p>
                    </div>

                    <span className="px-2 py-1 text-[10px] font-black uppercase rounded bg-elevated text-gold border border-gold/30">
                      {cleanArch}
                    </span>
                  </div>

                  {/* Causal Breakdown Factors */}
                  <div className="space-y-1 bg-elevated p-2.5 rounded-xl border border-border">
                    <span className="text-[10px] font-bold text-muted uppercase block">
                      Why Did This Move Happen? (Causal Attribution):
                    </span>
                    <ul className="text-xs space-y-1">
                      {(mover.deciding_factors || (mover.causal_attribution ? [mover.causal_attribution] : []))?.map((f, idx) => (
                        <li key={idx} className="text-text flex items-start gap-1.5">
                          <span className="text-amber-400">▸</span>
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Key Lessons Learned */}
                  {mover.lessons_learned && mover.lessons_learned.length > 0 && (
                    <div className="text-[11px] text-muted p-2 rounded-lg bg-panel border border-border">
                      <span className="text-emerald-400 font-bold">🧠 Quantitative Lesson: </span>
                      {mover.lessons_learned[0]}
                    </div>
                  )}

                  {/* Footer actions */}
                  <div className="flex items-center justify-end gap-2 pt-1 border-t border-border">
                    <button
                      onClick={() => handleAnalyze(mover.symbol)}
                      className="btn btn-xs btn-outline"
                    >
                      🔍 Analyze Case Study
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── SUB-TAB 3: Traps Filtered Out ────────────────────────────── */}
      {activeSubTab === 'traps' && (
        <div className="space-y-3">
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/25 flex items-center justify-between text-xs text-rose-200">
            <div className="flex items-center gap-2">
              <span className="text-lg">🛡️</span>
              <span>
                <strong>False-Positive & Manipulation Elimination:</strong> Stocks with 5% circuit-to-circuit manipulation, negligible order book depth, or illiquid penny turnover (&lt; ₹10 Cr) are automatically quarantined from pattern learning.
              </span>
            </div>
            <span className="font-black px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[10px]">
              {traps.length} Quarantined
            </span>
          </div>

          {traps.length === 0 ? (
            <UnavailableState
              title="Zero Traps Detected Today"
              reason="All analyzed movers possessed genuine institutional liquidity and healthy order book depth."
              size="md"
            />
          ) : (
            <div className="space-y-2">
              {traps.map((t) => (
                <div
                  key={t.symbol}
                  className="p-3 rounded-xl bg-panel border border-rose-500/30 flex items-center justify-between gap-3 text-xs"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="text-base">🚫</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <strong className="text-text font-black">{t.symbol}</strong>
                        <span className="text-rose-400 font-bold">{t.change_pct}%</span>
                        <span className="text-muted">Turnover: ₹{t.turnover_cr} Cr</span>
                      </div>
                      <span className="text-rose-300 text-[11px] block mt-0.5">
                        {t.trap_reason || 'Illiquid operator pump with no institutional sponsorship.'}
                      </span>
                    </div>
                  </div>

                  <span className="px-2 py-1 text-[10px] font-bold rounded bg-rose-500/15 text-rose-400 border border-rose-500/30">
                    EXCLUDED FROM LEARNING
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── SUB-TAB 4: Asymmetric Setups (Low Risk : High Reward) ────── */}
      {activeSubTab === 'asymmetric' && (
        <div className="space-y-3">
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-between text-xs text-emerald-200">
            <div className="flex items-center gap-2">
              <span className="text-lg">🎯</span>
              <span>
                <strong>Low Risk : Big Reward Asymmetric Radar:</strong> Setups mathematically guaranteed to offer ≥ 1:3.0 Risk:Reward before major moves (Pocket Pivots, F&O Ban Squeezes, Rubber Band 200-EMA mean-reversions, and 0DTE Expiry Gamma).
              </span>
            </div>
            <span className="font-black px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[10px]">
              Min R:R ≥ 1:3.0
            </span>
          </div>

          {displayedAsymmetric.length === 0 ? (
            <UnavailableState
              title="No Qualified Asymmetric Setups Detected"
              reason="No stocks currently offer a confirmed 1:3.0+ risk-to-reward ratio with strict invalidation pivots. Patience preserves quant capital."
              size="md"
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {displayedAsymmetric.map((opp) => {
                const isMax = opp.conviction_score >= 85
                const badgeColor =
                  {
                    POCKET_PIVOT: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40',
                    FNO_BAN_SQUEEZE: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
                    RUBBER_BAND_200EMA: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
                    EXPIRY_0DTE_GAMMA: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
                  }[opp.setup_type] || 'bg-gold/20 text-gold border-gold/40'

                const setupTitle =
                  {
                    POCKET_PIVOT: '🚀 Pocket Pivot (Base Accumulation)',
                    FNO_BAN_SQUEEZE: '🔥 F&O Ban Squeeze (MWPL Trap)',
                    RUBBER_BAND_200EMA: '🧲 Rubber Band (200-EMA Value Dip)',
                    EXPIRY_0DTE_GAMMA: '⚡ 0DTE Gamma (Straddle Unpinning)',
                  }[opp.setup_type] || opp.setup_type

                return (
                  <div
                    key={`${opp.symbol}-${opp.setup_type}`}
                    className={`p-4 rounded-2xl bg-panel border transition-all hover:border-emerald-400/50 flex flex-col justify-between gap-3 shadow-sm ${
                      isMax ? 'border-emerald-400/40 bg-emerald-500/5' : 'border-border'
                    }`}
                  >
                    {/* Header */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-base font-black text-text">{opp.symbol}</span>
                          <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-elevated text-muted border border-border">
                            {opp.segment}
                          </span>
                          <span className={`px-2 py-0.5 text-[10px] font-black rounded border ${badgeColor}`}>
                            {setupTitle}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-black text-emerald-400">
                            1:{opp.risk_reward_ratio?.toFixed(1)} R:R
                          </span>
                          <span
                            className={`px-2 py-0.5 text-[11px] font-black rounded-lg ${
                              isMax ? 'bg-emerald-500 text-panel' : 'bg-gold text-panel'
                            }`}
                          >
                            🧠 {opp.conviction_score}/100
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span>
                          LTP:{' '}
                          <strong className="text-text">
                            ₹{opp.ltp?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          </strong>
                        </span>
                        <span>•</span>
                        <span>
                          Risk/Share:{' '}
                          <strong className="text-rose-400">₹{opp.risk_pts?.toFixed(1)}</strong>
                        </span>
                      </div>
                    </div>

                    {/* Confluences List */}
                    <div className="space-y-1 bg-elevated p-2 rounded-xl border border-border text-[11px]">
                      <span className="text-[10px] font-bold text-muted uppercase tracking-wider block">
                        Institutional Confluences:
                      </span>
                      <ul className="space-y-0.5">
                        {opp.confluences?.slice(0, 3).map((c, idx) => (
                          <li key={idx} className="text-text flex items-start gap-1">
                            <span className="text-emerald-400 font-bold">✓</span>
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Actionable Blueprint Grid */}
                    <div className="grid grid-cols-4 gap-1.5 text-center text-xs">
                      <div className="p-2 rounded-xl bg-elevated border border-border">
                        <span className="text-[10px] font-bold text-muted block">Entry Band</span>
                        <span className="font-black text-amber-300 text-[11px] truncate block">
                          {opp.entry_range}
                        </span>
                      </div>
                      <div className="p-2 rounded-xl bg-elevated border border-border">
                        <span className="text-[10px] font-bold text-muted block">Stop Loss</span>
                        <span className="font-black text-rose-400 text-[11px] block">
                          ₹{opp.stop_loss?.toFixed(1)}
                        </span>
                      </div>
                      <div className="p-2 rounded-xl bg-elevated border border-border">
                        <span className="text-[10px] font-bold text-muted block">Target 1 (+2R)</span>
                        <span className="font-black text-emerald-400 text-[11px] block">
                          ₹{opp.target_1?.toFixed(1)}
                        </span>
                      </div>
                      <div className="p-2 rounded-xl bg-elevated border border-border">
                        <span className="text-[10px] font-bold text-muted block">Moonshot (+6R)</span>
                        <span className="font-black text-purple-400 text-[11px] block">
                          ₹{opp.moonshot_target?.toFixed(1)}
                        </span>
                      </div>
                    </div>

                    {/* Trader Playbook Rules */}
                    <div className="p-2 rounded-xl bg-elevated/70 border border-border text-[11px] space-y-1">
                      <div>
                        <span className="font-bold text-emerald-400">Entry Rule: </span>
                        <span className="text-muted">{opp.entry_rule}</span>
                      </div>
                      <div>
                        <span className="font-bold text-rose-400">Strict No-Chase: </span>
                        <span className="text-rose-300">{opp.no_chase_rule}</span>
                      </div>
                      <div>
                        <span className="font-bold text-sky-400">Profit Scaling: </span>
                        <span className="text-muted">{opp.profit_rule}</span>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center justify-between pt-1 border-t border-border">
                      <button
                        onClick={() => handleAnalyze(opp.symbol)}
                        className="btn btn-xs btn-outline"
                      >
                        🔬 Full Audit
                      </button>
                      <button
                        onClick={() => handleBuy(opp)}
                        className="btn btn-xs bg-emerald-500 hover:bg-emerald-400 text-panel font-black flex items-center gap-1 shadow-sm"
                      >
                        <span>⚡</span>
                        <span>Place Asymmetric Order</span>
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
