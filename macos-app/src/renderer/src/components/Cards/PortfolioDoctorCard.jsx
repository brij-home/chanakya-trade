import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const GRADE_STYLES = {
  'A+': { color: 'bg-green text-surface font-bold', border: 'border-green/40' },
  'A':  { color: 'bg-green/15 text-green border border-green/30', border: 'border-green/40' },
  'B':  { color: 'bg-blue/15 text-blue border border-blue/30', border: 'border-blue/40' },
  'C':  { color: 'bg-amber/15 text-amber border border-amber/30', border: 'border-amber/40' },
  'D':  { color: 'bg-red text-surface font-bold', border: 'border-red/40' },
}

export default function PortfolioDoctorCard({ data }) {
  const openInspector = useInspectorStore((s) => s.openInspector)
  if (!data) return null
  const d = data?.data ?? data ?? {}

  const gradeStyle = GRADE_STYLES[d.overall_health_grade] || GRADE_STYLES['A']
  const deadMoney = d.dead_money_holdings || []
  const taxHarvest = d.tax_harvest_candidates || []
  const prescriptions = d.action_prescriptions || []

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-3xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-blue text-xl">🩺</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Wealth Optimizer</p>
              <InfoBadge
                title="Broker Portfolio AI Doctor"
                content="Diagnoses Stage 4 dead money, Herfindahl concentration risks, tax-loss harvesting, and rebalancing opportunities."
                metricKey="minervini_trend_template"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Portfolio AI Health Diagnosis</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={`text-xs font-ui px-2.5 py-1 rounded ${gradeStyle.color}`}>
            Health Grade: {d.overall_health_grade}
          </span>
        </div>
      </div>

      {/* Overview Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-ui text-xs">
        <div className="bg-panel p-2.5 rounded-lg border border-border/60">
          <span className="text-[10px] text-muted uppercase font-medium">Total Net Worth</span>
          <p className="text-sm font-bold font-mono text-text mt-0.5">₹{d.total_net_worth?.toLocaleString()}</p>
        </div>
        <div className="bg-panel p-2.5 rounded-lg border border-border/60">
          <span className="text-[10px] text-muted uppercase font-medium">Dead Money %</span>
          <p className={`text-sm font-bold font-mono mt-0.5 ${d.dead_money_pct > 15 ? 'text-red' : 'text-green'}`}>
            {d.dead_money_pct}%
          </p>
        </div>
        <div className="bg-panel p-2.5 rounded-lg border border-border/60">
          <span className="text-[10px] text-muted uppercase font-medium">Concentration Risk</span>
          <p className={`text-sm font-bold font-mono mt-0.5 ${d.concentration_risk === 'HIGH' || d.concentration_risk === 'CRITICAL' ? 'text-red' : 'text-green'}`}>
            {d.concentration_risk} (HHI: {d.herfindahl_index})
          </p>
        </div>
        <div className="bg-panel p-2.5 rounded-lg border border-border/60">
          <span className="text-[10px] text-muted uppercase font-medium">Tax Savings Pot.</span>
          <p className="text-sm font-bold font-mono text-green mt-0.5">₹{d.total_tax_savings_estimate?.toLocaleString()}</p>
        </div>
      </div>

      {/* Dead Money Alerts (Stage 4 Markdown) */}
      {deadMoney.length > 0 && (
        <div className="bg-red/10 border border-red/30 rounded-lg p-3 space-y-2 font-ui">
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold text-red flex items-center gap-1">
              <span>⚠️</span> Stage 4 Dead-Money Holdings ({deadMoney.length} Positions)
            </span>
            <span className="text-red font-mono font-semibold text-[11px]">Total: ₹{d.total_dead_money_value?.toLocaleString()}</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            {deadMoney.map((dm, idx) => (
              <div key={idx} className="bg-elevated/70 p-2.5 rounded border border-red/20 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-bold font-mono text-text">{dm.symbol} ({dm.qty} shares)</span>
                  <span className="text-red font-mono font-bold">{dm.pnl_pct}%</span>
                </div>
                <p className="text-[11px] text-muted">{dm.diagnosis}</p>
                <p className="text-[10px] text-amber font-medium">💡 {dm.rebalance_suggestion}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tax-Loss Harvesting Candidates */}
      {taxHarvest.length > 0 && (
        <div className="bg-green/10 border border-green/30 rounded-lg p-3 space-y-2 font-ui">
          <div className="flex items-center justify-between text-xs">
            <span className="font-bold text-green flex items-center gap-1">
              <span>💰</span> Tax-Loss Harvesting Opportunities
            </span>
            <span className="text-green font-mono font-semibold text-[11px]">Save up to ₹{d.total_tax_savings_estimate?.toLocaleString()}</span>
          </div>

          <div className="space-y-1.5 text-xs">
            {taxHarvest.map((th, idx) => (
              <div key={idx} className="bg-elevated/60 p-2 rounded border border-green/20 flex items-center justify-between">
                <div>
                  <span className="font-bold font-mono text-text">{th.symbol}</span>
                  <span className="text-[11px] text-muted ml-2">Unrealized Loss: ₹{th.unrealised_loss?.toLocaleString()}</span>
                </div>
                <span className="text-green font-mono font-bold text-[11px]">Tax Save: ₹{th.tax_savings_potential?.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Prescriptions */}
      <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2 font-ui">
        <span className="text-[10px] text-muted uppercase font-medium">AI Wealth Prescriptions</span>
        <div className="space-y-1 text-xs">
          {prescriptions.map((p, idx) => (
            <p key={idx} className="bg-elevated/50 p-2 rounded border border-border/30 text-text leading-relaxed">
              ✓ {p}
            </p>
          ))}
        </div>
      </div>
    </div>
  )
}
