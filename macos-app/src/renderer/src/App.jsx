import { useEffect, useState, useCallback, lazy, Suspense } from 'react'
import { useChatStore, getBaseUrl } from './store/chatStore'
import { useMarketClock } from './hooks/useMarketClock'
import ActivityBar from './components/Shell/ActivityBar'
import ContextBar, { MarketClock } from './components/Shell/ContextBar'
import Sidebar from './components/Sidebar'
import ChatArea from './components/Chat/ChatArea'
import InputBar from './components/Input/InputBar'
import SettingsPanel from './components/Sidebar/SettingsPanel'
import SetupScreen from './components/SetupScreen'
import ActivityHUD from './components/Common/ActivityHUD'
import ModeBanner from './components/Common/ModeBanner'
import ToastContainer from './components/Toast/ToastContainer'
import HotkeyPanel from './components/UI/HotkeyPanel'
import ErrorBoundary from './components/ErrorBoundary'

// ── Lazy-loaded Workspace Views (Code-Split Chunks) ─────────────────────────
const TerminalView = lazy(() => import('./components/Views/TerminalView'))
const DebateArenaView = lazy(() => import('./components/Views/DebateArenaView'))
const OptionsDeskView = lazy(() => import('./components/Views/OptionsDeskView'))
const OverviewView = lazy(() => import('./components/Views/OverviewView'))
const PortfolioView = lazy(() => import('./components/Views/PortfolioView'))
const JournalView = lazy(() => import('./components/Views/JournalView'))
const AlertsView = lazy(() => import('./components/Views/AlertsView'))
const BacktestStudioView = lazy(() => import('./components/Views/BacktestStudioView'))
const OnboardingWizard = lazy(() => import('./components/Onboarding/OnboardingWizard'))

// ── Lazy-loaded Heavyweight Modals (Loaded on Demand) ────────────────────────
const CommandPalette = lazy(() => import('./components/Modals/CommandPalette'))
const OrderTicketModal = lazy(() => import('./components/Modals/OrderTicketModal'))
const TopOpportunitiesModal = lazy(() => import('./components/Modals/TopOpportunitiesModal'))
const SectorDrilldownModal = lazy(() => import('./components/Modals/SectorDrilldownModal'))
const MetricExplainerModal = lazy(() => import('./components/Modals/MetricExplainerModal'))

/* ── View Loading Skeleton ─────────────────────────────────────────────────── */
function ViewLoader({ label = 'Loading Workspace...' }) {
  return (
    <div
      className="flex flex-col items-center justify-center flex-1 h-full p-8 text-center"
      style={{ background: 'var(--color-surface)' }}
    >
      <div
        className="w-7 h-7 rounded-full border-2 border-t-transparent animate-spin mb-3"
        style={{ borderColor: 'var(--color-gold)', borderTopColor: 'transparent' }}
      />
      <span
        className="text-[11px] font-semibold tracking-wider font-mono uppercase"
        style={{ color: 'var(--color-muted)' }}
      >
        {label}
      </span>
    </div>
  )
}

/* ── Theme hook ─────────────────────────────────────────────────────────── */
function useTheme() {
  const [theme, setThemeState] = useState(() => {
    try { return localStorage.getItem('vt-theme') || 'dark' } catch { return 'dark' }
  })

  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('dark', 'light')
    root.classList.add(theme === 'light' ? 'light' : 'dark')
    try { localStorage.setItem('vt-theme', theme) } catch {}
  }, [theme])

  const toggle = useCallback(() => setThemeState((t) => (t === 'light' ? 'dark' : 'light')), [])
  return { theme, toggle }
}

/* ── Main App ───────────────────────────────────────────────────────────── */
export default function App() {
  const { setPort, setSidecarError, setBrokerStatuses, activeView, setActiveView } = useChatStore()
  const createSession = useChatStore((s) => s.createSession)
  const port = useChatStore((s) => s.port)
  const appMode = useChatStore((s) => s.appMode)
  const modeLoading = useChatStore((s) => s.modeLoading)
  const setAppMode = useChatStore((s) => s.setAppMode)
  const setModeLoading = useChatStore((s) => s.setModeLoading)
  const { theme, toggle: toggleTheme } = useTheme()
  const [pilotSafety, setPilotSafety] = useState(null)

  // Setup phase state machine — fast path: if terminal was already initialized, skip full boot screen
  const [setupPhase, setSetupPhase] = useState(() => {
    try {
      if (typeof window !== 'undefined' && localStorage.getItem('chanakya_setup_ready') === 'true') {
        return 'ready'
      }
    } catch (_) {}
    return 'initializing'
  })
  const [setupData, setSetupData] = useState(null)

  // Modal state
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false)
  const [isOrderTicketOpen, setIsOrderTicketOpen] = useState(false)
  const [orderTicketData, setOrderTicketData] = useState({
    symbol: 'RELIANCE', exchange: 'NSE', price: 2800, stopLoss: 2760, target: 2890,
  })
  const [isTopOppsOpen, setIsTopOppsOpen] = useState(false)
  const [sectorDrilldown, setSectorDrilldown] = useState({ isOpen: false, sector: null })
  const [showHotkeyRef, setShowHotkeyRef] = useState(false)

  // Per-view context state (passed to ContextBar)
  const [ctxSymbol, setCtxSymbol] = useState('NIFTY')
  const [ctxTimeframe, setCtxTimeframe] = useState('15m')
  const [ctxLayout, setCtxLayout] = useState('single')

  // ── Event listeners ──────────────────────────────────────────────────────
  useEffect(() => {
    const onOpenSector = (e) => {
      if (e.detail?.sector) setSectorDrilldown({ isOpen: true, sector: e.detail.sector })
    }
    const onOpenTop = () => setIsTopOppsOpen(true)
    const onCloseModals = () => {
      setIsCommandPaletteOpen(false)
      setIsTopOppsOpen(false)
      setSectorDrilldown({ isOpen: false, sector: null })
      setIsOrderTicketOpen(false)
    }
    window.addEventListener('open-sector-drilldown', onOpenSector)
    window.addEventListener('open-top-opportunities', onOpenTop)
    window.addEventListener('close-all-modals', onCloseModals)
    return () => {
      window.removeEventListener('open-sector-drilldown', onOpenSector)
      window.removeEventListener('open-top-opportunities', onOpenTop)
      window.removeEventListener('close-all-modals', onCloseModals)
    }
  }, [])

  // ── Sidecar / web init ───────────────────────────────────────────────────
  useEffect(() => {
    const isWeb = typeof window !== 'undefined' && (window.__CHANAKYA_TRADE_WEB__ || !window.electronAPI)
    if (isWeb) {
      const checkReady = async () => {
        const currentPort = parseInt(window.location.port, 10) === 5173
          ? 8765
          : parseInt(window.location.port, 10) || 8765
        setPort(currentPort)
        try {
          const res = await fetch(`${getBaseUrl(currentPort)}/api/onboarding/status`, {
            signal: AbortSignal.timeout(2000),
          })
          if (res.ok) {
            const data = await res.json()
            if (data?.onboarding_complete === false) {
              setSetupPhase('onboarding')
              try { localStorage.removeItem('chanakya_setup_ready') } catch (_) {}
            } else {
              setSetupPhase('ready')
              try { localStorage.setItem('chanakya_setup_ready', 'true') } catch (_) {}
            }
          } else {
            setSetupPhase('ready')
          }
        } catch {
          setSetupPhase('ready')
        }
      }
      checkReady()
      return
    }

    const safetyTimer = setTimeout(() => {
      setSetupPhase((prev) => (prev === 'initializing' ? 'ready' : prev))
    }, 600)

    window.electronAPI?.onSetupProgress((data) => {
      setSetupPhase('progress')
      setSetupData(data)
    })
    window.electronAPI?.onSetupPythonMissing((data) => {
      setSetupPhase('python_missing')
      setSetupData(data)
    })

    window.electronAPI?.onSidecarReady(async ({ port: p }) => {
      clearTimeout(safetyTimer)
      setPort(p)
      try {
        const res = await fetch(`${getBaseUrl(p)}/api/onboarding/status`, {
          signal: AbortSignal.timeout(2000),
        })
        const data = await res.json()
        if (data?.onboarding_complete === false) {
          setSetupPhase('onboarding')
          try { localStorage.removeItem('chanakya_setup_ready') } catch (_) {}
        } else {
          setSetupPhase('ready')
          try { localStorage.setItem('chanakya_setup_ready', 'true') } catch (_) {}
        }
      } catch {
        setSetupPhase('ready')
      }
    })

    window.electronAPI?.onSidecarError(({ message, details }) => {
      clearTimeout(safetyTimer)
      setSidecarError(message)
      if (setupPhase !== 'ready') {
        setSetupPhase('error')
        setSetupData({ message, details })
      }
    })

    window.electronAPI?.getPort?.()?.then(async (p) => {
      if (p) {
        clearTimeout(safetyTimer)
        setPort(p)
        try {
          const res = await fetch(`${getBaseUrl(p)}/api/onboarding/status`, {
            signal: AbortSignal.timeout(2000),
          })
          const data = await res.json()
          if (data?.onboarding_complete === false) {
            setSetupPhase('onboarding')
            try { localStorage.removeItem('chanakya_setup_ready') } catch (_) {}
          } else {
            setSetupPhase('ready')
            try { localStorage.setItem('chanakya_setup_ready', 'true') } catch (_) {}
          }
        } catch {
          setSetupPhase('ready')
        }
      }
    })

    return () => clearTimeout(safetyTimer)
  }, []) // eslint-disable-line

  // ── Status polling ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!port && port !== 0) return
    const fetchStatus = () =>
      fetch(`${getBaseUrl(port)}/api/status`).then((r) => r.json()).then(setBrokerStatuses).catch(() => {})
    fetchStatus()
    const t = setInterval(fetchStatus, 8000)
    return () => clearInterval(t)
  }, [port])

  // ── Fetch server-authoritative app mode (P0-A) ───────────────────────────────
  useEffect(() => {
    if (!port && port !== 0) return
    const fetchMode = async () => {
      setModeLoading(true)
      try {
        const res = await fetch(`${getBaseUrl(port)}/api/mode`)
        if (res.ok) {
          const data = await res.json()
          setAppMode(data.mode ?? 'PAPER')
        }
      } catch {
        // If endpoint is unavailable, keep default PAPER mode
        setModeLoading(false)
      }
    }
    fetchMode()
  }, [port]) // eslint-disable-line

  // ── Pilot guardrail visibility ────────────────────────────────────────────
  useEffect(() => {
    if (!port && port !== 0) return
    const fetchPilotSafety = () =>
      fetch(`${getBaseUrl(port)}/api/pilot/status`)
        .then((res) => (res.ok ? res.json() : null))
        .then(setPilotSafety)
        .catch(() => setPilotSafety(null))
    fetchPilotSafety()
    const timer = setInterval(fetchPilotSafety, 15000)
    return () => clearInterval(timer)
  }, [port])

  // ── Global keybindings ───────────────────────────────────────────────────
  useEffect(() => {
    function onKeyDown(e) {
      // ? → hotkey reference
      if (e.key === '?' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) {
        e.preventDefault()
        setShowHotkeyRef((v) => !v)
        return
      }
      if (e.metaKey || e.ctrlKey) {
        const handlers = {
          '1': () => setActiveView('terminal'),
          '2': () => setActiveView('debate'),
          '3': () => setActiveView('options'),
          '4': () => setActiveView('copilot'),
          '5': () => setActiveView('overview'),
          '6': () => setActiveView('portfolio'),
          '7': () => setActiveView('alerts'),
          '8': () => setActiveView('journal'),
          '9': () => setActiveView('backtest'),
          'b': () => setActiveView('backtest'),
          'n': () => createSession(),
          'k': () => setIsCommandPaletteOpen((v) => !v),
          'o': () => setIsTopOppsOpen((v) => !v),
          't': () => setIsOrderTicketOpen((v) => !v),
        }
        const key = e.key.toLowerCase()
        if (handlers[key]) {
          e.preventDefault()
          handlers[key]()
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [createSession, setActiveView])

  const handleOpenOrderTicket = useCallback((ticketData) => {
    if (ticketData) setOrderTicketData((prev) => ({ ...prev, ...ticketData }))
    setIsOrderTicketOpen(true)
  }, [])

  // ── Phase gates ──────────────────────────────────────────────────────────
  if (setupPhase === 'onboarding') {
    return (
      <Suspense fallback={<ViewLoader label="Loading Setup..." />}>
        <OnboardingWizard
          port={port}
          onComplete={() => {
            try { localStorage.setItem('chanakya_setup_ready', 'true') } catch (_) {}
            setSetupPhase('ready')
          }}
        />
      </Suspense>
    )
  }
  if (setupPhase !== 'ready') {
    return <SetupScreen phase={setupPhase} data={setupData} />
  }

  const isCopilot = activeView === 'copilot'
  const showContextBar = ['terminal', 'debate', 'options'].includes(activeView)

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--color-surface)' }}>

      {/* ── P0-A: Persistent Mode Banner ───────────────────────────── */}
      <ModeBanner mode={appMode} loading={modeLoading} pilotSafety={pilotSafety?.profile} />

      {/* ── Tier 1: Top Navigation Bar ──────────────────────────────────── */}
      <div
        className="drag flex items-center justify-between flex-shrink-0 px-3 gap-2 border-b"
        style={{
          height: '50px',
          background: 'var(--color-panel)',
          borderColor: 'var(--color-border)',
          backdropFilter: 'blur(12px)',
        }}
      >
        {/* Brand */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span
            className="text-base font-black font-ui hidden sm:inline"
            style={{ color: 'var(--color-text-dim)', letterSpacing: '0.02em' }}
          >
            ChanakyaTrade
          </span>
        </div>

        {/* Center: Workspace tabs */}
        <div
          className="no-drag flex items-center p-1 rounded-xl gap-0.5 text-xs"
          style={{ background: 'var(--color-elevated)', border: '1px solid var(--color-border)' }}
        >
          <WorkspaceTab id="terminal"  icon="📊" label="Terminal"    active={activeView === 'terminal'}  color="gold"     onClick={() => setActiveView('terminal')} shortcut="^1" />
          <WorkspaceTab id="debate"    icon="⚔️" label="Debate"      active={activeView === 'debate'}    color="emerald"  onClick={() => setActiveView('debate')} shortcut="^2" />
          <WorkspaceTab id="options"   icon="⚡" label="Options"     active={activeView === 'options'}   color="violet"   onClick={() => setActiveView('options')} shortcut="^3" />
          <WorkspaceTab id="copilot"   icon="💬" label="Copilot"     active={activeView === 'copilot'}   color="sapphire" onClick={() => setActiveView('copilot')} shortcut="^4" />
        </div>

        {/* Right: Status cluster */}
        <div className="no-drag flex items-center gap-1.5">
          <MarketClock />

          {/* Quick action: Opportunities Radar */}
          <button
            type="button"
            onClick={() => setIsTopOppsOpen(true)}
            className="hidden sm:flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer"
            style={{
              background: 'rgba(245,166,35,0.12)',
              border: '1px solid rgba(245,166,35,0.35)',
              color: 'var(--color-gold)',
            }}
            title="Opportunity Radar (Ctrl+O)"
          >
            🎯 <span className="hidden md:inline">Radar</span>
          </button>

          {/* Quick action: Order */}
          <button
            type="button"
            onClick={() => handleOpenOrderTicket()}
            className="hidden sm:flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer"
            style={{
              background: 'rgba(0,214,143,0.12)',
              border: '1px solid rgba(0,214,143,0.35)',
              color: 'var(--color-emerald)',
            }}
            title="Order Ticket (Ctrl+T)"
          >
            ⚡ <span className="hidden md:inline">Order</span>
          </button>

          {/* Search */}
          <button
            type="button"
            onClick={() => setIsCommandPaletteOpen(true)}
            className="hidden lg:flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-all cursor-pointer"
            style={{
              background: 'var(--color-elevated)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-muted)',
            }}
            title="Command Palette (Ctrl+K)"
          >
            <span>🔍</span>
            <span>Search…</span>
            <kbd
              className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold"
              style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)', color: 'var(--color-gold)' }}
            >
              ^K
            </kbd>
          </button>

          <ThemeToggle theme={theme} toggle={toggleTheme} />
          <StatusDot />
        </div>
      </div>

      {/* ── Tier 2: Context Bar (view-specific) ─────────────────────────── */}
      {showContextBar && (
        <ContextBar
          selectedSymbol={ctxSymbol}
          onSymbolChange={setCtxSymbol}
          timeframe={ctxTimeframe}
          onTimeframeChange={setCtxTimeframe}
          layoutMode={ctxLayout}
          onLayoutChange={setCtxLayout}
        />
      )}

      {/* ── Main Content Area ────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left Activity Bar — always present */}
        <ActivityBar alertCount={0} />

        {/* Copilot Sidebar */}
        {isCopilot && <Sidebar />}

        {/* View Container */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <ErrorBoundary title="Workspace View">
            <Suspense fallback={<ViewLoader label={`Loading ${activeView}...`} />}>
              {activeView === 'terminal' && (
                <TerminalView
                  onOpenOrderTicket={handleOpenOrderTicket}
                  externalSymbol={ctxSymbol}
                  onSymbolChange={setCtxSymbol}
                  externalTimeframe={ctxTimeframe}
                  onTimeframeChange={setCtxTimeframe}
                  externalLayout={ctxLayout}
                  onLayoutChange={setCtxLayout}
                />
              )}

              {activeView === 'debate' && (
                <DebateArenaView onOpenOrderTicket={handleOpenOrderTicket} />
              )}

              {activeView === 'options' && (
                <OptionsDeskView onOpenOrderTicket={handleOpenOrderTicket} />
              )}

              {activeView === 'copilot' && (
                <>
                  <ChatArea />
                  <InputBar />
                </>
              )}

              {activeView === 'overview'   && <OverviewView />}
              {activeView === 'portfolio'  && <PortfolioView onOpenOrderTicket={handleOpenOrderTicket} />}
              {activeView === 'journal'    && <JournalView />}
              {activeView === 'alerts'     && <AlertsView onOpenOrderTicket={handleOpenOrderTicket} />}
              {activeView === 'backtest'   && <BacktestStudioView onOpenOrderTicket={handleOpenOrderTicket} />}
              {activeView === 'settings'   && <SettingsPanel onClose={() => setActiveView('terminal')} />}
            </Suspense>
          </ErrorBoundary>
        </div>
      </div>

      {/* ── Global Modals (Lazy Loaded on Demand) ────────────────────────── */}
      <Suspense fallback={null}>
        <ErrorBoundary title="Command Palette">
          <CommandPalette
            isOpen={isCommandPaletteOpen}
            onClose={() => setIsCommandPaletteOpen(false)}
            onOpenOrderTicket={(data) => { setIsCommandPaletteOpen(false); handleOpenOrderTicket(data) }}
          />
        </ErrorBoundary>

        <ErrorBoundary title="Order Ticket">
          <OrderTicketModal
            isOpen={isOrderTicketOpen}
            onClose={() => setIsOrderTicketOpen(false)}
            initialData={orderTicketData}
            appMode={appMode}
          />
        </ErrorBoundary>

        <ErrorBoundary title="Opportunities Radar">
          <TopOpportunitiesModal
            isOpen={isTopOppsOpen}
            onClose={() => setIsTopOppsOpen(false)}
            onOpenOrderTicket={handleOpenOrderTicket}
          />
        </ErrorBoundary>

        <ErrorBoundary title="Sector Drilldown">
          <SectorDrilldownModal
            isOpen={sectorDrilldown.isOpen}
            sector={sectorDrilldown.sector}
            onClose={() => setSectorDrilldown({ isOpen: false, sector: null })}
            onOpenOrderTicket={handleOpenOrderTicket}
          />
        </ErrorBoundary>

        <ErrorBoundary title="Metric Explainer">
          <MetricExplainerModal />
        </ErrorBoundary>
      </Suspense>

      <ErrorBoundary title="Activity Monitor">
        <ActivityHUD />
      </ErrorBoundary>

      {/* ── Hotkey Reference Overlay (premium panel) ─────────────────────── */}
      <HotkeyPanel open={showHotkeyRef} onClose={() => setShowHotkeyRef(false)} />

      {/* ── Toast Notifications ──────────────────────────────────────────── */}
      <ToastContainer />
    </div>
  )
}

/* ── WorkspaceTab ───────────────────────────────────────────────────────── */
function WorkspaceTab({ icon, label, active, color, onClick, shortcut }) {
  const colorMap = {
    gold:     { bg: 'var(--color-gold)',    text: '#000', ring: 'rgba(245,166,35,0.4)' },
    emerald:  { bg: 'var(--color-emerald)', text: '#000', ring: 'rgba(0,214,143,0.4)' },
    violet:   { bg: 'var(--color-violet)',  text: '#fff', ring: 'rgba(157,125,255,0.4)' },
    sapphire: { bg: 'var(--color-sapphire)',text: '#fff', ring: 'rgba(77,155,255,0.4)' },
  }
  const c = colorMap[color] || colorMap.gold

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer"
      style={
        active
          ? { background: c.bg, color: c.text, fontWeight: 800, boxShadow: `0 1px 6px ${c.ring}` }
          : { color: 'var(--color-muted)' }
      }
      title={`${label} (${shortcut})`}
      onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = 'var(--color-text)' }}
      onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = 'var(--color-muted)' }}
    >
      <span className="text-sm leading-none">{icon}</span>
      <span className="hidden md:inline text-xs">{label}</span>
    </button>
  )
}

/* ── ThemeToggle ────────────────────────────────────────────────────────── */
function ThemeToggle({ theme, toggle }) {
  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggle}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer"
      style={{
        background: 'var(--color-elevated)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-muted)',
      }}
      title={`Theme: ${isDark ? 'Dark' : 'Light'} — Click to toggle`}
    >
      <span className="text-sm">{isDark ? '🌙' : '☀️'}</span>
      <span className="hidden sm:inline text-[11px]">{isDark ? 'Dark' : 'Light'}</span>
    </button>
  )
}

/* ── StatusDot ──────────────────────────────────────────────────────────── */
function StatusDot() {
  const { port, sidecarError } = useChatStore()
  const connected = !!port && !sidecarError

  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-ui"
      style={{ background: 'var(--color-panel)', border: '1px solid var(--color-border)' }}
      title={sidecarError ? `Error: ${sidecarError}` : connected ? 'API Connected' : 'Connecting…'}
    >
      <span
        className="w-2 h-2 rounded-full transition-all"
        style={{
          background: connected ? 'var(--color-emerald)' : 'var(--color-rose)',
          boxShadow: connected ? '0 0 6px rgba(0,214,143,0.7)' : '0 0 6px rgba(255,79,123,0.5)',
        }}
      />
      <span className="text-muted text-[11px]">
        {sidecarError ? 'Offline' : connected ? 'Live' : 'Starting…'}
      </span>
    </div>
  )
}

/* ── HotkeyReference ────────────────────────────────────────────────────── */
function HotkeyReference({ onClose }) {
  const hotkeys = [
    { key: '/ ', desc: 'Focus symbol search (in Terminal)' },
    { key: '^K', desc: 'Command palette' },
    { key: '^O', desc: 'Opportunity radar' },
    { key: '^T', desc: 'Order ticket' },
    { key: '^N', desc: 'New AI session' },
    { key: '^1', desc: 'Terminal view' },
    { key: '^2', desc: 'Debate Arena' },
    { key: '^3', desc: 'Options & GEX Desk' },
    { key: '^4', desc: 'AI Copilot' },
    { key: '^5', desc: 'Market Overview' },
    { key: '^6', desc: 'Portfolio Doctor' },
    { key: '^7', desc: 'Alerts Manager' },
    { key: '^8', desc: 'Trade Journal' },
    { key: '5 ', desc: '5m timeframe' },
    { key: '1 ', desc: '15m timeframe' },
    { key: 'D ', desc: '1D timeframe' },
    { key: 'Esc', desc: 'Close active modal' },
    { key: '? ', desc: 'This hotkey reference' },
  ]

  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center animate-slide-up-fade"
      style={{ background: 'rgba(3,4,10,0.88)', backdropFilter: 'blur(12px)' }}
      onClick={onClose}
    >
      <div
        className="modal-container p-6 w-[480px] max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold" style={{ color: 'var(--color-text)' }}>
            ⌨️ Keyboard Shortcuts
          </h2>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-xs font-bold cursor-pointer transition-colors"
            style={{ background: 'var(--color-elevated)', color: 'var(--color-muted)' }}
          >
            ✕
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {hotkeys.map(({ key, desc }) => (
            <div key={key + desc} className="flex items-center gap-3">
              <kbd
                className="flex-shrink-0 text-[11px] px-2 py-1 rounded-lg font-mono font-bold min-w-[40px] text-center"
                style={{
                  background: 'var(--color-elevated)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-gold)',
                }}
              >
                {key.trim()}
              </kbd>
              <span className="text-xs" style={{ color: 'var(--color-muted)' }}>{desc}</span>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-muted text-center mt-4">Press ? or Esc to close</p>
      </div>
    </div>
  )
}
