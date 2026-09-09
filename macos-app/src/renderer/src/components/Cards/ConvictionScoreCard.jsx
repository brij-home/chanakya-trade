import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'

/**
 * ConvictionScoreCard
 *
 * Displays the 12-Factor Orthogonal High-Conviction Trade Signal Score (0–100)
 * across 5 independent axes:
 *   1. Institutional Money (FII/DII Cash Flow, FII 5D Positioning)
 *   2. Macro & Global Regime (GIFT NIFTY / Global Macro, India VIX Direction & Level)
 *   3. Options Market Intelligence (GEX Dealer Posture, PCR Contrarian Gate, IV Skew)
 *   4. Price Structure & Map (SMC Market Structure, Max Pain Expiry Gravity)
 *   5. Timing & Real-Time Flow (Sector RRG Momentum, Event Calendar, Blast Signal)
 *
 * Includes hard-stop VETO enforcement (VIX > 25, extreme FII dumping, stale options chain).
 */

const AXIS_META = {
  INSTITUTIONAL: { label: 'Institutional Flow', icon: '🏛️', color: 'text-indigo-400', border: 'border-indigo-500/30', bg: 'bg-indigo-950/30' },
  MACRO: { label: 'Macro Regime', icon: '🌐', color: 'text-sky-400', border: 'border-sky-500/30', bg: 'bg-sky-950/30' },
  OPTIONS: { label: 'Options Intel', icon: '⚡', color: 'text-amber-400', border: 'border-amber-500/30', bg: 'bg-amber-950/30' },
  PRICE: { label: 'Price Structure', icon: '📊', color: 'text-emerald-400', border: 'border-emerald-500/30', bg: 'bg-emerald-950/30' },
  TIMING: { label: 'Timing & Flow', icon: '⏱️', color: 'text-purple-400', border: 'border-purple-500/30', bg: 'bg-purple-950/30' },
}

export default function ConvictionScoreCard({
  underlying = 'NIFTY',
  spot = 0,
  pcr = null,
  blastRadar = [],
  convictionScore = null,
}) {
  const { call } = useAPI()
  const [score, setScore] = useState(convictionScore)
  const [loading, setLoading] = useState(!convictionScore)
  const [expanded, setExpanded] = useState(false)
  const [selectedAxis, setSelectedAxis] = useState('ALL')

  // Use injected conviction score if provided; otherwise fetch independently
  useEffect(() => {
    if (convictionScore) {
      setScore(convictionScore)
      setLoading(false)
      return
    }
    if (!underlying) return

    const fetchScore = async () => {
      setLoading(true)
      try {
        const topBlast = blastRadar?.[0]
        const res = await call('/skills/conviction_score', {
          underlying,
          spot: spot > 0 ? spot : undefined,
          pcr: pcr ?? undefined,
          blast_score: topBlast?.score ?? undefined,
          vol_oi_ratio: topBlast?.vol_oi_ratio ?? undefined,
          imbalance_ratio: topBlast?.imbalance_ratio ?? undefined,
        })
        if (res?.data) {
          setScore(res.data)
        }
      } catch (e) {
        console.error('ConvictionScoreCard fetch error:', e)
      } finally {
        setLoading(false)
      }
    }

    fetchScore()
  }, [convictionScore, underlying, spot, pcr])

  // Use convictionScore prop directly when it updates (from GEX snapshot)
  useEffect(() => {
    if (convictionScore) {
      setScore(convictionScore)
      setLoading(false)
    }
  }, [convictionScore])

  if (loading) {
    return (
      <div className="p-3 rounded-2xl border border-border/40 bg-elevated/40 animate-pulse">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-4 h-4 rounded-full bg-border/40" />
          <div className="h-3 w-36 rounded bg-border/40" />
          <div className="ml-auto h-8 w-8 rounded-full bg-border/40" />
        </div>
        <div className="h-2 w-full rounded bg-border/30 mt-2" />
        <div className="h-2 w-3/4 rounded bg-border/20 mt-1.5" />
      </div>
    )
  }

  if (!score) return null

  const total = score.total_score ?? 0
  const verdict = score.verdict ?? 'WAIT'
  const summary = score.summary ?? ''
  const factors = score.factors ?? []
  const posSize = score.recommended_position_size ?? 'FLAT'
  const veto = score.veto

  // Color palettes per verdict
  const verdictStyles = {
    MAX_CONVICTION: {
      ring: 'ring-emerald-400/60',
      text: 'text-emerald-400',
      bg: 'bg-emerald-950/25',
      border: 'border-emerald-500/40',
      glow: '0 0 28px -6px rgba(52, 211, 153, 0.55)',
      badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
      gauge: '#10b981',
    },
    HIGH: {
      ring: 'ring-cyan-400/60',
      text: 'text-cyan-400',
      bg: 'bg-cyan-950/20',
      border: 'border-cyan-500/40',
      glow: '0 0 24px -6px rgba(6, 182, 212, 0.45)',
      badge: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
      gauge: '#06b6d4',
    },
    MODERATE: {
      ring: 'ring-amber-400/60',
      text: 'text-amber-400',
      bg: 'bg-amber-950/20',
      border: 'border-amber-500/40',
      glow: '0 0 20px -6px rgba(251, 191, 36, 0.35)',
      badge: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
      gauge: '#f59e0b',
    },
    WAIT: {
      ring: 'ring-rose-400/60',
      text: 'text-rose-400',
      bg: 'bg-rose-950/15',
      border: 'border-rose-500/40',
      glow: '0 0 18px -6px rgba(244, 63, 94, 0.35)',
      badge: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
      gauge: '#f43f5e',
    },
  }

  const vs = verdictStyles[verdict] ?? verdictStyles['WAIT']

  // Circular gauge math
  const GAUGE_R = 28
  const GAUGE_CIRC = 2 * Math.PI * GAUGE_R
  const fillPct = Math.min(1, Math.max(0, total / 100))
  const strokeDash = fillPct * GAUGE_CIRC
  const strokeGap = GAUGE_CIRC - strokeDash

  const factorSignalBadge = (signal) => {
    if (signal === 'BULLISH') return 'text-emerald-400'
    if (signal === 'BEARISH') return 'text-rose-400'
    if (signal === 'UNAVAILABLE') return 'text-muted'
    return 'text-amber-400'
  }

  const factorSignalIcon = (signal) => {
    if (signal === 'BULLISH') return '▲'
    if (signal === 'BEARISH') return '▼'
    if (signal === 'UNAVAILABLE') return '—'
    return '●'
  }

  const posSizeBadge = {
    '2X': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
    NORMAL: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
    HALF: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
    FLAT: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
  }

  // Filter factors if axis selected
  const displayedFactors = selectedAxis === 'ALL'
    ? factors
    : factors.filter((f) => f.axis === selectedAxis)

  // Axis score stats
  const axesPresent = ['INSTITUTIONAL', 'MACRO', 'OPTIONS', 'PRICE', 'TIMING']

  return (
    <div
      className={`rounded-2xl border ${vs.border} ${vs.bg} transition-all duration-300 overflow-hidden`}
      style={{ boxShadow: vs.glow }}
    >
      {/* Header */}
      <div
        className="p-3 flex items-center gap-3 cursor-pointer select-none"
        onClick={() => setExpanded((p) => !p)}
        role="button"
        tabIndex={0}
        title="Click to toggle 12-factor orthogonal breakdown"
      >
        {/* Circular Gauge */}
        <div className="relative shrink-0">
          <svg width="68" height="68" viewBox="0 0 68 68">
            {/* Track */}
            <circle
              cx="34"
              cy="34"
              r={GAUGE_R}
              fill="none"
              stroke="rgba(255,255,255,0.06)"
              strokeWidth="6"
            />
            {/* Fill */}
            <circle
              cx="34"
              cy="34"
              r={GAUGE_R}
              fill="none"
              stroke={vs.gauge}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${strokeDash} ${strokeGap}`}
              strokeDashoffset={GAUGE_CIRC * 0.25}
              style={{ transition: 'stroke-dasharray 0.8s cubic-bezier(0.4, 0, 0.2, 1)' }}
            />
            {/* Score text */}
            <text x="34" y="38" textAnchor="middle" fill="white" fontSize="15" fontWeight="800" fontFamily="monospace">
              {total}
            </text>
          </svg>
        </div>

        {/* Labels & Verdict Badges */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1 flex-wrap">
            <span className={`text-[9px] font-black px-1.5 py-0.5 rounded border ${vs.badge} tracking-wide uppercase`}>
              {verdict === 'MAX_CONVICTION' ? '🔥 MAX CONVICTION' :
               verdict === 'HIGH' ? '✅ HIGH CONVICTION' :
               verdict === 'MODERATE' ? '⚠️ MODERATE' : '🛑 WAIT / STAND DOWN'}
            </span>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${posSizeBadge[posSize] ?? posSizeBadge.FLAT}`}>
              {posSize === '2X' ? '⚡ 2× Sizing' :
               posSize === 'NORMAL' ? '✓ Normal Sizing' :
               posSize === 'HALF' ? '½ Sizing' : 'Flat / No Trade'}
            </span>
            {veto?.vetoed && (
              <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/50 uppercase tracking-wider animate-pulse">
                ⛔ Veto Active
              </span>
            )}
            <span className="ml-auto text-[9px] text-muted font-mono">{score.as_of}</span>
          </div>

          <div className="flex items-center gap-1.5 text-[9px] font-mono">
            <span className="text-emerald-400 font-bold">{score.bullish_count}▲ Bullish</span>
            <span className="text-muted">/</span>
            <span className="text-rose-400 font-bold">{score.bearish_count}▼ Bearish</span>
            <span className="text-muted">/</span>
            <span className="text-muted">{score.unavailable_count}— Neutral</span>
            <span className="text-muted/60 text-[8px] ml-auto font-sans font-semibold">12-Factor Orthogonal Engine</span>
          </div>

          <p className={`text-[10px] ${vs.text} font-medium font-ui leading-snug mt-1 line-clamp-2`}>
            {summary}
          </p>
        </div>

        {/* Expand toggle */}
        <div className="flex items-center gap-1 text-[10px] font-mono text-muted shrink-0 pl-1">
          <span className="hidden sm:inline text-[9px] uppercase tracking-wider">
            {expanded ? 'Hide Axes' : 'View 5 Axes'}
          </span>
          <span className={`text-xs ${vs.text} transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}>
            ▼
          </span>
        </div>
      </div>

      {/* Veto Alert Banner if active */}
      {veto?.vetoed && (
        <div className="mx-3 mb-2 p-2 rounded-xl bg-rose-500/15 border border-rose-500/40 flex items-start gap-2 text-rose-300 text-[10px] leading-tight">
          <span className="text-xs shrink-0">⛔</span>
          <div>
            <div className="font-black tracking-wide uppercase text-[9px] text-rose-400">Institutional Safety Veto Enforced</div>
            <div className="mt-0.5 opacity-90">{veto.reason} (Score capped at 55)</div>
          </div>
        </div>
      )}

      {/* Factor Breakdown (expandable) */}
      {expanded && factors.length > 0 && (
        <div className="px-3 pb-3 space-y-2.5 border-t border-border/30 pt-2.5 bg-surface/30">
          {/* Data-Driven Trade Plan & ETA Section */}
          {score.trade_plan && (
            <div className="p-3 rounded-xl bg-elevated/50 border border-border/50 space-y-2.5">
              <div className="flex items-center justify-between flex-wrap gap-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-black uppercase tracking-wider text-text flex items-center gap-1">
                    <span>📐</span> Data-Driven Trade Plan
                  </span>
                  <span className={`text-[8px] font-black px-1.5 py-0.2 rounded border uppercase ${
                    score.trade_plan.direction === 'LONG'
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                      : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                  }`}>
                    {score.trade_plan.direction}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${
                    score.trade_plan.is_asymmetry_viable
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                      : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  }`}>
                    ⚖️ R:R {score.trade_plan.rr_t2}:1
                  </span>
                  <span className="text-[9px] font-mono text-muted">
                    Entry: ₹{score.trade_plan.entry_price?.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
                  </span>
                </div>
              </div>

              {/* Levels Grid: Invalidation (SL) vs Targets */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[10px]">
                {/* Invalidation Stop-Loss */}
                <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/20">
                  <div className="flex items-center justify-between text-rose-400 font-bold text-[9px] uppercase">
                    <span>🛑 Invalidation (SL)</span>
                    <span className="font-mono">-{score.trade_plan.stop_distance_pts} pts</span>
                  </div>
                  <div className="font-mono font-black text-sm text-text mt-0.5">
                    ₹{score.trade_plan.invalidation_stop?.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
                  </div>
                  <div className="text-[8px] text-muted leading-tight mt-1 line-clamp-2">
                    {score.trade_plan.sl_rationale}
                  </div>
                </div>

                {/* Target 1 (Friction Point) */}
                <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
                  <div className="flex items-center justify-between text-cyan-400 font-bold text-[9px] uppercase">
                    <span>🎯 Target 1 ({score.trade_plan.rr_t1}:1 R:R)</span>
                    <span className="font-mono">+{score.trade_plan.t1_distance_pts} pts</span>
                  </div>
                  <div className="font-mono font-black text-sm text-text mt-0.5">
                    ₹{score.trade_plan.target_1?.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
                  </div>
                  <div className="flex items-center gap-1 text-[8px] font-mono text-cyan-300/80 mt-1">
                    <span>⏱️ ETA: {score.trade_plan.eta_t1_str}</span>
                  </div>
                  <div className="text-[8px] text-muted leading-tight mt-0.5 line-clamp-1">
                    {score.trade_plan.t1_rationale}
                  </div>
                </div>

                {/* Target 2 (Liquidity Expansion) */}
                <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                  <div className="flex items-center justify-between text-emerald-400 font-bold text-[9px] uppercase">
                    <span>🚀 Target 2 ({score.trade_plan.rr_t2}:1 R:R)</span>
                    <span className="font-mono">+{score.trade_plan.t2_distance_pts} pts</span>
                  </div>
                  <div className="font-mono font-black text-sm text-text mt-0.5">
                    ₹{score.trade_plan.target_2?.toLocaleString('en-IN', { minimumFractionDigits: 1 })}
                  </div>
                  <div className="flex items-center gap-1 text-[8px] font-mono text-emerald-300/80 mt-1">
                    <span>⏱️ ETA: {score.trade_plan.eta_t2_str}</span>
                  </div>
                  <div className="text-[8px] text-muted leading-tight mt-0.5 line-clamp-1">
                    {score.trade_plan.t2_rationale}
                  </div>
                </div>
              </div>

              {/* ETA, Clock & Options Friction Insights */}
              <div className="pt-1.5 border-t border-border/30 flex flex-col gap-1 text-[9px]">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-muted font-mono">
                    ATR Velocity: <b className="text-text">{score.trade_plan.velocity_pts_per_bar} pts/5m bar</b>
                  </span>
                  <span className="text-muted font-mono">•</span>
                  <span className="text-muted">
                    Session Clock: <b className={score.trade_plan.session_overrun_risk ? 'text-amber-400' : 'text-text'}>{score.trade_plan.session_clock_note}</b>
                  </span>
                </div>
                {score.trade_plan.structure_advice && (
                  <div className="text-[9px] text-text/80 bg-surface/40 p-1.5 rounded border border-border/30 flex items-start gap-1.5">
                    <span className="text-xs">🛡️</span>
                    <div className="flex-1">
                      <span className="font-bold text-primary mr-1">Structure Guidance:</span>
                      {score.trade_plan.structure_advice}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Axis Filter Pills */}
          <div className="flex items-center gap-1 overflow-x-auto pb-1 text-[9px] scrollbar-none">
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setSelectedAxis('ALL'); }}
              className={`px-2 py-0.5 rounded-full border transition-all ${
                selectedAxis === 'ALL'
                  ? 'bg-primary text-primary-foreground border-primary font-bold shadow-xs'
                  : 'bg-elevated/40 text-muted border-border/40 hover:text-text'
              }`}
            >
              All 12 Factors
            </button>
            {axesPresent.map((ax) => {
              const meta = AXIS_META[ax]
              const count = factors.filter((f) => f.axis === ax).length
              return (
                <button
                  key={ax}
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setSelectedAxis(ax); }}
                  className={`px-2 py-0.5 rounded-full border transition-all flex items-center gap-1 whitespace-nowrap ${
                    selectedAxis === ax
                      ? `${meta.bg} ${meta.color} ${meta.border} font-bold shadow-xs`
                      : 'bg-elevated/40 text-muted border-border/40 hover:text-text'
                  }`}
                >
                  <span>{meta.icon}</span>
                  <span>{meta.label}</span>
                  <span className="text-[8px] opacity-70">({count})</span>
                </button>
              )
            })}
          </div>

          {/* Factor List */}
          <div className="space-y-1.5">
            {displayedFactors.map((f, idx) => {
              const meta = AXIS_META[f.axis] || AXIS_META.TIMING
              return (
                <div
                  key={f.factor_id || idx}
                  className="p-2 rounded-xl bg-elevated/30 border border-border/30 hover:border-border/60 transition-colors flex items-start gap-2.5 text-[10px]"
                >
                  {/* Score bar & Signal */}
                  <div className="shrink-0 flex flex-col items-center gap-1 w-14">
                    <div className="flex items-center gap-1">
                      <span className={`text-[11px] font-black ${factorSignalBadge(f.signal)}`}>
                        {factorSignalIcon(f.signal)}
                      </span>
                      <span className="font-mono font-black text-[11px] text-text">
                        {f.score}<span className="text-[8px] text-muted font-normal">/10</span>
                      </span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-surface overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          f.score >= 7 ? 'bg-emerald-500' :
                          f.score >= 5 ? 'bg-amber-500' : 'bg-rose-500'
                        }`}
                        style={{ width: `${(f.score / 10) * 100}%` }}
                      />
                    </div>
                  </div>

                  {/* Factor Details */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-bold text-text text-[10px]">
                        {f.label}
                      </span>
                      <span className={`text-[8px] font-bold px-1 py-0.2 rounded border ${meta.border} ${meta.bg} ${meta.color}`}>
                        {meta.icon} {meta.label}
                      </span>
                      <span className={`text-[8px] font-bold uppercase ml-auto ${factorSignalBadge(f.signal)}`}>
                        {f.signal}
                      </span>
                    </div>
                    {f.detail && (
                      <div className="text-muted text-[9px] leading-relaxed mt-0.5">
                        {f.detail}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Institutional Calibration Guide */}
          <div className="pt-2 border-t border-border/30 grid grid-cols-4 gap-1 text-[8px] font-mono text-center">
            <div className="p-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <div className="font-black text-[9px]">85–100</div>
              <div className="text-muted font-sans font-semibold">2× Size</div>
            </div>
            <div className="p-1 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
              <div className="font-black text-[9px]">70–84</div>
              <div className="text-muted font-sans font-semibold">Normal</div>
            </div>
            <div className="p-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <div className="font-black text-[9px]">50–69</div>
              <div className="text-muted font-sans font-semibold">½ Size</div>
            </div>
            <div className="p-1 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400">
              <div className="font-black text-[9px]">{'<'}50</div>
              <div className="text-muted font-sans font-semibold">Stand Down</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
