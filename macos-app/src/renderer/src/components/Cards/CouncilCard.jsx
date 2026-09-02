import { useState } from 'react'
import Tooltip, { InfoBadge } from '../UI/Tooltip'
import { useChatStore } from '../../store/chatStore'

const VERDICT_STYLES = {
  STRONG_BUY: 'bg-emerald-500 text-black font-extrabold shadow-emerald-500/20 shadow-lg',
  BUY: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold',
  HOLD: 'bg-amber-500/15 text-amber-400 border border-amber-500/30 font-bold',
  SELL: 'bg-rose-500/15 text-rose-400 border border-rose-500/30 font-bold',
  STRONG_SELL: 'bg-rose-500 text-white font-extrabold shadow-rose-500/20 shadow-lg',
  UNAVAILABLE: 'bg-slate-500/15 text-slate-300 border border-slate-500/30 font-bold',
}

const COUNCIL_ICONS = {
  breakout: '🚀',
  options_sniper: '🎯',
  multibagger: '💎',
  macro_regime: '🌐',
  core_value: '🏛️',
}

const PERSONA_NAMES = {
  buffett: 'Warren Buffett',
  munger: 'Charlie Munger',
  lynch: 'Peter Lynch',
  jhunjhunwala: 'Rakesh Jhunjhunwala',
  kedia: 'Vijay Kedia',
  minervini: 'Mark Minervini',
  wyckoff: 'Richard Wyckoff',
  oneil: "William O'Neil",
  taleb: 'Nassim Taleb',
  simons: 'Jim Simons',
  smc: 'Smart Money Concepts',
  forensic: 'Forensic Auditor',
  soros: 'George Soros',
}

export default function CouncilCard({ data }) {
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [expandedPersona, setExpandedPersona] = useState(null)

  if (!data) return null
  const d = data?.data ?? data ?? {}
  const council = d.council || 'unavailable'
  const symbol = d.symbol || '—'
  const exchange = d.exchange || '—'
  const consensusVerdict = d.consensus_verdict || 'UNAVAILABLE'
  const hasConsensusScore = d.consensus_score != null && Number.isFinite(Number(d.consensus_score))
  const consensusScore = hasConsensusScore ? Number(d.consensus_score) : null
  const signals = d.signals || []

  const icon = COUNCIL_ICONS[council.toLowerCase()] || '🏛️'
  const isBuy = consensusVerdict.includes('BUY')
  const isSell = consensusVerdict.includes('SELL')

  return (
    <div className="bg-elevated/90 border border-border/80 rounded-2xl p-5 max-w-2xl w-full space-y-4 font-mono shadow-md backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber/15 border border-amber/30 flex items-center justify-center text-xl">
            {icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase font-bold tracking-widest text-muted font-ui">
                Council Research Summary
              </span>
              <InfoBadge
                title={`${council.toUpperCase()} Council Ensemble`}
                content="Research perspectives are shown with their available evidence. A council result never stages or submits an order."
                metricKey="persona_councils"
              />
            </div>
            <h2 className="text-base font-bold font-ui text-text flex items-center gap-2">
              <span>{symbol} ({exchange})</span>
              <span className="text-xs px-2 py-0.5 rounded-md bg-surface text-amber border border-border/60 font-mono">
                {council.toUpperCase()}
              </span>
            </h2>
          </div>
        </div>

        {/* Consensus Verdict Badge */}
        <div className="text-right">
          <span className={`px-3 py-1 rounded-xl text-xs uppercase tracking-wider block ${VERDICT_STYLES[consensusVerdict] || VERDICT_STYLES.HOLD}`}>
            {consensusVerdict}
          </span>
          <span className="text-[10px] text-muted block mt-1 font-mono">
            Conviction: <strong className="text-text">{hasConsensusScore ? `${consensusScore}/100` : 'Unavailable'}</strong>
          </span>
        </div>
      </div>

      {/* Conviction Progress Bar */}
      {hasConsensusScore && <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs font-ui">
          <span className="text-muted">Council Consensus Strength</span>
          <span className={`font-bold ${isBuy ? 'text-emerald-400' : isSell ? 'text-rose-400' : 'text-amber'}`}>
            {consensusScore >= 75 ? '🔥 High Conviction' : consensusScore >= 55 ? '⚖️ Moderate Conviction' : '⚠️ Neutral / Inconclusive'}
          </span>
        </div>
        <div className="h-2 w-full bg-surface rounded-full overflow-hidden border border-border/60">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              isBuy ? 'bg-gradient-to-r from-emerald-500 to-teal-400' : isSell ? 'bg-gradient-to-r from-rose-500 to-amber-500' : 'bg-gradient-to-r from-amber-500 to-amber-300'
            }`}
            style={{ width: `${Math.max(5, Math.min(100, consensusScore))}%` }}
          />
        </div>
      </div>}

      {/* Polled Specialist Members Grid */}
      <div className="space-y-2">
        <span className="text-[11px] uppercase font-bold text-muted font-ui tracking-wider flex items-center justify-between">
          <span>Specialist Members Polled ({signals.length})</span>
          <span className="text-[10px] text-amber font-normal">Click member to expand rationale</span>
        </span>

        <div className="grid grid-cols-1 gap-2">
          {signals.map((sig) => {
            const pid = sig.persona?.toLowerCase() || ''
            const name = PERSONA_NAMES[pid] || sig.persona || 'Analyst'
            const isMemberBuy = sig.verdict?.includes('BUY')
            const isMemberSell = sig.verdict?.includes('SELL')
            const isExpanded = expandedPersona === pid

            const memberColor = isMemberBuy
              ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
              : isMemberSell
              ? 'text-rose-400 bg-rose-500/10 border-rose-500/30'
              : 'text-amber bg-amber/10 border-amber/30'

            return (
              <div
                key={pid}
                className="rounded-xl border border-border/70 bg-surface/80 p-3 space-y-2 transition-all hover:border-amber/40"
              >
                <div
                  className="flex items-center justify-between cursor-pointer"
                  onClick={() => setExpandedPersona(isExpanded ? null : pid)}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm">🧠</span>
                    <span className="font-bold text-xs text-text font-ui">{name}</span>
                    <span className="text-[10px] text-muted">({sig.confidence}% conf)</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-lg text-[10px] uppercase font-bold border ${memberColor}`}>
                      {sig.verdict}
                    </span>
                    <span className="text-muted text-xs">{isExpanded ? '▲' : '▼'}</span>
                  </div>
                </div>

                {/* Primary Rationale Snippet */}
                {sig.rationale && sig.rationale.length > 0 && !isExpanded && (
                  <p className="text-[11px] text-muted font-ui truncate pl-6">
                    • {sig.rationale[0]}
                  </p>
                )}

                {/* Expanded Checklist & Metrics */}
                {isExpanded && (
                  <div className="pl-6 pt-2 border-t border-border/40 space-y-2 font-ui text-xs animate-fade-slide">
                    <div className="space-y-1">
                      <span className="text-[10px] uppercase font-bold text-muted block">Checklist Criteria:</span>
                      {sig.rationale?.map((r, i) => (
                        <div key={i} className="flex items-start gap-1.5 text-text/90 text-[11px]">
                          <span className="text-amber">•</span>
                          <span>{r}</span>
                        </div>
                      ))}
                    </div>

                    {sig.key_metrics && Object.keys(sig.key_metrics).length > 0 && (
                      <div className="pt-1 flex flex-wrap gap-1.5">
                        {Object.entries(sig.key_metrics).map(([k, v]) => (
                          <span key={k} className="px-2 py-0.5 rounded-md bg-elevated border border-border/50 text-[10px] text-muted font-mono">
                            {k}: <strong className="text-text">{v}</strong>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Action Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3">
        <div className="flex items-center gap-2">
          <button
            disabled={symbol === '—'}
            onClick={() => sendDraft(`structure ${symbol}`)}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface/80 border border-border/60 text-xs text-text font-ui transition-all cursor-pointer"
          >
            🏛️ SMC Structure
          </button>
          <button
            disabled={symbol === '—'}
            onClick={() => sendDraft(`multibagger ${symbol}`)}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface/80 border border-border/60 text-xs text-text font-ui transition-all cursor-pointer"
          >
            💎 Stage 2 VCP
          </button>
          <button
            disabled={symbol === '—'}
            onClick={() => sendDraft(`forensic ${symbol}`)}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface/80 border border-border/60 text-xs text-text font-ui transition-all cursor-pointer"
          >
            🛡️ Forensic Audit
          </button>
        </div>
      </div>
    </div>
  )
}
