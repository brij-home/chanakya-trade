import QuoteCard          from '../Cards/QuoteCard'
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


export default function Message({ message }) {
  const { role, text, cardType, data } = message

  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-lg bg-elevated border border-border rounded-xl px-4 py-2.5
                        text-text text-sm font-mono">
          {text}
        </div>
      </div>
    )
  }

  if (role === 'error') return <ErrorCard text={text} />

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
    case 'lifecycle':
    case 'trade_lifecycle':
    case 'trailing_sl':        return <PositionTrackerCard data={data} />
    case 'top_conviction':
    case 'conviction':
    case 'top10':
    case 'radar':              return <HighConvictionCard data={data} />
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

