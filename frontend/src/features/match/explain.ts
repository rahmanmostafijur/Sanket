import type { FilterState, MatchComponents } from '@/api/types'
import { percent } from '@/lib/format'

/**
 * Plain-language reasons from a match's `components` (backend/src/sanket/matching/score.py).
 * Only what the scorer recorded is described; nothing is estimated.
 */

export interface ScorePart {
  key: 'cosine' | 'skills' | 'title'
  label: string
  value: number
  weight: number
}

const FILTER_LABELS: Record<string, string> = {
  seniority: 'Seniority',
  work_mode: 'Work mode',
  employment_type: 'Employment type',
  country: 'Country',
  required_skills: 'Required skills',
}

export function scoreParts(components: MatchComponents): ScorePart[] {
  const parts: ScorePart[] = []
  if (components.cosine) parts.push({ key: 'cosine', label: 'Semantic fit', value: components.cosine.part, weight: components.cosine.weight })
  if (components.skills?.part != null) parts.push({ key: 'skills', label: 'Skills', value: components.skills.part, weight: components.skills.weight })
  if (components.title?.part != null) parts.push({ key: 'title', label: 'Title', value: components.title.part, weight: components.title.weight })
  return parts
}

export interface FilterRow {
  key: string
  label: string
  state: FilterState
}

/** The hard filters the profile set (filters the profile left open are omitted). */
export function filterRows(components: MatchComponents): FilterRow[] {
  return Object.entries(components.filters ?? {})
    .filter((entry): entry is [string, FilterState] => entry[1] !== undefined && entry[1] !== 'na')
    .map(([key, state]) => ({ key, label: FILTER_LABELS[key] ?? key, state }))
}

function list(items: readonly string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

export function explainMatch(components: MatchComponents): string[] {
  const reasons: string[] = []
  const skills = components.skills
  if (skills?.required_hits.length) reasons.push(`It asks for ${list(skills.required_hits)}, which your profile requires.`)
  if (skills?.preferred_hits.length) reasons.push(`It also lists ${list(skills.preferred_hits)} from your preferred skills.`)
  if (skills && !skills.job_skills_known) reasons.push('The posting names no skills, so skills did not count against it.')
  if (components.title?.best && components.title.part != null && components.title.part > 0) {
    reasons.push(`The title is close to “${components.title.best}”, one of the roles you want.`)
  }
  if (components.cosine) reasons.push(`Overall, the posting reads ${percent(components.cosine.value)}% similar to your profile summary and goals.`)
  const passed = filterRows(components).filter((row) => row.state === 'pass').map((row) => row.label.toLowerCase())
  if (passed.length) reasons.push(`It fits your ${list(passed)} preferences.`)
  if (components.location_match === true) reasons.push('Its location is one you listed.')
  return reasons
}

export function cautions(components: MatchComponents): string[] {
  const notes: string[] = []
  const missing = components.skills?.required_missing ?? []
  if (missing.length) notes.push(`Not mentioned in the posting: ${list(missing)}.`)
  const unknown = (components.unknown_fields ?? []).map((field) => (FILTER_LABELS[field] ?? field).toLowerCase())
  if (unknown.length) notes.push(`The posting does not say its ${list(unknown)}, so those filters were not applied.`)
  if (components.location_match === false) notes.push('Its location is not one you listed.')
  return notes
}
