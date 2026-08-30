import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const GRADE_CONFIG = {
  '👑 SUPER_COMPOUNDER': { color: 'bg-green text-black font-extrabold', border: 'border-green/40' },
  '🚀 HIGH_ALPHA':        { color: 'bg-amber/15 text-amber border border-amber/30 font-bold', border: 'border-amber/40' },
  '⚖️ BALANCED_GROWTH':   { color: 'bg-blue/15 text-blue border border-blue/30 font-bold', border: 'border-blue/40' },
  '⚠️ DEAD_MONEY':       { color: 'bg-red text-white font-extrabold', border: 'border-red/40' },
}

export default function MagicTrendCard({ data }) {
  const openInspector = useInspectorStore((s) => s.openInspector)
  if (!data) return null
  const d = data?.data ?? data ?? {}

  const gradeCfg = GRADE_CONFIG[d.grade] || GRADE_CONFIG['👑 SUPER_COMPOUNDER']
  const axes = d.axes || []
  const ticket = d.execution_ticket || {}

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-xl">⭐</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">3-Axis Super-Investor Engine</p>
              <InfoBadge
                title="3-Axis X-Y-Z Magic Trend Engine"
                content="Combines Axis X (Quality & Moat), Axis Y (Growth & Value Migration), and Axis Z (Timing & Valuation Asymmetry)."
                metricKey="minervini_trend_template"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Magic Trend Score & Twin Multiplier</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs bg-panel border border-border px-2.5 py-1 rounded text-amber font-mono font-bold">
            {d.symbol} • ₹{d.ltp?.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Main Score & Multiplier Highlight */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="bg-panel border border-border/60 p-3 rounded-lg flex items-center justify-between">
          <div>
            <span className="text-[10px] text-muted uppercase font-ui font-medium">Magic Trend Score</span>
            <p className="text-2xl font-bold font-mono text-green">
              {d.magic_trend_score}/100
            </p>
          </div>
          <div className="text-right">
            <span className={`text-xs font-ui px-2 py-1 rounded ${gradeCfg.color}`}>
              {d.grade}
            </span>
            <p className="text-[10px] text-muted font-ui mt-1">{d.verdict}</p>
          </div>
        </div>

        <div className="bg-panel border border-border/60 p-3 rounded-lg flex flex-col justify-between">
          <span className="text-[10px] text-muted uppercase font-ui font-medium">Dual-Engine Multiplier</span>
          <p className="text-xs text-text font-ui font-semibold leading-snug mt-1">
            🚀 {d.dual_engine_multiplier_potential}
          </p>
          <span className="text-[10px] text-amber font-mono mt-1">PEG: {d.peg_ratio ?? 1.0} • P/E: {d.pe_ratio ?? 25.0}x</span>
        </div>
      </div>

      {/* 3-Axis X, Y, Z Breakdown */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2.5">
        <div className="flex items-center justify-between text-xs font-ui">
          <span className="font-semibold text-text">3-Axis Quantitative Architecture</span>
          <span className="text-muted text-[10px]">Max 100 Pts</span>
        </div>

        <div className="space-y-2 font-ui">
          {/* Axis X: Quality */}
          <div className="bg-elevated/70 p-2.5 rounded border border-border/40 space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-blue">🏛️ Axis X: Quality & Moat (Buffett/Munger)</span>
              <span className="font-bold font-mono text-blue">{d.x_quality_score}/35 Pts</span>
            </div>
            <div className="w-full bg-surface h-1.5 rounded-full overflow-hidden">
              <div className="bg-blue h-full" style={{ width: `${(d.x_quality_score / 35) * 100}%` }} />
            </div>
            <p className="text-[10px] text-muted">ROCE: {d.roce_pct}% • Zero Pledge • Clean Accounting & High CFO Conversion</p>
          </div>

          {/* Axis Y: Growth */}
          <div className="bg-elevated/70 p-2.5 rounded border border-border/40 space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-green">🚀 Axis Y: Growth & Value Migration (Lynch/Mayer)</span>
              <span className="font-bold font-mono text-green">{d.y_growth_score}/35 Pts</span>
            </div>
            <div className="w-full bg-surface h-1.5 rounded-full overflow-hidden">
              <div className="bg-green h-full" style={{ width: `${(d.y_growth_score / 35) * 100}%` }} />
            </div>
            <p className="text-[10px] text-muted">Sales Growth: {d.sales_growth_3y}% CAGR • Reinvestment Rate & Operating Leverage</p>
          </div>

          {/* Axis Z: Timing */}
          <div className="bg-elevated/70 p-2.5 rounded border border-border/40 space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-amber">⚡ Axis Z: Timing & Market Structure (Minervini/Marks)</span>
              <span className="font-bold font-mono text-amber">{d.z_timing_score}/30 Pts</span>
            </div>
            <div className="w-full bg-surface h-1.5 rounded-full overflow-hidden">
              <div className="bg-amber h-full" style={{ width: `${(d.z_timing_score / 30) * 100}%` }} />
            </div>
            <p className="text-[10px] text-muted">Weinstein Stage: {d.weinstein_stage} • VCP Tightness • Asymmetric PEG Ratio</p>
          </div>
        </div>
      </div>

      {/* Trade Execution Ticket */}
      {ticket && ticket.entry_price && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2 font-ui">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className="bg-green text-black text-[10px] font-extrabold px-2 py-0.5 rounded">
                {ticket.action || 'LONG (BUY)'}
              </span>
              <span className="font-semibold text-text">Dynamic Trade Setup Ticket</span>
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

      {/* Why Pick / Why Avoid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-ui">
        <div className="bg-green/10 border border-green/30 p-2.5 rounded-lg space-y-1">
          <span className="text-[10px] text-green font-bold uppercase tracking-wider">✓ Super-Investor Thesis (Why Pick)</span>
          <p className="text-text leading-relaxed text-[11px]">{d.thesis_why_pick}</p>
        </div>
        <div className="bg-red/10 border border-red/30 p-2.5 rounded-lg space-y-1">
          <span className="text-[10px] text-red font-bold uppercase tracking-wider">✗ Risk Thresholds (When to Invalidate)</span>
          <p className="text-text leading-relaxed text-[11px]">{d.thesis_why_avoid}</p>
        </div>
      </div>
    </div>
  )
}
