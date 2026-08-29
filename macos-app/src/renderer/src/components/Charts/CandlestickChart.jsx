import { useEffect, useRef, useState, memo } from 'react'
import { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts'
import { useAPI } from '../../hooks/useAPI'

function CandlestickChartComponent({ symbol = 'NIFTY', exchange = 'NSE', height = 280, timeframe = '15m' }) {
  const chartContainerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)
  const sma20Ref = useRef(null)
  const sma50Ref = useRef(null)
  const sma200Ref = useRef(null)

  // Direct DOM refs for high-performance legend updates without React re-renders
  const ohlcTextRef = useRef(null)

  const { call } = useAPI()
  const [interval, setIntervalVal] = useState(timeframe || '15m')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chartData, setChartData] = useState(null)
  const [showSMA, setShowSMA] = useState({ sma20: true, sma50: true, sma200: false })

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
      const chg = close - open
      const chgPct = open !== 0 ? (chg / open) * 100 : 0
      const isPos = chg >= 0
      const colorClass = isPos ? 'text-emerald-400' : 'text-rose-400'
      const sign = isPos ? '+' : ''

      ohlcTextRef.current.innerHTML = `
        <span class="text-muted">O</span> <span class="text-text font-semibold">${open.toFixed(2)}</span>
        <span class="text-muted ml-2">H</span> <span class="text-text font-semibold">${high.toFixed(2)}</span>
        <span class="text-muted ml-2">L</span> <span class="text-text font-semibold">${low.toFixed(2)}</span>
        <span class="text-muted ml-2">C</span> <span class="text-text font-semibold">${close.toFixed(2)}</span>
        <span class="${colorClass} font-semibold ml-2">${sign}${chg.toFixed(2)} (${sign}${chgPct.toFixed(2)}%)</span>
      `
    } catch (e) {}
  }

  // 1. Fetch Candle Data on symbol, exchange, or interval change
  useEffect(() => {
    let unmounted = false
    setLoading(true)
    setError(null)

    const fetchCandles = async () => {
      try {
        const days = interval === '5m' || interval === '15m' || interval === '1h' ? 30 : 250
        const apiInterval = interval === '1D' ? 'day' : interval
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

  // 2. Initialize Lightweight Chart instance (Mount ONCE per container)
  useEffect(() => {
    const container = chartContainerRef.current
    if (!container) return

    const isDark = getIsDark()

    const chart = createChart(container, {
      width: container.clientWidth || 500,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#94a3b8' : '#64748b',
        fontSize: 11,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)' },
        horzLines: { color: isDark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: isDark ? 'rgba(245, 158, 11, 0.4)' : 'rgba(217, 119, 6, 0.4)', width: 1, style: 2 },
        horzLine: { color: isDark ? 'rgba(245, 158, 11, 0.4)' : 'rgba(217, 119, 6, 0.4)', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
        timeVisible: interval !== 'day' && interval !== '1D',
        secondsVisible: false,
      },
    })

    chartRef.current = chart

    // Add Candlestick Series
    const candleOpts = {
      upColor: isDark ? '#10b981' : '#059669',
      downColor: isDark ? '#f43f5e' : '#e11d48',
      borderUpColor: isDark ? '#10b981' : '#059669',
      borderDownColor: isDark ? '#f43f5e' : '#e11d48',
      wickUpColor: isDark ? '#10b981' : '#059669',
      wickDownColor: isDark ? '#f43f5e' : '#e11d48',
    }
    const candleSeries = chart.addSeries
      ? chart.addSeries(CandlestickSeries, candleOpts)
      : chart.addCandlestickSeries(candleOpts)
    candleSeriesRef.current = candleSeries

    // Add Volume Series
    const volOpts = {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    }
    const volumeSeries = chart.addSeries
      ? chart.addSeries(HistogramSeries, volOpts)
      : chart.addHistogramSeries(volOpts)
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })
    volumeSeriesRef.current = volumeSeries

    // Add SMA Series
    const sma20 = chart.addSeries
      ? chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1.5, priceLineVisible: false, title: 'SMA 20' })
      : chart.addLineSeries({ color: '#f59e0b', lineWidth: 1.5, priceLineVisible: false, title: 'SMA 20' })
    sma20Ref.current = sma20

    const sma50 = chart.addSeries
      ? chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1.5, priceLineVisible: false, title: 'SMA 50' })
      : chart.addLineSeries({ color: '#3b82f6', lineWidth: 1.5, priceLineVisible: false, title: 'SMA 50' })
    sma50Ref.current = sma50

    const sma200 = chart.addSeries
      ? chart.addSeries(LineSeries, { color: '#a855f7', lineWidth: 1.5, priceLineVisible: false, title: 'SMA 200' })
      : chart.addLineSeries({ color: '#a855f7', lineWidth: 1.5, priceLineVisible: false, title: 'SMA 200' })
    sma200Ref.current = sma200

    // High performance Crosshair Listener (Updates DOM directly, ZERO React re-renders)
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

    // Resize Observer
    const resizeObserver = new ResizeObserver((entries) => {
      if (!chartRef.current || entries.length === 0 || !entries[0].contentRect) return
      const { width } = entries[0].contentRect
      if (width > 0) {
        try {
          chartRef.current.applyOptions({ width })
        } catch (e) {}
      }
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      try {
        chart.remove()
      } catch (e) {}
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
      sma20Ref.current = null
      sma50Ref.current = null
      sma200Ref.current = null
    }
  }, [height])

  // 3. Update Chart Series data when chartData or SMA toggles change
  useEffect(() => {
    if (!chartRef.current || !chartData) return

    try {
      if (candleSeriesRef.current && chartData.candles) {
        const cleanCandles = sanitizeSeries(chartData.candles)
        if (cleanCandles.length > 0) {
          lastCandleRef.current = cleanCandles[cleanCandles.length - 1]
          candleSeriesRef.current.setData(cleanCandles)
          updateLegendDOM(cleanCandles[cleanCandles.length - 1])
        }
      }

      if (volumeSeriesRef.current && chartData.volumes) {
        const cleanVolumes = sanitizeSeries(chartData.volumes)
        if (cleanVolumes.length > 0) {
          volumeSeriesRef.current.setData(cleanVolumes)
        }
      }

      if (sma20Ref.current) {
        const cleanSMA20 = showSMA.sma20 && chartData.sma20 ? sanitizeSeries(chartData.sma20) : []
        sma20Ref.current.setData(cleanSMA20)
      }

      if (sma50Ref.current) {
        const cleanSMA50 = showSMA.sma50 && chartData.sma50 ? sanitizeSeries(chartData.sma50) : []
        sma50Ref.current.setData(cleanSMA50)
      }

      if (sma200Ref.current) {
        const cleanSMA200 = showSMA.sma200 && chartData.sma200 ? sanitizeSeries(chartData.sma200) : []
        sma200Ref.current.setData(cleanSMA200)
      }

      chartRef.current.timeScale().fitContent()
    } catch (chartErr) {
      console.error('Lightweight Chart series update error:', chartErr)
    }
  }, [chartData, showSMA])

  return (
    <div className="flex flex-col bg-panel border border-border/80 rounded-xl overflow-hidden shadow-sm transition-colors w-full h-full">
      {/* Chart Top Bar Controls */}
      <div className="flex flex-wrap items-center justify-between px-3.5 py-2 border-b border-border/60 bg-surface/50 text-xs font-mono gap-2">
        {/* Left: Symbol & Live OHLC stats container */}
        <div className="flex items-center gap-3 overflow-x-auto">
          <span className="text-amber font-bold tracking-wide">{symbol}</span>
          <div ref={ohlcTextRef} className="flex items-center gap-1.5 text-[11px]" />
        </div>

        {/* Right: Timeframe + SMA Toggles */}
        <div className="flex items-center gap-2">
          {/* SMA toggles */}
          <div className="hidden sm:flex items-center gap-1 text-[10px]">
            <button
              onClick={() => setShowSMA((s) => ({ ...s, sma20: !s.sma20 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors cursor-pointer ${
                showSMA.sma20 ? 'bg-amber/15 text-amber border-amber/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA20
            </button>
            <button
              onClick={() => setShowSMA((s) => ({ ...s, sma50: !s.sma50 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors cursor-pointer ${
                showSMA.sma50 ? 'bg-blue-500/15 text-blue-400 border-blue-500/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA50
            </button>
            <button
              onClick={() => setShowSMA((s) => ({ ...s, sma200: !s.sma200 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors cursor-pointer ${
                showSMA.sma200 ? 'bg-purple-500/15 text-purple-400 border-purple-500/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA200
            </button>
          </div>

          {/* Timeframe selector */}
          <div className="flex items-center bg-elevated rounded-lg border border-border/70 p-0.5 text-[11px]">
            {[
              { label: '5m', val: '5m' },
              { label: '15m', val: '15m' },
              { label: '1D', val: 'day' },
            ].map((tf) => (
              <button
                key={tf.val}
                onClick={() => setIntervalVal(tf.val)}
                className={`px-2 py-0.5 rounded transition-all cursor-pointer ${
                  interval === tf.val ? 'bg-amber text-black font-semibold shadow-xs' : 'text-muted hover:text-text'
                }`}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart Canvas Area */}
      <div className="relative w-full flex-1 min-h-[260px]" style={{ minHeight: `${height}px` }}>
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-surface/60 backdrop-blur-xs text-muted text-xs font-mono">
            <span className="text-amber animate-spin mr-2">◆</span> Loading market candles…
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center text-red text-xs font-ui p-4 text-center">
            {error}
          </div>
        )}
        <div ref={chartContainerRef} className="w-full h-full min-h-[260px]" />
      </div>
    </div>
  )
}

export default memo(CandlestickChartComponent)
