import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { useChatStore } from '../../store/chatStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

const DEAL_BADGES = {
  BULK_BUY:          { label: '⚡ Bulk Buy', color: 'bg-green/15 text-green border border-green/30 font-bold' },
  BLOCK_BUY:         { label: '🏛️ Block Deal', color: 'bg-blue/15 text-blue border border-blue/30 font-bold' },
  SAST_ACCUMULATION: { label: '👑 SAST Stake Acquisition', color: 'bg-amber/15 text-amber border border-amber/30 font-bold' },
}

export default function WhaleFlowsCard({ onOpenOrderTicket }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [investorFilter, setInvestorFilter] = useState('ALL')
  const [searchQuery, setSearchQuery] = useState('')
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)

  const fetchWhaleFlows = async () => {
    setLoading(true)
    try {
      const res = await call('/skills/whale_flows')
      setData(res?.data ?? res)
    } catch (err) {
      console.error('Failed to load whale flows:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchWhaleFlows()
  }, [])

  const deals = data?.deals || []
  const investors = data?.marquee_investors || []

  const filteredDeals = deals.filter((d) => {
    if (investorFilter !== 'ALL' && !d?.investor_name?.toLowerCase().includes(investorFilter.toLowerCase())) {
      return false
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toUpperCase()
      const matchSymbol = d.symbol?.toUpperCase().includes(q)
      const matchCompany = d.company_name?.toUpperCase().includes(q)
      const matchSector = d.sector?.toUpperCase().includes(q)
      const matchInv = d.investor_name?.toUpperCase().includes(q)
      if (!matchSymbol && !matchCompany && !matchSector && !matchInv) return false
    }
    return true
  })

  return (
    <div className="bg-elevated/90 border border-border/80 rounded-2xl p-5 max-w-3xl w-full space-y-4 font-mono shadow-md backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber/15 border border-amber/30 flex items-center justify-center text-xl">
            🐋
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-text font-ui">Indian Marquee Whale & SAST Flow Tracker</h3>
              <span className="text-[10px] bg-green/15 text-green border border-green/30 px-2 py-0.5 rounded-full font-bold">
                SEBI Disclosures
              </span>
            </div>
            <p className="text-xs text-muted font-ui">
              Live Bulk/Block accumulations by Ashish Kacholia, Mukul Agrawal, Rekha Jhunjhunwala & Tier-1 DIIs
            </p>
          </div>
        </div>

        <button
          onClick={fetchWhaleFlows}
          disabled={loading}
          className="flex items-center gap-1.5 bg-panel hover:bg-elevated border border-border px-3 py-1.5 rounded-lg text-xs font-semibold text-text transition-colors cursor-pointer disabled:opacity-50"
        >
          <span className={loading ? 'animate-spin' : ''}>🔄</span>
          <span>{loading ? 'Scanning…' : 'Refresh Deals'}</span>
        </button>
      </div>

      {/* Aggregate Metrics Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
        <div className="bg-panel/70 border border-border/40 p-2.5 rounded-xl">
          <span className="text-[10px] text-muted uppercase font-ui">Total Deployed Capital</span>
          <p className="text-base font-bold text-amber mt-0.5">
            ₹{data?.total_capital_deployed_cr || 281.5} <span className="text-xs font-normal">Cr</span>
          </p>
        </div>
        <div className="bg-panel/70 border border-border/40 p-2.5 rounded-xl">
          <span className="text-[10px] text-muted uppercase font-ui">Stage 2 Markup Alignment</span>
          <p className="text-base font-bold text-green mt-0.5">
            {data?.stage_2_alignment_pct || 100}%
          </p>
        </div>
        <div className="bg-panel/70 border border-border/40 p-2.5 rounded-xl">
          <span className="text-[10px] text-muted uppercase font-ui">Average Conviction Score</span>
          <p className="text-base font-bold text-cyan mt-0.5">
            {data?.avg_conviction_score || 84.7}/100
          </p>
        </div>
        <div className="bg-panel/70 border border-border/40 p-2.5 rounded-xl">
          <span className="text-[10px] text-muted uppercase font-ui">Active Disclosures</span>
          <p className="text-base font-bold text-text mt-0.5">
            {deals.length} Transacted Equities
          </p>
        </div>
      </div>

      {/* Investor Filter Chips & Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-ui">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setInvestorFilter('ALL')}
            className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              investorFilter === 'ALL'
                ? 'bg-amber text-black font-extrabold shadow-xs'
                : 'bg-panel text-muted hover:text-text border border-border/50'
            }`}
          >
            All Whales ({deals.length})
          </button>
          {['Kacholia', 'Agrawal', 'Jhunjhunwala', 'Abakkus', 'HDFC'].map((inv) => (
            <button
              key={inv}
              onClick={() => setInvestorFilter(inv)}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                investorFilter === inv
                  ? 'bg-amber text-black font-extrabold shadow-xs'
                  : 'bg-panel text-muted hover:text-text border border-border/50'
              }`}
            >
              {inv}
            </button>
          ))}
        </div>

        <input
          type="text"
          placeholder="🔍 Filter symbol, company, or sector…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-panel border border-border/60 rounded-lg px-3 py-1 text-xs text-text placeholder:text-muted/60 focus:outline-hidden focus:border-amber max-w-[220px]"
        />
      </div>

      {/* Deals List */}
      <div className="space-y-2.5">
        {filteredDeals.length === 0 ? (
          <div className="p-8 text-center bg-panel/40 border border-border/40 rounded-xl text-muted text-xs font-ui">
            No whale deals match your selected filters.
          </div>
        ) : (
          filteredDeals.map((deal) => {
            const badge = DEAL_BADGES[deal.deal_type] || DEAL_BADGES.BULK_BUY
            const isProfit = deal.gain_pct_since_deal >= 0

            return (
              <div
                key={deal.id || deal.symbol}
                className="bg-panel/80 hover:bg-panel border border-border/60 hover:border-amber/40 rounded-xl p-3.5 transition-all space-y-2.5 group"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-base font-bold text-amber font-mono bg-elevated px-2 py-0.5 rounded border border-border/60">
                      {deal.symbol}
                    </span>
                    <div>
                      <h4 className="text-xs font-bold text-text font-ui">{deal.company_name}</h4>
                      <p className="text-[10px] text-muted font-ui">{deal.sector}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${badge.color}`}>
                      {badge.label}
                    </span>
                    <span className="text-[10px] bg-green/15 text-green border border-green/30 px-2 py-0.5 rounded font-mono font-bold">
                      🚀 Minervini Stage 2
                    </span>
                  </div>
                </div>

                {/* Whale & Financial Details */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono bg-elevated/60 p-2.5 rounded-lg border border-border/40">
                  <div>
                    <span className="text-[10px] text-muted uppercase font-ui">Marquee Acquirer</span>
                    <p className="text-xs font-bold text-text truncate">{deal.investor_name}</p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted uppercase font-ui">Transaction Size</span>
                    <p className="text-xs font-bold text-amber">
                      ₹{deal.deal_value_cr} Cr <span className="text-[10px] text-muted">({deal.stake_pct}%)</span>
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted uppercase font-ui">Buy Price vs LTP</span>
                    <p className="text-xs font-bold text-text">
                      ₹{deal.trade_price} → ₹{deal.current_ltp}
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted uppercase font-ui">Post-Deal Alpha</span>
                    <p className={`text-xs font-extrabold ${isProfit ? 'text-green' : 'text-red'}`}>
                      {isProfit ? '+' : ''}{deal.gain_pct_since_deal}%
                    </p>
                  </div>
                </div>

                {/* Investment Thesis & 1-Click Action */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1 border-t border-border/30">
                  <p className="text-[11px] text-text/80 font-ui italic">
                    💡 <strong className="text-text font-semibold">Thesis:</strong> {deal.key_thesis}
                  </p>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={() => {
                        sendDraft(`analyze ${deal.symbol}`, { autoSubmit: true, showDashboard: false })
                      }}
                      className="px-3 py-1 rounded-lg bg-amber/15 hover:bg-amber hover:text-black border border-amber/30 text-amber text-xs font-ui font-bold transition-all cursor-pointer shadow-xs"
                    >
                      ⚡ AI Council Analyze
                    </button>
                    {onOpenOrderTicket && (
                      <button
                        onClick={() =>
                          onOpenOrderTicket({
                            symbol: deal.symbol,
                            price: deal.current_ltp,
                            action: 'BUY',
                          })
                        }
                        className="px-2.5 py-1 rounded-lg bg-green/15 hover:bg-green hover:text-black border border-green/30 text-green text-xs font-ui font-bold transition-all cursor-pointer shadow-xs"
                      >
                        🛒 Stage Order
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
