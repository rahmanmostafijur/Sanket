import { ApiError } from '@/api/client'
import type { CvProposal, PersonalInfo, ProfileWrite } from '@/api/types'
import { checkCvFile, cvImportMessage, filledFields, mergePersonal, mergeProfile } from './cvProposal'

const NONE: CvProposal = {
  personal: { full_name: '', headline: '', location: '', summary: '' },
  profile: {
    desired_titles: [],
    required_skills: [],
    preferred_skills: [],
    seniorities: [],
    work_modes: [],
    employment_types: [],
    countries: [],
    locations: [],
    summary: '',
  },
}

const PERSON: PersonalInfo = { full_name: 'Grace Sample', headline: 'Platform engineer', location: 'Dhaka', summary: 'Keeps systems up.' }

const PROFILE: ProfileWrite = {
  name: 'Python backend',
  active: false,
  desired_titles: ['Backend Engineer'],
  required_skills: ['Python'],
  preferred_skills: [],
  seniorities: ['mid'],
  work_modes: [],
  employment_types: [],
  countries: ['DE'],
  locations: [],
  summary: 'My own words',
  min_score_override: 0.7,
}

describe('mergePersonal', () => {
  it('keeps every current value when the CV states nothing', () => {
    expect(mergePersonal(PERSON, NONE.personal)).toEqual(PERSON)
  })

  it('replaces only the fields the CV states, trimmed', () => {
    const merged = mergePersonal(PERSON, { ...NONE.personal, full_name: '  Ada Example ', summary: '   ' })
    expect(merged).toEqual({ ...PERSON, full_name: 'Ada Example' })
  })

  it('cuts text to the length the API accepts', () => {
    expect(mergePersonal(PERSON, { ...NONE.personal, headline: 'x'.repeat(500) }).headline).toHaveLength(120)
  })
})

describe('mergeProfile', () => {
  it('keeps the form when the CV states nothing', () => {
    expect(mergeProfile(PROFILE, NONE.profile)).toEqual(PROFILE)
  })

  it('replaces non-empty lists and the summary, and leaves name, active flag and threshold alone', () => {
    const merged = mergeProfile(PROFILE, {
      ...NONE.profile,
      desired_titles: ['Platform Engineer', 'SRE'],
      seniorities: ['senior'],
      summary: 'Platform roles',
    })
    expect(merged).toEqual({
      ...PROFILE,
      desired_titles: ['Platform Engineer', 'SRE'],
      seniorities: ['senior'],
      summary: 'Platform roles',
    })
  })

  it('drops what the form cannot hold: repeats, unknown enum values and bad country codes', () => {
    const merged = mergeProfile(PROFILE, {
      ...NONE.profile,
      required_skills: ['Go', 'go', ' Docker '],
      work_modes: ['unknown'],
      countries: ['bd', 'Germany', 'BD'],
    })
    expect(merged.required_skills).toEqual(['Go', 'Docker'])
    expect(merged.work_modes).toEqual([])
    expect(merged.countries).toEqual(['BD'])
  })

  it('caps a list at what the API accepts', () => {
    const titles = Array.from({ length: 15 }, (_, index) => `Role ${index}`)
    expect(mergeProfile(PROFILE, { ...NONE.profile, desired_titles: titles }).desired_titles).toHaveLength(10)
  })

  it('does not change the object it was given', () => {
    const copy = structuredClone(PROFILE)
    mergeProfile(PROFILE, { ...NONE.profile, desired_titles: ['SRE'] })
    expect(PROFILE).toEqual(copy)
  })
})

describe('filledFields', () => {
  it('lists only the stated fields', () => {
    const proposal: CvProposal = { personal: { ...NONE.personal, full_name: 'Ada Example' }, profile: { ...NONE.profile, desired_titles: ['SRE'] } }
    expect(filledFields(proposal, true)).toEqual(['personal.full_name', 'profile.desired_titles'])
  })

  it('leaves personal details out when there is no account to put them in', () => {
    const proposal: CvProposal = { personal: { ...NONE.personal, full_name: 'Ada Example' }, profile: NONE.profile }
    expect(filledFields(proposal, false)).toEqual([])
  })
})

describe('checkCvFile', () => {
  it('accepts PDF and DOCX in any letter case', () => {
    expect(checkCvFile(new File(['x'], 'cv.PDF'))).toBeNull()
    expect(checkCvFile(new File(['x'], 'cv.docx'))).toBeNull()
  })

  it('rejects other types', () => {
    expect(checkCvFile(new File(['x'], 'cv.doc'))).toBe('Only PDF and DOCX files are supported.')
    expect(checkCvFile(new File(['x'], 'cv.pdf.txt'))).toBe('Only PDF and DOCX files are supported.')
  })

  it('rejects a file over 5 MB but accepts exactly 5 MB', () => {
    const file = (size: number) => Object.defineProperty(new File(['x'], 'cv.pdf'), 'size', { value: size })
    expect(checkCvFile(file(5 * 1024 * 1024))).toBeNull()
    expect(checkCvFile(file(5 * 1024 * 1024 + 1))).toBe('That file is larger than 5 MB.')
  })
})

describe('cvImportMessage', () => {
  const failure = (status: number, retryAfterMs: number | null = null, message = 'server text') => new ApiError(status, 'x', message, null, retryAfterMs)

  it('explains each failure', () => {
    expect(cvImportMessage(failure(413))).toBe('That file is larger than 5 MB.')
    expect(cvImportMessage(failure(422, null, 'The PDF has no text; it looks scanned.'))).toBe('The PDF has no text; it looks scanned.')
    expect(cvImportMessage(failure(429, 12_000))).toBe('Too many imports. Try again in 12 seconds.')
    expect(cvImportMessage(failure(429, 1_000))).toBe('Too many imports. Try again in 1 second.')
    expect(cvImportMessage(failure(503, 150_000))).toBe('The language model is unavailable right now (quota). Try again in 3 minutes.')
    expect(cvImportMessage(failure(503))).toBe('The language model is unavailable right now (quota). Try again later.')
  })

  it('falls back to one generic line for anything else', () => {
    expect(cvImportMessage(failure(502))).toBe('Could not read the CV. Try again.')
    expect(cvImportMessage(new ApiError(0, 'network_error', 'Could not connect'))).toBe('Could not read the CV. Try again.')
    expect(cvImportMessage(new Error('boom'))).toBe('Could not read the CV. Try again.')
  })
})
