import React, { memo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE } from './alertHelpers'

export const AlertTriageCard = memo(function AlertTriageCard({
  alert,
  isSelected,
  onSelect,
  onTrade,
  onAnalyze,
  onSendTelegram,
}) {
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const cleanContract = (alert.contract_symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  
  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull

  const liveContractByClean = useLiveSpot(cleanContract)
  const liveContractByFull = useLiveSpot(alert.contract_symbol && alert.contract_symbol !== cleanContract ? alert.contract_symbol : null)
  const liveContract = liveContractByClean ?? liveContractByFull

  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const isBull = alert.direction === 'BULLISH'
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED'
  const isT1 = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isFinalTarget = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED'
  const isTrail = alert.stage === 'TRAILING_UPDATE'
  const isEarly = alert.stage === 'EARLY_WARNING'

  const optType = alert.option_type || (alert.contract_symbol?.endsWith('PE') ? 'PE' : alert.contract_symbol?.endsWith('CE') ? 'CE' : null)
  const strikeNum = alert.strike ? Number(String(alert.strike).replace(/[^0-9.-]/g, '')) : null
  const isFuture = Boolean(alert.contract_symbol?.toUpperCase().includes('FUT') || alert.derivative_type === 'FUT')
  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && optType) || (alert.contract_symbol && (alert.contract_symbol.endsWith('CE') || alert.contract_symbol.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM'
  const isDerivative = !isSpotSetup && Boolean(isFuture || isPureOption || (alert.exchange === 'NFO' && (optType || strikeNum || alert.contract_symbol)))

  const rawSpot = liveSpot?.ltp ?? alert.underlying_spot ?? alert.metrics?.spot
  const spotNum = rawSpot ? Number(rawSpot) : null
  const rawOptLtp = liveContract?.ltp ?? alert.ltp ?? alert.option_premium
  const optLtpNum = rawOptLtp ? Number(rawOptLtp) : null

  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const slNum = isDerivative
    ? (optPlan?.sl_premium ? Number(optPlan.sl_premium) : (alert.option_stop_loss ? Number(alert.option_stop_loss) : (alert.stop_loss ? Number(alert.stop_loss) : null)))
    : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (alert.stop_loss ? Number(alert.stop_loss) : null))
  const entryNum = isDerivative
    ? (optPlan?.entry_premium ? Number(optPlan.entry_premium) : (optLtpNum || null))
    : (tradePlan.entry_price ? Number(tradePlan.entry_price) : (alert.trigger_level ? Number(alert.trigger_level) : spotNum))
  const t1Num = isDerivative
    ? (optPlan?.t1_premium ? Number(optPlan.t1_premium) : (alert.option_target_1 ? Number(alert.option_target_1) : (alert.target_level ? Number(alert.target_level) : null)))
    : (tradePlan.target_1 ? Number(tradePlan.target_1) : (alert.target_level ? Number(alert.target_level) : null))

  const fmtP = (v) => v !== null && v !== undefined && !isNaN(v) ? (Number(v) >= 500 ? Number(v).toFixed(1) : Number(v).toFixed(2)) : '—'

  let liveReturnPct = null
  if (optLtpNum && entryNum && entryNum > 0 && isDerivative) {
    const diff = optLtpNum - entryNum
    liveReturnPct = ((diff / entryNum) * 100).toFixed(1)
  } else if (spotNum && entryNum && entryNum > 0 && !isDerivative) {
    const diff = isBull ? spotNum - entryNum : entryNum - spotNum
    liveReturnPct = ((diff / entryNum) * 100).toFixed(1)
  }

  const conviction = alert.confidence || 85

  return (
    <article
      onClick={onSelect}
      className={`rounded-xl p-2.5 transition-all duration-150 cursor-pointer text-xs space-y-1.5 ${
        isSelected
          ? 'bg-surface border-l-4 border-l-gold border-y border-r border-gold/30 shadow-md ring-1 ring-gold/20'
          : isInvalidated
          ? 'bg-panel/50 hover:bg-surface/60 border border-rose-500/20 hover:border-rose-500/40 opacity-75'
          : 'bg-panel hover:bg-surface/80 border border-border/40 hover:border-border'
      }`}
    >
      {/* Row 1: Status Icon + Symbol + Strike + Direction + Live Price */}
      <div className="flex items-center justify-between gap-1.5 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
          <span className="text-xs">
            {isInvalidated ? '🛑' : isFinalTarget ? '🏁' : isT1 ? '🎯' : isTrail ? '📈' : isEarly ? '⏳' : style.icon}
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
          <span className={`text-[8px] font-bold ${isBull ? 'text-emerald-400' : 'text-rose-400'}`}>
            {isBull ? '▲' : '▼'} {alert.direction}
          </span>
        </div>

        {/* Live Price & Return */}
        <div className="flex flex-col items-end flex-shrink-0 text-right">
          <div className="flex items-center gap-1">
            <span className={`text-xs font-black font-mono leading-none ${
              isDerivative
                ? (liveContract?.flash === 'up' ? 'text-emerald-400' : liveContract?.flash === 'down' ? 'text-rose-400' : 'text-gold')
                : (liveSpot?.flash === 'up' ? 'text-emerald-400' : liveSpot?.flash === 'down' ? 'text-rose-400' : 'text-text')
            }`}>
              ₹{fmtP(isDerivative ? optLtpNum : spotNum)}
            </span>
            {liveReturnPct && (
              <span className={`text-[9px] font-bold ${Number(liveReturnPct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {Number(liveReturnPct) >= 0 ? '+' : ''}{liveReturnPct}%
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

      {/* Row 3: Key levels (Entry, SL, T1) + Quick CTAs */}
      <div className="flex items-center justify-between gap-1 pt-1 border-t border-border/20 text-[9px] font-mono flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          {entryNum && <span className="text-gold font-bold">Entry ₹{fmtP(entryNum)}</span>}
          {slNum && <span className="text-rose-400 font-bold">SL ₹{fmtP(slNum)}</span>}
          {t1Num && <span className="text-emerald-400 font-bold">T1 ₹{fmtP(t1Num)}</span>}
          <span className="text-muted">· {conviction}%</span>
        </div>

        {/* Action CTAs */}
        <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => onTrade(alert)}
            className="btn btn-xs text-[9px] px-1.5 py-0.5 font-bold text-emerald-300 hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 transition-all rounded"
            title="1-Click Trade: Open pre-populated Order Ticket"
          >⚡ Trade</button>
          <button
            onClick={() => onSendTelegram(alert)}
            className="btn btn-xs text-[9px] px-1 py-0.5 text-sky-300 hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 transition-all rounded"
            title="Send to Telegram"
          >↗ TG</button>
        </div>
      </div>
    </article>
  )
})
