import { ApiError } from '@/api/client'
import type { ProfileWrite } from '@/api/types'
import { LIMITS } from './limits'

/** Messages by field key: `personal.<field>` for the account's info, `profile.<field>` for the profile. */
export type FieldErrors = Record<string, string>
export type ErrorScope = 'personal' | 'profile'

/** The order the fields appear on the page, which is the order "first invalid" is judged in. */
export const FIELD_ORDER = [
  'personal.full_name',
  'personal.headline',
  'personal.location',
  'personal.summary',
  'profile.name',
  'profile.desired_titles',
  'profile.required_skills',
  'profile.preferred_skills',
  'profile.countries',
  'profile.locations',
  'profile.summary',
] as const

const LABELS: Record<string, string> = {
  'personal.full_name': 'Full name',
  'personal.headline': 'Headline',
  'personal.location': 'Location',
  'personal.summary': 'Short summary',
  'profile.name': 'Profile name',
  'profile.desired_titles': 'Preferred roles',
  'profile.required_skills': 'Required skills',
  'profile.preferred_skills': 'Preferred skills',
  'profile.countries': 'Countries',
  'profile.locations': 'Locations',
  'profile.summary': 'What you are looking for',
}

export const CONTENT_ERROR = 'Add at least a role, a skill or a summary so there is something to match.'
const CONTENT_FIELDS = ['profile.desired_titles', 'profile.required_skills', 'profile.preferred_skills', 'profile.summary']
const CONTENT_ERROR_FIELD = 'profile.desired_titles'

function hasContent(form: ProfileWrite): boolean {
  return form.desired_titles.length > 0 || form.required_skills.length > 0 || form.preferred_skills.length > 0 || form.summary.trim() !== ''
}

/** What is wrong with the profile part of the form, by field. The name is never required: it has a default. */
export function validateProfile(form: ProfileWrite): FieldErrors {
  const errors: FieldErrors = {}
  if (form.summary.length > LIMITS.summary) errors['profile.summary'] = `Use at most ${LIMITS.summary} characters.`
  else if (!hasContent(form)) errors[CONTENT_ERROR_FIELD] = CONTENT_ERROR
  return errors
}

/** The fields a 422 points at, with the server's wording. An error about the whole body has no field and is left out. */
export function errorsFromServer(error: unknown, scope: ErrorScope): FieldErrors {
  const errors: FieldErrors = {}
  if (!(error instanceof ApiError)) return errors
  for (const detail of error.details) {
    const field = detail.loc?.[detail.loc.length - 1]
    if (typeof field !== 'string' || !detail.msg) continue
    const key = `${scope}.${field}`
    if ((FIELD_ORDER as readonly string[]).includes(key)) errors[key] = detail.msg
  }
  return errors
}

export function firstInvalid(errors: FieldErrors): string | null {
  return FIELD_ORDER.find((key) => errors[key]) ?? null
}

/** One short line for the top of the form, or null when nothing is wrong. */
export function errorSummary(errors: FieldErrors): string | null {
  const labels = FIELD_ORDER.filter((key) => errors[key]).map((key) => LABELS[key])
  if (!labels.length) return null
  return `Please fix ${labels.length === 1 ? 'this field' : 'these fields'}: ${labels.join(', ')}.`
}

/** The errors that still stand after `changed` got a new value; `form` is the form with that value in it. */
export function clearFixed(errors: FieldErrors, changed: string, form: ProfileWrite): FieldErrors {
  const contentFixed = errors[CONTENT_ERROR_FIELD] === CONTENT_ERROR && CONTENT_FIELDS.includes(changed) && hasContent(form)
  if (!errors[changed] && !contentFixed) return errors
  const next = { ...errors }
  delete next[changed]
  if (contentFixed) delete next[CONTENT_ERROR_FIELD]
  return next
}

export const DEFAULT_PROFILE_NAME = 'My profile'

/** The headline, or "My profile", made unique among `taken` names by a number at the end. */
export function defaultProfileName(headline: string, taken: readonly string[]): string {
  const base = (headline.split(/\s+/).join(' ').trim() || DEFAULT_PROFILE_NAME).slice(0, LIMITS.name).trim()
  const used = new Set(taken.map((name) => name.trim().toLowerCase()))
  if (!used.has(base.toLowerCase())) return base
  for (let n = 2; ; n += 1) {
    const suffix = ` ${n}`
    const candidate = `${base.slice(0, LIMITS.name - suffix.length).trim()}${suffix}`
    if (!used.has(candidate.toLowerCase())) return candidate
  }
}

/** The name to save: what the user typed, else the default. A typed name is never changed. */
export function profileNameFor(name: string, headline: string, taken: readonly string[]): string {
  return name.trim() || defaultProfileName(headline, taken)
}
