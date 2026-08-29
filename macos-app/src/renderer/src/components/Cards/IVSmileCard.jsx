import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

const IV_FLOOR = 0.5

export default function IVSmileCard({ data, onOpenOrderTicket }) {
  const d = data?.data ?? data ?? {}
  const symbol = d.symbol ?? 'NIFTY'
  const expiry = d.expiry ?? '0DTE'
  const spot = Number(d.spot_price || 24250)
  const rows = (d.rows ?? []).slice().sort((a, b) => Number(a.strike) - Number(b.strike))
  const sendDraft = useChatStore((s) => s.sendDraft)

  const [selectedStrike, setSelectedStrike] = useState(null)
  const [activeTab, setActiveTab] = useState('CURVE') // CURVE vs TABLE

  function ivValid(v) {
    return Number(v ?? 0) >= IV_FLOOR
  }

  function fmtIV(v) {
    if (!ivValid(v)) return '—'
    return Number(v).toFixed(1) + '%'
  }

  // Find ATM: row with moneyness closest to 0 or strike closest to spot
  let atmIdx = -1
  if (rows.length > 0) {
    let minDiff = Infinity
    rows.forEach((r, i) => {
      const diff = Math.abs(Number(r.strike) - spot)
      if (diff < minDiff) {
        minDiff = diff
        atmIdx = i
      }
    })
  }

  const atmRow = atmIdx >= 0 ? rows[atmIdx] : null
  const atmPeIv = atmRow ? Number(atmRow.pe_iv ?? 0) : 14.5
  const atmCeIv = atmRow ? Number(atmRow.ce_iv ?? 0) : 13.8
  const atmStrike = atmRow ? Number(atmRow.strike) : Math.round(spot / 50) * 50

  // Calculate 25-Delta Skew / Put vs Call Skew
  const validRows = rows.filter((r) => ivValid(r.ce_iv) && ivValid(r.pe_iv))
  const avgCeIv = validRows.length > 0 ? validRows.reduce((a, b) => a + Number(b.ce_iv), 0) / validRows.length : 14
  const avgPeIv = validRows.length > 0 ? validRows.reduce((a, b) => a + Number(b.pe_iv), 0) / validRows.length : 17
  const netSkew = avgPeIv - avgCeIv

  let skewRegime = {
    title: 'STEEP PUT SKEW (DOWNSIDE HEDGE DEMAND)',
    color: 'text-amber-600 dark:text-amber',
    bg: 'bg-amber/15 dark:bg-amber/10',
    border: 'border-amber/40 dark:border-amber/30',
    icon: '🛡️',
    bias: 'Institutional hedging is bidding up OTM Puts relative to Calls. High put premium.',
    recommendation: 'Sell elevated Put Spreads (Bull Put Spread) or Buy cheap Call Spreads.',
  }

  if (netSkew < -1.0) {
    skewRegime = {
      title: 'CALL SKEW (UPSIDE EUPHORIA)',
      color: 'text-cyan-600 dark:text-cyan-400',
      bg: 'bg-cyan-500/15 dark:bg-cyan-500/10',
      border: 'border-cyan-500/40 dark:border-cyan-500/30',
      icon: '🚀',
      bias: 'Call IV exceeds Put IV due to aggressive upside chasing.',
      recommendation: 'Sell OTM Calls or deploy Bear Call Credit Spreads.',
    }
  } else if (Math.abs(netSkew) <= 1.0) {
    skewRegime = {
      title: 'SYMMETRIC SMILE (BALANCED VOLATILITY)',
      color: 'text-emerald-600 dark:text-emerald-400',
      bg: 'bg-emerald-500/15 dark:bg-emerald-500/10',
      border: 'border-emerald-500/40 dark:border-emerald-500/30',
      icon: '⚖️',
      bias: 'Symmetric implied volatility across upside and downside wings.',
      recommendation: 'Trade standard Iron Condors, Straddles, or directional breakout plays.',
    }
  }

  // Pre-calculate SVG Curve coordinates
  const displayRows = rows.length > 0 ? rows : [
    { strike: spot - 400, pe_iv: 19.5, ce_iv: 11.2 },
    { strike: spot - 200, pe_iv: 16.8, ce_iv: 12.4 },
    { strike: spot, pe_iv: 14.5, ce_iv: 13.8 },
    { strike: spot + 200, pe_iv: 13.2, ce_iv: 15.6 },
    { strike: spot + 400, pe_iv: 12.8, ce_iv: 18.2 },
  ]

  const allIvValues = displayRows.flatMap((r) => [Number(r.pe_iv || 0), Number(r.ce_iv || 0)]).filter((v) => v > 0)
  const minIV = allIvValues.length > 0 ? Math.max(5, Math.min(...allIvValues) - 2) : 10
  const maxIV = allIvValues.length > 0 ? Math.max(...allIvValues) + 2 : 25
  const ivRange = Math.max(1, maxIV - minIV)

  const width = 340
  const height = 130
  const paddingX = 25
  const paddingY = 20

  const pePoints = displayRows
    .map((r, i) => {
      const x = paddingX + (i / Math.max(1, displayRows.length - 1)) * (width - paddingX * 2)
      const y = height - paddingY - ((Number(r.pe_iv || minIV) - minIV) / ivRange) * (height - paddingY * 2)
      return `${x},${y}`
    })
    .join(' ')

  const cePoints = displayRows
    .map((r, i) => {
      const x = paddingX + (i / Math.max(1, displayRows.length - 1)) * (width - paddingX * 2)
      const y = height - paddingY - ((Number(r.ce_iv || minIV) - minIV) / ivRange) * (height - paddingY * 2)
      return `${x},${y}`
    })
    .join(' ')

  const activeInspectRow = selectedStrike !== null
    ? displayRows.find((r) => Number(r.strike) === selectedStrike) || atmRow
    : atmRow || displayRows[Math.floor(displayRows.length / 2)]

  return (
    <div className="bg-panel border border-border/90 rounded-2xl p-4 sm:p-5 max-w-2xl w-full space-y-4 shadow-xl backdrop-blur-md font-ui text-text">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-cyan-400 text-lg">📈</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold tracking-wide font-mono uppercase text-text">
                {symbol} VOLATILITY SMILE &amp; SKEW
              </h3>
              {expiry && (
                <span className="text-muted text-[10px] font-mono border border-border/80 bg-surface px-2 py-0.5 rounded">
                  {expiry}
                </span>
              )}
            </div>
            <p className="text-[11px] text-muted font-ui">
              Implied Volatility Curve, 25-Delta Skew &amp; Institutional Positioning
            </p>
          </div>
        </div>

        {/* View Toggle */}
        <div className="flex items-center gap-1 bg-surface border border-border/70 p-0.5 rounded-lg text-[10px] font-mono">
          <button
            onClick={() => setActiveTab('CURVE')}
            className={`px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'CURVE' ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
            }`}
          >
            Visual Curve
          </button>
          <button
            onClick={() => setActiveTab('TABLE')}
            className={`px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'TABLE' ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
            }`}
          >
            Strike Matrix
          </button>
        </div>
      </div>

      {/* Skew Diagnostic Banner */}
      <div className={`p-3 rounded-xl border ${skewRegime.bg} ${skewRegime.border} space-y-1.5`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span>{skewRegime.icon}</span>
            <span className={`text-xs font-bold font-mono tracking-wide ${skewRegime.color}`}>
              {skewRegime.title}
            </span>
          </div>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-surface/80 border border-border text-text">
            Net Skew (PE−CE): {netSkew >= 0 ? '+' : ''}{netSkew.toFixed(1)}%
          </span>
        </div>
        <p className="text-[11px] text-text/90 font-ui leading-relaxed">
          {skewRegime.bias}
        </p>
        <div className="text-[10px] font-mono text-muted flex items-center gap-1 pt-0.5">
          <span className="text-amber font-bold">💡 Trading Edge:</span>
          <span>{skewRegime.recommendation}</span>
        </div>
      </div>

      {/* Main Visual Dual-Line Smile Chart */}
      {activeTab === 'CURVE' ? (
        <div className="space-y-2">
          <div className="h-44 w-full relative bg-surface/80 rounded-xl border border-border/70 p-2 overflow-hidden flex items-center justify-center">
            <svg className="w-full h-full" viewBox={`0 0 ${width} ${height}`}>
              {/* Grid Lines */}
              <line x1="0" y1={paddingY} x2={width} y2={paddingY} stroke="rgba(255,255,255,0.05)" strokeDasharray="3" />
              <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="rgba(255,255,255,0.05)" strokeDasharray="3" />
              <line x1="0" y1={height - paddingY} x2={width} y2={height - paddingY} stroke="rgba(255,255,255,0.05)" strokeDasharray="3" />

              {/* Spot Reference Vertical Line */}
              <line x1={width / 2} y1="0" x2={width / 2} y2={height} stroke="#f43f5e" strokeWidth="1" strokeDasharray="3" opacity="0.7" />
              <text x={width / 2 + 4} y="14" fill="#f43f5e" fontSize="8" fontFamily="monospace" fontWeight="bold">
                Spot: {Math.round(spot)}
              </text>

              {/* Put IV Curve (Amber/Orange) */}
              <polyline
                fill="none"
                stroke="#f59e0b"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={pePoints}
              />

              {/* Call IV Curve (Cyan) */}
              <polyline
                fill="none"
                stroke="#06b6d4"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={cePoints}
              />

              {/* Strike Nodes */}
              {displayRows.map((r, i) => {
                const x = paddingX + (i / Math.max(1, displayRows.length - 1)) * (width - paddingX * 2)
                const yPe = height - paddingY - ((Number(r.pe_iv || minIV) - minIV) / ivRange) * (height - paddingY * 2)
                const yCe = height - paddingY - ((Number(r.ce_iv || minIV) - minIV) / ivRange) * (height - paddingY * 2)
                const isSelected = selectedStrike === Number(r.strike)
                const isAtm = i === atmIdx

                return (
                  <g key={r.strike} className="cursor-pointer" onClick={() => setSelectedStrike(Number(r.strike))}>
                    <circle cx={x} cy={yPe} r={isSelected ? 4.5 : 3} fill="#f59e0b" />
                    <circle cx={x} cy={yCe} r={isSelected ? 4.5 : 3} fill="#06b6d4" />
                    <text
                      x={x}
                      y={height - 4}
                      textAnchor="middle"
                      fill={isAtm ? '#f59e0b' : isSelected ? '#38bdf8' : '#888'}
                      fontSize="7.5"
                      fontFamily="monospace"
                      fontWeight={isAtm || isSelected ? 'bold' : 'normal'}
                    >
                      {Number(r.strike).toLocaleString('en-IN')}
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>

          {/* Curve Legend & Strike Quick Inspector */}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono bg-surface/60 p-2.5 rounded-xl border border-border/50">
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1.5 text-amber">
                <span className="w-2.5 h-1 bg-amber rounded-full inline-block" /> Put IV Curve
              </span>
              <span className="flex items-center gap-1.5 text-cyan-400">
                <span className="w-2.5 h-1 bg-cyan-400 rounded-full inline-block" /> Call IV Curve
              </span>
            </div>

            {activeInspectRow && (
              <div className="text-[11px] flex items-center gap-2">
                <span className="text-muted">Strike: <strong className="text-text">{Number(activeInspectRow.strike).toLocaleString('en-IN')}</strong></span>
                <span>PE IV: <strong className="text-amber">{fmtIV(activeInspectRow.pe_iv)}</strong></span>
                <span>CE IV: <strong className="text-cyan-400">{fmtIV(activeInspectRow.ce_iv)}</strong></span>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Detailed Strike Matrix Table */
        <div className="overflow-x-auto max-h-56 overflow-y-auto">
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr className="text-muted uppercase tracking-wider border-b border-border text-[10px]">
                <th className="text-left pb-2">Strike</th>
                <th className="text-right pb-2 pr-2">Call IV%</th>
                <th className="text-right pb-2 pr-2">Put IV%</th>
                <th className="text-right pb-2 pr-2">Skew (PE−CE)</th>
                <th className="text-right pb-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map((r, i) => {
                const ceIv = Number(r.ce_iv || 0)
                const peIv = Number(r.pe_iv || 0)
                const isAtm = i === atmIdx
                const skew = peIv - ceIv

                return (
                  <tr key={r.strike} className={`border-b border-border/40 hover:bg-surface/60 ${isAtm ? 'bg-amber/5' : ''}`}>
                    <td className={`py-1.5 font-bold ${isAtm ? 'text-amber' : 'text-text'}`}>
                      {Number(r.strike).toLocaleString('en-IN')} {isAtm && <span className="text-[9px] text-amber ml-1">ATM</span>}
                    </td>
                    <td className="py-1.5 text-right pr-2 text-cyan-400">{fmtIV(ceIv)}</td>
                    <td className="py-1.5 text-right pr-2 text-amber">{fmtIV(peIv)}</td>
                    <td className={`py-1.5 text-right pr-2 font-semibold ${skew > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {skew >= 0 ? '+' : ''}{skew.toFixed(1)}%
                    </td>
                    <td className="py-1.5 text-right">
                      <button
                        onClick={() => {
                          if (onOpenOrderTicket) {
                            onOpenOrderTicket({
                              symbol: `${symbol} ${r.strike} ${skew > 0 ? 'PE' : 'CE'}`,
                              price: spot,
                              quantity: 75,
                              segment: 'OPTIONS',
                            })
                          } else {
                            sendDraft(`analyze option strike ${r.strike} for ${symbol}`)
                          }
                        }}
                        className="text-[9px] px-2 py-0.5 rounded bg-surface border border-border hover:border-amber hover:text-amber cursor-pointer transition-all"
                      >
                        Trade
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 1-Click Skew Action Chips */}
      <div className="space-y-1.5 pt-1 border-t border-border/60">
        <span className="text-[10px] uppercase font-mono text-muted block">Exploit This Volatility Skew:</span>
        <div className="flex flex-wrap gap-1.5">
          {[
            {
              label: '⚡ Bull Put Credit Spread (Harvest Skew)',
              q: `Build a high-probability Bull Put credit spread for ${symbol} to harvest the elevated put volatility skew.`,
            },
            {
              label: '🎯 Cheap Upside Call Ladder',
              q: `Construct a low-cost Call Ratio Spread or Call Ladder for ${symbol} taking advantage of suppressed call IV.`,
            },
            {
              label: '🛡️ Vega-Neutral Iron Condor',
              q: `Design a Vega-neutral Iron Condor strategy for ${symbol} with optimal strike wings based on this IV smile.`,
            },
          ].map((chip) => (
            <button
              key={chip.label}
              onClick={() => sendDraft(chip.q)}
              className="text-[10px] font-ui px-2.5 py-1 rounded-full border border-border/70 text-muted hover:text-text hover:border-cyan-400/50 hover:bg-cyan-500/5 transition-all cursor-pointer shadow-xs"
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
