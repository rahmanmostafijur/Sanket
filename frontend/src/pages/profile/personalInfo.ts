import { ApiError } from '@/api/client'
import type { Me, PersonalInfo } from '@/api/types'

export const PERSONAL_KEYS = ['full_name', 'headline', 'location', 'summary'] as const

export type PersonalErrors = Partial<Record<keyof PersonalInfo, string>>

export function personalFrom(me: Me | null): PersonalInfo {
  return {
    full_name: me?.full_name ?? '',
    headline: me?.headline ?? '',
    location: me?.location ?? '',
    summary: me?.summary ?? '',
  }
}

/** What is sent: every field trimmed. */
export function trimmedPersonal(info: PersonalInfo): PersonalInfo {
  return {
    full_name: info.full_name.trim(),
    headline: info.headline.trim(),
    location: info.location.trim(),
    summary: info.summary.trim(),
  }
}

export function personalChanged(info: PersonalInfo, stored: Me): boolean {
  const next = trimmedPersonal(info)
  return PERSONAL_KEYS.some((key) => next[key] !== stored[key])
}

/** The fields a validation error (422) points at, with the server's wording. */
export function personalErrorsFrom(error: unknown): PersonalErrors {
  const errors: PersonalErrors = {}
  if (!(error instanceof ApiError)) return errors
  for (const detail of error.details) {
    const field = detail.loc?.[detail.loc.length - 1]
    const key = PERSONAL_KEYS.find((candidate) => candidate === field)
    if (key && detail.msg) errors[key] = detail.msg
  }
  return errors
}
