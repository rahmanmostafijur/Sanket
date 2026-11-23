import { Bookmark, Compass, Trash, X } from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { errorMessage } from '@/api/client'
import type { Job, Match } from '@/api/types'
import { FilterChips, type SortKey } from '@/components/jobs/FilterChips'
import { JobCard } from '@/components/jobs/JobCard'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/primitives'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { activeFilterCount, EMPTY_FILTERS, matchesFilters, type JobFilters } from '@/features/jobs/filters'
import { useActiveProfile, useClearSaved, useMatchIndex, useSavedJobs, useSetSaved, type SavedEntry } from '@/hooks/data'
import { jobDate, monthlyUsd, relativeTime } from '@/lib/format'
import { useSession } from '@/stores/session'
import { toast } from '@/stores/toasts'

type ListedEntry = SavedEntry & { job: Job }

function sorter(sort: SortKey, score: (entry: ListedEntry) => number): (a: ListedEntry, b: ListedEntry) => number {
  if (sort === 'match') return (a, b) => score(b) - score(a)
  if (sort === 'newest') return (a, b) => Date.parse(jobDate(b.job)) - Date.parse(jobDate(a.job))
  if (sort === 'salary') return (a, b) => (monthlyUsd(b.job.extracted?.salary) ?? -1) - (monthlyUsd(a.job.extracted?.salary) ?? -1)
  return (a, b) => Date.parse(b.savedAt) - Date.parse(a.savedAt)
}

/** A saved job the API no longer lists: nothing to show but the id and a way to drop it. */
function RemovedJob({ entry }: { entry: SavedEntry }) {
  const { setSaved, isPending } = useSetSaved()
  const remove = () =>
    setSaved({ jobId: entry.jobId, job: null, save: false }).then(
      () => toast({ tone: 'success', title: 'Removed from saved jobs' }),
      (error: unknown) => toast({ tone: 'error', title: 'Could not remove this job', description: errorMessage(error) }),
    )
  return (
    <div className="flex items-center gap-4 rounded-[var(--radius-card)] border border-dashed border-line px-5 py-4 text-[13.5px] text-muted">
      <span className="min-w-0 flex-1">This job is no longer listed. Saved {relativeTime(entry.savedAt)}.</span>
      <Button size="sm" variant="ghost" disabled={isPending} onClick={() => void remove()}><X /> Remove</Button>
    </div>
  )
}

export default function SavedJobsPage() {
  const navigate = useNavigate()
  const mode = useSession((s) => s.mode)
  const { entries: all, isLoading, error, refetch } = useSavedJobs()
  const clear = useClearSaved()
  const { profile } = useActiveProfile()
  const matchIndex = useMatchIndex(profile?.id)
  const [filters, setFilters] = useState<JobFilters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<SortKey>('relevance')
  const [confirmClear, setConfirmClear] = useState(false)

  const listed = useMemo(() => all.filter((entry): entry is ListedEntry => entry.job !== null), [all])
  const removed = useMemo(() => all.filter((entry) => entry.job === null), [all])
  const shown = useMemo(() => {
    const score = (entry: ListedEntry) => entry.matchScore ?? matchIndex.get(entry.jobId)?.score ?? -1
    return listed.filter((entry) => matchesFilters(entry.job, filters)).sort(sorter(sort, score))
  }, [listed, filters, sort, matchIndex])

  const clearAll = () => {
    setConfirmClear(false)
    clear().then(
      () => toast({ title: 'Saved jobs cleared' }),
      (cause: unknown) => toast({ tone: 'error', title: 'Could not clear every saved job', description: errorMessage(cause) }),
    )
  }
  const matchOf = (jobId: number): Match | null => matchIndex.get(jobId) ?? null

  return (
    <div className="mx-auto max-w-[1180px]">
      <PageHeader
        title="Saved Jobs"
        description={mode === 'api' ? 'Opportunities you bookmarked, kept with your Sanket account.' : 'Opportunities you bookmarked. Demo saves are kept in this browser.'}
        actions={
          all.length ? (
            confirmClear ? (
              <>
                <Button variant="ghost" onClick={() => setConfirmClear(false)}>Keep them</Button>
                <Button variant="danger" onClick={clearAll}><Trash /> Remove all {all.length}</Button>
              </>
            ) : (
              <Button variant="outline" onClick={() => setConfirmClear(true)}><Trash /> Clear all</Button>
            )
          ) : undefined
        }
      />
      {error ? (
        <ErrorState error={error} onRetry={refetch} className="rounded-[14px] border border-line bg-surface" />
      ) : isLoading ? (
        <div className="space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 rounded-[14px]" />)}</div>
      ) : all.length === 0 ? (
        <EmptyState
          className="rounded-[14px] border border-line bg-surface py-20"
          icon={<Bookmark />}
          title="Nothing saved yet"
          description="Use the bookmark on any job to keep it here for later."
          action={<Button variant="primary" onClick={() => navigate('/discover')}><Compass /> Discover jobs</Button>}
        />
      ) : (
        <>
          <FilterChips filters={filters} onChange={setFilters} sort={sort} onSortChange={setSort} />
          <p className="mt-5 text-[13.5px] text-muted"><span className="font-medium text-fg tabular">{shown.length}</span> of {all.length} saved jobs</p>
          <div className="mt-4 space-y-4">
            <AnimatePresence mode="popLayout" initial={false}>
              {shown.map((entry, index) => (
                <div key={entry.jobId}>
                  <JobCard job={entry.job} match={matchOf(entry.jobId)} index={index} />
                  <p className="mt-1.5 pl-1 text-[12px] text-subtle">Saved {relativeTime(entry.savedAt)}</p>
                </div>
              ))}
            </AnimatePresence>
            {activeFilterCount(filters) === 0 ? removed.map((entry) => <RemovedJob key={entry.jobId} entry={entry} />) : null}
          </div>
          {shown.length === 0 && activeFilterCount(filters) > 0 ? <EmptyState title="No saved jobs fit these filters" action={<Button onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</Button>} /> : null}
        </>
      )}
    </div>
  )
}
