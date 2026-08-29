import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const REGIME_CONFIG = {
  BULLISH: { bg: 'bg-green/10', border: 'border-green/30', text: 'text-green', icon: '🐂', label: 'Bullish Structure (HH/HL)' },
  BEARISH: { bg: 'bg-red/10', border: 'border-red/30', text: 'text-red', icon: '🐻', label: 'Bearish Structure (LH/LL)' },
  RANGING: { bg: 'bg-amber/10', border: 'border-amber/30', text: 'text-amber', icon: '⚖️', label: 'Consolidation / Range' },
}

const SETUP_BADGES = {
  'BREAKOUT_EXPANSION':     { label: '🚀 Breakout Expansion', color: 'bg-green text-surface' },
  'PULLBACK_RETEST':        { label: '🎯 Pullback to Demand OB', color: 'bg-blue/15 text-blue border border-blue/30' },
  'BOTTOM_FISHING_SPRING':  { label: '🎣 Bottom Fishing (Wyckoff Spring)', color: 'bg-green/15 text-green border border-green/30' },
  'TOP_FISHING_UTAD':       { label: '🏔️ Top Fishing (Wyckoff UTAD)', color: 'bg-red/15 text-red border border-red/30' },
  'VCP_CONTRACTION':        { label: '⚡ VCP Volatility Contraction', color: 'bg-amber/15 text-amber border border-amber/30' },
  'BREAKDOWN_EXPANSION':    { label: '📉 Breakdown Expansion', color: 'bg-red text-surface' },
  'CONSOLIDATION':          { label: '🔄 Range Consolidation', color: 'bg-panel text-muted border border-border' },
}

export default function MarketStructureCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const openInspector = useInspectorStore((s) => s.openInspector)

  const regimeCfg = REGIME_CONFIG[d.regime] || REGIME_CONFIG.RANGING
  const setupCfg = SETUP_BADGES[d.setup_type] || SETUP_BADGES.CONSOLIDATION
  const demands = d.active_demand_zones || []
  const supplies = d.active_supply_zones || []
  const fvgs = d.fair_value_gaps || []
  const sweeps = d.liquidity_sweeps || []

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">🏛️</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Smart Money Concepts (SMC)</p>
              <InfoBadge
                title="Institutional Market Structure"
                content="Identifies structural regimes, Order Blocks, Fair Value Gaps, and Market Structure Shifts (CHoCH)."
                metricKey="market_structure_smc"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Market Structure & Price Action</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs bg-panel border border-border px-2.5 py-1 rounded text-amber font-mono font-bold">
            {d.symbol} • ₹{d.ltp?.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Structural Regime & Setup Classifier Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <Tooltip
          title={`${d.regime} Structure Regime`}
          content={`Score: ${d.structure_score >= 0 ? '+' : ''}${d.structure_score}/100. Based on confirmed fractal swing point sequence.`}
          metricKey="market_structure_smc"
        >
          <div
            onClick={() => openInspector('market_structure_smc', { symbol: d.symbol })}
            className={`p-3 rounded-lg border ${regimeCfg.bg} ${regimeCfg.border} flex items-center justify-between cursor-pointer hover:scale-101 transition-transform`}
          >
            <div>
              <span className="text-[10px] text-muted uppercase font-ui">Market Regime</span>
              <p className={`text-sm font-bold font-ui flex items-center gap-1.5 ${regimeCfg.text}`}>
                <span>{regimeCfg.icon}</span>
                <span>{regimeCfg.label}</span>
              </p>
            </div>
            <span className={`text-base font-mono font-bold ${regimeCfg.text}`}>
              {d.structure_score >= 0 ? `+${d.structure_score}` : d.structure_score}
            </span>
          </div>
        </Tooltip>

        <Tooltip
          title="Active Technical Setup"
          content={`Confidence: ${d.setup_confidence}%. Differentiates breakout expansion, pullback to demand, bottom fishing, etc.`}
          metricKey="market_structure_smc"
        >
          <div
            onClick={() => openInspector('market_structure_smc', { symbol: d.symbol })}
            className="p-3 rounded-lg border border-border/60 bg-panel flex items-center justify-between cursor-pointer hover:scale-101 transition-transform"
          >
            <div>
              <span className="text-[10px] text-muted uppercase font-ui">Setup Archetype</span>
              <p className="text-xs font-bold font-ui text-text mt-0.5">
                {setupCfg.label}
              </p>
            </div>
            <span className="text-xs font-mono font-semibold text-green bg-green/10 px-2 py-0.5 rounded border border-green/30">
              {d.setup_confidence}% Conf
            </span>
          </div>
        </Tooltip>
      </div>

      {/* Signals & Institutional Transitions (CHoCH / BOS / Sweeps) */}
      {(d.choch_detected || d.bos_detected || sweeps.length > 0) && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-text font-ui">⚡ Structural Events & Transitions</span>
            <InfoBadge
              title="CHoCH & BOS Significance"
              content="CHoCH signals early trend reversal (bottom/top fishing). BOS signals high-probability trend continuation."
              metricKey="market_structure_smc"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {d.choch_detected && (
              <span className="bg-amber/15 text-amber border border-amber/30 text-xs px-2 py-1 rounded font-bold">
                ⚠️ {d.choch_type} (Structural Shift)
              </span>
            )}
            {d.bos_detected && (
              <span className="bg-green/15 text-green border border-green/30 text-xs px-2 py-1 rounded font-bold">
                🚀 {d.bos_type} (Continuation Breakout)
              </span>
            )}
            {sweeps.map((sw, idx) => (
              <span key={idx} className="bg-blue/15 text-blue border border-blue/30 text-xs px-2 py-1 rounded font-bold">
                🎯 {sw.type === 'BULLISH_SWEEP' ? 'Bullish Liquidity Sweep (Spring)' : 'Bearish Upthrust (UTAD)'}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* SMC Demand & Supply Order Blocks */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {/* Demand Zones */}
        <div className="bg-panel border border-border/60 rounded-lg p-2.5 space-y-1.5">
          <div className="flex items-center justify-between text-xs font-ui">
            <span className="text-green font-semibold flex items-center gap-1">
              <span>🛡️</span> Demand Order Blocks ({demands.length})
            </span>
          </div>
          {demands.length === 0 ? (
            <p className="text-[11px] text-muted font-ui">No unmitigated demand blocks.</p>
          ) : (
            demands.map((ob, idx) => (
              <div key={idx} className="bg-elevated/80 border border-green/30 p-1.5 rounded flex items-center justify-between text-xs font-mono">
                <span className="text-green font-bold">₹{ob.bottom.toFixed(1)} – ₹{ob.top.toFixed(1)}</span>
                <span className="text-muted text-[10px]">{ob.formed_date}</span>
              </div>
            ))
          )}
        </div>

        {/* Supply Zones */}
        <div className="bg-panel border border-border/60 rounded-lg p-2.5 space-y-1.5">
          <div className="flex items-center justify-between text-xs font-ui">
            <span className="text-red font-semibold flex items-center gap-1">
              <span>⚔️</span> Supply Order Blocks ({supplies.length})
            </span>
          </div>
          {supplies.length === 0 ? (
            <p className="text-[11px] text-muted font-ui">No unmitigated supply blocks.</p>
          ) : (
            supplies.map((ob, idx) => (
              <div key={idx} className="bg-elevated/80 border border-red/30 p-1.5 rounded flex items-center justify-between text-xs font-mono">
                <span className="text-red font-bold">₹{ob.bottom.toFixed(1)} – ₹{ob.top.toFixed(1)}</span>
                <span className="text-muted text-[10px]">{ob.formed_date}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Actionable Trade Levels */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between text-xs font-ui">
          <span className="text-muted uppercase text-[10px]">Actionable Trade Plan</span>
          <span className="text-green font-mono font-bold">1 : {d.risk_reward_ratio} R:R</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-elevated/70 p-2 rounded text-xs font-ui">
          <div>
            <span className="text-[10px] text-muted uppercase">Support</span>
            <p className="font-semibold text-text font-mono">₹{d.nearest_support?.toLocaleString()}</p>
          </div>
          <div>
            <span className="text-[10px] text-muted uppercase">Invalidation SL</span>
            <p className="font-semibold text-red font-mono">₹{d.invalidation_level?.toLocaleString()}</p>
          </div>
          <div>
            <span className="text-[10px] text-muted uppercase">Target 1 (2R)</span>
            <p className="font-semibold text-green font-mono">₹{d.target_1?.toLocaleString()}</p>
          </div>
          <div>
            <span className="text-[10px] text-muted uppercase">Target 2 (3.5R)</span>
            <p className="font-semibold text-green font-mono">₹{d.target_2?.toLocaleString()}</p>
          </div>
        </div>

        <p className="text-xs text-text font-ui leading-relaxed bg-elevated/40 p-2 rounded border border-border/40">
          💡 {d.actionable_trade_idea}
        </p>
      </div>
    </div>
  )
}
