/**
 * metricEncyclopedia.js
 * ─────────────────────
 * Static metadata, formulas, thresholds, and institutional guides for quant metrics.
 * Extracted from inspectorStore to minimize reactive store size and bundle overhead.
 */

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

  // ── CENTURY COMPOUNDER & FUNDAMENTAL MULTIBAGGER METRICS ───────────────────
  century_score: {
    title: 'Century Compounder Score (0–100)',
    category: 'Multibagger Discovery',
    tagColor: 'green',
    formula: 'Score = PAT Growth(35%) + P/E Re-rating(25%) + ROCE(20%) + Forensic Hygiene(20%)',
    thresholds: [
      { condition: 'Score ≥ 75', label: 'ELITE 100x CANDIDATE', color: 'green', desc: 'Highest mathematical alignment of profit compounding and valuation expansion.' },
      { condition: '60 ≤ Score < 75', label: 'EMERGING COMPOUNDER', color: 'blue', desc: 'Solid fundamental tailwinds; accumulate on pullbacks into Fair Value Zone.' },
      { condition: 'Score < 60', label: 'SPECULATIVE / WATCH', color: 'amber', desc: 'Lacks full institutional criteria or faces earnings volatility.' },
    ],
    explanation: 'A quantitative score measuring a company’s probability of becoming a true 10x to 100x multibagger over a 5 to 10 year horizon, based on historical patterns of top Indian market winners.',
    institutionalGuide: 'Focus capital on setups with Score ≥ 70 that are still trading near their Fair Value Anchor. High scores identify companies with strong earnings and solid balance sheets before the broader market bids them up.',
  },

  twin_engines: {
    title: 'Twin Engines of Multibaggers (PAT Growth × P/E Re-rating)',
    category: 'Multibagger Framework',
    tagColor: 'green',
    formula: 'Total Return = (1 + PAT Growth Rate)^N × (Exit P/E / Entry P/E)',
    thresholds: [
      { condition: 'Both Engines Active', label: 'PARABOLIC COMPOUNDER', color: 'green', desc: 'PAT doubling + P/E doubling turns ₹100 into ₹400 (4x) in a fraction of normal time.' },
      { condition: 'Single Engine Only', label: 'STANDARD COMPOUNDER', color: 'blue', desc: 'Growing only through earnings or only through multiple re-rating.' },
    ],
    explanation: 'The definitive mathematical law of stock market returns: Stock Price = Earnings (EPS) × Valuation Multiple (P/E). True 100x multibaggers happen when BOTH engines fire together — net profits grow 10x, and the market re-rates the P/E multiple from 15x to 45x (a 3x jump), multiplying your investment up to 30x to 100x.',
    institutionalGuide: 'Never rely on valuation re-rating alone (which is speculative). Look for companies where Engine 1 (PAT CAGR ≥ 25%) is rock-solid, so even if P/E stays flat, your capital doubles every 3 years.',
  },

  pat_expansion: {
    title: 'Engine 1: Profit After Tax (PAT) CAGR & Expansion',
    category: 'Fundamental Growth',
    tagColor: 'green',
    formula: 'PAT CAGR = (Net Profit_End / Net Profit_Start)^(1/N) - 1',
    thresholds: [
      { condition: 'CAGR ≥ 35%', label: 'HYPER-GROWTH', color: 'green', desc: 'Profits doubling every 2 to 2.5 years. Strong institutional magnet.' },
      { condition: '20% ≤ CAGR < 35%', label: 'STRONG EXPANSION', color: 'blue', desc: 'High-quality compounding pace; beats 90% of listed peers.' },
      { condition: 'CAGR < 15%', label: 'SUB-OPTIMAL', color: 'amber', desc: 'Insufficient fundamental velocity to power a sustained multibagger rally.' },
    ],
    explanation: 'Measures how fast actual net bottom-line earnings are growing year over year. Earnings growth is the fundamental engine that pulls the stock price upward over time.',
    institutionalGuide: 'Target businesses with PAT CAGR > 25% driven by real sales volume and margin expansion, not one-off asset sales. Check that Operating Cash Flow matches Net Profit.',
  },

  pe_rerating: {
    title: 'Engine 2: Valuation Multiple (P/E) Re-rating',
    category: 'Valuation Dynamic',
    tagColor: 'purple',
    formula: 'P/E = Market Price / EPS | Re-rating Room = Target Multiple / Current P/E',
    thresholds: [
      { condition: 'P/E < 20 & High ROCE', label: 'PRIME RE-RATING CANDIDATE', color: 'green', desc: 'Inexpensive entry multiple with massive room for institutional multiple expansion.' },
      { condition: '20 ≤ P/E ≤ 40', label: 'FAIR MULTIPLE', color: 'blue', desc: 'Priced reasonably for current high growth rate.' },
      { condition: 'P/E > 75', label: 'PRICED TO PERFECTION', color: 'red', desc: 'High multiple contraction risk if quarterly earnings miss estimates.' },
    ],
    explanation: 'Occurs when the market upgrades its perception of a company — for instance, from a cyclical commodity player (12x P/E) to a high-margin specialized manufacturer (35x P/E). Every ₹1 of profit is suddenly valued nearly 3x higher.',
    institutionalGuide: 'The biggest fortunes are made buying quality microcaps at 15–20x P/E before mutual funds discover them and bid them up to 50x P/E. Avoid buying when P/E is already overextended.',
  },

  ten_year_multiple: {
    title: '10-Year Projected Wealth Multiplier',
    category: 'Long-Term Compounding',
    tagColor: 'green',
    formula: '10Y Capital Multiple = Projected Future Market Cap / Current Market Cap',
    thresholds: [
      { condition: 'Multiple ≥ 100x', label: 'CENTURY COMPOUNDER', color: 'green', desc: 'Small/microcap base (₹200Cr–₹2,000Cr) with a vast addressable market.' },
      { condition: '10x–25x', label: 'CORE WEALTH CREATOR', color: 'blue', desc: 'Midcap emerging leader scaling into mega-cap status.' },
    ],
    explanation: 'An actuarial estimate of total capital multiplication potential over 10 years, calculated by stress-testing terminal addressable market size against current market capitalization.',
    institutionalGuide: '100x returns require starting small. A company with ₹500 Cr market cap can become ₹50,000 Cr in 10 years, but a ₹10,00,000 Cr giant cannot easily multiply 100x.',
  },

  roce: {
    title: 'Return on Capital Employed (ROCE)',
    category: 'Capital Efficiency',
    tagColor: 'green',
    formula: 'ROCE = EBIT / (Total Assets - Current Liabilities)',
    thresholds: [
      { condition: 'ROCE > 25%', label: 'EXCEPTIONAL ALLOCATOR', color: 'green', desc: 'Generates enormous cash returns on every rupee invested.' },
      { condition: '15% ≤ ROCE ≤ 25%', label: 'SOLID COMPOUNDER', color: 'blue', desc: 'Healthy business capable of self-funded expansion.' },
      { condition: 'ROCE < 12%', label: 'CAPITAL DESTROYER', color: 'red', desc: 'Earns less than the corporate cost of capital. Avoid.' },
    ],
    explanation: 'Shows how efficiently a company turns invested capital into operating profit. If ROCE is 30%, the company earns ₹30 profit for every ₹100 of capital deployed in the business.',
    institutionalGuide: 'Great multibaggers must have ROCE > 20%. High ROCE lets a company grow without diluting equity or taking heavy debt.',
  },

  operating_leverage: {
    title: 'Operating Leverage & Margin Expansion',
    category: 'Fundamental Velocity',
    tagColor: 'blue',
    formula: 'DOL = % Change in EBIT / % Change in Sales',
    thresholds: [
      { condition: 'DOL > 2.0x', label: 'HIGH LEVERAGE BENEFIT', color: 'green', desc: 'Small sales increases produce explosive bottom-line profit jumps.' },
    ],
    explanation: 'When a business has fixed costs (factories, software, machinery) and sales increase, each additional rupee of sales flows straight to the bottom line as pure profit.',
    institutionalGuide: 'Companies with high operating leverage experience explosive profit jumps when factory capacity utilization crosses 75–80%, sparking massive re-rating rallies.',
  },

  // ── ENTRY TIMING, ANTI-FOMO & RISK GUARDRAILS ─────────────────────────────
  anti_fomo: {
    title: 'Anti-FOMO Guardrail & Discipline Engine',
    category: 'Execution & Psychology',
    tagColor: 'amber',
    thresholds: [
      { condition: 'ACCUMULATE_NOW', label: 'BUY ZONE', color: 'green', desc: 'Price is within +3% of Fair Value Anchor. Low-risk entry.' },
      { condition: 'WAIT_FOR_DIP', label: 'PULLBACK PATIENCE', color: 'amber', desc: 'Price moved 3–8% past pivot. Place limit buy order on retest.' },
      { condition: 'OVEREXTENDED_AVOID', label: 'NO CHASE ZONE', color: 'red', desc: 'Price surged >8% past pivot. High probability of sharp shakeout.' },
    ],
    explanation: 'An institutional psychological guardrail that stops traders from chasing green candles. Retail traders buy at the top of parabolic spikes and panic sell during normal pullbacks. Anti-FOMO enforces entries strictly near institutional cost bases.',
    institutionalGuide: 'If Anti-FOMO says "WAIT_FOR_DIP", do NOT hit the buy market button! Let the stock come to your price level. The best traders are patient snipers, not emotional chasers.',
  },

  fair_value_zone: {
    title: 'Fair Value Anchor & Accumulation Zone',
    category: 'Pricing & Entry',
    tagColor: 'blue',
    formula: 'Fair Value Anchor = Volume POC + Structural Support Pivot',
    thresholds: [
      { condition: 'At or near Anchor', label: 'OPTIMAL ENTRY', color: 'green', desc: 'Minimal risk; stop-loss is tight and clearly defined.' },
      { condition: '> 5% above Anchor', label: 'EXTENDED', color: 'amber', desc: 'Reward-to-risk ratio degrades significantly.' },
    ],
    explanation: 'The optimal price zone where institutional block buying and high-volume accumulation occurred. Buying here aligns your entry price with institutional smart money.',
    institutionalGuide: 'Accumulate positions when price tests or hovers within 2–3% of this anchor. Your invalidation stop-loss is placed just below this structural floor.',
  },

  no_chase_boundary: {
    title: 'No-Chase Boundary (+5% Extension Rule)',
    category: 'Risk Management',
    tagColor: 'red',
    formula: 'No-Chase Ceiling = Breakout Pivot Price × 1.05 (+5.0%)',
    thresholds: [
      { condition: 'Price ≤ Boundary', label: 'VALID ENTRY', color: 'green', desc: 'Risk/reward remains asymmetric and favorable.' },
      { condition: 'Price > Boundary', label: 'CHASE VIOLATION', color: 'red', desc: 'Statistically poor entry; wait for 10-day or 20-day EMA pullback.' },
    ],
    explanation: 'The absolute maximum price you are mathematically permitted to pay for a breakout. When a stock rallies more than 5% past its base, the risk/reward ratio flips negatively against you.',
    institutionalGuide: 'Buying beyond the No-Chase Boundary exposes you to normal 4–6% institutional pullbacks, triggering premature stop-outs. If missed, wait for the first 10-day or 20-day EMA test.',
  },

  pullback_limit: {
    title: 'Pullback Invalidation Floor',
    category: 'Risk Management',
    tagColor: 'red',
    formula: 'Pullback Floor = Breakout Base Support Level - (0.5 · ATR_14)',
    thresholds: [
      { condition: 'Holds above Floor', label: 'HEALTHY RETEST', color: 'green', desc: 'Normal institutional back-test of support.' },
      { condition: 'Breaks below Floor', label: 'FAILED BREAKOUT', color: 'red', desc: 'Setup is broken; exit immediately to preserve capital.' },
    ],
    explanation: 'The lowest price a pullback can reach before the breakout is deemed broken or failed.',
    institutionalGuide: 'If price drops below this level, do not "buy the dip" blindly — the setup structure has failed. Respect the invalidation floor without hope or hesitation.',
  },

  risk_reward_ratio: {
    title: 'Risk-to-Reward Payoff Ratio (R:R)',
    category: 'Risk Architecture',
    tagColor: 'amber',
    formula: 'R:R = (Target Price - Entry Price) / (Entry Price - Stop Loss Price)',
    thresholds: [
      { condition: 'R:R ≥ 1:3.0', label: 'INSTITUTIONAL SETUP', color: 'green', desc: 'Positive mathematical expectancy; sustainable compounding.' },
      { condition: '1:2.0 ≤ R:R < 1:3.0', label: 'ACCEPTABLE SWING', color: 'blue', desc: 'Valid for high-win-rate setups.' },
      { condition: 'R:R < 1:2.0', label: 'POOR RISK ASYMMETRY', color: 'red', desc: 'Unfavorable payoff; do not take this trade.' },
    ],
    explanation: 'Calculates how many rupees of potential gain you stand to make for every ₹1 of capital you risk losing if your stop-loss is triggered.',
    institutionalGuide: 'Professional traders do not predict the future; they play positive expectancy games. With a 1:3.0 R:R, you can be wrong 60% of the time and still make superior returns.',
  },

  rvol: {
    title: 'Relative Volume 20-Day (RVOL)',
    category: 'Volume Footprint',
    tagColor: 'blue',
    formula: 'RVOL = Current Volume / 20-Day Simple Moving Average Volume',
    thresholds: [
      { condition: 'RVOL ≥ 2.0x', label: 'INSTITUTIONAL FOOTPRINT', color: 'green', desc: 'Big mutual funds, FIIs, or DIIs are actively participating.' },
      { condition: '1.0x ≤ RVOL < 2.0x', label: 'NORMAL VOLUME', color: 'blue', desc: 'Standard market liquidity; no extraordinary institutional participation.' },
      { condition: 'RVOL < 0.6x', label: 'VOLUME DRY-UP', color: 'amber', desc: 'Low interest or lack of selling pressure on consolidation pullbacks.' },
    ],
    explanation: 'Volume is the footprint of smart money. Relative Volume reveals whether today\'s price move has real institutional firepower behind it or is just meaningless retail noise.',
    institutionalGuide: 'A breakout on RVOL < 1.5x has a high probability of being a fakeout. Demand RVOL ≥ 2.0x on breakouts, and low RVOL (<0.7x) on pullbacks.',
  },

  timing_state: {
    title: 'Inflection Timing State & Readiness',
    category: 'Execution Timing',
    tagColor: 'amber',
    thresholds: [
      { condition: 'TRIGGER_NOW', label: 'ACTIVE BREAKOUT', color: 'green', desc: 'Breakout or pivot trigger firing right now with high volume. Immediate execution readiness.' },
      { condition: 'COILING_IMMINENT', label: 'SQUEEZE / COILING', color: 'amber', desc: 'Volatility has contracted tightly; setup is 1–3 sessions away from explosive trigger. Prepare alerts.' },
      { condition: 'PULLBACK_RETEST', label: 'SUPPORT RETEST', color: 'blue', desc: 'Breakout occurred; price is currently retesting broken resistance as new support. Low-risk entry.' },
    ],
    explanation: 'Classifies the precise phase of the trade setup so traders do not enter too early (dead money waiting for weeks) or too late (chasing after the move has finished).',
    institutionalGuide: 'Enter on TRIGGER_NOW for fast momentum, or on PULLBACK_RETEST for lowest-risk entry. On COILING_IMMINENT, set automated alerts and wait for confirmation.',
  },

  // ── TECHNICAL ARCHETYPES & RADAR SETUPS ──────────────────────────────────
  vcp_pivot: {
    title: 'Volatility Contraction Pattern (VCP) Pivot',
    category: 'Chart Pattern & Setup',
    tagColor: 'purple',
    formula: 'Contraction Sequence: Wave 1 (-20%) -> Wave 2 (-10%) -> Wave 3 (-3%) with Volume Drying',
    thresholds: [
      { condition: 'Final Contraction < 4%', label: 'READY TO EXPLODE', color: 'green', desc: 'Sellers completely exhausted; minimal overhead supply.' },
    ],
    explanation: 'Mastered by U.S. Investing Champion Mark Minervini. As a stock consolidates, each pullback gets smaller and tighter while volume drops to dry levels. This proves sellers have vanished, leaving only buyers to push price higher.',
    institutionalGuide: 'Enter as price breaks out above the high of the final tight consolidation (the pivot). Set stop-loss directly below the low of that final tight contraction (typically only 2–4% risk).',
  },

  ttm_squeeze: {
    title: 'TTM Squeeze Momentum Explosion',
    category: 'Volatility Compression',
    tagColor: 'amber',
    formula: 'Squeeze ON: Bollinger Bands (20, 2.0) inside Keltner Channels (20, 1.5)',
    thresholds: [
      { condition: 'Squeeze Active (Red Dots)', label: 'COILING / COMPRESSION', color: 'amber', desc: 'Volatility is storing energy like a compressed spring.' },
      { condition: 'Squeeze Firing (Green Dot)', label: 'VOLATILITY EXPANSION', color: 'green', desc: 'Explosive directional trend has unleashed. High momentum.' },
    ],
    explanation: 'Created by John Carter. Markets alternate between quiet consolidation and violent trending. When Bollinger Bands contract inside Keltner Channels, energy builds up. When it releases, large moves follow.',
    institutionalGuide: 'Do not anticipate the direction prematurely. Wait for the first colored momentum histogram bar to confirm direction, then ride the expansion until momentum bars begin fading.',
  },

  smc_spring_sweep: {
    title: 'SMC Liquidity Sweep & Wyckoff Spring',
    category: 'Smart Money Action',
    tagColor: 'green',
    formula: 'Sweep Condition: Low_t < Support_Level AND Close_t > Support_Level on High RVOL',
    thresholds: [
      { condition: 'Confirmed Sweep', label: 'BEAR TRAP / SPRING', color: 'green', desc: 'False breakdown immediately reclaimed; trapped shorts fuel rally.' },
    ],
    explanation: 'Institutions need massive liquidity to fill huge buy orders. They deliberately push price below an obvious support line to trigger retail stop-loss orders. Once all retail sell orders are absorbed, institutions push price instantly back above support.',
    institutionalGuide: 'Never short a breakdown immediately! If price swiftly reclaims the support level within 1–2 candles on high volume, buy immediately with a stop below the sweep low. The trapped sellers will fuel a rocket rally.',
  },

  rrg_leaders: {
    title: 'Sector Relative Rotation Graph (RRG) Leaders',
    category: 'Sector Momentum',
    tagColor: 'purple',
    formula: 'RS-Ratio > 100 & RS-Momentum > 100 vs NIFTY 50 Benchmark',
    thresholds: [
      { condition: 'Leading Quadrant', label: 'INSTITUTIONAL TAILWIND', color: 'green', desc: 'Sector is outperforming the benchmark and accelerating.' },
      { condition: 'Lagging Quadrant', label: 'SECTOR HEADWIND', color: 'red', desc: 'Sector is underperforming; avoid long setups.' },
    ],
    explanation: 'Visualizes the relative strength trend and momentum of Indian market sectors compared to Nifty 50. Leading sectors attract institutional inflows that carry individual stocks higher.',
    institutionalGuide: 'Over 60% of a stock’s price move is driven by its sector. Trading stocks in "Leading" or "Improving" sectors puts institutional wind at your back.',
  },

  // ── OPTIONS DESK & DERIVATIVES ANALYTICS ──────────────────────────────────
  max_pain: {
    title: 'Options Expiry Max Pain Magnet Strike',
    category: 'Derivatives & Options',
    tagColor: 'purple',
    formula: 'Max Pain Strike = Strike Price minimizing Total Dollar Value of All In-The-Money Options',
    thresholds: [
      { condition: 'Price near Max Pain on Expiry', label: 'PINNING EFFECT', color: 'amber', desc: 'High probability of sideways pin near strike.' },
    ],
    explanation: 'Option sellers (big institutions and market makers) write the vast majority of options. At expiration, the market tends to gravitate towards the strike price where the highest percentage of call and put options expire completely worthless.',
    institutionalGuide: 'On weekly and monthly expiry days (Thursdays), spot prices often get pinned near the Max Pain strike between 2:00 PM and 3:30 PM IST. Avoid buying OTM options close to expiry — theta decay and the Max Pain magnet will wipe them out.',
  },

  pcr: {
    title: 'Put-Call Ratio (PCR Sentiment & OI)',
    category: 'Derivatives Sentiment',
    tagColor: 'blue',
    formula: 'PCR = Total Open Interest of Puts / Total Open Interest of Calls',
    thresholds: [
      { condition: 'PCR > 1.30', label: 'OVERSOLD / PANIC', color: 'green', desc: 'Excessive put buying or heavy put writing. Strong contrarian bounce expected.' },
      { condition: '0.80 ≤ PCR ≤ 1.20', label: 'NEUTRAL EQUILIBRIUM', color: 'blue', desc: 'Balanced option market expectations.' },
      { condition: 'PCR < 0.65', label: 'OVERBOUGHT / EUPHORIA', color: 'red', desc: 'Complacent market; excessive call buying. Vulnerable to sharp selloff.' },
    ],
    explanation: 'Compares total outstanding Put contracts to Call contracts. When retail traders panic, they buy expensive puts (driving PCR high); when euphoric, they flood into calls (driving PCR low).',
    institutionalGuide: 'Use PCR as a contrarian indicator at market extremes. When PCR > 1.40 and price hits major support, look for sharp short-covering rallies.',
  },

  gex: {
    title: 'Dealer Net Gamma Exposure (GEX)',
    category: 'Market Microstructure',
    tagColor: 'amber',
    formula: 'Net GEX = Σ (Dealer Call Gamma) - Σ (Dealer Put Gamma)',
    thresholds: [
      { condition: 'Positive Gamma (+GEX)', label: 'VOLATILITY ABSORBER', color: 'green', desc: 'Market makers buy dips and sell rips. Dampens volatility; rangebound.' },
      { condition: 'Negative Gamma (-GEX)', label: 'VOLATILITY AMPLIFIER', color: 'red', desc: 'Market makers sell into declines and buy into rallies. Fast violent trends.' },
    ],
    explanation: 'Dealers and market makers who write options must continuously hedge their risk in the underlying stock or index. In Long Gamma (+GEX), their hedging stabilizes price swings. In Short Gamma (-GEX), their hedging accelerates moves like gasoline on fire.',
    institutionalGuide: 'When GEX is heavily negative, do NOT trade mean-reversion or iron condors! Ride breakouts with long options or tight trailing stops because market moves will be explosive.',
  },

  iv_smile: {
    title: 'Implied Volatility (IV) Smile & Skew',
    category: 'Options Pricing',
    tagColor: 'purple',
    formula: 'IV Skew = IV(OTM Puts) - IV(OTM Calls)',
    thresholds: [
      { condition: 'Put Skew High', label: 'CRASH HEDGING', color: 'amber', desc: 'Institutions paying premium for downside protection.' },
      { condition: 'Call Skew High', label: 'SHORT SQUEEZE DEMAND', color: 'green', desc: 'Aggressive upside call buying.' },
    ],
    explanation: 'Implied Volatility is never flat across strikes. OTM Puts usually trade at higher IV than OTM Calls because investors fear sudden market crashes more than upside surprises.',
    institutionalGuide: 'If IV on OTM Calls suddenly spikes higher than Puts (Call Skew), smart money is aggressively bidding for upside lottery tickets, signaling an imminent short squeeze.',
  },

  // ── QUANTITATIVE PERFORMANCE & BACKTEST METRICS ──────────────────────────
  sharpe_ratio: {
    title: 'Sharpe Ratio (Risk-Adjusted Return)',
    category: 'Quantitative Performance',
    tagColor: 'green',
    formula: 'Sharpe = (Annualized Return - Risk-Free Rate) / Annualized Volatility',
    thresholds: [
      { condition: 'Sharpe ≥ 2.0', label: 'ELITE QUANT ALPHA', color: 'green', desc: 'Exceptional consistency; very low volatility drag.' },
      { condition: '1.2 ≤ Sharpe < 2.0', label: 'INSTITUTIONAL GRADE', color: 'blue', desc: 'Solid risk-adjusted returns exceeding mutual fund benchmarks.' },
      { condition: 'Sharpe < 1.0', label: 'HIGH VOLATILITY DRAG', color: 'amber', desc: 'Returns may be volatile or lucky; drawdown risk is high.' },
    ],
    explanation: 'Measures how much profit a strategy generates relative to the volatility and stress you had to endure to get it.',
    institutionalGuide: 'Never judge a trading system by return alone. A 40% return with 35% volatility is dangerous, whereas a 28% return with 8% volatility (Sharpe > 2.5) compounds capital safely into massive fortunes.',
  },

  sortino_ratio: {
    title: 'Sortino Ratio (Downside Risk-Adjusted Return)',
    category: 'Quantitative Performance',
    tagColor: 'blue',
    formula: 'Sortino = (Annualized Return - Risk-Free Rate) / Downside Deviation',
    thresholds: [
      { condition: 'Sortino ≥ 2.5', label: 'EXCELLENT', color: 'green', desc: 'Minimal losing volatility; highly asymmetric upside.' },
    ],
    explanation: 'Similar to the Sharpe ratio, but it only penalizes downside / loss volatility. Unlike Sharpe, huge profitable winning streaks are not penalized as "risk".',
    institutionalGuide: 'For trend-following and momentum strategies, Sortino is more meaningful than Sharpe because explosive upward runs are pure profit, not risk.',
  },

  max_drawdown: {
    title: 'Maximum Capital Drawdown (MDD)',
    category: 'Risk & Capital Preservation',
    tagColor: 'red',
    formula: 'MDD = (Trough Value - Peak Value) / Peak Value',
    thresholds: [
      { condition: 'MDD < 12%', label: 'CONSERVATIVE / PRUDENT', color: 'green', desc: 'Safe drawdown profile; preserves trader psychology.' },
      { condition: '12% ≤ MDD ≤ 22%', label: 'MODERATE / ACCEPTABLE', color: 'amber', desc: 'Standard equity curve pullbacks for trend-following models.' },
      { condition: 'MDD > 30%', label: 'HIGH RUIN RISK', color: 'red', desc: 'Requires a +43% gain just to get back to breakeven.' },
    ],
    explanation: 'The largest historical percentage loss your trading account experienced from its all-time peak to its lowest point before recovering.',
    institutionalGuide: 'Drawdown determines whether a trader survives. A 50% loss requires a 100% gain just to break even! Always size positions so that max historical drawdown remains under your psychological tolerance.',
  },

  profit_factor: {
    title: 'Profit Factor (Gross Wins / Gross Losses)',
    category: 'Quantitative Expectancy',
    tagColor: 'green',
    formula: 'Profit Factor = Gross Winning Trades (₹) / Gross Losing Trades (₹)',
    thresholds: [
      { condition: 'PF ≥ 2.0', label: 'SUPERIOR SYSTEM', color: 'green', desc: 'Makes ₹2+ for every ₹1 lost. Highly robust.' },
      { condition: '1.5 ≤ PF < 2.0', label: 'HEALTHY EDGE', color: 'blue', desc: 'Strong sustainable edge over market commissions.' },
      { condition: 'PF < 1.2', label: 'MARGINAL EDGE', color: 'red', desc: 'Vulnerable to slippage and transaction friction.' },
    ],
    explanation: 'The ratio of all money made on winning trades divided by all money lost on losing trades.',
    institutionalGuide: 'Aim for systems with Profit Factor ≥ 1.75. If Profit Factor drops below 1.2, small changes in market regime or execution slippage will turn your profits into net losses.',
  },
}
