import type { CareerPersonal, EducationInput, ExperienceInput, ProjectInput, SkillInput } from '@/api/types'
import type { CertificationDraft, LanguageDraft } from './drafts'
import { rowKey, type FieldErrors } from './fieldErrors'
import { MIN_CERTIFICATION_YEAR, PERSONAL_LIMITS, TEXT_LIMITS } from './limits'
import { currentMonth, isMonth } from './months'

const COUNTRY_CODE = /^[A-Za-z]{2}$/
const SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i
const HTTP_SCHEME = /^https?:\/\//i

const tooLong = (max: number) => `Use at most ${max} characters.`

/** An error for text that is too long, or null. */
function length(value: string, max: number): string | null {
  return value.trim().length > max ? tooLong(max) : null
}

function required(value: string, message: string): string | null {
  return value.trim() ? null : message
}

/**
 * An error for a link that is not an http(s) address, or null. A link typed without a scheme is
 * fine: the API adds https://. `domain` limits the host to that site and its subdomains.
 */
export function checkUrl(value: string, domain?: string): string | null {
  const text = value.trim()
  if (!text) return null
  if (text.length > PERSONAL_LIMITS.url) return tooLong(PERSONAL_LIMITS.url)
  if (/\s/.test(text)) return 'Enter a web address without spaces.'
  if (SCHEME.test(text) && !HTTP_SCHEME.test(text)) return 'Use an address that starts with http:// or https://.'
  let host: string
  try {
    host = new URL(SCHEME.test(text) ? text : `https://${text}`).hostname.toLowerCase()
  } catch {
    return 'Enter a valid web address.'
  }
  if (!host.includes('.')) return 'Enter a valid web address.'
  if (domain && host !== domain && !host.endsWith(`.${domain}`)) return `Use a ${domain} address.`
  return null
}

function collect(errors: FieldErrors, key: string, message: string | null): void {
  if (message) errors[key] = message
}

export function validatePersonal(personal: CareerPersonal): FieldErrors {
  const errors: FieldErrors = {}
  collect(errors, 'full_name', length(personal.full_name, PERSONAL_LIMITS.full_name))
  collect(errors, 'headline', length(personal.headline, PERSONAL_LIMITS.headline))
  collect(errors, 'summary', length(personal.summary, PERSONAL_LIMITS.summary))
  collect(errors, 'city', length(personal.city, PERSONAL_LIMITS.city))
  const country = personal.country.trim()
  if (country && !COUNTRY_CODE.test(country)) errors.country = 'Use a two-letter country code, such as DE.'
  collect(errors, 'github_url', checkUrl(personal.github_url, 'github.com'))
  collect(errors, 'linkedin_url', checkUrl(personal.linkedin_url, 'linkedin.com'))
  collect(errors, 'portfolio_url', checkUrl(personal.portfolio_url))
  return errors
}

/** An error for a month that is missing (when `needed`), malformed, or (unless `allowFuture`) ahead of today. */
function checkMonth(value: string | null, needed: boolean, now: Date, allowFuture: boolean): string | null {
  const text = (value ?? '').trim()
  if (!text) return needed ? 'Add a month.' : null
  if (!isMonth(text)) return 'Use the format YYYY-MM, for example 2019-07.'
  if (!allowFuture && text > currentMonth(now)) return 'This month is in the future.'
  return null
}

const END_BEFORE_START = 'The end must not be before the start.'

function endBeforeStart(start: string, end: string | null): string | null {
  return end && isMonth(start) && isMonth(end) && end < start ? END_BEFORE_START : null
}

export function validateEducation(rows: readonly EducationInput[], now: Date = new Date()): FieldErrors {
  const limits = TEXT_LIMITS.education
  const errors: FieldErrors = {}
  rows.forEach((row, i) => {
    collect(errors, rowKey(i, 'institution'), required(row.institution, 'Add the institution.') ?? length(row.institution, limits.institution))
    collect(errors, rowKey(i, 'degree'), length(row.degree, limits.degree))
    collect(errors, rowKey(i, 'field'), length(row.field, limits.field))
    collect(errors, rowKey(i, 'grade'), length(row.grade, limits.grade))
    collect(errors, rowKey(i, 'start'), checkMonth(row.start, true, now, true))
    collect(errors, rowKey(i, 'end'), checkMonth(row.end, false, now, true) ?? endBeforeStart(row.start, row.end))
  })
  return errors
}

export function validateExperience(rows: readonly ExperienceInput[], now: Date = new Date()): FieldErrors {
  const limits = TEXT_LIMITS.experience
  const errors: FieldErrors = {}
  rows.forEach((row, i) => {
    collect(errors, rowKey(i, 'company'), required(row.company, 'Add the company.') ?? length(row.company, limits.company))
    collect(errors, rowKey(i, 'title'), required(row.title, 'Add the job title.') ?? length(row.title, limits.title))
    collect(errors, rowKey(i, 'description'), length(row.description, limits.description))
    collect(errors, rowKey(i, 'start'), checkMonth(row.start, true, now, false))
    if (!row.current) collect(errors, rowKey(i, 'end'), checkMonth(row.end, true, now, false) ?? endBeforeStart(row.start, row.end))
  })
  return errors
}

/** The indexes of the second and later rows whose name repeats an earlier one, ignoring case. */
function repeatedNames(names: readonly string[]): number[] {
  const seen = new Set<string>()
  const repeats: number[] = []
  names.forEach((name, i) => {
    const key = name.trim().toLowerCase()
    if (!key) return
    if (seen.has(key)) repeats.push(i)
    seen.add(key)
  })
  return repeats
}

const REPEATED = 'This is already in the list.'

export function validateSkills(rows: readonly SkillInput[]): FieldErrors {
  const errors: FieldErrors = {}
  rows.forEach((row, i) => collect(errors, rowKey(i, 'name'), required(row.name, 'Add the skill.') ?? length(row.name, TEXT_LIMITS.skills.name)))
  for (const i of repeatedNames(rows.map((row) => row.name))) errors[rowKey(i, 'name')] ??= REPEATED
  return errors
}

export function validateLanguages(rows: readonly LanguageDraft[]): FieldErrors {
  const errors: FieldErrors = {}
  rows.forEach((row, i) => {
    collect(errors, rowKey(i, 'name'), required(row.name, 'Add the language.') ?? length(row.name, TEXT_LIMITS.languages.name))
    if (!row.proficiency) errors[rowKey(i, 'proficiency')] = 'Choose a level.'
  })
  for (const i of repeatedNames(rows.map((row) => row.name))) errors[rowKey(i, 'name')] ??= REPEATED
  return errors
}

export function validateCertifications(rows: readonly CertificationDraft[], now: Date = new Date()): FieldErrors {
  const limits = TEXT_LIMITS.certifications
  const maxYear = now.getFullYear() + 1
  const errors: FieldErrors = {}
  rows.forEach((row, i) => {
    collect(errors, rowKey(i, 'title'), required(row.title, 'Add the certification name.') ?? length(row.title, limits.title))
    collect(errors, rowKey(i, 'issuer'), length(row.issuer, limits.issuer))
    collect(errors, rowKey(i, 'url'), checkUrl(row.url))
    const year = row.year.trim()
    if (year && (!/^\d{4}$/.test(year) || Number(year) < MIN_CERTIFICATION_YEAR || Number(year) > maxYear)) {
      errors[rowKey(i, 'year')] = `Use a year from ${MIN_CERTIFICATION_YEAR} to ${maxYear}.`
    }
  })
  return errors
}

export function validateProjects(rows: readonly ProjectInput[]): FieldErrors {
  const limits = TEXT_LIMITS.projects
  const errors: FieldErrors = {}
  rows.forEach((row, i) => {
    collect(errors, rowKey(i, 'title'), required(row.title, 'Add the project name.') ?? length(row.title, limits.title))
    collect(errors, rowKey(i, 'description'), length(row.description, limits.description))
    collect(errors, rowKey(i, 'url'), checkUrl(row.url))
  })
  return errors
}
