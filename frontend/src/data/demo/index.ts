import { ApiError } from '@/api/client'
import type {
  Job,
  JobDetail,
  JobFilterParams,
  JobListParams,
  JobListResponse,
  Match,
  MatchComponents,
  MatchEvent,
  Profile,
  ProfileWrite,
  Salary,
  SavedJobItem,
  SavedJobList,
  SearchItem,
  SearchParams,
  SearchResponse,
} from '@/api/types'
import type { DataSource } from '@/data/source'
import { jobDate } from '@/lib/format'
import { savedKey, useSaved } from '@/stores/saved'
import { DEMO_JOBS, demoIncomingJob } from './jobs'

/**
 * DEMO DATA SOURCE. Answers in the browser from fictional fixtures so the interface can be
 * explored without an API. Scores follow the shape of the real scorer
 * (backend/src/sanket/matching/score.py) but are computed from made-up inputs.
 */

export const DEMO_PERSONA = { name: 'Emon Hasan', email: 'emon@example.com' } as const

const DEMO_PROFILE_ID = 1
const LOADED_AT = new Date().toISOString()

let profiles: Profile[] = [
  {
    id: DEMO_PROFILE_ID,
    name: 'Python backend',
    active: true,
    desired_titles: ['Senior Python Backend Engineer', 'Backend Engineer'],
    required_skills: ['Python', 'FastAPI', 'PostgreSQL'],
    preferred_skills: ['Docker', 'AWS', 'Kubernetes', 'Redis'],
    seniorities: ['mid', 'senior'],
    work_modes: ['remote', 'hybrid'],
    employment_types: ['full_time', 'contract'],
    countries: [],
    locations: [],
    summary: 'Backend engineer focused on Python services, APIs and data-heavy systems.',
    min_score_override: null,
    embedding_status: 'ready',
    created_at: LOADED_AT,
    updated_at: LOADED_AT,
  },
]

const WEIGHTS = { cosine: 0.5, skills: 0.35, title: 0.15 }
const THRESHOLD = 0.6

function hash(text: string): number {
  let value = 0
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0
  return value
}

function titleOverlap(profile: Profile, job: Job): number {
  const words = new Set(job.title.toLowerCase().split(/\W+/).filter(Boolean))
  const scores = profile.desired_titles.map((title) => {
    const wanted = title.toLowerCase().split(/\W+/).filter(Boolean)
    return wanted.length ? wanted.filter((word) => words.has(word)).length / wanted.length : 0
  })
  return Math.max(0, ...scores)
}

export function demoScore(profile: Profile, job: Job): { score: number; components: MatchComponents } {
  const jobSkills = new Set((job.extracted?.skills ?? []).map((skill) => skill.toLowerCase()))
  const has = (skill: string) => jobSkills.has(skill.toLowerCase())
  const requiredHits = profile.required_skills.filter(has)
  const requiredMissing = profile.required_skills.filter((skill) => !has(skill))
  const preferredHits = profile.preferred_skills.filter(has)
  const reqPart = profile.required_skills.length ? requiredHits.length / profile.required_skills.length : 1
  const prefPart = profile.preferred_skills.length ? preferredHits.length / profile.preferred_skills.length : 0
  const skillsPart = reqPart * 0.75 + prefPart * 0.25
  const title = titleOverlap(profile, job)
  const cosine = 0.62 + (hash(job.title + job.company) % 30) / 100
  const score = cosine * WEIGHTS.cosine + skillsPart * WEIGHTS.skills + title * WEIGHTS.title
  const round = (value: number) => Math.round(value * 1000) / 1000
  const filter = (wanted: readonly string[], actual: string | null | undefined) =>
    wanted.length === 0 ? 'na' : !actual || actual === 'unknown' ? 'unknown' : wanted.includes(actual) ? 'pass' : 'fail'
  return {
    score: round(Math.min(1, score)),
    components: {
      cosine: { value: round(cosine), part: round(cosine), weight: WEIGHTS.cosine, min: 0.5, ok: true },
      skills: {
        part: round(skillsPart),
        weight: WEIGHTS.skills,
        required_hits: requiredHits,
        required_missing: requiredMissing,
        preferred_hits: preferredHits,
        job_skills_known: jobSkills.size > 0,
      },
      title: { part: round(title), weight: WEIGHTS.title, best: profile.desired_titles[0] ?? null },
      filters: {
        seniority: filter(profile.seniorities, job.extracted?.seniority),
        work_mode: filter(profile.work_modes, job.extracted?.work_mode),
        employment_type: filter(profile.employment_types, job.extracted?.employment_type),
        country: 'na',
        required_skills: requiredHits.length * 3 >= profile.required_skills.length * 2 ? 'pass' : 'fail',
      },
      unknown_fields: [],
      location_match: null,
      threshold: THRESHOLD,
    },
  }
}

export function demoMatch(profile: Profile, job: Job, id: number): Match {
  const { score, components } = demoScore(profile, job)
  return { id, job_id: job.job_id, score, status: 'active', components, created_at: job.first_seen_at, updated_at: job.first_seen_at, job }
}

function currentProfile(): Profile | undefined {
  return profiles.find((profile) => profile.id === DEMO_PROFILE_ID) ?? profiles[0]
}

function demoMatches(profile: Profile): Match[] {
  return DEMO_JOBS.map((job, index) => demoMatch(profile, job, index + 1))
    .filter((match) => match.score >= THRESHOLD && match.components.filters?.required_skills === 'pass')
    .sort((a, b) => a.id - b.id)
}

const YEARLY_FACTOR: Record<string, number> = { hour: 2080, day: 260, week: 52, month: 12, year: 1 }

/** The same annualisation the API applies to `salary_min`. */
function annualSalary(salary: Salary | null | undefined, currency: string): number | null {
  if (!salary || salary.currency?.toUpperCase() !== currency.toUpperCase() || !salary.period) return null
  const factor = YEARLY_FACTOR[salary.period]
  const amount = salary.max_amount ?? salary.min_amount
  return factor === undefined || amount == null ? null : amount * factor
}

function matchesFilters(job: Job, params: JobFilterParams): boolean {
  const ex = job.extracted
  const inList = <T extends string>(list: readonly T[] | undefined, value: string | null | undefined) =>
    !list?.length || (value != null && (list as readonly string[]).includes(value))
  const salary = ex?.salary
  const hasAmount = salary?.max_amount != null || salary?.min_amount != null
  const annual = params.salary_min != null && params.salary_currency ? annualSalary(salary, params.salary_currency) : null
  return (
    inList(params.work_mode, ex?.work_mode) &&
    inList(params.seniority, ex?.seniority) &&
    inList(params.employment_type, ex?.employment_type) &&
    inList(params.source, job.source) &&
    (!params.has_salary || hasAmount) &&
    (params.salary_min == null || (annual != null && annual >= params.salary_min))
  )
}

const byDate = (direction: 1 | -1) => (a: Job, b: Job) => direction * (Date.parse(jobDate(b)) - Date.parse(jobDate(a)))

function page<T>(items: readonly T[], params: { limit?: number; offset?: number }) {
  const offset = params.offset ?? 0
  const limit = params.limit ?? 20
  return { limit, offset, has_more: offset + limit < items.length, items: items.slice(offset, offset + limit) }
}

function demoSearch(params: SearchParams): SearchResponse {
  const terms = params.q.toLowerCase().split(/\W+/).filter((term) => term.length > 2)
  const mode = params.mode ?? 'hybrid'
  const scored = DEMO_JOBS.filter((job) => matchesFilters(job, params)).map((job) => {
    const haystack = [job.title, job.company, ...(job.extracted?.skills ?? [])].join(' ').toLowerCase()
    const hits = terms.filter((term) => haystack.includes(term)).length
    const titleHit = terms.some((term) => job.title.toLowerCase().includes(term))
    const matchedBy = mode === 'keyword' ? 'text' : mode === 'semantic' ? 'vector' : titleHit ? 'both' : hits ? 'text' : 'vector'
    const item: SearchItem = { ...job, score: hits / Math.max(1, terms.length), matched_by: matchedBy }
    return item
  })
  const ranked = scored
    .filter((item) => item.score > 0 || terms.length === 0)
    .sort(params.sort === 'newest' ? byDate(1) : (a, b) => b.score - a.score)
  return {
    query: params.q,
    total_candidates: ranked.length,
    degraded: false,
    degraded_reason: null,
    ...page(ranked, params),
  }
}

function demoListJobs(params: JobListParams): JobListResponse {
  const listed = DEMO_JOBS.filter((job) => matchesFilters(job, params)).sort(byDate(params.sort === 'oldest' ? -1 : 1))
  return { total: listed.length, ...page(listed, params) }
}

function demoJob(jobId: number): Job {
  const job = DEMO_JOBS.find((candidate) => candidate.job_id === jobId)
  if (!job) throw new ApiError(404, 'not_found', 'This demo job does not exist.')
  return job
}

/** Demo listings carry no description and link nowhere. */
function demoDetail(jobId: number): JobDetail {
  const job = demoJob(jobId)
  const postings = job.sources.map((ref) => ({ source: ref.source, name: ref.name, url: job.url, attribution: job.attribution, published_at: job.published_at }))
  return { ...job, description: null, postings }
}

/** Demo saved jobs stay in this browser, in the same local store the demo UI uses. */
function demoSavedList(): SavedJobList {
  const items: SavedJobItem[] = Object.entries(useSaved.getState().items)
    .filter(([key, entry]) => key === savedKey('demo', entry.job.job_id))
    .map(([, entry]) => ({ job_id: entry.job.job_id, saved_at: entry.savedAt, job: entry.job }))
  return { items: items.sort((a, b) => Date.parse(b.saved_at) - Date.parse(a.saved_at)) }
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const demoSource: DataSource = {
  kind: 'demo',
  health: async () => undefined,
  search: async (params) => {
    await delay(280)
    return demoSearch(params)
  },
  listJobs: async (params) => {
    await delay(220)
    return demoListJobs(params)
  },
  getJob: async (jobId) => {
    await delay(150)
    return demoDetail(jobId)
  },
  listSavedJobs: async () => demoSavedList(),
  saveJob: async (jobId) => {
    const existing = demoSavedList().items.find((item) => item.job_id === jobId)
    if (existing) return existing
    const job = demoJob(jobId)
    useSaved.getState().toggle(job, null)
    return { job_id: jobId, saved_at: new Date().toISOString(), job }
  },
  unsaveJob: async (jobId) => {
    useSaved.getState().remove(jobId)
  },
  listProfiles: async () => {
    await delay(120)
    return profiles
  },
  createProfile: async (write: ProfileWrite) => {
    const now = new Date().toISOString()
    const created: Profile = { ...write, id: Math.max(0, ...profiles.map((p) => p.id)) + 1, embedding_status: 'ready', created_at: now, updated_at: now }
    profiles = [...profiles, created]
    return created
  },
  replaceProfile: async (id, write) => {
    const existing = profiles.find((profile) => profile.id === id)
    if (!existing) throw new Error('profile not found')
    const updated: Profile = { ...existing, ...write, updated_at: new Date().toISOString() }
    profiles = profiles.map((profile) => (profile.id === id ? updated : profile))
    return updated
  },
  deleteProfile: async (id) => {
    profiles = profiles.filter((profile) => profile.id !== id)
  },
  listAllMatches: async (profileId) => {
    await delay(200)
    const profile = profiles.find((p) => p.id === profileId) ?? currentProfile()
    return profile ? demoMatches(profile) : []
  },
}

/** The next simulated live match, scored against the current demo profile. */
export function nextDemoEvent(sequence: number, profileId: number): MatchEvent | null {
  const profile = profiles.find((p) => p.id === profileId) ?? currentProfile()
  if (!profile) return null
  const job = demoIncomingJob(sequence)
  const match = demoMatch(profile, job, 1000 + sequence)
  return { ...match, created_at: new Date().toISOString(), reactivated: false }
}
