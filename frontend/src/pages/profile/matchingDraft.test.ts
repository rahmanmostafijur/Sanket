import type { MatchingDraft, ProfileWrite } from '@/api/types'
import { applyDraft, draftFields, DRAFT_STATE_KEY, readDraft } from './matchingDraft'

const FORM: ProfileWrite = {
  name: 'Python backend',
  active: false,
  desired_titles: [],
  required_skills: ['Old skill'],
  preferred_skills: [],
  seniorities: [],
  work_modes: ['remote'],
  employment_types: [],
  countries: ['DE'],
  locations: [],
  summary: 'Typed by hand',
  min_score_override: 0.5,
}

const DRAFT: MatchingDraft = {
  desired_titles: ['Backend Engineer', ' backend engineer ', 'Platform Engineer'],
  required_skills: ['Python', 'Go'],
  preferred_skills: [],
  seniorities: ['mid', 'senior'],
  locations: ['Berlin'],
  years_of_experience: 6.5,
}

describe('readDraft', () => {
  it('reads a draft from the router state', () => {
    expect(readDraft({ [DRAFT_STATE_KEY]: DRAFT })).toEqual(DRAFT)
  })

  it('has none when the state is empty or not shaped like a draft', () => {
    expect(readDraft(null)).toBeNull()
    expect(readDraft({ from: '/x' })).toBeNull()
    expect(readDraft({ [DRAFT_STATE_KEY]: { desired_titles: 'Engineer' } })).toBeNull()
    expect(readDraft({ [DRAFT_STATE_KEY]: { ...DRAFT, locations: [1] } })).toBeNull()
  })

  it('keeps only seniorities the form can hold and a numeric experience figure', () => {
    const draft = readDraft({ [DRAFT_STATE_KEY]: { ...DRAFT, seniorities: ['senior', 'unknown', 'chief'], years_of_experience: 'many' } })

    expect(draft?.seniorities).toEqual(['senior'])
    expect(draft?.years_of_experience).toBeNull()
  })
})

describe('applyDraft', () => {
  it('writes the draft lists in, without repeats, and leaves everything else alone', () => {
    const next = applyDraft(FORM, DRAFT)

    expect(next.desired_titles).toEqual(['Backend Engineer', 'Platform Engineer'])
    expect(next.required_skills).toEqual(['Python', 'Go'])
    expect(next.seniorities).toEqual(['mid', 'senior'])
    expect(next.locations).toEqual(['Berlin'])
    expect(next.preferred_skills).toEqual([])
    expect(next).toMatchObject({ name: 'Python backend', active: false, work_modes: ['remote'], countries: ['DE'], summary: 'Typed by hand', min_score_override: 0.5 })
  })

  it('keeps the form lists where the draft has nothing', () => {
    expect(applyDraft(FORM, { ...DRAFT, required_skills: [] }).required_skills).toEqual(['Old skill'])
  })

  it('cuts a list to what the form accepts', () => {
    const titles = Array.from({ length: 15 }, (_, i) => `Title ${i}`)

    expect(applyDraft(FORM, { ...DRAFT, desired_titles: titles }).desired_titles).toHaveLength(10)
  })

  it('does not change the form it was given', () => {
    const before = structuredClone(FORM)
    applyDraft(FORM, DRAFT)

    expect(FORM).toEqual(before)
  })
})

describe('draftFields', () => {
  it('lists the fields the draft fills', () => {
    expect(draftFields({ ...DRAFT, preferred_skills: [], locations: [' '] })).toEqual(['desired_titles', 'required_skills', 'seniorities'])
  })
})
