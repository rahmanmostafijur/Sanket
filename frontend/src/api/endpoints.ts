import { apiRequest, buildUrl, type ApiConfig } from './client'
import type {
  AccessToken,
  Credentials,
  CvProposal,
  JobDetail,
  JobListParams,
  JobListResponse,
  Me,
  MatchList,
  PersonalInfo,
  Profile,
  ProfileWrite,
  SavedJobItem,
  SavedJobList,
  SearchParams,
  SearchResponse,
  StreamToken,
} from './types'

/** Every call the frontend makes to the Sanket API. Paths match backend/src/sanket/api/routers. */

export function getHealth(config: ApiConfig, signal?: AbortSignal): Promise<unknown> {
  return apiRequest(config, '/healthz', { signal })
}

/** Creates an account and returns a token for it. A 401 here is not a lost session, so it is not reported. */
export function signUp(config: ApiConfig, credentials: Credentials): Promise<AccessToken> {
  return apiRequest(config, '/auth/signup', { method: 'POST', body: credentials, reportUnauthorized: false })
}

/** Signs in with an email and password. A wrong password is a 401 that must stay on the sign-in page. */
export function logIn(config: ApiConfig, credentials: Credentials): Promise<AccessToken> {
  return apiRequest(config, '/auth/login', { method: 'POST', body: credentials, reportUnauthorized: false })
}

/** The signed-in account; a 404 means the credential is not an account (API key). */
export function getMe(config: ApiConfig, signal?: AbortSignal): Promise<Me> {
  return apiRequest(config, '/me', { signal })
}

export function updateMe(config: ApiConfig, info: PersonalInfo): Promise<Me> {
  return apiRequest(config, '/me', { method: 'PUT', body: info })
}

/** Reads a PDF or DOCX and returns what it says. The API saves nothing. */
export function importCv(config: ApiConfig, file: File): Promise<CvProposal> {
  return apiRequest(config, '/cv/import', { method: 'POST', rawBody: file })
}

export function searchJobs(
  config: ApiConfig,
  params: SearchParams,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const { q, ...rest } = params
  return apiRequest(config, '/search', { query: { q, ...rest }, signal })
}

/** Browse listed jobs without a query, newest first by default. */
export function listJobs(
  config: ApiConfig,
  params: JobListParams,
  signal?: AbortSignal,
): Promise<JobListResponse> {
  return apiRequest(config, '/jobs', { query: { ...params }, signal })
}

export function getJob(config: ApiConfig, jobId: number, signal?: AbortSignal): Promise<JobDetail> {
  return apiRequest(config, `/jobs/${jobId}`, { signal })
}

export function listSavedJobs(config: ApiConfig, signal?: AbortSignal): Promise<SavedJobList> {
  return apiRequest(config, '/saved-jobs', { signal })
}

/** Idempotent: saving a job that is already saved returns the existing entry. */
export function saveJob(config: ApiConfig, jobId: number): Promise<SavedJobItem> {
  return apiRequest(config, `/saved-jobs/${jobId}`, { method: 'PUT' })
}

/** Idempotent: removing a job that is not saved succeeds. */
export function unsaveJob(config: ApiConfig, jobId: number): Promise<void> {
  return apiRequest(config, `/saved-jobs/${jobId}`, { method: 'DELETE' })
}

export async function listProfiles(config: ApiConfig, signal?: AbortSignal): Promise<Profile[]> {
  const body = await apiRequest<{ items: Profile[] }>(config, '/profiles', { signal })
  return body.items
}

export function createProfile(config: ApiConfig, profile: ProfileWrite): Promise<Profile> {
  return apiRequest(config, '/profiles', { method: 'POST', body: profile })
}

export function replaceProfile(config: ApiConfig, id: number, profile: ProfileWrite): Promise<Profile> {
  return apiRequest(config, `/profiles/${id}`, { method: 'PUT', body: profile })
}

export function deleteProfile(config: ApiConfig, id: number): Promise<void> {
  return apiRequest(config, `/profiles/${id}`, { method: 'DELETE' })
}

export function listMatches(
  config: ApiConfig,
  profileId: number,
  options: { afterId?: number; limit?: number; signal?: AbortSignal } = {},
): Promise<MatchList> {
  return apiRequest(config, `/profiles/${profileId}/matches`, {
    query: { after_id: options.afterId ?? 0, limit: options.limit ?? 100 },
    signal: options.signal,
  })
}

export function mintStreamToken(config: ApiConfig, profileId: number): Promise<StreamToken> {
  return apiRequest(config, '/auth/stream-token', { method: 'POST', body: { profile_id: profileId } })
}

export function feedPath(profileId: number): string {
  return `/profiles/${profileId}/matches/stream`
}

/** EventSource URL for a profile's feed, with an optional stream token and resume point. */
export function streamUrl(
  config: ApiConfig,
  profileId: number,
  options: { token?: StreamToken | null; lastEventId?: number | null } = {},
): string {
  const { token, lastEventId } = options
  return buildUrl(config.baseUrl, token?.path ?? feedPath(profileId), {
    ...(token ? { [token.query_parameter]: token.token } : {}),
    last_event_id: lastEventId ?? undefined,
  })
}
