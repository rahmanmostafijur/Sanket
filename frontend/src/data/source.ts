import type { ApiConfig } from '@/api/client'
import * as api from '@/api/endpoints'
import type {
  JobDetail,
  JobListParams,
  JobListResponse,
  Match,
  Profile,
  ProfileWrite,
  SavedJobItem,
  SavedJobList,
  SearchParams,
  SearchResponse,
} from '@/api/types'

/** Where the UI reads its data: the Sanket API. Pages only talk to this interface. */
export interface DataSource {
  health: (signal?: AbortSignal) => Promise<void>
  search: (params: SearchParams, signal?: AbortSignal) => Promise<SearchResponse>
  /** Listed jobs without a query. */
  listJobs: (params: JobListParams, signal?: AbortSignal) => Promise<JobListResponse>
  /** One job with its description and every listing; rejects with a 404 ApiError when unknown. */
  getJob: (jobId: number, signal?: AbortSignal) => Promise<JobDetail>
  listSavedJobs: (signal?: AbortSignal) => Promise<SavedJobList>
  saveJob: (jobId: number) => Promise<SavedJobItem>
  unsaveJob: (jobId: number) => Promise<void>
  listProfiles: (signal?: AbortSignal) => Promise<Profile[]>
  createProfile: (profile: ProfileWrite) => Promise<Profile>
  replaceProfile: (id: number, profile: ProfileWrite) => Promise<Profile>
  deleteProfile: (id: number) => Promise<void>
  /** Every active match of a profile, oldest first (as the API pages them). */
  listAllMatches: (profileId: number, signal?: AbortSignal) => Promise<Match[]>
}

/** Pages of 100; a profile rarely has more than a few hundred active matches. */
const MATCH_PAGE = 100
const MAX_MATCH_PAGES = 10

export function apiSource(config: ApiConfig): DataSource {
  return {
    health: async (signal) => {
      await api.getHealth(config, signal)
    },
    search: (params, signal) => api.searchJobs(config, params, signal),
    listJobs: (params, signal) => api.listJobs(config, params, signal),
    getJob: (jobId, signal) => api.getJob(config, jobId, signal),
    listSavedJobs: (signal) => api.listSavedJobs(config, signal),
    saveJob: (jobId) => api.saveJob(config, jobId),
    unsaveJob: (jobId) => api.unsaveJob(config, jobId),
    listProfiles: (signal) => api.listProfiles(config, signal),
    createProfile: (profile) => api.createProfile(config, profile),
    replaceProfile: (id, profile) => api.replaceProfile(config, id, profile),
    deleteProfile: (id) => api.deleteProfile(config, id),
    listAllMatches: async (profileId, signal) => {
      const all: Match[] = []
      let afterId = 0
      for (let page = 0; page < MAX_MATCH_PAGES; page += 1) {
        const body = await api.listMatches(config, profileId, { afterId, limit: MATCH_PAGE, signal })
        all.push(...body.items)
        if (!body.has_more || body.next_after_id === null) break
        afterId = body.next_after_id
      }
      return all
    },
  }
}
