import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'

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
          <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Strategy Simulator</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-text text-lg font-semibold">{symbol}</span>
            <span className="text-amber text-xs bg-amber/10 border border-amber/30 px-1.5 py-0.5 rounded font-ui">
              ₹{spotPrice.toLocaleString('en-IN')}
            </span>
          </div>
        </div>

        {/* Preset buttons */}
        <div className="flex items-center gap-1 overflow-x-auto text-[11px] font-ui">
          {Object.keys(PRESETS).map((p) => (
            <button
              key={p}
              onClick={() => handlePresetSelect(p)}
              className={`px-2 py-1 rounded transition-all whitespace-nowrap ${
                selectedPreset === p
                  ? 'bg-amber text-black font-semibold'
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
          <div className="bg-panel/80 border border-border/60 rounded-lg p-2">
            <p className="text-muted text-[10px] uppercase font-ui">Max Profit</p>
            <p className="text-green font-semibold mt-0.5">
              {typeof simData.max_profit === 'number'
                ? `₹${simData.max_profit.toLocaleString('en-IN')}`
                : simData.max_profit}
            </p>
          </div>
          <div className="bg-panel/80 border border-border/60 rounded-lg p-2">
            <p className="text-muted text-[10px] uppercase font-ui">Max Loss</p>
            <p className="text-red font-semibold mt-0.5">
              {typeof simData.max_loss === 'number'
                ? `₹${simData.max_loss.toLocaleString('en-IN')}`
                : simData.max_loss}
            </p>
          </div>
          <div className="bg-panel/80 border border-border/60 rounded-lg p-2">
            <p className="text-muted text-[10px] uppercase font-ui">Breakevens</p>
            <p className="text-text font-semibold mt-0.5 truncate">
              {simData.breakevens?.length > 0
                ? simData.breakevens.map((b) => `₹${b.toLocaleString('en-IN')}`).join(', ')
                : '—'}
            </p>
          </div>
          <div className="bg-panel/80 border border-border/60 rounded-lg p-2">
            <p className="text-muted text-[10px] uppercase font-ui">Estimated P&L</p>
            <p className={`font-semibold mt-0.5 ${currentPnlPoint.pnl >= 0 ? 'text-green' : 'text-red'}`}>
              {currentPnlPoint.pnl >= 0 ? '+' : ''}₹{currentPnlPoint.pnl.toLocaleString('en-IN')}
            </p>
          </div>
        </div>
      )}

      {/* Interactive Payoff SVG Graph */}
      {simData?.expiry_payoff && simData.expiry_payoff.length > 0 && (
        <div className="relative bg-surface border border-border/60 rounded-lg p-2 overflow-hidden">
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
            <span>Crosshair: ₹{sliderSpot.toLocaleString('en-IN')}</span>
          </div>
        </div>
      )}

      {/* Dynamic Interactive Sliders */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 bg-panel/40 border border-border/50 rounded-lg p-3 text-xs">
        {/* Slider 1: Spot Price */}
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="text-muted font-ui">Spot Price:</span>
            <span className="text-amber font-semibold">₹{sliderSpot.toLocaleString('en-IN')}</span>
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
            <span className="text-blue font-semibold">T+{targetDte} ({dte - targetDte}d left)</span>
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
            <span className={ivShock >= 0 ? 'text-green font-semibold' : 'text-red font-semibold'}>
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
        <div className="flex flex-wrap items-center justify-between gap-3 bg-panel/60 border border-border/40 rounded-lg px-3 py-2 text-[11px]">
          <span className="text-muted uppercase tracking-wider font-ui text-[10px]">Net Greeks</span>
          <div className="flex items-center gap-4">
            <span>Delta: <strong className="text-text">{simData.greeks.delta}</strong></span>
            <span>Gamma: <strong className="text-text">{simData.greeks.gamma}</strong></span>
            <span>Theta: <strong className={simData.greeks.theta >= 0 ? 'text-green' : 'text-red'}>
              ₹{simData.greeks.theta}/day
            </strong></span>
            <span>Vega: <strong className="text-text">₹{simData.greeks.vega}</strong></span>
          </div>
        </div>
      )}

      {/* Interactive Payoff SVG Chart */}
      <div className="bg-surface border border-border rounded-xl p-3.5 space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted text-[10px] uppercase tracking-wider font-ui">Strategy Legs ({legs.length})</span>
          <button
            onClick={addLeg}
            className="text-amber text-xs font-ui hover:underline flex items-center gap-1"
          >
            + Add Custom Leg
          </button>
        </div>

        <div className="space-y-1.5">
          {legs.map((leg, idx) => (
            <div
              key={idx}
              className="flex items-center gap-2 bg-panel border border-border/40 rounded p-2 text-xs flex-wrap"
            >
              {/* Buy / Sell toggle */}
              <select
                value={leg.action}
                onChange={(e) => updateLeg(idx, 'action', e.target.value)}
                className={`bg-elevated border rounded px-2 py-1 font-semibold ${
                  leg.action === 'BUY' ? 'text-green border-green/30' : 'text-red border-red/30'
                }`}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>

              {/* CE / PE */}
              <select
                value={leg.option_type}
                onChange={(e) => updateLeg(idx, 'option_type', e.target.value)}
                className="bg-elevated border border-border rounded px-2 py-1 text-text font-semibold"
              >
                <option value="CE">CE (Call)</option>
                <option value="PE">PE (Put)</option>
              </select>

              {/* Strike */}
              <div className="flex items-center gap-1">
                <span className="text-muted text-[10px]">Strike:</span>
                <input
                  type="number"
                  step={50}
                  value={leg.strike}
                  onChange={(e) => updateLeg(idx, 'strike', Number(e.target.value))}
                  className="bg-elevated border border-border rounded px-2 py-1 w-20 text-text font-mono"
                />
              </div>

              {/* Premium */}
              <div className="flex items-center gap-1">
                <span className="text-muted text-[10px]">Premium:</span>
                <input
                  type="number"
                  step={1}
                  value={leg.premium}
                  onChange={(e) => updateLeg(idx, 'premium', Number(e.target.value))}
                  className="bg-elevated border border-border rounded px-2 py-1 w-16 text-text font-mono"
                />
              </div>

              {/* Lots */}
              <div className="flex items-center gap-1">
                <span className="text-muted text-[10px]">Lots:</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={leg.lots}
                  onChange={(e) => updateLeg(idx, 'lots', Number(e.target.value))}
                  className="bg-elevated border border-border rounded px-2 py-1 w-12 text-text font-mono"
                />
              </div>

              <button
                onClick={() => removeLeg(idx)}
                className="ml-auto text-muted hover:text-red px-1 text-xs"
                title="Remove leg"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function PayoffSVG({ expiryData = [], targetData = [], spotPrice, breakevens = [] }) {
  if (expiryData.length === 0) return null

  const width = 680
  const height = 220
  const pad = { top: 20, right: 30, bottom: 30, left: 50 }

  const allPoints = [...expiryData, ...targetData]
  const minSpot = Math.min(...allPoints.map((p) => p.spot))
  const maxSpot = Math.max(...allPoints.map((p) => p.spot))
  const minPnl = Math.min(...allPoints.map((p) => p.pnl), -1000)
  const maxPnl = Math.max(...allPoints.map((p) => p.pnl), 1000)

  const scaleX = (s) => pad.left + ((s - minSpot) / (maxSpot - minSpot || 1)) * (width - pad.left - pad.right)
  const scaleY = (p) => pad.top + ((maxPnl - p) / (maxPnl - minPnl || 1)) * (height - pad.top - pad.bottom)

  const zeroY = scaleY(0)
  const spotX = scaleX(spotPrice)

  // Build SVG path strings
  const expPath = expiryData.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.spot)} ${scaleY(p.pnl)}`).join(' ')
  const targetPath = targetData.map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.spot)} ${scaleY(p.pnl)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto select-none overflow-visible">
      {/* Grid Lines */}
      <line x1={pad.left} y1={zeroY} x2={width - pad.right} y2={zeroY} stroke="#333333" strokeDasharray="3 3" strokeWidth="1.5" />
      <text x={pad.left - 8} y={zeroY + 3} fill="#666" fontSize="10" textAnchor="end" fontFamily="monospace">₹0</text>

      {/* Spot Price vertical marker */}
      {spotX >= pad.left && spotX <= width - pad.right && (
        <g>
          <line x1={spotX} y1={pad.top} x2={spotX} y2={height - pad.bottom} stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="2 2" />
          <circle cx={spotX} cy={zeroY} r="3" fill="#f59e0b" />
        </g>
      )}

      {/* Breakeven lines */}
      {breakevens.map((be, idx) => {
        const bx = scaleX(be)
        if (bx < pad.left || bx > width - pad.right) return null
        return (
          <g key={idx}>
            <line x1={bx} y1={pad.top} x2={bx} y2={height - pad.bottom} stroke="#6b7280" strokeWidth="1" strokeDasharray="2 2" />
            <text x={bx} y={height - pad.bottom + 12} fill="#9ca3af" fontSize="9" textAnchor="middle" fontFamily="monospace">
              BE ₹{Math.round(be)}
            </text>
          </g>
        )
      })}

      {/* Expiry Payoff Line */}
      <path d={expPath} fill="none" stroke="#22c55e" strokeWidth="2.5" />

      {/* Target Date T+0 Payoff Line */}
      {targetPath && (
        <path d={targetPath} fill="none" stroke="#3b82f6" strokeWidth="2" strokeDasharray="4 2" />
      )}
    </svg>
  )
}
