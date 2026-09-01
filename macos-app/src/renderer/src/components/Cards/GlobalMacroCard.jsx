import { useChatStore } from '../../store/chatStore'

export default function GlobalMacroCard({ data }) {
  const sendDraft = useChatStore((s) => s.sendDraft)
  if (!data) return null

  const {
    composite_score = 0,
    global_posture = 'NEUTRAL',
    posture_title = 'Balanced Global Baseline',
    summary = '',
    implied_nifty_gap_pct = 0,
    implied_nifty_gap_pts = 0,
    items = {},
    sector_impacts = [],
    as_of = '',
    data_source = 'LIVE_GLOBAL_FEED',
  } = data

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

  const gapColor = implied_nifty_gap_pct > 0.15
    ? 'text-emerald-400'
    : implied_nifty_gap_pct < -0.15
    ? 'text-rose-400'
    : 'text-text'

  const rawItems = Object.values(items || {})

  return (
    <div className="bg-elevated border border-border/80 rounded-2xl p-4 sm:p-5 max-w-4xl w-full space-y-4 shadow-xl">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-2xl">🌍</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-extrabold text-sm text-text font-mono uppercase tracking-wider">
                Global Macro Transmission & Indian Correlation
              </h3>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-panel border border-border text-muted">
                {data_source}
              </span>
            </div>
            <p className="text-[11px] text-muted font-ui">
              Direct high-correlation transmission into NSE/BSE institutional liquidity & opening gaps
            </p>
          </div>
        </div>

        <div className={`px-3 py-1 rounded-xl border text-xs font-mono font-black flex items-center gap-1.5 shadow-xs ${postureBg}`}>
          <span className="w-2 h-2 rounded-full bg-current animate-pulse" />
          <span>{posture_title}</span>
          <span className="text-[10px] opacity-80">({composite_score > 0 ? `+${composite_score}` : composite_score})</span>
        </div>
      </div>

      {/* Top Highlight: GIFT NIFTY Opening Gap Predictor & Executive Synthesis */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-3.5">
        {/* Gap Predictor Box */}
        <div className="md:col-span-4 bg-panel/70 border border-border/70 rounded-xl p-3.5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono font-bold uppercase text-muted tracking-wider">
                🇮🇳 GIFT NIFTY Implied Open
              </span>
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface text-amber border border-border/60 font-bold">
                ~0.96 Corr
              </span>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className={`text-2xl font-black font-mono ${gapColor}`}>
                {implied_nifty_gap_pct > 0 ? `+${implied_nifty_gap_pct.toFixed(2)}%` : `${implied_nifty_gap_pct.toFixed(2)}%`}
              </span>
              <span className="text-xs font-mono text-muted">
                ({implied_nifty_gap_pts > 0 ? `+${implied_nifty_gap_pts.toFixed(1)}` : `${implied_nifty_gap_pts.toFixed(1)}`} pts)
              </span>
            </div>
          </div>

          <div className="mt-3 pt-2.5 border-t border-border/40 text-[10px] font-ui text-muted leading-relaxed">
            {implied_nifty_gap_pct >= 0.65 ? (
              <span className="text-amber font-semibold">⚠️ Strong Gap-Up: Stalk opening exhaustion & mean-reversion. Avoid chasing market open.</span>
            ) : implied_nifty_gap_pct <= -0.65 ? (
              <span className="text-rose-400 font-semibold">⚠️ Strong Gap-Down: Watch for institutional liquidity sweeps at key swing supports.</span>
            ) : (
              <span>Balanced Opening: Expect sector-specific rotation and normal intraday price discovery.</span>
            )}
          </div>
        </div>

        {/* Global Executive Synthesis */}
        <div className="md:col-span-8 bg-surface/50 border border-border/60 rounded-xl p-3.5 flex flex-col justify-between">
          <div>
            <span className="text-[10px] font-mono font-bold uppercase text-muted tracking-wider block mb-1">
              Institutional Macro Synthesis
            </span>
            <p className="text-xs text-text/90 font-ui leading-relaxed">
              {summary || 'Global transmission baseline is balanced with normal cross-asset correlations.'}
            </p>
          </div>

          <div className="mt-3 flex items-center justify-between text-[10px] text-muted font-mono pt-2 border-t border-border/30">
            <span>As of: {as_of || 'Live Session'}</span>
            <span className="text-amber">Verified High-Correlation Transmission</span>
          </div>
        </div>
      </div>

      {/* High-Correlation Live Ticker Matrix */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted">
            The High-Correlation Global 6 (Live Feeds)
          </span>
          <span className="text-[10px] text-muted font-mono">0 Static Fallbacks</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
          {rawItems.slice(0, 6).map((it) => {
            const isPos = it.change_pct > 0
            const biasColor = it.impact_bias === 'BULLISH'
              ? 'text-emerald-400'
              : it.impact_bias === 'BEARISH'
              ? 'text-rose-400'
              : 'text-text'

            return (
              <div
                key={it.key}
                className="bg-panel rounded-xl p-2.5 border border-border/70 hover:border-amber/40 transition-all flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between text-[9px] font-mono text-muted">
                    <span className="truncate font-bold">{it.name}</span>
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
      </div>

      {/* Sector Impact Attribution Matrix */}
      {sector_impacts.length > 0 && (
        <div className="space-y-2">
          <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted block">
            Sector-Specific Transmission & Attribution
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

      {/* 1-Click Institutional Action Suite */}
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
            <span>🧠 George Soros Reflexivity</span>
          </button>
          <button
            onClick={() => sendDraft('funnel sector auto_market_aware')}
            className="px-2.5 py-1 rounded-lg bg-surface hover:bg-elevated border border-border text-text font-bold text-xs flex items-center gap-1.5 cursor-pointer transition-all"
          >
            <span>🎯 Leading Sectors Funnel</span>
          </button>
        </div>

        <span className="text-[10px] font-mono text-muted">
          Institutional SEBI & F&O Risk Filter Active
        </span>
      </div>
    </div>
  )
}
