import React, { useState, useEffect } from 'react'
import { convictionEmoji } from './alertHelpers'

export function TelegramPreflightModal({ alert, onConfirm, onCancel, sending, sentOk, sentError, callRef }) {
  const [destMode, setDestMode] = useState('DEFAULT')
  const [customChannel, setCustomChannel] = useState(() => {
    try {
      return localStorage.getItem('chanakya_telegram_channel') || ''
    } catch (_) {
      return ''
    }
  })
  const [destInfo, setDestInfo] = useState(null)

  useEffect(() => {
    if (!alert) return
    let active = true
    const fetchDest = async () => {
      try {
        if (callRef?.current) {
          const res = await callRef.current('/api/alerts/auto/telegram-destinations')
          if (active && res?.data) {
            setDestInfo(res.data)
            const cleanSym = (alert?.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim().toUpperCase()
            const isIndexSym = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX'].includes(cleanSym)
            const isFnoIndex = Boolean(
              (alert?.segment || '').toUpperCase() === 'FNO_INDEX' ||
              (isIndexSym && (alert?.option_type || ['GAMMA_BLAST', 'OPTIONS_MOMENTUM'].includes(alert?.alert_type) || ['FNO', 'NFO'].includes((alert?.exchange || '').toUpperCase())))
            )
            const isFnoStock = Boolean(
              !isFnoIndex && (
                alert?.option_type ||
                ['FNO_INDEX', 'FNO_STOCK', 'FNO'].includes((alert?.segment || '').toUpperCase()) ||
                ['GAMMA_BLAST', 'OPTIONS_MOMENTUM'].includes(alert?.alert_type)
              )
            )
            const isMcx = Boolean(
              (alert?.exchange || '').toUpperCase() === 'MCX' ||
              (alert?.exchange || '').toUpperCase() === 'CDS' ||
              ['COMMODITY', 'CURRENCY', 'MCX', 'CDS'].includes((alert?.segment || '').toUpperCase()) ||
              ['COMMODITY_MOMENTUM', 'CURRENCY_BREAKOUT'].includes(alert?.alert_type) ||
              (alert?.symbol || '').toUpperCase().startsWith('MCX:') ||
              (alert?.symbol || '').toUpperCase().startsWith('CDS:')
            )
            if (res.data.fno_index_chat_id && isFnoIndex) {
              setDestMode('FNO_INDEX_GROUP')
            } else if (res.data.fno_chat_id && isFnoStock) {
              setDestMode('FNO_GROUP')
            } else if (res.data.mcx_chat_id && isMcx) {
              setDestMode('MCX_GROUP')
            } else if (res.data.equity_chat_id) {
              setDestMode('EQUITY_GROUP')
            }
            if (res.data.channel_id && !customChannel) {
              setCustomChannel(res.data.channel_id)
            }
          }
        }
      } catch (_) {}
    }
    fetchDest()
    return () => { active = false }
  }, [callRef, alert])

  if (!alert) return null

  const scrutiny = alert.metrics?.scrutiny || null
  const conviction = Number(alert.confidence || scrutiny?.score || 75)
  const convBars = Math.round(conviction / 10)
  const optType = alert.option_type || null
  const strikeNum = alert.strike ? Number(alert.strike) : null
  const cleanSym = (alert.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS):/, '').trim()
  const contractLabel = alert.contract_symbol || [cleanSym, strikeNum ? Number(strikeNum).toLocaleString('en-IN') : '', optType || ''].filter(Boolean).join(' ')

  const scrutinyStatus = scrutiny?.status || 'QUANT_VERIFIED'
  const statusColor = scrutinyStatus === 'APPROVED' ? 'text-emerald-400' : scrutinyStatus === 'QUANT_VERIFIED' ? 'text-sky-400' : 'text-amber-400'
  const statusBg = scrutinyStatus === 'APPROVED' ? 'bg-emerald-500/15 border-emerald-500/30' : scrutinyStatus === 'QUANT_VERIFIED' ? 'bg-sky-500/15 border-sky-500/30' : 'bg-amber-500/15 border-amber-500/30'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel() }}
    >
      <div className="w-full max-w-md rounded-2xl border border-sky-500/30 bg-elevated shadow-2xl space-y-3 p-4 animate-slide-up-fade">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📨</span>
            <div>
              <div className="text-sm font-black text-text">Send to Telegram</div>
              <div className="text-[10px] text-muted font-mono">{contractLabel}</div>
            </div>
          </div>
          <button onClick={onCancel} className="text-muted hover:text-text text-sm font-bold w-6 h-6 flex items-center justify-center">✕</button>
        </div>

        {/* Scrutiny Status badge */}
        <div className={`flex items-center gap-2 p-2 rounded-lg border ${statusBg}`}>
          <span className={`text-[10px] font-black uppercase tracking-wider ${statusColor}`}>
            {scrutinyStatus === 'APPROVED' ? '🛡️ AI APPROVED' : scrutinyStatus === 'QUANT_VERIFIED' ? '⚡ QUANT VERIFIED' : `⚠️ ${scrutinyStatus}`}
          </span>
          {scrutiny?.auditor_model && (
            <span className="text-[8px] font-mono text-muted ml-auto">{scrutiny.auditor_model}</span>
          )}
        </div>

        {/* Conviction bar */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-muted font-bold uppercase tracking-wider">Conviction</span>
            <span className="font-black font-mono text-gold">{convictionEmoji(conviction)} {conviction}/100</span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-surface overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-amber-500 to-emerald-500 transition-all duration-300"
              style={{ width: `${conviction}%` }}
            />
          </div>
          <div className="text-[8px] font-mono text-muted text-right">{'█'.repeat(convBars)}{'░'.repeat(10 - convBars)}</div>
        </div>

        {/* Scrutiny dossier */}
        {scrutiny?.logic_confirmation && (
          <div className="p-2 rounded-lg bg-emerald-500/8 border border-emerald-500/25 space-y-0.5">
            <div className="text-[9px] font-black uppercase tracking-wider text-emerald-400">✅ Logic Confirmation</div>
            <p className="text-[10px] text-zinc-300 leading-relaxed">{scrutiny.logic_confirmation}</p>
          </div>
        )}
        {scrutiny?.trap_risk_warning && (
          <div className="p-2 rounded-lg bg-amber-500/8 border border-amber-500/25 space-y-0.5">
            <div className="text-[9px] font-black uppercase tracking-wider text-amber-400">⚠️ Trap Risk Warning</div>
            <p className="text-[10px] text-zinc-300 leading-relaxed">{scrutiny.trap_risk_warning}</p>
          </div>
        )}
        {scrutiny?.actionable_guidance && (
          <div className="p-2 rounded-lg bg-sky-500/8 border border-sky-500/25 space-y-0.5">
            <div className="text-[9px] font-black uppercase tracking-wider text-sky-400">🎯 Execution Guidance</div>
            <p className="text-[10px] text-zinc-300 leading-relaxed">{scrutiny.actionable_guidance}</p>
          </div>
        )}
        {!scrutiny && (
          <div className="p-2 rounded-lg bg-surface border border-border text-[10px] text-zinc-500 text-center">
            No scrutiny data. Run Re-Scrutinize first for full AI analysis.
          </div>
        )}

        {/* Destination Target Selector */}
        <div className="p-2.5 rounded-xl bg-surface border border-border space-y-1.5">
          <div className="flex items-center justify-between text-[10px]">
            <span className="font-bold text-muted uppercase tracking-wider">Destination Target</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setDestMode('DEFAULT')}
                className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                  destMode === 'DEFAULT'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                    : 'text-muted hover:text-text'
                }`}
              >
                🔒 Default Chat
              </button>
              {destInfo?.fno_index_chat_id && (
                <button
                  type="button"
                  onClick={() => setDestMode('FNO_INDEX_GROUP')}
                  className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                    destMode === 'FNO_INDEX_GROUP'
                      ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                      : 'text-muted hover:text-text'
                  }`}
                >
                  ⚡ {destInfo.fno_index_chat_name || 'Premium FnO Index'}
                </button>
              )}
              {destInfo?.fno_chat_id && (
                <button
                  type="button"
                  onClick={() => setDestMode('FNO_GROUP')}
                  className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                    destMode === 'FNO_GROUP'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'text-muted hover:text-text'
                  }`}
                >
                  🎯 {destInfo.fno_chat_name || 'Premium FnO Channel'}
                </button>
              )}
              {destInfo?.mcx_chat_id && (
                <button
                  type="button"
                  onClick={() => setDestMode('MCX_GROUP')}
                  className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                    destMode === 'MCX_GROUP'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : 'text-muted hover:text-text'
                  }`}
                >
                  🪙 {destInfo.mcx_chat_name || 'Premium MCX Channel'}
                </button>
              )}
              {destInfo?.equity_chat_id && (
                <button
                  type="button"
                  onClick={() => setDestMode('EQUITY_GROUP')}
                  className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                    destMode === 'EQUITY_GROUP'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'text-muted hover:text-text'
                  }`}
                >
                  🏢 {destInfo.equity_chat_name || 'Premium Equity Channel'}
                </button>
              )}
              <button
                type="button"
                onClick={() => setDestMode('CHANNEL')}
                className={`text-[9px] px-2 py-0.5 rounded font-bold transition-all ${
                  destMode === 'CHANNEL'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                    : 'text-muted hover:text-text'
                }`}
              >
                📢 Channel
              </button>
            </div>
          </div>

          {destMode === 'DEFAULT' ? (
            <div className="text-[9px] text-zinc-400 font-mono flex items-center justify-between px-1">
              <span>Target: <span className="text-text font-bold">
                {destInfo?.default_chat_id ? `Private Chat (${destInfo.default_chat_id.slice(0, 4)}***)` : 'Configured Telegram Chat'}
              </span></span>
              {destInfo && !destInfo.is_configured ? (
                <span className="text-amber-400 font-bold">⚠️ Unconfigured</span>
              ) : (
                <span className="text-emerald-400 font-bold">● Active</span>
              )}
            </div>
          ) : destMode === 'FNO_INDEX_GROUP' ? (
            <div className="text-[9px] text-zinc-400 font-mono flex items-center justify-between px-1">
              <span>Target: <span className="text-sky-400 font-bold">
                ⚡ {destInfo?.fno_index_chat_name || 'Premium_Alpha_Vortex_FnO_Index'} ({destInfo?.fno_index_chat_id})
              </span></span>
              <span className="text-sky-400 font-bold">● Active</span>
            </div>
          ) : destMode === 'FNO_GROUP' ? (
            <div className="text-[9px] text-zinc-400 font-mono flex items-center justify-between px-1">
              <span>Target: <span className="text-emerald-400 font-bold">
                🎯 {destInfo?.fno_chat_name || 'Premium_Alpha_Vortex_FnO_Channel'} ({destInfo?.fno_chat_id})
              </span></span>
              <span className="text-emerald-400 font-bold">● Active</span>
            </div>
          ) : destMode === 'MCX_GROUP' ? (
            <div className="text-[9px] text-zinc-400 font-mono flex items-center justify-between px-1">
              <span>Target: <span className="text-amber-400 font-bold">
                🪙 {destInfo?.mcx_chat_name || 'Premium_Alpha_Vortex_MCX_Channel'} ({destInfo?.mcx_chat_id})
              </span></span>
              <span className="text-amber-400 font-bold">● Active</span>
            </div>
          ) : destMode === 'EQUITY_GROUP' ? (
            <div className="text-[9px] text-zinc-400 font-mono flex items-center justify-between px-1">
              <span>Target: <span className="text-emerald-400 font-bold">
                🏢 {destInfo?.equity_chat_name || 'Premium_Alpha_Vortex_Equity_Channel'} ({destInfo?.equity_chat_id})
              </span></span>
              <span className="text-emerald-400 font-bold">● Active</span>
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={customChannel}
                  onChange={(e) => {
                    setCustomChannel(e.target.value)
                    localStorage.setItem('chanakya_telegram_channel', e.target.value)
                  }}
                  placeholder="@my_channel_handle or -100xxxxxxxxxx"
                  className="flex-1 text-[10px] font-mono py-1 px-2.5 rounded bg-panel border border-border text-text placeholder-zinc-600 focus:outline-none focus:border-sky-500"
                />
                {destInfo?.channel_id && destInfo.channel_id !== customChannel && (
                  <button
                    type="button"
                    onClick={() => {
                      setCustomChannel(destInfo.channel_id)
                      localStorage.setItem('chanakya_telegram_channel', destInfo.channel_id)
                    }}
                    className="text-[8px] px-1.5 py-1 rounded bg-sky-500/10 text-sky-300 border border-sky-500/25 hover:bg-sky-500/20 whitespace-nowrap"
                    title="Use channel ID configured in environment"
                  >
                    Env Channel
                  </button>
                )}
              </div>
              <div className="text-[8px] text-zinc-500 px-1">
                Enter public channel handle (e.g. <code>@chanakya_alerts</code>) or private channel/group ID (-100...)
              </div>
            </div>
          )}
        </div>

        {/* Alert summary */}
        <div className="text-[10px] text-zinc-500 p-2 rounded-lg bg-surface border border-border">
          <span className="font-bold text-muted">{alert.direction} · {alert.alert_type?.replace(/_/g, ' ')}</span>
          {alert.expiry_date && <span className="ml-1 text-amber-400">· Exp {alert.expiry_date}</span>}
          {(alert.environment === 'TEST' || alert.is_live === false) && (
            <span className="ml-1 text-purple-400 font-black">· TEST ALERT</span>
          )}
        </div>

        {/* Status messages */}
        {sentOk && (
          <div className="p-2 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-[10px] font-bold text-center">
            ✅ Alert dispatched to Telegram!
          </div>
        )}
        {sentError && (
          <div className="p-2 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-[10px] text-center">
            ❌ {sentError}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={onCancel}
            className="flex-1 btn btn-sm btn-ghost text-xs text-muted border border-border/50 hover:border-border"
          >Cancel</button>
          <button
            onClick={() => onConfirm(
              destMode === 'DEFAULT'
                ? null
                : destMode === 'FNO_INDEX_GROUP'
                  ? destInfo?.fno_index_chat_id
                  : destMode === 'FNO_GROUP'
                    ? destInfo?.fno_chat_id
                    : destMode === 'MCX_GROUP'
                      ? destInfo?.mcx_chat_id
                      : destMode === 'EQUITY_GROUP'
                        ? destInfo?.equity_chat_id
                        : customChannel.trim()
            )}
            disabled={sending || sentOk || (destMode === 'CHANNEL' && !customChannel.trim())}
            className="flex-1 btn btn-sm text-xs font-black bg-sky-500/20 hover:bg-sky-500/30 text-sky-200 border border-sky-500/40 hover:border-sky-500/60 disabled:opacity-50 transition-all"
          >
            {sending ? '⏳ Sending…' : sentOk ? '✅ Sent!' : '✓ Confirm & Send'}
          </button>
        </div>
      </div>
    </div>
  )
}
