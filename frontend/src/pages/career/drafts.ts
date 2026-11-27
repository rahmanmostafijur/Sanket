import type {
  CareerListInputs,
  CareerListKey,
  EducationInput,
  ExperienceInput,
  LanguageProficiency,
  ProjectInput,
  SkillInput,
} from '@/api/types'
import { MAX_ROWS, TEXT_LIMITS } from './limits'
import {
  validateCertifications,
  validateEducation,
  validateExperience,
  validateLanguages,
  validateProjects,
  validateSkills,
} from './validate'
import type { FieldErrors, FieldInfo } from './fieldErrors'

/** A language row while it is edited: the level may still be unchosen. */
export interface LanguageDraft {
  name: string
  proficiency: LanguageProficiency | ''
}

/** A certification row while it is edited: the year is what the input holds. */
export interface CertificationDraft {
  title: string
  issuer: string
  year: string
  url: string
}

export interface DraftOf {
  education: EducationInput
  experience: ExperienceInput
  skills: SkillInput
  languages: LanguageDraft
  certifications: CertificationDraft
  projects: ProjectInput
}

/** Everything the generic list section needs to know about one list section. */
export interface SectionModel<K extends CareerListKey> {
  key: K
  maxRows: number
  /** Fields in the order they appear in a row, for the order of "first invalid" and the summary line. */
  fields: readonly FieldInfo[]
  blank: () => DraftOf[K]
  toDraft: (item: CareerListInputs[K]) => DraftOf[K]
  toInput: (draft: DraftOf[K]) => CareerListInputs[K]
  /** Trims text and cuts it to the API's limits, for rows that did not come from the user's own typing. */
  clean: (draft: DraftOf[K]) => DraftOf[K]
  validate: (rows: readonly DraftOf[K][]) => FieldErrors
  /** What makes two rows the same entry: compared ignoring case. */
  dedupeKey: (draft: DraftOf[K]) => string
  /** Whether a row from a CV says enough to be worth showing for review. */
  isUsable: (draft: DraftOf[K]) => boolean
}

/** Trims every limited text field and cuts it to its limit. */
function cutText<T extends object>(draft: T, limits: Readonly<Record<string, number>>): T {
  const next = { ...draft } as Record<string, unknown>
  for (const [field, max] of Object.entries(limits)) {
    const value = next[field]
    if (typeof value === 'string') next[field] = value.trim().slice(0, max)
  }
  return next as T
}

function trimmed<T extends object>(draft: T): T {
  const next = { ...draft } as Record<string, unknown>
  for (const [field, value] of Object.entries(next)) if (typeof value === 'string') next[field] = value.trim()
  return next as T
}

const joined = (...parts: string[]): string => parts.map((part) => part.trim().toLowerCase()).join('|')

const PROFICIENCIES: readonly string[] = ['basic', 'conversational', 'fluent', 'native']
const LEVELS: readonly string[] = ['beginner', 'intermediate', 'advanced', 'expert']

export const EDUCATION: SectionModel<'education'> = {
  key: 'education',
  maxRows: MAX_ROWS.education,
  fields: [
    { key: 'institution', label: 'Institution' },
    { key: 'degree', label: 'Degree' },
    { key: 'field', label: 'Field of study' },
    { key: 'start', label: 'Start' },
    { key: 'end', label: 'End' },
    { key: 'grade', label: 'Grade' },
  ],
  blank: () => ({ institution: '', degree: '', field: '', start: '', end: null, grade: '' }),
  toDraft: (item) => ({ institution: item.institution, degree: item.degree, field: item.field, start: item.start, end: item.end, grade: item.grade }),
  toInput: (draft) => ({ ...trimmed(draft), end: draft.end?.trim() || null }),
  clean: (draft) => cutText(draft, TEXT_LIMITS.education),
  validate: (rows) => validateEducation(rows),
  dedupeKey: (draft) => joined(draft.institution, draft.degree),
  isUsable: (draft) => draft.institution.trim() !== '',
}

export const EXPERIENCE: SectionModel<'experience'> = {
  key: 'experience',
  maxRows: MAX_ROWS.experience,
  fields: [
    { key: 'company', label: 'Company' },
    { key: 'title', label: 'Job title' },
    { key: 'start', label: 'Start' },
    { key: 'end', label: 'End' },
    { key: 'description', label: 'Description' },
  ],
  blank: () => ({ company: '', title: '', start: '', end: null, current: false, description: '' }),
  toDraft: (item) => ({ company: item.company, title: item.title, start: item.start, end: item.end, current: item.current, description: item.description }),
  // A role that is still held has no end, whatever the input held before the switch was turned on.
  toInput: (draft) => ({ ...trimmed(draft), end: draft.current ? null : draft.end?.trim() || null }),
  clean: (draft) => cutText(draft, TEXT_LIMITS.experience),
  validate: (rows) => validateExperience(rows),
  dedupeKey: (draft) => joined(draft.company, draft.title, draft.start),
  isUsable: (draft) => draft.company.trim() !== '' || draft.title.trim() !== '',
}

export const SKILLS: SectionModel<'skills'> = {
  key: 'skills',
  maxRows: MAX_ROWS.skills,
  fields: [
    { key: 'name', label: 'Skill' },
    { key: 'level', label: 'Level' },
  ],
  blank: () => ({ name: '', level: null }),
  toDraft: (item) => ({ name: item.name, level: item.level }),
  toInput: (draft) => ({ ...trimmed(draft) }),
  clean: (draft) => {
    const next = cutText(draft, TEXT_LIMITS.skills)
    return LEVELS.includes(next.level ?? '') ? next : { ...next, level: null }
  },
  validate: (rows) => validateSkills(rows),
  dedupeKey: (draft) => joined(draft.name),
  isUsable: (draft) => draft.name.trim() !== '',
}

export const LANGUAGES: SectionModel<'languages'> = {
  key: 'languages',
  maxRows: MAX_ROWS.languages,
  fields: [
    { key: 'name', label: 'Language' },
    { key: 'proficiency', label: 'Level' },
  ],
  blank: () => ({ name: '', proficiency: '' }),
  toDraft: (item) => ({ name: item.name, proficiency: item.proficiency }),
  toInput: (draft) => ({ name: draft.name.trim(), proficiency: draft.proficiency === '' ? 'basic' : draft.proficiency }),
  clean: (draft) => {
    const next = cutText(draft, TEXT_LIMITS.languages)
    return PROFICIENCIES.includes(next.proficiency) ? next : { ...next, proficiency: '' }
  },
  validate: (rows) => validateLanguages(rows),
  dedupeKey: (draft) => joined(draft.name),
  isUsable: (draft) => draft.name.trim() !== '',
}

export const CERTIFICATIONS: SectionModel<'certifications'> = {
  key: 'certifications',
  maxRows: MAX_ROWS.certifications,
  fields: [
    { key: 'title', label: 'Name' },
    { key: 'issuer', label: 'Issuer' },
    { key: 'year', label: 'Year' },
    { key: 'url', label: 'Link' },
  ],
  blank: () => ({ title: '', issuer: '', year: '', url: '' }),
  toDraft: (item) => ({ title: item.title, issuer: item.issuer, year: item.year === null ? '' : String(item.year), url: item.url }),
  toInput: (draft) => {
    const year = draft.year.trim()
    return { title: draft.title.trim(), issuer: draft.issuer.trim(), year: year ? Number(year) : null, url: draft.url.trim() }
  },
  clean: (draft) => cutText(draft, TEXT_LIMITS.certifications),
  validate: (rows) => validateCertifications(rows),
  dedupeKey: (draft) => joined(draft.title, draft.issuer),
  isUsable: (draft) => draft.title.trim() !== '',
}

export const PROJECTS: SectionModel<'projects'> = {
  key: 'projects',
  maxRows: MAX_ROWS.projects,
  fields: [
    { key: 'title', label: 'Name' },
    { key: 'description', label: 'Description' },
    { key: 'url', label: 'Link' },
  ],
  blank: () => ({ title: '', description: '', url: '' }),
  toDraft: (item) => ({ title: item.title, description: item.description, url: item.url }),
  toInput: (draft) => ({ ...trimmed(draft) }),
  clean: (draft) => cutText(draft, TEXT_LIMITS.projects),
  validate: (rows) => validateProjects(rows),
  dedupeKey: (draft) => joined(draft.title),
  isUsable: (draft) => draft.title.trim() !== '',
}

export const MODELS: { [K in CareerListKey]: SectionModel<K> } = {
  education: EDUCATION,
  experience: EXPERIENCE,
  skills: SKILLS,
  languages: LANGUAGES,
  certifications: CERTIFICATIONS,
  projects: PROJECTS,
}
