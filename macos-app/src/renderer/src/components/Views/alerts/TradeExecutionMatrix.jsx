import React, { useMemo } from 'react'
import { resolveAlertLifecycle, resolveAlertProvenance, computeExecutionLevels, formatAlertTriggerTime, INDEX_LOT_SIZES } from './alertHelpers'

export function TradeExecutionMatrix({
  alert,
  levels: levelsProp,
  lifecycle: lifecycleProp,
  isBull: isBullProp,
  isDerivative: isDerivativeProp,
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
  const hedgedSpread = alert?.hedged_spread || alert?.actionable_plan?.hedged_spread || alert?.metrics?.hedged_spread || optPlan?.hedged_spread || tp?.hedged_spread || null
  const freeRollPlan = alert?.free_roll_plan || alert?.actionable_plan?.free_roll_plan || optPlan?.free_roll_plan || tp?.free_roll_plan || null
  const mktSt = marketStatus || 'SESSION_CLOSED'

  const isCrypto = (alert?.exchange || '').toUpperCase() === 'CRYPTO' || (alert?.exchange || '').toUpperCase() === 'BINANCE' || (alert?.segment || '').toUpperCase() === 'CRYPTO'
  const currSym = isCrypto ? '$' : '₹'
  const cleanSym = String(alert?.symbol || '').replace(/^(NSE|BSE|NFO|MCX|BFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()
  const lotSize = alert?.lot_size || alert?.metrics?.lot_size || optPlan?.lot_size || hedgedSpread?.lot_size || INDEX_LOT_SIZES[cleanSym] || null

  const formatNum = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '—'
    const num = Number(val)
    return num.toLocaleString(isCrypto ? 'en-US' : 'en-IN', {
      minimumFractionDigits: num % 1 === 0 ? 0 : (num >= 500 ? 1 : 2),
      maximumFractionDigits: 2,
    })
  }

  const lifecycle = useMemo(() => {
    if (lifecycleProp) return lifecycleProp
    return alert ? resolveAlertLifecycle(alert, { liveSpot: { ltp: currentPriceProp }, liveContract: { ltp: currentPriceProp } }) : null
  }, [lifecycleProp, alert, currentPriceProp])

  const isBull = isBullProp !== undefined ? isBullProp : (lifecycle?.isBull ?? false)
  const isDerivative = isDerivativeProp !== undefined ? isDerivativeProp : (lifecycle?.isDerivative ?? false)
  const isOptionSell = lifecycle?.isOptionSell ?? false
  const isTerminal = lifecycle?.isTerminal ?? false
  const currentPrice = isTerminal ? (lifecycle?.currentPrice ?? currentPriceProp) : (currentPriceProp ?? lifecycle?.currentPrice ?? alert?.current_price ?? null)

  const levels = useMemo(() => {
    if (levelsProp) return levelsProp
    if (lifecycle?.levels) return lifecycle.levels
    return computeExecutionLevels(alert, isDerivative, currentPrice) || {}
  }, [levelsProp, lifecycle, alert, isDerivative, currentPrice])

  const hedgedSpreadData = useMemo(() => {
    const isIronCondorAlert = Boolean(
      hedgedSpread?.strategy_name === 'IRON_CONDOR' ||
      alert?.alert_type === 'DEFINED_RISK_NEUTRAL' ||
      alert?.alert_type === 'IRON_CONDOR_PINNING' ||
      (alert?.headline || '').includes('CONDOR') ||
      (alert?.summary || '').includes('Iron Condor') ||
      alert?.condor_corridor ||
      alert?.profit_corridor ||
      alert?.actionable_plan?.profit_corridor ||
      alert?.metrics?.short_put_strike ||
      alert?.metrics?.strategy === 'IRON_CONDOR'
    )

    if (!hedgedSpread && !isIronCondorAlert) return null

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
      const cleanSymLeg = (leg.symbol || '').replace(/^(NSE|BSE|NFO|MCX|BFO|CDS|CRYPTO|BINANCE):/, '')
      const strikeLabel = strike ? `${Math.round(strike)} ${optionType}`.trim() : cleanSymLeg
      const premiumLabel = premium !== null ? `₹${formatNum(premium)}` : '—'
      const fullText = `${strikeLabel}${premium !== null ? ` @ ₹${formatNum(premium)}` : ''}`

      return {
        action,
        strike,
        optionType,
        premium,
        symbol: cleanSymLeg,
        strikeLabel,
        premiumLabel,
        quantity: leg.quantity || leg.lot_size || null,
        fullText,
      }
    }

    let allLegs = (hedgedSpread && Array.isArray(hedgedSpread.legs) && hedgedSpread.legs.length > 0)
      ? hedgedSpread.legs.map((l) => parseLegObj(l, l.side || l.action || 'BUY'))
      : []

    let buyLeg = null
    let sellLeg = null

    if (hedgedSpread && Array.isArray(hedgedSpread.legs) && hedgedSpread.legs.length >= 2) {
      const b = hedgedSpread.legs.find((l) => (l.side || l.action || '').toUpperCase() === 'BUY') || hedgedSpread.legs[0]
      const s = hedgedSpread.legs.find((l) => (l.side || l.action || '').toUpperCase() === 'SELL') || hedgedSpread.legs[1]
      buyLeg = parseLegObj(b, 'BUY')
      sellLeg = parseLegObj(s, 'SELL')
    } else if (hedgedSpread) {
      buyLeg = parseLegObj(hedgedSpread.long_leg, 'BUY')
      sellLeg = parseLegObj(hedgedSpread.short_leg, 'SELL')
    }

    const isIronCondor = Boolean(
      hedgedSpread?.strategy_name === 'IRON_CONDOR' ||
      isIronCondorAlert ||
      allLegs.length === 4
    )

    // Condor strikes resolution (robust synthesis when raw legs array is absent)
    const corridorRaw = alert?.condor_corridor ||
      alert?.profit_corridor ||
      alert?.actionable_plan?.profit_corridor ||
      hedgedSpread?.profit_corridor ||
      alert?.headline ||
      alert?.summary || ''
    const cMatch = corridorRaw.match(/(\d[\d,]+)\s*(?:[-–to\s]+)[₹$]?\s*(\d[\d,]+)/i)

    let shortPut = hedgedSpread?.short_put_strike ? Number(hedgedSpread.short_put_strike) : (alert?.metrics?.short_put_strike ? Number(alert.metrics.short_put_strike) : null)
    let shortCall = hedgedSpread?.short_call_strike ? Number(hedgedSpread.short_call_strike) : (alert?.metrics?.short_call_strike ? Number(alert.metrics.short_call_strike) : null)
    if (!shortPut && cMatch) shortPut = Number(cMatch[1].replace(/,/g, ''))
    if (!shortCall && cMatch) shortCall = Number(cMatch[2].replace(/,/g, ''))

    let longPut = hedgedSpread?.long_put_strike ? Number(hedgedSpread.long_put_strike) : (alert?.metrics?.long_put_strike ? Number(alert.metrics.long_put_strike) : null)
    let longCall = hedgedSpread?.long_call_strike ? Number(hedgedSpread.long_call_strike) : (alert?.metrics?.long_call_strike ? Number(alert.metrics.long_call_strike) : null)

    if (shortPut && shortCall && (!longPut || !longCall)) {
      let wingOffset = 300
      if (cleanSym.includes('NIFTY') && !cleanSym.includes('BANK')) wingOffset = 150
      else if (cleanSym.includes('FINNIFTY')) wingOffset = 150
      else if (cleanSym.includes('MIDCPNIFTY')) wingOffset = 100
      else if (cleanSym.includes('BANKNIFTY') || cleanSym.includes('SENSEX') || cleanSym.includes('BANKEX')) wingOffset = 300

      if (!longPut) longPut = shortPut - wingOffset
      if (!longCall) longCall = shortCall + wingOffset
    }

    // Synthesize 4 legs if allLegs is incomplete for an Iron Condor
    if (isIronCondor && allLegs.length < 4 && shortPut && shortCall && longPut && longCall) {
      allLegs = [
        {
          action: 'BUY',
          strike: longPut,
          optionType: 'PE',
          strikeLabel: `${Math.round(longPut)} PE`,
          premium: null,
          premiumLabel: 'Wing Hedge',
          symbol: `${cleanSym} ${Math.round(longPut)} PE`,
          fullText: `BUY ${Math.round(longPut)} PE`,
        },
        {
          action: 'SELL',
          strike: shortPut,
          optionType: 'PE',
          strikeLabel: `${Math.round(shortPut)} PE`,
          premium: null,
          premiumLabel: 'Short Put',
          symbol: `${cleanSym} ${Math.round(shortPut)} PE`,
          fullText: `SELL ${Math.round(shortPut)} PE`,
        },
        {
          action: 'SELL',
          strike: shortCall,
          optionType: 'CE',
          strikeLabel: `${Math.round(shortCall)} CE`,
          premium: null,
          premiumLabel: 'Short Call',
          symbol: `${cleanSym} ${Math.round(shortCall)} CE`,
          fullText: `SELL ${Math.round(shortCall)} CE`,
        },
        {
          action: 'BUY',
          strike: longCall,
          optionType: 'CE',
          strikeLabel: `${Math.round(longCall)} CE`,
          premium: null,
          premiumLabel: 'Wing Hedge',
          symbol: `${cleanSym} ${Math.round(longCall)} CE`,
          fullText: `BUY ${Math.round(longCall)} CE`,
        },
      ]
    }

    const flowType = isIronCondor ? 'NET_CREDIT' : (hedgedSpread?.flow_type || (hedgedSpread?.net_cashflow < 0 ? 'NET_CREDIT' : 'NET_DEBIT'))
    const profitCorridor = hedgedSpread?.profit_corridor || (shortPut && shortCall ? `₹${formatNum(shortPut)} – ₹${formatNum(shortCall)}` : null)
    const netCreditUnit = levels?.entry || (alert?.entry ? Number(alert.entry) : null)
    const breakevensStr = hedgedSpread?.breakevens ||
      (hedgedSpread?.breakeven_points && hedgedSpread.breakeven_points.length >= 2
        ? `₹${formatNum(hedgedSpread.breakeven_points[0])} – ₹${formatNum(hedgedSpread.breakeven_points[1])}`
        : (shortPut && shortCall && netCreditUnit ? `₹${formatNum(shortPut - netCreditUnit)} – ₹${formatNum(shortCall + netCreditUnit)}` : null))

    // Fallbacks if vertical spread legs were not complete:
    const fallbackBuyStrike = hedgedSpread?.buy_strike || optPlan?.strike || alert?.strike
    const fallbackSellStrike = hedgedSpread?.sell_strike || hedgedSpread?.hedge_strike
    const fallbackOptType = hedgedSpread?.option_type || optPlan?.option_type || alert?.option_type || (isBull ? 'CE' : 'PE')

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
      const sPrem = hedgedSpread?.hedge_premium || optPlan?.hedge_premium || null
      sellLeg = {
        action: 'SELL',
        strike: sStrike,
        optionType: fallbackOptType,
        premium: sPrem,
        strikeLabel: `${Math.round(sStrike)} ${fallbackOptType}`,
        premiumLabel: sPrem !== null ? `₹${formatNum(sPrem)}` : '—',
        symbol: hedgedSpread?.hedge_contract_symbol || `${alert?.symbol || ''} ${Math.round(sStrike)} ${fallbackOptType}`.trim(),
        fullText: `${Math.round(sStrike)} ${fallbackOptType}${sPrem ? ` @ ₹${formatNum(sPrem)}` : ''}`,
      }
    }

    const _lotSz = lotSize || 1
    const netDebit = hedgedSpread?.net_debit_per_unit
      ?? (buyLeg?.premium != null && sellLeg?.premium != null
          ? Math.max(0.1, Math.round(Math.abs(buyLeg.premium - sellLeg.premium) * 100) / 100)
          : null)
      ?? (hedgedSpread?.net_cashflow != null && lotSize
          ? Math.round((hedgedSpread.net_cashflow / _lotSz) * 100) / 100
          : null)
      ?? hedgedSpread?.net_debit
      ?? null

    let maxProfit = hedgedSpread?.max_profit_pts ?? hedgedSpread?.max_profit ?? null
    if (maxProfit === null && isIronCondor && netCreditUnit) {
      maxProfit = Math.round(netCreditUnit * _lotSz)
    } else if (maxProfit === null && buyLeg?.strike && sellLeg?.strike && netDebit) {
      maxProfit = Math.max(0, Math.round((Math.abs(buyLeg.strike - sellLeg.strike) - netDebit) * 100) / 100)
    }

    let maxLoss = hedgedSpread?.max_loss ?? null
    if (maxLoss === null && isIronCondor) {
      const slUnit = levels?.sl || (alert?.sl ? Number(alert.sl) : null)
      if (slUnit) maxLoss = Math.round(slUnit * _lotSz)
    } else if (maxLoss === null && netDebit && lotSize) {
      maxLoss = Math.round(netDebit * _lotSz)
    }

    const rrRatio = hedgedSpread?.spread_rr ?? (
      hedgedSpread?.risk_reward_ratio
        ? `1:${hedgedSpread.risk_reward_ratio}`
        : (maxProfit && maxLoss && maxLoss > 0 ? `1:${(maxProfit / maxLoss).toFixed(1)}` : '1:2.0')
    )

    const _rawBreakeven = hedgedSpread?.breakeven_point ?? hedgedSpread?.breakeven_spot ?? (
      buyLeg?.strike && netDebit
        ? (isBull ? buyLeg.strike + netDebit : buyLeg.strike - netDebit)
        : null
    )
    const breakeven = (_rawBreakeven && buyLeg?.strike && _rawBreakeven > 0 && _rawBreakeven < buyLeg.strike * 1.5)
      ? _rawBreakeven
      : null

    const spreadName = hedgedSpread?.spread_name || (
      hedgedSpread?.strategy_name ? hedgedSpread.strategy_name.replace(/_/g, ' ') : (isIronCondor ? 'Defined-Risk Iron Condor' : isBull ? 'Bull Call Spread' : 'Bear Put Spread')
    )
    const guidance = hedgedSpread?.guidance || hedgedSpread?.thesis || (
      isIronCondor && shortPut && shortCall
        ? `Collect net credit of ₹${formatNum(netCreditUnit || 0)}/unit (₹${formatNum(maxProfit || 0)}/lot). Full profit retained if ${cleanSym} expires within [₹${formatNum(shortPut)} – ₹${formatNum(shortCall)}]. Close 50% on +50% decay (₹${formatNum((netCreditUnit || 0) * 0.5)}) and ratchet stop-loss to cost.`
        : `${hedgedSpread?.theta_reduction_pct || 75}% Theta decay offset via short leg.`
    )
    const thetaReductionPct = hedgedSpread?.theta_reduction_pct ? `${hedgedSpread.theta_reduction_pct}%` : '75%'

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
      allLegs,
      isIronCondor,
      flowType,
      profitCorridor,
      breakevensStr,
    }
  }, [hedgedSpread, optPlan, alert, isBull, levels, lotSize, cleanSym])

  const hasLevels = Boolean(
    (levels?.entry !== null && levels?.entry !== undefined) ||
    (levels?.sl !== null && levels?.sl !== undefined) ||
    (levels?.t1 !== null && levels?.t1 !== undefined)
  )

  const formatPnl = (pnl) => {
    if (pnl === null || pnl === undefined || isNaN(pnl)) return null
    const n = Number(pnl)
    const sign = n >= 0 ? '+' : ''
    return `${sign}${currSym}${n.toLocaleString(isCrypto ? 'en-US' : 'en-IN')}`
  }

  const isNeutralSpread = Boolean(
    lifecycle?.isNeutralSpread ||
    levels?.isNeutralSpread ||
    alert?.alert_type === 'DEFINED_RISK_NEUTRAL' ||
    (alert?.headline || '').includes('CONDOR') ||
    hedgedSpreadData?.isIronCondor
  )

  const isUpward = (levels && levels.isUpwardPayoff !== undefined)
    ? levels.isUpwardPayoff
    : (isDerivative ? !isOptionSell : isBull)

  const isTrailedInProfit = Boolean(
    levels?.sl && levels?.entry && (isUpward ? levels?.sl >= levels?.entry : levels?.sl <= levels?.entry)
  )

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
  if (levels?.entry && levels?.t1 && currentPrice && !isSLHit && !isT1Hit) {
    const total = Math.abs(levels?.t1 - levels?.entry)
    const current = Math.abs(currentPrice - levels?.entry)
    const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((current / total) * 100))) : 0
    const remPts = Math.abs(levels?.t1 - currentPrice)
    t1DistInfo = { pct, remPts }
  }

  let t2DistInfo = null
  if (levels?.t1 && levels?.t2 && currentPrice && isT1Hit && !isT2Hit) {
    const total = Math.abs(levels?.t2 - levels?.t1)
    const current = Math.abs(currentPrice - levels?.t1)
    const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((current / total) * 100))) : 0
    const remPts = Math.abs(levels?.t2 - currentPrice)
    t2DistInfo = { pct, remPts }
  }

  let t3DistInfo = null
  if (levels?.t2 && levels?.t3 && currentPrice && isT2Hit && !isT3Hit) {
    const total = Math.abs(levels?.t3 - levels?.t2)
    const current = Math.abs(currentPrice - levels?.t2)
    const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((current / total) * 100))) : 0
    const remPts = Math.abs(levels?.t3 - currentPrice)
    t3DistInfo = { pct, remPts }
  }

  // Visual Runway Progress Percentage
  let progressPct = 30
  if (currentPrice && levels?.sl && levels?.t3 && levels?.t3 !== levels?.sl) {
    const totalSpan = Math.abs(levels?.t3 - levels?.sl)
    const currentDist = isUpward ? currentPrice - levels?.sl : levels?.sl - currentPrice
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

  const isStagnant = Boolean(
    lifecycle?.isTimeStop ||
    alert?.theta_scratch_recommended ||
    (alert?.headline || '').toUpperCase().includes('STAGNATION') ||
    (alert?.headline || '').toUpperCase().includes('SCRATCH') ||
    (alert?.summary || '').toUpperCase().includes('SCRATCH') ||
    alert?.stage === 'TIME_STOP_EXIT' ||
    alert?.stage === 'VELOCITY_STAGNATION_SCRATCH'
  )

  const noChaseLimit = Number(levels.no_chase_boundary || (levels?.entry ? (isUpward ? levels?.entry * 1.05 : levels?.entry * 0.95) : 0))
  const isExtended = Boolean(
    !isTerminal && !isStagnant && !isSLHit && !isInvalidated && currentPrice && noChaseLimit && (
      isUpward ? currentPrice > noChaseLimit : currentPrice < noChaseLimit
    )
  )
  const extendedPct = isExtended && levels?.entry
    ? Math.abs(((currentPrice - levels?.entry) / levels?.entry) * 100).toFixed(1)
    : null

  const pyramidRule = alert.actionable_plan?.pyramid_rule || alert.metrics?.pyramid_rule || tp.pyramid_rule
  const structuralFloor50 = alert.actionable_plan?.structural_floor_50sma || alert.metrics?.structural_floor_50sma || tp.structural_floor_50sma

  const expBadge = expiryInfo?.formatted
    ? `⏳ ${expiryInfo.formatted}${expiryInfo.dte !== null ? ` (${expiryInfo.dte} DTE)` : ''}`
    : expiryInfo?.expiry_date
    ? `⏳ Exp: ${expiryInfo.expiry_date}`
    : null

  const [isPlaybookExpanded, setIsPlaybookExpanded] = React.useState(true)
  const [isSpreadExpanded, setIsSpreadExpanded] = React.useState(true)

  return (
    <div className={`rounded-xl p-2 border transition-all duration-200 bg-panel/90 dark:bg-surface/80 space-y-1.5 shadow-sm ${
      isSLHit ? 'border-rose-300 dark:border-rose-500/40 bg-rose-50/50 dark:bg-rose-500/5' : isT3Hit ? 'border-purple-300 dark:border-purple-500/40 bg-purple-50/50 dark:bg-purple-500/5' : isT2Hit ? 'border-cyan-300 dark:border-cyan-500/40 bg-cyan-50/50 dark:bg-cyan-500/5' : isT1Hit ? 'border-emerald-300 dark:border-emerald-500/40 bg-emerald-50/50 dark:bg-emerald-500/5' : 'border-border/60 dark:border-border/40'
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
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-300 dark:bg-rose-500/25 dark:text-rose-300 dark:border-rose-500/50 animate-pulse">
              🛑 STOP LOSS HIT
            </span>
          ) : isT3Hit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-800 border border-purple-300 dark:bg-purple-500/25 dark:text-purple-200 dark:border-purple-400/50 animate-pulse">
              🚀 ALL TARGETS HIT
            </span>
          ) : isT2Hit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-cyan-100 text-cyan-800 border border-cyan-300 dark:bg-cyan-500/25 dark:text-cyan-200 dark:border-cyan-400/50 animate-pulse">
              🏁 T2 HIT · RUNNER ACTIVE
            </span>
          ) : isT1Hit ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/25 dark:text-emerald-200 dark:border-emerald-400/50 animate-pulse">
              🎯 T1 HIT · 50% BOOKED · SL RISK-FREE
            </span>
          ) : currentPrice && levels?.entry ? (
            <span className="text-[10px] font-black px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 dark:bg-gold/15 dark:text-gold dark:border-gold/30">
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
            <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/25">
              {expBadge}
            </span>
          )}
        </div>
      </div>

      {/* 5-Column High-Density Stage Grid */}
      {hasLevels && (
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 font-mono text-xs">
        {/* 1. STOP LOSS */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isSLHit
            ? 'bg-rose-500/25 border-2 border-rose-500 ring-2 ring-rose-500/40 shadow-[0_0_12px_rgba(244,63,94,0.3)] animate-pulse'
            : isTrailedInProfit
            ? 'bg-cyan-50/80 dark:bg-cyan-500/10 border border-cyan-300 dark:border-cyan-500/35 shadow-xs'
            : 'bg-rose-50/80 dark:bg-rose-500/5 border border-rose-200 dark:border-rose-500/20'
        }`}>
          <div className="flex items-center justify-between text-[11px]">
            <span className={`font-black uppercase tracking-wider ${isSLHit ? 'text-rose-100 dark:text-rose-200' : isTrailedInProfit ? 'text-cyan-800 dark:text-cyan-300' : 'text-rose-700 dark:text-rose-400'}`}>
              {isNeutralSpread ? '🛑 Max Loss (Capped)' : isSLHit ? '🛑 SL Breached' : isTrailedInProfit ? '🛡️ Trailed SL' : '🛑 Invalidation SL'}
            </span>
            <span className={`font-bold ${isSLHit ? 'text-rose-100 bg-rose-600/80 px-1 rounded' : isTrailedInProfit ? 'text-cyan-900 bg-cyan-100 dark:text-cyan-300 dark:bg-cyan-500/20 px-1 rounded' : 'text-rose-700 dark:text-rose-400'}`}>
              {isSLHit ? 'BREACHED' : isTrailedInProfit ? '🔒 PROFIT LOCKED' : isNeutralSpread ? 'CAPPED' : levels?.sl_pct ? `-${levels?.sl_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isSLHit ? 'text-white' : isTrailedInProfit ? 'text-cyan-900 dark:text-cyan-200' : 'text-rose-900 dark:text-rose-300'}`}>
            {currSym}{formatNum(levels?.sl)}
          </div>
          {trailingStop ? (
            <div className="text-[10px] text-cyan-800 dark:text-cyan-300 font-bold truncate">
              ⚡ Trail {currSym}{formatNum(trailingStop)}
            </div>
          ) : levels.max_loss !== null && levels.max_loss !== undefined ? (
            <div className="text-[10px] text-rose-700 dark:text-rose-400 font-bold truncate" title="Maximum Risk per lot (incl. STT & slippage)">
              Risk: -{currSym}{formatNum(levels.max_loss)}/lot
            </div>
          ) : levels.optPlanRef?.sl_pnl_per_lot !== undefined ? (
            <div className="text-[10px] text-rose-700/80 dark:text-rose-400/80 font-bold">
              {formatPnl(levels.optPlanRef.sl_pnl_per_lot)}
            </div>
          ) : null}
        </div>

        {/* 2. ENTRY TRIGGER */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isExtended
            ? 'bg-amber-100/80 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/40 shadow-sm'
            : currentPrice && !isSLHit
            ? 'bg-amber-50/90 dark:bg-gold/15 border border-amber-300 dark:border-gold/50 shadow-sm'
            : 'bg-amber-50/60 dark:bg-gold/5 border border-amber-200 dark:border-gold/25'
        }`}>
          <div className="flex items-center justify-between text-[11px]">
            <span className={`font-black uppercase tracking-wider ${isExtended ? 'text-amber-800 dark:text-amber-400' : 'text-amber-800 dark:text-gold'}`}>
              {isNeutralSpread ? '⚡ Net Credit' : isExtended ? '🛑 No Chase' : '⚡ Entry Trigger'}
            </span>
            <span className={`font-bold ${isExtended ? 'text-amber-900 bg-amber-200/80 dark:text-amber-300 dark:bg-amber-500/20 px-1 rounded' : 'text-amber-800 dark:text-amber-300'}`}>
              {isNeutralSpread ? 'CREDIT' : isExtended ? `EXTENDED +${extendedPct}%` : (isUpward ? 'BUY' : 'SELL')}
            </span>
          </div>
          <div className="text-xs font-black text-amber-950 dark:text-amber-200 mt-0.5">
            {currSym}{formatNum(levels?.entry)}
          </div>
          {isExtended ? (
            <div className="text-[10px] text-amber-800 dark:text-amber-300 font-bold truncate" title="Price is extended beyond buy zone. Wait for pullback to 50-SMA or secondary base consolidation.">
              ⏳ WAIT FOR PULLBACK
            </div>
          ) : levels?.entry_range ? (
            <div className="text-[10px] text-amber-800/90 dark:text-amber-300/90 font-mono font-medium truncate" title="Optimal Trade Entry (OTE) Pullback Range">
              🎯 OTE {levels?.entry_range}
            </div>
          ) : null}
          {levels?.no_chase_boundary ? (
            <div
              className="text-[10px] text-rose-700 dark:text-rose-400 font-bold truncate"
              title={
                levels.spot_no_chase_boundary
                  ? `No-Chase Option Limit: ${currSym}${formatNum(levels.no_chase_boundary)} (Underlying Spot Max: ${currSym}${formatNum(levels.spot_no_chase_boundary)})`
                  : 'No-Chase Maximum Entry Limit'
              }
            >
              🛑 NoChase {currSym}{formatNum(levels.no_chase_boundary)}
              {levels.spot_no_chase_boundary && (
                <span className="text-[9px] text-zinc-500 dark:text-zinc-400 ml-1 font-normal hidden xl:inline" title="Underlying Spot Breakout Ceiling">
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
            ? 'bg-emerald-50/80 dark:bg-emerald-500/10 border border-emerald-300 dark:border-emerald-500/40'
            : 'bg-emerald-50/50 dark:bg-emerald-500/5 border border-emerald-200 dark:border-emerald-500/20'
        }`}>
          <div className="flex items-center justify-between text-[11px]">
            <span className={`font-black uppercase tracking-wider ${isT1Hit ? 'text-emerald-100 dark:text-emerald-200' : 'text-emerald-800 dark:text-emerald-400'}`}>
              {isNeutralSpread ? '🎯 50% Decay Target' : '🎯 Target 1 (T1)'}
            </span>
            <span className={`font-bold ${isT1Hit ? 'text-emerald-950 bg-emerald-200 dark:text-emerald-100 dark:bg-emerald-600/70 px-1 rounded' : 'text-emerald-800 dark:text-emerald-400'}`}>
              {isT1Hit ? '✅ HIT!' : isNeutralSpread ? '-50% THETA' : levels.net_risk_reward ? `Net ${levels.net_risk_reward}` : levels?.t1_rr ? `${levels?.t1_rr}R` : levels?.t1_pct ? `+${levels?.t1_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isT1Hit ? 'text-emerald-950 dark:text-white' : 'text-emerald-900 dark:text-emerald-300'}`}>
            {currSym}{formatNum(levels?.t1)}
          </div>
          {t1DistInfo && !isT1Hit ? (
            <div className="text-[10px] text-emerald-800 dark:text-emerald-300 font-bold truncate">
              {t1DistInfo.pct}% · {currSym}{formatNum(t1DistInfo.remPts)} away
            </div>
          ) : isT1Hit ? (
            <div className="text-[10px] text-emerald-800 dark:text-emerald-200 font-bold truncate">
              50% Booked · SL BE
            </div>
          ) : null}
        </div>

        {/* 4. TARGET 2 */}
        <div className={`p-1.5 rounded-lg transition-all ${
          isT2Hit
            ? 'bg-cyan-500/25 border-2 border-cyan-400 ring-2 ring-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.3)] animate-pulse'
            : activeStage === 'T2'
            ? 'bg-cyan-50/80 dark:bg-cyan-500/10 border border-cyan-300 dark:border-cyan-500/40'
            : 'bg-cyan-50/50 dark:bg-cyan-500/5 border border-cyan-200 dark:border-cyan-500/20'
        }`}>
          <div className="flex items-center justify-between text-[11px]">
            <span className={`font-black uppercase tracking-wider ${isT2Hit ? 'text-cyan-100 dark:text-cyan-200' : 'text-cyan-800 dark:text-cyan-400'}`}>
              {isNeutralSpread ? '🏁 80% Decay Target' : '🏁 Target 2 (T2)'}
            </span>
            <span className={`font-bold ${isT2Hit ? 'text-cyan-950 bg-cyan-200 dark:text-cyan-100 dark:bg-cyan-600/70 px-1 rounded' : 'text-cyan-800 dark:text-cyan-400'}`}>
              {isT2Hit ? '✅ HIT!' : isNeutralSpread ? '-80% THETA' : levels?.t2_rr ? `${levels?.t2_rr}R` : levels?.t2_pct ? `+${levels?.t2_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isT2Hit ? 'text-cyan-950 dark:text-white' : 'text-cyan-900 dark:text-cyan-300'}`}>
            {currSym}{formatNum(levels?.t2)}
          </div>
          {t2DistInfo && !isT2Hit ? (
            <div className="text-[10px] text-cyan-800 dark:text-cyan-300 font-bold truncate">
              {t2DistInfo.pct}% · {currSym}{formatNum(t2DistInfo.remPts)} away
            </div>
          ) : isT2Hit ? (
            <div className="text-[10px] text-cyan-800 dark:text-cyan-200 font-bold truncate">
              Runner Locked
            </div>
          ) : null}
        </div>

        {/* 5. TARGET 3 */}
        <div className={`p-1.5 rounded-lg transition-all col-span-2 sm:col-span-1 ${
          isT3Hit
            ? 'bg-purple-500/30 border-2 border-purple-400 ring-2 ring-purple-500/60 shadow-[0_0_16px_rgba(168,85,247,0.4)] animate-pulse'
            : activeStage === 'T3'
            ? 'bg-purple-50/80 dark:bg-purple-500/10 border border-purple-300 dark:border-purple-500/40'
            : 'bg-purple-50/50 dark:bg-purple-500/5 border border-purple-200 dark:border-purple-500/20'
        }`}>
          <div className="flex items-center justify-between text-[11px]">
            <span className={`font-black uppercase tracking-wider ${isT3Hit ? 'text-purple-100' : 'text-purple-800 dark:text-purple-300'}`}>
              {isNeutralSpread ? '🚀 Max Profit (Expiry)' : '🚀 Target 3 (T3)'}
            </span>
            <span className={`font-bold ${isT3Hit ? 'text-purple-950 bg-purple-200 dark:text-purple-100 dark:bg-purple-600/70 px-1 rounded' : 'text-purple-800 dark:text-purple-300'}`}>
              {isT3Hit ? '🚀 MOONSHOT!' : isNeutralSpread ? '100% THETA' : levels?.t3_rr ? `${levels?.t3_rr}R` : levels?.t3_pct ? `+${levels?.t3_pct}%` : '—'}
            </span>
          </div>
          <div className={`text-xs font-black mt-0.5 ${isT3Hit ? 'text-purple-950 dark:text-white' : 'text-purple-900 dark:text-purple-200'}`}>
            {currSym}{formatNum(isNeutralSpread ? levels?.entry : levels?.t3)}
          </div>
          {t3DistInfo && !isT3Hit ? (
            <div className="text-[10px] text-purple-800 dark:text-purple-300 font-bold truncate">
              {t3DistInfo.pct}% · {currSym}{formatNum(t3DistInfo.remPts)} away
            </div>
          ) : isT3Hit ? (
            <div className="text-[10px] text-purple-800 dark:text-purple-200 font-bold truncate">
              Max Profit Hit
            </div>
          ) : alert?.actionable_plan?.runner_strike?.symbol ? (
            <div className="text-[10px] font-mono text-purple-800 dark:text-purple-300 font-bold truncate" title={`High-Beta Runner: ${alert.actionable_plan.runner_strike.symbol}`}>
              ⚡ {alert.actionable_plan.runner_strike.symbol.replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '')}
            </div>
          ) : null}
        </div>
      </div>
      )}

      {/* Fallback card when execution levels are calibrating */}
      {!hasLevels && (
        <div className="rounded-xl border border-amber-300 dark:border-amber-500/35 bg-amber-50/70 dark:bg-gradient-to-b dark:from-[#1c1404] dark:via-[#120d02] dark:to-[#0a0701] p-3 space-y-2 text-xs shadow-sm">
          <div className="flex items-center justify-between flex-wrap gap-2 pb-1.5 border-b border-amber-300/40 dark:border-amber-500/20 font-mono">
            <div className="flex items-center gap-2">
              <span className="text-amber-600 dark:text-amber-400 text-sm">⏳</span>
              <span className="font-black text-amber-900 dark:text-amber-200 uppercase tracking-wider">
                {alert?.alert_type ? alert.alert_type.replace(/_/g, ' ') : 'MOMENTUM BREAKOUT'} · CALIBRATING
              </span>
            </div>
            <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-500/40 text-[10px] font-bold">
              AWAITING L2 ORDER BOOK DEPTH
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 font-mono text-[11px]">
            <div className="p-2 rounded bg-panel/90 dark:bg-surface/80 border border-amber-300/60 dark:border-amber-500/20">
              <span className="text-slate-500 dark:text-zinc-400 text-[9.5px] uppercase block font-semibold">Contract / Vehicle</span>
              <span className="font-bold text-slate-900 dark:text-white text-xs mt-0.5 block truncate">
                {isDerivative ? `BUY ${cleanSym} ${alert.strike || ''} ${alert.option_type || 'CE'}` : `BUY ${cleanSym}`}
              </span>
              <span className="text-[9.5px] text-slate-500 dark:text-zinc-400">Lot Size: {lotSize || '—'} units</span>
            </div>

            <div className="p-2 rounded bg-panel/90 dark:bg-surface/80 border border-amber-300/60 dark:border-amber-500/20">
              <span className="text-slate-500 dark:text-zinc-400 text-[9.5px] uppercase block font-semibold">Entry Execution Rule</span>
              <span className="font-sans text-slate-700 dark:text-slate-200 text-[10.5px] mt-0.5 block leading-snug">
                Wait for 1m candle close confirmation above resistance with volume expansion.
              </span>
            </div>

            <div className="p-2 rounded bg-panel/90 dark:bg-surface/80 border border-amber-300/60 dark:border-amber-500/20">
              <span className="text-slate-500 dark:text-zinc-400 text-[9.5px] uppercase block font-semibold">De-Risk &amp; Profit Rule</span>
              <span className="font-sans text-slate-700 dark:text-slate-200 text-[10.5px] mt-0.5 block leading-snug">
                Scale 50% at +2R (+25% to +35% premium surge) &amp; ratchet SL to Cost.
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Slim 2px Visual Runway Progress Indicator (Zero Duplicate Text) */}
      {hasLevels && (
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
      )}

      {/* ── Institutional Broker Pre-Order (STAGE PRIMED) ── */}
      {(alert?.stage === 'PRIMED' || alert?.actionable_plan?.broker_order_type === 'BUY SL-LIMIT' || alert?.actionable_plan?.sl_limit_trigger) && (
        <div className="p-2 rounded-lg bg-amber-50 dark:bg-amber-500/15 border border-amber-300 dark:border-amber-400/50 flex flex-col gap-1.5 text-[11px]">
          <div className="flex items-center justify-between">
            <span className="font-black text-amber-800 dark:text-amber-300 flex items-center gap-1.5 uppercase tracking-wide">
              <span>⚡</span> BROKER PRE-ORDER: {alert?.actionable_plan?.broker_order_type || 'BUY SL-LIMIT'}
            </span>
            <span className="text-[10px] font-mono font-bold text-amber-800 bg-amber-100 dark:text-amber-200 dark:bg-amber-500/25 px-2 py-0.5 rounded border border-amber-300 dark:border-amber-400/40">
              STAGE PRIMED · ZERO LATENCY
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-[11px] font-mono">
            <div className="bg-panel/90 dark:bg-surface/80 border border-amber-300/60 dark:border-amber-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Trigger</span>
              <span className="font-black text-amber-800 dark:text-amber-300">{currSym}{formatNum(alert?.actionable_plan?.sl_limit_trigger || levels?.entry)}</span>
            </div>
            <div className="bg-panel/90 dark:bg-surface/80 border border-amber-300/60 dark:border-amber-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Limit Price</span>
              <span className="font-black text-slate-900 dark:text-text">{currSym}{formatNum(alert?.actionable_plan?.sl_limit_price || levels?.entry)}</span>
            </div>
            <div className="bg-panel/90 dark:bg-surface/80 border border-rose-300/60 dark:border-rose-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Stop Loss</span>
              <span className="font-black text-rose-700 dark:text-rose-400">{currSym}{formatNum(levels?.sl)}</span>
            </div>
            <div className="bg-panel/90 dark:bg-surface/80 border border-emerald-300/60 dark:border-emerald-500/30 px-2 py-1 rounded">
              <span className="text-muted block text-[10px] uppercase font-bold tracking-wider">Target 1 (+2R)</span>
              <span className="font-black text-emerald-800 dark:text-emerald-300">{currSym}{formatNum(levels?.t1)}</span>
            </div>
          </div>
          <div className="text-[10px] text-amber-800 dark:text-amber-200/90 flex items-center gap-1 font-sans">
            <span>💡</span>
            <span>Stage pending SL-Limit order in broker OMS now. Exchange matching engine will auto-fill on breach with zero execution latency.</span>
          </div>
        </div>
      )}

      {/* ── Institutional Defined-Risk Vertical Spread Blueprint ── */}
      {hedgedSpreadData && (
        <div className="rounded-xl border border-sky-300 dark:border-sky-500/40 bg-sky-50/50 dark:bg-gradient-to-b dark:from-[#0c182c] dark:via-[#091222] dark:to-[#060c18] p-3 space-y-2.5 shadow-sm text-xs">
          {/* Header Bar: Strategy & Key Metrics */}
          <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-sky-300/40 dark:border-sky-500/25">
            <button
              type="button"
              onClick={() => setIsSpreadExpanded(prev => !prev)}
              className="flex items-center gap-2 flex-wrap hover:opacity-80 transition-opacity text-left"
              title={isSpreadExpanded ? 'Collapse Spread Details' : 'Expand Spread Details'}
            >
              <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-300 text-xs shadow-inner border border-sky-300 dark:border-sky-400/30">
                🛡️
              </span>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-black text-slate-900 dark:text-white uppercase tracking-wider text-xs sm:text-[13px] font-sans">
                  {hedgedSpreadData.spreadName || 'DEFINED-RISK VERTICAL SPREAD'}
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10.5px] font-mono font-bold uppercase tracking-wider bg-sky-100 text-sky-800 border border-sky-300 dark:bg-sky-500/15 dark:text-sky-200 dark:border-sky-400/30">
                  THETA-NEUTRAL HEDGE
                </span>
                <span className="text-[10px] text-muted ml-0.5">{isSpreadExpanded ? '▲' : '▼'}</span>
              </div>
            </button>

            <div className="flex items-center gap-1.5 flex-wrap font-mono">
              <span className="px-2 py-0.5 rounded-md bg-sky-100 text-sky-900 border border-sky-300 dark:bg-sky-900/60 dark:text-sky-200 dark:border-sky-400/30 font-bold text-[10.5px]">
                R:R <span className="text-slate-950 dark:text-white font-black">{hedgedSpreadData.rrRatio}</span>
              </span>
              {hedgedSpreadData.maxProfit !== null && (
                <span className="px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-900 border border-emerald-300 dark:bg-emerald-950/80 dark:text-emerald-300 dark:border-emerald-500/40 font-bold text-[10.5px]">
                  Max Profit: <span className="text-slate-950 dark:text-white font-black">₹{formatNum(hedgedSpreadData.maxProfit)}</span>
                </span>
              )}
            </div>
          </div>

          {/* Multi-Leg Spread Matrix: 4-Leg Grid for Iron Condors or 3-Column for Vertical Spreads */}
          {isSpreadExpanded && (hedgedSpreadData.isIronCondor && hedgedSpreadData.allLegs.length === 4 ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono">
                {hedgedSpreadData.allLegs.map((leg, idx) => {
                  const isBuy = leg.action === 'BUY'
                  return (
                    <div
                      key={idx}
                      className={`p-2.5 rounded-lg border transition-all flex flex-col justify-between shadow-sm ${
                        isBuy
                          ? 'bg-emerald-50/80 dark:bg-gradient-to-b dark:from-[#082318] dark:to-[#04140d] border-emerald-300 dark:border-emerald-500/40 hover:border-emerald-400/70'
                          : 'bg-rose-50/80 dark:bg-gradient-to-b dark:from-[#290d15] dark:to-[#16050a] border-rose-300 dark:border-rose-500/40 hover:border-rose-400/70'
                      }`}
                    >
                      <div className="flex items-center justify-between pb-1 border-b border-border/40 dark:border-white/10">
                        <div className="flex items-center gap-1">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-black uppercase tracking-wider shadow-sm ${
                            isBuy ? 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950' : 'bg-rose-600 text-white dark:bg-rose-500'
                          }`}>
                            {isBuy ? 'BUY +1' : 'SELL -1'}
                          </span>
                          <span className={`text-[10px] font-bold ${isBuy ? 'text-emerald-800 dark:text-emerald-300/90' : 'text-rose-800 dark:text-rose-300/90'}`}>
                            {isBuy ? 'Wing' : 'Short'}
                          </span>
                        </div>
                        <span className={`text-[10px] font-bold ${isBuy ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}>
                          {leg.optionType || 'OPTION'}
                        </span>
                      </div>

                      <div className="my-2">
                        <div className="text-sm sm:text-base font-black text-slate-900 dark:text-white tracking-wide">
                          {leg.strikeLabel || leg.fullText || '—'}
                        </div>
                        {leg.symbol && leg.symbol !== leg.strikeLabel && (
                          <div className={`text-[9.5px] truncate mt-0.5 font-sans ${isBuy ? 'text-emerald-700 dark:text-emerald-300/70' : 'text-rose-700 dark:text-rose-300/70'}`} title={leg.symbol}>
                            {leg.symbol}
                          </div>
                        )}
                      </div>

                      <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-border/40 dark:border-white/10">
                        <span className="text-slate-500 dark:text-zinc-400 uppercase font-semibold text-[9.5px]">
                          {isBuy ? 'Entry Premium' : 'Credit Recv'}
                        </span>
                        <span className={`font-black text-xs ${isBuy ? 'text-emerald-800 dark:text-emerald-200' : 'text-rose-800 dark:text-rose-200'}`}>
                          {leg.premium !== null ? `₹${formatNum(leg.premium)}` : '—'}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Corridor & Summary Strip */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono text-xs pt-1">
                <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30">
                  <div className="text-[10px] font-bold text-emerald-800 dark:text-emerald-400 uppercase">Max Profit</div>
                  <div className="text-sm font-black text-emerald-900 dark:text-emerald-200 mt-0.5">
                    {hedgedSpreadData.maxProfit !== null ? `₹${formatNum(hedgedSpreadData.maxProfit)}` : '—'}
                  </div>
                  <div className="text-[9.5px] text-slate-600 dark:text-zinc-400">Total Credit per lot</div>
                </div>
                <div className="p-2 rounded-lg bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/30">
                  <div className="text-[10px] font-bold text-rose-800 dark:text-rose-400 uppercase">Max Loss (Capped)</div>
                  <div className="text-sm font-black text-rose-900 dark:text-rose-200 mt-0.5">
                    {hedgedSpreadData.maxLoss !== null ? `₹${formatNum(hedgedSpreadData.maxLoss)}` : '—'}
                  </div>
                  <div className="text-[9.5px] text-slate-600 dark:text-zinc-400">Defined Wing Risk</div>
                </div>
                <div className="p-2 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30">
                  <div className="text-[10px] font-bold text-amber-800 dark:text-amber-400 uppercase">Safe Corridor</div>
                  <div className="text-xs sm:text-sm font-black text-amber-900 dark:text-amber-200 mt-0.5 truncate" title={hedgedSpreadData.profitCorridor || 'Corridor'}>
                    {hedgedSpreadData.profitCorridor || '—'}
                  </div>
                  <div className="text-[9.5px] text-slate-600 dark:text-zinc-400">Short Strikes Bound</div>
                </div>
                <div className="p-2 rounded-lg bg-purple-50 dark:bg-purple-500/10 border border-purple-200 dark:border-purple-500/30">
                  <div className="text-[10px] font-bold text-purple-800 dark:text-purple-400 uppercase">Breakevens</div>
                  <div className="text-xs sm:text-sm font-black text-purple-900 dark:text-purple-200 mt-0.5 truncate" title={hedgedSpreadData.breakevensStr || 'Breakevens'}>
                    {hedgedSpreadData.breakevensStr || '—'}
                  </div>
                  <div className="text-[9.5px] text-slate-600 dark:text-zinc-400">Expiration Zero-P&L</div>
                </div>
              </div>
            </div>
          ) : (
            /* 3-Column Execution Matrix */
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 font-mono">
              {/* 🟢 BUY LEG (Long Contract) */}
              <div className="p-2.5 rounded-lg bg-emerald-50/80 dark:bg-gradient-to-b dark:from-[#082318] dark:to-[#04140d] border border-emerald-300 dark:border-emerald-500/40 hover:border-emerald-400/70 transition-all flex flex-col justify-between shadow-sm">
                <div className="flex items-center justify-between pb-1 border-b border-emerald-200 dark:border-emerald-500/20">
                  <div className="flex items-center gap-1.5">
                    <span className="px-1.5 py-0.5 rounded bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-black text-[10px] uppercase tracking-wider shadow-sm">
                      BUY +1
                    </span>
                    <span className="font-bold text-[10px] text-emerald-800 dark:text-emerald-300/90 uppercase tracking-wide">
                      Long Leg
                    </span>
                  </div>
                  <span className="text-[10px] text-emerald-700 dark:text-emerald-400 font-bold">
                    {hedgedSpreadData.buyLeg?.optionType || 'OPTION'}
                  </span>
                </div>

                <div className="my-2">
                  <div className="text-base sm:text-lg font-black text-slate-900 dark:text-white tracking-wide">
                    {hedgedSpreadData.buyLeg?.strikeLabel || hedgedSpreadData.longLeg || '—'}
                  </div>
                  {hedgedSpreadData.buyLeg?.symbol && hedgedSpreadData.buyLeg.symbol !== hedgedSpreadData.buyLeg.strikeLabel && (
                    <div className="text-[10px] text-emerald-800 dark:text-emerald-300/70 truncate mt-0.5 font-sans" title={hedgedSpreadData.buyLeg.symbol}>
                      {hedgedSpreadData.buyLeg.symbol}
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-emerald-200 dark:border-emerald-500/20">
                  <span className="text-emerald-800 dark:text-emerald-300/80 uppercase font-semibold text-[10px]">
                    Entry Premium
                  </span>
                  <span className="font-black text-emerald-900 dark:text-emerald-200 text-xs">
                    {hedgedSpreadData.buyLeg?.premium !== null && hedgedSpreadData.buyLeg?.premium !== undefined
                      ? `₹${formatNum(hedgedSpreadData.buyLeg.premium)}`
                      : hedgedSpreadData.longLeg?.includes('@')
                      ? hedgedSpreadData.longLeg.split('@')[1].trim()
                      : '—'}
                  </span>
                </div>
              </div>

              {/* 🔴 SELL LEG (Short Hedge Contract) */}
              <div className="p-2.5 rounded-lg bg-rose-50/80 dark:bg-gradient-to-b dark:from-[#290d15] dark:to-[#16050a] border border-rose-300 dark:border-rose-500/40 hover:border-rose-400/70 transition-all flex flex-col justify-between shadow-sm">
                <div className="flex items-center justify-between pb-1 border-b border-rose-200 dark:border-rose-500/20">
                  <div className="flex items-center gap-1.5">
                    <span className="px-1.5 py-0.5 rounded bg-rose-600 text-white dark:bg-rose-500 font-black text-[10px] uppercase tracking-wider shadow-sm">
                      SELL -1
                    </span>
                    <span className="font-bold text-[10px] text-rose-800 dark:text-rose-300/90 uppercase tracking-wide">
                      Hedge Leg
                    </span>
                  </div>
                  <span className="text-[10px] text-rose-700 dark:text-rose-400 font-bold">
                    {hedgedSpreadData.sellLeg?.optionType || 'HEDGE'}
                  </span>
                </div>

                <div className="my-2">
                  <div className="text-base sm:text-lg font-black text-slate-900 dark:text-white tracking-wide">
                    {hedgedSpreadData.sellLeg?.strikeLabel || hedgedSpreadData.shortLeg || '—'}
                  </div>
                  {hedgedSpreadData.sellLeg?.symbol && hedgedSpreadData.sellLeg.symbol !== hedgedSpreadData.sellLeg.strikeLabel && (
                    <div className="text-[10px] text-rose-800 dark:text-rose-300/70 truncate mt-0.5 font-sans" title={hedgedSpreadData.sellLeg.symbol}>
                      {hedgedSpreadData.sellLeg.symbol}
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-rose-200 dark:border-rose-500/20">
                  <span className="text-rose-800 dark:text-rose-300/80 uppercase font-semibold text-[10px]">
                    Credit Received
                  </span>
                  <span className="font-black text-rose-900 dark:text-rose-200 text-xs">
                    {hedgedSpreadData.sellLeg?.premium !== null && hedgedSpreadData.sellLeg?.premium !== undefined
                      ? `₹${formatNum(hedgedSpreadData.sellLeg.premium)}`
                      : hedgedSpreadData.shortLeg?.includes('@')
                      ? hedgedSpreadData.shortLeg.split('@')[1].trim()
                      : '—'}
                  </span>
                </div>
              </div>

              {/* ⚡ NET DEBIT & RISK CAP */}
              <div className="p-2.5 rounded-lg bg-amber-50/80 dark:bg-gradient-to-b dark:from-[#251b07] dark:to-[#140e02] border border-amber-300 dark:border-amber-500/40 hover:border-amber-400/70 transition-all flex flex-col justify-between shadow-sm">
                <div className="flex items-center justify-between pb-1 border-b border-amber-200 dark:border-amber-500/20">
                  <div className="flex items-center gap-1.5">
                    <span className="px-1.5 py-0.5 rounded bg-amber-600 text-white dark:bg-amber-500 dark:text-slate-950 font-black text-[10px] uppercase tracking-wider shadow-sm">
                      NET DEBIT:
                    </span>
                    <span className="font-bold text-[10px] text-amber-800 dark:text-amber-300/90 uppercase tracking-wide">
                      Max Capital Risk
                    </span>
                  </div>
                  <span className="text-[10px] text-amber-800 dark:text-amber-400 font-bold">
                    {hedgedSpreadData.breakeven ? `BE ₹${formatNum(hedgedSpreadData.breakeven)}` : 'CAPPED RISK'}
                  </span>
                </div>

                <div className="my-2">
                  <div className="text-base sm:text-lg font-black text-amber-900 dark:text-amber-200 tracking-wide flex items-baseline gap-1.5">
                    <span className="font-bold">Net Debit:</span>
                    <span>₹{formatNum(hedgedSpreadData.netDebit)}</span>
                    <span className="text-[10px] text-amber-800/80 dark:text-amber-300/70 font-normal">/ contract</span>
                  </div>
                  {hedgedSpreadData.maxLoss !== null && (
                    <div className="text-[10px] text-amber-800 dark:text-amber-300/90 truncate mt-0.5 font-mono">
                      Max Loss: <span className="font-bold text-rose-700 dark:text-rose-300">₹{formatNum(hedgedSpreadData.maxLoss)}</span> / lot
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between text-[11px] pt-1.5 border-t border-amber-200 dark:border-amber-500/20">
                  <span className="text-amber-800 dark:text-amber-300/80 uppercase font-semibold text-[10px]">
                    Theta Decay Offset
                  </span>
                  <span className="font-black text-emerald-800 dark:text-emerald-300 text-xs">
                    {hedgedSpreadData.thetaReductionPct || '75%'}
                  </span>
                </div>
              </div>
            </div>
          ))}

          {/* Institutional Guidance Banner */}
          {isSpreadExpanded && (
            <div className="p-2 rounded-lg bg-sky-100/70 dark:bg-sky-950/60 border border-sky-300 dark:border-sky-500/25 flex items-start gap-2 text-[11px] leading-relaxed text-sky-900 dark:text-sky-100">
              <span className="text-sky-700 dark:text-sky-300 text-sm flex-shrink-0">🛡️</span>
              <div className="flex-1 font-sans">
                <span className="font-bold text-sky-800 dark:text-sky-200">Execution Edge: </span>
                <span className="text-slate-700 dark:text-slate-200">{hedgedSpreadData.guidance}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Actionable Execution & Profit Capture Protocol ── */}
      <div className="rounded-xl border border-emerald-300 dark:border-emerald-500/35 bg-emerald-50/40 dark:bg-gradient-to-b dark:from-[#061a14] dark:via-[#04120e] dark:to-[#020a07] p-2.5 sm:p-3 space-y-2 shadow-sm text-xs">
        {/* Section Header */}
        <div className="flex items-center justify-between flex-wrap gap-2 pb-1.5 border-b border-emerald-300/40 dark:border-emerald-500/20">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsPlaybookExpanded(prev => !prev)}
              className="flex items-center gap-1.5 hover:opacity-80 transition-opacity text-left"
              title={isPlaybookExpanded ? 'Collapse Execution Protocol' : 'Expand Execution Protocol'}
            >
              <span className="flex items-center justify-center w-5 h-5 rounded-md bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300 text-xs font-bold border border-emerald-300 dark:border-emerald-500/30">
                ⚡
              </span>
              <span className="font-black text-slate-900 dark:text-white uppercase tracking-wider text-xs font-sans">
                Actionable Execution &amp; Profit Capture Protocol
              </span>
              <span className="text-[10px] text-muted ml-0.5">{isPlaybookExpanded ? '▲' : '▼'}</span>
            </button>
          </div>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/30 uppercase tracking-wider">
            {isNeutralSpread ? 'Delta-Neutral Theta Harvest' : isOptionSell ? 'Short Option Decay' : 'Directional Asymmetric Convexity'}
          </span>
        </div>

        {/* 4-Step Execution Grid & Recommendation Banner */}
        {isPlaybookExpanded && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 font-mono text-[11px]">
            {/* Step 1: Entry */}
            <div className="p-2 rounded-lg bg-panel/90 dark:bg-surface/80 border border-emerald-300/60 dark:border-emerald-500/25 flex flex-col justify-between">
              <div className="flex items-center justify-between pb-1 border-b border-border/30 dark:border-white/5">
                <span className="font-bold text-emerald-800 dark:text-emerald-400 uppercase text-[10px]">1. Entry Execution</span>
                <span className="px-1.5 py-0.2 rounded text-[9.5px] font-black bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-300">
                  {isNeutralSpread ? '4-LEG BASKET' : 'LIMIT / STOP'}
                </span>
              </div>
              <div className="my-1.5 font-sans text-slate-700 dark:text-slate-200 text-[11px] leading-snug">
                {isNeutralSpread ? (
                  <>
                    Execute wings first ({hedgedSpreadData?.allLegs?.[0]?.strikeLabel || 'BUY PE'} &amp; {hedgedSpreadData?.allLegs?.[3]?.strikeLabel || 'BUY CE'}) for margin relief, then SELL short corridor strikes ({hedgedSpreadData?.profitCorridor || 'Corridor'}). Collect net credit.
                  </>
                ) : levels?.entry ? (
                  <>
                    Enter {isDerivative ? `${cleanSym} ${alert.strike || ''} ${alert.option_type || ''}` : cleanSym} at <span className="font-bold text-slate-900 dark:text-white">₹{formatNum(levels.entry)}</span>. Max chase ceiling: <span className="font-bold text-amber-800 dark:text-amber-300">₹{formatNum(noChaseLimit || levels.entry)}</span>.
                  </>
                ) : (
                  <>
                    Enter {isDerivative ? `${cleanSym} ${alert.strike || ''} ${alert.option_type || 'CE'}` : cleanSym} on confirmed 1m breakout with volume expansion.
                  </>
                )}
              </div>
              <div className="text-[10px] text-slate-500 dark:text-zinc-400 font-mono pt-1 border-t border-border/30 dark:border-white/5">
                Trigger: {isNeutralSpread ? 'Within safe corridor' : '1m/5m candle close confirmation'}
              </div>
            </div>

            {/* Step 2: Target 1 Milestone */}
            <div className="p-2 rounded-lg bg-panel/90 dark:bg-surface/80 border border-emerald-300/60 dark:border-emerald-500/25 flex flex-col justify-between">
              <div className="flex items-center justify-between pb-1 border-b border-border/30 dark:border-white/5">
                <span className="font-bold text-emerald-800 dark:text-emerald-300 uppercase text-[10px]">2. T1 Milestone (+2R)</span>
                <span className="px-1.5 py-0.2 rounded text-[9.5px] font-black bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200">
                  {isNeutralSpread ? '50% DECAY' : 'SCALE 50%'}
                </span>
              </div>
              <div className="my-1.5 font-sans text-slate-700 dark:text-slate-200 text-[11px] leading-snug">
                {isNeutralSpread ? (
                  <>
                    At ₹{formatNum(levels?.t1)} (+50% decay), <span className="font-bold text-emerald-800 dark:text-emerald-300">book 50% profit</span> and ratchet Stop-Loss to Breakeven (Credit cost).
                  </>
                ) : levels?.t1 ? (
                  <>
                    At ₹{formatNum(levels.t1)} (+2R), <span className="font-bold text-emerald-800 dark:text-emerald-300">book 50% partial profit</span> and immediately ratchet SL to Breakeven (₹{formatNum(levels.entry)}).
                  </>
                ) : (
                  <>
                    On +2R (+25% to +35% move), book 50% partial profit and immediately ratchet SL to Cost.
                  </>
                )}
              </div>
              <div className="text-[10px] text-emerald-800 dark:text-emerald-300/80 font-mono pt-1 border-t border-border/30 dark:border-white/5">
                Result: Trade de-risked to 100% Free-Roll (₹0 risk)
              </div>
            </div>

            {/* Step 3: Target 2 / Runner */}
            <div className="p-2 rounded-lg bg-panel/90 dark:bg-surface/80 border border-cyan-300/60 dark:border-cyan-500/25 flex flex-col justify-between">
              <div className="flex items-center justify-between pb-1 border-b border-border/30 dark:border-white/5">
                <span className="font-bold text-cyan-800 dark:text-cyan-300 uppercase text-[10px]">3. Target 2 / Runner</span>
                <span className="px-1.5 py-0.2 rounded text-[9.5px] font-black bg-cyan-100 text-cyan-800 dark:bg-cyan-500/20 dark:text-cyan-200">
                  {isNeutralSpread ? '80% DECAY' : '9-EMA TRAIL'}
                </span>
              </div>
              <div className="my-1.5 font-sans text-slate-700 dark:text-slate-200 text-[11px] leading-snug">
                {isNeutralSpread ? (
                  <>
                    At ₹{formatNum(levels?.t2)} (80% decay), harvest remaining premium. Allow final 20% lots to expire worthless if spot is stable.
                  </>
                ) : levels?.t2 ? (
                  <>
                    Hold remaining 50% runner for T2 (₹{formatNum(levels.t2)}) and T3 (₹{formatNum(levels.t3)}). Trail stop along dynamic 9-EMA.
                  </>
                ) : (
                  <>
                    Trail remaining 50% position on 1-min 9-EMA for maximum expansion capture.
                  </>
                )}
              </div>
              <div className="text-[10px] text-cyan-800 dark:text-cyan-300/80 font-mono pt-1 border-t border-border/30 dark:border-white/5">
                Max upside capture on trending expansion
              </div>
            </div>

            {/* Step 4: Strict Invalidation */}
            <div className="p-2 rounded-lg bg-panel/90 dark:bg-surface/80 border border-rose-300/60 dark:border-rose-500/25 flex flex-col justify-between">
              <div className="flex items-center justify-between pb-1 border-b border-border/30 dark:border-white/5">
                <span className="font-bold text-rose-800 dark:text-rose-400 uppercase text-[10px]">4. Strict Invalidation</span>
                <span className="px-1.5 py-0.2 rounded text-[9.5px] font-black bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-300">
                  HARD STOP
                </span>
              </div>
              <div className="my-1.5 font-sans text-slate-700 dark:text-slate-200 text-[11px] leading-snug">
                {isNeutralSpread ? (
                  <>
                    If spot breaks outside corridor [{hedgedSpreadData?.profitCorridor || 'Corridor'}], exit tested spread. Max loss strictly capped at ₹{formatNum(levels?.sl)}.
                  </>
                ) : levels?.sl ? (
                  <>
                    If price closes below <span className="font-bold text-rose-800 dark:text-rose-300">₹{formatNum(levels.sl)}</span>, close position immediately. Zero hesitation, zero averaging down.
                  </>
                ) : (
                  <>
                    Strict mental stop on 1m swing low breach (max 15% option premium drawdown).
                  </>
                )}
              </div>
              <div className="text-[10px] text-rose-800 dark:text-rose-400/80 font-mono pt-1 border-t border-border/30 dark:border-white/5">
                Disciplined institutional capital protection
              </div>
            </div>
          </div>

          {/* Trader Action Recommendation Banner */}
          <div className="p-2.5 rounded-lg bg-emerald-50/90 dark:bg-gradient-to-r dark:from-emerald-950/80 dark:via-slate-900 dark:to-cyan-950/80 border border-emerald-300 dark:border-emerald-500/40 flex items-start gap-2.5 shadow-sm">
            <span className="text-base flex-shrink-0">{isStagnant ? '⚠️' : '🎯'}</span>
            <div className="flex-1 font-sans text-xs leading-relaxed">
              <div className={`font-black uppercase tracking-wide text-[10.5px] ${isStagnant ? 'text-amber-800 dark:text-amber-300' : 'text-emerald-800 dark:text-emerald-300'}`}>
                {isStagnant ? 'Institutional Velocity Scratch Directive' : 'Institutional Trader Action Directive'}
              </div>
              <div className="text-slate-700 dark:text-slate-200 mt-0.5">
                {isStagnant ? (
                  <>
                    <span className="font-bold text-amber-900 dark:text-amber-200">SCRATCH DIRECTIVE: </span>
                    Position momentum dried up after extended time in trade ({alert?.stagnation_minutes || alert?.time_in_trade || 'extended'} min). Scratch position near breakeven or market price to protect capital and eliminate theta bleed. Do not chase new targets.
                  </>
                ) : isNeutralSpread ? (
                  <>
                    <span className="font-bold text-slate-950 dark:text-white">RECOMMENDATION: </span>
                    {hedgedSpreadData?.allLegs?.length === 4 ? (
                      <>
                        Execute 4-leg condor: <span className="font-mono text-emerald-800 dark:text-emerald-300 font-bold">BUY {hedgedSpreadData.allLegs[0]?.strikeLabel}</span>, <span className="font-mono text-rose-800 dark:text-rose-300 font-bold">SELL {hedgedSpreadData.allLegs[1]?.strikeLabel}</span>, <span className="font-mono text-rose-800 dark:text-rose-300 font-bold">SELL {hedgedSpreadData.allLegs[2]?.strikeLabel}</span>, and <span className="font-mono text-emerald-800 dark:text-emerald-300 font-bold">BUY {hedgedSpreadData.allLegs[3]?.strikeLabel}</span> to collect ₹{formatNum(levels?.entry)} credit per unit ({hedgedSpreadData.maxProfit !== null ? `₹${formatNum(hedgedSpreadData.maxProfit)} per lot` : ''}). Retain 100% profit as long as {cleanSym} stays within {hedgedSpreadData.profitCorridor}. Book 50% profit once decay hits ₹{formatNum(levels?.t1)} to de-risk to zero.
                      </>
                    ) : (
                      <>
                        Sell safe corridor strikes while buying wings for defined risk. Collect ₹{formatNum(levels?.entry)} credit. Close 50% at ₹{formatNum(levels?.t1)} decay to de-risk.
                      </>
                    )}
                  </>
                ) : levels?.entry ? (
                  <>
                    <span className="font-bold text-slate-950 dark:text-white">RECOMMENDATION: </span>
                    {isUpward ? 'BUY ' : 'SELL '}
                    <span className="font-mono font-bold text-emerald-800 dark:text-emerald-300">{isDerivative ? `${cleanSym} ${alert.strike || ''} ${alert.option_type || ''}` : cleanSym}</span>
                    {' '}at ₹{formatNum(levels.entry)}. Set Stop-Loss at ₹{formatNum(levels.sl)}. When Target 1 (₹{formatNum(levels.t1)}) is reached, immediately book 50% profit and ratchet Stop-Loss to Entry (₹{formatNum(levels.entry)}) to guarantee a 100% risk-free trade with asymmetric runner potential.
                  </>
                ) : (
                  <>
                    <span className="font-bold text-slate-950 dark:text-white">RECOMMENDATION: </span>
                    High-torque breakout detected on {cleanSym} {alert.strike || ''} {alert.option_type || 'CE'}. Awaiting order book depth confirmation before submitting orders. Keep ticket primed for execution.
                  </>
                )}
              </div>
            </div>
          </div>
          </>
        )}
      </div>

      {/* ── Free-Roll Execution Protocol (+2R Scale 50% & Zero-Risk Runner) ── */}
      {freeRollPlan && (
        <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-1.5 text-[11px]">
          <div className="flex items-center gap-1.5 font-bold text-emerald-800 dark:text-emerald-300">
            <span className="text-xs">💎</span>
            <span>
              FREE-ROLL PROTOCOL: Bank {freeRollPlan.scale_pct || '50%'} at T1 (₹{formatNum(freeRollPlan.t1_target_premium || levels?.t1)}) &amp; ratchet SL to Cost (Risk = ₹0.00).
            </span>
          </div>
          <div className="text-[10px] font-mono text-cyan-800 bg-cyan-100 dark:text-cyan-300 dark:bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-300 dark:border-cyan-500/20 whitespace-nowrap">
            🏃 Runner: {freeRollPlan.runner_trailing_strategy || '1.5x ATR dynamic trail'}
          </div>
        </div>
      )}

      {/* Dynamic Institutional Guidance: Extended / Pullback / Pyramiding */}
      {isExtended && (
        <div className="px-2 py-1 rounded bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/25 flex items-center justify-between text-[11px] text-amber-900 dark:text-amber-200 flex-wrap gap-1">
          <div className="flex items-center gap-1.5 font-bold">
            <span>⏳</span>
            <span>WAIT FOR PULLBACK: Price is +{extendedPct}% past base entry. Institutional accumulation floor: {structuralFloor50 ? `Rising 50-SMA ₹${formatNum(structuralFloor50)}` : 'Rising 50-Day Moving Average'}.</span>
          </div>
          {pyramidRule && (
            <div className="text-[11px] text-cyan-800 dark:text-cyan-300 font-semibold" title={pyramidRule}>
              🧗 Pyramiding: Add +30% on secondary base breakout only
            </div>
          )}
        </div>
      )}
    </div>
  )
}
