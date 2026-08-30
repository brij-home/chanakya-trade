import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const PERSONA_ICONS = {
  buffett: '🏛️',
  jhunjhunwala: '🐂',
  lynch: '🛍️',
  soros: '🌐',
  munger: '🧠',
  forensic: '🛡️',
  minervini: '🚀',
  wyckoff: '📊',
  oneil: '📈',
  taleb: '🎲',
  kedia: '💎',
  simons: '🔢',
  smc: '🎯',
}

const PERSONA_STYLES = {
  buffett: 'Moat & Compounding',
  jhunjhunwala: 'India Growth & Leverage',
  lynch: 'GARP & Everyday Moats',
  soros: 'Reflexivity & Macro',
  munger: 'Latticework & Quality',
  forensic: 'Forensic Accounting & Red Flags',
  minervini: 'SEPA & VCP Breakouts',
  wyckoff: 'Volume Spread Analysis (VSA)',
  oneil: 'CAN SLIM Momentum',
  taleb: 'Antifragility & Convexity',
  kedia: 'SMILE Indian Multibaggers',
  simons: 'Statistical Arbitrage',
  smc: 'ICT Liquidity & Order Blocks',
}

export default function PersonaTrackRecordCard() {
  const [records, setRecords] = useState([])
  const [loading, setLoading] = useState(false)
  const [sortBy, setSortBy] = useState('win_rate_desc')
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)

  const fetchTrackRecords = async () => {
    setLoading(true)
    try {
      const res = await call('/skills/persona/track_records')
      if (res?.data?.track_records) {
        setRecords(res.data.track_records)
      }
    } catch (err) {
      console.error('Failed to load persona track records:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTrackRecords()
  }, [])

  const sortedRecords = [...(records || [])].sort((a, b) => {
    if (sortBy === 'win_rate_desc') return (b.win_rate || 0) - (a.win_rate || 0)
    if (sortBy === 'r_desc') return (b.compound_r || 0) - (a.compound_r || 0)
    if (sortBy === 'weight_desc') return (b.dynamic_weight_multiplier || 0) - (a.dynamic_weight_multiplier || 0)
    return (a?.name || '').localeCompare(b?.name || '')
  })

  return (
    <div className="bg-elevated/90 border border-border/80 rounded-2xl p-5 max-w-3xl w-full space-y-4 font-mono shadow-md backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber/15 border border-amber/30 flex items-center justify-center text-xl">
            🏆
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-text font-ui">AI Persona Accuracy & Dynamic Weighting Matrix</h3>
              <span className="text-[10px] bg-amber/15 text-amber border border-amber/30 px-2 py-0.5 rounded-full font-bold">
                13 Specialists
              </span>
            </div>
            <p className="text-xs text-muted font-ui">
              Self-evolving empirical track records, Brier calibration scores, and real-time council vote weighting
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="bg-panel border border-border/60 rounded-lg px-2.5 py-1 text-xs text-text font-ui focus:outline-hidden cursor-pointer"
          >
            <option value="win_rate_desc">Sort: Highest Win Rate</option>
            <option value="r_desc">Sort: Highest Compound R</option>
            <option value="weight_desc">Sort: Dynamic Weight Multiplier</option>
          </select>
          <button
            onClick={fetchTrackRecords}
            disabled={loading}
            className="p-1.5 bg-panel hover:bg-elevated border border-border rounded-lg text-xs text-text transition-colors cursor-pointer"
            title="Refresh track records"
          >
            <span className={loading ? 'animate-spin block' : 'block'}>🔄</span>
          </button>
        </div>
      </div>

      {/* Accuracy Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {sortedRecords.map((p) => {
          const icon = PERSONA_ICONS[p.persona_id] || '🏛️'
          const style = PERSONA_STYLES[p.persona_id] || 'Quantitative Analysis'
          const isHighWeight = p.dynamic_weight_multiplier >= 1.15

          return (
            <div
              key={p.persona_id}
              className="bg-panel/75 hover:bg-panel border border-border/60 hover:border-amber/40 rounded-xl p-3.5 space-y-2.5 transition-all group"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <span className="text-2xl p-1.5 bg-elevated rounded-lg border border-border/50">
                    {icon}
                  </span>
                  <div>
                    <h4 className="text-xs font-bold text-text font-ui group-hover:text-amber transition-colors">
                      {p.name}
                    </h4>
                    <p className="text-[10px] text-muted font-ui">{style}</p>
                  </div>
                </div>

                <div className="text-right">
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                      isHighWeight
                        ? 'bg-amber/15 text-amber border-amber/30 font-extrabold'
                        : 'bg-elevated text-muted border-border/60'
                    }`}
                  >
                    ⚖️ {p.dynamic_weight_multiplier}x Weight
                  </span>
                </div>
              </div>

              {/* Accuracy Bars & R-Multiple */}
              <div className="grid grid-cols-3 gap-2 bg-elevated/70 p-2 rounded-lg border border-border/40 text-xs font-mono">
                <div>
                  <span className="text-[10px] text-muted uppercase font-ui">Win Rate</span>
                  <p className="text-xs font-bold text-green mt-0.5">{p.win_rate}%</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted uppercase font-ui">Payoff</span>
                  <p className="text-xs font-bold text-amber mt-0.5">+{p.compound_r}R</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted uppercase font-ui">Brier Score</span>
                  <p className="text-xs font-bold text-cyan mt-0.5">{p.brier_score}</p>
                </div>
              </div>

              {/* Sector Affinity Tags & Consultation Button */}
              <div className="flex items-center justify-between gap-2 pt-1 border-t border-border/30">
                <div className="flex flex-wrap gap-1">
                  {Object.keys(p.sector_affinity || {}).slice(0, 2).map((sec) => (
                    <span
                      key={sec}
                      className="text-[9px] bg-panel text-muted/90 px-1.5 py-0.5 rounded border border-border/40 font-ui"
                    >
                      {sec}
                    </span>
                  ))}
                </div>

                <button
                  onClick={() => {
                    sendDraft(`persona ${p.persona_id} NIFTY`, { autoSubmit: true, showDashboard: false })
                  }}
                  className="px-2.5 py-1 rounded bg-amber/15 hover:bg-amber hover:text-black border border-amber/30 text-amber text-[10px] font-ui font-bold transition-all cursor-pointer shadow-xs"
                >
                  Consult Mind →
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
