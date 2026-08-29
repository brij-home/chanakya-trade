import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType } from 'lightweight-charts'
import { useAPI } from '../../hooks/useAPI'

export default function CandlestickChart({ symbol = 'NIFTY', exchange = 'NSE', height = 320 }) {
  const chartContainerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)
  const sma20Ref = useRef(null)
  const sma50Ref = useRef(null)
  const sma200Ref = useRef(null)

  const { call } = useAPI()
  const [interval, setIntervalVal] = useState('day')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chartData, setChartData] = useState(null)
  const [legend, setLegend] = useState(null)
  const [showSMA, setShowSMA] = useState({ sma20: true, sma50: true, sma200: false })

  const getIsDark = () =>
    document.documentElement.classList.contains('dark') ||
    !document.documentElement.classList.contains('light')

  // Fetch candle data on symbol or interval change
  useEffect(() => {
    let unmounted = false
    setLoading(true)
    setError(null)

    const fetchCandles = async () => {
      try {
        const days = interval === '5m' || interval === '15m' ? 30 : 250
        const res = await call('/skills/history', {
          symbol,
          exchange,
          interval,
          days,
        })
        const data = res?.data ?? res
        if (!unmounted) {
          if (data?.candles && data.candles.length > 0) {
            setChartData(data)
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

  // Initialize Lightweight Chart with full Theme awareness
  useEffect(() => {
    if (!chartContainerRef.current || !chartData || chartData.candles.length === 0) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const isDark = getIsDark()
    const container = chartContainerRef.current

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
        vertLines: { color: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)' },
        horzLines: { color: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: isDark ? 'rgba(245, 158, 11, 0.5)' : 'rgba(217, 119, 6, 0.5)', width: 1, style: 2 },
        horzLine: { color: isDark ? 'rgba(245, 158, 11, 0.5)' : 'rgba(217, 119, 6, 0.5)', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)',
        timeVisible: interval !== 'day',
        secondsVisible: false,
      },
    })

    chartRef.current = chart

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
      return Array.from(seen.values()).sort((a, b) => {
        const tA = typeof a.time === 'number' ? a.time : String(a.time)
        const tB = typeof b.time === 'number' ? b.time : String(b.time)
        return tA > tB ? 1 : tA < tB ? -1 : 0
      })
    }

    // 1. Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
      upColor: isDark ? '#10b981' : '#059669',
      downColor: isDark ? '#f43f5e' : '#e11d48',
      borderUpColor: isDark ? '#10b981' : '#059669',
      borderDownColor: isDark ? '#f43f5e' : '#e11d48',
      wickUpColor: isDark ? '#10b981' : '#059669',
      wickDownColor: isDark ? '#f43f5e' : '#e11d48',
    })
    const cleanCandles = sanitizeSeries(chartData.candles)
    if (cleanCandles.length > 0) {
      candleSeries.setData(cleanCandles)
    }
    candleSeriesRef.current = candleSeries

    // 2. Volume Series
    if (chartData.volumes && chartData.volumes.length > 0) {
      const cleanVolumes = sanitizeSeries(chartData.volumes)
      if (cleanVolumes.length > 0) {
        const volumeSeries = chart.addHistogramSeries({
          priceFormat: { type: 'volume' },
          priceScaleId: '',
        })
        volumeSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        })
        volumeSeries.setData(cleanVolumes)
        volumeSeriesRef.current = volumeSeries
      }
    }

    // 3. SMAs
    if (chartData.sma20 && chartData.sma20.length > 0) {
      const cleanSMA20 = sanitizeSeries(chartData.sma20)
      if (cleanSMA20.length > 0) {
        const sma20 = chart.addLineSeries({
          color: '#f59e0b',
          lineWidth: 1.5,
          priceLineVisible: false,
          title: 'SMA 20',
        })
        if (showSMA.sma20) sma20.setData(cleanSMA20)
        sma20Ref.current = sma20
      }
    }

    if (chartData.sma50 && chartData.sma50.length > 0) {
      const cleanSMA50 = sanitizeSeries(chartData.sma50)
      if (cleanSMA50.length > 0) {
        const sma50 = chart.addLineSeries({
          color: '#3b82f6',
          lineWidth: 1.5,
          priceLineVisible: false,
          title: 'SMA 50',
        })
        if (showSMA.sma50) sma50.setData(cleanSMA50)
        sma50Ref.current = sma50
      }
    }

    if (chartData.sma200 && chartData.sma200.length > 0) {
      const cleanSMA200 = sanitizeSeries(chartData.sma200)
      if (cleanSMA200.length > 0) {
        const sma200 = chart.addLineSeries({
          color: '#a855f7',
          lineWidth: 1.5,
          priceLineVisible: false,
          title: 'SMA 200',
        })
        if (showSMA.sma200) sma200.setData(cleanSMA200)
        sma200Ref.current = sma200
      }
    }

    // Crosshair legend handler
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesData) {
        const last = chartData.candles[chartData.candles.length - 1]
        if (last) {
          setLegend({
            open: last.open,
            high: last.high,
            low: last.low,
            close: last.close,
            change: last.close - last.open,
            changePct: ((last.close - last.open) / last.open) * 100,
          })
        }
        return
      }

      const data = param.seriesData.get(candleSeries)
      if (data) {
        setLegend({
          open: data.open,
          high: data.high,
          low: data.low,
          close: data.close,
          change: data.close - data.open,
          changePct: ((data.close - data.open) / data.open) * 100,
        })
      }
    })

    const last = chartData.candles[chartData.candles.length - 1]
    if (last) {
      setLegend({
        open: last.open,
        high: last.high,
        low: last.low,
        close: last.close,
        change: last.close - last.open,
        changePct: ((last.close - last.open) / last.open) * 100,
      })
    }

    chart.timeScale().fitContent()

    // Mutation observer for dark/light theme toggle
    const observer = new MutationObserver(() => {
      if (!chartRef.current) return
      const dark = getIsDark()
      chartRef.current.applyOptions({
        layout: { textColor: dark ? '#94a3b8' : '#64748b' },
        grid: {
          vertLines: { color: dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)' },
          horzLines: { color: dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)' },
        },
        rightPriceScale: { borderColor: dark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)' },
        timeScale: { borderColor: dark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)' },
      })
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })

    // Resize observer
    const resizeObserver = new ResizeObserver((entries) => {
      if (entries.length === 0 || !entries[0].contentRect) return
      const { width } = entries[0].contentRect
      chart.applyOptions({ width })
    })
    resizeObserver.observe(container)

    return () => {
      observer.disconnect()
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [chartData, height, showSMA])

  return (
    <div className="flex flex-col bg-panel border border-border rounded-xl overflow-hidden shadow-sm transition-colors">
      {/* Chart Top Bar Controls */}
      <div className="flex flex-wrap items-center justify-between px-3.5 py-2 border-b border-border bg-surface/50 text-xs font-mono gap-2">
        {/* Left: Symbol & Live OHLC stats */}
        <div className="flex items-center gap-3 overflow-x-auto">
          <span className="text-amber font-bold tracking-wide">{symbol}</span>
          {legend && (
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-muted">O <span className="text-text font-semibold">{legend.open?.toFixed(2)}</span></span>
              <span className="text-muted">H <span className="text-text font-semibold">{legend.high?.toFixed(2)}</span></span>
              <span className="text-muted">L <span className="text-text font-semibold">{legend.low?.toFixed(2)}</span></span>
              <span className="text-muted">C <span className="text-text font-semibold">{legend.close?.toFixed(2)}</span></span>
              <span className={`font-semibold ${legend.change >= 0 ? 'text-green' : 'text-red'}`}>
                {legend.change >= 0 ? '+' : ''}{legend.change?.toFixed(2)} ({legend.changePct?.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>

        {/* Right: Timeframe + SMA Toggles */}
        <div className="flex items-center gap-2">
          {/* SMA toggles */}
          <div className="hidden sm:flex items-center gap-1 text-[10px]">
            <button
              onClick={() => setShowSMA((s) => ({ ...s, sma20: !s.sma20 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors ${
                showSMA.sma20 ? 'bg-amber/15 text-amber border-amber/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA20
            </button>
            <button
              onClick={() => setShowSMA((s) => ({ ...s, sma50: !s.sma50 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors ${
                showSMA.sma50 ? 'bg-blue/15 text-blue border-blue/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA50
            </button>
            <button
              onClick={() => setShowSMA((s) => ({ ...s, sma200: !s.sma200 }))}
              className={`px-1.5 py-0.5 rounded border transition-colors ${
                showSMA.sma200 ? 'bg-purple/15 text-purple border-purple/40 font-semibold' : 'text-muted border-transparent opacity-60'
              }`}
            >
              SMA200
            </button>
          </div>

          {/* Timeframe selector */}
          <div className="flex items-center bg-elevated rounded-lg border border-border p-0.5 text-[11px]">
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
      <div className="relative w-full" style={{ height: `${height}px` }}>
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
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>
    </div>
  )
}
