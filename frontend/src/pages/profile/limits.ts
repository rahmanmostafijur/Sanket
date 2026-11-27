/** Limits from backend/src/sanket/profiles/criteria.py. */
export const LIMITS = { name: 100, titles: 10, required: 20, preferred: 30, locations: 10, countries: 20, summary: 2000 } as const

/** Limits of the account's personal details (`PUT /me`). */
export const PERSONAL_LIMITS = { full_name: 100, headline: 120, location: 100, summary: 600 } as const
