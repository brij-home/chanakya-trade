import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const STAGE_CONFIG = {
  'STAGE_1_BASE':         { label: 'Stage 1: Basing Area', color: 'bg-blue/15 text-blue border border-blue/30', desc: 'Accumulation base forming along flat 200 SMA' },
  'STAGE_2_MARKUP':       { label: '🚀 Stage 2: Markup (Superperformer)', color: 'bg-green text-surface font-bold', desc: 'Sustained institutional uptrend above rising 50/200 SMA' },
  'STAGE_3_DISTRIBUTION': { label: '⚠️ Stage 3: Top / Distribution', color: 'bg-amber/15 text-amber border border-amber/30', desc: 'Choppy topping action near multi-month highs' },
  'STAGE_4_MARKDOWN':     { label: '📉 Stage 4: Decline / Markdown', color: 'bg-red text-surface font-bold', desc: 'Downtrend below declining 50/200 SMA (AVOID)' },
}

export default function MultibaggerCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const openInspector = useInspectorStore((s) => s.openInspector)

  const stageCfg = STAGE_CONFIG[d.weinstein_stage] || STAGE_CONFIG['STAGE_1_BASE']
  const criteria = d.criteria_breakdown || []
  const contractions = d.vcp_contractions || []

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">💎</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Positional Superperformer Discovery</p>
              <InfoBadge
                title="Multibagger & Trend Template Model"
                content="Combines Mark Minervini 8-point Trend Template, Stan Weinstein Stage 2 Breakout, and VCP Volatility Contraction."
                metricKey="minervini_trend_template"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Multibagger Potential Screener</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs bg-panel border border-border px-2.5 py-1 rounded text-amber font-mono font-bold">
            {d.symbol} • ₹{d.ltp?.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Multibagger Score & Stage 2 Gauge */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <Tooltip
          title="Multibagger Potential Score"
          content="0-100 quantitative composite of Trend Template, Stage 2 status, VCP contraction, and sector tailwind."
          metricKey="minervini_trend_template"
        >
          <div
            onClick={() => openInspector('minervini_trend_template', { symbol: d.symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 p-3 rounded-lg flex items-center justify-between cursor-pointer transition-colors"
          >
            <div>
              <span className="text-[10px] text-muted uppercase font-ui">Multibagger Score</span>
              <p className="text-xl font-bold font-mono text-green">
                {d.multibagger_score}/100
              </p>
            </div>
            <span className="text-xs font-ui font-semibold bg-green/10 text-green border border-green/30 px-2 py-1 rounded">
              {d.category}
            </span>
          </div>
        </Tooltip>

        <Tooltip
          title="Stan Weinstein Stage"
          content={stageCfg.desc}
          metricKey="weinstein_stage_analysis"
        >
          <div
            onClick={() => openInspector('weinstein_stage_analysis', { symbol: d.symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 p-3 rounded-lg flex items-center justify-between cursor-pointer transition-colors"
          >
            <div>
              <span className="text-[10px] text-muted uppercase font-ui">Weinstein Stage</span>
              <p className="text-xs font-bold font-ui text-text mt-0.5">
                {stageCfg.label}
              </p>
            </div>
            <span className="text-xs font-mono font-bold text-amber">
              {d.stage_confidence}% Conf
            </span>
          </div>
        </Tooltip>
      </div>

      {/* Minervini 8-Point Trend Template Radar */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between text-xs font-ui">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-text">Minervini Trend Template</span>
            <span className="bg-green/10 text-green border border-green/30 text-[10px] px-1.5 py-0.5 rounded font-bold">
              {d.trend_template_passed}/8 Rules Passed
            </span>
          </div>
          <span className="text-muted text-[10px]">Superperformers: $\ge 6/8$</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs font-ui">
          {criteria.map((c, idx) => (
            <div
              key={idx}
              className={`p-2 rounded border flex items-center justify-between ${
                c.passed ? 'bg-green/10 border-green/30 text-text' : 'bg-elevated/40 border-border/40 text-muted'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className={c.passed ? 'text-green font-bold' : 'text-muted'}>
                  {c.passed ? '✓' : '✗'}
                </span>
                <span className="text-[11px] font-medium">{c.name}</span>
              </div>
              <span className="font-mono text-[10px] font-semibold">{c.current_value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* VCP Volatility Contraction Pattern */}
      {d.vcp_detected && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between text-xs font-ui">
            <span className="font-semibold text-text flex items-center gap-1">
              <span>⚡</span> Volatility Contraction Pattern (VCP) Active
            </span>
            <span className="text-amber font-mono font-bold">Pivot: ₹{d.vcp_pivot_price}</span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono">
            {contractions.map((c, idx) => (
              <div key={idx} className="bg-elevated p-2 rounded border border-border/50">
                <span className="text-[10px] text-muted uppercase font-ui">Wave #{c.number}</span>
                <p className="text-sm font-bold text-amber">-{c.depth_pct}%</p>
                <span className="text-[10px] text-muted">{c.bars_duration} bars</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Suggested Entry Strategy */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-1.5">
        <span className="text-[10px] text-muted uppercase font-ui">Positional Entry & Multibagger Playbook</span>
        <p className="text-xs text-text font-ui leading-relaxed bg-elevated/60 p-2.5 rounded border border-border/40">
          🎯 {d.suggested_entry_strategy}
        </p>
      </div>
    </div>
  )
}
