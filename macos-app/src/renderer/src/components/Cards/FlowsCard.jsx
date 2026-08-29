import { useEffect, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'

export default function FlowsCard({ data }) {
  if (!data) return null

  const d = data?.data ?? data ?? {}
  const fii = Number(d.fii_net_today ?? 0)
  const dii = Number(d.dii_net_today ?? 0)
  const fii5 = Number(d.fii_5d_net ?? 0)
  const dii5 = Number(d.dii_5d_net ?? 0)

  const { call } = useAPI()
  const [history, setHistory] = useState([])
  const [loadingHist, setLoadingHist] = useState(false)

  useEffect(() => {
    let unmounted = false
    setLoadingHist(true)
    const fetchHistory = async () => {
      try {
        const res = await call('/skills/flows_history', { days: 10 })
        const json = res?.data ?? res
        if (!unmounted && json?.history) {
          setHistory(json.history)
        }
      } catch (err) {
        console.error('Flows history error:', err)
      } finally {
        if (!unmounted) setLoadingHist(false)
      }
    }
    fetchHistory()
    return () => {
      unmounted = true
    }
  }, [])

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-xl w-full space-y-4 font-mono shadow-sm">
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber">🌊</span>
          <div>
            <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Radar</p>
            <p className="text-text text-base font-semibold font-ui">FII / DII Flow Intelligence</p>
          </div>
        </div>

        {/* Signal badge */}
        {d.signal && <Signal value={d.signal} reason={d.signal_reason} />}
      </div>

      {/* Flow grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <FlowBox label="FII Today" value={fii} streak={d.fii_streak} />
        <FlowBox label="DII Today" value={dii} streak={d.dii_streak} />
        <FlowBox label="FII 5-Day Net" value={fii5} />
        <FlowBox label="DII 5-Day Net" value={dii5} />
      </div>

      {/* Multi-Day Historical Flow Comparison */}
      {history.length > 0 && (
        <div className="space-y-2 pt-2 border-t border-border/40">
          <div className="flex justify-between text-[10px] text-muted uppercase font-ui">
            <span>Historical Net Activity (₹ Cr)</span>
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 bg-blue rounded-xs inline-block" /> FII Net
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 bg-purple rounded-xs inline-block" /> DII Net
              </span>
            </div>
          </div>

          <div className="space-y-1">
            {history.slice(0, 7).map((item, idx) => {
              const fNet = item.fii_net || 0
              const dNet = item.dii_net || 0
              return (
                <div key={idx} className="flex items-center gap-2 text-[11px] py-0.5">
                  <span className="w-16 text-muted font-mono text-[10px] shrink-0">{item.date}</span>

                  {/* FII Net bar & text */}
                  <div className="flex-1 flex items-center justify-end gap-1">
                    <span className={`text-[10px] ${fNet >= 0 ? 'text-green' : 'text-red'}`}>
                      {fNet >= 0 ? '+' : ''}{Math.round(fNet)}
                    </span>
                    <div className="w-16 bg-panel h-2 rounded overflow-hidden">
                      <div
                        className={`h-full ${fNet >= 0 ? 'bg-green' : 'bg-red'}`}
                        style={{ width: `${Math.min(100, Math.abs(fNet) / 50)}%` }}
                      />
                    </div>
                  </div>

                  {/* DII Net bar & text */}
                  <div className="flex-1 flex items-center gap-1">
                    <div className="w-16 bg-panel h-2 rounded overflow-hidden">
                      <div
                        className={`h-full ${dNet >= 0 ? 'bg-green' : 'bg-red'}`}
                        style={{ width: `${Math.min(100, Math.abs(dNet) / 50)}%` }}
                      />
                    </div>
                    <span className={`text-[10px] ${dNet >= 0 ? 'text-green' : 'text-red'}`}>
                      {dNet >= 0 ? '+' : ''}{Math.round(dNet)}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Divergence alert */}
      {d.divergence && (
        <div className="bg-amber/5 border border-amber/20 rounded-lg p-2.5 text-xs font-ui text-text">
          <span className="text-amber font-semibold">Institutional Divergence: </span>
          {d.divergence_type === 'FII_SELL_DII_BUY'
            ? 'FIIs are aggressively selling while domestic mutual funds (DIIs) are absorbing supply.'
            : 'FIIs are actively buying into strength while DIIs book profits.'}
        </div>
      )}
    </div>
  )
}

function FlowBox({ label, value, streak }) {
  const pos = value >= 0
  return (
    <div className="bg-panel rounded-lg p-2.5 border border-border/50">
      <p className="text-muted text-[10px] uppercase tracking-wider font-ui mb-0.5">{label}</p>
      <p className={`font-mono text-sm font-semibold ${pos ? 'text-green' : 'text-red'}`}>
        {pos ? '+' : ''}₹{Math.abs(value).toFixed(0)} Cr
      </p>
      {streak !== undefined && streak !== 0 && (
        <p className="text-muted text-[9px] font-ui mt-0.5">
          {Math.abs(streak)}d {streak >= 0 ? 'buying' : 'selling'}
        </p>
      )}
    </div>
  )
}

function Signal({ value, reason }) {
  const color =
    value === 'BULLISH'
      ? 'text-green border-green/30 bg-green/5'
      : value === 'BEARISH'
      ? 'text-red border-red/30 bg-red/5'
      : 'text-muted border-border'
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-ui ${color}`}>
      <span className="font-bold">{value}</span>
      {reason && <span className="text-muted text-[10px] hidden sm:inline">— {reason}</span>}
    </div>
  )
}
