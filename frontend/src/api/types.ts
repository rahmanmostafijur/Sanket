/**
 * Types that mirror the Sanket API contracts (backend/src/sanket/api/schemas.py and
 * profile_schemas.py). Keep them in step with the backend; nothing here is invented.
 * Dates are ISO 8601 strings as the API sends them.
 */

export const WORK_MODES = ['remote', 'hybrid', 'onsite', 'unknown'] as const
export const SENIORITIES = ['intern', 'junior', 'mid', 'senior', 'lead', 'unknown'] as const
export const EMPLOYMENT_TYPES = [
  'full_time',
  'part_time',
  'contract',
  'internship',
  'unknown',
] as const

export type WorkMode = (typeof WORK_MODES)[number]
export type Seniority = (typeof SENIORITIES)[number]
export type EmploymentType = (typeof EMPLOYMENT_TYPES)[number]
export type MatchedBy = 'text' | 'vector' | 'both'

export interface Salary {
  min_amount: number | null
  max_amount: number | null
  currency: string | null
  /** hour, day, week, month or year; null if unstated. */
  period: string | null
}

export interface Extracted {
  work_mode: string | null
  seniority: string | null
  employment_type: string | null
  country: string | null
  city: string | null
  skills: string[]
  min_years_experience: number | null
  salary: Salary | null
}

export interface SourceRef {
  source: string
  name: string
}

/** The job fields shared by search results and matched jobs. */
export interface Job {
  job_id: number
  title: string
  company: string
  location: string | null
  source: string | null
  source_name: string | null
  url: string | null
  attribution: string | null
  sources: SourceRef[]
  published_at: string | null
  first_seen_at: string
  salary_text: string | null
  extracted: Extracted | null
}

export interface SearchItem extends Job {
  score: number
  matched_by: MatchedBy
}

export interface SearchResponse {
  query: string
  limit: number
  offset: number
  total_candidates: number
  has_more: boolean
  degraded: boolean
  degraded_reason: string | null
  items: SearchItem[]
}

export type SearchMode = 'hybrid' | 'keyword' | 'semantic'
export type SearchSort = 'relevance' | 'newest'
export type JobListSort = 'newest' | 'oldest'

/** Filters shared by `GET /search` and `GET /jobs`. */
export interface JobFilterParams {
  work_mode?: WorkMode[]
  seniority?: Seniority[]
  employment_type?: EmploymentType[]
  source?: string[]
  country?: string[]
  location?: string
  company?: string
  skills?: string[]
  posted_after?: string
  /** Annual amount; jobs match on their extracted salary annualised by its period. */
  salary_min?: number
  /** 3-letter ISO code, required with `salary_min`. */
  salary_currency?: string
  /** true keeps only jobs with an extracted salary amount. */
  has_salary?: boolean
}

export interface SearchParams extends JobFilterParams {
  q: string
  limit?: number
  offset?: number
  /** hybrid (default) fuses full-text and vector retrieval; keyword and semantic use one each. */
  mode?: SearchMode
  /** Applied over every candidate before paging. */
  sort?: SearchSort
}

export interface JobListParams extends JobFilterParams {
  limit?: number
  offset?: number
  sort?: JobListSort
}

export interface JobListResponse {
  limit: number
  offset: number
  total: number
  has_more: boolean
  items: Job[]
}

/** One listing of a job on a source. */
export interface JobPosting {
  source: string
  name: string
  url: string | null
  attribution: string | null
  published_at: string | null
}

export interface JobDetail extends Job {
  /** Plain text, paragraphs separated by blank lines. Never HTML. */
  description: string | null
  postings: JobPosting[]
}

export interface SavedJobItem {
  job_id: number
  saved_at: string
  /** null when the job was removed after it was saved. */
  job: Job | null
}

export interface SavedJobList {
  /** Newest first. */
  items: SavedJobItem[]
}

export type EmbeddingStatus = 'pending' | 'ready' | 'failed'
/** Why a profile is still "pending" or "failed": the provider's quota ran out, or another step failed. */
export type EmbeddingNote = 'quota' | 'error'

export interface ProfileCriteria {
  desired_titles: string[]
  required_skills: string[]
  preferred_skills: string[]
  seniorities: Seniority[]
  work_modes: WorkMode[]
  employment_types: EmploymentType[]
  countries: string[]
  locations: string[]
  summary: string
  min_score_override: number | null
}

export interface ProfileWrite extends ProfileCriteria {
  name: string
  active: boolean
}

export interface Profile extends ProfileWrite {
  id: number
  embedding_status: EmbeddingStatus
  embedding_note?: EmbeddingNote | null
  created_at: string
  updated_at: string
}

export type FilterState = 'na' | 'pass' | 'unknown' | 'fail'

/** `components` of a match, as written by backend/src/sanket/matching/score.py. */
export interface MatchComponents {
  cosine?: { value: number; part: number; weight: number; min: number; ok: boolean }
  skills?: {
    part: number | null
    weight: number
    required_hits: string[]
    required_missing: string[]
    preferred_hits: string[]
    job_skills_known: boolean
  }
  title?: { part: number | null; weight: number; best: string | null }
  filters?: Partial<Record<string, FilterState>>
  unknown_fields?: string[]
  location_match?: boolean | null
  threshold?: number
}

export interface Match {
  id: number
  job_id: number
  /** 0 to 1. */
  score: number
  status: 'active' | 'withdrawn'
  components: MatchComponents
  created_at: string
  updated_at: string
  job: Job | null
}

export interface MatchEvent extends Match {
  reactivated: boolean
}

export interface MatchList {
  items: Match[]
  next_after_id: number | null
  has_more: boolean
}

export interface StreamToken {
  token: string
  expires_in: number
  path: string
  query_parameter: string
}

/** The error envelope every API error uses (backend/src/sanket/api/errors.py). */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    request_id?: string | null
    details?: { loc?: (string | number)[]; msg?: string; type?: string }[]
  }
}

/** What sign-up and sign-in send. */
export interface Credentials {
  email: string
  password: string
}

/** A signed-in session: a short-lived bearer token for the account. */
export interface AccessToken {
  access_token: string
  token_type: string
  expires_in: number
  email: string
}

/** The signed-in account (`GET /me`); empty strings when unset. The name and headline come from the career profile. */
export interface Me {
  email: string
  full_name: string
  headline: string
}

export type Availability = 'immediately' | 'within_one_month' | 'open_to_offers' | 'not_looking'
export type SkillLevel = 'beginner' | 'intermediate' | 'advanced' | 'expert'
export type LanguageProficiency = 'basic' | 'conversational' | 'fluent' | 'native'

/** The career profile's personal part. Optional text is "" and never null. */
export interface CareerPersonal {
  full_name: string
  headline: string
  summary: string
  country: string
  city: string
  github_url: string
  linkedin_url: string
  portfolio_url: string
  availability: Availability | null
}

/** Dates are "YYYY-MM". */
export interface EducationInput {
  institution: string
  degree: string
  field: string
  start: string
  end: string | null
  grade: string
}

export interface ExperienceInput {
  company: string
  title: string
  start: string
  end: string | null
  current: boolean
  description: string
}

export interface SkillInput {
  name: string
  level: SkillLevel | null
}

export interface LanguageInput {
  name: string
  proficiency: LanguageProficiency
}

export interface CertificationInput {
  title: string
  issuer: string
  year: number | null
  url: string
}

export interface ProjectInput {
  title: string
  description: string
  url: string
}

type WithId<T> = T & { id: number }

export type Education = WithId<EducationInput>
export type Experience = WithId<ExperienceInput>
export type Skill = WithId<SkillInput>
export type Language = WithId<LanguageInput>
export type Certification = WithId<CertificationInput>
export type Project = WithId<ProjectInput>

/** The sections the completeness figure counts. */
export type CareerSectionKey = 'personal' | 'education' | 'experience' | 'skills' | 'languages' | 'certifications' | 'projects'

export interface Completeness {
  percent: number
  sections: Record<CareerSectionKey, boolean>
  missing: CareerSectionKey[]
}

/** The whole career profile (`GET /career`). */
export interface Career {
  personal: CareerPersonal
  education: Education[]
  experience: Experience[]
  skills: Skill[]
  languages: Language[]
  certifications: Certification[]
  projects: Project[]
  completeness: Completeness
  years_of_experience: number | null
}

/** The sections stored as a list; each is replaced as a whole by `PUT /career/{section}`. */
export type CareerListKey = Exclude<CareerSectionKey, 'personal'>

/** The item a list section sends, by section. */
export interface CareerListInputs {
  education: EducationInput
  experience: ExperienceInput
  skills: SkillInput
  languages: LanguageInput
  certifications: CertificationInput
  projects: ProjectInput
}

/** What `POST /career/matching-draft` suggests for a matching profile. Nothing is created. */
export interface MatchingDraft {
  desired_titles: string[]
  required_skills: string[]
  preferred_skills: string[]
  seniorities: Seniority[]
  locations: string[]
  years_of_experience: number | null
}

/** What `POST /cv/import` reads out of a CV. Nothing in it is saved by the API. */
export type CvProposal = {
  personal: Omit<CareerPersonal, 'availability'>
} & { [K in CareerListKey]: CareerListInputs[K][] }
