import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

function fmt(n) {
  return Number(n ?? 0).toLocaleString('en-IN')
}

export default function OICard({ data }) {
  const d = data?.data ?? data ?? {}
  const symbol = d.symbol ?? d.underlying ?? '—'
  const spot = d.spot ?? d.spot_price ?? 0
  const pcr = d.pcr ?? d.put_call_ratio ?? null
  const maxPain = d.max_pain ?? d.resistance ?? null
  const support = d.support ?? null
  const chain = d.chain ?? []
  const dataSource = d.data_source

  const sendDraft = useChatStore((s) => s.sendDraft)
  const [viewMode, setViewMode] = useState('chart') // 'chart' | 'table'

  const topStrikes = [...chain]
    .sort((a, b) => (b.ce_oi + b.pe_oi) - (a.ce_oi + a.pe_oi))
    .slice(0, 10)
    .sort((a, b) => a.strike - b.strike)

  const maxOI = Math.max(
    ...topStrikes.map((s) => Math.max(s.ce_oi || 0, s.pe_oi || 0)),
    1
  )

  const getPcrBadge = (val) => {
    if (val == null) return null
    if (val >= 1.25) return { text: 'BULLISH', cls: 'bg-green/10 text-green border-green/30' }
    if (val <= 0.75) return { text: 'BEARISH', cls: 'bg-red/10 text-red border-red/30' }
    return { text: 'NEUTRAL', cls: 'bg-amber/10 text-amber border-amber/30' }
  }

  const pcrStatus = getPcrBadge(pcr)

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-3">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Open Interest Profile</p>
            {dataSource === 'ESTIMATED_MODEL' && (
              <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber/10 text-amber border border-amber/20 font-ui">
                Est. Model
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-text text-lg font-semibold">{symbol}</span>
            {spot > 0 && (
              <span className="text-amber text-xs bg-amber/10 border border-amber/30 px-1.5 py-0.5 rounded font-ui">
                Spot ₹{Number(spot).toLocaleString('en-IN')}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {pcr != null && (
            <div className="text-right">
              <span className="text-muted text-[10px] uppercase font-ui block">PCR</span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-text text-sm font-semibold">{Number(pcr).toFixed(2)}</span>
                {pcrStatus && (
                  <span className={`text-[9px] px-1.5 py-0.5 rounded border font-ui ${pcrStatus.cls}`}>
                    {pcrStatus.text}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* View toggle */}
          <div className="flex items-center bg-panel rounded border border-border/60 p-0.5 text-[11px] font-ui">
            <button
              onClick={() => setViewMode('chart')}
              className={`px-2 py-0.5 rounded transition-all ${
                viewMode === 'chart' ? 'bg-amber text-black font-semibold' : 'text-muted hover:text-text'
              }`}
            >
              Visual
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`px-2 py-0.5 rounded transition-all ${
                viewMode === 'table' ? 'bg-amber text-black font-semibold' : 'text-muted hover:text-text'
              }`}
            >
              Table
            </button>
          </div>
        </div>
      </div>

      {/* Key Levels Overview */}
      {(maxPain || support) && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          {support && (
            <div className="bg-green/5 border border-green/20 rounded-lg p-2.5">
              <p className="text-green text-[10px] font-ui uppercase tracking-wider">Strong Support (Max Put OI)</p>
              <p className="text-text text-sm font-semibold mt-0.5">₹{Number(support).toLocaleString('en-IN')}</p>
            </div>
          )}
          {maxPain && (
            <div className="bg-red/5 border border-red/20 rounded-lg p-2.5">
              <p className="text-red text-[10px] font-ui uppercase tracking-wider">Resistance Wall (Max Call OI)</p>
              <p className="text-text text-sm font-semibold mt-0.5">₹{Number(maxPain).toLocaleString('en-IN')}</p>
            </div>
          )}
        </div>
      )}

      {/* Visual Chart View */}
      {viewMode === 'chart' && (
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-[10px] text-muted font-ui px-1">
            <span className="text-red flex items-center gap-1">
              <span className="w-2 h-2 rounded-xs bg-red/80 inline-block" /> Call OI (Resistance)
            </span>
            <span className="text-text font-semibold">Strike</span>
            <span className="text-green flex items-center gap-1">
              Put OI (Support) <span className="w-2 h-2 rounded-xs bg-green/80 inline-block" />
            </span>
          </div>

          <div className="space-y-1.5">
            {topStrikes.map((row) => {
              const ceWidth = `${Math.min(100, Math.round(((row.ce_oi || 0) / maxOI) * 100))}%`
              const peWidth = `${Math.min(100, Math.round(((row.pe_oi || 0) / maxOI) * 100))}%`
              const atm =
                spot > 0 &&
                Math.abs(row.strike - spot) <
                  ((topStrikes[1]?.strike - topStrikes[0]?.strike) || 50) / 2

              return (
                <div key={row.strike} className="flex items-center gap-2 text-xs">
                  {/* Call Bar (Right to Left) */}
                  <div className="flex-1 flex items-center justify-end gap-1.5 overflow-hidden">
                    <span className="text-[10px] text-muted shrink-0">{fmt(row.ce_oi)}</span>
                    <div className="w-full bg-panel/40 h-3 rounded-l flex justify-end overflow-hidden">
                      <div
                        className="bg-red/70 h-full rounded-l transition-all duration-300"
                        style={{ width: ceWidth }}
                      />
                    </div>
                  </div>

                  {/* Strike Badge */}
                  <div
                    className={`w-20 text-center font-bold px-1.5 py-0.5 rounded text-[11px] shrink-0 ${
                      atm ? 'bg-amber text-black font-semibold' : 'bg-panel text-text border border-border/50'
                    }`}
                  >
                    {Number(row.strike).toLocaleString('en-IN')}
                    {atm && <span className="text-[9px] block leading-none mt-0.5">ATM</span>}
                  </div>

                  {/* Put Bar (Left to Right) */}
                  <div className="flex-1 flex items-center gap-1.5 overflow-hidden">
                    <div className="w-full bg-panel/40 h-3 rounded-r flex justify-start overflow-hidden">
                      <div
                        className="bg-green/70 h-full rounded-r transition-all duration-300"
                        style={{ width: peWidth }}
                      />
                    </div>
                    <span className="text-[10px] text-muted shrink-0">{fmt(row.pe_oi)}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Table View */}
      {viewMode === 'table' && topStrikes.length > 0 && (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-muted uppercase tracking-wider border-b border-border text-[10px] font-ui">
              <th className="text-right pb-2 text-red">Call OI</th>
              <th className="text-center pb-2 text-text">Strike</th>
              <th className="text-left pb-2 text-green">Put OI</th>
            </tr>
          </thead>
          <tbody>
            {topStrikes.map((row, i) => {
              const atm =
                spot > 0 &&
                Math.abs(row.strike - spot) <
                  ((topStrikes[1]?.strike - topStrikes[0]?.strike) || 50) / 2
              return (
                <tr key={i} className={`border-b border-border/40 last:border-0 ${atm ? 'bg-amber/5' : ''}`}>
                  <td className="py-1.5 text-right text-red">{fmt(row.ce_oi)}</td>
                  <td className={`py-1.5 text-center font-semibold ${atm ? 'text-amber' : 'text-text'}`}>
                    {Number(row.strike).toLocaleString('en-IN')} {atm && '★ ATM'}
                  </td>
                  <td className="py-1.5 text-left text-green">{fmt(row.pe_oi)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {/* 1-Click Action Chips */}
      <div className="mt-3 pt-3 border-t border-border/40 flex flex-wrap gap-1.5 text-[11px] font-ui">
        <button
          onClick={() => sendDraft(`payoff ${symbol}`)}
          className="bg-amber/10 text-amber border border-amber/30 hover:bg-amber/20 px-2.5 py-1 rounded-lg transition-colors cursor-pointer font-semibold shadow-xs"
          title={`Simulate options payoff strategy for ${symbol}`}
        >
          🎯 Payoff Simulator
        </button>
        <button
          onClick={() => sendDraft(`analyze ${symbol}`)}
          className="bg-panel hover:bg-elevated text-text border border-border/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
          title={`Launch full multi-agent AI debate for ${symbol}`}
        >
          ⚡ Multi-Agent Analysis
        </button>
        <button
          onClick={() => sendDraft(`backtest ${symbol} rsi`)}
          className="bg-panel hover:bg-elevated text-text border border-border/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
          title={`Run RSI backtest on ${symbol}`}
        >
          🧪 Backtest
        </button>
      </div>
    </div>
  )
}
