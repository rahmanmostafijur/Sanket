import { Banknote, Bookmark, BookmarkCheck, ExternalLink } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'
import type { Job, Match, MatchedBy } from '@/api/types'
import { MatchBadge, MatchBar, MatchRing } from '@/components/match/MatchVisuals'
import { Chip } from '@/components/ui/primitives'
import { cn } from '@/lib/cn'
import { employmentLabel, externalUrl, formatSalary, jobDate, percent, relativeTime, seniorityLabel, workModeLabel } from '@/lib/format'
import { errorMessage } from '@/api/client'
import { useIsSaved, useSetSaved } from '@/hooks/data'
import { toast } from '@/stores/toasts'
import { CompanyAvatar } from './CompanyAvatar'

export interface JobCardProps {
  job: Job
  /** The profile's match for this job, when it matched. Scores are shown only from a match. */
  match?: Match | null
  matchedBy?: MatchedBy
  variant?: 'list' | 'grid'
  index?: number
}

const MATCHED_BY_LABEL: Record<MatchedBy, string> = { text: 'Keyword', vector: 'Semantic', both: 'Keyword + semantic' }

function jobTags(job: Job): string[] {
  const ex = job.extracted
  return [workModeLabel(ex?.work_mode), employmentLabel(ex?.employment_type), seniorityLabel(ex?.seniority)].filter(
    (tag): tag is string => tag !== null,
  )
}

export function SaveButton({ job, score, className }: { job: Job; score: number | null; className?: string }) {
  const saved = useIsSaved(job.job_id)
  const { setSaved, isPending } = useSetSaved()
  const Icon = saved ? BookmarkCheck : Bookmark
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.85 }}
      aria-pressed={saved}
      aria-label={saved ? `Remove ${job.title} from saved jobs` : `Save ${job.title}`}
      disabled={isPending}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        const save = !saved
        setSaved({ jobId: job.job_id, job, save, matchScore: score }).then(
          () => toast({ tone: 'success', title: save ? 'Saved to your list' : 'Removed from saved jobs', description: job.title }),
          (error: unknown) => toast({ tone: 'error', title: save ? 'Could not save this job' : 'Could not remove this job', description: errorMessage(error) }),
        )
      }}
      className={cn(
        'relative z-10 grid size-8 place-items-center rounded-lg transition-colors',
        saved ? 'text-accent' : 'text-fg-2 hover:bg-elevated hover:text-fg',
        className,
      )}
    >
      <Icon className={cn('size-[19px]', saved && 'fill-accent/20')} />
    </motion.button>
  )
}

function SourceLine({ job }: { job: Job }) {
  const url = externalUrl(job)
  const name = job.source_name ?? job.source ?? 'Unknown source'
  return (
    <div className="flex min-w-0 items-center gap-2 text-[13.5px]">
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          title={job.attribution ?? `Original listing on ${name}`}
          onClick={(event) => event.stopPropagation()}
          className="relative z-10 truncate font-medium text-info hover:underline"
        >
          {name}
        </a>
      ) : (
        <span className="truncate font-medium text-info">{name}</span>
      )}
      <span className="text-subtle">•</span>
      <span className="shrink-0 text-muted">{relativeTime(jobDate(job))}</span>
      {url ? <ExternalLink className="size-3.5 shrink-0 text-muted" aria-hidden /> : null}
    </div>
  )
}

const ENTRANCE = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, transition: { duration: 0.12 } },
}

export function JobCard({ job, match, matchedBy, variant = 'list', index = 0 }: JobCardProps) {
  const salary = formatSalary(job)
  const tags = jobTags(job)
  const skills = job.extracted?.skills ?? []
  const score = match?.score ?? null
  const href = `/jobs/${job.job_id}`
  const transition = { duration: 0.35, ease: [0.22, 1, 0.36, 1] as const, delay: Math.min(index, 8) * 0.04 }

  if (variant === 'grid') {
    return (
      <motion.article layout {...ENTRANCE} transition={transition} className="group relative flex flex-col gap-4 rounded-[var(--radius-card)] border border-line bg-surface p-5 transition-colors hover:border-line-strong hover:bg-[#111a26] has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-accent/70">
        <div className="flex items-start gap-3.5">
          <CompanyAvatarSlot job={job} />
          <div className="min-w-0 flex-1">
            <h3 className="line-clamp-2 text-[15.5px] font-semibold leading-snug text-fg">
              <Link to={href} className="after:absolute after:inset-0 after:rounded-[var(--radius-card)] focus-visible:outline-none">{job.title}</Link>
            </h3>
            <p className="mt-1 truncate text-[13px] text-muted">{job.company}</p>
          </div>
          <SaveButton job={job} score={score} className="-mr-1.5 -mt-1" />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => <Chip key={tag}>{tag}</Chip>)}
        </div>
        <div className="mt-auto flex items-center justify-between gap-3 border-t border-line pt-3.5">
          <div className="min-w-0">
            <SourceLine job={job} />
            {salary ? <p className="mt-1 flex items-center gap-1.5 text-[13px] text-fg-2"><Banknote className="size-3.5 text-amber" />{salary}</p> : null}
          </div>
          {score !== null ? (
            <div className="flex items-center gap-2">
              <MatchRing score={score} size={38} stroke={3.5} />
              <div className="leading-tight"><p className="text-[15px] font-semibold text-fg tabular">{percent(score)}%</p><p className="text-[11px] text-muted">Match</p></div>
            </div>
          ) : matchedBy ? <span className="text-[11.5px] text-subtle">{MATCHED_BY_LABEL[matchedBy]}</span> : null}
        </div>
      </motion.article>
    )
  }

  return (
    <motion.article layout {...ENTRANCE} transition={transition} className="group relative rounded-[var(--radius-card)] border border-line bg-surface px-5 pb-4 pt-5 transition-colors hover:border-line-strong hover:bg-[#111a26] has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-accent/70 sm:px-6">
      <div className="flex gap-4 sm:gap-5">
        <CompanyAvatarSlot job={job} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-[17px] font-semibold tracking-[-0.01em] text-fg sm:text-lg">
                <Link to={href} className="after:absolute after:inset-0 after:rounded-[var(--radius-card)] focus-visible:outline-none">{job.title}</Link>
              </h3>
              <p className="sr-only">{job.company}</p>
              <SourceLine job={job} />
            </div>
            <div className="flex shrink-0 flex-col items-end gap-2.5">
              <div className="flex items-center gap-2">
                {score !== null ? <MatchBadge score={score} className="hidden sm:inline-flex" /> : null}
                <SaveButton job={job} score={score} />
              </div>
              {salary ? <p className="hidden text-[14px] text-fg-2 tabular sm:block">{salary}</p> : null}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="mr-1 text-[13px] font-medium text-fg-2">{job.company}</span>
            {tags.map((tag) => <Chip key={tag}>{tag}</Chip>)}
            {salary ? <span className="text-[13px] text-fg-2 sm:hidden">{salary}</span> : null}
          </div>
          <div className="mt-4 flex items-center gap-4">
            <p className="min-w-0 flex-1 truncate text-[13.5px] text-fg-2">
              {skills.length ? <>Skills: {skills.slice(0, 5).join(', ')}</> : <span className="text-subtle">No skills extracted</span>}
            </p>
            {score !== null ? (
              <div className="flex w-[44%] max-w-[320px] items-center gap-4">
                <MatchBar value={score} delay={0.15 + Math.min(index, 8) * 0.04} label="Match score" />
                <span className="w-9 text-right text-[14px] font-medium text-fg tabular">{percent(score)}%</span>
              </div>
            ) : matchedBy ? (
              <span className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11.5px] text-muted">{MATCHED_BY_LABEL[matchedBy]}</span>
            ) : null}
          </div>
        </div>
      </div>
    </motion.article>
  )
}

function CompanyAvatarSlot({ job }: { job: Job }) {
  return <CompanyAvatar company={job.company} />
}

export function JobCardSkeleton({ variant = 'list' }: { variant?: 'list' | 'grid' }) {
  return (
    <div className={cn('rounded-[var(--radius-card)] border border-line bg-surface p-5', variant === 'list' && 'sm:px-6')}>
      <div className="flex gap-5">
        <div className="skeleton size-12 rounded-xl" />
        <div className="flex-1 space-y-3">
          <div className="skeleton h-4 w-2/3 rounded" />
          <div className="skeleton h-3 w-1/3 rounded" />
          <div className="flex gap-2"><div className="skeleton h-6 w-16 rounded-md" /><div className="skeleton h-6 w-20 rounded-md" /><div className="skeleton h-6 w-14 rounded-md" /></div>
          {variant === 'list' ? <div className="skeleton h-1.5 w-full rounded-full" /> : null}
        </div>
      </div>
    </div>
  )
}
