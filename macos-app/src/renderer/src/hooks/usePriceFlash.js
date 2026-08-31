import { useRef, useCallback } from 'react'

/**
 * usePriceFlash — triggers a CSS flash animation on a DOM element
 * when a price value changes direction (up = emerald, down = rose).
 *
 * Usage:
 *   const { ref, flash } = usePriceFlash()
 *   useEffect(() => flash(newPrice, prevPrice), [newPrice])
 *   return <span ref={ref}>{price}</span>
 */
export function usePriceFlash() {
  const ref = useRef(null)
  const prevRef = useRef(null)

  const flash = useCallback((currentValue, previousValue) => {
    const el = ref.current
    if (!el) return
    const curr = Number(currentValue)
    const prev = Number(previousValue ?? prevRef.current)
    prevRef.current = curr
    if (isNaN(curr) || isNaN(prev) || curr === prev) return

    const cls = curr > prev ? 'price-flash-up' : 'price-flash-down'
    el.classList.remove('price-flash-up', 'price-flash-down')
    // Force reflow to restart animation
    void el.offsetWidth
    el.classList.add(cls)
    const timer = setTimeout(() => el.classList.remove(cls), 700)
    return () => clearTimeout(timer)
  }, [])

  /**
   * flashEl — directly flash an element by ref without tracking previous
   */
  const flashEl = useCallback((el, direction = 'up') => {
    if (!el) return
    const cls = direction === 'up' ? 'price-flash-up' : 'price-flash-down'
    el.classList.remove('price-flash-up', 'price-flash-down')
    void el.offsetWidth
    el.classList.add(cls)
    setTimeout(() => el.classList.remove(cls), 700)
  }, [])

  return { ref, flash, flashEl }
}

/**
 * usePriceDirection — returns 'up' | 'down' | 'neutral' based on value change
 */
export function usePriceDirection(value) {
  const prev = useRef(null)
  const direction = useRef('neutral')
  const curr = Number(value)
  if (prev.current !== null && !isNaN(curr) && !isNaN(prev.current)) {
    if (curr > prev.current) direction.current = 'up'
    else if (curr < prev.current) direction.current = 'down'
    else direction.current = 'neutral'
  }
  prev.current = curr
  return direction.current
}

/**
 * PriceFlash — wrapper component that auto-flashes on value change
 * Usage: <PriceFlash value={ltp} className="font-mono font-bold" />
 */
export function PriceFlash({ value, className = '', children }) {
  const { ref, flash } = usePriceFlash()
  const prev = useRef(null)

  // Flash on every render where value changes
  if (prev.current !== null) {
    flash(value, prev.current)
  }
  prev.current = Number(value)

  return (
    <span ref={ref} className={`tabular-nums transition-colors ${className}`}>
      {children ?? value}
    </span>
  )
}

export default usePriceFlash
