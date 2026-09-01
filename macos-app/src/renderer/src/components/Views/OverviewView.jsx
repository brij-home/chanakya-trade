import { useState, useEffect, useRef, useCallback } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import SkeletonCard from '../Loading/SkeletonCard'
import DataStateBadge from '../Common/DataStateBadge'
import UnavailableState from '../Common/UnavailableState'

// ── P0-A: This view NEVER uses hardcoded numeric fallbacks for production data.
// When data is unavailable (API down, provider error), we show UnavailableState.
// Users must always know whether they are seeing real or unavailable data.

const PHASE_STYLE = {
  LEADING:    { color: 'var(--color-emerald)', bg: 'rgba(0,214,143,0.12)', label: '▲ LEADING' },
  WEAKENING:  { color: 'var(--color-gold)',    bg: 'rgba(245,166,35,0.12)', label: '◤ WEAKENING' },
  LAGGING:    { color: 'var(--color-rose)',    bg: 'rgba(255,79,123,0.12)', label: '▼ LAGGING' },
  IMPROVING:  { color: 'var(--color-sapphire)',bg: 'rgba(77,155,255,0.12)', label: '◢ IMPROVING' },
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

/** India VIX arc gauge — only renders when value is a real number */
function VIXGauge({ value }) {
  if (value == null || isNaN(value)) return null
  const max = 40
  const pct = Math.min(value / max, 1)
  const circumference = 2 * Math.PI * 40
  const dash = circumference * pct
  const color = value < 14 ? 'var(--color-emerald)' : value < 20 ? 'var(--color-gold)' : 'var(--color-rose)'
  const label = value < 14 ? 'LOW FEAR' : value < 20 ? 'ELEVATED' : 'HIGH FEAR'

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={100} height={60} viewBox="0 0 100 60" aria-label={`India VIX: ${value}, ${label}`}>
        {/* Track */}
        <path
          d="M 10 55 A 40 40 0 0 1 90 55"
          fill="none" stroke="var(--color-border)" strokeWidth={8} strokeLinecap="round"
        />
        {/* Fill */}
        <path
          d="M 10 55 A 40 40 0 0 1 90 55"
          fill="none" stroke={color} strokeWidth={8} strokeLinecap="round"
          strokeDasharray={`${(dash/circumference) * 125.6} 125.6`}
          style={{ transition: 'stroke-dasharray 1s var(--ease-out)', filter: `drop-shadow(0 0 6px ${color})` }}
        />
        <text x="50" y="50" textAnchor="middle" fill="var(--color-text)" fontSize={14} fontWeight={700} fontFamily="JetBrains Mono">
          {value}
        </text>
      </svg>
      <div className="text-center">
        <div className="text-[9px] font-bold tracking-widest" style={{ color }}>INDIA VIX • {label}</div>
      </div>
    </div>
  )
}

/** Breadth indicator bar — only renders when values are real numbers */
function BreadthBar({ advancing, declining, unchanged }) {
  if (advancing == null || declining == null) return null
  const total = Math.max(1, advancing + declining + (unchanged ?? 0))
  const aP = (advancing / total * 100).toFixed(0)
  const dP = (declining / total * 100).toFixed(0)
  const uP = ((unchanged ?? 0) / total * 100).toFixed(0)

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[10px] font-mono">
        <span style={{ color: 'var(--color-emerald)' }}>▲ {advancing} ADV ({aP}%)</span>
        <span style={{ color: 'var(--color-muted)' }}>{unchanged ?? 0} UNCH</span>
        <span style={{ color: 'var(--color-rose)' }}>▼ {declining} DEC ({dP}%)</span>
      </div>
      <div className="flex h-3 rounded-full overflow-hidden gap-0.5">
        <div className="rounded-l-full transition-all" style={{ width: `${aP}%`, background: 'var(--color-emerald)' }} />
        <div className="transition-all" style={{ width: `${uP}%`, background: 'var(--color-subtle)' }} />
        <div className="rounded-r-full transition-all" style={{ width: `${dP}%`, background: 'var(--color-rose)' }} />
      </div>
    </div>
  )
}

/** FII/DII flow chart bar — only renders when value is a real number */
function FlowBar({ label, value, max = 3000 }) {
  if (value == null || isNaN(value)) return null
  const isPos = value >= 0
  const pct = Math.min(100, Math.abs(value) / Math.max(1, max) * 100)
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] font-mono">
        <span style={{ color: 'var(--color-muted)' }}>{label}</span>
        <span style={{ color: isPos ? 'var(--color-emerald)' : 'var(--color-rose)', fontWeight: 700 }}>
          {isPos ? '+' : ''}₹{Math.abs(value).toLocaleString('en-IN')} Cr
        </span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-subtle)' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            background: isPos ? 'var(--color-emerald)' : 'var(--color-rose)',
          }}
        />
      </div>
    </div>
  )
}

/* ── Main View ───────────────────────────────────────────────────────────── */
export default function OverviewView() {
  const { call } = useAPI()
  const callRef = useRef(call)
  useEffect(() => { callRef.current = call }, [call])
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [data, setData] = useState(null)
  const [globalMacro, setGlobalMacro] = useState(null)
  const [loading, setLoading] = useState(true)
  const [overviewError, setOverviewError] = useState(null)
  const [macroError, setMacroError] = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setOverviewError(null)
    setMacroError(null)

    const [resOverview, resMacro] = await Promise.allSettled([
      callRef.current('/skills/market_overview'),
      callRef.current('/skills/global_macro'),
    ])

    if (resOverview.status === 'fulfilled' && resOverview.value) {
      setData(resOverview.value?.data ?? resOverview.value)
    } else {
      setOverviewError(resOverview.reason?.message ?? 'Market overview unavailable')
    }

    if (resMacro.status === 'fulfilled' && resMacro.value) {
      setGlobalMacro(resMacro.value?.data ?? resMacro.value)
    } else {
      setMacroError(resMacro.reason?.message ?? 'Global macro data unavailable')
    }

    setLoading(false)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps — intentionally stable; callRef.current handles fresh call

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // P0-A: Derive real values only — no numeric fallbacks.
  // If data is null/absent, the corresponding sub-component shows UnavailableState.
  const vix = data?.vix ?? null
  const fiiNet = data?.fii_net ?? null
  const diiNet = data?.dii_net ?? null
  const advancers = data?.advancers ?? null
  const decliners = data?.decliners ?? null
  const unchanged = data?.unchanged ?? null
  const sectorList = (data?.sectors && data.sectors.length > 0) ? data.sectors : null

  const macroItems = globalMacro?.items ? Object.values(globalMacro.items) : null
  const impliedGap = globalMacro?.implied_nifty_gap_pct ?? null
  const impliedGapPts = globalMacro?.implied_nifty_gap_pts ?? null
  const sectorImpacts = globalMacro?.sector_impacts ?? []

  // Data source/freshness metadata from backend (P0-A envelope)
  const overviewStatus = data?._status ?? (data ? 'cached_fresh' : 'unavailable')
  const overviewAsOf = data?._as_of ?? null
  const overviewSource = data?._source_name ?? null
  const macroStatus = globalMacro?._status ?? (globalMacro ? 'cached_fresh' : 'unavailable')
  const macroAsOf = globalMacro?._as_of ?? null

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-black" style={{ color: 'var(--color-text)' }}>🌐 Market Overview &amp; Global Macro</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            GIFT NIFTY Gap • Global 6 • India VIX • FII/DII Flows • Sector RRG
          </p>
        </div>
        {/* P0-A: Show real data status, not a fake "Live Institutional Feeds" badge */}
        <DataStateBadge
          status={overviewStatus}
          sourceName={overviewSource}
          asOf={overviewAsOf}
        />
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[1,2,3].map(i => <SkeletonCard key={i} variant="card" lines={4} />)}
        </div>
      ) : (
        <>
          {/* Row 1: Global Macro Transmission */}
          <div
            className="rounded-2xl p-4 animate-slide-up-fade"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-xl">🌍</span>
                <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-text">
                  Global Macro &amp; Modelled Opening Sentiment
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs font-mono">
                {impliedGap != null ? (
                  <>
                    <span className="text-muted text-[10px]">Modelled Open:</span>
                    <span className={`font-black px-2 py-0.5 rounded-md border ${impliedGap >= 0 ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400' : 'bg-rose-500/15 border-rose-500/30 text-rose-400'}`}>
                      {impliedGap >= 0 ? `+${impliedGap.toFixed(2)}%` : `${impliedGap.toFixed(2)}%`}
                      {impliedGapPts != null ? ` (${impliedGapPts >= 0 ? '+' : ''}${impliedGapPts.toFixed(1)} pts)` : ''}
                    </span>
                  </>
                ) : (
                  <span className="text-[10px] text-muted">Implied open: unavailable</span>
                )}
                <DataStateBadge status={macroStatus} asOf={macroAsOf} compact />
              </div>
            </div>

            {/* Global Tickers Grid — P0-A: only if real data available */}
            {macroItems && macroItems.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
                {macroItems.slice(0, 6).map((m) => {
                  const isPos = m.change_pct > 0
                  // P0-A: show proxy badge for yfinance-derived values
                  const isProxy = m.data_status === 'derived_proxy' || m.is_proxy === true
                  return (
                    <div
                      key={m.name}
                      className="rounded-xl p-2.5 space-y-1 transition-all hover:scale-105"
                      style={{
                        background: 'var(--color-elevated)',
                        border: `1px solid ${isPos ? 'rgba(0,214,143,0.25)' : 'rgba(255,79,123,0.25)'}`,
                      }}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <div className="text-[10px] font-bold truncate" style={{ color: 'var(--color-muted)' }}>
                          {m.name}
                        </div>
                        {isProxy && (
                          <span
                            className="text-[8px] font-mono px-1 rounded bg-violet-500/15 border border-violet-500/25 text-violet-400 flex-shrink-0"
                            title="Research proxy — not your tradable MCX/exchange price"
                          >
                            PROXY
                          </span>
                        )}
                      </div>
                      <div className="text-xs font-mono font-bold" style={{ color: 'var(--color-text)' }}>
                        {Number(m.ltp).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                        <span className="text-[9px] font-normal text-muted ml-0.5">{m.unit}</span>
                      </div>
                      <div
                        className="text-[10px] font-mono font-bold flex items-center justify-between"
                        style={{ color: isPos ? 'var(--color-emerald)' : 'var(--color-rose)' }}
                      >
                        <span>{isPos ? '+' : ''}{Number(m.change_pct).toFixed(2)}%</span>
                        <span className="text-[8px] opacity-80 uppercase">{m.impact_bias || 'NEUTRAL'}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : macroError ? (
              <UnavailableState
                title="Global macro data unavailable"
                reason="Could not reach the data provider. Check your connection."
                hint="yfinance (research proxy) or Fyers required"
                onRetry={fetchData}
                size="sm"
              />
            ) : (
              <UnavailableState
                title="No macro data received"
                reason="The server did not return macro items for this session."
                onRetry={fetchData}
                size="sm"
              />
            )}

            {/* Sector Impact Attribution Summary */}
            {sectorImpacts.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {sectorImpacts.slice(0, 3).map((sec) => (
                  <div key={sec.sector_id} className="p-2 rounded-lg bg-surface/60 border border-border/50 text-[10px] font-ui space-y-0.5">
                    <div className="flex items-center justify-between font-bold">
                      <span className="text-text">{sec.sector_name}</span>
                      <span className={sec.bias?.includes('TAILWIND') ? 'text-emerald-400' : sec.bias?.includes('HEADWIND') ? 'text-rose-400' : 'text-muted'}>
                        {sec.bias?.includes('TAILWIND') ? '🚀 TAILWIND' : sec.bias?.includes('HEADWIND') ? '⚠️ HEADWIND' : '⚖️ NEUTRAL'}
                      </span>
                    </div>
                    <p className="text-muted leading-tight truncate">{sec.rationale}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Row 2: VIX + Breadth + FII/DII — P0-A: show UnavailableState when data is missing */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* VIX Gauge */}
            <div
              className="rounded-2xl p-4 animate-slide-up-fade"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wider mb-3" style={{ color: 'var(--color-muted)' }}>
                ⚡ India VIX — Fear Gauge
              </div>
              {vix != null ? (
                <>
                  <VIXGauge value={vix} />
                  <div className="mt-3 text-[10px] text-center" style={{ color: 'var(--color-muted)' }}>
                    Safe zone: VIX &lt; 14.5 | Danger: VIX &gt; 20
                  </div>
                </>
              ) : (
                <UnavailableState
                  title="India VIX unavailable"
                  reason={overviewError ?? 'No VIX data from provider'}
                  onRetry={fetchData}
                  size="sm"
                />
              )}
            </div>

            {/* Market Breadth */}
            <div
              className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)', animationDelay: '50ms' }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
                📊 NSE 500 Breadth
              </div>
              {advancers != null && decliners != null ? (
                <>
                  <BreadthBar advancing={advancers} declining={decliners} unchanged={unchanged} />
                  <div
                    className="text-center py-2 rounded-xl text-sm font-black"
                    style={{
                      background: advancers > decliners ? 'rgba(0,214,143,0.1)' : 'rgba(255,79,123,0.1)',
                      color: advancers > decliners ? 'var(--color-emerald)' : 'var(--color-rose)',
                    }}
                  >
                    {advancers > decliners ? '🚀 BULLISH BREADTH' : '🛡️ BEARISH BREADTH'}
                  </div>
                  <div className="text-[10px] text-muted">
                    A/D Ratio: {(advancers / Math.max(decliners, 1)).toFixed(2)}x &nbsp;|&nbsp;
                    {advancers + decliners + (unchanged ?? 0)} stocks tracked
                  </div>
                </>
              ) : (
                <UnavailableState
                  title="Breadth data unavailable"
                  reason={overviewError ?? 'NSE advance/decline data not available'}
                  onRetry={fetchData}
                  size="sm"
                />
              )}
            </div>

            {/* FII/DII Flows */}
            <div
              className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)', animationDelay: '100ms' }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
                💰 FII / DII Net Flows (Daily)
              </div>
              {fiiNet != null && diiNet != null ? (
                <>
                  <FlowBar label="FII Net" value={fiiNet} />
                  <FlowBar label="DII Net" value={diiNet} />
                  <div className="pt-1 border-t" style={{ borderColor: 'var(--color-border)' }}>
                    <FlowBar label="NET" value={fiiNet + diiNet} max={5000} />
                  </div>
                  <div className="text-[10px]" style={{ color: 'var(--color-muted)' }}>
                    Combined: <span style={{ color: (fiiNet + diiNet) >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)', fontWeight: 700 }}>
                      {(fiiNet + diiNet) >= 0 ? '+' : ''}₹{(fiiNet + diiNet).toLocaleString('en-IN')} Cr
                    </span>
                  </div>
                </>
              ) : (
                <UnavailableState
                  title="FII/DII flows unavailable"
                  reason={overviewError ?? 'Institutional flow data not available'}
                  hint="Source: NSE / SEBI data feed"
                  onRetry={fetchData}
                  size="sm"
                />
              )}
            </div>
          </div>

          {/* Row 3: Sector Rotation Grid */}
          <div
            className="rounded-2xl p-4 animate-slide-up-fade"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)', animationDelay: '150ms' }}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
                🔄 Sector Rotation — RRG Phase Matrix
              </div>
              <div className="flex items-center gap-3 text-[9px]">
                {Object.entries(PHASE_STYLE).map(([phase, cfg]) => (
                  <span key={phase} className="font-bold" style={{ color: cfg.color }}>{cfg.label}</span>
                ))}
              </div>
            </div>
            {sectorList && sectorList.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-2">
                {sectorList.map((s) => {
                  const phaseKey = s.phase || (s.quadrant ? s.quadrant.toUpperCase() : 'LEADING')
                  const cfg = PHASE_STYLE[phaseKey] || PHASE_STYLE.LEADING
                  const chgVal = s.change_pct ?? s.change ?? null
                  return (
                    <div
                      key={s.name || s.sector}
                      className="rounded-xl p-2.5 text-center space-y-1 transition-all cursor-pointer hover:scale-105"
                      style={{ background: cfg.bg, border: `1px solid ${cfg.color}33` }}
                      onClick={() => sendDraft(`funnel sector ${(s.name || s.sector).toLowerCase()}`)}
                    >
                      <div className="text-xs font-bold truncate" style={{ color: 'var(--color-text)' }}>{s.name || s.sector}</div>
                      <div className="text-[10px] font-bold" style={{ color: cfg.color }}>{cfg.label.split(' ')[0]}</div>
                      {chgVal != null ? (
                        <div className="text-[11px] font-mono font-bold" style={{ color: chgVal >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                          {chgVal >= 0 ? '+' : ''}{Number(chgVal).toFixed(1)}%
                        </div>
                      ) : (
                        <div className="text-[10px] text-muted">—</div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <UnavailableState
                title="Sector rotation data unavailable"
                reason={overviewError ?? 'RRG sector data requires a connected data provider'}
                hint="Ask: 'sector rotation' in Copilot to fetch live RRG"
                onRetry={fetchData}
                size="sm"
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}
