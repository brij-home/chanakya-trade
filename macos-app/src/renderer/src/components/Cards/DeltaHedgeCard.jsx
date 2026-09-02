import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

function deltaStatus(gap) {
  const abs = Math.abs(gap)
  if (abs <= 0.08) return { label: 'DELTA NEUTRAL', color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/15 dark:bg-emerald-500/10', border: 'border-emerald-500/40 dark:border-emerald-500/30', icon: '⚖️' }
  if (gap > 0.08) return { label: 'LONG DELTA (BULL BIAS)', color: 'text-cyan-600 dark:text-cyan-400', bg: 'bg-cyan-500/15 dark:bg-cyan-500/10', border: 'border-cyan-500/40 dark:border-cyan-500/30', icon: '📈' }
  return { label: 'SHORT DELTA (BEAR BIAS)', color: 'text-rose-600 dark:text-rose-400', bg: 'bg-rose-500/15 dark:bg-rose-500/10', border: 'border-rose-500/40 dark:border-rose-500/30', icon: '📉' }
}

export default function DeltaHedgeCard({ data, onOpenOrderTicket }) {
  const d = data?.data ?? data ?? {}
  const demo = d.demo ?? false
  const sendDraft = useChatStore((s) => s.sendDraft)
  
  const [posMultiplier, setPosMultiplier] = useState(1) // 1, 2, 5, 10 lots
  const [hedgeRatio, setHedgeRatio] = useState(1.0) // 50%, 75%, 100%
  const [activeRecipeTab, setActiveRecipeTab] = useState('FUTURES') // FUTURES vs OPTIONS vs COLLAR
  const [activeExplainerTab, setActiveExplainerTab] = useState('WHY') // WHY vs WHEN vs HOW

  const hasVerifiedInputs = !demo
    && Boolean(d.underlying || d.symbol)
    && (d.spot_price ?? d.spot) != null
    && d.net_delta != null
    && d.target_delta != null
    && d.lot_size != null

  if (!hasVerifiedInputs) {
    return (
      <div className="bg-panel border border-border/90 rounded-2xl p-5 max-w-2xl w-full space-y-2 shadow-xl font-ui text-text">
        <h3 className="text-sm font-bold tracking-wide font-mono uppercase">Delta Hedging &amp; Risk Control</h3>
        <p className="text-xs text-muted">Live position delta, verified spot, target delta, and contract lot size are required before a hedge can be calculated. No hedge has been staged.</p>
      </div>
    )
  }

  const underlying = (d.underlying || d.symbol).toUpperCase().replace('NSE:', '').replace('NFO:', '')
  const spotPrice = Number(d.spot_price ?? d.spot)
  
  const lotSize = Number(d.lot_size)

  const baseUnitDelta = Number(d.net_delta)
  const totalUnitDelta = baseUnitDelta * posMultiplier
  const currentDeltaQty = totalUnitDelta * lotSize
  const targetDeltaQty = Number(d.target_delta) * lotSize
  
  const rawGapQty = currentDeltaQty - targetDeltaQty
  const gapQty = rawGapQty * hedgeRatio
  const gapUnit = gapQty / lotSize
  const status = deltaStatus(totalUnitDelta)

  // Cash sensitivity: ₹ gain/loss for a 1% move in underlying
  const pointMove1Pct = spotPrice * 0.01
  const cashSensitivity1Pct = Math.round(currentDeltaQty * pointMove1Pct)

  // Calculate required hedge quantity
  const hedgeSide = gapQty > 0 ? 'SELL' : 'BUY'
  const futureLots = Math.max(1, Math.round(Math.abs(gapQty) / lotSize))
  const futureQty = futureLots * lotSize
  const optionStrike = gapQty > 0
    ? Math.floor(spotPrice / 50) * 50 - 50 // OTM Put for Long Delta hedge
    : Math.ceil(spotPrice / 50) * 50 + 50  // OTM Call for Short Delta hedge
  const optionType = gapQty > 0 ? 'PE' : 'CE'
  const optionLots = Math.max(1, Math.round(futureLots * 1.5))
  const optionQty = optionLots * lotSize

  // Pre-calculated recipes
  const recipes = [
    {
      id: 'FUTURES',
      title: 'Direct Futures Lock',
      badge: 'Exact & Zero Theta Bleed',
      action: hedgeSide,
      instrument: `${underlying} FUT`,
      lots: futureLots,
      quantity: futureQty,
      deltaImpact: `${gapQty > 0 ? '-' : '+'}${(futureLots * lotSize).toFixed(0)} shares`,
      estMargin: Math.round(futureLots * lotSize * spotPrice * 0.11),
      desc: `Instantly offsets ${Math.abs(gapQty).toFixed(0)} delta shares with 0 time-decay (theta) risk.`,
      icon: '⚡',
    },
    {
      id: 'OPTIONS',
      title: 'Asymmetric Option Shield',
      badge: 'Defined-Risk Tail Hedge',
      action: 'BUY',
      instrument: `${underlying} ${optionStrike} ${optionType}`,
      lots: optionLots,
      quantity: optionQty,
      deltaImpact: `${gapQty > 0 ? '-' : '+'}${(optionLots * lotSize * 0.5).toFixed(0)} shares`,
      estMargin: Math.round(optionQty * (spotPrice * 0.008)),
      desc: `Protects downside crash risk while preserving upside tail profit with capped maximum loss.`,
      icon: '🛡️',
    },
    {
      id: 'COLLAR',
      title: 'Zero-Cost Delta Collar',
      badge: 'Financed Premium Spread',
      action: 'SPREAD',
      instrument: `BUY ${optionStrike} ${optionType} + SELL ${optionStrike + (gapQty > 0 ? 300 : -300)} ${gapQty > 0 ? 'CE' : 'PE'}`,
      lots: futureLots,
      quantity: futureQty,
      deltaImpact: `${gapQty > 0 ? '-' : '+'}${(futureLots * lotSize * 0.85).toFixed(0)} shares`,
      estMargin: Math.round(futureQty * (spotPrice * 0.002)),
      desc: `Low-cost delta hedge using a funded OTM credit spread.`,
      icon: '🎯',
    },
  ]

  const activeRecipe = recipes.find((r) => r.id === activeRecipeTab) || recipes[0]

  // Visual meter (-1.0 to +1.0 normalized)
  const clampedDelta = Math.max(-1.0, Math.min(1.0, totalUnitDelta))
  const meterPercentage = ((clampedDelta + 1.0) / 2.0) * 100

  // Dynamic Why, When, How narratives
  const whyNarrative = d.why || `Your active ${posMultiplier}-lot position carries a net ${totalUnitDelta >= 0 ? 'Long' : 'Short'} Delta of ${totalUnitDelta >= 0 ? '+' : ''}${totalUnitDelta.toFixed(2)} (${currentDeltaQty >= 0 ? '+' : ''}${currentDeltaQty.toFixed(0)} delta shares). For every 1% move (~₹${pointMove1Pct.toFixed(0)} pts) in ${underlying}, your book experiences an immediate ₹${Math.abs(cashSensitivity1Pct).toLocaleString('en-IN')} directional P&L swing. Hedging isolates your pure Theta time-decay edge from directional whipsaws.`
  const whenNarrative = d.when || `1. Spot Drift: Rebalance when ${underlying} moves > ±0.75% (±${Math.round(spotPrice * 0.0075)} pts) from current spot ₹${spotPrice.toLocaleString('en-IN')}.\n2. Delta Tolerance: Rebalance when Net Delta drifts beyond ±0.15 from your target.\n3. End-of-Day Window: Execute at 03:15 PM IST to neutralize overnight gap risk before market close.`
  const howNarrative = d.how || `Route a LIMIT order to ${activeRecipe.action} ${activeRecipe.lots} Lot${activeRecipe.lots > 1 ? 's' : ''} (${activeRecipe.quantity} Qty) of ${activeRecipe.instrument} at ₹${spotPrice.toLocaleString('en-IN')} (Est. Margin: ₹${activeRecipe.estMargin.toLocaleString('en-IN')}). Place a protective invalidation stop ±${Math.round(spotPrice * 0.005)} pts away.`

  const handleStageOrder = (recipe) => {
    if (onOpenOrderTicket) {
      onOpenOrderTicket({
        symbol: recipe.instrument,
        side: recipe.action === 'SPREAD' ? 'BUY' : recipe.action,
        quantity: recipe.quantity,
        price: spotPrice,
        orderType: 'MARKET',
        segment: 'OPTIONS',
      })
    } else {
      sendDraft(`execute delta hedge: ${recipe.action} ${recipe.lots} lots (${recipe.quantity} qty) of ${recipe.instrument}`)
    }
  }

  return (
    <div className="bg-panel border border-border/90 rounded-2xl p-4 sm:p-5 max-w-2xl w-full space-y-4 shadow-xl backdrop-blur-md font-ui text-text">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-emerald-400 text-lg">⚡</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold tracking-wide font-mono uppercase text-text">
                DELTA HEDGING &amp; RISK CONTROL
              </h3>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${status.bg} ${status.border} ${status.color} flex items-center gap-1`}>
                <span>{status.icon}</span> {status.label}
              </span>
            </div>
            <p className="text-[11px] text-muted font-ui">
              Institutional Greeks Sensitivity &amp; Realistic Delta-Neutral Execution
            </p>
          </div>
        </div>
        
        {/* Position Scale Selector */}
        <div className="flex items-center gap-1 bg-surface border border-border/70 p-0.5 rounded-lg text-[10px] font-mono">
          <span className="text-muted px-1.5">Scale:</span>
          {[
            { label: '1 Lot', val: 1 },
            { label: '2 Lots', val: 2 },
            { label: '5 Lots', val: 5 },
            { label: '10 Lots', val: 10 },
          ].map((s) => (
            <button
              key={s.val}
              onClick={() => setPosMultiplier(s.val)}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                posMultiplier === s.val ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Visual Delta-Neutral Balance Needle Meter */}
      <div className="bg-surface/80 dark:bg-surface/70 border border-border/60 rounded-xl p-3.5 space-y-2">
        <div className="flex items-center justify-between text-[11px] font-mono">
          <span className="text-rose-600 dark:text-rose-400 flex items-center gap-1">◀ Short Delta (-1.0)</span>
          <span className="text-emerald-700 dark:text-emerald-400 font-bold px-2 py-0.5 bg-emerald-500/15 dark:bg-emerald-500/10 rounded border border-emerald-500/30">
            Neutral Safe Zone (-0.08 to +0.08)
          </span>
          <span className="text-cyan-600 dark:text-cyan-400 flex items-center gap-1">Long Delta (+1.0) ▶</span>
        </div>

        {/* Meter Track with Safe Target Zone */}
        <div className="relative h-3 w-full bg-border/40 rounded-full overflow-hidden flex items-center">
          <div className="absolute left-[45%] right-[45%] top-0 bottom-0 bg-emerald-500/30 border-x border-emerald-400/50" />
          <div
            className="absolute top-0 bottom-0 w-3 -ml-1.5 bg-gradient-to-r from-amber to-amber-light rounded-full shadow-lg border border-black transition-all duration-500"
            style={{ left: `${meterPercentage}%` }}
          />
        </div>

        <div className="flex justify-between items-center text-[10px] text-muted font-mono pt-0.5">
          <span>Net Delta: <strong className={status.color}>{totalUnitDelta >= 0 ? '+' : ''}{totalUnitDelta.toFixed(2)} Δ ({currentDeltaQty >= 0 ? '+' : ''}{currentDeltaQty.toFixed(0)} shares)</strong></span>
          <span>Target: <strong>0.00</strong></span>
          <span>Hedge Required: <strong className="text-amber">{hedgeSide} {futureLots} Lot{futureLots > 1 ? 's' : ''} ({futureQty} Qty)</strong></span>
        </div>
      </div>

      {/* Metrics Row: Position Delta, Rupee Cash Sensitivity, Hedge Ratio */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="bg-surface/80 dark:bg-surface/60 border border-border/60 rounded-xl p-3">
          <span className="text-[10px] text-muted uppercase font-mono block">Net Position Delta</span>
          <p className={`text-base font-mono font-bold mt-0.5 ${status.color}`}>
            {totalUnitDelta >= 0 ? '+' : ''}{totalUnitDelta.toFixed(2)} Δ ({currentDeltaQty >= 0 ? '+' : ''}{currentDeltaQty.toFixed(0)} shares)
          </p>
          <span className="text-[10px] text-muted block mt-0.5">
            {lotSize} shares/lot × {posMultiplier} lot{posMultiplier > 1 ? 's' : ''}
          </span>
        </div>

        <div className="bg-surface/80 dark:bg-surface/60 border border-border/60 rounded-xl p-3">
          <span className="text-[10px] text-muted uppercase font-mono block">₹ Cash Sensitivity (1% Move)</span>
          <p className={`text-base font-mono font-bold mt-0.5 ${cashSensitivity1Pct >= 0 ? 'text-cyan-600 dark:text-cyan-400' : 'text-rose-600 dark:text-rose-400'}`}>
            {cashSensitivity1Pct >= 0 ? '+' : ''}₹{Math.abs(cashSensitivity1Pct).toLocaleString('en-IN')}
          </p>
          <span className="text-[10px] text-muted block mt-0.5">
            PnL swing per ₹{Math.round(pointMove1Pct)} pts spot move
          </span>
        </div>

        <div className="bg-surface/60 border border-border/60 rounded-xl p-3">
          <span className="text-[10px] text-muted uppercase font-mono block">Hedge Ratio Target</span>
          <div className="flex items-center gap-1 mt-1">
            {[
              { label: '50%', val: 0.5 },
              { label: '75%', val: 0.75 },
              { label: '100%', val: 1.0 },
            ].map((r) => (
              <button
                key={r.label}
                onClick={() => setHedgeRatio(r.val)}
                className={`flex-1 py-0.5 rounded-md text-[10px] font-mono font-bold transition-all cursor-pointer ${
                  hedgeRatio === r.val
                    ? 'bg-amber text-black'
                    : 'bg-panel border border-border/60 text-muted hover:text-text'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <span className="text-[10px] text-muted block mt-1">
            Residual: {(totalUnitDelta * (1 - hedgeRatio)).toFixed(2)} Δ
          </span>
        </div>
      </div>

      {/* Decision Cockpit: WHY, WHEN, HOW Tabs */}
      <div className="bg-surface/80 border border-border/80 rounded-xl p-3 space-y-2">
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <div className="flex items-center gap-1.5">
            <span className="text-amber text-sm font-bold">◆</span>
            <span className="text-xs font-bold font-mono uppercase text-text">
              EXECUTIVE DECISION FRAMEWORK
            </span>
          </div>
          <div className="flex items-center gap-1 text-[10px] font-mono">
            {[
              { id: 'WHY', label: '🧠 Why Hedge?' },
              { id: 'WHEN', label: '⏱️ When to Act?' },
              { id: 'HOW', label: '🛠️ How to Execute?' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveExplainerTab(tab.id)}
                className={`px-2 py-1 rounded-md transition-all cursor-pointer font-bold ${
                  activeExplainerTab === tab.id
                    ? 'bg-amber/20 text-amber border border-amber/40'
                    : 'text-muted hover:text-text'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Content Narrative */}
        <div className="text-[11px] font-ui leading-relaxed text-text/90 bg-panel/70 p-2.5 rounded-lg border border-border/50">
          {activeExplainerTab === 'WHY' && (
            <div className="space-y-1">
              <p className="font-semibold text-cyan-400">Directional Monetary Risk:</p>
              <p>{whyNarrative}</p>
            </div>
          )}
          {activeExplainerTab === 'WHEN' && (
            <div className="space-y-1">
              <p className="font-semibold text-amber">Rebalance Trigger Conditions:</p>
              <pre className="font-mono text-[10px] text-muted whitespace-pre-wrap leading-tight">{whenNarrative}</pre>
            </div>
          )}
          {activeExplainerTab === 'HOW' && (
            <div className="space-y-1">
              <p className="font-semibold text-emerald-400">Order Routing &amp; Risk Guardrail:</p>
              <p>{howNarrative}</p>
            </div>
          )}
        </div>
      </div>

      {/* Actionable Hedging Recipes */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold font-mono uppercase tracking-wider text-muted flex items-center gap-1">
            <span>🎯</span> Recommended Hedging Recipes
          </span>
          <span className="text-[10px] text-muted font-mono">Realistic Indian Lot Sizing</span>
        </div>

        {/* Strategy Tab Buttons */}
        <div className="grid grid-cols-3 gap-1.5 p-1 bg-surface/80 rounded-xl border border-border/60">
          {recipes.map((r) => (
            <button
              key={r.id}
              onClick={() => setActiveRecipeTab(r.id)}
              className={`py-1.5 px-2 rounded-lg text-[11px] font-mono font-bold transition-all cursor-pointer flex items-center justify-center gap-1 ${
                activeRecipeTab === r.id
                  ? 'bg-amber text-black shadow-sm'
                  : 'text-muted hover:text-text hover:bg-panel'
              }`}
            >
              <span>{r.icon}</span>
              <span className="truncate">{r.title.split(' ')[0]}</span>
            </button>
          ))}
        </div>

        {/* Active Recipe Detail Card */}
        <div className="bg-surface/80 border border-border/80 rounded-xl p-3.5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base">{activeRecipe.icon}</span>
                <h4 className="text-xs font-bold font-mono text-text">{activeRecipe.title}</h4>
                <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber/10 text-amber border border-amber/30">
                  {activeRecipe.badge}
                </span>
              </div>
              <p className="text-[11px] text-muted font-ui mt-0.5">{activeRecipe.desc}</p>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-muted font-mono block">Est. Margin / Outlay</span>
              <span className="text-xs font-mono font-bold text-text">₹{activeRecipe.estMargin.toLocaleString('en-IN')}</span>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs font-mono">
            <div className="bg-panel p-2 rounded-lg border border-border/50">
              <span className="text-[9px] text-muted uppercase block">Action</span>
              <span className={`font-bold ${activeRecipe.action === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                {activeRecipe.action} {activeRecipe.lots} Lot{activeRecipe.lots > 1 ? 's' : ''}
              </span>
            </div>
            <div className="bg-panel p-2 rounded-lg border border-border/50 col-span-1 truncate">
              <span className="text-[9px] text-muted uppercase block">Instrument</span>
              <span className="font-bold text-text truncate block">{activeRecipe.instrument}</span>
            </div>
            <div className="bg-panel p-2 rounded-lg border border-border/50">
              <span className="text-[9px] text-muted uppercase block">Delta Impact</span>
              <span className="font-bold text-emerald-400">{activeRecipe.deltaImpact}</span>
            </div>
          </div>

          {/* 1-Click Execution Button */}
          <button
            onClick={() => handleStageOrder(activeRecipe)}
            className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-emerald-500 via-teal-500 to-emerald-600 hover:brightness-110 text-black font-bold text-xs font-mono uppercase tracking-wide transition-all shadow-md cursor-pointer flex items-center justify-center gap-2"
          >
            <span>⚡</span> Stage Order: {activeRecipe.action} {activeRecipe.lots} Lot{activeRecipe.lots > 1 ? 's' : ''} ({activeRecipe.quantity} Qty {underlying})
          </button>
        </div>
      </div>

      {/* Follow-up Quick Action Chips */}
      <div className="flex flex-wrap gap-1.5 pt-1 border-t border-border/50">
        {[
          { label: '📊 Gamma Flip Analysis', q: `What is the full Gamma Exposure (GEX) profile and flip level for ${underlying}?` },
          { label: '🛡️ 0DTE Tail Risk Shield', q: `What is the most cost-effective 0DTE delta hedge for ${underlying} given current IV skew?` },
          { label: '📈 Volatility Skew Trade', q: `How does the volatility smile look for ${underlying}, and how do I harvest put skew?` },
        ].map((chip) => (
          <button
            key={chip.label}
            onClick={() => sendDraft(chip.q)}
            className="text-[10px] font-ui px-2.5 py-1 rounded-full border border-border/70 text-muted hover:text-text hover:border-amber/50 hover:bg-amber/5 transition-all cursor-pointer"
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  )
}
