/**
 * GlobalMacroCard — P0-A Truthful Data Envelope
 *
 * CHANGES (P0-A):
 *  - Removed "LIVE_GLOBAL_FEED" default data_source label
 *  - Removed "Verified High-Correlation Transmission" claim
 *  - Removed "0 Static Fallbacks" claim (was incorrect)
 *  - Removed hardcoded "~0.96 Corr" badge
 *  - Renamed "GIFT NIFTY Implied Open" → "Modelled Overnight Sentiment"
 *    (actual GIFT Nifty data is not fetched; this is a weighted proxy model)
 *  - Added ProxyDisclosure for yfinance-derived items
 *  - Added DataStateBadge showing real source/freshness
 *  - All correlation claims now labeled as approximate model estimates
 */
import { useChatStore } from '../../store/chatStore'
import DataStateBadge from '../Common/DataStateBadge'
import ProxyDisclosure from '../Common/ProxyDisclosure'
import UnavailableState from '../Common/UnavailableState'

export default function GlobalMacroCard({ data }) {
  const sendDraft = useChatStore((s) => s.sendDraft)
  if (!data) return null

  const {
    composite_score = 0,
    global_posture = 'NEUTRAL',
    posture_title = 'Balanced Global Baseline',
    summary = '',
    // P0-A: renamed — this is a weighted proxy model, NOT actual GIFT NIFTY data
    implied_nifty_gap_pct,
    implied_nifty_gap_pts,
    items = {},
    sector_impacts = [],
    as_of = '',
    // P0-A: data_source default removed — we show the real status from the envelope
    data_source,
    _status,
    _source_name,
    _as_of,
    // Proxy metadata from backend DataEnvelope
    _proxy_info,
  } = data

  const dataStatus = _status ?? (data_source === 'LIVE_GLOBAL_FEED' ? 'derived_proxy' : 'unavailable')
  const sourceName = _source_name ?? (data_source === 'LIVE_GLOBAL_FEED' ? 'yfinance (multi-source proxy)' : data_source ?? 'Unknown source')
  const asOfDisplay = _as_of ?? as_of

  const isRiskOn = global_posture === 'RISK_ON'
  const isRiskOff = global_posture === 'RISK_OFF'
  const isVolatile = global_posture === 'VOLATILE_CAUTION'

  const postureBg = isRiskOn
    ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-400'
    : isRiskOff
    ? 'bg-rose-500/15 border-rose-500/40 text-rose-400'
    : isVolatile
    ? 'bg-amber-500/15 border-amber-500/40 text-amber'
    : 'bg-cyan-500/15 border-cyan-500/40 text-cyan-400'

  const hasGap = implied_nifty_gap_pct != null
  const gapColor = hasGap
    ? (implied_nifty_gap_pct > 0.15 ? 'text-emerald-400' : implied_nifty_gap_pct < -0.15 ? 'text-rose-400' : 'text-text')
    : 'text-muted'

  const rawItems = Object.values(items || {})
  // Detect items that are yfinance proxies (from backend metadata or data_status field)
  const hasProxyItems = rawItems.some((it) => it.data_status === 'derived_proxy' || it.is_proxy === true)

  return (
    <div className="bg-elevated border border-border/80 rounded-2xl p-4 sm:p-5 max-w-4xl w-full space-y-4 shadow-xl">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-2xl">🌍</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-extrabold text-sm text-text font-mono uppercase tracking-wider">
                Global Macro &amp; Indian Correlation Model
              </h3>
              {/* P0-A: Show real data status badge instead of fabricated "LIVE_GLOBAL_FEED" */}
              <DataStateBadge
                status={dataStatus}
                sourceName={sourceName}
                asOf={asOfDisplay || undefined}
                compact
              />
            </div>
            <p className="text-[11px] text-muted font-ui">
              Modelled cross-asset correlations into NSE/BSE. Proxies disclosed below.
            </p>
          </div>
        </div>

        <div className={`px-3 py-1 rounded-xl border text-xs font-mono font-black flex items-center gap-1.5 shadow-xs ${postureBg}`}>
          <span className="w-2 h-2 rounded-full bg-current" />
          <span>{posture_title}</span>
          <span className="text-[10px] opacity-80">({composite_score > 0 ? `+${composite_score}` : composite_score})</span>
        </div>
      </div>

      {/* P0-A: Proxy disclosure banner if any items are yfinance-derived */}
      {hasProxyItems && (
        <ProxyDisclosure
          sourceVenue="COMEX / NYMEX / Yahoo Finance"
          targetInstrument="MCX / NSE"
          conversionFormula="× USD/INR × lot-unit multiplier"
          fxPair={_proxy_info?.fx_pair}
          fxRate={_proxy_info?.fx_rate}
          fxAsOf={_proxy_info?.fx_as_of}
          variant="banner"
        />
      )}

      {/* Top Highlight: Modelled Opening Gap & Executive Synthesis */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-3.5">
        {/* Gap Predictor Box — P0-A: renamed from "GIFT NIFTY Implied Open" */}
        <div className="md:col-span-4 bg-panel/70 border border-border/70 rounded-xl p-3.5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono font-bold uppercase text-muted tracking-wider">
                🇮🇳 Modelled Overnight Sentiment
              </span>
              {/* P0-A: Removed hardcoded "~0.96 Corr" — this was an approximate model estimate */}
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface text-violet-400 border border-violet-500/30 font-bold">
                MODEL
              </span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              {hasGap ? (
                <>
                  <span className={`text-2xl font-black font-mono ${gapColor}`}>
                    {implied_nifty_gap_pct > 0 ? `+${implied_nifty_gap_pct.toFixed(2)}%` : `${implied_nifty_gap_pct.toFixed(2)}%`}
                  </span>
                  {implied_nifty_gap_pts != null && (
                    <span className="text-xs font-mono text-muted">
                      ({implied_nifty_gap_pts > 0 ? `+${implied_nifty_gap_pts.toFixed(1)}` : `${implied_nifty_gap_pts.toFixed(1)}`} pts est.)
                    </span>
                  )}
                </>
              ) : (
                <UnavailableState title="Gap estimate unavailable" size="sm" />
              )}
            </div>
          </div>

          {hasGap && (
            <div className="mt-3 pt-2.5 border-t border-border/40 text-[10px] font-ui text-muted leading-relaxed">
              {implied_nifty_gap_pct >= 0.65 ? (
                <span className="text-amber font-semibold">⚠️ Strong Gap-Up model: Stalk opening exhaustion &amp; mean-reversion. Confirm with actual GIFT NIFTY quote.</span>
              ) : implied_nifty_gap_pct <= -0.65 ? (
                <span className="text-rose-400 font-semibold">⚠️ Strong Gap-Down model: Watch for institutional liquidity sweeps. Confirm with actual GIFT NIFTY quote.</span>
              ) : (
                <span>Balanced Opening (modelled): Expect sector-specific rotation. Verify with live quote before acting.</span>
              )}
            </div>
          )}

          {/* P0-A: Explicit model disclosure */}
          <div className="mt-2 text-[9px] text-muted/60 font-mono leading-relaxed">
            ⚠ Not actual GIFT NIFTY data. Weighted proxy model using US futures.
            Do not use for order placement without verifying the live GIFT NIFTY quote.
          </div>
        </div>

        {/* Global Executive Synthesis */}
        <div className="md:col-span-8 bg-surface/50 border border-border/60 rounded-xl p-3.5 flex flex-col justify-between">
          <div>
            <span className="text-[10px] font-mono font-bold uppercase text-muted tracking-wider block mb-1">
              Macro Model Synthesis
            </span>
            <p className="text-xs text-text/90 font-ui leading-relaxed">
              {summary || 'No synthesis available. Run the global macro analysis in Copilot to generate a current summary.'}
            </p>
          </div>

          <div className="mt-3 flex items-center justify-between text-[10px] text-muted font-mono pt-2 border-t border-border/30">
            <span>As of: {asOfDisplay || '—'}</span>
            {/* P0-A: Removed "Verified High-Correlation Transmission" — correlation is approximate and model-derived */}
            <DataStateBadge status={dataStatus} sourceName={sourceName} compact />
          </div>
        </div>
      </div>

      {/* High-Correlation Live Ticker Matrix */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted">
            The Global 6 — Cross-Asset Monitor
          </span>
          {/* P0-A: Removed "0 Static Fallbacks" claim — was incorrect */}
          <span className="text-[10px] text-muted font-mono">
            {hasProxyItems ? 'yfinance proxy data' : 'Source: ' + (sourceName ?? 'unknown')}
          </span>
        </div>

        {rawItems.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
            {rawItems.slice(0, 6).map((it) => {
              const isPos = it.change_pct > 0
              const biasColor = it.impact_bias === 'BULLISH'
                ? 'text-emerald-400'
                : it.impact_bias === 'BEARISH'
                ? 'text-rose-400'
                : 'text-text'
              const isProxy = it.data_status === 'derived_proxy' || it.is_proxy === true

              return (
                <div
                  key={it.key ?? it.name}
                  className="bg-panel rounded-xl p-2.5 border border-border/70 hover:border-amber/40 transition-all flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between text-[9px] font-mono text-muted gap-1">
                      <span className="truncate font-bold">{it.name}</span>
                      {isProxy && (
                        <span
                          className="flex-shrink-0 px-1 rounded text-[8px] font-bold bg-violet-500/15 border border-violet-500/25 text-violet-400"
                          title="Research proxy — not your tradable exchange price"
                        >
                          P
                        </span>
                      )}
                    </div>
                    <p className="text-xs font-mono font-black text-text mt-1">
                      {Number(it.ltp).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                      <span className="text-[9px] font-normal text-muted ml-0.5">{it.unit}</span>
                    </p>
                  </div>

                  <div className="mt-2 pt-1.5 border-t border-border/40 flex items-center justify-between text-[10px] font-mono">
                    <span className={isPos ? 'text-emerald-400' : 'text-rose-400'}>
                      {isPos ? '+' : ''}{Number(it.change_pct).toFixed(2)}%
                    </span>
                    <span className={`text-[9px] font-bold ${biasColor}`}>
                      {it.impact_bias}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <UnavailableState
            title="Global ticker data unavailable"
            reason="No ticker items returned from provider"
            size="sm"
          />
        )}
      </div>

      {/* Sector Impact Attribution Matrix */}
      {sector_impacts.length > 0 && (
        <div className="space-y-2">
          <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted block">
            Sector-Specific Transmission &amp; Attribution
          </span>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
            {sector_impacts.map((sec) => {
              const isTailwind = sec.bias === 'BULLISH_TAILWIND'
              const isHeadwind = sec.bias === 'BEARISH_HEADWIND'
              const tagStyle = isTailwind
                ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                : isHeadwind
                ? 'bg-rose-500/15 border-rose-500/30 text-rose-400'
                : 'bg-surface border-border text-muted'

              return (
                <div
                  key={sec.sector_id}
                  className="bg-panel/50 border border-border/60 rounded-xl p-3 space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-xs font-mono text-text">
                      {sec.sector_name}
                    </span>
                    <span className={`text-[9px] font-mono font-black px-2 py-0.5 rounded-full border ${tagStyle}`}>
                      {isTailwind ? '🚀 TAILWIND' : isHeadwind ? '⚠️ HEADWIND' : '⚖️ NEUTRAL'}
                    </span>
                  </div>

                  <p className="text-[11px] font-ui text-text/80 leading-relaxed">
                    {sec.rationale}
                  </p>

                  {sec.affected_symbols && sec.affected_symbols.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 pt-1">
                      <span className="text-[9px] text-muted font-mono">Impacted:</span>
                      {sec.affected_symbols.slice(0, 5).map((sym) => (
                        <button
                          key={sym}
                          onClick={() => sendDraft(`analyze ${sym}`)}
                          className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-surface hover:bg-amber/20 hover:text-amber border border-border/60 text-muted transition-all cursor-pointer"
                        >
                          {sym}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Action Suite */}
      <div className="pt-2 border-t border-border/60 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => sendDraft('council macro_regime NIFTY')}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-elevated border border-border text-text font-bold text-xs flex items-center gap-1.5 cursor-pointer transition-all"
          >
            <span>🏛️ Macro Regime Council</span>
          </button>
          <button
            onClick={() => sendDraft('persona soros NIFTY')}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-elevated border border-border text-text font-bold text-xs flex items-center gap-1.5 cursor-pointer transition-all"
          >
            <span>🧠 Soros Reflexivity Model</span>
          </button>
          <button
            onClick={() => sendDraft('funnel sector auto_market_aware')}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-elevated border border-border text-text font-bold text-xs flex items-center gap-1.5 cursor-pointer transition-all"
          >
            <span>🎯 Leading Sectors Funnel</span>
          </button>
        </div>

        <span className="text-[10px] font-mono text-muted">
          All values are research proxies unless source states otherwise
        </span>
      </div>
    </div>
  )
}
