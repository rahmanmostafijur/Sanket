import type { Salary } from '@/api/types'
import { formatSalary, matchTier, monthlyUsd, percent, relativeTime } from './format'

const salary = (overrides: Partial<Salary>): Salary => ({ min_amount: null, max_amount: null, currency: 'USD', period: 'month', ...overrides })
const job = (s: Salary | null, text: string | null = null) => ({
  salary_text: text,
  extracted: { work_mode: null, seniority: null, employment_type: null, country: null, city: null, skills: [], min_years_experience: null, salary: s },
})

describe('formatSalary', () => {
  it('formats a range compactly with its period', () => {
    expect(formatSalary(job(salary({ min_amount: 4000, max_amount: 6000 })))).toBe('$4k – $6k / month')
  })
  it('handles a single bound and other currencies', () => {
    expect(formatSalary(job(salary({ min_amount: 90000, currency: 'EUR', period: 'year' })))).toBe('€90k / year')
    expect(formatSalary(job(salary({ max_amount: 50, currency: 'CHF', period: 'hour' })))).toBe('Up to CHF 50 / hour')
  })
  it('falls back to the posting text, shortened', () => {
    expect(formatSalary(job(null, 'Competitive'))).toBe('Competitive')
    expect(formatSalary(job(null, 'x'.repeat(80)))?.endsWith('…')).toBe(true)
  })
  it('returns null when nothing is known', () => {
    expect(formatSalary(job(null))).toBeNull()
  })
})

describe('monthlyUsd', () => {
  it('normalises USD salaries to a month', () => {
    expect(monthlyUsd(salary({ max_amount: 120000, period: 'year' }))).toBe(10000)
    expect(monthlyUsd(salary({ min_amount: 50, period: 'hour' }))).toBe(8000)
  })
  it('does not convert other currencies or salaries without a period', () => {
    expect(monthlyUsd(salary({ max_amount: 5000, currency: 'EUR' }))).toBeNull()
    expect(monthlyUsd(salary({ max_amount: 5000, period: null }))).toBeNull()
  })
})

describe('relativeTime', () => {
  const now = Date.parse('2026-11-24T12:00:00Z')
  it.each([
    ['2026-11-24T11:59:30Z', 'just now'],
    ['2026-11-24T11:55:00Z', '5m ago'],
    ['2026-11-24T09:00:00Z', '3h ago'],
    ['2026-11-22T12:00:00Z', '2d ago'],
  ])('%s is %s', (iso, expected) => {
    expect(relativeTime(iso, now)).toBe(expected)
  })
  it('is empty for missing or invalid dates', () => {
    expect(relativeTime(null, now)).toBe('')
    expect(relativeTime('not a date', now)).toBe('')
  })
})

describe('scores', () => {
  it('clamps to a whole percentage', () => {
    expect(percent(0.916)).toBe(92)
    expect(percent(1.4)).toBe(100)
    expect(percent(-1)).toBe(0)
  })
  it('puts scores in tiers', () => {
    expect([matchTier(0.9), matchTier(0.75), matchTier(0.5)]).toEqual(['strong', 'good', 'fair'])
  })
})
