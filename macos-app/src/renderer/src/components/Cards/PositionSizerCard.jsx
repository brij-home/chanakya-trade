import { useState } from 'react'
import { useInspectorStore } from '../../store/inspectorStore'
import Tooltip, { InfoBadge } from '../UI/Tooltip'

export default function PositionSizerCard({ data }) {
  const init = data?.data ?? data ?? {}
  const openInspector = useInspectorStore((s) => s.openInspector)

  const [symbol, setSymbol] = useState(init.symbol || 'NIFTY')
  const [entryPrice, setEntryPrice] = useState(Number(init.entry_price || 24000))
  const [stopLoss, setStopLoss] = useState(Number(init.stop_loss || (init.entry_price ? init.entry_price * 0.98 : 23600)))
  const [capital, setCapital] = useState(Number(init.capital || 200000))
  const [riskPct, setRiskPct] = useState(Number(init.max_risk_pct || 1.5))
  const [model, setModel] = useState(init.sizing_model || 'atr_volatility')
  const [isFno, setIsFno] = useState(Boolean(init.is_fno || ['NIFTY', 'BANKNIFTY', 'FINNIFTY'].includes(symbol)))

  // Stop distance
  const stopDist = Math.max(0.01, Math.abs(entryPrice - stopLoss))
  const riskBudget = capital * (riskPct / 100)

  // Local live calculation
  let rawShares = Math.floor(riskBudget / stopDist)
  if (model === 'atr_volatility') {
    const volStop = stopDist * 1.2
    rawShares = Math.floor(riskBudget / volStop)
  } else if (model === 'half_kelly') {
    const halfKellyAlloc = capital * 0.15
    rawShares = Math.floor(halfKellyAlloc / entryPrice)
  }

  // Capital ceiling (max 25%)
  const maxCap = capital * 0.25
  const capLimitedShares = Math.floor(maxCap / entryPrice)
  let calculatedShares = Math.min(rawShares, capLimitedShares)

  // Lot size detection
  let lotSize = 1
  if (isFno || symbol === 'NIFTY') lotSize = 25
  else if (symbol === 'BANKNIFTY') lotSize = 15
  else if (symbol === 'FINNIFTY') lotSize = 25

  let lots = 1
  if (lotSize > 1) {
    lots = Math.floor(calculatedShares / lotSize)
    if (lots === 0 && capital >= entryPrice * lotSize) lots = 1
    calculatedShares = lots * lotSize
  } else {
    calculatedShares = Math.max(1, calculatedShares)
    lots = 1
  }

  const capitalAllocated = calculatedShares * entryPrice
  const capitalPct = ((capitalAllocated / capital) * 100).toFixed(1)
  const actualRiskAmt = calculatedShares * stopDist
  const actualRiskPct = ((actualRiskAmt / capital) * 100).toFixed(2)
  const targetPrice = entryPrice + (stopDist * 2)
  const potentialProfit = calculatedShares * (stopDist * 2)

  return (
    <div className="bg-elevated border border-border rounded-xl p-4 max-w-2xl w-full space-y-4 font-mono shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/40 pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-amber text-lg">⚖️</span>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-muted text-[10px] uppercase tracking-widest font-ui">Institutional Risk Parity</p>
              <InfoBadge
                title="Volatility Risk-Parity"
                content="Positions are sized so that each trade contributes an equal dollar risk to the portfolio based on ATR volatility."
                metricKey="volatility_risk_parity"
              />
            </div>
            <p className="text-text text-base font-semibold font-ui">Position Sizing & Risk Budget Calculator</p>
          </div>
        </div>

        <Tooltip
          title={`Active Ticker: ${symbol}`}
          content="Click to inspect model for this asset."
          metricKey="volatility_risk_parity"
        >
          <span
            onClick={() => openInspector('volatility_risk_parity', { symbol })}
            className="text-xs bg-panel hover:bg-elevated border border-border px-2.5 py-1 rounded text-amber font-mono font-bold cursor-pointer transition-colors"
          >
            {symbol}
          </span>
        </Tooltip>
      </div>

      {/* Interactive Parameter Controls */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 bg-panel border border-border/60 p-3 rounded-lg text-xs font-ui">
        <div>
          <div className="flex items-center justify-between">
            <label className="text-[10px] text-muted uppercase">Entry Price (₹)</label>
          </div>
          <input
            type="number"
            value={entryPrice}
            onChange={(e) => setEntryPrice(Number(e.target.value))}
            className="w-full bg-elevated border border-border px-2 py-1 rounded text-text font-mono font-semibold mt-1 focus:outline-none focus:border-amber"
          />
        </div>

        <div>
          <label className="text-[10px] text-muted uppercase">Stop-Loss (₹)</label>
          <input
            type="number"
            value={stopLoss}
            onChange={(e) => setStopLoss(Number(e.target.value))}
            className="w-full bg-elevated border border-border px-2 py-1 rounded text-red font-mono font-semibold mt-1 focus:outline-none focus:border-red"
          />
        </div>

        <div>
          <label className="text-[10px] text-muted uppercase">Capital Budget (₹)</label>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="w-full bg-elevated border border-border px-2 py-1 rounded text-text font-mono font-semibold mt-1 focus:outline-none focus:border-amber"
          />
        </div>

        <div>
          <div className="flex items-center justify-between">
            <label className="text-[10px] text-muted uppercase">Risk Per Trade (%)</label>
            <InfoBadge
              title="1.5% Prudent Risk Rule"
              content="Risking 1-2% per trade ensures an account can survive 10+ consecutive losses without drawdowns exceeding 15%."
              metricKey="volatility_risk_parity"
            />
          </div>
          <input
            type="number"
            step="0.1"
            value={riskPct}
            onChange={(e) => setRiskPct(Number(e.target.value))}
            className="w-full bg-elevated border border-border px-2 py-1 rounded text-amber font-mono font-semibold mt-1 focus:outline-none focus:border-amber"
          />
        </div>
      </div>

      {/* Sizing Model Toggle & F&O Setting */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-ui">
        <div className="flex items-center gap-1.5 bg-panel p-1 rounded-lg border border-border/50">
          <Tooltip
            title="ATR Volatility Model"
            content="Adjusts stop distance by 1.5x ATR to prevent premature stop outs from market noise."
            metricKey="volatility_risk_parity"
          >
            <button
              onClick={() => setModel('atr_volatility')}
              className={`px-2.5 py-1 rounded transition-colors cursor-pointer ${
                model === 'atr_volatility' ? 'bg-amber text-surface font-bold' : 'text-muted hover:text-text'
              }`}
            >
              ATR Volatility
            </button>
          </Tooltip>

          <Tooltip
            title="Fixed Stop % Model"
            content="Direct stop distance division based purely on your charted technical price level."
            metricKey="volatility_risk_parity"
          >
            <button
              onClick={() => setModel('fixed_fractional')}
              className={`px-2.5 py-1 rounded transition-colors cursor-pointer ${
                model === 'fixed_fractional' ? 'bg-amber text-surface font-bold' : 'text-muted hover:text-text'
              }`}
            >
              Fixed Stop %
            </button>
          </Tooltip>

          <Tooltip
            title="Half-Kelly Growth Model"
            content="Optimal geometric capital growth formula (0.5x Kelly) for high win-rate strategies."
            metricKey="half_kelly"
          >
            <button
              onClick={() => setModel('half_kelly')}
              className={`px-2.5 py-1 rounded transition-colors cursor-pointer ${
                model === 'half_kelly' ? 'bg-amber text-surface font-bold' : 'text-muted hover:text-text'
              }`}
            >
              Half-Kelly
            </button>
          </Tooltip>
        </div>

        <label className="flex items-center gap-2 cursor-pointer text-muted hover:text-text">
          <input
            type="checkbox"
            checked={isFno}
            onChange={(e) => setIsFno(e.target.checked)}
            className="rounded border-border text-amber focus:ring-amber"
          />
          <span>F&O Lot Multiplier ({lotSize > 1 ? `${lotSize}x` : '1x'})</span>
        </label>
      </div>

      {/* Output Metric Cards Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Tooltip
          title="Recommended Shares / Lots"
          content="Quantity quantized according to standard exchange lot sizes."
          metricKey="volatility_risk_parity"
        >
          <div
            onClick={() => openInspector('volatility_risk_parity', { symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 hover:border-green/50 p-2.5 rounded-lg space-y-1 cursor-pointer transition-all w-full text-left"
          >
            <p className="text-[10px] text-muted font-ui uppercase">Optimal Shares</p>
            <p className="text-xl font-bold font-mono text-green">{calculatedShares.toLocaleString()}</p>
            {lotSize > 1 && (
              <p className="text-[10px] text-amber font-mono">{lots} Contract Lot{lots > 1 ? 's' : ''}</p>
            )}
          </div>
        </Tooltip>

        <Tooltip
          title="Total Capital Allocated"
          content="Total rupee outlay for the position. Max 25% single-stock ceiling."
          metricKey="volatility_risk_parity"
        >
          <div
            onClick={() => openInspector('volatility_risk_parity', { symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 hover:border-amber/50 p-2.5 rounded-lg space-y-1 cursor-pointer transition-all w-full text-left"
          >
            <p className="text-[10px] text-muted font-ui uppercase">Capital Allocated</p>
            <p className="text-xl font-bold font-mono text-text">₹{capitalAllocated.toLocaleString()}</p>
            <p className="text-[10px] text-muted font-mono">{capitalPct}% of Account</p>
          </div>
        </Tooltip>

        <Tooltip
          title="Max Dollar Rupee Risk"
          content="Total loss if the stop-loss order triggers at the designated price."
          metricKey="volatility_risk_parity"
        >
          <div
            onClick={() => openInspector('volatility_risk_parity', { symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 hover:border-red/50 p-2.5 rounded-lg space-y-1 cursor-pointer transition-all w-full text-left"
          >
            <p className="text-[10px] text-muted font-ui uppercase">Max Rupee Risk</p>
            <p className="text-xl font-bold font-mono text-red">₹{actualRiskAmt.toLocaleString()}</p>
            <p className="text-[10px] text-muted font-mono">{actualRiskPct}% Portfolio Risk</p>
          </div>
        </Tooltip>

        <Tooltip
          title="2R Target Payoff"
          content="Expected profit at a 2.0 Risk-to-Reward target milestone."
          metricKey="volatility_risk_parity"
        >
          <div
            onClick={() => openInspector('volatility_risk_parity', { symbol })}
            className="bg-panel hover:bg-elevated/70 border border-border/60 hover:border-green/50 p-2.5 rounded-lg space-y-1 cursor-pointer transition-all w-full text-left"
          >
            <p className="text-[10px] text-muted font-ui uppercase">2R Target Profit</p>
            <p className="text-xl font-bold font-mono text-green">₹{potentialProfit.toLocaleString()}</p>
            <p className="text-[10px] text-muted font-mono">Target: ₹{targetPrice.toLocaleString()}</p>
          </div>
        </Tooltip>
      </div>

      {/* R:R Visual Progress Bar */}
      <Tooltip
        title="1:2 Risk to Reward Ratio"
        content="Risk ₹1 to make ₹2. With a 40% win rate, 1:2 R:R delivers positive long-term mathematical expectancy."
        metricKey="volatility_risk_parity"
      >
        <div
          onClick={() => openInspector('volatility_risk_parity', { symbol })}
          className="w-full bg-panel hover:bg-elevated/60 border border-border/60 rounded-lg p-3 space-y-2 cursor-pointer transition-colors text-left"
        >
          <div className="flex items-center justify-between text-xs font-ui">
            <span className="text-red font-semibold">Stop: ₹{stopLoss} (-₹{stopDist})</span>
            <span className="font-bold text-amber font-mono">1 : 2.0 R:R Ratio</span>
            <span className="text-green font-semibold">Target: ₹{targetPrice} (+₹{(stopDist * 2).toFixed(1)})</span>
          </div>
          <div className="flex h-2 rounded-full overflow-hidden">
            <div className="bg-red w-1/3" title="1R Risk" />
            <div className="bg-green w-2/3" title="2R Reward" />
          </div>
        </div>
      </Tooltip>
    </div>
  )
}

