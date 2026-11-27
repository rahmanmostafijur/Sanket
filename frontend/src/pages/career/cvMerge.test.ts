import type { Career, CvProposal } from '@/api/types'
import { emptyCareer } from '@/test/careerApi'
import { CERTIFICATIONS, EDUCATION, EXPERIENCE, LANGUAGES, PROJECTS, SKILLS } from './drafts'
import { mergeList, mergePersonal, proposalCounts, withoutSection } from './cvMerge'

const NO_PERSONAL: CvProposal['personal'] = { full_name: '', headline: '', summary: '', country: '', city: '', github_url: '', linkedin_url: '', portfolio_url: '' }
const NOTHING: CvProposal = { personal: NO_PERSONAL, education: [], experience: [], skills: [], languages: [], certifications: [], projects: [] }

const CURRENT = { ...emptyCareer().personal, full_name: 'Ada Example', headline: 'Backend engineer', city: 'Berlin' }

describe('mergePersonal', () => {
  it('keeps every value when the CV states nothing', () => {
    const merge = mergePersonal(CURRENT, NO_PERSONAL)

    expect(merge.value).toEqual(CURRENT)
    expect(merge.filled).toEqual([])
  })

  it('writes over only the fields the CV states, trimmed, and keeps availability', () => {
    const merge = mergePersonal({ ...CURRENT, availability: 'open_to_offers' }, { ...NO_PERSONAL, headline: '  Platform engineer ', country: 'de' })

    expect(merge.value).toEqual({ ...CURRENT, headline: 'Platform engineer', country: 'DE', availability: 'open_to_offers' })
    expect(merge.filled).toEqual(['headline', 'country'])
  })

  it('does not count a value that is already there, and drops a country that is not a code', () => {
    const merge = mergePersonal(CURRENT, { ...NO_PERSONAL, full_name: 'Ada Example', country: 'Germany' })

    expect(merge.filled).toEqual([])
  })

  it('cuts text to the length the API accepts', () => {
    expect(mergePersonal(CURRENT, { ...NO_PERSONAL, headline: 'x'.repeat(200) }).value.headline).toHaveLength(120)
  })
})

describe('mergeList', () => {
  const saved = [{ institution: 'Example University', degree: 'BSc', field: '', start: '2015-09', end: '2019-06', grade: '' }]

  it('appends rows that are new and keeps every saved row first', () => {
    const merge = mergeList(EDUCATION, saved, [
      { institution: 'Sample College', degree: 'MSc', field: '', start: '2019-09', end: null, grade: '' },
    ])

    expect(merge.added).toBe(1)
    expect(merge.rows).toHaveLength(2)
    expect(merge.rows[0]).toBe(saved[0])
    expect(merge.rows[1]?.institution).toBe('Sample College')
  })

  it('skips an education row with the same institution and degree, ignoring case', () => {
    const merge = mergeList(EDUCATION, saved, [{ institution: ' example university ', degree: 'bsc', field: 'Maths', start: '2010-01', end: null, grade: '' }])

    expect(merge.added).toBe(0)
    expect(merge.rows).toEqual(saved)
  })

  it('treats the same institution with another degree as a different entry', () => {
    expect(mergeList(EDUCATION, saved, [{ institution: 'Example University', degree: 'MSc', field: '', start: '2019-09', end: null, grade: '' }]).added).toBe(1)
  })

  it('dedupes experience on company, title and start', () => {
    const job = { company: 'Example Ltd', title: 'Engineer', start: '2019-07', end: null, current: true, description: '' }
    const merge = mergeList(EXPERIENCE, [job], [{ ...job, company: 'EXAMPLE LTD', description: 'new text' }, { ...job, start: '2021-01' }])

    expect(merge.added).toBe(1)
    expect(merge.rows[1]?.start).toBe('2021-01')
  })

  it('dedupes skills and languages by name, and repeats inside the CV itself', () => {
    expect(mergeList(SKILLS, [{ name: 'Python', level: null }], [{ name: 'python', level: 'expert' }, { name: 'Go', level: null }, { name: 'GO', level: null }]).added).toBe(1)
    expect(mergeList(LANGUAGES, [{ name: 'English', proficiency: 'native' }], [{ name: 'english', proficiency: 'fluent' }, { name: 'German', proficiency: 'basic' }]).added).toBe(1)
  })

  it('dedupes certifications on title and issuer, and projects on title', () => {
    const cert = { title: 'Cloud practitioner', issuer: 'Example Institute', year: 2022, url: '' }

    expect(mergeList(CERTIFICATIONS, [CERTIFICATIONS.toDraft(cert)], [{ ...cert, year: 2023 }, { ...cert, issuer: 'Other' }]).added).toBe(1)
    expect(mergeList(PROJECTS, [{ title: 'Crawler', description: '', url: '' }], [{ title: 'crawler', description: 'x', url: '' }]).added).toBe(0)
  })

  it('drops rows that say nothing, cleans the rest and leaves a language level unchosen when it is unknown', () => {
    const merge = mergeList(LANGUAGES, [], [
      { name: '  ', proficiency: 'basic' },
      { name: ' French ', proficiency: 'perfect' as never },
    ])

    expect(merge.rows).toEqual([{ name: 'French', proficiency: '' }])
  })

  it('stops at the section row limit', () => {
    const current = Array.from({ length: 14 }, (_, i) => ({ name: `Language ${i}`, proficiency: 'basic' as const }))
    const merge = mergeList(LANGUAGES, current, [{ name: 'A', proficiency: 'basic' }, { name: 'B', proficiency: 'basic' }])

    expect(merge.rows).toHaveLength(15)
    expect(merge.added).toBe(1)
  })

  it('does not change what it was given', () => {
    const before = structuredClone(saved)
    mergeList(EDUCATION, saved, [{ institution: 'Sample College', degree: '', field: '', start: '2019-09', end: null, grade: '' }])

    expect(saved).toEqual(before)
  })
})

describe('proposalCounts and withoutSection', () => {
  const career: Career = { ...emptyCareer(), personal: CURRENT, skills: [{ id: 1, name: 'Python', level: null }] }
  const proposal: CvProposal = {
    ...NOTHING,
    personal: { ...NO_PERSONAL, full_name: 'Grace Sample', headline: 'Backend engineer' },
    skills: [{ name: 'Python', level: null }, { name: 'Go', level: null }],
    projects: [{ title: 'Crawler', description: '', url: '' }],
  }

  it('counts what each section would take, and leaves out sections with nothing new', () => {
    expect(proposalCounts(career, proposal)).toEqual({ personal: 1, skills: 1, projects: 1 })
  })

  it('removes one section from a proposal and no other', () => {
    const rest = withoutSection(withoutSection(proposal, 'skills'), 'personal')

    expect(rest.skills).toEqual([])
    expect(rest.personal.full_name).toBe('')
    expect(rest.projects).toEqual(proposal.projects)
    expect(proposal.skills).toHaveLength(2)
  })
})
