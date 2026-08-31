import { useChatStore } from '../../store/chatStore'

/**
 * ActivityBar — persistent left icon navigation rail (48px wide)
 * Always visible across all workspaces. Provides instant 1-click
 * access to all major views and utility panels.
 */

const WORKSPACE_ITEMS = [
  {
    id: 'terminal',
    icon: '📊',
    label: 'Strategic Quant Terminal',
    shortcut: '^1',
    accentColor: 'var(--color-gold)',
    accentBg: 'rgba(245, 166, 35, 0.15)',
  },
  {
    id: 'debate',
    icon: '⚔️',
    label: 'Multi-Agent Debate Arena',
    shortcut: '^2',
    accentColor: 'var(--color-emerald)',
    accentBg: 'rgba(0, 214, 143, 0.15)',
  },
  {
    id: 'options',
    icon: '⚡',
    label: 'Options & GEX Desk',
    shortcut: '^3',
    accentColor: 'var(--color-violet)',
    accentBg: 'rgba(157, 125, 255, 0.15)',
  },
  {
    id: 'copilot',
    icon: '💬',
    label: 'AI Copilot',
    shortcut: '^4',
    accentColor: 'var(--color-sapphire)',
    accentBg: 'rgba(77, 155, 255, 0.15)',
  },
]

const UTILITY_ITEMS = [
  { id: 'overview',   icon: '🌐', label: 'Market Overview',       shortcut: '^5' },
  { id: 'portfolio',  icon: '📈', label: 'Portfolio Doctor',      shortcut: '^6' },
  { id: 'alerts',     icon: '🔔', label: 'Alerts Manager',        shortcut: '^7' },
  { id: 'journal',    icon: '📋', label: 'Trade Journal',         shortcut: '^8' },
]

function ActivityBarIcon({ item, isActive, onClick, badge }) {
  const accent = item.accentColor || 'var(--color-gold)'
  const accentBg = item.accentBg || 'rgba(245, 166, 35, 0.15)'

  return (
    <div className="relative group no-drag">
      <button
        type="button"
        onClick={onClick}
        className="activity-bar-icon"
        style={
          isActive
            ? { background: accentBg, color: accent }
            : {}
        }
        title={`${item.label}  ${item.shortcut || ''}`}
        aria-label={item.label}
        aria-pressed={isActive}
      >
        {/* Active left indicator */}
        {isActive && (
          <span
            className="absolute left-[-4px] top-1/2 -translate-y-1/2 w-[3px] rounded-r-full"
            style={{
              height: '60%',
              background: accent,
              boxShadow: `0 0 8px ${accent}`,
            }}
          />
        )}

        <span className="text-lg leading-none select-none">{item.icon}</span>

        {/* Alert badge */}
        {badge > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full
              text-[9px] font-bold text-black flex items-center justify-center"
            style={{ background: 'var(--color-rose)' }}
          >
            {badge > 99 ? '99+' : badge}
          </span>
        )}
      </button>

      {/* Tooltip */}
      <div
        className="absolute left-full ml-3 top-1/2 -translate-y-1/2 pointer-events-none
          opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-[200]
          whitespace-nowrap"
        style={{ transitionDelay: '0.4s' }}
      >
        <div
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-semibold font-ui"
          style={{
            background: 'var(--color-elevated)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
            boxShadow: 'var(--shadow-float)',
          }}
        >
          {item.label}
          {item.shortcut && (
            <kbd
              className="text-[9px] px-1 py-0.5 rounded font-mono"
              style={{
                background: 'var(--color-highlight)',
                color: 'var(--color-muted)',
                border: '1px solid var(--color-border)',
              }}
            >
              {item.shortcut}
            </kbd>
          )}
        </div>
        {/* Arrow */}
        <div
          className="absolute right-full top-1/2 -translate-y-1/2 w-0 h-0"
          style={{
            borderTop: '5px solid transparent',
            borderBottom: '5px solid transparent',
            borderRight: '5px solid var(--color-border)',
            marginRight: '-1px',
          }}
        />
      </div>
    </div>
  )
}

export default function ActivityBar({ alertCount = 0 }) {
  const { activeView, setActiveView } = useChatStore()

  const handleNav = (id) => setActiveView(id)

  return (
    <div
      className="drag flex flex-col items-center justify-between flex-shrink-0 py-3 border-r border-border"
      style={{
        width: '52px',
        background: 'var(--color-panel)',
        userSelect: 'none',
      }}
      aria-label="Primary navigation"
      role="navigation"
    >
      {/* Top: Brand mark */}
      <div className="no-drag flex flex-col items-center gap-1 w-full">
        <button
          type="button"
          onClick={() => setActiveView('terminal')}
          className="activity-bar-icon animate-gold-pulse"
          title="ChanakyaTrade — Click for Terminal"
          aria-label="ChanakyaTrade home"
        >
          <span
            className="text-xl select-none"
            style={{
              color: 'var(--color-gold)',
              filter: 'drop-shadow(0 0 6px rgba(245,166,35,0.6))',
            }}
          >
            ◆
          </span>
        </button>

        {/* Separator */}
        <div
          className="w-6 h-px my-1"
          style={{ background: 'var(--color-border)' }}
        />

        {/* Primary workspaces */}
        <div className="flex flex-col items-center gap-1 w-full px-1">
          {WORKSPACE_ITEMS.map((item) => (
            <ActivityBarIcon
              key={item.id}
              item={item}
              isActive={activeView === item.id}
              onClick={() => handleNav(item.id)}
            />
          ))}
        </div>

        {/* Separator */}
        <div
          className="w-6 h-px my-1.5"
          style={{ background: 'var(--color-border)' }}
        />

        {/* Utility items */}
        <div className="flex flex-col items-center gap-1 w-full px-1">
          {UTILITY_ITEMS.map((item) => (
            <ActivityBarIcon
              key={item.id}
              item={item}
              isActive={activeView === item.id}
              onClick={() => handleNav(item.id)}
              badge={item.id === 'alerts' ? alertCount : 0}
            />
          ))}
        </div>
      </div>

      {/* Bottom: Settings */}
      <div className="no-drag flex flex-col items-center gap-1 w-full px-1">
        <div
          className="w-6 h-px mb-1"
          style={{ background: 'var(--color-border)' }}
        />
        <ActivityBarIcon
          item={{ id: 'settings', icon: '⚙️', label: 'Settings & Brokers', shortcut: '' }}
          isActive={activeView === 'settings'}
          onClick={() => handleNav('settings')}
        />
      </div>
    </div>
  )
}
