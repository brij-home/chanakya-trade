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
  const openInspector = useInspectorStore((s) => s.openInspector)
  const [activeTab, setActiveTab] = useState('ALL') // 'ALL' | 'SHORT' | 'MID' | 'LONG'

  if (!data) return null
  const d = data?.data ?? data ?? {}

  const stageCfg = STAGE_CONFIG[d.weinstein_stage] || STAGE_CONFIG['STAGE_1_BASE']
  const criteria = d.criteria_breakdown || []
  const contractions = d.vcp_contractions || []
  const ticket = d.execution_ticket || {}
  const stDetails = d.short_term_details || {}
  const mtDetails = d.mid_term_details || {}
  const ltDetails = d.long_term_details || {}

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-xl">💎</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Discovery Engine</p>
              <InfoBadge
                title="3-Horizon Multibagger Discovery"
                content="Evaluates Short-Term (VCP/RVOL), Mid-Term (Stage 2/CAN SLIM), and Long-Term (SMILE/ROCE) superperformer potential."
                metricKey="minervini_trend_template"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Multibagger Potential & Alpha Radar</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs bg-panel border border-border px-2.5 py-1 rounded text-amber font-mono font-bold">
            {d.symbol} • ₹{d.ltp?.toLocaleString()}
          </span>
        </div>
      </div>

      {/* 3-Horizon Horizon Cards Gauge */}
      <div className="grid grid-cols-3 gap-2">
        {/* Short Term */}
        <button
          onClick={() => setActiveTab('SHORT')}
          className={`p-2.5 rounded-lg border text-left transition-all ${
            activeTab === 'SHORT'
              ? 'bg-amber/15 border-amber shadow-sm'
              : 'bg-panel hover:bg-elevated/70 border-border/60'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted uppercase font-ui font-medium">⚡ Short (1–4W)</span>
            <span className="text-[10px] font-bold font-mono text-amber">{d.short_term_score ?? 50}/100</span>
          </div>
          <p className="text-xs font-bold font-ui text-text mt-1 truncate">
            {d.short_term_verdict || '⚪ DEVELOPING'}
          </p>
        </button>

        {/* Mid Term */}
        <button
          onClick={() => setActiveTab('MID')}
          className={`p-2.5 rounded-lg border text-left transition-all ${
            activeTab === 'MID'
              ? 'bg-green/15 border-green shadow-sm'
              : 'bg-panel hover:bg-elevated/70 border-border/60'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted uppercase font-ui font-medium">🚀 Mid (1–6M)</span>
            <span className="text-[10px] font-bold font-mono text-green">{d.mid_term_score ?? 50}/100</span>
          </div>
          <p className="text-xs font-bold font-ui text-text mt-1 truncate">
            {d.mid_term_verdict || '⚪ CONSOLIDATING'}
          </p>
        </button>

        {/* Long Term */}
        <button
          onClick={() => setActiveTab('LONG')}
          className={`p-2.5 rounded-lg border text-left transition-all ${
            activeTab === 'LONG'
              ? 'bg-blue/15 border-blue shadow-sm'
              : 'bg-panel hover:bg-elevated/70 border-border/60'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted uppercase font-ui font-medium">👑 Long (1–5Y)</span>
            <span className="text-[10px] font-bold font-mono text-blue">{d.long_term_score ?? 50}/100</span>
          </div>
          <p className="text-xs font-bold font-ui text-text mt-1 truncate">
            {d.long_term_verdict || '👑 COMPOUNDER'}
          </p>
        </button>
      </div>

      {/* Main Composite Score & Stage Overview */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <Tooltip
          title="Composite Multibagger Score"
          content="Weighted 3-horizon score combining VCP tightness, Weinstein Stage 2 markup, and forensic quality."
          metricKey="minervini_trend_template"
        >
          <div
            onClick={() => openInspector('minervini_trend_template', { symbol: d.symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 p-3 rounded-lg flex items-center justify-between cursor-pointer transition-colors"
          >
            <div>
              <span className="text-[10px] text-muted uppercase font-ui">Overall Multibagger Score</span>
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

      {/* Dynamic Horizon Content View */}
      {activeTab === 'SHORT' && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between text-xs font-ui">
            <span className="font-semibold text-text">⚡ Short-Term Alpha Catalyst Metrics</span>
            <span className="text-amber font-mono text-[11px]">RVOL: {stDetails.rvol_20d ?? 1.0}x</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">RVOL 20D</span>
              <p className="text-sm font-bold text-amber">{stDetails.rvol_20d ?? 1.0}x</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">3D Momentum</span>
              <p className="text-sm font-bold text-green">{stDetails.momentum_3d_pct ?? 0.0}%</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">VCP Pivot Dist</span>
              <p className="text-sm font-bold text-text">
                {stDetails.vcp_pivot_distance_pct !== null ? `${stDetails.vcp_pivot_distance_pct}%` : 'N/A'}
              </p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">Sector Tailwind</span>
              <p className="text-sm font-bold text-green">{d.sector_tailwind_score}/100</p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'LONG' && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between text-xs font-ui">
            <span className="font-semibold text-text">👑 Long-Term Wealth & Fundamental Quality</span>
            <span className={d.forensic_safe ? 'text-green font-bold text-[11px]' : 'text-red font-bold text-[11px]'}>
              {d.forensic_safe ? '✓ Forensic Safe' : '⚠️ Forensic Warning'}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">ROCE %</span>
              <p className="text-sm font-bold text-green">{ltDetails.roce_pct ?? 20.0}%</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">Debt / Equity</span>
              <p className="text-sm font-bold text-text">{ltDetails.debt_equity ?? 0.3}x</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">SMILE Score</span>
              <p className="text-sm font-bold text-amber">{ltDetails.smile_framework_score ?? 80}/100</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">CFO / PAT</span>
              <p className="text-sm font-bold text-green">{ltDetails.cfo_pat_ratio ?? 0.9}x</p>
            </div>
          </div>
        </div>
      )}

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

      {/* Actionable Trade Execution Ticket */}
      {ticket && ticket.entry_price && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2 font-ui">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className="bg-green text-surface text-[10px] font-bold px-2 py-0.5 rounded">
                {ticket.action || 'LONG (BUY)'}
              </span>
              <span className="font-semibold text-text">Institutional Trade Ticket</span>
            </div>
            <span className="text-muted text-[10px] font-mono">{ticket.recommended_horizon}</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">Entry Zone</span>
              <p className="text-sm font-bold text-text">₹{ticket.entry_price}</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">Stop Loss</span>
              <p className="text-sm font-bold text-red">₹{ticket.stop_loss}</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">Target 1 (2R)</span>
              <p className="text-sm font-bold text-green">₹{ticket.target_1}</p>
            </div>
            <div className="bg-elevated p-2 rounded border border-border/40">
              <span className="text-[10px] text-muted uppercase font-ui">Target 2 (3.5R)</span>
              <p className="text-sm font-bold text-amber">₹{ticket.target_2}</p>
            </div>
          </div>

          <p className="text-[11px] text-muted leading-relaxed bg-elevated/40 p-2 rounded border border-border/30">
            📌 <span className="font-medium text-text">Trailing Rule:</span> {ticket.trailing_stop_rule}
          </p>
        </div>
      )}

      {/* Suggested Entry Strategy */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-1.5 font-ui">
        <span className="text-[10px] text-muted uppercase font-ui font-medium">Multibagger Playbook & Catalyst Notes</span>
        <p className="text-xs text-text leading-relaxed bg-elevated/60 p-2.5 rounded border border-border/40">
          🎯 {d.suggested_entry_strategy}
        </p>
      </div>
    </div>
  )
}
