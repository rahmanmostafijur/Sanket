import type { Me, PersonalInfo } from '@/api/types'

export const PERSONAL_KEYS = ['full_name', 'headline', 'location', 'summary'] as const

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
