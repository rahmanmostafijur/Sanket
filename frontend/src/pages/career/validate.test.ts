import type { CareerPersonal, EducationInput, ExperienceInput } from '@/api/types'
import type { CertificationDraft, LanguageDraft } from './drafts'
import { checkUrl, validateCertifications, validateEducation, validateExperience, validateLanguages, validatePersonal, validateProjects, validateSkills } from './validate'

const NOW = new Date(2026, 10, 28)

const PERSONAL: CareerPersonal = { full_name: 'Ada Example', headline: '', summary: '', country: '', city: '', github_url: '', linkedin_url: '', portfolio_url: '', availability: null }
const EDU: EducationInput = { institution: 'Example University', degree: '', field: '', start: '2015-09', end: '2019-06', grade: '' }
const JOB: ExperienceInput = { company: 'Example Ltd', title: 'Engineer', start: '2019-07', end: null, current: true, description: '' }

describe('checkUrl', () => {
  it('accepts an empty value, http(s) addresses and addresses without a scheme', () => {
    expect(checkUrl('')).toBeNull()
    expect(checkUrl('https://example.com/a')).toBeNull()
    expect(checkUrl('http://example.com')).toBeNull()
    expect(checkUrl('example.com/ada')).toBeNull()
  })

  it('rejects other schemes, spaces, a host without a dot and addresses over 300 characters', () => {
    expect(checkUrl('ftp://example.com')).toMatch(/http/)
    expect(checkUrl('example .com')).toMatch(/spaces/)
    expect(checkUrl('localhost')).toMatch(/valid/)
    expect(checkUrl(`https://example.com/${'a'.repeat(300)}`)).toBe('Use at most 300 characters.')
  })

  it('holds a link to its site, subdomains included', () => {
    expect(checkUrl('github.com/ada', 'github.com')).toBeNull()
    expect(checkUrl('https://www.linkedin.com/in/ada', 'linkedin.com')).toBeNull()
    expect(checkUrl('https://example.com/ada', 'github.com')).toBe('Use a github.com address.')
    expect(checkUrl('https://notgithub.com/ada', 'github.com')).toBe('Use a github.com address.')
  })
})

describe('validatePersonal', () => {
  it('accepts a minimal profile', () => {
    expect(validatePersonal(PERSONAL)).toEqual({})
  })

  it('flags text over its limit and a country that is not two letters', () => {
    const errors = validatePersonal({ ...PERSONAL, full_name: 'x'.repeat(101), headline: 'x'.repeat(121), summary: 'x'.repeat(1001), city: 'x'.repeat(101), country: 'DEU' })

    expect(Object.keys(errors).sort()).toEqual(['city', 'country', 'full_name', 'headline', 'summary'])
    expect(errors.full_name).toBe('Use at most 100 characters.')
  })

  it('checks each link against its own site', () => {
    const errors = validatePersonal({ ...PERSONAL, github_url: 'https://example.com/a', linkedin_url: 'github.com/a', portfolio_url: 'not a link' })

    expect(Object.keys(errors).sort()).toEqual(['github_url', 'linkedin_url', 'portfolio_url'])
  })
})

describe('validateEducation', () => {
  it('accepts a complete row and one with no end', () => {
    expect(validateEducation([EDU, { ...EDU, end: null }], NOW)).toEqual({})
  })

  it('requires the institution and the start, and keeps the end after the start', () => {
    const errors = validateEducation([{ ...EDU, institution: ' ', start: '' }, { ...EDU, end: '2015-08' }, { ...EDU, start: '2015/09' }], NOW)

    expect(errors['0.institution']).toBe('Add the institution.')
    expect(errors['0.start']).toBe('Add a month.')
    expect(errors['1.end']).toBe('The end must not be before the start.')
    expect(errors['2.start']).toMatch(/YYYY-MM/)
  })

  it('limits the text fields', () => {
    expect(Object.keys(validateEducation([{ ...EDU, institution: 'x'.repeat(151), degree: 'x'.repeat(101), field: 'x'.repeat(101), grade: 'x'.repeat(51) }], NOW)).sort()).toEqual([
      '0.degree',
      '0.field',
      '0.grade',
      '0.institution',
    ])
  })
})

describe('validateExperience', () => {
  it('needs no end for a current role', () => {
    expect(validateExperience([JOB], NOW)).toEqual({})
  })

  it('needs company, title and start, and an end unless the role is current', () => {
    const errors = validateExperience([{ ...JOB, company: '', title: '', start: '', current: false }], NOW)

    expect(Object.keys(errors).sort()).toEqual(['0.company', '0.end', '0.start', '0.title'])
  })

  it('keeps the end after the start and neither date in the future', () => {
    const errors = validateExperience([{ ...JOB, current: false, end: '2019-01' }, { ...JOB, start: '2027-01', current: false, end: '2027-02' }], NOW)

    expect(errors['0.end']).toBe('The end must not be before the start.')
    expect(errors['1.start']).toBe('This month is in the future.')
    expect(errors['1.end']).toBe('This month is in the future.')
  })

  it('accepts the current month', () => {
    expect(validateExperience([{ ...JOB, start: '2026-11', current: false, end: '2026-11' }], NOW)).toEqual({})
  })

  it('limits the description to 2000 characters', () => {
    expect(validateExperience([{ ...JOB, description: 'x'.repeat(2001) }], NOW)['0.description']).toBe('Use at most 2000 characters.')
  })
})

describe('validateSkills and validateLanguages', () => {
  it('flags the second of two skills with the same name, ignoring case', () => {
    expect(validateSkills([{ name: 'Python', level: null }, { name: ' python ', level: 'expert' }, { name: 'Go', level: null }])).toEqual({ '1.name': 'This is already in the list.' })
  })

  it('requires a skill name of at most 60 characters', () => {
    expect(validateSkills([{ name: '', level: null }, { name: 'x'.repeat(61), level: null }])).toEqual({ '0.name': 'Add the skill.', '1.name': 'Use at most 60 characters.' })
  })

  it('requires a language name and level, and no repeats', () => {
    const rows: LanguageDraft[] = [{ name: 'English', proficiency: 'native' }, { name: 'english', proficiency: '' }, { name: '', proficiency: 'basic' }]

    expect(validateLanguages(rows)).toEqual({ '1.name': 'This is already in the list.', '1.proficiency': 'Choose a level.', '2.name': 'Add the language.' })
  })
})

describe('validateCertifications and validateProjects', () => {
  const cert: CertificationDraft = { title: 'Cloud practitioner', issuer: '', year: '2022', url: '' }

  it('accepts a year from 1950 to next year and none at all', () => {
    expect(validateCertifications([cert, { ...cert, year: '' }, { ...cert, year: '1950' }, { ...cert, year: '2027' }], NOW)).toEqual({})
  })

  it('rejects a year out of range or not a number', () => {
    const errors = validateCertifications([{ ...cert, year: '1949' }, { ...cert, year: '2028' }, { ...cert, year: '20x2' }], NOW)

    expect(Object.keys(errors)).toEqual(['0.year', '1.year', '2.year'])
  })

  it('requires a title and checks the link and lengths', () => {
    expect(validateCertifications([{ ...cert, title: '', issuer: 'x'.repeat(101), url: 'ftp://a.b' }], NOW)).toEqual({
      '0.title': 'Add the certification name.',
      '0.issuer': 'Use at most 100 characters.',
      '0.url': 'Use an address that starts with http:// or https://.',
    })
  })

  it('requires a project title and limits the description to 1000 characters', () => {
    expect(validateProjects([{ title: '', description: 'x'.repeat(1001), url: '' }])).toEqual({ '0.title': 'Add the project name.', '0.description': 'Use at most 1000 characters.' })
  })
})
