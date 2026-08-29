import { useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const QUADRANT_CONFIG = {
  LEADING:   { label: 'Leading',   bg: 'bg-green/10',  border: 'border-green/30',  text: 'text-green',  icon: '🚀', desc: 'Outperforming & Accelerating' },
  WEAKENING: { label: 'Weakening', bg: 'bg-amber/10',  border: 'border-amber/30',  text: 'text-amber',  icon: '⚠️', desc: 'Outperforming but Decelerating' },
  LAGGING:   { label: 'Lagging',   bg: 'bg-red/10',    border: 'border-red/30',    text: 'text-red',    icon: '📉', desc: 'Underperforming & Decelerating' },
  IMPROVING: { label: 'Improving', bg: 'bg-blue/10',   border: 'border-blue/30',   text: 'text-blue',   icon: '🔄', desc: 'Underperforming but Gaining Velocity' },
}

export default function RRGCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const sectors = d.sectors || []
  const stockAlign = d.stock_alignment

  const [lookupSym, setLookupSym] = useState('')
  const [activeStockAlign, setActiveStockAlign] = useState(stockAlign)
  const [searching, setSearching] = useState(false)
  const { call } = useAPI()
  const openInspector = useInspectorStore((s) => s.openInspector)

  const handleLookup = async (e) => {
    e.preventDefault()
    if (!lookupSym.trim()) return
    setSearching(true)
    try {
      const res = await call('/skills/rrg', { symbol: lookupSym.trim().toUpperCase() })
      const resData = res?.data ?? res
      if (resData?.stock_alignment) {
        setActiveStockAlign(resData.stock_alignment)
      }
    } catch (err) {
      console.error('RRG lookup error:', err)
    } finally {
      setSearching(false)
    }
  }

  const handleOpenSector = (secName) => {
    window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: secName } }))
  }

  // Count sectors per quadrant
  const counts = {
    LEADING: sectors.filter(s => s.quadrant === 'LEADING').length,
    IMPROVING: sectors.filter(s => s.quadrant === 'IMPROVING').length,
    WEAKENING: sectors.filter(s => s.quadrant === 'WEAKENING').length,
    LAGGING: sectors.filter(s => s.quadrant === 'LAGGING').length,
  }

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">🌐</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Relative Strength</p>
              <InfoBadge
                title="Relative Rotation Graph (RRG)"
                content="JdK 2D Relative Strength Trend vs Velocity Model comparing 10 major NSE sectors to NIFTY 50."
                metricKey="rrg_sector_matrix"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Relative Rotation Graphs (RRG)</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs bg-panel px-2.5 py-1 rounded border border-border text-muted font-ui">
            Benchmark: <strong className="text-text">NIFTY 50</strong>
          </span>
        </div>
      </div>

      {/* Quadrant Overview Tabs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {Object.entries(QUADRANT_CONFIG).map(([quadKey, cfg]) => (
          <Tooltip
            key={quadKey}
            title={`${cfg.label} Quadrant`}
            content={cfg.desc}
            metricKey="rrg_sector_matrix"
          >
            <div
              onClick={() => openInspector('rrg_sector_matrix')}
              className={`p-2.5 rounded-lg border ${cfg.bg} ${cfg.border} flex flex-col justify-between cursor-pointer hover:scale-102 transition-transform w-full text-left`}
            >
              <div className="flex items-center justify-between text-xs">
                <span className={`font-semibold font-ui ${cfg.text}`}>{cfg.icon} {cfg.label}</span>
                <span className={`font-bold font-mono text-sm ${cfg.text}`}>{counts[quadKey] ?? 0}</span>
              </div>
              <p className="text-[10px] text-muted font-ui mt-1 line-clamp-1">{cfg.desc}</p>
            </div>
          </Tooltip>
        ))}
      </div>

      {/* Interactive Stock Tailwind Search */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-semibold text-text font-ui">🎯 Stock Sector Tailwind Alignment</span>
            <InfoBadge
              title="Sector Tailwind Score"
              content="A 0-100 score quantifying whether a stock benefits from institutional sector momentum or faces rotational headwinds."
              metricKey="rrg_sector_matrix"
            />
          </div>
          <form onSubmit={handleLookup} className="flex items-center gap-1.5">
            <input
              type="text"
              placeholder="e.g. INFY, TATASTEEL"
              value={lookupSym}
              onChange={(e) => setLookupSym(e.target.value.toUpperCase())}
              className="bg-elevated border border-border px-2 py-1 rounded text-xs text-text font-mono w-36 focus:outline-none focus:border-amber"
            />
            <button
              type="submit"
              disabled={searching}
              className="bg-amber/10 hover:bg-amber/20 text-amber border border-amber/30 px-2.5 py-1 rounded text-xs font-ui font-semibold transition-colors cursor-pointer"
            >
              {searching ? '…' : 'Check'}
            </button>
          </form>
        </div>

        {activeStockAlign && (
          <Tooltip
            title={`${activeStockAlign.symbol} Sector Tailwind Breakdown`}
            content={`Belongs to ${activeStockAlign.sector} (${activeStockAlign.quadrant}). Tailwind score: ${activeStockAlign.tailwind_score}/100.`}
            metricKey="rrg_sector_matrix"
          >
            <div
              onClick={() => handleOpenSector(activeStockAlign.sector)}
              className="w-full flex items-center justify-between bg-elevated/70 hover:bg-elevated border border-border/40 hover:border-amber/40 p-2.5 rounded text-xs font-ui cursor-pointer transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="font-bold text-text font-mono text-sm">{activeStockAlign.symbol}</span>
                <span className="text-muted text-[11px]">Sector:</span>
                <span className="bg-panel px-1.5 py-0.5 rounded text-amber font-mono font-semibold">{activeStockAlign.sector}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded font-bold text-[11px] ${
                  QUADRANT_CONFIG[activeStockAlign.quadrant]?.bg ?? 'bg-panel'
                } ${QUADRANT_CONFIG[activeStockAlign.quadrant]?.text ?? 'text-text'}`}>
                  {activeStockAlign.quadrant}
                </span>
                <span className="text-muted text-[11px]">Tailwind Score:</span>
                <span className="font-bold text-green font-mono">{activeStockAlign.tailwind_score}/100</span>
                <span className="text-[10px] text-amber ml-1">Click to drill down →</span>
              </div>
            </div>
          </Tooltip>
        )}
      </div>

      {/* 2D Quadrant Scatter Matrix Canvas */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between text-xs text-muted font-ui">
          <div className="flex items-center gap-1.5">
            <span>RRG 2D Momentum Matrix</span>
            <InfoBadge
              title="2D RRG Coordinate System"
              content="X-Axis: RS-Ratio (Trend > 100 is outperforming). Y-Axis: RS-Momentum (Velocity > 100 is accelerating)."
              metricKey="rrg_sector_matrix"
            />
          </div>
          <span className="text-[10px] text-amber font-semibold">Click any sector node or row to see top stocks & contributing factors</span>
        </div>

        <div className="relative h-48 bg-elevated/80 border border-border/50 rounded-lg overflow-hidden flex items-center justify-center">
          {/* Axis lines */}
          <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-border/80" />
          <div className="absolute inset-y-0 left-1/2 border-l border-dashed border-border/80" />

          {/* Quadrant labels */}
          <span className="absolute top-2 right-2 text-[10px] font-bold text-green/60 font-ui">LEADING (Top Right)</span>
          <span className="absolute bottom-2 right-2 text-[10px] font-bold text-amber/60 font-ui">WEAKENING (Btm Right)</span>
          <span className="absolute bottom-2 left-2 text-[10px] font-bold text-red/60 font-ui">LAGGING (Btm Left)</span>
          <span className="absolute top-2 left-2 text-[10px] font-bold text-blue/60 font-ui">IMPROVING (Top Left)</span>

          {/* Plotted Sector Nodes */}
          {sectors.map((sec) => {
            const xPercent = Math.max(8, Math.min(92, ((sec.rs_ratio - 85) / 30) * 100))
            const yPercent = Math.max(8, Math.min(92, 100 - ((sec.rs_momentum - 85) / 30) * 100))
            const qCfg = QUADRANT_CONFIG[sec.quadrant] || QUADRANT_CONFIG.LEADING

            return (
              <Tooltip
                key={sec.sector}
                title={`NIFTY ${sec.sector} · Click to Drilldown`}
                content={`Ratio: ${sec.rs_ratio.toFixed(1)} | Momentum: ${sec.rs_momentum.toFixed(1)} | Quadrant: ${sec.quadrant}. Click to view top contributing stocks.`}
                metricKey="rrg_sector_matrix"
              >
                <div
                  style={{ left: `${xPercent}%`, top: `${yPercent}%` }}
                  onClick={() => handleOpenSector(sec.sector)}
                  className="absolute -translate-x-1/2 -translate-y-1/2 group cursor-pointer"
                >
                  <div className={`w-4 h-4 rounded-full ${qCfg.bg} border-2 ${qCfg.border} flex items-center justify-center shadow-xs transition-transform group-hover:scale-135`}>
                    <div className={`w-1.5 h-1.5 rounded-full ${qCfg.text === 'text-green' ? 'bg-green' : qCfg.text === 'text-red' ? 'bg-red' : qCfg.text === 'text-blue' ? 'bg-blue' : 'bg-amber'}`} />
                  </div>
                  <span className="absolute left-4.5 top-0 -translate-y-1/2 text-[9px] font-bold font-mono bg-panel/95 px-1.5 py-0.5 rounded border border-border/60 text-text whitespace-nowrap shadow-xs pointer-events-none group-hover:border-amber group-hover:text-amber">
                    {sec.sector}
                  </span>
                </div>
              </Tooltip>
            )
          })}
        </div>
      </div>

      {/* Sector Details Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-ui text-left">
          <thead>
            <tr className="border-b border-border/60 text-[10px] uppercase text-muted tracking-wider">
              <th className="pb-1.5 font-medium">Sector</th>
              <th className="pb-1.5 font-medium text-right">RS-Ratio</th>
              <th className="pb-1.5 font-medium text-right">RS-Mom</th>
              <th className="pb-1.5 font-medium text-right">1D Chg</th>
              <th className="pb-1.5 font-medium text-right">Quadrant</th>
              <th className="pb-1.5 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {sectors.map((s) => {
              const qCfg = QUADRANT_CONFIG[s.quadrant] || QUADRANT_CONFIG.LEADING
              const chgColor = s.day_change_pct >= 0 ? 'text-green' : 'text-red'
              return (
                <tr
                  key={s.sector}
                  onClick={() => handleOpenSector(s.sector)}
                  className="hover:bg-elevated/70 transition-colors cursor-pointer group"
                  title="Click to view top stocks and contributing factors in this sector"
                >
                  <td className="py-2 font-semibold text-text font-mono flex items-center gap-1.5 group-hover:text-amber">
                    <span className="text-amber text-xs">◆</span>
                    <span>{s.sector}</span>
                  </td>
                  <td className="py-2 text-right font-mono text-text">{Number(s.rs_ratio).toFixed(1)}</td>
                  <td className="py-2 text-right font-mono text-text">{Number(s.rs_momentum).toFixed(1)}</td>
                  <td className={`py-2 text-right font-mono font-semibold ${chgColor}`}>
                    {s.day_change_pct >= 0 ? '+' : ''}{Number(s.day_change_pct).toFixed(2)}%
                  </td>
                  <td className="py-2 text-right">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${qCfg.bg} ${qCfg.text}`}>
                      {s.quadrant}
                    </span>
                  </td>
                  <td className="py-2 text-right font-mono text-amber text-[11px] group-hover:underline">
                    Stocks →
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

