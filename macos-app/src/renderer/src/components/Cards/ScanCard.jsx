import { useEffect, useState } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'

function Section({ title, items, color, onSelect }) {
  if (!items?.length) return null

  // Deduplicate items by symbol to guarantee zero duplicate symbols in the UI
  const seenSymbols = new Set()
  const displayItems = []
  for (const it of items) {
    const sym = typeof it === 'string' ? it : it.symbol ?? it.tradingsymbol
    if (!sym || seenSymbols.has(sym)) continue
    seenSymbols.add(sym)
    displayItems.push(it)
  }

  if (!displayItems.length) return null

  return (
    <div>
      <p className={`text-[10px] uppercase tracking-widest font-ui mb-2 ${color}`}>{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {displayItems.map((item, i) => {
          const isObj = typeof item === 'object' && item !== null
          const rawSymbol = isObj ? item.symbol ?? item.tradingsymbol ?? JSON.stringify(item) : item
          const underlyingSymbol = isObj && item.symbol ? item.symbol : rawSymbol

          const hasContract = isObj && item.strike != null && item.option_type != null
          const optType = (item.option_type || '').toUpperCase()
          const isCall = optType === 'CE' || optType === 'CALL'

          let detail = ''
          if (isObj) {
            if (item.iv_rank != null) {
              detail = `IV ${item.iv_rank}%`
            } else if (item.oi_change_pct != null) {
              detail = `OI +${Number(item.oi_change_pct).toLocaleString()}%`
            } else if (item.oi_change != null) {
              detail = `OI +${Number(item.oi_change).toLocaleString()}`
            }
          }

          const uniqueKey = `${underlyingSymbol}-${item.strike ?? ''}-${item.option_type ?? ''}-${i}`

          return (
            <button
              key={uniqueKey}
              onClick={() => onSelect?.(underlyingSymbol)}
              className={`border rounded-lg px-2.5 py-1.5 transition-all hover:scale-102 cursor-pointer ${color
                .replace('text-', 'border-')
                .replace('500', '400')}/30 bg-panel hover:bg-elevated text-left flex items-center gap-1.5`}
              title={
                hasContract
                  ? `${underlyingSymbol} ${item.strike} ${optType} (Peak OI spike: ${detail})`
                  : `Select ${underlyingSymbol}`
              }
            >
              <span className={`text-[12px] font-mono font-semibold ${color}`}>{underlyingSymbol}</span>

              {hasContract && (
                <span
                  className={`text-[10px] font-mono px-1.5 py-0.2 rounded border font-semibold ${
                    isCall
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                      : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                  }`}
                >
                  {Math.round(item.strike)} {optType}
                </span>
              )}

              {item.spikes_count > 1 && (
                <span
                  className="text-[9px] font-ui px-1 py-0.2 rounded bg-amber/10 text-amber border border-amber/20"
                  title={`${item.spikes_count} active strike spikes for ${underlyingSymbol}`}
                >
                  {item.spikes_count}⚡
                </span>
              )}

              {detail && <span className="text-[10px] font-ui text-muted">{detail}</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function ScanCard({ data }) {
  const d = data?.data ?? data ?? {}
  const summary = d.summary ?? d.scan_summary ?? null
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)

  const [sectors, setSectors] = useState([])
  const [loadingSectors, setLoadingSectors] = useState(false)

  // Fetch live sector heatmap on mount
  useEffect(() => {
    let unmounted = false
    setLoadingSectors(true)
    const fetchSectors = async () => {
      try {
        const res = await call('/skills/sector_heatmap', {})
        const json = res?.data ?? res
        if (!unmounted && json?.sectors) {
          setSectors(json.sectors)
        }
      } catch (err) {
        console.error('Sector heatmap error:', err)
      } finally {
        if (!unmounted) setLoadingSectors(false)
      }
    }
    fetchSectors()
    return () => {
      unmounted = true
    }
  }, [])

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Top Header & Breadcrumb Navigation */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div>
          <div className="flex items-center gap-1.5 text-muted text-[10px] uppercase tracking-widest font-ui">
            <button
              onClick={() => useChatStore.getState().setShowDashboard(true)}
              className="hover:text-amber transition-colors cursor-pointer"
              title="Return to Home / Overview Dashboard"
            >
              🏠 Home
            </button>
            <span>/</span>
            <span>Market Scanner</span>
          </div>
          <p className="text-text text-base font-semibold font-ui mt-0.5">NSE Breadth &amp; Breakouts</p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('open-top-opportunities'))}
            className="px-2.5 py-1 bg-green/10 hover:bg-green/20 text-green border border-green/30 text-xs font-ui font-semibold rounded-lg transition-colors cursor-pointer flex items-center gap-1 shadow-xs"
            title="Open Market-Aware High-Conviction Radar"
          >
            <span>🎯</span>
            <span className="hidden sm:inline">Top</span> Radar
          </button>
          <button
            onClick={() => useChatStore.getState().setShowDashboard(true)}
            className="px-2.5 py-1 bg-panel hover:bg-elevated border border-border text-muted hover:text-text text-xs font-ui rounded-lg transition-colors cursor-pointer"
            title="Back to Overview Dashboard"
          >
            ← Dashboard
          </button>
        </div>
      </div>

      {summary && <p className="text-muted text-[12px] font-ui leading-relaxed">{summary}</p>}

      {/* Sector Breadth Heatmap Tiles */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-[10px] font-ui text-muted uppercase tracking-wider">
          <span>Sector Heatmap</span>
          {loadingSectors && <span>Refreshing…</span>}
        </div>

        {sectors.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {Array.from(new Map(sectors.map((s) => [s.code, s])).values()).map((sec) => {
              const chg = sec.change_pct ?? 0
              const isUp = chg >= 0
              const displayName = sec.name.replace(/^NIFTY\s*/i, '') || sec.code
              return (
                <button
                  key={sec.code}
                  onClick={() => {
                    window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: displayName } }))
                  }}
                  className={`p-2 rounded-lg border text-left transition-all hover:scale-102 cursor-pointer group ${
                    isUp
                      ? 'bg-green/10 border-green/30 text-green hover:border-green'
                      : 'bg-red/10 border-red/30 text-red hover:border-red'
                  }`}
                  title={`Click to view all constituent stocks & contributing factors in ${sec.name}`}
                >
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold font-ui truncate group-hover:text-amber">{displayName}</p>
                    <span className="text-[10px] opacity-70 group-hover:opacity-100 group-hover:text-amber">→</span>
                  </div>
                  <p className="text-[12px] font-bold mt-0.5 font-mono">
                    {isUp ? '+' : ''}
                    {chg.toFixed(2)}%
                  </p>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="bg-panel/40 border border-border/40 rounded-lg p-3 text-center text-muted text-xs font-ui">
            Loading sector metrics…
          </div>
        )}
      </div>

      {/* Technical & Options Breakouts (1-Click Instant Execution) */}
      <div className="space-y-3 pt-2 border-t border-border/40">
        <Section
          title="High Implied Volatility"
          items={d.high_iv}
          color="text-red"
          onSelect={(s) => sendDraft(`analyze ${s}`)}
        />
        <Section
          title="Unusual Open Interest Spike"
          items={d.unusual_oi}
          color="text-amber"
          onSelect={(s) => sendDraft(`oi ${s}`)}
        />
        <Section
          title="Strong Put Writing (Bullish Support)"
          items={d.high_put_writing}
          color="text-green"
          onSelect={(s) => sendDraft(`analyze ${s}`)}
        />
        <Section
          title="Active Opportunities"
          items={d.opportunities ?? d.results}
          color="text-blue"
          onSelect={(s) => sendDraft(`analyze ${s}`)}
        />
      </div>
    </div>
  )
}
