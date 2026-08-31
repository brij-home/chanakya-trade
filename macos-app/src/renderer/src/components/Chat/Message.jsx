import { useState, useCallback } from 'react'
import { useChatStore } from '../../store/chatStore'
import AnalysisCard       from '../Cards/AnalysisCard'
import StreamingAnalysisCard from '../Cards/StreamingAnalysisCard'
import BacktestCard       from '../Cards/BacktestCard'
import FlowsCard          from '../Cards/FlowsCard'
import MorningBriefCard   from '../Cards/MorningBriefCard'
import HoldingsCard       from '../Cards/HoldingsCard'
import MarkdownCard       from '../Cards/MarkdownCard'
import ErrorCard          from '../Cards/ErrorCard'
import FundsCard          from '../Cards/FundsCard'
import ProfileCard        from '../Cards/ProfileCard'
import OrdersCard         from '../Cards/OrdersCard'
import AlertsCard         from '../Cards/AlertsCard'
import OICard             from '../Cards/OICard'
import PatternsCard       from '../Cards/PatternsCard'
import GreeksCard         from '../Cards/GreeksCard'
import ScanCard           from '../Cards/ScanCard'
import DealsCard          from '../Cards/DealsCard'
import IVSmileCard        from '../Cards/IVSmileCard'
import GEXCard            from '../Cards/GEXCard'
import DeltaHedgeCard     from '../Cards/DeltaHedgeCard'
import RiskReportCard     from '../Cards/RiskReportCard'
import WalkForwardCard    from '../Cards/WalkForwardCard'
import WhatIfCard         from '../Cards/WhatIfCard'
import StrategyCard       from '../Cards/StrategyCard'
import DriftCard          from '../Cards/DriftCard'
import PairsCard          from '../Cards/PairsCard'
import MemoryCard         from '../Cards/MemoryCard'
import AuditCard          from '../Cards/AuditCard'
import TelegramCard       from '../Cards/TelegramCard'
import ProviderCard       from '../Cards/ProviderCard'
import PayoffSimulatorCard from '../Cards/PayoffSimulatorCard'
import RRGCard            from '../Cards/RRGCard'
import ForensicCard       from '../Cards/ForensicCard'
import PositionSizerCard  from '../Cards/PositionSizerCard'
import FunnelCard         from '../Cards/FunnelCard'
import MarketStructureCard from '../Cards/MarketStructureCard'
import MultibaggerCard from '../Cards/MultibaggerCard'
import PositionTrackerCard from '../Cards/PositionTrackerCard'
import HighConvictionCard from '../Cards/HighConvictionCard'
import BigMoveCard from '../Cards/BigMoveCard'
import CouncilCard from '../Cards/CouncilCard'
import PersonaCard from '../Cards/PersonaCard'
import DefinedRiskSpreadCard from '../Cards/DefinedRiskSpreadCard'
import MagicTrendCard from '../Cards/MagicTrendCard'
import ThematicBasketsCard from '../Cards/ThematicBasketsCard'
import PortfolioDoctorCard from '../Cards/PortfolioDoctorCard'
import ErrorBoundary from '../ErrorBoundary'

function renderCardContent(cardType, data) {
  switch (cardType) {
    case 'quote':              return <QuoteCard data={data} />
    case 'analysis':           return <AnalysisCard data={data} />
    case 'streaming_analysis': return <StreamingAnalysisCard data={data} />
    case 'backtest':           return <BacktestCard data={data} />
    case 'flows':              return <FlowsCard data={data} />
    case 'morning_brief':      return <MorningBriefCard data={data} />
    case 'holdings':           return <HoldingsCard data={data} />
    case 'funds':              return <FundsCard data={data} />
    case 'profile':            return <ProfileCard data={data} />
    case 'orders':             return <OrdersCard data={data} />
    case 'alerts':             return <AlertsCard data={data} />
    case 'oi':                 return <OICard data={data} />
    case 'patterns':           return <PatternsCard data={data} />
    case 'greeks':             return <GreeksCard data={data} />
    case 'scan':               return <ScanCard data={data} />
    case 'deals':              return <DealsCard data={data} />
    case 'iv_smile':           return <IVSmileCard data={data} />
    case 'gex':                return <GEXCard data={data} />
    case 'delta_hedge':        return <DeltaHedgeCard data={data} />
    case 'risk_report':        return <RiskReportCard data={data} />
    case 'walkforward':        return <WalkForwardCard data={data} />
    case 'whatif':             return <WhatIfCard data={data} />
    case 'strategy':           return <StrategyCard data={data} />
    case 'payoff':
    case 'payoff_sim':         return <PayoffSimulatorCard initialSymbol={data?.symbol || 'NIFTY'} initialSpot={data?.spot_price || data?.last_price || 24000} />
    case 'rrg':
    case 'sector_rotation':    return <RRGCard data={data} />
    case 'forensic':
    case 'forensics':          return <ForensicCard data={data} />
    case 'size':
    case 'position_size':      return <PositionSizerCard data={data} />
    case 'funnel':
    case 'smart_funnel':       return <FunnelCard data={data} />
    case 'structure':
    case 'market_structure':
    case 'smc':                return <MarketStructureCard data={data} />
    case 'multibagger':
    case 'vcp':
    case 'stage2':             return <MultibaggerCard data={data} />
    case 'magic_trend':
    case '3axis':
    case 'super_investor':
    case 'magictrend':         return <MagicTrendCard data={data} />
    case 'thematic_baskets':
    case 'baskets':
    case '100baggers':
    case 'lynch_garp':
    case 'jhunjhunwala_capex':
    case 'canslim_basket':     return <ThematicBasketsCard data={data} />
    case 'portfolio_doctor':
    case 'portfolio_health':
    case 'doctor':             return <PortfolioDoctorCard data={data} />
    case 'lifecycle':
    case 'trade_lifecycle':
    case 'trailing_sl':        return <PositionTrackerCard data={data} />
    case 'top_conviction':
    case 'conviction':
    case 'top10':
    case 'radar':              return <HighConvictionCard data={data} />
    case 'council':
    case 'persona_council':    return <CouncilCard data={data} />
    case 'persona':
    case 'persona_analyze':    return <PersonaCard data={data} />
    case 'spread':
    case 'spreads':
    case 'defined_risk_spread':
    case 'defined_risk_spreads': return <DefinedRiskSpreadCard data={data} />
    case 'big_move':
    case 'bigmove':
    case 'squeeze':            return <BigMoveCard data={data} />
    case 'drift':              return <DriftCard data={data} />
    case 'pairs':              return <PairsCard data={data} />
    case 'memory':             return <MemoryCard data={data} />
    case 'audit':              return <AuditCard data={data} />
    case 'telegram':           return <TelegramCard data={data} />
    case 'provider':           return <ProviderCard data={data} />
    case 'markdown':
    default:                   return <MarkdownCard data={data} />
  }
}


function MessageActions({ text, onRerun }) {
  const [copied, setCopied] = useState(false)
  const [thumbed, setThumbed] = useState(null) // 'up' | 'down' | null

  const handleCopy = useCallback(() => {
    try {
      navigator.clipboard.writeText(text || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {}
  }, [text])

  return (
    <div
      className="message-actions flex items-center gap-1 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150"
      style={{ fontSize: '11px' }}
    >
      {/* Copy */}
      <button
        title="Copy message"
        onClick={handleCopy}
        className="flex items-center gap-1 px-2 py-0.5 rounded-md transition-all cursor-pointer"
        style={{
          background: copied ? 'rgba(0,214,143,0.15)' : 'var(--color-elevated)',
          border: '1px solid var(--color-border)',
          color: copied ? 'var(--color-emerald)' : 'var(--color-muted)',
        }}
      >
        {copied ? '✓' : '📋'}
      </button>

      {/* Thumbs up */}
      <button
        title="Helpful"
        onClick={() => setThumbed(thumbed === 'up' ? null : 'up')}
        className="px-2 py-0.5 rounded-md transition-all cursor-pointer"
        style={{
          background: thumbed === 'up' ? 'rgba(0,214,143,0.15)' : 'var(--color-elevated)',
          border: `1px solid ${thumbed === 'up' ? 'rgba(0,214,143,0.4)' : 'var(--color-border)'}`,
          color: thumbed === 'up' ? 'var(--color-emerald)' : 'var(--color-muted)',
        }}
      >
        👍
      </button>

      {/* Thumbs down */}
      <button
        title="Not helpful"
        onClick={() => setThumbed(thumbed === 'down' ? null : 'down')}
        className="px-2 py-0.5 rounded-md transition-all cursor-pointer"
        style={{
          background: thumbed === 'down' ? 'rgba(255,79,123,0.15)' : 'var(--color-elevated)',
          border: `1px solid ${thumbed === 'down' ? 'rgba(255,79,123,0.4)' : 'var(--color-border)'}`,
          color: thumbed === 'down' ? 'var(--color-rose)' : 'var(--color-muted)',
        }}
      >
        👎
      </button>

      {/* Re-run */}
      {onRerun && (
        <button
          title="Re-run analysis"
          onClick={onRerun}
          className="px-2 py-0.5 rounded-md transition-all cursor-pointer"
          style={{
            background: 'var(--color-elevated)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-muted)',
          }}
        >
          🔄
        </button>
      )}
    </div>
  )
}

export default function Message({ message }) {
  const { role, text, cardType, data } = message
  const sendDraft = useChatStore((s) => s.sendDraft)

  if (role === 'user') {
    return (
      <div className="flex justify-end group">
        <div
          className="max-w-lg bg-elevated border border-border rounded-xl px-4 py-2.5 text-text text-sm font-mono relative"
        >
          {text}
          {/* Copy action for user messages (top-right on hover) */}
          <CopyBubble text={text} />
        </div>
      </div>
    )
  }

  if (role === 'error') return <ErrorCard text={text} />

  const handleRerun = text
    ? () => sendDraft(text, { autoSubmit: true })
    : undefined

  return (
    <div className="group">
      <ErrorBoundary title={cardType ? `${cardType.toUpperCase()} Card` : 'Message Content'}>
        {renderCardContent(cardType, data)}
      </ErrorBoundary>
      <MessageActions text={text} onRerun={handleRerun} />
    </div>
  )
}

/* Tiny inline copy bubble for user messages */
function CopyBubble({ text }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      title="Copy"
      onClick={() => {
        try { navigator.clipboard.writeText(text || '') } catch {}
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="absolute -top-2 -right-2 w-6 h-6 flex items-center justify-center rounded-full opacity-0 group-hover:opacity-100 transition-opacity text-[10px] cursor-pointer"
      style={{
        background: 'var(--color-elevated)',
        border: '1px solid var(--color-border)',
        color: copied ? 'var(--color-emerald)' : 'var(--color-muted)',
      }}
    >
      {copied ? '✓' : '⎘'}
    </button>
  )
}

