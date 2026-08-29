import { useState, useMemo } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const QUADRANT_CONFIG = {
  LEADING:   { label: 'Leading',   bg: 'bg-emerald-500/10',  border: 'border-emerald-500/30',  text: 'text-emerald-400',  glow: 'rgba(16, 185, 129, 0.15)', icon: '🚀', desc: 'Outperforming & Accelerating' },
  IMPROVING: { label: 'Improving', bg: 'bg-cyan-500/10',     border: 'border-cyan-500/30',     text: 'text-cyan-400',     glow: 'rgba(6, 182, 212, 0.15)',   icon: '🔄', desc: 'Underperforming but Gaining Velocity' },
  WEAKENING: { label: 'Weakening', bg: 'bg-amber-500/10',    border: 'border-amber-500/30',    text: 'text-amber-400',    glow: 'rgba(245, 158, 11, 0.15)',  icon: '⚠️', desc: 'Outperforming but Decelerating' },
  LAGGING:   { label: 'Lagging',   bg: 'bg-rose-500/10',     border: 'border-rose-500/30',     text: 'text-rose-400',     glow: 'rgba(244, 63, 94, 0.15)',   icon: '📉', desc: 'Underperforming & Decelerating' },
}

export default function RRGCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const sectors = d.sectors || []
  const stockAlign = d.stock_alignment

  const [selectedQuad, setSelectedQuad] = useState('ALL')
  const [showTrails, setShowTrails] = useState(true)
  const [hoveredSector, setHoveredSector] = useState(null)
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
  const counts = useMemo(() => ({
    ALL: sectors.length,
    LEADING: sectors.filter(s => s.quadrant === 'LEADING').length,
    IMPROVING: sectors.filter(s => s.quadrant === 'IMPROVING').length,
    WEAKENING: sectors.filter(s => s.quadrant === 'WEAKENING').length,
    LAGGING: sectors.filter(s => s.quadrant === 'LAGGING').length,
  }), [sectors])

  const [sortCol, setSortCol] = useState('rs_ratio')
  const [sortDir, setSortDir] = useState('desc')
  const [sectorSearch, setSectorSearch] = useState('')

  const handleHeaderSort = (col) => {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir('desc')
    }
  }

  const sortedAndFilteredSectors = useMemo(() => {
    let result = sectors
    if (selectedQuad !== 'ALL') {
      result = result.filter((s) => s.quadrant === selectedQuad)
    }
    if (sectorSearch.trim()) {
      const q = sectorSearch.trim().toUpperCase()
      result = result.filter(
        (s) =>
          s.sector?.toUpperCase().includes(q) ||
          s.top_stocks?.some((st) => st.toUpperCase().includes(q))
      )
    }
    return [...result].sort((a, b) => {
      let valA = a[sortCol]
      let valB = b[sortCol]
      if (typeof valA === 'string') {
        return sortDir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA)
      }
      valA = Number(valA) || 0
      valB = Number(valB) || 0
      return sortDir === 'asc' ? valA - valB : valB - valA
    })
  }, [sectors, selectedQuad, sectorSearch, sortCol, sortDir])

  // Coordinate normalizer for 2D plane (domain: 85 to 115)
  const getCoords = (ratio, mom) => {
    const x = Math.max(5, Math.min(95, ((ratio - 90) / 20) * 100))
    const y = Math.max(5, Math.min(95, 100 - ((mom - 90) / 20) * 100))
    return { x, y }
  }

  return (
    <div className="bg-elevated border border-border/80 rounded-2xl p-5 max-w-3xl w-full space-y-4 font-mono shadow-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/40 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-amber/15 border border-amber/30 flex items-center justify-center text-lg shadow-xs">
            🌐
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui font-semibold">Institutional Relative Strength</p>
              <InfoBadge
                title="Relative Rotation Graph (RRG)"
                content="JdK 2D Relative Strength Trend (RS-Ratio) vs Velocity (RS-Momentum) Model tracking 10 major NSE sectors vs NIFTY 50."
                metricKey="rrg_sector_matrix"
              />
            </div>
            <h2 className="text-text text-base font-bold font-ui flex items-center gap-2">
              <span>Relative Rotation Graphs (RRG)</span>
              <span className="text-[10px] font-mono font-normal px-2 py-0.5 rounded-full bg-surface border border-border text-muted">
                15m Dynamic Cycle
              </span>
            </h2>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTrails(!showTrails)}
            className={`px-2.5 py-1 rounded-lg text-xs font-ui font-medium border transition-all cursor-pointer flex items-center gap-1.5 ${
              showTrails
                ? 'bg-accent/20 border-accent/40 text-accent font-semibold'
                : 'bg-surface border-border text-muted hover:text-text'
            }`}
          >
            <span>⮑</span> {showTrails ? 'Trails Active' : 'Show Trails'}
          </button>
          <span className="text-xs bg-panel px-2.5 py-1 rounded-lg border border-border text-muted font-ui">
            Benchmark: <strong className="text-text">NIFTY 50</strong>
          </span>
        </div>
      </div>

      {/* Quadrant Overview Tabs with Filter Functionality */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        {Object.entries(QUADRANT_CONFIG).map(([quadKey, cfg]) => {
          const isSelected = selectedQuad === quadKey
          return (
            <div
              key={quadKey}
              onClick={() => setSelectedQuad(isSelected ? 'ALL' : quadKey)}
              className={`p-3 rounded-xl border ${cfg.bg} ${cfg.border} flex flex-col justify-between cursor-pointer transition-all ${
                isSelected ? 'ring-2 ring-amber shadow-sm scale-102' : 'hover:scale-101'
              }`}
            >
              <div className="flex items-center justify-between text-xs">
                <span className={`font-bold font-ui flex items-center gap-1 ${cfg.text}`}>
                  <span>{cfg.icon}</span> {cfg.label}
                </span>
                <span className={`font-bold font-mono text-sm px-2 py-0.5 rounded-full bg-surface/80 border border-border/60 ${cfg.text}`}>
                  {counts[quadKey] ?? 0}
                </span>
              </div>
              <p className="text-[10px] text-muted font-ui mt-1.5 leading-snug line-clamp-1">{cfg.desc}</p>
            </div>
          )
        })}
      </div>

      {/* Interactive Stock Tailwind Search */}
      <div className="bg-panel border border-border/60 rounded-xl p-3.5 space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-text font-ui">🎯 Stock Sector Tailwind Alignment</span>
            <InfoBadge
              title="Sector Tailwind Score"
              content="A 0-100 score quantifying whether a stock benefits from institutional sector momentum or faces rotational headwinds."
              metricKey="rrg_sector_matrix"
            />
          </div>
          <form onSubmit={handleLookup} className="flex items-center gap-1.5">
            <input
              type="text"
              placeholder="e.g. INFY, SBIN, M&M"
              value={lookupSym}
              onChange={(e) => setLookupSym(e.target.value.toUpperCase())}
              className="bg-elevated border border-border px-2.5 py-1.5 rounded-lg text-xs text-text font-mono w-40 focus:outline-none focus:border-amber focus:ring-1 focus:ring-amber/40"
            />
            <button
              type="submit"
              disabled={searching}
              className="bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 px-3 py-1.5 rounded-lg text-xs font-ui font-bold transition-colors cursor-pointer"
            >
              {searching ? '…' : 'Check Alignment'}
            </button>
          </form>
        </div>

        {activeStockAlign && (
          <div
            onClick={() => handleOpenSector(activeStockAlign.sector)}
            className="w-full flex flex-wrap items-center justify-between gap-2 bg-elevated hover:bg-elevated/80 border border-border/60 hover:border-amber/40 p-3 rounded-xl text-xs font-ui cursor-pointer transition-all shadow-xs"
          >
            <div className="flex items-center gap-2">
              <span className="font-bold text-text font-mono text-sm">{activeStockAlign.symbol}</span>
              <span className="text-muted text-[11px]">Parent Sector:</span>
              <span className="bg-surface px-2 py-0.5 rounded-lg text-amber font-mono font-bold border border-border/40">
                NIFTY {activeStockAlign.sector}
              </span>
            </div>
            <div className="flex items-center gap-2.5">
              <span className={`px-2.5 py-0.5 rounded-lg font-bold text-[11px] border ${
                QUADRANT_CONFIG[activeStockAlign.quadrant]?.bg ?? 'bg-panel'
              } ${QUADRANT_CONFIG[activeStockAlign.quadrant]?.border ?? 'border-border'} ${
                QUADRANT_CONFIG[activeStockAlign.quadrant]?.text ?? 'text-text'
              }`}>
                {activeStockAlign.quadrant}
              </span>
              <span className="text-muted text-[11px]">Tailwind Score:</span>
              <span className="font-bold text-emerald-400 font-mono text-sm">{activeStockAlign.tailwind_score}/100</span>
              <span className="text-[11px] text-amber font-semibold ml-1">Drill down →</span>
            </div>
          </div>
        )}
      </div>

      {/* 2D Interactive Scatter Canvas with SVG Trails */}
      <div className="bg-panel border border-border/70 rounded-xl p-3.5 space-y-2">
        <div className="flex items-center justify-between text-xs text-muted font-ui">
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-text">RRG 2D Momentum Matrix</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-surface border border-border text-muted">
              X: RS-Ratio (Trend) · Y: RS-Momentum (Velocity)
            </span>
          </div>
          <span className="text-[10px] text-amber font-semibold">Hover to inspect · Click any sector node to view top constituents</span>
        </div>

        <div className="relative h-64 bg-surface/90 border border-border/70 rounded-xl overflow-hidden shadow-inner flex items-center justify-center select-none">
          {/* Subtle Quadrant Color Glows */}
          <div className="absolute top-0 right-0 w-1/2 h-1/2 bg-emerald-500/5 border-l border-b border-dashed border-border/60" />
          <div className="absolute bottom-0 right-0 w-1/2 h-1/2 bg-amber-500/5 border-l border-dashed border-border/60" />
          <div className="absolute bottom-0 left-0 w-1/2 h-1/2 bg-rose-500/5 border-dashed border-border/60" />
          <div className="absolute top-0 left-0 w-1/2 h-1/2 bg-cyan-500/5 border-b border-dashed border-border/60" />

          {/* Quadrant Labels */}
          <span className="absolute top-2.5 right-3 text-[10px] font-bold text-emerald-400/80 font-ui flex items-center gap-1">
            <span>🚀</span> LEADING (Top Right)
          </span>
          <span className="absolute bottom-2.5 right-3 text-[10px] font-bold text-amber-400/80 font-ui flex items-center gap-1">
            <span>⚠️</span> WEAKENING (Btm Right)
          </span>
          <span className="absolute bottom-2.5 left-3 text-[10px] font-bold text-rose-400/80 font-ui flex items-center gap-1">
            <span>📉</span> LAGGING (Btm Left)
          </span>
          <span className="absolute top-2.5 left-3 text-[10px] font-bold text-cyan-400/80 font-ui flex items-center gap-1">
            <span>🔄</span> IMPROVING (Top Left)
          </span>

          {/* Center Benchmark Crosshair Badge */}
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 px-2 py-0.5 rounded-full bg-elevated/90 border border-border/80 text-[9px] font-mono text-muted shadow-xs z-10">
            NIFTY 50 (100, 100)
          </div>

          {/* SVG Historical Rotation Trail Vectors */}
          {showTrails && (
            <svg className="absolute inset-0 w-full h-full pointer-events-none z-15">
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#f59e0b" opacity="0.8" />
                </marker>
              </defs>
              {sectors.map((sec) => {
                const trail = sec.trail || []
                if (trail.length < 2) return null
                const pointsSvg = trail.map(pt => {
                  const { x, y } = getCoords(pt.rs_ratio, pt.rs_momentum)
                  return `${x}%,${y}%`
                }).join(' ')

                const isHovered = hoveredSector === sec.sector
                return (
                  <polyline
                    key={`trail-${sec.sector}`}
                    points={pointsSvg}
                    fill="none"
                    stroke={isHovered ? '#f59e0b' : 'rgba(255, 255, 255, 0.25)'}
                    strokeWidth={isHovered ? 2.5 : 1.2}
                    strokeDasharray={isHovered ? 'none' : '3 3'}
                    markerEnd="url(#arrow)"
                    className="transition-all duration-300"
                  />
                )
              })}
            </svg>
          )}

          {/* Plotted Sector Nodes */}
          {sectors.map((sec) => {
            const { x, y } = getCoords(sec.rs_ratio, sec.rs_momentum)
            const qCfg = QUADRANT_CONFIG[sec.quadrant] || QUADRANT_CONFIG.LEADING
            const isHovered = hoveredSector === sec.sector
            const isDimmed = selectedQuad !== 'ALL' && sec.quadrant !== selectedQuad

            return (
              <div
                key={sec.sector}
                style={{ left: `${x}%`, top: `${y}%` }}
                onMouseEnter={() => setHoveredSector(sec.sector)}
                onMouseLeave={() => setHoveredSector(null)}
                onClick={() => handleOpenSector(sec.sector)}
                className={`absolute -translate-x-1/2 -translate-y-1/2 group cursor-pointer z-20 transition-all duration-200 ${
                  isDimmed ? 'opacity-25' : 'opacity-100'
                }`}
              >
                {/* Node Pill */}
                <div className={`relative flex items-center gap-1 px-2 py-1 rounded-xl border shadow-sm transition-all duration-200 ${
                  isHovered
                    ? 'bg-amber text-black border-amber scale-115 ring-4 ring-amber/30 z-30 font-bold'
                    : `${qCfg.bg} ${qCfg.border} text-text hover:scale-108`
                }`}>
                  <span className="text-xs">{qCfg.icon}</span>
                  <span className="text-[10px] font-bold font-mono">{sec.sector}</span>
                  <span className={`text-[9px] font-mono ${isHovered ? 'text-black' : qCfg.text}`}>
                    {Number(sec.rs_ratio).toFixed(0)}
                  </span>
                </div>

                {/* Rich Hover Popover Card */}
                {isHovered && (
                  <div className="absolute left-1/2 -translate-x-1/2 bottom-8 w-56 p-2.5 bg-elevated/95 border border-border/80 backdrop-blur-md rounded-xl shadow-xl text-left z-40 space-y-1.5 pointer-events-none animate-in fade-in zoom-in-95">
                    <div className="flex items-center justify-between border-b border-border/50 pb-1">
                      <span className="font-bold text-text text-xs font-mono">NIFTY {sec.sector}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${qCfg.bg} ${qCfg.text}`}>
                        {sec.quadrant}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-1 text-[10px] font-mono">
                      <div>
                        <span className="text-muted block">RS-Ratio:</span>
                        <span className="font-bold text-text">{Number(sec.rs_ratio).toFixed(2)}</span>
                      </div>
                      <div>
                        <span className="text-muted block">RS-Momentum:</span>
                        <span className="font-bold text-text">{Number(sec.rs_momentum).toFixed(2)}</span>
                      </div>
                    </div>
                    {sec.top_stocks && sec.top_stocks.length > 0 && (
                      <div className="text-[10px] pt-1 border-t border-border/40">
                        <span className="text-muted block">Key Constituents:</span>
                        <span className="text-amber font-mono font-semibold truncate block">
                          {sec.top_stocks.slice(0, 3).join(', ')}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Sector Details Table Header & Search */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
        <span className="text-xs font-bold font-mono text-muted uppercase tracking-wider">
          Sector Breakdown ({sortedAndFilteredSectors.length})
        </span>
        <div className="relative">
          <input
            type="text"
            placeholder="Filter sector or stock..."
            value={sectorSearch}
            onChange={(e) => setSectorSearch(e.target.value)}
            className="bg-surface border border-border/60 rounded-lg px-2.5 py-1 text-xs text-text placeholder:text-muted/60 focus:outline-none focus:border-amber/60 font-mono w-44"
          />
          {sectorSearch && (
            <button
              onClick={() => setSectorSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-text text-xs"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Sector Details Table with Top Constituents */}
      <div className="overflow-x-auto rounded-xl border border-border/60">
        <table className="w-full text-xs font-ui text-left">
          <thead className="bg-surface/90">
            <tr className="border-b border-border/60 text-[10px] uppercase text-muted tracking-wider select-none">
              <th
                onClick={() => handleHeaderSort('sector')}
                className="py-2 px-3 font-semibold cursor-pointer hover:text-amber"
              >
                Sector {sortCol === 'sector' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              <th
                onClick={() => handleHeaderSort('rs_ratio')}
                className="py-2 px-2 font-semibold text-right cursor-pointer hover:text-amber"
              >
                RS-Ratio {sortCol === 'rs_ratio' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              <th
                onClick={() => handleHeaderSort('rs_momentum')}
                className="py-2 px-2 font-semibold text-right cursor-pointer hover:text-amber"
              >
                RS-Mom {sortCol === 'rs_momentum' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              <th
                onClick={() => handleHeaderSort('day_change_pct')}
                className="py-2 px-2 font-semibold text-right cursor-pointer hover:text-amber"
              >
                1D Chg {sortCol === 'day_change_pct' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              <th className="py-2 px-2 font-semibold text-center">Quadrant</th>
              <th className="py-2 px-3 font-semibold">Top Constituents</th>
              <th className="py-2 px-3 font-semibold text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30 bg-panel/50">
            {sortedAndFilteredSectors.map((s) => {
              const qCfg = QUADRANT_CONFIG[s.quadrant] || QUADRANT_CONFIG.LEADING
              const chgColor = s.day_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'
              const isHovered = hoveredSector === s.sector

              return (
                <tr
                  key={s.sector}
                  onMouseEnter={() => setHoveredSector(s.sector)}
                  onMouseLeave={() => setHoveredSector(null)}
                  onClick={() => handleOpenSector(s.sector)}
                  className={`transition-colors cursor-pointer group ${
                    isHovered ? 'bg-amber/10' : 'hover:bg-elevated/70'
                  }`}
                  title="Click to view full sector constituents and catalysts"
                >
                  <td className="py-2 px-3 font-bold text-text font-mono flex items-center gap-1.5 group-hover:text-amber">
                    <span className="text-amber text-xs">◆</span>
                    <span>{s.sector}</span>
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-text">{Number(s.rs_ratio).toFixed(1)}</td>
                  <td className="py-2 px-2 text-right font-mono text-text">{Number(s.rs_momentum).toFixed(1)}</td>
                  <td className={`py-2 px-2 text-right font-mono font-bold ${chgColor}`}>
                    {s.day_change_pct >= 0 ? '+' : ''}{Number(s.day_change_pct).toFixed(2)}%
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${qCfg.bg} ${qCfg.border} ${qCfg.text}`}>
                      {s.quadrant}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1 flex-wrap">
                      {(s.top_stocks || []).slice(0, 3).map((stk) => (
                        <span key={stk} className="text-[10px] px-1.5 py-0.2 rounded bg-surface border border-border/50 font-mono text-muted">
                          {stk}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="py-2 px-3 text-right font-mono text-amber text-[11px] font-semibold group-hover:underline">
                    Drilldown →
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
