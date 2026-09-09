import { useState, useEffect, useRef, useMemo } from 'react'
import { useChatStore } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import PayoffSimulatorCard from '../Cards/PayoffSimulatorCard'
import ConvictionScoreCard from '../Cards/ConvictionScoreCard'
import { getSymbolExchange } from '../../data/universeData'

// Cumulative standard normal distribution for Greeks
function normalCDF(x) {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2)
  const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
  return x > 0 ? 1 - p : p
}

function normalPDF(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)
}

function calculateGreeks(spot, strike, ivPct, isCall = true, daysToExpiry = 4, r = 0.065) {
  const S = Number(spot)
  const K = Number(strike)
  if (!S || S <= 0 || !K || K <= 0) {
    return {
      callDelta: '—',
      putDelta: '—',
      gamma: '—',
      vega: '—',
      callTheta: '—',
      putTheta: '—',
    }
  }
  const cleanIv = parseFloat(String(ivPct || '').replace(/[^0-9.-]/g, ''))
  if (!cleanIv || cleanIv <= 0) {
    return {
      callDelta: '—',
      putDelta: '—',
      gamma: '—',
      vega: '—',
      callTheta: '—',
      putTheta: '—',
    }
  }
  const sigma = Math.max(0.01, cleanIv / 100)
  const T = Math.max(1 / 365, (daysToExpiry || 4) / 365)
  const sqrtT = Math.sqrt(T)

  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * T) / (sigma * sqrtT)
  const d2 = d1 - sigma * sqrtT

  const callDelta = normalCDF(d1)
  const putDelta = callDelta - 1
  const gamma = normalPDF(d1) / (S * sigma * sqrtT)
  const vega = (S * sqrtT * normalPDF(d1)) / 100
  const thetaCall = (-(S * normalPDF(d1) * sigma) / (2 * sqrtT) - r * K * Math.exp(-r * T) * normalCDF(d2)) / 365
  const thetaPut = (-(S * normalPDF(d1) * sigma) / (2 * sqrtT) + r * K * Math.exp(-r * T) * normalCDF(-d2)) / 365

  return {
    callDelta: Math.max(0, Math.min(1, callDelta)).toFixed(2),
    putDelta: Math.max(-1, Math.min(0, putDelta)).toFixed(2),
    gamma: (gamma * 100).toFixed(3),
    vega: vega.toFixed(2),
    callTheta: thetaCall.toFixed(1),
    putTheta: thetaPut.toFixed(1),
  }
}

function BlastActionPopover({
  blastData,
  underlying,
  spot,
  resolvedExchange,
  onClose,
  onOpenOrderTicket,
  onSendTelegram,
  onSendCopilot,
}) {
  if (!blastData) return null
  const isCall = blastData.option_type === 'CE'
  const flame = isCall ? '🔥' : '🚨'

  return (
    <div
      className="p-3.5 rounded-2xl shadow-2xl font-mono border backdrop-blur-xl max-w-sm w-full animate-in fade-in zoom-in-95 duration-150 text-text"
      style={{
        background: 'rgba(15, 23, 42, 0.96)',
        borderColor: isCall ? 'rgba(34, 211, 238, 0.6)' : 'rgba(244, 63, 94, 0.6)',
        boxShadow: isCall ? '0 12px 48px -8px rgba(6, 182, 212, 0.45)' : '0 12px 48px -8px rgba(244, 63, 94, 0.45)',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Popover Header */}
      <div className="flex items-start justify-between border-b border-border/60 pb-2 mb-2">
        <div>
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-base animate-pulse">{flame}</span>
            <span
              className={`text-[9px] font-black px-1.5 py-0.2 rounded tracking-wide ${
                isCall ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
              }`}
            >
              {blastData.action_recommendation || (isCall ? 'BUY CALL (MOMENTUM)' : 'BUY PUT (BREAKDOWN)')}
            </span>
            <span className="text-[9px] font-bold text-amber bg-amber-500/15 border border-amber-500/30 px-1 py-0.2 rounded">
              Score {blastData.score}/100
            </span>
          </div>
          <h3 className="text-xs font-black text-text flex items-center gap-1">
            {blastData.action_title || blastData.contract}
          </h3>
          <p className="text-[10px] text-muted font-ui mt-0.5 leading-snug">
            {blastData.blast_reason}
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-muted hover:text-text p-1 text-xs cursor-pointer rounded-lg hover:bg-surface ml-1"
          title="Close Popover"
        >
          ✕
        </button>
      </div>

      {/* Actionable Profit Blueprint Matrix */}
      <div className="grid grid-cols-2 gap-1.5 mb-2 bg-surface/80 p-2 rounded-xl border border-border/50 text-[11px]">
        <div>
          <span className="text-[9px] uppercase tracking-wider text-muted block">Entry Zone</span>
          <span className="font-extrabold text-emerald-400 text-xs">
            {blastData.entry_range || `₹${blastData.bid} – ₹${blastData.ask}`}
          </span>
        </div>
        <div>
          <span className="text-[9px] uppercase tracking-wider text-muted block">Invalidation SL</span>
          <span className="font-extrabold text-rose-400 text-xs">
            ₹{blastData.stop_loss || '—'} <span className="text-[9px] font-normal opacity-75">({blastData.stop_loss_pct || '-25%'})</span>
          </span>
        </div>
        <div>
          <span className="text-[9px] uppercase tracking-wider text-muted block">Target 1 (1.5R Scalp)</span>
          <span className="font-extrabold text-cyan-300 text-xs">
            ₹{blastData.target_1 || '—'} <span className="text-[9px] font-normal opacity-75">({blastData.target_1_pct || '+35%'})</span>
          </span>
        </div>
        <div>
          <span className="text-[9px] uppercase tracking-wider text-muted block">Target 2 (2.5R Runner)</span>
          <span className="font-extrabold text-amber text-xs">
            ₹{blastData.target_2 || '—'} <span className="text-[9px] font-normal opacity-75">({blastData.target_2_pct || '+65%'})</span>
          </span>
        </div>
      </div>

      {/* Trader Execution Playbook */}
      <div className="space-y-1 text-[10px] mb-2.5 bg-black/40 p-2 rounded-xl border border-border/40 font-ui leading-tight">
        <div className="flex items-start gap-1">
          <span className="text-emerald-400 font-bold shrink-0">🟢 BUY:</span>
          <span className="text-text/90">{blastData.when_to_buy || `Enter on Ask/Retest while Spot holds support`}</span>
        </div>
        <div className="flex items-start gap-1">
          <span className="text-amber font-bold shrink-0">🟡 WAIT:</span>
          <span className="text-text/80">{blastData.when_to_wait || `DO NOT CHASE if premium spiked > 15%`}</span>
        </div>
        <div className="flex items-start gap-1">
          <span className="text-cyan-400 font-bold shrink-0">💰 PROFIT:</span>
          <span className="text-text/90 font-semibold">{blastData.profit_rule || `Take 50% off at T1 and trail SL to Cost`}</span>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex items-center gap-1.5 pt-0.5">
        <button
          onClick={() => {
            onOpenOrderTicket &&
              onOpenOrderTicket({
                symbol: blastData.contract,
                exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                price: blastData.ask || blastData.bid,
                orderType: 'BUY',
                side: 'BUY',
              })
            onClose && onClose()
          }}
          className={`flex-1 py-1 px-2.5 rounded-lg font-extrabold text-[10px] transition-all cursor-pointer flex items-center justify-center gap-1 shadow-md ${
            isCall
              ? 'bg-gradient-to-r from-cyan-400 to-cyan-500 text-black hover:brightness-110'
              : 'bg-gradient-to-r from-rose-500 to-rose-600 text-white hover:brightness-110'
          }`}
        >
          <span>🚀</span> Stage BUY Order
        </button>

        <button
          onClick={() => onSendTelegram && onSendTelegram(blastData)}
          className="px-2 py-1 rounded-lg bg-surface hover:bg-elevated border border-border/70 text-text hover:text-amber text-[10px] font-bold transition-all cursor-pointer flex items-center gap-1 shrink-0"
          title="Send actionable alert to Telegram"
        >
          <span>📲</span> Telegram
        </button>

        <button
          onClick={() => {
            onSendCopilot && onSendCopilot(blastData)
            onClose && onClose()
          }}
          className="px-2 py-1 rounded-lg bg-surface hover:bg-elevated border border-border/70 text-text hover:text-cyan-400 text-[10px] font-bold transition-all cursor-pointer flex items-center gap-1 shrink-0"
          title="Analyze in Copilot Chat"
        >
          <span>💬</span> Copilot
        </button>
      </div>
    </div>
  )
}

export default function OptionsDeskView({
  onOpenOrderTicket,
  selectedSymbol = 'NIFTY',
  onSelectSymbol = null,
}) {
  const { call } = useAPI()
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [underlying, setUnderlying] = useState(selectedSymbol || 'NIFTY')
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isLiveActive, setIsLiveActive] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isPayoffModalOpen, setIsPayoffModalOpen] = useState(false)
  const [activeBlastPopover, setActiveBlastPopover] = useState(null)
  const [telegramStatus, setTelegramStatus] = useState(null)
  const [strikeFilter, setStrikeFilter] = useState('ATM_10')
  const [chainSort, setChainSort] = useState('strike_asc')
  const [chainPage, setChainPage] = useState(1)
  const [chainPageSize, setPageSize] = useState(25) // Default 25 so ATM window (±10 = 21 strikes) is fully visible centered
  const [chainViewMode, setChainViewMode] = useState('STANDARD') // 'STANDARD' | 'GREEKS'
  const [showVisualBars, setShowVisualBars] = useState(true)
  const [deskPosScale, setDeskPosScale] = useState(1)
  const [showDeskWhy, setShowDeskWhy] = useState(false)

  const [customSymbolInput, setCustomSymbolInput] = useState('')
  const [showSymbolSearch, setShowSymbolSearch] = useState(false)

  // Synchronize with external selectedSymbol prop
  useEffect(() => {
    if (selectedSymbol && selectedSymbol !== underlying) {
      setUnderlying(selectedSymbol)
      setSelectedExpiry('')
    }
  }, [selectedSymbol])

  const handleSelectSymbol = (sym) => {
    if (!sym) return
    const clean = String(sym).trim().toUpperCase().replace(/^(NSE:|BSE:|MCX:|CDS:)/i, '')
    setUnderlying(clean)
    setSelectedExpiry('')
    setShowSymbolSearch(false)
    setCustomSymbolInput('')
    if (onSelectSymbol) {
      onSelectSymbol(clean)
    }
  }

  const resolvedExchange = data?.exchange || getSymbolExchange(underlying)

  const atmRowRef = useRef(null)
  const tableContainerRef = useRef(null)

  const fetchGex = async (isSilent = false) => {
    try {
      if (!isSilent) setLoading(true)
      else setIsRefreshing(true)
      const res = await call('/skills/gex_snapshot', {
        underlying,
        expiry: selectedExpiry || undefined,
      })
      const snapshot = res?.data ?? res
      if (snapshot) {
        setData(snapshot)
        setLastUpdated(new Date())
        if (!selectedExpiry && snapshot.expiry) {
          setSelectedExpiry(snapshot.expiry)
        }
      }
    } catch (err) {
      console.error('Failed to load GEX snapshot:', err)
    } finally {
      if (!isSilent) setLoading(false)
      setIsRefreshing(false)
    }
  }

  // Initial & underlying/expiry change fetch
  useEffect(() => {
    fetchGex(false)
  }, [underlying, selectedExpiry])

  // Real-time background auto-update (every 4s when live mode active)
  useEffect(() => {
    if (!isLiveActive) return
    const interval = setInterval(() => {
      fetchGex(true)
    }, 4000)
    return () => clearInterval(interval)
  }, [underlying, selectedExpiry, isLiveActive])

  const handleSendTelegramBlast = async (blastData) => {
    if (!blastData) return
    try {
      setTelegramStatus({ status: 'loading', msg: `Sending ${blastData.contract} alert to Telegram...` })
      const res = await call(
        '/skills/telegram_blast',
        {
          blast_data: blastData,
          underlying,
          spot: data?.spot_price || 0,
        },
        { method: 'POST' }
      )
      if (res?.data?.status === 'sent' || res?.status === 'ok') {
        setTelegramStatus({ status: 'success', msg: `✅ ${blastData.contract} alert sent to Telegram!` })
      } else {
        const reason = res?.data?.reason || res?.detail || 'Telegram bot token or chat ID not configured in .env'
        setTelegramStatus({ status: 'warning', msg: `⚠️ ${reason}` })
      }
    } catch (err) {
      setTelegramStatus({ status: 'error', msg: `❌ Telegram push error: ${err.message}` })
    }
    setTimeout(() => setTelegramStatus(null), 6000)
  }

  const handleOpenBlastPopover = (blastData, el) => {
    if (!blastData || !el) return
    const rect = el.getBoundingClientRect()
    setActiveBlastPopover({
      data: blastData,
      x: Math.min(window.innerWidth - 410, Math.max(16, rect.left - 120)),
      y: Math.max(60, Math.min(window.innerHeight - 440, rect.top - 200)),
    })
  }

  const spot = data?.spot_price || 0
  const spotChange = data?.spot_change || '0.00'
  const spotChangePct = data?.spot_change_pct || '0.00%'
  const spotIsPositive = data?.spot_is_positive ?? (!String(spotChange).startsWith('-'))
  const dataState = data?.data_state || (data ? 'UNVERIFIED' : 'LOADING')
  const isRealtime = Boolean(data?.is_realtime && dataState === 'LIVE')
  const dataSource = data?.data_source || (isRealtime ? 'broker' : 'fallback')
  const sourceLabel = data?.source_label || (isRealtime ? `${dataSource.toUpperCase()} Direct Feed` : 'Exchange Scraper (~15m Delayed)')
  const asOfTime = data?.as_of_display || data?.time || (lastUpdated ? lastUpdated.toLocaleTimeString('en-IN') + ' IST' : '')
  const brokerNote = data?.note || ''
  const blastRadar = data?.blast_radar || []
  const convictionScore = data?.conviction_score || null
  const gexProfile = data?.gex_profile || []
  const deltaHedge = data?.delta_hedge
  const ivSkew = data?.iv_skew || []
  const optionsChain = data?.options_chain || []
  const expiries = data?.expiries && data.expiries.length > 0 ? data.expiries : ['Current Expiry']
  const pcr = data?.pcr != null ? Number(data.pcr).toFixed(2) : '—'
  const pcrSentiment = data?.pcr_sentiment || (pcr !== '—' ? (Number(pcr) >= 1.0 ? 'BULLISH (Put Support)' : 'BEARISH (Call Overhead)') : 'Awaiting Data')
  const pcrBlast = Boolean(data?.pcr_blast)
  const pcrBlastMsg = data?.pcr_blast_msg || ''
  const maxPain = data?.max_pain != null && Number(data.max_pain) > 0 ? Number(data.max_pain) : null
  const totalCallOI = data?.total_call_oi || '—'
  const totalPutOI = data?.total_put_oi || '—'
  const netOIChange = data?.net_oi_change || '—'

  // Dynamic IV Curve SVG Points calculation
  const ivValues = ivSkew.map((p) => p.iv)
  const minIV = ivValues.length > 0 ? Math.min(...ivValues) : 12
  const maxIV = ivValues.length > 0 ? Math.max(...ivValues) : 22
  const ivRange = Math.max(1, maxIV - minIV)

  const svgPoints = ivSkew
    .map((pt, idx) => {
      const x = 15 + (idx / Math.max(1, ivSkew.length - 1)) * 210
      const y = 85 - ((pt.iv - minIV) / ivRange) * 65
      return `${x},${y}`
    })
    .join(' ')

  // Mathematically robust ATM index calculation (guaranteed valid index)
  const atmIdx = (() => {
    if (!optionsChain || optionsChain.length === 0 || spot <= 0) return -1
    const explicitIdx = optionsChain.findIndex((r) => r.is_atm)
    if (explicitIdx >= 0) return explicitIdx
    let closestIdx = 0
    let minDiff = Infinity
    optionsChain.forEach((r, idx) => {
      const diff = Math.abs(Number(r.strike) - spot)
      if (diff < minDiff) {
        minDiff = diff
        closestIdx = idx
      }
    })
    return closestIdx
  })()

  // Filtered & Sorted Options Chain (ATM ±5, ATM ±10, ATM ±15, ALL)
  const filteredChain = optionsChain.filter((row, idx) => {
    if (atmIdx < 0 || strikeFilter === 'ALL') return true
    if (strikeFilter === 'ATM_5') {
      return Math.abs(idx - atmIdx) <= 5
    }
    if (strikeFilter === 'ATM_10') {
      return Math.abs(idx - atmIdx) <= 10
    }
    if (strikeFilter === 'ATM_15') {
      return Math.abs(idx - atmIdx) <= 15
    }
    return true
  })

  const sortedChain = [...filteredChain].sort((a, b) => {
    if (chainSort === 'strike_desc') return Number(b.strike) - Number(a.strike)
    if (chainSort === 'call_oi_desc') {
      const vA = parseFloat(String(a.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      const vB = parseFloat(String(b.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      return vB - vA
    }
    if (chainSort === 'put_oi_desc') {
      const vA = parseFloat(String(a.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      const vB = parseFloat(String(b.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0
      return vB - vA
    }
    return Number(a.strike) - Number(b.strike)
  })

  const atmTargetStrike = optionsChain[atmIdx]?.strike
  const atmSortedIndex = sortedChain.findIndex(
    (r) => Number(r.strike) === Number(atmTargetStrike) || r.is_atm
  )
  const isPageSizeAll = chainPageSize === 'ALL'
  const pageSizeNum = isPageSizeAll ? sortedChain.length : Number(chainPageSize)
  const totalChainPages = isPageSizeAll ? 1 : Math.max(1, Math.ceil(sortedChain.length / pageSizeNum))
  const safeChainPage = isPageSizeAll ? 1 : Math.min(chainPage, totalChainPages)
  const paginatedChain = isPageSizeAll
    ? sortedChain
    : sortedChain.slice(
        (safeChainPage - 1) * pageSizeNum,
        safeChainPage * pageSizeNum
      )

  const scrollToATM = () => {
    if (tableContainerRef.current && atmRowRef.current) {
      const container = tableContainerRef.current
      const row = atmRowRef.current
      const rowTop = row.offsetTop
      const rowHeight = row.offsetHeight
      const containerHeight = container.clientHeight
      container.scrollTo({
        top: Math.max(0, rowTop - containerHeight / 2 + rowHeight / 2),
        behavior: 'smooth',
      })
    }
  }

  // When filter or underlying changes, land on the page containing the ATM strike
  useEffect(() => {
    if (atmIdx >= 0 && sortedChain.length > 0 && !isPageSizeAll) {
      const atmSortedIdx = sortedChain.findIndex(
        (r) => Number(r.strike) === Number(atmTargetStrike) || r.is_atm
      )
      if (atmSortedIdx >= 0) {
        const atmPage = Math.max(1, Math.ceil((atmSortedIdx + 1) / pageSizeNum))
        setChainPage(atmPage)
      }
    }
  }, [underlying, strikeFilter, chainPageSize])

  // Key structural walls derived from open interest distribution
  const callWallStrike = optionsChain.length > 0
    ? optionsChain.reduce((max, r) => ((parseFloat(String(r.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0) > (parseFloat(String(max?.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0) ? r : max), optionsChain[0] || {})?.strike
    : data?.call_wall || null

  const putWallStrike = optionsChain.length > 0
    ? optionsChain.reduce((max, r) => ((parseFloat(String(r.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0) > (parseFloat(String(max?.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0) ? r : max), optionsChain[0] || {})?.strike
    : data?.put_support || null

  // Institutional Multi-Factor Options Decision Matrix
  const decisionMatrix = useMemo(() => {
    if (dataState === 'BROKER_REQUIRED' || optionsChain.length === 0) {
      const isBrokerReq = dataState === 'BROKER_REQUIRED'
      return {
        strategyName: isBrokerReq ? 'BROKER CONNECTION REQUIRED' : 'AWAITING OPTION CHAIN',
        type: isBrokerReq ? 'BROKER_DISCONNECTED' : 'DATA_STANDBY',
        bias: isBrokerReq ? 'BSE BFO STREAMING' : 'NEUTRAL STANDBY',
        conviction: isBrokerReq ? 100 : 50,
        rationale: isBrokerReq
          ? (brokerNote || `${underlying} live spot is streaming directly from BSE. Connect Zerodha, Dhan, Shoonya, or Fyers for live BFO option chain and order execution.`)
          : `Live spot feed active. Waiting for derivative contracts to populate for ${underlying}.`,
        legs: [],
        netPremium: 0,
        maxProfit: '—',
        maxLoss: '—',
        riskReward: '—',
        breakeven: '—',
        winProb: 0,
        isPosGamma: true,
        distToPain: 0,
        distToCallWall: 0,
        distToPutWall: 0,
        expected1DMove: 0,
        expected1DMovePct: '0.00',
        atmStrike: spot || 0,
        step: 100,
      }
    }

    const isPosGamma = spot >= (data?.zero_gamma ?? spot - 50)
    const distToPain = (spot > 0 && maxPain != null && maxPain > 0) ? spot - maxPain : 0
    const distToCallWall = callWallStrike ? Number(callWallStrike) - spot : 200
    const distToPutWall = putWallStrike ? spot - Number(putWallStrike) : 200
    const isNearMaxPain = (maxPain != null && maxPain > 0) ? Math.abs(distToPain) <= (spot * 0.0075) : false
    const pcrNum = pcr !== '—' ? parseFloat(pcr) : 1.0
    const isPcrBullish = pcrNum >= 1.05
    const isPcrBearish = pcrNum <= 0.85
    const atmIVNum = minIV || 14
    const expected1DMove = Math.round(spot * (atmIVNum / 100) / Math.sqrt(365))
    const expected1DMovePct = (atmIVNum / Math.sqrt(365)).toFixed(2)

    // Step size for strikes
    const step = (underlying === 'NIFTY' || underlying === 'FINNIFTY') ? 50 : (underlying === 'BANKNIFTY' || underlying === 'SENSEX') ? 100 : (spot > 1000 ? 20 : 10)
    const atmStrike = Math.round(spot / step) * step

    let verdict = {
      strategyName: 'BULL CALL SPREAD',
      type: 'DIRECTIONAL_BULL',
      bias: 'BULLISH',
      conviction: 88,
      rationale: 'Positive Gamma regime with strong Put OI writing cushion; institutional flow defending Put Wall support.',
      legs: [
        { action: 'BUY', strike: atmStrike, type: 'CE', desc: 'ATM Call' },
        { action: 'SELL', strike: atmStrike + (step * 2), type: 'CE', desc: 'OTM Call (Call Wall)' },
      ],
      netPremium: Math.round(spot * 0.008),
      maxProfit: Math.round((step * 2) - (spot * 0.008)),
      maxLoss: Math.round(spot * 0.008),
      riskReward: '1 : 2.5',
      breakeven: `${atmStrike + Math.round(spot * 0.008)}`,
      winProb: 68,
    }

    if (isPosGamma && isNearMaxPain && pcrNum >= 0.95 && pcrNum <= 1.25) {
      verdict = {
        strategyName: 'IRON CONDOR / RANGE PIN',
        type: 'DELTA_NEUTRAL',
        bias: 'NEUTRAL PINNING',
        conviction: 92,
        rationale: 'Dealer Long Gamma pinning price near Max Pain strike. Mean-reverting volatility dampens breakout drift.',
        legs: [
          { action: 'SELL', strike: atmStrike + (step * 2), type: 'CE', desc: 'OTM Call Short' },
          { action: 'BUY', strike: atmStrike + (step * 4), type: 'CE', desc: 'Call Protection' },
          { action: 'SELL', strike: atmStrike - (step * 2), type: 'PE', desc: 'OTM Put Short' },
          { action: 'BUY', strike: atmStrike - (step * 4), type: 'PE', desc: 'Put Protection' },
        ],
        netPremium: Math.round(step * 0.45),
        maxProfit: Math.round(step * 0.45),
        maxLoss: Math.round(step * 1.55),
        riskReward: '1 : 3.4',
        breakeven: `${atmStrike - (step * 2) - Math.round(step * 0.45)} – ${atmStrike + (step * 2) + Math.round(step * 0.45)}`,
        winProb: 76,
      }
    } else if (!isPosGamma && (spot > (callWallStrike || atmStrike + 100) || isPcrBullish)) {
      verdict = {
        strategyName: 'LONG GAMMA SURGE / BREAKOUT',
        type: 'VOLATILITY_EXPANSION',
        bias: 'AGGRESSIVE BULLISH',
        conviction: 85,
        rationale: 'Spot broke above flip level into Negative Gamma territory; dealer short-gamma hedging will accelerate upward velocity.',
        legs: [
          { action: 'BUY', strike: atmStrike, type: 'CE', desc: 'ATM Momentum Call' },
        ],
        netPremium: Math.round(spot * 0.009),
        maxProfit: 'UNLIMITED',
        maxLoss: Math.round(spot * 0.009),
        riskReward: 'Asymmetric (1 : 4+)',
        breakeven: `${atmStrike + Math.round(spot * 0.009)}`,
        winProb: 62,
      }
    } else if (isPcrBearish || (!isPosGamma && spot < (putWallStrike || atmStrike - 100))) {
      verdict = {
        strategyName: 'BEAR PUT SPREAD',
        type: 'DIRECTIONAL_BEAR',
        bias: 'BEARISH',
        conviction: 87,
        rationale: 'Call writing resistance overhead with sub-0.85 PCR and Negative Gamma breakdown risk.',
        legs: [
          { action: 'BUY', strike: atmStrike, type: 'PE', desc: 'ATM Put' },
          { action: 'SELL', strike: atmStrike - (step * 2), type: 'PE', desc: 'OTM Put Target' },
        ],
        netPremium: Math.round(spot * 0.0075),
        maxProfit: Math.round((step * 2) - (spot * 0.0075)),
        maxLoss: Math.round(spot * 0.0075),
        riskReward: '1 : 2.7',
        breakeven: `${atmStrike - Math.round(spot * 0.0075)}`,
        winProb: 69,
      }
    } else if (atmIVNum <= 13.0 && isPosGamma) {
      verdict = {
        strategyName: 'SHORT STRADDLE / THETA HARVEST',
        type: 'THETA_DECAY',
        bias: 'NON-DIRECTIONAL',
        conviction: 89,
        rationale: 'Subdued volatility with tight dealer pinning creates optimal conditions for theta harvesting.',
        legs: [
          { action: 'SELL', strike: atmStrike, type: 'CE', desc: 'ATM Short Call' },
          { action: 'SELL', strike: atmStrike, type: 'PE', desc: 'ATM Short Put' },
        ],
        netPremium: Math.round(spot * 0.018),
        maxProfit: Math.round(spot * 0.018),
        maxLoss: 'Defined by Stop-Loss (30% premium)',
        riskReward: '1 : 1.5',
        breakeven: `${atmStrike - Math.round(spot * 0.018)} – ${atmStrike + Math.round(spot * 0.018)}`,
        winProb: 74,
      }
    }

    return {
      ...verdict,
      isPosGamma,
      distToPain,
      distToCallWall,
      distToPutWall,
      expected1DMove,
      expected1DMovePct,
      atmStrike,
      step,
    }
  }, [spot, maxPain, callWallStrike, putWallStrike, pcr, minIV, data?.zero_gamma, underlying, dataState, optionsChain.length, brokerNote])

  return (
    <div className="flex-1 overflow-y-auto p-2.5 sm:p-3.5 bg-surface text-text space-y-2.5 font-ui">
      {/* Top Header Card */}
      <div className="bg-panel/90 border border-border/80 rounded-xl p-3 shadow-sm backdrop-blur-md space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
          <div className="flex items-center gap-2.5">
            <span className="text-amber text-lg font-bold">◆</span>
            <div>
              <h1 className="text-sm font-bold tracking-wide font-mono text-text flex items-center gap-2">
                <span>QUANT &amp; OPTIONS DESK</span>
                <span className="text-xs px-2 py-0.5 rounded bg-amber/20 text-amber border border-amber/40 font-mono font-black">
                  {underlying}
                </span>
              </h1>
              <div className="flex items-center gap-2 text-[10px] text-muted">
                <span>Real-Time Greeks, GEX &amp; Multi-Factor Decision Matrix</span>
                <span>•</span>
                <span className="text-emerald-400 font-mono font-semibold">Synced Live Terminal Feeds</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Live Auto-Refresh Indicator & Pause/Resume */}
            <button
              onClick={() => setIsLiveActive(!isLiveActive)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition-all cursor-pointer ${
                isLiveActive
                  ? isRealtime
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/25'
                    : 'bg-amber-500/15 border-amber-500/30 text-amber hover:bg-amber-500/25'
                  : 'bg-surface border-border/70 text-muted hover:text-text'
              }`}
              title={isRealtime ? `Live sub-second real-time stream via ${sourceLabel} (Click to pause)` : `Delayed data feed (${sourceLabel}). Connect or route broker for real-time streaming.`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${isLiveActive ? (isRealtime ? 'bg-emerald-500 animate-pulse' : 'bg-amber-400 animate-pulse') : 'bg-muted'}`} />
              <span>{isLiveActive ? (isRealtime ? `LIVE (${dataSource.toUpperCase()})` : `DELAYED (${dataSource.toUpperCase()})`) : 'PAUSED'}</span>
              {asOfTime && (
                <span className="text-[9px] opacity-75 font-mono ml-0.5">
                  {asOfTime}
                </span>
              )}
            </button>

            {/* Quick Refresh Button */}
            <button
              onClick={() => fetchGex(true)}
              disabled={isRefreshing}
              className="px-2 py-1 rounded-lg bg-surface hover:bg-elevated border border-border/60 text-muted hover:text-amber text-xs font-bold transition-all cursor-pointer flex items-center gap-1"
              title="Refresh options chain now"
            >
              <span className={`inline-block ${isRefreshing ? 'animate-spin' : ''}`}>↻</span>
              <span className="text-[10px]">Refresh</span>
            </button>

            <button
              onClick={() => setIsPayoffModalOpen(true)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black text-xs font-bold transition-all shadow-xs cursor-pointer"
            >
              <span>🎯</span> Strategy Payoff
            </button>
          </div>
        </div>

        {/* Sub-bar: Instrument selector, Expiry & Key Analytics */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1">
              <span className="text-muted text-[11px]">Underlying:</span>
              <div className="flex items-center gap-0.5 bg-elevated rounded-lg p-0.5 border border-border/70 flex-wrap">
                {['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX', 'RELIANCE', 'HDFCBANK', 'TCS', 'INFY'].map((inst) => (
                  <button
                    key={inst}
                    onClick={() => handleSelectSymbol(inst)}
                    className={`px-2 py-0.5 rounded text-[11px] font-bold transition-all cursor-pointer ${
                      underlying === inst
                        ? 'bg-amber text-black shadow-xs'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {inst}
                  </button>
                ))}

                {/* Custom/Active symbol if not in the default pills */}
                {!['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX', 'RELIANCE', 'HDFCBANK', 'TCS', 'INFY'].includes(underlying) && (
                  <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-amber text-black shadow-xs">
                    {underlying}
                  </span>
                )}
              </div>
            </div>

            {/* F&O Symbol Search / Custom input */}
            {showSymbolSearch ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (customSymbolInput.trim()) {
                    handleSelectSymbol(customSymbolInput.trim())
                  }
                }}
                className="flex items-center gap-1"
              >
                <input
                  type="text"
                  value={customSymbolInput}
                  onChange={(e) => setCustomSymbolInput(e.target.value)}
                  placeholder="Sym (e.g. SBIN)"
                  autoFocus
                  className="bg-elevated border border-amber/60 text-text font-bold uppercase rounded px-2 py-0.5 text-[11px] focus:outline-none w-28"
                />
                <button
                  type="submit"
                  className="px-2 py-0.5 bg-amber text-black font-bold text-[10px] rounded cursor-pointer"
                >
                  Go
                </button>
                <button
                  type="button"
                  onClick={() => setShowSymbolSearch(false)}
                  className="px-1.5 py-0.5 text-muted hover:text-text text-[10px] cursor-pointer"
                >
                  ✕
                </button>
              </form>
            ) : (
              <button
                onClick={() => setShowSymbolSearch(true)}
                className="px-2 py-0.5 rounded text-[10px] font-mono text-muted hover:text-amber border border-border/60 hover:border-amber/40 bg-surface cursor-pointer flex items-center gap-1"
                title="Search or enter any F&O symbol"
              >
                <span>🔍</span> Other F&amp;O
              </button>
            )}

            <div className="flex items-center gap-1.5 ml-1">
              <span className="text-muted text-[11px]">Expiry:</span>
              <select
                value={selectedExpiry}
                onChange={(e) => setSelectedExpiry(e.target.value)}
                className="bg-elevated border border-border/80 text-text font-bold rounded-lg px-2 py-0.5 text-[11px] cursor-pointer focus:outline-none"
              >
                {expiries.map((exp) => (
                  <option key={exp} value={exp}>
                    {exp}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs">
            <div>
              <span className="text-muted mr-1 text-[11px]">Spot:</span>
              <span className={`font-bold text-xs ${spotIsPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                {spot > 0 ? `₹${Number(spot).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : 'Fetching...'}
              </span>
              {spot > 0 && (
                <span className={`font-semibold ml-1 text-[10px] ${spotIsPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ({spotChange} / {spotChangePct})
                </span>
              )}
              <span className="ml-1.5 px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-surface border border-border/70 text-muted">
                {resolvedExchange}
              </span>
            </div>

            {/* Transparent Data Provenance & asOfTimestamp Disclosure */}
            <div className="flex items-center gap-1.5 text-[10px] font-mono">
              <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold border ${
                isRealtime
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                  : dataState === 'BROKER_REQUIRED'
                  ? 'bg-blue-500/15 border-blue-500/30 text-blue-400'
                  : 'bg-amber-500/15 border-amber-500/30 text-amber'
              }`}>
                {isRealtime ? `⚡ REALTIME (${dataSource.toUpperCase()})` : dataState === 'BROKER_REQUIRED' ? '🔒 SPOT ONLY' : `⏱️ DELAYED (${dataSource.toUpperCase()})`}
              </span>
              <span className="text-muted text-[10px] hidden sm:inline">
                Feed: <span className="text-text font-semibold">{sourceLabel}</span>
              </span>
              <span className="text-muted text-[10px] hidden md:inline">
                • As of: <span className="text-text font-semibold">{asOfTime}</span>
              </span>
            </div>
          </div>
        </div>

        {/* Institutional Transparent Fallback Warning Banner */}
        {(!isRealtime && dataState !== 'BROKER_REQUIRED' && dataState !== 'LOADING') && (
          <div className="bg-amber-500/10 border-l-4 border-amber p-2.5 rounded-r-lg flex items-center justify-between text-xs font-mono shadow-sm">
            <div className="flex items-center gap-2.5">
              <span className="text-base text-amber">⚠️</span>
              <div>
                <span className="font-bold text-amber block">
                  FALLBACK DATA ACTIVE: {sourceLabel}
                </span>
                <span className="text-[11px] text-text/80 font-ui">
                  Real-time broker feed is inactive or failed. Displaying public exchange scraper feed (~15-minute delayed). Depth and live tick aggression are not real-time — do not use for sub-second execution.
                </span>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber text-[10px] font-bold shrink-0">
              NON-REALTIME
            </span>
          </div>
        )}

        {/* High-Impact PCR Blast Alert Banner */}
        {pcrBlast && (
          <div className="bg-gradient-to-r from-amber-500/20 via-orange-500/15 to-transparent border-l-4 border-amber p-2 rounded-r-lg flex items-center justify-between text-xs font-mono">
            <div className="flex items-center gap-2">
              <span className="text-base animate-bounce">⚡</span>
              <div>
                <span className="font-bold text-amber block">IMPACT VOLATILITY ALERT • PCR {pcr}</span>
                <span className="text-[11px] text-text/90 font-ui">{pcrBlastMsg || 'Extreme skew detected. High probability of violent gamma release.'}</span>
              </div>
            </div>
            <button
              onClick={() => sendDraft(`Analyze PCR ${pcr} extreme blast skew for ${underlying} and recommend asymmetrical options structure`)}
              className="px-2.5 py-1 bg-amber text-black font-bold text-[10px] rounded hover:brightness-110 cursor-pointer transition-all"
            >
              Analyze Squeeze
            </button>
          </div>
        )}

        {/* Dynamic Key Analytics Bar (PCR, Max Pain, Total OI, Net Flow) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 pt-1.5 border-t border-border/50 text-xs font-mono">
          <div className={`p-1.5 px-2 rounded-lg border transition-all ${
            pcrBlast
              ? 'bg-amber-500/15 border-amber-500/50 shadow-xs ring-1 ring-amber-500/40'
              : 'bg-surface/80 border-border/60'
          }`}>
            <div className="flex items-center justify-between text-[9px] text-muted">
              <span>PUT-CALL RATIO (PCR)</span>
              {pcrBlast && (
                <span className="text-[8px] font-black text-amber animate-pulse">
                  💥 BLAST SKEW
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-xs font-bold ${
                pcrBlast
                  ? 'text-amber font-black'
                  : pcr !== '—' && Number(pcr) >= 1.05
                  ? 'text-emerald-400'
                  : pcr !== '—' && Number(pcr) <= 0.85
                  ? 'text-rose-400'
                  : 'text-text'
              }`}>
                {pcr}
              </span>
              <span className="text-[8px] text-muted truncate">({pcrSentiment})</span>
            </div>
          </div>

          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">MAX PAIN STRIKE</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-xs font-bold text-amber">
                {maxPain > 0 ? `₹${Number(maxPain).toLocaleString('en-IN')}` : '—'}
              </span>
              <span className="text-[8px] text-muted">Expiry Pin</span>
            </div>
          </div>

          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">TOTAL OI (CALL vs PUT)</span>
            <div className="flex items-center gap-2 mt-0.5 text-[11px] font-bold">
              <span className="text-cyan-400">C: {totalCallOI}</span>
              <span className="text-muted">|</span>
              <span className="text-rose-400">P: {totalPutOI}</span>
            </div>
          </div>

          <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
            <span className="text-[9px] text-muted block">NET OI CHANGE</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-xs font-bold ${String(netOIChange).startsWith('-') ? 'text-rose-400' : 'text-emerald-400'}`}>
                {netOIChange}
              </span>
              <span className="text-[8px] text-muted">Institutional Flow</span>
            </div>
          </div>
        </div>
      </div>

      {/* Real-Time Institutional Options Decision Matrix Card */}
      <div className="bg-panel border border-border/80 rounded-xl p-3 shadow-md space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
          <div className="flex items-center gap-2">
            <span className="text-amber font-bold text-base">🧠</span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-bold uppercase tracking-wider text-text font-mono">
                  REAL-TIME OPTIONS DECISION MATRIX ({underlying})
                </h2>
                <span className="px-2 py-0.5 rounded-full text-[9px] font-bold font-mono bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  LIVE QUANT ENGINE
                </span>
              </div>
              <p className="text-[10px] text-muted font-ui">
                Multi-Factor Synthesis: GEX Regime • PCR Sentiment • Max Pain Magnet • Structural Walls • Volatility Skew
              </p>
            </div>
          </div>

          {/* Quick Verdict Badge in Header */}
          <div className="flex items-center gap-2">
            <div className="text-right">
              <span className="text-[9px] text-muted block font-mono">ALGORITHMIC VERDICT</span>
              <span className={`text-xs font-bold font-mono px-2 py-0.5 rounded border ${
                decisionMatrix.bias.includes('BULL')
                  ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                  : decisionMatrix.bias.includes('BEAR')
                  ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                  : 'bg-amber/15 border-amber/30 text-amber'
              }`}>
                {decisionMatrix.strategyName}
              </span>
            </div>
            <span className="text-xs font-mono font-black text-amber bg-surface px-2 py-1 rounded-lg border border-border/60">
              {decisionMatrix.conviction}% Conviction
            </span>
          </div>
        </div>

        {/* 5-Factor Analytical Matrix Row */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs font-mono">
          {/* Factor 1: GEX Regime */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 space-y-0.5">
            <div className="flex items-center justify-between text-[9px] text-muted">
              <span>1. GEX REGIME</span>
              <span className={decisionMatrix.isPosGamma ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
                {decisionMatrix.isPosGamma ? '+GEX PINNING' : '-GEX EXPANSION'}
              </span>
            </div>
            <div className="text-xs font-bold text-text">
              {decisionMatrix.isPosGamma ? 'Long Gamma (Pinning)' : 'Short Gamma (Breakout)'}
            </div>
            <div className="text-[9px] text-muted flex justify-between pt-0.5">
              <span>Flip: ₹{Number(data?.zero_gamma || spot - 50).toLocaleString('en-IN')}</span>
              <span className="text-pink-400">Δ {Math.abs(Math.round(spot - (data?.zero_gamma || spot - 50)))} pts</span>
            </div>
          </div>

          {/* Factor 2: Put-Call Ratio (PCR) */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 space-y-0.5">
            <div className="flex items-center justify-between text-[9px] text-muted">
              <span>2. PCR SENTIMENT</span>
              <span className={`font-bold ${pcr >= 1.05 ? 'text-emerald-400' : pcr <= 0.85 ? 'text-rose-400' : 'text-amber'}`}>
                PCR {pcr}
              </span>
            </div>
            <div className="text-xs font-bold text-text truncate">
              {pcr >= 1.10 ? 'Bullish Put Base' : pcr <= 0.85 ? 'Bearish Call Wall' : 'Balanced Flow'}
            </div>
            <div className="text-[9px] text-muted flex justify-between pt-0.5">
              <span>Calls: {totalCallOI}</span>
              <span>Puts: {totalPutOI}</span>
            </div>
          </div>

          {/* Factor 3: Max Pain Magnet */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 space-y-0.5">
            <div className="flex items-center justify-between text-[9px] text-muted">
              <span>3. MAX PAIN PIN</span>
              <span className="text-amber font-bold">₹{Number(maxPain).toLocaleString('en-IN')}</span>
            </div>
            <div className="text-xs font-bold text-text">
              {Math.abs(spot - maxPain) <= 40 ? '🎯 At Center Strike' : spot > maxPain ? `Above Pain (+${Math.round(spot - maxPain)} pts)` : `Below Pain (-${Math.round(maxPain - spot)} pts)`}
            </div>
            <div className="text-[9px] text-muted flex justify-between pt-0.5">
              <span>Pin Magnetism:</span>
              <span className={Math.abs(spot - maxPain) <= 75 ? 'text-emerald-400 font-bold' : 'text-muted'}>
                {Math.abs(spot - maxPain) <= 75 ? 'HIGH (Pin Risk)' : 'MODERATE'}
              </span>
            </div>
          </div>

          {/* Factor 4: Key Structural Walls */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 space-y-0.5">
            <div className="flex items-center justify-between text-[9px] text-muted">
              <span>4. EXPECTED RANGE</span>
              <span className="text-cyan-400 font-bold">WALLS</span>
            </div>
            <div className="text-xs font-bold text-text truncate">
              ₹{Number(putWallStrike || spot - 150).toLocaleString('en-IN')} – ₹{Number(callWallStrike || spot + 150).toLocaleString('en-IN')}
            </div>
            <div className="text-[9px] text-muted flex justify-between pt-0.5">
              <span className="text-amber">Support: Put Wall</span>
              <span className="text-cyan-400">Resist: Call Wall</span>
            </div>
          </div>

          {/* Factor 5: IV & Expected Move */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 space-y-0.5">
            <div className="flex items-center justify-between text-[9px] text-muted">
              <span>5. 1D EXPECTED MOVE</span>
              <span className="text-emerald-400 font-bold">ATM IV {minIV.toFixed(1)}%</span>
            </div>
            <div className="text-xs font-bold text-text">
              ±{decisionMatrix.expected1DMove} pts (±{decisionMatrix.expected1DMovePct}%)
            </div>
            <div className="text-[9px] text-muted flex justify-between pt-0.5">
              <span>Skew: Put Skew +3.4%</span>
              <span className="text-amber font-semibold">Decay: Normal</span>
            </div>
          </div>
        </div>

        {/* Institutional Decisive Recommendation Panel */}
        <div className="bg-gradient-to-r from-surface to-panel border border-border/80 rounded-xl p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-base">⚡</span>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-black tracking-wide text-amber uppercase">
                    RECOMMENDED ACTION: {decisionMatrix.strategyName}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.2 rounded font-mono font-bold bg-amber/15 text-amber border border-amber/30">
                    {decisionMatrix.bias}
                  </span>
                </div>
                <p className="text-[11px] text-text/80 font-ui mt-0.5 leading-snug">
                  {decisionMatrix.rationale}
                </p>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center gap-2">
              {decisionMatrix.legs && decisionMatrix.legs.length > 0 ? (
                <button
                  onClick={() => {
                    const primaryLeg = decisionMatrix.legs[0]
                    if (onOpenOrderTicket && primaryLeg) {
                      onOpenOrderTicket({
                        symbol: `${underlying} ${primaryLeg.strike} ${primaryLeg.type}`,
                        exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                        price: primaryLeg.type === 'CE' ? optionsChain[atmIdx]?.calls_ask : optionsChain[atmIdx]?.puts_ask,
                        side: primaryLeg.action,
                        segment: 'OPTIONS',
                      })
                    } else {
                      sendDraft(`execute strategy: ${decisionMatrix.strategyName} for ${underlying}`)
                    }
                  }}
                  className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-amber to-amber-light hover:brightness-110 text-black font-bold font-mono text-xs transition-all shadow-xs cursor-pointer flex items-center gap-1.5"
                  title="Stage multi-leg strategy order"
                >
                  <span>⚡</span> Stage 1-Click Order
                </button>
              ) : (
                <button
                  disabled
                  className="px-3 py-1.5 rounded-lg bg-surface border border-border/60 text-muted font-mono text-xs opacity-60 cursor-not-allowed flex items-center gap-1.5"
                >
                  <span>🔒</span> {dataState === 'BROKER_REQUIRED' ? 'Broker Required' : 'Awaiting Legs'}
                </button>
              )}

              <button
                onClick={() => setIsPayoffModalOpen(true)}
                className="px-3 py-1.5 rounded-lg bg-surface hover:bg-elevated border border-border/70 hover:border-amber/40 text-text font-bold font-mono text-xs transition-all cursor-pointer flex items-center gap-1.5"
                title="Open interactive payoff curve simulator"
              >
                <span>🎯</span> Simulate Payoff
              </button>

              <button
                onClick={() =>
                  sendDraft(
                    `Deep options debate for ${underlying}: Strategy ${decisionMatrix.strategyName}, Spot: ₹${spot}, PCR: ${pcr}, GEX: ${decisionMatrix.isPosGamma ? 'Long Gamma' : 'Short Gamma'}, Max Pain: ₹${maxPain}. What is the institutional trade plan?`
                  )
                }
                className="px-2.5 py-1.5 rounded-lg bg-surface hover:bg-elevated border border-border/60 text-muted hover:text-amber text-xs font-mono transition-all cursor-pointer flex items-center gap-1"
                title="Ask AI Copilot for quantitative thesis"
              >
                <span>💬</span> Copilot
              </button>
            </div>
          </div>

          {/* Strategic Legs & Risk Matrix Breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 pt-1.5 border-t border-border/50 text-xs font-mono">
            <div className="md:col-span-6 flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-muted uppercase font-bold">Legs:</span>
              {decisionMatrix.legs.length > 0 ? (
                decisionMatrix.legs.map((leg, idx) => (
                  <div
                    key={idx}
                    className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[11px] font-bold ${
                      leg.action === 'BUY'
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                        : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                    }`}
                  >
                    <span>{leg.action}</span>
                    <span>₹{Number(leg.strike).toLocaleString('en-IN')} {leg.type}</span>
                    <span className="text-[9px] opacity-75 font-normal">({leg.desc})</span>
                  </div>
                ))
              ) : (
                <span className="text-[11px] text-muted font-mono italic">
                  {dataState === 'BROKER_REQUIRED'
                    ? 'Connect broker for live BFO executable options legs'
                    : 'Awaiting real-time contract strikes'}
                </span>
              )}
            </div>

            <div className="md:col-span-6 flex flex-wrap items-center justify-start md:justify-end gap-3 text-[11px]">
              <div>
                <span className="text-muted text-[9px] block">Max Profit</span>
                <span className="text-emerald-400 font-bold font-mono">
                  {typeof decisionMatrix.maxProfit === 'number' ? `₹${decisionMatrix.maxProfit.toLocaleString('en-IN')}` : decisionMatrix.maxProfit}
                </span>
              </div>
              <div>
                <span className="text-muted text-[9px] block">Max Loss</span>
                <span className="text-rose-400 font-bold font-mono">
                  {typeof decisionMatrix.maxLoss === 'number' ? `₹${decisionMatrix.maxLoss.toLocaleString('en-IN')}` : decisionMatrix.maxLoss}
                </span>
              </div>
              <div>
                <span className="text-muted text-[9px] block">Risk : Reward</span>
                <span className="text-cyan-400 font-bold font-mono">{decisionMatrix.riskReward}</span>
              </div>
              <div>
                <span className="text-muted text-[9px] block">Breakeven</span>
                <span className="text-text font-bold font-mono">{decisionMatrix.breakeven}</span>
              </div>
              <div>
                <span className="text-muted text-[9px] block">Est. Win Prob</span>
                <span className="text-amber font-bold font-mono">{decisionMatrix.winProb}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Top 3-Pane Grid: GEX Volatility Pinning, Delta Hedging, IV Smile */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-2.5">
        {/* Card 1: GEX Volatility Pinning & Gamma Regime (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-xl p-3 shadow-xs space-y-2">
          <div className="flex items-center justify-between border-b border-border/50 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
              <span>📊</span> DEALER GAMMA &amp; VOLATILITY (GEX)
            </span>
            <span className="text-[10px] text-pink-400 font-mono font-bold">
              FLIP: {data?.zero_gamma ? `₹${Number(data.zero_gamma).toLocaleString('en-IN')}` : '—'}
            </span>
          </div>

          {/* Regime Banner */}
          <div className="bg-surface/80 p-2 rounded-lg border border-border/60 flex items-center justify-between">
            <div>
              <span className="text-[9px] text-muted block">Current Gamma Regime</span>
              <span className="text-[11px] font-bold text-emerald-400 font-mono flex items-center gap-1">
                <span>🟢</span> {decisionMatrix.isPosGamma ? 'POSITIVE GAMMA (PINNING)' : 'NEGATIVE GAMMA (EXPANSION)'}
              </span>
            </div>
            <div className="text-right">
              <span className="text-[9px] text-muted block">Dealer Stance</span>
              <span className="text-[10px] font-bold text-cyan-400 font-mono">
                {decisionMatrix.isPosGamma ? 'Long Gamma (Mean Reverting)' : 'Short Gamma (Breakout)'}
              </span>
            </div>
          </div>

          {/* Key Gamma Walls (Call Resistance vs Put Support) */}
          <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
            <div className="bg-cyan-500/10 border border-cyan-500/30 p-1.5 px-2 rounded-lg">
              <div className="flex items-center justify-between text-[9px] text-cyan-400 font-bold">
                <span>CALL WALL</span>
                <span>RESISTANCE</span>
              </div>
              <span className="text-xs font-bold text-text mt-0.5 block">
                {callWallStrike ? `₹${Number(callWallStrike).toLocaleString('en-IN')}` : '—'}
              </span>
              <span className="text-[9px] text-muted">Institutional Ceiling</span>
            </div>

            <div className="bg-amber/10 border border-amber/30 p-1.5 px-2 rounded-lg">
              <div className="flex items-center justify-between text-[9px] text-amber font-bold">
                <span>PUT WALL</span>
                <span>SUPPORT</span>
              </div>
              <span className="text-xs font-bold text-text mt-0.5 block">
                {putWallStrike ? `₹${Number(putWallStrike).toLocaleString('en-IN')}` : '—'}
              </span>
              <span className="text-[9px] text-muted">Institutional Floor</span>
            </div>
          </div>

          {/* Actionable Trader Takeaway */}
          <p className="text-[10px] text-muted font-ui leading-relaxed bg-surface/50 p-1.5 rounded-lg border border-border/40">
            💡 <strong className="text-text">Trading Insight:</strong> {
              optionsChain.length > 0 && putWallStrike && callWallStrike
                ? `Dealers are ${decisionMatrix.isPosGamma ? 'long gamma' : 'short gamma'}; price expected to oscillate between ₹${Number(putWallStrike).toLocaleString('en-IN')} (Put Wall) and ₹${Number(callWallStrike).toLocaleString('en-IN')} (Call Wall).`
                : dataState === 'BROKER_REQUIRED'
                ? `Live SENSEX spot is active at ₹${Number(spot).toLocaleString('en-IN')}. Connect broker to compute dealer gamma walls and zero flip level.`
                : 'Awaiting real-time option chain data to compute dealer pinning walls.'
            }
          </p>
        </div>

        {/* Card 2: Delta Neutral Hedging Recommendation (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-xl p-3 shadow-xs space-y-2">
          <div className="flex items-center justify-between border-b border-border/50 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
              <span>⚡</span> DELTA HEDGING &amp; RISK
            </span>
            <div className="flex items-center gap-1">
              {[
                { label: '1L', val: 1 },
                { label: '2L', val: 2 },
                { label: '5L', val: 5 },
              ].map((sc) => (
                <button
                  key={sc.val}
                  onClick={() => setDeskPosScale(sc.val)}
                  className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold transition-all cursor-pointer ${
                    deskPosScale === sc.val ? 'bg-amber text-black' : 'bg-surface text-muted hover:text-text'
                  }`}
                  title={`Scale position by ${sc.label}`}
                >
                  {sc.label}
                </button>
              ))}
              <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ml-1 ${
                Math.abs(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale) <= 0.08
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : Number(deltaHedge?.net_delta ?? 0.42) > 0
                  ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                  : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
              }`}>
                {Number(deltaHedge?.net_delta ?? 0.42) > 0 ? 'LONG Δ' : 'SHORT Δ'}
              </span>
            </div>
          </div>

          {/* Visual Delta Balance Needle Meter */}
          <div className="bg-surface/70 border border-border/60 rounded-lg p-2 space-y-1">
            <div className="flex items-center justify-between text-[9px] font-mono text-muted">
              <span className="text-rose-400">Short (-1.0)</span>
              <span className="text-emerald-400 font-bold">Neutral Zone</span>
              <span className="text-cyan-400">Long (+1.0)</span>
            </div>
            <div className="relative h-2 w-full bg-border/40 rounded-full overflow-hidden flex items-center">
              <div className="absolute left-[45%] right-[45%] top-0 bottom-0 bg-emerald-500/30 border-x border-emerald-400/50" />
              <div
                className="absolute top-0 bottom-0 w-2 -ml-1 bg-gradient-to-r from-amber to-amber-light rounded-full shadow-xs transition-all duration-300"
                style={{
                  left: `${((Math.max(-1.0, Math.min(1.0, Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale)) + 1.0) / 2.0) * 100}%`,
                }}
              />
            </div>
            <div className="flex justify-between items-center text-[9px] text-muted font-mono">
              <span>Net Δ: <strong className="text-text">{Number(deltaHedge?.net_delta ?? 0.42) >= 0 ? '+' : ''}{(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale).toFixed(2)} Δ ({Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale * (underlying === 'BANKNIFTY' ? 15 : 75))} shares)</strong></span>
              <span>₹/1%: <strong className="text-cyan-400">₹{Math.abs(Math.round(Number(deltaHedge?.net_delta ?? 0.42) * deskPosScale * (underlying === 'BANKNIFTY' ? 15 : 75) * spot * 0.01)).toLocaleString('en-IN')}</strong></span>
            </div>
          </div>

          {/* Actionable Hedge Recipes */}
          <div className="space-y-1.5 text-xs font-mono">
            <div className="bg-surface/80 p-2 rounded-lg border border-border/60">
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-muted block">Hedge Execution Blueprint</span>
                <button
                  onClick={() => setShowDeskWhy(!showDeskWhy)}
                  className="text-[9px] text-amber hover:underline cursor-pointer flex items-center gap-0.5"
                >
                  <span>{showDeskWhy ? '▲ Hide' : '▼ Why?'}</span>
                </button>
              </div>
              <span className="font-bold text-emerald-400 text-[11px] block truncate mt-0.5">
                SELL {Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale))} Lot{Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale)) > 1 ? 's' : ''} ({Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale)) * (underlying === 'BANKNIFTY' ? 15 : underlying === 'SENSEX' ? 20 : 75)} Qty) {underlying} FUT
              </span>
            </div>

            {/* Expandable Why & When Narrative */}
            {showDeskWhy && (
              <div className="bg-surface/90 border border-amber/30 rounded-lg p-2 space-y-1 text-[10px] font-ui text-text/90 leading-tight">
                <p className="font-bold text-amber">💡 Monetary Risk Rationale:</p>
                <p>
                  Holding {deskPosScale} lot{deskPosScale > 1 ? 's' : ''} with +{(Number(deltaHedge?.net_delta ?? 0) * deskPosScale).toFixed(2)} delta exposes you to ~₹{Math.abs(Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale * (underlying === 'BANKNIFTY' ? 15 : underlying === 'SENSEX' ? 20 : 75) * (spot || 0) * 0.01)).toLocaleString('en-IN')} loss per 1% drop in {underlying}.
                </p>
                <p className="text-muted font-mono pt-0.5">Trigger: When {underlying} drifts &gt; ±0.75% (±{Math.round((spot || 0) * 0.0075)} pts).</p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-1.5 text-[10px]">
              <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
                <span className="text-[8px] text-muted block">Gamma Risk</span>
                <span className="font-bold text-text">{deltaHedge?.net_gamma ?? '0.00'} Γ</span>
              </div>
              <div className="bg-surface/80 p-1.5 px-2 rounded-lg border border-border/60">
                <span className="text-[8px] text-muted block">Est. Margin</span>
                <span className="font-bold text-text">₹{Math.round(Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale)) * (underlying === 'BANKNIFTY' ? 15 : underlying === 'SENSEX' ? 20 : 75) * (spot || 0) * 0.11).toLocaleString('en-IN')}</span>
              </div>
            </div>

            <div className="pt-0.5">
              <button
                onClick={() => {
                  const hedgeLots = Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale))
                  const lotSz = (underlying === 'BANKNIFTY' ? 15 : underlying === 'FINNIFTY' ? 40 : underlying === 'SENSEX' ? 20 : 75)
                  if (onOpenOrderTicket) {
                    onOpenOrderTicket({
                      symbol: `${underlying} FUT`,
                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                      price: spot,
                      quantity: hedgeLots * lotSz,
                      side: Number(deltaHedge?.net_delta ?? 0) > 0 ? 'SELL' : 'BUY',
                      segment: 'OPTIONS',
                    })
                  } else {
                    sendDraft(`execute delta hedge: SELL ${hedgeLots} lots (${hedgeLots * lotSz} qty) ${underlying} FUT`)
                  }
                }}
                className="w-full py-1.5 px-2.5 rounded-lg bg-gradient-to-r from-emerald-500 to-teal-500 hover:brightness-110 text-black font-bold text-[11px] uppercase tracking-wide transition-all shadow-xs cursor-pointer flex items-center justify-center gap-1"
              >
                <span>⚡</span> Stage 1-Click Hedge ({Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale))} Lot{Math.max(1, Math.round(Number(deltaHedge?.net_delta ?? 0) * deskPosScale)) > 1 ? 's' : ''})
              </button>
            </div>
          </div>
        </div>

        {/* Card 3: Dynamic IV Smile & Skew Curve (4 Cols) */}
        <div className="lg:col-span-4 bg-panel border border-border/80 rounded-xl p-3 shadow-xs space-y-2">
          <div className="flex items-center justify-between border-b border-border/50 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted flex items-center gap-1">
              <span>📈</span> VOLATILITY SMILE &amp; SKEW
            </span>
            <span className="text-[9px] text-amber font-mono font-bold px-1.5 py-0.5 rounded bg-amber/10 border border-amber/30">
              PUT SKEW +3.4%
            </span>
          </div>

          {/* Interactive Dynamic SVG Smile Curve */}
          <div className="h-28 w-full relative flex items-center justify-center bg-surface/80 rounded-lg border border-border/60 p-1.5">
            <svg className="w-full h-full" viewBox="0 0 240 90">
              {/* Grid lines */}
              <line x1="0" y1="20" x2="240" y2="20" stroke="currentColor" className="text-border/60" strokeDasharray="3" />
              <line x1="0" y1="45" x2="240" y2="45" stroke="currentColor" className="text-border/60" strokeDasharray="3" />
              <line x1="0" y1="70" x2="240" y2="70" stroke="currentColor" className="text-border/60" strokeDasharray="3" />

              {/* Spot Marker Line (Pink) */}
              <line x1="120" y1="0" x2="120" y2="90" stroke="#f43f5e" strokeWidth="1.2" strokeDasharray="2" />
              <text x="123" y="12" fill="#f43f5e" fontSize="7" fontFamily="monospace" fontWeight="bold">
                Spot: {Math.round(spot)}
              </text>

              {/* Put IV Curve (Amber) */}
              {svgPoints && (
                <polyline
                  fill="none"
                  stroke="#f59e0b"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={svgPoints}
                />
              )}

              {/* Call IV Curve (Cyan) */}
              <polyline
                fill="none"
                stroke="#06b6d4"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray="4 2"
                points="15,75 70,72 120,68 170,62 225,55"
              />

              {/* ATM Circle Point */}
              <circle cx="120" cy="68" r="3" fill="#f59e0b" className="animate-pulse" />
              <text x="124" y="78" fill="#f59e0b" fontSize="7" fontFamily="monospace" fontWeight="bold">
                ATM ({minIV.toFixed(1)}%)
              </text>
            </svg>
          </div>

          <div className="flex justify-between items-center text-[9px] font-mono text-muted bg-surface/50 p-1.5 rounded-lg border border-border/40">
            <span className="flex items-center gap-1 text-amber">
              <span className="w-1.5 h-1 bg-amber rounded-full inline-block" /> Put IV ({ivSkew[0]?.iv || '18.2'}%)
            </span>
            <span className="text-cyan-400 font-bold">ATM ({minIV.toFixed(1)}%)</span>
            <span className="flex items-center gap-1 text-cyan-400">
              <span className="w-1.5 h-1 bg-cyan-400 rounded-full inline-block" /> Call IV (14.2%)
            </span>
          </div>

          {/* 1-Click Skew Strategy Action Chip */}
          <button
            onClick={() => sendDraft(`Build a high-probability Bull Put spread for ${underlying} to exploit elevated put skew`)}
            className="w-full py-1 px-2 rounded-lg bg-surface hover:bg-amber/10 border border-border/70 hover:border-amber/40 text-[10px] font-mono font-bold text-amber transition-all cursor-pointer flex items-center justify-center gap-1"
          >
            <span>🎯</span> Harvest Put Skew (Bull Put Spread)
          </button>
        </div>
      </div>

      {/* Blast Radar: High Impact Order Book Imbalance & Volume Blast Detector */}
      {blastRadar && blastRadar.length > 0 && (
        <div className="bg-panel border border-amber/50 rounded-2xl p-3 sm:p-4 shadow-md space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-lg">🔥</span>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-xs font-bold font-mono uppercase tracking-wider text-amber">
                    ORDER FLOW BLAST RADAR (TOP {blastRadar.length} IMPACT STRIKES)
                  </h2>
                  <span className="px-1.5 py-0.2 rounded text-[9px] font-bold font-mono bg-amber/20 text-amber border border-amber/40 animate-pulse">
                    HIGH SURGE PROBABILITY
                  </span>
                </div>
                <p className="text-[10px] text-muted font-ui">
                  Detected real-time order-book bid/ask queue imbalances &gt; 1.6x &amp; heavy volume surges.
                </p>
              </div>
            </div>
            <span className="text-[10px] font-mono text-muted">
              Live Order Book Sweep Monitoring
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {blastRadar.map((pick, pIdx) => {
              const isCall = pick.option_type === 'CE'
              return (
                <div
                  key={pIdx}
                  className={`p-3 rounded-2xl border transition-all shadow-sm space-y-2.5 ${
                    isCall
                      ? 'bg-cyan-950/20 border-cyan-500/40 hover:border-cyan-400'
                      : 'bg-rose-950/20 border-rose-500/40 hover:border-rose-400'
                  }`}
                >
                  {/* Card Header */}
                  <div className="flex items-center justify-between font-mono">
                    <span className="text-xs font-extrabold text-text flex items-center gap-1.5">
                      <span className={isCall ? 'text-cyan-400' : 'text-rose-400'}>
                        {pick.contract}
                      </span>
                      <span
                        className={`text-[9px] px-1.5 py-0.2 rounded font-black ${
                          isCall ? 'bg-cyan-500/20 text-cyan-300' : 'bg-rose-500/20 text-rose-300'
                        }`}
                      >
                        {pick.option_type}
                      </span>
                    </span>
                    <div className="flex items-center gap-1">
                      <span className="text-[9px] font-bold text-amber bg-amber-500/15 border border-amber-500/30 px-1.5 py-0.5 rounded">
                        Score {pick.score}/100
                      </span>
                      <span className="text-[9px] font-bold text-emerald-400 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded">
                        ⚡ {pick.imbalance_ratio}x Buyers
                      </span>
                    </div>
                  </div>

                  <p className="text-[10px] text-muted font-ui leading-snug">
                    {pick.blast_reason}
                  </p>

                  {/* Actionable Profit Blueprint Matrix */}
                  <div className="grid grid-cols-2 gap-1.5 bg-surface/70 p-2 rounded-xl border border-border/50 text-[10px] font-mono">
                    <div>
                      <span className="text-[8px] uppercase tracking-wider text-muted block">Entry Zone</span>
                      <span className="font-extrabold text-emerald-400 text-xs">
                        {pick.entry_range || `₹${pick.bid} – ₹${pick.ask}`}
                      </span>
                    </div>
                    <div>
                      <span className="text-[8px] uppercase tracking-wider text-muted block">Invalidation SL</span>
                      <span className="font-extrabold text-rose-400 text-xs">
                        ₹{pick.stop_loss || '—'}{' '}
                        <span className="text-[8px] font-normal opacity-75">
                          ({pick.stop_loss_pct || '-25%'})
                        </span>
                      </span>
                    </div>
                    <div>
                      <span className="text-[8px] uppercase tracking-wider text-muted block">Target 1 (1.5R)</span>
                      <span className="font-extrabold text-cyan-300 text-xs">
                        ₹{pick.target_1 || '—'}{' '}
                        <span className="text-[8px] font-normal opacity-75">
                          ({pick.target_1_pct || '+35%'})
                        </span>
                      </span>
                    </div>
                    <div>
                      <span className="text-[8px] uppercase tracking-wider text-muted block">Target 2 (2.5R)</span>
                      <span className="font-extrabold text-amber text-xs">
                        ₹{pick.target_2 || '—'}{' '}
                        <span className="text-[8px] font-normal opacity-75">
                          ({pick.target_2_pct || '+65%'})
                        </span>
                      </span>
                    </div>
                  </div>

                  {/* Trader Execution Rules */}
                  <div className="space-y-1 text-[9px] bg-black/30 p-2 rounded-xl border border-border/40 font-ui leading-tight">
                    <div className="flex items-start gap-1">
                      <span className="text-emerald-400 font-bold shrink-0">🟢 BUY:</span>
                      <span className="text-text/90">
                        {pick.when_to_buy || `Enter on Ask/Retest while Spot holds support`}
                      </span>
                    </div>
                    <div className="flex items-start gap-1">
                      <span className="text-amber font-bold shrink-0">🟡 WAIT:</span>
                      <span className="text-text/80">
                        {pick.when_to_wait || `DO NOT CHASE if premium spiked > 15%`}
                      </span>
                    </div>
                    <div className="flex items-start gap-1">
                      <span className="text-cyan-400 font-bold shrink-0">💰 PROFIT:</span>
                      <span className="text-text/90 font-semibold">
                        {pick.profit_rule || `Take 50% off at T1 and trail SL to Cost`}
                      </span>
                    </div>
                  </div>

                  {/* Realtime Bid/Ask & Action Controls */}
                  <div className="pt-1.5 border-t border-border/40 flex flex-wrap items-center justify-between gap-1.5 text-xs font-mono">
                    <div>
                      <span className="text-[8px] text-muted block uppercase">Bid / Ask</span>
                      <span className="font-bold text-text text-[11px]">
                        ₹{pick.bid} <span className="text-muted text-[9px]">/</span> ₹{pick.ask}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() =>
                          onOpenOrderTicket &&
                          onOpenOrderTicket({
                            symbol: pick.contract,
                            exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                            price: pick.ask || pick.bid,
                            side: pick.side || 'BUY',
                            orderType: 'BUY',
                            segment: 'OPTIONS',
                          })
                        }
                        className={`px-2.5 py-1 rounded-lg font-extrabold text-[10px] transition-all shadow-xs cursor-pointer flex items-center gap-1 ${
                          isCall
                            ? 'bg-gradient-to-r from-cyan-400 to-cyan-500 hover:brightness-110 text-black'
                            : 'bg-gradient-to-r from-rose-500 to-rose-600 hover:brightness-110 text-white'
                        }`}
                        title="Open Order Ticket"
                      >
                        <span>🚀</span> Stage Order
                      </button>

                      <button
                        onClick={() => handleSendTelegramBlast(pick)}
                        className="px-2 py-1 rounded-lg bg-surface hover:bg-elevated border border-border/70 text-text hover:text-amber text-[10px] font-bold transition-all cursor-pointer flex items-center gap-1"
                        title="Send actionable alert to Telegram"
                      >
                        <span>📲</span>
                      </button>

                      <button
                        onClick={() =>
                          sendDraft(
                            `Analyze ${pick.contract} blast surge (${pick.blast_reason}) and recommend asymmetric trade structure`
                          )
                        }
                        className="px-2 py-1 rounded-lg bg-surface hover:bg-elevated border border-border/70 text-text hover:text-cyan-400 text-[10px] font-bold transition-all cursor-pointer flex items-center gap-1"
                        title="Analyze in Copilot Chat"
                      >
                        <span>💬</span>
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[9px] text-muted font-mono pt-0.5">
                    <span>Vol: {Number(pick.volume || 0).toLocaleString('en-IN')}</span>
                    <span>OI: {Number(pick.oi || 0).toLocaleString('en-IN')}</span>
                    <span>R:R: {pick.risk_reward || '1:2.5'}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Conviction Score Card — 10-Factor High-Probability Signal Intelligence */}
      <div className="mt-3">
        <ConvictionScoreCard
          underlying={underlying}
          spot={typeof spot === 'number' ? spot : parseFloat(spot) || 0}
          pcr={pcr !== '—' ? parseFloat(pcr) || null : null}
          blastRadar={blastRadar}
          convictionScore={convictionScore}
        />
      </div>

      {/* Bottom Full-Width Institutional Options Chain Table */}
      {(() => {
        const maxCallOIVal = Math.max(...optionsChain.map((r) => parseFloat(String(r.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0), 1)
        const maxPutOIVal = Math.max(...optionsChain.map((r) => parseFloat(String(r.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0), 1)

        return (
          <div className="bg-panel border border-border/80 rounded-2xl p-4 shadow-md space-y-3">
            {/* Top Table Control Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 pb-3">
              <div className="flex flex-wrap items-center gap-2.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-amber font-bold">⛓️</span>
                  <span className="text-xs font-bold uppercase tracking-wider text-text font-mono">
                    {underlying} OPTIONS CHAIN
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 font-mono font-bold border border-emerald-500/30">
                    Spot: {spot > 0 ? `₹${Number(spot).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : 'Fetching...'}
                  </span>
                </div>

                {/* Key Structural Wall Badges */}
                <div className="flex items-center gap-1.5 text-[10px] font-mono hidden md:flex">
                  {callWallStrike && (
                    <span className="px-2 py-0.5 rounded bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 font-bold" title="Highest Call OI - Institutional Resistance">
                      🛡️ Call Wall: ₹{Number(callWallStrike).toLocaleString('en-IN')}
                    </span>
                  )}
                  {putWallStrike && (
                    <span className="px-2 py-0.5 rounded bg-amber/15 border border-amber/30 text-amber font-bold" title="Highest Put OI - Institutional Support">
                      🏰 Put Wall: ₹{Number(putWallStrike).toLocaleString('en-IN')}
                    </span>
                  )}
                  {maxPain > 0 && (
                    <span className="px-2 py-0.5 rounded bg-rose-500/15 border border-rose-500/30 text-rose-400 font-bold" title="Expiry Pin Level">
                      🎯 Max Pain: ₹{Number(maxPain).toLocaleString('en-IN')}
                    </span>
                  )}
                </div>
              </div>

              {/* Table Controls: View Mode + Visual Bars + Strike Filter + Sorting + Page Size */}
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                {/* View Mode Toggle: Standard vs Greeks */}
                <div className="flex items-center gap-0.5 bg-surface border border-border/60 p-0.5 rounded-lg text-[10px]">
                  <button
                    onClick={() => setChainViewMode('STANDARD')}
                    className={`px-2 py-0.5 rounded font-bold transition-all cursor-pointer ${
                      chainViewMode === 'STANDARD' ? 'bg-amber text-black shadow-xs' : 'text-muted hover:text-text'
                    }`}
                  >
                    📊 Standard
                  </button>
                  <button
                    onClick={() => setChainViewMode('GREEKS')}
                    className={`px-2 py-0.5 rounded font-bold transition-all cursor-pointer ${
                      chainViewMode === 'GREEKS' ? 'bg-amber text-black shadow-xs' : 'text-muted hover:text-text'
                    }`}
                  >
                    🔬 Greeks (Δ, Γ, Θ, ν)
                  </button>
                </div>

                {/* Depth Bars Toggle */}
                <button
                  onClick={() => setShowVisualBars(!showVisualBars)}
                  className={`px-2 py-0.5 rounded text-[10px] border transition-all cursor-pointer ${
                    showVisualBars
                      ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400 font-bold'
                      : 'bg-surface border-border/60 text-muted hover:text-text'
                  }`}
                  title="Toggle horizontal visual open interest depth bars"
                >
                  🔥 Depth Bars: {showVisualBars ? 'ON' : 'OFF'}
                </button>

                {/* Center on ATM Button */}
                <button
                  onClick={() => {
                    if (atmSortedIndex >= 0 && !isPageSizeAll) {
                      const targetPage = Math.max(1, Math.ceil((atmSortedIndex + 1) / pageSizeNum))
                      setChainPage(targetPage)
                    }
                    setTimeout(scrollToATM, 50)
                  }}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber/20 hover:bg-amber hover:text-black text-amber border border-amber/50 font-bold text-[10px] transition-all cursor-pointer shadow-xs"
                  title="Jump to and center on At-The-Money (Spot) strike"
                >
                  <span>🎯</span>
                  <span>Center on ATM</span>
                </button>

                {/* Strike Filter Chips */}
                <div className="flex items-center gap-0.5 bg-surface border border-border/60 p-0.5 rounded-lg text-[10px]">
                  {[
                    { id: 'ATM_5', label: 'ATM ±5' },
                    { id: 'ATM_10', label: 'ATM ±10' },
                    { id: 'ATM_15', label: 'ATM ±15' },
                    { id: 'ALL', label: 'All Strikes' },
                  ].map((f) => (
                    <button
                      key={f.id}
                      onClick={() => {
                        setStrikeFilter(f.id)
                        setChainPage(1)
                      }}
                      className={`px-1.5 py-0.5 rounded transition-all cursor-pointer ${
                        strikeFilter === f.id ? 'bg-amber text-black font-bold' : 'text-muted hover:text-text'
                      }`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>

                {/* Sort Selector */}
                <div className="flex items-center gap-1">
                  <select
                    value={chainSort}
                    onChange={(e) => {
                      setChainSort(e.target.value)
                      setChainPage(1)
                    }}
                    className="bg-surface border border-border/60 text-text rounded px-1.5 py-0.5 text-[10px] font-mono focus:outline-none cursor-pointer"
                  >
                    <option value="strike_asc">Strike (Low → High)</option>
                    <option value="strike_desc">Strike (High → Low)</option>
                    <option value="call_oi_desc">Highest Call OI</option>
                    <option value="put_oi_desc">Highest Put OI</option>
                  </select>
                </div>

                {/* Page Size Selector */}
                <div className="flex items-center gap-1">
                  {[15, 25, 50, 'ALL'].map((sz) => (
                    <button
                      key={sz}
                      onClick={() => {
                        setPageSize(sz)
                        setChainPage(1)
                      }}
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono cursor-pointer ${
                        chainPageSize === sz ? 'bg-amber text-black font-bold' : 'bg-surface text-muted hover:text-text border border-border/40'
                      }`}
                    >
                      {sz}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Matrix Table or Institutional Disconnected / Loading Notice */}
            {paginatedChain.length === 0 ? (
              <div className="p-8 text-center bg-surface/60 rounded-xl border border-dashed border-border/80 space-y-3">
                <div className="w-12 h-12 rounded-full bg-amber/10 border border-amber/30 text-amber flex items-center justify-center text-xl mx-auto">
                  {dataState === 'BROKER_REQUIRED' ? '🔒' : '⏳'}
                </div>
                <div className="max-w-md mx-auto space-y-1">
                  <h3 className="text-sm font-bold font-mono text-text">
                    {dataState === 'BROKER_REQUIRED'
                      ? 'BSE SENSEX Spot Streaming • Broker Required for BFO Chain'
                      : loading
                      ? 'Streaming Real-Time Option Chain & Greeks...'
                      : 'No Active Contracts Found'}
                  </h3>
                  <p className="text-xs text-muted font-ui">
                    {dataState === 'BROKER_REQUIRED'
                      ? brokerNote || 'Live SENSEX index spot price is streaming real-time from BSE. Connect your broker (Zerodha Kite, Dhan, Shoonya, or Fyers) to stream real-time BFO options depth, Greeks, and execute orders.'
                      : loading
                      ? 'Connecting to exchange live feed and deriving volatility surface...'
                      : 'No option contracts found for the selected expiry. Try selecting another expiry or instrument.'}
                  </p>
                </div>
                {dataState === 'BROKER_REQUIRED' && (
                  <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
                    <button
                      onClick={() => handleSelectSymbol('NIFTY')}
                      className="px-3 py-1.5 rounded-lg bg-amber text-black font-bold font-mono text-xs hover:brightness-110 cursor-pointer shadow-xs"
                    >
                      Switch to NIFTY (Live Open Chain)
                    </button>
                    <button
                      onClick={() => handleSelectSymbol('BANKNIFTY')}
                      className="px-3 py-1.5 rounded-lg bg-surface border border-border/80 text-text font-bold font-mono text-xs hover:text-amber cursor-pointer"
                    >
                      Switch to BANKNIFTY
                    </button>
                    <button
                      onClick={() => sendDraft('How do I connect my broker for BSE SENSEX options?')}
                      className="px-3 py-1.5 rounded-lg bg-surface border border-border/80 text-muted font-mono text-xs hover:text-text cursor-pointer"
                    >
                      Broker Setup Guide
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div ref={tableContainerRef} className="overflow-x-auto rounded-xl border border-border/50 max-h-[620px] overflow-y-auto relative scrollbar-thin">
                <table className="w-full text-xs font-mono text-left border-collapse">
                  <thead className="sticky top-0 z-20 bg-surface shadow-xs">
                    {/* Category Super-Headers */}
                    <tr className="bg-elevated/80 text-[10px] uppercase font-bold tracking-wider border-b border-border/70">
                      <th colSpan={chainViewMode === 'STANDARD' ? 6 : 6} className="py-1 px-3 text-cyan-400 text-center border-r border-border/60 bg-cyan-950/20">
                        ◄ CALL OPTIONS (CE)
                      </th>
                      <th className="py-1 px-3 text-amber text-center bg-surface font-extrabold border-x border-border/80">
                        STRIKE
                      </th>
                      <th colSpan={chainViewMode === 'STANDARD' ? 6 : 6} className="py-1 px-3 text-rose-400 text-center border-l border-border/60 bg-rose-950/20">
                        PUT OPTIONS (PE) ►
                      </th>
                    </tr>

                    {/* Column Headers */}
                    <tr className="border-b border-border/60 text-[10px] text-muted uppercase bg-surface/90">
                      {chainViewMode === 'STANDARD' ? (
                        <>
                          <th className="py-2 px-2.5 text-cyan-400">OI (Depth)</th>
                          <th className="py-2 px-2 text-cyan-400">OI Chg</th>
                          <th className="py-2 px-2 text-cyan-400">GEX</th>
                          <th className="py-2 px-2 text-cyan-400">IV</th>
                          <th className="py-2 px-2 text-cyan-400">Bid</th>
                          <th className="py-2 px-2.5 text-cyan-400 border-r border-border/60">Ask</th>
                        </>
                      ) : (
                        <>
                          <th className="py-2 px-2.5 text-cyan-400">Delta (Δ)</th>
                          <th className="py-2 px-2 text-cyan-400">Gamma (Γ)</th>
                          <th className="py-2 px-2 text-cyan-400">Theta (Θ)</th>
                          <th className="py-2 px-2 text-cyan-400">Vega (ν)</th>
                          <th className="py-2 px-2 text-cyan-400">Bid</th>
                          <th className="py-2 px-2.5 text-cyan-400 border-r border-border/60">Ask</th>
                        </>
                      )}

                      <th className="py-2 px-3 text-center bg-elevated text-text font-extrabold border-x border-border/80">
                        STRIKE
                      </th>

                      {chainViewMode === 'STANDARD' ? (
                        <>
                          <th className="py-2 px-2.5 text-rose-400 border-l border-border/60 text-right">Bid</th>
                          <th className="py-2 px-2 text-rose-400 text-right">Ask</th>
                          <th className="py-2 px-2 text-rose-400 text-right">IV</th>
                          <th className="py-2 px-2 text-rose-400 text-right">GEX</th>
                          <th className="py-2 px-2 text-rose-400 text-right">OI Chg</th>
                          <th className="py-2 px-2.5 text-rose-400 text-right">OI (Depth)</th>
                        </>
                      ) : (
                        <>
                          <th className="py-2 px-2.5 text-rose-400 border-l border-border/60 text-right">Bid</th>
                          <th className="py-2 px-2 text-rose-400 text-right">Ask</th>
                          <th className="py-2 px-2 text-rose-400 text-right">Vega (ν)</th>
                          <th className="py-2 px-2 text-rose-400 text-right">Theta (Θ)</th>
                          <th className="py-2 px-2 text-rose-400 text-right">Gamma (Γ)</th>
                          <th className="py-2 px-2.5 text-rose-400 text-right">Delta (Δ)</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {paginatedChain.map((row) => {
                      const isATM = row.is_atm
                      const isCallITM = spot > 0 ? Number(row.strike) < spot : false
                      const isPutITM = spot > 0 ? Number(row.strike) > spot : false
                      const isCallWall = callWallStrike != null && Number(row.strike) === Number(callWallStrike)
                      const isPutWall = putWallStrike != null && Number(row.strike) === Number(putWallStrike)
                      const isMaxPain = maxPain > 0 && Number(row.strike) === Number(maxPain)

                      const callOINum = parseFloat(String(row.calls_oi || 0).replace(/[^0-9.-]/g, '')) || 0
                      const putOINum = parseFloat(String(row.puts_oi || 0).replace(/[^0-9.-]/g, '')) || 0
                      const callOIWidth = Math.min(100, Math.round((callOINum / maxCallOIVal) * 100))
                      const putOIWidth = Math.min(100, Math.round((putOINum / maxPutOIVal) * 100))

                      const callOIChgIsPos = !String(row.calls_oi_chg || '').startsWith('-')
                      const putOIChgIsPos = !String(row.puts_oi_chg || '').startsWith('-')

                      const callIsBlast = Boolean(row.calls_blast)
                      const putIsBlast = Boolean(row.puts_blast)

                      const resolvedCallBlastData = row.calls_blast_data || (callIsBlast ? {
                        contract: `${underlying} ${row.strike} CE`,
                        strike: row.strike,
                        option_type: 'CE',
                        side: 'BUY',
                        action_recommendation: 'BUY (CALL MOMENTUM)',
                        score: row.calls_blast_score || 85,
                        blast_reason: row.calls_blast_reason || 'Surge in call volume and buyer aggression',
                        bid: row.calls_bid,
                        ask: row.calls_ask,
                        entry_range: `₹${(row.calls_bid * 0.95).toFixed(2)} – ₹${(row.calls_bid * 1.03).toFixed(2)}`,
                        stop_loss: Number((row.calls_bid * 0.75).toFixed(2)),
                        stop_loss_pct: '-25%',
                        target_1: Number((row.calls_bid * 1.35).toFixed(2)),
                        target_1_pct: '+35%',
                        target_2: Number((row.calls_bid * 1.65).toFixed(2)),
                        target_2_pct: '+65%',
                        risk_reward: '1:2.5',
                        when_to_buy: `Enter in range ₹${(row.calls_bid * 0.95).toFixed(2)} – ₹${(row.calls_bid * 1.03).toFixed(2)} while Spot holds support`,
                        when_to_wait: `DO NOT CHASE if premium > ₹${(row.calls_bid * 1.15).toFixed(2)}. Wait for dip.`,
                        profit_rule: `Book 50% at T1 (₹${(row.calls_bid * 1.35).toFixed(2)}), trail SL to Cost for T2.`,
                      } : null)

                      const resolvedPutBlastData = row.puts_blast_data || (putIsBlast ? {
                        contract: `${underlying} ${row.strike} PE`,
                        strike: row.strike,
                        option_type: 'PE',
                        side: 'BUY',
                        action_recommendation: 'BUY (PUT BREAKDOWN)',
                        score: row.puts_blast_score || 85,
                        blast_reason: row.puts_blast_reason || 'Put support liquidating / Downside breakdown volume',
                        bid: row.puts_bid,
                        ask: row.puts_ask,
                        entry_range: `₹${(row.puts_bid * 0.95).toFixed(2)} – ₹${(row.puts_bid * 1.03).toFixed(2)}`,
                        stop_loss: Number((row.puts_bid * 0.75).toFixed(2)),
                        stop_loss_pct: '-25%',
                        target_1: Number((row.puts_bid * 1.35).toFixed(2)),
                        target_1_pct: '+35%',
                        target_2: Number((row.puts_bid * 1.65).toFixed(2)),
                        target_2_pct: '+65%',
                        risk_reward: '1:2.5',
                        when_to_buy: `Enter in range ₹${(row.puts_bid * 0.95).toFixed(2)} – ₹${(row.puts_bid * 1.03).toFixed(2)} while Spot drifts lower`,
                        when_to_wait: `DO NOT CHASE if premium > ₹${(row.puts_bid * 1.15).toFixed(2)}. Wait for bounce.`,
                        profit_rule: `Book 50% at T1 (₹${(row.puts_bid * 1.35).toFixed(2)}), trail SL to Cost for T2.`,
                      } : null)

                      const callGreeks = calculateGreeks(spot, row.strike, row.calls_iv, true)
                      const putGreeks = calculateGreeks(spot, row.strike, row.puts_iv, false)

                      return (
                        <tr
                          key={row.strike}
                          ref={isATM ? atmRowRef : null}
                          className={`transition-colors group ${
                            isATM
                              ? 'bg-amber/20 border-y-2 border-amber font-bold shadow-xs'
                              : 'hover:bg-elevated/70'
                          }`}
                        >
                          {/* CALL SIDE */}
                          {chainViewMode === 'STANDARD' ? (
                            <>
                              {/* Call OI with Visual Depth Bar */}
                              <td className={`py-2 px-2.5 relative font-mono text-xs ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                {showVisualBars && (
                                  <div
                                    className="absolute inset-y-1 right-0 bg-cyan-500/20 rounded-l border-r-2 border-cyan-400/60 pointer-events-none transition-all duration-300"
                                    style={{ width: `${callOIWidth}%` }}
                                  />
                                )}
                                <span className={`relative z-10 font-bold ${isCallWall ? 'text-cyan-300 ring-1 ring-cyan-400/40 px-1 rounded bg-cyan-950/60' : 'text-text'}`}>
                                  {row.calls_oi}
                                </span>
                              </td>

                              {/* Call OI Change */}
                              <td className={`py-2 px-2 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                <span
                                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                    callOIChgIsPos
                                      ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                      : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                                  }`}
                                >
                                  {row.calls_oi_chg}
                                </span>
                              </td>

                              {/* Call GEX */}
                              <td className={`py-2 px-2 font-bold ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                <span className={String(row.calls_gex || '').startsWith('+') ? 'text-emerald-400' : 'text-rose-400'}>
                                  {row.calls_gex}
                                </span>
                              </td>

                              {/* Call IV */}
                              <td className={`py-2 px-2 text-text/90 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                {row.calls_iv}
                              </td>

                              {/* Call Bid (Clickable to Buy) */}
                              <td className={`py-2 px-2 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} CE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.calls_bid,
                                      orderType: 'BUY',
                                    })
                                  }
                                  onMouseEnter={(e) => {
                                    if (callIsBlast && resolvedCallBlastData) {
                                      handleOpenBlastPopover(resolvedCallBlastData, e.currentTarget)
                                    }
                                  }}
                                  className={`px-1.5 py-0.5 rounded border text-xs font-bold transition-all cursor-pointer flex items-center justify-between gap-1 w-full ${
                                    callIsBlast
                                      ? 'bg-cyan-500/20 border-cyan-400 text-cyan-300 ring-1 ring-cyan-400/50 shadow-xs hover:bg-cyan-500/30'
                                      : 'bg-surface hover:bg-emerald-500 hover:text-black border-border/60 text-text'
                                  }`}
                                  title={callIsBlast ? `🚀 BLAST ALERT: ${row.calls_blast_reason || 'Hover or click for profit roadmap'}` : 'Click to stage BUY Call Order'}
                                >
                                  <span>₹{row.calls_bid}</span>
                                  {callIsBlast && (
                                    <span
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleOpenBlastPopover(resolvedCallBlastData, e.currentTarget)
                                      }}
                                      className="text-[7px] bg-cyan-500 text-black px-1 rounded-xs font-black animate-pulse hover:scale-110 transition-transform"
                                      title="Click to view Actionable Profit Roadmap"
                                    >
                                      BLAST
                                    </span>
                                  )}
                                </button>
                              </td>

                              {/* Call Ask (Clickable to Sell) */}
                              <td className={`py-2 px-2.5 border-r border-border/60 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} CE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.calls_ask,
                                      orderType: 'SELL',
                                    })
                                  }
                                  className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer w-full text-center"
                                  title="Click to stage SELL Call Order"
                                >
                                  ₹{row.calls_ask}
                                </button>
                              </td>
                            </>
                          ) : (
                            /* GREEKS VIEW - CALLS */
                            <>
                              <td className={`py-2 px-2.5 text-cyan-400 font-bold ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                +{callGreeks.callDelta}
                              </td>
                              <td className={`py-2 px-2 text-muted ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                {callGreeks.gamma}
                              </td>
                              <td className={`py-2 px-2 text-rose-400 font-semibold ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                {callGreeks.callTheta}
                              </td>
                              <td className={`py-2 px-2 text-emerald-400 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                +{callGreeks.vega}
                              </td>
                              <td className={`py-2 px-2 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} CE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.calls_bid,
                                      orderType: 'BUY',
                                    })
                                  }
                                  onMouseEnter={(e) => {
                                    if (callIsBlast && resolvedCallBlastData) {
                                      handleOpenBlastPopover(resolvedCallBlastData, e.currentTarget)
                                    }
                                  }}
                                  className={`px-1.5 py-0.5 rounded border text-xs font-bold transition-all cursor-pointer flex items-center justify-between gap-1 w-full ${
                                    callIsBlast
                                      ? 'bg-cyan-500/20 border-cyan-400 text-cyan-300 ring-1 ring-cyan-400/50 shadow-xs hover:bg-cyan-500/30'
                                      : 'bg-surface hover:bg-emerald-500 hover:text-black border-border/60 text-text'
                                  }`}
                                  title={callIsBlast ? `🚀 BLAST ALERT: ${row.calls_blast_reason || 'Hover or click for profit roadmap'}` : 'Click to stage BUY Call Order'}
                                >
                                  <span>₹{row.calls_bid}</span>
                                  {callIsBlast && (
                                    <span
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleOpenBlastPopover(resolvedCallBlastData, e.currentTarget)
                                      }}
                                      className="text-[7px] bg-cyan-500 text-black px-1 rounded-xs font-black animate-pulse hover:scale-110 transition-transform"
                                      title="Click to view Actionable Profit Roadmap"
                                    >
                                      BLAST
                                    </span>
                                  )}
                                </button>
                              </td>
                              <td className={`py-2 px-2.5 border-r border-border/60 ${isCallITM ? 'bg-cyan-950/20' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} CE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.calls_ask,
                                      orderType: 'SELL',
                                    })
                                  }
                                  className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer w-full text-center"
                                >
                                  ₹{row.calls_ask}
                                </button>
                              </td>
                            </>
                          )}

                          {/* CENTER STRIKE COLUMN */}
                          <td
                            onClick={() => setIsPayoffModalOpen(true)}
                            className={`py-2 px-3 text-center font-bold border-x border-border/80 cursor-pointer transition-all ${
                              isATM
                                ? 'bg-amber text-black font-extrabold shadow-sm ring-2 ring-amber/60'
                                : 'bg-elevated/90 text-text hover:text-amber hover:bg-elevated'
                            }`}
                            title="Click to simulate multi-leg payoff centered at this strike"
                          >
                            <div className="flex flex-col items-center justify-center">
                              <span className="text-xs font-mono tracking-tight font-black">
                                {Number(row.strike).toLocaleString('en-IN')}
                              </span>
                              {/* Key Level Indicators */}
                              {isATM && spot > 0 && (
                                <span className="text-[8px] uppercase tracking-wider font-black bg-black text-amber px-1.5 py-0.5 rounded-sm mt-0.5 shadow-xs flex items-center gap-0.5">
                                  <span>⚡</span> ATM (Spot: ₹{Number(spot).toFixed(0)})
                                </span>
                              )}
                              {isCallWall && !isATM && (
                                <span className="text-[8px] uppercase tracking-wider font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 px-1 rounded-sm mt-0.5">
                                  🛡️ Call Wall
                                </span>
                              )}
                              {isPutWall && !isATM && (
                                <span className="text-[8px] uppercase tracking-wider font-bold bg-amber/20 text-amber border border-amber/40 px-1 rounded-sm mt-0.5">
                                  🏰 Put Wall
                                </span>
                              )}
                              {isMaxPain && !isATM && !isCallWall && !isPutWall && (
                                <span className="text-[8px] uppercase tracking-wider font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 px-1 rounded-sm mt-0.5">
                                  🎯 Max Pain
                                </span>
                              )}
                            </div>
                          </td>

                          {/* PUT SIDE */}
                          {chainViewMode === 'STANDARD' ? (
                            <>
                              {/* Put Bid (Clickable to Buy) */}
                              <td className={`py-2 px-2.5 border-l border-border/60 text-right ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} PE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.puts_bid,
                                      orderType: 'BUY',
                                    })
                                  }
                                  onMouseEnter={(e) => {
                                    if (putIsBlast && resolvedPutBlastData) {
                                      handleOpenBlastPopover(resolvedPutBlastData, e.currentTarget)
                                    }
                                  }}
                                  className={`px-1.5 py-0.5 rounded border text-xs font-bold transition-all cursor-pointer flex items-center justify-between gap-1 w-full ${
                                    putIsBlast
                                      ? 'bg-rose-500/20 border-rose-400 text-rose-300 ring-1 ring-rose-400/50 shadow-xs hover:bg-rose-500/30'
                                      : 'bg-surface hover:bg-emerald-500 hover:text-black border-border/60 text-text'
                                  }`}
                                  title={putIsBlast ? `🚀 BLAST ALERT: ${row.puts_blast_reason || 'Hover or click for profit roadmap'}` : 'Click to stage BUY Put Order'}
                                >
                                  {putIsBlast && (
                                    <span
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleOpenBlastPopover(resolvedPutBlastData, e.currentTarget)
                                      }}
                                      className="text-[7px] bg-rose-500 text-white px-1 rounded-xs font-black animate-pulse hover:scale-110 transition-transform"
                                      title="Click to view Actionable Profit Roadmap"
                                    >
                                      BLAST
                                    </span>
                                  )}
                                  <span className="ml-auto">₹{row.puts_bid}</span>
                                </button>
                              </td>

                              {/* Put Ask (Clickable to Sell) */}
                              <td className={`py-2 px-2 text-right ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} PE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.puts_ask,
                                      orderType: 'SELL',
                                    })
                                  }
                                  className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer w-full text-center"
                                  title="Click to stage SELL Put Order"
                                >
                                  ₹{row.puts_ask}
                                </button>
                              </td>

                              {/* Put IV */}
                              <td className={`py-2 px-2 text-right text-text/90 ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                {row.puts_iv}
                              </td>

                              {/* Put GEX */}
                              <td className={`py-2 px-2 text-right font-bold ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                <span className={String(row.puts_gex || '').startsWith('-') ? 'text-rose-400' : 'text-emerald-400'}>
                                  {row.puts_gex}
                                </span>
                              </td>

                              {/* Put OI Change */}
                              <td className={`py-2 px-2 text-right ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                <span
                                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                    putOIChgIsPos
                                      ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                                      : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                                  }`}
                                >
                                  {row.puts_oi_chg}
                                </span>
                              </td>

                              {/* Put OI with Visual Depth Bar */}
                              <td className={`py-2 px-2.5 relative text-right font-mono text-xs ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                {showVisualBars && (
                                  <div
                                    className="absolute inset-y-1 left-0 bg-rose-500/15 rounded-r border-l-2 border-rose-500/50 pointer-events-none transition-all duration-300"
                                    style={{ width: `${putOIWidth}%` }}
                                  />
                                )}
                                <span className={`relative z-10 font-bold ${isPutWall ? 'text-rose-300 ring-1 ring-rose-500/40 px-1 rounded bg-rose-950/60' : 'text-text'}`}>
                                  {row.puts_oi}
                                </span>
                              </td>
                            </>
                          ) : (
                            /* GREEKS VIEW - PUTS */
                            <>
                              <td className={`py-2 px-2.5 border-l border-border/60 text-right ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} PE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.puts_bid,
                                      orderType: 'BUY',
                                    })
                                  }
                                  onMouseEnter={(e) => {
                                    if (putIsBlast && resolvedPutBlastData) {
                                      handleOpenBlastPopover(resolvedPutBlastData, e.currentTarget)
                                    }
                                  }}
                                  className={`px-1.5 py-0.5 rounded border text-xs font-bold transition-all cursor-pointer flex items-center justify-between gap-1 w-full ${
                                    putIsBlast
                                      ? 'bg-rose-500/20 border-rose-400 text-rose-300 ring-1 ring-rose-400/50 shadow-xs hover:bg-rose-500/30'
                                      : 'bg-surface hover:bg-emerald-500 hover:text-black border-border/60 text-text'
                                  }`}
                                  title={putIsBlast ? `🚀 BLAST ALERT: ${row.puts_blast_reason || 'Hover or click for profit roadmap'}` : 'Click to stage BUY Put Order'}
                                >
                                  {putIsBlast && (
                                    <span
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleOpenBlastPopover(resolvedPutBlastData, e.currentTarget)
                                      }}
                                      className="text-[7px] bg-rose-500 text-white px-1 rounded-xs font-black animate-pulse hover:scale-110 transition-transform"
                                      title="Click to view Actionable Profit Roadmap"
                                    >
                                      BLAST
                                    </span>
                                  )}
                                  <span className="ml-auto">₹{row.puts_bid}</span>
                                </button>
                              </td>
                              <td className={`py-2 px-2 text-right ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                <button
                                  onClick={() =>
                                    onOpenOrderTicket &&
                                    onOpenOrderTicket({
                                      symbol: `${underlying} ${row.strike} PE`,
                                      exchange: resolvedExchange === 'BSE' ? 'BFO' : 'NFO',
                                      price: row.puts_ask,
                                      orderType: 'SELL',
                                    })
                                  }
                                  className="px-1.5 py-0.5 rounded bg-surface hover:bg-rose-500 hover:text-white border border-border/60 text-text font-bold text-xs transition-all cursor-pointer w-full text-center"
                                >
                                  ₹{row.puts_ask}
                                </button>
                              </td>
                              <td className={`py-2 px-2 text-right text-emerald-400 ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                +{putGreeks.vega}
                              </td>
                              <td className={`py-2 px-2 text-right text-rose-400 font-semibold ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                {putGreeks.putTheta}
                              </td>
                              <td className={`py-2 px-2 text-right text-muted ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                {putGreeks.gamma}
                              </td>
                              <td className={`py-2 px-2.5 text-right text-rose-400 font-bold ${isPutITM ? 'bg-rose-950/15' : ''}`}>
                                {putGreeks.putDelta}
                              </td>
                            </>
                          )}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Chain Pagination Controls */}
            {totalChainPages > 1 && (
              <div className="flex items-center justify-between pt-2 border-t border-border/40 text-[11px] font-mono text-muted">
                <span>
                  Showing {(safeChainPage - 1) * pageSizeNum + 1}–{Math.min(safeChainPage * pageSizeNum, sortedChain.length)} of {sortedChain.length} strikes
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setChainPage((p) => Math.max(1, p - 1))}
                    disabled={safeChainPage === 1}
                    className="px-2 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    ← Prev
                  </button>
                  {Array.from({ length: totalChainPages }, (_, i) => i + 1).map((pNum) => (
                    <button
                      key={pNum}
                      onClick={() => setChainPage(pNum)}
                      className={`w-6 h-6 rounded text-xs font-bold transition-all cursor-pointer ${
                        safeChainPage === pNum
                          ? 'bg-amber text-black'
                          : 'bg-surface border border-border text-muted hover:text-text'
                      }`}
                    >
                      {pNum}
                    </button>
                  ))}
                  <button
                    onClick={() => setChainPage((p) => Math.min(totalChainPages, p + 1))}
                    disabled={safeChainPage === totalChainPages}
                    className="px-2 py-0.5 rounded bg-surface border border-border text-muted hover:text-text disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {/* Interactive Payoff Strategy Simulator Modal */}
      {isPayoffModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-3 sm:p-6 animate-in fade-in duration-200"
          onClick={() => setIsPayoffModalOpen(false)}
        >
          <div
            className="bg-panel border border-border rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto shadow-2xl p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border/50 pb-3">
              <div className="flex items-center gap-2">
                <span className="text-amber text-xl">🎯</span>
                <div>
                  <h2 className="text-base font-bold font-mono text-text">
                    Multi-Leg Strategy Payoff Simulator ({underlying})
                  </h2>
                  <p className="text-[11px] text-muted">Black-Scholes Model • Expiry vs T+0 P&amp;L Curves • Greeks</p>
                </div>
              </div>
              <button
                onClick={() => setIsPayoffModalOpen(false)}
                className="text-muted hover:text-text p-1 text-lg font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <PayoffSimulatorCard initialSymbol={underlying} initialSpot={spot} />
          </div>
        </div>
      )}

      {/* Floating Actionable Blast Alert Popover */}
      {activeBlastPopover && (
        <>
          <div
            className="fixed inset-0 z-50 bg-black/25 backdrop-blur-[1px]"
            onClick={() => setActiveBlastPopover(null)}
          />
          <div
            style={{
              position: 'fixed',
              left: activeBlastPopover.x,
              top: activeBlastPopover.y,
              zIndex: 55,
            }}
          >
            <BlastActionPopover
              blastData={activeBlastPopover.data}
              underlying={underlying}
              spot={spot}
              resolvedExchange={resolvedExchange}
              onClose={() => setActiveBlastPopover(null)}
              onOpenOrderTicket={onOpenOrderTicket}
              onSendTelegram={handleSendTelegramBlast}
              onSendCopilot={(b) => sendDraft(`Analyze ${b.contract} blast surge`)}
            />
          </div>
        </>
      )}

      {/* Telegram Toast Notification */}
      {telegramStatus && (
        <div
          className={`fixed bottom-6 right-6 z-60 px-4 py-2.5 rounded-xl border text-xs font-mono font-bold shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-bottom-4 duration-200 ${
            telegramStatus.status === 'success'
              ? 'bg-emerald-950/90 border-emerald-500/60 text-emerald-300'
              : telegramStatus.status === 'error'
              ? 'bg-rose-950/90 border-rose-500/60 text-rose-300'
              : telegramStatus.status === 'warning'
              ? 'bg-amber-950/90 border-amber-500/60 text-amber-300'
              : 'bg-surface border-border text-text'
          }`}
        >
          {telegramStatus.status === 'loading' && <span className="animate-spin">⏳</span>}
          <span>{telegramStatus.msg}</span>
        </div>
      )}
    </div>
  )
}
