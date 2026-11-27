import type { Availability, CareerSectionKey, LanguageProficiency, SkillLevel } from '@/api/types'

export const AVAILABILITY_OPTIONS: readonly { value: Availability; label: string }[] = [
  { value: 'immediately', label: 'Available immediately' },
  { value: 'within_one_month', label: 'Available within one month' },
  { value: 'open_to_offers', label: 'Open to offers' },
  { value: 'not_looking', label: 'Not looking' },
]

export const SKILL_LEVEL_OPTIONS: readonly { value: SkillLevel; label: string }[] = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
  { value: 'expert', label: 'Expert' },
]

export const PROFICIENCY_OPTIONS: readonly { value: LanguageProficiency; label: string }[] = [
  { value: 'basic', label: 'Basic' },
  { value: 'conversational', label: 'Conversational' },
  { value: 'fluent', label: 'Fluent' },
  { value: 'native', label: 'Native' },
]

export function labelOf<T extends string>(options: readonly { value: T; label: string }[], value: T | null | ''): string {
  return options.find((option) => option.value === value)?.label ?? ''
}

/** Where each section is edited, and what to call it. Skills and languages share a page, as do certifications and projects. */
export const SECTION_META: Record<CareerSectionKey, { label: string; path: string }> = {
  personal: { label: 'Personal', path: '/profile/personal' },
  education: { label: 'Education', path: '/profile/education' },
  experience: { label: 'Experience', path: '/profile/experience' },
  skills: { label: 'Skills', path: '/profile/skills' },
  languages: { label: 'Languages', path: '/profile/skills' },
  certifications: { label: 'Certifications', path: '/profile/accomplishments' },
  projects: { label: 'Projects', path: '/profile/accomplishments' },
}

/** The English name of a two-letter country code, or null when there is none. */
export function countryName(code: string): string | null {
  const upper = code.trim().toUpperCase()
  if (!/^[A-Z]{2}$/.test(upper)) return null
  try {
    const name = new Intl.DisplayNames(['en'], { type: 'region' }).of(upper)
    return name && name !== upper ? name : null
  } catch {
    return null
  }
}

/** Years of experience as the draft banner and the overview say them: "6.5 years", "1 year". */
export function formatYears(years: number): string {
  const rounded = Math.round(years * 10) / 10
  return `${rounded} ${rounded === 1 ? 'year' : 'years'}`
}
