import { Activity, RotateCw, UserRoundPlus, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import type { Match } from '@/api/types'
import { CompanyAvatar } from '@/components/jobs/CompanyAvatar'
import { PageHeader } from '@/components/layout/PageHeader'
import { MatchRing } from '@/components/match/MatchVisuals'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/badge'
import { Card, Skeleton, StatusDot } from '@/components/ui/primitives'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useActiveProfile, useMatches } from '@/hooks/data'
import { useFeedEntries } from '@/hooks/useFeedEntries'
import { useLiveStatus } from '@/hooks/useLiveStatus'
import { useNow } from '@/hooks/useNow'
import { cn } from '@/lib/cn'
import { IS_DEV } from '@/lib/env'
import { percent, relativeTime } from '@/lib/format'
import { useLiveFeed } from '@/stores/liveFeed'

const DAY_MS = 86_400_000
const DAYS = 7

function StatusBadge() {
  const view = useLiveStatus()
  const color = { accent: 'text-accent border-accent/25 bg-accent/[0.07]', amber: 'text-amber border-amber/25 bg-amber/[0.07]', danger: 'text-danger border-danger/30 bg-danger/[0.07]', muted: 'text-muted border-line-strong bg-elevated' }[view.tone]
  const label = view.label === 'Live' ? 'Live connection active' : view.label
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className={cn('h-7 gap-2 px-3 text-[12.5px]', color)}>
          <StatusDot tone={view.tone} pulse={view.pulse} />
          {label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{view.description}</TooltipContent>
    </Tooltip>
  )
}

function NewMatchBanner() {
  const latest = useLiveFeed((s) => s.received[0] ?? null)
  const [dismissed, setDismissed] = useState<number | null>(null)
  const show = latest && latest.event.id !== dismissed
  return (
    <AnimatePresence>
      {show ? (
        <motion.div
          key={latest.event.id}
          initial={{ opacity: 0, y: -10, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ type: 'spring', stiffness: 380, damping: 30 }}
          className="flex items-center gap-4 rounded-[14px] border border-accent/30 bg-gradient-to-r from-accent/[0.12] to-accent/[0.03] px-5 py-4"
        >
          <Activity className="size-6 shrink-0 text-accent" />
          <Link to={`/jobs/${latest.event.job_id}`} className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold text-accent">New opportunity matched your profile!</p>
            <p className="truncate text-[13px] text-fg-2">
              {latest.event.job?.title ?? `Job ${latest.event.job_id}`} · {percent(latest.event.score)}% match · {relativeTime(new Date(latest.receivedAt).toISOString())}
            </p>
          </Link>
          <button type="button" aria-label="Dismiss" onClick={() => setDismissed(latest.event.id)} className="text-accent/80 hover:text-accent">
            <X className="size-5" />
          </button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}

function MatchRow({ match, isNew }: { match: Match; isNew: boolean }) {
  const reactivated = 'reactivated' in match && match.reactivated === true
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: -14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0 }}
      transition={{ type: 'spring', stiffness: 360, damping: 30 }}
      className={cn('flex items-center gap-4 rounded-[14px] border bg-surface px-4 py-4 sm:px-5', isNew ? 'border-accent/25' : 'border-line')}
    >
      <CompanyAvatar company={match.job?.company ?? '?'} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2">
          <span className="truncate text-[15px] font-semibold text-fg">{match.job?.title ?? `Job ${match.job_id}`}</span>
          {isNew ? <span className="shrink-0 rounded bg-accent/15 px-1.5 py-px text-[10.5px] font-semibold text-accent">NEW</span> : null}
          {reactivated ? <span className="shrink-0 text-[11px] text-info">Back again</span> : null}
        </p>
        <p className="mt-0.5 truncate text-[13px] text-muted">
          {match.job?.company ?? 'Unknown company'} · <span className="text-info">{match.job?.source_name ?? 'Unknown source'}</span> · <span className="text-accent">{percent(match.score)}% match</span>
        </p>
      </div>
      <span className="hidden shrink-0 text-[12.5px] text-subtle sm:block">{relativeTime(match.created_at)}</span>
      <Link to={`/jobs/${match.job_id}`} className="inline-flex h-9 shrink-0 items-center rounded-[10px] border border-line-strong bg-elevated px-4 text-[13.5px] font-medium text-fg hover:bg-hover">
        View
      </Link>
    </motion.li>
  )
}

function startOfLocalDay(epochMs: number): number {
  const date = new Date(epochMs)
  date.setHours(0, 0, 0, 0)
  return date.getTime()
}

/** Matches per local calendar day, oldest first, so the last entry is "today". */
function useDailyCounts(matches: readonly Match[]): number[] {
  const now = useNow()
  return useMemo(() => {
    const counts = Array.from({ length: DAYS }, () => 0)
    const today = startOfLocalDay(now)
    for (const match of matches) {
      const age = Math.round((today - startOfLocalDay(Date.parse(match.created_at))) / DAY_MS)
      if (age >= 0 && age < DAYS) counts[DAYS - 1 - age] = (counts[DAYS - 1 - age] ?? 0) + 1
    }
    return counts
  }, [matches, now])
}

function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(1, ...values)
  const points = values.map((value, index) => [8 + (index * 244) / (values.length - 1), 70 - (value / max) * 58] as const)
  const line = points.map(([x, y]) => `${x},${y}`).join(' ')
  return (
    <svg viewBox="0 0 260 80" className="h-24 w-full" role="img" aria-label={`Matches per day over the last ${DAYS} days: ${values.join(', ')}`}>
      <defs>
        <linearGradient id="live-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="var(--color-accent)" stopOpacity="0.22" />
          <stop offset="1" stopColor="var(--color-accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`8,78 ${line} 252,78`} fill="url(#live-fill)" />
      <motion.polyline points={line} fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinejoin="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease: 'easeOut' }} />
      {points.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="2.6" fill="#0f1722" stroke="var(--color-accent)" strokeWidth="1.5" />)}
    </svg>
  )
}

function FeedStats({ matches }: { matches: readonly Match[] }) {
  const daily = useDailyCounts(matches)
  const today = daily[DAYS - 1] ?? 0
  const average = matches.length ? matches.reduce((sum, m) => sum + m.score, 0) / matches.length : 0
  const latest = matches.reduce((max, m) => Math.max(max, Date.parse(m.created_at)), 0)
  const latestNote = today === 0 && latest > 0 ? `Latest match ${relativeTime(new Date(latest).toISOString())}` : null
  return (
    <Card className="p-5">
      <h2 className="text-[15.5px] font-semibold text-fg">Live Feed Stats</h2>
      <p className="mt-1 text-[12px] text-subtle">Matches per day, last {DAYS} days (your local time)</p>
      <Sparkline values={daily} />
      <div className="mt-2 grid grid-cols-2 gap-4">
        <div><p className="text-[22px] font-semibold text-fg tabular">{today}</p><p className="text-[12.5px] text-muted">New today</p>{latestNote ? <p className="mt-0.5 text-[11.5px] text-subtle">{latestNote}</p> : null}</div>
        <div><p className="text-[22px] font-semibold text-accent tabular">{matches.length ? `${percent(average)}%` : '—'}</p><p className="text-[12.5px] text-muted">Average match</p></div>
      </div>
    </Card>
  )
}

function ConnectionCard() {
  const stream = useLiveFeed((s) => s.stream)
  const retry = useLiveFeed((s) => s.retry)
  const view = useLiveStatus()
  const rows: [string, string][] = [
    ['Status', view.label],
    ['Connected since', stream.connectedAt && stream.status === 'open' ? relativeTime(new Date(stream.connectedAt).toISOString()) : '—'],
    ...(IS_DEV
      ? ([
          ['Last event id', stream.lastEventId != null ? String(stream.lastEventId) : '—'],
          ['Reconnect attempts', String(stream.attempt)],
        ] as [string, string][])
      : []),
  ]
  return (
    <Card className="p-5">
      <h2 className="text-[15.5px] font-semibold text-fg">Connection</h2>
      <p className="mt-2 text-[13px] leading-relaxed text-muted">{view.description}</p>
      <dl className="mt-4 space-y-2.5">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between text-[13px]">
            <dt className="text-subtle">{label}</dt>
            <dd className="font-medium text-fg-2 tabular">{value}</dd>
          </div>
        ))}
      </dl>
      {retry && (stream.status === 'failed' || stream.status === 'reconnecting' || stream.status === 'offline') ? (
        <Button size="sm" className="mt-4 w-full" onClick={retry}><RotateCw /> Reconnect now</Button>
      ) : null}
    </Card>
  )
}

export default function LiveMatchesPage() {
  const navigate = useNavigate()
  const { profile, isLoading: profileLoading, error: profileError } = useActiveProfile()
  const matchesQuery = useMatches(profile?.id)
  const entries = useFeedEntries(matchesQuery.matches, 50)
  const loading = profileLoading || matchesQuery.isLoading
  const error = profileError ?? matchesQuery.error

  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-4">Live Matches <StatusBadge /></span>}
        description="Get notified instantly when new jobs match your profile."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-4">
          <NewMatchBanner />
          {error ? (
            <ErrorState error={error} onRetry={() => void matchesQuery.refetch()} className="rounded-[14px] border border-line bg-surface" />
          ) : loading ? (
            [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[84px] rounded-[14px]" />)
          ) : !profile ? (
            <EmptyState
              className="rounded-[14px] border border-line bg-surface"
              icon={<UserRoundPlus />}
              title="No profile to match against"
              description="Live matches are found for a profile. Create one and new matches will stream in here."
              action={<Button variant="primary" onClick={() => navigate('/profile')}>Create profile</Button>}
            />
          ) : entries.length === 0 ? (
            <EmptyState
              className="rounded-[14px] border border-line bg-surface"
              icon={<MatchRing score={0} size={44} />}
              title="Waiting for matches"
              description="Keep this page open. Jobs that fit your profile appear here the moment they are matched."
            />
          ) : (
            <ul className="space-y-3">
              <AnimatePresence initial={false}>
                {entries.map(({ match, isNew }) => <MatchRow key={match.id} match={match} isNew={isNew} />)}
              </AnimatePresence>
            </ul>
          )}
        </div>
        <aside className="space-y-5 lg:sticky lg:top-[100px] lg:self-start">
          <FeedStats matches={matchesQuery.matches} />
          <ConnectionCard />
        </aside>
      </div>
    </div>
  )
}
