import { ArrowLeft, Banknote, Building, CalendarClock, ExternalLink, FileText, Gauge, Globe, Layers, MapPin, Radar, SearchX, UserRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import type { Job, JobDetail, JobPosting, Match } from '@/api/types'
import { CompanyAvatar } from '@/components/jobs/CompanyAvatar'
import { SaveButton } from '@/components/jobs/JobCard'
import { MatchBreakdown, MatchReasons } from '@/components/match/MatchBreakdown'
import { MatchRing } from '@/components/match/MatchVisuals'
import { Button } from '@/components/ui/Button'
import { Card, Chip, Skeleton } from '@/components/ui/primitives'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { UnderlineTabs } from '@/components/ui/Tabs'
import { isNotFound, useActiveProfile, useJobDetail, useMatchIndex, useMatches } from '@/hooks/data'
import { employmentLabel, externalUrl, formatSalary, jobDate, jobLocation, percent, relativeTime, seniorityLabel, workModeLabel } from '@/lib/format'
import { sourceMeta } from '@/lib/sources'
import { useRegisteredJob } from '@/stores/jobRegistry'
import { useSavedJob } from '@/stores/saved'
import { useSession } from '@/stores/session'

type Tab = 'details' | 'why' | 'source'

interface JobView {
  job: Job | null
  /** The full record from `GET /jobs/{id}`, once loaded. */
  detail: JobDetail | null
  match: Match | null
  isLoading: boolean
  detailLoading: boolean
  /** The API says the job does not exist or is no longer listed. */
  notFound: boolean
  error: unknown
  retry: () => void
}

/** The job from `GET /jobs/{id}`; jobs this tab has already seen stand in while it loads. */
function useJob(jobId: number): JobView {
  const mode = useSession((s) => s.mode)
  const { profile, isLoading: profileLoading } = useActiveProfile()
  const matchesQuery = useMatches(profile?.id)
  const index = useMatchIndex(profile?.id)
  const detailQuery = useJobDetail(jobId)
  const fromRegistry = useRegisteredJob(jobId)
  const fromSaved = useSavedJob(jobId)
  const match = index.get(jobId) ?? null
  const notFound = isNotFound(detailQuery.error)
  const detail = detailQuery.data ?? null
  // Demo live-feed jobs are not fixtures, so in demo mode a 404 still falls back to what was seen.
  const fallback = notFound && mode === 'api' ? null : (match?.job ?? fromRegistry ?? fromSaved)
  return {
    job: detail ?? fallback,
    detail,
    match,
    isLoading: profileLoading || matchesQuery.isLoading || detailQuery.isLoading,
    detailLoading: detailQuery.isLoading,
    notFound,
    error: notFound ? null : detailQuery.error,
    retry: () => void detailQuery.refetch(),
  }
}

function Fact({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-bg/40 p-3.5">
      <span className="mt-0.5 text-muted [&_svg]:size-4">{icon}</span>
      <div className="min-w-0">
        <dt className="text-[12px] text-subtle">{label}</dt>
        <dd className="mt-0.5 truncate text-[14px] font-medium text-fg">{value ?? <span className="font-normal text-subtle">Not stated</span>}</dd>
      </div>
    </div>
  )
}

function DetailsTab({ job, detail, detailLoading }: { job: Job; detail: JobDetail | null; detailLoading: boolean }) {
  const url = externalUrl(job)
  const ex = job.extracted
  const source = job.source_name ?? job.source ?? 'the source'
  const years = ex?.min_years_experience
  const description = detail?.description?.trim()
  return (
    <div className="space-y-7">
      <section>
        <h2 className="text-[16px] font-semibold text-fg">About the role</h2>
        {detailLoading ? (
          <div className="mt-3 space-y-2"><Skeleton className="h-4 w-full rounded" /><Skeleton className="h-4 w-5/6 rounded" /><Skeleton className="h-4 w-2/3 rounded" /></div>
        ) : description ? (
          <>
            <p className="mt-2 whitespace-pre-line break-words text-[14px] leading-relaxed text-fg-2">{description}</p>
            <p className="mt-3 text-[12.5px] text-subtle">
              Description from the listing on {source}{job.attribution ? `. ${job.attribution}` : ''}. Responsibilities and how to apply are on the original listing.
            </p>
          </>
        ) : (
          <p className="mt-2 text-[14px] leading-relaxed text-fg-2">
            Sanket has no description for this posting, only the structured details extracted from it. The full description, responsibilities and how to apply are on the original listing at {source}.
          </p>
        )}
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-[14px] font-medium text-accent hover:underline">
            <FileText className="size-4" /> Read the full description on {source} <ExternalLink className="size-3.5" />
          </a>
        ) : null}
      </section>
      <section>
        <h2 className="text-[16px] font-semibold text-fg">Key details</h2>
        <dl className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <Fact icon={<Globe />} label="Work mode" value={workModeLabel(ex?.work_mode)} />
          <Fact icon={<Gauge />} label="Seniority" value={seniorityLabel(ex?.seniority)} />
          <Fact icon={<Layers />} label="Employment type" value={employmentLabel(ex?.employment_type)} />
          <Fact icon={<MapPin />} label="Location" value={jobLocation(job)} />
          <Fact icon={<UserRound />} label="Experience" value={years != null ? `${years}+ years` : null} />
          <Fact icon={<Banknote />} label="Salary" value={formatSalary(job)} />
          <Fact icon={<CalendarClock />} label="Posted" value={relativeTime(jobDate(job))} />
          <Fact icon={<Radar />} label="First seen by Sanket" value={relativeTime(job.first_seen_at)} />
        </dl>
      </section>
      <section>
        <h2 className="text-[16px] font-semibold text-fg">Key requirements</h2>
        {ex?.skills.length ? (
          <div className="mt-3 flex flex-wrap gap-2">{ex.skills.map((skill) => <Chip key={skill} className="h-7 px-3 text-[13px]">{skill}</Chip>)}</div>
        ) : (
          <p className="mt-2 text-[13.5px] text-muted">No skills were extracted from this posting.</p>
        )}
        {ex === null ? <p className="mt-3 text-[13px] text-subtle">This posting has not been through extraction yet, so its details are limited.</p> : null}
      </section>
    </div>
  )
}

function PostingRow({ posting }: { posting: JobPosting }) {
  const url = externalUrl(posting)
  return (
    <li className="rounded-xl border border-line px-4 py-3 text-[14px] text-fg-2">
      <div className="flex items-center gap-3">
        <span className="size-2.5 shrink-0 rounded-full" style={{ background: sourceMeta(posting.source)?.color }} />
        <span className="min-w-0 truncate font-medium text-fg">{posting.name}</span>
        {posting.published_at ? <span className="shrink-0 text-[12.5px] text-muted">{relativeTime(posting.published_at)}</span> : null}
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex shrink-0 items-center gap-1 text-[13px] text-accent hover:underline">
            Original listing <ExternalLink className="size-3.5" />
          </a>
        ) : (
          <span className="ml-auto shrink-0 text-[12.5px] text-subtle">No link</span>
        )}
      </div>
      {posting.attribution ? <p className="mt-1.5 pl-[22px] text-[13px] text-muted">{posting.attribution}</p> : null}
    </li>
  )
}

function SourceTab({ job, detail }: { job: Job; detail: JobDetail | null }) {
  const url = externalUrl(job)
  const sources = job.sources.length ? job.sources : job.source ? [{ source: job.source, name: job.source_name ?? job.source }] : []
  if (detail?.postings.length) {
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-[15px] font-semibold text-fg">Listed on</h2>
          <ul className="mt-3 space-y-2">
            {detail.postings.map((posting, index) => <PostingRow key={`${posting.source}-${index}`} posting={posting} />)}
          </ul>
        </div>
        <p className="flex items-center gap-2 text-[13px] text-muted"><Building className="size-4" />{job.company}</p>
      </div>
    )
  }
  return (
    <div className="space-y-5">
      {job.attribution ? <p className="text-[14px] text-fg-2">{job.attribution}.</p> : null}
      <div>
        <h2 className="text-[15px] font-semibold text-fg">Listed on</h2>
        <ul className="mt-3 space-y-2">
          {sources.map((source) => (
            <li key={source.source} className="flex items-center gap-3 rounded-xl border border-line px-4 py-3 text-[14px] text-fg-2">
              <span className="size-2.5 rounded-full" style={{ background: sourceMeta(source.source)?.color }} />
              {source.name}
              {source.source === job.source && url ? (
                <a href={url} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-[13px] text-accent hover:underline">
                  Original listing <ExternalLink className="size-3.5" />
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
      <p className="flex items-center gap-2 text-[13px] text-muted"><Building className="size-4" />{job.company}</p>
    </div>
  )
}

function NotMatched() {
  return (
    <Card className="p-6">
      <h2 className="text-[16px] font-semibold text-fg">Your Match Breakdown</h2>
      <p className="mt-3 text-[14px] leading-relaxed text-muted">
        This job is not among your profile’s matches, so there is no score to show. Jobs are scored when they pass your profile’s filters and threshold.
      </p>
      <Link to="/profile" className="mt-4 inline-flex text-[13.5px] font-medium text-accent hover:underline">Review your profile →</Link>
    </Card>
  )
}

export default function JobDetailPage() {
  const params = useParams()
  const navigate = useNavigate()
  const jobId = Number(params.jobId)
  const { job, detail, match, isLoading, detailLoading, notFound, error, retry } = useJob(jobId)
  const [tab, setTab] = useState<Tab>('details')

  if (notFound && !job) {
    return (
      <EmptyState
        className="py-24"
        icon={<SearchX />}
        title="Job not found"
        description="This job does not exist or is no longer listed by any source."
        action={<><Button onClick={() => navigate('/discover')}>Discover jobs</Button><Button variant="primary" onClick={() => navigate('/')}>Your matches</Button></>}
      />
    )
  }
  if (!job && error) return <ErrorState error={error} onRetry={retry} className="py-24" />
  if (!job) {
    if (isLoading) return <div className="mx-auto max-w-[1180px] space-y-4 pt-4"><Skeleton className="h-40 rounded-[14px]" /><Skeleton className="h-80 rounded-[14px]" /></div>
    return (
      <EmptyState
        className="py-24"
        icon={<SearchX />}
        title="Job not available"
        description="This job could not be loaded. Open it from your search results, matches or saved jobs."
        action={<><Button onClick={() => navigate('/discover')}>Discover jobs</Button><Button variant="primary" onClick={() => navigate('/')}>Your matches</Button></>}
      />
    )
  }

  const url = externalUrl(job)
  const salary = formatSalary(job)
  const tags = [workModeLabel(job.extracted?.work_mode), employmentLabel(job.extracted?.employment_type), seniorityLabel(job.extracted?.seniority)].filter(Boolean) as string[]

  return (
    <div className="mx-auto max-w-[1180px] pt-2">
      <button type="button" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/discover'))} className="mb-5 inline-flex items-center gap-2 text-[14px] text-muted transition-colors hover:text-fg">
        <ArrowLeft className="size-4" /> Back to results
      </button>

      <Card className="p-5 sm:p-7">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <CompanyAvatar company={job.company} size="lg" />
          <div className="min-w-0 flex-1">
            <h1 className="text-[24px] font-semibold leading-tight tracking-[-0.02em] text-fg sm:text-[28px]">{job.title}</h1>
            <p className="mt-1.5 text-[15px] text-fg-2">
              {job.company} <span className="text-subtle">•</span> <span className="text-info">{job.source_name ?? job.source}</span> <span className="text-subtle">•</span> {relativeTime(jobDate(job))}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {tags.map((tag) => <Chip key={tag} className="h-7 px-3 text-[13px]">{tag}</Chip>)}
              {salary ? <Chip className="h-7 gap-1.5 px-3 text-[13px]"><Banknote className="size-3.5 text-amber" />{salary}</Chip> : null}
            </div>
          </div>
          <div className="flex items-center gap-4 sm:flex-col sm:items-end">
            {match ? (
              <div className="flex items-center gap-3">
                <MatchRing score={match.score} size={60} stroke={5} />
                <div className="leading-tight"><p className="text-[24px] font-semibold text-fg tabular">{percent(match.score)}%</p><p className="text-[13px] text-muted">Match</p></div>
              </div>
            ) : null}
            <div className="flex items-center gap-2">
              <SaveButton job={job} score={match?.score ?? null} className="size-10 border border-line-strong" />
              {url ? (
                <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex h-10 items-center gap-2 rounded-[10px] bg-accent px-4 text-sm font-semibold text-accent-ink hover:bg-accent-strong">
                  View original <ExternalLink className="size-4" />
                </a>
              ) : (
                <span className="text-[12.5px] text-subtle">No original link</span>
              )}
            </div>
          </div>
        </div>
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <Card className="p-5 sm:p-7">
          <UnderlineTabs
            id="job-tabs"
            value={tab}
            onChange={setTab}
            className="mb-6 border-b border-line"
            items={[
              { value: 'details', label: 'Job Details' },
              { value: 'why', label: 'Why this job matches you' },
              { value: 'source', label: 'Source' },
            ]}
          />
          {tab === 'details' ? <DetailsTab job={job} detail={detail} detailLoading={detailLoading && !detail} /> : null}
          {tab === 'why' ? (match ? <MatchReasons match={match} /> : <p className="text-[14px] text-muted">This job did not match your profile, so there is nothing to explain.</p>) : null}
          {tab === 'source' ? <SourceTab job={job} detail={detail} /> : null}
        </Card>
        <div className="space-y-6 lg:sticky lg:top-[100px] lg:self-start">
          {match ? <MatchBreakdown match={match} /> : <NotMatched />}
        </div>
      </div>
    </div>
  )
}
