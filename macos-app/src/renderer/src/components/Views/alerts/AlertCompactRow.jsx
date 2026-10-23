import React, { memo, useMemo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE, INDEX_LOT_SIZES, convictionEmoji, getStaleness, formatExpiryDetails, resolveAlertLifecycle, resolveAlertProvenance } from './alertHelpers'
import { RRMiniBar, MilestoneDots } from './AlertWidgets'

export const AlertCompactRow = memo(function AlertCompactRow({ alert, onSendTelegram, onTrade, onExpand, isExpanded, onDismiss }) {
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null
  const convictionTier = alert.metrics?.conviction_tier || plan.conviction_tier || null
  const executionMandate = plan.execution_style_mandate || alert.metrics?.execution_style_mandate || null

  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()
  const rawContract = alert.contract_symbol || optPlan?.contract_symbol || plan.option_contract || ''
  const cleanContract = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()

  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull

  const liveContractByClean = useLiveSpot(cleanContract)
  const liveContractByFull = useLiveSpot(rawContract && rawContract !== cleanContract ? rawContract : null)
  const liveContract = liveContractByClean ?? liveContractByFull

  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const provenance = useMemo(() => resolveAlertProvenance(alert), [alert])
  const isTest = provenance.isTest
  const isOffMarket = provenance.isOffMarket

  // Canonical Single Source of Truth Lifecycle Evaluation
  const lifecycle = useMemo(
    () => resolveAlertLifecycle(alert, { liveSpot, liveContract }),
    [alert, liveSpot, liveContract]
  )

  const {
    isTerminal,
    isDerivative,
    isBull,
    isBear,
    isNeutral,
    isOptionSell,
    optType,
    strikeNum,
    isFuture,
    isCrypto,
    currSym,
    levels,
    noChaseNum,
    spotNoChaseNum,
    entryNum,
    slNum,
    t1Num,
    t2Num,
    t3Num,
    currentPrice,
    spotNum,
    premiumNum,
    liveReturn,
    stagePill,
    isTimeStop,
    isSLHit,
    isExpired,
    isInvalidated,
    isT3Hit,
    isT2Hit,
    isT1Hit,
    horizonInfo,
  } = lifecycle

  const lotSize = isDerivative ? (alert.lot_size || optPlan?.lot_size || alert.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null) : null
  const expiryInfo = useMemo(() => formatExpiryDetails(alert), [alert])

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
  const reasonShort = alert.summary || alert.headline || ''
  const confluenceAlignment = alert.confluence_alignment || alert.metadata?.confluence_alignment || null
  const stagnationWarning = alert.stagnation_warning || alert.metadata?.stagnation_warning || null
  const physicalRisk = alert.physical_delivery_risk || alert.metadata?.physical_delivery_risk || null
  const gapRisk = alert.premarket_gap_risk || alert.metadata?.premarket_gap_risk || null

  const fmt = (n, dec = 0) => n != null && !isNaN(n) ? Number(n).toLocaleString(isCrypto ? 'en-US' : 'en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : '—'
  const fmtP = (n) => n != null && !isNaN(n) ? Number(n).toLocaleString(isCrypto ? 'en-US' : 'en-IN', { minimumFractionDigits: Number(n) < 100 ? 1 : 0, maximumFractionDigits: isCrypto ? 2 : 1 }) : '—'

  const flashClass = isDerivative
    ? (liveContract?.flash === 'up' ? 'bg-emerald-500/30 text-emerald-300 ring-1 ring-emerald-400' : liveContract?.flash === 'down' ? 'bg-rose-500/30 text-rose-300 ring-1 ring-rose-400' : '')
    : (liveSpot?.flash === 'up' ? 'bg-emerald-500/30 text-emerald-300 ring-1 ring-emerald-400' : liveSpot?.flash === 'down' ? 'bg-rose-500/30 text-rose-300 ring-1 ring-rose-400' : '')

  return (
    <article
      className={`rounded-xl border px-3 py-2 cursor-pointer transition-all duration-150 hover:border-gold/50 group shadow-xs ${isSLHit ? 'border-rose-500/50 bg-rose-500/5' : ''}`}
      style={{
        background: isExpanded ? 'var(--color-elevated)' : isSLHit ? 'rgba(255, 79, 123, 0.05)' : 'var(--color-panel)',
        borderColor: isExpanded ? style.color + '55' : isSLHit ? 'rgba(255, 79, 123, 0.5)' : style.border,
      }}
      onClick={() => onExpand()}
    >
      {/* ── Row 1: Clustered Identity + Direction + Meta badges + Stage Pill ────── */}
      <div className="flex items-center gap-2 min-w-0 flex-wrap">
        {/* Cluster 1: Stage Pill + Symbol + Strike + OptType + Expiry */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-[10px] font-black px-2 py-0.5 rounded-full border whitespace-nowrap flex-shrink-0 shadow-xs ${stagePill.cls}`}>
            {stagePill.label}
          </span>

          <span className="text-xs sm:text-[13px] font-black text-text font-mono whitespace-nowrap tracking-wide">{cleanSym}</span>
          {isDerivative && strikeNum && !isFuture && (
            <span className="text-[11px] font-black text-gold font-mono whitespace-nowrap">
              {currSym}{Number(strikeNum).toLocaleString(isCrypto ? 'en-US' : 'en-IN')}
            </span>
          )}
          {isDerivative && optType && !isFuture && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-black ${optType === 'CE' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'}`}>
              {optType}
            </span>
          )}
          {isDerivative && (expiryInfo?.fullDisplay || expiryShort) && (
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold whitespace-nowrap border ${
                expiryInfo?.isWeekly
                  ? 'bg-amber-500/15 text-amber-300 border-amber-500/35'
                  : 'bg-blue-500/15 text-blue-300 border-blue-500/35'
              }`}
              title={`Expiry Contract: ${expiryInfo?.formatted || 'Contract Expiry'} · ${expiryInfo?.isWeekly ? 'Weekly index contract' : 'Monthly series'}`}
            >
              {expiryInfo?.fullDisplay || expiryShort}
            </span>
          )}
        </div>

        <span className="text-border/40 text-xs hidden sm:inline">│</span>

        {/* Cluster 2: Market State + Horizon + Liquidity Watchdog */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {isTest ? (
            <span className="text-[10px] px-2 py-0.5 rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/35 whitespace-nowrap" title="🧪 Simulation: Offline backtest verification feed">🧪 TEST</span>
          ) : isOffMarket ? (
            <span className="text-[10px] px-2 py-0.5 rounded font-black bg-sky-500/20 text-sky-300 border border-sky-500/35 whitespace-nowrap" title="🌙 Session Closed: EOD snapshot levels active">🌙 OFF-MARKET / EOD</span>
          ) : (
            <span className="text-[10px] px-2 py-0.5 rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/35 whitespace-nowrap" title="🟢 Live Market: Streaming real-time tick and order-book data">🟢 REAL / LIVE</span>
          )}

          {/* Time Horizon & Cutoff Badge */}
          {horizonInfo && (
            <span
              title={horizonInfo.tooltip}
              className={`text-[10px] px-2 py-0.5 rounded font-black whitespace-nowrap border cursor-help ${horizonInfo.badgeClasses}`}
            >
              {horizonInfo.compactBadge}
            </span>
          )}

          {/* Options Liquidity Watchdog Badge */}
          {isDerivative && (alert.liquidity_status || alert.bid_ask_spread_pct !== null || alert.metrics?.liquidity) && (
            (() => {
              const spread = alert.bid_ask_spread_pct ?? alert.metrics?.liquidity?.bid_ask_spread_pct
              const status = alert.liquidity_status || alert.metrics?.liquidity?.liquidity_status || 'OPTIMAL'
              const isWide = status === 'WIDE_SPREAD_CAUTION' || (spread != null && spread > 2.5)
              const isMod = status === 'MODERATE' || (spread != null && spread > 1.0)
              const spreadLabel = spread != null ? `${spread.toFixed(1)}%` : ''
              return (
                <span
                  className={`text-[10px] px-2 py-0.5 rounded font-black whitespace-nowrap border hidden sm:inline ${
                    isWide ? 'bg-rose-500/20 text-rose-300 border-rose-500/40' :
                    isMod ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' :
                    'bg-emerald-500/20 text-emerald-300 border-emerald-500/35'
                  }`}
                  title={isWide ? `⚠️ Wide Bid-Ask Spread (${spreadLabel}) · High slippage risk · Limit orders mandatory!` : isMod ? `🟡 Moderate Spread (${spreadLabel}) · Patient limit fill recommended.` : `🟢 Optimal Liquidity (${spreadLabel}) · Tight top-of-book market depth.`}
                >
                  {isWide ? `⚠️ WIDE ${spreadLabel}` : isMod ? `🟡 SPREAD ${spreadLabel}` : `🟢 LIQUID ${spreadLabel}`.trim()}
                </span>
              )
            })()
          )}

          {/* Broker L2 Depth Connection Status */}
          {isTest ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap hidden md:inline" title="🧪 Synthetic Simulation Environment">
              🧪 SIM DEPTH
            </span>
          ) : alert.order_flow_signals?.live_depth === false || alert.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' || alert.order_flow_signals?.provenance === 'SYNTHETIC_L1_DISCONNECTED' ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap hidden md:inline" title="⚠️ Broker Depth Offline · Using tick-level fallback · Connect broker for full L2 book">
              ⚠️ SYNTHETIC L1
            </span>
          ) : (alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/35 whitespace-nowrap hidden md:inline" title="🟢 Live Broker L2 Depth Active · 50-level OBI & Iceberg detection running">
              🟢 LIVE L2 DEPTH
            </span>
          ) : null}

          {/* Telegram Status */}
          {alert.telegram_dispatched ? (
            <span className="text-[10px] px-2 py-0.5 rounded font-bold bg-sky-500/20 text-sky-300 border border-sky-500/35 whitespace-nowrap hidden md:inline-flex items-center gap-1" title="📱 Dispatched to Telegram channel successfully">
              <span>📱</span><span>TG SENT</span>
            </span>
          ) : alert.telegram_suppression_reason ? (
            <span className="text-[10px] px-2 py-0.5 rounded font-medium bg-amber-500/10 text-amber-300/90 border border-amber-500/25 whitespace-nowrap hidden md:inline-flex items-center gap-1 cursor-help" title={`📱 Telegram held: ${alert.telegram_suppression_reason}`}>
              <span>📱</span><span>TG HELD</span>
            </span>
          ) : null}
        </div>

        {/* Cluster 3: Direction + Conviction Tier + Mandates */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-[10px] font-black px-2 py-0.5 rounded whitespace-nowrap border ${
            isBull ? 'text-emerald-300 bg-emerald-500/15 border-emerald-500/30' :
            isNeutral ? 'text-purple-300 bg-purple-500/15 border-purple-500/30' :
            'text-rose-300 bg-rose-500/15 border-rose-500/30'
          }`}>
            {isBull ? '▲ BULL' : isNeutral ? '◆ NEUT' : '▼ BEAR'}
          </span>

          {convictionTier === 'APEX_CONFLUENCE' && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/25 text-amber-300 border border-amber-500/50 hidden sm:inline shadow-xs"
              title="💎 Tier 1 Apex Confluence (Conviction >= 90%) · Multi-model quantitative consensus · Full sizing permitted"
            >
              💎 APEX
            </span>
          )}
          {convictionTier === 'HIGH_CONVICTION' && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 hidden sm:inline"
              title="⚡ Tier 2 High Conviction (Conviction 80–89%) · Robust trend & volume confirmation"
            >
              ⚡ HIGH
            </span>
          )}
          {convictionTier === 'DEFINED_RISK_ONLY' && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 hidden sm:inline"
              title="🛡️ Tier 3 Defined-Risk Spread Only (Conviction 70–79%) · Naked buying vetoed"
            >
              🛡️ SPREAD
            </span>
          )}

          {/* Hedged Spread Execution Mandate */}
          {executionMandate === 'HEDGED_SPREAD_MANDATORY' && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/20 text-rose-300 border border-rose-500/40 hidden sm:inline"
              title={plan.sector_concurrency_warning || plan.trap_warning || '🛡️ Defined-Risk Spread Mandate: High India VIX or lunchtime chop decay · Vertical spread required'}
            >
              🛡️ HEDGE MANDATE
            </span>
          )}

          {/* Predatory Quant Pipeline Badges with 3-Part Actionable Tooltips */}
          {alert.metrics?.tiger_mandate && (
            <span
              className={`text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap border hidden lg:inline ${
                alert.metrics.tiger_mandate.mandate === 'MOMENTUM_EXPANSION'
                  ? 'bg-amber-500/25 text-amber-300 border-amber-500/50 animate-pulse'
                  : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
              }`}
              title={`🐅 Tiger Stalker: ${alert.metrics.tiger_mandate.mandate} · ${alert.metrics.tiger_mandate.reason || 'Momentum expansion active'}`}
            >
              {alert.metrics.tiger_mandate.mandate === 'MOMENTUM_EXPANSION' ? '🐅 TIGER POUNCE' : '🐅 TIGER STALKER'}
            </span>
          )}

          {alert.metrics?.eagle_regime?.chop_status === 'SEVERE_CHOP' && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/20 text-rose-300 border border-rose-500/40 hidden lg:inline"
              title={`🦅 Eagle Radar: Severe chop (CHOP=${alert.metrics.eagle_regime.chop_index?.toFixed(1) || ''}) · Capital preservation active`}
            >
              🦅 CHOP DEFENSE
            </span>
          )}

          {((alert.metrics?.rvol && alert.metrics.rvol >= 2.0) || alert.metrics?.predatory_pipeline?.elephant?.status === 'INSTITUTIONAL_FOOTPRINT') && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-purple-500/20 text-purple-300 border border-purple-500/40 hidden lg:inline"
              title={`🐘 Elephant Footprint: RVOL ${alert.metrics?.rvol?.toFixed(1) || '2.0+'}x + Order Block absorption · Institutional accumulation`}
            >
              🐘 ELEPHANT
            </span>
          )}

          {alert.metrics?.predatory_pipeline?.chanakya?.status === 'DE_TRAPPED' && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-emerald-500/20 text-emerald-300 border border-emerald-500/35 hidden lg:inline"
              title="🧠 Chanakya De-Trapped: Clean runway clear of OI walls, zero trap wicks"
            >
              🧠 DE-TRAPPED
            </span>
          )}

          {(alert.metrics?.free_roll_locked || alert.metrics?.predatory_pipeline?.cheetah?.status === 'FREE_ROLL_ACTIVE') && (
            <span
              className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-emerald-500/25 text-emerald-300 border border-emerald-500/50 animate-pulse hidden sm:inline"
              title="🐆 Cheetah Free-Roll: Stop ratcheted to cost/breakeven. Zero downside risk."
            >
              🐆 FREE-ROLL
            </span>
          )}

          {/* Strategy Category Label */}
          <span
            className="text-[10px] font-black px-2 py-0.5 rounded whitespace-nowrap hidden sm:inline"
            style={{ color: style.color, background: style.bg, border: `1px solid ${style.border}` }}
          >
            {style.label.replace('GAMMA BLAST', 'Γ-Blast').replace('SQUEEZE BREAKOUT', 'Squeeze').replace('SMC LIQUIDITY', 'SMC').replace('CIRCUIT WARNING', 'Circuit').replace('CONFLUENCE INFLECTION', 'Confluence').replace('OPTIONS MOMENTUM', 'Opt Mom').replace('ASYMMETRIC R:R', 'Asym').replace('PRECURSOR RADAR', 'Precursor').replace('COMMODITY MOMENTUM', 'Commodity').replace('CURRENCY BREAKOUT', 'Currency').replace('CVD ORDER FLOW', 'CVD Flow')}
          </span>

          {lotSize && (
            <span
              className="text-[10px] font-mono font-bold text-sky-400 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/25 whitespace-nowrap hidden xl:inline cursor-help"
              title={`Market Lot Size: ${lotSize} units per contract`}
            >
              Lot: {lotSize}
            </span>
          )}
        </div>

        {/* Milestone Indicator */}
        <MilestoneDots targetStatus={isT3Hit ? 'TARGET_ACHIEVED' : isT2Hit ? 'T2_ACHIEVED' : isT1Hit ? 'T1_ACHIEVED' : alert.target_status} stage={alert.stage} isSLHit={isSLHit} isExpired={isExpired} isInvalidated={isInvalidated} isTimeStop={isTimeStop} />

        {/* Live Return Pill (Right direction = Green, Loss = Red) */}
        {liveReturn && (
          <span className={`text-[10.5px] font-mono font-black px-2 py-0.5 rounded-full border whitespace-nowrap transition-all shadow-xs ${
            liveReturn.isProfitable
              ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_8px_rgba(16,185,129,0.2)]'
              : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
          }`} title="Live Return vs Entry Trigger">
            {liveReturn.isProfitable ? '▲ +' : '▼ '}{liveReturn.pct}% ({liveReturn.diff >= 0 ? '+' : ''}{currSym}{fmtP(liveReturn.diff)})
          </span>
        )}

        {/* Triggered Timestamp Badge */}
        {triggerTimeInfo && (
          <span
            className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-surface/90 text-zinc-300 border border-border/60 hover:border-gold/40 transition-all whitespace-nowrap flex items-center gap-1 ml-auto cursor-help shadow-xs"
            title={`Triggered: ${triggerTimeInfo.full}${triggerTimeInfo.elapsed ? ` (${triggerTimeInfo.elapsed})` : ''}`}
          >
            <span className="text-amber-400">🕒</span>
            <span className="text-zinc-200">{triggerTimeInfo.display}</span>
            {triggerTimeInfo.elapsed && (
              <span className="text-amber-400/90 font-medium">({triggerTimeInfo.elapsed})</span>
            )}
          </span>
        )}

        <span className={`inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse flex-shrink-0 ${triggerTimeInfo ? '' : 'ml-auto'}`} title="Live quote feed active" />
      </div>

      {/* ── Row 2: Live Price levels + Key Execution Milestones + Instant CTAs ─── */}
      <div className="flex items-center gap-2 min-w-0 flex-wrap mt-1.5 pt-1.5 border-t border-border/30">
        {/* Spot Price */}
        {isDerivative && spotNum && (
          <span className="text-[10.5px] font-mono tabular-nums text-zinc-400 whitespace-nowrap">
            Spot <span className="text-text font-bold">{currSym}{fmt(spotNum)}</span>
          </span>
        )}

        {/* Real-time Live Option Premium or Equity Price */}
        {isDerivative ? (
          premiumNum && (
            <span className={`text-xs font-mono tabular-nums px-2 py-0.5 rounded transition-all duration-200 whitespace-nowrap font-black border border-border/40 ${flashClass || 'bg-panel'}`}>
              Prem <span className="text-gold font-black">{currSym}{fmtP(premiumNum)}</span>
              {liveContract?.ltp && !isTerminal ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-1 align-middle" /> : null}
            </span>
          )
        ) : (
          currentPrice && (
            <span className={`text-xs font-mono tabular-nums px-2 py-0.5 rounded transition-all duration-200 whitespace-nowrap font-black border border-border/40 ${flashClass || 'bg-panel'}`}>
              LTP <span className="text-text font-black">{currSym}{fmt(currentPrice)}</span>
              {liveSpot?.ltp && !isTerminal ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-1 align-middle" /> : null}
            </span>
          )
        )}

        {/* SL Level (Highlighted if hit) */}
        {slNum && (
          <span className={`text-xs font-mono tabular-nums whitespace-nowrap font-bold px-1.5 py-0.5 rounded border ${
            isSLHit ? 'bg-rose-500/30 text-rose-200 border-rose-500/60 shadow-sm' : 'text-rose-400 bg-rose-500/10 border-rose-500/25'
          }`}>
            {isSLHit ? '🛑 SL ' : 'SL '}{currSym}{fmtP(slNum)}
          </span>
        )}

        {/* Entry Level */}
        {entryNum && (
          <span className="text-xs font-mono tabular-nums text-amber-300 bg-amber-500/10 border border-amber-500/25 px-1.5 py-0.5 rounded whitespace-nowrap font-bold">
            Entry {currSym}{fmtP(entryNum)}
          </span>
        )}

        {(alert.entry_range || alert.optimal_entry_range) && (
          <span
            className="text-[10px] font-mono tabular-nums font-bold text-amber-300 bg-amber-500/15 px-1.5 py-0.5 rounded border border-amber-500/35 whitespace-nowrap hidden md:inline"
            title="Optimal Trade Entry (OTE) pullback range"
          >
            OTE {alert.entry_range || alert.optimal_entry_range}
          </span>
        )}

        {(levels?.no_chase_boundary || noChaseNum) && (
          <span
            className="text-[10px] font-mono tabular-nums font-bold text-rose-300 bg-rose-500/15 px-1.5 py-0.5 rounded border border-rose-500/35 whitespace-nowrap hidden sm:inline"
            title={
              (levels?.spot_no_chase_boundary || spotNoChaseNum)
                ? `No-Chase Option Limit: Entries above ${currSym}${fmtP(levels?.no_chase_boundary || noChaseNum)} disqualify setup · Underlying Spot Max: ${currSym}${fmt(levels?.spot_no_chase_boundary || spotNoChaseNum)}`
                : `No-Chase limit: Entries beyond ${currSym}${fmtP(levels?.no_chase_boundary || noChaseNum)} are mathematically disqualified`
            }
          >
            NoChase {currSym}{fmtP(levels?.no_chase_boundary || noChaseNum)}
          </span>
        )}

        {(alert.actionable_plan?.sniper_plan || alert.metrics?.sniper_plan) && (
          <span
            className="text-[10px] font-mono tabular-nums font-bold text-emerald-300 bg-emerald-500/15 px-1.5 py-0.5 rounded border border-emerald-500/35 whitespace-nowrap hidden sm:inline"
            title={`🎯 SNIPER PLAN: OTE ₹${(alert.actionable_plan?.sniper_plan || alert.metrics?.sniper_plan).optimal_entry_zone} | Time Stop: ${(alert.actionable_plan?.sniper_plan || alert.metrics?.sniper_plan).time_stop_minutes}m`}
          >
            🎯 SNIPER 1:{(alert.actionable_plan?.sniper_plan || alert.metrics?.sniper_plan).risk_reward_ratio || '3.0'}
          </span>
        )}

        {/* Target Levels */}
        {t1Num && (
          <span className="text-xs font-mono tabular-nums whitespace-nowrap flex items-center gap-1">
            <span className={`px-1.5 py-0.5 rounded font-bold border transition-all ${
              isT1Hit ? 'bg-emerald-500/25 text-emerald-200 border-emerald-500/50 shadow-sm' : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/25'
            }`}>
              {isT1Hit ? '✅ T1 ' : 'T1 '}{currSym}{fmtP(t1Num)}
            </span>
            {t2Num && (
              <span className={`px-1.5 py-0.5 rounded font-bold border transition-all ${
                isT2Hit ? 'bg-cyan-500/25 text-cyan-200 border-cyan-500/50 shadow-sm' : 'text-cyan-400 bg-cyan-500/10 border-cyan-500/25'
              }`}>
                {isT2Hit ? '✅ T2 ' : 'T2 '}{currSym}{fmtP(t2Num)}
              </span>
            )}
            {t3Num && (
              <span className={`px-1.5 py-0.5 rounded font-bold border transition-all ${
                isT3Hit ? 'bg-purple-500/25 text-purple-200 border-purple-500/50 shadow-sm' : 'text-purple-400 bg-purple-500/10 border-purple-500/25'
              }`}>
                {isT3Hit ? '🚀 T3 ' : 'T3 '}{currSym}{fmtP(t3Num)}
              </span>
            )}
          </span>
        )}

        <div className="w-16 flex-shrink-0 hidden sm:block">
          <RRMiniBar sl={slNum} entry={entryNum} t1={t1Num} t2={t2Num} t3={t3Num} currentPrice={currentPrice} isUpward={isDerivative ? !isOptionSell : isBull} />
        </div>

        <span className="text-[10px] font-mono whitespace-nowrap" title={`Conviction: ${conviction}%`}>
          {convictionEmoji(conviction)}
          <span className="text-gold font-bold ml-1">{conviction}%</span>
        </span>

        {reasonShort && (
          <span className="text-[10px] text-zinc-400 truncate min-w-0 flex-1 hidden md:block" title={alert.summary}>
            {reasonShort}
          </span>
        )}

        {/* Action CTAs */}
        <div className="flex items-center gap-1.5 ml-auto flex-shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation()
              const txt = [
                `${cleanSym}${strikeNum ? ' ' + strikeNum : ''}${optType ? optType : ''}${expiryShort ? ' ' + expiryShort : ''}`,
                isDerivative ? (spotNum ? `Spot ${currSym}${fmt(spotNum)} Prem ${currSym}${fmtP(premiumNum)}` : '') : `LTP ${currSym}${fmt(currentPrice)}`,
                lotSize ? `Lot ${lotSize}` : '',
                slNum ? `SL ${currSym}${fmtP(slNum)}` : '',
                entryNum ? `Entry ${currSym}${fmtP(entryNum)}` : '',
                t1Num ? `T1 ${currSym}${fmtP(t1Num)}${t2Num ? ` T2 ${currSym}` + fmtP(t2Num) : ''}${t3Num ? ` T3 ${currSym}` + fmtP(t3Num) : ''}` : '',
                `Conv ${conviction}% · ${alert.direction}`,
              ].filter(Boolean).join(' | ')
              navigator.clipboard?.writeText(txt).catch(() => {})
            }}
            className="btn btn-xs btn-ghost text-[10px] px-1.5 py-0.5 text-muted hover:text-text border border-border/40 flex-shrink-0 rounded"
            title="Copy alert summary to clipboard"
          >📋</button>

          <button
            onClick={(e) => { e.stopPropagation(); onSendTelegram(alert) }}
            className="btn btn-xs text-[10px] px-2 py-0.5 font-bold flex-shrink-0 text-sky-300 hover:text-white bg-sky-500/15 hover:bg-sky-500/30 border border-sky-500/35 hover:border-sky-500/60 transition-all rounded"
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
              className="btn btn-xs text-[10px] px-2 py-0.5 font-bold flex-shrink-0 text-indigo-300 hover:text-white bg-indigo-500/15 hover:bg-indigo-500/30 border border-indigo-500/35 hover:border-indigo-500/60 transition-all rounded"
              title={`Option Alternative: ${optPlan?.contract_symbol || plan.option_contract} @ ${currSym}${optPlan?.entry_premium || plan.option_entry?.replace(/^[₹$]/, '') || '—'} (Click to trade Option)`}
            >⚡ Opt {optPlan?.strike ? `${optPlan.strike} ${optPlan.option_type || ''}` : (optPlan?.contract_symbol || plan.option_contract || '').replace(/^[A-Za-z]+/, '') || 'Proxy'}</button>
          )}

          {/* 1-Click Roll Strike Button */}
          {isDerivative && (isT2Hit || isT3Hit || Boolean(alert.strike_roll_recommendation)) && (
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
              className="btn btn-xs text-[10px] px-2 py-0.5 font-bold flex-shrink-0 text-amber-300 hover:text-amber-100 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 hover:border-amber-500/60 transition-all rounded animate-pulse"
              title={`Roll Strike: ${alert.strike_roll_recommendation?.reason || 'Lock in deep ITM gains and roll to liquid ATM strike'}`}
            >🔄 Roll Strike</button>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation()
              if (onTrade) {
                onTrade({
                  ...alert,
                  no_chase_boundary: levels?.no_chase_boundary || noChaseNum || alert.no_chase_boundary,
                  spot_no_chase_boundary: levels?.spot_no_chase_boundary || spotNoChaseNum || null,
                })
              }
            }}
            className="btn btn-xs text-[10px] px-2.5 py-0.5 font-black flex-shrink-0 text-slate-950 bg-emerald-500 hover:bg-emerald-400 border border-emerald-400/80 shadow-sm transition-all rounded"
            title="1-Click Trade: Open pre-populated Order Ticket"
          >⚡ Trade</button>

          {onDismiss && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDismiss(alert.alert_id || alert.id || alert.symbol)
              }}
              className="btn btn-xs text-[10px] px-1.5 py-0.5 font-bold flex-shrink-0 text-muted hover:text-rose-400 bg-surface/60 hover:bg-rose-500/15 border border-border/50 hover:border-rose-500/40 transition-all rounded"
              title="Dismiss / Remove this alert"
            >✕</button>
          )}

          <span className="text-muted text-[10px] flex-shrink-0 transition-transform duration-150" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
            ▼
          </span>
        </div>
      </div>
    </article>
  )
})
