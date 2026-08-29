import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const POSTURE_BADGES = {
  BULLISH_EXPANSION:    { label: '🚀 Bullish Expansion', color: 'bg-green text-surface font-bold', desc: 'Over 60% of universe in confirmed structural markup.' },
  CHOPPY_ROTATION:      { label: '⚖️ Choppy Rotation', color: 'bg-amber/15 text-amber border border-amber/30', desc: 'Mixed market structure; prioritize stock-specific momentum and tight invalidation stops.' },
  DEFENSIVE_RISK_OFF:   { label: '🛡️ Defensive / Risk-Off', color: 'bg-red text-surface font-bold', desc: 'Broad market weakness; focus on hedging or bottom-fishing springs.' },
}

const LIQUIDITY_TIER_BADGES = {
  TIER_1_ULTRA_LIQUID:  { label: '💧 Ultra Liquid (>₹100 Cr)', color: 'text-blue bg-blue/10 border-blue/30' },
  TIER_2_ACTIVE_LIQUID: { label: '⚡ Active Liquid (>₹25 Cr)', color: 'text-green bg-green/10 border-green/30' },
  TIER_3_MIDCAP:        { label: '💎 Active Midcap', color: 'text-amber bg-amber/10 border-amber/30' },
}

export default function HighConvictionCard({ data, onOpenOrderTicket }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const opportunities = d.opportunities || []
  const [filter, setFilter] = useState('ALL')
  const [expandedRow, setExpandedRow] = useState(null)
  const [telegramStatus, setTelegramStatus] = useState({})
  const { call } = useAPI()

  const openInspector = useInspectorStore((s) => s.openInspector)
  const sendDraft = useChatStore((s) => s.sendDraft)

  const posture = POSTURE_BADGES[d.market_posture] || POSTURE_BADGES.CHOPPY_ROTATION

  const handleSendTelegram = async (opp) => {
    setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: 'sending' }))
    try {
      await call('/skills/send_opportunity_telegram', {
        opportunity: opp,
      })
      setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: 'sent' }))
      setTimeout(() => {
        setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: null }))
      }, 3000)
    } catch {
      setTelegramStatus((prev) => ({ ...prev, [opp.symbol]: 'error' }))
    }
  }

  const readyCount = opportunities.filter(
    (o) => (o.eligibility_status || (o.conviction_score >= 70 ? 'READY' : 'STALK')) === 'READY'
  ).length
  const stalkCount = opportunities.filter(
    (o) => (o.eligibility_status || (o.conviction_score >= 70 ? 'READY' : 'STALK')) === 'STALK'
  ).length

  // Filter logic
  const filteredOpps = opportunities.filter((opp) => {
    if (filter === 'ALL') return true
    const status = opp.eligibility_status || (opp.conviction_score >= 70 ? 'READY' : 'STALK')
    if (filter === 'READY') return status === 'READY'
    if (filter === 'STALK') return status === 'STALK'
    if (filter === 'STAND_DOWN') return status === 'STAND_DOWN'
    const setup = (opp.setup_type || '').toUpperCase()
    if (filter === 'BREAKOUT') return setup.includes('BREAKOUT') || setup.includes('STAGE_2')
    if (filter === 'VCP') return setup.includes('VCP')
    if (filter === 'PULLBACK') return setup.includes('PULLBACK')
    if (filter === 'BOTTOM_FISHING') return setup.includes('BOTTOM_FISHING')
    return false
  })

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-3xl w-full space-y-4 font-mono shadow-md">
      {/* Header & Posture Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/50 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">🎯</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Market-Aware Opportunity Radar</p>
              <InfoBadge
                title="Two-Tier Decision Engine"
                content="Combines Strategic Conviction (Historical SMC, Minervini, RRG, Forensics) with Live Tactical Execution Gates (Live Tick, RVOL Surge, Options OI Buildup)."
                metricKey="execution_gate_pipeline"
              />
            </div>
            <p className="text-text text-base font-bold font-ui">Top High-Conviction Opportunities</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {d.data_source === 'LIVE_TICK' ? (
            <span className="text-[10px] bg-green/15 text-green border border-green/30 px-2 py-0.5 rounded font-ui font-semibold flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green animate-pulse"></span>
              Live Feed
            </span>
          ) : (
            <span
              className="text-[10px] bg-blue/15 text-blue border border-blue/30 px-2 py-0.5 rounded font-ui font-semibold flex items-center gap-1"
              title={d.dataset_timeline || 'NSE Daily OHLCV (250 Bars Lookback · EOD)'}
            >
              📅 EOD Dataset
            </span>
          )}
          <span className={`text-xs px-2.5 py-1 rounded font-ui ${posture.color}`}>
            {posture.label}
          </span>
          <span className="text-[10px] bg-panel border border-border px-2 py-1 rounded text-muted font-ui">
            {d.timestamp}
          </span>
        </div>
      </div>

      {/* Dataset & Timeline Provenance Banner */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 bg-panel/50 border border-border/50 rounded-lg text-[11px] font-ui text-muted">
        <div className="flex items-center gap-1.5">
          <span>📊</span>
          <span><strong className="text-text">Dataset Provenance:</strong> {d.dataset_timeline || 'NSE Daily OHLCV (250 Bars Lookback · EOD Daily Bars)'}</span>
        </div>
        <div className="flex items-center gap-1">
          <span>Timeline: <span className="text-text font-mono font-semibold">{d.timestamp}</span></span>
        </div>
      </div>

      {/* Top-Down Dynamic Routing Context */}
      {d.top_down_rationale && (
        <div className="bg-panel border border-border/60 p-2.5 rounded-lg text-xs font-ui text-text flex items-center gap-2">
          <span className="text-amber text-sm flex-shrink-0">⚡</span>
          <p className="text-muted text-[11px] leading-snug">
            <strong className="text-text">Strategy Context:</strong> {d.top_down_rationale}
          </p>
        </div>
      )}


      {/* Leading Sectors Strip */}
      {d.leading_sectors && d.leading_sectors.length > 0 && (
        <div className="flex items-center gap-1.5 bg-panel border border-border/50 p-2 rounded-lg text-xs font-ui overflow-x-auto">
          <span className="text-muted text-[10px] uppercase tracking-wider font-semibold flex-shrink-0">
            Leading Sectors:
          </span>
          {d.leading_sectors.map((sec, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: sec } }))}
              className="bg-green/10 hover:bg-green/20 text-green border border-green/30 hover:border-green text-[10px] px-2 py-0.5 rounded font-mono font-bold flex-shrink-0 cursor-pointer transition-all hover:scale-105"
              title={`Click to view all stocks and contributing factors in ${sec}`}
            >
              ⚡ {sec} →
            </button>
          ))}
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs font-ui">
        {[
          { id: 'ALL', label: `All (${opportunities.length})` },
          { id: 'READY', label: `🟢 Ready (${readyCount})`, activeClass: 'bg-green text-black font-bold' },
          { id: 'STALK', label: `🟡 Stalking (${stalkCount})`, activeClass: 'bg-amber text-black font-bold' },
          { id: 'BREAKOUT', label: '🚀 Breakouts' },
          { id: 'VCP', label: '⚡ VCP' },
          { id: 'PULLBACK', label: '🎯 Pullback' },
          { id: 'BOTTOM_FISHING', label: '🎣 Bottom Fishing' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setFilter(tab.id)}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer flex-shrink-0 ${
              filter === tab.id
                ? (tab.activeClass || 'bg-amber text-black font-bold')
                : 'bg-panel hover:bg-elevated text-muted hover:text-text border border-border/40'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Opportunity Table / Card List */}
      <div className="space-y-2">
        {filteredOpps.length === 0 ? (
          <div className="p-6 text-center text-muted text-xs font-ui bg-panel rounded-lg border border-border/40">
            No opportunities match this filter in the current scan.
          </div>
        ) : (
          filteredOpps.map((opp) => {
            const isExpanded = expandedRow === opp.symbol
            const scoreColor =
              opp.conviction_score >= 85 ? 'text-green' : opp.conviction_score >= 70 ? 'text-amber' : 'text-blue'
            const liqBadge = LIQUIDITY_TIER_BADGES[opp.liquidity_tier] || LIQUIDITY_TIER_BADGES.TIER_2_ACTIVE_LIQUID
            const tgState = telegramStatus[opp.symbol]

            // Determine canonical execution readiness badge from eligibility status
            const status = opp.eligibility_status || (opp.conviction_score >= 70 ? 'READY' : 'STALK')
            const readinessBadge =
              status === 'READY'
                ? { label: '🟢 READY', color: 'bg-green/15 text-green border-green/30' }
                : status === 'STALK'
                ? { label: '🟡 STALK', color: 'bg-amber/15 text-amber border-amber/30' }
                : { label: '⚪ STAND DOWN', color: 'bg-panel text-muted border-border/40' }

            return (
              <div
                key={opp.symbol}
                className="bg-panel hover:bg-elevated/80 border border-border/60 rounded-lg p-3 transition-colors space-y-2.5"
              >
                {/* Main Row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-bold text-amber bg-elevated border border-border px-2 py-1 rounded font-mono">
                      #{opp.rank}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-text font-mono tracking-wide">{opp.symbol}</span>
                        <span className="text-[11px] text-muted font-ui flex items-center gap-1">
                          <span>{opp.sector_icon || '🏢'}</span>
                          <span>{opp.sector}</span>
                        </span>
                        <span className="text-xs font-bold text-text font-mono">₹{opp.ltp?.toLocaleString()}</span>
                      </div>
                      <p className="text-[11px] text-muted font-ui mt-0.5 flex items-center gap-1.5 flex-wrap">
                        <span className="font-semibold text-text">{opp.setup_title}</span>
                        <span>•</span>
                        <span className="text-amber font-mono font-bold">1:{opp.risk_reward_ratio} R:R</span>
                        <span>•</span>
                        <span className={`text-[9px] px-1.5 py-0.2 rounded border font-mono ${liqBadge.color}`}>
                          ₹{opp.est_turnover_cr} Cr / day
                        </span>
                        <span>•</span>
                        <span className={`text-[9px] px-1.5 py-0.2 rounded border font-mono font-bold ${readinessBadge.color}`}>
                          {readinessBadge.label}
                        </span>
                      </p>
                    </div>
                  </div>

                  {/* Conviction Gauge & Action Buttons */}
                  <div className="flex items-center gap-2 sm:justify-end flex-wrap">
                    <Tooltip
                      title={`${opp.symbol} Strategic Conviction`}
                      content="Historical multi-pillar model: SMC Fractal Structure + RVOL Footprint + Minervini Stage 2 + RRG Sector Momentum + Forensic Quality."
                      metricKey="strategic_scoring"
                    >
                      <div className="flex items-center gap-1.5 bg-elevated px-2.5 py-1 rounded border border-border/60">
                        <span className="text-[10px] text-muted uppercase font-ui">Conviction</span>
                        <span className={`text-sm font-bold font-mono ${scoreColor}`}>
                          {opp.conviction_score}/100
                        </span>
                      </div>
                    </Tooltip>

                    <button
                      onClick={() => handleSendTelegram(opp)}
                      disabled={tgState === 'sending' || tgState === 'sent'}
                      className={`px-2 py-1 rounded border text-[11px] font-ui transition-colors cursor-pointer flex items-center gap-1 ${
                        tgState === 'sent'
                          ? 'bg-green/15 text-green border-green/30 font-bold'
                          : 'bg-elevated hover:bg-panel border-border/60 text-muted hover:text-text'
                      }`}
                      title="Send Instant Actionable Alert to Telegram"
                    >
                      <span>📱</span>
                      <span>{tgState === 'sending' ? 'Sending…' : tgState === 'sent' ? '✓ Sent' : 'Telegram'}</span>
                    </button>

                    <button
                      onClick={() => setExpandedRow(isExpanded ? null : opp.symbol)}
                      className="px-2 py-1 rounded bg-elevated hover:bg-panel border border-border/60 text-muted hover:text-text text-[11px] font-ui transition-colors cursor-pointer"
                    >
                      {isExpanded ? 'Hide ▲' : 'Levels ▼'}
                    </button>

                    <button
                      onClick={() => {
                        window.dispatchEvent(new CustomEvent('close-all-modals'))
                        sendDraft(`analyze ${opp.symbol}`)
                      }}
                      className="px-2.5 py-1 rounded bg-amber hover:bg-amber/90 text-black font-ui font-bold text-[11px] transition-colors cursor-pointer shadow-xs"
                      title="Run Full Multi-Agent AI Debate"
                    >
                      AI Debate 🤖
                    </button>
                  </div>
                </div>

                {/* Catalyst Notes Strip */}
                <div className="flex items-center justify-between text-[11px] font-ui bg-elevated/40 px-2.5 py-1 rounded border border-border/30">
                  <span className="text-muted truncate">💡 {opp.catalyst_summary}</span>
                  <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                    {opp.tags?.map((t, idx) => (
                      <span key={idx} className="bg-panel text-muted text-[9px] px-1.5 py-0.5 rounded border border-border/40">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Expanded Actionable Blueprint */}
                {isExpanded && (
                  <div className="pt-2 border-t border-border/40 space-y-2 text-xs font-ui">
                    {/* Institutional Why Rationale Callout */}
                    {opp.why_rationale && (
                      <div className="bg-green/10 border border-green/30 p-2.5 rounded-lg text-xs font-ui text-green-300">
                        <strong className="text-[10px] uppercase text-green font-bold block mb-0.5">🎯 Institutional Rationale & Contributing Factors:</strong>
                        {opp.why_rationale}
                      </div>
                    )}

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-elevated/70 p-2.5 rounded font-mono">
                      <div>
                        <span className="text-[10px] text-muted font-ui uppercase">Entry Level</span>
                        <p className="font-bold text-text">₹{opp.entry_price?.toLocaleString()}</p>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui uppercase">Invalidation SL</span>
                        <p className="font-bold text-red">₹{opp.stop_loss?.toLocaleString()} (-{opp.risk_pts} pts)</p>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui uppercase">Target 1 (2R)</span>
                        <p className="font-bold text-green">₹{opp.target_1?.toLocaleString()} (+{opp.reward_pts} pts)</p>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted font-ui uppercase">Target 2 (3.5R)</span>
                        <p className="font-bold text-green">₹{opp.target_2?.toLocaleString()}</p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                      <div className="flex items-center gap-2 text-[11px] text-muted">
                        <span>Structure: <strong className="text-text">{opp.structure_regime}</strong></span>
                        <span>•</span>
                        <span>Stage: <strong className="text-text">{opp.weinstein_stage}</strong></span>
                        <span>•</span>
                        <span>RVOL: <strong className="text-amber">{opp.rvol_20d}x</strong></span>
                        <span>•</span>
                        <span>Balance Sheet: <strong className="text-green">Grade {opp.forensic_quality}</strong></span>
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => openInspector('market_structure_smc', { symbol: opp.symbol })}
                          className="text-[10px] text-amber hover:underline cursor-pointer"
                        >
                          View SMC Blueprint →
                        </button>
                        <button
                          onClick={() => {
                            window.dispatchEvent(new CustomEvent('close-all-modals'))
                            sendDraft(`size ${opp.symbol} ${opp.entry_price} ${opp.stop_loss}`)
                          }}
                          className="text-[10px] bg-panel hover:bg-elevated border border-border px-2 py-0.5 rounded text-text cursor-pointer"
                        >
                          Size Position ⚖️
                        </button>
                      </div>
                    </div>

                    {/* Expected Timeline & Profit-Booking Playbook */}
                    <div className="bg-panel/60 p-2 rounded border border-border/30 space-y-1.5 text-[11px]">
                      <div className="flex flex-wrap items-center justify-between gap-1 text-muted">
                        <span className="flex items-center gap-1">
                          <span>⏳</span>
                          <span>Horizon: <strong className="text-text">{opp.expected_timeline || '3–10 Trading Days (Swing Momentum)'}</strong></span>
                        </span>
                        <span className="flex items-center gap-2">
                          <span>T1: <strong className="text-green font-mono">{opp.target_1_timeline || '2–5 Days'}</strong></span>
                          <span>•</span>
                          <span>T2: <strong className="text-green font-mono">{opp.target_2_timeline || '6–10 Days'}</strong></span>
                          <span>•</span>
                          <span>Time Invalidation: <strong className="text-red font-mono">{opp.time_stop_days || 10} Sessions</strong></span>
                        </span>
                      </div>
                      <p className="text-[10px] text-muted leading-tight border-t border-border/20 pt-1">
                        📋 <strong>Playbook:</strong> {opp.profit_booking_plan || `Scale out 50% at Target 1 (₹${opp.target_1?.toLocaleString()}), move SL to Breakeven (+0.2%), and trail remainder via Daily 20-EMA to Target 2.`}
                      </p>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-border/20 mt-1 text-[10px] text-muted">
                      <span>📊 Data Basis: <strong className="text-text font-mono">{opp.dataset_info || 'NSE Daily OHLCV (250 Bars)'}</strong></span>
                      <span>As of: <strong className="text-text font-mono">{opp.as_of_date || d.timestamp}</strong></span>
                    </div>
                  </div>
                )}

              </div>
            )
          })
        )}
      </div>

      {/* Footer Summary */}
      <div className="text-[11px] text-muted font-ui leading-relaxed bg-panel p-2.5 rounded border border-border/40">
        📌 <strong>Execution Rule:</strong> Only execute when live status is 🟢 <strong>READY</strong> (trigger active within &plusmn;0.5% entry zone). When 🟡 <strong>STALK</strong>, set limit order near 20-EMA/Demand OB. When +2R is reached, scale out 33%–50% and trail with Chandelier ATR.
      </div>
    </div>
  )
}
