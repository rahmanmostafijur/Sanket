import type { Job, Salary } from '@/api/types'

const WORK_MODE_LABELS: Record<string, string> = {
  remote: 'Remote',
  hybrid: 'Hybrid',
  onsite: 'On-site',
}
const SENIORITY_LABELS: Record<string, string> = {
  intern: 'Intern',
  junior: 'Junior',
  mid: 'Mid-level',
  senior: 'Senior',
  lead: 'Lead',
}
const EMPLOYMENT_LABELS: Record<string, string> = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  contract: 'Contract',
  internship: 'Internship',
}

/** Display label for an extracted value; null for unknown or missing values. */
export function workModeLabel(value: string | null | undefined): string | null {
  return value ? (WORK_MODE_LABELS[value] ?? null) : null
}
export function seniorityLabel(value: string | null | undefined): string | null {
  return value ? (SENIORITY_LABELS[value] ?? null) : null
}
export function employmentLabel(value: string | null | undefined): string | null {
  return value ? (EMPLOYMENT_LABELS[value] ?? null) : null
}

const CURRENCY_SYMBOLS: Record<string, string> = { USD: '$', EUR: '€', GBP: '£', CAD: 'C$', AUD: 'A$', INR: '₹', BDT: '৳', SEK: 'kr ' }
const PERIOD_LABELS: Record<string, string> = {
  hour: 'hour',
  day: 'day',
  week: 'week',
  month: 'month',
  year: 'year',
}
const MAX_SALARY_TEXT = 42

function compactAmount(amount: number): string {
  if (amount >= 1_000_000) return `${trimZero(amount / 1_000_000)}M`
  if (amount >= 1_000) return `${trimZero(amount / 1_000)}k`
  return trimZero(amount)
}

function trimZero(value: number): string {
  return value.toFixed(1).replace(/\.0$/, '')
}

function amountRange(salary: Salary): string | null {
  const symbol = salary.currency ? (CURRENCY_SYMBOLS[salary.currency] ?? `${salary.currency} `) : ''
  const { min_amount: min, max_amount: max } = salary
  if (min != null && max != null && min !== max) {
    return `${symbol}${compactAmount(min)} – ${symbol}${compactAmount(max)}`
  }
  const single = min ?? max
  if (single == null) return null
  return min == null ? `Up to ${symbol}${compactAmount(single)}` : `${symbol}${compactAmount(single)}`
}

/** "$4k – $6k / month" from the extraction, else the posting's own salary text, else null. */
export function formatSalary(job: Pick<Job, 'extracted' | 'salary_text'>): string | null {
  const salary = job.extracted?.salary
  const range = salary ? amountRange(salary) : null
  if (range && salary) {
    const period = salary.period ? PERIOD_LABELS[salary.period] : null
    return period ? `${range} / ${period}` : range
  }
  const text = job.salary_text?.trim()
  if (!text) return null
  return text.length > MAX_SALARY_TEXT ? `${text.slice(0, MAX_SALARY_TEXT - 1)}…` : text
}

const MONTHS_PER_PERIOD: Record<string, number> = {
  hour: 160,
  day: 21,
  week: 52 / 12,
  month: 1,
  year: 1 / 12,
}

/**
 * Monthly amount in USD for client-side salary filtering, or null when the salary is not in
 * USD or has no period (amounts in other currencies are not converted).
 */
export function monthlyUsd(salary: Salary | null | undefined): number | null {
  if (!salary || salary.currency !== 'USD' || !salary.period) return null
  const factor = MONTHS_PER_PERIOD[salary.period]
  const amount = salary.max_amount ?? salary.min_amount
  if (factor === undefined || amount == null) return null
  return amount * factor
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** "just now", "5m ago", "3h ago", "2d ago", then a short date. */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return ''
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const diff = Math.max(0, now - then)
  if (diff < MINUTE) return 'just now'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)}d ago`
  return new Date(then).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** The date a job was posted, or first seen when the source gave none. */
export function jobDate(job: Pick<Job, 'published_at' | 'first_seen_at'>): string {
  return job.published_at ?? job.first_seen_at
}

/** A 0..1 score as a whole percentage. */
export function percent(score: number): number {
  return Math.round(Math.min(1, Math.max(0, score)) * 100)
}

export type MatchTier = 'strong' | 'good' | 'fair'

export function matchTier(score: number): MatchTier {
  if (score >= 0.85) return 'strong'
  if (score >= 0.7) return 'good'
  return 'fair'
}

const numberFormat = new Intl.NumberFormat('en-US')

export function formatCount(value: number): string {
  return numberFormat.format(value)
}

/** Time-of-day greeting for the dashboard heading. */
export function greeting(date: Date = new Date()): string {
  const hour = date.getHours()
  if (hour < 5) return 'Good evening'
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

/** The job's original listing URL when it is a plain http(s) link, else null. */
export function externalUrl(job: Pick<Job, 'url'>): string | null {
  if (!job.url) return null
  try {
    const { protocol } = new URL(job.url)
    return protocol === 'http:' || protocol === 'https:' ? job.url : null
  } catch {
    return null
  }
}

/** "Berlin, DE" style location from the job or its extraction. */
export function jobLocation(job: Pick<Job, 'location' | 'extracted'>): string | null {
  if (job.location?.trim()) return job.location.trim()
  const parts = [job.extracted?.city, job.extracted?.country].filter(Boolean)
  return parts.length ? parts.join(', ') : null
}
