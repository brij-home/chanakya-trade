import { useState, useMemo } from 'react'
import { useChatStore, getActiveSymbol } from '../../store/chatStore'
import { useAPI } from '../../hooks/useAPI'
import BrokerPanel from './BrokerPanel'

const ROLE_LABELS = { data: 'DATA', execution: 'EXEC', both: '' }

// Quick commands kept for routing — used by InputBar command chips, not displayed in sidebar
export const QUICK_COMMANDS = [
  { label: 'Morning Brief',  command: 'morning-brief' },
  { label: 'Holdings',       command: 'holdings' },
  { label: 'Positions',      command: 'positions' },
  { label: 'Orders',         command: 'orders' },
  { label: 'Funds',          command: 'funds' },
  { label: 'Alerts',         command: 'alerts' },
  { label: 'FII/DII Flows',  command: 'flows' },
  { label: 'Patterns',       command: 'patterns' },
  { label: 'Scan',           command: 'scan' },
  { label: 'GEX',            command: 'gex NIFTY' },
  { label: 'IV Smile',       command: 'iv-smile NIFTY' },
  { label: 'Risk Report',    command: 'risk-report' },
  { label: 'Strategy',       command: 'strategy NIFTY bullish' },
  { label: 'Delta Hedge',    command: 'delta-hedge' },
  { label: 'What-If',        command: 'whatif' },
  { label: 'Drift',          command: 'drift' },
  { label: 'Memory',         command: 'memory' },
]

export default function Sidebar() {
  const { isLoading, brokerStatuses, port, activeView, setActiveView } = useChatStore()
  const sessions = useChatStore((s) => s.sessions)
  const activeSessionId = useChatStore((s) => s.activeSessionId)
  const createSession = useChatStore((s) => s.createSession)
  const switchSession = useChatStore((s) => s.switchSession)
  const deleteSession = useChatStore((s) => s.deleteSession)
  const showDashboard = useChatStore((s) => s.showDashboard)
  const setShowDashboard = useChatStore((s) => s.setShowDashboard)
  const sendDraft = useChatStore((s) => s.sendDraft)
  const setDraft = useChatStore((s) => s.setDraft)
  const messages = useChatStore((s) => s.messages)
  const activeSymbol = getActiveSymbol(messages)
  const [showBrokerPanel, setShowBrokerPanel] = useState(false)
  const [hoveredSession, setHoveredSession] = useState(null)
  const [sessionSearch, setSessionSearch] = useState('')

  const sessionList = Object.values(sessions).sort((a, b) => b.createdAt - a.createdAt)
  const connectedBrokers = Object.entries(brokerStatuses).filter(([, b]) => b.authenticated)

  // Group sessions by date
  const groupedSessions = useMemo(() => {
    const oneDay = 24 * 60 * 60 * 1000
    const todayStart = new Date().setHours(0, 0, 0, 0)
    const yesterdayStart = todayStart - oneDay

    const filtered = sessionList.filter((s) =>
      !sessionSearch.trim() ||
      s.title?.toLowerCase().includes(sessionSearch.toLowerCase())
    )

    const groups = {
      Today: [],
      Yesterday: [],
      'This Week': [],
      Older: [],
    }

    for (const s of filtered) {
      const created = s.createdAt || 0
      if (created >= todayStart) {
        groups.Today.push(s)
      } else if (created >= yesterdayStart) {
        groups.Yesterday.push(s)
      } else if (created >= todayStart - 7 * oneDay) {
        groups['This Week'].push(s)
      } else {
        groups.Older.push(s)
      }
    }

    return Object.entries(groups).filter(([, list]) => list.length > 0)
  }, [sessionList, sessionSearch])

  return (
    <div className="w-60 flex-shrink-0 bg-panel border-r border-border flex flex-col relative">

      {/* Broker panel overlay */}
      {showBrokerPanel && <BrokerPanel onClose={() => setShowBrokerPanel(false)} />}

      {/* Workspace Quick Jump */}
      <div className="px-3 pt-3 pb-2 space-y-1 border-b border-border/50">
        <div className="flex items-center justify-between px-1 pb-1">
          <span className="text-[10px] uppercase font-ui tracking-wider text-muted font-bold">Workspaces</span>
        </div>
        <button
          onClick={() => setActiveView('terminal')}
          className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-[11px] font-ui transition-colors cursor-pointer ${
            activeView === 'terminal'
              ? 'bg-amber/15 border-amber/40 text-amber font-bold shadow-xs'
              : 'border-border/60 text-muted hover:text-text hover:bg-elevated'
          }`}
          title="Switch to Strategic Quant Terminal (Ctrl+1)"
        >
          <span>📊</span>
          <span>Terminal</span>
          <span className="ml-auto text-[9px] text-subtle font-mono">^1</span>
        </button>

        <button
          onClick={() => setActiveView('debate')}
          className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-[11px] font-ui transition-colors cursor-pointer ${
            activeView === 'debate'
              ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-400 font-bold shadow-xs'
              : 'border-border/60 text-muted hover:text-text hover:bg-elevated'
          }`}
          title="Switch to Multi-Agent Debate Arena (Ctrl+2)"
        >
          <span>⚔️</span>
          <span>Debate Arena</span>
          <span className="ml-auto text-[9px] text-subtle font-mono">^2</span>
        </button>

        <button
          onClick={() => setActiveView('options')}
          className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-[11px] font-ui transition-colors cursor-pointer ${
            activeView === 'options'
              ? 'bg-cyan-500/15 border-cyan-500/40 text-cyan-400 font-bold shadow-xs'
              : 'border-border/60 text-muted hover:text-text hover:bg-elevated'
          }`}
          title="Switch to Quant Options & GEX Desk (Ctrl+3)"
        >
          <span>⚡</span>
          <span>Options &amp; GEX</span>
          <span className="ml-auto text-[9px] text-subtle font-mono">^3</span>
        </button>
      </div>

      {/* Navigation: Overview Dashboard & New Session */}
      <div className="px-3 pt-2 pb-2 space-y-1.5 border-b border-border/40">
        <button
          onClick={() => { setActiveView('copilot'); setShowDashboard(true); }}
          className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[11px] font-ui transition-colors cursor-pointer ${
            showDashboard && activeView === 'copilot'
              ? 'bg-amber/15 border-amber/40 text-amber font-semibold shadow-xs'
              : 'border-border/60 text-muted hover:text-text hover:bg-elevated'
          }`}
          title="Return to Copilot Dashboard"
        >
          <span>🏠</span>
          <span>Copilot Overview</span>
        </button>

        <button
          onClick={() => { setActiveView('copilot'); setShowDashboard(false); createSession(); }}
          className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border/60
                     text-[11px] font-ui text-muted hover:text-text hover:bg-elevated
                     transition-colors cursor-pointer"
          title="Start a new analysis session"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          <span>New Session</span>
          <span className="ml-auto text-[9px] text-subtle font-mono">^N</span>
        </button>

        {/* Quick Filter Search for Sessions */}
        {sessionList.length > 3 && (
          <div className="relative pt-1">
            <input
              type="text"
              placeholder="Search research sessions..."
              value={sessionSearch}
              onChange={(e) => setSessionSearch(e.target.value)}
              className="w-full bg-elevated border border-border/70 rounded-lg px-2.5 py-1 text-[11px] text-text placeholder:text-muted outline-none focus:border-amber/50"
            />
            {sessionSearch && (
              <button
                onClick={() => setSessionSearch('')}
                className="absolute right-2 top-2 text-xs text-muted hover:text-text"
              >
                ×
              </button>
            )}
          </div>
        )}
      </div>

      {/* Date-Grouped Session List — primary content */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        <div className="space-y-3">
          {groupedSessions.map(([groupName, list]) => (
            <div key={groupName} className="space-y-0.5">
              <span className="text-[10px] uppercase font-bold text-muted px-2 py-0.5 tracking-wider block font-ui">
                {groupName}
              </span>

              {list.map((s) => (
                <div
                  key={s.id}
                  onMouseEnter={() => setHoveredSession(s.id)}
                  onMouseLeave={() => setHoveredSession(null)}
                  className={`group flex items-center rounded-lg cursor-pointer transition-colors ${
                    s.id === activeSessionId && !showDashboard
                      ? 'bg-elevated text-text font-semibold'
                      : 'text-muted hover:bg-elevated/50 hover:text-text'
                  }`}
                >
                  <button
                    onClick={() => { setShowDashboard(false); switchSession(s.id); }}
                    className="flex-1 text-left px-2.5 py-1.5 text-[11px] font-ui truncate cursor-pointer"
                  >
                    {s.title}
                  </button>
                  {hoveredSession === s.id && sessionList.length > 1 && (
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
                      className="pr-2 text-subtle hover:text-red text-[11px] cursor-pointer transition-colors"
                      title="Delete session"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>
          ))}

          {groupedSessions.length === 0 && (
            <p className="text-[11px] text-muted text-center py-4">No matching sessions</p>
          )}
        </div>
      </div>

      {/* Quick Trading Tools (1-Click Instant Execution / Contextual Actions) */}
      <div className="px-3 py-2 border-t border-border/50 bg-panel/30">
        <div className="flex items-center justify-between mb-1.5 px-1">
          <p className="text-[10px] uppercase font-ui tracking-wider text-muted font-semibold">Institutional Tools</p>
          {activeSymbol && (
            <span className="text-[9px] font-mono text-amber bg-amber/10 border border-amber/30 px-1 rounded font-bold" title="Active Stock Context">
              {activeSymbol}
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-1 text-[11px] font-ui">
          <button
            onClick={() => sendDraft('brief')}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-muted hover:text-text hover:bg-elevated text-left transition-colors cursor-pointer"
            title="Generate Morning Market Brief"
          >
            <span>🌅</span> Brief
          </button>
          <button
            onClick={() => sendDraft('scan')}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-muted hover:text-text hover:bg-elevated text-left transition-colors cursor-pointer"
            title="Scan NSE Sector Breadth & Breakouts"
          >
            <span>🌐</span> Breadth
          </button>
          <button
            onClick={() => {
              if (activeSymbol) {
                sendDraft(`funnel ${activeSymbol}`)
              } else {
                setDraft('funnel ')
              }
            }}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-muted hover:text-text hover:bg-elevated text-left transition-colors cursor-pointer"
            title={activeSymbol ? `Screen ${activeSymbol} in Smart Funnel` : "Smart Funnel Multi-Agent Screening"}
          >
            <span>🎯</span> Funnel
          </button>
          <button
            onClick={() => {
              if (activeSymbol) {
                sendDraft(`rrg ${activeSymbol}`)
              } else {
                sendDraft('rrg')
              }
            }}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-muted hover:text-text hover:bg-elevated text-left transition-colors cursor-pointer"
            title={activeSymbol ? `Check ${activeSymbol} Sector RRG Momentum` : "Relative Rotation Graphs (RRG Matrix)"}
          >
            <span>📈</span> RRG
          </button>
          <button
            onClick={() => sendDraft('flows')}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-muted hover:text-text hover:bg-elevated text-left transition-colors cursor-pointer"
            title="FII & DII Cash & Futures Institutional Flows"
          >
            <span>🌊</span> Flows
          </button>
          <button
            onClick={() => {
              if (activeSymbol) {
                sendDraft(`forensic ${activeSymbol}`)
              } else {
                setDraft('forensic ')
              }
            }}
            className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-muted hover:text-text hover:bg-elevated text-left transition-colors cursor-pointer"
            title={activeSymbol ? `Audit Balance Sheet & Forensics for ${activeSymbol}` : "Forensic Accounting Audit (Beneish & Altman)"}
          >
            <span>🛡️</span> Forensic
          </button>
        </div>
      </div>

      {/* Broker status — compact, at bottom */}
      <div
        className="px-3 py-3 border-t border-border cursor-pointer hover:bg-elevated/50 transition-colors"
        onClick={() => setShowBrokerPanel(true)}
      >
        {connectedBrokers.length === 0 ? (
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-subtle flex-shrink-0" />
            <span className="text-[11px] text-muted font-ui">
              {(port || window.__CHANAKYA_TRADE_WEB__) ? 'No broker connected' : 'Starting...'}
            </span>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {connectedBrokers.map(([key, status]) => {
              const name = { zerodha: 'Zerodha', groww: 'Groww', angel_one: 'Angel One', upstox: 'Upstox', fyers: 'Fyers' }[key] ?? key
              const roleLabel = ROLE_LABELS[status.role] || ''
              return (
                <div key={key} className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-green flex-shrink-0" />
                  <span className="text-[11px] text-text font-ui">{name}</span>
                  {roleLabel && (
                    <span className={`text-[8px] font-ui font-bold uppercase tracking-wider px-1 py-0.5 rounded flex-shrink-0 ${
                      status.role === 'data' ? 'bg-blue/10 text-blue' : 'bg-amber/10 text-amber'
                    }`}>{roleLabel}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

// Route sidebar quick commands to API endpoints (used by InputBar chips)
export async function routeCommand(call, command) {
  const unwrap = (res) => res.data ?? res
  switch (command) {
    case 'morning-brief':
      return { cardType: 'morning_brief', data: unwrap(await call('/skills/morning_brief', {})) }
    case 'holdings':
      return { cardType: 'holdings', data: unwrap(await call('/skills/holdings', {})) }
    case 'positions':
      return { cardType: 'holdings', data: unwrap(await call('/skills/positions', {})) }
    case 'flows': {
      const fd = unwrap(await call('/skills/flows', {}))
      return { cardType: 'flows', data: fd?.flow_analysis ?? fd }
    }
    case 'orders':
      return { cardType: 'orders', data: unwrap(await call('/skills/orders', {})) }
    case 'funds':
      return { cardType: 'funds',    data: unwrap(await call('/skills/funds',    {})) }
    case 'alerts':
      return { cardType: 'alerts',   data: unwrap(await call('/skills/alerts/list', {})) }
    case 'patterns':
      return { cardType: 'patterns', data: unwrap(await call('/skills/patterns', {})) }
    case 'scan':
      return { cardType: 'scan',     data: unwrap(await call('/skills/scan',     { scan_type: 'options', filters: {} })) }
    case 'gex NIFTY':
      return { cardType: 'gex',         data: unwrap(await call('/skills/gex',         { symbol: 'NIFTY', expiry: null })) }
    case 'iv-smile NIFTY':
      return { cardType: 'iv_smile',    data: unwrap(await call('/skills/iv_smile',    { symbol: 'NIFTY', expiry: null })) }
    case 'risk-report':
      return { cardType: 'risk_report', data: unwrap(await call('/skills/risk_report', {})) }
    case 'strategy NIFTY bullish':
      return { cardType: 'strategy',    data: unwrap(await call('/skills/strategy',    { symbol: 'NIFTY', view: 'BULLISH', dte: 30 })) }
    case 'delta-hedge':
      return { cardType: 'delta_hedge', data: unwrap(await call('/skills/delta_hedge', {})) }
    case 'whatif':
      return { cardType: 'whatif',      data: unwrap(await call('/skills/whatif',      { scenario: 'market' })) }
    case 'drift':
      return { cardType: 'drift',       data: unwrap(await call('/skills/drift',       {})) }
    case 'memory':
      return { cardType: 'memory',      data: unwrap(await call('/skills/memory',      {})) }
    default:
      throw new Error(`Unknown command: ${command}`)
  }
}
