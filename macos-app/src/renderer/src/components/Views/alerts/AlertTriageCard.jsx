import React, { memo, useMemo } from 'react'
import { useLiveSpot } from './LiveSpotsContext'
import { AUTO_TYPE_STYLE, formatExpiryDetails, resolveAlertLifecycle, isTestOrSimAlert } from './alertHelpers'

export const AlertTriageCard = memo(function AlertTriageCard({
  alert,
  isSelected,
  onSelect,
  onTrade,
  onAnalyze,
  onSendTelegram,
  onDismiss,
}) {
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
    entryNum,
    slNum,
    t1Num,
    t2Num,
    t3Num,
    currentPrice,
    spotNum,
    liveReturn,
    stagePill,
    isTimeStop,
    isSLHit,
    isExpired,
    isInvalidated,
    isT3Hit,
    isT2Hit,
    isT1Hit,
    isTrail,
    isEarly,
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
  const stagnationWarning = alert.stagnation_warning || alert.metadata?.stagnation_warning || null
  const physicalRisk = alert.physical_delivery_risk || alert.metadata?.physical_delivery_risk || null
  const gapRisk = alert.premarket_gap_risk || alert.metadata?.premarket_gap_risk || null

  return (
    <article
      onClick={onSelect}
      className={`rounded-xl p-3 transition-all duration-150 cursor-pointer text-xs space-y-2 ${
        isSelected
          ? 'bg-surface border-l-4 border-l-gold border-y border-r border-gold/40 shadow-lg ring-1 ring-gold/25'
          : isSLHit
          ? 'bg-panel/50 hover:bg-surface/60 border border-rose-500/40 hover:border-rose-500/60 opacity-80'
          : isExpired || isInvalidated
          ? 'bg-panel/40 hover:bg-surface/50 border border-border/40 opacity-75'
          : 'bg-panel hover:bg-surface/80 border border-border/50 hover:border-border shadow-sm'
      }`}
    >
      {/* Row 1: Primary Header - Symbol, Strike/Expiry, Direction, and Prominent Live Price/Return */}
      <div className="flex items-center justify-between gap-2 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
          <span className="text-sm">
            {stagePill?.icon || style.icon}
          </span>
          <span className="font-black text-sm text-text leading-none tracking-tight">{alert.symbol}</span>
          
          {strikeNum && !isFuture && (
            <span className="text-[11px] font-black text-gold font-mono leading-none bg-gold/10 px-1.5 py-0.5 rounded border border-gold/30">
              {currSym}{Number(strikeNum).toLocaleString(isCrypto ? 'en-US' : 'en-IN')}
            </span>
          )}
          {optType && !isFuture && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-black uppercase tracking-wider ${
              optType === 'CE' ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40' : 'bg-rose-500/25 text-rose-300 border border-rose-500/40'
            }`}>{optType}</span>
          )}

          <span className={`text-[10px] font-black px-2 py-0.5 rounded border tracking-wide ${
            isBull ? 'text-emerald-300 bg-emerald-500/20 border-emerald-500/40' :
            isNeutral ? 'text-purple-300 bg-purple-500/20 border-purple-500/40' :
            'text-rose-300 bg-rose-500/20 border-rose-500/40'
          }`}>
            {isBull ? '▲ LONG' : isNeutral ? '◆ NEUTRAL' : '▼ SHORT'}
          </span>

          {/* Real-time Expiry Badge: Weekly vs Monthly */}
          {expiryInfo?.fullDisplay && (
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold whitespace-nowrap border ${
                expiryInfo.isWeekly
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-blue-500/20 text-blue-300 border-blue-500/40'
              }`}
              title={`Contract Expiry: ${expiryInfo.formatted || expiryInfo.fullDisplay} · Institutional Derivative Cycle · Monitor theta decay & rollover windows`}
            >
              {expiryInfo.fullDisplay}
            </span>
          )}

          {/* Real-time Stage Hit Badge */}
          {stagePill && (
            <span className={`text-[10px] px-2 py-0.5 rounded font-black uppercase border whitespace-nowrap ${stagePill.cls}`}>
              {stagePill.label}
            </span>
          )}
        </div>

        {/* Live Price & Prominent Return Pill */}
        <div className="flex items-center gap-2 flex-shrink-0 text-right">
          <div className="flex flex-col items-end">
            <div className="flex items-center gap-1.5">
              <span className={`text-sm font-black font-mono leading-none ${
                isDerivative
                  ? (liveContract?.flash === 'up' ? 'text-emerald-400' : liveContract?.flash === 'down' ? 'text-rose-400' : 'text-gold')
                  : (liveSpot?.flash === 'up' ? 'text-emerald-400' : liveSpot?.flash === 'down' ? 'text-rose-400' : 'text-text')
              }`}>
                {currSym}{fmtP(currentPrice)}
                {isDerivative && liveContract?.ltp ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-1 align-middle" /> : null}
              </span>
            </div>
            {isDerivative && spotNum && (
              <span className="text-[10px] font-mono text-muted leading-none mt-1">
                Spot {currSym}{Number(spotNum).toLocaleString(isCrypto ? 'en-US' : 'en-IN', { maximumFractionDigits: isCrypto ? 2 : 0 })}
              </span>
            )}
          </div>

          {liveReturnPct !== null && (
            <span className={`px-2 py-1 rounded text-[11px] font-black font-mono border whitespace-nowrap shadow-sm ${
              isProfitable
                ? 'bg-emerald-500/25 text-emerald-300 border-emerald-500/50'
                : 'bg-rose-500/25 text-rose-300 border-rose-500/50'
            }`}>
              {isProfitable ? '+' : ''}{liveReturnPct}%
            </span>
          )}
        </div>
      </div>

      {/* Row 2: Clustered Institutional Sentinels & Badges */}
      <div className="flex items-center gap-1.5 flex-wrap min-w-0">
        {/* Conviction Tier Badge */}
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

        {/* Hedged Spread Execution Mandate */}
        {executionMandate === 'HEDGED_SPREAD_MANDATORY' && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/25 text-rose-300 border border-rose-500/50"
            title={plan.sector_concurrency_warning || plan.trap_warning || 'Hedge Mandate · Elevated gamma event or sector chop · Vertical spread required to neutralize theta decay'}
          >
            🛡️ HEDGE MANDATE
          </span>
        )}

        {/* Time Horizon & ETA Badges */}
        {horizonInfo && (
          <div className="flex items-center gap-1">
            <span
              title={`Trade Horizon: ${horizonInfo.tooltip} · Intraday/Swing regime categorization · Plan holding duration and target staging`}
              className={`text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap border cursor-help ${horizonInfo.badgeClasses}`}
            >
              {horizonInfo.icon} {horizonInfo.shortLabel}
            </span>
            <span
              title={`Target ETA: ${horizonInfo.etaFull} · Projected institutional expansion window · Scale profit into momentum surge`}
              className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase whitespace-nowrap border ${horizonInfo.etaClasses}`}
            >
              🎯 {horizonInfo.etaLabel}
            </span>
          </div>
        )}

        {/* Multi-Horizon Confluence Alignment */}
        {confluenceAlignment === 'TRIPLE_HORIZON' && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-gradient-to-r from-amber-500/25 via-emerald-500/25 to-sky-500/25 text-amber-300 border border-amber-400/50 shadow-sm"
            title="Triple-Horizon Confluence · Intraday + Swing + Multibagger all mutually aligned in trend and volume structure · Maximum institutional tailwind"
          >
            👑 TRIPLE CONFLUENCE
          </span>
        )}
        {confluenceAlignment === 'DUAL_HORIZON' && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
            title="Dual-Horizon Alignment · Multi-timeframe trend and volume confirmation across primary horizons · Favorable edge"
          >
            ⚡ DUAL CONFLUENCE
          </span>
        )}

        {/* Pre-Market Opening Gap Sentinel */}
        {gapRisk === 'GAP_OVER_SL' && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/25 text-rose-300 border border-rose-500/50 animate-pulse"
            title="Gap Over SL Sentinel · Opening price gapped beyond invalidation stop-loss · Setup disqualified, do not execute"
          >
            🛑 GAP OVER SL
          </span>
        )}
        {gapRisk === 'GAP_NO_CHASE' && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/25 text-amber-300 border border-amber-500/50"
            title="No-Chase Sentinel · Opening price exceeded entry zone · R:R ratio degraded below 1:2.5, wait for retracement"
          >
            ⚠️ NO CHASE
          </span>
        )}

        {/* Stagnation & Chop Defense Sentinel */}
        {stagnationWarning && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-amber-500/20 text-amber-300 border border-amber-500/40 cursor-help"
            title={typeof stagnationWarning === 'string' ? stagnationWarning : 'Stagnation Sentinel · Consolidated in chop without reaching T1 (+2R) · Breakeven trailing stop active'}
          >
            ⏳ STAGNANT
          </span>
        )}

        {/* SEBI Physical Settlement Risk */}
        {physicalRisk && (
          <span
            className="text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap bg-rose-500/25 text-rose-300 border border-rose-500/50 cursor-help"
            title={typeof physicalRisk === 'object' && physicalRisk.advisory ? physicalRisk.advisory : (typeof physicalRisk === 'string' ? physicalRisk : 'SEBI Physical Settlement Alert · In-the-money contract within 4 days of expiry · Escalating margin penalties active, square off or roll')}
          >
            ⚠️ PHYSICAL RISK
          </span>
        )}

        {/* Broker Depth Feed Status */}
        {alert.order_flow_signals?.live_broker_connected === false || alert.order_flow_signals?.broker_depth_status === 'SYNTHETIC_L1_DISCONNECTED' || alert.order_flow_signals?.provenance === 'SYNTHETIC_L1_DISCONNECTED' ? (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap" title="Synthetic L1 Feed · No active broker WebSocket connection · Tick fallback active, use limit orders only">
            ⚠️ SYNTHETIC L1
          </span>
        ) : (alert.order_flow_signals?.live_broker_connected || alert.order_flow_signals?.broker_depth_status === 'LIVE_L2') ? (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap" title="Live Level 2 Feed · Real-time broker depth active · Real order book imbalance confirmed">
            🟢 LIVE L2
          </span>
        ) : null}

        {/* Telegram Delivery Status */}
        {alert.telegram_dispatched ? (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-black bg-sky-500/20 text-sky-300 border border-sky-500/40 whitespace-nowrap flex items-center gap-1" title="Telegram Push Dispatched · Broadcasted to registered institutional channel · Full trade plan synchronized">
            <span>📱</span><span>TG SENT</span>
          </span>
        ) : alert.telegram_suppression_reason ? (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 whitespace-nowrap flex items-center gap-1 cursor-help" title={`Telegram Push Held: ${alert.telegram_suppression_reason}`}>
            <span>📱</span><span>TG HELD</span>
          </span>
        ) : isTestOrSimAlert(alert) ? (
          <span className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-panel text-muted border border-border/50 whitespace-nowrap" title="Terminal Simulation Only · Test or Sim mode active · Real order dispatch bypassed">
            TERMINAL
          </span>
        ) : null}

        {/* Smart Order Routing Badge */}
        {plan.execution_ticket?.smart_routing && (
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-black uppercase whitespace-nowrap border ${
              plan.execution_ticket.smart_routing.routing_mode === 'ICEBERG'
                ? 'bg-sky-500/20 text-sky-300 border-sky-500/40'
                : plan.execution_ticket.smart_routing.routing_mode === 'PASSIVE_PEG'
                ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                : 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30'
            }`}
            title={
              plan.execution_ticket.smart_routing.notes ||
              `Smart Order Routing: ${plan.execution_ticket.smart_routing.routing_mode} · Estimated spread savings: ₹${plan.execution_ticket.smart_routing.estimated_spread_savings_inr || 0}`
            }
          >
            {plan.execution_ticket.smart_routing.routing_mode === 'ICEBERG'
              ? `🧊 ICEBERG (${plan.execution_ticket.smart_routing.num_tranches}T)`
              : plan.execution_ticket.smart_routing.routing_mode === 'PASSIVE_PEG'
              ? '🎯 PASSIVE PEG'
              : '⚡ DIRECT LIMIT'}
          </span>
        )}

        {/* Liquidity Spread Warning */}
        {(alert.metrics?.liquidity_warning || plan.execution_ticket?.liquidity_warning || alert.extra_metrics?.bid_ask_spread_pct > 2.0) && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 whitespace-nowrap"
            title={alert.metrics?.liquidity_warning || 'Wide Bid-Ask Spread · Bid-ask spread exceeds 2% · Limit execution strictly enforced'}
          >
            ⚠️ SPREAD
          </span>
        )}

        {/* Detector Degradation Probation */}
        {(alert.metrics?.detector_status === 'PROBATION' || alert.metrics?.probationary_discount) && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded font-black bg-rose-500/20 text-rose-300 border border-rose-500/40 whitespace-nowrap"
            title="Detector Probation · Negative rolling expectancy detected · Algorithmic sizing discounted by 25%"
          >
            ⚠️ PROBATION
          </span>
        )}
      </div>

      {/* Row 3: Headline / Thesis */}
      <p className="text-[12px] text-zinc-300 line-clamp-2 font-sans leading-snug" title={alert.headline || alert.summary}>
        {alert.headline || alert.summary}
      </p>

      {/* Row 4: Actionable Execution Levels & 1-Click CTAs */}
      <div className="flex items-center justify-between gap-1.5 pt-2 border-t border-border/30 text-[11px] font-mono flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {entryNum && <span className="text-gold font-bold">Entry {currSym}{fmtP(entryNum)}</span>}
          {(alert.entry_range || alert.optimal_entry_range) && (
            <span
              className="text-[10px] font-mono font-bold text-amber-300 bg-amber-500/15 px-1.5 py-0.5 rounded border border-amber-500/35 whitespace-nowrap"
              title="Optimal Trade Entry (OTE) pullback range"
            >
              OTE {alert.entry_range || alert.optimal_entry_range}
            </span>
          )}
          {(levels?.no_chase_boundary || alert.no_chase_boundary) && (
            <span
              className="text-[10px] font-mono font-bold text-rose-300 bg-rose-500/15 px-1.5 py-0.5 rounded border border-rose-500/35 whitespace-nowrap"
              title={
                levels?.spot_no_chase_boundary
                  ? `No-Chase Option Limit: Entries above ${currSym}${fmtP(levels.no_chase_boundary)} disqualify setup · Spot Max: ${currSym}${fmt(levels.spot_no_chase_boundary)}`
                  : "No-Chase boundary: Entries beyond this price degrade R:R below 1:2.5"
              }
            >
              NoChase {currSym}{fmtP(levels?.no_chase_boundary || alert.no_chase_boundary)}
            </span>
          )}
          {slNum && (
            <span className={`font-bold px-1.5 py-0.5 rounded ${isSLHit ? 'bg-rose-500/25 text-rose-300 border border-rose-500/50' : 'text-rose-400'}`}>
              {isSLHit ? '🛑 SL ' : 'SL '}{currSym}{fmtP(slNum)}
            </span>
          )}
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
          {t3Num && (
            <span className={`font-bold px-1.5 py-0.5 rounded ${isT3Hit ? 'bg-purple-500/25 text-purple-200 border border-purple-500/50' : 'text-purple-400'}`}>
              {isT3Hit ? '✅ Runner ' : 'Runner '}{currSym}{fmtP(t3Num)}
            </span>
          )}
          {alert.trailing_stop && (
            <span className="font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
              Trail SL {currSym}{fmtP(alert.trailing_stop)}
            </span>
          )}
          <span className="text-muted font-sans font-semibold">· {conviction}% Conv</span>
        </div>

        {/* Action CTAs */}
        <div className="flex items-center gap-1.5 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => onTrade(alert)}
            className="btn btn-xs text-[10px] px-2.5 py-1 font-bold text-emerald-300 hover:text-emerald-100 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 hover:border-emerald-500/60 transition-all rounded shadow-sm"
            title="1-Click Trade: Open pre-populated Order Ticket"
          >⚡ Trade</button>
          <button
            onClick={() => onSendTelegram(alert)}
            className="btn btn-xs text-[10px] px-2 py-1 font-bold text-sky-300 hover:text-sky-100 bg-sky-500/15 hover:bg-sky-500/25 border border-sky-500/40 transition-all rounded"
            title="Dispatch Alert to Telegram"
          >↗ TG</button>
          {onDismiss && (
            <button
              onClick={() => onDismiss(alert.alert_id || alert.id || alert.symbol)}
              className="btn btn-xs text-[10px] px-2 py-1 font-bold text-muted hover:text-rose-400 bg-surface/60 hover:bg-rose-500/20 border border-border/50 hover:border-rose-500/40 transition-all rounded"
              title="Dismiss / Remove this alert"
            >✕</button>
          )}
        </div>
      </div>
    </article>
  )
})
