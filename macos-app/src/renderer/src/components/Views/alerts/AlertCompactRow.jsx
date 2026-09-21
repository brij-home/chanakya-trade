import React, { memo, useMemo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE, INDEX_LOT_SIZES, convictionEmoji, getStaleness, formatExpiryDetails } from './alertHelpers'
import { RRMiniBar, MilestoneDots } from './AlertWidgets'

export const AlertCompactRow = memo(function AlertCompactRow({ alert, onSendTelegram, onTrade, onExpand, isExpanded, onDismiss }) {
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()
  const rawContract = alert.contract_symbol || optPlan?.contract_symbol || plan.option_contract || ''
  const cleanContract = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()

  const isCrypto = (alert.exchange || '').toUpperCase() === 'CRYPTO' || (alert.exchange || '').toUpperCase() === 'BINANCE' || (alert.segment || '').toUpperCase() === 'CRYPTO'
  const currSym = isCrypto ? '$' : '₹'

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
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isEarly = alert.stage === 'EARLY_WARNING'
  const isIgnited = alert.stage === 'IGNITED'
  const isExpired = alert.is_expired || alert.stage === 'EXPIRED'
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED' || isExpired
  const isT1Achieved = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isT2Achieved = alert.stage === 'T2_ACHIEVED' || alert.target_status === 'T2_ACHIEVED'
  const isFinalTargetAchieved = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED' || alert.stage === 'COMPLETED'
  const isTrail = alert.stage === 'TRAILING_UPDATE'

  const optType = alert.option_type || optPlan?.option_type || (rawContract?.endsWith('PE') ? 'PE' : rawContract?.endsWith('CE') ? 'CE' : null)
  const rawStrike = alert.strike || optPlan?.strike || alert.metrics?.strike
  const strikeNum = rawStrike ? Number(String(rawStrike).replace(/[^0-9.-]/g, '')) : null
  const isFuture = Boolean(rawContract?.toUpperCase().includes('FUT') || alert.symbol?.toUpperCase().includes('FUT') || alert.derivative_type === 'FUT')
  
  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && optType) || (rawContract && (rawContract.endsWith('CE') || rawContract.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'PATTERN_COILING' || alert.alert_type === 'MOMENTUM_ACCELERATION' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM' || alert.alert_type === 'TURTLE_SOUP_SHORT' || alert.alert_type === 'IRON_CONDOR_PINNING' || alert.alert_type === 'CRYPTO_SQUEEZE' || alert.alert_type === 'CRYPTO_MOMENTUM'
  const isDerivative = !isSpotSetup && Boolean(isFuture || isPureOption || (alert.exchange === 'NFO' && (optType || strikeNum || rawContract)))

  const lotSize = isDerivative ? (alert.lot_size || alert.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null) : null

  const expiryInfo = useMemo(() => formatExpiryDetails(alert), [alert])

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
    let isProf = false
    if (isDerivative) {
      diff = isOptionSell ? entryNum - currentPrice : currentPrice - entryNum
      isProf = diff >= 0
    } else if (isNeutral) {
      const spe = Number(alert.metrics?.short_pe || slNum || entryNum * 0.985)
      const sce = Number(alert.metrics?.short_ce || t1Num || entryNum * 1.015)
      isProf = currentPrice >= spe && currentPrice <= sce
      const center = (spe + sce) / 2
      diff = isProf ? Math.max(0, (entryNum * 0.015) - Math.abs(currentPrice - center) * 0.03) : -Math.min(Math.abs(currentPrice - spe), Math.abs(currentPrice - sce))
    } else {
      diff = isBull ? currentPrice - entryNum : entryNum - currentPrice
      isProf = diff >= 0
    }
    const pct = ((diff / entryNum) * 100).toFixed(1)
    liveReturn = { diff, pct, isProfitable: isProf }
  }

  // Dynamic live stage hit detection (real-time cross evaluation)
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

  const expiryShort = useMemo(() => {
    if (expiryInfo?.fullDisplay) return expiryInfo.fullDisplay
    const rawDate = alert.expiry_date || optPlan?.expiry_date || alert.expiry_details?.raw_date
    if (!rawDate) return null
    try {
      const parts = String(rawDate).trim().split(/[-/]/)
      if (parts.length === 3) {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        const d = parts[0].length === 4
          ? new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
          : new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]))
        const dte = Math.round((d.getTime() - Date.now()) / 86400000)
        return `${d.getDate()}-${months[d.getMonth()]}${dte >= 0 ? ` (${dte}d)` : ''}`
      }
    } catch (_) {}
    return String(rawDate)
  }, [expiryInfo, alert.expiry_date, optPlan?.expiry_date, alert.expiry_details?.raw_date])

  const triggerTimeStr = alert.timestamp || alert.created_at || alert.triggered_at || alert.time || ''

  const triggerTimeInfo = useMemo(() => {
    if (!triggerTimeStr) return null
    try {
      const raw = String(triggerTimeStr).trim()
      const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?/)
      const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

      if (m) {
        const [_, y, mo, d, hh, mm, ss] = m
        const alertDate = new Date(Number(y), Number(mo) - 1, Number(d), Number(hh), Number(mm), Number(ss || 0))
        const today = new Date()
        const isToday = alertDate.toDateString() === today.toDateString()

        const diffMs = Math.max(0, today.getTime() - alertDate.getTime())
        const diffMins = Math.floor(diffMs / 60000)
        let elapsed = ''
        if (diffMins < 1) elapsed = 'just now'
        else if (diffMins < 60) elapsed = `${diffMins}m ago`
        else if (diffMins < 1440) elapsed = `${Math.floor(diffMins / 60)}h ago`
        else elapsed = `${Math.floor(diffMins / 1440)}d ago`

        const timeStr = `${hh}:${mm}${ss ? `:${ss}` : ''}`
        const prettyDate = `${Number(d)} ${months[Number(mo) - 1]}`

        return {
          display: isToday ? `${timeStr} IST` : `${prettyDate} ${timeStr} IST`,
          full: raw,
          elapsed,
          timeOnly: timeStr,
        }
      }

      const clean = raw.replace(/\s*IST$/i, '').trim()
      const parsed = new Date(clean)
      if (!isNaN(parsed.getTime())) {
        const today = new Date()
        const isToday = parsed.toDateString() === today.toDateString()
        const timeStr = parsed.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
        const diffMs = Math.max(0, today.getTime() - parsed.getTime())
        const diffMins = Math.floor(diffMs / 60000)
        let elapsed = ''
        if (diffMins < 1) elapsed = 'just now'
        else if (diffMins < 60) elapsed = `${diffMins}m ago`
        else if (diffMins < 1440) elapsed = `${Math.floor(diffMins / 60)}h ago`
        else elapsed = `${Math.floor(diffMins / 1440)}d ago`

        const prettyDate = `${parsed.getDate()} ${months[parsed.getMonth()]}`

        return {
          display: isToday ? `${timeStr} IST` : `${prettyDate} ${timeStr} IST`,
          full: raw,
          elapsed,
          timeOnly: timeStr,
        }
      }

      return {
        display: raw.length > 18 ? raw.slice(-14) : raw,
        full: raw,
        elapsed: '',
        timeOnly: raw,
      }
    } catch (_) {
      return { display: String(triggerTimeStr), full: String(triggerTimeStr), elapsed: '', timeOnly: String(triggerTimeStr) }
    }
  }, [triggerTimeStr])

  const conviction = Number(alert.confidence || alert.metrics?.scrutiny?.score || 75)
  const reasonShort = (alert.summary || alert.headline || '').slice(0, 40)

  // Stage pill styling with high-contrast glowing alerts
  const stagePill = isExpired
    ? { label: '⏱️ EXPIRED', cls: 'bg-zinc-700/40 text-zinc-300 border-zinc-600/40' }
    : isSLHit
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

  const fmt = (n, dec = 0) => n != null && !isNaN(n) ? Number(n).toLocaleString(isCrypto ? 'en-US' : 'en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : '—'
  const fmtP = (n) => n != null && !isNaN(n) ? Number(n).toLocaleString(isCrypto ? 'en-US' : 'en-IN', { minimumFractionDigits: Number(n) < 100 ? 1 : 0, maximumFractionDigits: isCrypto ? 2 : 1 }) : '—'

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
            {currSym}{Number(strikeNum).toLocaleString(isCrypto ? 'en-US' : 'en-IN')}
          </span>
        )}
        {optType && !isFuture && (
          <span className={`text-[8px] px-1 py-px rounded font-black ${optType === 'CE' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
            {optType}
          </span>
        )}
        {isFuture && <span className="text-[8px] px-1 py-px rounded font-black bg-blue-500/20 text-blue-300">FUT</span>}
        {(expiryInfo?.fullDisplay || expiryShort) && (
          <span
            className={`text-[8px] font-mono px-1.5 py-px rounded font-bold whitespace-nowrap border ${
              expiryInfo?.isWeekly
                ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                : 'bg-blue-500/15 text-blue-300 border-blue-500/30'
            }`}
            title={expiryInfo?.formatted || 'Contract Expiry'}
          >
            {expiryInfo?.fullDisplay || expiryShort}
          </span>
        )}

        <span className="text-border/30 text-[9px] hidden sm:inline">│</span>

        {isTest
          ? <span className="text-[7px] px-1 py-px rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap">🧪 TEST</span>
          : <span className="text-[7px] px-1 py-px rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap">🟢 REAL / LIVE</span>
        }

        {/* ── Time Horizon Badge ── */}
        {alert.time_horizon && (
          <span className={`text-[7px] px-1.5 py-px rounded font-black whitespace-nowrap border ${
            alert.time_horizon === 'INTRADAY' ? 'bg-sky-500/15 text-sky-300 border-sky-500/30' :
            alert.time_horizon === 'SWING_SHORT' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' :
            alert.time_horizon === 'SWING_MID' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' :
            'bg-purple-500/15 text-purple-300 border-purple-500/30'
          }`}>
            {alert.time_horizon === 'INTRADAY'
              ? (alert.exchange === 'MCX' ? '⏱️ INTRADAY (23:15)' : '⏱️ INTRADAY (15:15)')
              : alert.time_horizon === 'SWING_SHORT' ? '⚡ 2-5D SWING'
              : alert.time_horizon === 'SWING_MID' ? '📈 1-4W SWING'
              : '🏛️ POSITIONAL'}
          </span>
        )}

        {/* ── Options Liquidity Watchdog Badge ── */}
        {isDerivative && (alert.liquidity_status || alert.bid_ask_spread_pct !== null || alert.metrics?.liquidity) && (
          (() => {
            const spread = alert.bid_ask_spread_pct ?? alert.metrics?.liquidity?.bid_ask_spread_pct
            const status = alert.liquidity_status || alert.metrics?.liquidity?.liquidity_status || 'OPTIMAL'
            const isWide = status === 'WIDE_SPREAD_CAUTION' || (spread != null && spread > 2.5)
            const isMod = status === 'MODERATE' || (spread != null && spread > 1.0)
            const spreadLabel = spread != null ? `${spread.toFixed(1)}%` : ''
            return (
              <span
                className={`text-[7px] px-1.5 py-px rounded font-black whitespace-nowrap border hidden sm:inline ${
                  isWide ? 'bg-rose-500/20 text-rose-300 border-rose-500/40' :
                  isMod ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' :
                  'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                }`}
                title={isWide ? `Wide Bid-Ask Spread (${spreadLabel}). Slippage risk on market orders!` : isMod ? `Moderate Spread (${spreadLabel}). Use Limit Orders.` : `Optimal Liquidity (${spreadLabel})`}
              >
                {isWide ? `⚠️ WIDE ${spreadLabel}` : isMod ? `🟡 SPREAD ${spreadLabel}` : `🟢 LIQUID ${spreadLabel}`.trim()}
              </span>
            )
          })()
        )}

        {/* ── Broker Level 2 Connection Status ── */}
        {isTest ? (
          <span className="text-[7px] px-1 py-px rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap hidden sm:inline" title="Simulated test environment">
            🧪 SIM DEPTH
          </span>
        ) : alert.order_flow_signals?.live_depth === false || alert.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' || alert.order_flow_signals?.provenance === 'SYNTHETIC_L1_DISCONNECTED' ? (
          <span className="text-[7px] px-1 py-px rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap hidden sm:inline" title="No active broker WebSocket depth connection. Using tick-level fallback.">
            ⚠️ SYNTHETIC L1 (NO BROKER WS)
          </span>
        ) : (alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
          <span className="text-[7px] px-1 py-px rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap hidden sm:inline" title="Live Broker Level 2 depth active">
            🟢 LIVE L2 DEPTH
          </span>
        ) : null}

        <span className={`text-[9px] font-black px-1.5 py-px rounded whitespace-nowrap ${
          isBull ? 'text-emerald-400 bg-emerald-500/10' :
          isNeutral ? 'text-purple-400 bg-purple-500/10' :
          'text-rose-400 bg-rose-500/10'
        }`}>
          {isBull ? '▲ BULL' : isNeutral ? '◆ NEUT' : '▼ BEAR'}
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
            {liveReturn.isProfitable ? '▲ +' : '▼ '}{liveReturn.pct}% ({liveReturn.diff >= 0 ? '+' : ''}{currSym}{fmtP(liveReturn.diff)})
          </span>
        )}

        {/* Triggered Timestamp Badge (High visibility on top right of compact card) */}
        {triggerTimeInfo && (
          <span
            className="text-[9px] font-mono font-bold px-2 py-0.5 rounded bg-surface/90 text-zinc-300 border border-border/60 hover:border-gold/40 transition-all whitespace-nowrap flex items-center gap-1.5 ml-auto cursor-help shadow-xs"
            title={`Triggered: ${triggerTimeInfo.full}${triggerTimeInfo.elapsed ? ` (${triggerTimeInfo.elapsed})` : ''}`}
          >
            <span className="text-[10px] text-amber-400">🕒</span>
            <span className="text-zinc-200">{triggerTimeInfo.display}</span>
            {triggerTimeInfo.elapsed && (
              <span className="text-[8px] text-amber-400/90 font-medium">({triggerTimeInfo.elapsed})</span>
            )}
          </span>
        )}

        <span className={`inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse flex-shrink-0 ${triggerTimeInfo ? '' : 'ml-auto'}`} title="Live quote feed active" />
      </div>

      {/* ── Row 2: Live Price levels + Realtime Direction + Conviction + Actions ─── */}
      <div className="flex items-center gap-1.5 min-w-0 flex-wrap mt-0.5">
        {/* Spot Price */}
        {isDerivative && spotNum && (
          <span className="text-[9px] font-mono text-zinc-400 whitespace-nowrap">
            Spot <span className="text-text font-bold">{currSym}{fmt(spotNum)}</span>
          </span>
        )}

        {/* Real-time Live Option Premium or Equity Price with Flash */}
        {isDerivative ? (
          premiumNum && (
            <span className={`text-[9px] font-mono px-1 py-0.5 rounded transition-all duration-200 whitespace-nowrap ${flashClass || 'bg-panel'}`}>
              Prem <span className="text-gold font-black">{currSym}{fmtP(premiumNum)}</span>
              {liveContract?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
            </span>
          )
        ) : (
          ltpNum && (
            <span className={`text-[9px] font-mono px-1 py-0.5 rounded transition-all duration-200 whitespace-nowrap ${flashClass || 'bg-panel'}`}>
              LTP <span className="text-text font-black">{currSym}{fmt(ltpNum)}</span>
              {liveSpot?.ltp ? <span className="inline-block w-1 h-1 rounded-full bg-emerald-400 animate-pulse ml-0.5 align-middle" /> : null}
            </span>
          )
        )}

        {/* SL Level (Highlighted if hit) */}
        {slNum && (
          <span className={`text-[9px] font-mono whitespace-nowrap font-bold px-1 py-px rounded ${
            isSLHit ? 'bg-rose-500/25 text-rose-300 border border-rose-500/50' : 'text-rose-600 dark:text-rose-400'
          }`}>
            {isSLHit ? '🛑 SL ' : 'SL '}{currSym}{fmtP(slNum)}
          </span>
        )}

        {/* Entry Level */}
        {entryNum && (
          <span className="text-[9px] font-mono text-amber-600 dark:text-amber-400 whitespace-nowrap font-bold">
            Entry {currSym}{fmtP(entryNum)}
          </span>
        )}

        {alert.no_chase_boundary && (
          <span
            className="text-[8px] font-mono font-bold text-rose-700 dark:text-rose-300 bg-rose-500/10 dark:bg-rose-500/15 px-1 py-px rounded border border-rose-300/60 dark:border-rose-500/30 whitespace-nowrap hidden sm:inline"
            title="No-Chase limit: Entries beyond this price are mathematically disqualified"
          >
            Max {currSym}{fmtP(alert.no_chase_boundary)}
          </span>
        )}

        {/* Target Levels (Highlighted with Checkmarks when hit) */}
        {t1Num && (
          <span className="text-[9px] font-mono whitespace-nowrap flex items-center gap-1">
            <span className={`px-1 py-px rounded font-bold transition-all ${
              isT1Hit ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40 shadow-sm' : 'text-emerald-500 dark:text-emerald-400'
            }`}>
              {isT1Hit ? '✅ T1 ' : 'T1 '}{currSym}{fmtP(t1Num)}
            </span>
            {t2Num && (
              <span className={`px-1 py-px rounded font-bold transition-all ${
                isT2Hit ? 'bg-cyan-500/25 text-cyan-200 border border-cyan-500/40 shadow-sm' : 'text-cyan-500 dark:text-cyan-400'
              }`}>
                {isT2Hit ? '✅ T2 ' : 'T2 '}{currSym}{fmtP(t2Num)}
              </span>
            )}
            {t3Num && (
              <span className={`px-1 py-px rounded font-bold transition-all ${
                isT3Hit ? 'bg-purple-500/25 text-purple-200 border border-purple-500/40 shadow-sm' : 'text-purple-400 dark:text-purple-300'
              }`}>
                {isT3Hit ? '🚀 T3 ' : 'T3 '}{currSym}{fmtP(t3Num)}
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


        <button
          onClick={(e) => {
            e.stopPropagation()
            const txt = [
              `${cleanSym}${strikeNum ? ' ' + strikeNum : ''}${optType ? optType : ''}${expiryShort ? ' ' + expiryShort : ''}`,
              isDerivative ? (spotNum ? `Spot ${currSym}${fmt(spotNum)} Prem ${currSym}${fmtP(premiumNum)}` : '') : `LTP ${currSym}${fmt(ltpNum)}`,
              lotSize ? `Lot ${lotSize}` : '',
              slNum ? `SL ${currSym}${fmtP(slNum)}` : '',
              entryNum ? `Entry ${currSym}${fmtP(entryNum)}` : '',
              t1Num ? `T1 ${currSym}${fmtP(t1Num)}${t2Num ? ` T2 ${currSym}` + fmtP(t2Num) : ''}${t3Num ? ` T3 ${currSym}` + fmtP(t3Num) : ''}` : '',
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
            title={`Option Alternative: ${optPlan?.contract_symbol || plan.option_contract} @ ${currSym}${optPlan?.entry_premium || plan.option_entry?.replace(/^[₹$]/, '') || '—'} (Click to trade Option)`}
          >⚡ Opt {optPlan?.contract_symbol ? optPlan.contract_symbol.slice(-6) : (plan.option_contract ? plan.option_contract.slice(-6) : '')}</button>
        )}

        {/* ── 1-Click Roll Strike Button ── */}
        {isDerivative && (isT2Hit || isT3Hit || isFinalTargetAchieved || Boolean(alert.strike_roll_recommendation)) && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (onTrade) {
                onTrade({
                  ...alert,
                  _isStrikeRoll: true,
                  _rollRecommendation: alert.strike_roll_recommendation,
                })
              }
            }}
            className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-amber-700 dark:text-amber-300 hover:text-amber-900 dark:hover:text-amber-200 bg-amber-500/15 hover:bg-amber-500/25 border border-amber-400/40 dark:border-amber-500/35 hover:border-amber-500/60 transition-all animate-pulse"
            title={`Roll Strike: ${alert.strike_roll_recommendation?.reason || 'Lock in deep ITM gains and roll to liquid ATM strike'}`}
          >🔄 Roll Strike</button>
        )}

        <button
          onClick={(e) => {
            e.stopPropagation()
            if (onTrade) onTrade(alert)
          }}
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-emerald-700 dark:text-emerald-300 hover:text-emerald-900 dark:hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-400/40 dark:border-emerald-500/35 hover:border-emerald-500/60 transition-all"
          title="1-Click Trade: Open pre-populated Order Ticket"
        >⚡ Trade</button>

        {onDismiss && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDismiss(alert.alert_id || alert.id || alert.symbol)
            }}
            className="btn btn-xs text-[9px] px-1 font-bold flex-shrink-0 text-muted hover:text-rose-400 bg-surface/60 hover:bg-rose-500/15 border border-border/50 hover:border-rose-500/40 transition-all rounded"
            title="Dismiss / Remove this alert"
          >✕</button>
        )}

        <span className="text-muted text-[9px] flex-shrink-0 transition-transform duration-150" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          ▼
        </span>
      </div>
    </article>
  )
})
