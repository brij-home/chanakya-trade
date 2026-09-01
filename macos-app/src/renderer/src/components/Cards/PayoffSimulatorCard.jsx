import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'
import { formatINR, formatINRFull } from '../../utils/formatINR'

const PRESETS = {
  'Bull Call Spread': (spot) => {
    const s = Math.round(spot / 50) * 50
    return [
      { action: 'BUY', option_type: 'CE', strike: s, premium: 140, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'CE', strike: s + 200, premium: 50, lots: 1, lot_size: 25 },
    ]
  },
  'Bear Put Spread': (spot) => {
    const s = Math.round(spot / 50) * 50
    return [
      { action: 'BUY', option_type: 'PE', strike: s, premium: 130, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'PE', strike: s - 200, premium: 45, lots: 1, lot_size: 25 },
    ]
  },
  'Long Straddle': (spot) => {
    const s = Math.round(spot / 50) * 50
    return [
      { action: 'BUY', option_type: 'CE', strike: s, premium: 140, lots: 1, lot_size: 25 },
      { action: 'BUY', option_type: 'PE', strike: s, premium: 130, lots: 1, lot_size: 25 },
    ]
  },
  'Short Straddle': (spot) => {
    const s = Math.round(spot / 50) * 50
    return [
      { action: 'SELL', option_type: 'CE', strike: s, premium: 140, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'PE', strike: s, premium: 130, lots: 1, lot_size: 25 },
    ]
  },
  'Iron Condor': (spot) => {
    const s = Math.round(spot / 50) * 50
    return [
      { action: 'BUY', option_type: 'PE', strike: s - 400, premium: 20, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'PE', strike: s - 200, premium: 55, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'CE', strike: s + 200, premium: 60, lots: 1, lot_size: 25 },
      { action: 'BUY', option_type: 'CE', strike: s + 400, premium: 22, lots: 1, lot_size: 25 },
    ]
  },
  'Iron Butterfly': (spot) => {
    const s = Math.round(spot / 50) * 50
    return [
      { action: 'BUY', option_type: 'PE', strike: s - 300, premium: 35, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'PE', strike: s, premium: 130, lots: 1, lot_size: 25 },
      { action: 'SELL', option_type: 'CE', strike: s, premium: 140, lots: 1, lot_size: 25 },
      { action: 'BUY', option_type: 'CE', strike: s + 300, premium: 40, lots: 1, lot_size: 25 },
    ]
  },
}

export default function PayoffSimulatorCard({ initialSymbol = 'NIFTY', initialSpot = 24000 }) {
  const { call } = useAPI()
  const [symbol, setSymbol] = useState(initialSymbol)
  const [spotPrice, setSpotPrice] = useState(initialSpot)
  const [sliderSpot, setSliderSpot] = useState(initialSpot)
  const [dte, setDte] = useState(7)
  const [targetDte, setTargetDte] = useState(4)
  const [iv, setIv] = useState(14)
  const [ivShock, setIvShock] = useState(0)
  const [selectedPreset, setSelectedPreset] = useState('Bull Call Spread')
  const [legs, setLegs] = useState(PRESETS['Bull Call Spread'](initialSpot))
  const [simData, setSimData] = useState(null)
  const [loading, setLoading] = useState(false)

  // Sync with incoming props when underlying or spot price changes
  useEffect(() => {
    if (initialSymbol) setSymbol(initialSymbol)
    if (initialSpot && initialSpot > 0) {
      setSpotPrice(initialSpot)
      setSliderSpot(initialSpot)
      if (PRESETS[selectedPreset]) {
        setLegs(PRESETS[selectedPreset](initialSpot))
      }
    }
  }, [initialSymbol, initialSpot])

  // Apply preset
  const handlePresetSelect = (presetName) => {
    setSelectedPreset(presetName)
    if (PRESETS[presetName]) {
      setLegs(PRESETS[presetName](spotPrice))
    }
  }

  // Fetch payoff simulation on parameters change
  useEffect(() => {
    let unmounted = false
    const calculate = async () => {
      if (legs.length === 0) return
      setLoading(true)
      try {
        const res = await call('/skills/payoff', {
          symbol,
          spot_price: spotPrice,
          dte,
          iv,
          iv_shock: ivShock,
          target_dte: targetDte,
          legs,
        })
        const data = res?.data ?? res
        if (!unmounted) setSimData(data)
      } catch (e) {
        console.error('Payoff simulation error', e)
      } finally {
        if (!unmounted) setLoading(false)
      }
    }

    const timer = setTimeout(calculate, 150)
    return () => {
      unmounted = true
      clearTimeout(timer)
    }
  }, [symbol, spotPrice, dte, targetDte, iv, ivShock, legs])

  // Update leg field
  const updateLeg = (index, field, value) => {
    setLegs((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: value }
      return next
    })
  }

  // Remove leg
  const removeLeg = (index) => {
    setLegs((prev) => prev.filter((_, i) => i !== index))
  }

  // Duplicate leg
  const duplicateLeg = (index) => {
    setLegs((prev) => {
      const item = prev[index]
      if (!item) return prev
      return [...prev.slice(0, index + 1), { ...item }, ...prev.slice(index + 1)]
    })
  }

  // Flip leg (BUY <-> SELL, CE <-> PE)
  const flipLeg = (index) => {
    setLegs((prev) => {
      const next = [...prev]
      const cur = next[index]
      if (!cur) return prev
      next[index] = {
        ...cur,
        action: cur.action === 'BUY' ? 'SELL' : 'BUY',
        option_type: cur.option_type === 'CE' ? 'PE' : 'CE',
      }
      return next
    })
  }

  // Add leg
  const addLeg = () => {
    const s = Math.round(spotPrice / 50) * 50
    setLegs((prev) => [
      ...prev,
      { action: 'BUY', option_type: 'CE', strike: s, premium: 50, lots: 1, lot_size: 25 },
    ])
  }

  // Calculate current spot P&L from target payoff curve
  const currentPnlPoint = simData?.target_payoff?.find(
    (p) => Math.abs(p.spot - sliderSpot) < 50
  ) ?? { pnl: 0 }

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-3xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
        <div>
          <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Strategy Payoff Builder</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-text text-lg font-bold">{symbol}</span>
            <span className="text-amber text-xs bg-amber/10 border border-amber/30 px-2 py-0.5 rounded-md font-ui font-bold">
              {formatINRFull(spotPrice)}
            </span>
            {loading && <span className="text-[10px] text-muted animate-pulse font-ui">⚡ Calculating...</span>}
          </div>
        </div>

        {/* Preset buttons */}
        <div className="flex items-center gap-1 overflow-x-auto text-[11px] font-ui">
          {Object.keys(PRESETS).map((p) => (
            <button
              key={p}
              onClick={() => handlePresetSelect(p)}
              className={`px-2.5 py-1 rounded-lg transition-all whitespace-nowrap cursor-pointer ${
                selectedPreset === p
                  ? 'bg-amber text-black font-extrabold shadow-sm'
                  : 'bg-panel text-muted hover:text-text border border-border/40'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Metrics Row */}
      {simData && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <div className="bg-panel/80 border border-border/60 rounded-xl p-2.5">
            <p className="text-muted text-[10px] uppercase font-ui font-semibold">Max Profit</p>
            <p className="text-green font-bold text-sm mt-0.5">
              {typeof simData.max_profit === 'number'
                ? formatINR(simData.max_profit)
                : simData.max_profit}
            </p>
          </div>
          <div className="bg-panel/80 border border-border/60 rounded-xl p-2.5">
            <p className="text-muted text-[10px] uppercase font-ui font-semibold">Max Loss</p>
            <p className="text-red font-bold text-sm mt-0.5">
              {typeof simData.max_loss === 'number'
                ? formatINR(simData.max_loss)
                : simData.max_loss}
            </p>
          </div>
          <div className="bg-panel/80 border border-border/60 rounded-xl p-2.5">
            <p className="text-muted text-[10px] uppercase font-ui font-semibold">Breakevens</p>
            <p className="text-text font-bold text-xs mt-0.5 truncate">
              {simData.breakevens?.length > 0
                ? simData.breakevens.map((b) => formatINR(b, 0)).join(', ')
                : '—'}
            </p>
          </div>
          <div className="bg-panel/80 border border-border/60 rounded-xl p-2.5">
            <p className="text-muted text-[10px] uppercase font-ui font-semibold">Estimated P&L</p>
            <p className={`font-bold text-sm mt-0.5 ${currentPnlPoint.pnl >= 0 ? 'text-green' : 'text-red'}`}>
              {currentPnlPoint.pnl >= 0 ? '+' : ''}{formatINR(currentPnlPoint.pnl)}
            </p>
          </div>
        </div>
      )}

      {/* Interactive Payoff SVG Graph */}
      {simData?.expiry_payoff && simData.expiry_payoff.length > 0 && (
        <div className="relative bg-surface border border-border/60 rounded-xl p-2.5 overflow-hidden">
          <PayoffSVG
            expiryData={simData.expiry_payoff}
            targetData={simData.target_payoff}
            spotPrice={sliderSpot}
            breakevens={simData.breakevens}
          />
          {/* Graph Legend */}
          <div className="flex items-center justify-between text-[10px] font-ui text-muted px-2 pt-1 border-t border-border/30">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-0.5 bg-green rounded-full inline-block" /> Expiry Payoff
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-0.5 bg-blue border-dashed border-t inline-block" /> T+{targetDte} Payoff
              </span>
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-amber rounded-full inline-block" /> Spot Marker
              </span>
            </div>
            <span>Crosshair: <strong>{formatINRFull(sliderSpot)}</strong></span>
          </div>
        </div>
      )}

      {/* Dynamic Interactive Sliders */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 bg-panel/40 border border-border/50 rounded-xl p-3 text-xs">
        {/* Slider 1: Spot Price */}
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="text-muted font-ui">Spot Price:</span>
            <span className="text-amber font-bold">{formatINRFull(sliderSpot)}</span>
          </div>
          <input
            type="range"
            min={Math.round(spotPrice * 0.85)}
            max={Math.round(spotPrice * 1.15)}
            step={25}
            value={sliderSpot}
            onChange={(e) => setSliderSpot(Number(e.target.value))}
            className="w-full accent-amber cursor-pointer"
          />
        </div>

        {/* Slider 2: Target Evaluation DTE */}
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="text-muted font-ui">Target Evaluation:</span>
            <span className="text-blue font-bold">T+{targetDte} ({dte - targetDte}d left)</span>
          </div>
          <input
            type="range"
            min={0}
            max={dte}
            step={1}
            value={targetDte}
            onChange={(e) => setTargetDte(Number(e.target.value))}
            className="w-full accent-blue cursor-pointer"
          />
        </div>

        {/* Slider 3: IV Shock */}
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="text-muted font-ui">IV Shock:</span>
            <span className={ivShock >= 0 ? 'text-green font-bold' : 'text-red font-bold'}>
              {ivShock >= 0 ? '+' : ''}{ivShock}% (IV: {iv + ivShock}%)
            </span>
          </div>
          <input
            type="range"
            min={-20}
            max={20}
            step={1}
            value={ivShock}
            onChange={(e) => setIvShock(Number(e.target.value))}
            className="w-full accent-purple cursor-pointer"
          />
        </div>
      </div>

      {/* Aggregate Greeks Banner */}
      {simData?.greeks && (
        <div className="flex flex-wrap items-center justify-between gap-3 bg-panel/60 border border-border/40 rounded-xl px-3 py-2 text-[11px]">
          <span className="text-muted uppercase tracking-wider font-ui text-[10px] font-bold">Net Portfolio Greeks</span>
          <div className="flex items-center gap-4">
            <span>Δ Delta: <strong className="text-text">{simData.greeks.delta}</strong></span>
            <span>Γ Gamma: <strong className="text-text">{simData.greeks.gamma}</strong></span>
            <span>Θ Theta: <strong className={simData.greeks.theta >= 0 ? 'text-green' : 'text-red'}>
              {formatINR(simData.greeks.theta)}/day
            </strong></span>
            <span>ν Vega: <strong className="text-text">{formatINR(simData.greeks.vega)}</strong></span>
          </div>
        </div>
      )}

      {/* Interactive Payoff Legs Container */}
      <div className="bg-surface border border-border rounded-xl p-3.5 space-y-2.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted text-[10px] uppercase tracking-wider font-ui font-bold">
            Strategy Legs ({legs.length})
          </span>
          <button
            onClick={addLeg}
            className="text-amber hover:text-amber/80 text-xs font-ui font-bold flex items-center gap-1 cursor-pointer"
          >
            + Add Custom Leg
          </button>
        </div>

        <div className="space-y-2">
          {legs.map((leg, idx) => {
            const isBuy = leg.action === 'BUY'
            const isCall = leg.option_type === 'CE'
            const legCost = (leg.lots || 1) * (leg.lot_size || 25) * (leg.premium || 0)

            return (
              <div
                key={idx}
                className="flex items-center gap-2 bg-panel border border-border/60 hover:border-amber/30 rounded-xl p-2.5 text-xs flex-wrap transition-all"
              >
                {/* Buy / Sell toggle */}
                <select
                  value={leg.action}
                  onChange={(e) => updateLeg(idx, 'action', e.target.value)}
                  className={`bg-elevated border rounded-lg px-2.5 py-1 font-bold cursor-pointer ${
                    isBuy ? 'text-green border-green/30 bg-green/10' : 'text-red border-red/30 bg-red/10'
                  }`}
                >
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>

                {/* CE / PE */}
                <select
                  value={leg.option_type}
                  onChange={(e) => updateLeg(idx, 'option_type', e.target.value)}
                  className={`bg-elevated border rounded-lg px-2 py-1 font-bold cursor-pointer ${
                    isCall ? 'text-cyan-400 border-cyan-500/30' : 'text-purple-400 border-purple-500/30'
                  }`}
                >
                  <option value="CE">CE (Call)</option>
                  <option value="PE">PE (Put)</option>
                </select>

                {/* Strike with Steppers */}
                <div className="flex items-center gap-1">
                  <span className="text-muted text-[10px] uppercase font-bold">Strike</span>
                  <button
                    type="button"
                    onClick={() => updateLeg(idx, 'strike', Math.max(50, leg.strike - 50))}
                    className="w-5 h-5 rounded bg-elevated border border-border flex items-center justify-center text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    −
                  </button>
                  <input
                    type="number"
                    step={50}
                    value={leg.strike}
                    onChange={(e) => updateLeg(idx, 'strike', Number(e.target.value))}
                    className="bg-elevated border border-border rounded-md px-2 py-1 w-20 text-text font-mono text-center font-bold"
                  />
                  <button
                    type="button"
                    onClick={() => updateLeg(idx, 'strike', leg.strike + 50)}
                    className="w-5 h-5 rounded bg-elevated border border-border flex items-center justify-center text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    +
                  </button>
                </div>

                {/* Premium with Steppers */}
                <div className="flex items-center gap-1">
                  <span className="text-muted text-[10px] uppercase font-bold">Prem</span>
                  <button
                    type="button"
                    onClick={() => updateLeg(idx, 'premium', Math.max(0.5, Number((leg.premium - 5).toFixed(1))))}
                    className="w-5 h-5 rounded bg-elevated border border-border flex items-center justify-center text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    −
                  </button>
                  <input
                    type="number"
                    step={0.5}
                    value={leg.premium}
                    onChange={(e) => updateLeg(idx, 'premium', Number(e.target.value))}
                    className="bg-elevated border border-border rounded-md px-2 py-1 w-16 text-text font-mono text-center font-bold"
                  />
                  <button
                    type="button"
                    onClick={() => updateLeg(idx, 'premium', Number((leg.premium + 5).toFixed(1)))}
                    className="w-5 h-5 rounded bg-elevated border border-border flex items-center justify-center text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    +
                  </button>
                </div>

                {/* Lots */}
                <div className="flex items-center gap-1">
                  <span className="text-muted text-[10px] uppercase font-bold">Lots</span>
                  <button
                    type="button"
                    onClick={() => updateLeg(idx, 'lots', Math.max(1, leg.lots - 1))}
                    className="w-5 h-5 rounded bg-elevated border border-border flex items-center justify-center text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    −
                  </button>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={leg.lots}
                    onChange={(e) => updateLeg(idx, 'lots', Number(e.target.value))}
                    className="bg-elevated border border-border rounded-md px-1.5 py-1 w-11 text-text font-mono text-center font-bold"
                  />
                  <button
                    type="button"
                    onClick={() => updateLeg(idx, 'lots', leg.lots + 1)}
                    className="w-5 h-5 rounded bg-elevated border border-border flex items-center justify-center text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    +
                  </button>
                </div>

                {/* Net Outlay Tag */}
                <span className="text-[10px] font-mono px-2 py-1 rounded bg-elevated border border-border text-muted hidden sm:inline-block">
                  {isBuy ? 'Debit' : 'Credit'}: <strong className="text-text">{formatINR(legCost)}</strong>
                </span>

                {/* Action buttons: Duplicate, Flip, Delete */}
                <div className="ml-auto flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => duplicateLeg(idx)}
                    title="Duplicate Leg"
                    className="px-1.5 py-0.5 rounded bg-elevated border border-border text-[10px] text-muted hover:text-text cursor-pointer"
                  >
                    ⎘
                  </button>
                  <button
                    type="button"
                    onClick={() => flipLeg(idx)}
                    title="Flip Action / Type"
                    className="px-1.5 py-0.5 rounded bg-elevated border border-border text-[10px] text-muted hover:text-amber cursor-pointer"
                  >
                    🔄
                  </button>
                  <button
                    type="button"
                    onClick={() => removeLeg(idx)}
                    className="text-muted hover:text-red px-1.5 py-0.5 rounded bg-elevated border border-border text-[10px] cursor-pointer"
                    title="Remove leg"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function PayoffSVG({ expiryData = [], targetData = [], spotPrice, breakevens = [] }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
  if (expiryData.length === 0) return null

  const width = 680
  const height = 240
  const pad = { top: 25, right: 30, bottom: 35, left: 55 }

  const allPoints = [...expiryData, ...targetData]
  const minSpot = Math.min(...allPoints.map((p) => p.spot))
  const maxSpot = Math.max(...allPoints.map((p) => p.spot))
  const minPnl = Math.min(...allPoints.map((p) => p.pnl), -1000)
  const maxPnl = Math.max(...allPoints.map((p) => p.pnl), 1000)

  const scaleX = (s) => pad.left + ((s - minSpot) / (maxSpot - minSpot || 1)) * (width - pad.left - pad.right)
  const scaleY = (p) => pad.top + ((maxPnl - p) / (maxPnl - minPnl || 1)) * (height - pad.top - pad.bottom)
  const unscaleX = (x) => minSpot + ((x - pad.left) / (width - pad.left - pad.right)) * (maxSpot - minSpot)

  const zeroY = scaleY(0)
  const spotX = scaleX(spotPrice)

  // Build SVG path strings
  const expPath = expiryData.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.spot)} ${scaleY(p.pnl)}`).join(' ')
  const targetPath = targetData.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.spot)} ${scaleY(p.pnl)}`).join(' ')

  // Build Area Fills
  const firstX = scaleX(expiryData[0].spot)
  const lastX = scaleX(expiryData[expiryData.length - 1].spot)
  const areaExpPath = `${expPath} L ${lastX} ${zeroY} L ${firstX} ${zeroY} Z`

  const handleMouseMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const mouseX = ((e.clientX - rect.left) / rect.width) * width
    if (mouseX >= pad.left && mouseX <= width - pad.right) {
      const approxSpot = Math.round(unscaleX(mouseX))
      // Find nearest point
      const expPt = expiryData.reduce((prev, curr) =>
        Math.abs(curr.spot - approxSpot) < Math.abs(prev.spot - approxSpot) ? curr : prev
      )
      const tgtPt = targetData.find((p) => p.spot === expPt.spot) || expPt
      const pctDiff = ((expPt.spot - spotPrice) / spotPrice) * 100

      setHoveredPoint({
        spot: expPt.spot,
        x: scaleX(expPt.spot),
        expPnl: expPt.pnl,
        tgtPnl: tgtPt.pnl,
        pctDiff,
      })
    }
  }

  const handleMouseLeave = () => setHoveredPoint(null)

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        className="w-full h-auto select-none overflow-visible cursor-crosshair"
      >
        <defs>
          <linearGradient id="profitFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.0" />
          </linearGradient>
          <linearGradient id="lossFill" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor="#ef4444" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#ef4444" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Shaded Area Under Curve */}
        <path d={areaExpPath} fill="url(#profitFill)" opacity="0.8" />

        {/* Zero P&L Axis */}
        <line
          x1={pad.left}
          y1={zeroY}
          x2={width - pad.right}
          y2={zeroY}
          stroke="#4b5563"
          strokeDasharray="3 3"
          strokeWidth="1.5"
        />
        <text
          x={pad.left - 8}
          y={zeroY + 3}
          fill="#9ca3af"
          fontSize="10"
          textAnchor="end"
          fontFamily="monospace"
          fontWeight="bold"
        >
          ₹0
        </text>

        {/* Spot Price vertical marker */}
        {spotX >= pad.left && spotX <= width - pad.right && (
          <g>
            <line
              x1={spotX}
              y1={pad.top}
              x2={spotX}
              y2={height - pad.bottom}
              stroke="#f59e0b"
              strokeWidth="1.8"
              strokeDasharray="3 3"
            />
            <circle cx={spotX} cy={zeroY} r="4" fill="#f59e0b" stroke="#000" strokeWidth="1.5" />
            <text
              x={spotX}
              y={pad.top - 6}
              fill="#f59e0b"
              fontSize="9"
              textAnchor="middle"
              fontFamily="monospace"
              fontWeight="bold"
            >
              SPOT ₹{Math.round(spotPrice).toLocaleString('en-IN')}
            </text>
          </g>
        )}

        {/* Breakeven lines */}
        {breakevens.map((be, idx) => {
          const bx = scaleX(be)
          if (bx < pad.left || bx > width - pad.right) return null
          return (
            <g key={idx}>
              <line
                x1={bx}
                y1={pad.top}
                x2={bx}
                y2={height - pad.bottom}
                stroke="#9ca3af"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
              <circle cx={bx} cy={zeroY} r="2.5" fill="#9ca3af" />
              <text
                x={bx}
                y={height - pad.bottom + 14}
                fill="#9ca3af"
                fontSize="9"
                textAnchor="middle"
                fontFamily="monospace"
              >
                BE ₹{Math.round(be).toLocaleString('en-IN')}
              </text>
            </g>
          )
        })}

        {/* Expiry Payoff Line */}
        <path d={expPath} fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round" />

        {/* Target Date T+DTE Payoff Line */}
        {targetPath && (
          <path d={targetPath} fill="none" stroke="#38bdf8" strokeWidth="2" strokeDasharray="4 3" />
        )}

        {/* Hover Crosshair Marker */}
        {hoveredPoint && (
          <g>
            <line
              x1={hoveredPoint.x}
              y1={pad.top}
              x2={hoveredPoint.x}
              y2={height - pad.bottom}
              stroke="#e5e7eb"
              strokeWidth="1"
              strokeDasharray="2 2"
            />
            <circle
              cx={hoveredPoint.x}
              cy={scaleY(hoveredPoint.expPnl)}
              r="4.5"
              fill={hoveredPoint.expPnl >= 0 ? '#22c55e' : '#ef4444'}
              stroke="#ffffff"
              strokeWidth="2"
            />
          </g>
        )}
      </svg>

      {/* Dynamic Hover Tooltip Bubble */}
      {hoveredPoint && (
        <div
          style={{
            left: `${Math.max(10, Math.min(85, (hoveredPoint.x / width) * 100))}%`,
            top: '8px',
          }}
          className="absolute -translate-x-1/2 bg-elevated/95 border border-border/80 backdrop-blur-md px-3 py-1.5 rounded-xl shadow-xl font-mono text-[11px] pointer-events-none z-30 flex items-center gap-3 animate-in fade-in"
        >
          <div>
            <span className="text-muted block text-[9px]">UNDERLYING SPOT</span>
            <span className="font-bold text-text">
              ₹{hoveredPoint.spot.toLocaleString('en-IN')}{' '}
              <span className={`text-[10px] ${hoveredPoint.pctDiff >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                ({hoveredPoint.pctDiff >= 0 ? '+' : ''}
                {hoveredPoint.pctDiff.toFixed(1)}%)
              </span>
            </span>
          </div>
          <div className="border-l border-border/50 pl-2.5">
            <span className="text-muted block text-[9px]">EXPIRY P&L</span>
            <span className={`font-bold ${hoveredPoint.expPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {hoveredPoint.expPnl >= 0 ? '+' : ''}₹{Math.round(hoveredPoint.expPnl).toLocaleString('en-IN')}
            </span>
          </div>
          <div className="border-l border-border/50 pl-2.5">
            <span className="text-muted block text-[9px]">T+TARGET P&L</span>
            <span className={`font-bold ${hoveredPoint.tgtPnl >= 0 ? 'text-cyan-400' : 'text-rose-400'}`}>
              {hoveredPoint.tgtPnl >= 0 ? '+' : ''}₹{Math.round(hoveredPoint.tgtPnl).toLocaleString('en-IN')}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
