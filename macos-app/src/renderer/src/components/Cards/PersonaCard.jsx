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

const PERSONA_DETAILS = {
  minervini: { name: 'Mark Minervini', tag: 'SEPA & VCP Breakouts', icon: '🚀', book: 'Trade Like a Stock Market Wizard' },
  wyckoff: { name: 'Richard Wyckoff', tag: 'VSA & Accumulation Springs', icon: '📈', book: 'Studies in Tape Reading' },
  oneil: { name: "William O'Neil", tag: 'CAN SLIM Momentum Growth', icon: '⚡', book: 'How to Make Money in Stocks' },
  taleb: { name: 'Nassim Nicholas Taleb', tag: 'Antifragile Convexity & Tail Risk', icon: '🛡️', book: 'The Black Swan / Antifragile' },
  kedia: { name: 'Vijay Kedia', tag: 'SMILE Indian Multibaggers', icon: '💎', book: 'Smallcap 10x–50x Growth' },
  simons: { name: 'Jim Simons', tag: 'Statistical Arbitrage & Quant Edges', icon: '🧮', book: 'The Man Who Solved the Market' },
  smc: { name: 'Smart Money Concepts', tag: 'Liquidity Sweeps & Order Blocks', icon: '🎯', book: 'ICT Institutional Price Delivery' },
  buffett: { name: 'Warren Buffett', tag: 'Durable Moat & FCF Compounding', icon: '🏛️', book: 'Berkshire Hathaway Letters' },
  munger: { name: 'Charlie Munger', tag: 'Inversion & Multidisciplinary Models', icon: '🧠', book: 'Poor Charlie’s Almanack' },
  jhunjhunwala: { name: 'Rakesh Jhunjhunwala', tag: 'India Macro Scale & Bull Horizons', icon: '🐂', book: 'India Growth Supercycle' },
  lynch: { name: 'Peter Lynch', tag: 'GARP & Common Sense Demand', icon: '🛒', book: 'One Up On Wall Street' },
  soros: { name: 'George Soros', tag: 'Macro Reflexivity & Currency Flows', icon: '🌊', book: 'The Alchemy of Finance' },
  forensic: { name: 'Forensic Auditor', tag: 'Beneish M-Score & Governance Audit', icon: '🔍', book: 'Financial Shenanigans Detection' },
}

export default function PersonaCard({ data }) {
  const sendDraft = useChatStore((s) => s.sendDraft)
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const personaId = (d.persona || 'buffett').toLowerCase()
  const verdict = d.verdict || 'HOLD'
  const confidence = Number(d.confidence ?? 0)
  const rationale = d.rationale || []
  const keyMetrics = d.key_metrics || {}

  const meta = PERSONA_DETAILS[personaId] || {
    name: personaId.toUpperCase(),
    tag: 'Specialist Intelligence',
    icon: '🧠',
    book: '',
  }

  const isBuy = verdict.includes('BUY')
  const isSell = verdict.includes('SELL')

  return (
    <div className="bg-elevated/90 border border-border/80 rounded-2xl p-5 max-w-2xl w-full space-y-4 font-mono shadow-md backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-amber/15 border border-amber/30 flex items-center justify-center text-2xl">
            {meta.icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase font-bold tracking-widest text-muted font-ui">
                Specialist Market Persona
              </span>
              <InfoBadge
                title={`${meta.name} Framework`}
                content={`Evaluated through authentic investment principles: ${meta.tag}`}
                metricKey="persona_intelligence"
              />
            </div>
            <h2 className="text-base font-bold font-ui text-text flex items-center gap-2">
              <span>{meta.name}</span>
              <span className="text-[11px] px-2 py-0.5 rounded-md bg-surface text-amber border border-border/60 font-ui font-medium">
                {meta.tag}
              </span>
            </h2>
          </div>
        </div>

        {/* Verdict Badge */}
        <div className="text-right">
          <span className={`px-3 py-1 rounded-xl text-xs uppercase tracking-wider block ${VERDICT_STYLES[verdict] || VERDICT_STYLES.HOLD}`}>
            {verdict}
          </span>
          <span className="text-[10px] text-muted block mt-1 font-mono">
            Confidence: <strong className="text-text">{confidence}%</strong>
          </span>
        </div>
      </div>

      {/* Confidence Gauge */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs font-ui">
          <span className="text-muted">Analysis Conviction</span>
          <span className={`font-bold ${isBuy ? 'text-emerald-400' : isSell ? 'text-rose-400' : 'text-amber'}`}>
            {confidence >= 75 ? 'Strong Signal' : confidence >= 50 ? 'Moderate Signal' : 'Neutral / Cautious'}
          </span>
        </div>
        <div className="h-2 w-full bg-surface rounded-full overflow-hidden border border-border/60">
          <div
            className={`h-full rounded-full transition-all duration-700 ${
              isBuy ? 'bg-gradient-to-r from-emerald-500 to-teal-400' : isSell ? 'bg-gradient-to-r from-rose-500 to-amber-500' : 'bg-gradient-to-r from-amber-500 to-amber-300'
            }`}
            style={{ width: `${Math.max(5, Math.min(100, confidence))}%` }}
          />
        </div>
      </div>

      {/* Rationale Checklist */}
      <div className="space-y-2">
        <span className="text-[11px] uppercase font-bold text-muted font-ui tracking-wider block">
          Checklist Verification & Signals
        </span>
        <div className="space-y-1.5 bg-surface/70 border border-border/60 rounded-xl p-3">
          {rationale.map((r, i) => (
            <div key={i} className="flex items-start gap-2 text-xs font-ui text-text/90">
              <span className="text-amber font-bold shrink-0">•</span>
              <span className="leading-relaxed">{r}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Key Metric Checkpoints */}
      {keyMetrics && Object.keys(keyMetrics).length > 0 && (
        <div className="space-y-2">
          <span className="text-[11px] uppercase font-bold text-muted font-ui tracking-wider block">
            Evaluated Dimension Scores
          </span>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Object.entries(keyMetrics).map(([k, v]) => (
              <div key={k} className="p-2.5 rounded-xl bg-surface border border-border/70 flex items-center justify-between">
                <span className="text-xs text-muted font-ui truncate">{k}</span>
                <span className="text-xs font-mono font-bold text-text">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer Quick Actions */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => sendDraft(`council breakout NIFTY`)}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface/80 border border-border/60 text-xs text-text font-ui transition-all cursor-pointer"
          >
            🚀 Breakout Council
          </button>
          <button
            onClick={() => sendDraft(`council multibagger NIFTY`)}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface/80 border border-border/60 text-xs text-text font-ui transition-all cursor-pointer"
          >
            💎 Multibagger Council
          </button>
        </div>

        <span className="text-[10px] text-muted font-mono">
          {keyMetrics['Analysis Engine'] || 'Autonomous Agent'}
        </span>
      </div>
    </div>
  )
}
