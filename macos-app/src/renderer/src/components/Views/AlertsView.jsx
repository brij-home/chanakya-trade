import React, {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import { useNotificationStore } from '../../store/notificationStore'
import UnavailableState from '../Common/UnavailableState'
import MoversAutopsyPanel from './MoversAutopsyPanel'
import AlertRoutingModal from '../Modals/AlertRoutingModal'

import {
  LiveSpotsCtx,
  LiveSpotsProvider,
  useLiveSpot,
  extractQuotes,
  TYPE_STYLE,
  AUTO_TYPE_STYLE,
  INDEX_LOT_SIZES,
  convictionEmoji,
  getStaleness,
  playTerminalChime,
  MCX_COMMODITY_SYMBOLS,
  CDS_CURRENCY_SYMBOLS,
  NSE_INDEX_SYMBOLS,
  classifyAlertSegment,
  formatExpiryDetails,
  computeNextExpiryOpportunity,
  computeExecutionLevels,
  RRMiniBar,
  MilestoneDots,
  TelegramPreflightModal,
  AlertCompactRow,
  AlertTriageCard,
  TradeExecutionMatrix,
  isTestOrSimAlert,
} from './alerts'

/**
 * In-place differential merger:
 * Updates existing alerts in-place preserving their array position and object reference
 * unless actual attributes changed. Prevents screen resets and re-renders.
 * Strictly avoids duplicates by alert_id.
 */

function mergeAlertsInPlace(prevAlerts = [], freshAlerts = []) {
  if (!prevAlerts || prevAlerts.length === 0) {
    const seen = new Set()
    return freshAlerts.filter((a) => {
      const id = a.alert_id || a.id
      if (!id || seen.has(id)) return false
      seen.add(id)
      return true
    })
  }

  // Deduplicate freshAlerts by alert_id first
  const freshMap = new Map()
  for (const a of freshAlerts) {
    const id = a.alert_id || a.id
    if (id && !freshMap.has(id)) {
      freshMap.set(id, a)
    }
  }

  let hasChanges = false
  const updatedExisting = []
  const seenIds = new Set()

  // 1. Update existing items in-place preserving their exact position & identity
  for (const oldItem of prevAlerts) {
    const id = oldItem.alert_id || oldItem.id
    if (!id || seenIds.has(id)) {
      hasChanges = true // Drop duplicate in prev
      continue
    }
    seenIds.add(id)

    const freshItem = freshMap.get(id)
    if (!freshItem) {
      const horizon = oldItem.time_horizon || oldItem.timeHorizon || 'INTRADAY'
      if (horizon === 'INTRADAY' && (oldItem.created_at || oldItem.timestamp)) {
        try {
          const clean = String(oldItem.created_at || oldItem.timestamp).replace(' IST', '').trim()
          const createdDate = new Date(clean)
          if (!isNaN(createdDate.getTime()) && createdDate.toDateString() !== new Date().toDateString()) {
            hasChanges = true
            updatedExisting.push({
              ...oldItem,
              is_invalidated: true,
              is_archived: true,
              is_active: false,
              stage: 'EXPIRED',
              invalidation_reason: oldItem.invalidation_reason || 'Intraday session expired (15:15 IST cutoff reached). Trade closed.'
            })
            continue
          }
        } catch (_) {}
      }
      // Item still exists locally
      updatedExisting.push(oldItem)
      continue
    }

    // Check if key fields changed
    const isModified =
      oldItem.stage !== freshItem.stage ||
      oldItem.is_invalidated !== freshItem.is_invalidated ||
      oldItem.is_archived !== freshItem.is_archived ||
      oldItem.target_status !== freshItem.target_status ||
      oldItem.trailing_stop !== freshItem.trailing_stop ||
      oldItem.ltp !== freshItem.ltp ||
      oldItem.summary !== freshItem.summary ||
      oldItem.headline !== freshItem.headline ||
      Boolean(oldItem.metrics?.post_mortem) !== Boolean(freshItem.metrics?.post_mortem) ||
      JSON.stringify(oldItem.metrics?.scrutiny) !== JSON.stringify(freshItem.metrics?.scrutiny)

    if (isModified) {
      hasChanges = true
      updatedExisting.push({ ...oldItem, ...freshItem })
    } else {
      // Keep exact same object reference! Prevents unnecessary React child re-renders
      updatedExisting.push(oldItem)
    }
  }

  // 2. Identify newly created alerts not in prev
  const brandNewAlerts = []
  for (const [id, f] of freshMap.entries()) {
    if (!seenIds.has(id)) {
      brandNewAlerts.push(f)
      hasChanges = true
    }
  }

  // If no changes at all, return the EXACT previous array reference!
  // React will do ZERO re-renders!
  if (!hasChanges && updatedExisting.length === prevAlerts.length) {
    return prevAlerts
  }

  return [...brandNewAlerts, ...updatedExisting]
}



const AutoAlertCard = memo(function AutoAlertCard({
  alert,
  onAnalyze,
  onInspectOptions,
  onOpenTicket,
  onArchiveToggle,
  onClearLockout,
  onDismiss,
  archiving,
  historyAttempts = [],
  densityMode = 'compact',
}) {
  // Subscribe to live prices for this card's symbol & contract individually.
  const cleanSym = alert.symbol?.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
  const rawContract = alert.contract_symbol || alert.actionable_plan?.option_plan?.contract_symbol || alert.actionable_plan?.option_contract || alert.metrics?.option_symbol || ''
  const cleanContract = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()

  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull

  const liveContractByClean = useLiveSpot(cleanContract)
  const liveContractByFull = useLiveSpot(
    rawContract && rawContract !== cleanContract ? rawContract : null
  )
  const liveContract = liveContractByClean ?? liveContractByFull

  const [showHistory, setShowHistory] = useState(false)
  const [showPostMortem, setShowPostMortem] = useState(false)
  const [showPlan, setShowPlan] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [clearingLockout, setClearingLockout] = useState(false)
  const [lockoutCleared, setLockoutCleared] = useState(false)

  const handleClearLockoutClick = async () => {
    if (!onClearLockout) return
    setClearingLockout(true)
    try {
      await onClearLockout(alert.symbol)
      setLockoutCleared(true)
      setTimeout(() => setLockoutCleared(false), 3500)
    } finally {
      setClearingLockout(false)
    }
  }

  const postMortem = alert.metrics?.post_mortem
  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const isEarly = alert.stage === 'EARLY_WARNING'
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED'
  const isExpired = alert.is_expired || alert.stage === 'EXPIRED'
  const isBull = alert.direction === 'BULLISH'
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isT1 = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isFinalTarget = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED'
  const isTarget = isT1 || isFinalTarget
  const isTrail = alert.stage === 'TRAILING_UPDATE'

  const isFuture = Boolean(
    alert.contract_symbol?.toUpperCase().includes('FUT') ||
    alert.symbol?.toUpperCase().includes('FUT') ||
    alert.derivative_type === 'FUT' ||
    alert.alert_type === 'FUTURES'
  )

  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && (alert.option_type || alert.contract_symbol)) || (alert.contract_symbol && (alert.contract_symbol.endsWith('CE') || alert.contract_symbol.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = !isFuture && !isPureOption && (alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'PATTERN_COILING' || alert.alert_type === 'MOMENTUM_ACCELERATION' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM')

  const isDerivative = isFuture || isPureOption || Boolean(
    !isSpotSetup && (
      (alert.exchange === 'NFO' && (alert.option_type || alert.strike || alert.contract_symbol))
    )
  )

  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const rawStrike = alert.strike || optPlan?.strike || alert.metrics?.strike
  const strikeNum = rawStrike ? Number(String(rawStrike).replace(/[^0-9.-]/g, '')) : null

  // Dynamic Live Spot: Prioritize streamed live quote if available, fallback to alert trigger spot
  const rawSpot = liveSpot?.ltp ?? alert.underlying_spot ?? alert.metrics?.spot
  const spotNum = rawSpot ? Number(String(rawSpot).replace(/[^0-9.-]/g, '')) : null

  // Dynamic Live Contract Premium/Price (Options Premium or Futures Price)
  const rawOptLtp = liveContract?.ltp ?? alert.ltp ?? alert.option_premium
  const optLtpNum = rawOptLtp ? Number(String(rawOptLtp).replace(/[^0-9.-]/g, '')) : null

  const expiryInfo = useMemo(() => formatExpiryDetails(alert), [alert])
  const nextExpiryOpp = useMemo(() => computeNextExpiryOpportunity(alert, expiryInfo), [alert, expiryInfo])
  const executionLevels = useMemo(
    () => computeExecutionLevels(alert, isDerivative, spotNum, optLtpNum),
    [alert, isDerivative, spotNum, optLtpNum]
  )

  const act = String(tradePlan.action || plan.action || '').toUpperCase()
  const isOptionSell = isDerivative && (
    act === 'SELL' ||
    act === 'WRITE' ||
    act === 'SHORT' ||
    alert.alert_type === 'OPTION_WRITE'
  )

  const slNum = isDerivative
    ? (optPlan?.sl_premium ? Number(optPlan.sl_premium) : (alert.option_stop_loss ? Number(alert.option_stop_loss) : (alert.stop_loss ? Number(alert.stop_loss) : null)))
    : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (alert.stop_loss ? Number(alert.stop_loss) : null))
  const entryNum = isDerivative
    ? (optPlan?.entry_premium ? Number(optPlan.entry_premium) : (alert.option_premium ? Number(alert.option_premium) : (optLtpNum || null)))
    : (tradePlan.entry_price ? Number(tradePlan.entry_price) : (alert.trigger_level ? Number(alert.trigger_level) : spotNum))
  const t1Num = isDerivative
    ? (optPlan?.t1_premium ? Number(optPlan.t1_premium) : (alert.option_target_1 ? Number(alert.option_target_1) : (alert.target_level ? Number(alert.target_level) : null)))
    : (tradePlan.target_1 ? Number(tradePlan.target_1) : (alert.target_level ? Number(alert.target_level) : null))
  const t2Num = isDerivative
    ? (optPlan?.t2_premium ? Number(optPlan.t2_premium) : (alert.option_target_2 ? Number(alert.option_target_2) : null))
    : (tradePlan.target_2 ? Number(tradePlan.target_2) : null)
  const t3Num = isDerivative
    ? (optPlan?.t3_premium ? Number(optPlan.t3_premium) : null)
    : (tradePlan.target_3 ? Number(tradePlan.target_3) : null)

  const currentPrice = isDerivative ? (optLtpNum || spotNum) : spotNum

  // Live Return % calculation & direction tracking
  let liveReturn = null
  if (currentPrice && entryNum && entryNum > 0) {
    let diff = 0
    if (isDerivative) {
      diff = isOptionSell ? entryNum - currentPrice : currentPrice - entryNum
    } else {
      diff = isBull ? currentPrice - entryNum : entryNum - currentPrice
    }
    const pct = ((diff / entryNum) * 100).toFixed(1)
    liveReturn = { diff, pct, isProfitable: diff >= 0 }
  }

  // Dynamic live stage hit detection (real-time cross evaluation)
  const isSLHit = Boolean(
    isInvalidated ||
    (slNum && currentPrice && (
      isDerivative
        ? (isOptionSell ? currentPrice >= slNum : currentPrice <= slNum)
        : (isBull ? currentPrice <= slNum : currentPrice >= slNum)
    ))
  )

  const isT3Hit = Boolean(
    isFinalTarget ||
    (t3Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t3Num : currentPrice >= t3Num)
        : (isBull ? currentPrice >= t3Num : currentPrice <= t3Num)
    ))
  )

  const isT2Hit = Boolean(
    isT3Hit ||
    alert.stage === 'T2_ACHIEVED' || alert.target_status === 'T2_ACHIEVED' ||
    (t2Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t2Num : currentPrice >= t2Num)
        : (isBull ? currentPrice >= t2Num : currentPrice <= t2Num)
    ))
  )

  const isT1Hit = Boolean(
    isT2Hit ||
    isT1 ||
    (t1Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t1Num : currentPrice >= t1Num)
        : (isBull ? currentPrice >= t1Num : currentPrice <= t1Num)
    ))
  )

  const trajectoryStatus = (() => {
    if (isSLHit) {
      return {
        badge: '🛑 SL BREACHED',
        text: 'Stop loss triggered — trade thesis invalidated',
        theme: 'rose',
      }
    }
    if (isT3Hit) {
      return {
        badge: '🚀 T3 REACHED',
        text: 'Target 3 hit — runners locked (+6R+ extension)',
        theme: 'purple',
      }
    }
    if (isT2Hit) {
      return {
        badge: '🏁 T2 ACHIEVED',
        text: 'Target 2 hit — 75% profit secured, trailing at T1',
        theme: 'cyan',
      }
    }
    if (isT1Hit) {
      return {
        badge: '🎯 T1 ACHIEVED',
        text: 'Target 1 hit — 50% scale out complete, SL ratcheted to breakeven',
        theme: 'emerald',
      }
    }
    if (liveReturn && currentPrice && entryNum) {
      if (liveReturn.isProfitable) {
        if (t1Num) {
          const t1Dist = Math.abs(t1Num - entryNum)
          const currDist = Math.abs(currentPrice - entryNum)
          const pctToT1 = Math.min(100, Math.max(0, Math.round((currDist / (t1Dist || 1)) * 100)))
          const ptsAway = Math.abs(t1Num - currentPrice)
          return {
            badge: `🟢 RIGHT DIRECTION (+${liveReturn.pct}%)`,
            text: `${pctToT1}% progress to T1 (${ptsAway > 0 ? `₹${ptsAway.toFixed(1)} away` : 'at target'})`,
            theme: 'emerald',
          }
        }
        return {
          badge: `🟢 PROFITABLE (+${liveReturn.pct}%)`,
          text: `Moving favorably from entry ₹${entryNum.toFixed(1)}`,
          theme: 'emerald',
        }
      } else {
        if (slNum) {
          const slDist = Math.abs(entryNum - slNum)
          const adverseDist = Math.abs(entryNum - currentPrice)
          const pctToSL = Math.min(100, Math.max(0, Math.round((adverseDist / (slDist || 1)) * 100)))
          const ptsBuffer = Math.abs(currentPrice - slNum)
          return {
            badge: `⚠️ PULLBACK (${liveReturn.pct}%)`,
            text: `${pctToSL}% toward SL — ₹${ptsBuffer.toFixed(1)} buffer remaining`,
            theme: 'amber',
          }
        }
        return {
          badge: `⚠️ AGAINST ENTRY (${liveReturn.pct}%)`,
          text: `Testing below entry level`,
          theme: 'amber',
        }
      }
    }
    return {
      badge: '⚡ LIVE TRACKING',
      text: 'Awaiting price updates',
      theme: 'blue',
    }
  })()

  // Real-time Cash Equity Return vs Trigger Level
  let liveCashReturn = null
  if (spotNum && alert.trigger_level && !isDerivative) {
    const trigger = Number(alert.trigger_level)
    if (trigger > 0) {
      const diff = isBull ? spotNum - trigger : trigger - spotNum
      const pct = ((diff / trigger) * 100).toFixed(1)
      liveCashReturn = { diff, pct, isProfitable: diff >= 0 }
    }
  }

  const targetNum = alert.target_level ? Number(String(alert.target_level).replace(/[^0-9.-]/g, '')) : null
  const stopLossNum = alert.stop_loss ? Number(String(alert.stop_loss).replace(/[^0-9.-]/g, '')) : null

  const expiryType = alert.expiry_type || (alert.contract_symbol && !['NIFTY', 'BANKNIFTY', 'FINNIFTY'].some((idx) => alert.symbol?.includes(idx)) ? 'MONTHLY' : 'WEEKLY')
  const optType = alert.option_type || optPlan?.option_type || (alert.contract_symbol?.endsWith('PE') ? 'PE' : alert.contract_symbol?.endsWith('CE') ? 'CE' : (optPlan?.contract_symbol?.endsWith('PE') ? 'PE' : optPlan?.contract_symbol?.endsWith('CE') ? 'CE' : null))

  let moneyness = null
  if (strikeNum && spotNum && optType && !isFuture) {
    if (optType === 'CE') {
      moneyness = spotNum >= strikeNum * 1.002 ? 'ITM' : spotNum <= strikeNum * 0.998 ? 'OTM' : 'ATM'
    } else if (optType === 'PE') {
      moneyness = spotNum <= strikeNum * 0.998 ? 'ITM' : spotNum >= strikeNum * 1.002 ? 'OTM' : 'ATM'
    }
  }

  return (
    <article
      className="rounded-2xl p-3 sm:p-3.5 space-y-2.5 transition-all duration-150 hover:border-gold/40 shadow-sm"
      style={{
        background: isInvalidated ? 'rgba(255, 79, 123, 0.04)' : 'var(--color-panel)',
        border: isInvalidated ? '1px solid rgba(255, 79, 123, 0.45)' : `1px solid ${style.border}`,
        boxShadow: isInvalidated
          ? '0 0 16px rgba(255, 79, 123, 0.08)'
          : isEarly
          ? 'var(--shadow-card)'
          : '0 0 16px rgba(245, 166, 35, 0.08)',
      }}
    >
      {/* ── CARD HEADER ─────────────────────────────────────────────────── */}
      {/* Power Header: 3-column Bloomberg-style — Symbol | Thesis | Actions */}
      <div className="flex items-center gap-2 min-w-0">

        {/* Col A: Stage icon + Symbol + Contract chip */}
        <div className="flex items-center gap-1.5 flex-shrink-0 min-w-0">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center text-sm flex-shrink-0"
            style={{
              background: isInvalidated ? 'rgba(255, 79, 123, 0.15)' : style.bg,
              border: `1px solid ${isInvalidated ? 'rgba(255, 79, 123, 0.4)' : style.border}`,
            }}
          >
            {isInvalidated ? '🛑' : isFinalTarget ? '🏁' : isT1 ? '🎯' : isTrail ? '📈' : style.icon}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-sm font-black tracking-wide text-text leading-none">{alert.symbol}</span>
              <span className={`text-[8px] px-1.5 py-px rounded font-black tracking-wider uppercase border ${
                isTest
                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/40'
                  : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
              }`}>
                {isTest ? '🧪 TEST' : '🟢 REAL / LIVE'}
              </span>
              {strikeNum && !isFuture && (
                <span className="text-[9px] font-black text-gold font-mono leading-none">₹{Number(strikeNum).toLocaleString('en-IN')}</span>
              )}
              {optType && !isFuture && (
                <span className={`text-[8px] px-1 py-px rounded font-black uppercase ${
                  optType === 'CE' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
                }`}>{optType}</span>
              )}
              {isFuture && (
                <span className="text-[8px] px-1 py-px rounded font-black uppercase bg-blue-500/20 text-blue-300">FUT</span>
              )}
              {moneyness && !isFuture && (
                <span className={`text-[8px] px-1 py-px rounded font-black ${
                  moneyness === 'ITM' ? 'text-emerald-300 bg-emerald-500/15' : moneyness === 'ATM' ? 'text-gold bg-gold/15' : 'text-zinc-400 bg-zinc-500/15'
                }`}>{moneyness}</span>
              )}
            </div>
            {/* Expiry + direction sub-line */}
            <div className="flex items-center gap-1 mt-0.5 flex-wrap">
              <span className={`text-[8px] font-bold ${isBull ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isBull ? '▲' : '▼'} {alert.direction}
              </span>
              {(isDerivative || Boolean(optPlan || optType || strikeNum || alert.expiry_date)) && expiryInfo?.fullDisplay && (
                <span
                  className={`text-[8px] font-mono px-1.5 py-px rounded font-bold whitespace-nowrap border ${
                    expiryInfo.isWeekly
                      ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                      : 'bg-blue-500/15 text-blue-300 border-blue-500/30'
                  }`}
                  title={expiryInfo.formatted || 'Contract Expiry'}
                >
                  {expiryInfo.isWeekly ? '⚡W' : '📅M'} {alert.expiry_date || expiryInfo.dateFormatted || expiryInfo.monthName}{expiryInfo.dte !== null ? ` (${expiryInfo.dte}d)` : ''}
                </span>
              )}

              {/* Time Horizon Badge */}
              {alert.time_horizon && (
                <span className={`text-[7px] px-1.5 py-px rounded font-black uppercase whitespace-nowrap border ${
                  alert.time_horizon === 'INTRADAY' ? 'bg-sky-500/15 text-sky-300 border-sky-500/30' :
                  alert.time_horizon === 'SWING_SHORT' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' :
                  alert.time_horizon === 'SWING_MID' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' :
                  'bg-purple-500/15 text-purple-300 border-purple-500/30'
                }`}>
                  {alert.time_horizon === 'INTRADAY' ? '⏱️ INTRADAY' :
                   alert.time_horizon === 'SWING_SHORT' ? '⚡ 2-5D SWING' :
                   alert.time_horizon === 'SWING_MID' ? '📈 1-4W SWING' : '🏛️ POSITIONAL'}
                </span>
              )}

              {/* Order Flow & Broker Depth Feed Status */}
              {isTest ? (
                <span className="text-[7px] px-1 py-px rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap" title="Simulated test environment">
                  🧪 SIM DEPTH
                </span>
              ) : alert.order_flow_signals?.live_broker_connected === false || alert.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' ? (
                <span className="text-[7px] px-1 py-px rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap" title="No active broker WebSocket connection. Using tick-level fallback.">
                  ⚠️ SYNTHETIC L1
                </span>
              ) : (alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
                <span className="text-[7px] px-1 py-px rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap" title="Live Broker Level 2 depth active">
                  🟢 LIVE L2
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {/* Col B: Status chip + Headline (flex-1, truncated) + key metric chips */}
        <div className="flex-1 min-w-0 flex items-center gap-2 overflow-hidden">
          {/* Status pill — compact, single word */}
          <div className="flex-shrink-0">
            {isTest ? (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-purple-500/20 text-purple-300 border border-purple-500/40 whitespace-nowrap">
                🧪 TEST
              </span>
            ) : isInvalidated ? (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse whitespace-nowrap">
                ❌ Invalid
              </span>
            ) : isFinalTarget ? (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse whitespace-nowrap">
                🏁 Hit
              </span>
            ) : isT1 ? (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 animate-pulse whitespace-nowrap">
                🎯 T1
              </span>
            ) : isTrail ? (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-blue-500/20 text-blue-300 border border-blue-500/40 whitespace-nowrap">
                📈 Trail
              </span>
            ) : isEarly ? (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-amber-500/15 text-amber-400 border border-amber-500/30 whitespace-nowrap">
                ⏳ Early
              </span>
            ) : (
              <span className="text-[8px] px-1.5 py-0.5 rounded-full font-black uppercase bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 animate-pulse whitespace-nowrap">
                🔥 Live
              </span>
            )}
          </div>

          {/* Headline — single line, truncated, most important signal info */}
          <p className="text-[11px] font-bold text-text truncate min-w-0 flex-1" title={alert.headline}>
            {alert.headline}
          </p>

          {/* 3 key metric chips — always visible, no wrap */}
          <div className="flex items-center gap-1 flex-shrink-0">
            <span className="text-[9px] font-mono font-bold text-gold whitespace-nowrap">
              {alert.confidence || 85}% conf
            </span>
            {alert.metrics?.vol_oi_ratio !== undefined && (
              <span className="text-[9px] font-mono font-bold px-1 py-px rounded bg-gold/10 text-gold border border-gold/25 whitespace-nowrap">
                {alert.metrics.vol_oi_ratio}x OI
              </span>
            )}
            {alert.metrics?.expected_rr && (
              <span className="text-[9px] font-mono font-bold px-1 py-px rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25 whitespace-nowrap">
                {alert.metrics.expected_rr}:1 R
              </span>
            )}
            {alert.metrics?.scrutiny && (
              <span
                className={`text-[9px] font-mono font-bold px-1 py-px rounded whitespace-nowrap ${
                  alert.metrics.scrutiny.status === 'APPROVED'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/35'
                    : alert.metrics.scrutiny.status === 'QUANT_VERIFIED'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/35'
                    : 'bg-amber-500/20 text-amber-300 border border-amber-500/35'
                }`}
                title={`Auditor: ${alert.metrics.scrutiny.auditor_model || 'FAST_LLM'}`}
              >
                {alert.metrics.scrutiny.status === 'APPROVED' ? '🛡️ AI ' : '⚡ QNT '}
                {alert.metrics.scrutiny.score}
              </span>
            )}
            {alert.no_chase_boundary && (
              <span className="text-[9px] font-mono font-bold px-1 py-px rounded bg-rose-500/10 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-300/60 dark:border-rose-500/30 whitespace-nowrap" title="No-Chase Maximum Entry Limit">
                🛑 Max ₹{Number(alert.no_chase_boundary).toLocaleString('en-IN', { maximumFractionDigits: 1 })}
              </span>
            )}
          </div>
        </div>

        {/* Col C: Live Price pill + Action buttons */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {/* Compact live price pill */}
          <div className="flex flex-col items-end text-right">
            {isDerivative ? (
              <>
                <span className={`text-[11px] font-black font-mono leading-none ${
                  liveContract?.flash === 'up' ? 'text-emerald-400' : liveContract?.flash === 'down' ? 'text-rose-400' : 'text-gold'
                }`}>
                  ₹{Number(optLtpNum || 0).toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                  {liveContract?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
                </span>
                {liveReturn && (
                  <span className={`text-[9px] font-bold leading-none ${liveReturn.isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {liveReturn.isProfitable ? '+' : ''}{liveReturn.pct}%
                  </span>
                )}
                <span className={`text-[8px] font-mono text-muted leading-none ${liveSpot?.flash === 'up' ? 'text-emerald-300' : liveSpot?.flash === 'down' ? 'text-rose-300' : ''}`}>
                  Spot ₹{Number(spotNum || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                </span>
              </>
            ) : (
              <>
                <span className={`text-[11px] font-black font-mono leading-none ${
                  liveSpot?.flash === 'up' ? 'text-emerald-400' : liveSpot?.flash === 'down' ? 'text-rose-400' : 'text-text'
                }`}>
                  ₹{Number(spotNum || 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  {liveSpot?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
                </span>
                {liveReturn && (
                  <span className={`text-[9px] font-bold leading-none ${liveReturn.isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {liveReturn.isProfitable ? '+' : ''}{liveReturn.pct}%
                  </span>
                )}
              </>
            )}
          </div>

          {/* Divider */}
          <span className="text-border/40 text-xs">│</span>

          {/* Action buttons — icon-only at compact size */}
          <button
            onClick={() => onAnalyze(alert.symbol)}
            className="btn btn-xs btn-ghost text-[10px] px-1.5 hover:bg-surface border border-border/40"
            title={`Deep analyze ${alert.symbol}`}
          >📊</button>

          {alert.option_type && !isInvalidated && (
            <button
              onClick={() => onInspectOptions(alert.symbol)}
              className="btn btn-xs btn-ghost text-[10px] px-1.5 text-gold hover:bg-gold/10 border border-gold/30"
              title="Options Desk"
            >⚡</button>
          )}

          {onArchiveToggle && (
            <button
              onClick={() => onArchiveToggle(alert.alert_id, !alert.is_archived)}
              disabled={archiving === alert.alert_id}
              className="btn btn-xs btn-ghost text-[10px] px-1.5 text-muted hover:text-text border border-border/40"
              title={alert.is_archived ? 'Restore alert' : 'Archive alert'}
            >
              {archiving === alert.alert_id ? '…' : alert.is_archived ? '↩️' : '📁'}
            </button>
          )}

          {onDismiss && (
            <button
              onClick={() => onDismiss(alert.alert_id || alert.id || alert.symbol)}
              className="btn btn-xs btn-ghost text-[10px] px-1.5 text-muted hover:text-rose-400 border border-border/40 hover:border-rose-500/40"
              title="Dismiss / Remove this alert"
            >
              ✕
            </button>
          )}

          {!isInvalidated ? (
            <button
              onClick={() => onOpenTicket(alert)}
              className="btn btn-xs btn-gold text-[10px] font-black px-2"
              title="Open order ticket"
            >🎫</button>
          ) : null}

          <button
            onClick={() => setShowDetails((v) => !v)}
            className={`btn btn-xs text-[10px] font-mono px-1.5 border transition-all ${
              showDetails ? 'bg-gold/20 text-gold border-gold/40' : 'btn-ghost text-muted hover:text-text border-border/40'
            }`}
            title="Toggle full plan & metrics"
          >
            {showDetails ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {/* ── Thesis Summary Bar (single slim line below header) ─────────── */}
      {(alert.trailing_rationale || alert.summary) && (
        <div className="flex items-start gap-2 px-1 text-[10px] text-zinc-400 leading-relaxed">
          <span
            className="text-[8px] px-1 py-px rounded font-black uppercase flex-shrink-0 mt-0.5"
            style={{ background: style.bg, color: style.color, border: `1px solid ${style.border}` }}
          >{style.label}</span>
          <p className={`${showDetails ? '' : 'line-clamp-2'} flex-1 min-w-0`}>
            {alert.trailing_rationale || alert.summary}
          </p>
          {alert.metrics?.oi_change_pct !== undefined && (
            <span className={`flex-shrink-0 text-[9px] font-mono font-bold px-1 py-px rounded ${
              alert.metrics.oi_change_pct < 0 ? 'bg-rose-500/15 text-rose-300' : 'bg-emerald-500/15 text-emerald-300'
            }`}>ΔOI {alert.metrics.oi_change_pct}%</span>
          )}
          {alert.trailing_stop && (
            <span className="flex-shrink-0 text-[9px] font-mono font-bold px-1 py-px rounded bg-cyan-500/15 text-cyan-300">
              Trail ₹{Number(alert.trailing_stop).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
          )}
        </div>
      )}

      {/* Multi-Strike Flow Consolidation Bar */}
      {Boolean((alert.metrics?.related_strikes || alert.related_strikes)?.length) && (
        <div className="flex items-center gap-1.5 flex-wrap px-2 py-1 rounded-lg bg-surface/70 border border-gold/25 text-[10px] animate-slide-up-fade">
          <span className="font-bold text-gold flex items-center gap-1 uppercase tracking-wider text-[9px]">
            <span>🌊 Flow ({((alert.metrics?.related_strikes || alert.related_strikes) || []).length + 1}):</span>
          </span>
          <span className="px-1.5 py-0.5 rounded bg-gold/25 text-gold border border-gold/40 font-mono font-bold text-[9px] shadow-sm">
            {alert.contract_symbol || `${alert.strike} ${alert.option_type}`} (Active)
          </span>
          {(alert.metrics?.related_strikes || alert.related_strikes || []).map((stk, sIdx) => (
            <button
              key={sIdx}
              onClick={(e) => {
                e.stopPropagation()
                if (onOpenTicket) {
                  onOpenTicket({
                    ...alert,
                    contract_symbol: stk,
                    actionable_plan: {
                      ...(alert.actionable_plan || {}),
                      option_contract: stk,
                    },
                  })
                }
              }}
              className="px-1.5 py-0.5 rounded bg-elevated hover:bg-gold/20 text-zinc-300 hover:text-gold border border-border/60 hover:border-gold/50 font-mono text-[9px] transition-all cursor-pointer"
              title={`1-Click execute ${stk} via order ticket`}
            >
              {stk} ↗
            </button>
          ))}
        </div>
      )}

      {/* Next Expiry Opportunity & Institutional Justification Callout */}
      {nextExpiryOpp && (
        <div className="p-2 rounded-xl bg-gradient-to-r from-amber-500/10 via-surface/90 to-amber-500/5 border border-amber-500/30 text-xs text-amber-800 dark:text-amber-200 space-y-0.5 animate-slide-up-fade">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-1.5 font-bold">
              <span className="text-xs">💡</span>
              <span className="text-[10px] font-black uppercase tracking-wider text-amber-700 dark:text-amber-300">
                Next Expiry Opportunity: {nextExpiryOpp.recommendedContract}
              </span>
            </div>
            <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-amber-500/15 dark:bg-amber-500/20 text-amber-800 dark:text-amber-200 border border-amber-500/30 dark:border-amber-500/40 font-bold uppercase">
              {nextExpiryOpp.tag}
            </span>
          </div>
          <p className="text-[10px] text-amber-900/80 dark:text-amber-100/90 leading-relaxed font-sans">
            <span className="font-bold text-amber-700 dark:text-amber-300">Institutional Justification: </span>
            {nextExpiryOpp.justification}
          </p>
        </div>
      )}

      {/* Invalidation Callout & Forensic Post-Mortem if invalidated */}
      {isInvalidated && (
        <div className="rounded-xl border border-rose-500/35 bg-rose-500/10 p-2.5 space-y-2 text-xs text-rose-800 dark:text-rose-200 animate-slide-up-fade">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="text-base flex-shrink-0">🛑</span>
              <div className="min-w-0 flex-1">
                <span className="font-black text-rose-700 dark:text-rose-300 block tracking-wide text-xs">
                  Trade Thesis Invalidated:
                </span>
                <span className="leading-relaxed text-rose-900/80 dark:text-rose-200/90 font-medium text-[11px] block truncate" title={alert.invalidation_reason || alert.summary}>
                  {alert.invalidation_reason || alert.summary}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0">
              {postMortem && (
                <button
                  onClick={() => setShowPostMortem((v) => !v)}
                  className="btn btn-xs btn-ghost text-[10px] font-bold text-rose-300 border border-rose-500/30 hover:bg-rose-500/20"
                >
                  {showPostMortem ? 'Hide Post-Mortem ▲' : '🧠 View Post-Mortem ▼'}
                </button>
              )}
              {onClearLockout && (
                <button
                  onClick={handleClearLockoutClick}
                  disabled={clearingLockout}
                  className="btn btn-xs btn-ghost text-[10px] font-bold text-amber-300 border border-amber-500/30 hover:bg-amber-500/20"
                  title="Manually clear lockout early if you identify an institutional reclaim or Wyckoff spring"
                >
                  {lockoutCleared ? '✓ Unlocked' : clearingLockout ? '⏳ Unlocking...' : '🔓 Clear Lockout'}
                </button>
              )}
            </div>
          </div>

          {/* Forensic Post-Mortem Drawer */}
          {postMortem && showPostMortem && (
            <div className="pt-2 border-t border-rose-500/25 space-y-2 animate-slide-up-fade">
              <div className="flex items-center justify-between flex-wrap gap-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs">🧠</span>
                  <span className="font-black uppercase tracking-wider text-[10px] text-rose-300">
                    Retrospective Post-Mortem & Attribution
                  </span>
                </div>
                <span className="text-[9px] font-black font-mono px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 uppercase">
                  Cause: {postMortem.primary_failure_reason ? postMortem.primary_failure_reason.replace(/_/g, ' ') : 'STRUCTURAL STOP HIT'}
                </span>
              </div>

              {/* What Was Missed Checklist */}
              {postMortem.missed_signals && postMortem.missed_signals.length > 0 && (
                <div className="space-y-1 bg-surface/60 p-2 rounded-lg border border-rose-500/20">
                  <span className="text-[10px] font-black text-amber-300 uppercase tracking-wider flex items-center gap-1">
                    <span>🔍</span> What Was Missed Prior to / During Invalidation:
                  </span>
                  <ul className="space-y-0.5 pl-1">
                    {postMortem.missed_signals.map((sig, i) => (
                      <li key={i} className="text-[10px] flex items-start gap-1.5 text-zinc-300 leading-relaxed font-sans">
                        <span className="text-rose-400 font-bold">•</span>
                        <span>{sig}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Corrective Actions Applied */}
              {postMortem.corrective_actions && postMortem.corrective_actions.length > 0 && (
                <div className="space-y-1 bg-surface/60 p-2 rounded-lg border border-emerald-500/25">
                  <span className="text-[10px] font-black text-emerald-300 uppercase tracking-wider flex items-center gap-1">
                    <span>🛡️</span> Systemic Guardrails & Self-Corrections Enforced:
                  </span>
                  <ul className="space-y-0.5 pl-1">
                    {postMortem.corrective_actions.map((act, i) => (
                      <li key={i} className="text-[10px] flex items-start gap-1.5 text-emerald-800/90 dark:text-emerald-200/90 leading-relaxed font-mono">
                        <span className="text-emerald-400 font-bold">✓</span>
                        <span>{act}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Metrics Snapshot Bar */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-[9px] font-mono pt-1">
                <div className="p-1 rounded bg-surface/80 border border-border/40">
                  <span className="text-muted block text-[8px] uppercase">Realized R</span>
                  <span className="font-bold text-rose-400">{postMortem.realized_r !== undefined ? `${postMortem.realized_r}R` : '-1.0R'}</span>
                </div>
                <div className="p-1 rounded bg-surface/80 border border-border/40">
                  <span className="text-muted block text-[8px] uppercase">Stop Distance</span>
                  <span className="font-bold text-amber-300">
                    {postMortem.loss_pts ? `${postMortem.loss_pts} pts ` : ''}
                    ({postMortem.loss_pct || 0}%)
                  </span>
                </div>
                <div className="p-1 rounded bg-surface/80 border border-border/40">
                  <span className="text-muted block text-[8px] uppercase">Min 1.2x ATR Floor</span>
                  <span className="font-bold text-cyan-300">
                    {postMortem.metrics_snapshot?.min_noise_sl_pts ? `${postMortem.metrics_snapshot.min_noise_sl_pts} pts` : 'Calculated'}
                  </span>
                </div>
                <div className="p-1 rounded bg-surface/80 border border-border/40">
                  <span className="text-muted block text-[8px] uppercase">Intraday VWAP</span>
                  <span className="font-bold text-zinc-300">
                    {postMortem.metrics_snapshot?.intraday_vwap ? `₹${postMortem.metrics_snapshot.intraday_vwap.toLocaleString('en-IN', { maximumFractionDigits: 1 })}` : 'N/A'}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Crisp 1-Line Trap Risk Warning (only if present, zero screen bloat) ── */}
      {alert.metrics?.scrutiny?.trap_risk_warning && !isInvalidated && (
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/25 text-[11px] text-amber-800 dark:text-amber-200">
          <span className="font-bold flex-shrink-0 text-amber-700 dark:text-amber-300">⚠️ Trap Risk:</span>
          <span className="truncate flex-1 font-sans" title={alert.metrics.scrutiny.trap_risk_warning}>
            {alert.metrics.scrutiny.trap_risk_warning}
          </span>
        </div>
      )}

      {/* ── Institutional 5-Tier Execution Runway (Entry, SL, T1, T2, T3) ── */}
      <TradeExecutionMatrix
        levels={executionLevels}
        isBull={isBull}
        isDerivative={isDerivative}
        currentPrice={currentPrice}
        trailingStop={alert.trailing_stop}
        slRationale={alert.actionable_plan?.trade_plan?.sl_rationale}
        tradePlan={alert.actionable_plan?.trade_plan || null}
        marketStatus={alert.market_status || alert.actionable_plan?.market_status?.status || 'SESSION_CLOSED'}
        expiryInfo={expiryInfo}
        densityMode={densityMode}
      />

      {/* ── Progressive Disclosure Deep Dive Drawer (Plan details, Hedge, Matched chips, Full metrics) ── */}
      {showDetails && (
        <div className="space-y-2 pt-2 border-t border-border/30 animate-slide-up-fade">
          {/* Hedging & Defined-Risk Structure Advice */}
          {(alert.actionable_plan?.structure_advice || alert.actionable_plan?.trade_plan?.structure_advice) && !isInvalidated && (
            <div className="p-2.5 rounded-xl border border-indigo-500/30 bg-indigo-500/10 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-bold text-indigo-300">
                <span className="text-sm">🛡️</span>
                <span className="uppercase tracking-wider text-[10px]">
                  HEDGE STRUCTURE RECOMMENDED:{' '}
                  {(
                    alert.actionable_plan?.options_recommended_structure ||
                    alert.actionable_plan?.trade_plan?.options_recommended_structure ||
                    'DEFINED_RISK_SPREAD'
                  ).replace(/_/g, ' ')}
                </span>
              </div>
              <p className="text-zinc-800 dark:text-zinc-200 text-[11px] leading-relaxed">
                {alert.actionable_plan?.structure_advice || alert.actionable_plan?.trade_plan?.structure_advice}
              </p>
              {(alert.actionable_plan?.session_clock_note || alert.actionable_plan?.trade_plan?.session_clock_note) && (
                <p className="text-amber-300/90 text-[10px] font-mono pt-0.5 border-t border-indigo-500/20">
                  {alert.actionable_plan?.session_clock_note || alert.actionable_plan?.trade_plan?.session_clock_note}
                </p>
              )}
            </div>
          )}

          {/* Institutional Trade Plan & Strategy Rationales */}
          {alert.actionable_plan?.trade_plan && !isInvalidated && (
            <div className="p-2.5 rounded-xl border border-indigo-500/30 bg-indigo-500/5 space-y-1.5 text-xs">
              <div className="flex items-center justify-between flex-wrap gap-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm">🔬</span>
                  <span className="font-black text-indigo-300 text-[10px] uppercase tracking-wider">
                    Institutional Trade Plan & Strategy Rationales
                  </span>
                </div>
                {alert.actionable_plan.trade_plan.asymmetry_verdict && (
                  <span className="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 uppercase">
                    {alert.actionable_plan.trade_plan.asymmetry_verdict}
                  </span>
                )}
              </div>

              <div className="space-y-1 pt-1 border-t border-indigo-500/20 text-[11px]">
                {alert.actionable_plan.trade_plan.sl_rationale && (
                  <div>
                    <span className="text-rose-400 font-bold">Stop Rationale: </span>
                    <span className="text-zinc-300">{alert.actionable_plan.trade_plan.sl_rationale}</span>
                  </div>
                )}
                {alert.actionable_plan.trade_plan.t1_rationale && (
                  <div>
                    <span className="text-emerald-400 font-bold">Target 1 Rationale: </span>
                    <span className="text-zinc-300">{alert.actionable_plan.trade_plan.t1_rationale}</span>
                    {alert.actionable_plan.trade_plan.eta_t1_str && (
                      <span className="ml-1.5 text-cyan-400 font-mono text-[10px]">({alert.actionable_plan.trade_plan.eta_t1_str})</span>
                    )}
                  </div>
                )}
                {alert.actionable_plan.trade_plan.t2_rationale && (
                  <div>
                    <span className="text-cyan-400 font-bold">Target 2 / Runner: </span>
                    <span className="text-zinc-300">{alert.actionable_plan.trade_plan.t2_rationale}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Filter Conditions & Setup Criteria Matched */}
          {alert.metrics?.matched_factors && alert.metrics.matched_factors.length > 0 && (
            <div className="p-2 rounded-xl border border-gold/30 bg-gold/5 space-y-1 text-xs">
              <div className="flex items-center justify-between flex-wrap gap-1.5">
                <span className="font-black text-gold flex items-center gap-1.5 text-[10px] uppercase tracking-wider">
                  <span>⚡</span> Filter Conditions & Setup Criteria Matched ({alert.metrics.matched_factors.length})
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  {alert.metrics.similarity_score ? (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-gold/20 text-gold border border-gold/40 font-bold">
                      {alert.metrics.similarity_score}% Archetype Match {alert.metrics.closest_archetype ? `· ${alert.metrics.closest_archetype}` : ''}
                    </span>
                  ) : null}
                  {alert.metrics.expected_rr ? (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold">
                      Expected R:R {alert.metrics.expected_rr}:1
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap gap-1 pt-0.5">
                {alert.metrics.matched_factors.map((factor, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface/90 border border-gold/20 text-[10px] font-sans text-zinc-800 dark:text-zinc-200"
                  >
                    <span className="text-emerald-400 font-bold text-xs">✓</span>
                    <span>{factor}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Quantitative Proof Metrics Grid */}
          {alert.metrics && Object.keys(alert.metrics).length > 0 && (
            <div
              className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 p-2 rounded-xl text-[10px] font-mono"
              style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border-subtle)' }}
            >
              {alert.metrics.vol_oi_ratio !== undefined && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">Vol / OI Ratio</span>
                  <span className="font-bold text-gold">{alert.metrics.vol_oi_ratio}x</span>
                </div>
              )}
              {alert.metrics.oi_change_pct !== undefined && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">Δ OI Unwinding</span>
                  <span className={`font-bold ${alert.metrics.oi_change_pct < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {alert.metrics.oi_change_pct}%
                  </span>
                </div>
              )}
              {alert.metrics.dist_to_pivot_pct !== undefined && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">Pivot Distance</span>
                  <span className="font-bold text-emerald-400">{alert.metrics.dist_to_pivot_pct}%</span>
                </div>
              )}
              {alert.metrics.dist_to_uc_pct !== undefined && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">To Circuit Ceiling</span>
                  <span className="font-bold text-rose-400">{alert.metrics.dist_to_uc_pct}%</span>
                </div>
              )}
              {alert.metrics.rvol !== undefined && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">RVOL 20D</span>
                  <span className="font-bold text-cyan-400">{alert.metrics.rvol}x</span>
                </div>
              )}
              {alert.metrics.spot !== undefined && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">Underlying Spot</span>
                  <span className="font-bold">₹{alert.metrics.spot}</span>
                </div>
              )}
              {alert.target_level > 0 && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">Target</span>
                  <span className="font-bold text-emerald-400">₹{alert.target_level}</span>
                </div>
              )}
              {alert.stop_loss > 0 && (
                <div>
                  <span className="text-[8px] text-muted uppercase block">Stop Loss</span>
                  <span className="font-bold text-rose-400">₹{alert.stop_loss}</span>
                </div>
              )}
            </div>
          )}

          {/* Multi-Attempt History Drawer */}
          {historyAttempts && historyAttempts.length > 0 && (
            <div className="rounded-xl border border-border/60 bg-surface/50 p-2 text-xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-bold text-[10px] text-muted flex items-center gap-1.5">
                  <span>📜</span> Attempt History ({historyAttempts.length + 1} total calls):
                </span>
                <button
                  onClick={() => setShowHistory((v) => !v)}
                  className="text-[9px] text-gold hover:underline font-mono font-bold"
                >
                  {showHistory ? 'Hide Attempts ▲' : `Show ${historyAttempts.length} Older Attempt${historyAttempts.length > 1 ? 's' : ''} ▼`}
                </button>
              </div>

              {showHistory && (
                <div className="space-y-1 pt-1 border-t border-border/40 animate-slide-up-fade">
                  {historyAttempts.map((hist, idx) => (
                    <div
                      key={hist.alert_id || idx}
                      className="p-1.5 rounded-lg bg-panel/70 border border-border/40 flex items-center justify-between gap-2 text-[10px]"
                    >
                      <div className="flex items-center gap-1.5">
                        <span>{hist.is_invalidated ? '🛑' : '⚡'}</span>
                        <div>
                          <span className="font-semibold text-text">
                            Attempt #{historyAttempts.length - idx}: {hist.headline || hist.alert_type}
                          </span>
                          <p className="text-[9px] text-muted font-mono">
                            {hist.invalidated_at || hist.created_at || 'Previous'} · Trigger: ₹{hist.trigger_level} · SL: ₹{hist.stop_loss}
                          </p>
                        </div>
                      </div>
                      <span className="text-[8px] font-mono px-1.5 py-0.2 rounded bg-rose-500/20 text-rose-300 font-bold">
                        {hist.is_invalidated ? 'INVALIDATED' : hist.stage}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Footer Timestamp Strip */}
      <div className="flex items-center justify-between text-[9px] font-mono text-muted/70 pt-1.5 border-t border-border/20 flex-wrap gap-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span>🕒 Triggered: {alert.timestamp || alert.created_at || 'Live'}</span>
          {alert.invalidated_at && (
            <span className="text-rose-400 font-semibold">⚠️ Invalidated: {alert.invalidated_at}</span>
          )}
          {alert.archived_at && (
            <span className="text-amber-400/80 font-semibold">📁 Archived: {alert.archived_at}</span>
          )}
        </div>
        <span className="text-[8px] uppercase tracking-wider text-muted/50">
          ID: {alert.alert_id?.slice(-8) || alert.symbol}
        </span>
      </div>
    </article>
  )
}, (prev, next) => {
  if (prev.alert !== next.alert) return false
  if (prev.archiving !== next.archiving) return false
  if (prev.historyAttempts?.length !== next.historyAttempts?.length) return false
  if (prev.densityMode !== next.densityMode) return false
  return true
})

/**
 * InstitutionalTradeInspector — Dedicated workstation on the right pane of Split View.
 * Displays the selected alert's complete dossier with interactive lot sizer,
 * 1-click execution bar, Payoff Runway, AI Scrutiny, and Trade rationales.
 */
function InstitutionalTradeInspector({
  alert,
  onAnalyze,
  onInspectOptions,
  onOpenTicket,
  onArchiveToggle,
  onClearLockout,
  onSendTelegram,
  onDismiss,
  archiving,
  historyAttempts = [],
}) {
  const [selectedLots, setSelectedLots] = useState(1)
  const cleanSym = alert?.symbol?.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
  const lotSize = INDEX_LOT_SIZES[cleanSym] || alert?.lot_size || alert?.metrics?.lot_size || 1
  const ltpNum = alert?.option_premium ? Number(alert.option_premium) : (alert?.ltp ? Number(alert.ltp) : 0)
  const marginEst = Math.round(selectedLots * lotSize * (ltpNum || 100))
  const isInvalidated = alert?.is_invalidated || alert?.stage === 'INVALIDATED'

  if (!alert) return null

  return (
    <div className="space-y-3 rounded-2xl border border-border/60 bg-panel/70 p-3 shadow-xl backdrop-blur-md">
      {/* ── 1-CLICK EXECUTION & SIZING COMMAND STRIP ── */}
      {!isInvalidated && (
        <div className="p-2.5 rounded-xl bg-surface/90 border border-gold/30 flex items-center justify-between flex-wrap gap-2 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-wider text-gold flex items-center gap-1">
              <span>⚡</span> 1-Click Sizing:
            </span>
            <div className="flex items-center gap-1">
              {[1, 2, 5].map((l) => (
                <button
                  key={l}
                  onClick={() => setSelectedLots(l)}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold transition-all ${
                    selectedLots === l
                      ? 'bg-gold text-black shadow-sm'
                      : 'bg-elevated text-muted hover:text-text border border-border/40'
                  }`}
                >
                  {l} Lot{l > 1 ? 's' : ''} ({l * lotSize})
                </button>
              ))}
              <button
                onClick={() => setSelectedLots(10)}
                className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold transition-all ${
                  selectedLots === 10
                    ? 'bg-gold text-black shadow-sm'
                    : 'bg-elevated text-muted hover:text-text border border-border/40'
                }`}
              >
                10L
              </button>
            </div>
            <span className="text-[9px] font-mono text-muted hidden sm:inline">
              Margin ~₹{marginEst.toLocaleString('en-IN')}
            </span>
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              onClick={() => onOpenTicket && onOpenTicket({ ...alert, quantity: selectedLots * lotSize, _autoSubmit: true })}
              className="btn btn-xs py-1 px-2.5 font-black text-xs text-black bg-emerald-400 hover:bg-emerald-300 shadow-[0_0_12px_rgba(0,214,143,0.3)] transition-all rounded-lg flex items-center gap-1"
              title="1-Click Instant Execution with sized lots"
            >
              <span>⚡</span> EXECUTE ({selectedLots * lotSize} Qty)
            </button>
            <button
              onClick={() => onSendTelegram && onSendTelegram(alert)}
              className="btn btn-xs py-1 px-2 text-[10px] text-sky-700 dark:text-sky-300 hover:text-sky-900 dark:hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-400/40 dark:border-sky-500/35 rounded-lg font-bold"
              title="Share alert via Telegram"
            >
              ↗ TG
            </button>
            <button
              onClick={() => onAnalyze && onAnalyze(alert.symbol)}
              className="btn btn-xs py-1 px-2 text-[10px] text-muted hover:text-text bg-elevated border border-border/50 rounded-lg font-bold"
              title="Deep Multi-Agent Analysis"
            >
              📊 Analyze
            </button>
          </div>
        </div>
      )}

      {/* Full AutoAlertCard in expanded format */}
      <AutoAlertCard
        alert={alert}
        onAnalyze={onAnalyze}
        onInspectOptions={onInspectOptions}
        onOpenTicket={(alt) => onOpenTicket && onOpenTicket({ ...alt, quantity: selectedLots * lotSize })}
        onArchiveToggle={onArchiveToggle}
        onClearLockout={onClearLockout}
        onDismiss={onDismiss}
        archiving={archiving}
        historyAttempts={historyAttempts}
        densityMode="expanded"
      />
    </div>
  )
}

const ManualAlertCard = memo(function ManualAlertCard({ alert, onRemove, onAnalyze, removing }) {
  const cleanSym = alert.symbol?.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull
  const style = TYPE_STYLE[alert.alert_type] || { icon: '🔔', color: 'var(--color-sapphire)' }
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isInvalidated = alert.is_invalidated
  const alertTime = alert.timestamp || alert.triggered_at || alert.invalidated_at || alert.created_at || ''
  const timeShort = alertTime.includes(' ') ? alertTime.split(' ').slice(-2).join(' ') : alertTime

  return (
    <article
      className="rounded-2xl p-4 space-y-3 transition-all duration-150"
      style={{
        background: isInvalidated ? 'rgba(255,79,123,0.06)' : 'var(--color-panel)',
        border: isInvalidated ? '1px solid rgba(255,79,123,0.4)' : '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
          style={{ background: `${style.color}18`, border: `1px solid ${style.color}33` }}
        >
          {isInvalidated ? '🛑' : style.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-black">{alert.symbol}</span>
              <span
                className={`text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-wider ${
                  isTest
                    ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                    : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                }`}
              >
                {isTest ? '🧪 TEST' : '🟢 REAL / LIVE'}
              </span>
              <span
                className="text-[9px] px-1.5 py-0.5 rounded font-bold"
                style={{ background: `${style.color}18`, color: style.color }}
              >
                {alert.alert_type}
              </span>
              {isInvalidated && (
                <span className="text-[9px] px-1.5 py-0.5 rounded font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40">
                  ❌ INVALIDATED
                </span>
              )}
              <span className="text-[9px] font-mono" style={{ color: 'var(--color-muted)' }}>
                {alert.exchange}
              </span>
            </div>
            {timeShort && (
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface/90 border border-border/60 text-[10px] font-mono text-muted shadow-sm"
                title={alertTime}
              >
                <span className="text-cyan-400">🕒</span>
                <span className="font-semibold text-text">{timeShort}</span>
              </span>
            )}
          </div>
          <p className="text-xs mt-1.5" style={{ color: 'var(--color-text)' }}>
            {alert.message || `${alert.condition} ${alert.threshold}`}
          </p>

          {/* Real-time spot price badge for manual alert */}
          {liveSpot?.ltp && (
            <div className="flex items-center gap-2 mt-1.5 flex-wrap text-[11px] font-mono">
              <span className="text-muted">Target: ₹{Number(alert.threshold).toLocaleString('en-IN')}</span>
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface/80 border border-border/50">
                <span className="text-muted">Live:</span>
                <span
                  className={`font-bold transition-colors duration-300 ${
                    liveSpot.flash === 'up'
                      ? 'text-emerald-400 font-black'
                      : liveSpot.flash === 'down'
                      ? 'text-rose-400 font-black'
                      : 'text-text'
                  }`}
                >
                  ₹{Number(liveSpot.ltp).toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 2 })}
                </span>
                <span className="text-[8px] font-black text-emerald-400 bg-emerald-500/10 px-1 py-0.2 rounded animate-pulse">
                  🟢 LIVE
                </span>
                {alert.threshold && (
                  <span className="text-[10px] text-muted">
                    ({(Math.abs(alert.threshold - liveSpot.ltp) / liveSpot.ltp * 100).toFixed(2)}% away)
                  </span>
                )}
              </span>
            </div>
          )}

          {isInvalidated && alert.invalidation_reason && (
            <p className="text-xs mt-1 text-rose-400 font-medium">
              Reason: {alert.invalidation_reason}
            </p>
          )}
          <div className="flex items-center gap-3 text-[10px] mt-1.5 font-mono text-muted flex-wrap">
            <span>🕒 Created: {alert.created_at || '—'}</span>
            {alert.triggered_at && <span className="text-emerald-400 font-semibold">✓ Triggered: {alert.triggered_at}</span>}
            {alert.invalidated_at && <span className="text-rose-400 font-semibold">⚠️ Invalidated: {alert.invalidated_at}</span>}
          </div>
        </div>
      </div>
      <div className="flex gap-2 pt-2 border-t" style={{ borderColor: 'var(--color-border-subtle)' }}>
        <button onClick={() => onAnalyze(alert.symbol)} className="btn btn-sm btn-ghost">
          Analyze
        </button>
        <button
          onClick={() => onRemove(alert.id)}
          disabled={removing}
          className="btn btn-sm ml-auto"
          style={{
            background: 'rgba(255,79,123,0.10)',
            border: '1px solid rgba(255,79,123,0.30)',
            color: 'var(--color-rose)',
          }}
        >
          {removing ? 'Removing…' : 'Remove'}
        </button>
      </div>
    </article>
  )
}, (prev, next) => {
  if (prev.alert !== next.alert) return false
  if (prev.removing !== next.removing) return false
  return true
})

function CreateAlertPanel({ onClose, onCreate, creating }) {
  const [symbol, setSymbol] = useState('')
  const [condition, setCondition] = useState('ABOVE')
  const [threshold, setThreshold] = useState('')
  const [invalidationThreshold, setInvalidationThreshold] = useState('')
  const canSubmit = symbol.trim() && Number(threshold) > 0

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) {
          onCreate({
            symbol: symbol.trim(),
            condition,
            threshold: Number(threshold),
            invalidation_threshold: invalidationThreshold ? Number(invalidationThreshold) : undefined,
          })
        }
      }}
      className="rounded-2xl p-4 space-y-3 animate-slide-up-fade"
      style={{
        background: 'var(--color-panel)',
        border: '1px solid var(--color-gold)',
        boxShadow: 'var(--glow-gold)',
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-bold">🔔 New price alert</span>
        <button type="button" onClick={onClose} className="text-muted text-xs">
          ✕
        </button>
      </div>
      <p className="text-[10px]" style={{ color: 'var(--color-muted)' }}>
        Alerts use the connected market-data feed. Alerts clearly indicate REAL/LIVE vs TEST and alert upon invalidation.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Symbol
          <input
            required
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="RELIANCE"
            className="input-field mt-1 text-xs w-full"
          />
        </label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Condition
          <select
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            className="input-field mt-1 text-xs w-full"
          >
            <option value="ABOVE">Crosses above</option>
            <option value="BELOW">Crosses below</option>
          </select>
        </label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Price
          <input
            required
            min="0.01"
            step="any"
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            placeholder="0.00"
            className="input-field mt-1 text-xs w-full"
          />
        </label>
        <label className="text-[10px] font-bold" style={{ color: 'var(--color-muted)' }}>
          Invalidation SL (Opt)
          <input
            min="0.01"
            step="any"
            type="number"
            value={invalidationThreshold}
            onChange={(e) => setInvalidationThreshold(e.target.value)}
            placeholder="0.00"
            className="input-field mt-1 text-xs w-full"
          />
        </label>
      </div>
      <button disabled={!canSubmit || creating} className="btn btn-sm btn-gold">
        {creating ? 'Creating…' : 'Create alert'}
      </button>
    </form>
  )
}

function AlertsViewInner({ onOpenOrderTicket, defaultDensity = 'expanded' }) {
  const { call } = useAPI()
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)
  const brokerStatuses = useChatStore((s) => s.brokerStatuses)
  const brokerStatusReady = useChatStore((s) => s.brokerStatusReady)

  // Active tab: 'auto' (Live Auto-Alerts) vs 'manual' (User Price Alerts)
  const [activeTab, setActiveTab] = useState('auto')

  // Auto alerts state & view mode ('ACTIVE' default: clutter-free valid active trades | 'ARCHIVED' | 'ALL')
  const [autoViewMode, setAutoViewMode] = useState('ACTIVE')
  const [cleaning, setCleaning] = useState(false)
  const [purging, setPurging] = useState(false)
  const [cleanupNotice, setCleanupNotice] = useState(null)
  const [archiving, setArchiving] = useState(null)
  const [autoAlerts, setAutoAlerts] = useState([])
  const [autoLoading, setAutoLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [testing, setTesting] = useState(false)
  const [showTools, setShowTools] = useState(false) // Unified maintenance + simulation dropdown
  const toolsMenuRef = useRef(null)

  // Dismiss Tools dropdown when clicking outside or pressing Escape
  useEffect(() => {
    if (!showTools) return
    const handleClickOutside = (e) => {
      if (toolsMenuRef.current && !toolsMenuRef.current.contains(e.target)) {
        setShowTools(false)
      }
    }
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setShowTools(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('touchstart', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('touchstart', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [showTools])

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDirection, setSelectedDirection] = useState('ALL') // ALL | BULLISH | BEARISH
  // Multi-select allowed segments: set of 'FNO_INDEX' | 'FNO_STOCK' | 'EQUITY' | 'COMMODITY' | 'CURRENCY' | 'CRYPTO'
  const ALL_CANONICAL_SEGMENTS = useMemo(() => ['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO'], [])

  const [selectedSegments, setSelectedSegments] = useState(() => {
    try {
      const saved = localStorage.getItem('chanakya_selected_segments')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          const s = new Set()
          for (const item of parsed) {
            if (item === 'FNO' || item === 'F&O') {
              s.add('FNO_INDEX')
              s.add('FNO_STOCK')
            } else if (['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO'].includes(item)) {
              s.add(item)
            }
          }
          if (s.size > 0) return s
        }
      }
    } catch (_) {}
    return new Set(['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO'])
  })
  const [showRoutingModal, setShowRoutingModal] = useState(false)

  const ALL_SEGMENTS_LIST = ['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO']
  const isAllSegmentsSelected = selectedSegments.size === 6
  const selectedSegment = isAllSegmentsSelected ? 'ALL' : (selectedSegments.size === 1 ? Array.from(selectedSegments)[0] : 'CUSTOM')

  const connectedBrokers = useMemo(() => {
    return Object.entries(brokerStatuses || {}).filter(([, b]) => b.authenticated)
  }, [brokerStatuses])
  const hasActiveBrokerSession = connectedBrokers.length > 0

  const setSelectedSegment = useCallback((val) => {
    if (val === 'ALL') {
      const all = new Set(['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO'])
      setSelectedSegments(all)
      try { localStorage.setItem('chanakya_selected_segments', JSON.stringify([...all])) } catch (_) {}
    } else if (val === 'FNO') {
      const fno = new Set(['FNO_INDEX', 'FNO_STOCK'])
      setSelectedSegments(fno)
      try { localStorage.setItem('chanakya_selected_segments', JSON.stringify([...fno])) } catch (_) {}
    } else {
      const one = new Set([val])
      setSelectedSegments(one)
      try { localStorage.setItem('chanakya_selected_segments', JSON.stringify([...one])) } catch (_) {}
    }
  }, [])

  const handleToggleSegment = useCallback((segId) => {
    setSelectedSegments((prev) => {
      const allList = ['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO']
      if (segId === 'ALL') {
        const next = new Set(allList)
        try { localStorage.setItem('chanakya_selected_segments', JSON.stringify([...next])) } catch (_) {}
        return next
      }
      let next
      if (prev.size === 6 || (prev.size === 1 && !prev.has(segId))) {
        // Switching to single segment mode
        next = new Set([segId])
      } else if (prev.size === 1 && prev.has(segId)) {
        // Clicking active single segment restores ALL
        next = new Set(allList)
      } else {
        // Multi-select toggle
        next = new Set(prev)
        if (next.has(segId)) {
          next.delete(segId)
          if (next.size === 0) {
            next = new Set(allList)
          }
        } else {
          next.add(segId)
        }
      }
      try { localStorage.setItem('chanakya_selected_segments', JSON.stringify([...next])) } catch (_) {}
      return next
    })
  }, [])

  const handleSaveRoutingSuccess = useCallback((newPrefs) => {
    if (newPrefs?.ui?.allowed_segments && Array.isArray(newPrefs.ui.allowed_segments)) {
      const normalized = []
      for (const s of newPrefs.ui.allowed_segments) {
        if (s === 'FNO' || s === 'F&O') {
          if (!normalized.includes('FNO_INDEX')) normalized.push('FNO_INDEX')
          if (!normalized.includes('FNO_STOCK')) normalized.push('FNO_STOCK')
        } else if (['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO'].includes(s)) {
          if (!normalized.includes(s)) normalized.push(s)
        }
      }
      const setVal = new Set(normalized.length > 0 ? normalized : ['FNO_INDEX', 'FNO_STOCK', 'EQUITY', 'COMMODITY', 'CURRENCY', 'CRYPTO'])
      setSelectedSegments(setVal)
      try {
        localStorage.setItem('chanakya_selected_segments', JSON.stringify([...setVal]))
      } catch (_) {}
    }
  }, [])

  const [selectedFilter, setSelectedFilter] = useState('ALL')
  const [selectedHorizon, setSelectedHorizon] = useState('ALL') // ALL | INTRADAY | SWING_SHORT | SWING_MID | POSITIONAL
  const [selectedStage, setSelectedStage] = useState('ALL')
  const [selectedEnv, setSelectedEnv] = useState('ALL') // ALL | LIVE | TEST
  const [densityMode, setDensityMode] = useState(() => {
    try {
      const saved = localStorage.getItem('chanakya_alerts_density_mode')
      if (saved) return saved
      if (typeof process !== 'undefined' && process.env?.NODE_ENV === 'test') {
        return defaultDensity || 'expanded'
      }
      return defaultDensity || 'split'
    } catch (_) {
      return defaultDensity || 'split'
    }
  }) // compact | split | expanded
  const [selectedAlertId, setSelectedAlertId] = useState(null)
  const [selectedSort, setSelectedSort] = useState('NEWEST') // NEWEST | CONFIDENCE | RR_RATIO | STAGE

  // ── Institutional Audio Chime state with localStorage persistence ──────────
  const [chimeEnabled, setChimeEnabled] = useState(() => {
    try {
      return localStorage.getItem('chanakya_alert_chime') !== 'false'
    } catch (_) {
      return true
    }
  })
  const seenAlertIdsRef = useRef(new Set())
  const hasInitializedAlertsRef = useRef(false)

  const toggleChime = useCallback(() => {
    setChimeEnabled((prev) => {
      const next = !prev
      try { localStorage.setItem('chanakya_alert_chime', String(next)) } catch (_) {}
      if (next) playTerminalChime('IGNITED')
      return next
    })
  }, [])

  // ── Compact-row expand tracking: set of alert_ids that are expanded ──────
  const [expandedRows, setExpandedRows] = useState(new Set())
  const toggleExpandRow = useCallback((alertId) => {
    setExpandedRows((prev) => {
      const next = new Set(prev)
      if (next.has(alertId)) next.delete(alertId)
      else next.add(alertId)
      return next
    })
  }, [])

  // ── Invalidation dismissal & bulk-archive state ──────────────────────────
  const [dismissedInvalidationsTs, setDismissedInvalidationsTs] = useState(() => {
    try {
      return Number(sessionStorage.getItem('chanakya_dismissed_invalidations_ts') || 0)
    } catch (_) {
      return 0
    }
  })
  const [archivingInvalidated, setArchivingInvalidated] = useState(false)

  // ── Telegram preflight modal state ───────────────────────────────────────
  const [telegramAlert, setTelegramAlert] = useState(null) // The alert being dispatched
  const [telegramSending, setTelegramSending] = useState(false)
  const [telegramSentOk, setTelegramSentOk] = useState(false)
  const [telegramSentError, setTelegramSentError] = useState(null)

  const handleOpenTelegramModal = useCallback((alert) => {
    setTelegramAlert(alert)
    setTelegramSending(false)
    setTelegramSentOk(false)
    setTelegramSentError(null)
  }, [])

  const handleCloseTelegramModal = useCallback(() => {
    setTelegramAlert(null)
    setTelegramSending(false)
    setTelegramSentOk(false)
    setTelegramSentError(null)
  }, [])

  const handleConfirmTelegram = useCallback(async (customChatId = null) => {
    if (!telegramAlert) return
    setTelegramSending(true)
    setTelegramSentError(null)
    try {
      const payload = { alert_id: telegramAlert.alert_id }
      if (customChatId && String(customChatId).trim()) {
        payload.chat_id = String(customChatId).trim()
      }
      await callRef.current('/api/alerts/auto/send-telegram', payload)
      setTelegramSentOk(true)
      // Auto-close after 2.2s on success
      setTimeout(() => handleCloseTelegramModal(), 2200)
    } catch (err) {
      setTelegramSentError(err.message || 'Failed to send. Check Telegram bot configuration.')
    } finally {
      setTelegramSending(false)
    }
  }, [telegramAlert, handleCloseTelegramModal])


  // Manual alerts state
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState(null)

  // Live streaming spot quotes are now managed inside LiveSpotsProvider (a context).
  // No useState here — prices NEVER cause AlertsView to re-render, preserving scroll perfectly.
  const liveSpotsCtx = useContext(LiveSpotsCtx)

  // Persistent scroll position — saved on user scroll, restored on mount
  const scrollContainerRef = useRef(null)
  const userScrollTopRef = useRef(0)

  // Restore scroll position on initial view mount if user previously scrolled
  useLayoutEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    try {
      const saved = Number(sessionStorage.getItem('chanakya_alerts_scroll_pos') || 0)
      if (saved > 0 && container.scrollTop === 0) {
        container.scrollTop = saved
        userScrollTopRef.current = saved
      }
    } catch (_) {}
  }, [])

  const handleScroll = useCallback((e) => {
    const target = e.target
    if (!target || target.scrollTop === undefined) return
    userScrollTopRef.current = target.scrollTop
    try {
      sessionStorage.setItem('chanakya_alerts_scroll_pos', String(target.scrollTop))
    } catch (_) {}
  }, [])

  useEffect(() => { callRef.current = call }, [call])

  // Load manual alerts (silent background refresh when isInitial is false)
  const loadAlerts = useCallback(async (isInitial = false) => {
    if (isInitial) setLoading(true)
    setError(null)
    try {
      const response = await callRef.current('/skills/alerts/list')
      const fresh = response?.data ?? response ?? []
      setAlerts((prev) => {
        if (prev.length === fresh.length && JSON.stringify(prev) === JSON.stringify(fresh)) {
          return prev
        }
        return fresh
      })
    } catch (err) {
      setError(err.message || 'Alerts are unavailable')
    } finally {
      if (isInitial) setLoading(false)
    }
  }, [])

  // Load auto alerts (silent in-place merge: zero scroll jumps, zero card re-renders)
  // NOTE: auto-alerts are ALSO synced by the singleton notificationStore.startPolling() loop
  // (owned by NotificationBell). This local fetch is kept only for view-mode filtering
  // (LIVE/ALL/TEST) and initial population on mount — not as a recurring timer.
  const loadAutoAlerts = useCallback(async (isInitial = false) => {
    if (isInitial) setAutoLoading(true)
    try {
      const res = await callRef.current('/skills/alerts/auto/list', { view_mode: autoViewMode })
      const fresh = res?.data ?? res ?? []

      // Institutional chime check on live ignited alerts
      if (hasInitializedAlertsRef.current && fresh.length > 0) {
        let hasNewIgnited = false
        for (const a of fresh) {
          const aid = a.alert_id || a.id
          if (aid && !seenAlertIdsRef.current.has(aid)) {
            seenAlertIdsRef.current.add(aid)
            if (a.stage === 'IGNITED' && a.environment !== 'TEST' && a.is_live !== false) {
              hasNewIgnited = true
            }
          }
        }
        if (hasNewIgnited && chimeEnabled) {
          playTerminalChime('IGNITED')
        }
      } else {
        for (const a of fresh) {
          const aid = a.alert_id || a.id
          if (aid) seenAlertIdsRef.current.add(aid)
        }
        hasInitializedAlertsRef.current = true
      }

      setAutoAlerts((prev) => mergeAlertsInPlace(prev, fresh))
    } catch (_) {
      // Fallback empty
    } finally {
      if (isInitial) setAutoLoading(false)
    }
  }, [autoViewMode, chimeEnabled])

  // Re-fetch when autoViewMode toggles (view filter changed — must re-query)
  useEffect(() => {
    loadAutoAlerts(false)
  }, [autoViewMode, loadAutoAlerts])

  // Sync store notifications into local autoAlerts so SSE-driven store updates
  // are reflected in the view without a separate poll.
  const storeNotifications = useNotificationStore((s) => s.notifications)
  useEffect(() => {
    if (!storeNotifications || storeNotifications.length === 0) return
    // Only merge AUTO-type alerts (PRICE/TECHNICAL/OPTIONS alerts come from manual list)
    // and exclude any test/simulated alerts
    const autoFromStore = storeNotifications.filter(
      (n) => n.alert_type && !['PRICE', 'TECHNICAL', 'CONDITIONAL'].includes(n.alert_type) && !isTestOrSimAlert(n)
    )
    if (autoFromStore.length > 0) {
      setAutoAlerts((prev) => mergeAlertsInPlace(prev, autoFromStore))
    }
  }, [storeNotifications])

  useEffect(() => {
    loadAlerts(true)
    loadAutoAlerts(true)

    // 1. Instant real-time update when SSE alert arrives (in-place replacement for existing, prepend for new)
    const handleLiveAlert = (event) => {
      const detail = event.detail
      if (!detail) return
      const newAlert = detail.alert || detail
      if (!newAlert || (!newAlert.alert_id && !newAlert.id && !newAlert.symbol)) return

      if (newAlert.alert_type === 'PRICE' || newAlert.alert_type === 'TECHNICAL' || newAlert.alert_type === 'CONDITIONAL') {
        setAlerts((prev) => {
          const id = newAlert.alert_id || newAlert.id
          const exists = prev.some((a) => (a.id || a.alert_id) === id)
          if (exists) {
            return prev.map((a) => ((a.id || a.alert_id) === id ? { ...a, ...newAlert } : a))
          }
          return [newAlert, ...prev]
        })
      } else {
        const aid = newAlert.alert_id || newAlert.id
        if (aid && !seenAlertIdsRef.current.has(aid)) {
          seenAlertIdsRef.current.add(aid)
          if (newAlert.stage === 'IGNITED' && newAlert.environment !== 'TEST' && newAlert.is_live !== false) {
            if (chimeEnabled) playTerminalChime('IGNITED')
          }
        }
        setAutoAlerts((prev) => mergeAlertsInPlace(prev, [newAlert]))
      }
    }

    window.addEventListener('new-market-alert', handleLiveAlert)

    // Clear event dispatched from SSE auto_alerts_cleared broadcast
    const handleClearEvent = (e) => {
      const mode = e?.detail?.mode || 'TEST_ONLY'
      if (mode === 'ALL') {
        setAutoAlerts([])
        setAlerts([])
        setSelectedAlertId(null)
      } else {
        setAutoAlerts((prev) => prev.filter((item) => !isTestOrSimAlert(item)))
        setAlerts((prev) => prev.filter((item) => !isTestOrSimAlert(item)))
      }
    }
    window.addEventListener('auto-alerts-cleared', handleClearEvent)

    // 2. Background polling — MANUAL alerts only (30s); auto-alerts come from SSE + store.
    // Reduced from 15s to 30s; auto-alerts no longer duplicated here.
    const syncTimer = setInterval(() => {
      loadAlerts(false)
    }, 30_000)

    return () => {
      window.removeEventListener('new-market-alert', handleLiveAlert)
      window.removeEventListener('auto-alerts-cleared', handleClearEvent)
      clearInterval(syncTimer)
    }
  }, [loadAlerts, loadAutoAlerts, chimeEnabled])

  // Extract all active / visible symbols to stream spot prices and option/future contract prices for
  const activeSymbols = useMemo(() => {
    const syms = new Set()
    const addSym = (raw) => {
      if (!raw || typeof raw !== 'string') return
      const clean = raw.replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
      if (clean) syms.add(clean)
    }

    for (const alt of autoAlerts) {
      addSym(alt.symbol)
      addSym(alt.contract_symbol)
      addSym(alt.actionable_plan?.option_plan?.contract_symbol)
      addSym(alt.actionable_plan?.option_contract)
      addSym(alt.metrics?.option_symbol)
      const related = alt.related_strikes || alt.metrics?.related_strikes
      if (Array.isArray(related)) {
        related.forEach(addSym)
      }
    }
    for (const a of alerts) {
      addSym(a.symbol)
      addSym(a.contract_symbol)
      addSym(a.actionable_plan?.option_plan?.contract_symbol)
      addSym(a.actionable_plan?.option_contract)
    }
    return Array.from(syms)
  }, [autoAlerts, alerts])

  // Real-time batch quote streaming for all active alert symbols (2.0s interval)
  // Real-time batch quote streaming — publishes to LiveSpotsContext.
  // AlertsView itself does NOT re-render from price updates.
  // Only the individual cards whose symbol changed re-render (via useLiveSpot hook).
  useEffect(() => {
    if (activeSymbols.length === 0 || !liveSpotsCtx) return

    let cancelled = false

    const fetchLiveSpots = async () => {
      if (typeof document !== 'undefined' && document.hidden) return
      try {
        const res = await callRef.current('/skills/quotes/batch', {
          symbols: activeSymbols,
          exchange: 'NSE',
        })
        if (cancelled) return
        const quotes = extractQuotes(res)
        if (!quotes || Object.keys(quotes).length === 0) return
        // Push into context — zero AlertsView re-renders
        liveSpotsCtx.publish(quotes)
      } catch (_) {
        // Silently tolerate temporary network blips
      }
    }

    fetchLiveSpots()
    // Market-hours-aware interval: 2s during open hours, 5s when closed.
    // This halves connection pressure outside trading hours (14:00–09:15 IST).
    const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000
    const istNow = new Date(Date.now() + new Date().getTimezoneOffset() * 60000 + IST_OFFSET_MS)
    const hhmm = istNow.getHours() * 100 + istNow.getMinutes()
    const day = istNow.getDay()
    const isMarketOpen = day >= 1 && day <= 5 && hhmm >= 915 && hhmm < 1530
    const quoteIntervalMs = isMarketOpen ? 2000 : 5000
    const quoteInterval = setInterval(fetchLiveSpots, quoteIntervalMs)

    const handleVisibilityChange = () => { if (!document.hidden) fetchLiveSpots() }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cancelled = true
      clearInterval(quoteInterval)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [activeSymbols, liveSpotsCtx])

  // Manual alert creation/deletion
  const createAlert = async (payload) => {
    setCreating(true)
    try {
      await callRef.current('/skills/alerts/add', payload)
      setShowCreate(false)
      await loadAlerts(false)
    } catch (err) {
      setError(err.message || 'Could not create the alert')
    } finally {
      setCreating(false)
    }
  }

  const removeAlert = async (id) => {
    setRemoving(id)
    try {
      await callRef.current('/skills/alerts/remove', { alert_id: id })
      await loadAlerts(false)
    } catch (err) {
      setError(err.message || 'Could not remove the alert')
    } finally {
      setRemoving(null)
    }
  }

  // Auto-alert scan trigger
  const handleScanNow = async () => {
    setScanning(true)
    try {
      const res = await callRef.current('/skills/alerts/auto/scan_now', {})
      const fresh = res?.data?.all_recent ?? res?.data ?? []
      setAutoAlerts((prev) => mergeAlertsInPlace(prev, fresh))
    } catch (_) {
    } finally {
      setScanning(false)
    }
  }

  // Trigger test alert (clearly marked as TEST)
  const handleTriggerTest = async (isInvalidation = false) => {
    setTesting(true)
    try {
      await callRef.current('/skills/alerts/auto/test', {
        alert_type: isInvalidation ? 'SQUEEZE_BREAKOUT' : 'GAMMA_BLAST',
        stage: isInvalidation ? 'INVALIDATED' : 'EARLY_WARNING',
        symbol: isInvalidation ? 'RELIANCE' : 'NIFTY',
        is_invalidation: isInvalidation,
      })
      await loadAutoAlerts(false)
    } catch (_) {
    } finally {
      setTesting(false)
    }
  }

  // Check invalidations immediately
  const handleCheckInvalidations = async () => {
    try {
      await callRef.current('/skills/alerts/auto/check_invalidations', {})
      await loadAutoAlerts(false)
    } catch (_) {}
  }

  // Trigger test target achieved or trailing alert
  const handleTriggerTestTarget = async (milestone = 'T1', shouldTrail = true) => {
    setTesting(true)
    try {
      await callRef.current('/skills/alerts/auto/test_target', {
        milestone,
        should_trail: shouldTrail,
        symbol: 'RELIANCE',
      })
      await loadAutoAlerts(false)
    } catch (_) {
    } finally {
      setTesting(false)
    }
  }

  // Check targets and trailing stops immediately
  const handleCheckTargets = async () => {
    try {
      await callRef.current('/skills/alerts/auto/check_targets', {})
      await loadAutoAlerts(false)
    } catch (_) {}
  }

  const handleArchiveToggle = useCallback(async (alertId, archive) => {
    setArchiving(alertId)
    // Immediate optimistic local update to guarantee zero lag or flicker
    setAutoAlerts((prev) =>
      prev.map((a) =>
        a.alert_id === alertId
          ? {
              ...a,
              is_archived: archive,
              is_active: !archive && !a.is_invalidated && a.stage !== 'INVALIDATED' && a.stage !== 'TARGET_ACHIEVED',
            }
          : a
      )
    )
    try {
      await callRef.current('/skills/alerts/auto/archive', {
        alert_id: alertId,
        archive,
        reason: archive ? 'Manual user archive to avoid clutter' : 'Restored to active trades',
      })
      await loadAutoAlerts(false)
    } catch (err) {
      console.error('Failed to toggle archive status:', err)
      await loadAutoAlerts(false)
    } finally {
      setArchiving(null)
    }
  }, [loadAutoAlerts])

  const handleCleanupOld = async (maxAgeDays = 3) => {
    setCleaning(true)
    setCleanupNotice(null)
    try {
      const res = await callRef.current('/skills/alerts/auto/cleanup', { max_age_days: maxAgeDays })
      const data = res?.data ?? res
      const purged = data?.purged_count ?? 0
      const reaped = data?.reaped ?? 0
      setCleanupNotice(
        purged > 0
          ? `🧹 Cleaned up ${purged} archived records older than ${maxAgeDays} days. Active valid trades preserved.`
          : reaped > 0
          ? `🧹 Cleaned up ${reaped} expired derivative alerts. Active valid trades preserved.`
          : `✨ No archived records older than ${maxAgeDays} days. Active trades remain intact.`
      )
      await loadAutoAlerts(false)
      setTimeout(() => setCleanupNotice(null), 5000)
    } catch (err) {
      setCleanupNotice(`Cleanup failed: ${err.message}`)
    } finally {
      setCleaning(false)
    }
  }

  const handlePurgeExpired = async () => {
    setPurging(true)
    setCleanupNotice(null)
    try {
      const res = await callRef.current('/skills/alerts/auto/cleanup_expired', { purge: true })
      const data = res?.data ?? res
      const purged = data?.purged ?? data?.reaped ?? 0
      setCleanupNotice(
        purged > 0
          ? `🧹 Successfully purged ${purged} expired contracts from alerts storage.`
          : '✨ No expired derivative contracts found to purge.'
      )
      await loadAutoAlerts(true)
      setTimeout(() => setCleanupNotice(null), 5000)
    } catch (err) {
      setCleanupNotice(`Could not purge expired alerts: ${err.message}`)
    } finally {
      setPurging(false)
    }
  }

  // ── Invalidation Banner controls ──────────────────────────────────────────
  const handleDismissInvalidationBanner = useCallback(() => {
    const now = Date.now()
    try {
      sessionStorage.setItem('chanakya_dismissed_invalidations_ts', String(now))
    } catch (_) {}
    setDismissedInvalidationsTs(now)
  }, [])

  const handleArchiveAllInvalidated = useCallback(async () => {
    setArchivingInvalidated(true)
    try {
      await callRef.current('/skills/alerts/auto/archive_all_invalidated', {})
    } catch (_) {}

    // Optimistically mark all local invalidated alerts as archived
    setAutoAlerts((prev) =>
      prev.map((a) =>
        (a.is_invalidated || a.stage === 'INVALIDATED')
          ? { ...a, is_archived: true, archived_at: new Date().toISOString(), archive_reason: 'Bulk archived invalidated setups' }
          : a
      )
    )

    // Sync notificationStore if present
    try {
      const store = useNotificationStore.getState()
      if (store && store.notifications) {
        const updated = store.notifications.map((n) =>
          (n.is_invalidated || n.stage === 'INVALIDATED')
            ? { ...n, is_archived: true, isArchived: true }
            : n
        )
        store.syncRecentAlerts(updated)
      }
    } catch (_) {}

    const now = Date.now()
    try {
      sessionStorage.setItem('chanakya_dismissed_invalidations_ts', String(now))
    } catch (_) {}
    setDismissedInvalidationsTs(now)

    setCleanupNotice(`📦 Successfully archived invalidated trade setups to Archived & History.`)
    setTimeout(() => setCleanupNotice(null), 5000)
    setArchivingInvalidated(false)
  }, [])

  const handleResetFilters = () => {
    setSearchQuery('')
    setSelectedFilter('ALL')
    setSelectedDirection('ALL')
    setSelectedSegment('ALL')
    setSelectedStage('ALL')
    setSelectedEnv('ALL')
    setDensityMode('compact')
    setSelectedSort('NEWEST')
    setExpandedRows(new Set())
  }

  // Clear entire auto-alert feed (emergency reset)
  const handleClearAuto = async () => {
    try {
      await callRef.current('/skills/alerts/auto/clear', {})
    } catch (_) {}
    setAutoAlerts([])
    setAlerts([])
    setSelectedAlertId(null)
    useNotificationStore.getState().clearAll()
    try {
      localStorage.removeItem('chanakya_notifications_v1')
    } catch (_) {}
    seenAlertIdsRef.current.clear()
  }

  const handleClearTestAlerts = useCallback(async () => {
    try {
      await callRef.current('/skills/alerts/auto/clear_test', {})
    } catch (_) {
      try {
        await callRef.current('/skills/alerts/auto/clear', {})
      } catch (__) {}
    }

    // 1. Immediately purge from local component states
    setAutoAlerts((prev) => prev.filter((item) => !isTestOrSimAlert(item)))
    setAlerts((prev) => prev.filter((item) => !isTestOrSimAlert(item)))

    // 2. Purge from Zustand notification store
    useNotificationStore.getState().purgeTestAlerts()

    // 3. Purge from localStorage
    try {
      const raw = localStorage.getItem('chanakya_notifications_v1')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          const filtered = parsed.filter((item) => !isTestOrSimAlert(item))
          localStorage.setItem('chanakya_notifications_v1', JSON.stringify(filtered))
        }
      }
    } catch (_) {}

    // 4. Clear active selection if it was a test alert & reset seen cache
    setSelectedAlertId(null)
    seenAlertIdsRef.current.clear()
  }, [])

  // Dismiss a single alert card permanently
  const handleDismissAlert = useCallback((alertId) => {
    if (!alertId) return
    const idStr = String(alertId).toUpperCase()
    const matchesTarget = (a) => {
      const aId = String(a.alert_id || a.id || '').toUpperCase()
      const aSym = String(a.symbol || '').toUpperCase()
      const aContract = String(a.contract_symbol || '').toUpperCase()
      return aId === idStr || aSym === idStr || aContract === idStr || aSym.includes(idStr) || aContract.includes(idStr)
    }

    setAutoAlerts((prev) => prev.filter((a) => !matchesTarget(a)))
    setAlerts((prev) => prev.filter((a) => !matchesTarget(a)))
    setSelectedAlertId((prev) => (prev && (prev === alertId || String(prev).includes(alertId) || String(alertId).includes(prev)) ? null : prev))
    useNotificationStore.getState().removeNotification(alertId)
    try {
      const raw = localStorage.getItem('chanakya_notifications_v1')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          const filtered = parsed.filter((item) => !matchesTarget(item))
          localStorage.setItem('chanakya_notifications_v1', JSON.stringify(filtered))
        }
      }
    } catch (_) {}
    try {
      callRef.current('/skills/alerts/auto/archive', {
        alert_id: alertId,
        archive: true,
        reason: 'User manually dismissed from alert feed',
      })
    } catch (_) {}
  }, [])

  // Clear single lockout manually if institutional reclaim spotted
  const handleClearLockout = useCallback(async (symbol) => {
    try {
      await callRef.current('/skills/alerts/auto/clear_lockout', { symbol })
      await loadAutoAlerts(false)
    } catch (err) {
      console.error('Failed to clear lockout:', err)
    }
  }, [loadAutoAlerts])

  const handleInspectOptions = useCallback(() => {
    setActiveView('options')
  }, [setActiveView])

  const handleAnalyze = useCallback((sym) => {
    sendDraft(`analyze ${sym}`)
  }, [sendDraft])

  const handleOpenTicket = useCallback((alt) => {
    const actPlan = alt.actionable_plan || {}
    const optPlan = actPlan.option_plan || null
    const tradePlan = actPlan.trade_plan || null
    const cleanSym = (alt.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
    const isPureOpt = alt.alert_type === 'OPTIONS_MOMENTUM' ||
      alt.alert_type === 'OPTION_WRITE' ||
      (alt.alert_type === 'GAMMA_BLAST' && (alt.option_type || alt.contract_symbol)) ||
      (alt.contract_symbol && (alt.contract_symbol.endsWith('CE') || alt.contract_symbol.endsWith('PE')) && alt.exchange === 'NFO')

    const wantOption = Boolean(alt._tradeOptionAlternative || (isPureOpt && (alt.contract_symbol || optPlan?.contract_symbol)))

    let targetSym = alt.contract_symbol || alt.symbol
    let targetPrice = alt.trigger_level || alt.ltp
    let targetSL = alt.stop_loss
    let targetTP = alt.target_level

    // Resolve exchange from alert metadata first
    const seg = classifyAlertSegment(alt)
    let targetExchange = alt.exchange || (
      seg === 'COMMODITY' ? 'MCX' :
      seg === 'CURRENCY' ? 'CDS' :
      seg === 'FNO' ? 'NFO' : 'NSE'
    )

    if (alt._isStrikeRoll) {
      const roll = alt._rollRecommendation || alt.strike_roll_recommendation
      if (roll?.recommended_contract) {
        targetSym = roll.recommended_contract
      } else if (roll?.recommended_strike) {
        const oType = alt.option_type || (String(targetSym).endsWith('PE') ? 'PE' : 'CE')
        targetSym = `${cleanSym} ${roll.recommended_strike} ${oType}`
      }
      targetExchange = alt.exchange === 'BSE' ? 'BFO' : (alt.exchange === 'MCX' ? 'MCX' : 'NFO')
      targetPrice = null
      targetSL = null
      targetTP = null
    } else if (wantOption) {
      targetExchange = 'NFO'
      if (optPlan?.contract_symbol) targetSym = optPlan.contract_symbol
      else if (actPlan.option_contract) targetSym = actPlan.option_contract
      else if (alt.contract_symbol) targetSym = alt.contract_symbol

      if (optPlan?.entry_premium && Number(optPlan.entry_premium) > 0) targetPrice = Number(optPlan.entry_premium)
      else if (alt.option_premium && Number(alt.option_premium) > 0) targetPrice = Number(alt.option_premium)
      else if (actPlan.option_entry) {
        const p = parseFloat(String(actPlan.option_entry).replace(/[₹,\s]/g, ''))
        if (!isNaN(p) && p > 0) targetPrice = p
      } else if (isPureOpt && alt.ltp && Number(alt.ltp) > 0) {
        targetPrice = Number(alt.ltp)
      } else {
        targetPrice = null
      }

      if (optPlan?.sl_premium && Number(optPlan.sl_premium) > 0) targetSL = Number(optPlan.sl_premium)
      else if (alt.option_stop_loss && Number(alt.option_stop_loss) > 0) targetSL = Number(alt.option_stop_loss)
      else if (actPlan.option_stop_loss) {
        const sl = parseFloat(String(actPlan.option_stop_loss).replace(/[₹,\s]/g, ''))
        if (!isNaN(sl) && sl > 0) targetSL = sl
      } else if (isPureOpt && alt.stop_loss && Number(alt.stop_loss) > 0) {
        targetSL = Number(alt.stop_loss)
      } else if (targetPrice && targetPrice > 0) {
        targetSL = Math.max(0.05, Math.round(targetPrice * 0.70 * 100) / 100)
      }

      if (optPlan?.t1_premium && Number(optPlan.t1_premium) > 0) targetTP = Number(optPlan.t1_premium)
      else if (alt.option_target_1 && Number(alt.option_target_1) > 0) targetTP = Number(alt.option_target_1)
      else if (actPlan.option_target_1) {
        const tp = parseFloat(String(actPlan.option_target_1).replace(/[₹,\s]/g, ''))
        if (!isNaN(tp) && tp > 0) targetTP = tp
      } else if (isPureOpt && alt.target_level && Number(alt.target_level) > 0) {
        targetTP = Number(alt.target_level)
      } else if (targetPrice && targetPrice > 0) {
        targetTP = Math.round(targetPrice * 1.60 * 100) / 100
      }
    } else {
      // Direct Cash / Equity / Index Spot trade
      targetSym = cleanSym
      if (seg === 'EQUITY' || seg === 'FNO') targetExchange = 'NSE'
      if (tradePlan) {
        if (tradePlan.entry_price) targetPrice = Number(tradePlan.entry_price)
        if (tradePlan.invalidation_stop) targetSL = Number(tradePlan.invalidation_stop)
        if (tradePlan.target_1) targetTP = Number(tradePlan.target_1)
      } else {
        if (alt.trigger_level) targetPrice = Number(alt.trigger_level)
        if (alt.stop_loss) targetSL = Number(alt.stop_loss)
        if (alt.target_level) targetTP = Number(alt.target_level)
      }
    }

    const lotSize = wantOption
      ? (optPlan?.lot_size || alt.lot_size || alt.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null)
      : (seg === 'COMMODITY' || seg === 'CURRENCY' ? (alt.lot_size || INDEX_LOT_SIZES[cleanSym] || null) : null)

    const ticketData = {
      symbol: targetSym,
      contract_symbol: targetSym,
      exchange: targetExchange,
      price: targetPrice != null && !isNaN(targetPrice) ? Number(targetPrice) : undefined,
      target: targetTP != null && !isNaN(targetTP) ? Number(targetTP) : undefined,
      stopLoss: targetSL != null && !isNaN(targetSL) ? Number(targetSL) : undefined,
      lotSize: lotSize != null && !isNaN(lotSize) ? Number(lotSize) : undefined,
      quantity: lotSize != null && !isNaN(lotSize) ? Number(lotSize) : 1,
      action: alt.direction === 'BEARISH' && !String(targetSym).toUpperCase().includes('PE') ? 'SELL' : 'BUY',
    }

    if (onOpenOrderTicket) {
      onOpenOrderTicket(ticketData)
    }

    window.dispatchEvent(
      new CustomEvent('open-order-ticket-modal', {
        detail: ticketData,
      })
    )
  }, [onOpenOrderTicket])


  // Active validation check: True only if trade is neither archived, invalidated, expired, nor final target reached
  const isAlertActive = (a) => {
    if (!a) return false
    if (a.is_expired || a.stage === 'EXPIRED' || a.is_invalidated || a.is_archived) return false
    if (a.stage === 'INVALIDATED' || a.stage === 'TARGET_ACHIEVED' || a.stage === 'COMPLETED' || a.target_status === 'TARGET_ACHIEVED') return false

    // Check Intraday session expiration
    const horizon = a.time_horizon || a.timeHorizon || 'INTRADAY'
    if (horizon === 'INTRADAY' && (a.created_at || a.timestamp)) {
      try {
        const clean = String(a.created_at || a.timestamp).replace(' IST', '').trim()
        const createdDate = new Date(clean)
        const now = new Date()
        if (!isNaN(createdDate.getTime()) && createdDate.toDateString() !== now.toDateString()) {
          return false
        }
      } catch (_) {}
    }

    return a.is_active !== undefined
      ? Boolean(a.is_active)
      : true
  }

  const activeCount = autoAlerts.filter(isAlertActive).length
  const archivedCount = autoAlerts.length - activeCount
  const expiredCount = autoAlerts.filter((a) => a.is_expired || a.stage === 'EXPIRED').length

  // Safe helper to parse alert timestamp to epoch ms (handles ISO, IST strings, and nulls)
  const parseAlertTimestamp = (raw) => {
    if (!raw) return null
    try {
      const clean = String(raw).replace(' IST', '').trim().replace(' ', 'T')
      const t = new Date(clean).getTime()
      return isNaN(t) ? null : t
    } catch (_) {
      return null
    }
  }

  // Invalidation count for banner:
  // 1. Must not already be archived (archived setups belong in history tab, not active radar)
  // 2. Must be within 15 mins of invalidation (avoids zombie warnings)
  // 3. Respects user dismissal in the current session
  const invalidatedAlerts = useMemo(() => {
    return autoAlerts.filter((a) => {
      if (!a.is_invalidated && a.stage !== 'INVALIDATED') return false
      if (a.is_archived || a.isArchived) return false

      const invTime = parseAlertTimestamp(a.invalidated_at || a.created_at || a.timestamp)
      if (invTime) {
        // Auto-expire from warning banner after 15 mins
        if ((Date.now() - invTime) > 15 * 60 * 1000) return false
        // Dismissed by user in current session
        if (dismissedInvalidationsTs && invTime <= dismissedInvalidationsTs) return false
      } else if (dismissedInvalidationsTs) {
        return false
      }
      return true
    })
  }, [autoAlerts, dismissedInvalidationsTs])
  const invalidatedCount = invalidatedAlerts.length

  // Deduplicate invalidated symbols to prevent repetitive "MANKIND, MANKIND" in the banner
  const uniqueInvalidatedList = useMemo(() => {
    const map = new Map()
    for (const a of invalidatedAlerts) {
      if (!map.has(a.symbol)) {
        map.set(a.symbol, `${a.symbol} (${a.alert_type?.replace('_', ' ') || 'SETUP'})`)
      }
    }
    return Array.from(map.values())
  }, [invalidatedAlerts])

  // Filter auto-alerts with duplicate suppression and memoization
  const filteredAutoAlerts = useMemo(() => {
    const seenIds = new Set()
    let results = autoAlerts.filter((a) => {
      const id = a.alert_id || a.id
      if (id) {
        if (seenIds.has(id)) return false
        seenIds.add(id)
      }

      // 1. Primary Filter: View Mode
      if (autoViewMode === 'ACTIVE' && !isAlertActive(a)) return false
      if (autoViewMode === 'ARCHIVED' && isAlertActive(a)) return false

      // 2. Search Query Filter (Symbol, Contract, Headline, Summary)
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toUpperCase()
        const matchSym = a.symbol?.toUpperCase().includes(q)
        const matchContract = a.contract_symbol?.toUpperCase().includes(q)
        const matchHeadline = a.headline?.toUpperCase().includes(q)
        const matchSummary = a.summary?.toUpperCase().includes(q)
        if (!matchSym && !matchContract && !matchHeadline && !matchSummary) return false
      }

      // 3. Direction Filter
      if (selectedDirection !== 'ALL' && a.direction !== selectedDirection) return false

      // 4. Unified Multi-Select Segment Filter (FNO_INDEX, FNO_STOCK, EQUITY, COMMODITY, CURRENCY, CRYPTO)
      if (selectedSegments.size < ALL_CANONICAL_SEGMENTS.length) {
        const seg = classifyAlertSegment(a)
        if (!selectedSegments.has(seg) && !(selectedSegments.has('FNO') && (seg === 'FNO_INDEX' || seg === 'FNO_STOCK'))) {
          return false
        }
      }

      // 5. Category / Alert-Type Filter
      if (selectedFilter === 'INVALIDATED') {
        if (!a.is_invalidated && a.stage !== 'INVALIDATED') return false
      } else if (selectedFilter === 'TARGET_HIT') {
        if (
          a.stage !== 'T1_ACHIEVED' &&
          a.stage !== 'TARGET_ACHIEVED' &&
          a.target_status !== 'T1_ACHIEVED' &&
          a.target_status !== 'TARGET_ACHIEVED'
        ) return false
      } else if (selectedFilter === 'HIGH_CONVICTION') {
        if (Number(a.confidence || 0) < 85) return false
      } else if (selectedFilter === 'MULTI_FLOW') {
        const rel = a.metrics?.related_strikes || a.related_strikes
        if (!Array.isArray(rel) || rel.length === 0) return false
      } else if (selectedFilter !== 'ALL' && a.alert_type !== selectedFilter && a.event_type !== selectedFilter) {
        return false
      }

      // 6. Stage Filter
      if (selectedStage !== 'ALL') {
        if (selectedStage === 'INVALIDATED' && !a.is_invalidated && a.stage !== 'INVALIDATED') return false
        if (selectedStage === 'T1_ACHIEVED' && a.stage !== 'T1_ACHIEVED' && a.target_status !== 'T1_ACHIEVED') return false
        if (selectedStage === 'TARGET_ACHIEVED' && a.stage !== 'TARGET_ACHIEVED' && a.target_status !== 'TARGET_ACHIEVED') return false
        if (
          selectedStage !== 'INVALIDATED' &&
          selectedStage !== 'T1_ACHIEVED' &&
          selectedStage !== 'TARGET_ACHIEVED' &&
          a.stage !== selectedStage
        ) return false
      }

      // 7. Environment Filter
      if (selectedEnv === 'LIVE') {
        if (a.environment === 'TEST' || a.is_live === false) return false
      } else if (selectedEnv === 'TEST') {
        if (a.environment !== 'TEST' && a.is_live !== false) return false
      }

      // 7b. Time Horizon Filter
      if (selectedHorizon !== 'ALL') {
        const h = a.time_horizon || 'INTRADAY'
        if (h !== selectedHorizon) return false
      }

      return true
    })

    // Helper to safely parse alert timestamp to epoch ms for deterministic ordering
    const getAlertEpoch = (a) => {
      const raw = a.created_at || a.timestamp || ''
      if (!raw) return 0
      try {
        const clean = raw.replace(' IST', '').trim()
        const ts = Date.parse(clean)
        return isNaN(ts) ? 0 : ts
      } catch (_) {
        return 0
      }
    }

    // 8. Multi-Sort (Default: Newest first; user selectable multi-tier sort)
    results = [...results].sort((a, b) => {
      const timeDiff = getAlertEpoch(b) - getAlertEpoch(a)
      const confDiff = (Number(b.confidence || 0)) - (Number(a.confidence || 0))

      if (selectedSort === 'CONFIDENCE') {
        // Multi-sort: Conviction DESC -> Newest first
        if (confDiff !== 0) return confDiff
        return timeDiff
      } else if (selectedSort === 'RR_RATIO') {
        // Multi-sort: Expected R:R DESC -> Conviction DESC -> Newest first
        const rrDiff = (Number(b.metrics?.expected_rr || 0)) - (Number(a.metrics?.expected_rr || 0))
        if (rrDiff !== 0) return rrDiff
        if (confDiff !== 0) return confDiff
        return timeDiff
      } else if (selectedSort === 'STAGE') {
        // Multi-sort: Stage priority (IGNITED first) -> Conviction DESC -> Newest first
        const stagePriority = {
          IGNITED: 0,
          TRAILING_UPDATE: 1,
          EARLY_WARNING: 2,
          T1_ACHIEVED: 3,
          TARGET_ACHIEVED: 4,
          INVALIDATED: 5,
          EXPIRED: 6,
        }
        const pa = stagePriority[a.stage] ?? 2
        const pb = stagePriority[b.stage] ?? 2
        if (pa !== pb) return pa - pb
        if (confDiff !== 0) return confDiff
        return timeDiff
      }
      // Default: NEWEST first, then highest conviction as tie-breaker
      if (timeDiff !== 0) return timeDiff
      return confDiff
    })

    return results
  }, [autoAlerts, autoViewMode, selectedFilter, selectedHorizon, selectedStage, selectedEnv, searchQuery, selectedDirection, selectedSegment, selectedSegments, selectedSort])

  // Group repeated attempts for the same symbol so the screen remains clean and uncluttered
  const groupedAutoAlerts = useMemo(() => {
    const symbolGroups = new Map()
    for (const alt of filteredAutoAlerts) {
      const clean = alt.symbol?.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase() || 'UNKNOWN'
      const subKey = alt.strike || alt.contract_symbol || alt.derivative_type || ''
      const key = `${clean}:${alt.alert_type || ''}:${subKey}`
      if (!symbolGroups.has(key)) {
        symbolGroups.set(key, [])
      }
      symbolGroups.get(key).push(alt)
    }

    const primaryAlerts = []
    const seenIds = new Set()
    for (const group of symbolGroups.values()) {
      if (group.length === 1) {
        const item = group[0]
        const id = item.alert_id || item.id
        if (id && !seenIds.has(id)) {
          seenIds.add(id)
          primaryAlerts.push({ alert: item, history: [] })
        }
      } else {
        // Prioritize active alert as primary; if none active, use the most recent alert
        const activeItem = group.find(isAlertActive)
        const primary = activeItem || group[0]
        const primaryId = primary.alert_id || primary.id
        if (primaryId && !seenIds.has(primaryId)) {
          seenIds.add(primaryId)
          const history = group.filter((a) => (a.alert_id || a.id) !== primaryId)
          primaryAlerts.push({ alert: primary, history })
        }
      }
    }
    return primaryAlerts
  }, [filteredAutoAlerts])

  // Segregate into 6 canonical market segments using classifyAlertSegment across active alerts
  const { fnoIndexCount, fnoStockCount, equityCount, commodityCount, currencyCount, cryptoCount, totalSegmentCount } = useMemo(() => {
    let fi = 0, fs = 0, e = 0, c = 0, cu = 0, cr = 0
    for (const a of autoAlerts) {
      if (autoViewMode === 'ACTIVE' && !isAlertActive(a)) continue
      if (autoViewMode === 'ARCHIVED' && isAlertActive(a)) continue
      const seg = classifyAlertSegment(a)
      if (seg === 'FNO_INDEX') fi++
      else if (seg === 'FNO_STOCK') fs++
      else if (seg === 'COMMODITY') c++
      else if (seg === 'CURRENCY') cu++
      else if (seg === 'CRYPTO') cr++
      else e++
    }
    const total = fi + fs + e + c + cu + cr
    return { fnoIndexCount: fi, fnoStockCount: fs, equityCount: e, commodityCount: c, currencyCount: cu, cryptoCount: cr, totalSegmentCount: total }
  }, [autoAlerts, autoViewMode])

  const { groupedFnoIndexAlerts, groupedFnoStockAlerts, groupedEquityAlerts, groupedCommodityAlerts, groupedCurrencyAlerts, groupedCryptoAlerts } = useMemo(() => {
    const fnoIdx = []
    const fnoStk = []
    const equity = []
    const commodity = []
    const currency = []
    const crypto = []
    for (const item of groupedAutoAlerts) {
      const seg = classifyAlertSegment(item.alert)
      if (seg === 'FNO_INDEX') fnoIdx.push(item)
      else if (seg === 'FNO_STOCK') fnoStk.push(item)
      else if (seg === 'COMMODITY') commodity.push(item)
      else if (seg === 'CURRENCY') currency.push(item)
      else if (seg === 'CRYPTO') crypto.push(item)
      else equity.push(item)
    }
    return {
      groupedFnoIndexAlerts: fnoIdx,
      groupedFnoStockAlerts: fnoStk,
      groupedEquityAlerts: equity,
      groupedCommodityAlerts: commodity,
      groupedCurrencyAlerts: currency,
      groupedCryptoAlerts: crypto,
    }
  }, [groupedAutoAlerts])

  const allVisibleGrouped = useMemo(() => {
    return [
      ...groupedFnoIndexAlerts,
      ...groupedFnoStockAlerts,
      ...groupedEquityAlerts,
      ...groupedCommodityAlerts,
      ...groupedCurrencyAlerts,
      ...groupedCryptoAlerts,
    ]
  }, [groupedFnoIndexAlerts, groupedFnoStockAlerts, groupedEquityAlerts, groupedCommodityAlerts, groupedCurrencyAlerts, groupedCryptoAlerts])

  const activeSelectedItem = useMemo(() => {
    if (!allVisibleGrouped.length) return null
    if (selectedAlertId) {
      const found = allVisibleGrouped.find(
        (item) => (item.alert.alert_id || item.alert.id || item.alert.symbol) === selectedAlertId
      )
      if (found) return found
    }
    return allVisibleGrouped[0]
  }, [allVisibleGrouped, selectedAlertId])

  const activeSelectedAlert = activeSelectedItem?.alert || null
  const activeSelectedHistory = activeSelectedItem?.history || []

  // ── Keyboard-First Rapid Scanning (J / K / T / A / Space) ────────────────
  useEffect(() => {
    const handleKeyDown = (e) => {
      const tag = document.activeElement?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return

      if (e.key === 'j' || e.key === 'ArrowDown') {
        if (!allVisibleGrouped.length) return
        e.preventDefault()
        const currentIdx = allVisibleGrouped.findIndex(
          (item) => (item.alert.alert_id || item.alert.id || item.alert.symbol) === (activeSelectedAlert?.alert_id || activeSelectedAlert?.id || activeSelectedAlert?.symbol)
        )
        const nextIdx = currentIdx < allVisibleGrouped.length - 1 ? currentIdx + 1 : 0
        const nextAlt = allVisibleGrouped[nextIdx]?.alert
        if (nextAlt) setSelectedAlertId(nextAlt.alert_id || nextAlt.id || nextAlt.symbol)
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        if (!allVisibleGrouped.length) return
        e.preventDefault()
        const currentIdx = allVisibleGrouped.findIndex(
          (item) => (item.alert.alert_id || item.alert.id || item.alert.symbol) === (activeSelectedAlert?.alert_id || activeSelectedAlert?.id || activeSelectedAlert?.symbol)
        )
        const prevIdx = currentIdx > 0 ? currentIdx - 1 : allVisibleGrouped.length - 1
        const prevAlt = allVisibleGrouped[prevIdx]?.alert
        if (prevAlt) setSelectedAlertId(prevAlt.alert_id || prevAlt.id || prevAlt.symbol)
      } else if (e.key === 't' || e.key === 'T') {
        if (activeSelectedAlert && !activeSelectedAlert.is_invalidated) {
          e.preventDefault()
          handleOpenTicket(activeSelectedAlert)
        }
      } else if (e.key === 'a' || e.key === 'A') {
        if (activeSelectedAlert?.symbol) {
          e.preventDefault()
          handleAnalyze(activeSelectedAlert.symbol)
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [allVisibleGrouped, activeSelectedAlert, handleOpenTicket, handleAnalyze])

  const renderAlertList = (items) => {
    if (!items || items.length === 0) return null
    return (
      <div className={densityMode === 'compact' ? 'space-y-1.5' : densityMode === 'split' ? 'space-y-2' : 'space-y-3'}>
        {items.map(({ alert: alt, history }) => {
          const alertKey = alt.alert_id || alt.id || alt.symbol
          const isRowExpanded = expandedRows.has(alertKey)
          const isSelected = (activeSelectedAlert?.alert_id || activeSelectedAlert?.id || activeSelectedAlert?.symbol) === alertKey

          if (densityMode === 'split') {
            return (
              <AlertTriageCard
                key={alertKey}
                alert={alt}
                isSelected={isSelected}
                onSelect={() => setSelectedAlertId(alertKey)}
                onTrade={handleOpenTicket}
                onAnalyze={handleAnalyze}
                onSendTelegram={handleOpenTelegramModal}
                onDismiss={handleDismissAlert}
              />
            )
          }

          if (densityMode === 'compact') {
            return (
              <div key={alertKey}>
                <AlertCompactRow
                  alert={alt}
                  onSendTelegram={handleOpenTelegramModal}
                  onTrade={handleOpenTicket}
                  onExpand={() => toggleExpandRow(alertKey)}
                  onDismiss={handleDismissAlert}
                  isExpanded={isRowExpanded}
                />
                {isRowExpanded && (
                  <div className="mt-1.5 ml-3 border-l-2 border-gold/30 pl-3">
                    <AutoAlertCard
                      alert={alt}
                      onAnalyze={handleAnalyze}
                      onInspectOptions={handleInspectOptions}
                      onOpenTicket={handleOpenTicket}
                      onArchiveToggle={handleArchiveToggle}
                      onClearLockout={handleClearLockout}
                      onDismiss={handleDismissAlert}
                      archiving={archiving}
                      historyAttempts={history}
                      densityMode="expanded"
                    />
                  </div>
                )}
              </div>
            )
          }

          // Expanded mode
          return (
            <div key={alertKey}>
              <AutoAlertCard
                alert={alt}
                onAnalyze={handleAnalyze}
                onInspectOptions={handleInspectOptions}
                onOpenTicket={handleOpenTicket}
                onArchiveToggle={handleArchiveToggle}
                onClearLockout={handleClearLockout}
                onDismiss={handleDismissAlert}
                archiving={archiving}
                historyAttempts={history}
                densityMode={densityMode}
              />
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <>
    <div
      ref={scrollContainerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto p-2 sm:p-2.5 space-y-2 font-ui"
      style={{ background: 'var(--color-surface)', overflowAnchor: 'auto' }}
    >
      {/* Header Bar */}
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-black tracking-wide flex items-center gap-2">
            🔔 Institutional Alert Center
          </h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            Real-time early warnings · NSE / NFO / MCX / CDS · Live vs Test · Proactive Invalidation
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-elevated border border-border">
          <button
            onClick={() => setActiveTab('auto')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              activeTab === 'auto' ? 'bg-gold text-panel font-black shadow-sm' : 'text-muted hover:text-text'
            }`}
          >
            ⚡ Live Auto-Alerts ({autoAlerts.length})
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              activeTab === 'manual' ? 'bg-gold text-panel font-black shadow-sm' : 'text-muted hover:text-text'
            }`}
          >
            🔔 Manual ({alerts.length})
          </button>
          <button
            onClick={() => setActiveTab('movers')}
            className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
              activeTab === 'movers' ? 'bg-amber-400 text-panel font-black shadow-sm' : 'text-muted hover:text-text'
            }`}
          >
            🔬 Movers Autopsy
          </button>
        </div>
      </header>

      {/* Invalidation Alert Banner */}
      {invalidatedCount > 0 && activeTab === 'auto' && (
        <div className="p-3 rounded-2xl bg-rose-500/10 border border-rose-500/35 text-rose-800 dark:text-rose-200 flex items-center justify-between gap-3 animate-slide-up-fade">
          <div className="flex items-center gap-2.5 text-xs min-w-0 flex-1">
            <span className="text-xl flex-shrink-0">🛑</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold">
                  ⚠️ {invalidatedCount} Trade {invalidatedCount === 1 ? 'Setup' : 'Setups'} Invalidated:
                </span>
                <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-500/30">
                  SL breached / thesis invalidated
                </span>
              </div>
              <p className="mt-0.5 text-rose-700 dark:text-rose-300/80 truncate">
                {uniqueInvalidatedList.slice(0, 4).join(', ')}
                {uniqueInvalidatedList.length > 4 ? ` +${uniqueInvalidatedList.length - 4} more` : ''} no longer valid due to stop-loss breach or structural failure.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => {
                setSelectedFilter('INVALIDATED')
                setSelectedStage('ALL')
              }}
              className="btn btn-sm btn-ghost text-rose-700 dark:text-rose-300 hover:bg-rose-500/20 text-xs flex-shrink-0 border border-rose-500/30 font-bold"
              title="Filter view to inspect invalidated setups"
            >
              View Invalidated ({invalidatedCount}) →
            </button>
            <button
              onClick={handleArchiveAllInvalidated}
              disabled={archivingInvalidated}
              className="btn btn-sm bg-rose-500/20 hover:bg-rose-500/30 text-rose-800 dark:text-rose-200 border border-rose-500/40 text-xs flex-shrink-0 font-bold flex items-center gap-1 cursor-pointer"
              title="Move all invalidated setups to Archived & History to clean the active radar"
            >
              <span>📦</span>
              <span>{archivingInvalidated ? 'Archiving…' : `Archive All (${invalidatedCount})`}</span>
            </button>
            <button
              onClick={handleDismissInvalidationBanner}
              className="p-1 rounded-lg hover:bg-rose-500/20 text-rose-500 dark:text-rose-400 hover:text-rose-700 dark:hover:text-rose-200 transition-colors text-sm font-bold leading-none cursor-pointer"
              title="Dismiss banner for this session"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Broker L2 WebSocket Depth Streaming Notice */}
      {brokerStatusReady && !hasActiveBrokerSession && activeTab === 'auto' && (
        <div className="p-3 rounded-2xl bg-amber-500/10 border border-amber-500/35 text-amber-800 dark:text-amber-200 flex items-center justify-between gap-3 animate-slide-up-fade">
          <div className="flex items-center gap-2.5 text-xs">
            <span className="text-xl flex-shrink-0">⚠️</span>
            <div>
              <div className="font-bold flex items-center gap-2">
                <span>NO ACTIVE BROKER CONNECTION — Level-2 Order Book Streaming Offline</span>
                <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-amber-500/15 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 border border-amber-500/30 dark:border-amber-500/40">
                  SYNTHETIC L1 ACTIVE
                </span>
              </div>
              <p className="text-amber-800/80 dark:text-amber-300/80 text-[11px] mt-0.5">
                Real-time broker order book depth (OBI & Iceberg detection) requires an active authenticated broker session. Trade setups are currently using tick-level OHLCV and volume delta reconstruction.
              </p>
            </div>
          </div>
          <button
            onClick={() => setActiveView('settings')}
            className="btn btn-sm btn-ghost text-amber-800 dark:text-amber-300 hover:bg-amber-500/20 text-xs flex-shrink-0 border border-amber-500/30 font-bold"
          >
            Connect Broker →
          </button>
        </div>
      )}

      {/* ── TAB 1: Real-Time Auto-Alerts ────────────────────────────── */}
      {activeTab === 'auto' && (
        <div className="space-y-3">
          {/* Institutional Unified High-Density Control Center */}
          <div className="p-2.5 rounded-2xl bg-panel/95 border border-border/80 backdrop-blur-md space-y-2">

            {/* ROW 1: View Mode + 5-way Segment Rail + Scan Now + Tools */}
            <div className="flex items-center justify-between flex-wrap gap-2">
              {/* Left: View Mode pills */}
              <div className="flex items-center gap-0.5 p-0.5 rounded-xl bg-surface/90 border border-border/60">
                <button
                  onClick={() => setAutoViewMode('ACTIVE')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-black rounded-lg transition-all ${
                    autoViewMode === 'ACTIVE'
                      ? 'bg-emerald-500/15 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border border-emerald-400/50 dark:border-emerald-500/40 shadow-sm'
                      : 'text-muted hover:text-text'
                  }`}
                  title="Show only valid active trades (removes clutter)"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                  <span>Active Valid Trades</span>
                  <span className="text-[10px] px-1.5 py-px rounded-full font-mono bg-emerald-500/20 dark:bg-emerald-500/30 text-emerald-800 dark:text-emerald-200">
                    {activeCount}
                  </span>
                </button>

                <button
                  onClick={() => setAutoViewMode('ARCHIVED')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                    autoViewMode === 'ARCHIVED'
                      ? 'bg-amber-500/15 dark:bg-amber-500/20 text-amber-800 dark:text-amber-300 border border-amber-400/50 dark:border-amber-500/40 shadow-sm'
                      : 'text-muted hover:text-text'
                  }`}
                  title="View archived, completed, and invalidated trades"
                >
                  <span>📁 Archived & History</span>
                  <span className="text-[10px] px-1.5 py-px rounded-full font-mono bg-amber-500/20 dark:bg-amber-500/30 text-amber-800 dark:text-amber-200">
                    {archivedCount}
                  </span>
                </button>

                <button
                  onClick={() => setAutoViewMode('ALL')}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-all ${
                    autoViewMode === 'ALL'
                      ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 shadow-sm'
                      : 'text-muted hover:text-text'
                  }`}
                  title="Show all records"
                >
                  All ({autoAlerts.length})
                </button>
              </div>

              {/* Right: Scan Now + Clean >3d Old + Tools dropdown */}
              <div className="flex items-center gap-1.5">
                <button
                  onClick={handleScanNow}
                  disabled={scanning}
                  className="btn btn-sm btn-gold text-xs flex items-center gap-1 font-bold shadow-sm py-1 px-3"
                  title="Scan live market feeds now"
                >
                  {scanning ? '⚡ Scanning…' : '⚡ Scan Now'}
                </button>

                <button
                  onClick={() => handleCleanupOld(3)}
                  disabled={cleaning}
                  className="btn btn-sm btn-ghost text-xs text-muted hover:text-amber-300 border border-border flex items-center gap-1 py-1 px-2.5"
                  title="Clean up expired derivative contracts and archived records older than 3 days. Active valid trades are never deleted."
                >
                  <span>{cleaning ? '🧹 Cleaning…' : '🧹 Clean >3d Old'}</span>
                </button>

                {/* Unified ⚙️ Tools dropdown (maintenance + simulation + clear) */}
                <div className="relative" ref={toolsMenuRef}>
                  <button
                    onClick={() => setShowTools((v) => !v)}
                    className={`btn btn-sm btn-ghost text-xs border flex items-center gap-1 py-1 px-2.5 transition-all ${
                      showTools ? 'text-gold border-gold/50 bg-gold/10' : 'text-muted border-border hover:text-text'
                    }`}
                    title="Maintenance, simulation & dev tools"
                  >
                    <span>⚙️ Tools</span>
                    <span className="text-[10px]">{showTools ? '▲' : '▼'}</span>
                  </button>
                  {showTools && (
                    <div
                      className="absolute right-0 top-full mt-1.5 w-72 p-2 rounded-xl bg-panel border border-border shadow-2xl z-50 space-y-0.5 text-xs animate-slide-up-fade"
                      style={{ backdropFilter: 'blur(16px)', background: 'var(--color-panel)' }}
                    >
                      {/* Maintenance section */}
                      <div className="text-[10px] font-bold text-muted uppercase px-2 py-1 tracking-wider">🧹 Maintenance</div>
                      {expiredCount > 0 && (
                        <button
                          onClick={() => { handlePurgeExpired(); setShowTools(false) }}
                          disabled={purging}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-rose-300 flex items-center gap-2 cursor-pointer transition-colors"
                        >
                          <span>🧹</span>
                          <div>
                            <span className="font-bold block">Purge Expired Contracts ({expiredCount})</span>
                            <span className="text-[10px] text-muted">Remove derivative alerts past expiry date</span>
                          </div>
                        </button>
                      )}
                      <button
                        onClick={() => { handleCleanupOld(3); setShowTools(false) }}
                        disabled={cleaning}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-amber-300 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>🧹</span>
                        <div>
                          <span className="font-bold block">{cleaning ? 'Cleaning…' : 'Clean Archived >3 Days Old'}</span>
                          <span className="text-[10px] text-muted">Active valid trades are never deleted</span>
                        </div>
                      </button>
                      {invalidatedCount > 0 && (
                        <button
                          onClick={() => { handleArchiveAllInvalidated(); setShowTools(false) }}
                          disabled={archivingInvalidated}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-rose-400 flex items-center gap-2 cursor-pointer transition-colors"
                        >
                          <span>📦</span>
                          <div>
                            <span className="font-bold block">Archive All Invalidated ({invalidatedCount})</span>
                            <span className="text-[10px] text-muted">Move invalidated setups to history tab</span>
                          </div>
                        </button>
                      )}
                      {autoAlerts.length > 0 && (
                        <button
                          onClick={() => { handleClearAuto(); setShowTools(false) }}
                          className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-rose-400 flex items-center gap-2 cursor-pointer transition-colors"
                        >
                          <span>🗑️</span>
                          <div>
                            <span className="font-bold block">Clear Entire Alert Feed</span>
                            <span className="text-[10px] text-muted">Emergency reset — removes all alerts from view</span>
                          </div>
                        </button>
                      )}
                      {/* Purge Test / Simulation alerts button */}
                      <button
                        onClick={() => { handleClearTestAlerts(); setShowTools(false) }}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-purple-400 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>🧪</span>
                        <div>
                          <span className="font-bold block">Clear Test / Simulated Alerts</span>
                          <span className="text-[10px] text-muted">Purge simulated cards without affecting live feeds</span>
                        </div>
                      </button>

                      {/* Simulation section */}
                      <div className="border-t border-border/40 mt-1 pt-1">
                        <div className="text-[10px] font-bold text-muted uppercase px-2 py-1 tracking-wider">🧪 Simulation Tools</div>
                      </div>
                      <button
                        onClick={() => { handleTriggerTestTarget('T1', true); setShowTools(false) }}
                        disabled={testing}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-cyan-300 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>🎯</span>
                        <div>
                          <span className="font-bold block">Simulate Target 1 Hit</span>
                          <span className="text-[10px] text-muted">Triggers partial lock & breakeven trail</span>
                        </div>
                      </button>
                      <button
                        onClick={() => { handleTriggerTestTarget('FINAL', false); setShowTools(false) }}
                        disabled={testing}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-amber-300 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>🏁</span>
                        <div>
                          <span className="font-bold block">Simulate Final Target Hit</span>
                          <span className="text-[10px] text-muted">Triggers full profit exit guidance</span>
                        </div>
                      </button>
                      <button
                        onClick={() => { handleTriggerTestTarget('TRAIL', true); setShowTools(false) }}
                        disabled={testing}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-blue-300 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>📈</span>
                        <div>
                          <span className="font-bold block">Simulate Trailing Stop Ratchet</span>
                          <span className="text-[10px] text-muted">Simulates ATR trailing stop update</span>
                        </div>
                      </button>
                      <button
                        onClick={() => { handleTriggerTest(true); setShowTools(false) }}
                        disabled={testing}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-rose-300 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>⚠️</span>
                        <div>
                          <span className="font-bold block">Simulate Invalidation</span>
                          <span className="text-[10px] text-muted">Simulates stop-loss breach & post-mortem</span>
                        </div>
                      </button>
                      <button
                        onClick={() => { handleTriggerTest(false); setShowTools(false) }}
                        disabled={testing}
                        className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-elevated text-purple-300 flex items-center gap-2 cursor-pointer transition-colors"
                      >
                        <span>🧪</span>
                        <div>
                          <span className="font-bold block">Send Test Alert (Gamma Blast)</span>
                          <span className="text-[10px] text-muted">Verifies alert pipeline end-to-end</span>
                        </div>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* ROW 2: Multi-Select Segment Rail & Delivery Routing */}
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-1 p-0.5 rounded-xl bg-surface/90 border border-border/60 w-fit flex-wrap">
                {/* All Markets master button */}
                <button
                  onClick={() => handleToggleSegment('ALL')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                    isAllSegmentsSelected
                      ? 'bg-gold text-surface shadow-sm font-black'
                      : 'text-muted hover:text-text hover:bg-elevated'
                  }`}
                  title={`Include all market segments (${totalSegmentCount} total setups across ${groupedAutoAlerts.length} symbol cards)`}
                >
                  <span>🌐 All Segments</span>
                  <span className={`text-[10px] font-mono px-1.5 py-px rounded-full ${
                    isAllSegmentsSelected ? 'bg-black/20 font-bold' : 'bg-elevated'
                  }`}>{totalSegmentCount}</span>
                  {groupedAutoAlerts.length !== totalSegmentCount && (
                    <span className={`text-[9px] font-mono opacity-70 hidden sm:inline ${
                      isAllSegmentsSelected ? 'text-black/80 dark:text-black/70 font-semibold' : 'text-muted'
                    }`} title={`${totalSegmentCount} total setups deduplicated into ${groupedAutoAlerts.length} symbol cards`}>
                      ({groupedAutoAlerts.length} cards)
                    </span>
                  )}
                </button>

                {/* Individual Segment multi-select pills */}
                {[
                  { id: 'FNO_INDEX', label: '⚡ F&O Indices',      count: fnoIndexCount,  activeColor: 'bg-indigo-500/15 dark:bg-indigo-500/25 text-indigo-800 dark:text-indigo-200 border-indigo-400/60 dark:border-indigo-500/50' },
                  { id: 'FNO_STOCK', label: '🎯 F&O Stocks',       count: fnoStockCount,  activeColor: 'bg-purple-500/15 dark:bg-purple-500/25 text-purple-800 dark:text-purple-200 border-purple-400/60 dark:border-purple-500/50' },
                  { id: 'EQUITY',    label: '🏢 Cash Equity',      count: equityCount,    activeColor: 'bg-emerald-500/15 dark:bg-emerald-500/25 text-emerald-800 dark:text-emerald-200 border-emerald-400/60 dark:border-emerald-500/50' },
                  { id: 'COMMODITY', label: '🌙 Commodity (MCX)',  count: commodityCount, activeColor: 'bg-amber-500/15 dark:bg-amber-500/25 text-amber-800 dark:text-amber-200 border-amber-400/60 dark:border-amber-500/50' },
                  { id: 'CURRENCY',  label: '💱 Currency (CDS)',   count: currencyCount,  activeColor: 'bg-cyan-500/15 dark:bg-cyan-500/25 text-cyan-800 dark:text-cyan-200 border-cyan-400/60 dark:border-cyan-500/50' },
                  { id: 'CRYPTO',    label: '🪙 Crypto 24x7',      count: cryptoCount,    activeColor: 'bg-amber-500/15 dark:bg-amber-500/25 text-amber-800 dark:text-amber-200 border-amber-400/60 dark:border-amber-500/50' },
                ].map((seg) => {
                  const isSelected = selectedSegments.has(seg.id)
                  return (
                    <button
                      key={seg.id}
                      onClick={() => handleToggleSegment(seg.id)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-all ${
                        isSelected
                          ? `${seg.activeColor} shadow-sm font-bold`
                          : 'border-transparent text-muted hover:text-text hover:bg-elevated opacity-60'
                      }`}
                      title={`Toggle ${seg.label} (${isSelected ? 'Included — click to remove' : 'Excluded — click to add'})`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full transition-all ${
                        isSelected ? 'bg-current shadow-[0_0_6px_currentColor]' : 'bg-muted/40'
                      }`} />
                      <span>{seg.label}</span>
                      <span className={`text-[10px] font-mono px-1.5 py-px rounded-full ${
                        isSelected ? 'bg-black/10 dark:bg-black/20 font-bold' : 'bg-elevated'
                      }`}>{seg.count}</span>
                    </button>
                  )
                })}
              </div>

              {/* Quick Alert Routing & Preferences button */}
              <button
                onClick={() => setShowRoutingModal(true)}
                className="btn btn-sm btn-ghost text-xs border border-border/80 hover:border-gold/60 text-muted hover:text-gold flex items-center gap-1.5 py-1.5 px-3 rounded-xl transition-all shadow-sm"
                title="Configure which markets send Telegram pushes, appear in UI, and sound chimes"
              >
                <span>⚙️ Alert Routing Matrix</span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface border border-border text-text">
                  {isAllSegmentsSelected ? 'ALL 6' : `${selectedSegments.size} ACTIVE`}
                </span>
              </button>
            </div>

            {/* ROW 3: Search + Category chips (scrollable) + Dropdowns */}
            <div className="flex items-center justify-between flex-wrap gap-2 pt-1.5 border-t border-border/40 text-[11px]">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                {/* Symbol / Contract Search Input */}
                <div className="relative w-44 flex-shrink-0">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="🔍 Symbol, strike…"
                    className="w-full text-xs pl-2.5 pr-6 py-1 rounded-lg bg-surface border border-border text-text placeholder:text-muted focus:outline-none focus:border-gold transition-colors font-sans"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-text text-xs cursor-pointer"
                      title="Clear search"
                    >
                      ✕
                    </button>
                  )}
                </div>

                {/* Category / Setup Dropdown */}
                <select
                  value={selectedFilter}
                  onChange={(e) => setSelectedFilter(e.target.value)}
                  className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer flex-shrink-0 ${
                    selectedFilter !== 'ALL'
                      ? 'border-gold text-gold font-bold bg-gold/10'
                      : 'border-border hover:border-gold/50'
                  }`}
                  title="Filter by setup / strategy category"
                >
                  <option value="ALL">All Categories / Setups</option>
                  <option value="TARGET_HIT">🎯 Targets Hit</option>
                  <option value="HIGH_CONVICTION">⭐ Conviction 85%+</option>
                  <option value="MULTI_FLOW">🌊 Multi-Strike Flow</option>
                  <option value="GAMMA_BLAST">⚡ Gamma Blast</option>
                  <option value="SQUEEZE_BREAKOUT">🚀 Squeeze Breakout</option>
                  <option value="CFAI_FLOAT_EXHAUSTION">🐋 Float Exhaustion (CFAI)</option>
                  <option value="ORDER_BOOK_EXPANSION">🏗️ Order-Book Titan</option>
                  <option value="BLOCK_DEAL_ABSORPTION">🛡️ Block Deal Absorption</option>
                  <option value="CAPEX_INFLECTION">🏭 Capex & CWIP Inflection</option>
                  <option value="RRG_ORDERBOOK_CONVERGENCE">🔄 RRG × Order-Book Convergence</option>
                  <option value="PROMOTER_SKIN_IN_THE_GAME">💎 Promoter Skin-in-the-Game</option>
                  <option value="SMC_SWEEP">🌊 SMC Sweep</option>
                  <option value="PRECURSOR_RADAR">⚡ Precursor Radar</option>
                  <option value="ASYMMETRIC_OPPORTUNITY">🎯 Asymmetric R:R</option>
                  <option value="CIRCUIT_WARNING">🔒 Circuit Warning</option>
                  <option value="CRYPTO_SQUEEZE">🪙 Crypto Squeeze (24x7)</option>
                  <option value="CRYPTO_MOMENTUM">🪙 Crypto Momentum</option>
                  <option value="CRYPTO_VOLATILITY">🪙 Crypto Volatility</option>
                  <option value="INVALIDATED">❌ Invalidated ({invalidatedCount})</option>
                </select>

                {/* Horizon Filter Dropdown */}
                <select
                  value={selectedHorizon}
                  onChange={(e) => setSelectedHorizon(e.target.value)}
                  className={`text-xs py-1 px-2.5 rounded-lg bg-surface border text-text focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer flex-shrink-0 ${
                    selectedHorizon !== 'ALL'
                      ? 'border-sky-400 text-sky-300 font-bold bg-sky-500/10'
                      : 'border-border hover:border-gold/50'
                  }`}
                  title="Filter by trade time horizon"
                >
                  <option value="ALL">All Horizons</option>
                  <option value="INTRADAY">⏱️ Intraday (15m–60m)</option>
                  <option value="SWING_SHORT">⚡ 2–5D Swing</option>
                  <option value="SWING_MID">📈 1–4W Swing</option>
                  <option value="POSITIONAL">🏛️ 1–6M Positional</option>
                </select>
              </div>

              {/* Right: compact inline dropdowns + density + sort + reset */}
              <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
                {/* Direction Filter */}
                <select
                  value={selectedDirection}
                  onChange={(e) => setSelectedDirection(e.target.value)}
                  className="text-xs py-1 px-2.5 rounded-lg bg-surface border border-border text-text hover:border-gold/50 focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer w-auto"
                  title="Filter by direction"
                >
                  <option value="ALL">All Directions</option>
                  <option value="BULLISH">📈 Bullish</option>
                  <option value="BEARISH">📉 Bearish</option>
                </select>

                {/* Stage Filter */}
                <select
                  value={selectedStage}
                  onChange={(e) => setSelectedStage(e.target.value)}
                  className="text-xs py-1 px-2.5 rounded-lg bg-surface border border-border text-text hover:border-gold/50 focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer w-auto"
                  title="Filter by trade lifecycle stage"
                >
                  <option value="ALL">All Stages</option>
                  <option value="EARLY_WARNING">⏳ Early Warning</option>
                  <option value="IGNITED">🔥 Ignited</option>
                  <option value="T1_ACHIEVED">🎯 Target 1 Hit</option>
                  <option value="TARGET_ACHIEVED">🏁 Final Target</option>
                  <option value="INVALIDATED">❌ Invalidated</option>
                </select>

                {/* Environment Filter */}
                <select
                  value={selectedEnv}
                  onChange={(e) => setSelectedEnv(e.target.value)}
                  className="text-xs py-1 px-2.5 rounded-lg bg-surface border border-border text-text hover:border-gold/50 focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer w-auto"
                  title="Filter by environment"
                >
                  <option value="ALL">All Envs</option>
                  <option value="LIVE">🟢 Live</option>
                  <option value="TEST">🧪 Test</option>
                </select>

                {/* Sort Order */}
                <select
                  value={selectedSort}
                  onChange={(e) => setSelectedSort(e.target.value)}
                  className="text-xs py-1 px-2.5 rounded-lg bg-surface border border-border text-text hover:border-gold/50 focus:outline-none focus:border-gold transition-colors font-sans cursor-pointer w-auto"
                  title="Sort alerts (Multi-sort enabled)"
                >
                  <option value="NEWEST">⏱ Newest First</option>
                  <option value="CONFIDENCE">⭐ Conviction ↓ + Newest</option>
                  <option value="STAGE">🔥 Stage Priority + Newest</option>
                  <option value="RR_RATIO">📊 R:R Ratio ↓ + Newest</option>
                </select>

                {/* Density Mode */}
                <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-surface border border-border">
                  <button
                    onClick={() => {
                      setDensityMode('compact')
                      try { localStorage.setItem('chanakya_alerts_density_mode', 'compact') } catch (_) {}
                    }}
                    className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
                      densityMode === 'compact' ? 'bg-gold/20 text-gold shadow-sm' : 'text-muted hover:text-text'
                    }`}
                    title="Compact card view"
                  >▤ Compact</button>
                  <button
                    onClick={() => {
                      setDensityMode('split')
                      try { localStorage.setItem('chanakya_alerts_density_mode', 'split') } catch (_) {}
                    }}
                    className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
                      densityMode === 'split' ? 'bg-gold/20 text-gold shadow-sm' : 'text-muted hover:text-text'
                    }`}
                    title="Master-Detail Split View (Triage rail on left, Institutional Trade Inspector on right)"
                  >◫ Split</button>
                  <button
                    onClick={() => {
                      setDensityMode('expanded')
                      try { localStorage.setItem('chanakya_alerts_density_mode', 'expanded') } catch (_) {}
                    }}
                    className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
                      densityMode === 'expanded' ? 'bg-gold/20 text-gold shadow-sm' : 'text-muted hover:text-text'
                    }`}
                    title="Expanded card view — all plan details visible by default"
                  >☰ Expanded</button>
                </div>

                {/* Audio Chime Mute/Unmute Toggle */}
                <button
                  onClick={toggleChime}
                  className={`px-2 py-0.5 rounded-lg text-xs font-bold border transition-all flex items-center gap-1 cursor-pointer ${
                    chimeEnabled
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25'
                      : 'bg-surface text-muted border-border hover:text-text'
                  }`}
                  title={chimeEnabled ? 'Audio Chime ON: Harmonic ping on ignited alerts (Click to mute)' : 'Audio Chime MUTED (Click to unmute)'}
                >
                  {chimeEnabled ? '🔔 Chime' : '🔕 Muted'}
                </button>

                {/* Reset Filters Button */}
                {(searchQuery || selectedFilter !== 'ALL' || selectedStage !== 'ALL' || selectedEnv !== 'ALL' || selectedDirection !== 'ALL' || selectedSegment !== 'ALL' || selectedSort !== 'NEWEST') && (
                  <button
                    onClick={handleResetFilters}
                    className="btn btn-sm btn-ghost text-xs text-gold hover:text-gold-light border border-gold/30 hover:bg-gold/10 flex items-center gap-1 font-bold px-2 py-0.5"
                    title="Reset all filters to defaults"
                  >
                    ✕ Reset
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Cleanup Status Toast Notice */}
          {cleanupNotice && (
            <div className="p-2.5 rounded-xl bg-surface/90 border border-amber-500/40 text-xs text-amber-800 dark:text-amber-200 flex items-center justify-between gap-2 animate-slide-up-fade">
              <span className="font-mono">{cleanupNotice}</span>
              <button onClick={() => setCleanupNotice(null)} className="text-muted hover:text-text text-xs font-bold">
                ✕
              </button>
            </div>
          )}

          {/* Alert Cards Feed */}
          {autoLoading && autoAlerts.length === 0 ? (
            <UnavailableState title="Checking market feeds" reason="Scanning for real-time Gamma Blasts, Squeezes, Commodity momentum, and Invalidations." size="md" />
          ) : (selectedSegment === 'ALL' && filteredAutoAlerts.length === 0) ? (
            <div className="p-8 text-center rounded-2xl bg-panel border border-border space-y-2">
              <div className="text-3xl">📡</div>
              <div className="text-sm font-bold text-text">No alerts match the current filters</div>
              <p className="text-xs text-muted max-w-md mx-auto">
                The engine monitors NSE F&O, Cash Equity, MCX Commodities (Crude, Gold, Silver), and Currency derivatives.
                Try adjusting the segment rail or clearing the category filter.
              </p>
              <div className="flex items-center justify-center gap-2 pt-2 flex-wrap">
                <button onClick={handleScanNow} disabled={scanning} className="btn btn-sm btn-gold">
                  ⚡ Scan Now
                </button>
                {(selectedSegment !== 'ALL' || selectedFilter !== 'ALL' || selectedStage !== 'ALL' || searchQuery) && (
                  <button onClick={handleResetFilters} className="btn btn-sm btn-ghost text-gold border border-gold/30">
                    ✕ Clear Filters
                  </button>
                )}
              </div>
            </div>
          ) : (
            /* Section renderer — Tri-modal layout: Split-Pane Master-Detail vs Full-Width Grid/List */
            densityMode === 'split' ? (
              <div className="flex flex-col lg:flex-row gap-4 items-start">
                {/* Master Triage Rail: Left column (42% width) */}
                <div className="w-full lg:w-[42%] flex-shrink-0 space-y-6">
                  {/* 1. Index Derivatives (NIFTY, BANKNIFTY, SENSEX) */}
                  {(selectedSegment === 'ALL' ? groupedFnoIndexAlerts.length > 0 : (selectedSegment === 'FNO_INDEX' || selectedSegment === 'FNO')) && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-indigo-500/40">
                        <div className="flex items-center gap-2">
                          <span className="text-base">⚡</span>
                          <h2 className="text-xs font-black uppercase tracking-wider text-indigo-300">
                            Institutional Index Derivatives (NIFTY, BANKNIFTY, SENSEX) ({groupedFnoIndexAlerts.length})
                          </h2>
                        </div>
                        <span className="text-[10px] font-mono text-muted">
                          {selectedSegment === 'FNO_INDEX' ? 'Filtered to Index Derivatives Only' : 'Gamma Blasts · Index Options · 0DTE Scalps · Futures'}
                        </span>
                      </div>
                      {groupedFnoIndexAlerts.length === 0 ? (
                        <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                          No active Index F&O alerts matching current filters
                        </div>
                      ) : (
                        renderAlertList(groupedFnoIndexAlerts)
                      )}
                    </div>
                  )}

                  {/* 2. Stock Derivatives (Single-Stock Options & Futures) */}
                  {(selectedSegment === 'ALL' ? groupedFnoStockAlerts.length > 0 : (selectedSegment === 'FNO_STOCK' || selectedSegment === 'FNO')) && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-purple-500/40">
                        <div className="flex items-center gap-2">
                          <span className="text-base">🎯</span>
                          <h2 className="text-xs font-black uppercase tracking-wider text-purple-300">
                            Institutional Stock Derivatives (Single-Stock Options & Futures) ({groupedFnoStockAlerts.length})
                          </h2>
                        </div>
                        <span className="text-[10px] font-mono text-muted">
                          {selectedSegment === 'FNO_STOCK' ? 'Filtered to Stock Derivatives Only' : 'High RVOL Momentum · Single-Stock Options · Stock Futures'}
                        </span>
                      </div>
                      {groupedFnoStockAlerts.length === 0 ? (
                        <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                          No active Stock F&O alerts matching current filters
                        </div>
                      ) : (
                        renderAlertList(groupedFnoStockAlerts)
                      )}
                    </div>
                  )}

                  {/* 3. Cash Equity Breakouts & Squeezes */}
                  {(selectedSegment === 'ALL' ? groupedEquityAlerts.length > 0 : selectedSegment === 'EQUITY') && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-emerald-500/40">
                        <div className="flex items-center gap-2">
                          <span className="text-base">🏢</span>
                          <h2 className="text-xs font-black uppercase tracking-wider text-emerald-400">
                            Institutional Cash Equity Breakouts & Squeezes ({groupedEquityAlerts.length})
                          </h2>
                        </div>
                        <span className="text-[10px] font-mono text-muted">
                          {selectedSegment === 'EQUITY' ? 'Filtered to Cash Equity Only' : 'VCP · Minervini · SMC · Delivery'}
                        </span>
                      </div>
                      {groupedEquityAlerts.length === 0 ? (
                        <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                          No active Cash Equity alerts matching current filters
                        </div>
                      ) : (
                        renderAlertList(groupedEquityAlerts)
                      )}
                    </div>
                  )}

                  {/* 4. Commodity (MCX) */}
                  {(selectedSegment === 'ALL' || selectedSegment === 'COMMODITY') && groupedCommodityAlerts.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-amber-500/40">
                        <div className="flex items-center gap-2">
                          <span className="text-base">🌙</span>
                          <h2 className="text-xs font-black uppercase tracking-wider text-amber-400">
                            Commodity (MCX) — Crude Oil · Gold · Silver · Metals ({groupedCommodityAlerts.length})
                          </h2>
                        </div>
                        <span className="text-[10px] font-mono text-muted">09:00–23:30 IST · Prompt Expiry · VWAP</span>
                      </div>
                      {renderAlertList(groupedCommodityAlerts)}
                    </div>
                  )}

                  {/* 5. Currency Derivatives (CDS) */}
                  {(selectedSegment === 'ALL' || selectedSegment === 'CURRENCY') && groupedCurrencyAlerts.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-cyan-500/40">
                        <div className="flex items-center gap-2">
                          <span className="text-base">💱</span>
                          <h2 className="text-xs font-black uppercase tracking-wider text-cyan-400">
                            Currency Derivatives (CDS) — USDINR · EURINR ({groupedCurrencyAlerts.length})
                          </h2>
                        </div>
                        <span className="text-[10px] font-mono text-muted">NSE CDS Segment · INR Pairs</span>
                      </div>
                      {renderAlertList(groupedCurrencyAlerts)}
                    </div>
                  )}

                  {/* 6. Crypto 24x7 (Binance & Deribit) */}
                  {(selectedSegment === 'ALL' || selectedSegment === 'CRYPTO') && groupedCryptoAlerts.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between pb-2 border-b border-amber-500/40">
                        <div className="flex items-center gap-2">
                          <span className="text-base">🪙</span>
                          <h2 className="text-xs font-black uppercase tracking-wider text-amber-400">
                            Crypto 24x7 — BTC · ETH · SOL · Derivatives ({groupedCryptoAlerts.length})
                          </h2>
                        </div>
                        <span className="text-[10px] font-mono text-muted">24/7/365 · Binance Futures · Deribit Surface</span>
                      </div>
                      {renderAlertList(groupedCryptoAlerts)}
                    </div>
                  )}

                  {/* Segment-specific empty state */}
                  {selectedSegment !== 'ALL' && filteredAutoAlerts.length === 0 && (
                    <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                      No {selectedSegment === 'COMMODITY' ? 'MCX Commodity' : selectedSegment === 'CURRENCY' ? 'Currency (CDS)' : selectedSegment === 'CRYPTO' ? 'Crypto 24x7' : selectedSegment === 'FNO' ? 'F&O' : 'Cash Equity'} alerts matching current filters
                    </div>
                  )}
                </div>

                {/* Institutional Trade Inspector: Right column (58% width, sticky) */}
                <div className="w-full lg:w-[58%] sticky top-2 min-w-0">
                  {activeSelectedAlert ? (
                    <InstitutionalTradeInspector
                      alert={activeSelectedAlert}
                      onAnalyze={handleAnalyze}
                      onInspectOptions={handleInspectOptions}
                      onOpenTicket={handleOpenTicket}
                      onArchiveToggle={handleArchiveToggle}
                      onClearLockout={handleClearLockout}
                      onSendTelegram={handleOpenTelegramModal}
                      onDismiss={handleDismissAlert}
                      archiving={archiving}
                      historyAttempts={activeSelectedHistory}
                    />
                  ) : (
                    <div className="p-8 text-center rounded-2xl bg-panel border border-border space-y-2">
                      <div className="text-2xl">🔍</div>
                      <div className="text-xs font-bold text-text">Select an alert from the rail to inspect</div>
                      <p className="text-[11px] text-muted">
                        Use <kbd className="px-1.5 py-0.5 rounded bg-surface border border-border text-[10px] font-mono">J</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-surface border border-border text-[10px] font-mono">K</kbd> to navigate, or click any card.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              /* Expanded & Compact modes (single-column full width) */
              <div className="space-y-6">
                {/* 1. Index Derivatives (NIFTY, BANKNIFTY, SENSEX) */}
                {(selectedSegment === 'ALL' ? groupedFnoIndexAlerts.length > 0 : (selectedSegment === 'FNO_INDEX' || selectedSegment === 'FNO')) && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-indigo-500/40">
                      <div className="flex items-center gap-2">
                        <span className="text-base">⚡</span>
                        <h2 className="text-xs font-black uppercase tracking-wider text-indigo-300">
                          Institutional Index Derivatives (NIFTY, BANKNIFTY, SENSEX) ({groupedFnoIndexAlerts.length})
                        </h2>
                      </div>
                      <span className="text-[10px] font-mono text-muted">
                        {selectedSegment === 'FNO_INDEX' ? 'Filtered to Index Derivatives Only' : 'Gamma Blasts · Index Options · 0DTE Scalps · Futures'}
                      </span>
                    </div>
                    {groupedFnoIndexAlerts.length === 0 ? (
                      <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                        No active Index F&O alerts matching current filters
                      </div>
                    ) : (
                      renderAlertList(groupedFnoIndexAlerts)
                    )}
                  </div>
                )}

                {/* 2. Stock Derivatives (Single-Stock Options & Futures) */}
                {(selectedSegment === 'ALL' ? groupedFnoStockAlerts.length > 0 : (selectedSegment === 'FNO_STOCK' || selectedSegment === 'FNO')) && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-purple-500/40">
                      <div className="flex items-center gap-2">
                        <span className="text-base">🎯</span>
                        <h2 className="text-xs font-black uppercase tracking-wider text-purple-300">
                          Institutional Stock Derivatives (Single-Stock Options & Futures) ({groupedFnoStockAlerts.length})
                        </h2>
                      </div>
                      <span className="text-[10px] font-mono text-muted">
                        {selectedSegment === 'FNO_STOCK' ? 'Filtered to Stock Derivatives Only' : 'High RVOL Momentum · Single-Stock Options · Stock Futures'}
                      </span>
                    </div>
                    {groupedFnoStockAlerts.length === 0 ? (
                      <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                        No active Stock F&O alerts matching current filters
                      </div>
                    ) : (
                      renderAlertList(groupedFnoStockAlerts)
                    )}
                  </div>
                )}

                {/* 3. Cash Equity Breakouts & Squeezes */}
                {(selectedSegment === 'ALL' ? groupedEquityAlerts.length > 0 : selectedSegment === 'EQUITY') && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-emerald-500/40">
                      <div className="flex items-center gap-2">
                        <span className="text-base">🏢</span>
                        <h2 className="text-xs font-black uppercase tracking-wider text-emerald-400">
                          Institutional Cash Equity Breakouts & Squeezes ({groupedEquityAlerts.length})
                        </h2>
                      </div>
                      <span className="text-[10px] font-mono text-muted">
                        {selectedSegment === 'EQUITY' ? 'Filtered to Cash Equity Only' : 'VCP · Minervini · SMC · Delivery'}
                      </span>
                    </div>
                    {groupedEquityAlerts.length === 0 ? (
                      <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                        No active Cash Equity alerts matching current filters
                      </div>
                    ) : (
                      renderAlertList(groupedEquityAlerts)
                    )}
                  </div>
                )}

                {/* 4. Commodity (MCX) */}
                {(selectedSegment === 'ALL' || selectedSegment === 'COMMODITY') && groupedCommodityAlerts.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-amber-500/40">
                      <div className="flex items-center gap-2">
                        <span className="text-base">🌙</span>
                        <h2 className="text-xs font-black uppercase tracking-wider text-amber-400">
                          Commodity (MCX) — Crude Oil · Gold · Silver · Metals ({groupedCommodityAlerts.length})
                        </h2>
                      </div>
                      <span className="text-[10px] font-mono text-muted">09:00–23:30 IST · Prompt Expiry · VWAP</span>
                    </div>
                    {renderAlertList(groupedCommodityAlerts)}
                  </div>
                )}

                {/* 5. Currency Derivatives (CDS) */}
                {(selectedSegment === 'ALL' || selectedSegment === 'CURRENCY') && groupedCurrencyAlerts.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-cyan-500/40">
                      <div className="flex items-center gap-2">
                        <span className="text-base">💱</span>
                        <h2 className="text-xs font-black uppercase tracking-wider text-cyan-400">
                          Currency Derivatives (CDS) — USDINR · EURINR ({groupedCurrencyAlerts.length})
                        </h2>
                      </div>
                      <span className="text-[10px] font-mono text-muted">NSE CDS Segment · INR Pairs</span>
                    </div>
                    {renderAlertList(groupedCurrencyAlerts)}
                  </div>
                )}

                {/* 6. Crypto 24x7 (Binance & Deribit) */}
                {(selectedSegment === 'ALL' || selectedSegment === 'CRYPTO') && groupedCryptoAlerts.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between pb-2 border-b border-amber-500/40">
                      <div className="flex items-center gap-2">
                        <span className="text-base">🪙</span>
                        <h2 className="text-xs font-black uppercase tracking-wider text-amber-400">
                          Crypto 24x7 — BTC · ETH · SOL · Derivatives ({groupedCryptoAlerts.length})
                        </h2>
                      </div>
                      <span className="text-[10px] font-mono text-muted">24/7/365 · Binance Futures · Deribit Surface</span>
                    </div>
                    {renderAlertList(groupedCryptoAlerts)}
                  </div>
                )}

                {/* Segment-specific empty state */}
                {selectedSegment !== 'ALL' && filteredAutoAlerts.length === 0 && (
                  <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                    No {selectedSegment === 'COMMODITY' ? 'MCX Commodity' : selectedSegment === 'CURRENCY' ? 'Currency (CDS)' : selectedSegment === 'CRYPTO' ? 'Crypto 24x7' : selectedSegment === 'FNO' ? 'F&O' : 'Cash Equity'} alerts matching current filters
                  </div>
                )}
              </div>
            )
          )}
        </div>
      )}

      {/* ── TAB 2: Manual Price Alerts ──────────────────────────────── */}
      {activeTab === 'manual' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted">
              {alerts.length} user-defined price alert{alerts.length === 1 ? '' : 's'} · monitored continuously
            </p>
            <button onClick={() => setShowCreate((v) => !v)} className="btn btn-sm btn-gold">
              + New Alert
            </button>
          </div>

          {showCreate && (
            <CreateAlertPanel onClose={() => setShowCreate(false)} onCreate={createAlert} creating={creating} />
          )}

          {loading ? (
            <UnavailableState title="Loading alerts" reason="Checking your active alerts." size="md" />
          ) : error ? (
            <UnavailableState title="Alerts unavailable" reason={error} onRetry={loadAlerts} size="md" />
          ) : alerts.length === 0 ? (
            <UnavailableState
              title="No active price alerts"
              reason="Create a price alert to monitor a level from your connected market-data feed."
              size="lg"
            />
          ) : (
            <div className="space-y-2">
              {alerts.map((alert) => (
                <ManualAlertCard
                  key={alert.id || alert.alert_id || alert.symbol}
                  alert={alert}
                  onRemove={removeAlert}
                  onAnalyze={handleAnalyze}
                  removing={removing === alert.id}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── TAB 3: Daily Movers Autopsy & Precursor Radar ───────────── */}
      {activeTab === 'movers' && (
        <MoversAutopsyPanel onOpenOrderTicket={onOpenOrderTicket} />
      )}
    </div>

    {/* ── Telegram Preflight Modal (portal-style, rendered outside scroll container) ── */}
    <TelegramPreflightModal
      alert={telegramAlert}
      onConfirm={handleConfirmTelegram}
      onCancel={handleCloseTelegramModal}
      sending={telegramSending}
      sentOk={telegramSentOk}
      sentError={telegramSentError}
      callRef={callRef}
    />

    {/* ── Alert Routing Modal ── */}
    <AlertRoutingModal
      isOpen={showRoutingModal}
      onClose={() => setShowRoutingModal(false)}
      onSaveSuccess={handleSaveRoutingSuccess}
    />
  </>
  )
}

// Wrap the default export in the LiveSpotsProvider so all cards have context access
const AlertsViewWithLiveSpots = function AlertsViewWithLiveSpots(props) {
  return (
    <LiveSpotsProvider>
      <AlertsViewInner {...props} />
    </LiveSpotsProvider>
  )
}
export default AlertsViewWithLiveSpots
