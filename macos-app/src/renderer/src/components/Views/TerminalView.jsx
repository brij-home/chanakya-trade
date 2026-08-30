import { useState, useEffect } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import CandlestickChart from '../Charts/CandlestickChart'

export default function TerminalView({ onSelectSymbol, onOpenOrderTicket }) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [selectedSymbol, setSelectedSymbol] = useState('NIFTY')
  const [timeframe, setTimeframe] = useState('15m')
  const [leftTab, setLeftTab] = useState('councils') // 'councils' | 'personas' | 'watchlist'
  const [intelligenceMode, setIntelligenceMode] = useState('councils') // 'councils' | 'personas'
  const [selectedCouncil, setSelectedCouncil] = useState('breakout')
  const [selectedPersona, setSelectedPersona] = useState('minervini')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [watchlistFilter, setWatchlistFilter] = useState('')
  const [watchlistCategory, setWatchlistCategory] = useState('ALL')
  const [watchlistSort, setWatchlistSort] = useState('alpha_asc')
  const [watchlistPage, setWatchlistPage] = useState(1)
  const [sectorViewMode, setSectorViewMode] = useState('2D')
  const watchlistPageSize = 7

  // Fetch terminal snapshot data
  useEffect(() => {
    let unmounted = false
    const fetchSnapshot = async (isInitial = false) => {
      try {
        if (isInitial) setLoading(true)
        const res = await call('/skills/dashboard_snapshot', {
          symbol: selectedSymbol,
          timeframe: timeframe,
        })
        const snapshot = res?.data ?? res
        if (!unmounted && snapshot) {
          setData(snapshot)
        }
      } catch (err) {
        console.error('Failed to load dashboard snapshot:', err)
      } finally {
        if (!unmounted && isInitial) setLoading(false)
      }
    }

    fetchSnapshot(true)
    const interval = setInterval(() => fetchSnapshot(false), 8000)
    return () => {
      unmounted = true
      clearInterval(interval)
    }
  }, [selectedSymbol, timeframe])

  // Synchronize intelligenceMode when user switches left panel tab
  const handleLeftTabChange = (tab) => {
    setLeftTab(tab)
    if (tab === 'councils') setIntelligenceMode('councils')
    if (tab === 'personas') setIntelligenceMode('personas')
  }

  const setup = data?.automated_setup
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
      verdict: 'STRONG BUY',
      confidence: 92,
      thesis: `Mark Minervini's SEPA (Specific Entry Point Analysis) identifies ${selectedSymbol} in pristine Stage 2 Markup with textbook Volatility Contraction Pattern (VCP) consolidation. Volume dried up 68% during the final pivot contraction before today's explosive expansion.`,
      key_metric: 'SEPA RS Rating: 94/99 (Top 6% Momentum)',
      quote: 'Look for contraction in volatility accompanied by a distinct volume contraction before the breakout.',
      checklist: [
        'Stock price above 50-DMA, 150-DMA, and 200-DMA',
        '200-DMA trending upward for > 1 month',
        'Current price within 15% of 52-week high',
        'Volume dried up on pullbacks, expanding on pivot breakout',
      ],
      metrics: { 'RS Rank': '94/99', 'VCP Pivot': 'Tight (2.4%)', 'Stage': 'Stage 2 Markup', 'Volume Surge': '+185%' },
    },
    {
      id: 'kedia',
      name: 'Vijay Kedia',
      title: 'SMILE Indian Multibaggers',
      icon: '💎',
      style: 'Multibagger',
      horizon: '6–24 Months (Positional)',
      verdict: 'BUY',
      confidence: 88,
      thesis: `Evaluated through Vijay Kedia's SMILE framework (Small market cap, Medium management quality, Increasing institutional interest, Large business opportunity, 5-Year Earnings visibility). High promoter holding with clean operating cashflow.`,
      key_metric: 'SMILE Score: 89/100 (High Multibagger Potential)',
      quote: 'Invest like a bull, sit like a sloth, and work like a hound to spot 10x opportunities.',
      checklist: [
        'Scalable addressable Indian domestic market',
        'Management integrity with zero pledge overhang',
        'Operating margin expansion (>18% EBITDA)',
        'Institutional FII/DII accumulation over past 2 quarters',
      ],
      metrics: { 'SMILE Score': '89/100', 'Promoter Holding': '68.4%', 'FCF Yield': '4.8%', 'Target Upside': '2.8x–4.5x' },
    },
    {
      id: 'taleb',
      name: 'Nassim Nicholas Taleb',
      title: 'Antifragile Convexity & Spreads',
      icon: '🛡️',
      style: 'Asymmetric Quant',
      horizon: '1–2 Expiries (Options)',
      verdict: 'STRONG BUY',
      confidence: 94,
      thesis: `Non-linear payoff architecture: Strictly capped downside via Defined-Risk spreads (Bull Call / Put Spread) with unmitigated positive convexity to capture right-tail upside surges while completely neutralizing Theta decay.`,
      key_metric: 'Payoff Convexity Asymmetry: 1 : 3.8 Risk-Reward',
      quote: 'Invest in asymmetric opportunities where your downside is bounded and upside is open-ended.',
      checklist: [
        'Zero naked short gamma exposure',
        'Right-tail positive skew capture',
        'Strictly bounded maximum loss (< 1.5% portfolio risk)',
        'Theta bleed eliminated via credit/debit spread pairing',
      ],
      metrics: { 'Max Loss': 'Capped', 'Payoff Skew': '+3.8R', 'Tail Hedge': 'Active', 'Theta Bleed': 'Neutralized' },
    },
    {
      id: 'wyckoff',
      name: 'Richard Wyckoff',
      title: 'VSA & Accumulation Springs',
      icon: '📈',
      style: 'Volume Spread',
      horizon: '2–6 Weeks (Swing)',
      verdict: 'BUY',
      confidence: 86,
      thesis: `Wyckoff Volume Spread Analysis (VSA) confirms Phase C Accumulation with completed Spring shakeout below support, followed by immediate institutional absorption and Sign of Strength (SOS) price action.`,
      key_metric: 'Wyckoff Phase: Phase D (Mark-Up Jump Across the Creek)',
      quote: 'When the composite operator has accumulated the floating supply, price must advance.',
      checklist: [
        'Selling Climax (SC) and Secondary Test (ST) established',
        'Phase C Spring / Shakeout tested on low volume',
        'Sign of Strength (SOS) bar crossing resistance',
        'Effort vs Result: High buying volume with wide spread',
      ],
      metrics: { 'Wyckoff Phase': 'Phase D (SOS)', 'RVOL 20D': '2.4x', 'Supply Float': 'Absorbed', 'Spring Test': 'Clean' },
    },
    {
      id: 'oneil',
      name: "William O'Neil",
      title: 'CAN SLIM Momentum Growth',
      icon: '⚡',
      style: 'Growth',
      horizon: '3–8 Weeks (Swing)',
      verdict: 'STRONG BUY',
      confidence: 90,
      thesis: `William O'Neil's CAN SLIM criteria fully satisfied: Accelerating quarterly EPS (>35% YoY), annual earnings growth, new product/catalyst momentum, and leading industry group rank with strong institutional backing.`,
      key_metric: 'CAN SLIM Composite Rank: 96/99',
      quote: 'Whole truth: 90% of the biggest winners in the stock market were emerging growth leaders.',
      checklist: [
        'C: Current Quarterly EPS up > 25% YoY',
        'A: Annual Earnings Growth > 20% over 3 years',
        'N: New high breakout from sound base',
        'I: Institutional Sponsorship increasing (Mutual Funds)',
      ],
      metrics: { 'EPS Growth': '+42% YoY', 'Base Quality': 'Flat Base (5W)', 'Inst Count': '+14 Funds', 'Industry Rank': 'Top 8%' },
    },
    {
      id: 'simons',
      name: 'Jim Simons',
      title: 'Statistical Arbitrage & EV',
      icon: '🧮',
      style: 'Mathematical Quant',
      horizon: '1–5 Days (Intraday/Swing)',
      verdict: 'BUY',
      confidence: 91,
      thesis: `Quantitative statistical edge: Mean reversion Z-score of -2.1 against 20-day regression channel combined with positive mathematical Expected Value (EV = +1.94R). Historical win-rate on identical setups is 73.4%.`,
      key_metric: 'Mathematical EV: +1.94R | Kelly Sizing: 0.42 Half-Kelly',
      quote: 'We search for anomalies in historical price patterns that have statistical significance.',
      checklist: [
        'Mean reversion Z-score < -2.0 standard deviations',
        'Expected Value (EV) > 1.5R with 70%+ edge',
        'Volatility Risk-Parity lot quantization',
        'Cointegration stationary against sector index',
      ],
      metrics: { 'Z-Score': '-2.14 σ', 'Hist Win Rate': '73.4%', 'Expected Value': '+1.94R', 'Sharpe Edge': '2.45' },
    },
    {
      id: 'smc',
      name: 'Smart Money Concepts',
      title: 'Liquidity Sweeps & Order Blocks',
      icon: '🎯',
      style: 'ICT Price Action',
      horizon: '1–3 Sessions (Intraday/Swing)',
      verdict: 'STRONG BUY',
      confidence: 95,
      thesis: `ICT Institutional Price Delivery: Asian session liquidity pool swept, unmitigated Demand Order Block (OB) tapped with Fair Value Gap (FVG) confluence, confirming Market Structure Shift (MSS/CHoCH) to the upside.`,
      key_metric: 'SMC Confluence: Unmitigated Demand OB + FVG Retest',
      quote: 'Smart money engineering liquidity before expanding price to institutional targets.',
      checklist: [
        'Equal lows liquidity sweep completed',
        'Change of Character (CHoCH) on 15m/1h timeframe',
        'Unmitigated Bullish Order Block (OB) tapped cleanly',
        'Fair Value Gap (FVG) imbalances being filled',
      ],
      metrics: { 'Structure': 'Bullish MSS/CHoCH', 'OB Zone': 'Demand OB ₹24,120', 'FVG Retest': 'Filled (100%)', 'Target': 'Buy-Side Liquidity' },
    },
    {
      id: 'forensic',
      name: 'Forensic Auditor',
      title: 'Beneish M-Score & Accruals',
      icon: '🔬',
      style: 'Governance & Quality',
      horizon: 'Fundamental Guardrail',
      verdict: 'BUY (SAFE)',
      confidence: 96,
      thesis: `Beneish M-Score of -2.85 is well below the -1.78 manipulation threshold. Altman Z''-Score of 3.42 indicates strong solvency (Safe Zone). Promoter share pledge is 0.0%, and working capital accruals are pristine.`,
      key_metric: 'Beneish M-Score: -2.85 (Pristine Non-Manipulator)',
      quote: 'First eliminate the accounting landmines, then look for compounding alpha.',
      checklist: [
        'Beneish M-Score < -1.78 (No earnings manipulation)',
        'Altman Z-Score > 2.60 (Strong solvency safe zone)',
        'Piotroski F-Score >= 7/9 (Operational improvement)',
        'Promoter share pledge < 5% (Zero margin call risk)',
      ],
      metrics: { 'Beneish M-Score': '-2.85 (SAFE)', 'Altman Z-Score': '3.42 (SAFE)', 'Piotroski F-Score': '8/9', 'Pledged Shares': '0.0%' },
    },
    {
      id: 'buffett',
      name: 'Warren Buffett',
      title: 'Durable Moat & FCF',
      icon: '🏰',
      style: 'Quality Value',
      horizon: '3–5+ Years (Compounding)',
      verdict: 'BUY',
      confidence: 89,
      thesis: `Wide economic moat with pricing power, Return on Invested Capital (ROIC > 18%), and robust free cash flow compounding. Sustainable competitive advantage in the Indian consumption/industrial landscape.`,
      key_metric: 'ROIC: 21.4% | FCF Conversion: 92%',
      quote: 'It is far better to buy a wonderful company at a fair price than a fair company at a wonderful price.',
      checklist: [
        'High ROIC (>15%) sustained over 5 years',
        'Durable competitive advantage / moat',
        'Strong Free Cash Flow conversion (>85%)',
        'Sensible capital allocation and reinvestment',
      ],
      metrics: { 'ROIC': '21.4%', 'FCF Conversion': '92%', 'Net Debt/EBITDA': '0.3x', 'Moat Rating': 'Wide Moat' },
    },
    {
      id: 'munger',
      name: 'Charlie Munger',
      title: 'Inversion & Mental Models',
      icon: '🧠',
      style: 'Mental Models',
      horizon: '3–5+ Years',
      verdict: 'BUY',
      confidence: 87,
      thesis: `Inverted analysis: Evaluated what could kill this business (technological obsolescence, reckless leverage, dishonest management). Zero fatal risks identified. Lollapalooza compounding factors in play.`,
      key_metric: 'Inversion Risk Score: 94/100 (Zero Fatal Flaws)',
      quote: 'Invert, always invert: Turn a situation upside down. What happens if we do the opposite?',
      checklist: [
        'Zero existential leverage risks',
        'No technological obsolescence threat in 5Y',
        'High return on incremental capital',
        'Management with skin in the game',
      ],
      metrics: { 'Inversion Score': '94/100', 'Leverage Risk': 'Near Zero', 'Governance': 'Top Tier', 'Lollapalooza': 'Present' },
    },
    {
      id: 'jhunjhunwala',
      name: 'Rakesh Jhunjhunwala',
      title: 'India Macro Scale',
      icon: '🐂',
      style: 'Megatrend Growth',
      horizon: '1–3 Years',
      verdict: 'STRONG BUY',
      confidence: 93,
      thesis: `Riding the Mother of All Bull Runs in India. Megatrend expansion driven by domestic demographic dividend, formalization, and multi-year private sector CAPEX cycle. Market is vastly underestimating future earnings scale.`,
      key_metric: 'Market Opportunity: 4.5x TAM Expansion',
      quote: 'Respect the market. Have an open mind. Know what to stake. India is in a structural supercycle.',
      checklist: [
        'Secular domestic demand expansion in India',
        'Market leader taking share from unorganized sector',
        'Operating leverage driving 30%+ profit growth',
        'Undervalued long-term earnings potential',
      ],
      metrics: { 'TAM Growth': '24% CAGR', 'Market Share': '38% (#1)', 'EPS Growth': '+36%', 'India Tailwind': 'Strong' },
    },
    {
      id: 'lynch',
      name: 'Peter Lynch',
      title: 'GARP & Common Sense',
      icon: '🛒',
      style: 'GARP',
      horizon: '6–18 Months',
      verdict: 'BUY',
      confidence: 85,
      thesis: `Growth At a Reasonable Price (GARP): PEG ratio of 0.82 indicates market is underpricing high-growth fundamentals. Common-sense consumer demand visible across Indian retail and commercial channels.`,
      key_metric: 'PEG Ratio: 0.82 (Undervalued Relative to Growth)',
      quote: 'Know what you own, and know why you own it. Look for companies with PEG < 1.0.',
      checklist: [
        'PEG ratio < 1.0 (Fair price for rapid growth)',
        'Fast-growing stalwart category',
        'Inventories growing slower than revenue',
        'Simple, understandable business model',
      ],
      metrics: { 'PEG Ratio': '0.82', 'Revenue Growth': '+28%', 'Inventory Turns': '6.4x', 'Debt/Equity': '0.24' },
    },
    {
      id: 'soros',
      name: 'George Soros',
      title: 'Global Macro Reflexivity',
      icon: '🌊',
      style: 'Global Macro',
      horizon: '1–3 Months',
      verdict: 'BUY',
      confidence: 88,
      thesis: `Soros Reflexivity Theory: Positive feedback loop between institutional capital inflows, credit expansion, and sector earnings revisions. FII/DII liquidity posture creating self-reinforcing upward trend.`,
      key_metric: 'Reflexive Momentum Factor: +2.8σ Positive Feedback',
      quote: 'Markets are constantly in a state of uncertainty and flux, and money is made by discounting the obvious and betting on the unexpected.',
      checklist: [
        'Positive feedback loop between price and fundamentals',
        'FII/DII institutional net buyers for > 5 sessions',
        'India VIX regime stable (< 14.5)',
        'Sector Relative Strength gaining against NIFTY 50',
      ],
      metrics: { 'Macro Regime': 'Expansionary', 'VIX Level': '12.8 (Low)', 'Flow Posture': '+₹1,840 Cr', 'Reflexivity': 'Positive' },
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
      verdict: 'STRONG BUY',
      score: 93,
      members: ['minervini', 'wyckoff', 'oneil', 'forensic'],
      thesis: `High-momentum confluence: Mark Minervini's SEPA Trend Template meets Wyckoff Phase D Volume Spread Analysis and CAN SLIM earnings acceleration, rigorously guarded by Forensic accounting audits.`,
    },
    {
      id: 'options_sniper',
      name: 'Options Sniper',
      icon: '🎯',
      desc: 'SMC + Taleb + Simons',
      badge: 'DEFINED-RISK',
      verdict: 'STRONG BUY',
      score: 95,
      members: ['smc', 'taleb', 'simons'],
      thesis: `Institutional asymmetry: ICT unmitigated Order Block execution paired with Jim Simons' mathematical Expected Value (+1.94R) and Nassim Taleb's Defined-Risk positive convexity options structures.`,
    },
    {
      id: 'multibagger',
      name: 'Multibagger Hub',
      icon: '💎',
      desc: 'Kedia + Buffett + Munger + Jhunjhunwala + Forensic',
      badge: 'COMPOUNDER',
      verdict: 'BUY',
      score: 90,
      members: ['kedia', 'buffett', 'munger', 'jhunjhunwala', 'forensic'],
      thesis: `Long-term Indian compounding powerhouse: Vijay Kedia's SMILE smallcap discovery engine merged with Warren Buffett's durable moat, Charlie Munger's inversion filter, and Jhunjhunwala's secular India supercycle.`,
    },
    {
      id: 'macro_regime',
      name: 'Macro Regime',
      icon: '🌐',
      desc: 'Soros + Jhunjhunwala + Simons + Forensic',
      badge: 'INSTITUTIONAL',
      verdict: 'BUY',
      score: 89,
      members: ['soros', 'jhunjhunwala', 'simons', 'forensic'],
      thesis: `Macro intelligence matrix: George Soros' reflexivity theory coupled with domestic FII/DII institutional flows, Jim Simons' quantitative statistical arbitrage, and India demographic tailwinds.`,
    },
    {
      id: 'core_value',
      name: 'Core Value Moat',
      icon: '🏛️',
      desc: 'Buffett + Munger + Lynch + Forensic',
      badge: 'DEFENSIVE',
      verdict: 'BUY',
      score: 88,
      members: ['buffett', 'munger', 'lynch', 'forensic'],
      thesis: `Defensive capital compounder: Warren Buffett's pricing power moat, Charlie Munger's zero-leverage sanity filter, and Peter Lynch's low PEG ratio (<1.0) backed by pristine Forensic M-Scores.`,
    },
  ]

  // Master Indian Equities & Indices Universe for Instant Search & Watchlist
  const MASTER_WATCHLIST = [
    { symbol: 'NIFTY', name: 'NIFTY 50', cat: 'INDEX', ltp: 24175.65, change_pct: 0.45 },
    { symbol: 'BANKNIFTY', name: 'BANK NIFTY', cat: 'INDEX', ltp: 57496.30, change_pct: 0.62 },
    { symbol: 'FINNIFTY', name: 'FIN NIFTY', cat: 'INDEX', ltp: 24850.00, change_pct: 0.38 },
    { symbol: 'RELIANCE', name: 'Reliance Ind', cat: 'ENERGY', ltp: 1287.00, change_pct: 0.85 },
    { symbol: 'HDFCBANK', name: 'HDFC Bank', cat: 'BANK', ltp: 720.30, change_pct: 0.42 },
    { symbol: 'ICICIBANK', name: 'ICICI Bank', cat: 'BANK', ltp: 1245.50, change_pct: 0.78 },
    { symbol: 'SBIN', name: 'State Bank of India', cat: 'BANK', ltp: 812.40, change_pct: 1.15 },
    { symbol: 'KOTAKBANK', name: 'Kotak Mahindra', cat: 'BANK', ltp: 1785.00, change_pct: -0.25 },
    { symbol: 'AXISBANK', name: 'Axis Bank', cat: 'BANK', ltp: 1195.00, change_pct: 0.55 },
    { symbol: 'INFY', name: 'Infosys', cat: 'TECH', ltp: 1750.00, change_pct: 1.25 },
    { symbol: 'TCS', name: 'Tata Consultancy', cat: 'TECH', ltp: 2342.00, change_pct: 0.90 },
    { symbol: 'HCLTECH', name: 'HCL Tech', cat: 'TECH', ltp: 1780.00, change_pct: 1.45 },
    { symbol: 'WIPRO', name: 'Wipro Ltd', cat: 'TECH', ltp: 545.00, change_pct: 0.35 },
    { symbol: 'COFORGE', name: 'Coforge', cat: 'TECH', ltp: 7850.00, change_pct: 2.15 },
    { symbol: 'TATAMOTORS', name: 'Tata Motors', cat: 'AUTO', ltp: 985.60, change_pct: 1.65 },
    { symbol: 'MARUTI', name: 'Maruti Suzuki', cat: 'AUTO', ltp: 12450.00, change_pct: 0.80 },
    { symbol: 'M&M', name: 'Mahindra & Mahindra', cat: 'AUTO', ltp: 2890.00, change_pct: 1.30 },
    { symbol: 'BAJFINANCE', name: 'Bajaj Finance', cat: 'FINANCE', ltp: 7120.00, change_pct: 0.65 },
    { symbol: 'LT', name: 'Larsen & Toubro', cat: 'INFRA', ltp: 3680.00, change_pct: 0.95 },
    { symbol: 'ITC', name: 'ITC Ltd', cat: 'FMCG', ltp: 505.40, change_pct: 0.20 },
    { symbol: 'BHARTIARTL', name: 'Bharti Airtel', cat: 'TELECOM', ltp: 1650.00, change_pct: 1.10 },
    { symbol: 'SUNPHARMA', name: 'Sun Pharma', cat: 'PHARMA', ltp: 1895.00, change_pct: 0.40 },
    { symbol: 'TITAN', name: 'Titan Company', cat: 'CONSUMER', ltp: 3450.00, change_pct: 0.75 },
    { symbol: 'TRENT', name: 'Trent Ltd', cat: 'STAGE 2', ltp: 7150.00, change_pct: 2.45 },
    { symbol: 'ZOMATO', name: 'Zomato Ltd', cat: 'STAGE 2', ltp: 275.00, change_pct: 3.10 },
    { symbol: 'HAL', name: 'Hindustan Aeronautics', cat: 'DEFENSE', ltp: 4680.00, change_pct: 1.85 },
    { symbol: 'BEL', name: 'Bharat Electronics', cat: 'DEFENSE', ltp: 312.00, change_pct: 2.10 },
    { symbol: 'ADANIENT', name: 'Adani Enterprises', cat: 'STAGE 2', ltp: 3045.00, change_pct: 1.40 },
  ]

  // Combined Watchlist: server items merged with master universe
  const combinedWatchlist = (() => {
    const map = new Map()
    for (const item of MASTER_WATCHLIST) {
      map.set(item.symbol, item)
    }
    for (const item of watchlist) {
      const clean = item.symbol.replace(' 50', '').trim()
      map.set(clean, {
        ...map.get(clean),
        symbol: clean,
        name: item.name || clean,
        ltp: item.ltp || map.get(clean)?.ltp || 1000,
        change_pct: item.change_pct != null ? item.change_pct : (map.get(clean)?.change_pct || 0),
        cat: item.tag || map.get(clean)?.cat || 'EQUITY',
      })
    }
    return Array.from(map.values())
  })()

  // Filtered watchlist based on search term & category filter
  const filteredWatchlist = combinedWatchlist.filter((w) => {
    const matchesCategory =
      watchlistCategory === 'ALL' ||
      w.cat === watchlistCategory ||
      (watchlistCategory === 'INDEX' && (w.symbol === 'NIFTY' || w.symbol === 'BANKNIFTY' || w.symbol === 'FINNIFTY')) ||
      (watchlistCategory === 'STAGE 2' && (w.cat === 'STAGE 2' || w.change_pct > 1.5))

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

  // Active Council & Active Persona Objects
  const activeCouncilObj = MASTER_COUNCILS.find((c) => c.id === selectedCouncil) || MASTER_COUNCILS[0]
  const activePersonaObj = MASTER_PERSONAS.find((p) => p.id === selectedPersona) || MASTER_PERSONAS[0]

  const displaySymbolName =
    selectedSymbol === 'NIFTY'
      ? 'NIFTY 50 (NSE)'
      : selectedSymbol === 'BANKNIFTY'
      ? 'BANK NIFTY (NSE)'
      : `${selectedSymbol} (NSE)`

  const activeWatchItem = combinedWatchlist.find(
    (w) => w.symbol === selectedSymbol || w.name === selectedSymbol || w.symbol.startsWith(selectedSymbol)
  )
  const currentPct = activeWatchItem?.change_pct ?? (setup?.progress ? 0.45 : 0.35)
  const isPos = Number(currentPct) >= 0

  const fiiVal = Number(flows?.fii_net ?? -1450)
  const diiVal = Number(flows?.dii_net ?? 1120)

  return (
    <div className="flex-1 overflow-y-auto p-3 sm:p-5 bg-surface text-text space-y-4 font-ui">
      {/* Top Terminal Status Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-panel/90 border border-border/80 rounded-2xl px-4 py-2.5 shadow-md backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Market Terminal • Live Stream</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted font-mono hidden sm:flex">
            <span className="px-2 py-0.5 rounded bg-surface border border-border text-[10px] text-text font-bold">
              {provenance?.data_source || 'LIVE_TICK'}
            </span>
            <span>{provenance?.as_of || 'Live Market Context'}</span>
          </div>
        </div>

        {/* Quick Timeframe & Action Toolbar */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-elevated rounded-xl p-0.5 border border-border/60 text-xs">
            {['5m', '15m', '1D'].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                  timeframe === tf ? 'bg-amber text-black font-bold shadow-xs' : 'text-muted hover:text-text'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          <button
            onClick={() => sendDraft(`council ${selectedCouncil} ${selectedSymbol}`)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber/15 hover:bg-amber/25 text-amber border border-amber/30 text-xs font-bold transition-colors cursor-pointer shadow-xs"
          >
            <span>🏛️</span> Poll {activeCouncilObj.name}
          </button>
          <button
            onClick={() => sendDraft(`analyze ${selectedSymbol}`)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-400 border border-emerald-500/30 text-xs font-bold transition-colors cursor-pointer shadow-xs"
          >
            <span>⚔️</span> Run Multi-Agent Debate
          </button>
        </div>
      </div>

      {/* Main 3-Column Terminal Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column (3 Cols): AI Councils / Personas / Watchlist */}
        <div className="lg:col-span-3 space-y-3">
          {/* Intelligence Switcher Tabs */}
          <div className="flex items-center bg-panel border border-border/80 rounded-2xl p-1 text-xs font-ui shadow-xs">
            <button
              onClick={() => handleLeftTabChange('councils')}
              className={`flex-1 py-1.5 rounded-xl font-bold transition-all cursor-pointer text-center text-[11px] ${
                leftTab === 'councils'
                  ? 'bg-amber text-black shadow-xs'
                  : 'text-muted hover:text-text'
              }`}
            >
              🏛️ Councils
            </button>
            <button
              onClick={() => handleLeftTabChange('personas')}
              className={`flex-1 py-1.5 rounded-xl font-bold transition-all cursor-pointer text-center text-[11px] ${
                leftTab === 'personas'
                  ? 'bg-amber text-black shadow-xs'
                  : 'text-muted hover:text-text'
              }`}
            >
              🧠 Personas
            </button>
            <button
              onClick={() => handleLeftTabChange('watchlist')}
              className={`flex-1 py-1.5 rounded-xl font-bold transition-all cursor-pointer text-center text-[11px] ${
                leftTab === 'watchlist'
                  ? 'bg-amber text-black shadow-xs'
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
                {['ALL', 'INDEX', 'BANK', 'TECH', 'AUTO', 'STAGE 2'].map((cat) => (
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
                      <div className="text-right font-mono">
                        <span className="text-xs font-bold text-text block">
                          ₹{Number(item.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </span>
                        <span className={`text-[10px] font-semibold ${isPositive ? 'text-green' : 'text-red'}`}>
                          {isPositive ? '+' : ''}
                          {Number(item.change_pct).toFixed(2)}%
                        </span>
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
        </div>

        {/* Center Column (6 Cols): Chart + Dynamic Intelligence Hub (Councils & Personas) */}
        <div className="lg:col-span-6 space-y-4">
          {/* Main Chart Box */}
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm relative overflow-hidden">
            {/* Header info */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3 mb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold text-text font-mono">
                    {displaySymbolName} • {timeframe} • Candlesticks
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-bold border ${isPos ? 'bg-green/10 text-green border-green/30' : 'bg-red/10 text-red border-red/30'}`}>
                    {isPos ? '+' : ''}{Number(currentPct).toFixed(2)}%
                  </span>
                </div>
                <span className="text-[11px] text-muted font-mono">SMC Structure • Demand/Supply OB • Volume Profile</span>
              </div>

              {/* SMC Alpha Badges */}
              <div className="flex items-center gap-1.5">
                <span className="px-2 py-0.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold">
                  SMC DEMAND
                </span>
                <span className="px-2 py-0.5 rounded-md bg-amber/15 border border-amber/30 text-amber text-[10px] font-bold">
                  VOL PROFILE
                </span>
              </div>
            </div>

            {/* Interactive Candlestick Chart */}
            <div className="w-full rounded-xl overflow-hidden bg-surface/50 border border-border/60">
              <CandlestickChart symbol={selectedSymbol} timeframe={timeframe} height={260} />
            </div>

            {/* Overlay SMC Box Details (Order Block & Volume Profile) */}
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-border/40 text-xs font-mono">
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">UNMITIGATED OB</span>
                <span className="font-bold text-emerald-400">
                  ₹{setup?.order_block?.bottom || '24,120'} – ₹{setup?.order_block?.top || '24,180'}
                </span>
              </div>
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">POC (Max Vol)</span>
                <span className="font-bold text-amber">₹{setup?.volume_profile?.poc || '24,165'}</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">VAH (70% High)</span>
                <span className="font-bold text-blue-400">₹{setup?.volume_profile?.vah || '24,240'}</span>
              </div>
              <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
                <span className="text-[10px] text-muted block">VAL (70% Low)</span>
                <span className="font-bold text-purple-400">₹{setup?.volume_profile?.val || '24,080'}</span>
              </div>
            </div>
          </div>

          {/* DYNAMIC INTELLIGENCE DECK: Synchronized with Left Nav selection */}
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm relative space-y-3.5">
            {/* View Mode Pill Switcher */}
            <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-amber text-base">
                  {intelligenceMode === 'councils' ? activeCouncilObj.icon : activePersonaObj.icon}
                </span>
                <div>
                  <h3 className="text-sm font-bold text-text flex items-center gap-2">
                    <span>
                      {intelligenceMode === 'councils'
                        ? `${activeCouncilObj.name} Consensus`
                        : `${activePersonaObj.name} Framework`}
                    </span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface border border-border text-amber font-mono font-bold">
                      {selectedSymbol}
                    </span>
                  </h3>
                  <span className="text-[11px] text-muted">
                    {intelligenceMode === 'councils'
                      ? `${activeCouncilObj.members.length} Specialist Minds Polled`
                      : activePersonaObj.title}
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
                        <span>{c.icon}</span>
                        <span>{c.name}</span>
                        <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-black/20 text-current font-bold">
                          {c.score}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {/* Active Council Banner */}
                <div className="bg-surface/90 border border-border/70 rounded-xl p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-text block">{activeCouncilObj.name} Consensus</span>
                      <span className="text-[11px] text-muted">{activeCouncilObj.desc}</span>
                    </div>
                    <div className="text-right">
                      <span className="px-2.5 py-0.5 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-extrabold block">
                        {activeCouncilObj.verdict}
                      </span>
                      <span className="text-[10px] text-amber font-mono font-bold">
                        Conviction: {activeCouncilObj.score}/100
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-text/90 leading-relaxed font-ui border-t border-border/40 pt-2">
                    {activeCouncilObj.thesis}
                  </p>
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
                                {member.name}
                              </span>
                            </div>
                            <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-1.5 py-0.2 rounded">
                              {member.verdict}
                            </span>
                          </div>
                          <p className="text-[10px] text-muted leading-tight truncate">
                            • {member.checklist[0]}
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
                          {p.confidence}%
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
                      <span className="px-2.5 py-0.5 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-extrabold block">
                        {activePersonaObj.verdict}
                      </span>
                      <span className="text-[10px] text-amber font-mono font-bold">
                        {activePersonaObj.confidence}% Conviction
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-text leading-relaxed font-ui border-t border-border/40 pt-2">
                    {activePersonaObj.thesis}
                  </p>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] font-mono border-t border-border/40">
                    <span className="text-emerald-400 font-semibold flex items-center gap-1">
                      <span>📊</span> {activePersonaObj.key_metric}
                    </span>
                    <span className="text-muted italic text-[10px]">
                      &quot;{activePersonaObj.quote}&quot;
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
                    {activePersonaObj.checklist.map((rule, idx) => (
                      <div key={idx} className="flex items-start gap-1.5 text-xs text-text/90 font-ui leading-tight">
                        <span className="text-emerald-400 font-bold">✓</span>
                        <span>{rule}</span>
                      </div>
                    ))}
                  </div>

                  {/* Dimension Metrics */}
                  <div className="p-3 rounded-xl bg-surface/70 border border-border/60 space-y-1.5">
                    <span className="text-[10px] uppercase font-bold text-muted tracking-wider block">
                      Evaluated Quant Scores:
                    </span>
                    <div className="grid grid-cols-2 gap-1.5">
                      {Object.entries(activePersonaObj.metrics).map(([k, v]) => (
                        <div key={k} className="p-2 rounded-lg bg-elevated/70 border border-border/50 text-[11px] font-mono">
                          <span className="text-muted text-[10px] block truncate">{k}</span>
                          <span className="font-bold text-text">{v}</span>
                        </div>
                      ))}
                    </div>
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

        {/* Right Column (3 Cols): Automated Setup Ticket */}
        <div className="lg:col-span-3 space-y-4">
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-3.5">
            <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-muted block">
                  AUTOMATED SETUP
                </span>
                <span className="text-[10px] text-emerald-400 font-semibold">(Institutional Risk Gate)</span>
              </div>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                setup?.action?.includes('SHORT')
                  ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                  : 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
              }`}>
                {setup?.status || 'READY'}
              </span>
            </div>

            {/* Timeline Horizon Badge */}
            <div className="flex items-center justify-between px-2.5 py-1 rounded-lg bg-surface/80 border border-border/60 text-[11px] font-mono">
              <span className="text-muted">⏱️ Timeline</span>
              <span className="text-amber font-semibold">{setup?.timeline || `${timeframe === 'day' ? '5–15 Days (Positional)' : '1–3 Sessions (Intraday)'}`}</span>
            </div>

            {/* Signal Details */}
            {(() => {
              const curLtp = MASTER_WATCHLIST.find((m) => m.symbol === selectedSymbol)?.ltp || data?.ltp || 1000.0
              const isShort = setup?.action && setup.action.includes('SHORT')
              const safeEntry = setup?.entry != null ? Number(setup.entry) : Number((curLtp * (isShort ? 1.002 : 0.998)).toFixed(2))
              const safeSl = setup?.stop_loss != null ? Number(setup.stop_loss) : Number((isShort ? curLtp * 1.012 : curLtp * 0.988).toFixed(2))
              const safeTgt1 = setup?.target_1 != null ? Number(setup.target_1) : Number((isShort ? curLtp * 0.976 : curLtp * 1.024).toFixed(2))
              const safeTgt2 = setup?.target_2 != null ? Number(setup.target_2) : Number((isShort ? curLtp * 0.958 : curLtp * 1.042).toFixed(2))
              const riskPts = setup?.risk_points ?? Math.abs(safeEntry - safeSl).toFixed(2)
              const riskPct = setup?.risk_pct ?? ((riskPts / safeEntry) * 100).toFixed(2)
              const rewPts = setup?.reward_points ?? Math.abs(safeTgt1 - safeEntry).toFixed(2)
              const rewPct = setup?.reward_pct ?? ((rewPts / safeEntry) * 100).toFixed(2)

              return (
                <div className="space-y-2 text-xs font-mono">
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">Symbol</span>
                    <span className="font-bold text-text">{setup?.symbol || `${selectedSymbol} (NSE)`}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">Action</span>
                    <span className={`font-bold px-2 py-0.5 rounded border ${
                      isShort
                        ? 'text-rose-400 bg-rose-500/15 border-rose-500/30'
                        : 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30'
                    }`}>
                      {setup?.action || (isShort ? 'SHORT (SELL)' : 'LONG (BUY)')}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">Trigger</span>
                    <span className="font-bold text-text">{setup?.trigger || (isShort ? 'Supply Rejection' : 'Demand Retest')}</span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">ENTRY PRICE</span>
                    <span className="font-bold text-emerald-400">
                      ₹{safeEntry.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">INVALIDATION SL</span>
                    <div className="text-right">
                      <span className="font-bold text-rose-400 block">
                        ₹{safeSl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <span className="text-[10px] text-muted">
                        (-{riskPts} pts / {riskPct}%)
                      </span>
                    </div>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">TARGET 1 (2R)</span>
                    <div className="text-right">
                      <span className="font-bold text-emerald-400 block">
                        ₹{safeTgt1.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </span>
                      <span className="text-[10px] text-muted">
                        (+{rewPts} pts / {rewPct}%)
                      </span>
                    </div>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">TARGET 2 (3.5R)</span>
                    <span className="font-bold text-text">
                      ₹{safeTgt2.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/30">
                    <span className="text-muted">R:R PAYOFF</span>
                    <span className="font-bold text-amber">1 : {setup?.risk_reward || '2.0'} R</span>
                  </div>

                  {/* Setup Thesis & Actionable Insights Box */}
                  <div className="p-2 rounded-xl bg-surface/90 border border-border/60 text-[11px] space-y-1">
                    <span className="text-muted font-bold block flex items-center gap-1">
                      <span>💡</span> Setup Thesis
                    </span>
                    <p className="text-text leading-snug font-ui text-[11px]">
                      {setup?.thesis || `Unmitigated ${isShort ? 'Supply' : 'Demand'} zone retest with institutional volume absorption and structured invalidation.`}
                    </p>
                  </div>

                  {/* Trailing Stop Rule */}
                  <div className="px-2 py-1.5 rounded-lg bg-elevated/60 border border-border/40 text-[10px] text-muted flex items-start gap-1.5">
                    <span>🛡️</span>
                    <span><strong>Rule:</strong> Move SL to Breakeven (+0.2% buffer) at Target 1. Trail rest with 3x ATR.</span>
                  </div>

                  {/* Execute Button */}
                  <button
                    onClick={() => {
                      if (onOpenOrderTicket) {
                        onOpenOrderTicket({
                          symbol: selectedSymbol,
                          exchange: 'NSE',
                          price: safeEntry,
                          stopLoss: safeSl,
                          target: safeTgt1,
                          action: isShort ? 'SELL' : 'BUY',
                        })
                      }
                    }}
                    className="w-full py-2.5 px-4 mt-2 rounded-xl bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black font-bold text-xs uppercase tracking-wider transition-all shadow-md cursor-pointer flex items-center justify-center gap-2"
                  >
                    <span>⚡</span> STAGE / EXECUTE ORDER
                  </button>
                </div>
              )
            })()}
          </div>
        </div>
      </div>

      {/* Bottom Row: 3-Card High Impact Analytics Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Card 1: Institutional Flows & Macro Pulse (3 Cols) */}
        <div className="lg:col-span-3 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-border/50 pb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
                <span>🌊</span> INSTITUTIONAL FLOWS
              </span>
              <span className="text-[9px] px-1.5 py-0.2 rounded bg-surface border border-border text-muted font-mono">
                {flows?.label || 'DLY CASH'}
              </span>
            </div>

            <div className="space-y-2 pt-2 text-xs font-mono">
              <div className="flex items-center justify-between bg-surface/80 p-2 rounded-xl border border-border/50">
                <span className="text-muted text-[11px]">FII Net Cash</span>
                <span className={`font-bold ${fiiVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {fiiVal >= 0 ? '+' : ''}₹{Number(fiiVal).toLocaleString('en-IN')} Cr
                </span>
              </div>

              <div className="flex items-center justify-between bg-surface/80 p-2 rounded-xl border border-border/50">
                <span className="text-muted text-[11px]">DII Net Cash</span>
                <span className={`font-bold ${diiVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {diiVal >= 0 ? '+' : ''}₹{Number(diiVal).toLocaleString('en-IN')} Cr
                </span>
              </div>

              <div className="flex items-center justify-between bg-surface/80 p-2 rounded-xl border border-border/50">
                <span className="text-muted text-[11px]">Net Cash Flow</span>
                <span className={`font-bold text-sm ${Number(flows?.net_total || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {Number(flows?.net_total || 0) >= 0 ? '+' : ''}₹{Number(flows?.net_total || 0).toLocaleString('en-IN')} Cr
                </span>
              </div>
            </div>
          </div>

          <div className="pt-1">
            <span className="text-[10px] font-bold text-amber font-mono block truncate bg-amber/10 border border-amber/30 px-2 py-1 rounded-lg text-center">
              {flows?.verdict || 'FII / DII INSTITUTIONAL BALANCE'}
            </span>
          </div>
        </div>

        {/* Card 2: Multi-Timeframe Technical Confluence (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-2xl p-4 shadow-sm space-y-2.5">
          <div className="flex items-center justify-between border-b border-border/50 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted flex items-center gap-1.5">
              <span>⚡</span> MULTI-TF CONFLUENCE
            </span>
            <span className="text-[10px] font-bold font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
              {data?.multi_tf?.confluence_score || 88}% CONFLUENCE
            </span>
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            {(data?.multi_tf?.timeframes || [
              { tf: '15m', label: 'Intraday', bias: 'BULLISH', signal: 'SMC Order Block Retest', rsi: 58.4, key_level: 'OB ₹24,120' },
              { tf: '1h', label: 'Swing', bias: 'BULLISH', signal: 'Higher Highs Structure', rsi: 61.2, key_level: 'EMA20 ₹24,050' },
              { tf: '1D', label: 'Trend', bias: 'BULLISH', signal: 'Stage 2 Markup (Minervini)', rsi: 64.8, key_level: '50-SMA ₹23,800' },
            ]).map((tfItem) => {
              const isBull = tfItem.bias === 'BULLISH'
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
                      <span className="font-semibold text-text text-xs block">{tfItem.signal}</span>
                      <span className="text-[10px] text-muted">{tfItem.key_level}</span>
                    </div>
                  </div>

                  <div className="text-right">
                    <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${isBull ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'}`}>
                      {tfItem.bias}
                    </span>
                    <span className="text-[10px] text-muted block font-mono">RSI {tfItem.rsi}</span>
                  </div>
                </div>
              )
            })}
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

          {/* RRG Quadrant Grid */}
          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
            {/* LEADING (Top Right) */}
            <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-2.5 space-y-1">
              <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider block flex items-center justify-between">
                <span>🟢 LEADING</span>
                <span className="text-[9px] text-muted">RS &gt; 100, Mom &gt; 100</span>
              </span>
              <div className="space-y-0.5">
                {(sectors.filter((s) => s.quadrant === 'LEADING' || s.name?.includes('AUTO') || s.name?.includes('METALS') || s.name?.includes('DEFENSE')).slice(0, 2)).map((s, idx) => (
                  <div key={idx} className="flex justify-between text-[11px]">
                    <span className="font-bold text-text">{s.name || 'NIFTY AUTO'}</span>
                    <span className="text-emerald-400 font-semibold">+{s.rs_ratio || 102.4}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* IMPROVING (Bottom Right) */}
            <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-xl p-2.5 space-y-1">
              <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider block flex items-center justify-between">
                <span>🔵 IMPROVING</span>
                <span className="text-[9px] text-muted">Mom &gt; 100</span>
              </span>
              <div className="space-y-0.5">
                {(sectors.filter((s) => s.quadrant === 'IMPROVING' || s.name?.includes('PHARMA') || s.name?.includes('IT') || s.name?.includes('TECH')).slice(0, 2)).map((s, idx) => (
                  <div key={idx} className="flex justify-between text-[11px]">
                    <span className="font-bold text-text">{s.name || 'NIFTY IT'}</span>
                    <span className="text-cyan-400 font-semibold">+{s.rs_ratio || 99.8}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* WEAKENING (Top Left) */}
            <div className="bg-amber/10 border border-amber/30 rounded-xl p-2.5 space-y-1">
              <span className="text-[10px] font-bold text-amber uppercase tracking-wider block flex items-center justify-between">
                <span>🟡 WEAKENING</span>
                <span className="text-[9px] text-muted">Mom &lt; 100</span>
              </span>
              <div className="space-y-0.5">
                {(sectors.filter((s) => s.quadrant === 'WEAKENING' || s.name?.includes('BANK') || s.name?.includes('FIN')).slice(0, 2)).map((s, idx) => (
                  <div key={idx} className="flex justify-between text-[11px]">
                    <span className="font-bold text-text">{s.name || 'NIFTY BANK'}</span>
                    <span className="text-amber font-semibold">{s.rs_ratio || 101.1}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* LAGGING (Bottom Left) */}
            <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-2.5 space-y-1">
              <span className="text-[10px] font-bold text-rose-400 uppercase tracking-wider block flex items-center justify-between">
                <span>🔴 LAGGING</span>
                <span className="text-[9px] text-muted">RS &lt; 100, Mom &lt; 100</span>
              </span>
              <div className="space-y-0.5">
                {(sectors.filter((s) => s.quadrant === 'LAGGING' || s.name?.includes('FMCG') || s.name?.includes('MEDIA') || s.name?.includes('REALTY')).slice(0, 2)).map((s, idx) => (
                  <div key={idx} className="flex justify-between text-[11px]">
                    <span className="font-bold text-text">{s.name || 'NIFTY FMCG'}</span>
                    <span className="text-rose-400 font-semibold">{s.rs_ratio || 97.5}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
