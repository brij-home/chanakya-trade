/**
 * SkeletonCard — Shimmer loading skeleton variants
 *
 * Usage:
 *   <SkeletonCard variant="quote" />
 *   <SkeletonCard variant="table" rows={5} />
 *   <SkeletonCard variant="chart" height={240} />
 *   <SkeletonCard variant="persona" />
 *   <SkeletonCard variant="opportunity" />
 *   <Skeleton width={120} height={14} className="mb-2" />
 */

/** Base shimmer block */
export function Skeleton({ width, height = 12, className = '', rounded = 'rounded-md' }) {
  return (
    <div
      className={`skeleton ${rounded} flex-shrink-0 ${className}`}
      style={{ width: width ? `${width}px` : '100%', height: `${height}px` }}
    />
  )
}

/** Quote / price card skeleton */
function QuoteSkeleton() {
  return (
    <div className="bg-panel border border-border rounded-2xl p-4 space-y-3 animate-slide-up-fade">
      <div className="flex items-start justify-between">
        <div className="space-y-1.5">
          <Skeleton width={80} height={10} />
          <Skeleton width={140} height={24} rounded="rounded-lg" />
          <Skeleton width={100} height={10} />
        </div>
        <Skeleton width={56} height={20} rounded="rounded-full" />
      </div>
      <Skeleton height={6} rounded="rounded-full" />
      <div className="flex gap-4">
        <Skeleton width={80} height={10} />
        <Skeleton width={80} height={10} />
        <Skeleton width={80} height={10} />
      </div>
    </div>
  )
}

/** Chart area skeleton */
function ChartSkeleton({ height = 260 }) {
  return (
    <div
      className="bg-panel border border-border rounded-2xl overflow-hidden animate-slide-up-fade"
      style={{ height }}
    >
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
        <Skeleton width={60} height={10} />
        <Skeleton width={40} height={10} />
        <Skeleton width={40} height={10} />
      </div>
      {/* Chart body — simulated candles */}
      <div className="flex items-end gap-1.5 px-4 pb-4 pt-3 h-full">
        {Array.from({ length: 28 }, (_, i) => {
          const h = 30 + Math.random() * 70
          return (
            <div key={i} className="flex flex-col items-center gap-0.5 flex-1">
              <div
                className="skeleton rounded-sm w-full"
                style={{ height: `${h}%`, opacity: 0.6 + (i / 28) * 0.4 }}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Table / list skeleton */
function TableSkeleton({ rows = 5 }) {
  return (
    <div className="bg-panel border border-border rounded-2xl overflow-hidden animate-slide-up-fade">
      {/* Header */}
      <div className="flex items-center gap-4 px-4 py-2.5 border-b border-border">
        <Skeleton width={80} height={9} />
        <Skeleton width={50} height={9} className="ml-auto" />
        <Skeleton width={60} height={9} />
      </div>
      {/* Rows */}
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-2.5 border-b border-border/50 last:border-b-0">
          <Skeleton width={36} height={36} rounded="rounded-xl" className="flex-shrink-0" />
          <div className="flex-1 space-y-1.5">
            <Skeleton width={90 + i * 8} height={10} />
            <Skeleton width={60} height={8} />
          </div>
          <div className="space-y-1.5 text-right">
            <Skeleton width={70} height={10} />
            <Skeleton width={45} height={8} />
          </div>
        </div>
      ))}
    </div>
  )
}

/** Persona card skeleton */
function PersonaSkeleton() {
  return (
    <div className="bg-panel border border-border rounded-2xl p-4 space-y-3 animate-slide-up-fade">
      <div className="flex items-center gap-3">
        <Skeleton width={44} height={44} rounded="rounded-xl" />
        <div className="flex-1 space-y-1.5">
          <Skeleton width={110} height={11} />
          <Skeleton width={80} height={9} />
        </div>
        <Skeleton width={48} height={20} rounded="rounded-full" />
      </div>
      <Skeleton height={9} />
      <Skeleton width="75%" height={9} />
      <div className="grid grid-cols-2 gap-2">
        {[1,2,3,4].map(i => (
          <div key={i} className="bg-elevated rounded-lg p-2 space-y-1">
            <Skeleton width={50} height={8} />
            <Skeleton height={10} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** Opportunity card skeleton */
function OpportunitySkeleton() {
  return (
    <div className="bg-panel border border-border rounded-2xl p-3.5 space-y-2.5 animate-slide-up-fade">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Skeleton width={28} height={28} rounded="rounded-lg" />
          <div className="space-y-1">
            <Skeleton width={70} height={11} />
            <Skeleton width={50} height={8} />
          </div>
        </div>
        <Skeleton width={44} height={20} rounded="rounded-full" />
      </div>
      <div className="flex gap-2">
        <div className="flex-1 bg-elevated rounded-lg p-2 space-y-1">
          <Skeleton width={35} height={8} />
          <Skeleton height={11} />
        </div>
        <div className="flex-1 bg-elevated rounded-lg p-2 space-y-1">
          <Skeleton width={35} height={8} />
          <Skeleton height={11} />
        </div>
        <div className="flex-1 bg-elevated rounded-lg p-2 space-y-1">
          <Skeleton width={35} height={8} />
          <Skeleton height={11} />
        </div>
      </div>
      <Skeleton height={8} />
    </div>
  )
}

/** Debate round skeleton */
function DebateSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-4 animate-slide-up-fade">
      {['emerald', 'rose'].map((color) => (
        <div
          key={color}
          className="bg-panel border border-border rounded-2xl p-4 space-y-3"
          style={{ borderLeftColor: `var(--color-${color})`, borderLeftWidth: '3px' }}
        >
          <div className="flex items-center gap-2">
            <Skeleton width={28} height={28} rounded="rounded-full" />
            <Skeleton width={90} height={11} />
          </div>
          {[100, 90, 85, 70, 80].map((w, i) => (
            <Skeleton key={i} width={`${w}%`} height={9} />
          ))}
        </div>
      ))}
    </div>
  )
}

/** Generic card skeleton — just header + body lines */
function CardSkeleton({ lines = 4, showHeader = true }) {
  return (
    <div className="bg-panel border border-border rounded-2xl p-4 space-y-3 animate-slide-up-fade">
      {showHeader && (
        <div className="flex items-center justify-between pb-2 border-b border-border/50">
          <Skeleton width={100} height={10} />
          <Skeleton width={40} height={10} />
        </div>
      )}
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={`${95 - i * 7}%`} height={9} />
      ))}
    </div>
  )
}

/** Main export with variant dispatch */
export default function SkeletonCard({ variant = 'card', rows, height, lines, showHeader }) {
  switch (variant) {
    case 'quote':       return <QuoteSkeleton />
    case 'chart':       return <ChartSkeleton height={height} />
    case 'table':       return <TableSkeleton rows={rows} />
    case 'persona':     return <PersonaSkeleton />
    case 'opportunity': return <OpportunitySkeleton />
    case 'debate':      return <DebateSkeleton />
    default:            return <CardSkeleton lines={lines} showHeader={showHeader} />
  }
}
