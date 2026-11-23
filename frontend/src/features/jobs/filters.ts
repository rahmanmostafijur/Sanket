import type { EmploymentType, Job, Seniority, WorkMode } from '@/api/types'
import { monthlyUsd } from '@/lib/format'

/**
 * The filters shared by the dashboard and Discover. Work mode, seniority, employment type and
 * source map onto `GET /search` and `GET /jobs` parameters; Discover sends `minMonthlyUsd` as
 * `salary_min` (times 12, in USD). Lists that do not come from the API filter in the browser.
 */
export interface JobFilters {
  workModes: WorkMode[]
  seniorities: Seniority[]
  employmentTypes: EmploymentType[]
  sources: string[]
  minMonthlyUsd: number | null
}

export const EMPTY_FILTERS: JobFilters = {
  workModes: [],
  seniorities: [],
  employmentTypes: [],
  sources: [],
  minMonthlyUsd: null,
}

export const SALARY_STEPS = [2000, 4000, 6000, 8000] as const

export function activeFilterCount(filters: JobFilters): number {
  return (
    filters.workModes.length +
    filters.seniorities.length +
    filters.employmentTypes.length +
    filters.sources.length +
    (filters.minMonthlyUsd ? 1 : 0)
  )
}

export function toggleValue<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
}

function inList(list: readonly string[], value: string | null | undefined): boolean {
  return list.length === 0 || (value != null && list.includes(value))
}

/** Every filter applied in the browser (for lists that do not come from `GET /search`). */
export function matchesFilters(job: Job, filters: JobFilters): boolean {
  const ex = job.extracted
  return (
    inList(filters.workModes, ex?.work_mode) &&
    inList(filters.seniorities, ex?.seniority) &&
    inList(filters.employmentTypes, ex?.employment_type) &&
    (filters.sources.length === 0 || job.sources.some((s) => filters.sources.includes(s.source)) || inList(filters.sources, job.source)) &&
    passesSalary(job, filters.minMonthlyUsd)
  )
}

/** The salary floor alone: jobs without a comparable USD salary are left out when it is set. */
export function passesSalary(job: Job, minMonthlyUsd: number | null): boolean {
  if (!minMonthlyUsd) return true
  const monthly = monthlyUsd(job.extracted?.salary)
  return monthly != null && monthly >= minMonthlyUsd
}

const PARAM = {
  workModes: 'work_mode',
  seniorities: 'seniority',
  employmentTypes: 'employment_type',
  sources: 'source',
  minMonthlyUsd: 'min_salary',
} as const

export function filtersFromParams(params: URLSearchParams): JobFilters {
  const salary = Number(params.get(PARAM.minMonthlyUsd))
  return {
    workModes: params.getAll(PARAM.workModes) as WorkMode[],
    seniorities: params.getAll(PARAM.seniorities) as Seniority[],
    employmentTypes: params.getAll(PARAM.employmentTypes) as EmploymentType[],
    sources: params.getAll(PARAM.sources),
    minMonthlyUsd: Number.isFinite(salary) && salary > 0 ? salary : null,
  }
}

/** URL params for `filters`, keeping unrelated params (such as `q`) of `base`. */
export function filtersToParams(filters: JobFilters, base: URLSearchParams = new URLSearchParams()): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const key of Object.values(PARAM)) next.delete(key)
  for (const value of filters.workModes) next.append(PARAM.workModes, value)
  for (const value of filters.seniorities) next.append(PARAM.seniorities, value)
  for (const value of filters.employmentTypes) next.append(PARAM.employmentTypes, value)
  for (const value of filters.sources) next.append(PARAM.sources, value)
  if (filters.minMonthlyUsd) next.set(PARAM.minMonthlyUsd, String(filters.minMonthlyUsd))
  return next
}
