import React, { memo, useState, useMemo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE, formatExpiryDetails, resolveAlertLifecycle, isTestOrSimAlert } from './alertHelpers'

/**
 * Individual row in the institutional AlertTableView.
 * Subscribes to live spot/contract prices via LiveSpotsContext.
 */
export const AlertTableRow = memo(function AlertTableRow({
  alert,
  onTrade,
  onSendTelegram,
  onDismiss,
  onAnalyze,
  isSelected,
  onSelect,
}) {
  const [isExpanded, setIsExpanded] = useState(false)
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

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

  // Canonical Single Source of Truth Lifecycle Evaluation
  const lifecycle = useMemo(
    () => resolveAlertLifecycle(alert, { liveSpot, liveContract }),
    [alert, liveSpot, liveContract]
  )

  const {
    isDerivative,
    isBull,
    isNeutral,
    optType,
    strikeNum,
    isFuture,
    isCrypto,
    currSym,
    entryNum,
    slNum,
    t1Num,
    t2Num,
    t3Num,
    currentPrice,
    spotNum,
    liveReturn,
    stagePill,
    isSLHit,
    isExpired,
    isInvalidated,
    isT1Hit,
    isT2Hit,
    isT3Hit,
    horizonInfo,
  } = lifecycle

  const liveReturnPct = liveReturn?.pct || null
  const isProfitable = liveReturn?.isProfitable || false

  const expiryInfo = useMemo(() => formatExpiryDetails(alert), [alert])
  const fmtP = (v) => v !== null && v !== undefined && !isNaN(v) ? (Number(v) >= 500 ? Number(v).toFixed(1) : Number(v).toFixed(2)) : '—'
  const conviction = alert.confidence || 85
  const convictionTier = alert.metrics?.conviction_tier || plan.conviction_tier || null
  const executionMandate = plan.execution_style_mandate || alert.metrics?.execution_style_mandate || null
  const confluenceAlignment = alert.confluence_alignment || alert.metadata?.confluence_alignment || null
  const gapRisk = alert.premarket_gap_risk || alert.metadata?.premarket_gap_risk || null
  const physicalRisk = alert.physical_delivery_risk || alert.metadata?.physical_delivery_risk || null
  const stagnationWarning = alert.stagnation_warning || alert.metadata?.stagnation_warning || null

  const isWideSpread = Boolean(alert.metrics?.liquidity_warning || plan.execution_ticket?.liquidity_warning || alert.extra_metrics?.bid_ask_spread_pct > 2.0)
  const spreadPct = alert.extra_metrics?.bid_ask_spread_pct || null

  const rollRec = alert.strike_roll_recommendation || alert._rollRecommendation || null
  const isStrikeRollEligible = Boolean(rollRec && !isExpired && !isInvalidated)

  const handleRowClick = () => {
    if (onSelect) onSelect(alert)
    else setIsExpanded((prev) => !prev)
  }

  return (
    <>
      <tr
        onClick={handleRowClick}
        className={`border-b border-border/30 transition-all cursor-pointer font-ui text-xs hover:bg-surface/70 ${
          isSelected
            ? 'bg-surface border-l-4 border-l-gold border-gold/40'
            : isSLHit
            ? 'bg-rose-500/5 hover:bg-rose-500/10 opacity-80'
            : isExpired || isInvalidated
            ? 'bg-panel/40 opacity-70'
            : 'bg-panel'
        }`}
      >
        {/* Col 1: Stage / Status */}
        <td className="py-2.5 px-3 whitespace-nowrap">
          <div className="flex items-center gap-1.5">
            <span className="text-sm">{stagePill?.icon || style.icon}</span>
            {stagePill ? (
              <span className={`text-[10px] px-2 py-0.5 rounded font-black uppercase border whitespace-nowrap ${stagePill.cls}`}>
                {stagePill.label}
              </span>
            ) : (
              <span className="text-[10px] px-2 py-0.5 rounded font-black uppercase bg-zinc-800 text-zinc-300 border border-zinc-700">
                ACTIVE
              </span>
            )}
          </div>
        </td>

        {/* Col 2: Symbol & Contract Details */}
        <td className="py-2.5 px-3 min-w-[150px]">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-black text-sm text-text leading-none tracking-tight">{alert.symbol}</span>
              {strikeNum && !isFuture && (
                <span className="text-[11px] font-black text-gold font-mono leading-none bg-gold/10 px-1.5 py-0.5 rounded border border-gold/30">
                  {currSym}{Number(strikeNum).toLocaleString(isCrypto ? 'en-US' : 'en-IN')}
                </span>
              )}
              {optType && !isFuture && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-black uppercase ${
                  optType === 'CE' ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40' : 'bg-rose-500/25 text-rose-300 border border-rose-500/40'
                }`}>{optType}</span>
              )}
            </div>

            {/* Expiry & Contract Details */}
            <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
              {expiryInfo?.fullDisplay && (
                <span
                  className={`text-[10px] font-mono px-1.5 py-px rounded font-bold whitespace-nowrap border ${
                    expiryInfo.isWeekly
                      ? 'bg-amber-500/15 text-amber-300 border-amber-500/35'
                      : 'bg-blue-500/15 text-blue-300 border-blue-500/35'
                  }`}
                  title={`Contract Expiry: ${expiryInfo.formatted || expiryInfo.fullDisplay} · Institutional Derivative Cycle`}
                >
                  {expiryInfo.fullDisplay}
                </span>
              )}
              {isDerivative && spotNum && (
                <span className="text-[10px] font-mono text-muted">
                  Spot {currSym}{Number(spotNum).toLocaleString(isCrypto ? 'en-US' : 'en-IN', { maximumFractionDigits: isCrypto ? 2 : 0 })}
                </span>
              )}
            </div>
          </div>
        </td>

        {/* Col 3: Bias / Direction */}
        <td className="py-2.5 px-3 whitespace-nowrap">
          <span className={`text-[10px] font-black px-2 py-1 rounded border tracking-wider inline-flex items-center gap-1 ${
            isBull ? 'text-emerald-300 bg-emerald-500/20 border-emerald-500/40' :
            isNeutral ? 'text-purple-300 bg-purple-500/20 border-purple-500/40' :
            'text-rose-300 bg-rose-500/20 border-rose-500/40'
          }`}>
            {isBull ? '▲ LONG' : isNeutral ? '◆ NEUTRAL' : '▼ SHORT'}
          </span>
        </td>

        {/* Col 4: Live Price (LTP) & Return Pill */}
        <td className="py-2.5 px-3 whitespace-nowrap tabular-nums">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-black font-mono leading-none ${
              isDerivative
                ? (liveContract?.flash === 'up' ? 'text-emerald-400' : liveContract?.flash === 'down' ? 'text-rose-400' : 'text-gold')
                : (liveSpot?.flash === 'up' ? 'text-emerald-400' : liveSpot?.flash === 'down' ? 'text-rose-400' : 'text-text')
            }`}>
              {currSym}{fmtP(currentPrice)}
              {isDerivative && liveContract?.ltp ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-1 align-middle" /> : null}
            </span>

            {liveReturnPct !== null && (
              <span className={`px-2 py-0.5 rounded text-[11px] font-black font-mono border whitespace-nowrap ${
                isProfitable
                  ? 'bg-emerald-500/25 text-emerald-300 border-emerald-500/50'
                  : 'bg-rose-500/25 text-rose-300 border-rose-500/50'
              }`}>
                {isProfitable ? '+' : ''}{liveReturnPct}%
              </span>
            )}
          </div>
        </td>

        {/* Col 5: Actionable Execution Levels (Entry, SL, T1, T2) */}
        <td className="py-2.5 px-3 whitespace-nowrap font-mono tabular-nums text-[11px]">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              {entryNum && <span className="text-gold font-bold">Entry {currSym}{fmtP(entryNum)}</span>}
              {slNum && (
                <span className={`font-bold px-1.5 py-0.5 rounded ${isSLHit ? 'bg-rose-500/25 text-rose-300 border border-rose-500/50' : 'text-rose-400'}`}>
                  {isSLHit ? '🛑 SL ' : 'SL '}{currSym}{fmtP(slNum)}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {t1Num && (
                <span className={`font-bold px-1.5 py-0.5 rounded ${isT1Hit ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/50' : 'text-emerald-400'}`}>
                  {isT1Hit ? '✅ T1 ' : 'T1 '}{currSym}{fmtP(t1Num)}
                </span>
              )}
              {t2Num && (
                <span className={`font-bold px-1.5 py-0.5 rounded ${isT2Hit ? 'bg-cyan-500/25 text-cyan-200 border border-cyan-500/50' : 'text-cyan-400'}`}>
                  {isT2Hit ? '✅ T2 ' : 'T2 '}{currSym}{fmtP(t2Num)}
                </span>
              )}
              {(alert.actionable_plan?.trade_plan?.rr_ratio || alert.metrics?.rr_ratio) && (
                <span className="text-muted font-sans font-bold text-[10px]">
                  R:R 1:{(alert.actionable_plan?.trade_plan?.rr_ratio || alert.metrics?.rr_ratio || 0).toFixed(1)}
                </span>
              )}
            </div>
          </div>
        </td>

        {/* Col 6: Conviction & Regimes */}
        <td className="py-2.5 px-3 whitespace-nowrap">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-bold text-[11px] text-zinc-200">
                {conviction}%
              </span>

              {convictionTier === 'APEX_CONFLUENCE' && (
                <span
                  className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/25 text-amber-300 border border-amber-500/50 shadow-sm"
                  title="Apex Confluence · Technical, volume, and smart money momentum align with >=90% conviction · Full position sizing eligible"
                >
                  💎 APEX
                </span>
              )}
              {convictionTier === 'HIGH_CONVICTION' && (
                <span
                  className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                  title="High Conviction · Conviction 80–89% with confirmed order flow · Standard trade allocation permitted"
                >
                  ⚡ HIGH
                </span>
              )}
              {convictionTier === 'DEFINED_RISK_ONLY' && (
                <span
                  className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-indigo-500/20 text-indigo-300 border border-indigo-500/40"
                  title="Defined-Risk Mandate · Conviction 70–79% or elevated IV · Mandates vertical spread to eliminate naked exposure"
                >
                  🛡️ SPREAD
                </span>
              )}
            </div>

            {/* Confluence & Horizon */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {confluenceAlignment === 'TRIPLE_HORIZON' && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/25 text-amber-300 border border-amber-400/50"
                  title="Triple-Horizon Confluence · Intraday + Swing + Multibagger all mutually aligned in trend and volume structure"
                >
                  👑 TRIPLE
                </span>
              )}
              {horizonInfo && (
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase whitespace-nowrap border ${horizonInfo.badgeClasses}`}
                  title={horizonInfo.tooltip}
                >
                  {horizonInfo.shortLabel}
                </span>
              )}
            </div>
          </div>
        </td>

        {/* Col 7: Risk Sentinels & Liquidity */}
        <td className="py-2.5 px-3 min-w-[130px]">
          <div className="flex items-center gap-1 flex-wrap">
            {gapRisk === 'GAP_OVER_SL' && (
              <span
                className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/25 text-rose-300 border border-rose-500/50 animate-pulse"
                title="Gap Over SL Sentinel · Opening price gapped beyond invalidation stop-loss · Setup disqualified"
              >
                🛑 GAP OVER SL
              </span>
            )}
            {gapRisk === 'GAP_NO_CHASE' && (
              <span
                className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/25 text-amber-300 border border-amber-500/50"
                title="No-Chase Sentinel · Price exceeded entry threshold · Wait for retracement"
              >
                ⚠️ NO CHASE
              </span>
            )}
            {stagnationWarning && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/20 text-amber-300 border border-amber-500/40"
                title="Stagnation Sentinel · Consolidated in chop without reaching T1 (+2R) · Breakeven trailing stop active"
              >
                ⏳ STAGNANT
              </span>
            )}
            {physicalRisk && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/25 text-rose-300 border border-rose-500/50"
                title="SEBI Physical Settlement Alert · In-the-money contract within 4 days of expiry · Escalating margin penalties"
              >
                ⚠️ PHYSICAL
              </span>
            )}
            {isWideSpread && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/20 text-amber-300 border border-amber-500/40"
                title={`Wide Spread: ${spreadPct ? spreadPct.toFixed(1) + '%' : '>2%'} · Limit execution enforced`}
              >
                ⚠️ WIDE {spreadPct ? `${spreadPct.toFixed(1)}%` : ''}
              </span>
            )}
            {alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2' ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap" title="Live Level 2 Feed · Real-time broker depth active">
                🟢 LIVE L2
              </span>
            ) : null}

            {/* Strike Roll CTA */}
            {isStrikeRollEligible && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  if (onTrade) onTrade({ ...alert, _isStrikeRoll: true, _rollRecommendation: rollRec })
                }}
                className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 hover:bg-indigo-500/30 transition-all flex items-center gap-1 shadow-sm"
                title={`Strike Rollover Opportunity: Delta ${rollRec.current_delta?.toFixed(2) || '0.70+'} deep ITM. Roll to ₹${rollRec.recommended_strike} to extract profit.`}
              >
                <span>🔄</span>
                <span>Roll Strike</span>
              </button>
            )}
          </div>
        </td>

        {/* Col 8: 1-Click Execution CTAs */}
        <td className="py-2.5 px-3 whitespace-nowrap text-right" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-end gap-1.5">
            <button
              onClick={() => onTrade(alert)}
              className="btn btn-xs text-[10px] px-2.5 py-1 font-bold text-emerald-300 hover:text-emerald-100 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 hover:border-emerald-500/60 transition-all rounded shadow-sm"
              title="1-Click Trade: Open pre-populated Order Ticket"
            >⚡ Trade</button>

            {onSendTelegram && (
              <button
                onClick={() => onSendTelegram(alert)}
                className="btn btn-xs text-[10px] px-2 py-1 font-bold text-sky-300 hover:text-sky-100 bg-sky-500/15 hover:bg-sky-500/25 border border-sky-500/40 transition-all rounded"
                title="Dispatch Alert to Telegram"
              >↗ TG</button>
            )}

            {onDismiss && (
              <button
                onClick={() => onDismiss(alert.alert_id || alert.id || alert.symbol)}
                className="btn btn-xs text-[10px] px-2 py-1 font-bold text-muted hover:text-rose-400 bg-surface/60 hover:bg-rose-500/20 border border-border/50 hover:border-rose-500/40 transition-all rounded"
                title="Dismiss / Remove this alert"
              >✕</button>
            )}
          </div>
        </td>
      </tr>

      {/* Optional In-Place Expanded Detail View */}
      {isExpanded && (
        <tr className="bg-surface/90 border-b border-border/50">
          <td colSpan={8} className="p-3">
            <div className="p-3 bg-panel/70 rounded-xl border border-border/40 text-xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-gold">Actionable Trade Plan · {alert.symbol}</span>
                <span className="text-muted text-[11px] font-mono">ID: {alert.alert_id || alert.id}</span>
              </div>
              <p className="text-zinc-300 text-[11px] font-sans">{alert.headline || alert.summary}</p>
              {alert.reasoning && (
                <div className="text-[11px] text-muted italic border-l-2 border-gold/40 pl-2">
                  {alert.reasoning}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
})

/**
 * Institutional High-Density Quant Table for ChanakyaTrade.
 * Provides sortable columns, Bloomberg-grade monospace alignment, live price ticks, and 1-click execution.
 */
export const AlertTableView = memo(function AlertTableView({
  alerts = [],
  items = [],
  onTrade,
  onSendTelegram,
  onDismiss,
  onAnalyze,
  selectedAlertId,
  onSelectAlert,
}) {
  const [sortField, setSortField] = useState('TIME')
  const [sortAsc, setSortAsc] = useState(false)

  // Unify alerts input (handles both raw alerts array and { alert, history } array)
  const alertList = useMemo(() => {
    if (items && items.length > 0) {
      return items.map((x) => x.alert || x)
    }
    return alerts
  }, [items, alerts])

  const handleSort = (field) => {
    if (sortField === field) {
      setSortAsc((prev) => !prev)
    } else {
      setSortField(field)
      // For numerical metrics like Conviction, LTP, RR, default to descending (highest first)
      // For alphabetical like Symbol, Stage, default to ascending (A-Z)
      setSortAsc(field === 'SYMBOL' || field === 'STAGE')
    }
  }

  const sortedAlerts = useMemo(() => {
    return [...alertList].sort((a, b) => {
      let valA, valB

      switch (sortField) {
        case 'SYMBOL':
          valA = a.symbol || ''
          valB = b.symbol || ''
          return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA)
        case 'CONVICTION':
          valA = a.confidence || 0
          valB = b.confidence || 0
          return sortAsc ? valA - valB : valB - valA
        case 'RR_RATIO':
          valA = a.actionable_plan?.trade_plan?.rr_ratio || a.metrics?.rr_ratio || 0
          valB = b.actionable_plan?.trade_plan?.rr_ratio || b.metrics?.rr_ratio || 0
          return sortAsc ? valA - valB : valB - valA
        case 'LTP':
          valA = a.ltp || a.trigger_level || 0
          valB = b.ltp || b.trigger_level || 0
          return sortAsc ? valA - valB : valB - valA
        case 'STAGE':
          valA = a.stage || ''
          valB = b.stage || ''
          return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA)
        case 'TIME':
        default: {
          valA = a.created_at || a.timestamp || null
          valB = b.created_at || b.timestamp || null
          if (!valA && !valB) return 0
          if (!valA) return 1
          if (!valB) return -1
          return sortAsc ? (valA > valB ? 1 : -1) : (valB > valA ? 1 : -1)
        }
      }
    })
  }, [alertList, sortField, sortAsc])

  if (!alertList || alertList.length === 0) {
    return null
  }

  const getSortIcon = (field) => {
    if (sortField !== field) return '↕'
    return sortAsc ? '↑' : '↓'
  }

  return (
    <div className="w-full overflow-x-auto rounded-xl border border-border/50 bg-panel shadow-md">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-surface/90 border-b border-border text-[11px] font-black uppercase text-muted tracking-wider">
            <th
              onClick={() => handleSort('STAGE')}
              className="py-2.5 px-3 cursor-pointer hover:text-text select-none whitespace-nowrap"
            >
              Stage {getSortIcon('STAGE')}
            </th>
            <th
              onClick={() => handleSort('SYMBOL')}
              className="py-2.5 px-3 cursor-pointer hover:text-text select-none whitespace-nowrap"
            >
              Symbol & Contract {getSortIcon('SYMBOL')}
            </th>
            <th className="py-2.5 px-3 whitespace-nowrap">
              Direction
            </th>
            <th
              onClick={() => handleSort('LTP')}
              className="py-2.5 px-3 cursor-pointer hover:text-text select-none whitespace-nowrap"
            >
              LTP & Return {getSortIcon('LTP')}
            </th>
            <th
              onClick={() => handleSort('RR_RATIO')}
              className="py-2.5 px-3 cursor-pointer hover:text-text select-none whitespace-nowrap"
            >
              Blueprint (Entry/SL/T1) {getSortIcon('RR_RATIO')}
            </th>
            <th
              onClick={() => handleSort('CONVICTION')}
              className="py-2.5 px-3 cursor-pointer hover:text-text select-none whitespace-nowrap"
            >
              Conviction & Regimes {getSortIcon('CONVICTION')}
            </th>
            <th className="py-2.5 px-3 whitespace-nowrap">
              Sentinels & Liquidity
            </th>
            <th className="py-2.5 px-3 text-right whitespace-nowrap">
              Execution CTAs
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedAlerts.map((alt) => {
            const key = alt.alert_id || alt.id || alt.symbol
            const isSelected = selectedAlertId === key

            return (
              <AlertTableRow
                key={key}
                alert={alt}
                onTrade={onTrade}
                onSendTelegram={onSendTelegram}
                onDismiss={onDismiss}
                onAnalyze={onAnalyze}
                isSelected={isSelected}
                onSelect={onSelectAlert}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
})
