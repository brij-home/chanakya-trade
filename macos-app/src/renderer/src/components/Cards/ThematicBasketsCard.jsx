import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const BASKET_TABS = [
  { id: 'mayer_100_baggers', name: '💎 100-Baggers', desc: 'Christopher Mayer small/midcap high-ROCE compounders' },
  { id: 'lynch_garp_fast_growers', name: '🚀 Lynch GARP', desc: 'Peter Lynch Growth at Reasonable Price (PEG < 1.0)' },
  { id: 'jhunjhunwala_operating_leverage', name: '🐘 Jhunjhunwala Capex', desc: 'High operating leverage & domestic Indian capex winners' },
  { id: 'canslim_high_momentum', name: '📈 CAN SLIM', desc: 'William O\'Neil leaders breaking out to 52W highs' },
  { id: 'order_book_powerhouses', name: '🏗️ Order-Book Titans', desc: 'Order-book to market-cap >= 1.5x multi-year revenue visibility' },
  { id: 'value_migration_leaders', name: '🛡️ Value Migration', desc: 'Capturing structural profit pools from legacy players' },
]

export default function ThematicBasketsCard({ data }) {
  const openInspector = useInspectorStore((s) => s.openInspector)
  const [selectedBasket, setSelectedBasket] = useState('mayer_100_baggers')

  if (!data) return null
  const d = data?.data ?? data ?? {}
  const candidates = d.top_candidates || []

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-3xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-xl">{d.icon || '👑'}</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Strategy Stacks</p>
              <InfoBadge
                title="Super-Investor Thematic Baskets"
                content="Curated investment stacks modeled after Christopher Mayer, Peter Lynch, Rakesh Jhunjhunwala, and William O'Neil."
                metricKey="minervini_trend_template"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">{d.basket_name || 'Super-Investor Thematic Baskets'}</p>
          </div>
        </div>

        <div className="flex items-center gap-2 font-ui">
          <span className="text-xs bg-panel border border-border px-2.5 py-1 rounded text-green font-mono font-bold">
            Target: {d.target_cagr || '25% – 35% CAGR'}
          </span>
        </div>
      </div>

      {/* Philosophy Banner */}
      <div className="bg-panel border border-border/60 p-3 rounded-lg font-ui space-y-1">
        <span className="text-[10px] text-muted uppercase font-medium">Core Strategy Philosophy</span>
        <p className="text-xs text-text leading-relaxed font-semibold">
          {d.investor_philosophy}
        </p>
        <div className="flex items-center gap-4 text-[10px] text-muted pt-1">
          <span>⏳ Holding Horizon: <strong className="text-text">{d.min_holding_horizon}</strong></span>
          <span>🔍 Scanned Universe: <strong className="text-text">{d.total_scanned} Tickers</strong></span>
          <span>⭐ Avg Basket Score: <strong className="text-green font-mono">{d.average_basket_score}/100</strong></span>
        </div>
      </div>

      {/* Ranked Candidate List */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-ui">
          <span className="font-semibold text-text">Top Ranked Basket Candidates</span>
          <span className="text-muted text-[10px]">Sorted by 3-Axis Magic Trend</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-ui">
          {candidates.map((c, idx) => (
            <div
              key={idx}
              onClick={() => openInspector('minervini_trend_template', { symbol: c.symbol })}
              className="bg-panel hover:bg-elevated/80 border border-border/60 p-3 rounded-lg cursor-pointer transition-all space-y-1.5"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-bold font-mono text-amber">#{idx + 1} {c.symbol}</span>
                  <span className="text-[10px] font-mono text-muted">₹{c.ltp}</span>
                </div>
                <span className="text-xs font-bold font-mono text-green bg-green/10 px-1.5 py-0.5 rounded border border-green/30">
                  {c.magic_trend_score}/100
                </span>
              </div>

              <div className="flex items-center justify-between text-[10px]">
                <span className="text-muted truncate">{c.grade}</span>
                <span className="text-text font-semibold">{c.verdict}</span>
              </div>

              <div className="grid grid-cols-3 gap-1 text-center text-[10px] font-mono pt-1 border-t border-border/30">
                <div className="bg-elevated/40 p-1 rounded">
                  <span className="text-muted block text-[9px]">X (Quality)</span>
                  <span className="font-bold text-blue">{c.x_quality_score}/35</span>
                </div>
                <div className="bg-elevated/40 p-1 rounded">
                  <span className="text-muted block text-[9px]">Y (Growth)</span>
                  <span className="font-bold text-green">{c.y_growth_score}/35</span>
                </div>
                <div className="bg-elevated/40 p-1 rounded">
                  <span className="text-muted block text-[9px]">Z (Timing)</span>
                  <span className="font-bold text-amber">{c.z_timing_score}/30</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
