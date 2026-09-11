import React, { memo } from 'react'
import { AUTO_TYPE_STYLE, INDEX_LOT_SIZES, convictionEmoji, getStaleness } from './alertHelpers'
import { RRMiniBar, MilestoneDots } from './AlertWidgets'

export const AlertCompactRow = memo(function AlertCompactRow({ alert, onSendTelegram, onTrade, onExpand, isExpanded }) {
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const style = AUTO_TYPE_STYLE[alert.alert_type] || AUTO_TYPE_STYLE.GAMMA_BLAST
  const isBull = alert.direction === 'BULLISH'
  const isTest = alert.environment === 'TEST' || alert.is_live === false
  const isEarly = alert.stage === 'EARLY_WARNING'
  const isIgnited = alert.stage === 'IGNITED'
  const isInvalidated = alert.is_invalidated || alert.stage === 'INVALIDATED'
  const isT1 = alert.stage === 'T1_ACHIEVED' || alert.target_status === 'T1_ACHIEVED'
  const isFinalTarget = alert.stage === 'TARGET_ACHIEVED' || alert.target_status === 'TARGET_ACHIEVED'
  const isTrail = alert.stage === 'TRAILING_UPDATE'

  const optType = alert.option_type || (alert.contract_symbol?.endsWith('PE') ? 'PE' : alert.contract_symbol?.endsWith('CE') ? 'CE' : null)
  const strikeNum = alert.strike ? Number(String(alert.strike).replace(/[^0-9.-]/g, '')) : null
  const isFuture = Boolean(alert.contract_symbol?.toUpperCase().includes('FUT') || alert.derivative_type === 'FUT')
  
  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && optType) || (alert.contract_symbol && (alert.contract_symbol.endsWith('CE') || alert.contract_symbol.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM'
  const isDerivative = !isSpotSetup && Boolean(isFuture || isPureOption || (alert.exchange === 'NFO' && (optType || strikeNum || alert.contract_symbol)))

  const lotSize = isDerivative ? (alert.lot_size || alert.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null) : null

  const spotNum = alert.underlying_spot ? Number(alert.underlying_spot) : null
  const premiumNum = alert.option_premium ? Number(alert.option_premium) : (alert.ltp ? Number(alert.ltp) : null)
  const ltpNum = alert.ltp ? Number(String(alert.ltp).replace(/[^0-9.-]/g, '')) : null

  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null
  const slNum = isDerivative
    ? (optPlan?.sl_premium ? Number(optPlan.sl_premium) : (alert.option_stop_loss ? Number(alert.option_stop_loss) : (alert.stop_loss ? Number(alert.stop_loss) : null)))
    : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (alert.stop_loss ? Number(alert.stop_loss) : null))
  const entryNum = isDerivative
    ? (optPlan?.entry_premium ? Number(optPlan.entry_premium) : (premiumNum || ltpNum))
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
  const convBars = Math.round(conviction / 10)
  const reasonShort = (alert.summary || alert.headline || '').slice(0, 40)

  const stagePill = isInvalidated ? { label: '❌ INVALID', cls: 'bg-rose-500/20 text-rose-300 border-rose-500/40' }
    : isFinalTarget ? { label: '🏁 T-HIT', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' }
    : isT1 ? { label: '🎯 T1', cls: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' }
    : isTrail ? { label: '📈 TRAIL', cls: 'bg-blue-500/20 text-blue-300 border-blue-500/40' }
    : isEarly ? { label: '⏳ EARLY', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' }
    : isIgnited ? { label: '🔥 IGNITED', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 animate-pulse' }
    : { label: '🟢 ACTIVE', cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' }

  const fmt = (n, dec = 0) => n != null && !isNaN(n) ? Number(n).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : '—'
  const fmtP = (n) => n != null && !isNaN(n) ? Number(n).toLocaleString('en-IN', { minimumFractionDigits: Number(n) < 100 ? 1 : 0, maximumFractionDigits: 1 }) : '—'

  return (
    <article
      className={`rounded-xl border px-2.5 py-1.5 cursor-pointer transition-all duration-150 hover:border-gold/40 group ${isInvalidated ? 'opacity-60' : ''}`}
      style={{
        background: isExpanded ? 'var(--color-elevated)' : 'var(--color-panel)',
        borderColor: isExpanded ? style.color + '55' : style.border,
      }}
      onClick={() => onExpand()}
    >
      {/* ── Row 1: Identity + Direction + Meta badges ───────────────────── */}
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

        <MilestoneDots targetStatus={alert.target_status} stage={alert.stage} />

        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse flex-shrink-0 ml-auto" title="Live feed active" />
      </div>

      {/* ── Row 2: Price levels + Conviction + Reason + Time + Telegram ─── */}
      <div className="flex items-center gap-1.5 min-w-0 flex-wrap mt-0.5">
        {isDerivative && spotNum && (
          <span className="text-[9px] font-mono text-zinc-400 whitespace-nowrap">
            Spot <span className="text-text font-bold">₹{fmt(spotNum)}</span>
          </span>
        )}

        {isDerivative ? (
          premiumNum && (
            <span className="text-[9px] font-mono whitespace-nowrap">
              Prem <span className="text-gold font-black">₹{fmtP(premiumNum)}</span>
            </span>
          )
        ) : (
          ltpNum && (
            <span className="text-[9px] font-mono whitespace-nowrap">
              LTP <span className="text-text font-black">₹{fmt(ltpNum)}</span>
            </span>
          )
        )}

        {slNum && (
          <span className="text-[9px] font-mono text-rose-400 whitespace-nowrap font-bold">
            SL ₹{fmtP(slNum)}
          </span>
        )}

        {entryNum && (
          <span className="text-[9px] font-mono text-amber-400 whitespace-nowrap font-bold">
            Entry ₹{fmtP(entryNum)}
          </span>
        )}

        {t1Num && (
          <span className="text-[9px] font-mono whitespace-nowrap">
            <span className="text-emerald-400 font-bold">T1 ₹{fmtP(t1Num)}</span>
            {t2Num && <span className="text-cyan-400 font-bold"> T2 ₹{fmtP(t2Num)}</span>}
            {t3Num && <span className="text-purple-300 font-bold"> T3 ₹{fmtP(t3Num)}</span>}
          </span>
        )}

        <div className="w-16 flex-shrink-0 hidden sm:block">
          <RRMiniBar sl={slNum} entry={entryNum} t1={t1Num} t2={t2Num} t3={t3Num} isUpward={isBull || isDerivative} />
        </div>

        <span className="text-[9px] font-mono whitespace-nowrap" title={`Conviction: ${conviction}`}>
          {convictionEmoji(conviction)}
          <span className="text-gold font-bold ml-0.5">{conviction}</span>
          <span className="text-zinc-600">{'█'.repeat(convBars)}{'░'.repeat(10 - convBars)}</span>
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
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-sky-300 hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 hover:border-sky-500/50 transition-all"
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
            className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-indigo-300 hover:text-indigo-200 bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-500/35 hover:border-indigo-500/60 transition-all"
            title={`Option Alternative: ${optPlan?.contract_symbol || plan.option_contract} @ ₹${optPlan?.entry_premium || plan.option_entry?.replace('₹', '') || '—'} (Click to trade Option)`}
          >⚡ Opt {optPlan?.contract_symbol ? optPlan.contract_symbol.slice(-6) : (plan.option_contract ? plan.option_contract.slice(-6) : '')}</button>
        )}

        <button
          onClick={(e) => {
            e.stopPropagation()
            if (onTrade) onTrade(alert)
          }}
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-emerald-300 hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/35 hover:border-emerald-500/60 transition-all"
          title="1-Click Trade: Open pre-populated Order Ticket"
        >⚡ Trade</button>

        <span className="text-muted text-[9px] flex-shrink-0 transition-transform duration-150" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          ▼
        </span>
      </div>
    </article>
  )
})
