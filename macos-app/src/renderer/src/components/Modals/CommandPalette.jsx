import { useState, useEffect, useRef } from 'react'
import { useChatStore, getActiveSymbol } from '../../store/chatStore'
import { fuzzySearchUniverse, saveRecentSearch } from '../../data/universeData'

export default function CommandPalette({ isOpen, onClose }) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [categoryFilter, setCategoryFilter] = useState('all')
  const sendDraft = useChatStore((s) => s.sendDraft)
  const messages = useChatStore((s) => s.messages)
  const activeSymbol = getActiveSymbol(messages)
  const inputRef = useRef(null)

  // Focus input on open
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      setCategoryFilter('all')
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  if (!isOpen) return null

  // Search universe data with category filter
  const results = fuzzySearchUniverse(query, activeSymbol, 14, categoryFilter)

  const executeQuery = (text) => {
    const cleanText = (text || query).trim()
    if (!cleanText) return
    saveRecentSearch({
      text: cleanText,
      symbol: activeSymbol || null,
      label: cleanText,
      icon: '⚡',
    })
    sendDraft(cleanText)
    onClose()
  }

  const selectItem = (item) => {
    const cmdToRun = item.command || (item.symbol ? `analyze ${item.symbol}` : item.text || item.label)
    saveRecentSearch({
      text: cmdToRun,
      symbol: item.symbol || null,
      label: item.symbol ? `${item.symbol} (${item.name || item.sector})` : (item.label || item.name),
      icon: item.icon || '🔍',
    })
    sendDraft(cmdToRun)
    onClose()
  }

  const handleFormSubmit = (e) => {
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }
    const cleanQuery = query.trim()
    const item = results[selectedIndex]
    if (item && selectedIndex >= 0 && selectedIndex < results.length) {
      selectItem(item)
    } else if (cleanQuery) {
      executeQuery(cleanQuery)
    }
  }

  // Keyboard navigation handler
  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((idx) => (idx + 1) % (results.length || 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((idx) => (idx - 1 + (results.length || 1)) % (results.length || 1))
    } else if (e.key === 'Tab') {
      e.preventDefault()
      const item = results[selectedIndex]
      if (item) {
        setQuery(item.command || item.symbol || item.text || item.label || '')
      }
    } else if (e.key === 'Enter') {
      e.preventDefault()
      handleFormSubmit()
    } else if (e.key === 'Escape') {
      onClose()
    }
  }

  const categories = [
    { id: 'all', label: 'All' },
    { id: 'stock', label: 'Stocks' },
    { id: 'index', label: 'Indices' },
    { id: 'etf', label: 'ETFs' },
    { id: 'commodity', label: 'Commodities' },
    { id: 'currency', label: 'Currencies' },
    { id: 'council', label: 'Councils' },
    { id: 'persona', label: 'Personas' },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/60 backdrop-blur-md p-4 select-none animate-fade-slide"
      onClick={onClose}
    >
      <div
        className="bg-panel border border-border/80 rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl font-ui"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Bar Form */}
        <form
          onSubmit={handleFormSubmit}
          className="flex items-center gap-2.5 px-4 py-3.5 border-b border-border/60 bg-panel/40"
        >
          <span className="text-amber text-base flex-shrink-0">🔍</span>
          <input
            ref={inputRef}
            type="text"
            placeholder="OmniSearch: Stock name, index, ETF, MCX commodity, council, persona... (e.g. BAJAJ-AUTO, GOLDBEES, CRUDEOIL, breakout)"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleKeyDown}
            className="w-full bg-transparent border-none outline-none text-text text-sm font-ui placeholder:text-muted"
          />
          {query.trim() ? (
            <button
              type="submit"
              onMouseDown={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              onClick={handleFormSubmit}
              className="px-2.5 py-1 rounded-lg bg-amber hover:bg-amber-light active:scale-95 text-black font-ui font-bold text-xs cursor-pointer transition-all shadow-xs flex-shrink-0 flex items-center gap-1"
              title="Execute command immediately"
            >
              <span>Send</span>
              <span>↵</span>
            </button>
          ) : (
            <kbd className="hidden sm:inline text-[10px] bg-panel border border-border px-1.5 py-0.5 rounded text-muted flex-shrink-0">
              ESC
            </kbd>
          )}
        </form>

        {/* Category Filter Pills */}
        <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border/40 bg-surface/50 overflow-x-auto no-scrollbar">
          {categories.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              onClick={() => {
                setCategoryFilter(cat.id)
                setSelectedIndex(0)
              }}
              className={`px-2 py-0.5 rounded-lg text-[10px] font-mono font-bold tracking-tight whitespace-nowrap cursor-pointer transition-all ${
                categoryFilter === cat.id
                  ? 'bg-amber text-black font-black shadow-xs'
                  : 'bg-panel text-muted hover:text-text border border-border/40'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* Results List */}
        <div className="max-h-84 overflow-y-auto p-2 space-y-0.5">
          {results.map((item, idx) => {
            const isSelected = selectedIndex === idx
            const isStock = item.type === 'symbol'
            const isCouncil = item.type === 'council'
            const isPersona = item.type === 'persona'
            const isRecent = item.category === 'recent'
            const stockType = item.stockType || item.category

            return (
              <button
                key={idx}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                }}
                onClick={() => selectItem(item)}
                className={`w-full flex items-center justify-between p-2.5 rounded-xl text-left text-xs transition-all cursor-pointer ${
                  isSelected ? 'bg-amber/15 text-text border border-amber/40 shadow-xs' : 'text-text hover:bg-panel/60 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div
                    className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm flex-shrink-0 border ${
                      isSelected ? 'bg-amber/20 border-amber/50 text-amber' : 'bg-surface border-border/70'
                    }`}
                  >
                    {item.icon || (isStock ? '🏢' : isCouncil ? '🏛️' : isPersona ? '🧠' : '⚡')}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-bold text-xs text-text font-mono truncate">
                        {isStock ? item.symbol : (item.label || item.name || item.text)}
                      </span>

                      {isStock && item.sector && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-surface border border-border/60 text-muted">
                          {item.sector}
                        </span>
                      )}

                      {isStock && item.lotSize && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-surface border border-border/60 text-muted hidden sm:inline-block">
                          Lot {item.lotSize}
                        </span>
                      )}

                      {isStock && stockType === 'index' && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                          INDEX
                        </span>
                      )}

                      {isStock && stockType === 'etf' && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-sky-500/15 border border-sky-500/30 text-sky-400">
                          ETF
                        </span>
                      )}

                      {isStock && stockType === 'commodity' && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-amber-500/15 border border-amber-500/30 text-amber">
                          MCX
                        </span>
                      )}

                      {isStock && stockType === 'currency' && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-violet-500/15 border border-violet-500/30 text-violet-400">
                          FOREX
                        </span>
                      )}

                      {isCouncil && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-blue-500/15 border border-blue-500/30 text-blue-400">
                          COUNCIL
                        </span>
                      )}

                      {isPersona && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-purple-500/15 border border-purple-500/30 text-purple-400">
                          PERSONA
                        </span>
                      )}

                      {isRecent && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-amber/15 border border-amber/30 text-amber">
                          RECENT
                        </span>
                      )}
                    </div>

                    <span className="text-[11px] text-muted block truncate font-ui">
                      {item.name || item.desc || item.usage || item.command || ''}
                    </span>
                  </div>
                </div>

                <code className="text-[10px] text-amber bg-panel px-2 py-0.5 rounded font-mono border border-border/50 flex-shrink-0 ml-2 hidden sm:inline-block">
                  {item.command || item.text || (item.symbol ? `analyze ${item.symbol}` : '')}
                </code>
              </button>
            )
          })}

          {results.length === 0 && query.trim() && (
            <div className="p-3 text-center">
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                }}
                onClick={() => executeQuery(query.trim())}
                className="w-full flex items-center justify-between p-3 rounded-xl bg-amber/15 hover:bg-amber/25 border border-amber/40 text-left transition-all cursor-pointer group shadow-sm"
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-lg">⚡</span>
                  <div>
                    <p className="text-xs font-semibold text-text group-hover:text-amber">
                      Execute Custom Prompt or Command
                    </p>
                    <p className="text-xs font-mono text-amber font-bold">{query.trim()}</p>
                  </div>
                </div>
                <span className="text-xs font-bold bg-amber text-black px-2.5 py-1 rounded-lg">Execute ↵</span>
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-border/40 bg-panel/40 flex items-center justify-between text-[10px] text-muted font-ui">
          <span>Navigate with <kbd className="bg-panel px-1 rounded border border-border">↑</kbd> <kbd className="bg-panel px-1 rounded border border-border">↓</kbd></span>
          <span>Complete with <kbd className="bg-panel px-1 rounded border border-border">Tab</kbd></span>
          <span>Execute with <kbd className="bg-panel px-1 rounded border border-border">↵ Enter</kbd></span>
        </div>
      </div>
    </div>
  )
}
