import { BriefcaseBusiness, Target, TrendingUp, Zap, type LucideIcon } from 'lucide-react'
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { useEffect, useMemo, type ReactNode } from 'react'
import type { Match } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { percent } from '@/lib/format'
import { useNow } from '@/hooks/useNow'
import { sourceMeta } from '@/lib/sources'

const DAY_MS = 24 * 60 * 60 * 1000

function CountUp({ value, suffix = '' }: { value: number; suffix?: string }) {
  const reduce = useReducedMotion()
  const motionValue = useMotionValue(reduce ? value : 0)
  const text = useTransform(motionValue, (v) => `${Math.round(v).toLocaleString()}${suffix}`)
  useEffect(() => {
    if (reduce) {
      motionValue.set(value)
      return undefined
    }
    const controls = animate(motionValue, value, { duration: 0.9, ease: [0.22, 1, 0.36, 1] })
    return () => controls.stop()
  }, [value, reduce, motionValue])
  return <motion.span>{text}</motion.span>
}

interface StatProps {
  icon: LucideIcon
  iconClass: string
  value: number
  suffix?: string
  label: string
  aside?: ReactNode
}

function Stat({ icon: Icon, iconClass, value, suffix, label, aside }: StatProps) {
  return (
    <Card className="flex-row items-center gap-4 rounded-[var(--radius-card)] px-5 py-5 shadow-[var(--shadow-card)] ring-line transition-shadow hover:ring-line-strong sm:px-6">
      <Icon className={`size-8 shrink-0 ${iconClass}`} strokeWidth={1.7} />
      <div className="min-w-0 flex-1">
        <p className="text-[26px] font-semibold leading-none tracking-tight text-fg tabular"><CountUp value={value} suffix={suffix} /></p>
        <p className="mt-2 truncate text-[14px] text-fg-2">{label}</p>
      </div>
      {aside}
    </Card>
  )
}

/** Figures computed from the profile's real matches; nothing is estimated. */
export function StatCards({ matches, isLoading }: { matches: readonly Match[]; isLoading: boolean }) {
  const now = useNow()
  const stats = useMemo(() => {
    const sources = new Set(matches.flatMap((m) => (m.job?.source ? [m.job.source] : [])))
    return {
      total: matches.length,
      top: matches.reduce((best, m) => Math.max(best, m.score), 0),
      sources: [...sources],
      today: matches.filter((m) => now - Date.parse(m.created_at) < DAY_MS).length,
    }
  }, [matches, now])

  if (isLoading) {
    return <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[92px] rounded-[14px]" />)}</div>
  }
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Stat
        icon={BriefcaseBusiness}
        iconClass="text-info"
        value={stats.total}
        label="Active matches"
        aside={
          stats.today > 0 ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="h-6 gap-1 border-accent/30 bg-accent/10 text-[12.5px] text-accent tabular">
                  <TrendingUp />{stats.today} new
                </Badge>
              </TooltipTrigger>
              <TooltipContent>New in the last 24 hours</TooltipContent>
            </Tooltip>
          ) : undefined
        }
      />
      <Stat icon={Target} iconClass="text-accent" value={percent(stats.top)} suffix="%" label="Top match" />
      <Stat
        icon={Zap}
        iconClass="text-info"
        value={stats.sources.length}
        label="Sources matched"
        aside={
          <span className="flex gap-1.5" aria-hidden>
            {stats.sources.slice(0, 4).map((id) => <span key={id} className="size-2.5 rounded-full" style={{ background: sourceMeta(id)?.color }} />)}
          </span>
        }
      />
    </div>
  )
}
