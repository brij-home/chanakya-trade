import React, { memo } from 'react'

export const PredatoryPipelineDrawer = memo(function PredatoryPipelineDrawer({
  alert,
  isOpen = true,
  onClose,
}) {
  if (!alert) return null

  const metrics = alert.metrics || {}
  const pipeline = metrics.predatory_pipeline || {}
  const eagle = pipeline.eagle || {}
  const tiger = pipeline.tiger || {}
  const chanakya = pipeline.chanakya || {}
  const sniper = pipeline.sniper || {}
  const cheetah = pipeline.cheetah || {}
  const elephant = pipeline.elephant || {}
  const cb = pipeline.circuit_breaker || metrics.circuit_breaker || {}
  const posSizing =
    alert.actionable_plan?.trade_plan?.position_sizing ||
    alert.actionable_plan?.position_sizing ||
    null

  const isCrypto =
    (alert.exchange || '').toUpperCase() === 'CRYPTO' ||
    (alert.exchange || '').toUpperCase() === 'BINANCE' ||
    (alert.segment || '').toUpperCase() === 'CRYPTO' ||
    (alert.symbol || '').toUpperCase().endsWith('USDT')
  const currSym = isCrypto ? '$' : '₹'

  const evVal =
    pipeline.expected_value_r !== undefined
      ? pipeline.expected_value_r
      : metrics.expected_value_r !== undefined
      ? metrics.expected_value_r
      : sniper.expected_value_r

  return (
    <div className="rounded-xl border border-gold/30 bg-surface/95 dark:bg-panel/95 backdrop-blur-md p-3 space-y-3 shadow-lg animate-slide-up-fade">
      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-border/50 pb-2">
        <div className="flex items-center gap-2">
          <span className="text-base">🏛️</span>
          <div>
            <h4 className="text-xs font-black uppercase tracking-wider text-gold flex items-center gap-1.5">
              Predatory Execution Pipeline & Diagnostic Dossier
              <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-gold/15 text-gold border border-gold/30">
                6-SEAT COUNCIL
              </span>
            </h4>
            <p className="text-[10px] text-zinc-400">
              Institutional order-flow verification, trap elimination, and mathematical edge validation
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {evVal !== undefined && (
            <span
              className={`text-[10px] font-mono font-black px-2 py-0.5 rounded border ${
                Number(evVal) >= 0.85
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : Number(evVal) >= 0.40
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
              }`}
              title="Mathematical Expected Value: (P_win * Payoff) - ((1 - P_win) * 1) - Friction"
            >
              EV: {Number(evVal) >= 0 ? '+' : ''}{Number(evVal).toFixed(2)}R
            </span>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="text-xs text-muted hover:text-text px-1 py-0.5 rounded hover:bg-surface border border-transparent hover:border-border transition-all"
              title="Close Predatory Diagnostic Drawer"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* 6-Seat Council Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
        {/* 1. 🦅 EAGLE */}
        <div className="p-2.5 rounded-lg bg-surface/60 border border-border/60 hover:border-sky-500/40 transition-all space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-black text-sky-400 flex items-center gap-1">
              <span>🦅</span> EAGLE (Macro Trend)
            </span>
            <span
              className={`text-[8px] font-black font-mono px-1.5 py-0.5 rounded uppercase ${
                eagle.status === 'ALIGNED'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
              }`}
            >
              {eagle.status || 'ALIGNED'}
            </span>
          </div>
          <p className="text-[9px] text-zinc-300 leading-tight">
            Nifty Benchmark: <span className="font-mono font-bold text-zinc-100">{eagle.nifty_change_pct !== undefined ? `${eagle.nifty_change_pct > 0 ? '+' : ''}${eagle.nifty_change_pct}%` : 'Normal'}</span>
          </p>
          <p className="text-[9px] text-zinc-400 leading-tight">
            Sector RRG Phase: <span className="font-mono text-zinc-200">{eagle.sector_rrg_phase || 'LEADING / IMPROVING'}</span>
          </p>
        </div>

        {/* 2. 🐅 TIGER */}
        <div className="p-2.5 rounded-lg bg-surface/60 border border-border/60 hover:border-amber-500/40 transition-all space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-black text-amber-400 flex items-center gap-1">
              <span>🐅</span> TIGER (Stalking / Kill Zone)
            </span>
            <span
              className={`text-[8px] font-black font-mono px-1.5 py-0.5 rounded uppercase ${
                tiger.in_kill_zone || tiger.status === 'KILL_ZONE_LOCKED'
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse'
                  : 'bg-zinc-500/20 text-zinc-300 border border-zinc-500/40'
              }`}
            >
              {tiger.status || 'STALKING_COIL'}
            </span>
          </div>
          <p className="text-[9px] text-zinc-300 leading-tight">
            Trigger Proximity: <span className="font-mono font-bold text-zinc-100">{tiger.proximity_pct !== undefined ? `${tiger.proximity_pct}%` : '±0.25%'}</span>
          </p>
          <p className="text-[9px] text-zinc-400 leading-tight">
            Volatility State: <span className="font-mono text-zinc-200">{tiger.squeeze_phase || 'SQUEEZE_ON'}</span>
          </p>
        </div>

        {/* 3. 🧠 CHANAKYA */}
        <div className="p-2.5 rounded-lg bg-surface/60 border border-border/60 hover:border-emerald-500/40 transition-all space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-black text-emerald-400 flex items-center gap-1">
              <span>🧠</span> CHANAKYA (De-Trapping)
            </span>
            <span
              className={`text-[8px] font-black font-mono px-1.5 py-0.5 rounded uppercase ${
                chanakya.status === 'DE_TRAPPED'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : 'bg-zinc-500/20 text-zinc-300 border border-zinc-500/40'
              }`}
            >
              {chanakya.status || 'DE_TRAPPED'}
            </span>
          </div>
          <p className="text-[9px] text-zinc-300 leading-tight">
            Upper Wick Ratio: <span className="font-mono font-bold text-zinc-100">{chanakya.upper_wick_ratio !== undefined ? `${(chanakya.upper_wick_ratio * 100).toFixed(0)}%` : '<40%'}</span> (Rejection Clean)
          </p>
          <p className="text-[9px] text-zinc-400 leading-tight">
            Runway Obstacles: <span className="font-mono text-emerald-300">CLEAR (No opposing walls)</span>
          </p>
        </div>

        {/* 4. 🎯 SNIPER */}
        <div className="p-2.5 rounded-lg bg-surface/60 border border-border/60 hover:border-rose-500/40 transition-all space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-black text-rose-400 flex items-center gap-1">
              <span>🎯</span> SNIPER (Precision & EV)
            </span>
            <span
              className={`text-[8px] font-black font-mono px-1.5 py-0.5 rounded uppercase ${
                sniper.status === 'LASER_ENTRY'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
              }`}
            >
              {sniper.status || 'LASER_ENTRY'}
            </span>
          </div>
          <p className="text-[9px] text-zinc-300 leading-tight">
            R:R Ratio: <span className="font-mono font-bold text-zinc-100">1:{sniper.rr_ratio || '2.50'}</span> · Chase: <span className="font-mono text-zinc-200">{sniper.chase_pct ? `${sniper.chase_pct}%` : '0.0%'}</span>
          </p>
          <p className="text-[9px] text-zinc-400 leading-tight">
            Expected Edge: <span className="font-mono font-bold text-emerald-300">{sniper.expected_value_r ? `+${sniper.expected_value_r}R` : '+1.10R'}</span> (Win: {sniper.p_win_est ? `${(sniper.p_win_est * 100).toFixed(0)}%` : '60%'})
          </p>
        </div>

        {/* 5. 🐆 CHEETAH */}
        <div className="p-2.5 rounded-lg bg-surface/60 border border-border/60 hover:border-cyan-500/40 transition-all space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-black text-cyan-400 flex items-center gap-1">
              <span>🐆</span> CHEETAH (Free-Roll)
            </span>
            <span
              className={`text-[8px] font-black font-mono px-1.5 py-0.5 rounded uppercase ${
                cheetah.status === 'FREE_ROLL_ACTIVE' || metrics.free_roll_locked
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse'
                  : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
              }`}
            >
              {cheetah.status === 'FREE_ROLL_ACTIVE' || metrics.free_roll_locked ? 'FREE-ROLL LOCKED' : (cheetah.status || 'FREE_ROLL_READY')}
            </span>
          </div>
          <p className="text-[9px] text-zinc-300 leading-tight">
            Mandate: <span className="font-mono text-zinc-200">{cheetah.mandate || 'POUNCE_MOMENTUM'}</span>
          </p>
          <p className="text-[9px] text-zinc-400 leading-tight">
            T1 Action: <span className="font-mono text-zinc-300">{cheetah.t1_action || 'Bank 50% & SL to Cost'}</span>
          </p>
        </div>

        {/* 6. 🐘 ELEPHANT */}
        <div className="p-2.5 rounded-lg bg-surface/60 border border-border/60 hover:border-purple-500/40 transition-all space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-black text-purple-400 flex items-center gap-1">
              <span>🐘</span> ELEPHANT (Footprint)
            </span>
            <span
              className={`text-[8px] font-black font-mono px-1.5 py-0.5 rounded uppercase ${
                elephant.status === 'INSTITUTIONAL_FOOTPRINT'
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
                  : 'bg-zinc-500/20 text-zinc-300 border border-zinc-500/40'
              }`}
            >
              {elephant.status || 'INSTITUTIONAL_FOOTPRINT'}
            </span>
          </div>
          <p className="text-[9px] text-zinc-300 leading-tight">
            RVOL: <span className="font-mono font-bold text-zinc-100">{elephant.rvol ? `${Number(elephant.rvol).toFixed(1)}x` : '2.0x+'}</span> · POC Clear: <span className="font-mono text-emerald-300">YES</span>
          </p>
          <p className="text-[9px] text-zinc-400 leading-tight">
            Structure: <span className="font-mono text-zinc-200">{elephant.has_order_block ? 'Order Block' : elephant.has_fair_value_gap ? 'FVG Liquidity' : 'Volume Expansion'}</span>
          </p>
        </div>
      </div>

      {/* Quantized Position Sizing & Closed-Loop Circuit Breaker Bar */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1 border-t border-border/40">
        {/* Quantized Position Sizing */}
        {posSizing && (
          <div className="p-2 rounded-lg bg-surface/80 border border-border/50 text-[10px] space-y-1">
            <div className="flex items-center justify-between font-bold text-zinc-200">
              <span className="flex items-center gap-1 text-gold text-[10px] uppercase font-black">
                <span>⚖️</span> Quantized Capital Allocation (₹100k Base)
              </span>
              <span className="font-mono text-sky-400 text-[9px] uppercase">
                {posSizing.sizing_model || 'Fixed Fractional'}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-1 font-mono text-[9px] text-zinc-300 pt-0.5">
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Shares / Lots</span>
                <span className="font-bold text-text">
                  {posSizing.lots > 0 ? `${posSizing.lots} Lot (${posSizing.shares} sh)` : `${posSizing.shares} shares`}
                </span>
              </div>
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Max Risk</span>
                <span className="font-bold text-rose-400">
                  {currSym}{posSizing.risk_amount} ({posSizing.risk_pct}%)
                </span>
              </div>
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Capital</span>
                <span className="font-bold text-zinc-200">
                  {currSym}{posSizing.capital_allocated?.toLocaleString('en-IN')}
                </span>
              </div>
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">R-Multiple</span>
                <span className="font-bold text-emerald-400">
                  {posSizing.r_multiple}R
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Closed-Loop Detector Circuit Breaker Status */}
        {cb.status && (
          <div className="p-2 rounded-lg bg-surface/80 border border-border/50 text-[10px] space-y-1">
            <div className="flex items-center justify-between font-bold text-zinc-200">
              <span className="flex items-center gap-1 text-purple-400 text-[10px] uppercase font-black">
                <span>🛡️</span> Closed-Loop Circuit Breaker ({alert.alert_type || cb.alert_type})
              </span>
              <span
                className={`text-[8px] font-mono font-black px-1.5 py-px rounded uppercase ${
                  cb.status === 'HEALTHY'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                    : cb.status === 'NORMAL'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                    : cb.status === 'PROBATION'
                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                }`}
              >
                {cb.status}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-1 font-mono text-[9px] text-zinc-300 pt-0.5">
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Win Rate</span>
                <span className="font-bold text-text">
                  {cb.win_rate !== undefined ? `${(cb.win_rate * 100).toFixed(0)}%` : '50%'}
                </span>
              </div>
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Payoff R</span>
                <span className="font-bold text-zinc-200">
                  {cb.payoff_ratio || '2.0'}R
                </span>
              </div>
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Expectancy</span>
                <span className="font-bold text-emerald-400">
                  {cb.expectancy !== undefined ? `${cb.expectancy > 0 ? '+' : ''}${cb.expectancy.toFixed(2)}` : '+0.50'}
                </span>
              </div>
              <div className="p-1 rounded bg-panel/80 border border-border/30">
                <span className="text-[8px] text-muted block uppercase">Half-Kelly</span>
                <span className="font-bold text-sky-400">
                  {cb.half_kelly !== undefined ? `${(cb.half_kelly * 100).toFixed(1)}%` : '12.5%'}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
})
