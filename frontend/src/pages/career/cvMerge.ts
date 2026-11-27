import type { CareerListInputs, CareerListKey, CareerPersonal, CareerSectionKey, CvProposal } from '@/api/types'
import { MODELS, type DraftOf, type SectionModel } from './drafts'
import { PERSONAL_LIMITS } from './limits'

/** The personal fields a CV can fill; availability is never in a CV. */
export type CvPersonalField = keyof CvProposal['personal']

const PERSONAL_FIELDS: readonly CvPersonalField[] = ['full_name', 'headline', 'summary', 'country', 'city', 'github_url', 'linkedin_url', 'portfolio_url']

const LIMIT_OF: Record<CvPersonalField, number> = {
  full_name: PERSONAL_LIMITS.full_name,
  headline: PERSONAL_LIMITS.headline,
  summary: PERSONAL_LIMITS.summary,
  country: 2,
  city: PERSONAL_LIMITS.city,
  github_url: PERSONAL_LIMITS.url,
  linkedin_url: PERSONAL_LIMITS.url,
  portfolio_url: PERSONAL_LIMITS.url,
}

export interface PersonalMerge {
  value: CareerPersonal
  /** The fields the CV changed. */
  filled: CvPersonalField[]
}

/** A proposed value the form can hold: trimmed and cut to its limit; a country must be a two-letter code. */
function proposedText(field: CvPersonalField, raw: string): string {
  const text = raw.trim()
  if (field === 'country') return /^[A-Za-z]{2}$/.test(text) ? text.toUpperCase() : ''
  return text.slice(0, LIMIT_OF[field])
}

/**
 * The personal details with every field the CV states written over the current one. A field the
 * CV leaves empty keeps its value, and so does a field the CV agrees with.
 */
export function mergePersonal(current: CareerPersonal, proposed: CvProposal['personal']): PersonalMerge {
  const value = { ...current }
  const filled: CvPersonalField[] = []
  for (const field of PERSONAL_FIELDS) {
    const text = proposedText(field, proposed[field])
    if (!text || text === current[field].trim()) continue
    value[field] = text
    filled.push(field)
  }
  return { value, filled }
}

export interface ListMerge<K extends CareerListKey> {
  /** The current rows followed by the new ones. */
  rows: DraftOf[K][]
  /** How many rows were appended from the CV. */
  added: number
}

/**
 * The current rows with the CV's rows that are not already there appended, so nothing the user
 * saved is dropped. Rows count as the same entry by the section's own key, ignoring case.
 */
export function mergeList<K extends CareerListKey>(model: SectionModel<K>, current: readonly DraftOf[K][], proposed: readonly CareerListInputs[K][]): ListMerge<K> {
  const seen = new Set(current.map((row) => model.dedupeKey(row)))
  const room = Math.max(0, model.maxRows - current.length)
  const fresh: DraftOf[K][] = []
  for (const item of proposed) {
    const row = model.clean(model.toDraft(item))
    const key = model.dedupeKey(row)
    if (!model.isUsable(row) || seen.has(key)) continue
    seen.add(key)
    fresh.push(row)
  }
  const added = fresh.slice(0, room)
  return { rows: [...current, ...added], added: added.length }
}

/** How many fields or rows of each section a CV would add to what is saved now. */
export function proposalCounts(career: CareerListSource, proposal: CvProposal): Partial<Record<CareerSectionKey, number>> {
  const counts: Partial<Record<CareerSectionKey, number>> = {}
  const personal = mergePersonal(career.personal, proposal.personal).filled.length
  if (personal) counts.personal = personal
  for (const key of Object.keys(MODELS) as CareerListKey[]) {
    const added = addedRows(key, career, proposal)
    if (added) counts[key] = added
  }
  return counts
}

type CareerListSource = { personal: CareerPersonal } & { [K in CareerListKey]: readonly CareerListInputs[K][] }

function addedRows<K extends CareerListKey>(key: K, career: CareerListSource, proposal: CvProposal): number {
  const model: SectionModel<K> = MODELS[key]
  const saved = career[key] as readonly CareerListInputs[K][]
  return mergeList(model, saved.map((item) => model.toDraft(item)), proposal[key] as CareerListInputs[K][]).added
}

/** The proposal without what one section took or the user turned away. */
export function withoutSection(proposal: CvProposal, section: CareerSectionKey): CvProposal {
  if (section === 'personal') {
    return { ...proposal, personal: { full_name: '', headline: '', summary: '', country: '', city: '', github_url: '', linkedin_url: '', portfolio_url: '' } }
  }
  return { ...proposal, [section]: [] }
}
