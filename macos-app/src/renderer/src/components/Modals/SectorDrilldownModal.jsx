import { useEffect, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const QUADRANT_CONFIG = {
  LEADING:   { label: 'Leading',   bg: 'bg-green/15 text-green border-green/30',  icon: '🚀', desc: 'Outperforming NIFTY with strong momentum.' },
  IMPROVING: { label: 'Improving', bg: 'bg-blue/15 text-blue border-blue/30',    icon: '🔄', desc: 'Gaining relative velocity vs benchmark.' },
  WEAKENING: { label: 'Weakening', bg: 'bg-amber/15 text-amber border-amber/30',  icon: '⚠️', desc: 'Outperforming, but trend momentum is decelerating.' },
  LAGGING:   { label: 'Lagging',   bg: 'bg-red/15 text-red border-red/30',        icon: '📉', desc: 'Underperforming benchmark with negative momentum.' },
}

const ELIGIBILITY_CONFIG = {
  READY: {
    label: '🟢 TOP PICK (READY TO EXECUTE)',
    badgeColor: 'bg-green/20 text-green border-green/40 shadow-[0_0_8px_rgba(16,185,129,0.25)]',
    boxBg: 'bg-green/5 border-green/30 text-green-300',
    title: 'Actionable Setup',
    icon: '⚡',
  },
  STALK: {
    label: '🟡 WATCHLIST / STALK TRIGGER',
    badgeColor: 'bg-amber/20 text-amber border-amber/40 shadow-[0_0_8px_rgba(245,158,11,0.2)]',
    boxBg: 'bg-amber/5 border-amber/30 text-amber-200',
    title: 'Trigger Stalking',
    icon: '🎯',
  },
  STAND_DOWN: {
    label: '⚪ AVOID / LOW CONVICTION',
    badgeColor: 'bg-muted/15 text-muted border-border/40',
    boxBg: 'bg-panel/40 border-border/40 text-muted',
    title: 'Low Alignment',
    icon: '⏸️',
  },
}

export default function SectorDrilldownModal({ isOpen, sector, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState('ALL')
  const [expandedSymbol, setExpandedSymbol] = useState(null)
  const [telegramStatus, setTelegramStatus] = useState({})
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)

  const fetchSectorDrilldown = async (secName, forceRefresh = false) => {
    if (!secName) return
    setLoading(true)
    try {
      const res = await call('/skills/sector_drilldown', {
        sector: secName,
        exchange: 'NSE',
        refresh: forceRefresh,
      })
      setData(res?.data ?? res)
    } catch (err) {
      console.error('Failed to fetch sector drilldown:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen && sector) {
      setFilter('ALL')
      setExpandedSymbol(null)
      setData(null)
      fetchSectorDrilldown(sector, false)
    }
  }, [isOpen, sector])

  // Close on ESC or close-all-modals
  useEffect(() => {
    function onKeyDown(e) {
      if (isOpen && e.key === 'Escape') onClose()
    }
    function handleCloseAll() {
      if (isOpen) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('close-all-modals', handleCloseAll)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('close-all-modals', handleCloseAll)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const opportunities = data?.opportunities || []
  const rrg = data?.rrg || {}
  const breadth = data?.breadth || {}
  const quadCfg = QUADRANT_CONFIG[rrg.quadrant] || QUADRANT_CONFIG.LEADING

  // Filter stocks by eligibility
  const filteredOpps = opportunities.filter((opp) => {
    if (filter === 'ALL') return true
    const status = opp.eligibility_status || 'READY'
    return status === filter
  })

  const readyCount = breadth.ready_count ?? opportunities.filter((o) => o.eligibility_status === 'READY').length
  const stalkCount = breadth.stalk_count ?? opportunities.filter((o) => o.eligibility_status === 'STALK').length
  const standDownCount = breadth.stand_down_count ?? opportunities.filter((o) => o.eligibility_status === 'STAND_DOWN').length

  const handleSendTelegram = async (opp) => {
    setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: 'sending' }))
    try {
      await call('/skills/send_opportunity_telegram', { opportunity: opp })
      setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: 'sent' }))
      setTimeout(() => {
        setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: null }))
      }, 3000)
    } catch {
      setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: 'error' }))
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200 select-none"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border/80 rounded-2xl w-full max-w-4xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden font-ui animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-6 py-4 border-b border-border bg-panel flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{data?.sector_icon || '🏢'}</span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-text flex items-center gap-2">
                  <span>{data?.sector_name || sector}</span>
                </h2>
                <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${quadCfg.bg}`}>
                  {quadCfg.icon} {quadCfg.label} Quadrant
                </span>
              </div>
              <p className="text-xs text-muted mt-0.5 font-mono">
                Benchmark: <strong className="text-text">NIFTY 50</strong> · Index: <span className="text-amber">{data?.index_symbol || '^INDEX'}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchSectorDrilldown(sector, true)}
              disabled={loading}
              className="flex items-center gap-1.5 bg-elevated hover:bg-panel border border-border px-3 py-1.5 rounded-lg text-xs font-semibold text-text transition-colors cursor-pointer disabled:opacity-50"
            >
              <span className={loading ? 'animate-spin' : ''}>🔄</span>
              <span>{loading ? 'Analyzing…' : 'Refresh'}</span>
            </button>
            <button
              onClick={onClose}
              className="text-muted hover:text-text p-1.5 rounded-lg hover:bg-elevated text-lg transition-colors cursor-pointer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Sector Health & Quantitative Breadth Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 px-6 py-3 border-b border-border/50 bg-panel/50 text-xs flex-shrink-0 font-mono">
          <div className="bg-elevated/70 border border-border/40 p-2.5 rounded-xl">
            <div className="flex items-center justify-between text-muted text-[10px] uppercase">
              <span>Trend (RS-Ratio)</span>
              <InfoBadge title="RS-Ratio" content=">100 indicates outperforming the broad market trend." metricKey="rrg_sector_matrix" />
            </div>
            <p className="text-base font-bold text-text mt-0.5">
              {Number(rrg.rs_ratio || 100).toFixed(1)}
              <span className={`text-[11px] ml-1 font-semibold ${Number(rrg.rs_ratio) >= 100 ? 'text-green' : 'text-amber'}`}>
                {Number(rrg.rs_ratio) >= 100 ? '▲ Strong' : '▼ Lagging'}
              </span>
            </p>
          </div>

          <div className="bg-elevated/70 border border-border/40 p-2.5 rounded-xl">
            <div className="flex items-center justify-between text-muted text-[10px] uppercase">
              <span>Velocity (RS-Mom)</span>
              <InfoBadge title="RS-Momentum" content=">100 indicates accelerating relative strength velocity." metricKey="rrg_sector_matrix" />
            </div>
            <p className="text-base font-bold text-text mt-0.5">
              {Number(rrg.rs_momentum || 100).toFixed(1)}
              <span className={`text-[11px] ml-1 font-semibold ${Number(rrg.rs_momentum) >= 100 ? 'text-green' : 'text-amber'}`}>
                {Number(rrg.rs_momentum) >= 100 ? '⚡ Accelerating' : '⏳ Slowing'}
              </span>
            </p>
          </div>

          <div className="bg-elevated/70 border border-border/40 p-2.5 rounded-xl">
            <div className="flex items-center justify-between text-muted text-[10px] uppercase">
              <span>Stage 2 Breadth</span>
              <InfoBadge title="Sector Breadth" content="% of constituent equities in confirmed Minervini / Stan Weinstein Stage 2 markup." metricKey="two_tier_pipeline" />
            </div>
            <p className="text-base font-bold text-text mt-0.5">
              {breadth.stage_2_pct ?? 0}%
              <span className="text-[10px] text-muted ml-1 font-normal">({breadth.total_stocks || opportunities.length} Equities)</span>
            </p>
          </div>

          <div className="bg-elevated/70 border border-border/40 p-2.5 rounded-xl">
            <div className="flex items-center justify-between text-muted text-[10px] uppercase">
              <span>Execution Summary</span>
              <InfoBadge title="Trade Eligibility" content="Number of sector stocks immediately eligible for execution vs stalking watchlist." metricKey="two_tier_pipeline" />
            </div>
            <p className="text-base font-bold text-green mt-0.5 flex items-center gap-2">
              <span>🟢 {readyCount} Ready</span>
              <span className="text-amber text-xs">🟡 {stalkCount} Stalk</span>
            </p>
          </div>
        </div>

        {/* Eligibility Filter Pills */}
        <div className="flex items-center gap-2 px-6 py-2.5 border-b border-border/40 bg-panel/30 overflow-x-auto text-xs flex-shrink-0">
          <span className="text-muted text-[11px] font-semibold uppercase tracking-wider flex-shrink-0">
            Eligibility Filter:
          </span>
          {[
            { id: 'ALL', label: `All Equities (${opportunities.length})` },
            { id: 'READY', label: `🟢 Top Picks (Ready to Execute) (${readyCount})`, activeClass: 'bg-green/20 text-green border-green/40 font-bold' },
            { id: 'STALK', label: `🟡 Watchlist / Stalking (${stalkCount})`, activeClass: 'bg-amber/20 text-amber border-amber/40 font-bold' },
            { id: 'STAND_DOWN', label: `⚪ Avoid / Low Conviction (${standDownCount})`, activeClass: 'bg-panel text-muted border-border font-bold' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilter(tab.id)}
              className={`px-3 py-1 rounded-lg text-xs transition-colors cursor-pointer flex-shrink-0 border ${
                filter === tab.id
                  ? (tab.activeClass || 'bg-amber text-black font-bold border-amber')
                  : 'bg-elevated/50 hover:bg-elevated text-muted hover:text-text border-border/40'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Modal Body: Stock Cards with Contributing Factors & Rationale */}
        <div className="flex-1 overflow-y-auto p-6 space-y-3">
          {loading && opportunities.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 space-y-3">
              <span className="text-3xl animate-spin">⏳</span>
              <p className="text-sm font-semibold text-text">Scanning sector constituents and computing quantitative factors…</p>
              <p className="text-xs text-muted">Analyzing SMC Market Structure, RVOL surge, Minervini criteria & Forensics.</p>
            </div>
          ) : filteredOpps.length === 0 ? (
            <div className="p-8 text-center text-muted text-xs bg-panel rounded-xl border border-border/40 font-ui">
              No equities match the selected eligibility filter in this sector scan.
            </div>
          ) : (
            filteredOpps.map((opp) => {
              const isExpanded = expandedSymbol === opp.symbol
              const elig = ELIGIBILITY_CONFIG[opp.eligibility_status] || ELIGIBILITY_CONFIG.READY
              const scoreColor = opp.conviction_score >= 80 ? 'text-green' : opp.conviction_score >= 60 ? 'text-amber' : 'text-blue'
              const tgState = telegramStatus[opp.symbol]
              const cf = opp.contributing_factors || {}

              return (
                <div
                  key={opp.symbol}
                  className={`bg-panel border rounded-xl p-4 transition-all duration-200 font-mono shadow-xs ${
                    opp.eligibility_status === 'READY'
                      ? 'border-green/40 hover:border-green/60 bg-gradient-to-r from-green/5 via-panel to-panel'
                      : opp.eligibility_status === 'STALK'
                      ? 'border-amber/30 hover:border-amber/50'
                      : 'border-border/40 opacity-80'
                  }`}
                >
                  {/* Stock Header Row */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-elevated border border-border/60 flex items-center justify-center font-bold text-xs text-amber">
                        {opp.rank || '•'}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-base font-bold text-text tracking-wide font-ui">{opp.symbol}</span>
                          <span className="text-xs text-muted font-ui">₹{Number(opp.ltp || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${elig.badgeColor}`}>
                            {opp.eligibility_label || elig.label}
                          </span>
                        </div>
                        <p className="text-[11px] text-muted font-ui mt-0.5">{opp.setup_title || opp.setup_type}</p>
                      </div>
                    </div>

                    {/* Right Quick Badges & Conviction Score */}
                    <div className="flex items-center gap-2.5">
                      <div className="text-right">
                        <p className="text-[10px] text-muted font-ui uppercase">Conviction Score</p>
                        <p className={`text-sm font-bold ${scoreColor}`}>
                          {opp.conviction_score}/100
                        </p>
                      </div>

                      <button
                        onClick={() => setExpandedSymbol(isExpanded ? null : opp.symbol)}
                        className="bg-elevated hover:bg-border px-3 py-1.5 rounded-lg text-xs font-ui font-semibold text-text transition-colors cursor-pointer border border-border/60"
                      >
                        {isExpanded ? 'Hide Factors ▲' : 'Inspect Factors ▼'}
                      </button>
                    </div>
                  </div>

                  {/* Highlighted "Why Pick / Why Avoid" Institutional Callout Banner */}
                  <div className={`mt-3 p-3 rounded-lg border text-xs font-ui leading-relaxed ${elig.boxBg}`}>
                    <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-[10px] mb-1">
                      <span>{elig.icon}</span>
                      <span>Quantitative Recommendation & Rationale:</span>
                    </div>
                    <p className="text-xs opacity-95">
                      {opp.why_rationale || opp.catalyst_summary || 'Evaluating quantitative momentum and structural alignment.'}
                    </p>
                  </div>

                  {/* Contributing Factors Key Value Tags */}
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                    <div className="bg-elevated/70 border border-border/40 px-2.5 py-1.5 rounded-lg flex flex-col justify-center">
                      <span className="text-[9px] text-muted uppercase font-ui">Weinstein Stage</span>
                      <span className="font-bold text-text text-[11px] truncate">💎 {cf.stage || opp.weinstein_stage}</span>
                    </div>
                    <div className="bg-elevated/70 border border-border/40 px-2.5 py-1.5 rounded-lg flex flex-col justify-center">
                      <span className="text-[9px] text-muted uppercase font-ui">Minervini Trend</span>
                      <span className="font-bold text-text text-[11px]">📊 {cf.trend_template || `${opp.trend_template_passed}/8 Passed`}</span>
                    </div>
                    <div className="bg-elevated/70 border border-border/40 px-2.5 py-1.5 rounded-lg flex flex-col justify-center">
                      <span className="text-[9px] text-muted uppercase font-ui">Relative Volume</span>
                      <span className={`font-bold text-[11px] ${Number(opp.rvol_20d) >= 1.5 ? 'text-green' : 'text-amber'}`}>
                        ⚡ {cf.rvol || `${Number(opp.rvol_20d || 1.0).toFixed(1)}x RVOL`}
                      </span>
                    </div>
                    <div className="bg-elevated/70 border border-border/40 px-2.5 py-1.5 rounded-lg flex flex-col justify-center">
                      <span className="text-[9px] text-muted uppercase font-ui">Forensic Safety</span>
                      <span className="font-bold text-text text-[11px]">🛡️ {cf.forensic_grade || `Grade ${opp.forensic_quality || 'A'}`}</span>
                    </div>
                  </div>

                  {/* Expanded Detailed Blueprint & Playbook Strip */}
                  {isExpanded && (
                    <div className="mt-3 pt-3 border-t border-border/50 space-y-3 text-xs font-ui animate-in fade-in duration-150">
                      {/* Actionable Blueprint Grid */}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-elevated/90 p-3 rounded-lg border border-border/60 font-mono">
                        <div>
                          <span className="text-[10px] text-muted uppercase font-ui">Entry Zone</span>
                          <p className="font-bold text-text text-sm">₹{Number(opp.entry_price).toFixed(2)}</p>
                        </div>
                        <div>
                          <span className="text-[10px] text-muted uppercase font-ui">Invalidation SL</span>
                          <p className="font-bold text-red text-sm">₹{Number(opp.stop_loss).toFixed(2)}</p>
                        </div>
                        <div>
                          <span className="text-[10px] text-muted uppercase font-ui">Target 1 (+2R)</span>
                          <p className="font-bold text-green text-sm">₹{Number(opp.target_1).toFixed(2)}</p>
                        </div>
                        <div>
                          <span className="text-[10px] text-muted uppercase font-ui">Risk : Reward</span>
                          <p className="font-bold text-amber text-sm">1:{opp.risk_reward_ratio} R:R</p>
                        </div>
                      </div>

                      {/* Holding Timeline & Playbook Banner */}
                      <div className="flex flex-wrap items-center gap-2 text-[11px] bg-panel/70 border border-border/40 p-2 rounded-lg text-muted">
                        <span className="text-amber font-semibold">⏳ Horizon:</span>
                        <span className="text-text font-mono font-medium">{opp.expected_timeline || '3–10 Trading Days'}</span>
                        <span className="text-border">|</span>
                        <span className="text-green font-semibold">Target 1:</span>
                        <span className="text-text font-mono">{opp.target_1_timeline || '2–5 Days'}</span>
                        <span className="text-border">|</span>
                        <span className="text-red font-semibold">Time Invalidation:</span>
                        <span className="text-text font-mono">{opp.time_stop_days || 10} sessions</span>
                      </div>

                      {opp.profit_booking_plan && (
                        <div className="p-2.5 rounded-lg bg-elevated border border-border/40 text-[11px] text-muted leading-relaxed">
                          <strong className="text-amber uppercase text-[10px] block mb-0.5">📋 Execution & Profit-Booking Playbook:</strong>
                          {opp.profit_booking_plan}
                        </div>
                      )}

                      {/* Action Bar */}
                      <div className="flex items-center justify-between pt-1">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              onClose()
                              sendDraft(`size ${opp.symbol} ${Number(opp.entry_price).toFixed(2)} ${Number(opp.stop_loss).toFixed(2)}`)
                            }}
                            className="bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer"
                            title="Size position with volatility risk parity"
                          >
                            ⚡ Size Position
                          </button>
                          <button
                            onClick={() => {
                              onClose()
                              sendDraft(`analyze ${opp.symbol}`)
                            }}
                            className="bg-amber hover:bg-amber/90 text-black px-3 py-1.5 rounded-lg text-xs font-bold transition-colors cursor-pointer shadow-xs"
                            title="Launch Full Multi-Agent AI Debate"
                          >
                            🤖 AI Debate
                          </button>
                        </div>

                        <button
                          onClick={() => handleSendTelegram(opp)}
                          disabled={tgState === 'sending' || tgState === 'sent'}
                          className="flex items-center gap-1 bg-green/15 hover:bg-green/25 text-green border border-green/30 px-3 py-1.5 rounded-lg text-xs font-bold transition-colors cursor-pointer"
                        >
                          <span>📱</span>
                          <span>
                            {tgState === 'sending'
                              ? 'Sending…'
                              : tgState === 'sent'
                              ? '✓ Alert Sent!'
                              : tgState === 'error'
                              ? '⚠️ Failed'
                              : 'Send to Telegram'}
                          </span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3 border-t border-border/50 bg-panel/50 flex items-center justify-between text-xs text-muted flex-shrink-0 font-ui">
          <span>Click anywhere outside or press <kbd className="bg-elevated px-1.5 py-0.5 rounded border border-border font-mono text-[10px]">ESC</kbd> to return to dashboard.</span>
          <span className="font-mono text-[10px] text-muted">
            Data Source: <strong className="text-text">{data?.data_source || 'HISTORICAL_EOD'}</strong> (250D Daily Bars)
          </span>
        </div>
      </div>
    </div>
  )
}
