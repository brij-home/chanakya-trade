import React, { memo, useMemo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE, formatExpiryDetails } from './alertHelpers'

export const AlertTriageCard = memo(function AlertTriageCard({
  alert,
  isSelected,
  onSelect,
  onTrade,
  onAnalyze,
  onSendTelegram,
}) {
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const rawContract = alert.contract_symbol || optPlan?.contract_symbol || plan.option_contract || ''
  const cleanContract = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  
  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull

  const liveContractByClean = useLiveSpot(cleanContract)
  const liveContractByFull = useLiveSpot(rawContract && rawContract !== cleanContract ? rawContract : null)
  const liveContract = liveContractByClean ?? liveContractByFull

  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const isBull = alert.direction === 'BULLISH'
  const isBear = alert.direction === 'BEARISH'
  const isNeutral = alert.direction === 'NEUTRAL' || alert.alert_type === 'IRON_CONDOR_PINNING'
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED'
  const isT1Achieved = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isT2Achieved = alert.stage === 'T2_ACHIEVED' || alert.target_status === 'T2_ACHIEVED'
  const isFinalTargetAchieved = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED' || alert.stage === 'COMPLETED'
  const isTrail = alert.stage === 'TRAILING_UPDATE'
  const isEarly = alert.stage === 'EARLY_WARNING'

  const optType = alert.option_type || optPlan?.option_type || (rawContract?.endsWith('PE') ? 'PE' : rawContract?.endsWith('CE') ? 'CE' : null)
  const rawStrike = alert.strike || optPlan?.strike || alert.metrics?.strike
  const strikeNum = rawStrike ? Number(String(rawStrike).replace(/[^0-9.-]/g, '')) : null
  const isFuture = Boolean(rawContract?.toUpperCase().includes('FUT') || alert.symbol?.toUpperCase().includes('FUT') || alert.derivative_type === 'FUT')
  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && optType) || (rawContract && (rawContract.endsWith('CE') || rawContract.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'PATTERN_COILING' || alert.alert_type === 'MOMENTUM_ACCELERATION' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM' || alert.alert_type === 'TURTLE_SOUP_SHORT' || alert.alert_type === 'IRON_CONDOR_PINNING'
  const isDerivative = !isSpotSetup && Boolean(isFuture || isPureOption || (alert.exchange === 'NFO' && (optType || strikeNum || rawContract)))

  const expiryInfo = useMemo(() => formatExpiryDetails(alert), [alert])

  const act = String(tradePlan.action || plan.action || '').toUpperCase()
  const isOptionSell = isDerivative && (
    act === 'SELL' ||
    act === 'WRITE' ||
    act === 'SHORT' ||
    alert.alert_type === 'OPTION_WRITE'
  )

  const rawSpot = liveSpot?.ltp ?? alert.underlying_spot ?? alert.metrics?.spot
  const spotNum = rawSpot ? Number(rawSpot) : null
  const rawOptLtp = liveContract?.ltp ?? alert.option_premium ?? (isDerivative ? alert.ltp : null)
  const optLtpNum = rawOptLtp ? Number(rawOptLtp) : null

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

  const currentPrice = isDerivative ? optLtpNum : spotNum
  const fmtP = (v) => v !== null && v !== undefined && !isNaN(v) ? (Number(v) >= 500 ? Number(v).toFixed(1) : Number(v).toFixed(2)) : '—'

  let liveReturnPct = null
  let isProfitable = false
  if (currentPrice && entryNum && entryNum > 0) {
    let diff = 0
    if (isDerivative) {
      diff = isOptionSell ? entryNum - currentPrice : currentPrice - entryNum
      isProfitable = diff >= 0
    } else if (isNeutral) {
      const spe = Number(alert.metrics?.short_pe || slNum || entryNum * 0.985)
      const sce = Number(alert.metrics?.short_ce || t1Num || entryNum * 1.015)
      isProfitable = currentPrice >= spe && currentPrice <= sce
      const center = (spe + sce) / 2
      diff = isProfitable ? Math.max(0, (entryNum * 0.015) - Math.abs(currentPrice - center) * 0.03) : -Math.min(Math.abs(currentPrice - spe), Math.abs(currentPrice - sce))
    } else {
      diff = isBull ? currentPrice - entryNum : entryNum - currentPrice
      isProfitable = diff >= 0
    }
    liveReturnPct = ((diff / entryNum) * 100).toFixed(1)
  }

  // Dynamic stage hits
  const isSLHit = Boolean(
    isInvalidated ||
    (slNum && currentPrice && (
      isDerivative
        ? (isOptionSell ? currentPrice >= slNum : currentPrice <= slNum)
        : isNeutral
        ? (currentPrice < slNum || (alert.metrics?.long_ce && currentPrice > alert.metrics.long_ce))
        : (isBull ? currentPrice <= slNum : currentPrice >= slNum)
    ))
  )

  const isT3Hit = Boolean(
    isFinalTargetAchieved ||
    (t3Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t3Num : currentPrice >= t3Num)
        : isNeutral
        ? false
        : (isBull ? currentPrice >= t3Num : currentPrice <= t3Num)
    ))
  )

  const isT2Hit = Boolean(
    isT3Hit ||
    isT2Achieved ||
    (t2Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t2Num : currentPrice >= t2Num)
        : isNeutral
        ? false
        : (isBull ? currentPrice >= t2Num : currentPrice <= t2Num)
    ))
  )

  const isT1Hit = Boolean(
    isT2Hit ||
    isT1Achieved ||
    (t1Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t1Num : currentPrice >= t1Num)
        : isNeutral
        ? isProfitable
        : (isBull ? currentPrice >= t1Num : currentPrice <= t1Num)
    ))
  )

  const conviction = alert.confidence || 85

  return (
    <article
      onClick={onSelect}
      className={`rounded-xl p-2.5 transition-all duration-150 cursor-pointer text-xs space-y-1.5 ${
        isSelected
          ? 'bg-surface border-l-4 border-l-gold border-y border-r border-gold/30 shadow-md ring-1 ring-gold/20'
          : isSLHit
          ? 'bg-panel/50 hover:bg-surface/60 border border-rose-500/30 hover:border-rose-500/50 opacity-80'
          : 'bg-panel hover:bg-surface/80 border border-border/40 hover:border-border'
      }`}
    >
      {/* Row 1: Status Icon + Symbol + Strike + Direction + Live Price */}
      <div className="flex items-center justify-between gap-1.5 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
          <span className="text-xs">
            {isSLHit ? '🛑' : isT3Hit ? '🚀' : isT2Hit ? '🏁' : isT1Hit ? '🎯' : isTrail ? '📈' : isEarly ? '⏳' : style.icon}
          </span>
          <span className="font-black text-sm text-text leading-none">{alert.symbol}</span>
          {strikeNum && !isFuture && (
            <span className="text-[10px] font-bold text-gold font-mono leading-none">₹{Number(strikeNum).toLocaleString('en-IN')}</span>
          )}
          {optType && !isFuture && (
            <span className={`text-[8px] px-1 py-px rounded font-black uppercase ${
              optType === 'CE' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'
            }`}>{optType}</span>
          )}
          {isFuture && (
            <span className="text-[8px] px-1 py-px rounded font-black uppercase bg-blue-500/20 text-blue-300">FUT</span>
          )}
          <span className={`text-[8px] font-black px-1.5 py-0.5 rounded ${
            isBull ? 'text-emerald-400 bg-emerald-500/15' :
            isNeutral ? 'text-purple-400 bg-purple-500/15' :
            'text-rose-400 bg-rose-500/15'
          }`}>
            {isBull ? '▲ LONG' : isNeutral ? '◆ NEUTRAL' : '▼ SHORT'}
          </span>

          {/* Real-time Expiry Badge: Weekly vs Monthly */}
          {expiryInfo?.fullDisplay && (
            <span
              className={`text-[8px] font-mono px-1.5 py-0.5 rounded font-bold whitespace-nowrap border ${
                expiryInfo.isWeekly
                  ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  : 'bg-blue-500/15 text-blue-300 border-blue-500/30'
              }`}
              title={expiryInfo.formatted || 'Contract Expiry'}
            >
              {expiryInfo.fullDisplay}
            </span>
          )}

          {/* Real-time Stage Hit Badge */}
          {isSLHit ? (
            <span className="text-[7px] px-1.5 py-px rounded font-black uppercase bg-rose-500/25 text-rose-300 border border-rose-500/50 animate-pulse">
              🛑 SL HIT
            </span>
          ) : isT3Hit ? (
            <span className="text-[7px] px-1.5 py-px rounded font-black uppercase bg-purple-500/25 text-purple-200 border border-purple-400/50 animate-pulse">
              🚀 T3 HIT
            </span>
          ) : isT2Hit ? (
            <span className="text-[7px] px-1.5 py-px rounded font-black uppercase bg-cyan-500/25 text-cyan-200 border border-cyan-400/50 animate-pulse">
              🏁 T2 HIT
            </span>
          ) : isT1Hit ? (
            <span className="text-[7px] px-1.5 py-px rounded font-black uppercase bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 animate-pulse">
              🎯 T1 HIT
            </span>
          ) : null}

          {/* Time Horizon Badge */}
          {alert.time_horizon && (
            <span className={`text-[7px] px-1 py-px rounded font-black uppercase whitespace-nowrap border ${
              alert.time_horizon === 'INTRADAY' ? 'bg-sky-500/15 text-sky-300 border-sky-500/30' :
              alert.time_horizon === 'SWING_SHORT' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' :
              alert.time_horizon === 'SWING_MID' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' :
              'bg-purple-500/15 text-purple-300 border-purple-500/30'
            }`}>
              {alert.time_horizon === 'INTRADAY' ? '⏱️ INTRADAY' :
               alert.time_horizon === 'SWING_SHORT' ? '⚡ 2-5D' :
               alert.time_horizon === 'SWING_MID' ? '📈 1-4W' : '🏛️ POS'}
            </span>
          )}

          {/* Broker Depth Feed Status */}
          {alert.order_flow_signals?.live_broker_connected === false || alert.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' || alert.order_flow_signals?.provenance === 'SYNTHETIC_L1_DISCONNECTED' ? (
            <span className="text-[7px] px-1 py-px rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap" title="No active broker WebSocket connection. Using tick-level fallback.">
              ⚠️ SYNTHETIC L1
            </span>
          ) : (alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
            <span className="text-[7px] px-1 py-px rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap" title="Live Broker Level 2 depth active">
              🟢 LIVE L2
            </span>
          ) : null}
        </div>

        {/* Live Price & Return */}
        <div className="flex flex-col items-end flex-shrink-0 text-right">
          <div className="flex items-center gap-1">
            <span className={`text-xs font-black font-mono leading-none ${
              isDerivative
                ? (liveContract?.flash === 'up' ? 'text-emerald-400' : liveContract?.flash === 'down' ? 'text-rose-400' : 'text-gold')
                : (liveSpot?.flash === 'up' ? 'text-emerald-400' : liveSpot?.flash === 'down' ? 'text-rose-400' : 'text-text')
            }`}>
              ₹{fmtP(currentPrice)}
              {isDerivative && liveContract?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
            </span>
            {liveReturnPct && (
              <span className={`text-[9px] font-bold ${isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isProfitable ? '+' : ''}{liveReturnPct}%
              </span>
            )}
          </div>
          {isDerivative && spotNum && (
            <span className="text-[8px] font-mono text-muted leading-none mt-0.5">
              Spot ₹{Number(spotNum).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
          )}
        </div>
      </div>

      {/* Row 2: Headline */}
      <p className="text-[11px] text-zinc-300 truncate font-sans" title={alert.headline || alert.summary}>
        {alert.headline || alert.summary}
      </p>

      {/* Row 3: Key levels (Entry, SL, T1, T2) + Quick CTAs */}
      <div className="flex items-center justify-between gap-1 pt-1 border-t border-border/20 text-[9px] font-mono flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          {entryNum && <span className="text-gold font-bold">Entry ₹{fmtP(entryNum)}</span>}
          {alert.no_chase_boundary && (
            <span
              className="text-[8px] font-mono font-bold text-rose-700 dark:text-rose-300 bg-rose-500/10 dark:bg-rose-500/15 px-1 py-px rounded border border-rose-300/60 dark:border-rose-500/30 whitespace-nowrap"
              title="No-Chase limit: Entries beyond this price are disqualified"
            >
              Max ₹{fmtP(alert.no_chase_boundary)}
            </span>
          )}
          {slNum && (
            <span className={`font-bold px-1 py-px rounded ${isSLHit ? 'bg-rose-500/25 text-rose-300 border border-rose-500/50' : 'text-rose-600 dark:text-rose-400'}`}>
              {isSLHit ? '🛑 SL ' : 'SL '}₹{fmtP(slNum)}
            </span>
          )}
          {t1Num && (
            <span className={`font-bold px-1 py-px rounded ${isT1Hit ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/50' : 'text-emerald-600 dark:text-emerald-400'}`}>
              {isT1Hit ? '✅ T1 ' : 'T1 '}₹{fmtP(t1Num)}
            </span>
          )}
          {t2Num && (
            <span className={`font-bold px-1 py-px rounded ${isT2Hit ? 'bg-cyan-500/25 text-cyan-200 border border-cyan-500/50' : 'text-cyan-600 dark:text-cyan-400'}`}>
              {isT2Hit ? '✅ T2 ' : 'T2 '}₹{fmtP(t2Num)}
            </span>
          )}
          <span className="text-muted">· {conviction}%</span>
        </div>

        {/* Action CTAs */}
        <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => onTrade(alert)}
            className="btn btn-xs text-[9px] px-1.5 py-0.5 font-bold text-emerald-700 dark:text-emerald-300 hover:text-emerald-900 dark:hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-400/40 dark:border-emerald-500/30 transition-all rounded"
            title="1-Click Trade: Open pre-populated Order Ticket"
          >⚡ Trade</button>
          <button
            onClick={() => onSendTelegram(alert)}
            className="btn btn-xs text-[9px] px-1 py-0.5 font-bold text-sky-700 dark:text-sky-300 hover:text-sky-900 dark:hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-400/40 dark:border-sky-500/30 transition-all rounded"
            title="Send to Telegram"
          >↗ TG</button>
        </div>
      </div>
    </article>
  )
})
