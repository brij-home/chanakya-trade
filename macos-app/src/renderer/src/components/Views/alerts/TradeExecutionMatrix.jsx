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

  const isUpward = levels.isUpwardPayoff !== undefined ? levels.isUpwardPayoff : (isBull || isDerivative)

  // Stage Hit Real-time Calculations
  const isSLHit = Boolean(
    levels.is_invalidated ||
    (levels.sl && currentPrice && (isUpward ? currentPrice <= levels.sl : currentPrice >= levels.sl))
  )

  const isT3Hit = Boolean(
    levels.t3 && currentPrice && !isSLHit && (isUpward ? currentPrice >= levels.t3 : currentPrice <= levels.t3)
  )

  const isT2Hit = Boolean(
    isT3Hit ||
    (levels.t2 && currentPrice && !isSLHit && (isUpward ? currentPrice >= levels.t2 : currentPrice <= levels.t2))
  )

  const isT1Hit = Boolean(
    isT2Hit ||
    (levels.t1 && currentPrice && !isSLHit && (isUpward ? currentPrice >= levels.t1 : currentPrice <= levels.t1))
  )

  // Active Target Stage in Flight
  const activeStage = isSLHit ? 'SL' : isT3Hit ? 'T3_DONE' : isT2Hit ? 'T3' : isT1Hit ? 'T2' : 'T1'

  // Distance & Progress to Active Stage
  let t1DistInfo = null
  if (levels.entry && levels.t1 && currentPrice && !isSLHit && !isT1Hit) {
    const total = Math.abs(levels.t1 - levels.entry)
    const current = Math.abs(currentPrice - levels.entry)
    const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((current / total) * 100))) : 0
    const remPts = Math.abs(levels.t1 - currentPrice)
    t1DistInfo = { pct, remPts }
  }

  let t2DistInfo = null
  if (levels.t1 && levels.t2 && currentPrice && isT1Hit && !isT2Hit) {
    const total = Math.abs(levels.t2 - levels.t1)
    const current = Math.abs(currentPrice - levels.t1)
    const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((current / total) * 100))) : 0
    const remPts = Math.abs(levels.t2 - currentPrice)
    t2DistInfo = { pct, remPts }
  }

  let t3DistInfo = null
  if (levels.t2 && levels.t3 && currentPrice && isT2Hit && !isT3Hit) {
    const total = Math.abs(levels.t3 - levels.t2)
    const current = Math.abs(currentPrice - levels.t2)
    const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((current / total) * 100))) : 0
    const remPts = Math.abs(levels.t3 - currentPrice)
    t3DistInfo = { pct, remPts }
  }

  // Visual Runway Progress Percentage
  let progressPct = 30
  if (currentPrice && levels.sl && levels.t3 && levels.t3 !== levels.sl) {
    const totalSpan = Math.abs(levels.t3 - levels.sl)
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
    <div className={`rounded-xl p-2.5 border transition-all duration-200 bg-surface/80 space-y-2 shadow-sm ${
      isSLHit ? 'border-rose-500/40 bg-rose-500/5' : isT3Hit ? 'border-purple-500/40 bg-purple-500/5' : isT2Hit ? 'border-cyan-500/40 bg-cyan-500/5' : isT1Hit ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-border/40'
    }`}>
      {/* Execution Matrix Header with Quick Verdict + Milestone Status */}
      <div className="flex items-center justify-between flex-wrap gap-1.5 pb-1 border-b border-border/30">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-mono">
            {isSLHit ? '🛑' : isT3Hit ? '🚀' : isT2Hit ? '🏁' : isT1Hit ? '🎯' : '⚡'}
          </span>
          <span className="text-[10px] font-black uppercase tracking-wider text-text">
            Trade Execution Matrix & Target Milestones
          </span>
          {/* Real-time Status Pill */}
          {isSLHit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-rose-500/25 text-rose-300 border border-rose-500/50 animate-pulse">
              🛑 STOP LOSS HIT
            </span>
          ) : isT3Hit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-purple-500/25 text-purple-200 border border-purple-400/50 animate-pulse">
              🚀 ALL TARGETS HIT (MAX PROFIT)
            </span>
          ) : isT2Hit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-cyan-500/25 text-cyan-200 border border-cyan-400/50 animate-pulse">
              🏁 T2 HIT · RUNNER IN FLIGHT TO T3
            </span>
          ) : isT1Hit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 animate-pulse">
              🎯 T1 HIT · 50% BOOKED · SL RISK-FREE
            </span>
          ) : currentPrice && levels.entry ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-gold/15 text-gold border border-gold/30">
              ⚡ ACTIVE TRADE · IN FLIGHT TO T1
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold flex-wrap">
          <span className={`px-1.5 py-0.5 rounded border ${mktBadge.cls}`}>
            {mktBadge.label}
          </span>
          {levels.time_horizon && (
            <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/25">
              ⏱️ {levels.time_horizon === 'INTRADAY' ? 'INTRADAY' : levels.time_horizon === 'SWING_SHORT' ? '2-5D SWING' : levels.time_horizon === 'SWING_MID' ? '1-4W SWING' : 'POSITIONAL'}
            </span>
          )}
          {levels.order_flow_signals?.live_broker_connected === false || levels.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' ? (
            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/25" title="No active broker WebSocket depth connection. Using tick-level fallback.">
              ⚠️ SYNTHETIC L1
            </span>
          ) : (levels.order_flow_signals?.live_broker_connected || levels.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/25" title="Live Broker Level 2 depth active">
              🟢 LIVE L2
            </span>
          ) : null}
          {expBadge && (
            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/25">
              {expBadge}
            </span>
          )}
        </div>
      </div>

      {/* 5-Column High-Contrast Interactive Stage Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 font-mono text-xs">
        {/* 1. STOP LOSS COLUMN (Crimson Glow when Hit) */}
        <div className={`p-2 rounded-lg transition-all duration-200 ${
          isSLHit
            ? 'bg-rose-500/25 border-2 border-rose-500 ring-2 ring-rose-500/40 shadow-[0_0_12px_rgba(244,63,94,0.3)] animate-pulse'
            : 'bg-rose-500/5 border border-rose-500/20 hover:border-rose-500/40'
        }`}>
          <div className="flex items-center justify-between">
            <span className={`text-[9px] font-black uppercase tracking-wider ${isSLHit ? 'text-rose-200' : 'text-rose-400'}`}>
              🛑 Invalidation SL
            </span>
            <span className={`text-[9px] font-bold ${isSLHit ? 'text-rose-100 bg-rose-600/60 px-1 rounded' : 'text-rose-400'}`}>
              {isSLHit ? 'BREACHED' : levels.sl_pct ? `-${levels.sl_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-sm font-black mt-0.5 ${isSLHit ? 'text-white' : 'text-rose-300'}`}>
            ₹{formatNum(levels.sl)}
          </div>
          <div className={`text-[9px] block truncate font-sans ${isSLHit ? 'text-rose-200 font-bold' : 'text-muted'}`} title={slRationale}>
            {isSLHit ? '❌ Stop Loss Hit' : (slRationale || (levels.sl_pts ? `Risk: ₹${formatNum(levels.sl_pts)}` : 'Structural SL'))}
          </div>
          {levels.optPlanRef?.sl_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${isSLHit ? 'text-rose-200' : 'text-rose-400/80'}`}>
              {formatPnl(levels.optPlanRef.sl_pnl_per_lot)}
            </div>
          )}
          {trailingStop && (
            <div className="pt-0.5 border-t border-rose-500/20 text-[9px] text-cyan-300 font-bold">
              ⚡ Trailing: ₹{formatNum(trailingStop)}
            </div>
          )}
        </div>

        {/* 2. ENTRY TRIGGER COLUMN */}
        <div className={`p-2 rounded-lg transition-all duration-200 ${
          currentPrice && !isSLHit
            ? 'bg-gold/15 border border-gold/50 shadow-sm'
            : 'bg-gold/5 border border-gold/25 hover:border-gold/50'
        }`}>
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-gold">
              ⚡ Entry Trigger
            </span>
            <span className="text-[9px] font-black px-1 rounded bg-gold/20 text-gold border border-gold/30">
              {isBull ? 'BUY' : 'SELL'}
            </span>
          </div>
          <div className="text-sm font-black text-gold mt-0.5">
            ₹{formatNum(levels.entry)}
          </div>
          <div className="text-[9px] text-muted block truncate font-sans">
            {isDerivative ? 'Contract Entry' : 'Spot Breakout Level'}
          </div>
          {levels.no_chase_boundary && (
            <div className="pt-0.5 border-t border-gold/20 text-[8px] text-amber-700 dark:text-amber-300 font-bold truncate" title="Do not chase beyond this level">
              🛑 Max ₹{formatNum(levels.no_chase_boundary)}
            </div>
          )}
        </div>

        {/* 3. TARGET 1 COLUMN (Emerald Glow when Hit) */}
        <div className={`p-2 rounded-lg transition-all duration-200 ${
          isT1Hit
            ? 'bg-emerald-500/25 border-2 border-emerald-400 ring-2 ring-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.3)] animate-pulse'
            : activeStage === 'T1'
            ? 'bg-emerald-500/10 border border-emerald-500/40 ring-1 ring-emerald-500/30'
            : 'bg-emerald-500/5 border border-emerald-500/20 hover:border-emerald-500/40'
        }`}>
          <div className="flex items-center justify-between">
            <span className={`text-[9px] font-black uppercase tracking-wider ${isT1Hit ? 'text-emerald-200' : 'text-emerald-400'}`}>
              🎯 Target 1 (T1)
            </span>
            <span className={`text-[9px] font-bold ${isT1Hit ? 'text-emerald-100 bg-emerald-600/70 px-1 rounded shadow-sm' : 'text-emerald-400'}`}>
              {isT1Hit ? '✅ HIT!' : levels.t1_pct ? `+${levels.t1_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-sm font-black mt-0.5 ${isT1Hit ? 'text-white' : 'text-emerald-300'}`}>
            ₹{formatNum(levels.t1)}
          </div>
          <div className={`text-[9px] block font-sans font-bold ${isT1Hit ? 'text-emerald-200' : 'text-emerald-400/90'}`}>
            {isT1Hit ? '✅ 50% Booked · SL Breakeven' : levels.t1_rr ? `${levels.t1_rr}:1 R:R · Book 50%` : 'Book 50%'}
          </div>
          {t1DistInfo && (
            <div className="text-[8px] text-emerald-300 font-bold">
              ⚡ {t1DistInfo.pct}% to T1 (₹{formatNum(t1DistInfo.remPts)} away)
            </div>
          )}
          {isDerivative && levels.optPlanRef?.t1_spot && (
            <div className="text-[8px] text-emerald-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t1_spot)}
            </div>
          )}
          {levels.optPlanRef?.t1_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t1_pnl_per_lot || 0) >= 0 ? 'text-emerald-300' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t1_pnl_per_lot)}
            </div>
          )}
        </div>

        {/* 4. TARGET 2 COLUMN (Cyan Glow when Hit) */}
        <div className={`p-2 rounded-lg transition-all duration-200 ${
          isT2Hit
            ? 'bg-cyan-500/25 border-2 border-cyan-400 ring-2 ring-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.3)] animate-pulse'
            : activeStage === 'T2'
            ? 'bg-cyan-500/10 border border-cyan-500/40 ring-1 ring-cyan-500/30'
            : 'bg-cyan-500/5 border border-cyan-500/20 hover:border-cyan-500/40'
        }`}>
          <div className="flex items-center justify-between">
            <span className={`text-[9px] font-black uppercase tracking-wider ${isT2Hit ? 'text-cyan-200' : 'text-cyan-400'}`}>
              🏁 Target 2 (T2)
            </span>
            <span className={`text-[9px] font-bold ${isT2Hit ? 'text-cyan-100 bg-cyan-600/70 px-1 rounded shadow-sm' : 'text-cyan-400'}`}>
              {isT2Hit ? '✅ HIT!' : levels.t2_pct ? `+${levels.t2_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-sm font-black mt-0.5 ${isT2Hit ? 'text-white' : 'text-cyan-300'}`}>
            ₹{formatNum(levels.t2)}
          </div>
          <div className={`text-[9px] block font-sans font-bold ${isT2Hit ? 'text-cyan-200' : 'text-cyan-400/90'}`}>
            {isT2Hit ? '✅ Resistance Hit · T1 Locked' : levels.t2_rr ? `${levels.t2_rr}:1 R:R · Wall` : 'Resistance Wall'}
          </div>
          {t2DistInfo && (
            <div className="text-[8px] text-cyan-300 font-bold">
              ⚡ {t2DistInfo.pct}% to T2 (₹{formatNum(t2DistInfo.remPts)} away)
            </div>
          )}
          {isDerivative && levels.optPlanRef?.t2_spot && (
            <div className="text-[8px] text-cyan-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t2_spot)}
            </div>
          )}
          {levels.optPlanRef?.t2_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t2_pnl_per_lot || 0) >= 0 ? 'text-emerald-300' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t2_pnl_per_lot)}
            </div>
          )}
        </div>

        {/* 5. TARGET 3 COLUMN (Purple/Gold Glow when Hit) */}
        <div className={`p-2 rounded-lg transition-all duration-200 col-span-2 sm:col-span-1 ${
          isT3Hit
            ? 'bg-purple-500/30 border-2 border-purple-400 ring-2 ring-purple-500/60 shadow-[0_0_16px_rgba(168,85,247,0.4)] animate-pulse'
            : activeStage === 'T3'
            ? 'bg-purple-500/10 border border-purple-500/40 ring-1 ring-purple-500/30'
            : 'bg-purple-500/5 border border-purple-500/20 hover:border-purple-500/40'
        }`}>
          <div className="flex items-center justify-between">
            <span className={`text-[9px] font-black uppercase tracking-wider ${isT3Hit ? 'text-purple-100' : 'text-purple-700 dark:text-purple-300'}`}>
              🚀 Target 3 (T3)
            </span>
            <span className={`text-[9px] font-bold ${isT3Hit ? 'text-purple-100 bg-purple-600/70 px-1 rounded shadow-sm' : 'text-purple-700 dark:text-purple-300'}`}>
              {isT3Hit ? '🚀 MOONSHOT!' : levels.t3_pct ? `+${levels.t3_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-sm font-black mt-0.5 ${isT3Hit ? 'text-white' : 'text-purple-800 dark:text-purple-200'}`}>
            ₹{formatNum(levels.t3)}
          </div>
          <div className={`text-[9px] block font-sans font-bold ${isT3Hit ? 'text-purple-200' : 'text-purple-700/90 dark:text-purple-300/90'}`}>
            {isT3Hit ? '🚀 Moonshot Hit · Max Target' : levels.t3_rr ? `${levels.t3_rr}:1 R:R · Runner` : 'Moonshot Runner'}
          </div>
          {t3DistInfo && (
            <div className="text-[8px] text-purple-300 font-bold">
              ⚡ {t3DistInfo.pct}% to T3 (₹{formatNum(t3DistInfo.remPts)} away)
            </div>
          )}
          {isDerivative && levels.optPlanRef?.t3_spot && (
            <div className="text-[8px] text-purple-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t3_spot)}
            </div>
          )}
          {levels.optPlanRef?.t3_pnl_per_lot !== undefined && levels.optPlanRef.t3_pnl_per_lot !== null && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t3_pnl_per_lot || 0) >= 0 ? 'text-emerald-300' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t3_pnl_per_lot)}
            </div>
          )}
        </div>
      </div>

      {/* Visual Trade Runway Progress Tracker */}
      <div className="pt-1.5 border-t border-border/20 space-y-1.5">
        <div className="flex items-center justify-between text-[8px] font-mono text-muted flex-wrap gap-1">
          <span className={`font-bold transition-colors ${isSLHit ? 'text-rose-300 font-black' : 'text-rose-400'}`}>
            {isSLHit ? '🛑 SL HIT ' : '🛑 SL '}₹{formatNum(levels.sl)}
          </span>
          <span className="text-gold font-bold">⚡ Entry ₹{formatNum(levels.entry)}</span>
          <span className={`font-bold transition-colors ${isT1Hit ? 'text-emerald-300 font-black' : 'text-emerald-400'}`}>
            {isT1Hit ? '✅ T1 HIT ' : '🎯 T1 '}₹{formatNum(levels.t1)}
          </span>
          <span className={`font-bold transition-colors ${isT2Hit ? 'text-cyan-200 font-black' : 'text-cyan-400'}`}>
            {isT2Hit ? '✅ T2 HIT ' : '🏁 T2 '}₹{formatNum(levels.t2)}
          </span>
          <span className={`font-bold transition-colors ${isT3Hit ? 'text-purple-200 font-black' : 'text-purple-300'}`}>
            {isT3Hit ? '🚀 T3 HIT ' : '🚀 T3 '}₹{formatNum(levels.t3)}
          </span>
        </div>
        <div className="relative w-full h-2.5 rounded-full bg-surface border border-border/40 overflow-hidden flex items-center shadow-inner">
          <div className={`h-full border-r ${isSLHit ? 'bg-rose-500/60 border-rose-500' : 'bg-rose-500/30 border-rose-500/60'}`} style={{ width: '20%' }} title="Stop Loss Risk Zone" />
          <div className="h-full bg-gold/30 border-r border-gold/60" style={{ width: '10%' }} title="Entry Zone" />
          <div className={`h-full border-r ${isT1Hit ? 'bg-emerald-500/50 border-emerald-400' : 'bg-emerald-500/25 border-emerald-500/60'}`} style={{ width: '30%' }} title="T1 Profit Zone" />
          <div className={`h-full border-r ${isT2Hit ? 'bg-cyan-500/50 border-cyan-400' : 'bg-cyan-500/25 border-cyan-500/60'}`} style={{ width: '20%' }} title="T2 Expansion Zone" />
          <div className={`h-full ${isT3Hit ? 'bg-purple-500/60' : 'bg-purple-500/25'}`} style={{ width: '20%' }} title="T3 Runner Moonshot Zone" />
          {currentPrice ? (
            <div
              className={`absolute top-0 bottom-0 w-3 -ml-1.5 rounded-full shadow-[0_0_10px_rgba(255,255,255,0.9)] border ${
                isSLHit
                  ? 'bg-rose-500 border-rose-200 ring-2 ring-rose-400 animate-pulse'
                  : isT3Hit
                  ? 'bg-purple-400 border-purple-100 ring-2 ring-purple-300 animate-pulse'
                  : isT2Hit
                  ? 'bg-cyan-400 border-cyan-100 ring-2 ring-cyan-300 animate-pulse'
                  : isT1Hit
                  ? 'bg-emerald-400 border-emerald-100 ring-2 ring-emerald-300 animate-pulse'
                  : 'bg-gold border-gold/50'
              }`}
              style={{ left: `${progressPct}%` }}
              title={`Live Price Position: ₹${formatNum(currentPrice)} (${progressPct}% runway)`}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}
