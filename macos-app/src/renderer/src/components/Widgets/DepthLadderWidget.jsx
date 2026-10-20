import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { getBaseUrl } from '../../store/chatStore'

/**
 * DepthLadderWidget — Institutional DOM (Depth of Market) Ladder Widget
 *
 * Visualizes real-time L2/L3 order book microstructure:
 * - 10-level Bid & Ask ladder with volume distribution bars
 * - Dynamic Order Book Imbalance (OBI) gradient meter (-1.0 to +1.0)
 * - Micro-price indicator & skew calculation vs arithmetic mid-price
 * - Automated resting fortress wall detection (>= 2.8x average depth)
 * - Iceberg absorption detection badge
 * - One-click interactive price selection for seamless order ticket entry
 * - Strict provenance honesty (LIVE_BROKER_L2 vs FEED_L1_DEPTH vs SYNTHETIC_L1_DISCONNECTED)
 */
export default function DepthLadderWidget({
  symbol,
  compact = false,
  onPriceSelect,
  currentPrice = null,
  stopLoss = null,
  target = null,
  noChaseBoundary = null,
  refreshIntervalMs = 2500,
}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const isMountedRef = useRef(true)

  const cleanSymbol = useMemo(() => {
    if (!symbol) return ''
    const s = String(symbol).trim().toUpperCase()
    if (s.startsWith('MCX:') || s.startsWith('CDS:') || s.startsWith('CRYPTO:')) return s
    const stripped = s.replace(/^(NSE|BSE|NFO):/, '').trim()
    if (
      ['CRUDEOIL', 'NATURALGAS', 'GOLD', 'SILVER', 'COPPER', 'ZINC', 'ALUMINIUM'].some(
        (c) => stripped.startsWith(c) && (stripped.endsWith('FUT') || stripped.includes('CE') || stripped.includes('PE'))
      )
    ) {
      return `MCX:${stripped}`
    }
    return stripped
  }, [symbol])

  const fetchDepth = useCallback(async () => {
    if (!cleanSymbol) return
    try {
      const baseUrl = getBaseUrl ? getBaseUrl() : 'http://127.0.0.1:8765'
      const res = await fetch(`${baseUrl}/api/market/order-book/${encodeURIComponent(cleanSymbol)}`, {
        headers: { Accept: 'application/json' },
      })
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Depth feed unavailable`)
      }
      const json = await res.json()
      if (isMountedRef.current && json && json.data) {
        setData(json.data)
        setError(null)
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err.message || 'Depth feed error')
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false)
      }
    }
  }, [cleanSymbol])

  useEffect(() => {
    isMountedRef.current = true
    setLoading(true)
    fetchDepth()

    // 1. Attempt sub-100ms real-time SSE stream with polling fallback
    let eventSource = null
    let pollInterval = null
    const baseUrl = getBaseUrl ? getBaseUrl() : 'http://127.0.0.1:8765'

    if (typeof EventSource !== 'undefined' && cleanSymbol) {
      try {
        const streamUrl = `${baseUrl}/api/market/order-book/${encodeURIComponent(cleanSymbol)}/stream`
        eventSource = new EventSource(streamUrl)

        eventSource.onmessage = (event) => {
          if (!isMountedRef.current || !event.data) return
          try {
            const parsed = JSON.parse(event.data)
            if (parsed?.data) {
              setData(parsed.data)
              setError(null)
              setLoading(false)
            }
          } catch (_) {
            // Heartbeat frame or comment
          }
        }

        eventSource.onerror = () => {
          if (eventSource) {
            eventSource.close()
            eventSource = null
          }
          if (!pollInterval && isMountedRef.current) {
            pollInterval = setInterval(fetchDepth, refreshIntervalMs)
          }
        }
      } catch (_) {
        pollInterval = setInterval(fetchDepth, refreshIntervalMs)
      }
    } else {
      pollInterval = setInterval(fetchDepth, refreshIntervalMs)
    }

    return () => {
      isMountedRef.current = false
      if (eventSource) eventSource.close()
      if (pollInterval) clearInterval(pollInterval)
    }
  }, [cleanSymbol, fetchDepth, refreshIntervalMs])

  // Extract levels and compute wall thresholds
  const {
    bids,
    asks,
    maxBidQty,
    maxAskQty,
    avgBidQty,
    avgAskQty,
    spread,
    spreadBps,
    obi,
    bias,
    provenance,
    microPrice,
    microSkew,
    iceberg,
    greeks,
  } = useMemo(() => {
    if (!data) {
      return {
        bids: [],
        asks: [],
        maxBidQty: 1,
        maxAskQty: 1,
        avgBidQty: 1,
        avgAskQty: 1,
        spread: 0,
        spreadBps: 0,
        obi: 0,
        bias: 'BALANCED',
        provenance: 'DISCONNECTED',
        microPrice: null,
        microSkew: 0,
        iceberg: null,
        greeks: null,
      }
    }

    const rawBids = Array.isArray(data.bids) ? data.bids : []
    const rawAsks = Array.isArray(data.asks) ? data.asks : []

    const numLevels = compact ? 5 : 10
    const bSlice = rawBids.slice(0, numLevels)
    const aSlice = rawAsks.slice(0, numLevels)

    const bQtys = bSlice.map((b) => Number(b.quantity || b.qty || 0))
    const aQtys = aSlice.map((a) => Number(a.quantity || a.qty || 0))

    const maxB = Math.max(1, ...bQtys)
    const maxA = Math.max(1, ...aQtys)
    const avgB = bQtys.length > 0 ? bQtys.reduce((acc, q) => acc + q, 0) / bQtys.length : 1
    const avgA = aQtys.length > 0 ? aQtys.reduce((acc, q) => acc + q, 0) / aQtys.length : 1

    const sp = Number(data.spread || 0)
    const ltp = Number(data.ltp || currentPrice || 0)
    const spBps = ltp > 0 ? (sp / ltp) * 10000 : 0
    const obiVal = Number(data.obi_5 ?? data.obi_weighted ?? 0)

    const bestB = bSlice[0] ? Number(bSlice[0].price || 0) : 0
    const bestA = aSlice[0] ? Number(aSlice[0].price || 0) : 0
    const mid = bestB > 0 && bestA > 0 ? (bestB + bestA) / 2 : ltp
    const bTopQ = bSlice[0] ? Number(bSlice[0].quantity || 0) : 0
    const aTopQ = aSlice[0] ? Number(aSlice[0].quantity || 0) : 0

    let calcMicro = null
    let skew = 0
    if (bTopQ + aTopQ > 0 && bestB > 0 && bestA > 0) {
      calcMicro = (bestB * aTopQ + bestA * bTopQ) / (bTopQ + aTopQ)
      skew = calcMicro - mid
    }

    return {
      bids: bSlice,
      asks: aSlice,
      maxBidQty: maxB,
      maxAskQty: maxA,
      avgBidQty: avgB,
      avgAskQty: avgA,
      spread: sp,
      spreadBps: spBps,
      obi: obiVal,
      bias: data.bias || 'BALANCED',
      provenance: data.provenance || data.broker_depth_status || 'SYNTHETIC_L1_DISCONNECTED',
      microPrice: calcMicro,
      microSkew: skew,
      iceberg: (data.iceberg_detected || data.is_iceberg_suspected)
        ? { side: data.iceberg_side || data.wall_side || 'BID', price: data.iceberg_price || data.wall_price }
        : null,
      greeks: data.greeks || null,
    }
  }, [data, compact, currentPrice])

  const provenanceBadge = useMemo(() => {
    if (provenance.includes('LIVE')) {
      return (
        <span
          className="text-[8px] font-black font-mono px-1.5 py-0.5 rounded border border-emerald-500/40 bg-emerald-500/20 text-emerald-300"
          title="Direct Level-2 broker depth feed streaming"
        >
          🟢 LIVE L2
        </span>
      )
    }
    if (provenance.includes('FEED') || provenance.includes('L1')) {
      return (
        <span
          className="text-[8px] font-black font-mono px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/20 text-amber-300"
          title="Exchange L1 broadcast depth"
        >
          🟡 L1 FEED
        </span>
      )
    }
    return (
      <span
        className="text-[8px] font-black font-mono px-1.5 py-0.5 rounded border border-zinc-700 bg-zinc-800 text-zinc-400"
        title="Offline / disconnected simulator mode"
      >
        🧪 SIM DEPTH
      </span>
    )
  }, [provenance])

  const obiPct = useMemo(() => {
    // Map -1.0 to 1.0 to 0% to 100%
    return Math.min(100, Math.max(0, ((obi + 1) / 2) * 100))
  }, [obi])

  return (
    <div className="bg-panel border border-border/80 rounded-xl p-2.5 font-mono text-[11px] select-none text-text shadow-lg">
      {/* Header Bar */}
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-border/50 text-[10px]">
        <div className="flex items-center gap-2">
          <span className="font-bold text-text text-xs tracking-tight">{cleanSymbol}</span>
          {provenanceBadge}
          {iceberg && (
            <span
              className="text-[8px] font-black px-1 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 animate-pulse"
              title={`Hidden iceberg detected absorbing on ${iceberg.side} side at ₹${iceberg.price}`}
            >
              🧊 ICEBERG {iceberg.side}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-muted">
          <span>
            Spread: <strong className="text-text font-bold">₹{spread.toFixed(2)}</strong> (
            <span className={spreadBps > 30 ? 'text-rose-400' : 'text-emerald-400'}>
              {spreadBps.toFixed(1)} bps
            </span>
            )
          </span>
          {microPrice !== null && (
            <span title="Volume-weighted micro-price skew">
              Micro: <strong className="text-sky-300 font-bold">₹{microPrice.toFixed(2)}</strong> (
              <span className={microSkew >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                {microSkew >= 0 ? '+' : ''}
                {microSkew.toFixed(2)}
              </span>
              )
            </span>
          )}
        </div>
      </div>

      {/* Option Greeks Ribbon (if contract is an option) */}
      {greeks && (
        <div className="mb-2 py-1 px-2 rounded-lg bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-between text-[10px] font-mono flex-wrap gap-1">
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-indigo-300">
              {greeks.option_type || 'OPT'} ₹{greeks.strike}
            </span>
            <span className="text-[9px] text-muted">
              (Spot: ₹{Number(greeks.spot || 0).toLocaleString('en-IN')})
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <span title="Delta: Price change per ₹1 underlying spot move">
              Δ <strong className="text-emerald-400">{greeks.delta != null ? greeks.delta : '—'}</strong>
            </span>
            <span title="Gamma: Rate of change of Delta">
              Γ <strong className="text-cyan-400">{greeks.gamma != null ? greeks.gamma : '—'}</strong>
            </span>
            <span title="Theta: Daily time-decay in rupees">
              Θ <strong className="text-rose-400">{greeks.theta != null ? `₹${greeks.theta}` : '—'}</strong>
            </span>
            <span title="Vega: Sensitivity per 1% change in IV">
              ν <strong className="text-amber-400">{greeks.vega != null ? greeks.vega : '—'}</strong>
            </span>
            <span title="Implied Volatility (Annualized)">
              IV <strong className="text-purple-300 font-bold">{greeks.iv_pct != null ? `${greeks.iv_pct}%` : '—'}</strong>
            </span>
          </div>
        </div>
      )}

      {/* OBI Imbalance Gauge */}
      <div className="mb-2.5 bg-elevated/60 border border-border/40 rounded-lg p-1.5">
        <div className="flex items-center justify-between text-[9px] mb-1 font-semibold">
          <span className="text-rose-400">Ask Pressure (Distribution)</span>
          <span
            className={`font-black ${
              obi > 0.2 ? 'text-emerald-400' : obi < -0.2 ? 'text-rose-400' : 'text-amber-400'
            }`}
          >
            OBI: {obi >= 0 ? '+' : ''}
            {obi.toFixed(2)} ({bias.replace('_', ' ')})
          </span>
          <span className="text-emerald-400">Bid Pressure (Accumulation)</span>
        </div>
        <div className="relative h-1.5 bg-zinc-800 rounded-full overflow-hidden flex">
          <div
            className="h-full bg-gradient-to-r from-rose-500 via-amber-500 to-emerald-500 w-full"
            style={{ opacity: 0.85 }}
          />
          <div
            className="absolute top-0 bottom-0 w-1.5 bg-white rounded-full shadow-[0_0_6px_rgba(255,255,255,1)] transform -translate-x-1/2 transition-all duration-300"
            style={{ left: `${obiPct}%` }}
          />
        </div>
      </div>

      {/* DOM Table Headers */}
      <div className="grid grid-cols-11 gap-1 text-[9px] font-bold text-muted pb-1 mb-1 border-b border-border/40 uppercase tracking-wider text-center">
        <div className="col-span-1 text-left pl-1">Ord</div>
        <div className="col-span-3 text-right">Bid Qty</div>
        <div className="col-span-3 text-center text-text font-black">Price (L2)</div>
        <div className="col-span-3 text-left">Ask Qty</div>
        <div className="col-span-1 text-right pr-1">Ord</div>
      </div>

      {/* DOM Ladder Body */}
      {loading && !data ? (
        <div className="py-8 text-center text-muted animate-pulse text-xs">
          Connecting to Level-2 order book depth…
        </div>
      ) : error && !data ? (
        <div className="py-6 text-center text-rose-400 text-xs">⚠️ {error}</div>
      ) : (
        <div className="space-y-0.5 max-h-[320px] overflow-y-auto pr-0.5">
          {/* Ask Rows (Reversed so lowest ask is at center adjacent to highest bid) */}
          {[...asks].reverse().map((ask, idx) => {
            const p = Number(ask.price || 0)
            const q = Number(ask.quantity || ask.qty || 0)
            const o = Number(ask.orders || ask.ord || 1)
            const barW = maxAskQty > 0 ? Math.min(100, Math.round((q / maxAskQty) * 100)) : 0
            const isWall = avgAskQty > 0 && q / avgAskQty >= 2.8 && q >= 100
            const wallRatio = avgAskQty > 0 ? (q / avgAskQty).toFixed(1) : '1.0'
            const isInside = idx === asks.length - 1 // Lowest ask

            return (
              <div
                key={`ask-${p}-${idx}`}
                onClick={() => onPriceSelect && onPriceSelect(p)}
                className={`grid grid-cols-11 gap-1 items-center py-0.5 rounded transition-colors cursor-pointer hover:bg-rose-500/10 ${
                  isInside ? 'bg-rose-950/20 border-b border-rose-500/30' : ''
                }`}
                title={`Click to set limit price to ₹${p.toFixed(2)}`}
              >
                <div className="col-span-1 text-muted text-left pl-1 text-[9px]">-</div>
                <div className="col-span-3 text-muted text-right text-[10px]">-</div>

                {/* Price Cell */}
                <div className="col-span-3 text-center font-bold text-[11px] text-rose-300 relative">
                  ₹{p.toFixed(2)}
                  {noChaseBoundary && p >= noChaseBoundary && (
                    <span
                      className="ml-1 text-[8px] px-1 py-px rounded bg-amber-500/20 text-amber-300 border border-amber-500/30"
                      title="No Chase Ceiling"
                    >
                      🛑 NO CHASE
                    </span>
                  )}
                  {target && Math.abs(p - target) < 1.0 && (
                    <span
                      className="ml-1 text-[8px] px-1 py-px rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                      title="Target 1 Anchor"
                    >
                      🎯 T1
                    </span>
                  )}
                </div>

                {/* Ask Qty with Visual Volume Bar */}
                <div className="col-span-3 relative flex items-center">
                  <div
                    className="absolute top-0 bottom-0 left-0 bg-rose-500/20 border-r border-rose-500/40 rounded-r"
                    style={{ width: `${barW}%` }}
                  />
                  <div className="relative z-10 pl-1.5 flex items-center gap-1 font-semibold text-rose-200">
                    <span>{q.toLocaleString('en-IN')}</span>
                    {isWall && (
                      <span
                        className="text-[7px] font-black px-1 py-px rounded bg-amber-500/25 text-amber-300 border border-amber-500/50 uppercase"
                        title={`🏰 BEARISH SUPPLY CEILING (${wallRatio}x avg ask depth): Heavy institutional limit selling blocks upside. Do not chase breakout into wall; take profit or look for exhaustion rejection with SL above ₹${p.toFixed(2)}.`}
                      >
                        🏰 {wallRatio}x
                      </span>
                    )}
                  </div>
                </div>

                <div className="col-span-1 text-right pr-1 text-muted text-[9px]">{o}</div>
              </div>
            )
          })}

          {/* Spread Indicator Divider */}
          <div className="py-1 px-2 my-0.5 rounded bg-zinc-800/80 border border-border/60 flex items-center justify-between text-[9px] font-bold text-muted">
            <span className="text-emerald-400">BEST BID</span>
            <span className="text-text font-black tracking-wider">
              SPREAD: ₹{spread.toFixed(2)}
            </span>
            <span className="text-rose-400">BEST ASK</span>
          </div>

          {/* Bid Rows (Top Bid at the top, descending) */}
          {bids.map((bid, idx) => {
            const p = Number(bid.price || 0)
            const q = Number(bid.quantity || bid.qty || 0)
            const o = Number(bid.orders || bid.ord || 1)
            const barW = maxBidQty > 0 ? Math.min(100, Math.round((q / maxBidQty) * 100)) : 0
            const isWall = avgBidQty > 0 && q / avgBidQty >= 2.8 && q >= 100
            const wallRatio = avgBidQty > 0 ? (q / avgBidQty).toFixed(1) : '1.0'
            const isInside = idx === 0 // Highest bid

            return (
              <div
                key={`bid-${p}-${idx}`}
                onClick={() => onPriceSelect && onPriceSelect(p)}
                className={`grid grid-cols-11 gap-1 items-center py-0.5 rounded transition-colors cursor-pointer hover:bg-emerald-500/10 ${
                  isInside ? 'bg-emerald-950/20 border-t border-emerald-500/30' : ''
                }`}
                title={`Click to set limit price to ₹${p.toFixed(2)}`}
              >
                <div className="col-span-1 text-left pl-1 text-muted text-[9px]">{o}</div>

                {/* Bid Qty with Visual Volume Bar */}
                <div className="col-span-3 relative flex items-center justify-end">
                  <div
                    className="absolute top-0 bottom-0 right-0 bg-emerald-500/20 border-l border-emerald-500/40 rounded-l"
                    style={{ width: `${barW}%` }}
                  />
                  <div className="relative z-10 pr-1.5 flex items-center gap-1 font-semibold text-emerald-200">
                    {isWall && (
                      <span
                        className="text-[7px] font-black px-1 py-px rounded bg-amber-500/25 text-amber-300 border border-amber-500/50 uppercase"
                        title={`🛡️ BULLISH DEMAND FLOOR (${wallRatio}x avg bid depth): Institutional accumulation absorbing selling pressure. Dips into ₹${p.toFixed(2)} are high-probability bounce zones. Anchor SL below this floor.`}
                      >
                        🛡️ {wallRatio}x
                      </span>
                    )}
                    <span>{q.toLocaleString('en-IN')}</span>
                  </div>
                </div>

                {/* Price Cell */}
                <div className="col-span-3 text-center font-bold text-[11px] text-emerald-300 relative">
                  ₹{p.toFixed(2)}
                  {stopLoss && Math.abs(p - stopLoss) < 1.0 && (
                    <span
                      className="ml-1 text-[8px] px-1 py-px rounded bg-rose-500/20 text-rose-300 border border-rose-500/30"
                      title="Stop-Loss Invalidation Anchor"
                    >
                      🛡️ SL
                    </span>
                  )}
                </div>

                <div className="col-span-3 text-muted text-left text-[10px]">-</div>
                <div className="col-span-1 text-muted text-right pr-1 text-[9px]">-</div>
              </div>
            )
          })}
        </div>
      )}

      {/* Footer / Instructions */}
      <div className="pt-2 mt-2 border-t border-border/40 flex items-center justify-between text-[9px] text-muted">
        <span>💡 Click any price rung to populate order ticket limit</span>
        <button
          type="button"
          onClick={fetchDepth}
          className="text-muted hover:text-text cursor-pointer transition-colors"
          title="Manual refresh"
        >
          🔄 Refresh
        </button>
      </div>
    </div>
  )
}
