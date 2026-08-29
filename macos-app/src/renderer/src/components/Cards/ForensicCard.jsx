import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const RATING_COLORS = {
  'A+': { bg: 'bg-green/15 text-green border-green/40', badge: 'bg-green text-surface' },
  'A':  { bg: 'bg-green/10 text-green border-green/30', badge: 'bg-green/90 text-surface' },
  'B':  { bg: 'bg-blue/10 text-blue border-blue/30',   badge: 'bg-blue text-surface' },
  'C':  { bg: 'bg-amber/10 text-amber border-amber/30', badge: 'bg-amber text-surface' },
  'D':  { bg: 'bg-red/10 text-red border-red/30',     badge: 'bg-red text-surface' },
}

export default function ForensicCard({ data }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const openInspector = useInspectorStore((s) => s.openInspector)

  const rating = d.quality_rating || 'B'
  const ratingStyle = RATING_COLORS[rating] || RATING_COLORS['B']
  const mScore = Number(d.beneish_m_score ?? -2.5)
  const isMScoreSafe = !d.is_beneish_flagged
  const zScore = Number(d.altman_z_score ?? 3.5)
  const zZone = d.distress_zone || 'SAFE'
  const fScore = Number(d.piotroski_f_score ?? 7)
  const redFlags = d.governance_red_flags || []
  const strengths = d.piotroski_strengths || []

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">🛡️</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Corporate Governance & Accounting Audit</p>
              <InfoBadge
                title="Forensic Accounting Suite"
                content="Combines Beneish M-Score, Altman Z''-Score, Piotroski 9-point F-Score, and promoter pledging constraints."
                metricKey="beneish_m_score"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">{d.symbol} Forensic Quality Rating</p>
          </div>
        </div>

        {/* Quality Rating Badge */}
        <Tooltip
          title={`Grade ${rating} Quality Assessment`}
          content="Calculated from weighted solvency, cash-flow vs accrual alignment, leverage, and operational momentum."
          metricKey="piotroski_f_score"
        >
          <div
            onClick={() => openInspector('piotroski_f_score', { symbol: d.symbol })}
            className={`flex items-center gap-2 px-3 py-1 rounded-lg border ${ratingStyle.bg} cursor-pointer hover:scale-105 transition-transform`}
          >
            <span className="text-xs font-ui font-medium">Quality Grade:</span>
            <span className="text-lg font-bold font-mono">{rating}</span>
          </div>
        </Tooltip>
      </div>

      {/* 3 Core Quantitative Forensic Models Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* 1. Beneish M-Score */}
        <Tooltip
          title="Beneish M-Score (Earnings Manipulation Model)"
          content="Identifies artificial revenue inflation and accruals distortion. M > -1.78 signifies elevated manipulation probability."
          metricKey="beneish_m_score"
          formula="M = -4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI..."
        >
          <div
            onClick={() => openInspector('beneish_m_score', { symbol: d.symbol })}
            className="w-full bg-panel hover:bg-elevated/70 border border-border/60 hover:border-amber/50 rounded-lg p-3 space-y-1.5 cursor-pointer transition-all hover:shadow-xs group"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-text font-ui group-hover:text-amber transition-colors">Beneish M-Score</span>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                isMScoreSafe ? 'bg-green/10 text-green' : 'bg-red/10 text-red'
              }`}>
                {isMScoreSafe ? 'CLEAN' : 'FLAGGED'}
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold font-mono text-text">{mScore.toFixed(2)}</span>
              <span className="text-[10px] text-muted font-ui">Safe: &le; -1.78</span>
            </div>
            <p className="text-[10px] text-muted font-ui line-clamp-1">
              {isMScoreSafe ? 'Clean revenue & accruals' : 'Accruals distortion risk'}
            </p>
          </div>
        </Tooltip>

        {/* 2. Altman Z''-Score */}
        <Tooltip
          title="Altman Z''-Score (Emerging Market Solvency)"
          content="Quantifies bankruptcy and credit default risk. Z'' > 2.60 is in the safe zone unburdened by debt distress."
          metricKey="altman_z_score"
          formula="Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4"
        >
          <div
            onClick={() => openInspector('altman_z_score', { symbol: d.symbol })}
            className="w-full bg-panel hover:bg-elevated/70 border border-border/60 hover:border-blue/50 rounded-lg p-3 space-y-1.5 cursor-pointer transition-all hover:shadow-xs group"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-text font-ui group-hover:text-blue transition-colors">Altman Z''-Score</span>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                zZone === 'SAFE' ? 'bg-green/10 text-green' : zZone === 'GREY' ? 'bg-amber/10 text-amber' : 'bg-red/10 text-red'
              }`}>
                {zZone}
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold font-mono text-text">{zScore.toFixed(2)}</span>
              <span className="text-[10px] text-muted font-ui">Safe: &gt; 2.60</span>
            </div>
            <p className="text-[10px] text-muted font-ui line-clamp-1">
              {zZone === 'SAFE' ? 'Strong solvency profile' : zZone === 'GREY' ? 'Moderate credit buffer' : 'Distress risk'}
            </p>
          </div>
        </Tooltip>

        {/* 3. Piotroski F-Score */}
        <Tooltip
          title="Piotroski 9-Point F-Score"
          content="Scores profitability, operational efficiency, and balance sheet deleveraging (0 to 9 points)."
          metricKey="piotroski_f_score"
        >
          <div
            onClick={() => openInspector('piotroski_f_score', { symbol: d.symbol })}
            className="w-full bg-panel hover:bg-elevated/70 border border-border/60 hover:border-green/50 rounded-lg p-3 space-y-1.5 cursor-pointer transition-all hover:shadow-xs group"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-text font-ui group-hover:text-green transition-colors">Piotroski F-Score</span>
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue/10 text-blue">
                {fScore >= 7 ? 'HIGH' : fScore >= 4 ? 'AVG' : 'WEAK'}
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold font-mono text-text">{fScore} <span className="text-xs text-muted font-normal">/ 9</span></span>
              <span className="text-[10px] text-muted font-ui">Passed</span>
            </div>
            <div className="w-full bg-elevated h-1.5 rounded-full overflow-hidden">
              <div
                style={{ width: `${(fScore / 9) * 100}%` }}
                className={`h-full ${fScore >= 7 ? 'bg-green' : fScore >= 4 ? 'bg-amber' : 'bg-red'}`}
              />
            </div>
          </div>
        </Tooltip>
      </div>

      {/* Governance Red Flags Warning Box */}
      {redFlags.length > 0 ? (
        <Tooltip
          title="Indian Governance Red Flag Warnings"
          content="Promoter share pledging >10%/20%, interest coverage <2.0x, or cash flow divergence."
          metricKey="governance_red_flags"
        >
          <div
            onClick={() => openInspector('governance_red_flags', { symbol: d.symbol })}
            className="w-full bg-red/10 border border-red/30 hover:border-red/60 rounded-lg p-3 space-y-1.5 cursor-pointer transition-colors text-left"
          >
            <div className="flex items-center justify-between text-red font-semibold text-xs font-ui">
              <div className="flex items-center gap-1.5">
                <span>⚠️</span>
                <span>Governance & Accounting Red Flags Detected ({redFlags.length})</span>
              </div>
              <span className="text-[10px] underline font-ui">Inspect details ➔</span>
            </div>
            <ul className="space-y-1 text-xs text-text font-ui">
              {redFlags.map((flag, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="text-red font-bold">•</span>
                  <span>{flag}</span>
                </li>
              ))}
            </ul>
          </div>
        </Tooltip>
      ) : (
        <div className="bg-green/10 border border-green/30 rounded-lg p-2.5 flex items-center justify-between text-xs font-ui text-green">
          <div className="flex items-center gap-2">
            <span>✓</span>
            <span>No critical promoter pledging, solvency, or accrual governance red flags detected.</span>
          </div>
          <InfoBadge
            title="Clean Governance Audit"
            content="Promoter pledge <5%, interest coverage >2.5x, and clean operating cash flow alignment."
            metricKey="governance_red_flags"
          />
        </div>
      )}

      {/* Piotroski Strengths Breakdown */}
      {strengths.length > 0 && (
        <div className="bg-panel border border-border/60 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-text font-ui">9-Point Operational Quality Checklist</span>
            <InfoBadge
              title="Piotroski Checklist"
              content="Click to see each of the 9 binary fundamental accounting criteria."
              metricKey="piotroski_f_score"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs font-ui text-muted">
            {strengths.map((item, idx) => (
              <div key={idx} className="flex items-center gap-1.5 bg-elevated/60 px-2 py-1 rounded">
                <span className="text-green text-xs font-bold">✓</span>
                <span className="truncate">{item}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary Narrative */}
      {d.summary_text && (
        <p className="text-xs text-muted font-ui italic border-t border-border/30 pt-2">
          "{d.summary_text}"
        </p>
      )}
    </div>
  )
}

