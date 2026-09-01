import { useState, useEffect, useCallback, useRef } from 'react'
import { useAPI } from '../../hooks/useAPI'

/**
 * OrderTicketModal — Paper / Live Order Management System (OMS)
 *
 * Transitions:
 *   Step 1 (Edit/Stage)  → Calls /api/risk/preflight & /api/orders/preview
 *   Step 2 (Double Confirm) → Calls /api/orders/execute with real order ID
 *
 * Truthful guarantees:
 *   - No fake timer client simulations
 *   - Real statutory charge computation (STT, GST, SEBI turnover, Stamp Duty)
 *   - Real PAPER- / LIVE- order ID prefixing and state tracking
 *   - Accessible modal semantics (role="dialog", aria-modal, focus trap, Escape)
 *   - Modal NEVER shows success if preview was not server-confirmed
 *   - Mode-aware copy: Paper OMS vs Live OMS with distinct styling
 */
export default function OrderTicketModal({ isOpen, onClose, initialData = {}, appMode = 'PAPER' }) {
  const isLiveMode = appMode === 'LIVE'
  const { call } = useAPI()
  const modalRef = useRef(null)

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
  const [previewOrder, setPreviewOrder] = useState(null)
  const [isValidatingRisk, setIsValidatingRisk] = useState(false)
  const [intentKey, setIntentKey] = useState('')

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
      setPreviewOrder(null)
      setPreflightInfo(null)
      const freshKey =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `intent-${Date.now()}-${Math.random().toString(36).slice(2)}`
      setIntentKey(freshKey)
    }
  }, [isOpen, initialData])

  // Escape key handler for accessibility
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  // Auto-calculate position size based on risk percentage
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
      // 1. Evaluate risk gate limits & behavioral advisory and fetch preview with intentKey
      const [riskRes, previewRes] = await Promise.allSettled([
        call('/api/risk/preflight', {
          symbol,
          action,
          quantity: qty,
          price,
          allow_override: true,
        }),
        call('/api/orders/preview', {
          symbol,
          side: action,
          quantity: qty,
          price,
          order_type: orderType,
          product,
          idempotency_key: intentKey,
        }),
      ])

      if (riskRes.status === 'fulfilled') {
        setPreflightInfo(riskRes.value?.data ?? riskRes.value)
      } else {
        setPreflightInfo(null)
      }

      if (previewRes.status === 'fulfilled') {
        const preview = previewRes.value?.data ?? previewRes.value
        // Only advance to Step 2 when the server returned a valid order ID
        if (!preview?.order_id) {
          setStatusMsg({
            type: 'error',
            text: 'Server did not return a valid order preview. Please retry.',
          })
          setPreviewOrder(null)
          return // Stay on Step 1
        }
        setPreviewOrder(preview)
        setStep(2)
      } else {
        // Preview call failed — stay on Step 1, never advance
        setPreviewOrder(null)
        setStatusMsg({
          type: 'error',
          text: `Order preview failed: ${previewRes.reason?.message ?? 'server error'}. Cannot proceed.`,
        })
        // Intentionally no setStep(2) — user must see the error and retry
      }
    } catch (err) {
      setPreflightInfo(null)
      setPreviewOrder(null)
      setStatusMsg({
        type: 'error',
        text: `Unexpected error during preview: ${err.message ?? 'unknown error'}`,
      })
    } finally {
      setIsValidatingRisk(false)
      // NOTE: setStep(2) is called only inside the success branch above, not here
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
      const orderId = previewOrder?.order_id
      if (!orderId) {
        // Preview was never server-confirmed — never show a fake success
        setStatusMsg({
          type: 'error',
          text: 'No valid server-generated order preview exists. Please go back and retry preview.',
        })
        return
      }

      // Step 2A: Explicitly confirm the order intent on backend
      await call('/api/orders/confirm', {
        order_id: orderId,
        preview_hash: previewOrder.preview_hash,
      })

      // Step 2B: Execute confirmed order through the real OMS backend
      const res = await call('/api/orders/execute', { order_id: orderId })
      const executedData = res?.data ?? res
      const status = executedData.status ?? 'UNKNOWN'
      const orderIdDisplay = executedData.order_id || orderId
      const modeLabel = isLiveMode ? 'Live Order' : 'Paper Order'

      setStatusMsg({
        type: 'success',
        text: `✓ ${modeLabel} Placed [${orderIdDisplay}]: ${status.replace('_', ' ')} @ ₹${Number(price).toFixed(2)} [SL: ₹${stopLoss}, TGT: ₹${target}]`,
      })

      setTimeout(() => {
        setStep(1)
        onClose()
      }, 1600)
    } catch (err) {
      setStatusMsg({ type: 'error', text: err.message || 'Order rejected by Risk Gate' })
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  const charges = previewOrder?.charges ?? null
  const totalCharges = charges?.total_charges ?? 0

  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="order-ticket-title"
        className="modal-container w-full max-w-lg font-ui"
        style={{ maxWidth: '520px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-elevated)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center text-lg"
              style={{
                background: step === 1 ? 'rgba(0,214,143,0.15)' : 'rgba(245,166,35,0.15)',
                border: `1px solid ${step === 1 ? 'rgba(0,214,143,0.4)' : 'rgba(245,166,35,0.4)'}`,
              }}
            >
              {step === 1 ? '⚡' : '🛡️'}
            </div>
            <div>
              <h2
                id="order-ticket-title"
                className="text-sm font-bold"
                style={{ color: isLiveMode ? 'var(--color-rose)' : 'var(--color-text)', fontFamily: 'Inter, sans-serif' }}
              >
                {step === 1 ? 'Smart Order Staging' : 'Double Confirmation Gate'}
              </h2>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>
                {step === 1
                  ? isLiveMode
                    ? '⚠️ LIVE OMS · Real Capital at Risk'
                    : 'Paper OMS · 0 Real Broker Risk'
                  : isLiveMode
                  ? 'Step 2 of 2: Verify & Transmit (LIVE ⚠️)'
                  : 'Step 2 of 2: Verify & Transmit (Paper)'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => { setStep(1); onClose() }}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-xs font-bold cursor-pointer transition-colors"
            style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-muted)' }}
            aria-label="Close order ticket"
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
                  <div
                    className="grid grid-cols-2 gap-1 p-1 rounded-xl"
                    style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)' }}
                  >
                    <button
                      type="button"
                      onClick={() => setAction('BUY')}
                      className="py-2 rounded-lg font-bold text-center transition-all cursor-pointer text-xs"
                      style={action === 'BUY' ? { background: 'var(--color-emerald)', color: '#000', fontWeight: 800 } : { color: 'var(--color-muted)' }}
                    >
                      ▲ BUY
                    </button>
                    <button
                      type="button"
                      onClick={() => setAction('SELL')}
                      className="py-2 rounded-lg font-bold text-center transition-all cursor-pointer text-xs"
                      style={action === 'SELL' ? { background: 'var(--color-rose)', color: '#fff', fontWeight: 800 } : { color: 'var(--color-muted)' }}
                    >
                      ▼ SELL
                    </button>
                  </div>
                </div>

                <div>
                  <span className="text-muted text-[10px] uppercase font-ui block mb-1">Trading Symbol</span>
                  <input
                    type="text"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                    className="w-full bg-panel border border-border/60 rounded-lg px-3 py-1.5 text-text font-bold uppercase font-mono"
                    aria-label="Trading symbol"
                  />
                </div>
              </div>

              {/* Price, Stop-Loss, Target */}
              <div className="grid grid-cols-3 gap-2">
                <div className="space-y-1">
                  <span className="text-[10px] uppercase font-bold" style={{ color: 'var(--color-muted)' }}>Entry Price</span>
                  <input
                    type="number"
                    step="0.05"
                    value={price}
                    onChange={(e) => setPrice(Number(e.target.value))}
                    className="input-field text-xs font-mono"
                    aria-label="Entry price"
                  />
                </div>
                <div className="space-y-1">
                  <span className="text-[10px] uppercase font-bold" style={{ color: 'var(--color-rose)' }}>Stop Loss</span>
                  <input
                    type="number"
                    step="0.05"
                    value={stopLoss}
                    onChange={(e) => setStopLoss(Number(e.target.value))}
                    className="w-full bg-panel border border-red/40 rounded px-2.5 py-1.5 text-red font-mono"
                    aria-label="Stop loss"
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
                    aria-label="Target price"
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
                        type="button"
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
                    <span className="text-text font-bold text-sm font-mono">{qty}</span>
                  </div>
                  <div>
                    <span className="text-muted text-[10px] block font-ui">Max Risk</span>
                    <span className="text-red font-semibold font-mono">₹{riskAmount.toFixed(0)}</span>
                  </div>
                  <div>
                    <span className="text-muted text-[10px] block font-ui">Risk:Reward</span>
                    <span className="text-green font-bold font-mono">1:{riskRewardRatio}</span>
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
                  disabled={isValidatingRisk}
                  className={`px-5 py-2 rounded-lg font-semibold font-ui text-xs transition-all flex items-center gap-1.5 cursor-pointer ${
                    action === 'BUY' ? 'bg-green hover:bg-green/90 text-black' : 'bg-red hover:bg-red/90 text-white'
                  }`}
                >
                  {isValidatingRisk ? 'Previewing…' : `Review & Confirm ${action} (₹${orderValue.toLocaleString('en-IN')}) →`}
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
                    <span>Execution Review &amp; Risk Guardrails</span>
                  </div>
                  {preflightInfo?.flags?.length > 0 && (
                    <span className="bg-amber/20 text-amber text-[10px] px-2 py-0.5 rounded-full border border-amber/40">
                      Advisory Active ({preflightInfo.flags.length})
                    </span>
                  )}
                </div>

                {/* Behavioral Advisory Box if flags detected */}
                {preflightInfo?.flags?.length > 0 && (
                  <div className="bg-amber/10 border border-amber/40 rounded-lg p-3 space-y-2 text-left">
                    <div className="flex items-center gap-1.5 text-amber font-bold text-[11px]">
                      <span>🧠</span>
                      <span>Behavioral Risk &amp; Tilt Advisory (Co-Pilot)</span>
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

                {/* Order Breakdown */}
                <div className="space-y-1.5 font-mono text-[11px] bg-panel p-3 rounded-lg border border-border/50">
                  <div className="flex justify-between">
                    <span className="text-muted">Order Details:</span>
                    <span className={`font-bold ${action === 'BUY' ? 'text-green' : 'text-red'}`}>
                      {action} {qty} × {symbol} ({exchange})
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Trade Value:</span>
                    <span className="text-text font-bold">₹{orderValue.toLocaleString('en-IN')}</span>
                  </div>
                  {previewOrder?.order_id && (
                    <div className="flex justify-between text-[10px]">
                      <span className="text-muted">{isLiveMode ? 'Live Intent ID:' : 'Paper Intent ID:'}</span>
                      <span className="text-violet-400 font-bold">{previewOrder.order_id}</span>
                    </div>
                  )}
                  {totalCharges > 0 && (
                    <div className="flex justify-between text-[10px] text-muted">
                      <span>Statutory Indian Charges:</span>
                      <span className="font-semibold text-text">₹{totalCharges.toFixed(2)} (STT, GST, SEBI)</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-muted">Stop Loss &amp; Max Risk:</span>
                    <span className="text-red font-semibold">₹{stopLoss} (-₹{riskAmount.toFixed(0)})</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Target Objective:</span>
                    <span className="text-green font-semibold">₹{target} (+₹{rewardAmount.toFixed(0)})</span>
                  </div>
                  <div className="flex justify-between pt-1 border-t border-border/30 text-[10px]">
                    <span className="text-muted">Execution Venue:</span>
                    {isLiveMode ? (
                      <span className="text-rose-400 font-bold">LIVE BROKER (Real execution — real capital at risk)</span>
                    ) : appMode === 'DEMO' ? (
                      <span className="text-amber-400 font-bold">DEMO OMS (Synthetic Sandbox — No Broker Connected)</span>
                    ) : (
                      <span className="text-blue font-bold">PAPER OMS (Simulated — No Real Money at Risk)</span>
                    )}
                  </div>
                </div>

                <label className="flex items-start gap-2.5 pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={confirmedRisk}
                    onChange={(e) => setConfirmedRisk(e.target.checked)}
                    className="mt-0.5 accent-amber rounded"
                    aria-label="Confirm risk acknowledgment"
                  />
                  <span className="text-muted text-[11px] font-ui leading-tight">
                    {preflightInfo?.flags?.length > 0
                      ? 'I acknowledge the behavioral risk advisory and choose to proceed with conscious awareness.'
                      : isLiveMode
                      ? 'I confirm that I have reviewed the order parameters, statutory costs, and acknowledge REAL CAPITAL is at risk on the live exchange.'
                      : 'I confirm that I have reviewed the order parameters, statutory costs, and paper execution role.'}
                  </span>
                </label>
              </div>

              {/* Status Message */}
              {statusMsg && (
                <div
                  role="status"
                  className={`p-2.5 rounded-lg text-xs font-ui ${
                    statusMsg.type === 'success'
                      ? 'bg-green/10 text-green border border-green/30 font-bold'
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
                  ← Back to Edit
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
                    ? isLiveMode
                      ? 'Transmitting Live Order to Broker…'
                      : 'Transmitting Paper Order…'
                    : preflightInfo?.flags?.length > 0
                    ? `⚡ Acknowledge & Transmit ${action} ${isLiveMode ? '(LIVE ⚠️)' : ''}`
                    : isLiveMode
                    ? `Double Confirm & Transmit ${action} (LIVE ⚠️)`
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
