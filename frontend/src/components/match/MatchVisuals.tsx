import { motion, useReducedMotion } from 'motion/react'
import { cn } from '@/lib/cn'
import { matchTier, percent, type MatchTier } from '@/lib/format'

const TIER_COLOR: Record<MatchTier, string> = {
  strong: 'var(--color-accent)',
  good: 'var(--color-info)',
  fair: 'var(--color-violet)',
}

const EASE = [0.22, 1, 0.36, 1] as const

/** "92% MATCH" pill. */
export function MatchBadge({ score, className }: { score: number; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 items-center rounded-md bg-accent px-2.5 text-xs font-bold tracking-wide text-accent-ink tabular',
        className,
      )}
    >
      {percent(score)}% MATCH
    </span>
  )
}

interface MatchBarProps {
  value: number
  color?: string
  className?: string
  delay?: number
  label?: string
}

/** Horizontal bar that grows to `value` (0..1). */
export function MatchBar({ value, color, className, delay = 0, label }: MatchBarProps) {
  const reduce = useReducedMotion()
  const width = `${percent(value)}%`
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent(value)}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-[#1d2836]', className)}
    >
      <motion.div
        className="h-full rounded-full"
        style={{ background: color ?? TIER_COLOR[matchTier(value)] }}
        initial={reduce ? { width } : { width: 0 }}
        animate={{ width }}
        transition={{ duration: 0.9, ease: EASE, delay }}
      />
    </div>
  )
}

interface MatchRingProps {
  score: number
  size?: number
  stroke?: number
  className?: string
  children?: React.ReactNode
}

/** Circular score indicator that sweeps in. */
export function MatchRing({ score, size = 44, stroke = 4, className, children }: MatchRingProps) {
  const reduce = useReducedMotion()
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - Math.min(1, Math.max(0, score)))
  const color = TIER_COLOR[matchTier(score)]
  return (
    <div className={cn('relative inline-grid shrink-0 place-items-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#1f2a39" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: reduce ? offset : circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.1, ease: EASE }}
          style={{ filter: `drop-shadow(0 0 6px color-mix(in srgb, ${color} 45%, transparent))` }}
        />
      </svg>
      {children ? <div className="absolute inset-0 grid place-items-center">{children}</div> : null}
    </div>
  )
}
