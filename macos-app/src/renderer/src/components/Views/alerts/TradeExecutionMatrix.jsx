import React, { useMemo } from 'react'
import { resolveAlertLifecycle, resolveAlertProvenance } from './alertHelpers'

export function TradeExecutionMatrix({
  alert,
  levels,
  isBull,
  isDerivative,
  currentPrice: currentPriceProp,
  trailingStop,
  slRationale,
  tradePlan,
  marketStatus,
  expiryInfo,
  densityMode = 'compact',
}) {
  const tp = tradePlan || alert?.actionable_plan?.trade_plan || {}
  const optPlan = alert?.actionable_plan?.option_plan || {}
  const hedgedSpread = alert?.hedged_spread || alert?.actionable_plan?.hedged_spread || optPlan?.hedged_spread || tp?.hedged_spread || null
  const freeRollPlan = alert?.free_roll_plan || alert?.actionable_plan?.free_roll_plan || optPlan?.free_roll_plan || tp?.free_roll_plan || null
  const mktSt = marketStatus || 'SESSION_CLOSED'

  // Single Source of Truth Lifecycle evaluated against the exact current price
  const lifecycle = useMemo(
    () => (alert ? resolveAlertLifecycle(alert, { liveSpot: { ltp: currentPriceProp }, liveContract: { ltp: currentPriceProp } }) : null),
    [alert, currentPriceProp]
  )

  const isTerminal = lifecycle?.isTerminal ?? false
  const currentPrice = isTerminal ? (lifecycle?.currentPrice ?? currentPriceProp) : (currentPriceProp ?? lifecycle?.currentPrice)

  const isCrypto = (alert?.exchange || '').toUpperCase() === 'CRYPTO' || (alert?.exchange || '').toUpperCase() === 'BINANCE' || (alert?.segment || '').toUpperCase() === 'CRYPTO'
  const currSym = isCrypto ? '$' : '₹'

  const formatNum = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '—'
    const num = Number(val)
    return num.toLocaleString(isCrypto ? 'en-US' : 'en-IN', {
      minimumFractionDigits: num >= 500 ? 1 : 2,
      maximumFractionDigits: 2,
    })
  }

  const formatPnl = (pnl) => {
    if (pnl === null || pnl === undefined || isNaN(pnl)) return null
    const n = Number(pnl)
    const sign = n >= 0 ? '+' : ''
    return `${sign}${currSym}${n.toLocaleString(isCrypto ? 'en-US' : 'en-IN')}`
  }

  const isUpward = levels.isUpwardPayoff !== undefined ? levels.isUpwardPayoff : (isBull || isDerivative)

  // Stage Hit Calculations from SSOT lifecycle
  const isTimeStop = lifecycle?.isTimeStop ?? false
  const isExpired = lifecycle?.isExpired ?? false
  const isInvalidated = lifecycle?.isInvalidated ?? false
  const isSLHit = lifecycle ? lifecycle.isSLHit : false
  const isT3Hit = lifecycle ? lifecycle.isT3Hit : false
  const isT2Hit = lifecycle ? lifecycle.isT2Hit : false
  const isT1Hit = lifecycle ? lifecycle.isT1Hit : false
  const horizonInfo = lifecycle?.horizonInfo ?? null

  // Active Target Stage in Flight
  const activeStage = isTimeStop ? 'TIME_STOP' : isSLHit ? 'SL' : isExpired ? 'EXPIRED' : isInvalidated ? 'INVALIDATED' : isT3Hit ? 'T3_DONE' : isT2Hit ? 'T3' : isT1Hit ? 'T2' : 'T1'

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

  // Provenance & Extension Calculations
  const provenance = resolveAlertProvenance(alert)
  const mktBadge = {
    cls: provenance.cls,
    label: provenance.isTest
      ? '🧪 TEST SIMULATION'
      : provenance.isOffMarket
      ? '🌙 SESSION CLOSED'
      : '🟢 LIVE MARKET',
  }

  const noChaseLimit = Number(levels.no_chase_boundary || (levels.entry ? (isUpward ? levels.entry * 1.05 : levels.entry * 0.95) : 0))
  const isExtended = Boolean(
    !isTerminal && currentPrice && noChaseLimit && (
      isUpward ? currentPrice > noChaseLimit : currentPrice < noChaseLimit
    )
  )
  const extendedPct = isExtended && levels.entry
    ? Math.abs(((currentPrice - levels.entry) / levels.entry) * 100).toFixed(1)
    : null

  const pyramidRule = alert.actionable_plan?.pyramid_rule || alert.metrics?.pyramid_rule || tp.pyramid_rule
  const structuralFloor50 = alert.actionable_plan?.structural_floor_50sma || alert.metrics?.structural_floor_50sma || tp.structural_floor_50sma

  const expBadge = expiryInfo?.formatted
    ? `⏳ ${expiryInfo.formatted}${expiryInfo.dte !== null ? ` (${expiryInfo.dte} DTE)` : ''}`
    : expiryInfo?.expiry_date
    ? `⏳ Exp: ${expiryInfo.expiry_date}`
    : null

  return (
    <div className={`rounded-xl p-2 border transition-all duration-200 bg-surface/80 space-y-1.5 shadow-sm ${
      isSLHit ? 'border-rose-500/40 bg-rose-500/5' : isT3Hit ? 'border-purple-500/40 bg-purple-500/5' : isT2Hit ? 'border-cyan-500/40 bg-cyan-500/5' : isT1Hit ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-border/40'
    }`}>
      {/* Execution Matrix Header with Quick Verdict + Milestone Status */}
      <div className="flex items-center justify-between flex-wrap gap-1 pb-1 border-b border-border/30 text-[10px]">
        <div className="flex items-center gap-1.5">
          <span className="font-mono">
            {lifecycle?.stagePill?.icon || (isSLHit ? '🛑' : isT3Hit ? '🚀' : isT2Hit ? '🏁' : isT1Hit ? '🎯' : '⚡')}
          </span>
          <span className="font-black uppercase tracking-wider text-text text-[10px]">
            Trade Execution Matrix &amp; Target Milestones
          </span>
          {/* Real-time Status Pill */}
          {lifecycle?.stagePill ? (
            <span className={`text-[8px] font-black px-1.5 py-0.5 rounded-full border ${lifecycle.stagePill.cls}`}>
              {lifecycle.stagePill.label}
            </span>
          ) : isSLHit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-rose-500/25 text-rose-300 border border-rose-500/50 animate-pulse">
              🛑 STOP LOSS HIT
            </span>
          ) : isT3Hit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-purple-500/25 text-purple-200 border border-purple-400/50 animate-pulse">
              🚀 ALL TARGETS HIT
            </span>
          ) : isT2Hit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-cyan-500/25 text-cyan-200 border border-cyan-400/50 animate-pulse">
              🏁 T2 HIT · RUNNER ACTIVE
            </span>
          ) : isT1Hit ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 animate-pulse">
              🎯 T1 HIT · 50% BOOKED · SL RISK-FREE
            </span>
          ) : currentPrice && levels.entry ? (
            <span className="text-[8px] font-black px-1.5 py-0.5 rounded-full bg-gold/15 text-gold border border-gold/30">
              ⚡ ACTIVE · IN FLIGHT
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold flex-wrap">
          <span className={`px-1.5 py-0.5 rounded border ${mktBadge.cls}`}>
            {mktBadge.label}
          </span>
          {horizonInfo && (
            <div className="flex items-center gap-1">
              <span
                title={horizonInfo.tooltip}
                className={`px-1.5 py-0.5 rounded font-black border cursor-help ${horizonInfo.badgeClasses}`}
              >
                {horizonInfo.icon} {horizonInfo.label}
              </span>
              <span
                title={`Target ETA: ${horizonInfo.etaFull}`}
                className={`px-1.5 py-0.5 rounded font-bold border ${horizonInfo.etaClasses}`}
              >
                🎯 ETA: {horizonInfo.etaFull}
              </span>
            </div>
          )}
          {expBadge && (
            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/25">
              {expBadge}
            </span>
          )}
        </div>
      </div>

      {/* 5-Column High-Density Stage Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 font-mono text-xs">
        {/* 1. STOP LOSS */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isSLHit
            ? 'bg-rose-500/25 border-2 border-rose-500 ring-2 ring-rose-500/40 shadow-[0_0_12px_rgba(244,63,94,0.3)] animate-pulse'
            : 'bg-rose-500/5 border border-rose-500/20'
        }`}>
          <div className="flex items-center justify-between text-[9px]">
            <span className={`font-black uppercase tracking-wider ${isSLHit ? 'text-rose-200' : 'text-rose-400'}`}>
              🛑 Invalidation SL
            </span>
            <span className={`font-bold ${isSLHit ? 'text-rose-100 bg-rose-600/60 px-1 rounded' : 'text-rose-400'}`}>
              {isSLHit ? 'BREACHED' : levels.sl_pct ? `-${levels.sl_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isSLHit ? 'text-white' : 'text-rose-300'}`}>
            {currSym}{formatNum(levels.sl)}
          </div>
          {trailingStop ? (
            <div className="text-[8px] text-cyan-300 font-bold truncate">
              ⚡ Trail {currSym}{formatNum(trailingStop)}
            </div>
          ) : levels.max_loss !== null && levels.max_loss !== undefined ? (
            <div className="text-[8px] text-rose-400 font-bold truncate" title="Maximum Risk per lot (incl. STT & slippage)">
              Risk: -{currSym}{formatNum(levels.max_loss)}/lot
            </div>
          ) : levels.optPlanRef?.sl_pnl_per_lot !== undefined ? (
            <div className="text-[8px] text-rose-400/80 font-bold">
              {formatPnl(levels.optPlanRef.sl_pnl_per_lot)}
            </div>
          ) : null}
        </div>

        {/* 2. ENTRY TRIGGER */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isExtended
            ? 'bg-amber-500/10 border border-amber-500/40 shadow-sm'
            : currentPrice && !isSLHit
            ? 'bg-gold/15 border border-gold/50 shadow-sm'
            : 'bg-gold/5 border border-gold/25'
        }`}>
          <div className="flex items-center justify-between text-[9px]">
            <span className={`font-black uppercase tracking-wider ${isExtended ? 'text-amber-400' : 'text-gold'}`}>
              {isExtended ? '🛑 No Chase' : '⚡ Entry Trigger'}
            </span>
            <span className={`font-bold ${isExtended ? 'text-amber-300 bg-amber-500/20 px-1 rounded' : 'text-amber-300'}`}>
              {isExtended ? `EXTENDED +${extendedPct}%` : (isUpward ? 'BUY' : 'SELL')}
            </span>
          </div>
          <div className="text-xs font-black text-amber-200 mt-0.5">
            {currSym}{formatNum(levels.entry)}
          </div>
          {isExtended ? (
            <div className="text-[8px] text-amber-300 font-bold truncate" title="Price is extended beyond buy zone. Wait for pullback to 50-SMA or secondary base consolidation.">
              ⏳ WAIT FOR PULLBACK
            </div>
          ) : levels.entry_range ? (
            <div className="text-[8px] text-amber-300/90 font-mono font-medium truncate" title="Optimal Trade Entry (OTE) Pullback Range">
              🎯 OTE {levels.entry_range}
            </div>
          ) : null}
          {levels.no_chase_boundary ? (
            <div className="text-[8px] text-rose-400 font-bold truncate" title="No-Chase Maximum Entry Limit">
              🛑 Max {currSym}{formatNum(levels.no_chase_boundary)}
            </div>
          ) : null}
        </div>

        {/* 3. TARGET 1 */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isT1Hit
            ? 'bg-emerald-500/25 border-2 border-emerald-400 ring-2 ring-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.3)] animate-pulse'
            : activeStage === 'T1'
            ? 'bg-emerald-500/10 border border-emerald-500/40'
            : 'bg-emerald-500/5 border border-emerald-500/20'
        }`}>
          <div className="flex items-center justify-between text-[9px]">
            <span className={`font-black uppercase tracking-wider ${isT1Hit ? 'text-emerald-200' : 'text-emerald-400'}`}>
              🎯 Target 1 (T1)
            </span>
            <span className={`font-bold ${isT1Hit ? 'text-emerald-100 bg-emerald-600/70 px-1 rounded' : 'text-emerald-400'}`}>
              {isT1Hit ? '✅ HIT!' : levels.net_risk_reward ? `Net ${levels.net_risk_reward}` : levels.t1_rr ? `${levels.t1_rr}R` : levels.t1_pct ? `+${levels.t1_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isT1Hit ? 'text-white' : 'text-emerald-300'}`}>
            {currSym}{formatNum(levels.t1)}
          </div>
          {t1DistInfo && !isT1Hit ? (
            <div className="text-[8px] text-emerald-300 font-bold truncate">
              {t1DistInfo.pct}% · {currSym}{formatNum(t1DistInfo.remPts)} away
            </div>
          ) : isT1Hit ? (
            <div className="text-[8px] text-emerald-200 font-bold truncate">
              50% Booked · SL BE
            </div>
          ) : null}
        </div>

        {/* 4. TARGET 2 */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isT2Hit
            ? 'bg-cyan-500/25 border-2 border-cyan-400 ring-2 ring-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.3)] animate-pulse'
            : activeStage === 'T2'
            ? 'bg-cyan-500/10 border border-cyan-500/40'
            : 'bg-cyan-500/5 border border-cyan-500/20'
        }`}>
          <div className="flex items-center justify-between text-[9px]">
            <span className={`font-black uppercase tracking-wider ${isT2Hit ? 'text-cyan-200' : 'text-cyan-400'}`}>
              🏁 Target 2 (T2)
            </span>
            <span className={`font-bold ${isT2Hit ? 'text-cyan-100 bg-cyan-600/70 px-1 rounded' : 'text-cyan-400'}`}>
              {isT2Hit ? '✅ HIT!' : levels.t2_rr ? `${levels.t2_rr}R` : levels.t2_pct ? `+${levels.t2_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isT2Hit ? 'text-white' : 'text-cyan-300'}`}>
            {currSym}{formatNum(levels.t2)}
          </div>
          {t2DistInfo && !isT2Hit ? (
            <div className="text-[8px] text-cyan-300 font-bold truncate">
              {t2DistInfo.pct}% · {currSym}{formatNum(t2DistInfo.remPts)} away
            </div>
          ) : isT2Hit ? (
            <div className="text-[8px] text-cyan-200 font-bold truncate">
              Runner Locked
            </div>
          ) : null}
        </div>

        {/* 5. TARGET 3 */}
        <div className={`p-1.5 rounded-lg transition-all col-span-2 sm:col-span-1 ${
          isT3Hit
            ? 'bg-purple-500/30 border-2 border-purple-400 ring-2 ring-purple-500/60 shadow-[0_0_16px_rgba(168,85,247,0.4)] animate-pulse'
            : activeStage === 'T3'
            ? 'bg-purple-500/10 border border-purple-500/40'
            : 'bg-purple-500/5 border border-purple-500/20'
        }`}>
          <div className="flex items-center justify-between text-[9px]">
            <span className={`font-black uppercase tracking-wider ${isT3Hit ? 'text-purple-100' : 'text-purple-700 dark:text-purple-300'}`}>
              🚀 Target 3 (T3)
            </span>
            <span className={`font-bold ${isT3Hit ? 'text-purple-100 bg-purple-600/70 px-1 rounded' : 'text-purple-700 dark:text-purple-300'}`}>
              {isT3Hit ? '🚀 MOONSHOT!' : levels.t3_rr ? `${levels.t3_rr}R` : levels.t3_pct ? `+${levels.t3_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isT3Hit ? 'text-white' : 'text-purple-800 dark:text-purple-200'}`}>
            {currSym}{formatNum(levels.t3)}
          </div>
          {t3DistInfo && !isT3Hit ? (
            <div className="text-[8px] text-purple-300 font-bold truncate">
              {t3DistInfo.pct}% · {currSym}{formatNum(t3DistInfo.remPts)} away
            </div>
          ) : isT3Hit ? (
            <div className="text-[8px] text-purple-200 font-bold truncate">
              Max Profit Hit
            </div>
          ) : alert?.actionable_plan?.runner_strike?.symbol ? (
            <div className="text-[7.5px] font-mono text-purple-300 font-bold truncate" title={`High-Beta Runner: ${alert.actionable_plan.runner_strike.symbol}`}>
              ⚡ {alert.actionable_plan.runner_strike.symbol.replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '')}
            </div>
          ) : null}
        </div>
      </div>

      {/* Slim 2px Visual Runway Progress Indicator (Zero Duplicate Text) */}
      <div className="relative w-full h-1.5 rounded-full bg-surface border border-border/40 overflow-hidden flex items-center">
        <div className={`h-full border-r ${isSLHit ? 'bg-rose-500/60 border-rose-500' : 'bg-rose-500/30 border-rose-500/60'}`} style={{ width: '20%' }} title="Stop Loss Zone" />
        <div className="h-full bg-gold/30 border-r border-gold/60" style={{ width: '10%' }} title="Entry Zone" />
        <div className={`h-full border-r ${isT1Hit ? 'bg-emerald-500/50 border-emerald-400' : 'bg-emerald-500/25 border-emerald-500/60'}`} style={{ width: '30%' }} title="T1 Profit Zone" />
        <div className={`h-full border-r ${isT2Hit ? 'bg-cyan-500/50 border-cyan-400' : 'bg-cyan-500/25 border-cyan-500/60'}`} style={{ width: '20%' }} title="T2 Expansion Zone" />
        <div className={`h-full ${isT3Hit ? 'bg-purple-500/60' : 'bg-purple-500/25'}`} style={{ width: '20%' }} title="T3 Runner Moonshot Zone" />
        {currentPrice ? (
          <div
            className={`absolute top-0 bottom-0 w-2.5 -ml-1 rounded-full shadow-[0_0_6px_rgba(255,255,255,0.9)] border ${
              isSLHit
                ? 'bg-rose-500 border-rose-200 ring-1 ring-rose-400 animate-pulse'
                : isT3Hit
                ? 'bg-purple-400 border-purple-100 ring-1 ring-purple-300 animate-pulse'
                : isT2Hit
                ? 'bg-cyan-400 border-cyan-100 ring-1 ring-cyan-300 animate-pulse'
                : isT1Hit
                ? 'bg-emerald-400 border-emerald-100 ring-1 ring-emerald-300 animate-pulse'
                : 'bg-gold border-gold/50'
            }`}
            style={{ left: `${progressPct}%` }}
            title={`Live Position: ${currSym}${formatNum(currentPrice)} (${progressPct}% runway)`}
          />
        ) : null}
      </div>

      {/* ── Institutional Defined-Risk Vertical Spread Blueprint ── */}
      {hedgedSpread && (
        <div className="p-2 rounded-lg bg-sky-950/40 border border-sky-500/30 flex flex-col gap-1.5 text-[9.5px]">
          <div className="flex items-center justify-between">
            <span className="font-black text-sky-300 flex items-center gap-1 uppercase tracking-wide">
              <span>🛡️</span> DEFINED-RISK VERTICAL SPREAD (Theta-Neutral)
            </span>
            <span className="font-mono font-bold text-sky-200 bg-sky-500/20 px-1.5 py-0.5 rounded border border-sky-500/30">
              R:R {hedgedSpread.spread_rr || '1:2.5'} · Max Profit: ₹{hedgedSpread.max_profit_pts ? formatNum(hedgedSpread.max_profit_pts) : '—'}
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5 text-[9px] font-mono">
            <div className="bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-1 rounded text-emerald-300 truncate" title={hedgedSpread.long_leg}>
              🟢 <span className="font-bold">BUY:</span> {hedgedSpread.long_leg}
            </div>
            <div className="bg-rose-500/10 border border-rose-500/20 px-1.5 py-1 rounded text-rose-300 truncate" title={hedgedSpread.short_leg}>
              🔴 <span className="font-bold">SELL:</span> {hedgedSpread.short_leg}
            </div>
            <div className="bg-amber-500/10 border border-amber-500/20 px-1.5 py-1 rounded text-amber-300 truncate">
              ⚡ <span className="font-bold">Net Debit:</span> ₹{formatNum(hedgedSpread.net_debit)}
            </div>
          </div>
          <div className="text-[8.5px] text-sky-200/80 flex items-center gap-1 font-sans">
            <span>🛡️</span>
            <span>{hedgedSpread.guidance || `${hedgedSpread.theta_reduction_pct || 75}% Theta decay offset via short leg.`}</span>
          </div>
        </div>
      )}

      {/* ── Free-Roll Execution Protocol (+2R Scale 50% & Zero-Risk Runner) ── */}
      {freeRollPlan && (
        <div className="p-2 rounded-lg bg-emerald-950/40 border border-emerald-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-1.5 text-[9.5px]">
          <div className="flex items-center gap-1.5 font-bold text-emerald-300">
            <span className="text-xs">💎</span>
            <span>
              FREE-ROLL PROTOCOL: Bank {freeRollPlan.scale_pct || '50%'} at T1 (₹{formatNum(freeRollPlan.t1_target_premium || levels.t1)}) & ratchet SL to Cost (Risk = ₹0.00).
            </span>
          </div>
          <div className="text-[8.5px] font-mono text-cyan-300 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/20 whitespace-nowrap">
            🏃 Runner: {freeRollPlan.runner_trailing_strategy || '1.5x ATR dynamic trail'}
          </div>
        </div>
      )}

      {/* Dynamic Institutional Guidance: Extended / Pullback / Pyramiding */}
      {isExtended && (
        <div className="px-2 py-1 rounded bg-amber-500/10 border border-amber-500/25 flex items-center justify-between text-[9.5px] text-amber-200 flex-wrap gap-1">
          <div className="flex items-center gap-1.5 font-bold">
            <span>⏳</span>
            <span>WAIT FOR PULLBACK: Price is +{extendedPct}% past base entry. Institutional accumulation floor: {structuralFloor50 ? `Rising 50-SMA ₹${formatNum(structuralFloor50)}` : 'Rising 50-Day Moving Average'}.</span>
          </div>
          {pyramidRule && (
            <div className="text-[9px] text-cyan-300 font-semibold" title={pyramidRule}>
              🧗 Pyramiding: Add +30% on secondary base breakout only
            </div>
          )}
        </div>
      )}
    </div>
  )
}
