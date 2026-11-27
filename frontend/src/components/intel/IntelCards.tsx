import { ArrowRight, ChartNoAxesColumn, CircleCheck, Circle } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { Match, Profile } from '@/api/types'
import { CompanyAvatar } from '@/components/jobs/CompanyAvatar'
import { useFeedEntries } from '@/hooks/useFeedEntries'
import { useLiveStatus } from '@/hooks/useLiveStatus'
import { MatchRing } from '@/components/match/MatchVisuals'
import { Card, Skeleton, StatusDot } from '@/components/ui/primitives'
import { cn } from '@/lib/cn'
import { percent, relativeTime } from '@/lib/format'

function HeaderLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-[13px] text-fg-2 transition-colors hover:text-accent">
      {children}
      <ArrowRight className="size-3.5" />
    </Link>
  )
}

export function LiveFeedCard({ matches, isLoading, className }: { matches: readonly Match[]; isLoading: boolean; className?: string }) {
  const status = useLiveStatus()
  const entries = useFeedEntries(matches, 4)
  return (
    <Card className={cn('p-5', className)}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2.5 text-[15.5px] font-semibold text-fg" title={status.description}>
          <StatusDot tone={status.tone} pulse={status.pulse} className="size-2.5" />
          Live Match Feed
        </h2>
        <HeaderLink to="/live">See all</HeaderLink>
      </div>
      <div className="relative mt-5">
        {isLoading ? (
          <div className="space-y-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full rounded-xl" />)}</div>
        ) : entries.length === 0 ? (
          <p className="py-6 text-center text-[13px] leading-relaxed text-muted">No matches yet. New matches for your profile appear here as they happen.</p>
        ) : (
          <ol className="relative space-y-5">
            <span aria-hidden className="absolute bottom-3 left-[3.5px] top-3 w-px bg-gradient-to-b from-accent/60 via-line-strong to-transparent" />
            <AnimatePresence initial={false}>
              {entries.map(({ match, at, isNew }) => (
                <motion.li
                  key={match.id}
                  layout
                  initial={{ opacity: 0, y: -12, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                  className="relative pl-6"
                >
                  <span aria-hidden className={cn('absolute left-0 top-1.5 size-2 rounded-full', isNew ? 'bg-accent shadow-[0_0_8px_rgb(184_243_107/0.9)]' : 'bg-[#3a4a60]')} />
                  <div className="flex items-center gap-2 text-[12px] text-muted">
                    {isNew ? <span className="rounded bg-accent/15 px-1.5 py-px text-[10.5px] font-semibold text-accent">NEW</span> : null}
                    {relativeTime(at)}
                  </div>
                  <Link to={`/jobs/${match.job_id}`} className="group mt-2 flex items-start gap-3">
                    <CompanyAvatar company={match.job?.company ?? '?'} size="sm" />
                    <span className="min-w-0">
                      <span className="line-clamp-2 text-[14px] font-medium leading-snug text-fg group-hover:text-accent">{match.job?.title ?? `Job ${match.job_id}`}</span>
                      <span className="mt-1 block truncate text-[12.5px] text-muted">
                        <span className="font-medium text-accent">{percent(match.score)}% match</span> • {match.job?.source_name ?? 'Unknown source'}
                      </span>
                    </span>
                  </Link>
                </motion.li>
              ))}
            </AnimatePresence>
          </ol>
        )}
      </div>
    </Card>
  )
}

export function ProfileMatchCard({ profile, best, className }: { profile: Profile | null; best: Match | null; className?: string }) {
  const skills = useMemo(() => {
    if (!profile) return []
    const hits = new Set([...(best?.components.skills?.required_hits ?? []), ...(best?.components.skills?.preferred_hits ?? [])].map((s) => s.toLowerCase()))
    return [...profile.required_skills, ...profile.preferred_skills].slice(0, 6).map((skill) => ({ skill, hit: hits.has(skill.toLowerCase()) }))
  }, [profile, best])
  return (
    <Card className={cn('p-5', className)}>
      <div className="flex items-center justify-between">
        <h2 className="text-[15.5px] font-semibold text-fg">Your Profile Match</h2>
        <HeaderLink to="/profile/matching">View Profile</HeaderLink>
      </div>
      {profile ? (
        <div className="mt-5 flex items-center gap-5">
          <div className="flex flex-col items-center gap-2">
            <MatchRing score={best?.score ?? 0} size={112} stroke={9}>
              <span className="text-[28px] font-semibold tracking-tight text-fg tabular">{best ? `${percent(best.score)}%` : '—'}</span>
            </MatchRing>
            <p className="max-w-[120px] text-center text-[13px] leading-tight text-fg-2">{best ? 'Best match' : 'No match yet'}</p>
          </div>
          <ul className="min-w-0 flex-1 space-y-2.5">
            {skills.length === 0 ? <li className="text-[13px] text-muted">Add skills to your profile.</li> : null}
            {skills.map(({ skill, hit }) => (
              <li key={skill} className="flex items-center gap-2.5 text-[14px] text-fg-2">
                {hit ? <CircleCheck className="size-[18px] shrink-0 fill-accent text-[#0f1722]" /> : <Circle className="size-[18px] shrink-0 text-muted" />}
                <span className="truncate">{skill}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-4 text-[13px] text-muted">Create a profile to see how jobs fit you.</p>
      )}
      {best?.job ? <p className="mt-4 truncate border-t border-line pt-3 text-[12px] text-muted">Best fit: <Link to={`/jobs/${best.job_id}`} className="text-fg-2 hover:text-accent">{best.job.title}</Link></p> : null}
    </Card>
  )
}

/** Decorative preview only: no numbers, nothing that reads as real data. */
export function QuickInsightsCard({ className }: { className?: string }) {
  return (
    <Card className={cn('overflow-hidden p-5', className)}>
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-[15.5px] font-semibold text-fg">
          <ChartNoAxesColumn className="size-5 text-accent" />
          Quick Insights
        </h2>
        <span className="rounded-full border border-line-strong px-2 py-0.5 text-[11px] text-fg-2">Coming Soon</span>
      </div>
      <p className="mt-3 text-[13.5px] leading-relaxed text-muted">Salary trends, top roles and market insights.</p>
      <svg viewBox="0 0 260 80" className="mt-4 h-20 w-full" aria-hidden>
        <defs>
          <linearGradient id="insight-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--color-accent)" stopOpacity="0.18" />
            <stop offset="1" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d="M4 66 L34 50 L58 58 L92 44 L120 30 L148 36 L176 20 L206 30 L232 14 L256 6 L256 80 L4 80 Z" fill="url(#insight-fill)" />
        <path d="M4 66 L34 50 L58 58 L92 44 L120 30 L148 36 L176 20 L206 30 L232 14 L256 6" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinejoin="round" opacity="0.85" />
        {[[34, 50], [58, 58], [92, 44], [120, 30], [148, 36], [176, 20], [206, 30], [232, 14], [256, 6]].map(([x, y]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="3" fill="#0f1722" stroke="var(--color-accent)" strokeWidth="1.6" />
        ))}
      </svg>
      <p className="mt-1 text-[11px] text-subtle">Preview. Salary analytics are not available yet.</p>
    </Card>
  )
}
