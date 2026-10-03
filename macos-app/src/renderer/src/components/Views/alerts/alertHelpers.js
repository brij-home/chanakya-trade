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

  // 1. Explicit test flags or non-live test environments
  if (isTestFlag || env === 'TEST' || env === 'SIMULATE' || env === 'DEMO') return true
  if (id.startsWith('test-') || id.startsWith('sim-') || id.startsWith('mock-') || id.startsWith('synthetic-') || id.includes('-test-')) return true

  // 2. Headline / summary containing test indicators (including word boundaries)
  if (/\btest\b/i.test(headline) || /\bsimulat/i.test(headline) || /\bmock\b/i.test(headline) || headline.includes('[TEST]') || headline.includes('🧪')) return true
  if (/\btest\b/i.test(summary) || /\bsimulat/i.test(summary) || /\bmock\b/i.test(summary) || summary.includes('TEST ALERT') || summary.includes('TEST MODE')) return true

  return false
}

/**
 * Institutional Provenance Resolver.
 * Maps alert state strictly to verified execution environment:
 * 🧪 TEST: Mock, unit test, simulation
 * 🌙 OFF-MARKET / EOD: Post-market or weekend EOD scanner
 * 🟢 REAL / LIVE: Live verified broker stream during active trading session
 */
export function resolveAlertProvenance(alert) {
  if (!alert) {
    return {
      label: '🟢 REAL / LIVE',
      cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
      isTest: false,
      isLive: true,
      isOffMarket: false,
    }
  }

  if (isTestOrSimAlert(alert)) {
    return {
      label: '🧪 TEST',
      cls: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
      isTest: true,
      isLive: false,
      isOffMarket: false,
    }
  }

  const env = String(alert.environment || '').toUpperCase()
  const mkt = String(alert.market_status || alert.actionable_plan?.market_status?.status || '').toUpperCase()
  const isOffMarket = env === 'EOD_SCAN' || env === 'OFF-MARKET' || mkt === 'SESSION_CLOSED'

  if (isOffMarket) {
    return {
      label: '🌙 OFF-MARKET / EOD',
      cls: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
      isTest: false,
      isLive: false,
      isOffMarket: true,
    }
  }

  return {
    label: '🟢 REAL / LIVE',
    cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
    isTest: false,
    isLive: true,
    isOffMarket: false,
  }
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
  ORDER_FLOW_DIVERGENCE: {
    icon: '📊',
    label: 'CVD ORDER FLOW',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.08)',
    border: 'rgba(56, 189, 248, 0.20)',
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
  TURTLE_SOUP_PLUS_ONE_LONG: {
    icon: '🐢',
    label: 'TURTLE SOUP LONG',
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.08)',
    border: 'rgba(16, 185, 129, 0.20)',
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
  CRYPTO_CVD_ABSORPTION: {
    icon: '🪙',
    label: 'ORDER FLOW CVD',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.08)',
    border: 'rgba(56, 189, 248, 0.20)',
  },
  CRYPTO_LIQUIDATION_FLUSH: {
    icon: '⚡',
    label: 'LIQUIDATION FLUSH',
    color: '#f43f5e',
    bg: 'rgba(244, 63, 94, 0.08)',
    border: 'rgba(244, 63, 94, 0.20)',
  },
  CRYPTO_BASIS_ARBITRAGE: {
    icon: '🌾',
    label: 'BASIS ARBITRAGE',
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.08)',
    border: 'rgba(16, 185, 129, 0.20)',
  },
  CRYPTO_VOL_ARBITRAGE: {
    icon: '🎯',
    label: 'VOL ARBITRAGE',
    color: '#a855f7',
    bg: 'rgba(168, 85, 247, 0.08)',
    border: 'rgba(168, 85, 247, 0.20)',
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
  'BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE',
  'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT',
  'BTC-PERP', 'ETH-PERP', 'SOL-PERP', 'XRP-PERP', 'DOGE-PERP',
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
  const isDerivAlt = alert.alert_type === 'GAMMA_BLAST' || alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE'
  const isStockDeriv = Boolean(
    seg === 'FNO_STOCK' ||
    (seg === 'FNO' && !isIndex) ||
    isFut || isOption || isDerivAlt ||
    (exch === 'NFO' && (isFut || isOption || alert.contract_symbol))
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
    // 4a. Broker YYYYMMDD format (matched FIRST before weekly): e.g. UNITDSPR202609291380PE, POLICYBZR202610271100PE, HAL202609294800PE
    const mIso = contractSym.match(/([A-Z0-9_&]+?)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(\d+)(CE|PE)$/i)
    if (mIso) {
      const yr = parseInt(mIso[2], 10)
      const mo = parseInt(mIso[3], 10) - 1
      const day = parseInt(mIso[4], 10)
      const parsed = new Date(yr, mo, day)
      if (!isNaN(parsed.getTime())) {
        d = parsed
        inferredExpiryType = isIndex ? 'WEEKLY' : 'MONTHLY'
      }
    }

    // 4b. NSE Index Weekly contract format: e.g. NIFTY2692425000CE (26=2026, 9=Sep, 24=day 24)
    // Month codes: 1-9 for Jan-Sep, O for Oct, N for Nov, D for Dec
    // Strictly requires valid day (01-31) and applies only to index contracts
    if ((!d || isNaN(d.getTime())) && isIndex) {
      const mWeekly = contractSym.match(/^([A-Z]+)(\d{2})([1-9OND])(0[1-9]|[12]\d|3[01])(\d+)(CE|PE)$/i)
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
    }

    // 4c. Monthly contract format: e.g. NIFTY26SEP25000CE or RELIANCE26SEP2900CE
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
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const target = new Date(d)
    target.setHours(0, 0, 0, 0)
    const calculatedDte = Math.round((target - today) / (1000 * 60 * 60 * 24))

    // Guard against deep historical years (e.g. year 2020 parsed from corrupted tokens)
    if (calculatedDte < -365 || d.getFullYear() < 2024) {
      d = null
      dateFormatted = null
      dte = null
    } else {
      dte = calculatedDte
      monthName = `${months[d.getMonth()]} ${d.getFullYear()}`
      weekday = days[d.getDay()]
      const dayOfMonth = d.getDate().toString().padStart(2, '0')
      dateFormatted = `${d.getDate()}-${months[d.getMonth()]}`

      if (isWeekly) {
        formatted = `${dayOfMonth}-${months[d.getMonth()]}-${d.getFullYear()} (${weekday}) Weekly Expiry`
      } else {
        formatted = `${monthName} Monthly Expiry (${dayOfMonth}-${months[d.getMonth()]}-${d.getFullYear()})`
      }
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

/**
 * Official NSE/BSE Exchange Trading Holidays (2025–2027)
 * Synchronized with market/calendar.py SSOT.
 */
export const NSE_TRADING_HOLIDAYS = new Set([
  // 2025
  '2025-01-26', '2025-02-26', '2025-03-14', '2025-03-31', '2025-04-10', '2025-04-14',
  '2025-04-18', '2025-05-01', '2025-06-07', '2025-07-06', '2025-08-15', '2025-08-27',
  '2025-10-02', '2025-10-22', '2025-11-05', '2025-12-25',
  // 2026
  '2026-01-26', '2026-02-16', '2026-03-04', '2026-03-20', '2026-04-03', '2026-04-14',
  '2026-04-21', '2026-05-01', '2026-05-27', '2026-06-26', '2026-08-15', '2026-09-14',
  '2026-10-02', '2026-10-20', '2026-11-10', '2026-11-24', '2026-12-25',
  // 2027
  '2027-01-26', '2027-03-08', '2027-03-23', '2027-03-26', '2027-04-14', '2027-05-01',
  '2027-08-15', '2027-09-04', '2027-10-02', '2027-10-09', '2027-10-29', '2027-11-14',
  '2027-12-25'
])

/**
 * Computes official market trading days between startDate and endDate (inclusive).
 * Strictly excludes:
 *   - Weekends (Saturday & Sunday)
 *   - Official Indian market holidays (Ganesh Chaturthi, Diwali, Republic Day, etc.)
 */
export function getTradingDaysBetween(startDate, endDate = new Date()) {
  if (!startDate || isNaN(startDate.getTime())) return 0
  const cur = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate())
  const end = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate())
  if (cur > end) return 0
  let count = 0
  while (cur <= end) {
    const day = cur.getDay() // 0 = Sun, 6 = Sat
    if (day !== 0 && day !== 6) {
      const y = cur.getFullYear()
      const m = String(cur.getMonth() + 1).padStart(2, '0')
      const d = String(cur.getDate()).padStart(2, '0')
      const iso = `${y}-${m}-${d}`
      if (!NSE_TRADING_HOLIDAYS.has(iso)) {
        count++
      }
    }
    cur.setDate(cur.getDate() + 1)
  }
  return count
}

/**
 * Institutional active validation check (SSOT):
 * True only if a trade setup is neither archived, invalidated, expired, nor exited (SL, Time Stop, Runner, Target).
 */
export function isAlertActive(a) {
  if (!a) return false
  if (a.is_expired || a.isExpired || a.stage === 'EXPIRED') return false
  if (a.is_invalidated || a.isInvalidated || a.is_archived || a.isArchived) return false
  const stage = String(a.stage || '').toUpperCase()
  const targetStatus = String(a.target_status || a.targetStatus || '').toUpperCase()
  const isTrailingRunner = Boolean(a.should_trail || a.shouldTrail)
  if (
    stage === 'INVALIDATED' ||
    (stage === 'TARGET_ACHIEVED' && !isTrailingRunner) ||
    stage === 'COMPLETED' ||
    stage === 'SL_HIT' ||
    stage === 'TIME_STOP_EXIT' ||
    stage === 'RUNNER_EXIT' ||
    stage === 'PROFIT_SECURED' ||
    (targetStatus === 'TARGET_ACHIEVED' && !isTrailingRunner) ||
    targetStatus === 'RUNNER_CLOSED' ||
    targetStatus === 'SL_HIT' ||
    targetStatus === 'TIME_STOP_EXIT'
  ) return false

  // Check Intraday session expiration: strictly for explicit intraday setups!
  const horizon = String(a.time_horizon || a.timeHorizon || '').toUpperCase()
  const isExplicitIntraday = horizon === 'INTRADAY' || (a.alert_type && (a.alert_type.toUpperCase().includes('INTRADAY') || a.alert_type.toUpperCase().includes('ORB') || a.alert_type.toUpperCase().includes('SCALP')))
  const isSwingOrPositional =
    horizon.includes('SWING') ||
    horizon.includes('POSITIONAL') ||
    horizon.includes('LONG') ||
    horizon.includes('MULTIBAGGER') ||
    horizon === 'ROLLING_24H' ||
    (a.alert_type && (
      a.alert_type.toUpperCase().includes('SWING') ||
      a.alert_type.toUpperCase().includes('MULTIBAGGER') ||
      a.alert_type.toUpperCase().includes('STAGE_1_TO_2')
    ))

  if (a.created_at || a.timestamp) {
    try {
      const exch = String(a.exchange || '').toUpperCase()
      const seg = String(a.segment || a.metrics?.segment || '').toUpperCase()
      const isCrypto = exch === 'CRYPTO' || exch === 'BINANCE' || exch === 'DERIBIT' || seg === 'CRYPTO' || String(a.symbol || '').toUpperCase().endsWith('USDT') || horizon === 'ROLLING_24H'

      const clean = String(a.created_at || a.timestamp).replace(' IST', '').trim()
      const createdDate = new Date(clean)
      const now = new Date()
      if (!isNaN(createdDate.getTime())) {
        if (isCrypto || horizon === 'ROLLING_24H') {
          // 24x7 Continuous markets use 24-hour rolling expiry window
          if (now.getTime() - createdDate.getTime() >= 86_400_000) {
            return false
          }
        } else if (isExplicitIntraday && !isSwingOrPositional) {
          if (createdDate.toDateString() !== now.toDateString()) {
            return false
          }
        } else if (a.alert_type === 'GAMMA_BLAST' && createdDate.toDateString() !== now.toDateString()) {
          // Intraday Gamma Blasts expire at the close of trading session
          return false
        } else {
          // Multi-day horizon retention in TRADING DAYS (excluding weekends & holidays)
          const tradingDays = getTradingDaysBetween(createdDate, now)
          if (horizon === 'SWING_SHORT' && tradingDays > 7) {
            return false
          } else if (horizon === 'SWING_MID' && tradingDays > 25) {
            return false
          } else if ((horizon === 'LONG_TERM' || horizon === 'POSITIONAL') && tradingDays > 130) {
            return false
          } else if (horizon === 'MULTIBAGGER' && tradingDays > 520) {
            return false
          } else if (!isSwingOrPositional && tradingDays > 5) {
            return false
          }
        }
      }
    } catch (_) {}
  }

  return a.is_active !== undefined
    ? Boolean(a.is_active)
    : true
}

/**
 * Canonical 5-Tier Horizon & ETA Resolver (SSOT):
 * Maps setups across:
 *   - INTRADAY: ⏱️ Intraday Scalp / Day Trade (Cutoff: Today 15:15 IST / MCX 23:15 IST)
 *   - SWING_SHORT: ⚡ Short-Term Swing (2–5 Sessions)
 *   - SWING_MID: 📈 Mid-Term Swing (1–4 Weeks)
 *   - LONG_TERM / POSITIONAL: 🏛️ Long-Term Positional (1–6 Months)
 *   - MULTIBAGGER: 🚀 Multibagger Alpha (6–24 Months Compounding Runway)
 */
export function resolveHorizonAndETA(alert) {
  if (!alert) {
    return {
      key: 'INTRADAY',
      label: 'INTRADAY',
      shortLabel: 'INTRADAY',
      icon: '⏱️',
      etaLabel: '15:15',
      etaFull: 'Today by 15:15 IST',
      compactBadge: '⏱️ INTRADAY • 15:15',
      badgeClasses: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
      etaClasses: 'bg-sky-500/10 text-sky-300 border-sky-500/20',
      tooltip: 'Intraday Setup: Square-off by 15:15 IST.',
    }
  }

  const rawHorizon = String(alert.time_horizon || alert.timeHorizon || '').toUpperCase()
  const rawType = String(alert.alert_type || alert.alertType || '').toUpperCase()
  const exch = String(alert.exchange || 'NSE').toUpperCase()
  const isCrypto =
    exch === 'CRYPTO' ||
    exch === 'BINANCE' ||
    exch === 'DERIBIT' ||
    (alert.segment || '').toUpperCase() === 'CRYPTO' ||
    String(alert.symbol || '').toUpperCase().endsWith('USDT') ||
    String(alert.symbol || '').toUpperCase().endsWith('USDC') ||
    String(alert.symbol || '').toUpperCase().startsWith('CRYPTO:')

  let key = 'INTRADAY'
  if (rawHorizon === 'SCALP' || rawHorizon === 'INTRADAY_SCALP_ONLY' || rawHorizon === 'FAST_SCALP') {
    key = 'SCALP'
  } else if (rawHorizon === 'ROLLING_24H' || (isCrypto && (!rawHorizon || rawHorizon === 'INTRADAY'))) {
    key = 'ROLLING_24H'
  } else if (rawHorizon === 'MULTIBAGGER') {
    key = 'MULTIBAGGER'
  } else if (rawHorizon === 'LONG_TERM' || rawHorizon === 'POSITIONAL') {
    key = 'LONG_TERM'
  } else if (rawHorizon === 'SWING_MID') {
    key = 'SWING_MID'
  } else if (rawHorizon === 'SWING_SHORT' || rawHorizon === 'SWING') {
    key = 'SWING_SHORT'
  } else if (rawHorizon === 'INTRADAY') {
    key = isCrypto ? 'ROLLING_24H' : 'INTRADAY'
  } else if (rawType.includes('MULTIBAGGER')) {
    key = 'MULTIBAGGER'
  } else if (rawType.includes('STAGE_1_TO_2')) {
    const text = String((alert.headline || '') + ' ' + (alert.summary || '') + ' ' + (alert.alert_id || '')).toUpperCase()
    key = text.includes('MULTIBAGGER') ? 'MULTIBAGGER' : 'LONG_TERM'
  } else if (rawType.includes('SQUEEZE') || rawType.includes('RRG') || rawType.includes('PULLBACK')) {
    key = 'SWING_MID'
  } else if (rawType.includes('COILING') || rawType.includes('CIRCUIT') || rawType.includes('VCP')) {
    key = 'SWING_SHORT'
  } else if (rawType.includes('GAMMA') || rawType.includes('SPARK') || rawType.includes('ORB') || rawType.includes('CONTAGION')) {
    key = (alert.headline || '').toUpperCase().includes('SCALP') ? 'SCALP' : 'INTRADAY'
  } else if (rawHorizon) {
    key = rawHorizon
  }

  // Derive ETA
  let etaLabel = alert.eta_label || alert.etaLabel || null
  let etaFull = null

  if (isCrypto && (!etaLabel || etaLabel.includes('15:15') || etaLabel.includes('Today'))) {
    etaLabel = '24h'
    etaFull = '24h Rolling Window'
  } else if (!etaLabel) {
    if (key === 'MULTIBAGGER') {
      etaLabel = '6–24m'
      etaFull = '6–24 Months'
    } else if (key === 'LONG_TERM' || key === 'POSITIONAL') {
      etaLabel = '1–6m'
      etaFull = '1–6 Months'
    } else if (key === 'SWING_MID') {
      if (alert.expiry_date) {
        etaLabel = alert.dte ? `${alert.dte}d` : '1–4w'
        etaFull = alert.dte ? `${alert.dte}d (${alert.expiry_type || 'Monthly'} Exp)` : '1–4 Weeks'
      } else {
        etaLabel = '1–4w'
        etaFull = '1–4 Weeks'
      }
    } else if (key === 'SWING_SHORT') {
      if (alert.expiry_date) {
        etaLabel = alert.dte ? `${alert.dte}d` : '2–5d'
        etaFull = alert.dte ? `${alert.dte}d (${alert.expiry_type || 'Weekly'} Exp)` : '2–5 Sessions'
      } else {
        etaLabel = '2–5d'
        etaFull = '2–5 Sessions'
      }
    } else if (key === 'SCALP') {
      etaLabel = '15–45m'
      etaFull = '15–45 Minutes (Fast Scalp)'
    } else if (key === 'ROLLING_24H') {
      etaLabel = '24h'
      etaFull = '24h Rolling Window'
    } else {
      // INTRADAY
      etaLabel = isCrypto ? '24h' : (exch === 'MCX' ? '23:15' : '15:15')
      etaFull = isCrypto ? '24h Rolling Window' : (exch === 'MCX' ? 'Today by 23:15 IST' : 'Today by 15:15 IST')
    }
  } else {
    etaFull = etaLabel
    if (isCrypto && (etaLabel.includes('15:15') || etaLabel.includes('Today'))) {
      etaLabel = '24h'
      etaFull = '24h Rolling Window'
    } else if (etaLabel.includes('Today')) {
      etaLabel = exch === 'MCX' ? '23:15' : '15:15'
    } else if (etaLabel.includes('2–5 Sessions') || etaLabel.includes('2-5')) {
      etaLabel = '2–5d'
    } else if (etaLabel.includes('1–4 Weeks') || etaLabel.includes('1-4')) {
      etaLabel = '1–4w'
    } else if (etaLabel.includes('1–6 Months') || etaLabel.includes('1-6')) {
      etaLabel = '1–6m'
    } else if (etaLabel.includes('6–24 Months') || etaLabel.includes('6-24')) {
      etaLabel = '6–24m'
    } else if (etaLabel.includes('24h') || etaLabel.includes('Rolling')) {
      etaLabel = '24h'
      etaFull = '24h Rolling Window'
    }
  }

  // Token styles & metadata
  switch (key) {
    case 'SCALP':
      return {
        key: 'SCALP',
        label: 'SCALP',
        shortLabel: 'SCALP',
        icon: '⚡',
        etaLabel: etaLabel || '15–45m',
        etaFull: etaFull || '15–45 Minutes (Fast Scalp)',
        compactBadge: `⚡ SCALP • ${etaLabel || '15–45m'}`,
        badgeClasses: 'bg-amber-500/20 text-amber-300 border-amber-500/40 ring-1 ring-amber-500/20',
        etaClasses: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
        tooltip: 'High-Velocity Scalp: Fast momentum target (15–45m), mandatory square-off before 15:00 IST.',
      }
    case 'ROLLING_24H':
      return {
        key: 'ROLLING_24H',
        label: '24H ROLLING',
        shortLabel: '24H',
        icon: '🪙',
        etaLabel: etaLabel || '24h',
        etaFull: etaFull || '24h Rolling Window',
        compactBadge: `🪙 24H • ${etaLabel || '24h'}`,
        badgeClasses: 'bg-teal-500/20 text-teal-300 border-teal-500/40',
        etaClasses: 'bg-teal-500/10 text-teal-300 border-teal-500/30',
        tooltip: '24/7 Continuous Market: Rolling 24-hour expiration window.',
      }
    case 'MULTIBAGGER':
      return {
        key: 'MULTIBAGGER',
        label: 'MULTIBAGGER',
        shortLabel: 'MULTI',
        icon: '🚀',
        etaLabel,
        etaFull: etaFull || '6–24 Months',
        compactBadge: `🚀 MULTI • ${etaLabel}`,
        badgeClasses: 'bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40 ring-1 ring-fuchsia-500/20 shadow-sm shadow-fuchsia-950/40',
        etaClasses: 'bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/30',
        tooltip: 'Multibagger Alpha: Fundamental compounding, CANSLIM acceleration, or Stage 2 breakout. Target ETA: 6–24 Months.',
      }
    case 'LONG_TERM':
    case 'POSITIONAL':
      return {
        key: 'LONG_TERM',
        label: 'LONG POSITIONAL',
        shortLabel: 'LONG',
        icon: '🏛️',
        etaLabel,
        etaFull: etaFull || '1–6 Months',
        compactBadge: `🏛️ LONG • ${etaLabel}`,
        badgeClasses: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40',
        etaClasses: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30',
        tooltip: 'Long-Term Positional: Multi-quarter structural compounding. Target ETA: 1–6 Months.',
      }
    case 'SWING_MID':
      return {
        key: 'SWING_MID',
        label: 'MID SWING',
        shortLabel: 'MID',
        icon: '📈',
        etaLabel,
        etaFull: etaFull || '1–4 Weeks',
        compactBadge: `📈 MID • ${etaLabel}`,
        badgeClasses: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
        etaClasses: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
        tooltip: 'Mid-Term Swing: Structural trend continuation & sector rotation. Target ETA: 1–4 Weeks.',
      }
    case 'SWING_SHORT':
      return {
        key: 'SWING_SHORT',
        label: 'SHORT SWING',
        shortLabel: 'SHORT',
        icon: '⚡',
        etaLabel,
        etaFull: etaFull || '2–5 Sessions',
        compactBadge: `⚡ SHORT • ${etaLabel}`,
        badgeClasses: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        etaClasses: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
        tooltip: 'Short-Term Swing: Volatility compression & momentum breakout. Target ETA: 2–5 Sessions.',
      }
    default:
      return {
        key: 'INTRADAY',
        label: 'INTRADAY',
        shortLabel: 'INTRADAY',
        icon: '⏱️',
        etaLabel,
        etaFull: etaFull || (exch === 'MCX' ? 'Today by 23:15 IST' : 'Today by 15:15 IST'),
        compactBadge: `⏱️ INTRADAY • ${etaLabel}`,
        badgeClasses: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
        etaClasses: 'bg-sky-500/10 text-sky-300 border-sky-500/20',
        tooltip: `Intraday Setup: Active for current session only. Hard square-off by ${exch === 'MCX' ? '23:15' : '15:15'} IST.`,
      }
  }
}

/**
 * Institutional Single Source of Truth (SSOT) Lifecycle Resolver for AutoAlerts.
 * Unifies level calculation, price resolution, P&L, stage mapping, and UI badge pills.
 * Enforces historical immutability: closed/terminal alerts read recorded backend exit metrics
 * and NEVER oscillate or recalculate against live streaming market quotes.
 */
export function resolveAlertLifecycle(alert, { liveSpot = null, liveContract = null } = {}) {
  if (!alert) return null

  const isTerminal = !isAlertActive(alert)
  const isCrypto = (alert.exchange || '').toUpperCase() === 'CRYPTO' || (alert.exchange || '').toUpperCase() === 'BINANCE' || (alert.segment || '').toUpperCase() === 'CRYPTO'
  const horizonInfo = resolveHorizonAndETA(alert)

  const plan = alert.actionable_plan || {}
  const tradePlan = plan.trade_plan || {}
  const optPlan = plan.option_plan || null

  const rawContract = alert.contract_symbol || optPlan?.contract_symbol || plan.option_contract || ''
  const cleanContract = rawContract.replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO|BINANCE):/, '').trim().toUpperCase()

  const optType = alert.option_type || optPlan?.option_type || (rawContract?.endsWith('PE') ? 'PE' : rawContract?.endsWith('CE') ? 'CE' : null)
  const rawStrike = alert.strike || optPlan?.strike || alert.metrics?.strike
  const strikeNum = rawStrike ? Number(String(rawStrike).replace(/[^0-9.-]/g, '')) : null
  const isFuture = Boolean(rawContract?.toUpperCase().includes('FUT') || alert.symbol?.toUpperCase().includes('FUT') || alert.derivative_type === 'FUT')

  const isPureOption = alert.alert_type === 'OPTIONS_MOMENTUM' || alert.alert_type === 'OPTION_WRITE' || (alert.alert_type === 'GAMMA_BLAST' && optType) || (rawContract && (rawContract.endsWith('CE') || rawContract.endsWith('PE')) && alert.exchange === 'NFO')
  const isSpotSetup = !isFuture && !isPureOption && (alert.alert_type === 'ASYMMETRIC_OPPORTUNITY' || alert.alert_type === 'SQUEEZE_BREAKOUT' || alert.alert_type === 'SQUEEZE_BREAKDOWN' || alert.alert_type === 'PATTERN_COILING' || alert.alert_type === 'MOMENTUM_ACCELERATION' || alert.alert_type === 'POCKET_PIVOT' || alert.alert_type === 'PRECURSOR_RADAR' || alert.alert_type === 'SMC_SWEEP' || alert.alert_type === 'CIRCUIT_WARNING' || alert.alert_type === 'COMMODITY_MOMENTUM' || alert.alert_type === 'TURTLE_SOUP_SHORT' || alert.alert_type === 'TURTLE_SOUP_PLUS_ONE_LONG' || alert.alert_type === 'IRON_CONDOR_PINNING' || alert.alert_type === 'CRYPTO_SQUEEZE' || alert.alert_type === 'CRYPTO_MOMENTUM')
  const isDerivative = !isSpotSetup && Boolean(isFuture || isPureOption || (alert.exchange === 'NFO' && (optType || strikeNum || rawContract)))

  const isBull = alert.direction === 'BULLISH'
  const isBear = alert.direction === 'BEARISH'
  const isNeutral = alert.direction === 'NEUTRAL' || alert.alert_type === 'IRON_CONDOR_PINNING'

  const act = String(tradePlan.action || plan.action || '').toUpperCase()
  const isOptionSell = isDerivative && (
    act === 'SELL' ||
    act === 'WRITE' ||
    act === 'SHORT' ||
    alert.alert_type === 'OPTION_WRITE'
  )

  // 1. Resolve Execution Levels
  const levels = computeExecutionLevels(
    alert,
    isDerivative,
    liveSpot?.ltp,
    liveContract?.ltp
  )
  const entryNum = levels.entry
  const slNum = levels.sl
  const t1Num = levels.t1
  const t2Num = levels.t2
  const t3Num = levels.t3

  // 2. SSOT Price Resolution
  // CRITICAL INVARIANT: For terminal/archived trades, NEVER use live streaming ticks!
  // Read recorded exit price: alert.ltp (which backend sets to CMP on exit)
  let currentPrice = null
  let spotNum = null
  let premiumNum = null

  if (isTerminal) {
    if (isDerivative) {
      const rawS = alert.underlying_spot != null ? alert.underlying_spot : alert.metrics?.spot
      spotNum = rawS != null ? Number(String(rawS).replace(/[^0-9.-]/g, '')) : null

      const isIndexOrStockSpot = (val) => {
        if (val == null || isNaN(val) || val <= 0) return false
        if (spotNum && Math.abs(val - spotNum) / spotNum < 0.05) return true
        if ((cleanSym.includes('NIFTY') || cleanSym.includes('SENSEX')) && val > 3000 && (entryNum == null || entryNum < 1500)) return true
        return false
      }

      let rawOpt = null
      if (alert.option_premium != null && Number(alert.option_premium) > 0 && !isIndexOrStockSpot(Number(alert.option_premium))) {
        rawOpt = alert.option_premium
      } else if (alert.ltp != null && Number(alert.ltp) > 0 && !isIndexOrStockSpot(Number(alert.ltp))) {
        rawOpt = alert.ltp
      } else if (alert.trigger_level != null && !isIndexOrStockSpot(Number(alert.trigger_level))) {
        rawOpt = alert.trigger_level
      } else {
        rawOpt = entryNum || alert.option_premium
      }

      currentPrice = rawOpt != null ? Number(String(rawOpt).replace(/[^0-9.-]/g, '')) : null
      premiumNum = currentPrice
    } else {
      const raw = alert.ltp != null ? alert.ltp : (alert.underlying_spot != null ? alert.underlying_spot : alert.trigger_level)
      currentPrice = raw != null ? Number(String(raw).replace(/[^0-9.-]/g, '')) : null
      spotNum = currentPrice
    }
  } else {
    // In-flight active trade: live quote takes priority, fallback to alert snapshot
    const rawSpot = liveSpot?.ltp ?? alert.underlying_spot ?? alert.metrics?.spot
    spotNum = rawSpot != null ? Number(String(rawSpot).replace(/[^0-9.-]/g, '')) : null

    if (isDerivative) {
      const isIndexOrStockSpot = (val) => {
        if (val == null || isNaN(val) || val <= 0) return false
        if (spotNum && Math.abs(val - spotNum) / spotNum < 0.05) return true
        if ((cleanSym.includes('NIFTY') || cleanSym.includes('SENSEX')) && val > 3000 && (entryNum == null || entryNum < 1500)) return true
        return false
      }

      let rawOpt = null
      if (liveContract?.ltp != null && Number(liveContract.ltp) > 0) {
        rawOpt = liveContract.ltp
      } else if (alert.option_premium != null && Number(alert.option_premium) > 0 && !isIndexOrStockSpot(Number(alert.option_premium))) {
        rawOpt = alert.option_premium
      } else if (alert.ltp != null && Number(alert.ltp) > 0 && !isIndexOrStockSpot(Number(alert.ltp))) {
        rawOpt = alert.ltp
      } else {
        rawOpt = alert.trigger_level != null && !isIndexOrStockSpot(Number(alert.trigger_level)) ? alert.trigger_level : entryNum
      }

      premiumNum = rawOpt != null ? Number(String(rawOpt).replace(/[^0-9.-]/g, '')) : null
      currentPrice = premiumNum
    } else {
      const rawEq = liveSpot?.ltp ?? alert.ltp ?? alert.underlying_spot ?? alert.trigger_level
      currentPrice = rawEq != null ? Number(String(rawEq).replace(/[^0-9.-]/g, '')) : null
    }
  }

  // 3. Return / P&L Resolution (SSOT)
  let liveReturn = null
  if (isTerminal && alert.pnl_pct !== undefined && alert.pnl_pct !== null) {
    const pctVal = Number(alert.pnl_pct)
    const pct = pctVal.toFixed(1)
    const diff = (entryNum && !isNaN(entryNum))
      ? ((isOptionSell ? -1 : 1) * (entryNum * (pctVal / 100)))
      : (currentPrice && entryNum ? currentPrice - entryNum : 0)
    liveReturn = {
      diff,
      pct,
      isProfitable: pctVal >= 0,
      isRealized: true,
      rMultiple: alert.r_multiple ?? null,
    }
  } else if (currentPrice && entryNum && entryNum > 0) {
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
    liveReturn = {
      diff,
      pct,
      isProfitable: isProf,
      isRealized: isTerminal,
      rMultiple: alert.r_multiple ?? null,
    }
  }

  // 4. Stage & Milestones Resolution (SSOT)
  let isTimeStop = false
  let isSLHit = false
  let isExpired = false
  let isInvalidated = false
  let isT3Hit = false
  let isT2Hit = false
  let isT1Hit = false
  let isRunnerExit = false
  let isTrail = false
  let isEarly = false
  let isIgnited = false
  let isPrimed = false
  let isStalk = false
  let resolvedStage = String(alert.stage || '').toUpperCase()

  const rawStage = String(alert.stage || '').toUpperCase()
  const targetStatus = String(alert.target_status || alert.targetStatus || '').toUpperCase()
  const reason = String(alert.invalidation_reason || alert.archive_reason || alert.summary || '').toUpperCase()

  if (isTerminal) {
    // IMMUTABLE HISTORICAL RECORD: Read stage strictly from backend SSOT
    if (rawStage === 'TIME_STOP_EXIT' || targetStatus === 'TIME_STOP_EXIT' || reason.includes('TIME-STOP') || reason.includes('TIME STOP')) {
      resolvedStage = 'TIME_STOP_EXIT'
      isTimeStop = true
    } else if (rawStage === 'SL_HIT' || targetStatus === 'SL_HIT' || reason.includes('STOP_LOSS') || reason.includes('SL HIT') || reason.includes('SL BREACH')) {
      resolvedStage = 'SL_HIT'
      isSLHit = true
    } else if (rawStage === 'EXPIRED' || alert.is_expired || alert.isExpired) {
      resolvedStage = 'EXPIRED'
      isExpired = true
    } else if (rawStage === 'TARGET_ACHIEVED' || rawStage === 'COMPLETED' || targetStatus === 'TARGET_ACHIEVED') {
      resolvedStage = 'TARGET_ACHIEVED'
      isT3Hit = true
      isT2Hit = true
      isT1Hit = true
    } else if (rawStage === 'RUNNER_EXIT' || targetStatus === 'RUNNER_CLOSED') {
      resolvedStage = 'RUNNER_EXIT'
      isRunnerExit = true
    } else if (rawStage === 'T2_ACHIEVED' || targetStatus === 'T2_ACHIEVED') {
      resolvedStage = 'T2_ACHIEVED'
      isT2Hit = true
      isT1Hit = true
    } else if (rawStage === 'T1_ACHIEVED' || targetStatus === 'T1_ACHIEVED') {
      resolvedStage = 'T1_ACHIEVED'
      isT1Hit = true
    } else if (alert.is_invalidated || alert.isInvalidated || rawStage === 'INVALIDATED') {
      resolvedStage = 'INVALIDATED'
      isInvalidated = true
    } else {
      resolvedStage = rawStage || 'ARCHIVED'
      isInvalidated = true
    }

    // Historical milestone checks for dots
    if (alert.achieved_milestones && Array.isArray(alert.achieved_milestones)) {
      if (alert.achieved_milestones.includes('T1_ACHIEVED')) isT1Hit = true
      if (alert.achieved_milestones.includes('T2_ACHIEVED')) isT2Hit = true
      if (alert.achieved_milestones.includes('TARGET_ACHIEVED') || alert.achieved_milestones.includes('T3_ACHIEVED')) isT3Hit = true
    }
  } else {
    // ACTIVE IN-FLIGHT TRADE: Dynamic evaluation
    const isExplicitSL = Boolean(
      rawStage === 'SL_HIT' ||
      targetStatus === 'SL_HIT' ||
      reason.includes('STOP_LOSS') ||
      reason.includes('SL HIT') ||
      reason.includes('SL BREACH')
    )

    const isPriceBreachedSL = Boolean(
      slNum && currentPrice && (
        isDerivative
          ? (isOptionSell ? currentPrice >= slNum : currentPrice <= slNum)
          : isNeutral
          ? (currentPrice < slNum || (alert.metrics?.long_ce && currentPrice > alert.metrics.long_ce))
          : (isBull ? currentPrice <= slNum : currentPrice >= slNum)
      )
    )

    isSLHit = isExplicitSL || isPriceBreachedSL

    isT3Hit = Boolean(
      rawStage === 'TARGET_ACHIEVED' || rawStage === 'COMPLETED' || targetStatus === 'TARGET_ACHIEVED' ||
      (t3Num && currentPrice && !isSLHit && (
        isDerivative ? (isOptionSell ? currentPrice <= t3Num : currentPrice >= t3Num) : (isBull ? currentPrice >= t3Num : currentPrice <= t3Num)
      ))
    )

    isT2Hit = Boolean(
      isT3Hit || rawStage === 'T2_ACHIEVED' || targetStatus === 'T2_ACHIEVED' ||
      (t2Num && currentPrice && !isSLHit && (
        isDerivative ? (isOptionSell ? currentPrice <= t2Num : currentPrice >= t2Num) : (isBull ? currentPrice >= t2Num : currentPrice <= t2Num)
      ))
    )

    isT1Hit = Boolean(
      isT2Hit || rawStage === 'T1_ACHIEVED' || targetStatus === 'T1_ACHIEVED' ||
      (t1Num && currentPrice && !isSLHit && (
        isDerivative ? (isOptionSell ? currentPrice <= t1Num : currentPrice >= t1Num) : (isBull ? currentPrice >= t1Num : currentPrice <= t1Num)
      ))
    )

    isTrail = rawStage === 'TRAILING_UPDATE'
    isEarly = rawStage === 'EARLY_WARNING'
    isIgnited = rawStage === 'IGNITED'
    isPrimed = rawStage === 'PRIMED'
    isStalk = rawStage === 'STALK'
    resolvedStage = isSLHit ? 'SL_HIT' : isT3Hit ? 'TARGET_ACHIEVED' : isT2Hit ? 'T2_ACHIEVED' : isT1Hit ? 'T1_ACHIEVED' : rawStage
  }

  // 5. Stage Pill & Trajectory Status
  let stagePill = { label: '🟢 ACTIVE', cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20', icon: '🟢' }
  let trajectoryStatus = { badge: '🟢 ACTIVE', text: 'Trade in flight — active execution', theme: 'emerald' }

  if (isTimeStop) {
    stagePill = { label: '⏱️ TIME STOP', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/40', icon: '⏱️' }
    trajectoryStatus = { badge: '⏱️ TIME STOP', text: alert.invalidation_reason || 'Velocity time stop reached — closed at CMP', theme: 'amber' }
  } else if (isSLHit) {
    stagePill = { label: '🛑 SL HIT', cls: 'bg-rose-500/25 text-rose-300 border-rose-500/60 ring-1 ring-rose-500/40' + (!isTerminal ? ' animate-pulse' : ''), icon: '🛑' }
    trajectoryStatus = { badge: '🛑 SL BREACHED', text: alert.invalidation_reason || 'Stop loss triggered — trade thesis invalidated', theme: 'rose' }
  } else if (isExpired) {
    stagePill = { label: '⏱️ EXPIRED', cls: 'bg-zinc-700/40 text-zinc-300 border-zinc-600/40', icon: '⏱️' }
    trajectoryStatus = { badge: '⏱️ EXPIRED', text: alert.invalidation_reason || 'Session time cutoff reached — trade closed', theme: 'slate' }
  } else if (isInvalidated) {
    stagePill = { label: '⚠️ INVALIDATED', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/40', icon: '⚠️' }
    trajectoryStatus = { badge: '⚠️ INVALIDATED', text: alert.invalidation_reason || 'Trade setup invalidated — structure or momentum collapsed', theme: 'amber' }
  } else if (isT3Hit) {
    stagePill = { label: '🚀 T3 HIT', cls: 'bg-purple-500/25 text-purple-200 border-purple-400/60 ring-1 ring-purple-500/40' + (!isTerminal ? ' animate-pulse' : ''), icon: '🚀' }
    trajectoryStatus = { badge: '🚀 T3 REACHED', text: 'Target 3 hit — runners locked (+6R+ extension)', theme: 'purple' }
  } else if (isT2Hit) {
    stagePill = { label: '🏁 T2 HIT', cls: 'bg-cyan-500/25 text-cyan-200 border-cyan-400/60 ring-1 ring-cyan-500/40' + (!isTerminal ? ' animate-pulse' : ''), icon: '🏁' }
    trajectoryStatus = { badge: '🏁 T2 ACHIEVED', text: 'Target 2 hit — 75% profit secured, trailing at T1', theme: 'cyan' }
  } else if (isT1Hit) {
    stagePill = { label: '🎯 T1 HIT', cls: 'bg-emerald-500/25 text-emerald-200 border-emerald-400/60 ring-1 ring-emerald-500/40' + (!isTerminal ? ' animate-pulse' : ''), icon: '🎯' }
    trajectoryStatus = { badge: '🎯 T1 ACHIEVED', text: 'Target 1 hit — 50% scale out complete, SL ratcheted to breakeven', theme: 'emerald' }
  } else if (isRunnerExit) {
    stagePill = { label: '🏁 RUNNER EXIT', cls: 'bg-cyan-500/25 text-cyan-200 border-cyan-400/60', icon: '🏁' }
    trajectoryStatus = { badge: '🏁 RUNNER CLOSED', text: alert.invalidation_reason || 'Runner trailing exit hit — remaining position closed', theme: 'cyan' }
  } else if (isTrail) {
    stagePill = { label: '📈 TRAIL', cls: 'bg-blue-500/20 text-blue-300 border-blue-500/40', icon: '📈' }
    trajectoryStatus = { badge: '📈 TRAILING ACTIVE', text: alert.trailing_rationale || 'Trailing stop active to protect gains', theme: 'blue' }
  } else if (isPrimed) {
    stagePill = { label: '🎯 PRIMED', cls: 'bg-amber-400/20 text-amber-300 border-amber-400/50 ring-1 ring-amber-400/30 animate-pulse', icon: '🎯' }
    trajectoryStatus = { badge: '🎯 PRIMED', text: 'Micro-proximity triggered (±0.35%) — sniper ready for ignition', theme: 'amber' }
  } else if (isStalk) {
    stagePill = { label: '🦅 STALK', cls: 'bg-sky-500/15 text-sky-400 border-sky-500/30', icon: '🦅' }
    trajectoryStatus = { badge: '🦅 STALK', text: 'Setup tracked on radar — waiting for trigger zone approach', theme: 'sky' }
  } else if (isEarly) {
    stagePill = { label: '⏳ EARLY', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30', icon: '⏳' }
    trajectoryStatus = { badge: '⏳ EARLY WARNING', text: 'Setup forming — awaiting trigger breakout', theme: 'amber' }
  } else if (isIgnited) {
    stagePill = { label: '🔥 IGNITED', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30 animate-pulse', icon: '🔥' }
    trajectoryStatus = { badge: '🔥 IGNITED', text: 'Breakout confirmed — trade active in flight', theme: 'emerald' }
  } else if (liveReturn && currentPrice && entryNum) {
    if (liveReturn.isProfitable) {
      if (t1Num) {
        const t1Dist = Math.abs(t1Num - entryNum)
        const currDist = Math.abs(currentPrice - entryNum)
        const pctToT1 = Math.min(100, Math.max(0, Math.round((currDist / (t1Dist || 1)) * 100)))
        const ptsAway = Math.abs(t1Num - currentPrice)
        trajectoryStatus = {
          badge: `🟢 RIGHT DIRECTION (+${liveReturn.pct}%)`,
          text: `${pctToT1}% progress to T1 (${ptsAway > 0 ? `₹${ptsAway.toFixed(1)} away` : 'at target'})`,
          theme: 'emerald',
        }
      } else {
        trajectoryStatus = {
          badge: `🟢 PROFITABLE (+${liveReturn.pct}%)`,
          text: `Moving favorably from entry ₹${entryNum.toFixed(1)}`,
          theme: 'emerald',
        }
      }
    } else {
      if (slNum) {
        const slDist = Math.abs(entryNum - slNum)
        const adverseDist = Math.abs(entryNum - currentPrice)
        const pctToSL = Math.min(100, Math.max(0, Math.round((adverseDist / (slDist || 1)) * 100)))
        const ptsBuffer = Math.abs(currentPrice - slNum)
        trajectoryStatus = {
          badge: `⚠️ PULLBACK (${liveReturn.pct}%)`,
          text: `${pctToSL}% toward SL — ₹${ptsBuffer.toFixed(1)} buffer remaining`,
          theme: 'amber',
        }
      } else {
        trajectoryStatus = {
          badge: `⚠️ AGAINST ENTRY (${liveReturn.pct}%)`,
          text: 'Testing below entry level',
          theme: 'amber',
        }
      }
    }
  }

  return {
    isTerminal,
    isDerivative,
    isBull,
    isBear,
    isNeutral,
    isOptionSell,
    cleanSym,
    cleanContract,
    rawContract,
    optType,
    strikeNum,
    isFuture,
    isCrypto,
    currSym: isCrypto ? '$' : '₹',
    levels,
    entryNum,
    slNum,
    t1Num,
    t2Num,
    t3Num,
    currentPrice,
    spotNum,
    premiumNum,
    liveReturn,
    stage: resolvedStage,
    stagePill,
    trajectoryStatus,
    isTimeStop,
    isSLHit,
    isExpired,
    isInvalidated,
    isT3Hit,
    isT2Hit,
    isT1Hit,
    isRunnerExit,
    isTrail,
    isEarly,
    isIgnited,
    isPrimed,
    isStalk,
    horizonInfo,
  }
}
