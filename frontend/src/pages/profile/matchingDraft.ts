import type { MatchingDraft, ProfileWrite, Seniority } from '@/api/types'
import { SENIORITIES } from '@/api/types'
import { LIMITS } from './limits'

/** The router location state a page passes to the matching page to open it with a draft. */
export const DRAFT_STATE_KEY = 'matchingDraft'

/** The form fields a draft fills, which the form marks "Filled". */
export type DraftField = 'desired_titles' | 'required_skills' | 'preferred_skills' | 'seniorities' | 'locations'

const DRAFT_FIELDS: readonly DraftField[] = ['desired_titles', 'required_skills', 'preferred_skills', 'seniorities', 'locations']

function isStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

/** The draft in a router location state, or null when there is none or it is not shaped like one. */
export function readDraft(state: unknown): MatchingDraft | null {
  if (typeof state !== 'object' || state === null) return null
  const raw = (state as Record<string, unknown>)[DRAFT_STATE_KEY]
  if (typeof raw !== 'object' || raw === null) return null
  const draft = raw as Record<string, unknown>
  if (!DRAFT_FIELDS.every((field) => isStrings(draft[field]))) return null
  const years = draft.years_of_experience
  return {
    desired_titles: draft.desired_titles as string[],
    required_skills: draft.required_skills as string[],
    preferred_skills: draft.preferred_skills as string[],
    seniorities: (draft.seniorities as string[]).filter((item): item is Seniority => (SENIORITIES as readonly string[]).includes(item) && item !== 'unknown'),
    locations: draft.locations as string[],
    years_of_experience: typeof years === 'number' ? years : null,
  }
}

const CAPS: Record<'desired_titles' | 'required_skills' | 'preferred_skills' | 'locations', number> = {
  desired_titles: LIMITS.titles,
  required_skills: LIMITS.required,
  preferred_skills: LIMITS.preferred,
  locations: LIMITS.locations,
}

/** Trimmed entries without repeats (ignoring case), cut to what the form accepts. */
function usable(items: readonly string[], max: number): string[] {
  const seen = new Set<string>()
  const kept: string[] = []
  for (const raw of items) {
    const item = raw.trim()
    if (!item || seen.has(item.toLowerCase())) continue
    seen.add(item.toLowerCase())
    kept.push(item)
  }
  return kept.slice(0, max)
}

/** The form with the draft's lists written in. Name, active flag and the rest stay as they are. */
export function applyDraft(form: ProfileWrite, draft: MatchingDraft): ProfileWrite {
  const next = { ...form }
  for (const field of Object.keys(CAPS) as (keyof typeof CAPS)[]) {
    const items = usable(draft[field], CAPS[field])
    if (items.length) next[field] = items
  }
  const seniorities = [...new Set(draft.seniorities)]
  if (seniorities.length) next.seniorities = seniorities
  return next
}

/** The fields `applyDraft` fills. */
export function draftFields(draft: MatchingDraft): DraftField[] {
  return DRAFT_FIELDS.filter((field) => {
    const value = draft[field]
    return field === 'seniorities' ? value.length > 0 : usable(value, CAPS[field as keyof typeof CAPS]).length > 0
  })
}
