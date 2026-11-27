import { LayoutGrid, List, SearchX, UserRoundPlus } from 'lucide-react'
import { GuestPrompt } from '@/components/auth/GuestPrompt'
import { AnimatePresence } from 'motion/react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import type { Match } from '@/api/types'
import { LiveFeedCard, ProfileMatchCard, QuickInsightsCard } from '@/components/intel/IntelCards'
import { FilterChips, type SortKey } from '@/components/jobs/FilterChips'
import { FilterPanel } from '@/components/jobs/FilterPanel'
import { JobCard, JobCardSkeleton } from '@/components/jobs/JobCard'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { Segmented, UnderlineTabs } from '@/components/ui/Tabs'
import { activeFilterCount, EMPTY_FILTERS, filtersToApi, filtersToParams, matchesFilters, type JobFilters } from '@/features/jobs/filters'
import { useActiveProfile, useJobList, useMatches } from '@/hooks/data'
import { useIsGuest } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { greeting, jobDate, monthlyUsd } from '@/lib/format'
import { describeIdentity, firstName } from '@/lib/identity'
import { usePreferences, type ResultsView } from '@/stores/preferences'
import { useSession } from '@/stores/session'
import { HeroHeading, HeroSearch } from './Hero'
import { StatCards } from './StatCards'

type ModeTab = 'all' | 'remote' | 'onsite' | 'hybrid'

const SORTERS: Record<SortKey, (a: Match, b: Match) => number> = {
  relevance: (a, b) => b.score - a.score,
  match: (a, b) => b.score - a.score,
  newest: (a, b) => Date.parse(b.job ? jobDate(b.job) : b.created_at) - Date.parse(a.job ? jobDate(a.job) : a.created_at),
  salary: (a, b) => (monthlyUsd(b.job?.extracted?.salary) ?? -1) - (monthlyUsd(a.job?.extracted?.salary) ?? -1),
}

const LATEST_JOBS_SHOWN = 10

/** What a guest sees instead of their matches: the newest public jobs, with the same filters. */
function LatestJobs({ filters, view }: { filters: JobFilters; view: ResultsView }) {
  const navigate = useNavigate()
  const query = useJobList({ sort: 'newest', ...filtersToApi(filters) })
  const jobs = query.data?.pages[0]?.items.slice(0, LATEST_JOBS_SHOWN) ?? []
  return (
    <section aria-label="Latest jobs">
      <div className="flex items-end justify-between gap-4 border-b border-line pb-3">
        <h2 className="text-[16px] font-semibold text-fg">Latest jobs</h2>
        <Button variant="ghost" size="sm" onClick={() => navigate(`/discover?${filtersToParams(filters).toString()}`)}>See all jobs</Button>
      </div>
      <div className="mt-5">
        {query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} className="rounded-[14px] border border-line bg-surface" />
        ) : query.isLoading ? (
          <div className="space-y-4">{[0, 1, 2].map((i) => <JobCardSkeleton key={i} />)}</div>
        ) : jobs.length === 0 ? (
          <EmptyState className="rounded-[14px] border border-line bg-surface" icon={<SearchX />} title="No jobs for these filters" description="Loosen the filters to see more jobs." />
        ) : (
          <div className={cn(view === 'grid' ? 'grid grid-cols-1 gap-4 md:grid-cols-2' : 'space-y-4')}>
            {jobs.map((job, index) => <JobCard key={job.job_id} job={job} variant={view} index={index} />)}
          </div>
        )}
      </div>
    </section>
  )
}

function useGreetingName(): string | null {
  const token = useSession((s) => s.token)
  return firstName(describeIdentity(token))
}

export default function OverviewPage() {
  const navigate = useNavigate()
  const name = useGreetingName()
  const guest = useIsGuest()
  const { profile, isLoading: profileLoading, error: profileError } = useActiveProfile()
  const matchesQuery = useMatches(profile?.id)
  const view = usePreferences((s) => s.view)
  const setView = usePreferences((s) => s.setView)
  const [filters, setFilters] = useState<JobFilters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<SortKey>('match')
  const [tab, setTab] = useState<ModeTab>('all')
  const [showPanel, setShowPanel] = useState(false)

  const withJob = useMemo(() => matchesQuery.matches.filter((m): m is Match & { job: NonNullable<Match['job']> } => m.job !== null), [matchesQuery.matches])
  const base = useMemo(() => withJob.filter((m) => matchesFilters(m.job, filters)), [withJob, filters])
  const counts = useMemo(() => {
    const by = (mode: string) => base.filter((m) => m.job.extracted?.work_mode === mode).length
    return { all: base.length, remote: by('remote'), onsite: by('onsite'), hybrid: by('hybrid') }
  }, [base])
  const shown = useMemo(
    () => base.filter((m) => tab === 'all' || m.job.extracted?.work_mode === tab).sort(SORTERS[sort]),
    [base, tab, sort],
  )

  const search = (query: string) => {
    const params = filtersToParams(filters)
    if (query.trim()) params.set('q', query.trim())
    navigate(`/discover?${params.toString()}`)
  }

  const loading = profileLoading || matchesQuery.isLoading
  const error = profileError ?? matchesQuery.error
  const best = matchesQuery.matches[0] ?? null

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[minmax(0,1fr)_316px]">
      <div className="min-w-0 space-y-6">
        <section className="space-y-6 pt-2">
          <HeroHeading greeting={greeting()} name={name} />
          <HeroSearch onSearch={search} onToggleFilters={() => setShowPanel((v) => !v)} filtersActive={showPanel || activeFilterCount(filters) > 0} />
          {guest ? (
            <FilterChips filters={filters} onChange={setFilters} sort="newest" onSortChange={setSort} sortOptions={['newest']} />
          ) : (
            <FilterChips filters={filters} onChange={setFilters} sort={sort} onSortChange={setSort} sortOptions={['match', 'newest', 'salary']} />
          )}
        </section>

        {guest ? <LatestJobs filters={filters} view={view} /> : null}

        {guest ? null : <StatCards matches={matchesQuery.matches} isLoading={loading} />}

        {guest ? null : <section aria-label="Matching jobs">
          <div className="flex items-end justify-between gap-4 border-b border-line">
            <UnderlineTabs
              id="overview-mode"
              value={tab}
              onChange={setTab}
              items={[
                { value: 'all', label: 'All Jobs', count: counts.all },
                { value: 'remote', label: 'Remote', count: counts.remote },
                { value: 'onsite', label: 'On-site', count: counts.onsite },
                { value: 'hybrid', label: 'Hybrid', count: counts.hybrid },
              ]}
            />
            <Segmented<ResultsView>
              id="overview-view"
              value={view}
              onChange={setView}
              className="mb-2 hidden sm:inline-flex"
              items={[
                { value: 'grid', label: <span className="sr-only">Grid view</span>, icon: <LayoutGrid /> },
                { value: 'list', label: <span className="sr-only">List view</span>, icon: <List /> },
              ]}
            />
          </div>

          <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[212px_minmax(0,1fr)]">
            <FilterPanel
              filters={filters}
              onChange={setFilters}
              jobs={withJob.map((m) => m.job)}
              className={cn('self-start lg:sticky lg:top-[100px]', showPanel ? 'block' : 'hidden lg:block')}
            />
            <div className="min-w-0">
              {error ? (
                <ErrorState error={error} onRetry={() => void matchesQuery.refetch()} className="rounded-[14px] border border-line bg-surface" />
              ) : loading ? (
                <div className="space-y-4">{[0, 1, 2].map((i) => <JobCardSkeleton key={i} />)}</div>
              ) : !profile ? (
                <EmptyState
                  className="rounded-[14px] border border-line bg-surface"
                  icon={<UserRoundPlus />}
                  title="Create your matching profile"
                  description="Tell Sanket the roles and skills you want. Matching jobs then appear here, scored against your profile, and arrive live as they are found."
                  action={<Button variant="primary" onClick={() => navigate('/profile')}>Create profile</Button>}
                />
              ) : shown.length === 0 ? (
                <EmptyState
                  className="rounded-[14px] border border-line bg-surface"
                  icon={<SearchX />}
                  title={withJob.length === 0 ? 'No matches yet' : 'No matches for these filters'}
                  description={
                    withJob.length === 0
                      ? profile.embedding_status === 'ready'
                        ? 'Matches appear as new jobs are indexed and fit your profile. Meanwhile, search all jobs.'
                        : 'Your profile is being prepared for matching. Matches appear once it is ready.'
                      : 'Loosen the filters to see more of your matches.'
                  }
                  action={
                    withJob.length === 0 ? (
                      <Button onClick={() => navigate('/discover')}>Discover jobs</Button>
                    ) : (
                      <Button onClick={() => { setFilters(EMPTY_FILTERS); setTab('all') }}>Reset filters</Button>
                    )
                  }
                />
              ) : (
                <div className={cn(view === 'grid' ? 'grid grid-cols-1 gap-4 md:grid-cols-2' : 'space-y-4')}>
                  <AnimatePresence mode="popLayout" initial={false}>
                    {shown.slice(0, 30).map((m, index) => (
                      <JobCard key={m.id} job={m.job} match={m} variant={view} index={index} />
                    ))}
                  </AnimatePresence>
                </div>
              )}
              {shown.length > 30 ? (
                <div className="mt-5 text-center">
                  <Button variant="outline" onClick={() => navigate('/live')}>See all {shown.length} matches</Button>
                </div>
              ) : null}
            </div>
          </div>
        </section>}
      </div>

      <aside className="grid grid-cols-1 content-start gap-5 md:grid-cols-2 xl:sticky xl:top-[100px] xl:grid-cols-1 xl:self-start" aria-label="Intelligence">
        {guest ? (
          <GuestPrompt className="md:col-span-2 xl:col-span-1" />
        ) : (
          <>
            <LiveFeedCard matches={matchesQuery.matches} isLoading={loading} />
            <ProfileMatchCard profile={profile} best={best} />
          </>
        )}
        <QuickInsightsCard className="md:col-span-2 xl:col-span-1" />
      </aside>
    </div>
  )
}
