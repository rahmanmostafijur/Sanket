import type { QueryClient } from '@tanstack/react-query'
import { IS_DEV } from '@/lib/env'
import { useSession } from '@/stores/session'

export const SIGN_IN_PATH = '/signin'
export const SIGN_UP_PATH = '/signup'
const AUTH_PATHS: ReadonlySet<string> = new Set([SIGN_IN_PATH, SIGN_UP_PATH])

export const EMAIL_MAX_LENGTH = 254
export const PASSWORD_MIN_LENGTH = 12
export const PASSWORD_MAX_LENGTH = 128
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Everything that belongs to the signed-in user: the credential, cached API data, the chosen profile. */
export function forgetSession(queryClient: QueryClient): void {
  const { clearToken, setActiveProfileId } = useSession.getState()
  clearToken()
  queryClient.clear()
  setActiveProfileId(null)
}

/**
 * Sign-in is enforced only in production builds. A development build can talk to an API running
 * with AUTH_DEV_BYPASS and has no credential, so a signed-out developer keeps working there.
 */
export function shouldRequireSignIn(token: string | null, isDev: boolean): boolean {
  return !isDev && !token
}

/** True for a visitor who is not signed in: public pages work, personal features ask them to sign in. */
export function useIsGuest(): boolean {
  const token = useSession((s) => s.token)
  return shouldRequireSignIn(token, IS_DEV)
}

export function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.has(pathname)
}

export interface ReturnLocation {
  pathname: string
  search?: string
  hash?: string
}

/** Where the user was heading before being sent to sign in: only an in-app path, never an auth page. */
export function destinationFrom(state: unknown, fallback = '/'): string {
  const from = typeof state === 'object' && state !== null && 'from' in state ? (state as { from: unknown }).from : null
  if (typeof from !== 'object' || from === null) return fallback
  const { pathname, search, hash } = from as { pathname?: unknown; search?: unknown; hash?: unknown }
  if (typeof pathname !== 'string' || !pathname.startsWith('/') || pathname.startsWith('//') || isAuthPath(pathname)) return fallback
  return `${pathname}${typeof search === 'string' ? search : ''}${typeof hash === 'string' ? hash : ''}`
}

/** The `from` state carried between the sign-in and sign-up pages, unchanged. */
export function fromState(state: unknown): { from: unknown } | undefined {
  return typeof state === 'object' && state !== null && 'from' in state ? { from: (state as { from: unknown }).from } : undefined
}

/** An inline message for an email address, or null when it looks usable. */
export function emailProblem(email: string): string | null {
  const value = email.trim()
  if (!value) return 'Enter your email address.'
  if (value.length > EMAIL_MAX_LENGTH || !EMAIL_PATTERN.test(value)) return 'Enter a valid email address, like name@example.com.'
  return null
}

/** An inline message for a new password, or null when it meets the length rules. */
export function passwordProblem(password: string): string | null {
  if (!password) return 'Enter a password.'
  if (password.length < PASSWORD_MIN_LENGTH) return `Use at least ${PASSWORD_MIN_LENGTH} characters.`
  if (password.length > PASSWORD_MAX_LENGTH) return `Use at most ${PASSWORD_MAX_LENGTH} characters.`
  return null
}

/** Seconds to wait, rounded up, from a `Retry-After` in milliseconds. */
export function retrySeconds(retryAfterMs: number | null): number | null {
  return retryAfterMs === null ? null : Math.max(1, Math.ceil(retryAfterMs / 1000))
}
