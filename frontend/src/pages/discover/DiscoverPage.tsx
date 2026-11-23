import { ArrowRight, Info, LayoutGrid, List, LoaderCircle, Search, SearchX, Sparkles, TextSearch } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import type { Job, SearchItem, SearchMode } from '@/api/types'
import { FilterChips, type SortKey } from '@/components/jobs/FilterChips'
import { JobCard, JobCardSkeleton } from '@/components/jobs/JobCard'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { Segmented, UnderlineTabs } from '@/components/ui/Tabs'
import { activeFilterCount, EMPTY_FILTERS, filtersFromParams, filtersToApi, filtersToParams, type JobFilters } from '@/features/jobs/filters'
import { useActiveProfile, useJobList, useMatchIndex, useSearch } from '@/hooks/data'
import { cn } from '@/lib/cn'
import { monthlyUsd } from '@/lib/format'
import { usePreferences, type ResultsView } from '@/stores/preferences'

type Lens = 'all' | 'keyword' | 'semantic'

const LENS_MODE: Record<Lens, SearchMode> = { all: 'hybrid', keyword: 'keyword', semantic: 'semantic' }
const BROWSE_SORTS: readonly SortKey[] = ['newest', 'match', 'salary']
const MONTHS_PER_YEAR = 12

function useDiscoverQuery() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const filters = useMemo(() => filtersFromParams(params), [params])
  const update = (next: { q?: string; filters?: JobFilters }) => {
    const base = new URLSearchParams(params)
    if (next.q !== undefined) {
      if (next.q.trim()) base.set('q', next.q.trim())
      else base.delete('q')
    }
    setParams(next.filters ? filtersToParams(next.filters, base) : base, { replace: next.q === undefined })
  }
  return { q, filters, update }
}

function SearchBar({ initial, onSubmit }: { initial: string; onSubmit: (q: string) => void }) {
  const [value, setValue] = useState(initial)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit(value)
  }
  return (
    <form role="search" onSubmit={submit} className="group flex h-14 items-center gap-3 rounded-2xl border border-line-strong bg-surface pl-5 pr-2 transition-[border-color,box-shadow] focus-within:border-accent/45 focus-within:shadow-[0_0_0_4px_rgb(184_243_107/0.07)]">
      <Search className="size-5 shrink-0 text-muted group-focus-within:text-accent" />
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        maxLength={200}
        placeholder="Python FastAPI backend engineer, or “remote data roles in Europe”"
        aria-label="Search jobs"
        className="h-full min-w-0 flex-1 bg-transparent text-[16px] text-fg outline-none"
      />
      <motion.button
        whileTap={{ scale: 0.92 }}
        type="submit"
        aria-label="Search"
        className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-accent-ink shadow-[0_0_20px_-4px_rgb(184_243_107/0.6)] hover:bg-accent-strong"
      >
        <Search className="size-[18px]" strokeWidth={2.4} />
      </motion.button>
    </form>
  )
}

/** Relevance and newest come sorted from the API; match and salary are sorted over what is loaded. */
function sortItems<T extends Job>(items: T[], sort: SortKey, score: (jobId: number) => number): T[] {
  if (sort === 'match') return [...items].sort((a, b) => score(b.job_id) - score(a.job_id))
  if (sort === 'salary') return [...items].sort((a, b) => (monthlyUsd(b.extracted?.salary) ?? -1) - (monthlyUsd(a.extracted?.salary) ?? -1))
  return items
}

function SearchIdeas({ onPick }: { onPick: (q: string) => void }) {
  const { profile } = useActiveProfile()
  const recent = usePreferences((s) => s.recentSearches)
  const ideas = [...new Set([...(profile?.desired_titles ?? []), ...recent, 'remote Python backend', 'senior data engineer', 'React TypeScript contract'])].slice(0, 6)
  return (
    <div className="rounded-[14px] border border-line bg-surface px-5 py-5">
      <p className="flex items-center gap-2 text-[15px] font-semibold text-fg"><Sparkles className="size-4 text-accent" /> Search every indexed job</p>
      <p className="mt-1 text-[13.5px] text-muted">Keywords and plain language both work. All results fuses full-text and semantic retrieval; the other tabs use one each.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {ideas.map((idea) => (
          <button key={idea} type="button" onClick={() => onPick(idea)} className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line-strong px-3.5 text-[13px] text-fg-2 transition-colors hover:border-accent/40 hover:text-fg">
            {idea}
            <ArrowRight className="size-3.5 text-muted" />
          </button>
        ))}
      </div>
    </div>
  )
}

function degradedNotice(mode: SearchMode, reason: string | null): string {
  const why = reason === 'embeddings_disabled' ? 'embeddings are switched off' : 'the query could not be embedded'
  return mode === 'semantic'
    ? `Semantic search is unavailable right now (${why}), so this tab has no results. Try All results or Keyword.`
    : `Semantic search is unavailable right now (${why}), so these are keyword results only.`
}

export default function DiscoverPage() {
  const { q, filters, update } = useDiscoverQuery()
  const [lens, setLens] = useState<Lens>('all')
  const [sort, setSort] = useState<SortKey>('relevance')
  const view = usePreferences((s) => s.view)
  const setView = usePreferences((s) => s.setView)
  const addRecent = usePreferences((s) => s.addRecentSearch)
  const { profile } = useActiveProfile()
  const matchIndex = useMatchIndex(profile?.id)
  const browsing = !q
  const effectiveSort: SortKey = browsing && sort === 'relevance' ? 'newest' : sort
  const apiFilters = useMemo(() => filtersToApi(filters), [filters])

  const searchQuery = useSearch({ q, mode: LENS_MODE[lens], sort: sort === 'newest' ? 'newest' : 'relevance', ...apiFilters })
  const browseQuery = useJobList({ sort: 'newest', ...apiFilters }, browsing)
  const query = browsing ? browseQuery : searchQuery
  const first = searchQuery.data?.pages[0]
  const browseTotal = browseQuery.data?.pages[0]?.total
  const loaded = useMemo<(Job | SearchItem)[]>(
    () => (browsing ? browseQuery.data?.pages : searchQuery.data?.pages)?.flatMap((page) => page.items) ?? [],
    [browsing, browseQuery.data, searchQuery.data],
  )
  const shown = useMemo(() => sortItems(loaded, effectiveSort, (id) => matchIndex.get(id)?.score ?? -1), [loaded, effectiveSort, matchIndex])
  const filterCount = activeFilterCount(filters)
  const filterNote = filterCount ? ` · ${filterCount} filter${filterCount > 1 ? 's' : ''}` : ''
  const tabCount = (value: Lens) => (!browsing && value === lens && first ? first.total_candidates : undefined)

  const search = (value: string) => {
    if (value.trim()) addRecent(value)
    update({ q: value })
  }

  return (
    <div className="mx-auto max-w-[1180px]">
      <PageHeader title="Discover Jobs" description="Search every job Sanket has indexed, by keyword or in plain language." />
      <div className="space-y-4">
        <UnderlineTabs
          id="discover-lens"
          value={lens}
          onChange={setLens}
          className="border-b border-line"
          items={[
            { value: 'all', label: 'All results', icon: <Sparkles className="size-4" />, count: tabCount('all') },
            { value: 'keyword', label: 'Keyword', icon: <TextSearch className="size-4" />, count: tabCount('keyword') },
            { value: 'semantic', label: 'Semantic', icon: <Sparkles className="size-4" />, count: tabCount('semantic') },
          ]}
        />
        <SearchBar key={q} initial={q} onSubmit={search} />
        <FilterChips
          filters={filters}
          onChange={(next) => update({ filters: next })}
          sort={effectiveSort}
          onSortChange={setSort}
          sortOptions={browsing ? BROWSE_SORTS : undefined}
        />
      </div>

      {browsing ? <div className="mt-6"><SearchIdeas onPick={search} /></div> : null}

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[14px] text-muted" aria-live="polite">
          {query.isLoading ? (browsing ? 'Loading the latest jobs…' : 'Searching…') : browsing ? (
            browseTotal !== undefined ? (
              <>
                Latest jobs · <span className="font-medium text-fg tabular">{shown.length}</span> shown of{' '}
                <span className="font-medium text-fg tabular">{browseTotal.toLocaleString()}</span> listed{filterNote}
              </>
            ) : null
          ) : first ? (
            <>
              <span className="font-medium text-fg tabular">{shown.length}</span> shown of{' '}
              <span className="font-medium text-fg tabular">{first.total_candidates.toLocaleString()}</span> results for “<span className="text-fg">{first.query}</span>”{filterNote}
            </>
          ) : null}
        </p>
        <div className="flex items-center gap-3">
          {query.isFetching && !query.isLoading ? <LoaderCircle className="size-4 animate-spin text-muted" aria-label="Updating" /> : null}
          <Segmented<ResultsView>
            id="discover-view"
            value={view}
            onChange={setView}
            items={[
              { value: 'list', label: <span className="sr-only">List view</span>, icon: <List /> },
              { value: 'grid', label: <span className="sr-only">Grid view</span>, icon: <LayoutGrid /> },
            ]}
          />
        </div>
      </div>

      {!browsing && first?.degraded ? (
        <p className="mt-3 flex items-center gap-2 rounded-xl border border-amber/25 bg-amber/[0.06] px-4 py-2.5 text-[13px] text-fg-2">
          <Info className="size-4 shrink-0 text-amber" />
          {degradedNotice(LENS_MODE[lens], first.degraded_reason)}
        </p>
      ) : null}
      {filters.minMonthlyUsd ? (
        <p className="mt-3 text-[12.5px] text-subtle">
          Salary filter: at least ${filters.minMonthlyUsd.toLocaleString()} a month (${(filters.minMonthlyUsd * MONTHS_PER_YEAR).toLocaleString()} a year) in USD, compared with the salary extracted from each posting, annualised by its pay period. Postings without an extracted USD salary are left out; other currencies are not converted.
        </p>
      ) : null}

      <div className="mt-4">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} className="rounded-[14px] border border-line bg-surface" />
        ) : query.isLoading ? (
          <div className={cn(view === 'grid' ? 'grid gap-4 md:grid-cols-2' : 'space-y-4')}>{[0, 1, 2, 3].map((i) => <JobCardSkeleton key={i} variant={view} />)}</div>
        ) : shown.length === 0 ? (
          <EmptyState
            className="rounded-[14px] border border-line bg-surface"
            icon={<SearchX />}
            title={browsing ? 'No listed jobs' : 'No jobs found'}
            description={browsing ? 'No listed job fits these filters yet.' : 'Try fewer words, a broader role, or remove some filters.'}
            action={filterCount ? <Button onClick={() => update({ filters: EMPTY_FILTERS })}>Clear filters</Button> : undefined}
          />
        ) : (
          <div className={cn(view === 'grid' ? 'grid grid-cols-1 gap-4 md:grid-cols-2' : 'space-y-4')}>
            <AnimatePresence mode="popLayout" initial={false}>
              {shown.map((item, index) => (
                <JobCard key={item.job_id} job={item} match={matchIndex.get(item.job_id) ?? null} matchedBy={'matched_by' in item ? item.matched_by : undefined} variant={view} index={index % 20} />
              ))}
            </AnimatePresence>
          </div>
        )}
        {query.hasNextPage ? (
          <div className="mt-6 flex justify-center">
            <Button variant="outline" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>
              {query.isFetchingNextPage ? <LoaderCircle className="animate-spin" /> : null}
              {browsing ? 'Load more jobs' : 'Load more results'}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
