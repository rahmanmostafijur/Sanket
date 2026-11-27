import { ApiError, errorMessage } from '@/api/client'
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, retrySeconds } from '@/lib/auth'

export const WRONG_CREDENTIALS = 'Incorrect email or password.'
export const EMAIL_TAKEN = 'An account with this email already exists.'
const INVALID_EMAIL = 'Enter a valid email address, like name@example.com.'
const INVALID_PASSWORD = `Use between ${PASSWORD_MIN_LENGTH} and ${PASSWORD_MAX_LENGTH} characters.`
const ACCOUNTS_OFF = 'Email sign-in is not available on this Sanket service.'

/** What went wrong with a sign-in or sign-up request, split into the field it belongs to. */
export interface AuthFailure {
  form: string | null
  email: string | null
  password: string | null
  /** The email already has an account: the page offers a link to sign in. */
  emailTaken: boolean
}

const NONE: AuthFailure = { form: null, email: null, password: null, emailTaken: false }

/** Seconds-to-wait message for a 429, from its `Retry-After` when the server sent one. */
export function tooManyAttempts(retryAfterMs: number | null): string {
  const seconds = retrySeconds(retryAfterMs)
  if (seconds === null) return 'Too many attempts. Try again in a moment.'
  return `Too many attempts. Try again in ${seconds} second${seconds === 1 ? '' : 's'}.`
}

function validationFailure(error: ApiError): AuthFailure {
  const fields = new Set(error.details.map((detail) => detail.loc?.[detail.loc.length - 1]))
  const email = fields.has('email') ? INVALID_EMAIL : null
  const password = fields.has('password') ? INVALID_PASSWORD : null
  return { ...NONE, email, password, form: email || password ? null : error.message }
}

/** Maps a failed sign-in or sign-up to messages. A wrong email and a wrong password read the same. */
export function authFailure(error: unknown): AuthFailure {
  if (!(error instanceof ApiError)) return { ...NONE, form: errorMessage(error) }
  if (error.status === 401) return { ...NONE, form: WRONG_CREDENTIALS }
  if (error.status === 409) return { ...NONE, email: EMAIL_TAKEN, emailTaken: true }
  if (error.status === 429) return { ...NONE, form: tooManyAttempts(error.retryAfterMs) }
  if (error.status === 422) return validationFailure(error)
  if (error.status === 404 && !error.isUnavailable) return { ...NONE, form: ACCOUNTS_OFF }
  return { ...NONE, form: errorMessage(error) }
}
