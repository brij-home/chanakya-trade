import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { INDIAN_UNIVERSE } from '../../data/universeData'
import { parseSearchQuery } from '../../utils/smartSearchParser'

/**
 * Institutional Smart Search Box with:
 * 1. Typeahead Popover with Keyboard Navigation (ArrowUp/Down, Enter, Tab, Esc)
 * 2. Active Radar & Feed Symbols suggestion with live setup count & stage badge
 * 3. 500+ NSE/BSE Universe Tickers & Company Aliases (e.g. "reliance" -> RELIANCE, "zomato" -> ETERNAL)
 * 4. Power-User Syntax Directives (sym:, strike:, rr:>3, score:>80, dir:bull, stage:ignited)
 * 5. Recent Searches persistence via localStorage with 1-click clearance
 * 6. Quick-Launch Smart Filter Pills on zero-query focus
 */

const QUICK_DIRECTIVE_PRESETS = [
  { label: '🔥 Ignited (In-Flight)', query: 'stage:ignited', desc: 'Active momentum setups executing right now' },
  { label: '⭐ Score 85+ (Elite)', query: 'score:>85', desc: 'Highest quantitative conviction threshold' },
  { label: '🎯 Asymmetric R:R ≥ 3.0', query: 'rr:>3', desc: 'Minimum 1:3 risk-to-reward asymmetry' },
  { label: '📈 Bullish Setups', query: 'dir:bull', desc: 'Long Call & Cash equity signals' },
  { label: '📉 Bearish Setups', query: 'dir:bear', desc: 'Short Put & Bearish breakout signals' },
  { label: '⚡ Gamma Blast', query: 'cat:gamma', desc: 'Unusual options order book compression' },
]

export default function SmartSearchBox({
  value = '',
  onChange,
  placeholder = '🔍 Symbol, strike, or rr:>3…',
  activeItems = [],
  universe = INDIAN_UNIVERSE,
  recentStorageKey = 'chanakya_smart_search_recent_v1',
  colorTheme = 'gold',
  className = '',
  id = 'smart-search-box',
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(0)
  const [recentSearches, setRecentSearches] = useState([])

  const containerRef = useRef(null)
  const inputRef = useRef(null)

  // Color theme map
  const themeStyles = {
    gold: {
      borderFocus: 'focus:border-gold',
      pillActive: 'bg-gold/15 text-amber-500 dark:text-amber-300 border-gold/40',
      highlight: 'bg-gold/15 text-amber-400',
      badge: 'bg-gold/20 text-amber-300',
    },
    emerald: {
      borderFocus: 'focus:border-emerald-500',
      pillActive: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border-emerald-500/40',
      highlight: 'bg-emerald-500/15 text-emerald-400',
      badge: 'bg-emerald-500/20 text-emerald-300',
    },
    sky: {
      borderFocus: 'focus:border-sky-500',
      pillActive: 'bg-sky-500/15 text-sky-600 dark:text-sky-300 border-sky-500/40',
      highlight: 'bg-sky-500/15 text-sky-400',
      badge: 'bg-sky-500/20 text-sky-300',
    },
  }[colorTheme] || {
    borderFocus: 'focus:border-gold',
    pillActive: 'bg-gold/15 text-amber-500 dark:text-amber-300 border-gold/40',
    highlight: 'bg-gold/15 text-amber-400',
    badge: 'bg-gold/20 text-amber-300',
  }

  // Load recent searches from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(recentStorageKey)
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed)) setRecentSearches(parsed.slice(0, 5))
      }
    } catch (_) {}
  }, [recentStorageKey])

  // Save recent search
  const saveRecent = useCallback((queryToSave) => {
    const q = (queryToSave || '').trim()
    if (!q || q.length < 2) return
    setRecentSearches((prev) => {
      const filtered = prev.filter((item) => item.toLowerCase() !== q.toLowerCase())
      const next = [q, ...filtered].slice(0, 5)
      try {
        localStorage.setItem(recentStorageKey, JSON.stringify(next))
      } catch (_) {}
      return next
    })
  }, [recentStorageKey])

  const removeRecent = useCallback((e, itemToRemove) => {
    e.stopPropagation()
    setRecentSearches((prev) => {
      const next = prev.filter((item) => item !== itemToRemove)
      try {
        localStorage.setItem(recentStorageKey, JSON.stringify(next))
      } catch (_) {}
      return next
    })
  }, [recentStorageKey])

  // Detect active directives in current value
  const parsedCurrent = useMemo(() => parseSearchQuery(value), [value])

  // Aggregate active symbols and option contracts from activeItems
  const activeFeedsMap = useMemo(() => {
    const symMap = new Map()
    const strikesSet = new Set()

    if (Array.isArray(activeItems)) {
      for (const item of activeItems) {
        if (!item) continue
        const sym = String(item.symbol || '').replace(/^(NSE|BSE|MCX|NFO|CDS|CRYPTO):/i, '').toUpperCase()
        if (sym && sym !== 'UNKNOWN') {
          if (!symMap.has(sym)) {
            symMap.set(sym, {
              count: 0,
              stage: item.stage || item.target_status || 'ACTIVE',
              direction: item.direction || 'BULLISH',
            })
          }
          const entry = symMap.get(sym)
          entry.count++
          if (item.stage === 'IGNITED') entry.stage = 'IGNITED'
          else if (item.stage === 'PRIMED' && entry.stage !== 'IGNITED') entry.stage = 'PRIMED'
        }

        const contract = item.contract_symbol || item.actionable_plan?.option_plan?.contract_symbol
        if (contract && typeof contract === 'string') {
          strikesSet.add(contract.toUpperCase())
        }
      }
    }

    return {
      symbols: Array.from(symMap.entries()).map(([symbol, data]) => ({ symbol, ...data })),
      contracts: Array.from(strikesSet),
    }
  }, [activeItems])

  // Compute suggestions based on query
  const suggestions = useMemo(() => {
    const trimmed = (value || '').trim()
    const cleanLower = trimmed.toLowerCase()

    // ── STATE 1: Empty Query Suggestions (Zero-Query state) ──────────────
    if (!trimmed) {
      const list = []

      // Quick Directive Presets
      for (const preset of QUICK_DIRECTIVE_PRESETS) {
        list.push({
          type: 'preset',
          category: 'Quick Directives',
          label: preset.label,
          query: preset.query,
          desc: preset.desc,
          icon: '⚡',
        })
      }

      // Top Active Symbols from current radar
      const topActive = activeFeedsMap.symbols.slice(0, 4)
      for (const s of topActive) {
        list.push({
          type: 'active_symbol',
          category: 'Active on Radar',
          label: `${s.symbol} (${s.count} setup${s.count > 1 ? 's' : ''})`,
          query: `sym:${s.symbol}`,
          badge: s.stage,
          icon: '🏷️',
        })
      }

      return list
    }

    // ── STATE 2: Typing Suggestions ──────────────────────────────────────
    const list = []

    // 1. Directives Autocomplete Helper (if user started typing a directive key)
    if (cleanLower.startsWith('rr:') || cleanLower === 'rr') {
      list.push(
        { type: 'syntax', category: 'Syntax Helper', label: 'rr:>2.0 (Minimum 1:2 R:R)', query: 'rr:>2.0', icon: '🎯' },
        { type: 'syntax', category: 'Syntax Helper', label: 'rr:>3.0 (Asymmetric 1:3+ R:R)', query: 'rr:>3.0', icon: '🎯' },
        { type: 'syntax', category: 'Syntax Helper', label: 'rr:>4.0 (Runner 1:4+ R:R)', query: 'rr:>4.0', icon: '🎯' }
      )
    } else if (cleanLower.startsWith('score:') || cleanLower === 'score' || cleanLower.startsWith('conf:')) {
      list.push(
        { type: 'syntax', category: 'Syntax Helper', label: 'score:>75 (Strong Setup)', query: 'score:>75', icon: '⭐' },
        { type: 'syntax', category: 'Syntax Helper', label: 'score:>85 (Elite Conviction)', query: 'score:>85', icon: '⭐' }
      )
    } else if (cleanLower.startsWith('dir:') || cleanLower === 'dir') {
      list.push(
        { type: 'syntax', category: 'Syntax Helper', label: 'dir:bull (Bullish / Call setups)', query: 'dir:bull', icon: '📈' },
        { type: 'syntax', category: 'Syntax Helper', label: 'dir:bear (Bearish / Put setups)', query: 'dir:bear', icon: '📉' }
      )
    } else if (cleanLower.startsWith('stage:') || cleanLower === 'stage') {
      list.push(
        { type: 'syntax', category: 'Syntax Helper', label: 'stage:ignited (In-flight breakouts)', query: 'stage:ignited', icon: '🔥' },
        { type: 'syntax', category: 'Syntax Helper', label: 'stage:primed (Near trigger pivot)', query: 'stage:primed', icon: '🎯' },
        { type: 'syntax', category: 'Syntax Helper', label: 'stage:stalk (Radar candidate)', query: 'stage:stalk', icon: '🦅' },
        { type: 'syntax', category: 'Syntax Helper', label: 'stage:target (Targets hit / T1)', query: 'stage:target', icon: '🎯' }
      )
    }

    // 2. Active Symbols match (from current feed)
    const matchingActive = activeFeedsMap.symbols.filter(
      (s) => s.symbol.toLowerCase().includes(cleanLower) || cleanLower.includes(s.symbol.toLowerCase())
    )
    for (const s of matchingActive.slice(0, 4)) {
      list.push({
        type: 'active_symbol',
        category: 'Active on Radar',
        label: s.symbol,
        subLabel: `${s.count} setup${s.count > 1 ? 's' : ''} in feed`,
        query: `sym:${s.symbol}`,
        badge: s.stage,
        icon: '🏷️',
      })
    }

    // 3. Indian Universe Equity / Index match (with name, sector, aliases)
    if (Array.isArray(universe)) {
      let uMatches = 0
      for (const item of universe) {
        if (uMatches >= 6) break
        const sym = item.symbol.toUpperCase()
        const symMatch = sym.toLowerCase().includes(cleanLower)
        const nameMatch = item.name?.toLowerCase().includes(cleanLower)
        let aliasMatch = null
        if (Array.isArray(item.aliases)) {
          for (const al of item.aliases) {
            if (al.toLowerCase().includes(cleanLower)) {
              aliasMatch = al
              break
            }
          }
        }

        if (symMatch || nameMatch || aliasMatch) {
          list.push({
            type: 'universe',
            category: 'NSE/BSE Universe',
            label: sym,
            subLabel: `${item.name || item.sector} ${item.lotSize ? `• Lot ${item.lotSize}` : ''}${
              aliasMatch ? ` (matched "${aliasMatch}")` : ''
            }`,
            query: `sym:${sym}`,
            badge: item.sector,
            icon: item.type === 'index' ? '🏛️' : item.type === 'commodity' ? '🛢️' : '🏢',
          })
          uMatches++
        }
      }
    }

    // 4. Active Option Contracts match
    const matchingContracts = activeFeedsMap.contracts.filter((c) => c.toLowerCase().includes(cleanLower))
    for (const c of matchingContracts.slice(0, 3)) {
      list.push({
        type: 'contract',
        category: 'Option Contract',
        label: c,
        query: `strike:${c}`,
        icon: '🎯',
      })
    }

    return list
  }, [value, activeFeedsMap, universe])

  // Keep highlighted index in bounds
  useEffect(() => {
    setHighlightedIndex(0)
  }, [suggestions.length, value])

  // Select a suggestion item
  const handleSelectSuggestion = useCallback(
    (item) => {
      const q = item.query || item.label
      onChange(q)
      saveRecent(q)
      setIsOpen(false)
      inputRef.current?.blur()
    },
    [onChange, saveRecent]
  )

  // Keyboard navigation inside input
  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!isOpen) {
        setIsOpen(true)
        return
      }
      setHighlightedIndex((prev) => (prev + 1) % (suggestions.length || 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!isOpen) {
        setIsOpen(true)
        return
      }
      setHighlightedIndex((prev) => (prev - 1 + (suggestions.length || 1)) % (suggestions.length || 1))
    } else if (e.key === 'Tab') {
      if (isOpen && suggestions[highlightedIndex]) {
        e.preventDefault()
        const selected = suggestions[highlightedIndex]
        onChange(selected.query || selected.label)
      }
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (isOpen && suggestions[highlightedIndex]) {
        handleSelectSuggestion(suggestions[highlightedIndex])
      } else {
        saveRecent(value)
        setIsOpen(false)
      }
    } else if (e.key === 'Escape') {
      setIsOpen(false)
    }
  }

  // Outside click listener
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('touchstart', handleOutsideClick)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('touchstart', handleOutsideClick)
    }
  }, [])

  // Global '/' keyboard listener to focus search box
  useEffect(() => {
    const handleGlobalSlash = (e) => {
      if (e.key === '/' && document.activeElement !== inputRef.current) {
        const tag = document.activeElement?.tagName
        if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
          e.preventDefault()
          inputRef.current?.focus()
          setIsOpen(true)
        }
      }
    }
    window.addEventListener('keydown', handleGlobalSlash)
    return () => window.removeEventListener('keydown', handleGlobalSlash)
  }, [])

  // Clear query button
  const handleClear = () => {
    onChange('')
    setIsOpen(true)
    inputRef.current?.focus()
  }

  return (
    <div ref={containerRef} className={`relative flex items-center ${isOpen ? 'z-[9999]' : 'z-auto'} ${className}`}>
      {/* Search Input Container */}
      <div className="relative w-full flex items-center">
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-autocomplete="list"
          value={value}
          onFocus={() => setIsOpen(true)}
          onChange={(e) => {
            onChange(e.target.value)
            if (!isOpen) setIsOpen(true)
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className={`w-full text-xs pl-2.5 pr-14 py-1 rounded-lg bg-surface border border-border text-text placeholder:text-muted focus:outline-none ${themeStyles.borderFocus} transition-colors font-sans shadow-2xs`}
        />

        {/* Right side controls: Clear '✕' + Shortcut hint '/' */}
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5 pointer-events-none">
          {value ? (
            <button
              type="button"
              onClick={handleClear}
              className="pointer-events-auto text-muted hover:text-text text-xs cursor-pointer px-1 py-0.5 rounded hover:bg-elevated transition-colors"
              title="Clear search (Esc)"
            >
              ✕
            </button>
          ) : (
            <kbd className="text-[10px] font-mono px-1 py-0.2 rounded bg-elevated border border-border/80 text-muted/80 shadow-2xs">
              /
            </kbd>
          )}
        </div>
      </div>

      {/* Floating Typeahead Popover */}
      {isOpen && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-1.5 w-80 sm:w-96 max-h-96 overflow-y-auto rounded-xl border shadow-2xl z-[9999] divide-y divide-border/60 text-xs select-none"
          style={{
            backgroundColor: 'var(--color-panel, #0d1320)',
            borderColor: 'var(--color-border, #182236)',
            boxShadow: '0 20px 50px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.08)',
          }}
        >
          {/* Recent Searches (if query is empty or matches) */}
          {recentSearches.length > 0 && !value.trim() && (
            <div className="p-2" style={{ backgroundColor: 'var(--color-surface, #090d16)' }}>
              <div className="flex items-center justify-between text-[10px] uppercase font-mono text-muted mb-1 px-1">
                <span>🕒 Recent Searches</span>
                <span className="text-[9px] text-muted/60">1-click restore</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {recentSearches.map((item) => (
                  <div
                    key={item}
                    onClick={() => {
                      onChange(item)
                      setIsOpen(false)
                    }}
                    className="group inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-elevated hover:bg-surface border border-border text-[11px] text-text cursor-pointer transition-all hover:border-gold/50"
                  >
                    <span>{item}</span>
                    <button
                      type="button"
                      onClick={(e) => removeRecent(e, item)}
                      className="text-muted/60 hover:text-rose-400 text-[10px] cursor-pointer"
                      title="Remove from history"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggestions List Grouped by Category */}
          {suggestions.length > 0 ? (
            <div className="py-1">
              {(() => {
                let lastCategory = null
                return suggestions.map((item, idx) => {
                  const isSelected = idx === highlightedIndex
                  const showCategoryHeader = item.category && item.category !== lastCategory
                  if (item.category) lastCategory = item.category

                  return (
                    <div key={`${item.type}-${item.query || item.label}-${idx}`}>
                      {showCategoryHeader && (
                        <div
                          className="px-3 pt-2 pb-1 text-[10px] uppercase font-mono font-bold tracking-wider text-muted border-b border-border/40"
                          style={{ backgroundColor: 'var(--color-surface, #090d16)' }}
                        >
                          {item.category}
                        </div>
                      )}
                      <div
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => handleSelectSuggestion(item)}
                        onMouseEnter={() => setHighlightedIndex(idx)}
                        className={`flex items-center justify-between px-3 py-1.5 cursor-pointer transition-colors ${
                          isSelected ? `${themeStyles.highlight} font-semibold` : 'text-text hover:bg-elevated'
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xs flex-shrink-0">{item.icon || '🔍'}</span>
                          <div className="flex flex-col min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="text-xs truncate font-medium">{item.label}</span>
                              {item.query && item.type !== 'preset' && (
                                <code className="text-[10px] font-mono text-muted px-1 rounded bg-black/20 dark:bg-white/10">
                                  {item.query}
                                </code>
                              )}
                            </div>
                            {(item.subLabel || item.desc) && (
                              <span className="text-[10px] text-muted truncate">
                                {item.subLabel || item.desc}
                              </span>
                            )}
                          </div>
                        </div>

                        {item.badge && (
                          <span
                            className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-md flex-shrink-0 ml-2 ${
                              item.badge === 'IGNITED'
                                ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                                : item.badge === 'PRIMED'
                                ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                                : 'bg-elevated text-muted border border-border'
                            }`}
                          >
                            {item.badge}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })
              })()}
            </div>
          ) : (
            <div className="p-3 text-center text-xs text-muted">
              <span>No direct ticker match. Press </span>
              <kbd className="px-1 py-0.5 rounded bg-elevated border border-border text-[10px] font-mono">Enter</kbd>
              <span> to free-search across all setups.</span>
            </div>
          )}

          {/* Footer Guide for Power-User Directives */}
          <div
            className="px-3 py-1.5 flex items-center justify-between text-[10px] font-mono text-muted border-t border-border/60 rounded-b-xl"
            style={{ backgroundColor: 'var(--color-surface, #090d16)' }}
          >
            <div className="flex items-center gap-1.5">
              <span>Directives:</span>
              <code className="text-text font-bold">sym:</code>
              <code className="text-text font-bold">{'rr:>3'}</code>
              <code className="text-text font-bold">{'score:>80'}</code>
              <code className="text-text font-bold">dir:bull</code>
            </div>
            <div className="flex items-center gap-1">
              <span>Navigate</span>
              <kbd className="px-1 rounded bg-elevated border border-border">↑↓</kbd>
              <span>Select</span>
              <kbd className="px-1 rounded bg-elevated border border-border">↵</kbd>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
