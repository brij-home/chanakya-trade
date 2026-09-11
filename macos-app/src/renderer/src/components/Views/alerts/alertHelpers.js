/**
 * Alert constants, categorization helpers, and mathematical execution calculators.
 */

export function extractQuotes(res) {
  const d = res?.data ?? res ?? {}
  if (d && typeof d === 'object' && d.quotes && typeof d.quotes === 'object' && !d.quotes.ltp) {
    return d.quotes
  }
  const out = {}
  for (const [k, v] of Object.entries(d)) {
    if (v && typeof v === 'object' && v.ltp !== undefined) out[k] = v
  }
  return Object.keys(out).length > 0 ? out : d
}

export const TYPE_STYLE = {
  PRICE: { icon: '💰', color: 'var(--color-gold)' },
  TECHNICAL: { icon: '📊', color: 'var(--color-violet)' },
  CONDITIONAL: { icon: '⚡', color: 'var(--color-cyan)' },
}

export const AUTO_TYPE_STYLE = {
  GAMMA_BLAST: {
    icon: '⚡',
    label: 'GAMMA BLAST',
    color: 'var(--color-gold)',
    bg: 'rgba(245, 166, 35, 0.08)',
    border: 'rgba(245, 166, 35, 0.20)',
  },
  SQUEEZE_BREAKOUT: {
    icon: '🎯',
    label: 'SQUEEZE BREAKOUT',
    color: 'var(--color-emerald)',
    bg: 'rgba(0, 214, 143, 0.08)',
    border: 'rgba(0, 214, 143, 0.20)',
  },
  CIRCUIT_WARNING: {
    icon: '🔒',
    label: 'CIRCUIT WARNING',
    color: 'var(--color-rose)',
    bg: 'rgba(255, 79, 123, 0.08)',
    border: 'rgba(255, 79, 123, 0.20)',
  },
  SMC_SWEEP: {
    icon: '🌊',
    label: 'SMC LIQUIDITY',
    color: 'var(--color-violet)',
    bg: 'rgba(157, 125, 255, 0.08)',
    border: 'rgba(157, 125, 255, 0.20)',
  },
  CONFLUENCE_INFLECTION: {
    icon: '👑',
    label: 'CONFLUENCE INFLECTION',
    color: 'var(--color-sapphire)',
    bg: 'rgba(77, 155, 255, 0.08)',
    border: 'rgba(77, 155, 255, 0.20)',
  },
  PRECURSOR_RADAR: {
    icon: '⚡',
    label: 'PRECURSOR RADAR',
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.08)',
    border: 'rgba(245, 158, 11, 0.20)',
  },
  OPTIONS_MOMENTUM: {
    icon: '🚀',
    label: 'OPTIONS MOMENTUM',
    color: 'var(--color-gold)',
    bg: 'rgba(245, 166, 35, 0.08)',
    border: 'rgba(245, 166, 35, 0.20)',
  },
  ASYMMETRIC_OPPORTUNITY: {
    icon: '🎯',
    label: 'ASYMMETRIC R:R',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.08)',
    border: 'rgba(56, 189, 248, 0.20)',
  },
}

export const INDEX_LOT_SIZES = {
  NIFTY: 65,
  'NIFTY 50': 65,
  BANKNIFTY: 30,
  'NIFTY BANK': 30,
  FINNIFTY: 60,
  'NIFTY FINANCIAL SERVICES': 60,
  MIDCPNIFTY: 120,
  'NIFTY MID SELECT': 120,
  NIFTYNXT50: 25,
  SENSEX: 20,
  BANKEX: 30,
  CRUDEOIL: 100,
  NATURALGAS: 1250,
  GOLD: 100,
  GOLDM: 10,
  SILVER: 30,
  SILVERM: 5,
  COPPER: 2500,
  ZINC: 5000,
  ALUMINIUM: 5000,
  USDINR: 1000,
  EURINR: 1000,
  GBPINR: 1000,
  JPYINR: 1000,
}

export function convictionEmoji(score) {
  const n = Number(score || 0)
  if (n >= 90) return '🔥'
  if (n >= 80) return '💪'
  if (n >= 70) return '👍'
  return '⚠️'
}

export function getStaleness(createdAt) {
  if (!createdAt) return null
  try {
    const clean = createdAt.replace(' IST', '').trim()
    const d = new Date(clean)
    if (isNaN(d.getTime())) return null
    const mins = Math.round((Date.now() - d.getTime()) / 60000)
    if (mins < 90) return null
    const hrs = Math.round(mins / 60)
    return hrs >= 1 ? `${hrs}h old` : `${mins}m old`
  } catch (_) { return null }
}

export function playTerminalChime(stage = 'IGNITED') {
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
      osc.type = 'sine'
      osc.frequency.setValueAtTime(880, now)
      osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12)
      gain.gain.setValueAtTime(0.08, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35)
      osc.start(now)
      osc.stop(now + 0.35)
    } else {
      osc.type = 'sine'
      osc.frequency.setValueAtTime(660, now)
      gain.gain.setValueAtTime(0.05, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25)
      osc.start(now)
      osc.stop(now + 0.25)
    }
  } catch (_) {}
}

export const MCX_COMMODITY_SYMBOLS = new Set([
  'CRUDEOIL', 'CRUDEOILM', 'GOLD', 'GOLDM', 'GOLDGUINEA', 'SILVER', 'SILVERM', 'SILVERMIC',
  'NATURALGAS', 'COPPER', 'ALUMINIUM', 'ZINC', 'LEAD', 'NICKEL', 'MENTHAOIL',
])
export const CDS_CURRENCY_SYMBOLS = new Set(['USDINR', 'EURINR', 'GBPINR', 'JPYINR', 'EURUSD', 'GBPUSD'])
export const NSE_INDEX_SYMBOLS = new Set([
  'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX',
  'NIFTY 50', 'NIFTY BANK', 'NIFTY FINANCIAL SERVICES', 'NIFTY MID SELECT',
])

export function classifyAlertSegment(alert) {
  if (!alert) return 'EQUITY'
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const exch = (alert.exchange || '').toUpperCase()
  const seg = (alert.segment || alert.metrics?.segment || alert.actionable_plan?.segment || '').toUpperCase()

  if (seg === 'FNO_INDEX') return 'FNO_INDEX'
  if (seg === 'FNO_STOCK') return 'FNO_STOCK'

  if (
    exch === 'MCX' ||
    seg === 'MCX' ||
    seg === 'COMMODITY' ||
    alert.symbol?.toUpperCase().startsWith('MCX:') ||
    MCX_COMMODITY_SYMBOLS.has(cleanSym)
  ) return 'COMMODITY'

  if (
    exch === 'CDS' ||
    seg === 'CDS' ||
    seg === 'CURRENCY' ||
    CDS_CURRENCY_SYMBOLS.has(cleanSym)
  ) return 'CURRENCY'

  const isIndex = NSE_INDEX_SYMBOLS.has(cleanSym) || seg === 'INDEX' || cleanSym.endsWith('INDEX')
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
    (seg === 'FNO' && (alert.option_type || alert.strike || isFut)) ||
    exch === 'NFO'
  )
  if (isDeriv) {
    return isIndex ? 'FNO_INDEX' : 'FNO_STOCK'
  }

  return 'EQUITY'
}

export function formatExpiryDetails(alert) {
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
          d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
        } else {
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

export function computeNextExpiryOpportunity(alert, expiryInfo) {
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

  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM'

  const isDerivative = !isSpotSetup && Boolean(
    isFuture ||
    alert.option_type ||
    alert.strike ||
    alert.contract_symbol ||
    alert.expiry_date ||
    alert.alert_type === 'GAMMA_BLAST' ||
    alert.alert_type === 'OPTIONS_MOMENTUM'
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

export function computeExecutionLevels(alert, isDerivative, spotNum, optLtpNum) {
  const isBull = alert.direction === 'BULLISH'
  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  let entry = null
  if (isDerivative) {
    if (optPlan?.entry_premium) {
      entry = Number(optPlan.entry_premium)
    } else if (alert.option_premium) {
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

  let sl = null
  if (isDerivative) {
    if (optPlan?.sl_premium) {
      sl = Number(optPlan.sl_premium)
    } else if (alert.option_stop_loss) {
      sl = Number(String(alert.option_stop_loss).replace(/[^0-9.-]/g, ''))
    } else if (alert.stop_loss && (alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE')) {
      sl = Number(String(alert.stop_loss).replace(/[^0-9.-]/g, ''))
    }
  } else {
    if (tradePlan.invalidation_stop) {
      sl = Number(tradePlan.invalidation_stop)
    } else if (alert.stop_loss) {
      sl = Number(String(alert.stop_loss).replace(/[^0-9.-]/g, ''))
    }
  }
  if ((!sl || isNaN(sl) || sl <= 0) && entry) {
    sl = isDerivative ? Math.max(1, entry * 0.65) : isBull ? entry * 0.985 : entry * 1.015
  }

  let t1 = null
  if (isDerivative) {
    if (optPlan?.t1_premium) {
      t1 = Number(optPlan.t1_premium)
    } else if (alert.option_target_1) {
      t1 = Number(String(alert.option_target_1).replace(/[^0-9.-]/g, ''))
    } else if (alert.target_level && (alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE')) {
      t1 = Number(String(alert.target_level).replace(/[^0-9.-]/g, ''))
    }
  } else {
    if (tradePlan.target_1) {
      t1 = Number(tradePlan.target_1)
    } else if (alert.target_level) {
      t1 = Number(String(alert.target_level).replace(/[^0-9.-]/g, ''))
    }
  }
  if ((!t1 || isNaN(t1) || t1 <= 0) && entry) {
    t1 = isDerivative ? entry * 1.6 : isBull ? entry * 1.03 : entry * 0.97
  }

  let t2 = null
  const act = String(tradePlan.action || alert?.actionable_plan?.action || '').toUpperCase()
  const isOptionSell = isDerivative && (
    act === 'SELL' ||
    act === 'WRITE' ||
    act === 'SHORT' ||
    (sl && entry && t1 && sl > entry && t1 < entry)
  )
  const isUpwardPayoff = isDerivative ? !isOptionSell : isBull
  if (isDerivative) {
    if (optPlan?.t2_premium) {
      t2 = Number(optPlan.t2_premium)
    } else if (alert.option_target_2) {
      t2 = Number(String(alert.option_target_2).replace(/[^0-9.-]/g, ''))
    }
  } else if (tradePlan.target_2) {
    t2 = Number(tradePlan.target_2)
  }
  if ((!t2 || isNaN(t2) || t2 <= 0) && t1 && entry) {
    const spread1 = Math.abs(t1 - entry)
    t2 = isUpwardPayoff ? t1 + spread1 * 0.6 : t1 - spread1 * 0.6
  }

  let t3 = null
  if (isDerivative) {
    if (optPlan?.t3_premium) {
      t3 = Number(optPlan.t3_premium)
    }
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
