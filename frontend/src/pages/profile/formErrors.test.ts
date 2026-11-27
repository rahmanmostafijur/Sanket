import { ApiError } from '@/api/client'
import type { ProfileWrite } from '@/api/types'
import {
  CONTENT_ERROR,
  clearFixed,
  defaultProfileName,
  errorSummary,
  errorsFromServer,
  firstInvalid,
  profileNameFor,
  validateProfile,
} from './formErrors'

const FORM: ProfileWrite = {
  name: '',
  active: true,
  desired_titles: [],
  required_skills: [],
  preferred_skills: [],
  seniorities: [],
  work_modes: [],
  employment_types: [],
  countries: [],
  locations: [],
  summary: '',
  min_score_override: null,
}

function invalid(...details: { loc: (string | number)[]; msg: string }[]): ApiError {
  return new ApiError(422, 'validation_error', 'the request is invalid', null, null, details)
}

describe('validateProfile', () => {
  it('never asks for a name, because it has a default', () => {
    expect(validateProfile({ ...FORM, name: '', summary: 'Backend roles' })).toEqual({})
  })

  it('asks for something to match on, at the first field that can hold it', () => {
    expect(validateProfile(FORM)).toEqual({ 'profile.desired_titles': CONTENT_ERROR })
  })

  it.each([
    ['a role', { desired_titles: ['Backend Engineer'] }],
    ['a required skill', { required_skills: ['Python'] }],
    ['a preferred skill', { preferred_skills: ['Docker'] }],
    ['a summary', { summary: 'Backend roles' }],
  ])('accepts %s alone', (_name, changes) => {
    expect(validateProfile({ ...FORM, ...changes })).toEqual({})
  })

  it('does not count a blank summary', () => {
    expect(validateProfile({ ...FORM, summary: '   ' })).toEqual({ 'profile.desired_titles': CONTENT_ERROR })
  })

  it('flags a summary over the limit on the summary field', () => {
    expect(Object.keys(validateProfile({ ...FORM, summary: 'x'.repeat(2001) }))).toEqual(['profile.summary'])
  })
})

describe('errorsFromServer', () => {
  it('maps each detail to the profile field it names', () => {
    const error = invalid({ loc: ['body', 'name'], msg: 'taken' }, { loc: ['body', 'summary'], msg: 'bad' })

    expect(errorsFromServer(error)).toEqual({ 'profile.name': 'taken', 'profile.summary': 'bad' })
  })

  it('leaves out what names no known field, and anything that is not an API error', () => {
    expect(errorsFromServer(invalid({ loc: ['body'], msg: 'whole body' }, { loc: ['body', 'nope'], msg: 'x' }))).toEqual({})
    expect(errorsFromServer(new Error('boom'))).toEqual({})
  })
})

describe('firstInvalid and errorSummary', () => {
  it('picks the first field in page order, whatever order the errors were found in', () => {
    const errors = { 'profile.summary': 'a', 'profile.locations': 'b', 'profile.name': 'c' }

    expect(firstInvalid(errors)).toBe('profile.name')
    expect(firstInvalid({})).toBeNull()
  })

  it('says which fields to fix, in page order', () => {
    expect(errorSummary({ 'profile.summary': 'a', 'profile.desired_titles': 'b' })).toBe('Please fix these fields: Preferred roles, What you are looking for.')
    expect(errorSummary({ 'profile.name': 'a' })).toBe('Please fix this field: Profile name.')
    expect(errorSummary({})).toBeNull()
  })
})

describe('clearFixed', () => {
  const errors = { 'profile.desired_titles': CONTENT_ERROR, 'profile.name': 'too long' }

  it('drops the error of the field that changed and keeps the others', () => {
    expect(clearFixed(errors, 'profile.name', FORM)).toEqual({ 'profile.desired_titles': CONTENT_ERROR })
  })

  it('drops the "something to match" error once any field that can hold it has content', () => {
    const cases: [string, Partial<ProfileWrite>][] = [
      ['profile.required_skills', { required_skills: ['Python'] }],
      ['profile.summary', { summary: 'Backend roles' }],
      ['profile.preferred_skills', { preferred_skills: ['Docker'] }],
    ]
    for (const [field, changes] of cases) {
      expect(clearFixed(errors, field, { ...FORM, ...changes })).toEqual({ 'profile.name': 'too long' })
    }
  })

  it('keeps that error while the fields are still empty, and returns the same object when nothing changed', () => {
    expect(clearFixed(errors, 'profile.summary', FORM)).toBe(errors)
    expect(clearFixed(errors, 'profile.locations', FORM)).toBe(errors)
  })
})

describe('profile name', () => {
  it('uses the headline, else "My profile"', () => {
    expect(defaultProfileName('Staff engineer', [])).toBe('Staff engineer')
    expect(defaultProfileName('  Staff \n engineer  ', [])).toBe('Staff engineer')
    expect(defaultProfileName('', [])).toBe('My profile')
    expect(defaultProfileName('   ', [])).toBe('My profile')
  })

  it('adds a number when the name is taken, ignoring case', () => {
    expect(defaultProfileName('', ['My profile'])).toBe('My profile 2')
    expect(defaultProfileName('', ['my PROFILE', 'My profile 2'])).toBe('My profile 3')
    expect(defaultProfileName('Staff engineer', ['Staff engineer'])).toBe('Staff engineer 2')
  })

  it('stays within the 100 character limit, suffix included', () => {
    const long = 'a'.repeat(150)

    expect(defaultProfileName(long, [])).toHaveLength(100)
    expect(defaultProfileName(long, ['a'.repeat(100)])).toHaveLength(100)
    expect(defaultProfileName(long, ['a'.repeat(100)]).endsWith(' 2')).toBe(true)
  })

  it('keeps a name the user typed, even when it is taken', () => {
    expect(profileNameFor('  Python backend  ', 'Staff engineer', ['Python backend'])).toBe('Python backend')
    expect(profileNameFor('', 'Staff engineer', [])).toBe('Staff engineer')
  })
})
