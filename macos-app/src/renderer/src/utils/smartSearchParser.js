/**
 * ChanakyaTrade — Institutional Smart Search & Syntax Directive Parser
 * Supports free-text fuzzy/alias search, contract matching, and power-user directives:
 * - sym:RELIANCE or symbol:INFY (exact or prefix symbol)
 * - strike:2400 or ce:2400 or pe:2400 (option contract strike)
 * - rr:>3 or rr:>=2.5 or rr:3+ (Risk:Reward ratio filter)
 * - score:>80 or score:85+ (Quantitative conviction threshold)
 * - dir:bull or dir:bear (Direction filter)
 * - stage:ignited or stage:primed or stage:target (Lifecycle stage)
 * - sec:IT or sector:Banking (Sector filter)
 * - cat:gamma or setup:squeeze (Alert category filter)
 */

import { INDIAN_UNIVERSE } from '../data/universeData'

/**
 * Pre-build fast alias and symbol lookup map for instant O(1) matching
 */
const ALIAS_MAP = new Map()
if (Array.isArray(INDIAN_UNIVERSE)) {
  for (const item of INDIAN_UNIVERSE) {
    const sym = item.symbol.toUpperCase()
    // Map symbol itself
    if (!ALIAS_MAP.has(sym.toLowerCase())) {
      ALIAS_MAP.set(sym.toLowerCase(), sym)
    }
    // Map aliases
    if (Array.isArray(item.aliases)) {
      for (const al of item.aliases) {
        const cleanAl = String(al).trim().toLowerCase()
        if (cleanAl && !ALIAS_MAP.has(cleanAl)) {
          ALIAS_MAP.set(cleanAl, sym)
        }
      }
    }
  }
}

/**
 * Parses numeric threshold from strings like ">3", ">=2.5", "3+", "80", ">80"
 */
function parseNumericThreshold(valStr) {
  if (!valStr) return null
  const clean = valStr.trim().replace('+', '')
  let num = null
  if (clean.startsWith('>=') || clean.startsWith('<=')) {
    num = parseFloat(clean.slice(2))
  } else if (clean.startsWith('>') || clean.startsWith('<')) {
    num = parseFloat(clean.slice(1))
  } else {
    num = parseFloat(clean)
  }
  return isNaN(num) ? null : num
}

/**
 * Parses R:R ratio from various alert formats:
 * - "1:3.2" -> 3.2
 * - 3.5 -> 3.5
 * - "1 : 4.0" -> 4.0
 */
export function extractRiskRewardRatio(item) {
  if (!item) return null
  const raw =
    item.risk_reward_ratio ??
    item.risk_reward ??
    item.metrics?.risk_reward_ratio ??
    item.metrics?.rr_ratio ??
    item.actionable_plan?.trade_plan?.risk_reward_ratio ??
    item.actionable_plan?.trade_plan?.risk_reward

  if (typeof raw === 'number' && !isNaN(raw)) return raw
  if (typeof raw === 'string') {
    if (raw.includes(':')) {
      const parts = raw.split(':')
      const denom = parseFloat(parts[parts.length - 1].trim())
      if (!isNaN(denom)) return denom
    }
    const parsed = parseFloat(raw.replace(/[^\d.]/g, ''))
    if (!isNaN(parsed)) return parsed
  }
  return null
}

/**
 * Extracts conviction / confidence / score as a number 0-100
 */
export function extractConvictionScore(item) {
  if (!item) return null
  const raw =
    item.confidence ??
    item.conviction ??
    item.conviction_score ??
    item.inflection_score ??
    item.century_score ??
    item.score ??
    item.metrics?.conviction_score ??
    item.metrics?.confidence

  if (typeof raw === 'number' && !isNaN(raw)) return raw
  if (typeof raw === 'string') {
    const parsed = parseFloat(raw.replace(/[^\d.]/g, ''))
    if (!isNaN(parsed)) return parsed
  }
  return null
}

/**
 * Parses a raw search string into structured directives and free-text terms
 */
export function parseSearchQuery(query) {
  const trimmed = (query || '').trim()
  if (!trimmed) {
    return {
      raw: query || '',
      trimmed: '',
      hasDirectives: false,
      directives: {
        symbols: [],
        strikes: [],
        minRR: null,
        minScore: null,
        directions: [],
        stages: [],
        sectors: [],
        categories: [],
      },
      terms: [],
      resolvedSymbols: [],
    }
  }

  const tokens = trimmed.split(/\s+/)
  const symbols = []
  const strikes = []
  let minRR = null
  let minScore = null
  const directions = []
  const stages = []
  const sectors = []
  const categories = []
  const terms = []
  const resolvedSymbols = []

  let hasDirectives = false

  for (const token of tokens) {
    const colonIdx = token.indexOf(':')
    if (colonIdx > 0) {
      const key = token.slice(0, colonIdx).toLowerCase()
      const val = token.slice(colonIdx + 1).trim()
      if (val) {
        if (key === 'sym' || key === 'symbol') {
          hasDirectives = true
          const cleanSym = val.replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO):/i, '').toUpperCase()
          symbols.push(cleanSym)
          continue
        }
        if (key === 'strike' || key === 'ce' || key === 'pe') {
          hasDirectives = true
          strikes.push(val.toUpperCase())
          continue
        }
        if (key === 'rr' || key === 'risk_reward') {
          hasDirectives = true
          const parsed = parseNumericThreshold(val)
          if (parsed !== null) minRR = parsed
          continue
        }
        if (key === 'score' || key === 'conf' || key === 'conviction') {
          hasDirectives = true
          const parsed = parseNumericThreshold(val)
          if (parsed !== null) minScore = parsed
          continue
        }
        if (key === 'dir' || key === 'direction') {
          hasDirectives = true
          const vUpper = val.toUpperCase()
          if (vUpper.startsWith('BULL') || vUpper === 'BUY' || vUpper === 'LONG') {
            directions.push('BULLISH')
          } else if (vUpper.startsWith('BEAR') || vUpper === 'SELL' || vUpper === 'SHORT') {
            directions.push('BEARISH')
          } else {
            directions.push(vUpper)
          }
          continue
        }
        if (key === 'stage' || key === 'status') {
          hasDirectives = true
          const vUpper = val.toUpperCase()
          if (vUpper.startsWith('IGNIT')) stages.push('IGNITED')
          else if (vUpper.startsWith('PRIME')) stages.push('PRIMED')
          else if (vUpper.startsWith('STALK')) stages.push('STALK')
          else if (vUpper.startsWith('EARLY') || vUpper.startsWith('WARN')) stages.push('EARLY_WARNING')
          else if (vUpper.startsWith('HIT') || vUpper.startsWith('TARGET') || vUpper.startsWith('T1')) stages.push('TARGET_HIT')
          else if (vUpper.startsWith('INVAL')) stages.push('INVALIDATED')
          else stages.push(vUpper)
          continue
        }
        if (key === 'sec' || key === 'sector') {
          hasDirectives = true
          sectors.push(val.toUpperCase())
          continue
        }
        if (key === 'cat' || key === 'type' || key === 'setup') {
          hasDirectives = true
          categories.push(val.toUpperCase())
          continue
        }
      }
    }

    // Free text term
    terms.push(token)
    // Check if free text term is a company/asset alias or ticker
    const lowerToken = token.toLowerCase()
    if (ALIAS_MAP.has(lowerToken)) {
      resolvedSymbols.push(ALIAS_MAP.get(lowerToken))
    }
  }

  return {
    raw: query,
    trimmed,
    hasDirectives,
    directives: {
      symbols,
      strikes,
      minRR,
      minScore,
      directions,
      stages,
      sectors,
      categories,
    },
    terms,
    resolvedSymbols,
  }
}

/**
 * Deterministic alert matcher against a parsed smart search query
 */
export function matchesSmartSearchAlert(alert, parsedQuery) {
  if (!alert) return false
  if (!parsedQuery || !parsedQuery.trimmed) return true

  const { directives, terms, resolvedSymbols } = parsedQuery

  // Directives matching:
  // 1. Symbol directive
  if (directives.symbols.length > 0) {
    const sym = String(alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO):/i, '').toUpperCase()
    const match = directives.symbols.some((s) => sym.includes(s))
    if (!match) return false
  }

  // 2. Strike directive
  if (directives.strikes.length > 0) {
    const contract = String(alert.contract_symbol || '').toUpperCase()
    const optPlanContract = String(alert.actionable_plan?.option_plan?.contract_symbol || '').toUpperCase()
    const strike = String(alert.strike || alert.option_strike || '')
    const match = directives.strikes.some((st) =>
      contract.includes(st) || optPlanContract.includes(st) || strike.includes(st)
    )
    if (!match) return false
  }

  // 3. Min Risk:Reward directive
  if (directives.minRR !== null) {
    const rr = extractRiskRewardRatio(alert)
    if (rr === null || rr < directives.minRR) return false
  }

  // 4. Min Score directive
  if (directives.minScore !== null) {
    const sc = extractConvictionScore(alert)
    if (sc === null || sc < directives.minScore) return false
  }

  // 5. Direction directive
  if (directives.directions.length > 0) {
    const dir = String(alert.direction || '').toUpperCase()
    const match = directives.directions.some((d) => dir.includes(d))
    if (!match) return false
  }

  // 6. Stage directive
  if (directives.stages.length > 0) {
    const stage = String(alert.stage || alert.target_status || '').toUpperCase()
    const isInv = Boolean(alert.is_invalidated || alert.stage === 'INVALIDATED')
    const match = directives.stages.some((st) => {
      if (st === 'INVALIDATED') return isInv
      if (st === 'TARGET_HIT') {
        return (
          stage === 'T1_ACHIEVED' ||
          stage === 'TARGET_ACHIEVED' ||
          alert.target_status === 'T1_ACHIEVED' ||
          alert.target_status === 'TARGET_ACHIEVED'
        )
      }
      return stage.includes(st)
    })
    if (!match) return false
  }

  // 7. Sector directive
  if (directives.sectors.length > 0) {
    const sec = String(alert.sector || alert.industry || '').toUpperCase()
    const match = directives.sectors.some((s) => sec.includes(s))
    if (!match) return false
  }

  // 8. Category directive
  if (directives.categories.length > 0) {
    const type = String(alert.alert_type || alert.event_type || '').toUpperCase()
    const match = directives.categories.some((c) => type.includes(c))
    if (!match) return false
  }

  // Free text terms matching
  if (terms.length > 0) {
    const sym = String(alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO):/i, '').toUpperCase()
    const contract = String(alert.contract_symbol || alert.actionable_plan?.option_plan?.contract_symbol || '').toUpperCase()
    const headline = String(alert.headline || '').toUpperCase()
    const summary = String(alert.summary || '').toUpperCase()
    const alertType = String(alert.alert_type || alert.event_type || '').toUpperCase()

    // Every free text term must match somewhere (OR with resolved aliases)
    for (const term of terms) {
      const q = term.toUpperCase()
      const matchSym = sym.includes(q)
      const matchContract = contract.includes(q)
      const matchHeadline = headline.includes(q)
      const matchSummary = summary.includes(q)
      const matchType = alertType.includes(q)
      const matchAlias = resolvedSymbols.includes(sym)

      if (!matchSym && !matchContract && !matchHeadline && !matchSummary && !matchType && !matchAlias) {
        return false
      }
    }
  }

  return true
}

/**
 * Candidate matcher for InflectionScannerView
 */
export function matchesSmartSearchCandidate(candidate, parsedQuery) {
  if (!candidate) return false
  if (!parsedQuery || !parsedQuery.trimmed) return true

  const { directives, terms, resolvedSymbols } = parsedQuery

  const sym = String(candidate.symbol || '').toUpperCase()
  const name = String(candidate.name || '').toUpperCase()
  const sector = String(candidate.sector || '').toUpperCase()
  const archetype = String(candidate.archetype_label || candidate.archetype || '').toUpperCase()
  const timing = String(candidate.timing_label || candidate.timing_state || '').toUpperCase()

  // 1. Symbol directive
  if (directives.symbols.length > 0) {
    const match = directives.symbols.some((s) => sym.includes(s))
    if (!match) return false
  }

  // 2. Min Score directive
  if (directives.minScore !== null) {
    const sc = extractConvictionScore(candidate)
    if (sc === null || sc < directives.minScore) return false
  }

  // 3. Min RR directive
  if (directives.minRR !== null) {
    const rr = extractRiskRewardRatio(candidate)
    if (rr === null || rr < directives.minRR) return false
  }

  // 4. Sector directive
  if (directives.sectors.length > 0) {
    const match = directives.sectors.some((s) => sector.includes(s))
    if (!match) return false
  }

  // Free text terms matching
  if (terms.length > 0) {
    for (const term of terms) {
      const q = term.toUpperCase()
      const matchSym = sym.includes(q)
      const matchName = name.includes(q)
      const matchSector = sector.includes(q)
      const matchArch = archetype.includes(q)
      const matchTiming = timing.includes(q)
      const matchAlias = resolvedSymbols.includes(sym)

      if (!matchSym && !matchName && !matchSector && !matchArch && !matchTiming && !matchAlias) {
        return false
      }
    }
  }

  return true
}
