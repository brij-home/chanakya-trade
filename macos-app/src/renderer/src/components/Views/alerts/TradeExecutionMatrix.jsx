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

  const hedgedSpreadData = useMemo(() => {
    if (!hedgedSpread) return null

    const parseLegObj = (leg, defaultAction = 'BUY') => {
      if (!leg) return null
      if (typeof leg === 'string') {
        const cleanStr = leg.replace(/^(NSE|BSE|NFO|MCX|BFO|CDS|CRYPTO|BINANCE):/, '')
        return {
          action: defaultAction,
          symbol: cleanStr,
          strikeLabel: cleanStr,
          strike: null,
          optionType: cleanStr.endsWith('CE') ? 'CE' : cleanStr.endsWith('PE') ? 'PE' : '',
          premium: null,
          premiumLabel: '—',
          fullText: leg,
        }
      }
      const action = (leg.side || leg.action || defaultAction).toUpperCase()
      const strike = leg.strike ? Number(leg.strike) : null
      const optionType = leg.option_type || (leg.symbol && leg.symbol.endsWith('CE') ? 'CE' : leg.symbol && leg.symbol.endsWith('PE') ? 'PE' : '')
      const premium = (leg.premium !== undefined && leg.premium !== null) ? Number(leg.premium) : null
      const cleanSym = (leg.symbol || '').replace(/^(NSE|BSE|NFO|MCX|BFO|CDS|CRYPTO|BINANCE):/, '')
      const strikeLabel = strike ? `${Math.round(strike)} ${optionType}`.trim() : cleanSym
      const premiumLabel = premium !== null ? `₹${formatNum(premium)}` : '—'
      const fullText = `${strikeLabel}${premium !== null ? ` @ ₹${formatNum(premium)}` : ''}`

      return {
        action,
        strike,
        optionType,
        premium,
        symbol: cleanSym,
        strikeLabel,
        premiumLabel,
        quantity: leg.quantity || leg.lot_size || null,
        fullText,
      }
    }

    let buyLeg = null
    let sellLeg = null

    if (Array.isArray(hedgedSpread.legs) && hedgedSpread.legs.length >= 2) {
      const b = hedgedSpread.legs.find((l) => (l.side || l.action || '').toUpperCase() === 'BUY') || hedgedSpread.legs[0]
      const s = hedgedSpread.legs.find((l) => (l.side || l.action || '').toUpperCase() === 'SELL') || hedgedSpread.legs[1]
      buyLeg = parseLegObj(b, 'BUY')
      sellLeg = parseLegObj(s, 'SELL')
    } else {
      buyLeg = parseLegObj(hedgedSpread.long_leg, 'BUY')
      sellLeg = parseLegObj(hedgedSpread.short_leg, 'SELL')
    }

    // Fallbacks if legs were not complete:
    const fallbackBuyStrike = hedgedSpread.buy_strike || optPlan?.strike || alert?.strike
    const fallbackSellStrike = hedgedSpread.sell_strike || hedgedSpread.hedge_strike
    const fallbackOptType = hedgedSpread.option_type || optPlan?.option_type || alert?.option_type || (isBull ? 'CE' : 'PE')

    if (!buyLeg && fallbackBuyStrike) {
      const bStrike = Number(fallbackBuyStrike)
      const bPrem = optPlan?.entry_premium || alert?.option_premium || alert?.ltp || null
      buyLeg = {
        action: 'BUY',
        strike: bStrike,
        optionType: fallbackOptType,
        premium: bPrem,
        strikeLabel: `${Math.round(bStrike)} ${fallbackOptType}`,
        premiumLabel: bPrem !== null ? `₹${formatNum(bPrem)}` : '—',
        symbol: alert?.contract_symbol || `${alert?.symbol || ''} ${Math.round(bStrike)} ${fallbackOptType}`.trim(),
        fullText: `${Math.round(bStrike)} ${fallbackOptType}${bPrem ? ` @ ₹${formatNum(bPrem)}` : ''}`,
      }
    }
    if (!sellLeg && fallbackSellStrike) {
      const sStrike = Number(fallbackSellStrike)
      const sPrem = hedgedSpread.hedge_premium || optPlan?.hedge_premium || null
      sellLeg = {
        action: 'SELL',
        strike: sStrike,
        optionType: fallbackOptType,
        premium: sPrem,
        strikeLabel: `${Math.round(sStrike)} ${fallbackOptType}`,
        premiumLabel: sPrem !== null ? `₹${formatNum(sPrem)}` : '—',
        symbol: hedgedSpread.hedge_contract_symbol || `${alert?.symbol || ''} ${Math.round(sStrike)} ${fallbackOptType}`.trim(),
        fullText: `${Math.round(sStrike)} ${fallbackOptType}${sPrem ? ` @ ₹${formatNum(sPrem)}` : ''}`,
      }
    }

    // Economics — per-contract (per-unit) netDebit is the canonical display value.
    // net_debit_per_unit is now exposed by DefinedRiskSpread.to_dict().
    // net_cashflow is lot-level (per_unit × lot_size) — never display as "/ contract".
    const lotSize = alert?.lot_size || hedgedSpread.lot_size || optPlan?.lot_size || null
    const _lotSz = lotSize || 1
    const netDebit = (
      // prefer explicit per-unit field (added in Fix 3)
      hedgedSpread.net_debit_per_unit
        // if both leg premiums are known, direct calculation is the most accurate per-contract debit
        ?? (buyLeg?.premium != null && sellLeg?.premium != null
            ? Math.max(0.1, Math.round(Math.abs(buyLeg.premium - sellLeg.premium) * 100) / 100)
            : null)
        // derive per-unit from lot-level cashflow when lot_size is known
        ?? (hedgedSpread.net_cashflow != null && lotSize
            ? Math.round((hedgedSpread.net_cashflow / _lotSz) * 100) / 100
            : null)
        // legacy lot-level fallbacks (scale down by lotSize if lot-level total was passed)
        ?? (hedgedSpread.net_debit != null && lotSize && hedgedSpread.net_debit > 50 && _lotSz > 1
            ? Math.round((hedgedSpread.net_debit / _lotSz) * 100) / 100
            : hedgedSpread.net_debit)
        ?? (hedgedSpread.capital_required != null && lotSize && hedgedSpread.capital_required > 50 && _lotSz > 1
            ? Math.round((hedgedSpread.capital_required / _lotSz) * 100) / 100
            : hedgedSpread.capital_required)
    )
    const maxProfit = hedgedSpread.max_profit_pts ?? hedgedSpread.max_profit ?? (
      buyLeg?.strike && sellLeg?.strike && netDebit
        ? Math.max(0, Math.round((Math.abs(buyLeg.strike - sellLeg.strike) - netDebit) * 100) / 100)
        : null
    )
    const rrRatio = hedgedSpread.spread_rr ?? (
      hedgedSpread.risk_reward_ratio
        ? `1:${hedgedSpread.risk_reward_ratio}`
        : (netDebit && maxProfit ? `1:${(maxProfit / netDebit).toFixed(1)}` : '1:2.5')
    )
    // Breakeven from server is in option-strike space (meaningful only when strikes are realistic).
    // Suppress it for index options where strike domain > 10000 to avoid misleading values.
    const _rawBreakeven = hedgedSpread.breakeven_point ?? hedgedSpread.breakeven_spot ?? (
      buyLeg?.strike && netDebit
        ? (isBull ? buyLeg.strike + netDebit : buyLeg.strike - netDebit)
        : null
    )
    // Only surface breakeven when it's in a sensible range relative to the long leg strike
    const breakeven = (_rawBreakeven && buyLeg?.strike && _rawBreakeven > 0 && _rawBreakeven < buyLeg.strike * 1.5)
      ? _rawBreakeven
      : null
    const maxLoss = hedgedSpread.max_loss
        ?? (netDebit && lotSize ? Math.round(netDebit * _lotSz) : null)
    const spreadName = hedgedSpread.spread_name || (
      hedgedSpread.strategy_name ? hedgedSpread.strategy_name.replace(/_/g, ' ') : (isBull ? 'Bull Call Spread' : 'Bear Put Spread')
    )
    const guidance = hedgedSpread.guidance || hedgedSpread.thesis || `${hedgedSpread.theta_reduction_pct || 75}% Theta decay offset via short leg.`
    const thetaReductionPct = hedgedSpread.theta_reduction_pct ? `${hedgedSpread.theta_reduction_pct}%` : '75%'

    return {
      longLeg: buyLeg?.fullText || '',
      shortLeg: sellLeg?.fullText || '',
      buyLeg,
      sellLeg,
      netDebit,
      maxProfit,
      maxLoss,
      lotSize,
      rrRatio,
      breakeven,
      spreadName,
      guidance,
      thetaReductionPct,
    }
  }, [hedgedSpread, optPlan, alert, isBull])

  // Single Source of Truth Lifecycle evaluated against the exact current price
  const lifecycle = useMemo(
    () => (alert ? resolveAlertLifecycle(alert, { liveSpot: { ltp: currentPriceProp }, liveContract: { ltp: currentPriceProp } }) : null),
    [alert, currentPriceProp]
  )

  const isTerminal = lifecycle?.isTerminal ?? false
  const currentPrice = isTerminal ? (lifecycle?.currentPrice ?? currentPriceProp) : (currentPriceProp ?? lifecycle?.currentPrice)

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
            <span className={`text-[10px] font-black px-1.5 py-0.5 rounded-full border ${lifecycle.stagePill.cls}`}>
              {lifecycle.stagePill.label}
            </span>
          ) : isSLHit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-rose-500/25 text-rose-300 border border-rose-500/50 animate-pulse">
              🛑 STOP LOSS HIT
            </span>
          ) : isT3Hit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-purple-500/25 text-purple-200 border border-purple-400/50 animate-pulse">
              🚀 ALL TARGETS HIT
            </span>
          ) : isT2Hit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-cyan-500/25 text-cyan-200 border border-cyan-400/50 animate-pulse">
              🏁 T2 HIT · RUNNER ACTIVE
            </span>
          ) : isT1Hit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 animate-pulse">
              🎯 T1 HIT · 50% BOOKED · SL RISK-FREE
            </span>
          ) : currentPrice && levels.entry ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-gold/15 text-gold border border-gold/30">
              ⚡ ACTIVE · IN FLIGHT
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5 text-[11px] font-mono font-bold flex-wrap">
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
          <div className="flex items-center justify-between text-[11px]">
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
            <div className="text-[10px] text-cyan-300 font-bold truncate">
              ⚡ Trail {currSym}{formatNum(trailingStop)}
            </div>
          ) : levels.max_loss !== null && levels.max_loss !== undefined ? (
            <div className="text-[10px] text-rose-400 font-bold truncate" title="Maximum Risk per lot (incl. STT & slippage)">
              Risk: -{currSym}{formatNum(levels.max_loss)}/lot
            </div>
          ) : levels.optPlanRef?.sl_pnl_per_lot !== undefined ? (
            <div className="text-[10px] text-rose-400/80 font-bold">
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
          <div className="flex items-center justify-between text-[11px]">
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
            <div className="text-[10px] text-amber-300 font-bold truncate" title="Price is extended beyond buy zone. Wait for pullback to 50-SMA or secondary base consolidation.">
              ⏳ WAIT FOR PULLBACK
            </div>
          ) : levels.entry_range ? (
            <div className="text-[10px] text-amber-300/90 font-mono font-medium truncate" title="Optimal Trade Entry (OTE) Pullback Range">
              🎯 OTE {levels.entry_range}
            </div>
          ) : null}
          {levels?.no_chase_boundary ? (
            <div
              className="text-[10px] text-rose-400 font-bold truncate"
              title={
                levels.spot_no_chase_boundary
                  ? `No-Chase Option Limit: ${currSym}${formatNum(levels.no_chase_boundary)} (Underlying Spot Max: ${currSym}${formatNum(levels.spot_no_chase_boundary)})`
                  : 'No-Chase Maximum Entry Limit'
              }
            >
              🛑 NoChase {currSym}{formatNum(levels.no_chase_boundary)}
              {levels.spot_no_chase_boundary && (
                <span className="text-[9px] text-zinc-400 ml-1 font-normal hidden xl:inline" title="Underlying Spot Breakout Ceiling">
                  (Spot {currSym}{formatNum(levels.spot_no_chase_boundary)})
                </span>
              )}
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
          <div className="flex items-center justify-between text-[11px]">
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
            <div className="text-[10px] text-emerald-300 font-bold truncate">
              {t1DistInfo.pct}% · {currSym}{formatNum(t1DistInfo.remPts)} away
            </div>
          ) : isT1Hit ? (
            <div className="text-[10px] text-emerald-200 font-bold truncate">
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
          <div className="flex items-center justify-between text-[11px]">
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
            <div className="text-[10px] text-cyan-300 font-bold truncate">
              {t2DistInfo.pct}% · {currSym}{formatNum(t2DistInfo.remPts)} away
            </div>
          ) : isT2Hit ? (
            <div className="text-[10px] text-cyan-200 font-bold truncate">
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
          <div className="flex items-center justify-between text-[11px]">
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
            <div className="text-[10px] text-purple-300 font-bold truncate">
              {t3DistInfo.pct}% · {currSym}{formatNum(t3DistInfo.remPts)} away
            </div>
          ) : isT3Hit ? (
            <div className="text-[10px] text-purple-200 font-bold truncate">
              Max Profit Hit
            </div>
          ) : alert?.actionable_plan?.runner_strike?.symbol ? (
            <div className="text-[10px] font-mono text-purple-300 font-bold truncate" title={`High-Beta Runner: ${alert.actionable_plan.runner_strike.symbol}`}>
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

      {/* ── Institutional Broker Pre-Order (STAGE PRIMED) ── */}
      {(alert?.stage === 'PRIMED' || alert?.actionable_plan?.broker_order_type === 'BUY SL-LIMIT' || alert?.actionable_plan?.sl_limit_trigger) && (
        <div className="p-2 rounded-lg bg-amber-500/15 border border-amber-400/50 flex flex-col gap-1.5 text-[11px]">
          <div className="flex items-center justify-between">
            <span className="font-black text-amber-300 flex items-center gap-1.5 uppercase tracking-wide">
              <span>⚡</span> BROKER PRE-ORDER: {alert?.actionable_plan?.broker_order_type || 'BUY SL-LIMIT'}
            </span>
            <span className="text-[10px] font-mono font-bold text-amber-200 bg-amber-500/25 px-2 py-0.5 rounded border border-amber-400/40">
              STAGE PRIMED · ZERO LATENCY
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-[11px] font-mono">
            <div className="bg-surface/80 border border-amber-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Trigger</span>
              <span className="font-black text-amber-300">{currSym}{formatNum(alert?.actionable_plan?.sl_limit_trigger || levels.entry)}</span>
            </div>
            <div className="bg-surface/80 border border-amber-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Limit Price</span>
              <span className="font-black text-text">{currSym}{formatNum(alert?.actionable_plan?.sl_limit_price || levels.entry)}</span>
            </div>
            <div className="bg-surface/80 border border-rose-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Stop Loss</span>
              <span className="font-black text-rose-400">{currSym}{formatNum(levels.sl)}</span>
            </div>
            <div className="bg-surface/80 border border-emerald-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Target 1 (+2R)</span>
              <span className="font-black text-emerald-300">{currSym}{formatNum(levels.t1)}</span>
            </div>
          </div>
          <div className="text-[10px] text-amber-200/90 flex items-center gap-1 font-sans">
            <span>💡</span>
            <span>Stage pending SL-Limit order in broker OMS now. Exchange matching engine will auto-fill on breach with zero execution latency.</span>
          </div>
        </div>
      )}

      {/* ── Institutional Defined-Risk Vertical Spread Blueprint ── */}
      {hedgedSpreadData && (
        <div className="rounded-xl border border-sky-500/40 bg-gradient-to-b from-[#0c182c] via-[#091222] to-[#060c18] p-3 space-y-2.5 shadow-lg shadow-sky-950/40 text-xs">
          {/* Header Bar: Strategy & Key Metrics */}
          <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-sky-500/25">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-sky-500/20 text-sky-300 text-xs shadow-inner border border-sky-400/30">
                🛡️
              </span>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-black text-white uppercase tracking-wider text-xs sm:text-[13px] font-sans">
                  {hedgedSpreadData.spreadName || 'DEFINED-RISK VERTICAL SPREAD'}
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10.5px] font-mono font-bold uppercase tracking-wider bg-sky-500/15 text-sky-200 border border-sky-400/30">
                  THETA-NEUTRAL HEDGE
                </span>
              </div>
            </div>

            <div className="flex items-center gap-1.5 flex-wrap font-mono">
              <span className="px-2 py-0.5 rounded-md bg-sky-900/60 text-sky-200 border border-sky-400/30 font-bold text-[10.5px]">
                R:R <span className="text-white font-black">{hedgedSpreadData.rrRatio}</span>
              </span>
              {hedgedSpreadData.maxProfit !== null && (
                <span className="px-2 py-0.5 rounded-md bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 font-bold text-[10.5px]">
                  Max Profit: <span className="text-white font-black">₹{formatNum(hedgedSpreadData.maxProfit)}</span>
                </span>
              )}
            </div>
          </div>

          {/* 3-Column Execution Matrix */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 font-mono">
            {/* 🟢 BUY LEG (Long Contract) */}
            <div className="p-2.5 rounded-lg bg-gradient-to-b from-[#082318] to-[#04140d] border border-emerald-500/40 hover:border-emerald-400/70 transition-all flex flex-col justify-between shadow-sm">
              <div className="flex items-center justify-between pb-1 border-b border-emerald-500/20">
                <div className="flex items-center gap-1.5">
                  <span className="px-1.5 py-0.5 rounded bg-emerald-500 text-slate-950 font-black text-[10px] uppercase tracking-wider shadow-sm">
                    BUY +1
                  </span>
                  <span className="font-bold text-[10px] text-emerald-300/90 uppercase tracking-wide">
                    Long Leg
                  </span>
                </div>
                <span className="text-[10px] text-emerald-400 font-bold">
                  {hedgedSpreadData.buyLeg?.optionType || 'OPTION'}
                </span>
              </div>

              <div className="my-2">
                <div className="text-base sm:text-lg font-black text-white tracking-wide">
                  {hedgedSpreadData.buyLeg?.strikeLabel || hedgedSpreadData.longLeg || '—'}
                </div>
                {hedgedSpreadData.buyLeg?.symbol && hedgedSpreadData.buyLeg.symbol !== hedgedSpreadData.buyLeg.strikeLabel && (
                  <div className="text-[10px] text-emerald-300/70 truncate mt-0.5 font-sans" title={hedgedSpreadData.buyLeg.symbol}>
                    {hedgedSpreadData.buyLeg.symbol}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-emerald-500/20">
                <span className="text-emerald-300/80 uppercase font-semibold text-[10px]">
                  Entry Premium
                </span>
                <span className="font-black text-emerald-200 text-xs">
                  {hedgedSpreadData.buyLeg?.premium !== null && hedgedSpreadData.buyLeg?.premium !== undefined
                    ? `₹${formatNum(hedgedSpreadData.buyLeg.premium)}`
                    : hedgedSpreadData.longLeg?.includes('@')
                    ? hedgedSpreadData.longLeg.split('@')[1].trim()
                    : '—'}
                </span>
              </div>
            </div>

            {/* 🔴 SELL LEG (Short Hedge Contract) */}
            <div className="p-2.5 rounded-lg bg-gradient-to-b from-[#290d15] to-[#16050a] border border-rose-500/40 hover:border-rose-400/70 transition-all flex flex-col justify-between shadow-sm">
              <div className="flex items-center justify-between pb-1 border-b border-rose-500/20">
                <div className="flex items-center gap-1.5">
                  <span className="px-1.5 py-0.5 rounded bg-rose-500 text-white font-black text-[10px] uppercase tracking-wider shadow-sm">
                    SELL -1
                  </span>
                  <span className="font-bold text-[10px] text-rose-300/90 uppercase tracking-wide">
                    Hedge Leg
                  </span>
                </div>
                <span className="text-[10px] text-rose-400 font-bold">
                  {hedgedSpreadData.sellLeg?.optionType || 'HEDGE'}
                </span>
              </div>

              <div className="my-2">
                <div className="text-base sm:text-lg font-black text-white tracking-wide">
                  {hedgedSpreadData.sellLeg?.strikeLabel || hedgedSpreadData.shortLeg || '—'}
                </div>
                {hedgedSpreadData.sellLeg?.symbol && hedgedSpreadData.sellLeg.symbol !== hedgedSpreadData.sellLeg.strikeLabel && (
                  <div className="text-[10px] text-rose-300/70 truncate mt-0.5 font-sans" title={hedgedSpreadData.sellLeg.symbol}>
                    {hedgedSpreadData.sellLeg.symbol}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-rose-500/20">
                <span className="text-rose-300/80 uppercase font-semibold text-[10px]">
                  Credit Received
                </span>
                <span className="font-black text-rose-200 text-xs">
                  {hedgedSpreadData.sellLeg?.premium !== null && hedgedSpreadData.sellLeg?.premium !== undefined
                    ? `₹${formatNum(hedgedSpreadData.sellLeg.premium)}`
                    : hedgedSpreadData.shortLeg?.includes('@')
                    ? hedgedSpreadData.shortLeg.split('@')[1].trim()
                    : '—'}
                </span>
              </div>
            </div>

            {/* ⚡ NET DEBIT & RISK CAP */}
            <div className="p-2.5 rounded-lg bg-gradient-to-b from-[#251b07] to-[#140e02] border border-amber-500/40 hover:border-amber-400/70 transition-all flex flex-col justify-between shadow-sm">
              <div className="flex items-center justify-between pb-1 border-b border-amber-500/20">
                <div className="flex items-center gap-1.5">
                  <span className="px-1.5 py-0.5 rounded bg-amber-500 text-slate-950 font-black text-[10px] uppercase tracking-wider shadow-sm">
                    NET DEBIT:
                  </span>
                  <span className="font-bold text-[10px] text-amber-300/90 uppercase tracking-wide">
                    Max Capital Risk
                  </span>
                </div>
                <span className="text-[10px] text-amber-400 font-bold">
                  {hedgedSpreadData.breakeven ? `BE ₹${formatNum(hedgedSpreadData.breakeven)}` : 'CAPPED RISK'}
                </span>
              </div>

              <div className="my-2">
                <div className="text-base sm:text-lg font-black text-amber-200 tracking-wide flex items-baseline gap-1.5">
                  <span className="font-bold">Net Debit:</span>
                  <span>₹{formatNum(hedgedSpreadData.netDebit)}</span>
                  <span className="text-[10px] text-amber-300/70 font-normal">/ contract</span>
                </div>
                {hedgedSpreadData.maxLoss !== null && (
                  <div className="text-[10px] text-amber-300/90 truncate mt-0.5 font-mono">
                    Max Loss: <span className="font-bold text-rose-300">₹{formatNum(hedgedSpreadData.maxLoss)}</span> / lot
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-amber-500/20">
                <span className="text-amber-300/80 uppercase font-semibold text-[10px]">
                  Theta Decay Offset
                </span>
                <span className="font-black text-emerald-300 text-xs">
                  {hedgedSpreadData.thetaReductionPct || '75%'}
                </span>
              </div>
            </div>
          </div>

          {/* Institutional Guidance Banner */}
          <div className="p-2 rounded-lg bg-sky-950/60 border border-sky-500/25 flex items-start gap-2 text-[11px] leading-relaxed text-sky-100">
            <span className="text-sky-300 text-sm flex-shrink-0">🛡️</span>
            <div className="flex-1 font-sans">
              <span className="font-bold text-sky-200">Execution Edge: </span>
              <span className="text-slate-200">{hedgedSpreadData.guidance}</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Free-Roll Execution Protocol (+2R Scale 50% & Zero-Risk Runner) ── */}
      {freeRollPlan && (
        <div className="p-2 rounded-lg bg-emerald-950/40 border border-emerald-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-1.5 text-[11px]">
          <div className="flex items-center gap-1.5 font-bold text-emerald-300">
            <span className="text-xs">💎</span>
            <span>
              FREE-ROLL PROTOCOL: Bank {freeRollPlan.scale_pct || '50%'} at T1 (₹{formatNum(freeRollPlan.t1_target_premium || levels.t1)}) & ratchet SL to Cost (Risk = ₹0.00).
            </span>
          </div>
          <div className="text-[10px] font-mono text-cyan-300 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/20 whitespace-nowrap">
            🏃 Runner: {freeRollPlan.runner_trailing_strategy || '1.5x ATR dynamic trail'}
          </div>
        </div>
      )}

      {/* Dynamic Institutional Guidance: Extended / Pullback / Pyramiding */}
      {isExtended && (
        <div className="px-2 py-1 rounded bg-amber-500/10 border border-amber-500/25 flex items-center justify-between text-[11px] text-amber-200 flex-wrap gap-1">
          <div className="flex items-center gap-1.5 font-bold">
            <span>⏳</span>
            <span>WAIT FOR PULLBACK: Price is +{extendedPct}% past base entry. Institutional accumulation floor: {structuralFloor50 ? `Rising 50-SMA ₹${formatNum(structuralFloor50)}` : 'Rising 50-Day Moving Average'}.</span>
          </div>
          {pyramidRule && (
            <div className="text-[11px] text-cyan-300 font-semibold" title={pyramidRule}>
              🧗 Pyramiding: Add +30% on secondary base breakout only
            </div>
          )}
        </div>
      )}
    </div>
  )
}
