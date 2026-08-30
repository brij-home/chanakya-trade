import { useState, useEffect } from 'react'
import { useAPI } from '../../hooks/useAPI'

export default function OrderTicketModal({ isOpen, onClose, initialData = {} }) {
  const { call } = useAPI()

  const [symbol, setSymbol] = useState(initialData.symbol || 'RELIANCE')
  const [exchange, setExchange] = useState(initialData.exchange || 'NSE')
  const [action, setAction] = useState(initialData.action || initialData.side || initialData.orderType || 'BUY')
  const [orderType, setOrderType] = useState('LIMIT')
  const [product, setProduct] = useState('MIS') // MIS (Intraday) | CNC (Delivery) | NRML (F&O)
  const [price, setPrice] = useState(initialData.price || 2800)
  const [stopLoss, setStopLoss] = useState(initialData.stopLoss || initialData.stop_loss || 2760)
  const [target, setTarget] = useState(initialData.target || initialData.target_1 || 2890)
  const [capital, setCapital] = useState(200000)
  const [riskPct, setRiskPct] = useState(1.0)
  const [qty, setQty] = useState(initialData.qty || initialData.quantity || 50)
  const [step, setStep] = useState(1) // 1: Edit/Stage, 2: Double Confirm
  const [confirmedRisk, setConfirmedRisk] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [statusMsg, setStatusMsg] = useState(null)
  const [preflightInfo, setPreflightInfo] = useState(null)
  const [isValidatingRisk, setIsValidatingRisk] = useState(false)

  // Sync state whenever modal opens or initialData changes
  useEffect(() => {
    if (isOpen) {
      if (initialData.symbol) setSymbol(initialData.symbol)
      if (initialData.exchange) setExchange(initialData.exchange)
      const act = initialData.action || initialData.side || initialData.orderType
      if (act) setAction(act)
      if (initialData.price) setPrice(Number(initialData.price))
      const sl = initialData.stopLoss ?? initialData.stop_loss
      if (sl != null) setStopLoss(Number(sl))
      const tgt = initialData.target ?? initialData.target_1 ?? initialData.target_2
      if (tgt != null) setTarget(Number(tgt))
      const q = initialData.qty ?? initialData.quantity
      if (q != null) setQty(Number(q))
      setStep(1)
      setStatusMsg(null)
      setConfirmedRisk(false)
    }
  }, [isOpen, initialData])

  // Auto-calculate position size based on 1% risk rule
  useEffect(() => {
    if (price > 0 && stopLoss > 0 && price !== stopLoss) {
      const riskPerShare = Math.abs(price - stopLoss)
      const maxRiskAmount = capital * (riskPct / 100)
      const calculatedQty = Math.max(1, Math.floor(maxRiskAmount / riskPerShare))
      setQty(calculatedQty)
    }
  }, [price, stopLoss, capital, riskPct])

  const riskAmount = Math.abs(price - stopLoss) * qty
  const rewardAmount = Math.abs(target - price) * qty
  const riskRewardRatio = riskAmount > 0 ? (rewardAmount / riskAmount).toFixed(2) : 0
  const orderValue = price * qty

  const handleProceedToConfirm = async () => {
    setStatusMsg(null)
    setConfirmedRisk(false)
    setIsValidatingRisk(true)
    try {
      const res = await call('/api/risk/preflight', {
        symbol,
        action,
        quantity: qty,
        price,
        allow_override: true,
      })
      setPreflightInfo(res?.data ?? res)
    } catch {
      setPreflightInfo(null)
    } finally {
      setIsValidatingRisk(false)
      setStep(2)
    }
  }

  const handlePlaceOrder = async () => {
    if (!confirmedRisk) {
      setStatusMsg({ type: 'error', text: 'Please check the confirmation box to acknowledge risk.' })
      return
    }
    setIsSubmitting(true)
    setStatusMsg(null)
    try {
      // Simulate order placement through Risk Gate in Paper mode
      await new Promise((r) => setTimeout(r, 600))
      setStatusMsg({
        type: 'success',
        text: `✓ Order Executed: ${action} ${qty} ${symbol} @ ₹${Number(price).toFixed(2)} [SL: ₹${stopLoss}, TGT: ₹${target}]`,
      })
      setTimeout(() => {
        setStep(1)
        onClose()
      }, 1500)
    } catch (err) {
      setStatusMsg({ type: 'error', text: err.message || 'Order rejected by Risk Gate' })
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4 select-none animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="bg-panel border border-border rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl font-mono animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >

        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/50 bg-panel/40">
          <div className="flex items-center gap-2">
            <span className="text-amber text-lg">{step === 1 ? '⚡' : '🛡️'}</span>
            <div>
              <p className="text-text text-sm font-semibold font-ui">
                {step === 1 ? 'Smart Order Staging' : 'Double Confirmation Gate'}
              </p>
              <p className="text-muted text-[10px] uppercase font-ui">
                {step === 1 ? 'Default Role: DATA ONLY (Protected)' : 'Step 2 of 2: Verify & Transmit'}
              </p>
            </div>
          </div>
          <button
            onClick={() => {
              setStep(1)
              onClose()
            }}
            className="text-muted hover:text-text p-1 rounded transition-colors text-base cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Modal Content */}
        <div className="p-5 space-y-4 text-xs">
          {step === 1 ? (
            <>
              {/* Action & Symbol Header */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-muted text-[10px] uppercase font-ui block mb-1">Direction</span>
                  <div className="grid grid-cols-2 gap-1 bg-panel p-1 rounded-lg border border-border/60">
                    <button
                      type="button"
                      onClick={() => setAction('BUY')}
                      className={`py-1 rounded font-semibold text-center transition-all cursor-pointer ${
                        action === 'BUY' ? 'bg-green text-black shadow-xs' : 'text-muted hover:text-text'
                      }`}
                    >
                      BUY
                    </button>
                    <button
                      type="button"
                      onClick={() => setAction('SELL')}
                      className={`py-1 rounded font-semibold text-center transition-all cursor-pointer ${
                        action === 'SELL' ? 'bg-red text-white shadow-xs' : 'text-muted hover:text-text'
                      }`}
                    >
                      SELL
                    </button>
                  </div>
                </div>

                <div>
                  <span className="text-muted text-[10px] uppercase font-ui block mb-1">Trading Symbol</span>
                  <input
                    type="text"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                    className="w-full bg-panel border border-border/60 rounded-lg px-3 py-1.5 text-text font-bold uppercase"
                  />
                </div>
              </div>

              {/* Price, Stop-Loss, Target */}
              <div className="grid grid-cols-3 gap-2">
                <div className="space-y-1">
                  <span className="text-muted text-[10px] uppercase font-ui">Entry Price</span>
                  <input
                    type="number"
                    step="0.05"
                    value={price}
                    onChange={(e) => setPrice(Number(e.target.value))}
                    className="w-full bg-panel border border-border/60 rounded px-2.5 py-1.5 text-text font-mono"
                  />
                </div>
                <div className="space-y-1">
                  <span className="text-red text-[10px] uppercase font-ui font-semibold">Stop Loss</span>
                  <input
                    type="number"
                    step="0.05"
                    value={stopLoss}
                    onChange={(e) => setStopLoss(Number(e.target.value))}
                    className="w-full bg-panel border border-red/40 rounded px-2.5 py-1.5 text-red font-mono"
                  />
                </div>
                <div className="space-y-1">
                  <span className="text-green text-[10px] uppercase font-ui font-semibold">Target</span>
                  <input
                    type="number"
                    step="0.05"
                    value={target}
                    onChange={(e) => setTarget(Number(e.target.value))}
                    className="w-full bg-panel border border-green/40 rounded px-2.5 py-1.5 text-green font-mono"
                  />
                </div>
              </div>

              {/* Risk Sizing Card */}
              <div className="bg-panel/60 border border-border/50 rounded-xl p-3 space-y-2">
                <div className="flex justify-between items-center text-[11px] font-ui">
                  <span className="text-muted">Auto Position Sizing (Risk %):</span>
                  <div className="flex items-center gap-1">
                    {[0.5, 1.0, 2.0].map((pct) => (
                      <button
                        key={pct}
                        onClick={() => setRiskPct(pct)}
                        className={`px-1.5 py-0.5 rounded border text-[10px] cursor-pointer ${
                          riskPct === pct ? 'bg-amber text-black font-semibold' : 'text-muted border-border/40'
                        }`}
                      >
                        {pct}%
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border/30 text-[11px]">
                  <div>
                    <span className="text-muted text-[10px] block font-ui">Calculated Qty</span>
                    <span className="text-text font-bold text-sm">{qty}</span>
                  </div>
                  <div>
                    <span className="text-muted text-[10px] block font-ui">Max Risk</span>
                    <span className="text-red font-semibold">₹{riskAmount.toFixed(0)}</span>
                  </div>
                  <div>
                    <span className="text-muted text-[10px] block font-ui">Risk:Reward</span>
                    <span className="text-green font-bold">1:{riskRewardRatio}</span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-2 pt-2 border-t border-border/40">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-lg bg-panel hover:bg-elevated text-muted hover:text-text font-ui transition-colors text-xs cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleProceedToConfirm}
                  className={`px-5 py-2 rounded-lg font-semibold font-ui text-xs transition-all flex items-center gap-1.5 cursor-pointer ${
                    action === 'BUY' ? 'bg-green hover:bg-green/90 text-black' : 'bg-red hover:bg-red/90 text-white'
                  }`}
                >
                  Review & Confirm {action} (₹{orderValue.toLocaleString('en-IN')}) &rarr;
                </button>
              </div>
            </>
          ) : (
            <>
              {/* Step 2: Double Confirmation Screen */}
              <div className="bg-elevated border border-amber/30 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between text-amber font-ui font-semibold text-xs">
                  <div className="flex items-center gap-2">
                    <span>🛡️</span>
                    <span>Execution Review & Risk Guardrails</span>
                  </div>
                  {preflightInfo?.flags?.length > 0 && (
                    <span className="bg-amber/20 text-amber text-[10px] px-2 py-0.5 rounded-full border border-amber/40">
                      Advisory Active ({preflightInfo.flags.length})
                    </span>
                  )}
                </div>

                {/* Behavioral Tilt & Risk Advisory Box if flags detected */}
                {preflightInfo?.flags?.length > 0 && (
                  <div className="bg-amber/10 border border-amber/40 rounded-lg p-3 space-y-2 text-left">
                    <div className="flex items-center gap-1.5 text-amber font-bold text-[11px]">
                      <span>🧠</span>
                      <span>Behavioral Risk & Tilt Advisory (Co-Pilot)</span>
                    </div>
                    {preflightInfo.disclaimers?.map((d, i) => (
                      <p key={i} className="text-amber/90 text-[11px] leading-relaxed">
                        • {d}
                      </p>
                    ))}
                    {preflightInfo.coaching_recommendations?.map((c, i) => (
                      <div key={i} className="bg-panel/80 rounded p-2 text-[10px] text-text font-mono border border-border/40">
                        <span className="text-amber font-bold">Coaching Tip: </span>
                        {c}
                      </div>
                    ))}
                  </div>
                )}

                <div className="space-y-2 font-mono text-[11px] bg-panel p-3 rounded-lg border border-border/50">
                  <div className="flex justify-between">
                    <span className="text-muted">Order Details:</span>
                    <span className={`font-bold ${action === 'BUY' ? 'text-green' : 'text-red'}`}>
                      {action} {qty} × {symbol} ({exchange})
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Total Trade Value:</span>
                    <span className="text-text font-bold">₹{orderValue.toLocaleString('en-IN')}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Stop Loss & Max Risk:</span>
                    <span className="text-red font-semibold">₹{stopLoss} (-₹{riskAmount.toFixed(0)})</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Target Objective:</span>
                    <span className="text-green font-semibold">₹{target} (+₹{rewardAmount.toFixed(0)})</span>
                  </div>
                  <div className="flex justify-between pt-1 border-t border-border/30">
                    <span className="text-muted">Default Broker Role:</span>
                    <span className="text-blue font-bold">DATA FEED ONLY (Simulated Paper Execution)</span>
                  </div>
                </div>

                <label className="flex items-start gap-2.5 pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={confirmedRisk}
                    onChange={(e) => setConfirmedRisk(e.target.checked)}
                    className="mt-0.5 accent-amber rounded"
                  />
                  <span className="text-muted text-[11px] font-ui leading-tight">
                    {preflightInfo?.flags?.length > 0
                      ? 'I acknowledge the behavioral risk advisory and choose to proceed with conscious awareness.'
                      : 'I confirm that I have reviewed the order parameters, stop loss, and position sizing.'}
                  </span>
                </label>
              </div>

              {/* Status Message */}
              {statusMsg && (
                <div
                  className={`p-2.5 rounded-lg text-xs font-ui ${
                    statusMsg.type === 'success'
                      ? 'bg-green/10 text-green border border-green/30'
                      : 'bg-red/10 text-red border border-red/30'
                  }`}
                >
                  {statusMsg.text}
                </div>
              )}

              {/* Step 2 Action Buttons */}
              <div className="flex items-center justify-between pt-2 border-t border-border/40">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="px-4 py-2 rounded-lg bg-panel hover:bg-elevated text-muted hover:text-text font-ui transition-colors text-xs cursor-pointer"
                >
                  &larr; Back to Edit
                </button>
                <button
                  type="button"
                  disabled={isSubmitting || !confirmedRisk}
                  onClick={handlePlaceOrder}
                  className={`px-5 py-2 rounded-lg font-bold font-ui text-xs transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-40 ${
                    action === 'BUY' ? 'bg-green hover:bg-green/90 text-black' : 'bg-red hover:bg-red/90 text-white'
                  }`}
                >
                  {isSubmitting
                    ? 'Transmitting Order…'
                    : preflightInfo?.flags?.length > 0
                    ? `⚡ Acknowledge & Execute ${action}`
                    : `Double Confirm & Transmit ${action}`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
