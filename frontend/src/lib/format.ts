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

const CURRENCY_SYMBOLS: Record<string, string> = { USD: '$', EUR: '€', GBP: '£', INR: '₹', BDT: '৳' }
type PayPeriod = 'hour' | 'day' | 'week' | 'month' | 'year'
/** Period words as sources and the extraction write them, mapped to one noun. */
const PERIOD_ALIASES: Record<string, PayPeriod> = {
  hour: 'hour', hours: 'hour', hourly: 'hour', hr: 'hour', 'per-hour-wage': 'hour',
  day: 'day', days: 'day', daily: 'day',
  week: 'week', weeks: 'week', weekly: 'week',
  month: 'month', months: 'month', monthly: 'month', mo: 'month',
  year: 'year', years: 'year', yearly: 'year', annual: 'year', annually: 'year', annum: 'year', yr: 'year', 'per-year-salary': 'year',
}
const MAX_SALARY_TEXT = 42
/** Posting text such as "115000-165000 USD per annual" or "36-43 USD per hourly". */
const PLAIN_SALARY_TEXT = /^(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s+([A-Za-z]{3})(?:\s+per\s+(\S+))?$/

/** "year" for yearly, annual, annually, per-year-salary and the like; null when unrecognised. */
export function payPeriod(value: string | null | undefined): PayPeriod | null {
  if (!value) return null
  return PERIOD_ALIASES[value.trim().toLowerCase()] ?? null
}

function compactAmount(amount: number): string {
  if (amount >= 1_000_000) return `${trimZero(amount / 1_000_000)}M`
  if (amount >= 1_000) return `${trimZero(amount / 1_000)}k`
  return String(Math.round(amount * 100) / 100)
}

function trimZero(value: number): string {
  return value.toFixed(1).replace(/\.0$/, '')
}

function money(currency: string | null, amount: number): string {
  const code = currency?.toUpperCase() ?? null
  if (!code) return compactAmount(amount)
  const symbol = CURRENCY_SYMBOLS[code]
  return symbol ? `${symbol}${compactAmount(amount)}` : `${code} ${compactAmount(amount)}`
}

function amountRange(salary: Salary): string | null {
  const { min_amount: min, max_amount: max, currency } = salary
  if (min != null && max != null && min !== max) return `${money(currency, min)}–${money(currency, max)}`
  const single = min ?? max
  if (single == null) return null
  return min == null ? `Up to ${money(currency, single)}` : money(currency, single)
}

function withPeriod(range: string, period: string | null | undefined): string {
  const noun = payPeriod(period)
  return noun ? `${range} / ${noun}` : range
}

/** The posting's own salary text, tidied when it is the plain "min-max CUR per period" form. */
function salaryFromText(text: string): string {
  const parsed = PLAIN_SALARY_TEXT.exec(text)
  if (parsed) {
    const [, low, high, currency, period] = parsed
    const range = amountRange({ min_amount: Number(low), max_amount: high ? Number(high) : Number(low), currency: currency ?? null, period: null })
    if (range && (!period || payPeriod(period))) return withPeriod(range, period)
  }
  return text.length > MAX_SALARY_TEXT ? `${text.slice(0, MAX_SALARY_TEXT - 1)}…` : text
}

/** "$220k–$290k / year" from the extraction, else the posting's own salary text, else null. */
export function formatSalary(job: Pick<Job, 'extracted' | 'salary_text'>): string | null {
  const salary = job.extracted?.salary
  const range = salary ? amountRange(salary) : null
  if (range && salary) return withPeriod(range, salary.period)
  const text = job.salary_text?.trim()
  return text ? salaryFromText(text) : null
}

const MONTHS_PER_PERIOD: Record<PayPeriod, number> = {
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
  if (!salary || salary.currency !== 'USD') return null
  const period = payPeriod(salary.period)
  const amount = salary.max_amount ?? salary.min_amount
  if (period === null || amount == null) return null
  return amount * MONTHS_PER_PERIOD[period]
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
