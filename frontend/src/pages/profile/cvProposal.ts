import { ApiError } from '@/api/client'
import type { CvProposal, PersonalInfo, ProfileWrite } from '@/api/types'
import { retrySeconds } from '@/lib/auth'
import { LIMITS, PERSONAL_LIMITS } from './limits'
import { PERSONAL_KEYS } from './personalInfo'

export const CV_MAX_BYTES = 5 * 1024 * 1024
export const CV_ACCEPT = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export const CV_PRIVACY_NOTE = 'Your CV text is sent to the language-model provider to read it. The file and its text are not stored.'

const PROFILE_LIST_KEYS = [
  'desired_titles',
  'required_skills',
  'preferred_skills',
  'seniorities',
  'work_modes',
  'employment_types',
  'countries',
  'locations',
] as const

type PersonalKey = (typeof PERSONAL_KEYS)[number]
type ProfileKey = 'summary' | (typeof PROFILE_LIST_KEYS)[number]

/** A form field the CV filled: `personal.<key>` or `profile.<key>`. */
export type FilledField = `personal.${PersonalKey}` | `profile.${ProfileKey}`

const ENUM_KEYS: ReadonlySet<string> = new Set(['seniorities', 'work_modes', 'employment_types'])

const LIST_MAX: Record<(typeof PROFILE_LIST_KEYS)[number], number> = {
  desired_titles: LIMITS.titles,
  required_skills: LIMITS.required,
  preferred_skills: LIMITS.preferred,
  seniorities: 6,
  work_modes: 4,
  employment_types: 5,
  countries: LIMITS.countries,
  locations: LIMITS.locations,
}

/** Error text for a file that must not be sent, or null. The server still checks the content. */
export function checkCvFile(file: File): string | null {
  if (!/\.(pdf|docx)$/i.test(file.name)) return 'Only PDF and DOCX files are supported.'
  if (file.size > CV_MAX_BYTES) return 'That file is larger than 5 MB.'
  return null
}

function text(value: string, max: number): string {
  return value.trim().slice(0, max)
}

/** Entries the form can hold: trimmed, no repeats, country codes upper-cased, no "unknown" enum value. */
function list<T extends string>(key: (typeof PROFILE_LIST_KEYS)[number], value: readonly T[]): T[] {
  const seen = new Set<string>()
  const items: T[] = []
  for (const raw of value) {
    const item = (key === 'countries' ? raw.trim().toUpperCase() : raw.trim()) as T
    const usable = key === 'countries' ? /^[A-Z]{2}$/.test(item) : item !== '' && !(ENUM_KEYS.has(key) && item === 'unknown')
    if (!usable || seen.has(item.toLowerCase())) continue
    seen.add(item.toLowerCase())
    items.push(item)
  }
  return items.slice(0, LIST_MAX[key])
}

/** Personal details with every field the CV stated replaced; empty means "not stated", so the current value stays. */
export function mergePersonal(current: PersonalInfo, proposed: PersonalInfo): PersonalInfo {
  const next = { ...current }
  for (const key of PERSONAL_KEYS) {
    const value = text(proposed[key], PERSONAL_LIMITS[key])
    if (value) next[key] = value
  }
  return next
}

/** The profile with every list or summary the CV stated replaced. Name and active flag are never touched. */
export function mergeProfile(current: ProfileWrite, proposed: CvProposal['profile']): ProfileWrite {
  const next = { ...current }
  const summary = text(proposed.summary, LIMITS.summary)
  if (summary) next.summary = summary
  for (const key of PROFILE_LIST_KEYS) {
    const items = list(key, proposed[key])
    if (items.length) Object.assign(next, { [key]: items })
  }
  return next
}

/** Which fields `mergePersonal` and `mergeProfile` would fill. Personal details are left out when there is no account. */
export function filledFields(proposal: CvProposal, withPersonal: boolean): FilledField[] {
  const fields: FilledField[] = []
  if (withPersonal) {
    for (const key of PERSONAL_KEYS) if (proposal.personal[key].trim()) fields.push(`personal.${key}`)
  }
  if (proposal.profile.summary.trim()) fields.push('profile.summary')
  for (const key of PROFILE_LIST_KEYS) if (list(key, proposal.profile[key]).length) fields.push(`profile.${key}`)
  return fields
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? '' : 's'}`
}

/** A human message for a failed import. */
export function cvImportMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Could not read the CV. Try again.'
  const seconds = retrySeconds(error.retryAfterMs)
  switch (error.status) {
    case 413:
      return 'That file is larger than 5 MB.'
    case 422:
      return error.message || 'Could not read that file. Use a text-based PDF or DOCX.'
    case 429:
      return seconds === null ? 'Too many imports. Try again in a moment.' : `Too many imports. Try again in ${plural(seconds, 'second')}.`
    case 503:
      return seconds === null
        ? 'The language model is unavailable right now (quota). Try again later.'
        : `The language model is unavailable right now (quota). Try again in ${plural(Math.ceil(seconds / 60), 'minute')}.`
    default:
      return 'Could not read the CV. Try again.'
  }
}
