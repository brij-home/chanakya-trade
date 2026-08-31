import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

const MOCK_TRADES = [
  { id: 1, date: '2026-08-30', symbol: 'NIFTY',    direction: 'LONG',  setup: 'SMC Order Block Retest', entry: 24100, exit: 24310, qty: 50,  pnl: 10500, r: 2.1, duration: '2h 15m', emotion: '😌', tags: ['SMC','BOS','OB'] },
  { id: 2, date: '2026-08-29', symbol: 'RELIANCE',  direction: 'LONG',  setup: 'VCP Breakout Stage 2',  entry: 2790,  exit: 2847,  qty: 70,  pnl: 3990,  r: 1.8, duration: '3 days', emotion: '🎯', tags: ['VCP','Stage2','EPS'] },
  { id: 3, date: '2026-08-28', symbol: 'BANKNIFTY', direction: 'SHORT', setup: 'Bull Trap CHoCH Bear',  entry: 54200, exit: 53750, qty: 25,  pnl: 11250, r: 2.5, duration: '4h 45m', emotion: '😌', tags: ['CHoCH','SMC','FVG'] },
  { id: 4, date: '2026-08-27', symbol: 'HDFCBANK',  direction: 'LONG',  setup: 'Wyckoff Spring',       entry: 1695,  exit: 1680,  qty: 90,  pnl: -1350, r: -0.6, duration: '1 day', emotion: '😤', tags: ['Wyckoff','Stop'] },
  { id: 5, date: '2026-08-26', symbol: 'INFY',      direction: 'LONG',  setup: 'Earnings Beat + Stage 2', entry: 1680, exit: 1720, qty: 100, pnl: 4000, r: 1.5, duration: '5 days', emotion: '😊', tags: ['Catalyst','Stage2'] },
  { id: 6, date: '2026-08-25', symbol: 'NIFTY',     direction: 'LONG',  setup: 'VWAP Reclaim + FVG',   entry: 23980, exit: 24080, qty: 50,  pnl: 5000,  r: 1.2, duration: '1h 20m', emotion: '😌', tags: ['VWAP','FVG','SMC'] },
]

const STREAK_STATS = {
  currentStreak: 5,
  streakType: 'WIN',
  totalTrades: 47,
  winners: 34,
  losers: 13,
  avgWin: 3.2,
  avgLoss: -1.4,
  bestTrade: 21000,
  worstTrade: -4800,
  avgHold: '2.1 days',
}

/* ── Emotion tracker ──────────────────────────────────────────────────────── */
function EmotionTrail({ trades }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>Emotion Trail:</span>
      {trades.map((t) => (
        <div key={t.id} title={`${t.symbol} — ${t.r >= 0 ? `+${t.r}R` : `${t.r}R`}`} className="cursor-pointer text-base">
          {t.emotion}
        </div>
      ))}
    </div>
  )
}

/* ── R-multiple sparkline ────────────────────────────────────────────────── */
function RSparkline({ trades }) {
  const values = trades.map((t) => t.r)
  const max = Math.max(...values.map(Math.abs), 3)
  const w = 40
  const h = 28
  const cx = w / (values.length - 1)

  const pts = values.map((v, i) => {
    const x = i * cx
    const y = h / 2 - (v / max) * (h / 2 - 2)
    return `${x},${y}`
  })

  return (
    <svg width={w} height={h} style={{ overflow: 'visible' }}>
      <line x1={0} y1={h/2} x2={w} y2={h/2} stroke="var(--color-border)" strokeWidth={0.5} strokeDasharray="2,2" />
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke="var(--color-gold)"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {values.map((v, i) => (
        <circle
          key={i}
          cx={i * cx}
          cy={h / 2 - (v / max) * (h / 2 - 2)}
          r={2.5}
          fill={v >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)'}
        />
      ))}
    </svg>
  )
}

/* ── Trade row ───────────────────────────────────────────────────────────── */
function TradeRow({ trade, onAnalyze }) {
  const [expanded, setExpanded] = useState(false)
  const isWin = trade.pnl >= 0

  return (
    <div
      className="border-b transition-colors cursor-pointer"
      style={{ borderColor: 'var(--color-border-subtle)' }}
    >
      <div
        className="grid items-center px-4 py-2.5 hover:bg-highlight transition-colors"
        style={{ gridTemplateColumns: '1.5fr 0.7fr 0.7fr 1fr 0.7fr 0.7fr 0.8fr 1.5fr' }}
        onClick={() => setExpanded((v) => !v)}
      >
        <div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>{trade.symbol}</span>
            <span
              className="text-[9px] px-1.5 py-0.5 rounded font-bold"
              style={{
                background: trade.direction === 'LONG' ? 'rgba(0,214,143,0.15)' : 'rgba(255,79,123,0.15)',
                color: trade.direction === 'LONG' ? 'var(--color-emerald)' : 'var(--color-rose)',
              }}
            >
              {trade.direction}
            </span>
          </div>
          <div className="text-[9px] mt-0.5" style={{ color: 'var(--color-muted)' }}>{trade.setup}</div>
        </div>
        <div className="text-[11px] font-mono text-muted">{trade.date.slice(5)}</div>
        <div className="text-[11px] font-mono" style={{ color: 'var(--color-text)' }}>₹{trade.entry.toLocaleString('en-IN')}</div>
        <div className="text-[11px] font-mono font-bold tabular-nums" style={{ color: isWin ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
          {isWin ? '+' : ''}₹{trade.pnl.toLocaleString('en-IN')}
        </div>
        <div className="text-[11px] font-mono font-black" style={{ color: isWin ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
          {trade.r >= 0 ? '+' : ''}{trade.r}R
        </div>
        <div className="text-[11px] font-mono text-muted">{trade.duration}</div>
        <div className="text-base">{trade.emotion}</div>
        <div className="flex flex-wrap gap-1">
          {trade.tags.map((tag) => (
            <span key={tag} className="text-[9px] px-1.5 py-0.5 rounded font-bold" style={{ background: 'var(--color-elevated)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }}>
              {tag}
            </span>
          ))}
        </div>
      </div>

      {expanded && (
        <div
          className="px-4 pb-3 pt-0 animate-slide-down-fade"
          style={{ background: 'var(--color-elevated)' }}
        >
          <div className="flex gap-2 pt-2">
            <button
              onClick={() => onAnalyze(`analyze this trade: ${trade.symbol} ${trade.direction} from ${trade.entry} to ${trade.exit}, setup: ${trade.setup}`)}
              className="btn btn-xs"
              style={{ background: 'rgba(157,125,255,0.15)', border: '1px solid rgba(157,125,255,0.4)', color: 'var(--color-violet)' }}
            >
              🔬 AI Post-Mortem
            </button>
            <span className="text-[10px] self-center" style={{ color: 'var(--color-muted)' }}>
              Qty: {trade.qty} · Entry ₹{trade.entry} → Exit ₹{trade.exit}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Win/Loss Calendar Heatmap ──────────────────────────────────────────── */
function WinLossCalendar({ trades }) {
  // Build a date → trade map
  const tradeMap = {}
  trades.forEach((t) => { tradeMap[t.date] = t })

  // Generate last 35 days (5 weeks)
  const today = new Date('2026-08-30')
  const days = []
  for (let i = 34; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    const key = d.toISOString().slice(0, 10)
    days.push({ key, d })
  }

  // 7 columns (weeks), 5 rows (days)
  const weeks = []
  for (let w = 0; w < 5; w++) weeks.push(days.slice(w * 7, w * 7 + 7))

  const dayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const maxPnl = Math.max(...trades.map((t) => Math.abs(t.pnl)), 1)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--color-muted)' }}>📅 Win/Loss Calendar — Last 35 Days</div>
        <div className="flex items-center gap-3 text-[9px]" style={{ color: 'var(--color-muted)' }}>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm inline-block" style={{ background: 'var(--color-emerald)' }} /> Win</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm inline-block" style={{ background: 'var(--color-rose)' }} /> Loss</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm inline-block" style={{ background: 'var(--color-elevated)' }} /> No Trade</span>
        </div>
      </div>

      {/* Day-of-week labels */}
      <div className="grid gap-1" style={{ gridTemplateColumns: `60px repeat(7, 1fr)` }}>
        <div />
        {dayLabels.map((l) => (
          <div key={l} className="text-center text-[8px] font-bold" style={{ color: 'var(--color-muted)' }}>{l}</div>
        ))}
      </div>

      {/* Calendar grid — rows = weeks */}
      {weeks.map((week, wi) => (
        <div key={wi} className="grid gap-1 items-center" style={{ gridTemplateColumns: `60px repeat(7, 1fr)` }}>
          {/* Week label */}
          <div className="text-[9px] font-mono text-right pr-2" style={{ color: 'var(--color-muted)' }}>
            {week[0]?.key.slice(5)}
          </div>
          {week.map(({ key, d }) => {
            const trade = tradeMap[key]
            const isWin = trade && trade.pnl >= 0
            const intensity = trade ? Math.min(1, Math.abs(trade.pnl) / maxPnl) : 0
            const dayOfWeek = d.getDay() // 0=Sun
            const isWeekend = dayOfWeek === 0 || dayOfWeek === 6
            const bgColor = trade
              ? isWin
                ? `rgba(0, 214, 143, ${0.15 + intensity * 0.7})`
                : `rgba(255, 79, 123, ${0.15 + intensity * 0.7})`
              : isWeekend
              ? 'rgba(255,255,255,0.02)'
              : 'var(--color-elevated)'
            const borderColor = trade
              ? isWin ? 'rgba(0,214,143,0.5)' : 'rgba(255,79,123,0.5)'
              : 'var(--color-border)'

            return (
              <div
                key={key}
                className="relative group"
                style={{ aspectRatio: '1' }}
              >
                <div
                  className="w-full h-full rounded-lg cursor-pointer transition-all hover:scale-110"
                  style={{ background: bgColor, border: `1px solid ${borderColor}`, minHeight: '28px' }}
                  title={trade ? `${trade.symbol} · ${isWin ? '+' : ''}₹${trade.pnl.toLocaleString('en-IN')} · ${trade.r >= 0 ? '+' : ''}${trade.r}R` : key}
                />
                {/* Tooltip */}
                {trade && (
                  <div
                    className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 rounded-lg text-[9px] font-mono pointer-events-none z-50 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap"
                    style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  >
                    <div className="font-bold">{trade.symbol}</div>
                    <div style={{ color: isWin ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
                      {isWin ? '+' : ''}₹{trade.pnl.toLocaleString('en-IN')} · {trade.r >= 0 ? '+' : ''}{trade.r}R
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}

      {/* Monthly summary chips */}
      <div className="flex flex-wrap gap-2 pt-2">
        {[
          { label: 'Winning Days', value: trades.filter((t) => t.pnl >= 0).length, color: 'var(--color-emerald)' },
          { label: 'Losing Days', value: trades.filter((t) => t.pnl < 0).length, color: 'var(--color-rose)' },
          { label: 'Best Day', value: `+₹${Math.max(...trades.map((t) => t.pnl)).toLocaleString('en-IN')}`, color: 'var(--color-emerald)' },
          { label: 'Worst Day', value: `₹${Math.min(...trades.map((t) => t.pnl)).toLocaleString('en-IN')}`, color: 'var(--color-rose)' },
          { label: 'Total P&L', value: `+₹${trades.reduce((a, t) => a + t.pnl, 0).toLocaleString('en-IN')}`, color: 'var(--color-gold)' },
        ].map(({ label, value, color }) => (
          <div key={label} className="px-3 py-1.5 rounded-xl text-[9px] font-mono" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
            <span style={{ color: 'var(--color-muted)' }}>{label}: </span>
            <span className="font-bold" style={{ color }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Main View ───────────────────────────────────────────────────────────── */
export default function JournalView() {
  const sendDraft = useChatStore((s) => s.sendDraft)
  const [filterTag, setFilterTag] = useState('')
  const [tab, setTab] = useState('trades')

  const allTags = [...new Set(MOCK_TRADES.flatMap((t) => t.tags))]
  const filtered = filterTag ? MOCK_TRADES.filter((t) => t.tags.includes(filterTag)) : MOCK_TRADES
  const wins = MOCK_TRADES.filter((t) => t.pnl >= 0)
  const totalR = MOCK_TRADES.reduce((a, t) => a + t.r, 0)

  const tabs = [
    { id: 'trades', label: '📋 Trade Log' },
    { id: 'analytics', label: '🧠 Pattern Analytics' },
    { id: 'calendar', label: '📅 Calendar' },
  ]

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3 font-ui" style={{ background: 'var(--color-surface)' }}>

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-black" style={{ color: 'var(--color-text)' }}>📋 Trade Journal</h1>
          <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
            {MOCK_TRADES.length} trades · Win rate {((wins.length / MOCK_TRADES.length) * 100).toFixed(0)}% · Total {totalR.toFixed(1)}R
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => sendDraft('analyze my trading patterns and find edge improvements')}
            className="btn btn-sm"
            style={{ background: 'rgba(157,125,255,0.15)', border: '1px solid rgba(157,125,255,0.4)', color: 'var(--color-violet)', fontWeight: 700 }}
          >
            🧠 AI Pattern Review
          </button>
        </div>
      </div>

      {/* Streak banner */}
      <div
        className="flex items-center gap-4 px-4 py-3 rounded-2xl animate-slide-up-fade"
        style={{
          background: STREAK_STATS.streakType === 'WIN' ? 'rgba(0,214,143,0.1)' : 'rgba(255,79,123,0.1)',
          border: `1px solid ${STREAK_STATS.streakType === 'WIN' ? 'rgba(0,214,143,0.35)' : 'rgba(255,79,123,0.35)'}`,
        }}
      >
        <div className="text-3xl">{STREAK_STATS.streakType === 'WIN' ? '🔥' : '🛡️'}</div>
        <div>
          <div className="text-sm font-black" style={{ color: STREAK_STATS.streakType === 'WIN' ? 'var(--color-emerald)' : 'var(--color-rose)' }}>
            {STREAK_STATS.currentStreak}-Trade {STREAK_STATS.streakType} STREAK
          </div>
          <div className="text-[10px]" style={{ color: 'var(--color-muted)' }}>
            {STREAK_STATS.totalTrades} total · {STREAK_STATS.winners}W / {STREAK_STATS.losers}L · Avg hold {STREAK_STATS.avgHold}
          </div>
        </div>
        <div className="ml-auto">
          <EmotionTrail trades={MOCK_TRADES.slice(0, 6)} />
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: 'Avg Win', value: `+${STREAK_STATS.avgWin}R`, color: 'var(--color-emerald)', icon: '📈' },
          { label: 'Avg Loss', value: `${STREAK_STATS.avgLoss}R`, color: 'var(--color-rose)', icon: '📉' },
          { label: 'Best Trade', value: `+₹${STREAK_STATS.bestTrade.toLocaleString('en-IN')}`, color: 'var(--color-emerald)', icon: '🏆' },
          { label: 'Worst Trade', value: `₹${STREAK_STATS.worstTrade.toLocaleString('en-IN')}`, color: 'var(--color-rose)', icon: '💀' },
        ].map(({ label, value, color, icon }) => (
          <div key={label} className="rounded-xl p-3" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
            <div className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>{icon} {label}</div>
            <div className="text-sm font-mono font-black tabular-nums mt-1" style={{ color }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Tab switcher */}
      <div className="tab-bar">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`tab-item ${tab === t.id ? 'active-violet' : ''}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'trades' && (
        <div
          className="rounded-2xl overflow-hidden animate-slide-up-fade"
          style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
        >
          {/* Tag filters */}
          <div className="flex items-center gap-2 px-4 py-2.5 border-b flex-wrap" style={{ borderColor: 'var(--color-border)', background: 'var(--color-elevated)' }}>
            <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-muted)' }}>Filter:</span>
            <button
              onClick={() => setFilterTag('')}
              className="text-[10px] px-2 py-0.5 rounded-full font-bold transition-all"
              style={!filterTag ? { background: 'var(--color-gold)', color: '#000' } : { background: 'var(--color-elevated)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }}
            >
              All
            </button>
            {allTags.map((tag) => (
              <button
                key={tag}
                onClick={() => setFilterTag(tag === filterTag ? '' : tag)}
                className="text-[10px] px-2 py-0.5 rounded-full font-bold transition-all"
                style={filterTag === tag ? { background: 'var(--color-sapphire)', color: '#fff' } : { background: 'var(--color-elevated)', color: 'var(--color-muted)', border: '1px solid var(--color-border)' }}
              >
                {tag}
              </button>
            ))}
          </div>

          {/* Column headers */}
          <div
            className="grid px-4 py-2 text-[9px] font-bold uppercase tracking-wider border-b"
            style={{ gridTemplateColumns: '1.5fr 0.7fr 0.7fr 1fr 0.7fr 0.7fr 0.8fr 1.5fr', color: 'var(--color-muted)', borderColor: 'var(--color-border)' }}
          >
            <span>Setup</span><span>Date</span><span>Entry</span><span>P&L</span><span>R</span><span>Hold</span><span>😊</span><span>Tags</span>
          </div>

          {filtered.map((trade) => (
            <TradeRow key={trade.id} trade={trade} onAnalyze={sendDraft} />
          ))}
        </div>
      )}

      {tab === 'analytics' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 animate-slide-up-fade">
          {/* Setup performance */}
          <div className="rounded-2xl p-4" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
            <div className="text-[10px] font-bold uppercase tracking-wider mb-3" style={{ color: 'var(--color-muted)' }}>🎯 Setup Performance</div>
            {[
              { setup: 'SMC Order Block', trades: 12, winRate: 83, avgR: 2.1 },
              { setup: 'VCP Breakout', trades: 8, winRate: 75, avgR: 1.8 },
              { setup: 'Wyckoff Spring', trades: 6, winRate: 67, avgR: 1.5 },
              { setup: 'VWAP Reclaim', trades: 9, winRate: 78, avgR: 1.2 },
              { setup: 'CHoCH Reversal', trades: 5, winRate: 80, avgR: 2.3 },
            ].map(({ setup, trades, winRate, avgR }) => (
              <div key={setup} className="flex items-center gap-3 mb-2">
                <span className="text-xs w-32 flex-shrink-0" style={{ color: 'var(--color-text)' }}>{setup}</span>
                <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--color-elevated)' }}>
                  <div className="h-full rounded-full" style={{ width: `${winRate}%`, background: 'var(--color-emerald)' }} />
                </div>
                <span className="text-[10px] font-mono font-bold w-10" style={{ color: 'var(--color-emerald)' }}>{winRate}%</span>
                <span className="text-[10px] font-mono w-12" style={{ color: 'var(--color-muted)' }}>+{avgR}R avg</span>
              </div>
            ))}
          </div>

          {/* R-distribution + sparkline */}
          <div className="rounded-2xl p-4" style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}>
            <div className="text-[10px] font-bold uppercase tracking-wider mb-3" style={{ color: 'var(--color-muted)' }}>📈 R-Multiple Distribution</div>
            <div className="flex items-end gap-1 h-28 pt-2">
              {MOCK_TRADES.map((t) => (
                <div
                  key={t.id}
                  className="flex-1 rounded-sm transition-all hover:opacity-75"
                  style={{
                    height: `${Math.abs(t.r) / 3 * 80}%`,
                    minHeight: '4px',
                    background: t.r >= 0 ? 'var(--color-emerald)' : 'var(--color-rose)',
                    opacity: 0.85,
                  }}
                  title={`${t.symbol}: ${t.r >= 0 ? '+' : ''}${t.r}R`}
                />
              ))}
            </div>
            <div className="flex justify-between text-[9px] mt-1" style={{ color: 'var(--color-muted)' }}>
              <span>Each bar = 1 trade</span>
              <span>Total: {totalR.toFixed(1)}R</span>
            </div>
          </div>
        </div>
      )}

      {tab === 'calendar' && (
        <div
          className="rounded-2xl p-5 animate-slide-up-fade"
          style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
        >
          <WinLossCalendar trades={MOCK_TRADES} />
        </div>
      )}
    </div>
  )
}
