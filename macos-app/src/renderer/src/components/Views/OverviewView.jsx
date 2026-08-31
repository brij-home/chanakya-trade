import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'
import SkeletonCard from '../Loading/SkeletonCard'

/* ── Data ─────────────────────────────────────────────────────────────── */
const GLOBAL_MARKETS = [
  { label: 'SGX Nifty',  value: 24190, change: +0.38, flag: '🇸🇬' },
  { label: 'Dow Jones',  value: 44089, change: +0.22, flag: '🇺🇸' },
  { label: 'NASDAQ',     value: 19350, change: +0.55, flag: '🇺🇸' },
  { label: 'USD/INR',    value: 83.82,  change: -0.05, flag: '💱' },
  { label: 'Crude Oil',  value: 78.4,  change: -0.80, flag: '🛢️' },
  { label: 'Gold',       value: 2618,  change: +0.40, flag: '🥇' },
]

const SECTORS_MOCK = [
  { name: 'IT',          rsi: 71, change: +2.1, phase: 'LEADING' },
  { name: 'Banking',     rsi: 58, change: +0.8, phase: 'LEADING' },
  { name: 'FMCG',        rsi: 48, change: -0.3, phase: 'WEAKENING' },
  { name: 'Auto',        rsi: 63, change: +1.5, phase: 'LEADING' },
  { name: 'Pharma',      rsi: 54, change: +0.2, phase: 'IMPROVING' },
  { name: 'Realty',      rsi: 44, change: -0.9, phase: 'LAGGING' },
  { name: 'Energy',      rsi: 67, change: +1.2, phase: 'LEADING' },
  { name: 'Metal',       rsi: 41, change: -1.4, phase: 'LAGGING' },
  { name: 'Defence',     rsi: 72, change: +2.8, phase: 'LEADING' },
  { name: 'PSU Bank',    rsi: 62, change: +1.1, phase: 'IMPROVING' },
  { name: 'Infra',       rsi: 56, change: +0.5, phase: 'IMPROVING' },
  { name: 'Chemical',    rsi: 49, change: -0.2, phase: 'WEAKENING' },
]

const PHASE_STYLE = {
  LEADING:    { color: 'var(--color-emerald)', bg: 'rgba(0,214,143,0.12)', label: '▲ LEADING' },
  WEAKENING:  { color: 'var(--color-gold)',    bg: 'rgba(245,166,35,0.12)', label: '◤ WEAKENING' },
  LAGGING:    { color: 'var(--color-rose)',    bg: 'rgba(255,79,123,0.12)', label: '▼ LAGGING' },
  IMPROVING:  { color: 'var(--color-sapphire)',bg: 'rgba(77,155,255,0.12)', label: '◢ IMPROVING' },
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

/** India VIX arc gauge */
function VIXGauge({ value = 12.8 }) {
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
  const total = advancing + declining + unchanged
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
  const pct = Math.abs(value) / max * 100
  const color = isPos ? 'var(--color-emerald)' : 'var(--color-rose)'
  return (
    <div className="flex items-center gap-3">
      <span className="text-[10px] font-mono w-16 text-right flex-shrink-0" style={{ color: 'var(--color-muted)' }}>{label}</span>
      <div className="flex-1 relative h-5 rounded-lg overflow-hidden" style={{ background: 'var(--color-elevated)' }}>
        <div
          className="absolute top-0 bottom-0 rounded-lg transition-all"
          style={{
            width: `${pct}%`,
            background: color,
            opacity: 0.8,
            left: isPos ? '50%' : `${50 - pct}%`,
          }}
        />
        <div className="absolute inset-0 flex items-center justify-center text-[10px] font-mono font-bold" style={{ color: 'var(--color-text)' }}>
          {isPos ? '+' : ''}₹{Math.abs(value).toLocaleString('en-IN')} Cr
        </div>
      </div>
    </div>
  )
}

/* ── Main View ───────────────────────────────────────────────────────────── */
export default function OverviewView() {
  const { call } = useAPI()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let unmounted = false
    const fetchData = async () => {
      try {
        setLoading(true)
        const res = await call('/skills/market_overview')
        if (!unmounted && res) setData(res?.data ?? res)
      } catch { /* use mock data */ } finally {
        if (!unmounted) setLoading(false)
      }
    }
    fetchData()
    return () => { unmounted = true }
  }, [])

  const vix = data?.vix ?? 12.8
  const fiiNet = data?.fii_net ?? -1240
  const diiNet = data?.dii_net ?? 1840
  const advancers = data?.advancers ?? 285
  const decliners = data?.decliners ?? 165
  const unchanged = data?.unchanged ?? 50

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-black" style={{ color: 'var(--color-text)' }}>🌐 Market Overview</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            India VIX • FII/DII Flows • Breadth • Sector Rotation • Global Markets
          </p>
        </div>
        <div
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold"
          style={{ background: 'rgba(0,214,143,0.12)', border: '1px solid rgba(0,214,143,0.3)', color: 'var(--color-emerald)' }}
        >
          <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--color-emerald)' }} />
          Live Market Context
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[1,2,3].map(i => <SkeletonCard key={i} variant="card" lines={4} />)}
        </div>
      ) : (
        <>
          {/* Row 1: VIX + Breadth + FII/DII */}
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

          {/* Row 2: Sector Rotation Grid */}
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
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
              {SECTORS_MOCK.map((s) => {
                const cfg = PHASE_STYLE[s.phase]
                return (
                  <div
                    key={s.name}
                    className="rounded-xl p-2.5 text-center space-y-1 transition-all cursor-pointer hover:scale-105"
                    style={{ background: cfg.bg, border: `1px solid ${cfg.color}33` }}
                    onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: s.name } }))}
                  >
                    <div className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>{s.name}</div>
                    <div className="text-[10px] font-bold" style={{ color: cfg.color }}>{cfg.label.split(' ')[0]}</div>
                    <div className="text-[11px] font-mono font-bold" style={{ color: s.change >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                      {s.change >= 0 ? '+' : ''}{s.change}%
                    </div>
                    <div className="text-[9px]" style={{ color: 'var(--color-muted)' }}>RSI {s.rsi}</div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Row 3: Global Markets */}
          <div
            className="rounded-2xl p-4 animate-slide-up-fade"
            style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)', animationDelay: '200ms' }}
          >
            <div className="text-[10px] font-bold uppercase tracking-wider mb-3" style={{ color: 'var(--color-muted)' }}>
              🌍 Global Markets
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {GLOBAL_MARKETS.map((m) => (
                <div
                  key={m.label}
                  className="rounded-xl p-3 space-y-1 transition-all hover:scale-105"
                  style={{
                    background: 'var(--color-elevated)',
                    border: `1px solid ${m.change >= 0 ? 'rgba(0,214,143,0.25)' : 'rgba(255,79,123,0.25)'}`,
                  }}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-base">{m.flag}</span>
                    <span className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>{m.label}</span>
                  </div>
                  <div className="text-sm font-mono font-bold" style={{ color: 'var(--color-text)' }}>
                    {m.value.toLocaleString('en-IN')}
                  </div>
                  <div
                    className="text-[11px] font-mono font-bold"
                    style={{ color: m.change >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)' }}
                  >
                    {m.change >= 0 ? '+' : ''}{m.change}%
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
