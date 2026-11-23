import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { ApiError } from '@/api/client'
import type { Job, JobListParams, Match, Profile, ProfileWrite, SavedJobList, SearchParams } from '@/api/types'
import { demoSource } from '@/data/demo'
import { apiSource, type DataSource } from '@/data/source'
import { useJobRegistry } from '@/stores/jobRegistry'
import { useLiveFeed } from '@/stores/liveFeed'
import { savedKey, useSaved, useSavedEntries } from '@/stores/saved'
import { useApiConfig, useSession } from '@/stores/session'

const SEARCH_PAGE = 20

function fingerprint(text: string | null): string {
  if (!text) return 'anon'
  let value = 0
  for (const char of text) value = (value * 33 + char.charCodeAt(0)) >>> 0
  return value.toString(36)
}

/** The active data source and a key that changes whenever the source or credential does. */
export function useDataSource(): { source: DataSource; key: string } {
  const mode = useSession((s) => s.mode)
  const config = useApiConfig()
  return useMemo(
    () =>
      mode === 'demo'
        ? { source: demoSource, key: 'demo' }
        : { source: apiSource(config), key: `api|${config.baseUrl}|${fingerprint(config.token)}` },
    [mode, config],
  )
}

export function useHealth() {
  const { source, key } = useDataSource()
  return useQuery({
    queryKey: ['health', key],
    queryFn: ({ signal }) => source.health(signal).then(() => true),
    retry: 1,
    refetchInterval: source.kind === 'api' ? 30_000 : false,
  })
}

export function useProfiles() {
  const { source, key } = useDataSource()
  return useQuery({ queryKey: ['profiles', key], queryFn: ({ signal }) => source.listProfiles(signal) })
}

/** The profile the app works with: the one picked in the session, else the first active one. */
export function useActiveProfile(): {
  profile: Profile | null
  profiles: Profile[]
  isLoading: boolean
  error: unknown
} {
  const query = useProfiles()
  const pickedId = useSession((s) => s.activeProfileId)
  const profiles = useMemo(() => query.data ?? [], [query.data])
  const profile =
    profiles.find((p) => p.id === pickedId) ?? profiles.find((p) => p.active) ?? profiles[0] ?? null
  return { profile, profiles, isLoading: query.isLoading, error: query.error }
}

/**
 * Active matches of a profile, with the live events received since merged in, best first.
 * Every job seen is remembered so its detail page can render.
 */
export function useMatches(profileId: number | null | undefined) {
  const { source, key } = useDataSource()
  const received = useLiveFeed((s) => s.received)
  const remember = useJobRegistry((s) => s.remember)
  const query = useQuery({
    queryKey: ['matches', key, profileId],
    queryFn: ({ signal }) => source.listAllMatches(profileId as number, signal),
    enabled: profileId != null,
  })
  const matches = useMemo(() => {
    const byId = new Map<number, Match>()
    for (const match of query.data ?? []) byId.set(match.id, match)
    for (const { event } of received) if (event.status === 'active') byId.set(event.id, event)
    return [...byId.values()].filter((m) => m.status === 'active').sort((a, b) => b.score - a.score)
  }, [query.data, received])
  useEffect(() => {
    remember(matches.flatMap((match) => (match.job ? [match.job] : [])))
  }, [matches, remember])
  return { ...query, matches }
}

/** Best match per job id, to show a real match score next to search results. */
export function useMatchIndex(profileId: number | null | undefined): Map<number, Match> {
  const { matches } = useMatches(profileId)
  return useMemo(() => {
    const index = new Map<number, Match>()
    for (const match of matches) if (!index.has(match.job_id)) index.set(match.job_id, match)
    return index
  }, [matches])
}

export type SearchQuery = Omit<SearchParams, 'limit' | 'offset'>

export function useSearch(params: SearchQuery) {
  const { source, key } = useDataSource()
  const remember = useJobRegistry((s) => s.remember)
  const query = useInfiniteQuery({
    queryKey: ['search', key, params],
    queryFn: ({ pageParam, signal }: { pageParam: number; signal: AbortSignal }) =>
      source.search({ ...params, limit: SEARCH_PAGE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.has_more ? last.offset + last.limit : undefined),
    enabled: params.q.trim().length > 0,
    placeholderData: (previous) => previous,
  })
  useEffect(() => {
    const items = query.data?.pages.flatMap((page) => page.items) ?? []
    remember(items)
  }, [query.data, remember])
  return query
}

export type JobListQuery = Omit<JobListParams, 'limit' | 'offset'>

/** Listed jobs without a query (`GET /jobs`), paged like search. */
export function useJobList(params: JobListQuery, enabled = true) {
  const { source, key } = useDataSource()
  const remember = useJobRegistry((s) => s.remember)
  const query = useInfiniteQuery({
    queryKey: ['jobs', key, params],
    queryFn: ({ pageParam, signal }: { pageParam: number; signal: AbortSignal }) =>
      source.listJobs({ ...params, limit: SEARCH_PAGE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.has_more ? last.offset + last.limit : undefined),
    enabled,
    placeholderData: (previous) => previous,
  })
  useEffect(() => {
    remember(query.data?.pages.flatMap((page) => page.items) ?? [])
  }, [query.data, remember])
  return query
}

/** How many listed jobs pass `params` (`GET /jobs` with one item; its `total` counts them all). */
export function useJobTotal(params: JobListQuery, enabled = true) {
  const { source, key } = useDataSource()
  return useQuery({
    queryKey: ['jobs-total', key, params],
    queryFn: ({ signal }) => source.listJobs({ ...params, limit: 1, offset: 0 }, signal).then((page) => page.total),
    enabled,
  })
}

/** A 404 with the API's error envelope: the job does not exist or is no longer listed. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && !error.isUnavailable
}

/** One job with its description and every listing (`GET /jobs/{id}`). */
export function useJobDetail(jobId: number) {
  const { source, key } = useDataSource()
  return useQuery({
    queryKey: ['job', key, jobId],
    queryFn: ({ signal }) => source.getJob(jobId, signal),
    enabled: Number.isInteger(jobId) && jobId > 0,
  })
}

/** A saved job, from the server in API mode or from this browser in demo mode. */
export interface SavedEntry {
  jobId: number
  /** null when the job was removed after it was saved. */
  job: Job | null
  savedAt: string
  /** The match score recorded when it was saved (demo mode only). */
  matchScore: number | null
}

function useSavedQuery() {
  const { source, key } = useDataSource()
  const queryKey = useMemo(() => ['saved-jobs', key] as const, [key])
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => source.listSavedJobs(signal),
    enabled: source.kind === 'api',
  })
  return { source, queryKey, query }
}

/** Saved jobs of the current data mode, newest first. */
export function useSavedJobs(): {
  entries: SavedEntry[]
  isLoading: boolean
  error: unknown
  refetch: () => void
} {
  const { source, query } = useSavedQuery()
  const local = useSavedEntries()
  const entries = useMemo<SavedEntry[]>(() => {
    if (source.kind === 'demo') {
      return local
        .map((entry) => ({ jobId: entry.job.job_id, job: entry.job, savedAt: entry.savedAt, matchScore: entry.matchScore }))
        .sort((a, b) => Date.parse(b.savedAt) - Date.parse(a.savedAt))
    }
    return (query.data?.items ?? []).map((item) => ({ jobId: item.job_id, job: item.job, savedAt: item.saved_at, matchScore: null }))
  }, [source.kind, local, query.data])
  return {
    entries,
    isLoading: source.kind === 'api' && query.isLoading,
    error: source.kind === 'api' ? query.error : null,
    refetch: () => void query.refetch(),
  }
}

export function useIsSaved(jobId: number): boolean {
  const { entries } = useSavedJobs()
  return entries.some((entry) => entry.jobId === jobId)
}

interface SaveInput {
  jobId: number
  job: Job | null
  save: boolean
  matchScore?: number | null
}

/**
 * Saves or removes a job. API mode writes to the server with an optimistic update that is rolled
 * back on failure; demo mode writes to this browser.
 */
export function useSetSaved() {
  const { source, queryKey } = useSavedQuery()
  const client = useQueryClient()
  const localItems = useSaved((s) => s.items)
  const toggleLocal = useSaved((s) => s.toggle)
  const removeLocal = useSaved((s) => s.remove)
  const mutation = useMutation({
    mutationFn: async ({ jobId, save }: SaveInput) => {
      if (save) await source.saveJob(jobId)
      else await source.unsaveJob(jobId)
    },
    onMutate: async ({ jobId, job, save }: SaveInput) => {
      await client.cancelQueries({ queryKey })
      const previous = client.getQueryData<SavedJobList>(queryKey)
      client.setQueryData<SavedJobList>(queryKey, (current) => {
        const rest = (current?.items ?? []).filter((item) => item.job_id !== jobId)
        return { items: save ? [{ job_id: jobId, saved_at: new Date().toISOString(), job }, ...rest] : rest }
      })
      return { previous }
    },
    onError: (_error, _input, context) => client.setQueryData(queryKey, context?.previous),
    onSettled: () => void client.invalidateQueries({ queryKey }),
  })
  const setSaved = async (input: SaveInput): Promise<void> => {
    if (source.kind === 'api') return mutation.mutateAsync(input)
    const isSaved = savedKey('demo', input.jobId) in localItems
    if (input.save && !isSaved && input.job) toggleLocal(input.job, input.matchScore ?? null)
    if (!input.save && isSaved) removeLocal(input.jobId)
  }
  return { setSaved, isPending: mutation.isPending }
}

/** Removes every saved job of the current data mode. */
export function useClearSaved() {
  const { source, queryKey } = useSavedQuery()
  const client = useQueryClient()
  const { entries } = useSavedJobs()
  const clearLocal = useSaved((s) => s.clear)
  return async (): Promise<void> => {
    if (source.kind === 'demo') return clearLocal()
    try {
      await Promise.all(entries.map((entry) => source.unsaveJob(entry.jobId)))
    } finally {
      await client.invalidateQueries({ queryKey })
    }
  }
}

export function useSaveProfile() {
  const { source, key } = useDataSource()
  const client = useQueryClient()
  const setActive = useSession((s) => s.setActiveProfileId)
  return useMutation({
    mutationFn: ({ id, profile }: { id: number | null; profile: ProfileWrite }) =>
      id == null ? source.createProfile(profile) : source.replaceProfile(id, profile),
    onSuccess: (saved) => {
      setActive(saved.id)
      void client.invalidateQueries({ queryKey: ['profiles', key] })
      void client.invalidateQueries({ queryKey: ['matches', key] })
    },
  })
}

export function useDeleteProfile() {
  const { source, key } = useDataSource()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => source.deleteProfile(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['profiles', key] }),
  })
}
