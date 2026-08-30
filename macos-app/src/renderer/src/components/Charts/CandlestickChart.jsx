import { useEffect, useRef, useState, memo, useCallback } from 'react'
import { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts'
import { useAPI } from '../../hooks/useAPI'

function CandlestickChartComponent({
  symbol = 'NIFTY',
  exchange = 'NSE',
  height = 280,
  timeframe = '15m',
  onCloseFullscreen = null,
  isModalView = false,
}) {
  const chartContainerRef = useRef(null)
  const stochContainerRef = useRef(null)
  const chartRef = useRef(null)
  const stochChartRef = useRef(null)

  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)
  const sma20Ref = useRef(null)
  const sma50Ref = useRef(null)
  const sma200Ref = useRef(null)
  const stochKSeriesRef = useRef(null)
  const stochDSeriesRef = useRef(null)

  // Track active price lines to cleanly clear & update without ghost lines
  const activePriceLinesRef = useRef([])

  // Direct DOM refs for high-performance legend updates without React re-renders
  const ohlcTextRef = useRef(null)

  const { call } = useAPI()
  const [interval, setIntervalVal] = useState(timeframe || '15m')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chartData, setChartData] = useState(null)

  // Dynamic visual coordinates for Order Block shaded background ribbons
  const [obZones, setObZones] = useState([])

  // Active Indicator State Toggles
  const [showIndicators, setShowIndicators] = useState({
    sma20: true,
    sma50: true,
    sma200: false,
    volume: true,
    orderBlocks: true,     // SMC Unmitigated Demand & Supply Order Blocks
    volumeProfile: true,   // POC, VAH, VAL levels
    stochRSI: true,        // Stochastic RSI sub-pane (Active by default)
    divergences: true,     // RSI Bull/Bear Divergence markers (Active by default)
  })

  const [isFullscreen, setIsFullscreen] = useState(false)

  const getIsDark = () =>
    typeof document !== 'undefined' &&
    (document.documentElement.classList.contains('dark') || !document.documentElement.classList.contains('light'))

  // Sync timeframe prop
  useEffect(() => {
    if (timeframe) {
      const mapped = timeframe === '1D' ? 'day' : timeframe
      setIntervalVal(mapped)
    }
  }, [timeframe])

  // Helper: Deduplicate and sort strictly ascending by time for Lightweight Charts
  const sanitizeSeries = (arr) => {
    if (!Array.isArray(arr) || arr.length === 0) return []
    const seen = new Map()
    for (const item of arr) {
      if (item && item.time != null) {
        const key = typeof item.time === 'object' ? `${item.time.year}-${item.time.month}-${item.time.day}` : String(item.time)
        seen.set(key, item)
      }
    }
    const sorted = Array.from(seen.values()).sort((a, b) => {
      const tA = typeof a.time === 'number' ? a.time : String(a.time)
      const tB = typeof b.time === 'number' ? b.time : String(b.time)
      return tA > tB ? 1 : tA < tB ? -1 : 0
    })
    return sorted
  }

  const lastCandleRef = useRef(null)

  // Update Legend DOM directly without triggering React re-renders
  const updateLegendDOM = (bar) => {
    try {
      if (!ohlcTextRef.current) return
      if (!bar || typeof bar !== 'object' || bar.open == null || bar.close == null) {
        ohlcTextRef.current.innerHTML = ''
        return
      }
      const open = Number(bar.open)
      const high = Number(bar.high ?? open)
      const low = Number(bar.low ?? open)
      const close = Number(bar.close)
      const vol = Number(bar.volume ?? 0)
      const chg = close - open
      const chgPct = open !== 0 ? (chg / open) * 100 : 0
      const isPos = chg >= 0
      const colorClass = isPos ? 'text-emerald-500 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400'
      const sign = isPos ? '+' : ''
      const volStr = vol >= 1e7 ? `${(vol / 1e7).toFixed(2)}Cr` : vol >= 1e5 ? `${(vol / 1e5).toFixed(2)}L` : vol >= 1e3 ? `${(vol / 1e3).toFixed(1)}k` : vol.toString()
      const rvolStr = bar.rvol ? ` (${bar.rvol}x)` : ''
      const instTag = bar.is_inst_buy
        ? '<span class="ml-2 px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/40 text-[9px] font-bold">🟢 Inst Buy</span>'
        : bar.is_inst_sell
        ? '<span class="ml-2 px-1.5 py-0.2 rounded bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-500/40 text-[9px] font-bold">🔴 Inst Sell</span>'
        : ''

      ohlcTextRef.current.innerHTML = `
        <span class="text-muted">O</span> <span class="text-text font-semibold">${open.toFixed(2)}</span>
        <span class="text-muted ml-1.5">H</span> <span class="text-text font-semibold">${high.toFixed(2)}</span>
        <span class="text-muted ml-1.5">L</span> <span class="text-text font-semibold">${low.toFixed(2)}</span>
        <span class="text-muted ml-1.5">C</span> <span class="text-text font-semibold">${close.toFixed(2)}</span>
        <span class="${colorClass} font-semibold ml-1.5">${sign}${chg.toFixed(2)} (${sign}${chgPct.toFixed(2)}%)</span>
        <span class="text-muted ml-2">Vol</span> <span class="text-text font-semibold">${volStr}${rvolStr}</span>
        ${instTag}
      `
    } catch (e) {}
  }

  // 1. Fetch Candle & Indicator Data
  useEffect(() => {
    let unmounted = false
    setLoading(true)
    setError(null)

    const fetchCandles = async () => {
      try {
        let days = 250
        if (interval === '5m') days = 15
        else if (interval === '15m') days = 30
        else if (interval === '1h' || interval === '60m') days = 90
        else if (interval === 'day' || interval === '1D') days = 365
        else if (interval === 'week' || interval === '1W' || interval === '1wk') days = 1200
        else if (interval === 'month' || interval === '1M' || interval === '1mo') days = 3650

        const apiInterval = interval === '1D' ? 'day' : interval === '1W' ? 'week' : interval === '1M' ? 'month' : interval
        const res = await call('/skills/history', {
          symbol,
          exchange,
          interval: apiInterval,
          days,
        })
        const data = res?.data ?? res
        if (!unmounted) {
          if (data?.candles && Array.isArray(data.candles) && data.candles.length > 0) {
            setChartData(data)
            setError(null)
          } else {
            setError('No historical chart data available.')
          }
        }
      } catch (err) {
        if (!unmounted) setError(err.message || 'Failed to load chart')
      } finally {
        if (!unmounted) setLoading(false)
      }
    }

    fetchCandles()
    return () => {
      unmounted = true
    }
  }, [symbol, exchange, interval])

  // 2. Recalculate Order Block pixel zones when chart scrolls/scales
  const recalculateOBZones = useCallback(() => {
    if (!candleSeriesRef.current || !chartData?.order_blocks || !showIndicators.orderBlocks) {
      setObZones([])
      return
    }

    try {
      const zones = []
      const demandList = chartData.order_blocks.demand || []
      const supplyList = chartData.order_blocks.supply || []
      const tfShort = (interval === 'day' || interval === '1D') ? '1D' : interval.toUpperCase()

      for (const d of demandList.slice(-2)) {
        const yTop = candleSeriesRef.current.priceToCoordinate(d.top)
        const yBottom = candleSeriesRef.current.priceToCoordinate(d.bottom)
        const yOte = d.ote_price ? candleSeriesRef.current.priceToCoordinate(d.ote_price) : null
        if (yTop != null && yBottom != null) {
          const top = Math.min(yTop, yBottom)
          const h = Math.max(6, Math.abs(yBottom - yTop))
          const tf = d.tf || tfShort
          const confText = d.confluence_count > 1 ? ` (${d.confluence_count}x)` : ''
          zones.push({
            type: 'DEMAND',
            top,
            height: h,
            tag: `[${tf}] DEMAND${confText}`,
            priceSpan: `₹${d.bottom}-${d.top}`,
            otePrice: d.ote_price ?? d.midpoint,
            volumeRatio: d.volume_ratio,
            confluenceCount: d.confluence_count ?? 1,
            oteTop: yOte != null ? Math.max(0, yOte - top) : null,
          })
        }
      }

      for (const s of supplyList.slice(-2)) {
        const yTop = candleSeriesRef.current.priceToCoordinate(s.top)
        const yBottom = candleSeriesRef.current.priceToCoordinate(s.bottom)
        const yOte = s.ote_price ? candleSeriesRef.current.priceToCoordinate(s.ote_price) : null
        if (yTop != null && yBottom != null) {
          const top = Math.min(yTop, yBottom)
          const h = Math.max(6, Math.abs(yBottom - yTop))
          const tf = s.tf || tfShort
          const confText = s.confluence_count > 1 ? ` (${s.confluence_count}x)` : ''
          zones.push({
            type: 'SUPPLY',
            top,
            height: h,
            tag: `[${tf}] SUPPLY${confText}`,
            priceSpan: `₹${s.bottom}-${s.top}`,
            otePrice: s.ote_price ?? s.midpoint,
            volumeRatio: s.volume_ratio,
            confluenceCount: s.confluence_count ?? 1,
            oteTop: yOte != null ? Math.max(0, yOte - top) : null,
          })
        }
      }

      setObZones(zones)
    } catch (e) {}
  }, [chartData, interval, showIndicators.orderBlocks])

  // 3. Initialize Main Lightweight Chart instance
  const effectiveHeight = isModalView ? (typeof height === 'number' ? height : 640) : (typeof height === 'number' ? height : 440)
  const mainChartHeight = showIndicators.stochRSI ? Math.max(220, effectiveHeight - 125) : effectiveHeight

  // Reset / Recenter Chart View to default autoscale and timeline bounds
  const handleResetView = useCallback(() => {
    if (chartRef.current) {
      try {
        chartRef.current.timeScale().fitContent()
        if (candleSeriesRef.current) {
          candleSeriesRef.current.priceScale().applyOptions({
            autoScale: true,
          })
        }
        if (volumeSeriesRef.current) {
          volumeSeriesRef.current.priceScale().applyOptions({
            autoScale: true,
            scaleMargins: { top: 0.70, bottom: 0 },
          })
        }
      } catch (e) {}
    }
    if (stochChartRef.current) {
      try {
        stochChartRef.current.timeScale().fitContent()
      } catch (e) {}
    }
    setTimeout(() => {
      recalculateOBZones()
    }, 50)
  }, [recalculateOBZones])

  useEffect(() => {
    const container = chartContainerRef.current
    if (!container) return

    const isDark = getIsDark()

    const chart = createChart(container, {
      width: container.clientWidth || 500,
      height: mainChartHeight,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#94a3b8' : '#475569',
        fontSize: 11,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)' },
        horzLines: { color: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: isDark ? 'rgba(245, 158, 11, 0.35)' : 'rgba(217, 119, 6, 0.35)', width: 1, style: 2 },
        horzLine: { color: isDark ? 'rgba(245, 158, 11, 0.35)' : 'rgba(217, 119, 6, 0.35)', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
        scaleMargins: { top: 0.08, bottom: 0.18 },
      },
      timeScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
        timeVisible: interval !== 'day' && interval !== '1D',
        secondsVisible: false,
      },
    })

    chartRef.current = chart

    // Candlestick Series (Crisp, solid, high-priority rendering)
    const candleOpts = {
      upColor: isDark ? '#10b981' : '#059669',
      downColor: isDark ? '#f43f5e' : '#e11d48',
      borderUpColor: isDark ? '#10b981' : '#059669',
      borderDownColor: isDark ? '#f43f5e' : '#e11d48',
      wickUpColor: isDark ? '#10b981' : '#059669',
      wickDownColor: isDark ? '#f43f5e' : '#e11d48',
      priceScaleId: 'right',
    }
    const candleSeries = chart.addSeries
      ? chart.addSeries(CandlestickSeries, candleOpts)
      : chart.addCandlestickSeries(candleOpts)
    candleSeriesRef.current = candleSeries

    // Volume Series (Anchored to floor, translucent, non-intrusive)
    const volOpts = {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    }
    const volumeSeries = chart.addSeries
      ? chart.addSeries(HistogramSeries, volOpts)
      : chart.addHistogramSeries(volOpts)
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.70, bottom: 0 },
    })
    volumeSeriesRef.current = volumeSeries

    // Moving Averages Series (Aligned to right price scale, delicate stroke, no title boxes covering candles)
    const smaCommon = {
      lineWidth: 1.5,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceScaleId: 'right',
      title: '', // Prevents floating text box from obstructing candlesticks
    }

    const sma20 = chart.addSeries
      ? chart.addSeries(LineSeries, { ...smaCommon, color: 'rgba(245, 158, 11, 0.65)' })
      : chart.addLineSeries({ ...smaCommon, color: 'rgba(245, 158, 11, 0.65)' })
    sma20Ref.current = sma20

    const sma50 = chart.addSeries
      ? chart.addSeries(LineSeries, { ...smaCommon, color: 'rgba(59, 130, 246, 0.65)' })
      : chart.addLineSeries({ ...smaCommon, color: 'rgba(59, 130, 246, 0.65)' })
    sma50Ref.current = sma50

    const sma200 = chart.addSeries
      ? chart.addSeries(LineSeries, { ...smaCommon, color: 'rgba(168, 85, 247, 0.65)' })
      : chart.addLineSeries({ ...smaCommon, color: 'rgba(168, 85, 247, 0.65)' })
    sma200Ref.current = sma200

    // High performance Crosshair Listener
    chart.subscribeCrosshairMove((param) => {
      try {
        if (!param || !param.time || !param.seriesData) {
          if (lastCandleRef.current) {
            updateLegendDOM(lastCandleRef.current)
          }
          return
        }
        const candleBar = param.seriesData.get ? param.seriesData.get(candleSeriesRef.current) : null
        if (candleBar && candleBar.open != null) {
          updateLegendDOM(candleBar)
        } else if (lastCandleRef.current) {
          updateLegendDOM(lastCandleRef.current)
        }
      } catch (e) {}
    })

    // Listen to visible range changes to update shaded OB zones & sync Stoch RSI
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      recalculateOBZones()
      if (stochChartRef.current && range) {
        try {
          stochChartRef.current.timeScale().setVisibleLogicalRange(range)
        } catch (e) {}
      }
    })
    chart.timeScale().subscribeVisibleTimeRangeChange(() => {
      recalculateOBZones()
    })

    // Real-time synchronization when dragging right price scale, panning, or zooming
    let isDragging = false
    const handleMouseDown = () => {
      isDragging = true
    }
    const handleMouseMove = () => {
      if (isDragging) {
        requestAnimationFrame(recalculateOBZones)
      }
    }
    const handleMouseUp = () => {
      if (isDragging) {
        isDragging = false
        requestAnimationFrame(recalculateOBZones)
      }
    }
    const handleWheel = () => {
      requestAnimationFrame(recalculateOBZones)
    }

    container.addEventListener('mousedown', handleMouseDown)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    container.addEventListener('wheel', handleWheel, { passive: true })

    // Resize Observer: Strictly track container WIDTH only to eliminate vertical feedback loops
    const resizeObserver = new ResizeObserver((entries) => {
      if (!chartRef.current || entries.length === 0 || !entries[0].contentRect) return
      const { width } = entries[0].contentRect
      if (width > 0) {
        try {
          chartRef.current.applyOptions({ width })
          recalculateOBZones()
        } catch (e) {}
      }
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      container.removeEventListener('mousedown', handleMouseDown)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      container.removeEventListener('wheel', handleWheel)
      try {
        chart.remove()
      } catch (e) {}
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
      sma20Ref.current = null
      sma50Ref.current = null
      sma200Ref.current = null
      activePriceLinesRef.current = []
    }
  }, [mainChartHeight, recalculateOBZones])

  // Explicitly update chart height whenever mainChartHeight prop changes
  useEffect(() => {
    if (chartRef.current) {
      try {
        chartRef.current.applyOptions({ height: mainChartHeight })
        recalculateOBZones()
      } catch (e) {}
    }
  }, [mainChartHeight, recalculateOBZones])

  // 4. Initialize Stoch RSI Sub-Chart instance if toggled
  useEffect(() => {
    if (!showIndicators.stochRSI || !stochContainerRef.current) {
      if (stochChartRef.current) {
        try {
          stochChartRef.current.remove()
        } catch (e) {}
        stochChartRef.current = null
        stochKSeriesRef.current = null
        stochDSeriesRef.current = null
      }
      return
    }

    const container = stochContainerRef.current
    const isDark = getIsDark()

    const stochChart = createChart(container, {
      width: container.clientWidth || 500,
      height: 100,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#94a3b8' : '#64748b',
        fontSize: 10,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      },
      grid: {
        vertLines: { color: 'transparent' },
        horzLines: { color: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)' },
      },
      rightPriceScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
        timeVisible: interval !== 'day' && interval !== '1D',
        secondsVisible: false,
      },
    })

    stochChartRef.current = stochChart

    const kSeries = stochChart.addSeries
      ? stochChart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1.5, title: '', lastValueVisible: false })
      : stochChart.addLineSeries({ color: '#f59e0b', lineWidth: 1.5, title: '', lastValueVisible: false })
    stochKSeriesRef.current = kSeries

    const dSeries = stochChart.addSeries
      ? stochChart.addSeries(LineSeries, { color: '#06b6d4', lineWidth: 1.5, title: '', lastValueVisible: false })
      : stochChart.addLineSeries({ color: '#06b6d4', lineWidth: 1.5, title: '', lastValueVisible: false })
    stochDSeriesRef.current = dSeries

    // Add 80 & 20 Overbought/Oversold reference lines
    try {
      kSeries.createPriceLine({ price: 80, color: 'rgba(239, 68, 68, 0.4)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'OB 80' })
      kSeries.createPriceLine({ price: 20, color: 'rgba(34, 197, 94, 0.4)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'OS 20' })
    } catch (e) {}

    // Populate data if available
    if (chartData?.stoch_rsi) {
      if (chartData.stoch_rsi.k) kSeries.setData(sanitizeSeries(chartData.stoch_rsi.k))
      if (chartData.stoch_rsi.d) dSeries.setData(sanitizeSeries(chartData.stoch_rsi.d))
      stochChart.timeScale().fitContent()
    }

    const resizeObserver = new ResizeObserver((entries) => {
      if (!stochChartRef.current || entries.length === 0 || !entries[0].contentRect) return
      const { width } = entries[0].contentRect
      if (width > 0) {
        try {
          stochChartRef.current.applyOptions({ width })
        } catch (e) {}
      }
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      try {
        stochChart.remove()
      } catch (e) {}
      stochChartRef.current = null
      stochKSeriesRef.current = null
      stochDSeriesRef.current = null
    }
  }, [showIndicators.stochRSI, chartData, interval])

  // 5. Update Chart Series Data, Price Lines (POC / VAH / VAL), and Markers
  useEffect(() => {
    if (!chartRef.current || !chartData) return

    try {
      // Candlesticks
      if (candleSeriesRef.current && chartData.candles) {
        const cleanCandles = sanitizeSeries(chartData.candles)
        if (cleanCandles.length > 0) {
          lastCandleRef.current = cleanCandles[cleanCandles.length - 1]
          candleSeriesRef.current.setData(cleanCandles)
          updateLegendDOM(cleanCandles[cleanCandles.length - 1])

          // Combined Markers: Divergence Signals + Institutional Buy/Sell Highlights
          const candleMarkers = []

          // 1. Divergence Markers on price swings
          if (showIndicators.divergences && chartData.divergences && chartData.divergences.length > 0) {
            const candleTimes = new Set(
              cleanCandles.map((c) =>
                typeof c.time === 'object' ? `${c.time.year}-${c.time.month}-${c.time.day}` : String(c.time)
              )
            )

            for (const div of chartData.divergences) {
              const key = typeof div.time === 'object' ? `${div.time.year}-${div.time.month}-${div.time.day}` : String(div.time)
              if (candleTimes.has(key)) {
                candleMarkers.push({
                  time: div.time,
                  position: div.type === 'BULLISH_DIV' ? 'belowBar' : 'aboveBar',
                  color: div.color,
                  shape: div.type === 'BULLISH_DIV' ? 'arrowUp' : 'arrowDown',
                  text: div.label,
                  size: 1.4,
                })
              }
            }
          }

          // 2. Institutional Buy/Sell High Volume Spike Markers (RVOL >= 2.0x)
          if (showIndicators.volume && chartData.candles) {
            for (const c of cleanCandles) {
              if (c.rvol && c.rvol >= 2.0) {
                if (c.is_inst_buy) {
                  candleMarkers.push({
                    time: c.time,
                    position: 'belowBar',
                    color: '#00e676',
                    shape: 'arrowUp',
                    text: `Inst Buy ${c.rvol}x`,
                    size: 1.1,
                  })
                } else if (c.is_inst_sell) {
                  candleMarkers.push({
                    time: c.time,
                    position: 'aboveBar',
                    color: '#ff1744',
                    shape: 'arrowDown',
                    text: `Inst Sell ${c.rvol}x`,
                    size: 1.1,
                  })
                }
              }
            }
          }

          const sortedMarkers = sanitizeSeries(candleMarkers)
          if (candleSeriesRef.current && typeof candleSeriesRef.current.setMarkers === 'function') {
            candleSeriesRef.current.setMarkers(sortedMarkers)
          }

          // 3. Synchronize matching Divergence markers on the Stochastic RSI oscillator line
          if (stochKSeriesRef.current && typeof stochKSeriesRef.current.setMarkers === 'function') {
            if (showIndicators.divergences && chartData.divergences && chartData.divergences.length > 0) {
              const stochMarkers = chartData.divergences.map((div) => ({
                time: div.time,
                position: div.type === 'BULLISH_DIV' ? 'belowBar' : 'aboveBar',
                color: div.color,
                shape: div.type === 'BULLISH_DIV' ? 'arrowUp' : 'arrowDown',
                text: div.type === 'BULLISH_DIV' ? '▲ Bull Div' : '▼ Bear Div',
                size: 1.1,
              }))
              stochKSeriesRef.current.setMarkers(sanitizeSeries(stochMarkers))
            } else {
              stochKSeriesRef.current.setMarkers([])
            }
          }
        }
      }

      // Volume Series (Vivid Institutional Spikes + Translucent Normal Bars)
      if (volumeSeriesRef.current) {
        const cleanVolumes = showIndicators.volume && chartData.volumes ? sanitizeSeries(chartData.volumes) : []
        volumeSeriesRef.current.setData(cleanVolumes)
      }

      // SMAs
      if (sma20Ref.current) {
        const cleanSMA20 = showIndicators.sma20 && chartData.sma20 ? sanitizeSeries(chartData.sma20) : []
        sma20Ref.current.setData(cleanSMA20)
      }
      if (sma50Ref.current) {
        const cleanSMA50 = showIndicators.sma50 && chartData.sma50 ? sanitizeSeries(chartData.sma50) : []
        sma50Ref.current.setData(cleanSMA50)
      }
      if (sma200Ref.current) {
        const cleanSMA200 = showIndicators.sma200 && chartData.sma200 ? sanitizeSeries(chartData.sma200) : []
        sma200Ref.current.setData(cleanSMA200)
      }

      // Clear previous custom price lines
      if (candleSeriesRef.current) {
        for (const pl of activePriceLinesRef.current) {
          try {
            candleSeriesRef.current.removePriceLine(pl)
          } catch (e) {}
        }
        activePriceLinesRef.current = []

        const isDarkNow = getIsDark()

        // Volume Profile: POC, VAH, VAL (Delicate, non-intrusive dotted/dashed levels)
        if (showIndicators.volumeProfile && chartData.volume_profile) {
          const vp = chartData.volume_profile
          const tfShort = (interval === 'day' || interval === '1D') ? '1D' : interval.toUpperCase()
          const tf = vp.tf || tfShort
          if (vp.poc > 0) {
            const pocLine = candleSeriesRef.current.createPriceLine({
              price: vp.poc,
              color: isDarkNow ? 'rgba(245, 158, 11, 0.65)' : 'rgba(217, 119, 6, 0.7)',
              lineWidth: 1,
              lineStyle: 2, // Dashed
              axisLabelVisible: true,
              title: '', // Transparent across candles; labeled on price axis
            })
            activePriceLinesRef.current.push(pocLine)
          }
          if (vp.vah > 0) {
            const vahLine = candleSeriesRef.current.createPriceLine({
              price: vp.vah,
              color: isDarkNow ? 'rgba(56, 189, 248, 0.45)' : 'rgba(2, 132, 199, 0.55)',
              lineWidth: 1,
              lineStyle: 3, // Dotted
              axisLabelVisible: true,
              title: '', // Transparent across candles; labeled on price axis
            })
            activePriceLinesRef.current.push(vahLine)
          }
          if (vp.val > 0) {
            const valLine = candleSeriesRef.current.createPriceLine({
              price: vp.val,
              color: isDarkNow ? 'rgba(192, 132, 252, 0.45)' : 'rgba(126, 34, 206, 0.55)',
              lineWidth: 1,
              lineStyle: 3, // Dotted
              axisLabelVisible: true,
              title: '', // Transparent across candles; labeled on price axis
            })
            activePriceLinesRef.current.push(valLine)
          }
        }
      }

      chartRef.current.timeScale().fitContent()
      // Recalculate shaded OB ribbon positions
      setTimeout(recalculateOBZones, 100)
    } catch (chartErr) {
      console.error('Lightweight Chart series update error:', chartErr)
    }
  }, [chartData, showIndicators, recalculateOBZones, interval])

  // Active Key Level badges
  const vp = chartData?.volume_profile
  const demandOB = chartData?.order_blocks?.demand?.[0]
  const supplyOB = chartData?.order_blocks?.supply?.[0]
  const tfMap = {
    '5m': '5m',
    '15m': '15m',
    '1h': '1h',
    '60m': '1h',
    day: '1D',
    '1d': '1D',
    '1D': '1D',
    week: '1W',
    '1w': '1W',
    '1W': '1W',
    month: '1M',
    '1m': '1M',
    '1M': '1M',
  }
  const tfLabel = tfMap[String(interval).toLowerCase()] || String(interval).toUpperCase()

  const chartContent = (
    <div className="flex flex-col bg-panel border border-border/80 rounded-xl overflow-hidden shadow-sm transition-colors w-full h-full">
      {/* Chart Top Bar Controls */}
      <div className="flex flex-wrap items-center justify-between px-3.5 py-2 border-b border-border/60 bg-surface/50 text-xs font-mono gap-2">
        {/* Left: Symbol & Live OHLC stats container */}
        <div className="flex items-center gap-3 overflow-x-auto">
          <span className="text-amber font-bold tracking-wide text-sm">{symbol}</span>
          <div ref={ohlcTextRef} className="flex items-center gap-1.5 text-[11px]" />
        </div>

        {/* Right: Timeframe, Indicators, and Fullscreen Toggles */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Indicator Control Chips */}
          <div className="flex items-center gap-1 text-[10px] flex-wrap">
            {/* SMC Order Blocks */}
            <button
              onClick={() => setShowIndicators((s) => ({ ...s, orderBlocks: !s.orderBlocks }))}
              title="Smart Money Concepts: Unmitigated Demand & Supply Order Blocks"
              className={`px-2 py-0.5 rounded border transition-colors cursor-pointer flex items-center gap-1 ${
                showIndicators.orderBlocks
                  ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border-emerald-500/40 font-semibold shadow-xs'
                  : 'text-muted border-border/60 hover:text-text opacity-70'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              SMC OB
            </button>

            {/* Volume Profile (POC/VAH/VAL) */}
            <button
              onClick={() => setShowIndicators((s) => ({ ...s, volumeProfile: !s.volumeProfile }))}
              title="Volume Profile: Point of Control (POC), Value Area High (VAH), Value Area Low (VAL)"
              className={`px-2 py-0.5 rounded border transition-colors cursor-pointer flex items-center gap-1 ${
                showIndicators.volumeProfile
                  ? 'bg-amber/20 text-amber-600 dark:text-amber border-amber/40 font-semibold shadow-xs'
                  : 'text-muted border-border/60 hover:text-text opacity-70'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber" />
              POC / VAH
            </button>

            {/* Stochastic RSI */}
            <button
              onClick={() => setShowIndicators((s) => ({ ...s, stochRSI: !s.stochRSI }))}
              title="Stochastic RSI Indicator (%K & %D with 80/20 Overbought/Oversold)"
              className={`px-2 py-0.5 rounded border transition-colors cursor-pointer flex items-center gap-1 ${
                showIndicators.stochRSI
                  ? 'bg-cyan-500/20 text-cyan-600 dark:text-cyan-400 border-cyan-500/40 font-semibold shadow-xs'
                  : 'text-muted border-border/60 hover:text-text opacity-70'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
              Stoch RSI
            </button>

            {/* RSI Divergence */}
            <button
              onClick={() => setShowIndicators((s) => ({ ...s, divergences: !s.divergences }))}
              title="RSI Bullish & Bearish Divergence Signals"
              className={`px-2 py-0.5 rounded border transition-colors cursor-pointer flex items-center gap-1 ${
                showIndicators.divergences
                  ? 'bg-purple-500/20 text-purple-600 dark:text-purple-400 border-purple-500/40 font-semibold shadow-xs'
                  : 'text-muted border-border/60 hover:text-text opacity-70'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
              Divergence
            </button>

            {/* Volume */}
            <button
              onClick={() => setShowIndicators((s) => ({ ...s, volume: !s.volume }))}
              title="Volume Histogram & Institutional Volume Spikes"
              className={`px-1.5 py-0.5 rounded border transition-colors cursor-pointer flex items-center gap-1 ${
                showIndicators.volume
                  ? 'bg-blue-500/20 text-blue-600 dark:text-blue-400 border-blue-500/40 font-semibold shadow-xs'
                  : 'text-muted border-border/60 hover:text-text opacity-70'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              VOL
            </button>

            {/* SMA 20/50 */}
            <button
              onClick={() => setShowIndicators((s) => ({ ...s, sma20: !s.sma20, sma50: !s.sma50 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors cursor-pointer ${
                showIndicators.sma20 ? 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA
            </button>
          </div>

          {/* Multi-Timeframe Institutional Selector */}
          <div className="flex items-center bg-elevated rounded-lg border border-border/70 p-0.5 text-[11px]">
            {[
              { label: '5m', val: '5m', desc: '5-Minute Scalp & Order Block Re-tests' },
              { label: '15m', val: '15m', desc: '15-Minute Intraday Structure & Swings' },
              { label: '1h', val: '1h', desc: '1-Hour Multi-Session Swing & Key Levels' },
              { label: '1D', val: 'day', desc: 'Daily Institutional Trend (Minervini Stage 2)' },
              { label: '1W', val: 'week', desc: 'Weekly Positional Trend & Stage Analysis' },
              { label: '1M', val: 'month', desc: 'Monthly Secular Macro Trend' },
            ].map((tf) => {
              const isActive =
                interval === tf.val ||
                (tf.val === 'day' && (interval === '1D' || interval === '1d')) ||
                (tf.val === 'week' && (interval === '1W' || interval === '1w')) ||
                (tf.val === 'month' && (interval === '1M' || interval === '1m'))
              return (
                <button
                  key={tf.val}
                  onClick={() => setIntervalVal(tf.val)}
                  title={tf.desc}
                  className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                    isActive ? 'bg-amber text-black font-semibold shadow-xs' : 'text-muted hover:text-text'
                  }`}
                >
                  {tf.label}
                </button>
              )
            })}
          </div>

          {/* Reset / Recenter Button */}
          <button
            onClick={handleResetView}
            title="Reset Chart View (Autoscale & Fit Content)"
            className="px-2 py-0.5 rounded-lg border border-border/70 bg-elevated hover:bg-elevated/80 text-muted hover:text-text text-[11px] font-mono transition-all cursor-pointer flex items-center gap-1 shadow-2xs"
          >
            <span>⟲</span> Reset
          </button>

          {/* Fullscreen Expansion Button */}
          {!isModalView && (
            <button
              onClick={() => setIsFullscreen(true)}
              title="Open Chart in Bigger Fullscreen Screen"
              className="p-1 px-1.5 rounded-lg border border-border/70 bg-elevated text-muted hover:text-amber hover:border-amber/50 transition-all cursor-pointer text-xs font-mono"
            >
              ⛶ Fullscreen
            </button>
          )}
          {isModalView && onCloseFullscreen && (
            <button
              onClick={onCloseFullscreen}
              className="p-1 px-2 rounded-lg border border-border/70 bg-rose-500/20 text-rose-500 dark:text-rose-400 hover:bg-rose-500/30 transition-all cursor-pointer text-xs font-bold"
            >
              ✕ Close
            </button>
          )}
        </div>
      </div>

      {/* Institutional Key Level Highlights Bar */}
      <div className="flex items-center gap-2 px-3.5 py-1.5 bg-surface/70 dark:bg-surface/40 backdrop-blur-xs border-b border-border/40 text-[10px] font-mono text-muted overflow-x-auto">
        {vp?.poc > 0 && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber/15 border border-amber/30 text-amber-800 dark:text-amber-300 font-bold whitespace-nowrap">
            <span>🎯 {vp.tf || tfLabel}-POC:</span> ₹{vp.poc.toFixed(2)}
          </span>
        )}
        {vp?.vah > 0 && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-800 dark:text-sky-300 font-bold whitespace-nowrap">
            <span>🔷 {vp.tf || tfLabel}-VAH:</span> ₹{vp.vah.toFixed(2)}
          </span>
        )}
        {vp?.val > 0 && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-800 dark:text-purple-300 font-bold whitespace-nowrap">
            <span>🟣 {vp.tf || tfLabel}-VAL:</span> ₹{vp.val.toFixed(2)}
          </span>
        )}
        {demandOB && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-800 dark:text-emerald-300 font-bold whitespace-nowrap">
            <span>🟢 [{demandOB.tf || tfLabel}] Demand{demandOB.confluence_count > 1 ? ` (${demandOB.confluence_count}x)` : ''}:</span> ₹{demandOB.bottom}-{demandOB.top}
            <span className="text-emerald-700 dark:text-emerald-300/90 text-[10px] font-semibold">| OTE: ₹{demandOB.ote_price ?? demandOB.midpoint}</span>
          </span>
        )}
        {supplyOB && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/15 border border-rose-500/30 text-rose-800 dark:text-rose-300 font-bold whitespace-nowrap">
            <span>🔴 [{supplyOB.tf || tfLabel}] Supply{supplyOB.confluence_count > 1 ? ` (${supplyOB.confluence_count}x)` : ''}:</span> ₹{supplyOB.bottom}-{supplyOB.top}
            <span className="text-rose-700 dark:text-rose-300/90 text-[10px] font-semibold">| OTE: ₹{supplyOB.ote_price ?? supplyOB.midpoint}</span>
          </span>
        )}
      </div>

      {/* Main Chart Canvas Area with Background Shaded Order Block Ribbons */}
      <div className="relative w-full overflow-hidden" style={{ height: `${mainChartHeight}px`, minHeight: `${mainChartHeight}px`, maxHeight: `${mainChartHeight}px` }}>
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface/60 backdrop-blur-xs text-muted text-xs font-mono">
            <span className="text-amber animate-spin mr-2">◆</span> Loading institutional market data…
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center text-red text-xs font-ui p-4 text-center">
            {error}
          </div>
        )}

        {/* Translucent Shaded Order Block Ribbons (Aligned to price coordinates with ultra-sheer veil) */}
        {showIndicators.orderBlocks && obZones.map((z, idx) => (
          <div
            key={idx}
            className={`absolute left-0 right-14 pointer-events-none rounded-xs flex items-center px-2 select-none ${
              z.type === 'DEMAND'
                ? 'bg-emerald-500/[0.025] dark:bg-emerald-500/[0.015] border-y border-dashed border-emerald-500/20'
                : 'bg-rose-500/[0.025] dark:bg-rose-500/[0.015] border-y border-dashed border-rose-500/20'
            }`}
            style={{
              top: `${z.top}px`,
              height: `${z.height}px`,
              zIndex: 5,
            }}
          >
            {/* Crisp High-Contrast Floating Chip Tag */}
            <div className="flex items-center gap-1.5 overflow-hidden ml-1">
              <span
                className={`px-1.5 py-0.2 rounded text-[9px] font-mono font-bold tracking-wider shadow-2xs border ${
                  z.type === 'DEMAND'
                    ? 'bg-emerald-950/85 text-emerald-300 border-emerald-500/40 backdrop-blur-xs'
                    : 'bg-rose-950/85 text-rose-300 border-rose-500/40 backdrop-blur-xs'
                }`}
              >
                {z.tag}
              </span>
              <span
                className={`px-1.5 py-0.2 rounded text-[9px] font-mono font-semibold shadow-2xs border backdrop-blur-xs ${
                  z.type === 'DEMAND'
                    ? 'bg-surface/85 text-text border-emerald-500/30'
                    : 'bg-surface/85 text-text border-rose-500/30'
                }`}
              >
                {z.priceSpan} <span className="text-amber font-bold ml-1">OTE: ₹{z.otePrice}</span>
              </span>
            </div>

            {z.oteTop != null && (
              <div
                className="absolute left-0 right-0 border-t border-dashed border-amber/40 pointer-events-none"
                style={{ top: `${z.oteTop}px` }}
              />
            )}
          </div>
        ))}

        <div ref={chartContainerRef} className="w-full h-full" />
      </div>

      {/* Stochastic RSI Lower Sub-Pane (Seamless, zero-gap dock) */}
      {showIndicators.stochRSI && (
        <div className="border-t border-border/60 bg-surface/40 px-3 py-1.5 flex flex-col flex-shrink-0">
          <div className="flex items-center justify-between text-[10px] font-mono text-muted mb-0.5">
            <div className="flex items-center gap-2">
              <span className="text-cyan-500 dark:text-cyan-400 font-bold">Stochastic RSI (14, 3, 3)</span>
              <span className="text-amber">● %K</span>
              <span className="text-cyan-500 dark:text-cyan-400">● %D</span>
            </div>
            <span className="text-muted text-[9px]">Overbought: 80 | Oversold: 20</span>
          </div>
          <div ref={stochContainerRef} className="w-full h-[100px]" />
        </div>
      )}
    </div>
  )

  // Fullscreen Modal View
  if (isFullscreen) {
    const modalHeight = typeof window !== 'undefined' && window.innerHeight
      ? Math.max(520, Math.round(window.innerHeight * 0.92) - 95)
      : 660

    return (
      <>
        {chartContent}
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md p-2 sm:p-4 animate-in fade-in duration-200"
          onClick={() => setIsFullscreen(false)}
        >
          <div
            className="w-full max-w-7xl h-[92vh] max-h-[94vh] bg-surface border border-border/80 rounded-2xl overflow-hidden shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <CandlestickChartComponent
              symbol={symbol}
              exchange={exchange}
              timeframe={interval}
              isModalView={true}
              height={modalHeight}
              onCloseFullscreen={() => setIsFullscreen(false)}
            />
          </div>
        </div>
      </>
    )
  }

  return chartContent
}

export default memo(CandlestickChartComponent)
