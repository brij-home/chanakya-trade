import React from 'react'

export function TradeExecutionMatrix({
  levels,
  isBull,
  isDerivative,
  currentPrice,
  trailingStop,
  slRationale,
  tradePlan,
  marketStatus,
  expiryInfo,
  densityMode = 'compact',
}) {
  const tp = tradePlan || {}
  const mktSt = marketStatus || 'SESSION_CLOSED'

  const formatNum = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '—'
    const num = Number(val)
    return num.toLocaleString('en-IN', {
      minimumFractionDigits: num >= 500 ? 1 : 2,
      maximumFractionDigits: 2,
    })
  }

  const formatPnl = (pnl) => {
    if (pnl === null || pnl === undefined || isNaN(pnl)) return null
    const n = Number(pnl)
    const sign = n >= 0 ? '+' : ''
    return `${sign}₹${n.toLocaleString('en-IN')}`
  }

  let progressPct = 30
  if (currentPrice && levels.sl && levels.t3 && levels.t3 !== levels.sl) {
    const totalSpan = Math.abs(levels.t3 - levels.sl)
    const isUpward = levels.isUpwardPayoff !== undefined ? levels.isUpwardPayoff : (isBull || isDerivative)
    const currentDist = isUpward ? currentPrice - levels.sl : levels.sl - currentPrice
    progressPct = Math.min(100, Math.max(0, Math.round((currentDist / totalSpan) * 100)))
  }

  const mktBadge = mktSt === 'LIVE'
    ? { cls: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/40', label: '🟢 LIVE MARKET' }
    : mktSt === 'PRE_MARKET'
    ? { cls: 'text-amber-400 bg-amber-500/15 border-amber-500/40', label: '🌅 PRE-MARKET' }
    : { cls: 'text-blue-400 bg-blue-500/15 border-blue-500/40', label: '🌙 SESSION CLOSED' }

  const expBadge = expiryInfo?.formatted
    ? `⏳ ${expiryInfo.formatted}${expiryInfo.dte !== null ? ` (${expiryInfo.dte} DTE)` : ''}`
    : expiryInfo?.expiry_date
    ? `⏳ Exp: ${expiryInfo.expiry_date}`
    : null

  return (
    <div className="rounded-xl p-2.5 border border-border/40 bg-surface/80 space-y-2 shadow-sm">
      {/* Execution Matrix Header with Quick Verdict + Market Status */}
      <div className="flex items-center justify-between flex-wrap gap-1.5 pb-1 border-b border-border/30">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-mono">🎯</span>
          <span className="text-[10px] font-black uppercase tracking-wider text-text">
            Trade Execution Matrix & Target Milestones
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold flex-wrap">
          <span className={`px-1.5 py-0.5 rounded border ${mktBadge.cls}`}>
            {mktBadge.label}
          </span>
          {expBadge && (
            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/25">
              {expBadge}
            </span>
          )}
          {levels.t1_rr ? (
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/25">
              T1 R:R {levels.t1_rr}:1
            </span>
          ) : null}
          {levels.t2_rr ? (
            <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/25">
              T2 R:R {levels.t2_rr}:1
            </span>
          ) : null}
          {levels.t3_rr ? (
            <span className="px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/25">
              T3 R:R {levels.t3_rr}:1
            </span>
          ) : null}
        </div>
      </div>

      {/* 5-Column High-Contrast Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 font-mono text-xs">
        {/* 1. STOP LOSS */}
        <div className="p-2 rounded-lg bg-rose-500/5 border border-rose-500/20 hover:border-rose-500/40 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-rose-400">
              🛑 Invalidation SL
            </span>
            <span className="text-[9px] font-bold text-rose-400">
              {levels.sl_pct ? `-${levels.sl_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-rose-300 mt-0.5">
            ₹{formatNum(levels.sl)}
          </div>
          <div className="text-[9px] text-muted block truncate font-sans" title={slRationale}>
            {slRationale || (levels.sl_pts ? `Risk: ₹${formatNum(levels.sl_pts)}` : 'Structural SL')}
          </div>
          {levels.optPlanRef?.sl_pnl_per_lot !== undefined && (
            <div className="text-[8px] font-bold text-rose-400/80">
              {formatPnl(levels.optPlanRef.sl_pnl_per_lot)}
            </div>
          )}
          {trailingStop && (
            <div className="pt-0.5 border-t border-rose-500/20 text-[9px] text-cyan-300 font-bold">
              ⚡ Trailing: ₹{formatNum(trailingStop)}
            </div>
          )}
        </div>

        {/* 2. ENTRY TRIGGER */}
        <div className="p-2 rounded-lg bg-gold/5 border border-gold/25 hover:border-gold/50 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-gold">
              ⚡ Entry Trigger
            </span>
            <span className="text-[9px] font-black px-1 rounded bg-gold/15 text-gold">
              {isBull ? 'BUY' : 'SELL'}
            </span>
          </div>
          <div className="text-sm font-black text-gold mt-0.5">
            ₹{formatNum(levels.entry)}
          </div>
          <div className="text-[9px] text-muted block truncate font-sans">
            {isDerivative ? 'Contract Entry' : 'Spot Breakout Level'}
          </div>
        </div>

        {/* 3. TARGET 1 */}
        <div className="p-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20 hover:border-emerald-500/40 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-emerald-400">
              🎯 Target 1 (T1)
            </span>
            <span className="text-[9px] font-bold text-emerald-400">
              {levels.t1_pct ? `+${levels.t1_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-emerald-300 mt-0.5">
            ₹{formatNum(levels.t1)}
          </div>
          <div className="text-[9px] text-emerald-400/90 block font-sans font-bold">
            {levels.t1_rr ? `${levels.t1_rr}:1 R:R · Book 50%` : 'Book 50%'}
          </div>
          {isDerivative && levels.optPlanRef?.t1_spot && (
            <div className="text-[8px] text-emerald-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t1_spot)}
            </div>
          )}
          {levels.optPlanRef?.t1_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t1_pnl_per_lot || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t1_pnl_per_lot)}
            </div>
          )}
          {tp.eta_t1_str && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate" title={tp.eta_t1_str}>
              ⏱ {tp.eta_t1_str}
            </div>
          )}
        </div>

        {/* 4. TARGET 2 */}
        <div className="p-2 rounded-lg bg-cyan-500/5 border border-cyan-500/20 hover:border-cyan-500/40 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-cyan-400">
              🏁 Target 2 (T2)
            </span>
            <span className="text-[9px] font-bold text-cyan-400">
              {levels.t2_pct ? `+${levels.t2_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-cyan-300 mt-0.5">
            ₹{formatNum(levels.t2)}
          </div>
          <div className="text-[9px] text-cyan-400/90 block font-sans font-bold">
            {levels.t2_rr ? `${levels.t2_rr}:1 R:R · Resistance Wall` : 'Resistance Wall'}
          </div>
          {isDerivative && levels.optPlanRef?.t2_spot && (
            <div className="text-[8px] text-cyan-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t2_spot)}
            </div>
          )}
          {levels.optPlanRef?.t2_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t2_pnl_per_lot || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t2_pnl_per_lot)}
            </div>
          )}
          {tp.eta_t2_str && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate" title={tp.eta_t2_str}>
              ⏱ {tp.eta_t2_str}
            </div>
          )}
        </div>

        {/* 5. TARGET 3 (RUNNER) */}
        <div className="p-2 rounded-lg bg-purple-500/5 border border-purple-500/20 hover:border-purple-500/40 transition-colors col-span-2 sm:col-span-1">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-purple-300">
              🚀 Target 3 (T3)
            </span>
            <span className="text-[9px] font-bold text-purple-300">
              {levels.t3_pct ? `+${levels.t3_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-purple-200 mt-0.5">
            ₹{formatNum(levels.t3)}
          </div>
          <div className="text-[9px] text-purple-300/90 block font-sans font-bold">
            {levels.t3_rr ? `${levels.t3_rr}:1 R:R · Moonshot Runner` : 'Moonshot Runner'}
          </div>
          {isDerivative && levels.optPlanRef?.t3_spot && (
            <div className="text-[8px] text-purple-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t3_spot)}
            </div>
          )}
          {levels.optPlanRef?.t3_pnl_per_lot !== undefined && levels.optPlanRef.t3_pnl_per_lot !== null && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t3_pnl_per_lot || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t3_pnl_per_lot)}
            </div>
          )}
          {tp.eta_t3_str && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate" title={tp.eta_t3_str}>
              ⏱ {tp.eta_t3_str}
            </div>
          )}
        </div>
      </div>

      {/* Visual Trade Runway Progress Tracker */}
      <div className="pt-1.5 border-t border-border/20 space-y-1.5">
        <div className="flex items-center justify-between text-[8px] font-mono text-muted flex-wrap gap-1">
          <span className="text-rose-400 font-bold">🛑 SL ₹{formatNum(levels.sl)}</span>
          <span className="text-gold font-bold">⚡ Entry ₹{formatNum(levels.entry)}</span>
          <span className="text-emerald-400 font-bold">🎯 T1 ₹{formatNum(levels.t1)}</span>
          <span className="text-cyan-400 font-bold">🏁 T2 ₹{formatNum(levels.t2)}</span>
          <span className="text-purple-300 font-bold">🚀 T3 ₹{formatNum(levels.t3)}</span>
        </div>
        <div className="relative w-full h-2 rounded-full bg-surface border border-border/40 overflow-hidden flex items-center shadow-inner">
          <div className="h-full bg-rose-500/30 border-r border-rose-500/60" style={{ width: '20%' }} title="Stop Loss Risk Zone" />
          <div className="h-full bg-gold/30 border-r border-gold/60" style={{ width: '10%' }} title="Entry Zone" />
          <div className="h-full bg-emerald-500/25 border-r border-emerald-500/60" style={{ width: '30%' }} title="T1 Profit Zone" />
          <div className="h-full bg-cyan-500/25 border-r border-cyan-500/60" style={{ width: '20%' }} title="T2 Expansion Zone" />
          <div className="h-full bg-purple-500/25" style={{ width: '20%' }} title="T3 Runner Moonshot Zone" />
          {currentPrice ? (
            <div
              className="absolute top-0 bottom-0 w-2.5 -ml-1.25 bg-white rounded-full shadow-[0_0_8px_rgba(255,255,255,0.8)] border border-gold"
              style={{ left: `${progressPct}%` }}
              title={`Live Price Position: ₹${formatNum(currentPrice)} (${progressPct}% runway)`}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}
