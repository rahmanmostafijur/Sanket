import type { Job } from '@/api/types'
import { activeFilterCount, EMPTY_FILTERS, filtersFromParams, filtersToParams, matchesFilters, toggleValue, type JobFilters } from './filters'

function job(extracted: Partial<NonNullable<Job['extracted']>>, source = 'remoteok'): Job {
  return {
    job_id: 1,
    title: 'Engineer',
    company: 'Acme',
    location: null,
    source,
    source_name: source,
    url: null,
    attribution: null,
    sources: [{ source, name: source }],
    published_at: null,
    first_seen_at: '2026-11-01T00:00:00Z',
    salary_text: null,
    extracted: { work_mode: null, seniority: null, employment_type: null, country: null, city: null, skills: [], min_years_experience: null, salary: null, ...extracted },
  }
}

const filters = (overrides: Partial<JobFilters>): JobFilters => ({ ...EMPTY_FILTERS, ...overrides })

describe('job filters', () => {
  it('round-trips through URL params and keeps unrelated params', () => {
    const value = filters({ workModes: ['remote', 'hybrid'], seniorities: ['senior'], sources: ['lever'], minMonthlyUsd: 4000 })
    const params = filtersToParams(value, new URLSearchParams('q=python'))
    expect(params.get('q')).toBe('python')
    expect(params.getAll('work_mode')).toEqual(['remote', 'hybrid'])
    expect(filtersFromParams(params)).toEqual(value)
  })

  it('ignores a salary param that is not a positive number', () => {
    expect(filtersFromParams(new URLSearchParams('min_salary=abc')).minMonthlyUsd).toBeNull()
  })

  it('matches on the extracted fields and the source', () => {
    const remote = job({ work_mode: 'remote', seniority: 'senior' })
    expect(matchesFilters(remote, filters({ workModes: ['remote'] }))).toBe(true)
    expect(matchesFilters(remote, filters({ workModes: ['onsite'] }))).toBe(false)
    expect(matchesFilters(remote, filters({ sources: ['lever'] }))).toBe(false)
    expect(matchesFilters(remote, filters({ sources: ['remoteok'] }))).toBe(true)
  })

  it('drops jobs without a comparable salary when a salary floor is set', () => {
    const paid = job({ salary: { min_amount: 5000, max_amount: 6000, currency: 'USD', period: 'month' } })
    expect(matchesFilters(paid, filters({ minMonthlyUsd: 4000 }))).toBe(true)
    expect(matchesFilters(job({}), filters({ minMonthlyUsd: 4000 }))).toBe(false)
  })

  it('counts active filters and toggles values without mutating', () => {
    expect(activeFilterCount(filters({ workModes: ['remote'], minMonthlyUsd: 2000 }))).toBe(2)
    const list = ['a']
    expect(toggleValue(list, 'b')).toEqual(['a', 'b'])
    expect(toggleValue(list, 'a')).toEqual([])
    expect(list).toEqual(['a'])
  })
})
