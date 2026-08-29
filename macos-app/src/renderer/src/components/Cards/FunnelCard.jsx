import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const VERDICT_STYLES = {
  'STRONG_BUY':  'bg-green text-surface font-bold',
  'BUY':         'bg-green/15 text-green border border-green/30 font-semibold',
  'HOLD':        'bg-amber/15 text-amber border border-amber/30 font-semibold',
  'SELL':        'bg-red/15 text-red border border-red/30 font-semibold',
  'STRONG_SELL': 'bg-red text-surface font-bold',
  'AVOID':       'bg-panel text-muted border border-border font-semibold',
}

export default function FunnelCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const openInspector = useInspectorStore((s) => s.openInspector)

  const reports = d.pre_filter_reports || []
  const plans = d.trade_plans || []
  const qualified = reports.filter(r => r.qualified)
  const filtered = reports.filter(r => !r.qualified)

  const [activeTab, setActiveTab] = useState('plans') // 'plans' | 'screen' | 'macro'

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">🎯</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Screening Pipeline</p>
              <InfoBadge
                title="Smart Funnel Multi-Agent Pipeline"
                content="Deterministic 0-token quantitative pre-filtering, macro context injection, and Bull vs Bear persona debates."
                metricKey="smart_funnel_pipeline"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Smart Funnel Multi-Agent Analysis</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-ui">
          <Tooltip
            title="Qualified Candidates"
            content="Passed technical momentum, valuation, sector RRG tailwind, and forensic accounting screens."
            metricKey="smart_funnel_pipeline"
          >
            <span className="bg-green/10 text-green px-2 py-0.5 rounded font-bold border border-green/30 cursor-pointer">
              {qualified.length} Passed
            </span>
          </Tooltip>
          <Tooltip
            title="Filtered Disqualifications"
            content="Eliminated in Stage 1 pre-filter without consuming AI LLM tokens."
            metricKey="smart_funnel_pipeline"
          >
            <span className="bg-red/10 text-red px-2 py-0.5 rounded font-bold border border-red/30 cursor-pointer">
              {filtered.length} Filtered
            </span>
          </Tooltip>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-border/40 pb-2 text-xs font-ui">
        <button
          onClick={() => setActiveTab('plans')}
          className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
            activeTab === 'plans' ? 'bg-amber text-surface font-bold' : 'text-muted hover:text-text'
          }`}
        >
          ⚔️ Synthesized Trade Plans ({plans.length})
        </button>
        <button
          onClick={() => setActiveTab('screen')}
          className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
            activeTab === 'screen' ? 'bg-amber text-surface font-bold' : 'text-muted hover:text-text'
          }`}
        >
          ⚡ Stage 1 Pre-Filter ({reports.length})
        </button>
        <button
          onClick={() => setActiveTab('macro')}
          className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
            activeTab === 'macro' ? 'bg-amber text-surface font-bold' : 'text-muted hover:text-text'
          }`}
        >
          🌐 Macro & VIX Context
        </button>
      </div>

      {/* TAB 1: Trade Plans */}
      {activeTab === 'plans' && (
        <div className="space-y-3">
          {plans.length === 0 ? (
            <div className="bg-panel p-4 rounded-lg text-center text-xs text-muted font-ui">
              No full multi-agent trade plans generated (run deep debate mode).
            </div>
          ) : (
            plans.map((p, idx) => (
              <div
                key={idx}
                onClick={() => openInspector('smart_funnel_pipeline', { symbol: p.symbol, verdict: p.verdict, ...p })}
                className="bg-panel hover:bg-elevated/80 border border-border/60 hover:border-amber/50 rounded-lg p-3.5 space-y-2.5 cursor-pointer transition-all"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-bold font-mono text-text">{p.symbol}</span>
                    <span className={`px-2.5 py-0.5 rounded text-xs ${VERDICT_STYLES[p.verdict] || VERDICT_STYLES['HOLD']}`}>
                      {p.verdict}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-ui">
                    <span className="text-muted">Debate Winner:</span>
                    <span className="font-bold text-amber font-mono">{p.winner}</span>
                    <span className="text-muted">• Confidence:</span>
                    <span className="font-bold text-green font-mono">{p.confidence}%</span>
                  </div>
                </div>

                {/* Strategy & Price levels */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-elevated/70 p-2.5 rounded text-xs font-ui">
                  <div>
                    <span className="text-[10px] text-muted uppercase">Entry</span>
                    <p className="font-semibold text-text font-mono truncate">{p.entry}</p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted uppercase">Stop-Loss</span>
                    <p className="font-semibold text-red font-mono truncate">{p.stop_loss}</p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted uppercase">Target</span>
                    <p className="font-semibold text-green font-mono truncate">{p.target}</p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted uppercase">Position Size</span>
                    <p className="font-semibold text-amber font-mono truncate">{p.position_size}</p>
                  </div>
                </div>

                {/* Rationale bullet points */}
                {p.rationale && p.rationale.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-muted font-ui uppercase font-semibold">Key Bull Rationale</span>
                    <ul className="text-xs text-text space-y-0.5 font-ui">
                      {p.rationale.map((r, rIdx) => (
                        <li key={rIdx} className="flex items-start gap-1.5">
                          <span className="text-green font-bold">✓</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* TAB 2: Stage 1 Screening Pre-Filter */}
      {activeTab === 'screen' && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-ui text-left">
            <thead>
              <tr className="border-b border-border/60 text-[10px] uppercase text-muted tracking-wider">
                <th className="pb-1.5 font-medium">Symbol</th>
                <th className="pb-1.5 font-medium text-right">Score</th>
                <th className="pb-1.5 font-medium text-right">Status</th>
                <th className="pb-1.5 font-medium pl-3">Evaluation Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {reports.map((r) => (
                <tr
                  key={r.symbol}
                  onClick={() => openInspector('smart_funnel_pipeline', { symbol: r.symbol, score: r.score })}
                  className="hover:bg-elevated/70 transition-colors cursor-pointer"
                  title="Click to inspect scoring model"
                >
                  <td className="py-2 font-bold text-text font-mono flex items-center gap-1.5">
                    <span className="text-amber">◆</span>
                    <span>{r.symbol}</span>
                  </td>
                  <td className="py-2 text-right font-mono font-semibold text-text">{Number(r.score).toFixed(0)}/100</td>
                  <td className="py-2 text-right">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      r.qualified ? 'bg-green/10 text-green' : 'bg-red/10 text-red'
                    }`}>
                      {r.status_label || (r.qualified ? 'QUALIFIED' : 'FILTERED')}
                    </span>
                  </td>
                  <td className="py-2 pl-3 text-muted text-[11px] truncate max-w-xs font-ui">
                    {r.qualified ? r.pass_reason : r.rejection_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* TAB 3: Macro Context */}
      {activeTab === 'macro' && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-3 text-xs font-ui">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Tooltip
              title="India VIX Volatility Gauge"
              content="Implied volatility of NIFTY options. VIX < 15 is calm bull, > 20 is elevated hedging hazard."
              metricKey="smart_funnel_pipeline"
            >
              <div
                onClick={() => openInspector('smart_funnel_pipeline')}
                className="bg-elevated hover:bg-elevated/80 p-2 rounded cursor-pointer transition-colors w-full text-left"
              >
                <span className="text-[10px] text-muted uppercase">India VIX</span>
                <p className="text-base font-bold font-mono text-amber">{d.macro_context?.vix ?? '—'}</p>
              </div>
            </Tooltip>

            <Tooltip
              title="Macro Posture"
              content="Market regime classification based on breadth, institutional flows, and trend filters."
              metricKey="smart_funnel_pipeline"
            >
              <div
                onClick={() => openInspector('smart_funnel_pipeline')}
                className="bg-elevated hover:bg-elevated/80 p-2 rounded cursor-pointer transition-colors w-full text-left"
              >
                <span className="text-[10px] text-muted uppercase">Market Posture</span>
                <p className="text-base font-bold font-mono text-green">{d.macro_context?.posture ?? 'BULLISH'}</p>
              </div>
            </Tooltip>

            <Tooltip
              title="FII Institutional Net Inflows"
              content="Net buying/selling in cash equity by foreign institutional investors."
              metricKey="smart_funnel_pipeline"
            >
              <div
                onClick={() => openInspector('smart_funnel_pipeline')}
                className="bg-elevated hover:bg-elevated/80 p-2 rounded cursor-pointer transition-colors w-full text-left"
              >
                <span className="text-[10px] text-muted uppercase">FII Net Flow</span>
                <p className="text-base font-bold font-mono text-text">{d.macro_context?.fii_net ?? '—'}</p>
              </div>
            </Tooltip>

            <Tooltip
              title="Market Breadth Ratio"
              content="Advance/Decline ratio across NIFTY 50 and NIFTY 500 components."
              metricKey="smart_funnel_pipeline"
            >
              <div
                onClick={() => openInspector('smart_funnel_pipeline')}
                className="bg-elevated hover:bg-elevated/80 p-2 rounded cursor-pointer transition-colors w-full text-left"
              >
                <span className="text-[10px] text-muted uppercase">Breadth Ratio</span>
                <p className="text-base font-bold font-mono text-text">{d.macro_context?.breadth ?? '1.4x'}</p>
              </div>
            </Tooltip>
          </div>
        </div>
      )}
    </div>
  )
}

