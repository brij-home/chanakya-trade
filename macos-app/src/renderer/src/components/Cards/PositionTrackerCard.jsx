import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const HEALTH_CONFIG = {
  'HEALTHY_ACCELERATING':  { label: '🚀 Accelerating Gain', color: 'bg-green/15 text-green border border-green/30' },
  'HEALTHY_PULLBACK':      { label: '🔄 Healthy Pullback', color: 'bg-blue/15 text-blue border border-blue/30' },
  'MOMENTUM_STALLING':     { label: '⚠️ Momentum Stalling', color: 'bg-amber/15 text-amber border border-amber/30' },
  'STRUCTURAL_INVALIDATION': { label: '🛑 Structural Invalidation', color: 'bg-red text-surface font-bold' },
}

export default function PositionTrackerCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const openInspector = useInspectorStore((s) => s.openInspector)

  const healthCfg = HEALTH_CONFIG[d.health_status] || HEALTH_CONFIG['HEALTHY_ACCELERATING']
  const milestones = d.milestones || []
  const trailing = d.trailing_stops || {}
  const diagnostics = d.diagnostic_bullet_points || []

  const isProfit = d.current_pnl_pts >= 0

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">📡</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Active Position Monitor</p>
              <InfoBadge
                title="Trade Lifecycle & Trailing Stop Engine"
                content="Tracks real-time R-multiple payoff, 2R breakeven shift, and computes Chandelier ATR & Structure trailing stops."
                metricKey="chandelier_trailing_sl"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Position Lifecycle & Dynamic Trailing SL</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs bg-panel border border-border px-2.5 py-1 rounded text-amber font-mono font-bold">
            {d.symbol}
          </span>
        </div>
      </div>

      {/* R-Multiple Payoff & Live PnL Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-panel border border-border/60 p-3 rounded-lg text-xs font-ui">
        <div>
          <span className="text-[10px] text-muted uppercase">Entry Price</span>
          <p className="text-sm font-bold font-mono text-text">₹{d.entry_price?.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-[10px] text-muted uppercase">Initial Stop-Loss</span>
          <p className="text-sm font-bold font-mono text-red">₹{d.initial_stop_loss?.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-[10px] text-muted uppercase">Current LTP</span>
          <p className="text-sm font-bold font-mono text-text">₹{d.ltp?.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-[10px] text-muted uppercase">Live Payoff</span>
          <p className={`text-base font-bold font-mono ${isProfit ? 'text-green' : 'text-red'}`}>
            {isProfit ? '+' : ''}{d.current_r_multiple?.toFixed(2)}R ({isProfit ? '+' : ''}{d.current_pnl_pct?.toFixed(2)}%)
          </p>
        </div>
      </div>

      {/* Health Status & Dynamic Trailing Stop Recommendation */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <Tooltip
          title="Position Health Status"
          content={`Health Score: ${d.health_score}/100. Evaluates trend integrity and R-multiple progression.`}
          metricKey="chandelier_trailing_sl"
        >
          <div
            onClick={() => openInspector('chandelier_trailing_sl', { symbol: d.symbol })}
            className="p-3 rounded-lg border border-border/60 bg-panel flex items-center justify-between cursor-pointer"
          >
            <div>
              <span className="text-[10px] text-muted uppercase font-ui">Health Diagnosis</span>
              <p className="text-xs font-bold font-ui text-text mt-0.5">
                {healthCfg.label}
              </p>
            </div>
            <span className="text-xs font-mono font-bold text-green bg-green/10 px-2 py-0.5 rounded border border-green/30">
              {d.health_score}/100
            </span>
          </div>
        </Tooltip>

        <Tooltip
          title="Recommended Trailing Stop"
          content={`Method: ${trailing.stop_method}. Protects profits dynamically as trade progresses.`}
          metricKey="chandelier_trailing_sl"
        >
          <div
            onClick={() => openInspector('chandelier_trailing_sl', { symbol: d.symbol })}
            className="p-3 rounded-lg border border-amber/30 bg-amber/10 flex items-center justify-between cursor-pointer"
          >
            <div>
              <span className="text-[10px] text-amber uppercase font-ui font-semibold">Active Recommended Stop</span>
              <p className="text-sm font-bold font-mono text-amber mt-0.5">
                ₹{trailing.recommended_active_stop?.toLocaleString()} ({trailing.stop_method})
              </p>
            </div>
            <span className="text-xs font-ui font-semibold text-amber border border-amber/40 px-2 py-0.5 rounded">
              Trail
            </span>
          </div>
        </Tooltip>
      </div>

      {/* Trailing Stop Levels Comparison */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
        <span className="text-xs font-semibold text-text font-ui">🛡️ Dynamic Trailing Stop Levels</span>
        <div className="grid grid-cols-3 gap-2 text-xs font-mono">
          <div className="bg-elevated p-2 rounded border border-border/50">
            <span className="text-[10px] text-muted font-ui uppercase">Structure HL</span>
            <p className="text-sm font-bold text-text">₹{trailing.structure_stop?.toLocaleString()}</p>
            <span className="text-[10px] text-muted">Swing Low Floor</span>
          </div>
          <div className="bg-elevated p-2 rounded border border-border/50">
            <span className="text-[10px] text-muted font-ui uppercase">Chandelier ATR</span>
            <p className="text-sm font-bold text-text">₹{trailing.chandelier_stop?.toLocaleString()}</p>
            <span className="text-[10px] text-muted">High - 3.0*ATR</span>
          </div>
          <div className="bg-elevated p-2 rounded border border-border/50">
            <span className="text-[10px] text-muted font-ui uppercase">20-EMA Floor</span>
            <p className="text-sm font-bold text-text">₹{trailing.ema20_stop?.toLocaleString()}</p>
            <span className="text-[10px] text-muted">Daily Trend Filter</span>
          </div>
        </div>
      </div>

      {/* Multi-Tier Profit Milestones */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
        <span className="text-xs font-semibold text-text font-ui">🎯 Profit Booking & Breakeven Milestones</span>
        <div className="space-y-1.5">
          {milestones.map((m, idx) => (
            <div
              key={idx}
              className={`p-2 rounded border flex items-center justify-between text-xs ${
                m.reached ? 'bg-green/10 border-green/30 text-text' : 'bg-elevated/40 border-border/40 text-muted'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={m.reached ? 'text-green font-bold' : 'text-muted'}>
                  {m.reached ? '✓ Reached' : '⏳ Pending'}
                </span>
                <span className="font-semibold font-ui">{m.name}</span>
                <span className="font-mono text-[11px] text-amber font-bold">₹{m.target_price}</span>
              </div>
              <span className="text-[10px] font-ui text-muted">{m.action_required}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Diagnostic Action Bar */}
      {diagnostics.length > 0 && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-1.5 font-ui">
          <span className="text-[10px] text-muted uppercase font-semibold">Trade Auditor Advice</span>
          <ul className="text-xs text-text space-y-1">
            {diagnostics.map((dItem, idx) => (
              <li key={idx} className="flex items-start gap-1.5">
                <span className="text-amber font-bold">▶</span>
                <span>{dItem}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
