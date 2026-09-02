import { useState } from 'react'
import Tooltip, { InfoBadge } from '../UI/Tooltip'
import { useChatStore } from '../../store/chatStore'

export default function DefinedRiskSpreadCard({ data }) {
  const sendDraft = useChatStore((s) => s.sendDraft)
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const underlying = d.underlying || '—'
  const strategy = d.strategy_name || d.strategy || 'UNAVAILABLE'
  const spotPrice = d.spot_price != null ? Number(d.spot_price) : null
  const netCashflow = d.net_cashflow != null ? Number(d.net_cashflow) : null
  const maxProfit = d.max_profit != null ? Number(d.max_profit) : null
  const maxLoss = d.max_loss != null ? Number(d.max_loss) : null
  const rrRatio = d.risk_reward_ratio != null ? Number(d.risk_reward_ratio) : null
  const breakevens = d.breakevens || []
  const legs = d.legs || []
  const marginReq = Number(d.margin_required || 0)

  const isDebit = netCashflow != null && netCashflow < 0
  const isCredit = netCashflow != null && netCashflow > 0

  return (
    <div className="bg-elevated/90 border border-border/80 rounded-2xl p-5 max-w-2xl w-full space-y-4 font-mono shadow-md backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-2xl">
            🛡️
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase font-bold tracking-widest text-muted font-ui">
                Defined-Risk Option Strategy
              </span>
              <InfoBadge
                title="Strictly Capped Risk"
                content="Multi-leg option spread with non-linear payoff, zero naked risk, and eliminated Theta bleed."
                metricKey="defined_risk_options"
              />
            </div>
            <h2 className="text-base font-bold font-ui text-text flex items-center gap-2">
              <span>{underlying}</span>
              <span className="text-xs px-2 py-0.5 rounded-md bg-surface text-cyan-400 border border-border/60 font-mono">
                {strategy.replace(/_/g, ' ')}
              </span>
            </h2>
          </div>
        </div>

        {/* Spot Price */}
        <div className="text-right">
          <span className="text-xs text-muted block font-ui">Spot Price</span>
          <span className="text-sm font-bold text-text font-mono">
            {spotPrice != null ? `₹${spotPrice.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
          </span>
        </div>
      </div>

      {/* Primary Payoff Metrics Box */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-surface/80 border border-border/70 rounded-xl p-3 text-center">
        <div>
          <span className="text-[10px] text-muted block uppercase font-ui">Max Profit</span>
          <span className="text-xs sm:text-sm font-bold text-emerald-400">
            {maxProfit != null ? `+₹${maxProfit.toLocaleString('en-IN', { minimumFractionDigits: 0 })}` : 'Unbounded'}
          </span>
        </div>
        <div>
          <span className="text-[10px] text-muted block uppercase font-ui">Max Loss (Capped)</span>
          <span className="text-xs sm:text-sm font-bold text-rose-400">
            {maxLoss != null ? `-₹${Math.abs(maxLoss).toLocaleString('en-IN', { minimumFractionDigits: 0 })}` : 'Defined'}
          </span>
        </div>
        <div>
          <span className="text-[10px] text-muted block uppercase font-ui">Net Cashflow</span>
          <span className={`text-xs sm:text-sm font-bold ${isCredit ? 'text-emerald-400' : 'text-amber'}`}>
            {netCashflow == null ? '—' : isCredit ? `+₹${netCashflow.toFixed(0)} (Cr)` : `-₹${Math.abs(netCashflow).toFixed(0)} (Dr)`}
          </span>
        </div>
        <div>
          <span className="text-[10px] text-muted block uppercase font-ui">Risk:Reward</span>
          <span className="text-xs sm:text-sm font-bold text-cyan-400">
            {rrRatio != null ? `1 : ${rrRatio.toFixed(2)}` : '—'}
          </span>
        </div>
      </div>

      {/* Strategy Legs Table */}
      <div className="space-y-2">
        <span className="text-[11px] uppercase font-bold text-muted font-ui tracking-wider block">
          Strategy Contract Legs ({legs.length})
        </span>

        <div className="space-y-1.5">
          {legs.map((leg, idx) => {
            const isBuy = leg.action?.toUpperCase() === 'BUY'
            return (
              <div
                key={idx}
                className="flex items-center justify-between p-2.5 rounded-xl bg-surface border border-border/60 text-xs font-mono"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
                      isBuy ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                    }`}
                  >
                    {leg.action?.toUpperCase()}
                  </span>
                  <span className="font-bold text-text">
                    {underlying} {leg.strike} {leg.option_type}
                  </span>
                </div>

                <div className="flex items-center gap-3 text-right">
                  <span className="text-muted">
                    Premium: <strong className="text-text">₹{Number(leg.premium || 0).toFixed(1)}</strong>
                  </span>
                  <span className="text-muted">
                    Qty: <strong className="text-text">{leg.quantity || (leg.lots * leg.lot_size)}</strong>
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Breakevens & Margin Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3 text-xs font-ui">
        <div className="flex items-center gap-2 font-mono text-[11px]">
          <span className="text-muted">Breakeven:</span>
          <span className="font-bold text-amber">
            {breakevens.length > 0 ? breakevens.map(b => `₹${Number(b).toFixed(1)}`).join(' / ') : 'Calculated at expiry'}
          </span>
          {marginReq > 0 && (
            <>
              <span className="text-muted">•</span>
              <span className="text-muted">Margin Req: <strong className="text-text font-mono">₹{marginReq.toLocaleString('en-IN')}</strong></span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
