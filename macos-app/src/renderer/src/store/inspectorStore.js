import { create } from 'zustand'

export const METRIC_ENCYCLOPEDIA = {
  beneish_m_score: {
    title: 'Beneish M-Score (Earnings Manipulation Model)',
    category: 'Forensic Accounting',
    tagColor: 'amber',
    formula: 'M = -4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI - 0.172·SGAI + 4.037·TATA + 0.0327·LVGI',
    thresholds: [
      { condition: 'M ≤ -1.78', label: 'CLEAN / SAFE', color: 'green', desc: 'Low probability of earnings manipulation or aggressive revenue recognition.' },
      { condition: 'M > -1.78', label: 'FLAGGED / AT RISK', color: 'red', desc: 'Statistically elevated probability of financial statement manipulation.' },
    ],
    explanation: 'Created by Prof. Messod Beneish, this 8-variable quantitative model identifies companies likely to be artificially inflating revenue, understating expenses, or shifting future earnings.',
    institutionalGuide: 'Institutional fund managers reject or penalize companies with M-Score > -1.78 because historical backtests show that flagged companies underperform benchmarks by over 12% annually.',
    variables: [
      { name: 'DSRI (Days Sales in Receivables Index)', desc: 'Measures whether receivables are growing faster than revenues (premature revenue booking).' },
      { name: 'GMI (Gross Margin Index)', desc: 'Detects deteriorating gross margins, a common driver of accounting pressure.' },
      { name: 'AQI (Asset Quality Index)', desc: 'Identifies capitalization of operating expenses into non-current assets.' },
      { name: 'SGI (Sales Growth Index)', desc: 'High growth firms face severe incentive pressures to maintain momentum.' },
      { name: 'TATA (Total Accruals to Total Assets)', desc: 'Examines divergence between accounting Net Income and actual Operating Cash Flow.' },
    ],
  },

  altman_z_score: {
    title: "Altman Z''-Score (Emerging Market Solvency Model)",
    category: 'Credit & Solvency',
    tagColor: 'blue',
    formula: "Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4",
    thresholds: [
      { condition: "Z'' > 2.60", label: 'SAFE ZONE', color: 'green', desc: 'Robust liquidity, solid retained earnings, and low insolvency risk.' },
      { condition: "1.10 ≤ Z'' ≤ 2.60", label: 'GREY ZONE', color: 'amber', desc: 'Moderate credit risk; warrants debt service coverage monitoring.' },
      { condition: "Z'' < 1.10", label: 'DISTRESS ZONE', color: 'red', desc: 'Substantial bankruptcy or default vulnerability within 24 months.' },
    ],
    explanation: "Edward Altman's 4-variable Z''-Score model is specifically adapted for emerging markets, non-manufacturers, and service corporations without requiring public equity market cap distortions.",
    institutionalGuide: 'Credit desks and long-only funds use the Z-Score to filter out insolvency traps. A score below 1.10 mandates a hard stop or hedging against corporate credit degradation.',
    variables: [
      { name: 'X1 (Working Capital / Total Assets)', desc: 'Measures net liquid assets relative to firm size.' },
      { name: 'X2 (Retained Earnings / Total Assets)', desc: 'Reflects cumulative profitability and age of firm.' },
      { name: 'X3 (EBIT / Total Assets)', desc: 'True asset productivity unburdened by tax or leverage.' },
      { name: 'X4 (Book Value of Equity / Total Liabilities)', desc: 'Capital cushion available before liabilities exceed assets.' },
    ],
  },

  piotroski_f_score: {
    title: 'Piotroski 9-Point F-Score (Fundamental Quality)',
    category: 'Fundamental Quality',
    tagColor: 'green',
    formula: 'F = Σ (Profitability [4 pts] + Leverage & Liquidity [3 pts] + Operating Efficiency [2 pts])',
    thresholds: [
      { condition: 'F = 8–9', label: 'VERY STRONG QUALITY', color: 'green', desc: 'Top decile operational performance across all metrics.' },
      { condition: 'F = 5–7', label: 'STABLE / AVERAGE', color: 'blue', desc: 'Sound operational metrics with minor areas of stagnation.' },
      { condition: 'F ≤ 4', label: 'WEAK / DETERIORATING', color: 'red', desc: 'Fundamental quality is deteriorating; high turnover risk.' },
    ],
    explanation: 'Designed by Stanford Professor Joseph Piotroski, this 9-criteria binary checklist evaluates continuous improvement in profitability, cash flow generation, leverage reduction, and asset turnover.',
    institutionalGuide: 'Piotroski F-Score is widely used as an institutional quality filter in Smart Beta ETFs. Pairing value stocks (low P/B) with high F-Scores (≥7) historically eliminates 70% of value traps.',
    variables: [
      { name: 'Profitability (4 pts)', desc: 'Positive ROA, Positive Operating Cash Flow, YoY ROA Growth, and Cash Flow > Net Income (Accrual Quality).' },
      { name: 'Leverage & Liquidity (3 pts)', desc: 'YoY Debt/Equity Reduction, Current Ratio Expansion, Zero Dilutive Share Issuance.' },
      { name: 'Operating Efficiency (2 pts)', desc: 'Gross Margin Expansion and Asset Turnover Growth.' },
    ],
  },

  rrg_sector_matrix: {
    title: 'Relative Rotation Graph (RRG) Matrix',
    category: 'Quantitative Momentum',
    tagColor: 'purple',
    formula: 'RS-Ratio = 100 + ( (Price_sector / Benchmark) - SMA(RS) ) / StdDev(RS) \nRS-Momentum = 100 + ( RS-Ratio - SMA(RS-Ratio) ) / StdDev(RS-Ratio)',
    thresholds: [
      { condition: 'LEADING (Top Right)', label: 'RS-Ratio > 100 & RS-Mom > 100', color: 'green', desc: 'Outperforming benchmark and accelerating. Primary alpha source.' },
      { condition: 'WEAKENING (Bottom Right)', label: 'RS-Ratio > 100 & RS-Mom < 100', color: 'amber', desc: 'Outperforming but losing momentum. Harvest profits / tighten trailing stops.' },
      { condition: 'LAGGING (Bottom Left)', label: 'RS-Ratio < 100 & RS-Mom < 100', color: 'red', desc: 'Underperforming and decelerating. Avoid long exposures / potential shorts.' },
      { condition: 'IMPROVING (Top Left)', label: 'RS-Ratio < 100 & RS-Mom > 100', color: 'blue', desc: 'Underperforming but gaining velocity. Early turnaround candidate.' },
    ],
    explanation: 'Relative Rotation Graphs (developed by Julius de Kempenaer) visualize the relative strength trend (X-axis) and velocity (Y-axis) of sector indices against the NIFTY 50 benchmark on a 2D plane.',
    institutionalGuide: 'Sector rotation drives over 60% of equity portfolio returns. Systematic managers allocate capital towards stocks residing in LEADING and IMPROVING sectors to gain institutional tailwinds.',
  },

  volatility_risk_parity: {
    title: 'ATR Volatility Risk-Parity Sizing',
    category: 'Risk Management',
    tagColor: 'amber',
    formula: 'Dollar_Risk = Account_Capital × Risk_Budget_Pct \nVol_Stop_Distance = ATR_14 × 1.5 \nOptimal_Shares = Dollar_Risk / Vol_Stop_Distance',
    thresholds: [
      { condition: 'Risk Budget: 1.0% - 2.0%', label: 'CONSERVATIVE / PRUDENT', color: 'green', desc: 'Prevents catastrophic drawdown even during 10 consecutive loss streaks.' },
      { condition: 'Single Stock Cap: ≤ 25%', label: 'MAX ALLOCATION CEILING', color: 'blue', desc: 'Limits concentration risk in single names.' },
    ],
    explanation: 'Volatility Risk Parity calculates position sizing such that every trade contributes an equal dollar risk to the portfolio, regardless of whether the asset is highly volatile or stable.',
    institutionalGuide: 'By sizing inversely to volatility (wider stops get smaller share counts), hedge funds eliminate the risk of a single high-beta stock dominating portfolio drawdown.',
  },

  half_kelly: {
    title: 'Half-Kelly Capital Allocation Criterion',
    category: 'Quantitative Growth',
    tagColor: 'green',
    formula: 'f* = [ (p · b - q) / b ] × 0.5 \nWhere: p = Win Rate, q = (1 - p), b = Win/Loss Payoff Ratio',
    thresholds: [
      { condition: 'Half-Kelly (0.5x)', label: 'OPTIMAL GROWTH', color: 'green', desc: '75% of full Kelly growth rate with 50% lower volatility and drastically reduced drawdown.' },
    ],
    explanation: 'The Kelly Criterion determines the theoretically optimal fraction of capital to risk on a series of positive-expectancy bets. In financial markets, Full-Kelly is notoriously volatile, so professional quantitative desks universally use Half-Kelly (0.5x).',
    institutionalGuide: 'Prevents over-allocation when strategy win rates are elevated. Provides geometric growth while insulating account capital from variance spikes.',
  },

  governance_red_flags: {
    title: 'Indian Corporate Governance & Red Flag Auditing',
    category: 'Forensic Risk',
    tagColor: 'red',
    formula: 'Pledge_Ratio = Pledged_Promoter_Shares / Total_Promoter_Shares \nInterest_Coverage = EBIT / Finance_Costs',
    thresholds: [
      { condition: 'Promoter Pledge > 20%', label: 'CRITICAL HAZARD', color: 'red', desc: 'High margin call liquidation hazard if stock corrects.' },
      { condition: 'Promoter Pledge 10%–20%', label: 'MODERATE CAUTION', color: 'amber', desc: 'Requires continuous tracking of collateral buffer.' },
      { condition: 'Interest Coverage < 2.0x', label: 'DEBT STRESS', color: 'red', desc: 'Operating earnings insufficient to comfortably service interest burden.' },
    ],
    explanation: 'Indian market governance forensic screeners check for promoter share encumbrances, circular transactions, related-party debt guarantees, and rapid auditor resignations.',
    institutionalGuide: 'Stocks with promoter pledges exceeding 20% frequently suffer cascading flash crashes when NBFCs and mutual funds dump pledged collateral into illiquid markets.',
  },

  smart_funnel_pipeline: {
    title: 'Smart Funnel 3-Stage Screening Pipeline',
    category: 'Multi-Agent Orchestration',
    tagColor: 'amber',
    formula: 'Candidate Score = Technicals(30%) + Valuation(20%) + Sector RRG Tailwind(25%) + Forensic Score(25%) - Red Flag Penalties',
    thresholds: [
      { condition: 'Score ≥ 70', label: 'QUALIFIED CANDIDATE', color: 'green', desc: 'Passed deterministic pre-filter; advances to Bull vs Bear LLM debate.' },
      { condition: 'Score < 70', label: 'DISQUALIFIED / FILTERED', color: 'red', desc: 'Eliminated in Stage 1 without consuming LLM inference tokens.' },
    ],
    explanation: 'A 3-stage quantitative funnel that filters 100+ tickers deterministically in Stage 1, contextualizes with macro & VIX in Stage 2, and runs an adversarial Bull vs Bear multi-agent debate in Stage 3.',
    institutionalGuide: 'Combines algorithmic cost-efficiency with deep adversarial qualitative debate to produce institutional trade plans with strict invalidation stops.',
    variables: [
      { name: 'Stage 1 (Pure Quant Pre-Filter)', desc: 'Zero-token algorithmic screen on RSI, EMAs, DCF upside, RRG tailwinds, and Beneish M-Score.' },
      { name: 'Stage 2 (Macro Context Injection)', desc: 'Injects India VIX, FII/DII institutional net flows, and Sector RRG rotation matrix.' },
      { name: 'Stage 3 (Adversarial Persona Debate)', desc: 'Bull vs Bear analysts synthesize trade plan under Facilitator & Fund Manager supervision.' },
    ],
  },

  market_structure_smc: {
    title: 'Smart Money Concepts (SMC) & Market Structure',
    category: 'Price Action & SMC',
    tagColor: 'green',
    formula: 'BULLISH: HH + HL Sequence | BEARISH: LH + LL Sequence\nCHoCH: Break above prior Lower High in downtrend (Bullish Reversal)',
    thresholds: [
      { condition: 'Score ≥ +40', label: 'CONFIRMED BULLISH STRUCTURE', color: 'green', desc: 'Higher Highs and Higher Lows confirmed by fractal swing points.' },
      { condition: 'CHoCH Triggered', label: 'MARKET STRUCTURE SHIFT', color: 'amber', desc: 'Early trend reversal transition (Wyckoff Spring or Breakout).' },
      { condition: 'Score ≤ -40', label: 'CONFIRMED BEARISH STRUCTURE', color: 'red', desc: 'Lower Highs and Lower Lows; avoid long entries.' },
    ],
    explanation: 'Smart Money Concepts analyzes market structure through fractal swing pivots, unmitigated Order Blocks (institutional demand/supply footprints), Fair Value Gaps (FVG liquidity imbalances), and liquidity sweeps.',
    institutionalGuide: 'Enter exclusively in the direction of the dominant higher-timeframe structure, ideally on pullbacks into unmitigated Demand Order Blocks with invalidation stops below confirmed structural swing lows.',
    variables: [
      { name: 'MSS / CHoCH (Change of Character)', desc: 'Early structural trend shift breaking prior swing high/low (bottom or top fishing trigger).' },
      { name: 'BOS (Break of Structure)', desc: 'Trend continuation break confirming aggressive institutional momentum.' },
      { name: 'Demand Order Block (OB)', desc: 'Last down candle prior to an explosive upward displacement move that broke market structure.' },
      { name: 'Fair Value Gap (FVG)', desc: '3-candle price imbalance indicating rapid institutional order filling with unfilled liquidity.' },
      { name: 'Liquidity Sweep (Stop Hunt)', desc: 'False breakout below swing low that immediately reclaims the level (Wyckoff Spring).' },
    ],
  },

  volume_profile_vpa: {
    title: 'Volume Price Analysis (VPA) & Volume Profile',
    category: 'Volume & Footprint',
    tagColor: 'blue',
    formula: 'RVOL = Current Volume / 20-Day SMA Volume\nValue Area = 70% of total volume radiating from Point of Control (POC)',
    thresholds: [
      { condition: 'RVOL ≥ 2.0x', label: 'HIGH INSTITUTIONAL VOLUME', color: 'green', desc: 'Heavy institutional buying or selling participation.' },
      { condition: 'Above VAH', label: 'VALUE AREA EXPANSION', color: 'blue', desc: 'Price accepted above Value Area High (bullish breakout).' },
      { condition: 'RVOL < 0.6x', label: 'VOLUME DRY-UP', color: 'amber', desc: 'Lack of selling pressure on pullbacks (seller exhaustion).' },
    ],
    explanation: 'Combines Point of Control (POC) Volume Profile histograms with Wyckoff Volume Spread Analysis (VSA) to detect absorption, stopping volume, and institutional accumulation.',
    institutionalGuide: 'Genuine breakouts must be backed by RVOL ≥ 1.8x. Narrow spread bars on high volume signal stopping volume / institutional absorption.',
    variables: [
      { name: 'POC (Point of Control)', desc: 'Price level where the maximum trading volume was transacted (strong gravitational support/resistance).' },
      { name: 'VAH & VAL', desc: 'Value Area High (upper 70% boundary) and Value Area Low (lower 70% boundary).' },
      { name: 'Absorption / Stopping Volume', desc: 'High volume with narrow spread near support indicating institutions buying up all retail panic selling.' },
    ],
  },

  minervini_trend_template: {
    title: 'Mark Minervini 8-Point Trend Template',
    category: 'Positional Superperformers',
    tagColor: 'purple',
    formula: 'Criteria: Price > 150 & 200 SMA, 150 > 200 SMA, 200 SMA Rising, 50 > 150 & 200, Price > 50 SMA, >= 30% Above 52W Low, <= 25% Off 52W High',
    thresholds: [
      { condition: '8 / 8 Passed', label: 'PERFECT STAGE 2 LEADER', color: 'green', desc: 'Meets all quantitative requirements of historical multibagger superperformers.' },
      { condition: '6–7 Passed', label: 'QUALIFIED LEADER', color: 'blue', desc: 'Strong technical momentum alignment; valid candidate for breakout.' },
      { condition: '< 6 Passed', label: 'DISQUALIFIED / BASE FORMING', color: 'red', desc: 'Lacks full institutional trend alignment; avoid aggressive positioning.' },
    ],
    explanation: 'Developed by U.S. Investing Champion Mark Minervini, this 8-criteria trend template is the definitive filter used to identify stocks in powerful Stage 2 markup phases prior to multi-hundred percent gains.',
    institutionalGuide: 'Never buy a stock trading below its 200-day moving average or in a Stage 4 decline. Leaders make higher highs while holding above their 50-day moving average.',
    variables: [
      { name: 'Moving Average Alignment', desc: 'Price > 50 EMA > 150 EMA > 200 SMA with upward slope.' },
      { name: '52-Week High Proximity', desc: 'Stock must trade within 25% of its 52-week high (multibaggers lead near highs).' },
      { name: '52-Week Low Distance', desc: 'Stock must be at least 30% above its 52-week low to ensure bottom lag is eliminated.' },
    ],
  },

  weinstein_stage_analysis: {
    title: 'Stan Weinstein 4-Stage Market Analysis',
    category: 'Positional Cycles',
    tagColor: 'green',
    formula: 'Stage 1 (Basing) -> Stage 2 (Markup/Expansion) -> Stage 3 (Distribution) -> Stage 4 (Markdown/Decline)',
    thresholds: [
      { condition: 'Stage 2 (Markup)', label: 'BUY / MULTIBAGGER ZONE', color: 'green', desc: 'Breakout above 30-week / 200-day SMA on massive volume. Heavy long bias.' },
      { condition: 'Stage 1 (Base)', label: 'WATCHLIST / ACCUMULATION', color: 'blue', desc: 'Constructing multi-month base; wait for Stage 2 breakout confirmation.' },
      { condition: 'Stage 4 (Markdown)', label: 'AVOID / SHORT ZONE', color: 'red', desc: 'Declining price below falling 200-day SMA. Never hold or average down.' },
    ],
    explanation: 'Classic stage analysis framework created by Stan Weinstein in Secrets for Profiting in Bull and Bear Markets. Classifies every asset into 4 distinct macro phases based on its 30-week (200-day) moving average.',
    institutionalGuide: '100% of major multibaggers originate from a Stage 2 breakout. Position traders enter on the initial Stage 2 expansion or on low-volume retests of the 50-day EMA.',
    variables: [
      { name: 'Stage 1 (Basing Area)', desc: 'Price oscillates sideways around a flattening 200-day SMA with diminishing volume.' },
      { name: 'Stage 2 (Advancing Phase)', desc: 'Explosive breakout above resistance on high volume, 200-day SMA turns upward.' },
      { name: 'Stage 3 (Top Area)', desc: 'Volatility widens, volume expands on down-days, 200-day SMA flattens.' },
      { name: 'Stage 4 (Declining Phase)', desc: 'Breakdown below support, price collapses below declining 200-day SMA.' },
    ],
  },

  chandelier_trailing_sl: {
    title: 'Chandelier ATR & Structure Trailing Stop-Loss',
    category: 'Trade Management',
    tagColor: 'amber',
    formula: 'Chandelier Stop = Highest High (N bars) - (3.0 · ATR_14)\nStructure Stop = Highest Confirmed Higher Low (HL) on Daily Timeframe',
    thresholds: [
      { condition: 'Payoff ≥ 2.0R', label: 'BREAKEVEN SHIFT', color: 'green', desc: 'Scale out 33-50% and raise stop-loss to Breakeven (+0.2% cost buffer).' },
      { condition: 'Payoff ≥ 3.0R', label: 'ACTIVATE CHANDELIER TRAIL', color: 'blue', desc: 'Trail stop dynamically below Highest High - 3.0x ATR to capture runner.' },
      { condition: 'Price < Trailing Stop', label: 'STRUCTURAL EXIT', color: 'red', desc: 'Exit position gracefully without emotional attachment.' },
    ],
    explanation: 'A systematic trade lifecycle and position management framework that locks in risk-free status at 2R and protects multibagger runners using volatility-adjusted Chandelier ATR and market structure trailing stops.',
    institutionalGuide: 'Never exit a winning multibagger on a fixed price target. Scale out 33-50% at 2R to eliminate account risk, then let the market take you out when the structural trend ends.',
    variables: [
      { name: '2R Breakeven Pivot', desc: 'When profit reaches 2x initial risk, lock partial gains and eliminate risk.' },
      { name: 'Structure Higher Low (HL)', desc: 'Trails stop behind verified structural support levels created by price swings.' },
      { name: 'Chandelier ATR (3.0x ATR)', desc: 'Gives the asset sufficient volatility buffer while preventing major profit givebacks.' },
    ],
  },
}

export const useInspectorStore = create((set) => ({
  isOpen: false,
  activeMetric: null,
  contextData: null,

  openInspector: (metricKeyOrConfig, contextData = null) => {
    if (typeof metricKeyOrConfig === 'string') {
      const predefined = METRIC_ENCYCLOPEDIA[metricKeyOrConfig] || {
        title: metricKeyOrConfig.replace(/_/g, ' ').toUpperCase(),
        category: 'Market Metric',
        explanation: 'Institutional indicator used for financial and quantitative analysis.',
        institutionalGuide: 'Analyze in confluence with price action and risk parameters.',
      }
      set({
        isOpen: true,
        activeMetric: { key: metricKeyOrConfig, ...predefined },
        contextData,
      })
    } else {
      set({
        isOpen: true,
        activeMetric: metricKeyOrConfig,
        contextData,
      })
    }
  },

  closeInspector: () => set({ isOpen: false, activeMetric: null, contextData: null }),
}))
