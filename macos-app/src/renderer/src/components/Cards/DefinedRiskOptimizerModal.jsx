import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'

/**
 * DefinedRiskOptimizerModal
 * ─────────────────────────
 * Evaluates, ranks, and visualizes 6 institutional defined-risk options structures:
 * Bull Call Spread, Bear Put Spread, Bull Put Credit Spread, Bear Call Credit Spread,
 * Iron Condor, and Iron Butterfly.
 */
export default function DefinedRiskOptimizerModal({
  isOpen,
  onClose,
  underlying = 'NIFTY',
  spot = 0,
  lotSize = 25,
  regime = 'NEUTRAL',
  onStageSpread,
  onSimulateStrategy,
}) {
  const { call } = useAPI()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selectedRegime, setSelectedRegime] = useState(regime || 'NEUTRAL')

  useEffect(() => {
    if (!isOpen) return

    let isMounted = true
    const fetchSpreads = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await call('/api/options/optimize_spreads', {
          underlying,
          spot: Number(spot) || 0,
          lot_size: Number(lotSize) || 25,
          regime: selectedRegime,
        })
        if (isMounted) {
          const payload = res?.data ?? res
          setData(payload)
        }
      } catch (err) {
        if (isMounted) {
          setError(err?.message || 'Failed to optimize defined-risk spreads')
        }
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    fetchSpreads()
    return () => {
      isMounted = false
    }
  }, [isOpen, underlying, spot, lotSize, selectedRegime, call])

  if (!isOpen) return null

  const strategies = data?.strategies || []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 dark:bg-black/75 backdrop-blur-sm p-3 sm:p-6 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="bg-panel border border-border rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/50 px-5 py-3.5 bg-elevated/40">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">⚡</span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold font-mono text-text">
                  Defined-Risk Options Spreads Optimizer
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber/15 text-amber border border-amber/30">
                  {underlying} · ₹{Number(spot).toLocaleString('en-IN')}
                </span>
              </div>
              <p className="text-[11px] text-muted font-ui">
                Institutional Risk-Capped Structures • Spreads &amp; Condors • Black-Scholes Greeks • Regime Calibrated
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted hover:text-text p-1 text-lg font-bold cursor-pointer transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Toolbar Filter */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-2.5 border-b border-border/40 bg-surface/50 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-muted font-ui">Market Regime:</span>
            {['BULLISH', 'BEARISH', 'NEUTRAL', 'RANGEBOUND', 'VOLATILE'].map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setSelectedRegime(r)}
                className={`px-2.5 py-1 rounded-md text-[11px] font-mono font-bold transition-all cursor-pointer ${
                  selectedRegime === r
                    ? 'bg-amber text-black shadow-xs'
                    : 'bg-elevated hover:bg-panel text-muted hover:text-text border border-border/60'
                }`}
              >
                {r}
              </button>
            ))}
          </div>

          <div className="text-[11px] font-mono text-muted tabular-nums">
            ATM Strike: <strong className="text-text">₹{data?.atm_strike || '—'}</strong> · Step: ₹{data?.strike_step || '—'} · Lot: {lotSize}
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading ? (
            <div className="py-20 flex flex-col items-center justify-center gap-2 text-muted font-mono text-xs">
              <span className="animate-spin text-2xl">⏳</span>
              <span>Evaluating multi-leg defined risk spreads across options chain...</span>
            </div>
          ) : error ? (
            <div className="p-4 rounded-xl bg-red/10 border border-red/30 text-red text-xs font-mono">
              {error}
            </div>
          ) : strategies.length === 0 ? (
            <div className="py-16 text-center text-muted font-ui text-xs">
              No strategy structures found for current spot and chain.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {strategies.map((strat) => {
                const isCredit = strat.flow_type === 'CREDIT'
                const scoreColor =
                  strat.suitability_score >= 80
                    ? 'text-emerald-500 bg-emerald-500/10 border-emerald-500/30'
                    : strat.suitability_score >= 60
                    ? 'text-amber bg-amber/10 border-amber/30'
                    : 'text-muted bg-panel border-border'

                return (
                  <div
                    key={strat.strategy_id}
                    className="bg-panel border border-border/70 hover:border-amber/40 rounded-xl p-4 flex flex-col justify-between space-y-3 transition-all shadow-xs"
                  >
                    {/* Strategy Top Row */}
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-sm font-bold font-mono text-text">
                              {strat.name}
                            </h3>
                            <span
                              className={`text-[9px] font-mono px-1.5 py-0.5 rounded font-bold border ${
                                strat.bias.includes('BULL')
                                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-600 dark:text-emerald-400'
                                  : strat.bias.includes('BEAR')
                                  ? 'bg-rose-500/15 border-rose-500/30 text-rose-600 dark:text-rose-400'
                                  : 'bg-indigo-500/15 border-indigo-500/30 text-indigo-400'
                              }`}
                            >
                              {strat.bias}
                            </span>
                          </div>
                          <p className="text-[11px] text-muted mt-1 leading-relaxed font-ui">
                            {strat.description}
                          </p>
                        </div>
                        <div
                          className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold border shrink-0 ${scoreColor}`}
                          title="Suitability match based on market regime and risk:reward"
                        >
                          <span>{strat.suitability_score}% Match</span>
                        </div>
                      </div>

                      {/* Financial Metrics Strip */}
                      <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-border/40 font-mono text-center">
                        <div className="bg-elevated/40 p-2 rounded-lg">
                          <span className="text-[10px] text-muted block">Cashflow</span>
                          <span
                            className={`text-xs font-bold tabular-nums ${
                              isCredit ? 'text-emerald-500' : 'text-sky-400'
                            }`}
                          >
                            {isCredit ? `+₹${strat.net_cashflow.toLocaleString('en-IN')}` : `-₹${Math.abs(strat.net_cashflow).toLocaleString('en-IN')}`}
                          </span>
                          <span className="text-[9px] text-muted block">{strat.flow_type}</span>
                        </div>

                        <div className="bg-elevated/40 p-2 rounded-lg">
                          <span className="text-[10px] text-muted block">Max Profit</span>
                          <span className="text-xs font-bold text-emerald-500 tabular-nums">
                            ₹{strat.max_profit.toLocaleString('en-IN')}
                          </span>
                          <span className="text-[9px] text-muted block">Capped</span>
                        </div>

                        <div className="bg-elevated/40 p-2 rounded-lg">
                          <span className="text-[10px] text-muted block">Max Loss</span>
                          <span className="text-xs font-bold text-rose-500 tabular-nums">
                            -₹{Math.abs(strat.max_loss).toLocaleString('en-IN')}
                          </span>
                          <span className="text-[9px] text-muted block">Defined</span>
                        </div>

                        <div className="bg-elevated/40 p-2 rounded-lg">
                          <span className="text-[10px] text-muted block">POP / R:R</span>
                          <span className="text-xs font-bold text-amber tabular-nums">
                            {strat.probability_of_profit_pct}%
                          </span>
                          <span className="text-[9px] text-muted block">1:{strat.risk_reward}</span>
                        </div>
                      </div>

                      {/* Breakevens */}
                      {strat.breakevens?.length > 0 && (
                        <div className="mt-2 text-[10px] font-mono text-muted flex items-center justify-between px-1">
                          <span>Breakeven Level(s):</span>
                          <span className="text-text font-bold tabular-nums">
                            {strat.breakevens.map((b) => `₹${b}`).join('  ·  ')}
                          </span>
                        </div>
                      )}

                      {/* Strategy Legs Table */}
                      <div className="mt-2.5 bg-surface/60 rounded-lg p-2 border border-border/50 text-[10px] font-mono space-y-1">
                        {strat.legs?.map((leg, idx) => (
                          <div key={idx} className="flex items-center justify-between text-muted">
                            <div className="flex items-center gap-1.5">
                              <span
                                className={`font-bold px-1 rounded text-[9px] ${
                                  leg.action === 'BUY'
                                    ? 'bg-emerald-500/20 text-emerald-400'
                                    : 'bg-rose-500/20 text-rose-400'
                                }`}
                              >
                                {leg.action}
                              </span>
                              <span className="text-text font-bold">
                                {leg.strike} {leg.option_type}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span>₹{leg.premium}</span>
                              <span className="text-text/70">{leg.quantity} Qty ({leg.lots}L)</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border/40 font-mono text-xs">
                      <button
                        type="button"
                        onClick={() => {
                          if (onSimulateStrategy) {
                            onSimulateStrategy(strat.legs, strat.name)
                          }
                        }}
                        className="px-3 py-1.5 rounded-lg bg-elevated hover:bg-panel border border-border text-muted hover:text-text font-semibold flex items-center justify-center gap-1 transition-all cursor-pointer"
                      >
                        <span>📈</span>
                        <span>Payoff Curve</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => {
                          if (onStageSpread) {
                            onStageSpread({
                              symbol: underlying,
                              action: strat.legs[0]?.action || 'BUY',
                              strike: strat.legs[0]?.strike,
                              optionType: strat.legs[0]?.option_type,
                              qty: lotSize,
                              strategyName: strat.name,
                              legs: strat.legs,
                            })
                          }
                          onClose()
                        }}
                        className="px-3 py-1.5 rounded-lg bg-amber hover:bg-amber/90 text-black font-bold flex items-center justify-center gap-1 transition-all cursor-pointer shadow-xs"
                      >
                        <span>⚡</span>
                        <span>Stage Spread</span>
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
