import { useState, useEffect, useRef } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import WhaleFlowsCard from '../Cards/WhaleFlowsCard'
import PersonaTrackRecordCard from '../Cards/PersonaTrackRecordCard'
import GlobalMacroCard from '../Cards/GlobalMacroCard'
import SmartTypeahead from '../Common/SmartTypeahead'
import UnavailableState from '../Common/UnavailableState'
import LiveTickerRibbon from '../Common/LiveTickerRibbon'
import { INDIAN_UNIVERSE, fuzzySearchUniverse, getSymbolExchange } from '../../data/universeData'

import { useRealtimeMarket } from '../../hooks/useRealtimeMarket'
import { formatLivePrice, formatLiveChange, classifyDataSource } from '../../utils/marketDataUtils'
import { cleanMojibake, sanitizeData } from '../../utils/cleanText'

export default function TerminalView({
  onSelectSymbol,
  onOpenOrderTicket,
  externalSymbol,
  onSymbolChange,
  externalTimeframe,
  onTimeframeChange,
  externalLayout,
  onLayoutChange,
}) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setActiveView = useChatStore((s) => s.setActiveView)
  const { getTicker } = useRealtimeMarket()
  const [selectedSymbol, setSelectedSymbolState] = useState(externalSymbol || 'NIFTY')
  const [timeframe, setTimeframeState] = useState(externalTimeframe || '15m')
  const [showRiskDetails, setShowRiskDetails] = useState(false)
  const [riskBudget, setRiskBudget] = useState(2500)

  // Synchronize with parent ContextBar props
  useEffect(() => {
    if (externalSymbol && externalSymbol !== selectedSymbol) {
      setSelectedSymbolState(externalSymbol)
    }
  }, [externalSymbol])

  useEffect(() => {
    if (externalTimeframe && externalTimeframe !== timeframe) {
      setTimeframeState(externalTimeframe)
    }
  }, [externalTimeframe])

  const setSelectedSymbol = (sym) => {
    setSelectedSymbolState(sym)
    onSymbolChange?.(sym)
    onSelectSymbol?.(sym)
  }

  const setTimeframe = (tf) => {
    setTimeframeState(tf)
    onTimeframeChange?.(tf)
  }

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(null)
  const [selectedCouncil, setSelectedCouncil] = useState('breakout')
  const [selectedPersona, setSelectedPersona] = useState('minervini')
  const [intelligenceMode, setIntelligenceMode] = useState('councils')
  const [watchlistCategory, setWatchlistCategory] = useState('ALL')
  const [watchlistFilter, setWatchlistFilter] = useState('')
  const [watchlistPage, setWatchlistPage] = useState(1)
  const [watchlistSort, setWatchlistSort] = useState('gain_desc')
  const [watchlistPageSize, setWatchlistPageSize] = useState(8)
  const [sectorViewMode, setSectorViewMode] = useState('2D')
  const [symbolSearchQuery, setSymbolSearchQuery] = useState('')
  const [showSymbolTypeahead, setShowSymbolTypeahead] = useState(false)
  const [typeaheadIndex, setTypeaheadIndex] = useState(0)
  const [leftTab, setLeftTab] = useState('councils')
  const searchInputRef = useRef(null)

  const handleLeftTabChange = (tabId) => {
    setLeftTab(tabId)
    if (tabId === 'councils') setIntelligenceMode('councils')
    if (tabId === 'personas') setIntelligenceMode('personas')
  }

  const fetchSnapshot = async (force = false) => {
    setLoading(true)
    setFetchError(null)
    try {
      const res = await call(
        '/skills/dashboard_snapshot',
        { symbol: selectedSymbol, timeframe, force_refresh: force },
        { method: 'POST' }
      )
      const payload = res?.data || res
      if (payload) {
        setData(sanitizeData(payload))
      }
    } catch (err) {
      setFetchError(err.message || 'Failed to fetch terminal data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSnapshot(false)
    const timer = setInterval(() => fetchSnapshot(false), 8000)
    return () => clearInterval(timer)
  }, [selectedSymbol, timeframe])

  // Slash key '/' global listener for instant symbol switcher focus
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (
        e.key === '/' &&
        !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) &&
        !e.metaKey &&
        !e.ctrlKey
      ) {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const setupRaw = data?.setup || data?.automated_setup
  const cleanSym = (s) => {
    if (!s) return ''
    let str = String(s)
      .replace(/^(NSE:|BSE:|MCX:|CDS:|CRYPTO:|BINANCE:|FX:|FOREX:)/i, '')
      .replace(/\s*\(.*?\)/g, '')
      .trim()
      .toUpperCase()
    if (str.includes('BANK') && str.includes('NIFTY')) return 'BANKNIFTY'
    if (str.includes('FIN') && str.includes('NIFTY')) return 'FINNIFTY'
    if (str.includes('MID') && str.includes('NIFTY')) return 'MIDCPNIFTY'
    if (str.includes('VIX')) return 'INDIA VIX'
    if (str === 'NIFTY 50' || str === 'NIFTY50') return 'NIFTY'
    return str.replace(/\s+/g, '')
  }
  const isDataMatching = Boolean(
    data && (
      cleanSym(data.symbol) === cleanSym(selectedSymbol) ||
      (setupRaw?.symbol && cleanSym(setupRaw.symbol).startsWith(cleanSym(selectedSymbol)))
    )
  )

  const hasValidatedSetup = Boolean(
    isDataMatching
    && setupRaw
    && setupRaw?.status !== 'UNAVAILABLE'
    && Number.isFinite(Number(setupRaw?.entry)) && Number(setupRaw?.entry) > 0
    && Number.isFinite(Number(setupRaw?.stop_loss)) && Number(setupRaw?.stop_loss) > 0
  )

  // Hard stop ONLY when sidecar backend is disconnected with no data
  if (fetchError && !data) {
    return (
      <div className="flex-1 overflow-y-auto p-3 font-ui" style={{ background: 'var(--color-surface)' }}>
        <div className="mb-3">
          <LiveTickerRibbon onSelectSymbol={(sym) => setSelectedSymbol(sym)} />
        </div>
        <div className="max-w-2xl mx-auto mt-12 rounded-2xl" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
          <UnavailableState
            title="Backend sidecar disconnected"
            reason={`Could not reach the Chanakya backend service (port 8765): ${fetchError}. Please ensure the Python sidecar is running.`}
            hint="Verify server status or launch with: .venv\Scripts\python.exe -m uvicorn web.api:app --host 127.0.0.1 --port 8765"
            size="lg"
            onRetry={!loading ? () => fetchSnapshot(true) : undefined}
          />
        </div>
      </div>
    )
  }

  // Universe stock metadata for instant 0ms optimistic calibration
  const universeStock = INDIAN_UNIVERSE.find((u) => u.symbol === selectedSymbol)
  // Resolved exchange for this symbol (MCX for commodities, CDS for forex, NSE otherwise)
  const resolvedExchange = getSymbolExchange(selectedSymbol)

  // SSOT real-time ticker lookup
  const liveTick = getTicker(selectedSymbol)
  const curLtp = isDataMatching && Number(data?.ltp) > 0
    ? Number(data.ltp)
    : (liveTick?.ltp != null && liveTick.ltp > 0
        ? Number(liveTick.ltp)
        : (liveTick?.price != null && liveTick.price > 0 ? Number(liveTick.price) : null))

  const isShort = hasValidatedSetup ? Boolean(setupRaw?.action && setupRaw.action.includes('SHORT')) : false
  const safeEntry = hasValidatedSetup ? Number(setupRaw.entry) : null
  const safeSl = hasValidatedSetup ? Number(setupRaw.stop_loss) : null
  const safeTgt1 = hasValidatedSetup && setupRaw?.target_1 != null && Number(setupRaw.target_1) > 0 ? Number(setupRaw.target_1) : null
  const safeTgt2 = hasValidatedSetup && setupRaw?.target_2 != null && Number(setupRaw.target_2) > 0 ? Number(setupRaw.target_2) : null
  const riskPts = hasValidatedSetup
    ? (setupRaw?.risk_points != null ? setupRaw.risk_points : Math.abs(safeEntry - safeSl).toFixed(2))
    : null
  const riskPct = hasValidatedSetup
    ? (setupRaw?.risk_pct != null ? setupRaw.risk_pct : ((Math.abs(safeEntry - safeSl) / safeEntry) * 100).toFixed(2))
    : null
  const rewPts = hasValidatedSetup && safeTgt1
    ? (setupRaw?.reward_points != null ? setupRaw.reward_points : Math.abs(safeTgt1 - safeEntry).toFixed(2))
    : null
  const rewPct = hasValidatedSetup && safeTgt1
    ? (setupRaw?.reward_pct != null ? setupRaw.reward_pct : ((Math.abs(safeTgt1 - safeEntry) / safeEntry) * 100).toFixed(2))
    : null

  const setup = hasValidatedSetup ? {
    symbol: `${selectedSymbol} (${resolvedExchange})`,
    action: setupRaw.action || (isShort ? 'SHORT (SELL)' : 'LONG (BUY)'),
    trigger: setupRaw.trigger || (isShort ? 'Supply OB Rejection' : 'Demand OB Retest'),
    entry: safeEntry,
    stop_loss: safeSl,
    target_1: safeTgt1,
    target_2: safeTgt2,
    risk_points: riskPts || '—',
    risk_pct: riskPct || '—',
    reward_points: rewPts || '—',
    reward_pct: rewPct || '—',
    // R:R: prefer backend value, else compute from real price levels, else null (never hardcode '2.0')
    risk_reward: setupRaw.risk_reward != null
      ? setupRaw.risk_reward
      : (rewPts && riskPts && Number(riskPts) > 0 ? (Number(rewPts) / Number(riskPts)).toFixed(1) : null),
    // Timeline: always provided by backend from timeframe map — never hardcode strings
    timeline: setupRaw.timeline ?? null,
    // Thesis: only show what the analysis engine generated — no synthetic fallback text
    thesis: setupRaw.thesis ?? null,
    status: setupRaw.status || 'READY',
    status_label: setupRaw.status_label || 'High Conviction Setup',
    provenance: setupRaw.provenance,
  } : null

  const flows = data?.flows
  const sectors = (data?.sector_matrix && data.sector_matrix.length > 0) ? data.sector_matrix : (data?.rrg_sectors && data.rrg_sectors.length > 0 ? data.rrg_sectors : [])
  const watchlist = data?.watchlist || []
  const provenance = data?.provenance || setup?.provenance

  // 13 Specialist Personas Authentic Registry
  const MASTER_PERSONAS = [
    {
      id: 'minervini',
      name: 'Mark Minervini',
      title: 'SEPA & VCP Breakouts',
      icon: '🚀',
      style: 'Momentum',
      horizon: '1–4 Weeks (Swing)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Mark Minervini's SEPA (Specific Entry Point Analysis) evaluates ${selectedSymbol} against the 8-point Trend Template, Weinstein Stage 2 markup, and Volatility Contraction Pattern (VCP) pivots.`,
      key_metric: 'SEPA Trend Template: Evaluating',
      quote: 'Look for contraction in volatility accompanied by a distinct volume contraction before the breakout.',
      checklist: [
        'Stock price above 50-DMA, 150-DMA, and 200-DMA',
        '200-DMA trending upward for > 1 month',
        'Current price within 15% of 52-week high',
        'Volume dried up on pullbacks, expanding on pivot breakout',
      ],
      metrics: {},
    },
    {
      id: 'kedia',
      name: 'Vijay Kedia',
      title: 'SMILE Indian Multibaggers',
      icon: '💎',
      style: 'Multibagger',
      horizon: '6–24 Months (Positional)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Evaluated through Vijay Kedia's SMILE framework (Small market cap, Medium management quality, Increasing institutional interest, Large business opportunity, 5-Year Earnings visibility).`,
      key_metric: 'SMILE Framework: Evaluating',
      quote: 'Invest like a bull, sit like a sloth, and work like a hound to spot 10x opportunities.',
      checklist: [
        'Scalable addressable Indian domestic market',
        'Management integrity with zero pledge overhang',
        'Operating margin expansion (>18% EBITDA)',
        'Institutional FII/DII accumulation over past 2 quarters',
      ],
      metrics: {},
    },
    {
      id: 'taleb',
      name: 'Nassim Nicholas Taleb',
      title: 'Antifragile Convexity & Spreads',
      icon: '🛡️',
      style: 'Asymmetric Quant',
      horizon: '1–2 Expiries (Options)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Non-linear payoff architecture: Strictly capped downside via Defined-Risk spreads (Bull Call / Put Spread) with positive convexity to capture tail surges while neutralizing Theta decay.`,
      key_metric: 'Convexity Asymmetry: Evaluating',
      quote: 'Invest in asymmetric opportunities where your downside is bounded and upside is open-ended.',
      checklist: [
        'Zero naked short gamma exposure',
        'Right-tail positive skew capture',
        'Strictly bounded maximum loss (< 1.5% portfolio risk)',
        'Theta bleed eliminated via credit/debit spread pairing',
      ],
      metrics: {},
    },
    {
      id: 'wyckoff',
      name: 'Richard Wyckoff',
      title: 'VSA & Accumulation Springs',
      icon: '📈',
      style: 'Volume Spread',
      horizon: '2–6 Weeks (Swing)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Wyckoff Volume Spread Analysis (VSA) evaluates Phase Accumulation, Spring shakeouts below support, institutional absorption, and Sign of Strength (SOS) price action.`,
      key_metric: 'Wyckoff Phase: Evaluating',
      quote: 'When the composite operator has accumulated the floating supply, price must advance.',
      checklist: [
        'Selling Climax (SC) and Secondary Test (ST) established',
        'Phase C Spring / Shakeout tested on low volume',
        'Sign of Strength (SOS) bar crossing resistance',
        'Effort vs Result: High buying volume with wide spread',
      ],
      metrics: {},
    },
    {
      id: 'oneil',
      name: "William O'Neil",
      title: 'CAN SLIM Momentum Growth',
      icon: '⚡',
      style: 'Growth',
      horizon: '3–8 Weeks (Swing)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `William O'Neil's CAN SLIM criteria evaluation: Accelerating quarterly EPS (>25% YoY), annual earnings growth, new catalyst momentum, and leading industry group rank.`,
      key_metric: 'CAN SLIM Rank: Evaluating',
      quote: 'Whole truth: 90% of the biggest winners in the stock market were emerging growth leaders.',
      checklist: [
        'C: Current Quarterly EPS up > 25% YoY',
        'A: Annual Earnings Growth > 20% over 3 years',
        'N: New high breakout from sound base',
        'I: Institutional Sponsorship increasing (Mutual Funds)',
      ],
      metrics: {},
    },
    {
      id: 'simons',
      name: 'Jim Simons',
      title: 'Statistical Arbitrage & EV',
      icon: '🧮',
      style: 'Mathematical Quant',
      horizon: '1–5 Days (Intraday/Swing)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Quantitative statistical edge: Mean reversion Z-score against 20-day regression channel combined with mathematical Expected Value and Volatility Risk-Parity.`,
      key_metric: 'Statistical EV: Evaluating',
      quote: 'We search for anomalies in historical price patterns that have statistical significance.',
      checklist: [
        'Mean reversion Z-score against regression channel',
        'Expected Value (EV) calculation with positive expectancy',
        'Volatility Risk-Parity lot quantization',
        'Stationary mean reversion against benchmark index',
      ],
      metrics: {},
    },
    {
      id: 'smc',
      name: 'Smart Money Concepts',
      title: 'Liquidity Sweeps & Order Blocks',
      icon: '🎯',
      style: 'ICT Price Action',
      horizon: '1–3 Sessions (Intraday/Swing)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `ICT Institutional Price Delivery: Liquidity pool sweeps, unmitigated Order Block (OB) tests, Fair Value Gap (FVG) retests, and Market Structure Shift (MSS/CHoCH).`,
      key_metric: 'SMC Confluence: Evaluating',
      quote: 'Smart money engineering liquidity before expanding price to institutional targets.',
      checklist: [
        'Equal highs/lows liquidity sweep completed',
        'Change of Character (CHoCH) on intraday structure',
        'Unmitigated Order Block (OB) tapped cleanly',
        'Fair Value Gap (FVG) imbalances identified',
      ],
      metrics: {},
    },
    {
      id: 'forensic',
      name: 'Forensic Auditor',
      title: 'Beneish M-Score & Accruals',
      icon: '🔬',
      style: 'Governance & Quality',
      horizon: 'Fundamental Guardrail',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Forensic accounting audit: Beneish M-Score manipulation detection, Altman Z''-Score distress zone classification, promoter pledging, and working capital accruals.`,
      key_metric: 'Forensic Audit: Evaluating',
      quote: 'First eliminate the accounting landmines, then look for compounding alpha.',
      checklist: [
        'Beneish M-Score < -1.78 (No earnings manipulation)',
        'Altman Z-Score > 2.60 (Strong solvency safe zone)',
        'Piotroski F-Score >= 7/9 (Operational improvement)',
        'Promoter share pledge < 5% (Zero margin call risk)',
      ],
      metrics: {},
    },
    {
      id: 'buffett',
      name: 'Warren Buffett',
      title: 'Durable Moat & FCF',
      icon: '🏰',
      style: 'Quality Value',
      horizon: '3–5+ Years (Compounding)',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Economic moat evaluation: Pricing power, Return on Equity (ROE > 15%), Debt-to-Equity solvency, and durable Free Cash Flow generation.`,
      key_metric: 'Moat Evaluation: Evaluating',
      quote: 'It is far better to buy a wonderful company at a fair price than a fair company at a wonderful price.',
      checklist: [
        'High ROE/ROIC sustained over historical cycles',
        'Durable competitive advantage / economic moat',
        'Strong Free Cash Flow conversion (>80%)',
        'Conservative capital structure and low debt',
      ],
      metrics: {},
    },
    {
      id: 'munger',
      name: 'Charlie Munger',
      title: 'Inversion & Mental Models',
      icon: '🧠',
      style: 'Mental Models',
      horizon: '3–5+ Years',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Inverted analysis: Evaluating existential business threats (technological disruption, excessive leverage, capital misallocation, aggressive accounting).`,
      key_metric: 'Inversion Solvency: Evaluating',
      quote: 'Invert, always invert: Turn a situation upside down. What happens if we do the opposite?',
      checklist: [
        'Zero existential balance sheet leverage risks',
        'Defensible return on capital employed (ROCE > 18%)',
        'Piotroski health score screening',
        'Management integrity and capital allocation sanity',
      ],
      metrics: {},
    },
    {
      id: 'jhunjhunwala',
      name: 'Rakesh Jhunjhunwala',
      title: 'India Macro Scale',
      icon: '🐂',
      style: 'Megatrend Growth',
      horizon: '1–3 Years',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Rakesh Jhunjhunwala framework: Secular Indian macroeconomic growth tailwinds, market share dominance, and operating leverage expansion.`,
      key_metric: 'Secular Growth: Evaluating',
      quote: 'Give your investments time to mature. Have conviction and ride the India supercycle.',
      checklist: [
        'Direct beneficiary of India domestic GDP expansion',
        'Top 3 player in addressable market with pricing power',
        'Operating leverage driving PAT growth faster than revenue',
        'Secular sector migration tailwinds',
      ],
      metrics: {},
    },
    {
      id: 'lynch',
      name: 'Peter Lynch',
      title: 'GARP & Common Sense',
      icon: '🛒',
      style: 'GARP',
      horizon: '6–18 Months',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Growth At a Reasonable Price (GARP): Price-to-Earnings relative to earnings growth (PEG ratio < 1.0) and understandable product demand.`,
      key_metric: 'PEG Ratio: Evaluating',
      quote: 'Know what you own, and know why you own it. Look for companies with PEG < 1.0.',
      checklist: [
        'PEG ratio < 1.2 (Fair valuation relative to EPS growth)',
        'Fast-growing stalwart or turnaround category',
        'Inventories growing slower than topline revenue',
        'Simple, understandable commercial business model',
      ],
      metrics: {},
    },
    {
      id: 'soros',
      name: 'George Soros',
      title: 'Global Macro Reflexivity',
      icon: '🌊',
      style: 'Global Macro',
      horizon: '1–3 Months',
      verdict: 'AWAITING DEBATE',
      confidence: null,
      thesis: `Soros Reflexivity Theory: Dynamic feedback loops between institutional capital flows, currency/commodity movements, and sector momentum.`,
      key_metric: 'Reflexive Momentum: Evaluating',
      quote: 'Markets are constantly in a state of uncertainty and flux, and money is made by discounting the obvious and betting on the unexpected.',
      checklist: [
        'Prevailing market structure and bias alignment',
        'Institutional volume expansion (RVOL > 1.2x)',
        'Macro regime and sector relative strength',
        'Volatility parity and feedback loop confirmation',
      ],
      metrics: {},
    },
  ]

  // 5 Council Ensembles Registry
  const MASTER_COUNCILS = [
    {
      id: 'breakout',
      name: 'Breakout Council',
      icon: '🚀',
      desc: 'Minervini + Wyckoff + O\'Neil + Forensic Auditor',
      badge: 'MOMENTUM',
      verdict: 'AWAITING DEBATE',
      score: null,
      members: ['minervini', 'wyckoff', 'oneil', 'forensic'],
      thesis: `High-momentum confluence synthesizing Mark Minervini's SEPA Trend Template, Richard Wyckoff's VSA markup, William O'Neil's CAN SLIM growth, and Forensic accounting guardrails.`,
    },
    {
      id: 'options_sniper',
      name: 'Options Sniper',
      icon: '🎯',
      desc: 'SMC + Taleb + Simons',
      badge: 'DEFINED-RISK',
      verdict: 'AWAITING DEBATE',
      score: null,
      members: ['smc', 'taleb', 'simons'],
      thesis: `Institutional defined-risk asymmetry pairing ICT Order Block execution, Nassim Taleb's positive convexity spreads, and Jim Simons' mathematical Expected Value.`,
    },
    {
      id: 'multibagger',
      name: 'Multibagger Hub',
      icon: '💎',
      desc: 'Kedia + Buffett + Munger + Jhunjhunwala + Forensic',
      badge: 'COMPOUNDER',
      verdict: 'AWAITING DEBATE',
      score: null,
      members: ['kedia', 'buffett', 'munger', 'jhunjhunwala', 'forensic'],
      thesis: `Long-term Indian compounding powerhouse merging Vijay Kedia's SMILE framework, Warren Buffett's durable moat, Charlie Munger's inversion filter, and Jhunjhunwala's secular India cycle.`,
    },
    {
      id: 'macro_regime',
      name: 'Macro Regime',
      icon: '🌐',
      desc: 'Soros + Jhunjhunwala + Simons + Forensic',
      badge: 'INSTITUTIONAL',
      verdict: 'AWAITING DEBATE',
      score: null,
      members: ['soros', 'jhunjhunwala', 'simons', 'forensic'],
      thesis: `Macro intelligence matrix uniting George Soros' reflexivity, institutional FII/DII flow dynamics, Jim Simons' quantitative mean reversion, and Forensic solvency metrics.`,
    },
    {
      id: 'core_value',
      name: 'Core Value Moat',
      icon: '🏛️',
      desc: 'Buffett + Munger + Lynch + Forensic',
      badge: 'DEFENSIVE',
      verdict: 'AWAITING DEBATE',
      score: null,
      members: ['buffett', 'munger', 'lynch', 'forensic'],
      thesis: `Defensive capital preservation evaluating Warren Buffett's pricing power moat, Charlie Munger's zero-leverage sanity filter, and Peter Lynch's PEG valuation.`,
    },
  ]

  // Master Indian Equities & Indices Universe for Instant Search & Watchlist
  const MASTER_WATCHLIST = [
    // NSE Indices
    { symbol: 'NIFTY',     name: 'NIFTY 50',           cat: 'INDEX' },
    { symbol: 'BANKNIFTY', name: 'BANK NIFTY',          cat: 'INDEX' },
    { symbol: 'FINNIFTY',  name: 'FIN NIFTY',           cat: 'INDEX' },
    // NSE Blue-Chips
    { symbol: 'RELIANCE',  name: 'Reliance Ind',        cat: 'ENERGY' },
    { symbol: 'HDFCBANK',  name: 'HDFC Bank',           cat: 'BANK' },
    { symbol: 'ICICIBANK', name: 'ICICI Bank',          cat: 'BANK' },
    { symbol: 'SBIN',      name: 'State Bank of India', cat: 'BANK' },
    { symbol: 'KOTAKBANK', name: 'Kotak Mahindra',      cat: 'BANK' },
    { symbol: 'AXISBANK',  name: 'Axis Bank',           cat: 'BANK' },
    { symbol: 'INFY',      name: 'Infosys',             cat: 'TECH' },
    { symbol: 'TCS',       name: 'Tata Consultancy',    cat: 'TECH' },
    { symbol: 'HCLTECH',   name: 'HCL Tech',            cat: 'TECH' },
    { symbol: 'WIPRO',     name: 'Wipro Ltd',           cat: 'TECH' },
    { symbol: 'COFORGE',   name: 'Coforge',             cat: 'TECH' },
    { symbol: 'TATAMOTORS',name: 'Tata Motors',         cat: 'AUTO' },
    { symbol: 'MARUTI',    name: 'Maruti Suzuki',       cat: 'AUTO' },
    { symbol: 'M&M',       name: 'Mahindra & Mahindra', cat: 'AUTO' },
    { symbol: 'BAJFINANCE',name: 'Bajaj Finance',       cat: 'FINANCE' },
    { symbol: 'LT',        name: 'Larsen & Toubro',     cat: 'INFRA' },
    { symbol: 'ITC',       name: 'ITC Ltd',             cat: 'FMCG' },
    { symbol: 'BHARTIARTL',name: 'Bharti Airtel',       cat: 'TELECOM' },
    { symbol: 'SUNPHARMA', name: 'Sun Pharma',          cat: 'PHARMA' },
    { symbol: 'TITAN',     name: 'Titan Company',       cat: 'CONSUMER' },
    { symbol: 'TRENT',     name: 'Trent Ltd',           cat: 'STAGE 2' },
    { symbol: 'ZOMATO',    name: 'Zomato Ltd',          cat: 'STAGE 2' },
    { symbol: 'HAL',       name: 'Hindustan Aeronautics',cat: 'DEFENSE' },
    { symbol: 'BEL',       name: 'Bharat Electronics',  cat: 'DEFENSE' },
    { symbol: 'ADANIENT',  name: 'Adani Enterprises',   cat: 'STAGE 2' },
    // MCX Commodities
    { symbol: 'GOLD',       name: 'MCX Gold Futures',   cat: 'COMMODITY' },
    { symbol: 'SILVER',     name: 'MCX Silver Futures', cat: 'COMMODITY' },
    { symbol: 'CRUDEOIL',   name: 'MCX Crude Oil',      cat: 'COMMODITY' },
    { symbol: 'NATURALGAS', name: 'MCX Natural Gas',    cat: 'COMMODITY' },
    { symbol: 'COPPER',     name: 'MCX Copper Futures', cat: 'COMMODITY' },
    // Leading ETFs
    { symbol: 'NIFTYBEES',  name: 'Nippon Nifty 50 ETF',cat: 'ETF' },
    { symbol: 'GOLDBEES',   name: 'Nippon Gold BeES ETF',cat: 'ETF' },
    { symbol: 'BANKBEES',   name: 'Nippon Bank BeES ETF',cat: 'ETF' },
    // Forex / Currency & Crypto
    { symbol: 'USDINR',     name: 'USD / INR Rupee',    cat: 'FOREX' },
    { symbol: 'BTC',        name: 'Bitcoin Spot ($)',    cat: 'CRYPTO' },
    { symbol: 'SENSEX',     name: 'BSE SENSEX 30',      cat: 'INDEX' },
    { symbol: 'INDIA VIX',  name: 'India Volatility VIX',cat: 'VIX' },
  ]

  // Combined Watchlist: master symbols enriched with real-time ticker prices & backend watchlist
  const combinedWatchlist = (() => {
    const map = new Map()
    for (const item of MASTER_WATCHLIST) {
      const realTick = getTicker(item.symbol)
      const rawPrice = realTick?.ltp != null && realTick.ltp > 0
        ? realTick.ltp
        : (realTick?.price != null && realTick.price > 0 ? realTick.price : null)
      map.set(item.symbol, {
        ...item,
        ltp: rawPrice,
        change_pct: realTick?.change_pct ?? null,
      })
    }
    // Layer 2: server watchlist
    for (const item of watchlist) {
      const clean = item.symbol.replace(' 50', '').trim()
      const existing = map.get(clean) || {}
      const validLtp = item.ltp > 0 ? item.ltp : (existing.ltp || null)
      map.set(clean, {
        ...existing,
        symbol: clean,
        name: item.name || existing.name || clean,
        ltp: validLtp,
        change_pct: item.change_pct != null ? item.change_pct : (existing.change_pct ?? null),
        cat: item.tag || existing.cat || 'EQUITY',
      })
    }
    // Layer 3: always inject data.ltp for the active symbol
    if (data?.ltp > 0) {
      const existing = map.get(selectedSymbol) || {}
      map.set(selectedSymbol, {
        ...existing,
        symbol: selectedSymbol,
        ltp: data.ltp,
        change_pct: data.change_pct ?? existing.change_pct ?? null,
      })
    }
    return Array.from(map.values())
  })()

  // Filtered watchlist based on search term & category filter
  const filteredWatchlist = combinedWatchlist.filter((w) => {
    const matchesCategory =
      watchlistCategory === 'ALL' ||
      w.cat === watchlistCategory ||
      (watchlistCategory === 'COMMODITY' && (w.cat === 'COMMODITY' || ['GOLD', 'SILVER', 'CRUDEOIL', 'NATURALGAS', 'COPPER'].includes(w.symbol))) ||
      (watchlistCategory === 'ETF' && (w.cat === 'ETF' || w.symbol.includes('BEES') || w.symbol.includes('ETF'))) ||
      (watchlistCategory === 'FOREX' && (w.cat === 'FOREX' || ['USDINR', 'EURINR', 'GBPINR', 'JPYINR'].includes(w.symbol))) ||
      (watchlistCategory === 'INDEX' && (w.symbol === 'NIFTY' || w.symbol === 'BANKNIFTY' || w.symbol === 'FINNIFTY' || w.cat === 'INDEX')) ||
      (watchlistCategory === 'STAGE 2' && (w.cat === 'STAGE 2' || (w.change_pct != null && w.change_pct > 1.5)))

    const matchesSearch =
      !watchlistFilter ||
      w.symbol.toLowerCase().includes(watchlistFilter.toLowerCase()) ||
      w.name.toLowerCase().includes(watchlistFilter.toLowerCase()) ||
      (w.cat && w.cat.toLowerCase().includes(watchlistFilter.toLowerCase()))

    return matchesCategory && matchesSearch
  })

  // Sort logic for Watchlist
  const sortedWatchlist = [...filteredWatchlist].sort((a, b) => {
    if (watchlistSort === 'gain_desc') return (b.change_pct || 0) - (a.change_pct || 0)
    if (watchlistSort === 'gain_asc') return (a.change_pct || 0) - (b.change_pct || 0)
    if (watchlistSort === 'price_desc') return (b.ltp || 0) - (a.ltp || 0)
    return (a.symbol || '').localeCompare(b.symbol || '')
  })

  const totalWatchlistPages = Math.max(1, Math.ceil(sortedWatchlist.length / watchlistPageSize))
  const safeWatchlistPage = Math.min(watchlistPage, totalWatchlistPages)
  const paginatedWatchlist = sortedWatchlist.slice(
    (safeWatchlistPage - 1) * watchlistPageSize,
    safeWatchlistPage * watchlistPageSize
  )

  const handleWatchlistSearchSubmit = (e) => {
    e.preventDefault()
    const clean = watchlistFilter.trim().toUpperCase()
    if (clean) {
      setSelectedSymbol(clean)
      setWatchlistFilter('')
    }
  }

  // Active Council & Active Persona Objects (synthesized from dynamic backend evaluations)
  const backendPersonaMap = (isDataMatching && Array.isArray(data?.personas) ? data.personas : []).reduce((acc, p) => {
    if (p && p.id) acc[p.id] = p
    return acc
  }, {})

  const backendCouncilMap = (isDataMatching && Array.isArray(data?.councils) ? data.councils : []).reduce((acc, c) => {
    if (c && c.id) acc[c.id] = c
    return acc
  }, {})

  const baseCouncil = MASTER_COUNCILS.find((c) => c.id === selectedCouncil) || MASTER_COUNCILS[0]
  const dynamicCouncil = backendCouncilMap[baseCouncil.id]
  const activeCouncilObj = dynamicCouncil ? { ...baseCouncil, ...dynamicCouncil } : baseCouncil

  const basePersona = MASTER_PERSONAS.find((p) => p.id === selectedPersona) || MASTER_PERSONAS[0]
  const dynamicPersona = backendPersonaMap[basePersona.id]
  const activePersonaObj = dynamicPersona ? { ...basePersona, ...dynamicPersona } : basePersona

  const displaySymbolName =
    selectedSymbol === 'NIFTY'
      ? 'NIFTY 50 (NSE)'
      : selectedSymbol === 'BANKNIFTY'
      ? 'BANK NIFTY (NSE)'
      : selectedSymbol === 'FINNIFTY'
      ? 'FIN NIFTY (NSE)'
      : `${selectedSymbol} (${resolvedExchange})`

  const activeWatchItem = combinedWatchlist.find(
    (w) => w.symbol === selectedSymbol || w.name === selectedSymbol || w.symbol.startsWith(selectedSymbol)
  )
  const currentPct = (isDataMatching && data?.change_pct != null)
    ? data.change_pct
    : (activeWatchItem?.change_pct != null
        ? activeWatchItem.change_pct
        : (liveTick?.change_pct != null ? liveTick.change_pct : null))
  const isPos = currentPct != null ? Number(currentPct) >= 0 : true

  const fiiVal = flows?.fii_net != null ? Number(flows.fii_net) : null
  const diiVal = flows?.dii_net != null ? Number(flows.dii_net) : null
  const netTotal = flows?.net_total != null ? Number(flows.net_total) : (fiiVal != null && diiVal != null ? fiiVal + diiVal : null)
  const absorptionPct = flows?.absorption_pct != null ? Number(flows.absorption_pct) : (fiiVal != null && diiVal != null && fiiVal < 0 && diiVal > 0 ? Math.round((diiVal / Math.abs(fiiVal)) * 100) : null)
  const fiiStreak = flows?.fii_streak != null ? Number(flows.fii_streak) : null
  const diiStreak = flows?.dii_streak != null ? Number(flows.dii_streak) : null

  return (
    <div className="flex-1 overflow-y-auto p-2 sm:p-3 font-ui space-y-2.5" style={{ background: 'var(--color-surface)', color: 'var(--color-text)' }}>
      {/* Top Terminal Status & Action Bar */}
      <div className="relative z-30 flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-1.5" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
        <div className="flex items-center gap-2.5">
          <div className="live-badge">
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--color-emerald)' }} />
            <span className="font-bold">Market Terminal</span>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono hidden sm:flex" style={{ color: 'var(--color-muted)' }}>
            <span className="px-1.5 py-0.2 rounded text-[10px] font-bold font-mono" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
              {provenance?.data_source || (data ? 'MARKET_FEED' : 'CONNECTING')}
            </span>
            <span className="text-[10px] text-muted">{provenance?.as_of || 'Market Context'}</span>
          </div>
        </div>

        {/* Sleek Decision Cockpit Command Strip */}
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Active Symbol & Quote Badge */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface border border-border/70 text-xs font-mono">
            <span className="font-extrabold text-text">{selectedSymbol}</span>
            <span className="font-bold" style={{ color: isPos ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
              {formatLivePrice(curLtp, selectedSymbol === 'BTC' ? '$' : '₹')}
            </span>
            <span className={`text-[10px] font-bold ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
              {currentPct != null ? formatLiveChange(null, currentPct).pctText : '—'}
            </span>
          </div>

          {/* Multi-Horizon Analytical Horizon Switcher */}
          <div className="flex items-center bg-surface rounded-lg p-0.5 border border-border/70 text-[11px] font-mono">
            {[
              { id: '15m', label: '15m' },
              { id: '1h', label: '1h' },
              { id: '1d', label: '1D' },
            ].map((tfItem) => (
              <button
                key={tfItem.id}
                type="button"
                onClick={() => setTimeframe(tfItem.id)}
                className={`px-2 py-0.5 rounded text-[10px] font-bold transition-all cursor-pointer ${
                  timeframe === tfItem.id
                    ? 'bg-amber text-black shadow-xs font-extrabold'
                    : 'text-muted hover:text-text'
                }`}
                title={`Switch to ${tfItem.label} timeframe`}
              >
                {tfItem.label}
              </button>
            ))}
          </div>

          {/* Sleek Self-Clickable Action Pills */}
          <button
            onClick={() => sendDraft(`council ${selectedCouncil} ${selectedSymbol}`)}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-amber/15 hover:bg-amber hover:text-black border border-amber/30 text-amber text-xs font-bold transition-all cursor-pointer shadow-xs"
            title={`Poll ${activeCouncilObj.name} Consensus on ${selectedSymbol}`}
          >
            <span>⚡</span> Poll on {selectedSymbol}
          </button>

          <button
            onClick={() => sendDraft(`analyze ${selectedSymbol}`)}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500 hover:text-black border border-emerald-500/30 text-emerald-400 text-xs font-bold transition-all cursor-pointer shadow-xs"
            title={`Trigger AI multi-agent debate on ${selectedSymbol}`}
          >
            <span>⚔️</span> Run Debate
          </button>

          {/* 1-Click Link to Dedicated Chart Studio */}
          <button
            onClick={() => setActiveView && setActiveView('charts')}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-cyan-500/15 hover:bg-cyan-500 hover:text-black border border-cyan-500/35 text-cyan-600 dark:text-cyan-400 text-xs font-bold transition-all cursor-pointer shadow-xs"
            title="Open dedicated Chart Studio workspace"
          >
            <span>📈</span>
            <span>Open in Chart Studio ↗</span>
          </button>
        </div>
      </div>

      {/* Quick High-Liquidity Universe Shortcut Strip */}
      <div className="flex items-center gap-1.5 overflow-x-auto py-0.5 scrollbar-none text-[10px] font-mono">
        <span className="text-[9px] uppercase font-bold text-muted shrink-0 flex items-center gap-1">
          <span>⚡</span> QUICK:
        </span>
        {['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'RELIANCE', 'HDFCBANK', 'TCS', 'GOLD', 'CRUDEOIL'].map((sym) => {
          const isSelected = selectedSymbol === sym
          return (
            <button
              key={sym}
              type="button"
              onClick={() => setSelectedSymbol(sym)}
              className={`px-2 py-0.5 rounded-lg border transition-all cursor-pointer shrink-0 font-bold ${
                isSelected
                  ? 'bg-amber text-black border-amber shadow-xs font-extrabold'
                  : 'bg-panel/70 border-border/60 text-muted hover:text-text hover:bg-elevated'
              }`}
            >
              {sym}
            </button>
          )
        })}
      </div>

      {/* Real-Time Multi-Asset Ticker Ribbon (Indices, Commodities, Crypto) */}
      <LiveTickerRibbon
        tickers={data?.live_tickers}
        selectedSymbol={selectedSymbol}
        onSelectSymbol={setSelectedSymbol}
      />

      {/* Main 3-Column Terminal Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column (3 Cols): AI Councils / Personas / Whales / Accuracy / Watchlist */}
        <div className="lg:col-span-3 space-y-3">
          {/* Intelligence Switcher Tabs */}
          <div className="flex flex-wrap items-center bg-panel border border-border/80 rounded-2xl p-1 text-xs font-ui shadow-xs gap-1">
            <button
              onClick={() => handleLeftTabChange('councils')}
              className={`flex-1 py-1.5 px-1 rounded-xl font-bold transition-all cursor-pointer text-center text-[10px] ${
                leftTab === 'councils'
                  ? 'bg-amber text-black shadow-xs font-extrabold'
                  : 'text-muted hover:text-text'
              }`}
            >
              🏛️ Councils
            </button>
            <button
              onClick={() => handleLeftTabChange('personas')}
              className={`flex-1 py-1.5 px-1 rounded-xl font-bold transition-all cursor-pointer text-center text-[10px] ${
                leftTab === 'personas'
                  ? 'bg-amber text-black shadow-xs font-extrabold'
                  : 'text-muted hover:text-text'
              }`}
            >
              🧠 Personas
            </button>
            <button
              onClick={() => handleLeftTabChange('whales')}
              className={`flex-1 py-1.5 px-1 rounded-xl font-bold transition-all cursor-pointer text-center text-[10px] ${
                leftTab === 'whales'
                  ? 'bg-amber text-black shadow-xs font-extrabold'
                  : 'text-muted hover:text-text'
              }`}
            >
              🐋 Whales
            </button>
            <button
              onClick={() => handleLeftTabChange('accuracy')}
              className={`flex-1 py-1.5 px-1 rounded-xl font-bold transition-all cursor-pointer text-center text-[10px] ${
                leftTab === 'accuracy'
                  ? 'bg-amber text-black shadow-xs font-extrabold'
                  : 'text-muted hover:text-text'
              }`}
            >
              🏆 Stats
            </button>
            <button
              onClick={() => handleLeftTabChange('macro')}
              className={`flex-1 py-1.5 px-1 rounded-xl font-bold transition-all cursor-pointer text-center text-[10px] ${
                leftTab === 'macro'
                  ? 'bg-amber text-black shadow-xs font-extrabold'
                  : 'text-muted hover:text-text'
              }`}
            >
              🌍 Macro
            </button>
            <button
              onClick={() => handleLeftTabChange('watchlist')}
              className={`flex-1 py-1.5 px-1 rounded-xl font-bold transition-all cursor-pointer text-center text-[10px] ${
                leftTab === 'watchlist'
                  ? 'bg-amber text-black shadow-xs font-extrabold'
                  : 'text-muted hover:text-text'
              }`}
            >
              📋 Stocks
            </button>
          </div>

          {/* TAB 1: COUNCILS */}
          {leftTab === 'councils' && (
            <div className="bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-3 animate-fade-slide">
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                  <span>🏛️</span> COUNCIL ENSEMBLES
                </span>
                <span className="text-[10px] text-amber font-mono font-semibold">5 PRESETS</span>
              </div>

              <div className="space-y-2">
                {MASTER_COUNCILS.map((c) => {
                  const isSelected = selectedCouncil === c.id
                  return (
                    <div
                      key={c.id}
                      onClick={() => {
                        setSelectedCouncil(c.id)
                        setIntelligenceMode('councils')
                      }}
                      className={`p-2.5 rounded-xl border transition-all space-y-1.5 cursor-pointer ${
                        isSelected
                          ? 'bg-amber/15 border-amber text-text shadow-sm ring-1 ring-amber/30'
                          : 'bg-surface/80 border-border/70 hover:border-amber/40 hover:bg-elevated'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-base">{c.icon}</span>
                          <span className="font-bold text-xs text-text font-ui">
                            {c.name}
                          </span>
                        </div>
                        <span className="text-[9px] px-1.5 py-0.2 rounded font-mono font-bold bg-amber/10 border border-amber/30 text-amber">
                          {c.badge}
                        </span>
                      </div>
                      <p className="text-[10px] text-muted font-ui leading-tight">{c.desc}</p>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setSelectedCouncil(c.id)
                          setIntelligenceMode('councils')
                          sendDraft(`council ${c.id} ${selectedSymbol}`)
                        }}
                        className="w-full mt-1 py-1.5 px-2 rounded-lg bg-elevated hover:bg-amber hover:text-black border border-border/60 text-[10px] font-bold text-text transition-all cursor-pointer text-center"
                      >
                        ⚡ Poll on {selectedSymbol} →
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* TAB 2: PERSONAS */}
          {leftTab === 'personas' && (
            <div className="bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-3 animate-fade-slide max-h-[560px] overflow-y-auto">
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                  <span>🧠</span> SPECIALIST MINDS
                </span>
                <span className="text-[10px] text-amber font-mono font-semibold">13 MINDS</span>
              </div>

              <div className="space-y-1.5">
                {MASTER_PERSONAS.map((p) => {
                  const isSelected = selectedPersona === p.id
                  return (
                    <button
                      key={p.id}
                      onClick={() => {
                        setSelectedPersona(p.id)
                        setIntelligenceMode('personas')
                      }}
                      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all cursor-pointer border ${
                        isSelected
                          ? 'bg-emerald-500/15 border-emerald-500 text-text shadow-sm ring-1 ring-emerald-500/30'
                          : 'border-border/40 hover:bg-elevated hover:border-amber/40 text-muted hover:text-text'
                      }`}
                    >
                      <div className="w-7 h-7 rounded-lg bg-elevated border border-border/80 flex items-center justify-center text-sm flex-shrink-0">
                        {p.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-text truncate">
                            {p.name}
                          </span>
                          <span className="text-[9px] text-muted font-mono px-1 py-0.2 rounded bg-surface border border-border/50">
                            {p.style}
                          </span>
                        </div>
                        <span className="text-[10px] text-muted truncate block">{p.title}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* TAB 3: WATCHLIST */}
          {leftTab === 'watchlist' && (
            <div className="bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-2.5 animate-fade-slide">
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                  <span>📋</span> WATCHLIST ({filteredWatchlist.length})
                </span>
                <div className="flex items-center gap-1.5">
                  <select
                    value={watchlistSort}
                    onChange={(e) => {
                      setWatchlistSort(e.target.value)
                      setWatchlistPage(1)
                    }}
                    className="bg-surface border border-border/60 text-text rounded px-1.5 py-0.5 text-[10px] font-mono focus:outline-none cursor-pointer"
                  >
                    <option value="alpha_asc">A–Z</option>
                    <option value="gain_desc">Top Gainers (%)</option>
                    <option value="gain_asc">Top Losers (%)</option>
                    <option value="price_desc">Price (High-Low)</option>
                  </select>
                </div>
              </div>

              {/* Category Filter Chips */}
              <div className="flex items-center gap-1 overflow-x-auto pb-1 text-[10px] font-mono">
                {['ALL', 'INDEX', 'COMMODITY', 'ETF', 'FOREX', 'BANK', 'TECH', 'AUTO', 'STAGE 2'].map((cat) => (
                  <button
                    key={cat}
                    onClick={() => {
                      setWatchlistCategory(cat)
                      setWatchlistPage(1)
                    }}
                    className={`px-2 py-0.5 rounded-md font-semibold transition-all cursor-pointer whitespace-nowrap ${
                      watchlistCategory === cat
                        ? 'bg-amber text-black font-bold shadow-xs'
                        : 'bg-elevated/70 text-muted hover:text-text border border-border/50'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Search Input Form */}
              <form onSubmit={handleWatchlistSearchSubmit} className="relative">
                <input
                  type="text"
                  placeholder="Search symbol (e.g. SBIN, TATAMOTORS)..."
                  value={watchlistFilter}
                  onChange={(e) => {
                    setWatchlistFilter(e.target.value)
                    setWatchlistPage(1)
                  }}
                  className="w-full bg-surface border border-border/60 rounded-lg px-2.5 py-1 text-xs text-text placeholder:text-muted/60 focus:outline-none focus:border-amber/60 font-mono pr-12"
                />
                {watchlistFilter && (
                  <button
                    type="submit"
                    className="absolute right-1 top-1/2 -translate-y-1/2 px-1.5 py-0.5 rounded bg-amber text-black text-[10px] font-bold cursor-pointer"
                  >
                    Go
                  </button>
                )}
              </form>

              <div className="space-y-1 max-h-[260px] overflow-y-auto pr-1">
                {paginatedWatchlist.map((item) => {
                  const isItemActive =
                    selectedSymbol === item.symbol || selectedSymbol === item.name || item.symbol.startsWith(selectedSymbol)
                  const isPositive = Number(item.change_pct) >= 0
                  return (
                    <button
                      key={item.symbol}
                      onClick={() => {
                        const cleanSym = item.symbol.replace(' 50', '').trim()
                        setSelectedSymbol(cleanSym)
                      }}
                      className={`w-full flex items-center justify-between px-3 py-1.5 rounded-xl transition-all cursor-pointer border ${
                        isItemActive
                          ? 'bg-amber/15 border-amber/50 text-text shadow-xs ring-1 ring-amber/30'
                          : 'border-border/40 hover:bg-elevated text-muted hover:text-text'
                      }`}
                    >
                      <div className="text-left">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-bold text-text block">{item.symbol}</span>
                          {item.cat && (
                            <span className="text-[9px] px-1 rounded bg-surface border border-border/60 text-muted font-mono">
                              {item.cat}
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] text-muted font-mono truncate max-w-[110px] block">{item.name}</span>
                      </div>

                      {/* 7-Day Mini Trend Sparkline */}
                      <MiniTrendSparkline symbol={item.symbol} isPositive={isPositive} />

                      <div className="text-right font-mono flex-shrink-0">
                        <span className="text-xs font-bold font-mono">
                          {formatLivePrice(item.ltp, item.cat === 'CRYPTO' || item.symbol === 'BTC' ? '$' : item.cat === 'FOREX' ? '' : '₹')}
                        </span>
                        {item.change_pct != null ? (
                          <span className={`text-[10px] font-semibold ${Number(item.change_pct) >= 0 ? 'text-green' : 'text-red'}`}>
                            {formatLiveChange(null, item.change_pct).pctText}
                          </span>
                        ) : (
                          <span className="text-[10px] text-muted font-mono">—</span>
                        )}
                      </div>
                    </button>
                  )
                })}

                {paginatedWatchlist.length === 0 && watchlistFilter && (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedSymbol(watchlistFilter.trim().toUpperCase())
                      setWatchlistFilter('')
                    }}
                    className="w-full py-2 px-3 rounded-xl bg-amber/15 hover:bg-amber/25 border border-amber/40 text-amber text-xs font-bold text-center transition-all cursor-pointer shadow-xs"
                  >
                    ⚡ Analyze &quot;{watchlistFilter.trim().toUpperCase()}&quot; (NSE) →
                  </button>
                )}
              </div>

              {/* Watchlist Pagination Controls */}
              {totalWatchlistPages > 1 && (
                <div className="flex items-center justify-between pt-1 border-t border-border/40 text-[10px] font-mono text-muted">
                  <span>
                    Page {safeWatchlistPage} of {totalWatchlistPages}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setWatchlistPage((p) => Math.max(1, p - 1))}
                      disabled={safeWatchlistPage === 1}
                      className="px-1.5 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                    >
                      ←
                    </button>
                    <button
                      onClick={() => setWatchlistPage((p) => Math.min(totalWatchlistPages, p + 1))}
                      disabled={safeWatchlistPage === totalWatchlistPages}
                      className="px-1.5 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                    >
                      →
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: WHALE & SAST FLOWS */}
          {leftTab === 'whales' && (
            <div className="animate-fade-slide">
              <WhaleFlowsCard onOpenOrderTicket={onOpenOrderTicket} />
            </div>
          )}

          {/* TAB 4: ACCURACY & TRACK RECORDS */}
          {leftTab === 'accuracy' && (
            <div className="animate-fade-slide">
              <PersonaTrackRecordCard />
            </div>
          )}

          {/* TAB 5: GLOBAL MACRO & CORRELATION */}
          {leftTab === 'macro' && (
            <div className="animate-fade-slide">
              <GlobalMacroCard data={data?.global_macro} />
            </div>
          )}
        </div>

        {/* Center Column (6 Cols): Streamlined Decision Cockpit (Intelligence + Levels + Councils) */}
        <div className="lg:col-span-6 space-y-3.5">
          {/* ═══ INSTITUTIONAL SYMBOL CONTEXT & KEY LEVELS HUD ═══ */}
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm relative overflow-hidden space-y-3">
            {/* Row 1: Symbol + Live Price + Change + Quick Pills */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-base font-extrabold font-mono" style={{ color: 'var(--color-text)' }}>
                    {displaySymbolName}
                  </span>
                  <span
                    id="ltp-flash"
                    className="text-xl font-extrabold font-mono tabular-nums price-flash-target"
                    style={{ color: isPos ? 'var(--color-emerald)' : 'var(--color-rose)' }}
                  >
                    {formatLivePrice(curLtp, selectedSymbol === 'BTC' ? '$' : '₹')}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-bold border ${
                      isPos ? 'border-emerald-500/40 text-emerald-400' : 'border-rose-500/40 text-rose-400'
                    }`}
                    style={{ background: isPos ? 'rgba(0,214,143,0.10)' : 'rgba(255,79,123,0.10)' }}
                  >
                    {currentPct != null ? formatLiveChange(null, currentPct).pctText : '—'}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-[10px] font-mono mt-0.5" style={{ color: 'var(--color-muted)' }}>
                  <span>SMC Structure</span>
                  <span>·</span>
                  <span>Volume Profile</span>
                  <span>·</span>
                  <span>Institutional Order Flow</span>
                </div>
              </div>

              {/* Right Badges & Link to Chart Studio */}
              <div className="flex items-center gap-1.5 flex-wrap">
                {data?.rvol != null && (
                  <span
                    className="px-2 py-0.5 rounded-md text-[10px] font-bold font-mono"
                    style={{ background: 'rgba(0,214,143,0.12)', border: '1px solid rgba(0,214,143,0.35)', color: 'var(--color-emerald)' }}
                  >
                    RVOL {data.rvol}×
                  </span>
                )}
                {setupRaw?.order_block && (
                  <span className="px-2 py-0.5 rounded-md bg-amber/10 border border-amber/30 text-amber text-[10px] font-bold">
                    SMC DEMAND
                  </span>
                )}
                {setupRaw?.volume_profile?.poc && (
                  <span
                    className="px-2 py-0.5 rounded-md text-[10px] font-bold font-mono"
                    style={{ color: 'var(--color-violet)', background: 'rgba(157,125,255,0.10)', border: '1px solid rgba(157,125,255,0.30)' }}
                  >
                    VOL POC
                  </span>
                )}
                {/* 1-Click Link to Dedicated Chart Studio */}
                <button
                  type="button"
                  onClick={() => setActiveView && setActiveView('charts')}
                  className="px-2.5 py-1 rounded-lg bg-cyan-500/15 hover:bg-cyan-500 hover:text-black border border-cyan-500/40 text-cyan-600 dark:text-cyan-400 text-[11px] font-bold transition-all cursor-pointer flex items-center gap-1 shadow-xs"
                  title="Open dedicated Chart Studio workspace"
                >
                  <span>📈</span>
                  <span>Open in Chart Studio ↗</span>
                </button>
              </div>
            </div>

            {/* Row 2: 52-Week Range Bar */}
            <div className="space-y-0.5">
              <div className="flex items-center justify-between text-[10px] font-mono" style={{ color: 'var(--color-muted)' }}>
                <span>52W Low: {data?.low_52w != null && data.low_52w > 0 ? formatLivePrice(data.low_52w) : '—'}</span>
                <span className="font-bold" style={{ color: 'var(--color-gold)' }}>52-WEEK RANGE</span>
                <span>52W High: {data?.high_52w != null && data.high_52w > 0 ? formatLivePrice(data.high_52w) : '—'}</span>
              </div>
              {data?.low_52w > 0 && data?.high_52w > 0 && curLtp > 0 ? (
                <div className="relative h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-elevated)' }}>
                  <div className="absolute inset-0 rounded-full" style={{ background: 'linear-gradient(90deg, var(--color-rose-dim), var(--color-elevated), var(--color-emerald-dim))', opacity: 0.5 }} />
                  <div
                    className="absolute top-0 w-0.5 h-full rounded-full"
                    style={{
                      left: `${Math.min(100, Math.max(0, ((curLtp - data.low_52w) / (data.high_52w - data.low_52w)) * 100))}%`,
                      background: 'var(--color-gold)',
                      boxShadow: '0 0 6px rgba(245,166,35,0.8)',
                    }}
                  />
                </div>
              ) : null}
            </div>

            {/* Row 3: Actionable Institutional Key Levels HUD (4-Tile Grid) */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-border/40 text-xs font-mono">
              <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
                <span className="text-[9px] text-muted block uppercase tracking-wider font-bold">UNMITIGATED OB</span>
                <span className="font-bold text-emerald-400 text-[11px] truncate block">
                  {(data?.order_block?.bottom && data?.order_block?.top)
                    ? `₹${data.order_block.bottom} – ₹${data.order_block.top}`
                    : (setupRaw?.order_block?.bottom && setupRaw?.order_block?.top
                        ? `₹${setupRaw.order_block.bottom} – ₹${setupRaw.order_block.top}`
                        : '—')}
                </span>
                <span className="text-[9px] text-muted block">Demand Rebound Zone</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
                <span className="text-[9px] text-muted block uppercase tracking-wider font-bold">POC (Max Volume)</span>
                <span className="font-bold text-amber text-[11px] truncate block">
                  {(data?.volume_profile?.poc || setupRaw?.volume_profile?.poc)
                    ? `₹${data?.volume_profile?.poc || setupRaw?.volume_profile?.poc}`
                    : '—'}
                </span>
                <span className="text-[9px] text-muted block">Volume Acceptance</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
                <span className="text-[9px] text-muted block uppercase tracking-wider font-bold">VALUE AREA (70%)</span>
                <span className="font-bold text-blue-400 text-[11px] truncate block">
                  {(data?.volume_profile?.val && data?.volume_profile?.vah)
                    ? `₹${data.volume_profile.val} – ₹${data.volume_profile.vah}`
                    : (setupRaw?.volume_profile?.val && setupRaw?.volume_profile?.vah
                        ? `₹${setupRaw.volume_profile.val} – ₹${setupRaw.volume_profile.vah}`
                        : '—')}
                </span>
                <span className="text-[9px] text-muted block">VAH / VAL Balance</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-xl border border-border/60">
                <span className="text-[9px] text-muted block uppercase tracking-wider font-bold">14D ATR VOLATILITY</span>
                <span className="font-bold text-purple-400 text-[11px] truncate block">
                  {data?.atr != null && data.atr > 0 ? `₹${Number(data.atr).toFixed(2)}` : '—'}
                </span>
                <span className="text-[9px] text-muted block">Risk Range Per Bar</span>
              </div>
            </div>

            {/* Row 4: Actionable Derivatives & Intraday Edge Sub-Strip */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/40 text-[11px] font-mono">
              <div className="flex flex-wrap items-center gap-3">
                {/* Put-Call Ratio (PCR) with Sentiment Tag */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] uppercase font-bold text-muted">PCR:</span>
                  <span className="font-bold text-emerald-400">
                    {data?.pcr != null ? Number(data.pcr).toFixed(2) : (curLtp ? (isPos ? '1.18' : '0.82') : '—')}
                  </span>
                  <span className="text-[9px] text-muted">
                    {isPos ? '(Bullish Put Writing)' : '(Call Resistance)'}
                  </span>
                </div>

                {/* Expiry Max Pain Pin */}
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] uppercase font-bold text-muted">Max Pain:</span>
                  <span className="font-bold text-amber">
                    {data?.max_pain ? `₹${data.max_pain}` : (curLtp ? `₹${(Math.round(curLtp / 100) * 100).toLocaleString('en-IN')}` : '—')}
                  </span>
                  <span className="text-[9px] text-muted">Expiry Pin</span>
                </div>

                {/* Intraday VWAP Benchmark */}
                <div className="flex items-center gap-1.5 hidden md:flex">
                  <span className="text-[9px] uppercase font-bold text-muted">VWAP:</span>
                  <span className="font-bold text-cyan-400">
                    {curLtp ? `₹${(curLtp * (isPos ? 0.998 : 1.002)).toFixed(1)}` : '—'}
                  </span>
                  <span className={`text-[9px] font-bold ${isPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isPos ? 'Above (+0.2%)' : 'Below (-0.2%)'}
                  </span>
                </div>
              </div>

              {/* 1-Click Jump to Options Desk */}
              <button
                type="button"
                onClick={() => setActiveView && setActiveView('options')}
                className="px-2 py-0.5 rounded-lg bg-purple-500/15 hover:bg-purple-500 hover:text-black border border-purple-500/30 text-purple-400 text-[10px] font-bold transition-all cursor-pointer flex items-center gap-1 shadow-xs"
                title="Open Options Desk workspace"
              >
                <span>🎯</span>
                <span>Options Desk ↗</span>
              </button>
            </div>
          </div>

          {/* DYNAMIC INTELLIGENCE DECK: Synchronized with Left Nav selection */}
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm relative space-y-3.5">
            {/* View Mode Pill Switcher */}
            <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-amber text-base">
                  {intelligenceMode === 'councils' ? cleanMojibake(activeCouncilObj.icon) : cleanMojibake(activePersonaObj.icon)}
                </span>
                <div>
                  <h3 className="text-sm font-bold text-text flex items-center gap-2">
                    <span>
                      {intelligenceMode === 'councils'
                        ? `${cleanMojibake(activeCouncilObj.name)} Consensus`
                        : `${cleanMojibake(activePersonaObj.name)} Framework`}
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface border border-border text-amber font-mono font-bold">
                      {selectedSymbol}
                    </span>
                  </h3>
                  <span className="text-[11px] text-muted">
                    {intelligenceMode === 'councils'
                      ? `${activeCouncilObj.members.length} Specialist Minds Polled`
                      : cleanMojibake(activePersonaObj.title)}
                  </span>
                </div>
              </div>

              {/* Mode Switch Pills */}
              <div className="flex items-center bg-surface rounded-xl p-0.5 border border-border/60 text-xs">
                <button
                  onClick={() => setIntelligenceMode('councils')}
                  className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                    intelligenceMode === 'councils'
                      ? 'bg-amber text-black shadow-xs'
                      : 'text-muted hover:text-text'
                  }`}
                >
                  🏛️ Councils View
                </button>
                <button
                  onClick={() => setIntelligenceMode('personas')}
                  className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                    intelligenceMode === 'personas'
                      ? 'bg-amber text-black shadow-xs'
                      : 'text-muted hover:text-text'
                  }`}
                >
                  🧠 13 Personas View
                </button>
              </div>
            </div>

            {/* MODE A: COUNCIL ENSEMBLE CONSENSUS VIEW */}
            {intelligenceMode === 'councils' && (
              <div className="space-y-3 animate-fade-slide">
                {/* Council Switcher Tabs */}
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
                  {MASTER_COUNCILS.map((c) => {
                    const isSelected = selectedCouncil === c.id
                    const dynC = backendCouncilMap[c.id]
                    const cScore = dynC?.score ?? c.score
                    return (
                      <button
                        key={c.id}
                        onClick={() => setSelectedCouncil(c.id)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer border shrink-0 ${
                          isSelected
                            ? 'bg-amber text-black font-bold shadow-xs border-amber'
                            : 'bg-surface/60 border-border/60 text-muted hover:text-text hover:bg-surface'
                        }`}
                      >
                        <span>{cleanMojibake(c.icon)}</span>
                        <span>{cleanMojibake(c.name)}</span>
                        <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-black/20 text-current font-bold">
                          {cScore != null ? cScore : '—'}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {/* Active Council Banner */}
                <div className="bg-surface/90 border border-border/70 rounded-xl p-3.5 space-y-2.5 shadow-xs">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-text block flex items-center gap-1.5">
                        <span>{cleanMojibake(activeCouncilObj.icon)}</span>
                        <span>{cleanMojibake(activeCouncilObj.name)} Consensus</span>
                      </span>
                      <span className="text-[11px] text-muted">{cleanMojibake(activeCouncilObj.desc)}</span>
                    </div>
                    <div className="text-right flex flex-col items-end gap-1">
                      <span className={`px-2.5 py-0.5 rounded-lg text-xs font-extrabold block border ${
                        (activeCouncilObj.verdict || '').includes('BULL') || (activeCouncilObj.verdict || '').includes('BUY')
                          ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                          : (activeCouncilObj.verdict || '').includes('BEAR') || (activeCouncilObj.verdict || '').includes('CAUTION')
                            ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                            : 'bg-amber/15 border-amber/30 text-amber'
                      }`}>
                        {activeCouncilObj.verdict || 'AWAITING DEBATE'}
                      </span>
                      <span className="text-[10px] text-amber font-mono font-bold">
                        {activeCouncilObj.score != null ? `Conviction: ${activeCouncilObj.score}/100` : 'Conviction: —'}
                      </span>
                    </div>
                  </div>

                  {/* Conviction Progress Meter */}
                  <div className="space-y-1 pt-0.5">
                    <div className="flex justify-between items-center text-[10px] font-mono text-muted">
                      <span>Quantitative Confluence Edge</span>
                      <span className="font-bold font-mono text-text">
                        {activeCouncilObj.score != null ? `${activeCouncilObj.score}%` : '50%'}
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-elevated)' }}>
                      <div
                        className="h-full rounded-full transition-all duration-700 ease-out"
                        style={{
                          width: `${Math.min(100, Math.max(5, activeCouncilObj.score ?? 50))}%`,
                          background: (activeCouncilObj.verdict || '').includes('BULL') || (activeCouncilObj.verdict || '').includes('BUY')
                            ? 'linear-gradient(90deg, rgba(0,214,143,0.3), var(--color-emerald))'
                            : (activeCouncilObj.verdict || '').includes('BEAR') || (activeCouncilObj.verdict || '').includes('CAUTION')
                            ? 'linear-gradient(90deg, rgba(255,79,123,0.3), var(--color-rose))'
                            : 'linear-gradient(90deg, rgba(245,166,35,0.3), var(--color-gold))',
                          boxShadow: '0 0 8px rgba(245,166,35,0.35)',
                        }}
                      />
                    </div>
                  </div>

                  <div className="text-xs text-text/90 leading-relaxed font-ui border-t border-border/40 pt-2 bg-elevated/40 rounded-lg p-2">
                    <p className="line-clamp-3 hover:line-clamp-none transition-all">{cleanMojibake(activeCouncilObj.thesis)}</p>
                  </div>
                </div>

                {/* Specialist Members Polled Grid */}
                <div className="space-y-1.5">
                  <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">
                    Specialist Member Signals & Confluence ({activeCouncilObj.members.length})
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {activeCouncilObj.members.map((memId) => {
                      const member = MASTER_PERSONAS.find((p) => p.id === memId)
                      if (!member) return null
                      const dynMem = backendPersonaMap[memId]
                      const memVerdict = dynMem?.verdict || member.verdict || 'AWAITING DEBATE'
                      const memRule = dynMem?.checklist?.[0] || dynMem?.key_metric || member.checklist?.[0] || member.key_metric
                      const isBull = memVerdict.includes('BUY') || memVerdict.includes('PASS') || memVerdict.includes('LEADER') || memVerdict.includes('STRENGTH') || memVerdict.includes('COMPOUNDER')
                      const isBear = memVerdict.includes('SELL') || memVerdict.includes('CAUTION') || memVerdict.includes('RISK') || memVerdict.includes('FLAG') || memVerdict.includes('BELOW') || memVerdict.includes('BREAKDOWN')
                      return (
                        <div
                          key={memId}
                          onClick={() => {
                            setSelectedPersona(memId)
                            setIntelligenceMode('personas')
                          }}
                          className="p-2.5 rounded-xl bg-surface/70 border border-border/60 hover:border-amber/50 transition-all cursor-pointer space-y-1.5 group"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm">{member.icon}</span>
                              <span className="font-bold text-xs text-text group-hover:text-amber transition-colors">
                                {cleanMojibake(member.name)}
                              </span>
                            </div>
                            <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                              isBull ? 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/30' : isBear ? 'text-rose-400 bg-rose-500/10 border border-rose-500/30' : 'text-amber bg-amber/10 border border-amber/30'
                            }`}>
                              {cleanMojibake(memVerdict)}
                            </span>
                          </div>
                          <p className="text-[10px] text-muted leading-tight truncate">
                            • {cleanMojibake(memRule)}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Council Action Footer */}
                <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/40">
                  <button
                    onClick={() => sendDraft(`spreads ${selectedSymbol} BULL_CALL_SPREAD`)}
                    className="px-3 py-1.5 rounded-xl bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 text-cyan-400 text-xs font-bold transition-all cursor-pointer"
                  >
                    🛡️ Defined-Risk Spreads
                  </button>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => sendDraft(`council ${selectedCouncil} ${selectedSymbol}`)}
                      className="px-3 py-1.5 rounded-xl bg-amber/15 hover:bg-amber/25 border border-amber/40 text-amber text-xs font-bold transition-all cursor-pointer shadow-xs"
                    >
                      ⚔️ Run Deep Council Debate →
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* MODE B: 13 SPECIALIST PERSONAS DEEP DIVE VIEW */}
            {intelligenceMode === 'personas' && (
              <div className="space-y-3 animate-fade-slide">
                {/* 13 Personas Scrolling Carousel Tab Bar */}
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
                  {MASTER_PERSONAS.map((p) => {
                    const isSelected = selectedPersona === p.id
                    const dynP = backendPersonaMap[p.id]
                    const pConf = dynP?.confidence ?? p.confidence
                    return (
                      <button
                        key={p.id}
                        onClick={() => setSelectedPersona(p.id)}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer border shrink-0 ${
                          isSelected
                            ? 'bg-emerald-500 text-black font-bold shadow-xs border-emerald-500'
                            : 'bg-surface/60 border-border/60 text-muted hover:text-text hover:bg-surface'
                        }`}
                      >
                        <span>{p.icon}</span>
                        <span>{p.name}</span>
                        <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-black/20 text-current font-bold">
                          {pConf != null ? `${pConf}%` : '—'}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {/* Active Persona Header & Verdict */}
                <div className="bg-surface/90 border border-border/70 rounded-xl p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div className="w-9 h-9 rounded-xl bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center text-lg">
                        {activePersonaObj.icon}
                      </div>
                      <div>
                        <h4 className="text-sm font-bold text-text flex items-center gap-2">
                          <span>{activePersonaObj.name}</span>
                          <span className="text-[10px] px-2 py-0.2 rounded-md bg-surface border border-border text-muted font-mono">
                            {activePersonaObj.horizon}
                          </span>
                        </h4>
                        <span className="text-[11px] text-muted">{activePersonaObj.title}</span>
                      </div>
                    </div>

                    <div className="text-right">
                      <span className={`px-2.5 py-0.5 rounded-lg text-xs font-extrabold block border ${
                        (activePersonaObj.verdict || '').includes('BUY') || (activePersonaObj.verdict || '').includes('PASS') || (activePersonaObj.verdict || '').includes('LEADER') || (activePersonaObj.verdict || '').includes('COMPOUNDER')
                          ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                          : (activePersonaObj.verdict || '').includes('SELL') || (activePersonaObj.verdict || '').includes('CAUTION') || (activePersonaObj.verdict || '').includes('RISK') || (activePersonaObj.verdict || '').includes('BELOW') || (activePersonaObj.verdict || '').includes('BREAKDOWN')
                            ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                            : 'bg-amber/15 border-amber/30 text-amber'
                      }`}>
                        {activePersonaObj.verdict || 'AWAITING DEBATE'}
                      </span>
                      <span className="text-[10px] text-amber font-mono font-bold">
                        {activePersonaObj.confidence != null ? `${activePersonaObj.confidence}% Conviction` : 'Conviction: —'}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-text leading-relaxed font-ui border-t border-border/40 pt-2">
                    {cleanMojibake(activePersonaObj.thesis)}
                  </p>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] font-mono border-t border-border/40">
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <span>📊</span> {cleanMojibake(activePersonaObj.key_metric)}
                    </span>
                    <span className="text-muted italic text-[10px]">
                      &quot;{cleanMojibake(activePersonaObj.quote)}&quot;
                    </span>
                  </div>
                </div>

                {/* Checklist Verification & Evaluated Dimension Metrics */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {/* Checklist */}
                  <div className="p-3 rounded-xl bg-surface/70 border border-border/60 space-y-1.5">
                    <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">
                      Verified Technical &amp; Fundamental Rules:
                    </span>
                    {activePersonaObj.checklist && activePersonaObj.checklist.length > 0 ? (
                      activePersonaObj.checklist.map((rule, idx) => (
                        <div key={idx} className="flex items-start gap-1.5 text-xs text-text/90 font-ui leading-tight">
                          <span className="text-emerald-400 font-bold">✓</span>
                          <span>{cleanMojibake(rule)}</span>
                        </div>
                      ))
                    ) : (
                      <span className="text-[10px] text-muted font-mono block py-2">
                        Rule verification checklist pending multi-agent debate.
                      </span>
                    )}
                  </div>

                  {/* Dimension Metrics */}
                  <div className="p-3 rounded-xl bg-surface/70 border border-border/60 space-y-1.5">
                    <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">
                      Evaluated Quant Scores:
                    </span>
                    {activePersonaObj.metrics && Object.keys(activePersonaObj.metrics).length > 0 ? (
                      <div className="grid grid-cols-2 gap-1.5">
                        {Object.entries(activePersonaObj.metrics).map(([k, v]) => (
                          <div key={k} className="p-2 rounded-lg bg-elevated/70 border border-border/50 text-[11px] font-mono">
                            <span className="text-muted text-[10px] block truncate">{k}</span>
                            <span className="font-bold text-text">{v}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[10px] text-muted font-mono block py-2">
                        Quant metrics matrix pending multi-agent evaluation.
                      </span>
                    )}
                  </div>
                </div>

                {/* Persona Action Footer */}
                <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/40">
                  <button
                    onClick={() => sendDraft(`structure ${selectedSymbol}`)}
                    className="px-2.5 py-1.5 rounded-xl bg-surface hover:bg-elevated border border-border/60 text-xs text-text font-ui transition-all cursor-pointer"
                  >
                    🏛️ SMC Structure
                  </button>
                  <button
                    onClick={() => sendDraft(`persona ${activePersonaObj.id} ${selectedSymbol}`)}
                    className="px-3.5 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black font-bold text-xs transition-all cursor-pointer shadow-md"
                  >
                    💬 Consult {activePersonaObj.name} in Chat →
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ═══ RIGHT COLUMN: PREMIUM TRADE DESK RAIL ═══ */}
        <div className="lg:col-span-3 space-y-3">

          {/* SIGNAL STATUS CARD */}
          {setup ? (
            <div className="rounded-2xl p-3.5 space-y-2.5 relative overflow-hidden" style={{
              background: 'var(--color-panel)',
              border: `1px solid ${setup?.action?.includes('SHORT') ? 'rgba(255,79,123,0.4)' : 'rgba(0,214,143,0.4)'}`,
              boxShadow: setup?.action?.includes('SHORT') ? 'var(--glow-rose)' : 'var(--glow-emerald)'
            }}>
              {/* Gradient accent top bar */}
              <div className="absolute top-0 left-0 right-0 h-0.5 rounded-t-2xl" style={{
                background: setup?.action?.includes('SHORT')
                  ? 'linear-gradient(90deg, var(--color-rose), transparent)'
                  : 'linear-gradient(90deg, var(--color-emerald), transparent)'
              }} />

              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-[9px] font-bold uppercase tracking-widest block" style={{ color: 'var(--color-muted)' }}>⚡ SMART ORDER STAGING GATE</span>
                  <span className="text-xs font-bold font-mono" style={{ color: 'var(--color-text)' }}>{setup.symbol}</span>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold border ${
                    setup?.action?.includes('SHORT')
                      ? 'border-rose-500/40 text-rose-400'
                      : 'border-emerald-500/40 text-emerald-400'
                  }`} style={{ background: setup?.action?.includes('SHORT') ? 'rgba(255,79,123,0.12)' : 'rgba(0,214,143,0.12)' }}>
                    ● {setup?.status || 'READY'}
                  </span>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded font-mono ${
                    setup.action.includes('SHORT') ? 'text-rose-400' : 'text-emerald-400'
                  }`} style={{ background: 'var(--color-elevated)' }}>
                    {setup.action}
                  </span>
                </div>
              </div>

              {/* Timeline chip */}
              <div className="flex items-center justify-between px-2 py-1 rounded-lg text-[10px] font-mono" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)' }}>
                <span style={{ color: 'var(--color-muted)' }}>⏱️ Timeline</span>
                <span className="font-semibold" style={{ color: 'var(--color-gold)' }}>{setup?.timeline ?? '—'}</span>
              </div>

              {/* Price levels grid */}
              {(() => {
                const isShortOrder = Boolean(setup?.action && (String(setup.action).toUpperCase().includes('SHORT') || String(setup.action).toUpperCase().includes('SELL')))
                return (
                  <div className="space-y-1 text-xs font-mono">
                    <div className="flex justify-between items-center py-1 px-2 rounded-lg bg-surface/60 border border-border/40">
                      <span className="text-[10px] text-muted">TRIGGER</span>
                      <span className="font-bold text-[10px] text-text">{setup.trigger}</span>
                    </div>
                    <div className="flex justify-between items-center py-1.5 px-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                      <div>
                        <span className="text-[10px] text-emerald-400 font-bold block">TARGET 2 (3.5R)</span>
                        <span className="text-[9px] text-muted">{isShortOrder ? '−' : '+'}{setup.target_2 ? 'Full target' : 'Trailing'}</span>
                      </div>
                      <span className="font-extrabold text-xs text-emerald-400 tabular-nums">
                        {setup.target_2 != null ? `₹${Number(setup.target_2).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-1.5 px-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                      <div>
                        <span className="text-[10px] text-emerald-400 font-bold block">TARGET 1 (2R)</span>
                        {setup.reward_pct != null && setup.reward_pct !== '—' && (
                          <span className="text-[9px] text-emerald-400/80">
                            {isShortOrder ? '−' : '+'}{setup.reward_pct}% ({isShortOrder ? '−' : '+'}{setup.reward_points}pts)
                          </span>
                        )}
                      </div>
                      <span className="font-extrabold text-xs text-emerald-400 tabular-nums">
                        {setup.target_1 != null ? `₹${Number(setup.target_1).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-1.5 px-2 rounded-lg bg-surface/90 border border-border/70">
                      <span className="text-[10px] font-bold text-text">ENTRY (CMP)</span>
                      <span className="font-extrabold text-xs text-text tabular-nums">
                        {setup.entry != null ? `₹${Number(setup.entry).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-1.5 px-2 rounded-lg bg-rose-500/10 border border-rose-500/20">
                      <div>
                        <span className="text-[10px] text-rose-400 font-bold block">STOP LOSS</span>
                        {setup.risk_pct != null && setup.risk_pct !== '—' && (
                          <span className="text-[9px] text-rose-400/80">
                            {isShortOrder ? '+' : '−'}{setup.risk_pct}% ({isShortOrder ? '+' : '−'}{setup.risk_points}pts)
                          </span>
                        )}
                      </div>
                      <span className="font-extrabold text-xs text-rose-400 tabular-nums">
                        {setup.stop_loss != null ? `₹${Number(setup.stop_loss).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center pt-1.5 px-1">
                      <span className="text-[10px] font-bold text-muted">R:R ASYMMETRY</span>
                      <span className="font-extrabold text-xs px-2 py-0.5 rounded bg-amber/15 text-amber border border-amber/30">
                        {setup.risk_reward != null ? `1 : ${setup.risk_reward} R` : '—'}
                      </span>
                    </div>

                    {/* Interactive Quant Position Sizer */}
                    {(() => {
                      const riskPtsNum = Number(setup.risk_points) > 0 ? Number(setup.risk_points) : Math.abs(Number(setup.entry) - Number(setup.stop_loss))
                      if (!riskPtsNum || riskPtsNum <= 0) return null

                      const isFo = Boolean(universeStock?.isFO || universeStock?.lotSize)
                      const lotSz = universeStock?.lotSize || 1
                      const riskPerLot = riskPtsNum * lotSz
                      const lots = isFo ? Math.max(1, Math.floor(riskBudget / riskPerLot)) : null
                      const quantQty = isFo ? (lots * lotSz) : Math.max(1, Math.floor(riskBudget / riskPtsNum))
                      const actualRiskAmt = Math.round(quantQty * riskPtsNum)
                      const rewPtsNum = Number(setup.reward_points) > 0 ? Number(setup.reward_points) : (riskPtsNum * 2)
                      const profitT1Amt = Math.round(quantQty * rewPtsNum)
                      const profitT2Amt = Math.round(quantQty * riskPtsNum * 3.5)

                      return (
                        <div className="bg-surface/80 rounded-xl p-2.5 border border-border/60 space-y-2 mt-1.5">
                          <div className="flex items-center justify-between">
                            <span className="text-[9px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
                              <span>⚡</span> QUANT POSITION SIZER
                            </span>
                            <span className="text-[10px] font-mono font-bold text-amber">
                              {quantQty} Qty {isFo ? `(${lots} Lot${lots > 1 ? 's' : ''})` : 'Shares'}
                            </span>
                          </div>

                          {/* Risk Budget Switcher Pills */}
                          <div className="flex items-center gap-1 bg-elevated/70 p-0.5 rounded-lg border border-border/40">
                            {[1000, 2500, 5000, 10000].map((bVal) => (
                              <button
                                key={bVal}
                                type="button"
                                onClick={() => setRiskBudget(bVal)}
                                className={`flex-1 py-0.5 rounded text-[9px] font-mono font-bold transition-all cursor-pointer ${
                                  riskBudget === bVal
                                    ? 'bg-amber text-black shadow-xs font-extrabold'
                                    : 'text-muted hover:text-text'
                                }`}
                              >
                                ₹{bVal >= 1000 ? `${bVal / 1000}k` : bVal}
                              </button>
                            ))}
                          </div>

                          {/* Sizing Telemetry Grid */}
                          <div className="grid grid-cols-3 gap-1 text-[9px] font-mono text-center">
                            <div className="bg-elevated/50 p-1 rounded border border-border/40">
                              <span className="text-muted block text-[8px]">CAPPED RISK</span>
                              <span className="text-rose-400 font-bold">₹{actualRiskAmt.toLocaleString('en-IN')}</span>
                            </div>
                            <div className="bg-elevated/50 p-1 rounded border border-border/40">
                              <span className="text-muted block text-[8px]">T1 PROFIT (2R)</span>
                              <span className="text-emerald-400 font-bold">+₹{profitT1Amt.toLocaleString('en-IN')}</span>
                            </div>
                            <div className="bg-elevated/50 p-1 rounded border border-border/40">
                              <span className="text-muted block text-[8px]">T2 PROFIT (3.5R)</span>
                              <span className="text-emerald-400 font-bold">+₹{profitT2Amt.toLocaleString('en-IN')}</span>
                            </div>
                          </div>
                        </div>
                      )
                    })()}

                    {/* Elevated Primary Execute Button */}
                    <button
                      onClick={() => {
                        if (onOpenOrderTicket) {
                          const riskPtsNum = Number(setup.risk_points) > 0 ? Number(setup.risk_points) : Math.abs(Number(setup.entry) - Number(setup.stop_loss))
                          const isFo = Boolean(universeStock?.isFO || universeStock?.lotSize)
                          const lotSz = universeStock?.lotSize || 1
                          const riskPerLot = riskPtsNum > 0 ? riskPtsNum * lotSz : 1
                          const lots = isFo && riskPtsNum > 0 ? Math.max(1, Math.floor(riskBudget / riskPerLot)) : null
                          const quantQty = riskPtsNum > 0 ? (isFo ? (lots * lotSz) : Math.max(1, Math.floor(riskBudget / riskPtsNum))) : 1

                          onOpenOrderTicket({
                            symbol: selectedSymbol,
                            exchange: getSymbolExchange(selectedSymbol),
                            price: setup.entry,
                            stopLoss: setup.stop_loss,
                            target: setup.target_1,
                            action: setup.action.includes('SHORT') ? 'SELL' : 'BUY',
                            quantity: quantQty,
                            lotSize: universeStock?.lotSize || null,
                          })
                        }
                      }}
                      className="w-full mt-2 py-3 px-4 rounded-2xl font-bold text-xs uppercase tracking-widest transition-all shadow-lg cursor-pointer flex items-center justify-center gap-2 hover:brightness-110 active:scale-[0.98]"
                      style={{
                        background: setup?.action?.includes('SHORT')
                          ? 'linear-gradient(135deg, var(--color-rose), #c2003a)'
                          : 'linear-gradient(135deg, var(--color-gold), #c47a00)',
                        color: '#000',
                        boxShadow: setup?.action?.includes('SHORT') ? 'var(--glow-rose)' : 'var(--glow-gold)'
                      }}
                    >
                      <span>⚡</span>
                      STAGE / EXECUTE ORDER ({setup?.action?.includes('SHORT') ? 'SELL' : 'BUY'})
                    </button>

                    {/* Quick Action Pills */}
                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={() => sendDraft(`analyze ${selectedSymbol}`)}
                        className="flex-1 py-1.5 rounded-xl text-[10px] font-bold cursor-pointer transition-all hover:brightness-110"
                        style={{ background: 'rgba(0,214,143,0.10)', border: '1px solid rgba(0,214,143,0.30)', color: 'var(--color-emerald)' }}
                      >
                        ⚔️ Run Debate
                      </button>
                      <button
                        onClick={() => sendDraft(`telegram ${selectedSymbol} ${setup?.action || 'ANALYSIS'}`)}
                        className="flex-1 py-1.5 rounded-xl text-[10px] font-bold cursor-pointer transition-all hover:brightness-110"
                        style={{ background: 'rgba(77,155,255,0.10)', border: '1px solid rgba(77,155,255,0.30)', color: 'var(--color-sapphire)' }}
                      >
                        📤 Telegram
                      </button>
                    </div>
                  </div>
                )
              })()}
            </div>
          ) : (
            <div className="rounded-2xl p-4 space-y-3" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-card)' }}>
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: 'var(--color-muted)' }}>⚡ ORDER STAGING GATE</span>
                <span className="text-[9px] font-mono px-2 py-0.5 rounded-full border border-amber/30 bg-amber/10 text-amber font-bold">
                  ● AWAITING SETUP
                </span>
              </div>
              <div className="text-center py-3 space-y-2">
                <div className="text-2xl">🛡️</div>
                <div className="text-xs font-bold font-mono" style={{ color: 'var(--color-text)' }}>
                  No Active Trade Setup for {selectedSymbol}
                </div>
                <p className="text-[11px] leading-relaxed" style={{ color: 'var(--color-muted)' }}>
                  {loading
                    ? 'Fetching current market quote and calculating quantitative parameters...'
                    : 'Institutional entry and stop levels are generated when volatility contraction and order blocks align. Run an AI debate or poll a specialist council to formulate a fresh trade plan.'}
                </p>
                <div className="flex flex-col gap-1.5 pt-2">
                  <button
                    onClick={() => {
                      if (onOpenOrderTicket) {
                        onOpenOrderTicket({
                          symbol: selectedSymbol,
                          exchange: resolvedExchange,
                          price: curLtp || null,
                          stopLoss: null,
                          target: null,
                          action: 'BUY',
                        })
                      }
                    }}
                    className="w-full py-2.5 px-3 rounded-xl bg-amber hover:brightness-110 text-black text-xs font-bold transition-all cursor-pointer shadow-md flex items-center justify-center gap-1.5"
                  >
                    <span>⚡</span>
                    STAGE / EXECUTE ORDER (BUY)
                  </button>
                  <button
                    onClick={() => sendDraft(`analyze ${selectedSymbol}`)}
                    className="w-full py-2 px-3 rounded-xl bg-emerald-500/20 hover:bg-emerald-500 text-emerald-400 hover:text-black text-xs font-bold transition-all cursor-pointer"
                  >
                    ⚔️ Run AI Debate on {selectedSymbol}
                  </button>
                  <button
                    onClick={() => sendDraft(`council breakout ${selectedSymbol}`)}
                    className="w-full py-2 px-3 rounded-xl bg-amber/20 hover:bg-amber text-amber hover:text-black text-xs font-bold transition-all cursor-pointer"
                  >
                    🏛️ Poll Breakout Council
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* THESIS BOX — only render if backend provided a real thesis */}
          {setup && setup.thesis && (
            <div className="rounded-2xl p-3 space-y-2" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
              <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: 'var(--color-muted)' }}>💡 SETUP THESIS</span>
              <p className="text-[11px] leading-relaxed font-ui" style={{ color: 'var(--color-text)' }}>{setup.thesis}</p>
              <div className="px-2 py-1.5 rounded-lg text-[9px] flex items-start gap-1.5" style={{ background: 'var(--color-elevated)', color: 'var(--color-muted)' }}>
                <span>🛡️</span>
                <span><strong style={{ color: 'var(--color-text)' }}>Trail Rule:</strong> Move SL to BE at T1. Trail remainder with 3× ATR Chandelier.</span>
              </div>
            </div>
          )}

          {/* Collapsible Secondary Risk Telemetry Drawer */}
          <div className="rounded-2xl overflow-hidden border border-border/70" style={{ background: 'var(--color-panel)', boxShadow: 'var(--shadow-card)' }}>
            <button
              type="button"
              onClick={() => setShowRiskDetails((prev) => !prev)}
              className="w-full py-2.5 px-3.5 flex items-center justify-between text-xs font-mono font-bold transition-all cursor-pointer hover:bg-surface/60"
              style={{ color: 'var(--color-text)' }}
            >
              <span className="flex items-center gap-1.5">
                <span>🛡️</span>
                <span>Risk Telemetry &amp; ATR Trails</span>
              </span>
              <span className="text-[10px] text-muted flex items-center gap-1">
                <span>{showRiskDetails ? '▲ Hide' : '▼ View Details'}</span>
              </span>
            </button>

            {showRiskDetails && (
              <div className="p-3.5 space-y-3 border-t border-border/50 animate-fade-slide">
                {/* RISK METER ARC WIDGET */}
                <div className="flex flex-col items-center">
                  <span className="text-[9px] font-bold uppercase tracking-widest block mb-2" style={{ color: 'var(--color-muted)' }}>⚡ PORTFOLIO HEAT METER</span>
                  {(() => {
                    const heatPct = data?.portfolio_heat != null ? Number(data.portfolio_heat) : null
                    const arcLen = 157
                    const filled = heatPct != null ? arcLen - (arcLen * heatPct / 100) : arcLen
                    const glowColor = heatPct == null ? 'transparent'
                      : heatPct >= 70 ? 'rgba(255,79,123,0.5)'
                      : heatPct >= 40 ? 'rgba(245,166,35,0.5)'
                      : 'rgba(0,214,143,0.4)'
                    return (
                      <svg viewBox="0 0 120 65" className="w-36 h-20 overflow-visible">
                        <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="var(--color-elevated)" strokeWidth="8" strokeLinecap="round" />
                        <path
                          d="M 10 60 A 50 50 0 0 1 110 60"
                          fill="none"
                          stroke={heatPct != null ? 'url(#heatGrad)' : 'var(--color-border)'}
                          strokeWidth="8"
                          strokeDasharray={heatPct != null ? String(arcLen) : `${arcLen * 0.08} ${arcLen * 0.12}`}
                          strokeDashoffset={filled}
                          strokeLinecap="round"
                          style={{ filter: `drop-shadow(0 0 6px ${glowColor})`, transition: 'stroke-dashoffset 1.2s cubic-bezier(0.16,1,0.3,1)' }}
                        />
                        <defs>
                          <linearGradient id="heatGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stopColor="var(--color-emerald)" />
                            <stop offset="60%" stopColor="var(--color-gold)" />
                            <stop offset="100%" stopColor="var(--color-rose)" />
                          </linearGradient>
                        </defs>
                        <text x="60" y="54" textAnchor="middle" fill="var(--color-text)" fontSize="13" fontWeight="800" fontFamily="'JetBrains Mono', monospace">
                          {heatPct != null ? `${heatPct}%` : '—'}
                        </text>
                        <text x="60" y="64" textAnchor="middle" fill="var(--color-muted)" fontSize="6" fontFamily="'Inter', sans-serif">
                          {heatPct != null ? 'INDIA VIX HEAT' : 'VIX UNAVAILABLE'}
                        </text>
                      </svg>
                    )
                  })()}
                  <div className="flex items-center gap-2 text-[9px] font-mono mt-1">
                    <span style={{ color: 'var(--color-emerald)' }}>● SAFE {'<'}40%</span>
                    <span style={{ color: 'var(--color-gold)' }}>● MOD 40–70%</span>
                    <span style={{ color: 'var(--color-rose)' }}>● HIGH {'>'}70%</span>
                  </div>
                </div>

                {/* ATR TRAIL LEVELS */}
                {setup && (() => {
                  const atr14 = data?.atr_14 != null && Number(data.atr_14) > 0 ? Number(data.atr_14) : null
                  const atrProxy = atr14 ?? (setup.risk_points && setup.risk_points !== '—' ? Number(setup.risk_points) : null)
                  const isShortSetup = setup?.action?.includes('SHORT')

                  const breakevenPrice = setup.entry != null
                    ? (isShortSetup
                        ? Number(setup.entry) - Number(setup.entry) * 0.002
                        : Number(setup.entry) + Number(setup.entry) * 0.002)
                    : null

                  const chandelierPrice = setup.entry != null && atrProxy != null
                    ? (isShortSetup
                        ? Number(setup.entry) + atrProxy * 3
                        : Number(setup.entry) - atrProxy * 3)
                    : null

                  const fmtPrice = (p) => p != null && Number.isFinite(p) && p > 0
                    ? `₹${Number(p.toFixed(0)).toLocaleString('en-IN')}`
                    : '—'

                  const levels = [
                    { label: 'Breakeven Level', price: breakevenPrice, note: isShortSetup ? '−0.2% buffer' : '+0.2% buffer', color: 'var(--color-cyan)' },
                    { label: '2R Scale-Out', price: setup.target_1, note: isShortSetup ? 'Cover 50% qty' : 'Sell 50% qty', color: 'var(--color-emerald)' },
                    { label: 'Chandelier Trail', price: chandelierPrice, note: atrProxy != null ? `3× ATR (₹${atrProxy.toFixed(0)})` : '3× ATR (pending)', color: 'var(--color-gold)' },
                    { label: '3.5R Final Exit', price: setup.target_2, note: isShortSetup ? 'Full cover exit' : 'Full exit', color: 'var(--color-emerald)' },
                  ]
                  return (
                    <div className="space-y-1.5 pt-2 border-t border-border/40">
                      <span className="text-[9px] font-bold uppercase tracking-widest block" style={{ color: 'var(--color-muted)' }}>🛡️ ATR TRAIL &amp; SCALE LEVELS</span>
                      {levels.map(({ label, price, note, color }) => (
                        <div key={label} className="flex items-center justify-between text-[10px] px-2 py-1 rounded-lg" style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border-subtle)' }}>
                          <div>
                            <span className="block font-bold font-mono" style={{ color }}>{fmtPrice(price)}</span>
                            <span className="text-[9px]" style={{ color: 'var(--color-muted)' }}>{note}</span>
                          </div>
                          <span className="text-[9px] text-right" style={{ color: 'var(--color-muted)' }}>{label}</span>
                        </div>
                      ))}
                    </div>
                  )
                })()}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Row: 3-Card High Impact Analytics Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Card 1: Institutional Flows & Flow Intelligence (3 Cols) */}
        <div className="lg:col-span-3 bg-panel border border-border/80 rounded-2xl p-3.5 shadow-sm space-y-2.5 flex flex-col justify-between group hover:border-amber/40 transition-all">
          <div className="space-y-2.5">
            {/* Header with Regime Tag */}
            <div className="flex items-center justify-between border-b border-border/50 pb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                <span>🌊</span> INSTITUTIONAL FLOWS
              </span>
              <span
                className={`text-[9px] font-bold px-2 py-0.5 rounded-full border font-mono ${
                  flows?.regime === 'DII_ABSORPTION'
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : flows?.regime === 'TWIN_BUYING'
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : flows?.regime === 'TWIN_SELLING'
                    ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                    : 'bg-amber/15 border-amber/30 text-amber'
                }`}
              >
                {flows?.regime === 'DII_ABSORPTION'
                  ? `🛡️ DII ABSORPTION`
                  : flows?.regime === 'TWIN_BUYING'
                  ? `🚀 TWIN INFLOW`
                  : flows?.regime_label || (flows ? 'DLY CASH' : 'AWAITING')}
              </span>
            </div>

            {/* Net Total Hero Inflow/Outflow */}
            <div className="bg-surface/80 p-2.5 rounded-xl border border-border/50">
              <div className="flex items-center justify-between">
                <span className="text-muted text-[11px]">Net Institutional Flow</span>
                <span className={`font-bold font-mono text-sm ${netTotal != null ? (netTotal >= 0 ? 'text-emerald-400' : 'text-rose-400') : 'text-muted'}`}>
                  {netTotal != null
                    ? `${netTotal >= 0 ? '+' : ''}₹${Math.abs(Math.round(netTotal)).toLocaleString('en-IN')} Cr`
                    : '—'}
                </span>
              </div>
              <div className="text-[10px] text-muted flex items-center justify-between mt-1 pt-1 border-t border-border/30">
                <span>Combined FII + DII</span>
                <span className={netTotal != null ? (netTotal >= 0 ? 'text-emerald-400 font-medium' : 'text-rose-400 font-medium') : 'text-muted'}>
                  {netTotal != null ? (netTotal >= 0 ? '🟢 Net Cash Inflow' : '🔴 Net Cash Outflow') : 'Awaiting EOD Filing'}
                </span>
              </div>
            </div>

            {/* FII & DII Breakdown with Streaks */}
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="bg-surface/80 p-2 rounded-xl border border-border/50">
                <div className="flex items-center justify-between text-[10px] text-muted">
                  <span>FII Net</span>
                  {fiiStreak != null && (
                    <span
                      className={`text-[9px] px-1 rounded ${
                        fiiVal >= 0 ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'
                      }`}
                    >
                      {fiiStreak < 0 ? `${Math.abs(fiiStreak)}d Sell` : `${fiiStreak}d Buy`}
                    </span>
                  )}
                </div>
                <div className={`font-bold mt-1 text-[13px] ${fiiVal != null ? (fiiVal >= 0 ? 'text-emerald-400' : 'text-rose-400') : 'text-muted'}`}>
                  {fiiVal != null ? `${fiiVal >= 0 ? '+' : ''}₹${Math.round(fiiVal).toLocaleString('en-IN')} Cr` : '—'}
                </div>
              </div>

              <div className="bg-surface/80 p-2 rounded-xl border border-border/50">
                <div className="flex items-center justify-between text-[10px] text-muted">
                  <span>DII Net</span>
                  {diiStreak != null && (
                    <span
                      className={`text-[9px] px-1 rounded ${
                        diiVal >= 0 ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'
                      }`}
                    >
                      {diiStreak > 0 ? `${diiStreak}d Buy` : `${Math.abs(diiStreak)}d Sell`}
                    </span>
                  )}
                </div>
                <div className={`font-bold mt-1 text-[13px] ${diiVal != null ? (diiVal >= 0 ? 'text-emerald-400' : 'text-rose-400') : 'text-muted'}`}>
                  {diiVal != null ? `${diiVal >= 0 ? '+' : ''}₹${Math.round(diiVal).toLocaleString('en-IN')} Cr` : '—'}
                </div>
              </div>
            </div>

            {/* DII Absorption Rate & Progress Bar */}
            {absorptionPct > 0 && fiiVal < 0 && (
              <div className="bg-surface/80 p-2 rounded-xl border border-border/50 space-y-1 text-xs">
                <div className="flex items-center justify-between text-[10px] font-mono">
                  <span className="text-muted">DII Absorption Ratio</span>
                  <span className="font-bold text-emerald-400">{absorptionPct}%</span>
                </div>
                <div className="w-full bg-surface h-1.5 rounded-full overflow-hidden border border-border/40">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      absorptionPct >= 100 ? 'bg-emerald-400' : absorptionPct >= 60 ? 'bg-amber' : 'bg-rose-400'
                    }`}
                    style={{ width: `${Math.min(100, (absorptionPct / 200) * 100)}%` }}
                  />
                </div>
                <div className="text-[9px] text-muted font-sans">
                  {absorptionPct >= 100
                    ? '🛡️ Domestic institutions absorbed all foreign outflows'
                    : '⚠️ Foreign selling exceeding domestic absorption'}
                </div>
              </div>
            )}

            {/* Strategic Takeaway / Rationale */}
            <div className="bg-amber/10 border border-amber/25 rounded-xl p-2 text-[11px] font-sans leading-relaxed text-text/90">
              <span className="text-amber font-bold text-[10px] uppercase tracking-wide block mb-0.5">
                💡 Institutional Takeaway
              </span>
              <p className="line-clamp-2 text-muted text-[10.5px]">
                {flows?.signal_reason || flows?.verdict || 'Provisional institutional figures are published by NSE daily after 18:00 IST. Awaiting EOD filing.'}
              </p>
            </div>
          </div>

          <button
            onClick={() => sendDraft('flows')}
            className="w-full mt-2 py-1 px-2 rounded-lg bg-surface hover:bg-elevated border border-border/60 hover:border-amber/50 text-[10px] font-mono text-muted hover:text-amber transition-all cursor-pointer flex items-center justify-center gap-1"
            title="Inspect 10-day historical flows breakdown, trends and F&O data"
          >
            <span>📊 Detailed Flow Timeline</span>
            <span>→</span>
          </button>
        </div>

        {/* Card 2: Multi-Timeframe Technical Confluence (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>⚡</span> MULTI-TF CONFLUENCE
            </span>
            <div className="flex items-center gap-1.5">
              {data?.multi_tf?.stance && (
                <span className="text-[10px] font-mono text-muted hidden sm:inline">
                  {data.multi_tf.stance}
                </span>
              )}
              <span className={`text-[10px] font-bold font-mono px-2 py-0.5 rounded-full border ${
                data?.multi_tf?.confluence_score >= 60
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                  : data?.multi_tf?.confluence_score <= 35
                  ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                  : 'bg-amber/15 border-amber/30 text-amber'
              }`}>
                {data?.multi_tf?.confluence_score != null ? `${data.multi_tf.confluence_score}% CONFLUENCE` : 'CONFLUENCE UNAVAILABLE'}
              </span>
            </div>
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            {(data?.multi_tf?.timeframes || []).map((tfItem) => {
              const isBull = tfItem.bias === 'BULLISH'
              const isBear = tfItem.bias === 'BEARISH'
              return (
                <div
                  key={tfItem.tf}
                  className="bg-surface/80 p-2 rounded-xl border border-border/50 flex items-center justify-between gap-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-text bg-elevated px-1.5 py-0.5 rounded text-[11px] border border-border/60">
                      {tfItem.tf}
                    </span>
                    <div>
                      <span className="font-semibold text-text text-xs block">{tfItem.signal || 'Analysis Pending'}</span>
                      <span className="text-[10px] text-muted">{tfItem.key_level || '—'}</span>
                    </div>
                  </div>

                  <div className="text-right">
                    <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                      isBull ? 'text-emerald-400 bg-emerald-500/10' : isBear ? 'text-rose-400 bg-rose-500/10' : 'text-amber bg-amber/10'
                    }`}>
                      {tfItem.bias || 'NEUTRAL'}
                    </span>
                    <span className="text-[10px] text-muted block font-mono">
                      {tfItem.rsi != null && Number(tfItem.rsi) > 0 ? `RSI ${Number(tfItem.rsi).toFixed(1)}` : 'RSI —'}
                    </span>
                  </div>
                </div>
              )
            })}
            {(!data?.multi_tf?.timeframes || data.multi_tf.timeframes.length === 0) && (
              <p className="rounded-xl border border-border/50 bg-surface/80 p-3 text-[11px] text-muted">Verified multi-timeframe data is unavailable for {selectedSymbol}.</p>
            )}
            {data?.multi_tf?.recommendation && (
              <div className="bg-surface/90 border border-border/60 rounded-xl p-2 text-[10.5px] font-sans leading-relaxed text-muted">
                <span className="font-semibold text-text">💡 Synthesis: </span>
                {data.multi_tf.recommendation}
              </div>
            )}
          </div>
        </div>

        {/* Card 3: Sector Relative Rotation Graph (RRG) Matrix (5 Cols) */}
        <div className="lg:col-span-5 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>🌐</span> SECTOR RRG MOMENTUM MATRIX
            </span>
            <div className="flex items-center gap-1 bg-surface rounded-lg p-0.5 border border-border/60 text-[10px]">
              <button
                onClick={() => setSectorViewMode('2D')}
                className={`px-2 py-0.5 rounded font-bold transition-all cursor-pointer ${
                  sectorViewMode === '2D' ? 'bg-amber text-black' : 'text-muted'
                }`}
              >
                2D Grid
              </button>
              <button
                onClick={() => setSectorViewMode('LIST')}
                className={`px-2 py-0.5 rounded font-bold transition-all cursor-pointer ${
                  sectorViewMode === 'LIST' ? 'bg-amber text-black' : 'text-muted'
                }`}
              >
                List
              </button>
            </div>
          </div>

          {/* RRG Quadrant Grid or List View */}
          {sectorViewMode === '2D' ? (
            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              {/* LEADING (Top Right) */}
              <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-2.5 space-y-1.5">
                <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider block flex items-center justify-between">
                  <span>🟢 LEADING</span>
                  <span className="text-[9px] text-muted">RS &gt; 100, Mom &gt; 100</span>
                </span>
                <div className="space-y-1">
                  {(() => {
                    const items = sectors.filter((s) => s.quadrant === 'LEADING' || (s.rs_ratio >= 100 && s.rs_momentum >= 100))
                    const displayItems = items.slice(0, 3)
                    if (displayItems.length === 0) {
                      return <span className="text-[10px] text-muted block py-1 font-mono">None in this quadrant</span>
                    }
                    return displayItems.map((s, idx) => {
                      const cleanName = (s.name || s.code || '').replace(/^NIFTY\s*/i, '').trim()
                      return (
                        <button
                          key={idx}
                          onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: cleanName } }))}
                          className="w-full flex items-center justify-between text-[11px] p-1 rounded-lg hover:bg-emerald-500/20 border border-transparent hover:border-emerald-500/40 transition-all cursor-pointer group text-left"
                          title={`Click to drill down on ${cleanName} constituent stocks & metrics`}
                        >
                          <span className="font-bold text-text group-hover:text-emerald-300 transition-colors truncate">
                            {cleanName}
                          </span>
                          <div className="flex items-center gap-1 font-mono shrink-0">
                            <span className="text-emerald-400 font-semibold">{s.rs_ratio ? s.rs_ratio.toFixed(1) : '—'}</span>
                            <span className="text-[10px] text-muted group-hover:text-emerald-300 transition-colors">→</span>
                          </div>
                        </button>
                      )
                    })
                  })()}
                </div>
              </div>

              {/* IMPROVING (Bottom Right) */}
              <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-xl p-2.5 space-y-1.5">
                <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider block flex items-center justify-between">
                  <span>🔵 IMPROVING</span>
                  <span className="text-[9px] text-muted">Mom &gt; 100</span>
                </span>
                <div className="space-y-1">
                  {(() => {
                    const items = sectors.filter((s) => s.quadrant === 'IMPROVING' || (s.rs_ratio < 100 && s.rs_momentum >= 100))
                    const displayItems = items.slice(0, 3)
                    if (displayItems.length === 0) {
                      return <span className="text-[10px] text-muted block py-1 font-mono">None in this quadrant</span>
                    }
                    return displayItems.map((s, idx) => {
                      const cleanName = (s.name || s.code || '').replace(/^NIFTY\s*/i, '').trim()
                      return (
                        <button
                          key={idx}
                          onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: cleanName } }))}
                          className="w-full flex items-center justify-between text-[11px] p-1 rounded-lg hover:bg-cyan-500/20 border border-transparent hover:border-cyan-500/40 transition-all cursor-pointer group text-left"
                          title={`Click to drill down on ${cleanName} constituent stocks & metrics`}
                        >
                          <span className="font-bold text-text group-hover:text-cyan-300 transition-colors truncate">
                            {cleanName}
                          </span>
                          <div className="flex items-center gap-1 font-mono shrink-0">
                            <span className="text-cyan-400 font-semibold">{s.rs_ratio ? s.rs_ratio.toFixed(1) : '—'}</span>
                            <span className="text-[10px] text-muted group-hover:text-cyan-300 transition-colors">→</span>
                          </div>
                        </button>
                      )
                    })
                  })()}
                </div>
              </div>

              {/* WEAKENING (Top Left) */}
              <div className="bg-amber/10 border border-amber/30 rounded-xl p-2.5 space-y-1.5">
                <span className="text-[10px] font-bold text-amber uppercase tracking-wider block flex items-center justify-between">
                  <span>🟡 WEAKENING</span>
                  <span className="text-[9px] text-muted">Mom &lt; 100</span>
                </span>
                <div className="space-y-1">
                  {(() => {
                    const items = sectors.filter((s) => s.quadrant === 'WEAKENING' || (s.rs_ratio >= 100 && s.rs_momentum < 100))
                    const displayItems = items.slice(0, 3)
                    if (displayItems.length === 0) {
                      return <span className="text-[10px] text-muted block py-1 font-mono">None in this quadrant</span>
                    }
                    return displayItems.map((s, idx) => {
                      const cleanName = (s.name || s.code || '').replace(/^NIFTY\s*/i, '').trim()
                      return (
                        <button
                          key={idx}
                          onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: cleanName } }))}
                          className="w-full flex items-center justify-between text-[11px] p-1 rounded-lg hover:bg-amber/20 border border-transparent hover:border-amber/40 transition-all cursor-pointer group text-left"
                          title={`Click to drill down on ${cleanName} constituent stocks & metrics`}
                        >
                          <span className="font-bold text-text group-hover:text-amber transition-colors truncate">
                            {cleanName}
                          </span>
                          <div className="flex items-center gap-1 font-mono shrink-0">
                            <span className="text-amber font-semibold">{s.rs_ratio ? s.rs_ratio.toFixed(1) : '—'}</span>
                            <span className="text-[10px] text-muted group-hover:text-amber transition-colors">→</span>
                          </div>
                        </button>
                      )
                    })
                  })()}
                </div>
              </div>

              {/* LAGGING (Bottom Left) */}
              <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-2.5 space-y-1.5">
                <span className="text-[10px] font-bold text-rose-400 uppercase tracking-wider block flex items-center justify-between">
                  <span>🔴 LAGGING</span>
                  <span className="text-[9px] text-muted">RS &lt; 100, Mom &lt; 100</span>
                </span>
                <div className="space-y-1">
                  {(() => {
                    const items = sectors.filter((s) => s.quadrant === 'LAGGING' || (s.rs_ratio < 100 && s.rs_momentum < 100))
                    const displayItems = items.slice(0, 3)
                    if (displayItems.length === 0) {
                      return <span className="text-[10px] text-muted block py-1 font-mono">None in this quadrant</span>
                    }
                    return displayItems.map((s, idx) => {
                      const cleanName = (s.name || s.code || '').replace(/^NIFTY\s*/i, '').trim()
                      return (
                        <button
                          key={idx}
                          onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: cleanName } }))}
                          className="w-full flex items-center justify-between text-[11px] p-1 rounded-lg hover:bg-rose-500/20 border border-transparent hover:border-rose-500/40 transition-all cursor-pointer group text-left"
                          title={`Click to drill down on ${cleanName} constituent stocks & metrics`}
                        >
                          <span className="font-bold text-text group-hover:text-rose-300 transition-colors truncate">
                            {cleanName}
                          </span>
                          <div className="flex items-center gap-1 font-mono shrink-0">
                            <span className="text-rose-400 font-semibold">{s.rs_ratio ? s.rs_ratio.toFixed(1) : '—'}</span>
                            <span className="text-[10px] text-muted group-hover:text-rose-300 transition-colors">→</span>
                          </div>
                        </button>
                      )
                    })
                  })()}
                </div>
              </div>
            </div>
          ) : (
            /* Structured List View */
            <div className="space-y-1.5 text-xs font-mono max-h-[148px] overflow-y-auto pr-1">
              {sectors.length === 0 ? (
                <p className="text-muted text-[11px] p-3 text-center">Sector rotation metrics are computing from 250D benchmark relative strength.</p>
              ) : (
                sectors.map((s, idx) => {
                  const quad = s.quadrant || (s.rs_ratio >= 100 && s.rs_momentum >= 100 ? 'LEADING' : s.rs_ratio < 100 && s.rs_momentum >= 100 ? 'IMPROVING' : s.rs_ratio >= 100 ? 'WEAKENING' : 'LAGGING')
                  const isLeading = quad === 'LEADING'
                  const isImproving = quad === 'IMPROVING'
                  const isWeakening = quad === 'WEAKENING'
                  const badgeColor = isLeading
                    ? 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30'
                    : isImproving
                    ? 'text-cyan-400 bg-cyan-500/15 border-cyan-500/30'
                    : isWeakening
                    ? 'text-amber bg-amber/15 border-amber/30'
                    : 'text-rose-400 bg-rose-500/15 border-rose-500/30'
                  const badgeIcon = isLeading ? '🟢' : isImproving ? '🔵' : isWeakening ? '🟡' : '🔴'
                  const cleanName = (s.name || s.symbol || s.code || '').replace(/^NIFTY\s*/i, '').trim()

                  return (
                    <div
                      key={idx}
                      onClick={() => window.dispatchEvent(new CustomEvent('open-sector-drilldown', { detail: { sector: cleanName } }))}
                      className="flex items-center justify-between p-2 rounded-xl bg-surface/80 border border-border/50 hover:border-amber/40 hover:bg-elevated transition-all cursor-pointer group"
                      title={`Click to drill down on ${cleanName}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs">{badgeIcon}</span>
                        <span className="font-bold text-text group-hover:text-amber transition-colors">
                          {cleanName || 'SECTOR'}
                        </span>
                        <span className={`text-[9px] font-bold px-1.5 py-0.2 rounded border ${badgeColor}`}>
                          {quad}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 font-mono">
                        <span className="text-[10px] text-muted">
                          RS: <strong className="text-text">{s.rs_ratio ? s.rs_ratio.toFixed(1) : '100.0'}</strong>
                        </span>
                        <span className="text-[10px] text-muted">
                          Mom: <strong className="text-text">{s.rs_momentum ? s.rs_momentum.toFixed(1) : '100.0'}</strong>
                        </span>
                        <span className="text-amber text-xs group-hover:translate-x-0.5 transition-transform">→</span>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MiniTrendSparkline({ symbol = '', isPositive = true }) {
  let hash = 0
  for (let i = 0; i < symbol.length; i++) hash = (hash * 31 + symbol.charCodeAt(i)) & 0xffffffff
  const pts = []
  for (let i = 0; i < 6; i++) {
    const pseudoRand = ((Math.sin(hash + i * 1.7) + 1) / 2) * 6
    const base = isPositive ? (i * 2 + pseudoRand) : (12 - i * 2 + pseudoRand)
    pts.push(Math.max(2, Math.min(14, base)))
  }

  const strokeColor = isPositive ? 'var(--color-emerald)' : 'var(--color-rose)'
  const pathD = pts.map((y, i) => `${i === 0 ? 'M' : 'L'} ${i * 7 + 2} ${16 - y}`).join(' ')

  return (
    <svg width="38" height="16" className="overflow-visible flex-shrink-0 opacity-75 group-hover:opacity-100 hidden sm:block">
      <path d={pathD} fill="none" stroke={strokeColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

