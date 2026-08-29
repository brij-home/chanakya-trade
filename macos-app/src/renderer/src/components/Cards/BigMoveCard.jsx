import { useInspectorStore } from '../../store/inspectorStore'
import { useChatStore } from '../../store/chatStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const VERDICT_STYLES = {
  EXPLOSIVE_BULLISH_EXPANSION: {
    badge: 'bg-green text-surface font-bold',
    label: '🚀 Explosive Bullish Expansion',
    icon: '🚀',
    border: 'border-green/40',
  },
  EXPLOSIVE_BEARISH_BREAKDOWN: {
    badge: 'bg-red text-surface font-bold',
    label: '🚨 Explosive Bearish Breakdown',
    icon: '🚨',
    border: 'border-red/40',
  },
  COILING_SQUEEZE_PENDING: {
    badge: 'bg-amber text-surface font-bold',
    label: '🔴 Energy Coiling (Squeeze Pending)',
    icon: '🔴',
    border: 'border-amber/40',
  },
  CHOPPY_RANGE: {
    badge: 'bg-panel text-muted border border-border',
    label: '⚖️ Choppy Range (Mean Reverting)',
    icon: '⚖️',
    border: 'border-border',
  },
}

const TIMING_BADGES = {
  TRIGGER_NOW:             { label: '⚡ Trigger Now (Breakout Active)', color: 'bg-green/15 text-green border border-green/30' },
  STALK_ON_PULLBACK:       { label: '🎯 Stalk on Minor Pullback', color: 'bg-amber/15 text-amber border border-amber/30' },
  PREPARE_FOR_BREAKOUT:    { label: '⏳ Prepare (Set Breakout Alerts)', color: 'bg-blue/15 text-blue border border-blue/30' },
  WAIT_FOR_CONFIRMATION:   { label: '⏸️ Wait for Confirmation', color: 'bg-panel text-muted border border-border' },
}

export default function BigMoveCard({ data, onOpenOrderTicket }) {
  if (!data) return null
  const d = data?.data ?? data ?? {}
  const sq = d.squeeze || {}
  const opt = d.options_flow || {}

  const openInspector = useInspectorStore((s) => s.openInspector)
  const sendDraft = useChatStore((s) => s.sendDraft)

  const verdict = VERDICT_STYLES[d.prediction_verdict] || VERDICT_STYLES.CHOPPY_RANGE
  const timing = TIMING_BADGES[d.timing_trigger] || TIMING_BADGES.WAIT_FOR_CONFIRMATION

  const isBullish = d.directional_bias === 'BULLISH'
  const isBearish = d.directional_bias === 'BEARISH'

  return (
    <div className={`bg-elevated border ${verdict.border} rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-md`}>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/50 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-2xl">{verdict.icon}</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Big Move Direction & Timing Predictor</p>
              <InfoBadge
                title="Institutional Large Move Predictor"
                content="Combines John Carter TTM Volatility Squeeze, Options OI Flow (Long Buildup vs Short Covering), SMC Market Structure, and Volume Expansion."
                metricKey="big_move_pipeline"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-base font-bold text-text font-mono">{d.symbol}</span>
              <span className="text-xs text-muted font-ui">₹{d.ltp?.toLocaleString()}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={`text-xs px-2.5 py-1 rounded font-ui ${verdict.badge}`}>
            {verdict.label}
          </span>
          <div className="bg-panel border border-border px-2.5 py-1 rounded text-center">
            <span className="text-[10px] text-muted block font-ui">Probability</span>
            <span className={`text-xs font-bold ${d.directional_probability >= 80 ? (isBullish ? 'text-green' : 'text-red') : 'text-amber'}`}>
              {d.directional_probability}%
            </span>
          </div>
        </div>
      </div>

      {/* Timing Status Strip */}
      <div className="flex items-center justify-between bg-panel border border-border/60 p-2.5 rounded-lg text-xs font-ui">
        <div className="flex items-center gap-2">
          <span className="text-muted text-[10px] uppercase font-semibold">Timing:</span>
          <span className={`text-[11px] px-2 py-0.5 rounded font-mono font-bold ${timing.color}`}>
            {timing.label}
          </span>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-muted">
          <span>Expected Move:</span>
          <span className={`font-bold font-mono ${isBullish ? 'text-green' : isBearish ? 'text-red' : 'text-amber'}`}>
            ±{d.expected_move_pct}% (₹{d.expected_move_pts} pts)
          </span>
        </div>
      </div>

      {/* Payoff Blueprint (Entry, SL, Target) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-panel/70 border border-border/40 p-3 rounded-lg text-xs font-ui">
        <div>
          <span className="text-[10px] text-muted uppercase block font-mono">Entry Reference</span>
          <p className="font-bold text-text text-sm font-mono mt-0.5">₹{d.ltp?.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-[10px] text-muted uppercase block font-mono">Invalidation Stop</span>
          <p className="font-bold text-red text-sm font-mono mt-0.5">₹{d.invalidation_price?.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-[10px] text-muted uppercase block font-mono">Move Target (2.5x ATR)</span>
          <p className="font-bold text-green text-sm font-mono mt-0.5">₹{d.target_price?.toLocaleString()}</p>
        </div>
        <div>
          <span className="text-[10px] text-muted uppercase block font-mono">Risk : Reward</span>
          <p className="font-bold text-amber text-sm font-mono mt-0.5">1 : {d.risk_reward_ratio}</p>
        </div>
      </div>

      {/* 2-Column Institutional Diagnostic: Squeeze vs Options OI */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-ui">
        {/* Squeeze Status */}
        <div className="bg-panel border border-border/60 p-3 rounded-lg space-y-2">
          <div className="flex items-center justify-between border-b border-border/40 pb-1.5">
            <span className="font-bold text-text flex items-center gap-1.5">
              <span>🌀</span>
              <span>TTM Volatility Squeeze</span>
            </span>
            <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
              sq.squeeze_fired ? 'bg-green/15 text-green border border-green/30' :
              sq.is_squeeze_on ? 'bg-amber/15 text-amber border border-amber/30' : 'bg-elevated text-muted'
            }`}>
              {sq.squeeze_fired ? '🟢 FIRED' : sq.is_squeeze_on ? `🔴 Coiling (${sq.squeeze_duration_bars} bars)` : '⚪ No Squeeze'}
            </span>
          </div>

          <div className="space-y-1 text-[11px] text-muted">
            <div className="flex justify-between">
              <span>Momentum Slope:</span>
              <span className={`font-mono font-bold ${sq.momentum_value >= 0 ? 'text-green' : 'text-red'}`}>
                {sq.momentum_value > 0 ? `+${sq.momentum_value}` : sq.momentum_value} ({sq.momentum_direction})
              </span>
            </div>
            <div className="flex justify-between">
              <span>Bollinger Bands:</span>
              <span className="font-mono text-text">₹{sq.bb_lower} – ₹{sq.bb_upper}</span>
            </div>
          </div>
        </div>

        {/* Options OI Flow */}
        <div className="bg-panel border border-border/60 p-3 rounded-lg space-y-2">
          <div className="flex items-center justify-between border-b border-border/40 pb-1.5">
            <span className="font-bold text-text flex items-center gap-1.5">
              <span>📊</span>
              <span>Options OI Flow</span>
            </span>
            <span className="text-[10px] bg-elevated border border-border px-2 py-0.5 rounded font-mono font-bold text-text">
              {opt.dominant_regime}
            </span>
          </div>

          <div className="space-y-1 text-[11px] text-muted">
            <div className="flex justify-between">
              <span>Put/Call Ratio (PCR):</span>
              <span className={`font-mono font-bold ${opt.pcr >= 1.1 ? 'text-green' : opt.pcr <= 0.8 ? 'text-red' : 'text-text'}`}>
                {opt.pcr} ({opt.institutional_sentiment})
              </span>
            </div>
            <div className="flex justify-between">
              <span>Max Pain Level:</span>
              <span className="font-mono text-text">₹{opt.max_pain_strike?.toLocaleString()}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Catalysts & Action Plan */}
      <div className="bg-panel border border-border/40 p-3 rounded-lg space-y-2 text-xs font-ui">
        <div className="flex items-center gap-1.5 text-text font-bold">
          <span>💡</span>
          <span>Institutional Catalysts & Alignments</span>
        </div>
        <ul className="space-y-1 text-[11px] text-muted list-disc list-inside">
          {d.catalysts?.map((c, idx) => (
            <li key={idx} className="leading-snug">{c}</li>
          ))}
        </ul>

        <div className="pt-2 border-t border-border/30 text-[11px] text-text font-semibold">
          📌 {d.action_plan}
        </div>
      </div>

      {/* Action Buttons (1-Click Instant Execution) */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              window.dispatchEvent(new CustomEvent('close-all-modals'))
              sendDraft(`size ${d.symbol} ${d.ltp} ${d.invalidation_price}`)
            }}
            className="px-2.5 py-1 rounded bg-panel hover:bg-elevated border border-border text-text text-xs font-ui transition-colors cursor-pointer"
            title="Size position with volatility risk parity"
          >
            Size Position ⚖️
          </button>
          <button
            onClick={() => openInspector('market_structure_smc', { symbol: d.symbol })}
            className="px-2.5 py-1 rounded bg-panel hover:bg-elevated border border-border text-amber hover:text-amber/90 text-xs font-ui transition-colors cursor-pointer"
          >
            SMC Blueprint →
          </button>
        </div>

        <button
          onClick={() => {
            window.dispatchEvent(new CustomEvent('close-all-modals'))
            sendDraft(`analyze ${d.symbol}`)
          }}
          className="px-3 py-1 rounded bg-amber hover:bg-amber/90 text-black font-ui font-bold text-xs transition-colors cursor-pointer shadow-xs"
          title="Run Multi-Agent AI Debate"
        >
          AI Multi-Agent Debate 🤖
        </button>
      </div>
    </div>
  )
}
