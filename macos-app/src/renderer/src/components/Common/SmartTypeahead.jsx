import { useState, useEffect, useRef } from 'react'
import { fuzzySearchUniverse, saveRecentSearch } from '../../data/universeData'

/**
 * SmartTypeahead - Institutional OmniSearch Autocomplete Popover
 * - 100% Solid High-Contrast Background (Clean slate in Light Mode, Obsidian in Dark Mode)
 * - Zero underlying text bleed-through (Solid opacity)
 * - Adaptive Viewport Collision Detection (No clipping on left or right edges)
 * - Categorized filtering: All, Stocks, Indices, ETFs, Commodities, Councils, Personas, Quant
 * - Crystal clear typography, badges, and 1-click action buttons
 */
export default function SmartTypeahead({
  query = '',
  activeSymbol = null,
  isOpen = false,
  onSelect,
  onClose,
  mode = 'full', // 'full' | 'symbols_only'
  position = 'above', // 'above' | 'below'
  align = 'auto', // 'auto' | 'left' | 'right'
  selectedIndex = 0,
  setSelectedIndex,
  results = null,
}) {
  const containerRef = useRef(null)
  const [popoverAlign, setPopoverAlign] = useState('left')
  const [activeCategory, setActiveCategory] = useState('all')

  const rawResults = results || fuzzySearchUniverse(
    query,
    activeSymbol,
    mode === 'symbols_only' ? 10 : 12,
    activeCategory
  )
  const items = results 
    ? results 
    : (mode === 'symbols_only' 
        ? rawResults.filter((r) => r.type === 'symbol') 
        : rawResults)

  // Calculate boundary positioning to prevent screen clipping
  useEffect(() => {
    if (!containerRef.current || !isOpen || position === 'above') return
    if (align === 'left' || align === 'right') {
      setPopoverAlign(align)
      return
    }

    const parent = containerRef.current.parentElement
    if (!parent) return
    const rect = parent.getBoundingClientRect()
    const popoverWidth = Math.min(480, window.innerWidth - 32)

    if (rect.left + popoverWidth > window.innerWidth - 16 && rect.right - popoverWidth >= 8) {
      setPopoverAlign('right')
      } else {
      setPopoverAlign('left')
    }
  }, [isOpen, query, position, align])

  // Scroll active item into view
  useEffect(() => {
    if (!containerRef.current) return
    const activeEl = containerRef.current.querySelector(`[data-index="${selectedIndex}"]`)
    if (activeEl && typeof activeEl.scrollIntoView === 'function') {
      activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [selectedIndex])

  if (!isOpen || items.length === 0) return null

  const handleSelect = (item, customAction = null) => {
    saveRecentSearch({
      text: item.command || (item.symbol ? `analyze ${item.symbol}` : item.text || item.label),
      symbol: item.symbol || null,
      label: item.symbol ? `${item.symbol} (${item.name || item.sector})` : (item.label || item.name),
      icon: item.icon || '🔍',
    })

    if (customAction && item.symbol) {
      if (customAction === 'chart') {
        onSelect({ ...item, command: `chart ${item.symbol}`, customAction: 'chart' })
      } else if (customAction === 'multibagger') {
        onSelect({ ...item, command: `multibagger ${item.symbol}`, customAction: 'multibagger' })
      } else if (customAction === 'council') {
        onSelect({ ...item, command: `council breakout ${item.symbol}`, customAction: 'council' })
      }
    } else {
      onSelect(item)
    }
  }

  // Highlight matching characters in query with solid amber badge
  const highlightMatch = (text, q) => {
    if (!text || !q) return text
    const cleanQ = q.trim().toLowerCase()
    const idx = text.toLowerCase().indexOf(cleanQ)
    if (idx === -1) return text
    return (
      <>
        {text.slice(0, idx)}
        <span className="bg-amber/30 text-amber-800 dark:text-amber-300 font-black px-1 py-0.5 rounded underline decoration-amber">
          {text.slice(idx, idx + cleanQ.length)}
        </span>
        {text.slice(idx + cleanQ.length)}
      </>
    )
  }

  const dynamicStyle = position === 'below' 
    ? {
        [popoverAlign === 'right' ? 'right' : 'left']: 0,
        width: 'min(480px, calc(100vw - 32px))',
        maxWidth: 'calc(100vw - 32px)',
      }
    : {}

  const categories = mode === 'symbols_only'
    ? [
        { id: 'all', label: 'All' },
        { id: 'stock', label: 'Stocks' },
        { id: 'index', label: 'Indices' },
        { id: 'etf', label: 'ETFs' },
        { id: 'commodity', label: 'Commodities' },
        { id: 'currency', label: 'Currencies' },
      ]
    : [
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
      ref={containerRef}
      style={dynamicStyle}
      className={`absolute z-50 max-h-[440px] overflow-y-auto bg-white dark:bg-[#0f1218] border-2 border-amber shadow-[0_20px_50px_rgba(0,0,0,0.35)] dark:shadow-[0_25px_60px_rgba(0,0,0,0.85)] rounded-2xl p-2 space-y-1.5 animate-fade-slide ring-2 ring-amber/20 select-none ${
        position === 'above' 
          ? 'left-0 right-0 w-full bottom-full mb-2' 
          : 'top-full mt-2'
      }`}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Category header / Quick label */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-100 dark:bg-[#161b24] border border-slate-200 dark:border-slate-800 rounded-xl text-[11px] uppercase font-extrabold text-slate-800 dark:text-slate-200 tracking-wider">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-amber animate-pulse" />
          <span>{query ? `OmniSearch Matches (${items.length})` : (activeCategory !== 'all' ? `${categories.find((c) => c.id === activeCategory)?.label || activeCategory} (${items.length})` : '🕒 Recent Searches & Recommendations')}</span>
        </span>
        <span className="font-mono text-[10px] font-extrabold px-2 py-0.5 rounded bg-amber text-black shadow-xs">
          Indian Markets 🇮🇳
        </span>
      </div>

      {/* Category Quick Filter Bar */}
      {!results && (
        <div className="flex items-center gap-1 overflow-x-auto py-1 px-1 no-scrollbar border-b border-slate-200 dark:border-slate-800">
          {categories.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setActiveCategory(cat.id)
                setSelectedIndex && setSelectedIndex(0)
              }}
              className={`px-2 py-0.5 rounded-lg text-[10px] font-mono font-bold tracking-tight whitespace-nowrap cursor-pointer transition-all ${
                activeCategory === cat.id
                  ? 'bg-amber text-black shadow-xs font-black'
                  : 'bg-slate-100 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      )}

      {/* Results List */}
      <div className="space-y-1">
        {items.map((item, idx) => {
          const isSelected = idx === selectedIndex
          const isStock = item.type === 'symbol'
          const isCouncil = item.type === 'council'
          const isPersona = item.type === 'persona'
          const isRecent = item.category === 'recent'
          const stockType = item.stockType || item.category

          return (
            <div
              key={idx}
              data-index={idx}
              onMouseEnter={() => setSelectedIndex && setSelectedIndex(idx)}
              onClick={() => handleSelect(item)}
              className={`group flex items-center justify-between p-2.5 rounded-xl cursor-pointer transition-all ${
                isSelected
                  ? 'bg-amber-50 dark:bg-amber-950/50 border-2 border-amber text-slate-900 dark:text-white shadow-sm ring-1 ring-amber/30'
                  : 'bg-white dark:bg-[#0f1218] hover:bg-slate-50 dark:hover:bg-[#161b24] text-slate-900 dark:text-slate-100 border border-slate-200/80 dark:border-slate-800/80'
              }`}
            >
              {/* Left Item Details */}
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div
                  className={`w-8 h-8 rounded-xl flex items-center justify-center text-sm flex-shrink-0 border transition-all ${
                    isSelected ? 'bg-amber text-black font-black shadow-md border-amber' : 'bg-slate-100 dark:bg-[#161b24] border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 font-bold'
                  }`}
                >
                  {item.icon || (isStock ? '🏢' : isCouncil ? '🏛️' : isPersona ? '🧠' : '⚡')}
                </div>

                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-extrabold text-xs text-slate-900 dark:text-white font-mono tracking-wide truncate">
                      {isStock ? highlightMatch(item.symbol, query) : highlightMatch(item.label || item.name || item.text, query)}
                    </span>

                    {isStock && item.sector && (
                      <span className="text-[10px] px-2 py-0.5 rounded-md font-mono font-bold bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300">
                        {item.sector}
                      </span>
                    )}

                    {isStock && item.lotSize && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-semibold bg-slate-100 dark:bg-slate-800 border border-slate-300/80 dark:border-slate-700/80 text-slate-600 dark:text-slate-400 hidden sm:inline-block">
                        Lot {item.lotSize}
                      </span>
                    )}

                    {isStock && stockType === 'index' && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-emerald-500 text-black shadow-xs">
                        INDEX
                      </span>
                    )}

                    {isStock && stockType === 'etf' && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-sky-500 text-black shadow-xs">
                        ETF
                      </span>
                    )}

                    {isStock && stockType === 'commodity' && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-amber-500 text-black shadow-xs">
                        MCX
                      </span>
                    )}

                    {isStock && stockType === 'currency' && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-violet-500 text-white shadow-xs">
                        FOREX
                      </span>
                    )}

                    {isCouncil && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-blue-600 text-white shadow-xs">
                        COUNCIL
                      </span>
                    )}

                    {isPersona && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-purple-600 text-white shadow-xs">
                        PERSONA
                      </span>
                    )}

                    {isRecent && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded font-mono font-extrabold bg-amber text-black shadow-xs">
                        RECENT
                      </span>
                    )}
                  </div>

                  {/* Secondary Description */}
                  <span className="text-[11px] text-slate-600 dark:text-slate-400 font-medium block truncate font-ui">
                    {item.name || item.desc || item.usage || item.command || ''}
                  </span>
                </div>
              </div>

              {/* Right 1-Click Action Chips (for stock items) */}
              {isStock && (
                <div className="hidden sm:flex items-center gap-1.5 flex-shrink-0 ml-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleSelect(item, 'council')
                    }}
                    className="px-2 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-amber hover:text-black dark:hover:bg-amber dark:hover:text-black border border-slate-300 dark:border-slate-700 text-[10px] font-bold text-slate-800 dark:text-slate-200 cursor-pointer transition-all shadow-xs"
                    title={`Run Breakout Council on ${item.symbol}`}
                  >
                    🏛️ Council
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleSelect(item, 'multibagger')
                    }}
                    className="px-2 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-emerald-500 hover:text-black dark:hover:bg-emerald-500 dark:hover:text-black border border-slate-300 dark:border-slate-700 text-[10px] font-bold text-slate-800 dark:text-slate-200 cursor-pointer transition-all shadow-xs"
                    title={`Check Minervini Stage 2 Markup on ${item.symbol}`}
                  >
                    💎 Stage 2
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Keyboard Shortcut Footer */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-100 dark:bg-[#161b24] border-t border-slate-200 dark:border-slate-800 rounded-b-xl text-[10px] font-mono text-slate-700 dark:text-slate-300 font-bold">
        <div className="flex items-center gap-3">
          <span>
            <kbd className="px-1.5 py-0.5 bg-white dark:bg-[#0f1218] border border-slate-300 dark:border-slate-700 rounded text-slate-900 dark:text-slate-100 font-bold">↑</kbd>{' '}
            <kbd className="px-1.5 py-0.5 bg-white dark:bg-[#0f1218] border border-slate-300 dark:border-slate-700 rounded text-slate-900 dark:text-slate-100 font-bold">↓</kbd> Navigate
          </span>
          <span>
            <kbd className="px-1.5 py-0.5 bg-white dark:bg-[#0f1218] border border-slate-300 dark:border-slate-700 rounded text-slate-900 dark:text-slate-100 font-bold">Tab</kbd> Complete
          </span>
          <span>
            <kbd className="px-1.5 py-0.5 bg-white dark:bg-[#0f1218] border border-slate-300 dark:border-slate-700 rounded text-slate-900 dark:text-slate-100 font-bold">↵ Enter</kbd> Run
          </span>
        </div>
        <span>
          <kbd className="px-1.5 py-0.5 bg-white dark:bg-[#0f1218] border border-slate-300 dark:border-slate-700 rounded text-slate-900 dark:text-slate-100 font-bold">Esc</kbd> Dismiss
        </span>
      </div>
    </div>
  )
}
