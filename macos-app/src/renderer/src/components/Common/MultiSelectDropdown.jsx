import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { ChevronDown, Check, X, Search, CheckSquare, Square } from 'lucide-react'

/**
 * MultiSelectDropdown — Institutional Bloomberg / Excel-Style Multi-Select Filter Component.
 * 
 * Features:
 * - Instant reactive filtering with multi-checkbox selection
 * - In-menu search filtering with auto-focus
 * - Excel-style "Select All" and "Clear" quick actions
 * - Instant Solo "only" action on row hover to isolate a single criterion in 1 click
 * - Tabular monospace count badges per option
 * - Quick reset (✕) directly on trigger button when filtered
 * - Keyboard accessible (Escape dismiss, tab navigation)
 * - Outside click listener with memory cleanup
 */
export default function MultiSelectDropdown({
  title = 'Filter',
  options = [],
  selected = new Set(),
  onChange,
  allLabel,
  icon = null,
  searchPlaceholder,
  enableSearch = null, // auto-enabled if options.length >= 6
  align = 'left',
  colorTheme = 'gold', // 'gold' | 'sky' | 'emerald' | 'amber' | 'sapphire' | 'rose'
  size = 'sm', // 'sm' | 'xs' | 'md'
  className = '',
  triggerClassName = '',
  maxDisplayLength = 22,
  disabled = false,
  titlePrefix = '',
  hiddenSelectTitle = '',
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const containerRef = useRef(null)
  const searchInputRef = useRef(null)

  // Normalize selected prop to a Set of strings
  const selectedSet = useMemo(() => {
    if (!selected) return new Set()
    if (selected instanceof Set) return new Set(selected)
    if (Array.isArray(selected)) return new Set(selected)
    if (typeof selected === 'string') {
      return selected === 'ALL' || selected === '' ? new Set() : new Set([selected])
    }
    return new Set()
  }, [selected])

  // Determine if "All" is active (either empty set, set containing 'ALL', or all options included)
  const isAll = useMemo(() => {
    if (selectedSet.size === 0 || selectedSet.has('ALL')) return true
    if (options.length > 0 && selectedSet.size >= options.length) return true
    return false
  }, [selectedSet, options.length])

  // Auto-enable search if more than 5 options
  const shouldShowSearch = enableSearch !== null ? enableSearch : options.length >= 6

  // Close on outside click or Escape
  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false)
        setSearchQuery('')
      }
    }

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        setIsOpen(false)
        setSearchQuery('')
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  // Focus search input on open
  useEffect(() => {
    if (isOpen && shouldShowSearch) {
      const timer = setTimeout(() => {
        searchInputRef.current?.focus()
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [isOpen, shouldShowSearch])

  // Filtered options based on in-menu search
  const filteredOptions = useMemo(() => {
    if (!searchQuery.trim()) return options
    const q = searchQuery.toLowerCase().trim()
    return options.filter((opt) => {
      const label = String(opt.label || opt.value || '').toLowerCase()
      const val = String(opt.value || '').toLowerCase()
      return label.includes(q) || val.includes(q)
    })
  }, [options, searchQuery])

  // Toggle single option
  const handleToggleOption = useCallback((val) => {
    if (isAll) {
      // If currently ALL, checking an option solos that option (instant intuitive filter)
      const next = new Set([val])
      onChange?.(next)
      return
    }

    const next = new Set(selectedSet)
    if (next.has(val)) {
      next.delete(val)
      // If no options remain selected, reset back to ALL
      if (next.size === 0) {
        onChange?.(new Set())
        return
      }
    } else {
      next.add(val)
      // If all options are now selected, reset back to ALL
      if (options.length > 0 && next.size >= options.length) {
        onChange?.(new Set())
        return
      }
    }
    onChange?.(next)
  }, [isAll, selectedSet, options.length, onChange])

  // Solo "only" action: immediately select ONLY this option
  const handleSoloOption = useCallback((e, val) => {
    e.stopPropagation()
    const next = new Set([val])
    onChange?.(next)
  }, [onChange])

  // Select All action: resets to ALL
  const handleSelectAll = useCallback(() => {
    onChange?.(new Set())
  }, [onChange])

  // Clear All action: clears selection
  const handleClear = useCallback(() => {
    // When user explicitly clicks "Clear", reset to empty/all
    onChange?.(new Set())
  }, [onChange])

  // Reset from trigger button (✕ icon)
  const handleQuickReset = useCallback((e) => {
    e.stopPropagation()
    onChange?.(new Set())
  }, [onChange])

  // Theme styling configurations
  const themeStyles = {
    gold: {
      activeTrigger: 'border-amber-400 text-amber-300 font-bold bg-amber-500/10 shadow-xs',
      activeBadge: 'bg-amber-400/20 text-amber-300 border-amber-400/40',
      activeCheckbox: 'bg-amber-400 text-black border-amber-400',
      hoverHighlight: 'hover:bg-amber-500/10',
      focusRing: 'focus:border-amber-400',
    },
    sky: {
      activeTrigger: 'border-sky-400 text-sky-300 font-bold bg-sky-500/10 shadow-xs',
      activeBadge: 'bg-sky-400/20 text-sky-300 border-sky-400/40',
      activeCheckbox: 'bg-sky-400 text-white border-sky-400',
      hoverHighlight: 'hover:bg-sky-500/10',
      focusRing: 'focus:border-sky-400',
    },
    emerald: {
      activeTrigger: 'border-emerald-400 text-emerald-300 font-bold bg-emerald-500/10 shadow-xs',
      activeBadge: 'bg-emerald-400/20 text-emerald-300 border-emerald-400/40',
      activeCheckbox: 'bg-emerald-400 text-black border-emerald-400',
      hoverHighlight: 'hover:bg-emerald-500/10',
      focusRing: 'focus:border-emerald-400',
    },
    sapphire: {
      activeTrigger: 'border-blue-400 text-blue-300 font-bold bg-blue-500/10 shadow-xs',
      activeBadge: 'bg-blue-400/20 text-blue-300 border-blue-400/40',
      activeCheckbox: 'bg-blue-400 text-white border-blue-400',
      hoverHighlight: 'hover:bg-blue-500/10',
      focusRing: 'focus:border-blue-400',
    },
    rose: {
      activeTrigger: 'border-rose-400 text-rose-300 font-bold bg-rose-500/10 shadow-xs',
      activeBadge: 'bg-rose-400/20 text-rose-300 border-rose-400/40',
      activeCheckbox: 'bg-rose-400 text-white border-rose-400',
      hoverHighlight: 'hover:bg-rose-500/10',
      focusRing: 'focus:border-rose-400',
    },
  }[colorTheme] || {
    activeTrigger: 'border-amber-400 text-amber-300 font-bold bg-amber-500/10 shadow-xs',
    activeBadge: 'bg-amber-400/20 text-amber-300 border-amber-400/40',
    activeCheckbox: 'bg-amber-400 text-black border-amber-400',
    hoverHighlight: 'hover:bg-amber-500/10',
    focusRing: 'focus:border-amber-400',
  }

  // Trigger label computation
  const triggerLabel = useMemo(() => {
    if (isAll) {
      return allLabel || `All ${title}`
    }
    if (selectedSet.size === 1) {
      const val = Array.from(selectedSet)[0]
      const found = options.find((o) => o.value === val)
      if (found) {
        let text = found.label || found.value
        // Truncate if too long
        if (text.length > maxDisplayLength) {
          text = text.substring(0, maxDisplayLength - 1) + '…'
        }
        return text
      }
      return `${title}: 1`
    }
    return `${titlePrefix ? titlePrefix + ' ' : ''}${title} (${selectedSet.size})`
  }, [isAll, allLabel, title, titlePrefix, selectedSet, options, maxDisplayLength])

  const selectedCount = isAll ? options.length : selectedSet.size

  return (
    <div ref={containerRef} className={`relative inline-block text-left ${isOpen ? 'z-[9999]' : 'z-auto'} ${className}`}>
      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        className={`flex items-center gap-1.5 rounded-lg border transition-all select-none cursor-pointer text-xs py-1 px-2.5 font-sans ${
          !isAll
            ? themeStyles.activeTrigger
            : 'bg-surface border-border text-text hover:border-gold/50'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''} ${triggerClassName}`}
        title={`Filter by ${title} (Multi-select enabled)`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        {icon && <span className="flex-shrink-0 text-muted">{icon}</span>}
        <span className="truncate max-w-[170px]">{triggerLabel}</span>

        {/* Quick clear '✕' button right on the trigger if active */}
        {!isAll && (
          <span
            role="button"
            tabIndex={0}
            onClick={handleQuickReset}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                handleQuickReset(e)
              }
            }}
            className="p-0.5 rounded-full hover:bg-black/20 text-current/80 hover:text-current transition-colors ml-0.5 cursor-pointer"
            title="Reset filter to All"
          >
            <X className="w-3 h-3" />
          </span>
        )}

        <ChevronDown
          className={`w-3 h-3 text-muted ml-0.5 transition-transform duration-150 flex-shrink-0 ${
            isOpen ? 'rotate-180 text-text' : ''
          }`}
        />
      </button>

      {/* Hidden select element for automated tests & headless compatibility */}
      {hiddenSelectTitle && (
        <select
          aria-hidden="true"
          tabIndex={-1}
          className="sr-only absolute opacity-0 pointer-events-none"
          title={hiddenSelectTitle}
          value={selectedSet.size === 1 ? Array.from(selectedSet)[0] : isAll ? 'ALL' : Array.from(selectedSet)[0] || 'ALL'}
          onChange={(e) => {
            const val = e.target.value
            if (val === 'ALL' || !val) {
              onChange?.(new Set())
            } else {
              onChange?.(new Set([val]))
            }
          }}
        >
          <option value="ALL">{allLabel || `All ${title}`}</option>
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label || opt.value}
            </option>
          ))}
        </select>
      )}

      {/* Floating Menu Popover */}
      {isOpen && (
        <div
          className={`absolute ${align === 'right' ? 'right-0' : 'left-0'} mt-1.5 min-w-[240px] max-w-[320px] rounded-xl border shadow-2xl z-[9999] py-1.5 flex flex-col text-xs font-sans animate-in fade-in zoom-in-95 duration-100`}
          style={{
            backgroundColor: 'var(--color-panel, #0d1320)',
            borderColor: 'var(--color-border, #182236)',
            boxShadow: '0 20px 50px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.08)',
          }}
          role="listbox"
          aria-multiselectable="true"
        >
          {/* Header Action Row */}
          <div
            className="flex items-center justify-between px-2.5 py-1.5 border-b border-border/80 text-[11px] text-muted rounded-t-lg"
            style={{ backgroundColor: 'var(--color-surface, #090d16)' }}
          >
            <span className="font-semibold text-text">
              {title}
              <span className="ml-1 text-[10px] font-mono opacity-60">
                ({selectedCount}/{options.length})
              </span>
            </span>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSelectAll}
                className="hover:text-gold transition-colors font-medium cursor-pointer"
                title="Select all options"
              >
                All
              </button>
              <span className="opacity-30">|</span>
              <button
                type="button"
                onClick={handleClear}
                className="hover:text-rose-400 transition-colors font-medium cursor-pointer"
                title="Reset to show all"
              >
                Reset
              </button>
            </div>
          </div>

          {/* Search Box */}
          {shouldShowSearch && (
            <div
              className="p-2 border-b border-border/60"
              style={{ backgroundColor: 'var(--color-panel, #0d1320)' }}
            >
              <div className="relative flex items-center">
                <Search className="w-3 h-3 absolute left-2 text-muted pointer-events-none" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={searchPlaceholder || `Search ${title.toLowerCase()}…`}
                  className="w-full text-text pl-7 pr-6 py-1 rounded-md border border-border text-[11px] placeholder:text-muted focus:outline-none focus:border-gold transition-colors"
                  style={{ backgroundColor: 'var(--color-surface, #090d16)' }}
                />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery('')}
                    className="absolute right-1.5 text-muted hover:text-text cursor-pointer p-0.5"
                    title="Clear search"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Options List */}
          <div className="max-h-60 overflow-y-auto custom-scrollbar py-1">
            {filteredOptions.length === 0 ? (
              <div className="py-4 text-center text-muted text-[11px]">
                No matching options found
              </div>
            ) : (
              filteredOptions.map((opt) => {
                const val = opt.value
                const isChecked = isAll || selectedSet.has(val)

                return (
                  <div
                    key={val}
                    onClick={() => handleToggleOption(val)}
                    className={`group flex items-center justify-between px-2.5 py-1.5 cursor-pointer select-none transition-colors ${
                      themeStyles.hoverHighlight
                    } ${
                      !isAll && selectedSet.has(val)
                        ? 'bg-elevated text-text font-medium'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {/* Checkbox + Icon + Label */}
                    <div className="flex items-center gap-2 min-w-0 pr-1">
                      <div
                        className={`w-3.5 h-3.5 rounded border flex items-center justify-center transition-all flex-shrink-0 ${
                          isChecked
                            ? themeStyles.activeCheckbox
                            : 'border-border bg-surface group-hover:border-border/80'
                        }`}
                      >
                        {isChecked && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                      </div>

                      {opt.icon && (
                        <span className="flex-shrink-0 text-xs">{opt.icon}</span>
                      )}

                      <span className="truncate text-xs text-text">
                        {opt.label || opt.value}
                      </span>
                    </div>

                    {/* Right side: Count badge + Solo "only" button */}
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {opt.count !== undefined && (
                        <span className="text-[10px] font-mono tabular-nums px-1.5 py-px rounded bg-surface border border-border/40 text-muted">
                          {opt.count}
                        </span>
                      )}

                      {/* Solo "only" hover button */}
                      <button
                        type="button"
                        onClick={(e) => handleSoloOption(e, val)}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-[10px] px-1 py-px rounded bg-surface hover:bg-gold hover:text-black border border-border text-muted font-mono cursor-pointer"
                        title={`Select ONLY "${opt.label || opt.value}"`}
                      >
                        only
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* Footer Active Summary if filtered */}
          {!isAll && (
            <div
              className="px-2.5 py-1.5 border-t border-border/80 text-[10px] text-muted flex items-center justify-between rounded-b-lg"
              style={{ backgroundColor: 'var(--color-surface, #090d16)' }}
            >
              <span className="font-mono">
                {selectedSet.size} of {options.length} selected
              </span>
              <button
                type="button"
                onClick={handleSelectAll}
                className="text-gold hover:underline cursor-pointer"
              >
                Reset to All
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
