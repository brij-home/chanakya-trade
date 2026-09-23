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

/**
 * Institutional filter to determine if an alert is synthetic, test, simulated, or off-market demo.
 * Ensures simulated alerts never contaminate live market views and can be cleanly eradicated.
 */
export function isTestOrSimAlert(item) {
  if (!item) return false
  const sym = String(item.symbol || '').toUpperCase()
  const contract = String(item.contract_symbol || item.contract || '').toUpperCase()
  const id = String(item.id || item.alert_id || '').toLowerCase()
  const headline = String(item.headline || '').toUpperCase()
  const summary = String(item.summary || '').toUpperCase()
  const env = String(item.environment || '').toUpperCase()
  const isTestFlag = item.is_test === true || item.isTest === true || item.metrics?.is_test === true
  const isLiveFlag = item.is_live !== false && item.isLive !== false

  // 1. Explicit test flags or non-live environment
  if (isTestFlag || env === 'TEST' || env === 'SIMULATE' || env === 'DEMO' || !isLiveFlag) return true
  if (id.startsWith('test-') || id.startsWith('sim-')) return true

  // 2. Headline / summary containing test indicators
  if (headline.includes('[TEST]') || headline.includes('🧪') || headline.includes('SIMULAT') || headline.includes('TEST ALERT')) return true
  if (summary.includes('SIMULAT') || summary.includes('TEST ALERT') || summary.includes('TEST MODE')) return true

  // 3. Known synthetic/mock test phrases from unit tests
  if (id.startsWith('mock-') || id.startsWith('synthetic-')) return true
  if (headline.includes('SYNTHETIC TEST') || summary.includes('SYNTHETIC TEST')) return true

  return false
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
  SQUEEZE_BREAKDOWN: {
    icon: '🔻',
    label: 'SQUEEZE BREAKDOWN',
    color: 'var(--color-rose)',
    bg: 'rgba(255, 79, 123, 0.08)',
    border: 'rgba(255, 79, 123, 0.20)',
  },
  PATTERN_COILING: {
    icon: '🌀',
    label: 'PATTERN COILING',
    color: 'var(--color-cyan)',
    bg: 'rgba(0, 209, 255, 0.08)',
    border: 'rgba(0, 209, 255, 0.20)',
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
  OPTION_WRITE: {
    icon: '🛡️',
    label: 'OPTION WRITE',
    color: '#a855f7',
    bg: 'rgba(168, 85, 247, 0.08)',
    border: 'rgba(168, 85, 247, 0.20)',
  },
  ASYMMETRIC_OPPORTUNITY: {
    icon: '🎯',
    label: 'ASYMMETRIC R:R',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.08)',
    border: 'rgba(56, 189, 248, 0.20)',
  },
  TURTLE_SOUP_SHORT: {
    icon: '🐢',
    label: 'TURTLE SOUP SHORT',
    color: '#f43f5e',
    bg: 'rgba(244, 63, 94, 0.08)',
    border: 'rgba(244, 63, 94, 0.20)',
  },
  IRON_CONDOR_PINNING: {
    icon: '🦅',
    label: 'IRON CONDOR PINNING',
    color: '#a855f7',
    bg: 'rgba(168, 85, 247, 0.08)',
    border: 'rgba(168, 85, 247, 0.20)',
  },
  COMMODITY_MOMENTUM: {
    icon: '⛏️',
    label: 'COMMODITY MOMENTUM',
    color: '#f97316',
    bg: 'rgba(249, 115, 22, 0.08)',
    border: 'rgba(249, 115, 22, 0.20)',
  },
  CURRENCY_MOMENTUM: {
    icon: '💱',
    label: 'CURRENCY MOMENTUM',
    color: '#06b6d4',
    bg: 'rgba(6, 182, 212, 0.08)',
    border: 'rgba(6, 182, 212, 0.20)',
  },
  MOMENTUM_ACCELERATION: {
    icon: '🚀',
    label: 'MOMENTUM SPARK',
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.08)',
    border: 'rgba(16, 185, 129, 0.20)',
  },
  CRYPTO_SQUEEZE: {
    icon: '🪙',
    label: 'CRYPTO SQUEEZE',
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.08)',
    border: 'rgba(245, 158, 11, 0.20)',
  },
  CRYPTO_MOMENTUM: {
    icon: '⚡',
    label: 'CRYPTO ALPHA',
    color: '#fbbf24',
    bg: 'rgba(251, 191, 36, 0.08)',
    border: 'rgba(251, 191, 36, 0.20)',
  },
  CRYPTO_VOLATILITY: {
    icon: '🌊',
    label: 'DERIBIT SURFACE',
    color: '#818cf8',
    bg: 'rgba(129, 140, 248, 0.08)',
    border: 'rgba(129, 140, 248, 0.20)',
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
export const CRYPTO_SYMBOLS = new Set([
  'BTC', 'ETH', 'SOL', 'BNB', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
  'BTC-PERP', 'ETH-PERP', 'SOL-PERP',
])
export const NSE_INDEX_SYMBOLS = new Set([
  'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX',
  'NIFTY 50', 'NIFTY BANK', 'NIFTY FINANCIAL SERVICES', 'NIFTY MID SELECT',
])

export function classifyAlertSegment(alert) {
  if (!alert) return 'EQUITY'
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE|DERIBIT):/, '').trim().toUpperCase()
  const exch = (alert.exchange || '').toUpperCase()
  const seg = (alert.segment || alert.metrics?.segment || alert.actionable_plan?.segment || '').toUpperCase()

  if (seg === 'FNO_INDEX') return 'FNO_INDEX'

  if (
    exch === 'CRYPTO' ||
    exch === 'BINANCE' ||
    exch === 'DERIBIT' ||
    seg === 'CRYPTO' ||
    alert.symbol?.toUpperCase().startsWith('CRYPTO:') ||
    alert.symbol?.toUpperCase().startsWith('BINANCE:') ||
    alert.symbol?.toUpperCase().startsWith('DERIBIT:') ||
    CRYPTO_SYMBOLS.has(cleanSym) ||
    cleanSym.endsWith('USDT')
  ) return 'CRYPTO'

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

  const isIndex = NSE_INDEX_SYMBOLS.has(cleanSym) || seg === 'INDEX' || cleanSym.endsWith('INDEX') || cleanSym.startsWith('NIFTY')
  if (isIndex) return 'FNO_INDEX'

  const isFut = Boolean(
    alert.contract_symbol?.toUpperCase().includes('FUT') ||
    alert.symbol?.toUpperCase().includes('FUT') ||
    alert.derivative_type === 'FUT' ||
    alert.alert_type === 'FUTURES'
  )
  const isOption = Boolean(
    alert.option_type || (alert.strike && Number(alert.strike) > 0) ||
    (alert.contract_symbol && alert.contract_symbol !== cleanSym && (alert.contract_symbol.includes('CE') || alert.contract_symbol.includes('PE')))
  )
  const isDerivAlt = alert.alert_type === 'GAMMA_BLAST' || alert.alert_type === 'OPTIONS_MOMENTUM'
  const isStockDeriv = Boolean(
    isFut || isOption || isDerivAlt ||
    (exch === 'NFO' && (isFut || isOption || alert.contract_symbol)) ||
    (seg === 'FNO_STOCK' && (isFut || isOption || isDerivAlt || alert.contract_symbol))
  )

  if (isStockDeriv) {
    return 'FNO_STOCK'
  }

  return 'EQUITY'
}

export function formatExpiryDetails(alert) {
  if (!alert) return null

  const plan = alert.actionable_plan || {}
  const optPlan = plan.option_plan || {}
  const derivAdvice = plan.derivatives_advice || {}

  // 1. Resolve raw date with complete fallback cascade
  let expiryDate =
    alert.expiry_date ||
    alert.expiry_details?.raw_date ||
    optPlan.expiry_date ||
    optPlan.expiry ||
    derivAdvice.expiry ||
    alert.expiry ||
    null

  // 2. Resolve contract symbol
  const rawContract =
    alert.contract_symbol ||
    optPlan.contract_symbol ||
    plan.option_contract ||
    ''
  const contractSym = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()

  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
  const isIndex = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'].some((idx) =>
    cleanSym.includes(idx)
  )

  let d = null
  let inferredExpiryType = null
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  // 3. Parse explicit expiry date string if present
  if (expiryDate) {
    try {
      const cleanDate = String(expiryDate).split('T')[0].trim()
      const parts = cleanDate.split(/[-/]/)
      if (parts.length === 3) {
        if (parts[0].length === 4) {
          d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
        } else {
          d = new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]))
        }
      }
    } catch (_) {}
  }

  // 4. If no explicit date string, parse contract symbol tokens
  if ((!d || isNaN(d.getTime())) && contractSym) {
    // 4a. NSE Index Weekly contract format: e.g. NIFTY2692425000CE (26=2026, 9=Sep, 24=day 24)
    // Month codes: 1-9 for Jan-Sep, O for Oct, N for Nov, D for Dec
    const mWeekly = contractSym.match(/^([A-Z]+)(\d{2})([1-9OND])(\d{2})(\d+)(CE|PE)$/i)
    if (mWeekly) {
      const yr = 2000 + parseInt(mWeekly[2], 10)
      const mCode = mWeekly[3].toUpperCase()
      const mo = mCode === 'O' ? 9 : mCode === 'N' ? 10 : mCode === 'D' ? 11 : parseInt(mCode, 10) - 1
      const day = parseInt(mWeekly[4], 10)
      const parsed = new Date(yr, mo, day)
      if (!isNaN(parsed.getTime())) {
        d = parsed
        inferredExpiryType = 'WEEKLY'
      }
    }

    // 4b. Monthly contract format: e.g. NIFTY26SEP25000CE or RELIANCE26SEP2900CE
    if (!d || isNaN(d.getTime())) {
      const mMonthly = contractSym.match(/(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)/i)
      if (mMonthly) {
        const yr = 2000 + parseInt(mMonthly[1], 10)
        const mStr = mMonthly[2].toUpperCase()
        const mIdx = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'].indexOf(mStr)
        if (mIdx >= 0) {
          // Approximate to last Thursday of month
          const lastDay = new Date(yr, mIdx + 1, 0)
          let lastThuDay = lastDay.getDate() - ((lastDay.getDay() + 7 - 4) % 7)
          d = new Date(yr, mIdx, lastThuDay)
          inferredExpiryType = 'MONTHLY'
        }
      }
    }
  }

  // 5. Determine Expiry Type ('WEEKLY' vs 'MONTHLY')
  let isWeekly = false
  let isMonthly = true

  const explicitType =
    alert.expiry_type ||
    optPlan.expiry_type ||
    (alert.expiry_details?.is_weekly ? 'WEEKLY' : alert.expiry_details?.is_monthly ? 'MONTHLY' : null)

  if (explicitType === 'WEEKLY') {
    isWeekly = true
    isMonthly = false
  } else if (explicitType === 'MONTHLY') {
    isWeekly = false
    isMonthly = true
  } else if (!isIndex) {
    // Single-stock equities on NSE/BSE only have monthly options
    isWeekly = false
    isMonthly = true
  } else if (d && !isNaN(d.getTime())) {
    // For index options, if adding 7 days crosses the month boundary, it is the monthly contract
    const nextWeek = new Date(d.getTime() + 7 * 86400000)
    if (nextWeek.getMonth() !== d.getMonth()) {
      isWeekly = false
      isMonthly = true
    } else {
      isWeekly = true
      isMonthly = false
    }
  } else if (inferredExpiryType) {
    isWeekly = inferredExpiryType === 'WEEKLY'
    isMonthly = inferredExpiryType === 'MONTHLY'
  } else {
    isWeekly = isIndex
    isMonthly = !isIndex
  }

  let monthName = alert.expiry_month_name || alert.expiry_details?.month_name || null
  let formatted = alert.expiry_formatted || alert.expiry_details?.formatted || null
  let dte = alert.dte !== undefined && alert.dte !== null ? alert.dte : null
  let weekday = null
  let dateFormatted = null

  if (d && !isNaN(d.getTime())) {
    monthName = `${months[d.getMonth()]} ${d.getFullYear()}`
    weekday = days[d.getDay()]
    const dayOfMonth = d.getDate().toString().padStart(2, '0')
    dateFormatted = `${d.getDate()}-${months[d.getMonth()]}`

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

  const shortBadge = isWeekly ? '⚡W' : '📅M'
  const tag = isWeekly ? 'WEEKLY' : 'MONTHLY'
  const dateToken = dateFormatted || (expiryDate ? String(expiryDate).split('T')[0] : monthName)
  const dteToken = dte !== null ? ` (${dte}d)` : ''
  const fullDisplay = dateToken ? `${shortBadge} ${dateToken}${dteToken}` : `${shortBadge} ${tag}`

  return {
    monthName: monthName || 'Current Cycle',
    formatted: formatted || (isWeekly ? 'Weekly Expiry' : 'Monthly Expiry'),
    dte,
    isWeekly,
    isMonthly,
    weekday,
    dateFormatted,
    shortBadge,
    tag,
    fullDisplay,
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

  const isSpotSetup = alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'PATTERN_COILING' || alert.alert_type === 'MOMENTUM_ACCELERATION' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM'

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
  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE'
  if (isDerivative) {
    if (optPlan?.entry_premium && Number(optPlan.entry_premium) > 0) {
      entry = Number(optPlan.entry_premium)
    } else if (alert.option_premium && Number(alert.option_premium) > 0) {
      entry = Number(String(alert.option_premium).replace(/[^0-9.-]/g, ''))
    } else if (plan.recommended_entry) {
      entry = Number(String(plan.recommended_entry).replace(/[^0-9.-]/g, ''))
    } else if (isPureOption && alert.ltp && Number(alert.ltp) > 0) {
      entry = Number(String(alert.ltp).replace(/[^0-9.-]/g, ''))
    } else if (optLtpNum && optLtpNum > 0) {
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
    no_chase_boundary: alert.no_chase_boundary || tradePlan.no_chase_boundary || null,
    entry_range: alert.entry_range || alert.optimal_entry_range || tradePlan.optimal_entry_range || null,
    anchored_levels: alert.anchored_levels || tradePlan.anchored_levels || null,
    time_horizon: alert.time_horizon || null,
    order_flow_signals: alert.order_flow_signals || null,
  }
}
