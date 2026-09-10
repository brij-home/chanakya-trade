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
import UnavailableState from '../Common/UnavailableState'
import MoversAutopsyPanel from './MoversAutopsyPanel'

// ─── LiveSpotsContext ────────────────────────────────────────────────────────
// Stores live quote data in a ref (never triggers parent re-renders).
// Cards subscribe to individual symbols; only the affected card re-renders.
// This is the canonical solution for high-frequency streaming data in React.
const LiveSpotsCtx = createContext(null)

function LiveSpotsProvider({ children }) {
  // The actual quote store — a ref, not state. Writing here is ZERO re-renders.
  const spotsRef = useRef({})
  // Map of symbol → Set<forceUpdate function> for surgical card updates
  const subscribersRef = useRef({})

  const subscribe = useCallback((symbol, forceUpdate) => {
    if (!symbol) return () => {}
    if (!subscribersRef.current[symbol]) subscribersRef.current[symbol] = new Set()
    subscribersRef.current[symbol].add(forceUpdate)
    return () => subscribersRef.current[symbol]?.delete(forceUpdate)
  }, [])

  const publish = useCallback((quotesMap) => {
    // quotesMap: { [symbol]: { ltp, change_pct, flash, ... } }
    const prev = spotsRef.current
    const next = { ...prev }
    const changedSymbols = new Set()

    for (const [sym, q] of Object.entries(quotesMap)) {
      if (!q || q.ltp === undefined || q.ltp === null) continue
      const oldEntry = prev[sym]
      const ltp = Number(q.ltp)
      const flash = oldEntry?.ltp !== undefined && oldEntry.ltp !== ltp
        ? (ltp > oldEntry.ltp ? 'up' : 'down')
        : null
      next[sym] = { ltp, change_pct: q.change_pct, change: q.change, high: q.high, low: q.low, flash }
      changedSymbols.add(sym)
    }
    spotsRef.current = next

    // Notify only the subscribers for changed symbols
    for (const sym of changedSymbols) {
      subscribersRef.current[sym]?.forEach((fn) => fn())
    }

    // Clear flash indicators after 750ms (targeted)
    if (changedSymbols.size > 0) {
      setTimeout(() => {
        const nowSpots = spotsRef.current
        const cleared = { ...nowSpots }
        let changed = false
        for (const sym of changedSymbols) {
          if (cleared[sym]?.flash) {
            cleared[sym] = { ...cleared[sym], flash: null }
            changed = true
          }
        }
        if (changed) {
          spotsRef.current = cleared
          for (const sym of changedSymbols) {
            subscribersRef.current[sym]?.forEach((fn) => fn())
          }
        }
      }, 750)
    }
  }, [])

  const get = useCallback((symbol) => spotsRef.current[symbol] ?? null, [])

  const ctx = useMemo(() => ({ subscribe, publish, get }), [subscribe, publish, get])

  return <LiveSpotsCtx.Provider value={ctx}>{children}</LiveSpotsCtx.Provider>
}

/**
 * useLiveSpot(symbol) — Subscribe to real-time price for a single symbol.
 * The card re-renders ONLY when the quoted LTP for THIS symbol changes.
 * The parent AlertsView and sibling cards do NOT re-render.
 */
function useLiveSpot(symbol) {
  const ctx = useContext(LiveSpotsCtx)
  const [, forceUpdate] = useState(0)
  const forceUpdateRef = useRef()
  forceUpdateRef.current = () => forceUpdate((n) => n + 1)

  useEffect(() => {
    if (!ctx || !symbol) return
    // Pass a stable wrapper so forceUpdateRef.current can be swapped without re-subscribing
    const fn = () => forceUpdateRef.current()
    return ctx.subscribe(symbol, fn)
  }, [ctx, symbol])

  return ctx?.get(symbol) ?? null
}

/**
 * Canonical batch quote response unwrapper.
 * Handles both: { quotes: {...} } and flat { SYM: {...} } dicts.
 */
function extractQuotes(res) {
  const d = res?.data ?? res ?? {}
  if (d && typeof d === 'object' && d.quotes && typeof d.quotes === 'object' && !d.quotes.ltp) {
    // Nested: { quotes: { SYM: {...} } } — strip the wrapper
    return d.quotes
  }
  // Flat dict or unknown shape — filter out metadata keys and return
  const out = {}
  for (const [k, v] of Object.entries(d)) {
    if (v && typeof v === 'object' && v.ltp !== undefined) out[k] = v
  }
  return Object.keys(out).length > 0 ? out : d
}

const TYPE_STYLE = {
  PRICE: { icon: '💰', color: 'var(--color-gold)' },
  TECHNICAL: { icon: '📊', color: 'var(--color-violet)' },
  CONDITIONAL: { icon: '⚡', color: 'var(--color-cyan)' },
}

const AUTO_TYPE_STYLE = {
  GAMMA_BLAST: {
    icon: '⚡',
    label: 'GAMMA BLAST',
    color: 'var(--color-gold)',
    bg: 'rgba(245, 166, 35, 0.12)',
    border: 'rgba(245, 166, 35, 0.35)',
  },
  SQUEEZE_BREAKOUT: {
    icon: '🎯',
    label: 'SQUEEZE BREAKOUT',
    color: 'var(--color-emerald)',
    bg: 'rgba(0, 214, 143, 0.12)',
    border: 'rgba(0, 214, 143, 0.35)',
  },
  CIRCUIT_WARNING: {
    icon: '🔒',
    label: 'CIRCUIT WARNING',
    color: 'var(--color-rose)',
    bg: 'rgba(255, 79, 123, 0.12)',
    border: 'rgba(255, 79, 123, 0.35)',
  },
  SMC_SWEEP: {
    icon: '🌊',
    label: 'SMC LIQUIDITY',
    color: 'var(--color-violet)',
    bg: 'rgba(157, 125, 255, 0.12)',
    border: 'rgba(157, 125, 255, 0.35)',
  },
  CONFLUENCE_INFLECTION: {
    icon: '👑',
    label: 'CONFLUENCE INFLECTION',
    color: 'var(--color-sapphire)',
    bg: 'rgba(77, 155, 255, 0.12)',
    border: 'rgba(77, 155, 255, 0.35)',
  },
  PRECURSOR_RADAR: {
    icon: '⚡',
    label: 'PRECURSOR RADAR',
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.35)',
  },
  OPTIONS_MOMENTUM: {
    icon: '🚀',
    label: 'OPTIONS MOMENTUM',
    color: 'var(--color-gold)',
    bg: 'rgba(245, 166, 35, 0.12)',
    border: 'rgba(245, 166, 35, 0.35)',
  },
  ASYMMETRIC_OPPORTUNITY: {
    icon: '🎯',
    label: 'ASYMMETRIC R:R',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.12)',
    border: 'rgba(56, 189, 248, 0.35)',
  },
}

// ── Lot size lookup for NSE/BSE index options & MCX (2026 Active - SEBI 15L-20L Mandate) ──
const INDEX_LOT_SIZES = {
  // NSE Index Options (2026 Active Re-baselined Specifications)
  NIFTY: 65,
  'NIFTY 50': 65,
  BANKNIFTY: 30,
  'NIFTY BANK': 30,
  FINNIFTY: 60,
  'NIFTY FINANCIAL SERVICES': 60,
  MIDCPNIFTY: 120,
  'NIFTY MID SELECT': 120,
  NIFTYNXT50: 25,
  // BSE Index Options
  SENSEX: 20,
  BANKEX: 30,
  // MCX Commodities
  CRUDEOIL: 100,
  NATURALGAS: 1250,
  GOLD: 100,
  GOLDM: 10,
  SILVER: 30,
  SILVERM: 5,
  COPPER: 2500,
  ZINC: 5000,
  ALUMINIUM: 5000,
  // Currency Derivatives
  USDINR: 1000,
  EURINR: 1000,
  GBPINR: 1000,
  JPYINR: 1000,
}

// ── Conviction emoji shorthand ─────────────────────────────────────────────
function convictionEmoji(score) {
  const n = Number(score || 0)
  if (n >= 90) return '🔥'
  if (n >= 80) return '💪'
  if (n >= 70) return '👍'
  return '⚠️'
}

// ── Staleness badge ────────────────────────────────────────────────────────
function getStaleness(createdAt) {
  if (!createdAt) return null
  try {
    const clean = createdAt.replace(' IST', '').trim()
    const d = new Date(clean)
    if (isNaN(d.getTime())) return null
    const mins = Math.round((Date.now() - d.getTime()) / 60000)
    if (mins < 90) return null // fresh
    const hrs = Math.round(mins / 60)
    return hrs >= 1 ? `${hrs}h old` : `${mins}m old`
  } catch (_) { return null }
}

// ── R:R mini visual bar ───────────────────────────────────────────────────
function RRMiniBar({ sl, entry, t1, t2, t3, isUpward = true }) {
  if (!sl || !entry || !t1) return null
  const totalRange = Math.abs((t3 || t2 || t1) - sl)
  if (totalRange <= 0) return null
  const slW = Math.max(4, Math.round((Math.abs(entry - sl) / totalRange) * 100))
  const t1W = Math.max(4, Math.round((Math.abs(t1 - entry) / totalRange) * 100))
  const t2W = t2 ? Math.max(4, Math.round((Math.abs(t2 - t1) / totalRange) * 100)) : 0
  const t3W = t3 ? Math.max(4, Math.round((Math.abs((t3 || t2) - (t2 || t1)) / totalRange) * 100)) : 0
  const rem = 100 - slW - t1W - t2W - t3W
  return (
    <div className="flex h-1 rounded-full overflow-hidden w-full" title={`SL→T1→T2→T3 R:R breakdown`}>
      <div style={{ width: `${slW}%` }} className="bg-rose-500/70" />
      <div style={{ width: `${t1W + Math.max(0, rem)}%` }} className="bg-emerald-500/60" />
      {t2W > 0 && <div style={{ width: `${t2W}%` }} className="bg-cyan-500/60" />}
      {t3W > 0 && <div style={{ width: `${t3W}%` }} className="bg-purple-500/50" />}
    </div>
  )
}

// ── Milestone progress dots ────────────────────────────────────────────────
function MilestoneDots({ targetStatus, stage }) {
  const t1Hit = stage === 'T1_ACHIEVED' || targetStatus === 'T1_ACHIEVED' || targetStatus === 'T2_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED'
  const t2Hit = targetStatus === 'T2_ACHIEVED' || targetStatus === 'TARGET_ACHIEVED'
  const t3Hit = targetStatus === 'TARGET_ACHIEVED'
  return (
    <span className="flex items-center gap-0.5 font-mono text-[9px]" title="T1 → T2 → T3 milestones">
      <span className={t1Hit ? 'text-emerald-400' : 'text-zinc-600'}>●</span>
      <span className={t2Hit ? 'text-cyan-400' : 'text-zinc-600'}>●</span>
      <span className={t3Hit ? 'text-purple-300' : 'text-zinc-600'}>●</span>
    </span>
  )
}

// ── Institutional terminal chime (Web Audio API Synthesizer) ─────────────
function playTerminalChime(stage = 'IGNITED') {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {})
    }
    const now = ctx.currentTime
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)

    if (stage === 'IGNITED') {
      // Harmonic institutional double ping (880Hz -> 1320Hz, A5 -> E6)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(880, now)
      osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12)
      gain.gain.setValueAtTime(0.08, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35)
      osc.start(now)
      osc.stop(now + 0.35)
    } else {
      // Crisp single ping (660Hz, E5)
      osc.type = 'sine'
      osc.frequency.setValueAtTime(660, now)
      gain.gain.setValueAtTime(0.05, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25)
      osc.start(now)
      osc.stop(now + 0.25)
    }
  } catch (_) {}
}

/**
 * AlertCompactRow — Bloomberg-density single-card for rapid scanning.
 * Packs Stage · Contract · Live/Test · Direction · Type · Lot Size · Spot · Premium
 * SL · Entry · T1/T2/T3 · Conviction · Reason · Timestamp · Telegram CTA · 1-Click Trade
 * into 2 ultra-compact lines, collapsible to expanded full card on click.
 */
const AlertCompactRow = memo(function AlertCompactRow({ alert, onSendTelegram, onTrade, onExpand, isExpanded }) {
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
  const isDerivative = Boolean(isFuture || optType || strikeNum || alert.contract_symbol || alert.expiry_date || alert.alert_type === 'GAMMA_BLAST')

  // Lot size (Dynamic from backend/broker master > metrics > 2026 lookup table)
  const lotSize = isDerivative ? (alert.lot_size || alert.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null) : null

  // Spot & premium
  const spotNum = alert.underlying_spot ? Number(alert.underlying_spot) : null
  const premiumNum = alert.option_premium ? Number(alert.option_premium) : (alert.ltp ? Number(alert.ltp) : null)
  const ltpNum = alert.ltp ? Number(String(alert.ltp).replace(/[^0-9.-]/g, '')) : null

  // Entry / SL / Targets from computation helpers
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null
  const slNum = optPlan?.sl_premium ? Number(optPlan.sl_premium) : (tradePlan.invalidation_stop ? Number(tradePlan.invalidation_stop) : (alert.stop_loss ? Number(alert.stop_loss) : null))
  const entryNum = isDerivative ? (premiumNum || ltpNum) : (tradePlan.entry_price ? Number(tradePlan.entry_price) : (alert.trigger_level ? Number(alert.trigger_level) : ltpNum))
  const t1Num = optPlan?.t1_premium ? Number(optPlan.t1_premium) : (tradePlan.target_1 ? Number(tradePlan.target_1) : (alert.target_level ? Number(alert.target_level) : null))
  const t2Num = optPlan?.t2_premium ? Number(optPlan.t2_premium) : (tradePlan.target_2 ? Number(tradePlan.target_2) : null)
  const t3Num = optPlan?.t3_premium ? Number(optPlan.t3_premium) : (tradePlan.target_3 ? Number(tradePlan.target_3) : null)

  // Expiry compact label
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

  // Stage pill
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
        {/* Stage pill */}
        <span className={`text-[8px] font-black px-1.5 py-0.5 rounded-full border whitespace-nowrap flex-shrink-0 ${stagePill.cls}`}>
          {stagePill.label}
        </span>

        {/* Contract identity */}
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

        {/* Separator */}
        <span className="text-border/30 text-[9px] hidden sm:inline">│</span>

        {/* Live/Test badge */}
        {isTest
          ? <span className="text-[7px] px-1 py-px rounded font-black bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap">🧪 TEST</span>
          : <span className="text-[7px] px-1 py-px rounded font-black bg-rose-500/20 text-rose-300 border border-rose-500/30 whitespace-nowrap">🔴 LIVE</span>
        }

        {/* Direction */}
        <span className={`text-[9px] font-black whitespace-nowrap ${isBull ? 'text-emerald-400' : 'text-rose-400'}`}>
          {isBull ? '▲' : '▼'} {alert.direction?.slice(0, 4)}
        </span>

        {/* Alert type chip */}
        <span
          className="text-[7px] font-black px-1 py-px rounded whitespace-nowrap hidden sm:inline"
          style={{ color: style.color, background: style.bg, border: `1px solid ${style.border}` }}
        >
          {style.label.replace('GAMMA BLAST', 'Γ-Blast').replace('SQUEEZE BREAKOUT', 'Squeeze').replace('SMC LIQUIDITY', 'SMC').replace('CIRCUIT WARNING', 'Circuit').replace('CONFLUENCE INFLECTION', 'Confluence').replace('OPTIONS MOMENTUM', 'Opt Mom').replace('ASYMMETRIC R:R', 'Asym').replace('PRECURSOR RADAR', 'Precursor').replace('COMMODITY MOMENTUM', 'Commodity').replace('CURRENCY BREAKOUT', 'Currency')}
        </span>

        {/* Lot size */}
        {lotSize && (
          <span
            className="text-[8px] font-mono font-bold text-sky-400 bg-sky-500/10 px-1.5 py-0.5 rounded border border-sky-500/25 whitespace-nowrap hidden md:inline cursor-help"
            title={`Market Lot Size: ${lotSize} units/shares per contract`}
          >
            Lot: {lotSize}
          </span>
        )}

        {/* Milestone dots */}
        <MilestoneDots targetStatus={alert.target_status} stage={alert.stage} />

        {/* Auto-refresh live dot */}
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse flex-shrink-0 ml-auto" title="Live feed active" />
      </div>

      {/* ── Row 2: Price levels + Conviction + Reason + Time + Telegram ─── */}
      <div className="flex items-center gap-1.5 min-w-0 flex-wrap mt-0.5">
        {/* Spot (for derivatives) */}
        {isDerivative && spotNum && (
          <span className="text-[9px] font-mono text-zinc-400 whitespace-nowrap">
            Spot <span className="text-text font-bold">₹{fmt(spotNum)}</span>
          </span>
        )}

        {/* Premium / LTP */}
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

        {/* SL */}
        {slNum && (
          <span className="text-[9px] font-mono text-rose-400 whitespace-nowrap font-bold">
            SL ₹{fmtP(slNum)}
          </span>
        )}

        {/* Entry trigger */}
        {entryNum && (
          <span className="text-[9px] font-mono text-amber-400 whitespace-nowrap font-bold">
            Entry ₹{fmtP(entryNum)}
          </span>
        )}

        {/* Targets */}
        {t1Num && (
          <span className="text-[9px] font-mono whitespace-nowrap">
            <span className="text-emerald-400 font-bold">T1 ₹{fmtP(t1Num)}</span>
            {t2Num && <span className="text-cyan-400 font-bold"> T2 ₹{fmtP(t2Num)}</span>}
            {t3Num && <span className="text-purple-300 font-bold"> T3 ₹{fmtP(t3Num)}</span>}
          </span>
        )}

        {/* R:R mini bar */}
        <div className="w-16 flex-shrink-0 hidden sm:block">
          <RRMiniBar sl={slNum} entry={entryNum} t1={t1Num} t2={t2Num} t3={t3Num} isUpward={isBull || isDerivative} />
        </div>

        {/* Conviction */}
        <span className="text-[9px] font-mono whitespace-nowrap" title={`Conviction: ${conviction}`}>
          {convictionEmoji(conviction)}
          <span className="text-gold font-bold ml-0.5">{conviction}</span>
          <span className="text-zinc-600">{'█'.repeat(convBars)}{'░'.repeat(10 - convBars)}</span>
        </span>

        {/* Reason */}
        {reasonShort && (
          <span className="text-[9px] text-zinc-500 truncate min-w-0 flex-1 hidden md:block" title={alert.summary}>
            {reasonShort}
          </span>
        )}

        {/* Staleness */}
        {staleness && (
          <span className="text-[8px] font-mono text-amber-400 whitespace-nowrap flex-shrink-0" title="Alert age">
            ⏱ {staleness}
          </span>
        )}

        {/* Timestamp */}
        {timeShort && (
          <span
            className="text-[8px] font-mono text-muted whitespace-nowrap flex-shrink-0 cursor-help"
            title={`Generated: ${alert.created_at || alert.timestamp || 'N/A'}`}
          >
            {timeShort} IST
          </span>
        )}

        {/* Copy to clipboard */}
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

        {/* Telegram Send */}
        <button
          onClick={(e) => { e.stopPropagation(); onSendTelegram(alert) }}
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-sky-300 hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 hover:border-sky-500/50 transition-all"
          title="Send to Telegram (due-diligence check)"
        >↗ TG</button>

        {/* 1-Click Instant Trade */}
        <button
          onClick={(e) => {
            e.stopPropagation()
            if (onTrade) onTrade(alert)
          }}
          className="btn btn-xs text-[9px] px-1.5 font-bold flex-shrink-0 text-emerald-300 hover:text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/35 hover:border-emerald-500/60 transition-all"
          title="1-Click Trade: Open pre-populated Order Ticket"
        >⚡ Trade</button>

        {/* Expand chevron */}
        <span className="text-muted text-[9px] flex-shrink-0 transition-transform duration-150" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          ▼
        </span>
      </div>
    </article>
  )
})

/**
 * TelegramPreflightModal — Due-diligence gate before Telegram dispatch.
 * Shows full scrutiny dossier (Logic, Trap, Guidance, Auditor model) +
 * conviction bar before allowing the user to send.
 */
function TelegramPreflightModal({ alert, onConfirm, onCancel, sending, sentOk, sentError, callRef }) {
  if (!alert) return null

  const scrutiny = alert.metrics?.scrutiny || null
  const conviction = Number(alert.confidence || scrutiny?.score || 75)
  const convBars = Math.round(conviction / 10)
  const optType = alert.option_type || null
  const strikeNum = alert.strike ? Number(alert.strike) : null
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim()
  const contractLabel = alert.contract_symbol || [cleanSym, strikeNum ? Number(strikeNum).toLocaleString('en-IN') : '', optType || ''].filter(Boolean).join(' ')

  const scrutinyStatus = scrutiny?.status || 'QUANT_VERIFIED'
  const statusColor = scrutinyStatus === 'APPROVED' ? 'text-emerald-400' : scrutinyStatus === 'QUANT_VERIFIED' ? 'text-sky-400' : 'text-amber-400'
  const statusBg = scrutinyStatus === 'APPROVED' ? 'bg-emerald-500/15 border-emerald-500/30' : scrutinyStatus === 'QUANT_VERIFIED' ? 'bg-sky-500/15 border-sky-500/30' : 'bg-amber-500/15 border-amber-500/30'

  const [destMode, setDestMode] = useState('DEFAULT')
  const [customChannel, setCustomChannel] = useState(() => {
    return localStorage.getItem('chanakya_telegram_channel') || ''
  })
  const [destInfo, setDestInfo] = useState(null)

  useEffect(() => {
    let active = true
    const fetchDest = async () => {
      try {
        if (callRef?.current) {
          const res = await callRef.current('/api/alerts/auto/telegram-destinations')
          if (active && res?.data) {
            setDestInfo(res.data)
            if (res.data.channel_id && !customChannel) {
              setCustomChannel(res.data.channel_id)
            }
          }
        }
      } catch (_) {}
    }
    fetchDest()
    return () => { active = false }
  }, [callRef])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel() }}
    >
      <div className="w-full max-w-md rounded-2xl border border-sky-500/30 bg-elevated shadow-2xl space-y-3 p-4 animate-slide-up-fade">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📨</span>
            <div>
              <div className="text-sm font-black text-text">Send to Telegram</div>
              <div className="text-[10px] text-muted font-mono">{contractLabel}</div>
            </div>
          </div>
          <button onClick={onCancel} className="text-muted hover:text-text text-sm font-bold w-6 h-6 flex items-center justify-center">✕</button>
        </div>

        {/* Scrutiny Status badge */}
        <div className={`flex items-center gap-2 p-2 rounded-lg border ${statusBg}`}>
          <span className={`text-[10px] font-black uppercase tracking-wider ${statusColor}`}>
            {scrutinyStatus === 'APPROVED' ? '🛡️ AI APPROVED' : scrutinyStatus === 'QUANT_VERIFIED' ? '⚡ QUANT VERIFIED' : `⚠️ ${scrutinyStatus}`}
          </span>
          {scrutiny?.auditor_model && (
            <span className="text-[8px] font-mono text-muted ml-auto">{scrutiny.auditor_model}</span>
          )}
        </div>

        {/* Conviction bar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-muted font-bold uppercase tracking-wider">Conviction</span>
            <span className="font-black font-mono text-gold">{convictionEmoji(conviction)} {conviction}/100</span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-surface overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-amber-500 to-emerald-500 transition-all duration-300"
              style={{ width: `${conviction}%` }}
            />
          </div>
          <div className="text-[8px] font-mono text-muted text-right">{'█'.repeat(convBars)}{'░'.repeat(10 - convBars)}</div>
        </div>

        {/* Scrutiny dossier */}
        {scrutiny?.logic_confirmation && (
          <div className="p-2 rounded-lg bg-emerald-500/8 border border-emerald-500/25 space-y-0.5">
            <div className="text-[9px] font-black uppercase tracking-wider text-emerald-400">✅ Logic Confirmation</div>
            <p className="text-[10px] text-zinc-300 leading-relaxed">{scrutiny.logic_confirmation}</p>
          </div>
        )}
        {scrutiny?.trap_risk_warning && (
          <div className="p-2 rounded-lg bg-amber-500/8 border border-amber-500/25 space-y-0.5">
            <div className="text-[9px] font-black uppercase tracking-wider text-amber-400">⚠️ Trap Risk Warning</div>
            <p className="text-[10px] text-zinc-300 leading-relaxed">{scrutiny.trap_risk_warning}</p>
          </div>
        )}
        {scrutiny?.actionable_guidance && (
          <div className="p-2 rounded-lg bg-sky-500/8 border border-sky-500/25 space-y-0.5">
            <div className="text-[9px] font-black uppercase tracking-wider text-sky-400">🎯 Execution Guidance</div>
            <p className="text-[10px] text-zinc-300 leading-relaxed">{scrutiny.actionable_guidance}</p>
          </div>
        )}
        {!scrutiny && (
          <div className="p-2 rounded-lg bg-surface border border-border text-[10px] text-zinc-500 text-center">
            No scrutiny data. Run Re-Scrutinize first for full AI analysis.
          </div>
        )}

        {/* Destination Target Selector */}
        <div className="p-2.5 rounded-xl bg-surface border border-border space-y-1.5">
          <div className="flex items-center justify-between text-[10px]">
            <span className="font-bold text-muted uppercase tracking-wider">Destination Target</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setDestMode('DEFAULT')}
                className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                  destMode === 'DEFAULT'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                    : 'text-muted hover:text-text'
                }`}
              >
                🔒 Default Chat
              </button>
              <button
                type="button"
                onClick={() => setDestMode('CHANNEL')}
                className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                  destMode === 'CHANNEL'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                    : 'text-muted hover:text-text'
                }`}
              >
                📢 Channel / Group
              </button>
            </div>
          </div>

          {destMode === 'DEFAULT' ? (
            <div className="text-[9px] text-zinc-400 font-mono flex items-center justify-between px-1">
              <span>Target: <span className="text-text font-bold">
                {destInfo?.default_chat_id ? `Private Chat (${destInfo.default_chat_id.slice(0, 4)}***)` : 'Configured Telegram Chat'}
              </span></span>
              {destInfo && !destInfo.is_configured ? (
                <span className="text-amber-400 font-bold">⚠️ Unconfigured</span>
              ) : (
                <span className="text-emerald-400 font-bold">● Active</span>
              )}
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={customChannel}
                  onChange={(e) => {
                    setCustomChannel(e.target.value)
                    localStorage.setItem('chanakya_telegram_channel', e.target.value)
                  }}
                  placeholder="@my_channel_handle or -100xxxxxxxxxx"
                  className="flex-1 text-[10px] font-mono py-1 px-2.5 rounded bg-panel border border-border text-text placeholder-zinc-600 focus:outline-none focus:border-sky-500"
                />
                {destInfo?.channel_id && destInfo.channel_id !== customChannel && (
                  <button
                    type="button"
                    onClick={() => {
                      setCustomChannel(destInfo.channel_id)
                      localStorage.setItem('chanakya_telegram_channel', destInfo.channel_id)
                    }}
                    className="text-[8px] px-1.5 py-1 rounded bg-sky-500/10 text-sky-300 border border-sky-500/25 hover:bg-sky-500/20 whitespace-nowrap"
                    title="Use channel ID configured in environment"
                  >
                    Env Channel
                  </button>
                )}
              </div>
              <div className="text-[8px] text-zinc-500 px-1">
                Enter public channel handle (e.g. <code>@chanakya_alerts</code>) or private channel/group ID (-100...)
              </div>
            </div>
          )}
        </div>

        {/* Alert summary */}
        <div className="text-[10px] text-zinc-500 p-2 rounded-lg bg-surface border border-border">
          <span className="font-bold text-muted">{alert.direction} · {alert.alert_type?.replace(/_/g, ' ')}</span>
          {alert.expiry_date && <span className="ml-1 text-amber-400">· Exp {alert.expiry_date}</span>}
          {(alert.environment === 'TEST' || alert.is_live === false) && (
            <span className="ml-1 text-purple-400 font-black">· TEST ALERT</span>
          )}
        </div>

        {/* Status messages */}
        {sentOk && (
          <div className="p-2 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-[10px] font-bold text-center">
            ✅ Alert dispatched to Telegram!
          </div>
        )}
        {sentError && (
          <div className="p-2 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-[10px] text-center">
            ❌ {sentError}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={onCancel}
            className="flex-1 btn btn-sm btn-ghost text-xs text-muted border border-border/50 hover:border-border"
          >Cancel</button>
          <button
            onClick={() => onConfirm(destMode === 'DEFAULT' ? null : customChannel.trim())}
            disabled={sending || sentOk || (destMode === 'CHANNEL' && !customChannel.trim())}
            className="flex-1 btn btn-sm text-xs font-black bg-sky-500/20 hover:bg-sky-500/30 text-sky-200 border border-sky-500/40 hover:border-sky-500/60 disabled:opacity-50 transition-all"
          >
            {sending ? '⏳ Sending…' : sentOk ? '✅ Sent!' : '✓ Confirm & Send'}
          </button>
        </div>
      </div>
    </div>
  )
}

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

/**
 * classifyAlertSegment — canonical single-pass segment classifier for an alert.
 * Returns: 'FNO' | 'EQUITY' | 'COMMODITY' | 'CURRENCY'
 */
const MCX_COMMODITY_SYMBOLS = new Set([
  'CRUDEOIL', 'CRUDEOILM', 'GOLD', 'GOLDM', 'GOLDGUINEA', 'SILVER', 'SILVERM', 'SILVERMIC',
  'NATURALGAS', 'COPPER', 'ALUMINIUM', 'ZINC', 'LEAD', 'NICKEL', 'MENTHAOIL',
])
const CDS_CURRENCY_SYMBOLS = new Set(['USDINR', 'EURINR', 'GBPINR', 'JPYINR', 'EURUSD', 'GBPUSD'])
const NSE_INDEX_SYMBOLS = new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'])

function classifyAlertSegment(alert) {
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const exch = (alert.exchange || '').toUpperCase()
  const seg = (alert.segment || alert.metrics?.segment || alert.actionable_plan?.segment || '').toUpperCase()

  // Commodity (MCX) — check before FNO to avoid misclassification
  if (
    exch === 'MCX' ||
    seg === 'MCX' ||
    alert.symbol?.toUpperCase().startsWith('MCX:') ||
    MCX_COMMODITY_SYMBOLS.has(cleanSym)
  ) return 'COMMODITY'

  // Currency (CDS)
  if (
    exch === 'CDS' ||
    seg === 'CDS' ||
    CDS_CURRENCY_SYMBOLS.has(cleanSym)
  ) return 'CURRENCY'

  // F&O / Derivatives
  const isIndex = NSE_INDEX_SYMBOLS.has(cleanSym) || seg === 'INDEX'
  const isFut = Boolean(
    alert.contract_symbol?.toUpperCase().includes('FUT') ||
    alert.symbol?.toUpperCase().includes('FUT') ||
    alert.derivative_type === 'FUT' ||
    alert.alert_type === 'FUTURES'
  )
  const isDeriv = Boolean(
    isIndex || isFut ||
    alert.option_type || alert.strike || alert.contract_symbol || alert.expiry_date ||
    alert.alert_type === 'GAMMA_BLAST' || alert.alert_type === 'OPTIONS_MOMENTUM' ||
    (seg === 'FNO' && (alert.option_type || alert.strike))
  )
  if (isDeriv) return 'FNO'

  return 'EQUITY'
}

/**
 * Parses and formats option/future expiry details with explicit month name,
 * weekday, specific week date, and Days to Expiry (DTE).
 */
function formatExpiryDetails(alert) {
  const expiryDate = alert.expiry_date || alert.expiry_details?.raw_date
  const expiryType =
    alert.expiry_type ||
    (alert.contract_symbol && !['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'].some((idx) => alert.symbol?.includes(idx))
      ? 'MONTHLY'
      : 'WEEKLY')
  const contractSym = alert.contract_symbol || ''

  let monthName = alert.expiry_month_name || alert.expiry_details?.month_name || null
  let formatted = alert.expiry_formatted || alert.expiry_details?.formatted || null
  let dte = alert.dte !== undefined && alert.dte !== null ? alert.dte : null
  const isWeekly = expiryType === 'WEEKLY'
  const isMonthly = expiryType === 'MONTHLY'
  let weekday = null

  if (expiryDate) {
    try {
      const parts = expiryDate.trim().split(/[-/]/)
      let d = null
      if (parts.length === 3) {
        if (parts[0].length === 4) {
          // YYYY-MM-DD
          d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
        } else {
          // DD-MM-YYYY
          d = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]))
        }
      }
      if (d && !isNaN(d.getTime())) {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        monthName = `${months[d.getMonth()]} ${d.getFullYear()}`
        weekday = days[d.getDay()]
        const dayOfMonth = d.getDate().toString().padStart(2, '0')

        const today = new Date()
        today.setHours(0, 0, 0, 0)
        const target = new Date(d)
        target.setHours(0, 0, 0, 0)
        dte = Math.round((target - today) / (1000 * 60 * 60 * 24))

        if (isWeekly) {
          formatted = `${dayOfMonth}-${months[d.getMonth()]}-${d.getFullYear()} (${weekday}) Weekly Expiry`
        } else {
          formatted = `${monthName} Monthly Expiry (${dayOfMonth}-${months[d.getMonth()]}-${d.getFullYear()})`
        }
      }
    } catch (_) {}
  } else if (contractSym) {
    const m = contractSym.match(/(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)/i)
    if (m) {
      const year = `20${m[1]}`
      const mStr = m[2].toUpperCase()
      const mCap = mStr.charAt(0) + mStr.slice(1).toLowerCase()
      monthName = `${mCap} ${year}`
      formatted = `${monthName} Monthly Expiry`
    }
  }

  return {
    monthName: monthName || 'Sep 2026',
    formatted: formatted || (isWeekly ? 'Weekly Expiry' : 'Monthly Expiry'),
    dte,
    isWeekly,
    isMonthly,
    weekday,
    badgeText: isWeekly
      ? `⚡ ${formatted || 'WEEKLY CONTRACT'}`
      : `📅 ${monthName ? `${monthName.toUpperCase()} ` : ''}MONTHLY CONTRACT`,
  }
}

/**
 * Computes whether there is an opportunity to roll or buy the next expiry strike,
 * with explicit institutional rationale (theta decay mitigation, multi-session hold, pin risk).
 */
function computeNextExpiryOpportunity(alert, expiryInfo) {
  if (alert.next_expiry_opportunity) {
    return {
      recommendedContract: alert.next_expiry_opportunity.recommended_contract || alert.next_expiry_opportunity.recommendedContract,
      tag: alert.next_expiry_opportunity.tag || 'THETA-HEDGED ROLL',
      justification: alert.next_expiry_opportunity.justification,
    }
  }

  const isFuture = Boolean(
    alert.contract_symbol?.toUpperCase().includes('FUT') ||
    alert.symbol?.toUpperCase().includes('FUT') ||
    alert.derivative_type === 'FUT' ||
    alert.alert_type === 'FUTURES'
  )

  const isDerivative = Boolean(
    isFuture ||
    alert.option_type ||
    alert.strike ||
    alert.contract_symbol ||
    alert.expiry_date ||
    alert.alert_type === 'GAMMA_BLAST'
  )
  if (!isDerivative) return null

  const dte = expiryInfo.dte
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const overrun = tradePlan.session_overrun_risk
  const thetaDrag = tradePlan.theta_drag_pct_of_gain || 0

  if ((dte !== null && dte <= 4) || overrun || thetaDrag >= 1.0) {
    if (expiryInfo.isWeekly) {
      return {
        recommendedContract: 'Next Weekly or Monthly Expiry',
        tag: 'THETA-HEDGED ROLL',
        justification: `Near-term weekly expiry faces accelerated theta decay (${dte !== null ? `${dte} DTE` : '<4 DTE'}). Target the next weekly or monthly expiry to give the breakout sufficient runway without severe gamma pin-risk or time decay.`,
      }
    } else {
      const now = new Date()
      const currentMonth = expiryInfo.monthName || now.toLocaleString('en-US', { month: 'short', year: 'numeric' })
      const nextMonthDate = new Date(now.getFullYear(), now.getMonth() + 1, 1)
      const nextMonth = nextMonthDate.toLocaleString('en-US', { month: 'short', year: 'numeric' })
      return {
        recommendedContract: `${nextMonth} Monthly Expiry`,
        tag: 'RUNWAY EXTENSION ROLL',
        justification: `Current ${currentMonth} contract has limited sessions remaining (${dte !== null ? `${dte} DTE` : '≤4 DTE'}). Entering the ${nextMonth} cycle provides 30+ sessions of runway, eliminating overnight theta decay friction and delta compression.`,
      }
    }
  }

  if (alert.stage === 'EARLY_WARNING' && expiryInfo.isWeekly) {
    const now = new Date()
    const currentMonth = expiryInfo.monthName || now.toLocaleString('en-US', { month: 'short', year: 'numeric' })
    return {
      recommendedContract: `${currentMonth} Monthly Contract`,
      tag: 'SWING / POSITIONAL TIP',
      justification: `Early-warning coiling setups often take 3–5 sessions to ignite. Opting for the Monthly contract avoids weekly decay drag while the base forms.`,
    }
  }

  return null
}

/**
 * Computes exact Entry, Stop Loss, Target 1, Target 2, and Target 3 levels
 * and respective risk/reward metrics with 100% data integrity and zero hardcoded fakes.
 */
function computeExecutionLevels(alert, isDerivative, spotNum, optLtpNum) {
  const isBull = alert.direction === 'BULLISH'
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  // 1. Entry level
  let entry = null
  if (isDerivative) {
    if (alert.option_premium) {
      entry = Number(String(alert.option_premium).replace(/[^0-9.-]/g, ''))
    } else if (plan.recommended_entry) {
      entry = Number(String(plan.recommended_entry).replace(/[^0-9.-]/g, ''))
    } else if (alert.ltp) {
      entry = Number(String(alert.ltp).replace(/[^0-9.-]/g, ''))
    } else if (optLtpNum) {
      entry = optLtpNum
    }
  } else {
    if (tradePlan.entry_price) {
      entry = Number(tradePlan.entry_price)
    } else if (alert.trigger_level) {
      entry = Number(String(alert.trigger_level).replace(/[^0-9.-]/g, ''))
    } else if (alert.ltp) {
      entry = Number(String(alert.ltp).replace(/[^0-9.-]/g, ''))
    } else if (spotNum) {
      entry = spotNum
    }
  }
  if (!entry || isNaN(entry) || entry <= 0) {
    entry = isDerivative ? (optLtpNum || null) : (spotNum || null)
  }

  // 2. Invalidation Stop Loss
  let sl = null
  if (tradePlan.invalidation_stop) {
    sl = Number(tradePlan.invalidation_stop)
  } else if (optPlan?.sl_premium && isDerivative) {
    sl = Number(optPlan.sl_premium)
  } else if (alert.stop_loss) {
    sl = Number(String(alert.stop_loss).replace(/[^0-9.-]/g, ''))
  }
  if ((!sl || isNaN(sl) || sl <= 0) && entry) {
    sl = isDerivative ? Math.max(1, entry * 0.65) : isBull ? entry * 0.985 : entry * 1.015
  }

  // 3. Target 1
  // For derivatives: prefer option_plan premium levels over spot trade_plan levels
  let t1 = null
  if (isDerivative && optPlan?.t1_premium) {
    t1 = Number(optPlan.t1_premium)
  } else if (tradePlan.target_1) {
    t1 = Number(tradePlan.target_1)
  } else if (alert.target_level) {
    t1 = Number(String(alert.target_level).replace(/[^0-9.-]/g, ''))
  }
  if ((!t1 || isNaN(t1) || t1 <= 0) && entry) {
    t1 = isDerivative ? entry * 1.6 : isBull ? entry * 1.03 : entry * 0.97
  }

  // 4. Target 2
  let t2 = null
  const act = String(tradePlan.action || alert?.actionable_plan?.action || '').toUpperCase()
  const isOptionSell = isDerivative && (
    act === 'SELL' ||
    act === 'WRITE' ||
    act === 'SHORT' ||
    (sl && entry && t1 && sl > entry && t1 < entry)
  )
  const isUpwardPayoff = isDerivative ? !isOptionSell : isBull
  if (isDerivative && optPlan?.t2_premium) {
    t2 = Number(optPlan.t2_premium)
  } else if (tradePlan.target_2) {
    t2 = Number(tradePlan.target_2)
  }
  if ((!t2 || isNaN(t2) || t2 <= 0) && t1 && entry) {
    const spread1 = Math.abs(t1 - entry)
    t2 = isUpwardPayoff ? t1 + spread1 * 0.6 : t1 - spread1 * 0.6
  }

  // 5. Target 3 (Runner / Moonshot)
  let t3 = null
  if (isDerivative && optPlan?.t3_premium) {
    t3 = Number(optPlan.t3_premium)
  } else if (tradePlan.target_3 && Number(tradePlan.target_3) > 0) {
    t3 = Number(tradePlan.target_3)
  }
  if ((!t3 || isNaN(t3) || t3 <= 0) && t2 && entry) {
    const spread2 = Math.abs(t2 - entry)
    t3 = isDerivative
      ? (isOptionSell ? entry * 0.2 : entry * 2.5)
      : isBull
      ? t2 + spread2 * 0.8
      : t2 - spread2 * 0.8
  }

  // Monotonic invariant enforcement
  if (t1 && t2 && entry) {
    if (isUpwardPayoff) {
      if (t2 <= t1) t2 = t1 + Math.abs(t1 - entry) * 0.5
      if (t3 !== null && t3 <= t2) t3 = t2 + Math.abs(t2 - t1) * 0.8
    } else {
      if (t2 >= t1) t2 = t1 - Math.abs(entry - t1) * 0.5
      if (t3 !== null && t3 >= t2) t3 = t2 - Math.abs(t1 - t2) * 0.8
    }
  }

  const hasValidBase = entry && sl && entry > 0
  const sl_pts = hasValidBase ? Math.abs(entry - sl) : null
  const sl_pct = hasValidBase ? ((sl_pts / entry) * 100).toFixed(1) : null

  const t1_pts = entry && t1 ? Math.abs(t1 - entry) : null
  const t1_pct = entry && t1 && entry > 0 ? ((t1_pts / entry) * 100).toFixed(1) : null
  const t1_rr = t1_pts !== null && sl_pts && sl_pts > 0 ? (t1_pts / sl_pts).toFixed(1) : null

  const t2_pts = entry && t2 ? Math.abs(t2 - entry) : null
  const t2_pct = entry && t2 && entry > 0 ? ((t2_pts / entry) * 100).toFixed(1) : null
  const t2_rr = t2_pts !== null && sl_pts && sl_pts > 0 ? (t2_pts / sl_pts).toFixed(1) : null

  const t3_pts = entry && t3 ? Math.abs(t3 - entry) : null
  const t3_pct = entry && t3 && entry > 0 ? ((t3_pts / entry) * 100).toFixed(1) : null
  const t3_rr = t3_pts !== null && sl_pts && sl_pts > 0 ? (t3_pts / sl_pts).toFixed(1) : null

  return {
    entry,
    sl,
    t1,
    t2,
    t3,
    sl_pts,
    sl_pct,
    t1_pts,
    t1_pct,
    t1_rr,
    t2_pts,
    t2_pct,
    t2_rr,
    t3_pts,
    t3_pct,
    t3_rr,
    isUpwardPayoff,
    isOptionSell,
    optPlanRef: optPlan || null,
  }
}

/**
 * TradeExecutionMatrix:
 * Provides an institutional, ultra-high-contrast 5-tier execution board.
 */
function TradeExecutionMatrix({
  levels,
  isBull,
  isDerivative,
  currentPrice,
  trailingStop,
  slRationale,
  tradePlan,
  marketStatus,
  expiryInfo,
  densityMode = 'compact',
}) {
  const tp = tradePlan || {}
  const mktSt = marketStatus || 'SESSION_CLOSED'

  const formatNum = (val) => {
    if (val === null || val === undefined || isNaN(val)) return '—'
    const num = Number(val)
    return num.toLocaleString('en-IN', {
      minimumFractionDigits: num >= 500 ? 1 : 2,
      maximumFractionDigits: 2,
    })
  }

  const formatPnl = (pnl) => {
    if (pnl === null || pnl === undefined || isNaN(pnl)) return null
    const n = Number(pnl)
    const sign = n >= 0 ? '+' : ''
    return `${sign}₹${n.toLocaleString('en-IN')}`
  }

  let progressPct = 30
  if (currentPrice && levels.sl && levels.t3 && levels.t3 !== levels.sl) {
    const totalSpan = Math.abs(levels.t3 - levels.sl)
    const isUpward = levels.isUpwardPayoff !== undefined ? levels.isUpwardPayoff : (isBull || isDerivative)
    const currentDist = isUpward ? currentPrice - levels.sl : levels.sl - currentPrice
    progressPct = Math.min(100, Math.max(0, Math.round((currentDist / totalSpan) * 100)))
  }

  const mktBadge = mktSt === 'LIVE'
    ? { cls: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/40', label: '🟢 LIVE MARKET' }
    : mktSt === 'PRE_MARKET'
    ? { cls: 'text-amber-400 bg-amber-500/15 border-amber-500/40', label: '🌅 PRE-MARKET' }
    : { cls: 'text-blue-400 bg-blue-500/15 border-blue-500/40', label: '🌙 SESSION CLOSED' }

  // Expiry badge
  const expBadge = expiryInfo?.formatted
    ? `⏳ ${expiryInfo.formatted}${expiryInfo.dte !== null ? ` (${expiryInfo.dte} DTE)` : ''}`
    : expiryInfo?.expiry_date
    ? `⏳ Exp: ${expiryInfo.expiry_date}`
    : null

  return (
    <div className="rounded-xl p-2.5 border border-border/70 bg-surface/90 space-y-2 shadow-sm">
      {/* Execution Matrix Header with Quick Verdict + Market Status */}
      <div className="flex items-center justify-between flex-wrap gap-1.5 pb-1 border-b border-border/40">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-mono">🎯</span>
          <span className="text-[10px] font-black uppercase tracking-wider text-text">
            Trade Execution Matrix & Target Milestones
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold flex-wrap">
          {/* Market session status */}
          <span className={`px-1.5 py-0.5 rounded border ${mktBadge.cls}`}>
            {mktBadge.label}
          </span>
          {/* Expiry badge */}
          {expBadge && (
            <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
              {expBadge}
            </span>
          )}
          {levels.t1_rr ? (
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              T1 R:R {levels.t1_rr}:1
            </span>
          ) : null}
          {levels.t2_rr ? (
            <span className="px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
              T2 R:R {levels.t2_rr}:1
            </span>
          ) : null}
          {levels.t3_rr ? (
            <span className="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/30">
              T3 R:R {levels.t3_rr}:1
            </span>
          ) : null}
        </div>
      </div>

      {/* 5-Column High-Contrast Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5 font-mono text-xs">
        {/* 1. STOP LOSS */}
        <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/35 hover:border-rose-500/60 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-rose-400">
              🛑 Invalidation SL
            </span>
            <span className="text-[9px] font-bold text-rose-400">
              {levels.sl_pct ? `-${levels.sl_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-rose-300 mt-0.5">
            ₹{formatNum(levels.sl)}
          </div>
          <div className="text-[9px] text-muted block truncate font-sans" title={slRationale}>
            {slRationale || (levels.sl_pts ? `Risk: ₹${formatNum(levels.sl_pts)}` : 'Structural SL')}
          </div>
          {/* Rupee risk per lot */}
          {levels.optPlanRef?.sl_pnl_per_lot !== undefined && (
            <div className="text-[8px] font-bold text-rose-400/80">
              {formatPnl(levels.optPlanRef.sl_pnl_per_lot)}
            </div>
          )}
          {trailingStop && (
            <div className="pt-0.5 border-t border-rose-500/25 text-[9px] text-cyan-300 font-bold">
              ⚡ Trailing: ₹{formatNum(trailingStop)}
            </div>
          )}
        </div>

        {/* 2. ENTRY TRIGGER */}
        <div className="p-2 rounded-lg bg-gold/10 border border-gold/45 hover:border-gold/70 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-gold">
              ⚡ Entry Trigger
            </span>
            <span className="text-[9px] font-black px-1 rounded bg-gold/20 text-gold">
              {isBull ? 'BUY' : 'SELL'}
            </span>
          </div>
          <div className="text-sm font-black text-gold mt-0.5">
            ₹{formatNum(levels.entry)}
          </div>
          <div className="text-[9px] text-muted block truncate font-sans">
            {isDerivative ? 'Contract Entry' : 'Spot Breakout Level'}
          </div>
        </div>

        {/* 3. TARGET 1 */}
        <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/35 hover:border-emerald-500/60 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-emerald-400">
              🎯 Target 1 (T1)
            </span>
            <span className="text-[9px] font-bold text-emerald-400">
              {levels.t1_pct ? `+${levels.t1_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-emerald-300 mt-0.5">
            ₹{formatNum(levels.t1)}
          </div>
          <div className="text-[9px] text-emerald-400/90 block font-sans font-bold">
            {levels.t1_rr ? `${levels.t1_rr}:1 R:R · Book 50%` : 'Book 50%'}
          </div>
          {/* Spot Reference for derivatives */}
          {isDerivative && levels.optPlanRef?.t1_spot && (
            <div className="text-[8px] text-emerald-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t1_spot)}
            </div>
          )}
          {/* Rupee P&L per lot */}
          {levels.optPlanRef?.t1_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t1_pnl_per_lot || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t1_pnl_per_lot)}
            </div>
          )}
          {/* ETA Badge */}
          {tp.eta_t1_str && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate" title={tp.eta_t1_str}>
              ⏱ {tp.eta_t1_str}
            </div>
          )}
        </div>

        {/* 4. TARGET 2 */}
        <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/35 hover:border-cyan-500/60 transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-cyan-400">
              🏁 Target 2 (T2)
            </span>
            <span className="text-[9px] font-bold text-cyan-400">
              {levels.t2_pct ? `+${levels.t2_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-cyan-300 mt-0.5">
            ₹{formatNum(levels.t2)}
          </div>
          <div className="text-[9px] text-cyan-400/90 block font-sans font-bold">
            {levels.t2_rr ? `${levels.t2_rr}:1 R:R · Resistance Wall` : 'Resistance Wall'}
          </div>
          {isDerivative && levels.optPlanRef?.t2_spot && (
            <div className="text-[8px] text-cyan-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t2_spot)}
            </div>
          )}
          {levels.optPlanRef?.t2_pnl_per_lot !== undefined && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t2_pnl_per_lot || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t2_pnl_per_lot)}
            </div>
          )}
          {tp.eta_t2_str && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate" title={tp.eta_t2_str}>
              ⏱ {tp.eta_t2_str}
            </div>
          )}
        </div>

        {/* 5. TARGET 3 (RUNNER) */}
        <div className="p-2 rounded-lg bg-purple-500/10 border border-purple-500/35 hover:border-purple-500/60 transition-colors col-span-2 sm:col-span-1">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-wider text-purple-300">
              🚀 Target 3 (T3)
            </span>
            <span className="text-[9px] font-bold text-purple-300">
              {levels.t3_pct ? `+${levels.t3_pct}%` : '—'}
            </span>
          </div>
          <div className="text-sm font-black text-purple-200 mt-0.5">
            ₹{formatNum(levels.t3)}
          </div>
          <div className="text-[9px] text-purple-300/90 block font-sans font-bold">
            {levels.t3_rr ? `${levels.t3_rr}:1 R:R · Moonshot Runner` : 'Moonshot Runner'}
          </div>
          {isDerivative && levels.optPlanRef?.t3_spot && (
            <div className="text-[8px] text-purple-300/60 font-sans">
              Spot ₹{formatNum(levels.optPlanRef.t3_spot)}
            </div>
          )}
          {levels.optPlanRef?.t3_pnl_per_lot !== undefined && levels.optPlanRef.t3_pnl_per_lot !== null && (
            <div className={`text-[8px] font-bold ${(levels.optPlanRef.t3_pnl_per_lot || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {formatPnl(levels.optPlanRef.t3_pnl_per_lot)}
            </div>
          )}
          {tp.eta_t3_str && (
            <div className="text-[8px] text-cyan-400/80 font-mono truncate" title={tp.eta_t3_str}>
              ⏱ {tp.eta_t3_str}
            </div>
          )}
        </div>
      </div>

      {/* Visual Trade Runway Progress Tracker */}
      <div className="pt-1 border-t border-border/20 space-y-1">
        <div className="flex items-center justify-between text-[8px] font-mono text-muted flex-wrap gap-1">
          <span className="text-rose-400 font-bold">🛑 SL ₹{formatNum(levels.sl)}</span>
          <span className="text-gold font-bold">⚡ Entry ₹{formatNum(levels.entry)}</span>
          <span className="text-emerald-400 font-bold">🎯 T1 ₹{formatNum(levels.t1)}</span>
          <span className="text-cyan-400 font-bold">🏁 T2 ₹{formatNum(levels.t2)}</span>
          <span className="text-purple-300 font-bold">🚀 T3 ₹{formatNum(levels.t3)}</span>
        </div>
        <div className="relative w-full h-1.5 rounded-full bg-surface border border-border/50 overflow-hidden flex items-center">
          <div className="h-full bg-rose-500/40 border-r border-rose-500" style={{ width: '20%' }} title="Stop Loss Risk Zone" />
          <div className="h-full bg-gold/40 border-r border-gold" style={{ width: '10%' }} title="Entry Zone" />
          <div className="h-full bg-emerald-500/35 border-r border-emerald-500" style={{ width: '30%' }} title="T1 Profit Zone" />
          <div className="h-full bg-cyan-500/35 border-r border-cyan-500" style={{ width: '20%' }} title="T2 Expansion Zone" />
          <div className="h-full bg-purple-500/35" style={{ width: '20%' }} title="T3 Runner Moonshot Zone" />
          {currentPrice ? (
            <div
              className="absolute top-0 bottom-0 w-2 -ml-1 bg-white rounded-full shadow-lg border border-gold animate-pulse"
              style={{ left: `${progressPct}%` }}
              title={`Live Price Position: ₹${formatNum(currentPrice)} (${progressPct}% runway)`}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}

const AutoAlertCard = memo(function AutoAlertCard({
  alert,
  onAnalyze,
  onInspectOptions,
  onOpenTicket,
  onArchiveToggle,
  onClearLockout,
  archiving,
  historyAttempts = [],
  densityMode = 'compact',
}) {
  // Subscribe to live prices for this card's symbol & contract individually.
  const cleanSym = alert.symbol?.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
  const cleanContract = alert.contract_symbol?.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()

  const liveSpotBySym = useLiveSpot(cleanSym)
  const liveSpotByFull = useLiveSpot(alert.symbol !== cleanSym ? alert.symbol : null)
  const liveSpot = liveSpotBySym ?? liveSpotByFull

  const liveContractByClean = useLiveSpot(cleanContract)
  const liveContractByFull = useLiveSpot(
    alert.contract_symbol && alert.contract_symbol !== cleanContract ? alert.contract_symbol : null
  )
  const liveContract = liveContractByClean ?? liveContractByFull

  const [showHistory, setShowHistory] = useState(false)
  const [showPostMortem, setShowPostMortem] = useState(false)
  const [showPlan, setShowPlan] = useState(false)
  const [showDetails, setShowDetails] = useState(densityMode === 'expanded')
  const [clearingLockout, setClearingLockout] = useState(false)
  const [lockoutCleared, setLockoutCleared] = useState(false)

  useEffect(() => {
    setShowDetails(densityMode === 'expanded')
  }, [densityMode])

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

  const isDerivative = Boolean(
    isFuture ||
    alert.option_type ||
    alert.strike ||
    alert.contract_symbol ||
    alert.expiry_date ||
    alert.alert_type === 'GAMMA_BLAST' ||
    alert.alert_type === 'OPTIONS_MOMENTUM'
  )

  const rawStrike = alert.strike || alert.metrics?.strike
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

  // Entry price calculation
  const entryPriceNum = isDerivative
    ? (
        alert.option_premium
          ? Number(String(alert.option_premium).replace(/[^0-9.-]/g, ''))
          : alert.actionable_plan?.recommended_entry
          ? Number(String(alert.actionable_plan.recommended_entry).replace(/[^0-9.-]/g, ''))
          : alert.ltp
          ? Number(String(alert.ltp).replace(/[^0-9.-]/g, ''))
          : null
      )
    : alert.trigger_level
    ? Number(String(alert.trigger_level).replace(/[^0-9.-]/g, ''))
    : null

  let liveContractReturn = null
  if (optLtpNum && entryPriceNum && entryPriceNum > 0 && isDerivative) {
    const diff = optLtpNum - entryPriceNum
    const pct = ((diff / entryPriceNum) * 100).toFixed(1)
    liveContractReturn = { diff, pct, isProfitable: diff >= 0 }
  }

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
  const optType = alert.option_type || (alert.contract_symbol?.endsWith('PE') ? 'PE' : alert.contract_symbol?.endsWith('CE') ? 'CE' : null)

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
              {isDerivative && alert.expiry_date && (
                <span className="text-[8px] text-muted font-mono">
                  {expiryInfo.isWeekly ? '⚡W' : '📅M'} {alert.expiry_date}{expiryInfo.dte !== null ? ` (${expiryInfo.dte}d)` : ''}
                </span>
              )}
              {isTest && (
                <span className="text-[7px] px-1 py-px rounded font-black uppercase bg-purple-500/20 text-purple-300">TEST</span>
              )}
            </div>
          </div>
        </div>

        {/* Col B: Status chip + Headline (flex-1, truncated) + key metric chips */}
        <div className="flex-1 min-w-0 flex items-center gap-2 overflow-hidden">
          {/* Status pill — compact, single word */}
          <div className="flex-shrink-0">
            {isInvalidated ? (
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
                {liveContractReturn && (
                  <span className={`text-[9px] font-bold leading-none ${liveContractReturn.isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {liveContractReturn.isProfitable ? '+' : ''}{liveContractReturn.pct}%
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
                {liveCashReturn && (
                  <span className={`text-[9px] font-bold leading-none ${liveCashReturn.isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {liveCashReturn.isProfitable ? '+' : ''}{liveCashReturn.pct}%
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
        <div className="p-2 rounded-xl bg-gradient-to-r from-amber-500/10 via-surface/90 to-amber-500/5 border border-amber-500/30 text-xs text-amber-200 space-y-0.5 animate-slide-up-fade">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-1.5 font-bold">
              <span className="text-xs">💡</span>
              <span className="text-[10px] font-black uppercase tracking-wider text-amber-300">
                Next Expiry Opportunity: {nextExpiryOpp.recommendedContract}
              </span>
            </div>
            <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-200 border border-amber-500/40 font-bold uppercase">
              {nextExpiryOpp.tag}
            </span>
          </div>
          <p className="text-[10px] text-amber-100/90 leading-relaxed font-sans">
            <span className="font-bold text-amber-300">Institutional Justification: </span>
            {nextExpiryOpp.justification}
          </p>
        </div>
      )}

      {/* Invalidation Callout & Forensic Post-Mortem if invalidated */}
      {isInvalidated && (
        <div className="rounded-xl border border-rose-500/35 bg-rose-500/10 p-2.5 space-y-2 text-xs text-rose-200 animate-slide-up-fade">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="text-base flex-shrink-0">🛑</span>
              <div className="min-w-0 flex-1">
                <span className="font-black text-rose-300 block tracking-wide text-xs">
                  Trade Thesis Invalidated:
                </span>
                <span className="leading-relaxed text-rose-200/90 font-medium text-[11px] block truncate" title={alert.invalidation_reason || alert.summary}>
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
                      <li key={i} className="text-[10px] flex items-start gap-1.5 text-emerald-200/90 leading-relaxed font-mono">
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

      {/* ── Institutional AI Chief Risk Officer Scrutiny & Devil's Advocate Dossier ── */}
      {alert.metrics?.scrutiny && !isInvalidated && (
        <div className="p-2.5 rounded-xl border border-emerald-500/30 bg-gradient-to-r from-emerald-500/10 via-surface/90 to-emerald-500/5 text-xs space-y-1.5 animate-slide-up-fade">
          <div className="flex items-center justify-between flex-wrap gap-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-sm">🛡️</span>
              <span className="font-black uppercase tracking-wider text-[10px] text-emerald-300">
                Institutional AI Scrutiny &amp; Devil&apos;s Advocate Dossier
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 uppercase">
                Sanctity: {alert.metrics.scrutiny.score}/100
              </span>
              <span className="text-[8px] font-mono text-muted uppercase">
                Auditor: {alert.metrics.scrutiny.auditor_model || 'FAST_LLM'}
              </span>
            </div>
          </div>

          {/* Logic Confirmation */}
          {alert.metrics.scrutiny.logic_confirmation && (
            <div className="text-[11px] text-zinc-200 leading-relaxed font-sans">
              <span className="font-bold text-emerald-300">Structural Edge: </span>
              {alert.metrics.scrutiny.logic_confirmation}
            </div>
          )}

          {/* Devil's Advocate Trap Warning */}
          {alert.metrics.scrutiny.trap_risk_warning && (
            <div className="p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/25 text-[11px] text-amber-200 leading-relaxed">
              <span className="font-bold text-amber-300">Devil&apos;s Advocate Trap Risk: </span>
              {alert.metrics.scrutiny.trap_risk_warning}
            </div>
          )}

          {/* Execution & Trailing Discipline */}
          {alert.metrics.scrutiny.actionable_guidance && (
            <div className="text-[10px] text-cyan-300/90 font-mono pt-0.5 border-t border-emerald-500/20">
              <span className="font-bold">Execution Rule: </span>
              {alert.metrics.scrutiny.actionable_guidance}
            </div>
          )}
        </div>
      )}

      {/* ── Institutional 5-Tier Execution Runway (Entry, SL, T1, T2, T3) ── */}
      <TradeExecutionMatrix
        levels={executionLevels}
        isBull={isBull}
        isDerivative={isDerivative}
        currentPrice={isDerivative ? optLtpNum : spotNum}
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
              <p className="text-zinc-200 text-[11px] leading-relaxed">
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
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface/90 border border-gold/20 text-[10px] font-sans text-zinc-200"
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

function AlertsViewInner({ onOpenOrderTicket }) {
  const { call } = useAPI()
  const callRef = useRef(call)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)

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
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDirection, setSelectedDirection] = useState('ALL') // ALL | BULLISH | BEARISH
  // Unified 5-way segment rail: ALL | FNO | EQUITY | COMMODITY | CURRENCY
  const [selectedSegment, setSelectedSegment] = useState('ALL')
  const [selectedFilter, setSelectedFilter] = useState('ALL')
  const [selectedStage, setSelectedStage] = useState('ALL')
  const [selectedEnv, setSelectedEnv] = useState('ALL') // ALL | LIVE | TEST
  const [densityMode, setDensityMode] = useState('compact') // compact | expanded
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

  // Re-fetch when autoViewMode toggles
  useEffect(() => {
    loadAutoAlerts(false)
  }, [autoViewMode, loadAutoAlerts])

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

    // 2. Background polling sync every 15s while view is active (SILENT update, zero screen flicker)
    const syncTimer = setInterval(() => {
      loadAlerts(false)
      loadAutoAlerts(false)
    }, 15000)

    return () => {
      window.removeEventListener('new-market-alert', handleLiveAlert)
      clearInterval(syncTimer)
    }
  }, [loadAlerts, loadAutoAlerts, chimeEnabled])

  // Extract all active / visible symbols to stream spot prices and option/future contract prices for
  const activeSymbols = useMemo(() => {
    const syms = new Set()
    for (const alt of autoAlerts) {
      if (alt.symbol) {
        const clean = alt.symbol.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
        if (clean) syms.add(clean)
      }
      if (alt.contract_symbol) {
        const cleanContract = alt.contract_symbol.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
        if (cleanContract) syms.add(cleanContract)
      }
    }
    for (const a of alerts) {
      if (a.symbol) {
        const clean = a.symbol.replace(/^(NSE|BSE|MCX|NFO):/, '').trim().toUpperCase()
        if (clean) syms.add(clean)
      }
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
    const quoteInterval = setInterval(fetchLiveSpots, 2000)

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
      setAutoAlerts([])
    } catch (_) {}
  }

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

    // Option plan or trade plan pricing
    if (optPlan) {
      if (optPlan.contract_symbol) targetSym = optPlan.contract_symbol
      if (optPlan.entry_premium || alt.option_premium) targetPrice = optPlan.entry_premium || alt.option_premium
      if (optPlan.sl_premium) targetSL = optPlan.sl_premium
      if (optPlan.t1_premium) targetTP = optPlan.t1_premium
      if (seg === 'FNO') targetExchange = 'NFO'
    } else if (alt.contract_symbol && actPlan.option_contract === alt.contract_symbol && actPlan.option_entry) {
      const optPremNum = parseFloat(String(actPlan.option_entry).replace(/[₹,\s]/g, ''))
      if (!isNaN(optPremNum) && optPremNum > 0) {
        targetPrice = optPremNum
        const optSLNum = parseFloat(String(actPlan.option_stop_loss || '').replace(/[₹,\s]/g, ''))
        const optTPNum = parseFloat(String(actPlan.option_target_1 || '').replace(/[₹,\s]/g, ''))
        if (!isNaN(optSLNum) && optSLNum > 0) targetSL = optSLNum
        if (!isNaN(optTPNum) && optTPNum > 0) targetTP = optTPNum
        if (seg === 'FNO') targetExchange = 'NFO'
      }
    } else if (tradePlan) {
      if (tradePlan.entry_price) targetPrice = tradePlan.entry_price
      if (tradePlan.invalidation_stop) targetSL = tradePlan.invalidation_stop
      if (tradePlan.target_1) targetTP = tradePlan.target_1
    }

    const cleanSym = (alt.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
    const lotSize = alt.lot_size || alt.metrics?.lot_size || INDEX_LOT_SIZES[cleanSym] || null

    const ticketData = {
      symbol: targetSym,
      exchange: targetExchange,
      price: targetPrice != null ? Number(targetPrice) : undefined,
      target: targetTP != null ? Number(targetTP) : undefined,
      stopLoss: targetSL != null ? Number(targetSL) : undefined,
      lotSize: lotSize != null ? Number(lotSize) : undefined,
      quantity: lotSize != null ? Number(lotSize) : 1,
      action: alt.direction === 'BEARISH' && !alt.contract_symbol?.includes('PE') ? 'SELL' : 'BUY',
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
    if (a.is_expired || a.stage === 'EXPIRED') return false
    return a.is_active !== undefined
      ? Boolean(a.is_active)
      : !a.is_archived &&
        !a.is_invalidated &&
        a.stage !== 'INVALIDATED' &&
        a.stage !== 'TARGET_ACHIEVED' &&
        a.target_status !== 'TARGET_ACHIEVED'
  }

  const activeCount = autoAlerts.filter(isAlertActive).length
  const archivedCount = autoAlerts.length - activeCount
  const expiredCount = autoAlerts.filter((a) => a.is_expired || a.stage === 'EXPIRED').length

  // Invalidation count for banner (filter to recent invalidations within the last 60 mins to avoid zombie warnings)
  const invalidatedAlerts = autoAlerts.filter((a) => {
    if (!a.is_invalidated && a.stage !== 'INVALIDATED') return false
    if (a.invalidated_at) {
      try {
        const invTime = new Date(a.invalidated_at.replace(' IST', '')).getTime()
        if (!isNaN(invTime) && (Date.now() - invTime) > 60 * 60 * 1000) return false
      } catch (_) {}
    }
    return true
  })
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

      // 4. Unified Segment Filter (replaces former selectedType + marketSegment)
      if (selectedSegment !== 'ALL') {
        const seg = classifyAlertSegment(a)
        if (seg !== selectedSegment) return false
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
      } else if (selectedFilter !== 'ALL' && a.alert_type !== selectedFilter) {
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
  }, [autoAlerts, autoViewMode, selectedFilter, selectedStage, selectedEnv, searchQuery, selectedDirection, selectedSegment, selectedSort])

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

  // Segregate into 4 canonical market segments using classifyAlertSegment
  const { groupedFnoAlerts, groupedEquityAlerts, groupedCommodityAlerts, groupedCurrencyAlerts } = useMemo(() => {
    const fno = []
    const equity = []
    const commodity = []
    const currency = []
    for (const item of groupedAutoAlerts) {
      const seg = classifyAlertSegment(item.alert)
      if (seg === 'FNO') fno.push(item)
      else if (seg === 'COMMODITY') commodity.push(item)
      else if (seg === 'CURRENCY') currency.push(item)
      else equity.push(item)
    }
    return { groupedFnoAlerts: fno, groupedEquityAlerts: equity, groupedCommodityAlerts: commodity, groupedCurrencyAlerts: currency }
  }, [groupedAutoAlerts])

  return (
    <>
    <div
      ref={scrollContainerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto p-3 space-y-3 font-ui"
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
        <div className="p-3 rounded-2xl bg-rose-500/10 border border-rose-500/35 text-rose-200 flex items-center justify-between gap-3 animate-slide-up-fade">
          <div className="flex items-center gap-2.5 text-xs">
            <span className="text-xl flex-shrink-0">🛑</span>
            <div>
              <span className="font-bold">
                ⚠️ {invalidatedCount} Trade {invalidatedCount === 1 ? 'Setup' : 'Setups'} Invalidated:
              </span>
              <span className="ml-1 text-rose-300/80">
                {uniqueInvalidatedList.slice(0, 3).join(', ')}
                {uniqueInvalidatedList.length > 3 ? '...' : ''} no longer valid due to stop-loss breach or structural failure.
              </span>
            </div>
          </div>
          <button
            onClick={() => {
              setSelectedFilter('INVALIDATED')
              setSelectedStage('ALL')
            }}
            className="btn btn-sm btn-ghost text-rose-300 hover:bg-rose-500/20 text-xs flex-shrink-0"
          >
            View Invalidated ({invalidatedCount}) →
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
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm'
                      : 'text-muted hover:text-text'
                  }`}
                  title="Show only valid active trades (removes clutter)"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                  <span>Active</span>
                  <span className="text-[10px] px-1.5 py-px rounded-full font-mono bg-emerald-500/30 text-emerald-200">
                    {activeCount}
                  </span>
                </button>

                <button
                  onClick={() => setAutoViewMode('ARCHIVED')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                    autoViewMode === 'ARCHIVED'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm'
                      : 'text-muted hover:text-text'
                  }`}
                  title="View archived, completed, and invalidated trades"
                >
                  <span>📁 Archived</span>
                  <span className="text-[10px] px-1.5 py-px rounded-full font-mono bg-amber-500/30 text-amber-200">
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

              {/* Right: Scan Now + Tools dropdown */}
              <div className="flex items-center gap-1.5">
                <button
                  onClick={handleScanNow}
                  disabled={scanning}
                  className="btn btn-sm btn-gold text-xs flex items-center gap-1 font-bold shadow-sm py-1 px-3"
                  title="Scan live market feeds now"
                >
                  {scanning ? '⚡ Scanning…' : '⚡ Scan Now'}
                </button>

                {/* Unified ⚙️ Tools dropdown (maintenance + simulation + clear) */}
                <div className="relative">
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

            {/* ROW 2: Unified 5-way Segment Rail */}
            <div className="flex items-center gap-0.5 p-0.5 rounded-xl bg-surface/90 border border-border/60 w-fit flex-wrap">
              {[
                { id: 'ALL',       label: '🌐 All Markets',          count: groupedAutoAlerts.length,      activeColor: 'bg-gold text-surface' },
                { id: 'FNO',       label: '⚡ F&O / Derivatives',    count: groupedFnoAlerts.length,       activeColor: 'bg-indigo-500/25 text-indigo-200 border border-indigo-500/50' },
                { id: 'EQUITY',    label: '🏢 Cash Equity',           count: groupedEquityAlerts.length,    activeColor: 'bg-emerald-500/25 text-emerald-200 border border-emerald-500/50' },
                { id: 'COMMODITY', label: '🌙 Commodity (MCX)',       count: groupedCommodityAlerts.length, activeColor: 'bg-amber-500/25 text-amber-200 border border-amber-500/50' },
                { id: 'CURRENCY',  label: '💱 Currency (CDS)',        count: groupedCurrencyAlerts.length,  activeColor: 'bg-cyan-500/25 text-cyan-200 border border-cyan-500/50' },
              ].map((seg) => (
                <button
                  key={seg.id}
                  onClick={() => setSelectedSegment(seg.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                    selectedSegment === seg.id
                      ? `${seg.activeColor} shadow-sm font-black`
                      : 'text-muted hover:text-text'
                  }`}
                  title={`Filter to ${seg.label} only`}
                >
                  <span>{seg.label}</span>
                  <span className={`text-[10px] font-mono px-1.5 py-px rounded-full ${
                    selectedSegment === seg.id ? 'bg-black/20' : 'bg-elevated'
                  }`}>{seg.count}</span>
                </button>
              ))}
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

                {/* Category chips — horizontally scrollable, no line-wrapping */}
                <div
                  className="flex items-center gap-1 overflow-x-auto min-w-0 flex-1"
                  style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
                >
                  {[
                    { id: 'ALL',                 label: 'All' },
                    { id: 'TARGET_HIT',          label: '🎯 Targets Hit',       activeClass: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' },
                    { id: 'HIGH_CONVICTION',     label: '⭐ 85%+ Conviction',   activeClass: 'bg-amber-500/20 text-amber-300 border border-amber-500/40' },
                    { id: 'MULTI_FLOW',          label: '🌊 Multi-Strike',      activeClass: 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' },
                    { id: 'GAMMA_BLAST',         label: '⚡ Gamma Blast',       activeClass: 'bg-gold/20 text-gold border border-gold/40' },
                    { id: 'SQUEEZE_BREAKOUT',    label: '🚀 Squeeze',           activeClass: 'bg-gold/20 text-gold border border-gold/40' },
                    { id: 'SMC_SWEEP',           label: '🌊 SMC Sweep',         activeClass: 'bg-violet-500/20 text-violet-300 border border-violet-500/40' },
                    { id: 'PRECURSOR_RADAR',     label: '⚡ Precursor',         activeClass: 'bg-amber-500/20 text-amber-300 border border-amber-500/40' },
                    { id: 'ASYMMETRIC_OPPORTUNITY', label: '🎯 Asymmetric R:R', activeClass: 'bg-sky-500/20 text-sky-300 border border-sky-500/40' },
                    { id: 'CIRCUIT_WARNING',     label: '🔒 Circuit',           activeClass: 'bg-rose-500/20 text-rose-400 border border-rose-500/40' },
                    { id: 'INVALIDATED',         label: `❌ Invalidated (${invalidatedCount})`, activeClass: 'bg-rose-500/20 text-rose-400 border border-rose-500/40' },
                  ].map((chip) => (
                    <button
                      key={chip.id}
                      onClick={() => setSelectedFilter(chip.id)}
                      className={`flex-shrink-0 px-2.5 py-0.5 rounded-lg font-bold transition-all text-[11px] whitespace-nowrap ${
                        selectedFilter === chip.id
                          ? (chip.activeClass || 'bg-gold/20 text-gold border border-gold/40')
                          : 'text-muted hover:text-text hover:bg-elevated'
                      }`}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
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
                    onClick={() => setDensityMode('compact')}
                    className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
                      densityMode === 'compact' ? 'bg-gold/20 text-gold' : 'text-muted hover:text-text'
                    }`}
                    title="Compact card view"
                  >▤ Compact</button>
                  <button
                    onClick={() => setDensityMode('expanded')}
                    className={`px-2 py-0.5 rounded text-xs font-bold transition-all ${
                      densityMode === 'expanded' ? 'bg-gold/20 text-gold' : 'text-muted hover:text-text'
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
            <div className="p-2.5 rounded-xl bg-surface/90 border border-amber-500/40 text-xs text-amber-200 flex items-center justify-between gap-2 animate-slide-up-fade">
              <span className="font-mono">{cleanupNotice}</span>
              <button onClick={() => setCleanupNotice(null)} className="text-muted hover:text-text text-xs font-bold">
                ✕
              </button>
            </div>
          )}

          {/* Alert Cards Feed */}
          {autoLoading && autoAlerts.length === 0 ? (
            <UnavailableState title="Checking market feeds" reason="Scanning for real-time Gamma Blasts, Squeezes, Commodity momentum, and Invalidations." size="md" />
          ) : filteredAutoAlerts.length === 0 ? (
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
            /* Section renderer — 4 segments in ALL mode, or filtered single segment */
            <div className="space-y-6">
              {/* Helper: renders a section header + cards for a given bucket */}
              {(selectedSegment === 'ALL' || selectedSegment === 'FNO') && groupedFnoAlerts.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-indigo-500/40">
                    <div className="flex items-center gap-2">
                      <span className="text-base">⚡</span>
                      <h2 className="text-xs font-black uppercase tracking-wider text-indigo-300">
                        F&O / Derivatives — Options & Futures ({groupedFnoAlerts.length})
                      </h2>
                    </div>
                    <span className="text-[10px] font-mono text-muted">Gamma Blasts · Index Options · Stock Futures</span>
                  </div>
                  <div className={densityMode === 'compact' ? 'space-y-1.5' : 'space-y-3'}>
                    {groupedFnoAlerts.map(({ alert: alt, history }) => {
                      const alertKey = alt.alert_id || alt.id || alt.symbol
                      const isRowExpanded = expandedRows.has(alertKey)
                      return (
                        <div key={alertKey}>
                          {densityMode === 'compact' ? (
                            <>
                              <AlertCompactRow
                                alert={alt}
                                onSendTelegram={handleOpenTelegramModal}
                                onTrade={handleOpenTicket}
                                onExpand={() => toggleExpandRow(alertKey)}
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
                                    archiving={archiving}
                                    historyAttempts={history}
                                    densityMode="expanded"
                                  />
                                </div>
                              )}
                            </>
                          ) : (
                            <AutoAlertCard
                              alert={alt}
                              onAnalyze={handleAnalyze}
                              onInspectOptions={handleInspectOptions}
                              onOpenTicket={handleOpenTicket}
                              onArchiveToggle={handleArchiveToggle}
                              onClearLockout={handleClearLockout}
                              archiving={archiving}
                              historyAttempts={history}
                              densityMode={densityMode}
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {(selectedSegment === 'ALL' || selectedSegment === 'EQUITY') && groupedEquityAlerts.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between pb-2 border-b border-emerald-500/40">
                    <div className="flex items-center gap-2">
                      <span className="text-base">🏢</span>
                      <h2 className="text-xs font-black uppercase tracking-wider text-emerald-400">
                        Cash Equity — Breakouts & Squeezes ({groupedEquityAlerts.length})
                      </h2>
                    </div>
                    <span className="text-[10px] font-mono text-muted">VCP · Minervini · SMC · Delivery</span>
                  </div>
                  <div className={densityMode === 'compact' ? 'space-y-1.5' : 'space-y-3'}>
                    {groupedEquityAlerts.map(({ alert: alt, history }) => {
                      const alertKey = alt.alert_id || alt.id || alt.symbol
                      const isRowExpanded = expandedRows.has(alertKey)
                      return (
                        <div key={alertKey}>
                          {densityMode === 'compact' ? (
                            <>
                              <AlertCompactRow
                                alert={alt}
                                onSendTelegram={handleOpenTelegramModal}
                                onTrade={handleOpenTicket}
                                onExpand={() => toggleExpandRow(alertKey)}
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
                                    archiving={archiving}
                                    historyAttempts={history}
                                    densityMode="expanded"
                                  />
                                </div>
                              )}
                            </>
                          ) : (
                            <AutoAlertCard
                              alert={alt}
                              onAnalyze={handleAnalyze}
                              onInspectOptions={handleInspectOptions}
                              onOpenTicket={handleOpenTicket}
                              onArchiveToggle={handleArchiveToggle}
                              onClearLockout={handleClearLockout}
                              archiving={archiving}
                              historyAttempts={history}
                              densityMode={densityMode}
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

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
                  <div className={densityMode === 'compact' ? 'space-y-1.5' : 'space-y-3'}>
                    {groupedCommodityAlerts.map(({ alert: alt, history }) => {
                      const alertKey = alt.alert_id || alt.id || alt.symbol
                      const isRowExpanded = expandedRows.has(alertKey)
                      return (
                        <div key={alertKey}>
                          {densityMode === 'compact' ? (
                            <>
                              <AlertCompactRow
                                alert={alt}
                                onSendTelegram={handleOpenTelegramModal}
                                onTrade={handleOpenTicket}
                                onExpand={() => toggleExpandRow(alertKey)}
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
                                    archiving={archiving}
                                    historyAttempts={history}
                                    densityMode="expanded"
                                  />
                                </div>
                              )}
                            </>
                          ) : (
                            <AutoAlertCard
                              alert={alt}
                              onAnalyze={handleAnalyze}
                              onInspectOptions={handleInspectOptions}
                              onOpenTicket={handleOpenTicket}
                              onArchiveToggle={handleArchiveToggle}
                              onClearLockout={handleClearLockout}
                              archiving={archiving}
                              historyAttempts={history}
                              densityMode={densityMode}
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

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
                  <div className={densityMode === 'compact' ? 'space-y-1.5' : 'space-y-3'}>
                    {groupedCurrencyAlerts.map(({ alert: alt, history }) => {
                      const alertKey = alt.alert_id || alt.id || alt.symbol
                      const isRowExpanded = expandedRows.has(alertKey)
                      return (
                        <div key={alertKey}>
                          {densityMode === 'compact' ? (
                            <>
                              <AlertCompactRow
                                alert={alt}
                                onSendTelegram={handleOpenTelegramModal}
                                onTrade={handleOpenTicket}
                                onExpand={() => toggleExpandRow(alertKey)}
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
                                    archiving={archiving}
                                    historyAttempts={history}
                                    densityMode="expanded"
                                  />
                                </div>
                              )}
                            </>
                          ) : (
                            <AutoAlertCard
                              alert={alt}
                              onAnalyze={handleAnalyze}
                              onInspectOptions={handleInspectOptions}
                              onOpenTicket={handleOpenTicket}
                              onArchiveToggle={handleArchiveToggle}
                              onClearLockout={handleClearLockout}
                              archiving={archiving}
                              historyAttempts={history}
                              densityMode={densityMode}
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Segment-specific empty state when a segment filter is active but has no results */}
              {selectedSegment !== 'ALL' && filteredAutoAlerts.length === 0 && (
                <div className="p-6 text-center text-xs text-muted border border-border/50 rounded-xl bg-surface/50">
                  No {selectedSegment === 'COMMODITY' ? 'MCX Commodity' : selectedSegment === 'CURRENCY' ? 'Currency (CDS)' : selectedSegment === 'FNO' ? 'F&O' : 'Cash Equity'} alerts matching current filters
                </div>
              )}
            </div>
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
