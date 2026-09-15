import React, { memo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE, INDEX_LOT_SIZES, convictionEmoji, getStaleness } from './alertHelpers'
import { RRMiniBar, MilestoneDots } from './AlertWidgets'

export const AlertCompactRow = memo(function AlertCompactRow({ alert, onSendTelegram, onTrade, onExpand, isExpanded }) {
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const rawContract = alert.contract_symbol || alert.actionable_plan?.option_plan?.contract_symbol || alert.actionable_plan?.option_contract || ''
  const cleanContract = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()

  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull

  const liveContractByClean = useLiveSpot(cleanContract)
  const liveContractByFull = useLiveSpot(rawContract && rawContract !== cleanContract ? rawContract : null)
  const liveContract = liveContractByClean ?? liveContractByFull

  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const isBull = alert.direction === 'BULLISH'
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isEarly = alert.stage === 'EARLY_WARNING'
  const isIgnited = alert.stage === 'IGNITED'
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED'
  const isT1Achieved = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isT2Achieved = alert.stage === 'T2_ACHIEVED' || alert.target_status === 'T2_ACHIEVED'
  const isFinalTargetAchieved = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED' || alert.stage === 'COMPLETED'
  const isTrail = alert.stage === 'TRAILING_UPDATE'

  const optType = alert.option_type || (rawContract?.endsWith('PE') ? 'PE' : rawContract?.endsWith('CE') ? 'CE' : null)
  const strikeNum = alert.strike ? Number(String(alert.strike).replace(/[^0-9.-]/g, '')) : null
  const isFuture = Boolean(rawContract?.toUpperCase().includes('FUT') || alert.symbol?.toUpperCase().includes('FUT') || alert.derivative_type === 'FUT')
  
  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && optType) || (rawContract && (rawContract.endsWith('CE') || rawContract.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'PATTERN_COILING' || alert.alert_type === 'MOMENTUM_ACCELERATION' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM'
  const isDerivative = !isSpotSetup && Boolean(isFuture || isPureOption || (alert.exchange === 'NFO' && (optType || strikeNum || rawContract)))

  const lotSize = isDerivative ? (alert.lot_size || alert.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null) : null

  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const act = String(tradePlan.action || plan.action || '').toUpperCase()
  const isOptionSell = isDerivative && (
    act === 'SELL' ||
    act === 'WRITE' ||
    act === 'SHORT' ||
    alert.alert_type === 'OPTION_WRITE'
  )

  // Real-time live prices
  const rawSpot = liveSpot?.ltp ?? alert.underlying_spot ?? alert.metrics?.spot
  const spotNum = rawSpot ? Number(rawSpot) : null

  const rawOptLtp = liveContract?.ltp ?? alert.option_premium ?? (isDerivative ? alert.ltp : null)
  const premiumNum = rawOptLtp ? Number(rawOptLtp) : null

  const rawLtp = (!isDerivative ? liveSpot?.ltp : null) ?? alert.ltp
  const ltpNum = rawLtp ? Number(String(rawLtp).replace(/[^0-9.-]/g, '')) : null

  const slNum = isDerivative
    ? (optPlan?.sl_premium ? Number(optPlan.sl_premium) : (alert.option_stop_loss ? Number(alert.option_stop_loss) : (alert.stop_loss ? Number(alert.stop_loss) : null)))
    : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (alert.stop_loss ? Number(alert.stop_loss) : null))
  const entryNum = isDerivative
    ? (optPlan?.entry_premium ? Number(optPlan.entry_premium) : (alert.option_premium ? Number(alert.option_premium) : (premiumNum || ltpNum)))
    : (tradePlan.entry_price ? Number(tradePlan.entry_price) : (alert.trigger_level ? Number(alert.trigger_level) : ltpNum))
  const t1Num = isDerivative
    ? (optPlan?.t1_premium ? Number(optPlan.t1_premium) : (alert.option_target_1 ? Number(alert.option_target_1) : (alert.target_level ? Number(alert.target_level) : null)))
    : (tradePlan.target_1 ? Number(tradePlan.target_1) : (alert.target_level ? Number(alert.target_level) : null))
  const t2Num = isDerivative
    ? (optPlan?.t2_premium ? Number(optPlan.t2_premium) : (alert.option_target_2 ? Number(alert.option_target_2) : null))
    : (tradePlan.target_2 ? Number(tradePlan.target_2) : null)
  const t3Num = isDerivative
    ? (optPlan?.t3_premium ? Number(optPlan.t3_premium) : null)
    : (tradePlan.target_3 ? Number(tradePlan.target_3) : null)

  // Live Return % calculation & direction tracking
  const currentPrice = isDerivative ? premiumNum : spotNum
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
    isFinalTargetAchieved ||
    (t3Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t3Num : currentPrice >= t3Num)
        : (isBull ? currentPrice >= t3Num : currentPrice <= t3Num)
    ))
  )

  const isT2Hit = Boolean(
    isT3Hit ||
    isT2Achieved ||
    (t2Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t2Num : currentPrice >= t2Num)
        : (isBull ? currentPrice >= t2Num : currentPrice <= t2Num)
    ))
  )

  const isT1Hit = Boolean(
    isT2Hit ||
    isT1Achieved ||
    (t1Num && currentPrice && !isSLHit && (
      isDerivative
        ? (isOptionSell ? currentPrice <= t1Num : currentPrice >= t1Num)
        : (isBull ? currentPrice >= t1Num : currentPrice <= t1Num)
    ))
  )

  const expiryShort = (() => {
    if (!alert.expiry_date) return null
    try {
      const parts = alert.expiry_date.trim().split(/[-/]/)
      if (parts.length === 3) {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        const d = parts[0].length === 4
          ? new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
          : new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]))
        const dte = Math.round((d.getTime() - Date.now()) / 86400000)
        return `${d.getDate()}-${months[d.getMonth()]}${dte >= 0 ? ` (${dte}d)` : ''}`
      }
    } catch (_) {}
    return alert.expiry_date
  })()

  const staleness = getStaleness(alert.created_at)
  const timeShort = (() => {
    if (!alert.created_at) return ''
    try {
      const clean = alert.created_at.replace(' IST', '').trim()
      const d = new Date(clean)
      if (isNaN(d.getTime())) return alert.created_at.slice(-8, -4)
      return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
    } catch (_) { return '' }
  })()

  const conviction = Number(alert.confidence || alert.metrics?.scrutiny?.score || 75)
  const reasonShort = (alert.summary || alert.headline || '').slice(0, 40)

  // Stage pill styling with high-contrast glowing alerts
  const stagePill = isSLHit
    ? { label: '🛑 SL HIT', cls: 'bg-rose-500/25 text-rose-300 border-rose-500/60 ring-1 ring-rose-500/40 animate-pulse' }
    : isT3Hit
    ? { label: '🚀 T3 HIT', cls: 'bg-purple-500/25 text-purple-200 border-purple-400/60 ring-1 ring-purple-500/40 animate-pulse' }
    : isT2Hit
    ? { label: '🏁 T2 HIT', cls: 'bg-cyan-500/25 text-cyan-200 border-cyan-400/60 ring-1 ring-cyan-500/40 animate-pulse' }
    : isT1Hit
    ? { label: '🎯 T1 HIT', cls: 'bg-emerald-500/25 text-emerald-200 border-emerald-400/60 ring-1 ring-emerald-500/40 animate-pulse' }
    : isTrail
    ? { label: '📈 TRAIL', cls: 'bg-blue-500/20 text-blue-300 border-blue-500/40' }
    : isEarly
    ? { label: '⏳ EARLY', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' }
    : isIgnited
    ? { label: '🔥 IGNITED', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 animate-pulse' }
    : { label: '🟢 ACTIVE', cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' }

  const fmt = (n, dec = 0) => n != null && !isNaN(n) ? Number(n).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : '—'
  const fmtP = (n) => n != null && !isNaN(n) ? Number(n).toLocaleString('en-IN', { minimumFractionDigits: Number(n) < 100 ? 1 : 0, maximumFractionDigits: 1 }) : '—'

  const flashClass = isDerivative
    ? (liveContract?.flash === 'up' ? 'bg-emerald-500/30 text-emerald-300 ring-1 ring-emerald-400' : liveContract?.flash === 'down' ? 'bg-rose-500/30 text-rose-300 ring-1 ring-rose-400' : '')
    : (liveSpot?.flash === 'up' ? 'bg-emerald-500/30 text-emerald-300 ring-1 ring-emerald-400' : liveSpot?.flash === 'down' ? 'bg-rose-500/30 text-rose-300 ring-1 ring-rose-400' : '')

  return (
    <article
      className={`rounded-xl border px-2.5 py-1.5 cursor-pointer transition-all duration-150 hover:border-gold/40 group ${isSLHit ? 'border-rose-500/50 bg-rose-500/5' : ''}`}
      style={{
        background: isExpanded ? 'var(--color-elevated)' : isSLHit ? 'rgba(255, 79, 123, 0.05)' : 'var(--color-panel)',
        borderColor: isExpanded ? style.color + '55' : isSLHit ? 'rgba(255, 79, 123, 0.5)' : style.border,
      }}
      onClick={() => onExpand()}
    >
      {/* ── Row 1: Identity + Direction + Meta badges + Stage Pill ────── */}
      <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
        <span className={`text-[8px] font-black px-1.5 py-0.5 rounded-full border whitespace-nowrap flex-shrink-0 ${stagePill.cls}`}>
          {stagePill.label}
        </span>

        <span className="text-[11px] font-black text-text font-mono whitespace-nowrap">{cleanSym}</span>
        {strikeNum && !isFuture && (
          <span className="text-[10px] font-black text-gold font-mono whitespace-nowrap">
            {Number(strikeNum).toLocaleString('en-IN')}
          </span>
        )}
        {optType && !isFuture && (
          <span className={`text-[8px] px-1 py-px rounded font-black ${optType === 'CE' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
            {optType}
          </span>
        )}
        {isFuture && <span className="text-[8px] px-1 py-px rounded font-black bg-blue-500/20 text-blue-300">FUT</span>}
        {expiryShort && (
          <span className="text-[8px] text-muted font-mono whitespace-nowrap">{expiryShort}</span>
        )}

        <span className="text-border/30 text-[9px] hidden sm:inline">│</span>

        {isTest
          ? <span className="text-[7px] px-1 py-px rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap">🧪 TEST</span>
          : <span className="text-[7px] px-1 py-px rounded font-black bg-rose-500/20 text-rose-300 border border-rose-500/30 whitespace-nowrap">🔴 LIVE</span>
        }

        {/* ── Time Horizon Badge ── */}
        {alert.time_horizon && (
          <span className={`text-[7px] px-1.5 py-px rounded font-black whitespace-nowrap border ${
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

        {/* ── Broker Level 2 Connection Status ── */}
        {alert.order_flow_signals?.live_depth === false || alert.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' || alert.order_flow_signals?.provenance === 'SYNTHETIC_L1_DISCONNECTED' ? (
          <span className="text-[7px] px-1 py-px rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap hidden sm:inline" title="No active broker WebSocket depth connection. Using tick-level fallback.">
            ⚠️ SYNTHETIC L1 (NO BROKER WS)
          </span>
        ) : (alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
          <span className="text-[7px] px-1 py-px rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap hidden sm:inline" title="Live Broker Level 2 depth active">
            🟢 LIVE L2 DEPTH
          </span>
        ) : null}

        <span className={`text-[9px] font-black whitespace-nowrap ${isBull ? 'text-emerald-400' : 'text-rose-400'}`}>
          {isBull ? '▲' : '▼'} {alert.direction?.slice(0, 4)}
        </span>

        <span
          className="text-[7px] font-black px-1 py-px rounded whitespace-nowrap hidden sm:inline"
          style={{ color: style.color, background: style.bg, border: `1px solid ${style.border}` }}
        >
          {style.label.replace('GAMMA BLAST', 'Γ-Blast').replace('SQUEEZE BREAKOUT', 'Squeeze').replace('SMC LIQUIDITY', 'SMC').replace('CIRCUIT WARNING', 'Circuit').replace('CONFLUENCE INFLECTION', 'Confluence').replace('OPTIONS MOMENTUM', 'Opt Mom').replace('ASYMMETRIC R:R', 'Asym').replace('PRECURSOR RADAR', 'Precursor').replace('COMMODITY MOMENTUM', 'Commodity').replace('CURRENCY BREAKOUT', 'Currency')}
        </span>

        {lotSize && (
          <span
            className="text-[8px] font-mono font-bold text-sky-400 bg-sky-500/10 px-1.5 py-0.5 rounded border border-sky-500/25 whitespace-nowrap hidden md:inline cursor-help"
            title={`Market Lot Size: ${lotSize} units/shares per contract`}
          >
            Lot: {lotSize}
          </span>
        )}

        <MilestoneDots targetStatus={isT3Hit ? 'TARGET_ACHIEVED' : isT2Hit ? 'T2_ACHIEVED' : isT1Hit ? 'T1_ACHIEVED' : alert.target_status} stage={alert.stage} isSLHit={isSLHit} />

        {/* Live Return Pill (Right direction = Green, Loss = Red) */}
        {liveReturn && (
          <span className={`text-[8px] font-mono font-bold px-1.5 py-0.5 rounded-full border whitespace-nowrap transition-all ${
            liveReturn.isProfitable
              ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 shadow-[0_0_8px_rgba(16,185,129,0.15)]'
              : 'bg-rose-500/15 text-rose-300 border-rose-500/30'
          }`} title="Live Return vs Entry">
            {liveReturn.isProfitable ? '▲ +' : '▼ '}{liveReturn.pct}% ({liveReturn.diff >= 0 ? '+' : ''}₹{fmtP(liveReturn.diff)})
          </span>
        )}

        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse flex-shrink-0 ml-auto" title="Live quote feed active" />
      </div>

      {/* ── Row 2: Live Price levels + Realtime Direction + Conviction + Actions ─── */}
      <div className="flex items-center gap-1.5 min-w-0 flex-wrap mt-0.5">
        {/* Spot Price */}
        {isDerivative && spotNum && (
          <span className="text-[9px] font-mono text-zinc-400 whitespace-nowrap">
            Spot <span className="text-text font-bold">₹{fmt(spotNum)}</span>
          </span>
        )}

        {/* Real-time Live Option Premium or Equity Price with Flash */}
        {isDerivative ? (
          premiumNum && (
            <span className={`text-[9px] font-mono px-1 py-0.5 rounded transition-all duration-200 whitespace-nowrap ${flashClass || 'bg-panel'}`}>
              Prem <span className="text-gold font-black">₹{fmtP(premiumNum)}</span>
              {liveContract?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
            </span>
          )
        ) : (
          ltpNum && (
            <span className={`text-[9px] font-mono px-1 py-0.5 rounded transition-all duration-200 whitespace-nowrap ${flashClass || 'bg-panel'}`}>
              LTP <span className="text-text font-black">₹{fmt(ltpNum)}</span>
              {liveSpot?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
            </span>
          )
        )}

        {/* SL Level (Highlighted if hit) */}
        {slNum && (
          <span className={`text-[9px] font-mono whitespace-nowrap font-bold px-1 py-px rounded ${
            isSLHit ? 'bg-rose-500/25 text-rose-300 border border-rose-500/50' : 'text-rose-600 dark:text-rose-400'
          }`}>
            {isSLHit ? '🛑 SL ' : 'SL '}₹{fmtP(slNum)}
          </span>
        )}

        {/* Entry Level */}
        {entryNum && (
          <span className="text-[9px] font-mono text-amber-600 dark:text-amber-400 whitespace-nowrap font-bold">
            Entry ₹{fmtP(entryNum)}
          </span>
        )}

        {alert.no_chase_boundary && (
          <span
            className="text-[8px] font-mono font-bold text-rose-700 dark:text-rose-300 bg-rose-500/10 dark:bg-rose-500/15 px-1 py-px rounded border border-rose-300/60 dark:border-rose-500/30 whitespace-nowrap hidden sm:inline"
            title="No-Chase limit: Entries beyond this price are mathematically disqualified"
          >
            Max ₹{fmtP(alert.no_chase_boundary)}
          </span>
        )}

        {/* Target Levels (Highlighted with Checkmarks when hit) */}
        {t1Num && (
          <span className="text-[9px] font-mono whitespace-nowrap flex items-center gap-1">
            <span className={`px-1 py-px rounded font-bold transition-all ${
              isT1Hit ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40 shadow-sm' : 'text-emerald-500 dark:text-emerald-400'
            }`}>
              {isT1Hit ? '✅ T1 ' : 'T1 '}₹{fmtP(t1Num)}
            </span>
            {t2Num && (
              <span className={`px-1 py-px rounded font-bold transition-all ${
                isT2Hit ? 'bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm' : 'text-cyan-500 dark:text-cyan-400'
              }`}>
                {isT2Hit ? '✅ T2 ' : 'T2 '}₹{fmtP(t2Num)}
              </span>
            )}
            {t3Num && (
              <span className={`px-1 py-px rounded font-bold transition-all ${
                isT3Hit ? 'bg-purple-500/25 text-purple-200 border border-purple-500/40 shadow-sm' : 'text-purple-400 dark:text-purple-300'
              }`}>
                {isT3Hit ? '🚀 T3 ' : 'T3 '}₹{fmtP(t3Num)}
              </span>
            )}
          </span>
        )}

        <div className="w-16 flex-shrink-0 hidden sm:block">
          <RRMiniBar sl={slNum} entry={entryNum} t1={t1Num} t2={t2Num} t3={t3Num} currentPrice={currentPrice} isUpward={isDerivative ? !isOptionSell : isBull} />
        </div>

        <span className="text-[9px] font-mono whitespace-nowrap" title={`Conviction: ${conviction}`}>
          {convictionEmoji(conviction)}
          <span className="text-gold font-bold ml-0.5">{conviction}</span>
        </span>

        {reasonShort && (
          <span className="text-[9px] text-zinc-500 truncate min-w-0 flex-1 hidden md:block" title={alert.summary}>
            {reasonShort}
          </span>
        )}

        {staleness && (
          <span className="text-[8px] font-mono text-amber-400 whitespace-nowrap flex-shrink-0" title="Alert age">
            ⏱ {staleness}
          </span>
        )}

        {timeShort && (
          <span
            className="text-[8px] font-mono text-muted whitespace-nowrap flex-shrink-0 cursor-help"
            title={`Generated: ${alert.created_at || alert.timestamp || 'N/A'}`}
          >
            {timeShort} IST
          </span>
        )}

        <button
          onClick={(e) => {
            e.stopPropagation()
            const txt = [
              `${cleanSym}${strikeNum ? ' ' + strikeNum : ''}${optType ? optType : ''}${expiryShort ? ' ' + expiryShort : ''}`,
              isDerivative ? (spotNum ? `Spot ₹${fmt(spotNum)} Prem ₹${fmtP(premiumNum)}` : '') : `LTP ₹${fmt(ltpNum)}`,
              lotSize ? `Lot ${lotSize}` : '',
              slNum ? `SL ₹${fmtP(slNum)}` : '',
              entryNum ? `Entry ₹${fmtP(entryNum)}` : '',
              t1Num ? `T1 ₹${fmtP(t1Num)}${t2Num ? ' T2 ₹' + fmtP(t2Num) : ''}${t3Num ? ' T3 ₹' + fmtP(t3Num) : ''}` : '',
              `Conv ${conviction} · ${alert.direction}`,
            ].filter(Boolean).join(' | ')
            navigator.clipboard?.writeText(txt).catch(() => {})
          }}
          className="btn btn-xs btn-ghost text-[9px] px-1 text-muted hover:text-text border border-border/30 flex-shrink-0"
          title="Copy alert summary to clipboard"
        >📋</button>

        <button
          onClick={(e) => { e.stopPropagation(); onSendTelegram(alert) }}
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-sky-700 dark:text-sky-300 hover:text-sky-900 dark:hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-400/40 dark:border-sky-500/30 hover:border-sky-500/50 transition-all"
          title="Send to Telegram (due-diligence check)"
        >↗ TG</button>

        {!isDerivative && (optPlan || plan.option_contract) && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (onTrade) {
                onTrade({
                  ...alert,
                  _tradeOptionAlternative: true,
                })
              }
            }}
            className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-indigo-700 dark:text-indigo-300 hover:text-indigo-900 dark:hover:text-indigo-200 bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-400/40 dark:border-indigo-500/35 hover:border-indigo-500/60 transition-all"
            title={`Option Alternative: ${optPlan?.contract_symbol || plan.option_contract} @ ₹${optPlan?.entry_premium || plan.option_entry?.replace('₹', '') || '—'} (Click to trade Option)`}
          >⚡ Opt {optPlan?.contract_symbol ? optPlan.contract_symbol.slice(-6) : (plan.option_contract ? plan.option_contract.slice(-6) : '')}</button>
        )}

        <button
          onClick={(e) => {
            e.stopPropagation()
            if (onTrade) onTrade(alert)
          }}
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-emerald-700 dark:text-emerald-300 hover:text-emerald-900 dark:hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-400/40 dark:border-emerald-500/35 hover:border-emerald-500/60 transition-all"
          title="1-Click Trade: Open pre-populated Order Ticket"
        >⚡ Trade</button>

        <span className="text-muted text-[9px] flex-shrink-0 transition-transform duration-150" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          ▼
        </span>
      </div>
    </article>
  )
})
