import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import SkeletonCard from '../Loading/SkeletonCard'

const PHASE_STYLE = {
  LEADING:    { color: 'var(--color-emerald)', bg: 'rgba(0,214,143,0.12)', label: '▲ LEADING' },
  WEAKENING:  { color: 'var(--color-gold)',    bg: 'rgba(245,166,35,0.12)', label: '◤ WEAKENING' },
  LAGGING:    { color: 'var(--color-rose)',    bg: 'rgba(255,79,123,0.12)', label: '▼ LAGGING' },
  IMPROVING:  { color: 'var(--color-sapphire)',bg: 'rgba(77,155,255,0.12)', label: '◢ IMPROVING' },
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

/** India VIX arc gauge */
function VIXGauge({ value = 11.2 }) {
  const max = 40
  const pct = Math.min(value / max, 1)
  const circumference = 2 * Math.PI * 40
  const dash = circumference * pct
  const color = value < 14 ? 'var(--color-emerald)' : value < 20 ? 'var(--color-gold)' : 'var(--color-rose)'
  const label = value < 14 ? 'LOW FEAR' : value < 20 ? 'ELEVATED' : 'HIGH FEAR'

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={100} height={60} viewBox="0 0 100 60">
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

/** Breadth indicator bar */
function BreadthBar({ advancing = 285, declining = 165, unchanged = 50 }) {
  const total = Math.max(1, advancing + declining + unchanged)
  const aP = (advancing / total * 100).toFixed(0)
  const dP = (declining / total * 100).toFixed(0)
  const uP = (unchanged / total * 100).toFixed(0)

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[10px] font-mono">
        <span style={{ color: 'var(--color-emerald)' }}>▲ {advancing} ADV ({aP}%)</span>
        <span style={{ color: 'var(--color-muted)' }}>{unchanged} UNCH</span>
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

/** FII/DII flow chart bar */
function FlowBar({ label, value, max = 3000 }) {
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
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [data, setData] = useState(null)
  const [globalMacro, setGlobalMacro] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let unmounted = false
    const fetchData = async () => {
      try {
        setLoading(true)
        const [resOverview, resMacro] = await Promise.allSettled([
          call('/skills/market_overview'),
          call('/skills/global_macro'),
        ])

        if (!unmounted) {
          if (resOverview.status === 'fulfilled' && resOverview.value) {
            setData(resOverview.value?.data ?? resOverview.value)
          }
          if (resMacro.status === 'fulfilled' && resMacro.value) {
            setGlobalMacro(resMacro.value?.data ?? resMacro.value)
          }
        }
      } catch {
        /* defensive fallback */
      } finally {
        if (!unmounted) setLoading(false)
      }
    }
    fetchData()
    return () => { unmounted = true }
  }, [])

  const vix = data?.vix ?? 11.2
  const fiiNet = data?.fii_net ?? -1240
  const diiNet = data?.dii_net ?? 1840
  const advancers = data?.advancers ?? 285
  const decliners = data?.decliners ?? 165
  const unchanged = data?.unchanged ?? 50
  const sectorList = data?.sectors && data.sectors.length > 0 ? data.sectors : [
    { name: 'IT', rsi: 65, change: +0.8, phase: 'LEADING' },
    { name: 'Banking', rsi: 58, change: +0.4, phase: 'IMPROVING' },
    { name: 'Pharma', rsi: 62, change: +0.7, phase: 'LEADING' },
    { name: 'Auto', rsi: 61, change: +0.6, phase: 'LEADING' },
    { name: 'Metal', rsi: 44, change: -0.9, phase: 'WEAKENING' },
    { name: 'Energy', rsi: 56, change: +0.3, phase: 'IMPROVING' },
    { name: 'Realty', rsi: 49, change: -0.4, phase: 'LAGGING' },
    { name: 'FMCG', rsi: 52, change: +0.1, phase: 'IMPROVING' },
    { name: 'Defence', rsi: 68, change: +1.8, phase: 'LEADING' },
    { name: 'Infra', rsi: 54, change: +0.2, phase: 'IMPROVING' },
  ]

  const macroItems = globalMacro?.items ? Object.values(globalMacro.items) : [
    { name: 'NASDAQ 100', ltp: 26370.89, change_pct: -0.12, unit: 'pts', impact_bias: 'NEUTRAL' },
    { name: 'S&P 500', ltp: 7686.14, change_pct: -0.33, unit: 'pts', impact_bias: 'NEUTRAL' },
    { name: 'US Dollar Index', ltp: 99.51, change_pct: +0.02, unit: 'idx', impact_bias: 'NEUTRAL' },
    { name: 'USD / INR', ltp: 94.89, change_pct: -0.28, unit: '₹', impact_bias: 'NEUTRAL' },
    { name: 'Brent Crude', ltp: 88.90, change_pct: -0.10, unit: '$/bbl', impact_bias: 'NEUTRAL' },
    { name: 'US 10Y Yield', ltp: 4.76, change_pct: +0.81, unit: '%', impact_bias: 'BEARISH' },
  ]

  const impliedGap = globalMacro?.implied_nifty_gap_pct ?? -0.29
  const impliedGapPts = globalMacro?.implied_nifty_gap_pts ?? -70.0
  const sectorImpacts = globalMacro?.sector_impacts ?? []

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-black" style={{ color: 'var(--color-text)' }}>🌐 Market Overview & Global Macro</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            GIFT NIFTY Gap • High-Correlation Global 6 • India VIX • FII/DII Flows • Sector RRG
          </p>
        </div>
        <div
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold"
          style={{ background: 'rgba(0,214,143,0.12)', border: '1px solid rgba(0,214,143,0.3)', color: 'var(--color-emerald)' }}
        >
          <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--color-emerald)' }} />
          Live Institutional Feeds
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[1,2,3].map(i => <SkeletonCard key={i} variant="card" lines={4} />)}
        </div>
      ) : (
        <>
          {/* Row 1: Global Macro Transmission & GIFT NIFTY Opening Gap */}
          <div
            className="rounded-2xl p-4 animate-slide-up-fade"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-xl">🌍</span>
                <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-text">
                  Global Macro Transmission & GIFT NIFTY Implied Open
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs font-mono">
                <span className="text-muted text-[10px]">Implied Open:</span>
                <span className={`font-black px-2 py-0.5 rounded-md border ${impliedGap >= 0 ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400' : 'bg-rose-500/15 border-rose-500/30 text-rose-400'}`}>
                  {impliedGap >= 0 ? `+${impliedGap.toFixed(2)}%` : `${impliedGap.toFixed(2)}%`} ({impliedGapPts >= 0 ? `+${impliedGapPts.toFixed(1)}` : impliedGapPts.toFixed(1)} pts)
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-surface border border-border text-amber font-bold">
                  {globalMacro?.global_posture ?? 'BALANCED'}
                </span>
              </div>
            </div>

            {/* Global Tickers Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
              {macroItems.slice(0, 6).map((m) => {
                const isPos = m.change_pct > 0
                return (
                  <div
                    key={m.name}
                    className="rounded-xl p-2.5 space-y-1 transition-all hover:scale-105"
                    style={{
                      background: 'var(--color-elevated)',
                      border: `1px solid ${isPos ? 'rgba(0,214,143,0.25)' : 'rgba(255,79,123,0.25)'}`,
                    }}
                  >
                    <div className="text-[10px] font-bold truncate" style={{ color: 'var(--color-muted)' }}>
                      {m.name}
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

            {/* Sector Impact Attribution Summary */}
            {sectorImpacts.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {sectorImpacts.slice(0, 3).map((sec) => (
                  <div key={sec.sector_id} className="p-2 rounded-lg bg-surface/60 border border-border/50 text-[10px] font-ui space-y-0.5">
                    <div className="flex items-center justify-between font-bold">
                      <span className="text-text">{sec.sector_name}</span>
                      <span className={sec.bias.includes('TAILWIND') ? 'text-emerald-400' : sec.bias.includes('HEADWIND') ? 'text-rose-400' : 'text-muted'}>
                        {sec.bias.includes('TAILWIND') ? '🚀 TAILWIND' : sec.bias.includes('HEADWIND') ? '⚠️ HEADWIND' : '⚖️ NEUTRAL'}
                      </span>
                    </div>
                    <p className="text-muted leading-tight truncate">{sec.rationale}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Row 2: VIX + Breadth + FII/DII */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* VIX Gauge */}
            <div
              className="rounded-2xl p-4 animate-slide-up-fade"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wider mb-3" style={{ color: 'var(--color-muted)' }}>
                ⚡ India VIX — Fear Gauge
              </div>
              <VIXGauge value={vix} />
              <div className="mt-3 text-[10px] text-center" style={{ color: 'var(--color-muted)' }}>
                Safe zone: VIX &lt; 14.5 | Danger: VIX &gt; 20
              </div>
            </div>

            {/* Market Breadth */}
            <div
              className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)', animationDelay: '50ms' }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
                📊 NSE 500 Breadth
              </div>
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
                {advancers + decliners + unchanged} stocks tracked
              </div>
            </div>

            {/* FII/DII Flows */}
            <div
              className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)', animationDelay: '100ms' }}
            >
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
                💰 FII / DII Net Flows (Daily)
              </div>
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
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-2">
              {sectorList.map((s) => {
                const phaseKey = s.phase || (s.quadrant ? s.quadrant.toUpperCase() : 'LEADING')
                const cfg = PHASE_STYLE[phaseKey] || PHASE_STYLE.LEADING
                const chgVal = s.change_pct ?? s.change ?? 0
                return (
                  <div
                    key={s.name || s.sector}
                    className="rounded-xl p-2.5 text-center space-y-1 transition-all cursor-pointer hover:scale-105"
                    style={{ background: cfg.bg, border: `1px solid ${cfg.color}33` }}
                    onClick={() => sendDraft(`funnel sector ${(s.name || s.sector).toLowerCase()}`)}
                  >
                    <div className="text-xs font-bold truncate" style={{ color: 'var(--color-text)' }}>{s.name || s.sector}</div>
                    <div className="text-[10px] font-bold" style={{ color: cfg.color }}>{cfg.label.split(' ')[0]}</div>
                    <div className="text-[11px] font-mono font-bold" style={{ color: chgVal >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                      {chgVal >= 0 ? '+' : ''}{Number(chgVal).toFixed(1)}%
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
